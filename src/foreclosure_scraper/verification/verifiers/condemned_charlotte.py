"""vacant_structure (condemned), charlotte_open_data.py's own `fof_ordered` check
(scrapers/city_websites/charlotte_open_data.py, source "city_websites.charlotte_open_data"):
does Charlotte's own CodeEnforcementCasesAll service still carry an OPEN case with a Findings-
of-Fact demolition order (`FOFOrdered`) on this address?

WHY THIS EXISTS: see condemned_adl.py's docstring for the full 2026-11-16 round-6 gap-matrix
investigation this is part of. Mecklenburg's 15 `condemned` rows (the only county this producer
covers) were `built-not-verified` the same way: a real, live-sampled producer, zero verifier.

THE SOURCE (live-checked 2026-11-16): the same ArcGIS FeatureServer/MapServer the scraper itself
reads -- gis.charlottenc.gov/.../HNS/CodeEnforcementCasesAll/MapServer/0 -- anonymous, no login,
no CAPTCHA (the scraper's own module docstring already live-verified this, 2026-10-13: not
attachments-enabled, no further capability to probe). `FOFOrdered` is an `esriFieldTypeSmall
Integer` (0/1); `CaseStatus` an `esriFieldTypeString`.

WHY NOT MATCH BY CASE NUMBER. The scraper's own `_to_listing()` writes the matched case's
`CaseNumber` into `raw['code_enforcement']['violations'][0]['case_id']` -- a precise key, in
principle. Live-sampled 2026-11-16 across five real Mecklenburg `condemned` rows: every one's
`raw['code_enforcement']` block had `case_id: None`, and one carried `fof_ordered: false` in its
own `charlotte_code_enforcement` detail despite the row's `raw['condemned']` being True. Both
point to the same cause `Listing.merge()`'s deep-merge already documents elsewhere (see
vacant_structure_hendersonville.py's own "THE BOARD'S COPY OF THE REGISTER IS NEVER A SOURCE"
section): a parcel can carry MANY of this service's cases over the years (one address, a dozen
code-enforcement cases across a decade is ordinary -- live-confirmed below), `raw['condemned']`
is set the moment ANY of them had `FOFOrdered`, and a LATER case's own merge can overwrite the
block's display fields without clearing the flag a prior case earned. The row's own `case_id`
is therefore not trustworthy as *which* case to re-check -- only the ADDRESS is.

MATCHING: `UPPER(FullAddress) LIKE '%<row's own normalized street_address, house number
included>%'` -- the WHOLE street text, never `enrichment_code_enforcement.py`'s own
`_street_keywords()` (that helper deliberately drops the house number, built for a DIFFERENT
service's address field that has no house number of its own to disambiguate against; tried
here first, then live-DISPROVED, not merely assumed differently to begin with -- see BUG FOUND
below). `FullAddress` always carries "<street> <city>, <ST> <zip>", so a LIKE on the street
text alone still matches regardless of city/zip suffix, while staying specific to one address.

BUG FOUND AND FIXED while live-validating (2026-11-16): a first pass built the query from
`_street_keywords()` instead ("HIGHLAND" alone, dropping "2229"/"ST") and only inspected the
FIRST 8 of however many features the LIKE returned for its confirmed/stale decision. On real
Charlotte data this doubly failed: a single common street-name word matches every OTHER street
sharing it citywide (533 total features for "HIGHLAND" alone, almost none of them actually at
2229 Highland St), and the one truly open, FOF-ordered case at a real sampled address (5601 PAW
CREEK RD, case 20210015439; 2329 SANDERS AV, case 20220003651) sorted past position 8 in the
broad result set -- both addresses came back `stale`, wrongly, under that version. Re-querying
the SAME two addresses by their own full street text instead returns 12 and 20 features
respectively, each genuinely at that one address, and the real open/FOF case appears in both
(confirming they should read `confirmed`, not `stale`). The decision logic now scans every
returned feature, never only the evidence-display slice.

Live-verified 2026-11-16 on four real sampled Mecklenburg rows with the corrected query: "2601
ABELWOOD RD" (12 cases, every one now `Closed`/`FOFOrdered=0` -- a real `stale`, the FOF order
has since been resolved), "2229 HIGHLAND ST" (5 cases, one -- 20210060969 -- still `Open`/
`FOFOrdered=1`), "5601 PAW CREEK RD" (12 cases, one -- 20210015439 -- still open), "2329 SANDERS
AV" (20 cases, one -- 20220003651 -- still open): three genuinely `confirmed`, one genuinely
`stale`, on real data.

A single query, never `_arcgis_layer.py`'s whole-layer cache: the full CodeEnforcementCasesAll
table is the service's entire multi-year caseload (far larger than the "a few thousand rows"
`_arcgis_layer.py`'s own docstring sizes a whole-layer load for), so a targeted per-row LIKE,
the same choice `code_enforcement_city_open_data.py` already makes for this identical shape of
service, is the right one here too.

VERDICTS: confirmed (at least one matched case is still `CaseStatus='Open'` with a truthy
`FOFOrdered`), stale (cases found at this address but none both open and FOF-ordered any more),
refuted (the service answered and this address has no case at all), unconfirmed (the service
could not be asked, or the row has no numbered street address to query by).

TTL 30 days, retry 7 -- a demolition order is not a daily-moving fact; matches
vacant_structure_hendersonville.py's cadence for this identical signal.

GOVERNS: deliberately omitted, same reasoning as condemned_adl.py's docstring (`raw['condemned']`
is a bare flag with no per-source provenance to clear selectively on a merged parcel).

EVIDENCE: the query keyword, how many cases matched, and per matched case (at most 8) its case
number, status and FOFOrdered flag -- no field beyond `FullAddress`/`CaseStatus`/`FOFOrdered`/
`CaseNumber` (never `EmailAddress`/`InspectorPhone`, which the scraper's own docstring already
excludes as inspector contact data, not the owner's).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional
from urllib.parse import urlencode

from ..core import VerificationResult, result

SIGNAL = "vacant_structure"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
ROW_SOURCE = "city_websites.charlotte_open_data"
SOURCE = "Charlotte HNS/CodeEnforcementCasesAll (gis.charlottenc.gov)"
SERVICE_URL = ("https://gis.charlottenc.gov/arcgis/rest/services/HNS/"
              "CodeEnforcementCasesAll/MapServer/0/query")
FIELDS = "CaseNumber,CaseStatus,FOFOrdered,FullAddress"
MAX_CASES_IN_EVIDENCE = 8
_NAME = __name__.rsplit(".", 1)[-1]


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def applies(row: dict) -> bool:
    return bool(_raw(row).get("condemned")) and row.get("source") == ROW_SOURCE


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def _query(client, street: str) -> Optional[list[dict]]:
    params = {"where": f"UPPER(FullAddress) LIKE '%{street.upper()}%'", "outFields": FIELDS,
             "returnGeometry": "false", "f": "json"}
    url = SERVICE_URL + "?" + urlencode(params)
    try:
        data = await client.get_json(url)
    except Exception:  # noqa: BLE001 - unreachable; verify() answers unconfirmed on this
        return None
    if not isinstance(data, dict) or "error" in data:
        return None
    return [(f.get("attributes") or {}) for f in (data.get("features") or [])]


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    ev: dict[str, Any] = {}
    street = row.get("street_address")
    if not street or not str(street).strip():
        ev["reason"] = "no_identity"
        return _res("unconfirmed", ev)
    street = str(street).strip()

    feats = await _query(client, street)
    if feats is None:
        ev["reason"] = "endpoint_unreachable"
        return _res("unconfirmed", ev)
    if not feats:
        ev["reason"] = "no_case_at_address"
        return _res("refuted", ev)

    # Decide over EVERY matched feature, never only the evidence-display slice -- see the
    # module docstring's BUG FOUND AND FIXED section (a decision scoped to feats[:8] missed the
    # genuinely open case on two of four real sampled addresses, both with well over 8 total
    # cases on file).
    any_open_fof = any(str(a.get("CaseStatus") or "").strip().lower() == "open"
                       and bool(a.get("FOFOrdered")) for a in feats)
    cases = [{"case_number": a.get("CaseNumber"), "status": a.get("CaseStatus"),
             "fof_ordered": bool(a.get("FOFOrdered"))} for a in feats[:MAX_CASES_IN_EVIDENCE]]
    ev["cases"] = cases
    ev["cases_matched"] = len(feats)
    if any_open_fof:
        return _res("confirmed", ev)
    ev["reason"] = "no_open_fof_case"
    return _res("stale", ev)
