"""Unit tests for the county-assessor photo enricher (pure logic, no network)."""
import asyncio
import time

import pytest

from foreclosure_scraper import enrichment_assessor_photo as m
from foreclosure_scraper.models import Listing, ListingType


def _li(**kw) -> Listing:
    base = dict(source="s", source_url="x", listing_type=ListingType.TAX_LIEN,
                state="NC", county="Buncombe", parcel_id="9639454911")
    base.update(kw)
    return Listing(**base)


# ---------------------------------------------------------------- slugs -----
def test_slug_matches_lrcpwa_convention():
    from foreclosure_scraper import enrichment_lrcpwa_photo as legacy
    assert m._slug("Henderson", "10007200") == legacy._slug("Henderson", "10007200")
    assert m._slug("Burke", "2772-57-7749") == "burke_2772577749.jpg"
    assert m._slug("Buncombe", "963945491100000") == "buncombe_963945491100000.jpg"


def test_county_name_normalizes():
    assert m._county_name(_li(county="buncombe county")) == "Buncombe"
    assert m._county_name(_li(county=None)) == ""


# ------------------------------------------------------- key derivation -----
def test_buncombe_pin_variants_pads_10_digit_to_15():
    assert m.buncombe_pin_variants("9639454911")[0] == "963945491100000"
    assert m.buncombe_pin_variants("963945491100000") == ["963945491100000"]
    assert m.buncombe_pin_variants("9639-45-4911")[0] == "963945491100000"
    assert m.buncombe_pin_variants("") == []
    assert m.buncombe_pin_variants(None) == []


def test_buncombe_pin_variants_keeps_raw_as_fallback():
    v = m.buncombe_pin_variants("96394549")
    assert v[-1] == "96394549"


# ------------------------------------------------------- URL selection ------
def test_pick_gaston_photo_prefers_asrimg_and_drops_cama_sketch():
    urls = ["https://gastonnc.devnetwedge.com/PropertyImages/CAMA/2027/140613-1.JPG",
            "https://gastonnc.devnetwedge.com/PropertyImages/ASRIMG/2026/2367104.JPG"]
    assert m.pick_gaston_photo(urls).endswith("2367104.JPG")
    # CAMA-only means sketch-only -> no photo
    assert m.pick_gaston_photo(urls[:1]) is None
    assert m.pick_gaston_photo([]) is None
    assert m.pick_gaston_photo([None, 123]) is None


def test_pick_ncpts_photo_ignores_sketch():
    urls = ["https://pwa.ncptscloud.com/Henderson/ImageResource.ashx?type=sketch&filepath=a.jpg",
            "https://pwa.ncptscloud.com/Henderson/ImageResource.ashx?type=photo&filepath=b.jpg"]
    assert m.pick_ncpts_photo(urls).endswith("b.jpg")
    assert m.pick_ncpts_photo(urls[:1]) is None


def test_lincoln_photo_names_drops_sentinel_and_dedupes():
    rows = [{"PRIMARYIMA": "images.gif", "IMAGE": "images.gif"},
            {"PRIMARYIMA": "20211108/100742AA.JPG"},
            {"PRIMARYIMA": " 20211108/100742AA.JPG "},
            {"PRIMARYIMA": None, "IMAGE": "20050223/31226AA.JPG"},
            {}]
    assert m.lincoln_photo_names(rows) == ["20211108/100742AA.JPG",
                                           "20050223/31226AA.JPG"]
    assert m.lincoln_photo_names([]) == []


# ------------------------------------------------------------ image sniff ---
def test_is_img():
    assert m._is_img(b"\xff\xd8\xff\xe0JFIF")
    assert m._is_img(b"\x89PNG\r\n\x1a\n")
    assert not m._is_img(b'{"error": 404}')
    assert not m._is_img(b"")
    assert not m._is_img(None)


# -------------------------------------------------------------- gating ------
def test_is_eligible():
    assert m.is_eligible(_li())
    # unsupported county
    assert not m.is_eligible(_li(county="Spartanburg", state="SC"))
    # no parcel key
    assert not m.is_eligible(_li(parcel_id=None))
    # already has a real photo
    got = _li()
    got.raw = {"images": {"real": ["parcel_photos/x.jpg"]}}
    assert not m.is_eligible(got)
    # aerial/street-only does NOT count as a real photo
    aerial = _li()
    aerial.raw = {"images": {"aerial": ["a.jpg"], "street": ["s.jpg"]}}
    assert m.is_eligible(aerial)


def test_select_targets_ranks_addressless_and_hot_first_within_a_county():
    cold = _li(parcel_id="1", street_address="1 MAIN ST")
    cold.raw = {"distress_stack": {"tier": "COLD", "score": 1}}
    hot_with_addr = _li(parcel_id="2", street_address="2 MAIN ST")
    hot_with_addr.raw = {"distress_stack": {"tier": "HOT", "score": 90}}
    no_addr = _li(parcel_id="3", street_address=None)
    no_addr.raw = {"distress_stack": {"tier": "COOL", "score": 5}}

    ranked = m.select_targets([cold, hot_with_addr, no_addr], cap=10)
    assert [li.parcel_id for li in ranked] == ["3", "2", "1"]
    assert len(m.select_targets([cold, hot_with_addr, no_addr], cap=2)) == 2
    assert m.select_targets([cold], cap=0) == []


def test_select_targets_stripes_across_counties_by_expected_yield():
    """A capped run must not be monopolized by one county. Lincoln holds most of
    the address-less leads; before striping it took 68% of a 1000-lead run while
    the ~2x-hit-rate Buncombe adapter starved."""
    leads = ([_li(county="Lincoln", parcel_id=f"L{i}", street_address=None)
              for i in range(100)]
             + [_li(county="Buncombe", parcel_id=f"B{i}",
                    street_address=f"{i} MAIN ST") for i in range(100)]
             + [_li(county="Henderson", parcel_id=f"H{i}") for i in range(2)])

    picked = m.select_targets(leads, cap=20)
    counts: dict[str, int] = {}
    for li in picked:
        counts[li.county] = counts.get(li.county, 0) + 1

    assert sum(counts.values()) == 20
    # The high-yield county wins the biggest share even though every one of its
    # leads HAS an address and every Lincoln lead does not.
    assert counts["Buncombe"] > counts["Lincoln"] > 0
    # ...and a tiny county is never crowded out entirely.
    assert counts["Henderson"] == 2
    # Share tracks the hit-rate ratio (0.90 vs 0.47), it is not winner-take-all.
    assert counts["Buncombe"] < 2.5 * counts["Lincoln"]


def test_select_targets_gives_leftover_slots_to_counties_with_leads_remaining():
    leads = ([_li(county="Buncombe", parcel_id=f"B{i}") for i in range(50)]
             + [_li(county="Henderson", parcel_id="H1")])
    picked = m.select_targets(leads, cap=30)
    assert len(picked) == 30
    assert sum(1 for li in picked if li.county == "Henderson") == 1


def test_rank_key_survives_garbage_score():
    li = _li()
    li.raw = {"distress_stack": {"tier": "HOT", "score": "not-a-number"},
              "grade": {"overall": None}}
    assert m._rank_key(li)[3] == 0


# ------------------------------------------------------------- side effects -
def test_set_image_writes_all_dashboard_aliases():
    li = _li()
    m._set_image(li, "buncombe_963945491100000.jpg", "buncombe_assessor_photo")
    rel = "parcel_photos/buncombe_963945491100000.jpg"
    assert li.raw["images"]["real"] == [rel]
    assert li.raw["images"]["primary"] == rel
    assert li.raw["images"]["source"] == "buncombe_assessor_photo"
    assert li.raw["zillow"]["photo"] == rel
    assert li.raw["assessor_photo"]["county"] == "Buncombe"


def test_set_image_promotes_primary_over_an_existing_aerial():
    """enrichment_images ranks primary real > street > aerial > map, so a real
    drive-by photo must REPLACE an aerial primary, not lose to setdefault."""
    li = _li()
    li.raw = {"images": {"aerial": "https://esri/tile.png", "map": "https://osm/m.png",
                         "primary": "https://esri/tile.png"}}
    m._set_image(li, "buncombe_x.jpg", "buncombe_assessor_photo")
    assert li.raw["images"]["primary"] == "parcel_photos/buncombe_x.jpg"
    assert li.raw["zillow"]["photo"] == "parcel_photos/buncombe_x.jpg"
    # the aerial is kept as a fallback, just demoted
    assert li.raw["images"]["aerial"] == "https://esri/tile.png"


def test_file_is_img_rejects_non_image_bytes(tmp_path):
    good = tmp_path / "good.jpg"
    good.write_bytes(b"\xff\xd8\xff\xe0stub")
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"<html>404 not found</html>")
    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"")
    assert m._file_is_img(good)
    assert not m._file_is_img(bad)
    assert not m._file_is_img(empty)
    assert not m._file_is_img(tmp_path / "missing.jpg")


def test_thumbnail_shrinks_and_returns_jpeg():
    from PIL import Image
    buf = __import__("io").BytesIO()
    Image.new("RGB", (2000, 1500), (10, 120, 200)).save(buf, "JPEG")
    out = m._thumbnail(buf.getvalue())
    assert out and out[:2] == b"\xff\xd8"
    assert max(Image.open(__import__("io").BytesIO(out)).size) <= m._thumb_px()
    assert m._thumbnail(b"not an image") is None


# --------------------------------------------------------------- driver -----
def test_driver_reuses_existing_file_without_fetching(tmp_path, monkeypatch):
    """A photo already on disk (e.g. from enrichment_lrcpwa_photo) must be
    re-wired, not re-downloaded."""
    li = _li(county="Henderson", parcel_id="10007200")
    (tmp_path / m._slug("Henderson", "10007200")).write_bytes(b"\xff\xd8\xff\xe0stub")

    called = []

    async def _boom(http, listing):
        called.append(listing)
        return None

    monkeypatch.setitem(m.ADAPTERS, ("NC", "Henderson"), (_boom, "ncpts_assessor_photo"))
    stats = asyncio.run(m.enrich_assessor_photo([li], photos_dir=tmp_path))
    assert stats["cached"] == 1 and stats["fetched"] == 0
    assert called == []
    assert li.raw["images"]["real"] == ["parcel_photos/henderson_10007200.jpg"]


def test_driver_writes_thumbnail_and_counts_no_photo(tmp_path, monkeypatch):
    from PIL import Image
    import io as _io
    buf = _io.BytesIO()
    Image.new("RGB", (1200, 900), (30, 90, 60)).save(buf, "JPEG")
    payload = buf.getvalue()

    hit = _li(parcel_id="9639454911")
    miss = _li(parcel_id="9639454912")

    async def _fake(http, listing):
        return payload if listing.parcel_id.endswith("1") else None

    monkeypatch.setitem(m.ADAPTERS, ("NC", "Buncombe"), (_fake, "buncombe_assessor_photo"))
    stats = asyncio.run(m.enrich_assessor_photo([hit, miss], photos_dir=tmp_path))
    assert stats["fetched"] == 1
    assert stats["no_photo"] == 1
    written = tmp_path / m._slug("Buncombe", "9639454911")
    assert written.exists() and 0 < written.stat().st_size < len(payload)
    assert hit.raw["images"]["real"] == [f"parcel_photos/{written.name}"]
    assert not (miss.raw or {}).get("images")
    assert stats["by_county"]["Buncombe"]["fetched"] == 1


def test_driver_one_bad_lead_never_kills_the_run(tmp_path, monkeypatch):
    from PIL import Image
    import io as _io
    buf = _io.BytesIO()
    Image.new("RGB", (400, 300), (200, 10, 10)).save(buf, "JPEG")
    payload = buf.getvalue()

    bad = _li(parcel_id="1")
    good = _li(parcel_id="2")

    async def _flaky(http, listing):
        if listing.parcel_id == "1":
            raise RuntimeError("adapter exploded")
        return payload

    monkeypatch.setitem(m.ADAPTERS, ("NC", "Buncombe"), (_flaky, "buncombe_assessor_photo"))
    stats = asyncio.run(m.enrich_assessor_photo([bad, good], photos_dir=tmp_path))
    assert stats["errors"] == 1
    assert stats["fetched"] == 1
    assert good.raw["images"]["real"]


def test_driver_respects_cap(tmp_path, monkeypatch):
    from PIL import Image
    import io as _io
    buf = _io.BytesIO()
    Image.new("RGB", (400, 300), (1, 2, 3)).save(buf, "JPEG")
    payload = buf.getvalue()

    leads = [_li(parcel_id=f"96394549{i:02d}") for i in range(5)]

    async def _always(http, listing):
        return payload

    monkeypatch.setitem(m.ADAPTERS, ("NC", "Buncombe"), (_always, "buncombe_assessor_photo"))
    stats = asyncio.run(m.enrich_assessor_photo(leads, photos_dir=tmp_path, cap=2))
    assert stats["eligible"] == 5
    assert stats["targets"] == 2
    assert stats["fetched"] == 2


def test_driver_refetches_when_cached_file_is_not_an_image(tmp_path, monkeypatch):
    """A non-empty file is NOT proof of a photo. A truncated download or an HTML
    error page must be re-fetched and overwritten, never wired up as the photo."""
    from PIL import Image
    import io as _io
    buf = _io.BytesIO()
    Image.new("RGB", (400, 300), (7, 7, 7)).save(buf, "JPEG")
    payload = buf.getvalue()

    li = _li(county="Henderson", parcel_id="10007200")
    poisoned = tmp_path / m._slug("Henderson", "10007200")
    poisoned.write_bytes(b"<html><body>Service Unavailable</body></html>")

    async def _fake(http, listing):
        return payload

    monkeypatch.setitem(m.ADAPTERS, ("NC", "Henderson"), (_fake, "ncpts_assessor_photo"))
    stats = asyncio.run(m.enrich_assessor_photo([li], photos_dir=tmp_path))
    assert stats["cached"] == 0 and stats["fetched"] == 1
    assert m._file_is_img(poisoned)
    assert li.raw["images"]["source"] == "ncpts_assessor_photo"


def test_driver_budget_zero_stops_before_any_fetch(tmp_path, monkeypatch):
    """Deterministic proof the deadline is live: with the budget already blown,
    not a single adapter call happens."""
    calls = []

    async def _never(http, listing):
        calls.append(listing.parcel_id)
        return None

    leads = [_li(parcel_id=f"96394549{i:02d}") for i in range(5)]
    monkeypatch.setitem(m.ADAPTERS, ("NC", "Buncombe"), (_never, "buncombe_assessor_photo"))
    stats = asyncio.run(m.enrich_assessor_photo(leads, photos_dir=tmp_path, budget_s=-1))
    assert calls == []
    assert stats["targets"] == 5
    assert stats["skipped_budget"] == 5
    assert stats["fetched"] == 0


def test_driver_tiny_budget_stops_the_run_early(tmp_path, monkeypatch):
    """A tiny budget must bound WALL CLOCK. The old check sat before the first
    await, so asyncio.gather evaluated it at t~0 for every lead and it could
    never fire; now it sits inside the semaphore, right before the fetch."""
    from PIL import Image
    import io as _io
    buf = _io.BytesIO()
    Image.new("RGB", (200, 150), (9, 9, 9)).save(buf, "JPEG")
    payload = buf.getvalue()

    calls = []

    async def _slow(http, listing):
        calls.append(listing.parcel_id)
        await asyncio.sleep(0.35)
        return payload

    n = m._concurrency() * 2
    leads = [_li(parcel_id=f"9639454{i:03d}") for i in range(n)]
    monkeypatch.setitem(m.ADAPTERS, ("NC", "Buncombe"), (_slow, "buncombe_assessor_photo"))
    stats = asyncio.run(m.enrich_assessor_photo(leads, photos_dir=tmp_path, budget_s=0.20))

    # the first concurrency-wide batch gets through; everything queued behind it
    # finds the deadline blown and bails instead of running to completion
    assert 0 < len(calls) < n
    assert stats["skipped_budget"] >= n - m._concurrency()
    assert stats["fetched"] + stats["skipped_budget"] + stats["no_photo"] == n


def test_driver_budget_cancels_an_in_flight_slow_fetch(tmp_path, monkeypatch):
    """The budget must bound WALL CLOCK, not just the start of new work: a fetch
    already in flight is capped at the remaining budget."""
    async def _hang(http, listing):
        await asyncio.sleep(30)
        return b"\xff\xd8never"

    leads = [_li(parcel_id=f"96394549{i:02d}") for i in range(3)]
    monkeypatch.setitem(m.ADAPTERS, ("NC", "Buncombe"), (_hang, "buncombe_assessor_photo"))
    t0 = time.monotonic()
    stats = asyncio.run(m.enrich_assessor_photo(leads, photos_dir=tmp_path, budget_s=0.4))
    elapsed = time.monotonic() - t0
    assert elapsed < 5, f"run did not honour the 0.4s budget: {elapsed:.1f}s"
    assert stats["skipped_budget"] == 3
    assert stats["fetched"] == 0 and stats["errors"] == 0


def test_env_knobs_are_read_at_call_time_not_import_time(tmp_path, monkeypatch):
    """The orchestrator sets these AFTER importing the module."""
    monkeypatch.setenv("ASSESSOR_PHOTO_THUMB", "64")
    monkeypatch.setenv("ASSESSOR_PHOTO_CONCURRENCY", "2")
    monkeypatch.setenv("ASSESSOR_PHOTO_BUDGET_S", "12.5")
    monkeypatch.setenv("ASSESSOR_PHOTO_MAX", "3")
    assert m._thumb_px() == 64
    assert m._concurrency() == 2
    assert m._budget_s() == 12.5
    assert m._max_leads() == 3

    async def _none(http, listing):
        return None

    leads = [_li(parcel_id=f"96394549{i:02d}") for i in range(5)]
    monkeypatch.setitem(m.ADAPTERS, ("NC", "Buncombe"), (_none, "buncombe_assessor_photo"))
    stats = asyncio.run(m.enrich_assessor_photo(leads, photos_dir=tmp_path))
    assert stats["eligible"] == 5 and stats["targets"] == 3


def test_env_knobs_fall_back_on_garbage(monkeypatch):
    monkeypatch.setenv("ASSESSOR_PHOTO_MAX", "not-a-number")
    monkeypatch.setenv("ASSESSOR_PHOTO_THUMB", "")
    monkeypatch.setenv("ASSESSOR_PHOTO_CONCURRENCY", "0")
    assert m._max_leads() == m._DEF_MAX
    assert m._thumb_px() == m._DEF_THUMB
    assert m._concurrency() == 1


def test_driver_noop_when_gated_off(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECLOSURE_ASSESSOR_PHOTO", "0")
    stats = asyncio.run(m.enrich_assessor_photo([_li()], photos_dir=tmp_path))
    assert stats["targets"] == 0 and stats["fetched"] == 0


def test_driver_skips_unsupported_counties(tmp_path):
    sp = _li(state="SC", county="Spartanburg", parcel_id="623094954074")
    stats = asyncio.run(m.enrich_assessor_photo([sp], photos_dir=tmp_path))
    assert stats["eligible"] == 0 and stats["targets"] == 0


@pytest.mark.parametrize("county", ["Buncombe", "Lincoln", "Gaston",
                                    "Rutherford", "Burke", "Madison", "Henderson"])
def test_every_registered_county_has_a_callable_adapter(county):
    fetch, label = m.ADAPTERS[("NC", county)]
    assert asyncio.iscoroutinefunction(fetch)
    assert label.endswith("_assessor_photo")
