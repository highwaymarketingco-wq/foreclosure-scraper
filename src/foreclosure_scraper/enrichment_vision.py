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
# 4000 tokens: gemini-2.5-flash is wordier than 2.0-flash and 2000 was
# truncating the JSON mid-observation in ~17% of calls (parse_fail in
# run on 2026-05-13). 4000 covers the longest observed responses with
# room to spare. Still well inside the 250K TPM free-tier cap.
MAX_TOKENS = 4000
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

When the only photo is a basemap or generic Realtor placeholder (no actual property visible), set the JSON value of condition_tier to null (the literal null, not the text) and confidence to "LOW".

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
GROQ_MODEL = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")
GROQ_EXTRA_BODY = {"reasoning_effort": "none"}
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
    # --- 4/4 real tiers, well grounded (cite specifics from the actual photo) ---
    "nvidia/nemotron-nano-12b-v2-vl",                 # 8/8, ~9.6s. Best NIM lane.
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",  # 8/8, ~8.4s. Tied best.
    # --- net-new, verified this round ---
    "nvidia/ising-calibration-1.5-31b",               # 4/4, ~7.0s (fastest chat route)
    "thinkingmachines/inkling",                       # 4/4, ~18.5s. Was wrongly written
                                                      # off as a timeout; a 300s retry proved
                                                      # it fine. Pessimism bias (skews 'major').
    # --- meets the bar but biased; keep at the back of the rotation ---
    "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",        # 3/4, over-optimistic (move_in_ready)
    "meta/llama-3.2-90b-vision-instruct",             # 5/8, slow (~20s) but honest: returns
                                                      # LOW-confidence nulls rather than guessing
])).split(",") if m.strip()]
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
    """Raised by a backend when it hits its daily/rate quota (HTTP 429 /
    RESOURCE_EXHAUSTED). The pool catches this, retires that backend for the
    rest of the run, and re-queues the listing for another backend."""


def _is_quota_msg(msg: str) -> bool:
    msg = msg.lower()
    return ("429" in msg or "resource_exhausted" in msg or "quota" in msg
            or "exceeded" in msg or "rate limit" in msg)


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
    """One Gemini API key = one backend (one project's free quota)."""
    def __init__(self, key: str, idx: int):
        from google import genai
        self.client = genai.Client(api_key=key)
        self.name = f"gemini#{idx}"
        self.model = GEMINI_VISION_MODEL
        self.delay = INTER_CALL_DELAY
        self.cap = MAX_PHOTOS_PER_LISTING

    async def assess(self, li: Listing, payloads, urls) -> Optional[dict]:
        from google.genai import types as t
        parts = [t.Part.from_bytes(data=d, mime_type=m) for d, m in payloads[:self.cap]]
        prompt = f"{SYSTEM_PROMPT}\n\n{_user_prompt(li)}"
        try:
            resp = await self.client.aio.models.generate_content(
                model=self.model, contents=parts + [prompt],
                config=t.GenerateContentConfig(
                    max_output_tokens=MAX_TOKENS,
                    response_mime_type="application/json"),
            )
        except Exception as exc:
            if _is_quota_msg(str(exc)):
                raise QuotaExhausted(self.name)
            log.warning("vision.api_error", backend=self.name, source_url=li.source_url, error=str(exc)[:160])
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
                 extra_body: Optional[dict] = None):
        self.name = name
        self.url = url
        self.key = key
        self.model = model
        self.http = http
        self.cap = cap
        self.delay = delay
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
            r = await self.http.post(self.url, json=body, timeout=90.0,
                                     headers={"Authorization": f"Bearer {self.key}",
                                              "Content-Type": "application/json"})
        except Exception as exc:
            log.warning("vision.api_error", backend=self.name, source_url=li.source_url, error=str(exc)[:160])
            return None
        if r.status_code == 429:
            raise QuotaExhausted(self.name)
        if r.status_code >= 400:
            log.warning("vision.api_error", backend=self.name, status=r.status_code, error=r.text[:160])
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
            log.warning("vision.api_error", backend=self.name, source_url=li.source_url, error=str(exc)[:160])
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
            log.warning("vision.api_error", backend=self.name, source_url=li.source_url, error=str(exc)[:160])
            return None
        text = "\n".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        usage = None
        u = getattr(resp, "usage", None)
        if u:
            usage = {"input_tokens": getattr(u, "input_tokens", None),
                     "output_tokens": getattr(u, "output_tokens", None)}
        return _finalize(_parse_json_response(text), "anthropic", self.model,
                         len(blocks), urls, usage)


async def _build_backends(http: httpx.AsyncClient) -> list:
    """Assemble every available FREE vision backend (plus paid Anthropic only
    as a last resort). Order doesn't matter — all pull from one shared queue."""
    backends: list = []

    # Gemini — one backend per key (each key = one project's free quota).
    keys = _parse_gemini_keys()
    if keys:
        try:
            from google import genai  # noqa: F401
            for i, k in enumerate(keys, 1):
                try:
                    backends.append(_GeminiBackend(k, i))
                except Exception as exc:
                    log.warning("vision.backend_init_fail", backend=f"gemini#{i}", error=str(exc)[:120])
        except ImportError:
            log.warning("vision.sdk_missing", provider="gemini", hint="pip install google-genai")

    # GitHub Models — free, uses the gh token if GITHUB_MODELS_TOKEN/GITHUB_TOKEN set.
    # ONE LANE PER MODEL: GitHub rate-limits per model tier, so registering N verified
    # models gives N parallel free lanes instead of one (was a single gpt-4o-mini lane).
    gh = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if gh:
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
    mk = os.environ.get("MISTRAL_API_KEY")
    if mk:
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
            backends.append(_OpenAICompatBackend(f"nvidia:{short}", NVIDIA_URL, nv, m,
                                                 http, cap=1, delay=2.0))

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

    # Anthropic — paid; only as a fallback when nothing free is configured.
    if not backends and os.environ.get("ANTHROPIC_API_KEY"):
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


async def enrich_with_vision(listings: list[Listing], max_listings: int | None = None) -> None:
    """Run vision condition assessment on listings with usable imagery.
    Overrides condition_tier with the photo-derived value when confidence
    is HIGH or MEDIUM.

    Provider selection via VISION_PROVIDER env:
      - "anthropic" (default): Claude Sonnet 4.5, ~$0.01-0.03/listing
      - "gemini": Gemini 2.0 Flash, FREE on -exp model up to 1500 req/day
    Caller controls budget by max_listings.

    Already-scored leads are skipped (idempotent) unless VISION_REGRADE_SCORED=1
    — see _needs_vision.
    """
    targets = [li for li in listings if _needs_vision(li)]
    # Prioritize the most actionable listings for the (free-quota-bounded)
    # Vision budget: soonest sale date first, then never-scored leads, then
    # listings with an opening bid (real auctions), so the cap covers the best
    # leads — not whatever happened to be first.
    #
    # The never-scored key sits BELOW sale date on purpose. Dated leads keep
    # exact date order (an imminent sale that gained photos since last week
    # still gets re-read), but the huge date-less tail — where most of the
    # board lives — spends the cap on leads that have NO condition read yet
    # instead of re-grading ones that already do. That is what turns a raised
    # cap into new coverage rather than repeat work.
    def _vpri(li: Listing):
        from datetime import datetime as _dt
        sd = li.sale_date
        if sd is not None and hasattr(sd, "tzinfo") and sd.tzinfo is not None:
            sd = sd.replace(tzinfo=None)
        has_date = 0 if sd else 1
        raw = li.raw if isinstance(li.raw, dict) else {}
        already_scored = 1 if raw.get("vision") else 0
        return (has_date, sd or _dt.max, already_scored,
                0 if li.opening_bid else 1)
    targets.sort(key=_vpri)
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

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
        backends = await _build_backends(http)
        if not backends:
            log.warning("vision.no_backends",
                        hint="set GEMINI_API_KEY_n / GITHUB_MODELS_TOKEN / GROQ_API_KEY, or run Ollama")
            return
        log.info("vision.pool_built", backends=[b.name for b in backends], count=len(backends))

        # One SHARED queue; one worker per backend. When a backend hits its
        # quota it retires and re-queues its in-flight listing, so the other
        # backends pick up the slack — no quota share is wasted.
        queue: asyncio.Queue = asyncio.Queue()
        for li in targets:
            queue.put_nowait(li)

        # Cooldown/strikes: a 429 is often a PER-MINUTE limit (Groq, GitHub),
        # not a daily cap. So on 429 we re-queue the listing, sleep a cooldown,
        # and let the SAME backend rejoin — only retiring it after STRIKES
        # consecutive 429s with no success in between. A success resets strikes,
        # so a per-minute-limited backend keeps contributing all run; a truly
        # daily-exhausted one (e.g. a spent Gemini key) retires after STRIKES.
        cooldown = float(os.environ.get("VISION_BACKEND_COOLDOWN", "60"))
        max_strikes = int(os.environ.get("VISION_BACKEND_STRIKES", "2"))
        # Per-listing hard timeout — a single stuck network await (hung image
        # fetch or provider call whose own timeout doesn't fire) must never
        # freeze a worker. On timeout we drop that listing (re-scored next run)
        # and move on. Covers fetch(≤15s) + provider POST(≤90s) with margin.
        item_timeout = float(os.environ.get("VISION_ITEM_TIMEOUT", "150"))

        # HARD failures (410 end-of-life, 404 unknown model, unparseable reply,
        # item timeout) are NOT quota problems, so the cooldown/strike path
        # above never saw them. Before this block they fell straight through to
        # _apply2(li, None) and the listing was DROPPED for the whole run — one
        # dead backend permanently ate one queue slot per failure. The
        # 2026-07-27 pass lost 1,222 of 1,500 slots that way (only 278 scored)
        # because 7 retired NIM models + a 404 Groq model kept eating the queue.
        #
        # Two bounded guards fix it:
        #   1. Re-queue a hard-failed listing so a HEALTHY backend can still
        #      score it — at most VISION_MAX_REQUEUE times, so a fully dead
        #      pool can never loop forever.
        #   2. Retire the backend after VISION_BACKEND_HARD_FAILS CONSECUTIVE
        #      hard failures (a success resets the counter), mirroring the
        #      quota strike system. This is what stops a 410 model from eating
        #      the queue at all.
        #
        # The budget is PER-BACKEND, not global. A global 1+2 budget was still
        # losing listings: INTERMITTENT lanes (verified live — mistral-medium-
        # 3.5-128b answered 1 of 4 real calls, llama-3.2-11b-vision 3 of 4)
        # never rack up max_hard_fails CONSECUTIVE failures, so they never
        # retire and keep drawing work; three bounces off flaky lanes burned a
        # listing's whole budget while a HEALTHY backend sat idle right there
        # (60-listing stress test scored only 57).
        #
        # Rule: each backend may attempt a given listing ONCE, plus
        # VISION_MAX_REQUEUE extra retries once every live lane has had its
        # turn. So for every listing
        #     attempts <= len(backends) + VISION_MAX_REQUEUE
        # which is finite and independent of how flaky any lane is. A fully
        # dead pool still terminates twice over, because each backend also
        # retires after max_hard_fails consecutive hard failures.
        max_requeue = int(os.environ.get("VISION_MAX_REQUEUE", "2"))
        max_hard_fails = int(os.environ.get("VISION_BACKEND_HARD_FAILS", "5"))

        # Per-listing state keyed by id(li). id() is the one key that is unique
        # BY CONSTRUCTION here: `targets` holds a strong reference to every
        # listing for the whole call, so no id can be recycled mid-run and two
        # distinct listings can never collide. Do NOT be tempted to key this by
        # source_url — 652 source_urls are shared by 19,392 board leads (one
        # ArcGIS URL by 3,293), so a url-keyed budget would let one lead spend
        # thousands of others' attempts. See test_attempt_budget_key_is_per_object.
        tried: dict[int, set[int]] = {}       # id(li) -> backend indexes that ran it
        tries: dict[int, int] = {}            # id(li) -> attempts spent (the hard cap)
        attempt_cap = len(backends) + max_requeue
        # API-backend indexes still able to take work; a retired or finished
        # worker drops out, so "another lane could serve this listing" never
        # counts a lane that is already gone. Floor lanes are deliberately NOT
        # in here: a floor worker sits idle until every API worker has exited,
        # so counting it as "a lane that will come for this listing" would park
        # the API lanes waiting for a worker that is itself waiting for them.
        live_idx: set[int] = {i for i, b in enumerate(backends)
                              if not getattr(b, "is_floor", False)}
        # Listings the API pool exhausted its attempts on, held for the floor
        # (None when no floor backend is configured, so they are given up on).
        floor_pending: Optional[list[Listing]] = (
            [] if any(getattr(b, "is_floor", False) for b in backends) else None)
        attempts = {"n": 0}                   # completed backend calls (watchdog progress)

        def _requeue(li: Listing, idx: int) -> bool:
            """Put a failed/ungraded listing back on the queue if attempts are
            left. Returns True if re-queued.

            One flat cap — len(backends) + VISION_MAX_REQUEUE — is what makes
            the bound provable no matter how the pool hands the listing around:
            one turn per lane plus a few spares. The pop-side preference below
            is what keeps the spares from being spent on the same lane twice.
            """
            k = id(li)
            if tries.get(k, 0) >= attempt_cap:
                return False
            queue.put_nowait(li)
            return True

        # ...and on the pop side, PREFER a listing this lane hasn't tried. The
        # scan is bounded (never walks the whole queue — it can be 19k items),
        # defers at most scan_limit-1 items to the back, and never drops one,
        # so it cannot livelock or CPU-spin.
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
                # repeat for a listing no other live lane could serve better —
                # that lane will pop it on its own next tick.
                for i, li in enumerate(deferred):
                    seen = tried.get(id(li)) or set()
                    if not any(j not in seen for j in live_idx if j != idx):
                        chosen = deferred.pop(i)
                        break
            for d in deferred:
                queue.put_nowait(d)
            return chosen

        # An empty queue does NOT mean the run is over: another worker may still
        # be mid-call (or in its inter-call delay) on a listing that is about to
        # be re-queued. If the fast HEALTHY lane exits at that moment, the
        # re-queued listing is left to the flaky lanes only — the exact way work
        # goes missing. So a worker with nothing to pop idles while any peer is
        # still holding an item, and only re-attempts a listing it has already
        # tried once the whole pool has gone idle (i.e. no lane that hasn't
        # tried it is coming). Terminating: every queued listing still has
        # attempts left by construction, total attempts are capped, and each
        # holder finishes within item_timeout — so inflight reaches 0, the queue
        # drains, and every idler exits. The sleep keeps it off the CPU.
        inflight = {"n": 0}
        idle_tick = float(os.environ.get("VISION_IDLE_TICK", "0.05"))

        async def _next(idx: int) -> Optional[Listing]:
            idle_ticks = 0
            while True:
                li = _take(idx, allow_repeat=(inflight["n"] <= 0 and idle_ticks >= 2))
                if li is not None:
                    return li
                if _past_deadline():
                    return None
                if queue.empty() and inflight["n"] <= 0:
                    return None
                await asyncio.sleep(idle_tick)
                idle_ticks = idle_ticks + 1 if inflight["n"] <= 0 else 0

        # Optional wall-clock cap so a long run (esp. the slow local floor)
        # can't overrun into the next scheduled pass. 0 = unlimited.
        import time as _time
        _budget = float(os.environ.get("VISION_MAX_SECONDS", "0") or 0)
        _deadline = (_time.monotonic() + _budget) if _budget > 0 else None

        def _past_deadline() -> bool:
            return _deadline is not None and _time.monotonic() > _deadline

        # Floor backends (Ollama) are low-quality local fallbacks. They must
        # only score what the API pools COULDN'T this run — otherwise they'd
        # race ahead (no cooldown) and poison listings with weak scores that
        # block a good provider from scoring them on a future day. So a floor
        # worker waits until every API backend has retired, then drains the rest.
        api_active = {"n": sum(1 for b in backends if not getattr(b, "is_floor", False))}

        async def api_worker(backend, idx: int) -> None:
            strikes = 0
            hard_fails = 0
            holding = False
            try:
                while True:
                    # Release the previous item BEFORE asking for the next one,
                    # so a worker never counts itself as in-flight while idling.
                    if holding:
                        inflight["n"] -= 1
                        holding = False
                    if _past_deadline():
                        return
                    li = await _next(idx)
                    if li is None:
                        return
                    inflight["n"] += 1
                    holding = True
                    res = None
                    try:
                        payloads, urls = await asyncio.wait_for(
                            _fetch_image_blocks(li, http), timeout=item_timeout)
                        if not payloads:
                            continue
                        res = await asyncio.wait_for(
                            backend.assess(li, payloads, urls), timeout=item_timeout)
                        strikes = 0
                    except QuotaExhausted:
                        strikes += 1
                        # Nothing was assessed, so this does NOT spend one of
                        # the listing's per-backend attempts.
                        queue.put_nowait(li)
                        if strikes >= max_strikes:
                            log.info("vision.backend_retired", backend=backend.name,
                                     strikes=strikes, remaining=queue.qsize())
                            return
                        log.info("vision.backend_cooldown", backend=backend.name,
                                 strikes=strikes, cooldown_s=cooldown, remaining=queue.qsize())
                        await asyncio.sleep(cooldown)
                        continue
                    except asyncio.TimeoutError:
                        log.warning("vision.item_timeout", backend=backend.name, remaining=queue.qsize())
                    except Exception as exc:
                        log.warning("vision.worker_error", backend=backend.name, error=str(exc)[:140])
                    # This lane has now had its turn at this listing.
                    tried.setdefault(id(li), set()).add(idx)
                    tries[id(li)] = tries.get(id(li), 0) + 1
                    attempts["n"] += 1
                    if res is not None:
                        # The call went through and parsed, so the lane is
                        # ALIVE even if it declined to grade the property.
                        hard_fails = 0
                        if _canonical_tier(res):
                            _apply2(li, res)
                        elif not _requeue(li, idx):
                            # Every live lane declined — keep the report as a
                            # diagnostic but leave the lead formally un-scored.
                            log.info("vision.listing_ungraded", backend=backend.name,
                                     source_url=li.source_url)
                            _record_ungraded(li, res)
                    else:
                        # HARD failure (410/404/parse-fail/timeout). Hand the
                        # listing to another backend instead of dropping it,
                        # and count a strike against THIS backend.
                        hard_fails += 1
                        if not _requeue(li, idx):
                            if floor_pending is not None:
                                # The local floor exists precisely to finish what
                                # the API pool could not. Park it there (once —
                                # the floor never re-queues) instead of on the
                                # shared queue, which the API lanes would keep
                                # popping past their attempt cap.
                                floor_pending.append(li)
                            else:
                                log.info("vision.listing_given_up", backend=backend.name,
                                         source_url=li.source_url,
                                         attempts=tries.get(id(li), 0),
                                         lanes=len(tried.get(id(li)) or ()))
                                _apply2(li, None)
                        if hard_fails >= max_hard_fails:
                            log.info("vision.backend_retired_hard", backend=backend.name,
                                     hard_fails=hard_fails, remaining=queue.qsize())
                            return
                    if getattr(backend, "delay", 0):
                        await asyncio.sleep(backend.delay)
            finally:
                if holding:
                    inflight["n"] -= 1
                live_idx.discard(idx)
                api_active["n"] -= 1

        async def floor_worker(backend, idx: int) -> None:
            # Wait for the API pools to finish; bail early if they drain it all
            # AND left nothing parked for the floor.
            while api_active["n"] > 0:
                if queue.empty() and not floor_pending:
                    return
                await asyncio.sleep(3)
            log.info("vision.floor_active", backend=backend.name,
                     remaining=queue.qsize(), parked=len(floor_pending or ()))
            while True:
                if _past_deadline():
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

        worker_tasks = [
            asyncio.create_task(
                floor_worker(b, i) if getattr(b, "is_floor", False) else api_worker(b, i))
            for i, b in enumerate(backends)
        ]

        # Heartbeat + no-progress watchdog. Even a single wedged worker (sync
        # block / pool-wait that freezes the loop between item-timeouts) used to
        # stall the whole run silently. This logs progress every 60s and, if
        # `scored` hasn't advanced for VISION_STALL_SECONDS, cancels the workers
        # so the run finishes and publishes whatever it has.
        stall_limit = float(os.environ.get("VISION_STALL_SECONDS", "360"))

        async def watchdog() -> None:
            # Progress = completed backend calls, NOT just `scored`. A pass that
            # is working fine but grading nothing (basemap-only listings answer
            # condition_tier=null everywhere) must not be mistaken for a wedged
            # worker and aborted.
            last_seen, last_progress = -1, _time.monotonic()
            while any(not t.done() for t in worker_tasks):
                await asyncio.sleep(60)
                log.info("vision.heartbeat", scored=scored, attempts=attempts["n"],
                         queue=queue.qsize(),
                         live_workers=sum(1 for t in worker_tasks if not t.done()))
                if attempts["n"] > last_seen:
                    last_seen, last_progress = attempts["n"], _time.monotonic()
                elif _time.monotonic() - last_progress > stall_limit:
                    log.warning("vision.stall_abort", scored=scored, queue=queue.qsize(),
                                idle_s=int(_time.monotonic() - last_progress))
                    for t in worker_tasks:
                        t.cancel()
                    return

        wd = asyncio.create_task(watchdog())
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        wd.cancel()
        leftover = queue.qsize()

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
        overrides=overrides,
        input_tokens=total_in,
        output_tokens=total_out,
        estimated_cost_usd=round(cost, 4),
    )
