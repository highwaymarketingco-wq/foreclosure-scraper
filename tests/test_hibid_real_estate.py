"""hibid_real_estate.py was fixed 2026-10-01 (national-auction-tier audit,
batch 4): most lots never spell out "<X> County" in their title/description
at all -- live-verified two in-footprint NC rows (Lincolnton, Rutherfordton)
came back with county=None even though the city alone is enough to resolve
it via the shared WNC/upstate-SC gazetteer (`_upstate_city_to_county`,
already used by national.gsa_realproperty). Added that as a fallback when
the "<X> County" regex finds nothing."""
from foreclosure_scraper.scrapers.national.hibid_real_estate import _build_listing

# Live-captured lot (2026-10-01): title has no "County" text at all.
_LOT_LINCOLNTON = {
    "id": 311452472,
    "lead": "1217 Daniels Rd Lincolnton NC 28092",
    "description": "",
    "bidAmount": 123.45,  # the known unauthenticated-caller sentinel
    "category": [{"id": 1, "categoryName": "Real Estate"}],
    "auction": {
        "id": 758389,
        "eventName": "3/2 2104sqft -- 1217 Daniels in Lincolnton NC",
        "eventCity": "Lincolnton",
        "eventState": "NC",
        "eventZip": "28092",
        "bidCloseDateTime": "2026-10-09T19:49:00",
        "auctioneer": {"name": "Akita Properties"},
    },
}

# A lot whose description DOES spell out "<X> County" -- the regex path
# must still win (more specific than the gazetteer) when both are present.
_LOT_WITH_EXPLICIT_COUNTY = {
    "id": 999,
    "lead": "123 Main St",
    "description": "Located in Spartanburg County, SC. 1 acre lot.",
    "bidAmount": 123.45,
    "category": [{"id": 1, "categoryName": "Real Estate"}],
    "auction": {"eventCity": "Inman", "eventState": "SC"},
}


def test_county_resolves_via_gazetteer_when_title_has_no_county_text():
    li = _build_listing("NC", _LOT_LINCOLNTON)
    assert li is not None
    assert li.city == "Lincolnton"
    assert li.county == "Lincoln"


def test_explicit_county_text_still_takes_priority():
    li = _build_listing("SC", _LOT_WITH_EXPLICIT_COUNTY)
    assert li is not None
    assert li.county == "Spartanburg"


def test_sentinel_bid_amount_is_never_surfaced_as_opening_bid():
    li = _build_listing("NC", _LOT_LINCOLNTON)
    assert li.opening_bid is None


def test_out_of_gazetteer_city_leaves_county_none_not_guessed():
    # Live-verified 2026-10-01: Castle Hayne NC is a real hit on this source
    # but is not a known place in the gazetteer -- county must stay None
    # rather than being guessed, consistent with the rest of this codebase's
    # "accuracy over volume" posture.
    lot = {
        "id": 1,
        "lead": "28 Stoney Rd, Castle Hayne NC",
        "description": "",
        "bidAmount": 123.45,
        "category": [{"id": 1, "categoryName": "Real Estate"}],
        "auction": {"eventCity": "Castle Hayne", "eventState": "NC"},
    }
    li = _build_listing("NC", lot)
    assert li is not None
    assert li.county is None
