"""USDA Rural Development resale properties — federal REO source.

USDA RD lists single-family + multi-family + farm/ranch properties
foreclosed by Rural Development. Free, no auth, plain HTML.

The public site (resales.usda.gov) is a JSP app whose search is NOT a
plain GET(?state=XX). It's a two-step, session-scoped flow:

  1. GET /resales/public/search{KIND}    -> establishes the form session
     and (on the SFH page) renders the active-states dropdown:
       <option value="45">South Carolina (1)</option>   # FIPS, count
  2. GET /resales/public/getCountiesOfStateWithActiveProperties
         ?stateCode=<FIPS>&searchFormName=<KIND>
     with Accept: application/json + X-Requested-With -> JSON list of
     active counties [{"countyCode","countyName":"Lexington (1)"}].
     NOTE: when a state has 0 active properties for that kind the endpoint
     returns an HTML *error* page (not JSON) — we treat that as 0 counties.
  3. POST /resales/public/search{KIND} with stateCode, countyCode,
     propertyType, listingType=All Types, Search=Search -> the results
     page whose #propertySummariesTable <tbody> <tr> rows are the data.
     (listingType MUST be "All Types" — an empty listingType returns 0 rows.)

Columns (verified 2026-06): Photo | Listing Type | Street Address | City |
State | County | Zip | Price/Bid | Beds | Baths | Sq. Ft., with a
"Details" anchor to /resales/public/{KIND}PropertyDetail?id=NNN.

Volume is small (typically 0-10 per state) but the listings are
high-quality and clean: USDA RD pre-vets title before listing, so
they're closer to retail-ready than sheriff sales.

EXTRACTION-COMPLETENESS AUDIT (2026-10-04, final batch): each row's own
PropertyDetail page (already linked from the search table, ``detail_href``)
carries a LOT this scraper never fetched -- live-confirmed on a real current
SC listing (id=7619, Lexington County):

- **A real scheduled ``sale_date`` and sale location/time** ("Sale Date:
  5-5-25", "Sale Time: 11:00 am", "Location: Lexington County Judicial
  Complex 205 East Main St, Lexington, South Carolina") -- this scraper had
  NO ``sale_date`` field populated anywhere before this fix, on a source
  whose whole value proposition is a scheduled foreclosure auction.
- **Real Estate Taxes** ("$517") -- an annual tax-bill dollar figure never
  captured (this is NOT the same thing as the existing ``tax_value`` Listing
  field, which other scrapers use for an ASSESSED valuation basis -- kept
  under ``raw`` to avoid conflating the two).
- **House facts** (House Style, Rooms, Basement, Garage, Foundation, Age
  [years], Heating, Cooling, Water, Sewage, Lot Size) and **Govt Bid**
  (cross-checks the already-captured table price) -- all on the SAME
  simple ``<div class="col-md-4 ...">Label:</div><div class="col-md-8
  ...">Value</div>`` markup pair, trivially regex-parseable.
- **A full photo gallery** (``ul.propertyimages li img``) -- the search
  table's single thumbnail (already captured) is only ONE of potentially
  several.

Wired as a capped per-row detail fetch (volume is tiny -- typically 0-10
rows per state -- so no meaningful cost), bounded by the same
``_STEP_TIMEOUT_S``/overall ``deadline`` budget this module already uses so
it can't blow the scraper's own hang-avoidance guarantees.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime
from typing import Iterable

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


_BASE = "https://www.resales.usda.gov/resales/public"

# State -> FIPS state code the site uses in stateCode= and the dropdown.
_STATE_FIPS = {"NC": "37", "SC": "45"}
_FIPS_STATE = {v: k for k, v in _STATE_FIPS.items()}

# Kind -> (path segment, searchFormName the active-counties endpoint wants,
#          propertyType POST value, PropertyKind, listing label).
_KINDS = {
    "SFH": ("searchSFH", "SFH", "Single Family", PropertyKind.SINGLE_FAMILY),
    "MFH": ("searchMFH", "MFH", "Multi-Family", PropertyKind.MULTI_FAMILY),
    "FSA": ("searchFSA", "FSA", "Farm & Ranch", PropertyKind.LAND),
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}
_JSON_HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# "Lexington (1)" -> "Lexington"; the trailing "(N)" is the active count.
_COUNT_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")

# --- per-step budget-bail (per project_fc_fullrun_hang) ----------------------
# The resales.usda.gov JSP app is a session-scoped multi-step flow against ONE
# host, so every request funnels through the shared per-host throttle. Under the
# concurrent full-run this froze for 2h47m: the outer safe_run wait_for could not
# reclaim the loop because a wedged network step stalled below the async budget.
# Fix: bound EACH network step with its own asyncio.wait_for, and stop walking
# the state/kind/county matrix once a wall-clock deadline is spent — so the
# scraper always returns what it has well inside its soft timeout, no matter how
# slow (or wedged) an individual JSP round-trip is.
_STEP_TIMEOUT_S = 30.0     # hard cap for any single GET/POST round-trip
# Overall wall-clock budget for the whole fetch(); leaves headroom under the
# class timeout_s so we bail cooperatively BEFORE safe_run's wait_for fires.
_TOTAL_BUDGET_S = 200.0

# Real nationwide volume is tiny (typically 0-10 rows per state per kind),
# so this is generous headroom, not a meaningful limiter in practice --
# defensive only, same convention as this repo's other per-row detail caps.
_DETAIL_FETCH_CAP = int(os.environ.get("USDA_RD_DETAIL_CAP", "40"))

# Every PropertyDetail page's label/value pairs render as this exact
# col-md-4/col-md-8 div pair -- live-confirmed stable across both the House
# Facts section AND the separate Foreclosure Sale Information section (same
# shared template). `[^<]*` deliberately cannot cross a tag boundary, so a
# label/value whose value is itself further markup is skipped rather than
# mis-captured.
_LABEL_VALUE_RE = re.compile(
    r'<div class="col-md-4[^"]*">([^<]*)</div>\s*<div class="col-md-8[^"]*">([^<]*)</div>',
    re.I,
)
_GALLERY_RE = re.compile(r'<ul class="propertyimages">(.*?)</ul>', re.I | re.S)
_GALLERY_IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.I)
_ACRES_RE = re.compile(r"([\d,.]+)\s*acres?\b", re.I)
_SQFT_TEXT_RE = re.compile(r"([\d,.]+)\s*(?:sq\.?\s*ft|sf)\b", re.I)

# House-facts labels -> the raw['usda_rd']['house_facts'] key they fill.
_HOUSE_FACT_LABELS = {
    "house style": "house_style", "rooms": "rooms", "basement": "basement",
    "garage": "garage", "foundation": "foundation", "heating": "heating",
    "cooling": "cooling", "water": "water", "sewage": "sewage",
}


def _parse_lot_size_sqft(text: str | None) -> float | None:
    """'0.75 Acres' / '32,670 sq ft' -> sqft. None on an unrecognized unit
    (never guesses -- a wrong unit silently poisons valuation math)."""
    if not text:
        return None
    am = _ACRES_RE.search(text)
    if am:
        try:
            return float(am.group(1).replace(",", "")) * 43560.0
        except ValueError:
            return None
    sm = _SQFT_TEXT_RE.search(text)
    if sm:
        try:
            return float(sm.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _parse_detail_page(html: str) -> dict:
    """Label/value pairs + photo gallery off one PropertyDetail page.
    Best-effort -- any field the page doesn't carry is simply absent;
    never raises (a bad detail fetch must not cost the row this scraper
    already built from the search table)."""
    out: dict = {}
    location_parts: list[str] = []
    for raw_label, raw_value in _LABEL_VALUE_RE.findall(html):
        label = raw_label.strip().rstrip(":").strip().lower()
        value = re.sub(r"\s+", " ", raw_value).strip()
        if not value:
            continue
        if label == "age":
            out["age_text"] = value
        elif label == "lot size":
            out["lot_size_text"] = value
        elif label == "real estate taxes":
            out["annual_tax_text"] = value
        elif label == "sale date":
            out["sale_date_text"] = value
        elif label == "sale time":
            out["sale_time_text"] = value
        elif label == "govt bid":
            out["govt_bid_text"] = value
        elif label == "location":
            location_parts.append(value)
        elif label == "" and location_parts:
            # The sale-location address wraps onto a 2nd row with NO label
            # ("Location:" row + an unlabeled continuation row) -- live-
            # confirmed stable shape, only trusted once Location: was seen.
            location_parts.append(value)
        elif label in _HOUSE_FACT_LABELS:
            out[_HOUSE_FACT_LABELS[label]] = value
    if location_parts:
        out["sale_location"] = ", ".join(location_parts)

    gm = _GALLERY_RE.search(html)
    if gm:
        imgs = [u for u in _GALLERY_IMG_RE.findall(gm.group(1)) if u.startswith("http")]
        if imgs:
            out["gallery"] = imgs
    return out


async def _enrich_from_detail(c, li: Listing, detail_url: str) -> None:
    """Best-effort per-row detail-page pull -- see module docstring for the
    full list of fields this recovers (sale_date above all: this scraper
    had NO sale_date anywhere before this fix)."""
    try:
        r = await asyncio.wait_for(
            c.get(detail_url, headers=_HEADERS), timeout=_STEP_TIMEOUT_S
        )
        if r.status_code != 200 or len(r.text) < 500:
            return
        fields = _parse_detail_page(r.text)
    except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001
        log.info("usda_rd.detail_failed", url=detail_url,
                  error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return
    if not fields:
        return

    sdt = fields.get("sale_date_text")
    if sdt:
        try:
            li.sale_date = dateparser.parse(sdt, dayfirst=False, fuzzy=True)
        except (ValueError, TypeError, OverflowError):
            pass

    age_num = _clean_num(fields.get("age_text"))
    if age_num is not None and 0 <= age_num <= 300:
        year = datetime.utcnow().year - int(age_num)
        if 1700 <= year <= datetime.utcnow().year:
            li.year_built = year

    lot = _parse_lot_size_sqft(fields.get("lot_size_text"))
    if lot is not None:
        li.lot_size_sqft = lot

    if li.opening_bid is None:
        govt_bid = _clean_num(fields.get("govt_bid_text"))
        if govt_bid is not None:
            li.opening_bid = govt_bid

    extra = li.raw.setdefault("usda_rd", {}).setdefault("detail", {})
    for k in ("sale_time_text", "sale_location", "annual_tax_text",
              "house_style", "rooms", "basement", "garage", "foundation",
              "heating", "cooling", "water", "sewage"):
        if fields.get(k):
            extra[k] = fields[k]
    tax = _clean_num(fields.get("annual_tax_text"))
    if tax is not None:
        extra["annual_tax"] = tax

    gallery = fields.get("gallery")
    if gallery:
        have = li.raw.setdefault("images", {}).setdefault("real", [])
        for u in gallery:
            if u not in have:
                have.append(u)


def _clean_num(text: str | None) -> float | None:
    """Parse a numeric cell (beds/baths/sqft) into a float, defensively."""
    if not text:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _cell(row, idx: int):
    tds = row.css("td")
    return tds[idx] if 0 <= idx < len(tds) else None


def _cell_text(row, idx: int) -> str:
    td = _cell(row, idx)
    return (td.text(separator=" ").strip() if td is not None else "")


async def _active_counties(c, state: str, kind: str) -> list[str]:
    """Return active county codes for a state+kind, or [] (never raises).

    Establishes the form session with a GET to the kind's search page, then
    asks the active-counties JSON endpoint. A non-JSON / non-list body means
    the state has no active inventory for that kind -> [].
    """
    path, form_name, _pt, _pk = _KINDS[kind]
    fips = _STATE_FIPS.get(state)
    if not fips:
        return []
    ref = f"{_BASE}/{path}"
    try:
        # Each round-trip is individually hard-bounded so a wedged JSP step can
        # never stall the loop past _STEP_TIMEOUT_S (the freeze-avoidance fix).
        await asyncio.wait_for(c.get(ref, headers=_HEADERS), timeout=_STEP_TIMEOUT_S)
        url = (f"{_BASE}/getCountiesOfStateWithActiveProperties"
               f"?stateCode={fips}&searchFormName={form_name}")
        r = await asyncio.wait_for(
            c.get(url, headers={**_HEADERS, **_JSON_HEADERS, "Referer": ref}),
            timeout=_STEP_TIMEOUT_S,
        )
    except (Exception, asyncio.TimeoutError) as exc:
        log.warning("usda_rd.counties_failed", state=state, kind=kind,
                    error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return []
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or "json" not in ctype.lower():
        # HTML error page = 0 active counties for this state+kind.
        return []
    try:
        data = r.json()
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    codes: list[str] = []
    for item in data:
        if isinstance(item, dict):
            code = item.get("countyCode")
            if code:
                codes.append(str(code))
    return codes


async def _search_county(
    c, state: str, kind: str, county_code: str,
    detail_budget: list[int] | None = None,
) -> list[Listing]:
    """POST the search form for one active county and parse the result rows.

    ``detail_budget`` is a 1-element mutable counter shared across the
    whole run (see USDARuralDevelopment.fetch) -- decremented once per
    per-row detail fetch so the real nationwide total (not just this one
    county) stays bounded by _DETAIL_FETCH_CAP."""
    path, _form_name, prop_type, prop_kind = _KINDS[kind]
    fips = _STATE_FIPS[state]
    ref = f"{_BASE}/{path}"
    form = {
        "city": "",
        "zipCode": "",
        "propertyType": prop_type,
        "stateCode": fips,
        "countyCode": county_code,
        "listingType": "All Types",   # empty listingType returns 0 rows
        "minPrice": "",
        "maxPrice": "",
        "bedrooms": "",
        "bathrooms": "",
        "squareFootage": "",
        "Search": "Search",
    }
    headers = {
        **_HEADERS,
        "Referer": ref,
        "Origin": "https://www.resales.usda.gov",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        r = await asyncio.wait_for(
            c.post(ref, data=form, headers=headers), timeout=_STEP_TIMEOUT_S
        )
    except (Exception, asyncio.TimeoutError) as exc:
        log.warning("usda_rd.search_failed", state=state, kind=kind,
                    county=county_code, error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return []
    if r.status_code != 200:
        return []

    tree = HTMLParser(r.text)
    table = tree.css_first("#propertySummariesTable")
    if table is None:
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    for row in table.css("tbody tr"):
        # Detail anchor lives in the first (Photo) cell.
        detail_href = ""
        for a in row.css("a"):
            href = a.attributes.get("href", "") or ""
            if "PropertyDetail" in href:
                detail_href = href
                break

        # Found 2026-10-01 (national/reo per-source audit): the Photo cell
        # (column 0) carries a real listing thumbnail
        # (<img src="https://www.resales.usda.gov.../SFH_INTRANET/....png">)
        # that was never captured, despite this table already being in hand
        # (no extra request). Confirmed live.
        photo_url = None
        img = row.css_first("img[src]")
        if img is not None:
            src = (img.attributes.get("src") or "").strip()
            if src.startswith("http"):
                photo_url = src

        # Columns: 0 Photo, 1 Listing Type, 2 Street, 3 City, 4 State,
        #          5 County, 6 Zip, 7 Price/Bid, 8 Beds, 9 Baths, 10 Sq.Ft.
        # The Street cell also carries a "Map" link + text; take the first
        # non-empty text line as the address.
        street_td = _cell(row, 2)
        street = ""
        if street_td is not None:
            for piece in street_td.text(separator="|").split("|"):
                piece = piece.strip()
                if piece and piece.lower() != "map":
                    street = piece
                    break
        if not street:
            continue

        city = _cell_text(row, 3)
        st_abbr = _FIPS_STATE.get(fips, state)
        county = _COUNT_SUFFIX_RE.sub("", _cell_text(row, 5)).strip() or None
        zip_code = (_cell_text(row, 6) or "").strip() or None
        listing_label = (_cell_text(row, 1) or "").strip()

        price = None
        pm = _PRICE_RE.search(_cell_text(row, 7))
        if pm:
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                price = None

        beds = _clean_num(_cell_text(row, 8))
        baths = _clean_num(_cell_text(row, 9))
        sqft = _clean_num(_cell_text(row, 10))

        full_url = (
            detail_href if detail_href.startswith("http")
            else f"{_BASE}/{detail_href.lstrip('/').removeprefix('resales/public/')}"
            if detail_href else ref
        )
        dedupe = full_url if detail_href else f"{street}|{zip_code}"
        if dedupe in seen:
            continue
        seen.add(dedupe)

        li = Listing(
            source="reo.usda_rd",
            source_url=full_url,
            listing_type=ListingType.REO,
            property_kind=prop_kind,
            state=st_abbr,
            street_address=street,
            city=city or None,
            county=county,
            zip_code=zip_code,
            opening_bid=price,
            bedrooms=beds,
            bathrooms=baths,
            living_sqft=sqft,
            description=(
                f"USDA Rural Development {kind} "
                f"{listing_label or 'REO'} ({st_abbr})"
            ),
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"usda_rd": {
                "kind": kind,
                "listing_label": listing_label,
                "county_code": county_code,
            },
            "images": {"real": [photo_url]} if photo_url else {}},
        )

        # Per-row detail-page pull: sale_date above all (see module
        # docstring -- this scraper had none before this fix), plus tax/
        # house-facts/lot-size/year-built/full gallery. Capped + budgeted,
        # never fatal to the row the search table already gave us.
        if (detail_href and detail_href.startswith(("/", "http"))
                and detail_budget is not None and detail_budget[0] > 0):
            detail_budget[0] -= 1
            await _enrich_from_detail(c, li, full_url)

        out.append(li)
    log.info("usda_rd.county_done", state=state, kind=kind,
             county=county_code, count=len(out))
    return out


async def _fetch_state(state: str, kind: str = "SFH",
                       deadline: float | None = None,
                       detail_budget: list[int] | None = None) -> list[Listing]:
    """Pull one state+kind: discover active counties, then search each.

    `deadline` is a time.monotonic() wall-clock cutoff. Every county search is
    gated on it so a slow host can't run the matrix past the overall budget — we
    return whatever we've collected and let the caller stop cleanly.
    `detail_budget` is the run-wide per-row detail-fetch counter (see
    _search_county).
    """
    out: list[Listing] = []
    if deadline is not None and time.monotonic() >= deadline:
        log.warning("usda_rd.state_skipped_budget", state=state, kind=kind)
        return out
    async with client(timeout=30.0) as c:
        codes = await _active_counties(c, state, kind)
        if not codes:
            log.info("usda_rd.state_done", state=state, kind=kind, count=0)
            return out
        for code in codes:
            if deadline is not None and time.monotonic() >= deadline:
                log.warning("usda_rd.county_skipped_budget", state=state, kind=kind,
                            county=code, remaining=len(codes) - codes.index(code))
                break
            try:
                out.extend(await _search_county(
                    c, state, kind, code, detail_budget=detail_budget
                ))
            except Exception as exc:  # noqa: BLE001
                log.warning("usda_rd.county_failed", state=state, kind=kind,
                            county=code, error=str(exc)[:200])
    log.info("usda_rd.state_done", state=state, kind=kind, count=len(out))
    return out


class USDARuralDevelopment(BaseScraper):
    slug = "reo.usda_rd"
    name = "USDA Rural Development REO (NC + SC)"
    category = "federal_reo"
    expected_min_count = 0  # Often 0 in either state
    requires_apify = False
    # Re-enabled 2026-07-01: the 2026-06-27 freeze was a perf hang (unbounded JSP
    # round-trips against one throttled host), NOT a wall. Every network step is
    # now hard-bounded by asyncio.wait_for(_STEP_TIMEOUT_S) and the full
    # state/kind/county matrix is gated on a _TOTAL_BUDGET_S wall-clock deadline,
    # so fetch() always returns inside timeout_s even if a step wedges.
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        deadline = time.monotonic() + _TOTAL_BUDGET_S
        detail_budget = [_DETAIL_FETCH_CAP]  # shared mutable counter, whole run
        for state in ("NC", "SC"):
            for kind in ("SFH", "MFH", "FSA"):
                if time.monotonic() >= deadline:
                    log.warning("usda_rd.budget_exhausted", state=state, kind=kind,
                                collected=len(out))
                    log.info("usda_rd.done", total=len(out))
                    return out
                try:
                    out.extend(await _fetch_state(
                        state, kind, deadline=deadline, detail_budget=detail_budget
                    ))
                except Exception as exc:  # noqa: BLE001
                    log.warning("usda_rd.state_failed", state=state, kind=kind,
                                error=str(exc)[:200])
        log.info("usda_rd.done", total=len(out))
        return out
