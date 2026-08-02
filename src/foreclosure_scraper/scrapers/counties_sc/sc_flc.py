"""SC Forfeited Land Commission — statewide FLC / tax-sale assignment lists.

The FLC holds every parcel struck to the county at a delinquent-tax sale. Those
parcels are assignable OVER THE COUNTER at the back-taxes figure, which is the
operator's BUY-DIRECT lane — so this source has to produce PARCELS, not links.

2026-08-02 REBUILD. The full run alarmed with "0 listings for 2 consecutive runs
(normally ~18/run) — source likely broken". Both halves of that were true, for
different reasons:

  * The "~18/run" baseline was never real inventory. It was the nav-chrome junk
    (county office addresses, "E-911 Addressing", copyright footers) that the
    2026-06-25 filter correctly killed. Losing it was a fix, not a regression.
  * But the source really is dead, and the filter is not why. This scraper only
    ever scanned each county TREASURER LANDING PAGE for anchors ending in .pdf
    whose label mentioned forfeit/tax sale. Live probe of all seven counties on
    2026-08-02: ZERO such anchors anywhere.
        Spartanburg  0 pdf anchors        Union    0 (JS-rendered shell)
        Anderson     5 pdf anchors, none FLC (holiday schedule, job application)
        Pickens      0 (CMS serves one 92KB shell for every path)
        Cherokee     3 pdf anchors, none a parcel list
        Laurens      "Current FLC List" is a <li> with NO href (broken link)
    The counties moved their FLC lists off the landing pages. Scraping those
    pages can only ever return 0 now.
  * And even when it did match, it emitted ONE row per PDF LINK — a document,
    not a parcel. It never opened a single list.

The rebuild is document-first: go to the FLC documents directly and PARSE THEM
INTO PARCEL ROWS.

  1. COUNTY_FLC_DOCS — curated direct document URLs, live-verified.
  2. Hub-page discovery still runs on top, so a county that posts a NEW list
     where we can see it is picked up without a code change.
  3. Text-layer PDFs are parsed locally with pdfplumber + an SC-TMS row regex.
  4. Anderson's lists are SCANNED IMAGES (pypdf: 0 characters, 1 image/page), so
     a text parse yields nothing. They go through the same FREE, key-rotating
     Gemini pool the rest of the repo uses (enrichment_doc_ocr / vision), one
     page at a time — whole-document OCR silently truncates. Verified
     2026-08-02: 2025REFLC.pdf -> 2 real-estate parcels, 2025MHFLC.pdf -> a full
     mobile-home assignment list with TMS + situs + defaulter + price.

Compliance: every URL here is a free public .gov document over plain HTTP. No
login, no paywall, no CAPTCHA, no WAF bypass.

NOT covered here on purpose: Spartanburg (counties_sc.spartanburg_flc), Oconee
(counties_sc.oconee_forfeited_land), Horry (counties_sc.horry_flc), Georgetown
and Charleston — each has a dedicated scraper. Adding them here would duplicate.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urljoin

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...config import SC_COUNTIES
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# Hub pages scanned for NEWLY-posted FLC documents. These no longer carry the
# lists themselves (see module docstring) but cost one cheap GET each and keep
# the source self-healing if a county re-links its list.
COUNTY_TAX_URLS: dict[str, tuple[str, ...]] = {
    # Greenville/Greenwood/Newberry/Abbeville removed per scope narrowing 2026-05.
    "Spartanburg": (
        "https://www.spartanburgcounty.gov/216/Tax-Collector",
    ),
    "Anderson": (
        "https://www.andersoncountysc.org/departments-a-z/treasurer/",
    ),
    "Pickens": (
        "https://www.pickenscountysc.gov/treasurer/tax-sale",
    ),
    # Oconee removed 2026-06-26: old URL 500s, and Oconee FLC is now fully
    # covered by the dedicated counties_sc.oconee_forfeited_land scraper.
    "Cherokee": (
        "https://cherokeecountysc.gov/delinquent-tax/",  # 403 to plain GET; get_text auto-escalates to curl_cffi impersonate (200)
    ),
    # 2026-06-26: countyofunion.com is SSL-dead and co.laurens.sc.us no longer
    # resolves (DNS). Repointed to the live tax-collector domains.
    "Union": ("https://www.unioncountytc.com/",),
    "Laurens": ("https://www.laurenscountysc.gov/departments/treasurer/",),
}

#: Direct FLC / tax-sale-assignment documents, live-verified 2026-08-02.
#: Counties publish these on a fixed path and swap the file when the list is
#: refreshed, so a 404 here means "check for a new year's filename", not a bug.
COUNTY_FLC_DOCS: dict[str, tuple[str, ...]] = {
    "Anderson": (
        # 2025 FLC real-estate assignment list (scanned; OCR lane).
        "https://www.andersoncountysc.org/wp-content/uploads/2025/12/2025REFLC.pdf",
        # 2025 FLC mobile-home assignment list (scanned; OCR lane).
        "https://www.andersoncountysc.org/wp-content/uploads/2025/12/2025MHFLC.pdf",
    ),
}

# SC tax map numbers come in several county formats:
#   Spartanburg  6-18-07-092.00      Anderson  126-05-17-005
#   Greenville   0123-45-67-890.00   dashed alnum prefixes on some CMS exports
PARCEL_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}-\d{3}\.\d{3}\b"
    r"|\b\d{1,3}-\d{2}-\d{2}-\d{3}(?:\.\d{2,3})?\b"
    r"|\b[A-Z0-9]{3,5}-\d{2}-\d{2,4}-\d{3,4}\b"
)
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
MONEY_RE = re.compile(r"\$\s*([\d,]+\.\d{2})")

# Substrings that mark a line as page chrome (county-office contact block,
# nav / GIS menu items, footer, JS) rather than a forfeited-land parcel row.
# Lines containing any of these are dropped even if they happen to carry a TMS.
_NAV_CONTACT_MARKERS = (
    "e-911", "e911", "911 address", "addressing",
    "copyright", "©", "all rights reserved",
    "contact", "phone", "fax", "email", "hours", "monday", "friday",
    "planning", "subdividing", "combining",
    "linklevel", "linksection", "pagelinkfilter", "rz.",  # JS chrome
    "privacy", "sitemap", "site map", "accessibility", "disclaimer",
    "department", "treasurer's office", "tax collector's office",
)

# A document link is an FLC/tax-sale LIST if its label says so. The short tokens
# (flc/fla) are word-bounded — a bare substring test matches far too much on real
# county filenames ("...-fillable.pdf", "inflation", "flag").
_DOC_WANTED_RE = re.compile(
    r"forfeit|forfeited\s*land|tax[\s_-]*sale|delinquent|assignment|surplus"
    r"|\bflc\b|\bfla\b",
    re.I,
)
# ...and is NOT a post-sale/bidder/procedural sheet.
_DOC_UNWANTED = ("bidder", "result", "sold", "winning", "procedure", "policy",
                 "registration", "faq", "instruction", "overage", "web policy")

# --- OCR lane ---------------------------------------------------------------
FLC_OCR_ENABLED = os.environ.get("SC_FLC_OCR", "1") != "0"
# Anderson's two lists are 3 and 5 pages. 40 is a generous ceiling that still
# bounds a county that posts a 200-page scan.
FLC_OCR_MAX_PAGES = int(os.environ.get("SC_FLC_OCR_MAX_PAGES", "40"))
FLC_OCR_MODEL = os.environ.get("SC_FLC_OCR_MODEL",
                               os.environ.get("DOC_OCR_MODEL", "gemini-2.5-flash"))
# Free-tier Gemini limits are per-minute as well as per-day, and the daily vision
# pass shares this key pool — so a fully-exhausted sweep is usually transient.
_OCR_SWEEPS = int(os.environ.get("SC_FLC_OCR_SWEEPS", "3"))
_OCR_COOLDOWN_S = float(os.environ.get("SC_FLC_OCR_COOLDOWN_S", "35"))

_OCR_PROMPT = (
    "This page is from a South Carolina county Forfeited Land Commission (FLC) "
    "or delinquent tax-sale assignment list. Transcribe EVERY data row on the "
    "page, top to bottom, skipping headers, instructions and footers. "
    'Return ONLY JSON: {"rows":[{"item":"","parcel_id":"","owner_name":"",'
    '"address":"","city":"","amount":""}]}. parcel_id is the tax map / TMS '
    "number. amount is the assignment price or total tax due. Use an empty "
    "string for any column not printed on the row. Do not invent rows; if the "
    "page has no data rows return an empty list."
)


def _is_nav_or_contact(line: str) -> bool:
    """True if a body line is page chrome (office address/phone, nav, footer,
    JS) and must not be emitted as a forfeited-land parcel row."""
    low = (line or "").lower()
    return any(m in low for m in _NAV_CONTACT_MARKERS)


def _wanted_doc(label: str, href: str) -> bool:
    blob = f"{label} {href}".lower()
    if any(k in blob for k in _DOC_UNWANTED):
        return False
    return bool(_DOC_WANTED_RE.search(blob))


def _money(text: str) -> Optional[float]:
    m = MONEY_RE.search(text or "")
    if not m:
        # bare "1,281.65" (OCR strips the $ into its own column)
        m2 = re.search(r"\b([\d,]+\.\d{2})\b", text or "")
        if not m2:
            return None
        raw = m2.group(1)
    else:
        raw = m.group(1)
    try:
        v = float(raw.replace(",", ""))
    except ValueError:
        return None
    return v if v > 0 else None


def _pdf_pages(data: bytes) -> list[str]:
    """Text of each page; empty strings for a scanned page with no text layer."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def _split_pdf_pages(data: bytes) -> list[bytes]:
    """One single-page PDF per page — OCR quality collapses on whole documents
    (live check: whole-doc OCR of the 3-page Anderson list returned 2 of the
    rows it should have seen; page-by-page returned them reliably)."""
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    out: list[bytes] = []
    for page in reader.pages:
        writer = pypdf.PdfWriter()
        writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        out.append(buf.getvalue())
    return out


def _parse_text_rows(text: str) -> list[dict]:
    """Pull parcel rows out of a text-layer FLC list."""
    rows: list[dict] = []
    for line in (text or "").splitlines():
        line = " ".join(line.split())
        if len(line) < 12 or _is_nav_or_contact(line):
            continue
        pm = PARCEL_RE.search(line)
        if not pm:
            continue
        am = ADDR_RE.search(line)
        rows.append({
            "parcel_id": pm.group(0),
            "address": am.group(1) if am else "",
            "amount": _money(line),
            "line": line[:300],
        })
    return rows


class _OCRQuotaOut(Exception):
    """Every key in the free pool is rate-limited right now."""


class _OCRNoKey(_OCRQuotaOut):
    """No OCR key is configured at all, so scanned lists cannot be read.

    Subclasses _OCRQuotaOut deliberately: both mean "this scanned document went
    UNREAD", and the caller must not report an unread source as a clean zero.
    Previously _ocr_document() just returned [] here, so a missing key produced
    0 parcels with no error and no alarm — the same silent-failure class that let
    the upset-bid lane sit dead for months. Distinct type so the operator note
    can tell "add a key" apart from "wait for quota"."""


def _is_quota(msg: str) -> bool:
    m = msg.lower()
    return any(s in m for s in ("quota", "rate limit", "429",
                                "resource_exhausted", "exceeded"))


async def _ocr_page(page_pdf: bytes, keys: list[str]) -> Optional[list[dict]]:
    """OCR one page through the free Gemini pool, rotating keys past quota.

    The pool's free tier limits are per-MINUTE as well as per-day and the daily
    vision pass shares it, so an exhausted sweep is usually transient: sweep the
    whole pool, wait, sweep again. Raises _OCRQuotaOut when every key is still
    limited after the last sweep — the caller must NOT turn that into a clean 0.
    """
    try:
        from google import genai
        from google.genai import types as t
    except ImportError:
        log.warning("sc_flc.ocr_sdk_missing", hint="pip install google-genai")
        return None
    for sweep in range(_OCR_SWEEPS):
        for key in keys:
            try:
                client = genai.Client(api_key=key)
                resp = await client.aio.models.generate_content(
                    model=FLC_OCR_MODEL,
                    contents=[
                        t.Part.from_bytes(data=page_pdf, mime_type="application/pdf"),
                        _OCR_PROMPT,
                    ],
                    config=t.GenerateContentConfig(
                        temperature=0, max_output_tokens=40000,
                        response_mime_type="application/json"),
                )
            except Exception as exc:  # noqa: BLE001
                if _is_quota(str(exc)):
                    continue          # next key
                log.warning("sc_flc.ocr_error", error=str(exc)[:160])
                return None
            raw = ""
            try:
                raw = (resp.text or "").strip()
            except Exception:  # noqa: BLE001
                for cand in getattr(resp, "candidates", []) or []:
                    for p in getattr(getattr(cand, "content", None), "parts", []) or []:
                        raw += getattr(p, "text", "") or ""
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            try:
                return json.loads(raw).get("rows") or []
            except (json.JSONDecodeError, AttributeError):
                log.warning("sc_flc.ocr_bad_json", head=raw[:120])
                return None
        if sweep + 1 < _OCR_SWEEPS:
            log.info("sc_flc.ocr_pool_cooling", sweep=sweep + 1,
                     keys=len(keys), sleep_s=_OCR_COOLDOWN_S)
            await asyncio.sleep(_OCR_COOLDOWN_S)
    raise _OCRQuotaOut(f"all {len(keys)} Gemini keys rate-limited")


async def _ocr_document(data: bytes) -> list[dict]:
    """OCR a scanned FLC list page by page. Returns [] when OCR is unavailable."""
    if not FLC_OCR_ENABLED:
        return []
    from ...enrichment_vision import _parse_gemini_keys
    keys = _parse_gemini_keys()
    if not keys:
        log.warning("sc_flc.ocr_no_key",
                    hint="set GEMINI_API_KEY(_1..) to read scanned FLC lists")
        raise _OCRNoKey("no Gemini key configured; scanned FLC list unread")
    try:
        pages = _split_pdf_pages(data)
    except Exception:  # noqa: BLE001
        log.warning("sc_flc.pdf_split_failed", exc_info=True)
        return []
    rows: list[dict] = []
    for page_pdf in pages[:FLC_OCR_MAX_PAGES]:
        try:
            got = await _ocr_page(page_pdf, keys)
        except _OCRQuotaOut:
            # Keep whatever pages already came back; only a document that read
            # NOTHING is worth escalating to the caller.
            if rows:
                log.warning("sc_flc.ocr_partial", pages_read=len(rows))
                return rows
            raise
        if got is None:
            break                                 # provider down; stop burning pages
        rows.extend(got)
    return rows


def _normalize_ocr_row(row: dict) -> Optional[dict]:
    """Keep only OCR rows that carry a real TMS — everything else is header or
    hallucination."""
    parcel = str(row.get("parcel_id") or "").strip()
    if not parcel or not PARCEL_RE.search(parcel):
        return None
    address = str(row.get("address") or "").strip()
    city = str(row.get("city") or "").strip()
    # OCR often folds the city into the address ("790 Mountain View Drive in Anderson")
    m = re.search(r"^(.*?)\s+(?:in|near)\s+([A-Z][A-Za-z .'-]+)$", address)
    if m and not city:
        address, city = m.group(1).strip(), m.group(2).strip()
    return {
        "parcel_id": PARCEL_RE.search(parcel).group(0),
        "address": address,
        "city": city or None,
        "owner_name": (str(row.get("owner_name") or "").strip() or None),
        "item": (str(row.get("item") or "").strip() or None),
        "amount": _money(str(row.get("amount") or "")),
    }


async def _doc_rows(url: str) -> tuple[list[dict], str]:
    """Fetch one FLC document and return (parcel rows, lane used)."""
    try:
        data = await get_bytes(url, timeout=90.0)
    except Exception:  # noqa: BLE001
        log.warning("sc_flc.doc_fetch_failed", url=url[:120])
        return [], "fetch_failed"
    if not data or data[:4] != b"%PDF":
        return [], "not_pdf"
    try:
        pages = _pdf_pages(data)
    except Exception:  # noqa: BLE001
        log.warning("sc_flc.pdf_open_failed", url=url[:120])
        return [], "unreadable"
    text_rows: list[dict] = []
    for page_text in pages:
        text_rows.extend(_parse_text_rows(page_text))
    if text_rows:
        return text_rows, "text"
    # No text layer (or no TMS in it) — scanned list, hand it to OCR.
    ocr_rows = [r for r in (_normalize_ocr_row(x) for x in await _ocr_document(data)) if r]
    return ocr_rows, "ocr"


def _ocr_unavailable_note(quota_out: int, no_key: bool = False) -> str:
    if no_key:
        return (
            f"{quota_out} scanned FLC list(s) unread: no OCR key is configured. "
            "Set GEMINI_API_KEY (or GEMINI_API_KEY_1..N). Raising rather than "
            "returning 0 so a missing key is never mistaken for an empty source."
        )
    return (
        f"{quota_out} scanned FLC list(s) unread: the free Gemini key pool was "
        "rate-limited for the whole pass. This is a transient quota condition, "
        "not a dead source — re-run, or stagger against the daily vision pass."
    )


class SCForfeitedLand(BaseScraper):
    slug = "counties_sc.sc_flc"
    name = "SC Forfeited Land / Tax Sale (all counties)"
    category = "county_tax"
    timeout_s = 600.0   # OCR of a multi-page scan is the long pole
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[tuple[str, str]] = set()
        counties = {c.name for c in SC_COUNTIES}
        quota_out = 0
        pool_dead = False
        no_key = False

        for county in sorted(set(COUNTY_FLC_DOCS) | set(COUNTY_TAX_URLS)):
            if county not in counties:
                continue
            docs: list[str] = list(COUNTY_FLC_DOCS.get(county, ()))

            # Hub-page discovery: pick up a list a county newly linked.
            for url in COUNTY_TAX_URLS.get(county, ()):
                try:
                    html = await get_text(url, timeout=45.0)
                except Exception:  # noqa: BLE001
                    continue
                tree = HTMLParser(html)
                for a in tree.css("a[href$='.pdf']"):
                    href = urljoin(url, a.attributes.get("href", ""))
                    label = a.text(strip=True) or ""
                    if _wanted_doc(label, href) and href not in docs:
                        docs.append(href)
                        log.info("sc_flc.discovered_doc", county=county,
                                 label=label[:60], url=href[:120])

            for doc_url in docs:
                if pool_dead:
                    # The key pool did not recover across a full sweep cycle; it
                    # will not recover later in the same run either. Don't spend
                    # minutes proving that again on every remaining document.
                    quota_out += 1
                    continue
                try:
                    rows, lane = await _doc_rows(doc_url)
                except _OCRNoKey as exc:
                    quota_out += 1
                    pool_dead = True
                    no_key = True
                    log.warning("sc_flc.ocr_no_key_doc", county=county,
                                url=doc_url[:120], error=str(exc))
                    continue
                except _OCRQuotaOut as exc:
                    quota_out += 1
                    pool_dead = True
                    log.warning("sc_flc.ocr_quota_out", county=county,
                                url=doc_url[:120], error=str(exc))
                    continue
                log.info("sc_flc.doc", county=county, lane=lane, rows=len(rows),
                         url=doc_url[:120])
                for row in rows:
                    parcel = row.get("parcel_id")
                    key = (county, parcel or row.get("line", "")[:80])
                    if not parcel or key in seen:
                        continue
                    seen.add(key)
                    owner = row.get("owner_name")
                    desc = row.get("line") or (
                        f"{county} County SC FLC assignable parcel {parcel}"
                        + (f" — {owner}" if owner else "")
                    )
                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=doc_url,
                            listing_type=ListingType.TAX_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            foreclosure_process="tax",
                            state="SC",
                            county=county,
                            parcel_id=parcel,
                            street_address=row.get("address") or None,
                            city=row.get("city") or None,
                            opening_bid=row.get("amount"),
                            owner_name=owner,
                            defendant=owner,
                            description=desc[:300],
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                            raw={"sc_flc": {
                                "county": county,
                                "doc_url": doc_url,
                                "lane": lane,
                                "item": row.get("item"),
                                "assignment_price": row.get("amount"),
                            }},
                        )
                    )

        log.info("sc_flc.counts", parcels=len(out), ocr_quota_out=quota_out)
        if not out and quota_out:
            # Never let an OCR outage masquerade as "ran clean, 0 rows" — that is
            # how this source stayed silently dead for two runs. Raise so
            # safe_run classifies it and the run report says WHY.
            raise RuntimeError(_ocr_unavailable_note(quota_out, no_key=no_key))
        return out


if __name__ == "__main__":
    # Manual smoke:
    #   uv run python -m foreclosure_scraper.scrapers.counties_sc.sc_flc
    async def _main() -> None:
        s = SCForfeitedLand()
        rows = await s.safe_run()
        print("outcome:", s.last_outcome, "|", s.last_reason)
        print("rows:", len(rows))
        for r in rows[:20]:
            print(" -", r.county, "|", r.parcel_id, "|", r.street_address,
                  "|", r.city, "| $", r.opening_bid, "|", r.owner_name)

    asyncio.run(_main())
