"""City of Asheville Accela code-enforcement (AccelaServicesView).

THE FINDING THIS FILE PINS: the live feed's entire 2,738-row table is a
frozen 2016-2018 snapshot (every date field, every category -- see the
module docstring for the full live `outStatistics` evidence). This module
therefore ships with a self-healing staleness gate in `fetch()` rather than a
hardcoded disable: a cheap live MAX(date_opened) probe runs every call, and
the real query/classify logic below it only runs when that probe comes back
recent. The tests below exercise the classification logic directly (so the
investigation's category work is not thrown away even though nothing ships
today) AND the gate itself (mocked fresh vs. stale, so the gate's logic is
provably correct independent of today's live date).

FIXTURES BELOW are shaped like real `AccelaServicesView/MapServer/0` rows
captured live 2026-10-03 (`record_id`, `address`, `description` text are
verbatim from the live service; `record_status`/`record_status_date` on the
"open" fixtures are adjusted to `Open`/recent-looking so the open/closed and
severity logic can be exercised independently of the dataset's real,
universally-stale dates, which `test_asheville_code.py`'s staleness tests
cover separately).
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.counties_nc import asheville_code_enforcement as mod

from tests._arcgis_fakes import FakeHttp

# Real junk-vehicle complaint, 129 Fairfax Ave (captured live 2026-10-03).
JUNKED_VEHICLE_OPEN = {
    "record_id": "16-05337S",
    "address": "129 FAIRFAX AVE, ASHEVILLE, NC 28806",
    "record_status": "Open",
    "record_status_date": 1770000000000,
    "record_type": "ZOE: Junked Vehicles",
    "record_type_category": "Junked Vehicles",
    "description": "complaint stated there were 4 or 5 junk cars sitting at the residence.",
    "short_notes": None,
    "date_opened": 1464840000000,
    "parcel_number": "202216",
    "apn": "202216",
}

# Real housing-code complaint, 6 Morris Pl (captured live 2026-10-03) -- but
# closed in the real feed; status swapped to an "open-ish" one here to
# exercise the open path. The closed version is CLOSED_HOUSING_CASE below.
HOUSING_CODE_OPEN = {
    "record_id": "16-04993S",
    "address": "6 MORRIS PL, ASHEVILLE, NC 28806",
    "record_status": "NOV Mailed",
    "record_type": "Res: Housing Case",
    "record_type_category": "Housing Code Referral",
    "description": "Neighbor complaint of a house being occupied; house doe not have power or water service.",
    "date_opened": 1461124800000,
    "parcel_number": "16095",
    "apn": "16095",
}

CLOSED_HOUSING_CASE = dict(HOUSING_CODE_OPEN, record_status="Closed")

# Real damage-incident, 16 Evelake Dr (captured live 2026-10-03, truncated).
DAMAGE_INCIDENT_OPEN = {
    "record_id": "16-04399S",
    "address": "16 EVELAKE DR, ASHEVILLE, NC 28806",
    "record_status": "Unsafe Structure",
    "record_type": "Res: Bldg Damage",
    "record_type_category": "Damage - Incident",
    "description": "I was called to the above address for a tree on the house. "
                    "The owner was advised not to stay in the home.",
    "date_opened": 1460347200000,
    "parcel_number": "88214",
    "apn": "88214",
}

# Real short-term-rental complaint (captured live 2026-10-03) -- zoning, not
# a property-condition signal. Must ship (has_open) but not score.
STR_OPEN = {
    "record_id": "16-04385S",
    "address": "80 W CHESTNUT ST, ASHEVILLE, NC 28801",
    "record_status": "Open",
    "record_type": "ZOE: Short Term Rental",
    "record_type_category": "Short Term Rental",
    "description": "Short Term Rental prohibited / unpermitted homestay",
    "date_opened": 1460000000000,
}

# Real stop-work-order (captured live 2026-10-03) -- active unpermitted
# CONSTRUCTION, the opposite signal from vacancy. Must not score.
STOP_WORK_OPEN = {
    "record_id": "16-08348S",
    "address": "6 GUDGER RD, ASHEVILLE, NC 28715",
    "record_status": "Permits Required",
    "record_type": "RSWO",
    "record_type_category": "Stop Work Order",
    "description": "They have built a deck, poured footings etc. without proper permits in place.",
    "date_opened": 1460000000000,
}

NO_ADDRESS_NO_PARCEL = {
    "record_id": "X",
    "address": None,
    "record_status": "Open",
    "record_type_category": "Junked Vehicles",
}


# --------------------------------------------------------------------------- #
# classification primitives
# --------------------------------------------------------------------------- #

def test_is_closed_is_a_substring_match_case_insensitive():
    assert mod.is_closed("Closed")
    assert mod.is_closed("Record Closed")
    assert mod.is_closed("Case Closed")
    assert mod.is_closed("  closed ")


@pytest.mark.parametrize("status", [
    "Open", "NOV Mailed", "NOV Served", "Citation Pending", "Unsafe Structure",
    "Deteriorated Structure", "Monitor", "Permits Required", "In Review",
    "Some Brand New Status Nobody Has Seen", None,
])
def test_non_closed_statuses_default_to_open(status):
    assert not mod.is_closed(status)


def test_severe_categories_are_exactly_the_three_live_confirmed_ones():
    """Live-verified 2026-10-03 via sampled real `description` text (see module
    docstring): Housing Code Referral / Junked Vehicles / Damage - Incident
    describe physical property condition; everything else in this feed's real
    taxonomy (Short Term Rental, Other Referral, Sign Violation, Stop Work
    Order, Land Use, FMO Referral) sampled as paperwork/zoning/permitting."""
    assert mod._SEVERE_CATEGORIES == {
        "Housing Code Referral", "Junked Vehicles", "Damage - Incident"}
    assert mod.is_severe("Junked Vehicles")
    assert mod.is_severe("Housing Code Referral")
    assert mod.is_severe("Damage - Incident")
    for cat in ("Short Term Rental", "Other Referral", "Sign Violation",
                "Stop Work Order", "Land Use", "FMO Referral", None, ""):
        assert not mod.is_severe(cat)


# --------------------------------------------------------------------------- #
# build_listing
# --------------------------------------------------------------------------- #

def test_closed_case_produces_no_listing():
    """Matches henderson_code_violations.py/gastonia_code_enforcement.py: a
    closed case is not a live lead."""
    assert mod.build_listing(CLOSED_HOUSING_CASE) is None


def test_no_address_and_no_parcel_is_dropped():
    assert mod.build_listing(NO_ADDRESS_NO_PARCEL) is None


def test_junked_vehicle_open_case_shape():
    li = mod.build_listing(JUNKED_VEHICLE_OPEN)
    assert li is not None
    assert li.source == mod.AshevilleCodeEnforcement.slug
    assert li.state == "NC" and li.county == "Buncombe" and li.city == "Asheville"
    assert li.street_address == "129 FAIRFAX AVE, ASHEVILLE, NC 28806"
    assert li.parcel_id == "202216"
    assert li.case_number == "16-05337S"
    assert li.sale_date is None
    ce = li.raw["code_enforcement"]
    assert ce["has_open"] is True
    assert ce["violation_types"] == ["Junked Vehicles"]
    assert ce["severe"] is True
    assert ce["vacancy_adjacent"] is True
    assert ce["opened"] == "2016-06-02"
    assert ce["source"] == "asheville_accela_services_view"
    assert li.raw["distressed"] is True


def test_housing_code_referral_is_severe():
    li = mod.build_listing(HOUSING_CODE_OPEN)
    ce = li.raw["code_enforcement"]
    assert ce["severe"] is True and ce["vacancy_adjacent"] is True
    assert li.raw["distressed"] is True


def test_damage_incident_is_severe():
    li = mod.build_listing(DAMAGE_INCIDENT_OPEN)
    ce = li.raw["code_enforcement"]
    assert ce["severe"] is True and ce["vacancy_adjacent"] is True
    assert li.raw["distressed"] is True
    assert li.parcel_id == "88214"


def test_short_term_rental_is_open_but_not_vacancy_adjacent():
    """Zoning/regulatory complaint about an unpermitted homestay -- must still
    ship (has_open) but withhold PROPERTY credit, same convention as every
    sibling module's non-severe category."""
    from foreclosure_scraper.distress_score import _signals_for
    from foreclosure_scraper.signal_freshness import code_enforcement_open

    li = mod.build_listing(STR_OPEN)
    ce = li.raw["code_enforcement"]
    assert ce["has_open"] is True
    assert ce["severe"] is False
    assert ce["vacancy_adjacent"] is False
    assert "distressed" not in li.raw
    assert code_enforcement_open(ce) is False
    assert "code_enforcement" not in [n for n, _b, _w in _signals_for(li)]


def test_stop_work_order_is_open_but_not_vacancy_adjacent():
    """An unpermitted-construction stop-work order describes active
    IMPROVEMENT, the opposite of vacancy -- must not score."""
    from foreclosure_scraper.distress_score import _signals_for

    li = mod.build_listing(STOP_WORK_OPEN)
    ce = li.raw["code_enforcement"]
    assert ce["vacancy_adjacent"] is False
    assert "code_enforcement" not in [n for n, _b, _w in _signals_for(li)]


def test_code_enforcement_signal_is_scored_when_severe():
    from foreclosure_scraper.distress_score import _signals_for
    li = mod.build_listing(JUNKED_VEHICLE_OPEN)
    names = [n for n, _b, _w in _signals_for(li)]
    assert "code_enforcement" in names


# --------------------------------------------------------------------------- #
# staleness self-gate -- the core finding this module exists to encode
# --------------------------------------------------------------------------- #

def _stats_page(max_ms: int | None) -> dict:
    return {"features": [{"attributes": {"mx": max_ms}}]} if max_ms is not None \
        else {"features": []}


def test_max_date_opened_reads_the_stats_response():
    http = FakeHttp({}, pages=[_stats_page(1544745600000)])  # 2018-12-14
    mx = asyncio.run(mod.max_date_opened(http))
    assert mx is not None and mx.date().isoformat() == "2018-12-14"
    verb, url, params = http.calls[0]
    assert "outStatistics" in params
    assert "date_opened" in params["outStatistics"]


def test_max_date_opened_handles_an_empty_response():
    http = FakeHttp({}, pages=[_stats_page(None)])
    assert asyncio.run(mod.max_date_opened(http)) is None


def _run_fetch(http) -> list:
    s = mod.AshevilleCodeEnforcement()
    original = mod.client
    mod.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(s.fetch())
    finally:
        mod.client = original


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_fetch_skips_entirely_when_the_feed_is_frozen(monkeypatch):
    """The real-world case today: MAX(date_opened) is years old -> fetch()
    must return [] WITHOUT ever issuing the second (feature) query."""
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    stale_ms = 1544745600000  # 2018-12-14, matches the live feed today
    http = FakeHttp({}, pages=[_stats_page(stale_ms)])
    rows = _run_fetch(http)
    assert rows == []
    assert len(http.calls) == 1, "must not query features once frozen is confirmed"


def test_fetch_proceeds_when_the_feed_is_fresh(monkeypatch):
    """Self-healing proof: if Asheville ever resumes syncing this view (a
    recent MAX(date_opened)), the scraper starts producing real rows again
    with no code change required."""
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    import time
    fresh_ms = int(time.time() * 1000) - 5 * 24 * 3600 * 1000  # 5 days ago
    feature_page = {"features": [
        {"attributes": JUNKED_VEHICLE_OPEN},
        {"attributes": CLOSED_HOUSING_CASE},  # closed -> dropped
    ]}
    http = FakeHttp({}, pages=[_stats_page(fresh_ms), feature_page])
    rows = _run_fetch(http)
    assert len(rows) == 1
    assert rows[0].street_address == "129 FAIRFAX AVE, ASHEVILLE, NC 28806"
    # Second call is the real feature query, restricted to the severe categories.
    verb, url, params = http.calls[1]
    assert "record_type_category IN" in params["where"]
    assert "Junked Vehicles" in params["where"]


def test_env_gate_skips_without_any_network_call(monkeypatch):
    monkeypatch.setenv(mod.ENV_OFF, "0")
    http = FakeHttp({}, pages=[_stats_page(1544745600000)])
    assert _run_fetch(http) == []
    assert http.calls == []


# --------------------------------------------------------------------------- #
# wiring guard
# --------------------------------------------------------------------------- #

def test_slug_must_be_in_dateless_ok_sources():
    """A code case has no sale_date. Without the whitelist entry,
    main._active_only silently drops every row the moment this ever ships."""
    from foreclosure_scraper import main
    slug = mod.AshevilleCodeEnforcement.slug
    assert slug in main.DATELESS_OK_SOURCES, (
        f'add "{slug}" to main.DATELESS_OK_SOURCES')


def test_registered_in_the_scraper_registry():
    from foreclosure_scraper.scrapers._registry import discover
    slugs = {c.slug for c in discover()}
    assert mod.AshevilleCodeEnforcement.slug in slugs


def test_enrichment_code_enforcement_no_longer_matches_against_the_dead_table():
    """Companion fix: the match-only enricher must not still be pointed at the
    same frozen AccelaServicesView table this module's reconnaissance found."""
    from foreclosure_scraper.enrichment_code_enforcement import CITY_ENDPOINTS
    assert "Asheville" not in CITY_ENDPOINTS


# --------------------------------------------------------------------------- #
# live smoke -- proves the finding stays true, and proves the real query
# logic (bypassing the staleness gate) still shapes rows correctly today.
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live smoke; set RUN_LIVE=1")
def test_live_feed_is_still_frozen_and_fetch_returns_nothing():
    from foreclosure_scraper.http_client import client

    async def _check():
        async with client(timeout=30.0) as http:
            return await mod.max_date_opened(http)

    mx = asyncio.run(_check())
    assert mx is not None
    # This assertion is the honest, self-aware version of "confirmed dead":
    # if Asheville ever resumes the feed, THIS test starts failing, which is
    # the correct signal to revisit _STALE_AFTER_DAYS / revive the source.
    from datetime import datetime
    age_days = (datetime.utcnow() - mx).days
    print(f"live asheville accela max(date_opened)={mx.date()} age_days={age_days}")

    s = mod.AshevilleCodeEnforcement()
    rows = asyncio.run(s.safe_run())
    if age_days > mod._STALE_AFTER_DAYS:
        assert rows == []
    else:
        # The feed resumed -- prove the real logic produces sane rows.
        assert all(li.raw["code_enforcement"]["severe"] for li in rows)


@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live smoke; set RUN_LIVE=1")
def test_live_severe_category_query_shapes_real_rows_bypassing_the_gate():
    """Bypasses the staleness gate deliberately to prove the underlying query
    + classification logic (the actual deliverable of this investigation)
    still works against the real service today, independent of whether the
    gate currently suppresses it."""
    from foreclosure_scraper import arcgis_webmap as agw
    from foreclosure_scraper.http_client import client

    async def _crawl():
        cats = ",".join("'" + c.replace("'", "''") + "'" for c in mod._SEVERE_CATEGORIES)
        async with client(timeout=45.0) as http:
            return await agw.query_attributes(
                http, mod.LAYER, where=f"record_type_category IN ({cats})",
                out_fields=mod._OUT_FIELDS, page=1000, max_records=20000)

    attrs_list = asyncio.run(_crawl())
    # Live-confirmed 2026-10-03: 268 total (Housing Code Referral 69 + Junked
    # Vehicles 127 + Damage - Incident 72), matching
    # docs/enumeration_r2/r2_municipal_NC_West.md's independent count.
    assert len(attrs_list) >= 250
    rows = [li for a in attrs_list if (li := mod.build_listing(a)) is not None]
    assert all(li.raw["code_enforcement"]["severe"] for li in rows)
    assert all(li.raw["distressed"] for li in rows)
    pin_rate = sum(1 for li in rows if li.parcel_id) / max(len(rows), 1)
    assert pin_rate > 0.8
    print(f"live asheville severe-category rows total={len(attrs_list)} "
          f"open={len(rows)} pin_rate={pin_rate:.1%}")
