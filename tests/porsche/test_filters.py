"""Tests for filter rules + parsing helpers."""
from __future__ import annotations

from porsche_scraper.filters import FilterCriteria, current_year, matches
from porsche_scraper.models import (
    Listing,
    TitleStatus,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)


def _l(**kw) -> Listing:
    base = dict(
        source="test",
        source_url="https://example.com/x",
        title=kw.pop("title", "2016 Porsche 911 Carrera"),
        year=kw.pop("year", 2016),
        model=kw.pop("model", "911"),
        price_usd=kw.pop("price_usd", 30_000),
    )
    base.update(kw)
    return Listing(**base)


# ---------- year window ----------


def test_keeps_in_year_range():
    assert matches(_l(year=1990))                 # air-cooled floor
    assert matches(_l(year=2001, title="2001 Porsche 911 Carrera", model="911"))
    assert matches(_l(year=current_year()))


def test_drops_too_old():
    assert not matches(_l(year=1989))


def test_drops_future_year():
    assert not matches(_l(year=current_year() + 1))


def test_drops_unknown_year_by_default():
    assert not matches(_l(year=None, title="Porsche 911 (year tbd)"))


def test_keeps_unknown_year_when_explicit_opt_in():
    crit = FilterCriteria(require_known_year=False)
    assert matches(_l(year=None, title="Porsche 911"), crit)


# ---------- price cap applies to EVERY source ----------
# The board is a steals board — every Porsche under the cap ($50k as of
# 2026-08-15), from any source, not just salvage. A known price over the cap is
# dropped regardless of title. Only price-TBD auction cars survive without a
# number. These tests use the default cap, so they track MAX_PRICE_USD.


def test_keeps_below_price_cap():
    assert matches(_l(price_usd=49_999))


def test_drops_just_over_price_cap():
    assert not matches(_l(price_usd=50_001, title_status=TitleStatus.CLEAN))


def test_drops_over_price_cap_with_clean_title():
    assert not matches(_l(price_usd=60_000, title_status=TitleStatus.CLEAN))


def test_drops_over_cap_salvage_when_price_is_known():
    # A $60k salvage GT3 is not a steal. Known price beats title now.
    assert not matches(_l(price_usd=60_000, title_status=TitleStatus.SALVAGE))


def test_drops_over_cap_rebuilt_when_price_is_known():
    assert not matches(_l(price_usd=60_000, title_status=TitleStatus.REBUILT))


def test_keeps_cheap_salvage():
    assert matches(_l(price_usd=18_000, title_status=TitleStatus.SALVAGE))


def test_keeps_price_tbd_auction_car():
    # Copart / IAAI / GovDeals — no asking price, salvage title, price set at sale.
    assert matches(_l(price_usd=None, current_bid_usd=None,
                      title_status=TitleStatus.SALVAGE))


def test_uses_current_bid_when_no_price():
    l = _l(price_usd=None, current_bid_usd=20_000)
    assert matches(l)


def test_drops_auction_car_when_current_bid_over_cap():
    l = _l(price_usd=None, current_bid_usd=55_000, title_status=TitleStatus.SALVAGE)
    assert not matches(l)


def test_drops_no_price_unless_allowed():
    l = _l(price_usd=None, current_bid_usd=None)
    assert not matches(l)
    assert matches(l, FilterCriteria(allow_unknown_price=True))


# ---------- excluded models ----------


def test_drops_panamera_by_title():
    assert not matches(_l(title="2018 Porsche Panamera 4S", model="Panamera"))


def test_keeps_cayenne_now_included():
    # Cayenne (+ Taycan) are intentionally INCLUDED (feat 1e9e158, "include
    # Taycan + Cayenne ... drop cayenne exclusion"). Only Panamera + Macan
    # remain excluded.
    assert matches(_l(model="Cayenne", title="2017 Porsche Cayenne"))


def test_drops_macan():
    assert not matches(_l(title="2019 Porsche Macan", model="Macan"))


def test_keeps_911():
    assert matches(_l(title="2018 Porsche 911 Carrera", model="911"))


def test_keeps_cayman_and_boxster():
    assert matches(_l(title="2016 Porsche Cayman GT4", model="Cayman"))
    assert matches(_l(title="2014 Porsche Boxster S", model="Boxster"))


# Tricky: "Caymanian" or "Macandrew" shouldn't match, but our substring
# match treats anything with `macan` in it as Macan. That's acceptable
# for now (no real Porsche trim has those substrings), but lock it in
# so future contributors notice if they tighten the matcher.
def test_substring_match_is_intentional():
    # "Cayman" must NOT trigger Cayenne/Macan/Panamera. Verify the boundary.
    assert matches(_l(title="2016 Porsche Cayman GT4 — Caymanian Spec", model="Cayman"))


# ---------- drivable ----------


def test_drops_parts_only():
    l = _l(
        title="2016 Porsche 911 — parts only, no engine",
        title_status=TitleStatus.PARTS_ONLY,
    )
    l.drivable = False
    assert not matches(l)


def test_drops_blown_engine():
    l = _l(title="2014 Porsche Cayman with blown motor")
    l.drivable = infer_drivable(l.title, l.title_status)
    assert l.drivable is False
    assert not matches(l)


def test_keeps_drivable_unknown():
    l = _l(title="2016 Porsche 911 Carrera")
    l.drivable = infer_drivable(l.title, l.title_status)
    assert l.drivable is None
    assert matches(l)


def test_keeps_explicitly_drivable():
    l = _l(title="2014 Porsche Boxster, runs and drives great")
    l.drivable = True
    assert matches(l)


# ---------- helper parsing ----------


def test_parse_price_handles_dollar_and_commas():
    assert parse_price("$34,995") == 34_995.0
    assert parse_price("12000") == 12_000.0
    assert parse_price(45_000) == 45_000.0
    assert parse_price(None) is None
    assert parse_price("call for price") is None


def test_parse_miles_handles_units():
    assert parse_miles("85,000 miles") == 85_000
    assert parse_miles("85k mi") == 85_000
    assert parse_miles("123") == 123
    assert parse_miles(None) is None


def test_parse_miles_bat_k_mile_pattern():
    # BaT excerpts use "24k-Mile" / "6,000-Mile"
    assert parse_miles("24k-Mile 2016 Porsche 911") == 24_000
    assert parse_miles("55,000-Mile") == 55_000


def test_parse_miles_ignores_prose_without_unit():
    # Mileage extraction must NOT concatenate year + listing-id digits
    # from a free-prose excerpt when no "mi"/"miles" token is present.
    assert parse_miles("This 2024 Porsche 911 GT3 R Rennsport is the 7th of 77 examples built") is None


def test_parse_year():
    assert parse_year("2016 Porsche 911 Carrera") == 2016
    assert parse_year("Porsche") is None
    assert parse_year(None) is None


def test_infer_title_status():
    assert infer_title_status("2016 Porsche 911 — rebuilt title") == TitleStatus.REBUILT
    assert infer_title_status("Salvage Porsche Cayman") == TitleStatus.SALVAGE
    assert infer_title_status("clean title!") == TitleStatus.CLEAN
    assert infer_title_status("2016 Porsche 911") == TitleStatus.UNKNOWN


# ---------- dedupe key ----------


def test_dedupe_prefers_vin():
    a = _l(vin="WP0AB2A91GS123456")
    b = _l(vin="WP0AB2A91GS123456", source="other")
    assert a.dedupe_key() == b.dedupe_key()


def test_dedupe_falls_back_to_source_id():
    a = _l(listing_id="abc", source="cars_com")
    b = _l(listing_id="abc", source="cars_com")
    assert a.dedupe_key() == b.dedupe_key()
