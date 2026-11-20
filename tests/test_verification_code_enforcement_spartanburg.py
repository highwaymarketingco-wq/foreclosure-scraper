"""code_enforcement_spartanburg.py: the sibling verifier over counties_sc.spartanburg_condemned's
own bare `raw["code_enforcement"] = True` write -- the SAME bug class as
elderly_disabled_sc_homestead.py's (2026-11-19) and code_enforcement_gastonia.py's (round 72)
fixes: a verifier whose scope is narrower than the real, live, wired producer set. Every existing
code_enforcement verifier required a dict-shaped block (adl/city_open_data/henderson/gastonia all
call `isinstance(ce, dict)` first), so none of them ever recognized this producer's bare boolean,
leaving 843 real Spartanburg SC `code_enforcement` hit rows (confirmed live via
board_stream.iter_board_rows() on the 2026-11-19 board) `built-not-verified (source status
unknown)` in gap_matrix.py however long the scraper ran.

This module delegates its live check to condemned_spartanburg.verify() byte-for-byte (same
producer, same parcel-level ConditionFactor='DL' claim, just a different ledger), so this file
reuses that module's own real, previously-captured response fixture
(tests/fixtures/verification/condemned.json.gz) rather than capturing anything new: the request
URL this module's delegation produces is byte-identical to condemned_spartanburg.py's own
(identical SERVICE_URL/FIELDS/where-clause shape -- the ReplayFetcher matches on URL alone), so
replaying the SAME four real 2026-11-16 sampled parcels proves the delegation actually reaches
the real service shape, not a mocked stand-in.

What this pins:
  * the registry's own contract (signal="code_enforcement", ttl=30, retry=7, governs=() --
    the bare-boolean raw["code_enforcement"] has no per-source provenance to clear selectively,
    same reasoning condemned_spartanburg.py's own docstring gives for omitting GOVERNS);
  * applies(): SC Spartanburg rows from this exact producer whose block is bare `True`; rejects
    wrong state/county, the sibling spartanburg_city_condemned.py's dict-shaped block (the
    documented NOT COVERED PDF source), a falsy/missing flag, and a trailing " county" suffix
    is tolerated (same convention code_enforcement_gastonia.py's applies() already uses);
  * every verdict against the REAL captured response (same fixture, same real parcels
    condemned_spartanburg.py's own tests already pin): confirmed (still 'DL'), stale (reassessed
    to 'VP', and separately a now-blank condition), unconfirmed (no parcel id/address at all);
  * the delegated result is correctly RE-LABELED under this module's own SIGNAL/SOURCE/verifier
    name, never condemned_spartanburg's.
"""
from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import _arcgis_layer as agl
from foreclosure_scraper.verification.verifiers import code_enforcement_spartanburg as ces

FIX = Path(__file__).parent / "fixtures" / "verification"


def _bundle() -> dict:
    with gzip.open(FIX / "condemned.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)["responses"]


RESP = _bundle()


@pytest.fixture(autouse=True)
def _no_run_cache():
    agl._RUNS.clear()


def run(coro):
    return asyncio.run(coro)


def _row(address: str | None, parcel_id: str | None, *, county: str = "Spartanburg",
         state: str = "SC", source: str | None = ces.ROW_SOURCE, ce=True, **kw) -> dict:
    row = {"state": state, "county": county, "street_address": address, "parcel_id": parcel_id,
          "source": source, "raw": {"code_enforcement": ce}}
    row.update(kw)
    return row


def _check(row: dict):
    return run(ces.verify(row, ReplayFetcher(RESP)))


# --------------------------------------------------------------------------- #
# contract                                                                    #
# --------------------------------------------------------------------------- #

def test_discovered_with_contract():
    vs = {v.name: v for v in discover()}
    v = vs["code_enforcement_spartanburg"]
    assert (v.signal, v.ttl_days, v.retry_days) == ("code_enforcement", 30, 7)
    assert v.governs == ()
    assert v.identity == "property"


# --------------------------------------------------------------------------- #
# applies()                                                                   #
# --------------------------------------------------------------------------- #

def test_applies_sc_spartanburg_this_source_bare_true():
    row = _row("2468 SUGAR RIDGE RD", "6196-36-6127.12")
    assert ces.applies(row) is True


def test_applies_tolerates_trailing_county_suffix():
    row = _row("2468 SUGAR RIDGE RD", "6196-36-6127.12", county="Spartanburg County")
    assert ces.applies(row) is True


def test_applies_rejects_wrong_state_county_source_or_shape():
    base = _row("2468 SUGAR RIDGE RD", "6196-36-6127.12")
    assert ces.applies({**base, "state": "NC"}) is False
    assert ces.applies({**base, "county": "Greenville"}) is False
    assert ces.applies({**base, "source": "counties_sc.spartanburg_city_condemned"}) is False
    assert ces.applies({**base, "raw": {"code_enforcement": False}}) is False
    assert ces.applies({**base, "raw": {}}) is False
    assert ces.applies({**base, "raw": None}) is False


def test_applies_rejects_the_dict_shaped_city_pdf_block_not_guessed():
    """spartanburg_city_condemned.py's own dict-shaped block (the documented NOT COVERED PDF
    source) must never be treated as this module's bare-True shape, even though it also sets
    raw['condemned']=True and is also, by coincidence, Spartanburg County."""
    ce = {"has_open": True, "severe": True, "condemned": True,
         "source": "spartanburg_city_master_condemnation_list"}
    row = _row("123 MAIN ST", "7-12-09-058.11",
              source="counties_sc.spartanburg_city_condemned", ce=ce)
    assert ces.applies(row) is False


# --------------------------------------------------------------------------- #
# verdicts (delegated to condemned_spartanburg.verify(), real captured fixture)
# --------------------------------------------------------------------------- #

def test_confirmed_when_cama_still_reads_dl():
    row = _row("2468 SUGAR RIDGE RD", "6196-36-6127.12")
    res = _check(row)
    assert res.verdict == "confirmed"
    assert res.signal == "code_enforcement"
    assert res.verifier == "code_enforcement_spartanburg"
    assert res.source == ces.SOURCE
    assert res.evidence["cards"][0]["condition_factor"] == "DL"


def test_stale_when_reassessed_to_very_poor():
    row = _row("1365 BOILING SPRINGS RD", "7115-62-8793.48")
    res = _check(row)
    assert res.verdict == "stale"
    assert res.evidence["cards"][0]["condition_factor"] == "VP"


def test_stale_when_condition_now_blank():
    row = _row("581 CANAAN RD", "7121-22-3850.56")
    res = _check(row)
    assert res.verdict == "stale"
    assert res.evidence["cards"][0]["condition_factor"] is None


def test_unconfirmed_without_identity():
    row = _row(None, None)
    res = _check(row)
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "no_identity"


def test_relabels_under_its_own_signal_never_vacant_structures():
    """The delegated call must come back filed under THIS module's signal/source/verifier, not
    condemned_spartanburg's own -- a sweep run keys its ledger write on the verifier's own
    declared SIGNAL (core.Verifier.signal), so a mislabeled result would silently write into
    the wrong ledger file."""
    row = _row("2468 SUGAR RIDGE RD", "6196-36-6127.12")
    res = _check(row)
    assert res.signal == "code_enforcement"
    assert res.signal != "vacant_structure"
