"""screen_ledger: which (column, county) cells a run screened, from run_health statuses. Made-up runs."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from foreclosure_scraper import screen_ledger as SL


def test_status_ok():
    assert SL.status_ok("OK (12)")
    assert SL.status_ok("EMPTY (verified)")
    for bad in ("🔴 ALARM — BLOCKED: HTTP 403", "DORMANT — disabled", "CARRYOVER (5 stale from prior run)",
                "REGRESSED (expected ≥ 50)", "", None):
        assert not SL.status_ok(bad)


def test_county_in_filename_longest_name_and_county_dirs_only():
    base = SL.SCRAPERS
    assert SL.county_in_filename(base / "counties_sc" / "dillon_sheriff.py") == ("SC", "Dillon")
    assert SL.county_in_filename(base / "counties_nc" / "new_hanover_tax.py") == ("NC", "New Hanover")
    assert SL.county_in_filename(base / "national" / "dillon_sheriff.py") is None
    assert SL.county_in_filename(base / "counties_nc" / "nc_county_csv_delinquent_tax.py") is None


def test_feed_columns_of(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("a = ListingType.SHERIFF_SALE\nb = Listing(listing_type='tax_sale')\nc = ListingType.UNKNOWN\n")
    assert SL.feed_columns_of(p) == {"lt_sheriff_sale", "lt_tax_sale"}


def _rh(*sources, enrich=None):
    return {"generated_at": "2026-10-07T17:00:00+00:00",
            "sources": [{"source": s, "count": 0, "status": st} for s, st in sources],
            "enrichments": enrich or {}}


def test_build_ok_screens_failed_does_not():
    led = SL.build(_rh(("counties_sc.dillon_sheriff", "OK (3)"),
                       ("counties_sc.barnwell_sheriff", "🔴 ALARM — TIMEOUT"),
                       ("counties_sc.qpaybill_delinquent_roll", "OK (7000)")))
    assert SL.screened(led, "lt_sheriff_sale", "SC", "Dillon")
    assert not SL.screened(led, "lt_sheriff_sale", "SC", "Barnwell")
    assert "SC|Barnwell" in led["not_screened"]["lt_sheriff_sale"]
    # budgeted, pager-lossy enumeration never screens
    assert not any(SL.screened(led, c, "SC", "Abbeville") for c in SL.TAX_COLUMNS)
    assert led["run_at"].startswith("2026-10-07") and led["schema"] == SL.SCHEMA


def test_county_delinquent_roll_screens_the_tax_family():
    led = SL.build(_rh(("counties_sc.dillon_delinquent_tax", "OK (343)")))
    assert all(SL.screened(led, c, "SC", "Dillon") for c in SL.TAX_COLUMNS)


def test_statewide_feed_and_city_exclusion():
    led = SL.build(_rh(("national.courtlistener_bankruptcy", "OK (5)"),
                       ("counties_sc.spartanburg_vacant", "OK (4659)")))
    assert SL.screened(led, "lt_bankruptcy", "NC", "Alamance") and SL.screened(led, "lt_bankruptcy", "SC", "York")
    assert not SL.screened(led, "vacant", "SC", "Spartanburg")      # city registry, not the county


def test_unhealthy_jail_roster_removed():
    led = SL.build(_rh(("national.jail_bookings", "OK (2380)"),
                       enrich={"jail_bookings": {"rosters_unhealthy": ["Cleveland"]}}))
    assert SL.screened(led, "jail_booking", "NC", "Buncombe")
    assert not SL.screened(led, "jail_booking", "NC", "Cleveland")


def test_ok_source_wins_over_a_failed_one_for_the_same_cell(monkeypatch):
    cov = {"a.one": [(("lt_sheriff_sale",), {("SC", "Dillon")}, "t")],
           "a.two": [(("lt_sheriff_sale",), {("SC", "Dillon")}, "t")]}
    monkeypatch.setattr(SL, "screens_for", lambda slug: cov.get(slug, []))
    led = SL.build(_rh(("a.one", "🔴 ALARM — x"), ("a.two", "OK (1)")))
    assert SL.screened(led, "lt_sheriff_sale", "SC", "Dillon")
    assert "lt_sheriff_sale" not in led["not_screened"]


def test_write_load_fresh(tmp_path: Path):
    p = SL.write_ledger(_rh(("counties_sc.dillon_sheriff", "OK (3)")), tmp_path / "screen_ledger.json")
    led = SL.load(p)
    assert led and SL.fresh(led, date(2026, 10, 9))
    assert not SL.fresh(led, date(2026, 11, 30))
    assert not SL.fresh(led, date(2026, 10, 1))                  # a ledger from the future
    assert SL.load(tmp_path / "missing.json") == {}
    (tmp_path / "bad.json").write_text('{"schema": "other"}')
    assert SL.load(tmp_path / "bad.json") == {}


def test_run_health_writes_the_ledger_beside_it(tmp_path: Path):
    from foreclosure_scraper.run_health import write_health_artifact
    out = write_health_artifact(out_path=tmp_path / "run_health.json",
                                summary={"by_source": {"counties_sc.dillon_sheriff": 2},
                                         "source_status": {"counties_sc.dillon_sheriff": "OK (2)"}})
    led = SL.load(out.parent / "screen_ledger.json")
    assert SL.screened(led, "lt_sheriff_sale", "SC", "Dillon")
