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
    raw = {"qpaybill_roll": {"identification_no": "000-00-00-001", "balance_owed": owed,
                             "years_unpaid": [str(y) for y in years],
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
              extra={"county_tax_list": {"tax_year": 2026, "total_due": 2400.0},
                     # merged in by dedupe, which records the source it came from
                     "also_seen_in": [{"source": "counties_x.county_tax_list", "url": "https://x.invalid/2"}]})
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


# ---- raw['tax_big_old']: $7,000+ of property tax already late, 2+ levy years late ----------------

def _big(years, owed, per_year=None, **kw):
    # parcel_key: the multi-year engine keys its block by the row's parcel (tax_binding: a block
    # on a row of another source binds only by that parcel)
    extra = {"multi_year_delinquent_tax": {"years": years, "total_due": owed, "parcel_key": "0000000001",
                                           "per_year": per_year or {}}}
    return _row([], extra=extra, owed=owed, **kw)


def test_big_old_needs_two_late_years_and_the_late_part_over_the_line():
    from foreclosure_scraper.enrichment_tax_owed import BIG_TAX_BALANCE
    assert BIG_TAX_BALANCE == 7000.0
    assert _big([2023, 2024], 7000.0).raw.get("tax_big_old") is True
    assert "tax_big_old" not in _big([2023, 2024], 6999.99).raw
    assert "tax_big_old" not in _big([2025], 50000.0).raw                  # one late year
    # unpaid 2024 + 2025 + the current 2026 bill: 2 late years, but only $6,000 of it is late
    li = _big([2024, 2025, 2026], 9000.0, {"2024": 3000.0, "2025": 3000.0, "2026": 3000.0})
    assert li.raw["tax_owed"]["years_delinquent"] == 2
    assert "tax_big_old" not in li.raw
    li = _big([2024, 2025, 2026], 12000.0, {"2024": 4000.0, "2025": 4000.0, "2026": 4000.0})
    assert li.raw["tax_big_old"] is True


def test_big_old_is_cleared_and_never_on_another_lien():
    li = _big([2023, 2024], 8000.0)
    assert li.raw["tax_big_old"] is True
    li.raw["multi_year_delinquent_tax"]["years"] = [2024]
    enrich_tax_owed([li], today=TODAY)
    enrich_tax_aging([li], today=TODAY)
    assert "tax_big_old" not in li.raw
    assert "tax_big_old" not in _big([2023, 2024], 8000.0,
                                     source="counties_sc.sc_dew_lien_registry").raw


def test_big_old_ships_to_phones_and_the_dashboard_filter_reads_it():
    from pathlib import Path
    from foreclosure_scraper.web_artifact import RAW_KEEP, _SLIM_RAW_SCALARS
    assert RAW_KEEP.get("tax_big_old") == "*" and RAW_KEEP.get("tax_not_yet_late") == "*"
    assert "tax_big_old" in _SLIM_RAW_SCALARS
    root = Path(__file__).resolve().parents[1] / "docs"
    assert 'contact === "tax_big_old" && !r.tax_big_old' in (root / "dashboard.js").read_text()
    assert '<option value="tax_big_old">' in (root / "index.html").read_text()


# ---- BIG_OLD_TAX_WARM_FLOOR: big + old + a mailing address or phone on file -> at least WARM ------

def _floor_row(years=(2023, 2024), owed=9000.0, *, mail=False, phone=False, years_list=None):
    li = _big(list(years_list or years), owed)
    li.raw.pop("owner_mailing", None)
    li.raw["owner_mailing"] = {"mailing": "1 TEST LN ANYTOWN SC", "absentee": False} if mail else {}
    if phone:
        li.raw["skip_trace"] = {"phone_numbers": ["555-0100"]}
    return li


def _tier(li):
    ds.score_board([li], previous_path=None, today=TODAY)
    return li.raw["distress_stack"]


def test_floor_with_a_mailing_address():
    st = _tier(_floor_row(mail=True))
    assert ds.BIG_OLD_TAX_WARM_FLOOR == "WARM"
    assert st["tier"] == "WARM" and st["tier_floor"] == "tax_big_old"
    assert st["tax_big_old"] == "contact"


def test_floor_with_a_phone():
    st = _tier(_floor_row(phone=True))
    assert st["tier"] == "WARM" and st["tier_floor"] == "tax_big_old"


def test_no_floor_without_contact():
    st = _tier(_floor_row())
    assert st["tier"] == "COLD" and "tier_floor" not in st
    assert st["tax_big_old"] == "no_contact"


def test_floor_never_demotes_and_never_opens_hot():
    # a tier already WARM or HOT is left as it is and carries no floor marker
    for tier in ("WARM", "HOT"):
        d = {"tax_big_old": "contact"}
        assert ds._tier_floor(d, tier) == tier and "tier_floor" not in d
    # the floor gives WARM, not HOT, and an ended event / senior lien / scope cap holds COLD
    assert ds._tier_floor({"tax_big_old": "contact"}, "COLD") == "WARM"
    for cap in ({"stale_reason": "sale passed"}, {"surviving_senior_debt_risk": True},
                {"scope_capped": "flip_outside_footprint"}):
        assert ds._tier_floor({"tax_big_old": "contact", **cap}, "COLD") == "COLD"
    # a row the base rule already makes WARM keeps WARM without the marker
    li = _floor_row(mail=True)
    li.raw["owner_mailing"]["absentee"] = True      # the absentee route to WARM
    li.raw["code_enforcement"] = {"status": "open"}
    st = _tier(li)
    assert st["tier"] in ("WARM", "HOT")


def test_not_yet_late_or_small_rows_never_qualify():
    st = _tier(_floor_row(years_list=[2026], owed=9000.0, mail=True))   # only the current bill
    assert st["tier"] == "COLD" and "tax_big_old" not in st
    st = _tier(_floor_row(years_list=[2025, 2026], owed=50000.0, mail=True))   # one late year
    assert "tax_big_old" not in st
    st = _tier(_floor_row(owed=6999.0, mail=True))
    assert st["tier"] == "COLD" and "tax_big_old" not in st


def test_a_refuted_tax_verdict_takes_the_floor_away(monkeypatch):
    li = _floor_row(mail=True)
    monkeypatch.setattr(ds, "suppressed_scorer_signals", lambda raw, today=None: {"recorded_debt:tax"})
    st = _tier(li)
    assert st["tier"] == "COLD" and "tax_big_old" not in st


def test_retraction_keeps_the_floor():
    li = _floor_row(mail=True)
    st = _tier(li)
    st["equity_band"] = "high"
    assert ds.retract_equity_rank(li)
    assert li.raw["distress_stack"]["tier"] == "WARM"
    assert li.raw["distress_stack"]["tier_floor"] == "tax_big_old"
