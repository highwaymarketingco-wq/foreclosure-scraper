"""Heir/estate/life-estate owner-of-record parcels read LIVE from the legacy ASP.NET
"WTH tgis" GIS viewer platform (`<county>sc.wthgis.com`), for SC counties that carry
no parcel_cache entry at all and so are invisible to this project's other heir/estate
producer, counties_sc.sc_heir_estate_parcel_cache.py (a pure-local parcel_cache read --
see that module's own 2026-11-16 docstring for the full registry-vs-live-GIS
distinction and its county-by-county dead-end research on this exact platform).

ROUND 18 (2026-11-17), closing gap_matrix's lt_estate_lead "no source known" bucket
(12 cells, all SC, zero est_rows total 268; see gap_list_2026-11-16.csv filtered to
lt_estate_lead/no source known). Confirmed FIRST that no mechanical derivation from
already-collected signals is correct here: a read-only board_stream scan of all 12
counties found plenty of rows that already carry a probate-flavored raw signal
(relationship_signal.kind=="probate", raw.probate, raw.sc_probate_notice) under OTHER
listing_types (distressed/lis_pendens/probate_notice), but Listing.merge()'s fill-only
field semantics (every field including listing_type keeps the FIRST-seen non-null
value) mean flipping an existing row's listing_type, or landing a same-parcel new
ESTATE_LEAD Listing on top of it, never changes what the published board shows --
exactly the documented behavior distress_score.py's ABSORBED_LIFE_TYPES exists to
compensate for (score the life-event signal, don't relabel the row). The SAME
fill-only-merge fact is independently confirmed by land_sc_heir_estate_parcel_cache.py's
own 2026-11-14 note: of that producer's 9,850 real hits, only the 2,948 that were
genuinely new parcels (no existing board row at all) landed; the other 6,902
"overlap an existing board row ... not attempted" to merge. So the only thing that
ever grows this column for real is a producer that finds NET-NEW parcels no other
scraper has already put on the board -- i.e. a genuinely new per-county source, same
conclusion scripts/ingest_chesterfield_wthgis.py's own commit note already reached
for all 12 cells ("zero scrapers anywhere set listing_type='estate_lead'").

That SAME commit (round 17, same day) separately built a WTH ASP.NET scraper for
Chesterfield (ingest_chesterfield_wthgis.py) for FOUR OTHER columns (assessed_value /
lot_size / atty_deed_ref / atty_legal_description) and live-confirmed, as a side
finding, that Chesterfield's own getftr.aspx detail page carries a real
"Owner&nbsp;Name" field (DSID=6796; sample: FeatureID 85, owner "Smith Kim Blakeney
Etal"). It did not build an owner-decedent pass itself -- that script's own job and
board-write were scoped to the other four columns' fields. This module reuses the
EXACT same live, already-proven WTH mechanics (search phase via
custom.aspx?RequestType=CustomSearchRequest&SearchType=Name, detail phase via
getftr.aspx) for THAT purpose: a COUNTY-WIDE decedent/life-estate owner sweep,
searched directly by decedent-indicating substring ("ESTATE", "HEIR" -- the same
two tokens nc_heir_estate_parcels.py's own _ESTATE_TOKEN/_HEIR_TOKEN test for, now
used as the live SearchCriteria since the WTH name index does a plain substring
match, not merely last-name-prefix: live-confirmed 2026-11-17, SearchCriteria=
"ESTATE|" alone returns 534 distinct Chesterfield parcels, not just surnames
starting with that word).

LIVE-VERIFIED 2026-11-17 (read-only GETs, no login/CAPTCHA, matching UA the sibling
ingest script already uses): Chesterfield DSID=6796, 605 distinct raw hits across
both tokens; a 24-point spread sample run through this project's OWN classifiers
(imported below, never reimplemented) scored 22/24 _is_life_estate, 1/24 a genuine
_is_decedent (non-life-estate) hit ("Heirs Ann C"), 1/24 correctly _excluded_row
("Walters Real Estate and...", a business) -- i.e. ~96% of raw hits are real,
correctly-classified ESTATE_LEAD-shape leads (mostly the "Life Estate" variety,
which this classifier treats as a genuine distinct lead type since 2026-11-10, not
noise), 0% unclassifiable. That is the ONLY county enabled in _WTHGIS_COUNTIES below.

Marion SC (DSID=1064, also on this platform, also live-reachable, also returns real
getftr.aspx data per ingest_chesterfield_wthgis.py's own note) was NOT added: its
ESTATE/HEIR search hits were live-confirmed to exist (48/0 raw hits) but were not run
through the same classifier-sampling verification this module requires before
trusting a county's data -- and that script's note that 0/280 of Marion's EXISTING
board rows carry a parcel_id (irrelevant to a from-scratch producer like this one,
which never binds to an existing row) was about a DIFFERENT, patch-style use of the
same platform. Left for a future round to verify the same way Chesterfield was here,
not added speculatively. Dillon/McCormick (same platform family, live-reachable at
the correct /tgis/default.aspx entry point -- the earlier "generic 404" note was
against the wrong path, ArcGIS REST discovery URLs this legacy ASP.NET app never
serves) and Edgefield (qpublic.net, a different, non-Cloudflare-walled host from the
Schneider qpublic.schneidercorp.com elsewhere) are reachable but their DSID / search
form were not located this round -- see project_lt_estate_lead_round18_2026-11-17.md.
Cherokee/Clarendon/Bamberg/Abbeville/Allendale/Lee/Fairfield (7 of the 12 cells) are
confirmed real Cloudflare/WAF walls on qpublic.schneidercorp.com or
beacon.schneidercorp.com -- a genuine capability gap, not attempted here or anywhere.

Politeness: same as the sibling ingest script -- a small county-run legacy ASP.NET
box, not a CDN. Low concurrency, generous timeout, bounded retries.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Iterable, Optional

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ..counties_nc.nc_heir_estate_parcels import (
    _excluded_row,
    _heir_names,
    _is_decedent,
    _is_life_estate,
    _HEIR_TOKEN,
)

log = structlog.get_logger()

#: county -> its WTH "tgis" dataset id. Only counties individually live-verified
#: (search index returns real, classifier-passing owner data -- see module docstring)
#: are listed; a platform sibling being reachable is not enough on its own.
_WTHGIS_COUNTIES: dict[str, dict] = {
    "Chesterfield": {"dsid": 6796, "base": "https://chesterfieldsc.wthgis.com/tgis/"},
}

#: Decedent-indicating substrings searched directly against the WTH owner-name
#: index (a plain substring match, not a last-name-only search -- live-confirmed).
#: Deliberately the same vocabulary nc_heir_estate_parcels.py's own
#: _ESTATE_TOKEN/_HEIR_TOKEN test for, kept in sync by hand since one is a live
#: search string and the others are compiled regexes over already-fetched text.
_SEARCH_TOKENS = ("ESTATE", "HEIR")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) HighWayResearch/1.0 (+parcel-cache build)"
CONCURRENCY = 4
TIMEOUT_S = 20.0
RETRIES = 3

_FIELD_RE_CACHE: dict[str, re.Pattern] = {}


def _field(txt: str, name: str) -> str:
    """Pull one getftr.aspx detail-table cell by its `<th>` label (shared regex
    shape with the sibling ingest_chesterfield_wthgis.py; not imported from there
    because that script is a one-off CLI tool, not a package module)."""
    pat = _FIELD_RE_CACHE.get(name)
    if pat is None:
        pat = _FIELD_RE_CACHE[name] = re.compile(re.escape(name) + r"</th><td[^>]*>([^<]*)</td>")
    m = pat.search(txt)
    return m.group(1).strip() if m else ""


def _parse_search_hits(txt: str) -> dict[str, int]:
    """Map Number -> FeatureID for every result row a search page returned."""
    out: dict[str, int] = {}
    for m in re.finditer(r"showf\(\s*\d+\s*,\s*(\d+)\s*\).*?mainResultItem'>([^<]+)<", txt, re.S):
        fid, mapno = m.group(1), m.group(2).strip()
        if mapno:
            out[mapno] = int(fid)
    return out


def _parse_detail(txt: str) -> Optional[dict]:
    """The subset of getftr.aspx's detail fields this producer needs, or None if
    the page carries no Map Number at all (a dead FeatureID)."""
    mapno = _field(txt, "Map&nbsp;Number")
    if not mapno:
        return None
    return {
        "map_number": mapno,
        "owner": _field(txt, "Owner&nbsp;Name"),
        "owner2": _field(txt, "Owner&nbsp;Name2"),
        "address": _field(txt, "Property&nbsp;Address1"),
        "mailing": " ".join(
            p for p in (
                _field(txt, "Mailing&nbsp;Address1"), _field(txt, "Mailing&nbsp;Address2"),
                _field(txt, "Mailing&nbsp;City"), _field(txt, "Mailing&nbsp;State"),
                _field(txt, "Mailing&nbsp;ZipCode"),
            ) if p
        ) or None,
        "market_value": _num(_field(txt, "MarketValueTotalValue")),
        "tax_value": _num(_field(txt, "TaxValueTotalValue")),
        "acreage": _num(_field(txt, "MarketValueAcres")),
    }


def _num(s: str) -> Optional[float]:
    try:
        v = float(str(s).strip())
    except (TypeError, ValueError):
        return None
    return v if v != 0 else None


async def _get(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> Optional[str]:
    async with sem:
        for attempt in range(RETRIES):
            try:
                r = await client.get(url, timeout=TIMEOUT_S)
                if r.status_code == 200:
                    return r.text
            except (httpx.TimeoutException, httpx.TransportError):
                pass
            if attempt < RETRIES - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
        return None


def _classify(rec: dict) -> Optional[dict]:
    """Returns the dict sc_heir_estate_parcel_cache.py-style raw/description info
    for a real hit, or None if `rec`'s owner fields are noise/excluded."""
    owner = (rec.get("owner") or "").strip()
    if not owner:
        return None
    owner_fields = [owner, rec.get("owner2") or ""]
    is_life_estate = _is_life_estate(owner_fields)
    if not is_life_estate and (not _is_decedent(owner_fields) or _excluded_row(owner_fields)):
        return None
    return {
        "owner": owner,
        "is_life_estate": is_life_estate,
        "match": ("life_estate" if is_life_estate else
                   "heirs" if _HEIR_TOKEN.search(owner) else "estate"),
        "heir_names": _heir_names(owner_fields),
    }


class SCWthgisHeirEstate(BaseScraper):
    slug = "counties_sc.sc_wthgis_heir_estate"
    name = "SC Heir / Estate / Life-Estate Owner-of-Record (WTH tgis live GIS)"
    category = "motivated_seller"
    expected_min_count = 1
    # Live network across a small per-county ASP.NET box (not a CDN): a two-phase
    # search-then-detail sweep. Chesterfield alone needs ~605 detail fetches --
    # live-measured 2026-11-17: a 900s budget only reached 536/605 (this session's
    # own earlier interactive probing of the same host likely cost it some of that
    # headroom), salvaging 513 real classified rows via the incremental append
    # below rather than losing the whole run (BaseScraper.partial's documented
    # contract). Raised for a cleaner single-pass landing run next time.
    timeout_s = 1500.0
    requires_apify = False
    optional = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.run_stats: dict = {"counties": 0, "search_hits": 0, "detail_fetched": 0, "kept": 0}

    async def fetch(self) -> Iterable[Listing]:
        out = self.partial
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(headers={"User-Agent": UA}) as client:
            for county, cfg in _WTHGIS_COUNTIES.items():
                dsid, base = cfg["dsid"], cfg["base"]
                search_urls = [
                    base + f"custom.aspx?DSID={dsid}&RequestType=CustomSearchRequest"
                            f"&SearchType=Name&SearchCriteria={tok}%7C"
                    for tok in _SEARCH_TOKENS
                ]
                texts = await asyncio.gather(*(_get(client, u, sem) for u in search_urls))
                hits: dict[str, int] = {}
                for txt in texts:
                    if txt:
                        hits.update(_parse_search_hits(txt))
                if not hits:
                    log.warning("sc_wthgis_heir_estate.no_hits", county=county)
                    continue
                self.run_stats["search_hits"] += len(hits)

                # Detail-fetch + classify + emit in CHUNKS (not one giant gather() over
                # every FeatureID): a county-wide sweep can be hundreds of requests, and
                # BaseScraper.partial's own contract is that a scraper appending as it
                # goes ships that work if the soft timeout fires mid-run. One atomic
                # gather() of everything would lose ALL of it on a timeout instead --
                # live-measured 2026-11-17: Chesterfield's 605 hits did not finish
                # detail-fetching inside a 300s budget, and a non-incremental version
                # of this loop shipped zero rows despite real, classifiable data already
                # fetched. Chunk size matches CONCURRENCY so each chunk is one wave of
                # in-flight requests, not a second semaphore layer.
                self.run_stats["counties"] += 1
                kept = 0
                now = datetime.now(timezone.utc)
                items = list(hits.items())
                for i in range(0, len(items), CONCURRENCY):
                    chunk = items[i:i + CONCURRENCY]
                    urls = [base + f"getftr.aspx?D={dsid}&F={fid}&Z=1" for _, fid in chunk]
                    texts = await asyncio.gather(*(_get(client, u, sem) for u in urls))
                    for (mapno, _fid), txt in zip(chunk, texts):
                        if not txt:
                            continue
                        rec = _parse_detail(txt)
                        if not rec:
                            continue
                        self.run_stats["detail_fetched"] += 1
                        cls = _classify(rec)
                        if not cls:
                            continue
                        li = Listing(
                        source=self.slug,
                        source_url=base + f"getftr.aspx?D={dsid}&F={_fid}&Z=1",
                        acreage=rec.get("acreage"),
                        market_value=rec.get("market_value"),
                        tax_value=rec.get("tax_value"),
                        listing_type=ListingType.ESTATE_LEAD,
                        property_kind=PropertyKind.UNKNOWN,
                        state="SC",
                        county=county,
                        street_address=rec.get("address") or None,
                        parcel_id=mapno,
                        defendant=cls["owner"],
                        description=(
                            f"Life estate owner of record ({cls['owner']}) in {county} County, SC"
                            if cls["is_life_estate"] else
                            f"Heir/estate owner of record ({cls['owner']}) in {county} County, SC"
                        ),
                        first_seen=now,
                        last_seen=now,
                        raw={
                            "heir_estate": {
                                "owner_of_record": cls["owner"],
                                "heir_names": cls["heir_names"],
                                "mailing": rec.get("mailing"),
                                "match": cls["match"],
                                "life_estate": cls["is_life_estate"],
                                "source": "wthgis_live",
                            },
                            "relationship_signal": {
                                "kind": "life_estate" if cls["is_life_estate"] else "probate",
                                "keyword": ("life_estate_owner_of_record" if cls["is_life_estate"]
                                            else "heir_estate_owner_of_record"),
                                "source": self.slug,
                            },
                            **({"life_events": ["life_estate"]} if cls["is_life_estate"] else {}),
                        },
                        )
                        out.append(li)
                        kept += 1
                self.run_stats["kept"] += kept
                log.info("sc_wthgis_heir_estate.county", county=county,
                         search_hits=len(hits), kept=kept)
        log.info("sc_wthgis_heir_estate.done", listings=len(out), **self.run_stats)
        return out


if __name__ == "__main__":
    async def _main() -> None:
        s = SCWthgisHeirEstate()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)} stats={s.run_stats}")
        for li in rows[:12]:
            print(f"  {li.county:12} {(li.defendant or '')[:40]:40} parcel={li.parcel_id}")

    asyncio.run(_main())
