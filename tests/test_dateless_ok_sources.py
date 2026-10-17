"""Guard: the built-but-dateless sources must stay in DATELESS_OK_SOURCES.

These 8 sources produce leads with NO sale_date (elderly owners, storm damage,
delinquent tax, obituaries). If they fall out of DATELESS_OK_SOURCES, _active_only
silently drops every one of their leads (they read 0 on the board) — the exact bug
fixed 2026-06-30. This pins them so a future refactor can't reintroduce it.
"""
from datetime import datetime

from foreclosure_scraper.main import DATELESS_OK_SOURCES, _active_only
from foreclosure_scraper.models import Listing, ListingType


def test_built_dateless_sources_are_whitelisted():
    required = {
        "counties_nc.buncombe_elderly",
        "counties_nc.asheville_helene",
        "public_notices.gannett_obituaries",
        "counties_nc.buncombe_delinquent_tax",
        "counties_sc.spartanburg_delinquent_tax",
        "counties_sc.cherokee_delinquent_tax",
        "national.gsa_realproperty",
        "national.servicelink_auction",
        "counties_sc.spartan_weekly_legals",
        # 2026-09-29 sale-type/no-date audit: horry_flc is a standing FLC
        # over-the-counter roster (never sets sale_date, per its own docstring),
        # same as every other _flc source, but had been left off this list.
        "counties_sc.horry_flc",
        # national.williams (rewritten 2026-10-02): most rows carry a real
        # courthouse sale_date, but a sale that has already happened reports no
        # date at all -- only an auction_status of "upset_bid_period" (NC's
        # statutory 10-day post-sale window). Same shape as nc_upset_bids below.
        "national.williams",
        # 2026-10-14 (date-coverage audit pass2, item #5 verification): found while adding
        # these three to board_persist.AGE_EXEMPT_SOURCES -- none was whitelisted here, and none
        # of the three ever sets sale_date (every Listing() call site in each file reviewed), so
        # EVERY row from all three was being silently dropped before reaching the board at all.
        "counties_nc.wnc_rod_foreclosure_starts",
        "counties_nc.nc_rod_captcha",
        "counties_sc.sc_rod_walled",
        # 2026-10-15 (date-coverage audit pass3): same discovery shape -- neither scraper's
        # Listing() ever sets sale_date (every call site reviewed), so without this entry
        # EVERY row from both was being silently dropped before reaching the board at all.
        "counties_nc.nc_rowan_cott",
        "national.nc_unclaimed",
    }
    missing = required - DATELESS_OK_SOURCES
    assert not missing, f"dateless sources dropped from DATELESS_OK_SOURCES (leads will 0-out): {missing}"


def test_nc_rowan_cott_and_nc_unclaimed_survive_active_only_with_no_sale_date():
    """Direct behavioral pin (not just set membership): a fresh, dateless row from either
    scraper must pass _active_only(), matching the real Listing() shape each file emits."""
    for source in ("counties_nc.nc_rowan_cott", "national.nc_unclaimed"):
        li = Listing(source=source, source_url="https://example.com/x",
                     listing_type=ListingType.UNKNOWN, sale_date=None,
                     first_seen=datetime(2026, 1, 1), last_seen=datetime(2026, 1, 1))
        assert _active_only(li, horizon_days=60, now=datetime(2026, 10, 15)), source


def test_horry_flc_dateless_row_survives_active_only():
    """counties_sc.horry_flc never sets sale_date (over-the-counter FLC inventory).
    Before the 2026-09-29 fix, a horry_flc row with no sale_date would have been
    silently dropped by _active_only the next time this source actually ran through
    the normal pipeline (the rows already on the board got there via a bypass path,
    not this gate)."""
    li = Listing(
        source="counties_sc.horry_flc",
        source_url="https://horrycountysc.gov/x",
        listing_type=ListingType.TAX_SALE,
        state="SC",
        county="Horry",
        street_address="1 Main St",
        sale_date=None,
        raw={},
    )
    assert _active_only(li, horizon_days=120, now=datetime(2026, 9, 29)) is True


def test_nc_rod_captcha_dateless_row_survives_active_only():
    """counties_nc.nc_rod_captcha never sets sale_date at all (confirmed by reading every
    Listing() call site, 2026-10-14 pass2 audit verification): it only sweeps SUBSTITUTE
    TRUSTEE / NOTICE OF FORECLOSURE recordings, never the eventual sale deed. Before this fix,
    every single row this source ever produced was silently dropped here before reaching the
    board."""
    li = Listing(
        source="counties_nc.nc_rod_captcha",
        source_url="https://example.com/rod",
        listing_type=ListingType.LIS_PENDENS,
        state="NC",
        county="Wake",
        street_address="1 Main St",
        sale_date=None,
        raw={},
    )
    assert _active_only(li, horizon_days=120, now=datetime(2026, 10, 14)) is True


def test_polk_tax_delinquent_search_row_survives_active_only():
    """counties_nc.polk_tax mixes a dated auction page with a dateless delinquent-tax-search
    sub-scraper (added 2026-10-12, standing tax balance, no sale date anywhere in
    _apply_detail). Before this fix every search-path row 0-counted on every run
    (2026-10-17 gap-sweep wave 6, drops-dateless-filtered-source: 1,622 rows)."""
    li = Listing(
        source="counties_nc.polk_tax",
        source_url="https://example.com/polk",
        listing_type=ListingType.TAX_LIEN,
        state="NC",
        county="Polk",
        street_address="1 Main St",
        sale_date=None,
        raw={},
    )
    assert _active_only(li, horizon_days=120, now=datetime(2026, 10, 17)) is True


def test_williams_upset_bid_row_survives_active_only():
    """A completed-sale/upset-bid-period national.williams row has no
    sale_date at all (the page gives no date for it, only a status
    sentence). Without the whitelist, _active_only would drop it as a
    'dateless historic roster' even though the lead is still live."""
    li = Listing(
        source="national.williams",
        source_url="https://bid.auctionnetwork.com/Listing/Details/8463529/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        state="NC",
        county="Guilford County",
        street_address="614 SEBASTIAN LN",
        sale_date=None,
        auction_status="upset_bid_period",
        raw={},
    )
    assert _active_only(li, horizon_days=120, now=datetime(2026, 10, 2)) is True
