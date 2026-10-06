"""raw['stale_case'] is derived from the withdrawn tags every run, never inherited (2026-10-06).

Measured on the published board of 2026-10-06 (223,832 rows, streamed read-only): 99,847 rows
carried raw['stale_case']. 98,564 had a withdrawn tag (95,301 the status 'presumed_withdrawn',
3,263 only raw['pulled_sale'].presumed_withdrawn). 1,283 had no tag at all and nothing for
board_quality's stale check to find: 1,251 no reason of any kind, 32 only a sale date that has
passed (which never sets the flag). 1,232 of them were last seen in the 2026-09-22 run, which is
what a re-scraped row looks like when merge_prior_board() dropped the prior copy's tag but kept
its flag (c3cba6ed fixed the matched path). Nothing cleared the flag afterwards: board_quality
only ever set it, so a row that is not re-scraped, or an offline pass over the board
(scripts/enrich_board.py), kept it for good. Effect: the dashboard's presumedWithdrawn() read it
as "presumed withdrawn" and lead_signals capped intent at 69. 46 of the 1,283 are HOT tier; 7 of
those (and 3 WARM-tier rows) were capped out of the 'hot' intent band.

The rows below take their shapes from that board (source, listing type, county, distress stack,
grade, intent, sale date, status), with the owner, address and parcel replaced by placeholders.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from foreclosure_scraper.board_persist import merge_prior_board
from foreclosure_scraper.enrichment_board_quality import enrich_board_quality
from foreclosure_scraper.enrichment_lead_signals import enrich_lead_signals
from foreclosure_scraper.models import Listing, ListingType

TODAY = date(2026, 10, 6)
LAST_FULL_RUN = datetime(2026, 9, 22, 15, 45, 53)
MERGE_NOW = datetime(2026, 10, 5, 2, 18, 47)


def _pickens_hot(**raw) -> Listing:
    """counties.multi_year_delinquent_tax, Pickens SC: HOT tier, stack 3, score 60, grade 61,
    published intent 69 'warm' (capped by an inherited stale_case; uncapped it is 75)."""
    return Listing(
        source="counties.multi_year_delinquent_tax", source_url="https://example.invalid/pickens",
        listing_type=ListingType.TAX_LIEN, state="SC", county="Pickens",
        street_address="100 EXAMPLE RD", parcel_id="9999-00-00-000", last_seen=LAST_FULL_RUN,
        raw={"distress_stack": {"tier": "HOT", "stack": 3, "score": 60,
                                "categories": ["FINANCIAL", "LIFE_EVENT", "PROPERTY"],
                                "signals": ["distressed_condition", "probate_deed", "recorded_debt",
                                            "tax_lien", "tax_lien_chronic"], "equity_band": "high"},
             "grade": {"overall_score": 61}, **raw})


def _rutherford_tax(**raw) -> Listing:
    """counties_nc.rutherford_tax: COLD tier, 'advertised', intent 20 'cool', stale_case, no tag."""
    return Listing(
        source="counties_nc.rutherford_tax", source_url="https://example.invalid/rutherford",
        listing_type=ListingType.TAX_LIEN, state="NC", county="Rutherford", auction_status="advertised",
        street_address="200 EXAMPLE LN", parcel_id="9999999", last_seen=LAST_FULL_RUN,
        raw={"distress_stack": {"tier": "COLD", "stack": 1, "score": 20, "categories": ["FINANCIAL"],
                                "signals": ["recorded_debt", "tax_lien"]}, **raw})


def _henderson_tax_sale(**raw) -> Listing:
    """counties_nc.henderson_foreclosure_parcels: a tax sale on 2026-05-27, long past, no upset
    window open, inherited stale_case and no tag. (HOT here only to see the down-rank.)"""
    return Listing(
        source="counties_nc.henderson_foreclosure_parcels", source_url="https://example.invalid/henderson",
        listing_type=ListingType.TAX_SALE, state="NC", county="Henderson",
        street_address="300 EXAMPLE CT", parcel_id="9999999999", last_seen=LAST_FULL_RUN,
        sale_date=datetime(2026, 5, 27, 10, 0, 0),
        raw={"distress_stack": {"tier": "HOT", "stack": 2, "score": 40, "categories": ["FINANCIAL", "LEGAL"],
                                "signals": ["recorded_debt", "tax_lien"]}, **raw})


# ------------------------------------------------------------------ the flag is not earned: gone
def test_an_untagged_stale_case_is_removed_and_nothing_else_moves():
    li = _rutherford_tax(stale_case=True, intent_score=20, intent_band="cool")
    stats = enrich_board_quality([li], today=TODAY)
    assert "stale_case" not in li.raw
    assert stats["stale_case_cleared"] == 1 and "stale_flagged" not in stats
    assert li.raw["distress_stack"]["tier"] == "COLD" and "downranked_stale" not in li.raw["distress_stack"]
    assert li.auction_status == "advertised"
    assert (li.raw["intent_score"], li.raw["intent_band"]) == (20, "cool")


def test_a_hot_row_the_flag_capped_gets_its_intent_band_back_on_the_next_scoring_pass():
    """The 7 HOT rows of the published board. Tail order is lead_signals THEN board_quality, so the
    cap is lifted by the pass after the one that clears the flag; the tier never moved."""
    li = _pickens_hot(stale_case=True)
    enrich_lead_signals([li])
    assert (li.raw["intent_score"], li.raw["intent_band"]) == (69, "warm")      # as published
    enrich_board_quality([li], today=TODAY)
    assert "stale_case" not in li.raw
    assert li.raw["distress_stack"]["tier"] == "HOT"                           # never down-ranked
    assert (li.raw["intent_score"], li.raw["intent_band"]) == (69, "warm")      # not rescored yet
    enrich_lead_signals([li])
    assert (li.raw["intent_score"], li.raw["intent_band"]) == (75, "hot")


def test_a_passed_sale_date_is_not_stale_case_but_still_down_ranks_a_hot_row():
    """32 of the 1,283: stale_case with only 'sale_date_passed' behind it. The flag means "the
    source stopped listing the case"; the sale date keeps its own flag and its own down-rank."""
    li = _henderson_tax_sale(stale_case=True)
    stats = enrich_board_quality([li], today=TODAY)
    assert "stale_case" not in li.raw and stats["stale_case_cleared"] == 1
    assert li.raw["sale_date_passed"] is True and li.raw["sale_date_passed_days"] == 132
    ds = li.raw["distress_stack"]
    assert ds["tier"] == "WARM" and ds["downranked_reason"] == "sale_date_passed"
    assert stats["hot_downranked"] == 1 and "stale_flagged" not in stats


# ------------------------------------------------------------------- the flag is earned: kept
@pytest.mark.parametrize("status,pulled,why", [
    ("presumed_withdrawn", None, "presumed_withdrawn"),                       # 95,301 published rows
    ("active", {"presumed_withdrawn": True, "consecutive_misses": 1}, "pulled_sale_presumed_withdrawn"),
    (None, {"presumed_withdrawn": True, "consecutive_misses": 2}, "pulled_sale_presumed_withdrawn"),
])
def test_a_stale_case_with_a_withdrawn_tag_behind_it_is_kept(status, pulled, why):
    raw = {"stale_case": True}
    if pulled:
        raw["pulled_sale"] = pulled
    li = _pickens_hot(**raw)
    li.auction_status = status
    stats = enrich_board_quality([li], today=TODAY)
    assert li.raw["stale_case"] is True and "stale_case_cleared" not in stats
    assert li.raw["distress_stack"]["tier"] == "WARM"
    assert li.raw["distress_stack"]["downranked_reason"] == why


def test_a_withdrawn_tag_without_the_flag_still_sets_it():
    li = _rutherford_tax()
    li.auction_status = "presumed_withdrawn"
    stats = enrich_board_quality([li], today=TODAY)
    assert li.raw["stale_case"] is True and stats["stale_flagged"] == 1


def test_the_pass_is_idempotent_and_only_touches_the_unearned_flag():
    rows = [_rutherford_tax(stale_case=True), _pickens_hot(stale_case=True), _henderson_tax_sale(stale_case=True),
            _pickens_hot(stale_case=True, pulled_sale={"presumed_withdrawn": True, "consecutive_misses": 1})]
    enrich_board_quality(rows, today=TODAY)
    once = json.dumps([r.model_dump(mode="json") for r in rows], sort_keys=True)
    stats = enrich_board_quality(rows, today=TODAY)
    assert json.dumps([r.model_dump(mode="json") for r in rows], sort_keys=True) == once
    assert "stale_case_cleared" not in stats
    assert [bool(r.raw.get("stale_case")) for r in rows] == [False, False, False, True]


# ------------------------------------------------------- the tail in order, around the merge
def _legacy_untagged(addr: str, parcel: str) -> Listing:
    """A published row of the 1,251 shape: stale_case, no tag, a HOT stack capped at intent 69."""
    li = _pickens_hot(stale_case=True, intent_score=69, intent_band="warm")
    li.street_address, li.parcel_id = addr, parcel
    return li


def test_the_full_run_order_a_rescraped_row_loses_the_flag_and_an_unseen_one_is_tagged_by_aging(tmp_path):
    """merge_prior_board() -> lead_signals -> board_quality, as main.run() runs them. A row the run
    re-scrapes loses the flag at the merge (so lead_signals sees no cap); a row the run did not see
    is aged (tagged presumed withdrawn), so its flag is earned again and board_quality keeps it."""
    seen_prior = _legacy_untagged("100 EXAMPLE RD", "9999-00-00-000")
    gone_prior = _legacy_untagged("101 EXAMPLE RD", "9999-00-00-001")
    (tmp_path / "listings.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in (seen_prior, gone_prior)]))
    fresh = _pickens_hot()
    fresh.raw.pop("distress_stack")
    fresh.last_seen = MERGE_NOW
    merged, st = merge_prior_board([fresh], docs_dir=tmp_path, now=MERGE_NOW)
    assert (st["matched"], st["prior_only_kept"]) == (1, 1)
    by_addr = {li.street_address: li for li in merged}   # aged prior-only rows come first
    seen, gone = by_addr["100 EXAMPLE RD"], by_addr["101 EXAMPLE RD"]
    assert "stale_case" not in seen.raw and "pulled_sale" not in seen.raw
    assert gone.auction_status == "presumed_withdrawn" and gone.raw["pulled_sale"]["presumed_withdrawn"]

    enrich_lead_signals(merged)
    enrich_board_quality(merged, today=TODAY)
    assert "stale_case" not in seen.raw
    assert seen.raw["distress_stack"]["tier"] == "HOT" and seen.raw["intent_band"] == "hot"
    assert gone.raw["stale_case"] is True
    assert gone.raw["distress_stack"]["tier"] == "WARM"
    assert gone.raw["distress_stack"]["downranked_reason"] == "presumed_withdrawn"
