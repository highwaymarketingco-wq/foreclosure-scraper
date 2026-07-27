"""Google Street View Static enricher — cost-safety tests.

This enricher spends real money, so the tests are written as spend guards, not
happy-path coverage. Every test asserts on the number of BILLED image calls.
No network: `client()` is replaced with a fake that records every request.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_streetview as sv
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

# A minimally-valid JPEG blob (magic bytes + enough length to clear _is_jpeg).
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 4096


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
_UNSET = object()


def _li(n: int = 0, addr=_UNSET, **kw) -> Listing:
    now = datetime.utcnow()
    base = dict(
        source="test",
        source_url=f"https://example.test/{n}",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY,
        street_address=f"{100 + n} Main St" if addr is _UNSET else addr,
        city="Asheville",
        state="NC",
        county="Buncombe",
        parcel_id=f"PID{n:05d}",
        first_seen=now,
        last_seen=now,
    )
    base.update(kw)
    return Listing(**base)


class _Resp:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeHTTP:
    """Records (url, params) for every request and answers from canned rules."""

    def __init__(self, meta_status="OK", image=JPEG, image_status=200):
        self.calls: list[tuple[str, dict]] = []
        self.meta_status = meta_status
        self.image = image
        self.image_status = image_status

    @property
    def metadata_calls(self):
        return [c for c in self.calls if c[0] == sv.METADATA_URL]

    @property
    def image_calls(self):
        return [c for c in self.calls if c[0] == sv.IMAGE_URL]

    async def get(self, url, params=None, timeout=None, **kw):
        self.calls.append((url, dict(params or {})))
        if url == sv.METADATA_URL:
            status = (self.meta_status(len(self.metadata_calls))
                      if callable(self.meta_status) else self.meta_status)
            return _Resp(200, {
                "status": status,
                "pano_id": f"PANO{len(self.metadata_calls)}",
                "date": "2025-04",
                "location": {"lat": 35.6, "lng": -82.5},
                "copyright": "© Google",
            })
        return _Resp(self.image_status, None, self.image)


class _NoNetHTTP:
    """Any request at all is a test failure."""

    async def get(self, *a, **kw):  # noqa: D102
        raise AssertionError("HTTP request made when none was allowed")


def _install(monkeypatch, http):
    """Swap the shared async http client for `http`."""
    class _CM:
        async def __aenter__(self):
            return http

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(sv, "client", lambda **kw: _CM())
    return http


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Enabled + keyed + isolated counter/photo dirs. Tests opt out as needed."""
    monkeypatch.setenv("FORECLOSURE_STREETVIEW", "1")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "TEST-KEY-NOT-REAL")
    monkeypatch.setenv("STREETVIEW_COUNTER_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setenv("STREETVIEW_KEY_FILE", str(tmp_path / "nope.txt"))
    monkeypatch.delenv("STREETVIEW_DRY_RUN", raising=False)
    monkeypatch.delenv("STREETVIEW_ALLOW_PAID", raising=False)
    monkeypatch.delenv("GOOGLE_STREETVIEW_API_KEY", raising=False)
    return tmp_path


def _run(listings, photos_dir):
    return asyncio.run(sv.enrich_streetview(listings, photos_dir=photos_dir))


# --------------------------------------------------------------------------- #
# 1. OFF by default / no key -> hard no-op, zero requests
# --------------------------------------------------------------------------- #
def test_disabled_by_default_makes_no_calls(monkeypatch, tmp_path):
    monkeypatch.delenv("FORECLOSURE_STREETVIEW", raising=False)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "TEST-KEY-NOT-REAL")
    monkeypatch.setenv("STREETVIEW_COUNTER_FILE", str(tmp_path / "usage.json"))
    _install(monkeypatch, _NoNetHTTP())

    leads = [_li(i) for i in range(5)]
    stats = _run(leads, tmp_path / "photos")

    assert stats["enabled"] is False
    assert stats["billed_image_calls"] == 0
    assert not (tmp_path / "usage.json").exists()
    assert all(not (li.raw.get("images") or {}).get("street") for li in leads)


def test_no_key_is_clean_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("FORECLOSURE_STREETVIEW", "1")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_STREETVIEW_API_KEY", raising=False)
    monkeypatch.setenv("STREETVIEW_KEY_FILE", str(tmp_path / "absent_key.txt"))
    monkeypatch.setenv("STREETVIEW_COUNTER_FILE", str(tmp_path / "usage.json"))
    _install(monkeypatch, _NoNetHTTP())

    stats = _run([_li(i) for i in range(5)], tmp_path / "photos")

    assert stats["enabled"] is False
    assert stats["billed_image_calls"] == 0
    assert stats["metadata_calls"] == 0


def test_key_read_from_secrets_file(monkeypatch, tmp_path):
    monkeypatch.setenv("FORECLOSURE_STREETVIEW", "1")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_STREETVIEW_API_KEY", raising=False)
    kf = tmp_path / "google_maps_api_key.txt"
    kf.write_text("  FILE-KEY-NOT-REAL \n")
    monkeypatch.setenv("STREETVIEW_KEY_FILE", str(kf))
    monkeypatch.setenv("STREETVIEW_COUNTER_FILE", str(tmp_path / "usage.json"))
    http = _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(0)], tmp_path / "photos")

    assert stats["attached"] == 1
    assert http.metadata_calls[0][1]["key"] == "FILE-KEY-NOT-REAL"


# --------------------------------------------------------------------------- #
# 2. metadata (free) always precedes the billed image call
# --------------------------------------------------------------------------- #
def test_metadata_called_before_image(env, monkeypatch):
    http = _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(0)], env / "photos")

    assert [c[0] for c in http.calls] == [sv.METADATA_URL, sv.IMAGE_URL]
    assert stats["metadata_calls"] == 1
    assert stats["billed_image_calls"] == 1
    # the image call reuses the pano the metadata probe validated
    assert http.image_calls[0][1]["pano"] == "PANO1"


def test_zero_results_metadata_spends_nothing(env, monkeypatch):
    http = _install(monkeypatch, _FakeHTTP(meta_status="ZERO_RESULTS"))

    leads = [_li(i) for i in range(6)]
    stats = _run(leads, env / "photos")

    assert stats["metadata_calls"] == 6
    assert stats["no_imagery"] == 6
    assert stats["billed_image_calls"] == 0
    assert http.image_calls == []
    assert json.loads((env / "usage.json").read_text())["billed_image_calls"] == 0


def test_mixed_coverage_only_bills_where_imagery_exists(env, monkeypatch):
    # every other lead has no panorama
    http = _install(monkeypatch, _FakeHTTP(
        meta_status=lambda n: "OK" if n % 2 == 1 else "ZERO_RESULTS"))
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")

    stats = _run([_li(i) for i in range(6)], env / "photos")

    assert stats["metadata_calls"] == 6
    assert stats["billed_image_calls"] == 3
    assert len(http.image_calls) == 3


def test_dry_run_never_bills(env, monkeypatch):
    monkeypatch.setenv("STREETVIEW_DRY_RUN", "1")
    http = _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(i) for i in range(4)], env / "photos")

    assert stats["metadata_ok"] == 4
    assert stats["billed_image_calls"] == 0
    assert http.image_calls == []


# --------------------------------------------------------------------------- #
# 3. budget caps
# --------------------------------------------------------------------------- #
def test_per_run_cap_is_hard(env, monkeypatch):
    monkeypatch.setenv("STREETVIEW_MAX", "3")
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")
    http = _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(i) for i in range(25)], env / "photos")

    assert stats["billed_image_calls"] == 3
    assert len(http.image_calls) == 3
    assert stats["attached"] == 3
    assert stats["skipped_run_cap"] >= 1


def test_run_cap_zero_spends_nothing(env, monkeypatch):
    monkeypatch.setenv("STREETVIEW_MAX", "0")
    http = _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(i) for i in range(10)], env / "photos")

    assert stats["billed_image_calls"] == 0
    assert http.image_calls == []


def test_monthly_counter_persists_across_runs(env, monkeypatch):
    """The whole point: run N+1 cannot re-spend run N's budget."""
    monkeypatch.setenv("STREETVIEW_MAX", "2")
    monkeypatch.setenv("STREETVIEW_MONTHLY_MAX", "3")
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")

    http1 = _install(monkeypatch, _FakeHTTP())
    s1 = _run([_li(i) for i in range(10)], env / "photos")
    assert s1["billed_image_calls"] == 2

    # fresh leads + fresh photo dir so nothing is served from the disk cache
    http2 = _install(monkeypatch, _FakeHTTP())
    s2 = _run([_li(100 + i) for i in range(10)], env / "photos2")

    assert s2["billed_image_calls"] == 1        # only 1 left in the month
    assert s2["skipped_month_cap"] >= 1
    assert len(http2.image_calls) == 1
    ledger = json.loads((env / "usage.json").read_text())
    assert ledger["billed_image_calls"] == 3
    assert ledger["month"] == sv._month_key()
    assert len(http1.image_calls) == 2

    # a third run gets nothing at all
    http3 = _install(monkeypatch, _FakeHTTP())
    s3 = _run([_li(200 + i) for i in range(5)], env / "photos3")
    assert s3["billed_image_calls"] == 0
    assert http3.image_calls == []


def test_monthly_cap_clamped_under_free_tier(env, monkeypatch):
    """An operator typo (or an over-eager env) cannot cross into billing."""
    monkeypatch.setenv("STREETVIEW_MONTHLY_MAX", "5000000")
    monkeypatch.setenv("STREETVIEW_MAX", "1")
    _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(0)], env / "photos")

    assert stats["monthly_cap"] == sv.FREE_TIER_GUARD
    assert stats["monthly_cap"] < sv.FREE_TIER_MONTHLY


def test_prior_month_ledger_does_not_block_this_month(env, monkeypatch):
    (env / "usage.json").write_text(json.dumps(
        {"month": "1999-01", "billed_image_calls": 999999}))
    monkeypatch.setenv("STREETVIEW_MAX", "1")
    _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(0)], env / "photos")

    assert stats["billed_image_calls"] == 1
    assert json.loads((env / "usage.json").read_text())["month"] == sv._month_key()


def test_unwritable_ledger_refuses_to_spend(env, monkeypatch):
    # counter path points at a directory -> writes must fail
    bad = env / "counter_dir"
    bad.mkdir()
    monkeypatch.setenv("STREETVIEW_COUNTER_FILE", str(bad))
    http = _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(i) for i in range(4)], env / "photos")

    assert stats["billed_image_calls"] == 0
    assert http.image_calls == []


def test_wall_clock_budget_zero_bails(env, monkeypatch):
    monkeypatch.setenv("STREETVIEW_BUDGET_S", "0")
    http = _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(i) for i in range(10)], env / "photos")

    assert stats["billed_image_calls"] == 0
    assert stats["budget_hit"] == 1
    assert http.calls == []


def test_disk_cache_costs_nothing_on_rerun(env, monkeypatch):
    monkeypatch.setenv("STREETVIEW_MAX", "5")
    pdir = env / "photos"
    http1 = _install(monkeypatch, _FakeHTTP())
    leads = [_li(i) for i in range(3)]
    s1 = _run(leads, pdir)
    assert s1["billed_image_calls"] == 3

    http2 = _install(monkeypatch, _FakeHTTP())
    leads2 = [_li(i) for i in range(3)]     # same properties, new objects
    s2 = _run(leads2, pdir)

    assert s2["cached"] == 3
    assert s2["billed_image_calls"] == 0
    assert http2.calls == []
    assert leads2[0].raw["images"]["street"].startswith("parcel_photos/streetview/")
    assert len(http1.image_calls) == 3


# --------------------------------------------------------------------------- #
# 4. target selection
# --------------------------------------------------------------------------- #
def test_skips_leads_without_valid_address(env, monkeypatch):
    http = _install(monkeypatch, _FakeHTTP())
    leads = [
        _li(0, addr=None),
        _li(1, addr=""),
        _li(2, addr="Lis Pendens - Tract 4"),
        _li(3, addr="123 Real St"),
    ]
    stats = _run(leads, env / "photos")

    assert stats["targets"] == 1
    assert stats["billed_image_calls"] == 1
    assert len(http.image_calls) == 1
    assert (leads[3].raw.get("images") or {}).get("street")
    assert not (leads[0].raw.get("images") or {}).get("street")


def test_skips_leads_that_already_have_a_photo(env, monkeypatch):
    _install(monkeypatch, _FakeHTTP())
    have_real = _li(0)
    have_real.raw = {"images": {"real": ["https://cdn/photo.jpg"], "primary": "https://cdn/photo.jpg"}}
    have_street = _li(1)
    have_street.raw = {"images": {"street": "https://mapillary/x.jpg"}}
    bare = _li(2)

    stats = _run([have_real, have_street, bare], env / "photos")

    assert stats["targets"] == 1
    assert stats["billed_image_calls"] == 1
    assert have_real.raw["images"]["primary"] == "https://cdn/photo.jpg"
    assert have_street.raw["images"]["street"] == "https://mapillary/x.jpg"


def test_ambiguous_address_without_geo_is_skipped(env, monkeypatch):
    """No lat/lng and no city/zip -> a same-named street elsewhere could match."""
    _install(monkeypatch, _FakeHTTP())
    li = _li(0, city=None, zip_code=None)
    stats = _run([li], env / "photos")
    assert stats["targets"] == 0


def test_uses_latlng_when_available(env, monkeypatch):
    http = _install(monkeypatch, _FakeHTTP())
    li = _li(0, latitude=35.5951, longitude=-82.5515)
    _run([li], env / "photos")
    assert http.metadata_calls[0][1]["location"] == "35.595100,-82.551500"


def test_hot_leads_get_the_budget_first(env, monkeypatch):
    monkeypatch.setenv("STREETVIEW_MAX", "1")
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")
    _install(monkeypatch, _FakeHTTP())

    cold = _li(0)
    hot = _li(1)
    hot.raw = {"distress_stack": {"tier": "HOT"}, "grade": {"overall": "A"}}

    stats = _run([cold, hot], env / "photos")

    assert stats["billed_image_calls"] == 1
    assert (hot.raw.get("images") or {}).get("street")
    assert not (cold.raw.get("images") or {}).get("street")


# --------------------------------------------------------------------------- #
# 5. image attachment + primary priority (must match enrichment_images)
# --------------------------------------------------------------------------- #
def test_street_becomes_primary_over_aerial_and_map(env, monkeypatch):
    _install(monkeypatch, _FakeHTTP())
    li = _li(0)
    li.raw = {
        "images": {"aerial": "https://esri/tile", "map": "https://osm/map",
                   "primary": "https://esri/tile"},
        "zillow": {"photo": "https://esri/tile"},
    }
    _run([li], env / "photos")

    images = li.raw["images"]
    assert images["street"].startswith("parcel_photos/streetview/")
    assert images["primary"] == images["street"]     # street beats aerial + map
    assert images["aerial"] == "https://esri/tile"   # untouched
    assert li.raw["zillow"]["photo"] == images["street"]
    assert images["street_source"] == "google_streetview"


def test_real_photo_still_outranks_street(env, monkeypatch):
    """A lead that acquires a real photo mid-pipeline keeps it as primary."""
    _install(monkeypatch, _FakeHTTP())
    li = _li(0)
    li.raw = {"images": {}, "zillow": {"photo": "https://cdn/real.jpg"}}
    sv._attach(li, "parcel_photos/streetview/x.jpg", {"pano_id": "P"}, "q")
    assert li.raw["images"]["primary"] == "parcel_photos/streetview/x.jpg"

    li.raw["images"]["real"] = ["https://cdn/real.jpg"]
    sv._attach(li, "parcel_photos/streetview/x.jpg", {"pano_id": "P"}, "q")
    assert li.raw["images"]["primary"] == "https://cdn/real.jpg"
    assert li.raw["zillow"]["photo"] == "https://cdn/real.jpg"


def test_provenance_recorded(env, monkeypatch):
    _install(monkeypatch, _FakeHTTP())
    li = _li(0)
    _run([li], env / "photos")

    prov = li.raw["images"]["streetview"]
    assert prov["provider"] == "google_streetview"
    assert prov["pano_id"] == "PANO1"
    assert prov["capture_date"] == "2025-04"
    assert prov["attribution"] == "© Google"
    assert prov["local_path"] == li.raw["images"]["street"]


def test_photo_written_to_disk_and_url_carries_no_api_key(env, monkeypatch):
    """The published path must never leak the billable key."""
    _install(monkeypatch, _FakeHTTP())
    li = _li(0)
    _run([li], env / "photos")

    rel = li.raw["images"]["street"]
    on_disk = env / "photos" / Path(rel).name
    assert on_disk.exists() and on_disk.stat().st_size > 0
    blob = json.dumps(li.raw)
    assert "TEST-KEY-NOT-REAL" not in blob
    assert "maps.googleapis.com" not in rel


def test_non_image_response_does_not_attach(env, monkeypatch):
    http = _install(monkeypatch, _FakeHTTP(image=b"<html>error</html>"))
    li = _li(0)
    stats = _run([li], env / "photos")

    assert stats["billed_image_calls"] == 1   # charge-on-attempt: still counted
    assert stats["attached"] == 0
    assert stats["errors"] == 1
    assert not (li.raw.get("images") or {}).get("street")
    assert len(http.image_calls) == 1


def test_cache_reattach_keeps_original_provenance(env, monkeypatch):
    pdir = env / "photos"
    _install(monkeypatch, _FakeHTTP())
    li = _li(0)
    _run([li], pdir)
    original = dict(li.raw["images"]["streetview"])
    assert original["pano_id"] == "PANO1"

    # same property, board reloaded without the images blob -> cache path
    again = _li(0)
    _install(monkeypatch, _NoNetHTTP())
    again.raw = {"images": {"streetview": original}}
    _run([again], pdir)

    assert again.raw["images"]["streetview"]["pano_id"] == "PANO1"
    assert again.raw["images"]["streetview"]["capture_date"] == "2025-04"
    assert "reattached_from_cache_at" in again.raw["images"]["streetview"]


def test_cost_estimate_is_zero_inside_free_tier(env, monkeypatch):
    _install(monkeypatch, _FakeHTTP())
    stats = _run([_li(0)], env / "photos")
    assert stats["est_cost_usd_this_run"] == 0.0
    assert stats["est_cost_usd_month"] == 0.0


def test_cost_estimate_counts_only_calls_above_free_tier(env, monkeypatch):
    """With the paid opt-in, the $ figure must reflect real overage."""
    (env / "usage.json").write_text(json.dumps({
        "month": sv._month_key(), "billed_image_calls": sv.FREE_TIER_MONTHLY - 1}))
    monkeypatch.setenv("STREETVIEW_ALLOW_PAID", "1")
    monkeypatch.setenv("STREETVIEW_MONTHLY_MAX", "20000")
    monkeypatch.setenv("STREETVIEW_MAX", "3")
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")
    _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(i) for i in range(5)], env / "photos")

    assert stats["billed_image_calls"] == 3
    assert stats["month_billed_total"] == sv.FREE_TIER_MONTHLY + 2
    # 1 of the 3 was the last free call; 2 were billable
    assert stats["est_cost_usd_this_run"] == round(2 * sv.PAID_PER_1000_USD / 1000, 2)
    assert stats["est_cost_usd_month"] == round(2 * sv.PAID_PER_1000_USD / 1000, 2)


def test_one_bad_lead_does_not_kill_the_run(env, monkeypatch):
    calls = {"n": 0}

    class _Flaky(_FakeHTTP):
        async def get(self, url, params=None, timeout=None, **kw):
            if url == sv.METADATA_URL:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("boom")
            return await super().get(url, params=params, timeout=timeout, **kw)

    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")
    _install(monkeypatch, _Flaky())

    stats = _run([_li(i) for i in range(4)], env / "photos")

    assert stats["errors"] == 1
    assert stats["attached"] == 3


# --------------------------------------------------------------------------- #
# 6. malformed raw shapes (string where a nested dict is expected)
#    Real board data carries raw['grade'] == 'A' and raw['images'] == '' —
#    `(x or {}).get(...)` on those is an AttributeError that used to escape
#    _priority/_needs_street_photo and kill the whole enricher.
# --------------------------------------------------------------------------- #
def test_priority_tolerates_string_nesting():
    li = _li(0)
    li.raw = {"distress_stack": "HOT", "grade": "A", "images": "nope"}
    assert isinstance(sv._priority(li), int)

    li2 = _li(1)
    li2.raw = {"distress_stack": ["HOT"], "grade": 3, "images": ["x"]}
    assert isinstance(sv._priority(li2), int)

    li3 = _li(2)
    li3.raw = "not a dict at all"
    assert sv._priority(li3) == 0


def test_needs_street_photo_tolerates_string_images():
    li = _li(0)
    li.raw = {"images": "parcel_photos/whatever.jpg"}
    assert sv._needs_street_photo(li) is True          # unusable => no photo

    li2 = _li(1)
    li2.raw = {"images": ["a", "b"]}
    assert sv._needs_street_photo(li2) is True

    li3 = _li(2)
    li3.raw = None
    assert sv._needs_street_photo(li3) is True

    li4 = _li(3)
    li4.raw = {"images": {"street": "https://mapillary/x.jpg"}}
    assert sv._needs_street_photo(li4) is False


def test_targets_survives_malformed_leads():
    leads = [_li(0), _li(1), _li(2)]
    leads[0].raw = {"distress_stack": "HOT", "grade": "A", "images": "nope"}
    leads[1].raw = "not a dict at all"
    out = sv._targets(leads)
    assert len(out) == 3


def test_string_shaped_raw_does_not_crash_the_run(env, monkeypatch):
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")
    http = _install(monkeypatch, _FakeHTTP())

    bad = _li(0)
    bad.raw = {"distress_stack": "HOT", "grade": "A",
               "images": "nope", "zillow": "not-a-dict"}
    good = _li(1)

    stats = _run([bad, good], env / "photos")

    assert stats["targets"] == 2
    assert stats["attached"] == 2
    assert stats["errors"] == 0
    assert len(http.image_calls) == 2
    assert bad.raw["images"]["street"].startswith("parcel_photos/streetview/")
    # a non-dict zillow blob is left exactly as found, never clobbered
    assert bad.raw["zillow"] == "not-a-dict"


# --------------------------------------------------------------------------- #
# 7. the counter path must be absolute — a relative one silently resets the
#    monthly spend fence whenever the process starts from another cwd
# --------------------------------------------------------------------------- #
def test_default_counter_path_is_absolute(monkeypatch):
    monkeypatch.delenv("STREETVIEW_COUNTER_FILE", raising=False)
    monkeypatch.delenv("STREETVIEW_KEY_FILE", raising=False)
    assert Path(sv._DEFAULT_COUNTER).is_absolute()
    cfg = sv._Config()
    assert cfg.counter_path.is_absolute()
    assert cfg.key_file.is_absolute()


def test_counter_path_is_cwd_independent(monkeypatch, tmp_path):
    monkeypatch.delenv("STREETVIEW_COUNTER_FILE", raising=False)
    here = sv._Config().counter_path
    monkeypatch.chdir(tmp_path)
    assert sv._Config().counter_path == here

    # an operator-supplied RELATIVE path is anchored at the repo too
    monkeypatch.setenv("STREETVIEW_COUNTER_FILE", "data/custom_usage.json")
    assert sv._Config().counter_path == sv._REPO_ROOT / "data" / "custom_usage.json"


# --------------------------------------------------------------------------- #
# 8. cross-process safety — two overlapping runs share ONE month budget
# --------------------------------------------------------------------------- #
def test_concurrent_process_spend_is_seen_mid_run(env, monkeypatch):
    """Another process spends the month out while we are running.

    The ledger re-reads the on-disk total inside the lock before every
    reservation, so we must stop instead of spending against our stale copy.
    """
    monkeypatch.setenv("STREETVIEW_MAX", "10")
    monkeypatch.setenv("STREETVIEW_MONTHLY_MAX", "10")
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")

    counter = env / "usage.json"

    class _OtherProcess(_FakeHTTP):
        async def get(self, url, params=None, timeout=None, **kw):
            resp = await super().get(url, params=params, timeout=timeout, **kw)
            if url == sv.IMAGE_URL:
                # a second run drains the month between our reservations
                counter.write_text(json.dumps({
                    "month": sv._month_key(), "billed_image_calls": 10,
                    "metadata_calls": 0}))
            return resp

    http = _install(monkeypatch, _OtherProcess())
    stats = _run([_li(i) for i in range(8)], env / "photos")

    assert stats["billed_image_calls"] == 1
    assert len(http.image_calls) == 1
    assert stats["skipped_month_cap"] >= 1
    assert json.loads(counter.read_text())["billed_image_calls"] == 10


def test_stale_lower_counter_cannot_hand_budget_back(env, monkeypatch):
    """A truncated/rolled-back counter file must not resurrect spent budget."""
    monkeypatch.setenv("STREETVIEW_MAX", "5")
    monkeypatch.setenv("STREETVIEW_MONTHLY_MAX", "2")
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")
    counter = env / "usage.json"

    class _Rollback(_FakeHTTP):
        async def get(self, url, params=None, timeout=None, **kw):
            resp = await super().get(url, params=params, timeout=timeout, **kw)
            if url == sv.IMAGE_URL:
                counter.write_text(json.dumps({
                    "month": sv._month_key(), "billed_image_calls": 0}))
            return resp

    http = _install(monkeypatch, _Rollback())
    stats = _run([_li(i) for i in range(6)], env / "photos")

    assert stats["billed_image_calls"] == 2      # month cap, not 6
    assert len(http.image_calls) == 2


def test_lock_held_elsewhere_refuses_to_spend(env, monkeypatch):
    """If the inter-process lock can't be taken, we do not spend. Ever."""
    fcntl = pytest.importorskip("fcntl")
    monkeypatch.setenv("STREETVIEW_LOCK_TIMEOUT_S", "0")
    lock_path = env / "usage.json.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        http = _install(monkeypatch, _FakeHTTP())
        stats = _run([_li(i) for i in range(4)], env / "photos")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    assert stats["billed_image_calls"] == 0
    assert http.calls == []          # aborted before any request went out


def test_lock_is_released_between_runs(env, monkeypatch):
    """Two sequential runs must both be able to take the lock."""
    monkeypatch.setenv("STREETVIEW_MAX", "5")
    _install(monkeypatch, _FakeHTTP())
    s1 = _run([_li(0)], env / "photos")
    _install(monkeypatch, _FakeHTTP())
    s2 = _run([_li(50)], env / "photos")

    assert s1["billed_image_calls"] == 1
    assert s2["billed_image_calls"] == 1
    assert (env / "usage.json.lock").exists()


# --------------------------------------------------------------------------- #
# 9. metadata accounting: per-run cap enforced, monthly only when configured,
#    and no disk write per free probe
# --------------------------------------------------------------------------- #
def test_metadata_cap_scales_to_zero_with_run_cap(monkeypatch):
    monkeypatch.delenv("STREETVIEW_METADATA_MAX", raising=False)
    monkeypatch.setenv("STREETVIEW_MAX", "0")
    assert sv._Config().metadata_cap == 0
    monkeypatch.setenv("STREETVIEW_MAX", "7")
    assert sv._Config().metadata_cap == 28


def test_run_cap_zero_makes_no_requests_at_all(env, monkeypatch):
    monkeypatch.setenv("STREETVIEW_MAX", "0")
    http = _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(i) for i in range(10)], env / "photos")

    assert stats["billed_image_calls"] == 0
    assert stats["metadata_calls"] == 0
    assert http.calls == []


def test_monthly_metadata_cap_enforced_when_set(env, monkeypatch):
    monkeypatch.setenv("STREETVIEW_DRY_RUN", "1")
    monkeypatch.setenv("STREETVIEW_METADATA_MONTHLY_MAX", "2")
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")

    http1 = _install(monkeypatch, _FakeHTTP())
    s1 = _run([_li(i) for i in range(5)], env / "photos")
    assert s1["metadata_calls"] == 2
    assert len(http1.metadata_calls) == 2
    assert json.loads((env / "usage.json").read_text())["metadata_calls"] == 2

    # the monthly total persisted, so a second run gets nothing
    http2 = _install(monkeypatch, _FakeHTTP())
    s2 = _run([_li(100 + i) for i in range(5)], env / "photos2")
    assert s2["metadata_calls"] == 0
    assert http2.calls == []


def test_monthly_metadata_recorded_but_not_capped_by_default(env, monkeypatch):
    """Default 0 == not enforced, and the file says so rather than pretending."""
    monkeypatch.setenv("STREETVIEW_DRY_RUN", "1")
    monkeypatch.delenv("STREETVIEW_METADATA_MONTHLY_MAX", raising=False)

    _install(monkeypatch, _FakeHTTP())
    s1 = _run([_li(i) for i in range(4)], env / "photos")
    _install(monkeypatch, _FakeHTTP())
    s2 = _run([_li(100 + i) for i in range(4)], env / "photos2")

    assert s1["metadata_calls"] == 4
    assert s2["metadata_calls"] == 4
    led = json.loads((env / "usage.json").read_text())
    assert led["metadata_calls"] == 8          # recorded across runs
    assert led["metadata_monthly_cap"] == 0    # honestly labelled unenforced


def test_metadata_probe_does_not_write_the_ledger_every_lead(env, monkeypatch):
    """~12,900 probes/run must not mean ~12,900 JSON writes."""
    monkeypatch.setenv("STREETVIEW_DRY_RUN", "1")
    flushes = {"n": 0}
    original = sv._Ledger._flush

    def counting(self):
        flushes["n"] += 1
        return original(self)

    monkeypatch.setattr(sv._Ledger, "_flush", counting)
    _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(i) for i in range(12)], env / "photos")

    assert stats["metadata_calls"] == 12
    assert flushes["n"] <= 2       # preflight + one finalize, not one per lead
    assert json.loads((env / "usage.json").read_text())["metadata_calls"] == 12


def test_billed_calls_still_flush_every_time(env, monkeypatch):
    """The money counter keeps its charge-on-attempt write per call."""
    monkeypatch.setenv("STREETVIEW_MAX", "3")
    monkeypatch.setenv("STREETVIEW_CONCURRENCY", "1")
    writes = []
    original = sv._Ledger._flush

    def recording(self):
        ok = original(self)
        writes.append(self.month_billed)
        return ok

    monkeypatch.setattr(sv._Ledger, "_flush", recording)
    _install(monkeypatch, _FakeHTTP())

    stats = _run([_li(i) for i in range(3)], env / "photos")

    assert stats["billed_image_calls"] == 3
    # every billed reservation persisted its own increment before spending
    assert writes.count(1) == 1 and writes.count(2) == 1 and writes.count(3) == 1
    assert json.loads((env / "usage.json").read_text())["billed_image_calls"] == 3
