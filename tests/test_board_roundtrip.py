"""Board round-trip must preserve the lazy-detail sidecar.

Regression guard: an incremental board-writer that reads listings.json, tweaks a
lead, and re-runs write_artifact must NOT drop the heavy comps/vision keys. The
fix is load_board() (merges the sidecar back before returning). Without it, the
second write rebuilds the sidecar from raw that no longer has those keys ->
empty sidecar -> blank detail panels.
"""
from __future__ import annotations

import json

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import write_artifact, load_board, LAZY_DETAIL_KEYS


def _lead(i: int) -> Listing:
    return Listing(source="x", source_url=f"u{i}", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", parcel_id=f"P{i}", street_address=f"{i} Main St",
                   raw={"grade": {"overall": "B"},
                        "comps": [{"addr": f"{i} Elm", "sold_price": 200000 + i}],
                        "vision": {"parsed": True}})


def test_load_board_merges_sidecar(tmp_path):
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    # sidecar carries the lazy keys, listings.json does not
    listings = json.loads((tmp_path / "listings.json").read_text())
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    assert all(not any(k in (r.get("raw") or {}) for k in LAZY_DETAIL_KEYS) for r in listings)
    assert detail[0].get("comps") and detail[0].get("vision")
    # load_board glues them back
    board = load_board(tmp_path)
    assert board[0].raw.get("comps") and board[0].raw.get("vision")


def test_incremental_rewrite_preserves_lazy(tmp_path):
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    # simulate an incremental pass: load via load_board, tweak, rewrite
    board = load_board(tmp_path)
    board[0].owner_name = "NEW OWNER"
    write_artifact(board, {"notes": "pass 2"}, docs_dir=tmp_path)
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    # lazy data survived the second write (the bug would have emptied it)
    assert detail[0].get("comps"), "lazy detail lost on incremental rewrite"
    assert detail[0]["comps"][0]["sold_price"] == 200000


def test_naive_reload_now_preserves_lazy(tmp_path):
    # write_artifact now backfills the prior sidecar by IDENTITY (source_url /
    # parcel_id / addr+county), so even a naive reload that never called
    # load_board keeps the lazy detail. This is the safety net for the full run,
    # which builds `enriched` fresh (no sidecar in raw) and only re-visions a
    # capped subset — without this it wiped vision/comps for ~29k leads/run.
    # load_board is still preferred (it merges detail into raw for in-memory use).
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    naive = [Listing.model_validate(d) for d in json.loads((tmp_path / "listings.json").read_text())]
    write_artifact(naive, {"notes": "pass 2 naive"}, docs_dir=tmp_path)
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    assert detail[0].get("comps"), "sidecar-preserve should keep lazy detail across a naive re-write"
    assert detail[0].get("vision")
    assert detail[0]["comps"][0]["sold_price"] == 200000


def test_fresh_detail_wins_over_prior_sidecar(tmp_path):
    # The identity backfill must never override detail the current run DID produce.
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    fresh = _lead(0)
    fresh.raw["vision"] = {"parsed": True, "_provider": "gemini", "tier": "NEW"}
    write_artifact([fresh], {"notes": "pass 2 fresh"}, docs_dir=tmp_path)
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    assert detail[0]["vision"].get("tier") == "NEW", "fresh vision must win over prior sidecar"


# --- regression: ambiguous identity keys must NEVER carry detail across -------
# The sidecar backfill originally trusted source_url as "most unique". On the real
# board 652 source_urls are shared by 19,392 leads (one ArcGIS URL by 3,293; county
# PDF rolls give every lead the same URL), so first-wins handed ONE property's
# vision report to 985 unrelated leads — wrong condition grades, wrong ARV, and
# permanently removed from the scoring queue. Caught in review 2026-07-27.

def _rec(url, addr, county, parcel=None):
    li = Listing(source="x", source_url=url, listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county=county, parcel_id=parcel, street_address=addr,
                 raw={"grade": {"overall": "B"}})
    return li


def test_shared_source_url_does_not_fan_out_vision(tmp_path):
    """Leads sharing a source_url must not inherit each other's vision.

    Each lead here still has a UNIQUE street_address, so lead A legitimately
    keeps its own report through that key — the bug was B and C also receiving it.
    """
    a = _rec("http://county.gov/roll.pdf", "1 Main St", "Burke")
    a.raw["vision"] = {"condition_tier": "gut", "_provider": "gemini"}
    b = _rec("http://county.gov/roll.pdf", "2 Oak Ave", "Burke")
    c = _rec("http://county.gov/roll.pdf", "3 Pine Rd", "Burke")
    write_artifact([a, b, c], {"notes": "t"}, docs_dir=tmp_path)

    # Re-write with NO vision in raw (simulates a pass that did not re-vision).
    board = [_rec("http://county.gov/roll.pdf", "1 Main St", "Burke"),
             _rec("http://county.gov/roll.pdf", "2 Oak Ave", "Burke"),
             _rec("http://county.gov/roll.pdf", "3 Pine Rd", "Burke")]
    write_artifact(board, {"notes": "t2"}, docs_dir=tmp_path)
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    assert detail[0].get("vision"), "the owning lead keeps its report via its unique address"
    assert not detail[1].get("vision"), "lead B must not inherit A's vision via the shared URL"
    assert not detail[2].get("vision"), "lead C must not inherit A's vision via the shared URL"


def test_shared_url_as_only_key_carries_nothing(tmp_path):
    """When the shared source_url is the ONLY available key (no address, no
    parcel — the real county-PDF-roll shape), no detail may carry at all."""
    a = _rec("http://county.gov/roll.pdf", None, None)
    a.raw["vision"] = {"condition_tier": "gut", "_provider": "gemini"}
    b = _rec("http://county.gov/roll.pdf", None, None)
    write_artifact([a, b], {"notes": "t"}, docs_dir=tmp_path)

    board = [_rec("http://county.gov/roll.pdf", None, None),
             _rec("http://county.gov/roll.pdf", None, None)]
    write_artifact(board, {"notes": "t2"}, docs_dir=tmp_path)
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    got = [bool(d.get("vision")) for d in detail]
    assert got.count(True) == 0, (
        f"an ambiguous-only key leaked vision to {got.count(True)} leads; it must carry to none")


def test_unique_parcel_id_still_carries_detail(tmp_path):
    """The safe key must keep working — the fix must not disable the backfill."""
    a = _rec("http://county.gov/roll.pdf", "1 Main St", "Burke", parcel="PARCEL-1")
    a.raw["vision"] = {"condition_tier": "gut", "_provider": "gemini"}
    b = _rec("http://county.gov/roll.pdf", "2 Oak Ave", "Burke", parcel="PARCEL-2")
    write_artifact([a, b], {"notes": "t"}, docs_dir=tmp_path)

    board = [_rec("http://county.gov/roll.pdf", "1 Main St", "Burke", parcel="PARCEL-1"),
             _rec("http://county.gov/roll.pdf", "2 Oak Ave", "Burke", parcel="PARCEL-2")]
    write_artifact(board, {"notes": "t2"}, docs_dir=tmp_path)
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    assert detail[0].get("vision"), "unique parcel_id must still carry prior detail"
    assert not detail[1].get("vision"), "the other parcel must not inherit it"
