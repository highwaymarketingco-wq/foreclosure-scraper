"""Copart Solr response parser — fixture-based test."""
from __future__ import annotations

import json
from pathlib import Path

from porsche_scraper.filters import FilterCriteria, filter_listings
from porsche_scraper.models import TitleStatus
from porsche_scraper.scrapers.copart import parse_solr_response

FIXTURE = Path(__file__).parent / "fixtures" / "copart.json"


def test_excludes_cayenne_at_parse_time():
    listings = parse_solr_response(json.loads(FIXTURE.read_text()))
    models = {l.model for l in listings}
    assert "CAYENNE" not in models
    # Other excluded models we left out of the fixture but verifying defense-in-depth.


def test_parses_run_and_drive_flag():
    listings = parse_solr_response(json.loads(FIXTURE.read_text()))
    by_lot = {l.listing_id: l for l in listings}
    # 911 Carrera S - run & drive
    assert by_lot["75612345"].drivable is True
    assert by_lot["75612345"].title_status == TitleStatus.SALVAGE
    # Cayman - explicitly not running
    assert by_lot["75613001"].drivable is False


def test_drops_parts_only_via_filter():
    listings = parse_solr_response(json.loads(FIXTURE.read_text()))
    crit = FilterCriteria(min_year=2014, max_year=2026, max_price_usd=45_000)
    kept = filter_listings(listings, crit)
    kept_lots = {l.listing_id for l in kept}
    # 911 salvage run-and-drive: kept (salvage exception, drivable=True)
    assert "75612345" in kept_lots
    # Cayman rebuilt not running: dropped (drivable=False)
    assert "75613001" not in kept_lots
    # Boxster parts-only: dropped
    assert "75613444" not in kept_lots


def test_high_priced_salvage_kept_above_cap():
    # Salvage listings ignore the price cap; verify the Solr 911 is kept
    # even if we set the cap below its bid.
    listings = parse_solr_response(json.loads(FIXTURE.read_text()))
    crit = FilterCriteria(min_year=2014, max_year=2026, max_price_usd=5_000)
    kept_lots = {l.listing_id for l in filter_listings(listings, crit)}
    assert "75612345" in kept_lots  # $12,500 bid, salvage — still kept
