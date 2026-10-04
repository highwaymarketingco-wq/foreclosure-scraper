"""Laurens County SC — Tax Sale Overage Claim List.

Laurens County publishes a live-maintained, multi-year PDF of unclaimed
tax-sale surplus funds: when a delinquent parcel sells at auction for MORE
than the taxes owed, the excess ("overage") is owed back to the FORMER
owner, same mechanism as counties_sc.york_overage_claims and
counties_sc.orangeburg_overage_claims.

  https://www.laurenscountysc.gov/departments/treasurer/forms_and_documents.php
  -> "2021-2024 Overage List" document link (DocumentCenter equivalent is a
     CivicPlus "Forms and Documents" widget; the real file currently lives at
     https://www.laurenscountysc.gov/Images/Documents/Departments/Treasurer/
     2021_2024%20Overage%20Lists.pdf -- note it resolves relative to the site
     ROOT, not the treasurer sub-path, because the page sets a <base> tag;
     urljoin() against the page URL alone gives a WRONG, 404ing URL).

CAUTION -- a dead-domain trap found live 2026-10-04: the old
`laurenscounty.us` domain (still the top Google result for
"Laurens County delinquent tax", and still the host a stale-but-ranking PDF
link from that domain points at) no longer belongs to the county at all --
it now 301-redirects to an unrelated third-party medical practice site
(rockvilleobgyn.com) sitting behind a Cloudflare challenge. Confirmed live
with a real browser render. The CURRENT, real site is `laurenscountysc.gov`.
Do not resurrect a `laurenscounty.us` URL here.

UNLIKE York's and Orangeburg's text-layer PDFs, Laurens's list is a SCANNED
image PDF -- confirmed live 2026-10-04 (pypdf extracts 0 characters on all 4
pages, each page carries exactly one full-page JPEG XObject). Visually
inspected all 4 rendered pages directly: each page is ONE TAX-SALE YEAR's
table (page 1 = "DECEMBER 8, 2021 TAX SALE OVERAGE", page 2 = "DECEMBER 7,
2022", pages 3-4 continue the same shape for 2023/2024), columns ITEM# / MAP#
(dashed TMS, e.g. "906-10-02-022") / OWNER OF PROPERTY / OVERAGE. Co-owners
or heirs sit on their OWN row directly under the claim with ITEM#/MAP#/
OVERAGE left blank on that continuation row (e.g. item 1412's claim has FOUR
names: JONES ANNIE, MOBLEY VALERIE, MOBLEY ERIC L, SIMPSON ERNEST, all one
claim) -- the OCR prompt below asks Gemini to fold those into one
semicolon-joined owner_name per item, matching how York's text parser already
treats a compound "A & B" name as a single string for one claim.

Goes through the same FREE, key-rotating Gemini OCR pool as
counties_sc.sc_flc (one page at a time -- whole-document OCR is known to
silently truncate, see sc_flc.py's docstring), reusing
enrichment_vision._parse_gemini_keys for the key pool. Live-verified
2026-10-04: a real OCR pass against this exact file correctly transcribed
page 1's 31 claims including the multi-owner item 1412 and item 2945 rows.

Free, public, no login, no CAPTCHA, no disclaimer click-through required to
reach this particular document (unlike Aiken, see
counties_sc.aiken_delinquent_tax's sibling investigation note in
docs/HERMES.md's history -- Aiken's disclaimer gates only a blank claim FORM,
no roster; Laurens needs no disclaimer at all for this PDF).
Slug: counties_sc.laurens_overage_claims
Category: county_tax
ListingType: TAX_SALE_OVERAGE
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
from datetime import datetime
from typing import Iterable, Optional

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...parcel_cache import lookup as _parcel_lookup

log = structlog.get_logger()

HUB_URL = "https://www.laurenscountysc.gov/departments/treasurer/forms_and_documents.php"
#: Direct fallback, live-verified 2026-10-04, used only if hub-page discovery
#: (which reads the real <a> href off the live page, avoiding the relative-
#: URL trap described in the module docstring) fails outright.
FALLBACK_DOC_URL = (
    "https://www.laurenscountysc.gov/Images/Documents/Departments/Treasurer/"
    "2021_2024%20Overage%20Lists.pdf"
)

TMS_RE = re.compile(r"\b\d{2,4}-\d{2}-\d{2}-\d{3}\b")
MONEY_RE = re.compile(r"\$?\s*([\d,]+\.\d{2})")

OCR_ENABLED = os.environ.get("LAURENS_OVERAGE_OCR", "1") != "0"
OCR_MODEL = os.environ.get("LAURENS_OVERAGE_OCR_MODEL",
                           os.environ.get("DOC_OCR_MODEL", "gemini-2.5-flash"))
_OCR_SWEEPS = int(os.environ.get("LAURENS_OVERAGE_OCR_SWEEPS", "3"))
_OCR_COOLDOWN_S = float(os.environ.get("LAURENS_OVERAGE_OCR_COOLDOWN_S", "35"))
_OCR_CALL_TIMEOUT_S = 60.0

_OCR_PROMPT = (
    "This page is one year's table from a South Carolina county's Tax Sale "
    "Overage (unclaimed surplus funds) list. The header names the tax sale "
    "date, e.g. 'DECEMBER 8, 2021 TAX SALE OVERAGE'. Columns are ITEM#, "
    "MAP# (a dashed tax map number like 906-10-02-022), OWNER OF PROPERTY, "
    "and OVERAGE (a dollar amount). Some claims list MULTIPLE owners/heirs "
    "stacked on separate lines directly below the claim, with ITEM#/MAP#/"
    "OVERAGE left blank on those continuation lines -- join every name for "
    "that one claim into a single owner_name string separated by '; '. "
    'Return ONLY JSON: {"tax_sale_date":"","rows":[{"item":"","map_number":"",'
    '"owner_name":"","amount":""}]}. Use an empty string for any value not '
    "printed. Do not invent rows; skip the header and any fully blank row."
)


def _money(text: str) -> Optional[float]:
    m = MONEY_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _is_quota(msg: str) -> bool:
    m = (msg or "").lower()
    return any(s in m for s in ("quota", "rate limit", "429", "resource_exhausted", "exceeded"))


class _OCRQuotaOut(Exception):
    """Every key in the free pool is rate-limited right now."""


class _OCRNoKey(_OCRQuotaOut):
    """No OCR key is configured at all -- distinct from quota-out so the
    operator note can tell "add a key" apart from "wait and retry"."""


def _split_pdf_pages(data: bytes) -> list[bytes]:
    """One single-page PDF per page -- OCR quality collapses on whole
    documents (same finding sc_flc.py made for Anderson's scanned lists)."""
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


async def _ocr_page(page_pdf: bytes, keys: list[str]) -> Optional[dict]:
    """OCR one page through the free Gemini pool, rotating keys past quota.
    Returns {"tax_sale_date": str, "rows": [...]} or None on a hard provider
    error. Raises _OCRQuotaOut when every key is still limited after every
    sweep -- the caller must not mistake that for "page has no data"."""
    try:
        from google import genai
        from google.genai import types as t
    except ImportError:
        log.warning("laurens_overage.ocr_sdk_missing", hint="pip install google-genai")
        return None
    for sweep in range(_OCR_SWEEPS):
        for key in keys:
            try:
                client = genai.Client(api_key=key)
                resp = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=OCR_MODEL,
                        contents=[
                            t.Part.from_bytes(data=page_pdf, mime_type="application/pdf"),
                            _OCR_PROMPT,
                        ],
                        config=t.GenerateContentConfig(
                            temperature=0, max_output_tokens=40000,
                            response_mime_type="application/json"),
                    ),
                    timeout=_OCR_CALL_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                log.warning("laurens_overage.ocr_call_timeout", key=key[:8])
                continue
            except Exception as exc:  # noqa: BLE001
                if _is_quota(str(exc)):
                    continue
                log.warning("laurens_overage.ocr_error", error=str(exc)[:160])
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
                return json.loads(raw)
            except (json.JSONDecodeError, AttributeError):
                log.warning("laurens_overage.ocr_bad_json", head=raw[:120])
                return None
        if sweep + 1 < _OCR_SWEEPS:
            log.info("laurens_overage.ocr_pool_cooling", sweep=sweep + 1,
                     keys=len(keys), sleep_s=_OCR_COOLDOWN_S)
            await asyncio.sleep(_OCR_COOLDOWN_S)
    raise _OCRQuotaOut(f"all {len(keys)} Gemini keys rate-limited")


async def _ocr_document(data: bytes, max_pages: int = 20) -> list[dict]:
    """OCR the scanned overage list page by page. Each returned dict is one
    page's {"tax_sale_date", "rows": [...]}. Raises _OCRNoKey/_OCRQuotaOut
    (never returns [] for those) so an unread document is never mistaken for
    a clean zero."""
    if not OCR_ENABLED:
        return []
    from ...enrichment_vision import _parse_gemini_keys
    keys = _parse_gemini_keys()
    if not keys:
        log.warning("laurens_overage.ocr_no_key",
                    hint="set GEMINI_API_KEY(_1..) to read the scanned overage list")
        raise _OCRNoKey("no Gemini key configured; scanned overage list unread")
    try:
        pages = _split_pdf_pages(data)
    except Exception:  # noqa: BLE001
        log.warning("laurens_overage.pdf_split_failed", exc_info=True)
        return []
    out: list[dict] = []
    for page_pdf in pages[:max_pages]:
        try:
            got = await _ocr_page(page_pdf, keys)
        except _OCRQuotaOut:
            if out:
                log.warning("laurens_overage.ocr_partial", pages_read=len(out))
                return out
            raise
        if got is None:
            break
        if got.get("rows"):
            out.append(got)
    return out


def _normalize_row(tax_sale_date: str, row: dict) -> Optional[dict]:
    map_number = str(row.get("map_number") or "").strip()
    m = TMS_RE.search(map_number) or TMS_RE.search(str(row.get("item") or ""))
    if not m:
        return None
    owner = str(row.get("owner_name") or "").strip()
    if not owner:
        return None
    amount = _money(str(row.get("amount") or ""))
    if amount is None or amount <= 0:
        return None
    return {
        "item": str(row.get("item") or "").strip() or None,
        "map_number": m.group(0),
        "owner_name": owner,
        "amount": amount,
        "tax_sale_date": tax_sale_date or None,
    }


async def _discover_doc_url(c: httpx.AsyncClient) -> str:
    """Read the real 'Overage List' href off the live Forms and Documents
    page. Falls back to FALLBACK_DOC_URL (which will start 404ing the day the
    county rotates the filename again) only if the page itself is
    unreachable or no longer carries a matching link."""
    try:
        resp = await c.get(HUB_URL, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("laurens_overage.hub_fetch_fail", error=str(exc)[:160])
        return FALLBACK_DOC_URL
    try:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(resp.text)
    except Exception:  # noqa: BLE001
        return FALLBACK_DOC_URL
    # The page sets a <base> tag pointing at the site root, so a relative
    # href must be resolved against the RESPONSE's final URL only if there is
    # no <base> -- selectolax doesn't resolve <base> for us, so do it by hand.
    base_el = tree.css_first("base[href]")
    base = base_el.attributes.get("href") if base_el else str(resp.url)
    for a in tree.css("a[href]"):
        label = a.text(strip=True) or ""
        if re.search(r"overage\s*list", label, re.I):
            from urllib.parse import urljoin
            return urljoin(base or str(resp.url), a.attributes.get("href", ""))
    return FALLBACK_DOC_URL


class LaurensOverageClaims(BaseScraper):
    slug = "counties_sc.laurens_overage_claims"
    name = "Laurens County SC Overage Claim List"
    category = "county_tax"
    timeout_s = 300.0   # OCR of a multi-page scan is the long pole
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
            doc_url = await _discover_doc_url(c)
            try:
                resp = await c.get(doc_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60.0)
                resp.raise_for_status()
                data = resp.content
            except Exception as exc:  # noqa: BLE001
                log.warning("laurens_overage.doc_fetch_fail", url=doc_url, error=str(exc)[:160])
                return out

        if data[:4] != b"%PDF":
            log.warning("laurens_overage.not_pdf", url=doc_url, head=data[:8])
            return out

        try:
            pages = await _ocr_document(data)
        except _OCRNoKey as exc:
            raise RuntimeError(
                "Laurens overage list is a scanned PDF unread: no OCR key is "
                "configured. Set GEMINI_API_KEY (or GEMINI_API_KEY_1..N). "
                "Raising rather than returning 0 so a missing key is never "
                "mistaken for an empty source."
            ) from exc
        except _OCRQuotaOut as exc:
            raise RuntimeError(
                "Laurens overage list unread: the free Gemini key pool was "
                "rate-limited for the whole pass. Transient quota condition, "
                "not a dead source -- re-run, or stagger against the daily "
                "vision pass."
            ) from exc

        now = datetime.utcnow()
        seen: set[str] = set()
        for page in pages:
            tax_sale_date = str(page.get("tax_sale_date") or "").strip()
            for raw_row in page.get("rows") or []:
                rec = _normalize_row(tax_sale_date, raw_row)
                if not rec:
                    continue
                key = f"{rec['map_number']}|{rec['tax_sale_date']}"
                if key in seen:
                    continue
                seen.add(key)

                situs = None
                try:
                    situs = _parcel_lookup("Laurens", rec["map_number"], "SC")
                except Exception:  # noqa: BLE001 — situs is a nice-to-have, never fatal
                    situs = None
                street_address = situs.get("address") if situs else None

                out.append(Listing(
                    source=self.slug,
                    source_url=doc_url,
                    listing_type=ListingType.TAX_SALE_OVERAGE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Laurens",
                    parcel_id=rec["map_number"],
                    owner_name=rec["owner_name"],
                    street_address=street_address,
                    # sale_date intentionally left unset -- see
                    # york_overage_claims.py's identical note and this slug's
                    # entry in main.py.DATELESS_OK_SOURCES. The ORIGINAL
                    # tax-sale date is preserved in raw instead.
                    description=(f"Tax-sale overage of ${rec['amount']:,.2f} owed to former "
                                 f"owner {rec['owner_name']} (parcel {rec['map_number']}, "
                                 f"item {rec['item'] or '?'}, "
                                 f"{rec['tax_sale_date'] or 'unknown-date'} tax sale)."),
                    first_seen=now,
                    last_seen=now,
                    raw={"tax_sale_overage": {
                        "amount": rec["amount"],
                        "tax_sale_date": rec["tax_sale_date"],
                        "item": rec["item"],
                        "map_number": rec["map_number"],
                    }},
                ))

        log.info("laurens_overage.done", pages=len(pages), usable=len(out))
        return out


if __name__ == "__main__":
    # Manual smoke: uv run python -m foreclosure_scraper.scrapers.counties_sc.laurens_overage_claims
    async def _main() -> None:
        s = LaurensOverageClaims()
        rows = await s.safe_run()
        print("outcome:", s.last_outcome, "|", s.last_reason)
        print("rows:", len(rows))
        for r in rows[:20]:
            print(" -", r.parcel_id, "|", r.owner_name, "| $",
                  r.raw.get("tax_sale_overage", {}).get("amount"), "|",
                  r.raw.get("tax_sale_overage", {}).get("tax_sale_date"))

    asyncio.run(_main())
