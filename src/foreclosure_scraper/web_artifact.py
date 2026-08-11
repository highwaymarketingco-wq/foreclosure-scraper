"""Generate the static-site JSON files consumed by docs/index.html (the live dashboard).

Writes (every one of these, plus a .gz twin for the four payloads, in ONE call —
a publish that stages some and not others ships a mis-joined board):
  docs/listings.json        — array of sanitized listings (Pydantic-dumped, raw kept slim)
  docs/listings_detail.json — index-aligned sidecar: the heavy comps/vision keys
  docs/listings_slim.json   — SLIM-V1, the board payload phones fetch
  docs/detail_shards/*.json.gz — index-aligned detail, cut so a phone can fetch one lead
  docs/run_meta.json        — run timestamp, source_status, totals, sources contributing
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


def read_board_json(path: Path | str):
    """Read a board JSON file, transparently falling back to its ``.gz`` twin.

    The uncompressed docs/listings.json (~97MB) is NOT committed to git — it
    exceeds GitHub's 100MB/file limit, and the dashboard only ever loads the
    gzipped copy. The local runner regenerates the plain .json every write, so on
    that machine this reads the plain file directly. Everywhere else (a fresh
    clone, a cloud CI/patch job, disaster recovery) only the committed .gz exists,
    so we decompress that instead. Either way the whole system can rebuild the
    board from just the 6MB .gz — nothing depends on the big file being present.
    """
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text())
    gz = p.with_name(p.name + ".gz")
    if gz.exists():
        import gzip as _gzip
        return json.loads(_gzip.decompress(gz.read_bytes()).decode("utf-8"))
    raise FileNotFoundError(f"{p} (and {p.name}.gz) not found")


def _board_file_present(path: Path) -> bool:
    """True when a board file exists as either the plain .json or its .gz twin.

    The presence test that pairs with read_board_json. `path.exists()` alone is
    the wrong question anywhere the uncompressed twin is gitignored.
    """
    p = Path(path)
    return p.exists() or p.with_name(p.name + ".gz").exists()


def load_board(docs_dir: Path | str = "docs") -> list[Listing]:
    """Load the published board as Listing objects WITH the lazy-detail sidecar
    merged back into each lead's raw.

    listings.json is slim (the heavy comps/vision keys live in the index-aligned
    listings_detail.json). Any incremental board-writer that reads listings.json
    directly and re-runs write_artifact would drop that detail — the sidecar gets
    rebuilt from raw, which no longer has those keys. Loading through this helper
    merges detail[i] back into listing[i].raw first, so the round-trip preserves
    it. Always use this instead of a hand-rolled json.loads loop in a board pass.

    Reads via read_board_json, so it works from either the plain .json (local
    runner) or the committed .gz (fresh clone / cloud) — see that helper.
    """
    docs = Path(docs_dir)
    records = read_board_json(docs / "listings.json")
    detail_path = docs / "listings_detail.json"
    details: list = []
    if detail_path.exists() or (detail_path.with_name(detail_path.name + ".gz")).exists():
        try:
            details = read_board_json(detail_path)
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
    "recorded_sales": "*",            # county sales-roll transactions: price/date/deed/parties (audit trail)
    "recorded_ratio_comps": "*",      # median sale-to-assessed ratio from nearby recorded sales
    "comp_median_ppa_recorded": "*",  # median $/acre from recorded vacant-lot sales
    "condition_tier": "*",            # move_in_ready / cosmetic / major / gut
    "condition_source": "*",          # "vision-HIGH" / "vision-MEDIUM" / regex/age default
    "vision": "*",                    # full Claude Vision condition report
    "doc_ocr": "*",                   # OCR of scanned legal-notice/deed docs: owner+address+debt$
    "dot_ocr": "*",                   # recorded Deed-of-Trust ORIGINAL principal + labelled
                                      # ESTIMATED current balance (never a payoff) + provenance
    "loan_amount": "*",               # scalar mirror of dot_ocr.loan_amount (recorded principal)
    "nc_ptscloud_delinquent_tax": "*",
    "lrcpwa": "*",                       # land-records parcel resolve: assessed/mailing/absentee   # PTS delinquent roll: parcel/assessed/mailing/tax_year (skip-trace)
    "nc_county_pdf_delinquent_tax": "*", # county PDF delinquent roll: county_id/owner provenance
    "rent_median_ppsf": "*",
    "estimated_monthly_rent": "*",
    "data_quality": "*",              # investor-facing caveats: synthetic_address / no_sqft / low_arv_confidence
    "parcel_resolution": "*",         # parcel + centroid reverse-geo (Cleveland NC / Cherokee SC fallback)
    "situs_road_only": "*",           # road name for a parcel with NO house number — CONTEXT, never mailable
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
    # The court-record BLOCK itself (cause of action, court location, ordered
    # date) was written by enrichment_courts._apply_nc_hit for every NC case
    # match and then stripped here because it was never whitelisted: 621
    # matches on the 2026-08-04 run, ZERO of them on the published board.
    "court_record": "*",
    # County sales roll: the parcel's own sale history (date/price/sqft/
    # arms-length flag) plus the fields it backfills. comps sat at 0% on the
    # 2026-08-03 board; forgetting to whitelist this would gather them and
    # throw them away at publish, exactly as happened to court_record.
    "county_sales": "*",
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
    "competition": "*",               # publication-reach/competition tag {level, reason, widely_published, sources}
    "signal_stack": "*",              # list-stacking: {count, signals[]} distinct distress signals per property
    "intent_score": "*",              # normalized 0-100 seller-intent score
    "intent_band": "*",               # hot/warm/cool/cold band
    "condition_cama": "*",            # CAMA per-parcel condition/grade/year_built
    "storm_damage": "*",              # Hurricane Helene damage-assessment match {damage_level, estimated_loss, ...}
    "rollback_exposure": "*",         # present-use/elderly deferral: rollback tax that comes due ON SALE
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

# "No house number assigned" sentinels that county layers put in the house-number
# slot of an otherwise real road ("99999 MEADOW RD", "0 CEDAR SPRINGS RD"). NC
# alone publishes 17,788 parcels as "99999 <ROAD>" and 285,716 as "0 <ROAD>", and
# SC's split situs uses PROP_ST_NO="0" for the same thing — every one of them a
# vacant / unnumbered lot. They are NOT mailable, but they lead with digits, so
# _HOUSE_NUM_RE waves them through and they reach the mail merge, the geocoder
# and the board looking like fact. Rejected outright: falling through to the
# road-suffix rule would just re-accept them on the strength of the "RD".
# NOTE: no re.ASCII — GIS situs strings carry non-breaking spaces, and an
# ASCII-only \s let "0\xa0MEADOW RD" slip straight through this guard.
_PLACEHOLDER_HOUSE_NUM_RE = re.compile(r"^(?:0+|9{4,})(?:\s| )+\S")


def is_pinpointable_address(addr: str | None) -> bool:
    """True only when `addr` identifies ONE BUILDING — i.e. it leads with a real
    house number.

    STRICTER than _is_valid_street_address on purpose. That one answers "is this
    a plausible address string" and deliberately accepts bare rural roads via the
    road-suffix rule ("MEADOW RD", "NC HWY 9"), which is right for display.

    But a bare road is NOT a building. Geocoding it returns the ROAD CENTROID, so
    anything that spends money or asserts fact per-property must use this gate
    instead. Measured on the live board: 1,237 addressed leads are numberless and
    84% of them still return Street View imagery — of a random stretch of road,
    which would then be attached to the lead and condition-graded as if it were
    the house. Use this for Street View targeting, mail merges, and any
    "resolved" marker; use _is_valid_street_address for rendering.
    """
    if not _is_valid_street_address(addr):
        return False
    return bool(_HOUSE_NUM_RE.match(str(addr).strip()))


def _is_valid_street_address(addr: str | None) -> bool:
    """True if `addr` looks like a real, mailable street address (house number or
    a recognized rural road form), False for court-doc/lien placeholders,
    no-house-number sentinels and empties. Defensive: bad input -> False, never
    raises."""
    if not isinstance(addr, str):
        return False
    s = addr.strip()
    if not s:
        return False
    low = s.lower()
    if any(m in low for m in _INVALID_ADDR_MARKERS):
        return False
    if _PLACEHOLDER_HOUSE_NUM_RE.match(s):
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


# ===========================================================================
# SLIM-V1 — docs/listings_slim.json(.gz), the mobile payload
#
# 2026-08-10: the board was killing the WebContent process on two iPhones on
# every launch. docs/dashboard.js now streams listings.json.gz and projects each
# record down to a field allowlist as it parses (521 MB heap -> 167 MB), which
# fixed the crash but still makes a phone download and inflate 272 MB to throw
# ~85% of it away. This emits that projection build-side instead: ~52 MB of JSON
# and ~4 MB on the wire.
#
# THE THREE RULES THIS FILE IS UNDER:
#
# 1. ADDITIVE, NEVER AUTHORITATIVE. listings.json + listings_detail.json are
#    TOGETHER the only full-fidelity board on disk — both are gitignored, only
#    the .gz twins are committed. Drop a key from either and the next
#    load_board() returns Listings without it, the next write_artifact()
#    re-serializes from that lobotomized raw, and the enrichment is gone
#    permanently, with three unattended launchd jobs (dailyvision 09:30, lrcpwa
#    12:00, sosagent 14:00) doing it within hours. So the slim file is derived
#    from the same `payload` list AFTER both authoritative files are already on
#    disk, it never mutates `payload`, and load_board() must NEVER read it.
#
# 2. IT IS THE BUILD-SIDE COPY OF THE CLIENT'S PROJECTOR, and the two can drift.
#    _SLIM_TOP / _SLIM_RAW / _SLIM_RAW_SCALARS mirror _LEAN_TOP / _LEAN_RAW /
#    _LEAN_RAW_SCALARS in docs/dashboard.js, and _project_slim_record mirrors
#    projectRecord(rec, true) — including the four fields the client derives
#    from `description` (kw_vacant, the flattened acres probe,
#    lrcpwa.mail_state, life_events as an int) and the Helene placard regex, all
#    of which are precomputed here so the slim file does not have to ship
#    `description` at all. The projector is idempotent, so a LEAN client running
#    it over an already-slim record is a no-op and one code path reads both
#    files. tests/test_board_slim.py parses the JS and asserts the two lists are
#    equal — if that test fails, the client changed and this must follow.
#
# 3. NOTE _SLIM_RAW's "*" SENTINEL. grade and calc are kept WHOLE. They were
#    sub-allowlisted client-side and both drifted within hours: the grade badge
#    row rendered "undefined undefined undefined undefined" and every listing on
#    every phone claimed "CONFIDENCE: LOW". A fabricated number on a board people
#    bid money off is worse than a missing one. Do not sub-allowlist them here.
# ===========================================================================

# Top-level scalars. Mirrors _LEAN_TOP. `description` is deliberately absent —
# everything the client derived from it is precomputed below.
_SLIM_TOP = (
    "source", "source_url", "listing_type", "property_kind",
    "street_address", "city", "state", "zip_code", "county", "parcel_id",
    "latitude", "longitude",
    "sale_date", "sale_time", "sale_location", "upset_bid_deadline", "redemption_deadline",
    "opening_bid", "judgment_amount", "tax_value", "auction_status", "foreclosure_process",
    "bedrooms", "bathrooms", "living_sqft", "year_built", "acreage", "zoning",
    "case_number", "plaintiff", "defendant", "trustee", "owner_name",
)

# Per-block sub-key allowlist. Mirrors _LEAN_RAW. A block present in the source
# is ALWAYS emitted even when none of its sub-keys survive, because several
# client call sites test the block for existence rather than reading it
# (raw.upset_bid, raw.bankruptcy). "*" keeps the block whole — see rule 3.
_SLIM_RAW: dict[str, str | tuple[str, ...]] = {
    "grade": "*",
    "calc": "*",
    # data_quality.summary is 5.7 MB of prose and reads like an obvious cut. It
    # stays: it is the CSV's data_quality_note column, and the export must be
    # byte-identical on every device.
    "data_quality": ("flags", "summary"),
    "distress_stack": ("tier", "score", "stack", "signals", "categories", "absentee",
                       "out_of_state", "contactable", "equity_band",
                       "surviving_senior_debt_risk"),
    "signal_stack": ("count",),
    "strategy_fit": ("tags",),
    "owner_mailing": ("mailing", "mail_state", "absentee", "out_of_state"),
    "owner_phone": ("phone", "source", "needs_dnc_scrub"),
    "sos_agent": ("sosid", "best_contact_name", "best_contact_address"),
    "rod": ("has_mortgage", "has_adverse_lien"),
    "equity": ("value", "pct", "is_underwater"),
    "title_risk": ("surviving_senior_debt_risk",),
    "corroboration": ("court_confirmed", "label", "tier", "multi_source"),
    "helene": ("worst_placard", "worst_damage_pct", "damaged_buildings"),
    "bankruptcy": ("chapter", "date_filed", "case_name", "docket_number", "court"),
    "courtlistener": ("chapter", "date_filed", "court"),
    "last_sale": ("date", "amount", "basis"),
    "zillow": ("photo",),
    "gis": ("owner",),
    "lrcpwa": ("absentee", "mail_state"),
    "tax_owed": ("balance",),
    "upset_bid": ("in_window", "days_remaining"),
}

# Mirrors _LEAN_RAW_SCALARS.
_SLIM_RAW_SCALARS = (
    "intent_score", "intent_band", "multifamily_class",
    "stale_case", "geo_imprecise", "sold_confirmed", "kw_vacant", "acres",
)

# Mirrors _ACRE_KEYS. The client probes three containers x four names = the
# 12-way acreage probe; the result is flattened to raw.acres here so the slim
# file carries one number instead of three blocks kept alive to hold it.
_SLIM_ACRE_KEYS = ("acreage", "acres", "calculatedAcres", "deededAcres")

# Mirrors the two regexes in heleneInfo()'s description fallback. Only Asheville
# Helene leads carry a placard in prose rather than in the dedup meta.
_HELENE_PLACARD_RE = re.compile(r"Helene damage:\s*([A-Za-z]+)\s+placard")
_HELENE_PCT_RE = re.compile(r"placard\s*-\s*([0-9]+)%")
_HELENE_SOURCE = "counties_nc.asheville_helene"

_VACANT_MARKERS = ("vacant lot", "vacant land", "vacant parcel")

# JS parseFloat: optional sign, leading numeric prefix, trailing garbage ignored
# ("12.5 acres" -> 12.5). Anchored at the start after stripping leading space.
_JS_FLOAT_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def _js_parse_float(v):
    """Python stand-in for JS ``parseFloat``, which is what the client's acreage
    probe uses. Non-numeric -> None (JS NaN). Booleans are NOT numbers in JS, and
    Python's bool-is-int would otherwise turn ``acreage: true`` into 1 acre.

    Integral results come back as ``int`` so json.dumps emits ``12`` and not
    ``12.0`` — matching JSON.stringify, which has no float/int distinction.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        m = _JS_FLOAT_RE.match(v.strip())
        if not m:
            return None
        try:
            f = float(m.group(0))
        except ValueError:
            return None
    else:
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / Infinity
        return None
    return int(f) if f.is_integer() and abs(f) < 2 ** 53 else f


def _slim_acres_probe(raw: dict):
    """Mirrors _acresProbe: first hit across (raw.lrcpwa, raw.gis, raw) x the
    four acreage spellings. Returns None when nothing parses."""
    r = raw if isinstance(raw, dict) else {}
    for src in (r.get("lrcpwa"), r.get("gis"), r):
        if not isinstance(src, dict):
            continue
        for k in _SLIM_ACRE_KEYS:
            v = _js_parse_float(src.get(k))
            if v is not None:
                return v
    return None


def _slim_life_event_count(le) -> int | float:
    """Mirrors _lifeEventCount. raw.life_events is a list of probate/elderly
    signals but the client only ever reads ``.length``, so the slim file ships
    the count. Matches the JS exactly, including that a bool has no .length."""
    if le is None or isinstance(le, bool):
        return 0
    if isinstance(le, (int, float)):
        return le
    try:
        return len(le) or 0
    except TypeError:
        return 0


def _project_slim_record(rec: dict) -> dict:
    """Build-side ``projectRecord(rec, lean=true)``.

    Pure: never mutates `rec` or anything reachable from it. The "*" blocks are
    passed through by REFERENCE (they are large and this runs 38,500 times), so
    every derived value below is written into a dict this function created.
    """
    if not isinstance(rec, dict):
        return rec

    out: dict = {}
    for k in _SLIM_TOP:
        if k in rec:
            out[k] = rec[k]

    desc = rec.get("description")
    if not isinstance(desc, str):
        desc = ""
    # kw_vacant replaces the three description probes in _catOf(), which decide
    # land vs residential and therefore which buyers match a lead. Precomputing
    # it is what lets `description` (6.1 MB) leave the payload without mobile
    # silently classifying leads differently from desktop.
    #
    # The `elif desc` (rather than a plain else) is what makes the CLIENT's
    # projector a strict fixed point on this file's output: with no description
    # in hand it emits no kw_vacant, so writing `kw_vacant: false` here for the
    # 65-odd records that carry an empty description would make
    # projectRecord(slim) stop deep-equalling slim. _catOf reads an absent
    # kw_vacant and a false one identically once description is also gone, so
    # this is byte-saving, not behaviour.
    kwv = rec.get("kw_vacant")
    if kwv is not None:
        out["kw_vacant"] = bool(kwv)
    elif desc:
        low = desc.lower()
        out["kw_vacant"] = any(m in low for m in _VACANT_MARKERS)

    raw = rec.get("raw")
    if not isinstance(raw, dict):
        if "raw" in rec:
            out["raw"] = raw
        return out

    r: dict = {}
    for k, subs in _SLIM_RAW.items():
        src = raw.get(k)
        if src is None:
            continue
        if not isinstance(src, dict):
            r[k] = src            # shape drift: keep verbatim, same as the client
            continue
        if subs == "*":
            r[k] = src            # by reference — never mutated
            continue
        r[k] = {sk: src[sk] for sk in subs if sk in src}

    for k in _SLIM_RAW_SCALARS:
        if k in raw:
            r[k] = raw[k]

    asi = raw.get("also_seen_in")
    if isinstance(asi, list):
        # Mirrors the client's {url, source} map. Absent sub-keys stay absent
        # rather than becoming nulls — JSON.stringify drops undefined.
        r["also_seen_in"] = [
            ({sk: s[sk] for sk in ("url", "source") if sk in s} if isinstance(s, dict) else s)
            for s in asi
        ]

    if "life_events" in raw:
        r["life_events"] = _slim_life_event_count(raw["life_events"])

    # lrcpwa.mail_state is the flattened form of lrcpwa.mailing.state, which the
    # out-of-state chip reads. Today's board carries only the nested key, so
    # without this the chip vanishes for 270 of the 3,062 leads with an lrcpwa
    # block. (r["lrcpwa"] is our own dict, so this mutation cannot reach payload.)
    lr = r.get("lrcpwa")
    if isinstance(lr, dict) and "mail_state" not in lr:
        src_lr = raw.get("lrcpwa")
        mailing = src_lr.get("mailing") if isinstance(src_lr, dict) else None
        if isinstance(mailing, dict) and mailing.get("state") is not None:
            lr["mail_state"] = mailing["state"]

    if "acres" not in r:
        a = _slim_acres_probe(raw)
        if a is not None:
            r["acres"] = a

    # heleneInfo() falls back to a regex over `description` when the dedup meta
    # carries no placard. Run that fallback here, while description is still in
    # hand, so worst_placard is always populated in the slim file.
    if desc and rec.get("source") == _HELENE_SOURCE:
        h = r.get("helene")
        if h is None:
            h = {}
        if isinstance(h, dict) and not h.get("worst_placard"):
            m = _HELENE_PLACARD_RE.search(desc)
            p = _HELENE_PCT_RE.search(desc)
            if m:
                h["worst_placard"] = m.group(1)
            if p:
                h["worst_damage_pct"] = int(p.group(1))
            if m or p:
                r["helene"] = h

    out["raw"] = r
    return out


def _slim_payload_bytes(payload: list) -> bytes:
    """Serialize the slim projection of `payload`.

    Record-at-a-time and joined, rather than json.dumps over a projected list,
    so the whole projected object graph is never resident — this runs right
    after two multi-hundred-MB serializations on an 8 GB machine.

    COMPACT SEPARATORS, and only here: default separators cost 17.1 MB of pure
    whitespace at this record count. listings.json keeps its default separators
    because its bytes must not change.
    """
    parts = [
        json.dumps(_project_slim_record(rec), ensure_ascii=False, default=str,
                   separators=(",", ":")).encode("utf-8")
        for rec in payload
    ]
    return b"[" + b",".join(parts) + b"]"


def _emit_slim(docs: Path, payload: list) -> int | None:
    """Write listings_slim.json + .gz. Returns the record count, or None if the
    slim payload could not be produced.

    Never raises. This runs inside three unattended daily jobs, after the
    authoritative board is already safely on disk, and a derivative file is not
    worth failing a run over.

    On failure the slim files are REMOVED rather than left behind. Index i is
    the join across listings.json / listings_detail.json / listings_slim.json,
    and that alignment only holds within one write_artifact call — a stale slim
    file beside a fresh board is a silently mis-joined board on a phone, which is
    strictly worse than no slim file at all (the client 404s and streams the fat
    one, which is exactly what it does today).
    """
    slim_path = docs / "listings_slim.json"
    gz_path = docs / "listings_slim.json.gz"
    if os.getenv("FORECLOSURE_SLIM") == "0":   # emergency stop for the launchd jobs
        return None
    try:
        import gzip as _gzip
        slim_bytes = _slim_payload_bytes(payload)
        _atomic_write_bytes(slim_path, slim_bytes)
        _atomic_write_bytes(gz_path, _gzip.compress(slim_bytes, compresslevel=9, mtime=0))
        return len(payload)
    except Exception as exc:  # noqa: BLE001
        for p in (slim_path, gz_path,
                  slim_path.with_name(slim_path.name + ".tmp"),
                  gz_path.with_name(gz_path.name + ".tmp")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        log.warning("web_artifact.slim_failed", error=str(exc))
        return None


# ===========================================================================
# DETAIL SHARDS — docs/detail_shards/NNNNN.json.gz, the mobile detail payload
#
# Phase 3 gave phones docs/listings_slim.json.gz, so the BOARD fits. Opening one
# lead still did not: listings_detail.json inflates to 70.8 MB and the client
# Object.assigns all 38,500 of them permanently into LISTINGS[i].raw, so on the
# device whose whole problem is memory the first tap finished it. dashboard.js
# therefore skips the sidecar entirely on LEAN and prints "Open this lead on a
# desktop for comps, photo analysis and CAMA."
#
# A shard is that file, cut into 39 index-aligned pieces. Shard k covers board
# indices [k*SIZE, (k+1)*SIZE). A phone fetches the ONE shard holding the lead
# it opened — 413 KB at the median, 6 MB inflated — instead of 7.6 MB / 70.8 MB.
#
# WHY THE CONTENT IS THE COMPLEMENT OF SLIM AND NOT JUST LAZY_DETAIL_KEYS.
# The detail panel's "Everything We Found" (dashboard.js:1641) is not a named
# read, it is a reflective sweep over Object.keys(raw). The slim projection is a
# name allowlist, and a name allowlist cannot preserve a reflective reader: the
# board carries 107 distinct raw.* keys and slim keeps 29. A shard carrying only
# the five LAZY_DETAIL_KEYS would restore comps/vision/CAMA and leave ~46 other
# blocks blank — eviction_market (80.9% of records), amount_owed (59.9%), tenure
# (43.7%), recorded_comps, recorded_sales, condemned, divorce, nc_ecourts. So a
# shard record is listings_detail.json[i] MERGED WITH every raw key that
# listings.json carries and the slim projection does NOT reproduce in full.
#
# _SHARD_SKIP_RAW is derived from _SLIM_RAW / _SLIM_RAW_SCALARS rather than
# written out, so it cannot drift from the projector the way a hand-kept second
# list would. Only two classes of key are skipped:
#   * _SLIM_RAW entries marked "*" (grade, calc) — slim ships them WHOLE.
#   * _SLIM_RAW_SCALARS — slim ships the scalar verbatim.
# A block slim keeps only a SUB-TUPLE of (zillow -> photo, gis -> owner,
# signal_stack -> count, equity -> value/pct/is_underwater, ...) is emitted here
# in FULL, on purpose. The client merge is a top-level assign, so a partial
# block in the shard would REPLACE, not deepen, the partial block already on the
# record — and the panel reads exactly the sub-keys slim drops (zillow
# .description, gis.mailing, signal_stack.signals, equity.payoff_source). The
# duplicated sub-keys cost bytes; a half-populated block costs facts.
#
# THE INVARIANT THIS CODE IS UNDER, same as SLIM-V1's rule 1: ADDITIVE, NEVER
# AUTHORITATIVE. listings.json + listings_detail.json are TOGETHER the only
# full-fidelity board on disk. Shards are emitted from the SAME payload/details
# lists AFTER all six authoritative files are already written, they never mutate
# either list, and load_board() must NEVER read them.
# ===========================================================================

DETAIL_SHARD_DIR = "detail_shards"
DETAIL_SHARD_SIZE = 1000          # records per shard -> 39 files at 38,500 leads
DETAIL_SHARD_SCHEMA = "shard-v1"

# Raw keys the slim payload already reproduces IN FULL, so a shard would only
# duplicate them. Derived, never hand-listed — see the block comment above.
_SHARD_SKIP_RAW = frozenset(k for k, v in _SLIM_RAW.items() if v == "*") | frozenset(_SLIM_RAW_SCALARS)


def _shard_record(rec: dict, det) -> dict:
    """One shard entry: the raw keys slim does not carry, plus the sidecar.

    Pure — never mutates `rec`, `rec["raw"]` or `det`. Sub-objects are passed by
    REFERENCE (this runs 38,500 times right after two multi-hundred-MB
    serializations), so nothing below may write into them.

    `det` is applied LAST. It cannot collide today — write_artifact pops every
    LAZY_DETAIL_KEY out of raw before building details, so the two key sets are
    disjoint — but if that ever changes, the sidecar is the copy that survived
    the identity-keyed cross-run backfill and is the one to keep.

    An empty result is still emitted by the caller: index alignment IS the join.
    """
    out: dict = {}
    raw = rec.get("raw") if isinstance(rec, dict) else None
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k not in _SHARD_SKIP_RAW:
                out[k] = v
    if isinstance(det, dict) and det:
        out.update(det)
    return out


def _rm_detail_shards(shard_dir: Path) -> None:
    """Remove the shard directory and any temp files, never raising.

    Deliberately a real deletion and not a no-op: index i is the join across
    listings.json / listings_detail.json / detail_shards, and that alignment
    only holds within one write_artifact call. Shards left behind from a
    PREVIOUS board would silently show one lead's comps and vision under another
    lead's address — worse than the honest "open on desktop" note the client
    falls back to when the metadata is absent.

    Leaving the (now-empty) directory would be equally wrong: every publish site
    gates `git add docs/detail_shards` on "exists OR already tracked", and the
    tracked half of that gate is what lets this deletion reach the repo.
    """
    try:
        import shutil
        shutil.rmtree(shard_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


def _emit_detail_shards(docs: Path, payload: list, details: list,
                        slim_ok: bool = True) -> dict | None:
    """Write docs/detail_shards/NNNNN.json.gz. Returns the run_meta board
    sub-block describing them, or None when no usable shard set exists.

    Never raises. This runs inside four unattended launchd jobs, after the
    authoritative board is already safely on disk, and a derivative file is not
    worth failing a run over.

    On ANY failure — or when `slim_ok` is False — the whole directory is REMOVED
    rather than left half-written or left behind: the client keys off the
    metadata, which is omitted in lockstep, so it falls back to today's
    desktop-only note instead of rendering half a lead or a stale one.

    `slim_ok` is the deliberate coupling of the two mobile derivatives. Shards
    are only ever fetched by the LEAN client, they are advertised inside the
    same run_meta "board" block the slim payload owns, and that block is defined
    as describing the payload THIS call wrote. So when slim is absent — the
    FORECLOSURE_SLIM=0 emergency stop, or a projection failure — the honest
    outcome is that the whole mobile payload is absent together, and mobile
    degrades to exactly what it does today. Emitting 28 MB of shards that
    nothing advertises would be the worst of both.
    """
    shard_dir = docs / DETAIL_SHARD_DIR
    if not slim_ok:
        _rm_detail_shards(shard_dir)
        return None
    if os.getenv("FORECLOSURE_DETAIL_SHARDS") == "0":   # emergency stop
        # Unlike the slim stop, this REMOVES. A stale shard set is mis-joined
        # data on a phone; a stale slim file at least still describes a board.
        _rm_detail_shards(shard_dir)
        return None
    if not payload:
        _rm_detail_shards(shard_dir)
        return None
    try:
        import gzip as _gzip
        shard_dir.mkdir(parents=True, exist_ok=True)
        written: set[str] = set()
        for start in range(0, len(payload), DETAIL_SHARD_SIZE):
            stop = start + DETAIL_SHARD_SIZE
            recs = payload[start:stop]
            dets = details[start:stop]
            # Joined bytes rather than json.dumps over a built list, matching
            # _slim_payload_bytes: the merged object graph is never resident.
            parts = [
                json.dumps(_shard_record(rec, dets[i] if i < len(dets) else None),
                           ensure_ascii=False, default=str,
                           separators=(",", ":")).encode("utf-8")
                for i, rec in enumerate(recs)
            ]
            body = b"[" + b",".join(parts) + b"]"
            name = f"{start // DETAIL_SHARD_SIZE:05d}.json.gz"
            _atomic_write_bytes(shard_dir / name,
                                _gzip.compress(body, compresslevel=9, mtime=0))
            written.add(name)
        # Purge shards from a LARGER previous board plus any orphaned .tmp. A
        # board that shrinks from 38,500 to 20,000 leaves shards 20..38 on disk
        # holding indices that no longer exist.
        for stale in shard_dir.iterdir():
            if stale.name not in written:
                try:
                    stale.unlink()
                except OSError:
                    pass
        return {
            "schema": DETAIL_SHARD_SCHEMA,
            "dir": DETAIL_SHARD_DIR,
            "size": DETAIL_SHARD_SIZE,   # records per shard: index i -> i // size
            "count": len(written),       # number of shard files
            "records": len(payload),     # indices covered: must equal board.count
        }
    except Exception as exc:  # noqa: BLE001
        _rm_detail_shards(shard_dir)
        log.warning("web_artifact.detail_shards_failed", error=str(exc))
        return None


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

    Reads through read_board_json, exactly like load_board at :59. It used to use
    plain .exists() + plain json.loads on the uncompressed twins ONLY, and both
    of those are gitignored (.gitignore:77-78) — only listings.json.gz and
    listings_detail.json.gz are committed. So on a fresh clone, a cloud/CI run or
    a disaster-recovery restore — the exact machines read_board_json's docstring
    was written for — this returned {} and the safety net silently disappeared.
    The next write_artifact would then publish details[i]={} for every lead it
    hadn't re-enriched, and since listings.json + listings_detail.json are
    TOGETHER the only full-fidelity board on disk, the next load_board would bake
    that loss in permanently. Silent, unattended, unrecoverable. Never narrow
    this back to the plain files.
    """
    lp = docs / "listings.json"
    dp = docs / "listings_detail.json"
    if not _board_file_present(lp) or not _board_file_present(dp):
        return {}
    try:
        recs = read_board_json(lp)
        dets = read_board_json(dp)
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

    # SLIM-V1, the mobile payload. Derived from the SAME `payload` list, and
    # deliberately emitted only after the two authoritative files are already on
    # disk: nothing below this line can change listings.json's bytes, and a bug
    # in the derivative cannot cost a run its board. See the SLIM-V1 block above.
    del listings_bytes, detail_bytes    # free ~350 MB before projecting (8 GB box)
    slim_count = _emit_slim(docs, payload)

    # DETAIL SHARDS, the mobile detail payload. Same contract as the slim file
    # and deliberately last: every authoritative byte is already on disk, this
    # reads `payload` and `details` without mutating either, and a failure here
    # costs a derivative, never a board. Gated on the slim emit having succeeded
    # — the two are one mobile payload, advertised in one metadata block. See
    # the DETAIL SHARDS block above.
    shard_meta = _emit_detail_shards(docs, payload, details,
                                     slim_ok=slim_count is not None)

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
    # Board block: how the dashboard learns the slim payload exists and how many
    # records it must contain. run_meta.json is already in every publish list, so
    # this adds zero new entries to the five hardcoded ones. Absent whenever the
    # slim emit was skipped or failed — and it is NOT carried forward from the
    # prior meta by the health-preservation block below, which is the point: a
    # board block always describes the slim file written by THIS call.
    #
    # detail_shards is a SIBLING key, added without touching schema/count: the
    # client's boardExpectedCount() (dashboard.js:469) gates on board.schema ===
    # "slim-v1" and returns null for anything else, so renaming or re-shaping
    # the outer block would silently disable the record-count gate that stops a
    # short payload rendering as a whole board. It carries `size` so the client
    # derives shard index i // size instead of hardcoding 1000, and `records` so
    # a client that fetched a shard set from a different write can tell.
    if slim_count is not None:
        meta["board"] = {"schema": "slim-v1", "count": slim_count}
        if shard_meta is not None:
            meta["board"]["detail_shards"] = shard_meta

    # PRESERVE per-source health across partial writers.
    # Fourteen maintenance scripts (sos_agent_refresh, lrcpwa_refresh,
    # owner_mailing_refresh, the ingest_* family, ...) call write_artifact with a
    # one-key summary like {"notes": "scheduled NC SOS refresh"}. Each one then
    # blanked by_source / source_status / by_state, so run_meta.json - the ONLY
    # per-source health report there is - showed "by_source": {} for days after a
    # full run, and neither the operator nor a dashboard could answer "which
    # sources are actually contributing". Carry the prior run's values forward
    # when this writer did not compute its own, and mark the file so the staleness
    # is visible rather than implied.
    _carried: list[str] = []
    if meta_path.exists():
        try:
            prior_meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001 - a corrupt prior file must not block the write
            prior_meta = {}
        for key in ("by_source", "by_state", "by_county_top", "source_status",
                    "regressions", "errors"):
            if not meta.get(key) and prior_meta.get(key):
                meta[key] = prior_meta[key]
                _carried.append(key)
        if _carried:
            meta["health_carried_from"] = prior_meta.get("run_time")
            meta["health_carried_keys"] = _carried
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    log.info("web_artifact.written", listings=len(listings), bytes=listings_path.stat().st_size)
    return listings_path, meta_path
