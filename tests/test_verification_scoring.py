"""Scoring uses verdicts: a non-expired refuted/stale verdict removes the scorer signals its
record governs (distress_score._collect, enrichment_lead_signals._facet_signals); confirmed,
unconfirmed and wall change nothing; an expired verdict changes nothing."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper.enrichment_lead_signals import _facet_signals
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.verifiers import tax_lien_buncombe as tlb

TODAY = date(2026, 10, 5)


def _vrec(verdict, *, expires_in_days=25, governs=tlb.GOVERNS):
    checked = datetime(2026, 10, 5, tzinfo=timezone.utc) - timedelta(days=5)
    return {"signal": "tax_lien", "verdict": verdict, "evidence": {}, "source": tlb.SOURCE,
            "checked_at": core.iso_z(checked), "verifier_version": "v1",
            "verifier": "tax_lien_buncombe",
            "expires_at": core.iso_z(checked + timedelta(days=5 + expires_in_days)),
            "governs": list(governs)}


def _lead(verification=None, amount_source="tax_owed", parcel="961895417300000"):
    raw = {"tax_owed": {"balance": 775.59, "kind": "delinquent_tax", "year": 2025},
           "amount_owed": {"value": 775.59, "source": amount_source, "is_actual_debt": True},
           "code_enforcement": None}
    if verification is not None:
        raw["verification"] = verification
    return Listing(source="counties_nc.buncombe_delinquent_tax", source_url="https://x/y",
                   listing_type=ListingType.TAX_LIEN, state="NC", county="Buncombe",
                   parcel_id=parcel, street_address=f"{parcel[-3:]} PISGAH VIEW RD", raw=raw)


def _names(li):
    return {n for n, _c, _w in ds._signals_for(li, today=TODAY)}


def test_baseline_scores_the_tax_lien_and_the_tax_debt():
    assert {"tax_lien", "recorded_debt"} <= _names(_lead())


@pytest.mark.parametrize("verdict", ["refuted", "stale"])
def test_a_refuted_or_stale_tax_lien_drops_out_of_scoring(verdict):
    names = _names(_lead([_vrec(verdict)]))
    assert "tax_lien" not in names
    assert "recorded_debt" not in names          # the debt was the tax balance


def test_a_judgment_debt_survives_a_refuted_tax_lien():
    # A REAL judgment: a court-published lis pendens carrying the indebtedness. (A `judgment` label on
    # a standing county tax_lien ROLL row is the roll balance a tax scraper promoted to
    # judgment_amount, not a judgment: it follows the tax verdict, see test_tax_roll_amount_kind.)
    li = _lead([_vrec("refuted")], amount_source="judgment").model_copy(update={
        "listing_type": ListingType.LIS_PENDENS, "source": "counties_nc.nc_ecourts_lis_pendens"})
    names = _names(li)
    assert "tax_lien" not in names and "recorded_debt" in names


def test_a_judgment_labelled_roll_balance_follows_a_refuted_tax_lien():
    names = _names(_lead([_vrec("refuted")], amount_source="judgment"))
    assert "tax_lien" not in names and "recorded_debt" not in names


@pytest.mark.parametrize("verdict", ["confirmed", "unconfirmed", "wall"])
def test_other_verdicts_change_nothing(verdict):
    assert _names(_lead([_vrec(verdict)])) == _names(_lead())


def test_an_expired_refutation_changes_nothing():
    assert _names(_lead([_vrec("refuted", expires_in_days=-1)])) == _names(_lead())


def test_only_governed_names_are_removed():
    names = _names(_lead([_vrec("refuted", governs=("tax_lien",))]))
    assert "tax_lien" not in names and "recorded_debt" in names


def test_score_board_tiers_follow_the_verdict():
    # two parcels: score_board unions signals across a parcel group, and on the real board
    # every row of a parcel gets the same verdict (one ledger entry per property)
    plain, refuted = _lead(), _lead([_vrec("refuted")], parcel="961895417400000")
    ds.score_board([plain, refuted], previous_path=None)
    assert "tax_lien" in plain.raw["distress_stack"]["signals"]
    assert "tax_lien" not in (refuted.raw["distress_stack"].get("signals") or [])
    assert refuted.raw["distress_stack"]["score"] < plain.raw["distress_stack"]["score"]


def test_lead_signal_facets_follow_the_same_rule():
    sc = _lead()
    sc.raw["sc_tax_delinquent"] = {"year": 2025}
    base = _facet_signals(sc, TODAY)
    assert {"tax_lien", "recorded_debt"} <= base
    sc.raw["verification"] = [_vrec("stale")]
    after = _facet_signals(sc, TODAY)
    assert "tax_lien" not in after and "recorded_debt" not in after
    sc.raw["amount_owed"]["source"] = "judgment"
    # a `judgment` label on a standing county tax_lien ROLL row is the roll balance (it follows the
    # tax verdict); only a real judgment survives: the same row typed as a court lis pendens
    assert "recorded_debt" not in _facet_signals(sc, TODAY)
    court = sc.model_copy(update={"listing_type": ListingType.LIS_PENDENS,
                                  "source": "counties_nc.nc_ecourts_lis_pendens"})
    assert "recorded_debt" in _facet_signals(court, TODAY)
    sc.raw["verification"] = [_vrec("confirmed")]
    assert _facet_signals(sc, TODAY) == base


def test_confirmed_is_readable_for_a_badge():
    li = _lead([_vrec("confirmed")])
    assert core.verdict_badges(li.raw) == {"tax_lien": "confirmed"}
