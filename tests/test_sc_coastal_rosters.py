"""Coastal SC Master-in-Equity sale-roster scraper (publicindex + county-native
GIS geo-resolution).

Added 2026-06-24 for the COASTAL track. Feeds the previously-empty oceanfront /
downtown-Charleston gate (main._check_oceanfront) by scraping the coastal SC
counties' Master-in-Equity foreclosure-SALE rosters and resolving each parcel
TMS/PIN to lat/lng at scrape time, so the near-beach ones can pass the
ingest-time scope gate (which needs coordinates, not just an address). Geo
resolution moved off the shared, token-walled SCDOT MapServer onto each
county's own free endpoint on 2026-10-02 (_COASTAL_SC_GIS) -- see that dict's
docstring in the module for per-county live-verification notes.
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from foreclosure_scraper.scrapers.counties_sc.sc_coastal_rosters import (
    COASTAL_COUNTIES,
    COUNTY_SALE_CODES,
    SCCoastalRosters,
    _COASTAL_SC_GIS,
    _PARCEL_CELL_RE,
    _query_layer,
    _resolve_tms,
    _tms_candidates,
    parse_sale_roster,
)

_SEL = "https://publicindex.sccourts.org/horry/courtrosters/RosterSelection.aspx"

# Horry MO layout (13 cols): "Master/Sale before Master", TMS at the 10th cell.
_HORRY_ROW = """<table><tr class="standardRow">
<td>1</td><td>06/01/2026</td><td>10:00 AM</td><td></td><td>Master/Sale before Master</td>
<td>Bank-PLT</td><td>04/01/2026</td>
<td><a href="CaseDetails.aspx?CaseID=1">2025CP2609320</a><br/>Bank vs Sherry Battle-Edmonds, defendant</td>
<td>Foreclosure 420</td><td>1860801332</td><td>Atty</td><td></td><td>Judgment $250,000.00</td></tr></table>"""

# Beaufort SALE layout (9 cols): R-prefixed PIN at the 8th cell, $ in last cell.
_BEAUFORT_ROW = """<table><tr class="altRow">
<td>1</td>
<td>2025CP0702550 Colleton River Co , plaintiff, et al vs Lawrence Crowley, defendant</td>
<td>Barry L. Johnson  (843) 555-1212</td><td></td><td>10/16/2025</td>
<td>Foreclosure 420</td><td>Sale; Deficiency Waived</td>
<td>R60002500000480000</td><td>Judgment $436,513.24. Deficiency Waived</td></tr></table>"""

# A row that is NOT a foreclosure (must be skipped).
_NON_FC_ROW = """<table><tr class="standardRow">
<td>1</td><td>06/01/2026</td><td>9:00 AM</td><td></td><td>Surplus Petition</td>
<td>Someone</td><td>04/01/2026</td><td><a>2025CP0700001</a></td>
<td>Debt Collection 110</td><td>1234567890</td></tr></table>"""

# A foreclosure row with NO parcel identifier (Beaufort MO hearing docket style)
# — must be skipped because it can't be geo-resolved for the near-beach gate.
_FC_NO_PARCEL_ROW = """<table><tr class="standardRow">
<td>1</td><td>07/17/2026</td><td>9:30 AM</td><td></td><td>Surplus Petition</td>
<td>Asset Recovery Inc-OTH</td><td>04/15/2026</td>
<td>2021CP0701402 Bank , plaintiff vs James Barkley, defendant</td>
<td>Foreclosure 420</td><td>Genevieve Speese Johnson  (757) 999-2099</td>
<td>James Calvin Barkley</td><td></td></tr></table>"""


def test_parses_horry_mo_layout():
    out = parse_sale_roster(_HORRY_ROW, _SEL, "Horry")
    assert len(out) == 1
    li = out[0]
    assert li.county == "Horry"
    assert li.state == "SC"
    assert li.case_number == "2025CP2609320"
    assert li.parcel_id == "1860801332"
    assert li.foreclosure_process == "judicial"
    assert li.opening_bid == 250000.0
    assert li.source == "counties_sc.sc_coastal_rosters"


def test_parses_beaufort_sale_layout():
    out = parse_sale_roster(_BEAUFORT_ROW, _SEL, "Beaufort")
    assert len(out) == 1
    li = out[0]
    assert li.county == "Beaufort"
    assert li.case_number == "2025CP0702550"
    assert li.parcel_id == "R60002500000480000"
    assert li.opening_bid == 436513.24


def test_skips_non_foreclosure_rows():
    assert parse_sale_roster(_NON_FC_ROW, _SEL, "Beaufort") == []


def test_skips_foreclosure_rows_without_parcel():
    # No parcel -> can't resolve to lat/lng -> can't pass the near-beach gate.
    assert parse_sale_roster(_FC_NO_PARCEL_ROW, _SEL, "Beaufort") == []


def test_parcel_cell_regex_accepts_real_formats():
    assert _PARCEL_CELL_RE.match("1860801332")          # Horry bare TMS
    assert _PARCEL_CELL_RE.match("369-110-100-30")      # Horry dashed
    assert _PARCEL_CELL_RE.match("R60002500000480000")  # Beaufort R-PIN
    assert _PARCEL_CELL_RE.match("R600 025 000 0048 00")
    assert not _PARCEL_CELL_RE.match("Surplus Petition")
    assert not _PARCEL_CELL_RE.match("9:30 AM")
    assert not _PARCEL_CELL_RE.match("5")


def test_tms_candidates_numeric_and_grouped():
    # dashed numeric -> add dash-free form
    assert "36911010030" in _tms_candidates("369-110-100-30")
    # R-PIN -> add the spaced 3-3-3-4-4 grouped form
    c = _tms_candidates("R60002500000480000")
    assert "R600 025 000 0048 0000" in c
    # truncated trailing group ("...0185 00") -> padded "...0185 0000"
    c2 = _tms_candidates("R100 024 000 0185 00")
    assert "R100 024 000 0185 0000" in c2


def test_charleston_excluded():
    # Charleston's publicindex courtrosters app exposes NO Master roster, so it
    # must not be crawled here (downtown-Charleston leads come from elsewhere).
    assert "charleston" not in COASTAL_COUNTIES
    assert "charleston" not in COUNTY_SALE_CODES


def test_county_codes_cover_every_county():
    assert set(COUNTY_SALE_CODES) == set(COASTAL_COUNTIES)


def test_horry_now_crawled():
    """2026-10-02: Horry was documented (this file's own _HORRY_ROW fixture
    predates this test) but never actually added to COASTAL_COUNTIES /
    COUNTY_SALE_CODES, so it was never crawled. Added once a working
    county-native geo-resolver existed for it (_COASTAL_SC_GIS["Horry"])."""
    assert COASTAL_COUNTIES.get("horry") == "Horry"
    assert COUNTY_SALE_CODES.get("horry") == ("MO",)


def test_tms_candidates_generalizes_beyond_r_prefix():
    """Beaufort's live parcel roll has non-R letter-prefixed PINs too (e.g.
    "M100 006 000 0611 0000", confirmed live 2026-10-02) even though every
    roster TMS sampled this session happened to be R-prefixed -- the regrouping
    logic must not be hardcoded to the letter R."""
    c = _tms_candidates("M60002500000480000")
    assert "M600 025 000 0048 0000" in c
    c2 = _tms_candidates("M100 006 000 0611 00")
    assert "M100 006 000 0611 0000" in c2


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    slugs = {s.slug for s in all_scrapers()}
    assert "counties_sc.sc_coastal_rosters" in slugs


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live SC publicindex + SCDOT — slow; set RUN_NETWORK_TESTS=1",
)
def test_live_yields_geocoded_coastal_rows():
    out = list(asyncio.run(SCCoastalRosters().fetch()))
    assert out, "expected at least one coastal foreclosure row"
    geocoded = [li for li in out if li.latitude is not None and li.longitude is not None]
    # The whole point: rows must carry coordinates so the near-beach gate works.
    assert geocoded, "expected coordinates resolved via SCDOT"
    for li in out:
        assert li.state == "SC"
        assert li.county in COASTAL_COUNTIES.values()


def test_select_sale_rosters_excludes_hearings_picks_newest():
    """Roster selection must keep only foreclosure-SALE rosters and order by
    sale DATE (newest first), not lexicographic URL — the original stale-roster
    bug. Mirrors the real Horry MO page (sales + CPNJ/settlement hearings)."""
    from foreclosure_scraper.scrapers.counties_sc.sc_coastal_rosters import (
        _select_sale_rosters, _is_sale_roster, _roster_date,
    )
    html = (
        '<a href="RosterDetails.aspx?CourtAgency=26003&RosterID=419&RosterCode=MO">'
        'Foreclosure Sale - February 2, 2026 - 11:00 am</a>'
        '<a href="RosterDetails.aspx?CourtAgency=26003&RosterID=422&RosterCode=MO">'
        'Foreclosure Sale - May 4, 2026 - 11:00am</a>'
        '<a href="RosterDetails.aspx?CourtAgency=26003&RosterID=430&RosterCode=MO">'
        'Foreclosure Sale - July 6, 2026</a>'
        '<a href="RosterDetails.aspx?CourtAgency=26002&RosterID=519&RosterCode=MO">'
        'CPNJ Motions ( 7/6/2026 - 7/8/2026) Honorable Will Wheeler 3D</a>'
        '<a href="RosterDetails.aspx?CourtAgency=26002&RosterID=514&RosterCode=MO">'
        'SETTLEMENT HEARINGS - Honorable G. D. Morgan</a>'
    )
    sel = _select_sale_rosters(html, ("MO",))
    ids = [h.split("RosterID=")[1].split("&")[0] for h, _ in sel]
    assert "519" not in ids and "514" not in ids   # hearing dockets excluded
    assert ids[0] == "430"                          # newest sale (July 6) first
    assert _is_sale_roster("Foreclosure Sale - July 6, 2026")
    assert not _is_sale_roster("CPNJ Motions")
    assert not _is_sale_roster("SETTLEMENT HEARINGS")
    assert _roster_date("Foreclosure Sale - July 6, 2026").date().isoformat() == "2026-07-06"


# ---- _geo_enrich -> _apply_attrs street_address wiring (2026-10-02 audit) --------
#
# _geo_enrich() resolves a roster row's bare TMS via SCDOT and calls
# enrichment_arcgis._apply_attrs(li, attrs) directly -- with no address of its
# own to seed from, unlike every other _apply_attrs caller (enrichment_
# address_backfill / enrichment_parcel_lookup both duplicate a site_address
# pick-and-fill locally before calling it). Confirmed live 2026-10-01: lat/lng
# resolved on sampled rows while street_address stayed null on all of them.
# Fixed centrally in _apply_attrs itself. SCDOT_BASE (smpesri.scdot.org) is
# itself live-confirmed token-walled again today (2026-10-02, HTTP 200 +
# {"error":{"code":499,"message":"Token Required"}} on every coastal layer),
# so SCCoastalRosters().fetch() can't demonstrate this end-to-end against live
# data right now -- these two tests pin the fix directly against the real
# field shapes docs/sc_gis_endpoints_coastal.md captured live for Beaufort
# (single GisFile_-prefixed column) and Georgetown (split StreetNumber +
# StreetName, no single situs column) before that doc's SCDOT replacement
# effort. Both shapes are already in enrichment_arcgis.FIELD_ALIASES /
# _stitch_situs's fallback.

def test_apply_attrs_fills_street_address_from_beaufort_situs():
    from foreclosure_scraper.enrichment_arcgis import _apply_attrs
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="counties_sc.sc_coastal_rosters", source_url="https://x", listing_type=ListingType.FORECLOSURE_SALE,
                 state="SC", county="Beaufort")
    assert li.street_address is None
    filled = _apply_attrs(li, {"GisFile_Owner1": "PRYOR JULIUS E",
                                "GisFile_SitusAddre": "20 SMITH RD",
                                "GisFile_Appraised": 185000})
    assert li.street_address == "20 SMITH RD"
    assert filled > 0


def test_apply_attrs_fills_street_address_from_georgetown_split_situs():
    """No single situs column -- StreetNumber + StreetName must stitch."""
    from foreclosure_scraper.enrichment_arcgis import _apply_attrs
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="counties_sc.sc_coastal_rosters", source_url="https://x", listing_type=ListingType.FORECLOSURE_SALE,
                 state="SC", county="Georgetown")
    filled = _apply_attrs(li, {"Owner1": "MCCONNELL PATRICIA W LIFE ESTATE",
                                "StreetNumber": "615", "StreetName": "S CEDAR AVE",
                                "TMS": "123-45-67-890"})
    assert li.street_address == "615 S CEDAR AVE"
    assert filled > 0


def test_apply_attrs_never_overwrites_an_existing_street_address():
    from foreclosure_scraper.enrichment_arcgis import _apply_attrs
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="counties_sc.sc_coastal_rosters", source_url="https://x", listing_type=ListingType.FORECLOSURE_SALE,
                 state="SC", county="Beaufort", street_address="1 REAL ST")
    _apply_attrs(li, {"GisFile_SitusAddre": "20 SMITH RD"})
    assert li.street_address == "1 REAL ST"


def test_apply_attrs_skips_gis_placeholder_addresses():
    from foreclosure_scraper.enrichment_arcgis import _apply_attrs
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="counties_sc.sc_coastal_rosters", source_url="https://x", listing_type=ListingType.FORECLOSURE_SALE,
                 state="SC", county="Beaufort")
    _apply_attrs(li, {"GisFile_SitusAddre": "NO ADDRESS ASSIGNED"})
    assert li.street_address is None


def test_scdot_base_token_wall_confirmed_live():
    """Live pin for WHY this scraper no longer queries SCDOT at all (2026-10-02
    rebuild moved geo-resolution onto _COASTAL_SC_GIS's county-native
    endpoints instead) -- the shared SCDOT host is still walled, re-confirmed
    the same day the county-native replacement shipped. Network-dependent;
    skip offline rather than fail."""
    import httpx

    from foreclosure_scraper.enrichment_arcgis import SCDOT_BASE

    try:
        r = httpx.get(f"{SCDOT_BASE}/7/query",
                      params={"where": "1=1", "outFields": "*",
                              "resultRecordCount": "1", "f": "json"},
                      timeout=15.0)
    except httpx.HTTPError:
        pytest.skip("network unavailable")
    if r.status_code != 200:
        pytest.skip(f"unexpected status {r.status_code}, not asserting wall state")
    data = r.json()
    err = data.get("error")
    if not err:
        pytest.skip("SCDOT is unwalled right now -- informational only, not a regression")
    assert err.get("code") == 499


# ---- _COASTAL_SC_GIS / _query_layer / _resolve_tms (2026-10-02 rebuild) ----------
#
# Replaces the token-walled SCDOT resolver with per-county county-native
# endpoints. Live-verified this session against REAL roster rows: Beaufort
# 4/4 and Horry 14/19 TMS values resolved (see _COASTAL_SC_GIS's docstring for
# the full account, including the two counties -- Georgetown/Colleton -- that
# had zero active rosters today and so couldn't be checked against a real
# roster TMS). The tests below pin the merge/matching LOGIC deterministically
# against mock transports rather than depending on live roster cadence.

def test_coastal_sc_gis_covers_every_crawled_county():
    """Every county this scraper actually crawls must have a geo-resolver
    entry, and every configured layer must carry the fields _query_layer
    needs."""
    for county in COASTAL_COUNTIES.values():
        cfg = _COASTAL_SC_GIS.get(county)
        assert cfg, f"no _COASTAL_SC_GIS entry for crawled county {county!r}"
        assert cfg["layers"], f"{county} has no layers configured"
        for layer in cfg["layers"]:
            assert layer["url"].startswith("https://")
            assert layer["id_fields"]


def test_resolve_tms_merges_horry_cama_and_address_layers():
    """Horry splits CAMA (owner/mailing/deed/sale/value + parcel geometry) and
    situs address across two separate layers joined by the same TMS
    (confirmed live 2026-10-02 -- see module docstring). _resolve_tms must
    query both and merge them into one attrs dict without the second layer's
    lack of geometry clobbering the first layer's centroid."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/24/query" in str(request.url):
            return httpx.Response(200, json={
                "features": [{
                    "attributes": {"TMS": "1791604022", "OwnerName": "GOMEZ IGNACIO MANUEL",
                                   "OwnerStreet": "1 MAIN ST", "DeedBook": "1234",
                                   "DeedPage": "56", "SaleDate": 1600000000000,
                                   "MarketProp": 150000},
                    "geometry": {"rings": [[[-78.97, 33.67], [-78.98, 33.68], [-78.97, 33.67]]]},
                }]
            })
        if "/22/query" in str(request.url):
            return httpx.Response(200, json={
                "features": [{
                    "attributes": {"TMS": "1791604022", "ADDRESS": "181 DRY VALLEY LP",
                                   "CITY": "Myrtle Beach", "STATE": "SC", "ZIPCODE": 29588},
                }]
            })
        return httpx.Response(200, json={"features": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await _resolve_tms(c, "Horry", "1791604022")

    attrs = asyncio.run(run())
    assert attrs is not None
    assert attrs["_match_confident"] is True
    assert attrs["_centroid"] is not None            # from layer 24 (CAMA)
    assert attrs["OwnerName"] == "GOMEZ IGNACIO MANUEL"  # from layer 24
    assert attrs["ADDRESS"] == "181 DRY VALLEY LP"       # from layer 22 (join)

    from foreclosure_scraper.enrichment_arcgis import _apply_attrs
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="counties_sc.sc_coastal_rosters", source_url="https://x",
                 listing_type=ListingType.FORECLOSURE_SALE, state="SC", county="Horry",
                 parcel_id="1791604022")
    _apply_attrs(li, attrs)
    assert li.latitude is not None and li.longitude is not None
    assert li.street_address == "181 DRY VALLEY LP"
    assert li.tax_value == 150000.0
    assert li.raw["gis"]["owner"] == "GOMEZ IGNACIO MANUEL"
    assert li.raw["gis"]["mailing"] == "1 MAIN ST"
    assert li.raw["gis"]["last_sale"]["book"] == "1234"


def test_resolve_tms_returns_none_when_every_layer_misses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"features": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await _resolve_tms(c, "Beaufort", "R999999999999999999")

    assert asyncio.run(run()) is None


def test_resolve_tms_unknown_county_returns_none():
    async def run():
        async with httpx.AsyncClient() as c:
            return await _resolve_tms(c, "Nowhere County", "12345")

    assert asyncio.run(run()) is None


def test_query_layer_regrouped_candidate_matches_beaufort_style_pin():
    """Beaufort's roster gives a bare R-PIN; the live layer stores it spaced
    3-3-3-4-4. _query_layer must try the regrouped form, not just the raw
    roster string."""
    seen_wheres: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        where = request.url.params.get("where", "")
        seen_wheres.append(where)
        if "ParcelPIN='R600 025 000 0048 0000'" in where:
            return httpx.Response(200, json={
                "features": [{
                    "attributes": {"ParcelPIN": "R600 025 000 0048 0000"},
                    "geometry": {"x": -80.7, "y": 32.2},
                }]
            })
        return httpx.Response(200, json={"features": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await _query_layer(c, _COASTAL_SC_GIS["Beaufort"]["layers"][0]["url"],
                                       ("ParcelPIN", "GisFile_PIN"), "R60002500000480000")

    attrs = asyncio.run(run())
    assert attrs is not None
    assert attrs["_centroid"] == (32.2, -80.7)
    assert any("R600 025 000 0048 0000" in w for w in seen_wheres)


def test_query_layer_like_fallback_rejects_ambiguous_multi_hit():
    """The last-resort LIKE fallback must not pick a result when it's
    ambiguous (more than one feature matched) -- better to leave a lead
    ungeocoded than silently attach the wrong parcel's coordinates."""

    def handler(request: httpx.Request) -> httpx.Response:
        where = request.url.params.get("where", "")
        if "LIKE" in where:
            return httpx.Response(200, json={
                "features": [
                    {"attributes": {"TMS": "01-0101-001-00-00"}},
                    {"attributes": {"TMS": "99-0101-001-00-99"}},
                ]
            })
        return httpx.Response(200, json={"features": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await _query_layer(c, _COASTAL_SC_GIS["Georgetown"]["layers"][0]["url"],
                                       ("TMS",), "01-0101-001-00-00")

    assert asyncio.run(run()) is None
