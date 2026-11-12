"""Private helpers (the registry skips modules whose name starts with "_") for verifiers that read
a public ArcGIS FeatureServer layer: the query URLs, a whole-layer paged load through the sweep's
`client` (GET only, so the Fetcher's per-host pacing and capture apply), the layer's own edit
stamps, and a per-run cache.

ONE LOAD PER LAYER PER SWEEP RUN. The first row that needs a layer loads it (metadata, a
returnCountOnly count, then resultOffset pages of `page` rows) and every later row of the same
sweep reads the in-memory snapshot; concurrent callers share one load. The cache is keyed by the
`client`, which the sweep creates once per run, so it dies with the run. A layer of a few
thousand rows is 3-4 requests per run however many board rows ask about it, which is cheaper
than any per-row or per-batch query (verify() sees one row at a time).

COMPLETENESS. A snapshot is `complete` only when the count request answered, the pages loaded
without an error, and the rows loaded equal the count. A verifier must not decide "no such case"
or "dropped off" from an incomplete snapshot (the same rule the jail verifier applies to an
unhealthy roster).

out_fields is always an explicit list: a verifier names exactly the columns it reads, so a
personal column on the layer (an owner, a phone, an email, a free-text note) is never fetched.
"""
from __future__ import annotations

import asyncio
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from ..core import iso_z, utc_now


def query_url(layer: str, params: dict) -> str:
    """`layer`/query with `params` + f=json, in a fixed order (test fixtures key on the URL)."""
    return f"{layer}/query?{urlencode({**params, 'f': 'json'})}"


def meta_url(layer: str) -> str:
    return f"{layer}?f=json"


def count_url(layer: str, where: str = "1=1") -> str:
    return query_url(layer, {"where": where, "returnCountOnly": "true"})


def page_url(layer: str, *, out_fields: str, order_by: str, offset: int, page: int,
             where: str = "1=1") -> str:
    return query_url(layer, {"where": where, "outFields": out_fields, "returnGeometry": "false",
                             "orderByFields": order_by, "resultOffset": str(offset),
                             "resultRecordCount": str(page)})


def epoch_iso(v: Any) -> Optional[str]:
    """An ArcGIS epoch-milliseconds value as an ISO-Z timestamp, else None."""
    try:
        return iso_z(datetime.fromtimestamp(float(v) / 1000.0, tz=timezone.utc))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def epoch_date(v: Any) -> Optional[str]:
    s = epoch_iso(v)
    return s[:10] if s else None


@dataclass
class LayerSnapshot:
    layer: str
    rows: list[dict]                       # attribute dicts, in order_by order
    count: Optional[int]                   # the layer's own returnCountOnly answer
    fetched_at: str
    data_last_edit: Optional[str] = None   # editingInfo.dataLastEditDate (ISO-Z)
    error: Optional[str] = None
    cache: dict = field(default_factory=dict)   # per-snapshot derived indexes (verifier-owned)

    @property
    def complete(self) -> bool:
        return (self.error is None and self.count is not None and self.count > 0
                and len(self.rows) == self.count)

    @property
    def health(self) -> str:
        if self.error is not None:
            return "layer_unavailable"
        if not self.count:
            return "layer_empty"
        if len(self.rows) != self.count:
            return "layer_incomplete"
        return "ok"

    def evidence(self) -> dict:
        out = {"layer": self.layer, "fetched_at": self.fetched_at, "layer_count": self.count,
               "layer_rows_loaded": len(self.rows), "layer_data_last_edit": self.data_last_edit}
        if self.error:
            out["layer_error"] = self.error
        return {k: v for k, v in out.items() if v is not None}


async def _get(client: Any, url: str) -> Any:
    data = await client.get_json(url)
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"ArcGIS error: {str(data['error'])[:200]}")
    return data


async def load_layer(client: Any, layer: str, *, out_fields: str, order_by: str,
                     page: int = 2000, max_pages: int = 50) -> LayerSnapshot:
    """The whole layer (explicit out_fields, no geometry) plus its count and edit stamps.
    Never raises: a failure is recorded in `error` and the snapshot is not complete."""
    fetched = iso_z(utc_now())
    rows: list[dict] = []
    count: Optional[int] = None
    last_edit: Optional[str] = None
    try:
        meta = await _get(client, meta_url(layer))
        last_edit = epoch_iso(((meta or {}).get("editingInfo") or {}).get("dataLastEditDate"))
        count = int((await _get(client, count_url(layer)) or {}).get("count"))
        for i in range(max_pages):
            data = await _get(client, page_url(layer, out_fields=out_fields, order_by=order_by,
                                               offset=i * page, page=page))
            feats = (data or {}).get("features") or []
            rows.extend((f.get("attributes") or {}) for f in feats)
            if not feats or (len(feats) < page and not data.get("exceededTransferLimit")):
                break
            if len(rows) >= count:
                break
    except Exception as exc:  # noqa: BLE001 - the verifier answers unconfirmed on this
        return LayerSnapshot(layer=layer, rows=rows, count=count, fetched_at=fetched,
                             data_last_edit=last_edit,
                             error=f"{type(exc).__name__}: {str(exc)[:200]}")
    return LayerSnapshot(layer=layer, rows=rows, count=count, fetched_at=fetched,
                         data_last_edit=last_edit)


# client -> {layer: LayerSnapshot | asyncio.Task}: a per-run cache (the sweep makes one client
# per run); it dies with the client.
_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


async def layer_for(client: Any, layer: str, *, out_fields: str, order_by: str,
                    page: int = 2000) -> LayerSnapshot:
    """The layer for this sweep run: loaded by the first row that needs it, shared by every
    later row (and by concurrent callers) of the same `client`."""
    try:
        per_run = _RUNS.setdefault(client, {})
    except TypeError:                                   # not weak-referenceable: no sharing
        per_run = {}
    entry = per_run.get(layer)
    if isinstance(entry, LayerSnapshot):
        return entry
    loop = asyncio.get_running_loop()
    if not (isinstance(entry, asyncio.Task) and entry.get_loop() is loop):
        entry = loop.create_task(load_layer(client, layer, out_fields=out_fields,
                                            order_by=order_by, page=page))
        per_run[layer] = entry

        def _done(t: asyncio.Task, per_run=per_run, layer=layer) -> None:
            if not t.cancelled() and t.exception() is None:
                per_run[layer] = t.result()
        entry.add_done_callback(_done)
    # shield: a row timing out while the layer loads must not cancel the load for the rest
    return await asyncio.shield(entry)
