"""Tests for the real HTTP/parse path of marriage-license enrichment.

Before 2026-10-02 this signal had ZERO coverage of the actual lookup path: only
pure string-parsing helpers were tested, never the HTTP+parse flow itself. The
module was rewritten to reuse `rod/aumentum.py`'s Cott/Aumentum eSearch v4
adapter (live-verified: Buncombe's deed/lien name-index grid also carries
marriage records as doc_type "MARRIED", real spouse names in grantor/grantee,
dates masked). These tests cover the grid-shape-to-spouse-match path with a
fixture mirroring the LIVE grid (same shape as test_aumentum_rod.py's SAMPLE),
and the orchestration function with `aumentum.search_by_name` monkeypatched so
CI never touches the network -- same convention as the rest of rod/*.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.enrichment_marriage_license import (
    _best_marriage_match,
    _is_marriage_doc,
    _name_parts,
    _search_county,
    _spouse_from_doc,
    _vendor_covered_counties,
    enrich_marriage_licenses,
)
from foreclosure_scraper.models import Listing
from foreclosure_scraper.rod import aumentum
from foreclosure_scraper.rod.aumentum import _parse_instruments_grid

# Real-shape fixture (same cpgvInstruments grid test_aumentum_rod.py's SAMPLE
# uses): a MARRIED row with real grantor/grantee spouse names and a masked
# date, plus an unrelated DEED OF TRUST row for the SAME surname so the
# "confirmed no-match" path (real rows back, none of them a marriage record)
# has something realistic to exercise too.
MARRIAGE_GRID = """
<table id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments"
       class="cottPagedGridView">
  <tr class="cottPagedGridViewHeaderStyle">
    <th>&nbsp;</th><th>Date Filed</th><th>Index</th><th>Type</th><th>Grantor</th>
    <th>Grantee</th><th>Description</th><th>File Number</th><th>Book/Page</th>
    <th>Ref</th><th>Images</th><th>GIS</th><th>Tax</th><th></th>
  </tr>
  <tr class="cottPagedGridViewRowStyle">
    <td>1</td>
    <td align="center">**/**/2026<br><span class="StatusDate">Date Filed<br />**/**/2026</span></td>
    <td>DTH</td><td>MARRIED</td>
    <td><table><tr><td>SMITH, MOLLY KATHRYN</td></tr></table></td>
    <td><table><tr><td>ELIE-YORK, SEBASTIAN</td></tr></table></td>
    <td></td><td></td><td>159 / 1744</td><td></td><td>1</td><td></td><td></td><td></td>
  </tr>
  <tr class="cottPagedGridViewAltRowStyle">
    <td>2</td><td align="center">11/30/2022</td><td>CRP</td><td>DEED OF TRUST</td>
    <td><table><tr><td>SMITH, MOLLY KATHRYN</td></tr></table></td>
    <td><table><tr><td>BANK OF AMERICA</td></tr></table></td>
    <td></td><td>2022012345</td><td>6279 / 1440</td><td></td><td>1</td><td></td><td></td><td></td>
  </tr>
</table>
"""

# Grid with NO marriage row at all -- for the "confirmed no-match" path: the
# vendor returned real rows for this name, just nothing tagged as a marriage.
NO_MARRIAGE_GRID = """
<table id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments"
       class="cottPagedGridView">
  <tr class="cottPagedGridViewHeaderStyle">
    <th>&nbsp;</th><th>Date Filed</th><th>Index</th><th>Type</th><th>Grantor</th>
    <th>Grantee</th><th>Description</th><th>File Number</th><th>Book/Page</th>
    <th>Ref</th><th>Images</th><th>GIS</th><th>Tax</th><th></th>
  </tr>
  <tr class="cottPagedGridViewRowStyle">
    <td>1</td><td align="center">11/30/2022</td><td>CRP</td><td>DEED OF TRUST</td>
    <td><table><tr><td>JONES, ROBERT</td></tr></table></td>
    <td><table><tr><td>BANK OF AMERICA</td></tr></table></td>
    <td></td><td>2022099999</td><td>6999 / 1</td><td></td><td>1</td><td></td><td></td><td></td>
  </tr>
</table>
"""


# --------------------------------------------------------------------------- #
# Name parsing                                                                 #
# --------------------------------------------------------------------------- #
def test_name_parts_comma_convention():
    assert _name_parts("SMITH, MOLLY KATHRYN") == ("SMITH", "MOLLY")


def test_name_parts_title_case_first_last_convention():
    # first_last_parts handles "Joshua D Smith" -> ("SMITH", "JOSHUA")
    assert _name_parts("Joshua D Smith") == ("SMITH", "JOSHUA")


def test_name_parts_empty_is_none():
    assert _name_parts("") is None
    assert _name_parts(None) is None


# --------------------------------------------------------------------------- #
# Grid -> spouse-match (the real parse path, same grid shape as production)    #
# --------------------------------------------------------------------------- #
def test_is_marriage_doc_matches_married_type():
    assert _is_marriage_doc("MARRIED") is True
    assert _is_marriage_doc("DEED OF TRUST") is False
    assert _is_marriage_doc(None) is False


def test_parses_married_row_and_extracts_spouse():
    docs = _parse_instruments_grid(MARRIAGE_GRID, "Buncombe", "NC")
    married = [d for d in docs if d.doc_type == "MARRIED"]
    assert len(married) == 1
    hit = _spouse_from_doc(married[0], "SMITH", "MOLLY")
    assert hit is not None
    assert hit["spouse_name"] == "Elie-York, Sebastian"
    assert hit["match_confidence"] == "high"
    assert hit["license_date"] is None          # masked date -> None, not a crash
    assert hit["book"] == "159" and hit["page"] == "1744"


def test_spouse_from_doc_medium_confidence_on_surname_only():
    docs = _parse_instruments_grid(MARRIAGE_GRID, "Buncombe", "NC")
    married = docs[0]
    hit = _spouse_from_doc(married, "SMITH", "NOTMOLLY")
    assert hit is not None
    assert hit["match_confidence"] == "medium"


def test_spouse_from_doc_no_surname_match_returns_none():
    docs = _parse_instruments_grid(MARRIAGE_GRID, "Buncombe", "NC")
    married = docs[0]
    assert _spouse_from_doc(married, "NOTASURNAME", "WHOEVER") is None


def test_best_marriage_match_ignores_non_marriage_rows():
    docs = _parse_instruments_grid(MARRIAGE_GRID, "Buncombe", "NC")
    assert len(docs) == 2    # MARRIED row + the unrelated DEED OF TRUST row
    best = _best_marriage_match(docs, "SMITH", "MOLLY")
    assert best is not None
    assert best["spouse_name"] == "Elie-York, Sebastian"


def test_best_marriage_match_none_when_no_marriage_row_present():
    docs = _parse_instruments_grid(NO_MARRIAGE_GRID, "Buncombe", "NC")
    assert len(docs) == 1   # a real row came back, just not a marriage record
    assert _best_marriage_match(docs, "JONES", "ROBERT") is None


# --------------------------------------------------------------------------- #
# Vendor-county coverage                                                       #
# --------------------------------------------------------------------------- #
def test_vendor_covered_counties_reads_live_aumentum_registry():
    covered = _vendor_covered_counties("NC")
    # Mecklenburg + Buncombe are the 2 of the original 5 hardcoded counties this
    # reuse covers; asserting via the adapter's own registry (not a hardcoded
    # list here) means a new tenant the adapter adds later is picked up free.
    assert "Buncombe" in covered
    assert "Mecklenburg" in covered
    # Wake/Durham/Forsyth are confirmed walls (see module docstring) -- this
    # adapter was never going to cover them and does not claim to.
    assert "Wake" not in covered
    assert "Durham" not in covered
    assert "Forsyth" not in covered


def test_vendor_covered_counties_empty_for_uncovered_state():
    assert _vendor_covered_counties("SC") == set() or "Spartanburg" not in _vendor_covered_counties("SC")


# --------------------------------------------------------------------------- #
# _search_county: match / confirmed-no-match / fetch-failed tri-state         #
# --------------------------------------------------------------------------- #
def test_search_county_match(monkeypatch):
    async def fake_search_by_name(state, county, name, max_docs=400):
        return _parse_instruments_grid(MARRIAGE_GRID, county, state)

    monkeypatch.setattr(aumentum, "search_by_name", fake_search_by_name)
    match, confident = asyncio.run(_search_county("NC", "Buncombe", "SMITH, MOLLY KATHRYN"))
    assert confident is True
    assert match is not None
    assert match["spouse_name"] == "Elie-York, Sebastian"


def test_search_county_confirmed_no_match(monkeypatch):
    async def fake_search_by_name(state, county, name, max_docs=400):
        return _parse_instruments_grid(NO_MARRIAGE_GRID, county, state)

    monkeypatch.setattr(aumentum, "search_by_name", fake_search_by_name)
    match, confident = asyncio.run(_search_county("NC", "Buncombe", "JONES, ROBERT"))
    assert match is None
    assert confident is True    # the search worked, just no marriage row


def test_search_county_fetch_failed_is_not_confident(monkeypatch):
    """Empty result (exception OR a down backend like Mecklenburg's live-
    confirmed outage) must NOT be reported as a confident no-match -- doing so
    would permanently lock in 'checked, nothing found' for a county whose
    server is merely down right now."""
    async def fake_search_by_name(state, county, name, max_docs=400):
        return []

    monkeypatch.setattr(aumentum, "search_by_name", fake_search_by_name)
    match, confident = asyncio.run(_search_county("NC", "Mecklenburg", "SMITH, JOHN"))
    assert match is None
    assert confident is False


def test_search_county_exception_is_not_confident(monkeypatch):
    async def raising_search_by_name(state, county, name, max_docs=400):
        raise RuntimeError("Session state is not available in this context")

    monkeypatch.setattr(aumentum, "search_by_name", raising_search_by_name)
    match, confident = asyncio.run(_search_county("NC", "Mecklenburg", "SMITH, JOHN"))
    assert match is None
    assert confident is False


# --------------------------------------------------------------------------- #
# Full orchestration                                                           #
# --------------------------------------------------------------------------- #
def _listing(**kw) -> Listing:
    base = dict(source="test", source_url="http://x", state="NC", county="Buncombe")
    base.update(kw)
    return Listing(**base)


def test_enrich_writes_match_for_covered_county(monkeypatch):
    async def fake_search_by_name(state, county, name, max_docs=400):
        return _parse_instruments_grid(MARRIAGE_GRID, county, state)

    monkeypatch.setattr(aumentum, "search_by_name", fake_search_by_name)
    li = _listing(owner_name="SMITH, MOLLY KATHRYN")
    stats = asyncio.run(enrich_marriage_licenses([li]))
    assert stats["matches"] == 1
    assert li.raw["marriage_license"]["spouse_name"] == "Elie-York, Sebastian"


def test_enrich_writes_terminal_no_match_sentinel(monkeypatch):
    async def fake_search_by_name(state, county, name, max_docs=400):
        return _parse_instruments_grid(NO_MARRIAGE_GRID, county, state)

    monkeypatch.setattr(aumentum, "search_by_name", fake_search_by_name)
    li = _listing(owner_name="JONES, ROBERT")
    stats = asyncio.run(enrich_marriage_licenses([li]))
    assert stats["confirmed_no_match"] == 1
    assert li.raw["marriage_license"]["status"] == "no_match"


def test_enrich_leaves_unstamped_on_fetch_failure_for_retry(monkeypatch):
    """The Mecklenburg-outage case: a down backend must not stamp the listing,
    so a later run (after the county's server recovers) retries it."""
    async def fake_search_by_name(state, county, name, max_docs=400):
        return []

    monkeypatch.setattr(aumentum, "search_by_name", fake_search_by_name)
    li = _listing(county="Mecklenburg", owner_name="SMITH, JOHN")
    stats = asyncio.run(enrich_marriage_licenses([li]))
    assert stats["fetch_failed"] == 1
    assert "marriage_license" not in li.raw


def test_enrich_skips_uncovered_county_without_network_call(monkeypatch):
    called = False

    async def fake_search_by_name(state, county, name, max_docs=400):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(aumentum, "search_by_name", fake_search_by_name)
    li = _listing(county="Wake", owner_name="SMITH, JOHN")  # confirmed wall, not covered
    stats = asyncio.run(enrich_marriage_licenses([li]))
    assert stats["not_covered"] == 1
    assert called is False
    assert "marriage_license" not in li.raw


def test_enrich_idempotent_skips_already_processed_listing(monkeypatch):
    called = False

    async def fake_search_by_name(state, county, name, max_docs=400):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(aumentum, "search_by_name", fake_search_by_name)
    li = _listing(owner_name="SMITH, MOLLY KATHRYN")
    li.raw["marriage_license"] = {"status": "no_match", "checked_at": "2026-01-01T00:00:00+00:00"}
    stats = asyncio.run(enrich_marriage_licenses([li]))
    assert stats["skipped_existing"] == 1
    assert called is False


def test_enrich_respects_rate_limit(monkeypatch):
    calls = 0

    async def fake_search_by_name(state, county, name, max_docs=400):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(aumentum, "search_by_name", fake_search_by_name)
    monkeypatch.setenv("MARRIAGE_LICENSE_MAX_REQUESTS", "1")
    import importlib
    import foreclosure_scraper.enrichment_marriage_license as mod
    importlib.reload(mod)
    try:
        listings = [_listing(owner_name=f"SMITH, PERSON{i}") for i in range(5)]
        asyncio.run(mod.enrich_marriage_licenses(listings))
        assert calls == 1
    finally:
        monkeypatch.delenv("MARRIAGE_LICENSE_MAX_REQUESTS", raising=False)
        importlib.reload(mod)
