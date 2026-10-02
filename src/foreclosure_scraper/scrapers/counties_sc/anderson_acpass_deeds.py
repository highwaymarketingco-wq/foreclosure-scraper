"""Anderson County SC ACPASS deed search (deedmain.cgi / dedtypen.cgi) —
keyless, auth-free instrument-type sweep.

NOT the login-walled assessor module (``enrichment_acpass.py``, which hits
``asrmain.cgi`` / ``asrdetail1.cgi`` — Anderson's property tax/ASSESSMENT
search, gated behind ``ACPASS_EMAIL`` / ``ACPASS_PASSWORD``). This module
hits the REGISTER-OF-DEEDS "LAND SEARCH" form on the same ACPASS host
instead (``acpass.andersoncountysc.org/deeda.cgi?SearchType=L``), which
needs no account at all.

``robots.txt`` here is a bare ``Disallow: /``. Per the 2026-09-20 compliance
ruling (see ``CLAUDE.md``) that is a policy signal, not a technical wall —
no CAPTCHA, login, or WAF challenge sits in front of it — so fetching it
politely (rate-limited through the shared ``http_client``) is in scope.

Mechanics fully mapped 2026-08-03 in ``docs/enumeration_r4/r4_deed_mining.md``
and re-confirmed live 2026-10-01 against the real host:

- A ``QryType`` code is MANDATORY (an empty one returns a 0-row error page —
  there is no type-less date sweep).
- Search: ``POST deedmain.cgi`` with
  ``QrySrchType=L&QryName=&QryFromDate=MM/DD/YYYY&QryToDate=MM/DD/YYYY&QryType=NNN&Submit=Submit``.
- Hard 25 rows/page. The "More" button posts a DIFFERENT endpoint,
  ``dedtypen.cgi``, carrying hidden cursor fields
  (``searchtype``/``searchinstr``/``searchbegdate``/``searchenddate``/
  ``daten``/``instrnon``) lifted straight off the previous page.
- Detail: ``GET deddetail1.cgi?instryearnbr=L{year}{instr}`` — Inst #, File
  Date, Type, Book/Page (Amount is always blank at Anderson — confirmed
  across 8 sampled types including this one), a GRANTOR/GRANTEE party list,
  a free-text DESCRIPTION, and a "View Images" link (captured as a
  reference URL only; not fetched — downloading/OCR-ing the scanned image
  is a separate, larger project, see ``enrichment_doc_ocr.py``'s own scope).

Two instrument-type codes captured here (of the 144 total; see the doc above
for the full audited list — most codes return 0 rows for the distress types
this project cares about):

  **020 POA** — power of attorney. The GRANTOR is the PRINCIPAL (the person
  granting power — the one going absentee or losing capacity); the GRANTEE
  is the agent. Absentee/incapacity proxy signal, no sale clock.

  **195 COURT ORDER** — a mixed bag by description, captured by TYPE CODE
  (not by keyword), but includes ``ORDER ESTABLISHING/DETERMINING HEIRS``
  (a heir-property lead with the estate already judicially adjudicated —
  "the highest value per row on the whole board" per the research doc) and
  ``ORDER QUIET TITLE`` (a title-defect flag). Rows whose description does
  not mention HEIR get listing_type UNKNOWN rather than a confident
  classification — still captured, just not claimed as an estate lead.

No property address is carried by this index at all — ACPASS land-search
rows are INSTRUMENT-level (parties + book/page), not parcel-level.
``enrichment_resolve_name_to_property`` already exists for exactly this
shape (the same gap ``counties_nc.nc_ecourts_divorce`` has) and resolves
these by owner name downstream. No sale_date either — these are standing
legal-record events, not scheduled auctions — so the slug is whitelisted in
``main.DATELESS_OK_SOURCES``.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://acpass.andersoncountysc.org"
_FORM_URL = f"{_BASE}/deeda.cgi?SearchType=L"
_SEARCH_CGI = f"{_BASE}/deedmain.cgi"
_NEXT_CGI = f"{_BASE}/dedtypen.cgi"
_DETAIL_CGI = f"{_BASE}/deddetail1.cgi"

#: code -> human label. The live TYPE column already spells these out, but
#: this drives which codes get queried and is stamped into raw[] for a code
#: fetched with 0 rows (where the live label is never observed).
CODES: dict[str, str] = {"020": "POA", "195": "COURT ORDER"}

# Matches the 24-month probe window in docs/enumeration_r4/r4_deed_mining.md
# (020 is paged/high-volume there; 195 was "finite", 17 rows in 24 months as
# of 2026-08-03).
_LOOKBACK_DAYS = 730
# Hard safety cap on pagination per code: 25 rows/page, so this bounds a
# single code's sweep to 1,000 rows even if the real total has grown well
# past the research snapshot.
_MAX_PAGES_PER_CODE = 40
# Detail fetches are the expensive part (one GET per instrument). Cap the
# whole run so a surprise high-volume code can't turn this into an
# hours-long crawl.
_MAX_DETAIL_FETCHES = 400

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_ROW_SPLIT_RE = re.compile(r'name="instryearnbr"\s+value="(L\d+)"')
_TYPE_RE = re.compile(r'<div align="center">([^<]+)</div>')
_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")
_BOOKPAGE_RE = re.compile(r"(\d{4,6})(?:&nbsp;)+\s*(\d{3,6})")
_DESC_RE = re.compile(r"<strong>([^<]+)</strong>")

# The "More" button's hidden paging form. Real markup has a malformed
# attribute (confirmed live) — `value=240000520"` is missing its OPENING
# quote on `instrnon` — so that one field's regex tolerates either quoting.
_CURSOR_FIELD_RE = {
    "searchtype": re.compile(r'name="searchtype"\s+type="hidden"\s+value="([^"]*)"'),
    "searchinstr": re.compile(r'name="searchinstr"\s+type="hidden"\s+value="([^"]*)"'),
    "searchbegdate": re.compile(r'name="searchbegdate"\s+type="hidden"\s+value="([^"]*)"'),
    "searchenddate": re.compile(r'name="searchenddate"\s+type="hidden"\s+value="([^"]*)"'),
    "daten": re.compile(r'name="daten"\s+type="hidden"\s+value="([^"]*)"'),
    "instrnon": re.compile(r'name="instrnon"\s+type="hidden"\s+value="?([^">]*)"?>'),
}

# Institutional parties (the court, the county, the clerk's office) show up
# as both GRANTOR and GRANTEE on a COURT ORDER (the index cross-references
# both roles for searchability) — never the actual human subject of the
# order. Excluded when picking a lead name.
_INSTITUTIONAL_RE = re.compile(
    r"\b(COURT|PROBATE|COUNTY|STATE OF|CLERK|SHERIFF|MASTER IN EQUITY)\b", re.I
)


def _parse_search_rows(html: str) -> list[dict]:
    """Parse a deedmain.cgi / dedtypen.cgi result page into row dicts.

    Real markup is tag-soup `<font>`/`<div>` tables with no stable class
    names, so this is regex-driven (same house style as
    ``anderson_master_in_equity._parse_pdf``) rather than a DOM walk."""
    rows: list[dict] = []
    parts = _ROW_SPLIT_RE.split(html)
    # parts = [preamble, key0, chunk0, key1, chunk1, ...]
    for i in range(1, len(parts), 2):
        key = parts[i]
        chunk = parts[i + 1] if i + 1 < len(parts) else ""
        no_re = re.compile(r'deddetail1\.cgi\?instryearnbr=' + re.escape(key) + r'">(\d+)</a>')
        m_no = no_re.search(chunk)
        if not m_no:
            continue  # malformed/foreign chunk (e.g. the trailing paging form) — skip
        m_type = _TYPE_RE.search(chunk)
        m_date = _DATE_RE.search(chunk)
        m_bp = _BOOKPAGE_RE.search(chunk)
        m_desc = _DESC_RE.search(chunk)
        rows.append({
            "instr_key": key,
            "instr_no": m_no.group(1),
            "type": m_type.group(1).strip() if m_type else None,
            "file_date": m_date.group(1) if m_date else None,
            "book": m_bp.group(1) if m_bp else None,
            "page": m_bp.group(2) if m_bp else None,
            "description": re.sub(r"\s+", " ", m_desc.group(1)).strip() if m_desc else None,
            "detail_url": f"{_DETAIL_CGI}?instryearnbr={key}",
        })
    return rows


def _parse_cursor(html: str) -> dict[str, str] | None:
    """Pull the hidden dedtypen.cgi paging fields off a result page's 'More'
    form. None when there is no more-button block (last/only page) or any
    expected field is missing (safer to stop paging than to guess)."""
    if 'name="instrnon"' not in html:
        return None
    out: dict[str, str] = {}
    for field, rx in _CURSOR_FIELD_RE.items():
        m = rx.search(html)
        if not m:
            return None
        out[field] = m.group(1)
    return out


def _parse_detail(html: str) -> dict:
    """Parse a deddetail1.cgi instrument detail page: the GRANTOR/GRANTEE
    party list, the DESCRIPTION line, and the "View Images" URL if present.
    Amount is always blank at Anderson (confirmed across 8 sampled
    instrument types in docs/enumeration_r4/r4_deed_mining.md) so it is not
    extracted."""
    clean = re.sub(r"<[^>]+>", "\n", html)
    clean = clean.replace("&nbsp;", " ")
    lines = [ln.strip() for ln in clean.split("\n") if ln.strip()]

    parties: list[dict] = []
    for i, line in enumerate(lines):
        if line in ("GRANTOR", "GRANTEE") and i >= 1:
            name = lines[i - 1]
            if name and name != ":":
                parties.append({"name": name, "role": line})

    info: dict = {"parties": parties}
    for i, line in enumerate(lines):
        if line.upper() == "DESCRIPTION" and i + 1 < len(lines):
            val = lines[i + 1]
            if val and val.upper() != "IMAGES":
                info["description"] = val
            break

    m_img = re.search(r'href="(/pgms/rvimain\.pgm\?[^"]+)"', html)
    if m_img:
        href = m_img.group(1)
        info["image_url"] = f"{_BASE}{href}" if href.startswith("/") else href

    return info


def _subject_names(parties: list[dict], role_priority: tuple[str, ...]) -> list[str]:
    """Unique, non-institutional party names, preferring earlier roles in
    ``role_priority``."""
    seen: list[str] = []
    for role in role_priority:
        for p in parties:
            if p.get("role") != role:
                continue
            name = (p.get("name") or "").strip()
            if name and not _INSTITUTIONAL_RE.search(name) and name not in seen:
                seen.append(name)
    return seen


def _build_listing(slug: str, code: str, label: str, row: dict, detail: dict) -> Listing:
    parties = detail.get("parties", [])
    description = row.get("description") or detail.get("description")
    if code == "020":
        # The PRINCIPAL (GRANTOR) is the subject of interest, not the agent.
        names = _subject_names(parties, ("GRANTOR",))
        listing_type = ListingType.UNKNOWN
    else:  # "195" COURT ORDER
        names = _subject_names(parties, ("GRANTEE", "GRANTOR"))
        listing_type = (
            ListingType.ESTATE_LEAD if description and "HEIR" in description.upper()
            else ListingType.UNKNOWN
        )

    owner_name = "; ".join(names[:3]) if names else None

    return Listing(
        source=slug,
        source_url=row["detail_url"],
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Anderson",
        case_number=row.get("instr_no"),
        defendant=owner_name,
        owner_name=owner_name,
        legal_description=description,
        description=description,
        raw={
            "anderson_acpass": {
                "instr_key": row.get("instr_key"),
                "instr_no": row.get("instr_no"),
                "type_code": code,
                "type_label": row.get("type") or label,
                "file_date": row.get("file_date"),
                "book": row.get("book"),
                "page": row.get("page"),
                "parties": parties,
                "image_url": detail.get("image_url"),
            },
        },
    )


async def _fetch_type_code(c, code: str, from_str: str, to_str: str) -> list[dict]:
    """Run the date+type sweep for one code, following 'More' pagination."""
    resp = await c.post(
        _SEARCH_CGI,
        data={
            "QrySrchType": "L", "QryName": "",
            "QryFromDate": from_str, "QryToDate": to_str,
            "QryType": code, "Submit": "Submit",
        },
        headers={
            "Referer": _FORM_URL, "Origin": _BASE,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    if resp.status_code != 200:
        log.warning("anderson_acpass.search_failed", code=code, status=resp.status_code)
        return []

    rows = _parse_search_rows(resp.text)
    cursor = _parse_cursor(resp.text)
    pages = 1
    while cursor and pages < _MAX_PAGES_PER_CODE:
        resp = await c.post(
            _NEXT_CGI, data=cursor,
            headers={
                "Referer": _SEARCH_CGI, "Origin": _BASE,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if resp.status_code != 200:
            break
        new_rows = _parse_search_rows(resp.text)
        if not new_rows:
            break
        rows.extend(new_rows)
        cursor = _parse_cursor(resp.text)
        pages += 1
    return rows


class AndersonAcpassDeeds(BaseScraper):
    slug = "counties_sc.anderson_acpass_deeds"
    name = "Anderson County (SC) ACPASS deed search (POA + Court Order)"
    category = "county_rod"
    timeout_s = 240.0
    # 195 COURT ORDER alone was a thin 17 rows / 24 months as of 2026-08-03 —
    # too thin to set a nonzero floor without false-flagging a quiet month.
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        today = datetime.utcnow()
        from_str = (today - timedelta(days=_LOOKBACK_DAYS)).strftime("%m/%d/%Y")
        to_str = today.strftime("%m/%d/%Y")
        detail_budget = _MAX_DETAIL_FETCHES

        async with client(timeout=30.0, headers={"User-Agent": _UA}) as c:
            for code, label in CODES.items():
                try:
                    rows = await _fetch_type_code(c, code, from_str, to_str)
                except Exception:
                    log.warning("anderson_acpass.code_fetch_error", code=code)
                    continue

                for row in rows:
                    detail: dict = {}
                    if detail_budget > 0:
                        detail_budget -= 1
                        try:
                            dr = await c.get(row["detail_url"], headers={"Referer": _SEARCH_CGI})
                            if dr.status_code == 200:
                                detail = _parse_detail(dr.text)
                        except Exception:
                            pass
                    out.append(_build_listing(self.slug, code, label, row, detail))
                self.partial = list(out)

        log.info("anderson_acpass.done", total=len(out))
        return out
