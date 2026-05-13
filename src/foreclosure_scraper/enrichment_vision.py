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
    for i in range(1, 11):
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
