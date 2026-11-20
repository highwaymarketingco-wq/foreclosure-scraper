"""elderly_disabled_sc_homestead: the York/Lexington/Spartanburg CAMA layers against the rows
counties_sc.{york,lexington,spartanburg}_homestead.py source (made-up parcels, no network)."""
from __future__ import annotations

import asyncio
import json

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import elderly_disabled as buncombe
from foreclosure_scraper.verification.verifiers import elderly_disabled_sc_homestead as V

PID = "12345-01-001"


def _row(county="york", owner="SMITH, JOHN", **kw):
    r = {"state": "SC", "county": county, "parcel_id": PID, "owner_name": owner,
         "listing_type": "elderly_disabled", "source": f"counties_sc.{county}_homestead",
         "raw": {"gis_exempt": {"code": "HOMESTEAD", "tag": "sc_homestead_exemption"},
                "tax_relief": {"kind": "homestead_exemption", "basis": "sc_homestead_age65_disabled",
                              "deferred_value": None, "county": county.title()}}}
    r.update(kw)
    return r


def _layer_json(cfg: V._County, *, present: bool, owner: str = "SMITH, JOHN", id_field: str | None = None):
    id_field = id_field or cfg.id_fields[0]
    attrs = {id_field: PID, cfg.flag_field: cfg.flag_present if present else ("" if cfg.flag_field != "HomesteadNumber" else "A2")}
    for i, f in enumerate(cfg.owner_fields):
        attrs[f] = owner if i == 0 else None
    return json.dumps({"features": [{"attributes": attrs}]})


def _empty():
    return json.dumps({"features": []})


def _run(row, responses):
    f = ReplayFetcher(responses)
    return asyncio.run(V.verify(row, f)), f


def test_registered_and_shares_the_signal_without_overlapping_buncombes_applies():
    verifiers = {x.name: x for x in registry.discover()}
    v = verifiers["elderly_disabled_sc_homestead"]
    assert v.signal == "elderly_disabled" and v.governs and not v.wall
    # same SIGNAL as the Buncombe module, disjoint applies() (registry.py's own contract)
    assert verifiers["elderly_disabled"].signal == v.signal
    nc_row = {"state": "NC", "county": "Buncombe", "listing_type": "elderly_disabled", "raw": {}}
    sc_row = _row()
    assert buncombe.applies(nc_row) and not V.applies(nc_row)
    assert V.applies(sc_row) and not buncombe.applies(sc_row)


def test_applies_only_to_the_three_homestead_counties_with_a_claim():
    assert V.applies(_row("york"))
    assert V.applies(_row("lexington"))
    assert V.applies(_row("spartanburg"))
    assert not V.applies(_row("greenville"))                       # not one of the three
    assert not V.applies(_row("york", state="NC"))                 # wrong state
    assert not V.applies(_row("york", listing_type="tax_lien", raw={}))  # no claim carried
    # the claim shape alone is enough, even without listing_type (enrichment_tax_relief's path)
    assert V.applies(_row("york", listing_type="tax_lien"))


def test_confirmed_when_the_flag_is_present_and_owner_matches():
    for county in ("york", "lexington", "spartanburg"):
        cfg = V.COUNTIES[county]
        url = V.layer_url(cfg, cfg.id_fields[0], PID)
        r, f = _run(_row(county), {url: _layer_json(cfg, present=True)})
        assert r.verdict == "confirmed", county
        assert r.evidence["basis"] == "exemption_on_record"
        assert r.evidence["flag_present_today"] is True
        assert r.evidence["owner_match"] == "same"
        assert "SMITH" not in str(r.evidence)      # public ledger: no owner name leaked
        assert f.asked == [url]


def test_fallback_id_field_used_when_the_primary_finds_nothing():
    cfg = V.COUNTIES["york"]
    primary = V.layer_url(cfg, cfg.id_fields[0], PID)
    fallback = V.layer_url(cfg, cfg.id_fields[1], PID)
    r, f = _run(_row("york"), {primary: _empty(), fallback: _layer_json(cfg, present=True)})
    assert r.verdict == "confirmed" and f.asked == [primary, fallback]


def test_owner_differs_is_unconfirmed_never_refuted():
    cfg = V.COUNTIES["spartanburg"]
    url = V.layer_url(cfg, cfg.id_fields[0], PID)
    r, _ = _run(_row("spartanburg"), {url: _layer_json(cfg, present=True, owner="NEWCOMER, NORA")})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "owner_differs_relief_present"
    assert r.evidence["flag_present_today"] is True


def test_stale_when_the_flag_is_absent_today_but_the_parcel_is_found():
    cfg = V.COUNTIES["lexington"]
    url = V.layer_url(cfg, cfg.id_fields[0], PID)
    r, _ = _run(_row("lexington"), {url: _layer_json(cfg, present=False)})
    assert r.verdict == "stale" and r.evidence["basis"] == "homestead_flag_cleared"
    assert r.evidence["flag_present_today"] is False


def test_parcel_not_found_and_layer_errors_are_unconfirmed():
    cfg = V.COUNTIES["york"]
    primary = V.layer_url(cfg, cfg.id_fields[0], PID)
    fallback = V.layer_url(cfg, cfg.id_fields[1], PID)
    r, f = _run(_row("york"), {primary: _empty(), fallback: _empty()})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "parcel_not_in_county_layer"
    assert f.asked == [primary, fallback]

    r, _ = _run(_row("york"), {primary: json.dumps({"error": {"code": 500}})})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "layer_unreadable"

    r, f = _run(_row("york"), {})     # no recording at all -> LookupError inside ReplayFetcher
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "layer_unreadable"

    r, f = _run(_row("york", parcel_id=None, raw={}), {})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "parcel_unresolvable" and f.asked == []


def test_each_county_queries_its_own_scrapers_live_url_and_field_names():
    # pins against counties_sc.*_homestead.py's own constants (no import -- see module docstring)
    from foreclosure_scraper.scrapers.counties_sc import lexington_homestead as lex
    from foreclosure_scraper.scrapers.counties_sc import spartanburg_homestead as spt
    from foreclosure_scraper.scrapers.counties_sc import york_homestead as yrk
    assert V.COUNTIES["york"].layer_url == yrk.QUERY_URL
    assert V.COUNTIES["lexington"].layer_url == lex.QUERY_URL
    assert V.COUNTIES["spartanburg"].layer_url == spt.QUERY_URL
