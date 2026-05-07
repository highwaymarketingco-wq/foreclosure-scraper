"""Pin SCOPE_DENY_COUNTIES — counties that NEVER appear on the dashboard
regardless of how their listings were attributed.

Without explicit deny: zip-prefix fallback + SCOPE_BYPASS_SOURCES would
let denied counties leak in. Run #16 forensics confirmed: 2 Haywood NC
listings + 1 Abbeville SC listing slipped through via zip prefixes
(287xx covers Haywood, 296xx covers Abbeville) even though neither was
in NC_COUNTIES / SC_COUNTIES.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.config import (
    SCOPE_DENY_COUNTIES,
    SCOPE_DENY_COUNTIES_NORMALIZED,
    in_scope,
)
from foreclosure_scraper.main import _in_scope, SCOPE_BYPASS_SOURCES
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(*, source: str = "test", county: str | None = None,
        state: str | None = None, zip_code: str | None = None,
        **kw) -> Listing:
    base = dict(
        source=source,
        source_url=f"https://example.com/{county}-{state}",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        county=county,
        state=state,
        zip_code=zip_code,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


def test_deny_set_covers_b_and_d_rollbacks():
    """2026-05-07b (Charlotte + WNC) + d (eastern NC + south-of-Newberry SC)
    rollbacks. Eastern NC counties were already removed from NC_COUNTIES
    in rollback A, but BK listings leak via SCOPE_BYPASS_SOURCES — the
    deny set is what plugs that hole."""
    must_include = {
        # 2026-05-07b
        ("Mecklenburg", "NC"), ("Madison", "NC"), ("Yancey", "NC"),
        ("Haywood", "NC"), ("Abbeville", "SC"),
        # 2026-05-07d
        ("Wake", "NC"), ("Forsyth", "NC"), ("Guilford", "NC"),
        ("Durham", "NC"), ("Cumberland", "NC"), ("Alamance", "NC"),
        ("Iredell", "NC"), ("Cabarrus", "NC"), ("Union", "NC"),
        ("Pitt", "NC"), ("Johnston", "NC"), ("Rowan", "NC"),
        ("Swain", "NC"), ("Newberry", "SC"), ("Greenwood", "SC"),
    }
    missing = must_include - SCOPE_DENY_COUNTIES_NORMALIZED
    assert not missing, f"deny set missing: {missing}"


def test_in_scope_denies_mecklenburg_directly():
    """config.in_scope must short-circuit to False for denied counties."""
    assert in_scope("Mecklenburg", "NC") is False


def test_in_scope_denies_haywood():
    assert in_scope("Haywood", "NC") is False


def test_in_scope_denies_abbeville():
    assert in_scope("Abbeville", "SC") is False


def test_main_in_scope_denies_mecklenburg_via_zip_fallback():
    """Mecklenburg zip 282xx is in SCOPE_ZIP_PREFIXES — without the deny
    set, a Mecklenburg listing with no county tag (or with county tagged
    Mecklenburg) and zip=28202 would pass via the prefix path. Deny
    must override."""
    li = _li(county="Mecklenburg", state="NC", zip_code="28202")
    assert _in_scope(li) is False


def test_main_in_scope_denies_haywood_via_zip_fallback():
    """287xx covers Haywood (Asheville/Waynesville area). The 2 Run #16
    Haywood listings sneaked in this way."""
    li = _li(county="Haywood", state="NC", zip_code="28786")
    assert _in_scope(li) is False


def test_main_in_scope_denies_mecklenburg_even_via_bypass_source():
    """SCOPE_BYPASS_SOURCES (CourtListener bankruptcy/civil/adversary)
    bypasses the normal in_scope. Deny must STILL override — investor
    doesn't want Charlotte BK listings if they're not investing there."""
    bypass = next(iter(SCOPE_BYPASS_SOURCES))
    li = _li(source=bypass, county="Mecklenburg", state="NC")
    assert _in_scope(li) is False


def test_kept_county_still_passes():
    """Buncombe (Asheville) is in scope — sanity-check the deny doesn't
    break legit listings."""
    li = _li(county="Buncombe", state="NC", zip_code="28801")
    assert _in_scope(li) is True


def test_greenville_sc_back_in_scope():
    """2026-05-07c restored Greenville per user direction."""
    li = _li(county="Greenville", state="SC", zip_code="29601")
    assert _in_scope(li) is True


def test_brunswick_zip_prefix_now_passes():
    """Brunswick NC (Wilmington area) — coastal user-key. Without 284
    in SCOPE_ZIP_PREFIXES, HomeHarvest distressed listings tagged only
    by zip would have failed scope. 2026-05-07c added 284."""
    # zip-only path: county not set, but 284xx zip
    li = _li(county=None, state="NC", zip_code="28461")
    assert _in_scope(li) is True


def test_unattributed_bk_listing_tagged_state_only():
    """SCOPE_BYPASS_SOURCES (CL bankruptcy) listings without a county
    pass scope but get raw.geo_attribution = 'state-only' so the
    dashboard can group / filter the unattributed bucket."""
    bypass = next(iter(SCOPE_BYPASS_SOURCES))
    li = _li(source=bypass, county=None, state="NC")
    assert _in_scope(li) is True
    assert li.raw.get("geo_attribution") == "state-only"


def test_attributed_bk_listing_not_tagged_state_only():
    """BK listings WITH a county should NOT get the state-only marker."""
    bypass = next(iter(SCOPE_BYPASS_SOURCES))
    li = _li(source=bypass, county="Buncombe", state="NC")
    assert _in_scope(li) is True
    assert "geo_attribution" not in (li.raw or {})


def test_county_normalization_still_denies():
    """'Mecklenburg County' / 'mecklenburg' / 'MECKLENBURG' should all
    normalize and hit the deny set."""
    for variant in ("Mecklenburg County", "mecklenburg", "MECKLENBURG"):
        li = _li(county=variant, state="NC", zip_code="28202")
        assert _in_scope(li) is False, f"{variant!r} should be denied"
