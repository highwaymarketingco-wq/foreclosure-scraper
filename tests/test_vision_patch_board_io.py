"""Daily-vision pass must read the board with the lazy-detail sidecar merged in.

Regression guard for the coverage bug: "vision" is a LAZY_DETAIL_KEY, so after
write_artifact the reports live in docs/listings_detail.json and the slim
listings.json has NONE of them. scripts/patch_vision_gemini.py used to hydrate
from a raw json.loads of listings.json, so every already-scored lead looked
un-scored ("0 already vision-scored; 30003 un-scored" against a board with 2347
reports) — the pass re-graded the same priority head every day and coverage
never advanced.

BOARD I/O REWRITE (2026-09-30): the pass no longer reads through load_board()
(refused above BOARD_LOAD_MAX_SOURCE_MB on the real board) or writes through
write_artifact() — see patch_vision_gemini.py's own module docstring. It reads
via web_artifact._iter_board_records() (the same sidecar merge load_board()
itself uses, just streamed) and writes via web_artifact.patch_existing_rows()
(mutates only the rows this run's vision pass actually touched). This file's
tests were rewritten to exercise those primitives directly instead of the
now-removed load_board_no_shrink()/_hydrate() helpers -- the regressions they
guard against are unchanged.

Also guards the write end: patch_existing_rows() streams the EXISTING board's
rows through unchanged except for the small matched subset (with a strict
manifest count guard on top), so a row that fails Listing.model_validate() can
no longer cause the published board to shrink -- that whole class of risk,
which load_board_no_shrink() existed to recover from, is now structurally
impossible on the write side. The read side must still degrade gracefully
(skip, not crash, on a malformed candidate).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import _iter_board_records, write_artifact

# The pass lives under scripts/ (not an installed package), so load it by path.
_MOD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "patch_vision_gemini.py"
_spec = importlib.util.spec_from_file_location("patch_vision_gemini", _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(mod)

_REAL_IMAGE = {"images": {"real": ["https://example.test/photo.jpg"]}}


def _lead(i: int, vision: dict | None = None, with_photo: bool = False) -> Listing:
    raw: dict = {"grade": {"overall": "B"}}
    if with_photo:
        raw.update(_REAL_IMAGE)
    if vision is not None:
        raw["vision"] = vision
    return Listing(source="x", source_url=f"u{i}", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", parcel_id=f"P{i}",
                   street_address=f"{i} Main St", raw=raw)


def _light(rec: dict) -> Listing:
    """Mirrors patch_vision_gemini._collect_candidates()'s own cheap pre-check construct."""
    return Listing.model_construct(raw=rec.get("raw") or {})


def test_sidecar_vision_counts_as_already_scored(tmp_path):
    # lead 0 scored, lead 1 not. write_artifact pushes vision into the sidecar.
    write_artifact([_lead(0, {"condition_tier": "cosmetic", "_provider": "gemini"}), _lead(1)],
                   {"notes": "t"}, docs_dir=tmp_path)
    slim = json.loads((tmp_path / "listings.json").read_text())
    assert all("vision" not in (r.get("raw") or {}) for r in slim), \
        "precondition: listings.json must be slim (vision lives in the sidecar)"

    recs = list(_iter_board_records(tmp_path))
    assert len(recs) == 2
    lights = [_light(r) for r in recs]
    # THE BUG: without the sidecar merge both leads look un-scored.
    assert lights[0].raw.get("vision"), "sidecar vision must be merged back into raw"
    assert mod.needs_vision(lights[0]) is False, "already-scored lead must be skipped"
    assert mod.needs_vision(lights[1]) is True
    assert sum(1 for li in lights if not mod.needs_vision(li)) == 1


def test_raw_json_load_would_have_missed_it(tmp_path):
    # Documents the old failure mode so nobody reintroduces it: reading the SLIM
    # listings.json directly (no sidecar merge) makes every lead look un-scored.
    write_artifact([_lead(0, {"condition_tier": "gut", "_provider": "gemini"})],
                   {"notes": "t"}, docs_dir=tmp_path)
    naive = [Listing.model_validate(d) for d in json.loads((tmp_path / "listings.json").read_text())]
    assert all(mod.needs_vision(li) for li in naive), \
        "raw json.loads hydration sees zero vision — that was the bug"


def test_ollama_only_lead_is_rescored(tmp_path):
    # The upgrade rule: a weak local-Ollama score still needs a real provider.
    write_artifact([_lead(0, {"condition_tier": "cosmetic", "_provider": "ollama"})],
                   {"notes": "t"}, docs_dir=tmp_path)
    recs = list(_iter_board_records(tmp_path))
    li = _light(recs[0])
    assert li.raw.get("vision")
    assert mod.needs_vision(li) is True, "ollama-only vision must be re-scored"


def test_malformed_candidate_is_skipped_not_crashed_and_never_shrinks_the_board(tmp_path, monkeypatch):
    """The old load_board_no_shrink() recovery path existed because load_board() +
    write_artifact() re-validated (and could silently drop) every row. patch_existing_rows()
    cannot drop a row at all -- it streams each existing row's raw dict through unchanged except
    for the small matched patch subset -- so a malformed record can no longer shrink the
    published board no matter what the read side does with it. This proves the read side (which
    DOES call Listing.model_validate() on candidates) still degrades gracefully: a record that
    fails validation is simply excluded from `candidates`, not crashed on, and the published
    board is untouched either way.
    """
    # lead 0: photo + no vision -> a real candidate, and the one our fake vision pass scores.
    # lead 1: photo + no vision too, but poisoned on disk below -> must be skipped, not crash.
    write_artifact([_lead(0, with_photo=True), _lead(1, with_photo=True)],
                   {"notes": "t"}, docs_dir=tmp_path)
    recs = json.loads((tmp_path / "listings.json").read_text())
    recs[1]["listing_type"] = "not-a-real-listing-type"
    (tmp_path / "listings.json").write_text(json.dumps(recs))
    # The board is published as gzipped PARTS (board_parts.py); the plain listings.json above is
    # now hand-edited out of sync with both the manifest AND the parts, so a bare read would
    # silently prefer the still-valid parts and never see this poisoning at all (confirmed: this
    # test failed with candidates == ["u0", "u1"] without this). BOARD_MANIFEST_SKIP forces the
    # plain file to be read as-is, exactly like the pre-rewrite version of this test did.
    monkeypatch.setenv("BOARD_MANIFEST_SKIP", "1")

    candidates, total_rows, unscored_total = mod._collect_candidates(tmp_path)
    assert total_rows == 2                       # both rows streamed, neither crashes the scan
    assert unscored_total == 2                   # both look un-scored (poisoning doesn't hide that)
    assert [li.source_url for li in candidates] == ["u0"]   # only the valid one becomes a candidate

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import patch_vision_gemini as pvg_mod  # the same module, imported normally for monkeypatch access

    import pytest
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pvg_mod, "REPO", tmp_path)   # board_lock only needs a writable dir for its own lock subdir
        mp.setattr(pvg_mod, "DOCS", tmp_path)
        mp.setenv("PATCH_PUBLISH", "0")
        mp.setenv("VISION_MAX_SECONDS", "0")

        async def _fake_enrich(listings, max_listings=None):
            for li in listings:
                li.raw["vision"] = {"_provider": "gemini", "condition_tier": "C2",
                                    "confidence": "HIGH"}
        mp.setattr(pvg_mod, "enrich_with_vision", _fake_enrich)
        mp.setattr(sys, "argv", ["patch_vision_gemini.py"])

        from foreclosure_scraper import web_artifact as wa
        wa._LOAD_STAMPS.clear()
        wa._VERIFIED.clear()

        rc = pvg_mod.main()
    assert rc == 0

    after = json.loads((tmp_path / "listings.json").read_text())
    assert len(after) == 2, "the board must never shrink, poisoned record or not"
    # the poisoned record is untouched (still carries the bad listing_type, proving it was
    # never re-validated on the write path either)
    poisoned = next(r for r in after if r["source_url"] == "u1")
    assert poisoned["listing_type"] == "not-a-real-listing-type"


def test_write_roundtrip_preserves_sidecar(tmp_path, monkeypatch):
    # A patch pass must not wipe the vision sidecar for a lead it never touched.
    write_artifact([_lead(0, {"condition_tier": "major", "_provider": "gemini"}),
                    _lead(1, with_photo=True)],
                   {"notes": "t"}, docs_dir=tmp_path)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import patch_vision_gemini as pvg_mod

    monkeypatch.setattr(pvg_mod, "REPO", tmp_path)   # board_lock only needs a writable dir for its own lock subdir
    monkeypatch.setattr(pvg_mod, "DOCS", tmp_path)
    monkeypatch.setenv("PATCH_PUBLISH", "0")
    monkeypatch.setenv("VISION_MAX_SECONDS", "0")

    async def _fake_enrich(listings, max_listings=None):
        for li in listings:
            li.raw["vision"] = {"_provider": "gemini", "condition_tier": "cosmetic",
                                "confidence": "HIGH"}
    monkeypatch.setattr(pvg_mod, "enrich_with_vision", _fake_enrich)
    monkeypatch.setattr(sys, "argv", ["patch_vision_gemini.py"])

    from foreclosure_scraper import web_artifact as wa
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()

    rc = pvg_mod.main()
    assert rc == 0

    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    # lead 0 (never a candidate: already vision-scored) keeps its ORIGINAL sidecar entry
    assert detail[0].get("vision", {}).get("condition_tier") == "major"
    # lead 1 (the candidate our fake pass scored) has its NEW sidecar entry
    assert detail[1].get("vision", {}).get("condition_tier") == "cosmetic"
    assert len(json.loads((tmp_path / "listings.json").read_text())) == 2
