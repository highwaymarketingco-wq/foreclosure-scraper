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
getftr.aspx data per ingest_chesterfield_wthgis.py's own note) was NOT added in round
18: its ESTATE/HEIR search hits were live-confirmed to exist (48/0 raw hits) but were
not run through the same classifier-sampling verification this module requires before
trusting a county's data. Cherokee/Clarendon/Bamberg/Abbeville/Allendale/Lee/Fairfield
(7 of the 12 cells) are confirmed real Cloudflare/WAF walls on qpublic.schneidercorp.com
or beacon.schneidercorp.com -- a genuine capability gap, not attempted here or anywhere.

ROUND 19 (2026-11-17) closed 3 of the remaining 4 open cells -- Dillon, McCormick,
Marion -- and resolved Edgefield as a real wall (declined in declined_registry.json,
not this module's concern; see project_lt_estate_lead_round19_2026-11-17.md for the
full writeup).

DSID DISCOVERY FIX: round 18's own note said the Chesterfield-style "Parcel Tools
Menu" JS (the only place a DSID is visible without a headful browser) is "apparently
rendered only through live, interactive use of the viewer ... not visible in a single
static GET" and left Dillon/McCormick's DSIDs unresolved on that belief. FALSE --
live-reprobed 2026-11-17: that JS IS present on a single static GET, but only of the
bare subdomain ROOT (e.g. `https://dillonsc.wthgis.com/`, content-type text/html,
"<title>Dillon County, SC Map</title>"), not of `/tgis/default.aspx` (the near-empty
VIEWSTATE-only shell round 18 tested, which is a DIFFERENT, legacy page on the same
app that never carries this inline script). The root page's own
`addMenuItem(...,"fetchOverlay('tgis/custom.aspx?DSID=<N>&...')")` line gives the
DSID directly: Dillon=1042, McCormick=46 (also independently cross-checked against
each root page's own `g_hoverDss` JS variable, which matches). Same method
re-confirmed Marion's already-known DSID=1064 via its own root page's `g_hoverDss`.

LIVE-VERIFIED 2026-11-17 (same read-only GET pattern, same UA, same two search
tokens):
  - Dillon (DSID=1042, base https://dillonsc.wthgis.com/tgis/): 73 raw ESTATE hits
    (0 HEIR). Schema IDENTICAL to Chesterfield's getftr.aspx (Map&nbsp;Number,
    Owner&nbsp;Name/2, Property&nbsp;Address1, Mailing&nbsp;*, MarketValueTotalValue,
    TaxValueTotalValue, MarketValueAcres -- field-for-field, live-diffed against a
    real detail page). A 24-point spread sample through the real classifiers below
    scored 7/24 real (6 _is_decedent "...Estate"/"...Estate Etal" owners never
    life-estate-flavored here, 0 life_estate, 0 heirs) and 17/24 correctly
    _excluded_row (overwhelmingly one repeat-investor business name, "H&K Real
    Estate Holdings LLC", across many parcels -- the "ESTATE" search substring
    matches "Real Estate" business names too, exactly the same noise shape
    Chesterfield's own 1/24 "Walters Real Estate and..." sample hit, just more of
    it here). 0/24 misclassified either direction.
  - McCormick (DSID=46, base https://mccormicksc.wthgis.com/tgis/): 174 ESTATE + 1
    HEIR = 175 raw hits. Same Chesterfield-identical schema (live-diffed the same
    way). A 24-point spread sample scored 24/24 real (20 life_estate, 4 estate),
    0/24 excluded, 0/24 misclassified -- the cleanest signal of any county this
    project has tested on this platform, Chesterfield included.
  - Marion (DSID=1064, base https://marionsc.wthgis.com/tgis/): 48 raw hits (all
    ESTATE; 0 HEIR, matching round 18's own "48/0" live probe exactly once this
    round's search-parsing fix below is applied). Round 18's hesitation is now
    resolved: ALL 48 (not a sample -- the county is small enough to check
    exhaustively) were detail-fetched and run through the SAME unmodified
    classifiers. Real signal exists (7/48: 6 _is_decedent "...Estate" owners, 1
    life_estate, 0 heirs) but the search token is far noisier here than on any
    other county tested -- 41/48 are investor/business names ("... REAL ESTATE
    LLC/CO/INVESTMENT/MANAGEMENT/SERVICES", several repeats of the same corporate
    owner across many parcels) that _excluded_row correctly drops, 0/48
    misclassified. Genuinely real, if thin (7 rows, matching this cell's own
    est_rows_affected=6 almost exactly) -- built anyway, same bar Chesterfield and
    the other two counties were held to (confirmed real signal + 0% misclassification,
    not a specific hit-rate floor).

TWO PLATFORM-LEVEL FIXES this round's live verification forced, both backward
compatible with every county already enabled (Chesterfield/Dillon/McCormick all
re-verified unaffected by either change):

  1. Marion's getftr.aspx uses a COMPLETELY different `<th>` label set than every
     other county on this platform -- "TMS&nbsp;Number" not "Map&nbsp;Number",
     "Owner&nbsp;Name1" not "Owner&nbsp;Name" (owner2 label is the same), "Description"
     (a plain situs address, confirmed live: "405 CHARLESTON ST") doing the job
     "Property&nbsp;Address1" does elsewhere, and NO MarketValueTotalValue /
     TaxValueTotalValue / MarketValueAcres / Mailing&nbsp;* fields of any kind (this
     county's schema has "Land&nbsp;Value"/"Building&nbsp;Value" split cells instead,
     already flagged as a different schema by round 17's own "Total&nbsp;cres [sic]"
     note -- not summed into a fabricated total here, left genuinely None rather than
     invent a derived field this project has never used elsewhere). `_DEFAULT_FIELDS`
     below is the Chesterfield-identical label set every other county uses as-is;
     `_parse_detail()` now takes an optional per-county `fields` override dict
     (Marion's `_WTHGIS_COUNTIES` entry sets one, Chesterfield/Dillon/McCormick don't
     need to) instead of the field labels being hard-coded. This is a schema
     adapter, not new classification logic -- `_classify()` itself, and every
     function it calls, is untouched.
  2. Marion's search-result markup leaves `mainResultItem` EMPTY and puts the real
     Map/TMS Number in a sibling `secondaryResultItem` div instead (live-diffed:
     `...showf(1064 , 538)'></div>...<div id=resultsParcelNumber class='mainResult
     Item'></div><div class='secondaryResultItem'>5081223000000</div>...` -- this is
     why round 18's own "48/0" Marion probe never got its map numbers out even
     though the search itself already worked). `_parse_search_hits()`'s regex now
     accepts EITHER class name, preferring `mainResultItem` when it has real content
     (every other county's own shape, unchanged) and falling back to
     `secondaryResultItem` only when `mainResultItem` is empty -- live-reverified
     this produces IDENTICAL hit counts/map-numbers for Chesterfield/Dillon/McCormick
     to the original single-class regex (their `mainResultItem` is always populated),
     so no existing county's behavior changed.

Dillon/McCormick (same platform family) and Edgefield (qpublic.net, a different,
non-Cloudflare-walled host from the Schneider qpublic.schneidercorp.com elsewhere)
were reachable per round 18 but their DSID / search form were not located that round
-- Dillon/McCormick resolved above. Edgefield's resolution belongs to
declined_registry.json, not this module: the county's OWN site (both
edgefieldcounty.sc.gov and the qpublic.net/sc/edgefield/ assessor microsite it also
links) has exactly ONE owner/property search tool, reached via a "Search Records"
link to `qpublic.schneidercorp.com/Application.aspx?AppID=859&LayerID=16089&
PageTypeID=2&PageID=7160` -- live-confirmed 2026-11-17 to answer that exact URL with
the SAME Cloudflare "Just a moment..." 403 bot-check as the 7 already-declined
qpublic.schneidercorp.com counties. Not a different, unwalled tool as round 18's
more cautious "reachable, not explored further" note left open -- the qpublic.net
landing page round 18 tested is just a static front door to the walled host.

RUN-SCOPE: `SCWthgisHeirEstate(counties=[...])` restricts a single run to a subset
of `_WTHGIS_COUNTIES` (e.g. just the 3 counties this round added) so a landing run
does not have to pay Chesterfield's own ~600-hit cost (and produce nothing but
already-landed duplicates) every time; omitting it sweeps every enabled county, the
only mode that existed before this round.

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
#: are listed; a platform sibling being reachable is not enough on its own. A county
#: whose getftr.aspx uses different <th> labels sets its own "fields" override (see
#: _DEFAULT_FIELDS); every county below but Marion matches the default exactly.
_WTHGIS_COUNTIES: dict[str, dict] = {
    "Chesterfield": {"dsid": 6796, "base": "https://chesterfieldsc.wthgis.com/tgis/"},
    "Dillon": {"dsid": 1042, "base": "https://dillonsc.wthgis.com/tgis/"},
    "McCormick": {"dsid": 46, "base": "https://mccormicksc.wthgis.com/tgis/"},
    "Marion": {
        "dsid": 1064,
        "base": "https://marionsc.wthgis.com/tgis/",
        "fields": {
            "map_number": "TMS&nbsp;Number",
            "owner": "Owner&nbsp;Name1",
            "address": "Description",
            "mailing_address1": None,
            "mailing_address2": None,
            "mailing_city": None,
            "mailing_state": None,
            "mailing_zip": None,
            "market_value": None,
            "tax_value": None,
            "acreage": None,
        },
    },
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


#: Default WTH getftr.aspx <th> label schema -- Chesterfield/Dillon/McCormick all
#: match this exactly (live-diffed 2026-11-17/18). A county whose deployment uses
#: different labels (Marion -- round 19) overrides only the keys that differ via
#: its own `_WTHGIS_COUNTIES[...]["fields"]`; a value of None means that county's
#: schema has no matching cell at all for that key (left as a genuine None, not a
#: parsing miss -- every caller already treats None as "no data", same as _num()
#: already does for a 0/missing value).
_DEFAULT_FIELDS: dict[str, Optional[str]] = {
    "map_number": "Map&nbsp;Number",
    "owner": "Owner&nbsp;Name",
    "owner2": "Owner&nbsp;Name2",
    "address": "Property&nbsp;Address1",
    "mailing_address1": "Mailing&nbsp;Address1",
    "mailing_address2": "Mailing&nbsp;Address2",
    "mailing_city": "Mailing&nbsp;City",
    "mailing_state": "Mailing&nbsp;State",
    "mailing_zip": "Mailing&nbsp;ZipCode",
    "market_value": "MarketValueTotalValue",
    "tax_value": "TaxValueTotalValue",
    "acreage": "MarketValueAcres",
}


def _parse_search_hits(txt: str) -> dict[str, int]:
    """Map Number -> FeatureID for every result row a search page returned.

    Prefers the `mainResultItem` div (every county's shape except Marion); when
    that div is empty, falls back to the sibling `secondaryResultItem` div
    (Marion's own shape -- live-diffed 2026-11-17: its `mainResultItem` renders
    with no text at all, and the real Map/TMS Number appears in `secondaryResult
    Item` instead). `[^<]+` requires at least one character, so an empty
    `mainResultItem` never matches and the alternation falls through to the next
    candidate -- live-reverified this produces IDENTICAL output to the original
    mainResultItem-only pattern for every county whose div is populated.
    """
    out: dict[str, int] = {}
    pat = r"showf\(\s*\d+\s*,\s*(\d+)\s*\).*?(?:mainResultItem|secondaryResultItem)'>([^<]+)<"
    for m in re.finditer(pat, txt, re.S):
        fid, mapno = m.group(1), m.group(2).strip()
        if mapno:
            out[mapno] = int(fid)
    return out


def _parse_detail(txt: str, fields: Optional[dict] = None) -> Optional[dict]:
    """The subset of getftr.aspx's detail fields this producer needs, or None if
    the page carries no Map/TMS Number at all (a dead FeatureID). `fields`
    overrides `_DEFAULT_FIELDS` per-key for a county whose <th> labels differ
    (see _WTHGIS_COUNTIES); omitted entirely, every caller gets the original
    Chesterfield-shape behavior unchanged."""
    f = dict(_DEFAULT_FIELDS)
    if fields:
        f.update(fields)
    mapno = _field(txt, f["map_number"]) if f.get("map_number") else ""
    if not mapno:
        return None
    mailing = " ".join(
        p for p in (
            _field(txt, f[k]) if f.get(k) else ""
            for k in ("mailing_address1", "mailing_address2", "mailing_city",
                      "mailing_state", "mailing_zip")
        ) if p
    ) or None
    return {
        "map_number": mapno,
        "owner": _field(txt, f["owner"]) if f.get("owner") else "",
        "owner2": _field(txt, f["owner2"]) if f.get("owner2") else "",
        "address": (_field(txt, f["address"]) if f.get("address") else "") or None,
        "mailing": mailing,
        "market_value": _num(_field(txt, f["market_value"])) if f.get("market_value") else None,
        "tax_value": _num(_field(txt, f["tax_value"])) if f.get("tax_value") else None,
        "acreage": _num(_field(txt, f["acreage"])) if f.get("acreage") else None,
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
    # contract). Round 19 (2026-11-17) added Dillon/McCormick/Marion (73+175+48=296
    # more raw hits, ~0.67 hits/sec detail-fetch pace measured round 18) -- a full
    # sweep of all 4 counties now needs on the order of 1350s of detail-fetching
    # alone; raised to 2100s (vs. round 18's 1500s) for comfortable single-pass
    # headroom on a FULL sweep. A landing run that only needs the 3 new counties
    # should pass `counties=[...]` (see __init__) rather than relying on this
    # timeout to cover Chesterfield's own already-landed 605 hits for nothing.
    timeout_s = 2100.0
    requires_apify = False
    optional = True

    def __init__(self, *a, counties: Optional[Iterable[str]] = None, **kw):
        super().__init__(*a, **kw)
        self.run_stats: dict = {"counties": 0, "search_hits": 0, "detail_fetched": 0, "kept": 0}
        # Restrict this run to a subset of _WTHGIS_COUNTIES (e.g. just the counties
        # a given round added) instead of always re-sweeping every enabled county --
        # added round 19 so a landing run for Dillon/McCormick/Marion does not also
        # pay Chesterfield's own ~600-hit cost to produce nothing but duplicates of
        # rows round 18 already landed. None (the only mode that existed before
        # this round) sweeps everything in _WTHGIS_COUNTIES.
        if counties is None:
            self._counties = dict(_WTHGIS_COUNTIES)
        else:
            unknown = set(counties) - set(_WTHGIS_COUNTIES)
            if unknown:
                raise ValueError(f"not in _WTHGIS_COUNTIES: {sorted(unknown)}")
            self._counties = {c: _WTHGIS_COUNTIES[c] for c in counties}

    async def fetch(self) -> Iterable[Listing]:
        out = self.partial
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(headers={"User-Agent": UA}) as client:
            for county, cfg in self._counties.items():
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
                        rec = _parse_detail(txt, cfg.get("fields"))
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
