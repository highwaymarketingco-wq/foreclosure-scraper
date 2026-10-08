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
import re
from datetime import datetime, timezone
from typing import Iterable, NamedTuple, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind
from ...sensitive_fields import drop_sensitive

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
    #: Some layers (Buncombe's bill tables) carry the TAXPAYER'S MAILING address
    #: on columns separate from situs (address_line1/city/state/postal_code here,
    #: NOT the property's own city/state/zip). Joined in order, blanks dropped,
    #: and written to raw["owner_mailing"] rather than to street_address/city/zip_
    #: -- see multi_year_delinquent_tax.py, which reads this exact Buncombe schema
    #: the same way. Absentee-owner signal, never the property's own address.
    mailing_parts: tuple[str, ...] = ()
    #: The layer's OWN coordinate columns (WGS84 degrees), when it publishes them as
    #: attributes. Used directly as Listing.latitude/longitude instead of leaving the row
    #: to the address geocoder (2026-10-07 extraction audit: New Hanover's permits layer
    #: carries Lat/Lon on 92% of rows and they were never requested).
    lat_field: Optional[str] = None
    lon_field: Optional[str] = None
    #: Field holding the mailing address's state abbreviation, for absentee /
    #: out-of-state detection (mail_state != the layer's own `state`).
    mail_state: Optional[str] = None
    #: raw["owner_mailing"]["source"] tag. Defaults to the layer slug, but a value
    #: from scripts/repair_parcel_from_address.py's PARCEL_MAILING_SOURCES (e.g.
    #: "county_tax_roll", what multi_year_delinquent_tax.py tags this exact Buncombe
    #: table with) lets that repair path recognize the block as parcel-layer-sourced.
    mailing_source: Optional[str] = None
    #: Field holding the AMOUNT OWED (a tax bill, a lien). Stored as
    #: raw["arcgis_distress"]["amount_owed"], the key enrichment_tax_owed's generic scan
    #: already reads, so the balance reaches raw["tax_owed"] and the debt-aware ranking.
    #: Without it a delinquent-roll layer carries its bill only under a source-specific
    #: column name (Greenville's is TOTTAX) that nothing downstream knows.
    amount: Optional[str] = None
    #: process="code_enforcement" ONLY (2026-10-02 breadth fix). Until this date
    #: _to_listing() wrote raw["arcgis_distress"] + foreclosure_process="code_enforcement"
    #: but NEVER raw["code_enforcement"] -- the key distress_score.py's PROPERTY
    #: signal and the county-signal coverage tracker actually read -- so 5 already-
    #: live, already-wired layers (columbia_code_vacant_boarded, greensboro_code_housing,
    #: durham_open_code_violations, rockhill_code_housing, rockhill_code_exterior_major;
    #: live-verified 2026-10-02 counts 1,020/665/1,110/17/15) contributed NOTHING to
    #: either, despite being real and current. Fixed generically for every
    #: process="code_enforcement" layer: when None (the default), the layer's own
    #: `where`/sub-layer-choice already restricts to a structurally-severe category
    #: (true for all 4 of those above except Durham), so severe=True unconditionally.
    #: When set, `detail`'s value is tested against this pattern instead -- Durham's
    #: "Open Landuse Code Violation Cases" layer admits ALL Topics unfiltered, mixing
    #: real structural ones (Repair Only/Repair or Demolish/Unsafe Building/B-C
    #: Abatement) with yard-nuisance ones (Weedy/Junked Lot, Vehicle, Weedy Chronic
    #: Violator) this module's OWN comments elsewhere already reject as "weaker"/
    #: "yard-nuisance" for Greensboro and Rock Hill -- same conservative severe/
    #: not-severe split henderson_code_violations.py draws for its own county,
    #: applied here rather than claiming every open Durham case is vacancy-adjacent.
    ce_severe_re: Optional[re.Pattern] = None
    #: Stamps raw["condemned"]=True (a bare boolean, Spartanburg's own shape --
    #: see spartanburg_condemned.py) instead of a fabricated raw["code_enforcement"]
    #: case record. For a layer whose rows are an APPRAISER CONDITION rating or a
    #: CITY-ORDERED demolition case, not an actual code-enforcement complaint with a
    #: case number/status history, inventing a `violations` list with a fake
    #: case_id/status would misrepresent the evidence; distress_score.py's
    #: `elif r.get("condemned")` branch already grants the identical PROPERTY
    #: code_enforcement credit (w=14) off the bare flag, so nothing is lost.
    #: 2026-10-02 introduced this as a hardcoded `lay.slug ==
    #: "rockhill_code_demolition"` check (Rock Hill's demolition sub-layer, the
    #: only layer that needed it that day); generalized to this explicit per-layer
    #: field 2026-10-03 when greenwood_cama_condemned became the second real case
    #: needing it -- same reasoning commit 6e00d55b used to turn Durham's one-off
    #: severity special-case into the generic `ce_severe_re` field above. Explicit
    #: opt-in (default False) rather than keying off `process` value, so a
    #: differently-sourced layer that happens to share a process string (e.g. New
    #: Hanover's demolition_permits -- a homeowner's own voluntary teardown
    #: application, not a condemnation) is never swept in by accident.
    condemned: bool = False


LAYERS: tuple[Layer, ...] = (
    # Buncombe's delinquent roll on the board today comes from the county's
    # ADVERTISEMENT PDF. This layer is the live unpaid-bill file behind it and
    # carries 675 parcels the PDF does not, plus assessed value and deed refs.
    # real_value>0 is what separates real property from the 6,873 vehicle rows.
    #
    # SITUS FIX (2026-09-29, project_buncombe_unpaid_bills_situs_fix): address_line1/
    # city/state/postal_code is the TAXPAYER'S MAILING address, not the property's --
    # verified live: e.g. owner RADIFY ASHEVILLE LLC carries address_line1="249 Main
    # Ave S Ste 107 Pmb 362", city/state "North Bend WA" while the actual parcel sits
    # at 155 Tunnel Rd, Asheville NC (house_num/street_name/street_type). This is the
    # exact schema counties.multi_year_delinquent_tax already reads correctly for
    # this same Buncombe table (see its _buncombe_situs) -- situs comes from
    # house_num/street_direction/street_name/street_type, and the mailing block is
    # kept separate (mailing_parts/mail_state below) so absentee/out-of-state signal
    # isn't lost, just no longer asserted as the property's own address. Previously
    # this layer wrote the mailing address into street_address/city/zip_, which is
    # why its rows failed to merge against the same parcel's multi_year_delinquent_tax
    # row -- dedupe's house-number guard correctly refused to fuse two different
    # streets. See scripts/resolve_parcel_from_address.py's DENY_SOURCES comment for
    # the historical characterization of this bug; that entry stays in place because
    # rows already published under the old (mailing-as-situs) behavior are still on
    # the board and have not been backfilled.
    Layer(
        slug="buncombe_unpaid_bills",
        state="NC", county="Buncombe",
        url=("https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
             "Unpaid%20Property%20Bills%20from%202025/FeatureServer/0"),
        listing_type=ListingType.TAX_LIEN,
        where="real_value>0",
        fields=("bill", "pin", "owner1_last_name", "owner1_first_name",
                "house_num", "street_direction", "street_name", "street_type",
                "address_line1", "address_line2", "city", "state", "postal_code",
                "real_value", "total_value", "levy_year", "acres",
                "deed_book", "deed_page", "total_due", "tax_due"),
        parcel="pin", owner_last="owner1_last_name", owner_first="owner1_first_name",
        situs_parts=("house_num", "street_direction", "street_name", "street_type"),
        mailing_parts=("address_line1", "address_line2", "city", "state", "postal_code"),
        mail_state="state", mailing_source="county_tax_roll",
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
    # Same table shape and same mailing-vs-situs bug as buncombe_unpaid_bills above
    # (verified live 2026-09-29 against this specific 2024 service too, e.g. owner
    # SKIDMORE DAVID's mailing is "4418 Eastern St, New Orleans LA" while the parcel
    # sits at "359 Lower Grassy Branch Rd" in Buncombe) -- same fix, same reasoning.
    Layer(
        slug="buncombe_unpaid_bills_2024",
        state="NC", county="Buncombe",
        url=("https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
             "Buncombe_County_All_Property_Bills_Unpaid_from_2024/FeatureServer/0"),
        listing_type=ListingType.TAX_LIEN,
        where="real_value>0",
        fields=("bill", "pin", "owner1_last_name", "owner1_first_name",
                "house_num", "street_direction", "street_name", "street_type",
                "address_line1", "address_line2", "city", "state", "postal_code",
                "real_value", "total_value", "levy_year"),
        parcel="pin", owner_last="owner1_last_name", owner_first="owner1_first_name",
        situs_parts=("house_num", "street_direction", "street_name", "street_type"),
        mailing_parts=("address_line1", "address_line2", "city", "state", "postal_code"),
        mail_state="state", mailing_source="county_tax_roll",
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
        fields=("REID", "dmg_loc", "damage_cat_cal", "program_type", "county",
                # 2026-10-08 source-completeness audit: on the layer, never requested. The
                # assessor's own point (latitude/longitude, 456 of 456 rows) places the row for
                # the geo parcel enricher: REID is Burke's 5-digit real-estate id, which
                # validation nulls (415 rows on the 2026-10-08 run), and Burke's parcel cache
                # keys on the 10-digit PIN. Damage_Val / BLDG_Val are NCEM's estimated damage
                # and building value, damage the short class, start_time the assessment time.
                "latitude", "longitude", "damage", "Damage_Val", "BLDG_Val", "start_time"),
        parcel="REID", situs="dmg_loc", lat_field="latitude", lon_field="longitude",
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
                "NUMBER", "DIR", "STREET", "TYPE", "CITY", "ZIPCODE", "PID",
                # 2026-10-07 extraction audit: the permit's own description (99%), its
                # type, issue/final/expiration/last-inspection dates, unit, zoning and
                # the layer's own Lat/Lon (92%) were never requested.
                "DESCRIPTION", "PERMIT_TYPE", "ISSUE_DATE", "FINALED_DATE",
                "EXPIRATION_DATE", "LAST_INSPECTION_DATE", "UNIT", "MAIN_ZONE",
                "Lat", "Lon"),
        # 2026-10-08: whole-structure demolitions that are still live. 'Interior Demolition' is
        # a renovation (160 rows), and Void/Withdrawn/Revoked permits are dead (161 rows): live
        # 2026-10-08, 1,746 -> 1,438. Same rule as nc_metro_demolition_permits (dead permits
        # dropped, an EXPIRED permit kept as a stalled teardown; Greensboro's interior class not
        # read).
        where=("WORK_CLASS = 'Demolition' AND (PERMIT_STATUS IS NULL OR "
               "PERMIT_STATUS NOT IN ('Void','Withdrawn','Revoked'))"),
        parcel="PID", lat_field="Lat", lon_field="Lon",
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
    # ------------------------------------------------------------------
    # 2026-09-21 COUNTY-BREADTH ADDITIONS (docs/county_breadth_research_2026-09-21.md).
    # Verified live the same day: count, field list, one real row, and the
    # value distribution of the filtered column.
    # ------------------------------------------------------------------
    # City of Columbia (Richland County) property code cases, 8,590 back to 2006.
    # Richland had 9 leads on the whole board and no code, vacancy or demolition
    # signal at all. Only the rows that describe a STRUCTURE the city has already
    # judged vacant, boarded or slated for demolition are admitted (1,064 of 8,590
    # on 2026-09-21): a yard-parking or roll-cart case is not a distressed property.
    # CaseStatus is limited to the two OPEN states ("In Violation", "Open"); the
    # 5,000+ other rows are resolved, no-violation or referred-out cases.
    #
    # CAVEATS, both measured: (1) the feed's newest OpenedDate is 2026-01-15, so it
    # has not been refreshed for about eight months and a case still "In Violation"
    # may have been cured since; (2) there is NO owner, parcel or value field, only
    # ADDRESS, so a lead here is an address the resolver must turn into an owner
    # (Richland has no parcel cache yet). The layer also carries Neighborhood and
    # CouncilDistrict, deliberately not requested.
    Layer(
        slug="columbia_code_vacant_boarded",
        state="SC", county="Richland",
        url=("https://services1.arcgis.com/Mnt8FoJcogKtoVBs/arcgis/rest/services/"
             "CodeViolationProperty/FeatureServer/0"),
        listing_type=ListingType.DISTRESSED,
        where=("CaseStatus IN ('In Violation','Open') AND "
               "(Problem LIKE '%Boarded Building%' OR Problem LIKE '%Demolition%' "
               "OR Problem LIKE 'Vacant Building%')"),
        fields=("CaseNum", "OpenedDate", "Problem", "CaseStatus", "ADDRESS"),
        situs="ADDRESS", detail="Problem", process="code_enforcement",
        source_page="https://www.columbiasc.gov/",
    ),
    # Greenville County parcels whose tax bill is still unpaid. TOTTAX > 0 with a NULL
    # PAIDDATE is the county's own "billed and not paid" state; on 2026-09-21 that was
    # 2,855 parcels, and 1,926 of the first 2,000 sampled carry a 2025 bill (ACCTNO
    # starts with the tax year), i.e. unpaid since the January 2026 due date, so these
    # are delinquent and not merely un-billed. Median bill about $825, first-2,000 sum
    # $4.3M. The layer is the county's replacement for the GreenvilleJS/Map_Layers_JS
    # service (removed between 2026-08-03 and 2026-09-21: "Service ... not found").
    #
    # Fields requested are property/assessment facts only: owner of record, situs
    # parts, tax value, the bill. STREET/CITY/STATE/ZIP5 on this layer are the OWNER'S
    # MAILING address, not the property's, so `city` and `zip_` are deliberately NOT
    # mapped (a mailing city stamped on the property would be wrong for every absentee);
    # the parcel cache (PARCEL_LAYERS["Greenville"]) supplies the mailing block by PIN.
    # DESCR is a legal description ("PH2", "UNIT B"), never a street.
    #
    # Tolerated: gcgis.org is a single county-run host that has already moved this
    # service once, and losing it must not discard the other layers' rows (see fetch()).
    Layer(
        slug="greenville_unpaid_tax_parcels",
        state="SC", county="Greenville",
        url=("https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/"
             "QueryLayers/MapServer/0"),
        listing_type=ListingType.TAX_LIEN,
        where="TOTTAX > 0 AND PAIDDATE IS NULL",
        fields=("PIN", "OWNAM1", "OWNAM2", "STRNUM", "STRPRE", "LOCATE", "STRTYP",
                "STRSUF", "TAXMKTVAL", "TOTTAX", "ACCTNO", "PROPTYPE",
                # 2026-10-07 extraction audit: on the layer, never requested (fill on a
                # live 2,000-row sample): last sale price SLPRICE (56%) + DEEDDATE and
                # deed book/page CUBOOK/CUPAGE (99%); FAIRMKTVAL/LANDVAL (100%) and
                # BLDGVAL (41%); SQFEET/BEDROOMS/BATHRMS/HALFBATH (~30%); prior owner
                # POWNNM (82%); GIS_ACRES (100%); care-of NAMECO; SUBDIV; LANDUSE;
                # IMPROVED; and the OWNER'S MAILING address STREET/CITY/STATE/ZIP5
                # (100%; only ~26% equal the situs), which now feeds raw.owner_mailing.
                "SLPRICE", "DEEDDATE", "CUBOOK", "CUPAGE", "FAIRMKTVAL", "LANDVAL",
                "BLDGVAL", "SQFEET", "BEDROOMS", "BATHRMS", "HALFBATH", "POWNNM",
                "GIS_ACRES", "NAMECO", "SUBDIV", "LANDUSE", "IMPROVED",
                "STREET", "CITY", "STATE", "ZIP5"),
        parcel="PIN", owner_last="OWNAM1",
        situs_parts=("STRNUM", "STRPRE", "LOCATE", "STRTYP", "STRSUF"),
        mailing_parts=("STREET", "CITY", "STATE", "ZIP5"), mail_state="STATE",
        value="TAXMKTVAL", detail="ACCTNO", process="tax", amount="TOTTAX",
        source_page="https://www.greenvillecounty.org/TaxCollector/OnlineTax.aspx",
    ),
    # ------------------------------------------------------------------
    # 2026-09-28 non-footprint code/vacant discovery pass (docs/coverage_gap_build_plan_2026-09-23.md
    # §2.5: this family has no statewide shortcut, each county needs its own check). Ran the check
    # against Mecklenburg, Wake, Guilford, Forsyth, Durham, Cumberland, Union, Cabarrus, Iredell NC
    # and York, Lexington, Horry SC. Mecklenburg was already genuinely covered by
    # city_websites/charlotte_open_data.py (not this module) so skipped here. The other 9 of these
    # 12 (Wake, Forsyth, Cumberland, Union, Cabarrus, Iredell NC; Lexington, Horry SC) turned up
    # nothing live and free after a real per-county search -- see that search's notes for what was
    # checked and why each was rejected (stale one-time snapshots, boundary-only layers with no case
    # data, thin non-property nuisance complaints, or an outright login/token wall). Only Guilford,
    # Durham (NC) and York (SC) had a real, live, case-level hit.
    # ------------------------------------------------------------------
    # Greensboro (Guilford County) code compliance cases, CaseStatus='A' (active) filters the
    # 98,696-row full case history down to 1,511 currently-open cases; CaseType='Housing' (665 of
    # those) isolates minimum-housing/structural violations from the weaker Nuisances/Vehicle/
    # Zoning/Front-Yard-Parking/Graffiti categories on the same layer -- several rows are absentee
    # LLC landlords (e.g. "Trail Llc", "Place Holdings Llc") with an out-of-state or out-of-county
    # mailing address, a real distressed-landlord signal. CaseNotes carries tenant name/phone
    # (confirmed live, e.g. "Tenant Andicca Clarke 336-42-6399") and is deliberately NOT requested,
    # same privacy discipline as the rest of this module.
    Layer(
        slug="greensboro_code_housing",
        state="NC", county="Guilford",
        url=("https://gis.greensboro-nc.gov/arcgis/rest/services/"
             "OpenGateCity/OpenData_CC_DS/MapServer/1"),
        listing_type=ListingType.DISTRESSED,
        where="CaseStatus='A' AND CaseType='Housing'",
        fields=("CaseNumber", "CaseType", "FullAddress", "City", "State",
                "OwnerName", "OwnerName2", "OwnerMailAddr", "OwnerMailCity",
                "OwnerMailState", "OwnerMailZip", "EntryDate", "CaseStatus"),
        situs="FullAddress", city="City", owner_last="OwnerName",
        process="code_enforcement",
        source_page=("https://www.greensboro-nc.gov/departments/"
                      "neighborhood-development/code-compliance"),
    ),
    # City of Durham's own "Open Landuse Code Violation Cases" dataset (its name, not a filter this
    # module applies) -- 1,110 rows, case numbers running "26-xxxx" confirming it is a live current
    # feed, not a stale export. No owner/parcel field, only situs (AddressNum + Street), so the
    # resolver supplies the owner the same way it does for Richland's columbia_code_vacant_boarded.
    # Topic breaks down as Repair Only (<50%) 734, Weedy/Junked Lot 225, Repair or Demolish (>50%)
    # 50, Unsafe Building 45, Vehicle 32, Weedy Chronic Violator 17, B/C Abatement 5 -- kept as one
    # unfiltered layer (unlike Greensboro) because "Repair or Demolish" and "Unsafe Building" alone
    # would be too thin and the dataset's own name says these are already the open ones.
    Layer(
        slug="durham_open_code_violations",
        state="NC", county="Durham",
        url=("https://webgis2.durhamnc.gov/server/rest/services/"
             "ProjectServices/NIS_LUCodeViolations/MapServer/0"),
        listing_type=ListingType.DISTRESSED,
        fields=("CaseNum", "PropertyStatus", "Topic", "AddressNum", "Street",
                "AptSuite", "PropertyCity", "PropertyState", "PropertyZip"),
        situs_parts=("AddressNum", "Street"), city="PropertyCity", zip_="PropertyZip",
        detail="Topic", process="code_enforcement",
        # Topic breakdown (see comment above): Repair Only/Repair or Demolish/
        # Unsafe Building/B-C Abatement are structural-condition categories;
        # Weedy/Junked Lot, Vehicle, Weedy Chronic Violator are yard-nuisance,
        # not admitted as severe (see Layer.ce_severe_re docstring).
        ce_severe_re=re.compile(r"repair|demolish|unsafe|abatement", re.I),
        source_page="https://www.durhamnc.gov/1303/Custom-Maps-and-Data-Layers",
    ),
    # City of Rock Hill (York County) "Open Cases" code-enforcement service -- a MapServer split
    # into ~15 per-category sub-layers sharing one schema (CaseNumber/Type/Status/AddressText/
    # CreatedDateTime/ClosedDateTime, all NULL ClosedDateTime confirmed live). Verified counts across
    # every sub-layer 2026-09-28: Housing 18, Demolition 15, Exterior Structure-Major 15, Exterior
    # Structure-Minor 42, Overgrown 94, Accessory Usage 8, Junk Vehicle 9, Accessory Structure 1,
    # Zoning 1, Short Term Rentals/Board/Exterior Property/Graffiti/Yard Debris/Unsecured Property 0.
    # Only the three genuinely structure-distress categories are admitted here -- Overgrown/Junk
    # Vehicle/Yard Debris/Accessory Usage are yard-nuisance complaints on otherwise-normal occupied
    # homes (same call already made for Greensboro's Nuisances and rejected for Pickens/Anderson
    # elsewhere in this file), not a distress signal. No owner field; case numbers run "CN-2026xxxx".
    Layer(
        slug="rockhill_code_housing",
        state="SC", county="York",
        url=("https://rockhillgis.cityofrockhill.com/arcgis/rest/services/"
             "OpenCodeEnforcementCases/Open_Cases/MapServer/1"),
        listing_type=ListingType.DISTRESSED,
        fields=("CaseNumber", "Type", "Status", "AddressText", "CreatedDateTime"),
        situs="AddressText", detail="Status", process="code_enforcement",
        source_page="https://www.cityofrockhill.com/departments/neighborhood-services",
    ),
    Layer(
        slug="rockhill_code_demolition",
        state="SC", county="York",
        url=("https://rockhillgis.cityofrockhill.com/arcgis/rest/services/"
             "OpenCodeEnforcementCases/Open_Cases/MapServer/5"),
        listing_type=ListingType.DISTRESSED,
        fields=("CaseNumber", "Type", "Status", "AddressText", "CreatedDateTime"),
        situs="AddressText", detail="Status", process="demolition_permit",
        condemned=True,
        source_page="https://www.cityofrockhill.com/departments/neighborhood-services",
    ),
    Layer(
        slug="rockhill_code_exterior_major",
        state="SC", county="York",
        url=("https://rockhillgis.cityofrockhill.com/arcgis/rest/services/"
             "OpenCodeEnforcementCases/Open_Cases/MapServer/7"),
        listing_type=ListingType.DISTRESSED,
        fields=("CaseNumber", "Type", "Status", "AddressText", "CreatedDateTime"),
        situs="AddressText", detail="Status", process="code_enforcement",
        source_page="https://www.cityofrockhill.com/departments/neighborhood-services",
    ),
    # ------------------------------------------------------------------
    # 2026-09-28 non-footprint code/vacant discovery pass, ROUND 2 (same day, second batch,
    # 12 more counties beyond the first 12 documented above). Every one came up NOT FOUND after a
    # real per-county search -- recorded here so a future session doesn't re-run this exact work.
    # No Layer entries resulted; this comment IS the deliverable of that research.
    #
    # Rowan (Salisbury): gis.rowancountync.gov Energov folder checked (Zoningcases = stale rezoning
    #   approvals back to 2004; MHPcases = mobile-home-park permits, no violation data). Salisbury's
    #   open-data hub (42 datasets) has none. Salisbury's "/311" CrowdsourceReporter app is titled
    #   "Salisbury311 (retired)" -- dead.
    # Davidson (Lexington/Thomasville): webgis.co.davidson.nc.us Lexington/OpenGov folders checked --
    #   OpenGov's layers (OpenGovParcelFlags, PlanningWarningLayer) are parcel/assessment master data
    #   (owner, sale history, zoning, tax code), no case number or violation-status field anywhere.
    #   A promising "Code Enforcement Service Requests" AGOL app is owned by gis_lfucg -- that's
    #   Lexington-Fayette, KENTUCKY, a name collision, not Lexington NC (also org-private).
    # Randolph (Asheboro): gis.randolphcountync.gov Planning/LandUseCases is a public-comment layer
    #   for rezoning cases, not violations. OpenData_PW's "Structures" layer is address/footprint
    #   only (house#, complex name, unit count), no status/case field. Code Enforcement is a
    #   2-officer, zoning-only office with no public case list.
    # Alamance (Burlington/Graham): the ReGIS regional platform (Burlington/Graham/Elon/county,
    #   shared Esri Portal) has two real code-enforcement layers -- BurlCodeEnforcement and
    #   SmartGov_Map layer 6 ("Code Enforcement Zones") -- but both are boundary-only
    #   enforcement-officer zone polygons (fields: Zone_ID/Enf_Officer only), same rejection class as
    #   Anderson/Gaston's boundary-only layers elsewhere in this file. Burlington's SeeClickFix Open311
    #   API can't be scoped to the city (jurisdiction_id/lat/lng params both return an unfiltered
    #   global feed). navburl-burlington.opendata.arcgis.com is Burlington, ONTARIO -- false positive.
    # Orange (Chapel Hill/Carrboro/Hillsborough): gis.orangecountync.gov's EnerGov "Planning" layer
    #   only carries Name/Description/CreatedDate (sampled record was a rezoning case, not a
    #   violation). Chapel Hill's ArcGIS Hub has SeeClickFix requests and a permit tool, no violation
    #   dataset. Carrboro's old GIS host is dead (NXDOMAIN). A "Hillsborough" dashboard that surfaces
    #   in search is Hillsborough County, FLORIDA -- false positive.
    # Pitt (Greenville NC): gis.pittcountync.gov and Greenville's own gisonline.greenvillenc.gov both
    #   fully enumerated. Greenville's EnerGov MapServer DOES have layers named "Code Enforcement
    #   Zones" and "CodeEnforcement_6Zones" -- both are enforcement-district boundary polygons, not
    #   case records (same rejection class as Alamance above). City's Code Enforcement page only
    #   links a write-only PublicStuff complaint-filing widget.
    # Berkeley SC (Moncks Corner/Goose Creek): county's ArcGIS Server "energov" and "internal" folders
    #   return 403 Forbidden; Goose Creek's own EnerGov/OpenGov folders return "499 Token Required" --
    #   explicit login/token walls. Everything actually public (a 77-layer composite map, a "custom"
    #   folder) is zoning/parcel/flood/school/voting boundary data only.
    # Kershaw SC (Camden): county's ArcGIS Hub (17 datasets) is parcels/zoning/boundary only. A
    #   "Camden Code Enforcement Viewer Dashboard" is explicitly titled "(Internal)" and its AGOL item
    #   lookup confirms "Item does not exist or is inaccessible" -- private/login-walled. Camden does
    #   have a real vacant-building registry ordinance (125-day trigger) but it's an
    #   administrative/paper process with no public map/list/API.
    # Williamsburg SC (Kingstree): county GIS runs on WTH Technology's "ThinkGIS" -- a proprietary
    #   parcel viewer with no REST/JSON API, not Esri/ArcGIS (this vendor also serves Clarendon and
    #   Marlboro below, which is why none of these three show up in ArcGIS org/REST searches the way
    #   Guilford/Durham/York did). Kingstree's Code Enforcement page is contact-only.
    # Colleton SC (Walterboro): the one shape-matching hit on the county's AGOL org --
    #   CitizenProblemReports FeatureServer, with layers literally named "Blight Problems" and
    #   "Building Problems" -- is confirmed EMPTY (all 13 sub-layers return count:0), an unconfigured
    #   "ArcGIS for Local Government" template ("allows you to use an existing service to publish an
    #   empty feature layer" per its own description). Same pattern as Gaston's already-rejected
    #   "Blight Problems, live, 0 rows" case elsewhere in this file. Real system is Accela Citizen
    #   Access (a stateful ASP.NET WebForms app, no plain-GET/JSON endpoint) -- an acceptable non-hit,
    #   not forced as a match.
    # Clarendon SC (Manning): same WTH ThinkGIS proprietary viewer as Williamsburg -- no code-case
    #   layer, no ArcGIS Hub exists for this county.
    # Marlboro SC (Bennettsville): same WTH ThinkGIS proprietary viewer. County's real code-enforcement
    #   system is on sc.accessgov.com/marlboro, a JS single-page app that's primarily a building-permit
    #   application portal; probed common REST paths (api/publicsearch, api/search,
    #   api/PublicRecords/Search, api/CodeEnforcement, etc.) -- all 404, no open query endpoint.
    # ------------------------------------------------------------------
    # 2026-10-03 condition-code reconnaissance (continuing the condemned/code_
    # enforcement breadth work from 6e00d55b, which bridged 6 raw-key gaps but
    # explicitly left "is there a Spartanburg-style CAMA condition field anywhere
    # else" as a scoped-but-not-attempted recon task). Checked the ArcGIS field
    # list (?f=json on the layer root -- no query needed) of every county this
    # project already queries for owner/mailing/parcel resolution but had not yet
    # been checked for this specific field: the 34-county `parcel_cache.PARCEL_
    # LAYERS` registry minus the counties already checked that day (Mecklenburg,
    # Spartanburg, Greenville, Richland, Guilford, Durham, York, Henderson, Burke,
    # Transylvania, New Hanover), plus a few more with wired GIS access
    # (enrichment_arcgis.NC_GIS/SC_GIS, sc_coastal_rosters) -- 22 counties total:
    # NC Rutherford/Cleveland/Polk/Gaston/McDowell/Lincoln/Madison/Mitchell/
    # Carteret/Onslow/Brunswick/Pender; SC Laurens/Pickens/Colleton/Beaufort/
    # Georgetown/Charleston/Anderson/Oconee/Union/Horry, PLUS the 13 SC counties
    # in PARCEL_LAYERS not covered above (Aiken/Barnwell/Berkeley/Calhoun/Chester/
    # Darlington/Florence/Greenwood/Hampton/Lancaster/Lexington/Saluda/Sumter) --
    # 35 counties checked live in total. Also confirmed, live, that the NC OneMap
    # statewide fallback (NC1Map_Parcels, the ~90-county safety net behind every
    # NC county with no dedicated layer) carries no condition field at all --
    # `struct` is a bare Y/N "has a structure" flag, not a condition rating.
    #   Two already-wired fields turned up (NOT net-new, confirmed by grep before
    # building anything): Gaston's VacantImpro (already gaston_vacant.py's whole
    # signal) and Lincoln's parcel-layer VACANT (already lincoln_vacant.py's whole
    # signal) -- both vacant-LAND flags, not a condition/demolition signal anyway.
    # Carteret's Condition/GradeAndCDU (Average/Good/Fair/Poor/Very Poor/Unsound,
    # 854 distressed of 64,295 parcels, live-verified) looked like a fresh find
    # but is ALREADY wired, just through a different, older module than today's
    # condemned bridge: enrichment_cama_condition.py's CAMA_SOURCES, which already
    # lists Carteret (and Buncombe/Onslow/York/Spartanburg/Gaston) and is the
    # established home for "county assessor CONDITION rating" as a signal.
    #   Every other county in the 35 came back a genuine negative: no field in
    # its live schema resembling a condition/quality/demolition code (full field
    # lists eyeballed for the ones with few enough columns to do so safely; see
    # SOURCE_REGISTER.md for the slug/count this adds).
    #   ONE real, live, net-new, previously-unwired hit: Greenwood SC. Its CAMA
    # parcel layer (the SAME endpoint parcel_cache.PARCEL_LAYERS["Greenwood"]
    # already queries for owner/mailing) carries Condition/ConditionText +
    # Quality/QualityText -- an appraiser rating, not a code-case. Distinct
    # values live-verified 2026-10-03: Excellent, Very Good/Excellent, Good/Very
    # Good, Average/Good, Average, Badly Worn/Average, Badly Worn, Worn Out/Badly
    # Worn, Worn Out (12,106 Good-or-better of 22,441 non-null; 17,106 null —
    # never assessed or vacant-land cards). The two pure-distressed tiers,
    # 'Badly Worn' (681) and 'Worn Out' (28) plus the 10 straddling both ('Worn
    # Out/Badly Worn'), total 719 of 39,547 parcels county-wide -- live-verified
    # by direct count query, not a sample extrapolation. The ambiguous blended
    # label 'Badly Worn/Average' (600) is deliberately NOT included: it is a
    # genuine middle value on this scale, not a severe one, and forcing it in
    # would repeat the exact "field LOOKED right but was degenerate/ambiguous"
    # mistake this recon was explicitly told to avoid. Sample real rows (not just
    # the field name): "117 MADDOX RD" (owner LAUNCH PAD MOBILE LLC, tax value
    # $5,000), "16 EDGEWOOD DR" (owner BUTLER E BRYAN, built 1948, tax value
    # $17,300) -- genuine low-value, LLC- and individual-owned structures, the
    # motivated-seller profile this engine targets, not a degenerate always-same
    # value.
    #   Greenwood currently carries only 6 leads on the whole board (0 with a
    # parcel_id), so wiring this purely as a PIN-join enrichment the way Carteret
    # is wired would enrich zero existing rows today. Wired instead as its own
    # LEAD SOURCE here (process=`condemned`, Layer.condemned=True -> raw
    # ["condemned"]=True, Spartanburg's own bare-boolean shape, not a fabricated
    # code_enforcement case record -- see Layer.condemned docstring), the same
    # architecture spartanburg_condemned.py and rockhill_code_demolition already
    # use, so these 719 parcels become real new leads with their own owner/
    # situs/mailing/value rather than silently waiting for a parcel_id that may
    # never arrive. In scope per `in_scope_distressed()` ("if its a distressed
    # property its anywhere in nc and sc," config.py/validation.py, 2026-09-15)
    # even though Greenwood sits outside the older 18-county FLIP footprint
    # HERMES.md/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md still document as denied —
    # that denial is scoped to FLIP-type leads only, not every distress signal.
    Layer(
        slug="greenwood_cama_condemned",
        state="SC", county="Greenwood",
        url=("https://www.greenwoodsc.gov/arcgis/rest/services/"
             "Operational_Layers/CAMA/MapServer/9"),
        listing_type=ListingType.DISTRESSED,
        where="ConditionText IN ('Worn Out','Badly Worn','Worn Out/Badly Worn')",
        fields=("PIN", "Owner", "SiteAddress", "ConditionText", "YearBuilt",
                "TaxValue_Total", "MailAddress", "MailCityState"),
        parcel="PIN", owner_last="Owner", situs="SiteAddress",
        value="TaxValue_Total", detail="ConditionText",
        mailing_parts=("MailAddress", "MailCityState"),
        mailing_source="greenwood_cama_condemned",
        condemned=True, process="condemned",
        source_page="https://www.greenwoodsc.gov/departments/assessor",
    ),
    # ------------------------------------------------------------------
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


#: "No house number assigned" sentinels NC layers write in the house-number slot
#: of an otherwise real road ("0 TIPTON HILL RD", "99999 MEADOW RD") -- the same
#: convention web_artifact._PLACEHOLDER_HOUSE_NUM_RE and
#: enrichment_parcel_from_geo._NC_NO_NUMBER_SENTINELS guard against elsewhere in
#: this codebase. `situs_parts`' first element is documented as the house-number
#: column, so it is the only one checked.
_HOUSE_NUM_SENTINEL_RE = re.compile(r"^(?:0+|9{4,})$")


def _norm_addr(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.lower().replace(",", " ").split())


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


def _own_coords(a: dict, lay: Layer) -> dict:
    """latitude/longitude from the layer's own coordinate columns, when it declares them
    and they are real degrees (0 and out-of-range values are this kind of layer's nulls)."""
    if not (lay.lat_field and lay.lon_field):
        return {}
    try:
        lat, lon = float(a.get(lay.lat_field)), float(a.get(lay.lon_field))
    except (TypeError, ValueError):
        return {}
    if not (-90 < lat < 90 and -180 < lon < 180) or lat == 0 or lon == 0:
        return {}
    return {"latitude": lat, "longitude": lon}


def _raw_block(a: dict, lay: Layer) -> dict:
    """The raw["arcgis_distress"] sub-dict: every non-blank requested attribute, plus a
    normalised `amount_owed` when the layer declares an amount field."""
    # An attribute bag from a county layer: explicit outFields only (Layer.fields), and
    # never an SSN/licence/birth-date-like column (sensitive_fields.drop_sensitive).
    # The owner's MAILING columns are kept out of this property-shaped block: they belong
    # in raw["owner_mailing"] only, so nothing can read a mailing CITY/STREET here as the
    # property's own (the guard test_arcgis_distress_breadth's Greenville test pins).
    mail_cols = set(lay.mailing_parts) | ({lay.mail_state} if lay.mail_state else set())
    blk = {"layer": lay.slug, **{k: v for k, v in drop_sensitive(a).items()
                                 if v not in (None, "") and k not in mail_cols}}
    if lay.amount:
        amt = _num(a.get(lay.amount))
        if amt:
            blk["amount_owed"] = amt
    return blk


def _to_listing(a: dict, lay: Layer) -> Optional[Listing]:
    situs = _clean(a.get(lay.situs)) if lay.situs else None
    if not situs and lay.situs_parts:
        bits = []
        for i, p in enumerate(lay.situs_parts):
            v = _clean(a.get(p))
            if i == 0 and v and _HOUSE_NUM_SENTINEL_RE.match(v):
                v = None                # "0"/"99999" no-address-assigned sentinel
            bits.append(v)
        situs = " ".join(b for b in bits if b) or None
    parcel = _clean(a.get(lay.parcel)) if lay.parcel else None
    if not (situs or parcel):
        return None                     # nothing to locate the property by
    owner = _owner(a, lay)
    detail = _clean(a.get(lay.detail)) if lay.detail else None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    bits = [b for b in (owner, situs, detail) if b]
    raw: dict = {"arcgis_distress": _raw_block(a, lay)}
    if lay.process == "code_enforcement":
        # 2026-10-02 breadth fix -- see Layer.ce_severe_re docstring. One row here
        # is one case, not a grouped property (unlike henderson_code_violations.py's
        # per-PIN fold), so open_violations=1 per Listing; the board's own dedupe
        # merges repeat cases at the same parcel/address the same way any other
        # two independent sources would.
        severe = bool(lay.ce_severe_re.search(detail or "")) if lay.ce_severe_re else True
        raw["code_enforcement"] = {
            "county": lay.county,
            "open_violations": 1,
            "total_violations": 1,
            "prior_cases": 0,
            "repeat_offender": False,
            "violation_types": [detail] if detail else [],
            "severe": severe,
            "violations": [{
                "violation": detail or "unknown",
                "status": "open",
                "date": None,
                "case_id": parcel or situs,
            }],
            "has_open": True,
            "vacancy_adjacent": severe,
            "source": lay.slug,
        }
        if severe:
            raw["distressed"] = True
    if lay.condemned:
        # See Layer.condemned docstring: a bare boolean, Spartanburg's own
        # shape, for a layer whose rows are a condition rating or a city-
        # ordered demolition case rather than an actual case-tracked
        # code-enforcement complaint. rockhill_code_demolition (15 real open
        # cases, live-verified 2026-10-02) and greenwood_cama_condemned (719
        # real "Badly Worn"/"Worn Out" CAMA parcels, live-verified 2026-10-03)
        # both opt in explicitly; New Hanover's demolition_permits layer
        # (a homeowner's own voluntary teardown application, not a
        # condemnation) deliberately does not.
        raw["condemned"] = True
    if lay.mailing_parts:
        mail_bits = [_clean(a.get(p)) for p in lay.mailing_parts]
        mailing = " ".join(b for b in mail_bits if b) or None
        if mailing:
            mail_state = _clean(a.get(lay.mail_state)) if lay.mail_state else None
            mail_state = (mail_state or "").upper()[:2] or None
            raw["owner_mailing"] = {
                "owner": owner,
                "mailing": mailing,
                "situs": situs,
                "parcel_id": parcel,
                "mail_state": mail_state,
                "absentee": bool(situs and _norm_addr(situs) not in _norm_addr(mailing)),
                "out_of_state": bool(mail_state and mail_state != lay.state),
                "source": lay.mailing_source or lay.slug,
            }
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
        **_own_coords(a, lay),
        owner_name=owner, defendant=owner,
        tax_value=_num(a.get(lay.value)) if lay.value else None,
        foreclosure_process=lay.process,
        description=f"{lay.county} {lay.state} — {' | '.join(bits)}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
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
        # These are tolerated: each is under 100 rows, each sits on a
        # single-city/county host, and losing one is not worth losing the
        # rest. LayerHarvest still logs tolerated=True, so the loss stays
        # VISIBLE — it is an accepted loss, not a silent one. Every
        # county-scale layer stays hard-fail.
        #
        # lincoln_code_violations added 2026-09-15: arcgisserver.lincolncountync.gov
        # has an incomplete TLS chain (same host the dedicated
        # lincoln_code_violations.py scraper already works around with a local
        # verify=False httpx client). This shared harvester uses one client
        # across all 18 layers, so a per-host verify override isn't practical
        # here without weakening TLS checks for every other host too -- and
        # this layer's real signal is tiny anyway (only 66 of 3,465 violations
        # are OPEN). Tolerating it was discarding all 8,693 rows from the other
        # 17 healthy layers on every run.
        #
        # The five 2026-09-28 additions (greensboro_code_housing,
        # durham_open_code_violations, rockhill_code_housing/_demolition/
        # _exterior_major) are each a brand-new, unproven single-city host
        # this module has zero operational track record with. Tolerating
        # them up front is the same trade already made for Greenville and
        # Lincoln above: a first-week flake on any one of them must not
        # discard every other county's rows the way Clinton's did.
        guard = LayerHarvest(
            self.slug, [lay.slug for lay in LAYERS],
            tolerate=("laurens_county_owned", "pickens_county_owned",
                      "burke_county_owned", "lincoln_code_violations",
                      "greenville_unpaid_tax_parcels",
                      "greensboro_code_housing", "durham_open_code_violations",
                      "rockhill_code_housing", "rockhill_code_demolition",
                      "rockhill_code_exterior_major"),
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
