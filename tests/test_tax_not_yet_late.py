"""A row whose ONLY unpaid property-tax bill is not late yet earns no tax credit (2026-10-07).

Owner + attorney rule: ignore a current-year bill that is not late. Mirrors the trivial-balance
rule (TRIVIAL_TAX_BALANCE): the row stays on the board as context with raw['tax_not_yet_late'],
the scorer, lead_signals, fullmer_rank and the amount_owed promotion give it nothing for the tax.
A row with an older unpaid year keeps its credit. Hand-made rows; names and numbers invented.
"""
from __future__ import annotations

from datetime import date, datetime

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper import fullmer_rank as fr
from foreclosure_scraper.enrichment_amount_owed import _tax_owed_promotion, promote_tax_owed_amount_owed
from foreclosure_scraper.enrichment_lead_signals import _facet_signals
from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed, tax_not_yet_late
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

TODAY = date(2026, 10, 7)
_NOW = datetime(2026, 10, 7)


def _row(years, *, source="counties_sc.qpaybill_delinquent_roll", lt=ListingType.TAX_LIEN,
         state="SC", county="Oconee", owed=2400.0, extra=None):
    raw = {"qpaybill_roll": {"balance_owed": owed, "years_unpaid": [str(y) for y in years],
                             "all_unpaid_years": [str(y) for y in years]},
           "owner_mailing": {"mailing": "1 TEST LN ANYTOWN SC", "absentee": True},
           **(extra or {})}
    li = Listing(source=source, source_url="https://x.invalid/1", listing_type=lt,
                 property_kind=PropertyKind.UNKNOWN, state=state, county=county,
                 parcel_id="000-00-00-001", street_address="1 TEST LN", judgment_amount=owed,
                 first_seen=_NOW, last_seen=_NOW, raw=raw)
    enrich_tax_owed([li], today=TODAY)
    promote_tax_owed_amount_owed([li])
    enrich_tax_aging([li], today=TODAY)
    return li


def _names(li):
    return {n for n, _c, _w in ds._signals_for(li, today=TODAY)}


def test_only_a_current_bill_earns_no_tax_credit():
    li = _row([2026])
    assert ds.tax_not_yet_late(li, TODAY)
    assert li.raw["tax_not_yet_late"] is True                       # kept on the board as context
    assert li.raw["tax_aging_surfaced"]["status"] == "not_yet_late"
    names = _names(li)
    assert "tax_lien" not in names and "recorded_debt" not in names
    assert "recorded_debt" not in _facet_signals(li, TODAY)


def test_an_older_unpaid_year_keeps_the_credit():
    li = _row([2025, 2026])
    assert not ds.tax_not_yet_late(li, TODAY)
    assert "tax_not_yet_late" not in li.raw
    names = _names(li)
    assert "tax_lien" in names and "recorded_debt" in names
    assert li.raw["tax_owed"]["years_delinquent"] == 1
    assert li.raw["tax_owed"]["not_yet_late_years"] == [2026]


def test_the_rule_ends_on_the_delinquent_date():
    li = _row([2026])
    assert ds.tax_not_yet_late(li, date(2027, 1, 15))
    assert not ds.tax_not_yet_late(li, date(2027, 1, 16))         # SC: late from January 16
    enrich_tax_aging([li], today=date(2027, 1, 16))
    assert "tax_not_yet_late" not in li.raw


def test_a_standing_tax_sale_roll_row_follows_the_same_rule():
    li = _row([2026], lt=ListingType.TAX_SALE)
    assert "tax_sale" not in _names(li)
    li = _row([2025, 2026], lt=ListingType.TAX_SALE)
    assert "tax_sale" in _names(li)


def test_no_amount_owed_promotion_and_no_fullmer_credit():
    li = _row([2026])
    assert _tax_owed_promotion(li.raw, li) is None
    assert (li.raw.get("amount_owed") or {}).get("source") != "tax_owed"
    # a checkpoint that was promoted before the rule: fullmer still gives no arrears or ripeness
    li.raw["amount_owed"] = {"value": 2400.0, "source": "tax_owed", "is_actual_debt": True}
    li.raw["two_year_delinquent"] = {"is_two_year_plus": True}
    assert fr.tax_arrears(li) == (None, False)
    assert fr.years_delinquent(li) == (None, False)
    s = fr.score(li)
    assert "delinq_ripe" not in s["why"] and "arrears_stated" not in s["why"]


def test_a_judgment_labelled_copy_of_the_balance_is_dropped_too():
    # a non-roll row that merged a roll's balance: tax_owed beside a judgment-labelled copy of it
    li = _row([2026], lt=ListingType.ELDERLY_DISABLED, source="counties_x.some_exemption_list",
              extra={"county_tax_list": {"tax_year": 2026, "total_due": 2400.0}})
    assert li.raw["tax_owed"]["balance"] == 2400.0
    li.raw["amount_owed"] = {"value": 2400.0, "source": "judgment", "is_actual_debt": True}
    assert "recorded_debt" not in _names(li)
    li.raw["amount_owed"] = {"value": 9999.0, "source": "judgment", "is_actual_debt": True}
    assert "recorded_debt" in _names(li)                            # a different, real debt stays


def test_evidence_is_required_a_bare_tax_owed_year_is_not_enough():
    """Only tax_owed names the year (its source block is gone): not established, credit kept."""
    raw = {"tax_owed": {"balance": 1700.0, "kind": "delinquent_tax", "year": 2026,
                        "source": "counties_nc.some_list", "basis": "own_record"}}
    assert not tax_not_yet_late(raw, "NC", "Buncombe", "counties_nc.some_list", TODAY)
    # a sale list or an advertisement naming one year is not evidence either (often the sale's year)
    raw["some_tax_sale_list"] = {"tax_year": 2026, "opening_bid": 1700.0}
    assert not tax_not_yet_late(raw, "NC", "Buncombe", "counties_nc.some_list", TODAY)
    # a live bill roll naming the year is
    raw["catalis_roll"] = {"year": 2026, "total_due": 1700.0}
    assert tax_not_yet_late(raw, "NC", "Buncombe", "counties_nc.some_list", TODAY)


def test_a_past_due_source_or_merge_is_never_only_a_current_bill():
    raw = {"tax_owed": {"balance": 900.0, "kind": "delinquent_tax", "year": 2026,
                        "source": "counties_nc.elderly_list"},
           "elderly_tax": {"tax_year": 2026},
           "also_seen_in": [{"source": "counties.multi_year_delinquent_tax", "url": "u"}]}
    assert not tax_not_yet_late(raw, "NC", "Buncombe", "counties_nc.elderly_list", TODAY)


def test_ptscloud_tax_year_label_is_not_the_levy_year():
    """PTS Cloud labels some 2025-levy bills TAX_YEAR 2026 (bill -2026-2025-, due 09/01/2025)."""
    pts = {"principal_tax_due": 1800.0, "tax_year": "2026",
           "bill_number": "0000000001-2026-2025-0070-00"}
    raw = {"nc_ptscloud_delinquent_tax": dict(pts)}
    assert not tax_not_yet_late(raw, "NC", "Pitt", "counties_nc.nc_ptscloud_delinquent_tax", TODAY)
    raw = {"nc_ptscloud_delinquent_tax": {**pts, "bill_number": "0000000001-2026-2026-0000-00",
                                          "bill_due_date": "09/01/2026"}}
    assert tax_not_yet_late(raw, "NC", "Pitt", "counties_nc.nc_ptscloud_delinquent_tax", TODAY)
    raw["nc_ptscloud_delinquent_tax"]["interest_due"] = 31.5      # interest = a bill already late
    assert not tax_not_yet_late(raw, "NC", "Pitt", "counties_nc.nc_ptscloud_delinquent_tax", TODAY)


def test_other_liens_are_not_property_tax_bills():
    li = _row([2026], source="counties_sc.sc_dew_lien_registry")
    assert not ds.tax_not_yet_late(li, TODAY)
