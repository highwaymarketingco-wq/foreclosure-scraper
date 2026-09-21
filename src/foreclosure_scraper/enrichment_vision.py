"""Vision condition assessment.

For every listing with usable imagery, sends the photos to a vision LLM
(Anthropic Claude or Google Gemini) with a flipper-trained prompt and gets
back a structured condition assessment:
  - condition_tier: move_in_ready / cosmetic / major / gut
  - confidence: HIGH / MEDIUM / LOW
  - per-component observations (roof, exterior, windows, yard, structural)
  - rehab $/sqft range adjusted from photo evidence
  - red_flags + positive_signs lists
  - vision_summary: 2-3 sentence flipper assessment

Provider selection via env VISION_PROVIDER:
  - "anthropic" (default): Claude Sonnet 4.5, $0.01-0.03/listing,
    needs ANTHROPIC_API_KEY
  - "gemini": Gemini 2.0 Flash, FREE up to 1500 req/day or
    ~$0.0001/listing on paid tier, needs GEMINI_API_KEY (mint at
    https://aistudio.google.com/apikey)

Both providers produce the same output dict shape so downstream code
(comp matcher, dashboard popouts) is provider-agnostic.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import re
import time
from typing import Callable, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()


# Provider selection — default to Anthropic for backwards compat
VISION_PROVIDER = os.environ.get("VISION_PROVIDER", "anthropic").lower().strip()

# Anthropic settings
#
# 2026-08-07: switched the default from claude-sonnet-4-5-20250929 to Haiku
# 4.5. This is a grading task ("roof condition, boarded windows, overgrown
# lot, score 1-5"), and a small model does it as accurately as a large one at
# a fraction of the price. Measured on the live board: 9,326 eligible leads at
# ~1,600 input / ~400 output tokens each is ~$34 on Haiku 4.5 ($1/$5 per
# Mtok) versus ~$67-84 on Sonnet/Opus for the identical grades. Override with
# ANTHROPIC_VISION_MODEL if a specific run wants a different model.
ANTHROPIC_VISION_MODEL = os.environ.get("ANTHROPIC_VISION_MODEL", "claude-haiku-4-5")
# Legacy alias kept for any external imports
VISION_MODEL = ANTHROPIC_VISION_MODEL

# $/million tokens, input/output. Used only to enforce VISION_MAX_SPEND_USD
# below — not billed by this code, Anthropic bills the real usage. Keep in
# sync with the model actually in use; a stale price under-enforces the cap
# (spends more than intended) rather than over-enforcing it, so err toward
# looking the current price up if this drifts.
_ANTHROPIC_PRICE_PER_MTOK = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
}


class _SpendGuard:
    """Running-total $ stop for the Anthropic vision path ONLY.

    The free providers (Gemini/Groq/GitHub/OpenRouter/Mistral/Cloudflare/NVIDIA/
    Ollama) have no $ cost, so this guard is scoped to the one backend that
    does. It sits at the entry of _assess_one_anthropic rather than inside the
    worker-pool scheduler in enrich_with_vision: the pool already treats "this
    backend returned None" as a normal decline and re-queues the listing to a
    free backend, so refusing the call here needs no change to that pool logic
    at all — it is just one more reason a backend can say no.

    VISION_MAX_SPEND_USD unset or 0 = no limit (existing behavior).
    """

    def __init__(self) -> None:
        self.limit = float(os.environ.get("VISION_MAX_SPEND_USD", "0") or 0)
        self.spent = 0.0
        self._warned = False

    def over_budget(self) -> bool:
        return self.limit > 0 and self.spent >= self.limit

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        in_price, out_price = _ANTHROPIC_PRICE_PER_MTOK.get(
            model, _ANTHROPIC_PRICE_PER_MTOK["claude-haiku-4-5"])
        self.spent += (input_tokens / 1_000_000) * in_price
        self.spent += (output_tokens / 1_000_000) * out_price


_spend_guard = _SpendGuard()

# Gemini settings — Google zeroed out gemini-2.0-flash's free tier on
# 2026-05-12 (quota metric returns limit: 0 for new and existing keys),
# so the default is now gemini-2.5-flash which still has free quota
# (10 RPM / 250 RPD / 250K TPM per account). With 3-account rotation
# that's 750 RPD effective — enough for a 633-call weekly run + small
# patch reruns. If quota gets tight, override to gemini-2.5-flash-lite
# (15 RPM / 1000 RPD per account ≈ 3000 RPD across 3 keys, lower quality).
# Verified retired/404'ing names (do NOT use):
#   - gemini-2.0-flash      (free tier zeroed 2026-05-12)
#   - gemini-2.0-flash-exp  (deprecated 2025)
#   - gemini-1.5-flash      (deprecated 2026; v1beta removed it)
GEMINI_VISION_MODEL = os.environ.get(
    "GEMINI_VISION_MODEL", "gemini-2.5-flash"
)
# 2026-09-21: THE Gemini yield problem. Free-tier quota is PER PROJECT PER MODEL,
# and gemini-2.5-flash is capped at 20 requests/day per project (quotaId
# GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 20, measured live).
# Nine keys on that one model = ~180 calls/day at best, and the daily pass was
# scoring 63-76 of them. Every other model has its OWN bucket, so the pool now
# registers one lane per (key, model). Measured live 2026-09-21 with the
# production prompt on a real listing photo (see docs/vision_repair_2026-09-21.md
# for the full table); the per-minute limits below are from the 429 bodies.
#   gemini-3.5-flash-lite  15 RPM  ~1-4s   best lane (gemini-flash-lite-latest is an
#                                          ALIAS of it and shares the bucket: not registered)
#   gemini-2.5-flash-lite  10 RPM, 20 RPD  ~2-6s
#   gemini-3.1-flash-lite  15 RPM  slow and erratic (10-84s)
#   gemini-2.5-flash       10 RPM, 20 RPD
#   gemini-3-flash-preview  5 RPM  ~20s (best grader, tiny quota)
# Rejected: gemma-4-* answer with EMPTY text; gemini-3.5-flash / 3.6 / 3.7 / 3.8
# return 503 "high demand" or time out at 60s.
GEMINI_POOL_MODELS = [m.strip() for m in os.environ.get("GEMINI_VISION_MODELS", ",".join([
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
])).split(",") if m.strip()]
# Free-tier requests/minute per model, used only to pace each lane (delay =
# 60/rpm + 0.5s). A model not listed here is paced as 5 RPM (the strictest seen).
GEMINI_MODEL_RPM = {
    "gemini-3.5-flash-lite": 15, "gemini-3.1-flash-lite": 15,
    "gemini-2.5-flash-lite": 10, "gemini-2.5-flash": 10,
    "gemini-3-flash-preview": 5, "gemini-3.5-flash": 5,
}

MAX_PHOTOS_PER_LISTING = 7   # up to 5 real + aerial + street
MAX_REAL_PHOTOS = 5          # how many of the listing photos to send
# 4000 tokens: gemini-2.5-flash is wordier than 2.0-flash and 2000 was
# truncating the JSON mid-observation in ~17% of calls (parse_fail in
# run on 2026-05-13). 4000 covers the longest observed responses with
# room to spare. Still well inside the 250K TPM free-tier cap.
MAX_TOKENS = 4000
# Free-tier-safe defaults: 1 in-flight + 6s delay = 10 RPM. Override
# both via env when on a paid tier with higher limits.
CONCURRENCY = int(os.environ.get("VISION_CONCURRENCY", "1"))
INTER_CALL_DELAY = float(os.environ.get("VISION_INTER_CALL_DELAY", "6.0"))

# ---------------------------------------------------------------------------
# Run budget + per-call timeouts (2026-09-21 vision repair)
# ---------------------------------------------------------------------------
# The daily pass used to hold the board lock for 4 hours to score 371-759 leads
# (2026-09-21 ops audit, finding O6), and every one of its ReadTimeouts
# burned 90 seconds. The wall-clock default is now 90 minutes and a single
# provider call is cut off at 60 seconds. All three are env-tunable.
VISION_MAX_SECONDS_DEFAULT = 5400.0        # 90 minutes


def vision_max_seconds() -> float:
    """Wall-clock budget for one vision pass, in seconds.

    VISION_MAX_SECONDS unset or blank -> 5400 (90 min).
    VISION_MAX_SECONDS=0              -> unlimited (explicit opt-out; the test
                                         suite and one-off backfills use this).
    Anything unparseable falls back to the default rather than to unlimited.
    """
    raw = (os.environ.get("VISION_MAX_SECONDS") or "").strip()
    if not raw:
        return VISION_MAX_SECONDS_DEFAULT
    try:
        return max(0.0, float(raw))
    except ValueError:
        return VISION_MAX_SECONDS_DEFAULT


def _start_stagger() -> float:
    """Seconds between the opening calls of consecutive lanes/workers, so a pool of
    nine keys x five models does not fire 45 requests in the same second (rate-limit
    windows are per model per project, and the first burst is where the 429 storm
    starts). VISION_START_STAGGER_S=0 disables."""
    try:
        return max(0.0, float(os.environ.get("VISION_START_STAGGER_S", "1.5")))
    except ValueError:
        return 1.5


def _call_timeout() -> float:
    """Per provider-call HTTP timeout. Healthy lanes measured live on 2026-09-21
    answered in 1-40s; the 90s this replaced only bought idle waits (30 of the
    day's ising calls timed out and each held its worker for the full 90s)."""
    try:
        return max(5.0, float(os.environ.get("VISION_CALL_TIMEOUT", "60")))
    except ValueError:
        return 60.0



def _exc_label(exc: BaseException, limit: int) -> str:
    """Log the exception TYPE alongside its message.

    `str(exc)[:160]` alone produced 143 log lines reading `error=` — completely
    empty — during the 2026-09-13 daily pass, because several client libraries
    raise exceptions whose __str__ is blank (bare `APIError()`, timeouts, cancelled
    tasks). An error line that names no error cannot be acted on, and a 76% miss
    rate that reports nothing looks like the backend is simply slow instead of
    failing. The type name is always present, so it always says something.
    """
    msg = str(exc).strip()
    name = type(exc).__name__
    return f"{name}: {msg[:limit]}" if msg else name

SYSTEM_PROMPT = """You are an experienced real-estate flipper assessing renovation needs from listing photos and aerial views. You make accurate cost-aware judgments grounded in what the photos actually show, not optimistic guesses.

Rehab tiers (Carolina market, 2026 dollars):
- move_in_ready: $5-20/sqft. Minor paint/carpet/cleaning at most. Property looks ready to occupy.
- cosmetic: $15-45/sqft. Paint, flooring, minor kitchen/bath updates, light landscaping. No major systems work.
- major: $35-80/sqft. Significant interior rehab + some systems work (HVAC, roof patching, plumbing fixtures). Cosmetic done top-to-bottom.
- gut: $110-220/sqft. Down to studs, full systems replacement, foundation/roof/structural work, possible additions. Property is uninhabitable as-is.

When the only photo is a basemap or generic Realtor placeholder (no actual property visible), set the JSON value of condition_tier to null (the literal null, not the text) and confidence to "LOW".

CRITICAL — AERIAL-ONLY LISTINGS: When only aerial/satellite imagery is available (no listing photos or street views), do NOT assume the property is vacant land. Aerial views of wooded or overgrown lots frequently contain a house obscured by tree canopy. Use the property_kind field: if it indicates a structure (SINGLE_FAMILY, MULTI_FAMILY, TOWNHOUSE, CONDO, etc.), a building exists even if the aerial doesn't clearly show it. In that case:
- Assess what you CAN see from the aerial: roof shape/condition, lot condition, surrounding neighborhood quality, driveway/parking.
- Set confidence to "LOW" since you cannot see the structure's actual condition.
- Do NOT classify as "gut" based solely on an overgrown aerial appearance — that is tree cover, not structural distress.
- A "cosmetic" or "major" tier with LOW confidence is appropriate when you can see a roof but not the walls/interior.

Output ONLY valid JSON, no markdown fences, no preamble."""


def _user_prompt(li: Listing) -> str:
    parts = [
        f"PROPERTY: {li.street_address or '(no address)'}, {li.city or ''}, {li.state or ''} {li.zip_code or ''}".strip(),
        f"County: {li.county or '?'}",
        f"Property kind: {li.property_kind.value if li.property_kind else 'unknown'}",
    ]
    if li.year_built:
        parts.append(f"Year built: {li.year_built}")
    if li.living_sqft:
        parts.append(f"Living sqft: {li.living_sqft:,.0f}")
    if li.bedrooms or li.bathrooms:
        parts.append(f"Beds/baths: {li.bedrooms}/{li.bathrooms}")
    if li.opening_bid:
        parts.append(f"Asking/bid: ${li.opening_bid:,.0f}")
    if li.description:
        d = li.description[:300]
        parts.append(f"Listing text: {d}")

    # Detect imagery mode so the LLM knows what it's looking at.
    raw = li.raw if isinstance(li.raw, dict) else {}
    images = raw.get("images") or {}
    has_real = bool(images.get("real"))
    has_street = bool(images.get("street"))
    has_aerial = bool(images.get("aerial"))
    if not has_real and not has_street and has_aerial:
        parts.append("")
        parts.append(
            "NOTE: Only aerial/satellite imagery is available for this property — "
            "no street-level or interior photos. If the property_kind indicates a "
            "structure (house, townhouse, condo, etc.), a building exists on this "
            "lot even if tree canopy obscures it in the aerial view. Do NOT mistake "
            "tree cover or overgrown vegetation for a distressed or vacant-land "
            "property. Grade the roof and lot from what you CAN see, set confidence "
            "to LOW, and avoid 'gut' unless you see clear structural collapse."
        )

    parts.append("")
    parts.append("Look at the attached photos and aerial views. Return JSON ONLY:")
    parts.append("""{
  "condition_tier": "move_in_ready" | "cosmetic" | "major" | "gut" | null,
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "observations": {
    "roof": "<what you see — shape, age signs, missing shingles, visible damage>",
    "exterior_walls": "<siding condition, paint, visible damage>",
    "windows_doors": "<intact, broken, boarded, replacement age>",
    "yard_landscaping": "<maintained, overgrown, debris, fencing>",
    "structural_signs": "<any visible foundation, sagging, lean, cracking>",
    "interior_visible": "<if any interior shots: floors, walls, kitchen/bath condition>"
  },
  "rehab_psf_low": <int>,
  "rehab_psf_high": <int>,
  "red_flags": [<concise items, e.g. "boarded windows", "missing roof shingles">],
  "positive_signs": [<concise items, e.g. "recently painted exterior", "new roof">],
  "vision_summary": "<2-3 sentences: experienced flipper's quick read on this property>"
}""")
    return "\n".join(parts)


async def _fetch_image_bytes(c: httpx.AsyncClient, url: str) -> Optional[tuple[bytes, str]]:
    """Download image; return (bytes, media_type). Returns None on failure."""
    try:
        r = await c.get(url, timeout=15.0, follow_redirects=True)
        if r.status_code != 200:
            return None
        media_type = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not media_type.startswith("image/"):
            media_type = "image/jpeg"
        # Cap at ~3 MB (Anthropic limit)
        data = r.content[:3 * 1024 * 1024]
        # Normalize WebP/other formats to JPEG. Some backends (e.g. NVIDIA
        # nemotron-nano-vl-8b) 500 with "cannot identify image file" on WebP,
        # and rdcpix/Realtor + Zillow serve WebP heavily. PIL reads WebP fine;
        # re-encoding to JPEG makes every backend able to decode it. JPEG/PNG
        # pass through untouched.
        if media_type not in ("image/jpeg", "image/png"):
            try:
                import io as _io
                from PIL import Image as _Image
                im = _Image.open(_io.BytesIO(data)).convert("RGB")
                out = _io.BytesIO()
                im.save(out, "JPEG", quality=85)
                data, media_type = out.getvalue(), "image/jpeg"
            except Exception:
                pass  # unreadable here — leave as-is; a backend that can read it still will
        return data, media_type
    except Exception:
        return None


def _has_real_image(li: Listing) -> bool:
    """True when this lead has an image vision can actually grade.

    The OSM basemap does not count: _select_image_urls appends it only as a last
    resort and the model is instructed to return a null condition_tier for it, so
    grading a basemap-only lead spends quota and produces nothing.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    images = raw.get("images") or {}
    if not isinstance(images, dict):
        return False
    if images.get("real") or images.get("street") or images.get("aerial"):
        return True
    z = raw.get("zillow") or {}
    return bool(isinstance(z, dict) and (z.get("photos") or z.get("photo")))


def _select_image_urls(li: Listing) -> list[str]:
    """Pick up to MAX_PHOTOS_PER_LISTING image URLs to send to Vision.

    Priority: real photos > street view > aerial. Skips OSM basemap.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    images = raw.get("images") or {}
    urls: list[str] = []
    real = images.get("real") or []
    if isinstance(real, list):
        urls.extend([u for u in real[:MAX_REAL_PHOTOS] if u])
    elif isinstance(real, str) and real:
        urls.append(real)
    # Legacy fallback: pull from raw.zillow.photo(s) if images.real not set yet
    if not urls:
        zillow = raw.get("zillow") or {}
        z_photos = zillow.get("photos") or []
        if isinstance(z_photos, list) and z_photos:
            urls.extend([u for u in z_photos[:MAX_REAL_PHOTOS] if u])
        elif zillow.get("photo"):
            urls.append(zillow["photo"])
    if len(urls) < MAX_PHOTOS_PER_LISTING and images.get("street"):
        urls.append(images["street"])
    if len(urls) < MAX_PHOTOS_PER_LISTING and images.get("aerial"):
        urls.append(images["aerial"])
    # Skip if only the OSM basemap is present (not useful for vision)
    if len(urls) < MAX_PHOTOS_PER_LISTING and not urls and images.get("map"):
        urls.append(images["map"])  # last-resort, vision will return null/LOW
    # Dedupe + cap
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= MAX_PHOTOS_PER_LISTING:
            break
    return out


def _parse_json_response(text: str) -> Optional[dict]:
    """Anthropic models sometimes wrap JSON in fences. Strip + parse.

    Found 2026-09-16: a multi-entry document (e.g. a county's whole monthly
    tax-sale LIST as one PDF, prompted as if it were "ONE document") can make
    the model return a JSON ARRAY of entries instead of the single object
    every caller assumes -- json.loads() happily returns that list despite
    this function's declared -> Optional[dict], and every caller then crashes
    with "list indices must be integers or slices, not str" the moment it
    does parsed["field"] or parsed["_source"] = .... Live-reproduced against
    two Pickens County SC multi-listing sale-list PDFs. Deliberately return
    None rather than guess and take parsed[0]: a list response means we don't
    know which entry belongs to THIS lead, and writing the wrong entry's
    owner/address/amount onto it is worse than writing nothing -- the same
    reasoning this codebase applies everywhere else a match could be wrong
    (the TAX_SALE_OVERAGE guard, the ambiguous-envelope rejection in parcel
    resolution, etc.). Multi-entry documents already have a purpose-built
    path (_row_backfill_from_aggregate) that matches per lead by name/address
    search instead of guessing an index.
    """
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        # Try to find first {...} block
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
    return None


async def _fetch_image_blocks(
    li: Listing, http: httpx.AsyncClient
) -> tuple[list[tuple[bytes, str]], list[str]]:
    """Download up to MAX_PHOTOS_PER_LISTING images for a listing in parallel.
    Returns (image_payloads, urls) where each payload is (bytes, media_type).
    Provider-neutral; both Anthropic + Gemini share this download path.
    """
    urls = _select_image_urls(li)
    if not urls:
        return [], []
    fetches = await asyncio.gather(*(_fetch_image_bytes(http, u) for u in urls))
    payloads = [f for f in fetches if f]
    return payloads, urls


async def _assess_one_anthropic(
    client, li: Listing, http: httpx.AsyncClient
) -> Optional[dict]:
    """Run Claude Vision on one listing. Returns the parsed JSON or None."""
    if _spend_guard.over_budget():
        # Declines exactly like any other exhausted backend: the pool re-queues
        # this listing to a free backend rather than dropping it, so hitting
        # the $ cap degrades to "finish the rest for free" instead of stopping
        # the run.
        if not _spend_guard._warned:
            log.info("vision.anthropic_budget_reached",
                     spent_usd=round(_spend_guard.spent, 2),
                     limit_usd=_spend_guard.limit)
            _spend_guard._warned = True
        return None
    payloads, urls = await _fetch_image_blocks(li, http)
    if not payloads:
        return None

    image_blocks = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(data).decode("ascii"),
            },
        }
        for data, media_type in payloads
    ]

    user_text = _user_prompt(li)
    content = image_blocks + [{"type": "text", "text": user_text}]

    try:
        resp = await client.messages.create(
            model=ANTHROPIC_VISION_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        log.warning("vision.api_error", provider="anthropic", source_url=li.source_url, error=_exc_label(exc, 200))
        return None

    text_chunks = [b.text for b in resp.content if hasattr(b, "text")]
    raw_text = "\n".join(text_chunks).strip()
    parsed = _parse_json_response(raw_text)
    if not parsed:
        log.debug("vision.parse_fail", provider="anthropic", text=raw_text[:200])
        return None

    usage = getattr(resp, "usage", None)
    if usage:
        in_tok = getattr(usage, "input_tokens", None) or 0
        out_tok = getattr(usage, "output_tokens", None) or 0
        parsed["_usage"] = {"input_tokens": in_tok, "output_tokens": out_tok}
        _spend_guard.record(ANTHROPIC_VISION_MODEL, in_tok, out_tok)
    parsed["_provider"] = "anthropic"
    parsed["_model"] = ANTHROPIC_VISION_MODEL
    parsed["_n_photos"] = len(image_blocks)
    parsed["_image_urls"] = urls
    return parsed


# Backwards-compat alias: pre-existing call sites use _assess_one.
_assess_one = _assess_one_anthropic


async def _assess_one_gemini(
    client, li: Listing, http: httpx.AsyncClient
) -> Optional[dict]:
    """Run Gemini Vision on one listing. Returns the parsed JSON or None.

    Same input/output contract as _assess_one_anthropic so the rest of the
    pipeline (raw["vision"], raw["condition_tier"]) is provider-agnostic.
    Uses the new google-genai SDK (`from google import genai`).
    """
    payloads, urls = await _fetch_image_blocks(li, http)
    if not payloads:
        return None

    from google.genai import types as genai_types

    image_parts = [
        genai_types.Part.from_bytes(data=data, mime_type=media_type)
        for data, media_type in payloads
    ]
    user_text = _user_prompt(li)
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_text}"
    contents = image_parts + [full_prompt]

    try:
        resp = await client.aio.models.generate_content(
            model=GEMINI_VISION_MODEL,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=MAX_TOKENS,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:
        log.warning("vision.api_error", provider="gemini", source_url=li.source_url, error=_exc_label(exc, 200))
        return None

    raw_text = ""
    try:
        raw_text = (resp.text or "").strip()
    except Exception:
        try:
            for cand in getattr(resp, "candidates", []) or []:
                parts = getattr(getattr(cand, "content", None), "parts", []) or []
                for p in parts:
                    t = getattr(p, "text", None)
                    if t:
                        raw_text += t
        except Exception:
            raw_text = ""
    if not raw_text:
        return None
    parsed = _parse_json_response(raw_text)
    if not parsed:
        log.debug("vision.parse_fail", provider="gemini", text=raw_text[:200])
        return None

    usage = getattr(resp, "usage_metadata", None)
    if usage:
        parsed["_usage"] = {
            "input_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
        }
    parsed["_provider"] = "gemini"
    parsed["_model"] = GEMINI_VISION_MODEL
    parsed["_n_photos"] = len(image_parts)
    parsed["_image_urls"] = urls
    return parsed


def _build_anthropic_client():
    """Set up Anthropic client. Returns (client, assess_fn) or (None, None)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("vision.no_api_key", provider="anthropic", hint="set ANTHROPIC_API_KEY to enable")
        return None, None
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        log.warning("vision.sdk_missing", provider="anthropic", hint="pip install anthropic")
        return None, None
    client = AsyncAnthropic(api_key=api_key, max_retries=6, timeout=90.0)
    return client, _assess_one_anthropic


def _parse_gemini_keys() -> list[str]:
    """Collect every Gemini API key available, in order to try them.

    Supports two env-var styles for multi-account quota rotation:
      - GEMINI_API_KEY: a single key OR a comma-separated list
        (e.g. "key1,key2,key3"). Whitespace stripped per key.
      - GEMINI_API_KEY_1, GEMINI_API_KEY_2, ... GEMINI_API_KEY_10 :
        numbered env vars. Gaps are skipped so callers can leave _1
        empty and set _2/_3 only (matches the workflow yaml pattern).

    Empty/None values are dropped. Duplicates preserved (caller decides).
    """
    keys: list[str] = []
    primary = os.environ.get("GEMINI_API_KEY") or ""
    for part in primary.split(","):
        k = part.strip()
        if k:
            keys.append(k)
    for i in range(1, 61):
        v = (os.environ.get(f"GEMINI_API_KEY_{i}") or "").strip()
        if v and v not in keys:
            keys.append(v)
    return keys


class GeminiRotatingClient:
    """Wraps multiple Gemini API keys, rotating to the next key when
    one returns 429 RESOURCE_EXHAUSTED. Each key has its own daily
    free-tier quota (1500 RPD on gemini-2.0-flash), so 4 keys = 6000
    RPD effective ceiling at $0 cost.

    Behavior:
      - Starts on key[0]. Builds a lazy client per key on first use.
      - On 429 from generate_content, marks the current key 'exhausted',
        switches to next available key, retries the request once.
      - When ALL keys are exhausted, returns None (assess_fn handles it
        like a normal API error).
      - Exhausted state is in-process only — doesn't persist across runs.
        That's fine; each daily run gets a fresh quota for each key.
    """

    def __init__(self, keys: list[str]):
        from google import genai
        self._genai = genai
        self._keys = list(keys)
        self._exhausted: set[int] = set()
        self._clients: dict[int, object] = {}
        self._idx = 0

    @property
    def num_keys(self) -> int:
        return len(self._keys)

    def _current_client(self):
        """Return the client for the current key idx, building if needed."""
        if self._idx not in self._clients:
            self._clients[self._idx] = self._genai.Client(api_key=self._keys[self._idx])
        return self._clients[self._idx]

    def _rotate(self) -> bool:
        """Mark current key exhausted, advance to next non-exhausted.
        Returns True if a fresh key is available, False if all spent."""
        self._exhausted.add(self._idx)
        for offset in range(1, self.num_keys + 1):
            candidate = (self._idx + offset) % self.num_keys
            if candidate not in self._exhausted:
                self._idx = candidate
                log.info(
                    "vision.gemini.rotated_key",
                    new_idx=self._idx,
                    exhausted_count=len(self._exhausted),
                    total_keys=self.num_keys,
                )
                return True
        return False

    # The .aio.models.generate_content path is what _assess_one_gemini
    # uses. We expose a compatible attribute chain so the call site
    # doesn't need to know we're rotating: client.aio.models.generate_content(...)

    class _ModelsProxy:
        def __init__(self, parent: "GeminiRotatingClient"):
            self._parent = parent

        async def generate_content(self, **kwargs):
            # Try up to num_keys times: each 429 rotates + retries.
            tries = 0
            last_exc: Optional[Exception] = None
            while tries < self._parent.num_keys:
                tries += 1
                client = self._parent._current_client()
                try:
                    return await client.aio.models.generate_content(**kwargs)
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc).lower()
                    # 429 / quota / resource_exhausted → rotate, retry
                    is_quota = (
                        "429" in msg
                        or "resource_exhausted" in msg
                        or "quota" in msg
                        or "exceeded" in msg
                    )
                    if not is_quota:
                        # Some other API error — don't burn through keys
                        raise
                    rotated = self._parent._rotate()
                    if not rotated:
                        log.warning(
                            "vision.gemini.all_keys_exhausted",
                            keys=self._parent.num_keys,
                        )
                        raise
            # Should not reach — defensive
            if last_exc:
                raise last_exc

    class _AioProxy:
        def __init__(self, parent: "GeminiRotatingClient"):
            self.models = GeminiRotatingClient._ModelsProxy(parent)

    @property
    def aio(self):
        # Build lazily so attribute access doesn't fail if construction
        # somehow happens with 0 keys.
        return GeminiRotatingClient._AioProxy(self)


def _build_gemini_client():
    """Set up Gemini client. Returns (client, assess_fn) or (None, None).

    Supports multi-key rotation: when GEMINI_API_KEY is comma-separated
    (or numbered GEMINI_API_KEY_N env vars are set), the returned client
    rotates between keys on 429. Each Gemini account has its own daily
    free-tier quota (1500 RPD on gemini-2.0-flash), so 4 keys yield
    ~6000 RPD effective cap at $0.
    """
    keys = _parse_gemini_keys()
    if not keys:
        log.warning("vision.no_api_key", provider="gemini", hint="set GEMINI_API_KEY (mint at https://aistudio.google.com/apikey) — single key, comma-separated list, or numbered GEMINI_API_KEY_1/2/3")
        return None, None
    try:
        from google import genai  # noqa: F401
    except ImportError:
        log.warning("vision.sdk_missing", provider="gemini", hint="pip install google-genai")
        return None, None
    if len(keys) == 1:
        # Fast path — single key, plain client, no rotation overhead.
        from google import genai
        client = genai.Client(api_key=keys[0])
        log.info("vision.gemini.client_built", keys=1, rotation=False)
        return client, _assess_one_gemini
    # Multi-key rotation
    client = GeminiRotatingClient(keys)
    log.info("vision.gemini.client_built", keys=len(keys), rotation=True)
    return client, _assess_one_gemini


# ---------------------------------------------------------------------------
# Multi-provider backend pool
# ---------------------------------------------------------------------------
# Each FREE source (one per Gemini *project*, GitHub Models, Groq, local
# Ollama) is a "backend". enrich_with_vision pools them: all backends pull
# from ONE shared work queue, so a backend that hits its daily quota (429)
# just drops out and the others keep draining the remaining listings — no
# key's share is wasted. Ollama (local, unlimited) never drops out, so it's
# the floor that finishes whatever the API pools couldn't.

# GitHub Models — free tier, uses the existing `gh` token (or GITHUB_MODELS_TOKEN).
GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_MODELS_MODEL = os.environ.get("GITHUB_MODELS_MODEL", "openai/gpt-4o-mini")
# Verified 2026-07-27 on 4 real property photos (4 trials each). GitHub Models
# rate-limits per model TIER, so each id is its own lane rather than sharing one
# bucket. Ordered best-grading first; several return a PERFECT 4-distinct tier
# ordering across the 4 photos, which is better discrimination than most NIM lanes.
GITHUB_VISION_MODELS = [m.strip() for m in os.environ.get("GITHUB_VISION_MODELS", ",".join([
    "openai/gpt-4o",                                   # 4/4, perfect ordering (high tier)
    "meta/llama-4-maverick-17b-128e-instruct-fp8",     # 4/4, perfect ordering, 4.1s
    "mistral-ai/mistral-small-2503",                   # 4/4, perfect ordering, 3.2s, LOW tier
                                                       # = best quota-per-quality here
    "openai/gpt-4.1",                                  # 4/4 (high tier)
    "openai/gpt-4o-mini",                              # 4/4 across three runs (low tier)
    "openai/gpt-4.1-mini",                             # 4/4 (low tier)
    "meta/llama-4-scout-17b-16e-instruct",             # 4/4 on retest
    "mistral-ai/mistral-medium-2505",                  # 4/4 (low tier)
])).split(",") if m.strip()]
# Rejected: openai/gpt-4.1-nano answered move_in_ready for 3 of 4 including a
# cluttered doublewide — non-null but confidently wrong. Paid-gated (never called):
# gpt-5 family, o1/o3/o4-mini.
# Groq — free tier, very fast. Vision model names change; override via env.
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Verified live 2026-07-27 against GET /openai/v1/models: llama-4-scout is GONE
# (404 "does not exist or you do not have access"), and qwen3.6-27b is now the
# ONLY catalog entry with "image" in input_modalities. It is a reasoning model:
# left alone it burns the whole token budget on a <think> block and never emits
# JSON, and response_format=json_object 400s (json_validate_failed). It only
# returns a parseable condition JSON with reasoning_effort="none" — hence
# GROQ_EXTRA_BODY below. Free-tier TPM is 8k and one prompt+photo is ~5.4k, so
# roughly one call/minute; the delay is paced to match.
#
# Re-verified live 2026-09-16: qwen3.6-27b is ALSO gone (404) -- Groq renamed
# it to qwen/qwen3.8-27b (confirmed live against GET /openai/v1/models: it is
# now the only "image"-capable entry, active=true). Live-tested with a real
# call. That test also surfaced a second, independent issue: a bare call with
# no max_tokens defaulted to requesting ~1019 output tokens and got a 429
# ("output tokens per minute (OTPM): Limit 1000") -- this account's Groq org
# has a 1000 OTPM cap distinct from the 8k *input* TPM this comment already
# paces for. The shared MAX_TOKENS=4000 every other backend uses blows through
# it on every call. max_tokens=900 in GROQ_EXTRA_BODY below overrides it via
# _OpenAICompatBackend's `body.update(self.extra_body)` (extra_body is merged
# in AFTER the max_tokens=MAX_TOKENS default, so this only affects Groq) --
# confirmed live: max_tokens=200 returned 200 OK with valid JSON.
GROQ_MODEL = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
GROQ_EXTRA_BODY = {"reasoning_effort": "none", "max_tokens": 900}
# Ollama — local, unlimited, free. qwen2.5vl:3b > moondream and still fits 8GB.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")
# OpenRouter — free tier routes to ~30 models incl. free vision ones, one key.
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_VISION_MODEL", "meta-llama/llama-3.2-11b-vision-instruct:free")
# Mistral — free "Experiment" tier: ~1B tokens/month, no card (2 RPM). Pixtral
# is deprecated; the current maintained vision model is mistral-small-latest.
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL = os.environ.get("MISTRAL_VISION_MODEL", "mistral-medium-latest")
# Verified 2026-07-27. Mistral rate-limits PER CANONICAL MODEL (confirmed live from
# x-ratelimit-limit-req-minute headers), so each of these is a genuinely separate
# free lane — this is the largest free capacity found anywhere in the sweep.
#   ministral-3b   750 RPM / 1.3M TPM   <- highest capacity of ANY provider tested
#   ministral-8b   188 RPM / 625k TPM
#   mistral-medium  50 RPM /  25k TPM   <- best QUALITY (only Mistral model with a
#                                          perfect 4-distinct tier ordering)
#   mistral-large    4 RPM / 250k TPM
# CAUTION: mistral-small-latest / magistral-small-latest / mistral-vibe-cli-fast /
# mistral-small-2603 are ALIASES sharing ONE 50 RPM bucket (proved live: calls to one
# decremented the others' remaining count). They are one lane, not four — and
# mistral-small-latest (the OLD default here) graded a brand-new 2021 build as
# "cosmetic", so quality was poor too. Hence the default moved to mistral-medium.
MISTRAL_VISION_MODELS = [m.strip() for m in os.environ.get("MISTRAL_VISION_MODELS", ",".join([
    "mistral-medium-latest",   # best quality
    "ministral-8b-latest",     # 4/4 twice, 188 RPM
    "ministral-3b-latest",     # 3/4 twice, 750 RPM — the capacity workhorse
    "mistral-large-latest",    # 4/4 but only 4 RPM, so it sits at the back
])).split(",") if m.strip()]
# Excluded: ministral-14b (4/4 non-null but answered "major" for 3 of 4 incl. a
# well-maintained ranch); magistral-medium (returns list-shaped content that crashes
# the current parser, 5 RPM, deprecating); mistral-small-2506 (great grader, 300 RPM,
# but DEPRECATES 2026-07-31 — days away, so not worth wiring).
# Cloudflare Workers AI — 10k neurons/day free; needs account id + token.
# mistral-small-3.1-24b has strong vision and (unlike Llama-3.2-vision) needs
# NO one-time license-agreement click, so it works on a fresh token immediately.
CLOUDFLARE_MODEL = os.environ.get("CLOUDFLARE_VISION_MODEL", "@cf/mistralai/mistral-small-3.1-24b-instruct")

# NVIDIA NIM — OpenAI-compatible. ONE free key reaches MANY hosted vision models,
# and NIM rate-limits PER MODEL (~40 RPM each), so registering N vision models =
# N parallel free lanes in the pool (8 lanes here ≈ 320 RPM of free headroom).
#
# REFRESHED 2026-07-27. The previous list was written 2026-06-19 and 7 of its 13
# entries had since been retired — llama-4-maverick, mistral-small-4-119b,
# mistral-large-3-675b, ministral-14b, qwen3.5-397b, gemma-3n-e4b/e2b all
# answered HTTP 410 "has reached its end of life" and no longer appear in
# GET /v1/models at all. Those dead lanes are what ate the vision queue.
#
# Every model below was verified with a REAL single-image call on 2026-07-27:
# the actual production prompt + a real rdcpix listing photo (webp normalized to
# JPEG by _fetch_image_bytes, same as production), and only counted as working
# if _parse_json_response returned a dict containing condition_tier.
#
# Probed and REJECTED, do not re-add without re-probing:
#   404 "Function ... not found for account" (listed but not deployed to this
#       key): google/gemma-3-12b-it, google/gemma-3-4b-it,
#       microsoft/phi-3-vision-128k-instruct, moonshotai/kimi-k2.6,
#       nvidia/cosmos-reason2-8b, nvidia/vila, nvidia/neva-22b,
#       microsoft/kosmos-2, adept/fuyu-8b, google/deplot
#   500 "multimodal processing is not enabled": nvidia/nemotron-3-ultra-550b-a55b,
#       nvidia/nemotron-3-super-120b-a12b
#   400 not multimodal: mistralai/mistral-nemotron
#   400 no text input: nvidia/nemotron-parse
#   claims it cannot see the image: z-ai/glm-5.2
#   read timeout on the full prompt (180s and 300s, twice): google/gemma-4-31b-it,
#       deepseek-ai/deepseek-v4-flash, deepseek-ai/deepseek-v4-pro
#   "DEGRADED function cannot be invoked": stepfun-ai/step-3.7-flash
# Override via NVIDIA_VISION_MODELS.
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# RE-VERIFIED 2026-07-27 with the STRICT bar: 4 real property photos from the
# board, production SYSTEM_PROMPT + parser, and a model only counts if it returns
# a REAL non-null condition_tier on >=3 of 4. "Responds with JSON" is NOT enough —
# see the blindness note below.
NVIDIA_VISION_MODELS = [m.strip() for m in os.environ.get("NVIDIA_VISION_MODELS", ",".join([
    # RE-VERIFIED 2026-09-21 with the production prompt + parser on two real listing
    # photos through this module's own _OpenAICompatBackend (and 6 simultaneous calls
    # per lane: all answered, no 429). Only lanes that returned a REAL tier are kept.
    "nvidia/ising-calibration-1.5-31b",   # 2/2 real tiers (move_in_ready, major), 9-18s.
                                          # The lane that carried 340-426 of every day's scores.
    "google/gemma-4-31b-it",              # NEW: 2/2 real tiers (cosmetic, major), 10-16s.
                                          # Was a 180s read-timeout on 2026-07-27; healthy now.
    "meta/muse-glimmer-30b",              # NEW: 2/2 tiers but both "cosmetic" (weak spread),
                                          # 13-32s. Back of the rotation.
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",  # good grader, but the host intermittently
                                          # answers 503 "Worker local total request limit reached
                                          # (16/16)"; the circuit breaker rides that out.
])).split(",") if m.strip()]
# Concurrent workers per NIM lane. NIM is ~40 RPM per model and answers in 7-30s, so a
# single sequential worker used a fifth of the lane. 6 simultaneous calls per lane all
# answered on 2026-09-21; 3 leaves headroom. Override: VISION_NIM_WORKERS.
NVIDIA_DEFAULT_WORKERS = max(1, int(os.environ.get("VISION_NIM_WORKERS", "3")))
NVIDIA_LANE_WORKERS: dict[str, int] = {
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": 1,
    "meta/muse-glimmer-30b": 2,
}
# REMOVED 2026-09-21 (HTTP 410 "has reached its end of life" or gone from GET /v1/models):
#   nvidia/nemotron-nano-12b-v2-vl (EOL 2026-08-26), thinkingmachines/inkling (EOL
#   2026-08-25), nvidia/llama-3.1-nemotron-nano-vl-8b-v1 (EOL 2026-08-26).
# REMOVED 2026-09-21 (read timeouts at 60-93s on a single-photo call): meta/llama-3.2-90b-
#   vision-instruct, moonshotai/kimi-k3, z-ai/glm-5.3-flash. llama-3.2-11b-vision answers
#   but returns a null tier. Not multimodal on this host (400/500 "multimodal processing is
#   not enabled"): nvidia/nemotron-3.5-lightning-30b-a3b, poolside/laguna-xs-2.1, z-ai/glm-5.3.
#   404 "Not found for account" (not entitled): kimi-k2.6, gemma-3-12b-it, cosmos-reason2-8b,
#   nemotron-nano-3-30b-a3b.
# DROPPED 2026-07-27, do NOT re-add without re-probing:
#   mistralai/mistral-medium-3.5-128b — DEAD: 4/4 read timeouts even at 300s (it also
#     timed out on a 96x96 image). It was configured and silently contributed nothing.
#   meta/llama-3.2-11b-vision-instruct — 1/4 real tiers, worst configured performer.
#   minimaxai/minimax-m3 — 2/4. It genuinely SEES the photo but then returns null because
#     it judges a street view not to be a "real listing photo". Prompt-interpretation
#     failure, so a prompt tweak could recover it — until then it just burns a slot.
#   google/diffusiongemma-26b-a4b-it — 2/4, and one trial took 101.8s (over the 90s timeout).
#
# BLIND-BUT-CONFIDENT — these return HTTP 200 with perfectly parseable JSON while not
# seeing the image at all, which is the single most dangerous failure mode here (a
# confident tier on an unseen photo silently corrupts condition -> rehab -> ARV):
#   openai/gpt-oss-120b, openai/gpt-oss-20b ("there's no image attached")
#   z-ai/glm-5.2 (states it has no multimodal capability)
#   deepseek-ai/deepseek-v4-pro ("no actual property photos, only a generic basemap")
# NEVER register these as vision lanes. The _looks_blind() guard below is the backstop.
#
# ENTITLEMENT (settled, stop re-chasing): the 404 "Function ...: Not found for account"
# models are not a routing problem. The alternate ai.api.nvidia.com/v1/vlm/{org}/{model}
# route resolves to the same NVCF function UUID and returns the same 404, and those UUIDs
# are absent from this account's NVCF registry. They are simply not entitled to this key.


class QuotaExhausted(Exception):
    """Raised by a backend on HTTP 429 / RESOURCE_EXHAUSTED. The pool re-queues
    the listing (no attempt spent) and backs the lane off.

    retry_after  seconds the provider said to wait (Retry-After header or the
                 "Please retry in 14.6s" line of a Gemini 429 body), else None.
    daily        True when the 429 is a DAILY cap (Gemini ...PerDay..., Cloudflare
                 "daily free allocation of 10,000 neurons"): waiting a minute
                 cannot fix that, so the pool disables the lane for the run
                 instead of cooling down and retrying it ten times.
    Both default so the historical `raise QuotaExhausted(name)` still works.
    """

    def __init__(self, *args, retry_after: Optional[float] = None, daily: bool = False):
        super().__init__(*args)
        self.retry_after = retry_after
        self.daily = daily


class BackendDisabled(Exception):
    """Raised by a backend on a PERMANENT error: HTTP 401/402/403/404/410 (dead
    or end-of-life model, unpaid subscription, bad key, model not entitled to this
    key). Retrying cannot help within a run, so the pool disables the lane for the
    rest of the run on the FIRST occurrence instead of feeding it five listings."""

    def __init__(self, name: str = "", status: Optional[int] = None, reason: str = ""):
        super().__init__(name, status, reason)
        self.name = name
        self.status = status
        self.reason = reason


#: HTTP statuses that mean "this lane is gone for the run".
_PERMANENT_STATUSES = frozenset({401, 402, 403, 404, 410})

_DAILY_MARKERS = ("perday", "per day", "daily", "neurons")


def _is_quota_msg(msg: str) -> bool:
    msg = msg.lower()
    return ("429" in msg or "resource_exhausted" in msg or "quota" in msg
            or "exceeded" in msg or "rate limit" in msg)


def _is_daily_quota(msg: str) -> bool:
    """True when a 429 body says the DAILY cap is spent (see QuotaExhausted.daily)."""
    m = (msg or "").lower()
    return any(k in m for k in _DAILY_MARKERS)


def _retry_after_seconds(msg: str = "", header: Optional[str] = None) -> Optional[float]:
    """Provider's own 'wait this long' hint: the Retry-After header, else the
    'Please retry in 14.59s' / 'retry in 51.6s' line Gemini appends to a 429."""
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    m = re.search(r"retry in ([\d.]+)\s*s", msg or "", re.I)
    if m:
        try:
            return max(0.0, float(m.group(1)))
        except ValueError:
            return None
    return None


def _safe_body(text: str) -> str:
    """Provider error text with the account identifier NVIDIA echoes on a 404
    ("Not found for account '<id>'") removed, so a shared log carries no ids."""
    return re.sub(r"account '[^']*'", "account '<redacted>'", text or "")


def _http_status_of(exc: BaseException) -> Optional[int]:
    """HTTP status carried by an SDK exception (google.genai ClientError/ServerError
    expose .code), else parsed off the leading '429 RESOURCE_EXHAUSTED.' of its text."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    m = re.match(r"\s*(\d{3})\b", str(exc))
    return int(m.group(1)) if m else None


CONDITION_TIERS = ("move_in_ready", "cosmetic", "major", "gut")


def _canonical_tier(result: Optional[dict]) -> Optional[str]:
    """Normalize `result["condition_tier"]` in place and return it, or None.

    Weaker models echo the prompt's literal ``condition_tier=null`` instruction,
    or answer with the string "null"/"none"/"n/a" instead of a real JSON null.
    Anything that isn't one of the four canonical tiers becomes None, so every
    reader (the override rule, the null-tier re-queue) agrees on what counts as
    an actual grade.
    """
    if not isinstance(result, dict):
        return None
    ct = result.get("condition_tier")
    if isinstance(ct, str):
        s = ct.strip().lower()
        if "=" in s:                       # "condition_tier=null" -> "null"
            s = s.split("=", 1)[1].strip()
        ct = s if s in CONDITION_TIERS else None
    elif ct not in CONDITION_TIERS:
        ct = None
    result["condition_tier"] = ct
    return ct


# A model that cannot actually SEE the attached image but answers anyway is the
# most dangerous backend failure mode here: it returns HTTP 200 and perfectly
# parseable JSON, so every other guard passes, and a confident condition_tier on an
# unseen photo silently corrupts condition -> rehab estimate -> ARV -> max bid.
# Measured 2026-07-27: openai/gpt-oss-120b and gpt-oss-20b reply "there's no image
# attached", z-ai/glm-5.2 says it has no multimodal capability, and deepseek-v4-pro
# reported "no actual property photos, only a generic basemap or Realtor placeholder"
# on 4 real house photos. Those ids are unregistered, but this catches any future one.
_BLIND_MARKERS = (
    "no image", "not attached", "no photo", "cannot see", "can't see", "unable to see",
    "no actual property photo", "don't have access to", "do not have access to",
    "no multimodal", "not multimodal", "unable to view", "cannot view",
    "as a text-based", "i'm unable to process image",
)


def _looks_blind(parsed: dict) -> bool:
    """True when the reply reads like the model never received the image."""
    blob = " ".join(
        str(parsed.get(k) or "") for k in ("summary", "notes", "reasoning", "description", "raw")
    ).lower()
    return any(m in blob for m in _BLIND_MARKERS)


def _finalize(parsed: Optional[dict], provider: str, model: str, n: int,
              urls: list[str], usage: Optional[dict] = None) -> Optional[dict]:
    if not parsed:
        return None
    # Blind-but-confident backstop: drop the result entirely rather than let an
    # unseeing model's tier reach the board. Returning None routes the listing to
    # another backend, exactly like any other hard failure.
    if _looks_blind(parsed):
        log.warning("vision.backend_blind", provider=provider, model=model,
                    note="reply indicates the image was not received — result discarded")
        return None
    if usage:
        parsed["_usage"] = usage
    parsed["_provider"] = provider
    parsed["_model"] = model
    parsed["_n_photos"] = n
    parsed["_image_urls"] = urls
    return parsed


class _GeminiBackend:
    """One (Gemini API key, model) pair = one lane with its OWN free-tier bucket.

    Google meters the free tier per project per model, so a lane is the unit of
    quota, of pacing and of health. `gate` is an optional asyncio.Semaphore shared
    by every lane of ONE key: it caps how many calls that key's project has in
    flight at once, so a key that carries five models is not hit by five
    simultaneous requests (the "one key hammered" failure).
    """
    def __init__(self, key: str, idx: int, model: Optional[str] = None,
                 gate: Optional[asyncio.Semaphore] = None,
                 delay: Optional[float] = None, name: Optional[str] = None):
        from google import genai
        self.client = genai.Client(api_key=key)
        self.model = model or GEMINI_VISION_MODEL
        self.name = name or f"gemini#{idx}"
        self.delay = INTER_CALL_DELAY if delay is None else delay
        self.cap = MAX_PHOTOS_PER_LISTING
        self.gate = gate
        self.workers = 1
        self.start_delay = 0.0           # set by _build_backends (opening-burst stagger)

    async def assess(self, li: Listing, payloads, urls) -> Optional[dict]:
        from google.genai import types as t
        parts = [t.Part.from_bytes(data=d, mime_type=m) for d, m in payloads[:self.cap]]
        prompt = f"{SYSTEM_PROMPT}\n\n{_user_prompt(li)}"
        try:
            cfg = t.GenerateContentConfig(
                max_output_tokens=MAX_TOKENS,
                response_mime_type="application/json",
                http_options=t.HttpOptions(timeout=int(_call_timeout() * 1000)))
            if self.gate is not None:
                async with self.gate:
                    resp = await self.client.aio.models.generate_content(
                        model=self.model, contents=parts + [prompt], config=cfg)
            else:
                resp = await self.client.aio.models.generate_content(
                    model=self.model, contents=parts + [prompt], config=cfg)
        except Exception as exc:
            msg = str(exc)
            status = _http_status_of(exc)
            if status == 429 or (status is None and _is_quota_msg(msg)):
                raise QuotaExhausted(self.name, retry_after=_retry_after_seconds(msg),
                                     daily=_is_daily_quota(msg))
            if status in _PERMANENT_STATUSES or (
                    status == 400 and "api key" in msg.lower()):
                raise BackendDisabled(self.name, status, _exc_label(exc, 120))
            log.warning("vision.api_error", backend=self.name, source_url=li.source_url,
                        status=status, error=_exc_label(exc, 160))
            return None
        text = ""
        try:
            text = (resp.text or "").strip()
        except Exception:
            for cand in getattr(resp, "candidates", []) or []:
                for p in getattr(getattr(cand, "content", None), "parts", []) or []:
                    text += getattr(p, "text", "") or ""
        usage = None
        u = getattr(resp, "usage_metadata", None)
        if u:
            usage = {"input_tokens": getattr(u, "prompt_token_count", None),
                     "output_tokens": getattr(u, "candidates_token_count", None)}
        return _finalize(_parse_json_response(text), "gemini", self.model,
                         len(parts), urls, usage)


class _OpenAICompatBackend:
    """GitHub Models or Groq — both speak the OpenAI chat/completions API
    with base64 data-URL images."""
    def __init__(self, name: str, url: str, key: str, model: str,
                 http: httpx.AsyncClient, cap: int = 4, delay: float = 1.0,
                 extra_body: Optional[dict] = None, workers: int = 1):
        self.name = name
        self.url = url
        self.key = key
        self.model = model
        self.http = http
        self.cap = cap
        self.delay = delay
        # Concurrent worker tasks the pool runs against THIS lane. NIM answers in
        # 7-30s and rate-limits at ~40 RPM per model, so one sequential worker
        # (the old shape) left most of the lane's quota unused: measured
        # 2026-09-21, 6 simultaneous calls per model all succeeded.
        self.workers = max(1, int(workers))
        self.start_delay = 0.0           # set by _build_backends (opening-burst stagger)
        self.worker_stagger = _start_stagger()   # gap between this lane's own workers
        # Provider-specific request fields (e.g. Groq needs reasoning_effort
        # "none" or its qwen3.6 vision model never stops thinking long enough
        # to emit the JSON). Merged into the body verbatim.
        self.extra_body = extra_body or {}

    async def assess(self, li: Listing, payloads, urls) -> Optional[dict]:
        content = [{"type": "text", "text": f"{SYSTEM_PROMPT}\n\n{_user_prompt(li)}"}]
        for d, m in payloads[:self.cap]:
            b64 = base64.b64encode(d).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:{m};base64,{b64}"}})
        body = {"model": self.model, "max_tokens": MAX_TOKENS, "temperature": 0.2,
                "messages": [{"role": "user", "content": content}]}
        body.update(self.extra_body)
        try:
            r = await self.http.post(self.url, json=body, timeout=_call_timeout(),
                                     headers={"Authorization": f"Bearer {self.key}",
                                              "Content-Type": "application/json"})
        except Exception as exc:
            log.warning("vision.api_error", backend=self.name, source_url=li.source_url, error=_exc_label(exc, 160))
            return None
        if r.status_code == 429:
            body_txt = getattr(r, "text", "") or ""
            hdrs = getattr(r, "headers", None) or {}
            raise QuotaExhausted(
                self.name,
                retry_after=_retry_after_seconds(body_txt, hdrs.get("retry-after")),
                daily=_is_daily_quota(body_txt))
        if r.status_code in _PERMANENT_STATUSES:
            # 410 end-of-life / retired service, 402 unpaid subscription, 401/403
            # bad key, 404 model not deployed for this key: nothing a retry fixes.
            body_txt = _safe_body(r.text)
            log.warning("vision.api_error", backend=self.name, status=r.status_code, error=body_txt[:160])
            raise BackendDisabled(self.name, r.status_code, body_txt[:120])
        if r.status_code >= 400:
            log.warning("vision.api_error", backend=self.name, status=r.status_code, error=_safe_body(r.text)[:160])
            return None
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"]
        except Exception:
            return None
        usage = None
        u = data.get("usage") or {}
        if u:
            usage = {"input_tokens": u.get("prompt_tokens"),
                     "output_tokens": u.get("completion_tokens")}
        return _finalize(_parse_json_response(text), self.name, self.model,
                         min(len(payloads), self.cap), urls, usage)


class _OllamaBackend:
    """Local Ollama vision model — unlimited, free, never quota-exhausts."""
    def __init__(self, host: str, model: str, http: httpx.AsyncClient, cap: int = 1):
        self.name = "ollama"
        self.host = host
        self.model = model
        self.http = http
        self.cap = cap
        self.delay = 0.0
        self.is_floor = True   # low-quality local fallback: run last, only on leftovers

    @staticmethod
    def _to_clean_jpeg_b64(data: bytes) -> Optional[str]:
        """Normalize any image to a plain RGB JPEG — moondream's loader rejects
        webp/odd formats with 'failed to load image'. Returns base64 or None."""
        try:
            import io
            from PIL import Image
            im = Image.open(io.BytesIO(data))
            im.load()
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            # Downscale big photos — moondream is small; 768px is plenty.
            im.thumbnail((768, 768))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            return None

    async def assess(self, li: Listing, payloads, urls) -> Optional[dict]:
        imgs = []
        for d, _ in payloads[:self.cap]:
            j = self._to_clean_jpeg_b64(d)
            if j:
                imgs.append(j)
        if not imgs:
            return None
        body = {"model": self.model, "stream": False, "format": "json",
                "prompt": f"{SYSTEM_PROMPT}\n\n{_user_prompt(li)}",
                "images": imgs, "options": {"num_predict": MAX_TOKENS}}
        try:
            r = await self.http.post(f"{self.host}/api/generate", json=body, timeout=240.0)
        except Exception as exc:
            log.warning("vision.api_error", backend=self.name, source_url=li.source_url, error=_exc_label(exc, 160))
            return None
        if r.status_code >= 400:
            log.warning("vision.api_error", backend=self.name, status=r.status_code, error=r.text[:160])
            return None
        try:
            text = r.json().get("response", "")
        except Exception:
            return None
        return _finalize(_parse_json_response(text), "ollama", self.model, len(imgs), urls)


class _AnthropicBackend:
    """Legacy paid fallback — only used when no free backend is configured."""
    def __init__(self, client):
        self.client = client
        self.name = "anthropic"
        self.model = ANTHROPIC_VISION_MODEL
        self.delay = INTER_CALL_DELAY
        self.cap = MAX_PHOTOS_PER_LISTING

    async def assess(self, li: Listing, payloads, urls) -> Optional[dict]:
        if _spend_guard.over_budget():
            # A QuotaExhausted raise is the pool's existing signal for "this
            # backend is done" — it retires the backend and re-queues whatever
            # it was holding to a live lane, exactly like a real 429. Reusing
            # it means the $ cap needs no new pool-level handling.
            if not _spend_guard._warned:
                log.info("vision.anthropic_budget_reached",
                         spent_usd=round(_spend_guard.spent, 2),
                         limit_usd=_spend_guard.limit)
                _spend_guard._warned = True
            raise QuotaExhausted(self.name)
        blocks = [{"type": "image", "source": {"type": "base64", "media_type": m,
                   "data": base64.b64encode(d).decode("ascii")}}
                  for d, m in payloads[:self.cap]]
        try:
            resp = await self.client.messages.create(
                model=self.model, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": blocks + [{"type": "text", "text": _user_prompt(li)}]}])
        except Exception as exc:
            if _is_quota_msg(str(exc)):
                raise QuotaExhausted(self.name)
            log.warning("vision.api_error", backend=self.name, source_url=li.source_url, error=_exc_label(exc, 160))
            return None
        text = "\n".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        usage = None
        u = getattr(resp, "usage", None)
        if u:
            in_tok = getattr(u, "input_tokens", None) or 0
            out_tok = getattr(u, "output_tokens", None) or 0
            usage = {"input_tokens": in_tok, "output_tokens": out_tok}
            _spend_guard.record(self.model, in_tok, out_tok)
        return _finalize(_parse_json_response(text), "anthropic", self.model,
                         len(blocks), urls, usage)


class _LaneHealth:
    """Half-open circuit breaker for ONE backend, shared by all of its workers.

    WHY THIS EXISTS. The pool used to retire a backend by letting its worker
    `return`, forever. Any backend that looked bad for a few minutes (a Gemini
    per-minute 429 storm, a run of NIM 503s, a network blip) was gone for the rest
    of the 4-hour run, and nothing ever brought it back. Measured 2026-09-21:
    live_workers went 20 -> 12 -> 3 -> 1 inside 40 minutes and stayed at 1 for
    3 hours while the lanes that had only been rate-limited sat retired.

    States
      closed    healthy; takes work.
      open      banned until `open_until`; then ONE worker is granted a probe
                (half-open). A successful probe closes it, a failed one re-opens
                it for another `reopen_s`.
      disabled  gone for the run (410/402/401/403/404, daily quota spent). Never
                probed: a retry cannot help before the quota clock resets.

    reopen_s == 0 restores the legacy behaviour (a tripped lane is disabled, its
    workers exit); the pre-existing pool tests pin that mode.

    Error handling this class encodes
      record_permanent()   410/402/... -> disabled immediately.
      record_quota(daily)  daily cap -> disabled; per-minute 429 -> exponential
                           back-off with jitter (honouring the provider's own
                           retry-after), and `strike_limit` consecutive 429s
                           trip the breaker.
      record_hard_fail()   timeout / 5xx / unparseable: `hard_limit` consecutive
                           failures trip the breaker.
      record_success()     closes the breaker and clears every counter.
    """

    def __init__(self, name: str, *, hard_limit: int = 5, strike_limit: int = 10,
                 reopen_s: float = 600.0, cooldown_s: float = 70.0,
                 max_backoff_s: float = 300.0,
                 clock: Callable[[], float] = time.monotonic,
                 rand: Callable[[], float] = random.random):
        self.name = name
        self.hard_limit = max(1, hard_limit)
        self.strike_limit = max(1, strike_limit)
        self.reopen_s = max(0.0, reopen_s)
        self.cooldown_s = max(0.0, cooldown_s)
        self.max_backoff_s = max(self.cooldown_s, max_backoff_s)
        self._clock = clock
        self._rand = rand
        self.state = "closed"
        self.open_until = 0.0
        self.probing = False
        self.hard_fails = 0          # consecutive
        self.strikes = 0             # consecutive 429s
        self.reason = ""
        # lifetime counters, for the end-of-run per-backend table
        self.attempts = 0
        self.ok = 0
        self.errors: dict[str, int] = {}
        self.trips = 0
        self.readmissions = 0

    # -- queries ---------------------------------------------------------
    @property
    def up(self) -> bool:
        """Counts toward `live_workers`: closed, or a probe is in flight."""
        return self.state == "closed" or (self.state == "open" and self.probing)

    def gate(self) -> tuple[str, float]:
        """What may a worker of this backend do right now?
        ("go", 0)      take work.
        ("probe", 0)   take work as the half-open probe (exactly one caller gets it).
        ("wait", s)    banned; come back in about s seconds.
        ("off", 0)     disabled: the worker should exit."""
        if self.state == "closed":
            return "go", 0.0
        if self.state == "disabled":
            return "off", 0.0
        now = self._clock()
        if self.probing:
            return "wait", 1.0               # a peer worker is running the probe
        if now < self.open_until:
            return "wait", self.open_until - now
        self.probing = True
        self.readmissions += 1
        return "probe", 0.0

    # -- outcomes --------------------------------------------------------
    def _note(self, kind: str) -> None:
        self.errors[kind] = self.errors.get(kind, 0) + 1

    def record_success(self) -> bool:
        """Returns True when this success re-admitted a banned lane."""
        self.ok += 1
        self.attempts += 1
        self.hard_fails = 0
        self.strikes = 0
        self.probing = False
        if self.state == "open":
            self.state = "closed"
            self.reason = ""
            return True
        return False

    def _trip(self, reason: str) -> None:
        if self.state == "disabled":
            # A permanent disable is final: a late failure reported by a peer worker
            # that was still in flight must not turn it into a re-admittable ban.
            return
        self.probing = False
        self.reason = reason
        self.trips += 1
        if self.reopen_s <= 0:
            self.state = "disabled"          # legacy: retired for the run
        else:
            self.state = "open"
            self.open_until = self._clock() + self.reopen_s

    def record_permanent(self, status, reason: str = "") -> None:
        self.attempts += 1
        self._note(f"http{status}" if status else "permanent")
        self.probing = False
        self.state = "disabled"
        self.reason = f"permanent:{status}" + (f" {reason}" if reason else "")

    def record_hard_fail(self, kind: str = "hard") -> bool:
        """Returns True when this failure tripped the breaker."""
        self.attempts += 1
        self._note(kind)
        self.hard_fails += 1
        if self.probing or self.hard_fails >= self.hard_limit:
            self._trip(f"{self.hard_fails} consecutive failures ({kind})")
            return True
        return False

    def record_quota(self, retry_after: Optional[float] = None,
                     daily: bool = False) -> tuple[float, bool]:
        """A 429. Returns (seconds the worker should sleep, tripped?).
        A 429 spends no listing attempt, so it does not bump `attempts`."""
        self._note("429-daily" if daily else "429")
        if daily:
            self.probing = False
            self.state = "disabled"
            self.reason = "daily quota spent"
            return 0.0, True
        self.strikes += 1
        if self.probing or self.strikes >= self.strike_limit:
            self._trip(f"{self.strikes} consecutive 429s")
            return 0.0, True
        if retry_after is not None and retry_after > 0:
            base = retry_after + 1.0
        else:
            base = self.cooldown_s * (2 ** (self.strikes - 1))
        wait = min(self.max_backoff_s, base)
        return wait * (1.0 + 0.25 * self._rand()), False   # jitter: never a lock-step retry


async def _build_backends(http: httpx.AsyncClient) -> list:
    """Assemble every available FREE vision backend (plus paid Anthropic only
    as a last resort). Order doesn't matter — all pull from one shared queue."""
    backends: list = []

    # Gemini: one lane per (key, model). Each key is one project; Google meters
    # the free tier per project PER MODEL, so N keys x M models = N*M independent
    # buckets (gemini-2.5-flash alone is only 20 requests/day/project; see
    # GEMINI_POOL_MODELS). Two spreading rules keep the keys from being hammered:
    #   * the model order is ROTATED per key, so the nine keys do not all open on
    #     the same model at the same second;
    #   * one semaphore per key (VISION_GEMINI_KEY_CONCURRENCY, default 2) bounds
    #     that project's in-flight calls across all of its models.
    keys = _parse_gemini_keys()
    if keys:
        try:
            from google import genai  # noqa: F401
            models = GEMINI_POOL_MODELS or [GEMINI_VISION_MODEL]
            per_key = max(1, int(os.environ.get("VISION_GEMINI_KEY_CONCURRENCY", "2")))
            stagger = _start_stagger()
            for i, k in enumerate(keys, 1):
                gate = asyncio.Semaphore(per_key)
                rot = (i - 1) % len(models)
                for n, m in enumerate(models[rot:] + models[:rot]):
                    rpm = GEMINI_MODEL_RPM.get(m, 5)
                    delay = max(INTER_CALL_DELAY, 60.0 / rpm + 0.5)
                    name = f"gemini#{i}" if len(models) == 1 else f"gemini#{i}:{m.replace('gemini-', '')}"
                    try:
                        b = _GeminiBackend(k, i, model=m, gate=gate, delay=delay, name=name)
                        b.start_delay = ((i - 1) + n * 0.5) * stagger
                        backends.append(b)
                    except Exception as exc:
                        log.warning("vision.backend_init_fail", backend=name, error=str(exc)[:120])
        except ImportError:
            log.warning("vision.sdk_missing", provider="gemini", hint="pip install google-genai")

    # GitHub Models — free, uses the gh token if GITHUB_MODELS_TOKEN/GITHUB_TOKEN set.
    # ONE LANE PER MODEL: GitHub rate-limits per model tier, so registering N verified
    # models gives N parallel free lanes instead of one (was a single gpt-4o-mini lane).
    # GITHUB MODELS WAS FULLY RETIRED ON 2026-07-30 (github.blog changelog
    # 2026-07-30 "GitHub Models is now retired"): the catalog and inference
    # endpoints answer 503 HTML / 410 "retirement brownout" for every model.
    # Verified live 2026-09-21. Off unless VISION_ENABLE_GITHUB=1.
    gh = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if gh and os.environ.get("VISION_ENABLE_GITHUB") == "1":
        for m in (GITHUB_VISION_MODELS or [GITHUB_MODELS_MODEL]):
            short = m.split("/")[-1][:28]
            backends.append(_OpenAICompatBackend(f"github:{short}", GITHUB_MODELS_URL, gh,
                                                 m, http, cap=2, delay=2.0))

    # Groq — free, fast, but the free tier caps qwen3.6-27b at 8k tokens/minute
    # and one prompt+photo is ~5.4k, so pace it ~1 call/min (delay=45) instead
    # of the old 2s, which just bought a 429 on every second call. cap=1 for the
    # same token-budget reason. reasoning_effort=none is REQUIRED (see GROQ_MODEL).
    gq = os.environ.get("GROQ_API_KEY")
    if gq and GROQ_MODEL:
        backends.append(_OpenAICompatBackend("groq", GROQ_URL, gq, GROQ_MODEL,
                                             http, cap=1, delay=45.0,
                                             extra_body=GROQ_EXTRA_BODY))

    # OpenRouter — free tier, one key reaches many free vision models.
    ork = os.environ.get("OPENROUTER_API_KEY")
    if ork:
        backends.append(_OpenAICompatBackend("openrouter", OPENROUTER_URL, ork,
                                             OPENROUTER_MODEL, http, cap=4, delay=3.0))

    # Mistral — free tier, and rate limits are PER CANONICAL MODEL (verified live from
    # the x-ratelimit-limit-req-minute headers), so each verified model is its own lane.
    # The old single "mistral" lane at delay=30 was sized for a believed 2 RPM; the real
    # limits are far higher (ministral-3b is 750 RPM), so pace per model instead.
    _MISTRAL_DELAY = {           # seconds between calls, from the measured RPM
        "ministral-3b-latest": 0.5,     # 750 RPM
        "ministral-8b-latest": 1.0,     # 188 RPM
        "mistral-medium-latest": 2.0,   #  50 RPM
        "mistral-large-latest": 16.0,   #   4 RPM
    }
    # Mistral answers HTTP 402 "Check your subscription" on every model with this
    # key (verified live 2026-09-21): the free Experiment tier is no longer active
    # for it. Off unless VISION_ENABLE_MISTRAL=1 (set it after fixing the account).
    mk = os.environ.get("MISTRAL_API_KEY")
    if mk and os.environ.get("VISION_ENABLE_MISTRAL") == "1":
        for m in (MISTRAL_VISION_MODELS or [MISTRAL_MODEL]):
            backends.append(_OpenAICompatBackend(f"mistral:{m[:24]}", MISTRAL_URL, mk,
                                                 m, http, cap=2,
                                                 delay=_MISTRAL_DELAY.get(m, 30.0)))

    # Cloudflare Workers AI — 10k neurons/day free. Needs account id + token.
    cf_tok = os.environ.get("CLOUDFLARE_API_TOKEN")
    cf_acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if cf_tok and cf_acct:
        cf_url = f"https://api.cloudflare.com/client/v4/accounts/{cf_acct}/ai/v1/chat/completions"
        backends.append(_OpenAICompatBackend("cloudflare", cf_url, cf_tok,
                                             CLOUDFLARE_MODEL, http, cap=2, delay=1.0))

    # NVIDIA NIM — ONE free key, MANY vision models, each its own ~40 RPM lane.
    # The per-model limits stack into parallel free lanes, so this is typically
    # the single biggest contributor in the pool. All 8 models re-verified with
    # a real single-image call on 2026-07-27 (see NVIDIA_VISION_MODELS).
    nv = os.environ.get("NVIDIA_API_KEY")
    if nv:
        for m in NVIDIA_VISION_MODELS:
            short = m.split("/")[-1][:22]
            # cap=1 (single image): several NIM models (llama-3.2-90b, the mistral
            # family) reject >1 image ("at most 1 image"); sending just the primary
            # photo makes ALL 13 lanes usable for multi-photo listings + kills the
            # ~500 wasted "at most 1 image" calls seen in the backlog-clear run.
            nb = _OpenAICompatBackend(
                f"nvidia:{short}", NVIDIA_URL, nv, m, http, cap=1, delay=2.0,
                workers=NVIDIA_LANE_WORKERS.get(m, NVIDIA_DEFAULT_WORKERS))
            nb.start_delay = len(backends) * 0.25 * _start_stagger()
            backends.append(nb)

    # Ollama — local, unlimited. Only if the daemon is reachable + model present.
    if os.environ.get("VISION_USE_OLLAMA", "1") != "0":
        try:
            tr = await http.get(f"{OLLAMA_HOST}/api/tags", timeout=2.5)
            if tr.status_code == 200:
                names = [m.get("name", "") for m in (tr.json().get("models") or [])]
                if any(OLLAMA_MODEL in n for n in names):
                    backends.append(_OllamaBackend(OLLAMA_HOST, OLLAMA_MODEL, http))
                else:
                    log.info("vision.ollama_model_absent", host=OLLAMA_HOST, want=OLLAMA_MODEL, have=names[:5])
        except Exception:
            pass  # ollama not running — fine, it's optional

    # Anthropic — paid. Default stays "fallback of last resort" (only added
    # when the free pool is empty) so a normal run never spends money by
    # accident. Set VISION_INCLUDE_ANTHROPIC=1 to add it to the pool alongside
    # whatever free backends are present — e.g. to deliberately spend down a
    # pre-funded budget (VISION_MAX_SPEND_USD) faster than the free pool alone
    # would clear the backlog. It draws from the SAME shared queue as every
    # other backend, so it only picks up listings the free lanes haven't
    # already claimed — it competes for the tail, it doesn't duplicate work.
    want_anthropic = not backends or os.environ.get("VISION_INCLUDE_ANTHROPIC") == "1"
    if want_anthropic and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from anthropic import AsyncAnthropic
            backends.append(_AnthropicBackend(AsyncAnthropic(
                api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=4, timeout=90.0)))
        except ImportError:
            log.warning("vision.sdk_missing", provider="anthropic", hint="pip install anthropic")

    return backends


# Pricing per 1M tokens for cost estimate logging. Anthropic: Sonnet 4.5
# $3 in / $15 out. Gemini-2.5-flash: $0.075 in / $0.30 out (paid tier).
# Free pools (gemini free project, github models, groq, ollama) cost $0; the
# math still yields a "what it would have cost" figure for capacity planning.
_PROVIDER_PRICING = {
    "anthropic": {"in_per_mtok": 3.0, "out_per_mtok": 15.0},
    "gemini": {"in_per_mtok": 0.075, "out_per_mtok": 0.30},
    "github": {"in_per_mtok": 0.15, "out_per_mtok": 0.60},
    "groq": {"in_per_mtok": 0.0, "out_per_mtok": 0.0},
    "ollama": {"in_per_mtok": 0.0, "out_per_mtok": 0.0},
}


def _needs_vision(li: Listing) -> bool:
    """A listing needs a vision pass if it has usable imagery AND is not already
    scored. Skipping already-scored leads makes the pass IDEMPOTENT — the
    full-run board-persist merge carries a matched lead's prior raw["vision"]
    onto the fresh Listing, and this gate then keeps the (free-tier-bounded)
    vision budget from re-grading work already done.

    Escape hatch: VISION_REGRADE_SCORED=1 restores the old behavior (re-read
    already-scored leads too — e.g. an imminent sale that gained fresh photos),
    letting the _vpri sort decide order instead of skipping outright.
    """
    if not _select_image_urls(li):
        return False
    if os.environ.get("VISION_REGRADE_SCORED", "0") == "1":
        return True
    raw = li.raw if isinstance(li.raw, dict) else {}
    return not raw.get("vision")


def _distress_tier(li: Listing) -> str:
    """The stacked-distress tier the operator board shows (HOT/WARM/COLD), or ''.
    Lives in raw["distress_stack"]["tier"] (see distress_score.py)."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    ds = raw.get("distress_stack")
    return (ds.get("tier") or "") if isinstance(ds, dict) else ""


def _vpri(li: Listing):
    """Scoring order. Lower sorts first.

    1. PHOTO FIRST. Grading is only possible where an image exists, so a lead with
       one outranks a lead without one regardless of anything else. (Previously
       the key led with sale_date, which spent the whole budget on the
       soonest-selling leads whether or not they had a photo: 26,434 leads had a
       photo but only 10,250 were ever graded while quota went to basemap-only rows
       that can only return a null tier.)
    2. HOT, then WARM, then everything else. The operator works the HOT/WARM board;
       a condition read on a COLD row is worth far less than one on a HOT row, and a
       90-minute budget cannot reach all ~5,000 gradable rows. (2026-09-21)
    3. Soonest sale date, then never-scored before already-scored, then real
       auctions (opening bid) before the rest.
    """
    from datetime import datetime as _dt
    sd = li.sale_date
    if sd is not None and hasattr(sd, "tzinfo") and sd.tzinfo is not None:
        sd = sd.replace(tzinfo=None)
    has_date = 0 if sd else 1
    raw = li.raw if isinstance(li.raw, dict) else {}
    already_scored = 1 if raw.get("vision") else 0
    no_photo = 0 if _has_real_image(li) else 1
    tier_rank = {"HOT": 0, "WARM": 1}.get(_distress_tier(li), 2)
    return (no_photo, tier_rank, has_date, sd or _dt.max, already_scored,
            0 if li.opening_bid else 1)


class _YieldMonitor:
    """The 'stop burning the board lock on a dead pool' rule (audit O6).

    update() is called once per heartbeat and returns a reason string when the pass
    should end early, else None. It fires on either of:

      * COLLAPSE: the number of usable backends stayed <= `min_live` for
        `live_window_s` (default 2 backends for 15 minutes). Disabled when the pool
        never had more than `min_live` backends to begin with: a deliberately tiny
        pool did not collapse. (VISION_YIELD_LIVE_MIN / VISION_YIELD_LIVE_S)
      * LOW YIELD: after a `grace_s` warm-up (default 20 minutes), fewer than
        `min_rate_per_h` listings were scored per hour over the trailing
        `rate_window_s` (default 100/hour measured over 15 minutes). Never fires
        when the queue is empty, because then the run is simply finishing.
        (VISION_MIN_SCORED_PER_HOUR / VISION_YIELD_WINDOW_S / VISION_YIELD_WARMUP_S)

    VISION_YIELD_STOP=0 turns both rules off.

    A pure class with an injectable clock so the rules are unit-testable.
    """

    def __init__(self, *, initial_live: int, min_live: int = 2,
                 live_window_s: float = 900.0, min_rate_per_h: float = 100.0,
                 rate_window_s: float = 900.0, grace_s: float = 1200.0,
                 clock: Callable[[], float] = time.monotonic):
        self.initial_live = initial_live
        self.min_live = min_live
        self.live_window_s = live_window_s
        self.min_rate_per_h = min_rate_per_h
        self.rate_window_s = rate_window_s
        self.grace_s = grace_s
        self._clock = clock
        self._t0 = clock()
        self._low_since: Optional[float] = None
        self._hist: list[tuple[float, int]] = []

    def rate_per_hour(self, now: float, scored: int) -> Optional[float]:
        """Scored/hour over the trailing window, or None until a full window exists."""
        base = None
        for t, n in self._hist:
            if t <= now - self.rate_window_s:
                base = (t, n)
            else:
                break
        if base is None:
            return None
        dt = now - base[0]
        return (scored - base[1]) * 3600.0 / dt if dt > 0 else None

    def update(self, live: int, scored: int, queue_left: int) -> Optional[str]:
        now = self._clock()
        self._hist.append((now, scored))
        # keep just enough history for the trailing window
        cutoff = now - self.rate_window_s * 2
        while len(self._hist) > 2 and self._hist[1][0] < cutoff:
            self._hist.pop(0)

        if self.min_live >= 0 and self.initial_live > self.min_live:
            if live <= self.min_live:
                if self._low_since is None:
                    self._low_since = now
                elif now - self._low_since >= self.live_window_s:
                    return (f"live_workers<={self.min_live} for "
                            f"{int(now - self._low_since)}s (started with {self.initial_live})")
            else:
                self._low_since = None

        if queue_left > 0 and now - self._t0 >= self.grace_s and self.min_rate_per_h > 0:
            rate = self.rate_per_hour(now, scored)
            if rate is not None and rate < self.min_rate_per_h:
                return (f"scored/hour {rate:.0f} < {self.min_rate_per_h:.0f} over the "
                        f"last {int(self.rate_window_s)}s")
        return None


#: Summary of the most recent enrich_with_vision() call (stop reason, per-backend
#: health table). Read by tests and by callers that want to log it; never required.
_LAST_RUN: dict = {}


async def enrich_with_vision(listings: list[Listing], max_listings: int | None = None) -> None:
    """Run vision condition assessment on listings with usable imagery.
    Overrides condition_tier with the photo-derived value when confidence
    is HIGH or MEDIUM.

    Provider selection via VISION_PROVIDER env:
      - "anthropic" (default): Claude Sonnet 4.5, ~$0.01-0.03/listing
      - "gemini": the free multi-provider pool (Gemini per-key-per-model lanes,
        NVIDIA NIM lanes, Groq, Cloudflare; see _build_backends)
    Caller controls budget by max_listings.

    Already-scored leads are skipped (idempotent) unless VISION_REGRADE_SCORED=1
    (see _needs_vision). Rows with no real photo are skipped unless
    VISION_INCLUDE_NO_PHOTO=1, and the rest are scored HOT, then WARM, first
    (see _vpri).

    The pass ends when the queue drains, at the VISION_MAX_SECONDS wall clock
    (default 90 minutes; 0 = unlimited), or when _YieldMonitor decides the pool has
    collapsed or is scoring under 100/hour.
    """
    global _LAST_RUN
    targets = [li for li in listings if _needs_vision(li)]
    skipped_no_photo = 0
    if os.environ.get("VISION_INCLUDE_NO_PHOTO", "0") != "1":
        n_before = len(targets)
        targets = [li for li in targets if _has_real_image(li)]
        skipped_no_photo = n_before - len(targets)
    # Prioritize the most actionable listings for the (free-quota-bounded) Vision
    # budget. See _vpri for the order and why.
    targets.sort(key=_vpri)
    if max_listings:
        targets = targets[:max_listings]
    if not targets:
        log.info("vision.no_targets", provider=VISION_PROVIDER, skipped_no_photo=skipped_no_photo)
        return

    log.info(
        "vision.start",
        provider=VISION_PROVIDER,
        target_count=len(targets),
        of_total=len(listings),
        hot=sum(1 for li in targets if _distress_tier(li) == "HOT"),
        warm=sum(1 for li in targets if _distress_tier(li) == "WARM"),
        skipped_no_photo=skipped_no_photo,
    )

    overrides = 0
    total_in = total_out = 0

    def _apply(li: Listing, result: Optional[dict]) -> None:
        nonlocal overrides, total_in, total_out
        if not result:
            return
        if not isinstance(li.raw, dict):
            li.raw = {}
        ct = _canonical_tier(result)
        li.raw["vision"] = result
        usage = result.pop("_usage", None) or {}
        total_in += usage.get("input_tokens", 0) or 0
        total_out += usage.get("output_tokens", 0) or 0
        conf = (result.get("confidence") or "").upper()
        if ct and conf in ("HIGH", "MEDIUM"):
            old = li.raw.get("condition_tier")
            li.raw["condition_tier"] = ct
            li.raw["condition_source"] = f"vision-{conf}"
            if old != ct:
                overrides += 1

    scored = 0
    ungraded = 0
    by_backend: dict[str, int] = {}

    def _apply2(li: Listing, result: Optional[dict]) -> None:
        nonlocal scored
        _apply(li, result)
        if result:
            scored += 1
            prov = result.get("_provider", "?")
            by_backend[prov] = by_backend.get(prov, 0) + 1

    def _record_ungraded(li: Listing, result: dict) -> None:
        """Every available backend answered but NONE actually graded the
        property (condition_tier came back null — 7 of 9 lanes did that on a
        real-photo probe, and a basemap-only listing legitimately yields null
        everywhere).

        Such a report must NOT land in raw["vision"]: that key is exactly what
        needs_vision()/_vpri treat as "already scored", so a weak lane's null
        would permanently lock the lead out of ever being graded properly.
        Park it under raw["vision_unscored"] instead — that key is absent from
        web_artifact.RAW_KEEP, so it never reaches the published board and the
        lead comes back un-scored (and re-gradable) on the next run.
        """
        nonlocal ungraded, total_in, total_out
        if not isinstance(li.raw, dict):
            li.raw = {}
        usage = result.pop("_usage", None) or {}
        total_in += usage.get("input_tokens", 0) or 0
        total_out += usage.get("output_tokens", 0) or 0
        li.raw["vision_unscored"] = result
        ungraded += 1

    run_started = time.monotonic()
    stop = {"reason": None, "at": 0.0}

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
        backends = await _build_backends(http)
        if not backends:
            log.warning("vision.no_backends",
                        hint="set GEMINI_API_KEY_n / NVIDIA_API_KEY / GROQ_API_KEY, or run Ollama")
            return
        log.info("vision.pool_built", backends=[b.name for b in backends], count=len(backends))

        # One SHARED queue; each backend runs `workers` tasks (default 1) pulling
        # from it, so a slow-but-healthy lane (a NIM model answering in 15s) is not
        # capped at one call at a time.
        queue: asyncio.Queue = asyncio.Queue()
        for li in targets:
            queue.put_nowait(li)

        # ---- error handling knobs (all env-tunable) --------------------------
        # 429  -> the lane backs off (exponential, jittered, honouring the
        #         provider's retry-after) and is banned after `max_strikes`
        #         consecutive 429s. A DAILY-cap 429 disables the lane for the run.
        # 410/402/401/403/404 -> the lane is disabled for the run on the FIRST hit
        #         (BackendDisabled). Before, each dead lane ate five listings.
        # timeout / 5xx / unparseable -> `max_hard_fails` consecutive failures ban it.
        # A banned lane is NOT gone: after `reopen_s` (default 10 minutes) ONE probe
        # call is let through (half-open circuit breaker); success re-admits it.
        # VISION_BACKEND_REOPEN_SECONDS=0 restores the legacy retire-for-the-run.
        cooldown = float(os.environ.get("VISION_BACKEND_COOLDOWN", "70"))
        max_strikes = int(os.environ.get("VISION_BACKEND_STRIKES", "10"))
        reopen_s = float(os.environ.get("VISION_BACKEND_REOPEN_SECONDS", "600"))
        max_backoff = float(os.environ.get("VISION_BACKEND_MAX_BACKOFF", "300"))
        # Per-listing hard timeout: covers the image fetch plus the provider call
        # (itself capped by VISION_CALL_TIMEOUT). A stuck await must never freeze a
        # worker. 90s (was 150s: a timeout held its worker for 2.5 minutes).
        item_timeout = float(os.environ.get("VISION_ITEM_TIMEOUT", "90"))

        # HARD failures (410 end-of-life, 404 unknown model, unparseable reply,
        # item timeout) are NOT quota problems. Before the 2026-07-27 fix they fell
        # straight through to _apply2(li, None) and the listing was DROPPED for the
        # whole run: one dead backend permanently ate one queue slot per failure
        # (1,222 of 1,500 slots that day). Two bounded guards fix it:
        #   1. Re-queue a hard-failed listing so a HEALTHY backend can still score
        #      it, bounded by a per-listing attempt budget.
        #   2. Ban the backend after VISION_BACKEND_HARD_FAILS CONSECUTIVE hard
        #      failures (a success resets the counter), so a dead lane stops eating
        #      the queue.
        #
        # The budget is PER-BACKEND, not global: each backend may attempt a given
        # listing ONCE, plus VISION_MAX_REQUEUE extra retries once every live lane
        # has had its turn, and never more than VISION_MAX_ATTEMPTS in total. So for
        # every listing
        #     attempts <= min(len(backends) + VISION_MAX_REQUEUE, VISION_MAX_ATTEMPTS)
        # which is finite and independent of how flaky any lane is. (The total cap
        # is new: with 40+ lanes the old len(backends)+2 let one bad listing walk
        # 40 slow lanes.)
        max_requeue = int(os.environ.get("VISION_MAX_REQUEUE", "2"))
        max_hard_fails = int(os.environ.get("VISION_BACKEND_HARD_FAILS", "5"))
        max_attempts = int(os.environ.get("VISION_MAX_ATTEMPTS", "8"))

        # Per-listing state keyed by id(li). id() is the one key that is unique BY
        # CONSTRUCTION here: `targets` holds a strong reference to every listing for
        # the whole call, so no id can be recycled mid-run. Do NOT key this by
        # source_url — 652 source_urls are shared by 19,392 board leads. See
        # test_attempt_budget_key_is_per_object.
        tried: dict[int, set[int]] = {}       # id(li) -> backend indexes that ran it
        tries: dict[int, int] = {}            # id(li) -> attempts spent (the hard cap)
        attempt_cap = min(len(backends) + max_requeue, max(1, max_attempts))

        is_floor = [bool(getattr(b, "is_floor", False)) for b in backends]
        healths: list[_LaneHealth] = [
            _LaneHealth(b.name, hard_limit=max_hard_fails, strike_limit=max_strikes,
                        reopen_s=reopen_s, cooldown_s=cooldown, max_backoff_s=max_backoff)
            for b in backends
        ]
        # API-backend indexes still able to take work. A floor lane is deliberately
        # NOT in here: a floor worker sits idle until every API worker has exited, so
        # counting it as "a lane that will come for this listing" would park the API
        # lanes waiting for a worker that is itself waiting for them.
        live_idx: set[int] = {i for i in range(len(backends)) if not is_floor[i]}
        workers_left = {i: max(1, int(getattr(b, "workers", 1)))
                        for i, b in enumerate(backends) if not is_floor[i]}
        # Listings the API pool exhausted its attempts on, held for the floor
        # (None when no floor backend is configured, so they are given up on).
        floor_pending: Optional[list[Listing]] = [] if any(is_floor) else None
        attempts = {"n": 0}                   # completed backend calls (watchdog progress)
        # Rows skipped because no photo could be downloaded, and the current run of
        # consecutive such rows across the whole pool (see the worker).
        dropped = {"no_image": 0}
        fetch_streak = {"n": 0}
        fetch_pause_after = int(os.environ.get("VISION_FETCH_PAUSE_AFTER", "20"))
        fetch_pause_s = float(os.environ.get("VISION_FETCH_PAUSE_S", "15"))
        fetch_stop_after = int(os.environ.get("VISION_FETCH_STOP_AFTER", "100"))
        max_inflight = max(1, int(os.environ.get("VISION_MAX_INFLIGHT", "24")))
        inflight_sem = asyncio.Semaphore(max_inflight)   # bounds decoded images in RAM (8GB Mac)

        def _requeue(li: Listing, idx: int) -> bool:
            """Put a failed/ungraded listing back on the queue if attempts are
            left. Returns True if re-queued."""
            k = id(li)
            if tries.get(k, 0) >= attempt_cap:
                return False
            queue.put_nowait(li)
            return True

        # ...and on the pop side, PREFER a listing this lane hasn't tried. The scan is
        # bounded (never walks the whole queue — it can be 19k items), defers at most
        # scan_limit-1 items to the back, and never drops one, so it cannot livelock
        # or CPU-spin.
        scan_limit = max(1, int(os.environ.get("VISION_REQUEUE_SCAN", "8")))

        def _take(idx: int, allow_repeat: bool) -> Optional[Listing]:
            deferred: list[Listing] = []
            chosen: Optional[Listing] = None
            for _ in range(scan_limit):
                try:
                    li = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if idx not in (tried.get(id(li)) or ()):
                    chosen = li
                    break
                deferred.append(li)
            if chosen is None and allow_repeat:
                # Everything nearby was already tried by THIS lane. Only take a
                # repeat for a listing no other live lane could serve better — that
                # lane will pop it on its own next tick.
                for i, li in enumerate(deferred):
                    seen = tried.get(id(li)) or set()
                    if not any(j not in seen for j in live_idx if j != idx):
                        chosen = deferred.pop(i)
                        break
            for d in deferred:
                queue.put_nowait(d)
            return chosen

        # An empty queue does NOT mean the run is over: another worker may still be
        # mid-call (or in its inter-call delay) on a listing that is about to be
        # re-queued. So a worker with nothing to pop idles while any peer is still
        # holding an item, and only re-attempts a listing it has already tried once
        # the whole pool has gone idle. Terminating: every queued listing still has
        # attempts left by construction, total attempts are capped, and each holder
        # finishes within item_timeout — so inflight reaches 0, the queue drains, and
        # every idler exits. The sleep keeps it off the CPU.
        inflight = {"n": 0}
        idle_tick = float(os.environ.get("VISION_IDLE_TICK", "0.05"))

        # Wall-clock cap so a long run can't overrun into the next scheduled pass
        # (and, for the daily job, so it stops holding the board lock). Default 90
        # minutes; VISION_MAX_SECONDS=0 = unlimited.
        _budget = vision_max_seconds()
        _deadline = (time.monotonic() + _budget) if _budget > 0 else None

        def _past_deadline() -> bool:
            return _deadline is not None and time.monotonic() > _deadline

        def _stopping() -> bool:
            return _past_deadline() or stop["reason"] is not None

        async def _next(idx: int) -> Optional[Listing]:
            idle_ticks = 0
            while True:
                li = _take(idx, allow_repeat=(inflight["n"] <= 0 and idle_ticks >= 2))
                if li is not None:
                    return li
                if _stopping():
                    return None
                if queue.empty() and inflight["n"] <= 0:
                    return None
                await asyncio.sleep(idle_tick)
                idle_ticks = idle_ticks + 1 if inflight["n"] <= 0 else 0

        # Floor backends (Ollama) are low-quality local fallbacks. They must only
        # score what the API pools COULDN'T this run — otherwise they'd race ahead (no
        # cooldown) and poison listings with weak scores that block a good provider
        # from scoring them on a future day. So a floor worker waits until every API
        # worker has exited, then drains the rest.
        api_active = {"n": sum(workers_left.values())}

        def _lane_event(h: _LaneHealth, backend, event: str, **kw) -> None:
            log.info(event, backend=backend.name, reason=h.reason, remaining=queue.qsize(), **kw)

        async def api_worker(backend, idx: int, wnum: int) -> None:
            health = healths[idx]
            holding = False
            try:
                # Spread the opening burst: nine keys x five models must not all fire
                # in the same second. Fakes without these attributes start at once.
                lead = float(getattr(backend, "start_delay", 0.0) or 0.0) \
                    + wnum * float(getattr(backend, "worker_stagger", 0.0) or 0.0)
                if lead > 0:
                    await asyncio.sleep(lead)
                while True:
                    # Release the previous item BEFORE asking for the next one, so a
                    # worker never counts itself as in-flight while idling.
                    if holding:
                        inflight["n"] -= 1
                        holding = False
                    if _stopping():
                        return
                    verdict, wait_s = health.gate()
                    if verdict == "off":
                        live_idx.discard(idx)
                        return
                    if verdict == "wait":
                        # Banned: nothing to do until the half-open probe window. Wake
                        # every few seconds so a stop/deadline is noticed, and give up
                        # if there is no work left that a probe could serve.
                        if queue.empty() and inflight["n"] <= 0:
                            return
                        await asyncio.sleep(min(max(wait_s, idle_tick), 5.0))
                        continue
                    probing = verdict == "probe"
                    if probing:
                        _lane_event(health, backend, "vision.backend_probe")
                    li = await _next(idx)
                    if li is None:
                        if probing:
                            health.probing = False   # hand the probe slot back
                        return
                    inflight["n"] += 1
                    holding = True
                    res = None
                    fail_kind = "none"
                    try:
                        async with inflight_sem:
                            payloads, urls = await asyncio.wait_for(
                                _fetch_image_blocks(li, http),
                                timeout=min(item_timeout, 30.0))
                            if payloads:
                                fetch_streak["n"] = 0
                                res = await asyncio.wait_for(
                                    backend.assess(li, payloads, urls), timeout=item_timeout)
                        if not payloads:
                            # No downloadable photo. Isolated, this is a dead image URL
                            # and the row is simply skipped for this run. A LONG STREAK
                            # is the network being down, and the old code then popped
                            # and dropped the entire queue at ~100 rows a second: the
                            # 9/20 pass ended with `unscored_remaining=0` after 4,406
                            # rows vanished in the last 45 seconds (same minute as the
                            # "Could not resolve host" push failure), and 9/14 drained
                            # 4,472 targets to 54 scored in 16 minutes the same way.
                            # So: count it, slow down, and stop the pass if it persists.
                            if probing:
                                health.probing = False
                            dropped["no_image"] += 1
                            fetch_streak["n"] += 1
                            if fetch_streak["n"] >= fetch_stop_after:
                                if stop["reason"] is None:
                                    stop["reason"] = (
                                        f"image_fetch_failing: {fetch_streak['n']} rows in a "
                                        f"row had no downloadable photo (network down?)")
                                    stop["at"] = time.monotonic()
                                    log.warning("vision.fetch_failing_stop",
                                                streak=fetch_streak["n"], queue=queue.qsize())
                            elif fetch_streak["n"] >= fetch_pause_after:
                                await asyncio.sleep(fetch_pause_s)
                            continue
                        health.strikes = 0
                    except QuotaExhausted as q:
                        # Nothing was assessed, so this does NOT spend one of the
                        # listing's per-backend attempts.
                        queue.put_nowait(li)
                        sleep_s, tripped = health.record_quota(q.retry_after, q.daily)
                        if health.state == "disabled":
                            _lane_event(health, backend, "vision.backend_retired",
                                        strikes=health.strikes, daily=q.daily)
                            continue
                        if tripped:
                            _lane_event(health, backend, "vision.backend_banned",
                                        strikes=health.strikes, reopen_s=reopen_s)
                            continue
                        log.info("vision.backend_cooldown", backend=backend.name,
                                 strikes=health.strikes, cooldown_s=round(sleep_s, 1),
                                 remaining=queue.qsize())
                        await asyncio.sleep(sleep_s)
                        continue
                    except BackendDisabled as d:
                        queue.put_nowait(li)          # not the listing's fault
                        health.record_permanent(d.status, d.reason)
                        _lane_event(health, backend, "vision.backend_disabled", status=d.status)
                        continue
                    except asyncio.TimeoutError:
                        fail_kind = "timeout"
                        log.warning("vision.item_timeout", backend=backend.name, remaining=queue.qsize())
                    except Exception as exc:
                        fail_kind = "error"
                        log.warning("vision.worker_error", backend=backend.name, error=str(exc)[:140])
                    # This lane has now had its turn at this listing.
                    tried.setdefault(id(li), set()).add(idx)
                    tries[id(li)] = tries.get(id(li), 0) + 1
                    attempts["n"] += 1
                    if res is not None:
                        # The call went through and parsed, so the lane is ALIVE even
                        # if it declined to grade the property.
                        if health.record_success():
                            _lane_event(health, backend, "vision.backend_readmitted")
                        if _canonical_tier(res):
                            _apply2(li, res)
                        elif not _requeue(li, idx):
                            # Every live lane declined — keep the report as a
                            # diagnostic but leave the lead formally un-scored.
                            log.info("vision.listing_ungraded", backend=backend.name,
                                     source_url=li.source_url)
                            _record_ungraded(li, res)
                    else:
                        # HARD failure (parse-fail/5xx/timeout). Hand the listing to
                        # another backend instead of dropping it, and count a strike
                        # against THIS backend.
                        tripped = health.record_hard_fail(fail_kind)
                        if not _requeue(li, idx):
                            if floor_pending is not None:
                                # The local floor exists precisely to finish what the
                                # API pool could not. Park it there (once — the floor
                                # never re-queues) instead of on the shared queue.
                                floor_pending.append(li)
                            else:
                                log.info("vision.listing_given_up", backend=backend.name,
                                         source_url=li.source_url,
                                         attempts=tries.get(id(li), 0),
                                         lanes=len(tried.get(id(li)) or ()))
                                _apply2(li, None)
                        if tripped:
                            _lane_event(
                                health, backend,
                                "vision.backend_retired_hard" if health.state == "disabled"
                                else "vision.backend_banned",
                                hard_fails=health.hard_fails, reopen_s=reopen_s)
                            continue
                    if getattr(backend, "delay", 0):
                        await asyncio.sleep(backend.delay)
            finally:
                if holding:
                    inflight["n"] -= 1
                workers_left[idx] -= 1
                if workers_left[idx] <= 0:
                    live_idx.discard(idx)
                api_active["n"] -= 1

        async def floor_worker(backend, idx: int) -> None:
            # Wait for the API pools to finish; bail early if they drain it all
            # AND left nothing parked for the floor.
            while api_active["n"] > 0:
                if queue.empty() and not floor_pending:
                    return
                if _stopping():
                    return
                await asyncio.sleep(3)
            log.info("vision.floor_active", backend=backend.name,
                     remaining=queue.qsize(), parked=len(floor_pending or ()))
            while True:
                if _stopping():
                    return
                li = _take(idx, allow_repeat=True)
                if li is None:
                    if floor_pending:
                        li = floor_pending.pop()
                    else:
                        return
                payloads, urls = await _fetch_image_blocks(li, http)
                if not payloads:
                    continue
                try:
                    res = await backend.assess(li, payloads, urls)
                except Exception as exc:
                    log.warning("vision.worker_error", backend=backend.name, error=str(exc)[:140])
                    res = None
                tried.setdefault(id(li), set()).add(idx)
                tries[id(li)] = tries.get(id(li), 0) + 1
                attempts["n"] += 1
                # The floor is the last resort — no re-queue from here. A null
                # tier still must not be written as a score (see _record_ungraded).
                if res is None:
                    _apply2(li, None)
                elif _canonical_tier(res):
                    _apply2(li, res)
                else:
                    _record_ungraded(li, res)

        worker_tasks = []
        for i, b in enumerate(backends):
            if is_floor[i]:
                worker_tasks.append(asyncio.create_task(floor_worker(b, i)))
            else:
                for w in range(workers_left[i]):
                    worker_tasks.append(asyncio.create_task(api_worker(b, i, w)))

        # Heartbeat + watchdogs. Every tick it (1) logs progress, (2) evaluates the
        # yield stop, (3) enforces the wall clock on lanes that ignore the deadline
        # (a worker asleep in a long back-off), and (4) aborts a pool that has made
        # no progress at all for VISION_STALL_SECONDS. Even a single wedged worker
        # (sync block / pool-wait that freezes the loop between item-timeouts) used
        # to stall the whole run silently.
        stall_limit = float(os.environ.get("VISION_STALL_SECONDS", "360"))
        hb_s = float(os.environ.get("VISION_HEARTBEAT_SECONDS", "60"))
        stop_grace = float(os.environ.get("VISION_STOP_GRACE_SECONDS", "30"))
        api_idx = [i for i in range(len(backends)) if not is_floor[i]]
        yield_on = os.environ.get("VISION_YIELD_STOP", "1") != "0"
        ymon = _YieldMonitor(
            initial_live=len(api_idx),
            min_live=int(os.environ.get("VISION_YIELD_LIVE_MIN", "2")),
            live_window_s=float(os.environ.get("VISION_YIELD_LIVE_S", "900")),
            min_rate_per_h=float(os.environ.get("VISION_MIN_SCORED_PER_HOUR", "100")),
            rate_window_s=float(os.environ.get("VISION_YIELD_WINDOW_S", "900")),
            grace_s=float(os.environ.get("VISION_YIELD_WARMUP_S", "1200")),
        )

        def _live_backends() -> int:
            return sum(1 for i in api_idx if healths[i].up and workers_left.get(i, 0) > 0)

        async def watchdog() -> None:
            # Progress = completed backend calls, NOT just `scored`. A pass that is
            # working fine but grading nothing (basemap-only listings answer
            # condition_tier=null everywhere) must not be mistaken for a wedged
            # worker and aborted.
            last_seen, last_progress = -1, time.monotonic()
            while any(not t.done() for t in worker_tasks):
                await asyncio.sleep(hb_s)
                now = time.monotonic()
                live = _live_backends()
                rate = ymon.rate_per_hour(now, scored)
                log.info("vision.heartbeat", scored=scored, attempts=attempts["n"],
                         queue=queue.qsize(), live_workers=live,
                         banned=sum(1 for i in api_idx if healths[i].state == "open"),
                         disabled=sum(1 for i in api_idx if healths[i].state == "disabled"),
                         scored_per_hour=(round(rate) if rate is not None else None))
                if stop["reason"] is None:
                    why = ymon.update(live, scored, queue.qsize()) if yield_on else None
                    if why:
                        stop["reason"], stop["at"] = f"yield: {why}", now
                        log.warning("vision.yield_stop", reason=why, scored=scored,
                                    queue=queue.qsize(), live_workers=live)
                elif now - stop["at"] > stop_grace:
                    for t in worker_tasks:
                        t.cancel()
                    return
                if _deadline is not None and time.monotonic() > _deadline + stop_grace:
                    if stop["reason"] is None:
                        stop["reason"], stop["at"] = "wall_clock", now
                    log.warning("vision.deadline_abort", scored=scored, queue=queue.qsize())
                    for t in worker_tasks:
                        t.cancel()
                    return
                if attempts["n"] > last_seen:
                    last_seen, last_progress = attempts["n"], now
                elif now - last_progress > stall_limit:
                    stop["reason"] = stop["reason"] or "stalled"
                    log.warning("vision.stall_abort", scored=scored, queue=queue.qsize(),
                                idle_s=int(now - last_progress))
                    for t in worker_tasks:
                        t.cancel()
                    return

        wd = asyncio.create_task(watchdog())
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        wd.cancel()
        leftover = queue.qsize()

        if stop["reason"] is None and _past_deadline():
            stop["reason"] = "wall_clock"
        elapsed = time.monotonic() - run_started
        table = {}
        for i, b in enumerate(backends):
            h = healths[i]
            if is_floor[i] or (not h.attempts and not h.errors and h.state == "closed"):
                continue
            table[b.name] = {"state": h.state, "attempts": h.attempts, "ok": h.ok,
                             "errors": dict(h.errors), "trips": h.trips,
                             "readmissions": h.readmissions, "reason": h.reason}
            log.info("vision.backend_stats", backend=b.name, state=h.state, attempts=h.attempts,
                     ok=h.ok, errors=dict(h.errors), trips=h.trips,
                     readmissions=h.readmissions, reason=h.reason)
        _LAST_RUN = {"stop_reason": stop["reason"], "elapsed_s": round(elapsed, 1),
                     "scored": scored, "leftover": leftover, "backends": table,
                     "by_backend": dict(by_backend), "no_image": dropped["no_image"]}

    # Mixed-provider cost estimate (free pools = $0).
    cost = 0.0
    pr = _PROVIDER_PRICING
    cost += (total_in / 1_000_000) * pr.get("gemini", {}).get("in_per_mtok", 0)
    cost += (total_out / 1_000_000) * pr.get("gemini", {}).get("out_per_mtok", 0)
    log.info(
        "vision.done",
        targets=len(targets),
        scored=scored,
        ungraded=ungraded,          # answered but condition_tier null everywhere
        by_backend=by_backend,
        unscored_remaining=leftover,
        no_image=dropped["no_image"],       # skipped: no downloadable photo (dead URL or network)
        stop_reason=stop["reason"],
        elapsed_s=round(elapsed),
        overrides=overrides,
        input_tokens=total_in,
        output_tokens=total_out,
        estimated_cost_usd=round(cost, 4),
    )
