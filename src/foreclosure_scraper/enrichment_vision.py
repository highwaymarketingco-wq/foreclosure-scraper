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
import re
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()


# Provider selection — default to Anthropic for backwards compat
VISION_PROVIDER = os.environ.get("VISION_PROVIDER", "anthropic").lower().strip()

# Anthropic settings
ANTHROPIC_VISION_MODEL = "claude-sonnet-4-5-20250929"
# Legacy alias kept for any external imports
VISION_MODEL = ANTHROPIC_VISION_MODEL

# Gemini settings — gemini-1.5-flash chosen for free-tier headroom.
# Verified pricing/quota 2026-05-08:
#   gemini-1.5-flash: 15 RPM / 1M TPM / 1500 RPD (free tier — fits us)
#   gemini-2.5-flash: 10 RPM /  250 RPD (free tier — too tight; we hit
#                                        429 RESOURCE_EXHAUSTED in run #6)
#   gemini-2.0-flash-exp: deprecated, returns 404
# Override via GEMINI_VISION_MODEL env. Paid tier on any of these has
# 2000 RPM / no daily cap.
GEMINI_VISION_MODEL = os.environ.get(
    "GEMINI_VISION_MODEL", "gemini-1.5-flash"
)

MAX_PHOTOS_PER_LISTING = 7   # up to 5 real + aerial + street
MAX_REAL_PHOTOS = 5          # how many of the listing photos to send
# 2000 tokens needed for multi-photo observations: 1000 was truncating
# the structured JSON output mid-key, causing parse_fail in run #6.
MAX_TOKENS = 2000
# Free-tier-safe defaults: 1 in-flight + 6s delay = 10 RPM. Override
# both via env when on a paid tier with higher limits.
CONCURRENCY = int(os.environ.get("VISION_CONCURRENCY", "1"))
INTER_CALL_DELAY = float(os.environ.get("VISION_INTER_CALL_DELAY", "6.0"))


SYSTEM_PROMPT = """You are an experienced real-estate flipper assessing renovation needs from listing photos and aerial views. You make accurate cost-aware judgments grounded in what the photos actually show, not optimistic guesses.

Rehab tiers (Carolina market, 2026 dollars):
- move_in_ready: $5-20/sqft. Minor paint/carpet/cleaning at most. Property looks ready to occupy.
- cosmetic: $15-45/sqft. Paint, flooring, minor kitchen/bath updates, light landscaping. No major systems work.
- major: $35-80/sqft. Significant interior rehab + some systems work (HVAC, roof patching, plumbing fixtures). Cosmetic done top-to-bottom.
- gut: $110-220/sqft. Down to studs, full systems replacement, foundation/roof/structural work, possible additions. Property is uninhabitable as-is.

When the only photo is a basemap or generic Realtor placeholder (no actual property visible), return condition_tier=null and confidence=LOW.

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
        return data, media_type
    except Exception:
        return None


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
    """Anthropic models sometimes wrap JSON in fences. Strip + parse."""
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find first {...} block
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
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
        log.warning("vision.api_error", provider="anthropic", source_url=li.source_url, error=str(exc)[:200])
        return None

    text_chunks = [b.text for b in resp.content if hasattr(b, "text")]
    raw_text = "\n".join(text_chunks).strip()
    parsed = _parse_json_response(raw_text)
    if not parsed:
        log.debug("vision.parse_fail", provider="anthropic", text=raw_text[:200])
        return None

    usage = getattr(resp, "usage", None)
    if usage:
        parsed["_usage"] = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
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
        log.warning("vision.api_error", provider="gemini", source_url=li.source_url, error=str(exc)[:200])
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


def _build_gemini_client():
    """Set up Gemini client. Returns (client, assess_fn) or (None, None).
    Uses the supported google-genai SDK; the old google-generativeai
    package is deprecated."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.warning("vision.no_api_key", provider="gemini", hint="set GEMINI_API_KEY (mint at https://aistudio.google.com/apikey)")
        return None, None
    try:
        from google import genai
    except ImportError:
        log.warning("vision.sdk_missing", provider="gemini", hint="pip install google-genai")
        return None, None
    client = genai.Client(api_key=api_key)
    return client, _assess_one_gemini


# Pricing per 1M tokens for cost estimate logging. Anthropic: Sonnet 4.5
# $3 in / $15 out. Gemini-2.0-flash: $0.075 in / $0.30 out (paid tier).
# gemini-2.0-flash-exp is currently free; the math still produces a non-zero
# "what it would have cost" estimate which is useful for capacity planning.
_PROVIDER_PRICING = {
    "anthropic": {"in_per_mtok": 3.0, "out_per_mtok": 15.0},
    "gemini": {"in_per_mtok": 0.075, "out_per_mtok": 0.30},
}


async def enrich_with_vision(listings: list[Listing], max_listings: int | None = None) -> None:
    """Run vision condition assessment on listings with usable imagery.
    Overrides condition_tier with the photo-derived value when confidence
    is HIGH or MEDIUM.

    Provider selection via VISION_PROVIDER env:
      - "anthropic" (default): Claude Sonnet 4.5, ~$0.01-0.03/listing
      - "gemini": Gemini 2.0 Flash, FREE on -exp model up to 1500 req/day
    Caller controls budget by max_listings.
    """
    if VISION_PROVIDER == "gemini":
        client, assess_fn = _build_gemini_client()
    else:
        client, assess_fn = _build_anthropic_client()
    if client is None or assess_fn is None:
        return

    targets = [li for li in listings if _select_image_urls(li)]
    if max_listings:
        targets = targets[:max_listings]
    if not targets:
        log.info("vision.no_targets", provider=VISION_PROVIDER)
        return

    log.info(
        "vision.start",
        provider=VISION_PROVIDER,
        target_count=len(targets),
        of_total=len(listings),
    )

    sem = asyncio.Semaphore(CONCURRENCY)
    overrides = 0
    total_in = total_out = 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as http:

        async def one(li: Listing) -> None:
            nonlocal overrides, total_in, total_out
            async with sem:
                result = await assess_fn(client, li, http)
                if INTER_CALL_DELAY > 0:
                    await asyncio.sleep(INTER_CALL_DELAY)
            if not result:
                return
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["vision"] = result
            usage = result.pop("_usage", None) or {}
            total_in += usage.get("input_tokens", 0) or 0
            total_out += usage.get("output_tokens", 0) or 0

            # Override condition_tier when Vision confidence is HIGH or MEDIUM
            ct = result.get("condition_tier")
            conf = (result.get("confidence") or "").upper()
            if ct in ("move_in_ready", "cosmetic", "major", "gut") and conf in ("HIGH", "MEDIUM"):
                old = li.raw.get("condition_tier")
                li.raw["condition_tier"] = ct
                li.raw["condition_source"] = f"vision-{conf}"
                if old != ct:
                    overrides += 1

        await asyncio.gather(*(one(li) for li in targets))

    pricing = _PROVIDER_PRICING.get(VISION_PROVIDER, _PROVIDER_PRICING["anthropic"])
    cost = (total_in / 1_000_000 * pricing["in_per_mtok"]) + (
        total_out / 1_000_000 * pricing["out_per_mtok"]
    )
    log.info(
        "vision.done",
        provider=VISION_PROVIDER,
        targets=len(targets),
        overrides=overrides,
        input_tokens=total_in,
        output_tokens=total_out,
        estimated_cost_usd=round(cost, 4),
    )
