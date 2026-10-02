"""nc_bankruptcy_sales.py was rewritten 2026-10-01: the old version fell back
to scanning every <li> on the page for bankruptcy keywords ("case",
"trustee", ...) when its <table>-row scan found nothing (neither district
site has ever used a <table>), and that fallback matched the SITE
NAVIGATION menu, fabricating fake BANKRUPTCY listings with no real
address/debtor/date. Verify the rewrite parses real sale links, leaves the
genuine "no public sales" empty state at zero, and does NOT fabricate rows
from nav chrome."""
from foreclosure_scraper.scrapers.counties_nc.nc_bankruptcy_sales import parse_district_html

# Trimmed live fragment (captured 2026-10-01) — the real Eastern District
# content: a Drupal node body with one <p><a href=".pdf">...</a></p> per
# sale, grouped under bare <p><u><strong>Month</strong></u></p> headers.
_EASTERN_REAL = """
<div class="node__content">
  <div class="field field--name-body field--type-text-with-summary field--label-hidden">
    <div class="field__items"><div class="field__item even" property="content:encoded">
      <p><u><strong>October</strong></u></p>
      <p><a href="/sites/nceb/files/sale_20261021_Crabtree_Family_Moving_LLC.pdf">October 21, 2026 - Crabtree Family Moving, LLC</a></p>
      <p><a href="/sites/nceb/files/sale_20261028_Branagan.pdf">October 28, 2026 - Edward and Yudelka Branagan</a></p>
      <p><u><strong>November</strong></u></p>
      <p><a href="/sites/nceb/files/sale_20261101_Cory_Kendric_Hardin.pdf">November 1, 2026 - Cory Kendric Hardin</a></p>
    </div></div>
  </div>
</div>
"""

# The old buggy fallback matched THESE nav links (real site chrome, not
# listings) because they contain "case"/"trustee"/"#"/"date" keywords and
# are >20 chars. The fixed parser must emit nothing for a page like this.
_NAV_CHROME_ONLY = """
<ul class="menu">
  <li><a href="/case-info">Case Info Case Assignments</a></li>
  <li><a href="/public-interest">Public Interest Cases</a></li>
  <li><a href="/trustee-contact-list">Trustee Contact List</a></li>
  <li><a href="/debtor-noticing">Debtor Electronic Bankruptcy Noticing</a></li>
</ul>
"""

# Real Middle District empty state (captured 2026-10-01).
_MIDDLE_EMPTY = """
<div id="main-content">
  <h1>Public Sales</h1>
  <p>No public sales are listed at this time.</p>
</div>
"""

_URL = "https://www.nceb.uscourts.gov/Public-Sales-Notice"


def test_real_sales_parse_with_debtor_date_and_pdf():
    rows = parse_district_html(_EASTERN_REAL, "Eastern", _URL)
    assert len(rows) == 3

    first = rows[0]
    assert first.defendant == "Crabtree Family Moving, LLC"
    assert first.sale_date is not None
    assert first.sale_date.isoformat().startswith("2026-10-21")
    assert first.state == "NC"
    assert first.county == "Eastern District"
    assert first.source_url == (
        "https://www.nceb.uscourts.gov/sites/nceb/files/sale_20261021_Crabtree_Family_Moving_LLC.pdf"
    )
    # PDF must be wired for enrich_doc_ocr (document_url is the field it reads).
    assert first.raw["document_url"] == first.source_url
    assert first.raw["documents"] == [first.source_url]

    second = rows[1]
    assert second.defendant == "Edward and Yudelka Branagan"


def test_nav_chrome_alone_produces_zero_rows():
    """The exact bug: nav menu text must never become a fabricated listing."""
    rows = parse_district_html(_NAV_CHROME_ONLY, "Eastern", _URL)
    assert rows == []


def test_middle_district_empty_state_is_zero_not_fabricated():
    rows = parse_district_html(_MIDDLE_EMPTY, "Middle", "https://www.ncmb.uscourts.gov/public-sales")
    assert rows == []


def test_short_or_blank_html_is_zero():
    assert parse_district_html("", "Eastern", _URL) == []
    assert parse_district_html("<html></html>", "Eastern", _URL) == []
