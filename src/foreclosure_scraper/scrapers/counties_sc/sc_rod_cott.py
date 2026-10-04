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
    # "DIS STMT" removed 2026-10-04 (extraction-completeness audit, batch 13) --
    # see the matching, more detailed comment in rod/cott_recordroom.py._DISTRESS.
    # Live-verified: every "DIS STMT" row Union actually records is a
    # "HOMEOWNERS DISCLOSURE STATEMENT" (a building-safety filing), never an
    # estate distribution statement; this token was a 100% false-positive match.
    if any(k in s for k in ("DOD", "DIST", "DEATH", "DECEAS", "ESTATE")):
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
    rod_block: dict = {"doc_type": doc.doc_type, "grantor": doc.grantor,
                       "grantee": doc.grantee, "book": doc.book, "page": doc.page,
                       "instrument": doc.instrument_no, "recorded": rec}
    # 2026-10-04 (batch 13): doc.raw['cott_recordroom'] now carries the grantee's
    # own mailing address + a $ consideration when the vendor's Property/PartyTwo
    # cells parsed one (rod/cott_recordroom.py) -- surfaced into raw['rod'] for
    # provenance. See that module's own comment for why grantee_address is not
    # bridged into raw['owner_mailing'] here.
    extra = doc.raw.get("cott_recordroom") if isinstance(doc.raw, dict) else None
    if isinstance(extra, dict):
        if extra.get("grantee_address"):
            rod_block["grantee_address"] = extra["grantee_address"]
        if extra.get("consideration_amount") is not None:
            rod_block["consideration_amount"] = extra["consideration_amount"]
    raw: dict = {"rod": rod_block, "cott_rod": True}
    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": doc.doc_type,
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    return Listing(
        source=slug, source_url=source_url,
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state=doc.state, county=doc.county,
        # 2026-10-04 (batch 13): parcel_id + street_address recovered from the
        # Cott RecordRoom "Property" cell's own structured Parcel #/Address --
        # previously thrown away into one flattened notes soup (see
        # rod/cott_recordroom.py). Matches the sibling sc_rod_acclaim.py, which
        # already wires parcel_id the same way.
        parcel_id=(doc.parcel_id or "").strip() or None,
        street_address=(getattr(doc, "property_address", None) or "").strip() or None,
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
