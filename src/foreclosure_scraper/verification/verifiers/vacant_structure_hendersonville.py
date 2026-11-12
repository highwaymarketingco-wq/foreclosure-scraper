"""vacant_structure, City of Hendersonville NC: is the structure still on the city's vacant-
structures register, and does the register still say it is vacant (not occupied, not gone)?

Evolved from docs/validation_2026-10-02/scripts/validate_code_enforcement.py (FINDINGS.md
section 3, Finding B: of 11 sampled register rows, 27.3% "still vacant", 54.5% "now occupied",
18.2% "dropped off"). The layer and the cell readers are the scraper's own
(counties_nc.hendersonville_vacant_structures: LAYER, _tri, _date_in, _clean, FORBIDDEN_FIELDS).

THE SOURCE (live-checked 2026-10-06): VACANT_STRUCTURES_7_24_24/FeatureServer/0, anonymous
ArcGIS Online, 52 rows, loaded ONCE per sweep run (_arcgis_layer.layer_for: metadata, count,
one page). It is a FROZEN snapshot: editingInfo.dataLastEditDate is 2024-07-24 (the date in the
layer's name), so what it says about a structure is what a code officer recorded by then. Every
verdict carries `layer_data_last_edit` and `register_age_days` so nobody reads a confirmed as a
2026 site visit. Columns read: FID, DATE, ADDRESS, OCCUPIED, BOARDED_UP, CONDEMNED,
DELINQUENT_TAX, NOTES. NOTES is read for ONE purpose and never kept: classify_demolition() turns
it into "completed" / "planned" / "negated" / none in memory (the cell is run through the
scraper's scrub_contact first: owners' emails and officers' phone numbers sit in free text), and
only that word reaches the evidence. Never requested: OWNER, MAILING_ADDRESS, MAIL_CITY, ST, ZIP,
PHONE__, EMAIL, column19.

FINDINGS' 54.5% "now occupied" counted every OCCUPIED value other than NO as occupied,
blanks included; live, the column is NO on 26 of 52 rows, blank on 24, YES on 1 and UNKNOWN on 1.
So this verifier keeps a blank apart: it is no observation, not an occupied one.

WHICH ROWS (applies). NC Henderson rows whose raw['code_enforcement'] or raw['vacancy'] is the
register's block (source "hendersonville_vacant_structures_register"), whatever row carries it.

MATCHING. The row's street address, models._normalize_addr, against the register's ADDRESS
(the scraper writes the register's ADDRESS as the row's address; the first register row of an
address wins, as in the scraper, unless the board's block names a listed DATE that picks one of
several). The match is on the whole normalized address, house number included, so 112 and 120 N
Blue Ridge Ave are two rows (FID 4 and FID 7) and can never be taken for each other.

THE BOARD'S COPY OF THE REGISTER IS NEVER A SOURCE (v2). The board block's `demolished`,
`notes` and the rest were read by the scraper from a register row, and a merge can put another
row's block on a row: 112 N Blue Ridge Ave carried the 'pulling demo permit to tear this down'
note of 120 N Blue Ridge Ave (FID 7) while its own row (FID 4) holds a person's name and no date,
and the house stands (county building value 13,900). Everything the verdict uses comes from the
register row THIS verifier matched, in the live layer. The block is only compared with it:
`board_block_agrees` False says the block belongs to another row, `board_demolished_flag_ignored`
says its demolished flag found no support in the matched row.

DEMOLITION (v2). The scraper's keyword (any "demo") read "NO IMMEDIATE PLANS TO DEMO AND
REBUILD" as a demolition (618 Ferncliff Ln). classify_demolition() is negation- and tense-aware:
  completed   a demolition word in a completed sense (demolished, demoed, razed, torn down,
              bulldozed, "house removed", "demolition complete") that is not under a negation or
              a plan ("to be", "will", "pending", "scheduled", "permit", "no", "not"...);
  planned     a demolition word that is only a plan, a permit or an order ("pulling demo permit
              to tear this down");
  negated     a demolition word under a negation ("no immediate plans to demo").
A demolition is decisive (stale, "structure_demolished") only when a completed note (NOTES, or
DELINQUENT_TAX's "DEMOED") says so, OR a note mentions demolition in any other way and the county
parcel layer agrees (Henderson County parcels FeatureServer, by the row's PIN else by address:
TOTAL_BLDG_VALUE_ASSESSED is 0 and HEATED_AREA is zero or absent). One weak source alone is
`unconfirmed` ("demolition_not_established"): a plan or a negation the county layer does not back
(618 Ferncliff Ln: the county still carries building value 1,200 and 630 sq ft), or the county layer
alone for a row whose notes never mention demolition. The county layer is asked only for those
rows. Its owner and mailing columns are never requested.

OCCUPANCY (v2). OCCUPIED=YES is a code officer's observation on the day it was written. From a
layer last edited more than OCCUPANCY_MAX_LAYER_AGE_DAYS (365) ago, on a row not itself dated
within the last OCCUPANCY_MAX_ROW_AGE_DAYS (180), it is too old to end a vacancy claim:
`unconfirmed` ("register_occupancy_too_old"; 902 Sylvan Blvd: a row listed 2024-04-25 in a layer
last edited 2024-07-24 was the only basis of its stale). A confirmed (the register records vacancy)
is unchanged: it never takes a signal out of the score and every verdict carries the register's age.

VERDICTS (core.py's meanings):
  confirmed    on the register and the register records vacancy: OCCUPIED NO, or BOARDED_UP
               yes/partial, or CONDEMNED yes/a date (the scraper's _tri: an affirmative cell).
  stale        on the register but marked OCCUPIED YES by a register fresh enough to say so
               ("marked_occupied"); or the structure is gone ("structure_demolished", see
               DEMOLITION: a completed note, or a mention the county layer backs); or not on the
               register any more although the register has been edited since the row was first
               seen ("dropped_off_register").
  refuted      not on the register at this address, and the register has NOT been edited since
               the row was first seen ("not_on_register"): the entry cannot have been removed
               since, so the block on this row is about another address (a merged row).
  unconfirmed  the layer failed, came back empty or incomplete; the row has no numbered
               address; the register row records nothing about occupancy (OCCUPIED blank or
               UNKNOWN, not boarded, not condemned: "occupancy_not_recorded"); the occupancy is
               too old ("register_occupancy_too_old"); or a demolition is mentioned and not
               established ("demolition_not_established").

GOVERNS "vacant_structure:hendersonville_vacant_structures_register" and
"code_enforcement:hendersonville_vacant_structures_register": partial rules (core.qualifiers)
read in distress_score._collect and enrichment_lead_signals._facet_signals. A refuted or stale
verdict ends the vacant_structure credit of the register's raw['vacancy'] block and the
code_enforcement credit of the register's raw['code_enforcement'] block only, never another
source's block on the same parcel. raw['distressed'] / raw['condemned'] are bare flags with no
provenance and are not governed.

TTL 30 days, retry 7: the register is frozen; a republished layer is picked up within a month.

EVIDENCE (whitelisted fields, no names, no contact data, no free text): the layer URL,
fetched_at, layer count, last data edit and age, the register FID and listed DATE and its age,
occupied / boarded_up / condemned as true/false/null, the condemned date, demolished and its
basis, the demolition note's kind, the county layer's building value / heated area / land class
/ snapshot date and how it was matched, whether the board's block agrees with the matched row,
reason. ROW_SUMMARY_EXCLUDE drops owner_name from the ledger row summary (it is the register's
OWNER).
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Optional

from ..core import VerificationResult, parse_ts, result, utc_now
from . import _arcgis_layer as agl

SIGNAL = "vacant_structure"
VERSION = "v2"         # v2 (2026-10-06): notes only from the matched live row (never the board's
                       # copy), negation- and tense-aware demolition, a demolition mention needs
                       # the county parcel layer to agree, an occupancy value from a frozen
                       # register is too old to end a vacancy claim
TTL_DAYS = 30
RETRY_DAYS = 7
REG_SOURCE = "hendersonville_vacant_structures_register"
SOURCE = "City of Hendersonville vacant-structures register (services1.arcgis.com)"
GOVERNS = (f"vacant_structure:{REG_SOURCE}", f"code_enforcement:{REG_SOURCE}")
ROW_SUMMARY_EXCLUDE = ("owner_name",)

#: The only columns requested. NOTES is free text read in memory for classify_demolition() and
#: never stored or published (see the docstring); no owner, address, phone or email column.
OUT_FIELDS = "FID,DATE,ADDRESS,OCCUPIED,BOARDED_UP,CONDEMNED,DELINQUENT_TAX,NOTES"
NEVER_FIELDS = ("OWNER", "MAILING_ADDRESS", "MAIL_CITY", "ST", "ZIP", "PHONE__", "EMAIL",
                "column19")
ORDER_BY = "FID ASC"

#: an OCCUPIED value is too old to end a vacancy claim when the layer was last edited more than
#: this many days ago AND the row itself is not dated within the other limit
OCCUPANCY_MAX_LAYER_AGE_DAYS = 365
OCCUPANCY_MAX_ROW_AGE_DAYS = 180

#: Henderson County's parcel layer (parcel_cache.PARCEL_LAYERS["Henderson"]["url"], pinned by a
#: test). Only these columns: never PROPERTY_OWNER, OWNER_MAIL_*.
COUNTY_LAYER = "https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/FeatureServer/0"
COUNTY_FIELDS = "PIN,LOCATION_ADDR,LAND_CLASS,TOTAL_BLDG_VALUE_ASSESSED,HEATED_AREA,AUT_SNAPSHOT_DATE"

_NAME = __name__.rsplit(".", 1)[-1]


def _scraper():
    from ...scrapers.counties_nc import hendersonville_vacant_structures
    return hendersonville_vacant_structures


def layer() -> str:
    return _scraper().LAYER


def _fields_are_safe() -> bool:
    asked = set(OUT_FIELDS.split(","))
    return not (asked & set(NEVER_FIELDS)) and not (asked & set(_scraper().FORBIDDEN_FIELDS))


# ---------------------------------------------------------------------------
# demolition in a register note (pure)
# ---------------------------------------------------------------------------

_CLAUSE = re.compile(r"[;,\n]+|\s+-\s+|\.\s+")
_TOKEN = re.compile(r"[A-Za-z']+")
#: any demolition vocabulary; a hit that is not "completed" below is a plan, a permit or a negation
_MENTION = re.compile(
    r"\bdemo\b|\bdemos\b|\bdemol\w*|\bdemoed\b|\bdemo'd\b|\braz(?:e|ed|es|ing)\b|"
    r"\btear(?:ing)?\s+(?:this|it|that|the\s+\w+)?\s*down\b|\btorn\s+down\b|\btore\s+down\b|"
    r"\bbulldoz\w*|\bknock(?:ed|ing)?\s+down\b", re.I)
#: a demolition word in a COMPLETED sense
_COMPLETED = re.compile(
    r"\b(?:demolished|demoed|demo'd|razed|torn\s+down|tore\s+down|bulldozed)\b|"
    r"\b(?:house|home|structure|building|dwelling|trailer|mobile\s+home|garage|shed|residence)"
    r"\s+(?:was\s+|has\s+been\s+|been\s+)?removed\b|"
    r"\b(?:demolition|demo)\s+(?:is\s+)?(?:complete|completed|done|finished)\b", re.I)
_NEGATION = frozenset({"no", "not", "never", "none", "without", "nor", "yet", "isn't", "isnt",
                       "wasn't", "wasnt", "hasn't", "hasnt", "won't", "wont", "can't", "cant",
                       "cannot"})
_PLAN = frozenset({"be", "being", "will", "would", "plan", "plans", "planned", "planning",
                   "intend", "intends", "intended", "pending", "scheduled", "schedule", "soon",
                   "need", "needs", "needed", "should", "must", "may", "might", "could", "if",
                   "when", "until", "awaiting", "waiting", "ordered", "order", "request",
                   "requested", "want", "wants", "wanted", "permit", "permits", "proposed",
                   "expected", "future", "upcoming", "going", "gonna"})
_WINDOW = 5     # words before a hit that can turn it into a negation or a plan


def classify_demolition(*texts: Any) -> Optional[str]:
    """What a register note says about demolition, tense- and negation-aware:
    "completed" (a demolition word in a completed sense, under no negation and no plan),
    "planned" (a demolition word that is only a plan, a permit or an order: "pulling demo permit to
    tear this down"), "negated" (under a negation: "no immediate plans to demo and rebuild"),
    or None (no demolition vocabulary at all). completed beats planned beats negated.
    A clause (split on ; , - and sentence ends) is read alone, so a "not occupied" before a dash
    never negates a "demolished" after it. Pure; the text is never returned."""
    kinds: set[str] = set()
    for text in texts:
        for clause in _CLAUSE.split(str(text or "")):
            done = [(m.start(), m.end()) for m in _COMPLETED.finditer(clause)]
            for m in _MENTION.finditer(clause):
                before = [w.lower() for w in _TOKEN.findall(clause[:m.start()])][-_WINDOW:]
                is_done = any(a <= m.start() < b or m.start() <= a < m.end() for a, b in done)
                if before and _NEGATION & set(before):
                    kinds.add("negated")
                elif is_done and not (_PLAN & set(before)):
                    kinds.add("completed")
                else:
                    kinds.add("planned")
            # a completed phrase the mention regex does not cover ("house removed")
            for a, b in done:
                if not _MENTION.search(clause[a:b]):
                    before = [w.lower() for w in _TOKEN.findall(clause[:a])][-_WINDOW:]
                    if _NEGATION & set(before):
                        kinds.add("negated")
                    elif _PLAN & set(before):
                        kinds.add("planned")
                    else:
                        kinds.add("completed")
    for k in ("completed", "planned", "negated"):
        if k in kinds:
            return k
    return None


# ---------------------------------------------------------------------------
# the county parcel layer (the second source for a demolition)
# ---------------------------------------------------------------------------

_DIRS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST"}


def house_street(addr: Any) -> Optional[tuple[str, str]]:
    """('112', 'BLUE') for '112 N BLUE RIDGE AVE': the house number and the first street word
    after any direction, which is what the register's '618 FERNCLIFF' and the county's '618
    FERNCLIFF LN' share. None without a real house number."""
    w = re.sub(r"[^A-Z0-9 ]", " ", str(addr or "").upper()).split()
    if len(w) < 2 or not w[0].isdigit() or int(w[0]) <= 0:
        return None
    rest = [x for x in w[1:] if x not in _DIRS]
    return (str(int(w[0])), rest[0]) if rest else None


def county_url_pin(pin: str) -> str:
    return agl.query_url(COUNTY_LAYER, {"where": f"PIN='{pin}'", "outFields": COUNTY_FIELDS,
                                        "returnGeometry": "false"})


def county_url_address(addr: str) -> str:
    a = re.sub(r"\s+", " ", str(addr or "").strip().upper()).replace("'", "''")
    return agl.query_url(COUNTY_LAYER, {"where": f"LOCATION_ADDR LIKE '{a}%'",
                                        "outFields": COUNTY_FIELDS, "returnGeometry": "false"})


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def county_view(a: dict) -> dict:
    """The county parcel's building facts: building value, heated area, land class, snapshot date
    and `no_building` (an explicit 0 building value and no heated area: the county layer says
    there is nothing standing; an absent building value is no answer, not a zero)."""
    bv, ha = _num(a.get("TOTAL_BLDG_VALUE_ASSESSED")), _num(a.get("HEATED_AREA"))
    out = {"building_value": bv, "heated_area": ha,
           "land_class": str(a.get("LAND_CLASS") or "").strip() or None,
           "snapshot": agl.epoch_date(a.get("AUT_SNAPSHOT_DATE")),
           "no_building": bv == 0 and not ha}
    return out


async def county_parcel(row: dict, reg_address: str, client) -> Optional[dict]:
    """The county parcel of the register row, from the row's PIN else the register's address, only
    when the parcel's own situs is that address (house number and street): the board's PIN can be
    a resolver's mistake. {'matched_by', **county_view} or None (no answer, error, ambiguous)."""
    want = house_street(reg_address)
    tries = []
    pin = re.sub(r"\D", "", str(row.get("parcel_id") or ""))
    if len(pin) == 10:
        tries.append(("pin", county_url_pin(pin)))
    if want:
        tries.append(("address", county_url_address(reg_address)))
    for how, url in tries:
        try:
            data = await client.get_json(url)
        except Exception:  # noqa: BLE001 - no county answer is not a verdict
            continue
        if not isinstance(data, dict) or data.get("error"):
            continue
        feats = [(f or {}).get("attributes") or {} for f in data.get("features") or []]
        feats = [a for a in feats if house_street(a.get("LOCATION_ADDR")) == want]
        if len(feats) == 1:
            return {"matched_by": how, **county_view(feats[0])}
    return None


# ---------------------------------------------------------------------------
# which rows
# ---------------------------------------------------------------------------

def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _blocks(row: dict) -> tuple[Optional[dict], Optional[dict]]:
    raw = _raw(row)
    ce, vac = raw.get("code_enforcement"), raw.get("vacancy")
    ce = ce if isinstance(ce, dict) and ce.get("source") == REG_SOURCE else None
    vac = vac if isinstance(vac, dict) and vac.get("source") == REG_SOURCE else None
    return ce, vac


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "NC":
        return False
    if str(row.get("county") or "").strip().lower() != "henderson":
        return False
    ce, vac = _blocks(row)
    return bool(ce or vac)


# ---------------------------------------------------------------------------
# the register, indexed once per snapshot
# ---------------------------------------------------------------------------

def _addr(v: Any) -> Optional[str]:
    from ...models import _normalize_addr
    from ..core import _house_numbered
    a = _normalize_addr(v) if v else None
    return a if a and _house_numbered(a) else None


def _index(snap: agl.LayerSnapshot) -> dict:
    idx = snap.cache.get("register")
    if idx is None:
        idx = defaultdict(list)
        for a in snap.rows:
            ad = _addr(_scraper()._clean(a.get("ADDRESS")))
            if ad:
                idx[ad].append(a)
        snap.cache["register"] = idx
    return idx


def register_view(a: dict) -> dict:
    s = _scraper()
    out = {"register_fid": a.get("FID"), "listed_date": s._date_in(a.get("DATE")),
           "occupied": s._tri(a.get("OCCUPIED")), "boarded_up": s._tri(a.get("BOARDED_UP")),
           "condemned": s._tri(a.get("CONDEMNED")),
           "condemned_date": s._date_in(a.get("CONDEMNED"))}
    return out


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, {k: v for k, v in ev.items() if v is not None or k in (
        "occupied", "boarded_up", "condemned")}, source=SOURCE, version=VERSION, verifier=_NAME)


def _clean_note(v: Any) -> str:
    """A register free-text cell with emails and phone numbers stripped (the scraper's own
    scrub_contact) before anything reads it. In memory only: never returned, never stored."""
    sc = _scraper()
    return sc.scrub_contact(sc._clean(v)) or ""


def _pick(hits: list[dict], ce: Optional[dict]) -> dict:
    """The register row for an address: the only one, else (several rows share the address) the
    one whose listed DATE is the board block's, else the first, as the scraper does."""
    if len(hits) > 1 and ce and ce.get("listed_date"):
        for a in hits:
            if register_view(a)["listed_date"] == ce.get("listed_date"):
                return a
    return hits[0]


def block_agrees(ce: Optional[dict], view: dict) -> Optional[bool]:
    """Does the board's code_enforcement block carry the matched register row's own facts (listed
    date, occupied, boarded up, condemned)? False = the block was read off another register row
    and merged onto this one (112 N Blue Ridge Ave wore 120's). None = nothing to compare."""
    if not ce:
        return None
    checks = [ce.get(k) == view.get(k) for k in ("listed_date", "occupied", "boarded_up", "condemned")
              if k in ce]
    return all(checks) if checks else None


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    ce, _vac = _blocks(row)
    ev: dict[str, Any] = {}
    if not _fields_are_safe():                       # belt and braces: never fetch a personal column
        ev["reason"] = "unsafe_out_fields"
        return _res("unconfirmed", ev)
    snap = await agl.layer_for(client, layer(), out_fields=OUT_FIELDS, order_by=ORDER_BY)
    ev.update(snap.evidence())
    now = (datetime(today.year, today.month, today.day, tzinfo=timezone.utc) if today
           else utc_now())
    last = parse_ts(snap.data_last_edit)
    if last is not None:
        ev["register_age_days"] = (now - last).days
    if not snap.complete:
        ev["reason"] = snap.health
        return _res("unconfirmed", ev)
    addr = _addr(row.get("street_address"))
    if not addr:
        ev["reason"] = "no_numbered_address"
        return _res("unconfirmed", ev)

    hits = _index(snap).get(addr) or []
    if not hits:
        first_seen = parse_ts(row.get("first_seen"))
        ev["row_first_seen"] = row.get("first_seen") or None
        if last is not None and first_seen is not None and last <= first_seen:
            ev["reason"] = "not_on_register"
            return _res("refuted", ev)
        ev["reason"] = "dropped_off_register"
        return _res("stale", ev)

    a = _pick(hits, ce)
    ev["matched_by"] = "address"
    view = register_view(a)
    ev.update(view)
    if len(hits) > 1:
        ev["register_rows_at_address"] = len(hits)
    listed = parse_ts(view["listed_date"])
    if listed is not None:
        ev["register_row_age_days"] = (now - listed).days

    # Everything below reads the MATCHED register row only. The board's block is compared with it
    # and never used: a merge can put another row's block (and its "demolished") on this one.
    agrees = block_agrees(ce, view)
    if agrees is False:
        ev["board_block_agrees"] = False
    kind = classify_demolition(_clean_note(a.get("NOTES")), _clean_note(a.get("DELINQUENT_TAX")))
    board_flag = bool(ce and ce.get("demolished") is True)
    if board_flag and kind is None:
        ev["board_demolished_flag_ignored"] = True
    if kind == "completed":
        ev["demolished"] = True
        ev["demolished_basis"] = ("register DELINQUENT_TAX"
                                  if classify_demolition(_clean_note(a.get("DELINQUENT_TAX"))) == "completed"
                                  else "register NOTES")
        ev["demolition_note"] = kind
        ev["reason"] = "structure_demolished"
        return _res("stale", ev)

    county = None
    if kind or board_flag:
        # a mention that does not say "done", or a board copy that claims a demolition the live
        # row does not: the county parcel layer is the second source
        county = await county_parcel(row, _scraper()._clean(a.get("ADDRESS")) or "", client)
        if county:
            ev.update({"county_" + k: v for k, v in county.items() if k != "no_building"})
    if kind:
        ev["demolition_note"] = kind
        if county and county["no_building"]:
            ev["demolished"] = True
            ev["demolished_basis"] = "county parcel layer and register NOTES"
            ev["reason"] = "structure_demolished"
            return _res("stale", ev)
        ev["reason"] = "demolition_not_established"
        return _res("unconfirmed", ev)
    if county and county["no_building"]:
        # the board says demolished, the matched row never mentions it, and only the county layer
        # shows an empty parcel: one weak source alone
        ev["reason"] = "demolition_not_established"
        return _res("unconfirmed", ev)

    if ev["occupied"] is True:
        layer_age = ev.get("register_age_days")
        row_age = ev.get("register_row_age_days")
        too_old = ((layer_age is None or layer_age > OCCUPANCY_MAX_LAYER_AGE_DAYS)
                   and not (row_age is not None and row_age <= OCCUPANCY_MAX_ROW_AGE_DAYS))
        if too_old:
            ev["reason"] = "register_occupancy_too_old"
            return _res("unconfirmed", ev)
        ev["reason"] = "marked_occupied"
        return _res("stale", ev)
    if ev["occupied"] is False or ev["boarded_up"] or ev["condemned"]:
        return _res("confirmed", ev)
    ev["reason"] = "occupancy_not_recorded"
    return _res("unconfirmed", ev)
