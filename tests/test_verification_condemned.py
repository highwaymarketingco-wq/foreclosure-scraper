"""The five `condemned` (vacant_structure) verifiers added in the 2026-11-16 round-6 gap-matrix
sweep (see condemned_adl.py's module docstring for the shared investigation context, and
condemned_charlotte.py's for the keyword-matching bug this testing pass itself found and fixed
before any of this was captured).

What this pins, per module:
  * applies(): recognizes the one real producer source it owns, and only rows carrying a
    truthy raw['condemned']; never another module's source, never a falsy/missing flag.
  * every verdict shown below against REAL captured responses
    (tests/fixtures/verification/condemned.json.gz: all 18 requests captured 2026-11-16 through
    the real Fetcher, from the exact five real sampled board rows per module this file encodes
    -- byte-identical to what one real sweep run against these rows would ask).
  * the condemned_charlotte regression this investigation found: a decision scoped to only the
    first 8 returned features (rather than every one) would wrongly call "5601 PAW CREEK RD"
    and "2329 SANDERS AV" stale when each genuinely has an open, FOF-ordered case further down
    an address with well over 8 total historical cases on file.
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
from foreclosure_scraper.verification.verifiers import condemned_adl as adl
from foreclosure_scraper.verification.verifiers import condemned_charlotte as cha
from foreclosure_scraper.verification.verifiers import condemned_greenwood as gwd
from foreclosure_scraper.verification.verifiers import condemned_rocky_mount as rmt
from foreclosure_scraper.verification.verifiers import condemned_spartanburg as spt

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


def _row(source: str, address: str, parcel_id: str | None, county: str, state: str,
        condemned: bool = True, **kw) -> dict:
    row = {"state": state, "county": county, "street_address": address, "parcel_id": parcel_id,
          "source": source, "raw": {"condemned": condemned}}
    row.update(kw)
    return row


def _check(mod, row: dict):
    return run(mod.verify(row, ReplayFetcher(RESP)))


# --------------------------------------------------------------------------- #
# contract                                                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mod,ttl,retry", [
    (adl, 30, 7), (cha, 30, 7), (rmt, 60, 14), (spt, 30, 7), (gwd, 30, 7),
])
def test_discovered_with_contract(mod, ttl, retry):
    vs = {v.name: v for v in discover()}
    v = vs[mod.__name__.rsplit(".", 1)[-1]]
    assert (v.signal, v.ttl_days, v.retry_days) == ("vacant_structure", ttl, retry)
    assert v.governs == ()          # bare raw['condemned'] has no provenance to clear


# --------------------------------------------------------------------------- #
# applies()                                                                   #
# --------------------------------------------------------------------------- #

def test_adl_applies_only_its_slug_and_condemned_true():
    row = _row("counties_generic.arcgis_distress.rockhill_code_demolition", "801 HARRISON ST",
              "6002104006", "York", "SC")
    assert adl.applies(row) is True
    assert adl.applies({**row, "raw": {"condemned": False}}) is False
    assert adl.applies({**row, "raw": {}}) is False
    other = _row("counties_generic.arcgis_distress.rockhill_code_housing", "1 MAIN ST",
                 None, "York", "SC")
    assert adl.applies(other) is False            # not an opted-in condemned=True slug
    assert adl.applies(_row("city_websites.charlotte_open_data", "1 MAIN ST", None,
                            "Mecklenburg", "NC")) is False


def test_charlotte_applies_only_its_source_and_condemned_true():
    row = _row("city_websites.charlotte_open_data", "2229 HIGHLAND ST", "06706307",
              "Mecklenburg", "NC")
    assert cha.applies(row) is True
    assert cha.applies({**row, "raw": {"condemned": False}}) is False
    assert cha.applies({**row, "source": "counties_nc.gastonia_code_enforcement"}) is False


def test_rocky_mount_applies_only_its_source_and_known_county():
    row = _row("counties_generic.arcgis_distress.rocky_mount_blight_survey_2025", "806 LONG AVE",
              "3759-86-6196", "Edgecombe", "NC")
    assert rmt.applies(row) is True
    assert rmt.applies({**row, "county": "Nash"}) is True
    assert rmt.applies({**row, "county": "Wilson"}) is False     # not one of the two survey counties
    assert rmt.applies({**row, "raw": {"condemned": False}}) is False
    assert rmt.applies({**row, "source": "counties_nc.edgecombe_tax_foreclosure"}) is False


def test_spartanburg_applies_only_its_source_and_condemned_true():
    row = _row("counties_sc.spartanburg_condemned", "2468 SUGAR RIDGE RD", "6196-36-6127.12",
              "Spartanburg", "SC")
    assert spt.applies(row) is True
    assert spt.applies({**row, "raw": {"condemned": False}}) is False
    assert spt.applies({**row, "source": "counties_sc.spartanburg_city_condemned"}) is False


def test_greenwood_applies_only_its_source_and_condemned_true():
    row = _row("counties_generic.arcgis_distress.greenwood_cama_condemned", "117 MADDOX RD",
              "6913-876-159", "Greenwood", "SC")
    assert gwd.applies(row) is True
    assert gwd.applies({**row, "raw": {"condemned": False}}) is False
    # a NEIGHBORING arcgis_distress slug on the SAME service family must not be claimed
    assert gwd.applies({**row, "source": "counties_generic.arcgis_distress.spartanburg_city_tax_sale"}) is False


# --------------------------------------------------------------------------- #
# verify() -- real captured responses, real sampled rows (2026-11-16)        #
# --------------------------------------------------------------------------- #

def test_adl_refuted_when_no_longer_on_the_demolition_layer():
    row = _row("counties_generic.arcgis_distress.rockhill_code_demolition", "505 BYNUM AV",
              "5980701006", "York", "SC")
    res = _check(adl, row)
    assert res.verdict == "refuted"
    assert res.evidence["reason"] == "no_case_on_layer"
    assert res.evidence["layer_count"] == 17


def test_adl_confirmed_when_still_open_on_the_demolition_layer():
    row = _row("counties_generic.arcgis_distress.rockhill_code_demolition", "801 HARRISON ST",
              "6002104006", "York", "SC")
    res = _check(adl, row)
    assert res.verdict == "confirmed"
    assert res.evidence["cases"][0]["open"] is True


def test_charlotte_stale_when_every_case_now_closed():
    row = _row("city_websites.charlotte_open_data", "2601 ABELWOOD RD", "06916309",
              "Mecklenburg", "NC")
    res = _check(cha, row)
    assert res.verdict == "stale"
    assert res.evidence["cases_matched"] == 12
    assert all(not c["fof_ordered"] for c in res.evidence["cases"])


def test_charlotte_confirmed_second_real_address():
    """A second real sampled Mecklenburg row -- 5601 PAW CREEK RD, 12 total historical cases,
    one (20210015439) still open/FOF-ordered. The investigation's own BUG FOUND section (this
    module's docstring) found this exact address wrongly called `stale` under the original,
    too-broad `_street_keywords()` query ("CREEK" alone, 2,000 unrelated matches, the true
    match sorted past the old feats[:8] decision scope); the fixed full-street-text query
    narrows to these same 12 real cases, where the open one is well within reach either way."""
    row = _row("city_websites.charlotte_open_data", "5601 PAW CREEK RD", "05913125",
              "Mecklenburg", "NC")
    res = _check(cha, row)
    assert res.verdict == "confirmed"
    assert res.evidence["cases_matched"] == 12
    assert any(c["case_number"] == "20210015439" and c["fof_ordered"]
              for c in res.evidence["cases"])


def test_charlotte_confirmed_small_case_count():
    row = _row("city_websites.charlotte_open_data", "2229 HIGHLAND ST", "06706307",
              "Mecklenburg", "NC")
    res = _check(cha, row)
    assert res.verdict == "confirmed"
    assert any(c["case_number"] == "20210060969" and c["fof_ordered"] for c in res.evidence["cases"])


def test_rocky_mount_confirmed_edgecombe():
    row = _row("counties_generic.arcgis_distress.rocky_mount_blight_survey_2025", "806 LONG AVE",
              "3759-86-6196", "Edgecombe", "NC")
    res = _check(rmt, row)
    assert res.verdict == "confirmed"
    assert res.evidence["matched"]["SITEADD"] == "806 LONG AVE"


def test_rocky_mount_confirmed_matches_by_parcel_not_address_text():
    """A second real sampled Edgecombe row, different street, same layer snapshot (one load
    serves every row of the same sweep run)."""
    row = _row("counties_generic.arcgis_distress.rocky_mount_blight_survey_2025",
              "1004 BLANDWOOD DR", "3759-92-1125", "Edgecombe", "NC")
    res = _check(rmt, row)
    assert res.verdict == "confirmed"
    assert res.evidence["matched"]["PARNO"] == "3759-92-1125"


def test_rocky_mount_unconfirmed_without_identity():
    row = _row("counties_generic.arcgis_distress.rocky_mount_blight_survey_2025", None, None,
              "Edgecombe", "NC")
    res = _check(rmt, row)
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "no_identity"


def test_spartanburg_confirmed_still_dl():
    row = _row("counties_sc.spartanburg_condemned", "2468 SUGAR RIDGE RD", "6196-36-6127.12",
              "Spartanburg", "SC")
    res = _check(spt, row)
    assert res.verdict == "confirmed"
    assert res.evidence["cards"][0]["condition_factor"] == "DL"


def test_spartanburg_stale_reassessed_to_very_poor():
    row = _row("counties_sc.spartanburg_condemned", "1365 BOILING SPRINGS RD",
              "7115-62-8793.48", "Spartanburg", "SC")
    res = _check(spt, row)
    assert res.verdict == "stale"
    assert res.evidence["cards"][0]["condition_factor"] == "VP"


def test_spartanburg_stale_condition_now_blank():
    row = _row("counties_sc.spartanburg_condemned", "581 CANAAN RD", "7121-22-3850.56",
              "Spartanburg", "SC")
    res = _check(spt, row)
    assert res.verdict == "stale"
    assert res.evidence["cards"][0]["condition_factor"] is None


def test_spartanburg_unconfirmed_without_identity():
    row = _row("counties_sc.spartanburg_condemned", None, None, "Spartanburg", "SC")
    res = _check(spt, row)
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "no_identity"


def test_greenwood_confirmed_still_badly_worn():
    row = _row("counties_generic.arcgis_distress.greenwood_cama_condemned", "117 MADDOX RD",
              "6913-876-159", "Greenwood", "SC")
    res = _check(gwd, row)
    assert res.verdict == "confirmed"
    assert res.evidence["cards"][0]["condition_text"] == "Badly Worn"


def test_greenwood_confirmed_second_sampled_parcel():
    row = _row("counties_generic.arcgis_distress.greenwood_cama_condemned", "1 LEE ST",
              "6923-507-677", "Greenwood", "SC")
    res = _check(gwd, row)
    assert res.verdict == "confirmed"


def test_greenwood_unconfirmed_without_identity():
    row = _row("counties_generic.arcgis_distress.greenwood_cama_condemned", None, None,
              "Greenwood", "SC")
    res = _check(gwd, row)
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "no_identity"


def test_greenwood_is_severe_matches_compound_values():
    assert gwd._is_severe("Badly Worn") is True
    assert gwd._is_severe("Badly Worn/Average") is True
    assert gwd._is_severe("Worn Out/Badly Worn") is True
    assert gwd._is_severe("Average") is False
    assert gwd._is_severe(None) is False
