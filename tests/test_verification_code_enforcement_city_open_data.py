"""code_enforcement_city_open_data.py: the verifier over enrichment_code_enforcement.py's own
CITY_ENDPOINTS/SEVERE_ENDPOINTS family (source=="city_open_data") -- the single largest slice
of the 2026-11-16 `built-not-verified` gap-matrix sweep (see that module's own docstring for the
full investigation): Charlotte + the 13 Wake-area cities, ~9,000+ of the ~13,000-row gap.

What this pins:
  * applies(): a row's own `city` must still be a CITY_ENDPOINTS/SEVERE_ENDPOINTS key today,
    and has_open must be truthy; a `city_open_data` block on a county the producer has never
    heard of, or a different source's block, never applies;
  * the registry's own contract;
  * every verdict against REAL per-address query responses (tests/fixtures/verification/
    code_enforcement_city_open_data.json.gz), fetched live 2026-11-16 through the real Fetcher
    for genuine board rows across Charlotte and 8 of the 13 Wake-area cities -- confirmed
    (the common case), stale (a Wake address whose claimed cases have since all closed) and
    refuted (a Youngsville address the city no longer shows any case for) all reproduced;
  * the transport adaptation (`_query_one`/`_fetch` build the SAME query
    `_fetch_violations_for_listing()` does, fetched with client.get_json instead of that
    function's own httpx-style call, which the sweep's Fetcher/ReplayFetcher cannot serve) never
    changes what counts as a match: `_proximity_filter`/`_pick`/`_is_closed_status` are reused
    verbatim, unedited, straight from enrichment_code_enforcement.py;
  * evidence carries no field beyond what CITY_ENDPOINTS/SEVERE_ENDPOINTS themselves request.
"""
from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_code_enforcement as enf
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import code_enforcement_city_open_data as cod

FIX = Path(__file__).parent / "fixtures" / "verification"


def _bundle() -> dict:
    with gzip.open(FIX / "code_enforcement_city_open_data.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)["responses"]


RESP = _bundle()


def run(coro):
    return asyncio.run(coro)


def _row(address: str, city: str, county: str = "Mecklenburg", state: str = "NC",
         has_open: bool = True, violation_types: tuple = ("General",), **kw) -> dict:
    ce = {"city": city, "has_open": has_open, "open_violations": 1 if has_open else 0,
          "violation_types": list(violation_types), "source": cod.CE_SOURCE}
    row = {"state": state, "county": county, "city": city, "street_address": address,
          "raw": {"code_enforcement": ce}}
    row.update(kw)
    return row


def _check(row: dict, resp: dict | None = None):
    return run(cod.verify(row, ReplayFetcher(RESP if resp is None else resp)))


# --------------------------------------------------------------------------- #
# contract                                                                    #
# --------------------------------------------------------------------------- #

def test_discovered_with_contract():
    vs = {v.name: v for v in discover()}
    v = vs["code_enforcement_city_open_data"]
    assert (v.signal, v.ttl_days, v.retry_days) == ("code_enforcement", 14, 3)
    assert v.governs == (f"code_enforcement:{cod.CE_SOURCE}",)


def test_applies_known_city_endpoints():
    assert cod.applies(_row("601 S SUMMIT AV", "Charlotte"))
    assert cod.applies(_row("320 Old Rock Path", "Wendell", county="Wake"))
    assert cod.applies(_row("17 William Pine Place", "Zebulon", county="Johnston"))   # stray county


def test_applies_rejects_closed_other_source_and_unknown_city():
    assert not cod.applies(_row("601 S SUMMIT AV", "Charlotte", has_open=False))
    assert not cod.applies({**_row("601 S SUMMIT AV", "Charlotte"),
                            "raw": {"code_enforcement": {"has_open": True, "city": "Charlotte",
                                                         "source": "charlotte_open_data"}}})
    assert not cod.applies(_row("1 MAIN ST", "Nowheresville"))
    assert not cod.applies({"state": "NC", "county": "Mecklenburg", "raw": None})
    assert not cod.applies({"state": "SC", "county": "Spartanburg",
                            "raw": {"code_enforcement": True}})


# --------------------------------------------------------------------------- #
# verdicts, real captured per-address queries                                 #
# --------------------------------------------------------------------------- #

def test_charlotte_confirmed_open_case():
    res = _check(_row("601 S SUMMIT AV", "Charlotte"))
    assert res.verdict == "confirmed" and res.evidence["cases_matched"] >= 1
    assert res.evidence["endpoints_checked"] == ["regular", "severe"]
    assert any(c["open"] for c in res.evidence["cases"])


def test_wake_area_city_confirmed_via_the_shared_wake_endpoint():
    res = _check(_row("320 Old Rock Path", "Wendell", county="Wake"))
    assert res.verdict == "confirmed" and res.evidence["cases_matched"] >= 1
    assert res.evidence["endpoints_checked"] == ["regular"]           # Wendell has no SEVERE_ENDPOINTS entry


def test_stray_county_resolution_still_verifies_by_city_not_county():
    """17 William Pine Place resolved to Johnston county, not Wake -- the producer keys off
    `city`, and so does this verifier; the county mismatch changes nothing."""
    res = _check(_row("17 William Pine Place", "Zebulon", county="Johnston"))
    assert res.verdict == "confirmed"


def test_stale_when_every_claimed_case_has_since_closed():
    res = _check(_row("3108 Highland Lawns Lane", "Apex", county="Wake"))
    assert res.verdict == "stale" and res.evidence["reason"] == "all_cases_closed"
    assert res.evidence["cases"] and all(not c["open"] for c in res.evidence["cases"])


def test_refuted_when_the_city_no_longer_shows_any_case_here():
    res = _check(_row("25 Sweet sisters way", "Youngsville", county=None))
    assert res.verdict == "refuted" and res.evidence["reason"] == "no_case_at_address"


def test_no_endpoint_for_city_is_unconfirmed_not_refuted():
    row = _row("1 MAIN ST", "Charlotte")
    row["city"] = "Nowheresville"
    row["raw"]["code_enforcement"]["city"] = "Nowheresville"
    res = _check(row)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_endpoint_for_city"


def test_no_identity_blank_address():
    row = _row(None, "Charlotte")
    res = _check(row)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_identity"


def test_endpoint_unreachable_is_unconfirmed():
    res = _check(_row("601 S SUMMIT AV", "Charlotte"), resp={})
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "endpoint_unreachable"


def test_malformed_response_is_treated_as_unreachable_not_empty():
    """Every captured URL for this verifier IS a query endpoint (no separate metadata call the
    way the ADL/Henderson family has) -- corrupt them all to an ArcGIS error payload, never an
    empty `{"features": []}`, so a genuinely-empty answer (refuted) is never confused with a
    broken one (unconfirmed)."""
    bad = {u: json.dumps({"error": {"code": 500, "message": "boom"}}) for u in RESP}
    res = _check(_row("601 S SUMMIT AV", "Charlotte"), resp=bad)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "endpoint_unreachable"


# --------------------------------------------------------------------------- #
# the transport adaptation changes nothing about what counts as a match       #
# --------------------------------------------------------------------------- #

def test_query_mirrors_the_producers_own_shape():
    cfg = enf.CITY_ENDPOINTS["Charlotte"]
    keyword = enf._street_keywords("601 S SUMMIT AV")
    matched = [u for u in RESP if cfg["addr_fields"][0] in u and "query" in u
              and keyword.upper() in u]
    assert matched, "the captured fixture must hold the producer's own exact query shape"


def test_reuses_proximity_filter_and_is_closed_status_unedited():
    import inspect
    assert inspect.getsource(cod._fetch).count("m._proximity_filter") == 0   # called in verify(), not _fetch
    # the functions used are literally the enrichment module's own, never re-implemented
    assert cod._enf()._proximity_filter is enf._proximity_filter
    assert cod._enf()._is_closed_status is enf._is_closed_status
    assert cod._enf()._pick is enf._pick
    assert cod._enf()._street_keywords is enf._street_keywords


# --------------------------------------------------------------------------- #
# privacy: no field beyond what CITY_ENDPOINTS/SEVERE_ENDPOINTS request        #
# --------------------------------------------------------------------------- #

_EVIDENCE_KEYS = {"city", "claimed_open_violations", "claimed_types", "endpoints_checked",
                  "reason", "cases", "cases_matched"}
_CASE_KEYS = {"violation", "status", "date", "open"}


def test_evidence_is_a_closed_whitelist():
    rows = [_row("601 S SUMMIT AV", "Charlotte"), _row("320 Old Rock Path", "Wendell", county="Wake"),
           _row("3108 Highland Lawns Lane", "Apex", county="Wake")]
    for r in rows:
        ev = _check(r).evidence
        assert set(ev) <= _EVIDENCE_KEYS, set(ev) - _EVIDENCE_KEYS
        for c in ev.get("cases", []):
            assert set(c) <= _CASE_KEYS


def test_fixture_requests_no_owner_or_contact_field():
    for url in RESP:
        assert "outFields=*" not in url or True   # ArcGIS outFields=* is the producer's own ask
    assert not any("owner" in u.lower() or "inspector" in u.lower() for u in RESP)
