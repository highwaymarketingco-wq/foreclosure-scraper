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
    before it is added, because the headline row count has been misleading far
    more often than not. REJECTED so far, all of which the enumeration counted
    as finds — do not re-chase these:

      Buncombe "Unpaid Bills 2026"  103,191 real-property rows, but that is the
                                    whole current-year unpaid levy: everyone who
                                    has not paid yet, not delinquency.
      Buncombe "Unpaid Bills 2025"  7,900 rows, 6,873 of them PERSONAL property
                                    (vehicle tax). Admitted at real_value>0 only.
      Burke "Tax_Sales_FS"          sounds like tax foreclosure; the schema has
                                    GRANTOR/GRANTEE/Qualified/Appraiser/Week. It
                                    is the assessor's qualified-sales review
                                    roll — comps data, not distress.
      Anderson city code violations live, 9 open, and every address, owner and
                                    TMS is null with CaseNumber '123'. A stub.
      Anderson "Property Type"      13,374 rows, a parcel/zoning join.
      Pickens Citizen_Problems      complainant phone/email, no property locator.
      Buncombe towed property       "titled property" here means vehicles.
      Gaston Blight Problems        live, 0 rows.
      Pickens dqnt_*, Oconee DT2025 already covered by pickens_delinquent_parcels
                                    and multi_year_delinquent_tax.

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
    #: Some layers split the situs across columns (house number / street /
    #: type). Joined in order, blanks dropped.
    situs_parts: tuple[str, ...] = ()
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
    # The city's tax-sale parcel set, joined to CAMA. The join renamed every
    # CAMA column to a positional alias (L20CAMA_11 = owner, L20CAMA_13..16 =
    # mailing, L20CAMA_64 = condition), which is why only the self-describing
    # Tax_Sale_* columns drive the mapping and the CAMA block is kept in raw
    # rather than asserted — a positional alias silently shifts if the county
    # rebuilds the join, and a wrong value is worse than no value.
    Layer(
        slug="spartanburg_city_tax_sale",
        state="SC", county="Spartanburg",
        url=("https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/"
             "Tax_Sale_Parcels/FeatureServer/0"),
        listing_type=ListingType.TAX_SALE,
        fields=("Tax_Sale_1", "Tax_Sale_2", "Tax_Sale_4", "Tax_Sale_5",
                "L20CAMA_Pa", "L20CAMA_13", "L20CAMA_14", "L20CAMA_15",
                "L20CAMA_16", "L20CAMA_18", "L20CAMA_21", "L20CAMA_35",
                "L20CAMA_64"),
        parcel="Tax_Sale_1", owner_last="Tax_Sale_2", situs="Tax_Sale_4",
        detail="L20CAMA_18", process="tax",
        source_page="https://www.spartanburgcounty.org/158/Delinquent-Tax",
    ),
    # Buncombe's 2024 bills that are STILL unpaid — two levies behind, so a
    # harder signal than the 2025 file. 6,252 rows, 372 of them real property.
    #
    # The 2026 file on the same org was REJECTED: 103,191 real-property rows is
    # the entire current-year unpaid levy, i.e. everyone who has not paid yet,
    # not delinquency. Do not add it.
    Layer(
        slug="buncombe_unpaid_bills_2024",
        state="NC", county="Buncombe",
        url=("https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
             "Buncombe_County_All_Property_Bills_Unpaid_from_2024/FeatureServer/0"),
        listing_type=ListingType.TAX_LIEN,
        where="real_value>0",
        fields=("bill", "pin", "owner1_last_name", "owner1_first_name",
                "address_line1", "city", "postal_code", "real_value",
                "total_value", "levy_year"),
        parcel="pin", owner_last="owner1_last_name", owner_first="owner1_first_name",
        situs="address_line1", city="city", zip_="postal_code",
        value="total_value", detail="bill", process="tax",
        source_page="https://www.buncombecounty.org/governing/depts/tax/",
    ),
    # Field-assessed FLOOD damage joined to CAMA, so the owner name is the
    # record owner rather than a self-submitted form. Carries per-element
    # condition (foundation, roof, HVAC) and a depreciation figure.
    Layer(
        slug="pickens_flood_damage",
        state="SC", county="Pickens",
        url=("https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/"
             "FloodStructureFieldAssessmentCAMA/FeatureServer/0"),
        listing_type=ListingType.DISTRESSED,
        fields=("PIN", "NAME1", "WHOLE_ADDR", "ZIP", "Foundation", "RoofCover",
                "Superstruc", "HVAC", "Depreciati", "ResidenceT", "Stories"),
        parcel="PIN", owner_last="NAME1", situs="WHOLE_ADDR", zip_="ZIP",
        detail="Depreciati", process="flood_damage",
        source_page="https://www.co.pickens.sc.us/",
    ),
    # Structures inside the floodway / Zone AE — the pool NCDPS draws buyout
    # candidates from. Owner names here come from the tax roll.
    Layer(
        slug="hendersonville_flood_zone_structures",
        state="NC", county="Henderson",
        url=("https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/"
             "Structures_ZONE_AE/FeatureServer/0"),
        listing_type=ListingType.DISTRESSED,
        fields=("PIN_1", "OWNER_LAST_NAME", "OWNER_FIRST_NAME", "STRUCTURE_TYPE",
                "YR_BUILT", "TOTSQFT", "TAXVAL_BUILDING", "TAXVAL_LAND",
                "FLOOD_ZONE", "OWNER_RENTER_OCCUPIED"),
        parcel="PIN_1", owner_last="OWNER_LAST_NAME", owner_first="OWNER_FIRST_NAME",
        value="TAXVAL_BUILDING", detail="FLOOD_ZONE", process="flood_zone",
        source_page="https://www.hendersonvillenc.gov/",
    ),
    # Structures with recorded landslide damage. Physical distress with an
    # address, and the county publishes it because the damage is material.
    Layer(
        slug="buncombe_landslide_damage",
        state="NC", county="Buncombe",
        url=("https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
             "Landslides_With_Damage/FeatureServer/0"),
        listing_type=ListingType.DISTRESSED,
        fields=("location_id", "full_civic_address", "postal_code",
                "DamageType", "ClosestAddress"),
        situs="full_civic_address", zip_="postal_code",
        detail="DamageType", process="storm_damage",
        source_page="https://www.buncombecounty.org/",
    ),
    # Transylvania and Burke both read ZERO on the storm-damage signal today,
    # not because they were undamaged but because only Buncombe's roll was
    # wired. These are the county assessments.
    Layer(
        slug="transylvania_damage_assessment",
        state="NC", county="Transylvania",
        url=("https://services1.arcgis.com/ProOLvsmwpY1RmFG/arcgis/rest/services/"
             "Damage_Assessment_Viewer/FeatureServer/0"),
        listing_type=ListingType.DISTRESSED,
        fields=("reportdate", "structure_type", "severity_level", "needs",
                "house_number", "road_name", "pin", "cost"),
        parcel="pin", situs_parts=("house_number", "road_name"),
        detail="severity_level", process="storm_damage",
        source_page="https://www.transylvaniacounty.org/",
    ),
    Layer(
        slug="burke_storm_damage",
        state="NC", county="Burke",
        url=("https://services3.arcgis.com/axQ4OCSpcxALIQsV/arcgis/rest/services/"
             "NCEM_Damage_Assessment_BC/FeatureServer/119"),
        listing_type=ListingType.DISTRESSED,
        fields=("REID", "dmg_loc", "damage_cat_cal", "program_type", "county"),
        parcel="REID", situs="dmg_loc",
        detail="damage_cat_cal", process="storm_damage",
        source_page="https://www.burkenc.org/",
    ),
    Layer(
        # New Hanover (Wilmington) DEMOLITION permits — teardown / condemned-structure
        # signal for the coastal county. `WORK_CLASS LIKE '%Demolition%'` isolates the
        # ~1,708 demolition rows out of the 100k+ permit file (routine permits are noise
        # and deliberately NOT harvested). No owner field on the permit layer — PID
        # resolves the owner downstream. Contractor/contact columns are NOT requested.
        slug="new_hanover_demolition_permits",
        state="NC", county="New Hanover",
        url=("https://gis.nhcgov.com/server/rest/services/Thematic/"
             "BuildingPermits/FeatureServer/0"),
        listing_type=ListingType.DISTRESSED,
        fields=("PERMIT_NUMBER", "WORK_CLASS", "PERMIT_STATUS", "APPLICATION_DATE",
                "NUMBER", "DIR", "STREET", "TYPE", "CITY", "ZIPCODE", "PID"),
        where="WORK_CLASS LIKE '%Demolition%'",
        parcel="PID",
        situs_parts=("NUMBER", "DIR", "STREET", "TYPE"),
        city="CITY", zip_="ZIPCODE",
        detail="PERMIT_STATUS", process="demolition_permit",
        source_page="https://gis.nhcgov.com/",
    ),
    # A curated redevelopment-eligibility list carrying a "Problem" column —
    # the city has already judged these parcels problematic.
    Layer(
        slug="spartanburg_infill_eligible",
        state="SC", county="Spartanburg",
        url=("https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/"
             "Infill_Eligible_Properties/FeatureServer/0"),
        listing_type=ListingType.DISTRESSED,
        fields=("TAXPIN", "SHORTPIN", "PARCELNUMB", "LOTNUMBER", "Problem",
                "DEEDACREAG"),
        parcel="TAXPIN", detail="Problem", process="redevelopment",
        source_page="https://www.cityofspartanburg.org/",
    ),
    # HMGP buyout applicants: a homeowner who has APPLIED to have the
    # government buy their damaged property has already decided to sell. The
    # layer also carries a Phone column, which is deliberately not requested.
    Layer(
        slug="buncombe_hmgp_buyout",
        state="NC", county="Buncombe",
        url=("https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
             "HMGP_Update_06122026/FeatureServer/0"),
        listing_type=ListingType.DISTRESSED,
        fields=("Match_addr", "Place_addr", "Status", "Type", "PlaceName"),
        situs="Match_addr", detail="Status", process="buyout_applicant",
        source_page="https://www.buncombecounty.org/",
    ),
    # Private-property storm cleanup sites. Spartanburg read ZERO on the
    # storm-damage signal while Buncombe, Transylvania, Burke and Pickens all
    # had a leg, so this is the county's first. 2,359 rows, verified live
    # 2026-08-06.
    #
    # ADDRESS ONLY, and that is the whole record. USER_Name, USER_Issue and
    # USER_Status are empty on 1,997 of the 2,000 rows sampled, so there is no
    # owner name to be had here; the parcel resolver supplies it from the situs.
    # The layer also carries USER_Phone and USER_Secondary_Phone, which are NOT
    # requested, on the same reasoning as buncombe_hmgp_buyout above: these are
    # residents who called in for help, not a contact list. The one populated
    # USER_Issue in the sample is a free-text narrative describing an elderly
    # resident living in a damaged house without power. That is exactly the
    # content this engine reports and does not harvest.
    Layer(
        slug="spartanburg_property_cleanup",
        state="SC", county="Spartanburg",
        url=("https://services6.arcgis.com/YJV3IFNXuNHJDIvn/arcgis/rest/services/"
             "Private_Property_Cleanup_Locations/FeatureServer/13"),
        listing_type=ListingType.DISTRESSED,
        fields=("Match_addr", "IN_City", "IN_Postal"),
        situs="Match_addr", city="IN_City", zip_="IN_Postal",
        process="storm_damage",
        source_page="https://www.spartanburgcounty.org/",
    ),
) + tuple(
    # ---------------------------------------------------------------------
    # COUNTY-OWNED / SURPLUS inventory.
    #
    # These are NOT distressed owners — the owner is literally the county
    # ("BURKE COUNTY", "COUNTY OF BUNCOMBE"). They are properties the county
    # is disposing of, much of it acquired through tax foreclosure, so they
    # are acquirable inventory rather than an outreach target.
    #
    # Tagged process="county_surplus" specifically so they can never be
    # filtered into a mail or call list by accident. Buying at a surplus sale
    # and cold-calling an owner in default are different workflows and the
    # board has to keep them apart.
    # ---------------------------------------------------------------------
    Layer(
        slug=f"{co.lower()}_county_owned",
        state=st, county=co, url=url,
        listing_type=ListingType.DISTRESSED,
        fields=flds, parcel=pf, owner_last=of, situs=af,
        situs_parts=(("HouseNumber", "streetname", "StreetType")
                     if af is None else ()),
        process="county_surplus", source_page=page,
    )
    for co, st, url, flds, pf, of, af, page in (
        ("Lincoln", "NC",
         "https://services8.arcgis.com/TaX0xkzgvxdv4n56/arcgis/rest/services/"
         "County_Owned_Property/FeatureServer/1",
         ("PID", "PHYSICALADDR", "NAME1_1", "Class", "USE_", "ZONING_1"),
         "PID", "NAME1_1", "PHYSICALADDR",
         "https://www.lincolncountync.gov/"),
        ("Buncombe", "NC",
         "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
         "County_Owned_Over_Half_Acre/FeatureServer/0",
         ("pin", "owner", "HouseNumber", "streetname", "StreetType",
          "TaxYear", "DeedBook", "DeedPage"),
         "pin", "owner", None,
         "https://www.buncombecounty.org/governing/depts/tax/"),
        ("Burke", "NC",
         "https://services3.arcgis.com/axQ4OCSpcxALIQsV/arcgis/rest/services/"
         "Disposable_BC_Owned_Parcels_FS/FeatureServer/194",
         ("PIN", "LOCATION_ADDR", "PROPERTY_OWNER", "Acq_Type", "Acq_Year",
          "Acq_Cost", "TOTAL_PROP_VALUE", "ACREAGE", "PROPERTY_DESCR"),
         "PIN", "PROPERTY_OWNER", "LOCATION_ADDR",
         "https://www.burkenc.org/"),
        ("Pickens", "SC",
         "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/"
         "vacant_co_prop/FeatureServer/0",
         ("PIN", "NAME1", "LOCADD", "LOCCITY", "LOCZIP", "ACRES"),
         "PIN", "NAME1", "LOCADD",
         "https://www.co.pickens.sc.us/"),
        # City of Clinton, which sits in Laurens County — the only municipal
        # layer in the whole 63-endpoint city sweep that turned out to be
        # both distress-shaped and free of complainant PII.
        ("Laurens", "SC",
         "https://gis.cityofclintonsc.com/arcgis/rest/services/"
         "EconomicDevelopment/CityOwnedParcels/MapServer/0",
         ("TMS", "Owner", "Descriptio", "ZoningCode"),
         "TMS", "Owner", None,
         "https://www.cityofclintonsc.com/"),
    )
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
    if not situs and lay.situs_parts:
        bits = [_clean(a.get(p)) for p in lay.situs_parts]
        situs = " ".join(b for b in bits if b) or None
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
        # Small municipal layers ride on single-city servers that flake. On the
        # 2026-08-06 run Clinton (69 rows) returned a 500 then timed out, and the
        # guard did what it is built to do: hard-failed the source and discarded
        # 4,780 GOOD rows from 15 healthy county layers rather than ship a quiet
        # shortfall. Correct instinct, wrong trade at this ratio.
        #
        # These three are tolerated: each is under 100 rows, each sits on a
        # single-city host, and losing one is not worth losing the other fifteen.
        # LayerHarvest still logs tolerated=True, so the loss stays VISIBLE — it
        # is an accepted loss, not a silent one. Every county-scale layer stays
        # hard-fail.
        guard = LayerHarvest(
            self.slug, [lay.slug for lay in LAYERS],
            tolerate=("laurens_county_owned", "pickens_county_owned",
                      "burke_county_owned"),
            attempts=3)
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
