"""SC county delinquent-tax SALE lists (annual, published ~November).

SC counties publish the parcels going to the annual delinquent-tax sale as a
PDF list (owner name + TMS map number + property description/address). This is
strong pre-sale distress: the owner owes back taxes and the property is headed
to auction unless redeemed.

These lists are SEASONAL — posted ~Nov, sale ~Dec, redemption runs ~12 months —
so this scraper is gated to the Oct–Jan window (active_months) and lies dormant
the rest of the year, auto-resuming in November. Verified parser against the
live Cherokee 2023 list (format: `item# NAME TMS description`).

Free, plain HTTP PDF (pdfplumber), no anti-bot, ToS-OK (county treasurer pages).
Extensible: add Pickens/Spartanburg by dropping their URL + TMS pattern in
SC_DELINQUENT once their current-year list URL is confirmed.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# county -> {page (landing page to discover the current list PDF link), url
# templates ({year}) as fallback, TMS regex}. Discovering the link from the page
# is robust to the filename changing year to year; templates are the fallback.
SC_DELINQUENT: dict[str, dict] = {
    "Cherokee": {
        "page": "https://cherokeecountysc.gov/delinquent-tax/tax-sale-bidders/",
        "urls": [
            "https://cherokeecountysc.gov/wp-content/uploads/{year}/11/{year}-Delinquent-Tax-List.pdf",
            "https://cherokeecountysc.gov/wp-content/uploads/{year}/12/{year}-Delinquent-Tax-List.pdf",
        ],
        "tms": r"\d{3}-\d{2}-\d{2}-[\d.]+",
    },
}


def _discover_pdf(page_html: str, base: str, year: int) -> list[str]:
    """Find candidate list-PDF links on a county delinquent-tax page, ranked:
    current-year + 'delinquent/tax list' first."""
    hrefs = re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', page_html, re.I)
    from urllib.parse import urljoin
    cands = []
    for h in hrefs:
        u = urljoin(base, h)
        low = u.lower()
        score = 0
        if str(year) in low:
            score += 4
        if str(year - 1) in low:
            score += 2
        if "delinquent" in low or "tax-list" in low or "tax_list" in low or "ledger" in low:
            score += 3
        if "bidder" in low or "procedure" in low or "registration" in low:
            score -= 3  # procedures doc, not the parcel list
        cands.append((score, u))
    return [u for s, u in sorted(cands, key=lambda x: -x[0]) if s > 0]

_ITEM_RE = re.compile(r"^\s*(\d{4,6}|NEW OWNER)\s+(.+)$")


def parse_list(text: str, county: str, tms_pat: str, url: str) -> list[Listing]:
    """Parse a delinquent-tax list PDF's text into per-parcel Listings.
    Lines look like: `00005 ADAMS ISAAC 029-00-00-028.001 1240 LOVE SPRINGS`."""
    tms_re = re.compile(rf"({tms_pat})")
    out: list[Listing] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        line = line.strip()
        m = _ITEM_RE.match(line)
        if not m:
            continue
        tm = tms_re.search(line)
        if not tm:
            continue
        tms = tm.group(1)
        # name = between the item-number token and the TMS; desc = after the TMS.
        head = line[m.start(2): tm.start()].strip() if tm.start() > m.start(2) else ""
        # m.group(1) is the item# or "NEW OWNER"; the name is in head minus that.
        name = re.sub(r"^\s*(NEW OWNER)\s*", "", head).strip() or None
        desc = line[tm.end():].strip() or None
        key = f"{tms}|{name}"
        if key in seen:
            continue
        seen.add(key)
        out.append(Listing(
            source="counties_sc.sc_delinquent_tax_list",
            source_url=url,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC", county=county,
            street_address=desc,           # county "description" is the situs/address
            defendant=name,                # delinquent owner
            parcel_id=tms,
            description=re.sub(r"\s+", " ", line)[:300],
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw={"sc_delinquent_tax": {"county": county, "item_line": line[:200]}},
        ))
    return out


def _pdf_text(data: bytes) -> str:
    try:
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:
        log.warning("sc_delinquent.pdf_parse_fail", error=str(exc)[:160])
        return ""


class SCDelinquentTaxList(BaseScraper):
    slug = "counties_sc.sc_delinquent_tax_list"
    name = "SC County Delinquent Tax Sale Lists (annual PDF)"
    category = "county_tax"
    expected_min_count = 0
    requires_render = False
    timeout_s = 120.0
    active_months = (10, 11, 12, 1)  # SC lists post ~Nov; dormant off-season

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        year = datetime.utcnow().year
        for county, cfg in SC_DELINQUENT.items():
            # Build the candidate URL list: discovered page links first (robust
            # to filename changes), then the year-templated fallbacks.
            candidates: list[str] = []
            if cfg.get("page"):
                try:
                    html = await get_text(cfg["page"], headers={"User-Agent": "Mozilla/5.0"}, timeout=40.0)
                    candidates += _discover_pdf(html, cfg["page"], year)
                except Exception:
                    pass
            for tmpl in cfg.get("urls", []):
                for y in (year, year - 1):
                    candidates.append(tmpl.format(year=y))
            seen_url: set[str] = set()
            for url in candidates:
                if url in seen_url:
                    continue
                seen_url.add(url)
                try:
                    data = await get_bytes(url, timeout=60.0)
                except Exception:
                    continue
                if not (data and data[:4] == b"%PDF"):
                    continue
                rows = parse_list(_pdf_text(data), county, cfg["tms"], url)
                if rows:  # found the actual parcel list (not a procedures doc)
                    out.extend(rows)
                    log.info("sc_delinquent.county_ok", county=county, url=url, count=len(rows))
                    break
        log.info("sc_delinquent.done", count=len(out))
        return out
