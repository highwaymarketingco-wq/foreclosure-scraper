"""vacant_structure (condemned), the 718 Greenwood SC `condemned` rows tagged
`counties_generic.arcgis_distress.greenwood_cama_condemned`: does Greenwood County's own CAMA
assessor roll still rate this parcel's building condition in the same severe tier
("Badly Worn"/"Worn Out") that originally earned it `raw['condemned']=True`?

WHY THIS EXISTS: see condemned_adl.py's docstring for the full 2026-11-16 round-6 gap-matrix
investigation this is part of. 718 rows is the single largest county slice found this pass --
bigger than any other producer in scope -- and needed its own, careful look before building
anything: `arcgis_distress_layers.py`'s own `greenwood_cama_condemned` Layer entry no longer sets
`condemned=True` as of 2026-10-09 (its own code comment: "greenwood_cama_condemned did [stamp
condemned] until 2026-10-09: a condition rating, see condition_rating"; today `lay.condemned is
None` and `lay.condition_rating is True` instead, which writes `raw['condition_cama']`/
`raw['distressed']` only). The 718 board rows are therefore all LEGACY writes from before that
narrowing, every one of them a real, decided design choice by this project's own prior work, not
a bug to re-litigate.

SO WHAT IS THIS MODULE ACTUALLY VERIFYING? Not "is this structure condemned" as a fresh claim --
this project has already decided a bare CAMA condition rating does not, by itself, support that
word going forward, and this module does not second-guess that. What it DOES check, honestly,
is narrower and still real: the SAME underlying physical-condition fact (`ConditionText`) that
the scraper read at the time it wrote `raw['condemned']=True` is still live, still queryable, and
still either backs or no longer backs that specific historical claim. Live-verified 2026-11-16 on
five real sampled rows (PINs 6913-876-159/6913-831-220/6923-507-677/6923-654-657/6923-169-651,
each already carrying `raw['condition_cama']['condition']=="Badly Worn"`): every one STILL reads
`ConditionText="Badly Worn"` today on a direct re-query by PIN -- this is current, re-checkable
assessor data, not an orphaned snapshot (contrast the code_enforcement gap-sweep's own Guilford
finding, a producer DISABLED for genuinely frozen data, correctly left unverified rather than
forced). A `stale` verdict here means the SAME fact the legacy flag rested on no longer holds
(the county reassessed it better) -- never a claim that the PROJECT's own current condemned
determination has changed.

THE SEVERE TIER VOCABULARY (live-surveyed 2026-11-16, 2,000-row sample of the live service's own
`ConditionText` column): `Average` 1,122, blank 807, `Badly Worn` 21, `Badly Worn/Average` 23,
`Good` 19, `Average/Good` 5, `Very Good` 1, `Worn Out` 1, `Worn Out/Badly Worn` 1. `Badly Worn`
and `Worn Out` are the two severe tiers (a multi-structure parcel's CDUC-style "/"-joined value,
e.g. "Badly Worn/Average", carries a card in each -- the SAME tier presence rule, never a stricter
exact-string match that would wrongly miss it). Matches every live-sampled legacy row's own value
exactly ("Badly Worn" on all five checked); no row sampled this pass carried "Worn Out" to
confirm that half of the pair directly, so it is included on the vocabulary survey's own evidence
(the live service's field alias -- "Condition Text" -- and the scraper's historical comment
calling the appraiser's rating "Worn Out" for the strongest tier), not claimed as separately
row-verified.

A TARGETED PER-ROW QUERY, never `_arcgis_layer.py`'s whole-layer cache: this service's `CAMA/
MapServer/9` is Greenwood County's entire improved-parcel roll -- 39,554 rows, live-counted
2026-11-16 -- far past what a per-sweep-run whole-layer load should pull just to answer a
handful of per-row queries (the same reasoning condemned_spartanburg.py's docstring gives for
its own, even bigger, county roll). A single `where=PIN='<id>'` query, by the row's own
`parcel_id` (`arcgis_distress_layers.py`'s own `_to_listing()`: `parcel = a.get(lay.situs) if
not situs else ...` -- here the Layer's own PIN field, carried straight onto the Listing),
falling back to a `SiteAddress` exact match when a row carries no parcel id.

VERDICTS: confirmed (the matched card's `ConditionText` still contains "Badly Worn" or
"Worn Out"), stale (the parcel is still on the roll but its condition no longer does), refuted
(the service answered and this parcel id / address has no card on the roll at all), unconfirmed
(the service could not be asked, or the row carries neither a parcel id nor a street address).

TTL 30 days, retry 7 -- matches condemned_spartanburg.py's/vacant_structure_hendersonville.py's
cadence for this identical shape of claim; an assessor condition rating changes on
reinspection, not daily.

GOVERNS: deliberately omitted, same reasoning as condemned_adl.py's docstring.

EVIDENCE: the matched parcel id or address and the live `ConditionText` string -- no field
beyond `PIN`/`SiteAddress`/`ConditionText` (never `Owner`/`MailAddress`/`MailCityState`/
`YearBuilt`/`TaxValue_Total`, every one of which the LAYER itself requests but this claim does
not need).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _arcgis_layer as agl

SIGNAL = "vacant_structure"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
ROW_SOURCE = "counties_generic.arcgis_distress.greenwood_cama_condemned"
SOURCE = "Greenwood County CAMA (greenwoodsc.gov Operational_Layers/CAMA/9)"
SERVICE_URL = "https://www.greenwoodsc.gov/arcgis/rest/services/Operational_Layers/CAMA/MapServer/9"
FIELDS = "PIN,SiteAddress,ConditionText"
_SEVERE_TIERS = ("badly worn", "worn out")
MAX_CASES_IN_EVIDENCE = 8
_NAME = __name__.rsplit(".", 1)[-1]


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def applies(row: dict) -> bool:
    return bool(_raw(row).get("condemned")) and row.get("source") == ROW_SOURCE


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


def _esc(v: str) -> str:
    return v.replace("'", "''")


def _is_severe(cond: Any) -> bool:
    c = str(cond or "").strip().lower()
    return any(tier in c for tier in _SEVERE_TIERS)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    ev: dict[str, Any] = {}
    pid = row.get("parcel_id")
    addr = row.get("street_address")
    if pid:
        where = f"PIN='{_esc(str(pid))}'"
        ev["matched_by"] = "parcel_id"
    elif addr:
        where = f"UPPER(SiteAddress)=UPPER('{_esc(str(addr))}')"
        ev["matched_by"] = "street_address"
    else:
        ev["reason"] = "no_identity"
        return _res("unconfirmed", ev)

    feats = await agl.query_one(client, SERVICE_URL, where=where, out_fields=FIELDS)
    if feats is None:
        ev["reason"] = "endpoint_unreachable"
        return _res("unconfirmed", ev)
    if not feats:
        ev["reason"] = "no_parcel_on_roll"
        return _res("refuted", ev)

    cards = []
    any_severe = False
    for a in feats[:MAX_CASES_IN_EVIDENCE]:
        cond = a.get("ConditionText")
        if _is_severe(cond):
            any_severe = True
        cards.append({"condition_text": cond or None})
    ev["cards"] = cards
    ev["cards_matched"] = len(feats)
    if any_severe:
        return _res("confirmed", ev)
    ev["reason"] = "condition_no_longer_severe"
    return _res("stale", ev)
