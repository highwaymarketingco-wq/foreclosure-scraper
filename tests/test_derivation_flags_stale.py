"""enrich_derivation_flags must drop a block that no longer applies.

Found 2026-09-18: it only ever wrote raw['derivation_flags'] when a flag
applied, so a flag set on old data survived forever. 116 board leads were
flagged free_and_clear while their ROD block showed has_mortgage=True with
3-24 open mortgages (one had 77 instruments on file).
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_derivation_flags import enrich_derivation_flags
from foreclosure_scraper.models import Listing, ListingType


def _lead(rod, flags=None):
    raw = {"rod": rod}
    if flags is not None:
        raw["derivation_flags"] = flags
    return Listing(source="x", source_url="u", listing_type=ListingType.TAX_LIEN,
                   state="SC", county="Spartanburg", owner_name="BYRD SANDRA D", raw=raw)


_STALE = {"free_and_clear": {"flag": True, "reason": "no_mortgage_recordings"}}
_OPEN_MTG = {"instrument_count": 41, "has_mortgage": True, "open_mortgages_est": 3, "source": "cchs_rod"}
_CLEAN = {"instrument_count": 2, "has_mortgage": False, "open_mortgages_est": 0, "source": "cchs_rod",
          "fetched_at": "2026-08-01T00:00:00+00:00"}


def test_stale_free_and_clear_is_removed_when_rod_now_shows_open_mortgages():
    li = _lead(_OPEN_MTG, flags=_STALE)
    stats = enrich_derivation_flags([li])
    # The stale free_and_clear claim is gone, but _OPEN_MTG's open mortgage is
    # now itself a legitimate signal (unreleased_mortgage, added alongside
    # free_and_clear as its mirror image). Because a NEW flag block ends up
    # non-empty, the function takes the "replace" branch (out written fresh
    # over the old block) rather than the dedicated "drop the now-empty
    # block" branch, so dropped_stale stays 0 here -- see the companion
    # all-flags-empty case below for that counter's own test.
    assert "free_and_clear" not in li.raw.get("derivation_flags", {})
    assert li.raw["derivation_flags"]["unreleased_mortgage"]["flag"] is True
    assert stats["dropped_stale"] == 0 and stats["free_and_clear"] == 0


_NEITHER_APPLIES = {"instrument_count": 4, "has_mortgage": True, "open_mortgages_est": 0,
                     "source": "cchs_rod"}


def test_stale_free_and_clear_dropped_with_no_replacement_flag():
    """Same stale-removal case, but with ROD data where NEITHER free_and_clear
    NOR unreleased_mortgage applies (has_mortgage=True, open_mortgages_est=0 --
    internally inconsistent/edge data, but exercises the real 'out' ends up
    empty, so the whole stale block is deleted' path and its dropped_stale
    counter, now that _OPEN_MTG above no longer reaches it)."""
    li = _lead(_NEITHER_APPLIES, flags=_STALE)
    stats = enrich_derivation_flags([li])
    assert "derivation_flags" not in li.raw
    assert stats["dropped_stale"] == 1 and stats["free_and_clear"] == 0
    assert stats["unreleased_mortgage"] == 0


def test_flag_that_still_applies_is_kept_and_refreshed():
    li = _lead(_CLEAN, flags={"free_and_clear": {"flag": True, "reason": "old"}})
    stats = enrich_derivation_flags([li])
    assert li.raw["derivation_flags"]["free_and_clear"]["reason"] == "no_mortgage_recordings"
    assert stats["free_and_clear"] == 1 and stats["dropped_stale"] == 0


def test_lead_that_never_had_flags_is_untouched():
    li = _lead(_OPEN_MTG)
    stats = enrich_derivation_flags([li])
    # No PRE-EXISTING flags to drop (dropped_stale stays 0) — but _OPEN_MTG's
    # open mortgage legitimately earns a fresh unreleased_mortgage flag.
    assert "free_and_clear" not in li.raw.get("derivation_flags", {})
    assert li.raw["derivation_flags"]["unreleased_mortgage"]["flag"] is True
    assert stats["dropped_stale"] == 0


def test_non_dict_raw_does_not_crash():
    li = Listing(source="x", source_url="u", listing_type=ListingType.TAX_LIEN,
                 state="SC", county="Spartanburg", owner_name="BYRD SANDRA D")
    li.raw = None
    assert enrich_derivation_flags([li])["dropped_stale"] == 0
