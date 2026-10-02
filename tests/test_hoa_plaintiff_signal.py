"""HOA/POA/COA plaintiff classifier + enrichment pass (2026-10-02 lt_hoa_sale
investigation). `lt_hoa_sale` (ListingType.HOA_SALE) shows ~0 rows board-wide
even though counties_sc.charleston_mie.py proves real HOA foreclosures are
being scraped live (case 25-3794 "Canterbury Woods v. McCracken"). The higher-
value fix is NOT to chase that one scraper's tagging further — it's to read
the plaintiff text dozens of OTHER already-running sources collect for every
generic foreclosure_sale/lis_pendens row, because NC and SC HOA lien
foreclosures ride the exact same public notice process as a bank foreclosure.

Sample strings below are taken verbatim from real `plaintiff` values on the
live board (docs/listings_part_*.json.gz, read via board_stream.iter_board_rows(),
2026-10-02), not invented — including the exact false-positive trap the task
calls out: dozens of real "... National Association" bank/trustee rows sit
right next to real "... Homeowners Association" HOA rows.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_hoa_plaintiff_signal import (
    TARGET_LISTING_TYPES,
    enrich_hoa_plaintiff_signal,
)
from foreclosure_scraper.enrichment_title_risk import classify_hoa_plaintiff
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

# ---------------------------------------------------------------------------
# classify_hoa_plaintiff — the shared, name-string-in/dict-out classifier.
# ---------------------------------------------------------------------------

REAL_HOA_PLAINTIFFS = [
    "Amherst Homeowners Association Inc",
    "Anderson Grant Homeowners' Association, Inc.",
    "August Brook Home Owners Association, Inc.",
    "Bella Casa Homeowners Association, Inc.",
    "Berkeley Homeowners’ Association, Inc.",
    "Bridle Path Homeowners' Association, Inc.",
    "Catawba Falls Preserve Community Association",
    "Chadsworth Commons Condominium Association",
    "Rock At Jocassee Property Owners Association, Inc The",
    "The Rock At Jocassee Property Owners Association, Inc.",
    "Attenborough Townes Hoa, Inc.",
    "Pines At Timberwood Homeowners Association Inc",
    "The Townes at Edwards Mill Condominium Association",
    "Franklin Pointe Homeowners Association, Inc.",
    "Langston Homeowners Association, Inc.",
    # Possessive forms ("owner's" / "homeowner's") -- found live, and the
    # reason enrichment_title_risk._HOA_PATTERNS needed the _OWNER_POSS fix:
    "South Wind Villas Homeowner's Association",
    "Maxwell Commons Home Owner's Association, Inc.",
    # The task's own named example family (Charleston MIE, case 25-3794).
    "Canterbury Woods Property Owners Association",
]


@pytest.mark.parametrize("plaintiff", REAL_HOA_PLAINTIFFS)
def test_real_hoa_plaintiffs_are_classified_as_hoa(plaintiff):
    result = classify_hoa_plaintiff(plaintiff)
    assert result["is_hoa"] is True, plaintiff
    assert result["matched"]


REAL_BANK_NATIONAL_ASSOCIATION_PLAINTIFFS = [
    # The exact false-positive trap: real legal bank names carry the word
    # "Association" (as "National Association") right next to real HOA rows
    # that also carry "Association" -- these must NOT be flagged HOA.
    "Fifth Third Bank National Association",
    "Fifth Third Bank, National Association",
    "PNC Bank, National Association",
    "Pnc Bank National Association",
    "JPMorgan Chase Bank, National Association",
    "Jp Morgan Chase Bank, National Association",
    "U.S. Bank National Association",
    "U S Bank National Association",
    "Us Bank Trust National Association",
    "U.S. Bank Trust Company, National Association",
    "U.S. Bank Trust National Association, not in its individual capacity but "
    "solely as Owner Trustee for GSMS 2021-1 Trust",
    "Wells Fargo Bank National Association , plaintiff, et al",
]

REAL_OTHER_NON_HOA_PLAINTIFFS = [
    # Savings & loan ASSOCIATIONS -- a second real bank-naming trap, distinct
    # from "National Association".
    "First Piedmont Federal Savings And Loan Association",
    "Oconee Federal Savings And Loan Association",
    # Credit unions, government, MERS, generic banks -- real live-board values.
    "Skyla Federal Credit Union",
    "Founders Federal Credit Union",
    "South Carolina Department Of Transportation",
    "American Express National Bank",
    "Capital One Na",
    "Bank Of America Na",
    "MidFirst Bank",
    "Mortgage Electronic Registration Systems",
    "MERS",
    # Bare, UNQUALIFIED "... Association" names -- real live-board values with
    # no demonstrable HOA qualifier. Conservative default: left unflagged.
    "Tall Ship Association Inc",
    "Chickasaw Association Inc",
    "Chickasaw Association, Inc.",
    "Harbor Town Association, Inc.",
    "CP-07-2872 THE CHARLES ASSOCIATION, INC.",
    "Holly Towne Association of Residence Owners, Inc.",
    # Real live-board false-positive catch (2026-10-02 live verification):
    # "POA" here is Power of Attorney, not Property Owners Association. The
    # bare \bp\.?o\.?a\.?\b acronym branch used to match this and was removed
    # from _HOA_PATTERNS for exactly this reason — see that tuple's comment.
    "Angela Maria Rogers Individually And As Poa For Shirley Stewart Burges",
]


@pytest.mark.parametrize("plaintiff", REAL_BANK_NATIONAL_ASSOCIATION_PLAINTIFFS)
def test_national_association_banks_are_never_misclassified_as_hoa(plaintiff):
    result = classify_hoa_plaintiff(plaintiff)
    assert result["is_hoa"] is False, plaintiff
    assert result["matched"], f"{plaintiff} should hit the SENIOR bank table, not fall through unmatched"


@pytest.mark.parametrize("plaintiff", REAL_OTHER_NON_HOA_PLAINTIFFS)
def test_other_real_non_hoa_plaintiffs_are_not_flagged(plaintiff):
    result = classify_hoa_plaintiff(plaintiff)
    assert result["is_hoa"] is False, plaintiff


def test_classify_handles_empty_and_none():
    assert classify_hoa_plaintiff(None)["is_hoa"] is False
    assert classify_hoa_plaintiff("")["is_hoa"] is False
    assert classify_hoa_plaintiff("   ")["is_hoa"] is False


# ---------------------------------------------------------------------------
# enrich_hoa_plaintiff_signal — the per-listing enrichment pass.
# ---------------------------------------------------------------------------

def _row(listing_type, plaintiff=None, raw=None, **kw):
    defaults = dict(
        source="t.x", source_url="http://x", property_kind=PropertyKind.UNKNOWN,
        state="SC", county="Spartanburg", case_number="26-1234",
    )
    defaults.update(kw)
    return Listing(listing_type=listing_type, plaintiff=plaintiff, raw=raw or {}, **defaults)


def test_enrich_tags_hoa_plaintiffs_on_target_types_and_never_drops():
    rows = [
        _row(ListingType.LIS_PENDENS, plaintiff="Amherst Homeowners Association Inc"),
        _row(ListingType.FORECLOSURE_SALE, plaintiff="U.S. Bank National Association"),
        _row(ListingType.LIS_PENDENS, plaintiff=None),
        _row(ListingType.TAX_LIEN, plaintiff="Bridle Path Homeowners' Association, Inc."),
    ]
    n = len(rows)
    stats = enrich_hoa_plaintiff_signal(rows)
    assert len(rows) == n  # pure computation, drops nothing

    assert stats["checked"] == 2  # the two target-type rows with a plaintiff
    assert stats["tagged"] == 1

    assert rows[0].raw["hoa_plaintiff_signal"]["hoa_sale_suspected"] is True
    assert rows[0].raw["hoa_plaintiff_signal"]["plaintiff"] == "Amherst Homeowners Association Inc"
    assert rows[0].raw["hoa_plaintiff_signal"]["listing_type"] == "lis_pendens"

    assert "hoa_plaintiff_signal" not in rows[1].raw  # bank -> not tagged
    assert "hoa_plaintiff_signal" not in rows[2].raw  # no plaintiff text at all
    # TAX_LIEN is out of TARGET_LISTING_TYPES even with a real HOA plaintiff
    # string -- this signal is scoped to the two generic types the
    # investigation named, not every listing type that happens to carry one.
    assert "hoa_plaintiff_signal" not in rows[3].raw


def test_target_listing_types_are_exactly_the_two_generic_types():
    assert TARGET_LISTING_TYPES == {ListingType.FORECLOSURE_SALE, ListingType.LIS_PENDENS}


def test_enrich_falls_back_to_raw_plaintiff_when_field_is_empty():
    """Mirrors enrichment_title_risk._party_text's own fallback order — some
    scrapers only populate raw['plaintiff'], not the structured field."""
    row = _row(ListingType.FORECLOSURE_SALE, plaintiff=None,
               raw={"plaintiff": "Franklin Pointe Homeowners Association, Inc."})
    stats = enrich_hoa_plaintiff_signal([row])
    assert stats["tagged"] == 1
    assert row.raw["hoa_plaintiff_signal"]["hoa_sale_suspected"] is True


def test_signal_survives_publish_slim_via_raw_keep():
    """RAW_KEEP must name this key or write_artifact's _slim_raw() drops it
    silently at publish (same lesson as co_defendant_signal / owner_name_signal
    — see tests/test_raw_keep_covers_enrichers.py)."""
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "hoa_plaintiff_signal" in RAW_KEEP


def test_enricher_is_wired_into_main_pipeline():
    """Source-text check (same style as test_co_defendant_signal.py's wiring
    test) rather than running the full network-backed pipeline."""
    import inspect

    from foreclosure_scraper import main as main_module

    src = inspect.getsource(main_module)
    assert "enrichment_hoa_plaintiff_signal import enrich_hoa_plaintiff_signal" in src
    assert "enrich_hoa_plaintiff_signal(enriched)" in src
