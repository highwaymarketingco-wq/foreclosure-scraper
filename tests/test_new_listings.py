"""New-this-run detection (early-access / geo-alert capability).

Owner ask: beat ForeclosureHub's 'get notified before properties hit the
general listings'. We flag what's NEW vs the prior run by dedupe identity
and prioritize fresh lis pendens (earliest signal).
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.new_listings import _prior_keys, top_new_for_alert
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(**kw):
    base = dict(
        source="t", source_url="x", listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY, state="NC", county="Burke",
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


def test_prior_keys_built_from_dicts():
    li = _li(case_number="24SP000123")
    prior = [li.model_dump(mode="json")]
    keys = _prior_keys(prior)
    assert li.dedupe_key() in keys


def test_new_detection_via_dedupe_identity():
    """A listing whose dedupe key matches the prior run is NOT new; a
    different case number IS new."""
    seen = _li(case_number="24SP000123")
    prior_keys = _prior_keys([seen.model_dump(mode="json")])

    same = _li(case_number="24-SP-000123")    # same digits → same key
    fresh = _li(case_number="25SP999999")     # different
    assert same.dedupe_key() in prior_keys
    assert fresh.dedupe_key() not in prior_keys


def test_top_new_prioritizes_lis_pendens_then_soonest_sale():
    fc_far = _li(case_number="A", listing_type=ListingType.FORECLOSURE_SALE,
                 sale_date=datetime(2026, 12, 1))
    fc_far.raw = {"is_new": True}
    lp = _li(case_number="B", listing_type=ListingType.LIS_PENDENS)
    lp.raw = {"is_new": True}
    fc_soon = _li(case_number="C", listing_type=ListingType.FORECLOSURE_SALE,
                  sale_date=datetime(2026, 7, 1))
    fc_soon.raw = {"is_new": True}
    not_new = _li(case_number="D")
    not_new.raw = {"is_new": False}

    out = top_new_for_alert([fc_far, lp, fc_soon, not_new])
    assert not_new not in out               # only new ones
    assert out[0] is lp                     # lis pendens first (earliest signal)
    assert out.index(fc_soon) < out.index(fc_far)  # sooner sale ranks higher
