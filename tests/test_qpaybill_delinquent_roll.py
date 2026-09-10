"""The SC qPayBill delinquent roll: grid parsing, aggregation, and the enumeration
invariants that keep an incomplete sweep from looking like a complete one.

WHY THESE TESTS EXIST, in one line each:

  * parse_grid splits owner from situs address on the ``<br/>`` the portal emits.
    Everything downstream -- the mail spine, dedupe, the resolver -- depends on not
    getting "ABNER EUGENE JR HEIRS OF 1951 DAVIS BRIDGE RD" as one blob.
  * A parcel appears once PER UNPAID YEAR, so aggregation is what turns three rows
    into one lead carrying is_two_year_plus. Emitting the rows would put the same
    house on the board three times and bury the strongest distress signal in it.
  * The pager is LOSSY AND SILENT about it: measured 2026-09-10 on Barnwell it
    returned 804 of 930 parcels with errors=0 and no stall reported. The enumeration
    must therefore never conclude completeness from a pager alone, and _next_chars
    must always include the unread alphabetical tail.
  * Orangeburg's Identification-No. is an ACCOUNT id, not a parcel. Claiming it as
    parcel_id would feed dedupe (which keys parcel:{state}:{county}:{p}) ids that are
    not parcels, and this repo has already lost 122 distinct properties to one fused
    bogus parcel key.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import (
    ACCOUNT_ID_ONLY,
    PAGE_CAP,
    QPAYBILL_SUBS,
    _ALPHABET,
    _all_match,
    _next_chars,
    _to_listings,
    parse_grid,
)

#: A verbatim row pair from Barnwell, 2026-09-10.
REAL_ROWS = """
<table><tr><th>Notice No.</th><th>Name / Property Address</th><th>Year</th>
<th>Description</th><th>Identification No.</th><th>Type</th><th>Status</th>
<th>Payment Date</th><th>Amount</th><th>&nbsp;</th><th>&nbsp;</th></tr>
<tr><td>000207255</td><td>ABNER EUGENE JR HEIRS OF<br/>1951 DAVIS BRIDGE RD</td>
<td>2025</td><td>PROP OF HORACE AB...</td><td>045-00-00-021.03</td>
<td>RealEstate</td><td>Unpaid</td><td></td><td>$130.55</td>
<td><a href="TaxesDetailsType4.aspx?receiptNo=000207255">View</a></td>
<td><input type="submit" value="Add to Cart" /></td></tr>
<tr><td>000213255</td><td>ABNEY BARBARA JENE OR<br/>210 JOHN ST</td>
<td>2025</td><td>PROP OF NANCY S J...</td><td>048-02-03-007.01</td>
<td>RealEstate</td><td>Unpaid</td><td></td><td>$132.07</td>
<td><a href="x">View</a></td><td></td></tr></table>
"""


def test_owner_and_situs_address_split_on_the_br_tag():
    rows = parse_grid(REAL_ROWS)
    assert len(rows) == 2
    assert rows[0]["owner"] == "ABNER EUGENE JR HEIRS OF"
    assert rows[0]["address"] == "1951 DAVIS BRIDGE RD"
    assert rows[0]["ident"] == "045-00-00-021.03"
    assert rows[0]["amount"] == 130.55
    assert rows[0]["year"] == "2025"
    assert rows[0]["status"] == "Unpaid"
    assert rows[0]["notice_no"] == "000207255"


def test_the_heirs_signal_survives_parsing():
    """"HEIRS OF" in the owner string is the heirship signal the downstream
    owner_name_signal enricher grades. Losing it to a bad split loses the lead type
    this engine most wants."""
    rows = parse_grid(REAL_ROWS)
    assert "HEIRS OF" in rows[0]["owner"]


def test_a_row_with_no_amount_is_not_a_lead():
    html = REAL_ROWS.replace("$130.55", "")
    assert len(parse_grid(html)) == 1


@pytest.mark.parametrize("bad", ["$0.00", "$99,999.00", "$1,000,000.00"])
def test_placeholder_amounts_are_rejected(bad):
    """qPayBill emits 99999.00 as a placeholder; a zero balance is not delinquent."""
    html = REAL_ROWS.replace("$130.55", bad)
    rows = parse_grid(html)
    assert all(r["ident"] != "045-00-00-021.03" for r in rows)


def test_a_paid_row_is_not_a_lead():
    html = REAL_ROWS.replace("<td>Unpaid</td><td></td><td>$130.55</td>",
                             "<td>Paid</td><td>01/02/2026</td><td>$130.55</td>")
    rows = parse_grid(html)
    assert all(r["ident"] != "045-00-00-021.03" for r in rows)


def test_a_short_row_is_ignored():
    assert parse_grid("<table><tr><td>a</td><td>b</td></tr></table>") == []


# ---------------------------------------------------------------------------
# Aggregation: one Listing per parcel, years rolled up
# ---------------------------------------------------------------------------

def _row(ident, year, amount, owner="SMITH JOHN", addr="1 MAIN ST"):
    return {"notice_no": f"N{year}", "owner": owner, "address": addr, "year": year,
            "description": "PROP OF X", "ident": ident, "status": "Unpaid",
            "amount": amount}


def test_three_unpaid_years_become_one_lead_flagged_two_year_plus():
    out = _to_listings("Barnwell", [_row("045-00-00-021.03", y, 100.0)
                                    for y in ("2023", "2024", "2025")])
    assert len(out) == 1
    raw = out[0].raw["qpaybill_roll"]
    assert raw["balance_owed"] == 300.0
    assert raw["years_unpaid"] == ["2023", "2024", "2025"]
    assert raw["years_delinquent"] == 3
    assert raw["is_two_year_plus"] is True
    assert raw["rows"] == 3


def test_a_single_year_is_not_two_year_plus():
    out = _to_listings("Barnwell", [_row("045-00-00-021.03", "2025", 130.55)])
    assert out[0].raw["qpaybill_roll"]["is_two_year_plus"] is False


def test_distinct_parcels_stay_distinct():
    out = _to_listings("Barnwell", [_row("045-00-00-021.03", "2025", 10.0),
                                    _row("048-02-03-007.01", "2025", 20.0)])
    assert len(out) == 2


def test_the_owner_and_address_reach_the_listing_fields():
    out = _to_listings("Barnwell", [_row("045-00-00-021.03", "2025", 10.0,
                                         owner="ABNER EUGENE JR HEIRS OF",
                                         addr="1951 DAVIS BRIDGE RD")])
    li = out[0]
    assert li.owner_name == "ABNER EUGENE JR HEIRS OF"
    assert li.defendant == "ABNER EUGENE JR HEIRS OF"
    assert li.street_address == "1951 DAVIS BRIDGE RD"
    assert li.state == "SC" and li.county == "Barnwell"


def test_an_account_id_county_makes_no_parcel_claim():
    """Orangeburg's Identification-No. is 2082143 -- an account, not a parcel.
    dedupe keys on parcel:{state}:{county}:{p}, and this repo has already collapsed
    122 distinct properties into one row by trusting a non-parcel as a parcel key."""
    assert "Orangeburg" in ACCOUNT_ID_ONLY
    out = _to_listings("Orangeburg", [_row("2082143", "2025", 10.0)])
    assert out[0].parcel_id is None
    raw = out[0].raw["qpaybill_roll"]
    assert raw["identification_no"] == "2082143"
    assert raw["is_account_id_not_parcel"] is True


def test_a_parcel_county_does_claim_its_parcel():
    out = _to_listings("Barnwell", [_row("045-00-00-021.03", "2025", 10.0)])
    assert out[0].parcel_id == "045-00-00-021.03"
    assert out[0].raw["qpaybill_roll"]["is_account_id_not_parcel"] is False


# ---------------------------------------------------------------------------
# Enumeration invariants
# ---------------------------------------------------------------------------

def test_next_chars_always_includes_the_unread_tail():
    """THE invariant that keeps the sweep honest. Rows come back alphabetically and
    the page stops at 25, so everything after the LAST name read is unread, not
    absent. Deepening only into observed characters would silently skip it."""
    rows = [{"owner": "ABNER X"}, {"owner": "ABNEY Y"}, {"owner": "ADKINS Z"}]
    chars, last = _next_chars(rows, "A")
    assert chars == {"B", "D"}
    assert last == "D", "the last character seen is what bounds the unread tail"


def test_next_chars_ignores_names_that_end_at_the_prefix():
    chars, last = _next_chars([{"owner": "SMITH"}], "SMITH")
    assert chars == set() and last is None


def test_all_match_rejects_a_drifted_page():
    """A page whose owners do not start with the prefix means the paging session is
    answering with another letter's search. Accepting it files those parcels under
    the wrong prefix; measured, this is what a shared cookie jar produces."""
    assert _all_match([{"owner": "ABNEY B"}], "AB") is True
    assert _all_match([{"owner": "MOORE C"}], "AB") is False
    assert _all_match([], "AB") is True          # nothing to contradict


def test_the_alphabet_covers_entity_names_starting_with_a_digit():
    """Rolls carry entities like "2ND CHANCE LLC"; a letters-only alphabet would
    never search for them."""
    assert set("0123456789") <= set(_ALPHABET)
    assert len(_ALPHABET) == 36


def test_page_cap_matches_the_portals_observed_page_size():
    assert PAGE_CAP == 25


def test_every_county_has_a_subdomain_and_the_five_known_ones_are_kept():
    """The five counties enrichment_qpaybill_tax already used must not be dropped
    while adding the fourteen new ones."""
    assert len(QPAYBILL_SUBS) == 19
    for known in ("Spartanburg", "Oconee", "Laurens", "Union", "Cherokee"):
        assert known in QPAYBILL_SUBS
    assert all(v and "." not in v for v in QPAYBILL_SUBS.values())


def test_the_enricher_and_the_source_agree_on_the_five_shared_counties():
    from foreclosure_scraper.enrichment_qpaybill_tax import QPAYBILL_COUNTIES
    for (state, county), sub in QPAYBILL_COUNTIES.items():
        assert state == "SC"
        assert QPAYBILL_SUBS.get(county) == sub, (
            f"{county}: enricher uses {sub!r}, source uses "
            f"{QPAYBILL_SUBS.get(county)!r} -- one of them is querying the wrong host"
        )


# ---------------------------------------------------------------------------
# THE DETAIL PASS, and the URL-join bug that made an earlier version of this
# module declare it a dead end in a committed docstring.
#
# The grid link is href="TaxesDetailsType4.aspx?..." -- RELATIVE TO /Taxes/,
# because the search page is /Taxes/TaxesDefaultType4.aspx. Joined to the host
# root it becomes /TaxesDetailsType4.aspx, which the server answers with a
# 5,713-byte page whose body is the single word ERROR. That reads exactly like a
# refusal, and was recorded as one. A whole data layer for 19 counties -- the
# county appraised value and the owner-occupancy ratio -- was written off by a
# wrong URL join.
# ---------------------------------------------------------------------------

from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import (  # noqa: E402
    _acres, _detail_url, fetch_details, parse_detail,
)


@pytest.mark.parametrize("href", [
    "TaxesDetailsType4.aspx?receiptNo=000207255&recID=583993116",
    "/TaxesDetailsType4.aspx?receiptNo=000207255&recID=583993116",
    "Taxes/TaxesDetailsType4.aspx?receiptNo=000207255&recID=583993116",
    "/Taxes/TaxesDetailsType4.aspx?receiptNo=000207255&recID=583993116",
])
def test_the_detail_link_always_resolves_under_slash_taxes(href):
    """Every shape of the href must land on /Taxes/, never the host root."""
    got = _detail_url("barnwelltreasurer", href)
    assert got == ("https://barnwelltreasurer.qpaybill.com/Taxes/"
                   "TaxesDetailsType4.aspx?receiptNo=000207255&recID=583993116")
    assert "/Taxes/Taxes/" not in got
    assert got.count("/Taxes/") == 1


#: Trimmed verbatim from a live Barnwell detail page, 2026-09-10.
REAL_DETAIL = """
<div>Notice #: 000207255</div><div>Status: Unpaid</div>
<div>Issue Date: 12/08/25</div><div>Balance Due:$130.55</div>
<div>Name:</div><div>ABNER EUGENE JR HEIRS OF</div>
<div>Tax Year:</div><div>2025</div>
<div>Total Appraisal:</div><div>690</div>
<div>Total Assessed:</div><div>40</div>
<div>Assessment Ratio:</div><div>Land Appraisal:</div><div>Building Appraisal:</div>
<div>6%</div><div>0</div><div>690</div>
<div>Record Type:</div><div>Real Estate</div>
<div>Map Number:</div><div>045-00-00-021.03</div>
<div>Acres:</div><div>.00</div><div>Buildings:</div><div>1</div>
<div>Description:</div><div>PROP OF HORACE ABN AD#26-00002 64 10X51 MAGNOLIA S-6-13</div>
<div>County Tax:</div><div>$19.12</div>
<div>Residential Exemption:</div><div>$0.00</div>
<div>Homestead Exemption:</div><div>$0.00</div>
<div>Penalty:</div><div>$2.68</div><div>Cost:</div><div>$110.00</div>
"""


def test_the_county_appraised_value_is_parsed():
    """THE field. The coverage matrix has VALUE at 1% in Oconee and 3% in Union;
    this is the county's own 100%-basis number, free, on every delinquent parcel."""
    d = parse_detail(REAL_DETAIL)
    assert d["appraised_value"] == 690.0
    assert d["assessed_value"] == 40.0


def test_the_assessment_ratio_is_an_owner_occupancy_flag():
    """SC law: 4% is the owner-occupied legal-residence ratio, 6% is everything
    else. So a 6% parcel is authoritatively NOT the owner's residence -- a free
    absentee-owner signal, and `absentee_owner` was measured at 0 rows on the
    live board."""
    d = parse_detail(REAL_DETAIL)
    assert d["assessment_ratio_pct"] == 6
    assert d["owner_occupied"] is False
    d4 = parse_detail(REAL_DETAIL.replace("<div>6%</div>", "<div>4%</div>"))
    assert d4["assessment_ratio_pct"] == 4
    assert d4["owner_occupied"] is True


def test_an_unknown_ratio_is_not_guessed_as_absentee():
    """A missing or odd ratio must be None, never False. False means 'the county
    says this is not their residence', and inventing that would put a homeowner
    on an absentee list."""
    d = parse_detail(REAL_DETAIL.replace("<div>6%</div>", "<div>x</div>"))
    assert d.get("owner_occupied") is None


def test_the_full_description_survives_where_the_grid_truncates_it():
    """The grid shows 'PROP OF HORACE AB...'; the detail page has all of it."""
    d = parse_detail(REAL_DETAIL)
    assert d["legal_description"] == "PROP OF HORACE ABN AD#26-00002 64 10X51 MAGNOLIA S-6-13"
    assert "..." not in d["legal_description"]


def test_acres_and_buildings_are_parsed():
    d = parse_detail(REAL_DETAIL)
    assert d["acres"] == ".00"
    assert d["buildings"] == "1"


def test_the_error_page_yields_nothing_rather_than_junk():
    """The wrong-URL page. It must parse to {} so a bad join can never look like
    a record with empty fields."""
    assert parse_detail("<html><body>ERROR</body></html>") == {}
    assert parse_detail("") == {}


@pytest.mark.parametrize("raw,want", [(".00", None), ("0", None), (".83", 0.83),
                                      ("48.40", 48.4), ("", None), (None, None), ("abc", None)])
def test_zero_acres_means_unrecorded_not_zero(raw, want):
    """'.00' is the county recording no acreage. Storing 0.0 would say the parcel
    has no land, which is false and would fail any acreage filter."""
    assert _acres(raw) == want


def test_the_grid_row_carries_its_own_detail_link():
    """The link is kept ON the row so the detail pass never reconstructs a URL --
    reconstructing it is precisely how it got joined to the wrong base."""
    rows = parse_grid(REAL_ROWS)
    assert rows[0]["detail_href"] == "TaxesDetailsType4.aspx?receiptNo=000207255"


def test_detail_fields_reach_the_listing():
    r = _row("045-00-00-021.03", "2025", 130.55)
    r["detail"] = {"appraised_value": 690.0, "acres": ".83", "owner_occupied": False,
                   "legal_description": "PROP OF HORACE ABN", "assessment_ratio_pct": 6}
    li = _to_listings("Barnwell", [r])[0]
    assert li.tax_value == 690.0
    assert li.acreage == 0.83
    assert li.legal_description == "PROP OF HORACE ABN"
    assert li.raw["qpaybill_roll"]["detail"]["owner_occupied"] is False


def test_no_detail_leaves_the_listing_clean():
    li = _to_listings("Barnwell", [_row("045-00-00-021.03", "2025", 130.55)])[0]
    assert li.tax_value is None and li.acreage is None
    assert "detail" not in li.raw["qpaybill_roll"]
