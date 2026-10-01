"""counties_nc.transylvania_delinquent_tax — ViewTaxBill field gaps (audit 2026-10-01).

Per-source extraction audit (docs/HERMES.md sec 8): live-queried the ViewTaxBill
detail page (account 70094770, year 2025 bill 133) and found three published
fields `_parse_detail` never read: Outbuilding Value (a CAMA-spec gap -- HERMES
sec 9 notes "only 32% have real CAMA specs"), Last Transaction Date, and Last
Payment Date (a real distress-severity signal: no last_payment_date at all means
the bill has NEVER been paid, worse than a merely-lapsed payer).

A blank "Last Payment Date :" line is immediately followed by the NEXT section
header ("Taxes/fees"), not an empty string -- the live page genuinely renders no
value there when nothing was ever paid. The naive `_label_value(lines, label)`
helper (return the line right after the label) would therefore read "Taxes/fees"
as if it were a date. This test locks in the date-shape guard that catches that.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.transylvania_delinquent_tax import _parse_detail

# Mirrors the live ViewTaxBill page's flattened text shape 1:1 (account
# 70094770, live-verified 2026-10-01): owner has a transaction date but has
# NEVER made a payment, so "Last Payment Date :" renders with nothing after it.
_DETAIL_HTML_NEVER_PAID = """
<div>Tax Bill Information</div>
<div>Account Info</div>
<div>Account Number :</div><div>70094770</div>
<div>A &amp; T Holdings Trust</div>
<div>73 Smokestone Ct</div>
<div>Las Vegas, NV 89110</div>
<div>Bill Info</div>
<div>Year-Bill Number :</div><div>2025-133</div>
<div>Parcel Number :</div><div>8583012326000</div>
<div>T361A01019 04 MS.03</div>
<div>Escrow :</div>
<div>Legal Description :</div><div>U32 L053 DAWATUA CT</div>
<div>Taxable Values</div>
<div>Building Value :</div><div>0</div>
<div>Outbuilding Value :</div><div>0</div>
<div>Land Value :</div><div>20,000</div>
<div>Parcel Value Total :</div><div>20,000</div>
<div>Balance Info</div>
<div>Current Balance :</div><div>109.72</div>
<div>Last Transaction Date :</div><div>06/09/2026</div>
<div>Last Payment Date :</div>
<div>Taxes/fees</div>
"""

# A second owner who HAS made a payment, with a real outbuilding value — the
# positive case for all three new fields.
_DETAIL_HTML_PAID_WITH_OUTBUILDING = """
<div>Account Info</div>
<div>Account Number :</div><div>99999</div>
<div>Ashe Leesa G</div>
<div>123 Main St</div>
<div>Brevard, NC 28712</div>
<div>Bill Info</div>
<div>Parcel Number :</div><div>12345</div>
<div>Legal Description :</div><div>LOT 5</div>
<div>Taxable Values</div>
<div>Building Value :</div><div>50,000</div>
<div>Outbuilding Value :</div><div>2,760</div>
<div>Land Value :</div><div>10,000</div>
<div>Parcel Value Total :</div><div>62,760</div>
<div>Balance Info</div>
<div>Current Balance :</div><div>50.00</div>
<div>Last Transaction Date :</div><div>08/28/2026</div>
<div>Last Payment Date :</div><div>08/28/2026</div>
"""


def test_blank_last_payment_date_is_none_not_the_next_section_header():
    det = _parse_detail(_DETAIL_HTML_NEVER_PAID)
    assert det["last_transaction_date"] == "06/09/2026"
    assert det["last_payment_date"] is None  # never "Taxes/fees"


def test_outbuilding_value_zero_is_none_like_other_money_fields():
    det = _parse_detail(_DETAIL_HTML_NEVER_PAID)
    assert det["outbuilding_value"] is None  # _f() treats 0 as absent, consistent with building_value


def test_populated_outbuilding_value_and_both_dates_are_captured():
    det = _parse_detail(_DETAIL_HTML_PAID_WITH_OUTBUILDING)
    assert det["outbuilding_value"] == 2760.0
    assert det["last_transaction_date"] == "08/28/2026"
    assert det["last_payment_date"] == "08/28/2026"
