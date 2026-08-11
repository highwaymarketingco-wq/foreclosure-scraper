"""The board cannot tell when an input record describes a DIFFERENT property.

Every test here is a regression tripwire for a measured defect on the live
38,500-lead board, not a hypothetical:

  * ONE Lincoln County NC appraisal (`market_value == 299453.0`, actually
    308 S Academy St, Lincolnton, a commercial building) stamped onto 1,433
    leads across 1,354 distinct parcels, driving $320,145,300 of max bids and
    ~$155M of equity — while the detector built for exactly this fired on 0 of
    them, because its gate required assessed_value AND acreage and both are
    null on ~95% of the cohort.
  * 3,262 Spartanburg vacant-registry leads pinned to the city centroid because
    the scraper asked its polygon layer for `returnGeometry: "false"`.
  * 258 leads whose sale date has passed, 32 still "active", 23 still
    publishing a deal verdict (8 GREAT).
  * 5,308 leads where the assessor row names a different owner than the source.
  * 26 leads publishing $40.2M of equity off an ARV the valuation declined to
    publish and this module's own fallback invented.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.distress_score import retract_equity_rank
from foreclosure_scraper.enrichment_board_qa import (
    OWNER_MISMATCH_FLAG,
    SHARED_ANCHOR_FLAG,
    enrich_board_qa,
    owner_records_disagree,
    shared_anchor_stamps,
)
from foreclosure_scraper.enrichment_board_quality import enrich_board_quality
from foreclosure_scraper.enrichment_equity import (
    enrich_equity,
    valuation_ran_without_arv,
    withhold_equity,
)
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_sc.spartanburg_vacant import parcel_centroid


def _lead(**kw) -> Listing:
    raw = kw.pop("raw", None)
    base = dict(source="counties_nc.nc_county_pdf_delinquent_tax", source_url="u",
                listing_type=ListingType.TAX_LIEN, state="NC", county="Lincoln")
    base.update(kw)
    return Listing(raw=raw if raw is not None else {}, **base)


def _stamped(n: int, value: float, *, owner_prefix="OWNER", **extra) -> list[Listing]:
    """`n` leads, distinct parcels and owners, all carrying the same anchor."""
    return [_lead(parcel_id=f"P{i:05d}", owner_name=f"{owner_prefix} {i}",
                  market_value=value, **extra) for i in range(n)]


def _anchored_calc(arv: float = 300000.0) -> dict:
    """A calc block shaped like the Lincoln cohort's: the ARV IS the county
    figure restated, which is what `anchor_not_independent` means."""
    return {"arv_expected": arv, "arv_flags": ["anchor_not_independent"],
            "max_bid_70": round(arv * 0.7, -2), "wholesale_mao": round(arv * 0.65, -2),
            "roi_pct": 42.0, "estimated_profit": 50000.0,
            "deal_status": "GREAT", "deal_message": "go bid", "notes": []}


# ---------------------------------------------------------------------------
# B1 — the county figure stamped across a county's worth of parcels
# ---------------------------------------------------------------------------

def test_stamp_detected_on_non_round_value_across_many_parcels():
    leads = _stamped(40, 299453.0)
    stamps = shared_anchor_stamps(leads)
    assert len(stamps) == 40
    info = stamps[id(leads[0])]
    assert info["value"] == 299453.0
    assert info["parcels"] == 40
    assert info["basis"] == "sub_hundred_precision"
    assert info["field"] == "market_value"


def test_round_value_repeated_is_left_alone():
    """McDowell $3,000 x 214 parcels and Spartanburg $17,500 x 203 are a
    delinquent-tax roll's genuine floor valuations for near-worthless slivers.
    Blanking their economics would gut the normal case for nothing."""
    assert shared_anchor_stamps(_stamped(214, 3000.0)) == {}
    assert shared_anchor_stamps(_stamped(203, 17500.0)) == {}


def test_small_non_round_cluster_is_left_alone():
    """Seven identical spec-built houses in one subdivision genuinely share an
    appraisal. On the live board the non-round groups run 1,352 then 7, 7, 5."""
    assert shared_anchor_stamps(_stamped(7, 770587.0)) == {}


def test_round_value_fires_when_the_leads_own_records_disagree():
    """Clause (b): the safety net for a future stamp on a round number."""
    leads = _stamped(30, 400000.0)
    for li in leads[:10]:                 # their own tax_value says ~$40k
        li.tax_value = 40000.0
    stamps = shared_anchor_stamps(leads)
    assert len(stamps) == 30
    assert stamps[id(leads[0])]["basis"] == "own_records_disagree"


def test_tax_value_is_not_independent_evidence_against_itself():
    """When tax_value IS the anchor it cannot corroborate it. Guards the SC
    units error too: assessed_value is a 4%/6% statutory ratio and is never
    read here, so it cannot manufacture a 16.7x 'disagreement' on every SC row."""
    leads = [_lead(parcel_id=f"P{i}", owner_name=f"O {i}", tax_value=400000.0,
                   assessed_value=24000.0) for i in range(30)]
    assert shared_anchor_stamps(leads) == {}


def test_stamp_needs_distinct_parcels_not_just_rows():
    """1,433 rows over 1,354 parcels is the defect. 1,433 rows over ONE parcel
    is one property listed many times, which is a different thing entirely."""
    leads = [_lead(parcel_id="SAME", owner_name=f"O {i}", market_value=299453.0)
             for i in range(50)]
    assert shared_anchor_stamps(leads) == {}


def test_stamped_lead_loses_bid_verdict_equity_and_hot_tier():
    leads = _stamped(40, 299453.0)
    for li in leads:
        li.raw = {
            "calc": _anchored_calc(),
            "equity": {"value": 155000.0, "pct": 0.52, "arv_used": 299500.0},
            "distress_stack": {"tier": "HOT", "stack": 2, "score": 30,
                               "equity_band": "high", "absentee": True,
                               "contactable": True,
                               "surviving_senior_debt_risk": False},
        }
    summary = enrich_board_qa(leads)

    for li in leads:
        calc = li.raw["calc"]
        assert SHARED_ANCHOR_FLAG in calc["arv_flags"]
        # the ARV itself SURVIVES — grading's contract is that the gate
        # withholds what is DERIVED from the ARV, not the ARV.
        assert calc["arv_expected"] == 300000.0
        for gone in ("max_bid_70", "wholesale_mao", "roi_pct", "estimated_profit",
                     "deal_status", "deal_message"):
            assert gone not in calc, gone
        assert any("stamped across" in n or "different parcels" in n
                   for n in calc["notes"])
        assert li.raw["equity"]["withheld"] is True
        assert "value" not in li.raw["equity"] and "pct" not in li.raw["equity"]
        assert li.raw["distress_stack"]["tier"] != "HOT"
        assert li.raw["distress_stack"]["equity_band"] is None
        assert SHARED_ANCHOR_FLAG in li.raw["qa_flags"]

    assert summary[SHARED_ANCHOR_FLAG] == 40
    assert summary["anchor_stamp_equity_withheld"] == 40

    # anchor_stamp_max_bid_withheld counts leads whose max bid THIS PASS had to
    # strip by hand. It is deliberately allowed to be absent.
    #
    # The module's own comment predicted this: "Once grading.ARV_FLAGS_CONTRADICTED
    # knows this string, THIS call does all of the work below and the explicit
    # strip becomes a confirming no-op." That happened during integration review —
    # anchor_shared_across_parcels is now in ARV_FLAGS_CONTRADICTED, so
    # gate_calc_dict() removes the money before the manual strip looks for it, and
    # the counter correctly drops to zero.
    #
    # Asserting == 40 pinned WHICH LAYER did the work. The outcome is asserted
    # above, per lead, and is what actually matters: max_bid_70 and the verdict
    # are gone. A counter that only fires when the upstream gate FAILED is a
    # useful signal, so it is checked here rather than deleted — it must never
    # exceed the cohort, which would mean the gate let a bid through.
    assert summary.get("anchor_stamp_max_bid_withheld", 0) <= 40


def test_comp_grounded_lead_in_a_stamped_cluster_keeps_its_money():
    """Only leads whose ARV DESCENDS from the stamp are retracted. A lead whose
    ARV came from real comps happens to carry a stamped market_value and keeps
    everything — 11 of the 1,352 detected rows on the live board."""
    leads = _stamped(40, 299453.0)
    for li in leads:
        li.raw = {"calc": _anchored_calc()}
    comped = leads[0]
    comped.raw["calc"] = {"arv_expected": 443000.0,
                          "arv_flags": ["geo_imprecise_comps"],
                          "max_bid_70": 332200.0, "notes": []}
    enrich_board_qa(leads)
    assert comped.raw["calc"]["max_bid_70"] == 332200.0
    assert SHARED_ANCHOR_FLAG in comped.raw["qa_flags"]      # flagged, not gutted
    assert "max_bid_70" not in leads[1].raw["calc"]


def test_whole_assessor_row_across_many_parcels_is_retracted_too():
    """HALLIDAY Q STANFORD IV, 0.88 acres, assessed $9,781.20, on 668 DISTINCT
    Spartanburg parcels — 264 of them publishing a max bid. The value-only route
    correctly declines to convict this one: its market_value ($384,600) is a
    ROUND number. The identical owner and acreage are what convict it."""
    leads = [_lead(county="Spartanburg", state="SC", parcel_id=f"S{i:05d}",
                   owner_name="HALLIDAY Q STANFORD IV", assessed_value=9781.20,
                   acreage=0.88, market_value=384600.0,
                   raw={"calc": _anchored_calc(384600.0)}) for i in range(40)]
    assert shared_anchor_stamps(leads) == {}      # round value, not convicted alone
    enrich_board_qa(leads)
    for li in leads:
        assert "max_bid_70" not in li.raw["calc"]
        assert SHARED_ANCHOR_FLAG in li.raw["calc"]["arv_flags"]
        assert "gis_row_shared" in li.raw["qa_flags"]
        assert any("assessor record" in n for n in li.raw["calc"]["notes"])


def test_small_shared_assessor_row_stays_display_only():
    """Two parcels sharing a row is ambiguous — adjacent lots under one deed, a
    duplicated record, two identical spec houses. It is flagged, not gutted."""
    leads = [_lead(county="Spartanburg", state="SC", parcel_id=f"S{i}",
                   owner_name="SAME OWNER LLC", assessed_value=9781.20,
                   acreage=0.88, market_value=384600.0,
                   raw={"calc": _anchored_calc(384600.0)}) for i in range(3)]
    enrich_board_qa(leads)
    for li in leads:
        assert "gis_row_shared" in li.raw["qa_flags"]
        assert li.raw["calc"]["max_bid_70"] is not None      # money survives
        assert SHARED_ANCHOR_FLAG not in li.raw["qa_flags"]


def test_retraction_is_idempotent():
    leads = _stamped(40, 299453.0)
    for li in leads:
        li.raw = {"calc": _anchored_calc(),
                  "equity": {"value": 1.0, "pct": 0.5}}
    enrich_board_qa(leads)
    first = [dict(li.raw["calc"]) for li in leads]
    enrich_board_qa(leads)
    for li, before in zip(leads, first):
        assert li.raw["calc"]["arv_flags"].count(SHARED_ANCHOR_FLAG) == 1
        assert len(li.raw["calc"]["notes"]) == len(before["notes"])


def test_stamp_retraction_keeps_the_arv_tripwires_at_zero():
    """`bid_on_contradicted_arv` and `verdict_on_flagged_arv` MUST read zero on
    the board as published — so the withholding has to happen before the
    tripwires look, not after."""
    leads = _stamped(40, 299453.0)
    for li in leads:
        li.raw = {"calc": _anchored_calc()}
    summary = enrich_board_qa(leads)
    assert summary.get("verdict_on_flagged_arv", 0) == 0
    assert summary.get("bid_on_contradicted_arv", 0) == 0
    assert summary.get("derived_without_arv", 0) == 0


# ---------------------------------------------------------------------------
# B1 (second half) — the gis_row_shared gate that never evaluated
# ---------------------------------------------------------------------------

def test_gis_row_shared_fires_with_only_market_value_present():
    """The old gate was `if av and ac and own and cty and pid`. On the Lincoln
    cohort assessed_value is null on 1,373 of 1,433 and acreage on 1,344, so it
    never evaluated — and market_value was never in the key at all."""
    leads = [_lead(parcel_id="A1", owner_name="AMERO PROPERTIES LLC", market_value=299453.0),
             _lead(parcel_id="B2", owner_name="AMERO PROPERTIES LLC", market_value=299453.0)]
    for li in leads:
        li.raw = {}
    enrich_board_qa(leads)
    assert all("gis_row_shared" in li.raw.get("qa_flags", []) for li in leads)


def test_gis_row_shared_does_not_fire_on_owner_alone():
    """Dropping the value requirement entirely takes the detector to 5,449 rows,
    2,215 of them keyed on (county, state, None, None, None, owner) — that is a
    landlord who owns two parcels, not a fanned-out assessor row."""
    leads = [_lead(parcel_id="A1", owner_name="BIG LANDLORD LLC"),
             _lead(parcel_id="B2", owner_name="BIG LANDLORD LLC")]
    for li in leads:
        li.raw = {}
    enrich_board_qa(leads)
    assert all("gis_row_shared" not in li.raw.get("qa_flags", []) for li in leads)


# ---------------------------------------------------------------------------
# B7 — two different people on the same card
# ---------------------------------------------------------------------------

def test_benign_owner_differences_are_not_mismatches():
    for source_owner, gis_owner in [
        ("Kendra A Mason", "MASON KENDRA A"),                       # word order
        ("ADKINS GARRY WAYNE (LE)", "ADKINS GARRY"),                # life estate
        ("YOUNG SHERRILL D", "YOUNG SHERRILL D (DECEASED)"),        # status marker
        ("MATHIS, JOSHUA CODY", "MATHIS, JOSHUA CODY;MATHIS, SHANA LOUISE"),
        ("THOMPSON FAMILY LIMITED PARTNERSHIP", "THE THOMPSON FAMILY LIMITED PARTNERSHIP"),
        ("Kenneth Wayne Peigler Jr", "PEIGLER KENNETH W SR"),       # generation
        ("BROWN LYNNIC BROWN CHRISTINA", "BROWN LYNNIC"),           # co-owner subset
        ("Kevin Joseph Gurchiek", "GURCHIEK KEVIN J<br>GURCHIEK CYNTHIA M"),
        ("UNKNOWN OWNER", "WILKIE, JULIA HEIRS"),                   # placeholder
        ("SMITH JOHN", ""),                                          # nothing to compare
    ]:
        assert not owner_records_disagree(source_owner, gis_owner), (source_owner, gis_owner)


def test_two_different_parties_are_flagged():
    for source_owner, gis_owner in [
        ("HINES, KEITH A", "HAMILTON, JAMES LEE"),
        ("LYTLE, JAMES E SR", "PEREZ RODNEY A;SINGLETON GINA R"),
        ("GUENTHER DOUGLAS KARL", "INCANDELA NICHOLAS JOSEPH"),
        ("DEPARTMENT OF VETERANS AFFAIRS", "OTT WILLIAM B III"),
    ]:
        assert owner_records_disagree(source_owner, gis_owner), (source_owner, gis_owner)


def test_owner_mismatch_flags_but_does_not_gate_money():
    """Display-only, deliberately: the disagreement means either a bad join OR
    an assessor row that is simply fresher than the court record. 3,190 of the
    3,681 zero-overlap leads publish a max bid; blanking them would gut the
    normal case to punish an ambiguity."""
    li = _lead(parcel_id="P1", owner_name="HINES, KEITH A",
               raw={"gis": {"owner": "HAMILTON, JAMES LEE"},
                    "calc": {"arv_expected": 200000.0, "max_bid_70": 140000.0}})
    summary = enrich_board_qa([li])
    assert OWNER_MISMATCH_FLAG in li.raw["qa_flags"]
    assert li.raw["calc"]["max_bid_70"] == 140000.0
    assert summary["owner_mismatch_two_private_parties"] == 1


# ---------------------------------------------------------------------------
# B3 — equity inventing an ARV the valuation declined to publish
# ---------------------------------------------------------------------------

def test_equity_withheld_when_valuation_ran_and_published_no_arv():
    """All 26 live cases have a real calc block — rehab, tier, confidence,
    notes — and no arv_expected, no arv_withheld, no arv_flags. `arv_trust`
    returns 'ok' on exactly that shape, so only this test catches it."""
    li = _lead(market_value=9_000_000.0, judgment_amount=1_000_000.0,
               raw={"calc": {"rehab_expected": 40000.0, "rehab_tier": "light",
                             "confidence": "LOW", "notes": []}})
    assert valuation_ran_without_arv(li) is True
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq["withheld"] is True
    assert "value" not in eq and "pct" not in eq
    assert eq["arv_trust"] == "withheld"


def test_equity_still_computed_when_no_valuation_ever_ran():
    """The distinction that matters is whether a valuation RAN. A source that
    never reached calc has had nothing decided about its value, and blanking
    those would delete equity on leads where nothing is wrong."""
    li = _lead(market_value=200000.0, judgment_amount=50000.0, raw={})
    assert valuation_ran_without_arv(li) is False
    stats = enrich_equity([li])
    assert stats["computed"] == 1
    assert li.raw["equity"]["value"] is not None
    assert stats["withheld_no_arv"] == 0


def test_withhold_equity_reports_only_real_retractions():
    li = _lead(raw={"equity": {"value": 100.0, "pct": 0.1}})
    assert withhold_equity(li, "contradicted", ["x"]) is True
    assert withhold_equity(li, "contradicted", ["x"]) is False    # already withheld
    assert li.raw["equity"]["withheld"] is True


def test_withhold_equity_stays_silent_when_nothing_was_published():
    """'Withheld because the ARV is contradicted' on a lead that never had an
    equity figure is a guess at someone else's reason — it is far more likely
    absent because no payoff could be estimated."""
    li = _lead(raw={})
    assert withhold_equity(li, "contradicted", ["x"]) is False
    assert "equity" not in li.raw


def test_equity_band_refuses_a_figure_with_no_arv_behind_it():
    """The ranking half of the same decision. `arv_trust` returns 'ok' on a
    calc block with no arv_expected, no arv_withheld and no flags, so without
    this the stale figure on a carried-over board would still promote to HOT."""
    from foreclosure_scraper.distress_score import _equity_band
    stale = _lead(raw={"equity": {"pct": 0.55},
                       "calc": {"rehab_expected": 1000.0, "roi_pct": 90}})
    assert _equity_band(stale) is None
    ok = _lead(raw={"equity": {"pct": 0.55},
                    "calc": {"arv_expected": 250000.0, "roi_pct": 90}})
    assert _equity_band(ok) == "high"


def test_equity_band_refuses_the_withheld_marker():
    """The only signal that survives a LATE cross-row retraction: board_qa
    withholds the figure after score_board has already banded it."""
    from foreclosure_scraper.distress_score import _equity_band
    li = _lead(raw={"equity": {"withheld": True, "arv_trust": "contradicted"},
                    "calc": {"arv_expected": 250000.0, "roi_pct": 90}})
    assert _equity_band(li) is None


def test_retract_equity_rank_does_not_clobber_a_sibling_listing():
    """`score_board` assigns the SAME dict object to every listing on a parcel,
    so an in-place edit would silently re-tier the sibling that legitimately
    supplied the band."""
    shared = {"tier": "HOT", "stack": 2, "score": 30, "equity_band": "high",
              "absentee": True, "contactable": True,
              "surviving_senior_debt_risk": False}
    a = _lead(raw={"distress_stack": shared})
    b = _lead(raw={"distress_stack": shared})
    assert retract_equity_rank(a) is True
    assert a.raw["distress_stack"]["tier"] == "WARM"
    assert b.raw["distress_stack"]["tier"] == "HOT"
    assert retract_equity_rank(a) is False     # idempotent


# ---------------------------------------------------------------------------
# B9 — a sale that already happened, still advertised as upcoming
# ---------------------------------------------------------------------------

def _past_sale(days: int, status: str) -> Listing:
    return _lead(parcel_id="P1", owner_name="O",
                 sale_date=datetime.now() - timedelta(days=days),
                 auction_status=status,
                 raw={"calc": {"arv_expected": 250000.0, "max_bid_70": 170000.0,
                               "deal_status": "GREAT", "deal_message": "bid it",
                               "notes": []}})


def test_past_sale_loses_the_verdict_immediately_and_keeps_the_dollars():
    li = _past_sale(3, "active")
    stats = enrich_board_quality([li])
    assert li.raw["sale_date_passed"] is True
    assert li.raw["sale_date_passed_days"] == 3
    assert "deal_status" not in li.raw["calc"]
    assert "deal_message" not in li.raw["calc"]
    assert li.raw["calc"]["max_bid_70"] == 170000.0      # still a real valuation
    assert stats["past_sale_verdict_withheld"] >= 1


def test_active_survives_the_nc_upset_bid_window():
    """In NC the upset-bid period runs ten days from the report of sale, so
    'active' three days after the sale date is TRUE — and an upset bid is one
    of the better opportunities on this board."""
    li = _past_sale(3, "active")
    enrich_board_quality([li])
    assert li.auction_status == "active"
    assert "auction_status_reported" not in li.raw


def test_active_is_normalized_once_the_upset_window_has_closed():
    li = _past_sale(40, "active")
    enrich_board_quality([li])
    assert li.auction_status == "sale_date_passed"
    assert li.raw["auction_status_reported"] == "active"


def test_past_sale_never_sets_sold_confirmed():
    """`sold_confirmed` means COURT-CONFIRMED and six readers treat it as 'hide
    this lead'. Sales are continued, postponed and cancelled constantly — a
    passed date is not confirmation that a sale occurred."""
    li = _past_sale(400, "active")
    enrich_board_quality([li])
    assert "sold_confirmed" not in li.raw


def test_truthful_past_sale_status_is_left_verbatim():
    li = _past_sale(40, "status: cancelled")
    enrich_board_quality([li])
    assert li.auction_status == "status: cancelled"


def test_past_sale_reaches_the_board_through_qa_flags():
    """web_artifact.RAW_KEEP is a WHITELIST and `sale_date_passed` is not on it,
    so the raw key alone would be gathered and thrown away at publish. qa_flags
    is whitelisted, so board_qa mirrors the signal onto it."""
    from foreclosure_scraper.enrichment_board_qa import SALE_PASSED_FLAG
    li = _past_sale(40, "active")
    enrich_board_quality([li])
    enrich_board_qa([li])
    assert SALE_PASSED_FLAG in li.raw["qa_flags"]
    assert li.auction_status == SALE_PASSED_FLAG      # one word for one fact


def test_future_sale_is_untouched():
    li = _lead(parcel_id="P1", sale_date=datetime.now() + timedelta(days=7),
               auction_status="active",
               raw={"calc": {"arv_expected": 250000.0, "deal_status": "GREAT"}})
    enrich_board_quality([li])
    assert li.raw["calc"]["deal_status"] == "GREAT"
    assert "sale_date_passed" not in li.raw


# ---------------------------------------------------------------------------
# B2 — the Spartanburg pin
# ---------------------------------------------------------------------------

def test_parcel_centroid_lands_inside_a_real_parcel_polygon():
    """The five parcels spot-checked against the city pin sit 2.03-3.48 miles
    away; this is 202 NORTH ST (TAXPIN 712204145906) as the layer returns it."""
    geom = {"rings": [[[-81.93364, 34.92021], [-81.93329, 34.92024],
                       [-81.93332, 34.92052], [-81.93361, 34.92049],
                       [-81.93364, 34.92021]]]}
    lat, lon = parcel_centroid(geom)
    assert 34.9202 < lat < 34.9206
    assert -81.9337 < lon < -81.9332
    # and nowhere near the ASL sculpture on West Main St that 3,262 leads shared
    assert abs(lat - 34.9498) > 0.02


def test_parcel_centroid_refuses_geometry_it_cannot_vouch_for():
    assert parcel_centroid(None) is None
    assert parcel_centroid({}) is None
    assert parcel_centroid({"rings": []}) is None
    assert parcel_centroid({"rings": [[[-81.93, 34.92], [-81.93, 34.92]]]}) is None
    # a projection/datum error: Web Mercator metres left unconverted
    assert parcel_centroid({"rings": [[[-9119000, 4150000], [-9119001, 4150000],
                                       [-9119001, 4150001], [-9119000, 4150001],
                                       [-9119000, 4150000]]]}) is None


def test_parcel_centroid_handles_a_degenerate_zero_area_ring():
    """A sliver or duplicated-vertex record still has a usable location."""
    lat, lon = parcel_centroid({"rings": [[[-81.93, 34.92], [-81.93, 34.93],
                                           [-81.93, 34.92]]]})
    assert 34.92 <= lat <= 34.93
    assert lon == -81.93
