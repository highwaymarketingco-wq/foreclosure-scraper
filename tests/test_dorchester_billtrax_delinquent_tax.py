"""Dorchester SC BillTrax delinquent-tax scraper: field parsing, the real-estate
filter, and the multi-year aggregation.

WHY THESE TESTS EXIST, in one line each:

  * The search API returns EVERY bill ever flagged delinquent, including ones long
    since paid off (TotalDueNow == "0"). The "IsPaid"/"Unpaid" filter parameter was
    measured live (2026-09-29) to return an IDENTICAL PageAttributes.TotalRecords
    for "All"/"Paid"/"Unpaid" on a blank query -- so trusting that label instead of
    the actual TotalDueNow value would put thousands of zero-balance historical
    rows on the board as if they were live leads.
  * AccountNumber is shared by real estate (a TMS), vehicles/boats (a plain digit
    string) and business filings ("FIL########"). Feeding a non-TMS value into
    parcel_id would poison the parcel-keyed dedupe exactly the way Orangeburg's
    qPayBill account-ids already did in this repo (see qpaybill_delinquent_roll's
    own test suite) -- so only TMS-shaped AccountNumbers become leads.
  * A parcel delinquent across multiple tax years arrives as multiple bills sharing
    one AccountNumber. Emitting them as separate rows would put the same house on
    the board twice and hide the multi-year-delinquent signal (the "2+ years back"
    ripeness flag the motivated-seller engine looks for); aggregation sums the
    balance and lists the years once per parcel, the same shape as
    sc_catalis_delinquent_roll.aggregate_bills.

FIXTURES BELOW are verbatim field maps taken from LIVE production responses
(dorchestercountyscdelinquenttaxapi.billtrax.com, captured 2026-09-29), not
hand-built: APPELT_MULTIYEAR is account 161-00-00-097-000 ("APPELT BRIAN DAVID",
5090 Ashley River Rd), which really does carry two distinct-year unpaid bills
($6,212.98 for 2025 and $6,082.10 for 2024 -- a genuine, ongoing, 2-year-plus
delinquency). LONG_SINGLE is account 135-00-00-118-777, a single nonzero 2025
bill. CAROLINA_PERSONAL_PROPERTY is a real "M-" (non-real-estate) bill on the
same roll, included to prove the real-estate filter actually excludes it.
"""
from __future__ import annotations

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_sc.dorchester_billtrax_delinquent_tax import (
    UTILITY_ID,
    _aggregate,
    _bill_year,
    _field_map,
    _is_real_estate,
)

# --- verbatim Bill[] field lists, as the API returns them under
# Results[0].Rows[*].BillsAndPayments[*].Bill --------------------------------

APPELT_2025_BILL = [
    {"FieldName": "AccountNumber", "FieldValue": "161-00-00-097-000"},
    {"FieldName": "StickerNo", "FieldValue": ""},
    {"FieldName": "BillNumber", "FieldValue": "R-2025-00046221"},
    {"FieldName": "PropertyOwner", "FieldValue": "APPELT BRIAN DAVID"},
    {"FieldName": "PropertyLocation", "FieldValue": "ASHLEY RIVER RD 5090"},
    {"FieldName": "TotalDueNow", "FieldValue": "6212.9799999999996"},
    {"FieldName": "BillDate", "FieldValue": "2025-09-30T04:00:00Z"},
    {"FieldName": "BlockPayment", "FieldValue": "false"},
    {"FieldName": "ReasonToBlockPayment",
     "FieldValue": "Unavailable for online payment, please contact Delinquent Tax Office ."},
]
APPELT_2024_BILL = [
    {"FieldName": "AccountNumber", "FieldValue": "161-00-00-097-000"},
    {"FieldName": "StickerNo", "FieldValue": ""},
    {"FieldName": "BillNumber", "FieldValue": "R-2024-00046221"},
    {"FieldName": "PropertyOwner", "FieldValue": "APPELT BRIAN DAVID"},
    {"FieldName": "PropertyLocation", "FieldValue": "ASHLEY RIVER RD 5090"},
    {"FieldName": "TotalDueNow", "FieldValue": "6082.1000000000004"},
    {"FieldName": "BillDate", "FieldValue": "2024-10-11T04:00:00Z"},
    {"FieldName": "BlockPayment", "FieldValue": "false"},
    {"FieldName": "ReasonToBlockPayment",
     "FieldValue": "Unavailable for online payment, please contact Delinquent Tax Office ."},
]
LONG_2025_BILL = [
    {"FieldName": "AccountNumber", "FieldValue": "135-00-00-118-777"},
    {"FieldName": "BillNumber", "FieldValue": "R-2025-03500776"},
    {"FieldName": "PropertyOwner", "FieldValue": "LONG CHRISTOPHER F & AMANDA C (J"},
    {"FieldName": "PropertyLocation", "FieldValue": "ESTATES DR"},
    {"FieldName": "TotalDueNow", "FieldValue": "1797.77"},
    {"FieldName": "BillDate", "FieldValue": "2025-12-08T05:00:00Z"},
    {"FieldName": "BlockPayment", "FieldValue": "false"},
    {"FieldName": "ReasonToBlockPayment", "FieldValue": ""},
]
# A real "M-" (vehicle/manufactured-home/personal-property) bill on the same roll --
# AccountNumber is a plain digit account id, not a TMS.
CAROLINA_PERSONAL_PROPERTY_BILL = [
    {"FieldName": "AccountNumber", "FieldValue": "51831763"},
    {"FieldName": "BillNumber", "FieldValue": "M-2025-03500777"},
    {"FieldName": "PropertyOwner", "FieldValue": "CAROLINA CUSTOM CONTRACTING LL"},
    {"FieldName": "PropertyLocation", "FieldValue": "120 WALDEN RIDGE WAY          "},
    {"FieldName": "TotalDueNow", "FieldValue": "32.450000000000003"},
    {"FieldName": "BillDate", "FieldValue": "2026-09-14T04:00:00Z"},
    {"FieldName": "BlockPayment", "FieldValue": "true"},
    {"FieldName": "ReasonToBlockPayment",
     "FieldValue": "Unavailable for online payment, please contact Delinquent Tax Office ."},
]
# A historically-delinquent-but-now-PAID bill: IsDeliquent stays true forever as a
# permanent marker even though TotalDueNow is back to 0 -- the exact case that makes
# trusting the "Unpaid" filter label (rather than the value) wrong.
SMITH_PAID_OFF_BILL = [
    {"FieldName": "AccountNumber", "FieldValue": "012-00-00-137-000"},
    {"FieldName": "BillNumber", "FieldValue": "R-2025-03500291"},
    {"FieldName": "PropertyOwner", "FieldValue": "SMITH THERESA LORAINE"},
    {"FieldName": "PropertyLocation", "FieldValue": "MOUNT ZION RD"},
    {"FieldName": "TotalDueNow", "FieldValue": "0"},
    {"FieldName": "BillDate", "FieldValue": "2025-12-08T05:00:00Z"},
    {"FieldName": "BlockPayment", "FieldValue": "false"},
    {"FieldName": "ReasonToBlockPayment", "FieldValue": ""},
]


def _bp(bill_fields, *, is_deliquent=True, is_paid=False, bill_id="x", property_id="y"):
    """Wrap a Bill[] field list the way the real BillsAndPayments[] entry does."""
    return {"Bill": bill_fields, "Payment": [], "IsDeliquent": is_deliquent,
            "IsPaid": is_paid, "BillId": bill_id, "PropertyId": property_id}


def _bills_from(*bps):
    """Mirror _fetch_page's own flattening: Bill[] field list -> flat dict + the
    private bp-level keys the aggregator reads."""
    out = []
    for bp in bps:
        bill = _field_map(bp["Bill"])
        bill["_IsDeliquent"] = bp["IsDeliquent"]
        bill["_IsPaid"] = bp["IsPaid"]
        bill["_BillId"] = bp["BillId"]
        bill["_PropertyId"] = bp["PropertyId"]
        out.append(bill)
    return out


def test_utility_id_is_a_24_hex_mongo_objectid():
    """Verified live 2026-09-29 via POST /crm/api/utilities/list -- Dorchester's
    ONLY bill type, Name="Delinquent Tax". A non-hex value here 500s the API with
    a MongoDB ObjectId.Parse FormatException (also verified live)."""
    assert len(UTILITY_ID) == 24
    assert all(c in "0123456789abcdef" for c in UTILITY_ID)


def test_bill_year_parses_the_embedded_year():
    assert _bill_year("R-2025-00046221") == 2025
    assert _bill_year("R-2024-00046221") == 2024
    assert _bill_year("M-2025-03500777") == 2025
    assert _bill_year("") is None
    assert _bill_year(None) is None
    assert _bill_year("FIL00001129") is None  # no embedded year at all


def test_real_estate_filter_matches_tms_shape_only():
    """Verified live on a 3,000-row sample 2026-09-29: BillNumber's 'R-'/'M-' prefix
    matched AccountNumber's TMS-vs-not shape 100% of the time (2,917/2,917 and
    83/83), so the TMS regex alone is a reliable real-estate filter."""
    assert _is_real_estate("161-00-00-097-000") is True
    assert _is_real_estate("135-00-00-118-777") is True
    assert _is_real_estate("51831763") is False          # vehicle/personal-property account
    assert _is_real_estate("FIL00001129") is False        # business filing id
    assert _is_real_estate("") is False
    assert _is_real_estate(None) is False


def test_multiyear_real_delinquency_aggregates_into_one_listing():
    """APPELT BRIAN DAVID, 5090 Ashley River Rd: two real, currently-unpaid bills
    (2025 + 2024) on the same TMS. This is the "2+ years back" signal the
    motivated-seller engine treats as the strongest distress marker qPayBill/
    Catalis-style sources surface -- it must survive as ONE parcel-level lead
    with both years and the summed balance, not two separate board rows."""
    bills = _bills_from(_bp(APPELT_2025_BILL), _bp(APPELT_2024_BILL))
    listings = _aggregate(bills)
    assert len(listings) == 1
    li = listings[0]
    assert li.parcel_id == "161-00-00-097-000"
    assert li.owner_name == "APPELT BRIAN DAVID"
    assert li.defendant == "APPELT BRIAN DAVID"
    assert li.street_address == "ASHLEY RIVER RD 5090"
    assert li.county == "Dorchester"
    assert li.state == "SC"
    assert li.listing_type == ListingType.TAX_LIEN
    assert li.property_kind == PropertyKind.UNKNOWN

    detail = li.raw["billtrax_dorchester_delinquent_tax"]
    assert detail["years"] == [2024, 2025]
    assert detail["years_delinquent"] == 2
    assert detail["is_two_year_plus"] is True
    assert detail["total_due"] == round(6212.98 + 6082.10, 2)
    assert len(detail["bills"]) == 2

    assert li.raw["tax_owed"]["balance"] == round(6212.98 + 6082.10, 2)
    assert li.raw["tax_owed"]["kind"] == "delinquent_tax"
    assert li.raw["tax_owed"]["year"] == 2025  # most recent year


def test_single_bill_real_estate_lead():
    bills = _bills_from(_bp(LONG_2025_BILL))
    listings = _aggregate(bills)
    assert len(listings) == 1
    li = listings[0]
    assert li.parcel_id == "135-00-00-118-777"
    assert li.owner_name == "LONG CHRISTOPHER F & AMANDA C (J"
    assert li.raw["billtrax_dorchester_delinquent_tax"]["total_due"] == 1797.77
    assert li.raw["billtrax_dorchester_delinquent_tax"]["years"] == [2025]


def test_non_real_estate_bill_is_excluded():
    """The 'M-' personal-property bill must not become a Listing at all -- its
    AccountNumber is an account id, not a parcel."""
    bills = _bills_from(_bp(CAROLINA_PERSONAL_PROPERTY_BILL))
    listings = _aggregate(bills)
    assert listings == []


def test_paid_off_bill_with_zero_balance_is_excluded():
    """A historically-delinquent bill that is now fully paid (TotalDueNow == 0)
    must not surface as a lead just because IsDeliquent is permanently true."""
    bills = _bills_from(_bp(SMITH_PAID_OFF_BILL, is_paid=True))
    listings = _aggregate(bills)
    assert listings == []


def test_mixed_batch_keeps_only_real_nonzero_real_estate():
    bills = _bills_from(
        _bp(APPELT_2025_BILL), _bp(APPELT_2024_BILL),
        _bp(LONG_2025_BILL),
        _bp(CAROLINA_PERSONAL_PROPERTY_BILL, is_paid=True),
        _bp(SMITH_PAID_OFF_BILL, is_paid=True),
    )
    listings = _aggregate(bills)
    parcels = {li.parcel_id for li in listings}
    assert parcels == {"161-00-00-097-000", "135-00-00-118-777"}
