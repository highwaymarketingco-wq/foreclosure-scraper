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
        listing_type: ListingType = ListingType.LIS_PENDENS,
        **kw) -> Listing:
    base = dict(
        source=source,
        source_url=f"https://example.com/{county}-{state}",
        listing_type=listing_type,
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


#: Deny-list tests below construct a FLIP-type lead explicitly. Confirmed
#: directly with the user 2026-09-15: "if its a flip, its only in the
#: counties we talked about. if its a distressed property its anywhere in
#: nc and sc" — SCOPE_DENY_COUNTIES (and the narrow config.SC_COUNTIES/
#: NC_COUNTIES footprint) now only gate FLIP-type leads (see
#: main._FLIP_LISTING_TYPES); a distressed-type lead (this file's default,
#: LIS_PENDENS, included) in one of these same counties is legitimately
#: admissible via config.in_scope_distressed instead — see the
#: test_distressed_* tests at the bottom of this file for that coverage.
_FLIP = ListingType.FORECLOSURE_SALE


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
    set, a Mecklenburg FLIP listing with no county tag (or with county
    tagged Mecklenburg) and zip=28202 would pass via the prefix path. Deny
    must override for flip-type leads."""
    li = _li(county="Mecklenburg", state="NC", zip_code="28202", listing_type=_FLIP)
    assert _in_scope(li) is False


def test_main_in_scope_denies_haywood_via_zip_fallback():
    """287xx covers Haywood (Asheville/Waynesville area). The 2 Run #16
    Haywood listings sneaked in this way. Flip-type lead."""
    li = _li(county="Haywood", state="NC", zip_code="28786", listing_type=_FLIP)
    assert _in_scope(li) is False


def test_main_in_scope_denies_mecklenburg_even_via_bypass_source():
    """SCOPE_BYPASS_SOURCES (CourtListener bankruptcy/civil/adversary)
    bypasses the normal in_scope. Deny must STILL override for a flip-type
    lead — investor doesn't want a Charlotte flip if they're not investing
    there. (A distressed-type BK lead in Mecklenburg — the far more common
    real shape for this source bucket — is legitimately admitted; see
    test_distressed_bypass_source_in_denied_county_is_admitted below.)"""
    bypass = next(iter(SCOPE_BYPASS_SOURCES))
    li = _li(source=bypass, county="Mecklenburg", state="NC", listing_type=_FLIP)
    assert _in_scope(li) is False


def test_kept_county_still_passes():
    """Buncombe (Asheville) is in scope — sanity-check the deny doesn't
    break legit listings."""
    li = _li(county="Buncombe", state="NC", zip_code="28801")
    assert _in_scope(li) is True


def test_greenville_sc_denied():
    """Greenville SC was re-pruned 2026-05-14 and the owner re-confirmed it
    stays denied 2026-06-16 — for FLIP-type leads. (2026-09-15: Greenville's
    own delinquent-tax source, counties_sc.greenville_delinquent_tax, ships
    2,287+ real DISTRESSED-type rows for this exact county — confirmed with
    the user that distressed leads are in-scope statewide regardless of
    this flip-only deny entry; see test_distressed_lead_in_denied_county_
    is_admitted_anywhere below.)"""
    li = _li(county="Greenville", state="SC", zip_code="29601", listing_type=_FLIP)
    assert _in_scope(li) is False


def test_brunswick_nc_denied():
    """Brunswick NC (coastal, Wilmington area) was pruned 2026-05-15 in the
    'anything east of Charlotte' cleanup. Explicit deny beats the 284 zip
    prefix, so a 284xx Brunswick FLIP listing must fail scope."""
    li = _li(county="Brunswick", state="NC", zip_code="28461", listing_type=_FLIP)
    assert _in_scope(li) is False


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
    normalize and hit the deny set, for a flip-type lead."""
    for variant in ("Mecklenburg County", "mecklenburg", "MECKLENBURG"):
        li = _li(county=variant, state="NC", zip_code="28202", listing_type=_FLIP)
        assert _in_scope(li) is False, f"{variant!r} should be denied"


# --- 2026-09-15: distressed-anywhere coverage -------------------------------
# Confirmed directly with the user: "if its a flip, its only in the counties
# we talked about. if its a distressed property its anywhere in nc and sc."
# The tests above pin that FLIP leads still respect the old 18-county
# footprint + deny list. These pin the other half: a DISTRESSED-type lead is
# admissible in ANY real NC or SC county, including ones on the deny list —
# because the deny list is a flip-scope concept, not a blanket ban.

def test_distressed_lead_in_denied_county_is_admitted_anywhere():
    """A DISTRESSED-type lead (this file's _li() default: LIS_PENDENS) in a
    county on SCOPE_DENY_COUNTIES must NOT be dropped — the deny list only
    applies to flip-type leads now."""
    for county, state in (("Mecklenburg", "NC"), ("Greenville", "SC"),
                          ("Wake", "NC"), ("Abbeville", "SC")):
        li = _li(county=county, state=state)
        assert _in_scope(li) is True, f"{county}, {state} distressed lead should be admitted"


def test_distressed_lead_outside_the_old_18_county_footprint_is_admitted():
    """Florence SC was never in config.SC_COUNTIES (the old narrow flip
    footprint) and is NOT on the deny list either — it was simply never
    considered. A distressed-type lead there must still be admitted
    (in_scope_distressed treats any real NC/SC county as in-scope)."""
    li = _li(county="Florence", state="SC")
    assert _in_scope(li) is True


def test_distressed_bypass_source_in_denied_county_is_admitted():
    """The exact real-world shape: a CourtListener bankruptcy filing
    (SCOPE_BYPASS_SOURCES, distressed-type by default) in Mecklenburg —
    should be admitted now, unlike the flip-type version of this same
    scenario in test_main_in_scope_denies_mecklenburg_even_via_bypass_source
    above."""
    bypass = next(iter(SCOPE_BYPASS_SOURCES))
    li = _li(source=bypass, county="Mecklenburg", state="NC")
    assert _in_scope(li) is True


def test_flip_lead_still_denied_in_a_fake_county():
    """A flip-type lead in a county that isn't real at all must still be
    rejected (in_scope's normal behavior, unaffected by this change)."""
    li = _li(county="Notarealcounty", state="NC", listing_type=_FLIP)
    assert _in_scope(li) is False


def test_distressed_lead_in_a_fake_county_is_still_rejected():
    """in_scope_distressed only admits REAL NC/SC county names — a typo or
    garbage county string must still be dropped, not silently admitted."""
    li = _li(county="Notarealcounty", state="NC")
    assert _in_scope(li) is False
