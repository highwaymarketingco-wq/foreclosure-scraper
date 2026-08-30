"""Document OCR enrichment — pull the buried owner name + property address
out of scanned legal-notice / foreclosure / tax / probate / lis-pendens
documents (FREE, Gemini-first).

The Reddit market insight: county systems (Aumentum tax portals, Odyssey,
Register-of-Deeds imaging) leave the structured name/address FIELDS blank —
the real lead is printed inside the SCANNED IMAGE of the notice. Run that
image (or PDF) through vision OCR and the defendant + subject property fall
out. Same idea recovers the dollar amount off a recorded lien whose index
row carries no value.

Provider order is FREE-first and quota-rotating, mirroring
enrichment_vision: Gemini (one backend per API key = one project's free
quota) -> GitHub Models -> Groq. Anthropic is deliberately NOT used here
(paid). Text-layer PDFs skip vision entirely: pdfplumber lifts the text
locally and a tiny Gemini text call parses it (cheap), so we only spend
vision tokens on genuinely scanned pages.

Writes raw['doc_ocr'] = {owner_name, co_owner_name, property_address,
city, state, zip, sale_date, amount, case_number, doc_type, _provider}.
Backfills li.defendant / street_address / city / state / zip_code /
case_number / judgment_amount ONLY when they are blank — never clobbers a
value a scraper already parsed. Idempotent (skips leads already carrying
raw['doc_ocr'] unless FORECLOSURE_DOC_OCR_FORCE=1), budget-bounded, gated.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from typing import Iterable, Optional

import httpx
import structlog

from .http_client import client as http_client
from .models import Listing
from .enrichment_vision import (
    _parse_gemini_keys,
    _parse_json_response,
    GEMINI_VISION_MODEL,
    GITHUB_MODELS_URL,
    GITHUB_MODELS_MODEL,
    GROQ_URL,
    GROQ_MODEL,
    NVIDIA_URL,
    NVIDIA_VISION_MODELS,
    MISTRAL_URL,
    MISTRAL_VISION_MODELS,
)

log = structlog.get_logger(__name__)

# --- Anthropic Claude vision OCR --------------------------------------------
# Claude uses a different API shape (messages, not chat/completions) so it
# needs its own caller. Only used as a last-resort fallback when all free
# providers are quota-exhausted — costs ~$0.01-0.03/call.
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-20250514")

async def _anthropic_call(http: httpx.AsyncClient, key: str,
                          blocks: list, text: Optional[str] = None) -> Optional[dict]:
    """One Anthropic Claude vision call for doc OCR. blocks = [(bytes, mime)]."""
    content = []
    if text:
        content.append({"type": "text", "text": f"{OCR_PROMPT}\n\nDOCUMENT TEXT:\n{text}"})
    else:
        content.append({"type": "text", "text": OCR_PROMPT})
        for d, m in (blocks or []):
            b64 = base64.b64encode(d).decode("ascii")
            media = "image/jpeg" if not m.startswith("image/") else m
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": media, "data": b64}})
    body = {"model": ANTHROPIC_MODEL, "max_tokens": 1500,
            "messages": [{"role": "user", "content": content}]}
    try:
        r = await http.post(ANTHROPIC_URL, json=body, timeout=90.0,
                            headers={"x-api-key": key,
                                     "anthropic-version": "2023-06-01",
                                     "Content-Type": "application/json"})
    except Exception as exc:
        log.warning("doc_ocr.anthropic_error", error=str(exc)[:160])
        return None
    if r.status_code == 429:
        raise _QuotaOut("anthropic")
    if r.status_code >= 400:
        log.warning("doc_ocr.anthropic_error", status=r.status_code, error=r.text[:120])
        return None
    try:
        txt = r.json()["content"][0]["text"]
        parsed = _parse_json_response(txt)
    except Exception:
        return None
    if parsed is not None:
        parsed["_provider"] = "anthropic"
    return parsed

# --- gating / budgets -------------------------------------------------------
DOC_OCR_ENABLED = os.environ.get("FORECLOSURE_DOC_OCR", "1") != "0"
DOC_OCR_FORCE = os.environ.get("FORECLOSURE_DOC_OCR_FORCE", "0") == "1"
DOC_OCR_MAX = int(os.environ.get("DOC_OCR_MAX", "400"))
DOC_OCR_BUDGET_S = float(os.environ.get("DOC_OCR_BUDGET_S", "600"))
# A document URL shared across MORE than this many leads is an AGGREGATE LIST
# (a county tax-advertisement PDF, a MIE sale roster) — not a per-property
# notice. OCRing it per-lead would burn quota and stamp the list's top row onto
# every lead, so those are skipped. Per-property scanned notices (one distinct
# doc per lead, e.g. Column/Cloudinary enotice images) are kept.
DOC_OCR_MAX_SHARE = int(os.environ.get("DOC_OCR_MAX_SHARE", "3"))
DOC_OCR_MODEL = os.environ.get("DOC_OCR_MODEL", GEMINI_VISION_MODEL)
_MAX_DOC_BYTES = 12 * 1024 * 1024   # notices/deeds are small; cap defensively
_MAX_PDF_TEXT_CHARS = 20000

_DOC_EXT = (".pdf", ".tif", ".tiff", ".jpg", ".jpeg", ".png", ".gif", ".bmp")
# raw[] fields a scraper might stash a document/notice image or PDF under.
_DOC_FIELDS = (
    "document_url", "doc_url", "notice_url", "notice_image", "doc_image",
    "instrument_image", "instrument_url", "pdf_url", "image_url", "scan_url",
    "recorded_document_url", "deed_url", "source_pdf", "documents",
)

OCR_PROMPT = (
    "You are reading ONE United States legal/property document: a foreclosure "
    "or tax-sale notice, lis pendens, notice to creditors / probate estate "
    "filing, or a recorded deed/mortgage/lien. Extract ONLY what is explicitly "
    "printed. Return STRICT JSON with these keys (use null when absent, never "
    "guess):\n"
    '  "owner_name": the DEFENDANT / property owner / borrower / decedent — the '
    "PERSON or estate the document is about. NOT the plaintiff, bank, lender, "
    "trustee, attorney, county, or clerk.\n"
    '  "co_owner_name": a second owner/defendant if listed, else null.\n'
    '  "property_address": street address of the SUBJECT property (the real '
    "estate at issue), not a mailing address for the attorney/court.\n"
    '  "city": subject property city.\n'
    '  "state": 2-letter state.\n'
    '  "zip": 5-digit zip.\n'
    '  "sale_date": scheduled sale/hearing date as printed (YYYY-MM-DD if '
    "possible).\n"
    '  "amount": the single most relevant DOLLAR figure — judgment, debt, '
    "opening/upset bid, tax due, or secured lien amount — as a number without "
    "$ or commas.\n"
    '  "case_number": docket/case/file number if present.\n'
    '  "doc_type": one short label, e.g. "foreclosure_notice", "tax_sale", '
    '"lis_pendens", "probate_notice", "deed_of_trust", "lien".\n'
    "Output the JSON object only, no prose."
)


# --- document discovery -----------------------------------------------------
def _doc_urls(li: Listing) -> list[str]:
    """Candidate document URLs on this lead, best first. Returns [] if none."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    out: list[str] = []
    for f in _DOC_FIELDS:
        v = raw.get(f)
        if isinstance(v, str) and v.startswith("http"):
            out.append(v)
        elif isinstance(v, list):
            out.extend(u for u in v if isinstance(u, str) and u.startswith("http"))
    su = getattr(li, "source_url", None) or ""
    if isinstance(su, str) and su.lower().split("?")[0].endswith(_DOC_EXT):
        out.append(su)
    # de-dupe, keep order, cap to 1 (one document is enough; saves quota)
    seen: set[str] = set()
    uniq = [u for u in out if not (u in seen or seen.add(u))]
    return uniq[:1]


async def _fetch_doc(c: httpx.AsyncClient, url: str) -> Optional[tuple[bytes, str]]:
    """Download a document, preserving PDF vs image mime. None on failure."""
    try:
        r = await c.get(url, timeout=20.0, follow_redirects=True)
        if r.status_code != 200 or not r.content:
            return None
        mime = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        data = r.content[:_MAX_DOC_BYTES]
        if not mime:
            mime = "application/pdf" if data[:4] == b"%PDF" else "image/jpeg"
        return data, mime
    except Exception:
        return None


def _pdf_text(data: bytes) -> Optional[str]:
    """Lift the text layer from a PDF (first 3 pages). Returns None if the PDF
    is scanned (no meaningful text) or unreadable — caller then OCRs it."""
    try:
        import io
        import pdfplumber
        chunks: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages[:3]:
                t = page.extract_text() or ""
                if t:
                    chunks.append(t)
        text = "\n".join(chunks).strip()
        return text[:_MAX_PDF_TEXT_CHARS] if len(text) >= 200 else None
    except Exception:
        return None


# --- provider calls (free-first, quota-rotating) ----------------------------
class _QuotaOut(Exception):
    pass


def _is_quota(msg: str) -> bool:
    m = msg.lower()
    return any(s in m for s in ("quota", "rate limit", "429", "resource_exhausted",
                                "exceeded", "too many requests"))


async def _gemini_call(key: str, parts_or_text, is_text: bool) -> Optional[dict]:
    """One Gemini generate_content call. `parts_or_text` is the extracted PDF
    text (is_text=True) or a list of (bytes, mime) document blocks."""
    try:
        from google import genai
        from google.genai import types as t
    except ImportError:
        return None
    client = genai.Client(api_key=key)
    if is_text:
        contents = [f"{OCR_PROMPT}\n\nDOCUMENT TEXT:\n{parts_or_text}"]
    else:
        contents = [t.Part.from_bytes(data=d, mime_type=m) for d, m in parts_or_text]
        contents.append(OCR_PROMPT)
    try:
        resp = await client.aio.models.generate_content(
            model=DOC_OCR_MODEL, contents=contents,
            config=t.GenerateContentConfig(
                max_output_tokens=1500, response_mime_type="application/json"),
        )
    except Exception as exc:
        if _is_quota(str(exc)):
            raise _QuotaOut(key[:8])
        log.warning("doc_ocr.gemini_error", error=str(exc)[:160])
        return None
    text = ""
    try:
        text = (resp.text or "").strip()
    except Exception:
        for cand in getattr(resp, "candidates", []) or []:
            for p in getattr(getattr(cand, "content", None), "parts", []) or []:
                text += getattr(p, "text", "") or ""
    parsed = _parse_json_response(text)
    if parsed is not None:
        parsed["_provider"] = "gemini"
    return parsed


#: Backends that answered "permanently gone" this process. A retiring provider
#: (GitHub Models returns HTTP 410 github_models_retirement_brownout) will keep
#: returning 410 for every subsequent call, so retrying it is pure wall-clock.
#: The 2026-07-31 run ate 96 such round-trips and finished that pass with
#: ocr_ok=0, backfilled=0 — time spent to accomplish nothing. One 410 now
#: disables the backend for the rest of the run; the next run re-tries it once,
#: so a provider that comes back heals itself without a code change.
_RETIRED_BACKENDS: set[str] = set()


async def _openai_compat_call(http: httpx.AsyncClient, name: str, url: str,
                              key: str, model: str, blocks=None,
                              text: Optional[str] = None) -> Optional[dict]:
    """GitHub Models / Groq — OpenAI chat API. `text` = parse lifted PDF text;
    `blocks` = base64 data-URL images (these endpoints don't take PDF bytes)."""
    if name in _RETIRED_BACKENDS:
        return None
    if text is not None:
        content = [{"type": "text", "text": f"{OCR_PROMPT}\n\nDOCUMENT TEXT:\n{text}"}]
    else:
        content = [{"type": "text", "text": OCR_PROMPT}]
        for d, m in (blocks or []):
            b64 = base64.b64encode(d).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:{m};base64,{b64}"}})
    body = {"model": model, "max_tokens": 1500, "temperature": 0.1,
            "messages": [{"role": "user", "content": content}]}
    try:
        r = await http.post(url, json=body, timeout=90.0,
                            headers={"Authorization": f"Bearer {key}",
                                     "Content-Type": "application/json"})
    except Exception as exc:
        log.warning("doc_ocr.compat_error", backend=name, error=str(exc)[:160])
        return None
    if r.status_code == 429:
        raise _QuotaOut(name)
    # 410 Gone / 404 on the endpoint itself = the provider is retired, not busy.
    # Trip the breaker so the remaining leads skip it instead of re-proving it.
    if r.status_code in (404, 410):
        _RETIRED_BACKENDS.add(name)
        log.warning("doc_ocr.backend_retired", backend=name, status=r.status_code,
                    error=r.text[:160],
                    note="disabled for this run; will be retried once next run")
        return None
    if r.status_code >= 400:
        log.warning("doc_ocr.compat_error", backend=name, status=r.status_code, error=r.text[:120])
        return None
    try:
        parsed = _parse_json_response(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return None
    if parsed is not None:
        parsed["_provider"] = name
    return parsed


async def _ocr_document(li: Listing, http: httpx.AsyncClient,
                        gemini_keys: list[str]) -> Optional[dict]:
    """Resolve one lead's document to a parsed dict, trying free providers in
    order. Returns None if no document, download fails, or all providers fail."""
    urls = _doc_urls(li)
    if not urls:
        return None
    fetched = await _fetch_doc(http, urls[0])
    if not fetched:
        return None
    data, mime = fetched
    is_pdf = mime == "application/pdf" or data[:4] == b"%PDF"

    # PDF with a real text layer: parse locally-lifted text (cheap, no vision).
    if is_pdf:
        txt = _pdf_text(data)
        if txt:
            for k in gemini_keys:
                try:
                    res = await _gemini_call(k, txt, is_text=True)
                    if res:
                        res["_source"] = "pdf_text"
                        return res
                except _QuotaOut:
                    continue
            # all Gemini keys exhausted — text parses fine on GitHub/Groq too
            gh = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
            gq = os.environ.get("GROQ_API_KEY")
            for name, url, key, model in (
                ("github", GITHUB_MODELS_URL, gh, GITHUB_MODELS_MODEL),
                ("groq", GROQ_URL, gq, GROQ_MODEL)):
                if not key:
                    continue
                try:
                    res = await _openai_compat_call(http, name, url, key, model, text=txt)
                    if res:
                        res["_source"] = "pdf_text"
                        return res
                except _QuotaOut:
                    continue

            # NVIDIA + Mistral text fallback (same OpenAI-compat path)
            nv_key = os.environ.get("NVIDIA_API_KEY")
            if nv_key:
                for nv_model in NVIDIA_VISION_MODELS:
                    try:
                        res = await _openai_compat_call(http, f"nvidia:{nv_model.split('/')[-1]}",
                                                        NVIDIA_URL, nv_key, nv_model, text=txt)
                        if res:
                            res["_source"] = "pdf_text"
                            return res
                    except _QuotaOut:
                        continue
                    except Exception:
                        continue
            ms_key = os.environ.get("MISTRAL_API_KEY")
            if ms_key:
                for ms_model in MISTRAL_VISION_MODELS:
                    try:
                        res = await _openai_compat_call(http, f"mistral:{ms_model}",
                                                        MISTRAL_URL, ms_key, ms_model, text=txt)
                        if res:
                            res["_source"] = "pdf_text"
                            return res
                    except _QuotaOut:
                        continue
                    except Exception:
                        continue
            # Claude text fallback
            claude_key = os.environ.get("ANTHROPIC_API_KEY")
            if claude_key:
                try:
                    res = await _anthropic_call(http, claude_key, blocks=None, text=txt)
                    if res:
                        res["_source"] = "pdf_text"
                        return res
                except _QuotaOut:
                    pass
            return None
        # scanned PDF: only Gemini accepts application/pdf directly
        for k in gemini_keys:
            try:
                res = await _gemini_call(k, [(data, "application/pdf")], is_text=False)
                if res:
                    res["_source"] = "pdf_scan"
                    return res
            except _QuotaOut:
                continue
        return None

    # image document: Gemini first, then GitHub Models, then Groq
    blocks = [(data, mime if mime.startswith("image/") else "image/jpeg")]
    for k in gemini_keys:
        try:
            res = await _gemini_call(k, blocks, is_text=False)
            if res:
                res["_source"] = "image"
                return res
        except _QuotaOut:
            continue
    gh = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if gh:
        try:
            res = await _openai_compat_call(http, "github", GITHUB_MODELS_URL, gh,
                                            GITHUB_MODELS_MODEL, blocks)
            if res:
                res["_source"] = "image"
                return res
        except _QuotaOut:
            pass
    gq = os.environ.get("GROQ_API_KEY")
    if gq:
        try:
            res = await _openai_compat_call(http, "groq", GROQ_URL, gq, GROQ_MODEL, blocks)
            if res:
                res["_source"] = "image"
                return res
        except _QuotaOut:
            pass

    # NVIDIA NIM — free, ~40 RPM per model, OpenAI-compatible
    nv_key = os.environ.get("NVIDIA_API_KEY")
    if nv_key and not getattr(_ocr_document, "_nv_disabled", False):
        for nv_model in NVIDIA_VISION_MODELS:
            try:
                res = await _openai_compat_call(http, f"nvidia:{nv_model.split('/')[-1]}",
                                                NVIDIA_URL, nv_key, nv_model, blocks)
                if res:
                    res["_source"] = "image"
                    return res
            except _QuotaOut:
                continue
            except Exception:
                continue

    # Mistral — free tier, OpenAI-compatible
    ms_key = os.environ.get("MISTRAL_API_KEY")
    if ms_key and not getattr(_ocr_document, "_ms_disabled", False):
        for ms_model in MISTRAL_VISION_MODELS:
            try:
                res = await _openai_compat_call(http, f"mistral:{ms_model}",
                                                MISTRAL_URL, ms_key, ms_model, blocks)
                if res:
                    res["_source"] = "image"
                    return res
            except _QuotaOut:
                continue
            except Exception:
                continue

    # Anthropic Claude — LAST resort, costs money ($0.01-0.03/call)
    claude_key = os.environ.get("ANTHROPIC_API_KEY")
    if claude_key:
        try:
            res = await _anthropic_call(http, claude_key, blocks)
            if res:
                res["_source"] = "image"
                return res
        except _QuotaOut:
            pass

    return None


# --- backfill ---------------------------------------------------------------
def _clean_amount(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(re.sub(r"[^0-9.]", "", str(v)) or 0) or None
    except Exception:
        return None


def apply_ocr(li: Listing, parsed: dict) -> list[str]:
    """Write raw['doc_ocr'] and backfill blank Listing fields. Returns the list
    of field names actually filled (for stats). Never clobbers a set value."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["doc_ocr"] = parsed
    filled: list[str] = []

    name = (parsed.get("owner_name") or "").strip()
    if name and not (getattr(li, "defendant", None) or "").strip():
        li.defendant = name
        filled.append("defendant")
    if name and not (getattr(li, "owner_name", None) or "").strip():
        li.owner_name = name
        filled.append("owner_name")

    addr = (parsed.get("property_address") or "").strip()
    if addr and not (getattr(li, "street_address", None) or "").strip():
        li.street_address = addr
        filled.append("street_address")
    for src, attr in (("city", "city"), ("state", "state"), ("zip", "zip_code")):
        val = (parsed.get(src) or "").strip() if isinstance(parsed.get(src), str) else parsed.get(src)
        if val and not (getattr(li, attr, None) or ""):
            setattr(li, attr, str(val).strip()[:(5 if attr == "zip_code" else 60)])
            filled.append(attr)

    cn = (parsed.get("case_number") or "").strip() if isinstance(parsed.get("case_number"), str) else None
    if cn and not (getattr(li, "case_number", None) or "").strip():
        li.case_number = cn
        filled.append("case_number")

    amt = _clean_amount(parsed.get("amount"))
    if amt and not getattr(li, "judgment_amount", None):
        li.judgment_amount = amt
        filled.append("judgment_amount")
    return filled


# --- entry point ------------------------------------------------------------
async def enrich_doc_ocr(listings: Iterable[Listing],
                         http: Optional[httpx.AsyncClient] = None) -> dict:
    stats = {"targets": 0, "ocr_ok": 0, "backfilled": 0, "skipped_budget": 0, "no_provider": 0}
    if not DOC_OCR_ENABLED:
        return stats
    gemini_keys = _parse_gemini_keys()
    have_compat = bool(os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
                       or os.environ.get("GROQ_API_KEY"))
    if not gemini_keys and not have_compat:
        stats["no_provider"] = 1
        log.warning("doc_ocr.no_provider", hint="set GEMINI_API_KEY_n / GITHUB_MODELS_TOKEN / GROQ_API_KEY")
        return stats

    listings = list(listings)
    candidates = [li for li in listings
                  if _doc_urls(li) and (DOC_OCR_FORCE or not (isinstance(li.raw, dict) and li.raw.get("doc_ocr")))]
    # Aggregate-list guard: drop leads whose document URL is a shared list PDF
    # (appears on more than DOC_OCR_MAX_SHARE leads) — OCRing a county tax-ad or
    # sale roster per-lead is wasteful and stamps the top row onto every lead.
    from collections import Counter
    url_counts = Counter(_doc_urls(li)[0] for li in candidates)
    aggregate = {u for u, c in url_counts.items() if c > DOC_OCR_MAX_SHARE}
    targets = [li for li in candidates if _doc_urls(li)[0] not in aggregate]
    stats["targets"] = len(targets)
    stats["skipped_aggregate"] = len(candidates) - len(targets)
    if aggregate:
        log.info("doc_ocr.aggregate_skipped", lists=len(aggregate), leads=stats["skipped_aggregate"])
    if not targets:
        return stats

    async def _run(hc: httpx.AsyncClient) -> None:
        start = time.monotonic()
        for i, li in enumerate(targets):
            if i >= DOC_OCR_MAX or (time.monotonic() - start) > DOC_OCR_BUDGET_S:
                stats["skipped_budget"] = len(targets) - i
                log.info("doc_ocr.budget_stop", done=i, remaining=stats["skipped_budget"])
                break
            try:
                parsed = await asyncio.wait_for(
                    _ocr_document(li, hc, gemini_keys), timeout=120.0)
            except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
                log.warning("doc_ocr.item_fail", source_url=getattr(li, "source_url", None), error=str(exc)[:120])
                continue
            if not parsed:
                continue
            stats["ocr_ok"] += 1
            if apply_ocr(li, parsed):
                stats["backfilled"] += 1

    if http is not None:
        await _run(http)
    else:
        async with http_client(timeout=30.0) as hc:
            await _run(hc)
    log.info("doc_ocr.done", **stats)
    return stats
