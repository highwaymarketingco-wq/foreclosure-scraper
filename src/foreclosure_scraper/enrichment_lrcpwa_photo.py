"""NC PTS Cloud land-records PROPERTY PHOTOS — the county's own drive-by photo
of the building, hosted locally for the dashboard (FREE).

The land-records PWA (lrcpwa.ncptscloud.com) carries the county assessor's
building photos. The image endpoint is header-gated (needs X-Tenant), so a
plain <img> tag can't load it — we fetch server-side, thumbnail, and host the
copy under docs/parcel_photos/ so the static dashboard can show it.

Flow per lead (Henderson/Madison/Rutherford/Burke, reusing raw['lrcpwa'].id set
by enrichment_lrcpwa_parcel):
    GET /api/getParcelDetails?ParcelId=<id>   (X-Tenant)
        -> imageMetadata.buildingImageMetadata[] {buildingPk, hasPhoto}
    GET /api/GetParcelImage?ImageType=Photo&ParcelId=<parcelPk>&BuildingPk=<bpk>
        -> JPEG -> thumbnail(640) -> docs/parcel_photos/<county>_<parcel>.jpg

Sets raw['images']['real'] = ["parcel_photos/<file>"] (+ primary + the
zillow.photo alias the dashboard reads). Capped to the leads worth a photo
(distress HOT/WARM or graded) so the git repo doesn't balloon. Idempotent
(skips leads already imaged / files already on disk). Gate FORECLOSURE_LRCPWA_PHOTO=0.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import time
from pathlib import Path
from typing import Iterable, Optional

import httpx
import structlog

from .http_client import client
from .models import Listing
from .enrichment_lrcpwa_parcel import BASE, TENANTS, _county

log = structlog.get_logger(__name__)

_ENABLED = os.environ.get("FORECLOSURE_LRCPWA_PHOTO") != "0"
# Count cap + wall-clock budget. This one was already the best-behaved of the
# image phases (budget enforced per lead inside `one()`), and it is NOT the
# bottleneck — recent runs saw targets=23 because _worth_photo gates on a
# distress tier / letter grade in 4 PTS-Cloud counties. Raised anyway so a
# future backfill (or the address-resolver unlocking a batch of parcels) isn't
# silently truncated. TRADEOFF: at ~2 leads/s with 6-way concurrency the budget,
# not the count, is what ends this phase — 1800s worst case, typically seconds.
_MAX = int(os.environ.get("LRCPWA_PHOTO_MAX", "6000"))
_BUDGET_S = float(os.environ.get("LRCPWA_PHOTO_BUDGET_S", "1800"))
_THUMB = int(os.environ.get("LRCPWA_PHOTO_THUMB", "640"))
_DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "parcel_photos"

# Worth a photo: an operator-facing lead (has a distress tier or a letter grade).
_GOOD_GRADES = {"A", "B", "C", "D"}


def _worth_photo(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    tier = (raw.get("distress_stack") or {}).get("tier")
    grade = (raw.get("grade") or {}).get("overall")
    return tier in ("HOT", "WARM") or grade in _GOOD_GRADES


def _has_image(li: Listing) -> bool:
    im = (li.raw or {}).get("images") or {}
    return bool(im.get("real") or im.get("aerial") or im.get("street"))


def _slug(county: str, parcel: str) -> str:
    return f"{county.lower()}_{re.sub(r'[^A-Za-z0-9]', '', parcel)}.jpg"


def _is_img(b: bytes) -> bool:
    return b[:2] == b"\xff\xd8" or b[:4] == b"\x89PNG"


async def _detail(http: httpx.AsyncClient, tenant: str, pid) -> Optional[dict]:
    try:
        r = await http.get(f"{BASE}/api/getParcelDetails?ParcelId={pid}",
                            headers={"X-Tenant": tenant, "Accept": "application/json"})
        if r.status_code != 200 or not r.text.strip():
            return None
        j = r.json()
        return j[0] if isinstance(j, list) and j else j
    except Exception:
        return None


async def _photo_bytes(http: httpx.AsyncClient, tenant: str, parcel_pk, building_pk) -> Optional[bytes]:
    try:
        r = await http.get(
            f"{BASE}/api/GetParcelImage",
            params={"ImageType": "Photo", "ParcelId": parcel_pk, "BuildingPk": building_pk},
            headers={"X-Tenant": tenant})
        if r.status_code == 200 and _is_img(r.content):
            return r.content
    except Exception:
        return None
    return None


def _thumbnail(data: bytes) -> Optional[bytes]:
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((_THUMB, _THUMB))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=78)
        return out.getvalue()
    except Exception:
        return None


async def enrich_lrcpwa_photo(listings: Iterable[Listing],
                              photos_dir: Optional[Path] = None) -> dict:
    stats = {"targets": 0, "fetched": 0, "cached": 0, "no_photo": 0, "skipped_budget": 0}
    if not _ENABLED:
        return stats
    pdir = Path(photos_dir) if photos_dir else _DEFAULT_DIR
    pdir.mkdir(parents=True, exist_ok=True)

    targets = [li for li in listings
               if _county(li) and (li.parcel_id or "").strip()
               and not _has_image(li) and _worth_photo(li)]
    stats["targets"] = len(targets)
    if not targets:
        return stats

    start = time.monotonic()
    sem = asyncio.Semaphore(int(os.environ.get("LRCPWA_PHOTO_CONCURRENCY", "6")))
    async with client(timeout=30.0) as http:
        async def one(li: Listing):
            if stats["fetched"] + stats["cached"] >= _MAX or (time.monotonic() - start) > _BUDGET_S:
                stats["skipped_budget"] += 1
                return
            county = _county(li)
            parcel = (li.parcel_id or "").strip()
            fname = _slug(county, parcel)
            fpath = pdir / fname
            if fpath.exists() and fpath.stat().st_size > 0:
                _set_image(li, fname)
                stats["cached"] += 1
                return
            pid = ((li.raw or {}).get("lrcpwa") or {}).get("id")
            async with sem:
                if not pid:  # not address-resolved yet — resolve id via search
                    pid = await _resolve_id(http, county, parcel)
                if not pid:
                    return
                det = await _detail(http, county, pid)
                if not det:
                    return
                im = det.get("imageMetadata") or {}
                ppk = im.get("parcelPk") or det.get("parcelPk")
                bldgs = [b for b in (im.get("buildingImageMetadata") or []) if b.get("hasPhoto")]
                if not bldgs:
                    stats["no_photo"] += 1
                    return
                raw = await _photo_bytes(http, county, ppk, bldgs[0]["buildingPk"])
            if not raw:
                stats["no_photo"] += 1
                return
            thumb = _thumbnail(raw)
            if not thumb:
                return
            fpath.write_bytes(thumb)
            _set_image(li, fname)
            stats["fetched"] += 1

        await asyncio.gather(*(one(li) for li in targets))
    log.info("lrcpwa_photo.done", **stats)
    return stats


async def _resolve_id(http: httpx.AsyncClient, tenant: str, parcel: str):
    import json as _json
    try:
        r = await http.post(f"{BASE}/api/GetParcelDetailsByQueryParam",
                            headers={"X-Tenant": tenant, "Content-Type": "application/json"},
                            content=_json.dumps({"searchKey": "ParcelId", "searchValue": parcel}))
        if r.status_code == 200 and r.text.strip() not in ("", "null", "[]"):
            j = r.json()
            d = j[0] if isinstance(j, list) and j else j
            return d.get("id") if isinstance(d, dict) else None
    except Exception:
        return None
    return None


def _set_image(li: Listing, fname: str):
    if not isinstance(li.raw, dict):
        li.raw = {}
    rel = f"parcel_photos/{fname}"
    images = li.raw.setdefault("images", {})
    images["real"] = [rel]
    images.setdefault("primary", rel)
    # dashboard reads raw.zillow.photo as the card image alias
    li.raw.setdefault("zillow", {})
    li.raw["zillow"]["photo"] = rel
    li.raw["images"]["source"] = "lrcpwa_assessor_photo"
