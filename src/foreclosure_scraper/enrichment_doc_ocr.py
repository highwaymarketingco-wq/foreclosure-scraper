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
DOC_OCR_MAX = int(os.environ.get("DOC_OCR_MAX", "2500"))
DOC_OCR_BUDGET_S = float(os.environ.get("DOC_OCR_BUDGET_S", "2400"))
# A document URL shared across MORE than this many leads is an AGGREGATE LIST
# (a county tax-advertisement PDF, a MIE sale roster) — not a per-property
# notice. OCRing it per-lead would burn quota and stamp the list's top row onto
# every lead, so those are skipped. Per-property scanned notices (one distinct
# doc per lead, e.g. Column/Cloudinary enotice images) are kept.
DOC_OCR_MAX_SHARE = int(os.environ.get("DOC_OCR_MAX_SHARE", "3"))
DOC_OCR_MODEL = os.environ.get("DOC_OCR_MODEL", GEMINI_VISION_MODEL)
_MAX_DOC_BYTES = 12 * 1024 * 1024   # notices/deeds are small; cap defensively
_MAX_PDF_TEXT_CHARS = 20000
# The aggregate-roster reader (see _row_backfill_from_aggregate / the aggregate
# pass in enrich_doc_ocr) pays no OCR/vision cost -- pdfplumber text extraction
# is local and free, and it runs ONCE per unique document, not per lead -- so it
# can afford to read the WHOLE roster instead of the 3-page/20K-char budget
# that exists to bound COST on the per-lead vision/text-parse path below.
# Confirmed 2026-09-23 against the live board: Catawba County NC's delinquent-
# tax roster (counties_nc.nc_county_pdf_delinquent_tax, 3,958 leads) is 161
# pages, alphabetical by taxpayer name, ~25 rows/page; the old 3-page cap made
# every row past roughly "ACEVEDO ELIAS NOE" (98% of the document) structurally
# invisible to _row_backfill_from_aggregate. Buncombe County's roster (845
# leads) is 12 pages, so the same cap hid ~75% of it. This is THE dominant
# explanation for agg_backfilled=2 of agg_leads=8955 in the 2026-09-22 run.
# DOC_OCR_AGG_MAX_PAGES=0 (the default) means "no page limit" -- the char
# budget below is what actually bounds a pathological input.
DOC_OCR_AGG_MAX_PAGES = int(os.environ.get("DOC_OCR_AGG_MAX_PAGES", "0")) or None
DOC_OCR_AGG_MAX_CHARS = int(os.environ.get("DOC_OCR_AGG_MAX_CHARS", "2000000"))

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
    "estate at issue), not a mailing address for the attorney/court, the "
    "personal representative or the executor; null when the document names no "
    "real property.\n"
    '  "city": subject property city.\n'
    '  "state": 2-letter state.\n'
    '  "zip": 5-digit zip.\n'
    '  "sale_date": scheduled sale/hearing date as printed (YYYY-MM-DD if '
    "possible). A notice to creditors has NO sale date: its claims deadline "
    'goes in "claims_deadline" and sale_date is null.\n'
    '  "claims_deadline": the date creditors must present claims by (notice to '
    "creditors only), else null.\n"
    '  "amount": the single most relevant DOLLAR figure — judgment, debt, '
    "opening/upset bid, tax due, or secured lien amount — as a number without "
    "$ or commas.\n"
    '  "case_number": docket/case/file number if present.\n'
    '  "doc_type": one short label, e.g. "foreclosure_notice", "tax_sale", '
    '"lis_pendens", "notice_to_creditors", "probate_notice", "deed_of_trust", '
    '"lien".\n'
    "Output the JSON object only, no prose."
)


# --- document discovery -----------------------------------------------------
# Which URLs on a lead are its documents is decided in ONE place, doc_inventory.ocr_doc_urls:
# the classic _DOC_FIELDS above, the source-specific notice blocks scrapers stash a lead's own
# notice under (Column e-notice PDFs, Brunswick / coastal / Swain / Haywood notice PDFs, master-
# in-equity sale PDFs, SC forfeited-land documents), then a document-like source_url. The same
# function feeds the inventory, the ledger and the documents_images audit check.
from . import doc_inventory as _inv  # noqa: E402
from . import doc_ledger as _dl  # noqa: E402

#: bumps when the prompt, the provider chain or apply_ocr changes what a read produces; the
#: ledger re-reads a document read by an older version.
DOC_OCR_VERSION = "doc_ocr-v2"
DOC_OCR_AGG_VERSION = "doc_ocr_agg-v2"
#: documents read per lead per run (each one gets its own ledger outcome; the rest wait for the
#: next run). Before 2026-10-09 only the first document of a lead was ever read.
DOC_OCR_DOCS_PER_LEAD = int(os.environ.get("DOC_OCR_DOCS_PER_LEAD", "3"))
#: the aggregate (roster) pass runs FIRST under its own share of the budget: it is local and free
#: (pdfplumber), and before 2026-10-09 it ran after the per-lead loop, so a budget spent on paid
#: provider calls starved it (2026-10-07 full run: 18 rosters, 12,431 leads, never read).
DOC_OCR_AGG_BUDGET_S = float(os.environ.get("DOC_OCR_AGG_BUDGET_S", "600"))
#: a roster read within this many days is not read again (same extractor version)
DOC_OCR_AGG_REFRESH_DAYS = float(os.environ.get("DOC_OCR_AGG_REFRESH_DAYS", "7"))
_LEDGER_SAVE_EVERY = 25

#: the live stats of the current/last enrich_doc_ocr call, so a caller whose outer cap cancels
#: the pass can still log what it did
LAST_STATS: dict = {}


def _doc_urls(li: Listing) -> list[str]:
    """The lead's primary document URL (a one-element list), or []."""
    return _inv.ocr_doc_urls(li)[:1]


def _doc_urls_all(li: Listing, cap: Optional[int] = None) -> list[str]:
    """Up to `cap` (DOC_OCR_DOCS_PER_LEAD) of the lead's document URLs, best first."""
    n = DOC_OCR_DOCS_PER_LEAD if cap is None else cap
    return _inv.ocr_doc_urls(li)[:max(1, n)]


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


def _pdf_text(data: bytes, max_pages: Optional[int] = 3,
              max_chars: int = _MAX_PDF_TEXT_CHARS) -> Optional[str]:
    """Lift the text layer from a PDF. Returns None if the PDF is scanned (no
    meaningful text) or unreadable — caller then OCRs it.

    `max_pages` defaults to 3 (the per-lead notice/deed case: bounding a paid
    vision/text call). Pass `max_pages=None` to read every page — the
    aggregate-roster reader needs the whole document; see DOC_OCR_AGG_MAX_PAGES
    above for why."""
    try:
        import io
        import pdfplumber
        chunks: list[str] = []
        total = 0
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            for page in pages:
                t = page.extract_text() or ""
                if t:
                    chunks.append(t)
                    total += len(t)
                if max_chars and total >= max_chars:
                    break
        text = "\n".join(chunks).strip()
        return text[:max_chars] if len(text) >= 200 else None
    except Exception:
        return None


_HTML_DROP = re.compile(r"<(script|style|noscript|svg|head)\b.*?</\1\s*>", re.I | re.S)
_HTML_TAG = re.compile(r"<[^>]+>")


def _looks_html(data: bytes, mime: str) -> bool:
    if mime.startswith("text/html") or mime == "application/xhtml+xml":
        return True
    head = data[:512].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))


def _html_text(data: bytes, max_chars: int = _MAX_PDF_TEXT_CHARS) -> Optional[str]:
    """Visible text of an HTML notice page (a newspaper legal notice, a sale advert). Before
    2026-10-09 such a page was sent to the vision models as if it were a JPEG."""
    try:
        s = data.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None
    s = _HTML_DROP.sub(" ", s)
    s = _HTML_TAG.sub(" ", s)
    import html as _html
    s = re.sub(r"\s+", " ", _html.unescape(s)).strip()
    return s[:max_chars] if len(s) >= 200 else None


# --- provider calls (free-first, quota-rotating) ----------------------------
class _QuotaOut(Exception):
    pass


class _Overloaded(_QuotaOut):
    """Gemini answered 503 UNAVAILABLE ('model is currently experiencing high demand'). Every
    key reaches the same overloaded model, so the remaining keys are not tried for this
    document (the 2026-10-07 run spent its 900 s cycling 503s across keys). A subclass of
    _QuotaOut, so a caller that only knows _QuotaOut (dot_ocr, extract_lien_amounts) treats it
    as 'this key cannot answer now' and moves on, as it did for a quota answer."""


_GEMINI_OVERLOAD = {"streak": 0, "until": 0.0}
#: after this many overloaded answers in a row Gemini is skipped for _OVERLOAD_PAUSE_S
_OVERLOAD_STREAK = int(os.environ.get("DOC_OCR_GEMINI_OVERLOAD_STREAK", "3"))
_OVERLOAD_PAUSE_S = float(os.environ.get("DOC_OCR_GEMINI_OVERLOAD_PAUSE_S", "120"))


def _gemini_paused() -> bool:
    return time.monotonic() < _GEMINI_OVERLOAD["until"]


def _note_overload(hit: bool) -> None:
    if not hit:
        _GEMINI_OVERLOAD["streak"] = 0
        return
    _GEMINI_OVERLOAD["streak"] += 1
    if _GEMINI_OVERLOAD["streak"] >= _OVERLOAD_STREAK:
        _GEMINI_OVERLOAD["until"] = time.monotonic() + _OVERLOAD_PAUSE_S
        _GEMINI_OVERLOAD["streak"] = 0
        log.info("doc_ocr.gemini_overload_pause", seconds=_OVERLOAD_PAUSE_S)


def _is_overloaded(msg: str) -> bool:
    m = msg.lower()
    return "503" in m and ("unavailable" in m or "high demand" in m or "overloaded" in m)


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
        if _is_overloaded(str(exc)):
            raise _Overloaded(key[:8])
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


#: a scanned page whose long side is under this many points is rasterized for the model
_SMALL_PAGE_PT = 800.0
#: target long side, in pixels, of a rasterized scanned page
_RASTER_LONG_SIDE_PX = 2400


def _first_page_long_side(data: bytes) -> float:
    try:
        import io as _io
        import pdfplumber
        with pdfplumber.open(_io.BytesIO(data)) as pdf:
            if not pdf.pages:
                return 0.0
            pg = pdf.pages[0]
            return float(max(pg.width or 0, pg.height or 0))
    except Exception:  # noqa: BLE001
        return 0.0


def _raster_scan(data: bytes) -> Optional[tuple[bytes, str]]:
    """Page 1 of a scanned PDF as a grayscale PNG whose long side is about
    _RASTER_LONG_SIDE_PX (resolution 150 to 600 dpi). rod.doc_images.rasterize_pdf_page1
    renders at 110 dpi, which turns a cropped newspaper notice into ~130 x 380 pixels."""
    if not data or data[:4] != b"%PDF":
        return None
    try:
        import io as _io
        import pdfplumber
        with pdfplumber.open(_io.BytesIO(data)) as pdf:
            if not pdf.pages:
                return None
            pg = pdf.pages[0]
            long_pt = float(max(pg.width or 0, pg.height or 0)) or 792.0
            res = int(max(150, min(600, _RASTER_LONG_SIDE_PX * 72.0 / long_pt)))
            im = pg.to_image(resolution=res)
            buf = _io.BytesIO()
            im.original.convert("L").save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "image/png"
    except Exception:  # noqa: BLE001
        return None


def _paid_allowed() -> bool:
    """The Anthropic fallback costs money ($0.01-0.03 a call). Since 2026-10-09 doc OCR stays on
    free tiers unless the owner opts in with DOC_OCR_ALLOW_PAID=1."""
    return os.environ.get("DOC_OCR_ALLOW_PAID", "0") == "1"


async def _gemini_chain(gemini_keys: list[str], payload, is_text: bool) -> Optional[dict]:
    """Every Gemini key in turn; an overloaded model (503) stops the chain for this document and
    feeds the overload pause (_note_overload)."""
    if _gemini_paused():
        return None
    for k in gemini_keys:
        try:
            res = await _gemini_call(k, payload, is_text=is_text)
        except _Overloaded:
            _note_overload(True)
            return None
        except _QuotaOut:
            continue
        _note_overload(False)
        if res:
            return res
    return None


async def _compat_chain(http: httpx.AsyncClient, *, text: Optional[str] = None,
                        blocks=None) -> Optional[dict]:
    """The free OpenAI-compatible providers (GitHub Models, Groq, NVIDIA NIM, Mistral), then
    Anthropic only when DOC_OCR_ALLOW_PAID=1."""
    gh = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    gq = os.environ.get("GROQ_API_KEY")
    lanes = [("github", GITHUB_MODELS_URL, gh, GITHUB_MODELS_MODEL),
             ("groq", GROQ_URL, gq, GROQ_MODEL)]
    nv_key = os.environ.get("NVIDIA_API_KEY")
    if nv_key:
        lanes += [(f"nvidia:{m.split('/')[-1]}", NVIDIA_URL, nv_key, m) for m in NVIDIA_VISION_MODELS]
    ms_key = os.environ.get("MISTRAL_API_KEY")
    if ms_key:
        lanes += [(f"mistral:{m}", MISTRAL_URL, ms_key, m) for m in MISTRAL_VISION_MODELS]
    for name, url, key, model in lanes:
        if not key:
            continue
        try:
            res = await _openai_compat_call(http, name, url, key, model, blocks=blocks, text=text)
        except _QuotaOut:
            continue
        except Exception:  # noqa: BLE001
            continue
        if res:
            return res
    claude_key = os.environ.get("ANTHROPIC_API_KEY")
    if claude_key and _paid_allowed():
        try:
            res = await _anthropic_call(http, claude_key, blocks or [], text=text)
        except _QuotaOut:
            res = None
        if res:
            return res
    return None


async def _ocr_text(txt: str, http: httpx.AsyncClient, gemini_keys: list[str]) -> Optional[dict]:
    res = await _gemini_chain(gemini_keys, txt, is_text=True)
    if res:
        return res
    return await _compat_chain(http, text=txt)


async def _ocr_bytes(data: bytes, mime: str, http: httpx.AsyncClient,
                     gemini_keys: list[str]) -> tuple[Optional[dict], str]:
    """Read one fetched document. Returns (parsed or None, kind): kind is pdf_text, pdf_scan,
    image or html_text for a document the providers were asked about, or 'unsupported:<why>'
    for bytes no provider can read (a spreadsheet, an HTML page with no text, an empty file)."""
    is_pdf = mime == "application/pdf" or data[:4] == b"%PDF"
    if is_pdf:
        txt = _pdf_text(data)
        if txt:
            res = await _ocr_text(txt, http, gemini_keys)
            return (res, "pdf_text")
        # scanned PDF. A small page (a newspaper's cropped notice is about 84 x 251 pt) is sent
        # as a high-resolution PNG: handed over as a PDF it is read at the model's own low
        # resolution, and on the 10/7 board the one dense Column notice in the sample came back
        # with wrong digits in its case number and house number. Otherwise Gemini takes the PDF
        # directly (every page); the compat providers always take page 1 as a PNG.
        png = _raster_scan(data)
        small = _first_page_long_side(data) < _SMALL_PAGE_PT
        if small and png:
            res = await _gemini_chain(gemini_keys, [png], is_text=False)
        else:
            res = await _gemini_chain(gemini_keys, [(data, "application/pdf")], is_text=False)
        if res:
            return (res, "pdf_scan")
        if png:
            res = await _compat_chain(http, blocks=[png])
        return (res, "pdf_scan")
    if _looks_html(data, mime):
        txt = _html_text(data)
        if not txt:
            return (None, "unsupported:html_without_text")
        return (await _ocr_text(txt, http, gemini_keys), "html_text")
    if data[:4] in (b"II*\x00", b"MM\x00*") or mime == "image/tiff":
        # a recorded-page TIFF: the vision providers take PNG/JPEG, not TIFF
        try:
            import io as _io
            from PIL import Image as _Image
            im = _Image.open(_io.BytesIO(data))
            im.seek(0)
            out = _io.BytesIO()
            im.convert("L").save(out, "PNG")
            data, mime = out.getvalue(), "image/png"
        except Exception:  # noqa: BLE001
            return (None, "unsupported:tiff_unreadable")
    if mime.startswith("image/") or data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
        blocks = [(data, mime if mime.startswith("image/") else "image/jpeg")]
        res = await _gemini_chain(gemini_keys, blocks, is_text=False)
        if res:
            return (res, "image")
        return (await _compat_chain(http, blocks=blocks), "image")
    if data[:2] == b"PK" or "spreadsheet" in mime or "excel" in mime or "officedocument" in mime:
        return (None, "unsupported:office_file")
    if not data.strip():
        return (None, "unsupported:empty")
    return (None, f"unsupported:{(mime or 'unknown')[:30]}")


async def _ocr_document(li: Listing, http: httpx.AsyncClient,
                        gemini_keys: list[str]) -> Optional[dict]:
    """Resolve one lead's primary document to a parsed dict, trying free providers in
    order. Returns None if no document, download fails, or all providers fail."""
    urls = _doc_urls(li)
    if not urls:
        return None
    fetched = await _fetch_doc(http, urls[0])
    if not fetched:
        return None
    data, mime = fetched
    res, kind = await _ocr_bytes(data, mime, http, gemini_keys)
    if res:
        res["_source"] = kind
    return res


# --- backfill ---------------------------------------------------------------
def _clean_amount(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(re.sub(r"[^0-9.]", "", str(v)) or 0) or None
    except Exception:
        return None


_CREDITOR_DOC = re.compile(r"creditor|probate", re.I)


def normalize_parsed(parsed: dict) -> dict:
    """Fix the two systematic misreads the 2026-10-09 accuracy sample found in notices to
    creditors (12 of the 22 scanned notices read on the 10/7 board): the models put the CLAIMS
    DEADLINE in sale_date (9 of 9 that had a date), and the personal representative's or the
    attorney's mailing address in property_address. A notice to creditors names no sale and,
    almost always, no property: the date moves to claims_deadline, the address is dropped."""
    out = dict(parsed)
    if _CREDITOR_DOC.search(str(out.get("doc_type") or "")):
        if out.get("sale_date") and not out.get("claims_deadline"):
            out["claims_deadline"] = out.get("sale_date")
        out["sale_date"] = None
        if out.get("property_address") or out.get("city") or out.get("zip"):
            out["property_address"] = out["city"] = out["zip"] = None
            out["_address_dropped"] = "notice_to_creditors_names_a_mailing_address"
    return out


def _num_groups(s: object) -> tuple:
    return tuple(int(g) for g in re.findall(r"\d+", str(s or "")))


_HOUSE_NO = re.compile(r"^\s*([1-9]\d{0,5})\s+[A-Za-z]")


def read_conflicts_with_lead(li: Listing, parsed: dict) -> Optional[str]:
    """Why a document read cannot be THIS lead's, or None. A roster or sale list that a lead
    points at (a Pickens or Anderson master-in-equity list, a sale-list PDF) is read by the
    model as its FIRST entry; on the 10/7 board that put another case's defendant or owner on 2
    of the 6 text-layer reads. The read binds only when it does not contradict the lead's own
    identifiers: the case number (the digit groups must agree), else the house number."""
    rc = str(getattr(li, "case_number", None) or "").strip()
    dc = str(parsed.get("case_number") or "").strip()
    if rc and dc and _num_groups(rc) and _num_groups(dc):
        return None if _num_groups(rc) == _num_groups(dc) else "case_number_mismatch"
    ra = _HOUSE_NO.match(str(getattr(li, "street_address", None) or ""))
    da = _HOUSE_NO.match(str(parsed.get("property_address") or ""))
    if ra and da and ra.group(1) != da.group(1):
        return "house_number_mismatch"
    return None


# city and zip are not revised: neighbours share them, so an equal value is no evidence
_REVISABLE = (("owner_name", ("owner_name", "defendant")),
              ("property_address", ("street_address",)),
              ("case_number", ("case_number",)), ("amount", ("judgment_amount",)))


def _same(a: object, b: object) -> bool:
    if a in (None, "") or b in (None, ""):
        return False
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return abs(float(a) - float(_clean_amount(b) if isinstance(b, str) else b)) < 1
        except (TypeError, ValueError):
            return False
    na = re.sub(r"[^a-z0-9]", "", str(a).lower())
    nb = re.sub(r"[^a-z0-9]", "", str(b).lower())
    return bool(na) and na == nb


def _vouched_elsewhere(li: Listing, value: object) -> bool:
    """True when `value` also appears in the lead's raw data outside the document reads (a
    scraper's own block, a merged source): then the column may hold it on that evidence, not
    because a read put it there. (A dedupe merge of two notices can give a row one source's case
    number and the other's notice: the Column notice on such a row still names its decedent.)"""
    raw = li.raw if isinstance(li.raw, dict) else {}
    nv = re.sub(r"[^a-z0-9]", "", str(value).lower())
    if len(nv) < 4:
        return False
    rest = {k: v for k, v in raw.items() if not str(k).startswith("doc_ocr")}
    try:
        blob = json.dumps(rest, default=str)
    except Exception:  # noqa: BLE001
        return False
    return nv in re.sub(r"[^a-z0-9]", "", blob.lower())


def revise_columns(li: Listing, old: dict, new: Optional[dict]) -> list[str]:
    """Undo what an earlier read put in the lead's columns where a better read (`new`, or None
    when the earlier read is known to be another lead's) says otherwise. A column is touched
    only while it still holds exactly the earlier read's value AND no other part of the lead's
    raw data carries that value (_vouched_elsewhere); it gets the new read's value, or is
    cleared. Returns the columns changed."""
    changed: list[str] = []
    for f, cols in _REVISABLE:
        ov = old.get(f)
        if ov in (None, ""):
            continue
        nv = (new or {}).get(f)
        if f == "amount" and new is not None and new.get("amount_kind") != "judgment":
            nv = None
        if _same(ov, nv):
            continue
        if _vouched_elsewhere(li, ov):
            continue
        for c in cols:
            if _same(getattr(li, c, None), ov):
                if f == "amount":
                    setattr(li, c, _clean_amount(nv) if nv not in (None, "") else None)
                elif f == "zip":
                    setattr(li, c, str(nv).strip()[:5] if nv else None)
                else:
                    setattr(li, c, str(nv).strip() if nv else None)
                changed.append(c)
    return changed


_TAX_DOC = re.compile(r"tax", re.I)


def amount_kind(parsed: dict) -> str:
    """What the extracted dollar figure is, from the document type the reader reported: a tax
    balance (tax_sale / tax notice) is never a judgment. The 2026-10-07 HOT-gate bug (1947db81)
    was exactly a tax balance stored as judgment_amount."""
    dt = str(parsed.get("doc_type") or "")
    if _TAX_DOC.search(dt):
        return "tax_owed"
    if re.search(r"deed_of_trust|mortgage", dt, re.I):
        return "loan_principal"
    if re.search(r"lien|judgment", dt, re.I):
        return "judgment"
    return "unknown"


def apply_ocr(li: Listing, parsed: dict, *, primary: bool = True) -> list[str]:
    """Write raw['doc_ocr'] and backfill blank Listing fields. Returns the list
    of field names actually filled (for stats). Never clobbers a set value.

    primary=False (a lead's second or third document): raw['doc_ocr'] keeps the first
    document's read and gains an '_also' entry naming this one's type and fields; blank
    columns are still filled from it."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    parsed = dict(parsed)
    parsed["amount_kind"] = amount_kind(parsed) if parsed.get("amount") not in (None, "") else None
    parsed.setdefault("_v", DOC_OCR_VERSION)
    if primary or not isinstance(li.raw.get("doc_ocr"), dict):
        li.raw["doc_ocr"] = parsed
    else:
        also = li.raw["doc_ocr"].setdefault("_also", [])
        if isinstance(also, list) and len(also) < 5:
            also.append({"doc_type": parsed.get("doc_type"), "_source": parsed.get("_source"),
                         "fields": sorted(k for k in ("owner_name", "property_address", "amount",
                                                      "sale_date", "case_number")
                                          if parsed.get(k) not in (None, ""))})
    filled: list[str] = []
    _target = li.raw["doc_ocr"] if (primary or not isinstance(li.raw.get("doc_ocr"), dict)) else None

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
    # Only a judgment or lien figure becomes judgment_amount. A tax balance, a loan principal,
    # an opening bid or an auction deposit stays in raw['doc_ocr'] (amount + amount_kind): on
    # the 10/7 board an auction contract package's $5,000 earnest-money deposit had landed in
    # judgment_amount (doc_type auction_notice), the same class as the 1947db81 HOT-gate bug.
    if amt and parsed.get("amount_kind") == "judgment" \
            and not getattr(li, "judgment_amount", None):
        li.judgment_amount = amt
        filled.append("judgment_amount")
    if _target is not None and filled:
        _target["_filled"] = sorted(set(filled))    # what this read put in the columns
    return filled


# --- entry point ------------------------------------------------------------
_ADDR_IN_ROW = re.compile(
    # (?<![.\-\d]) stops the match starting inside a parcel/account number such
    # as "6-21-00-456.00", which otherwise swallowed the owner name with it.
    r"(?<![.\-\d])\b\d{1,6}\s+"
    r"(?:[A-Za-z0-9][A-Za-z0-9.'\-]*\s+){1,4}?"
    r"(?:ST|STREET|RD|ROAD|DR|DRIVE|AVE|AVENUE|LN|LANE|CT|COURT|CIR|CIRCLE|"
    r"BLVD|WAY|HWY|HIGHWAY|PL|PLACE|TRL|TRAIL|PKWY|TER|LOOP)\b\.?",
    re.I)

# A bare run of 8+ consecutive digits reads as a parcel PIN or account number
# (Buncombe County NC's PINs are 15 digits; a house number in _ADDR_IN_ROW is
# capped at 6, and these rosters' dollar amounts do not reach 8 digits), never
# a street address or a small dollar figure. See the column-merge guard below.
_LONG_ID_RUN = re.compile(r"\d{8,}")


# A number right after one of these words is a lot / tract / block / unit / post number, not a
# house number. Florence County SC's tax-sale roster prints legal descriptions ("LOT 43 MEETING
# ST", "LOTS 34 & 35 HOWARD ST", "TRK 4 OFF HWY 57"); on the 10/7 board every one of the 8
# Florence roster addresses that could be checked against the roster was such a lot number
# stamped as a house number.
_NOT_HOUSE_PREFIX = re.compile(
    r"(?:\bLOTS?|\bL|\bTRK|\bTRACTS?|\bTR|\bBLK|\bBLOCK|\bUNIT|\bAPT|\bPARCEL|\bPOST|"
    r"\bNO\.?|\bPH|\bPHASE|\bSEC|\bSECTION|\bBLDG|\bSUB|#|&|\bAND)\s*$", re.I)
_PARCELISH = re.compile(r"\d+-\d+")


def _plausible_situs(row: str, m: "re.Match") -> bool:
    """False when an _ADDR_IN_ROW match is a legal description, not a street address: its
    number follows LOT / TRK / BLK / # / & ..., or the match runs through a parcel number."""
    if _NOT_HOUSE_PREFIX.search(row[max(0, m.start() - 14):m.start()]):
        return False
    return not _PARCELISH.search(m.group(0))


def reverify_aggregate_stamp(li: Listing, text: str) -> Optional[str]:
    """Re-check an address an earlier version of the roster matcher stamped (raw.doc_ocr
    _source aggregate_row_match without the current version). Returns None when the stamp
    stands, else the action taken: 'replaced' (the current matcher reads a different address
    from the lead's own line) or 'cleared' (it reads none). A stamp is touched only while the
    row's street_address still appears on the lead's roster line, so an address a later
    enricher set is never removed."""
    addr = (getattr(li, "street_address", None) or "").strip()
    if not addr:
        return None
    norm = re.sub(r"\s+", " ", addr).upper()
    if not any(norm in re.sub(r"\s+", " ", ln).upper() for ln in text.splitlines()):
        return None
    li.street_address = None
    raw_before = dict(li.raw.get("doc_ocr") or {}) if isinstance(li.raw, dict) else {}
    filled = _row_backfill_from_aggregate(li, text)
    new = (li.street_address or "").strip()
    if filled and new.upper() == norm:
        if isinstance(li.raw, dict) and isinstance(li.raw.get("doc_ocr"), dict):
            li.raw["doc_ocr"]["_v"] = DOC_OCR_AGG_VERSION
        return None
    if isinstance(li.raw, dict):
        if filled:
            li.raw["doc_ocr"]["_v"] = DOC_OCR_AGG_VERSION
            li.raw["doc_ocr"]["replaced_stamp"] = True
        else:
            li.raw.pop("doc_ocr", None)
            li.raw["doc_ocr_rejected"] = {"reason": "roster_address_not_a_situs",
                                          "_source": raw_before.get("_source")}
    return "replaced" if filled else "cleared"


def _lead_identifiers(li: Listing) -> list[str]:
    """Tokens that should appear on THIS lead's own row of a shared roster."""
    out: list[str] = []
    for v in (getattr(li, "parcel_id", None), getattr(li, "case_number", None)):
        if isinstance(v, str) and len(v.strip()) >= 5:
            out.append(v.strip())
    for v in (getattr(li, "owner_name", None), getattr(li, "defendant", None)):
        if isinstance(v, str) and len(v.strip()) >= 6:
            out.append(v.strip())
    return out


def _row_backfill_from_aggregate(li: Listing, text: str) -> list[str]:
    """Fill blanks on ONE lead from ITS OWN row of a shared multi-property doc.

    A county tax-sale roster is one PDF referenced by hundreds of leads. OCRing
    it per-lead is wasteful, and applying one parse to every lead stamps the top
    row onto all of them — which is why the aggregate guard skipped these
    entirely and doc_ocr covered 2 of 94,384 rows.

    Instead: read the document ONCE, then locate the row that carries THIS
    lead's parcel id / case number / owner name and read only that row. No
    identifier match means no write — a lead is never given another property's
    address.
    """
    if not text:
        return []
    idents = _lead_identifiers(li)
    if not idents:
        return []
    # LINE-SCOPED, deliberately. A character window around the match reaches into
    # the NEIGHBOURING row of a roster and hands this lead the previous
    # property's address — verified by test: parcel ...456.00 was given the
    # ...123.00 row's street. Only the line carrying the identifier may be read.
    row = ""
    ident_start = ident_end = 0
    for ident in idents:
        # a WHOLE token: parcel 172800898126 is not parcel 172800898126A (a McDowell row on the
        # 10/7 board was matched to its neighbour's line by the bare substring)
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(ident) + r"(?![A-Za-z0-9])", re.I)
        for line in text.splitlines():
            m = pat.search(line)
            if m:
                row = line
                ident_start, ident_end = m.start(), m.end()
                break
        if row:
            break
    if not row:
        return []
    # Column-merge guard. A physical text line carrying a SECOND long
    # (8+ digit) parcel/account-number-shaped run, distinct from this lead's
    # own matched identifier, is almost certainly TWO OR MORE unrelated
    # properties' fields concatenated onto one line -- pdfplumber's
    # extract_text() groups words into a "line" by y-position only, blind to
    # the page's column bands, and a dense multi-column roster (Buncombe
    # County NC's tax-lien PDF, verified live 2026-09-23) can weave 3-4
    # properties' name/parcel/amount/address fragments into one output line.
    # This is not theoretical: on an 11-lead real sample from that document,
    # this exact shape stamped a NEIGHBOUR's street onto 2 of 11 leads (NIX,
    # WILLIAM L JR got PAGANO, RAYMOND J's "1 CREST AVE"; FRANK W MORRIS JR
    # ETAL got a stranger's "17 SILENT PL") before this guard existed --
    # docs/doc_ocr_aggregate_match_fix_2026-09-23.md. Refusing to guess which
    # fragment on a contaminated line is this lead's own is strictly safer
    # than the alternative: no write beats a wrong write.
    if any(m.end() <= ident_start or m.start() >= ident_end
           for m in _LONG_ID_RUN.finditer(row)):
        return []
    filled: list[str] = []
    if not (getattr(li, "street_address", None) or "").strip():
        # Search only the text AFTER this lead's own identifier, not the whole
        # row. Every clean single-column roster this was checked against
        # (county tax-ad PDFs printing one property per line) lists
        # identifier-then-address in that reading order, so this costs
        # nothing there. A multi-column roster (verified live 2026-09-23
        # against Buncombe County NC's tax-lien PDF) can merge TWO OR MORE
        # unrelated properties' fields onto one physical text line --
        # pdfplumber's extract_text() groups words into a line by y-position
        # only, blind to the page's column bands -- so an address belonging
        # to a DIFFERENT property can sit earlier on that same merged line
        # than this lead's own identifier. Searching the whole row (the old
        # behaviour) could pick that up and stamp a neighbour's street onto
        # this lead -- exactly the failure this function exists to prevent.
        # This trades a theoretical loss of recall (a layout that prints the
        # address BEFORE the identifier would no longer match) for closing
        # that real, demonstrated contamination path; no such
        # address-before-identifier layout was observed in the live rosters
        # checked. See tests/test_doc_ocr_aggregate_match.py.
        best = None
        for m in _ADDR_IN_ROW.finditer(row, ident_end):
            if _plausible_situs(row, m):
                best = m
        if best:
            li.street_address = re.sub(r"\s+", " ", best.group(0)).strip()[:70]
            filled.append("street_address")
    if filled:
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["doc_ocr"] = {"_source": "aggregate_row_match",
                             "matched_on": idents[0], "fields": filled,
                             "_v": DOC_OCR_AGG_VERSION}
    return filled


_FIELD_KEYS = ("owner_name", "co_owner_name", "property_address", "city", "zip", "sale_date",
               "amount", "case_number", "doc_type")


def _county_of(li: Listing) -> str:
    return f"{(getattr(li, 'state', None) or '?')}:{(getattr(li, 'county', None) or '?')}"


def _reapply_from_ledger(li: Listing, led, key: str, entry: dict) -> list[str]:
    """Re-apply a document's earlier read (public values + the private store's names and
    address) to a lead that does not carry it, without reading the document again."""
    vals = dict(entry.get("values") or {})
    vals.update(led.private.get(key))
    if not any(vals.get(k) not in (None, "") for k in _FIELD_KEYS):
        return []
    vals["_provider"] = entry.get("provider")
    vals["_source"] = "ledger"
    vals["_ledger_key"] = key
    return apply_ocr(li, vals, primary=not isinstance(li.raw, dict) or not li.raw.get("doc_ocr"))


async def _fetch_doc_checked(c: httpx.AsyncClient, url: str) -> tuple[Optional[bytes], str, str]:
    """(data, mime, problem): problem is '' on success, else fetch_failed / too_large."""
    try:
        r = await c.get(url, timeout=20.0, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return None, "", f"fetch_failed:{type(exc).__name__}"
    if r.status_code != 200 or not r.content:
        return None, "", f"fetch_failed:http_{r.status_code}"
    if len(r.content) > _MAX_DOC_BYTES:
        return None, "", "too_large"
    mime = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    data = r.content
    if not mime:
        mime = "application/pdf" if data[:4] == b"%PDF" else "image/jpeg"
    return data, mime, ""


async def enrich_doc_ocr(listings: Iterable[Listing],
                         http: Optional[httpx.AsyncClient] = None) -> dict:
    """Read every lead's notice / filing documents (and the shared rosters a lead's blank
    address can be read from), recording each document's outcome in the processed-documents
    ledger (doc_ledger, lane doc_ocr), so the next run resumes where this one stopped.

    Order: the aggregate (roster) pass first under DOC_OCR_AGG_BUDGET_S (local, free), then
    the per-lead documents, HOT then WARM then the rest (doc_inventory.lead_value_key), up to
    DOC_OCR_DOCS_PER_LEAD documents a lead. A document the ledger has read with this extractor
    version is not fetched again (its result is re-applied to a lead that lost it); a failed one
    waits for its retry time; a fetched document whose bytes another URL already served reuses
    that read. Bounded by DOC_OCR_MAX documents fetched and DOC_OCR_BUDGET_S seconds.
    """
    global LAST_STATS
    stats = {"targets": 0, "ocr_ok": 0, "backfilled": 0, "skipped_budget": 0, "no_provider": 0,
             "docs_attempted": 0, "ledger_not_due": 0, "ledger_reapplied": 0,
             "same_content_reused": 0, "fetch_failed": 0, "provider_failed": 0,
             "unsupported": 0, "no_fields": 0, "timeouts": 0}
    LAST_STATS = stats
    if not DOC_OCR_ENABLED:
        return stats
    gemini_keys = _parse_gemini_keys()
    have_compat = bool(os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
                       or os.environ.get("GROQ_API_KEY") or os.environ.get("NVIDIA_API_KEY")
                       or os.environ.get("MISTRAL_API_KEY"))
    have_provider = bool(gemini_keys or have_compat)
    if not have_provider:
        # the roster pass needs no model; the per-lead pass does
        stats["no_provider"] = 1
        log.warning("doc_ocr.no_provider",
                    hint="set GEMINI_API_KEY_n / GITHUB_MODELS_TOKEN / GROQ_API_KEY")

    led = _dl.get_ledger("doc_ocr") if _dl.enabled() else None
    listings = list(listings)
    # Aggregate detection counts EVERY lead that references a document (normalized URL, so a
    # cache-busting ?v= does not split one roster into many), not only the leads still lacking
    # doc_ocr: a roster half of whose leads were already matched is still a roster.
    from collections import Counter
    primary: dict[int, str] = {}
    url_counts: Counter = Counter()
    for li in listings:
        urls = _doc_urls(li)
        if urls:
            n = _inv.normalize_url(urls[0])
            primary[id(li)] = n
            url_counts[n] += 1
    aggregate = {u for u, c in url_counts.items() if c > DOC_OCR_MAX_SHARE}

    # An earlier read that contradicts the lead's own case / house number is another lead's
    # (a sale list read as its first entry): its column fills are undone and the read is set
    # aside, so the lead is read again below. No fetch needed.
    stats["old_reads_rejected"] = 0
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        d = raw.get("doc_ocr") if raw else None
        if not isinstance(d, dict) or d.get("_source") in ("aggregate_row_match", "ledger"):
            continue
        why = read_conflicts_with_lead(li, d)
        if why:
            revise_columns(li, d, None)
            raw["doc_ocr_rejected"] = {"reason": why, "doc_type": d.get("doc_type"),
                                       "_source": d.get("_source")}
            del raw["doc_ocr"]
            stats["old_reads_rejected"] += 1

    def _needs_read(li: Listing) -> bool:
        d = li.raw.get("doc_ocr") if isinstance(li.raw, dict) else None
        if DOC_OCR_FORCE or not isinstance(d, dict):
            return True
        # a read by an older extractor version is read again once (its column fills are
        # revised against the new read: revise_columns)
        return d.get("_source") not in ("aggregate_row_match", "ledger") \
            and d.get("_v") != DOC_OCR_VERSION

    candidates = [li for li in listings if id(li) in primary and _needs_read(li)]
    targets = [li for li in candidates if primary[id(li)] not in aggregate]
    targets.sort(key=_inv.lead_value_key)
    stats["targets"] = len(targets)
    agg_map: dict[str, tuple[str, list]] = {}
    for li in candidates:
        n = primary[id(li)]
        if n in aggregate:
            agg_map.setdefault(n, (_doc_urls(li)[0], []))[1].append(li)
    # roster addresses an older matcher stamped are re-checked against their roster line
    agg_verify: dict[str, list] = {}
    for li in listings:
        d = li.raw.get("doc_ocr") if isinstance(li.raw, dict) else None
        if isinstance(d, dict) and d.get("_source") == "aggregate_row_match" \
                and d.get("_v") != DOC_OCR_AGG_VERSION and id(li) in primary \
                and primary[id(li)] in aggregate:
            agg_verify.setdefault(primary[id(li)], []).append(li)
            agg_map.setdefault(primary[id(li)], (_doc_urls(li)[0], []))
    stats["aggregate_docs"] = len(agg_map)
    stats["aggregate_leads"] = sum(len(v[1]) for v in agg_map.values())
    stats["aggregate_stamps_to_verify"] = sum(len(v) for v in agg_verify.values())
    if agg_map:
        log.info("doc_ocr.aggregate_queued", docs=len(agg_map), leads=stats["aggregate_leads"])
    if not targets and not agg_map:
        return stats

    recorded = {"n": 0}

    def _record(key: str, **kw) -> None:
        if led is None:
            return
        led.record(key, **kw)
        recorded["n"] += 1
        if recorded["n"] % _LEDGER_SAVE_EVERY == 0:
            try:
                led.save()
            except Exception:  # noqa: BLE001
                log.warning("doc_ocr.ledger_save_failed")

    async def _aggregate_pass(hc: httpx.AsyncClient, start: float) -> None:
        # ---- aggregate pass: read each shared document once, match per lead ----
        stats.setdefault("agg_docs_read", 0)
        stats.setdefault("agg_backfilled", 0)
        stats.setdefault("agg_docs_not_needed", 0)
        stats.setdefault("agg_docs_not_due", 0)
        budget = min(DOC_OCR_AGG_BUDGET_S, DOC_OCR_BUDGET_S)
        stats.setdefault("agg_stamps_replaced", 0)
        stats.setdefault("agg_stamps_cleared", 0)
        groups = []
        for n, (url, leads) in agg_map.items():
            need = [li for li in leads if not (getattr(li, "street_address", None) or "").strip()]
            verify = agg_verify.get(n, [])
            if not need and not verify:
                stats["agg_docs_not_needed"] += 1
                continue
            groups.append((min(_inv.lead_value_key(li) for li in (need or verify)), url, need, verify))
        groups.sort(key=lambda g: g[0])
        for _rank, url, need, verify in groups:
            if (time.monotonic() - start) > budget:
                log.info("doc_ocr.aggregate_budget_stop", remaining=len(groups) - stats["agg_docs_read"])
                break
            key = _inv.doc_key(url)
            if led is not None and not DOC_OCR_FORCE:
                e = led.get(key)
                age = None
                if e and e.get("processed_at"):
                    pa = _dl._parse(e["processed_at"])
                    age = (_dl._utc_now() - pa).total_seconds() / 86400.0 if pa else None
                if e and e.get("extractor_version") == DOC_OCR_AGG_VERSION \
                        and (e.get("outcome") in ("aggregate_read", "unsupported_format")
                             and age is not None and age < DOC_OCR_AGG_REFRESH_DAYS) \
                        and int((e.get("values") or {}).get("rows_tried") or 0) >= len(need) \
                        and not verify:
                    stats["agg_docs_not_due"] += 1
                    continue
                if e and not led.is_due(key, DOC_OCR_AGG_VERSION) \
                        and e.get("outcome") not in ("aggregate_read", "unsupported_format"):
                    stats["agg_docs_not_due"] += 1
                    continue
            src = getattr(need[0], "source", None)
            try:
                data, mime, problem = await asyncio.wait_for(_fetch_doc_checked(hc, url), timeout=90.0)
            except Exception:  # noqa: BLE001
                data, mime, problem = None, "", "fetch_failed:timeout"
            if data is None:
                _record(key, outcome="too_large" if problem == "too_large" else "fetch_failed",
                        version=DOC_OCR_AGG_VERSION, category="roster", url=url, source=src,
                        reason=problem, rows=len(need))
                continue
            sha = _dl.content_hash(data)
            if not (mime == "application/pdf" or data[:4] == b"%PDF"):
                _record(key, outcome="unsupported_format", version=DOC_OCR_AGG_VERSION,
                        category="roster", url=url, source=src, content_sha256=sha,
                        nbytes=len(data), reason="roster_not_pdf", rows=len(need))
                continue
            # Full document, not the 3-page per-lead default -- see
            # DOC_OCR_AGG_MAX_PAGES.
            text = _pdf_text(data, max_pages=DOC_OCR_AGG_MAX_PAGES,
                             max_chars=DOC_OCR_AGG_MAX_CHARS)
            if not text:
                # a scanned roster: no text layer to match rows in (per-page vision OCR of a
                # roster is not done: cost); recorded so it is not fetched again this week
                _record(key, outcome="unsupported_format", version=DOC_OCR_AGG_VERSION,
                        category="roster", url=url, source=src, content_sha256=sha,
                        nbytes=len(data), reason="roster_scanned_no_text_layer", rows=len(need))
                continue
            stats["agg_docs_read"] += 1
            for li in verify:
                try:
                    act = reverify_aggregate_stamp(li, text)
                except Exception:  # noqa: BLE001
                    act = None
                if act:
                    stats[f"agg_stamps_{act}"] += 1
            filled_here = 0
            for li in need:
                try:
                    if _row_backfill_from_aggregate(li, text):
                        stats["agg_backfilled"] += 1
                        filled_here += 1
                except Exception:  # noqa: BLE001
                    continue
            _record(key, outcome="aggregate_read", version=DOC_OCR_AGG_VERSION, category="roster",
                    url=url, source=src, content_sha256=sha, nbytes=len(data),
                    fields=["street_address"] if filled_here else [],
                    landed=["street_address"] if filled_here else [],
                    values={"rows_tried": len(need), "rows_filled": filled_here},
                    rows=len(need) + len(verify))

    async def _per_lead_pass(hc: httpx.AsyncClient, start: float) -> None:
        for i, li in enumerate(targets):
            if stats["docs_attempted"] >= DOC_OCR_MAX or (time.monotonic() - start) > DOC_OCR_BUDGET_S:
                stats["skipped_budget"] = len(targets) - i
                log.info("doc_ocr.budget_stop", done=i, remaining=stats["skipped_budget"])
                break
            got_any = False
            for j, url in enumerate(_doc_urls_all(li)):
                key = _inv.doc_key(url)
                _d = li.raw.get("doc_ocr") if isinstance(li.raw, dict) else None
                is_primary = not isinstance(_d, dict) or (
                    j == 0 and _d.get("_v") != DOC_OCR_VERSION
                    and _d.get("_source") not in ("aggregate_row_match", "ledger"))
                if led is not None and not DOC_OCR_FORCE and not led.is_due(key, DOC_OCR_VERSION):
                    stats["ledger_not_due"] += 1
                    e = led.get(key) or {}
                    if e.get("outcome") == "extracted" and is_primary:
                        if _reapply_from_ledger(li, led, key, e):
                            stats["ledger_reapplied"] += 1
                    continue
                if stats["docs_attempted"] >= DOC_OCR_MAX:
                    break
                stats["docs_attempted"] += 1
                common = dict(version=DOC_OCR_VERSION, category="notice", url=url,
                              source=getattr(li, "source", None), county=_county_of(li))
                try:
                    data, mime, problem = await asyncio.wait_for(
                        _fetch_doc_checked(hc, url), timeout=60.0)
                except Exception:  # noqa: BLE001
                    data, mime, problem = None, "", "fetch_failed:timeout"
                if data is None:
                    stats["fetch_failed"] += 1
                    _record(key, outcome="too_large" if problem == "too_large" else "fetch_failed",
                            reason=problem, **common)
                    continue
                sha = _dl.content_hash(data)
                same = led.same_content(sha, DOC_OCR_VERSION) if led is not None else None
                if same and same[0] != key:
                    stats["same_content_reused"] += 1
                    k0, e0 = same
                    filled = _reapply_from_ledger(li, led, k0, e0) if is_primary or e0.get("outcome") == "extracted" else []
                    _record(key, outcome=e0.get("outcome") or "no_fields", content_sha256=sha,
                            nbytes=len(data), fields=e0.get("fields") or [], landed=filled,
                            values={**(e0.get("values") or {}), **led.private.get(k0)},
                            provider=e0.get("provider"), reason="same_content_as_another_url",
                            **common)
                    continue
                if not have_provider:
                    _record(key, outcome="provider_failed", content_sha256=sha, nbytes=len(data),
                            reason="no_model_key_configured", **common)
                    continue
                try:
                    parsed, kind = await asyncio.wait_for(
                        _ocr_bytes(data, mime, hc, gemini_keys), timeout=120.0)
                except asyncio.TimeoutError:
                    stats["timeouts"] += 1
                    _record(key, outcome="timeout", content_sha256=sha, nbytes=len(data), **common)
                    continue
                except Exception as exc:  # noqa: BLE001
                    log.warning("doc_ocr.item_fail", source_url=getattr(li, "source_url", None),
                                error=str(exc)[:120])
                    _record(key, outcome="provider_failed", content_sha256=sha, nbytes=len(data),
                            reason=f"error:{type(exc).__name__}", **common)
                    continue
                if kind.startswith("unsupported:"):
                    stats["unsupported"] += 1
                    _record(key, outcome="unsupported_format", content_sha256=sha,
                            nbytes=len(data), reason=kind.split(":", 1)[1], **common)
                    continue
                if not parsed:
                    stats["provider_failed"] += 1
                    _record(key, outcome="provider_failed", content_sha256=sha, nbytes=len(data),
                            reason=kind, **common)
                    continue
                parsed["_source"] = kind
                stats["ocr_ok"] += 1
                parsed = normalize_parsed(parsed)
                old = li.raw.get("doc_ocr") if isinstance(li.raw, dict) else None
                old = old if isinstance(old, dict) and old.get("_v") != DOC_OCR_VERSION \
                    and old.get("_source") not in ("aggregate_row_match", "ledger") else None
                conflict = read_conflicts_with_lead(li, parsed)
                if conflict:
                    stats.setdefault("reads_of_another_lead", 0)
                    stats["reads_of_another_lead"] += 1
                    if old is not None:
                        revise_columns(li, old, None)
                    _record(key, outcome="no_fields", content_sha256=sha, nbytes=len(data),
                            provider=parsed.get("_provider"),
                            reason=f"read_is_another_lead:{conflict}", **common)
                    continue
                fields = [k for k in _FIELD_KEYS if parsed.get(k) not in (None, "", [], {})]
                revised: list[str] = []
                if old is not None:
                    parsed["amount_kind"] = amount_kind(parsed) if parsed.get("amount") not in (None, "") else None
                    revised = revise_columns(li, old, parsed)
                    is_primary = True       # the new read replaces the old one
                filled = apply_ocr(li, parsed, primary=is_primary) + revised
                if filled:
                    stats["backfilled"] += 1
                if fields:
                    got_any = True
                else:
                    stats["no_fields"] += 1
                _record(key, outcome="extracted" if fields else "no_fields", content_sha256=sha,
                        nbytes=len(data), provider=parsed.get("_provider"), fields=fields,
                        landed=filled, values=parsed, reason=kind, **common)
            if got_any:
                stats.setdefault("leads_read", 0)
                stats["leads_read"] += 1

    async def _run(hc: httpx.AsyncClient) -> None:
        start = time.monotonic()
        try:
            await _aggregate_pass(hc, start)
            if have_provider:
                await _per_lead_pass(hc, start)
        finally:
            if led is not None:
                led.last_run = {"at": _dl._iso(_dl._utc_now()),
                                "stats": {k: v for k, v in stats.items() if isinstance(v, (int, float))}}
                try:
                    led.save()
                except Exception:  # noqa: BLE001
                    log.warning("doc_ocr.ledger_save_failed")

    if http is not None:
        await _run(http)
    else:
        async with http_client(timeout=30.0) as hc:
            await _run(hc)
    log.info("doc_ocr.done", **stats)
    return stats
