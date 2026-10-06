"""enrichment_gis_attrs.apply_gis_attrs attaches the statutory exemption code (raw['gis_exempt'], and
raw['tax_relief'] bridged from it) only when the matched parcel feature IS the row's parcel.

THE DEFECT (measured 2026-10-06 on the 2026-10-05 board, 4,481 rows carrying an elderly / disabled
/ veteran claim: 3,898 are the elderly scraper's own rows; 156 came by a merge of that scraper's row
into a row of the SAME parcel; 371 by a merge into a row of ANOTHER parcel (the old address-key merge,
fixed in dedupe 2026-10-06); 51 only through this module). The 51 are rows whose lat/lng was queried
point-in-polygon against the county layer (enrichment_gis_attrs._query_point) and the code of
whatever polygon the point landed in was written to the row: a geocode on the road beside the house
or on a neighbour's land gave the row the neighbour's exemption. 41 of the 51 sit on a parcel that is
not exempt today.

The shapes below are the layer's own (Buncombe property_bc_dis/MapServer/1, outFields=*: `pin`,
`pinnum`, the situs columns HouseNumber / streetname / StreetType, `Address` = the OWNER'S mailing
address, `Exempt`); parcel ids and street addresses are public record, every owner is invented.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper import enrichment_gis_attrs as mod
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _lead(**kw) -> Listing:
    now = datetime.utcnow()
    base = dict(source="counties_generic.arcgis_distress.buncombe_unpaid_bills",
                source_url="https://example.test", listing_type=ListingType.TAX_LIEN,
                property_kind=PropertyKind.SINGLE_FAMILY, state="NC", county="Buncombe",
                first_seen=now, last_seen=now, latitude=35.62689, longitude=-82.55)
    base.update(kw)
    return Listing(**base)


def _feature(pin: str, code: str = "ELD", house: str = "87", street: str = "ELKWOOD",
             kind: str = "AVE", owner: str = "PRYDE MARCELLE", pad: str = "00000") -> dict:
    """One parcel of the county layer as outFields=* returns it."""
    return {"pin": pin, "pinnum": pin + pad, "owner": owner, "Exempt": code, "TaxYear": "26",
            "HouseNumber": house, "NumberSuffix": "", "direction": "", "streetname": street,
            "StreetType": kind, "PostDirection": "", "Address": "250 MAILING RD", "CityName": "FLETCHER",
            "State": "NC", "Zipcode": "28732", "TotalMarketValue": "310000", "TaxValue": "290000",
            "Class": "100"}


def _attached(li: Listing) -> bool:
    return "gis_exempt" in li.raw or "tax_relief" in li.raw


# ---- the parcel the feature is --------------------------------------------------------------

def test_the_rows_own_parcel_gets_the_code():
    li = _lead(parcel_id="9730-72-9200-00000", street_address="87 ELKWOOD AVE")
    mod.apply_gis_attrs(li, _feature("9730729200"))
    assert li.raw["gis_exempt"] == {"code": "ELD", "tag": "elderly_exemption"}
    assert li.raw["tax_relief"]["kind"] == "elderly"


@pytest.mark.parametrize("parcel", ["9730729200", "973072920000000", "9730-72-9200", "9730-72-9200-00000"])
def test_every_spelling_of_the_same_parcel_id_is_the_same_parcel(parcel):
    li = _lead(parcel_id=parcel)
    mod.apply_gis_attrs(li, _feature("9730729200"))
    assert li.raw["gis_exempt"]["code"] == "ELD"


def test_a_point_that_lands_in_a_neighbours_polygon_attaches_nothing():
    """31 Martin Luther King Jr Dr is the exempt parcel 9648695364; the row is the lien bill for the
    parcel next door, 9648690092, whose geocode fell on the neighbour: the code is not the row's."""
    li = _lead(parcel_id="9648-69-0092-00000", street_address="14 MARTIN LUTHER KING JR DR")
    flags = mod.apply_gis_attrs(li, _feature("9648695364", house="31", street="MARTIN LUTHER KING JR",
                                             kind="DR"))
    assert not _attached(li)
    assert li.raw["gis_attrs"]["matched"] is True and flags["owner_name"] == 1   # nothing else changed


def test_a_row_filed_under_another_parcel_id_than_the_parcel_at_its_address_attaches_nothing():
    """87 Elkwood Ave's lien row carries the unrelated '99999 Elkwood Ave' parcel id; the point lands
    on the real 87 Elkwood Ave (ELD). The parcel id is another parcel's: no claim for this row (the
    elderly scraper's own row of 9730729200 carries it)."""
    li = _lead(parcel_id="9730-71-7960-00000", street_address="87 ELKWOOD AVE")
    mod.apply_gis_attrs(li, _feature("9730729200"))
    assert not _attached(li)


def test_the_same_parcel_with_a_conflicting_address_attaches_nothing():
    li = _lead(parcel_id="9730729200", street_address="12 OTHER ST")
    mod.apply_gis_attrs(li, _feature("9730729200"))
    assert not _attached(li)


def test_the_same_parcel_with_no_comparable_address_is_enough():
    for addr in (None, "ELKWOOD AVE", "99999 ELKWOOD AVE"):
        li = _lead(parcel_id="9730729200", street_address=addr)
        mod.apply_gis_attrs(li, _feature("9730729200"))
        assert li.raw["gis_exempt"]["code"] == "ELD", addr


def test_a_point_alone_is_never_enough():
    """No parcel id and no address on the row: the polygon under a geocode proves nothing, and the
    address the same call then copies from the polygon must not count as the row's own."""
    li = _lead()
    flags = mod.apply_gis_attrs(li, _feature("9730729200"))
    assert flags["street_address"] == 1 and li.street_address == "87 ELKWOOD AVE"   # backfilled ...
    assert not _attached(li)                                                          # ... not identity


def test_an_exact_address_identifies_a_row_without_a_parcel_id():
    li = _lead(street_address="87 Elkwood Avenue")
    mod.apply_gis_attrs(li, _feature("9730729200"))
    assert li.raw["gis_exempt"]["code"] == "ELD"
    li = _lead(street_address="89 ELKWOOD AVE")                     # the next house
    mod.apply_gis_attrs(li, _feature("9730729200"))
    assert not _attached(li)


def test_a_parcel_a_resolver_took_from_the_same_point_is_no_identity():
    """raw['parcel_from_geo'] is the parcel under the row's own point (enrichment_parcel_from_geo):
    the polygon the point lands in is that parcel by construction. Only the address can say."""
    li = _lead(parcel_id="9730729200", raw={"parcel_from_geo": {"method": "point"}})
    mod.apply_gis_attrs(li, _feature("9730729200"))
    assert not _attached(li)
    li = _lead(parcel_id="9730729200", street_address="87 ELKWOOD AVE",
               raw={"parcel_from_geo": {"method": "point"}})
    mod.apply_gis_attrs(li, _feature("9730729200"))
    assert li.raw["gis_exempt"]["code"] == "ELD"


def test_a_condominium_unit_is_its_own_parcel():
    unit = _lead(parcel_id="9627023924C0102")
    mod.apply_gis_attrs(unit, _feature("9627023924", pad="C0102", house="14"))
    assert unit.raw["gis_exempt"]["code"] == "ELD"
    other = _lead(parcel_id="9627023924C0102")                      # the point hit the common area
    mod.apply_gis_attrs(other, _feature("9627023924", pad="00000", house="14"))
    assert not _attached(other)


def test_a_layer_without_a_recognizable_parcel_field_needs_the_address():
    attrs = {"Exempt": "ELD", "OBJECTID": 7, "SITUS_ADDR": "87 ELKWOOD AVE"}
    li = _lead(parcel_id="9730729200")
    mod.apply_gis_attrs(li, dict(attrs))
    assert not _attached(li)
    li = _lead(parcel_id="9730729200", street_address="87 ELKWOOD AVE")
    mod.apply_gis_attrs(li, dict(attrs))
    assert li.raw["gis_exempt"]["code"] == "ELD"


def test_no_code_on_the_feature_changes_nothing():
    li = _lead(parcel_id="9730729200")
    mod.apply_gis_attrs(li, _feature("9730729200", code=""))
    assert not _attached(li)


# ---- the elderly scraper's own rows ----------------------------------------------------------

def _own(code="ELD", **kw) -> Listing:
    return _lead(source=mod.ELDERLY_SOURCE, listing_type=ListingType.ELDERLY_DISABLED,
                 parcel_id="9730729200", street_address="87 ELKWOOD AVE",
                 raw={"gis_exempt": {"code": code, "tag": "elderly_exemption" if code == "ELD"
                                     else "disabled_veteran_exemption", "care_of": "A NIECE"},
                      "life_event": "elderly_disabled_homestead"}, **kw)


def test_the_scrapers_own_row_keeps_its_claim_whatever_polygon_the_point_hit():
    li = _own()
    mod.apply_gis_attrs(li, _feature("9730729200"))
    assert li.raw["gis_exempt"] == {"code": "ELD", "tag": "elderly_exemption", "care_of": "A NIECE"}
    li = _own()
    mod.apply_gis_attrs(li, _feature("9730710000", code="DIS", house="85"))   # a neighbour, another code
    assert li.raw["gis_exempt"] == {"code": "ELD", "tag": "elderly_exemption", "care_of": "A NIECE"}
    assert li.raw["tax_relief"]["kind"] == "elderly"                       # the bridge follows the row's own code


def test_the_scrapers_own_veteran_row_is_not_bridged_by_a_neighbours_elderly_code():
    li = _own(code="VET")
    mod.apply_gis_attrs(li, _feature("9730710000", code="ELD", house="85"))
    assert li.raw["gis_exempt"]["code"] == "VET" and "tax_relief" not in li.raw


# ---- what is not touched -----------------------------------------------------------------------

def test_an_existing_claim_is_left_alone_not_removed():
    """apply_gis_attrs only ever adds: a claim a prior run attached stays for the verifier to judge."""
    li = _lead(parcel_id="9648690092", raw={"gis_exempt": {"code": "ELD", "tag": "elderly_exemption"}})
    mod.apply_gis_attrs(li, _feature("9648695364", house="31", street="MARTIN LUTHER KING JR", kind="DR"))
    assert li.raw["gis_exempt"] == {"code": "ELD", "tag": "elderly_exemption"}


def test_values_and_owner_still_backfill_when_the_code_is_refused():
    li = _lead(parcel_id="9648690092")
    mod.apply_gis_attrs(li, _feature("9648695364"))
    assert not _attached(li) and li.owner_name == "PRYDE MARCELLE" and li.market_value == 310000


def test_exempt_parcel_relation_reads_the_row_before_the_call():
    attrs = _feature("9730729200")
    assert mod.exempt_parcel_relation("9730-72-9200-00000", "87 ELKWOOD AVE", False, attrs) == ("same", "match")
    assert mod.exempt_parcel_relation("9730-71-7960-00000", "87 ELKWOOD AVE", False, attrs) == ("different", "match")
    assert mod.exempt_parcel_relation(None, None, False, attrs) == ("unknown", "unknown")
    assert mod.exempt_parcel_relation("9730729200", "99999 ELKWOOD AVE", False, attrs) == ("same", "unknown")
    assert mod.exempt_parcel_relation("9730729200", "5 OTHER ST", True, attrs) == ("unknown", "conflict")
    assert mod.exempt_is_rows_own("same", "unknown") and mod.exempt_is_rows_own("unknown", "match")
    assert not mod.exempt_is_rows_own("same", "conflict") and not mod.exempt_is_rows_own("different", "match")
    assert not mod.exempt_is_rows_own("unknown", "unknown")
