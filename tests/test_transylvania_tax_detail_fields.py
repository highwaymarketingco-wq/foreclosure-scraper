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


# --------------------------------------------------------------------------- 2026-10-03 follow-up audit
#
# Live-sampled 30 current unpaid bills (2026-10-03): Net Taxable Valuation is
# populated on every one (30/30), Personal Value on 12/30 (often a mobile home
# riding on an otherwise-real-estate account), and Exemption on 1/30 -- a real
# $116,285 homestead/elderly exemption on account 70527110. A probed companion
# "TaxDistrictsData" per-bill tax/fee breakdown table turned out to be dead on
# the vendor's own site (its own AJAX call 404s: "the controller ... was not
# found"), so that one was investigated and correctly NOT pursued.

_DETAIL_HTML_WITH_EXEMPTION = """
<div>Account Info</div>
<div>Account Number :</div><div>70527110</div>
<div>Baker Michael D &amp; Baker Elizabeth D</div>
<div>44 Blantyre Church Rd</div>
<div>Brevard, NC 28712</div>
<div>Bill Info</div>
<div>Parcel Number :</div><div>9518755741000</div>
<div>Legal Description :</div><div>LOT 9</div>
<div>Taxable Values</div>
<div>Building Value :</div><div>120,000</div>
<div>Land Value :</div><div>30,000</div>
<div>Parcel Value Total :</div><div>150,000</div>
<div>Deferred Value :</div><div>5,000</div>
<div>Taxable Value :</div><div>145,000</div>
<div>Balance Info</div>
<div>Current Balance :</div><div>14.09</div>
<div>Personal Value :</div><div>875</div>
<div>Total Valuation :</div><div>145,875</div>
<div>Exemption :</div><div>116,285</div>
<div>Net Taxable Valuation :</div><div>29,590</div>
"""


def test_exemption_deferred_and_personal_value_are_captured():
    det = _parse_detail(_DETAIL_HTML_WITH_EXEMPTION)
    assert det["exemption"] == 116285.0
    assert det["deferred_value"] == 5000.0
    assert det["personal_value"] == 875.0
    assert det["net_taxable_valuation"] == 29590.0


def test_zero_exemption_is_none_like_other_money_fields():
    det = _parse_detail(_DETAIL_HTML_PAID_WITH_OUTBUILDING)
    assert det["exemption"] is None
    assert det["deferred_value"] is None
    assert det["personal_value"] is None
