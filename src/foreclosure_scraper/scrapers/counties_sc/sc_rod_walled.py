"""SC Register of Deeds walled sites — Beaufort, Jasper, Clarendon.

Live-reverified 2026-10-14 (the prior Playwright/generic-SPA-table-scraping
implementation was replaced; see each county's section below). This file was
flagged by docs/source_completeness_audit_2026-10-13.md as needing the
owner's own login for all three counties, on the strength of the sibling
`sc_rod_acclaim.py` (Pickens AcclaimWeb) finding. That assumption does NOT
hold uniformly here -- the three counties turned out to need three different
answers:

Beaufort: "BrowserViewDMP" (New Vision Systems), NO WAF, and -- confirmed
  live via this deployment's OWN api/search/clientinfo, not assumed from the
  shared vendor code -- NO login, NO reCAPTCHA, NO field encryption either
  (`authentication":"0"`, `"useRecaptchaV3":null`, `"encryptData":"0"`). The
  real gap was that this file's old generic Playwright table-scraper never
  matched Beaufort's ag-Grid Angular SPA (not plain `<table><tr>` rows) AND
  never touched the per-document PDF at all. Both fixed by calling the
  vendor's own free JSON API directly (rod/beaufort_dmp.py) -- no browser
  needed for Beaufort at all now.

Jasper: Cloudflare at the edge -- but ALSO a real, independent Google
  reCAPTCHA v2 gate ("Please complete the CAPTCHA to enter this site",
  g-recaptcha sitekey 6LfblzYqAAAAAFNl9g-RwU5zbI97HFqwWbhoD4Rb) on the
  Land Records search tab itself, confirmed live 2026-10-14 with nodriver
  already past Cloudflare's own edge challenge (clicking "Add New Tab" ->
  "Land Records" surfaces the CAPTCHA modal before any search form
  appears). This is a second, independent wall from a different vendor
  (Courthouse Computer Systems) than Clarendon's Cloudflare-only AcclaimWeb.
  GENUINELY WALLED -- solving a real CAPTCHA is out of scope here, same as
  every other genuinely-walled source in this codebase. No code changes;
  kept queued under the audit doc's "Needs YOU logged in" section.

Clarendon: Cloudflare ONLY -- no second app-level CAPTCHA was ever hit, and
  it is the SAME AcclaimWeb vendor + free document API as Pickens
  (sc_rod_acclaim.py / rod/acclaim.py). This codebase's existing nodriver
  wall-bypass tier (wall_bypass.py / browser_utils.py -- already used by
  e.g. sc_public_index.py, chester_delinquent_tax.py) clears Clarendon's
  challenge; once cleared, the exact same search/GridResults +
  Image/DocumentPdfAllPages/{TransactionItemId} calls Pickens uses work
  identically as in-page fetch() calls issued from that cleared tab (see
  rod/acclaim.discover_recent_nods_via_browser). Live-verified against 4
  real distress documents + 2 controls, all real %PDF-1.4 bytes. The PDF
  endpoint itself is ALSO behind the same Cloudflare wall (unlike Pickens,
  where it is open to anyone) -- it is NOT stamped into
  raw['documents']/['document_url'] the generic, GET-only enrich_doc_ocr.py
  pass would try to fetch cold and simply 403 against; it is recorded
  instead under raw['clarendon_pdf_fetch'] with an explicit note that it
  needs this same Cloudflare-cleared session, not a bare GET.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...rod import acclaim, beaufort_dmp

log = structlog.get_logger()

CLARENDON_BASE = "https://acclaimprod.clarendoncountygov.org/acclaimweb"
CLARENDON_LOOKBACK_DAYS = 45

# Jasper: Courthouse Computer Systems, Cloudflare + a real Google reCAPTCHA v2
# gate on the search feature itself. See the module docstring for the live
# evidence. Kept here (rather than deleted) so the wall is self-documenting
# in the code, the same convention this codebase uses for every other
# confirmed-genuine wall.
JASPER_BASE = "https://us6.courthousecomputersystems.com/jasperSC"
JASPER_WALL_NOTE = (
    "Cloudflare edge cleared by nodriver, but the Land Records search tab "
    "itself is gated by a real Google reCAPTCHA v2 ('Please complete the "
    "CAPTCHA to enter this site', sitekey 6LfblzYqAAAAAFNl9g-RwU5zbI97HFqwWbhoD4Rb) "
    "-- confirmed live 2026-10-14. Genuinely walled; not automated."
)


class ScRodWalledScraper(BaseScraper):
    """SC ROD sites — Beaufort (free JSON API, no browser), Clarendon
    (Cloudflare, cleared via this codebase's existing nodriver tier),
    Jasper (genuinely walled — Cloudflare + a real reCAPTCHA v2 gate)."""

    slug = "counties_sc.sc_rod_walled"
    name = "SC ROD Walled Sites"
    category = "rod"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        beaufort = await self._fetch_beaufort()
        results.extend(beaufort)
        log.info("sc_rod_walled.county_done", county="beaufort", found=len(beaufort))

        log.info("sc_rod_walled.county_skipped_genuine_wall", county="jasper",
                 note=JASPER_WALL_NOTE)

        clarendon = await self._fetch_clarendon()
        results.extend(clarendon)
        log.info("sc_rod_walled.county_done", county="clarendon", found=len(clarendon))

        return results

    # -- Beaufort: free JSON API, no browser at all -------------------------

    async def _fetch_beaufort(self) -> list[Listing]:
        out: list[Listing] = []
        try:
            docs = await beaufort_dmp.discover_recent_distress(state="SC", county="Beaufort")
        except Exception as exc:
            log.warning("sc_rod_walled.beaufort_failed", error=str(exc)[:200])
            return out
        for doc in docs:
            li = _beaufort_doc_to_listing(doc, self.slug,
                                           f"{beaufort_dmp.BASE}/api/search")
            if li:
                out.append(li)
        return out

    # -- Clarendon: Cloudflare, cleared via existing nodriver tier -----------

    async def _fetch_clarendon(self) -> list[Listing]:
        out: list[Listing] = []
        browser = None
        try:
            from ...wall_bypass import _html_to_text, _is_cloudflare_challenge
            from ...browser_utils import start_browser
        except ImportError:
            log.error("sc_rod_walled.clarendon_no_wall_bypass")
            return out

        for headless in (False, True):  # headed first: measured more reliable live
            try:
                browser = await start_browser(
                    headless=headless,
                    browser_args=[
                        "--no-sandbox", "--disable-gpu", "--window-size=1920,1080",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                tab = await browser.get(f"{CLARENDON_BASE}/search/SearchTypeDocType")
                await tab.wait(3)
                cleared = False
                for _ in range(10):
                    content = await tab.get_content()
                    if not _is_cloudflare_challenge(_html_to_text(content)):
                        cleared = True
                        break
                    await asyncio.sleep(2)
                if cleared:
                    break
                try:
                    browser.stop()
                except BaseException:
                    pass
                browser = None
            except Exception as exc:
                log.warning("sc_rod_walled.clarendon_browser_failed",
                            headless=headless, error=str(exc)[:200])
                if browser is not None:
                    try:
                        browser.stop()
                    except BaseException:
                        pass
                    browser = None

        if browser is None:
            log.warning("sc_rod_walled.clarendon_wall_not_cleared")
            return out

        try:
            docs = await acclaim.discover_recent_nods_via_browser(
                tab, "SC", "Clarendon", CLARENDON_BASE,
                days_back=CLARENDON_LOOKBACK_DAYS,
            )
            for doc in docs:
                li = _clarendon_doc_to_listing(doc, self.slug,
                                               f"{CLARENDON_BASE}/search/SearchTypeDocType")
                if li:
                    out.append(li)
        except Exception as exc:
            log.warning("sc_rod_walled.clarendon_sweep_failed", error=str(exc)[:200])
        finally:
            try:
                browser.stop()
            except BaseException:
                pass
        return out


# ---------------------------------------------------------------------------
# Listing building
# ---------------------------------------------------------------------------

_BEAUFORT_LISTING_TYPE: dict[str, ListingType] = {
    "lien": ListingType.TAX_LIEN,
    "mechanics_lien": ListingType.TAX_LIEN,
    "tax_lien": ListingType.TAX_LIEN,
    "probate_deed": ListingType.PROBATE_NOTICE,
    "bankruptcy": ListingType.BANKRUPTCY,
}


def _beaufort_doc_to_listing(doc, slug: str, source_url: str) -> Listing | None:
    bucket, _kind = beaufort_dmp.DISTRESS_CODES.get(doc.doc_type, (None, None))
    lt = _BEAUFORT_LISTING_TYPE.get(bucket)
    if lt is None:
        return None
    rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
    desc = (f"{doc.doc_type} recorded {rec}: {(doc.grantor or '?').strip()}"
            f"{' (' + doc.notes + ')' if doc.notes else ''}")
    raw: dict[str, Any] = dict(doc.raw or {})
    raw["rod"] = {"doc_type": doc.doc_type, "grantor": doc.grantor, "grantee": doc.grantee,
                  "book": doc.book, "page": doc.page, "instrument": doc.instrument_no,
                  "recorded": rec}
    if bucket == "probate_deed":
        raw["relationship_signal"] = {"kind": "probate", "keyword": doc.doc_type,
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    return Listing(
        source=slug, source_url=source_url,
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state=doc.state, county=doc.county,
        defendant=(doc.grantor or "").strip() or None,
        case_number=(doc.instrument_no or "").strip() or None,
        legal_description=(doc.notes or "").strip() or None,
        description=desc,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


def _clarendon_doc_to_listing(doc, slug: str, source_url: str) -> Listing | None:
    s = (doc.doc_type or "").upper()
    if "DIST" in s or "DEATH" in s:
        lt = ListingType.PROBATE_NOTICE
        kind = "probate"
    elif "LIEN" in s or "MECH" in s:
        lt = ListingType.TAX_LIEN
        kind = "lien"
    elif "FORECLOS" in s or "TRUSTEE" in s or "LIS PENDENS" in s or "NOTICE OF SALE" in s:
        lt = ListingType.LIS_PENDENS
        kind = "foreclosure"
    else:
        return None
    rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
    desc = (f"{doc.doc_type} recorded {rec}: {(doc.grantor or '?').strip()}"
            f"{' (' + doc.notes + ')' if doc.notes else ''}")
    raw: dict[str, Any] = {"rod": {"doc_type": doc.doc_type, "grantor": doc.grantor,
                                   "grantee": doc.grantee, "book": doc.book, "page": doc.page,
                                   "instrument": doc.instrument_no, "recorded": rec},
                           "acclaim_rod": True}
    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": doc.doc_type,
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    # The free scanned-document PDF exists at this URL (same AcclaimWeb
    # pattern as Pickens) but -- unlike Pickens -- it sits behind Clarendon's
    # own Cloudflare wall: a cold GET (what enrich_doc_ocr.py's generic,
    # httpx-only fetch does) gets a 403 challenge page, not the PDF. Recorded
    # honestly as a browser-gated recipe, NOT stamped into
    # raw['documents']/['document_url'] (document_links.stamp_documents),
    # which would silently feed that generic pass a Cloudflare interstitial.
    pdf_url = (doc.raw or {}).get("document_pdf_url")
    if pdf_url:
        raw["clarendon_pdf_fetch"] = {
            "method": "GET", "url": pdf_url,
            "requires": "cloudflare_cleared_session",
            "note": "cold httpx/curl-cffi 403s; only fetchable from a nodriver "
                    "tab that already cleared this county's Cloudflare challenge "
                    "(see rod.acclaim.discover_recent_nods_via_browser).",
        }
    return Listing(
        source=slug, source_url=source_url,
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state=doc.state, county=doc.county,
        parcel_id=doc.parcel_id,
        defendant=(doc.grantor or "").strip() or None,
        case_number=(doc.instrument_no or "").strip() or None,
        legal_description=(doc.notes or "").strip() or None,
        description=desc,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )
