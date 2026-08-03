"""Walk an ArcGIS Online app down to the layers (and filters) it actually shows.

Counties increasingly publish a "list" that is not a page at all: there is no
HTML table, no PDF, no CSV — just a Web Experience / Dashboard whose embedded
Web Map carries a ``definitionExpression`` on a shared county parcel layer. The
filter IS the list. Henderson County NC publishes its foreclosure parcels this
way: the parcel FeatureServer holds all ~60k parcels, and the only thing that
says WHICH 15 are in foreclosure is a definitionExpression buried three JSON
documents deep.

The chain (all public, all anonymous, no auth):

    /sharing/rest/content/items/<app id>/data?f=json      # Experience/Dashboard
      -> dataSources[*].itemId where type == WEB_MAP
    /sharing/rest/content/items/<webmap id>/data?f=json   # Web Map
      -> operationalLayers[*].{title,url,layerDefinition.definitionExpression}
    <layer url>/query?where=<that definitionExpression>   # the actual rows

This module does that walk GENERICALLY so other counties hiding a list the same
way cost one config dict instead of one scraper rewrite. Nothing here is
county-specific.

Two deliberate design choices:

* **Re-read every run.** The definitionExpression is the county's own live
  filter — a REID list that changes as parcels enter and leave foreclosure.
  Callers pass the expression straight through as the query WHERE rather than
  caching a parsed ID list, so the scrape is always current and works for any
  filter shape (``IN (...)``, ``OR`` chains, date ranges, compound predicates).
* **Trust boundary.** The expression is remote text spliced into a SQL WHERE, and
  the layer URL is remote text we would otherwise fetch. Both are validated:
  expressions containing statement-stacking / comment / DML syntax are rejected
  (:func:`is_safe_expression`), and callers pin the expected layer host
  (:func:`host_matches`) so a hijacked or re-pointed web map can't redirect the
  scrape at an unexpected server.

Free, public, anonymous ArcGIS REST throughout. The county-hosted parcel servers
(e.g. gisweb.hendersoncountync.gov) 403 a bare urllib request but return 200 to
the shared ``http_client`` because it sends a real browser User-Agent — a UA
header, not a CAPTCHA/WAF defeat.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence
from urllib.parse import urlencode, urlparse

import httpx
import structlog

log = structlog.get_logger()

DEFAULT_PORTAL = "https://www.arcgis.com"

#: ArcGIS item ids are 32 lowercase hex chars.
_ITEM_ID_RE = re.compile(r"\b[0-9a-f]{32}\b")

#: A definitionExpression is remote text we splice into a SQL WHERE clause.
#: Reject statement stacking, comment syntax, and anything that isn't a filter.
_SQL_UNSAFE = re.compile(
    r"(;|--|/\*|\*/|\bxp_\w|\bexec\b|\bdrop\b|\binsert\b|\bupdate\b|"
    r"\bdelete\b|\btruncate\b|\balter\b|\bgrant\b)", re.I)
_MAX_EXPR_CHARS = 30000

#: Above this encoded-query length we switch GET -> POST. ArcGIS REST accepts
#: both; long REID lists blow past common 4k/8k request-line limits.
_POST_THRESHOLD = 1800


class ArcGisError(RuntimeError):
    """An ArcGIS endpoint returned an error (including HTTP 200 + {"error":...}).

    Raised rather than swallowed on purpose: a filter/field-name drift that turns
    a live source into a silent 0 must surface as a scraper ERROR, not as a
    plausible-looking ZERO_RESULT.
    """


@dataclass(frozen=True)
class MapLayer:
    """One operational layer pulled out of a web map."""

    title: str | None = None
    url: str | None = None
    definition_expression: str | None = None
    item_id: str | None = None
    layer_id: Any = None

    @property
    def host(self) -> str:
        return urlparse(self.url or "").netloc.lower()


# --------------------------------------------------------------------------- #
# item fetch
# --------------------------------------------------------------------------- #

def item_data_url(item_id: str, portal: str = DEFAULT_PORTAL) -> str:
    return f"{portal.rstrip('/')}/sharing/rest/content/items/{item_id}/data"


async def fetch_item_data(http: httpx.AsyncClient, item_id: str,
                          portals: Sequence[str] = (DEFAULT_PORTAL,),
                          timeout: float = 30.0) -> dict:
    """Fetch an item's *data* document, trying each portal in turn.

    Org portals (``<org>.maps.arcgis.com``) and www.arcgis.com both serve public
    items; we try the caller's list so a private-org-only item still resolves.
    """
    last: Exception | None = None
    for portal in portals:
        url = item_data_url(item_id, portal)
        try:
            r = await http.get(url, params={"f": "json"}, timeout=timeout)
            if r.status_code != 200:
                last = ArcGisError(f"{url} -> HTTP {r.status_code}")
                continue
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            continue
        if not isinstance(data, dict):
            last = ArcGisError(f"{url} -> non-object payload")
            continue
        if data.get("error"):
            last = ArcGisError(f"{url} -> {str(data['error'])[:200]}")
            continue
        return data
    raise ArcGisError(f"item {item_id} unreadable: {last}")


def referenced_item_ids(data: dict) -> list[str]:
    """Item ids an app document points at, web maps first.

    Experience Builder keeps them in ``dataSources`` ({id: {type, itemId}});
    Dashboards and StoryMaps scatter ``itemId`` through their widget tree. We
    read the structured field when present and fall back to a hex scan so a
    layout we haven't seen still resolves.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(v: Any) -> None:
        if isinstance(v, str) and _ITEM_ID_RE.fullmatch(v) and v not in seen:
            seen.add(v)
            out.append(v)

    ds = data.get("dataSources")
    if isinstance(ds, dict):
        # Web maps first — they're the ones that carry operationalLayers.
        for want_map in (True, False):
            for spec in ds.values():
                if not isinstance(spec, dict):
                    continue
                is_map = str(spec.get("type") or "").upper().replace("_", "") == "WEBMAP"
                if is_map is want_map:
                    _add(spec.get("itemId"))

    def _walk(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("itemId", "webmap", "mapItemId") and isinstance(v, str):
                    _add(v)
                else:
                    _walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                _walk(v, depth + 1)

    _walk(data)
    return out


# --------------------------------------------------------------------------- #
# layer extraction
# --------------------------------------------------------------------------- #

def _definition_expression(node: dict) -> str | None:
    """definitionExpression lives under layerDefinition, but some authoring
    clients write it at the top level of the layer entry."""
    for holder in (node.get("layerDefinition"), node):
        if isinstance(holder, dict):
            expr = holder.get("definitionExpression")
            if isinstance(expr, str) and expr.strip():
                return expr.strip()
    return None


def _child_url(parent_url: str | None, node: dict) -> str | None:
    """Sub-layers of a MapServer entry carry an ``id`` instead of a full URL."""
    url = node.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    lid = node.get("id")
    if parent_url and isinstance(lid, int):
        return f"{parent_url.rstrip('/')}/{lid}"
    return None


def extract_layers(webmap: dict, item_id: str | None = None) -> list[MapLayer]:
    """Flatten a web map's operationalLayers (+ group/sub layers + tables)."""
    out: list[MapLayer] = []

    def _visit(node: Any, parent_url: str | None, depth: int) -> None:
        if depth > 6 or not isinstance(node, dict):
            return
        url = _child_url(parent_url, node)
        title = node.get("title") or node.get("name")
        expr = _definition_expression(node)
        if url or expr:
            out.append(MapLayer(
                title=(str(title).strip() if title else None),
                url=url,
                definition_expression=expr,
                item_id=item_id,
                layer_id=node.get("id"),
            ))
        for key in ("layers", "featureCollection", "layerGroup"):
            child = node.get(key)
            if isinstance(child, dict):
                child = child.get("layers")
            if isinstance(child, list):
                for c in child:
                    _visit(c, url or parent_url, depth + 1)

    for key in ("operationalLayers", "tables"):
        for node in webmap.get(key) or []:
            _visit(node, None, 0)
    return out


async def walk_layers(http: httpx.AsyncClient, item_id: str,
                      portals: Sequence[str] = (DEFAULT_PORTAL,),
                      max_depth: int = 2, timeout: float = 30.0) -> list[MapLayer]:
    """Resolve an app/web-map item id to its flattened layer list.

    Accepts either end of the chain: hand it an Experience Builder / Dashboard
    item and it follows the embedded web map(s); hand it a web map item and it
    reads the layers directly.
    """
    seen: set[str] = set()
    layers: list[MapLayer] = []

    async def _resolve(iid: str, depth: int) -> None:
        if iid in seen or depth > max_depth:
            return
        seen.add(iid)
        data = await fetch_item_data(http, iid, portals=portals, timeout=timeout)
        if data.get("operationalLayers") or data.get("tables"):
            found = extract_layers(data, item_id=iid)
            log.info("arcgis_webmap.layers", item=iid, layers=len(found))
            layers.extend(found)
            return
        for child in referenced_item_ids(data):
            await _resolve(child, depth + 1)

    await _resolve(item_id, 0)
    return layers


def find_layer(layers: Iterable[MapLayer], title_pattern: str,
               require_definition: bool = True) -> MapLayer | None:
    """First layer whose title matches, preferring one that carries a filter."""
    pat = re.compile(title_pattern, re.I)
    fallback: MapLayer | None = None
    for lyr in layers:
        if not lyr.title or not pat.search(lyr.title):
            continue
        if lyr.definition_expression:
            return lyr
        fallback = fallback or lyr
    return None if require_definition else fallback


# --------------------------------------------------------------------------- #
# expression handling
# --------------------------------------------------------------------------- #

def is_safe_expression(expr: str | None) -> bool:
    """Reject a remote definitionExpression that isn't a plain filter."""
    if not expr or not expr.strip():
        return False
    if len(expr) > _MAX_EXPR_CHARS:
        return False
    return not _SQL_UNSAFE.search(expr)


def host_matches(url: str | None, allowed_hosts: Sequence[str]) -> bool:
    """True when ``url``'s host is (or is a subdomain of) an allowed host."""
    host = urlparse(url or "").netloc.lower().split(":")[0]
    if not host:
        return False
    return any(host == a.lower() or host.endswith("." + a.lower()) for a in allowed_hosts)


def literal_values(expr: str, field_name: str | None = None) -> list[str]:
    """Pull the quoted/numeric literals out of a filter, in order, deduped.

    Handles both shapes counties actually author:
    ``REID = '1' OR REID = '2'`` and ``REID IN ('1','2')``. Purely for
    observability/logging — the expression itself is what gets queried, so a
    parse miss here never costs rows.
    """
    if not expr:
        return []
    fld = re.escape(field_name) if field_name else r"[A-Za-z_][\w.]*"
    out: list[str] = []
    seen: set[str] = set()

    def _add(v: str) -> None:
        v = v.strip().strip("'\"").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    for m in re.finditer(rf"{fld}\s*=\s*('(?:[^']|'')*'|[-\d.]+)", expr, re.I):
        _add(m.group(1).replace("''", "'"))
    for m in re.finditer(rf"{fld}\s+IN\s*\(([^)]*)\)", expr, re.I):
        for part in m.group(1).split(","):
            _add(part.replace("''", "'"))
    return out


# --------------------------------------------------------------------------- #
# querying
# --------------------------------------------------------------------------- #

def _query_url(layer_url: str) -> str:
    u = layer_url.rstrip("/")
    return u if u.endswith("/query") else u + "/query"


async def query_features(
    http: httpx.AsyncClient,
    layer_url: str,
    *,
    out_fields: str,
    where: str = "1=1",
    return_geometry: bool = False,
    out_sr: int | str = 4326,
    page: int = 1000,
    max_records: int | None = None,
    order_by: str | None = None,
    timeout: float = 40.0,
    extra: dict[str, str] | None = None,
) -> list[dict]:
    """Paginated ``/query``. Returns raw features (``attributes`` + ``geometry``).

    Pagination follows the ArcGIS contract: ``resultOffset`` + ``resultRecordCount``,
    stopping when ``exceededTransferLimit`` is false/absent or a short page comes
    back. A repeated-OBJECTID guard catches the older MapServer layers that
    silently ignore ``resultOffset`` (which would otherwise loop forever).

    ``out_fields`` is REQUIRED and may not be ``"*"``. Enumerating fields keeps
    us from ever pulling columns a layer shouldn't be exposing (some public NC
    parcel layers carry taxpayer identifiers); we take only what we name.
    """
    if not out_fields or out_fields.strip() == "*":
        raise ValueError("out_fields must be an explicit field list, never '*'")
    if not is_safe_expression(where):
        raise ArcGisError(f"unsafe/empty where clause rejected: {str(where)[:120]!r}")

    url = _query_url(layer_url)
    out: list[dict] = []
    seen_oids: set[Any] = set()
    offset = 0

    while True:
        params: dict[str, str] = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "resultOffset": str(offset),
            "resultRecordCount": str(page),
            "f": "json",
        }
        if return_geometry:
            params["outSR"] = str(out_sr)
        if order_by:
            params["orderByFields"] = order_by
        if extra:
            params.update(extra)

        if len(urlencode(params)) > _POST_THRESHOLD:
            r = await http.post(url, data=params, timeout=timeout)
        else:
            r = await http.get(url, params=params, timeout=timeout)
        if r.status_code != 200:
            raise ArcGisError(f"{url} -> HTTP {r.status_code}")
        data = r.json()
        if not isinstance(data, dict):
            raise ArcGisError(f"{url} -> non-object payload")
        if data.get("error"):
            # HTTP 200 + an error body is the classic silent-death shape.
            raise ArcGisError(f"{url} -> {str(data['error'])[:300]}")

        feats = data.get("features") or []
        oid_field = data.get("objectIdFieldName") or "OBJECTID"
        fresh = 0
        for ft in feats:
            oid = (ft.get("attributes") or {}).get(oid_field)
            if oid is not None:
                if oid in seen_oids:
                    continue
                seen_oids.add(oid)
            fresh += 1
            out.append(ft)
            if max_records and len(out) >= max_records:
                return out

        if not feats or fresh == 0:
            break
        if data.get("exceededTransferLimit") is not True and len(feats) < page:
            break
        if data.get("exceededTransferLimit") is False:
            break
        offset += len(feats)

    return out


async def query_attributes(http: httpx.AsyncClient, layer_url: str, **kw) -> list[dict]:
    """:func:`query_features` reduced to the attribute dicts."""
    return [(f.get("attributes") or {}) for f in await query_features(http, layer_url, **kw)]
