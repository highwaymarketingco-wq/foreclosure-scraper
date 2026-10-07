"""A county tax-roll balance is a tax balance, not a court judgment.

2026-10-07, the pre_publish checkpoint of the full run: the HOT tier grew from 441 to 1,504 and
1,458 of the 1,504 were standing tax_lien roll rows (Rutherford 1,120, the Buncombe-area and
multi-year rolls the rest).
Their scrapers promote the roll balance to Listing.judgment_amount, so enrich_amount_owed labelled
it `judgment` / is_actual_debt, the equity engine read it as an EVIDENCED payoff (a judgment is a
fact about the debt, a tax bill is not: enrichment_equity._NON_MORTGAGE_PAYOFF_SOURCES), and a
$6.65 balance on a vacant lot opened the HOT gate with a tax_lien + vacant_lot stack of two.
Replayed on the checkpoint: HOT 1,504 -> 46, none of the change outside a standing tax_lien roll
row. These tests pin the shapes (owners are invented).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper.enrichment_amount_owed import (
    _tax_owed_promotion, enrich_amount_owed, is_standing_tax_roll_row,
    promote_tax_owed_amount_owed,
)
from foreclosure_scraper.enrichment_equity import enrich_equity
from foreclosure_scraper.enrichment_lead_signals import _facet_signals
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.verifiers import tax_lien_buncombe as tlb

TODAY = date(2026, 10, 7)
_NOW = datetime(2026, 10, 7)


def _judgment_label(v):
    return {"value": v, "source": "judgment", "label": "Judgment / indebtedness",
            "confidence": "high", "is_actual_debt": True}


def _roll(owed, *, source="counties_nc.rutherford_tax", label="judgment", vacant=True,
          parcel="1650388", stale_equity=False, arv=60000.0):
    """A Rutherford TR-452 roll row as the 2026-10-07 checkpoint carried it: tax_lien typed, the roll
    balance in judgment_amount, labelled `judgment` by the old waterfall, with an absentee owner
    reachable by mail and (usually) a vacant lot."""
    raw = {
        "rutherford_tax": {"report": "TR-452 Delinquent Bills Report w/ Parcel Id", "parcel": parcel,
                           "taxpayer": "TESTER, ADA", "amount_owed": owed, "tax_year": "2025",
                           "data_as_of": "1/31/2026 10:13:19 PM"},
        "tax_owed": {"balance": owed, "kind": "delinquent_tax", "source": source, "year": 2025,
                     "basis": "own_record"},
        "amount_owed": _judgment_label(owed) if label == "judgment" else
        {"value": owed, "source": label, "label": "Delinquent property tax owed",
         "confidence": "high", "is_actual_debt": True},
        "owner_mailing": {"mailing": "259 TEST RD RUTHERFORDTON", "absentee": True},
        "calc": {"arv_expected": arv},
    }
    if vacant:
        raw["vacant_lot"] = {"land_use": "VACANT", "source": "parcel_cache_landuse"}
    li = Listing(source=source, source_url="https://x/y", listing_type=ListingType.TAX_LIEN,
                 property_kind=PropertyKind.LAND, state="NC", county="Rutherford", parcel_id=parcel,
                 street_address=f"{parcel[-3:]} TEST RD", judgment_amount=owed,
                 first_seen=_NOW, last_seen=_NOW, raw=raw)
    enrich_equity([li])           # computed from the label above, exactly as the checkpoint's was
    if stale_equity:
        # the checkpoint's stored flag, computed when the label was `judgment`
        li.raw["equity"]["evidenced"] = True
        li.raw["equity"]["payoff_source"] = "amount_owed:judgment"
    return li


def _score(li):
    ds.score_board([li], previous_path=None, today=TODAY)
    return li.raw["distress_stack"]


def _tail(li):
    """The post-checkpoint tail, in its order: promote the tax balance, recompute equity, score."""
    promote_tax_owed_amount_owed([li])
    enrich_equity([li])
    return _score(li)


# ---- the old behaviour, pinned so the fix is visible --------------------------------------------
def test_the_checkpoint_shape_is_evidenced_equity_on_a_tax_bill():
    li = _roll(1770.17)
    assert li.raw["amount_owed"]["source"] == "judgment"
    assert li.raw["equity"]["payoff_source"] == "amount_owed:judgment"
    assert li.raw["equity"]["evidenced"] is True


# ---- the tail: promote relabels, equity stops reading it as a mortgage, the row is WARM -------
def test_a_1770_dollar_roll_balance_is_warm_not_hot_after_the_tail():
    li = _roll(1770.17)
    ds_ = _tail(li)
    assert li.raw["amount_owed"]["source"] == "tax_owed"
    assert li.raw["amount_owed"]["label"] == "Delinquent property tax owed"
    assert li.raw["equity"]["payoff_source"] == "amount_owed:tax_owed"
    assert li.raw["equity"]["evidenced"] is False
    assert ds_["tier"] == "WARM"                       # tax_lien + vacant_lot is a stack of two
    assert ds_["stack"] == 2 and {"tax_lien", "vacant_lot"} <= set(ds_["signals"])
    assert ds_["equity_band"] == "high" and ds_["equity_evidenced"] is False


def test_the_scorer_alone_cannot_be_opened_by_a_stale_judgment_label():
    """score_late_rows and rescoring scripts do not run the promote step: a stored equity block
    computed from the old `judgment` label must not open HOT on a standing roll row."""
    li = _roll(1770.17, stale_equity=True)
    assert li.raw["equity"]["evidenced"] is True
    assert _score(li)["tier"] == "WARM"


def test_a_6_dollar_65_interest_residue_earns_nothing_and_is_cold():
    li = _roll(6.65)
    ds_ = _tail(li)
    assert ds_["tier"] == "COLD"
    assert "tax_lien" not in ds_["signals"] and "recorded_debt" not in ds_["signals"]
    assert ds_["signals"] == ["vacant_lot"]            # the lot stays context, one category


def test_the_floor_is_the_registrys_de_minimis_and_is_a_boundary():
    from foreclosure_scraper.verification.verifiers._tax_common import DE_MINIMIS
    assert ds.TRIVIAL_TAX_BALANCE == DE_MINIMIS == 25.0
    under = _tail(_roll(24.99, parcel="1650391"))
    at = _tail(_roll(25.00, parcel="1650392"))
    assert under["tier"] == "COLD" and "tax_lien" not in under["signals"]
    assert at["tier"] == "WARM" and "tax_lien" in at["signals"]


def test_the_floor_reads_the_largest_amount_the_row_carries():
    """A principal-only tax_owed beside a total with interest is not a trivial balance."""
    li = _roll(20.0, parcel="1650393")
    li.judgment_amount = 61.50                          # the roll's own total
    li.raw["amount_owed"] = _judgment_label(61.50)
    assert not ds.trivial_tax_roll(li)
    assert "tax_lien" in _tail(li)["signals"]


def test_the_scorer_alone_applies_the_floor_to_a_judgment_labelled_residue():
    li = _roll(6.65, stale_equity=True)
    ds_ = _score(li)
    assert "tax_lien" not in ds_["signals"] and ds_["tier"] == "COLD"


# ---- real judgments and non-roll rows are unchanged ----------------------------------------------
def _foreclosure(owed=187425.0):
    """A genuine foreclosure judgment: lis_pendens, court-published indebtedness, vacant lot, a
    mailable owner, an evidenced equity: HOT before and after."""
    li = Listing(source="counties_sc.greenville_mie_adverts", source_url="u",
                 listing_type=ListingType.LIS_PENDENS, state="SC", county="Greenville",
                 parcel_id="0123456789", street_address="9 TEST LN", judgment_amount=owed,
                 first_seen=_NOW, last_seen=_NOW,
                 raw={"amount_owed": _judgment_label(owed), "calc": {"arv_expected": 320000.0},
                      "vacant_lot": {"land_use": "VACANT"},
                      "owner_mailing": {"mailing": "1 TEST ST GREENVILLE", "absentee": True},
                      "tax_owed": {"balance": 9.5, "kind": "delinquent_tax", "year": 2025,
                                   "basis": "own_record"}})
    enrich_equity([li])
    return li


def test_a_genuine_foreclosure_judgment_is_not_relabelled_and_keeps_its_tier():
    li = _foreclosure()
    before = _score(li)
    assert not is_standing_tax_roll_row(li)
    assert _tax_owed_promotion(li.raw, li) is None      # never overwritten, tax_owed or not
    ds_ = _tail(li)
    assert li.raw["amount_owed"]["source"] == "judgment"
    assert li.raw["equity"]["payoff_source"] == "amount_owed:judgment"
    assert ds_["tier"] == before["tier"] == "HOT"
    assert "recorded_debt" in ds_["signals"] and "lis_pendens" in ds_["signals"]


def test_a_small_real_judgment_is_not_a_trivial_tax_balance():
    li = _foreclosure(owed=12.0)
    assert not ds.trivial_tax_roll(li)
    assert "recorded_debt" in _score(li)["signals"]


@pytest.mark.parametrize("source", ["counties_sc.sc_dew_lien_registry", "counties_sc.sc_state_tax_lien",
                                    "nc_ecourts_judgments", "counties_nc.nc_ecourts_lis_pendens"])
def test_a_lien_or_court_tax_lien_row_keeps_its_judgment_label_and_credit(source):
    """The verification registry's own list of tax_lien rows that are NOT a county property tax:
    a recorded state lien or a court judgment is a judgment."""
    li = _roll(10.0, source=source, parcel="1650400")
    assert not is_standing_tax_roll_row(li)
    assert _tax_owed_promotion(li.raw, li) is None
    assert not ds.trivial_tax_roll(li)
    ds_ = _tail(li)
    assert li.raw["amount_owed"]["source"] == "judgment"
    assert "tax_lien" in ds_["signals"] and "recorded_debt" in ds_["signals"]


def test_a_tax_sale_with_a_coming_sale_date_is_not_a_standing_roll():
    li = Listing(source="counties_sc.charleston_tax_sale_xlsx", source_url="u",
                 listing_type=ListingType.TAX_SALE, state="SC", county="Charleston",
                 parcel_id="2340000012", street_address="3 TEST AVE", judgment_amount=10.0,
                 sale_date=date(2026, 11, 2), first_seen=_NOW, last_seen=_NOW,
                 raw={"amount_owed": _judgment_label(10.0)})
    assert not is_standing_tax_roll_row(li)
    assert "tax_sale" in {n for n, _c, _w in ds._signals_for(li, today=TODAY)}


def test_a_cross_referenced_tax_balance_on_a_non_roll_lead_is_not_touched():
    """A probate lead pinned to a delinquent parcel inherits the balance (the 9/29 design): only a
    standing roll row's own claim is governed by the floor."""
    li = Listing(source="public_notices.test_obituaries", source_url="u",
                 listing_type=ListingType.ESTATE_LEAD, state="NC", county="Rutherford",
                 parcel_id="1650401", street_address="5 TEST RD",
                 raw={"tax_owed": {"balance": 8.0, "kind": "delinquent_tax", "year": 2025,
                                   "basis": "parcel_cross_ref"}})
    assert not ds.trivial_tax_roll(li)
    assert "recorded_debt" in {n for n, _c, _w in ds._signals_for(li, today=TODAY)}


# ---- a refuted tax verdict now removes the credit the old label kept -----------------------------
def _vrec(verdict):
    checked = datetime(2026, 10, 5, tzinfo=timezone.utc) - timedelta(days=5)
    return {"signal": "tax_lien", "verdict": verdict, "evidence": {}, "source": tlb.SOURCE,
            "checked_at": core.iso_z(checked), "verifier_version": "v1", "verifier": "tax_lien_buncombe",
            "expires_at": core.iso_z(checked + timedelta(days=30)), "governs": list(tlb.GOVERNS)}


@pytest.mark.parametrize("verdict", ["refuted", "stale"])
@pytest.mark.parametrize("label", ["judgment", "tax_owed"])
def test_a_refuted_tax_verdict_removes_the_credit_whatever_the_label(verdict, label):
    li = _roll(775.59, source="counties_nc.buncombe_delinquent_tax", label=label, vacant=False,
               parcel="961895417300000")
    li.raw["verification"] = [_vrec(verdict)]
    names = {n for n, _c, _w in ds._signals_for(li, today=TODAY)}
    assert "tax_lien" not in names
    assert "recorded_debt" not in names                 # the old `judgment` label left this behind
    assert "recorded_debt" not in _facet_signals(li, TODAY)


def test_a_real_judgment_beside_a_refuted_tax_verdict_still_counts():
    li = _foreclosure()
    li.raw["verification"] = [_vrec("refuted")]
    names = {n for n, _c, _w in ds._signals_for(li, today=TODAY)}
    assert "recorded_debt" in names


# ---- the lead-signals chip follows the scorer -------------------------------------------------------
def test_the_lead_signals_chip_follows_the_same_floor():
    assert "recorded_debt" not in _facet_signals(_roll(6.65), TODAY)
    assert "recorded_debt" in _facet_signals(_roll(1770.17), TODAY)
    assert "recorded_debt" in _facet_signals(_foreclosure(owed=12.0), TODAY)


# ---- the future full run labels it right at the source --------------------------------------------
def test_enrich_amount_owed_labels_a_roll_balance_tax_owed_and_a_judgment_judgment():
    roll = Listing(source="counties_nc.rutherford_wildfire_tax", source_url="u",
                   listing_type=ListingType.TAX_LIEN, state="NC", county="Rutherford",
                   parcel_id="1650402", judgment_amount=508.71, first_seen=_NOW, last_seen=_NOW)
    lien = Listing(source="counties_sc.sc_dew_lien_registry", source_url="u",
                   listing_type=ListingType.TAX_LIEN, state="SC", county="Richland",
                   judgment_amount=508.71, first_seen=_NOW, last_seen=_NOW)
    court = Listing(source="counties_sc.greenville_mie_adverts", source_url="u",
                    listing_type=ListingType.LIS_PENDENS, state="SC", county="Greenville",
                    judgment_amount=508.71, first_seen=_NOW, last_seen=_NOW)
    counts = enrich_amount_owed([roll, lien, court])
    assert roll.raw["amount_owed"]["source"] == "tax_owed"
    assert roll.raw["amount_owed"]["is_actual_debt"] is True and roll.raw["amount_owed"]["value"] == 508.71
    assert lien.raw["amount_owed"]["source"] == "judgment"
    assert court.raw["amount_owed"]["source"] == "judgment"
    assert counts["tax_owed"] == 1 and counts["judgment"] == 2


# ---- idempotence --------------------------------------------------------------------------------------
def test_the_tail_is_idempotent():
    li = _roll(1770.17)
    first = _tail(li)
    ao1, eq1 = dict(li.raw["amount_owed"]), dict(li.raw["equity"])
    st = promote_tax_owed_amount_owed([li])
    enrich_equity([li])
    second = _score(li)
    assert st["relabelled_judgment"] == 0                # already tax_owed: nothing left to relabel
    assert li.raw["amount_owed"] == ao1
    assert li.raw["equity"] == eq1
    assert second == first


def test_promote_reports_how_many_judgment_labels_it_corrected():
    a, b, c = _roll(300.0, parcel="1650410"), _roll(40.0, parcel="1650411"), _foreclosure()
    st = promote_tax_owed_amount_owed([a, b, c])
    assert st["relabelled_judgment"] == 2 and st["unchanged"] == 1


def test_without_the_row_the_old_rule_holds_for_the_backfill_scripts():
    """scripts/backfill_tax_owed_amount_owed.py calls _tax_owed_promotion(raw) on dicts with no row
    context: a judgment is still never overwritten there."""
    li = _roll(300.0, parcel="1650412")
    assert _tax_owed_promotion(li.raw) is None
    assert _tax_owed_promotion(li.raw, li)["source"] == "tax_owed"
    assert _tax_owed_promotion(li.raw, {"listing_type": "tax_lien",
                                        "source": "counties_nc.rutherford_tax"})["source"] == "tax_owed"
