"""Terry Howe FLC: _SC_COUNTIES widened from the 7-county flip footprint to the
full 46-county SC gazetteer (docs/coverage_gap_build_plan_2026-09-23.md item 7).

BUG, FOUND WHILE PROBING ITEM 7: `_SC_COUNTIES` was built from
`config.ALL_COUNTIES`, which -- despite the generic name and despite this
module's own docstring claiming any in-scope SC county's auction is picked up --
is actually the narrow 18-county FLIP footprint's 7-county SC subset
(Spartanburg/Anderson/Pickens/Oconee/Cherokee/Union/Laurens). Every OTHER real SC
county's Terry Howe auction was silently dropped by `_county_of()` before the FLC
marker check or `parse_flc_rows` ever ran -- the same footprint-artifact bug
class the plan doc's item #1 already found and fixed in
`nc_ecourts_lis_pendens.TARGET_COUNTIES` this same session. TAX_SALE (this
scraper's listing_type) is NOT in `main._FLIP_LISTING_TYPES`, so it routes
through `config.in_scope_distressed()`, which admits any real NC/SC county with
no deny list -- confirmed below by checking every widened county against that
real function, not assumed.

LIVE-VERIFIED 2026-09-23 (GET https://terryhowe.com/wp-json/wp/v2/auctions?
per_page=100&_fields=id,title,link,content, 100 auctions returned): two auctions
for counties OUTSIDE the old 7-county set were real, current, and FLC-marked:

  "Fairfield County, SC – 6 Properties for Fairfield County Forfeited Land
   Commission" (link: terryhowe.com/auctions/fairfield-county-sc-7-properties-
   for-fairfield-forfeited-land-commission/). Body opens "These properties are
   owned by the Fairfield County Forfeited Land Commission. They were acquired
   by delinquent tax sale deed..." -- matches _FLC_MARK on both "forfeited land"
   and "delinquent tax" in title+body. parse_flc_rows() on the real body returns
   6 rows: TMS 088-00-00-068-000 "Off Chester Rd" Winnsboro; 126-04-01-006-000
   "410 Davis Cir" Winnsboro; 128-00-00-004-000 "Off Bayberry Dr" Winnsboro;
   134-04-02-012-000 "281 Colonels Cir" Ridgeway; 145-02-09-008-000 "Cherry Rd"
   Winnsboro; and one more.

  "Chester County, SC – 25 Properties" (link: terryhowe.com/auctions/chester-
   county-sc-25-properties/). Title alone carries no FLC wording, but the body
   does ("acquired by the sellers due to delinquent tax sale deed... Quitclaim
   Deed only"), so _FLC_MARK still matches on title+body combined -- proving the
   filter's title-OR-body design (not title-only) is load-bearing here.
   parse_flc_rows() returns 25 rows, e.g. TMS 095-00-00-047-000 "3641 Songbird
   Ln" Chester; 101-00-00-058-000 "2008 Discovery Rd" Cornwell;
   104-00-00-084-000 "2002 Gregg Rd" Rock Hill.

Both were confirmed DROPPED pre-fix (`_county_of(title)` returned None for both
titles, verified by running the OLD `config.ALL_COUNTIES`-sourced set against
them before this fix) and confirmed ADMITTED post-fix with ZERO other code
change -- the parser (`parse_flc_rows`) and the FLC marker (`_FLC_MARK`) were
already correct; only the county allow-list was wrong.

These are recorded as fixture-shaped unit tests (the real title/body text below,
captured live 2026-09-23) so CI stays deterministic; the live findings above are
what justified the fix and are preserved here for the audit trail.
"""
from __future__ import annotations

from foreclosure_scraper.config import in_scope_distressed
from foreclosure_scraper.validation import SC_COUNTIES as ALL_SC_COUNTIES
from foreclosure_scraper.scrapers.counties_sc.terry_howe_flc import (
    _SC_COUNTIES,
    _county_of,
    _strip_html,
    _FLC_MARK,
    parse_flc_rows,
)

# Real title (WP REST "title.rendered", HTML-entity-encoded dash left as-is —
# _county_of/_FLC_MARK operate on the raw rendered string, same as production)
# and body (HTML-stripped via _strip_html, same as fetch() does), captured live
# 2026-09-23 from https://terryhowe.com/wp-json/wp/v2/auctions .
_FAIRFIELD_TITLE = (
    "Fairfield County, SC &#8211; 6 Properties for Fairfield County "
    "Forfeited Land Commission"
)
_FAIRFIELD_BODY_HTML = (
    "<p>All items in this real estate auction will be sold individually. "
    "These properties are owned by the Fairfield County Forfeited Land "
    "Commission. They were acquired by&nbsp;delinquent tax sale deed&nbsp;and "
    "will be transferred by&nbsp;Quitclaim Deed only&nbsp;using the most "
    "recent deed description.</p>"
    "<p>Tax ID Description "
    "088-00-00-068-000 Off Chester Rd, Winnsboro, SC "
    "126-04-01-006-000 410 Davis Cir, Winnsboro, SC "
    "128-00-00-004-000 Off Bayberry Dr, Winnsboro, SC "
    "134-04-02-012-000 281 Colonels Cir, Ridgeway, SC "
    "145-02-09-008-000 Cherry Rd, Winnsboro, SC "
    "146-00-00-012-000 512 Longtown Rd, Ridgeway, SC</p>"
)

_CHESTER_TITLE = "Chester County, SC &#8211; 25 Properties"
_CHESTER_BODY_HTML = (
    "<p>All properties in this real estate auction will be sold individually. "
    "These properties were acquired by the sellers due to delinquent tax sale "
    "deed and will be transferred by Quitclaim Deed only using the most recent "
    "deed description.</p>"
    "<p>Tax ID Description "
    "095-00-00-047-000 3641 Songbird Ln, Chester, SC "
    "101-00-00-058-000 2008 Discovery Rd, Cornwell, SC "
    "104-00-00-084-000 2002 Gregg Rd, Rock Hill, SC</p>"
)


def test_sc_counties_is_the_full_46_county_gazetteer():
    assert _SC_COUNTIES == {c.lower() for c in ALL_SC_COUNTIES}
    assert len(_SC_COUNTIES) == 46


def test_formerly_dropped_counties_now_pass_county_of():
    # Pre-fix, _county_of sourced from config.ALL_COUNTIES (7 SC counties) and
    # returned None for both of these real titles.
    assert _county_of(_FAIRFIELD_TITLE) == "Fairfield"
    assert _county_of(_CHESTER_TITLE) == "Chester"


def test_every_sc_county_passes_the_real_scope_gate():
    # TAX_SALE is not a flip listing type, so these must clear
    # config.in_scope_distressed(), not the narrow flip footprint.
    for c in _SC_COUNTIES:
        assert in_scope_distressed(c.title(), "SC"), (
            f"{c} is in _SC_COUNTIES but fails in_scope_distressed -- its rows "
            f"would be silently dropped at the main.py scope gate"
        )


def test_fairfield_auction_passes_flc_marker_and_parses_real_rows():
    body = _strip_html(_FAIRFIELD_BODY_HTML)
    assert _FLC_MARK.search(_FAIRFIELD_TITLE + " " + body)
    rows = parse_flc_rows(body)
    assert len(rows) == 6
    by_parcel = {r["parcel_id"]: r for r in rows}
    assert by_parcel["088-00-00-068-000"]["street_address"] == "Off Chester Rd"
    assert by_parcel["088-00-00-068-000"]["city"] == "Winnsboro"
    assert by_parcel["134-04-02-012-000"]["city"] == "Ridgeway"


def test_chester_auction_flc_marker_is_body_only_not_title():
    # The title alone ("Chester County, SC – 25 Properties") carries no FLC
    # wording -- proving the title+body combined check is load-bearing, not
    # redundant with a title-only check.
    body = _strip_html(_CHESTER_BODY_HTML)
    assert not _FLC_MARK.search(_CHESTER_TITLE)
    assert _FLC_MARK.search(body)
    assert _FLC_MARK.search(_CHESTER_TITLE + " " + body)
    rows = parse_flc_rows(body)
    assert len(rows) == 3
    by_parcel = {r["parcel_id"]: r for r in rows}
    assert by_parcel["095-00-00-047-000"]["street_address"] == "3641 Songbird Ln"
    assert by_parcel["104-00-00-084-000"]["city"] == "Rock Hill"
