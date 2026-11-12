"""verification.core: the result type, row identity and the read side the scorer uses."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from foreclosure_scraper.models import Listing
from foreclosure_scraper.verification import core

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _rec(signal="tax_lien", verdict="refuted", governs=("tax_lien",), expires=NOW + timedelta(days=10)):
    return {"signal": signal, "verdict": verdict, "evidence": {}, "source": "s",
            "checked_at": core.iso_z(NOW - timedelta(days=1)), "verifier_version": "v1",
            "verifier": "x", "expires_at": core.iso_z(expires) if expires else None,
            "governs": list(governs)}


# ---------------------------------------------------------------------------
# VerificationResult
# ---------------------------------------------------------------------------

def test_result_round_trips_and_stamps_utc():
    r = core.result("tax_lien", "confirmed", {"total": 12.5}, source="tax.example",
                    version="v1", verifier="tax_lien_x", now=NOW)
    assert r.checked_at == "2026-10-05T12:00:00Z"
    d = r.to_dict()
    assert set(d) == {"signal", "verdict", "evidence", "source", "checked_at",
                      "verifier_version", "verifier"}
    assert core.VerificationResult.from_dict(d) == r
    assert r.decisive


@pytest.mark.parametrize("bad", ["maybe", "", "CONFIRMED"])
def test_result_rejects_unknown_verdicts(bad):
    with pytest.raises(ValueError):
        core.VerificationResult(signal="tax_lien", verdict=bad)


def test_result_needs_signal_and_dict_evidence():
    with pytest.raises(ValueError):
        core.VerificationResult(signal="", verdict="wall")
    with pytest.raises(ValueError):
        core.VerificationResult(signal="x", verdict="wall", evidence=["not", "a", "dict"])


def test_verdict_classes():
    assert core.SUPPRESSING == {"refuted", "stale"}
    assert core.DECISIVE == {"confirmed", "refuted", "stale"}
    assert set(core.VERDICTS) == {"confirmed", "refuted", "stale", "unconfirmed", "wall"}


def test_expires_at_and_parse_ts():
    assert core.expires_at("2026-10-05T00:00:00Z", 30) == "2026-11-04T00:00:00Z"
    assert core.expires_at("", 30) is None and core.expires_at("2026-10-05T00:00:00Z", None) is None
    assert core.parse_ts("2026-10-05T01:02:03+00:00") == datetime(2026, 10, 5, 1, 2, 3, tzinfo=timezone.utc)
    assert core.parse_ts("junk") is None


# ---------------------------------------------------------------------------
# row identity
# ---------------------------------------------------------------------------

def test_row_key_is_the_normalized_parcel_identity():
    a = {"state": "NC", "county": "Buncombe", "parcel_id": "8772-95-9699-00000",
         "street_address": "98 Turner Cove Rd", "source_url": "https://roll.example/all.pdf"}
    b = dict(a, parcel_id="877295969900000")
    assert core.row_key(a) == core.row_key(b) == "parcel:NC:buncombe:8772959699"


def test_row_keys_carry_every_branch_and_the_address_ignores_zip():
    row = {"state": "NC", "county": "Buncombe", "parcel_id": "877295969900000",
           "street_address": "98 Turner Cove Road", "case_number": "24 CVD 123"}
    keys = core.row_keys(row)
    assert keys[0].startswith("parcel:")
    assert "addr:NC:buncombe:98 turner cove rd" in keys
    assert "case:NC:buncombe:24cvd123" in keys
    assert core.row_keys(dict(row, zip_code="28806"))[1] == keys[1]


def test_a_backfilled_parcel_keeps_the_address_key():
    before = {"state": "NC", "county": "Buncombe", "street_address": "5 Main St"}
    after = dict(before, parcel_id="964912345600000")
    assert core.row_key(before).startswith("addr:")
    assert core.row_key(before) in core.row_keys(after)


def test_never_keys_on_a_shared_source_url():
    a = {"source": "x", "source_url": "https://county.example/roll.pdf", "owner_name": "A"}
    b = {"source": "x", "source_url": "https://county.example/roll.pdf", "case_number": None,
         "defendant": "SOMEONE ELSE"}
    assert core.row_key(a).startswith("row:")
    assert core.row_key(a) != core.row_key(b)
    assert not any(k.startswith("url:") for k in core.row_keys(a))


def test_row_key_works_on_a_listing_object_and_a_dict_alike():
    d = {"state": "NC", "county": "Buncombe", "parcel_id": "964912345600000",
         "source": "s", "source_url": "u", "listing_type": "tax_lien"}
    li = Listing.model_construct(**d)
    assert core.row_key(li) == core.row_key(d)


def test_tier_rank_orders_hot_warm_cold():
    rows = [{"raw": {"distress_stack": {"tier": t}}} for t in ("COLD", "HOT", "WARM")]
    assert sorted(core.tier_rank(r) for r in rows) == [0, 1, 2]
    assert core.tier_rank({"raw": {}}) == 3


# ---------------------------------------------------------------------------
# the read side
# ---------------------------------------------------------------------------

def test_refuted_and_stale_suppress_their_governed_signals():
    raw = {"verification": [_rec(verdict="refuted", governs=("tax_lien", "recorded_debt:tax")),
                            _rec(signal="jail_booking", verdict="stale", governs=("incarceration",))]}
    assert core.suppressed_scorer_signals(raw, NOW) == {"tax_lien", "recorded_debt:tax", "incarceration"}


@pytest.mark.parametrize("verdict", ["confirmed", "unconfirmed", "wall"])
def test_other_verdicts_suppress_nothing(verdict):
    assert core.suppressed_scorer_signals({"verification": [_rec(verdict=verdict)]}, NOW) == set()


def test_an_expired_refutation_suppresses_nothing():
    raw = {"verification": [_rec(expires=NOW - timedelta(seconds=1))]}
    assert core.suppressed_scorer_signals(raw, NOW) == set()


def test_a_date_reference_counts_the_whole_day():
    # expires mid-day on 2026-10-05: the scorer's date(2026, 10, 5) still honours it
    raw = {"verification": [_rec(expires=datetime(2026, 10, 5, 18, 0, tzinfo=timezone.utc))]}
    assert core.suppressed_scorer_signals(raw, date(2026, 10, 5)) == {"tax_lien"}
    assert core.suppressed_scorer_signals(raw, date(2026, 10, 6)) == set()


def test_read_side_tolerates_junk():
    for raw in (None, {}, {"verification": "x"}, {"verification": [1, None, {"no": "signal"}]}):
        assert core.suppressed_scorer_signals(raw, NOW) == set()
        assert core.verdict_badges(raw, NOW) == {}


def test_verdict_badges_show_only_current_records():
    raw = {"verification": [_rec(verdict="confirmed"),
                            _rec(signal="bankruptcy_stay", verdict="refuted",
                                 expires=NOW - timedelta(days=1))]}
    assert core.verdict_badges(raw, NOW) == {"tax_lien": "confirmed"}


def test_compact_bounds_evidence():
    ev = {"years": list(range(100)), "note": "x" * 2000}
    c = core.compact(ev)
    assert len(c["years"]) == 40 and len(c["note"]) < 600


@pytest.mark.parametrize("addr", ["OLD TRULL RD", "NC 9 HWY", "0 NO ADDRESS ASSIGNED", "S TURKEY CREEK RD"])
def test_an_address_without_a_real_house_number_is_not_an_identity(addr):
    keys = core.row_keys({"state": "NC", "county": "Buncombe", "parcel_id": "8697194400",
                          "street_address": addr})
    assert keys == ["parcel:NC:buncombe:8697194400"]


def test_a_numbered_address_with_a_unit_letter_is_an_identity():
    keys = core.row_keys({"state": "NC", "county": "Buncombe", "street_address": "2514A South Blvd"})
    assert keys[0].startswith("addr:NC:buncombe:2514")
