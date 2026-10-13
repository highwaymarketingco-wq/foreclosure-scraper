"""Unit tests for counties_nc.nc_avalon_tax's record -> Listing parse.

FOUND 2026-10-13 (source-completeness audit, same Catalis/Avalon Wildfire
platform as counties_nc.rutherford_wildfire_tax): this scraper had no
real-estate type filter at all (a personal/business-property tax bill could
reach the board as a fake land lead) and silently dropped mailing address,
legal description, assessed value, status flags, the levy/fee breakdown, and
payment-history/original-amount-due signals that are already present on every
fetched record.

No real API fixture exists for this file -- CloudFront is currently blocking
live calls from both the Mac and the Oracle VM (see the module's _signal_block
docstring and this audit's own verification). The records below are
SYNTHETIC: built strictly from the real, confirmed Wildfire record schema in
tests/fixtures/rutherford_wildfire_records_page1.json (a genuine capture from
the sibling county on the same vendor platform), with plausible-but-made-up
Lincoln County values. No network.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc import nc_avalon_tax as m

_SLUG = "counties_nc.nc_avalon_tax"
_BASE_URL = "https://www.lincolncountytax.com"


def _rec(**overrides) -> dict:
    """A real-estate (REI), delinquent bill with every field populated --
    the full-schema happy path. Values are synthetic."""
    base = {
        "OwnerAddress": {
            "Line1": "412 OAK RIDGE RD",
            "City": "DENVER",
            "State": "NC",
            "Zip": "28037",
        },
        "OwnerName1": "SMITH, JAMES R",
        "OwnerName2": "",
        "Description": "LOT 14 OAK RIDGE SUB PB 22 PG 88",
        "AbstractType": "REI",
        "ParcelNumber": "4512-00-14",
        "FlagsString": "DLQ,ADVERTISED",
        "Flags": [
            {"Description": "DELINQUENT"},
            {"Description": "ADVERTISED"},
        ],
        "LineItems": [
            {
                "LevyType": "TAX", "LevyTypeDescription": "Tax",
                "TaxingUnit": "LINCOLN COUNTY", "LevyAmount": 1200.0, "LevyAmountDue": 1200.0,
            },
            {
                "LevyType": "ADVT", "LevyTypeDescription": "Advertisement",
                "TaxingUnit": "LINCOLN COUNTY", "LevyAmount": 2.0, "LevyAmountDue": 2.0,
            },
        ],
        "FilePaymentHistory": {},
        "Values": {
            "RealValue": 185000.0,
            "OriginalAmountDue": 1150.0,
            "AmountDue": 1202.0,
        },
        "SitusAddress": {"Line1": "412 OAK RIDGE RD", "City": "DENVER", "Zip": "28037"},
        "IDHash": "AB12CD34EF56",
        "BillingID": "4512-00-14-2025",
        "IDs": {"ID1": {"Name": "Year", "Value": "2025"}},
        "Year": 2025,
        "OwnerID": "OWN-9001",
        "Payment": {"Status": "Unpaid", "PaymentLog": {}},
        "isDelinquent": True,
    }
    base.update(overrides)
    return base


def test_personal_property_bill_is_filtered_out_entirely():
    """A vehicle (personal property) bill rides the same API/request shape
    with no server-side Property-type facet -- must be dropped client side
    or it becomes a fake real-estate lead."""
    rec = _rec(AbstractType="IND")
    assert m._record_to_listing(rec, "lincoln", "NC", _BASE_URL, _SLUG) is None


def test_business_property_bill_is_filtered_out_entirely():
    rec = _rec(AbstractType="BUS")
    assert m._record_to_listing(rec, "lincoln", "NC", _BASE_URL, _SLUG) is None


def test_real_estate_delinquent_bill_becomes_a_listing():
    li = m._record_to_listing(_rec(), "lincoln", "NC", _BASE_URL, _SLUG)
    assert li is not None
    assert li.parcel_id == "4512-00-14"
    assert li.owner_name == "SMITH, JAMES R"
    assert li.street_address == "412 OAK RIDGE RD"
    assert li.city == "DENVER"
    assert li.zip_code == "28037"
    assert li.county == "Lincoln"
    assert li.tax_value == 1202.0
    assert li.listing_type.value == "tax_lien"


def test_non_delinquent_real_estate_bill_with_positive_amount_due_is_kept():
    """Not-yet-delinquent but still owing -- the existing fallback this fix
    did not change."""
    rec = _rec(isDelinquent=False)
    li = m._record_to_listing(rec, "lincoln", "NC", _BASE_URL, _SLUG)
    assert li is not None
    assert li.tax_value == 1202.0


def test_non_delinquent_real_estate_bill_with_zero_amount_due_is_dropped():
    rec = _rec(isDelinquent=False, Values={"RealValue": 185000.0, "AmountDue": 0})
    assert m._record_to_listing(rec, "lincoln", "NC", _BASE_URL, _SLUG) is None


def test_owner_name_joins_name1_and_name2():
    rec = _rec(OwnerName1="SMITH, JAMES R", OwnerName2="SMITH, LINDA K")
    li = m._record_to_listing(rec, "lincoln", "NC", _BASE_URL, _SLUG)
    assert li.owner_name == "SMITH, JAMES R / SMITH, LINDA K"


def test_market_value_and_legal_description_are_captured():
    li = m._record_to_listing(_rec(), "lincoln", "NC", _BASE_URL, _SLUG)
    assert li.market_value == 185000.0
    assert li.legal_description == "LOT 14 OAK RIDGE SUB PB 22 PG 88"


def test_owner_mailing_address_is_captured():
    li = m._record_to_listing(_rec(), "lincoln", "NC", _BASE_URL, _SLUG)
    mail = li.raw["owner_mailing"]
    assert mail["addr"] == "412 OAK RIDGE RD"
    assert (mail["city"], mail["state"], mail["zip"]) == ("DENVER", "NC", "28037")


def test_missing_owner_address_returns_none_mailing():
    rec = _rec(OwnerAddress={})
    li = m._record_to_listing(rec, "lincoln", "NC", _BASE_URL, _SLUG)
    assert li.raw["owner_mailing"] is None


def test_flags_are_captured_from_flags_array():
    li = m._record_to_listing(_rec(), "lincoln", "NC", _BASE_URL, _SLUG)
    assert li.raw["flags"] == ["DELINQUENT", "ADVERTISED"]


def test_flags_fall_back_to_flags_string_when_flags_array_empty():
    rec = _rec(Flags=[], FlagsString="DLQ,OUTLAW")
    li = m._record_to_listing(rec, "lincoln", "NC", _BASE_URL, _SLUG)
    assert li.raw["flags"] == ["DLQ", "OUTLAW"]


def test_line_items_breakdown_is_captured():
    li = m._record_to_listing(_rec(), "lincoln", "NC", _BASE_URL, _SLUG)
    items = li.raw["line_items"]
    assert len(items) == 2
    by_type = {x["levy_type"]: x for x in items}
    assert by_type["TAX"] == {
        "levy_type": "TAX", "levy_type_description": "Tax",
        "taxing_unit": "LINCOLN COUNTY", "amount": 1200.0, "amount_due": 1200.0,
    }
    assert round(sum(x["amount"] for x in items), 2) == 1202.0


def test_has_payment_history_false_on_a_fully_unpaid_bill():
    li = m._record_to_listing(_rec(), "lincoln", "NC", _BASE_URL, _SLUG)
    assert li.raw["has_payment_history"] is False


def test_has_payment_history_true_when_file_payment_history_is_populated():
    rec = _rec(FilePaymentHistory={"Payments": [{"Amount": 50.0, "Date": "2026-01-01"}]})
    li = m._record_to_listing(rec, "lincoln", "NC", _BASE_URL, _SLUG)
    assert li.raw["has_payment_history"] is True


def test_original_amount_due_and_id_hash_are_captured():
    li = m._record_to_listing(_rec(), "lincoln", "NC", _BASE_URL, _SLUG)
    assert li.raw["original_amount_due"] == 1150.0
    assert li.raw["id_hash"] == "AB12CD34EF56"


def test_slim_line_items_handles_missing_or_malformed_line_items():
    assert m._slim_line_items({}) == []
    assert m._slim_line_items({"LineItems": None}) == []
    assert m._slim_line_items({"LineItems": ["not a dict"]}) == []


def test_flag_labels_empty_when_neither_flags_nor_flags_string_present():
    assert m._flag_labels({}) == []
