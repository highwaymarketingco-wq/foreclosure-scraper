"""Claude Vision condition assessment.

For every listing with usable imagery, sends the photos to Claude Sonnet 4.5
with a flipper-trained prompt and gets back a structured condition assessment:
  - condition_tier: move_in_ready / cosmetic / major / gut
  - confidence: HIGH / MEDIUM / LOW
  - per-component observations (roof, exterior, windows, yard, structural)
  - rehab $/sqft range adjusted from photo evidence
  - red_flags + positive_signs lists
  - vision_summary: 2-3 sentence flipper assessment

Replaces the regex/age-based condition tier with grounded visual signal
when photos exist. Costs ~$0.01-0.03 per listing depending on photo count.
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


VISION_MODEL = "claude-sonnet-4-5-20250929"
MAX_PHOTOS_PER_LISTING = 7   # up to 5 real + aerial + street
MAX_REAL_PHOTOS = 5          # how many of the listing photos to send
MAX_TOKENS = 1000            # bumped to fit richer multi-photo observations
# Concurrency configurable so the retry pass can throttle harder than the main run
CONCURRENCY = int(os.environ.get("VISION_CONCURRENCY", "4"))
INTER_CALL_DELAY = float(os.environ.get("VISION_INTER_CALL_DELAY", "0.0"))


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


async def _assess_one(client, li: Listing, http: httpx.AsyncClient) -> Optional[dict]:
    """Run Claude Vision on one listing. Returns the parsed JSON or None."""
    urls = _select_image_urls(li)
    if not urls:
        return None

    # Download images in parallel
    image_blocks: list[dict] = []
    fetches = await asyncio.gather(*(_fetch_image_bytes(http, u) for u in urls))
    for fetched in fetches:
        if not fetched:
            continue
        data, media_type = fetched
        image_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(data).decode("ascii"),
            },
        })

    if not image_blocks:
        return None

    user_text = _user_prompt(li)
    content = image_blocks + [{"type": "text", "text": user_text}]

    try:
        resp = await client.messages.create(
            model=VISION_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        log.warning("vision.api_error", source_url=li.source_url, error=str(exc)[:200])
        return None

    # Extract text from response
    text_chunks = [b.text for b in resp.content if hasattr(b, "text")]
    raw_text = "\n".join(text_chunks).strip()
    parsed = _parse_json_response(raw_text)
    if not parsed:
        log.debug("vision.parse_fail", text=raw_text[:200])
        return None

    # Token usage for cost tracking
    usage = getattr(resp, "usage", None)
    if usage:
        parsed["_usage"] = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
    parsed["_n_photos"] = len(image_blocks)
    parsed["_image_urls"] = urls
    return parsed


async def enrich_with_vision(listings: list[Listing], max_listings: int | None = None) -> None:
    """Run Claude Vision on listings with usable imagery. Overrides condition_tier
    with the photo-derived value when confidence is HIGH.

    Cost: ~$0.01-0.03 per listing. Caller controls budget by max_listings.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("vision.no_api_key", hint="set ANTHROPIC_API_KEY to enable")
        return

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        log.warning("vision.sdk_missing", hint="pip install anthropic")
        return

    targets = [li for li in listings if _select_image_urls(li)]
    if max_listings:
        targets = targets[:max_listings]
    if not targets:
        log.info("vision.no_targets")
        return

    log.info("vision.start", target_count=len(targets), of_total=len(listings))

    # max_retries=6 gives the SDK headroom for 429s with exponential backoff
    client = AsyncAnthropic(api_key=api_key, max_retries=6, timeout=90.0)
    sem = asyncio.Semaphore(CONCURRENCY)
    overrides = 0
    total_in = total_out = 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as http:

        async def one(li: Listing) -> None:
            nonlocal overrides, total_in, total_out
            async with sem:
                result = await _assess_one(client, li, http)
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

    # Cost estimate (Sonnet 4.5: $3/Mtok in, $15/Mtok out)
    cost = (total_in / 1_000_000 * 3.0) + (total_out / 1_000_000 * 15.0)
    log.info(
        "vision.done",
        targets=len(targets),
        overrides=overrides,
        input_tokens=total_in,
        output_tokens=total_out,
        estimated_cost_usd=round(cost, 2),
    )
