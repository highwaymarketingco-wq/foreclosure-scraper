"""Vision: dashboard-hosted relative photo paths are read, and the processed-documents ledger
around the pass (2026-10-09 documents_images audit). Made-up rows; no network."""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper import doc_inventory as inv
from foreclosure_scraper import doc_ledger as dl
from foreclosure_scraper import enrichment_vision as V
from foreclosure_scraper.models import Listing


def _li(images: dict, **raw) -> Listing:
    li = Listing(source="test.src", source_url="https://example.test/x", state="NC",
                 county="Testcounty")
    li.raw = {"images": images, **raw}
    return li


@pytest.fixture
def ledger_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC_LEDGER_DIR", str(tmp_path / "led"))
    monkeypatch.setenv("DOC_LEDGER_PRIVATE_DIR", str(tmp_path / "priv"))
    dl.reset_cache()
    yield tmp_path
    dl.reset_cache()


def test_a_relative_parcel_photo_is_read_from_docs(tmp_path, monkeypatch):
    """2,908 rows of the 10/7 board had only parcel_photos/... images; every one 'failed to
    download', and the fetch-failing breaker stopped the whole vision pass within minutes."""
    from PIL import Image
    docs = tmp_path / "docs"
    (docs / "parcel_photos").mkdir(parents=True)
    Image.new("RGB", (8, 8), "red").save(docs / "parcel_photos" / "test_1.jpg", "JPEG")
    monkeypatch.setattr(V, "_DOCS_DIR", docs)

    class NoNet:
        async def get(self, *a, **kw):
            raise AssertionError("a local photo must not be fetched over the network")

    got = asyncio.run(V._fetch_image_bytes(NoNet(), "parcel_photos/test_1.jpg"))
    assert got is not None and got[1] == "image/jpeg" and got[0][:2] == b"\xff\xd8"


def test_a_missing_relative_photo_is_fetched_from_the_published_site(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "_DOCS_DIR", tmp_path)
    monkeypatch.setattr(V, "_PAGES_BASE", "https://site.example.test/board/")
    asked = []

    class R:
        status_code = 200
        headers = {"content-type": "image/jpeg"}
        content = b"\xff\xd8\xff" + b"0" * 10

    class Net:
        async def get(self, url, **kw):
            asked.append(url)
            return R()

    got = asyncio.run(V._fetch_image_bytes(Net(), "parcel_photos/none.jpg"))
    assert asked == ["https://site.example.test/board/parcel_photos/none.jpg"] and got


def test_an_html_page_is_not_a_photo():
    class R:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        content = b"<html>not found</html>"

    class Net:
        async def get(self, url, **kw):
            return R()

    assert asyncio.run(V._fetch_image_bytes(Net(), "https://img.example.test/a.jpg")) is None


def test_a_path_outside_docs_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "_DOCS_DIR", tmp_path)
    assert V._local_image("../secrets/x.jpg") is None


def test_ledger_records_each_outcome_and_skips_an_ungraded_set(ledger_dir, monkeypatch):
    graded = _li({"real": ["https://img.example.test/g.jpg"]}, distress_stack={"tier": "WARM"})
    ungraded = _li({"real": ["https://img.example.test/u.jpg"]})
    failed = _li({"real": ["https://img.example.test/f.jpg"]})
    sent = []

    async def fake_impl(listings, max_listings=None):
        for li in listings:
            if not V._needs_vision(li):
                continue
            sent.append(li.raw["images"]["real"][0])
            if li is graded:
                li.raw["vision"] = {"condition_tier": "major", "confidence": "HIGH",
                                    "_provider": "fake", "_n_photos": 1}
                li.raw["condition_source"] = "vision-HIGH"
            elif li is ungraded:
                li.raw["vision_unscored"] = {"condition_tier": None}
            else:
                V._mark_fetch_failed(li, V._select_image_urls(li))

    monkeypatch.setattr(V, "_enrich_with_vision_impl", fake_impl)
    asyncio.run(V.enrich_with_vision([graded, ungraded, failed]))
    led = dl.DocLedger.load("vision")
    out = {k: e["outcome"] for k, e in led.rows.items()}
    assert out[inv.image_set_key(["https://img.example.test/g.jpg"])] == "graded"
    assert out[inv.image_set_key(["https://img.example.test/u.jpg"])] == "ungraded"
    assert out[inv.image_set_key(["https://img.example.test/f.jpg"])] == "fetch_failed"
    assert led.rows[inv.image_set_key(["https://img.example.test/g.jpg"])]["values"]["condition_tier"] == "major"

    # next run, fresh rows (raw.vision_unscored is not published): the ungraded set is not sent
    # again inside its retry window; the graded set comes back from the ledger without a call
    sent.clear()
    dl.reset_cache()
    again_graded = _li({"real": ["https://img.example.test/g.jpg"]})
    again_ungraded = _li({"real": ["https://img.example.test/u.jpg"]})
    asyncio.run(V.enrich_with_vision([again_graded, again_ungraded]))
    assert sent == []
    assert again_graded.raw["vision"]["condition_tier"] == "major"
    assert again_graded.raw["vision"]["_from_ledger"] is True
    assert again_graded.raw["condition_source"] == "vision-HIGH"


def test_the_skip_set_is_cleared_when_the_pass_is_cancelled(ledger_dir, monkeypatch):
    async def slow_impl(listings, max_listings=None):
        await asyncio.sleep(5)

    monkeypatch.setattr(V, "_enrich_with_vision_impl", slow_impl)

    async def run():
        try:
            await asyncio.wait_for(V.enrich_with_vision([_li({"real": ["https://i.example.test/a.jpg"]})]), 0.05)
        except asyncio.TimeoutError:
            pass

    asyncio.run(run())
    assert V._LEDGER_SKIP == set()
