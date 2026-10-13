"""Greenville County SC probate search (appsas400 — the county's own AS/400 web portal).

Greenville is NOT one of the courts that feeds southcarolinaprobate.net (see
sc_probate_net.py's module docstring — it legit-empties there). It runs its own, separate,
free, public search at ``https://www.greenvillecounty.org/appsas400/Probate/`` instead. HERMES's
2026-10-13 status report claimed Greenville probate has "no online portal... manual pull only"
-- FALSE, live-verified below by direct curl from a clean /tmp/ working dir (a browser-pane
navigation hung instead; curl worked). The real mechanics, confirmed live 2026-10-13 (an earlier
draft of this scraper guessed at an ASP.NET-postback/VIEWSTATE flow like sc_probate_net's own
site and got 0 results against the real site -- this is the corrected, re-verified version):

1. The search is a plain GET with QUERY-STRING params to ``SearchResults.aspx`` --
   ``LastName``, ``FirstName``, ``MiddleName``, ``PartyType``, ``CaseNumber`` -- no VIEWSTATE,
   no POST, no form-field prep needed. ``GET SearchResults.aspx`` with NO query string instead
   returns the ENTIRE unfiltered case index (confirmed live: a bare GET came back labeled
   "450631 Matches Found" and 254MB) -- always pass every param (blank string for the ones not
   being searched), never call this URL with no params.
2. The server replies 302 to the SAME path with the real query swapped for an opaque
   ``?q=<encrypted-token>``; ``httpx.AsyncClient(follow_redirects=True)`` chases this
   automatically in one ``client.get()`` call. The final response is the real results page --
   confirmed live, a single page, NO pager (Smith+EST's "2643 Matches Found" all sit in one
   ~1.5MB response; there is no "next page" control to follow).
3. Results are a plain 3-column table (``class="JobsTable"``, no element id) -- Case #
   (a ``SearchDetails.aspx?CaseNumber=...`` link; the href's own case-number value carries
   trailing whitespace padding from the AS/400 backend -- strip it), Name, Party Type.
4. ``SearchDetails.aspx?CaseNumber=<case#>`` (also a plain GET, also one redirect hop to an
   opaque token, also auto-chased) returns a label/value table (``class="altDetailsTable"``,
   ``<tr><th>Label:</th><td>Value</td></tr>`` rows -- a real DOM structure, not scraped off
   flattened text) for the decedent: Name, Party Type, Address, Date of Death, Date of Birth,
   Sex, Status, Case Type, Case SubType, File Date, Expiration of Estate Creditor Claims
   Period, PR Appointed Date, Closed Date. A second, separate ``altDetailsTable`` under a
   "Parties Involved (N)" heading repeats the SAME 3-field group (Name/Party Type/Address) once
   per party, each group followed by a spacer row -- confirmed live on a real 2-PR case
   (APT23F34). N can be 0 (confirmed live, APT1390F21): an empty table, no parties at all.
   Every Party Type sampled so far (several real cases) was "Personal Representative" -- no
   attorney/trustee role has been observed on this site, unlike sc_probate_net's; `trustee` is
   left unset rather than guessed. Address is OFTEN BLANK on both the decedent's own row and
   every party's row (confirmed on every live-fetched sample this scraper was built against) --
   unlike the claim in an earlier draft of this docstring, a populated Address is the
   exception, not the norm; treat it as a bonus field, not a guaranteed one.
5. File Date is the one near-always-populated date (seen even on a 12/31/1866-filed, clearly-
   ancient batch-intestate record) -- Date of Death/Date of Birth are frequently blank. Closed
   Date tells you definitively whether the estate is closed: when it is blank the estate is
   still open (kept regardless of age, same rule sc_probate_net applies off its own Status
   text); when it is populated, the case is only kept if File Date (or Date of Death) falls
   inside MAX_AGE_DAYS -- an ancient placeholder-looking date like 12/31/1866 or 12/31/1900 just
   fails that check on its own, no special-casing needed.

Case numbers here (e.g. ``APT29F27``) use Greenville's own internal scheme -- not the
``YYYYESnnnnnnn`` format southcarolinaprobate.net's shared aggregator uses for OTHER counties.

Breadth tradeoff, same one sc_probate_net makes for its own per-county sweep: a single EST
search under one common surname already returns thousands of hits (2,643 for "Smith" alone)
and there is no date-range or county-wide listing endpoint on this form -- CaseNumber is
EXACT-match only (tested live: a real case number used as a prefix search returned 0 rows), so
there is no way to narrow the search itself to recent filings. This sweeps the SAME common-
surname list sc_probate_net uses and reads a capped SAMPLE of each surname's result rows (order
returned by the AS/400 backend does not appear to be date-sorted -- it is an arbitrary slice of
that surname's full match set, not a "most recent N"); each sampled case gets its own detail-
page fetch (a second request) so the age/closed filter can be applied, since none of that is
visible on the summary row itself.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Iterable

import httpx
import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...config import RuntimeConfig
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE_URL = "https://www.greenvillecounty.org/appsas400/Probate/"
SEARCH_URL = BASE_URL + "SearchResults.aspx"
DETAIL_URL = BASE_URL + "SearchDetails.aspx"

# Confirmed live 2026-10-13 off the real <select>: EST ("Deceased Person") is the real
# estate-matter bucket -- a Smith search under EST returns thousands of hits; DEC
# ("Deceased", a narrower/different list) returned only 3. Always search EST.
PARTY_TYPE_ESTATE = "EST"

# Same common-surname sweep sc_probate_net.py uses -- a single EST search already returns
# thousands of hits per name, so a handful of high-frequency surnames covers a large slice
# of the index without a full-index enumeration endpoint (none exists on this form).
SURNAMES: tuple[str, ...] = (
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Davis", "Wilson", "Moore", "Taylor", "White",
)

#: Rows sampled per surname search (NOT the total match count -- a popular surname
#: returns thousands; see module docstring on why "first N" is a sample, not a recency cut).
#: Each sampled row costs one extra detail-page request, so this is a politeness/runtime
#: bound, not a target -- most of a sample will be old/closed and dropped by is_current().
MAX_ROWS_PER_SURNAME = 150

#: A closed estate whose most recent date (File Date, or Date of Death if File Date is
#: somehow missing) is older than this is history, not a lead. 0 turns the filter off. An
#: estate with NO Closed Date is kept regardless of age (see module docstring point 5).
MAX_AGE_DAYS = int(os.environ.get("GREENVILLE_PROBATE_MAX_AGE_DAYS", "365"))

_CASE_NUMBER_RE = re.compile(r"CaseNumber=([^'\"&]+)", re.I)


def _clean(text: str | None) -> str:
    """Collapse the AS/400 backend's fixed-width space padding (e.g. 'SMITH          , A    H'
    -> 'SMITH, A H') into normal spacing. Used on every value pulled off either page."""
    if not text:
        return ""
    collapsed = " ".join(text.split())
    return re.sub(r"\s+,", ",", collapsed).strip()


def _clean_address(text: str | None) -> str:
    """Same whitespace collapse as `_clean`, plus one narrow, source-data-specific fix: the
    AS/400 backend sometimes concatenates the house number straight into the street name with
    NO separating space at all (confirmed live, case 2020ES23016822: literally
    '788OLLAND FORD ROAD', not a whitespace-collapse artifact of this scraper -- the raw HTML
    has no space there either). A leading digit run directly touching a letter is never a
    valid address otherwise, so inserting the one space a real address would have is safe and
    keeps the field geocodable."""
    cleaned = _clean(text)
    return re.sub(r"^(\d+)([A-Za-z])", r"\1 \2", cleaned)


def _parse_results(html: str) -> list[dict]:
    """Parse the plain 3-column `table.JobsTable` (Case #, Name, Party Type) -- confirmed
    live 2026-10-13: no element id on this table, and the case-number link is SINGLE-quoted
    (`<a href='SearchDetails.aspx?CaseNumber=...'>`) with trailing whitespace padding baked
    into the href value itself, both of which broke a double-quote-assuming first draft."""
    tree = HTMLParser(html)
    out: list[dict] = []
    for tr in tree.css("table.JobsTable tr"):
        a = tr.css_first("a")
        if a is None:
            continue
        href = a.attributes.get("href") or ""
        m = _CASE_NUMBER_RE.search(href)
        if not m:
            continue
        case_number = m.group(1).strip()
        if not case_number:
            continue
        cells = tr.css("td")
        name = _clean(cells[1].text(strip=True)) if len(cells) > 1 else ""
        party_type = _clean(cells[2].text(strip=True)) if len(cells) > 2 else ""
        out.append({"case_number": case_number, "name": name, "party_type": party_type})
    return out


def _label_key(th_text: str) -> str:
    return th_text.strip().rstrip(":").strip().lower().replace(" ", "_").replace("/", "_")


def _is_heading_table(table) -> bool:
    return table.css_first("th.heading") is not None


def _parse_label_value_table(table) -> dict[str, str]:
    """One `<tr><th>Label:</th><td>Value</td></tr>` table -> {label_key: value}."""
    out: dict[str, str] = {}
    for tr in table.css("tr"):
        th = tr.css_first("th")
        td = tr.css_first("td")
        if th is None or td is None:
            continue
        out[_label_key(th.text(strip=True))] = _clean(td.text(strip=True))
    return out


def _parse_parties_table(table) -> list[dict[str, str]]:
    """The repeating Name/Party Type/Address triplet-per-party table (0..N parties;
    confirmed live on real 0-, 1- and 2-party cases). Groups rows on each new 'name' key,
    since a party with no Address row still starts a fresh group on its Name row."""
    parties: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for tr in table.css("tr"):
        th = tr.css_first("th")
        td = tr.css_first("td")
        if th is None or td is None:
            continue
        key = _label_key(th.text(strip=True))
        value = _clean(td.text(strip=True))
        if key == "name":
            current = {"name": value}
            parties.append(current)
        elif current is not None:
            current[key] = value
    return parties


def _parse_detail(html: str) -> dict:
    """A case's SearchDetails.aspx page -> {..decedent fields.., 'parties': [...]}."""
    tree = HTMLParser(html)
    data_tables = [t for t in tree.css("table.altDetailsTable") if not _is_heading_table(t)]
    decedent = _parse_label_value_table(data_tables[0]) if data_tables else {}
    parties = _parse_parties_table(data_tables[1]) if len(data_tables) > 1 else []
    decedent["parties"] = parties
    return decedent


def _parse_us_date(v: str | None) -> datetime | None:
    try:
        return datetime.strptime((v or "").strip(), "%m/%d/%Y")
    except ValueError:
        return None


def is_current(detail: dict, now: datetime | None = None) -> bool:
    """Keep an estate with no recorded Closed Date (still open, kept whatever its age -- the
    same rule sc_probate_net applies off its own Status text, here off Closed Date instead
    since Greenville's own Status strings are truncated AS/400 codes, e.g. 'Estates- I'); a
    CLOSED estate is kept only if File Date (or Date of Death) is inside MAX_AGE_DAYS."""
    if MAX_AGE_DAYS <= 0:
        return True
    if not (detail.get("closed_date") or "").strip():
        return True
    now = now or datetime.utcnow()
    dates = [d for d in (_parse_us_date(detail.get("file_date")),
                         _parse_us_date(detail.get("date_of_death"))) if d]
    if not dates:
        return False
    return (now - max(dates)).days <= MAX_AGE_DAYS


def _personal_representative(parties: list[dict[str, str]]) -> dict[str, str] | None:
    for p in parties:
        if "personal representative" in p.get("party_type", "").lower():
            return p
    return parties[0] if parties else None


async def _search_surname(client: httpx.AsyncClient, surname: str) -> list[dict]:
    r = await client.get(SEARCH_URL, params={
        "LastName": surname, "FirstName": "", "MiddleName": "",
        "PartyType": PARTY_TYPE_ESTATE, "CaseNumber": "",
    })
    r.raise_for_status()
    rows = _parse_results(r.text)
    return rows[:MAX_ROWS_PER_SURNAME]


async def _fetch_detail(client: httpx.AsyncClient, case_number: str) -> dict:
    r = await client.get(DETAIL_URL, params={"CaseNumber": case_number})
    r.raise_for_status()
    return _parse_detail(r.text)


def _build_listing(summary: dict, detail: dict) -> Listing:
    case_number = summary["case_number"]
    decedent = detail.get("name") or summary.get("name") or None
    pr = _personal_representative(detail.get("parties") or [])
    pr_name = pr.get("name") if pr else None
    status = detail.get("status") or None

    desc = f"Greenville County SC probate estate {case_number}"
    if decedent:
        desc += f" — decedent {decedent}"
    if pr_name:
        desc += f"; PR {pr_name}"
    if status:
        desc += f" [{status}]"

    return Listing(
        source="counties_sc.greenville_probate",
        source_url=f"{DETAIL_URL}?CaseNumber={case_number}",
        listing_type=ListingType.PROBATE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Greenville",
        street_address=_clean_address(detail.get("address")) or None,
        owner_name=decedent,   # decedent — matches sc_probate_net's convention
        defendant=pr_name,     # Personal Representative / contact — same convention as sc_probate_net
        case_number=case_number,
        description=desc[:500],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"greenville_probate": {
            "record_kind": "probate",
            "decedent": decedent,
            "case_type": detail.get("case_type"),
            "case_subtype": detail.get("case_subtype"),
            "file_date": detail.get("file_date"),
            "date_of_death": detail.get("date_of_death"),
            "date_of_birth": detail.get("date_of_birth") or None,
            "sex": detail.get("sex") or None,
            "pr_appointed_date": detail.get("pr_appointed_date"),
            "closed_date": detail.get("closed_date") or None,
            "creditor_claims_expiration": detail.get(
                "expiration_of_estate_creditor_claims_period") or None,
            "status": status,
            "personal_representative": pr or None,
            "parties": detail.get("parties") or None,
        }},
    )


class GreenvilleProbate(BaseScraper):
    """Greenville County SC probate search (county's own AS/400 portal, not
    southcarolinaprobate.net — Greenville doesn't feed that aggregator)."""

    slug = "counties_sc.greenville_probate"
    name = "Greenville County SC Probate (appsas400 portal)"
    category = "probate"
    expected_min_count = 0
    requires_apify = False
    # Up to 10 surnames x up to MAX_ROWS_PER_SURNAME detail fetches, each paced; generous
    # soft timeout so a slow run ships partial results (banked in self.partial) instead of
    # nothing, same pattern sc_probate_net uses for its own grid-pager sweep.
    timeout_s = 1800.0

    async def fetch(self) -> Iterable[Listing]:
        cfg = RuntimeConfig.from_env()
        out: list[Listing] = self.partial
        seen: set[str] = {li.case_number for li in out if li.case_number}

        async with httpx.AsyncClient(
            headers={"User-Agent": cfg.user_agent},
            follow_redirects=True,
            timeout=cfg.request_timeout_s + 30.0,
        ) as client:
            for surname in SURNAMES:
                try:
                    rows = await _search_surname(client, surname)
                except httpx.HTTPError as exc:
                    log.warning("greenville_probate.search_failed", surname=surname,
                                error=str(exc)[:200])
                    continue

                name_hits = 0
                name_stale = 0
                for summary in rows:
                    case_number = summary["case_number"]
                    if case_number in seen:
                        continue
                    seen.add(case_number)
                    await asyncio.sleep(0.5)
                    try:
                        detail = await _fetch_detail(client, case_number)
                    except httpx.HTTPError as exc:
                        log.warning("greenville_probate.detail_failed",
                                    case_number=case_number, error=str(exc)[:200])
                        continue
                    if not is_current(detail):
                        name_stale += 1
                        continue
                    out.append(_build_listing(summary, detail))
                    name_hits += 1

                log.info("greenville_probate.surname_done", surname=surname,
                          count=name_hits, stale_or_old=name_stale,
                          rows_sampled=len(rows), max_age_days=MAX_AGE_DAYS)
                await asyncio.sleep(1.0)
        return out
