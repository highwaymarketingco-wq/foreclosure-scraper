"""Orangeburg County SC — Tax Sale Overage Claim Lists.

Orangeburg County publishes YEARLY tax-sale surplus rosters: when a
delinquent parcel sells at auction for MORE than the taxes owed, the excess
("overage") is owed back to the FORMER owner. Unlike Aiken's and most other
SC counties' overage pages (disclaimer -> blank claim form + instructions
only, no roster -- see this module's sibling york_overage_claims.py
docstring and the 2026-10-04 Aiken investigation in docs/HERMES.md history),
Orangeburg's "Overage Claim Procedures" page links an actual per-year list
of claimants:

  https://www.orangeburgcounty.org/371/Overage-Claim-Procedures

Verified live 2026-10-04 (real browser render -- the three document links
are NOT plain <a href> tags findable by a naive querySelectorAll('a'); they
render through the CivicPlus DocumentCenter widget and only surfaced via the
accessibility tree / an href*="DocumentCenter" selector):

  2021 Overage Claims -> /DocumentCenter/View/2405                (text-layer PDF, 8 pages,  212 records)
  2022 Overage Claims -> /DocumentCenter/View/3074/2022-Overage-List (text-layer PDF, 4 pages, ~108 records)
  2023 Overage Claims -> /DocumentCenter/View/3534                (served with NO file extension in
                                                                     the URL and a misleading page
                                                                     title, but `file(1)` on the real
                                                                     downloaded bytes shows it is an
                                                                     actual .xlsx workbook, not a PDF
                                                                     -- 281 data rows, clean columns)

Both PDFs are TEXT-layer (pypdf extracts real characters, no OCR needed) --
unlike Laurens's scanned overage list (counties_sc.laurens_overage_claims).
One line per record: "SALE_NUMBER NAME TAX_MAP_NUMBER $OVERAGE". The 2021
PDF's extracted text uses non-breaking spaces (U+00A0) as word separators and
a Unicode hyphen (U+2010) inside the tax-map number instead of ASCII "-";
the 2022 PDF uses plain ASCII for both. The parser normalizes both before
matching so one regex covers every year's PDF.

Orangeburg County is OUTSIDE the project's narrow 18-county WNC+Upstate-SC
flip footprint (src/foreclosure_scraper/config.py SC_COUNTIES) but is not on
SCOPE_DENY_COUNTIES either. That narrow footprint only gates FLIP listing
types (FORECLOSURE_SALE/AUCTION/SHERIFF_SALE/HOA_SALE/REO) --
TAX_SALE_OVERAGE is not one of them (see main.py._FLIP_LISTING_TYPES /
_county_in_scope), so it is admitted for any non-denied NC/SC county via
in_scope_distressed(), the same rule that already lets
counties_sc.york_overage_claims (York is likewise outside the 18-county
list) reach the board. Confirmed by reading main.py directly, not assumed.

No situs lookup: Orangeburg is not one of the counties cached in
parcel_cache.py (checked 2026-10-04), so street_address is left unset
(the parcel/owner/amount alone are still a real, actionable lead).

Free, public, no login, no CAPTCHA, no disclaimer click-through.
Slug: counties_sc.orangeburg_overage_claims
Category: county_tax
ListingType: TAX_SALE_OVERAGE
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from .._xlsx_stdlib import cell, header_index, read_rows

log = structlog.get_logger()

HUB_URL = "https://www.orangeburgcounty.org/371/Overage-Claim-Procedures"

#: Direct document URLs, live-verified 2026-10-04. Hub-page discovery below
#: also runs on top so a newly-posted year is picked up with no code change,
#: the same "curated + self-healing" shape counties_sc.sc_flc uses.
KNOWN_DOCS: tuple[tuple[str, str], ...] = (
    ("https://www.orangeburgcounty.org/DocumentCenter/View/2405", "2021"),
    ("https://www.orangeburgcounty.org/DocumentCenter/View/3074/2022-Overage-List", "2022"),
    ("https://www.orangeburgcounty.org/DocumentCenter/View/3534", "2023"),
)

#: The 2021 PDF's extracted text sometimes carries a stray space between the
#: first TMS segment and its hyphen ("0278 -00-01-024.000" -- confirmed live
#: 2026-10-04, this is in the SOURCE text layer itself, not an extraction
#: artifact: it happens on ~90% of 2021's rows but 0% of 2022's), and at
#: least one row uses a hyphen instead of a period before the final segment
#: ("0174-19-08-003-000"). \s* around every hyphen and an either/or on the
#: final separator cover both without needing a second regex per year.
TMS_RE = re.compile(r"\d{3,4}\s*-\s*\d{2}\s*-\s*\d{2}\s*-\s*\d{3}(?:[.\-]\d{2,3})?")
SALE_NUMBER_RE = re.compile(r"^\d{8,9}")
AMOUNT_RE = re.compile(r"\$\s*([\d,]+\.\d{2})\s*$")

#: pypdf renders several distinct Unicode hyphen glyphs for the same ASCII "-"
#: depending on the source PDF's font; normalize them all before matching.
_HYPHEN_VARIANTS = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
})


def parse_overage_text(text: str) -> list[dict]:
    """Parse SALE NUMBER / NAME / TAX MAP NUMBER / OVERAGE rows out of a
    text-layer PDF page's extracted text -- one record per line.

    Each data row starts with an 8-9 digit sale number (the header row does
    not, so it's skipped automatically); the NAME is whatever sits between
    the sale number and the first TMS-shaped token; the dollar amount is
    anchored to end-of-line so it can't accidentally swallow a street number
    or TMS digit."""
    records: list[dict] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.replace("\xa0", " ").translate(_HYPHEN_VARIANTS)
        line = " ".join(line.split())
        if not line:
            continue
        sm = SALE_NUMBER_RE.match(line)
        if not sm:
            continue
        tm = TMS_RE.search(line, sm.end())
        am = AMOUNT_RE.search(line)
        if not tm or not am:
            continue
        name = line[sm.end():tm.start()].strip()
        if not name:
            continue
        try:
            amount = float(am.group(1).replace(",", ""))
        except ValueError:
            continue
        records.append({
            "sale_number": sm.group(0),
            "name": name,
            "map_number": re.sub(r"\s+", "", tm.group(0)),
            "amount": amount,
        })
    return records


def parse_overage_xlsx(data: bytes) -> list[dict]:
    """Parse the SALE NUMBER / NAME / TAX MAP NUMBER / OVERAGE columns out of
    the 2023+ list, which Orangeburg now publishes as a real .xlsx workbook
    served at a DocumentCenter URL with no file extension (confirmed live
    2026-10-04 via the magic-byte check in fetch() below -- the response
    starts with the ZIP/xlsx signature `PK\\x03\\x04`, not `%PDF`).

    Uses the repo's stdlib-only xlsx reader (scrapers/_xlsx_stdlib.py,
    already shared by charleston_tax_sale_xlsx.py / horry_delinquent_xlsx.py)
    rather than adding openpyxl as a new dependency."""
    records: list[dict] = []
    try:
        rows = read_rows(data, sheet=1)
    except Exception as exc:  # noqa: BLE001
        log.warning("orangeburg_overage.xlsx_open_fail", error=str(exc)[:160])
        return records
    hdr = header_index(rows, ("sale number", "name", "tax map number", "overage"))
    if not hdr:
        log.warning("orangeburg_overage.xlsx_header_mismatch",
                     head=rows[0] if rows else None)
        return records
    header_row, cols = hdr
    i_sale = cols.get("sale number")
    i_name = cols.get("name")
    i_map = cols.get("tax map number")
    i_amt = cols.get("overage")
    for row in rows[header_row + 1:]:
        sale_number = cell(row, i_sale)
        name = cell(row, i_name)
        map_number = cell(row, i_map)
        if not (sale_number and name and map_number):
            continue
        try:
            amount = float(cell(row, i_amt).replace(",", "").replace("$", ""))
        except ValueError:
            continue
        records.append({
            "sale_number": sale_number,
            "name": name,
            "map_number": map_number,
            "amount": amount,
        })
    return records


async def _discover_new_docs(c: httpx.AsyncClient, have: set[str]) -> list[tuple[str, str]]:
    """Hub-page discovery: pick up a year Orangeburg posts after this file is
    written, without a code change -- same self-healing shape as sc_flc.py's
    COUNTY_TAX_URLS sweep layered on top of its curated COUNTY_FLC_DOCS."""
    found: list[tuple[str, str]] = []
    try:
        resp = await c.get(HUB_URL, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("orangeburg_overage.hub_fetch_fail", error=str(exc)[:160])
        return found
    try:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(resp.text)
    except Exception:  # noqa: BLE001
        return found
    for a in tree.css("a[href*='DocumentCenter/View']"):
        href = urljoin(HUB_URL, a.attributes.get("href", "") or "")
        label = a.text(strip=True) or ""
        if not href or href in have:
            continue
        if not re.search(r"overage", label, re.I):
            continue  # skip the Agreement-and-Release blank form, etc.
        ym = re.search(r"(20\d{2})", label)
        found.append((href, ym.group(1) if ym else "unknown"))
    return found


class OrangeburgOverageClaims(BaseScraper):
    slug = "counties_sc.orangeburg_overage_claims"
    name = "Orangeburg County SC Overage Claim Lists"
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 50
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[tuple[str, str]] = set()
        docs = list(KNOWN_DOCS)

        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as c:
            have_urls = {u for u, _ in docs}
            docs.extend(await _discover_new_docs(c, have_urls))

            for url, year in docs:
                try:
                    resp = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    resp.raise_for_status()
                    data = resp.content
                except Exception as exc:  # noqa: BLE001
                    log.warning("orangeburg_overage.doc_fetch_fail", url=url, error=str(exc)[:160])
                    continue

                if data[:4] == b"PK\x03\x04":
                    records = parse_overage_xlsx(data)
                    doc_kind = "xlsx"
                elif data[:4] == b"%PDF":
                    try:
                        from pypdf import PdfReader
                        reader = PdfReader(io.BytesIO(data))
                        text = "\n".join(p.extract_text() or "" for p in reader.pages)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("orangeburg_overage.pdf_parse_fail", url=url, error=str(exc)[:160])
                        continue
                    records = parse_overage_text(text)
                    doc_kind = "pdf"
                else:
                    log.warning("orangeburg_overage.unknown_doc_type", url=url, head=data[:8])
                    continue

                now = datetime.utcnow()
                added = 0
                for rec in records:
                    if rec["amount"] <= 0:
                        continue  # already fully disbursed/escheated -- nothing left to claim
                    key = (rec["sale_number"], rec["map_number"])
                    if key in seen:
                        continue
                    seen.add(key)
                    added += 1
                    out.append(Listing(
                        source=self.slug,
                        source_url=url,
                        listing_type=ListingType.TAX_SALE_OVERAGE,
                        property_kind=PropertyKind.UNKNOWN,
                        state="SC",
                        county="Orangeburg",
                        parcel_id=rec["map_number"],
                        owner_name=rec["name"],
                        # sale_date intentionally left unset: overage sits unclaimed
                        # until someone files, a standing condition not a scheduled
                        # event (same reasoning as york_overage_claims.py). See this
                        # slug's entry in main.py.DATELESS_OK_SOURCES.
                        description=(f"Tax-sale overage of ${rec['amount']:,.2f} owed to former "
                                     f"owner {rec['name']} (parcel {rec['map_number']}, "
                                     f"sale #{rec['sale_number']}, {year} overage list)."),
                        first_seen=now,
                        last_seen=now,
                        raw={"tax_sale_overage": {
                            "amount": rec["amount"],
                            "sale_number": rec["sale_number"],
                            "map_number": rec["map_number"],
                            "list_year": year,
                            "doc_kind": doc_kind,
                        }},
                    ))
                log.info("orangeburg_overage.doc_done", url=url[-40:], year=year,
                         doc_kind=doc_kind, parsed=len(records), added=added)

        log.info("orangeburg_overage.done", docs=len(docs), usable=len(out))
        return out


if __name__ == "__main__":
    # Manual smoke: uv run python -m foreclosure_scraper.scrapers.counties_sc.orangeburg_overage_claims
    import asyncio

    async def _main() -> None:
        s = OrangeburgOverageClaims()
        rows = await s.safe_run()
        print("outcome:", s.last_outcome, "|", s.last_reason)
        print("rows:", len(rows))
        for r in rows[:15]:
            print(" -", r.parcel_id, "|", r.owner_name, "| $",
                  r.raw.get("tax_sale_overage", {}).get("amount"))

    asyncio.run(_main())
