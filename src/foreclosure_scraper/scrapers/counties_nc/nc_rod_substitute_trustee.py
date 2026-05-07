"""NC Register of Deeds — pre-foreclosure recordings (Notice of Sale,
Substitute Trustee Deed, Lis Pendens) across in-scope NC counties.

Routes through the existing rod/aumentum / rod/cott / rod/cchs vendor
modules (already battle-tested for ASP.NET WebForms search) rather
than re-implementing per-vendor flows. Each vendor's
``discover_recent_nods()`` returns a list of RodDoc records filtered
to NOD-style document types within a date range.

Coverage (in-scope NC counties only after the 2026-05-07 scope rollback):

  Aumentum:  Buncombe (registerofdeeds.buncombecounty.org)
             Gaston   (deeds.gastongov.com)
  Cott:      Polk     (cotthosting.com/ncpolkexternal)
             Rutherford (cotthosting.com/NCRUTHERFORDEXTERNAL)
  CCHS:      Burke    (us5.courthousecomputersystems.com/burkenc)
             Lincoln  (us5.courthousecomputersystems.com/lincolnnc)
             Cleveland (us5.courthousecomputersystems.com/clevelandnc)

NOT YET COVERED (no ROD vendor mapped):
  Henderson, Mitchell, McDowell, Transylvania, New Hanover, Brunswick,
  Onslow, Lincoln (verify), Madison/Yancey/Haywood (these were
  intentionally dropped from scope per 2026-05-07b rollback).

Output: each RodDoc is converted into a Listing with:
  - listing_type = LIS_PENDENS (these are PRE-foreclosure leads — the
    actual sale hasn't happened yet)
  - sale_date = None (not in the recording — Notice of Sale lists a
    FUTURE date; we'd need to fetch the doc body to get it)
  - defendant = grantor (current owner against whom foreclosure is filed)
  - case_number = book/page or instrument_no
  - raw.nc_rod = {vendor, doc_type, recorded_date, book, page,
    instrument_no}

This is a LEAD source, not a sold-comp source. Post-sale recordings
("Trustee's Deed Upon Sale" with deed-tax stamps that encode the
hammer price) require extending each vendor module's discover_*
function to ALSO sweep post-sale doc types AND the parser to capture
the consideration column. That's a separate larger effort.

Note re: previous 'permitium' configuration: the URL
``https://buncombe-recordings.permitium.com/`` doesn't resolve on
public DNS — it appears to have been a misconfiguration. Buncombe's
actual ROD is the Aumentum-hosted URL above, verified reachable via
the rod/aumentum.py module.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...rod import aumentum, cchs, cott
from ...rod.models import RodDoc

log = structlog.get_logger()


# In-scope NC counties paired with the vendor module that handles them.
# Order matters only for determinism in logs.
SOURCES: list[tuple[str, object, str]] = [
    # (county_name, vendor_module, vendor_label)
    ("Buncombe", aumentum, "aumentum"),
    ("Gaston",   aumentum, "aumentum"),
    ("Polk",       cott,   "cott"),
    ("Rutherford", cott,   "cott"),
    ("Burke",     cchs,    "cchs"),
    ("Lincoln",   cchs,    "cchs"),
    ("Cleveland", cchs,    "cchs"),
]

LOOKBACK_DAYS = 60
MAX_DOCS_PER_COUNTY = 80


def _doc_to_listing(doc: RodDoc, vendor_label: str) -> Listing:
    """Convert a RodDoc into a Listing for the foreclosure pipeline."""
    # Case-number-style identifier: prefer instrument#, then book/page
    case_id = None
    if doc.instrument_no:
        case_id = f"INST-{doc.instrument_no}"
    elif doc.book and doc.page:
        case_id = f"BK{doc.book}-PG{doc.page}"

    # Source URL: link back to the vendor's search page so the investor
    # can pull the actual recorded document (signature page + deed of
    # trust details). Best-effort — the vendor module knows the host.
    source_url = "https://www.nccourts.gov/"
    if vendor_label == "aumentum":
        host = aumentum.AUMENTUM_COUNTIES.get(("NC", doc.county))
        if host:
            source_url = host.rstrip("/") + "/SrchName.aspx"
    elif vendor_label == "cott":
        host = cott.COTT_COUNTIES.get(("NC", doc.county))
        if host:
            source_url = host.rstrip("/") + "/SrchName.aspx"
    elif vendor_label == "cchs":
        slug = cchs.CCHS_COUNTIES.get(("NC", doc.county))
        if slug:
            source_url = (
                f"https://us5.courthousecomputersystems.com/{slug}/searchonline.asp"
            )

    return Listing(
        source="counties_nc.nc_rod_substitute_trustee",
        source_url=source_url,
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=doc.county,
        case_number=case_id,
        defendant=doc.grantor,
        plaintiff=doc.grantee,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "nc_rod": {
                "vendor": vendor_label,
                "doc_type": doc.doc_type,
                "recorded_date": doc.recorded_date.isoformat() if doc.recorded_date else None,
                "book": doc.book,
                "page": doc.page,
                "instrument_no": doc.instrument_no,
                "grantor": doc.grantor,
                "grantee": doc.grantee,
            },
        },
    )


class NCRodSubstituteTrustee(BaseScraper):
    """NC ROD pre-foreclosure recordings across in-scope counties via
    rod/aumentum + rod/cott + rod/cchs."""

    slug = "counties_nc.nc_rod_substitute_trustee"
    name = "NC ROD pre-foreclosure recordings (7 in-scope counties)"
    category = "register_of_deeds"
    expected_min_count = 0
    requires_apify = False
    # The vendor modules use plain httpx + ASP.NET form posts (no JS) —
    # not Scrapling-required despite the prior misclassification.
    requires_render = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        per_county: dict[str, int] = {}
        for county, vendor, vendor_label in SOURCES:
            try:
                docs = await vendor.discover_recent_nods(
                    state="NC", county=county,
                    days_back=LOOKBACK_DAYS,
                    max_docs=MAX_DOCS_PER_COUNTY,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "nc_rod.vendor_failed",
                    county=county, vendor=vendor_label,
                    error=str(exc)[:200],
                )
                continue
            per_county[f"{county}/{vendor_label}"] = len(docs)
            for d in docs:
                # Vendor sometimes returns the wrong county (when a search
                # fans out across vendor's whole tenant); enforce.
                if d.county and d.county != county:
                    d.county = county
                out.append(_doc_to_listing(d, vendor_label))

        log.info(
            "nc_rod.done",
            total=len(out), per_county=per_county,
            counties_searched=len(SOURCES),
        )
        return out
