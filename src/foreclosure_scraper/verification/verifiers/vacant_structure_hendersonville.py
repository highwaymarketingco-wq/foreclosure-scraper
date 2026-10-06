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
DELINQUENT_TAX (the last only for "DEMOED"). Never requested: OWNER, MAILING_ADDRESS, MAIL_CITY,
ST, ZIP, PHONE__, EMAIL, column19, NOTES (owners' emails sit in NOTES; the ledger is PUBLIC).

FINDINGS' 54.5% "now occupied" counted every OCCUPIED value other than NO as occupied,
blanks included; live, the column is NO on 26 of 52 rows, blank on 24, YES on 1 and UNKNOWN on 1.
So this verifier keeps a blank apart: it is no observation, not an occupied one.

WHICH ROWS (applies). NC Henderson rows whose raw['code_enforcement'] or raw['vacancy'] is the
register's block (source "hendersonville_vacant_structures_register"), whatever row carries it.

MATCHING. The row's street address, models._normalize_addr, against the register's ADDRESS
(the scraper writes the register's ADDRESS as the row's address; the first register row of an
address wins, as in the scraper).

VERDICTS (core.py's meanings):
  confirmed    on the register and the register records vacancy: OCCUPIED NO, or BOARDED_UP
               yes/partial, or CONDEMNED yes/a date (the scraper's _tri: an affirmative cell).
  stale        on the register but marked OCCUPIED YES ("marked_occupied"); or the structure is
               gone ("structure_demolished": the register's DELINQUENT_TAX says DEMOED, or the
               board block's own `demolished`, which the scraper read from the register's NOTES
               that this verifier does not fetch); or not on the register any more although the
               register has been edited since the row was first seen ("dropped_off_register").
  refuted      not on the register at this address, and the register has NOT been edited since
               the row was first seen ("not_on_register"): the entry cannot have been removed
               since, so the block on this row is about another address (a merged row).
  unconfirmed  the layer failed, came back empty or incomplete; the row has no numbered
               address; or the register row records nothing about occupancy (OCCUPIED blank or
               UNKNOWN, not boarded, not condemned: "occupancy_not_recorded").

GOVERNS "vacant_structure:hendersonville_vacant_structures_register" and
"code_enforcement:hendersonville_vacant_structures_register": partial rules (core.qualifiers)
read in distress_score._collect and enrichment_lead_signals._facet_signals. A refuted or stale
verdict ends the vacant_structure credit of the register's raw['vacancy'] block and the
code_enforcement credit of the register's raw['code_enforcement'] block only, never another
source's block on the same parcel. raw['distressed'] / raw['condemned'] are bare flags with no
provenance and are not governed.

TTL 30 days, retry 7: the register is frozen; a republished layer is picked up within a month.

EVIDENCE (whitelisted fields, no names, no contact data, no free text): the layer URL,
fetched_at, layer count, last data edit and age, the register FID and listed DATE, occupied /
boarded_up / condemned as true/false/null, the condemned date, demolished and its basis, reason.
ROW_SUMMARY_EXCLUDE drops owner_name from the ledger row summary (it is the register's OWNER).
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from ..core import VerificationResult, parse_ts, result, utc_now
from . import _arcgis_layer as agl

SIGNAL = "vacant_structure"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
REG_SOURCE = "hendersonville_vacant_structures_register"
SOURCE = "City of Hendersonville vacant-structures register (services1.arcgis.com)"
GOVERNS = (f"vacant_structure:{REG_SOURCE}", f"code_enforcement:{REG_SOURCE}")
ROW_SUMMARY_EXCLUDE = ("owner_name",)

#: The only columns requested. Never a personal or free-text column (see the docstring).
OUT_FIELDS = "FID,DATE,ADDRESS,OCCUPIED,BOARDED_UP,CONDEMNED,DELINQUENT_TAX"
NEVER_FIELDS = ("OWNER", "MAILING_ADDRESS", "MAIL_CITY", "ST", "ZIP", "PHONE__", "EMAIL",
                "column19", "NOTES")
ORDER_BY = "FID ASC"
_DEMO = re.compile(r"\bdemo(?:ed|lished|lition)?\b", re.I)

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


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    ce, _vac = _blocks(row)
    ev: dict[str, Any] = {}
    if not _fields_are_safe():                       # belt and braces: never fetch a personal column
        ev["reason"] = "unsafe_out_fields"
        return _res("unconfirmed", ev)
    snap = await agl.layer_for(client, layer(), out_fields=OUT_FIELDS, order_by=ORDER_BY)
    ev.update(snap.evidence())
    last = parse_ts(snap.data_last_edit)
    if last is not None:
        ev["register_age_days"] = (utc_now() - last).days
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

    a = hits[0]
    ev["matched_by"] = "address"
    ev.update(register_view(a))
    if len(hits) > 1:
        ev["register_rows_at_address"] = len(hits)
    demo_tax = bool(_DEMO.search(str(a.get("DELINQUENT_TAX") or "")))
    demo_board = bool(ce and ce.get("demolished") is True)
    if demo_tax or demo_board:
        ev["demolished"] = True
        ev["demolished_basis"] = ("register DELINQUENT_TAX" if demo_tax
                                  else "board block (register NOTES, not fetched)")
        ev["reason"] = "structure_demolished"
        return _res("stale", ev)
    if ev["occupied"] is True:
        ev["reason"] = "marked_occupied"
        return _res("stale", ev)
    if ev["occupied"] is False or ev["boarded_up"] or ev["condemned"]:
        return _res("confirmed", ev)
    ev["reason"] = "occupancy_not_recorded"
    return _res("unconfirmed", ev)
