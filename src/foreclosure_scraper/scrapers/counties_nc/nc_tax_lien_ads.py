"""NC annual tax-lien advertisements (NCGS 105-369) that four more counties post as PDFs:
Hoke, Lee, Davidson and Randolph. Sibling of nc_county_pdf_delinquent_tax (Lincoln, Catawba,
McDowell), with one parser per county because every county prints its own layout.

SOURCES AND MEASURED SIZE (2026-10-07; levy year 2025 in every file)
  Hoke      hokecounty.net/749/2025-Delinquent-Tax: "2025 Taxes Ad List Non Transferred"
            (DocumentCenter/View/4258, 53 pages) and "... Transferred" (View/4259, 3 pages; parcels
            that changed hands after Jan 1, so the bill follows the old owner).
            Line: "<owner> <PARCEL 99999-99-99-999> <amount>$ <situs>".
  Lee       leecountync.gov "2025 Delinquent Real Property 01.22.2026.pdf" (77 pages).
            Line: "<customer #> <owner> <PROPERTY ID, 12 digits> <location> 2,025 $<amount>".
  Davidson  co.davidson.nc.us/DocumentCenter/View/5034/2025-ADVERTISEMENT-LIST (19 pages,
            published 2026). Line: "<account #> <owner> <legal / plat / deed refs> <location>
            <acreage> <PARCEL> $<amount>"; the owner is cut at the first legal token. The ad prints
            a 13-digit PIN without its leading zero on about a quarter of the rows (12 digits);
            those get the zero back (200 of 200 sampled then hit the parcel cache, 0 before).
  Randolph  randolphcountync.gov/343/Tax-Liens: 13 PDFs by surname letter ("0-9", "A", ... "T-Z",
            DocumentCenter/View/545-557), "2025 taxes", sale notice dated 2026.
            Line: "<PARCEL 10 digits> <owner> <amount> [<second owner>]".
  The number of rows each county really publishes is in docs/new_sources_2026-10-07_distress.md
  (measured by this parser, not estimated).

RULES
  * Every row is real property (these are real-property lien ads).
  * THE NOT-YET-LATE RULE (_tax_kit): the advertised levy year is 2025, late since 2026-01-06, so
    rows count; raw['tax_owed'] = {balance, kind, source, year, basis 'advertised_list',
    years_delinquent (late years only), ...}. A file whose levy year is not late yet emits nothing.
  * The parcel number is the parcel-cache key; owner mailing and value come from the cache join.
    Owner names are kept only as the ad prints them (owner_name), never the free legal text.
  * One county's file failing (moved, renamed) fails only that county (LayerHarvest tolerate).

DATELESS: slug counties_nc.nc_tax_lien_ads goes in main.DATELESS_OK_SOURCES.
Gate: FORECLOSURE_NC_TAX_LIEN_ADS=0.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, NamedTuple, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind
from ..counties_generic._tax_kit import tax_owed_block

log = structlog.get_logger()

SLUG = "counties_nc.nc_tax_lien_ads"
ENV_OFF = "FORECLOSURE_NC_TAX_LIEN_ADS"


def _amt(s: str) -> float:
    return float(re.sub(r"[,\s$]", "", s))


def _sq(s: Optional[str]) -> Optional[str]:
    s = re.sub(r"\s+", " ", s or "").strip(" ,")
    return s or None


# ----------------------------------------------------------------------------- parsers
_HOKE = re.compile(r"^(?P<owner>.*?)\s+(?P<pid>\d{5}-\d{2}-\d{2}-\d{3})\s+(?P<amt>[\d,]+\.\d{2})\s*\$\s*(?P<situs>.*)$")


def parse_hoke(text: str) -> list[dict]:
    out = []
    for ln in text.splitlines():
        m = _HOKE.match(ln.strip())
        if m:
            situs = _sq(m.group("situs"))
            if situs and re.match(r"^0+\s", situs):
                situs = None                       # "0 STREET": no house number assigned
            out.append({"pid": m.group("pid"), "owner": _sq(m.group("owner")),
                        "situs": situs, "amount": _amt(m.group("amt"))})
    return out


_LEE = re.compile(r"^(?P<cust>\d{1,8})\s+(?P<owner>.*?)\s+(?P<pid>\d{12})\s+(?P<loc>.*?)\s+"
                  r"(?P<yr>\d,\d{3})\s+\$(?P<amt>[\d,]+\.\d{2})$")


def parse_lee(text: str) -> list[dict]:
    """A record pypdf wraps over two lines ("<cust> <owner>" / "<pid> <loc> 2,025 $<amt>", or the
    "2,025 $<amt>" tail alone) is matched joined with the unmatched line before it."""
    out = []
    buf: list[str] = []
    for raw_ln in text.splitlines():
        ln = raw_ln.strip()
        m = _LEE.match(ln)
        for k in (1, 2, 3):
            if m or len(buf) < k:
                break
            m = _LEE.match(" ".join(buf[-k:] + [ln]))
        buf = [] if m else (buf + [ln])[-3:]
        if m:
            loc = _sq(m.group("loc"))
            if loc and re.match(r"^0+\s", loc):
                loc = None
            out.append({"pid": m.group("pid"), "owner": _sq(m.group("owner")), "situs": loc,
                        "amount": _amt(m.group("amt")), "year": int(m.group("yr").replace(",", ""))})
    return out


_DAV = re.compile(r"^(?P<acct>\d{5,8})\s+(?P<body>.*?)\s+(?P<pid>\d{9,14}[A-Z]?)\s+\$(?P<amt>[\d,]+\.\d{2})$")
_LEGAL_TOKEN = re.compile(r"[=]|^\d|^[A-Z]{0,2}\d|&\d")


def parse_davidson(text: str) -> list[dict]:
    out = []
    for ln in text.splitlines():
        m = _DAV.match(ln.strip())
        if not m:
            continue
        words = m.group("body").split()
        owner = []
        for w in words:
            if _LEGAL_TOKEN.search(w):
                break
            owner.append(w)
        pid = m.group("pid")
        if len(pid) == 12 and pid.isdigit():
            pid = "0" + pid          # the ad drops the leading zero of a 13-digit Davidson PIN
        out.append({"pid": pid, "owner": _sq(" ".join(owner)), "situs": None,
                    "amount": _amt(m.group("amt"))})
    return out


_RAND = re.compile(r"^(?P<pid>\d{10})\s+(?P<owner>.*?)\s*(?P<amt>\d{1,3}(?:,\d{3})*\.\d{2})(?:\s+(?P<owner2>.*))?$")


def parse_randolph(text: str) -> list[dict]:
    out = []
    for ln in text.splitlines():
        m = _RAND.match(ln.strip())
        if m:
            owners = [o for o in (_sq(m.group("owner")), _sq(m.group("owner2"))) if o]
            out.append({"pid": m.group("pid"), "owner": " & ".join(owners) or None, "situs": None,
                        "amount": _amt(m.group("amt"))})
    return out


class County(NamedTuple):
    name: str
    page: str
    files: tuple[str, ...]          # PDF URLs
    parse: Callable[[str], list[dict]]
    year: int


_RAND_IDS = (557, 556, 555, 554, 553, 552, 551, 550, 549, 548, 547, 546, 545)
COUNTIES: tuple[County, ...] = (
    County("Hoke", "https://www.hokecounty.net/749/2025-Delinquent-Tax",
           ("https://www.hokecounty.net/DocumentCenter/View/4258/2025-Taxes-Ad-List-Nontransferred",
            "https://www.hokecounty.net/DocumentCenter/View/4259/2025-Taxes-Ad-List-Transferred"),
           parse_hoke, 2025),
    County("Lee", "https://leecountync.gov/",
           ("https://leecountync.gov/2025%20Delinquent%20Real%20Property%2001.22.2026.pdf",),
           parse_lee, 2025),
    County("Davidson", "https://www.co.davidson.nc.us/DocumentCenter/View/5034/2025-ADVERTISEMENT-LIST",
           ("https://www.co.davidson.nc.us/DocumentCenter/View/5034/2025-ADVERTISEMENT-LIST",),
           parse_davidson, 2025),
    County("Randolph", "https://www.randolphcountync.gov/343/Tax-Liens",
           tuple(f"https://www.randolphcountync.gov/DocumentCenter/View/{i}" for i in _RAND_IDS),
           parse_randolph, 2025),
)


def to_listing(rec: dict, county: County, *, now: Optional[datetime] = None) -> Optional[Listing]:
    year = rec.get("year") or county.year
    to = tax_owed_block([(year, rec["amount"])], state="NC", county=county.name, source=SLUG,
                        basis="advertised_list")
    if not to:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    raw: dict[str, Any] = {
        "nc_tax_lien_ad": {"county": county.name, "tax_year": year, "amount": rec["amount"],
                           "parcel": rec["pid"], "years_unpaid": [year], "list_page": county.page},
        "tax_owed": to,
    }
    return Listing(
        source=SLUG, source_url=county.page,
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        state="NC", county=county.name,
        street_address=rec.get("situs"), parcel_id=rec["pid"],
        owner_name=rec.get("owner"), defendant=rec.get("owner"),
        foreclosure_process="tax",
        description=f"{county.name} NC unpaid {year} real-estate tax ${rec['amount']:,.0f} — {rec['pid']}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


class NCTaxLienAds(BaseScraper):
    slug = SLUG
    name = "NC tax-lien advertisements: Hoke, Lee, Davidson, Randolph (county PDFs)"
    category = "county_tax"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        guard = LayerHarvest(self.slug, [c.name for c in COUNTIES],
                             tolerate=[c.name for c in COUNTIES], attempts=2)
        out: list[Listing] = []
        async with client(timeout=120.0) as c:
            with guard:
                for county in COUNTIES:
                    recs = await guard.harvest(county.name, self._one(c, county))
                    seen = set()
                    for rec in recs:
                        key = (rec["pid"], rec["amount"])
                        if key in seen:
                            continue
                        seen.add(key)
                        li = to_listing(rec, county)
                        if li:
                            out.append(li)
        log.info("nc_tax_lien_ads.done", leads=len(out))
        return out

    @staticmethod
    def _one(c, county: County):
        async def _run() -> list[dict]:
            recs: list[dict] = []
            for i, url in enumerate(county.files):
                if i:
                    await asyncio.sleep(1.7)
                r = await c.get(url)
                if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                    raise RuntimeError(f"{county.name}: HTTP {r.status_code} {url[-40:]}")
                recs.extend(county.parse(pdf_text(r.content)))
            log.info("nc_tax_lien_ads.county", county=county.name, rows=len(recs))
            return recs
        return _run
