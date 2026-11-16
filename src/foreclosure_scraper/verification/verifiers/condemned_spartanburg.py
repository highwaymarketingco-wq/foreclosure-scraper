"""vacant_structure (condemned), scrapers/counties_sc/spartanburg_condemned.py (source
"counties_sc.spartanburg_condemned"): does Spartanburg County's own CAMA assessor roll still
rate this parcel's building condition "DL" (DELAPITATED), the scraper's own condemned-equivalent
tier?

WHY THIS EXISTS: see condemned_adl.py's docstring for the full 2026-11-16 round-6 gap-matrix
investigation this is part of. This is the SINGLE LARGEST real producer in scope: 713 of
Spartanburg's 928 `condemned` rows, live-sampled 2026-11-16 (the remainder splits across
spartanburg_city_condemned.py's PDF-based "Master Condemnation List" -- see NOT COVERED below --
and a handful of small-tail merge artifacts this investigation did not chase: 3 unrelated
arcgis_distress_layers.py layers whose own `process` is tax/redevelopment/storm_damage, not
condemned, that nonetheless carry a handful of `raw['condemned']=True` rows each, almost
certainly from a MERGE with a spartanburg_condemned/spartanburg_city_condemned hit on the same
parcel rather than from their own logic -- the same bare-flag merge ambiguity
condemned_charlotte.py's docstring documents at length for Charlotte).

THE SOURCE (live-checked 2026-11-16): maps.spartanburgcounty.org/.../GIS/CAMA_Parcels/
FeatureServer/0 -- a plain, anonymous, no-login ArcGIS FeatureServer, the SAME service the
scraper itself already reads. `ConditionFactor` is a free-text field; 'DL' is the scraper's own
condemned-equivalent tier (`_CONDEMNED_COND`), 'VP' (VERY POOR) a weaker tier it keeps as
`distressed` only, never `condemned`. This module checks the SAME single tier the scraper does,
never a broader or narrower rule.

A TARGETED PER-ROW QUERY, never `_arcgis_layer.py`'s whole-layer cache: this service's `CAMA_
Parcels/0` is Spartanburg County's ENTIRE parcel roll -- 183,465 rows, live-counted 2026-11-16 --
two orders of magnitude past what a per-sweep-run whole-layer load should pull just to answer a
handful of per-row queries (contrast condemned_rocky_mount.py's two 124/92-row survey layers,
small enough to cache whole). A single `where=GISParcelNumber='<id>'` query, by the row's own
`parcel_id` (the scraper's own `_parcel()`: `GISParcelNumber`, falling back to `MAPNUMBER`),
falling back to a `PropertyLocation` exact match when a row carries no parcel id, mirrors the
scraper's OWN identity choice exactly. Live-verified 2026-11-16 on a real sampled row (PIN
"6196-36-6127.12", 2468 SUGAR RIDGE RD): `ConditionFactor` still reads `"DL  "` today (the
service pads it with trailing spaces -- stripped the same way the scraper's own `cond.strip()
.upper()` does, never compared raw).

A parcel can carry more than one CAMA "card" (building) under the same `GISParcelNumber` -- the
scraper's own comment notes this ("many building cards" on one parcel) and de-dupes to one
listing per parcel by keeping the first; this module instead reads EVERY card the targeted query
returns and treats the parcel as still condemned if ANY of them still reads 'DL' (a parcel is
not less condemned for having a second, better-rated outbuilding on the same tax lot).

VERDICTS: confirmed (at least one matched card's `ConditionFactor` still strips/uppers to 'DL'),
stale (the parcel still exists on the roll but every card now reads something else -- a
reassessment, a repair, a rebuild), refuted (the service answered and this parcel id / address
has no card on the roll at all -- a parcel that has since been split, merged or retired),
unconfirmed (the service could not be asked, or the row carries neither a parcel id nor a street
address to query by).

NOT COVERED (reported, not forced): `spartanburg_city_condemned.py`'s own "Master Condemnation
List" (81 of Spartanburg's 928 rows) is a no-login PDF from the city's document center, not an
API -- this project's verification Fetcher offers `get_text`/`get_json` only (confirmed by
reading every existing verifier: none parses a PDF), and no PDF-parsing library is used anywhere
under `verification/` today. A real fix exists (fetch the PDF's bytes and parse it the same way
the scraper itself already does -- BaseScraper's own http_client is not restricted to text/json
the way the sweep's lightweight Fetcher deliberately is) but it is new transport capability for
the verification layer, not a verifier built on what it already offers; left for a dedicated
follow-up rather than forced here.

TTL 30 days, retry 7 -- matches vacant_structure_hendersonville.py's cadence for this identical
signal; an assessor condition rating changes on inspection, not daily.

GOVERNS: deliberately omitted, same reasoning as condemned_adl.py's docstring.

EVIDENCE: the matched parcel id or address, how many CAMA cards matched, and per card (at most
8) its condition code -- no field beyond `GISParcelNumber`/`PropertyLocation`/`ConditionFactor`
(never `OwnerName`/`TaxpayerName`/any appraised or assessed value column the scraper itself
requests but this claim does not need).
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
ROW_SOURCE = "counties_sc.spartanburg_condemned"
SOURCE = "Spartanburg County CAMA_Parcels (maps.spartanburgcounty.org)"
SERVICE_URL = ("https://maps.spartanburgcounty.org/server/rest/services/"
              "GIS/CAMA_Parcels/FeatureServer/0")
FIELDS = "GISParcelNumber,MAPNUMBER,PropertyLocation,ConditionFactor"
_CONDEMNED_COND = "DL"
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


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    ev: dict[str, Any] = {}
    pid = row.get("parcel_id")
    addr = row.get("street_address")
    if pid:
        where = f"GISParcelNumber='{_esc(str(pid))}' OR MAPNUMBER='{_esc(str(pid))}'"
        ev["matched_by"] = "parcel_id"
    elif addr:
        where = f"UPPER(PropertyLocation)=UPPER('{_esc(str(addr))}')"
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
    any_condemned = False
    for a in feats[:MAX_CASES_IN_EVIDENCE]:
        cond = str(a.get("ConditionFactor") or "").strip().upper()
        if cond == _CONDEMNED_COND:
            any_condemned = True
        cards.append({"condition_factor": cond or None})
    ev["cards"] = cards
    ev["cards_matched"] = len(feats)
    if any_condemned:
        return _res("confirmed", ev)
    ev["reason"] = "condition_no_longer_dl"
    return _res("stale", ev)
