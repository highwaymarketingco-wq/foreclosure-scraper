"""reo.vrm_va_reo: 2026-10-04 final-batch extraction-completeness audit.

This batch's highest-volume source (193 real current NC+SC rows,
live-confirmed). Two confirmed findings:

1. A 9th+ instance of the RAW_KEEP silent-drop pattern this whole 21-batch
   audit kept finding: beds/baths/sqft/list_price were flat, unregistered
   raw keys (only vrm_id/images survived _slim_raw()). Namespaced under a
   newly-registered raw['vrm_va_reo'].
2. The detail page carries a full photo gallery (28 real photos vs. the
   card's single thumbnail), the real listing agent's name/phone/email/
   license (free contactability, server-rendered), the full narrative
   description, MLS ID, parcel number, year built, and a refined property
   type. ``REAL_DETAIL_HTML`` below is a trimmed-but-real capture
   (2026-10-04, vrmproperties.com, 508 Redwood Pl Unit#2, Jacksonville NC).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from foreclosure_scraper.scrapers.reo import vrm_va_reo as M
from foreclosure_scraper.web_artifact import RAW_KEEP

REAL_CARD_HTML = """
<div class="card">
  <a href="/Property-For-Sale/31766/508-redwood-pl-unit#2-jacksonville-nc-28540">
    <img class="img-fit" src="https://media.vrmproperties.com/media/5c18a621-3604-42f2-bbd0-38cfa6677cfa">
  </a>
  <div class="card-body">
    <h6 class="card-subtitle">$199,000</h6>
    <p class="card-text properCase">508 Redwood Pl Unit#2<br>Jacksonville, NC 28540</p>
    <p class="card-text specs">
      <span>2&nbsp;<i title="Beds"></i></span>
      <span>2&nbsp;<i title="Baths"></i></span>
      <span>1,149&nbsp;<i title="Square Feet"></i></span>
    </p>
  </div>
</div>
"""

REAL_DETAIL_HTML = """
<html><body>
<p id="shortDesc">Welcome to 508 Redwood...<span id="dots">...</span></p>
<p id="longDesc" style="display:none">Welcome to 508 Redwood Place, Unit 2, a three-level townhome just outside the Jacksonville city limits. The first floor includes a one-car garage, a bedroom, and a full bath.</p>
<div class="col-12 col-bold-font">House Facts</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-2 mr-0 pr-0 mb-2">Property ID</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-4 ml-0 mr-0 pl-0 pr-0 mb-2">191981</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-2 mr-0 pr-0 mb-2">MLS ID</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-4 ml-0 mr-0 pl-0 pr-0 mb-2">
100607302                    </div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-2 mr-0 pr-0 mb-2">Status</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-4 ml-0 mr-0 pl-0 pr-0 mb-2">For Sale</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-2 mr-0 pr-0 mb-2">Stories</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-4 ml-0 mr-0 pl-0 pr-0 mb-2">
3                    </div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-2 mr-0 pr-0 mb-2">Property type</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-4 ml-0 mr-0 pl-0 pr-0 mb-2">Townhome</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-2 mr-0 pr-0 mb-2">HOA</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-4 ml-0 mr-0 pl-0 pr-0 mb-2">No</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-2 mr-0 pr-0 mb-2">Parcel Number</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-4 ml-0 mr-0 pl-0 pr-0 mb-2">
                        Unknown
                    </div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-2 mr-0 pr-0 mb-2">Lot</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-4 ml-0 mr-0 pl-0 pr-0 mb-2">
544 SF                    </div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-2 mr-0 pr-0 mb-2">Year Built</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-4 ml-0 mr-0 pl-0 pr-0 mb-2">
2023                    </div>
<div id="brokerAccordionBody" class="collapse">
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-4 mr-0 pr-0 mb-2 col-bold-font">Agent</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-8 ml-0 mr-0 pl-0 pr-0 mb-2"></div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-4 mr-0 pr-0 mb-2">Name</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-8 ml-0 mr-0 pl-0 pr-0 mb-2">Jeff&nbsp;Sweyer</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-4 mr-0 pr-0 mb-2">Phone</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-8 ml-0 mr-0 pl-0 pr-0 mb-2">(910) 555-0386</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-4 mr-0 pr-0 mb-2">Email</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-8 ml-0 mr-0 pl-0 pr-0 mb-2">contact23@sample-mail.test</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-4 mr-0 pr-0 mb-2">License</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-8 ml-0 mr-0 pl-0 pr-0 mb-2">192129</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-4 mr-0 pr-0 mb-2 col-bold-font">Brokerage</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-8 ml-0 mr-0 pl-0 pr-0 mb-2"></div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-4 mr-0 pr-0 mb-2">Name</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-8 ml-0 mr-0 pl-0 pr-0 mb-2">Berkshire Hathaway HomeServices Carolina Premier P</div>
<div class="col-6 col-sm-3 col-md-5 col-lg-4 col-xxl-4 mr-0 pr-0 mb-2">Phone</div>
<div class="col-6 col-sm-9 col-md-7 col-lg-8 col-xxl-8 ml-0 mr-0 pl-0 pr-0 mb-2">(910) 555-0288</div>
</div>
<img class="d-block" src="https://media.vrmproperties.com/media/1cb590f7-9160-4911-a559-23e1bdfe9986">
<img class="d-block" src="https://media.vrmproperties.com/media/cad420d7-ece3-4ba1-80e8-6d7b06d09886">
<img class="d-block" src="https://media.vrmproperties.com/media/5c18a621-3604-42f2-bbd0-38cfa6677cfa">
</body></html>
"""


def test_vrm_va_reo_raw_key_is_registered():
    assert "vrm_va_reo" in RAW_KEEP
    assert RAW_KEEP["vrm_va_reo"] == "*"


def test_parse_card_namespaces_beds_baths_sqft_list_price():
    from selectolax.parser import HTMLParser
    card = HTMLParser(REAL_CARD_HTML).css_first("div.card")
    li = M._parse_card(card, "NC", "reo.vrm_va_reo")
    assert li is not None
    assert "beds" not in li.raw  # no longer flat/unregistered
    assert li.raw["vrm_va_reo"] == {
        "beds": 2, "baths": 2, "sqft": 1149, "list_price": 199000.0,
    }
    assert li.raw["images"] == {
        "real": ["https://media.vrmproperties.com/media/5c18a621-3604-42f2-bbd0-38cfa6677cfa"]
    }


def test_parse_detail_page_extracts_house_facts_and_agent_contact():
    out = M._parse_detail_page(REAL_DETAIL_HTML)
    assert out["mls_id"] == "100607302"
    assert out["status"] == "For Sale"
    assert out["stories"] == "3"
    assert out["property_type"] == "Townhome"
    assert out["hoa"] == "No"
    assert out["parcel_number"] == "Unknown"
    assert out["lot_text"] == "544 SF"
    assert out["year_built_text"] == "2023"
    assert out["agent_name"] == "Jeff Sweyer"
    assert out["agent_phone"] == "(910) 555-0386"
    assert out["agent_email"] == "contact23@sample-mail.test"
    assert out["agent_license"] == "192129"
    assert "three-level townhome" in out["description"]
    assert len(out["gallery"]) == 3


def test_parse_detail_page_does_not_conflate_agent_and_brokerage_name():
    """The real bug this fix caught live: a naive flat dict lets the
    Brokerage sub-block's own 'Name'/'Phone' overwrite the individual
    Agent's, since both share identical labels in the same accordion."""
    out = M._parse_detail_page(REAL_DETAIL_HTML)
    assert out["agent_name"] == "Jeff Sweyer"
    assert out["brokerage_name"] == "Berkshire Hathaway HomeServices Carolina Premier P"
    assert out["agent_phone"] == "(910) 555-0386"
    assert out["brokerage_phone"] == "(910) 555-0288"


def test_parse_lot_sqft_units():
    assert M._parse_lot_sqft("544 SF") == 544.0
    assert M._parse_lot_sqft("0.75 Acres") == 0.75 * 43560.0
    assert M._parse_lot_sqft(None) is None


def _make_listing() -> "M.Listing":
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind
    return Listing(
        source="reo.vrm_va_reo",
        source_url="https://vrmproperties.com/Property-For-Sale/31766/508-redwood-pl",
        listing_type=ListingType.REO, property_kind=PropertyKind.SINGLE_FAMILY,
        state="NC", street_address="508 Redwood Pl Unit#2", city="Jacksonville",
        case_number="vrm-31766", opening_bid=199000.0,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={"vrm_id": "31766", "vrm_va_reo": {"beds": 2, "baths": 2, "sqft": 1149, "list_price": 199000.0}},
    )


def test_enrich_from_detail_fills_agent_contact_above_all():
    """HERMES sec 9's #1 priority: free contactability."""
    c = AsyncMock()
    c.get = AsyncMock(return_value=MagicMock(status_code=200, text=REAL_DETAIL_HTML))
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li))
    assert li.raw["vrm_va_reo"]["agent_name"] == "Jeff Sweyer"
    assert li.raw["vrm_va_reo"]["agent_phone"] == "(910) 555-0386"
    assert li.raw["vrm_va_reo"]["agent_email"] == "contact23@sample-mail.test"
    # beds/baths/sqft/list_price from the card must survive, untouched
    assert li.raw["vrm_va_reo"]["beds"] == 2


def test_enrich_from_detail_extends_gallery_and_upgrades_property_type():
    c = AsyncMock()
    c.get = AsyncMock(return_value=MagicMock(status_code=200, text=REAL_DETAIL_HTML))
    li = _make_listing()
    li.raw["images"] = {"real": ["https://media.vrmproperties.com/media/5c18a621-3604-42f2-bbd0-38cfa6677cfa"]}
    asyncio.run(M._enrich_from_detail(c, li))
    assert len(li.raw["images"]["real"]) == 3  # 1 card photo + 2 new gallery photos, deduped
    from foreclosure_scraper.models import PropertyKind
    assert li.property_kind == PropertyKind.TOWNHOUSE  # was SINGLE_FAMILY on the card


def test_enrich_from_detail_sets_year_built_and_lot_and_real_description():
    c = AsyncMock()
    c.get = AsyncMock(return_value=MagicMock(status_code=200, text=REAL_DETAIL_HTML))
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li))
    assert li.year_built == 2023
    assert li.lot_size_sqft == 544.0
    assert "three-level townhome" in li.description


def test_enrich_from_detail_skips_an_unknown_parcel_number():
    c = AsyncMock()
    c.get = AsyncMock(return_value=MagicMock(status_code=200, text=REAL_DETAIL_HTML))
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li))
    assert li.parcel_id is None  # "Unknown" on the real page -- never fabricated


def test_enrich_from_detail_never_raises_on_fetch_failure():
    c = AsyncMock()
    c.get = AsyncMock(side_effect=OSError("connection reset"))
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li))
    assert li.year_built is None  # untouched, not crashed


def test_fetch_state_respects_the_detail_budget():
    """Budgeted, not per-card: exhausting the counter mid-page must stop
    further detail fetches for the SAME run."""
    from contextlib import asynccontextmanager

    list_html = ("<html><body>" + REAL_CARD_HTML + REAL_CARD_HTML.replace(
        "31766", "31767").replace("508-redwood", "999-other") + " " * 1200
        + "</body></html>")

    detail_calls = []

    async def get(url, **kw):
        if "Property-For-Sale" in url and "Properties-For-Sale" not in url:
            detail_calls.append(url)
            return MagicMock(status_code=200, text=REAL_DETAIL_HTML)
        return MagicMock(status_code=200, text=list_html)

    @asynccontextmanager
    async def fake_client(*a, **kw):
        stub = MagicMock()
        stub.get = get
        yield stub

    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(M, "client", fake_client)
    try:
        budget = [1]  # only ONE detail fetch allowed this whole run
        out = asyncio.run(M._fetch_state("NC", "reo.vrm_va_reo", detail_budget=budget))
        assert len(out) == 2  # both cards parsed
        assert len(detail_calls) == 1  # but only one got enriched
        assert budget[0] == 0
    finally:
        mp.undo()
