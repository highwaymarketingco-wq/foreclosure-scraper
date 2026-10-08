"""co_defendants already rides along on every SC PublicIndex / lis-pendens case
(sc_public_index.py, sc_public_index_lis_pendens.py both write it), but nothing
in the repo ever read it back out before this enricher. A SC judicial
foreclosure must join every other party with a recorded interest as a
defendant, so the list often names a second mortgagee, a HUD/USDA junior lien,
an HOA with an assessment lien, or an estate standing in for a dead co-owner --
all free, all already on the board, all previously invisible.

Sample strings below are taken verbatim from real `co_defendants` arrays on the
live board (docs/listings.json, 2026-10-01), not invented.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_co_defendant_signal import (
    classify_co_defendants,
    enrich_co_defendant_signal,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


@pytest.mark.parametrize("names", [
    ["Arthur State Bank, Mortgagee And Assignee", "B4M Investments, Llc, Mortgagee"],
    ["Onemain Financial Group Llc"],
    ["Capital One Na", "Discover Bank"],
    ["Synchrony Bank"],
    ["Mortgage Electronic Registration Systems, Inc.,"],
    ["Portfolio Recovery Associates Llc"],
    ["Sc Telco Federal Credit Union"],
])
def test_private_lienholder_entities_are_caught(names):
    sig = classify_co_defendants(names)
    assert sig is not None
    assert sig["junior_lienholders"], f"expected a hit in {names}"


@pytest.mark.parametrize("names", [
    ["Secretary Of Housing And Urban Development"],
    ["Its Agency The Rural Housing Service"],
    ["Department Of Revenue South Carolina"],
])
def test_government_lienholders_are_caught_separately(names):
    sig = classify_co_defendants(names)
    assert sig is not None
    assert sig["government_lienholders"]
    assert not sig["junior_lienholders"]


@pytest.mark.parametrize("names", [
    ["Anderson Grant Homeowners Association Inc"],
    ["The Cliffs At Keowee Vineyards Community Association Inc"],
])
def test_hoa_named_as_party_is_caught(names):
    sig = classify_co_defendants(names)
    assert sig is not None
    assert sig["hoa"]


def test_estate_co_defendant_is_caught_even_though_owner_name_signal_never_sees_it():
    sig = classify_co_defendants(["Allen Estate Of, Roy Douglas", "1St Franklin Financial Corporation"])
    assert sig is not None
    assert sig["estate_co_defendants"]
    assert sig["estate_co_defendants"][0]["grade"] == "strong"
    # the same row also carries a private lienholder -- both must survive together
    assert sig["junior_lienholders"]


def test_bare_trailing_estate_with_no_OF_is_left_alone_by_design():
    """'Amanda W Cooper Estate' is a REAL live-board co-defendant string, but it
    has no 'OF' -- classify() requires 'ESTATE OF' precisely so 'ACME REAL
    ESTATE HOLDINGS LLC' never reads as a death. Inheriting that same judgment
    call (not loosening it here) means this one is correctly NOT an estate hit,
    even though it still correctly IS a junior-lienholder hit."""
    sig = classify_co_defendants(["Amanda W Cooper Estate", "1St Franklin Financial Corporation"])
    assert sig is not None
    assert sig["estate_co_defendants"] is None
    assert sig["junior_lienholders"]


@pytest.mark.parametrize("names", [
    ["Smith, John"],
    ["Doe, Jane", "Doe, John"],
    ["Allegheny Casualty Co."],  # a bail-bond surety, not a lienholder
])
def test_plain_co_defendants_yield_nothing(names):
    assert classify_co_defendants(names) is None


def test_classify_handles_empty_and_none():
    assert classify_co_defendants([]) is None
    assert classify_co_defendants([None, ""]) is None  # type: ignore[list-item]


def _row(co_defendants, container="court"):
    raw = {container: {"co_defendants": co_defendants}} if co_defendants is not None else {}
    return Listing(source="t.x", source_url="http://x", listing_type=ListingType.FORECLOSURE_SALE,
                   property_kind=PropertyKind.UNKNOWN, state="SC", county="Spartanburg",
                   case_number="26-1234", raw=raw)


def test_enrich_reads_both_raw_shapes_and_never_drops():
    rows = [
        _row(["Arthur State Bank, Mortgagee And Assignee"], container="court"),
        _row(["Allen Estate Of, Roy Douglas"], container="sc_public_index"),
        _row(["Smith, John"], container="court"),
        _row(None),
        _row([]),
    ]
    n = len(rows)
    stats = enrich_co_defendant_signal(rows)
    assert len(rows) == n
    assert stats["tagged"] == 2
    assert stats["junior_lienholder"] == 1
    assert stats["estate"] == 1
    assert "co_defendant_signal" in rows[0].raw
    assert "co_defendant_signal" in rows[1].raw
    assert "co_defendant_signal" not in (rows[2].raw or {})


def test_signal_survives_publish_slim_via_raw_keep():
    """2026-10-01: wired. web_artifact.RAW_KEEP now carries a
    `co_defendant_signal` entry so write_artifact's _slim_raw() keeps this key
    on save, per HERMES Section 10 ('New raw.* field? Add the key to RAW_KEEP').
    (This test used to assert the INVERSE -- 'not yet in RAW_KEEP' -- as a
    deliberate trip-wire for whoever wired the enricher into main.py. That
    person is this commit; the trip-wire has done its job.)
    """
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "co_defendant_signal" in RAW_KEEP


def test_enricher_is_wired_into_main_pipeline():
    """main.py must actually call enrich_co_defendant_signal(), not just have
    RAW_KEEP updated -- a RAW_KEEP entry with no call site would publish a key
    that's never populated. Source-text check (same style as other
    wiring-reachability tests in this repo) rather than running the full
    pipeline, which needs network-backed scrapers this test suite doesn't run."""
    import inspect

    from foreclosure_scraper import main as main_module

    src = inspect.getsource(main_module)
    assert "enrichment_co_defendant_signal import enrich_co_defendant_signal" in src
    assert "enrich_co_defendant_signal(enriched)" in src


def test_the_plaintiff_is_never_its_own_junior_lienholder():
    """A party list that repeats the suing lender (2 of 135 tagged rows on the 10/8 checkpoint)
    is not a second lien; another lender beside it still is. Made-up names."""
    alone = _row(["Example National Bank"], container="sc_public_index")
    alone.plaintiff = "Example National Bank"
    other = _row(["EXAMPLE NATIONAL BANK", "Sample Credit Union"], container="sc_public_index")
    other.plaintiff = "Example National Bank"
    enrich_co_defendant_signal([alone, other])
    assert "co_defendant_signal" not in alone.raw
    assert other.raw["co_defendant_signal"]["junior_lienholders"] == ["Sample Credit Union"]
