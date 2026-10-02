"""Coastal SC Master-in-Equity foreclosure-sale rosters via publicindex.sccourts.org.

Built 2026-06-24 for the COASTAL track. The dashboard had 0 oceanfront-tagged
leads because no SOURCE fed the near-beach gate (main._check_oceanfront /
oceanfront.is_oceanfront) for the out-of-footprint coastal counties. This
scraper feeds it.

It reuses the exact publicindex flow that ``sc_county_rosters.py`` already
drives for the upstate counties:

    Disclaimer.aspx -> Accept -> RosterSelection.aspx -> RosterDetails (RosterCode=MO)

verified 2026-06-24 against the live host for every coastal county. Each
county's RosterSelection page exposes Master-in-Equity ("MO") sale rosters
whose "Foreclosure 420" sub-type rows are the foreclosure sales:

    Horry       -> 10 MO rosters live   (Grand Strand: Myrtle Beach, N Myrtle, Surfside)
    Beaufort    -> 17 MO rosters live   (Hilton Head, Fripp, Hunting Island)
    Georgetown  ->  2 MO rosters live   (Pawleys Island, Litchfield, DeBordieu)
    Colleton    ->  1 MO roster  live   (Edisto Beach)

Charleston is DELIBERATELY EXCLUDED: its publicindex courtrosters app exposes
NO Master-in-Equity roster type (verified 2026-06-24 — the RosterType dropdown
lists only Removal/Motion/Trial/Transfer dockets, no MO/Foreclosure). Charleston
County runs its Master-in-Equity foreclosure sales through a separate system, so
downtown-Charleston peninsula leads must come from another source (NC/SC ROD /
lis-pendens paths), not this roster scraper.

KEY DIFFERENCE vs. the upstate roster scraper: these counties are OUT of the
18-county footprint and only re-enter scope through the oceanfront / downtown-
Charleston gate in ``main._in_scope`` — which runs at INGEST, BEFORE the
enrichment chain geocodes anything. ``is_oceanfront`` treats precise lat/lng as
authoritative (a single near-beach distance hit admits the lead), but with NO
coordinates it falls back to a 2-of-3 keyword/street heuristic that MIE roster
rows (parcel# only, no address text) can never satisfy. So a coastal roster row
with only a TMS would be DENIED before geocoding ever runs.

Fix: we resolve each TMS -> lat/lng (+ address/owner/assessed) AT SCRAPE TIME.

2026-06-24 ... 2026-08-12 this went through the shared statewide SCDOT parcel
MapServer (enrichment_arcgis.SCDOT_BASE / SC_LAYER). SCDOT went TOKEN-WALLED
2026-08-12 (HTTP 200 + ``{"error":{"code":499,"message":"Token Required"}}`` on
every layer, re-confirmed live 2026-10-02) and has stayed walled since —
_resolve_tms's old SCDOT-only implementation treated the wall identically to a
genuine "TMS not found" miss, so this scraper's geo-enrichment silently
returned 0 resolved for ~2 months while still reporting success.

2026-10-02 rebuild: each coastal county now resolves against its OWN
county-native, token-free ArcGIS endpoint instead (_COASTAL_SC_GIS below),
live-verified against real roster TMS values this session (see that dict's
docstring for per-county hit rates and residual gaps). Horry — previously
scoped (this file already carried a dedicated test fixture for its MO roster
layout) but never actually wired into COASTAL_COUNTIES, and excluded "per
scope" from the 2026-08-12 county-native discovery doc because nobody had
looked yet — gets a working two-layer resolver (county's own public
parcelapp/HorryCountyGISApp MapServer) and is added to the crawled counties
for the first time here.

Free + compliant: publicindex via the stealth browser (no CAPTCHA/login/WAF
defeat — just the public Disclaimer accept), every GIS endpoint via plain HTTP,
no token, no paid APIs.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Iterable, Optional

import httpx
import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...enrichment_arcgis import _apply_attrs
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from .sc_county_rosters import ACCEPT_BTN, HOST

log = structlog.get_logger()

# Coastal county-url-slug -> display name. Only the counties whose publicindex
# RosterSelection exposes a Master-in-Equity SALE roster (verified live
# 2026-06-24). Charleston omitted on purpose (no Master roster at all — see
# module docstring). Horry added 2026-10-02 (verified live: real "Foreclosure
# 420" rows under RosterCode=MO today) — it was scoped from day one (the MO
# layout test fixture below predates this change) but never actually added to
# this dict, so it was never crawled.
COASTAL_COUNTIES: dict[str, str] = {
    "horry": "Horry",
    "beaufort": "Beaufort",
    "georgetown": "Georgetown",
    "colleton": "Colleton",
}

# The RosterCode that holds the foreclosure SALE roster differs per county
# (verified live 2026-06-24 by inspecting each RosterSelection page):
#   Horry      -> MO   ("Master/Sale before Master" rows carry a TMS at cell 9)
#   Beaufort   -> SALE ("Master's Sales"; 9-col layout, R-prefixed PIN at cell 7)
#   Georgetown -> MO + SALE  (SALE when present; MO is the hearing docket)
#   Colleton   -> MO + SALE
# We try every listed code per county and keep whatever yields Foreclosure-420
# rows with a parcel identifier. Order matters only for de-dupe stability.
COUNTY_SALE_CODES: dict[str, tuple[str, ...]] = {
    "horry": ("MO",),
    "beaufort": ("SALE", "MO"),
    "georgetown": ("SALE", "MO"),
    "colleton": ("SALE", "MO"),
}

# Most-recent N sale rosters per county (one per sale day) to bound run time.
# Coastal counties run frequent sales, so 4 covers ~the next month of dates.
MAX_ROSTERS_PER_COUNTY = 4

# ---- TMS/PIN -> lat/lng (+ owner/situs/value/deed) resolvers, per county ---------
#
# Replaces the token-walled shared SCDOT MapServer (enrichment_arcgis.SCDOT_BASE,
# dead since 2026-08-12 — see module docstring) with each county's OWN free,
# token-free ArcGIS endpoint. This is an EXACT-match lookup on the parcel id
# field(s), NOT the address-LIKE matching enrichment_arcgis.SC_GIS/enrich() does
# elsewhere — a roster row has only a bare TMS/PIN at this point, no address to
# seed an address search from. We deliberately do NOT reuse SC_GIS/enrich()'s
# address-matching code path here for that reason, even though the config
# SHAPE below (url + which field(s) to match) mirrors it.
#
# Live-verified 2026-10-02 against REAL roster rows pulled this session:
#   Beaufort:   4/4 real roster PINs resolved (ParcelPIN, grouped R-PIN format;
#               _tms_candidates' existing regrouping logic handles it unchanged).
#   Horry:      14/19 real roster TMS values resolved against HorryCountyGISApp
#               layer 24 (owner/mailing/deed/sale/value + geometry), 9 of those
#               14 also got a situs address from layer 22 ("Addresses", joined
#               by the same TMS). The 5 misses were either a 4-digit-not-3
#               trailing dash segment or otherwise didn't match any candidate
#               form tried — plausible GIS-layer lag on a recently split/platted
#               lot, not chased further this session.
#   Georgetown / Colleton: COULD NOT be demonstrated against a real roster row
#               today — both counties had zero active MO/SALE rosters when this
#               was built (roster cadence varies; see expected_min_count=0 on
#               SCCoastalRosters below). The endpoints themselves are live and
#               return real owner/situs data for a known parcel from
#               docs/sc_gis_endpoints_coastal.md's own live samples — only the
#               roster-TMS-to-GIS-field format match is unverified. The LIKE
#               fallback in _query_layer exists specifically as a safety net
#               for these two until a real roster row can confirm the exact
#               format.
#   Charleston: kept for parity / a future Charleston source, NOT live-tested
#               this session — the host returned HTTP 200 +
#               {"error":{"code":500,"message":"...not started"}} on 2026-10-02
#               (a transient ArcGIS Server stop, not a token wall). Its layer
#               (61) has no situs column at all regardless (owner+mailing only
#               — see enrichment_arcgis.SC_GIS["Charleston"]).
_COASTAL_SC_GIS: dict[str, dict[str, Any]] = {
    "Horry": {
        "layers": (
            # CAMA: owner/mailing/deed/sale/value + the parcel polygon (the
            # geometry we actually need for lat/lng). No situs column.
            {
                "url": "https://www.horrycounty.org/parcelapp/rest/services/HorryCountyGISApp/MapServer/24/query",
                "id_fields": ("TMS",),
            },
            # Situs address only, joined by the same TMS. No useful geometry.
            {
                "url": "https://www.horrycounty.org/parcelapp/rest/services/HorryCountyGISApp/MapServer/22/query",
                "id_fields": ("TMS",),
            },
        ),
    },
    "Beaufort": {
        "layers": (
            {
                "url": "https://gis.beaufortcountysc.gov/server/rest/services/EnerGov/MapServer/1/query",
                "id_fields": ("ParcelPIN", "GisFile_PIN"),
            },
        ),
    },
    "Georgetown": {
        "layers": (
            {
                "url": "https://gis1.georgetowncountysc.org/portal/rest/services/GCGIS_Energov/MapServer/2/query",
                "id_fields": ("TMS",),
            },
        ),
    },
    "Colleton": {
        "layers": (
            {
                "url": "https://services1.arcgis.com/m0cnLGKdhwao8WvM/arcgis/rest/services/Public_Data/FeatureServer/2/query",
                "id_fields": ("PIN",),
            },
        ),
    },
    "Charleston": {
        "layers": (
            {
                "url": "https://gisccapps.charlestoncounty.org/arcgis/rest/services/GIS_VIEWER/New_Parcel_Search/MapServer/61/query",
                "id_fields": ("PID",),
            },
        ),
    },
}


def _tms_candidates(raw: str) -> list[str]:
    """Generate the parcel-id forms a county-native GIS layer might store for
    a roster TMS/PIN.

    Formats seen live (2026-06-24 against SCDOT; re-confirmed 2026-10-02
    against the county-native replacements — the same grouping logic matched
    4/4 real Beaufort roster PINs unchanged):
      * Numeric TMS (Horry/Georgetown/Colleton) — dashed ``267-12-03-0046`` or
        bare ``1860801332``; the GIS layer typically stores the dash-free
        digits (Horry confirmed live).
      * Letter-prefixed grouped PIN (Beaufort uses "R"; the live county layer
        also has "M"-prefixed parcels elsewhere in its roll, so this is not
        hardcoded to R) — roster gives ``R60002500000480000`` (R + 17 digits)
        but the layer stores it spaced as ``R600 025 000 0048 0000``
        (letter + 3-3-3-4-4 groups). We re-emit the grouped form so it matches.
    Yields raw + normalized variants, de-duped in order.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    out: list[str] = []

    def add(v: str) -> None:
        v = v.strip()
        if v and v not in out:
            out.append(v)

    add(raw)
    # Letter-prefixed grouped PIN (Beaufort's live roll uses "R", "M", ...):
    # regroup the digits as 3-3-3-4-4. The roster sometimes truncates the
    # trailing group to 2 chars ("...0887 00") while the GIS layer stores the
    # full 4 ("...0887 0000"), so pad the last group to 4.
    rm = re.match(r"^([A-Za-z])\s*([\d ]+)$", raw)
    if rm:
        prefix = rm.group(1).upper()
        groups = rm.group(2).split()
        d = re.sub(r"\D", "", rm.group(2))
        if groups:
            groups[-1] = groups[-1].ljust(4, "0")
            add(prefix + " " + " ".join(groups))
        if len(d) >= 16:
            add(f"{prefix}{d[0:3]} {d[3:6]} {d[6:9]} {d[9:13]} {d[13:17]}")
            add(f"{prefix}{d}")
        # Padded-last-group canonical (handles "...0185 00" -> "...0185 0000").
        if len(d) >= 13:
            tail = d[13:].ljust(4, "0")[:4]
            add(f"{prefix}{d[0:3]} {d[3:6]} {d[6:9]} {d[9:13]} {tail}")
    # Numeric TMS variants.
    digits = re.sub(r"\D", "", raw)
    add(digits)
    add(digits.lstrip("0"))
    return out


async def _query_layer(
    c: httpx.AsyncClient, url: str, id_fields: tuple[str, ...], tms: str,
) -> Optional[dict[str, Any]]:
    """Try every (candidate, field) pair as an EXACT match against one
    county-native layer, returning the first hit's attributes (+ a
    ``_centroid`` (lat, lng) when the layer returned polygon/point geometry).
    None on a miss against every candidate.

    We can't know a priori whether the id column is typed as text or a
    number, so a quoted (string) match is tried for every field and, when the
    candidate is all-digits, ALSO an unquoted (numeric) match — mirroring the
    old SCDOT resolver's approach. Bad type combinations error out (HTTP 200 +
    an ``error`` body) and are skipped rather than raising.

    Last resort: a LIKE match on the candidate's raw digits, wrapped in
    wildcards, for a county whose roster TMS format doesn't exactly match the
    GIS layer's own dash/zero-padding convention (Georgetown/Colleton were NOT
    confirmable against a live roster row this session — see _COASTAL_SC_GIS's
    docstring). Only accepted when it returns EXACTLY one feature; an
    ambiguous multi-hit is treated as a miss rather than risk a wrong parcel.
    """

    async def _query(where: str, limit: int = 1) -> Optional[list[dict[str, Any]]]:
        try:
            r = await c.get(
                url,
                params={
                    "where": where,
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultRecordCount": str(limit),
                    "f": "json",
                },
                timeout=20.0,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            if "error" in data:  # e.g. quoting a string against an int column
                return None
            feats = data.get("features") or []
            return feats or None
        except (httpx.HTTPError, ValueError):
            return None

    def _to_attrs(feat: dict[str, Any]) -> dict[str, Any]:
        attrs = dict(feat.get("attributes") or {})
        geom = feat.get("geometry") or {}
        if "x" in geom and "y" in geom:
            attrs["_centroid"] = (geom["y"], geom["x"])
        elif geom.get("rings"):
            pts = [p for ring in geom["rings"] for p in ring]
            if pts:
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                attrs["_centroid"] = (cy, cx)
        return attrs

    # Per-field, per-candidate exact match. ONE query each so a type mismatch
    # on one column can't poison the rest of the search.
    for cand in _tms_candidates(tms):
        esc = cand.replace("'", "''")
        for fld in id_fields:
            feats = await _query(f"{fld}='{esc}'")
            if feats:
                return _to_attrs(feats[0])
            if cand.isdigit():
                feats = await _query(f"{fld}={cand}")
                if feats:
                    return _to_attrs(feats[0])

    digits = re.sub(r"\D", "", tms)
    if len(digits) >= 6:
        for fld in id_fields:
            feats = await _query(f"{fld} LIKE '%{digits}%'", limit=2)
            if feats and len(feats) == 1:
                return _to_attrs(feats[0])
    return None


async def _resolve_tms(c: httpx.AsyncClient, county: str, tms: str) -> Optional[dict[str, Any]]:
    """Resolve a roster TMS/PIN to lat/lng (+ owner/situs/value/deed) via the
    county-native endpoint(s) configured in ``_COASTAL_SC_GIS``. Most counties
    are a single layer; Horry's CAMA and situs-address data live on two
    separate layers keyed by the same TMS, so every configured layer is
    queried and the hits merged (first layer's non-empty values and geometry
    win on any key collision). None when every configured layer misses.
    """
    cfg = _COASTAL_SC_GIS.get(county)
    if not cfg:
        return None
    merged: Optional[dict[str, Any]] = None
    for layer in cfg["layers"]:
        attrs = await _query_layer(c, layer["url"], layer["id_fields"], tms)
        if not attrs:
            continue
        if merged is None:
            merged = attrs
        else:
            for k, v in attrs.items():
                if k not in merged or merged[k] in (None, "", "<Null>"):
                    merged[k] = v
    if merged is not None and merged.get("_centroid"):
        merged["_match_confident"] = True
        return merged
    return None


def _select_sale_rosters(selection_html: str, codes: tuple[str, ...]) -> list[tuple[str, Optional[datetime]]]:
    """From a RosterSelection page, return the foreclosure-SALE roster links
    (href, sale_date) for the requested RosterCodes, newest sale date first,
    capped at MAX_ROSTERS_PER_COUNTY. Hearing/motion dockets and non-sale
    rosters are excluded; selection is by parsed DATE, never URL string order."""
    tree = HTMLParser(selection_html)
    cand: list[tuple[str, Optional[datetime]]] = []
    seen: set[str] = set()
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").replace("&amp;", "&").strip()
        if "RosterDetails.aspx" not in href:
            continue
        m = re.search(r"RosterCode=([A-Za-z]+)", href)
        if not m or m.group(1) not in codes:
            continue
        text = a.text() or ""
        if not _is_sale_roster(text):
            continue
        if href in seen:
            continue
        seen.add(href)
        cand.append((href, _roster_date(text)))
    # Newest sale date first; rosters with no parseable date sort last.
    cand.sort(key=lambda x: (x[1] is not None, x[1] or datetime.min), reverse=True)
    return cand[:MAX_ROSTERS_PER_COUNTY]


async def _fetch_county(county_slug: str, codes: tuple[str, ...]) -> list[tuple[str, Optional[datetime]]]:
    """Drive Disclaimer -> RosterSelection -> RosterDetails for one coastal
    county in a single stealth-browser session. Selects the foreclosure-SALE
    rosters with the newest sale dates (see _select_sale_rosters). Returns
    (roster_html, sale_date_hint) per roster page."""
    from scrapling.fetchers import StealthyFetcher

    base = f"{HOST}/{county_slug}/courtrosters"
    roster_pages: list[tuple[str, Optional[datetime]]] = []

    async def action(page):
        await page.goto(f"{base}/Disclaimer.aspx", wait_until="domcontentloaded")
        try:
            await page.click(f'input[name="{ACCEPT_BTN}"]', timeout=8000)
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await page.goto(f"{base}/RosterSelection.aspx", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=8000)
        selection = await page.content()
        for path, rdate in _select_sale_rosters(selection, codes):
            await page.goto(f"{base}/{path}", wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=8000)
            roster_pages.append((await page.content(), rdate))
        return page

    try:
        await StealthyFetcher.async_fetch(
            f"{base}/Disclaimer.aspx", headless=True, timeout=60000, page_action=action
        )
    except Exception:
        return []
    return roster_pages


# Parcel/TMS identifiers as they appear in roster cells: a numeric TMS (10-13
# digits, optionally dashed) OR a Beaufort-style R-prefixed grouped PIN.
_PARCEL_CELL_RE = re.compile(
    r"^(?:R\s*[\d ]{14,22}|\d[\d.\-\s]{8,16}\d)$"
)
_CASE_RE = re.compile(r"\b(\d{4}CP\d{4,8})\b")
_AMT_RE = re.compile(r"\$([\d,]+\.\d{2})")

# Roster-link triage. The MO/SALE RosterCode mixes actual foreclosure-SALE
# rosters ("Foreclosure Sale - June 1, 2026") with motion/hearing dockets
# ("CPNJ Motions", "Settlement Hearings") under the SAME code. We must keep only
# the sale rosters, and select them by the SALE DATE in the link text — NOT by a
# lexicographic URL sort, which silently grabbed stale past rosters (the original
# bug: every emitted lead was a sale that had already happened).
_HEARING_WORDS = (
    "motion", "hearing", "settlement", "trial", "transfer", "removal",
    "docket", "cpnj", "status conf", "roster call", "non-jury", "non jury",
    "jury", "calendar call", "pre-trial", "pretrial",
)
_ROSTER_DATE_RE = re.compile(
    r"([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})"
)


def _is_sale_roster(text: str) -> bool:
    """True only for a foreclosure SALE roster (not a hearing/motion docket)."""
    t = (text or "").lower()
    if any(w in t for w in _HEARING_WORDS):
        return False
    return "sale" in t  # "Foreclosure Sale", "Master's Sales", "Upset Bid Sale"


def _roster_date(text: str) -> Optional[datetime]:
    """Parse the sale date out of a roster link's label, e.g.
    'Foreclosure Sale - June 1, 2026' or 'Master's Sale 7/6/2026'."""
    m = _ROSTER_DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return dateparser.parse(m.group(1))
    except (ValueError, TypeError, OverflowError):
        return None


def _clean_cell(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def parse_sale_roster(html: str, roster_url: str, county: str,
                      roster_date: Optional[datetime] = None) -> list[Listing]:
    """Layout-tolerant parser for a publicindex RosterDetails sale page.

    The coastal counties use DIFFERENT column layouts (Horry MO = 13 cols with
    TMS at cell 9; Beaufort SALE = 9 cols with R-PIN at cell 7), so instead of
    fixed indices we scan every cell of each row for the load-bearing tokens:
    the "Foreclosure 420" sub-type, a parcel/TMS identifier, the case number,
    a sale date, and a $ judgment/bid amount. Only rows that are Foreclosure 420
    AND have a parcel identifier are emitted (a parcel is required so the SCDOT
    geo-resolver can place it for the near-beach gate)."""
    out: list[Listing] = []
    tree = HTMLParser(html)
    for tr in tree.css("tr.standardRow, tr.altRow"):
        cells = [_clean_cell(td.html or "") for td in tr.css("td")]
        if len(cells) < 6:
            continue
        blob = " | ".join(cells)
        if "foreclosure 420" not in blob.lower():
            continue

        parcel = None
        for cell in cells:
            cc = cell.strip()
            if _PARCEL_CELL_RE.match(cc) and re.search(r"\d", cc):
                parcel = cc
                break
        if not parcel:
            continue  # no parcel -> can't geo-resolve -> can't pass the gate

        case_m = _CASE_RE.search(blob)
        case_number = case_m.group(1) if case_m else None

        sale_date = None
        for cell in cells:
            m = re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", cell.strip())
            if m:
                try:
                    sale_date = dateparser.parse(cell.strip())
                    break
                except (ValueError, TypeError):
                    pass
        # Fall back to the roster's own sale date (from the RosterSelection link
        # label, e.g. "Foreclosure Sale - July 6, 2026") when no per-row cell
        # date is present — so the active-window filter has a real date to judge.
        if sale_date is None:
            sale_date = roster_date

        sale_time = None
        for cell in cells:
            if re.match(r"^\d{1,2}:\d{2}\s*[AP]M$", cell.strip(), re.I):
                sale_time = cell.strip()
                break

        opening_bid = None
        amt_m = _AMT_RE.search(blob)
        if amt_m:
            try:
                opening_bid = float(amt_m.group(1).replace(",", ""))
            except ValueError:
                pass

        # Plaintiff: the caption cell usually starts "<case#> <Plaintiff> ...,
        # plaintiff". Pull the text between case number and ", plaintiff".
        plaintiff = None
        defendant = None
        cap_m = re.search(
            r"\d{4}CP\d{4,8}\s+(.+?),\s*plaintiff", blob, re.I)
        if cap_m:
            plaintiff = cap_m.group(1).strip()[:200]
        def_m = re.search(r"\bvs\.?\s+(.+?)(?:,?\s*defendant|,?\s*et al|\|)",
                          blob, re.I)
        if def_m:
            defendant = def_m.group(1).strip()[:200]

        out.append(
            Listing(
                source="counties_sc.sc_coastal_rosters",
                source_url=roster_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county=county,
                parcel_id=parcel,
                sale_date=sale_date,
                sale_time=sale_time,
                opening_bid=opening_bid,
                plaintiff=plaintiff,
                defendant=defendant,
                case_number=case_number,
                foreclosure_process="judicial",
                auction_status="active",
                description=blob[:500] or None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sc_coastal_roster": {"county": county, "roster_url": roster_url}},
            )
        )
    return out


async def _geo_enrich(listings: list[Listing]) -> int:
    """Resolve TMS -> lat/lng (+ address/owner/assessed) for each listing via
    each county's own county-native GIS endpoint(s) (_COASTAL_SC_GIS), IN
    PLACE, so coordinates are present before the scope gate. Returns the
    number of listings that got coordinates."""
    by_county: dict[str, list[Listing]] = {}
    for li in listings:
        if not li.parcel_id:
            continue
        cn = (li.county or "").replace(" County", "").strip().title()
        if cn in _COASTAL_SC_GIS:
            by_county.setdefault(cn, []).append(li)
    if not by_county:
        return 0

    resolved = 0
    sem = asyncio.Semaphore(10)

    async def one(c: httpx.AsyncClient, county: str, li: Listing) -> None:
        nonlocal resolved
        async with sem:
            attrs = await _resolve_tms(c, county, li.parcel_id or "")
        if attrs:
            had_geo = li.latitude is not None and li.longitude is not None
            _apply_attrs(li, attrs)
            if not had_geo and li.latitude is not None and li.longitude is not None:
                resolved += 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            # NOTE: key name kept as "scdot_parcel_resolved" even though SCDOT
            # itself is no longer queried here — it's in web_artifact.py's
            # RAW_KEEP publish allowlist under that name, and renaming it would
            # need a matching RAW_KEEP change to avoid the key being silently
            # dropped at publish. Not worth the churn for a bookkeeping flag.
            li.raw["scdot_parcel_resolved"] = True

    async with client(timeout=25.0) as c:
        await asyncio.gather(
            *(one(c, county, li) for county, lis in by_county.items() for li in lis)
        )
    return resolved


class SCCoastalRosters(BaseScraper):
    slug = "counties_sc.sc_coastal_rosters"
    name = "SC Coastal MIE Rosters (publicindex + SCDOT geo)"
    category = "county_court"
    expected_min_count = 0  # roster cadence varies; some weeks a county has 0 sales
    requires_render = True
    timeout_s = 900.0

    async def fetch(self) -> Iterable[Listing]:
        # Bank rows as they are collected: if the soft timeout fires,
        # base_scraper ships self.partial instead of discarding the run.
        out = self.partial
        seen: set[tuple] = set()

        # Run all counties in PARALLEL — each gets its own stealth browser session
        # so they don't block on each other's page loads.
        county_tasks = []
        for slug, county in COASTAL_COUNTIES.items():
            codes = COUNTY_SALE_CODES.get(slug, ("MO",))
            county_tasks.append(_fetch_county(slug, codes))
        all_pages = await asyncio.gather(*county_tasks, return_exceptions=True)

        for slug_idx, (slug, county) in enumerate(COASTAL_COUNTIES.items()):
            pages = all_pages[slug_idx]
            if isinstance(pages, Exception):
                log.error("sc_coastal_rosters.county_failed", county=county, error=str(pages))
                continue
            base = f"{HOST}/{slug}/courtrosters"
            for html, rdate in pages:
                for li in parse_sale_roster(
                    html, f"{base}/RosterSelection.aspx", county, rdate
                ):
                    key = (li.county, li.case_number or li.parcel_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(li)

        # Resolve TMS -> lat/lng so the near-beach gate can admit these at
        # ingest. Without this every row dies at main._in_scope (out-of-
        # footprint county + no coords -> oceanfront 2-of-3 fallback fails).
        try:
            n = await _geo_enrich(out)
            log.info("sc_coastal_rosters.geo", rows=len(out), resolved=n)
        except Exception:
            log.error("sc_coastal_rosters.geo_failed", exc_info=True)
        return out
