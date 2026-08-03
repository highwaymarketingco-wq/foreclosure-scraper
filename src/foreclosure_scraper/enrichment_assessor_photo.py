"""FREE county-assessor PROPERTY PHOTOS — the county's own drive-by photo of the
structure, hosted locally for the dashboard.

Why this lane matters: Street View / aerial imagery needs a STREET ADDRESS, and
41% of the board has none. An assessor photo is keyed by PARCEL, so it reaches
exactly the leads the address-based photo paths can never touch. Every endpoint
below is public, unauthenticated, no API key, no CAPTCHA, no WAF bypass.

LIVE-VERIFIED COUNTY MATRIX (2026-07-27, against real board parcels)
--------------------------------------------------------------------
WORKS (implemented here):
  NC Buncombe   image-api.spatialest.com/api/v1.2/nc-buncombe-images/image
                ?term=<15-digit PIN>:image&size=lrg      18/20 sample parcels
                (10-digit board PINs are zero-padded to 15: pin + "00000")
  NC Lincoln    Server_TaxParcelViewerSP/MapServer/6 (Improvements) .PRIMARYIMA
                -> arcgisserver.lincolncountync.gov/Photos/<PRIMARYIMA>
                keyed by AGPAR_ (== the 5-digit parcel_id most Lincoln board
                leads carry); a 10-digit PIN is first mapped via MapServer/0.
                7/15 sample parcels (misses are vacant land)
  NC Gaston     property.spatialest.com/nc/gaston POST /api/v2/search {term}
                -> id -> api.spatialest.com/v1/nc/gaston/images-api?id=..&json=true
                -> gastonnc.devnetwedge.com/PropertyImages/ASRIMG/... (photo).
                The /CAMA/ sibling URL is the SKETCH and is filtered out.
                Gaston's search only matches on ADDRESS (a PIN query returns an
                unfiltered page), so this adapter needs a street address.
  NC Rutherford / Burke / Madison / Henderson
                lrcpwa.ncptscloud.com GetParcelImage (same host as
                enrichment_lrcpwa_photo) BUT resolving with searchKey "Pin" as
                well as "ParcelId". The existing module only tries "ParcelId",
                so every Rutherford/Burke lead whose parcel_id is a 10-digit PIN
                was unreachable. With the Pin key: Rutherford 5/10, Burke 7/10.

CONFIRMED WALLS / NO-PHOTO (do not re-chase):
  SC Spartanburg  Photos exist ONLY on qpublic.schneidercorp.com, which is behind
                  Cloudflare Turnstile. The county's own maps.spartanburgcounty.org
                  GIS/CAMA_Parcels layer carries the full CAMA record (100+ fields:
                  LivingArea, YearBuilt, Foundation, RoofCover...) but NO image
                  column. WALL.
  NC McDowell     bttaxpayerportal.com/ITSPublicMD/AppraisalCard.aspx?id=<PIN>
                  returns a PDF, but the only embedded raster is the building
                  SKETCH (verified visually: 640x480 / 960x720 near-white line
                  drawings, pixel mean 243-247). No photo anywhere on the card.
  NC Polk         parcels.polknc.org:8080/<TMS>.pdf record cards contain ZERO
                  embedded images.
  NC Cleveland    webgis.net/nc/cleveland/PropertyCard.php is a plain-text card
                  (no <img>); the Tax MapServer has no image layer.
  NC Transylvania RE-CHECKED 2026-08-03, and the earlier "both 100% NULL" note was
                  half wrong: `Report_URL` IS 100% NULL (0 of 31,751), but `CARD`
                  is populated on 31,633 rows (99.6%), and the report PDF really
                  does resolve without it:
                    gis.transylvaniacounty.org/GISReports/propertyreports/
                    Parcel_{PIN}-{CARD}.pdf            42/42 sampled -> HTTP 200
                  It is still NOT a photo lane. Every card carries exactly three
                  rasters and the shape signature is identical on all 42 sampled
                  parcels (in-town, rural, improved and vacant alike):
                    532x256  AERIAL (orthophoto)
                    532x252  AERIAL (second vintage/zoom)
                    300x197  the county LOGO (byte-identical across every PDF)
                  There is no drive-by photo slot on the card at all. Wiring this
                  in would publish an AERIAL as raw['images']['real'], which is
                  exactly what this module's contract forbids (see _has_real_photo:
                  "Aerial/street fallbacks do NOT count"), and enrichment_images
                  already supplies aerials for free. So: WALL for photos, and do
                  not re-chase it as one.
                  The PDF is, separately, a rich free CAMA-attribute source (year
                  built, heated sqft, beds, baths, half-baths, fireplaces, land /
                  building / assessed value, sale price + date, deed book/page) —
                  that belongs in an attribute lane, not here.
  NC Mitchell     43 layers, none carry building photos.
  SC Anderson     NewPropertyViewer/MapServer/5 has no image field.
  SC Laurens      Pebble/PropertyParcel has no image field on any layer.
  SC Oconee / Pickens / Union / Cherokee / Georgetown  qPublic only. WALL.

Flow per lead: adapter -> raw JPEG/PNG bytes -> thumbnail(640) ->
docs/parcel_photos/<county>_<parcel>.jpg -> raw['images']['real'] + primary +
the raw['zillow']['photo'] alias the dashboard card reads.

Idempotent: a lead that already has a real image is skipped, and an
already-downloaded file that sniffs as a real JPEG/PNG is re-wired without a
fetch (the slug matches enrichment_lrcpwa_photo's, so its existing files are
reused, never re-downloaded).

Bounding:
  ASSESSOR_PHOTO_MAX (default 1000)      lead cap. select_targets() is the SINGLE
                                         enforcement point — it truncates the
                                         target list and the driver does not
                                         re-check.
  ASSESSOR_PHOTO_BUDGET_S (default 1800) wall-clock budget, checked inside the
                                         semaphore right before each fetch.
  ASSESSOR_PHOTO_THUMB / _CONCURRENCY    thumbnail edge px / parallel fetches.
  FORECLOSURE_ASSESSOR_PHOTO=0           gate the whole lane off.
All of them are read at CALL time, so an orchestrator that sets them after
importing this module is respected.

A capped run is striped across counties by expected yield (COUNTY_HIT_RATE), not
handed wholesale to whichever county holds the address-less leads.
"""
from __future__ import annotations

import asyncio
import io
import json as _json
import os
import re
import time
from pathlib import Path
from typing import Iterable, Optional

import httpx
import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------- config ----
# Every knob is read at CALL time, never captured at import time. The
# orchestrator imports this module long before it decides on caps/budgets, and
# an import-time constant would silently ignore any env var set afterwards.
_DEF_MAX = 1000
_DEF_BUDGET_S = 1800.0
_DEF_THUMB = 640
_DEF_CONC = 6
_DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "parcel_photos"


def _env_num(name: str, default, cast):
    """Env knob -> number, falling back to the default on unset/garbage."""
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def _enabled() -> bool:
    return os.environ.get("FORECLOSURE_ASSESSOR_PHOTO") != "0"


def _max_leads() -> int:
    return _env_num("ASSESSOR_PHOTO_MAX", _DEF_MAX, int)


def _budget_s() -> float:
    return _env_num("ASSESSOR_PHOTO_BUDGET_S", _DEF_BUDGET_S, float)


def _thumb_px() -> int:
    return _env_num("ASSESSOR_PHOTO_THUMB", _DEF_THUMB, int)


def _concurrency() -> int:
    return max(1, _env_num("ASSESSOR_PHOTO_CONCURRENCY", _DEF_CONC, int))

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

# Endpoints (all public, no key, no login).
_BUNCOMBE_IMG = "https://image-api.spatialest.com/api/v1.2/nc-buncombe-images/image"
_BUNCOMBE_REF = "https://prc-buncombe.spatialest.com/"
_LINCOLN_MS = ("https://arcgisserver.lincolncountync.gov/arcgis/rest/services/"
               "Server_TaxParcelViewerSP/MapServer")
_LINCOLN_PHOTOS = "https://arcgisserver.lincolncountync.gov/Photos"
_GASTON_BASE = "https://property.spatialest.com/nc/gaston"
_GASTON_IMAGES = "https://api.spatialest.com/v1/nc/gaston/images-api"
_NCPTS = "https://lrcpwa.ncptscloud.com"
# NC PTS land-records tenants (IsValidTenant=true; every other NC county 500s).
_NCPTS_TENANTS = {"Henderson", "Madison", "Rutherford", "Burke"}

_CSRF_RE = re.compile(r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', re.I)

# Lincoln's photo table stores "no photo on file" as this sentinel filename.
_LINCOLN_NO_PHOTO = "images.gif"


# ------------------------------------------------------------ pure helpers --
_COUNTY_SUFFIX_RE = re.compile(r"\s+county\s*$", re.I)


def _county_name(li: Listing) -> str:
    """Board county strings arrive in every casing ("buncombe county", "MCDOWELL",
    "Burke") — normalize to the Title-case bare name the adapter table is keyed on."""
    return _COUNTY_SUFFIX_RE.sub("", (li.county or "").strip()).strip().title()


def _slug(county: str, parcel: str) -> str:
    """docs/parcel_photos filename. Deliberately IDENTICAL to
    enrichment_lrcpwa_photo._slug so a photo either module already pulled is
    detected on disk and reused instead of re-downloaded."""
    return f"{county.lower()}_{re.sub(r'[^A-Za-z0-9]', '', parcel)}.jpg"


def _is_img(b: bytes | None) -> bool:
    return bool(b) and (b[:2] == b"\xff\xd8" or b[:4] == b"\x89PNG")


def _file_is_img(p: Path) -> bool:
    """A file already on disk only counts as a reusable photo when it actually
    STARTS with JPEG/PNG magic bytes. "exists and non-empty" is not enough: a
    truncated download or a cached HTML/JSON error page is non-empty too, and
    would get wired up as this property's photo forever (nothing re-checks it)."""
    try:
        with p.open("rb") as fh:
            return _is_img(fh.read(8))
    except OSError:
        return False


def _has_real_photo(li: Listing) -> bool:
    """True when the lead already carries a ground-level photo. Aerial/street
    fallbacks do NOT count — an assessor photo is strictly better than either."""
    im = (li.raw or {}).get("images") or {}
    return bool(im.get("real"))


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def buncombe_pin_variants(parcel: str | None) -> list[str]:
    """Buncombe's image key is the 15-digit pinnum (10-digit pin + 5-digit ext).
    Board leads carry either form, so try the 15-digit shape first (that's what
    the image host indexes) then the raw digits."""
    d = _digits(parcel)
    if not d:
        return []
    out: list[str] = []
    if len(d) == 10:
        out.append(d + "00000")
    elif len(d) == 15:
        out.append(d)
    elif 10 < len(d) < 15:
        out.append(d.ljust(15, "0"))
    if d not in out:
        out.append(d)
    return out


def pick_gaston_photo(urls: Iterable[str]) -> Optional[str]:
    """Gaston's images-api returns [ASRIMG photo, CAMA sketch]. Verified live:
    /ASRIMG/ is the drive-by photo, /CAMA/ is the dimensioned floor sketch."""
    cands = [u for u in (urls or []) if isinstance(u, str) and u.startswith("http")]
    for u in cands:
        if "/ASRIMG/" in u.upper():
            return u
    return None


def pick_ncpts_photo(urls: Iterable[str]) -> Optional[str]:
    """NC PTS image URLs are explicitly typed (?type=photo / ?type=sketch)."""
    for u in urls or []:
        if isinstance(u, str) and "type=photo" in u:
            return u
    return None


def lincoln_photo_names(rows: Iterable[dict]) -> list[str]:
    """PRIMARYIMA values from the Improvements layer, sentinel rows dropped."""
    out: list[str] = []
    for r in rows or []:
        name = (r or {}).get("PRIMARYIMA") or (r or {}).get("IMAGE")
        if not name or not isinstance(name, str):
            continue
        name = name.strip()
        if name.lower() == _LINCOLN_NO_PHOTO:
            continue
        if name not in out:
            out.append(name)
    return out


_GRADE_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}


def _rank_key(li: Listing) -> tuple:
    """Descending WITHIN-COUNTY sort key so a tight cap spends its budget on the
    leads an operator would actually look at: HOT/WARM distress, then grade, then
    score. Cross-county ordering is done by expected yield in select_targets —
    ranking address-less leads first GLOBALLY is what skewed a run to Lincoln."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    stack = raw.get("distress_stack") or {}
    tier = {"HOT": 3, "WARM": 2, "COOL": 1}.get(stack.get("tier"), 0)
    grade = _GRADE_RANK.get(((raw.get("grade") or {}).get("overall") or ""), 0)
    try:
        score = int(stack.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    # Address-less leads first: they are the ones no street-view path can reach.
    no_addr = 0 if (li.street_address or "").strip() else 1
    return (no_addr, tier, grade, score)


def _thumbnail(data: bytes) -> Optional[bytes]:
    try:
        from PIL import Image
        px = _thumb_px()
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((px, px))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=78)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def _set_image(li: Listing, fname: str, source: str) -> None:
    if not isinstance(li.raw, dict):
        li.raw = {}
    rel = f"parcel_photos/{fname}"
    images = li.raw.setdefault("images", {})
    images["real"] = [rel]
    # NOT setdefault: enrichment_images ranks primary real > street > aerial >
    # map, so a lead that already picked an aerial/map/street primary must be
    # PROMOTED to the real drive-by photo we just landed. setdefault left the
    # aerial in place and the dashboard kept showing a rooftop.
    images["primary"] = rel
    images["source"] = source
    # the dashboard card reads raw.zillow.photo as its image alias
    li.raw.setdefault("zillow", {})
    li.raw["zillow"]["photo"] = rel
    li.raw["assessor_photo"] = {"county": _county_name(li), "source": source, "file": rel}


# --------------------------------------------------------------- adapters ---
# Each adapter: async (http, listing) -> raw image bytes | None. NEVER raises.

async def _fetch_buncombe(http: httpx.AsyncClient, li: Listing) -> Optional[bytes]:
    for term in buncombe_pin_variants(li.parcel_id):
        try:
            r = await http.get(_BUNCOMBE_IMG,
                               params={"term": f"{term}:image", "size": "lrg"},
                               headers={**_UA, "Referer": _BUNCOMBE_REF})
        except Exception:  # noqa: BLE001
            continue
        if r.status_code == 200 and _is_img(r.content):
            return r.content
    return None


async def _lincoln_akpar(http: httpx.AsyncClient, li: Listing) -> Optional[str]:
    """Lincoln's photo table is keyed by AGPAR_ (an internal 5-6 digit parcel
    key). Most Lincoln board leads already carry that key as parcel_id; a
    10-digit PIN is mapped through the parcel layer first."""
    key = _digits(li.parcel_id)
    if not key:
        return None
    if len(key) <= 7:
        return key
    try:
        r = await http.get(f"{_LINCOLN_MS}/0/query",
                           params={"where": f"PIN='{key}'", "outFields": "AKPAR_",
                                   "f": "json", "returnGeometry": "false"},
                           headers=_UA)
        feats = (r.json() or {}).get("features") or []
    except Exception:  # noqa: BLE001
        return None
    if not feats:
        return None
    ak = (feats[0].get("attributes") or {}).get("AKPAR_")
    return str(ak) if ak else None


async def _fetch_lincoln(http: httpx.AsyncClient, li: Listing) -> Optional[bytes]:
    ak = await _lincoln_akpar(http, li)
    if not ak:
        return None
    try:
        r = await http.get(f"{_LINCOLN_MS}/6/query",
                           params={"where": f"AGPAR_='{ak}'",
                                   "outFields": "PRIMARYIMA,IMAGE",
                                   "f": "json", "returnGeometry": "false"},
                           headers=_UA)
        rows = [f.get("attributes") or {} for f in ((r.json() or {}).get("features") or [])]
    except Exception:  # noqa: BLE001
        return None
    for name in lincoln_photo_names(rows):
        try:
            ri = await http.get(f"{_LINCOLN_PHOTOS}/{name}", headers=_UA)
        except Exception:  # noqa: BLE001
            continue
        if ri.status_code == 200 and _is_img(ri.content):
            return ri.content
    return None


async def _spatialest_csrf(http: httpx.AsyncClient, base: str) -> Optional[str]:
    try:
        r = await http.get(f"{base}/", headers=_UA)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200:
        return None
    m = _CSRF_RE.search(r.text)
    return m.group(1) if m else None


async def _fetch_gaston(http: httpx.AsyncClient, li: Listing) -> Optional[bytes]:
    """Gaston: resolve the Spatialest PID by ADDRESS (its search ignores a PIN
    query and returns an unfiltered page), then pull the ASRIMG photo."""
    addr = (li.street_address or "").strip()
    if not addr:
        return None
    csrf = await _spatialest_csrf(http, _GASTON_BASE)
    headers = {**_UA, "Referer": f"{_GASTON_BASE}/", "Accept": "application/json",
               "X-Requested-With": "XMLHttpRequest"}
    if csrf:
        headers["X-CSRF-TOKEN"] = csrf
    try:
        r = await http.post(f"{_GASTON_BASE}/api/v2/search",
                            json={"filters": {"term": addr}, "page": 1, "limit": 21},
                            headers=headers)
        d = r.json()
    except Exception:  # noqa: BLE001
        return None
    # Only a SINGLE exact match ({"id": pid}) is trustworthy — a `results` list
    # is the generic unfiltered page and would attach the wrong parcel's photo.
    pid = d.get("id") if isinstance(d, dict) else None
    if not pid:
        return None
    try:
        ri = await http.get(_GASTON_IMAGES, params={"id": pid, "json": "true"},
                            headers={**_UA, "Referer": f"{_GASTON_BASE}/"})
        urls = _json.loads(ri.text) if ri.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return None
    photo = pick_gaston_photo(urls if isinstance(urls, list) else [])
    if not photo:
        return None
    try:
        rp = await http.get(photo, headers={**_UA, "Referer": f"{_GASTON_BASE}/"})
    except Exception:  # noqa: BLE001
        return None
    return rp.content if rp.status_code == 200 and _is_img(rp.content) else None


async def _ncpts_record(http: httpx.AsyncClient, tenant: str, parcel: str) -> Optional[dict]:
    """Resolve a parcel to its land-record. Tries searchKey ParcelId (the account
    number) AND Pin (the 10-digit map PIN) — the Pin key is what unlocks the
    Rutherford/Burke board leads, which carry PINs, not account numbers."""
    for key in ("ParcelId", "Pin"):
        try:
            r = await http.post(f"{_NCPTS}/api/GetParcelDetailsByQueryParam",
                                headers={"X-Tenant": tenant,
                                         "Content-Type": "application/json",
                                         "Accept": "application/json"},
                                content=_json.dumps({"searchKey": key,
                                                     "searchValue": parcel}))
        except Exception:  # noqa: BLE001
            continue
        if r.status_code != 200 or r.text.strip() in ("", "null", "[]"):
            continue
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            continue
        d = j[0] if isinstance(j, list) and j else j
        if isinstance(d, dict) and d.get("id"):
            return d
    return None


async def _fetch_ncpts(http: httpx.AsyncClient, li: Listing) -> Optional[bytes]:
    tenant = _county_name(li)
    if tenant not in _NCPTS_TENANTS:
        return None
    parcel = (li.parcel_id or "").strip()
    if not parcel:
        return None
    rec = await _ncpts_record(http, tenant, parcel)
    if not rec:
        return None
    try:
        rd = await http.get(f"{_NCPTS}/api/getParcelDetails",
                            params={"ParcelId": rec["id"]},
                            headers={"X-Tenant": tenant, "Accept": "application/json"})
        if rd.status_code != 200 or not rd.text.strip():
            return None
        det = rd.json()
    except Exception:  # noqa: BLE001
        return None
    if isinstance(det, list):
        det = det[0] if det else None
    if not isinstance(det, dict):
        return None
    meta = det.get("imageMetadata") or {}
    parcel_pk = meta.get("parcelPk") or det.get("parcelPk")
    buildings = [b for b in (meta.get("buildingImageMetadata") or []) if b.get("hasPhoto")]
    if not parcel_pk or not buildings:
        return None
    try:
        rp = await http.get(f"{_NCPTS}/api/GetParcelImage",
                            params={"ImageType": "Photo", "ParcelId": parcel_pk,
                                    "BuildingPk": buildings[0].get("buildingPk")},
                            headers={"X-Tenant": tenant})
    except Exception:  # noqa: BLE001
        return None
    return rp.content if rp.status_code == 200 and _is_img(rp.content) else None


# (state, county) -> (adapter, source label). Auto-doubles as the eligibility set.
ADAPTERS: dict[tuple[str, str], tuple] = {
    ("NC", "Buncombe"): (_fetch_buncombe, "buncombe_assessor_photo"),
    ("NC", "Lincoln"): (_fetch_lincoln, "lincoln_assessor_photo"),
    ("NC", "Gaston"): (_fetch_gaston, "gaston_assessor_photo"),
    ("NC", "Rutherford"): (_fetch_ncpts, "ncpts_assessor_photo"),
    ("NC", "Burke"): (_fetch_ncpts, "ncpts_assessor_photo"),
    ("NC", "Madison"): (_fetch_ncpts, "ncpts_assessor_photo"),
    ("NC", "Henderson"): (_fetch_ncpts, "ncpts_assessor_photo"),
}


def _adapter_for(li: Listing):
    return ADAPTERS.get(((li.state or "").upper(), _county_name(li)))


def is_eligible(li: Listing) -> bool:
    """A lead worth spending a fetch on: a county we have a working adapter for,
    a parcel key, and no ground photo yet."""
    if _adapter_for(li) is None:
        return False
    if not (li.parcel_id or "").strip():
        return False
    return not _has_real_photo(li)


# Live-verified sample hit rates from the county matrix at the top of this file.
# These are EXPECTED YIELD per fetch, and they are what a run's slots get striped
# by — a bare _rank_key sort put every address-less lead first, and Lincoln holds
# most of those, so a 1000-lead run spent 68% of its budget on the 0.47-yield
# county and starved the 0.90-yield one that is ~70% of the eligible pool.
COUNTY_HIT_RATE: dict[tuple[str, str], float] = {
    ("NC", "Buncombe"): 0.90,    # 18/20 sample parcels
    ("NC", "Burke"): 0.70,       # 7/10
    ("NC", "Rutherford"): 0.50,  # 5/10
    ("NC", "Lincoln"): 0.47,     # 7/15 (misses are vacant land)
    ("NC", "Henderson"): 0.50,   # same NC PTS adapter as Rutherford/Burke
    ("NC", "Madison"): 0.50,     # same NC PTS adapter
    ("NC", "Gaston"): 0.40,      # unmeasured + needs an address -> conservative
}
_DEFAULT_HIT_RATE = 0.30


def county_hit_rate(li: Listing) -> float:
    return COUNTY_HIT_RATE.get(((li.state or "").upper(), _county_name(li)),
                               _DEFAULT_HIT_RATE)


def select_targets(listings: Iterable[Listing], cap: int) -> list[Listing]:
    """Pick the leads a capped run should spend its fetches on.

    Two-level: within a county, `_rank_key` order (address-less first, then
    distress tier/grade/score — the operator-value ordering). Across counties,
    weighted striping: a county's k-th best lead costs k / hit_rate, and the
    cheapest costs win. That hands each county a share of the run proportional
    to its expected yield instead of letting whichever county happens to hold
    the address-less leads monopolize the whole budget, while a county that runs
    out of eligible leads simply stops competing and its slots flow to the rest.

    This is the SINGLE enforcement point for the cap — the driver does not
    re-check it, because `targets` is already truncated here.
    """
    cap = max(0, cap)
    if cap <= 0:
        return []
    buckets: dict[tuple[str, str], list[Listing]] = {}
    for li in listings:
        if is_eligible(li):
            buckets.setdefault(((li.state or "").upper(), _county_name(li)), []).append(li)

    scored: list[tuple[float, tuple[str, str], int, Listing]] = []
    for key, leads in buckets.items():
        leads.sort(key=_rank_key, reverse=True)
        weight = max(COUNTY_HIT_RATE.get(key, _DEFAULT_HIT_RATE), 0.01)
        for i, li in enumerate(leads):
            scored.append(((i + 1) / weight, key, i, li))
    # (cost, county, within-county rank) — fully deterministic, never compares
    # Listing objects.
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return [li for _, _, _, li in scored[:cap]]


# ------------------------------------------------------------------ driver --
async def enrich_assessor_photo(listings: Iterable[Listing],
                                photos_dir: Optional[Path] = None,
                                cap: Optional[int] = None,
                                budget_s: Optional[float] = None) -> dict:
    stats = {"eligible": 0, "targets": 0, "fetched": 0, "cached": 0,
             "no_photo": 0, "errors": 0, "skipped_budget": 0, "bytes": 0,
             "by_county": {}}
    if not _enabled():
        return stats
    listings = list(listings)
    cap = _max_leads() if cap is None else cap
    budget = _budget_s() if budget_s is None else budget_s

    pdir = Path(photos_dir) if photos_dir else _DEFAULT_DIR
    pdir.mkdir(parents=True, exist_ok=True)

    stats["eligible"] = sum(1 for li in listings if is_eligible(li))
    targets = select_targets(listings, cap)
    stats["targets"] = len(targets)
    if not targets:
        return stats

    start = time.monotonic()
    deadline = start + budget
    sem = asyncio.Semaphore(_concurrency())

    def _bump(county: str, key: str) -> None:
        stats["by_county"].setdefault(county, {"fetched": 0, "cached": 0, "no_photo": 0})
        stats["by_county"][county][key] += 1

    async with client(timeout=45.0) as http:
        async def one(li: Listing) -> None:
            county = _county_name(li)
            try:
                parcel = (li.parcel_id or "").strip()
                fname = _slug(county, parcel)
                fpath = pdir / fname
                # Idempotent: a file already on disk (this run, a prior run, or
                # enrichment_lrcpwa_photo — same slug) is re-wired, never re-fetched.
                # It must sniff as a real image; a non-empty truncated/error file
                # falls through and gets re-fetched (and overwritten) instead.
                if _file_is_img(fpath):
                    _set_image(li, fname, "assessor_photo_cached")
                    stats["cached"] += 1
                    _bump(county, "cached")
                    return
                entry = _adapter_for(li)
                if entry is None:
                    return
                fetch, label = entry
                async with sem:
                    # The wall-clock budget is enforced HERE, after the semaphore
                    # and immediately before the only slow call. asyncio.gather
                    # builds every one() coroutine up front, so a deadline test
                    # placed before the first await runs at t~0 for ALL leads and
                    # can never fire — that was the no-op this replaces.
                    left = deadline - time.monotonic()
                    if left <= 0:
                        stats["skipped_budget"] += 1
                        return
                    # ...and the fetch itself is capped at the remaining budget,
                    # so an adapter that does several sequential requests against
                    # a slow county host (each up to the 45s client timeout) can
                    # not blow past the deadline while it is already in flight.
                    try:
                        raw = await asyncio.wait_for(fetch(http, li), timeout=left)
                    except (asyncio.TimeoutError, TimeoutError):
                        stats["skipped_budget"] += 1
                        return
                if not _is_img(raw):
                    stats["no_photo"] += 1
                    _bump(county, "no_photo")
                    return
                thumb = _thumbnail(raw)
                if not thumb:
                    stats["errors"] += 1
                    return
                fpath.write_bytes(thumb)
                _set_image(li, fname, label)
                stats["fetched"] += 1
                stats["bytes"] += len(thumb)
                _bump(county, "fetched")
            except Exception:  # noqa: BLE001 — one bad lead never kills the run
                stats["errors"] += 1
                log.debug("assessor_photo.lead_failed", county=county,
                          parcel=(li.parcel_id or "")[:32])

        await asyncio.gather(*(one(li) for li in targets), return_exceptions=True)

    log.info("assessor_photo.done", **{k: v for k, v in stats.items() if k != "by_county"})
    return stats


def enrich_assessor_photo_sync(listings: Iterable[Listing],
                               photos_dir: Optional[Path] = None,
                               cap: Optional[int] = None,
                               budget_s: Optional[float] = None) -> dict:
    """Sync entrypoint for the orchestrator / one-off scripts."""
    coro = enrich_assessor_photo(listings, photos_dir=photos_dir, cap=cap,
                                 budget_s=budget_s)
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
