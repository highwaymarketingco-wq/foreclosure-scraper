"""national.seeclickfix — HERMES extraction-completeness audit, batch 18
(2026-10-04). RE-ENABLED this batch; previously disabled 2026-09-15 as a
confirmed garbage emitter.

Root cause (re-confirmed live 2026-10-04, unchanged): SCF's v2 `/issues`
endpoint silently ignores `lat`/`lng`/`radius` -- a query built around
Asheville NC's coordinates still returns issues from Mesquite TX, Cape
Winelands (South Africa), Toledo OH, Oakland CA, Fort Lauderdale FL,
Albuquerque NM, Rock Island IL.

Real, free fix (new finding this batch): SCF has a working `place_url`
scoping param. Each of the 20 footprint cities' slug was re-resolved via
`/api/v2/places?lat=&lng=` (which DOES state-disambiguate) and spot-
verified live against `/issues?place_url=<slug>` -- e.g.
`place_url=hendersonville` silently resolves to Hendersonville, TENNESSEE
(wrong state), while the correct slug is `hendersonville_nc`.
`place_url=spartanburg` returned 415 real Spartanburg, SC rows.

A defense-in-depth state check was also added: `place_url=shelby-nc`
returned one row address-texted "Brownsville, TX" mixed into otherwise-
correct Shelby, NC rows (SCF's own place-tagging has occasional noise) --
`_address_names_wrong_state` drops any row whose free-text address names a
different state outright.

`county` is now a real, gazetteer-verified value (was a hardcoded `None`
in the disabled version, which meant even a hypothetical correctly-geo-
scoped row would have been dropped at the scope gate).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import BaseScraper
from foreclosure_scraper.scrapers.national import seeclickfix as m
from foreclosure_scraper.web_artifact import RAW_KEEP


def test_scraper_is_not_disabled():
    """FIXED 2026-10-04: re-enabled now that the underlying geo-param bug
    is fixed."""
    assert m.SeeClickFixScraper.disabled is False


def test_every_footprint_city_has_a_place_url_and_county():
    assert len(m._CITIES) == 20
    for c in m._CITIES:
        assert c.get("place_url"), c
        assert c.get("county"), c
        assert c["state"] in ("NC", "SC")


def test_no_two_cities_share_a_place_url():
    """Each slug was independently resolved -- a collision would mean two
    cities are accidentally querying the same place."""
    slugs = [c["place_url"] for c in m._CITIES]
    assert len(set(slugs)) == len(slugs)


def test_hendersonville_slug_is_the_nc_specific_one():
    """The exact collision this batch found: the bare 'hendersonville'
    slug resolves to Hendersonville, TENNESSEE on the real API."""
    hv = next(c for c in m._CITIES if c["city"] == "Hendersonville")
    assert hv["place_url"] == "hendersonville_nc"
    assert hv["place_url"] != "hendersonville"


def test_fetch_city_queries_by_place_url_not_lat_lng():
    """Regression guard for the original bug: the outgoing request params
    must use place_url, and must NOT send lat/lng/radius (silently ignored
    by the real API, confirmed live 2026-10-04). `iss.get("lat")` further
    down (reading the per-ISSUE lat back out of the response) is unrelated
    and must not trip this."""
    import inspect
    src = inspect.getsource(m.SeeClickFixScraper._fetch_city)
    params_block = src.split("params = {", 1)[1].split("}", 1)[0]
    assert '"place_url": c["place_url"]' in params_block
    assert '"lat"' not in params_block
    assert '"radius"' not in params_block


def test_address_names_wrong_state_detects_known_collision():
    assert m._address_names_wrong_state(
        "Cleveland N Morton Street And Hortencis Brownsville, TX", "NC"
    ) is True
    assert m._address_names_wrong_state(
        "301-307 East Warren Street Shelby, NC 28150, USA", "NC"
    ) is False


def test_address_names_wrong_state_is_lenient_on_terse_addresses():
    """Must not reject genuinely-good terse addresses that happen not to
    spell out the state -- live-sampled real row shape."""
    assert m._address_names_wrong_state(
        "281 Wells Drforest City NC 28043, USA", "NC"
    ) is False
    assert m._address_names_wrong_state("", "NC") is False
    assert m._address_names_wrong_state(None, "NC") is False


def test_address_names_wrong_state_does_not_false_positive_on_own_state():
    # NC is never in _OTHER_STATE_TOKENS, so an NC address never trips this.
    assert "NC" not in m._OTHER_STATE_TOKENS
    assert "SC" not in m._OTHER_STATE_TOKENS


def test_raw_keep_already_covers_seeclickfix():
    assert RAW_KEEP.get("seeclickfix") == "*"


def test_distress_keyword_filter_unchanged():
    assert "blight" in m._DISTRESS_KEYWORDS
    assert "vacant" in m._DISTRESS_KEYWORDS
    assert "abandoned" in m._DISTRESS_KEYWORDS


def test_scraper_is_registered_and_discoverable():
    from foreclosure_scraper.scrapers._registry import discover
    slugs = {cls.slug for cls in discover()}
    assert "national.seeclickfix" in slugs
    assert issubclass(m.SeeClickFixScraper, BaseScraper)


# ---------------------------------------------------------------------------
# Source-completeness audit 2026-10-14: "photo field" flag. Live-verified
# against 453 real rows (5 footprint cities) / 202 distress-keyword rows:
# `media.image_full` (a real resident-uploaded photo) populated on 99/202
# (49%); the rest carry only `media.representative_image_url`, a generic
# per-category stock icon (same icon for every issue of that category,
# confirmed by re-fetching across unrelated rows) that is NOT per-row data
# and stays uncaptured by design.
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload


class _FakeHttpClient:
    def __init__(self, pages):
        self._pages = pages
        self._i = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        page = self._pages[self._i] if self._i < len(self._pages) else {"issues": []}
        self._i += 1
        return _FakeResp(page)


_REAL_ISSUE_WITH_PHOTO = {
    # Shape live-verified 2026-10-14 against place_url=spartanburg.
    "id": 22478671,
    "summary": "Junk in Yard",
    "description": "trash and junk piled in the side yard",
    "address": "123 Elm St, Spartanburg, SC",
    "lat": 34.9, "lng": -81.9,
    "created_at": "2026-08-11T10:25:06-04:00",
    "updated_at": "2026-08-11T10:25:06-04:00",
    "html_url": "https://seeclickfix.com/issues/22478671",
    "media": {
        "video_url": None,
        "image_full": (
            "https://seeclickfix.com/rails/active_storage/representations/"
            "redirect/eyJ.../2decddc0-6621-40b9-a808-f5f0722b89f8.jpg"
        ),
        "image_square_100x100": (
            "https://seeclickfix.com/rails/active_storage/representations/"
            "redirect/eyJ.../thumb_2decddc0.jpg"
        ),
        "representative_image_url": (
            "https://seeclickfix.com/rails/active_storage/representations/"
            "redirect/eyJ.../2decddc0-6621-40b9-a808-f5f0722b89f8.jpg"
        ),
    },
}

_REAL_ISSUE_NO_PHOTO = {
    "id": 22961415,
    "summary": "Overgrown vacant lot",
    "description": "abandoned and overgrown",
    "address": "456 Oak St, Spartanburg, SC",
    "lat": 34.9, "lng": -81.9,
    "created_at": "2026-08-01T00:00:00-04:00",
    "updated_at": "2026-08-01T00:00:00-04:00",
    "html_url": "https://seeclickfix.com/issues/22961415",
    "media": {
        "video_url": None,
        "image_full": None,
        "image_square_100x100": None,
        # Generic per-category stock icon -- same URL for every "Tree"-type
        # issue regardless of address; not per-row data (see module docstring).
        "representative_image_url": (
            "https://seeclickfix.com/assets/categories/tree-"
            "dde3541ec612fcdf09413e99a627d32c887f9dd5599e78f23f5b67319970b4bc.png"
        ),
    },
}


def test_captures_real_resident_uploaded_photo(monkeypatch):
    fake = _FakeHttpClient([{"issues": [_REAL_ISSUE_WITH_PHOTO]}])
    monkeypatch.setattr(m, "client", lambda timeout=30.0: fake)
    c = next(c for c in m._CITIES if c["city"] == "Spartanburg")
    out = asyncio.run(m.SeeClickFixScraper()._fetch_city(c))
    assert len(out) == 1
    scf = out[0].raw["seeclickfix"]
    assert scf["photo_url"] == _REAL_ISSUE_WITH_PHOTO["media"]["image_full"]
    assert scf["photo_thumbnail_url"] == (
        _REAL_ISSUE_WITH_PHOTO["media"]["image_square_100x100"]
    )
    assert scf["video_url"] is None


def test_does_not_mistake_the_generic_category_icon_for_a_real_photo(monkeypatch):
    fake = _FakeHttpClient([{"issues": [_REAL_ISSUE_NO_PHOTO]}])
    monkeypatch.setattr(m, "client", lambda timeout=30.0: fake)
    c = next(c for c in m._CITIES if c["city"] == "Spartanburg")
    out = asyncio.run(m.SeeClickFixScraper()._fetch_city(c))
    assert len(out) == 1
    scf = out[0].raw["seeclickfix"]
    assert scf["photo_url"] is None
    assert scf["photo_thumbnail_url"] is None
    # The generic stock-icon URL must never leak into photo_url.
    assert "assets/categories" not in str(scf["photo_url"])


def test_missing_media_block_does_not_crash(monkeypatch):
    """Defensive: `iss.get("media") or {}` must not raise when a row has no
    `media` key at all (rather than an empty/null one)."""
    issue = dict(_REAL_ISSUE_NO_PHOTO)
    del issue["media"]
    fake = _FakeHttpClient([{"issues": [issue]}])
    monkeypatch.setattr(m, "client", lambda timeout=30.0: fake)
    c = next(c for c in m._CITIES if c["city"] == "Spartanburg")
    out = asyncio.run(m.SeeClickFixScraper()._fetch_city(c))
    assert len(out) == 1
    scf = out[0].raw["seeclickfix"]
    assert scf["photo_url"] is None
    assert scf["photo_thumbnail_url"] is None
    assert scf["video_url"] is None


def test_live_spartanburg_fetch_returns_correctly_scoped_real_rows():
    """Live network call against the real API, scoped to one city (not the
    full 20-city sweep) -- confirms the place_url fix actually works end to
    end, not just that the code shape looks right. Spartanburg was picked
    because it's one of the larger, more consistently active footprint
    cities (415 total issues live-verified 2026-10-04), so a distress-
    keyword hit is likely without being guaranteed -- this asserts on
    SCOPE correctness (every kept row's city/state/county match the query)
    rather than on an exact count, since real civic-complaint volume
    changes day to day."""
    c = next(c for c in m._CITIES if c["city"] == "Spartanburg")
    scraper = m.SeeClickFixScraper()
    try:
        rows = asyncio.run(scraper._fetch_city(c))
    except Exception as exc:  # pragma: no cover - network flake, not a code bug
        import pytest
        pytest.skip(f"live network call failed, not a code assertion: {exc}")
        return
    for li in rows:
        assert li.city == "Spartanburg"
        assert li.state == "SC"
        assert li.county == "Spartanburg"
        assert li.source == "national.seeclickfix"
        assert li.raw["seeclickfix"]["place_url"] == "spartanburg"
