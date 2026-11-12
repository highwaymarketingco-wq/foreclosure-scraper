"""porsche_cpo parser — fixture-based test that catches the shared-ancestor bug.

Before the fix, the fallback parser walked exactly 4 parents up from
every /details/ anchor and landed on a common banner element, so every
'listing' came back with identical price + title.
"""
from __future__ import annotations

from porsche_scraper.scrapers.porsche_cpo import _listings_from_html_fallback


SHARED_ANCESTOR_HTML = """
<html><body>
  <header class="page-banner">
    <h1>Porsche Sound</h1>
    <p class="hero-price">From $107,670</p>
    <p class="hero-mileage">2,960,721</p>
  </header>
  <main>
    <div class="results-grid">
      <article class="result">
        <h3>2016 Porsche 911 Carrera</h3>
        <div class="price">$84,995</div>
        <div class="miles">38,000 miles</div>
        <a href="/us/en-US/details/abc-911-1">View vehicle</a>
      </article>
      <article class="result">
        <h3>2019 Porsche 718 Cayman</h3>
        <div class="price">$62,500</div>
        <div class="miles">22,400 miles</div>
        <a href="/us/en-US/details/def-cayman-2">View vehicle</a>
      </article>
      <article class="result">
        <h3>2014 Porsche Boxster</h3>
        <div class="price">$39,995</div>
        <div class="miles">71,200 miles</div>
        <a href="/us/en-US/details/ghi-boxster-3">View vehicle</a>
      </article>
    </div>
  </main>
</body></html>
"""


def test_distinct_listings_not_inherited_from_shared_ancestor():
    listings = _listings_from_html_fallback(SHARED_ANCESTOR_HTML)
    assert len(listings) == 3, f"expected 3 distinct listings, got {len(listings)}"
    prices = {l.price_usd for l in listings}
    assert prices == {84995.0, 62500.0, 39995.0}, (
        f"each card must inherit its OWN price; got {prices}. "
        f"If you see {{107670.0}} the shared-ancestor bug is back."
    )
    # Years should also be per-listing, not all the same.
    years = {l.year for l in listings}
    assert years == {2016, 2019, 2014}


def test_skips_hero_anchor_without_model_or_year():
    html = """
    <html><body>
      <a href="/us/en-US/details/sound-feature">Porsche Sound</a>
      <article>
        <h3>2016 Porsche 911</h3>
        <div>$80,000</div>
        <a href="/us/en-US/details/real-listing">View</a>
      </article>
    </body></html>
    """
    listings = _listings_from_html_fallback(html)
    # Sound-feature anchor has no model/year/price — must be filtered.
    assert len(listings) == 1
    assert listings[0].source_url.endswith("/real-listing")
