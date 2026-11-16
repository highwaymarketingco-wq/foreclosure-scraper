"""Regression guard for the 2026-11-15 _TOP_FIELDS omission bug in
scripts/backfill_gis_attrs_boardwide.py and its Lexington-scoped sibling
scripts/backfill_lexington_gis_attrs.py.

THE BUG. Both scripts snapshot a fixed tuple of Listing attributes (_TOP_FIELDS) before
and after calling enrichment_gis_attrs.enrich_gis_attrs(), and only ever put a field in
the patch sent to patch_existing_rows() if that field's name is in _TOP_FIELDS. bedrooms
and bathrooms are real top-level Listing scalars (models.py) that
parcel_cache_join.apply_hit() fills whenever a parcel_cache hit carries them -- and
enrich_gis_attrs's own cache_join stats correctly counted "filled bedrooms"/"filled
bathrooms" on every run -- but _TOP_FIELDS never named either one, so every prior batch
silently dropped them from the patch. Live-confirmed on the published board: Lexington SC
carried 0 of 31,402 rows with bedrooms/bathrooms set despite 10+ board-wide batches of
this exact mechanism having already "landed" (project_gis_attrs_boardwide_dormant_2026-10-23).

This file guards two things: (1) _TOP_FIELDS in both scripts is a superset of every
Listing scalar apply_hit() can set, so a FUTURE field added there without updating
_TOP_FIELDS fails this test instead of silently vanishing again; and (2) the scripts'
own before/after diff formula, exercised directly against a fake before/after snapshot
pair, actually carries a changed bedrooms/bathrooms value into the resulting patch.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import backfill_gis_attrs_boardwide as BW  # noqa: E402
import backfill_lexington_gis_attrs as LEX  # noqa: E402

# Every Listing scalar attribute parcel_cache_join.apply_hit() can set (read off its own
# source: every `li.<attr> = ...` assignment there, 2026-11-15). street_address/land_use/
# assessed_value are intentionally NOT required here -- they are filled by other code
# inside enrich_gis_attrs() (the live-GIS-query path, the script's own situs-fill hook),
# not by apply_hit(), so their presence in _TOP_FIELDS is not this bug's concern.
APPLY_HIT_SCALAR_FIELDS = ("owner_name", "market_value", "tax_value", "living_sqft",
                           "acreage", "year_built", "bedrooms", "bathrooms")


def test_apply_hit_fields_survive_boardwide_top_fields():
    missing = [f for f in APPLY_HIT_SCALAR_FIELDS if f not in BW._TOP_FIELDS]
    assert not missing, (
        f"backfill_gis_attrs_boardwide._TOP_FIELDS is missing {missing} -- "
        "parcel_cache_join.apply_hit() can fill these Listing scalars, so a patch built "
        "from this tuple will silently drop any cache hit's value for them (the exact "
        "2026-11-15 bedrooms/bathrooms bug).")


def test_apply_hit_fields_survive_lexington_top_fields():
    missing = [f for f in APPLY_HIT_SCALAR_FIELDS if f not in LEX._TOP_FIELDS]
    assert not missing, (
        f"backfill_lexington_gis_attrs._TOP_FIELDS is missing {missing} -- same bug class "
        "as backfill_gis_attrs_boardwide's.")


def _diff_patch(top_fields, raw_watch_keys, before: dict, after_li) -> dict:
    """The exact before/after -> patch formula both scripts use (copied here rather than
    imported, since it lives inline in each script's main(), not a standalone function --
    this exercises the REAL tuples via the REAL formula shape, not a reimplementation)."""
    after = {**{f: getattr(after_li, f, None) for f in top_fields},
             **{k: after_li.raw.get(k) if isinstance(after_li.raw, dict) else None
                for k in raw_watch_keys}}
    patch: dict = {}
    for f in top_fields:
        if after[f] != before[f]:
            patch[f] = after[f]
    raw_patch = {k: after[k] for k in raw_watch_keys if after[k] != before[k]}
    if raw_patch:
        patch["raw"] = raw_patch
    return patch


class _FakeListing:
    """Bare attribute bag -- just enough for the diff formula's getattr() calls, without
    pulling in the real Listing/pydantic machinery this test does not need."""

    def __init__(self, **kw):
        self.raw = {}
        for k, v in kw.items():
            setattr(self, k, v)


def test_changed_bedrooms_and_bathrooms_survive_the_diff_boardwide():
    before = {f: None for f in BW._TOP_FIELDS}
    before.update({k: None for k in BW._RAW_WATCH_KEYS})
    after_li = _FakeListing(bedrooms=3.0, bathrooms=2.0)
    patch = _diff_patch(BW._TOP_FIELDS, BW._RAW_WATCH_KEYS, before, after_li)
    assert patch.get("bedrooms") == 3.0, patch
    assert patch.get("bathrooms") == 2.0, patch


def test_changed_bedrooms_and_bathrooms_survive_the_diff_lexington():
    before = {f: None for f in LEX._TOP_FIELDS}
    before.update({k: None for k in LEX._RAW_WATCH_KEYS})
    after_li = _FakeListing(bedrooms=4.0, bathrooms=4.5)
    patch = _diff_patch(LEX._TOP_FIELDS, LEX._RAW_WATCH_KEYS, before, after_li)
    assert patch.get("bedrooms") == 4.0, patch
    assert patch.get("bathrooms") == 4.5, patch


def test_lexington_script_filters_to_sc_lexington_only():
    assert LEX.STATE == "SC"
    assert LEX.COUNTY == "Lexington"
