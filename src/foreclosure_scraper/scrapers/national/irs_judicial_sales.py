"""IRS judicial / seized-property real-estate sales — irsauctions.gov.

The IRS (Treasury, PALS — Property Appraisal & Liquidation Specialists) runs a
free, public, no-login portal that lists JUDICIAL and seizure sales of REAL
PROPERTY seized to satisfy FEDERAL tax liens (26 U.S.C. §§ 6335 / 7403). This is
distinct from a county tax sale: the seller is the United States, title flows
from a federal Notice/Order of Sale, and the inventory spans the whole country,
so in-footprint (NC/SC) hits are sporadic but high-value. We keep the watcher
running with expected_min_count=0 and only emit NC/SC rows.

Access path (free, public, server-rendered Drupal HTML — NO login, NO CAPTCHA;
verified live 2026-08-17, root reachable ~40 KB, my older "walled" note is STALE):

  1. GET /auction/items -> the active-inventory index. Every property card links
     to an `/ad/<slug>` detail page. (The `/first-time-bidder` guess and a bare
     `/sales.html` do not exist; `/auction/items` is the real listing path.)
  2. GET /ad/<slug> for each -> the detail page. Fields are parsed from the
     rendered Drupal markup (there is NO public JSON API):
       - Asset Address: a `<address>` block ("<street><br>City,, ZIP ST<br>US").
       - "Date of Auction": a `<time datetime="...Z">` -> sale_date.
       - "Minimum Bid": field-minimum-bid decimal -> opening_bid.
       - "Notice Information" / "Asset Description" -> description.
       - "Sale Location": a second `<address>` block -> sale_location.
       - Order-of-Sale / Notice-of-Encumbrances / Mail-in-Bid-Form PDFs are
         harvested onto the Listing so the doc-OCR pass can read the exact
         encumbrance / legal-description detail off the federal notice.
  3. Filter to NC/SC by the parsed state; map city->county best-effort. Personal-
     property (watches/jewelry/vehicles) lots are skipped — real property only.

Verified 2026-08-17: 9 active lots (NM, FL, MA×4, PA, AR×2, plus one TX personal-
property lot). No NC/SC currently active, so a clean 0 is the expected off-
footprint outcome (ZERO_RESULT, not an error).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...http_client import get_text
from ...base_scraper import BaseScraper
from ...document_links import harvest_document_links, stamp_documents
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://www.irsauctions.gov"
_INDEX = f"{_BASE}/auction/items"

# Only emit rows in our core states. (City->county is best-effort below.)
_CORE_STATES = {"NC", "SC"}

_AD_RE = re.compile(r'href="(/ad/[^"#?]+)"', re.I)
_ADDR_BLOCK_RE = re.compile(
    r"field-property-address.*?<address[^>]*>(.*?)</address>", re.I | re.S
)
_SALE_LOC_RE = re.compile(
    r"field-sale-location.*?<address[^>]*>(.*?)</address>", re.I | re.S
)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_AUCTION_DATE_RE = re.compile(
    r"Date of Auction.*?<time datetime=\"([^\"]+)\"", re.I | re.S
)
_MIN_BID_RE = re.compile(
    r"field-minimum-bid.*?field__item[^>]*>\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I | re.S
)
# "City,, 72715 AR"  or  "City, 72715 AR"  (ZIP then two-letter state, at end)
_ZIP_STATE_RE = re.compile(r"(\d{5})(?:-\d{4})?\s+([A-Za-z]{2})\s*$")
# fallback "ST 72715"
_STATE_ZIP_RE = re.compile(r"\b([A-Za-z]{2})\b\s+(\d{5})(?:-\d{4})?")

# Title / notice text -> PropertyKind.
_KIND_PATTERNS = (
    (re.compile(r"vacant land|\bland\b|\bacreage\b|\bacres?\b", re.I), PropertyKind.LAND),
    (re.compile(r"multi[- ]?unit|multi[- ]?family|duplex|triplex|fourplex", re.I), PropertyKind.MULTI_FAMILY),
    (re.compile(r"row\s?house|town\s?house", re.I), PropertyKind.TOWNHOUSE),
    (re.compile(r"condo", re.I), PropertyKind.CONDO),
    (re.compile(r"mobile|manufactured", re.I), PropertyKind.MOBILE),
    (re.compile(r"commercial|office|warehouse|retail|industrial", re.I), PropertyKind.COMMERCIAL),
    (re.compile(r"single[- ]?family|starter home|residence|\bhome\b|house|bungalow", re.I), PropertyKind.SINGLE_FAMILY),
)
# Personal-property lots (not real estate) — skip entirely.
_PERSONAL_RE = re.compile(r"personal[- ]?property|watches|jewelry|purses|vehicle|firearm|artwork", re.I)


def _clean(s: str | None) -> str | None:
    if not s:
        return None
    s = _TAG_RE.sub("", s)
    s = s.replace("&#039;", "'").replace("&amp;", "&").replace("&nbsp;", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _float(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _county_for(city: str | None, state: str) -> str | None:
    """Best-effort city -> in-footprint county (None when unknown; row still emitted)."""
    if not city:
        return None
    try:
        from ..._upstate_city_to_county import upstate_county_for
        return upstate_county_for(city, state)
    except Exception:  # noqa: BLE001
        return None


def _parse_address(html: str) -> tuple[str | None, str | None, str | None, str | None] | None:
    """Return (street, city, state, zip) from the Asset Address block, or None."""
    m = _ADDR_BLOCK_RE.search(html)
    if not m:
        return None
    lines = [_clean(l) for l in _BR_RE.split(m.group(1))]
    lines = [l for l in lines if l and l.lower() != "united states"]
    if not lines:
        return None
    street = lines[0]
    city = state = zip_code = None
    for line in (lines[1:] or lines):
        zm = _ZIP_STATE_RE.search(line)
        if zm:
            zip_code, state = zm.group(1), zm.group(2).upper()
            city = line[: zm.start()].split(",")[0].strip() or None
            break
        sm = _STATE_ZIP_RE.search(line)
        if sm:
            state, zip_code = sm.group(1).upper(), sm.group(2)
            city = line[: sm.start()].split(",")[0].strip() or None
            break
    # Some rows repeat the full "street City, ST  ZIP" on line 0 — trim the tail
    # so street doesn't carry the city/state/zip.
    if street:
        if zip_code:
            street = re.sub(r"[,\s]+" + re.escape(zip_code) + r"(?:-\d{4})?.*$", "", street).strip()
        if state:
            street = re.sub(r"[,\s]+" + re.escape(state) + r"\b\.?\s*$", "", street, flags=re.I).strip()
        if city:
            street = re.sub(r"[,\s]+" + re.escape(city) + r"\s*$", "", street, flags=re.I).strip()
        street = street.rstrip(",").strip() or None
    return street, city, state, zip_code


def _parse_sale_date(html: str) -> datetime | None:
    m = _AUCTION_DATE_RE.search(html)
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    # Store naive UTC to match repo convention (datetime.utcnow()).
    if dt.tzinfo is not None:
        dt = datetime(*dt.utctimetuple()[:6])
    return dt


def _pdf_in(html: str, field: str) -> str | None:
    m = re.search(re.escape(field) + r'.*?href="([^"]+\.pdf[^"]*)"', html, re.I | re.S)
    return urljoin(_BASE, m.group(1)) if m else None


def _kind_for(*texts: str | None) -> PropertyKind:
    """Classify from the curated title first, then fall back to notice text."""
    for text in texts:
        if not text:
            continue
        for pat, kind in _KIND_PATTERNS:
            if pat.search(text):
                return kind
    return PropertyKind.UNKNOWN


def parse_detail(html: str, url: str) -> Listing | None:
    """Parse one /ad/ detail page into a Listing, or None if not NC/SC real property."""
    title = _clean(re.search(r'class="treas-page-title"[^>]*>(.*?)</span>', html, re.I | re.S).group(1)) \
        if re.search(r'class="treas-page-title"', html, re.I) else None
    if not title:
        tm = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        title = _clean(tm.group(1)).split("|")[0].strip() if tm else None
    hay = f"{title or ''} {url}"
    if _PERSONAL_RE.search(hay):
        return None  # personal-property lot, not real estate

    addr = _parse_address(html)
    if not addr:
        return None
    street, city, state, zip_code = addr
    if state not in _CORE_STATES:
        return None

    sale_date = _parse_sale_date(html)
    bid = _float(_MIN_BID_RE.search(html).group(1)) if _MIN_BID_RE.search(html) else None

    notice = _clean(
        (re.search(r"field-notice-information.*?field__item[^>]*>(.*?)</div>", html, re.I | re.S) or
         re.search(r"field-asset-description.*?field__item[^>]*>(.*?)</div>", html, re.I | re.S) or
         [None, None])[1] if re.search(r"field-(notice-information|asset-description)", html, re.I) else None
    )
    sale_loc = None
    slm = _SALE_LOC_RE.search(html)
    if slm:
        parts = [_clean(l) for l in _BR_RE.split(slm.group(1))]
        sale_loc = ", ".join(p for p in parts if p and p.lower() != "united states") or None

    kind = _kind_for(title, notice)

    # Federal Notice/Order-of-Sale PDFs (loan/encumbrance/legal detail live here).
    order_pdf = _pdf_in(html, "field-order-of-sale")
    encumb_pdf = _pdf_in(html, "field-notice-of-encumbrances")
    mailin_pdf = _pdf_in(html, "field-mail-in-bid-form")

    desc_bits = ["IRS judicial sale of seized real property"]
    if title:
        desc_bits.append(title)
    if notice:
        desc_bits.append(notice[:400])
    description = " — ".join(desc_bits)

    li = Listing(
        source="national.irs_judicial_sales",
        source_url=url,
        listing_type=ListingType.AUCTION,
        property_kind=kind,
        street_address=street,
        city=city,
        state=state,
        zip_code=zip_code,
        county=_county_for(city, state),
        sale_date=sale_date,
        sale_location=sale_loc,
        opening_bid=bid,
        plaintiff="United States (IRS / Treasury PALS)",
        foreclosure_process="judicial",
        description=description[:1000],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"irs": {
            "title": title,
            "minimum_bid": bid,
            "notice_of_sale_url": order_pdf,
            "notice_of_encumbrances_url": encumb_pdf,
            "mail_in_bid_form_url": mailin_pdf,
            "sale_location": sale_loc,
            "auction_datetime_utc": sale_date.isoformat() if sale_date else None,
        }},
    )

    # Wire the doc harvester: order-of-sale (the judicial Notice of Sale) first so
    # it is the primary OCR input, then the other federal PDFs. We stamp these
    # explicit federal instruments rather than a blind link-sweep, so the OCR pass
    # gets the notice/encumbrance detail and not the site's property photos/chrome.
    ordered = [u for u in (order_pdf, encumb_pdf, mailin_pdf) if u]
    # Fall back to a filtered generic harvest only when no explicit PDF field was
    # found (keeps a linked notice from being missed on an atypical template).
    if not ordered:
        ordered = [u for u in harvest_document_links(html, base_url=url) if u.lower().endswith(".pdf")]
    if ordered:
        if order_pdf:
            li.raw["notice_url"] = order_pdf  # scanned by enrich_doc_ocr as primary
        stamp_documents(li, ordered)
    return li


class IRSJudicialSales(BaseScraper):
    slug = "national.irs_judicial_sales"
    name = "IRS Judicial / Seized Real Property Sales (irsauctions.gov)"
    category = "federal_auction"
    timeout_s = 180.0
    expected_min_count = 0  # National inventory is tiny; NC/SC hits are sporadic.
    requires_apify = False

    async def fetch(self) -> Iterable[Listing]:
        try:
            index_html = await get_text(_INDEX, impersonate=True, timeout=60.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("irs_judicial.index_fail", error=str(exc)[:200])
            return []

        slugs = sorted({m.group(1) for m in _AD_RE.finditer(index_html)})
        log.info("irs_judicial.index_ok", ads=len(slugs))
        out: list[Listing] = []
        for slug in slugs:
            url = f"{_BASE}{slug}"
            try:
                html = await get_text(url, impersonate=True, timeout=60.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("irs_judicial.detail_fail", slug=slug, error=str(exc)[:160])
                continue
            try:
                li = parse_detail(html, url)
            except Exception as exc:  # noqa: BLE001
                log.warning("irs_judicial.parse_fail", slug=slug, error=str(exc)[:160])
                continue
            if li is not None:
                out.append(li)
                log.info("irs_judicial.hit", state=li.state, city=li.city)
        log.info("irs_judicial.done", count=len(out), scanned=len(slugs))
        return out
