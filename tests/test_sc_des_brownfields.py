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
    county, desc, _docs = _parse_detail_page(html)
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
    county, _, _docs = _parse_detail_page(html)
    assert county is None


def test_detail_page_non_county_tags_stay_none():
    """Live example: pinewood-site-history tags = ['Pollution'] only."""
    html = '<div class="field--name-field-categories"><div class="field__item">Pollution</div></div>'
    county, _, _docs = _parse_detail_page(html)
    assert county is None


def test_detail_page_with_no_tags_field_is_handled():
    county, desc, _docs = _parse_detail_page("<main><p>Some unrelated short text</p></main>")
    assert county is None


def test_description_snippet_skips_short_boilerplate_lines():
    html = """
    <article>
    OK
    <p>This is a real substantial paragraph describing the actual site history in detail.</p>
    </article>
    """
    _, desc, _docs = _parse_detail_page(html)
    assert desc == "This is a real substantial paragraph describing the actual site history in detail."


# --------------------------------------------------------------------------- #
# 2026-10-04 extraction-completeness fix: real per-site case documents
# (Emergency Orders, Corrective Action Plans, monitoring/progress reports)
# were fetched as part of parsing the description and then thrown away.
# --------------------------------------------------------------------------- #

#: Trimmed from the live able-contracting-fire page structure, 2026-10-04.
_REAL_SITE_WITH_DOCS = """
<nav>
  <a href="/programs/bureau-air-quality/asbestos/guidance-documents">Asbestos guidance documents</a>
  <a href="/programs/bureau-water/land-application-permit-program/public-notice-requirements">Public notice requirements</a>
</nav>
<div class="field--name-field-categories">
  <div class="field__item">Sites of Interest</div>
  <div class="field__item">Jasper</div>
</div>
<div class="node__content">
  <p>DHEC issued an <a href="/sites/des/files/media/document/Able%20EO.pdf">Emergency Order</a>
  to the company. See the <a href="/sites/des/files/media/document/Environmental%20Smoke%20Fact%20Sheet.pdf">
  DHEC Environmental Smoke Fact Sheet</a> for more.</p>
</div>
"""


def test_real_per_site_documents_are_harvested():
    county, desc, docs = _parse_detail_page(_REAL_SITE_WITH_DOCS, base_url="https://des.sc.gov/x")
    assert "https://des.sc.gov/sites/des/files/media/document/Able%20EO.pdf" in docs
    assert ("https://des.sc.gov/sites/des/files/media/document/"
            "Environmental%20Smoke%20Fact%20Sheet.pdf") in docs


def test_global_nav_boilerplate_documents_are_excluded():
    """Live finding: every DES site page shares the same ~9 global-nav
    boilerplate PDF links (generic guidance/public-notice pages that appear
    site-wide, outside the article body). Scoping to body_el alone must
    exclude them, or they would win stamp_documents()'s 8-link cap on every
    one of the ~96 sites before a single real per-site document got a slot."""
    _county, _desc, docs = _parse_detail_page(_REAL_SITE_WITH_DOCS, base_url="https://des.sc.gov/x")
    assert not any("guidance-documents" in d or "public-notice-requirements" in d
                   for d in docs)
    assert len(docs) == 2


def test_a_site_with_no_documents_returns_an_empty_list():
    county, desc, docs = _parse_detail_page(
        '<div class="node__content"><p>Some unrelated short text, no links at all here.</p></div>'
    )
    assert docs == []


def test_stamp_documents_reaches_the_listing():
    """End-to-end: fetch()'s per-site Listing must actually carry the
    harvested doc URLs via raw['documents'] (the shape enrichment_doc_ocr
    scans), not just return them from _parse_detail_page and drop them."""
    import asyncio
    from unittest.mock import patch

    from foreclosure_scraper.scrapers.counties_sc.sc_des_brownfields import SCDESBrownfields

    async def fake_get_text(url, **kw):
        if "able-contracting-fire" in url:
            return _REAL_SITE_WITH_DOCS
        if "environmental-sites-projects" in url:
            return ('<a href="/community/community-engagement/environmental-sites-projects/'
                    'able-contracting-fire">Able Contracting Fire</a>')
        return ""

    with patch(
        "foreclosure_scraper.scrapers.counties_sc.sc_des_brownfields.get_text",
        side_effect=fake_get_text,
    ):
        rows = asyncio.run(SCDESBrownfields().fetch())
    assert len(rows) == 1
    li = rows[0]
    assert li.county == "Jasper"
    docs = li.raw.get("documents") or []
    assert any("Able%20EO.pdf" in d for d in docs)
    assert li.raw.get("document_url")
