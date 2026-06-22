"""NC Register-of-Deeds distress recordings via the Logan "The Lookup" adapter.

Closes the NC ROD gap for the Logan counties whose pick-list loads
(Transylvania, McDowell, Mitchell). Sweeps recent recordings browserless/free
(rod/logan.py) and emits TYPED leads:
  * FCL / LIS/P / S/TR / N/SUB / R/TR  -> LIS_PENDENS      (pre-foreclosure)
  * TR/D / TD / C/TR/D / SHF/D         -> FORECLOSURE_SALE (post-sale deed)
  * D/DIST / ADM/DT / EXEC/DT          -> PROBATE_NOTICE   (+ relationship_signal)
  * LIEN / JUDGMENT                    -> TAX_LIEN         (financial)

Each lead carries grantor (defendant), instrument#, and the legal description;
the address waterfall + parcel inventory resolve a situs from the owner name.
(Spartanburg uses different codes + a broken loader -> not wired here yet.)
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...rod import logan

_LOOKBACK_DAYS = 60

_PRE = {"FCL", "LIS/P", "S/TR", "N/SUB", "R/TR"}
_SALE = {"TR/D", "TD", "C/TR/D", "SHF/D"}
_PROBATE = {"D/DIST", "DEED/DIST", "ADM/DT", "EXEC/DT"}
_LIEN = {"LIEN", "LN", "LIEN000", "JUDGMENT", "JGMT", "JUDG", "JUDGM"}


def _classify(doc_type: str) -> tuple[ListingType, str] | None:
    s = (doc_type or "").strip().upper()
    if s in _PRE:
        return ListingType.LIS_PENDENS, "pre_foreclosure"
    if s in _SALE:
        return ListingType.FORECLOSURE_SALE, "foreclosure_deed"
    if s in _PROBATE:
        return ListingType.PROBATE_NOTICE, "probate"
    if s in _LIEN:
        return ListingType.TAX_LIEN, "lien"
    return None


def _to_listing(doc, slug: str, source_url: str) -> Listing | None:
    cls = _classify(doc.doc_type)
    if cls is None:
        return None
    lt, kind = cls
    rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
    desc = f"{doc.doc_type} recorded {rec}: {(doc.grantor or '?').strip()}"
    raw: dict = {"rod": {"doc_type": doc.doc_type, "grantor": doc.grantor,
                         "grantee": doc.grantee, "book": doc.book, "page": doc.page,
                         "instrument": doc.instrument_no, "recorded": rec},
                 "logan_rod": True}
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
        description=desc,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


class NCRodLogan(BaseScraper):
    slug = "counties_nc.nc_rod_logan"
    name = "NC Register of Deeds (Logan 'The Lookup' — foreclosure/lien/probate)"
    category = "register_of_deeds"
    expected_min_count = 0   # small counties; weekly distress volume varies
    requires_render = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for (state, county), host in logan.LOGAN_COUNTIES.items():
            src = f"{host}/index.php"
            for d in await logan.discover_recent_nods(state, county, days_back=_LOOKBACK_DAYS):
                li = _to_listing(d, self.slug, src)
                if li:
                    out.append(li)
        return out
