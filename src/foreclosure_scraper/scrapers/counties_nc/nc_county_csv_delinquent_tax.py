"""NC county delinquent-tax rolls published as free .gov CSV downloads — the
full NCGS 105-369 roll for counties that self-host a machine-readable list
(FREE, no login).

CSV sibling of nc_county_pdf_delinquent_tax.py (PDF advertisements) and
nc_ptscloud_delinquent_tax.py (the API counties). Each county here posts its
delinquent-taxpayer report as a plain CSV; one config dict per county maps the
CSV's column headers to our roles, because headers vary by county.

New Hanover's CSV carries the property LOCATION (situs), so these leads land
with a real street address and skip the name->parcel resolver entirely. The CSV
has one row per (parcel, bill year); we aggregate to one lead per parcel with the
SUMMED back-tax owed across years. Amount is tax OWED -> raw['tax_owed'] (via
enrichment_tax_owed), NOT tax_value. Gate off with FORECLOSURE_NC_CSV_TAX=0.
When a county rotates its DocumentCenter file id, update the URL here.

FIXED 2026-10-03 (extraction-completeness audit, batch 4): the CSV's own
header is "Customer Name,Property ID,Property Location,Bill Year,Bill
Number,Total Receivable" -- live-pulled (3,544 rows, 100% filled) and
confirmed "Bill Number" (the county's own per-year tax-bill id, e.g.
"16000250") was read nowhere, dropped on every row. Wired into
raw['bill_numbers'] as a {year: bill_number} map (629 of the 1,404 parcels
here carry 2+ billing years, so a flat list would silently lose the
year<->bill pairing) -- a real per-bill reference id for any future county
tax-bill lookup/payment-portal integration.

FIXED 2026-11-16/17 (gap_matrix "no source known" tax-cluster survey): two
real issues, found live.

(1) SILENTLY BROKEN since some point before 2026-11: the county rotated the
file AT THE SAME DocumentCenter URL from a real CSV to an .xlsx ("November
2026 Delinquent Taxpayers_...xlsx", content-type
application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, ZIP
signature "PK\x03\x04"). The old code's own "is this a CSV?" guard only
recognized a PDF (`%PDF`) or an HTML error page (`<`) as a moved-document
signal, so the ZIP header fell through to `csv.DictReader` and either raised
_csv.Error ("new-line character seen in unquoted field") or, worse, silently
read zero valid rows — a classic silent-200 failure (feedback_silently_
broken_or_stale_producer_2026-10-28.md), not a real "no source" gap. Live
XML inside that zip (verified 2026-11-17: xl/worksheets/sheet1.xml +
xl/sharedStrings.xml) has the IDENTICAL header row and column names the CSV
always had ("Customer Name", "Property ID", "Property Location", "Bill
Year", "Bill Number", "Total Receivable") — same vendor export, same
schema, just a different container. Added a stdlib-only (zipfile +
xml.etree, no new dependency) `_parse_xlsx` sibling to `_parse_csv`, and the
fetcher now dispatches on the response's own byte signature instead of
assuming CSV.

(2) multi_year_delinquent_tax / two_year_delinquent gap: this scraper
already aggregates every (parcel, bill-year) row and keeps the full `years`
set per parcel (see `_parse_csv`/`_aggregate_rows` below) — direct,
zero-inference evidence of how many distinct tax years are unpaid on a
parcel — but never wrote gap_matrix.py's own `raw['multi_year_delinquent_tax']`
/ `raw['two_year_delinquent']` keys, only its own namespaced
`raw['nc_county_csv_delinquent_tax']` block, so New Hanover showed as
"no source known" for both columns despite the roll being read every run.
Live-measured 2026-11-17 (the real .xlsx, 1,270 distinct parcels): 579
parcels (45.6%) carry 2+ distinct bill years -- a real, substantial
multi-year population, not a rounding error. Now stamps both raw keys
directly from the same `years` set: `multi_year_delinquent_tax` only on a
genuine 2+-year hit (matching this column's own doc, "present" IS the hit --
see gap_matrix.py SIMPLE_PRESENCE_COLS), and `two_year_delinquent` always
(its own `is_two_year_plus` flag carries the true/false, and any dict here
already satisfies gap_matrix.py's "checked" test). A genuinely single-year
parcel also stamps `raw['_nc_csv_tax_mydt_checked']` (same shadow-key
pattern as Gaston/Pasquotank's own `_gaston_mydt_checked` /
`_pasquotank_tax_checked`, added to gap_matrix.py's checked_columns() the
same way) so a real negative screen is never miscounted as unchecked.
"""
from __future__ import annotations

import csv
import io
import os
import zipfile
from datetime import datetime
from typing import Iterable
from xml.etree import ElementTree as ET

import structlog

from ...base_scraper import BaseScraper
from ...layer_guard import LayerHarvest
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_XLSX_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

COUNTIES: dict[str, dict] = {
    "New Hanover": {
        "url": "https://www.nhcgov.com/DocumentCenter/View/11283/Delinquent_Taxpayers_Report_CSV",
        "cols": {
            "owner": "Customer Name",
            "parcel": "Property ID",
            "situs": "Property Location",
            "amount": "Total Receivable",
            "year": "Bill Year",
            "bill_number": "Bill Number",
        },
    },
}


def _money(s: str | None) -> float | None:
    try:
        f = float((s or "").replace(",", "").replace("$", "").strip() or 0)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _clean(s: str | None) -> str | None:
    return " ".join((s or "").split()).strip() or None


def _aggregate_rows(rows: Iterable[dict], cols: dict) -> list[dict]:
    """Aggregate the (parcel, bill-year) rows into one dict per parcel with the
    summed owed amount and the year span. Shared by the CSV and .xlsx readers --
    both hand this the same shape (plain str-keyed dict per row, BOM/whitespace
    already stripped from keys)."""
    agg: dict[str, dict] = {}
    for row in rows:
        parcel = _clean(row.get(cols["parcel"]))
        amt = _money(row.get(cols["amount"]))
        if not parcel or amt is None:
            continue
        rec = agg.setdefault(parcel, {
            "owner": _clean(row.get(cols["owner"])),
            "situs": _clean(row.get(cols.get("situs", ""))),
            "amount": 0.0,
            "years": set(),
            "bill_numbers": {},
        })
        rec["amount"] += amt
        yr = _clean(row.get(cols.get("year", "")))
        if yr:
            rec["years"].add(yr)
            bill_no = _clean(row.get(cols.get("bill_number", "")))
            if bill_no:
                # One bill number per billing year -- keyed by year, not a
                # flat list, so a multi-year parcel never loses the pairing.
                rec["bill_numbers"][yr] = bill_no
    return [dict(parcel=p, **v) for p, v in agg.items()]


def _parse_csv(text: str, cols: dict) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    # DictReader keys can carry a BOM on the first header; normalize.
    rows = ({(k or "").lstrip("﻿").strip(): v for k, v in raw_row.items()}
            for raw_row in reader)
    return _aggregate_rows(rows, cols)


def _parse_xlsx(content: bytes, cols: dict) -> list[dict]:
    """Stdlib-only (zipfile + xml.etree) reader for the .xlsx sibling of the
    CSV format above -- no openpyxl dependency needed for one sheet of plain
    string/number cells. An .xlsx is a zip of XML parts; shared strings (every
    text cell) live once in xl/sharedStrings.xml and are referenced by index
    from the sheet's own <c t="s"><v>IDX</v></c> cells, while numeric cells
    carry their literal value directly."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", _XLSX_NS):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", _XLSX_NS)))
        sheet_names = sorted(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet"))
        if not sheet_names:
            return []
        sheet = ET.fromstring(zf.read(sheet_names[0]))

    def cell_val(c):
        v = c.find("m:v", _XLSX_NS)
        if v is None or v.text is None:
            return None
        return shared[int(v.text)] if c.get("t") == "s" else v.text

    xml_rows = sheet.findall(".//m:sheetData/m:row", _XLSX_NS)
    if not xml_rows:
        return []
    header = [cell_val(c) for c in xml_rows[0].findall("m:c", _XLSX_NS)]

    def _rows() -> Iterable[dict]:
        for xr in xml_rows[1:]:
            vals = [cell_val(c) for c in xr.findall("m:c", _XLSX_NS)]
            vals += [None] * (len(header) - len(vals))
            yield {h: v for h, v in zip(header, vals) if h}

    return _aggregate_rows(_rows(), cols)


def _to_listing(rec: dict, county: str, url: str) -> Listing:
    now = datetime.utcnow()
    owner = rec.get("owner")
    situs = rec.get("situs")
    amt = round(rec["amount"], 2)
    years = sorted(rec.get("years") or [])
    yr_span = f"{years[0]}-{years[-1]}" if len(years) > 1 else (years[0] if years else "")
    is_multi = len(years) >= 2
    raw: dict = {
        "nc_county_csv_delinquent_tax": {
            "county": county,
            "county_id": rec["parcel"],
            "id_is_parcel": True,
            "principal_tax_due": amt,   # OWED, not value
            "bill_years": years,
            "year_span": yr_span,
            "bill_numbers": rec.get("bill_numbers") or None,
            "owner": owner,
            "situs": situs,
        },
        # two_year_delinquent's own "checked" test is just "any dict present"
        # (gap_matrix.py _EMPTY check), so this is honest either way: True on
        # a real 2+-year parcel, False (still a real screen) on a 1-year one.
        "two_year_delinquent": {
            "is_two_year_plus": is_multi,
            "years_delinquent": len(years),
            "bill_years": years,
            "source": "nc_county_csv_delinquent_tax",
        },
    }
    if is_multi:
        # multi_year_delinquent_tax is a SIMPLE_PRESENCE_COLS column (presence
        # IS the hit) -- only stamp it on a genuine 2+-year parcel.
        raw["multi_year_delinquent_tax"] = {
            "years_delinquent": len(years), "bill_years": years,
            "source": "nc_county_csv_delinquent_tax",
        }
    else:
        # a genuinely single-year parcel is still a real screen, not an
        # unchecked row -- same shadow-key pattern as Gaston/Pasquotank's
        # own _gaston_mydt_checked / _pasquotank_tax_checked (gap_matrix.py
        # checked_columns() extended to match, 2026-11-17).
        raw["_nc_csv_tax_mydt_checked"] = True
    return Listing(
        source="counties_nc.nc_county_csv_delinquent_tax",
        source_url=url,
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        owner_name=owner,
        defendant=owner,
        street_address=situs,          # county-provided situs — no resolver needed
        parcel_id=rec["parcel"],
        foreclosure_process="tax",
        description=(f"{owner or ''} — {county} NC delinquent tax "
                     f"${amt:,.0f} owed ({rec['parcel']})")[:300],
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


class NCCountyCsvDelinquentTax(BaseScraper):
    slug = "counties_nc.nc_county_csv_delinquent_tax"
    name = "NC County Delinquent-Tax CSV Rolls (New Hanover)"
    category = "county_tax"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_NC_CSV_TAX") == "0":
            return []
        out: list[Listing] = []
        # Each county is a big block of leads behind ONE annual CSV. A file that
        # 404s or silently changes shape leaves a hole that passes for normal
        # shrinkage — LayerHarvest declares the set and fails loud instead.
        guard = LayerHarvest(self.slug, list(COUNTIES))
        async with client(timeout=60.0) as c:
            with guard:
                for county, cfg in COUNTIES.items():
                    out.extend(await guard.harvest(
                        county, self._county_fetcher(c, county, cfg)))
        return out

    @staticmethod
    def _county_fetcher(c, county: str, cfg: dict):
        async def _one() -> list[Listing]:
            r = await c.get(cfg["url"], headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                raise RuntimeError(f"{county}: HTTP {r.status_code}")
            head = r.content[:16].lstrip(b"\xef\xbb\xbf").lstrip()
            # 2026-11-17: New Hanover rotated this SAME DocumentCenter URL from a
            # real CSV to an .xlsx (ZIP signature "PK\x03\x04") -- that is a valid,
            # expected shape now, not a moved-document failure, so it is dispatched
            # to _parse_xlsx rather than raising. Only a PDF or an HTML error page
            # still means "the county moved the document".
            if head[:4] == b"PK\x03\x04":
                recs = _parse_xlsx(r.content, cfg["cols"])
            elif head[:4] == b"%PDF" or head[:1] == b"<":
                raise RuntimeError(
                    f"{county}: response is not a CSV/.xlsx (starts {r.content[:16]!r}) "
                    "— the county most likely moved the document")
            else:
                text = r.content.decode("utf-8-sig", errors="replace")
                recs = _parse_csv(text, cfg["cols"])
            leads = [_to_listing(rec, county, cfg["url"]) for rec in recs]
            log.info("nc_csv_tax.county_done", county=county, leads=len(leads))
            return leads

        return _one
