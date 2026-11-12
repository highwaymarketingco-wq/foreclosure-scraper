"""enrichment_title_risk.py — classifier + enrichment-pass tests.

Written 2026-10-03 during the title_risk (41/148-county) live-board audit.
Despite the module existing since 2026-06-26 (b608c862) it had NO dedicated
test file before this one.

The audit live-verified raw['title_risk'] via board_stream.iter_board_rows()
(read-only; load_board() is never safe on this 8GB Mac) and found two
separate things:

  1. The 41/148-county, ~3% board-wide fill rate is overwhelmingly a REAL
     ceiling, not a bug: 76% of the live board (tax_lien + tax_sale +
     distressed = 166K/219K rows) is pre-litigation distress/tax-delinquency
     signal with no lawsuit and therefore no "foreclosing party" to read at
     all. This has nothing to do with ROD (register-of-deeds) vendor
     coverage — enrichment_title_risk.py is pure-compute over court-filing
     party text (plaintiff/trustee/creditor/attorney), never touches ROD
     deed/mortgage/lien data. (A separate, unrelated module, rod/priority.py,
     has its own distinct title_risk_summary field fed by ROD data — not
     what this module or the coverage CSV's title_risk column means.)

  2. A real, separate, FIXABLE bug: enrich_title_risk() ran unconditionally
     on every listing type, including three where plaintiff/trustee do NOT
     mean "the foreclosing party" at all:
       * BANKRUPTCY: trustee = the court-appointed BANKRUPTCY trustee (an
         estate administrator), not a foreclosure-sale trustee. Live
         example: trustee="Mays, Robert" -> a bare personal name with no
         corporate suffix hits _classify()'s "private individual" junior
         branch and stamps surviving_senior_debt_risk=True on a BK filing
         with no pending foreclosure sale at all.
       * DIVORCE_NOTICE: plaintiff = the spouse who filed for divorce, not a
         foreclosing creditor. Same bare-name fallthrough.
       * ESTATE_LEAD: trustee is repurposed by national.estate_sales to hold
         the ESTATE-SALE COMPANY name ("Private Listing", "Blue Ridge Estate
         Liquidators LLC"), not a foreclosure trustee.
     distress_score.py reads raw['title_risk']['surviving_senior_debt_risk']
     and applies a flat -20 points ("title-wipeout trap", keeps the lead out
     of HOT) — so these were live false signals actively corrupting lead
     scoring, not just a cosmetic mislabel.

  The fix scopes enrich_title_risk() to _TITLE_RISK_LISTING_TYPES, the
  listing types that legitimately carry a foreclosing party, mirroring the
  exact allowlist pattern enrichment_hoa_plaintiff_signal.TARGET_LISTING_TYPES
  already established for the same class of false positive.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_title_risk import (
    _TITLE_RISK_LISTING_TYPES,
    _classify,
    _party_text,
    classify_hoa_plaintiff,
    enrich_title_risk,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _row(listing_type, plaintiff=None, trustee=None, raw=None, **kw):
    defaults = dict(
        source="t.x", source_url="http://x", property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Buncombe", case_number="26-1234",
    )
    defaults.update(kw)
    return Listing(listing_type=listing_type, plaintiff=plaintiff, trustee=trustee,
                    raw=raw or {}, **defaults)


# ---------------------------------------------------------------------------
# _classify — core senior/junior/unknown logic (basic sanity; the HOA-specific
# half of this is already covered by test_hoa_plaintiff_signal.py).
# ---------------------------------------------------------------------------

def test_classify_senior_bank_wins():
    result = _classify("U.S. Bank Trust National Association, as Trustee")
    assert result["kind"] == "senior_lien_foreclosure"
    assert result["surviving_senior_debt"] is False


def test_classify_junior_hoa():
    result = _classify("Fernbrook III Homeowners Association")
    assert result["kind"] == "junior_lien_foreclosure"
    assert result["surviving_senior_debt_risk"] is True


def test_classify_bare_personal_name_is_junior_individual():
    result = _classify("Mays, Robert")
    assert result["kind"] == "junior_lien_foreclosure"
    assert result["matched"] == "private individual"


def test_classify_no_party_text_returns_none():
    assert _classify("") is None
    assert _classify(None) is None


# ---------------------------------------------------------------------------
# enrich_title_risk — the per-listing enrichment pass, scope-gated to
# _TITLE_RISK_LISTING_TYPES.
# ---------------------------------------------------------------------------

def test_title_risk_listing_types_are_the_expected_allowlist():
    assert _TITLE_RISK_LISTING_TYPES == {
        ListingType.FORECLOSURE_SALE,
        ListingType.LIS_PENDENS,
        ListingType.SHERIFF_SALE,
        ListingType.HOA_SALE,
        ListingType.AUCTION,
        ListingType.TAX_SALE,
        ListingType.UNKNOWN,
    }


def test_bankruptcy_trustee_is_never_classified_as_a_foreclosing_party():
    """Regression for the live false positive: a BK-case trustee's bare name
    must not become a junior_lien_foreclosure 'trap' flag."""
    row = _row(ListingType.BANKRUPTCY, trustee="Mays, Robert")
    stats = enrich_title_risk([row])
    assert "title_risk" not in row.raw
    assert stats["out_of_scope_type"] == 1
    assert stats["junior_risk"] == 0


def test_divorce_petitioner_is_never_classified_as_a_foreclosing_party():
    row = _row(ListingType.DIVORCE_NOTICE, plaintiff="Smith, Jane")
    stats = enrich_title_risk([row])
    assert "title_risk" not in row.raw
    assert stats["out_of_scope_type"] == 1


def test_estate_sale_company_is_never_classified_as_a_foreclosing_party():
    row = _row(ListingType.ESTATE_LEAD, trustee="Blue Ridge Estate Liquidators LLC")
    stats = enrich_title_risk([row])
    assert "title_risk" not in row.raw
    assert stats["out_of_scope_type"] == 1

    row2 = _row(ListingType.ESTATE_LEAD, trustee="Private Listing")
    enrich_title_risk([row2])
    assert "title_risk" not in row2.raw


@pytest.mark.parametrize("listing_type", [
    ListingType.FORECLOSURE_SALE, ListingType.LIS_PENDENS, ListingType.SHERIFF_SALE,
    ListingType.HOA_SALE, ListingType.AUCTION, ListingType.TAX_SALE, ListingType.UNKNOWN,
])
def test_in_scope_types_still_get_classified_normally(listing_type):
    """Regression guard: the scope gate must not silently break the types
    that legitimately carry a foreclosing party."""
    row = _row(listing_type, plaintiff="Wells Fargo Bank, N.A.")
    stats = enrich_title_risk([row])
    assert row.raw["title_risk"]["kind"] == "senior_lien_foreclosure"
    assert stats["out_of_scope_type"] == 0
    assert stats["senior"] == 1


@pytest.mark.parametrize("listing_type", [
    ListingType.BANKRUPTCY, ListingType.DIVORCE_NOTICE, ListingType.ESTATE_LEAD,
    ListingType.PROBATE_NOTICE, ListingType.ELDERLY_DISABLED, ListingType.TAX_LIEN,
    ListingType.DISTRESSED, ListingType.TAX_SALE_OVERAGE, ListingType.REO,
])
def test_out_of_scope_types_are_never_classified_even_with_a_senior_bank_name(listing_type):
    """Even a real bank name must not be stamped on an out-of-scope type —
    the point is that these types have no pending foreclosure sale at all,
    not merely that individual-name matching is risky."""
    row = _row(listing_type, plaintiff="Wells Fargo Bank, N.A.")
    stats = enrich_title_risk([row])
    assert "title_risk" not in row.raw
    assert stats["out_of_scope_type"] == 1
    assert stats["senior"] == 0


def test_enrich_never_drops_rows_regardless_of_scope():
    rows = [
        _row(ListingType.FORECLOSURE_SALE, plaintiff="PennyMac"),
        _row(ListingType.BANKRUPTCY, trustee="Mays, Robert"),
        _row(ListingType.LIS_PENDENS, plaintiff=None),
    ]
    n = len(rows)
    enrich_title_risk(rows)
    assert len(rows) == n


def test_stats_histogram_keys_present():
    rows = [
        _row(ListingType.FORECLOSURE_SALE, plaintiff="PennyMac"),
        _row(ListingType.BANKRUPTCY, trustee="Mays, Robert"),
    ]
    stats = enrich_title_risk(rows)
    assert set(stats) == {"senior", "junior_risk", "unknown", "no_party",
                           "out_of_scope_type", "rows"}
    assert stats["rows"] == 2
    assert stats["senior"] == 1
    assert stats["out_of_scope_type"] == 1


def test_signal_key_still_in_raw_keep():
    """raw_keep lesson (same as hoa_plaintiff_signal / co_defendant_signal):
    web_artifact._slim_raw() drops any raw key RAW_KEEP doesn't name."""
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "title_risk" in RAW_KEEP


def test_enricher_still_wired_into_main_pipeline():
    import inspect

    from foreclosure_scraper import main as main_module

    src = inspect.getsource(main_module)
    assert "enrichment_title_risk import enrich_title_risk" in src
    assert "enrich_title_risk(enriched)" in src


# ---------------------------------------------------------------------------
# _party_text — sanity that the fallback chain still works for in-scope rows
# (full coverage of this already lives implicitly in test_hoa_plaintiff_signal.py).
# ---------------------------------------------------------------------------

def test_party_text_prefers_structured_plaintiff_over_raw_fallback():
    li = _row(ListingType.FORECLOSURE_SALE, plaintiff="Wells Fargo Bank",
              raw={"plaintiff": "Should Not Be Used"})
    assert _party_text(li) == "Wells Fargo Bank"


def test_party_text_falls_back_to_trustee_when_plaintiff_empty():
    li = _row(ListingType.FORECLOSURE_SALE, plaintiff=None, trustee="Rogers Townsend")
    assert _party_text(li) == "Rogers Townsend"
