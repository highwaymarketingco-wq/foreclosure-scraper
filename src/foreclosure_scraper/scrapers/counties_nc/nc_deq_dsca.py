"""NC DEQ DSCA — Dry-Cleaning Solvent Cleanup Act facility lists.

REBUILT 2026-10-01 (HERMES sec 8 per-source audit), against the REAL data
source. A dry-cleaning facility (active, inactive, or closed) is a genuine
property-distress signal: DSCA exists because dry-cleaning solvents
(perchloroethylene) are a common source of soil/groundwater contamination,
and a site under DSCA compliance tracking carries real remediation exposure
that depresses marketability the same way a UST release or a recorded
land-use restriction does (see counties_generic.state_contamination, the
sibling environmental source fixed the same day).

DISABLED SINCE 2026-09-15 (see git history) because the page this module
used to target (``.../dry-cleaning-solvent-cleanup-act-program``) has no
site-list table at all, just prose and a sidebar-navigation table; the old
`<tr>` regex matched the nav table and emitted nav labels ("Public Notices",
"Contacts") as fake contamination-site listings.

THE REAL DATA lives on a DIFFERENT DEQ page
(``.../science-data-and-reports/dsca-site-listsfacility-inventories``) as
two separate downloadable .xlsx workbooks, both verified live 2026-10-01:

  "Active and Inactive Drycleaner Facilities (Excel)" -- currently-tracked
      sites; Service Type carries the "(Active)"/"(Inactive)" status inline
      ("Full Service (Active)", "Coin-Op Laundromat (Inactive)").
  "Closed Dry-Cleaner Facilities (Excel)" -- sites DEQ no longer inspects.
      Still a real signal: the solvent-contamination liability a closed
      facility leaves behind doesn't disappear when compliance tracking
      stops: it just becomes less visible, which if anything raises the risk
      that a buyer/lender finds out the hard way instead of from DEQ.

Both download links are Drupal media-entity URLs
(``/<slug>/download?attachment``) found by text-matching the anchor's own
visible link text ("EXCEL") next to each list's heading on the page --
no login, no CAPTCHA, a plain GET. Parsed with the existing
``_xlsx_stdlib`` helper (zipfile + ElementTree; this project carries no
openpyxl dependency) rather than a new third-party reader.

COLUMNS (both workbooks share the same shape; Closed drops the four
machine-count columns and renames "Inspected" to "Closed"):
    Facility ID | County | Inspector | Facility Name | Address | City | ZIP |
    Service Type | Inspected/Closed (Excel date serial) | Generator Status |
    # Machines | # Hal | # Petro | # Other

Filtered to this project's footprint counties only (``config.NC_COUNTIES``)
-- verified live 2026-10-01: 27 active/inactive + 31 closed = 58 footprint
rows out of 328 + 391 statewide.

Dateless: a compliance-tracking status is a standing condition, not a
scheduled event (same reasoning as every delinquent-tax roll in
``main.DATELESS_OK_SOURCES`` -- added there alongside this fix).

Free, public, no login, no CAPTCHA.
Slug: counties_nc.nc_deq_dsca
Category: environmental
ListingType: DISTRESSED
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...config import NC_COUNTIES
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind
from .._xlsx_stdlib import excel_serial_to_date, header_index, read_rows

log = structlog.get_logger()

SLUG = "counties_nc.nc_deq_dsca"
LIST_PAGE = ("https://www.deq.nc.gov/about/divisions/waste-management/"
             "science-data-and-reports/dsca-site-listsfacility-inventories")

FOOTPRINT_COUNTIES = frozenset(c.name for c in NC_COUNTIES)

# Each workbook's download link sits right after its own heading text on the
# list page; anchor on the heading so a future re-dated file (the URL embeds
# "february-2025") is still found without a hardcoded link.
_LINKS = (
    ("active_inactive", "Active and Inactive Drycleaner Facilities"),
    ("closed", "Closed Dry-Cleaner Facilities"),
)
_EXCEL_HREF_RE = re.compile(
    r'<a href="([^"]+/download\?attachment)"[^>]*>EXCEL</a>', re.I
)


def _clean(s: Optional[str]) -> Optional[str]:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s or None


def _zip5(z: Optional[str]) -> Optional[str]:
    z = (z or "").strip()
    m = re.match(r"(\d{5})", z)
    return m.group(1) if m else None


def find_excel_links(page_html: str) -> dict[str, str]:
    """{"active_inactive": url, "closed": url} for whichever lists are found
    on the page, resolved relative to the DEQ site root."""
    out: dict[str, str] = {}
    for key, heading in _LINKS:
        idx = page_html.find(heading)
        if idx < 0:
            continue
        # The EXCEL link for this list is the second doc link after the
        # heading (PDF comes first); search a bounded window right after it.
        window = page_html[idx: idx + 1200]
        m = _EXCEL_HREF_RE.search(window)
        if not m:
            continue
        href = m.group(1)
        if href.startswith("/"):
            href = "https://www.deq.nc.gov" + href
        out[key] = href
    return out


def parse_workbook(data: bytes, list_kind: str, page_url: str) -> list[Listing]:
    """One Listing per footprint-county row. ``list_kind`` is "active_inactive"
    or "closed" (only affects the status label and raw tagging -- both
    workbooks share the same column layout for the fields this reads)."""
    rows = read_rows(data)
    hdr = header_index(rows, ("facility id", "county", "address", "city", "zip"))
    if hdr is None:
        log.warning("nc_deq_dsca.header_not_found", list_kind=list_kind,
                    note="workbook layout may have changed")
        return []
    hdr_row, cols = hdr

    def col(name: str) -> Optional[int]:
        return cols.get(name)

    c_id, c_county, c_inspector, c_name, c_addr, c_city, c_zip, c_svc, c_date, c_gen = (
        col("facility id"), col("county"), col("inspector"), col("facility name"),
        col("address"), col("city"), col("zip"), col("service type"),
        col("inspected") if col("inspected") is not None else col("closed"),
        col("generator status"),
    )

    out: list[Listing] = []
    now = datetime.utcnow()
    for row in rows[hdr_row + 1:]:
        county = _clean(row[c_county]) if c_county is not None and c_county < len(row) else None
        if not county or county not in FOOTPRINT_COUNTIES:
            continue

        def get(c: Optional[int]) -> Optional[str]:
            return _clean(row[c]) if c is not None and c < len(row) else None

        facility_id = get(c_id)
        name = get(c_name)
        addr = get(c_addr)
        city = get(c_city)
        zip_code = _zip5(get(c_zip))
        service_type = get(c_svc)
        generator = get(c_gen)
        date_val = excel_serial_to_date(get(c_date)) if c_date is not None else None

        status = "closed" if list_kind == "closed" else (
            "active" if service_type and "inactive" not in service_type.lower()
            else "inactive" if service_type else None
        )

        desc_bits = [b for b in (name, service_type,
                                 f"status: {status}" if status else None) if b]
        description = f"{county} County NC — " + " — ".join(desc_bits) if desc_bits else \
            f"{county} County NC dry-cleaner facility"

        out.append(Listing(
            source=SLUG,
            source_url=page_url,
            listing_type=ListingType.DISTRESSED,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county=county,
            street_address=addr,
            city=city,
            zip_code=zip_code,
            description=description[:300],
            first_seen=now,
            last_seen=now,
            raw={
                "nc_deq_dsca": {
                    "facility_id": facility_id,
                    "facility_name": name,
                    "inspector": get(c_inspector),
                    "service_type": service_type,
                    "generator_status": generator,
                    "status": status,
                    "list_kind": list_kind,
                    "status_date": date_val.date().isoformat() if date_val else None,
                }
            },
        ))
    return out


class NCDEQDSCA(BaseScraper):
    slug = SLUG
    name = "NC DEQ DSCA Dry-Cleaner Facility Lists (footprint counties)"
    category = "environmental"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        try:
            page_html = await get_text(LIST_PAGE, impersonate=True, timeout=40.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("nc_deq_dsca.page_fail", error=str(exc)[:160])
            return []
        if not page_html or len(page_html) < 500:
            return []

        links = find_excel_links(page_html)
        if not links:
            log.warning("nc_deq_dsca.no_links_found",
                        note="page layout may have changed -- neither EXCEL link found")
            return []

        out: list[Listing] = []
        for list_kind, url in links.items():
            try:
                data = await get_bytes(url, timeout=40.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("nc_deq_dsca.download_fail", list_kind=list_kind, error=str(exc)[:160])
                continue
            if not data or data[:2] != b"PK":
                log.warning("nc_deq_dsca.not_xlsx", list_kind=list_kind)
                continue
            try:
                rows = parse_workbook(data, list_kind, LIST_PAGE)
            except Exception as exc:  # noqa: BLE001
                log.warning("nc_deq_dsca.parse_fail", list_kind=list_kind, error=str(exc)[:160])
                continue
            out.extend(rows)
            log.info("nc_deq_dsca.list_done", list_kind=list_kind, rows=len(rows))

        log.info("nc_deq_dsca.done", count=len(out))
        return out
