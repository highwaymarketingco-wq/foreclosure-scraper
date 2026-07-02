"""Terry Howe & Associates — SC Forfeited Land Commission (FLC) auctions.

SC counties liquidate tax-failed / FLC inventory through third-party auctioneers;
Terry Howe is the main one for the upstate (Spartanburg / Anderson / Laurens and
others). The county FLC pages don't list the parcels, but Terry Howe publishes the
whole catalog via a free unauthenticated WordPress REST endpoint — no key, no
render, no CAPTCHA, no login:
  GET /wp-json/wp/v2/auctions?per_page=100  -> [{title, link, content(html)}, ...]

Each in-scope auction title is "{County} County, SC – N Properties for {County}
County Forfeited Land Commission". The content body carries a plain-text
"TaxID Description" table — one row per forfeited parcel:

  6-18-07-053.00 817 Saxon Ave, Spartanburg, SC
  5-16-09-084.02 Off Dodd St, Wellford, SC

so every row yields a real SC TMS **Parcel ID** + street address (+ city). FLC
parcels are quitclaim-only, no title search, bidding opens at $100 — prime cheap
owner-lost distressed inventory.

PARSER (2026-07-02): the body is walked as that TaxID table, splitting on each TMS
token so the Parcel ID is captured (strongest dedupe key) and "Off <street>"
locator parcels — which have no house number but ARE real forfeited lots — are
kept, not dropped. Two TMS layouts are handled:
  * upstate dashed   6-18-07-053.00           (d-dd-dd-ddd.dd)
  * long dotted-zero  088-00-00-068-000       (ddd-dd-dd-ddd-ddd)
Bodies with no TaxID table fall back to a street-address harvest so an older
non-tabular FLC post still surfaces its parcels.

Free, plain HTTP (httpx), no Apify / proxy / render / stealth.
"""
from __future__ import annotations

import html
import re
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...config import ALL_COUNTIES
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

API = "https://terryhowe.com/wp-json/wp/v2/auctions?per_page=100&_fields=id,title,link,content"
_SC_COUNTIES = {c.name.lower() for c in ALL_COUNTIES if c.state == "SC"}

_TITLE_COUNTY = re.compile(r"([A-Za-z][A-Za-z ]+?)\s+County,\s*SC", re.I)
_FLC_MARK = re.compile(r"forfeited\s+land|FLC|delinquent\s+tax", re.I)

# SC TMS / parcel formats used across Terry Howe FLC bodies:
#   upstate dashed      6-18-07-053.00        (d-dd-dd-ddd.dd)
#   long dotted-zero    088-00-00-068-000     (ddd-dd-dd-ddd-ddd)
# Anchored on a run of dash-separated numeric groups so a bare street number
# ("817 Saxon Ave") is never mistaken for a parcel.
_TMS = re.compile(r"\b(\d{1,3}-\d{2}-\d{2}-\d{3}(?:[.-]\d{2,3})?)\b")

# Marks where the parcel table starts: "TaxID Description" / "Tax ID Description".
_TABLE_HEAD = re.compile(r"Tax\s?ID\s+Description\s+", re.I)

# Fallback street-address harvest for bodies that carry no TaxID table.
_ADDR = re.compile(
    r"\b(\d{1,5}\s+[A-Za-z0-9.'\-]+(?:\s+[A-Za-z0-9.'\-]+){0,4}?\s+"
    r"(?:Rd|Road|St|Street|Ln|Lane|Dr|Drive|Ave|Avenue|Hwy|Highway|Ct|Court|"
    r"Way|Blvd|Cir|Circle|Pl|Place|Ter|Terrace|Trl|Trail|Pkwy|Loop))\b\.?", re.I)


def _strip_html(markup: str) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup or "")).strip()
    # Decode entities (&amp; -> &, &#8211; -> –) so addresses/cities are clean.
    return html.unescape(text)


def _county_of(title: str) -> str | None:
    m = _TITLE_COUNTY.search(title or "")
    if not m:
        return None
    c = m.group(1).strip()
    return c if c.lower() in _SC_COUNTIES else None


# A row's description ends at the state token; everything after "..., SC" is the
# Type/notes column ("House", "Lot", "Duplex. Rented.") and is discarded.
# Captures the field JUST BEFORE ", SC" as the city and everything before that
# as the street — so a unit field in the middle
# ("505 N Broad St, Units A&B, Clinton, SC") gives street "505 N Broad St,
# Units A&B" and the real city "Clinton", not the unit.
_CITY_STATE = re.compile(r"^(?P<street>.*?),\s*(?P<city>[A-Za-z][A-Za-z .'&-]*?)\s*,\s*S\.?C\.?\b", re.S)
# markdown/emphasis artifacts that leak from the CMS body ("**")
_JUNK = re.compile(r"\*+")


def _split_row(desc: str) -> tuple[str | None, str | None]:
    """Split a table cell into (street, city).

    "817 Saxon Ave, Spartanburg, SC"                 -> ("817 Saxon Ave", "Spartanburg")
    "Off Dodd St, Wellford, SC"                      -> ("Off Dodd St", "Wellford")
    "505 N Broad St, Units A&B, Clinton, SC Duplex." -> ("505 N Broad St, Units A&B", "Clinton")
    "Cherry Rd" (no ", SC" anchor)                   -> ("Cherry Rd", None)

    The city is the comma-field immediately before the "SC" state token; the
    trailing Type/notes column after "SC" is dropped.
    """
    desc = _JUNK.sub("", desc or "").strip()
    m = _CITY_STATE.search(desc)
    if m:
        street = m.group("street").strip().strip(",").strip() or None
        city = m.group("city").strip() or None
        return street, city
    # No ", SC" anchor — take the leading comma-field as the street.
    parts = [p.strip() for p in desc.split(",") if p.strip()]
    if parts and re.fullmatch(r"S\.?C\.?", parts[-1], re.I):
        parts = parts[:-1]
    if not parts:
        return None, None
    return (parts[0] or None), (parts[1] if len(parts) >= 2 else None)


def parse_flc_rows(body: str) -> list[dict]:
    """Parse a Terry Howe FLC auction body into parcel rows.

    Primary path: the "TaxID Description" table. Split the table region on each
    TMS token; the text from one TMS to the next is that parcel's description
    ("817 Saxon Ave, Spartanburg, SC"). Every row keeps its Parcel ID, and
    "Off <street>" locator parcels (no house number) are preserved.

    Returns a list of {parcel_id, street_address, city} dicts (address/city may
    be None). If no TMS table is found, falls back to a plain street-address
    harvest (parcel_id None) so older non-tabular posts still surface.
    """
    rows: list[dict] = []
    seen: set[str] = set()

    head = _TABLE_HEAD.search(body or "")
    region = body[head.end():] if head else (body or "")
    matches = list(_TMS.finditer(region))

    if matches:
        for i, mt in enumerate(matches):
            parcel = mt.group(1)
            start = mt.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(region)
            desc = region[start:end].strip().strip(",").strip()
            street, city = _split_row(desc)
            key = parcel.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append({"parcel_id": parcel, "street_address": street, "city": city})
        return rows

    # No TaxID table — fall back to a street-address-only harvest.
    for m in _ADDR.finditer(body or ""):
        ad = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".")
        low = ad.lower()
        if low in seen:
            continue
        seen.add(low)
        rows.append({"parcel_id": None, "street_address": ad, "city": None})
    return rows


class TerryHoweFLC(BaseScraper):
    slug = "counties_sc.terry_howe_flc"
    name = "Terry Howe FLC auctions (SC Forfeited Land Commission)"
    category = "county_tax"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0 Chrome/126"}) as c:
            try:
                r = await c.get(API, follow_redirects=True)
            except Exception as exc:  # noqa: BLE001
                log.warning("terry_howe_flc.fetch_failed", error=str(exc)[:160])
                return []
            if r.status_code != 200:
                log.warning("terry_howe_flc.bad_status", status=r.status_code)
                return []
            try:
                auctions = r.json()
            except ValueError:
                log.warning("terry_howe_flc.json_failed")
                return []

        seen: set[tuple] = set()
        for a in auctions if isinstance(auctions, list) else []:
            t = a.get("title") or {}
            title = (t.get("rendered") if isinstance(t, dict) else t) or ""
            county = _county_of(title)
            if not county:
                continue  # not an in-footprint SC county auction
            link = a.get("link") or ""
            cb = a.get("content") or {}
            body = _strip_html(cb.get("rendered") if isinstance(cb, dict) else cb)
            if not _FLC_MARK.search(title + " " + body):
                continue  # keep FLC / tax-failed auctions only
            rows = parse_flc_rows(body)
            if rows:
                for row in rows:
                    parcel = row.get("parcel_id")
                    street = row.get("street_address")
                    # dedupe on parcel when present, else on the street text
                    key = (county, (parcel or street or "").lower())
                    if not key[1] or key in seen:
                        continue
                    seen.add(key)
                    out.append(Listing(
                        source=self.slug, source_url=link, listing_type=ListingType.TAX_SALE,
                        state="SC", county=county,
                        parcel_id=parcel,
                        street_address=street,
                        city=row.get("city"),
                        property_kind=PropertyKind.UNKNOWN,
                        foreclosure_process="tax",
                        raw={"flc": {"auctioneer": "Terry Howe", "auction_title": title[:200],
                                     "source": "forfeited_land_commission"}},
                    ))
            else:
                # No parseable row — still surface the county FLC auction as a lead.
                key = (county, link)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Listing(
                    source=self.slug, source_url=link, listing_type=ListingType.TAX_SALE,
                    state="SC", county=county,
                    description=title[:200],
                    foreclosure_process="tax",
                    raw={"flc": {"auctioneer": "Terry Howe", "auction_title": title[:200],
                                 "source": "forfeited_land_commission", "bundle": True}},
                ))
        log.info("terry_howe_flc.done", count=len(out))
        return out
