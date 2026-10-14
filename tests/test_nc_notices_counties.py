"""ncnotices.com county-scoped parser (NC Press Association grid -> typed leads).

The fixture is REAL grid HTML captured live 2026-07-31 with the 11 footprint
counties ticked, trimmed to one row per parse branch plus one out-of-footprint
row. Every assertion below is about a row that actually published.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import types
from datetime import UTC, datetime

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.public_notices import _press_assoc as pa
from foreclosure_scraper.scrapers.public_notices import nc_notices_counties as M

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "ncnotices_county_grid.html"
_SLUG = "public_notices.nc_notices_counties"

# The flat single-<tr>-per-result shape the helper must also accept.
_FLAT = """
<table id="GridView1">
<tr><td>The Herald Friday, July 31, 2026 City: Marion County: McDowell</td>
<td>NOTICE OF FORECLOSURE SALE 26SP000012-560 Under and by virtue of the power of sale
contained in a Deed of Trust executed by JOHN Q PUBLIC, dated May 1, 2019 and recorded in
Book 1234 at Page 56 in the McDowell County Registry. The property at 118 Sycamore Lane
(PIN 1697-32-4455) will be sold at public auction on September 9, 2026.</td>
<td><input onclick="javascript:location.href='Details.aspx?SID=abc&amp;ID=777001';return false;"/></td>
</tr></table>
"""


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return pa.parse_grid(_FIXTURE.read_text())


@pytest.fixture(scope="module")
def listings(rows) -> list:
    return [li for li in (M._to_listing(r, _SLUG) for r in rows) if li]


# ---------------------------------------------------------------- helper ---

def test_parse_grid_reads_every_row(rows):
    assert len(rows) == 7
    first = rows[0]
    assert first["notice_id"].isdigit()
    assert first["publication"] == "Beacon Tribune"
    assert first["date_text"] == "Thursday, July 30, 2026"
    assert first["published_at"].date().isoformat() == "2026-07-30"
    assert "click 'view' to open the full text" not in first["text"]


def test_parse_grid_accepts_the_flat_row_shape():
    rows = pa.parse_grid(_FLAT)
    assert len(rows) == 1
    assert rows[0]["notice_id"] == "777001"
    assert rows[0]["county_meta"] == "McDowell"
    assert rows[0]["city_meta"] == "Marion"


def test_pager_labels():
    html = _FIXTURE.read_text()
    assert pa.total_pages(html) == 5
    assert pa.current_page(html) == 1
    assert pa.total_pages("<div>no pager</div>") is None


def test_parse_date_handles_platform_formats():
    assert pa.parse_date("Thursday, July 30, 2026").month == 7
    assert pa.parse_date("7/30/2026").day == 30
    assert pa.parse_date("nonsense") is None


# -------------------------------------------------------- county routing ---

def test_subject_county_beats_publication_county(listings):
    """A Buncombe paper carries Henderson County foreclosures — the notice body
    wins over the grid's County: field, which is the PUBLISHER's county."""
    harvie = next(li for li in listings if li.defendant == "KAREN HARVIE")
    assert harvie.county == "Henderson"
    source_row = next(r for r in pa.parse_grid(_FIXTURE.read_text())
                      if "KAREN HARVIE" in r["text"])
    assert source_row["county_meta"] == "Buncombe"


def test_publication_county_is_the_fallback(listings):
    """The NCGS 105-369 ad names a municipality, not a county — fall back to
    the publishing paper's county (Flat Rock is in Henderson)."""
    ad = next(li for li in listings if li.listing_type is ListingType.TAX_LIEN)
    assert ad.county == "Henderson"


def test_out_of_footprint_row_is_dropped(rows):
    columbus = next(r for r in rows if r["county_meta"] == "Columbus")
    assert M._to_listing(columbus, _SLUG) is None


def test_every_listing_is_in_footprint_and_nc(listings):
    assert listings
    assert {li.county for li in listings} <= set(M.FOOTPRINT)
    assert {li.state for li in listings} == {"NC"}


def test_haywood_is_in_footprint_and_classifies_real_rows():
    """Added 2026-09-30 (docs/HANDOFF.md item 16 / gap_ledger.md). Live httpx
    probe (no Playwright, no board) confirmed the mechanism against a control
    (Buncombe) then against Haywood: ticking the real Haywood county checkbox
    and running this scraper's own "foreclosure" and "notice to creditors"
    queries returned real, dated, case-numbered rows (publication "Mountaineer,
    The" / city "Waynesville" — Haywood's county seat). Both fixtures below are
    the real preview text captured live 2026-09-30, notice_id 982438 and 982818.

    The NCGS 105-369 tax-lien EXACT query specifically returned 0 for Haywood
    over the full 365-day lookback (confirmed against the live "No public
    notices found" marker, not a parsing miss) -- so this addition closes real
    coverage for FORECLOSURE_SALE/PROBATE_NOTICE, not the tax_delinquent gap
    itself, which stays open per the gap ledger.

    UPDATE 2026-10-04 (HERMES extraction-completeness audit, public_notices
    batch): the "real coverage" claim above was only half true. This test
    never checked main._in_scope() -- and Haywood is explicitly deny-listed
    (config.SCOPE_DENY_COUNTIES) AND not in the 18-county flip footprint, so
    the FORECLOSURE_SALE row below was being silently dropped at the board
    gate on every real run since 2026-09-30, the exact same bug class the
    newspapers.* batch found the same day. Fixed in nc_notices_counties.py by
    remapping FORECLOSURE_SALE -> LIS_PENDENS for any county outside the true
    18-county footprint (Haywood + the 8 coastal FOOTPRINT entries); the 11
    real footprint counties are unaffected. This test now asserts the
    corrected type AND that it actually reaches the board.
    """
    assert "Haywood" in M.FOOTPRINT

    foreclosure_row = {
        "notice_id": "982438",
        "publication": "Mountaineer, The",
        "date_text": "Wednesday, September 16, 2026",
        "published_at": None,
        "county_meta": "Haywood",
        "city_meta": "Waynesville",
        "text": ("26SP000070-430 NOTICE OF SUBSTITUTE TRUSTEE'S FORECLOSURE SALE OF "
                 "REAL PROPERTY UNDER AND BY VIRTUE of the power and authority "
                 "contained in that certain Deed of Trust executed and delivered by "
                 "William O'Brien and Betty Sue McCoy O'Brien dated March 12, 2009 "
                 "and recorded on April 3, 2009"),
    }
    li = M._to_listing(foreclosure_row, _SLUG)
    assert li is not None
    assert li.county == "Haywood"
    assert li.state == "NC"
    # Haywood is deny-listed and outside the 18-county flip footprint, so the
    # raw FORECLOSURE_SALE classification is remapped to LIS_PENDENS -- see
    # the UPDATE note above. This is what actually reaches the board; a bare
    # FORECLOSURE_SALE here would be silently dropped by main._in_scope().
    assert li.listing_type is ListingType.LIS_PENDENS
    assert li.foreclosure_process == "power_of_sale"
    assert li.case_number == "26SP000070-430"
    assert li.defendant == "William O'Brien and Betty Sue McCoy O'Brien"

    from foreclosure_scraper import main as _main
    assert _main._in_scope(li) is True

    creditors_row = {
        "notice_id": "982818",
        "publication": "Mountaineer, The",
        "date_text": "Wednesday, September 16, 2026",
        "published_at": None,
        "county_meta": "Haywood",
        "city_meta": "Waynesville",
        "text": ("NOTICE TO CREDITORS Having qualified as Administrator, Patton "
                 "Medford Philtest of the Estate of Tamsin Denise Philtest, late of "
                 "Haywood County, State of North Carolina, this is to notify all "
                 "persons, firms and corporations having claims against the estate "
                 "to exhibit them to the undersigned in c"),
    }
    li2 = M._to_listing(creditors_row, _SLUG)
    assert li2 is not None
    assert li2.county == "Haywood"
    assert li2.listing_type is ListingType.PROBATE_NOTICE
    assert li2.defendant == "Tamsin Denise Philtest"


# ------------------------------------------------------- classification ----

def test_classification_covers_all_three_categories(listings):
    by_type = {li.listing_type for li in listings}
    assert ListingType.FORECLOSURE_SALE in by_type   # substitute trustee sale
    assert ListingType.TAX_SALE in by_type           # county-plaintiff tax sale
    assert ListingType.TAX_LIEN in by_type           # NCGS 105-369 advertisement
    assert ListingType.PROBATE_NOTICE in by_type     # NCGS 28A-14-1 creditors
    assert ListingType.LIS_PENDENS in by_type        # action filed, no sale yet


def test_county_as_plaintiff_is_tagged_as_a_tax_action(listings):
    """'COUNTY OF BUNCOMBE, a Body Politic and Corporate, Plaintiff' is the NC
    in-rem tax-foreclosure caption — it must not fall through to a plain
    power-of-sale foreclosure."""
    tax = [li for li in listings if li.foreclosure_process == "tax"]
    assert len(tax) == 3
    assert all(li.listing_type in (ListingType.TAX_SALE, ListingType.TAX_LIEN,
                                   ListingType.LIS_PENDENS) for li in tax)
    sale = next(li for li in listings if li.listing_type is ListingType.TAX_SALE)
    assert sale.plaintiff and "Buncombe" in sale.plaintiff
    assert sale.defendant == "Roger Lunsford"


def test_plaintiff_does_not_swallow_the_caption_boilerplate():
    """Real Rutherford text. A permissive "anything before Plaintiff" pattern
    returned the whole caption; only the party may come back."""
    text = ("IN THE GENERAL COURT OF JUSTICE SUPERIOR COURT DIVISION BEFORE THE CLERK "
            "26 M 110 NOTICE OF DOCKETING TAX FORECLOSURE JUDGMENT STATE OF NORTH "
            "CAROLINA COUNTY OF RUTHERFORD RUTHERFORD COUNTY, Plaintiff, Vs. Larry "
            "Douglas, Jerome Douglas, Coretta Patricia Robinson Defendant(s) Pursuant to")
    m = M._PLAINTIFF_RE.search(text)
    assert m and M._tidy_name(m.group(1)) == "RUTHERFORD COUNTY"
    # Joint government plaintiffs stay intact.
    joint = ("FILE NO. 25 CVD 861 CITY OF MARION and MCDOWELL COUNTY, Plaintiffs, "
             "vs. JOHN GREGORY CLAYTON, ET AL., Defendants")
    m = M._PLAINTIFF_RE.search(joint)
    assert m and M._tidy_name(m.group(1)) == "CITY OF MARION and MCDOWELL COUNTY"


def test_power_of_sale_process_on_deed_of_trust_foreclosures(listings):
    saxe = next(li for li in listings if li.defendant and "Saxe" in li.defendant)
    assert saxe.listing_type is ListingType.FORECLOSURE_SALE
    assert saxe.foreclosure_process == "power_of_sale"


def test_non_lead_notices_are_dropped():
    for noise in (
        "NOTICE OF PUBLIC HEARING Notice is hereby given that the Buncombe County "
        "Board of Adjustment will hold a regular meeting on Wednesday.",
        "T & T MINI STORAGE will offer for sale the following units in Burke County.",
    ):
        assert M._classify(noise) is None


# ------------------------------------------------------------- fields ------

def test_estate_notice_carries_the_decedent_and_probate_signal(listings):
    estate = next(li for li in listings if li.listing_type is ListingType.PROBATE_NOTICE)
    assert estate.defendant == "Wendy Faye Wiltest"
    assert estate.owner_name == "Wendy Faye Wiltest"
    assert estate.raw["probate"]["decedent"] == "Wendy Faye Wiltest"
    assert estate.raw["relationship_signal"]["kind"] == "probate"
    assert estate.street_address is None   # an estate notice names no property
    assert estate.sale_date is None


def test_case_numbers_are_captured(listings):
    cases = {li.case_number for li in listings if li.case_number}
    assert {"26SP000066-440", "26CV003253-100", "22CVD003028-100",
            "26SP000128-440"} <= cases


def test_deed_of_trust_book_page_is_captured_for_rod_lookup(listings):
    harvie = next(li for li in listings if li.defendant == "KAREN HARVIE")
    assert harvie.raw["public_notice"]["deed_of_trust"] == {"book": "2910", "page": "550"}


def test_source_url_points_at_the_notice(listings):
    for li in listings:
        assert li.source_url.startswith("https://www.ncnotices.com/Details.aspx?ID=")
        assert li.source_url.rsplit("=", 1)[1].isdigit()


def test_raw_flags_the_preview_as_truncated(listings):
    """The full body is reCAPTCHA-gated, so downstream must know these fields
    come from a ~300-char preview and are not authoritative-complete."""
    for li in listings:
        assert li.raw["public_notice"]["preview_truncated"] is True
        assert li.raw["public_notice"]["site"] == "ncnotices.com"


def test_publication_date_is_kept_both_raw_and_machine_readable(listings):
    harvie = next(li for li in listings if li.defendant == "KAREN HARVIE")
    pn = harvie.raw["public_notice"]
    assert pn["publication"] == "Beacon Tribune"
    assert pn["publication_date"] == "Thursday, July 30, 2026"
    assert pn["published_at"].startswith("2026-07-30")
    # The publisher's county is retained even when the subject county differs.
    assert pn["publication_county"] == "Buncombe" and harvie.county == "Henderson"


def test_address_parcel_and_sale_date_parse_when_present():
    """Rarely survives truncation live, but must work when the text has them."""
    row = pa.parse_grid(_FLAT)[0]
    li = M._to_listing(row, _SLUG)
    assert li is not None
    assert li.county == "McDowell"
    assert li.street_address == "118 Sycamore Lane"
    assert li.parcel_id == "1697-32-4455"
    assert li.sale_date is not None and li.sale_date.date().isoformat() == "2026-09-09"
    assert li.defendant == "JOHN Q PUBLIC"


# --------------------------------------------------------------- fetch -----

async def _no_op_backfill(listings):
    """Stand-in for _enrich_missing_addresses in tests that exercise the
    full fetch() pipeline with a faked render -- the real backfill makes a
    live network/browser call per row, which has no place in a unit test."""
    return None


def test_fetch_dedupes_by_notice_id_across_pages(monkeypatch):
    """The same notice appears under more than one keyword; a lead must be
    emitted once."""
    html = _FIXTURE.read_text()

    async def _fake_render():
        return [html, html, html]

    monkeypatch.setattr(M, "_render_queries", _fake_render)
    monkeypatch.setattr(M, "_enrich_missing_addresses", _no_op_backfill)
    out = asyncio.run(M.NCNoticesCounties().fetch())
    assert len(out) == 6   # 7 fixture rows, 1 out-of-footprint
    assert len({li.source_url for li in out}) == 6


def test_fetch_survives_a_render_that_returns_nothing(monkeypatch):
    async def _fake_render():
        return []

    monkeypatch.setattr(M, "_render_queries", _fake_render)
    assert list(asyncio.run(M.NCNoticesCounties().fetch())) == []


def test_scraper_is_registered_and_shaped_like_its_siblings():
    from foreclosure_scraper.scrapers._registry import discover

    cls = next(c for c in discover() if c.slug == _SLUG)
    assert cls.category == "public_notices"
    assert cls.timeout_s >= 600      # 11 county postbacks + 4 paged queries
    assert cls.expected_min_count == 0


# ------------------------------------------- detail fetch (shared helper) --
# Live-verified 2026-10-13 against ncnotices.com (docs/source_completeness_
# audit_2026-10-13.md): the gate is Cloudflare Turnstile (NOT Google
# reCAPTCHA -- g-recaptcha never appears), and even a resolved Turnstile
# token doesn't guarantee the server's postback actually populates the
# notice body -- a generic "Sorry, there was a problem loading..." error
# with an empty content span is a real, observed outcome, indistinguishable
# in practice from the explicit challenge. fetch_notice_detail() treats both
# the same way: return None, no retry, no bypass. These tests fake the
# Playwright page exactly like tests/test_sos_agent_handoff.py already does
# for a different scrapling-driven scraper in this codebase.

class _FakeDetailPage:
    """Stands in for the page passed to fetch_notice_detail()'s page_action.

    `token_ready` controls how many evaluate() polls report the Turnstile
    response field still pending (0 = already resolved before the first
    poll, matching a silent auto-verify)."""

    def __init__(self, final_html: str, token_ready: int = 0):
        self.final_html = final_html
        self.token_ready = token_ready
        self._polls = 0
        self.clicked: list[str] = []

    async def wait_for_load_state(self, *a, **k):
        return None

    async def wait_for_timeout(self, *a, **k):
        return None

    async def evaluate(self, js):
        self._polls += 1
        return self._polls <= self.token_ready  # True == still pending

    async def click(self, sel, timeout=None):
        self.clicked.append(sel)

    async def content(self):
        return self.final_html


def _install_fake_scrapling(monkeypatch, page):
    async def async_fetch(url, page_action=None, **kw):
        if page_action:
            await page_action(page)
        return None

    mod = types.ModuleType("scrapling.fetchers")
    mod.StealthyFetcher = types.SimpleNamespace(async_fetch=async_fetch)
    monkeypatch.setitem(sys.modules, "scrapling", types.ModuleType("scrapling"))
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", mod)


def test_fetch_notice_detail_returns_none_when_challenge_still_visible(monkeypatch):
    html = ('<div class="cf-turnstile" id="recaptcha"></div>'
            '<span class="pnlError">You must complete the challenge in order '
            'to continue.</span>')
    _install_fake_scrapling(monkeypatch, _FakeDetailPage(html))
    text = asyncio.run(
        M.fetch_notice_detail("https://www.ncnotices.com/Details.aspx?ID=1"))
    assert text is None


def test_fetch_notice_detail_returns_none_on_generic_postback_error(monkeypatch):
    """Live-verified 2026-10-13: a resolved Turnstile token does not
    guarantee real content -- the server can still render this generic
    error with an empty lblContentText. Same fail-safe treatment as an
    explicit gate."""
    html = ('<span id="ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_'
            'lblMessage" class="pnlError">Sorry, there was a problem loading '
            'the search results page.</span>'
            '<span id="ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_'
            'lblContentText"></span>')
    _install_fake_scrapling(monkeypatch, _FakeDetailPage(html, token_ready=2))
    text = asyncio.run(
        M.fetch_notice_detail("https://www.ncnotices.com/Details.aspx?ID=2"))
    assert text is None


def test_fetch_notice_detail_returns_real_text_when_postback_succeeds(monkeypatch):
    html = ('<div id="right_content"><span id="lblContentText">123 Sycamore '
            'Lane, parcel 1697-32-4455, sale on September 9, 2026'
            '</span></div>')
    page = _FakeDetailPage(html, token_ready=1)
    _install_fake_scrapling(monkeypatch, page)
    text = asyncio.run(
        M.fetch_notice_detail("https://www.ncnotices.com/Details.aspx?ID=3"))
    assert text is not None
    assert "123 Sycamore Lane" in text
    assert page.clicked   # the click actually happened before content() was read


def test_fetch_notice_detail_returns_none_when_fetch_raises(monkeypatch):
    async def _boom(url, page_action=None, **kw):
        raise RuntimeError("Timeout 60000ms exceeded")

    mod = types.ModuleType("scrapling.fetchers")
    mod.StealthyFetcher = types.SimpleNamespace(async_fetch=_boom)
    monkeypatch.setitem(sys.modules, "scrapling", types.ModuleType("scrapling"))
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", mod)
    text = asyncio.run(
        M.fetch_notice_detail("https://www.ncnotices.com/Details.aspx?ID=4"))
    assert text is None


# ------------------------------------------- bounded address backfill ------

def _foreclosure_listing(notice_id: str = "900001", **overrides) -> Listing:
    fields = dict(
        source=_SLUG,
        source_url=M._DETAIL_URL.format(notice_id),
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Buncombe",
        street_address=None,
        case_number=None,
        sale_date=None,
        parcel_id=None,
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        raw={"public_notice": {"site": "ncnotices.com"}},
    )
    fields.update(overrides)
    return Listing(**fields)


def test_enrich_missing_addresses_backfills_from_detail_text(monkeypatch):
    li = _foreclosure_listing()

    async def _fake_fetch(url):
        return ("UNDER AND BY VIRTUE of the power of sale the property at 118 "
                "Sycamore Lane (PIN 1697-32-4455) will be sold at public "
                "auction on September 9, 2026. Case 26SP000128-440.")

    monkeypatch.setattr(M, "fetch_notice_detail", _fake_fetch)
    asyncio.run(M._enrich_missing_addresses([li]))
    assert li.street_address == "118 Sycamore Lane"
    assert li.parcel_id == "1697-32-4455"
    assert li.sale_date is not None and li.sale_date.date().isoformat() == "2026-09-09"
    assert li.case_number == "26SP000128-440"
    assert li.raw["public_notice"]["detail_body_fetched"] is True


def test_enrich_missing_addresses_skips_rows_that_already_have_an_address(monkeypatch):
    li = _foreclosure_listing(street_address="999 Already Known Dr")
    calls: list[str] = []

    async def _fake_fetch(url):
        calls.append(url)
        return "should never be reached"

    monkeypatch.setattr(M, "fetch_notice_detail", _fake_fetch)
    asyncio.run(M._enrich_missing_addresses([li]))
    assert calls == []
    assert li.street_address == "999 Already Known Dr"


def test_enrich_missing_addresses_skips_probate(monkeypatch):
    """An estate notice legitimately names no property -- don't spend a
    bounded request looking for one (see the module docstring)."""
    li = Listing(
        source=_SLUG,
        source_url=M._DETAIL_URL.format("900002"),
        listing_type=ListingType.PROBATE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Buncombe",
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        raw={},
    )
    calls: list[str] = []

    async def _fake_fetch(url):
        calls.append(url)
        return "text"

    monkeypatch.setattr(M, "fetch_notice_detail", _fake_fetch)
    asyncio.run(M._enrich_missing_addresses([li]))
    assert calls == []


def test_enrich_missing_addresses_respects_the_cap(monkeypatch):
    monkeypatch.setattr(M, "_MAX_DETAIL_FETCH", 2)
    listings = [_foreclosure_listing(notice_id=str(900100 + i)) for i in range(5)]
    calls: list[str] = []

    async def _fake_fetch(url):
        calls.append(url)
        return None

    monkeypatch.setattr(M, "fetch_notice_detail", _fake_fetch)
    asyncio.run(M._enrich_missing_addresses(listings))
    assert len(calls) == 2


def test_enrich_missing_addresses_propagates_an_unexpected_failure(monkeypatch):
    """fetch_notice_detail() is designed to never raise (it catches its own
    failures and returns None) -- but if something unexpected still does
    raise here, _enrich_missing_addresses does NOT swallow it itself. That
    safety net lives one level up, in fetch()'s own try/except (see
    test_fetch_survives_a_broken_backfill below) -- documented here so the
    division of responsibility is explicit rather than assumed."""
    li = _foreclosure_listing()

    async def _raises(url):
        raise RuntimeError("boom")

    monkeypatch.setattr(M, "fetch_notice_detail", _raises)
    with pytest.raises(RuntimeError):
        asyncio.run(M._enrich_missing_addresses([li]))


def test_fetch_survives_a_broken_backfill(monkeypatch):
    html = _FIXTURE.read_text()

    async def _fake_render():
        return [html]

    async def _broken_backfill(listings):
        raise RuntimeError("boom")

    monkeypatch.setattr(M, "_render_queries", _fake_render)
    monkeypatch.setattr(M, "_enrich_missing_addresses", _broken_backfill)
    out = asyncio.run(M.NCNoticesCounties().fetch())
    assert len(out) == 6   # the run still completes and returns its leads


def test_fetch_wires_in_the_detail_backfill_when_enabled(monkeypatch):
    html = _FIXTURE.read_text()

    async def _fake_render():
        return [html]

    calls: list[int] = []

    async def _fake_backfill(listings):
        calls.append(len(listings))

    monkeypatch.setattr(M, "_render_queries", _fake_render)
    monkeypatch.setattr(M, "_enrich_missing_addresses", _fake_backfill)
    monkeypatch.setattr(M, "_DETAIL_FETCH_ENABLED", True)
    out = asyncio.run(M.NCNoticesCounties().fetch())
    assert calls == [len(out)]


def test_fetch_skips_the_detail_backfill_when_disabled(monkeypatch):
    html = _FIXTURE.read_text()

    async def _fake_render():
        return [html]

    calls: list[int] = []

    async def _fake_backfill(listings):
        calls.append(len(listings))

    monkeypatch.setattr(M, "_render_queries", _fake_render)
    monkeypatch.setattr(M, "_enrich_missing_addresses", _fake_backfill)
    monkeypatch.setattr(M, "_DETAIL_FETCH_ENABLED", False)
    asyncio.run(M.NCNoticesCounties().fetch())
    assert calls == []
