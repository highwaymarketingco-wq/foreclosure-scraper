"""code_enforcement, Spartanburg County SC's own CAMA assessor condition proxy
(counties_sc.spartanburg_condemned, source="counties_sc.spartanburg_condemned"): does the
county's own CAMA_Parcels roll still rate this parcel's building condition "DL" (DELAPITATED)
today?

THE BUG THIS CLOSES (2026-11-19, round-73 continuation of the same "verifier narrower than
producer set" sweep that found elderly_disabled_sc_homestead.py and code_enforcement_gastonia.py
the two previous rounds). counties_sc.spartanburg_condemned is a LIVE, wired-in producer (main.py
runs it; confirmed live via board_stream.iter_board_rows() on today's board: 934 Spartanburg SC
`code_enforcement` hit rows total, split 843 from this source's bare `raw["code_enforcement"] =
True` write and 91 from the sibling spartanburg_city_condemned.py's dict-shaped block -- see
NOT COVERED below) whose own module comment says exactly what it writes and why:

    # The signal distress_score keys on: raw['condemned'] -> code_enforcement (w=14)
    raw["condemned"] = True
    raw["code_enforcement"] = True

Every existing code_enforcement verifier was scoped to a DIFFERENT shape before this fix:
code_enforcement_adl.py requires a dict whose `source` is one of arcgis_distress_layers.py's own
process=="code_enforcement" Layer slugs (Spartanburg's CAMA proxy is not built on that generic
Layer registry at all -- it is its own standalone scraper); code_enforcement_city_open_data.py
requires the row's city to be one of a fixed Wake-area CITY_ENDPOINTS/SEVERE_ENDPOINTS set;
code_enforcement_henderson.py and code_enforcement_gastonia.py are each hardcoded to one other
county. None of the four's `_block()`/`applies()` helpers even accept a bare boolean `True` for
`raw["code_enforcement"]` (every one calls `isinstance(ce, dict)` first) -- so these 843 rows
read `built-not-verified (source status unknown)` in gap_matrix.py however long the scraper ran,
the identical bug shape (a real, live, wired producer with zero matching applies()) as both prior
rounds' fixes.

THE SOURCE AND THE CHECK. The SAME single live query vacant_structure's own
condemned_spartanburg.py already runs for this identical producer and this identical
parcel-level claim (maps.spartanburgcounty.org CAMA_Parcels/0, a plain anonymous ArcGIS
FeatureServer, `ConditionFactor` a free-text field, 'DL' the scraper's own condemned-equivalent
tier) -- the scraper's own comment above makes the two ledgers' claims the SAME underlying fact
("code_enforcement (w=14)" and "condemned" both key off the identical `ConditionFactor='DL'`
read), so this module delegates to condemned_spartanburg.verify() byte-for-byte rather than
re-implementing or re-querying: one live request answers both ledgers, the two verifiers just
label and file the identical verdict/evidence under their own SIGNAL. This also means the two
modules can never disagree about what the roll says, the same discipline probate_heir_greenville.py
reuses greenville_probate._parse_detail for and heir_estate_wthgis.py reuses heir_roll's own
field names for.

VERDICTS: confirmed/stale/refuted/unconfirmed, condemned_spartanburg.verify()'s own meanings --
confirmed (at least one CAMA card still reads ConditionFactor 'DL'), stale (the parcel is still
on the roll but every card now reads something else -- reassessed, repaired, rebuilt), refuted
(the parcel id/address has no card on the roll at all -- split, merged or retired since), never
`refuted` for "service answered, claim held, but couldn't be rechecked" (the correct bias when
this is an informational flag, not a right to collect).

NOT COVERED (reported, not forced -- same deferral condemned_spartanburg.py's own docstring
already makes for the identical producer family): spartanburg_city_condemned.py's "Master
Condemnation List" (91 of these 934 rows, dict-shaped `raw["code_enforcement"]` with
`source == "spartanburg_city_master_condemnation_list"`) is a no-login PDF, and the verification
layer's Fetcher offers `get_text`/`get_json` only -- no PDF-parsing capability exists under
`verification/` today, the exact same transport gap condemned_spartanburg.py's own "NOT COVERED"
section already names for its sibling vacant_structure ledger. `applies()` below deliberately
returns False for that shape rather than guessing; it stays a real, correctly-classified
`built-not-verified` cell until a dedicated PDF-fetch follow-up lands.

GOVERNS: deliberately omitted, same reasoning as condemned_adl.py's and condemned_spartanburg.py's
own docstrings -- `raw["code_enforcement"]` here carries no per-source provenance to clear
selectively on a merged row (it is a bare `True`, not a dict naming its own source), so a
stale/refuted verdict could silently clear ANOTHER source's bare `raw["code_enforcement"] = True`
on the same parcel; this module has no way to scope around that and does not try.

TTL 30 days, retry 7 -- matches condemned_spartanburg.py's own cadence for the SAME underlying
CAMA read (an assessor condition rating changes on inspection, not daily), not the 14/3 cadence
the active-caseload code_enforcement siblings (henderson/gastonia) use for a different kind of
source.

EVIDENCE: condemned_spartanburg.verify()'s own evidence shape unchanged (the matched parcel id
or address, how many CAMA cards matched, and per card its condition code) -- no field beyond what
that module already reads.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..core import VerificationResult, result
from . import condemned_spartanburg as cs

SIGNAL = "code_enforcement"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
ROW_SOURCE = cs.ROW_SOURCE   # "counties_sc.spartanburg_condemned"
SOURCE = cs.SOURCE           # "Spartanburg County CAMA_Parcels (maps.spartanburgcounty.org)"
_NAME = __name__.rsplit(".", 1)[-1]


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "SC":
        return False
    county = str(row.get("county") or "").strip().lower()
    if county.endswith(" county"):
        county = county[: -len(" county")]
    if county != "spartanburg":
        return False
    if row.get("source") != ROW_SOURCE:
        return False
    return _raw(row).get("code_enforcement") is True


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    inner = await cs.verify(row, client, today=today)
    return result(SIGNAL, inner.verdict, inner.evidence, source=SOURCE, version=VERSION,
                 verifier=_NAME)
