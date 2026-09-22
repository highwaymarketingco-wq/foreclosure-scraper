"""Stacked-distress score: the HOT/WARM/COLD operator board.

Turns the signals we already collect into a ranked motivated-seller score, the
way the paid lead desks do. Core idea (roadmap §6): a property hit by MULTIPLE
*distinct distress categories* is a far hotter lead than one with a single
signal. We:

  1. Group listings by parcel (state + county + parcel id), so the same property
     in foreclosure AND tax sale stacks; cross-listing.
  2. Collect distress signals across the group, bucketed into 5 CATEGORIES.
     STACKED-2+ counts distinct *categories* (two liens = one FINANCIAL, not
     two) so a single default event can't fake a stack. The enforcement chain
     (lis pendens -> foreclosure -> sale -> upset bid -> REO / auction) is ONE
     FINANCIAL category, because it is one event seen at successive steps.
  3. Every signal carries an EVIDENCE class (audit 2026-09-21, F6):
        record       a public record about this property or case
        inferred     derived from text, a heuristic or a deed pattern
        name_joined  a record about a party, attached to the property by owner-name search
        name_only    a party name matched in a roster with no second identifier
     Name-based signals still add SCORE, but a name-based category never CREATES a
     stack: it counts only once two record-linked categories already exist. HOT
     needs at least one record-linked signal.
  4. Score = best weight per category + absentee/out-of-state bonus - senior-lien
     penalty. Tier: distressed lane = HOT needs stack 2+, EVIDENCED equity >= med,
     a mailable owner and a record-linked signal; WARM = stack 2+, or a strong
     single signal with (possibly estimated) equity, or absentee + a real event.
     The equity term is ARV-derived, so it passes through the ARV trust gate first
     (`_equity_band`): a lead whose valuation the board refuses to bid off ranks on
     its distress RECORDS, never on its equity.
  5. LIFECYCLE (F2): the scorer takes `today`. An upset-bid window counts only while
     it is open, a sale whose date passed (14 days NC, 7 days SC) with no open
     window or redemption period contributes nothing and caps the tier at COLD.
  6. FORECLOSURE LANE (F7): a foreclosure-type lead with a live date (sale within 30
     days, or an open upset-bid window) is tiered as a bidder's lead, not a seller's:
     no mailable-owner or equity requirement; HOT if the title risk is known clean
     and no bankruptcy stay is in force, else WARM (COLD on a junior-lien trap).

  7. FOOTPRINT (owner rule 2026-09-15): a flip-type lead stamped raw['scope'] ==
     'flip_outside_footprint' by the data-quality pass is capped COLD with
     `scope_capped: "flip_outside_footprint"` and contributes nothing to its parcel; a
     distressed-type lead on the same parcel, or a stamp on one, is scored normally.

Contactability (a mailable owner) is a HARD GATE for HOT in the distressed lane:
a hot lead you can't reach isn't actionable. Already-sold properties
(sold_confirmed) are excluded. Pure computation over the board; no scraping.
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

import structlog

from .mailing_shape import mailing_dict
from .models import Listing
from .name_normalize import party_middle_conflict
from .enrichment_equity import (
    equity_is_evidenced, is_countable_debt, valuation_ran_without_arv,
)
from .signal_freshness import (
    bankruptcy_lapsed, code_enforcement_open, custody_ended, to_date,
)
from .valuation.grading import ARV_TRUST_BLOCKS_DERIVED, arv_trust

log = structlog.get_logger()

#: Counters from the most recent `score_board` call (lane / cap counts, errors). The tier
#: histogram it returns stays exactly {HOT, WARM, COLD}; these are for the run log.
LAST_STATS: dict = {}


class ScoreBoardError(RuntimeError):
    """`score_board` could not score every group. Raised AFTER every group that could be
    scored was, so `.hist` holds the partial histogram and `.failures` the first few
    (source, error) pairs. Audit F17: the failure used to be logged and the run carried on
    with the PREVIOUS run's tiers still on the rows, which every later stage (lead
    signals, Fullmer, the published board) then read as current. Rows in a failed group
    are stamped `score_error` and dropped to COLD, so nothing stale survives."""

    def __init__(self, message: str, *, failed: int = 0, hist: Optional[dict] = None,
                 failures: Optional[list] = None):
        super().__init__(message)
        self.failed = failed
        self.hist = hist or {}
        self.failures = failures or []


# ---------------------------------------------------------------------------
# Evidence classes
# ---------------------------------------------------------------------------
REC, INF, NJ, NO = "record", "inferred", "name_joined", "name_only"
#: Name-based evidence. Adds score; never creates a stack on its own.
_WEAK_EVIDENCE = frozenset({NJ, NO})
#: A name-based category joins the stack only when at least this many RECORD-linked categories are
#: already there. 2 means it can lengthen a real stack but never complete one: foreclosure + a
#: jail-roster name collision is one real event and a coincidence, not stack 2 (audit F6's own
#: worked example). Set to 1 for the looser reading "any record-linked partner is enough", under
#: which that example would still be stack 2.
_NAME_BASED_MIN_RECORD_CATEGORIES = 2
_EVIDENCE_ORDER = {REC: 3, INF: 2, NJ: 1, NO: 0}   # tie-break: the stronger evidence wins

# ATC-45 Helene placard severity -> honest PROPERTY-signal weight. Calibrated
# against the existing scale (generic distressed=10, code_enforcement=14,
# bankruptcy=18, probate=20): a Restricted placard (limited entry, real damage)
# sits just above generic distressed; an Unsafe red-tag (do-not-occupy, facing
# major repair/teardown) sits above code enforcement. Helene leads have only the
# PROPERTY category (stack=1) so they can never reach HOT on this alone — they
# only tier up to WARM when combined with absentee ownership + severity.
_HELENE_PLACARD_BASE = {"restricted": 12, "unsafe": 16, "destroyed": 20}


def _helene_signal(li: Listing) -> Optional[tuple[str, str, int]]:
    """Scaled distress signal for a Hurricane-Helene ATC-45 placard lead.

    Replaces the flat generic 'distressed' (10) with a weight graded by placard
    severity + damage % + how many structures on the parcel are damaged. Reads
    the raw['helene'] meta set by the dedup pass, else parses the description.
    Returns None for non-Helene leads.
    """
    if li.source != "counties_nc.asheville_helene":
        return None
    r = li.raw if isinstance(li.raw, dict) else {}
    meta = r.get("helene") if isinstance(r.get("helene"), dict) else {}
    desc = li.description or ""
    placard = str(meta.get("worst_placard") or "").lower()
    if not placard:
        m = re.search(r"Helene damage:\s*([A-Za-z]+)\s+placard", desc)
        placard = m.group(1).lower() if m else ""
    base = _HELENE_PLACARD_BASE.get(placard)
    if base is None:
        return None
    pct = meta.get("worst_damage_pct")
    if pct is None:
        p = re.search(r"placard\s*-\s*([0-9]+)%", desc)
        pct = float(p.group(1)) if p else 0.0
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        pct = 0.0
    buildings = meta.get("damaged_buildings") or 1
    w = base
    if placard == "restricted" and pct >= 50:
        w += 2
    elif placard in ("unsafe", "destroyed") and pct >= 75:
        w += 3
    if isinstance(buildings, int) and buildings >= 3:
        w += 2  # a multi-structure damaged complex is a larger repair burden
    return (f"helene_{placard}", "PROPERTY", w)


# raw['storm_damage'] (the Helene damage-layer join, enrichment_helene_damage) grades
# damage on a ladder that spells the same severities several ways. Only structural damage
# with real repair burden is a seller-pressure signal; "affected", a green placard and
# minor damage are not. Weights sit on the same scale as the Helene placard table above so
# a placard lead and a joined-damage lead of the same severity score the same.
_STORM_DESTROYED = {"destroyed", "natural disaster - destroyed"}
_STORM_MAJOR = {"major damage", "major", "red", "natural disaster - major damage"}
_STORM_MODERATE = {"yellow", "natural disaster - inundated", "natural disaster - landslide"}


def _storm_signal(sd) -> Optional[tuple[str, str, int]]:
    """(name, category, weight) from raw['storm_damage'], or None below the bar."""
    if not isinstance(sd, dict):
        return None
    level = str(sd.get("damage_level") or sd.get("placard") or "").strip().lower()
    if level in _STORM_DESTROYED:
        w = 20
    elif level in _STORM_MAJOR:
        w = 16
        if sd.get("substantial_damage") is True:
            w += 3       # FEMA 50% rule: repair cost >= half the value forces a rebuild to code
    elif level in _STORM_MODERATE:
        w = 12
        if sd.get("substantial_damage") is True:
            w += 4
    else:
        return None
    return ("storm_damage", "PROPERTY", w)


# MLS lifecycle statuses that signal a seller who couldn't (or stopped trying
# to) move the property on the open market — a strong, fresh motivated-seller
# tell that often precedes a price drop or a quiet pre-foreclosure sale.
_DEAD_MLS_STATUSES = {"expired", "withdrawn", "cancelled", "canceled"}

# A listing sitting on-market past ~2x the local market-velocity months-of-
# inventory (MOI) is genuinely stale — buyers have passed on it at the current
# price for twice as long as the typical sell-through. We read MOI from the
# per-listing market_velocity block (enrichment_comps); fall back to a sane
# default when velocity could not be computed for the parcel's market.
_STALE_MOI_FALLBACK_MONTHS = 6.0
_STALE_MOI_MULTIPLIER = 2.0
# A price cut is only meaningful past noise (rounding, list re-keys). Require a
# real markdown vs the prior snapshot before it counts as a distress signal.
_PRICE_CUT_MIN_PCT = 0.04   # >=4% off the prior list price
_PRICE_CUT_MIN_ABS = 2500.0  # and at least $2.5k absolute


# Court-verified divorce: the FCCMS (SC) / eCourts (NC) party-name match stored in
# raw['divorce']. Until 2026-09-20 nothing read it (only the deed-derived
# relationship_signal reached the score), so 5,523 collected hits ranked nothing.
# Measured on those hits: 47% of the newest party cases are >15 years old and
# only 13% are within 3 years, so a flat weight would score settled decades-old
# divorces as motivation. A recent filing means marital property is being
# divided or sold; an old one is history. The match is by name only (no DOB or
# address), so weights sit below the property-evidenced divorce (15), the same
# way incarceration (8) is a low-confidence name-only signal. Attorney and
# guardian-ad-litem rows are the owner's NAME appearing as counsel, not the
# owner being divorced (45 hits were attorney-only collisions); they never count.
_DIVORCE_PARTY_ROLES = frozenset({"plaintiff", "defendant", "petitioner", "respondent"})
_DIVORCE_RECENT_YEARS = 3.0
_DIVORCE_WINDOW_YEARS = 7.0
_DIVORCE_W_RECENT = 12
_DIVORCE_W_WINDOW = 6


def _divorce_signal(r: dict, today: Optional[date] = None, owner_name: Optional[str] = None) -> Optional[tuple[str, str, int]]:
    """(name, category, weight) from raw['divorce'], or None. A case row with no
    role is kept (role unknown); a row whose role is not a party role is skipped."""
    dv = r.get("divorce")
    if not isinstance(dv, dict) or not dv.get("case_count"):
        return None
    if owner_name and party_middle_conflict(
            owner_name, [c.get("parties") for c in (dv.get("cases") or []) if isinstance(c, dict)]):
        # Same first and last name as the court party but a DIFFERENT middle initial:
        # another person. 41% of comparable hits were like this (audit 2026-09-21).
        return None
    newest: Optional[date] = None
    for c in dv.get("cases") or []:
        if not isinstance(c, dict):
            continue
        role = str(c.get("role") or "").strip().lower()
        if role and role not in _DIVORCE_PARTY_ROLES:
            continue
        # to_date reads ISO and the US MM/DD/YYYY form the NC eCourts hits carry; the
        # ISO-only parse that stood here scored every NC hit 0 without saying so (F6).
        d = to_date(c.get("filed_date"))
        if d is None:
            continue
        if newest is None or d > newest:
            newest = d
    if newest is None:
        return None
    age_years = ((today or date.today()) - newest).days / 365.25
    if age_years <= _DIVORCE_RECENT_YEARS:
        return ("divorce", "LIFE_EVENT", _DIVORCE_W_RECENT)
    if age_years <= _DIVORCE_WINDOW_YEARS:
        return ("divorce", "LIFE_EVENT", _DIVORCE_W_WINDOW)
    return None


def _mls_fields(li: Listing) -> dict:
    """Pull the raw MLS lifecycle fields HomeHarvest persists, regardless of
    which scraper wrote them. homeharvest.py writes raw['homeharvest'];
    homeharvest_distressed.py writes raw['distressed']. Both carry the same
    mls_status / list_date / days_on_mls trio."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    for sub in ("homeharvest", "distressed"):
        block = raw.get(sub)
        if isinstance(block, dict) and (
            block.get("mls_status") is not None
            or block.get("days_on_mls") is not None
        ):
            return block
    return {}


# signal -> (category, weight). Categories: FINANCIAL / SALES / LEGAL /
# LIFE_EVENT / PROPERTY. Weight ~ motivation strength.
#
# FINANCIAL holds the whole ENFORCEMENT CHAIN (lis pendens, foreclosure sale, sheriff sale,
# court sale, upset bid, tax sale) so one event seen at two steps is one category. SALES is
# for market symptoms of a seller who could not sell (MLS withdrawn or stale, price cut,
# partition) plus REO and auction when no enforcement record sits beside them.
_LISTING_TYPE_SIGNAL = {
    "foreclosure_sale": ("FINANCIAL", 30),
    "lis_pendens": ("FINANCIAL", 28),
    "sheriff_sale": ("FINANCIAL", 25),   # was SALES: it is the execution of the foreclosure (F5)
    "tax_sale": ("FINANCIAL", 30),       # a SCHEDULED sale; a standing delinquent roll is 20 (F10)
    "tax_lien": ("FINANCIAL", 20),
    "auction": ("SALES", 18),
    "reo": ("SALES", 15),
    "distressed": ("PROPERTY", 10),
    "probate_notice": ("LIFE_EVENT", 20),
    # Listing types that reached the board and were never scored (F11). Weights follow the
    # nearest neighbour already on the scale.
    "divorce_notice": ("LIFE_EVENT", 15),     # same as the deed-evidenced divorce
    "estate_lead": ("LIFE_EVENT", 20),        # same as probate
    "hoa_sale": ("FINANCIAL", 25),            # a lien foreclosure with a sale date
    "bankruptcy": ("LEGAL", 18),              # only once the filing is tied to a property
    "elderly_disabled": ("LIFE_EVENT", 8),    # an attribute, weighted like senior_exemption
    "tax_sale_overage": ("FINANCIAL", 15),    # money owed to the former owner, a lower bar
}
_TAX_SALE_STANDING_ROLL_WEIGHT = 20   # a delinquent roll with no upcoming sale date = tax_lien (F10)

def evidence_of(ds: dict, signal: str) -> str:
    """Evidence class of one signal on a published `distress_stack`. `record` is the default and
    is NOT stored (the stack ships in full on the slim board and most signals are records), so an
    absent entry means record."""
    ev = ds.get("evidence") if isinstance(ds, dict) else None
    return (ev or {}).get(signal, REC)


#: name -> category, for readers that only have signal names (the lead-signals chip).
SIGNAL_CATEGORY = {
    "foreclosure_sale": "FINANCIAL", "lis_pendens": "FINANCIAL", "sheriff_sale": "FINANCIAL",
    "tax_sale": "FINANCIAL", "tax_lien": "FINANCIAL", "tax_lien_chronic": "FINANCIAL",
    "hoa_sale": "FINANCIAL", "tax_sale_overage": "FINANCIAL", "court_sale": "FINANCIAL",
    "upset_bid": "FINANCIAL", "recorded_debt": "FINANCIAL", "str_permit_lapsed": "FINANCIAL",
    "deferral_rollback": "FINANCIAL", "lien": "FINANCIAL", "builder_distress": "FINANCIAL",
    "auction": "SALES", "reo": "SALES", "mls_withdrawn_expired": "SALES",
    "stale_on_market": "SALES", "price_cut": "SALES", "partition": "SALES",
    "distressed": "PROPERTY", "code_enforcement": "PROPERTY", "distressed_condition": "PROPERTY",
    "storm_damage": "PROPERTY", "vacant_structure": "PROPERTY", "vacant_lot": "PROPERTY",
    "helene_restricted": "PROPERTY", "helene_unsafe": "PROPERTY", "helene_destroyed": "PROPERTY",
    "probate": "LIFE_EVENT", "probate_notice": "LIFE_EVENT", "probate_deed": "LIFE_EVENT",
    "estate_lead": "LIFE_EVENT", "divorce": "LIFE_EVENT", "divorce_notice": "LIFE_EVENT",
    "senior_exemption": "LIFE_EVENT", "elderly_disabled": "LIFE_EVENT", "life_estate": "LIFE_EVENT",
    "bankruptcy": "LEGAL", "bankruptcy_stay": "LEGAL", "incarceration": "LEGAL",
}

#: The enforcement chain. When any of these is present on a parcel, an REO or auction listing
#: on the same parcel is the OUTCOME of it (the bank now holds the property, or it is being
#: auctioned), not a second, independent kind of distress.
_ENFORCEMENT_CHAIN = frozenset({
    "foreclosure_sale", "lis_pendens", "court_sale", "sheriff_sale", "upset_bid",
    "hoa_sale", "tax_sale",
})
#: Signals that a bidder acts on (as opposed to an owner-outreach lead). Title risk matters
#: for these (F18) and they define the foreclosure lane (F7).
_BIDDER_SIGNALS = frozenset({"foreclosure_sale", "auction", "sheriff_sale", "hoa_sale",
                             "court_sale", "upset_bid"})
_LANE_KINDS = frozenset({"foreclosure_sale", "auction", "sheriff_sale", "court_sale", "upset_bid"})
_LANE_WINDOW_DAYS = 30
#: Types whose row carries a scheduled sale, so a sale date in the past means the event is over.
_SALE_LIFECYCLE_TYPES = frozenset({"foreclosure_sale", "sheriff_sale", "auction", "hoa_sale",
                                   "tax_sale", "lis_pendens"})
#: Days after the sale date at which an ended sale stops counting. NC keeps the upset-bid
#: window (NCGS 45-21.27, ~14 days from sale); SC has no upset bid, only the redemption
#: period for tax sales (handled separately), so a week covers confirmation paperwork.
_STALE_GRACE_DAYS = {"NC": 14, "SC": 7}
_STALE_GRACE_DEFAULT = 7
_SC_REDEMPTION_DAYS = 365   # SC Code 12-51-90: 12 months to redeem after a tax sale

# listing_type "distressed" is a catch-all: 31 sources emit it. Most are real evidence that the
# building or lot is in bad shape (code enforcement, condemned, vacant, storm damage, failing
# HUD inspection). These are not. Each is a record ABOUT the parcel or a program, not a sign
# the owner is under pressure, and giving them a PROPERTY category let them complete a stack
# of two (audit 2026-09-21: 645 of the 1,646 HOT leads were New Hanover demolition permits).
# They still ship on the board and in the dashboard as context; they just add no score.
# A parcel with real poor-condition evidence still gets PROPERTY through raw['distressed'].
_CONTEXT_ONLY_DISTRESSED_SOURCES = frozenset({
    # a demolition permit is the owner (or a developer) tearing a structure down, not a bad building
    "new_hanover_demolition_permits",
    # environmental and dam registries: regulated facilities, mostly commercial, not owner pressure
    "nc_ust_incidents", "sc_ust_registry", "nc_dam_safety", "nc_inactive_hazardous",
    "sc_des_brownfields", "sems", "acres",
    # federal contract and listing records with no condition evidence
    "hud_section8_contracts", "crexi_multifamily",
    # hazard-zone and program context
    "fema_disasters", "hendersonville_flood_zone_structures", "buncombe_hmgp_buyout",
})

# Sources whose rows carry a listing type that does not say what the record is (audit F10 and
# the A3 follow-up). The override decides the signal by the source's real meaning, so the
# rows already on the board score correctly without waiting for a re-scrape; the scrapers
# are retyped too, and once they are the type table above gives the same answer.
#   mcdowell_probate       a GIS owner-of-record flagged DECEASED: a probate/heir lead
#   greenville_mie_adverts a Master-in-Equity foreclosure advert: a foreclosure record
_SOURCE_OVERRIDE = {
    "mcdowell_probate": ("estate_lead", "LIFE_EVENT", 20, REC),
    "greenville_mie_adverts": ("lis_pendens", "FINANCIAL", 28, REC),
}

#: Sources whose `sale_date` is really a lien FILING date, not an auction. scripts/ingest_all.py
#: maps filing_date -> sale_date so a LiensNC row survives the dateless filter, and nc_sos_ucc
#: does the same with the UCC filing. The date says nothing about an event that can end, so no
#: lifecycle rule (sale passed, upset-bid window, days to event, foreclosure lane) may read it.
#: One set, shared by the scorer, the board-quality pass and the upset-bid enricher.
FILING_DATE_SOURCES = frozenset({"liensnc", "nc_sos_ucc"})
#: Listing types for which `sale_date` IS an event date. (`court_sale` is a status a docket
#: lookup stamps on these rows, see `sale_date_is_event`.)
SALE_EVENT_TYPES = frozenset({"foreclosure_sale", "auction", "sheriff_sale", "tax_sale",
                              "hoa_sale", "lis_pendens"})

#: Listing types the owner scopes to the 18 footprint counties (main._FLIP_LISTING_TYPES; a test pins
#: the two together). Every other type is a distressed lead, in scope anywhere in NC and SC.
FLIP_TYPES = frozenset({"foreclosure_sale", "auction", "sheriff_sale", "hoa_sale", "reo"})
#: raw['scope'] value the data-quality pass stamps on a flip whose county is outside the footprint
#: (owner rule 2026-09-15: "if its a flip, its only in the counties we talked about"). The row still
#: ships; the scorer takes it out of HOT and WARM.
OUT_OF_FOOTPRINT = "flip_outside_footprint"

#: Slugs whose 'distressed' rows come from listing-description keywords, not from a record.
_KEYWORD_DISTRESSED_SLUGS = frozenset({"distressed", "homeharvest_distressed", "homeharvest"})
_FLC_RE = re.compile(r"(^|_)flc(_|$)|forfeited_land")
#: A raw sale date some sources keep only inside their own block (the resolved Greenville
#: adverts null the structured sale_date on purpose, so they stay in the active pool).
_RAW_SALE_DATE_FALLBACKS = (("greenville_mie", "sale_date"),)


def _slugs(li: Listing) -> list[str]:
    return [p for p in str(li.source or "").split(".") if p]


def _ltype(li: Listing) -> str:
    lt = li.listing_type
    return lt.value if hasattr(lt, "value") else str(lt or "")


def sale_date_is_event(li: Listing) -> bool:
    """Is `li.sale_date` the date of a sale or auction? Only for a sale-type lead
    (SALE_EVENT_TYPES, or a row a court lookup stamped with a sale notice), and never for a
    source whose `sale_date` is a lien filing date (FILING_DATE_SOURCES). A LiensNC row typed
    tax_lien with a filing date 31 days back must not read as "sale passed"."""
    if any(p in FILING_DATE_SOURCES for p in _slugs(li)):
        return False
    if _ltype(li) in SALE_EVENT_TYPES:
        return True
    r = li.raw if isinstance(li.raw, dict) else {}
    return r.get("court_sale_status") in ("sale_noticed", "sold_unconfirmed")


def flip_outside_footprint(li: Listing) -> bool:
    """A stamped flip-type lead outside the 18 footprint counties. A stamp on a distressed-type
    row (a real tax delinquency in a coastal county, say) does not apply: distressed leads are in
    scope anywhere, so only a flip is capped."""
    r = li.raw if isinstance(li.raw, dict) else {}
    return r.get("scope") == OUT_OF_FOOTPRINT and _ltype(li) in FLIP_TYPES


def _context_only_distressed(li: Listing) -> bool:
    """True for a 'distressed'-typed record that says nothing about the owner's distress."""
    slug = str(li.source or "").rsplit(".", 1)[-1]
    # county-owned inventory: the owner is the county, there is no one to be motivated
    return slug in _CONTEXT_ONLY_DISTRESSED_SOURCES or slug.endswith("_county_owned")


def _is_liensnc(li: Listing) -> bool:
    """LiensNC rows are construction lien-agent filings (46,989 rows typed tax_lien): a notice
    that building work is under way, not owner distress. A tax_lien 20 plus the absentee bonus
    reached the WARM line by itself, which made this one source 52% of all WARM leads
    (audit A8). Context-only regardless of the listing type it carries."""
    return "liensnc" in _slugs(li)


def _is_county_owned_inventory(li: Listing) -> bool:
    """Forfeited-land / FLC inventory: the county already holds title, so the 'delinquent
    owner' the tax_sale weight assumes no longer exists (F10)."""
    return any(_FLC_RE.search(p) for p in _slugs(li))


def _mls_signals(li: Listing, prior_price: Optional[float] = None) -> list[tuple[str, str, int, str]]:
    """SALES-category signals derived from the MLS lifecycle fields HomeHarvest
    persists (mls_status / days_on_mls / list_price). These turn the raw realtor
    feed — which we previously only used for routing — into real distress tells:

      - stale_on_market: days_on_mls past ~2x local months-of-inventory. The
        market has passed on it at this price for twice the typical sell-through.
      - price_cut: current list price meaningfully below the prior snapshot's
        list price (seller capitulating). prior_price comes from score_board's
        cross-run index built off docs/listings.json. ONLY for a listing that has MLS
        fields: `opening_bid` is a list price on the realtor feeds but a tax balance on
        a tax-lien row, where a "cut" is the owner paying the bill down (F5).
      - withdrawn/expired: mls_status in expired/withdrawn/cancelled — couldn't
        sell on the open market, a classic pre-foreclosure / pre-pocket-sale tell.
    """
    sig: list[tuple[str, str, int, str]] = []
    mls = _mls_fields(li)
    if not mls:
        return sig

    status = str(mls.get("mls_status") or "").strip().lower()
    if status in _DEAD_MLS_STATUSES:
        sig.append(("mls_withdrawn_expired", "SALES", 18, REC))

    dom = mls.get("days_on_mls")
    try:
        dom = float(dom) if dom is not None else None
    except (TypeError, ValueError):
        dom = None
    if dom is not None:
        raw = li.raw if isinstance(li.raw, dict) else {}
        moi = (raw.get("market_velocity") or {}).get("moi")
        try:
            moi = float(moi) if moi is not None else _STALE_MOI_FALLBACK_MONTHS
        except (TypeError, ValueError):
            moi = _STALE_MOI_FALLBACK_MONTHS
        # moi is months-of-inventory; days threshold = 2x MOI expressed in days.
        stale_days = moi * 30.0 * _STALE_MOI_MULTIPLIER
        if dom >= stale_days:
            sig.append(("stale_on_market", "SALES", 14, REC))

    # price_cut — current list price (opening_bid carries list_price for the
    # realtor feeds) below the prior run's list price by a real margin.
    cur = li.opening_bid
    if prior_price and cur and cur > 0 and prior_price > 0 and cur < prior_price:
        drop = prior_price - cur
        if drop >= _PRICE_CUT_MIN_ABS and (drop / prior_price) >= _PRICE_CUT_MIN_PCT:
            sig.append(("price_cut", "SALES", 16, INF))

    return sig


# ---------------------------------------------------------------------------
# Dates, lifecycle and the foreclosure lane
# ---------------------------------------------------------------------------
def _sale_date_of(li: Listing, r: dict) -> Optional[date]:
    """The date of the sale or auction, or None: a filing date (LiensNC, nc_sos_ucc) and the
    date on a row that is not a sale-type lead are not event dates (`sale_date_is_event`)."""
    if any(p in FILING_DATE_SOURCES for p in _slugs(li)):
        return None
    d = to_date(li.sale_date) if sale_date_is_event(li) else None
    if d is not None:
        return d
    for key, field in _RAW_SALE_DATE_FALLBACKS:
        blk = r.get(key)
        if isinstance(blk, dict):
            d = to_date(blk.get(field))
            if d is not None:
                return d
    return None


def _upset_open(ub, today: date) -> bool:
    """An upset-bid block counts only while its window is open. The old test was
    truthiness of the dict, and the enricher closes a window by writing the SAME dict with
    `in_window: False`, so a window that closed 60 days ago still scored 22 (F2). The
    stored flag is frozen at build time (F15), so the deadline is re-read against `today`."""
    if not isinstance(ub, dict) or ub.get("in_window") is not True:
        return False
    dl = to_date(ub.get("deadline_iso"))
    return dl is None or dl >= today


def _upset_days(ub, today: date) -> Optional[int]:
    dl = to_date(ub.get("deadline_iso")) if isinstance(ub, dict) else None
    if dl is not None:
        return max(0, (dl - today).days)
    try:
        return max(0, int(ub.get("days_remaining")))
    except (AttributeError, TypeError, ValueError):
        return None


def _redemption_open(li: Listing, r: dict, sale: Optional[date], today: date) -> bool:
    """SC tax sale: the owner can still redeem until the redemption deadline. Use the stored
    deadline; when there is none, the statutory 12 months from the sale date."""
    rd = to_date(getattr(li, "redemption_deadline", None)) or to_date(r.get("redemption_deadline"))
    if rd is not None:
        return rd >= today
    if (li.state or "").upper() == "SC" and sale is not None:
        return sale + timedelta(days=_SC_REDEMPTION_DAYS) >= today
    return False


def _sale_status(li: Listing, r: dict, today: date, kind: str) -> tuple[bool, Optional[int], Optional[str]]:
    """(live, days_to_sale, stale_reason) for a row that carries a scheduled sale.

    live is False only when the sale date passed more than the state's grace ago AND no
    upset-bid window is open AND (for a tax sale) no redemption period is running."""
    sd = _sale_date_of(li, r)
    if sd is None:
        return True, None, None
    days = (sd - today).days
    if days >= 0:
        return True, days, None
    past = -days
    grace = _STALE_GRACE_DAYS.get((li.state or "").upper(), _STALE_GRACE_DEFAULT)
    if past <= grace:
        return True, days, None
    if _upset_open(r.get("upset_bid"), today):
        return True, days, None
    if kind == "tax_sale" and _redemption_open(li, r, sd, today):
        return True, days, None
    return False, days, f"{kind}: sale date {sd.isoformat()} passed {past} days ago, no open upset-bid window or redemption"


def _resolved_by_name(r: dict) -> bool:
    """The parcel on this row came from the name-to-property resolver. The resolver's own
    notes say uniqueness "came from who owns property, not from the name being distinctive"
    and that 2 of its first 6 Buncombe resolutions were another person."""
    rn = r.get("resolved_from_name")
    return isinstance(rn, dict) and rn.get("confidence") == "unique_match"


class _Collected:
    """Everything one listing contributes to its parcel group."""
    __slots__ = ("signals", "stale", "events", "stay")

    def __init__(self) -> None:
        self.signals: list[tuple[str, str, int, str]] = []    # (name, category, weight, evidence)
        self.stale: list[str] = []                             # reasons an ended sale was dropped
        self.events: list[tuple[str, int, bool]] = []          # (kind, days_to_event, in_foreclosure_lane)
        self.stay: Optional[dict] = None                       # a bankruptcy stay in force


def _stay_block(r: dict, today: date) -> Optional[dict]:
    """The bankruptcy stay, when one is in force. `enrichment_bankruptcy_stay` writes it
    once and never clears it; the bankruptcy TTL is the honest end date (a Chapter 7 stay is
    gone in months)."""
    st = r.get("bankruptcy_stay")
    if not isinstance(st, dict) or st.get("status") != "stayed":
        return None
    if bankruptcy_lapsed({"date_filed": st.get("date_filed"), "chapter": st.get("chapter")}, today):
        return None
    return {"status": "stayed", "chapter": st.get("chapter"),
            "resume_risk": st.get("resume_risk"), "case": st.get("case")}


def _collect(li: Listing, prior_price: Optional[float], today: date) -> _Collected:
    """The signals, lifecycle facts and lane events of ONE listing."""
    c = _Collected()
    sig = c.signals
    r = li.raw if isinstance(li.raw, dict) else {}
    lt = _ltype(li)
    slugs = _slugs(li)
    by_name = _resolved_by_name(r)

    # ---- the listing-type signal ---------------------------------------------------
    override = None
    if lt == "distressed":
        override = next((_SOURCE_OVERRIDE[s] for s in slugs if s in _SOURCE_OVERRIDE), None)
    skip_type = (
        lt not in _LISTING_TYPE_SIGNAL
        or _is_liensnc(li)                                            # A8: context-only
        or (lt == "distressed" and override is None and _context_only_distressed(li))
        or (lt == "bankruptcy" and not (li.parcel_id or li.street_address))   # F11: needs a property
    )
    if not skip_type:
        if override is not None:
            name, cat, w, ev = override
        else:
            name = lt
            cat, w = _LISTING_TYPE_SIGNAL[lt]
            # A Helene placard lead gets a severity-graded signal instead of the flat generic 'distressed' (10).
            hel = _helene_signal(li) if lt == "distressed" else None
            if hel:
                name, cat, w = hel
            ev = _type_evidence(lt, slugs, by_name, helene=bool(hel))
        if by_name and ev == REC:
            ev = NJ
        kind = name if name in _SALE_LIFECYCLE_TYPES else None
        live, days, why = (True, None, None)
        if kind:
            live, days, why = _sale_status(li, r, today, kind)
        if kind == "tax_sale":
            sd = _sale_date_of(li, r)
            upcoming = sd is not None and sd >= today
            if _is_county_owned_inventory(li) and not upcoming:
                live, why = True, None
                name = None                                            # F10: county holds title
            elif not upcoming:
                w = _TAX_SALE_STANDING_ROLL_WEIGHT                     # F10: a roll, not a sale
        if name is not None:
            if not live:
                c.stale.append(why)
            else:
                sig.append((name, cat, w, ev))
                if days is not None and days >= 0 and name in _LANE_KINDS and days <= _LANE_WINDOW_DAYS:
                    c.events.append((name, days, True))
                elif days is not None and days >= 0:
                    c.events.append((name, days, False))

    # ---- market symptoms (price_cut only when MLS fields exist, see _mls_signals) -----
    sig.extend(_mls_signals(li, prior_price=prior_price))

    # ---- court sale status -----------------------------------------------------------
    css = r.get("court_sale_status")
    if css in ("sale_noticed", "sold_unconfirmed"):
        live, days, why = _sale_status(li, r, today, "court_sale")
        if not live:
            c.stale.append(why)
        else:
            sig.append(("court_sale", "FINANCIAL", 25, REC))
            if css == "sale_noticed" and days is not None and 0 <= days <= _LANE_WINDOW_DAYS:
                c.events.append(("court_sale", days, True))

    # ---- upset bid: only while the window is open ---------------------------------------
    ub = r.get("upset_bid")
    if _upset_open(ub, today):
        published = isinstance(ub, dict) and ub.get("source") == "published"
        sig.append(("upset_bid", "FINANCIAL", 22, REC if published else INF))
        d = _upset_days(ub, today)
        if d is not None:
            c.events.append(("upset_bid", d, True))

    # ---- debt ------------------------------------------------------------------------
    _to = r.get("tax_owed")
    _real_tax = isinstance(_to, dict) and isinstance(_to.get("balance"), (int, float)) and _to["balance"] > 0
    if is_countable_debt(r.get("amount_owed")) or _real_tax:
        # A REAL debt only: an actual judgment / opening bid, or a real delinquent-tax balance
        # (raw['tax_owed']). An estimate (assessed value, an assumed two years of tax) is a
        # magnitude hint the amount_owed module itself labels "not debt". The waterfall can
        # pick an estimate over a real balance sitting beside it (645 New Hanover leads), so
        # the real balance is credited directly.
        sig.append(("recorded_debt", "FINANCIAL", 12, REC))
    pd = r.get("pickens_delinquent")
    if isinstance(pd, dict) and pd.get("chronic"):
        # Three or more separate delinquency publications is not an oversight. It used to be
        # a raw['distressed'] boolean read as PROPERTY, so one tax record completed a stack of
        # two (F5). It is the same fact as the tax lien, so it raises that category's weight.
        sig.append(("tax_lien_chronic", "FINANCIAL", 24, REC))
    if r.get("str_permit_lapsed"):
        # revoked/expired short-term-rental permit = lost rental income, a
        # financial motivation to sell (esp. where whole-house STRs are banned).
        sig.append(("str_permit_lapsed", "FINANCIAL", 12, REC))
    tr = r.get("tax_relief")
    if isinstance(tr, dict):
        if tr.get("kind") in ("elderly", "disabled", "blind"):
            # senior/disabled owner-occupant: equity-rich, motivated by health/
            # downsizing/estate transition.
            sig.append(("senior_exemption", "LIFE_EVENT", 8, REC))
        elif tr.get("kind") == "use_value_deferral":
            # present-use deferral = rollback lien due on sale (equity + urgency).
            sig.append(("deferral_rollback", "FINANCIAL", 6, REC))

    # ---- legal: name-only matches (F6) and the bankruptcy stay (F3) ---------------------
    bk = r.get("bankruptcy")
    stay = _stay_block(r, today)
    c.stay = stay
    if bk and not bankruptcy_lapsed(bk, today):
        sig.append(("bankruptcy", "LEGAL", 18, NO))
    if r.get("incarceration") and not custody_ended(r.get("jail_booking"), today):
        sig.append(("incarceration", "LEGAL", 8, NO))  # low-conf name-only signal

    # ---- life events -----------------------------------------------------------------
    if r.get("probate") or r.get("estate"):
        # an estate case record (notice or court file). It is name-based only when the lead's
        # PARCEL came from the name-to-property resolver (`by_name`), the case audit F6 names.
        sig.append(("probate", "LIFE_EVENT", 20, NJ if by_name else REC))
    # relationship-deed signals (probate / divorce / partition) tagged by
    # enrichment_relationship_deeds. Without this, in-place-tagged active
    # listings and ALL divorce signals never reached the score.
    rs = r.get("relationship_signal")
    if isinstance(rs, dict):
        rkind = rs.get("kind")
        if rkind == "probate":
            sig.append(("probate_deed", "LIFE_EVENT", 20, REC))
        elif rkind == "divorce":
            # zero-consideration quitclaim could be a gift, not a split — weaker
            kw = rs.get("keyword")
            w = 8 if kw == "zero_consideration_quitclaim" else 15
            sig.append(("divorce", "LIFE_EVENT", w, INF))
        elif rkind == "partition":
            # forced/judicial sale (usually already sold) — modest SALES signal
            sig.append(("partition", "SALES", 12, REC))
    # court-verified divorce (party-name match; recency-weighted, see _divorce_signal)
    dvs = _divorce_signal(r, today=today, owner_name=li.owner_name)
    if dvs:
        sig.append((*dvs, NO))

    # ---- property --------------------------------------------------------------------
    ce = r.get("code_enforcement")
    # F12: a code-enforcement block is written even when every case is closed
    # (`has_open` False), and nothing clears it. Count it only while a case is open. A block
    # that says every case is closed also ends the `condemned` flag that rode with it; a bare
    # `condemned` flag with no case record beside it still counts.
    if ce:
        if code_enforcement_open(ce, today):
            sig.append(("code_enforcement", "PROPERTY", 14, REC))
    elif r.get("condemned"):
        sig.append(("code_enforcement", "PROPERTY", 14, REC))
    if _distressed_flag_counts(li, r):
        sig.append(("distressed_condition", "PROPERTY", 8, REC))
    st = _storm_signal(r.get("storm_damage"))
    if st:
        sig.append((*st, REC))
    if _vacant_structure(r):
        sig.append(("vacant_structure", "PROPERTY", 12, REC))
    return c


def _type_evidence(lt: str, slugs: list[str], by_name: bool, *, helene: bool = False) -> str:
    """Evidence class of the listing-type signal."""
    if lt == "distressed":
        if helene:
            return REC
        return INF if any(s in _KEYWORD_DISTRESSED_SLUGS for s in slugs) else REC
    if lt in ("estate_lead", "divorce_notice", "bankruptcy"):
        return NJ      # a party record (obituary, summons, filing) matched to a property by name
    return REC


def _distressed_flag_counts(li: Listing, r: dict) -> bool:
    """raw['distressed'] as a PROPERTY source. Pickens set it for 3+ delinquency cycles, which
    is a tax fact and not physical distress (F5), so on that source it counts only when the
    assessor's condition code (raw['condition_cama']) says the same."""
    if not r.get("distressed"):
        return False
    if "pickens_delinquent_parcels" in _slugs(li):
        cc = r.get("condition_cama")
        return bool(isinstance(cc, dict) and cc.get("distressed"))
    return True


def _vacant_structure(r: dict) -> bool:
    """A code officer confirmed the structure vacant or boarded up (raw['vacancy'], the
    Hendersonville register). `vacant_lot` is undeveloped land, not a vacant house, and the
    USPS vacancy figure is ZIP-level context; neither is a seller-pressure signal."""
    for key in ("vacancy", "vacant"):
        v = r.get(key)
        if isinstance(v, dict) and (v.get("vacant") is True or v.get("boarded_up") is True):
            return True
    return False


def _signals_ev(li: Listing, prior_price: Optional[float] = None,
                today: Optional[date] = None) -> list[tuple[str, str, int, str]]:
    return _collect(li, prior_price, today or date.today()).signals


def _signals_for(li: Listing, prior_price: Optional[float] = None,
                 today: Optional[date] = None) -> list[tuple[str, str, int]]:
    """Return (signal_name, category, weight) for one listing's distress signals.

    prior_price (optional) is the same listing's list price from the previous
    run's snapshot, used only for the price_cut MLS signal. Defaults to None so
    single-listing callers (and tests) keep working unchanged. `today` (default
    date.today()) is the reference date for the lifecycle rules: an ended sale or a
    closed upset-bid window contributes nothing."""
    return [(n, cat, w) for n, cat, w, _ev in _signals_ev(li, prior_price, today)]


# ---------------------------------------------------------------------------
# The tier rule, in ONE place
# ---------------------------------------------------------------------------
def _tier(stack: int, score: float, eq_ok: bool, mailable: bool,
          absentee: bool, senior_survives: bool, *,
          eq_evidenced: Optional[bool] = None, record_linked: bool = True,
          non_attribute: bool = True) -> str:
    """The distressed-lane HOT/WARM/COLD rule.

    Extracted from `score_board` so `retract_equity_rank` can re-derive a tier
    after the equity term is pulled out from under it without restating the
    rule. A second hand-written copy of `stack >= 2 and eq_ok and ...` is how a
    retraction comes to disagree with the scorer it is retracting.

    The three keyword arguments are the evidence gates and default to "not a
    constraint", so a caller with only the six original arguments gets the original rule:
      eq_evidenced  HOT needs equity that rests on a recorded fact (F4). None = unknown = ok.
      record_linked HOT needs at least one signal that is a record about the property (F6).
      non_attribute the absentee route to WARM needs an event, not just an 8-point attribute
                    such as a senior exemption (F16).
    """
    hot_eq = eq_ok and (eq_evidenced is not False)
    if stack >= 2 and hot_eq and mailable and not senior_survives and record_linked:
        return "HOT"
    if stack >= 2 or (score >= 28 and eq_ok) or (absentee and stack >= 1 and score >= 20 and non_attribute):
        return "WARM"
    return "COLD"


def _derive_tier(ds: dict, eq_ok: bool, eq_evidenced: Optional[bool]) -> str:
    """The FULL tier of a published `distress_stack`: the base rule plus the lane, the caps
    and the bidder title gates. `score_board` and `retract_equity_rank` both come through
    here, so a retraction cannot disagree with the scorer it retracts. Reads only fields the
    stack itself carries; an older stack that lacks the newer fields gets the older behaviour."""
    if ds.get("scope_capped"):
        return "COLD"                              # a flip outside the 18 footprint counties
    if ds.get("stale_reason"):
        return "COLD"                              # F2: the event is over
    senior = bool(ds.get("surviving_senior_debt_risk"))
    bidder = bool(ds.get("bidder"))
    title = ds.get("title_status")
    stayed = bool(ds.get("stay"))
    if ds.get("lane") == "foreclosure":
        # F7: a bidder's lead. Days to sale and title risk decide it, not a mailable owner or equity.
        if senior:
            return "COLD"                          # F18: a junior lien leaves the senior debt with the buyer
        linked = ds.get("record_linked", True)     # a sale whose parcel came from a name search is not one to drive to
        return "HOT" if (title == "clean" and not stayed and linked) else "WARM"
    tier = _tier(ds.get("stack") or 0, ds.get("score") or 0, eq_ok,
                 bool(ds.get("contactable")), bool(ds.get("absentee")), senior,
                 eq_evidenced=eq_evidenced, record_linked=ds.get("record_linked", True),
                 non_attribute=ds.get("non_attribute", True))
    if bidder:
        if senior:
            return "COLD"                          # F18
        if tier == "HOT" and title != "clean":
            tier = "WARM"                          # F18: unknown or missing title risk is not HOT-eligible
    if stayed and tier == "HOT":
        tier = "WARM"                              # F3: a stayed foreclosure will not be sold on schedule
    return tier


def retract_equity_rank(li: Listing) -> bool:
    """Pull the equity term out of an already-published ``distress_stack``.

    The ranking half of a LATE retraction. `enrichment_board_qa` can only learn
    that a county appraisal is stamped across hundreds of parcels once every
    lead is in memory, which is after `score_board` has already banded and
    tiered them. Withholding the equity FIGURE at that point is not enough: the
    tier computed from it is still sitting on the card, and a HOT tier is an
    instruction to spend money contacting an owner.

    Copies the stack before mutating. (`score_board` now gives each listing its own copy
    too, but this stays defensive: the stack may have been shared by an older run.)
    Returns True when a band was actually removed.
    """
    raw = li.raw if isinstance(li.raw, dict) else None
    if not raw:
        return False
    ds = raw.get("distress_stack")
    if not isinstance(ds, dict) or ds.get("equity_band") is None:
        return False
    ds = dict(ds)
    ds["equity_band"] = None
    ds["equity_retracted"] = True
    ds["equity_evidenced"] = False
    ds["tier"] = _derive_tier(ds, False, False)
    raw["distress_stack"] = ds
    return True


def _equity_info(li: Listing) -> tuple[Optional[str], bool]:
    """(band, evidenced): the seller's REAL equity (ARV − payoff − liens) banded, and whether
    the payoff behind it is a recorded fact (F4).

    Falls back to flip-ROI only when equity could not be computed; the ROI fallback is
    never evidenced (it is ARV minus costs over cash in, not a fact about the debt).

    ARV TRUST GATE — the ranking half of the same decision enrichment_equity
    makes about the figure. BOTH inputs to this function are ARV-derived:
    `equity.pct` is (ARV − payoff − liens) / ARV, and the `roi_pct` fallback is
    ARV minus every cost over cash in. So on a valuation the board will not bid
    off, this function has nothing left to read that is worth ranking on, and it
    says so by returning None.

    IT IS NOT ENOUGH that enrichment_equity now withholds the figure. This runs
    over whatever raw['equity'] is on the Listing, and on a board carried over
    from a run that predates that gate — or one patched by a script that
    refreshes the valuation without re-running the equity engine — the stale
    figure is still sitting there. A gate that only holds when the writer ran
    first is not a gate; the check is repeated here, off the same
    `grading.arv_trust`, so the two cannot drift.

    WHAT RETURNING None COSTS, and why that is the right price. The band feeds the HOT
    gate (`eq_ok`), one WARM route (`score >= 28 and eq_ok`), and the published
    `distress_stack.equity_band`. None closes exactly those. A contradicted lead can
    therefore no longer reach HOT, which is correct, because HOT is an instruction to spend money
    contacting an owner, and equity is the ONLY term in that rule that comes from the
    valuation. What it does NOT close is `stack >= 2` or the absentee route: those are built
    from probate, tax delinquency, code enforcement and divorce records, which are
    independent of the ARV and are not impugned by a bad comp set.

    TWO CASES `arv_trust` CANNOT SEE, both added after it:

      * A calc block with no `arv_expected`, no `arv_withheld` and no flags classifies "ok".
        The valuation still ran and came back empty, and any equity on such a lead was
        computed off market_value / tax_value x 1.25 by `enrichment_equity._arv`. Same test,
        same function: `enrichment_equity.valuation_ran_without_arv`.
      * The `withheld` MARKER: the only signal that survives a late CROSS-ROW retraction
        (`enrichment_board_qa` retracts equity on a county appraisal stamped across hundreds
        of parcels).
    """
    raw = li.raw or {}
    calc = raw.get("calc") or {}
    if isinstance(calc, dict):
        if arv_trust(calc.get("arv_flags"), calc.get("arv_expected"),
                     calc.get("arv_withheld")) in ARV_TRUST_BLOCKS_DERIVED:
            return None, False
    if valuation_ran_without_arv(li):
        return None, False
    eqb = raw.get("equity") or {}
    if eqb.get("withheld"):
        return None, False
    pct = eqb.get("pct")
    if pct is not None:
        evidenced = eqb["evidenced"] if isinstance(eqb.get("evidenced"), bool) else equity_is_evidenced(eqb)
        if pct >= 0.40:
            return "high", evidenced
        if pct >= 0.15:
            return "med", evidenced
        return "low", evidenced   # includes underwater (negative pct)
    roi = (raw.get("calc") or {}).get("roi_pct")
    if roi is None:
        return None, False
    if roi >= 50:
        return "high", False
    if roi >= 20:
        return "med", False
    return "low", False


def _equity_band(li: Listing) -> Optional[str]:
    """Seller's REAL equity band (high / med / low / None). See `_equity_info`, which also
    says whether the equity is evidenced."""
    return _equity_info(li)[0]


_PARCEL_JUNK = re.compile(r"[^A-Za-z0-9]")


def _parcel_key(li: Listing, suspicious_keys: frozenset = frozenset()) -> str:
    """Group key: state + county + parcel. The old key was state + parcel, so the same
    number in two counties fused unrelated properties, and so did every placeholder ("N/A",
    "0", "TBD", "UNKNOWN": one key per state). An id with no digit, under four characters
    after stripping, or all zeros is not a parcel number and ungroups (F9).

    suspicious_keys (audit 2026-09-22): dedupe.suspicious_parcel_keys(listings) computed once
    per score_board call, a set of Listing.dedupe_key() strings. A parcel id can look real (14
    digits, passes every check above) and still not describe one property -- a lien-agent
    filing batch citing a subdivision's master-tract PIN for every lot before the county
    splits it (Pender County 3208-90-5620-0000 covered 216 distinct addresses in one run).
    Grouping by it would stack 216 unrelated properties' distress signals into one. Checked via
    li.dedupe_key() itself (not a reconstruction of this function's own "p:..." format, which
    differs cosmetically) so the two can never drift out of sync."""
    if suspicious_keys and li.dedupe_key() in suspicious_keys:
        return f"id:{id(li)}"  # a real-looking id shared by too many real addresses: ungroup
    pid = _PARCEL_JUNK.sub("", (li.parcel_id or "")).lower()
    if len(pid) >= 4 and any(ch.isdigit() for ch in pid) and set(pid) != {"0"}:
        county = re.sub(r"\s+county$", "", (li.county or "").strip(), flags=re.I).lower() or "?"
        return f"p:{(li.state or '').upper()}:{county}:{pid}"
    return f"id:{id(li)}"  # ungrouped


# ---------------------------------------------------------------------------
# Prior-run price index (price_cut)
# ---------------------------------------------------------------------------
_CHUNK = 1 << 20   # read size of the streaming snapshot reader


def _stream_json_rows(path: Path) -> Iterator[dict]:
    """Yield the rows of a JSON array file (plain or .gz) one at a time. The old reader did
    `json.loads(path.read_text())` on a 1.1 GB file, which holds the text and the parsed
    board at once (audit F17); this holds one 1 MB chunk."""
    dec = json.JSONDecoder()
    buf = ""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        while True:
            chunk = f.read(_CHUNK)
            if chunk:
                buf += chunk
            elif not buf.strip():
                return
            i = 0
            while True:
                while i < len(buf) and buf[i] in " \n\r\t,[":
                    i += 1
                if i >= len(buf) or buf[i] == "]":
                    break
                try:
                    obj, j = dec.raw_decode(buf, i)
                except ValueError:
                    break                      # the object continues in the next chunk
                yield obj
                i = j
            buf = buf[i:]
            if not chunk:
                # a clean file ends at the closing bracket; anything else is a truncated or
                # corrupt snapshot, which must not read as "no prior prices"
                if buf.strip() not in ("", "]"):
                    raise ValueError("snapshot ends mid-row (truncated or corrupt JSON)")
                return


def _prior_price_index(previous_path: Optional[Path]) -> dict[str, float]:
    """Build {dedupe_key: prior list_price} from the previous run's snapshot.

    Reuses the same docs/listings.json snapshot enrichment_pulled_sales.py reads
    (the cross-run diff). We only need each prior listing's identity + list
    price, so this is a lightweight STREAMING read (no whole-file parse and no full Listing
    hydration). Keyed by Listing.dedupe_key() so it matches the current run's listings.

    The slim `.gz` sibling of the snapshot carries every field used here and is far smaller,
    so it is preferred when it exists. A read error is logged and counted in `LAST_STATS`
    (price_cut is silently off without it), never swallowed without a trace.
    """
    if previous_path is None:
        previous_path = Path("docs/listings.json")
    previous_path = Path(previous_path)
    gz = previous_path if str(previous_path).endswith(".gz") else Path(str(previous_path) + ".gz")
    src = gz if gz.exists() else previous_path
    if not src.exists():
        return {}

    from .models import ListingType, PropertyKind
    lt_map = {lt.value: lt for lt in ListingType}
    pk_map = {pk.value: pk for pk in PropertyKind}

    idx: dict[str, float] = {}
    try:
        for d in _stream_json_rows(src):
            if not isinstance(d, dict):
                continue
            price = d.get("opening_bid")
            try:
                price = float(price) if price is not None else None
            except (TypeError, ValueError):
                price = None
            if not price or price <= 0:
                continue
            # Minimal Listing for a stable dedupe_key (same fields the key uses).
            try:
                li = Listing(
                    source=d.get("source") or "prior",
                    source_url=d.get("source_url") or "prior",
                    listing_type=lt_map.get(d.get("listing_type") or "unknown", ListingType.UNKNOWN),
                    property_kind=pk_map.get(d.get("property_kind") or "unknown", PropertyKind.UNKNOWN),
                    street_address=d.get("street_address"),
                    city=d.get("city"),
                    state=d.get("state"),
                    zip_code=d.get("zip_code"),
                    county=d.get("county"),
                    parcel_id=d.get("parcel_id"),
                    case_number=d.get("case_number"),
                )
            except Exception:
                continue
            key = li.dedupe_key()
            # Keep the highest prior price on key collision: a real markdown should
            # measure against the listing's earlier (higher) ask, not a stale low.
            if key not in idx or price > idx[key]:
                idx[key] = price
    except Exception as exc:  # noqa: BLE001
        log.warning("distress_score.prior_index_failed", path=str(src), error=str(exc)[:200])
        LAST_STATS["price_index_error"] = str(exc)[:200]
        return {}
    return idx


# ---------------------------------------------------------------------------
# Scoring one parcel group
# ---------------------------------------------------------------------------
def _copy_ds(ds: dict) -> dict:
    """A copy of a stack that shares no mutable child with the original. The stack is flat
    apart from lists (`categories`, `signals`) and small flat dicts (`evidence`, `stay`), so
    one level of copying is enough; `copy.deepcopy` did the same job at four times the cost on
    170,000 rows."""
    return {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
            for k, v in ds.items()}


def _as_today(today) -> date:
    if today is None:
        return date.today()
    return today.date() if isinstance(today, datetime) else today


def _score_group(active: list[Listing], prior_prices: dict, today: date) -> dict:
    """The `distress_stack` of one parcel group (every listing on it, sold ones excluded)."""
    sigs: list[tuple[str, str, int, str]] = []
    stale: list[str] = []
    events: list[tuple[str, int, bool]] = []
    stay: Optional[dict] = None
    for li in active:
        prior_price = prior_prices.get(li.dedupe_key()) if prior_prices else None
        col = _collect(li, prior_price, today)
        sigs.extend(col.signals)
        stale.extend(col.stale)
        events.extend(col.events)
        stay = stay or col.stay

    names = {n for n, _c, _w, _e in sigs}
    # F5: an REO or auction listing on a parcel that also has an enforcement record is the
    # OUTCOME of that enforcement, not a second kind of distress.
    if names & _ENFORCEMENT_CHAIN:
        sigs = [(n, "FINANCIAL" if (n in ("reo", "auction") and c == "SALES") else c, w, e)
                for n, c, w, e in sigs]
    # F3: a stayed foreclosure is not evidence of a second, independent distress.
    if stay:
        sigs = [s for s in sigs if s[0] != "bankruptcy"]
        names = {n for n, _c, _w, _e in sigs}

    # ---- categories, evidence and the stack --------------------------------------------
    by_cat: dict[str, list[tuple[str, int, str]]] = {}
    for n, c, w, e in sigs:
        by_cat.setdefault(c, []).append((n, w, e))
    categories = sorted(by_cat)
    cat_w: dict[str, int] = {}
    cat_ev: dict[str, str] = {}
    for c, items in by_cat.items():
        top = max(items, key=lambda it: (it[1], _EVIDENCE_ORDER[it[2]]))
        cat_w[c] = top[1]
        if top[2] in _WEAK_EVIDENCE:
            # the signal that SUPPLIES the score is a name match: a low-weight record beside it
            # (an 8-point exemption beside a 20-point name-joined probate) must not launder it
            cat_ev[c] = top[2]
        else:
            # otherwise the category is as strong as its best non-name signal: a derived upset-bid
            # window (inferred, 22) beside the tax lien it belongs to (record, 20) is a record
            cat_ev[c] = max((it[2] for it in items if it[2] not in _WEAK_EVIDENCE),
                            key=_EVIDENCE_ORDER.__getitem__)
    strong = [c for c in categories if cat_ev[c] == REC]
    mid = [c for c in categories if cat_ev[c] == INF]
    weak = [c for c in categories if cat_ev[c] in _WEAK_EVIDENCE]
    counted = strong + mid
    # A name-based category may LENGTHEN a stack of two record-linked categories but never
    # complete one: foreclosure + a jail-roster name collision is one real event and a coincidence.
    if len(strong) >= _NAME_BASED_MIN_RECORD_CATEGORIES:
        counted += weak
        uncounted: list[str] = []
    else:
        uncounted = list(weak)
    stack = len(counted) if counted else (1 if categories else 0)
    stack_capped = None
    # F5: a stack needs at least one category of real weight; two 8-point attributes are not a stack
    if stack >= 2 and max(cat_w[c] for c in counted) < 15:
        stack, stack_capped = 1, "no category weight >= 15"
    score = sum(cat_w.values())
    signals = sorted(names)
    record_linked = bool(strong)
    non_attribute = any(w >= 12 for _n, _c, w, _e in sigs)

    # ---- equity (best across the group), contactability, senior lien -----------------------
    # `_equity_info` returns None on a contradicted/withheld ARV, so a parcel group whose every
    # listing carries a bad valuation contributes no band and cannot satisfy `eq_ok`. If ONE
    # listing has a clean valuation and another does not, the clean one supplies the band.
    infos = [_equity_info(li) for li in active]
    pick = (next((i for i in infos if i[0] in ("high", "med") and i[1]), None)
            or next((i for i in infos if i[0] in ("high", "med")), None)
            or next((i for i in infos if i[0]), (None, False)))
    eq, eq_evidenced = pick
    # owner_mailing is usually a dict but some sources emit a bare string (F14): mailing_dict
    # turns that into {"mailing": text}, so those leads are contactable and can reach HOT.
    _oms = [mailing_dict((li.raw or {}).get("owner_mailing")) for li in active]
    absentee = any(om.get("absentee") for om in _oms)
    oos = any(om.get("out_of_state") for om in _oms)
    mailable = any(om.get("mailing") for om in _oms)
    if absentee:
        score += 8
    if oos:
        score += 4
    # Title-wipeout trap: a junior-lien / HOA / credit-union / individual
    # foreclosure where a senior bank mortgage likely SURVIVES the sale is a
    # bidding trap, not a clean acquisition: penalize it and keep it out of HOT.
    trs = [tr for li in active for tr in [(li.raw or {}).get("title_risk")] if isinstance(tr, dict)]
    senior_survives = any(tr.get("surviving_senior_debt_risk") for tr in trs)
    if senior_survives:
        score -= 20
    bidder = bool(names & _BIDDER_SIGNALS)
    if senior_survives:
        title_status = "junior_risk"
    elif any(tr.get("kind") == "senior_lien_foreclosure" for tr in trs):
        title_status = "clean"
    elif trs:
        title_status = "unknown"
    else:
        title_status = "missing"

    # ---- lane, days to event, stale ---------------------------------------------------------
    lane_days = [d for _k, d, in_lane in events if in_lane]
    lane = "foreclosure" if lane_days else "distressed"
    all_days = [d for _k, d, _l in events]
    days_to_event = min(lane_days) if lane_days else (min(all_days) if all_days else None)
    live_chain = bool(names & _ENFORCEMENT_CHAIN)
    stale_reason = "; ".join(sorted(set(stale))) if (stale and not live_chain) else None

    ds: dict = {"tier": "COLD", "stack": stack, "categories": categories,
                "signals": signals, "score": round(score),
                "equity_band": eq, "absentee": absentee, "out_of_state": oos,
                "contactable": mailable, "surviving_senior_debt_risk": senior_survives}
    # Additive fields. Kept compact on purpose (distress_stack ships in full on the slim
    # board): each appears only when it differs from the default a reader assumes.
    ev_map = {n: e for n, _c, _w, e in sigs if e != REC}
    if ev_map:
        ds["evidence"] = ev_map
    if sigs and not record_linked:
        ds["record_linked"] = False
    if eq is not None:
        ds["equity_evidenced"] = bool(eq_evidenced)
    if sigs and not non_attribute:
        ds["non_attribute"] = False
    if lane == "foreclosure":
        ds["lane"] = "foreclosure"
    if days_to_event is not None:
        ds["days_to_event"] = days_to_event
    if bidder:
        ds["bidder"] = True
        ds["title_status"] = title_status
    if uncounted:
        ds["uncounted_categories"] = uncounted
    if stack_capped:
        ds["stack_capped"] = stack_capped
    if stale_reason:
        ds["stale_reason"] = stale_reason
    if stay:
        ds["stay"] = stay
    ds["tier"] = _derive_tier(ds, eq in ("high", "med"), bool(eq_evidenced) if eq else None)
    return ds


def score_board(listings: list[Listing], previous_path: Optional[Path] = None,
                today: Optional[date] = None) -> dict:
    """Compute and attach raw['distress_stack'] to each listing. Returns a
    tier histogram.

    previous_path points at the prior run's docs/listings.json snapshot (same
    file enrichment_pulled_sales.py diffs). It powers the price_cut MLS signal
    by comparing each listing's list price against its prior-run ask; it is only read when
    some listing actually has MLS fields. Defaults to docs/listings.json; pass a path (or a
    non-existent one) to control it. `today` (default date.today()) is the reference date
    for the lifecycle rules and is injectable for tests.

    Raises ScoreBoardError when any group could not be scored (after scoring the rest)."""
    today = _as_today(today)
    LAST_STATS.clear()
    # group by parcel. A parcel id shared by many distinct addresses (a subdivision's lots all
    # citing one pre-split tract PIN in a lien-agent filing batch) is not a real grouping key
    # and is ungrouped by _parcel_key (audit 2026-09-22, Pender County 3208-90-5620-0000).
    from .dedupe import suspicious_parcel_keys
    suspicious = suspicious_parcel_keys(listings)
    LAST_STATS["suspicious_parcel_ids"] = len(suspicious)
    groups: dict[str, list[Listing]] = {}
    for li in listings:
        groups.setdefault(_parcel_key(li, suspicious), []).append(li)

    # price_cut is gated to MLS listings, so the (expensive) prior-run read is skipped when none exist
    prior_prices = _prior_price_index(previous_path) if any(_mls_fields(li) for li in listings) else {}

    hist = {"HOT": 0, "WARM": 0, "COLD": 0}
    counts = {"lane_foreclosure": 0, "stale_capped": 0, "stay_capped": 0, "scope_capped": 0, "errors": 0}
    failures: list[tuple[str, str]] = []
    for key, group in groups.items():
        # exclude sold/closed properties from active scoring
        active_all = [li for li in group if not (li.raw or {}).get("sold_confirmed")]
        if not active_all:
            for li in group:
                if isinstance(li.raw, dict):
                    li.raw.pop("distress_stack", None)
            continue
        # A stamped flip outside the footprint contributes NOTHING to its parcel and gets a visible
        # COLD stack with the reason. A distressed-type lead on the same parcel is scored on its own.
        capped = [li for li in active_all if flip_outside_footprint(li)]
        active = [li for li in active_all if not flip_outside_footprint(li)]
        for li in capped:
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["distress_stack"] = {
                "tier": "COLD", "stack": 0, "categories": [], "signals": [], "score": 0,
                "equity_band": None, "absentee": False, "out_of_state": False, "contactable": False,
                "surviving_senior_debt_risk": False, "scope_capped": OUT_OF_FOOTPRINT}
        counts["scope_capped"] += len(capped)
        if not active:
            hist["COLD"] += 1
            continue
        try:
            ds = _score_group(active, prior_prices, today)
        except Exception as exc:  # noqa: BLE001  - one bad group must not hide the rest, or pass silently
            counts["errors"] += 1
            if len(failures) < 5:
                failures.append((str(active[0].source), f"{type(exc).__name__}: {exc}"[:200]))
            log.error("distress_score.group_failed", source=active[0].source, error=str(exc)[:200])
            for li in active:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                # never leave the PREVIOUS run's tier standing on a row we could not score
                li.raw["distress_stack"] = {"tier": "COLD", "stack": 0, "categories": [], "signals": [],
                                            "score": 0, "score_error": f"{type(exc).__name__}"}
            continue
        for li in active:
            if not isinstance(li.raw, dict):
                li.raw = {}
            # each listing gets its OWN copy: a shared dict meant enrich_board_quality's
            # in-place downrank on one sibling re-tiered every other listing on the parcel (F9)
            li.raw["distress_stack"] = _copy_ds(ds)
        hist[ds["tier"]] += 1
        counts["lane_foreclosure"] += ds.get("lane") == "foreclosure"
        counts["stale_capped"] += bool(ds.get("stale_reason"))
        counts["stay_capped"] += bool(ds.get("stay"))
    LAST_STATS.update(counts)
    LAST_STATS["tiers"] = dict(hist)
    log.info("distress_score.done", **hist, **counts)
    if counts["errors"]:
        raise ScoreBoardError(
            f"score_board: {counts['errors']} parcel group(s) failed to score; first: {failures[0]}",
            failed=counts["errors"], hist=hist, failures=failures)
    return hist
