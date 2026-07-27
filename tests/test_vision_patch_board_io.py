"""Daily-vision pass must read the board through load_board().

Regression guard for the coverage bug: "vision" is a LAZY_DETAIL_KEY, so after
write_artifact the reports live in docs/listings_detail.json and the slim
listings.json has NONE of them. scripts/patch_vision_gemini.py used to hydrate
from a raw json.loads of listings.json, so every already-scored lead looked
un-scored ("0 already vision-scored; 30003 un-scored" against a board with 2347
reports) — the pass re-graded the same priority head every day and coverage
never advanced.

Also guards the write end: the pass must not publish a board with fewer leads
than it loaded, even when a record fails strict Listing.model_validate.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import write_artifact

# The pass lives under scripts/ (not an installed package), so load it by path.
_MOD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "patch_vision_gemini.py"
_spec = importlib.util.spec_from_file_location("patch_vision_gemini", _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(mod)


def _lead(i: int, vision: dict | None = None) -> Listing:
    raw: dict = {"grade": {"overall": "B"}}
    if vision is not None:
        raw["vision"] = vision
    return Listing(source="x", source_url=f"u{i}", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", parcel_id=f"P{i}",
                   street_address=f"{i} Main St", raw=raw)


def test_sidecar_vision_counts_as_already_scored(tmp_path):
    # lead 0 scored, lead 1 not. write_artifact pushes vision into the sidecar.
    write_artifact([_lead(0, {"condition_tier": "cosmetic", "_provider": "gemini"}), _lead(1)],
                   {"notes": "t"}, docs_dir=tmp_path)
    slim = json.loads((tmp_path / "listings.json").read_text())
    assert all("vision" not in (r.get("raw") or {}) for r in slim), \
        "precondition: listings.json must be slim (vision lives in the sidecar)"

    board, n_records = mod.load_board_no_shrink(tmp_path)
    assert n_records == 2 and len(board) == 2
    # THE BUG: without the sidecar merge both leads look un-scored.
    assert board[0].raw.get("vision"), "sidecar vision must be merged back into raw"
    assert mod.needs_vision(board[0]) is False, "already-scored lead must be skipped"
    assert mod.needs_vision(board[1]) is True
    assert sum(1 for li in board if not mod.needs_vision(li)) == 1


def test_raw_json_load_would_have_missed_it(tmp_path):
    # Documents the old failure mode so nobody reintroduces it.
    write_artifact([_lead(0, {"condition_tier": "gut", "_provider": "gemini"})],
                   {"notes": "t"}, docs_dir=tmp_path)
    naive = [mod._hydrate(d) for d in json.loads((tmp_path / "listings.json").read_text())]
    assert all(mod.needs_vision(li) for li in naive), \
        "raw json.loads hydration sees zero vision — that was the bug"


def test_ollama_only_lead_is_rescored(tmp_path):
    # The upgrade rule: a weak local-Ollama score still needs a real provider.
    write_artifact([_lead(0, {"condition_tier": "cosmetic", "_provider": "ollama"})],
                   {"notes": "t"}, docs_dir=tmp_path)
    board, _ = mod.load_board_no_shrink(tmp_path)
    assert board[0].raw.get("vision")
    assert mod.needs_vision(board[0]) is True, "ollama-only vision must be re-scored"


def test_board_never_shrinks_on_invalid_record(tmp_path):
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    recs = json.loads((tmp_path / "listings.json").read_text())
    # Poison one record so strict Listing.model_validate rejects it.
    recs[1]["listing_type"] = "not-a-real-listing-type"
    (tmp_path / "listings.json").write_text(json.dumps(recs))

    from foreclosure_scraper.web_artifact import load_board
    assert len(load_board(tmp_path)) == 1, "precondition: load_board drops the bad record"

    board, n_records = mod.load_board_no_shrink(tmp_path)
    assert n_records == 2
    assert len(board) == 2, "recovery path must keep records load_board dropped"
    assert {li.source_url for li in board} == {"u0", "u1"}


def test_write_roundtrip_preserves_sidecar(tmp_path):
    # A full load -> write cycle through the sanctioned helpers must not wipe
    # the vision sidecar for leads this pass never touched.
    write_artifact([_lead(0, {"condition_tier": "major", "_provider": "gemini"}), _lead(1)],
                   {"notes": "t"}, docs_dir=tmp_path)
    board, _ = mod.load_board_no_shrink(tmp_path)
    write_artifact(board, {"notes": "pass 2"}, docs_dir=tmp_path)
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    assert detail[0].get("vision", {}).get("condition_tier") == "major"
    assert len(json.loads((tmp_path / "listings.json").read_text())) == 2
