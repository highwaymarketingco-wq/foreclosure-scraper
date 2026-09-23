"""national.estate_sales must not fuse unrelated counties' leads together.

MEASURED 2026-09-23 on the live board: one address ("947 22nd St Pl NE" /
Hickory, NC, mangled by a since-removed widget-scraping path into
"5986 springs rd, conover, ncHickory,\xa0NC\xa028601") appeared 5 times under
5 different counties (Cleveland, Gaston, Greenville, Mecklenburg,
Spartanburg) -- 55% of this source's 29 board rows were duplicated garbage.

Root cause, confirmed against a real fetch of
https://www.estatesales.net/NC/Shelby/28150 (saved as the fixture here):
estatesales.net's zip search returns events within a wide radius, not just
the searched city -- the Shelby (Cleveland Co.) page's own JSON-LD includes
real sales in Hickory (Catawba Co.), Gastonia (Gaston Co.), Connelly Springs
(Burke Co.), Starr (Anderson Co. SC), Inman and Landrum (Spartanburg Co. SC).
_saleevent_to_listing stamped the SEARCHED county onto every event regardless
of where it actually was, so the same real Catawba County sale got relabeled
Cleveland, Gaston, Greenville, Mecklenburg and Spartanburg on different days'
runs (whichever zip's search happened to include it in its radius).

A second, larger bug compounded it: the HTML card-selector fallback
(div[class*='sale'] etc.) ran unconditionally alongside the JSON-LD parser
instead of only when JSON-LD found nothing. That selector list also matches
estatesales.net's "sales near you" widget, whose promo cards carry OTHER
cities' addresses with "NN miles away" trailing text. On the fixture page,
JSON-LD alone correctly found the 20 real sale events; the unconditional
card loop added 81 more elements, 61 of them widget noise like
"947 22nd st pl neHickory,\xa0NC\xa02860230 milesaway" mis-parsed as a
street address -- all still stamped with the searched county.

Fix: resolve each event's own county from its actual city via
upstate_county_for() (falling back to the search county only when the
event has no place info), and only run the HTML card fallback when the
JSON-LD parser truly found nothing, matching the existing text-block
fallback's own "if not out" pattern.
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.scrapers.national.estate_sales import _parse_estatesales_net

FIXTURE = Path(__file__).parent / "fixtures" / "estatesales_net_shelby_28150.html"


def _parse():
    html = FIXTURE.read_text()
    return _parse_estatesales_net(
        html, "https://www.estatesales.net/NC/Shelby/28150", "Shelby", "NC", "Cleveland",
    )


def test_only_the_real_sale_events_are_returned_not_widget_noise():
    out = _parse()
    # MEASURED: the fixture page has exactly 20 real JSON-LD SaleEvent blocks
    # and 20 matching div.sale-row__details cards. Before the fix this
    # returned 101 (20 real + 81 from the unconditionally-run card fallback,
    # most of it "nearby sales" widget garbage).
    assert len(out) == 20


def test_no_listing_carries_miles_away_widget_text_as_its_address():
    out = _parse()
    for li in out:
        if li.street_address:
            assert "milesaway" not in li.street_address.replace(" ", "").lower()
            assert "miles away" not in li.street_address.lower()


def test_each_events_county_matches_its_own_city_not_the_search_county():
    out = _parse()
    by_city = {li.city: li.county for li in out if li.city}
    # These are all real cities present in the fixture's JSON-LD, each in a
    # DIFFERENT county than the searched Shelby/Cleveland Co. -- before the
    # fix every one of these was mislabeled "Cleveland".
    assert by_city["Hickory"] == "Catawba"
    assert by_city["Gastonia"] == "Gaston"
    assert by_city["Connelly Springs"] == "Burke"
    assert by_city["Starr"] == "Anderson"
    assert by_city["Inman"] == "Spartanburg"
    assert by_city["Landrum"] == "Spartanburg"


def test_events_with_no_place_data_keep_the_search_county_as_best_guess():
    out = _parse()
    # VirtualLocation SaleEvent nodes (no address at all) can't be resolved
    # to a real county, so they fall back to the searched city/county --
    # that's a reasonable default, not a regression, as long as it only
    # applies to genuinely unresolvable events.
    shelby_rows = [li for li in out if li.city == "Shelby"]
    assert len(shelby_rows) >= 10
    assert all(li.county == "Cleveland" for li in shelby_rows)
    assert all(li.street_address is None for li in shelby_rows)
