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
