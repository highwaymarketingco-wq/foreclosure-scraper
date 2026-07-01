"""Guard: the built-but-dateless sources must stay in DATELESS_OK_SOURCES.

These 8 sources produce leads with NO sale_date (elderly owners, storm damage,
delinquent tax, obituaries). If they fall out of DATELESS_OK_SOURCES, _active_only
silently drops every one of their leads (they read 0 on the board) — the exact bug
fixed 2026-06-30. This pins them so a future refactor can't reintroduce it.
"""
from foreclosure_scraper.main import DATELESS_OK_SOURCES


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
    }
    missing = required - DATELESS_OK_SOURCES
    assert not missing, f"dateless sources dropped from DATELESS_OK_SOURCES (leads will 0-out): {missing}"
