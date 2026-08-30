"""Tests for the 7 new Goliath Data gap modules."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from foreclosure_scraper.models import Listing, ListingType


def _make_listing(**kwargs):
    """Create a minimal Listing for testing."""
    raw = kwargs.pop("raw", {})
    listing_type = kwargs.pop("listing_type", ListingType.TAX_LIEN)
    return Listing(
        owner_name=kwargs.get("owner_name", "SMITH JOHN"),
        defendant=kwargs.get("defendant", ""),
        street_address=kwargs.get("street_address", "123 Main St"),
        city=kwargs.get("city", "Raleigh"),
        state=kwargs.get("state", "NC"),
        county=kwargs.get("county", "Wake"),
        zip_code=kwargs.get("zip_code", "27601"),
        source=kwargs.get("source", "test"),
        source_url=kwargs.get("source_url", "https://example.com"),
        parcel_id=kwargs.get("parcel_id", "P123"),
        listing_type=listing_type,
        raw=raw,
    )


class TestDNcScrubber:
    """Test DNC scrubber enrichment."""

    def test_dnc_imports(self):
        from foreclosure_scraper.enrichment_dnc import enrich_dnc_scrub
        assert callable(enrich_dnc_scrub)

    def test_dnc_unverified_without_file(self):
        """Without a local DNC file, all phones should be tagged unverified."""
        from foreclosure_scraper.enrichment_dnc import enrich_dnc_scrub, _load_dnc
        # Force no DNC file
        import foreclosure_scraper.enrichment_dnc as dnc_mod
        dnc_mod._DNC_SET = None
        dnc_mod._DNC_PATH = Path("/nonexistent/dnc_registry.csv")

        listing = _make_listing(raw={"owner_phone": {"phone": "919-555-1234"}})
        result = enrich_dnc_scrub([listing])
        assert result["listings_with_phone"] == 1
        assert result["unverified"] >= 1
        assert listing.raw["dnc_scrub"][0]["dnc_status"] == "unverified"
        assert listing.raw["dnc_scrub"][0]["dnc_registered"] is None

    def test_dnc_idempotent(self):
        """Already-scrubbed listings should be skipped."""
        from foreclosure_scraper.enrichment_dnc import enrich_dnc_scrub
        import foreclosure_scraper.enrichment_dnc as dnc_mod
        dnc_mod._DNC_SET = set()
        dnc_mod._DNC_PATH = Path("/nonexistent/dnc_registry.csv")

        listing = _make_listing(raw={
            "owner_phone": {"phone": "9195551234"},
            "dnc_scrub": [{"phone": "9195551234", "dnc_status": "clear"}]
        })
        result = enrich_dnc_scrub([listing])
        assert result["scrubbed"] == 1  # counted as scrubbed (already done)


class TestMarriageLicense:
    """Test marriage license enrichment."""

    def test_marriage_imports(self):
        from foreclosure_scraper.enrichment_marriage_license import enrich_marriage_licenses
        assert callable(enrich_marriage_licenses)

    def test_marriage_parse_name(self):
        from foreclosure_scraper.enrichment_marriage_license import _parse_name
        # No comma: last word = last name (First Last format)
        assert _parse_name("SMITH JOHN") == ("JOHN", "SMITH")
        assert _parse_name("Doe, Jane") == ("DOE", "JANE")
        assert _parse_name("John Smith") == ("SMITH", "JOHN")
        assert _parse_name("") is None
        assert _parse_name(None) is None

    def test_marriage_match_confidence(self):
        from foreclosure_scraper.enrichment_marriage_license import _match_confidence
        assert _match_confidence("SMITH", "JOHN", {"spouse_name": "JOHN SMITH"}) == "high"
        assert _match_confidence("SMITH", "JOHN", {"spouse_name": "SMITH"}) == "medium"
        assert _match_confidence("SMITH", "JOHN", {"spouse_name": "JONES"}) == "low"

    def test_marriage_idempotent(self):
        """Listings with existing marriage_license data should be skipped."""
        from foreclosure_scraper.enrichment_marriage_license import enrich_marriage_licenses
        listing = _make_listing(
            owner_name="SMITH JOHN",
            raw={"marriage_license": {"spouse_name": "JANE SMITH"}}
        )
        result = enrich_marriage_licenses([listing])
        assert result["skipped_existing"] == 1


class TestCampaignExport:
    """Test campaign export module."""

    def test_campaign_imports(self):
        from foreclosure_scraper.campaign_export import export_campaigns
        assert callable(export_campaigns)

    def test_campaign_sms_export(self, tmp_path):
        from foreclosure_scraper.campaign_export import export_campaigns
        listing = _make_listing(
            owner_name="SMITH JOHN",
            raw={"skip_trace": {"phone_numbers": ["9195551234"]}}
        )
        result = export_campaigns([listing], output_dir=str(tmp_path), formats=["sms"])
        assert "sms" in result["files"]
        assert result["stats"]["sms_rows"] == 1
        csv_path = Path(result["files"]["sms"])
        assert csv_path.exists()
        content = csv_path.read_text()
        assert "9195551234" in content

    def test_campaign_filter_by_state(self, tmp_path):
        from foreclosure_scraper.campaign_export import export_campaigns
        li_nc = _make_listing(state="NC", owner_name="SMITH JOHN")
        li_sc = _make_listing(state="SC", owner_name="JONES BOB")
        result = export_campaigns(
            [li_nc, li_sc], output_dir=str(tmp_path),
            formats=["email"], filters={"state": "NC"}
        )
        assert result["stats"]["filtered_leads"] == 1
        assert result["stats"]["total_leads"] == 2


class TestWorkflowEngine:
    """Test workflow automation engine."""

    def test_workflow_imports(self):
        from foreclosure_scraper.workflow_engine import evaluate_workflows
        assert callable(evaluate_workflows)

    def test_workflow_hot_lead_trigger(self):
        from foreclosure_scraper.workflow_engine import evaluate_workflows, _check_trigger
        listing = _make_listing(
            owner_name="SMITH JOHN",
            raw={"grade": {"overall": "A"}, "owner_phone": {"phone": "9195551234"}}
        )
        assert _check_trigger(listing, {"grade": ["A"], "has_phone": True}) is True
        assert _check_trigger(listing, {"grade": ["B"]}) is False

    def test_workflow_tag_action(self):
        from foreclosure_scraper.workflow_engine import _apply_action
        listing = _make_listing(raw={})
        _apply_action(listing, {"type": "tag", "value": "priority_sms"})
        assert "priority_sms" in listing.raw["workflow_tags"]
        _apply_action(listing, {"type": "set_status", "value": "contact_pending"})
        assert listing.raw["workflow_status"] == "contact_pending"

    def test_workflow_default_rules(self, tmp_path):
        from foreclosure_scraper.workflow_engine import _load_rules
        # _load_rules creates defaults if file doesn't exist
        # Just verify it returns a list
        rules = _load_rules(Path(tmp_path / "test_workflows.json"))
        assert isinstance(rules, list)
        assert len(rules) > 0


class TestAnalyticsDashboard:
    """Test analytics dashboard."""

    def test_analytics_imports(self):
        from foreclosure_scraper.analytics_dashboard import generate_dashboard
        assert callable(generate_dashboard)

    def test_analytics_compute_metrics(self):
        from foreclosure_scraper.analytics_dashboard import compute_metrics
        listings = [
            _make_listing(raw={"grade": {"overall": "A"}, "calc": {"arv": 200000, "max_bid": 120000}}),
            _make_listing(raw={"grade": {"overall": "B"}, "calc": {"arv": 150000, "max_bid": 90000}}),
        ]
        metrics = compute_metrics(listings)
        assert metrics["total_leads"] == 2
        assert metrics["by_grade"]["A"] == 1
        assert metrics["total_arv"] == 350000
        assert len(metrics["hot_leads"]) == 2

    def test_analytics_html_generation(self, tmp_path):
        from foreclosure_scraper.analytics_dashboard import generate_html, compute_metrics
        listings = [_make_listing(raw={"grade": {"overall": "A"}})]
        metrics = compute_metrics(listings)
        html = generate_html(metrics)
        assert "<html" in html
        assert "Foreclosure Analytics" in html
        assert "Total Leads" in html


class TestAPIServer:
    """Test REST API server."""

    def test_api_imports(self):
        from foreclosure_scraper.api_server import create_server
        assert callable(create_server)

    def test_api_filter_leads(self):
        from foreclosure_scraper.api_server import _filter_leads, _BOARD
        li_nc = _make_listing(state="NC", county="Wake")
        li_sc = _make_listing(state="SC", county="Greenville")
        filtered = _filter_leads([li_nc, li_sc], {"state": ["NC"]})
        assert len(filtered) == 1
        assert filtered[0].state == "NC"

    def test_api_search_leads(self):
        from foreclosure_scraper.api_server import _search_leads, _BOARD
        import foreclosure_scraper.api_server as api_mod
        li = _make_listing(owner_name="SMITH JOHN", parcel_id="P12345")
        api_mod._BOARD = [li]
        api_mod._BOARD_INDEX = {li.dedupe_key(): li}
        results = _search_leads("SMITH")
        assert len(results) == 1
        results = _search_leads("P12345")
        assert len(results) == 1
        results = _search_leads("NONEXISTENT")
        assert len(results) == 0

    def test_api_listing_to_dict(self):
        from foreclosure_scraper.api_server import _listing_to_dict
        li = _make_listing(raw={"calc": {"arv": 200000}, "secret_key": "hidden"})
        d = _listing_to_dict(li)
        assert "raw" in d
        assert "calc" in d["raw"]
        assert "secret_key" not in d["raw"]  # not in keep_keys


class TestHourlyRefresh:
    """Test hourly refresh module."""

    def test_hourly_imports(self):
        from foreclosure_scraper.hourly_refresh import hourly_refresh
        assert callable(hourly_refresh)
