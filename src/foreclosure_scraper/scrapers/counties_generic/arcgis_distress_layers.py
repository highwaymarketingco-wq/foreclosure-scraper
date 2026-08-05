"""Config-driven reader for county ArcGIS layers that ARE a distress signal.

WHY THIS EXISTS
    The 18 per-county enumeration docs list ~525 verified free endpoints, and a
    measured 263 of them are still unbuilt. Most of the unbuilt tail is one
    shape: a county publishes a single FeatureServer/MapServer layer that IS the
    signal (a delinquent roll, an open code-violation list, a condemned-structure
    inventory), and wiring it needs nothing but a field mapping.

    Writing a bespoke module per layer is what has kept that tail unbuilt. This
    is the table: one `Layer` entry per endpoint, and adding the next verified
    one is a few lines rather than a new file.

WHAT BELONGS HERE (and what does not)
    ONLY layers whose rows are themselves distressed properties. Parcel masters,
    sales history and building footprints are ENRICHMENT, not leads — they have
    six-figure row counts and would swamp the board with non-distressed
    property. Those belong in the enrichment modules that already read them.

    Every candidate is checked for NET-NEW value against the published board
    before it is added. Two layers with large headline counts were rejected on
    exactly that basis:
      * Buncombe "Unpaid Property Bills" is 7,900 rows, but 6,873 are PERSONAL
        property (vehicle tax). Only the real-property subset is admitted.
      * Pickens dqnt_* and Oconee DT2025 were already covered by
        `pickens_delinquent_parcels` / `multi_year_delinquent_tax`. Not added.

PRIVACY
    Several of these layers carry the CONTACT DETAILS OF THE PERSON WHO FILED
    THE COMPLAINT (Lincoln NAME/PHONE/EMAIL, Pickens poc*). A complainant is not
    a distressed owner, and their phone number is not ours to collect. Field
    lists below are explicit and exclude them; `outFields` is never a wildcard.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable, NamedTuple, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_PAGE = 1000


class Layer(NamedTuple):
    """One county layer and the attribute names it uses for each role."""
    slug: str
    state: str
    county: str
    url: str                      # .../FeatureServer/0 or .../MapServer/15
    listing_type: ListingType
    #: Fields requested verbatim. NEVER a wildcard — see the privacy note.
    fields: tuple[str, ...]
    #: Server-side filter that isolates the DISTRESSED rows.
    where: str = "1=1"
    parcel: Optional[str] = None
    owner_last: Optional[str] = None
    owner_first: Optional[str] = None
    situs: Optional[str] = None
    city: Optional[str] = None
    zip_: Optional[str] = None
    value: Optional[str] = None
    detail: Optional[str] = None       # violation description / bill id
    process: Optional[str] = None
    source_page: Optional[str] = None  # human-facing page for source_url


LAYERS: tuple[Layer, ...] = (
    # Buncombe's delinquent roll on the board today comes from the county's
    # ADVERTISEMENT PDF. This layer is the live unpaid-bill file behind it and
    # carries 675 parcels the PDF does not, plus assessed value and deed refs.
    # real_value>0 is what separates real property from the 6,873 vehicle rows.
    Layer(
        slug="buncombe_unpaid_bills",
        state="NC", county="Buncombe",
        url=("https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
             "Unpaid%20Property%20Bills%20from%202025/FeatureServer/0"),
        listing_type=ListingType.TAX_LIEN,
        where="real_value>0",
        fields=("bill", "pin", "owner1_last_name", "owner1_first_name",
                "address_line1", "city", "state", "postal_code",
                "real_value", "total_value", "levy_year", "acres",
                "deed_book", "deed_page", "total_due", "tax_due"),
        parcel="pin", owner_last="owner1_last_name", owner_first="owner1_first_name",
        situs="address_line1", city="city", zip_="postal_code",
        value="total_value", detail="bill", process="tax",
        source_page="https://www.buncombecounty.org/governing/depts/tax/",
    ),
    # Lincoln publishes 3,465 violations back to 1999; only 66 are OPEN, and a
    # closed violation is not a distress signal. NAME / PHONE / EMAIL on this
    # layer are the COMPLAINANT's and are deliberately not requested.
    Layer(
        slug="lincoln_code_violations",
        state="NC", county="Lincoln",
        url=("https://arcgisserver.lincolncountync.gov/arcgis/rest/services/"
             "ComDev/MapServer/15"),
        listing_type=ListingType.DISTRESSED,
        where="STATUS='Open'",
        fields=("VIOLATIONID", "FULLADDR", "LOCDESC", "VIOLATETYPE",
                "VIOLATEDESC", "CODE", "STATUS", "SUBMITDT"),
        situs="FULLADDR", detail="VIOLATEDESC", process="code_enforcement",
        source_page="https://www.lincolncountync.gov/246/Code-Enforcement",
    ),
)


def _clean(v) -> Optional[str]:
    s = str(v).strip() if v is not None else ""
    return s or None


def _num(v) -> Optional[float]:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _owner(a: dict, lay: Layer) -> Optional[str]:
    last = _clean(a.get(lay.owner_last)) if lay.owner_last else None
    first = _clean(a.get(lay.owner_first)) if lay.owner_first else None
    if last and first:
        return f"{last}, {first}"
    return last or first


def _to_listing(a: dict, lay: Layer) -> Optional[Listing]:
    situs = _clean(a.get(lay.situs)) if lay.situs else None
    parcel = _clean(a.get(lay.parcel)) if lay.parcel else None
    if not (situs or parcel):
        return None                     # nothing to locate the property by
    owner = _owner(a, lay)
    detail = _clean(a.get(lay.detail)) if lay.detail else None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    bits = [b for b in (owner, situs, detail) if b]
    return Listing(
        source=f"counties_generic.arcgis_distress.{lay.slug}",
        source_url=lay.source_page or lay.url,
        listing_type=lay.listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state=lay.state, county=lay.county,
        street_address=situs,
        city=_clean(a.get(lay.city)) if lay.city else None,
        zip_code=_clean(a.get(lay.zip_)) if lay.zip_ else None,
        parcel_id=parcel,
        owner_name=owner, defendant=owner,
        tax_value=_num(a.get(lay.value)) if lay.value else None,
        foreclosure_process=lay.process,
        description=f"{lay.county} {lay.state} — {' | '.join(bits)}"[:300],
        first_seen=now, last_seen=now,
        raw={"arcgis_distress": {"layer": lay.slug, **{k: v for k, v in a.items()
                                                       if v not in (None, "")}}},
    )


async def _fetch_layer(c, lay: Layer) -> list[Listing]:
    out: list[Listing] = []
    offset = 0
    while True:
        r = await c.get(lay.url + "/query", params={
            "where": lay.where,
            "outFields": ",".join(lay.fields),     # explicit, never "*"
            "returnGeometry": "false",
            "resultOffset": offset,
            "resultRecordCount": _PAGE,
            "f": "json",
        }, timeout=45.0)
        if r.status_code != 200:
            raise RuntimeError(f"{lay.slug}: HTTP {r.status_code}")
        d = r.json()
        # ArcGIS answers 200 with an error BODY; treat that as the failure it is.
        if "error" in d:
            raise RuntimeError(f"{lay.slug}: {str(d['error'])[:120]}")
        feats = d.get("features") or []
        for f in feats:
            li = _to_listing(f.get("attributes") or {}, lay)
            if li:
                out.append(li)
        if len(feats) < _PAGE or not d.get("exceededTransferLimit"):
            break
        offset += _PAGE
    log.info("arcgis_distress.layer_done", layer=lay.slug,
             county=lay.county, leads=len(out))
    return out


class ArcgisDistressLayers(BaseScraper):
    slug = "counties_generic.arcgis_distress_layers"
    name = "County ArcGIS distress layers (delinquent rolls, open code violations)"
    category = "county_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_ARCGIS_DISTRESS") == "0":
            return []
        out: list[Listing] = []
        guard = LayerHarvest(self.slug, [lay.slug for lay in LAYERS])
        async with client(timeout=45.0) as c:
            with guard:
                for lay in LAYERS:
                    out.extend(await guard.harvest(
                        lay.slug, self._one(c, lay)))
        return out

    @staticmethod
    def _one(c, lay: Layer):
        async def _run() -> list[Listing]:
            return await _fetch_layer(c, lay)
        return _run
