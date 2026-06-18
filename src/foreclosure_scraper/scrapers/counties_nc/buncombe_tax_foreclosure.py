"""Buncombe County NC tax-foreclosure sales — Trumba calendar feed (ICS).

Buncombe publishes its tax-foreclosure auction calendar as a structured Trumba
feed (plain HTTP, no anti-bot). Each event carries owner, property address,
sale date, opening/current bid, case number, parcel PIN, redeemed-status, and
lat/lon — richer and cleaner than scraping the aspx detail pages. Verified
live 2026-06-18.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

ICS_URL = "https://www.trumba.com/calendars/tax-foreclosures-all.ics"


def _unfold(ics: str) -> str:
    # ICS line folding: continuation lines begin with a space or tab.
    return re.sub(r"\r?\n[ \t]", "", ics)


def _events(ics: str) -> list[dict]:
    out: list[dict] = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", _unfold(ics), re.S):
        ev: dict = {}
        for line in block.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            name = key.split(";")[0]
            if name == "X-TRUMBA-CUSTOMFIELD":
                m = re.search(r'NAME="([^"]+)"', key)
                if m:
                    ev[f"cf:{m.group(1)}"] = val
            else:
                ev.setdefault(name, val)
        out.append(ev)
    return out


def _clean(s: str | None) -> str:
    return re.sub(r"\\([,;])", r"\1", (s or "")).strip()


def _parse_date(dt: str | None) -> datetime | None:
    m = re.search(r"(\d{8})", dt or "")
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d")
        except ValueError:
            return None
    return None


class BuncombeTaxForeclosure(BaseScraper):
    slug = "counties_nc.buncombe_tax_foreclosure"
    name = "Buncombe County NC Tax Foreclosure (Trumba feed)"
    category = "county_tax"
    expected_min_count = 0  # episodic
    requires_render = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        try:
            ics = await get_text(ICS_URL, headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:
            log.warning("buncombe_tax.fetch_failed", error=str(exc)[:160])
            return []
        out: list[Listing] = []
        for ev in _events(ics):
            owner = _clean(ev.get("SUMMARY"))
            addr = _clean(ev.get("LOCATION"))
            if not (owner or addr):
                continue
            bid = None
            bm = re.search(r"[\d,]+(?:\.\d+)?", _clean(ev.get("cf:Opening/Current Bid", "")).replace("$", ""))
            if bm:
                try:
                    bid = float(bm.group(0).replace(",", ""))
                except ValueError:
                    pass
            case = _clean(ev.get("cf:Case Number")) or None
            redeemed = _clean(ev.get("cf:Redeemed", "")).lower().startswith("y")
            pin = None
            pm = re.search(r"PINN=(\w+)", (ev.get("cf:PIN lookup", "") or "") + (ev.get("DESCRIPTION", "") or ""))
            if pm:
                pin = pm.group(1)
            lat = lon = None
            if ev.get("GEO"):
                try:
                    lat, lon = [float(x) for x in ev["GEO"].split(";")[:2]]
                except (ValueError, IndexError):
                    pass
            raw: dict = {"buncombe_tax": {"property_type": _clean(ev.get("cf:Property Type")), "redeemed": redeemed}}
            if redeemed:
                raw["sold_confirmed"] = True
                raw["tax_sale_status"] = "redeemed"
            out.append(Listing(
                source=self.slug,
                source_url=_clean(ev.get("X-TRUMBA-LINK")) or "https://taxforeclosures.buncombenc.gov/",
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC", county="Buncombe",
                street_address=addr or None,
                defendant=owner or None,  # property owner = foreclosure defendant
                parcel_id=pin, case_number=case,
                opening_bid=bid, sale_date=_parse_date(ev.get("DTSTART")),
                latitude=lat, longitude=lon,
                description=_clean(re.sub(r"<[^>]+>", " ", ev.get("DESCRIPTION", "")))[:300] or None,
                first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
                raw=raw,
            ))
        log.info("buncombe_tax.done", count=len(out))
        return out
