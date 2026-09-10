"""Every raw key an enricher writes must survive the publish slim.

`web_artifact._slim_raw()` copies only the keys named in `RAW_KEEP`. Anything else
is dropped at write time, silently, with no error and no log line -- so an
enricher can run perfectly, cost hours of politely rate-limited fetching, and
leave nothing on the board.

That is not hypothetical. On 2026-09-10 the LiensNC related-filings enricher wrote
`raw['liensnc_related']` for 1,500 entries -- owner phone, email and mailing
address, the exact contactability the engine had been short of -- and a scan of
the resulting board found the key on ZERO rows. RAW_KEEP had never named it. The
run reported success the whole way.

This test walks the enrichment modules for literal `raw[...] = ` assignments and
asserts each key is either in RAW_KEEP or explicitly listed below as intentionally
internal. It is deliberately a source scan rather than a runtime check: the point
is to fail in CI the moment someone adds a new enricher, not after a long harvest.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from foreclosure_scraper.web_artifact import RAW_KEEP

SRC = Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper"

# Keys deliberately NOT published: scratch state, provenance the dashboard never
# reads, or values folded into another published key before the write.
INTENTIONALLY_INTERNAL = {
    "_seen_this_run", "_from_prior_board", "_idx", "_merged_idxs",
    "_partial", "_tmp", "_scratch", "_debug",
    # Redundant with something already published — verified 2026-09-10, not guessed:
    # `living_sqft_estimated` is a top-level Listing FIELD and ships in the row itself.
    "living_sqft_estimated",
    # `gis_attrs` is a summary of `gis_attrs_full`, which IS in RAW_KEEP.
    "gis_attrs",
    # `parcel_from_geo` is provenance for the resolve; `parcel_resolution` IS published.
    "parcel_from_geo",
    # `property_kind_reclassified` is provenance; `property_kind` is a published field.
    "property_kind_reclassified",
    # `vision_unscored` is DELIBERATELY unpublished, and this one bit me: I added it
    # to RAW_KEEP during the 2026-09-10 dropped-key audit and broke
    # test_ungraded_report_never_reaches_the_published_board. An ungraded vision
    # report on the board is indistinguishable from a real grade to anything reading
    # raw['vision*'], so the dashboard would present a failed model call as a
    # condition assessment. The diagnostic stays in-process via the
    # vision.listing_ungraded log line.
    "vision_unscored",
}


def _raw_keys_written(path: Path) -> set[str]:
    """Literal string keys assigned into a `raw`-ish dict in this module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if not isinstance(tgt, ast.Subscript):
                continue
            if not isinstance(tgt.slice, ast.Constant) or not isinstance(tgt.slice.value, str):
                continue
            base = tgt.value
            # li.raw["x"] = ...  /  raw["x"] = ...
            name = None
            if isinstance(base, ast.Attribute) and base.attr == "raw":
                name = "raw"
            elif isinstance(base, ast.Name) and base.id in ("raw", "_raw"):
                name = "raw"
            if name:
                found.add(tgt.slice.value)
    return found


def _enrichment_modules() -> list[Path]:
    return sorted(
        p for p in SRC.glob("enrich*.py")
        if p.is_file() and not p.name.startswith("_")
    )


def test_there_are_enrichment_modules_to_check():
    """Guard the guard: a glob that silently matches nothing would pass forever."""
    mods = _enrichment_modules()
    assert len(mods) > 20, f"only found {len(mods)} enrichment modules — glob is wrong"


@pytest.mark.parametrize("module", _enrichment_modules(), ids=lambda p: p.name)
def test_enricher_raw_keys_survive_the_publish_slim(module):
    written = _raw_keys_written(module)
    unpublished = {
        k for k in written
        if k not in RAW_KEEP and k not in INTENTIONALLY_INTERNAL and not k.startswith("_")
    }
    assert not unpublished, (
        f"{module.name} writes raw keys that _slim_raw() will silently DROP at "
        f"publish: {sorted(unpublished)}. Either add them to RAW_KEEP in "
        f"web_artifact.py, or add them to INTENTIONALLY_INTERNAL in this test with "
        f"a reason. Do not leave them unlisted — that is how 1,500 owner phone "
        f"numbers were harvested and thrown away on 2026-09-10."
    )


def test_the_two_keys_that_were_actually_lost_are_now_covered():
    """Direct regression pin for the 2026-09-10 loss."""
    assert "liensnc_related" in RAW_KEEP
    assert "fullmer" in RAW_KEEP
