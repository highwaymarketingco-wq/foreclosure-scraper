"""Generate the static-site JSON files consumed by docs/index.html (the live dashboard).

Writes:
  docs/listings.json   — array of sanitized listings (Pydantic-dumped, raw kept slim)
  docs/run_meta.json   — run timestamp, source_status, totals, sources contributing
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import structlog

from .models import Listing
from .stale_link_fallback import annotate_stale_links

log = structlog.get_logger()


def load_board(docs_dir: Path | str = "docs") -> list[Listing]:
    """Load the published board as Listing objects WITH the lazy-detail sidecar
    merged back into each lead's raw.

    listings.json is slim (the heavy comps/vision keys live in the index-aligned
    listings_detail.json). Any incremental board-writer that reads listings.json
    directly and re-runs write_artifact would drop that detail — the sidecar gets
    rebuilt from raw, which no longer has those keys. Loading through this helper
    merges detail[i] back into listing[i].raw first, so the round-trip preserves
    it. Always use this instead of a hand-rolled json.loads loop in a board pass.
    """
    docs = Path(docs_dir)
    records = json.loads((docs / "listings.json").read_text())
    detail_path = docs / "listings_detail.json"
    details: list = []
    if detail_path.exists():
        try:
            details = json.loads(detail_path.read_text())
        except Exception:  # noqa: BLE001
            details = []
    out: list[Listing] = []
    for i, rec in enumerate(records):
        if i < len(details) and isinstance(details[i], dict) and details[i]:
            raw = rec.get("raw")
            if isinstance(raw, dict):
                raw.update(details[i])
        try:
            out.append(Listing.model_validate(rec))
        except Exception:  # noqa: BLE001
            pass
    return out


# Whitelist of `raw` sub-keys to keep in the output (keep file small + privacy-OK)
RAW_KEEP = {
    "gis": ("owner", "mailing", "last_sale"),
    "zillow": ("zpid", "homeType", "zestimate", "yearBuilt", "bedrooms", "bathrooms",
               "livingArea", "lotSize", "taxAssessedValue", "description", "photo", "photos"),
    "flags": "*",
    "assessment": "*",
    "calc": "*",      # ARV / rehab / max_bid / ROI / cash-on-cash
    "amount_owed": "*",  # cross-sourced debt figure {value, source, label, confidence, is_actual_debt}
    "equity": "*",       # owner equity = ARV − payoff − senior liens {value, pct, payoff_source, ...}
    "liens": "*",        # joined lien stack (state tax liens etc.) [{type, amount, source, super_priority}]
    "skip_trace": "*",   # owner name / mailing address / phone for outreach (free)
    "is_new": "*",       # new-this-run flag (early-access highlight)
    "first_seen_run": "*",
    "outreach": "*",     # owner contact + letter/email/sms drafts + channels
    "crm": "*",          # lead status + notes (persisted across runs)
    "grade": "*",     # A-F per-dimension + overall
    "location": ("median_household_income", "median_home_value",
                 "owner_occupied_pct", "unemployment_pct"),
    "comps": "*",                     # 3 sold comps per listing (HomeHarvest)
    "rent_comps": "*",                # 3 rent comps per listing (HomeHarvest)
    "comps_note": "*",                # explanation when no like-for-like found
    "comp_median_ppsf": "*",
    "market_velocity": "*",           # months-of-inventory + holding-period estimate
    "recorded_comps": "*",            # county-GIS recorded arms-length sales (median $/sqft, Tier-0 ARV)
    "comp_median_ppsf_recorded": "*",
    "condition_tier": "*",            # move_in_ready / cosmetic / major / gut
    "condition_source": "*",          # "vision-HIGH" / "vision-MEDIUM" / regex/age default
    "vision": "*",                    # full Claude Vision condition report
    "doc_ocr": "*",                   # OCR of scanned legal-notice/deed docs: owner+address+debt$
    "nc_ptscloud_delinquent_tax": "*",
    "lrcpwa": "*",                       # land-records parcel resolve: assessed/mailing/absentee   # PTS delinquent roll: parcel/assessed/mailing/tax_year (skip-trace)
    "nc_county_pdf_delinquent_tax": "*", # county PDF delinquent roll: county_id/owner provenance
    "rent_median_ppsf": "*",
    "estimated_monthly_rent": "*",
    "data_quality": "*",              # investor-facing caveats: synthetic_address / no_sqft / low_arv_confidence
    "parcel_resolution": "*",         # parcel + centroid reverse-geo (Cleveland NC / Cherokee SC fallback)
    "lis_pendens_resolution": "*",    # SC lis-pendens GIS resolver provenance
    "rod_docs": "*",                  # ROD recorded documents (deeds, mortgages, satisfactions)
    "lien_priority": "*",             # senior/junior liens + super-priority warnings
    "propwire": "*",                  # equity, owner, last sale (when present)
    "loopnet": "*",                   # multifamily-specific cap rate, units, etc.
    "reac": "*",                      # HUD REAC inspection scores {latest_score, scores[], distressed}
    "images": "*",                    # {primary, map, street} fallback image map
    "flood": "*",                     # FEMA flood-zone tag {zone, in_sfha, ...}
    "nod": "*",                       # ROD-discovered Notice of Default
    "bankruptcy": "*",                # CourtListener bankruptcy match on defendant name
    "courtlistener": "*",             # raw bankruptcy docket data when emitted as a listing
    "distressed": "*",                # HomeHarvest distressed-keyword matches
    "epa": "*",                       # EPA ECHO environmental hazards
    "crime": "*",                     # FBI UCR / per-zip crime stats
    "fema_repetitive_loss": "*",      # NFIP multiple-loss properties (much stronger than flood zone alone)
    "code_enforcement": "*",          # City open code violations (Charlotte 311 etc.)
    "sc_tax_delinquent": "*",         # SC delinquent tax / pre-tax-sale tag
    "building_permits": "*",          # recent permits = positive, stale open = negative
    "bid4assets": "*",                # auction-site raw payload
    "sos_status": "*",                # NC SOS LLC dissolution status (when defendant is LLC)
    "sos_agent": "*",                 # NC SOS registered agent + officers = free entity-owner contact
    "rent_comps_extra": "*",          # broader rent comp pool when strict was empty
    "rent_median_ppsf_extra": "*",
    "estimated_monthly_rent_extra": "*",
    "schools": "*",                   # GreatSchools per-address ratings (when key set)
    "walk_score": "*",                # Walk Score per-address (when key set)
    "nc_ecourts": "*",                # NC Tyler Odyssey judgment-search row
    "upset_bid": "*",                 # NCGS §45-21.27 10-day upset-bid window
    "nc_case_status": "*",            # NC eCourts case status (pending/sold/upset)
    "court_documents": "*",           # Tyler RegisterOfActions sale paper trail [{type,date,available}]
    "court_balance_due": "*",         # live court-derived debt (judgment + accrued interest)
    "court_balance_due_as_of": "*",
    "court_record_url": "*",          # deep link to the Tyler case page
    "court_sale_status": "*",         # confirmed / sold_unconfirmed / sale_noticed / judgment
    "sold_confirmed": "*",            # court-confirmed sale → already sold, filter off active board
    "owner_mailing": "*",             # #0 contactability: owner name + mailing addr + absentee/out-of-state flags
    "owner_phone": "*",               # NC voter-file phone (name+address match) — DNC-gated, needs_dnc_scrub
    "rod": "*",                       # Gaston NC ROD lien existence (D/T mortgage + adverse liens) by owner name
    "divorce": "*",                   # SC Family-Court divorce / marital-dissolution match on owner party-name (FCCMS)
    "geo_imprecise": "*",             # out_of_bbox (geo nulled) | centroid_snap (county/town-center fallback)
    "stale_case": "*",                # presumed_withdrawn lis-pendens — likely resolved, down-ranked from HOT
    "life_events": "*",               # elderly/probate signals: life_estate | estate_probate | multiple_heirs | trust
    "gis_exempt": "*",                # statutory tax-relief exemption (ELD/DIS/BLD/VET) -> hard elderly/disabled signal
    "owner_name_source": "*",         # provenance when owner_name was promoted from tax/GIS
    "notice_contact": "*",            # attributable attorney/trustee email from the legal-notice body
    "incarceration": "*",             # owner matched a state corrections roster (NC DAC) — low-conf stack signal
    "distress_stack": "*",
    "strategy_fit": "*",
    "eviction_market": "*",           # LSC county eviction-pressure market signal (context)
    "cama": "*",                      # county CAMA distress (condition/last-sale/deed-ref/owner-occupancy)
    "footprint": "*",                 # footprint-derived sqft ESTIMATE (area/stories/match) — transparency for estimated living_sqft
    "relationship_signal": "*",       # probate / divorce / partition deed signal
    "refresh_misses": "*",            # daily-refresh consecutive-absence counter (drop after N)
    "last_refresh_seen": "*",         # date a refreshed source last confirmed this listing in inventory
    "carryover": "*",                 # Last-known-good replay marker
    "filed_date": "*",                # Generic file-date for lis pendens / liens
    "county_pin": "*",                # Case#-encoded venue county correction
    "geo_attribution": "*",           # 'state-only' marker for unattributed BK listings
    "foreclosure_sold_comps": "*",    # Per-listing like-for-like recently-sold foreclosure comps
    "foreclosure_sold_comp_summary": "*",  # County-level sold-comp rollup
    "actual_sold_price": "*",         # Real hammer price (Pickens MIE results PDFs etc.)
    "pickens_mie": "*",               # Pickens MIE results PDF parse provenance
    "anderson_mie_results": "*",      # Anderson MIE Sale-Results parse provenance
    "spartanburg_pdf": "*",           # Spartanburg MIE PDF parse provenance (now includes is_results_pdf)
    "assessor_card": "*",             # on-demand per-parcel card: recorded sale price + history + sqft source
    "pulled_sale": "*",               # cross-run withdrawn/pulled-sale aging counter
    "comps_geo_warning": "*",         # low-confidence ARV note (comps out of geo radius)
    "link_check": "*",                # link-validator reachability tag {status, http}
    "fallback_links": "*",            # reliable backups for stale aggregator links {google, maps, parcel_gis}
    "link_may_be_stale": "*",         # True for old/carryover aggregator leads (operator "verify link" hint)
    "fhfa_value": "*",                # FHFA HPI-adjusted value estimate {value, source, ...}
    "title_risk": "*",                # title-defect / cloud-on-title risk assessment
    "zls": "*",                       # ZLS status field
    "qa_flags": "*",                  # automated data-quality flags (dup_address, arv_below_asis, etc.)
    "last_sale": "*",                 # display-ready last sale {date, amount, basis, source} for the dashboard
    "also_seen_in": "*",              # every other source + link this property was seen at (kept on merge)
    "corroboration": "*",             # court-confirmed vs single-source-aggregator flag {court_confirmed, tier, sources, label}
    "signal_stack": "*",              # list-stacking: {count, signals[]} distinct distress signals per property
    "intent_score": "*",              # normalized 0-100 seller-intent score
    "intent_band": "*",               # hot/warm/cool/cold band
    "condition_cama": "*",            # CAMA per-parcel condition/grade/year_built
    "storm_damage": "*",              # Hurricane Helene damage-assessment match {damage_level, estimated_loss, ...}
    "condemned": "*",                 # condemned/dilapidated flag from county condemned inventory
    "owner_mismatch": "*",            # court lead whose geo-snapped property was stripped (name-only, unverified)
    "resolved_from_name": "*",        # name->property resolver provenance {county, strategy, confidence}
    "_resolved_deep_enriched": "*",   # marker: resolved lead already got the same-run comps/Vision catch-up
    "tax_owed": "*",                  # normalized delinquent-tax balance {balance, kind, source, year, basis}
    "tenure": "*",                    # owner tenure {years_held, long_tenure} — high-equity proxy
    "contact": "*",                   # ingested skip-trace contact {phones, emails, mailing, needs_dnc_scrub}
    "link_kind": "*",                 # 'record' (real per-record link) | 'search' (portal only)
    "search_url": "*",                # portal search page when there's no direct record link
}


# Court-doc / lien / placeholder markers that scrapers sometimes drop into
# street_address when no real parcel address was resolved. These are NOT
# properties and must not render on the dashboard/map as one.
_INVALID_ADDR_MARKERS = (
    "lis pendens",
    "claim of lien",
    "notice to",
    "tract",
    "property in",
)

# A real street address starts with a house number ("123 Main St") or is a
# recognized rural form: a state/secondary road designator (SR 1135, US 221 N,
# NC 12, Hwy 9), a "Lot N" form, or a named road with a street-type suffix
# (e.g. "Riverfork Road", "Antreville Highway"). Anything else that matches an
# invalid marker (or is empty) is treated as junk.
_HOUSE_NUM_RE = re.compile(r"^\d+\s+\S")
_RURAL_DESIGNATOR_RE = re.compile(
    r"^(?:sr|us|nc|sc|hwy|highway|county\s+road|cr|state\s+road|lot)\b",
    re.IGNORECASE,
)
_ROAD_SUFFIX_RE = re.compile(
    r"\b(?:road|rd|street|st|drive|dr|highway|hwy|lane|ln|court|ct|avenue|ave|"
    r"boulevard|blvd|circle|cir|way|place|pl|trail|trl|pike|loop|run|path|"
    r"terrace|ter|parkway|pkwy|cove|point|pointe|ridge|creek|branch|crossing|"
    r"bend|pass|row|alley)\b",
    re.IGNORECASE,
)


def _is_valid_street_address(addr: str | None) -> bool:
    """True if `addr` looks like a real street address (house number or a
    recognized rural road form), False for court-doc/lien placeholders and
    empties. Defensive: bad input -> False, never raises."""
    if not isinstance(addr, str):
        return False
    s = addr.strip()
    if not s:
        return False
    low = s.lower()
    if any(m in low for m in _INVALID_ADDR_MARKERS):
        return False
    if _HOUSE_NUM_RE.match(s):
        return True
    if _RURAL_DESIGNATOR_RE.match(s):
        return True
    if _ROAD_SUFFIX_RE.search(s):
        return True
    return False


# Heavy raw keys read ONLY by the detail panel (audited: absent from every
# filter/sort/card-render path). Moved to the index-aligned listings_detail.json
# so the initial board parse skips ~10MB of comps/vision arrays.
LAZY_DETAIL_KEYS = ("vision", "foreclosure_sold_comps", "comps", "cama", "rent_comps")


def _identity_keys(rec: dict):
    """Candidate cross-run identity keys for a published record.

    Used to carry a lead's prior sidecar detail (vision/comps/cama) across a
    FULL re-scrape, where index alignment is meaningless (order + count change
    every run).

    CAUTION — a key here is only a CANDIDATE, never trusted on its own. None of
    these is unique by construction: on the live board 652 source_urls are shared
    by 19,392 leads (one ArcGIS service URL alone is shared by 3,293, and county
    PDF rolls give every lead in the file the same URL), and 82 address+county
    pairs collide on placeholders like "0 no address assigned". Callers MUST
    discard any key claimed by more than one record — see _unique_key_map. An
    earlier version trusted source_url as "most unique" and handed one property's
    vision report to 985 unrelated leads.
    """
    keys: list[str] = []
    su = rec.get("source_url")
    if isinstance(su, str) and su.strip():
        keys.append("u:" + su.strip())
    pid = rec.get("parcel_id")
    if isinstance(pid, str) and pid.strip():
        keys.append("p:" + pid.strip().lower())
    addr = rec.get("street_address")
    cnty = rec.get("county")
    if isinstance(addr, str) and addr.strip() and isinstance(cnty, str) and cnty.strip():
        keys.append("a:" + addr.strip().lower() + "|" + cnty.strip().lower())
    return keys


def _load_prior_details_by_key(docs: Path) -> dict:
    """Map identity-key -> prior sidecar detail dict from the currently-published
    board, so write_artifact can preserve vision/comps/cama for leads that
    persist across runs but weren't re-enriched this run.

    Without this, a completed full run (which only re-visions a capped subset)
    writes details[i]={} for every un-re-visioned lead, WIPING the sidecar for
    the ~29k leads it didn't touch. Keyed by identity (not index) so it survives
    the reordering a full re-scrape produces. Returns {} if the board is absent
    or unreadable (fresh publish, or first run) — never raises.
    """
    lp = docs / "listings.json"
    dp = docs / "listings_detail.json"
    if not lp.exists() or not dp.exists():
        return {}
    try:
        recs = json.loads(lp.read_text())
        dets = json.loads(dp.read_text())
    except Exception:  # noqa: BLE001
        return {}
    unique = _unique_key_map(recs)
    out: dict = {}
    for i, rec in enumerate(recs):
        if i >= len(dets):
            break
        d = dets[i]
        if not isinstance(d, dict) or not d or not isinstance(rec, dict):
            continue
        for key in _identity_keys(rec):
            if unique.get(key):
                out[key] = d
    return out


def _unique_key_map(recs: list) -> dict:
    """key -> True only when EXACTLY ONE record in `recs` claims it.

    An ambiguous key cannot identify a lead, so carrying detail across it hands
    one property's vision/comps report to every other lead behind the same key.
    Counting first (rather than first-wins) is what makes the backfill safe.
    """
    freq: dict = {}
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        for key in _identity_keys(rec):
            freq[key] = freq.get(key, 0) + 1
    return {k: (n == 1) for k, n in freq.items()}


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically: a temp file in the same dir + os.replace, so a
    kill mid-write leaves the PRIOR file intact instead of a truncated,
    corrupt one. os.replace is atomic within a filesystem."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _slim_raw(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k, keep in RAW_KEEP.items():
        v = raw.get(k)
        if v is None:
            continue
        if keep == "*":
            out[k] = v
        elif isinstance(v, dict):
            out[k] = {sk: v[sk] for sk in keep if sk in v}
    return out


def _to_dict(li: Listing) -> dict:
    d = li.model_dump(mode="json", exclude_none=False)
    # Trim raw payload
    d["raw"] = _slim_raw(li.raw)
    # Null junk addresses in the PUBLISHED record so the dashboard/map don't
    # render a court-doc/lien placeholder ("Lis Pendens …", "Tract …", etc.)
    # as if it were a property. The listing is kept; raw is untouched.
    if not _is_valid_street_address(d.get("street_address")):
        d["street_address"] = None
    # Drop legal_description from public view (often huge)
    if "legal_description" in d and d["legal_description"]:
        d["legal_description"] = d["legal_description"][:200]
    # Stale-link safety net: for per-property aggregator leads (realtor/
    # zillow/trulia/homes.com/foreclosure.com) add reliable fallback links
    # (county GIS + Google + Maps) into raw and flag old carryover leads as
    # link_may_be_stale. NEVER touches source_url; never drops the lead.
    annotate_stale_links(d)
    return d


def write_artifact(
    listings: list[Listing],
    summary: dict,
    docs_dir: Path | str = "docs",
) -> tuple[Path, Path]:
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)

    listings_path = docs / "listings.json"
    meta_path = docs / "run_meta.json"

    payload = [_to_dict(li) for li in listings]

    # Split the heavy, detail-panel-only raw keys (comps/vision arrays — the
    # most deeply nested payload) into an index-aligned sidecar the dashboard
    # fetches lazily on the first card open. Index alignment (not a per-lead id)
    # is the join: both files are built from `payload` in the same order, so
    # detail[i] belongs to listing[i]. Popping happens LAST (after _to_dict /
    # _slim_raw / annotate_stale_links) so nothing re-adds these keys. Additive:
    # if listings_detail.json is missing/mismatched, those panels render empty.
    # Prior sidecar, keyed by identity — lets a full re-scrape (which only
    # re-visions a capped subset) KEEP vision/comps/cama for the leads it
    # didn't touch this run, instead of overwriting details[i] with {}.
    # Fresh detail from THIS run always wins; prior only backfills missing keys.
    prior = _load_prior_details_by_key(docs)
    # Guard BOTH sides: a key can be unique in the prior board yet ambiguous in
    # what we are about to write (e.g. a re-scrape that pulled 3,293 leads from
    # one ArcGIS URL). Carrying detail across it would fan one report out to all
    # of them, so only keys unique on BOTH sides are allowed to match.
    payload_unique = _unique_key_map(payload) if prior else {}
    details = []
    for rec in payload:
        raw = rec.get("raw")
        d = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        if prior:
            pri = None
            for key in _identity_keys(rec):
                if payload_unique.get(key) and key in prior:
                    pri = prior[key]
                    break
            if pri:
                for k in LAZY_DETAIL_KEYS:
                    if k not in d and k in pri:
                        d[k] = pri[k]
        details.append(d)
    import gzip
    listings_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    detail_path = docs / "listings_detail.json"
    detail_bytes = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
    # Atomic writes (temp + os.replace) so a kill mid-write can never leave a
    # truncated 100MB+ file — the prior good file survives. git history is the
    # rollback backup for a completed-but-bad write (the count-drop guard flags
    # those before publish).
    _atomic_write_bytes(listings_path, listings_bytes)
    _atomic_write_bytes(detail_path, detail_bytes)
    # Also emit gzipped copies the dashboard fetches (16x smaller). The .json
    # files remain the local source-of-truth + a fallback. mtime=0 keeps the gzip
    # header deterministic so identical data produces identical bytes (no git churn).
    _atomic_write_bytes(docs / "listings.json.gz", gzip.compress(listings_bytes, compresslevel=9, mtime=0))
    _atomic_write_bytes(docs / "listings_detail.json.gz", gzip.compress(detail_bytes, compresslevel=9, mtime=0))

    meta = {
        "run_time": datetime.utcnow().isoformat() + "Z",
        "total": len(listings),
        "by_source": summary.get("by_source", {}),
        "by_state": summary.get("by_state", {}),
        "by_county_top": summary.get("by_county_top", []),
        "source_status": summary.get("source_status", {}),
        "regressions": summary.get("regressions", []),
        "errors": summary.get("errors", []),
        "notes": summary.get("notes", ""),
    }
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    log.info("web_artifact.written", listings=len(listings), bytes=listings_path.stat().st_size)
    return listings_path, meta_path
