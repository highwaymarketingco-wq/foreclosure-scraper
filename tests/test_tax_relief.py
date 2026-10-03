"""Tests for enrichment_tax_relief.py — senior/disabled exemption + present-use
rollback-lien tagging.

This enricher had no dedicated test file before this one, unlike its sibling
enrichment_rollback_deferral.py (which shares the same "rollback tax comes due
on sale" subject and IS covered by tests/test_rollback_deferral.py). Adding
this closes that gap: `_classify()` encodes county-specific quirks (Rutherford
typing its deferral column as a STRING so `> 0` 400s; Gaston/York carrying only
a Y/N flag with no dollar amount; York's dual HOMESTEAD/FARM meaning) that a
future edit could silently break with no test failing.

All tests are offline: `_query` is monkeypatched, nothing here opens a network
connection or touches the board.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_tax_relief as mod


def _lead(**kw) -> Listing:
    from datetime import datetime
    now = datetime.utcnow()
    base = dict(
        source="test",
        source_url="https://example.test",
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=now,
        last_seen=now,
    )
    base.update(kw)
    return Listing(**base)


def _run(listings, **kw):
    return asyncio.run(mod.enrich_tax_relief(listings, **kw))


# --------------------------------------------------------------------------
# _classify — one test per (state, county) config's classify kind
# --------------------------------------------------------------------------

def test_buncombe_senior_exemption_classifies_known_codes():
    cfg = mod._RELIEF_LAYERS[("NC", "Buncombe")]
    for code, kind in (("ELD", "elderly"), ("DIS", "disabled"), ("BLD", "blind")):
        hit = mod._classify(cfg, {"Exempt": code})
        assert hit == {"kind": kind, "basis": "elderly_disabled_exclusion", "code": code}


def test_buncombe_senior_exemption_rejects_unknown_code():
    cfg = mod._RELIEF_LAYERS[("NC", "Buncombe")]
    assert mod._classify(cfg, {"Exempt": "GOV"}) is None
    assert mod._classify(cfg, {"Exempt": ""}) is None


def test_henderson_use_value_deferral_carries_a_dollar_amount():
    cfg = mod._RELIEF_LAYERS[("NC", "Henderson")]
    hit = mod._classify(cfg, {"TOTAL_DEFERRED_VALUE": "125000"})
    assert hit == {"kind": "use_value_deferral", "basis": "present_use_rollback_lien",
                   "deferred_value": 125000.0}


def test_henderson_zero_or_missing_deferred_value_is_not_a_hit():
    cfg = mod._RELIEF_LAYERS[("NC", "Henderson")]
    assert mod._classify(cfg, {"TOTAL_DEFERRED_VALUE": "0"}) is None
    assert mod._classify(cfg, {"TOTAL_DEFERRED_VALUE": None}) is None
    assert mod._classify(cfg, {}) is None


def test_rutherford_deferral_is_parsed_as_a_string_not_compared_numerically():
    """THE bug this config exists to prevent: Rutherford types Use_Value_Deferred
    as esriFieldTypeString, so `_classify` must parse it rather than assume the
    ArcGIS layer already filtered numerically (the where-clause does an
    IS NOT NULL / non-empty string test, not a numeric one)."""
    cfg = mod._RELIEF_LAYERS[("NC", "Rutherford")]
    hit = mod._classify(cfg, {"Use_Value_Deferred": "73,300.00"})
    assert hit == {"kind": "use_value_deferral", "basis": "present_use_rollback_lien",
                   "deferred_value": 73300.0}


def test_rutherford_deferral_zero_string_is_not_a_hit():
    cfg = mod._RELIEF_LAYERS[("NC", "Rutherford")]
    assert mod._classify(cfg, {"Use_Value_Deferred": "0"}) is None
    assert mod._classify(cfg, {"Use_Value_Deferred": ""}) is None


def test_gaston_flag_only_reports_no_invented_dollar_amount():
    """Gaston publishes LUV_YES_NO as a bare Y/N — the rollback lien is known to
    exist but its size is not published. _classify must not guess a number."""
    cfg = mod._RELIEF_LAYERS[("NC", "Gaston")]
    hit = mod._classify(cfg, {"LUV_YES_NO": "Y"})
    assert hit == {"kind": "use_value_deferral", "basis": "present_use_rollback_lien",
                   "deferred_value": None}
    assert mod._classify(cfg, {"LUV_YES_NO": "N"}) is None
    assert mod._classify(cfg, {"LUV_YES_NO": ""}) is None


def test_york_sc_homestead_and_farm_are_distinct_kinds():
    cfg = mod._RELIEF_LAYERS[("SC", "York")]
    homestead = mod._classify(cfg, {"HOMESTEAD": "Y", "LandUseDesc": "RESIDENTIAL"})
    assert homestead == {"kind": "homestead_exemption",
                          "basis": "sc_homestead_age65_disabled", "deferred_value": None}
    farm = mod._classify(cfg, {"HOMESTEAD": "N", "LandUseDesc": "FARM - CROPLAND"})
    assert farm == {"kind": "use_value_deferral", "basis": "sc_ag_use_value_rollback",
                     "deferred_value": None}
    assert mod._classify(cfg, {"HOMESTEAD": "N", "LandUseDesc": "RESIDENTIAL"}) is None


# --------------------------------------------------------------------------
# enrich_tax_relief — end to end, _query monkeypatched
# --------------------------------------------------------------------------

def test_stamps_tax_relief_on_a_matching_lead(monkeypatch):
    async def fake_query(http, url, where, out_fields=None, count=1):
        assert "Use_Value_Deferred" in where
        return [{"Use_Value_Deferred": "73300"}]

    monkeypatch.setattr(mod, "_query", fake_query)
    li = _lead(state="NC", county="Rutherford County", parcel_id="1234567890")
    stats = _run([li])
    assert stats == {"queried": 1, "tagged": 1}
    assert li.raw["tax_relief"] == {
        "kind": "use_value_deferral", "basis": "present_use_rollback_lien",
        "deferred_value": 73300.0, "county": "Rutherford",
    }
    # 2026-10-02 breadth fix: a use_value_deferral hit also promotes into
    # raw['rollback_exposure'] -- the key enrichment_rollback_deferral.py and the
    # county-signal coverage tracker actually read.
    re_block = li.raw["rollback_exposure"]
    assert re_block["deferred_value"] == 73300.0
    assert re_block["rollback_years"] == 4  # NC
    assert re_block["basis"] == "present_use_rollback_lien"
    assert re_block["county"] == "Rutherford" and re_block["state"] == "NC"
    # No invented tax rate: this layer carries a deferred VALUE, not a bill amount.
    assert re_block["annual_deferred_tax"] is None
    assert re_block["estimated_rollback"] is None
    assert re_block["tax_rate_source"] == "unavailable_no_bill_layer"


def test_senior_exemption_hit_does_not_promote_rollback_exposure(monkeypatch):
    """A senior/disabled/blind exemption is not a rollback liability -- only
    use_value_deferral hits should ever stamp raw['rollback_exposure']."""
    async def fake_query(http, url, where, out_fields=None, count=1):
        return [{"Exempt": "ELD"}]

    monkeypatch.setattr(mod, "_query", fake_query)
    li = _lead(state="NC", county="Buncombe", parcel_id="1234567890")
    stats = _run([li])
    assert stats == {"queried": 1, "tagged": 1}
    assert li.raw["tax_relief"]["kind"] == "elderly"
    assert "rollback_exposure" not in li.raw


def test_burke_use_value_deferral_reuses_henderson_shape():
    """Burke carries the identical schema as Henderson (same regional CAMA
    vendor) -- live-verified 2026-10-02: 1,560 real parcels, TOTAL_DEFERRED_VALUE
    a genuine dollar amount (not a flag)."""
    cfg = mod._RELIEF_LAYERS[("NC", "Burke")]
    hit = mod._classify(cfg, {"TOTAL_DEFERRED_VALUE": "225888"})
    assert hit == {"kind": "use_value_deferral", "basis": "present_use_rollback_lien",
                   "deferred_value": 225888.0}
    assert mod._classify(cfg, {"TOTAL_DEFERRED_VALUE": "0"}) is None


def test_lincoln_landeferred_is_a_flag_not_a_dollar_amount():
    """THE bug this config exists to prevent: Lincoln's LANDEFERRED reads -1 for
    every real deferred parcel (live-verified 2026-10-02, old FoxPro/dBase
    boolean-TRUE convention), never a real dollar figure. _classify must report
    the flag only, exactly like Gaston's LUV_YES_NO, and never treat -1 as $-1
    or as a magnitude."""
    cfg = mod._RELIEF_LAYERS[("NC", "Lincoln")]
    hit = mod._classify(cfg, {"LANDEFERRED": -1})
    assert hit == {"kind": "use_value_deferral", "basis": "present_use_rollback_lien",
                   "deferred_value": None}
    assert mod._classify(cfg, {"LANDEFERRED": 0}) is None
    assert mod._classify(cfg, {"LANDEFERRED": None}) is None


def test_lincoln_query_uses_the_insecure_tls_client(monkeypatch):
    """arcgisserver.lincolncountync.gov has an incomplete TLS chain -- the SAME
    host counties_nc.lincoln_code_violations.py already works around with a
    scoped verify=False client. Confirm enrich_tax_relief routes Lincoln's
    query through the insecure client, not the shared (verify=True) one."""
    from contextlib import asynccontextmanager

    created = []

    class _FakeClient:
        def __init__(self, *a, verify=True, **kw):
            self.verify = verify
            created.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeClient)

    seen = {"secure": [], "insecure": []}

    async def fake_query(http, url, where, out_fields=None, count=1):
        seen["insecure" if http.verify is False else "secure"].append(url)
        return [{"LANDEFERRED": -1}]

    monkeypatch.setattr(mod, "_query", fake_query)
    li = _lead(state="NC", county="Lincoln", parcel_id="2646891349")
    stats = _run([li])
    assert stats == {"queried": 1, "tagged": 1}
    assert seen["insecure"] and not seen["secure"]
    # Both clients are always opened (cheap: httpx doesn't connect until first
    # request), one per verify mode.
    assert {c.verify for c in created} == {True, False}


def test_no_query_hit_leaves_the_lead_untagged(monkeypatch):
    async def fake_query(http, url, where, out_fields=None, count=1):
        return []

    monkeypatch.setattr(mod, "_query", fake_query)
    li = _lead(state="NC", county="Rutherford", parcel_id="1234567890")
    stats = _run([li])
    assert stats == {"queried": 1, "tagged": 0}
    assert "tax_relief" not in (li.raw or {})


def test_uncovered_county_is_never_queried(monkeypatch):
    calls = {"n": 0}

    async def fake_query(http, url, where, out_fields=None, count=1):
        calls["n"] += 1
        return []

    monkeypatch.setattr(mod, "_query", fake_query)
    li = _lead(state="SC", county="Spartanburg", parcel_id="1234567890")
    stats = _run([li])
    assert stats == {"queried": 0, "tagged": 0}
    assert calls["n"] == 0


def test_lead_without_a_parcel_id_is_never_queried(monkeypatch):
    calls = {"n": 0}

    async def fake_query(http, url, where, out_fields=None, count=1):
        calls["n"] += 1
        return []

    monkeypatch.setattr(mod, "_query", fake_query)
    li = _lead(state="NC", county="Buncombe", parcel_id=None)
    stats = _run([li])
    assert stats == {"queried": 0, "tagged": 0}
    assert calls["n"] == 0


def test_already_tagged_lead_is_not_requeried(monkeypatch):
    calls = {"n": 0}

    async def fake_query(http, url, where, out_fields=None, count=1):
        calls["n"] += 1
        return [{"Exempt": "ELD"}]

    monkeypatch.setattr(mod, "_query", fake_query)
    li = _lead(state="NC", county="Buncombe", parcel_id="1234567890",
               raw={"tax_relief": {"kind": "elderly"}})
    stats = _run([li])
    assert stats == {"queried": 0, "tagged": 0}
    assert calls["n"] == 0


def test_kill_switch_short_circuits(monkeypatch):
    calls = {"n": 0}

    async def fake_query(http, url, where, out_fields=None, count=1):
        calls["n"] += 1
        return [{"Exempt": "ELD"}]

    monkeypatch.setattr(mod, "_query", fake_query)
    monkeypatch.setenv("FORECLOSURE_TAX_RELIEF", "0")
    li = _lead(state="NC", county="Buncombe", parcel_id="1234567890")
    stats = _run([li])
    assert stats == {"queried": 0, "tagged": 0}
    assert calls["n"] == 0


def test_max_queries_caps_the_batch(monkeypatch):
    async def fake_query(http, url, where, out_fields=None, count=1):
        return []

    monkeypatch.setattr(mod, "_query", fake_query)
    leads = [_lead(state="NC", county="Buncombe", parcel_id=str(i) * 10)
             for i in range(1, 6)]
    stats = _run(leads, max_queries=2)
    assert stats["queried"] == 2


# --------------------------------------------------------------------------
# Publish-slim coverage (the class of bug tests/test_raw_keep_covers_enrichers.py
# guards against generically; pinned directly here too since this key sits next
# to rollback_exposure in RAW_KEEP and both describe the same rollback-on-sale
# liability).
# --------------------------------------------------------------------------

def test_tax_relief_key_is_registered_in_raw_keep():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "tax_relief" in RAW_KEEP
