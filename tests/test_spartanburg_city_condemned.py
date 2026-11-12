"""City of Spartanburg SC Master Condemnation List (PDF).

Offline tests run against SAVED WORD GEOMETRY from the real document
(``tests/fixtures/spartanburg_city_condemned_words.json`` — pages 1 and 2,
verbatim text/x0/top for every word). Storing coordinates rather than the
binary keeps the fixture small and readable while still driving the real code
path: column assignment by x0, line bucketing, chrome suppression, and the
multi-line record folding that a four-heir property requires.

Page 1 is included specifically because it opens with the six-line disclaimer
paragraph whose words spill across every column — that text was swept into the
first real record's owner list before the buffer-reset guard existed.

RUN_LIVE=1 adds an opt-in smoke test that fetches the live PDF.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_sc import spartanburg_city_condemned as mod

FIX = Path(__file__).parent / "fixtures"


class FakePage:
    """Stands in for a pdfplumber Page — only extract_words() is used."""

    def __init__(self, words):
        self._words = words

    def extract_words(self):
        return list(self._words)


def _pages() -> list[FakePage]:
    return [FakePage(w) for w in
            json.loads((FIX / "spartanburg_city_condemned_words.json").read_text())]


def _records() -> list[dict]:
    recs = []
    for page in _pages():
        recs.extend(mod.records_from_lines(mod.page_lines(page)))
    return recs


def _listings() -> list:
    return [li for li in (mod.build_listing(r) for r in _records()) if li]


# --------------------------------------------------------------------------- #
# column geometry
# --------------------------------------------------------------------------- #

def test_column_boundaries_are_contiguous_and_ordered():
    names = [n for n, _lo, _hi in mod._COLS]
    assert names == ["address", "tax_map", "owner", "owner_address",
                     "date_condemned", "inspector"]
    for (_n1, _lo1, hi1), (_n2, lo2, _hi2) in zip(mod._COLS, mod._COLS[1:]):
        assert hi1 == lo2, "a gap or overlap would silently drop words"


def test_split_columns_assigns_a_real_anchor_line():
    words = [
        {"text": "281", "x0": 52.0}, {"text": "Caulder", "x0": 63.0},
        {"text": "Cir.", "x0": 85.0}, {"text": "7-16-07-082.00", "x0": 157.0},
        {"text": "BC&K", "x0": 246.0}, {"text": "Investments", "x0": 262.0},
        {"text": "LLC", "x0": 294.0}, {"text": "160", "x0": 373.0},
        {"text": "Orchard", "x0": 384.0}, {"text": "Inman,", "x0": 414.0},
        {"text": "SC", "x0": 433.0}, {"text": "29349", "x0": 441.0},
        {"text": "6/30/2011", "x0": 561.0}, {"text": "TRE", "x0": 669.0},
    ]
    cells = mod.split_columns(words)
    assert cells["address"] == "281 Caulder Cir."
    assert cells["tax_map"] == "7-16-07-082.00"
    assert cells["owner"] == "BC&K Investments LLC"
    assert cells["owner_address"] == "160 Orchard Inman, SC 29349"
    assert cells["date_condemned"] == "6/30/2011"
    assert cells["inspector"] == "TRE"


# --------------------------------------------------------------------------- #
# chrome suppression — the disclaimer bug
# --------------------------------------------------------------------------- #

def test_disclaimer_text_never_becomes_an_owner():
    """The page-1 disclaimer spans all six columns. Before the buffer reset it
    landed in the first record's owner list ('shall the act of distribution
    co...' was emitted as an owner name)."""
    recs = _records()
    assert recs
    blob = " ".join(o for r in recs for o in r["owners"])
    for phrase in ("act of distribution", "warranty", "DISCLAIMER",
                   "responsibility of the data user", "reliability"):
        assert phrase.lower() not in blob.lower()
    first = recs[0]
    assert first["address"] == "323 Allen Ct."
    assert first["owners"][0] == "Carolina Investments Co."


def test_header_and_footer_rows_are_not_records():
    recs = _records()
    for r in recs:
        assert "PROPERTY ADDRESS" not in (r["address"] or "")
        assert "Updated as of" not in " ".join(r["owners"])


def test_chrome_line_clears_the_continuation_buffer():
    """A record must never inherit continuation lines from the page above it."""
    lines = [
        {"address": "", "tax_map": "", "owner": "STRAY OWNER",
         "owner_address": "", "date_condemned": "", "inspector": ""},
        {"address": "", "tax_map": "", "owner": "PROPERTY ADDRESS TAX MAP OWNER",
         "owner_address": "", "date_condemned": "", "inspector": ""},
        {"address": "1 Main St.", "tax_map": "7-16-07-082.00", "owner": "REAL OWNER",
         "owner_address": "PO Box 1", "date_condemned": "1/2/2020", "inspector": "EG"},
    ]
    recs = mod.records_from_lines(lines)
    assert len(recs) == 1
    assert recs[0]["owners"] == ["REAL OWNER"]


# --------------------------------------------------------------------------- #
# multi-line record folding
# --------------------------------------------------------------------------- #

def test_continuation_lines_precede_their_anchor_and_fold_into_one_record():
    """714 S. Center St. is a four-owner property; the three extra owners print
    on the lines ABOVE the tax-map line. Text-order extraction interleaves them
    with the previous record."""
    r = next(r for r in _records() if r["address"] == "714 S. Center St.")
    assert r["tax_map"] == "7-11-11-053.00"
    assert r["owners"] == ["Margaret McNalley", "Dorie Thomas",
                           "Emmanuel Jeter", "Cecil Diane J. Ross"]
    assert len(r["owner_addresses"]) == 4
    assert r["date_condemned"] == datetime(2020, 5, 27)


def test_the_record_above_a_multi_owner_block_keeps_only_its_own_owner():
    r = next(r for r in _records() if r["address"] == "650 S. Center St.")
    assert r["owners"] == ["Liller Miller"]


def test_a_property_address_that_wraps_is_joined():
    """'724 Ashley Hwy.' prints on the continuation line and its building id on
    the anchor line."""
    r = next(r for r in _records() if r["tax_map"] == "7-08-13-182.00")
    assert r["address"] == "724 Ashley Hwy. (Bldg. ID: 186063)"


def test_owner_block_preserves_a_name_the_line_split_cut_in_half():
    """'Spartanburg County Youth' / 'Sports' is one owner wrapped across lines;
    'Gary & Anita Morton' / 'Cari Rodriguez' is two owners. The PDF prints them
    identically, so BOTH readings are kept rather than guessing."""
    r = next(r for r in _records() if r["address"] == "176 Amos St.")
    assert r["owners"] == ["Spartanburg County Youth", "Sports"]
    assert r["owner_block"] == "Spartanburg County Youth Sports"
    li = mod.build_listing(r)
    assert li.raw["code_enforcement"]["owner_block"] == "Spartanburg County Youth Sports"


# --------------------------------------------------------------------------- #
# field parsing
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,want", [
    ("7-12-09-058.11", "7-12-09-058.11"),
    ("7-12-09-058-14", "7-12-09-058.14"),   # dash variant -> one parcel key
    ("no parcel here", None),
    ("", None), (None, None),
])
def test_norm_tms(raw, want):
    assert mod._norm_tms(raw) == want


def test_the_two_printed_tms_spellings_collapse_to_one_dedupe_key():
    a = mod.build_listing({"tax_map": mod._norm_tms("7-12-09-058-14"),
                           "address": "341 Allen St.", "owners": ["X"],
                           "owner_addresses": [], "date_condemned": None,
                           "inspector": None})
    b = mod.build_listing({"tax_map": "7-12-09-058.14", "address": "341 Allen St.",
                           "owners": ["X"], "owner_addresses": [],
                           "date_condemned": None, "inspector": None})
    assert a.dedupe_key() == b.dedupe_key()


@pytest.mark.parametrize("raw,want", [
    ("2/4/2025", datetime(2025, 2, 4)),
    ("6/27/2008", datetime(2008, 6, 27)),
    ("3/2/26", datetime(2026, 3, 2)),
    ("", None), (None, None), ("EG", None),
])
def test_parse_date(raw, want):
    assert mod._parse_date(raw) == want


def test_a_record_with_no_date_still_becomes_a_lead():
    """861 Carson Ave. is on the list with no condemnation date printed."""
    li = next(li for li in _listings() if li.street_address == "861 Carson Ave.")
    assert li.raw["code_enforcement"]["date_condemned"] is None
    assert li.raw["condemned"] is True


# --------------------------------------------------------------------------- #
# listing shape / joining
# --------------------------------------------------------------------------- #

def test_listing_shape():
    li = next(li for li in _listings() if li.parcel_id == "7-16-07-082.00")
    assert li.source == "counties_sc.spartanburg_city_condemned"
    assert li.listing_type is ListingType.UNKNOWN
    assert li.state == "SC" and li.county == "Spartanburg" and li.city == "Spartanburg"
    assert li.sale_date is None
    assert li.owner_name == li.defendant == "BC&K Investments LLC"
    ce = li.raw["code_enforcement"]
    assert ce["condemned"] is True and ce["severe"] is True
    assert ce["date_condemned"] == "2011-06-30"
    assert ce["source"] == "spartanburg_city_master_condemnation_list"
    assert li.raw["condemned"] is True and li.raw["distressed"] is True
    assert li.raw["owner_mailing"]["raw"].startswith("160 Orchard")


def test_tms_is_the_same_namespace_the_delinquent_tax_source_writes():
    """spartanburg_delinquent_tax emits '7-16-09-062.00'. A condemned structure
    must MERGE onto the delinquent-tax lead at the same parcel, not sit beside
    it as a second property."""
    from foreclosure_scraper.models import Listing
    condemned = next(li for li in _listings() if li.parcel_id == "7-16-07-082.00")
    tax = Listing(source="counties_sc.spartanburg_delinquent_tax",
                  source_url="https://example.invalid/", state="SC",
                  county="Spartanburg", parcel_id="7-16-07-082.00",
                  raw={"tax_owed": {"balance": 4200.0}})
    assert condemned.dedupe_key() == tax.dedupe_key()
    merged = tax.merge(condemned)
    assert merged.raw["tax_owed"]["balance"] == 4200.0
    assert merged.raw["condemned"] is True


def test_condemnation_scores_as_a_property_signal():
    from foreclosure_scraper.distress_score import _signals_for
    li = _listings()[0]
    names = [n for n, _b, _w in _signals_for(li)]
    assert "code_enforcement" in names
    assert "distressed_condition" in names


def test_multiple_owners_flag():
    li = next(li for li in _listings() if li.street_address == "714 S. Center St.")
    assert li.raw["multiple_owners"] is True
    assert li.raw["code_enforcement"]["owner_count"] == 4


def test_government_owner_is_dropped():
    rec = {"tax_map": "7-11-16-031.00", "address": "227 James Anderson Ln.",
           "owners": ["Housing Authority of The City of Spartanburg"],
           "owner_block": "Housing Authority of The City of Spartanburg",
           "owner_addresses": ["PO Box 2828"], "date_condemned": None,
           "inspector": "EG"}
    assert mod.build_listing(rec) is None


def test_record_with_neither_address_nor_tax_map_is_dropped():
    assert mod.build_listing({"tax_map": None, "address": None, "owners": [],
                              "owner_block": None, "owner_addresses": [],
                              "date_condemned": None, "inspector": None}) is None


def test_duplex_marker_sets_multi_family():
    from foreclosure_scraper.models import PropertyKind
    li = mod.build_listing({"tax_map": "7-12-08-072.00",
                            "address": "140/142 Garrett St. (Duplex)",
                            "owners": ["Dax Properties, LLC"], "owner_block": "Dax",
                            "owner_addresses": ["444 N. Sweetwater Hills Dr."],
                            "date_condemned": None, "inspector": "DH"})
    assert li.property_kind is PropertyKind.MULTI_FAMILY


# --------------------------------------------------------------------------- #
# fetch-level guards
# --------------------------------------------------------------------------- #

def test_non_pdf_response_returns_empty_rather_than_exploding(monkeypatch):
    async def _fake(url, timeout=None):
        return b"<html>404 not found</html>"
    monkeypatch.setattr(mod, "get_bytes", _fake)
    assert asyncio.run(mod.SpartanburgCityCondemned().fetch()) == []


def test_env_gate_skips_without_fetching(monkeypatch):
    calls = []

    async def _fake(url, timeout=None):
        calls.append(url)
        return b"%PDF-"
    monkeypatch.setattr(mod, "get_bytes", _fake)
    monkeypatch.setenv(mod.ENV_OFF, "0")
    assert asyncio.run(mod.SpartanburgCityCondemned().fetch()) == []
    assert calls == []


# --------------------------------------------------------------------------- #
# wiring guard (fails until main.py is updated — see the report)
# --------------------------------------------------------------------------- #

def test_slug_must_be_in_dateless_ok_sources():
    from foreclosure_scraper import main
    slug = mod.SpartanburgCityCondemned.slug
    assert slug in main.DATELESS_OK_SOURCES, (
        f'add "{slug}" to main.DATELESS_OK_SOURCES')


def test_scraper_is_auto_discovered_by_the_registry():
    from foreclosure_scraper.scrapers._registry import discover
    assert mod.SpartanburgCityCondemned in discover()


def test_it_is_a_different_source_from_the_county_condemned_scraper():
    from foreclosure_scraper.scrapers.counties_sc import spartanburg_condemned as county
    assert mod.SpartanburgCityCondemned.slug != county.SpartanburgCondemned.slug


# --------------------------------------------------------------------------- #
# live smoke
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live smoke; set RUN_LIVE=1")
def test_live():
    s = mod.SpartanburgCityCondemned()
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == "OK"
    assert len(rows) >= s.expected_min_count
    assert all(li.parcel_id for li in rows)
    assert all(li.raw["condemned"] for li in rows)
    assert sum(1 for li in rows if li.raw.get("owner_mailing")) / len(rows) > 0.95
    print(f"live spartanburg city condemned={len(rows)} "
          f"dated={sum(1 for li in rows if li.raw['code_enforcement']['date_condemned'])}")
