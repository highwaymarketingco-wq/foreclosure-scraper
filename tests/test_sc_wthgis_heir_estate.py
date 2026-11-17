"""counties_sc.sc_wthgis_heir_estate -- live WTH "tgis" heir/estate/life-estate sweep.

Fixtures below are trimmed excerpts of REAL markup captured live 2026-11-17 from
chesterfieldsc.wthgis.com/tgis/custom.aspx (DSID=6796, SearchType=Name) and
getftr.aspx. No network calls in these tests; fetch() itself is exercised with a
monkeypatched httpx.AsyncClient (no real request leaves the process).

Confirms:
  - _field()/_parse_detail() survive the real `<th>...</th><td ...>...</td>` table
    shape, including the money cells' extra `style="text-align: right;"` attribute
  - _parse_search_hits() parses the real `showf(DSID , FID)` / `mainResultItem` pair
  - _classify(): a real "Life Estate" owner passes (and is tagged life_estate, not
    probate); a real decedent-heir owner passes (tagged probate/heirs); a real
    "Real Estate" business name is correctly excluded; a owner-less/garbage record
    yields nothing
  - fetch() end-to-end: two search tokens whose hits overlap on one FeatureID
    dedupe to one Listing each, every emitted Listing carries
    listing_type == ESTATE_LEAD, and a detail fetch that 404s is skipped cleanly
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_sc import sc_wthgis_heir_estate as m

# Real getftr.aspx detail-table cells, FeatureID 68 (Chesterfield, live 2026-11-17).
REAL_LIFE_ESTATE_DETAIL = """
<table>
<tr><th>Map&nbsp;Number</th><td>001 000 000 046</td></tr>
<tr><th>Owner&nbsp;Name</th><td>Blakeney Mavis T Life Estate</td></tr>
<tr><th>Owner&nbsp;Name2</th><td></td></tr>
<tr><th>Property&nbsp;Address1</th><td>394 Hazel Blakeney Rd</td></tr>
<tr><th>MarketValueTotalValue</th><td style="text-align: right;">16200.00</td></tr>
<tr><th>MarketValueAcres</th><td style="text-align: right;">2.70</td></tr>
<tr><th>TaxValueTotalValue</th><td style="text-align: right;">11100.00</td></tr>
</table>
"""

# Real search-result row markup, same FeatureID (Chesterfield, live 2026-11-17).
REAL_SEARCH_ROW = (
    "omToParcel onclick='showf(6796 , 68)'>Zoom</button></div>"
    "<div id=resultsParcelNumber class='mainResultItem'>001 000 000 046</div><div "
)

# A second, decedent (non-life-estate) real owner name, same platform/session.
REAL_HEIR_DETAIL = """
<tr><th>Map&nbsp;Number</th><td>090 000 000 212</td></tr>
<tr><th>Owner&nbsp;Name</th><td>Heirs Ann C</td></tr>
<tr><th>Owner&nbsp;Name2</th><td></td></tr>
<tr><th>Property&nbsp;Address1</th><td></td></tr>
"""

# A real business-name false positive that _excluded_row must drop.
REAL_EXCLUDED_DETAIL = """
<tr><th>Map&nbsp;Number</th><td>077 000 000 001</td></tr>
<tr><th>Owner&nbsp;Name</th><td>Walters Real Estate and</td></tr>
"""

# Real search-result row markup, Marion's own shape (DSID=1064, FeatureID 538,
# live 2026-11-17): mainResultItem renders EMPTY and the real TMS Number is in a
# sibling secondaryResultItem div instead -- the shape every other county on this
# platform does NOT use (round 19).
REAL_MARION_SEARCH_ROW = (
    "onclick='showf(1064 , 538)'></div><button id=btnViewPropertyRecordCard "
    "onclick='printPropertyRecordCard(1064 , 538)'>Card</button>"
    "<button id=btnZoomToParcel onclick='showf(1064 , 538)'>Zoom</button></div>"
    "<div id=resultsParcelNumber class='mainResultItem'></div>"
    "<div class='secondaryResultItem'>5081223000000</div>"
)

# Real getftr.aspx detail-table cells, Marion's own <th> label schema (DSID=1064,
# FeatureID 538, live 2026-11-17): TMS&nbsp;Number not Map&nbsp;Number,
# Owner&nbsp;Name1 not Owner&nbsp;Name, Description doing Property&nbsp;Address1's
# job, and no MarketValueTotalValue/TaxValueTotalValue/MarketValueAcres/Mailing
# fields at all.
REAL_MARION_DETAIL = """
<tr><th>TMS&nbsp;Number</th><td>5081223000000</td></tr>
<tr><th>Owner&nbsp;Name1</th><td>HARDEES REAL ESTATE INVESTMENT</td></tr>
<tr><th>Owner&nbsp;Name2</th><td></td></tr>
<tr><th>Description</th><td>405 CHARLESTON ST</td></tr>
"""

# Same Marion schema, a real genuine decedent hit (not a business name), FeatureID
# 14442, live 2026-11-17.
REAL_MARION_DECEDENT_DETAIL = """
<tr><th>TMS&nbsp;Number</th><td>0850000191000</td></tr>
<tr><th>Owner&nbsp;Name1</th><td>ESTATE OF SHELBY MCLELLAN</td></tr>
<tr><th>Owner&nbsp;Name2</th><td></td></tr>
<tr><th>Description</th><td></td></tr>
"""

MARION_FIELDS = m._WTHGIS_COUNTIES["Marion"]["fields"]


def test_field_reads_plain_and_styled_cells():
    assert m._field(REAL_LIFE_ESTATE_DETAIL, "Owner&nbsp;Name") == "Blakeney Mavis T Life Estate"
    assert m._field(REAL_LIFE_ESTATE_DETAIL, "MarketValueTotalValue") == "16200.00"
    assert m._field(REAL_LIFE_ESTATE_DETAIL, "Property&nbsp;Address1") == "394 Hazel Blakeney Rd"
    assert m._field(REAL_LIFE_ESTATE_DETAIL, "Nonexistent&nbsp;Field") == ""


def test_parse_search_hits_real_row():
    hits = m._parse_search_hits(REAL_SEARCH_ROW)
    assert hits == {"001 000 000 046": 68}


def test_parse_detail_real_life_estate_record():
    rec = m._parse_detail(REAL_LIFE_ESTATE_DETAIL)
    assert rec["map_number"] == "001 000 000 046"
    assert rec["owner"] == "Blakeney Mavis T Life Estate"
    assert rec["address"] == "394 Hazel Blakeney Rd"
    assert rec["market_value"] == 16200.00
    assert rec["acreage"] == 2.70
    assert rec["tax_value"] == 11100.00


def test_parse_detail_no_map_number_is_none():
    assert m._parse_detail("<tr><th>Owner&nbsp;Name</th><td>Nobody</td></tr>") is None


def test_classify_real_life_estate_owner():
    rec = m._parse_detail(REAL_LIFE_ESTATE_DETAIL)
    cls = m._classify(rec)
    assert cls is not None
    assert cls["is_life_estate"] is True
    assert cls["match"] == "life_estate"
    assert cls["owner"] == "Blakeney Mavis T Life Estate"


def test_classify_real_heir_owner_is_probate_not_life_estate():
    rec = m._parse_detail(REAL_HEIR_DETAIL)
    cls = m._classify(rec)
    assert cls is not None
    assert cls["is_life_estate"] is False
    assert cls["match"] == "heirs"


def test_classify_real_business_name_is_excluded():
    rec = m._parse_detail(REAL_EXCLUDED_DETAIL)
    cls = m._classify(rec)
    assert cls is None


def test_classify_empty_owner_is_none():
    assert m._classify({"owner": "", "owner2": ""}) is None
    assert m._classify({"owner": None}) is None


def test_parse_search_hits_falls_back_to_secondary_result_item():
    # Marion's own shape (round 19): mainResultItem is empty, the real TMS Number
    # lives in the sibling secondaryResultItem div instead.
    hits = m._parse_search_hits(REAL_MARION_SEARCH_ROW)
    assert hits == {"5081223000000": 538}


def test_parse_search_hits_mixed_shapes_in_one_page():
    # A page carrying both shapes (never actually happens -- one page is one
    # county -- but proves the mainResultItem branch still wins when populated,
    # matching every pre-round-19 county's own behavior unchanged).
    mixed = REAL_SEARCH_ROW + REAL_MARION_SEARCH_ROW
    hits = m._parse_search_hits(mixed)
    assert hits == {"001 000 000 046": 68, "5081223000000": 538}


def test_parse_detail_marion_schema_override():
    rec = m._parse_detail(REAL_MARION_DETAIL, MARION_FIELDS)
    assert rec["map_number"] == "5081223000000"
    assert rec["owner"] == "HARDEES REAL ESTATE INVESTMENT"
    assert rec["address"] == "405 CHARLESTON ST"
    # Marion's schema has none of these cells -- genuine None, not a parsing miss.
    assert rec["mailing"] is None
    assert rec["market_value"] is None
    assert rec["tax_value"] is None
    assert rec["acreage"] is None


def test_parse_detail_marion_business_name_excluded():
    rec = m._parse_detail(REAL_MARION_DETAIL, MARION_FIELDS)
    assert m._classify(rec) is None  # "...REAL ESTATE INVESTMENT" is a business


def test_parse_detail_marion_real_decedent_classifies():
    rec = m._parse_detail(REAL_MARION_DECEDENT_DETAIL, MARION_FIELDS)
    cls = m._classify(rec)
    assert cls is not None
    assert cls["match"] == "estate"
    assert cls["is_life_estate"] is False


def test_parse_detail_without_fields_override_is_unchanged():
    # Omitting `fields` entirely must behave exactly like round 18 (Chesterfield/
    # Dillon/McCormick never pass an override).
    assert m._parse_detail(REAL_LIFE_ESTATE_DETAIL) == m._parse_detail(REAL_LIFE_ESTATE_DETAIL, None)


def test_counties_filter_restricts_the_sweep():
    s = m.SCWthgisHeirEstate(counties=["Dillon", "Marion"])
    assert set(s._counties) == {"Dillon", "Marion"}


def test_counties_filter_rejects_unknown_county():
    import pytest
    with pytest.raises(ValueError, match="Someplace"):
        m.SCWthgisHeirEstate(counties=["Someplace"])


def test_default_registry_includes_all_round19_counties():
    assert set(m._WTHGIS_COUNTIES) == {"Chesterfield", "Dillon", "McCormick", "Marion"}


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _FakeAsyncClient:
    """Routes GETs by substring match on the URL -- enough to drive fetch()
    through a full search-then-detail pass with no real network."""

    def __init__(self, routes: dict[str, str], headers=None):
        self._routes = routes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, timeout=None):
        for needle, text in self._routes.items():
            if needle in url:
                return _FakeResponse(text)
        return _FakeResponse("", status_code=404)


def test_fetch_dedupes_across_search_tokens_and_tags_estate_lead(monkeypatch):
    # Both the ESTATE and HEIR searches surface the SAME FeatureID (68) plus one
    # token-exclusive hit each; fetch() must not double-count FeatureID 68 and
    # must skip a detail fetch that 404s cleanly rather than raising.
    estate_search = (
        REAL_SEARCH_ROW +
        "<button onclick='showf(6796 , 212)'>Zoom</button>"
        "<div class='mainResultItem'>090 000 000 212</div>"
    )
    heir_search = (
        REAL_SEARCH_ROW +  # same FeatureID 68 re-surfaced under the HEIR token
        "<button onclick='showf(6796 , 999)'>Zoom</button>"
        "<div class='mainResultItem'>999 000 000 999</div>"  # detail 404s below
    )
    routes = {
        "SearchCriteria=ESTATE": estate_search,
        "SearchCriteria=HEIR": heir_search,
        "F=68": REAL_LIFE_ESTATE_DETAIL,
        "F=212": REAL_HEIR_DETAIL,
        # F=999 intentionally absent -> _FakeAsyncClient returns 404
    }

    def _fake_client(headers=None):
        return _FakeAsyncClient(routes)

    monkeypatch.setattr(m.httpx, "AsyncClient", _fake_client)

    # Scoped to Chesterfield alone (round 19 added Dillon/McCormick/Marion to the
    # registry; the fake client's URL-substring routing would otherwise also
    # "find" these same canned fixtures under every other county's own DSID).
    s = m.SCWthgisHeirEstate(counties=["Chesterfield"])
    rows = asyncio.run(s.fetch())

    assert len(rows) == 2  # FeatureID 68 once (deduped) + 212; 999 skipped (404)
    assert all(li.listing_type == ListingType.ESTATE_LEAD for li in rows)
    assert all(li.state == "SC" and li.county == "Chesterfield" for li in rows)
    by_parcel = {li.parcel_id: li for li in rows}
    assert by_parcel["001 000 000 046"].raw["heir_estate"]["life_estate"] is True
    assert by_parcel["090 000 000 212"].raw["heir_estate"]["life_estate"] is False
    assert s.run_stats["kept"] == 2
