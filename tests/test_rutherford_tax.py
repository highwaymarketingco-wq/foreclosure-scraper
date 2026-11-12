"""Unit tests for the repointed Rutherford NC delinquent-tax scraper.

Fixtures are cut from the real artifacts (2026-08-03):
  * rutherford_revenue_index.html — the Revize page, <base href> and all
  * rutherford_tr452_rows.json    — real TR-452 rows in the real sheet layout
    (banner, parameter block, header, data, Subtotal/Total trailer). The repo
    .gitignore excludes *.xlsx, so the workbook is rebuilt from these rows at
    test time by tests/_xlsx_fixture.py — which also means the scraper's stdlib
    zip+iterparse reader is exercised against a genuine PK-zip file.
No network.
"""
import json
from pathlib import Path

from foreclosure_scraper.scrapers.counties_nc import rutherford_tax as m

from ._xlsx_fixture import build_xlsx

FIX = Path(__file__).parent / "fixtures"
_HTML = (FIX / "rutherford_revenue_index.html").read_text()
_ROWS = [{int(k): v for k, v in row.items()}
         for row in json.loads((FIX / "rutherford_tr452_rows.json").read_text())]
_XLSX = build_xlsx(_ROWS)


# --------------------------------------------------------------------------- #
# link discovery
# --------------------------------------------------------------------------- #

def test_discovery_resolves_against_base_href_not_the_page_path():
    """The trap that made this file 404: the anchor is a bare filename, but
    Revize declares <base href="https://www.rutherfordcountync.gov/">, so it is
    SITE-ROOT relative. Resolving against the department path 302s to
    cms6.revize.com and then hard-404s."""
    url = m._discover_xlsx_url(_HTML)
    assert url.startswith("https://www.rutherfordcountync.gov/TR-452")
    assert "revenue_department_tax_administrator" not in url


def test_discovery_percent_encodes_spaces_and_keeps_the_cache_buster():
    url = m._discover_xlsx_url(_HTML)
    assert " " not in url
    assert "%20" in url
    assert url.endswith(".xlsx?t=202602011040510")


def test_discovery_ignores_the_other_documents_on_the_page():
    assert ".docx" not in m._discover_xlsx_url(_HTML)


def test_discovery_falls_back_when_the_link_is_gone():
    assert m._discover_xlsx_url("<html><body>no links</body></html>") == m._FALLBACK_XLSX


def test_encode_spaces_leaves_the_query_string_alone():
    got = m._encode_spaces("https://h/a b c.xlsx?t=1&u=2")
    assert got == "https://h/a%20b%20c.xlsx?t=1&u=2"


# --------------------------------------------------------------------------- #
# situs splitting
# --------------------------------------------------------------------------- #

def test_split_situs_address():
    assert m._split_situs("297 E MAIN ST FOREST CITY, NC 28043") == (
        "297 E MAIN ST", "Forest City", "28043", None)


def test_split_situs_multiword_city_is_not_eaten_by_the_street():
    assert m._split_situs("0 WAMBLI PASS LAKE LURE, NC 28746") == (
        "0 WAMBLI PASS", "Lake Lure", "28746", None)


def test_split_situs_tolerates_the_missing_comma():
    # The Sturgis SitusAddress line omits the comma; the same splitter serves it.
    assert m._split_situs("0 GLEN RIDGE TRL LAKE LURE NC 28746") == (
        "0 GLEN RIDGE TRL", "Lake Lure", "28746", None)


def test_split_situs_legal_description_returns_no_address():
    street, city, zipc, legal = m._split_situs("B I COTTON MILLS LO176 SE2 PL6-59")
    assert (street, city, zipc) == (None, None, None)
    assert legal == "B I COTTON MILLS LO176 SE2 PL6-59"


def test_split_situs_drops_the_00000_placeholder_zip():
    street, city, zipc, legal = m._split_situs("827 OLD HENRIETTA RD NC 00000")
    assert street == "827 OLD HENRIETTA RD"
    assert zipc is None and city is None and legal is None


def test_split_situs_empty():
    assert m._split_situs("") == (None, None, None, None)


# --------------------------------------------------------------------------- #
# workbook parse
# --------------------------------------------------------------------------- #

def _parsed():
    return m._parse_listings(_XLSX, m.SLUG, "u")


def test_banner_header_and_total_rows_are_not_leads():
    """The sheet ends with Subtotal/Total rows carrying the full county figure.
    Letting one through would put a single multi-million-dollar phantom lead on
    the board."""
    out = _parsed()
    assert len(out) == 4
    assert all(li.parcel_id for li in out)
    assert max(li.judgment_amount for li in out) < 9000


def test_multiple_bills_on_one_parcel_are_summed_into_one_lead():
    by = {li.parcel_id: li for li in _parsed()}
    assert by["425508"].judgment_amount == 4285.79        # 4275.29 + 10.50
    assert by["425508"].raw["rutherford_tax"]["bill_count"] == 2
    assert len(by["425508"].raw["rutherford_tax"]["bill_numbers"]) == 2


def test_amount_owed_is_first_class_and_mirrored_into_raw():
    by = {li.parcel_id: li for li in _parsed()}
    li = by["1640084"]
    assert li.judgment_amount == 143.37
    assert li.raw["rutherford_tax"]["amount_owed"] == 143.37
    # nothing is for sale yet — an opening_bid here would feed _flip_candidate
    assert li.opening_bid is None


def test_listing_type_and_process():
    for li in _parsed():
        assert li.listing_type.value == "tax_lien"
        assert li.foreclosure_process == "tax"
        assert (li.state, li.county) == ("NC", "Rutherford")


def test_legal_description_rows_still_emit_and_keep_their_parcel():
    by = {li.parcel_id: li for li in _parsed()}
    li = by["1646174"]
    assert li.street_address is None
    assert li.legal_description == "FIREFLY LODGE UN101 PL29-123"
    assert li.dedupe_key().startswith("parcel:NC:rutherford:")


def test_report_metadata_is_captured():
    raw = _parsed()[0].raw["rutherford_tax"]
    assert raw["tax_year"] == "2025"
    assert raw["data_as_of"].startswith("1/31/2026")
    assert raw["dateless"] is True


def test_zero_house_number_is_flagged_not_dropped():
    by = {li.parcel_id: li for li in _parsed()}
    assert by["1640084"].raw["rutherford_tax"]["no_situs_number"] is True
    assert by["425508"].raw["rutherford_tax"]["no_situs_number"] is False


def test_owner_padding_is_stripped():
    by = {li.parcel_id: li for li in _parsed()}
    assert by["1640084"].owner_name == "PATEL, VICK"
    assert by["1640084"].defendant == "PATEL, VICK"


def test_parcel_dedupe_keys_are_unique():
    out = _parsed()
    assert len({li.dedupe_key() for li in out}) == len(out)


def test_money_helper():
    assert m._money("1,234.50") == 1234.50
    assert m._money("0") is None
    assert m._money("") is None
    assert m._money(None) is None


# --- owner decision 2026-10-07: the 10-digit PIN from the county parcel layer is parcel_id;
# the roll's Parcel_Number stays in raw (parcel_alias.py's alias). Made-up ids. ---

import asyncio as _asyncio

from foreclosure_scraper.models import Listing as _Listing, ListingType as _LT
from foreclosure_scraper.scrapers.counties_nc import rutherford_tax as _rt


class _PinResp:
    status_code = 200

    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


class _PinHttp:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        i = len(self.calls) - 1
        return _PinResp(self.pages[i] if i < len(self.pages) else {"features": []})


def _f(num, pin):
    return {"attributes": {"Parcel_Number": num, "PIN": pin}}


def test_pin_map_pages_politely_and_keeps_only_ten_digit_pins(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(_rt.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(_rt, "_PIN_PAGE", 2)
    http = _PinHttp([{"features": [_f("123456", "1600000001"), _f("1234567", "160-000-0002")],
                      "exceededTransferLimit": True},
                     {"features": [_f("7654321", "BAD")]}])
    m = _asyncio.run(_rt._pin_map(http))
    assert m == {"123456": "1600000001", "1234567": "1600000002"}
    assert [c["resultOffset"] for c in http.calls] == ["0", "2"]
    assert sleeps == [_rt._PIN_PAGE_PAUSE_S] and _rt._PIN_PAGE_PAUSE_S >= 1.6


def test_apply_pins_switches_parcel_id_and_keeps_the_roll_id():
    li = _Listing(source="counties_nc.rutherford_tax", source_url="u", listing_type=_LT.TAX_LIEN,
                  state="NC", county="Rutherford", parcel_id="123456",
                  raw={"rutherford_tax": {"parcel": "123456"}})
    other = _Listing(source="counties_nc.rutherford_tax", source_url="u", listing_type=_LT.TAX_LIEN,
                     state="NC", county="Rutherford", parcel_id="999999",
                     raw={"rutherford_tax": {"parcel": "999999"}})
    assert _rt.apply_pins([li, other], {"123456": "1600000001"}) == 1
    assert li.parcel_id == "1600000001" and li.raw["rutherford_tax"]["parcel"] == "123456"
    assert li.raw["rutherford_tax"]["pin"] == "1600000001"
    assert other.parcel_id == "999999"            # no PIN: keeps the roll id (alias still works)


def test_a_failed_pin_map_read_returns_what_it_has():
    class _Boom:
        async def get(self, *a, **k):
            raise RuntimeError("down")
    assert _asyncio.run(_rt._pin_map(_Boom())) == {}


def test_a_pin_shared_by_two_roll_parcels_is_not_applied():
    a = _Listing(source="counties_nc.rutherford_tax", source_url="u", listing_type=_LT.TAX_LIEN,
                 state="NC", county="Rutherford", parcel_id="111111",
                 raw={"rutherford_tax": {"parcel": "111111"}})
    b = _Listing(source="counties_nc.rutherford_tax", source_url="u", listing_type=_LT.TAX_LIEN,
                 state="NC", county="Rutherford", parcel_id="222222",
                 raw={"rutherford_tax": {"parcel": "222222"}})
    assert _rt.apply_pins([a, b], {"111111": "1600000009", "222222": "1600000009"}) == 0
    assert (a.parcel_id, b.parcel_id) == ("111111", "222222")
