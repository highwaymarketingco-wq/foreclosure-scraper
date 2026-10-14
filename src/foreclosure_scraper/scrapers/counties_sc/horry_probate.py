"""Horry County SC Probate Court estate cases (Spartan public portal, JSON).

Source
------
Horry County Probate Court's public case search runs on the Spartan Computer
Services portal:

    page   https://scportal.hostedbyspartan.com/HorryPublicProbate/pages/CaseSearchPage.aspx
    data   https://scportal.hostedbyspartan.com/HorryPublicProbate/Handlers/Data.asmx/CaseSearch

The page's own DataTables grid calls the data handler with a GET (``Content-Type:
application/json``) carrying the form fields as query parameters; the answer is
``{"d": "<json string>"}`` with ``recordsTotal`` and ``aaData`` rows. No login, no
CAPTCHA, no terms page, no robots.txt on the host (404). Estate case numbers carry
the year and agency: ``2026ES26nnnnn`` (AgencyId 26500 = "Horry Probate Estate").

Read live 2026-10-07 with one 10-row request: 3,184 estate cases filed in 2026 so
far. Full live proof the same day (9 data requests, 30 s): 4,016 estates filed in the
last 365 days (3,176 from 2026, 840 from late 2025). Row fields: WARANTNO (case number), CseFilDt (filed), PPTYNAME (primary party,
"LAST, FIRST M"), PPTYTYPE ("Deceased Person"), CseTypIn, CMSCASE/PPTYSEQ (detail
keys) and the judicial assistant's name and code (not kept). The decedent's name and
the county go to the downstream owner-name resolver like every other probate source.

PER-CASE DETAIL PAGE (added 2026-10-13, source-completeness audit Pattern D): the
grid's own render() call builds `CaseDetailPage.aspx?AgencyId={row.APPCODE}&CaseId=
{row.CMSCASE}&PartySeq={row.PPTYSEQ}` (confirmed live against the page's own JS,
2026-10-13) -- a plain ASPX page, no login/CAPTCHA/WAF, ~0.15 s average over 5 live
fetches. It carries a "Primary Parties" table (Name/Type/Date of Death/Address) and
a "Case Parties" table (Name/Type) listing every party on the case, including
whoever is serving as Personal Representative / Co-Personal Representative / Special
Administrator. Live-sampled ~90 real cases spread across both years 2026-10-13: the
decedent address cell is sparse (roughly 1 in 20 populated -- most are blank, the
real hits look like "18604 Stony Point Strongsville, OH 44136", i.e. the decedent's
own last-known address, not necessarily the SC property being probated) while a
named representative is present on close to half of cases. This was previously
described in a comment and explicitly skipped ("would cost one request per case")
-- it is now fetched, but budgeted: capped at DETAIL_FETCH_CAP per run and cut off
by a remaining-time budget (see `_enrich_with_detail_pages`), since a year's ~4,000
estates make full per-case coverage every run impractical. Pure enrichment -- a
failed, slow, or empty detail fetch never breaks or drops the underlying listing.

Pagination: iDisplayStart / iDisplayLength (500 per request), so a year of Horry
estates is about 7 requests. By default the current and the previous year are read
and rows filed more than HORRY_PROBATE_LOOKBACK_DAYS (365) ago are dropped.

First documented in docs/county_breadth_research_2026-09-21.md (section 4); built
2026-10-07 (docs/new_sources_2026-10-07_liens_courts.md, SC-HORRY-PROBATE).
Gate with FORECLOSURE_HORRY_PROBATE=0.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://scportal.hostedbyspartan.com/HorryPublicProbate/"
PAGE_URL = BASE + "pages/CaseSearchPage.aspx"
DATA_URL = BASE + "Handlers/Data.asmx/CaseSearch"
DETAIL_URL = BASE + "pages/CaseDetailPage.aspx"
AGENCY_ID = "26500"
PAGE_SIZE = 500
MAX_PAGES_PER_YEAR = 20          # 10,000 rows; Horry files about 4,000 estates a year
ENV_OFF = "FORECLOSURE_HORRY_PROBATE"
LOOKBACK_ENV = "HORRY_PROBATE_LOOKBACK_DAYS"
_PAUSE_S = 1.7

# --- per-case detail page (CaseDetailPage.aspx) -----------------------------
# Added 2026-10-13 (source-completeness audit Pattern D). A year of Horry
# estates runs ~4,000 cases, so fetching every detail page every run isn't
# practical -- this is a budgeted sample, not full coverage, mirroring
# national/landwatch.py's DETAIL_FETCH_CAP_PER_COUNTY (hard count ceiling)
# combined with national/estate_sales.py's / counties_nc/polk_tax.py's
# remaining-time-budget pattern (so a slow run fills in fewer cases instead
# of blowing past timeout_s).
DETAIL_FETCH_CAP = 300
_DETAIL_PAUSE_S = 0.3            # lighter than the list-fetch's _PAUSE_S -- confirmed live
                                  # 2026-10-13: ~0.15s avg over 5 plain fetches, no WAF/throttle seen
_DETAIL_TIME_SAFETY_MARGIN_S = 15.0  # unspent cushion of timeout_s left for the detail pass to exit cleanly
_AJAX_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": PAGE_URL,
}

# Primary Parties table row: <td>Name</td><td>Type</td><td>Date of Death</td><td>Address</td>
_PRIMARY_PARTY_ROW_RE = re.compile(
    r'<tr class="gridItem(?:Nrm|Alt)">\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>',
    re.S,
)
# Case Parties table row: <td>Name</td><td>Type</td> (every party on the case, one row each)
_CASE_PARTY_ROW_RE = re.compile(
    r'<tr class="gridItem(?:Nrm|Alt)">\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', re.S,
)
_MAIL_STATE_RE = re.compile(r",\s*([A-Z]{2})\s*\d{5}")
# Case-party TYPE substrings (lowercased) that mean "runs the estate" -- covers
# "Personal Representative" and "Co-Personal Representative" via substring match.
_REP_ROLE_MARKERS = ("personal representative", "special administrator")


def search_params(year: int, start: int, length: int = PAGE_SIZE) -> dict[str, str]:
    """The query string the page's own grid sends for an estate case-number prefix."""
    return {
        "sEcho": "1", "iColumns": "5", "iDisplayStart": str(start), "iDisplayLength": str(length),
        "AgencyId": AGENCY_ID, "CaseNumber": f"{year}ES26", "CaseType": "", "ClerkCode": "",
        "LastName": "", "FirstName": "", "DispositionStatus": "",
    }


def decode(payload: Any) -> dict[str, Any]:
    """ASMX ``{"d": "<json>"}`` -> the DataTables object ({} when malformed)."""
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("d")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except ValueError:
            return {}
    return inner if isinstance(inner, dict) else {}


def _s(v: Any) -> str | None:
    s = re.sub(r"\s+", " ", str(v if v is not None else "")).strip()
    return s or None


def _filed(v: Any) -> datetime | None:
    try:
        return datetime.strptime(str(v).strip(), "%m/%d/%Y")
    except (TypeError, ValueError):
        return None


def build_listing(row: dict[str, Any], *, now: datetime) -> Listing | None:
    """One grid row -> a PROBATE_NOTICE lead, or None for a non-decedent / unnamed row."""
    case = _s(row.get("WARANTNO"))
    name = _s(row.get("PPTYNAME"))
    party_type = _s(row.get("PPTYTYPE"))
    if not case or not name:
        return None
    if party_type and "deceased" not in party_type.lower():
        return None
    filed = _filed(row.get("CseFilDt"))
    if filed and filed > now + timedelta(days=400):
        filed = None    # keying slips exist (one live row read 3025); a future date is not a date
    return Listing(
        source=HorryProbate.slug,
        source_url=PAGE_URL,
        listing_type=ListingType.PROBATE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Horry",
        case_number=case,
        owner_name=name,          # the decedent; the owner->GIS resolver finds the property
        description=f"Horry County SC estate {case} opened {filed.date().isoformat() if filed else '?'} "
                    f"for {name} (deceased)",
        first_seen=now,
        last_seen=now,
        raw={"probate": {
            "decedent": name,
            "case_number": case,
            "filing_date": filed.date().isoformat() if filed else None,
            "court": "Horry County Probate Court",
            "party_type": party_type,
            "case_type": _s(row.get("CseTypIn")),
            "detail_keys": {"agency": _s(row.get("APPCODE")), "case_id": row.get("CMSCASE"),
                            "party_seq": row.get("PPTYSEQ")},
            "source": "horry_spartan_portal",
        }},
    )


def detail_url(agency: Any, case_id: Any, party_seq: Any) -> str | None:
    """``CaseDetailPage.aspx?AgencyId=...&CaseId=...&PartySeq=...`` -- the exact
    template the search grid's own render() call builds (confirmed live
    2026-10-13 against the page's own JS: ``'CaseDetailPage.aspx?AgencyId={0}
    &CaseId={1}&PartySeq={2}'.format(row.APPCODE, row.CMSCASE, row.PPTYSEQ)``).
    CMSCASE/PPTYSEQ arrive from the grid as floats (e.g. ``160275.0``); they are
    coerced to plain ints here since that's the shape real case numbers take."""
    if not agency or case_id is None or party_seq is None:
        return None
    try:
        cid = int(float(case_id))
        seq = int(float(party_seq))
    except (TypeError, ValueError):
        return None
    return f"{DETAIL_URL}?AgencyId={agency}&CaseId={cid}&PartySeq={seq}"


def _parse_detail_html(html: str | None) -> dict[str, Any]:
    """Parse one CaseDetailPage.aspx response for the two per-case fields the
    search grid can't carry: the decedent's own last-known address (``Primary
    Parties`` table, 4th column) and the name(s) of whoever is serving as
    Personal Representative / Co-Personal Representative / Special
    Administrator (``Case Parties`` table). Confirmed live 2026-10-13 across
    ~90 real cases spanning both years: the address cell is sparse (roughly 1
    in 20 populated; most show an empty ``&nbsp;`` or bare-comma cell) while a
    representative name is present on close to half. Never raises -- a page
    shape it doesn't recognize just yields an empty/partial dict, never a
    fabricated field."""
    out: dict[str, Any] = {}
    if not html:
        return out

    i = html.find("Primary Parties")
    j = html.find("Case Parties")
    if i != -1 and j != -1:
        m = _PRIMARY_PARTY_ROW_RE.search(html[i:j])
        if m:
            addr = re.sub(r"\s+", " ", m.group(4)).replace("&nbsp;", "").strip(" ,")
            if addr:
                out["decedent_address"] = addr
                sm = _MAIL_STATE_RE.search(addr)
                if sm:
                    out["mail_state"] = sm.group(1)

    if j != -1:
        k = html.find("Scheduled Events", j)
        parties_html = html[j:k] if k != -1 else html[j:]
        reps: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for pm in _CASE_PARTY_ROW_RE.finditer(parties_html):
            name = re.sub(r"\s+", " ", pm.group(1)).strip()
            role = re.sub(r"\s+", " ", pm.group(2)).strip()
            if not name or not role:
                continue
            if any(marker in role.lower() for marker in _REP_ROLE_MARKERS):
                key = (name, role)
                if key not in seen:
                    seen.add(key)
                    reps.append({"name": name, "role": role})
        if reps:
            out["personal_representatives"] = reps

    return out


async def _fetch_detail_page(http: Any, agency: Any, case_id: Any, party_seq: Any) -> dict[str, Any]:
    """Best-effort fetch + parse of one CaseDetailPage.aspx. Pure enrichment --
    never raises. The underlying Listing already comes from the search grid
    (``build_listing``), so a failed, slow, or empty detail fetch must never
    break or drop it. Uses the same plain httpx session the list-fetch pass
    already opened -- no browser, no stealth tier needed (confirmed live
    2026-10-13: no login, no CAPTCHA, no WAF block on this endpoint)."""
    url = detail_url(agency, case_id, party_seq)
    if not url:
        return {}
    try:
        r = await http.get(url, headers={"Referer": PAGE_URL})
        html = r.text if r.status_code == 200 else None
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        log.debug("horry_probate.detail_fetch_failed", url=url, error=str(exc)[:160])
        return {}
    try:
        return _parse_detail_html(html)
    except Exception as exc:  # noqa: BLE001 - a parse bug must not drop the listing either
        log.debug("horry_probate.detail_parse_failed", url=url, error=str(exc)[:160])
        return {}


def _apply_detail(li: Listing, extras: dict[str, Any]) -> None:
    """Merge a parsed CaseDetailPage.aspx dict into its Listing. Pure
    enrichment: only adds data the search grid never carries, never raises.
    The decedent-address shape mirrors counties_nc/polk_tax.py's
    ``raw["owner_mailing"]`` convention -- situs is unknown at this source
    (the decedent's own last-known address isn't necessarily the SC property
    being probated), so ``absentee`` defaults False rather than guessing,
    same reasoning polk_tax uses."""
    if not extras:
        return

    reps = extras.get("personal_representatives")
    if reps:
        li.raw.setdefault("probate", {})["personal_representatives"] = reps

    mailing = extras.get("decedent_address")
    if mailing:
        mail_state = extras.get("mail_state")
        li.raw["owner_mailing"] = {
            "owner": li.owner_name,
            "mailing": mailing,
            "situs": None,
            "mail_state": mail_state,
            "absentee": False,
            "out_of_state": bool(mail_state and mail_state != "SC"),
            "source": "horry_probate_detail",
        }


class HorryProbate(BaseScraper):
    slug = "counties_sc.horry_probate"
    name = "Horry County (SC) Probate Court estate cases (Spartan portal)"
    category = "probate"
    timeout_s = 180.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("horry_probate.disabled")
            return []
        now = datetime.utcnow()
        lookback = int(os.environ.get(LOOKBACK_ENV, "365"))
        cutoff = now - timedelta(days=lookback)
        out: list[Listing] = []
        seen: set[str] = set()
        fetch_start = time.monotonic()
        async with client(timeout=45.0) as http:
            try:
                await http.get(PAGE_URL)       # the page the grid lives on, as a browser loads it
            except Exception as exc:  # noqa: BLE001
                log.warning("horry_probate.page_failed", error=str(exc)[:160])
                return []
            for year in (now.year, now.year - 1):
                if datetime(year, 12, 31) < cutoff:
                    continue
                start = 0
                for _ in range(MAX_PAGES_PER_YEAR):
                    await asyncio.sleep(_PAUSE_S)
                    try:
                        r = await http.get(DATA_URL, params=search_params(year, start), headers=_AJAX_HEADERS)
                        data = decode(r.json()) if r.status_code == 200 else {}
                    except Exception as exc:  # noqa: BLE001
                        log.warning("horry_probate.page_error", year=year, start=start, error=str(exc)[:160])
                        break
                    if data.get("Error"):
                        log.warning("horry_probate.server_error", year=year, error=str(data["Error"])[:160])
                        break
                    rows = data.get("aaData") or []
                    for row in rows:
                        li = build_listing(row, now=now)
                        if li is None or li.case_number in seen:
                            continue
                        filed = (li.raw["probate"].get("filing_date") or "")
                        if filed and datetime.fromisoformat(filed) < cutoff:
                            continue
                        seen.add(li.case_number)
                        out.append(li)
                    total = int(data.get("recordsFiltered") or data.get("recordsTotal") or 0)
                    start += len(rows)
                    if not rows or start >= total:
                        break
                log.info("horry_probate.year_done", year=year, kept=len(out))

            # Bank every list-grid row BEFORE the per-case detail pass below,
            # so a soft-timeout mid-enrichment still ships them all (same
            # ordering as counties_nc/polk_tax.py; base_scraper.safe_run's
            # partial-salvage path reads self.partial on a timeout).
            self.partial = list(out)
            await self._enrich_with_detail_pages(http, out, fetch_start)
        return out

    async def _enrich_with_detail_pages(
        self, http: Any, listings: list[Listing], fetch_start: float
    ) -> None:
        """Per-case CaseDetailPage.aspx enrichment pass (decedent address +
        personal representative) -- added 2026-10-13, source-completeness
        audit Pattern D. Capped by DETAIL_FETCH_CAP and cut off by a
        remaining-time budget so this can never blow past self.timeout_s; a
        year of Horry estates runs ~4,000 cases, so full per-case coverage
        every run isn't practical -- this is a budgeted sample, not full
        coverage, by design. Never drops a listing: every error is caught
        inside ``_fetch_detail_page``."""
        deadline = fetch_start + self.timeout_s - _DETAIL_TIME_SAFETY_MARGIN_S
        done = 0
        for li in listings:
            if done >= DETAIL_FETCH_CAP:
                log.info("horry_probate.detail_fetch_cap_reached", cap=DETAIL_FETCH_CAP,
                          total=len(listings))
                break
            if time.monotonic() > deadline:
                log.info("horry_probate.detail_fetch_budget_spent", done=done,
                          remaining=len(listings) - done)
                break
            keys = (li.raw.get("probate") or {}).get("detail_keys") or {}
            agency, case_id, party_seq = keys.get("agency"), keys.get("case_id"), keys.get("party_seq")
            if not agency or case_id is None or party_seq is None:
                continue
            done += 1
            await asyncio.sleep(_DETAIL_PAUSE_S)
            try:
                extras = await _fetch_detail_page(http, agency, case_id, party_seq)
                _apply_detail(li, extras)
            except Exception as exc:  # noqa: BLE001 - enrichment must never drop the listing
                log.debug("horry_probate.detail_enrich_failed", case=li.case_number, error=str(exc)[:160])


if __name__ == "__main__":
    from collections import Counter

    async def _main() -> None:
        s = HorryProbate()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        print("by filing month", sorted(Counter((li.raw["probate"]["filing_date"] or "?")[:7] for li in rows).items())[-6:])

    asyncio.run(_main())
