"""reo.treasury_seized: 2026-10-04 final-batch extraction-completeness audit.

Three confirmed live findings, all fixed here (see the module's own
docstring for the full write-up):
1. ADDR_RE missed a real current NC listing entirely (a hyphenated
   unit-letter house number, "139-B Farless Road").
2. opening_bid was dead code -- the list page never shows a dollar price;
   the real "Starting Bid: $X" lives only on each listing's own detail page.
3. The detail page carries a PDF flyer, parcel number, county (the list
   page has none at all), lot size, year built, zoning, and auctioneer --
   all previously uncaptured.

Fixtures below are trimmed-but-real captures (2026-10-04) of
treasury.gov's own realprop.shtml list-page markup and 2721briar.shtml's
detail page.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from foreclosure_scraper.scrapers.reo import treasury_seized as M

# Real list-page fragment (2026-10-04): the per-listing <a><img alt=...></a>
# wrapper that links each thumbnail to its own detail page.
REAL_LIST_FRAGMENT = (
    '<td height="180"><p class="style1"><b><font color="#cc0000" size="3">'
    'SINGLE FAMILY HOME</font></b><font size="2" color="#cc0000"><b>: </b>'
    '</font><span class="style12"><font color="#cc0000">2721 Briar Ridge '
    'Drive, Charlotte, North Carolina 28270</font></span>'
    '<p class="style20"><a href="2721briar.shtml">For complete details on '
    'this property click on the photo or CLICK HERE</a></p></td>'
    '<td height="182"><a href="2721briar.shtml"><img '
    'src="images/2721briar01.gif" alt="2721 Briar Ridge Drive, Charlotte, '
    'North Carolina 28270" width="224" border="0"></a></td>'
)

# Real NC listing with no wrapping <a> at all (its own detail page isn't
# ready -- "Complete details on this property coming soon...") -- must not
# crash and must simply produce no link-map entry.
REAL_COMING_SOON_FRAGMENT = (
    '<p class="style11">3,481 sq. ft. vacant service &amp; repair/retail '
    'building.</p><p class="style20">Complete details on this property '
    'coming soon...</p>'
    '<td height="182"><img src="images/5253division01.gif" alt="5253 '
    'Division Avenue S., Grand Rapids, Michigan 49548" width="224" '
    'height="161" border="0"></td>'
)

# Real detail-page fragment (2026-10-04, 2721briar.shtml), trimmed to the
# label/value table plus the Auction Flyer link + an unrelated cross-
# referenced listing's own flyer (the real page really does carry one, from
# a "similar properties" link elsewhere on the same template).
REAL_DETAIL_HTML = """
<html><body>
<a href="images/beaumontflyer.pdf">Beaumont Flyer</a>
<div>Starting Bid:</div>
<div>$160,000</div>
<div>Living Space:</div>
<div>2,835 &plusmn; sq. ft.</div>
<div>Site Area:</div>
<div>11,326 &plusmn; sq. ft.</div>
<div>Year Built:</div>
<div>1998</div>
<div>Parcel  No:</div>
<div>22727209</div>
<div>2025 Mecklenburg County Taxes:</div>
<div>$3,991 &plusmn;</div>
<div>Zoning:</div>
<div>N1-A/Residential Dwelling</div>
<div>CWS NC Auction License:</div>
<div>#10348</div>
<div>Auctioneer:</div>
<div>Mike Lewis #10334</div>
<p>Auction Flyer: <a href="images/2721briarflyer.pdf" target="_blank">Download here</a></p>
</body></html>
"""


def test_addr_re_catches_the_hyphenated_unit_suffix_house_number():
    """The real, previously-invisible listing."""
    s = ("0.54 acre residential lot with a manufactured home. "
         "139-B Farless Road, Merry Hill, North Carolina 27957")
    m = M.ADDR_RE.search(s)
    assert m is not None
    street, city, state_raw, zipc = m.groups()
    assert street == "139-B Farless Road"
    assert city == "Merry Hill"
    assert zipc == "27957"


def test_addr_re_still_matches_the_ordinary_shape():
    s = "2721 Briar Ridge Drive, Charlotte, North Carolina 28270"
    m = M.ADDR_RE.search(s)
    assert m is not None
    assert m.group(1) == "2721 Briar Ridge Drive"


def test_detail_link_map_keys_by_street_lowercased():
    link_map = M._detail_link_map(REAL_LIST_FRAGMENT)
    assert "2721 briar ridge drive" in link_map
    href, photo = link_map["2721 briar ridge drive"]
    assert href == "2721briar.shtml"
    assert photo == "images/2721briar01.gif"


def test_detail_link_map_skips_a_listing_with_no_detail_link_yet():
    """'Coming soon' properties have no <a> wrapper at all -- must not
    crash, must simply produce no entry."""
    link_map = M._detail_link_map(REAL_COMING_SOON_FRAGMENT)
    assert link_map == {}


def test_parse_detail_page_extracts_every_real_field():
    out = M._parse_detail_page(REAL_DETAIL_HTML)
    assert out["opening_bid"] == "$160,000"
    assert out["living_sqft"] == "2,835 ± sq. ft."
    assert out["lot_size_sqft"] == "11,326 ± sq. ft."
    assert out["year_built"] == "1998"
    assert out["parcel_id"] == "22727209"
    assert out["zoning"] == "N1-A/Residential Dwelling"
    assert out["auctioneer"] == "Mike Lewis #10334"
    assert out["county"] == "Mecklenburg"
    assert out["tax_amount_text"] == "$3,991 ±"


def test_f_and_year_helpers():
    assert M._f("$160,000") == 160000.0
    assert M._f("11,326 ± sq. ft.") == 11326.0
    assert M._f(None) is None
    assert M._year("1998") == 1998
    assert M._year(None) is None
    assert M._year("not a year") is None


def _make_listing() -> "M.Listing":
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind
    return Listing(
        source="reo.treasury_seized",
        source_url=M.URL,
        listing_type=ListingType.REO,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        street_address="2721 Briar Ridge Drive",
        city="Charlotte",
        zip_code="28270",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"treasury_seized": {"forward_excerpt": "x"}},
    )


def test_enrich_from_detail_fills_every_real_field(monkeypatch):
    """opening_bid is the headline fix (was always None); parcel/county/
    zoning/year_built/lot_size and the document + tax amount are the rest."""
    from contextlib import asynccontextmanager

    async def get(url, **kw):
        return MagicMock(status_code=200, text=REAL_DETAIL_HTML)

    @asynccontextmanager
    async def fake_client(*a, **kw):
        stub = MagicMock()
        stub.get = get
        yield stub

    monkeypatch.setattr(M, "client", fake_client)

    li = _make_listing()
    scraper = M.TreasurySeizedRealProperty()
    asyncio.run(scraper._enrich_from_detail(li, "https://www.treasury.gov/auctions/treasury/rp/2721briar.shtml"))

    assert li.opening_bid == 160000.0
    assert li.living_sqft == 2835.0
    assert li.lot_size_sqft == 11326.0
    assert li.year_built == 1998
    assert li.parcel_id == "22727209"
    assert li.county == "Mecklenburg"
    assert li.zoning == "N1-A/Residential Dwelling"
    assert li.raw["treasury_seized"]["auctioneer"] == "Mike Lewis #10334"
    assert li.raw["treasury_seized"]["annual_tax"] == 3991.0


def test_enrich_from_detail_prefers_this_listings_own_flyer():
    """The real page's generic document harvest surfaces an UNRELATED
    cross-referenced listing's flyer (beaumontflyer.pdf) ahead of this
    listing's own (2721briarflyer.pdf) -- the targeted Auction Flyer: match
    must force the right one primary."""
    import asyncio as _asyncio
    from contextlib import asynccontextmanager

    async def get(url, **kw):
        return MagicMock(status_code=200, text=REAL_DETAIL_HTML)

    @asynccontextmanager
    async def fake_client(*a, **kw):
        stub = MagicMock()
        stub.get = get
        yield stub

    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(M, "client", fake_client)
    try:
        li = _make_listing()
        scraper = M.TreasurySeizedRealProperty()
        _asyncio.run(scraper._enrich_from_detail(
            li, "https://www.treasury.gov/auctions/treasury/rp/2721briar.shtml"
        ))
        assert li.raw["document_url"].endswith("2721briarflyer.pdf")
        assert any(u.endswith("2721briarflyer.pdf") for u in li.raw["documents"])
    finally:
        mp.undo()


def test_enrich_from_detail_never_raises_on_a_fetch_failure():
    from contextlib import asynccontextmanager

    async def get(url, **kw):
        raise OSError("connection reset")

    @asynccontextmanager
    async def fake_client(*a, **kw):
        stub = MagicMock()
        stub.get = get
        yield stub

    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(M, "client", fake_client)
    try:
        li = _make_listing()
        scraper = M.TreasurySeizedRealProperty()
        # must not raise, and must leave the list-only fields untouched.
        asyncio.run(scraper._enrich_from_detail(li, "https://x/y.shtml"))
        assert li.opening_bid is None
        assert li.county is None
    finally:
        mp.undo()


def test_full_fetch_wires_detail_enrichment_for_a_matched_listing(monkeypatch):
    """End-to-end fetch(): the list page's own NC listing gets its detail
    page fetched and opening_bid/county/parcel_id filled in -- previously
    always None/empty."""
    list_html = (
        "<html><body>" + REAL_LIST_FRAGMENT + " " * 1200 + "</body></html>"
    )

    calls = []

    async def get(url, **kw):
        calls.append(url)
        if "2721briar.shtml" in url:
            return MagicMock(status_code=200, text=REAL_DETAIL_HTML)
        return MagicMock(status_code=200, text=list_html)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_client(*a, **kw):
        stub = MagicMock()
        stub.get = get
        yield stub

    monkeypatch.setattr(M, "client", fake_client)

    out = list(asyncio.run(M.TreasurySeizedRealProperty().fetch()))
    assert len(out) == 1
    li = out[0]
    assert li.street_address == "2721 Briar Ridge Drive"
    assert li.opening_bid == 160000.0
    assert li.county == "Mecklenburg"
    assert li.parcel_id == "22727209"
    assert li.source_url.endswith("2721briar.shtml")
    assert li.raw["images"]["real"] == [
        "https://www.treasury.gov/auctions/treasury/rp/images/2721briar01.gif"
    ]
    assert any("2721briar.shtml" in u for u in calls)
