"""Buncombe County NC tax foreclosures via the public Trumba JSON calendar.

The taxforeclosures.buncombenc.gov page renders a Trumba calendar widget; we
bypass it and hit the JSON endpoint directly. Free, pure HTTP, no Apify needed.

2026-08-02 REGRESSION FIX (source had gone to 0 rows). Three compounding bugs:

1. WRONG DATE WINDOW — the whole reason it returned nothing. Each Trumba event's
   startDateTime is the *bidding-begins* date, NOT a future auction date, and the
   county leaves a parcel on the calendar until it is redeemed or sold. So every
   currently-open foreclosure has a start date in the PAST. Querying
   ``startdate=today`` therefore matched zero events even though the county was
   publishing an active list. Live probe 2026-08-02: today..+400d = 0 events;
   -2000d..+400d = 58 events (33 not yet redeemed). We now look BACK
   ``LOOKBACK_DAYS`` and forward ``LOOKAHEAD_DAYS``.

2. WRONG CUSTOM-FIELD KEY — Trumba names a custom field ``label``, not ``name``.
   ``cf.get("name")`` was always None, so case_number and opening_bid were never
   populated on any row this scraper ever produced.

3. REDEEMED ROWS NOT FILTERED — the feed carries a "Redeemed" field; 25 of the 58
   live events are Redeemed=Yes (the taxpayer paid, nothing to buy). Those are now
   dropped so the board only sees live inventory.

4. STALE sale_date DROPPED EVERY ROW (found in verification, after 1-3 were
   fixed). Because startDateTime is bidding-BEGINS, fixing the window recovered
   33 parcels that all carried a 2022-2026 past date — and main._active_only
   dropped 33 of 33. The fetch went 0 -> 33 while the board stayed at 0. A past
   start is now withheld from sale_date (kept in raw.bidding_begins_iso, flagged
   by raw.sale_date_withheld) so the row travels the dateless lane; only a
   genuinely future start is dated. Same remedy already used by
   scrapers.national.nc_upset_bids. This REQUIRES "counties_nc.buncombe_tax" in
   main.DATELESS_OK_SOURCES — measured 0/33 surviving without that entry and
   33/33 with it.

Also added: the "PIN lookup" custom field carries the Buncombe GIS PIN, which is
the parcel key the address/GIS backfill needs — it is now parsed into parcel_id.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

import structlog
from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

JSON_URL = "https://www.trumba.com/calendars/tax-foreclosures-all.json"

# Bidding-begins dates run years back on parcels still awaiting sale; the oldest
# live (un-redeemed) event on 2026-08-02 was filed 2022-01. Look back far enough
# to catch the whole standing list, forward for newly-scheduled ones.
LOOKBACK_DAYS = 2000
LOOKAHEAD_DAYS = 400

_TAG_RE = re.compile(r"<[^>]+>")
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
# Buncombe GIS PIN, e.g. .../buncomap/Default.aspx?PINN=966738953300000
PIN_RE = re.compile(r"PINN=([0-9]{8,20})", re.I)
MONEY_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d{2})?)")


def _strip(value: str | None) -> str:
    return _TAG_RE.sub(" ", value or "").replace("&#160;", " ").strip()


def _custom_fields(ev: dict) -> dict[str, str]:
    """Map Trumba custom fields by their LABEL (the key Trumba actually emits)."""
    out: dict[str, str] = {}
    for cf in ev.get("customFields") or []:
        label = (cf.get("label") or cf.get("name") or "").strip().lower()
        if label:
            out[label] = cf.get("value") or ""
    return out


def _money(value: str) -> float | None:
    m = MONEY_RE.search(value or "")
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if v > 0 else None


class BuncombeTax(BaseScraper):
    slug = "counties_nc.buncombe_tax"
    name = "Buncombe County (NC) Tax Foreclosures"
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 1

    async def fetch(self) -> Iterable[Listing]:
        today = datetime.utcnow()
        params = {
            "startdate": (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d"),
            "enddate": (today + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y%m%d"),
        }
        try:
            async with client(timeout=30.0) as c:
                r = await c.get(JSON_URL, params=params)
                if r.status_code != 200:
                    return []
                # Trumba returns a JSONP-like response sometimes; sniff the JSON body
                text = r.text
                start = text.find("{")
                if start < 0:
                    # A bare "[]" (no objects) is a legitimate empty calendar.
                    return []
                import json
                try:
                    data = json.loads(text[start:])
                except json.JSONDecodeError:
                    # Try parsing as raw JSON array
                    data = json.loads(text)
        except Exception:
            return []

        events = data if isinstance(data, list) else data.get("events", [])
        out: list[Listing] = []
        redeemed_dropped = 0
        for ev in events:
            sd = ev.get("startDateTime") or ev.get("start") or ev.get("startdate")
            if not sd:
                continue
            try:
                bidding_begins = dateparser.parse(sd)
            except (ValueError, TypeError):
                continue
            if bidding_begins.tzinfo is not None:
                bidding_begins = bidding_begins.replace(tzinfo=None)

            # bidding_begins is a START of availability, not an auction date. A
            # parcel stays biddable until it is redeemed or sold, so 31 of the 33
            # live rows have a start date years in the past (2022-2025). Stamping
            # it as sale_date made main._active_only read it as a long-dead
            # auction and drop EVERY row (measured 0/33 survive) — the same class
            # of bug already handled in scrapers.national.nc_upset_bids. Only a
            # genuinely FUTURE start is a scheduled event worth dating; anything
            # already open travels the dateless lane with the date kept in raw.
            sale_date = bidding_begins if bidding_begins > datetime.utcnow() else None

            fields = _custom_fields(ev)
            # The taxpayer redeemed — the parcel is off the market.
            if (fields.get("redeemed") or "").strip().lower().startswith("y"):
                redeemed_dropped += 1
                continue

            title = ev.get("title", "")  # defendant name
            location = ev.get("location") or ""
            # location often contains an HTML <a> with the address; strip tags
            addr_m = ADDR_RE.search(_TAG_RE.sub(" ", location))
            address = addr_m.group(1) if addr_m else None

            case_num = _strip(fields.get("case number")) or None
            bid = None
            for key, value in fields.items():
                if "bid" in key and ("opening" in key or "current" in key):
                    bid = _money(value)
                    break
            pin_m = PIN_RE.search(fields.get("pin lookup") or "")
            parcel = pin_m.group(1) if pin_m else None

            out.append(
                Listing(
                    source=self.slug,
                    source_url=ev.get("permaLinkUrl") or "https://taxforeclosures.buncombenc.gov/",
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=address,
                    state="NC",
                    county="Buncombe",
                    parcel_id=parcel,
                    sale_date=sale_date,
                    case_number=case_num,
                    opening_bid=bid,
                    defendant=title.strip() or None,
                    description=_strip(ev.get("description"))[:400] or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"buncombe_tax": {
                        "property_type": _strip(fields.get("property type")) or None,
                        "fire_district": _strip(fields.get("fire district")) or None,
                        "bidding_begins": sd,
                        "bidding_begins_iso": bidding_begins.isoformat(),
                        "sale_date_withheld": sale_date is None,
                        "pin": parcel,
                    }},
                )
            )
        log.info("buncombe_tax.counts", events=len(events), kept=len(out),
                 redeemed_dropped=redeemed_dropped)
        return out
