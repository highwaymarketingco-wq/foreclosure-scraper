"""people_search: multi-candidate capture fix (2026-10-14).

Live-verified against real fastpeoplesearch.com and truepeoplesearch.com
searches (see the scraper module's own docstring for the full
investigation). The old code took `cards[0]` only and used a single CSS
selector list, which in practice captured ZERO real candidates on either
site:

  - fastpeoplesearch is reached through the wall_bypass browser tier
    (curl-cffi impersonation still 403s), which returns flattened visible
    TEXT with no HTML tags at all (wall_bypass._html_to_text) -- so the old
    `soup.select(".card", ...)` always found 0 elements and every search
    silently recorded "no_match", even though the real page body plainly
    listed 9-10 free candidates per name.
  - truepeoplesearch's curl-cffi tier DOES return real HTML with `.card`
    elements, but `cards[0]` was the "Search Neighbors" form widget (id
    `divSearchFormMobileFullContainer`), not a person -- the real results
    sit in `.card-summary` cards further down, including a hidden
    `.d-none` duplicate of the very first one.

`FASTPEOPLESEARCH_TEXT_EXCERPT` is a trimmed, real, live-captured
(2026-10-14) excerpt of a "John Smith" / NC search's flattened text: the
tail of the popular-cities boilerplate (no tag boundary before the first
real name -- the case `_TEXT_CARD_RE`'s 2-token name anchor exists for),
3 real free result cards, and 1 sponsored/paid card that must NOT be
captured. `TRUEPEOPLESEARCH_HTML_EXCERPT` is a trimmed, real, live-captured
(2026-10-14) excerpt of the same search's real HTML: the junk search-form
`.card`, 2 real `.card-summary` result cards, and a `.d-none` hidden
duplicate of the first.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from foreclosure_scraper.scrapers.national import people_search as M

FASTPEOPLESEARCH_TEXT_EXCERPT = (
    "Mocksville Monroe Mooresville Morganton Mount Airy New Bern Raeford "
    "Raleigh Reidsville Rocky Mount Rowland Roxboro Salisbury Sanford Sylva "
    "Thomasville Wadesboro Waxhaw Wilmington Wilson Winston Salem "
    "John Smith Age 50 • Holiday, FL Past Addresses: Holiday, FL • "
    "New Port Richey, FL • Atlanta, GA • Topton, NC • Weeki "
    "Wachee, FL Relatives: Mozelle Smith • Andrew Smith • Andy "
    "Smith • Ann Smith • Bradley Smith AKA: John M Smith Jr • "
    "John Milton Smith 3rd • John MILT Smith • John Smith Jr "
    "View Free Details "
    "Johnathan Smith Age 38 • Beulaville, NC Past Addresses: "
    "Beulaville, NC • Beulaville, NC • Beulaville, NC • "
    "Beulaville, NC • Benson, NC Relatives: Keighley Smith • "
    "Brandon Smith • Brooke Springer • Catherine Smith • "
    "Eric Smith AKA: Johnathan R Smith • John Michael Smith • "
    "Jonathan R Smith • Jonathan L Smith View Free Details "
    "Johnnie Smith Age 43 • Kalamazoo, MI Past Addresses: Kalamazoo, "
    "MI • Aurora, NC • Middletown, RI • Providence, RI "
    "• Tiverton, RI Relatives: Renae Smith • Adreanna Smith "
    "• Ariel Garrison • Brianna Smith • Daniel Lueth AKA: "
    "Johnnie W Smith Jr • Johnnie William Smith Jr • Johnnie W "
    "Smith • Johnnie William Smith View Free Details "
    "John Allen Smith Bluff City, TN Age 53 View Details "
    "Sponsored By TruthFinder.com"
)

TRUEPEOPLESEARCH_HTML_EXCERPT = """
<div class="card shadow-form" id="divSearchFormMobileFullContainer" style="display:none;">
<div class="card-body">
<div class="search-form search-form-name" id="searchFormNameMobileFullContainer">
<input aria-label="Name" class="input-n form-control" id="id-mf-n" name="Name" value="John Smith"/>
</div>
</div>
</div>
<div class="card card-body shadow-form card-summary pt-3 mb-2" data-detail-link="/find/person/pn680869lr92u8un0829">
<div class="row">
<div class="col-md-8">
<div class="content-header">
                John Smith
            </div>
<div>
<span class="">Age </span>
<span class="content-value">
36                </span><span> • </span><span class="content-value">Mcalester, OK</span>
</div>
<div class="mt-2">
<span class="content-label">Used to live in </span>
<span class="content-value">McAlester OK, Cottonwood AZ, Eufaula OK, ...  </span>
</div>
<div class="">
<span class="content-label">Related to </span>
<span class="content-value">Amanda Smith, Ashley Coffman</span>
</div>
</div>
</div>
</div>
<div class="card card-body shadow-form card-summary pt-3 mb-2" data-detail-link="/find/person/pz9zzz9lr92u8un0829">
<div class="row">
<div class="col-md-8">
<div class="content-header">
                John Smith
            </div>
<div>
<span class="">Age </span>
<span class="content-value">
48                </span><span> • </span><span class="content-value">Farmington, NM</span>
</div>
<div class="mt-2">
<span class="content-label">Used to live in </span>
<span class="content-value">Durango CO, Pagosa Springs CO, Aztec NM, ...  </span>
</div>
</div>
</div>
</div>
<div class="card card-body shadow-form card-summary pt-3 d-none" data-detail-link="/find/person/p1144gfruekc4fkry39odjfgu">
<div class="row">
<div class="col-md-8">
<div class="h4">
                John Smith
            </div>
<div>
<span class="content-label">Age </span>
<span class="content-value">
36                </span>
</div>
<div>
<span class="content-label">Lives in </span>
<span class="content-value">Mcalester, OK</span>
</div>
</div>
</div>
</div>
"""


def test_matches_from_text_captures_every_free_card_not_just_first():
    matches = M._matches_from_text(FASTPEOPLESEARCH_TEXT_EXCERPT)
    # 3 real free cards -- the old cards[0]-only code captured at most 1,
    # and in practice (CSS selectors against tagless flattened text)
    # captured 0.
    assert len(matches) == 3
    names = [m["name"] for m in matches]
    assert names == ["John Smith", "Johnathan Smith", "Johnnie Smith"]


def test_matches_from_text_first_card_name_not_contaminated_by_boilerplate():
    # The real failure mode: with no tag boundary between the trailing
    # popular-cities list and the first real name, a looser token count
    # swallows "Winston Salem" into the name.
    matches = M._matches_from_text(FASTPEOPLESEARCH_TEXT_EXCERPT)
    first = matches[0]
    assert first["name"] == "John Smith"
    assert first["age"] == "50"
    assert first["city"] == "Holiday, FL"


def test_matches_from_text_excludes_sponsored_cards():
    matches = M._matches_from_text(FASTPEOPLESEARCH_TEXT_EXCERPT)
    assert all("Allen" not in m["name"] for m in matches)
    assert all("Bluff City" not in (m["full_text"] or "") for m in matches)


def test_matches_from_cards_skips_search_form_and_hidden_duplicate():
    soup = BeautifulSoup(TRUEPEOPLESEARCH_HTML_EXCERPT, "html.parser")
    cards = soup.select(M._SITES["truepeoplesearch"]["card_selector"])
    # 3 `.card-summary` elements in the fixture: 2 real + 1 hidden dup.
    assert len(cards) == 3
    matches = M._matches_from_cards(cards)
    # The old cards[0]-only code (against the unfiltered `.card` selector)
    # would have returned the search-form widget, a person, 0 times.
    assert len(matches) == 2
    assert matches[0]["age"] == "36"
    assert matches[0]["city"] is None  # DOM path doesn't split out city
    assert "Mcalester, OK" in matches[0]["full_text"]
    assert matches[1]["age"] == "48"
    assert "Farmington, NM" in matches[1]["full_text"]


def test_matches_from_cards_empty_when_no_age_marker():
    # A page of pure chrome (search form, filters, ads) with no person
    # cards at all must fall through to "no_match", not crash.
    soup = BeautifulSoup(
        '<div class="card"><div class="card-body">Search Neighbors</div></div>',
        "html.parser",
    )
    cards = soup.select(".card")
    assert M._matches_from_cards(cards) == []
