"""SC Register-of-Deeds distress recordings via the Harris Acclaim Web adapter.

Closes the SC ROD gap for counties on AcclaimWeb (currently Pickens). Sweeps
recent recordings browserless/free (rod/acclaim.py) and emits properly-TYPED
leads — NOT fake foreclosure NODs (SC foreclosure is judicial; those are in the
courts, already covered):
  * deed of distribution / death  -> PROBATE_NOTICE (LIFE_EVENT distress)
  * tax / mechanics / other lien   -> TAX_LIEN       (FINANCIAL distress)

Each lead carries grantor (owner), parcel_id, instrument#, and legal description;
the address waterfall resolves the situs from the parcel via county GIS.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...rod import acclaim

_LOOKBACK_DAYS = 45


def _classify(doc_type: str) -> tuple[ListingType, str] | None:
    s = (doc_type or "").upper()
    if "REL" in s or "SAT" in s or "TERM" in s:   # resolutions, not distress
        return None
    if "DIST" in s or "DEATH" in s:
        return ListingType.PROBATE_NOTICE, "probate"
    if "LIEN" in s or "MECH" in s:
        return ListingType.TAX_LIEN, "lien"
    if "FORECLOS" in s or "TRUSTEE" in s or "LIS PENDENS" in s or "NOTICE OF SALE" in s:
        return ListingType.LIS_PENDENS, "foreclosure"
    return None


def _to_listing(doc, slug: str, source_url: str) -> Listing | None:
    cls = _classify(doc.doc_type)
    if cls is None:
        return None
    lt, kind = cls
    rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
    desc = (f"{doc.doc_type} recorded {rec}: {(doc.grantor or '?').strip()}"
            f"{' (' + doc.notes + ')' if doc.notes else ''}")
    raw: dict = {"rod": {"doc_type": doc.doc_type, "grantor": doc.grantor,
                         "grantee": doc.grantee, "book": doc.book, "page": doc.page,
                         "instrument": doc.instrument_no, "recorded": rec},
                 "acclaim_rod": True}
    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": doc.doc_type,
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    return Listing(
        source=slug, source_url=source_url,
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state=doc.state, county=doc.county,
        parcel_id=doc.parcel_id,
        defendant=(doc.grantor or "").strip() or None,
        case_number=(doc.instrument_no or "").strip() or None,
        legal_description=(doc.notes or "").strip() or None,
        description=desc,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


class SCRodAcclaim(BaseScraper):
    slug = "counties_sc.sc_rod_acclaim"
    name = "SC Register of Deeds (Harris Acclaim — probate + liens)"
    category = "register_of_deeds"
    expected_min_count = 0   # weekly window varies; counties small
    requires_render = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for (state, county), base in acclaim.ACCLAIM_COUNTIES.items():
            src_url = f"{base}/search/SearchTypeDocType"
            docs = await acclaim.discover_recent_nods(state, county, days_back=_LOOKBACK_DAYS)
            for d in docs:
                li = _to_listing(d, self.slug, src_url)
                if li:
                    out.append(li)
        return out
