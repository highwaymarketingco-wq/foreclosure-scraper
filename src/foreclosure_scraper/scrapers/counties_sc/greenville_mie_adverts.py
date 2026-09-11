"""Greenville County SC Master-in-Equity foreclosure adverts — TMS + total judgment debt.

WHAT THIS UNLOCKS
    docs/blocked_sources_forensic.md recorded "SC PublicIndex — per-case DETAIL (TMS +
    judgment $)" as ABSENT: "Detail sits behind __doPostBack JS links that are dead in a
    saved HTML file." That reasoned from the wrong artifact. The Master-in-Equity is
    REQUIRED to advertise every foreclosure sale, and Greenville's advertisements are
    published as ordinary web pages by the county's newspaper of record. No portal, no
    postback, no login -- and publicindex.sccourts.org is not touched, so the operator's
    ToS wall stands untouched.

    Verified live 2026-09-11 on 2022-CP-23-03386:
        case            2022-CP-23-03386
        TMS             0577040104000
        judgment debt   $161,897.79
        address         4002 Fork Shoals Rd Simpsonville, SC 29680
        sale date       08/07/2023
        plaintiff       AmeriHome Mortgage Company, LLC

    The judgment amount is the number the whole buy box turns on: it is the actual debt
    against the property, not an estimate. `calc.est_gross_margin` was populated on 1,297
    of 94,384 board rows -- 1.4% -- and this source carries it per case.

THE SITEMAP RETURNS HTTP 404 AND 96KB OF VALID XML
    wp-sitemap-posts-advert-1.xml answers 404 while serving 772 <loc> entries. A probe
    that checks the status and stops sees nothing. This is the same shape as the qPayBill
    detail page that was written off for a wrong URL: the status said no, the body said
    yes. So the status is deliberately ignored here and the parse decides.

SCOPE NOTE FOR THE OPERATOR
    Greenville was pruned from the FORECLOSURE footprint by explicit direction
    (config carries `# 2026-05-14 — pruned Greenville again per user direction`). It
    remains inside the statewide SC DISTRESSED scope, which is what these rows are
    emitted as. If foreclosure-lane scope should also exclude them, that is a
    scope_repass decision, not something this scraper should quietly pre-empt.

Free, public, no login.
Slug: counties_sc.greenville_mie_adverts
Category: court
ListingType: FORECLOSURE_SALE
"""
from __future__ import annotations

import asyncio
import html as _html
import os
import re
from datetime import datetime
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://mie.greenvillejournal.com"
SITEMAP = f"{BASE}/wp-sitemap-posts-advert-1.xml"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

MAX_ADVERTS = int(os.getenv("GREENVILLE_MIE_MAX", "400"))
_CONCURRENCY = int(os.getenv("GREENVILLE_MIE_CONCURRENCY", "4"))

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+/advert/[^<\s]+)\s*</loc>", re.I)
_CASE_RE = re.compile(r"(20\d\d-CP-\d{2}-\d+)", re.I)
_TMS_RE = re.compile(r"TMS[^0-9]{0,20}([0-9][0-9\-\.]{6,})", re.I)
_JUDGMENT_RE = re.compile(r"total judgment debt[^$]{0,60}\$\s*([\d,]+(?:\.\d{2})?)", re.I)
_ADDR_RE = re.compile(r"STREET ADDRESS IS:?\s*\n?\s*([^\n]{5,90})", re.I)
_SALE_RE = re.compile(r"\bon\s+(\d{2}/\d{2}/\d{4})", re.I)
_PLAINTIFF_RE = re.compile(r"\n([A-Z][A-Za-z .,&'\-]{4,60}?)\s*,?\s*\n?\s*Plaintiff", re.I)
_DEFENDANT_RE = re.compile(r"\n([A-Z][A-Za-z .,&'\-]{4,60}?)\s*,?\s*\n?\s*Defendant", re.I)


def _text(raw: str) -> str:
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    t = _html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return re.sub(r"[ \t]+", " ", t)


def _money(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def parse_sitemap(xml: str) -> list[str]:
    """Advert URLs. The status code is IGNORED by the caller on purpose -- this endpoint
    answers HTTP 404 while serving 772 valid <loc> entries."""
    return list(dict.fromkeys(_LOC_RE.findall(xml or "")))


def parse_advert(url: str, raw: str) -> Listing | None:
    t = _text(raw)
    case = None
    m = _CASE_RE.search(t) or _CASE_RE.search(url)
    if m:
        case = m.group(1).upper()
    tms = (_TMS_RE.search(t).group(1) if _TMS_RE.search(t) else None)
    judgment = _money(_JUDGMENT_RE.search(t).group(1) if _JUDGMENT_RE.search(t) else None)
    addr_m = _ADDR_RE.search(t)
    street = city = zipc = None
    if addr_m:
        full = " ".join(addr_m.group(1).split()).strip(" .,")
        # "4002 Fork Shoals Rd Simpsonville, SC 29680"
        zm = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", full)
        if zm:
            zipc = zm.group(1)
            full = full[:zm.start()].strip(" ,")
        full = re.sub(r",?\s*SC\s*$", "", full).strip(" ,")
        if "," in full:
            street, city = (x.strip() for x in full.rsplit(",", 1))
        else:
            street = full
    sale = None
    sm = _SALE_RE.search(t)
    if sm:
        try:
            sale = datetime.strptime(sm.group(1), "%m/%d/%Y")
        except ValueError:
            sale = None
    # A row with neither a parcel nor an address cannot be underwritten or routed.
    if not (tms or street):
        return None
    pl = _PLAINTIFF_RE.search(t)
    df = _DEFENDANT_RE.search(t)
    now = datetime.utcnow()
    return Listing(
        source="counties_sc.greenville_mie_adverts",
        source_url=url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC", county="Greenville",
        parcel_id=tms, case_number=case,
        street_address=street, city=city, zip_code=zipc,
        sale_date=sale,
        judgment_amount=judgment,
        plaintiff=(pl.group(1).strip() if pl else None),
        defendant=(df.group(1).strip() if df else None),
        owner_name=(df.group(1).strip() if df else None),
        first_seen=now, last_seen=now,
        raw={"greenville_mie": {
            "case_number": case, "tms": tms,
            # THE field. The actual debt against the property, not an estimate --
            # calc.est_gross_margin was populated on only 1.4% of the board.
            "total_judgment_debt": judgment,
            "sale_date": sm.group(1) if sm else None,
            "advert_url": url,
        }},
    )


class GreenvilleMIEAdverts(BaseScraper):
    slug = "counties_sc.greenville_mie_adverts"
    name = "Greenville SC Master-in-Equity foreclosure adverts"
    category = "court"
    timeout_s = 420.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        headers = {"User-Agent": _UA, "Accept": "text/html,application/xml"}
        out: list[Listing] = []
        stats = {"adverts": 0, "parsed": 0, "no_anchor": 0, "errors": 0,
                 "with_judgment": 0, "with_tms": 0}
        async with httpx.AsyncClient(timeout=45.0, headers=headers,
                                     follow_redirects=True) as c:
            try:
                r = await c.get(SITEMAP)
            except Exception as exc:  # noqa: BLE001
                log.warning("greenville_mie.sitemap_failed", error=str(exc)[:120])
                return []
            # DO NOT check r.status_code: this endpoint returns 404 with valid XML.
            urls = parse_sitemap(r.text)
            stats["adverts"] = len(urls)
            if not urls:
                log.warning("greenville_mie.sitemap_empty", status=r.status_code,
                            bytes=len(r.text or ""),
                            note="404 here is normal; an EMPTY parse is the real failure")
                return []
            urls = urls[-MAX_ADVERTS:]          # newest last in the sitemap
            sem = asyncio.Semaphore(_CONCURRENCY)

            async def one(u: str) -> None:
                async with sem:
                    try:
                        rr = await c.get(u)
                        rr.raise_for_status()
                    except Exception:  # noqa: BLE001
                        stats["errors"] += 1
                        return
                li = parse_advert(u, rr.text)
                if not li:
                    stats["no_anchor"] += 1
                    return
                stats["parsed"] += 1
                if li.judgment_amount:
                    stats["with_judgment"] += 1
                if li.parcel_id:
                    stats["with_tms"] += 1
                out.append(li)

            await asyncio.gather(*(one(u) for u in urls))
        log.info("greenville_mie.done", fetched=len(urls), **stats)
        return out
