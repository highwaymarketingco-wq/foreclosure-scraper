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

As of build time Charleston Probate + Charleston Marriage are the only
in-footprint courts that actually post here; Colleton, Georgetown, Oconee, and
Cherokee return "no records" (those courts don't feed this aggregator). They're
still queried every run so they auto-light-up if the court starts publishing. To
surface a broad set without a per-name guessing game, we sweep a short list of
common SC surnames per county and dedupe on the case/license number.

BREADTH EXTENSION (2026-10-02): this aggregator's county dropdown lists every
court that participates, statewide, NOT only the 18-county flip footprint --
verified live by reading the real ``ddlCounties`` <select> (Aiken, Bamberg,
Barnwell, Charleston, Cherokee, Chester, Colleton, Dorchester, Florence,
Georgetown, Kershaw, Lancaster, Marlboro, Oconee, Orangeburg, Sumter, York).
2026-10-02 EXTENSION — gvDocket (the per-case document/activity log). Every
case's response ALSO ships a third sub-grid, `..._gvDocket`, positioned right
after `..._gvParties` -- fetched on every run already (same response), but
never parsed at all until now. Live-verified (Charleston Probate, "Smith"):
it is a two-column (Activity, Description) log of every filed document/court
activity, e.g. "DEATH CERTIFICATE", "CREDITORS NOTICE",
"INVENTORY/APPRAISEMENT", "INFORMATION TO HEIRS AND DEVISEES" (SC's statutory
notice to known heirs/devisees -- Probate Code 62-3-705/-706), "BOND WAIVER",
"RENUNCIATION FORM". Checked precisely, not assumed: across 20 real docket
tables / ~800 rows sampled live, NOT ONE row anywhere on this site carries a
dollar figure or any value/bond-amount column -- the grid is a pure
document-TYPE log (what was filed, occasionally when), never the filed
document's own content. The actual Inventory & Appraisement dollar total,
and the actual names on an "Information to Heirs" filing, live only inside
the scanned PDF itself -- on Charleston's shape there is no link to it at
all; on York/Dorchester's shape (see `_docket_entries()`'s own docstring)
there IS a per-document link, but it opens a PAID viewer, confirmed live, so
neither shape yields the content for free either way. So `_docket_entries()`
below gives the closest
FREE, LIVE-CONFIRMED signal this source has for either ask: whether an
inventory/appraisement was filed at all (the nearest free proxy to "does this
estate have a known asset value", never the value itself) and whether a
formal notice to heirs was filed at all (confirms heirs were identified and
notified, never their names). Both are real, previously-uncaptured facts,
not approximations of a number/name we are choosing not to show.

Probed every one of those NOT already in COUNTIES with a single "Smith" search:
Dorchester Probate returned 20 real hits and York Probate returned 3; Aiken,
Bamberg, Barnwell, Chester, Kershaw, Lancaster, Orangeburg, Sumter, Florence and
Marlboro all came back "no records" (same legit-empty shape as Colleton/
Georgetown/Oconee/Cherokee above -- these courts don't feed this aggregator
either, so they are NOT added; re-check if that ever changes). Dorchester and
York are added below, Marriage variant included (same pattern as Charleston) so
a future marriage-license signal needs no further wiring. Neither is in the
18-county flip footprint, but PROBATE_NOTICE is a distressed-type lead, not a
flip, so both are admissible per config.in_scope_distressed regardless.
"""
from __future__ import annotations

import asyncio
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
    # 2026-10-02 BREADTH EXTENSION — verified live (see module docstring): both
    # return real estates/marriages today, unlike the legit-empty courts above.
    ("Dorchester Probate", "Dorchester", "SC", False),
    ("Dorchester Marriage", "Dorchester", "SC", True),
    ("York Probate", "York", "SC", False),
    ("York Marriage", "York", "SC", True),
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


#: Party "Type" values that identify the attorney of record (a distinct row
#: from the PR in the same gvParties grid -- live-verified 2026-10-01: a
#: Charleston Probate case's sub-grid carries BOTH a "PERSONAL REPRESENTATIVE"
#: row AND an "Attorney" row, each with its own full mailing address. Only the
#: PR was ever read; the attorney (HERMES sec 8's explicit "attorney/trustee"
#: field) was dropped on the floor.
_ATTORNEY_TYPES = ("attorney",)


def _pr_from_parties(party_table) -> tuple[str | None, dict | None, str | None, dict | None]:
    """Pull the Personal Representative AND the attorney of record (name +
    mailing address each) from a case's gvParties sub-grid.

    Returns (pr_name, pr_address_dict, attorney_name, attorney_address_dict).
    For a marriage license grid there is no PR/Attorney Type value, so the
    first two elements fall back to the first party row (the spouse) and the
    attorney pair is always (None, None) there -- unchanged prior behavior.
    """
    if party_table is None:
        return None, None, None, None
    rows = party_table.css("tr")
    if len(rows) < 2:
        return None, None, None, None
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
    pr_result: tuple[str, dict] | None = None
    attorney_result: tuple[str, dict] | None = None
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
        if pr_result is None and any(t in ptype for t in _PR_TYPES):
            pr_result = (name, addr)
        if attorney_result is None and any(t in ptype for t in _ATTORNEY_TYPES):
            attorney_result = (name, addr)
        # Keep scanning remaining rows regardless: a grid can carry both a PR
        # row and an attorney row, and we want both, not just the first match.
    pr_name, pr_addr = pr_result if pr_result else (first_pr if first_pr else (None, None))
    atty_name, atty_addr = attorney_result if attorney_result else (None, None)
    return pr_name, pr_addr, atty_name, atty_addr


#: Document/activity "Description" text patterns in the gvDocket log that map
#: to a real, free, live-confirmed signal (see the module docstring's
#: 2026-10-02 EXTENSION note for exactly what each one does and does NOT
#: prove -- never a dollar figure, never a heir's name).
_DOCKET_INVENTORY_RE = re.compile(r"\bINVENTORY\b", re.I)
_DOCKET_INFO_TO_HEIRS_RE = re.compile(
    r"INFO(?:RMATION)?\s*(?:TO)?\s*HEIRS|HEIRS\s+AND\s+DEVISEES", re.I)
_DOCKET_BOND_WAIVER_RE = re.compile(r"\bBOND\s+WAIVER\b", re.I)
_DOCKET_RENUNCIATION_RE = re.compile(r"\bRENUNCIATION\b", re.I)


def _docket_entries(docket_table) -> list[dict]:
    """Parse one case's gvDocket sub-grid into a real list of {activity,
    description[, document_url]} entries.

    Header-driven, not positional: Charleston's docket is 2 columns
    (Activity, Description), but York/Dorchester's is 3 (Document, Activity,
    Description) -- live-verified 2026-10-02, a column-position read would
    have silently misaligned every York/Dorchester row. Description is the
    document/activity TYPE string (never its dollar content -- see module
    docstring); Activity is usually blank (the row is just a filed-document
    marker) but occasionally carries a date for a court-ordered event.

    When a "Document" column is present it links to a per-document viewer --
    live-verified 2026-10-02 (York, a real "PAID NOTICE TO CREDITORS FEE"
    row's link) that this is a GleamTech DocumentUltimate viewer gated behind
    "Add to Cart" / "Add all pages to Cart" with a watermarked preview
    ("All watermarks on images will be removed upon purchase.") -- a PAID
    document purchase, not a free document image. Per this project's FREE-
    only rule the link is kept ONLY as an informational pointer for a human;
    it is never auto-followed/fetched here.
    """
    if docket_table is None:
        return []
    rows = docket_table.css("tr")
    if len(rows) < 2:
        return []
    header = [c.text(strip=True).lower() for c in rows[0].css("th, td")]

    def idx(name: str) -> int | None:
        for i, h in enumerate(header):
            if name in h:
                return i
        return None

    i_doc, i_act, i_desc = idx("document"), idx("activity"), idx("description")

    def cell(cells, i: int | None) -> str:
        return cells[i].text(strip=True) if i is not None and i < len(cells) else ""

    out: list[dict] = []
    for tr in rows[1:]:          # skip the header row
        cells = tr.css("td")
        if not cells:
            continue
        activity = cell(cells, i_act) or None
        description = cell(cells, i_desc) or None
        if not activity and not description:
            continue
        entry = {"activity": activity, "description": description}
        if i_doc is not None and i_doc < len(cells):
            a = cells[i_doc].css_first("a")
            href = a.attributes.get("href") if a is not None else None
            if href:
                entry["document_url"] = href  # PAID viewer -- never fetched
        out.append(entry)
    return out


def _docket_flags(entries: list[dict]) -> dict:
    """Derived booleans from the docket log -- the closest free signal this
    source exposes for an estate's financial/heir posture. Never a dollar
    figure, never a heir's name (neither exists anywhere on this site; see
    the module docstring's 2026-10-02 EXTENSION note, checked precisely
    against ~800 live docket rows, not assumed)."""
    joined = " | ".join(e.get("description") or "" for e in entries)
    return {
        "has_inventory_appraisement": bool(_DOCKET_INVENTORY_RE.search(joined)),
        "has_info_to_heirs": bool(_DOCKET_INFO_TO_HEIRS_RE.search(joined)),
        "has_bond_waiver": bool(_DOCKET_BOND_WAIVER_RE.search(joined)),
        "has_renunciation": bool(_DOCKET_RENUNCIATION_RE.search(joined)),
    }


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
    # Same per-case positional pairing as party_tables (gvParties and gvDocket
    # share one "ctlNN" index per case, confirmed live 2026-10-02).
    docket_tables = [
        tb for tb in tree.css("table")
        if (tb.attributes.get("id") or "").startswith(
            "ctl00_ContentPlaceHolder1_cgvCases_"
        ) and (tb.attributes.get("id") or "").endswith("_gvDocket")
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
        docket_table = docket_tables[case_i] if case_i < len(docket_tables) else None
        case_i += 1
        pr_name, pr_addr, atty_name, atty_addr = _pr_from_parties(party_table)
        docket = _docket_entries(docket_table)
        docket_flags = _docket_flags(docket)

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
                # HERMES sec 8 explicitly calls out attorney/trustee as a
                # required field; the gvParties sub-grid carries a distinct
                # Attorney row (name + full mailing address) beside the PR
                # row. `trustee` is this codebase's standing convention for
                # the attorney/firm handling a case (see law_firms/* and the
                # master-in-equity scrapers).
                trustee=atty_name or None,
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
                    "attorney": atty_addr,
                    # 2026-10-02: the per-case filed-document/activity log,
                    # never parsed before (see module docstring). A real
                    # list, not a joined string; the derived booleans are
                    # the closest free signal for estate value / heir
                    # notice this source has -- never the dollar figure or
                    # the heirs' names, neither of which exists here.
                    "docket": docket or None,
                    **docket_flags,
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
        spouse_name, spouse_addr, _atty_name, _atty_addr = _pr_from_parties(party_table)

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
    expected_min_count = 0  # Charleston/Dorchester/York post here today; the rest legit-empty
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
