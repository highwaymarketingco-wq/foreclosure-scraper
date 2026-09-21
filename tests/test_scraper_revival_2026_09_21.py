"""Offline revival tests, 2026-09-21: gaston_tax_foreclosures, sc_tax_delinquent, anderson_sheriff,
daily_courier and funeral_home_rss. Hand-built or synthetic samples only; no network.

Each test is anchored to something measured live the same day, named in its docstring.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from foreclosure_scraper import main as M
from foreclosure_scraper.models import ListingType

FIX = Path(__file__).parent / "fixtures"


class Resp:
    def __init__(self, status=200, text="", headers=None, url="https://x/"):
        self.status_code, self.text, self.headers, self.url = status, text, headers or {}, url


class FakeClient:
    """Scripted GET responses by URL substring; records every request."""

    def __init__(self, routes=None, default=None):
        self.routes = routes or {}
        self.default = default
        self.calls: list[str] = []

    async def get(self, url, **kw):
        self.calls.append(url)
        for key in sorted(self.routes, key=len, reverse=True):     # most specific route wins
            if (url == key[1:]) if key.startswith("=") else (key in url):   # "=URL" means exact match
                val = self.routes[key]
                item = val.pop(0) if isinstance(val, list) and len(val) > 1 else (val[0] if isinstance(val, list) else val)
                if isinstance(item, Exception):
                    raise item
                return item
        if self.default is not None:
            if isinstance(self.default, Exception):
                raise self.default
            return self.default
        return Resp(404, "")


def _patch_client(monkeypatch, module, fake):
    @asynccontextmanager
    async def cm(**kw):
        yield fake
    monkeypatch.setattr(module, "client", cm)


# =========================================================================== #
# gaston_tax_foreclosures
# =========================================================================== #

from foreclosure_scraper.scrapers.counties_nc import gaston_tax_foreclosures as gaston  # noqa: E402

_FUTURE = (datetime.utcnow() + timedelta(days=12)).strftime("%B %d, %Y").replace(" 0", " ")
_UPSET = (datetime.utcnow() + timedelta(days=22)).strftime("%B %d, %Y").replace(" 0", " ")

_GASTON_PAGE = f"""<html><body><div class="fr-view">
<p>Owner: Closed Sold Owner</p><p>Parcel: 100001</p><p>Physical Address: 1 Sold St., Gastonia, NC</p>
<p>Sale Date: January 21, 2026 at 10 am.</p><p>Current Bid: $96,600.00</p><p>Last Day to Upset: March 5, 2026</p>
<p>File Number: 25 M 100</p><p>Sale Closed-Property Sold</p>
<p>Owner: Old Ordinal Owner</p><p>Parcel: 100002</p><p>Physical Address: 2 Old Rd., Dallas, NC</p>
<p>Sale Date: August 4th, 2021 at 10 am.</p><p>Current Bid: $71,662.50</p><p>Last Day to Upset: October 29, 2021</p>
<p>File Number: 21 M 200</p><p>Sale Closed - Property Sold</p>
<p>Owner: Cancelled Owner</p><p>Parcel: 100003</p><p>Physical Address: vacant lot on Beam Rd, Gastonia, NC</p>
<p>Sale Date: September 2, 2026 at 10 am.</p><p>Starting Bid (Subject to Change): $4,000.00</p>
<p>File Number: 26 M 300</p><p>Settled- Sale Cancelled</p>
<p>Owner: Upcoming Owner</p><p>Parcel: 100004</p><p>Physical Address: 4 Live Ave., Gastonia, NC</p>
<p>Sale Date: {_FUTURE} at 10 am.</p><p>Starting Bid: $20,000.00</p><p>Last Day to Upset: {_UPSET}</p>
<p>File Number: 26 M 400</p><p>Bidding open</p>
</div></body></html>"""


def _gaston_rows():
    text = gaston._widget_text(_GASTON_PAGE)
    return [gaston._parse_block(b, "https://www.gastongov.com/671") for b in gaston._records(text)]


def test_gaston_ordinal_dates_parse():
    """Live 2026-09-21: 5 of 81 rows had sale_date None because 'August 4th, 2021' did not parse."""
    assert gaston._parse_date("August 4th, 2021 at 10 am.") == datetime(2021, 8, 4)
    assert gaston._parse_date("May 28th, 2019 at 10 am.") == datetime(2019, 5, 28)
    assert gaston._parse_date("March 16, 2026") == datetime(2026, 3, 16)
    assert all(li.sale_date is not None for li in _gaston_rows())


@pytest.mark.parametrize("text,cls", [
    ("Settled, Sale Cancelled", "cancelled"), ("Settled- Sale Cancelled", "cancelled"),
    ("Sale Cancelled", "cancelled"), ("Settled- Property Redeemed", "redeemed"),
    ("Sale Closed-Property Sold", "sold"), ("Sale Closed - Property Sold", "sold"),
    ("Sale Closed- Property Sold", "sold"), ("Bidding open", None), (None, None)])
def test_gaston_status_classes(text, cls):
    assert gaston._status_class(text) == cls


def test_gaston_closed_sales_are_terminal_and_never_pass_active_only():
    """Live: 0 of 81 passed _active_only. That was correct: every row is a closed sale."""
    rows = _gaston_rows()
    assert len(rows) == 4
    by = {li.parcel_id: li for li in rows}
    assert by["100001"].auction_status == "sold" and by["100003"].auction_status == "cancelled"
    for pid in ("100001", "100002", "100003"):
        assert M._active_only(by[pid], 120) is False


def test_gaston_upcoming_sale_lands_without_any_whitelist_entry():
    """A dated live sale passes scope + _active_only as-is; that is what will land in season."""
    live = {li.parcel_id: li for li in _gaston_rows()}["100004"]
    assert live.listing_type == ListingType.TAX_SALE
    assert M._in_scope(live) and M._active_only(live, 120)
    assert live.auction_status == "Bidding open"
    ub = live.raw["upset_bid"]
    assert ub["in_window"] is True and ub["source"] == "published" and ub["deadline_iso"]


def test_gaston_sold_price_recorded_only_for_sold_rows():
    by = {li.parcel_id: li for li in _gaston_rows()}
    assert by["100001"].raw["actual_sold_price"] == 96600.0
    assert "actual_sold_price" not in by["100003"].raw and "actual_sold_price" not in by["100004"].raw
    assert "upset_bid" not in by["100001"].raw          # the sale is closed; no open window


# =========================================================================== #
# sc_tax_delinquent
# =========================================================================== #

from foreclosure_scraper.scrapers.counties_sc import sc_tax_delinquent as sctd  # noqa: E402


def test_sc_sale_year_prefers_the_label_then_filename_then_stamp_then_text():
    assert sctd._sale_year("2025 delinquent tax sale results",
                           "https://h/TAX SALE RESULTS FOR WEBSITE.pdf?t=202511051005560") == 2025
    assert sctd._sale_year("", "https://h/document_center/Delinquent Tax/2017DelSaleListing.pdf?t=202011152031280") == 2017
    assert sctd._sale_year("", "https://h/2024 Tax Sale Results for Web.pdf?t=202410100938370") == 2024
    assert sctd._sale_year("", "https://h/TAX SALE RESULTS FOR WEBSITE.pdf?t=202511051005560") == 2025
    assert sctd._sale_year("", "https://h/x.pdf", "2023 TAX SALE OWNER (NOW OR FORMERLY)") == 2023
    assert sctd._sale_year("", "https://h/x.pdf", "no year here") is None


def test_sc_redemption_window_follows_the_pickens_tax_sale_convention():
    today = datetime(2026, 9, 21)
    assert sctd._redemption_deadline(2025) == datetime(2026, 12, 31)
    assert sctd._redemption_open(2025, today) is True       # sold Nov 2025, owner can still redeem
    assert sctd._redemption_open(2024, today) is False      # window closed Dec 2025
    assert sctd._redemption_open(2017, today) is False
    assert sctd._redemption_open(None, today) is None


_PICKENS = """<html><head><base href="root/"></head><body>
<a href="TAX SALE RESULTS FOR WEBSITE.pdf?t=202511051005560">2025 delinquent tax sale results</a>
<a href="2024 Tax Sale Results for Web.pdf?t=202410100938370">2024 delinquent tax sale results</a>
<a href="document_center/Departments/Delinquent Tax/2017DelSaleListing.pdf?t=202011152031280">2017 delinquent tax sale results</a>
<a href="Current Delinquent Tax List.pdf">Delinquent tax list 2026</a>
</body></html>"""


def _run_html(monkeypatch, fetched):
    async def fake_pdf(c, url, county, label=""):
        fetched.append(label or url)
        return []
    monkeypatch.setattr(sctd, "_scrape_pdf", fake_pdf)
    fake = FakeClient({"pickens": [Resp(200, _PICKENS, url="https://www.co.pickens.sc.us/departments/delinquent_tax/index.php")]})
    return asyncio.run(sctd._scrape_html(fake, "https://www.co.pickens.sc.us/departments/delinquent_tax/index.php", "Pickens")), fake


def test_sc_closed_results_pdfs_are_skipped_before_any_request(monkeypatch):
    """Live: 1,177 of 1,334 rows came from 2015-2019 sale lists and 115 more from 2021-2024
    results: sold years ago, redemption over. Only the 2025 results (and a current list) are fetched."""
    monkeypatch.delenv("SC_TAX_DELINQUENT_INCLUDE_HISTORICAL", raising=False)
    fetched: list[str] = []
    _run_html(monkeypatch, fetched)
    assert sorted(fetched) == ["2025 delinquent tax sale results", "delinquent tax list 2026"]   # labels are lower-cased


def test_sc_include_historical_env_restores_the_old_behaviour(monkeypatch):
    monkeypatch.setenv("SC_TAX_DELINQUENT_INCLUDE_HISTORICAL", "1")
    fetched: list[str] = []
    _run_html(monkeypatch, fetched)
    assert len(fetched) == 4


def test_sc_open_results_rows_carry_a_redemption_deadline_and_pass_the_gates():
    from foreclosure_scraper.models import Listing
    li = Listing(source="counties_sc.sc_tax_delinquent", source_url="u", listing_type=ListingType.TAX_SALE,
                 state="SC", county="Pickens", parcel_id="4185-00-38-3525", defendant="TEST OWNER",
                 raw={"sc_tax_delinquent": {}})
    sctd._mark_post_sale([li], 2025)
    assert li.redemption_deadline == datetime(2026, 12, 31)
    assert li.raw["sc_tax_delinquent"]["disposition"] == "post_sale_redemption_open"
    assert M._in_scope(li) and M._active_only(li, 120)      # slug is already in DATELESS_OK_SOURCES


def test_sc_slug_needs_no_main_py_change():
    assert "counties_sc.sc_tax_delinquent" in M.DATELESS_OK_SOURCES


# =========================================================================== #
# anderson_sheriff
# =========================================================================== #

from foreclosure_scraper.scrapers.counties_sc import anderson_sheriff as anders  # noqa: E402


def test_anderson_dead_host_fails_fast_and_is_classified_not_timed_out(monkeypatch):
    """Live: TCP connect to 192.155.253.203:443 times out / is refused. The old code retried for
    >120 s and was reported as TIMEOUT. Now: one attempt, classified from the exception."""
    fake = FakeClient(default=httpx.ConnectTimeout("connect timed out"))
    _patch_client(monkeypatch, anders, fake)
    called = []

    async def no_impersonate(*a, **k):
        called.append(1)
        return ""
    monkeypatch.setattr(anders, "get_text_impersonate", no_impersonate)
    s = anders.AndersonSheriff()
    assert asyncio.run(s.safe_run()) == []
    assert len(fake.calls) == 1 and not called
    assert s.last_outcome == "TIMEOUT" and "ConnectTimeout" in s.last_reason

    fake2 = FakeClient(default=httpx.ConnectError("refused"))
    _patch_client(monkeypatch, anders, fake2)
    s2 = anders.AndersonSheriff()
    asyncio.run(s2.safe_run())
    assert s2.last_outcome == "BLOCKED" and len(fake2.calls) == 1


def test_anderson_block_status_escalates_to_the_chrome_tier_once(monkeypatch):
    fake = FakeClient(default=Resp(403, "forbidden"))
    _patch_client(monkeypatch, anders, fake)
    seen = []

    async def imp(url, **k):
        seen.append(url)
        return ("<table><tr><th>Case</th><th>Defendant</th></tr>"
                "<tr><td>2024-CP-04-00123</td><td>Sample Ownername</td><td>12 Main St Anderson</td></tr></table>" + " " * 200)
    monkeypatch.setattr(anders, "get_text_impersonate", imp)
    out = asyncio.run(anders.AndersonSheriff().safe_run())
    assert seen == [anders.PAGE_URL] and len(out) == 1
    assert out[0].case_number == "2024-CP-04-00123" and out[0].county == "Anderson"


# =========================================================================== #
# daily_courier
# =========================================================================== #

from foreclosure_scraper.scrapers.newspapers import daily_courier as dc  # noqa: E402

_LISTING = (FIX / "daily_courier_listing_2026_09_21.html").read_text()
_AD = (FIX / "daily_courier_ad_foreclosure.html").read_text()
_CRED = (FIX / "daily_courier_ad_creditors.html").read_text()


@pytest.mark.parametrize("text,expect", [
    ("Special Proceedings No. 26SP000130-800 Trustee", "26SP000130"),
    ("File 25 SP 123 in", "25SP123"), ("24CVD1234", "24CVD1234"), ("26M000412", "26M000412")])
def test_daily_courier_file_numbers_including_the_six_digit_form(text, expect):
    """Live: '26SP000130-800' never matched the old 1-5 digit pattern, so case_number was always empty."""
    m = dc.FILE_RE.search(text)
    assert m and f"{m.group(1)}{m.group(2).upper()}{m.group(3)}" == expect


def test_daily_courier_listing_cards_dedupe_and_skip_non_foreclosures():
    cards = dc.parse_listing_cards(_LISTING)
    assert len(cards) == 4                                   # the duplicate href collapses
    fetchable = [u for u, t in cards if dc._worth_fetching(t)]
    assert len(fetchable) == 2 and all("north-carolina-rutherford-county/ad_" in u for u in fetchable)


def test_daily_courier_parses_the_current_notice_layout():
    li = dc.parse_notice(_AD, "https://www.thedigitalcourier.com/x/ad_1.html", now=datetime(2026, 9, 21))
    assert li.listing_type == ListingType.FORECLOSURE_SALE and (li.state, li.county) == ("NC", "Rutherford")
    assert li.case_number == "26SP000901" and li.raw["daily_courier"]["case_number_full"] == "26SP000901-800"
    assert (li.street_address, li.city, li.zip_code) == ("100 Example Road", "Rutherfordton", "28139")
    assert li.sale_date == datetime(2026, 9, 22) and li.sale_time == "1:00 p.m."
    assert li.trustee == "Pat E. Trustee" and li.plaintiff == "Example Credit Union"
    assert li.defendant == "Sample T. Ownerperson" and li.owner_name == li.defendant
    assert li.sale_location == "Rutherford County Courthouse"
    assert li.raw["daily_courier"]["deed_of_trust"] == {"book": "2001", "page": "1234", "dated": "January 5, 2022"}


def test_daily_courier_reads_the_full_notice_not_the_truncated_meta():
    """The meta description is ~270 chars with the words run together and stops before the address."""
    from selectolax.parser import HTMLParser
    meta = HTMLParser(_AD).css_first('meta[name="description"]').attributes["content"]
    assert "Address of Property" not in meta and "OFFORECLOSURE" in meta
    assert "Address of Property: 100 Example Road" in dc._notice_text(HTMLParser(_AD))


def test_daily_courier_notice_passes_the_orchestrator_gates_when_the_sale_is_ahead():
    li = dc.parse_notice(_AD, "u")
    li.sale_date = datetime.utcnow() + timedelta(days=1)
    assert M._in_scope(li) and M._active_only(li, 120)


def test_daily_courier_ignores_estate_notices_and_unidentifiable_ones():
    assert dc.parse_notice(_CRED, "u") is None
    bare = "<h1>NOTICE OF FORECLOSURE SALE</h1><div itemprop='description'>Foreclosure notice with no file number or street.</div>"
    assert dc.parse_notice(bare, "u") is None


def test_daily_courier_fetch_paces_retries_a_429_and_never_requests_estate_cards(monkeypatch):
    waits: list[float] = []

    async def rec(sec):
        waits.append(sec)
    monkeypatch.setattr(dc.asyncio, "sleep", rec)
    ad1, ad2 = "ad_11111111-1111-5111-a111-111111111111", "ad_44444444-4444-5444-a444-444444444444"
    fake = FakeClient({
        "=" + dc.LISTING_URLS[0]: [Resp(200, _LISTING)],
        ad1: [Resp(429, "Too Many Requests"), Resp(200, _AD)],
        ad2: [Resp(200, _AD.replace("26SP000901", "26SP000902").replace("100 Example Road", "7 Other Lane"))],
    })
    _patch_client(monkeypatch, dc, fake)
    s = dc.DailyCourierForeclosures()
    out = asyncio.run(s.safe_run())
    assert sorted(li.case_number for li in out) == ["26SP000901", "26SP000902"]
    assert not any("notice-to-creditors" in u or "public-hearing" in u for u in fake.calls)
    assert 20.0 in waits and dc.DELAY_S in waits             # a 429 back-off, and the per-request pacing
    assert len(s.partial) == 2                               # partial rows are kept for a soft timeout


def test_daily_courier_survives_a_persistent_429(monkeypatch):
    async def no_sleep(_s):
        return None
    monkeypatch.setattr(dc.asyncio, "sleep", no_sleep)
    fake = FakeClient({"=" + dc.LISTING_URLS[0]: [Resp(200, _LISTING)]}, default=Resp(429, "Too Many Requests"))
    _patch_client(monkeypatch, dc, fake)
    assert asyncio.run(dc.DailyCourierForeclosures().safe_run()) == []
    assert len([u for u in fake.calls if "/ad_" in u]) == 2 * dc.MAX_ATTEMPTS


# =========================================================================== #
# funeral_home_rss
# =========================================================================== #

from foreclosure_scraper.scrapers.public_notices import funeral_home_rss as fh  # noqa: E402

_FRAZER = """<?xml version="1.0"?><rss version="2.0"><channel><title>Recent Obituaries for Sample Home</title>
<item><title>Jane Q Sample | 09/15/2026</title><link>https://h/obituary/jane-sample?fh_id=1</link>
<description>Jane Q Sample, 87 years old, is survived by her son Tom Sample.</description></item>
<item><title>Bob Example | 09/14/2026</title><link>https://h/obituary/bob-example?fh_id=2</link><description>Bob Example, 71 years.</description></item>
</channel></rss>"""


def _funeral_rows(monkeypatch):
    monkeypatch.setattr(fh, "HOMES", {"sullivanking.com": ("Anderson", "SC", "frazer")})
    fake = FakeClient({"sullivanking": [Resp(200, _FRAZER)]})
    _patch_client(monkeypatch, fh, fake)
    return asyncio.run(fh.FuneralHomeRss().safe_run())


def test_funeral_rows_carry_county_state_and_the_owner_name(monkeypatch):
    """Live 2026-09-21: 50 of 50 rows had county+state (Buncombe 10, Cleveland 20, Anderson 20)."""
    rows = _funeral_rows(monkeypatch)
    assert len(rows) == 2
    for li in rows:
        assert (li.county, li.state) == ("Anderson", "SC")
        assert li.listing_type == ListingType.PROBATE_NOTICE
        assert li.owner_name == li.defendant and li.defendant in ("Jane Q Sample", "Bob Example")
        assert li.raw["dateless"] is True


def test_funeral_rows_are_scoped_in_but_die_in_active_only_without_the_whitelist_line(monkeypatch):
    """The reconciliation said 'no county'. The real cause is the missing DATELESS_OK_SOURCES entry.
    Written so it stays true after main.py gains the line: the slug is removed, then added, explicitly."""
    slug = "public_notices.funeral_home_rss"
    rows = _funeral_rows(monkeypatch)
    assert all(M._in_scope(li) for li in rows)
    monkeypatch.setattr(M, "DATELESS_OK_SOURCES", set(M.DATELESS_OK_SOURCES) - {slug})
    assert not any(M._active_only(li, 120) for li in rows)
    monkeypatch.setattr(M, "DATELESS_OK_SOURCES", set(M.DATELESS_OK_SOURCES) | {slug})
    assert all(M._active_only(li, 120) for li in rows)


def test_funeral_rows_are_name_resolver_targets(monkeypatch):
    from foreclosure_scraper.enrichment_resolve_name_to_property import _is_target
    assert all(_is_target(li) for li in _funeral_rows(monkeypatch))
