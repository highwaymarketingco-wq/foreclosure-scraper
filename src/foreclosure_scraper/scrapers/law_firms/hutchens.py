"""Hutchens Law Firm — sales.hutchenslawfirm.com pending trustee sales (NC + SC).

Hutchens merged into FOUNDATION LEGAL GROUP, but the Foundation hub has no sale
feed of its own: foundationlegalgroup.com serves a 114-byte stub and
hutchenslawfirm.com still links out to sales.hutchenslawfirm.com. There is
deliberately no separate "foundation" scraper — that would double-count every
row. This module IS the Foundation NC/SC feed.

Verified live 2026-07-31:
  https://sales.hutchenslawfirm.com/NCfcSalesList.aspx  -> 233 pending sales
  https://sales.hutchenslawfirm.com/SCfcSalesList.aspx  -> 143 pending sales

Both are ASP.NET GridViews rendered ENTIRELY server-side — the grid's own pager
row reads "Displaying page 1 of 1" and the only __doPostBack on the page is
column sorting, so there is no pagination to follow and no postback to forge.

The two grids do NOT share a column layout, which is why columns are resolved
from the header row instead of fixed indices:
  NC: Case No. | SP# | County | Sale Date | Property Address | Property CSZ |
      Deed of Trust Book/Page | Bid Amount
  SC: Case No. | Case Docket# | County | Sale Date | Property Address |
      Property CSZ | Deed of Trust Book/Page | Bid Amount | Deficiency

Field notes the parser depends on:
  * "Case No." (2547-5868) is Hutchens' INTERNAL file number. The court number is
    "SP#" on NC (25SP000046-980) and "Case Docket#" on SC (2022-CP-23-00802) —
    that is what enrichment_case_detail (`\\d{4}-CP-\\d{2}-\\d{4,6}`) and
    enrichment_court_bid (NC SP regex) match on, so the court number goes in
    `case_number` and the firm file number goes in the description.
  * "Bid Amount" is free text: "Bid not available yet" (265 rows), "$49,489.91"
    (85 rows), or "Bid upset 04/03/2024, increasing bid to $746,000.00" (26 rows).
    The old digit-anywhere regex read the "04" out of the upset DATE and stored a
    $4.00 opening bid on all 26 of those. Only a $-anchored amount is accepted now.
  * "Deed of Trust Book/Page" is present on 374 of 376 rows and may carry a book
    prefix ("R 8776 / 2360", "MO 5421 / 1478", "Volume 125 / 2213"). Recorded into
    raw["rod_docs"] so the ROD / payoff lookups can use it.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ._footprint import in_footprint, keep, normalize_county

log = structlog.get_logger()

URLS = (
    ("https://sales.hutchenslawfirm.com/NCfcSalesList.aspx", "NC"),
    ("https://sales.hutchenslawfirm.com/SCfcSalesList.aspx", "SC"),
)

#: Header label -> canonical field. Both grids are covered; a label the firm
#: renames simply drops out of the map and its field goes null rather than
#: silently shifting every column after it (what fixed indices would do).
_HEADER_MAP = {
    "case no.": "firm_file_no",
    "case no": "firm_file_no",
    "sp#": "court_case",
    "case docket#": "court_case",
    "county": "county",
    "sale date": "sale_date",
    "property address": "street",
    "property csz": "csz",
    "deed of trust book/page": "book_page",
    "bid amount": "bid",
    "deficiency": "deficiency",
}

#: "Charlotte, NC 28202" -> city, zip
_CSZ_RE = re.compile(r"^\s*(?P<city>[A-Za-z .'\-]+?)\s*,\s*[A-Z]{2}\s+(?P<zip>\d{5})(?:-?\d{4})?\s*$")
#: Only a $-anchored figure is a real bid. Multiple matches -> the LAST one, which
#: is the "increasing bid to $X" amount on an upset row.
_DOLLAR_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
_UPSET_DATE_RE = re.compile(r"upset\s+(\d{1,2}/\d{1,2}/\d{2,4})", re.I)


def _header_indices(grid) -> dict[str, int]:
    """Map canonical field -> column index using the grid's own header row."""
    header = None
    for row in grid.css("tr"):
        ths = row.css("th")
        if ths:
            header = ths
            break
    if not header:
        return {}
    out: dict[str, int] = {}
    for idx, th in enumerate(header):
        label = " ".join(th.text(strip=True).lower().split())
        field = _HEADER_MAP.get(label)
        if field and field not in out:
            out[field] = idx
    return out


def _cell(cells: list[str], idx: int | None) -> str | None:
    if idx is None or idx >= len(cells):
        return None
    return cells[idx].strip() or None


def _parse_bid(raw_bid: str | None) -> tuple[float | None, str | None]:
    """-> (amount, upset_date_str). 'Bid not available yet' -> (None, None)."""
    if not raw_bid:
        return None, None
    amounts = _DOLLAR_RE.findall(raw_bid)
    amount = None
    if amounts:
        try:
            amount = float(amounts[-1].replace(",", ""))
        except ValueError:
            amount = None
        if amount is not None and amount <= 0:
            amount = None
    upset = _UPSET_DATE_RE.search(raw_bid)
    return amount, (upset.group(1) if upset else None)


def _split_book_page(raw_bp: str | None) -> tuple[str | None, str | None]:
    """'R 8776 / 2360' -> ('R 8776', '2360'); '1241 / 2' -> ('1241', '2')."""
    if not raw_bp:
        return None, None
    text = " ".join(raw_bp.split())
    if not text:
        return None, None
    if "/" in text:
        book, _, page = text.partition("/")
        return (book.strip() or None), (page.strip() or None)
    return text or None, None


def _parse_csz(raw_csz: str | None) -> tuple[str | None, str | None]:
    if not raw_csz:
        return None, None
    m = _CSZ_RE.match(" ".join(raw_csz.split()))
    if not m:
        return None, None
    return m.group("city").strip() or None, m.group("zip")


class Hutchens(BaseScraper):
    slug = "law_firms.hutchens"
    name = "Hutchens Law Firm (Foundation Legal Group)"
    category = "law_firm"
    timeout_s = 240.0
    expected_min_count = 20

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        total = 0
        failed: list[str] = []

        for url, state in URLS:
            try:
                html = await get_text(url, timeout=60.0)
            except Exception as exc:  # noqa: BLE001 — reported below
                failed.append(f"{state}: {str(exc)[:120]}")
                log.warning("hutchens.fetch_failed", state=state, error=str(exc)[:160])
                continue
            scraped, kept = self._parse_grid(html, url, state)
            total += scraped
            out.extend(kept)

        in_foot = sum(1 for li in out if in_footprint(li.county, li.state))
        log.info(
            "hutchens.counts",
            total_scraped=total,
            kept=len(out),
            in_footprint=in_foot,
            coastal_lane=len(out) - in_foot,
            failed=failed or None,
        )
        if failed and not out:
            # Both grids unreachable — raise so safe_run reports BLOCKED rather
            # than a clean-looking zero.
            raise RuntimeError(f"hutchens: no grid reachable ({'; '.join(failed)})")
        return out

    def _parse_grid(self, html: str, url: str, state: str) -> tuple[int, list[Listing]]:
        tree = HTMLParser(html)
        grid = tree.css_first("table[id*='SalesListGrid']") or tree.css_first("#SalesListGrid")
        if grid is None:
            log.warning("hutchens.grid_missing", state=state, url=url)
            return 0, []

        cols = _header_indices(grid)
        if cols.get("street") is None or cols.get("county") is None:
            log.warning("hutchens.header_unrecognized", state=state, columns=sorted(cols))

        scraped = 0
        kept: list[Listing] = []
        for row in grid.css("tr"):
            if row.css("th"):
                continue  # header row
            cells = [c.text(strip=True) for c in row.css("td")]
            if len(cells) < 6:
                continue  # the grid's "Change page: ..." pager row is a single cell
            li = self._row_to_listing(cells, cols, url, state)
            if li is None:
                continue
            scraped += 1
            if keep(li.county, li.state):
                kept.append(li)
        return scraped, kept

    def _row_to_listing(
        self, cells: list[str], cols: dict[str, int], url: str, state: str
    ) -> Listing | None:
        firm_file_no = _cell(cells, cols.get("firm_file_no"))
        court_case = _cell(cells, cols.get("court_case"))
        county = normalize_county(_cell(cells, cols.get("county")))
        date_raw = _cell(cells, cols.get("sale_date"))
        street = _cell(cells, cols.get("street"))
        city, zip_code = _parse_csz(_cell(cells, cols.get("csz")))
        book, page = _split_book_page(_cell(cells, cols.get("book_page")))
        bid, upset_date = _parse_bid(_cell(cells, cols.get("bid")))
        deficiency = _cell(cells, cols.get("deficiency"))

        if not street and not court_case and not firm_file_no:
            return None

        sale_date = None
        if date_raw:
            try:
                sale_date = dateparser.parse(date_raw)
            except (ValueError, TypeError, OverflowError):
                sale_date = None

        desc_bits = [
            f"Hutchens trustee sale — court case {court_case}" if court_case
            else "Hutchens trustee sale",
            f"firm file {firm_file_no}" if firm_file_no else "",
            f"deed of trust book/page {book}/{page}" if book and page else (
                f"deed of trust book {book}" if book else ""
            ),
            f"upset bid filed {upset_date}" if upset_date else "",
            f"deficiency {deficiency.lower()}" if deficiency else "",
        ]

        listing = Listing(
            source=self.slug,
            source_url=url,
            listing_type=ListingType.FORECLOSURE_SALE,
            property_kind=PropertyKind.UNKNOWN,
            street_address=street,
            city=city,
            state=state,
            zip_code=zip_code,
            county=county,
            sale_date=sale_date,
            case_number=court_case,
            opening_bid=bid,
            description=", ".join(b for b in desc_bits if b) or None,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        if book:
            listing.raw["rod_docs"] = [{
                "doc_type": "DEED OF TRUST",
                "book": book,
                "page": page,
                "amount": None,
                "recorded_date": None,
                "county": county,
                "state": state,
                "source": self.slug,
            }]
        return listing
