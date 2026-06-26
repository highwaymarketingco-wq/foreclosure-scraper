"""Pin the per-case court BID enricher (enrichment_court_bid).

Covers the pure logic that gates and shapes the SC Public Index per-case
lookup, WITHOUT any network I/O (the live render is exercised separately by a
manual smoke). The enricher's job: for foreclosure leads that already hold a
court case_number but no opening_bid, look that one case up and fill the
recorded bid + upset status — compliant, per-case (Rule-610), SC-only (NC court
bid is not viable on free surfaces, so NC must be reported, not scraped).
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper.enrichment_court_bid import (
    _apply,
    _derive_upset_status,
    _extract_bid_amount,
    _norm_sc_case,
    _parse_money,
    enrich_court_bid,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(**kw) -> Listing:
    base = dict(
        source="counties_sc.sc_public_index_lis_pendens",
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Anderson",
        case_number="2025-CP-04-01606",
        raw={},
    )
    base.update(kw)
    return Listing(**base)


# --- pure helpers ----------------------------------------------------------

def test_norm_sc_case():
    assert _norm_sc_case("2025-CP-42-02945") == ("2025CP4202945", "Spartanburg")
    assert _norm_sc_case("2026CP3700133") == ("2026CP3700133", "Oconee")
    # unmapped county code -> not lookupable
    assert _norm_sc_case("2025-CP-99-00001") == (None, None)
    # NC SP format is not SC-CP
    assert _norm_sc_case("24SP123") == (None, None)
    assert _norm_sc_case("") == (None, None)


def test_parse_money_band():
    assert _parse_money("123,456.78") == 123456.78
    # filing-fee-sized values are below the $1k foreclosure-bid floor
    assert _parse_money("225.00") is None
    # implausibly large -> rejected
    assert _parse_money("99,000,000") is None


def test_extract_bid_amount_ignores_filing_fees():
    assert _extract_bid_amount("High Bid: $142,500.00") == (142500.0, "bid")
    assert _extract_bid_amount("Sold for $98,000 to the bank") == (98000.0, "sold")
    assert _extract_bid_amount("Upset Bid: $151,000.00") == (151000.0, "upset_bid")
    # only court costs present -> no bid
    assert _extract_bid_amount("Balance Due: $0.00 Fine/Costs: $225.00") == (None, None)


def test_derive_upset_status():
    assert _derive_upset_status("confirmed", None) == "closed_confirmed"
    assert _derive_upset_status("sold_unconfirmed", None) == "sold_pending_upset"
    assert _derive_upset_status("sale_noticed", None) == "scheduled"
    assert _derive_upset_status("judgment", None) == "judgment_entered"
    assert _derive_upset_status(None, [{"type": "Order of Confirmation of Sale"}]) == "closed_confirmed"
    assert _derive_upset_status(None, [{"type": "Report of Sale"}]) == "sold_pending_upset"
    assert _derive_upset_status(None, None) == "unknown"


# --- apply -----------------------------------------------------------------

def test_apply_fills_opening_bid_from_real_bid():
    li = _li(opening_bid=None)
    result = {
        "detail_url": "https://publicindex.sccourts.org/Anderson/PublicIndex/CaseDetails.aspx?x",
        "amount": 142500.0, "amount_kind": "bid",
        "judgment_amount": 160000.0, "sale_status": "sold_unconfirmed",
        "upset_status": "sold_pending_upset", "documents": [{"type": "Report of Sale"}],
    }
    tag = _apply(li, result, source="sc_public_index:Anderson")
    assert tag == "bid_filled"
    assert li.opening_bid == 142500.0
    assert li.judgment_amount == 160000.0
    cb = li.raw["court_bid"]
    assert cb["amount"] == 142500.0
    assert cb["upset_status"] == "sold_pending_upset"
    assert cb["source"] == "sc_public_index:Anderson"


def test_apply_status_only_when_no_dollar_bid():
    li = _li(opening_bid=None)
    result = {
        "detail_url": "https://x", "amount": None, "amount_kind": None,
        "judgment_amount": None, "sale_status": "sale_noticed",
        "upset_status": "scheduled", "documents": [{"type": "Notice of Sale"}],
    }
    tag = _apply(li, result, source="sc_public_index:Anderson")
    assert tag == "status_only"
    assert li.opening_bid is None                 # never fabricated
    assert li.raw["court_bid"]["upset_status"] == "scheduled"


def test_apply_does_not_overwrite_existing_bid():
    li = _li(opening_bid=120000.0)
    result = {"detail_url": "https://x", "amount": 999.0, "amount_kind": "bid",
              "judgment_amount": None, "sale_status": None, "upset_status": "unknown",
              "documents": None}
    _apply(li, result, source="s")
    assert li.opening_bid == 120000.0             # untouched


# --- gating (no network: these targets never reach the renderer) -----------

def _run(listings):
    return asyncio.run(enrich_court_bid(listings))


def test_gate_skips_non_foreclosure_type():
    li = _li(listing_type=ListingType.DISTRESSED, opening_bid=None)
    stats = _run([li])
    assert stats["sc_candidates"] == 0


def test_gate_skips_when_opening_bid_present():
    li = _li(opening_bid=95000.0)
    stats = _run([li])
    assert stats["sc_candidates"] == 0


def test_gate_skips_when_no_case_number():
    li = _li(case_number=None, opening_bid=None)
    stats = _run([li])
    assert stats["sc_candidates"] == 0


def test_nc_sp_reported_not_viable_not_scraped():
    li = _li(state="NC", county="Buncombe", case_number="26 SP 000284-100", opening_bid=None)
    stats = _run([li])
    assert stats["sc_candidates"] == 0
    assert stats["nc_skipped_not_viable"] == 1
    assert stats["looked_up"] == 0                # NC never hits the network


def test_nc_lawfirm_filenum_skipped_as_format():
    # 25-17343-FC01 is a Brock Scott internal file#, NOT a court case# — must
    # not be treated as an NC SP case nor looked up.
    li = _li(state="NC", county="Gaston", case_number="25-17343-FC01", opening_bid=None)
    stats = _run([li])
    assert stats["nc_skipped_not_viable"] == 0
    assert stats["other_skipped_format"] == 1


def test_off_switch(monkeypatch):
    monkeypatch.setenv("COURT_BID_OFF", "1")
    li = _li(opening_bid=None)
    stats = _run([li])
    assert stats["scanned"] == 0
    assert stats["sc_candidates"] == 0


def test_already_court_bid_filled_is_skipped():
    li = _li(opening_bid=None, raw={"court_bid": {"amount": 100000.0}})
    stats = _run([li])
    assert stats["sc_candidates"] == 0


def test_sale_date_priority_ordering():
    from foreclosure_scraper.enrichment_court_bid import _priority
    soon = _li(sale_date=datetime.utcnow())
    far = _li(sale_date=None)
    assert _priority(soon) < _priority(far)
