"""Unit tests for the NC PTS Cloud land-records parcel resolver (no network)."""
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper import enrichment_lrcpwa_parcel as m


def _li(**kw):
    base = dict(source="counties_nc.nc_ptscloud_delinquent_tax", source_url="x",
                listing_type=ListingType.TAX_LIEN, state="NC", county="Henderson",
                parcel_id="10007200")
    base.update(kw)
    return Listing(**base)


_REC = {
    "propertyAddress1": "201 SUGARLOAF RD", "physicalAddressCity": "HENDERSONVILLE",
    "physicalAddressState": "NC", "physicalAddressZip": "28792",
    "totalPropertyValue": 476260, "primaryOwnerName": "HENDERSONVILLE HOSPITALITY LLC",
    "mailingAddress1": "2733 BONAR HALL PATH", "mailingAddressCity": "DULUTH",
    "mailingAddressState": "GA", "mailingAddressZip": "30097", "id": 123685, "reid": "10007200",
}


def test_apply_fills_address_value_owner_mailing():
    li = _li()
    filled = m._apply(li, _REC)
    assert filled
    assert li.street_address == "201 SUGARLOAF RD"
    assert li.city == "Hendersonville"
    assert li.zip_code == "28792"
    assert li.market_value == 476260.0
    lr = li.raw["lrcpwa"]
    assert lr["absentee"] is True          # mails to GA, property in NC
    assert lr["mailing"]["state"] == "GA"
    assert lr["id"] == 123685


def test_placeholder_address_not_set_but_value_kept():
    li = _li(parcel_id="9999")
    rec = dict(_REC, propertyAddress1="0 NO ADDRESS ASSIGNED")
    m._apply(li, rec)
    assert not (li.street_address or "")     # placeholder rejected
    assert li.market_value == 476260.0       # value still filled


def test_placeholder_detector():
    assert m._is_placeholder_addr("0 NO ADDRESS ASSIGNED")
    assert m._is_placeholder_addr("NO SITUS")
    assert m._is_placeholder_addr("0")
    assert not m._is_placeholder_addr("201 SUGARLOAF RD")


def test_county_gate():
    assert m._county(_li(county="Henderson")) == "Henderson"
    assert m._county(_li(county="Rutherford County")) == "Rutherford"
    assert m._county(_li(county="Buncombe")) is None   # not on the lrcpwa cluster


def test_never_clobbers_existing_address():
    li = _li(street_address="999 REAL ST")
    m._apply(li, _REC)
    assert li.street_address == "999 REAL ST"


def test_search_key_prefers_the_burke_spine_reid():
    """Burke leads reach the board as 10-digit map PINs, which this API answers
    with HTTP 500 (measured 2026-08-03: 0/26 by PIN, 25/26 by REID). Once
    nc_burke_spine has stamped the REID on, that is the key to search."""
    li = _li(county="Burke", parcel_id="2703905385",
             raw={"burke_spine": {"pin": "2703905385", "reid": "2796"}})
    assert m._search_key(li) == "2796"


def test_search_key_falls_back_to_the_parcel_id():
    assert m._search_key(_li()) == "10007200"
    # spine ran but could not resolve this PIN (ambiguous) — no REID to prefer
    assert m._search_key(_li(raw={"burke_spine": {"pin": "2713194819"}})) == "10007200"
    assert m._search_key(_li(raw={"burke_spine": "not-a-dict"})) == "10007200"
