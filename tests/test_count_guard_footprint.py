"""The count guard must tell a buy-box correction apart from data loss.

Regression cover for the 2026-09-09 diagnosis. A clean 15h run was refused and the
board sat frozen for 12 days, because `scope_repass` correctly removed 30,509 rows
that resolve to counties outside the footprint and the guard read that as "a source
broke". The high-water mark (94,384) had been set while those same rows were still
unresolved, and the mark only ever moved UP -- so every honest run afterwards hit
the identical wall. That is the deadlock these tests pin down.

The guard keeps its teeth. It exists because 72K rows once vanished silently, so an
unexplained collapse is still refused, a partial explanation does not cover the
rest, and a run claiming it meant to delete nearly everything is capped.
"""
from __future__ import annotations

import json

import pytest

from foreclosure_scraper import web_artifact
from foreclosure_scraper.models import Listing


def _rows(n: int) -> list[Listing]:
    return [
        Listing(source="t.x", source_url="http://x", street_address=f"{i} Main St",
                county="Greenville", state="SC")
        for i in range(n)
    ]


@pytest.fixture
def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir(parents=True)
    # A board file must exist for the guard block to run at all.
    (d / "listings.json").write_text(json.dumps([{"source": "t", "source_url": "u"}] * 10))
    return d


def _highwater(docs, count: int) -> None:
    (docs / "board_highwater.json").write_text(json.dumps({"count": count}))


def _write(docs, n: int, off_footprint: int = 0):
    return web_artifact.write_artifact(
        _rows(n),
        {"total": n, "off_footprint_removed": off_footprint},
        docs_dir=docs,
    )


def test_shrink_explained_by_footprint_removals_is_allowed(docs):
    """The 2026-09-09 case: the shrink IS the buy-box correction, so it must pass.

    Proportions mirror the real run -- 30,509 of 94,384 is ~32% -- which sits well
    inside the 60% allowance cap exercised by
    `test_absurd_allowance_is_capped`.
    """
    _highwater(docs, 40_000)
    _write(docs, 27_000, off_footprint=13_000)   # 40,000 - 13,000 = 27,000 expected
    assert (docs / "listings.json").exists()


def test_high_water_rebases_after_an_explained_shrink(docs):
    """Without a rebase the old mark describes a population we no longer publish,
    and the next honest run is blocked all over again."""
    _highwater(docs, 40_000)
    _write(docs, 27_000, off_footprint=13_000)
    hw = json.loads((docs / "board_highwater.json").read_text())
    assert hw["count"] == 27_000
    assert hw["rebased_from"] == 40_000


def test_unexplained_collapse_is_still_refused(docs):
    """A source dying silently is the whole reason the guard exists."""
    _highwater(docs, 40_000)
    with pytest.raises(RuntimeError, match="COUNT GUARD"):
        _write(docs, 27_000, off_footprint=0)


def test_partial_explanation_does_not_cover_real_loss(docs):
    """13k explained does not license losing another 20k on top of it."""
    _highwater(docs, 40_000)
    with pytest.raises(RuntimeError, match="COUNT GUARD"):
        _write(docs, 7_000, off_footprint=13_000)


def test_absurd_allowance_is_capped(docs):
    """A run claiming it intended to remove everything is exactly the bug the
    guard is for, so the allowance is capped at 60% of the baseline."""
    _highwater(docs, 40_000)
    with pytest.raises(RuntimeError, match="COUNT GUARD"):
        _write(docs, 200, off_footprint=39_900)


def test_duplicate_collapse_is_NOT_silently_allowed(docs):
    """Deliberate policy, not an oversight.

    Roughly 22,115 of the board's rows are genuine duplicates of the same property
    from different sources, and collapsing them is correct. But `PIN_RE` in
    scrape_liensnc.py proved dedupe CAN be wrong -- it captured 'ehurst' from
    "Pinehurst" and fused 122 distinct properties into one row with no log line. A
    blanket "dedupe shrink is always fine" allowance would have waved that through.
    So dedupe shrink is NOT an automatic allowance: the operator reads the new
    `dedupe.suspicious_primary_key` warning and rebases once, deliberately.
    """
    _highwater(docs, 40_000)
    with pytest.raises(RuntimeError, match="COUNT GUARD"):
        _write(docs, 30_000, off_footprint=0)


def test_growth_still_moves_the_mark_up(docs):
    _highwater(docs, 20_000)
    _write(docs, 25_000, off_footprint=0)
    hw = json.loads((docs / "board_highwater.json").read_text())
    assert hw["count"] == 25_000
    assert "rebased_from" not in hw
