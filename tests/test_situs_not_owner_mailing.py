"""A listing's PROPERTY address must be the parcel's situs, never the owner's mailing address.

THE BUG (2026-10-06). Every generic situs picker in the package (enrichment_arcgis._apply_attrs,
enrichment_address_backfill._populate_from_attrs, enrichment_parcel_lookup._populate_from_parcel,
enrichment_gis_attrs.apply_gis_attrs, enrichment_situs_address.apply_situs_address, and the
owner-v2 / name resolvers through them) read a county layer's attribute bag through
case-insensitive alias lists like "ADDRESS", "StreetAddress", "CITY", "ZIP". On several audited
layers those exact columns are the OWNER'S MAILING block:

    Buncombe NC property_bc_dis   Address/CityName/State/Zipcode = mailing, City = a jurisdiction
                                  code ("CAS"); the situs is HouseNumber + streetname + ...
    Spartanburg SC CAMA_Parcels   StreetAddress/City/State/Zip = mailing
    Lincoln NC                    ADDRESS1/ADDRESS2/CITY/STATE/ZIP = mailing
    Transylvania NC               ADDRESS_1 = a second owner's name, ADDRESS_3/CITY/... = mailing
    Pender NC, Pickens SC,        bare ADDR/ADD1/CITY/ZIP or Billing* / MAIL_* = mailing
    Georgetown SC, Carteret NC

Run against 40 live records per layer, the pickers wrote the owner's mailing street on 40/40
Buncombe records (gis_attrs also on 40/40 Spartanburg ones) and mailing city/ZIP on most
Lincoln, Pender, Pickens, Georgetown and Carteret records. On the 2026-10-06 board this put an
owner's mailing address on the property of ~1,100 rows (docs/HANDOFF.md item 69).

THE FIXTURE is those live records (captured 2026-10-06), pseudonymized for this public repo:
owner names and ids replaced, house numbers and street-name words remapped consistently within
each record (so "mailing == situs" holds exactly where it held live), cities/states/ZIPs kept.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_arcgis as ea
from foreclosure_scraper import enrichment_address_backfill as ab
from foreclosure_scraper import enrichment_address_owner_v2 as v2
from foreclosure_scraper import enrichment_gis_attrs as ga
from foreclosure_scraper import enrichment_parcel_lookup as pl
from foreclosure_scraper import enrichment_situs_address as sa
from foreclosure_scraper.models import Listing, ListingType

FIX = json.loads((Path(__file__).parent / "fixtures" / "county_layer_situs_vs_mailing.json").read_text())
LAYERS = FIX["layers"]

#: per layer: (situs single field or None, situs parts, mailing street field, mailing city, mailing zip)
TRUTH = {
    "buncombe_property_bc_dis": (None, ("HouseNumber", "NumberSuffix", "direction", "streetname",
                                        "StreetType", "PostDirection"), "Address", "CityName", "Zipcode"),
    "spartanburg_cama_parcels": ("PropertyLocation", (), "StreetAddress", "City", "Zip"),
    "lincoln_taxparcelviewer": ("PHYSICALADDR", (), "ADDRESS1", "CITY", "ZIP"),
    "transylvania_parcels": (None, (), "ADDRESS_3", "CITY", "ZIP_CODE"),
    "pender_layers_4": ("PROPERTY_ADDRESS", (), "ADDR", "CITY", "ZIP"),
    "pickens_open_data": ("LOCADD", (), "ADD1", "CITY", "ZIP"),
    "georgetown_energov": (None, ("StreetNumber", "StreetName"), "BillingAddress", "City", "ZipCode"),
    "carteret_parceldata": ("PropertyAddress", (), "MAIL_ADDRESS1", "MAIL_CITY", "MAIL_ZI5"),
}


def _norm(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _situs_of(name: str, a: dict) -> str | None:
    single, parts, *_ = TRUTH[name]
    if single:
        v = str(a.get(single) or "").strip()
        return v or None
    if parts:
        return ea.split_situs(a, parts)
    return None


def _owner_occupied(name: str, a: dict) -> bool:
    situs = _situs_of(name, a)
    mail = a.get(TRUTH[name][2])
    return bool(situs and mail and _norm(mail) and _norm(mail) in _norm(situs))


def _blank(name: str) -> Listing:
    st = "SC" if name.split("_")[0] in ("spartanburg", "pickens", "georgetown") else "NC"
    return Listing(source="t", source_url="https://x", listing_type=ListingType.TAX_LIEN,
                   state=st, county=name.split("_")[0].title(), raw={})


def _run_pickers(a: dict, name: str) -> dict[str, Listing]:
    out = {}
    li = _blank(name); ea._apply_attrs(li, copy.deepcopy(a)); out["arcgis._apply_attrs"] = li
    li = _blank(name); ab._populate_from_attrs(li, copy.deepcopy(a)); out["address_backfill"] = li
    li = _blank(name); pl._populate_from_parcel(li, copy.deepcopy(a)); out["parcel_lookup"] = li
    li = _blank(name); ga.apply_gis_attrs(li, copy.deepcopy(a)); out["gis_attrs"] = li
    li = _blank(name); sa.apply_situs_address(li, copy.deepcopy(a)); out["situs_address"] = li
    b = copy.deepcopy(a)
    li = _blank(name); v2._inject_site_alias(b, None); ab._populate_from_attrs(li, b)
    out["owner_v2"] = li
    return out


CASES = [(name, r["case"], r["attributes"]) for name in TRUTH for r in LAYERS[name]["records"]]


@pytest.mark.parametrize("name,case,attrs", CASES, ids=[f"{n}-{c}" for n, c, _ in CASES])
def test_no_picker_writes_the_owner_mailing_block_as_the_property(name, case, attrs):
    """Absentee / out-of-state records: no picker may write the mailing street, city or ZIP."""
    _, _, m_street, m_city, m_zip = TRUTH[name]
    occupied = _owner_occupied(name, attrs)
    situs = _situs_of(name, attrs)
    for picker, li in _run_pickers(attrs, name).items():
        if li.street_address:
            # whatever was written is the parcel's own situs
            assert situs and _norm(li.street_address) == _norm(situs), (picker, case, li.street_address)
        if not occupied:
            if attrs.get(m_street):
                assert _norm(li.street_address) != _norm(attrs[m_street]) or \
                    _norm(attrs[m_street]) == _norm(situs), (picker, case, "mailing street")
            # the layer's own situs city/ZIP (Pickens LOCCITY, Spartanburg StreetCommunity ...)
            # may coincide with the mailing one; anything else equal to the mailing is wrong
            view = ea.situs_view(attrs)
            if attrs.get(m_city) and li.city and _norm(view.get("PROP_CITY")) != _norm(attrs[m_city]):
                assert _norm(li.city) != _norm(attrs[m_city]), (picker, case, "mailing city")
            mz = re.sub(r"\D", "", str(attrs.get(m_zip) or ""))[:5]
            sz = re.sub(r"\D", "", str(view.get("PROP_ZIP") or ""))[:5]
            if mz and li.zip_code and sz != mz:
                assert li.zip_code != mz, (picker, case, "mailing zip")


@pytest.mark.parametrize("name,case,attrs", [c for c in CASES if _situs_of(c[0], c[2])],
                         ids=[f"{n}-{c}" for n, c, a in CASES if _situs_of(n, a)])
def test_every_picker_still_finds_the_situs(name, case, attrs):
    situs = _situs_of(name, attrs)
    for picker, li in _run_pickers(attrs, name).items():
        assert li.street_address, (picker, case)
        assert _norm(li.street_address) == _norm(situs), (picker, case, li.street_address, situs)


def test_buncombe_no_house_number_lot_gets_no_address():
    """99999 = no house number assigned. Before: the mailing street; now: nothing."""
    rec = next(r["attributes"] for r in LAYERS["buncombe_property_bc_dis"]["records"]
               if r["case"] == "no_number")
    for picker, li in _run_pickers(rec, "buncombe_property_bc_dis").items():
        assert not li.street_address, picker
        assert not li.zip_code, picker


def test_buncombe_owner_occupied_gets_postal_city_and_zip_absentee_does_not():
    recs = {r["case"]: r["attributes"] for r in LAYERS["buncombe_property_bc_dis"]["records"]}
    st, city, z = ea.situs_city_zip(recs["owner_occupied"])
    assert st == ea.split_situs(recs["owner_occupied"], TRUTH["buncombe_property_bc_dis"][1])
    assert city == recs["owner_occupied"]["CityName"] and z == recs["owner_occupied"]["Zipcode"]
    st, city, z = ea.situs_city_zip(recs["absentee"])
    assert st and _norm(st) != _norm(recs["absentee"]["Address"])
    assert city is None and z is None
    # `City` is a jurisdiction code, never a city
    for li in _run_pickers(recs["absentee"], "buncombe_property_bc_dis").values():
        assert (li.city or "").upper() not in ("CAS", "CBM", "CWV")


def test_registered_layers_detect_their_own_situs_column():
    """The LIKE/situs field detector (used by enrich(), owner-v2, the name resolver and
    situs_address) on each layer's real field list."""
    want = {"buncombe_property_bc_dis": None, "spartanburg_cama_parcels": "PropertyLocation",
            "lincoln_taxparcelviewer": "PHYSICALADDR", "transylvania_parcels": None,
            "pender_layers_4": "PROPERTY_ADDRESS", "pickens_open_data": "LOCADD",
            "georgetown_energov": None, "carteret_parceldata": "PropertyAddress"}
    for name, expect in want.items():
        url = LAYERS[name]["url"] + "/query"
        ea._FIELD_CACHE[url] = LAYERS[name]["fields"]
        try:
            got = asyncio.run(ea._detect_addr_field(None, url))
        finally:
            ea._FIELD_CACHE.pop(url, None)
        assert got == expect, (name, got)
    # an unregistered layer (Henderson) is untouched by the registry
    assert ea.layer_schema(LAYERS["henderson_parcels"]["fields"]) is None


def test_unregistered_layer_bag_is_returned_unchanged():
    rec = LAYERS["henderson_parcels"]["records"][0]["attributes"]
    assert ea.situs_view(rec) == rec
    assert ea.situs_view(rec) is not rec


def test_situs_view_does_not_modify_the_input_bag():
    rec = LAYERS["buncombe_property_bc_dis"]["records"][0]["attributes"]
    before = copy.deepcopy(rec)
    v = ea.situs_view(rec)
    assert rec == before
    assert "Address" not in v and "CityName" not in v and "City" not in v


def test_city_zip_aliases_carry_no_mailing_column():
    assert not any("mail" in c.lower() for c in ea.FIELD_ALIASES["city"])
    assert not any("mail" in c.lower() for c in ea.FIELD_ALIASES["zip"])


def test_buncombe_nc_gis_matches_on_situs_columns_not_address():
    cfg = ea.NC_GIS["Buncombe"]
    assert cfg["addr_field"].startswith("__concat:")
    fields = ea._concat_fields(cfg["addr_field"])
    assert "Address" not in fields and fields[0] == "HouseNumber" and "streetname" in fields


def test_split_situs_query_pins_the_house_number(monkeypatch):
    """A split-situs layer's LIKE query first pins HouseNumber, so a long road's real parcel
    is not lost behind the first 8 parcels on it."""
    seen = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"features": []}

    class _C:
        async def get(self, url, params=None, timeout=None):
            seen.append(params["where"])
            return _Resp()

    asyncio.run(ea._arcgis_query(_C(), "https://x/query", ea.NC_GIS["Buncombe"]["addr_field"],
                                 "12 Example Cove Rd", house_no="12"))
    assert seen[0].startswith("HouseNumber='12' AND UPPER(streetname) LIKE")
    assert "Address" not in " ".join(seen)


# ---------------------------------------------------------------------------------------
# Sources that read these layers / bills directly
# ---------------------------------------------------------------------------------------

def test_buncombe_elderly_publishes_the_situs_and_keeps_the_mailing_in_raw(monkeypatch):
    from foreclosure_scraper.scrapers.counties_nc import buncombe_elderly as m
    from tests._arcgis_fakes import FakeHttp

    recs = {r["case"]: dict(r["attributes"]) for r in LAYERS["buncombe_property_bc_dis"]["records"]}
    for i, a in enumerate(recs.values()):
        a.update(owner=f"OWNER {i}", pin=f"96490000{i:02d}", Exempt="ELD", Class="100",
                 TotalMarketValue="100000", TaxValue="100000")
    http = FakeHttp(pages=[{"features": [{"attributes": a} for a in recs.values()]}, {"features": []}])

    class _Ctx:
        async def __aenter__(self):
            return http

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(m, "client", lambda *a, **kw: _Ctx())
    out = {li.parcel_id: li for li in asyncio.run(m.BuncombeElderly().fetch())}
    by_case = dict(zip(recs, out.values()))

    occ, absn, oos, nonum = (by_case[c] for c in ("owner_occupied", "absentee", "out_of_state", "no_number"))
    for case, li in by_case.items():
        a = recs[case]
        assert _norm(li.street_address) != _norm(a["Address"]) or case == "owner_occupied", case
        om = li.raw["owner_mailing"]
        assert _norm(a["Address"]) in _norm(om["mailing"]) and om["source"] == "buncombe_elderly_gis"
    assert _norm(occ.street_address) == _norm(recs["owner_occupied"]["Address"])
    assert occ.city == recs["owner_occupied"]["CityName"].title()
    assert occ.zip_code == recs["owner_occupied"]["Zipcode"]
    assert occ.raw["owner_mailing"]["absentee"] is False
    assert absn.street_address == ea.split_situs(recs["absentee"], TRUTH["buncombe_property_bc_dis"][1])
    assert absn.city is None and absn.zip_code is None
    assert absn.raw["owner_mailing"]["absentee"] is True
    assert oos.raw["owner_mailing"]["out_of_state"] is True and oos.zip_code is None
    assert nonum.street_address is None and nonum.city is None


def test_transylvania_tax_bill_mailing_goes_to_raw_not_the_property():
    from foreclosure_scraper.scrapers.counties_nc.transylvania_delinquent_tax import (
        _owner_mailing_block, _parse_detail)

    # The ViewTaxBill detail page's flattened shape (fictional owner and address).
    page = """
    <div>Account Info</div>
    <div>Account Number :</div><div>70000001</div>
    <div>Example Holdings Trust</div>
    <div>48 Sample Ct</div>
    <div>Reno, NV 89501</div>
    <div>Bill Info</div>
    <div>Parcel Number :</div><div>8500000000000</div>
    <div>Legal Description :</div><div>U1 L1 EXAMPLE CT</div>
    """
    det = _parse_detail(page)
    om = _owner_mailing_block(det, "Example Holdings Trust", "8500000000000")
    assert om["street"] == "48 Sample Ct" and om["state"] == "NV"
    assert om["out_of_state"] is True and om["absentee"] is True and om["situs"] is None
    assert "48 Sample Ct" in om["mailing"]
    src = Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper" / "scrapers" / \
        "counties_nc" / "transylvania_delinquent_tax.py"
    text = src.read_text()
    assert "street_address=None," in text and "Address shown is the owner mailing address" not in text


def test_qpaybill_po_box_in_the_property_address_cell_is_not_published():
    from foreclosure_scraper.scrapers.counties_sc import qpaybill_delinquent_roll as q

    rows = [{"ident": "000-00-00-001", "year": "2023", "amount": 120.0, "owner": "OWNER A",
             "address": "PO BOX 123", "status": "Unpaid"},
            {"ident": "000-00-00-002", "year": "2023", "amount": 80.0, "owner": "OWNER B",
             "address": "12 EXAMPLE RD", "status": "Unpaid"}]
    out = {li.raw["qpaybill_roll"]["identification_no"]: li for li in q._to_listings("Oconee", rows)}
    assert out["000-00-00-001"].street_address is None
    assert out["000-00-00-001"].raw["qpaybill_roll"]["address_cell_owner_mailing"] == "PO BOX 123"
    assert out["000-00-00-001"].raw["owner_mailing"]["mailing"] == "PO BOX 123"
    assert out["000-00-00-002"].street_address == "12 EXAMPLE RD"


def test_lis_pendens_resolver_spartanburg_reads_property_location_not_street_address():
    from foreclosure_scraper.enrichment_lis_pendens_resolver import COUNTY_SCHEMA, _resolve_address

    rec = next(r["attributes"] for r in LAYERS["spartanburg_cama_parcels"]["records"]
               if r["case"] == "out_of_state")
    out = _resolve_address(dict(rec, OwnerName="DOE JANE"), COUNTY_SCHEMA["Spartanburg"], "Jane Doe")
    assert out["street_address"] == rec["PropertyLocation"]
    assert out.get("city") == "SPARTANBURG"          # StreetCommunity, not the mailing City
    assert out.get("zip") == rec["StreetZip"][:5]    # StreetZip, not the mailing Zip
    assert out["mailing_zip"] == rec["Zip"][:5]


def test_lis_pendens_resolver_no_occupancy_flag_never_takes_the_mailing_address():
    from foreclosure_scraper.enrichment_lis_pendens_resolver import _resolve_address

    schema = {"owner": ("Name",), "situs": (), "situs_parts": ("STREET_NUM", "STREET_NAM"),
              "mailing": ("Address_2",), "city": ("Address_3",), "zip": ("ZIP_CODE",),
              "parcel": ("ParcelID",), "owner_occ": ()}
    attrs = {"Name": "DOE JANE", "Address_2": "48 SAMPLE CT", "Address_3": "RENO NV",
             "ZIP_CODE": "89501", "ParcelID": "001-00-00-001", "STREET_NUM": "0", "STREET_NAM": "EXAMPLE RD"}
    out = _resolve_address(attrs, schema, "Jane Doe")
    assert "street_address" not in out          # neither the mailing nor a no-number road
    assert "city" not in out and "zip" not in out
    assert out["parcel_id"] == "001-00-00-001" and out["mailing_zip"] == "89501"


# The Spartanburg assessor CSV's real header (captured 2026-10-06) and one pseudonymized row:
# an absentee owner mailing from "10 SAMPLE HWY" owns a lot at "933 EXAMPLE ST".
_SPBG_CSV = (
    "AccountNumber,ParcelNumber,CardNumber,CardCount,District,PermitType,DeedBook,DeedPage,SaleDate,"
    "LandSizeDescription,Acreage,OwnerName,TaxpayerName,StreetAddress,City,State,Zip,PreviousOwnerName,"
    "HomesteadNumber,PropertyLocation,LegalDescription,SaleAmount,PropertyType,BuildingType,BuildingGrade,"
    "PermitDate,PermitValue,PermitNumber,GISParcelNumber,PreviousAppraisedLandValue,"
    "PreviousAppraisedBuildingValue,CurrentAppraisedLandValue,CurrentAppraisedBuildingValue,"
    "CurrentTaxableLandValue,CurrentTaxableBuildingValue,PreviousTaxableLandValue,PreviousTaxableBuildingValue,"
    "PreviousAssessedLandValue,PreviousAssessedBuildingValue,CurrentAssessedLandValue,"
    "CurrentAssessedBuildingValue,YearBuilt,Census,FireDistrict,TownCode,LandUse,ReviewDate,ConditionFactor,"
    "LivingArea,TotalArea,Units,StoryHeight,FullBaths,HalfBaths,BedRooms,Fireplaces,Foundation,Frame,"
    "RoofStructure,RoofStructure2,RoofCover,HeatType,SecondaryHeatType,HeatFuel,PrimaryExternalWallType,"
    "SecondaryExternalWallType,PrimaryInteriorWallType,SecondaryInteriorWallType,PrimaryFloors,"
    "SecondaryFloors,Basement,Garage,Attic,DesignCode,CDUC,Utility1,Utility2,Utility3,RoadType,Topo,"
    "AssessmentCode,StreetNumber,StreetDirection,StreetName,StreetCommunity,StreetHalf,StreetLot,StreetZip,"
    "OwnerLookup,LocationLookup,InstrumentNumber,RecID\n"
    "1,4-33-00-004.34,0,0,4B0J,,1,1,2023-02-14 0:00:00,ACRE,0.107,EXAMPLE LLC,EXAMPLE LLC,10 SAMPLE HWY,"
    "WOODRUFF,SC,29388,,,933 EXAMPLE ST WOODRUFF,LOT 1,330000,6RGP,,,1900-01-01 0:00:00,0,,"
    "6095-68-6217.69,2300,0,2300,0,2300,0,2300,0,138,0,138,0,0,236.00,TAF,J,RESIDENTIAL,"
    "1900-01-01 0:00:00,    ,0,0,0,,0,0,0,0,,,,,,,,,,,,,,,,,,,,PUBLIC WATER,SEPTIC,,PAVED,BLW,6% RES VAC,"
    "933,,EXAMPLE ST,WOODRUFF,,,29388,1,2,DEE-2023-1,1\n"
)


def test_sc_cama_spartanburg_csv_keys_on_the_situs_not_the_mailing_street(tmp_path, monkeypatch):
    import io
    from foreclosure_scraper import sc_assessor_cama as cama

    monkeypatch.setattr(cama, "DB_PATH", tmp_path / "cama.db")
    monkeypatch.setattr(cama.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(_SPBG_CSV.encode("latin-1")))
    spec = cama.SC_CAMA[("SC", "Spartanburg")]
    assert cama._build_from_csv("SC", "Spartanburg", spec, max_rows=None) == 1
    assert cama.lookup("SC", "Spartanburg", street_address="933 Example St")["market_value"] == 2300
    assert cama.lookup("SC", "Spartanburg", street_address="10 Sample Hwy") is None


def test_parcel_inventory_scdot_situs_never_reads_the_mailing_street():
    from foreclosure_scraper.parcel_inventory import _scdot_situs

    rec = next(r["attributes"] for r in LAYERS["spartanburg_cama_parcels"]["records"]
               if r["case"] == "absentee")
    assert _scdot_situs(rec) == rec["PropertyLocation"]
    assert _scdot_situs({"ADDRESS1": "48 SAMPLE CT", "LocationLookup": 1234775}) == ""


def test_enrich_claims_the_parcel_on_the_lead_s_own_street(monkeypatch):
    """The HouseNumber-pinned query returns every parcel with that number on a street
    containing the keyword (live Buncombe: 21 LAUREL AVE, 21 MOUNTAIN LAUREL DR, 21 LAUREL
    PARK DR). The parcel_id goes to the one on the lead's own street, never the first."""
    def rec(pin, street, stype):
        return {"pin": pin, "pinnum": pin + "00000", "CityName": "ASHEVILLE", "HouseNumber": "21",
                "streetname": street, "StreetType": stype, "Address": "PO BOX 1",
                "SITUS_ADDR": f"21 {street} {stype}"}
    results = [rec("1111111111", "MOUNTAIN HAZEL", "DR"), rec("2222222222", "HAZEL", "AVE"),
               rec("3333333333", "HAZEL PARK", "DR")]

    async def fake_query(c, base, addr_field, street, house_no=None, out_fields="*"):
        return [dict(r) for r in results]

    class _Ctx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(ea, "_arcgis_query", fake_query)
    monkeypatch.setattr(ea, "client", lambda *a, **kw: _Ctx())
    li = Listing(source="t", source_url="https://x", listing_type=ListingType.TAX_LIEN, state="NC",
                 county="Buncombe", street_address="21 Hazel Avenue", raw={})
    asyncio.run(ea.enrich([li], concurrency=1))
    assert li.parcel_id == "2222222222"
    li2 = Listing(source="t", source_url="https://x", listing_type=ListingType.TAX_LIEN, state="NC",
                  county="Buncombe", street_address="21 Hazel Court", raw={})
    asyncio.run(ea.enrich([li2], concurrency=1))
    assert li2.parcel_id is None        # three candidates, none on Hazel Court: claim none


def test_qpaybill_owner_mailing_street_in_the_address_cell_is_checked_against_the_county(monkeypatch):
    """Oconee's and Lancaster's portals put the owner's mailing street in the Property Address
    cell for some parcels. The county's own parcel record (local cache) decides."""
    from foreclosure_scraper import parcel_cache
    from foreclosure_scraper.scrapers.counties_sc import qpaybill_delinquent_roll as q

    cache = {  # pseudonymized shapes of real Oconee / Lancaster cache rows
        "1": {"owner_mailing": "48 SAMPLE CT RENO NV 89501"},                   # no situs, out of state
        "2": {"owner_mailing": "900 EXAMPLE RD LANCASTER SC 29720", "address": "CALVERT ESTATE RD"},
        "3": {"owner_mailing": "12 HOME ST KERSHAW SC 29067", "address": "12 HOME ST"},  # owner-occupied
        "4": {"owner_mailing": "77 OTHER RD WALHALLA SC 29691"},                 # no situs, in state
    }
    monkeypatch.setattr(parcel_cache, "lookup", lambda county, pid, state=None: cache.get(pid))
    assert q._owner_mailing_not_situs("Oconee", "1", "48 SAMPLE CT") == "out_of_state_mailing"
    assert q._owner_mailing_not_situs("Lancaster", "2", "900 EXAMPLE RD") == "mailing_not_situs"
    assert q._owner_mailing_not_situs("Lancaster", "3", "12 HOME ST") is None
    assert q._owner_mailing_not_situs("Oconee", "4", "77 OTHER RD") is None   # cannot tell: kept
    assert q._owner_mailing_not_situs("Oconee", "1", "5 UNRELATED LN") is None


def test_prior_board_merge_does_not_reinherit_the_mailing_as_the_property():
    """merge_prior_board folds the prior board in BEFORE any enricher runs, and Listing.merge()
    fills every field the fresh row left empty. A fixed source that now leaves the property
    address empty (situs unknown) must not get the prior row's mailing address back."""
    from foreclosure_scraper.board_persist import keep_mailing_off_address

    def li(**kw):
        base = dict(source="counties_nc.transylvania_delinquent_tax", source_url="https://x",
                    listing_type=ListingType.TAX_LIEN, state="NC", county="Transylvania",
                    parcel_id="8500000000000", raw={})
        base.update(kw)
        return Listing(**base)

    fresh = li(raw={"owner_mailing": {"mailing": "48 Sample Ct, Reno, NV 89501", "source": "transylvania_tax_bill"}})
    prior = li(street_address="48 Sample Ct", city="Reno", zip_code="89501")
    merged = fresh.merge(prior)
    assert merged.street_address == "48 Sample Ct"            # what merge() alone does
    assert keep_mailing_off_address(fresh, prior, merged) is True
    assert merged.street_address is None and merged.city is None and merged.zip_code is None

    # a prior street that came from the county's situs by parcel id is kept
    prior2 = li(street_address="48 Sample Ct", raw={"situs_address_source": "parcel_cache:exact"})
    merged2 = fresh.merge(prior2)
    assert keep_mailing_off_address(fresh, prior2, merged2) is False
    assert merged2.street_address == "48 Sample Ct"

    # a prior property address that is not the owner's mailing is inherited as before
    prior3 = li(street_address="12 Parcel Rd", city="Brevard")
    merged3 = fresh.merge(prior3)
    assert keep_mailing_off_address(fresh, prior3, merged3) is False
    assert merged3.street_address == "12 Parcel Rd" and merged3.city == "Brevard"

    # a fresh row's own street is never touched; the owner's mailing city/ZIP still are not
    # inherited onto it
    fresh4 = li(street_address="12 Parcel Rd", raw=dict(fresh.raw))
    merged4 = fresh4.merge(prior)
    assert keep_mailing_off_address(fresh4, prior, merged4) is True
    assert merged4.street_address == "12 Parcel Rd" and merged4.city is None and merged4.zip_code is None
