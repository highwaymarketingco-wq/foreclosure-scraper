"""Standalone, resumable address-resolution engine.

12,412 of the 30,003 board leads (41%) carry NO street_address. The repo already
has ~17 working resolver modules, but they only ever run inside the 14h full
pipeline — which keeps getting killed before the address chain finishes, so the
gap never closes. This script runs those SAME resolvers as a small, bounded,
repeatable batch job that checkpoints every lead it touches, so ten 30-minute
runs make the same progress one uninterrupted 5-hour run would.

Nothing here re-implements resolution logic. It is a router + budget + memory
around the existing enrichers:

    parcel lane   parcel_id present    -> enrich_with_parcel_lookup
                                       -> enrich_situs_address
    geo lane      lat/lng, no parcel   -> enrich_parcel_from_geo
                                       -> enrich_situs_address
                                       -> enrich_parcel_reverse_geo (optional)
    owner lane    defendant/owner+cty  -> enrich_addresses_from_owner_v2
                                       -> enrich_addresses_from_owner

Checkpoint (.cache/address_resolution.json) maps a stable lead key to the
outcome + timestamp. On restart, already-resolved leads are skipped forever and
recently-failed leads are skipped until their retry window expires — that is
what makes repeated runs cheap and additive instead of re-grinding lead #1.

Env controls
    ADDR_MAX=300              leads attempted this run (split across lanes)
    ADDR_BUDGET_S=1800        hard wall-clock budget; always exits + saves
    ADDR_ONLY_PATH=parcel     run a single lane (parcel|geo|owner)
    ADDR_WRITE=1              write resolved addresses back to the board
                              (DEFAULT IS DRY-RUN — nothing is persisted)
    ADDR_CONCURRENCY=6        per-lane bounded concurrency (county-GIS polite)
    ADDR_RETRY_AFTER_DAYS=14  re-attempt a failed lead after this many days
    ADDR_REVERSE_GEO=0        enable the 1-req/sec Nominatim reverse-geo tail
    ADDR_CACHE=<path>         override the checkpoint file location

Usage
    ADDR_MAX=25 ADDR_BUDGET_S=180 uv run python scripts/resolve_addresses.py
    ADDR_MAX=400 ADDR_WRITE=1     uv run python scripts/resolve_addresses.py

Board-writer when ADDR_WRITE=1 — run alone (no weekly/merge pass active).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import structlog

from foreclosure_scraper.models import Listing
from foreclosure_scraper.web_artifact import (
    _is_valid_street_address,
    load_board,
    write_artifact,
)

log = structlog.get_logger()

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
DEFAULT_CACHE = REPO / ".cache" / "address_resolution.json"

LANES = ("parcel", "geo", "owner")
CHECKPOINT_VERSION = 1

# Leads whose coordinates are a party's MAILING address rather than the subject
# property must never be point-snapped to a parcel — that writes a confidently
# wrong situs. Same exclusion list resolve_geo_only.py uses, inverted: these are
# the only sources whose lat/lng IS the property, everything else geo-resolves
# only through its own parcel_id.
PROPERTY_GPS_SOURCES = {
    "counties_nc.asheville_helene",
    "national.hud_reac_inspection",
    "national.distressed",
    "national.foreclosure_dot_com",
    "national.crexi_multifamily",
}


# ---------------------------------------------------------------------------
# Pure helpers (no network, no disk) — unit-tested in
# tests/test_address_resolution_checkpoint.py
# ---------------------------------------------------------------------------

def lead_key(li: Listing) -> str:
    """Stable cross-run identity for a lead.

    NOT source_url alone. Bulk sources publish one document for thousands of
    leads — 2,227 McDowell tax leads share a single PDF URL, 1,855 Henderson
    leads share `https://bcpwa.ncptscloud.com/`. Keying on the URL would collapse
    12,412 address-less leads into 5,930 keys, so checkpointing ONE McDowell
    lead would mark the other 2,226 as done and they would never be attempted
    again. The key is therefore the composite of every identifying field.

    Deliberately includes parcel_id and county, which the resolvers CAN fill in.
    Within a run that is a non-issue (keys are snapshotted before any lane
    runs). Across runs, a lead that gained a parcel_id re-keys and so becomes
    eligible again ahead of its retry window — which is what we want, since it
    now has a far better handle to resolve on.
    """
    parts = [
        li.source or "",
        (li.source_url or "").strip(),
        (li.parcel_id or "").strip().lower(),
        (li.county or "").strip().lower(),
        (li.state or "").strip().upper(),
        (li.defendant or li.owner_name or "").strip().lower(),
        (li.description or "")[:120].strip().lower(),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8", "replace")).hexdigest()
    return "k:" + digest[:20]


def route_lane(li: Listing) -> str | None:
    """Best resolver lane for what this lead HAS. None = unreachable.

    Ordered by yield: a parcel_id is a government-unique key (highest hit rate),
    a coordinate is next, an owner name is a fuzzy last resort. A lead with both
    a parcel_id and coords goes to the parcel lane because situs resolves
    parcel-first anyway.
    """
    if (li.street_address or "").strip():
        return None
    if (li.parcel_id or "").strip():
        return "parcel"
    if li.latitude is not None and li.longitude is not None:
        return "geo"
    # DEFENDANT, not "defendant or owner_name". Both owner enrichers select on
    # li.defendant, so an owner_name-only lead is accepted into the lane and then
    # silently skipped by everything in it — burning a batch slot and banking a
    # meaningless "failed". 94 of the 2,117 owner-lane leads are like this, and
    # their owner_name is a PROPERTY name anyway ("Woodridge Apartments",
    # "Grove at Ashton Park"), which a GIS owner-field search cannot match. They
    # are genuinely unreachable with today's resolvers, so they report as such.
    if (li.defendant or "").strip() and (li.county or "").strip():
        return "owner"
    return None


def placeholder_coords(listings: Iterable[Listing], min_shared: int = 3) -> set[tuple[float, float]]:
    """Coordinates shared by >= min_shared leads — county centroids, courthouse
    pins, geocoder fallbacks. A real distinct property never shares an EXACT
    coordinate with two others.

    enrich_situs_address computes this itself, but only over the slice handed to
    it. Because this script hands it a few hundred leads at a time, its internal
    detection would go blind and start point-snapping placeholders. So we compute
    it board-wide and suppress those coords for the duration of the call.
    """
    counts: Counter = Counter()
    for li in listings:
        if li.latitude is None or li.longitude is None:
            continue
        try:
            counts[(round(float(li.latitude), 4), round(float(li.longitude), 4))] += 1
        except (TypeError, ValueError):
            continue
    return {k for k, n in counts.items() if n >= min_shared}


def is_placeholder_point(li: Listing, coords: set[tuple[float, float]]) -> bool:
    if li.latitude is None or li.longitude is None:
        return False
    try:
        return (round(float(li.latitude), 4), round(float(li.longitude), 4)) in coords
    except (TypeError, ValueError):
        return False


def load_checkpoint(path: Path) -> dict:
    """Read the checkpoint, or return an empty one. Never raises — a corrupt or
    truncated cache costs re-work, it must not abort the run."""
    try:
        data = json.loads(Path(path).read_text())
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {"version": CHECKPOINT_VERSION, "updated": None, "entries": {}}


def save_checkpoint(path: Path, cp: dict) -> None:
    """Atomic write (temp + replace) so a kill mid-save can't truncate the
    checkpoint into unreadability."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cp["version"] = CHECKPOINT_VERSION
    cp["updated"] = datetime.now(timezone.utc).isoformat()
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cp, ensure_ascii=False, default=str))
    os.replace(tmp, p)


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def should_bank(status: str, write: bool) -> bool:
    """True when this outcome may be written to the checkpoint.

    A 'resolved' entry means "done, skip forever" (see should_skip). In a DRY-RUN
    the address was found in memory but never persisted to the board, so banking
    it would STRAND the lead: skipped on every future run yet still address-less
    on the board. So 'resolved' is only bankable once it is actually written.

    Failures/junk are bankable either way — they were genuinely attempted and
    nothing was discarded, and should_skip re-tries them after retry_after_days.
    """
    return status != "resolved" or write


def should_skip(entry: dict | None, now: datetime, retry_after_days: float) -> bool:
    """True when a checkpointed lead should NOT be attempted again this run.

    resolved -> skip forever (the address is already on the board).
    failed   -> skip until retry_after_days has elapsed; county GIS coverage
                does change, so a permanent blacklist would be wrong.
    Unparseable/missing timestamp -> retry (fail open toward doing work).
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("status") == "resolved":
        return True
    if entry.get("status") != "failed":
        return False
    ts = _parse_ts(entry.get("ts"))
    if ts is None:
        return False
    return (now - ts) < timedelta(days=retry_after_days)


def bucket_targets(
    listings: Iterable[Listing],
    cp: dict,
    now: datetime,
    only_path: str | None = None,
    retry_after_days: float = 14.0,
    property_gps_sources: set[str] | None = None,
    ph_coords: set[tuple[float, float]] | None = None,
) -> dict[str, list[Listing]]:
    """Every address-less lead still WORTH attempting, bucketed by lane.

    Drops anything the checkpoint marks resolved, anything that failed inside
    the retry window, and any geo-lane lead whose coordinate can't be trusted.
    Pure function: no network, no disk.
    """
    gps_sources = PROPERTY_GPS_SOURCES if property_gps_sources is None else property_gps_sources
    coords = ph_coords or set()
    entries = cp.get("entries", {}) if isinstance(cp, dict) else {}

    buckets: dict[str, list[Listing]] = {lane: [] for lane in LANES}
    for li in listings:
        lane = route_lane(li)
        if lane is None:
            continue
        if only_path and lane != only_path:
            continue
        # The geo lane point-snaps a coordinate to a parcel. Only do that when
        # the coordinate is known to BE the property (a geocoded court filing
        # can be a party's mailing address) and isn't a shared placeholder —
        # otherwise we'd write one confidently wrong situs onto many leads.
        if lane == "geo":
            if li.source not in gps_sources:
                continue
            if is_placeholder_point(li, coords):
                continue
        if should_skip(entries.get(lead_key(li)), now, retry_after_days):
            continue
        buckets[lane].append(li)
    return {lane: stripe_by_county(pool) for lane, pool in buckets.items()}


def stripe_by_county(pool: list[Listing]) -> list[Listing]:
    """Reorder a lane's pool so consecutive leads come from different counties.

    The parcel pool is 79% three counties (McDowell 2,247 / Lincoln 1,397 /
    Hyde 1,390). Taken in board order, every batch for weeks would hit the same
    county — so one county whose GIS has no situs field would silently consume
    the entire budget and the other 15 counties would never be tried. Striping
    makes each batch a broad sample: real throughput stays the same, but a dead
    county costs 1/N of a batch instead of all of it. Deterministic (no RNG), so
    a re-run with the same checkpoint picks the same order.
    """
    groups: dict[str, list[Listing]] = defaultdict(list)
    for li in pool:
        groups[f"{(li.county or '?').strip().lower()}|{li.state or '?'}"].append(li)
    queues = [groups[k] for k in sorted(groups)]
    out: list[Listing] = []
    i = 0
    while queues:
        q = queues[i % len(queues)]
        out.append(q.pop(0))
        if not q:
            queues.remove(q)
            i = 0
        else:
            i += 1
    return out


def allocate(buckets: dict[str, list[Listing]], limit: int) -> dict[str, list[Listing]]:
    """Split this run's lead budget ROUND-ROBIN across the non-empty lanes.

    First-come allocation would spend every small batch on the 6,374 parcel
    leads and never touch geo/owner, so a lane going dead would stay invisible
    for weeks. Round-robin keeps every lane observable on every run.
    """
    out: dict[str, list[Listing]] = {lane: [] for lane in LANES}
    active = [lane for lane in LANES if buckets.get(lane)]
    if not active or limit <= 0:
        return out
    cursor = {lane: 0 for lane in LANES}
    taken = 0
    idx = 0
    while taken < limit and active:
        lane = active[idx % len(active)]
        pool = buckets[lane]
        if cursor[lane] < len(pool):
            out[lane].append(pool[cursor[lane]])
            cursor[lane] += 1
            taken += 1
            idx += 1
        else:
            active.remove(lane)
            idx = 0
    return out


def _snapshot(li: Listing) -> dict:
    return {
        "street_address": (li.street_address or "").strip(),
        "city": (li.city or "").strip(),
        "zip_code": (li.zip_code or "").strip(),
        "parcel_id": (li.parcel_id or "").strip(),
        "owner_name": (li.owner_name or "").strip(),
    }


def lane_degraded(lane_stats: dict | None) -> bool:
    """True when a lane did not actually get to try every lead it was given —
    a step hit the wall-clock budget, raised, or was skipped for lack of budget.

    Cancelling an asyncio.gather gives no per-lead accounting, so we cannot tell
    which of the lane's leads were reached. This matters a lot: without it,
    `ADDR_BUDGET_S=15` over 300 leads banks 300 `failed` entries for leads that
    were never contacted, and the retry window then hides all 300 for two weeks
    — a short run would poison the board. Resolved leads are still recorded (a
    resolution is proof of work); everything else is left unwritten so the next
    run picks it straight back up.
    """
    st = lane_stats or {}
    if st.get("skipped_no_budget"):
        return True
    return any(
        isinstance(v, str) and (v == "BUDGET_TIMEOUT" or v.startswith("ERROR:"))
        for v in st.values()
    )


def _provenance(li: Listing, lane: str) -> str:
    """Which resolver actually produced the address — the enrichers each stamp
    their own marker into raw, so read those before falling back to the lane."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    src = raw.get("situs_address_source")
    if isinstance(src, str) and src:
        return src
    if "addr_owner_v2" in raw:
        return "addr_owner_v2"
    if isinstance(raw.get("gis"), dict) and raw["gis"].get("owner_match_strategy"):
        return str(raw["gis"]["owner_match_strategy"])
    return f"{lane}_lane"


def classify_outcome(before: dict, li: Listing) -> tuple[str, list[str], str | None]:
    """(status, gained_fields, address) for one attempted lead.

    An enricher may synthesize a non-address ("Lot 12, Tract B") when the GIS
    misses. Those are counted as FAILED and reverted — a junk string in
    street_address is worse than a null, because it hides the lead from every
    later resolver and from the photo/vision pass this whole exercise exists to
    unlock.
    """
    after = _snapshot(li)
    gained = [k for k, v in after.items() if v and not before.get(k)]
    addr = after["street_address"]
    if addr and not before["street_address"]:
        # County GIS situs fields carry padded runs of spaces ("104   WHITLEY RD",
        # "801 BILTMORE  AVE"). Collapse them on the way in — the raw form breaks
        # exact-match dedupe against other sources and reads as sloppy in a
        # mail-merge. Only ever touches an address this run just wrote.
        squashed = " ".join(addr.split())
        if squashed != addr:
            li.street_address = addr = squashed
        if _is_valid_street_address(addr):
            return "resolved", gained, addr
        li.street_address = None
        gained = [g for g in gained if g != "street_address"]
        return "junk", gained, addr
    return "failed", gained, None


# ---------------------------------------------------------------------------
# Lane runners — thin async wrappers around the existing enrichers
# ---------------------------------------------------------------------------

class _Budget:
    """Wall-clock budget shared by every lane. `remaining()` drives asyncio
    timeouts so the process ALWAYS returns and saves, never hangs."""

    def __init__(self, seconds: float) -> None:
        self.deadline = time.monotonic() + seconds
        self.total = seconds

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def spent(self) -> float:
        return self.total - self.remaining()


async def _step(name: str, coro, budget: _Budget, stats: dict, min_s: float = 5.0) -> None:
    """Run one enricher under the remaining budget. Per-step try/except so a
    single dead county endpoint can't abort the whole run, and a timeout is a
    normal, expected outcome (work already applied to the Listing objects
    survives cancellation)."""
    left = budget.remaining()
    if left <= min_s:
        stats.setdefault("skipped_no_budget", []).append(name)
        coro.close()
        return
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(coro, timeout=left)
        stats[name] = result if isinstance(result, dict) else "ok"
    except (asyncio.TimeoutError, TimeoutError):
        stats[name] = "BUDGET_TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        stats[name] = f"ERROR: {type(exc).__name__}: {exc}"
        log.warning("resolve_addresses.step_failed", step=name, error=str(exc))
    finally:
        stats[f"{name}_secs"] = round(time.monotonic() - t0, 1)


class _suppress_coords:
    """Temporarily blank lat/lng on placeholder-coordinate leads.

    enrich_situs_address falls back to point-in-polygon when a parcel query
    misses. Handed a small slice it cannot detect board-wide placeholders, so
    without this it would happily snap 300 leads sharing a courthouse pin to
    whatever parcel sits under that pin. Restored in __exit__ (also on
    exception) so nothing leaks into the board write.
    """

    def __init__(self, leads: list[Listing], coords: set[tuple[float, float]]) -> None:
        self.hits = [li for li in leads if is_placeholder_point(li, coords)]
        self.saved: list[tuple[Listing, float | None, float | None]] = []

    def __enter__(self) -> "_suppress_coords":
        for li in self.hits:
            self.saved.append((li, li.latitude, li.longitude))
            li.latitude = None
            li.longitude = None
        return self

    def __exit__(self, *exc) -> None:
        for li, lat, lng in self.saved:
            li.latitude = lat
            li.longitude = lng


async def run_parcel_lane(leads: list[Listing], budget: _Budget, conc: int,
                          coords: set) -> dict:
    """SITUS FIRST, then parcel_lookup on the leftovers.

    Order matters and the obvious order is wrong. enrich_with_parcel_lookup
    falls back to SYNTHESIZING a pseudo-address from the description ("Lot 12,
    Tract B") when the GIS misses. Every downstream resolver — including
    enrich_situs_address — selects on `not street_address`, so that synthesized
    string makes the lead invisible to the enricher that would have found the
    REAL situs. Running parcel_lookup first measurably starved situs (9 targets
    down to 5 on a 9-lead batch). Situs goes first; parcel_lookup only sees what
    situs could not resolve.
    """
    from foreclosure_scraper.enrichment_parcel_lookup import enrich_with_parcel_lookup
    from foreclosure_scraper.enrichment_situs_address import enrich_situs_address

    stats: dict = {"targets": len(leads)}
    if not leads:
        return stats
    with _suppress_coords(leads, coords):
        await _step("situs", enrich_situs_address(leads, concurrency=conc), budget, stats)
        left = [li for li in leads if not (li.street_address or "").strip()]
        stats["parcel_lookup_targets"] = len(left)
        if left:
            await _step("parcel_lookup", enrich_with_parcel_lookup(left), budget, stats)
    return stats


async def run_geo_lane(leads: list[Listing], budget: _Budget, conc: int,
                       coords: set, reverse_geo: bool) -> dict:
    from foreclosure_scraper.enrichment_parcel_from_geo import enrich_parcel_from_geo
    from foreclosure_scraper.enrichment_situs_address import enrich_situs_address

    stats: dict = {"targets": len(leads)}
    if not leads:
        return stats
    await _step("parcel_from_geo", enrich_parcel_from_geo(leads, concurrency=conc), budget, stats)
    await _step("situs", enrich_situs_address(leads, concurrency=conc), budget, stats)
    if reverse_geo:
        # Nominatim is serial at ~1 req/sec by TOS, so this tail is the single
        # most likely thing to eat a run. Cap its query budget to what actually
        # fits in the time left. The module reads its cap at import time, so the
        # env var is set before the (deferred) import.
        cap = max(0, int(min(len(leads), budget.remaining() / 1.3)))
        if cap:
            os.environ["FORECLOSURE_REVERSE_GEO_MAX"] = str(cap)
            import importlib

            import foreclosure_scraper.enrichment_parcel_reverse_geo as rg
            importlib.reload(rg)
            await _step("reverse_geo", rg.enrich_parcel_reverse_geo(leads), budget, stats)
        else:
            stats["reverse_geo"] = "skipped_no_budget"
    return stats


async def run_owner_lane(leads: list[Listing], budget: _Budget, conc: int) -> dict:
    from foreclosure_scraper.enrichment_address_backfill import enrich_addresses_from_owner
    from foreclosure_scraper.enrichment_address_owner_v2 import enrich_addresses_from_owner_v2

    stats: dict = {"targets": len(leads)}
    if not leads:
        return stats
    await _step("owner_v2", enrich_addresses_from_owner_v2(leads, concurrency=conc), budget, stats)
    # v1 backfill only sees what v2 left address-less; it uses a different
    # owner-field detector and catches counties v2's stricter matcher rejects.
    left = [li for li in leads if not (li.street_address or "").strip()]
    stats["owner_v1_targets"] = len(left)
    if left:
        await _step("owner_v1", enrich_addresses_from_owner(left, concurrency=conc), budget, stats)
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def main() -> int:
    max_leads = _env_int("ADDR_MAX", 300)
    budget_s = _env_float("ADDR_BUDGET_S", 1800.0)
    only_path = (os.environ.get("ADDR_ONLY_PATH") or "").strip().lower() or None
    write = os.environ.get("ADDR_WRITE") == "1"
    conc = _env_int("ADDR_CONCURRENCY", 6)
    retry_days = _env_float("ADDR_RETRY_AFTER_DAYS", 14.0)
    reverse_geo = os.environ.get("ADDR_REVERSE_GEO") == "1"
    cache_path = Path(os.environ.get("ADDR_CACHE") or DEFAULT_CACHE)

    if only_path and only_path not in LANES:
        print(f"ADDR_ONLY_PATH must be one of {LANES}, got {only_path!r}")
        return 2

    t0 = time.monotonic()
    listings = load_board(DOCS)  # merges the lazy-detail sidecar so it round-trips
    cp = load_checkpoint(cache_path)
    now = datetime.now(timezone.utc)

    addr_before = sum(1 for li in listings if (li.street_address or "").strip())
    missing = [li for li in listings if not (li.street_address or "").strip()]
    coords = placeholder_coords(listings)

    lane_pool: Counter = Counter()
    for li in missing:
        lane = route_lane(li)
        if lane:
            lane_pool[lane] += 1

    buckets = bucket_targets(
        listings, cp, now,
        only_path=only_path, retry_after_days=retry_days, ph_coords=coords,
    )

    print(
        f"board={len(listings)} addr_present={addr_before} addr_missing={len(missing)}\n"
        f"routable:  " + "  ".join(f"{k}={lane_pool.get(k, 0)}" for k in LANES)
        + f"  unreachable={len(missing) - sum(lane_pool.values())}\n"
        f"eligible:  " + "  ".join(f"{k}={len(buckets[k])}" for k in LANES)
        + "   (routable minus checkpointed + untrusted geo points)\n"
        f"checkpoint={cache_path} entries={len(cp.get('entries', {}))} "
        f"placeholder_coords={len(coords)}\n"
        f"mode={'WRITE' if write else 'DRY-RUN'} max={max_leads} budget={budget_s:.0f}s "
        f"conc={conc} only={only_path or 'all'} reverse_geo={reverse_geo}",
        flush=True,
    )

    targets = allocate(buckets, max_leads)
    attempted = [li for lane in LANES for li in targets[lane]]
    print("selected:  " + "  ".join(f"{k}={len(targets[k])}" for k in LANES)
          + f"  total={len(attempted)}", flush=True)
    if not attempted:
        print("nothing to do (all routable leads resolved or inside the retry window)")
        save_checkpoint(cache_path, cp)
        return 0

    # Snapshot BOTH the key and the field state before any lane runs. The key
    # includes parcel_id/county, which a lane can fill in — recomputing it after
    # the fact would file the result under an identity the next run won't match.
    keys = {id(li): lead_key(li) for li in attempted}
    before = {id(li): _snapshot(li) for li in attempted}
    budget = _Budget(budget_s)
    lane_stats: dict[str, dict] = {}

    async def go() -> None:
        if targets["parcel"]:
            lane_stats["parcel"] = await run_parcel_lane(targets["parcel"], budget, conc, coords)
        if targets["geo"]:
            lane_stats["geo"] = await run_geo_lane(targets["geo"], budget, conc, coords, reverse_geo)
        if targets["owner"]:
            lane_stats["owner"] = await run_owner_lane(targets["owner"], budget, conc)

    try:
        asyncio.run(go())
    except KeyboardInterrupt:
        print("interrupted — saving checkpoint for work completed so far", flush=True)
    except Exception as exc:  # noqa: BLE001
        log.error("resolve_addresses.run_failed", error=str(exc))
        print(f"run error ({type(exc).__name__}: {exc}) — saving checkpoint anyway", flush=True)

    # ---- score + checkpoint (always runs, even after a timeout/interrupt) ----
    entries = cp.setdefault("entries", {})
    by_lane: dict[str, Counter] = defaultdict(Counter)
    by_county: dict[str, Counter] = defaultdict(Counter)
    samples: list[str] = []
    gained_fields: Counter = Counter()

    for lane in LANES:
        degraded = lane_degraded(lane_stats.get(lane))
        if degraded and targets[lane]:
            print(f"note: {lane} lane degraded (budget/error) — only resolved leads "
                  f"will be checkpointed; the rest stay eligible for the next run",
                  flush=True)
        for li in targets[lane]:
            try:
                status, gained, addr = classify_outcome(before[id(li)], li)
            except Exception as exc:  # noqa: BLE001
                log.warning("resolve_addresses.classify_failed", error=str(exc))
                continue
            by_lane[lane][status] += 1
            by_county[f"{li.county or '?'}-{li.state or '?'}"][status] += 1
            for g in gained:
                gained_fields[g] += 1
            if degraded and status != "resolved":
                continue  # never attempted (or unknowable) — do not bank a failure
            key = keys[id(li)]
            entry = {
                "status": "resolved" if status == "resolved" else "failed",
                "lane": lane,
                "county": li.county,
                "source": li.source,
                "ts": now.isoformat(),
                "attempts": int((entries.get(key) or {}).get("attempts") or 0) + 1,
            }
            if status == "resolved":
                entry["address"] = addr
                entry["city"] = (li.city or "").strip() or None
                entry["zip"] = (li.zip_code or "").strip() or None
                entry["provenance"] = _provenance(li, lane)
                if len(samples) < 15:
                    samples.append(
                        f"  [{lane}] {addr}"
                        + (f", {li.city}" if li.city else "")
                        + (f" {li.zip_code}" if li.zip_code else "")
                        + f"   ({li.county or '?'} {li.state or '?'} | {li.source})"
                    )
            else:
                if status == "junk":
                    entry["reason"] = "synthesized_non_address_reverted"
                if gained:
                    entry["gained"] = gained
            if should_bank(status, write):
                entries[key] = entry

    save_checkpoint(cache_path, cp)

    # ---- report ------------------------------------------------------------
    total_resolved = sum(c["resolved"] for c in by_lane.values())
    total_junk = sum(c["junk"] for c in by_lane.values())
    total_failed = sum(c["failed"] for c in by_lane.values())

    print("\n=== lane detail ===")
    for lane in LANES:
        if lane not in lane_stats:
            continue
        print(f"{lane}: {json.dumps(lane_stats[lane], default=str)}")

    print("\n=== summary ===")
    print(f"attempted={len(attempted)}  resolved={total_resolved}  "
          f"failed={total_failed}  junk_reverted={total_junk}")
    for lane in LANES:
        c = by_lane.get(lane)
        if c:
            print(f"  {lane:<7} attempted={sum(c.values()):<5} resolved={c['resolved']:<5} "
                  f"failed={c['failed']:<5} junk={c['junk']}")
    if gained_fields:
        print("  side-gains: " + "  ".join(f"{k}+{v}" for k, v in gained_fields.most_common()))
    if by_county:
        print("  by county (resolved/attempted): " + "  ".join(
            f"{c}={by_county[c]['resolved']}/{sum(by_county[c].values())}"
            for c in sorted(by_county)))
    print(f"budget: {budget.spent():.0f}s of {budget_s:.0f}s   "
          f"elapsed: {time.monotonic() - t0:.0f}s")
    print(f"checkpoint: {len(entries)} entries -> {cache_path}")

    if samples:
        print("\n=== sample resolved addresses ===")
        for s in samples:
            print(s)

    if write:
        addr_after = sum(1 for li in listings if (li.street_address or "").strip())
        write_artifact(
            listings,
            {"notes": f"standalone address resolution: +{addr_after - addr_before} addresses"},
            docs_dir=DOCS,
        )
        print(f"\nWROTE BOARD: addresses {addr_before} -> {addr_after} "
              f"(+{addr_after - addr_before})")
    else:
        print("\nDRY-RUN: board NOT written. Re-run with ADDR_WRITE=1 to persist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
