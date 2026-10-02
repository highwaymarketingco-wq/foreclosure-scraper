"""SC DES brownfields/cleanup sites.

2026-10-01 per-source audit found two real gaps: SITE_LIST_URL had silently
404'd (the site restructured its path to add a "community-engagement"
segment) and dropped ~20+ sites that only this page carried; and every row
shipped with county hardcoded to "Statewide" even though each site's own
detail page frequently carries a real county in its structured "Tags"
field. Verify the link-extraction filter still rejects nav/menu junk, and
that county is only promoted off a single unambiguous real-county tag
match -- never guessed from narrative prose (the exact anti-pattern that
got city_websites/cities.py disabled elsewhere in this codebase).
"""
from foreclosure_scraper.scrapers.counties_sc.sc_des_brownfields import (
    SITE_LIST_URL,
    _extract_site_links,
    _parse_detail_page,
)


def test_site_list_url_has_the_community_engagement_segment():
    """Old path (.../community/environmental-sites-projects) 404s live as of
    2026-10-01; the site moved it under community-engagement."""
    assert "community-engagement/environmental-sites-projects" in SITE_LIST_URL


def test_real_site_link_is_kept():
    html = ('<a href="/community/community-engagement/environmental-sites-projects/'
            'congaree-river-sediment-cleanup">Congaree River Sediment Cleanup</a>')
    links = _extract_site_links(html, "https://des.sc.gov/programs/x")
    assert links == [
        ("https://des.sc.gov/community/community-engagement/"
         "environmental-sites-projects/congaree-river-sediment-cleanup",
         "Congaree River Sediment Cleanup"),
    ]


def test_nav_and_section_label_links_are_rejected():
    """2026-09-15 fix regression guard: a bare in-page anchor resolving (via
    urljoin) to a URL that still contains unrelated path text, and a section
    heading whose link text merely mentions "brownfield", must not pass."""
    html = (
        '<a href="#main-content">Skip to main content</a>'
        '<a href="/programs/bureau-land-waste-management/'
        'brownfields-voluntary-cleanup-program/funding">Brownfields Funding & Incentives</a>'
    )
    links = _extract_site_links(
        html,
        "https://des.sc.gov/programs/bureau-land-waste-management/"
        "brownfields-voluntary-cleanup-program",
    )
    assert links == []


def test_detail_page_single_county_tag_is_used():
    """Live example: able-contracting-fire tags = ['Sites of Interest', 'Jasper']."""
    html = """
    <div class="field--name-field-categories">
      <div class="field__item">Sites of Interest</div>
      <div class="field__item">Jasper</div>
    </div>
    <div class="node__content"><p>On January 6, 2020, DHEC completed the removal of material.</p></div>
    """
    county, desc = _parse_detail_page(html)
    assert county == "Jasper"
    assert "DHEC completed the removal" in desc


def test_detail_page_two_county_tags_stays_ambiguous():
    """Live example: new-indy-catawba tags = ['New Indy', 'Lancaster', 'York'] --
    a real cross-county case. Picking one would be a guess, not a fact."""
    html = """
    <div class="field--name-field-categories">
      <div class="field__item">New Indy</div>
      <div class="field__item">Lancaster</div>
      <div class="field__item">York</div>
    </div>
    """
    county, _ = _parse_detail_page(html)
    assert county is None


def test_detail_page_non_county_tags_stay_none():
    """Live example: pinewood-site-history tags = ['Pollution'] only."""
    html = '<div class="field--name-field-categories"><div class="field__item">Pollution</div></div>'
    county, _ = _parse_detail_page(html)
    assert county is None


def test_detail_page_with_no_tags_field_is_handled():
    county, desc = _parse_detail_page("<main><p>Some unrelated short text</p></main>")
    assert county is None


def test_description_snippet_skips_short_boilerplate_lines():
    html = """
    <article>
    OK
    <p>This is a real substantial paragraph describing the actual site history in detail.</p>
    </article>
    """
    _, desc = _parse_detail_page(html)
    assert desc == "This is a real substantial paragraph describing the actual site history in detail."
