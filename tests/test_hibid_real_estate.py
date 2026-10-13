"""hibid_real_estate.py was fixed 2026-10-01 (national-auction-tier audit,
batch 4): most lots never spell out "<X> County" in their title/description
at all -- live-verified two in-footprint NC rows (Lincolnton, Rutherfordton)
came back with county=None even though the city alone is enough to resolve
it via the shared WNC/upstate-SC gazetteer (`_upstate_city_to_county`,
already used by national.gsa_realproperty). Added that as a fallback when
the "<X> County" regex finds nothing.

ADDED 2026-10-13 (source-completeness audit, Pattern B): the search-result
row only ever surfaced one photo's worth of data (previously: none at all --
no image field was even requested). Live-confirmed this same 1217 Daniels Rd
lot (re-checked 2026-10-13) now carries `pictureCount: 38` and a `pictures`
array of 38 real `fullSizeLocation` CDN URLs in the SAME lotSearch response
-- no extra per-listing request needed. `_LOT_LINCOLNTON` below is extended
with the first 10 of those 38 real (live-captured) URLs to test the new
dedupe + 8-cap behavior realistically."""
from foreclosure_scraper.scrapers.national.hibid_real_estate import (
    MAX_PHOTOS,
    _build_listing,
    _real_photos,
)

# Live-captured lot (2026-10-01, pictures re-captured live 2026-10-13): title
# has no "County" text at all.
_LOT_LINCOLNTON = {
    "id": 311452472,
    "lead": "1217 Daniels Rd Lincolnton NC 28092",
    "description": "",
    "bidAmount": 123.45,  # the known unauthenticated-caller sentinel
    "category": [{"id": 1, "categoryName": "Real Estate"}],
    "pictureCount": 38,
    "pictures": [
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719051&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=weFVJAJNd2eFSJQl3YaaO48bhBFXO%2fJy"},
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719092&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=weFVJAJNd2d6Gl6LVidjR%2fJcsaTYi6TM"},
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719126&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=xFvCkzqeLbMbiWCvT7ej8Dh9PTQ3SKu9"},
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719131&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=xFvCkzqeLbMrLAD3vSY%2fvGIw7nJvX2yo"},
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719153&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=xFvCkzqeLbOMnK5RgYMCEKaFGIXIkSse"},
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719341&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=psv6kBVj6C%2fDKb3Zknk4od32msmluMn%2f"},
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719201&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=VrTV32anCvVjNE%2fpo2jXH13iB7Kz6shB"},
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719207&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=VrTV32anCvWTTw%2fE9UCLJBijf4P%2fUPSJ"},
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719254&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=VrTV32anCvV9nbEd5qpTfMfnSvMaWXv4"},
        {"fullSizeLocation": "https://cdn.hibid.com/img.axd?id=8387719276&wid=&rwl=false&p=&ext=&w=0&h=0&t=&lp=&c=true&wt=false&sz=MAX&checksum=VrTV32anCvVspwVOEn0ZSxBYp6umWhjP"},
    ],
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


def test_real_gallery_photos_written_to_raw_images_capped_at_max():
    # 10 real pictures fixtured (live gallery is 38) -- capped to MAX_PHOTOS.
    li = _build_listing("NC", _LOT_LINCOLNTON)
    assert li is not None
    assert "images" in li.raw
    photos = li.raw["images"]["real"]
    assert len(photos) == MAX_PHOTOS
    # First photo matches the live-captured featured/first gallery image.
    assert photos[0].startswith("https://cdn.hibid.com/img.axd?id=8387719051")
    # All real CDN URLs, no placeholders.
    assert all(p.startswith("https://cdn.hibid.com/img.axd?") for p in photos)


def test_real_photos_helper_dedupes_and_caps():
    dupe_url = "https://cdn.hibid.com/img.axd?id=1"
    lot = {"pictures": [{"fullSizeLocation": dupe_url}] * 20}
    out = _real_photos(lot)
    assert out == [dupe_url]  # deduped to a single entry, well under the cap


def test_real_photos_helper_handles_missing_pictures_field():
    # A lot with no pictures/pictureCount at all (e.g. an older cached
    # response, or a lot with zero photos) must not raise.
    assert _real_photos({}) == []
    assert _real_photos({"pictures": []}) == []
    assert _real_photos({"pictures": [{"fullSizeLocation": ""}]}) == []


def test_lot_without_pictures_field_has_no_images_key():
    # Backward-compat: a lot dict that never had the pictures field requested
    # (e.g. a stale fixture, or the field legitimately empty) must not add an
    # "images" key at all -- mirrors freddie_homesteps's `if photo:` pattern.
    lot = dict(_LOT_LINCOLNTON)
    lot.pop("pictures", None)
    li = _build_listing("NC", lot)
    assert li is not None
    assert "images" not in li.raw
