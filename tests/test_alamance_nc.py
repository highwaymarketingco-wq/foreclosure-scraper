"""Alamance County NC Spatialest card adapter -- parsing + resolver, pure/offline.

Fixtures below are the ACTUAL JSON Alamance's property.spatialest.com returned for two
real, live-queried parcels on 2026-10-20 (vacant land #100395, improved single-family
#100396) -- not guessed shapes. See the module docstring in
src/foreclosure_scraper/assessor_cards/alamance_nc.py for the verification trail.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from foreclosure_scraper.assessor_cards import alamance_nc as an

# ---- real recordcard JSON, vacant land (no dwelling block) ----
VACANT_CARD = {
    "id": "100395",
    "parcel": {
        "header": {
            "parcel_number": 100395,
            "physical_street_address": "SILK HOPE LIBERTY RD",
            "current_owner_name_1": "RAMSEUR CATTLE FARM LLC",
            "total_FMV_current": "$48,231",
            "grouping_parcel_num": "8736927627",
        },
        "sections": [
            [
                [{"parcel_number": 100395, "map_pin": "8736927627",
                  "description_1": "VACANT LAND 10-19 ACRES", "map_acres": "15.62"}],
                [{"land_FMV_cur": "$48,231", "improve_FMV_cur": "$0",
                  "total_FMV_current": "$48,231"}],
            ],
            [[]],
            [[{"current_owner_id": "0720075", "current_owner_name_1": "RAMSEUR CATTLE FARM LLC"}]],
            [[
                {"date_sold": "01/04/2023", "deed_name": "RAMSEUR CATTLE FARM LLC",
                 "deed_book": "4428-0206", "tax_year": 2024, "sales_amount": "$102,000",
                 "qualify_code": None},
                {"date_sold": "07/19/2017", "deed_name": "CAMPEAU DANIEL",
                 "deed_book": "3680-0069", "tax_year": 2018, "sales_amount": "$33,000",
                 "qualify_code": None},
                {"date_sold": "09/19/2000", "deed_name": "MANNING JUDITH K",
                 "deed_book": "1425-703", "tax_year": 2001, "sales_amount": "$0",
                 "qualify_code": None},
            ]],
        ],
    },
}

# ---- real recordcard JSON, improved single-family ----
IMPROVED_CARD = {
    "id": "100396",
    "parcel": {
        "header": {
            "parcel_number": 100396,
            "physical_street_address": "3557 SILK HOPE LIBERTY RD",
            "current_owner_name_1": "SMITH GEORGE FRANKLIN SR HEIRS",
            "total_FMV_current": "$228,809",
            "grouping_parcel_num": "8736935462",
        },
        "sections": [
            [
                [{"parcel_number": 100396, "description_1": "SINGLE FAMILY", "map_acres": "3.31"}],
                [{"land_FMV_cur": "$46,684", "improve_FMV_cur": "$182,125",
                  "total_FMV_current": "$228,809"}],
            ],
            [[{
                "year_actually_built": 1958, "component_code_desc": "SITE BUILT",
                "finished_area": "1,616 sqft", "fireplace": "Y", "basement": "N",
                "num_of_bathrooms": "2 Full Bath(s)", "num_of_half_baths": "0 Half Bath(s)",
                "num_of_bedrooms": 2, "num_of_stories": "1.00",
            }]],
            [[{"current_owner_id": "0637235", "current_owner_name_1": "SMITH GEORGE FRANKLIN SR HEIRS"}]],
            [[
                {"date_sold": "12/25/2011", "qualify_code": "E", "deed_name": "SMITH GEORGE F SR HEIRS",
                 "deed_book": "2303-0154", "tax_year": 2012, "sales_amount": "$0"},
                {"date_sold": "09/09/2005", "qualify_code": "E", "deed_name": "SMITH GEORGE F SR",
                 "deed_book": "2303-0154", "tax_year": 2006, "sales_amount": "$0"},
                {"date_sold": "03/05/1986", "qualify_code": "D",
                 "deed_name": "SMITH GEORGE FRANKLIN & SMITH DOROTHY FLYNT",
                 "deed_book": "0510-0648", "tax_year": 1987, "sales_amount": "$0"},
            ]],
        ],
    },
}


# ---- pure parsing ----

def test_parse_vacant_land_fills_value_and_sales_but_no_dwelling():
    res = an.parse_card(VACANT_CARD)
    assert res.market_value == 48231.0
    assert res.living_sqft is None and res.year_built is None and res.bedrooms is None
    assert len(res.sales) == 3
    # newest-first
    assert res.sales[0].sale_date == "2023-01-04" and res.sales[0].price == 102000.0
    assert res.sales[0].book == "4428" and res.sales[0].page == "0206"
    assert res.sales[-1].sale_date == "2000-09-19" and res.sales[-1].price is None  # $0 -> None
    assert res.has_fill()   # market_value + sales alone still count as a fill


def test_parse_improved_fills_dwelling_specs_and_sales():
    res = an.parse_card(IMPROVED_CARD)
    assert res.market_value == 228809.0
    assert res.living_sqft == 1616.0 and res.living_sqft_is_heated is True
    assert res.year_built == 1958
    assert res.bedrooms == 2.0
    assert res.bathrooms == 2.0   # 2 full + 0 half
    assert len(res.sales) == 3
    assert res.sales[0].sale_date == "2011-12-25"
    assert res.sales[0].book == "2303" and res.sales[0].page == "0154"
    assert res.sales[0].reason == "E" and res.sales[0].grantor == "SMITH GEORGE F SR HEIRS"
    # oldest sale (1986) sorts last
    assert res.sales[-1].sale_date == "1986-03-05"


def test_split_book_page():
    assert an._split_book_page("4428-0206") == ("4428", "0206")
    assert an._split_book_page("69") == ("69", None)
    assert an._split_book_page(None) == (None, None)


def test_deed_date_iso_drops_placeholder_years():
    assert an._deed_date_iso("1/4/2023") == "2023-01-04"
    assert an._deed_date_iso("1/1/1899") is None   # pre-1900 placeholder
    assert an._deed_date_iso("not a date") is None


def test_money_parses_dollar_strings_and_rejects_zero():
    from foreclosure_scraper.assessor_cards.base import money
    assert money("$102,000") == 102000.0
    assert money("$0") is None


# ---- resolver: trust ONLY a single exact-match id, never an ambiguous list ----

class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    """Minimal async stand-in for the httpx client, scripted per test."""

    def __init__(self, *, root_text="", post_by_term=None, card_by_pid=None):
        self.root_text = root_text
        self.post_by_term = post_by_term or {}
        self.card_by_pid = card_by_pid or {}
        self.posted_terms: list[str] = []

    async def get(self, url, headers=None):
        if url == an.SOURCE_URL:
            return _FakeResp(200, text=self.root_text)
        pid = url.rsplit("/", 1)[-1]
        if pid in self.card_by_pid:
            return _FakeResp(200, payload=self.card_by_pid[pid])
        return _FakeResp(404, payload={})

    async def post(self, url, json=None, headers=None):
        term = (json or {}).get("filters", {}).get("term")
        self.posted_terms.append(term)
        return _FakeResp(200, payload=self.post_by_term.get(term, {}))


def _lead(parcel_id=None, street_address=None):
    return SimpleNamespace(parcel_id=parcel_id, street_address=street_address)


def test_resolve_pid_trusts_a_single_id_hit_from_the_pin():
    c = _FakeClient(post_by_term={"8736935462": {"id": 100396}})
    pid = asyncio.run(an._resolve_pid(c, {}, _lead(parcel_id="8736935462")))
    assert pid == "100396"
    assert c.posted_terms == ["8736935462"]   # PIN tried first, succeeded -> no address fallback


def test_resolve_pid_falls_back_to_address_when_pin_misses():
    c = _FakeClient(post_by_term={
        "3557 SILK HOPE LIBERTY RD": {"id": 100396},
    })
    pid = asyncio.run(an._resolve_pid(
        c, {}, _lead(parcel_id="9999999999", street_address="3557 SILK HOPE LIBERTY RD")))
    assert pid == "100396"
    assert c.posted_terms == ["9999999999", "3557 SILK HOPE LIBERTY RD"]


def test_resolve_pid_never_guesses_from_an_ambiguous_results_list():
    # "SILK HOPE LIBERTY RD" alone (live-observed) returns a `results` list of 8
    # candidates, no `id` -- must NOT bind to any of them.
    c = _FakeClient(post_by_term={
        "SILK HOPE LIBERTY RD": {"results": [{"ParcelIdentifier": 100395}, {"ParcelIdentifier": 100396}]},
    })
    pid = asyncio.run(an._resolve_pid(c, {}, _lead(street_address="SILK HOPE LIBERTY RD")))
    assert pid is None


def test_resolve_pid_returns_none_with_no_pin_or_address():
    c = _FakeClient()
    pid = asyncio.run(an._resolve_pid(c, {}, _lead()))
    assert pid is None
    assert c.posted_terms == []


# ---- end to end fetch() ----

def test_fetch_end_to_end_improved_parcel():
    csrf_html = '<meta name="csrf-token" content="abc123">'
    c = _FakeClient(
        root_text=csrf_html,
        post_by_term={"8736935462": {"id": 100396}},
        card_by_pid={"100396": IMPROVED_CARD},
    )

    # fetch() opens its own client() context manager; patch it to hand back our fake.
    import foreclosure_scraper.assessor_cards.alamance_nc as mod

    class _CM:
        async def __aenter__(self):
            return c

        async def __aexit__(self, *a):
            return False

    orig_client = mod.client
    mod.client = lambda *a, **kw: _CM()
    try:
        res = asyncio.run(mod.fetch(_lead(parcel_id="8736935462")))
    finally:
        mod.client = orig_client

    assert res is not None
    assert res.living_sqft == 1616.0
    assert res.market_value == 228809.0
    assert res.source_url.endswith("#/property/100396")


def test_fetch_returns_none_when_priming_fails():
    c = _FakeClient(root_text="<html>no csrf meta here</html>")
    import foreclosure_scraper.assessor_cards.alamance_nc as mod

    class _CM:
        async def __aenter__(self):
            return c

        async def __aexit__(self, *a):
            return False

    orig_client = mod.client
    mod.client = lambda *a, **kw: _CM()
    try:
        res = asyncio.run(mod.fetch(_lead(parcel_id="8736935462")))
    finally:
        mod.client = orig_client
    assert res is None


def test_adapter_is_auto_discovered():
    """COUNTY tuple must match the exact (state, county) auto-discovery expects."""
    assert an.COUNTY == ("NC", "Alamance")
    from foreclosure_scraper import enrichment_assessor_card as eac
    adapters = eac._adapters()
    assert ("NC", "Alamance") in adapters
    assert adapters[("NC", "Alamance")] is an.fetch
