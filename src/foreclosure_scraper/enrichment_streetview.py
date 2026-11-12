"""Google Street View Static photos — a real street-level shot of the ACTUAL house.

This is the image the Vision condition-grader actually wants: facade, roof line,
boarded windows, overgrowth, tarps, junk cars. Esri aerial shows a roof polygon;
Mapillary is volunteer-contributed and thin outside metro corridors. Street View
covers essentially every drivable US road, so any lead with a real street address
can get a gradeable photo.

PAID API — OFF BY DEFAULT. Google Maps Platform replaced the old pooled
$200/month credit on 2025-03-01 with a PER-SKU free monthly cap. Verified against
Google's official pricing on 2026-07-27:

  * "Static Street View" (the image call)  — Essentials tier,
    10,000 free events/month, then $7.00 per 1,000 (10,001-100,000 band).
  * "Street View Metadata" (the /metadata call) — Essentials tier, NO CHARGE and
    NO quota consumed ("Street View Static API metadata requests are available
    at no charge. No quota is consumed when you request metadata.").
  * Billing MUST be enabled on the Cloud project even to use the free tier.

Because a mistake here costs real money, spending is fenced structurally, not by
convention:

  1. Gate      — FORECLOSURE_STREETVIEW=1 required. Default OFF, hard no-op.
  2. Key       — env GOOGLE_MAPS_API_KEY, else .secrets/google_maps_api_key.txt.
                 Absent => clean no-op, zero requests. We never create a key.
  3. Free-first— the FREE /metadata endpoint is ALWAYS called before any billed
                 image call. status != OK (no imagery within radius) => skip, $0.
  4. Disk cache— an already-downloaded photo is reused. A re-run of the same
                 board costs $0.
  5. Run cap   — STREETVIEW_MAX billed image calls per run (default 300).
  6. Month cap — a PERSISTENT counter (<repo>/data/streetview_usage.json,
                 gitignored) caps billed calls per calendar month at
                 STREETVIEW_MONTHLY_MAX (default 2,000). The cap is itself
                 clamped to 9,000 — under the 10,000 free tier — unless
                 STREETVIEW_ALLOW_PAID=1 is set explicitly. So repeated runs
                 cannot silently walk into billing. The counter path is ABSOLUTE
                 (repo-anchored): a run started from another working directory
                 must not get a fresh, empty counter.
  7. Charge-on-attempt — the counter is incremented and FLUSHED TO DISK *before*
                 the image request goes out, never after. A crash mid-call can
                 over-count (costs coverage) but never under-count (costs money).
                 If the counter cannot be persisted, the enricher refuses to
                 spend at all.
  8. Cross-process lock — the read-modify-write of the counter is serialized
                 across PROCESSES with an flock'd sidecar lockfile, and the
                 on-disk month total is re-read inside that lock before every
                 reservation. Two overlapping runs (run_local.sh plus a manual
                 run) therefore share one month budget instead of each spending
                 a full one. If file locking is unavailable or the lock cannot be
                 taken, the enricher REFUSES to spend rather than risk
                 double-spending.
  9. Wall clock— STREETVIEW_BUDGET_S (default 1200s) bail, like the other
                 enrichers, so a slow API can't wedge the run.
 10. STREETVIEW_DRY_RUN=1 — metadata-only coverage probe. Zero billed calls.

Metadata calls are FREE and consume no Google quota, so they are fenced only for
politeness: STREETVIEW_METADATA_MAX bounds them PER RUN (default 4x
STREETVIEW_MAX, so STREETVIEW_MAX=0 means zero of everything). The month-to-date
metadata total is recorded in the counter file for observability and is enforced
only when STREETVIEW_METADATA_MONTHLY_MAX is set above 0. Nothing here pretends
to enforce a monthly metadata cap that isn't configured.

KEY-LEAK SAFETY: the signed image URL contains the API key, and docs/listings.json
is published to a PUBLIC GitHub Pages site. Publishing that URL would hand the
operator's billable key to anyone who views the dashboard. So we download the
JPEG server-side once and host it under docs/parcel_photos/streetview/, exactly
like enrichment_lrcpwa_photo does with the assessor photos, and store only the
relative path. The key never leaves this process.

Writes (all inside raw['images'], which web_artifact keeps wholesale):
    raw.images.street        — "parcel_photos/streetview/<file>.jpg"
    raw.images.street_source — "google_streetview"
    raw.images.streetview    — provenance {provider, pano_id, capture_date,
                               pano_location, attribution, fetched_at, query}
    raw.images.primary       — re-picked per the existing priority
                               real > street > aerial > map
    raw.zillow.photo         — alias kept in sync (dashboard card image)
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

try:  # POSIX only; absence is handled as "cannot lock" => refuse to spend.
    import fcntl
except Exception:  # noqa: BLE001  # pragma: no cover - non-POSIX only
    fcntl = None  # type: ignore[assignment]

from .http_client import client
from .models import Listing
from .web_artifact import _is_valid_street_address, is_pinpointable_address

log = structlog.get_logger(__name__)

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
IMAGE_URL = "https://maps.googleapis.com/maps/api/streetview"

# Verified from Google's official pricing pages on 2026-07-27. Used only to keep
# the guard honest + to print a $ estimate in the logs — never to authorize spend.
FREE_TIER_MONTHLY = 10_000        # Static Street View, Essentials tier
PAID_PER_1000_USD = 7.00          # 10,001-100,000 band
# Hard ceiling on the monthly cap unless the operator explicitly opts into paid
# usage. 1,000 events of headroom under the free tier absorbs any month-boundary
# skew between our UTC clock and Google's billing month.
FREE_TIER_GUARD = 9_000

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_PHOTO_DIR = _REPO_ROOT / "docs" / "parcel_photos" / "streetview"
# ABSOLUTE, repo-anchored — a relative default would silently start a FRESH
# monthly counter whenever the process is launched from another cwd (cron vs
# run_local.sh vs a manual shell), which would quietly reset the spend fence.
_DEFAULT_COUNTER = str(_REPO_ROOT / "data" / "streetview_usage.json")
_DEFAULT_KEY_FILE = str(_REPO_ROOT / ".secrets" / "google_maps_api_key.txt")


# --------------------------------------------------------------------------- #
# config (read fresh per call — never baked in at import, so env caps always
# apply and tests can drive them)
# --------------------------------------------------------------------------- #
def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, default)).strip())
    except Exception:  # noqa: BLE001
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, default)).strip())
    except Exception:  # noqa: BLE001
        return float(default)


def _abs_path(value: str) -> Path:
    """Absolute path, anchored at the repo root when `value` is relative.

    The monthly spend counter must resolve to the SAME file no matter which
    directory the process was started from.
    """
    p = Path(value).expanduser()
    return p if p.is_absolute() else (_REPO_ROOT / p)


def _as_dict(value: Any) -> dict:
    """Real board data puts strings where nested dicts are expected.

    e.g. raw['grade'] == 'A' instead of {'overall': 'A'}. `(x or {}).get(...)`
    raises AttributeError on those, which has killed whole runs before. Every
    nested read in this module goes through here.
    """
    return value if isinstance(value, dict) else {}


class _Config:
    """Per-call config snapshot. All caps clamped to sane, non-negative values."""

    def __init__(self) -> None:
        self.enabled = os.environ.get("FORECLOSURE_STREETVIEW", "0").strip() == "1"
        self.dry_run = os.environ.get("STREETVIEW_DRY_RUN", "0").strip() == "1"
        self.allow_paid = os.environ.get("STREETVIEW_ALLOW_PAID", "0").strip() == "1"

        self.run_cap = max(0, _env_int("STREETVIEW_MAX", 300))
        month_cap = max(0, _env_int("STREETVIEW_MONTHLY_MAX", 2000))
        self.month_cap_requested = month_cap
        # Structural free-tier fence: without an explicit paid opt-in the monthly
        # cap can never be raised past FREE_TIER_GUARD, no matter what env says.
        self.month_cap = month_cap if self.allow_paid else min(month_cap, FREE_TIER_GUARD)
        # Metadata is free and consumes no Google quota, but bound it anyway so a
        # huge board can't fire an unbounded number of requests at Google if that
        # ever changes. Derived from run_cap WITHOUT a floor, so STREETVIEW_MAX=0
        # means zero of everything (a floor of 1 used to leak 4 probes).
        self.metadata_cap = max(0, _env_int("STREETVIEW_METADATA_MAX", self.run_cap * 4))
        # Month-to-date metadata is always RECORDED; it is only ENFORCED when the
        # operator sets this above 0. 0 == not enforced, and we say so rather
        # than keeping a counter that looks like a cap and isn't.
        self.metadata_month_cap = max(0, _env_int("STREETVIEW_METADATA_MONTHLY_MAX", 0))

        self.budget_s = max(0.0, _env_float("STREETVIEW_BUDGET_S", 1200.0))
        self.concurrency = max(1, _env_int("STREETVIEW_CONCURRENCY", 4))
        self.timeout_s = max(1.0, _env_float("STREETVIEW_TIMEOUT_S", 20.0))
        # How long to wait for another process's ledger lock before giving up.
        # Giving up denies the reservation — it never spends unlocked.
        self.lock_timeout_s = max(0.0, _env_float("STREETVIEW_LOCK_TIMEOUT_S", 15.0))

        self.size = (os.environ.get("STREETVIEW_SIZE", "640x640") or "640x640").strip()
        self.radius_m = max(1, _env_int("STREETVIEW_RADIUS_M", 50))
        self.thumb_px = max(64, _env_int("STREETVIEW_THUMB", 640))
        # An operator-supplied relative path is resolved against the repo root,
        # not the cwd, for the same reason the default is absolute.
        self.counter_path = _abs_path(
            os.environ.get("STREETVIEW_COUNTER_FILE", _DEFAULT_COUNTER).strip()
            or _DEFAULT_COUNTER
        )
        self.key_file = _abs_path(
            os.environ.get("STREETVIEW_KEY_FILE", _DEFAULT_KEY_FILE).strip()
            or _DEFAULT_KEY_FILE
        )


# --------------------------------------------------------------------------- #
# API key — read-only. We never create, prompt for, or write a key.
# --------------------------------------------------------------------------- #
def _load_api_key(cfg: _Config) -> Optional[str]:
    for var in ("GOOGLE_MAPS_API_KEY", "GOOGLE_STREETVIEW_API_KEY"):
        v = (os.environ.get(var) or "").strip()
        if v:
            return v
    try:
        if cfg.key_file.exists():
            v = cfg.key_file.read_text().strip()
            if v:
                return v
    except Exception:  # noqa: BLE001
        return None
    return None


# --------------------------------------------------------------------------- #
# persistent monthly ledger
# --------------------------------------------------------------------------- #
def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


class _Ledger:
    """Persistent, charge-on-attempt counter of BILLED image calls per month.

    Every reservation is written to disk BEFORE the caller is allowed to spend.
    If the file cannot be written the ledger goes read-only and denies every
    further reservation — we would rather lose photo coverage than lose track of
    money already spent.

    Two levels of mutual exclusion guard the read-modify-write:

      * an asyncio.Lock, for the worker coroutines inside THIS process;
      * an flock'd sidecar lockfile (<counter>.lock) plus a re-read of the
        on-disk total inside that lock, for OTHER processes. Without it two
        overlapping runs would each load the same month total, each spend a full
        cap, and last-write-wins would hide half the spend.

    If file locking is unavailable (no fcntl) or the lock cannot be acquired
    within STREETVIEW_LOCK_TIMEOUT_S, reservations are DENIED. Refusing to spend
    is always preferred over spending without a serialized counter.
    """

    def __init__(self, path: Path, month: str, run_cap: int, month_cap: int,
                 metadata_cap: int, metadata_month_cap: int = 0,
                 lock_timeout_s: float = 15.0):
        self.path = path
        self.lock_path = path.parent / (path.name + ".lock")
        self.month = month
        self.run_cap = run_cap
        self.month_cap = month_cap
        self.metadata_cap = metadata_cap
        self.metadata_month_cap = metadata_month_cap
        self.lock_timeout_s = lock_timeout_s
        self.run_billed = 0
        self.run_metadata = 0
        self.month_billed = 0
        self.month_metadata = 0
        self.persist_ok = True
        self._metadata_dirty = False
        self._lock: Optional[asyncio.Lock] = None
        self._load()

    # -- io ---------------------------------------------------------------
    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                if isinstance(data, dict) and data.get("month") == self.month:
                    self.month_billed = int(data.get("billed_image_calls") or 0)
                    self.month_metadata = int(data.get("metadata_calls") or 0)
        except Exception as exc:  # noqa: BLE001
            # Unreadable ledger == unknown spend. Fail CLOSED.
            log.warning("streetview.ledger.unreadable", path=str(self.path), err=str(exc))
            self.persist_ok = False

    # -- cross-process lock ------------------------------------------------
    async def _acquire(self) -> Optional[int]:
        """Take the exclusive inter-process lock. None => caller must not spend."""
        if fcntl is None:  # pragma: no cover - POSIX everywhere we run
            log.error("streetview.ledger.no_file_locking",
                      hint="fcntl unavailable — refusing to spend because the "
                           "monthly counter cannot be serialized across processes")
            self.persist_ok = False
            return None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        except Exception as exc:  # noqa: BLE001
            log.error("streetview.ledger.lock_open_failed",
                      path=str(self.lock_path), err=str(exc))
            self.persist_ok = False
            return None
        deadline = time.monotonic() + self.lock_timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except Exception:  # noqa: BLE001 - held by another process
                if time.monotonic() >= deadline:
                    try:
                        os.close(fd)
                    except Exception:  # noqa: BLE001
                        pass
                    log.error("streetview.ledger.lock_timeout",
                              path=str(self.lock_path),
                              waited_s=self.lock_timeout_s,
                              hint="another streetview run holds the spend "
                                   "counter — refusing to spend unlocked")
                    return None
                await asyncio.sleep(0.05)

    def _release(self, fd: int) -> None:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:  # noqa: BLE001
            pass
        try:
            os.close(fd)
        except Exception:  # noqa: BLE001
            pass

    def _reload_billed_locked(self) -> bool:
        """Re-read the month's billed total. MUST be called holding the flock.

        Only ever raises our view of the total (max), so a stale or truncated
        write by anyone else can't hand us back budget we already spent.
        """
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                if isinstance(data, dict) and data.get("month") == self.month:
                    self.month_billed = max(
                        self.month_billed, int(data.get("billed_image_calls") or 0))
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("streetview.ledger.reload_failed", path=str(self.path),
                      err=str(exc))
            self.persist_ok = False
            return False

    def _flush(self) -> bool:
        payload = {
            "month": self.month,
            "billed_image_calls": self.month_billed,
            "metadata_calls": self.month_metadata,
            "free_tier_monthly": FREE_TIER_MONTHLY,
            "monthly_cap": self.month_cap,
            "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "metadata_monthly_cap": self.metadata_month_cap,
            "note": "billed_image_calls counts Static Street View image requests "
                    "(charge-on-attempt) and is the enforced monthly spend fence. "
                    "metadata_calls is free/no-quota and is recorded for "
                    "observability; it is enforced only when metadata_monthly_cap "
                    "is above 0.",
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # PID-scoped temp name: every _flush already runs under the flock,
            # but a shared "<counter>.tmp" would still race any other writer
            # (os.replace would hit ENOENT after someone else renamed it).
            tmp = self.path.with_suffix(self.path.suffix + f".tmp{os.getpid()}")
            tmp.write_text(json.dumps(payload, indent=2))
            os.replace(tmp, self.path)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("streetview.ledger.write_failed", path=str(self.path), err=str(exc))
            self.persist_ok = False
            return False

    async def preflight(self) -> bool:
        """Prove we can lock AND persist BEFORE the run spends anything.

        Done under the cross-process lock so a concurrent run's spend can't be
        clobbered by our opening write.
        """
        if not self.persist_ok:
            return False
        fd = await self._acquire()
        if fd is None:
            return False
        try:
            if not self._reload_billed_locked():
                return False
            return self._flush()
        finally:
            self._release(fd)

    async def finalize(self) -> bool:
        """Persist the free-metadata tally once, at end of run.

        Billed calls are already on disk (charge-on-attempt); this exists only so
        the observability counter isn't re-serialized on every single probe.
        """
        if not self.persist_ok or not self._metadata_dirty:
            return False
        async with self._get_lock():
            fd = await self._acquire()
            if fd is None:
                return False
            try:
                if not self._reload_billed_locked():
                    return False
                ok = self._flush()
                if ok:
                    self._metadata_dirty = False
                return ok
            finally:
                self._release(fd)

    # -- reservations ------------------------------------------------------
    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def reserve_metadata(self) -> bool:
        """Reserve one FREE metadata probe.

        No disk write: metadata costs nothing, and flushing the whole JSON per
        probe was up to ~12,900 serialize+write+os.replace cycles per run. The
        tally is persisted once by finalize().
        """
        async with self._get_lock():
            if not self.persist_ok:
                return False
            if self.run_metadata >= self.metadata_cap:
                return False
            if self.metadata_month_cap and self.month_metadata >= self.metadata_month_cap:
                return False
            self.run_metadata += 1
            self.month_metadata += 1
            self._metadata_dirty = True
            return True

    async def reserve_image(self) -> tuple[bool, str]:
        """Reserve ONE billed image call. Returns (granted, reason_if_denied).

        The increment is persisted, under the cross-process lock and after
        re-reading the on-disk total, before returning True — so the caller may
        only spend against money we have already written down, and two
        concurrent runs cannot both spend the same remaining budget.
        """
        async with self._get_lock():
            if not self.persist_ok:
                return False, "ledger_unwritable"
            if self.run_billed >= self.run_cap:
                return False, "run_cap"
            fd = await self._acquire()
            if fd is None:
                return False, "ledger_locked"
            try:
                if not self._reload_billed_locked():
                    return False, "ledger_unwritable"
                if self.month_billed >= self.month_cap:
                    return False, "month_cap"
                self.run_billed += 1
                self.month_billed += 1
                if not self._flush():
                    # Could not write the charge down -> roll back, stop spending.
                    self.run_billed -= 1
                    self.month_billed -= 1
                    return False, "ledger_unwritable"
                self._metadata_dirty = False
                return True, ""
            finally:
                self._release(fd)


# --------------------------------------------------------------------------- #
# lead selection
# --------------------------------------------------------------------------- #
def _images(li: Listing) -> dict:
    """The lead's images dict, coerced into existence.

    raw['images'] is occasionally a non-dict on real board data; writing into
    that would raise, so replace it (it is unusable either way).
    """
    if not isinstance(li.raw, dict):
        li.raw = {}
    images = li.raw.get("images")
    if not isinstance(images, dict):
        images = {}
        li.raw["images"] = images
    return images


def _needs_street_photo(li: Listing) -> bool:
    """True when this lead has no ground-level photo yet.

    Skips leads that already carry real listing/assessor photos, and leads that
    already have ANY street-level image (Mapillary, or our own from a prior run)
    so a re-run never re-buys what we already have.

    A non-dict raw['images'] (string, list, None) carries no usable photo path,
    so it is treated as "no photo" rather than crashing the whole selection pass.
    """
    raw = _as_dict(getattr(li, "raw", None))
    images = _as_dict(raw.get("images"))
    if images.get("real"):
        return False
    if images.get("street"):
        return False
    return True


def _priority(li: Listing) -> int:
    """Sort key (ascending): spend the capped budget on operator-facing leads first.

    Every nested read is coerced: real board data has raw['grade'] == 'A' and
    raw['distress_stack'] == 'HOT' as bare strings, and `(x or {}).get(...)` on
    those raises AttributeError out of list.sort(), killing the enricher.
    """
    try:
        raw = _as_dict(getattr(li, "raw", None))
        tier = _as_dict(raw.get("distress_stack")).get("tier")
        grade = _as_dict(raw.get("grade")).get("overall")
        # Tolerate the flattened shapes too, so the ordering still means
        # something instead of silently scoring every lead 0.
        if tier is None and isinstance(raw.get("distress_stack"), str):
            tier = raw["distress_stack"]
        if grade is None and isinstance(raw.get("grade"), str):
            grade = raw["grade"]
        score = 0
        if tier == "HOT":
            score += 3
        elif tier == "WARM":
            score += 2
        if grade in ("A", "B"):
            score += 2
        elif grade in ("C", "D"):
            score += 1
        return -score
    except Exception:  # noqa: BLE001 - ordering must never abort the run
        return 0


def _location_query(li: Listing) -> Optional[str]:
    """The `location` value for Street View.

    Prefers lat/lng: any lead reaching this enricher has a validated street
    address, so its coordinates are address- or parcel-derived (precise), and a
    coordinate can't be mis-matched to a same-named street in another county.
    Falls back to a fully-qualified address string.
    """
    if li.latitude is not None and li.longitude is not None:
        try:
            lat, lng = float(li.latitude), float(li.longitude)
            if -90 <= lat <= 90 and -180 <= lng <= 180 and (lat, lng) != (0.0, 0.0):
                return f"{lat:.6f},{lng:.6f}"
        except Exception:  # noqa: BLE001
            pass
    street = (li.street_address or "").strip()
    state = (li.state or "").strip()
    city = (li.city or "").strip()
    zipc = (li.zip_code or "").strip()
    if not (street and state and (city or zipc)):
        return None  # too ambiguous to trust — a wrong-house photo is worse than none
    parts = [street, city, f"{state} {zipc}".strip()]
    return ", ".join(p for p in parts if p)


def _targets(listings: Iterable[Listing]) -> list[Listing]:
    """Select + order the leads worth spending on.

    Per-lead try/except: one malformed lead must cost that lead's photo, not the
    entire enricher. Same for the sort — _priority is already exception-proof,
    but a comparison blowing up here would abort a run that has money on the line.
    """
    out: list[Listing] = []
    for li in listings:
        try:
            # is_pinpointable_address, NOT _is_valid_street_address: the latter
            # accepts a bare road ("MEADOW RD"), which geocodes to the road
            # CENTROID. Street View happily returns imagery for it (measured: 84%
            # of the board's 1,237 numberless addresses), so we would pay for a
            # photo of a random stretch of road and then attach it to the lead and
            # condition-grade it as that house. Requires a real house number.
            if (is_pinpointable_address(getattr(li, "street_address", None))
                    and _needs_street_photo(li)
                    and _location_query(li) is not None):
                out.append(li)
        except Exception as exc:  # noqa: BLE001
            log.debug("streetview.target_skipped",
                      source_url=getattr(li, "source_url", None), err=str(exc))
    try:
        out.sort(key=_priority)
    except Exception as exc:  # noqa: BLE001
        log.warning("streetview.priority_sort_failed", err=str(exc))
    return out


# --------------------------------------------------------------------------- #
# image handling
# --------------------------------------------------------------------------- #
def _slug(li: Listing) -> str:
    """Stable per-property filename so a re-run hits the disk cache, not the API."""
    parcel = (li.parcel_id or "").strip()
    county = (li.county or "").strip().lower()
    state = (li.state or "").strip().lower()
    if parcel:
        base = f"{state}_{county}_{parcel}"
    else:
        base = f"{state}_{county}_{(li.street_address or '').strip().lower()}"
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:120] or "unknown"


def _is_jpeg(b: bytes) -> bool:
    return len(b) > 1024 and b[:2] == b"\xff\xd8"


def _thumbnail(data: bytes, px: int) -> Optional[bytes]:
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((px, px))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=78)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def _attach(li: Listing, rel_path: str, meta: Optional[dict], query: str) -> None:
    """Attach the street photo + provenance and re-pick primary.

    Priority is the existing one from enrichment_images: real > street > aerial > map.
    """
    images = _images(li)
    prev_primary = images.get("primary")
    images["street"] = rel_path
    images["street_source"] = "google_streetview"
    meta = meta or {}
    prior = images.get("streetview")
    if meta.get("cached") and isinstance(prior, dict) and prior.get("pano_id"):
        # Re-attaching a photo we already own: keep the original pano/date
        # provenance rather than overwriting it with nulls.
        prior["local_path"] = rel_path
        prior["reattached_from_cache_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds")
    else:
        images["streetview"] = {
            "provider": "google_streetview",
            "pano_id": meta.get("pano_id"),
            "capture_date": meta.get("date"),
            "pano_location": meta.get("location"),
            "attribution": meta.get("copyright") or "© Google",
            "query": query,
            "from_disk_cache": bool(meta.get("cached")),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "local_path": rel_path,
            "note": "Google Street View Static image, downloaded server-side and "
                    "self-hosted (the signed URL carries the API key and must "
                    "never be published).",
        }

    real = images.get("real") or []
    primary = (
        (real[0] if isinstance(real, list) and real else None)
        or images.get("street")
        or images.get("aerial")
        or images.get("map")
    )
    if primary:
        images["primary"] = primary
        zillow = li.raw.get("zillow")
        if zillow is None:
            zillow = {}
            li.raw["zillow"] = zillow
        # Only move the dashboard alias when it was pointing at the image we just
        # superseded (or nothing) — never clobber a scraper's real listing photo.
        # A non-dict raw['zillow'] is left exactly as found (no crash, no data
        # loss); the alias just isn't synced for that lead.
        if isinstance(zillow, dict) and zillow.get("photo") in (None, "", prev_primary):
            zillow["photo"] = primary


# --------------------------------------------------------------------------- #
# API calls
# --------------------------------------------------------------------------- #
async def _metadata(http, key: str, location: str, cfg: _Config) -> Optional[dict]:
    """FREE metadata probe. Returns the payload when status == OK, else None.

    Google: "Street View Static API metadata requests are available at no charge.
    No quota is consumed when you request metadata." This is what makes the
    budget survivable — most no-imagery leads cost nothing.
    """
    r = await http.get(
        METADATA_URL,
        params={
            "location": location,
            "radius": cfg.radius_m,
            "source": "outdoor",
            "key": key,
        },
        timeout=cfg.timeout_s,
    )
    if getattr(r, "status_code", 0) != 200:
        return None
    try:
        payload = r.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("status") != "OK":
        return None
    return payload


async def _image_bytes(http, key: str, pano_id: Optional[str], location: str,
                       cfg: _Config) -> Optional[bytes]:
    """The ONE billed call. Only ever reached after a reserved ledger charge."""
    params: dict[str, Any] = {
        "size": cfg.size,
        "source": "outdoor",
        "return_error_code": "true",
        "key": key,
    }
    if pano_id:
        params["pano"] = pano_id      # exactly the pano metadata validated
    else:
        params["location"] = location
        params["radius"] = cfg.radius_m
    r = await http.get(IMAGE_URL, params=params, timeout=cfg.timeout_s)
    if getattr(r, "status_code", 0) != 200:
        return None
    content = getattr(r, "content", b"") or b""
    return content if _is_jpeg(content) else None


# --------------------------------------------------------------------------- #
# main entry point
# --------------------------------------------------------------------------- #
async def enrich_streetview(
    listings: Iterable[Listing],
    photos_dir: Optional[Path] = None,
) -> dict:
    """Attach a Google Street View photo to leads with a real street address.

    Returns a stats dict. Never raises: any per-lead failure is swallowed and
    counted so one bad lead can't kill a run.
    """
    stats: dict[str, Any] = {
        "enabled": False, "targets": 0, "cached": 0,
        "metadata_calls": 0, "metadata_ok": 0, "no_imagery": 0,
        "billed_image_calls": 0, "attached": 0, "errors": 0,
        "skipped_run_cap": 0, "skipped_month_cap": 0, "skipped_metadata_cap": 0,
        "skipped_ledger_locked": 0, "skipped_ledger_unwritable": 0,
        "budget_hit": 0, "dry_run": 0,
    }
    cfg = _Config()
    if not cfg.enabled:
        log.info("streetview.disabled",
                 hint="paid API — set FORECLOSURE_STREETVIEW=1 to enable "
                      "(see docs/streetview_setup.md)")
        return stats

    key = _load_api_key(cfg)
    if not key:
        log.info("streetview.no_api_key", key_file=str(cfg.key_file),
                 hint=f"put the key in {cfg.key_file} or GOOGLE_MAPS_API_KEY — "
                      "see docs/streetview_setup.md (billing must be enabled on "
                      "the Cloud project even for the free tier)")
        return stats

    leads = list(listings)
    targets = _targets(leads)
    stats["enabled"] = True
    stats["targets"] = len(targets)
    stats["dry_run"] = 1 if cfg.dry_run else 0
    if not targets:
        log.info("streetview.no_targets", listings=len(leads))
        return stats

    pdir = Path(photos_dir) if photos_dir else _DEFAULT_PHOTO_DIR
    try:
        pdir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        log.error("streetview.photo_dir_failed", path=str(pdir), err=str(exc))
        return stats

    # Pass 0 — FREE disk-cache attach for photos already bought in a prior run.
    # Deliberately ahead of every cap/ledger check: re-attaching a file we own
    # costs nothing, so it must never be blocked by a spend guard.
    pending: list[Listing] = []
    for li in targets:
        try:
            fname = f"{_slug(li)}.jpg"
            fpath = pdir / fname
            if fpath.exists() and fpath.stat().st_size > 0:
                _attach(li, f"parcel_photos/streetview/{fname}", {"cached": True}, "cache")
                stats["cached"] += 1
            else:
                pending.append(li)
        except Exception:  # noqa: BLE001
            stats["errors"] += 1
    if not pending:
        log.info("streetview.all_cached", targets=len(targets), cached=stats["cached"])
        return stats

    if cfg.month_cap != cfg.month_cap_requested:
        log.warning(
            "streetview.monthly_cap_clamped",
            requested=cfg.month_cap_requested, applied=cfg.month_cap,
            free_tier=FREE_TIER_MONTHLY,
            hint="set STREETVIEW_ALLOW_PAID=1 to intentionally exceed the free tier",
        )

    ledger = _Ledger(cfg.counter_path, _month_key(), cfg.run_cap, cfg.month_cap,
                     cfg.metadata_cap, cfg.metadata_month_cap, cfg.lock_timeout_s)
    if not await ledger.preflight():
        log.error("streetview.abort_no_ledger", path=str(cfg.counter_path),
                  hint="cannot lock or persist the monthly spend counter — "
                       "refusing to make billed calls")
        return stats

    remaining_month = max(0, cfg.month_cap - ledger.month_billed)
    log.info(
        "streetview.start",
        targets=len(targets), pending=len(pending), cached=stats["cached"],
        run_cap=cfg.run_cap, month_cap=cfg.month_cap,
        month_used=ledger.month_billed, month_remaining=remaining_month,
        free_tier=FREE_TIER_MONTHLY, dry_run=cfg.dry_run,
        counter=str(cfg.counter_path),
    )

    start = time.monotonic()
    stop = {"flag": False}   # set once a hard cap/budget is hit: stop probing

    async with client(timeout=cfg.timeout_s) as http:

        async def one(li: Listing) -> None:
            try:
                fname = f"{_slug(li)}.jpg"
                fpath = pdir / fname
                rel = f"parcel_photos/streetview/{fname}"

                location = _location_query(li)
                if not location:
                    return

                # 1) FREE metadata probe — never spend before we know imagery exists.
                if not await ledger.reserve_metadata():
                    stats["skipped_metadata_cap"] += 1
                    stop["flag"] = True
                    return
                meta = await _metadata(http, key, location, cfg)
                stats["metadata_calls"] += 1
                if not meta:
                    stats["no_imagery"] += 1
                    return
                stats["metadata_ok"] += 1

                if cfg.dry_run:
                    return  # coverage probe only — never spends

                # 2) reserve the billed call BEFORE issuing it.
                granted, reason = await ledger.reserve_image()
                if not granted:
                    if reason == "run_cap":
                        stats["skipped_run_cap"] += 1
                    elif reason == "month_cap":
                        stats["skipped_month_cap"] += 1
                    elif reason == "ledger_locked":
                        stats["skipped_ledger_locked"] += 1
                    elif reason == "ledger_unwritable":
                        stats["skipped_ledger_unwritable"] += 1
                    stop["flag"] = True
                    return

                stats["billed_image_calls"] += 1
                data = await _image_bytes(http, key, meta.get("pano_id"),
                                          location, cfg)
                if not data:
                    stats["errors"] += 1
                    return

                # 3) self-host it (never publish the key-bearing URL).
                blob = _thumbnail(data, cfg.thumb_px) or data
                fpath.write_bytes(blob)
                _attach(li, rel, meta, location)
                stats["attached"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                log.debug("streetview.lead_failed", source_url=getattr(li, "source_url", None),
                          err=str(exc))

        # Bounded worker pool rather than gather-everything: with 12k targets a
        # gather would schedule every coroutine up front, so a cap/budget stop
        # could not actually stop anything. Workers pull one lead at a time and
        # exit the moment a hard cap or the wall clock trips.
        cursor = {"i": 0}
        cursor_lock = asyncio.Lock()

        async def _next() -> Optional[Listing]:
            async with cursor_lock:
                if stop["flag"] or cursor["i"] >= len(pending):
                    return None
                li = pending[cursor["i"]]
                cursor["i"] += 1
                return li

        async def worker() -> None:
            while True:
                li = await _next()
                if li is None:
                    return
                if (time.monotonic() - start) > cfg.budget_s:
                    if not stop["flag"]:
                        stats["budget_hit"] += 1
                        stop["flag"] = True
                    return
                await one(li)

        await asyncio.gather(*(worker() for _ in range(cfg.concurrency)),
                             return_exceptions=True)

    # One write for the whole run's free-metadata tally (see reserve_metadata).
    await ledger.finalize()

    stats["month_billed_total"] = ledger.month_billed
    stats["month_metadata_total"] = ledger.month_metadata
    stats["monthly_cap"] = cfg.month_cap
    stats["metadata_monthly_cap"] = cfg.metadata_month_cap
    stats["month"] = ledger.month
    # Honest cost: only the portion of this month's calls ABOVE the free tier is
    # billable, and only the slice of that portion this run is responsible for.
    before_run = ledger.month_billed - ledger.run_billed
    paid_this_run = max(0, ledger.month_billed - max(before_run, FREE_TIER_MONTHLY))
    paid_this_month = max(0, ledger.month_billed - FREE_TIER_MONTHLY)
    stats["est_cost_usd_this_run"] = round(paid_this_run * PAID_PER_1000_USD / 1000.0, 2)
    stats["est_cost_usd_month"] = round(paid_this_month * PAID_PER_1000_USD / 1000.0, 2)
    log.info("streetview.done", elapsed_s=round(time.monotonic() - start, 1), **stats)
    return stats
