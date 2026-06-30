"""Cherokee County SC delinquent-tax watcher — cherokeecountysc.gov.

Cherokee County (Gaffney, SC — Upstate core) posts its annual delinquent-tax
SALE material under /delinquent-tax/ as wp-content/uploads PDFs. When the
year-end PARCEL LIST is published (~Oct–Dec) it carries owner name + TMS map
number + property situs per delinquent parcel — strong pre-sale distress: the
owner owes back taxes and the property heads to the December tax sale unless
redeemed (SC 12-51 redemption ~12 months).

This is SEASONAL. Most of the year the page only has procedural docs (bidder
registration, web policy), and the actual parcel list is absent — so off-season
runs must return 0 CLEANLY, never error. We do that two ways:
  * active_months gates the run to the Oct–Jan window (dormant otherwise), and
  * even in-window, we only emit rows from a PDF that actually parses into
    parcel records; a procedural PDF yields 0 rows and is skipped.

Access path (free, public .gov — NO login, NO CAPTCHA, plain HTTP + pypdf):
  1. GET /delinquent-tax/ (and the /tax-sale-bidders/ subpage) -> list every
     wp-content/uploads *.pdf link.
  2. Rank candidates: current/prior year + "delinquent / tax list / ledger"
     score up; "bidder / registration / policy / privacy / procedure" score
     down (those are the procedural docs, not the parcel list).
  3. Download each candidate, pypdf-extract text, parse `owner TMS situs` rows.
     The first PDF that yields real parcel rows is the list; stop there.

TMS format (Cherokee): NNN-NN-NN-NNN(.NNN)  e.g. 029-00-00-028.001.

Verified live 2026-06-30: page reachable, 3 PDFs present — all procedural
(2025 bidder-info, web-additions, web-policy), NO current parcel list. The
watcher returns 0 cleanly (off-season), which is the expected DORMANT/ZERO
outcome, not a failure.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...http_client import get_bytes, get_text
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGES = (
    "https://cherokeecountysc.gov/delinquent-tax/",
    "https://cherokeecountysc.gov/delinquent-tax/tax-sale-bidders/",
)
# Cherokee TMS: NNN-NN-NN-NNN(.NNN)
TMS_PAT = r"\d{3}-\d{2}-\d{2}-[\d.]+"

# A parcel row in the list PDF starts with an item number, then owner name,
# then the TMS, then the situs/description. Same shape the SC annual-list parser
# uses, kept self-contained here so this county can diverge if its format does.
_ITEM_RE = re.compile(r"^\s*(\d{3,6}|NEW OWNER)\s+(.+)$")


def discover_pdf_links(html: str, base: str, year: int) -> list[str]:
    """Return candidate list-PDF URLs on a Cherokee delinquent-tax page, ranked
    so the parcel LIST sorts above procedural docs (bidder info / policy)."""
    hrefs = re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I)
    cands: list[tuple[int, str]] = []
    for h in hrefs:
        u = urljoin(base, h)
        low = u.lower()
        score = 0
        if str(year) in low:
            score += 4
        if str(year - 1) in low:
            score += 2
        if any(k in low for k in ("delinquent", "tax-list", "tax_list",
                                   "ledger", "sale-list", "taxsale")):
            score += 3
        if any(k in low for k in ("bidder", "registration", "register",
                                   "policy", "privacy", "procedure",
                                   "addition", "info", "faq")):
            score -= 4  # procedural doc, not the parcel list
        cands.append((score, u))
    # Keep even non-positive-scoring PDFs as low-priority candidates: a list
    # whose filename gives no hints will still be tried after the obvious ones.
    return [u for _s, u in sorted(cands, key=lambda x: -x[0])]


def parse_list(text: str, url: str, year: int) -> list[Listing]:
    """Parse delinquent-tax list PDF text into per-parcel Listings.
    Row shape: `00005 ADAMS ISAAC 029-00-00-028.001 1240 LOVE SPRINGS RD`."""
    tms_re = re.compile(rf"({TMS_PAT})")
    out: list[Listing] = []
    seen: set[str] = set()
    redemption = datetime(year, 12, 31)  # ~12-mo redemption off the Dec sale
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        m = _ITEM_RE.match(line)
        if not m:
            continue
        tm = tms_re.search(line)
        if not tm:
            continue
        tms = tm.group(1)
        head = line[m.start(2):tm.start()].strip() if tm.start() > m.start(2) else ""
        name = re.sub(r"^\s*(NEW OWNER)\s*", "", head).strip() or None
        situs = line[tm.end():].strip() or None
        key = f"{tms}|{name}"
        if key in seen:
            continue
        seen.add(key)
        out.append(Listing(
            source="counties_sc.cherokee_delinquent_tax",
            source_url=url,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC",
            county="Cherokee",
            street_address=situs,
            defendant=name,
            parcel_id=tms,
            redemption_deadline=redemption,
            foreclosure_process="tax",
            description=re.sub(r"\s+", " ", line)[:300],
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"cherokee_delinquent_tax": {"item_line": line[:200], "year": year}},
        ))
    return out


def _pdf_text(data: bytes) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as exc:  # noqa: BLE001
        log.warning("cherokee_delinquent.pdf_parse_fail", error=str(exc)[:160])
        return ""


class CherokeeDelinquentTax(BaseScraper):
    slug = "counties_sc.cherokee_delinquent_tax"
    name = "Cherokee County (SC) Delinquent Tax Sale List (annual PDF)"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0          # off-season the list is absent -> clean 0
    active_months = (10, 11, 12, 1)  # SC list posts ~Nov; dormant off-season

    async def fetch(self) -> Iterable[Listing]:
        year = datetime.utcnow().year
        candidates: list[str] = []
        seen_url: set[str] = set()
        for page in PAGES:
            try:
                html = await get_text(page, impersonate=True, timeout=40.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("cherokee_delinquent.page_fail", page=page,
                            error=str(exc)[:160])
                continue
            for u in discover_pdf_links(html, page, year):
                if u not in seen_url:
                    seen_url.add(u)
                    candidates.append(u)

        if not candidates:
            log.info("cherokee_delinquent.no_pdfs")
            return []

        out: list[Listing] = []
        for url in candidates:
            try:
                data = await get_bytes(url, timeout=60.0)
            except Exception:  # noqa: BLE001
                continue
            if not (data and data[:4] == b"%PDF"):
                continue
            rows = parse_list(_pdf_text(data), url, year)
            if rows:  # the actual parcel list (procedural PDFs yield 0)
                out.extend(rows)
                log.info("cherokee_delinquent.list_ok", url=url, count=len(rows))
                break

        log.info("cherokee_delinquent.done", count=len(out),
                 candidates=len(candidates))
        return out
