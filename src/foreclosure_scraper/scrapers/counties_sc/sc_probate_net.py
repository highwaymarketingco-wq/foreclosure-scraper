"""southcarolinaprobate.net — centralized SC probate estate + marriage search.

A handful of SC probate courts publish their case index to a single shared
ASP.NET WebForms app at ``https://www.southcarolinaprobate.net/search/`` (with a
Charleston-only mirror at ``/charlestonprobatesearch/``). The county dropdown
lists every participating court; an in-page name-search form returns a results
grid per county.

Unlike the SC Judicial Public Index (publicindex.sccourts.org), this site is
NOT bot-walled — plain httpx with a real-browser UA gets HTTP 200, so no
Scrapling/stealth render is needed. The flow is a two-step ASP.NET postback:

1. GET the search page → collect ``__VIEWSTATE`` + friends + the session cookie.
2. POST a ``ddlCounties`` change postback (selects the county; for marriage
   counties this also flips the hidden ``hfOnlyMarriage`` flag server-side) →
   collect the refreshed VIEWSTATE.
3. POST ``btnSearch`` with a last/business name → the server returns:
     - PROBATE counties: grid ``cgvCases`` — Case#, Case Name (decedent),
       Party (attorney/PR), Type of Case, Filing Date, County, Appointment
       Date, Creditor Claim Due, Case Status. Each case also embeds an
       expandable ``..._gvParties`` sub-grid with the Personal Representative's
       full name + mailing address.
     - MARRIAGE counties: grid ``cgvMarriage`` — License#, Case Name
       (Groom/Bride), Application Date, Marriage date, County, plus a
       ``..._gvParties`` sub-grid with both spouses' names + addresses.

These are DISTRESS-LEAD records, not property listings: a decedent + the
appointed Personal Representative is a classic motivated-seller signal (heirs
liquidate to avoid carrying costs / split the estate). We emit them as
address-less Listings — ``owner_name`` = decedent (probate) or the couple
(marriage), with the PR's name + mailing address captured in ``raw`` and
backfilled to a property by the downstream owner→GIS enricher. Dateless: a
filing/appointment date is recorded in ``raw`` but there is no sale date.

In-footprint counties only. As of build time Charleston Probate + Charleston
Marriage are the only in-footprint courts that actually post here; Colleton,
Georgetown, Oconee, and Cherokee return "no records" (those courts don't feed
this aggregator). They're still queried every run so they auto-light-up if the
court starts publishing. To surface a broad set without a per-name guessing
game, we sweep a short list of common SC surnames per county and dedupe on the
case/license number.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterable

import httpx
import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...config import RuntimeConfig
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE_URL = "https://www.southcarolinaprobate.net/search/"

# ASP.NET WebForms control-name prefix on every form field.
PRE = "ctl00$ContentPlaceHolder1$"

# In-footprint courts to query. The dropdown ``value`` is exactly the visible
# label here. Marriage variants flip hfOnlyMarriage server-side on the
# county-change postback, so we only need to flag is_marriage for parsing.
#   (dropdown_value, display_county, state, is_marriage)
COUNTIES: tuple[tuple[str, str, str, bool], ...] = (
    ("Charleston Probate", "Charleston", "SC", False),
    ("Colleton", "Colleton", "SC", False),
    ("Georgetown", "Georgetown", "SC", False),
    ("Oconee", "Oconee", "SC", False),
    ("Cherokee", "Cherokee", "SC", False),
    ("Charleston Marriage", "Charleston", "SC", True),
)

# Common SC surnames swept per county. Each is a separate name search; the
# server returns every estate/marriage whose searched party shares the surname,
# so a handful of high-frequency names covers a large slice of the index. Rows
# are deduped on case#/license# across names, so overlap is harmless.
SURNAMES: tuple[str, ...] = (
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Davis", "Wilson", "Moore", "Taylor", "White",
)

# Party "Type" values in the gvParties sub-grid that identify the Personal
# Representative (the actual decision-maker / motivated-seller contact).
_PR_TYPES = ("personal representative", "co-personal representative")

# Empty-grid sentinel the app renders when a search has no hits.
_NO_RECORDS = "no records matching"


def _hidden_fields(html: str) -> dict[str, str]:
    """Collect every hidden input (VIEWSTATE, EVENTVALIDATION, etc.)."""
    tree = HTMLParser(html)
    out: dict[str, str] = {}
    for inp in tree.css("input[type=hidden]"):
        name = inp.attributes.get("name")
        if name:
            out[name] = inp.attributes.get("value") or ""
    return out


def _is_case_number(text: str, marriage: bool) -> bool:
    """A real case/license number cell: probate 'YYYYES#######',
    marriage 'YYYY#######' (all digits). Used to tell genuine main-grid case
    rows apart from the interleaved gvParties / gvDocket sub-grid rows."""
    t = (text or "").strip()
    if not t:
        return False
    if marriage:
        return t.isdigit() and len(t) >= 6
    # probate: 4-digit year + ES + digits, e.g. 2024ES1000123
    return bool(t[:4].isdigit() and "ES" in t.upper())


def _pr_from_parties(party_table) -> tuple[str | None, dict | None]:
    """Pull the Personal Representative (name + mailing address) from a
    case's gvParties sub-grid. Returns (pr_name, pr_address_dict)."""
    if party_table is None:
        return None, None
    rows = party_table.css("tr")
    if len(rows) < 2:
        return None, None
    header = [c.text(strip=True).lower() for c in rows[0].css("th, td")]

    def idx(*names: str) -> int | None:
        for n in names:
            for i, h in enumerate(header):
                if n in h:
                    return i
        return None

    i_first = idx("first name")
    i_last = idx("last name")
    i_mid = idx("middle")
    i_suf = idx("suffix")
    i_a1 = idx("address 1")
    i_a2 = idx("address 2")
    i_city = idx("city")
    i_state = idx("state")
    i_zip = idx("zip")
    i_type = idx("type")

    def cell(cells, i):
        return cells[i].text(strip=True) if i is not None and i < len(cells) else ""

    first_pr = None  # fall back to the first party if no explicit PR found
    for tr in rows[1:]:
        cells = tr.css("td")
        if not cells:
            continue
        ptype = cell(cells, i_type).lower()
        name = " ".join(
            p for p in (
                cell(cells, i_first), cell(cells, i_mid),
                cell(cells, i_last), cell(cells, i_suf),
            ) if p
        ).strip()
        if not name:
            continue
        addr = {
            "name": name,
            "type": cell(cells, i_type) or None,
            "address1": cell(cells, i_a1) or None,
            "address2": cell(cells, i_a2) or None,
            "city": cell(cells, i_city) or None,
            "state": cell(cells, i_state) or None,
            "zip": cell(cells, i_zip) or None,
        }
        if first_pr is None:
            first_pr = (name, addr)
        if any(t in ptype for t in _PR_TYPES):
            return name, addr
    return first_pr if first_pr else (None, None)


def _parse_probate(html: str, county: str, state: str) -> list[Listing]:
    """Parse the cgvCases probate grid into decedent/PR distress leads."""
    out: list[Listing] = []
    tree = HTMLParser(html)
    grid = tree.css_first("table#ctl00_ContentPlaceHolder1_cgvCases")
    if grid is None:
        return out
    if _NO_RECORDS in (grid.text() or "").lower():
        return out

    # gvParties sub-grids appear in the same document order as their parent
    # case rows; pair them positionally.
    party_tables = [
        tb for tb in tree.css("table")
        if (tb.attributes.get("id") or "").startswith(
            "ctl00_ContentPlaceHolder1_cgvCases_"
        ) and (tb.attributes.get("id") or "").endswith("_gvParties")
    ]

    case_i = 0
    for tr in grid.css("tr"):
        cells = tr.css("td")
        if len(cells) < 8:
            continue
        case_number = cells[1].text(strip=True)
        if not _is_case_number(case_number, marriage=False):
            continue

        case_name = cells[2].text(strip=True) or None   # decedent
        party = cells[3].text(strip=True) or None        # attorney/PR label
        case_type = cells[4].text(strip=True) or None
        filing_date = cells[5].text(strip=True) or None
        appt_date = cells[7].text(strip=True) if len(cells) > 7 else None
        status = cells[-1].text(strip=True) or None

        party_table = party_tables[case_i] if case_i < len(party_tables) else None
        case_i += 1
        pr_name, pr_addr = _pr_from_parties(party_table)

        desc = f"SC probate estate {case_number} ({county} County)"
        if case_name:
            desc += f" — decedent {case_name}"
        if pr_name:
            desc += f"; PR {pr_name}"
        if status:
            desc += f" [{status}]"

        out.append(
            Listing(
                source="counties_sc.sc_probate_net",
                source_url=BASE_URL,
                listing_type=ListingType.PROBATE_NOTICE,
                property_kind=PropertyKind.UNKNOWN,
                state=state,
                county=county,
                owner_name=case_name,       # decedent — owner->GIS enricher fills the property
                defendant=pr_name or party, # the Personal Representative / contact
                case_number=case_number,
                description=desc[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sc_probate_net": {
                    "record_kind": "probate",
                    "decedent": case_name,
                    "case_type": case_type,
                    "filing_date": filing_date,
                    "appointment_date": appt_date or None,
                    "status": status,
                    "personal_representative": pr_addr,
                }},
            )
        )
    return out


def _parse_marriage(html: str, county: str, state: str) -> list[Listing]:
    """Parse the cgvMarriage grid into marriage-license distress leads."""
    out: list[Listing] = []
    tree = HTMLParser(html)
    grid = tree.css_first("table#ctl00_ContentPlaceHolder1_cgvMarriage")
    if grid is None:
        return out
    if _NO_RECORDS in (grid.text() or "").lower():
        return out

    party_tables = [
        tb for tb in tree.css("table")
        if (tb.attributes.get("id") or "").startswith(
            "ctl00_ContentPlaceHolder1_cgvMarriage_"
        ) and (tb.attributes.get("id") or "").endswith("_gvParties")
    ]

    case_i = 0
    for tr in grid.css("tr"):
        cells = tr.css("td")
        if len(cells) < 5:
            continue
        license_number = cells[1].text(strip=True)
        if not _is_case_number(license_number, marriage=True):
            continue

        couple = cells[2].text(strip=True) or None       # GROOM/BRIDE
        appl_date = cells[3].text(strip=True) or None
        marriage_date = cells[4].text(strip=True) if len(cells) > 4 else None

        party_table = party_tables[case_i] if case_i < len(party_tables) else None
        case_i += 1
        spouse_name, spouse_addr = _pr_from_parties(party_table)

        desc = f"SC marriage license {license_number} ({county} County)"
        if couple:
            desc += f" — {couple}"
        if marriage_date:
            desc += f"; married {marriage_date}"

        out.append(
            Listing(
                source="counties_sc.sc_probate_net",
                source_url=BASE_URL,
                listing_type=ListingType.PROBATE_NOTICE,
                property_kind=PropertyKind.UNKNOWN,
                state=state,
                county=county,
                owner_name=couple,            # the couple — owner->GIS enricher resolves a property
                defendant=spouse_name or None,
                case_number=license_number,
                description=desc[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sc_probate_net": {
                    "record_kind": "marriage",
                    "couple": couple,
                    "application_date": appl_date,
                    "marriage_date": marriage_date or None,
                    "party": spouse_addr,
                }},
            )
        )
    return out


async def _search_county(
    client: httpx.AsyncClient,
    dropdown_value: str,
    county: str,
    state: str,
    marriage: bool,
    surname: str,
) -> list[Listing]:
    """Run one (county, surname) name search via the two-step postback."""
    # Step 1: load the form for hidden fields + session cookie.
    r0 = await client.get(BASE_URL)
    r0.raise_for_status()
    fields = _hidden_fields(r0.text)

    # Step 2: county-change postback (selects county; flips marriage mode).
    form = dict(fields)
    form["__EVENTTARGET"] = PRE + "ddlCounties"
    form["__EVENTARGUMENT"] = ""
    form[PRE + "ddlCounties"] = dropdown_value
    form[PRE + "rblPartyType"] = "0"
    r1 = await client.post(BASE_URL, data=form)
    r1.raise_for_status()
    fields = _hidden_fields(r1.text)

    # Step 3: the search postback.
    form = dict(fields)
    form["__EVENTTARGET"] = PRE + "btnSearch"
    form["__EVENTARGUMENT"] = ""
    form[PRE + "ddlCounties"] = dropdown_value
    form[PRE + "tbLastName"] = surname
    form[PRE + "tbFirstName"] = ""
    form[PRE + "tbMiddleName"] = ""
    form[PRE + "tbCaseNumber"] = ""
    form[PRE + "rblPartyType"] = "0"
    r2 = await client.post(BASE_URL, data=form)
    r2.raise_for_status()

    if marriage:
        return _parse_marriage(r2.text, county, state)
    return _parse_probate(r2.text, county, state)


class SCProbateNet(BaseScraper):
    """southcarolinaprobate.net centralized probate + marriage name search."""

    slug = "counties_sc.sc_probate_net"
    name = "SC Probate Net (centralized probate + marriage)"
    category = "probate"
    expected_min_count = 0  # only Charleston posts here today; others legit-empty
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        cfg = RuntimeConfig.from_env()
        out: list[Listing] = []
        # Dedupe across surname sweeps + counties on (county, kind, case#).
        seen: set[tuple] = set()

        async with httpx.AsyncClient(
            headers={"User-Agent": cfg.user_agent},
            follow_redirects=True,
            timeout=cfg.request_timeout_s + 30.0,
        ) as client:
            # Sequential per (county, surname) — compliant, one request at a time.
            for dropdown_value, county, state, marriage in COUNTIES:
                county_hits = 0
                for surname in SURNAMES:
                    try:
                        listings = await _search_county(
                            client, dropdown_value, county, state, marriage, surname
                        )
                    except httpx.HTTPError as exc:
                        log.warning(
                            "sc_probate_net.search_failed",
                            county=county, surname=surname,
                            error=str(exc)[:200],
                        )
                        continue
                    for li in listings:
                        kind = li.raw.get("sc_probate_net", {}).get("record_kind")
                        key = (li.county, kind, li.case_number)
                        if li.case_number and key in seen:
                            continue
                        seen.add(key)
                        out.append(li)
                        county_hits += 1
                    # Be polite to the shared county server between searches.
                    await asyncio.sleep(1.0)
                log.info(
                    "sc_probate_net.county_done",
                    county=county, marriage=marriage, count=county_hits,
                )
        return out
