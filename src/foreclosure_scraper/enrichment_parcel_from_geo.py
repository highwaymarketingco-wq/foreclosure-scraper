"""Resolve a parcel_id for geo-bearing (or address-bearing) leads that have none.

Root cause this closes
----------------------
52% of leads carry a parcel_id; the rest do not. 2054 of the parcel-less leads
DO have lat/lng, and another ~1468 have a street_address. Today nothing turns
those into a parcel:

  * ``enrichment_parcel_lookup`` runs the OTHER direction — it needs a
    parcel_id (or one extractable from description text) ALREADY present, then
    looks up address/specs. It never *derives* a parcel from coordinates.
  * ``enrichment_parcel_reverse_geo`` also requires ``li.parcel_id`` up front;
    it reverse-geocodes a centroid to an approximate address, not a parcel.
  * ``parcel_resolver.resolve_sc_parcel_key`` DOES point-in-polygon, but it is
    (a) only invoked from the assessor-card enricher (gated behind
    ``ASSESSOR_CARD_ON``), (b) limited to 5 SC counties via ``_SC_KEY_FIELD``,
    and (c) returns a county-specific key string for the adapter rather than
    writing ``li.parcel_id``. So the 2054 geo-bearing leads stay parcel-less.

A live probe (2026-06-25) confirmed both statewide layers return a parcel id on
a simple point query for every in-scope county:

  * SC: SCDOT ``SC_Parcels`` MapServer, one layer per county. The parcel-id
    field name varies (Spartanburg ``TAXPIN``, Anderson/Laurens ``TMS``,
    Greenville/Beaufort/Pickens ``PIN``, Oconee ``TMS_NUMBER``, Union
    ``ParcelID`` …) — handled by the existing ``_scdot_parcel`` priority list.
  * NC: NC OneMap ``NC1Map_Parcels`` FeatureServer/1, statewide, parcel field
    ``parno`` (resolves Gaston/Buncombe/Henderson/Forsyth/McDowell/Polk/Lincoln/
    Guilford/Rutherford/Cleveland …). CORRECTION 2026-09-28: the line that used
    to stand here ("Cleveland parcels are absent from this statewide layer") was
    stale — a live re-check (10/10 real Cleveland lat/lng pairs, immediate point
    query + envelope retry) resolved every one with a correct ``cntyname:
    'Cleveland'`` and real ``parno``. Cleveland's low identity rate on the board
    traces to this session's parcel_from_geo runs getting cut short by NC
    OneMap's own circuit breaker / token-wall interruptions before reaching most
    of Cleveland's rows, not to a coverage gap. Don't build a native-NC fallback
    for Cleveland on the strength of the old note; re-run the resolver instead
    (``scripts/resolver_backfill_parcel.py``, chunked/checkpointed to survive an
    interruption).

This module is point-in-polygon FIRST (lat/lng -> parcel), with an
address->parcel fallback (geocode the street to a point via the same county
GIS, then point query) only for leads that have a street_address but no
coordinates. Free, pure-HTTP, no auth. Writes ONLY ``li.parcel_id`` (and a
small provenance blob under ``raw.parcel_from_geo``); never touches address,
value, or owner — the downstream GIS-attrs track consumes the new parcel_id.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

import httpx
import structlog
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .enrichment_arcgis import (
    SCDOT_BASE, SC_LAYER,
    scdot_walled, mark_scdot_walled, is_scdot_token_error,  # noqa: F401  (compat)
    host_walled, mark_host_walled, note_host_ok, note_host_hard_failure,
    is_token_error,
)
from .http_client import client
from .models import Listing
from .parcel_cache import PARCEL_LAYERS
from .parcel_inventory import _scdot_parcel

log = structlog.get_logger()

# Counties whose OWN county-hosted ArcGIS layer (already verified for
# parcel_cache.py's offline bulk cache -- PARCEL_LAYERS[county]) has been
# LIVE-CONFIRMED to also answer a geometry (point-in-polygon) query, not just
# an attribute query. This is what lets a lat/lng-bearing lead resolve a
# parcel_id when SCDOT is token-walled (2026-08-12, still dead 2026-09-28:
# every query returns HTTP 200 + {"error":{"code":499,"message":"Token
# Required"}}) -- SCDOT was the ONLY point-parcel source in this module before
# this addition (see the module docstring's I-09 gap: "geometry availability
# per layer is unverified").
#
# Anderson verified live 2026-09-28: `gis.cityofandersonsc.com`'s
# `WaterUtilities/County_Parcels/FeatureServer/0` (the exact URL
# PARCEL_LAYERS["Anderson"]["url"] already points at) answers
# geometryType=esriGeometryPoint with a real TMS -- confirmed by deriving a
# parcel's own centroid from its returned polygon and querying that point back
# (round-trip match). Point-in-polygon needs no address field at all, so it
# resolves leads whose PHYS_ADDR the layer never populated (that field is only
# ~39% numbered on this layer -- a real data gap, not a query-capability one).
# Tested against the 150 Anderson SC board leads with no parcel_id from the
# three national feeds that caused the 36%->28% flip-lane regression
# (fannie_homepath, usda_properties, terry_howe_auctions): 92 of 150 (61%)
# newly resolve a parcel_id (48 by address match, 44 more by point-in-polygon
# on leads whose only coordinate was a real geocode, not the Anderson
# county-seat centroid fallback (34.504, -82.650) that ~30 of the 150 carry
# instead of a real per-property point -- those are correctly left
# unresolved here rather than silently attached to a random neighbour's
# parcel).
#
# Only add a county here after live-verifying ITS OWN layer answers a
# geometry query the same way -- do not assume it from the attribute-query
# entry in PARCEL_LAYERS alone.
NATIVE_SC_POINT_CAPABLE: frozenset[str] = frozenset({"Anderson"})

# NC statewide parcel layer (same service already used by enrichment_owner_mailing
# / enrichment_bankruptcy_property). One consistent schema across all 100 NC
# counties; parcel id in ``parno``, county in ``cntyname``.
NC_ONEMAP_PARCELS = (
    "https://services.nconemap.gov/secure/rest/services/"
    "NC1Map_Parcels/FeatureServer/1/query"
)

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126"}

# Rough NC+SC bounding box — reject (0,0) and out-of-area coords that would
# point-query the wrong place (or nothing).
_LAT_MIN, _LAT_MAX = 32.0, 37.0
_LON_MIN, _LON_MAX = -84.5, -75.0


def _norm_county(county: Optional[str]) -> str:
    """'Spartanburg County, SC' -> 'Spartanburg'."""
    c = (county or "").replace(" County", "").strip()
    for suffix in (", NC", ", SC", ",NC", ",SC"):
        if c.upper().endswith(suffix):
            c = c[: -len(suffix)].strip()
    return c.split(",")[0].strip().title()


def _in_box(li: Listing) -> bool:
    return (
        li.latitude is not None
        and li.longitude is not None
        and _LAT_MIN <= li.latitude <= _LAT_MAX
        and _LON_MIN <= li.longitude <= _LON_MAX
    )


def _clean_parcel(pid: Any) -> str:
    """Reject blank/placeholder parcel ids only -- NOT by length.

    Found 2026-09-15: this used to also reject anything under 5 characters
    (matching a length gate in enrichment_arcgis.py's address-match path,
    on the theory that "real APNs have meaningful structure"). That's false --
    live-verified against Cleveland County NC: NC OneMap's `parno` field
    returns bare ids like '1020' (4 chars) for real, owned, assessed parcels
    (confirmed via a direct _point_query() call: full owner name, address and
    market value came back attached to that exact id). The length floor was
    silently discarding every short-format parcel id NC OneMap returned,
    board-wide, for any county using a short numeric parno convention -- not
    a hypothetical edge case, a confirmed live failure. Parcel-id format
    varies by county (bare sequential ints vs. long formatted PINs like
    '6804-28-5537.00'); length is not a valid plausibility signal.
    """
    s = str(pid or "").strip()
    if not s or s.isspace() or s in ("0", "0.0"):
        return ""
    return s


# Half-width of the fallback envelope, in degrees. ~5.5 m at NC/SC latitude —
# tight enough that it lands inside the intended parcel, wide enough to survive
# the server's spatial-index tolerance. Measured on 25 live geo-only leads:
# 5e-5 -> 13 unique / 4 ambiguous / 8 empty; 1e-4 -> 14 unique / 9 ambiguous.
# The bigger box buys one extra hit and more than doubles ambiguity, so 5e-5 it is.
_ENVELOPE_HALF_DEG = 5e-5


class _ArcHardError(Exception):
    """A non-200 ArcGIS response, retried the same as a transport error before
    counting toward the host breaker (see _arc_query)."""


# Hard wall-clock ceiling for a SINGLE ArcGIS query attempt, enforced by
# asyncio.wait_for() below regardless of what httpx's own timeout thinks is
# happening. Env-tunable so a test can shrink it instead of waiting out the
# real 25s default.
#
# Diagnosed 2026-09-30 (a resolver_backfill_parcel.py run against real data):
# chunk 2 stalled with a TCP connection to an ArcGIS host sitting ESTABLISHED,
# unchanged, for 4.5+ minutes — 2-10x past this module's own documented
# worst case (25s timeout x 3 tenacity retries = 80-160s). Root cause: httpx's
# `timeout=` (and the client's httpx.Timeout(read=..., connect=..., pool=...)
# in http_client.client()) bounds each individual connect/write/read
# *operation*, not the total request. httpcore issues a FRESH
# `read(timeout=...)` call for every chunk of a response it parses
# (httpcore/_async/http11.py's `_receive_event`, called in a loop by
# `_receive_response_body`) — so a peer that trickles data (or answers just
# often enough to keep resetting that per-chunk clock) without ever
# completing the response defeats the configured timeout entirely: no
# exception is ever raised, no matter how long it runs. The prior code also
# passed a redundant `timeout=25.0` on this specific call, which silently
# widened the client's tuned connect=8s/pool=8s hardening (see
# http_client.client()'s HTTP_CONNECT_TIMEOUT/HTTP_POOL_TIMEOUT) back up to
# 25s on every ArcGIS request — removed below so that hardening applies here
# too.
_ARC_HARD_TIMEOUT_S = float(os.environ.get("ARC_QUERY_HARD_TIMEOUT_S", "25.0"))


async def _arc_query(
    c, layer_query_url: str, params: dict, *, hard_timeout: float = _ARC_HARD_TIMEOUT_S
) -> Optional[list]:
    """GET an ArcGIS /query and return its feature list (None on any failure).
    ArcGIS reports failure as HTTP 200 + an `error` key, so status alone is not
    enough — a token-required response looks exactly like an empty result set.

    Retries up to 3 times (short exponential-jitter backoff) on a transport
    error, a non-200 status, or a `hard_timeout` trip before counting it
    toward the host breaker. Diagnosed 2026-09-28: NC OneMap tripped its
    8-consecutive-failures breaker mid-run despite answering ~1,766 leads
    cleanly just before (55% hit rate) and probing healthy again minutes
    later — the signature of a short-lived blip, not a dead host, and this
    call had zero retry cushioning unlike get_text() elsewhere in this
    codebase. A genuine token/auth wall (SCDOT-class) still trips the host on
    its FIRST occurrence, unaffected by this retry (that branch never raises,
    so AsyncRetrying never sees it).

    Every attempt is wrapped in `asyncio.wait_for(..., hard_timeout)` — a
    backstop that doesn't care what httpx's own timeout thinks is happening
    (see the module-level comment on `_ARC_HARD_TIMEOUT_S` for why that
    matters). `hard_timeout` is a parameter, not just the module constant, so
    a test can exercise a real hung endpoint without waiting out the real
    default."""
    # Generic per-host breaker: skip a host that's already been tripped (token
    # wall or repeated timeouts) instead of re-hitting it for every lead.
    if host_walled(layer_query_url):
        return None
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=1, max=8),
            retry=retry_if_exception_type(
                (httpx.TransportError, httpx.TimeoutException, TimeoutError, _ArcHardError)
            ),
            reraise=True,
        ):
            with attempt:
                # No per-call `timeout=` on c.get(): let the client's own
                # httpx.Timeout (connect/pool/read/write all set — see
                # http_client.client()) apply, and let asyncio.wait_for be the
                # ONE hard ceiling on total attempt duration.
                r = await asyncio.wait_for(
                    c.get(layer_query_url, params=params), timeout=hard_timeout
                )
                if r.status_code != 200:
                    raise _ArcHardError(f"HTTP {r.status_code}")
                data = r.json()
                if "error" in data:
                    # A token/auth wall (SCDOT-class) trips the host immediately so
                    # no later lead re-hits it; an ordinary query error (bad where
                    # clause) does not, and neither raises for retry — it's a clean
                    # per-request answer, not a transient failure.
                    if is_token_error(data):
                        mark_host_walled(layer_query_url, reason="token/auth error")
                    return None
                note_host_ok(layer_query_url)
                return data.get("features") or []
    except (_ArcHardError, httpx.TransportError, httpx.TimeoutException, TimeoutError):
        note_host_hard_failure(layer_query_url)
        return None
    except Exception:  # noqa: BLE001  (anything else — still a HARD failure)
        note_host_hard_failure(layer_query_url)
        return None


async def _point_query(
    c, layer_query_url: str, lat: float, lon: float, out_fields: str = "*"
) -> Optional[dict[str, Any]]:
    """Resolve the parcel polygon containing (lat, lon) — point first, then a
    tiny envelope.

    NC OneMap's NC1Map_Parcels currently answers EVERY esriGeometryPoint query
    with HTTP 200 and zero features — verified 2026-07-27 against Buncombe,
    downtown Asheville and downtown Raleigh, on a layer that reports 5,938,639
    parcels and happily returns rows for an attribute query. A silent
    always-empty spatial filter, not a coverage gap. The identical query with
    geometryType=esriGeometryEnvelope returns the right parcel, so we retry as a
    ~5.5 m box around the same point.

    The envelope result is accepted ONLY when it matches exactly one parcel.
    A box straddling a boundary returns several, and picking features[0] there
    would write a confidently wrong neighbouring parcel onto the lead — worse
    than leaving it unresolved. Point-in-polygon needs no such guard because it
    is unique by construction.
    """
    base = {
        "geometryType": "esriGeometryPoint",
        "geometry": f"{lon},{lat}",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
    }
    feats = await _arc_query(c, layer_query_url, base)
    if feats:
        return dict(feats[0].get("attributes") or {})
    if feats is None:
        return None  # hard failure (HTTP error / ArcGIS error) — don't re-hit

    d = _ENVELOPE_HALF_DEG
    env = dict(base)
    env["geometryType"] = "esriGeometryEnvelope"
    env["geometry"] = json.dumps({
        "xmin": lon - d, "ymin": lat - d, "xmax": lon + d, "ymax": lat + d,
        "spatialReference": {"wkid": 4326},
    })
    env["resultRecordCount"] = 2  # only need to know "exactly one" vs "several"
    feats = await _arc_query(c, layer_query_url, env)
    if not feats or len(feats) != 1:
        return None
    return dict(feats[0].get("attributes") or {})


async def _parcel_from_point_sc(c, li: Listing) -> tuple[str, str]:
    """Returns (parcel_id, source_tag). source_tag is 'scdot_point' or, for a
    county resolved via its own layer instead, 'native_point:<County>'."""
    county = _norm_county(li.county)
    pid = ""
    source = "scdot_point"

    # SCDOT first (statewide, one shared host). Once its token wall is tripped,
    # host_walled() short-circuits every subsequent SC lead — no re-hit.
    if not scdot_walled():
        layer = SC_LAYER.get(county)
        if layer is not None:
            attrs = await _point_query(c, f"{SCDOT_BASE}/{layer}/query", li.latitude, li.longitude)
            if attrs:
                # _scdot_parcel walks the per-county field-name priority list (TAXPIN,
                # TMS, TMS_NUMBER, PIN via fallback, ParcelID, …) for the unique id.
                pid = _scdot_parcel(attrs)
                if not pid:
                    # Some county layers only expose PIN (Greenville/Beaufort/Pickens).
                    for f in ("PIN", "PARNO", "PARID", "Parcel_ID", "PARCEL_ID"):
                        if attrs.get(f):
                            pid = str(attrs[f]).strip()
                            break

    if not pid and county in NATIVE_SC_POINT_CAPABLE:
        # SCDOT is walled (or answered with nothing) — fall back to the county's
        # OWN ArcGIS layer, on its own host, so it isn't caught by SCDOT's breaker.
        # This is the same PARCEL_LAYERS entry parcel_cache.py already trusts for
        # its offline bulk cache; only counties live-verified to also answer a
        # geometry query are listed in NATIVE_SC_POINT_CAPABLE.
        native = PARCEL_LAYERS.get(county)
        id_field = (native.get("id_fields") or [None])[0] if native else None
        if native and id_field and not host_walled(native["url"]):
            attrs = await _point_query(c, native["url"], li.latitude, li.longitude, out_fields=id_field)
            if attrs and attrs.get(id_field):
                pid = str(attrs[id_field]).strip()
                source = f"native_point:{county}"

    return _clean_parcel(pid), source


# The matched OneMap record already carries the SITUS address, city and ZIP —
# the very fields the next enricher would otherwise re-query a county layer for.
# `siteadd` / `scity` / `szip` are names enrichment_arcgis._ADDR_FIELD_CANDIDATES
# and enrichment_situs_address already recognise, so stashing the bag lets
# enrich_situs_address resolve the address from cache with ZERO extra HTTP.
_NC_OUT_FIELDS = (
    "parno,cntyname,siteadd,sunit,scity,sstate,szip,"
    "saddno,saddpref,saddstname,saddsttyp,saddstsuf,ownname,parval"
)


async def _parcel_from_point_nc(c, li: Listing) -> str:
    # NC OneMap is the ONLY NC point-parcel source here; if it's tripped (token
    # wall on its /secure/ path, or repeated timeouts) skip it — re-hitting it for
    # every NC lead is the SCDOT-class 16h hang. (_point_query fires TWO 25s calls
    # per lead, so an unguarded degradation is especially expensive here.)
    if host_walled(NC_ONEMAP_PARCELS):
        return ""
    attrs = await _point_query(
        c, NC_ONEMAP_PARCELS, li.latitude, li.longitude, out_fields=_NC_OUT_FIELDS
    )
    if not attrs:
        return ""
    # County guard: the statewide layer could in theory return a neighbouring
    # county's parcel for a point near a border. Only trust it when cntyname
    # agrees with the lead's county (when both are known).
    want = _norm_county(li.county)
    got = str(attrs.get("cntyname") or "").strip().title()
    if want and got and want != got:
        return ""
    pid = _clean_parcel(attrs.get("parno"))
    if pid and isinstance(li.raw, dict) and not li.raw.get("gis_attrs_full"):
        # Only when absent: a county-layer bag stashed by gis_attrs is richer
        # than the statewide one and must not be clobbered.
        cleaned = _clean_nc_situs(attrs)
        li.raw["gis_attrs_full"] = cleaned
        road = cleaned.get(_NC_ROAD_ONLY_KEY)
        if road:
            # Surface the road as CONTEXT ONLY, never as an address. Keyed to
            # nothing: it is written onto the very Listing whose own point
            # matched this parcel, so no cross-lead fan-out is possible, and the
            # parcel_id it is stamped with is the unique id of that same parcel.
            li.raw[_NC_ROAD_ONLY_KEY] = {
                "road": road,
                "city": cleaned.get("scity") or None,
                "zip": cleaned.get("szip") or None,
                "parcel_id": pid,
                "source": "nc_onemap_point",
                "mailable": False,
                "note": "NC parcel has no assigned house number (vacant/unnumbered lot)",
            }
    return pid


# NC's "no house number assigned" sentinels. 17,788 parcels carry siteadd
# "99999 <ROAD>" and 285,716 carry "0 <ROAD>" — all vacant land / undeveloped
# lots / unnumbered building lots. Passed through, "99999 MEADOW RD" reads as a
# real street address (it starts with digits, so every downstream validator
# accepts it) and would be mailed, geocoded and shown on the board as fact.
_NC_NO_NUMBER_SENTINELS = ("99999", "0")

# Where the bare road goes once the sentinel is stripped. NOT `siteadd`:
# `siteadd` is the field enrichment_situs_address reads to WRITE
# li.street_address (it is in enrichment_arcgis._ADDR_FIELD_CANDIDATES), and a
# numberless road ("MEADOW RD") is not a mailable address — yet it satisfies
# web_artifact._is_valid_street_address via the road-suffix rule, so writing it
# would (a) publish it as the property's address, (b) send it to the geocoder
# and a mail merge, and (c) make scripts/resolve_addresses classify the lead
# "resolved" and checkpoint it as done FOREVER, killing any later chance at the
# real address. The road still locates the parcel roughly and pairs with
# parcel_id + coords, so it is kept here as provenance instead.
_NC_ROAD_ONLY_KEY = "situs_road_only"


def _clean_nc_situs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Sanitize NC OneMap situs fields. Returns a copy; caller's dict untouched.

    A sentinel house number means the parcel has NO assigned address, so the
    address fields are emptied rather than patched: `siteadd` is blanked (an
    empty situs is skipped by every address writer) and the bare road is parked
    under `situs_road_only` with a `situs_no_house_number` flag. Real addresses
    ("801 BILTMORE  AVE") only get their double spaces collapsed.
    """
    out = dict(attrs)
    raw = str(out.get("siteadd") or "").strip()
    if raw:
        head, _, rest = raw.partition(" ")
        road = " ".join(rest.split())
        if head in _NC_NO_NUMBER_SENTINELS:
            # No house number exists for this parcel -> there is no address to
            # write. Keep the road as context under its own key.
            out["siteadd"] = ""
            out["situs_no_house_number"] = True
            if road:
                out[_NC_ROAD_ONLY_KEY] = road
        else:
            out["siteadd"] = " ".join(raw.split())
    num = str(out.get("saddno") or "").strip()
    if num in _NC_NO_NUMBER_SENTINELS:
        out["saddno"] = ""
        out["situs_no_house_number"] = True
    for f in ("saddstname", "scity"):
        if out.get(f):
            out[f] = " ".join(str(out[f]).split())
    return out


def _withdrawn(li: Listing) -> bool:
    """True when repair_parcel_from_address withdrew this lead's neighbour-derived parcel (coordinates had
    attached a parcel next door). Re-attaching it here would let the next join refill the neighbour's values."""
    pfa = li.raw.get("parcel_from_address") if isinstance(li.raw, dict) else None
    return isinstance(pfa, dict) and bool(pfa.get("withdrawn_parcel"))


async def _resolve_one(c, li: Listing, counts: dict) -> None:
    if li.parcel_id:
        return
    if _withdrawn(li):
        return
    if not (li.state and li.county and _in_box(li)):
        return
    counts["queried"] += 1
    # Normalize raw BEFORE the lookup — _parcel_from_point_nc stashes the
    # matched attribute bag into it, and would silently skip that on a lead
    # whose raw isn't a dict yet.
    if not isinstance(li.raw, dict):
        li.raw = {}
    if li.state == "SC":
        pid, source = await _parcel_from_point_sc(c, li)
    elif li.state == "NC":
        pid = await _parcel_from_point_nc(c, li)
        source = "nc_onemap_point"
    else:
        return
    if not pid:
        return
    li.parcel_id = pid
    li.raw["parcel_from_geo"] = {
        "source": source,
        "lat": li.latitude,
        "lng": li.longitude,
    }
    counts["resolved"] += 1


# FALLBACK POINTS (2026-10-06). The geocoder places a lead with no usable address on its city
# centre (Tier 3) or county seat (Tier 4, enrichment_geocode.COUNTY_SEAT_CENTROIDS), and a
# point-in-polygon query there returns whatever parcel lies under that point. On the 10/5
# checkpoint Rutherford parcel 1654116 (a church in Rutherfordton, at the county-seat point) was
# attached to 619 rows of 10 sources, New Hanover 3115-88-8610.000 to 121, Rutherford 1652469 to
# 50; on the published board Lincoln 3633940779 sits on 1,618 rows and Anderson 1233003020 on 817.
# The resolver stashed that parcel's attributes on every one of them (1654116: owner a church,
# situs 252 N WASHINGTON ST), the situs writers copied the situs onto the address-less ones, and
# dedupe() merged them (see dedupe.py's 'shared parcels' block). A fallback point is not the
# property's location, so no parcel is resolved from it: a point flagged imprecise
# (enrichment_geocode.imprecise_point_flag), a county-seat centroid, or a point shared by
# _CENTROID_MIN_COLLISIONS or more of the listings passed in (enrichment_board_quality's own test
# for a geocoder fallback, which flags the same rows centroid_snap later in the run).

def _shared_points(listings: list[Listing]) -> set:
    from collections import Counter
    from .enrichment_board_quality import _CENTROID_MIN_COLLISIONS
    n = Counter(
        (round(li.latitude, 5), round(li.longitude, 5))
        for li in listings
        if li.latitude is not None and li.longitude is not None
    )
    return {p for p, c in n.items() if c >= _CENTROID_MIN_COLLISIONS}


def _fallback_point(li: Listing, shared: set) -> bool:
    from .enrichment_geocode import imprecise_point_flag, is_county_seat_point
    if imprecise_point_flag(li.raw) or is_county_seat_point(li.latitude, li.longitude):
        return True
    return (round(li.latitude, 5), round(li.longitude, 5)) in shared


async def enrich_parcel_from_geo(listings: list[Listing], concurrency: int = 8) -> dict:
    """Point-in-polygon resolve a parcel_id for every geo-bearing lead that has
    none. SC -> SCDOT SC_Parcels; NC -> NC OneMap NC1Map_Parcels. Writes only
    ``li.parcel_id`` (+ provenance). Idempotent: leads that already carry a
    parcel_id are skipped, so re-runs are no-ops on resolved leads. A lead whose
    point is a geocoder fallback (see FALLBACK POINTS above) is skipped too.
    """
    candidates = [
        li
        for li in listings
        if not li.parcel_id and li.state in ("SC", "NC") and li.county and _in_box(li) and not _withdrawn(li)
    ]
    shared = _shared_points(listings) if candidates else set()
    targets = [li for li in candidates if not _fallback_point(li, shared)]
    skipped = len(candidates) - len(targets)
    if skipped:
        log.info("parcel_from_geo.skipped_fallback_points", leads=skipped, shared_points=len(shared))
    if not targets:
        log.info("parcel_from_geo.no_targets")
        return {"queried": 0, "resolved": 0, "skipped_fallback_point": skipped}

    log.info("parcel_from_geo.start", target_count=len(targets))
    counts = {"queried": 0, "resolved": 0, "skipped_fallback_point": skipped}
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(c, li: Listing) -> None:
        async with sem:
            await _resolve_one(c, li, counts)

    async with client(timeout=25.0, headers=_UA) as c:
        await asyncio.gather(*(_bounded(c, li) for li in targets))

    log.info("parcel_from_geo.done", **counts)
    return counts
