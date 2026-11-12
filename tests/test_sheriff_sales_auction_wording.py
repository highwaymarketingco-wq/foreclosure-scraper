"""Pin the 2026-10-02 `_SALE_CONTEXT_RE` auction-wording fix in
national/sheriff_sales.py — see the module docstring's 2026-10-02 writeup.

Found while live-auditing why `lt_sheriff_sale` shows only 1/148 counties on
the board (and that 1 row is itself a confirmed-stale false positive from
the 2026-10-01 fix, not a real sale — see the other writeup in this module).
Brunswick County NC's real, currently-live page titles its postings
"Sheriff's Auctions" throughout and never says "sheriff's sale" or "public
auction" — the exact two phrasings `_SALE_CONTEXT_RE` recognized before this
fix — so a real posting with a real case number was silently dropped.

FIXED 2026-10-04 (HERMES extraction-completeness audit, batch 18): this
file used to pin the known REMAINING gap (Brunswick's real page splits the
case number and the "Sheriff's Auction" phrase across separate sibling
`<p>` tags, and the fallback parser evaluated one element at a time, so
this specific live posting did not parse even after the regex fix above).
That gap is now fixed via `_join_single_posting_container` (see module
docstring's 2026-10-04 FIXED note) -- the test below now pins the FIXED
behavior instead of the gap.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.sheriff_sales import (
    _SALE_CONTEXT_RE,
    _parse_brunswick,
)

# A single-block notice shaped like Brunswick's own site language ("Sheriff's
# Auction", not "Sheriff's Sale") with the address/case number in the SAME
# element — the shape _SALE_CONTEXT_RE's existing sibling tests already use
# for "sheriff's sale"/"public auction".
_REAL_AUCTION_WORDING_HTML = """
<html><body>
<div class="content">
  <p>SHERIFF'S AUCTION: the property located at 123 Main St, Shelby, NC,
  case number 24-CVD-5678, will be sold at the courthouse steps.</p>
</div>
</body></html>
"""

# Real-shaped reproduction of Brunswick's actual live markup (re-fetched
# live 2026-10-04, unchanged since 2026-10-02): case number and the auction
# phrase are in separate sibling <p> tags under the same entry-content div,
# with blank spacer <p>s between. Includes the real sergeant's contact
# phone run together with no separator ("Powell, 9108804903Civil Division"),
# exactly as the live page renders it.
_REAL_BRUNSWICK_SPLIT_PARAGRAPHS_HTML = """
<html><body>
<div class="entry-content">
<p>FILE# 19 CVS 004029-640</p>
<p>&nbsp;</p>
<p>Brian M. Chism, Sheriff of Brunswick County,<br>
Sergeant. Christopher Powell, 9108804903<br>
Civil Division<br>
Brunswick County Sheriffs&#8217; Office</p>
<p>&nbsp;</p>
<p><a href="https://example.com/x">SHERIFF&#8217;S AUCTION 7/17/2026
<strong>(POSTPONED TO 7/31/26)</strong></a></p>
<p>&nbsp;</p>
</div>
</body></html>
"""


def test_sale_context_regex_now_matches_sheriffs_auction_wording():
    """The real fix: 'Sheriff's Auction' (no 'sale') now matches."""
    assert _SALE_CONTEXT_RE.search("SHERIFF'S AUCTION 7/17/2026")
    assert _SALE_CONTEXT_RE.search("Sheriff’s Auctions")  # curly apostrophe, as published


def test_sale_context_regex_does_not_loosen_to_bare_auction():
    """Must not regress the 2026-10-01 fix: bare 'auction' with no sheriff/
    public/execution qualifier still must not match on its own."""
    assert not _SALE_CONTEXT_RE.search("Golf Carts auction fundraiser for the K9 unit")


def test_brunswick_parses_a_real_single_block_auction_notice():
    """A notice using Brunswick's own real wording, with the case number in
    the SAME block, now parses — this is the part of the bug that is fixed."""
    out = _parse_brunswick(
        _REAL_AUCTION_WORDING_HTML, "https://www.brunswicksheriff.com/resources/auctions"
    )
    assert len(out) == 1
    assert out[0].case_number is not None
    assert out[0].street_address == "123 Main St"


def test_brunswicks_actual_live_markup_now_parses_fixed_2026_10_04():
    """FIXED 2026-10-04 (batch 18): the real site splits the case number
    and the sale-context phrase into separate sibling <p> tags under one
    div.entry-content -- _join_single_posting_container now joins that
    container's text (since it holds exactly one case-number signal and
    one sale-context signal, nothing else to confuse the join with) before
    extraction, so this now parses to the real single posting instead of
    zero."""
    out = _parse_brunswick(
        _REAL_BRUNSWICK_SPLIT_PARAGRAPHS_HTML,
        "https://www.brunswicksheriff.com/resources/auctions",
    )
    assert len(out) == 1
    li = out[0]
    assert li.case_number is not None and "19" in li.case_number
    assert li.county == "Brunswick"
    assert li.state == "NC"
    # The POSTPONED-TO date must win over the superseded original 7/17 date.
    assert li.sale_date is not None
    assert (li.sale_date.month, li.sale_date.day) == (7, 31)
    assert li.raw["sheriff_sale"]["contact_phone"] == "9108804903"
