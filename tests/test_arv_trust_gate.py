"""The ARV trust gate — derived figures may never outrank the ARV they came from.

The defect this file exists for, measured on the live 38,500-lead board: the
engine could withhold a lead's LETTER grade for a failed ARV sanity check and,
on the very same row, publish "GREAT · ROI 192.6% · max bid $1,271,200".
3646 Summer Rd, Henderson NC — an ARV 7.4x the county's own appraisal. 9,111
leads kept a flagged ARV and all 9,111 published a max bid off it; 206 published
a deal verdict, 58 of them GREAT.

The rule under test, in one sentence:
    ANY calc arv_flag removes the VERDICT.
    A CONTRADICTING arv_flag also removes every DOLLAR derived from the ARV.

The last two tests are the ones that matter most: a clean lead must come through
completely untouched, and an unrecognised future flag must fail SAFE.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.enrichment_board_qa import enrich_board_qa
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc as vcalc
from foreclosure_scraper.valuation import grading


MONEY = grading.ARV_DERIVED_MONEY_FIELDS
VERDICT = grading.ARV_VERDICT_FIELDS


def _li(**kw) -> Listing:
    base = dict(source="counties_sc.test", source_url="http://x",
                listing_type=ListingType.FORECLOSURE_SALE, state="SC",
                county="Spartanburg", first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(), raw={})
    base.update(kw)
    return Listing(**base)


def _calc(flags, **kw) -> vcalc.Calc:
    """A Calc carrying a full set of derived figures plus the given arv_flags."""
    base = dict(
        arv_expected=300000.0, arv_low=270000.0, arv_high=330000.0,
        arv_confidence="MEDIUM", arv_flags=list(flags) or None,
        max_bid_70=180000.0, wholesale_mao=170000.0, wholesale_spread=80000.0,
        total_investment=190000.0, estimated_profit=110000.0, roi_pct=57.9,
        cash_on_cash_pct=90.0, bid_to_arv_pct=33.3, haircut_needed=None,
        deal_status="GREAT", deal_message="List $100,000 is below max viable bid.",
        hold_status="OK", cap_rate_pct=8.2, rehab_expected=30000.0, notes=[],
    )
    base.update(kw)
    return vcalc.Calc(**base)


# ---------------------------------------------------------------------------
# 1. CONTRADICTED — the money goes with the verdict
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", sorted(grading.ARV_FLAGS_CONTRADICTED))
def test_contradicted_flag_withholds_every_derived_figure(flag):
    c = _calc([flag])
    assert grading.apply_arv_trust_gate(c) == "contradicted"
    for f in MONEY + VERDICT:
        assert getattr(c, f) is None, f"{flag} left {f} published"
    # The ARV itself STAYS. Withholding it too would hide the disagreement the
    # operator needs in order to check the parcel.
    assert c.arv_expected == 300000.0
    assert c.arv_low and c.arv_high
    # ...and the buy-and-hold lens is untouched: it never reads arv_expected.
    assert c.hold_status == "OK" and c.cap_rate_pct == 8.2
    assert any("No max bid" in n for n in c.notes), "no reason was recorded"
    assert flag in " ".join(c.notes), "the note must name the actual flag"


def test_the_reported_case_3646_summer_rd_loses_its_verdict_and_its_bid():
    """arv_above_anchor: ARV 7.4x the county appraisal, published GREAT with a
    $1,271,200 max bid against a $230,200 appraisal."""
    c = _calc(["arv_above_anchor"], arv_expected=1_694_900.0,
              max_bid_70=1_271_200.0, roi_pct=192.6, deal_status="GREAT")
    grading.apply_arv_trust_gate(c)
    assert c.deal_status is None and c.max_bid_70 is None and c.roi_pct is None
    assert c.arv_expected == 1_694_900.0


# ---------------------------------------------------------------------------
# 2. WEAK EVIDENCE — the verdict goes, the dollars stay
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", sorted(grading.ARV_FLAGS_WEAK_EVIDENCE))
def test_weak_flag_withholds_only_the_verdict(flag):
    c = _calc([flag])
    assert grading.apply_arv_trust_gate(c) == "weak"
    for f in VERDICT:
        assert getattr(c, f) is None, f"{flag} left {f} published"
    for f in MONEY:
        assert getattr(c, f) is not None, f"{flag} wrongly blanked {f}"
    assert any("No deal verdict" in n for n in c.notes)


def test_contradicted_wins_when_both_kinds_of_flag_are_present():
    c = _calc(["geo_imprecise_comps", "comp_kind_mismatch"])
    assert grading.apply_arv_trust_gate(c) == "contradicted"
    assert c.max_bid_70 is None


# ---------------------------------------------------------------------------
# 3. STRUCTURAL INVARIANTS
# ---------------------------------------------------------------------------

def test_withheld_arv_publishes_nothing_derived():
    """calc already gets this right — all 531 arv_withheld board rows are clean,
    because every downstream block is written `if out.arv_expected`. The gate
    enforces it anyway: that is an implicit coupling inside a file this module
    does not own, and a confident bid beside an ARV the engine refused to print
    is the worst version of this bug."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, living_sqft=1400.0)
    c = _calc(["ppsf_ceiling"], arv_expected=None, arv_low=None, arv_high=None,
              arv_withheld=780300.0)          # ...but the derived figures LINGER
    assert grading.arv_trust(c.arv_flags, c.arv_expected, c.arv_withheld) == "withheld"
    grading.grade(li, c)
    for f in MONEY + VERDICT:
        assert getattr(c, f) is None, f"{f} survived beside a withheld ARV"


def test_gate_is_idempotent():
    c = _calc(["bid_proxy_arv"])
    grading.apply_arv_trust_gate(c)
    notes_after_one = list(c.notes)
    grading.apply_arv_trust_gate(c)
    assert c.notes == notes_after_one, "a second pass duplicated the note"


def test_grade_applies_the_gate_because_it_is_the_shared_seam():
    """All 13 producers of raw['calc'] run compute -> grade -> to_dict. The gate
    hangs off grade() so it reaches every one of them; calc.to_dict then drops
    the Nones, so the board simply has no such keys."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, opening_bid=100000.0)
    c = _calc(["comp_kind_mismatch"])
    grading.grade(li, c)
    assert c.max_bid_70 is None
    d = vcalc.to_dict(c)
    for f in MONEY + VERDICT:
        assert f not in d, f"{f} survived into the serialized board block"


def test_financial_subgrade_is_neutral_on_a_contradicted_arv():
    """The overall letter was already withheld on these, but the per-dimension
    `financial` letter still published — and it is 100% a function of bid/ARV."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, opening_bid=60000.0)
    g = grading.grade(li, _calc(["floor_raise_large"]))
    assert g.overall is None
    assert g.financial_score == 50, "a contradicted ARV must not score financials"


# ---------------------------------------------------------------------------
# 4. THE DICT MIRROR (carried-over boards / writers that skip grade())
# ---------------------------------------------------------------------------

def test_gate_calc_dict_matches_the_object_gate():
    d = vcalc.to_dict(_calc(["bid_proxy_arv"]))
    assert grading.gate_calc_dict(d) == "contradicted"
    for f in MONEY + VERDICT:
        assert f not in d
    assert d["arv_expected"] == 300000.0


def test_data_quality_enforces_and_captions():
    li = _li(street_address="1 Test St", property_kind=PropertyKind.SINGLE_FAMILY,
             living_sqft=1400.0, raw={"calc": vcalc.to_dict(_calc(["comp_kind_mismatch"]))})
    enrich_data_quality([li])
    dq = li.raw["data_quality"]
    assert "arv_unreliable" in dq["flags"]
    assert "arv_bid_and_roi_withheld" in dq["flags"]
    assert "comp_kind_mismatch" in dq["summary"], "the caveat must name the reason"
    assert "max_bid_70" not in li.raw["calc"], "the dict gate did not enforce"

    li2 = _li(street_address="2 Test St", property_kind=PropertyKind.SINGLE_FAMILY,
              living_sqft=1400.0,
              raw={"calc": vcalc.to_dict(_calc(["anchor_not_independent"]))})
    enrich_data_quality([li2])
    dq2 = li2.raw["data_quality"]
    assert "arv_no_independent_check" in dq2["flags"]
    # The quiet tier must NOT borrow the loud tier's names — it covers ~half the
    # board and would wallpaper over the 7.5% that means "do not bid".
    assert "arv_unreliable" not in dq2["flags"]
    assert li2.raw["calc"]["max_bid_70"] == 180000.0
    assert "deal_status" not in li2.raw["calc"]


def test_board_qa_tripwires_read_zero_after_the_gate_and_fire_without_it():
    gated = _li(street_address="3 Test St", parcel_id="P3",
                raw={"calc": vcalc.to_dict(_calc(["arv_above_anchor"]))})
    grading.gate_calc_dict(gated.raw["calc"])
    ungated = _li(street_address="4 Test St", parcel_id="P4",
                  raw={"calc": vcalc.to_dict(_calc(["arv_above_anchor"]))})

    enrich_board_qa([gated, ungated])
    assert not set(gated.raw.get("qa_flags") or []) & {
        "verdict_on_flagged_arv", "bid_on_contradicted_arv", "derived_without_arv"}
    ungated_flags = set(ungated.raw.get("qa_flags") or [])
    assert "verdict_on_flagged_arv" in ungated_flags
    assert "bid_on_contradicted_arv" in ungated_flags


# ---------------------------------------------------------------------------
# 5. THE GUARDS THAT MATTER MOST
# ---------------------------------------------------------------------------

def test_a_clean_lead_is_completely_untouched():
    """16,057 board leads carry an ARV and no flag at all. The board's entire
    usefulness is those rows; not one field of theirs may move."""
    li = _li(state="NC", county="Gaston", street_address="14 Maple Dr",
             property_kind=PropertyKind.SINGLE_FAMILY, living_sqft=1850.0,
             acreage=0.34, bedrooms=3.0, bathrooms=2.0, year_built=2003,
             market_value=300000.0, tax_value=300000.0, opening_bid=210000.0,
             raw={"comp_median_ppsf": 175.0,
                  "comps": [{"price_per_sqft": 175.0, "adjusted_ppsf": 175.0,
                             "sold_price": 262500, "sqft": 1500, "kind": "sfr",
                             "geo_anchored": True} for _ in range(3)]})
    c = vcalc.compute(li)
    before = {f: getattr(c, f) for f in MONEY + VERDICT}
    assert c.arv_flags is None, f"fixture is not clean: {c.arv_flags}"
    g = grading.grade(li, c)
    assert {f: getattr(c, f) for f in MONEY + VERDICT} == before
    assert c.max_bid_70 and c.roi_pct is not None
    assert c.deal_status in ("GREAT", "OK", "NEGOTIATE", "PASS")
    assert g.overall in ("A", "B", "C", "D", "F")

    enrich_data_quality([li])
    flags = li.raw["data_quality"]["flags"]
    for f in ("arv_unreliable", "arv_bid_and_roi_withheld", "arv_no_independent_check"):
        assert f not in flags


def test_an_unrecognised_flag_fails_safe():
    """V1 owns calc.py and adds flags there. A name this file has never seen must
    remove the knife-edge verdict (cheap, 206 leads board-wide) WITHOUT blanking
    money the flag may not even be about."""
    c = _calc(["some_future_guard_v1_adds"])
    assert grading.apply_arv_trust_gate(c) == "weak"
    assert c.deal_status is None
    assert c.max_bid_70 == 180000.0
