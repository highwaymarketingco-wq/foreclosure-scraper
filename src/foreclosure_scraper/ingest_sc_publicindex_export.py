"""Offline parser for a SAVED SC Judicial Public Index search-results page.

The state-wide SC Judicial Public Index (``https://publicindex.sccourts.org/
<County>/PublicIndex/``) is an ASP.NET WebForms app gated behind an F5 / Shape
"Client Challenge" JS bot detector. The live scraper
(``scrapers.counties_sc.sc_public_index_lis_pendens``) drives it with a stealth
browser. This module does the OPPOSITE: it makes **no network request at all**.
A human operator runs the PISearch on their own browser (any court type / case
sub-type — Foreclosure, Partition, Ejectment/Possession, State Tax Lien, etc.),
saves the results page to disk (Ctrl-S / "Save Page As"), and drops the .html
file where the runner (``scripts/parse_publicindex_export.py``) can find it. We
only parse the public HTML they already retrieved.

Compliant by construction: this file imports NO HTTP client, browser driver, or
stealth-fetcher library — it takes an HTML string and returns Listings, nothing
more. ``tests/test_publicindex_export.py`` greps this very source to assert none
of those fetcher identifiers ever appear.

We REUSE the SearchResults table-parsing logic from the live scraper — the
``tr.standardRow / tr.altRow`` + ``table#ContentPlaceHolder1_SearchResults``
selectors, the ``title="Plaintiff VS Defendant"`` extraction, the case-number
normalization, and the ``§15-11-10`` county-from-case-number decode — but
GENERALIZE it beyond Foreclosure-420: each row's Case Sub-Type text is mapped to
the best-fit ``ListingType`` so partition / possession / tax-lien / judgment
lanes all flow through the same parser. The exact sub-type string is always
stashed in ``raw['sc_public_index']['subtype']`` so nothing is lost.
"""
from __future__ import annotations

import re
from datetime import datetime

from selectolax.parser import HTMLParser

from .enrichment_lis_pendens_resolver import SC_COUNTY_BY_CODE
from .models import Listing, ListingType, PropertyKind

SOURCE_SLUG = "counties_sc.sc_public_index_export"

# --------------------------------------------------------------------------- #
# Case-number handling.
#
# The live foreclosure scraper hard-codes the ``CP`` (Common Pleas) case type in
# its regexes. An offline export can span many case types (CP civil, and the
# magistrate / summary-court lanes), so we accept ANY 2-4 letter case-type token
# while still isolating the 2-digit county-venue code (position 2). SC Code
# §15-11-10 ties venue to the property county, so the venue code is the
# authoritative county for the listing.
#
# Accepted shapes (case-type token generalized from the CP-only originals):
#   * "2026CP4201547"    - cleaned form emitted in a result anchor
#   * "2026-CP-42-01547" - canonical dashed form
# --------------------------------------------------------------------------- #
CASE_RE_CLEAN = re.compile(r"\b(\d{4})([A-Z]{2})(\d{2})(\d{4,7})\b")
CASE_RE_DASHED = re.compile(r"\b(\d{4})-([A-Z]{2})-(\d{2})-(\d{4,7})\b")

# Title attribute we extract plaintiff/defendant from:
#   title="  Plaintiff Name VS Defendant Name [, defendant, et al]"
TITLE_VS_RE = re.compile(r"^\s*(.*?)\s+VS\s+(.*?)\s*$", re.IGNORECASE)

# Trailing role tags on a defendant name pulled from the title attr.
_DEF_ROLE_RE = re.compile(
    r",\s*(defendant|plaintiff)(\s*,\s*et\s*al\.?)?\s*$",
    re.IGNORECASE,
)

# Currency in a Judgment-amount column -> float.
_MONEY_RE = re.compile(r"[-+]?\$?\s*([\d,]+(?:\.\d{1,2})?)")


def _format_case_number(raw: str) -> str:
    """Normalize ``2026CP4201547`` to ``2026-CP-42-01547`` (canonical SC form).

    Generalized over the case-type token (CP/CV/SC/...) but otherwise mirrors
    ``sc_public_index_lis_pendens._format_case_number``."""
    raw = (raw or "").strip()
    if CASE_RE_DASHED.search(raw):
        return raw
    m = CASE_RE_CLEAN.search(raw)
    if m:
        yr, ct, cc, idx = m.groups()
        return f"{yr}-{ct}-{cc}-{idx}"
    return raw


def _county_from_case(case_number: str) -> str | None:
    """Decode the case-venue county from the 2-digit county code embedded in the
    SC case number (YYYY-XX-CC-NNNNN). Authoritative per SC Code §15-11-10."""
    if not case_number:
        return None
    m = CASE_RE_DASHED.search(case_number) or CASE_RE_CLEAN.search(case_number)
    if not m:
        return None
    # county code is the 3rd captured group in both patterns
    return SC_COUNTY_BY_CODE.get(m.group(3))


# --------------------------------------------------------------------------- #
# Sub-type -> ListingType lane mapping.
#
# Ordered list of (case-insensitive substring, ListingType). First match wins,
# so put more specific phrases before generic ones. The exact raw sub-type text
# is always preserved in raw['sc_public_index']['subtype'] regardless of lane.
#
# Enum gaps (no exact SC-flavored member exists) are noted inline; we use the
# closest real ListingType and never invent enum values.
# --------------------------------------------------------------------------- #
_SUBTYPE_LANES: tuple[tuple[str, ListingType], ...] = (
    # A filed CP foreclosure is a pre-sale lis pendens — matches the live
    # scraper's choice (ListingType.LIS_PENDENS), NOT FORECLOSURE_SALE (which is
    # the noticed auction, a later stage).
    ("foreclosure", ListingType.LIS_PENDENS),
    # Partition / forced-sale actions among co-owners. No dedicated enum member;
    # a partition is a court action clouding title that forces a sale, so the
    # closest fit is LIS_PENDENS (a pending suit against the property).
    ("partition", ListingType.LIS_PENDENS),
    # State / county tax lien. Closest real member is TAX_LIEN.
    ("state tax lien", ListingType.TAX_LIEN),
    ("tax lien", ListingType.TAX_LIEN),
    # Ejectment / eviction / possession (landlord-tenant, summary ejectment).
    # No eviction enum member; these are still name-indexed distress/court
    # signals, so the closest fit is LIS_PENDENS.
    ("ejectment", ListingType.LIS_PENDENS),
    ("possession", ListingType.LIS_PENDENS),
    ("eviction", ListingType.LIS_PENDENS),
    # Money judgment / transcript of judgment — a lien-generating court result.
    # Closest real member is TAX_LIEN? No: a civil judgment is a general lien,
    # not a tax lien. There is no JUDGMENT member, so map to LIS_PENDENS (the
    # generic court-distress lane) and rely on the captured judgment amount.
    ("judgment", ListingType.LIS_PENDENS),
)

# Sub-types we consider "known lanes" worth ingesting when the operator exported
# a mixed grid. Anything not matching any lane substring is skipped (keeps the
# lane counts honest) unless the caller opts to keep-all.
KNOWN_LANE_SUBSTRINGS: tuple[str, ...] = tuple(s for s, _ in _SUBTYPE_LANES)


def lane_for_subtype(subtype: str) -> ListingType | None:
    """Map a Case Sub-Type cell to the best-fit ListingType.

    Returns ``None`` when the sub-type doesn't match any known lane (caller
    decides whether to skip or keep-all). Case-insensitive substring match,
    first-match-wins in ``_SUBTYPE_LANES`` order."""
    s = (subtype or "").lower()
    if not s:
        return None
    for needle, lane in _SUBTYPE_LANES:
        if needle in s:
            return lane
    return None


def _parse_money(text: str) -> float | None:
    if not text:
        return None
    m = _MONEY_RE.search(text)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return val if val > 0 else None


def _county_url(county: str) -> str:
    return f"https://publicindex.sccourts.org/{county}/PublicIndex/"


def parse_publicindex_html(
    html: str,
    default_county: str | None = None,
    keep_all_subtypes: bool = False,
) -> list[Listing]:
    """Extract Listing rows from a saved SC Public Index SearchResults page.

    Reuses the live scraper's table selectors + title extraction, generalized
    across case sub-types. A disclaimer-only page (no results table) yields ``[]``.

    Args:
        html: the saved page's HTML text.
        default_county: fallback county when the case number can't decode one
            (e.g. the operator names the file/arg after a county).
        keep_all_subtypes: if True, rows whose sub-type matches no known lane are
            still emitted as ListingType.UNKNOWN (default False skips them).
    """
    out: list[Listing] = []
    if not html:
        return out

    tree = HTMLParser(html)
    grid = tree.css_first("table#ContentPlaceHolder1_SearchResults")
    if not grid:
        # Disclaimer-only / no-results page.
        return out

    headers = [h.text(strip=True).lower() for h in grid.css("th")]

    def col_idx(*names: str) -> int | None:
        for n in names:
            for i, h in enumerate(headers):
                if n in h:
                    return i
        return None

    case_i = col_idx("case number")
    filed_i = col_idx("filed date")
    status_i = col_idx("case status")
    subtype_i = col_idx("subtype", "sub-type", "sub type")
    party_type_i = col_idx("party type")
    name_i = col_idx("name")
    judgment_i = col_idx("judgment", "judgment amount", "amount")

    seen: set[str] = set()

    for row in grid.css("tr.standardRow, tr.altRow"):
        cells = row.css("td")
        if not cells:
            continue

        subtype = (
            cells[subtype_i].text(strip=True)
            if subtype_i is not None and subtype_i < len(cells)
            else ""
        )

        # Map sub-type -> lane. Skip unknown lanes unless keep_all_subtypes.
        lane = lane_for_subtype(subtype)
        if lane is None:
            if not keep_all_subtypes:
                continue
            lane = ListingType.UNKNOWN

        # Case number from the anchor inside the case cell (falls back to text).
        case_raw = ""
        if case_i is not None and case_i < len(cells):
            anchor = cells[case_i].css_first("a")
            case_raw = anchor.text(strip=True) if anchor else cells[case_i].text(strip=True)
        case_number = _format_case_number(case_raw)
        # Reject rows without a parseable SC case number (malformed rows).
        if not (CASE_RE_DASHED.search(case_number) or CASE_RE_CLEAN.search(case_number)):
            continue

        # Plaintiff / Defendant from the <td title="Plaintiff VS Defendant">.
        plaintiff = None
        defendant = None
        if case_i is not None and case_i < len(cells):
            title_attr = cells[case_i].attributes.get("title") or ""
            tm = TITLE_VS_RE.match(title_attr)
            if tm:
                plaintiff = tm.group(1).strip() or None
                defendant_raw = tm.group(2).strip()
                defendant = _DEF_ROLE_RE.sub("", defendant_raw).strip() or None

        # Fallback: Name + Party Type cell when the title attr is absent.
        if not plaintiff and not defendant and name_i is not None and party_type_i is not None:
            party_name = cells[name_i].text(strip=True) if name_i < len(cells) else ""
            party_type = (
                cells[party_type_i].text(strip=True).lower() if party_type_i < len(cells) else ""
            )
            if party_name:
                if "plaintiff" in party_type:
                    plaintiff = party_name
                elif "defendant" in party_type:
                    defendant = party_name

        # De-dupe on case number (the grid emits one row per party, so the same
        # case recurs — keep the first).
        if case_number in seen:
            continue
        seen.add(case_number)

        filed_date = None
        if filed_i is not None and filed_i < len(cells):
            txt = cells[filed_i].text(strip=True)
            if txt:
                try:
                    filed_date = datetime.strptime(txt, "%m/%d/%Y")
                except ValueError:
                    filed_date = None

        status_txt = (
            cells[status_i].text(strip=True)
            if status_i is not None and status_i < len(cells)
            else ""
        )

        judgment_amount = None
        if judgment_i is not None and judgment_i < len(cells):
            judgment_amount = _parse_money(cells[judgment_i].text(strip=True))

        # Authoritative county from the case# venue code (§15-11-10); fall back
        # to the caller-provided default (filename/arg) when it can't decode.
        listing_county = _county_from_case(case_number) or default_county

        source_url = (
            _county_url(listing_county) + f"CaseDetails.aspx?CaseNum={case_number}"
            if listing_county
            else f"https://publicindex.sccourts.org/PublicIndex/CaseDetails.aspx?CaseNum={case_number}"
        )

        parts = [
            f"SC Public Index {subtype or 'case'} {case_number}",
            f"({listing_county} County)" if listing_county else "",
            f"filed {filed_date.strftime('%Y-%m-%d')}" if filed_date else "",
            f"- {plaintiff} VS {defendant}" if plaintiff and defendant else "",
        ]
        description = " ".join(p for p in parts if p)[:500]

        out.append(
            Listing(
                source=SOURCE_SLUG,
                source_url=source_url,
                listing_type=lane,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county=listing_county,
                case_number=case_number,
                plaintiff=plaintiff,
                defendant=defendant,
                judgment_amount=judgment_amount,
                sale_date=None,
                description=description,
                auction_status=status_txt.lower() or None,
                first_seen=filed_date or datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "sc_public_index": {
                        "filed_date": filed_date.isoformat() if filed_date else None,
                        "status": status_txt,
                        "subtype": subtype,
                        "case_raw": case_raw,
                        "judgment_amount": judgment_amount,
                        "export": True,
                    }
                },
            )
        )

    return out
