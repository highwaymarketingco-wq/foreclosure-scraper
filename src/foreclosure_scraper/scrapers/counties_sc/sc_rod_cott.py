"""SC Register-of-Deeds distress recordings via the Cott RecordRoom adapter.

Closes the SC ROD gap for Cott RecordRoom counties (Union; reusable for others).
SC foreclosure is judicial (lis pendens lives in the courts — sc_public_index_*),
so the ROD distress signal here is PROBATE (deed of distribution / death /
distribution statement = inherited-property leads, names included) + LIENS.
Free, browserless (rod/cott_recordroom.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...rod import cott_recordroom as cott


def _classify(doc_type: str) -> tuple[ListingType, str] | None:
    s = (doc_type or "").upper()
    if any(k in s for k in ("SAT", "REL", "TERM", "CANCEL")):
        return None
    if any(k in s for k in ("DOD", "DIST", "DIS STMT", "DEATH", "DECEAS", "ESTATE")):
        return ListingType.PROBATE_NOTICE, "probate"
    if any(k in s for k in ("LIEN", "MECH", "JUDG", "EXECUTION")):
        return ListingType.TAX_LIEN, "lien"
    return None


def _to_listing(doc, slug: str, source_url: str) -> Listing | None:
    cls = _classify(doc.doc_type)
    if cls is None:
        return None
    lt, kind = cls
    rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
    raw: dict = {"rod": {"doc_type": doc.doc_type, "grantor": doc.grantor,
                         "grantee": doc.grantee, "book": doc.book, "page": doc.page,
                         "instrument": doc.instrument_no, "recorded": rec},
                 "cott_rod": True}
    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": doc.doc_type,
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    return Listing(
        source=slug, source_url=source_url,
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state=doc.state, county=doc.county,
        defendant=(doc.grantor or "").strip() or None,
        case_number=(doc.instrument_no or "").strip() or None,
        legal_description=(doc.notes or "").strip() or None,
        description=f"{doc.doc_type} recorded {rec}: {(doc.grantor or '?').strip()}",
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


class SCRodCott(BaseScraper):
    slug = "counties_sc.sc_rod_cott"
    name = "SC Register of Deeds (Cott RecordRoom — probate/lien)"
    category = "register_of_deeds"
    expected_min_count = 0
    requires_render = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for (state, county), slug in cott.COTT_RR_COUNTIES.items():
            src = f"{cott.COTT_RR_HOST}/{slug}/guest/Search/records"
            for d in await cott.discover_recent_nods(state, county, days_back=60):
                li = _to_listing(d, self.slug, src)
                if li:
                    out.append(li)
        return out
