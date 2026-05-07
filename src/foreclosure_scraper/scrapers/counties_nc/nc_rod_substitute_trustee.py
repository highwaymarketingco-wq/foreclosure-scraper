"""NC Register of Deeds — Substitute Trustee Deed + Trustee's Deed
Upon Sale indexer scraper, Buncombe-only after the 2026-05-07 scope
rollback.

Two distinct value sources from the same portal:

  PRE-SALE  Substitute Trustee Deed + Notice of Sale recordings —
             precede the SP foreclosure docket by 2-6 weeks. Earliest
             publicly-available indicator that a foreclosure is
             imminent (lead source).

  POST-SALE Trustee's Deed Upon Sale recordings — these are the
             documents that transfer the property to the winning
             bidder. They include the deed-tax stamp which encodes the
             sold price (NC charges $1 per $500 of consideration, so
             stamp_amount × 500 = sold_price). Feeds the
             foreclosure_sold_comps pool.

The Buncombe portal (https://buncombe-recordings.permitium.com/) is a
Permitium hosted recording-search SaaS. Behind a JS app shell + likely
Cloudflare bot mitigation — needs Scrapling stealth to render.

This scraper currently runs in DIAGNOSTIC mode: it tries the stealth
flow, logs what it sees (page title, form selectors found, table row
counts), and falls back to skeleton if the structure doesn't match
the documented Permitium pattern. Production parsing will be added
once we have CI logs from the live portal showing the actual element
structure.

Set NC_ROD_DEBUG=1 to log raw HTML excerpt for inspection.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


# Per-county configuration. Document-type values are the actual filter
# strings each portal accepts — verified from the indexer dropdown
# options as of May 2026. 2026-05-07 scope rollback: dropped Mecklenburg
# / Wake / Durham portals; only Buncombe (in user's WNC core scope)
# remains. Portal configs for the dropped counties are preserved here
# in code comments below for future re-activation if scope changes.
#
# DEACTIVATED PORTALS (kept as comments for fast re-activation):
#   Mecklenburg: https://meckrod.manatron.com/RealEstate/SearchEntry.aspx (manatron)
#     doc_types: SUBSTITUTE TRUSTEE DEED, NOTICE OF SALE, CLAIM OF LIEN, TRUSTEES DEED
#   Wake: https://services.wakegov.com/booksweb/PublicFreeMonitorSearch.aspx (aumentum)
#     doc_types: SUBSTITUTE TRUSTEE DEED, NOTICE OF SALE, CLAIM OF LIEN
#   Durham: https://rod-public.dconc.gov/Search.aspx (aumentum)
#     doc_types: SUBSTITUTE TRUSTEE DEED, NOTICE OF SALE, CLAIM OF LIEN
COUNTY_PORTALS: dict[str, dict] = {
    "Buncombe": {
        "url": "https://buncombe-recordings.permitium.com/",
        "search_path": "/searches/new",
        "doc_types": [
            "SUBSTITUTE TRUSTEE DEED",
            "NOTICE OF SALE",
        ],
        "vendor": "permitium",
    },
}


# ---- Permitium parsing patterns (best-effort, refined as CI logs land) ----

# NC deed-tax stamp: $1 per $500 of consideration. So a "EXCISE TAX:
# $50.00" stamp implies a $25,000 sale price.
EXCISE_TAX_RE = re.compile(
    r"(?:excise\s+tax|stamp(?:ed)?\s+tax|consideration\s+stamp)\s*[:=]?\s*"
    r"\$\s*([\d,]+(?:\.\d{2})?)",
    re.I,
)
# Direct consideration line ("CONSIDERATION: $123,456.00")
CONSIDERATION_RE = re.compile(
    r"consideration\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I,
)
# Recording date / instrument date
DATE_RE = re.compile(
    r"\b(?:recorded|instrument|filed)\s*(?:on|date)?\s*[:=]?\s*"
    r"((?:\d{1,2}/\d{1,2}/\d{2,4})|(?:\w+\s+\d{1,2},?\s+\d{4}))",
    re.I,
)


def _sold_price_from_stamp(text: str) -> Optional[float]:
    """NC deed tax: $1 per $500 of consideration. Stamp_amount × 500 =
    sold price. Prefer explicit CONSIDERATION line if present."""
    m = CONSIDERATION_RE.search(text)
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
            if 100 <= v <= 10_000_000:
                return v
        except ValueError:
            pass
    m = EXCISE_TAX_RE.search(text)
    if m:
        try:
            stamp = float(m.group(1).replace(",", ""))
            v = stamp * 500
            if 100 <= v <= 10_000_000:
                return v
        except ValueError:
            pass
    return None


def _parse_permitium_results_html(html: str, county: str,
                                  source_url: str,
                                  doc_type: str) -> list[Listing]:
    """Parse a Permitium recording-search results HTML page.

    Permitium's results UI varies by tenant configuration, but the
    common pattern is:
      * Each recording = one row in a results table OR a result card div
      * Per-row data: instrument#, recorded date, parties (grantor/
        grantee), document type, book/page
      * Trustee's Deed Upon Sale rows include a deed-tax stamp value
        in a 'consideration' / 'excise tax' field, from which we
        derive sold price (NC charges $1 per $500 consideration).

    We use selectolax for fast HTML parsing + multiple selector
    fallbacks since Permitium's HTML structure varies. Best-effort.
    """
    out: list[Listing] = []
    try:
        from selectolax.parser import HTMLParser
    except ImportError:
        return out

    tree = HTMLParser(html)

    # Collect candidate "row" elements via the most common Permitium
    # structures. Falls through fallbacks until something hits.
    candidates: list = []
    for selector in (
        "table.results-table tbody tr",
        "table.search-results tbody tr",
        "table[id*='results'] tbody tr",
        "tr.result-row",
        "div.result-card, div.recording-row",
        "div[class*='result-item']",
        # Last-resort: ANY tr in any table on the page (filtered downstream)
        "table tbody tr",
    ):
        candidates = tree.css(selector)
        if candidates:
            log.info(
                "nc_rod.permitium_rows_found",
                county=county, selector=selector, count=len(candidates),
                doc_type=doc_type,
            )
            break

    if not candidates:
        log.info(
            "nc_rod.permitium_no_rows", county=county,
            note="No table/card rows matched any common Permitium selector. "
                 "Inspect nc_rod.permitium_landing log to see actual structure.",
        )
        return out

    # Per-row extraction. Combine the row's text and run regex against it
    # — robust to varying cell layouts since we just need: case#/instrument
    # ref, date, parties, money fields.
    instrument_re = re.compile(r"\b(?:Inst(?:rument)?|Doc(?:ument)?)\s*#?\s*[:=]?\s*(\d{6,})", re.I)
    book_page_re = re.compile(r"\b[Bb]ook\s*(\d+)[\s/,]+[Pp]age\s*(\d+)", re.I)
    party_re = re.compile(r"\b(?:Grantor|Defendant|Borrower)\s*[:=]?\s*([A-Z][\w &.,'\-]{2,80})", re.I)

    for node in candidates:
        try:
            row_text = (node.text(separator=" ", strip=True) or "").strip()
        except Exception:
            continue
        if len(row_text) < 20:
            continue

        # Filter: this row must mention the doc type we care about
        # (Substitute Trustee Deed / Notice of Sale / Trustee's Deed
        # Upon Sale). Skips header rows + unrelated documents on the
        # page.
        dt_lower = doc_type.lower()
        if dt_lower not in row_text.lower() and not any(
            k in row_text.lower() for k in (
                "substitute trustee", "notice of sale", "trustee's deed",
                "trustees deed", "claim of lien",
            )
        ):
            continue

        # Date — look for a date pattern in the row
        date_m = DATE_RE.search(row_text)
        recorded_date: datetime | None = None
        if date_m:
            try:
                from dateutil import parser as _dp
                recorded_date = _dp.parse(date_m.group(1), fuzzy=True)
            except (ValueError, TypeError):
                pass

        # Sold price (only meaningful for Trustee's Deed Upon Sale)
        sold_price = _sold_price_from_stamp(row_text)
        is_post_sale = (
            "trustee" in row_text.lower() and "deed" in row_text.lower()
            and ("upon sale" in row_text.lower() or sold_price is not None)
        )

        # Parties / debtor name
        defendant = None
        pm = party_re.search(row_text)
        if pm:
            defendant = pm.group(1).strip()[:200]

        # Instrument or book/page identifier — used as case_number proxy
        case_id = None
        im = instrument_re.search(row_text)
        if im:
            case_id = f"INST-{im.group(1)}"
        else:
            bm = book_page_re.search(row_text)
            if bm:
                case_id = f"BK{bm.group(1)}-PG{bm.group(2)}"

        if not (recorded_date or sold_price or case_id):
            continue  # nothing useful extracted

        raw_payload: dict = {
            "nc_rod_permitium": {
                "vendor": "permitium",
                "doc_type": doc_type,
                "raw_row_excerpt": row_text[:400],
                "recorded_date_iso": (recorded_date.isoformat()
                                       if recorded_date else None),
                "is_post_sale": is_post_sale,
            },
        }
        if sold_price is not None:
            # Top-level so enrichment_foreclosure_sold_comps reads it as
            # confirmed hammer price.
            raw_payload["actual_sold_price"] = sold_price

        out.append(Listing(
            source="counties_nc.nc_rod_substitute_trustee",
            source_url=source_url,
            listing_type=ListingType.FORECLOSURE_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county=county,
            case_number=case_id,
            defendant=defendant,
            sale_date=recorded_date if is_post_sale else None,
            opening_bid=sold_price,
            description=row_text[:500],
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw=raw_payload,
        ))

    log.info(
        "nc_rod.permitium_extracted",
        county=county, doc_type=doc_type,
        candidates=len(candidates), parsed=len(out),
    )
    return out


async def _scrapling_search_permitium(
    portal_url: str, doc_type: str, county: str, days_back: int = 60,
) -> tuple[str, list[Listing]]:
    """Drive a Permitium recording-search portal and return (raw_html,
    listings). Returns ("", []) when Scrapling not available or portal
    unreachable. Logs diagnostic info on every path so the first CI run
    surfaces the actual page structure even when parsing fails."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("nc_rod.scrapling_missing", portal=portal_url)
        return "", []

    # Try the search-results URL directly (some Permitium tenants accept
    # query-string filters); fall back to the landing page if 404.
    search_url = (
        f"{portal_url.rstrip('/')}/searches/results?"
        f"document_type={doc_type.replace(' ', '+')}&"
        f"date_from={(datetime.utcnow() - timedelta(days=days_back)).strftime('%Y-%m-%d')}&"
        f"date_to={datetime.utcnow().strftime('%Y-%m-%d')}"
    )

    html = ""
    for url_attempt in (search_url, portal_url):
        try:
            result = await StealthyFetcher.async_fetch(
                url_attempt,
                headless=True,
                network_idle=True,
                timeout=90000,
            )
            body = getattr(result, "body", b"")
            html_attempt = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
            if html_attempt and len(html_attempt) > 1000:
                html = html_attempt
                log.info(
                    "nc_rod.permitium_landing",
                    portal=portal_url, attempted=url_attempt,
                    html_bytes=len(html),
                    has_search_form=("<form" in html.lower() and "search" in html.lower()),
                    has_results_table=("<table" in html.lower() and "<tr" in html.lower()),
                    has_doc_type_filter="document_type" in html.lower() or "doc_type" in html.lower(),
                )
                break
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "nc_rod.permitium_fetch_failed",
                portal=portal_url, attempted=url_attempt,
                error=str(exc)[:200],
            )
            continue

    if not html:
        return "", []

    if os.environ.get("NC_ROD_DEBUG"):
        log.debug("nc_rod.html_excerpt", excerpt=html[:3000])

    listings = _parse_permitium_results_html(
        html, county=county, source_url=portal_url, doc_type=doc_type,
    )
    return html, listings


class NCRodSubstituteTrustee(BaseScraper):
    """NC Register of Deeds — substitute-trustee + notice-of-sale +
    trustee's-deed-upon-sale recordings (Buncombe only after scope
    rollback)."""

    slug = "counties_nc.nc_rod_substitute_trustee"
    name = "NC ROD Substitute Trustee + Trustee's Deed (Buncombe)"
    category = "register_of_deeds"
    expected_min_count = 0
    requires_apify = False
    # Permitium portal is JS app shell + likely Cloudflare; needs Scrapling.
    requires_render = True
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for county, cfg in COUNTY_PORTALS.items():
            portal_url = cfg["url"]
            for doc_type in cfg["doc_types"]:
                try:
                    html, listings = await _scrapling_search_permitium(
                        portal_url=portal_url,
                        doc_type=doc_type,
                        county=county,
                        days_back=60,
                    )
                    out.extend(listings)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "nc_rod.search_failed",
                        county=county, doc_type=doc_type,
                        error=str(exc)[:200],
                    )

        if not out:
            # Diagnostic emit so the run report is honest about why no
            # data: the stealth flow ran but didn't yet know how to
            # parse the live portal structure. Next iteration uses the
            # nc_rod.permitium_landing log to refine selectors.
            log.info(
                "nc_rod.no_listings_yet",
                counties=list(COUNTY_PORTALS),
                note=("Permitium search-form selectors not yet wired. "
                      "Check nc_rod.permitium_landing log entries from "
                      "this run for actual page structure to refine."),
            )
        return out
