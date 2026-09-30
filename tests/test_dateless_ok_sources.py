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
    }
    missing = required - DATELESS_OK_SOURCES
    assert not missing, f"dateless sources dropped from DATELESS_OK_SOURCES (leads will 0-out): {missing}"


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
