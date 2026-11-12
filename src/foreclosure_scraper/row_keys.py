"""One shared str object per distinct dict key across rows parsed one at a time from JSON.

WHY. The board is read back row by row in two places: ``checkpoint.load()`` (every resume) and
``board_persist.merge_prior_board()`` (every full run streams the prior published board). Each
row is decoded by its own ``JSONDecoder.raw_decode`` call, and CPython's decoder shares repeated
key strings only WITHIN one call, so every row gets private copies of every key of its ``raw``
tree ("situs_address_source", "fallback_links", ... a few hundred per row). Measured on the VM
(2026-10-06) loading the 10/5 pre_publish checkpoint, 270,481 rows: 14,930 MiB as parsed, 11,235
MiB with the keys shared (-25%); at 355,000 rows 20,267 vs 15,213 MiB. A full run holds the prior
board's rows (prior-only rows and the prior side of every match) for its whole length.

Only KEYS are shared, and only by identity: the values, the key order and therefore every
model_dump / json.dumps of the result are unchanged. The cache is a plain dict owned by the
caller for one load (not sys.intern), so nothing outlives the rows that use it.

VALUES (2026-10-07). ``raw['fema_disaster']`` is the SAME declaration block on every row (4.7 KB of
JSON, present on 100% of rows, 44% of all bytes of the 350,013-row board): in memory it is one object
shared by reference while the run holds it, but each row read back from JSON gets a private copy. The
second full run was killed by the memory watchdog at 25.6 GB inside merge_prior_board for exactly that
reason (the prior board grew from 223,832 to 350,013 rows and its copies of this one block alone were
about 40% of the heap). ``share_row`` also replaces such repeated block values by one equal object, so
every model_dump / json.dumps is unchanged. Nothing in the pipeline mutates the block in place (the
enrichers REPLACE ``raw['fema_disaster']``); keep it that way for every key listed here.
"""
from __future__ import annotations


def share_keys(obj, cache: dict):
    """``obj`` rebuilt with every str dict key (at any depth) replaced by ``cache``'s copy of it.

    Dicts and lists are rebuilt (same order); every other value is returned as is."""
    if type(obj) is dict:
        return {(cache.setdefault(k, k) if type(k) is str else k): share_keys(v, cache)
                for k, v in obj.items()}
    if type(obj) is list:
        return [share_keys(v, cache) for v in obj]
    return obj


#: raw keys whose value is the same block on (nearly) every row, shared by equality when read back.
SHARED_VALUE_KEYS = ("fema_disaster",)
_MAX_CANONICAL = 512


def share_row(rec, cache: dict):
    """``share_keys(rec, cache)`` plus one shared object per distinct value of each SHARED_VALUE_KEYS."""
    out = share_keys(rec, cache)
    raw = out.get("raw") if type(out) is dict else None
    if type(raw) is dict:
        for key in SHARED_VALUE_KEYS:
            val = raw.get(key)
            if type(val) is dict and val:
                raw[key] = _canonical(cache, key, val)
    return out


def _canonical(cache: dict, key: str, val: dict):
    pool = cache.setdefault(("__shared_values__", key), [])
    for i, known in enumerate(pool):
        if known == val:
            if i:
                pool.insert(0, pool.pop(i))     # most recently matched first: runs of one county are common
            return known
    if len(pool) < _MAX_CANONICAL:
        pool.insert(0, val)
    return val

