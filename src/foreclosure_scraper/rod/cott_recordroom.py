"""Cott Systems "RecordRoom" Register-of-Deeds adapter (browserless, free).

Distinct from rod/cott.py (which handles the older cotthosting.com / Manatron
ASP.NET portals for NC Polk/Rutherford). RecordRoom is the newer
recordroom.cottsystems.com app with a DataTables JSON results endpoint. Guest
access to the INDEX is fully open (document images are pay-per-view, but we only
need index metadata). Returns party NAMES + doc type + book/page — actionable
leads like the Pickens/Acclaim path. SC is judicial, so ROD distress here is
PROBATE (deed of distribution / death) + LIENS. Reusable for any RecordRoom
county via COTT_RR_COUNTIES.

Flow (verified live), through the shared cookie-persisting client:
  1. GET  /{slug}/guest/Search/records      -> .ASPXANONYMOUS + session cookies
  2. POST /{slug}/search/Records (form FromDate/ThruDate/Type=""/Page=1)
        -> 302 PRG; stores the search server-side in session
  3. POST /{slug}/Search/Records/Result/ (JSON DataTables payload; the columns
        array is REQUIRED) -> {recordsTotal, data:[{Type, PartyOne, PartyTwo,
        RecordingDate, Property, FileNumber, BookPage}, ...]}; paginate via start.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import structlog

from ..http_client import client
from .models import RodDoc

log = structlog.get_logger()

COTT_RR_HOST = "https://recordroom.cottsystems.com"
COTT_RR_COUNTIES: dict[tuple[str, str], str] = {
    ("SC", "Union"): "unionsc",
}

# Distress KindCodes (probate + liens). Matched as substrings; resolutions out.
# "DIS STMT" was REMOVED 2026-10-04 (extraction-completeness audit, batch 13):
# live-pulled every "DEE DIS STMT" row Union has recorded in the last 90 days
# (37 of them -- 74% of this adapter's entire live "distress" output) and 37/37
# are "HOMEOWNERS DISCLOSURE STATEMENT" filings with the Department of Building
# Safety / City of Union Planning Department as the counterparty (a routine
# manufactured-home-to-real-property titling disclosure), NOT an estate
# "distribution statement" -- the abbreviation this token was added for. Every
# one was shipping live as a PROBATE_NOTICE with the homeowner tagged as a
# decedent. "DISTRIB" (a real "DEED OF DISTRIBUTION" would contain it) is kept;
# it never matched a single live row in a full 1-year sweep, but it is not a
# false-positive risk the way "DIS STMT" was.
_DISTRESS = ("DOD", "DEED OF DIST", "DEATH", "DISTRIB",
             "TAX LIEN", "LIEN", "MECH", "JUDG", "EXECUTION")
_RESOLVED = ("SAT", "REL", "TERM", "CANCEL", "RESC", "SUBORD", "WITHDRAW")

# Markup inside the "Property"/"PartyTwo" cells (see module docstring: each is
# raw vendor HTML, not plain text). Parcel #, the property's own situs address,
# the legal-description "Remarks", and a deed's $ consideration are each a
# separate <strong>Label:</strong> <span class="indexdetail_data">...</span>
# run inside the same cell _clean() used to flatten to one soup string --
# confirmed live 2026-10-04 on a real "DEE DOD" (deed of distribution) row:
# Parcel # "074-10-02-003" + situs "709 PERRIN AVENUE  UNION, SC 29379" were
# both present and both thrown away, the heir-defendant's own OWN mailing
# address (on PartyTwo, same markup) too. Regex, not an HTML parser, to match
# this module's own existing _clean() convention for these small vendor cells.
_PARCEL_RE = re.compile(r'Parcel\s*#:</strong>\s*<span[^>]*>\s*<a[^>]*>([^<]+)</a>', re.I)
_REMARKS_RE = re.compile(r'Remarks:</strong>\s*<span[^>]*>([^<]+)</span>', re.I)
_AMOUNT_RE = re.compile(r'Amount:</strong>\s*\$\s*([\d,]+(?:\.\d+)?)', re.I)
# Property's own address div uses <strong>Address:</strong>; a party's (grantor/
# grantee) uses <span class="indexdetail_label">Address: </span> -- both close
# with the same indexdetail_address > indexdetail_data pair, so one pattern
# anchored on the wrapper class covers both markups.
_ADDR_BLOCK_RE = re.compile(
    r'class="indexdetail_address">.*?class="indexdetail_data">([^<]+)</span>',
    re.I | re.S)


def _extract_parcel(html: str | None) -> str | None:
    m = _PARCEL_RE.search(html or "")
    return _clean(m.group(1)) or None if m else None


def _extract_remarks(html: str | None) -> str | None:
    m = _REMARKS_RE.search(html or "")
    return _clean(m.group(1)) or None if m else None


def _extract_amount(html: str | None) -> float | None:
    m = _AMOUNT_RE.search(html or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _extract_block_address(html: str | None) -> str | None:
    m = _ADDR_BLOCK_RE.search(html or "")
    return _clean(m.group(1)) or None if m else None

# DataTables column order the endpoint requires (3 render-only cols + fields).
_COLS = ["", "", "", "ScanPages", "RecordingDate", "Type",
         "PartyOne", "PartyTwo", "Property", "FileNumber", "BookPage"]
_DATE_RE = re.compile(r"/Date\((\d+)")


def _clean(v) -> str:
    """RecordRoom returns HTML-formatted cells (<div>, <br/>); strip to text."""
    import html as _html
    s = re.sub(r"<[^>]+>", " ", str(v or ""))
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def is_distress(doc_type: str | None) -> bool:
    s = _clean(doc_type).upper()
    return any(k in s for k in _DISTRESS) and not any(k in s for k in _RESOLVED)


def _parse_date(v) -> datetime | None:
    if not v:
        return None
    m = _DATE_RE.search(str(v))
    if m:
        try:
            return datetime.utcfromtimestamp(int(m.group(1)) / 1000)
        except (ValueError, OverflowError):
            return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v)[:10], fmt)
        except ValueError:
            continue
    return None


def _columns() -> list[dict]:
    return [{"data": d, "name": "", "searchable": True, "orderable": True,
             "search": {"value": "", "regex": False}} for d in _COLS]


async def discover_recent_nods(state: str, county: str, days_back: int = 45,
                               max_docs: int = 600) -> list[RodDoc]:
    slug = COTT_RR_COUNTIES.get((state, county))
    if not slug:
        return []
    today = datetime.utcnow()
    frm = today - timedelta(days=max(1, days_back))
    fmt = lambda d: f"{d.month}/{d.day}/{d.year}"  # noqa: E731
    base = f"{COTT_RR_HOST}/{slug}"
    out: list[RodDoc] = []
    seen: set[str] = set()
    try:
        async with client(timeout=60.0) as c:
            await c.get(f"{base}/guest/Search/records")
            await c.post(f"{base}/search/Records",
                         data={"FromDate": fmt(frm), "ThruDate": fmt(today), "Type": "", "Page": "1"},
                         headers={"X-Requested-With": "XMLHttpRequest"})
            for start in range(0, max_docs, 100):
                payload = {"draw": 1, "columns": _columns(),
                           "order": [{"column": 4, "dir": "asc"}],
                           "start": start, "length": 100,
                           "search": {"value": "", "regex": False}, "Filters": []}
                r = await c.post(f"{base}/Search/Records/Result/", json=payload,
                                 headers={"X-Requested-With": "XMLHttpRequest"})
                if r.status_code != 200:
                    break
                try:
                    rows = (r.json() or {}).get("data") or []
                except Exception:
                    break
                if not rows:
                    break
                for row in rows:
                    if not is_distress(row.get("Type")):
                        continue
                    inst = _clean(row.get("FileNumber"))
                    bp = _clean(row.get("BookPage"))
                    bm = re.findall(r"\d+", bp)
                    key = inst or bp
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    prop_html = row.get("Property") or ""
                    party2_html = row.get("PartyTwo") or ""
                    # Remarks (legal description) when the structured field parses;
                    # fall back to the old whole-cell soup so a markup change never
                    # drops the text outright, just loses its structure.
                    remarks = _extract_remarks(prop_html) or (_clean(prop_html) or None)
                    grantee_addr = _extract_block_address(party2_html)
                    raw_block: dict = {"type": _clean(row.get("Type"))}
                    if grantee_addr:
                        # The grantee's (PartyTwo's) OWN mailing address -- for a
                        # probate deed of distribution this is the heir's address,
                        # which can differ from the inherited property's situs
                        # (a real absentee-heir signal). Deliberately kept here as
                        # provenance only, NOT bridged into raw['owner_mailing'] --
                        # for a lien/judgment row PartyTwo is the CREDITOR, not the
                        # owner, and this adapter cannot tell which kind of row it
                        # is from the address block alone. Same "flag, don't wire"
                        # call as batch 12's spartan_weekly_legals petitioner block.
                        raw_block["grantee_address"] = grantee_addr
                    amount = _extract_amount(prop_html)
                    if amount is not None:
                        raw_block["consideration_amount"] = amount
                    out.append(RodDoc(
                        county=county, state=state,
                        doc_type=_clean(row.get("Type")),
                        recorded_date=_parse_date(row.get("RecordingDate")),
                        book=bm[0] if bm else None, page=bm[1] if len(bm) > 1 else None,
                        grantor=_clean(row.get("PartyOne")) or None,
                        grantee=_clean(row.get("PartyTwo")) or None,
                        instrument_no=inst or None,
                        parcel_id=_extract_parcel(prop_html),
                        property_address=_extract_block_address(prop_html),
                        consideration_amount=amount,
                        notes=remarks,
                        raw={"cott_recordroom": raw_block},
                    ))
                if len(rows) < 100:
                    break
    except Exception:
        log.warning("cott_rr.discover_failed", state=state, county=county)
        return []
    log.info("cott_rr.discovered", county=county, distress=len(out))
    return out[:max_docs]
