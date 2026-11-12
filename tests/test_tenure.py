"""Owner-tenure enrichment: long-held = high-equity proxy (local, from GIS sale year)."""
from datetime import datetime
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_tenure import enrich_tenure


def _li(raw):
    now = datetime.utcnow()
    return Listing(source="s", source_url="https://x/1", listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state="SC", county="Spartanburg",
                   first_seen=now, last_seen=now, raw=raw)


def test_long_tenure_flagged():
    li = _li({"gis": {"last_sale": {"date": "2010-06-01"}}})
    enrich_tenure([li], now_year=2026)
    assert li.raw["tenure"]["years_held"] == 16
    assert li.raw["tenure"]["long_tenure"] is True


def test_short_tenure_not_long():
    li = _li({"gis": {"last_sale": {"year": 2023}}})
    enrich_tenure([li], now_year=2026)
    assert li.raw["tenure"]["years_held"] == 3
    assert li.raw["tenure"]["long_tenure"] is False


def test_no_sale_date_skipped():
    li = _li({})
    stats = enrich_tenure([li], now_year=2026)
    assert stats["computed"] == 0
    assert "tenure" not in li.raw
