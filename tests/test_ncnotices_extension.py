"""Pin the ncnotices.com divorce + probate query extension.

Live HTTP fetch is integration-only (Scrapling/Playwright). These tests
exercise the pure parser + classifier branches via synthetic HTML.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.public_notices.ncpublicnotices import (
    QUERIES,
    _CATEGORY_RULES,
    _classify,
    _matches_category,
    _parse_results_html,
)
from foreclosure_scraper.models import ListingType


URL = "https://www.ncnotices.com/notice/123"


# ---- query coverage ----

def test_queries_include_foreclosure_divorce_probate():
    cats = {cat for _, cat in QUERIES}
    assert "foreclosure" in cats
    assert "divorce" in cats
    assert "probate" in cats


def test_at_least_one_query_per_category():
    """Each category must have ≥1 query — otherwise that lead-type
    will be silently absent from runs."""
    cats: dict[str, int] = {}
    for _, cat in QUERIES:
        cats[cat] = cats.get(cat, 0) + 1
    for required in ("foreclosure", "divorce", "probate"):
        assert cats.get(required, 0) >= 1


# ---- _classify ----

def test_classify_foreclosure_to_tax_sale():
    assert _classify("Tax foreclosure auction notice", "foreclosure") == ListingType.TAX_SALE


def test_classify_foreclosure_to_sheriff_sale():
    assert _classify("Sheriff sale of property", "foreclosure") == ListingType.SHERIFF_SALE


def test_classify_foreclosure_default():
    assert _classify("Notice of foreclosure sale", "foreclosure") == ListingType.FORECLOSURE_SALE


def test_classify_divorce():
    assert _classify("Notice of divorce summons", "divorce") == ListingType.DIVORCE_NOTICE


def test_classify_probate():
    assert _classify("Notice to Creditors estate of John Doe", "probate") == ListingType.PROBATE_NOTICE


def test_classify_unknown_category():
    assert _classify("random text", "garbage") == ListingType.UNKNOWN


# ---- _matches_category ----

def test_matches_foreclosure_keyword():
    assert _matches_category("substitute trustee sale notice", "foreclosure") is True


def test_matches_divorce_keyword():
    assert _matches_category("absolute divorce summons published", "divorce") is True


def test_matches_probate_keyword():
    assert _matches_category("notice to creditors of estate", "probate") is True


def test_no_match_for_unrelated_text():
    assert _matches_category("just an ordinary newspaper article", "foreclosure") is False


# ---- _CATEGORY_RULES ----

def test_foreclosure_requires_address():
    assert _CATEGORY_RULES["foreclosure"]["require_address"] is True


def test_probate_does_not_require_address():
    """Probate notices typically reference 'estate of X' + county only,
    no street address — relax the address requirement."""
    assert _CATEGORY_RULES["probate"]["require_address"] is False


def test_divorce_does_not_require_address():
    assert _CATEGORY_RULES["divorce"]["require_address"] is False


# ---- _parse_results_html ----

PROBATE_HTML = """
<html><body>
<div class="search-result">
  <p>NOTICE TO CREDITORS. Having qualified as Executor of the Estate of JOHN ALBERT SMITH, deceased, late of Buncombe County, North Carolina, this is to notify all persons having claims against said estate to present them on or before May 15, 2026.</p>
  <a href="/notice/12345">View notice</a>
</div>
</body></html>
"""


def test_parse_probate_notice_emits_listing():
    out = _parse_results_html(PROBATE_HTML, query="notice to creditors", category="probate")
    assert len(out) >= 1
    li = out[0]
    assert li.listing_type == ListingType.PROBATE_NOTICE
    assert li.county == "Buncombe"
    # Probate notices don't need an address — but should still capture
    # the named decedent in raw
    assert (li.raw or {}).get("ncnotices", {}).get("named_party") is not None


DIVORCE_HTML = """
<html><body>
<div class="search-result">
  <p>NOTICE OF SERVICE OF PROCESS BY PUBLICATION. To: JANE DOE, Defendant. Take notice that an absolute divorce action has been filed against you in the General Court of Justice, District Court Division, Mecklenburg County, North Carolina.</p>
  <a href="/notice/56789">View notice</a>
</div>
</body></html>
"""


def test_parse_divorce_notice_emits_listing():
    out = _parse_results_html(DIVORCE_HTML, query="absolute divorce service publication", category="divorce")
    assert len(out) >= 1
    li = out[0]
    assert li.listing_type == ListingType.DIVORCE_NOTICE
    assert li.county == "Mecklenburg"


FORECLOSURE_HTML = """
<html><body>
<div class="search-result">
  <p>SUBSTITUTE TRUSTEE FORECLOSURE SALE. Buncombe County. Property at 123 Main Street, Asheville, NC 28801. Sale date: March 15, 2026 at 10:00 AM. Opening bid: $87,500.</p>
  <a href="/notice/99999">View notice</a>
</div>
</body></html>
"""


def test_parse_foreclosure_still_works():
    """Backwards-compat: existing foreclosure category continues to work."""
    out = _parse_results_html(FORECLOSURE_HTML, query="substitute trustee", category="foreclosure")
    assert len(out) >= 1
    li = out[0]
    assert li.listing_type == ListingType.FORECLOSURE_SALE
    assert li.street_address is not None
    assert "Main" in li.street_address


def test_probate_named_party_also_lands_in_owner_name():
    """Regression found live 2026-10-01: this parser set `defendant` from the
    named party but never mirrored it onto `owner_name`, unlike every sibling
    scraper in this package. ~20 enrichers (enrichment_voter_phone.py --
    explicitly "the one free personal-phone source" -- enrichment_county_phone,
    enrichment_images, enrichment_owner_cluster, etc.) read li.owner_name with
    no defendant fallback of their own, so every row from this source was
    silently invisible to them despite carrying a real party name."""
    out = _parse_results_html(PROBATE_HTML, query="notice to creditors", category="probate")
    assert len(out) >= 1
    li = out[0]
    assert li.defendant is not None
    assert li.owner_name == li.defendant


def test_foreclosure_named_party_also_lands_in_owner_name():
    """Same regression, foreclosure branch (has its own `if require_address`
    code path that independently needed the same fix)."""
    out = _parse_results_html(FORECLOSURE_HTML, query="substitute trustee", category="foreclosure")
    assert len(out) >= 1
    li = out[0]
    if li.defendant is not None:
        assert li.owner_name == li.defendant


def test_parse_skips_ui_chrome():
    """Login / nav / chrome text must not become listings."""
    html = """
    <html><body>
    <div class="search-result"><p>Login to access your subscriber account</p></div>
    <div class="search-result"><p>Use the search above to filter notices</p></div>
    </body></html>
    """
    assert _parse_results_html(html, query="x", category="probate") == []


def test_parse_empty_returns_empty_list():
    assert _parse_results_html("", query="x", category="foreclosure") == []


# ---- HTML debug dump ----


def test_dump_html_writes_file_when_enabled(tmp_path, monkeypatch):
    """When the parser misses on substantial HTML, _dump_html_for_debug
    should save the body for offline inspection."""
    monkeypatch.setenv("NCNOTICES_DEBUG_DUMP", "1")
    monkeypatch.setenv("NCNOTICES_DEBUG_DUMP_DIR", str(tmp_path))
    # Re-import the module so the env-derived module-globals re-evaluate.
    import importlib
    from foreclosure_scraper.scrapers.public_notices import ncpublicnotices
    importlib.reload(ncpublicnotices)

    html = "<html>" + ("x" * 5000) + "</html>"
    ncpublicnotices._dump_html_for_debug(html, "notice to creditors", "probate", "https://example.com/x")
    files = list(tmp_path.glob("ncnotices_probate_*.html"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert "query='notice to creditors'" in body
    assert "category='probate'" in body
    assert "x" * 100 in body  # body content preserved


def test_dump_html_skips_short_bodies(tmp_path, monkeypatch):
    """Sub-1KB responses are noise (WAF blocks, 503s); don't dump."""
    monkeypatch.setenv("NCNOTICES_DEBUG_DUMP", "1")
    monkeypatch.setenv("NCNOTICES_DEBUG_DUMP_DIR", str(tmp_path))
    import importlib
    from foreclosure_scraper.scrapers.public_notices import ncpublicnotices
    importlib.reload(ncpublicnotices)

    ncpublicnotices._dump_html_for_debug("tiny", "x", "foreclosure", "https://example.com/y")
    assert list(tmp_path.glob("*.html")) == []


def test_dump_html_disabled_by_env(tmp_path, monkeypatch):
    """NCNOTICES_DEBUG_DUMP=0 disables the dump entirely."""
    monkeypatch.setenv("NCNOTICES_DEBUG_DUMP", "0")
    monkeypatch.setenv("NCNOTICES_DEBUG_DUMP_DIR", str(tmp_path))
    import importlib
    from foreclosure_scraper.scrapers.public_notices import ncpublicnotices
    importlib.reload(ncpublicnotices)

    html = "<html>" + ("x" * 5000) + "</html>"
    ncpublicnotices._dump_html_for_debug(html, "x", "foreclosure", "https://example.com/y")
    assert list(tmp_path.glob("*.html")) == []


def test_h4_linkless_cards_get_unique_urls():
    """H4 fix: cards without their own <a href> must get unique
    synthetic source_url so dedupe_key() doesn't collapse them all
    into a single 'url:BASE' bucket."""
    html = """
    <html><body>
    <div class="search-result"><p>Notice to Creditors. Estate of JOHN ALBERT SMITH, late of Buncombe County. Executor must receive claims by May 15.</p></div>
    <div class="search-result"><p>Notice to Creditors. Estate of MARY JONES, late of Rutherford County. Personal representative claims by June 1.</p></div>
    <div class="search-result"><p>Notice to Creditors. Estate of WILLIAM BROWN, late of Polk County. Administrator deadline July 1.</p></div>
    </body></html>
    """
    out = _parse_results_html(html, query="notice to creditors", category="probate")
    assert len(out) == 3
    urls = {li.source_url for li in out}
    # Three distinct synthetic URLs, NOT all the same BASE
    assert len(urls) == 3, f"All 3 cards should have unique URLs; got: {urls}"
    # All start with the BASE + fragment
    for u in urls:
        assert "ncnotices.com" in u
        assert "#notice-" in u


def test_h4_real_href_preserved():
    """When the card DOES have an <a href>, use it (not the synthetic
    fallback)."""
    html = """
    <html><body>
    <div class="search-result">
      <p>Notice to Creditors. Estate of JOHN SMITH, late of Buncombe County. Executor claims by May 15.</p>
      <a href="/notices/123">View notice</a>
    </div>
    </body></html>
    """
    out = _parse_results_html(html, query="notice to creditors", category="probate")
    assert len(out) == 1
    assert out[0].source_url == "https://www.ncnotices.com/notices/123"


def test_addr_re_skips_probate_estate_false_positives():
    """ADDR_RE must not match 'St' inside 'Estate'. Forensics 2026-06-15:
    ~11 probate notices landed with street_address like
    '2026 as Limited Personal Representative of the Est' because the
    street-type alternation lacked \\b word boundaries."""
    from foreclosure_scraper.scrapers.public_notices.ncpublicnotices import ADDR_RE
    probate_texts = [
        "Having qualified on the 27 day of May, 2026 as Limited Personal "
        "Representative of the Estate of Jerold Basel Wiltest",
        "Notice qualified 19 May, 2026 as Executor of the Estate",
        "qualified on the 26 day of May, 2026 as Administrator of the Estate "
        "of Jeffrey Brent Saunders",
    ]
    for text in probate_texts:
        m = ADDR_RE.search(text)
        assert m is None, (
            f"ADDR_RE incorrectly matched {m.group(1)!r} in probate text {text!r}"
        )


def test_addr_re_still_matches_real_addresses():
    """Word-boundary tightening must not break true-positive captures."""
    from foreclosure_scraper.scrapers.public_notices.ncpublicnotices import ADDR_RE
    cases = [
        ("Property located at 1014 Sunset Drive, Asheville NC", "1014 Sunset Drive"),
        ("Sale at 712 Hanover Drive Shelby NC 28150",            "712 Hanover Drive"),
        ("Inspect 4567 Westview Way for showing",                "4567 Westview Way"),
        ("foreclosure on 89 N Main St, Hendersonville",          "89 N Main St"),
    ]
    for text, expected in cases:
        m = ADDR_RE.search(text)
        assert m, f"ADDR_RE failed on {text!r}"
        assert m.group(1) == expected, f"got {m.group(1)!r} expected {expected!r}"


def test_parse_dedupes_by_named_party():
    """Two probate cards for the same estate (same name + county)
    should emit one listing."""
    html = """
    <html><body>
    <div class="search-result">
      <p>Notice to Creditors. Estate of JOHN ALBERT SMITH, late of Buncombe County. Executor must receive claims by May 15.</p>
    </div>
    <div class="search-result">
      <p>Notice to Creditors. Estate of JOHN ALBERT SMITH, late of Buncombe County. Republished notice with same content.</p>
    </div>
    </body></html>
    """
    out = _parse_results_html(html, query="notice to creditors", category="probate")
    assert len(out) == 1


# ---- detail-body enrichment now runs for every category, not just probate -
# FOUND 2026-10-13 (docs/source_completeness_audit_2026-10-13.md): this used
# to be _enrich_probate_details(), gated to category == "probate" even
# though the underlying fetch has nothing probate-specific about it. Live
# re-verification that day found it behaves identically for foreclosure rows
# (same Cloudflare-Turnstile gate, same two failure modes, same frequency) --
# so the probate-only gate was a bug, not a deliberate scope choice. Fixed by
# generalizing to _enrich_notice_details(), which these tests cover.

import asyncio
from datetime import UTC, datetime

from foreclosure_scraper.models import Listing, PropertyKind
import foreclosure_scraper.scrapers.public_notices.ncpublicnotices as _ncp

_DETAIL_SLUG = "public_notices.ncnotices"


def _detail_listing(listing_type, notice_id: str = "55555", **overrides) -> Listing:
    fields = dict(
        source=_DETAIL_SLUG,
        source_url=f"https://www.ncnotices.com/Details.aspx?ID={notice_id}",
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Buncombe",
        street_address=None,
        case_number=None,
        sale_date=None,
        plaintiff=None,
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        raw={},
    )
    fields.update(overrides)
    return Listing(**fields)


def test_enrich_notice_details_backfills_a_foreclosure_row(monkeypatch):
    """The exact gap the audit flagged: a foreclosure row whose address fell
    past the search-snippet truncation must get the detail-fetch shot at
    recovery, the same as a probate row always did."""
    li = _detail_listing(ListingType.FORECLOSURE_SALE)

    async def _fake_fetch(url):
        return ("UNDER AND BY VIRTUE of the power of sale the property at 42 "
                "Lakeview Drive will be sold at public auction on October 1, "
                "2026. Case 26SP000900-440.")

    monkeypatch.setattr(_ncp, "fetch_notice_detail", _fake_fetch)
    asyncio.run(_ncp._enrich_notice_details([li]))
    assert li.street_address == "42 Lakeview Drive"
    assert li.case_number == "26SP000900-440"
    assert li.sale_date is not None and li.sale_date.date().isoformat() == "2026-10-01"
    assert li.raw.get("ncnotices", {}).get("detail_body_fetched") is True


def test_enrich_notice_details_still_extracts_probate_pr_and_dod(monkeypatch):
    """Backward-compat: the probate PR/DOD extraction this function used to
    be named for must keep working after the generalization."""
    li = _detail_listing(ListingType.PROBATE_NOTICE)

    async def _fake_fetch(url):
        return ("Personal Representative Jane Q Smith 123 Main St Asheville "
                "NC 28801 Date of Death: January 5, 2026")

    monkeypatch.setattr(_ncp, "fetch_notice_detail", _fake_fetch)
    asyncio.run(_ncp._enrich_notice_details([li]))
    assert li.raw["probate"]["personal_representative"] == "Jane Q Smith"
    assert li.raw["probate"]["date_of_death"] == "January 5, 2026"


def test_enrich_notice_details_skips_non_detail_urls():
    """A linkless card's synthetic fragment URL (BASE#notice-...) is not a
    real Details.aspx link -- must be skipped, not fetched."""
    li = _detail_listing(
        ListingType.DIVORCE_NOTICE,
        source_url="https://www.ncnotices.com/#notice-divorce-abc123",
    )
    # No fetch_notice_detail monkeypatch -- if the URL-shape guard didn't
    # skip this row, the real (network-calling) function would run here.
    asyncio.run(_ncp._enrich_notice_details([li]))
    assert li.street_address is None


def test_enrich_notice_details_respects_the_cap(monkeypatch):
    monkeypatch.setattr(_ncp, "MAX_DETAIL_FETCH", 2)
    listings = [
        _detail_listing(ListingType.FORECLOSURE_SALE, notice_id=str(70000 + i))
        for i in range(5)
    ]
    calls: list[str] = []

    async def _fake_fetch(url):
        calls.append(url)
        return None

    monkeypatch.setattr(_ncp, "fetch_notice_detail", _fake_fetch)
    asyncio.run(_ncp._enrich_notice_details(listings))
    assert len(calls) == 2


def test_enrich_notice_details_does_not_overwrite_existing_fields(monkeypatch):
    li = _detail_listing(
        ListingType.FORECLOSURE_SALE,
        street_address="999 Already Known Dr",
        case_number="26SP000111-440",
    )

    async def _fake_fetch(url):
        return "42 Different Lane will be sold. Case 26SP999999-440."

    monkeypatch.setattr(_ncp, "fetch_notice_detail", _fake_fetch)
    asyncio.run(_ncp._enrich_notice_details([li]))
    assert li.street_address == "999 Already Known Dr"
    assert li.case_number == "26SP000111-440"


def test_enrich_notice_details_returns_none_adds_nothing(monkeypatch):
    """fetch_notice_detail() returning None (gated/failed) must leave the
    listing exactly as the snippet parse produced it."""
    li = _detail_listing(ListingType.FORECLOSURE_SALE)

    async def _fake_fetch(url):
        return None

    monkeypatch.setattr(_ncp, "fetch_notice_detail", _fake_fetch)
    asyncio.run(_ncp._enrich_notice_details([li]))
    assert li.street_address is None
    assert li.raw == {}
