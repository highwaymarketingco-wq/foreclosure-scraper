"""Address synthesis must not stuff a shared boilerplate/no-house-number string into
street_address for sources that have no situs at all (2026-11-15).

THE BUG THIS PINS (identity-collision scan, see
project_vm_push_credentials_missing_and_board_divergence_2026-11-13.md, "Known
text-blob-address scraper bug" / pattern 3 of the 2026-11-15 no-zip/no-house-number
board-wide scan): counties_nc.polk_tax, counties_nc.nc_ptscloud_delinquent_tax and
counties_nc.nc_county_pdf_delinquent_tax never carry a situs on their own data (each
module's own docstring says so -- parcel_id is meant to backfill the address later via
GIS). When a row's `description` has no house-numbered address pattern either,
_synth_for_listing()'s "tax" catch-all branch (and, below it, the generic desc[:80]
last resort) used to wrap that same bare road name / repeated boilerplate sentence into
street_address regardless, and dedupe_key()'s address branch then merged every
DIFFERENT real parcel that happened to share it. Confirmed live 2026-11-15: Polk's
"Dublin Ln" key alone covered 15 distinct real taxdetail.php?id records; board-wide, 69
keys / 192 rows, 100% from these three sources.

Fix: these three sources now return None from _synth_for_listing() once the
house-numbered-address search just above has already failed, so street_address stays
null. For Polk that's the whole fix -- its source_url is per-record (taxdetail.php?id=N),
so dedupe_key() falls through all the way to a genuinely unique url: key on its own.

For the other two, whose source_url is ONE shared per-county download link, this is NOT
a new gap to patch here: dedupe.py already has a dedicated, tested mechanism for exactly
this shape (see dedupe.py's own "roll URL keys (2026-10-09, 4)" section and
board_persist._SOURCE_PARCEL_FIELDS, which lists both nc_ptscloud_delinquent_tax and
nc_county_pdf_delinquent_tax by name) -- it reads the id each row's OWN source published
even after validation.py nulled it for being too short (dedupe.nulled_source_parcel(),
raw['parcel_id_nulled']) and only merges two same-URL rows when nothing else disagrees
(dedupe.url_key_conflict()). Giving these two sources their own extra case_number (an
earlier draft of this fix did) bypasses that mechanism instead of relying on it, and
broke the published-row/grandfather-restore contract tests
(test_grandfather_restored_parcel.py, test_withdrawn_tag_sticky.py) that depend on them
reaching the plain url: key. The tests below instead prove the two layers compose
correctly as they are: this file's own exclusion stops the bad synthetic address, and
dedupe.py's existing identity evidence (exercised directly, not reimplemented) keeps
distinct real accounts apart once it does.
"""
from __future__ import annotations

from foreclosure_scraper import dedupe as D
from foreclosure_scraper.enrichment_address_final import (
    _synth_for_listing, enrich_with_address_synthesis,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.validation import validate


def _polk_row(n: int, owner: str, road: str, detail_id: str) -> Listing:
    return Listing(
        source="counties_nc.polk_tax",
        source_url=f"https://cms.revize.com/revize/apps/polkcounty/taxdetail.php?id={detail_id}",
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Polk", owner_name=owner,
        description=f"Polk County delinquent tax — {road}",
        raw={f"_rid_{n}": 1},
    )


def _ptscloud_row(n: int, owner: str, town: str, zip_code: str, parcel: str,
                   owed: float) -> Listing:
    """The live Madison shape: PARCEL_NUM ("parcel" here) is a short, non-placeholder
    internal sequence number that validation.py's too-short guard nulls back to None
    (Madison isn't on validation.COUNTY_NATIVE_SHORT_PARCEL's allowlist), and
    DESCRIPTION is the county's own repeated '0 NO 911 ADDRESS ASSIGNED <town>, NC <zip>'
    boilerplate for every unaddressed parcel in that town -- confirmed live, this exact
    text, Madison county."""
    return Listing(
        source="counties_nc.nc_ptscloud_delinquent_tax",
        source_url="https://bcpwa.ncptscloud.com/",
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Madison", owner_name=owner, defendant=owner,
        parcel_id=parcel,
        description=f"{owner} — Madison NC delinquent tax ${owed:,.0f} owed (parcel {parcel})",
        raw={f"_rid_{n}": 1, "nc_ptscloud_delinquent_tax": {
            "legal_description": f"0 NO 911 ADDRESS ASSIGNED {town}, NC {zip_code}",
            "parcel": parcel}},
    )


def test_polk_bare_road_name_is_not_synthesized():
    """No house number anywhere in the description -- must stay unaddressed."""
    li = _polk_row(1, "WILLIAMS DONNIE A", "DUBLIN LN", "2547")
    assert _synth_for_listing(li) is None


def test_polk_rows_sharing_one_road_stay_distinct_after_synthesis():
    """The exact live shape: 15 real parcels on Polk's own Dublin Ln, reduced to 3 here --
    each has its own taxdetail.php?id, so each must keep its own dedupe_key(). Polk's own
    source_url is already per-record, so this needs nothing beyond the exclusion."""
    rows = [
        _polk_row(1, "CHINQUAPIN HILL LLC", "DUBLIN LN", "7015"),
        _polk_row(2, "CHINQUAPIN HILL LLC", "DUBLIN LN", "7013"),
        _polk_row(3, "WILLIAMS DONNIE A", "DUBLIN LN", "2547"),
    ]
    enrich_with_address_synthesis(rows)
    assert all(li.street_address is None for li in rows)
    keys = {li.dedupe_key() for li in rows}
    assert len(keys) == 3
    assert all(k.startswith("url:") for k in keys)


def test_polk_row_with_a_real_house_numbered_address_is_still_taken():
    """The ~70% good case must keep working: when desc DOES carry a specific address,
    the generic address-pattern search above the exclusion already finds and returns it,
    and the exclusion must never shadow that."""
    li = Listing(source="counties_nc.polk_tax",
                 source_url="https://cms.revize.com/revize/apps/polkcounty/taxdetail.php?id=9001",
                 listing_type=ListingType.TAX_LIEN, state="NC", county="Polk",
                 owner_name="SUNNY HILL OWNER",
                 description="Polk County delinquent tax — 32 SUNNY HILL LN")
    assert _synth_for_listing(li) == "32 SUNNY HILL LN"


def test_ptscloud_repeated_911_boilerplate_is_not_synthesized():
    li = _ptscloud_row(1, "HAYES RUN REALTY, LLC", "MARSHALL", "28753", "183", 3140)
    assert _synth_for_listing(li) is None


def test_ptscloud_rows_sharing_the_911_boilerplate_stay_distinct_through_the_full_pipeline():
    """End to end, using the real downstream pipeline rather than reimplementing it: two
    DIFFERENT real Madison accounts, same town, same repeated DESCRIPTION boilerplate,
    each a short non-placeholder PARCEL_NUM. validate() nulls both (too short) and
    records raw['parcel_id_nulled']; this file's own fix keeps street_address null
    instead of masking that with a fake address; dedupe.py's existing
    nulled_source_parcel()/url_key_conflict() machinery (unchanged by this fix) then
    reads the nulled id back and keeps the two rows apart despite the shared
    source_url -- exactly the mechanism dedupe.py's own "roll URL keys" section
    documents for this source by name."""
    rows = [
        _ptscloud_row(1, "HAYES RUN REALTY, LLC", "MARSHALL", "28753", "183", 3140),
        _ptscloud_row(2, "SOMEBODY ELSE LLC", "MARSHALL", "28753", "211", 980),
    ]
    enrich_with_address_synthesis(rows)
    assert all(li.street_address is None for li in rows)
    validate(rows)
    assert {li.parcel_id for li in rows} == {None}
    assert {li.dedupe_key() for li in rows} == {"url:https://bcpwa.ncptscloud.com/"}
    assert D.nulled_source_parcel(rows[0].parcel_id, rows[0].raw, rows[0].source) == "183"
    assert D.nulled_source_parcel(rows[1].parcel_id, rows[1].raw, rows[1].source) == "211"
    merged = D.dedupe(rows)
    assert len(merged) == 2


def test_henderson_tax_synthesis_is_unchanged():
    """The exclusion is scoped to the three confirmed sources only -- a different
    "*_tax" source must keep its existing "Parcel — {description}" fallback."""
    li = Listing(source="counties_nc.henderson_tax", source_url="https://example.test/henderson",
                 listing_type=ListingType.TAX_SALE, state="NC", county="Henderson",
                 description="LT 5 BLK 2 SOME SUBDIVISION")
    assert _synth_for_listing(li) == "Parcel — LT 5 BLK 2 SOME SUBDIVISION"
