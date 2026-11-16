"""code_enforcement_adl.py: the generic verifier over every arcgis_distress_layers.py
process=="code_enforcement" Layer (Lincoln's own standalone archive scraper included), the
second-largest slice of the 2026-11-16 `built-not-verified` gap-matrix sweep (see that module's
own docstring for the full investigation).

What this pins:
  * applies(): recognizes every slug `_layers()` names today (Lincoln x2, Durham, Richland,
    York x2), never Henderson's own OVT slug (no overlap within the shared SIGNAL), never a
    block with has_open falsy or an unrecognized source;
  * the registry's own contract (SIGNAL/TTL/GOVERNS-via-governs_for);
  * every verdict against REAL captured responses, one real full-layer load per slug
    (tests/fixtures/verification/code_enforcement_adl.json.gz: Lincoln's two write-paths,
    Durham, Richland, York's two sub-layers, each fetched live 2026-11-16 through the real
    Fetcher exactly as one sweep run would, byte-identical to its own --capture-dir);
  * the shared `_arcgis_layer.load_layer()` pagination-offset fix this investigation found
    (Lincoln's own service caps every page at 1,000 features however large resultRecordCount
    asks for; the old offset=i*page skipped rows 1,000-1,999 of 3,465 every single load) --
    Lincoln's layer loads COMPLETE and decisive here, not merely "unconfirmed forever";
  * governs_for() ends only the ONE matched slug's own block, never another source's identically
    named signal on a merged row;
  * evidence carries no field beyond what each Layer's own, already-privacy-reviewed `fields`
    tuple requests.
"""
from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path

import pytest

from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import _arcgis_layer as agl
from foreclosure_scraper.verification.verifiers import code_enforcement_adl as adl
from foreclosure_scraper.verification.verifiers import code_enforcement_henderson as ovt

FIX = Path(__file__).parent / "fixtures" / "verification"


def _bundle() -> dict:
    with gzip.open(FIX / "code_enforcement_adl.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)["responses"]


RESP = _bundle()


@pytest.fixture(autouse=True)
def _no_run_cache():
    agl._RUNS.clear()


def run(coro):
    return asyncio.run(coro)


def _row(source: str, address: str, county: str = "Lincoln", state: str = "NC",
         has_open: bool = True, **kw) -> dict:
    ce = {"county": county, "has_open": has_open, "source": source}
    row = {"state": state, "county": county, "street_address": address, "raw": {"code_enforcement": ce}}
    row.update(kw)
    return row


def _check(row: dict, resp: dict | None = None):
    return run(adl.verify(row, ReplayFetcher(RESP if resp is None else resp)))


# --------------------------------------------------------------------------- #
# contract                                                                    #
# --------------------------------------------------------------------------- #

def test_discovered_with_contract():
    vs = {v.name: v for v in discover()}
    v = vs["code_enforcement_adl"]
    assert (v.signal, v.ttl_days, v.retry_days) == ("code_enforcement", 14, 3)
    assert v.governs == ()                       # per-record only, via governs_for
    assert v.governs_fn is adl.governs_for


def test_applies_recognizes_every_current_slug():
    for slug, county in (("lincoln_code_violations", "Lincoln"),
                         ("lincoln_county_code_violations_archive", "Lincoln"),
                         ("durham_open_code_violations", "Durham"),
                         ("columbia_code_vacant_boarded", "Richland"),
                         ("rockhill_code_housing", "York"),
                         ("rockhill_code_exterior_major", "York")):
        assert adl.applies(_row(slug, "1 MAIN ST", county=county)), slug


def test_applies_rejects_henderson_and_unknown_and_closed():
    assert not adl.applies(_row(ovt.CE_SOURCE, "1 MAIN ST", county="Henderson"))
    assert not adl.applies(_row("some_future_producer", "1 MAIN ST"))
    assert not adl.applies(_row("lincoln_code_violations", "1 MAIN ST", has_open=False))
    assert not adl.applies({"state": "NC", "county": "Lincoln", "raw": None})
    assert not adl.applies({"state": "NC", "county": "Lincoln", "raw": {"code_enforcement": True}})


def test_applies_never_overlaps_hendersons_own_verifier():
    row = _row(ovt.CE_SOURCE, "23 MONO LN", county="Henderson")
    row["parcel_id"] = "9681135571"
    assert ovt.applies(row) and not adl.applies(row)


# --------------------------------------------------------------------------- #
# verdicts, real captured layers                                             #
# --------------------------------------------------------------------------- #

def test_lincoln_confirmed_open_case():
    res = _check(_row("lincoln_code_violations", "8167 Optimist Club Road"))
    assert res.verdict == "confirmed" and res.evidence["cases_matched"] >= 1
    assert res.evidence["matched_slug"] == "lincoln_code_violations"
    assert all(c["open"] for c in res.evidence["cases"] if c["open"])


def test_lincoln_archive_confirmed_same_physical_layer():
    """The archive scraper's own source tag reads the IDENTICAL Lincoln layer."""
    res = _check(_row("lincoln_county_code_violations_archive", "7864 Cove Side Dr"))
    assert res.verdict == "confirmed"
    assert res.evidence["matched_slug"] == "lincoln_county_code_violations_archive"


def test_lincoln_layer_loads_complete_after_the_pagination_fix():
    res = _check(_row("lincoln_code_violations", "8167 Optimist Club Road"))
    assert res.evidence["layer_count"] == res.evidence["layer_rows_loaded"] == 3465


def test_richland_confirmed_vacant_boarded():
    res = _check(_row("columbia_code_vacant_boarded", "3131  LAKEWOOD Ave", county="Richland"))
    assert res.verdict == "confirmed" and res.evidence["cases_matched"] >= 1
    assert any(c.get("status", "").lower() in ("open", "in violation") for c in res.evidence["cases"])


def test_rockhill_exterior_major_confirmed():
    res = _check(_row("rockhill_code_exterior_major", "350 EBENEZER AV", county="York", state="SC"))
    assert res.verdict == "confirmed" and res.evidence["cases_matched"] == 1


def test_durham_refuted_when_case_has_closed_off_the_feed():
    """2907 Beechwood Dr: the board's static claim; the service's own feed (dataset name "Open
    ... Cases") simply no longer carries this address today -- live-confirmed by hand against
    the fresh 911-row reload (down from the board's own 947), not a matching bug."""
    res = _check(_row("durham_open_code_violations", "2907 BEECHWOOD DR", county="Durham"))
    assert res.verdict == "refuted" and res.evidence["reason"] == "no_case_on_layer"


def test_rockhill_housing_refuted_when_the_tiny_feed_has_moved_on():
    res = _check(_row("rockhill_code_housing", "1047 STONEWALL AV S", county="York", state="SC"))
    assert res.verdict == "refuted" and res.evidence["reason"] == "no_case_on_layer"


def test_bare_road_name_is_unconfirmed_never_guessed():
    """A real Lincoln row whose own street_address has no house number (county data gap, not a
    verifier bug -- the same _house_numbered discipline Henderson's own module applies)."""
    res = _check(_row("lincoln_code_violations", "MACE LN"))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_identity"


def test_no_identity_blank_address():
    res = _check(_row("lincoln_code_violations", None))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_identity"


def test_unknown_source_is_unconfirmed_not_refuted():
    res = _check(_row("a_future_layer_not_yet_in_the_registry", "1 MAIN ST"))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "unknown_source"


@pytest.mark.parametrize("damage,reason", [
    ("none", "layer_unavailable"),
    ("count0", "layer_empty"),
    ("count_more", "layer_incomplete"),
])
def test_a_bad_layer_is_never_decisive(damage, reason):
    lay = adl._layers()["durham_open_code_violations"]
    resp = dict(RESP)
    cnt = agl.count_url(lay.url)
    if damage == "none":
        resp = {u: b for u, b in resp.items() if "durhamnc" not in u}
    elif damage == "count0":
        resp[cnt] = json.dumps({"count": 0})
    elif damage == "count_more":
        resp[cnt] = json.dumps({"count": 99999})
    res = _check(_row("durham_open_code_violations", "2907 BEECHWOOD DR", county="Durham"), resp)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == reason


def test_one_layer_load_per_run_shared_across_rows():
    client = ReplayFetcher(RESP)
    rows = [_row("durham_open_code_violations", a, county="Durham")
           for a in ("2907 BEECHWOOD DR", "908 N ELIZABETH ST", "1906 TAYLOR ST")] * 3

    async def go():
        return await asyncio.gather(*(adl.verify(r, client) for r in rows))
    out = run(go())
    assert len(out) == 9
    durham_asked = [u for u in client.asked if "durhamnc" in u]
    assert len(durham_asked) == 3                 # meta, count, one page (911 rows < 2000)
    assert len(set(durham_asked)) == 3


# --------------------------------------------------------------------------- #
# governs_for: ends only the matched source's own block                       #
# --------------------------------------------------------------------------- #

def test_governs_for_names_only_the_matched_slug():
    res = _check(_row("durham_open_code_violations", "908 N ELIZABETH ST", county="Durham"))
    rec = {"evidence": res.evidence}
    assert adl.governs_for(rec) == ("code_enforcement:durham_open_code_violations",)


def test_governs_for_empty_without_a_matched_slug():
    assert adl.governs_for({"evidence": {}}) == ()
    assert adl.governs_for(None) == ()
    assert adl.governs_for("not a dict") == ()
    g = {v.name: v for v in discover() if v.signal == "code_enforcement"}["code_enforcement_adl"]
    rec = {"signal": "code_enforcement", "verdict": "refuted",
          "evidence": {"matched_slug": "columbia_code_vacant_boarded"}}
    assert g.governs_of(rec) == ("code_enforcement:columbia_code_vacant_boarded",)
    assert g.governs_of({"evidence": {}}) == ()


# --------------------------------------------------------------------------- #
# privacy: no field beyond each Layer's own requested fields                  #
# --------------------------------------------------------------------------- #

_EVIDENCE_KEYS = {"matched_slug", "layer", "fetched_at", "layer_count", "layer_rows_loaded",
                  "layer_data_last_edit", "layer_error", "reason", "cases", "cases_matched"}
_CASE_KEYS = {"violation", "status", "open"}


def test_evidence_is_a_closed_whitelist():
    rows = [_row("durham_open_code_violations", "908 N ELIZABETH ST", county="Durham"),
           _row("columbia_code_vacant_boarded", "3131  LAKEWOOD Ave", county="Richland"),
           _row("rockhill_code_exterior_major", "350 EBENEZER AV", county="York", state="SC"),
           _row("lincoln_code_violations", "8167 Optimist Club Road")]
    for r in rows:
        agl._RUNS.clear()
        ev = _check(r).evidence
        assert set(ev) <= _EVIDENCE_KEYS, set(ev) - _EVIDENCE_KEYS
        for c in ev.get("cases", []):
            assert set(c) <= _CASE_KEYS


def test_fixture_requests_no_owner_or_contact_column():
    for url in RESP:
        if "outFields" not in url:
            continue
        from urllib.parse import parse_qs, urlsplit
        fields = set(parse_qs(urlsplit(url).query).get("outFields", [""])[0].split(","))
        assert not any("owner" in f.lower() or "phone" in f.lower() or "email" in f.lower()
                      or "complainant" in f.lower() for f in fields), (url, fields)
