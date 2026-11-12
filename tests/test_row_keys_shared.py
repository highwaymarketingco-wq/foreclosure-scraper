"""Rows read back one at a time share their dict-key strings (row_keys.share_keys), and nothing
else changes: same values, same key order, same model_dump, same merge result.

Why it matters (VM, 2026-10-06, 10/5 pre_publish checkpoint): 270,481 rows held 14,930 MiB as
parsed and 11,235 MiB with shared keys; 355,000 rows 20,267 vs 15,213 MiB. The publish of 355,000
rows peaked at 22,790 MiB on the 23,974 MiB VM with the per-row keys.

Real rows: tests/fixtures/placeholder_twins_10_5_groups.json.gz (28 rows of the 10/5 checkpoint,
14 live/aged-copy groups, phones redacted), so the raw trees are the production shape.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path

import pytest

from foreclosure_scraper import board_persist as bp
from foreclosure_scraper import checkpoint as C
from foreclosure_scraper.models import Listing
from foreclosure_scraper.row_keys import share_keys
from foreclosure_scraper.row_keys import share_row as _real_share_row

FIXTURE = Path(__file__).parent / "fixtures" / "placeholder_twins_10_5_groups.json.gz"
NOW = datetime(2026, 10, 6, 12, 0, 0)


def _records() -> list[dict]:
    return json.loads(gzip.open(FIXTURE, "rt", encoding="utf-8").read())


def _rows() -> list[Listing]:
    return [Listing.model_validate(r["row"]) for r in _records()]


def _keys(o, out: list) -> list:
    if isinstance(o, dict):
        for k, v in o.items():
            out.append(k)
            _keys(v, out)
    elif isinstance(o, list):
        for v in o:
            _keys(v, out)
    return out


def _dump(rows) -> list[str]:
    return [json.dumps(li.model_dump(mode="json")) for li in rows]


def _no_share(obj, cache):
    return obj


# ---------------------------------------------------------------------------- the helper

def test_share_keys_keeps_values_and_order_and_shares_key_objects():
    text = json.dumps(_records()[0]["row"])
    a, b = json.loads(text), json.loads(text)          # two separate decodes, like two rows
    assert not any(x is y for x, y in zip(_keys(a, []), _keys(b, [])) if len(x) > 1)
    cache: dict = {}
    sa, sb = share_keys(a, cache), share_keys(b, cache)
    assert json.dumps(sa) == text and json.dumps(sb) == text       # same values, same key order
    ka, kb = _keys(sa, []), _keys(sb, [])
    assert len(ka) > 50 and all(x is y for x, y in zip(ka, kb))      # one object per key
    assert len(cache) == len(set(ka))


def test_share_keys_leaves_leaf_values_alone():
    v = "a value string"
    rec = {"k": v, "n": [1, {"m": v}], "x": None}
    out = share_keys(rec, {})
    assert out == rec and out["k"] is v and out["n"][1]["m"] is v


# ---------------------------------------------------------------------------- checkpoint.load

@pytest.fixture
def ckdir(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CHECKPOINT_DIR", tmp_path / "ck")
    monkeypatch.setattr(C, "ENABLED", True)
    return tmp_path / "ck"


def test_checkpoint_load_round_trips_real_rows_and_shares_keys(ckdir):
    rows = _rows()
    assert C.save(rows, "pre_publish")
    back = C.load()
    assert _dump(back) == _dump(rows)
    k0, k1 = _keys(back[0].raw, []), _keys(back[1].raw, [])
    common = set(k0) & set(k1)
    assert len(common) > 20
    by0 = {k: k for k in k0}
    assert all(by0[k] is k for k in k1 if k in common)            # same object across rows


def test_checkpoint_load_identical_with_and_without_sharing(ckdir, monkeypatch):
    rows = _rows()
    assert C.save(rows, "pre_publish")
    shared = _dump(C.load())
    import foreclosure_scraper.row_keys as rk
    monkeypatch.setattr(rk, "share_keys", _no_share)
    assert _dump(C.load()) == shared


# ---------------------------------------------------------------------------- merge_prior_board

def _board(docs: Path, rows: list[Listing]) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "listings.json").write_text(json.dumps([li.model_dump(mode="json") for li in rows]))


def _merge(tmp_path, monkeypatch, share: bool):
    recs = _records()
    prior = [Listing.model_validate(r["row"]) for r in recs]
    # fresh = the live row of half the groups, re-scraped (a different instance of the same
    # data): those match or fold their aged copy; the other groups' rows are prior-only and age.
    keys = sorted({r["key"] for r in recs})[:7]
    fresh = [Listing.model_validate(r["row"]) for r in recs if r["role"] == "keep" and r["key"] in keys]
    docs = tmp_path / ("docs_shared" if share else "docs_plain")
    _board(docs, prior)
    monkeypatch.setenv("BOARD_PRIOR_MERGE_ALLOW_LARGE", "1")
    if not share:
        monkeypatch.setattr(bp, "share_row", _no_share)
    merged, stats = bp.merge_prior_board(fresh, docs_dir=docs, now=NOW)
    monkeypatch.setattr(bp, "share_row", _real_share_row)
    return merged, stats


def test_merge_prior_board_identical_with_and_without_sharing(tmp_path, monkeypatch):
    assert {r["role"] for r in _records()} == {"keep", "drop"}
    m_plain, s_plain = _merge(tmp_path, monkeypatch, share=False)
    m_shared, s_shared = _merge(tmp_path, monkeypatch, share=True)
    assert s_shared == s_plain
    assert _dump(m_shared) == _dump(m_plain)
    # every branch that validates a prior row ran on these real rows
    assert s_plain["matched"] + s_plain["matched_placeholder_twin"] > 0
    assert s_plain["prior_only_kept"] + s_plain["placeholder_twin_ambiguous"] > 0


def test_merge_prior_board_kept_prior_rows_share_keys(tmp_path, monkeypatch):
    merged, stats = _merge(tmp_path, monkeypatch, share=True)
    aged = [li for li in merged if (li.raw or {}).get("pulled_sale")]
    assert len(aged) >= 2
    k0, k1 = _keys(aged[0].raw, []), _keys(aged[1].raw, [])
    by0 = {k: k for k in k0}
    common = [k for k in k1 if k in by0]
    assert common and all(by0[k] is k for k in common)


# ---- value sharing (2026-10-07): raw['fema_disaster'] is one block on every row of a county ----------
import json as _json

from foreclosure_scraper.models import Listing as _Listing
from foreclosure_scraper.row_keys import SHARED_VALUE_KEYS, share_row


def _row(n, block):
    return {"source": "s", "source_url": "http://x", "state": "NC", "county": "Buncombe", "street_address": f"{n} Test St",
            "raw": {"fema_disaster": _json.loads(_json.dumps(block)), "calc": {"n": n}}}


def test_equal_blocks_on_different_rows_become_one_object():
    block = {"declarations": [{"n": 4827, "county": "Buncombe"}], "ia": 12}
    cache: dict = {}
    a = share_row(_row(1, block), cache)
    b = share_row(_row(2, block), cache)
    assert a["raw"]["fema_disaster"] is b["raw"]["fema_disaster"]
    assert a["raw"]["calc"] is not b["raw"]["calc"]             # row-specific values stay private


def test_different_blocks_stay_distinct():
    cache: dict = {}
    a = share_row(_row(1, {"declarations": [1]}), cache)
    b = share_row(_row(2, {"declarations": [2]}), cache)
    c = share_row(_row(3, {"declarations": [1]}), cache)
    assert a["raw"]["fema_disaster"] is not b["raw"]["fema_disaster"]
    assert a["raw"]["fema_disaster"] is c["raw"]["fema_disaster"]


def test_the_serialised_row_is_unchanged():
    block = {"declarations": [{"n": 1}], "ia": None}
    row = _row(1, block)
    before = _json.dumps(row, sort_keys=False)
    assert _json.dumps(share_row(row, {}), sort_keys=False) == before


def test_rows_without_the_block_or_with_an_odd_value_are_untouched():
    cache: dict = {}
    plain = {"raw": {"calc": {"x": 1}}}
    odd = {"raw": {"fema_disaster": "not a dict"}}
    none_raw = {"street_address": "no raw at all"}
    assert share_row(plain, cache) == plain
    assert share_row(odd, cache) == odd
    assert share_row(none_raw, cache) == none_raw


def test_sharing_survives_listing_validation():
    block = {"declarations": [{"n": 4827}], "ia": 3}
    cache: dict = {}
    la = _Listing.model_validate(share_row(_row(1, block), cache))
    lb = _Listing.model_validate(share_row(_row(2, block), cache))
    assert la.raw["fema_disaster"] is lb.raw["fema_disaster"]


def test_the_shared_keys_are_replaced_not_mutated_by_the_enricher():
    # the rule the docstring states: the FEMA enricher REPLACES raw['fema_disaster'] (dict(info)), so a shared
    # block is never changed in place for the other rows.
    src = __import__("pathlib").Path(__import__("foreclosure_scraper.enrichment_fema_disaster", fromlist=["x"]).__file__).read_text()
    assert 'li.raw["fema_disaster"] = dict(info)' in src
    assert SHARED_VALUE_KEYS == ("fema_disaster",)
