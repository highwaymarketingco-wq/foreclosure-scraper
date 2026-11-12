"""Pin the stale-link fallback enrichment behavior.

The single biggest "dead link" offender is the per-property aggregator
page (realtor/zillow/trulia/homes.com/foreclosure.com). These hard-block
bots (403/429) so they look broken even when live, and go genuinely dead
when the listing delists. Policy: NEVER touch source_url, NEVER drop the
lead — just ADD reliable fallback links (county GIS + Google + Maps) and
flag old/carryover leads as link_may_be_stale.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from foreclosure_scraper.stale_link_fallback import (
    STALE_AGE_DAYS,
    annotate_stale_links,
    build_fallback_links,
    is_aggregator_url,
)


def test_is_aggregator_url_matches_per_property_hosts():
    assert is_aggregator_url("https://www.zillow.com/homedetails/x/1_zpid/")
    assert is_aggregator_url("https://www.realtor.com/realestateandhomes-detail/x")
    assert is_aggregator_url("https://www.trulia.com/p/x")
    assert is_aggregator_url("https://www.foreclosure.com/address/x_lid")


def test_is_aggregator_url_rejects_non_aggregators_and_junk():
    assert not is_aggregator_url("https://publicindex.sccourts.org/x")
    assert not is_aggregator_url("https://portal-nc.tylertech.cloud/x")
    assert not is_aggregator_url(None)
    assert not is_aggregator_url("")
    assert not is_aggregator_url("not a url")


def test_build_fallback_links_known_county_has_all_three():
    links = build_fallback_links(
        street_address="305 S Lee St", city="Chesnee", state="SC",
        zip_code="29323", county="Spartanburg",
    )
    assert "google" in links and links["google"].startswith("https://www.google.com/search")
    assert "maps" in links
    assert "parcel_gis" in links


def test_build_fallback_links_unknown_county_still_gets_google():
    links = build_fallback_links(
        street_address="1 Main St", city="Nowhere", state="SC",
        zip_code=None, county="Faketon",
    )
    assert "google" in links
    assert "parcel_gis" not in links


def test_county_suffix_is_stripped():
    links = build_fallback_links(
        street_address="1 Main St", city="Asheville", state="NC",
        zip_code="28801", county="Buncombe County",
    )
    assert "parcel_gis" in links


def test_annotate_never_changes_source_url():
    rec = {
        "source_url": "https://www.realtor.com/realestateandhomes-detail/x",
        "street_address": "49 Madison Ave", "city": "Asheville", "state": "NC",
        "zip_code": "28801", "county": "Buncombe",
        "first_seen": datetime.now(timezone.utc).isoformat(), "raw": {},
    }
    original = rec["source_url"]
    annotate_stale_links(rec)
    assert rec["source_url"] == original
    assert "fallback_links" in rec["raw"]


def test_old_carryover_lead_is_flagged_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=STALE_AGE_DAYS + 10)).isoformat()
    rec = {
        "source_url": "https://www.zillow.com/homedetails/x/1_zpid/",
        "street_address": "1 Oak Ln", "city": "Candler", "state": "NC",
        "county": "Buncombe", "first_seen": old, "raw": {},
    }
    annotate_stale_links(rec)
    assert rec["raw"]["link_may_be_stale"] is True


def test_carryover_marker_flags_stale_even_when_young():
    rec = {
        "source_url": "https://www.realtor.com/realestateandhomes-detail/x",
        "street_address": "5 A St", "city": "Anderson", "state": "SC",
        "county": "Anderson",
        "first_seen": datetime.now(timezone.utc).isoformat(),
        "raw": {"carryover": {"stale": True}},
    }
    annotate_stale_links(rec)
    assert rec["raw"]["link_may_be_stale"] is True


def test_young_fresh_lead_is_not_flagged():
    rec = {
        "source_url": "https://www.zillow.com/homedetails/x/1_zpid/",
        "street_address": "1 Oak Ln", "city": "Candler", "state": "NC",
        "county": "Buncombe",
        "first_seen": datetime.now(timezone.utc).isoformat(), "raw": {},
    }
    annotate_stale_links(rec)
    assert "fallback_links" in rec["raw"]
    assert "link_may_be_stale" not in rec["raw"]


def test_dead_link_check_flags_stale():
    rec = {
        "source_url": "https://www.realtor.com/realestateandhomes-detail/x",
        "street_address": "5 A St", "city": "Anderson", "state": "SC",
        "county": "Anderson",
        "first_seen": datetime.now(timezone.utc).isoformat(),
        "raw": {"link_check": {"status": "dead", "http": 404}},
    }
    annotate_stale_links(rec)
    assert rec["raw"]["link_may_be_stale"] is True


def test_non_aggregator_lead_is_untouched():
    rec = {
        "source_url": "https://publicindex.sccourts.org/x",
        "street_address": "1 Court St", "county": "Spartanburg",
        "raw": {"link_check": {"status": "anti-bot"}},
    }
    annotate_stale_links(rec)
    assert "fallback_links" not in rec["raw"]
    assert "link_may_be_stale" not in rec["raw"]


def test_annotate_does_not_clobber_existing_fallback_links():
    rec = {
        "source_url": "https://www.zillow.com/homedetails/x/1_zpid/",
        "street_address": "1 Oak Ln", "city": "Candler", "state": "NC",
        "county": "Buncombe",
        "first_seen": datetime.now(timezone.utc).isoformat(),
        "raw": {"fallback_links": {"google": "https://preset.example/"}},
    }
    annotate_stale_links(rec)
    # existing google preserved, new keys merged in
    assert rec["raw"]["fallback_links"]["google"] == "https://preset.example/"
    assert "parcel_gis" in rec["raw"]["fallback_links"]


def test_annotate_is_safe_on_missing_raw_and_bad_input():
    rec = {"source_url": "https://www.zillow.com/homedetails/x/1_zpid/"}
    annotate_stale_links(rec)  # no raw, no address — must not raise
    assert isinstance(rec.get("raw"), dict)
    # bad input types
    assert annotate_stale_links(None) is None
    assert annotate_stale_links("str") == "str"
