"""Pin the 2026-10-13 fix in national/sheriff_sales.py (source-completeness
audit, Pattern D): the module docstring claimed a linked PDF was "noted in
raw but not OCR'd here", but `_fetch_county`'s link-collection loop actually
`continue`d on any non-HTML extension with ZERO trace anywhere -- the PDF
href was never written into any Listing's raw dict, so nothing downstream
(enrichment_doc_ocr.py) ever saw it.

Live-verified 2026-10-13 (see commit message for the full fetch log):
  - Cleveland County's real site-wide nav links a "Public Auction" PDF at
    .../wp-content/uploads/2025/05/No-Public-Auction-8.5-x-11-in.pdf --
    confirmed 200 application/pdf via a plain GET, no login/CAPTCHA.
  - Charleston County's real pending-sales page carries real per-case notice
    PDFs under .../departments/sheriff/pending-sales/ (e.g. SALE-24-7705.pdf)
    -- also confirmed 200 via a plain GET -- alongside ~11 UNRELATED
    department PDFs (org charts, mission statements, juvenile forms) whose
    full URL path also contains "sheriff" (department prefix), which is
    exactly why the relevance filter below must not key on "sheriff" (see
    the 2026-10-01 false-positive writeup this module's docstring already
    carries for the same hostname/path-substring trap).
  - Brunswick County's real page links an unrelated firearms-return form
    PDF, never a sale document (its real current posting links to a
    Craigslist listing instead).

These fixtures are synthetic (no network calls) but schema-accurate: the
real paths/filenames found live above are reused verbatim as the relevance
test's inputs, and the end-to-end fixtures mirror the real markup shapes
already pinned by this module's sibling test files (free-text <p> blocks
with the sale-context phrase + address/case in one element, a case that
produces exactly one real posting, and a case that produces two).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.national import sheriff_sales as ss


# --- _SALE_KEYWORDS relevance filter, exercised against REAL live paths ----

def test_real_cleveland_auction_pdf_path_is_sale_relevant():
    path = "/wp-content/uploads/2025/05/no-public-auction-8.5-x-11-in.pdf"
    assert any(kw in path for kw in ss._SALE_KEYWORDS)


def test_real_charleston_sale_pdf_paths_are_sale_relevant():
    for path in (
        "/departments/sheriff/pending-sales/sheriffs sale-post-2025-cp-10-02685.pdf",
        "/departments/sheriff/pending-sales/world-harvest-ministries-j-192_gis.pdf",
        "/departments/sheriff/pending-sales/sale-24-7705.pdf",
    ):
        assert any(kw in path for kw in ss._SALE_KEYWORDS), path


def test_real_charleston_unrelated_department_pdf_is_excluded_despite_sheriff_in_path():
    """The exact trap the 2026-10-01 false-positive fix already warns about:
    every PDF this department publishes sits under a path containing
    "sheriff" as a PREFIX, not just sale notices. "sheriff" must not be one
    of the relevance keywords or this (real, live, unrelated) PDF would be
    swept in too."""
    path = "/departments/sheriff/files/det-stats.pdf"
    assert "sheriff" not in ss._SALE_KEYWORDS
    assert not any(kw in path for kw in ss._SALE_KEYWORDS)


def test_real_brunswick_unrelated_firearms_pdf_is_excluded():
    path = "/site/wp-content/uploads/2023/03/questionnaire-for-return-of-firearms-1.pdf"
    assert not any(kw in path for kw in ss._SALE_KEYWORDS)


# --- end-to-end _fetch_county: doc_urls collected + stamped onto raw -------

def _patch_fetch(monkeypatch, html: str):
    async def _fake_robots_allows(_host, _path):
        return True

    async def _fake_fetch_html(_url, timeout=30.0):  # noqa: ARG001
        return html

    monkeypatch.setattr(ss, "_robots_allows", _fake_robots_allows)
    monkeypatch.setattr(ss, "_fetch_html", _fake_fetch_html)


# Charleston-shaped: one real posting (sale-context + address + case number
# all in the SAME <p>, matching _parse_charleston's fallback requirement)
# plus a real-shaped per-case sale PDF link and a real-shaped unrelated
# department PDF link elsewhere on the page.
_ONE_POSTING_WITH_PDF_HTML = """
<html><body>
<div class="content">
  <p>NOTICE OF SHERIFF'S SALE: the property located at 450 Harbor Dr,
  Charleston, SC, case number 2025-CP-10-02685, will be sold at public
  auction on the courthouse steps.</p>
</div>
<div class="sidebar">
  <a href="https://www.charlestoncounty.gov/departments/sheriff/pending-sales/SALE-2025-CP-10-02685.pdf">View PDF</a>
  <a href="https://www.charlestoncounty.gov/departments/sheriff/files/det-stats.pdf">Detention Stats</a>
</div>
</body></html>
"""


def test_single_real_posting_gets_its_pdf_stamped_into_raw(monkeypatch):
    _patch_fetch(monkeypatch, _ONE_POSTING_WITH_PDF_HTML)
    out = asyncio.run(ss._fetch_county(
        "SC", "Charleston", "Charleston County Sheriff",
        "https://www.charlestoncounty.org",
        "/departments/sheriff/pending-sales.php",
    ))
    assert len(out) == 1
    li = out[0]
    assert li.raw["document_url"] == (
        "https://www.charlestoncounty.gov/departments/sheriff/pending-sales/"
        "SALE-2025-CP-10-02685.pdf"
    )
    assert li.raw["documents"] == [
        "https://www.charlestoncounty.gov/departments/sheriff/pending-sales/"
        "SALE-2025-CP-10-02685.pdf"
    ]
    # the unrelated department PDF (det-stats.pdf) must never be swept in.
    assert "det-stats" not in " ".join(li.raw["documents"])


# Brunswick-shaped: two genuinely distinct postings (each self-contained in
# its own <p>, so the per-element fallback -- not the single-posting join --
# picks both up) plus one sale-relevant PDF link on the page.
_TWO_POSTINGS_WITH_PDF_HTML = """
<html><body>
<div class="content">
  <p>NOTICE OF SHERIFF'S SALE: property at 100 First St, Shelby, NC, case
  number 24-CVD-1111, sold at public auction.</p>
  <p>NOTICE OF SHERIFF'S SALE: property at 200 Second St, Shelby, NC, case
  number 24-CVD-2222, sold at public auction.</p>
</div>
<div class="sidebar">
  <a href="https://example.com/sales/SALE-24-CVD-1111.pdf">View PDF</a>
</div>
</body></html>
"""


def test_two_distinct_postings_on_one_page_do_not_get_a_guessed_pdf(monkeypatch):
    """Must not repeat the misattribution class of bug the join-container and
    dedup fixes above guard against: with 2+ real postings off one page,
    there is no reliable way to tell which PDF belongs to which row, so
    neither listing gets the PDF guessed onto it."""
    _patch_fetch(monkeypatch, _TWO_POSTINGS_WITH_PDF_HTML)
    out = asyncio.run(ss._fetch_county(
        "NC", "Brunswick", "Brunswick County Sheriff",
        "https://www.brunswicksheriff.com",
        "/resources/auctions",
    ))
    assert len(out) == 2
    for li in out:
        assert "documents" not in li.raw
        assert "document_url" not in li.raw


# Cleveland-shaped: no real posting at all (the nav "Public Auction" link
# text is short boilerplate, same as the real live page) -- a sale-relevant
# PDF is still discoverable on the page, but with zero real listings there
# is nothing to attach it to.
_NO_POSTING_WITH_PDF_HTML = """
<html><body>
<div class="content">
  <p>Welcome to the Cleveland County Sheriff's Office.</p>
</div>
<nav>
  <a href="https://www.sheriffclevelandcounty.com/wp-content/uploads/2025/05/No-Public-Auction-8.5-x-11-in.pdf">Public Auction</a>
</nav>
</body></html>
"""


def test_zero_real_postings_means_nothing_to_stamp(monkeypatch):
    _patch_fetch(monkeypatch, _NO_POSTING_WITH_PDF_HTML)
    out = asyncio.run(ss._fetch_county(
        "NC", "Cleveland", "Cleveland County Sheriff",
        "https://www.sheriffclevelandcounty.com",
        "/",
    ))
    assert out == []
