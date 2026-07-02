"""Pickens County SC delinquent tax-sale bidder/results list — self-hosted PDF.

Pickens posts its annual "Delinquent Tax Sale Results" as a free, public,
no-login .gov PDF under /departments/delinquent_tax/. Unlike Spartanburg's
list (situs only) or Cherokee's (owner+TMS only), the Pickens PDF is the one
that closes the taxes-OWED gap: every row carries OWNER + MAP/PARCEL # +
SALE/BID PRICE + the prior- and current-year TAX AMOUNTS on a single line:

    BIDDER #  ITEM #  MAP/PARCEL #  <OWNER NAME>  $SALE/BID  $2024 TAXES  $2025 TAXES
    150       00002   4185-00-38-3525  ABERCROMBIE, ROGER KEITH  $ 55,000.00  $ 2,910.52  $ 3,032.44

Distress semantics: this is a POST-sale results list (sold ~Nov). Under SC Code
12-51 the original owner keeps a ~12-month right of redemption off the sale, so
each sold parcel is a live motivated-seller lead — the owner owed back taxes and
their property was auctioned but is still redeemable. BIDDER # of "PBO" (Property
Bought by Owner / pulled) and "BF"/"bf" (bid off to the Forfeited Land
Commission) mark non-arms-length rows; we still emit them as delinquent-tax
leads (the owner was delinquent) but flag the disposition in raw.

Access path (FREE, public, NO login / CAPTCHA / paywall):
  * The delinquent-tax page carries a <base href="root/"> tag, so its file-group
    hrefs (e.g. "TAX SALE RESULTS FOR WEBSITE.pdf") resolve against the DOMAIN
    ROOT. Root URLs 301-redirect to the Revize store at
    cms5.revize.com/revize/pickenscountysc/<href>, which serves the raw PDF.
    We discover the current-year link off the page and resolve it that way; if
    discovery misses, we fall back to the known current filename. Parsed with
    pdfplumber.

Amount owed (current-year taxes) -> raw['pickens_tax_sale']['taxes_owed'], which
enrichment_tax_owed picks up via its generic _TAXISH scan and normalizes to
raw['tax_owed']. Situs isn't in this list; parcel_id backfills the address via
SC GIS. SEASONAL: the results PDF publishes ~Nov and stays up year-round, so no
active_months gate — it's a stable annual doc, refreshed when the county rolls
to a new year.

Live-verified 2026-07-02: page reachable, 2025 PDF fetches (4 pages, ~147 KB),
160 parcel rows parse, 140 with owner+parcel+current-year tax amount.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.co.pickens.sc.us/departments/delinquent_tax/index.php"
DOMAIN_ROOT = "https://www.co.pickens.sc.us/"
# Fallback if link discovery misses the current-year "Results" doc. The county
# reuses this flat filename each cycle (root-relative -> Revize store).
FALLBACK_HREF = "TAX SALE RESULTS FOR WEBSITE.pdf"

# Pickens TMS / MAP-PARCEL #: NNNN-NN-NN-NNNN  (e.g. 4185-00-38-3525)
_PARCEL_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}-\d{4})\b")
# The three trailing money columns: SALE/BID, prior-year tax, current-year tax.
# Each is "$ <digits>.NN" or "$ -" (redeemed / no-sale).
_MONEY_RE = re.compile(r"\$\s*([\d][\d,\s]*\.\d{2}|-)")
# pdfplumber DROPS glyphs on some long rows, rendering "3,032.44" as "3 2.44"
# (the ",03" is physically missing from the content stream — table extraction
# reproduces the same loss). Such a token has an interior space BETWEEN digits
# and cannot be reconstructed, so we treat it as untrustworthy rather than emit
# a wrong number. This detects that: a digit, optional comma-digits, a space,
# then more digits before the cents.
_GARBLED_MONEY_RE = re.compile(r"\d[\d,]*\s+\d")


def _money(tok: str) -> float | None:
    """Parse a clean '$ 55,000.00' / '$ -' money token to a float.

    Returns None for '$ -' (redeemed / no-sale), for a GARBLED token (pdfplumber
    dropped glyphs, leaving an interior space between digits — unrecoverable), or
    for an unparseable token. Callers that need the raw string keep it separately.
    """
    body = re.sub(r"^\$\s*", "", (tok or "").strip())
    if _GARBLED_MONEY_RE.search(body):
        return None  # dropped-glyph garble — don't fabricate a value
    s = re.sub(r"[^\d.]", "", body)
    if not s or s == ".":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f > 0 else None


def _clean_owner(s: str | None) -> str | None:
    s = re.sub(r"\s+", " ", (s or "")).strip().strip(";,").strip()
    # A bare number or stray '$' fragment isn't an owner name.
    if not s or s in {"$", "-"} or s.isdigit():
        return None
    return s


def parse_results(text: str, url: str) -> list[Listing]:
    """One Listing per delinquent parcel in the Pickens results PDF."""
    out: list[Listing] = []
    seen: set[str] = set()
    year = datetime.utcnow().year
    redemption = datetime(year, 12, 31)  # ~12-mo SC redemption off the ~Nov sale
    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip())
        if not line:
            continue
        pm = _PARCEL_RE.search(line)
        if not pm:
            continue  # header / footer / notes
        parcel = pm.group(1)
        # BIDDER # is the leading token: a number, or PBO/PB0/BF/bf disposition.
        head = line[: pm.start()].strip()
        toks = head.split()
        bidder = toks[0] if toks else None
        # ITEM # is the last numeric token before the parcel (5-digit, e.g. 00002).
        item_no = None
        for t in reversed(toks):
            if t.isdigit():
                item_no = t
                break
        # Everything after the parcel: "<OWNER NAME> $sale $2024 $2025".
        tail = line[pm.end():].strip()
        monies = _MONEY_RE.findall(tail)
        # Owner name = tail up to the FIRST '$' (money block).
        dollar = tail.find("$")
        owner = _clean_owner(tail[:dollar] if dollar != -1 else tail)
        # Column order is SALE/BID, 2024 TAXES, 2025 TAXES. The delinquent amount
        # OWED is the current-year tax (last money column); fall back to 2024.
        sale_bid = _money(monies[0]) if len(monies) >= 1 else None
        tax_2024 = _money(monies[1]) if len(monies) >= 2 else None
        tax_2025 = _money(monies[2]) if len(monies) >= 3 else None
        # OWED = current-year tax when it parsed clean; else fall back to the
        # prior-year figure (also delinquent) so a glyph-garbled current-year
        # cell still yields a real owed number. Record which year it came from.
        if tax_2025:
            taxes_owed, taxes_owed_year = tax_2025, "current"
        elif tax_2024:
            taxes_owed, taxes_owed_year = tax_2024, "prior"
        else:
            taxes_owed, taxes_owed_year = None, None
        disposition = None
        bu = (bidder or "").upper()
        if bu in {"PBO", "PB0"}:
            disposition = "redeemed_or_pulled"  # Property Bought by Owner / pulled
        elif bu == "BF":
            disposition = "bid_off_to_flc"       # Forfeited Land Commission
        key = parcel
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Listing(
                source="counties_sc.pickens_tax_sale",
                source_url=url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Pickens",
                owner_name=owner,
                defendant=owner,
                parcel_id=parcel,
                opening_bid=sale_bid,
                redemption_deadline=redemption,
                foreclosure_process="tax",
                description=(
                    f"{owner or 'Owner n/a'} — Pickens SC delinquent tax sale"
                    + (f", ${taxes_owed:,.0f} owed" if taxes_owed else "")
                    + f" ({parcel})"
                )[:300],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "pickens_tax_sale": {
                        "bidder": bidder,
                        "item_no": item_no,
                        "parcel": parcel,
                        "owner": owner,
                        "sale_bid_price": sale_bid,
                        "taxes_owed": taxes_owed,       # OWED -> normalized to tax_owed
                        "taxes_owed_year": taxes_owed_year,  # "current" | "prior" (garble fallback)
                        "tax_2024": tax_2024,
                        "tax_2025": tax_2025,
                        "disposition": disposition,
                        "row": raw_line.strip()[:200],
                    }
                },
            )
        )
    return out


def discover_results_url(html: str, year: int) -> str | None:
    """Find the newest "<year> Delinquent Tax Sale Results" PDF href on the page.

    Hrefs are root-relative (page has <base href="root/">). Returns an absolute
    domain-root URL; the 301 to the Revize store happens on fetch. Prefers the
    current year, then the prior year, then any results PDF.
    """
    anchors = re.findall(
        r'<a[^>]+href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>',
        html, re.I | re.S,
    )
    ranked: list[tuple[int, str]] = []
    for href, label in anchors:
        text_label = re.sub(r"<[^>]+>", "", label).strip().lower()
        blob = (href + " " + text_label).lower()
        if "result" not in blob and "sale" not in blob:
            continue
        score = 0
        if str(year) in blob:
            score += 5
        if str(year - 1) in blob:
            score += 3
        if "result" in blob:
            score += 2
        # href is root-relative because of <base href="root/">
        ranked.append((score, urljoin(DOMAIN_ROOT, href)))
    if not ranked:
        return None
    ranked.sort(key=lambda x: -x[0])
    return ranked[0][1]


class PickensTaxSale(BaseScraper):
    slug = "counties_sc.pickens_tax_sale"
    name = "Pickens County (SC) Delinquent Tax Sale Results (owner+parcel+amount PDF)"
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 0  # a fresh cycle can briefly 0 before the results post

    async def fetch(self) -> Iterable[Listing]:
        # 1) discover the current-year results PDF off the delinquent-tax page.
        year = datetime.utcnow().year
        url: str | None = None
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
            url = discover_results_url(html, year)
        except Exception as exc:  # noqa: BLE001
            log.warning("pickens_tax_sale.page_fail", error=str(exc)[:160])
        if not url:
            url = urljoin(DOMAIN_ROOT, FALLBACK_HREF)
            log.info("pickens_tax_sale.fallback_href", url=url)

        # 2) fetch the PDF (root URL 301s to the cms5.revize.com store).
        try:
            data = await get_bytes(url + ("&" if "?" in url else "?") + "t=1",
                                   timeout=75.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("pickens_tax_sale.fetch_fail", url=url, error=str(exc)[:160])
            return []
        if not (data and data[:4] == b"%PDF"):
            log.info("pickens_tax_sale.not_pdf", url=url)
            return []

        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        except Exception as exc:  # noqa: BLE001
            log.warning("pickens_tax_sale.pdf_parse_fail", error=str(exc)[:160])
            return []

        rows = parse_results(text, url)
        log.info("pickens_tax_sale.done", count=len(rows), url=url)
        return rows
