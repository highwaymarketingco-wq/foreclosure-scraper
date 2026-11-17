"""Craven County NC gis.cravencountync.gov ArcGIS REST "mMaps/Property" MapServer -- a real,
open, unauthenticated backend behind the county's own TaxBillSearch app.

WHY THIS EXISTS (round 18 of the tax-cluster gap_matrix sweep, 2026-11-17). Round 17's own note
(this project's memory, project_tax_cluster_round17_2026-11-16.md) found
gis.cravencountync.gov/apps/taxBillSearch/ is "a real, live, custom Bootstrap app... backed by a
live, OPEN, unauthenticated ArcGIS REST services directory... the specific tax-bill backend
endpoint was not located this round (the app's own functions.js has no FeatureServer/MapServer
reference a plain grep catches -- needs real browser network-tab inspection)."

FOUND, without any browser (this round's own agent-automation caution): the app's rendered
HTML itself (not functions.js) carries the real layer URL as a plain inline string --
    https://gis.cravencountync.gov/arcgis/rest/services/mMaps/Property/MapServer/29
(the "TaxNotices" table a UI helper endpoint, /apps/support/CopyTaxBills?ID=, uses to fetch one
bill's PDF by TaxRoll_ID). Walking that service's own sibling layer list
(.../mMaps/Property/MapServer?f=json) turned up two FAR more useful layers than the one the app
itself links:

    Layer 17 "TaxTable"                         -- one row per (parcel, tax year) BILL, with
                                                    its own outstanding balance, back to at
                                                    least 2017.
    Layer 6  "Parcels in Use Value Program"      -- one row per PUV-enrolled parcel, with its
                                                    own present-use-deferred assessment.
(2 siblings NOT used here: 29 "TaxNotices", a per-year PDF-filename index with no amount field
at all; 10 "Parcels with Tax Exclusion(s)", homestead/elderly/disabled exclusions -- a
different signal from present-use rollback, not this module's job.)

LAYER 17 (TaxTable) -- multi_year_delinquent_tax / two_year_delinquent / tax_aging_surfaced.
`TaxRoll_TotalDue` is the OUTSTANDING balance for that (parcel, year) bill, 0 once paid --
live-confirmed real, old arrears 2026-11-17: 3,570 rows carry TaxYear<=2025 (the latest FULLY
MATURED levy year as of this writing -- see `_matured_cutoff_year`) with TotalDue>0, e.g. parcel
"6-064   -091"/2017, owner "NOONAN, ROBERT C - EXECUTOR OF THE", $3,311.43 still owed -- genuine
multi-year arrears, not a current-bill-not-yet-due artifact. The current levy year alone
(TaxYear=2026, 40,754 rows with a nonzero balance) is excluded from every count below via
tax_calendar.levy_year_is_delinquent() -- NC's own delinquency date is January 6 of the
following year, so an unpaid 2026 bill in November 2026 is not yet late, the identical "current
levy vs matured arrears" distinction scrapers/counties_generic/multi_year_delinquent_tax.py's
own docstring already establishes for Buncombe/Oconee/Pickens (a date-driven cutoff here, not
that module's row-count-ratio heuristic, because this vendor has no "service per year" shape to
measure a ratio over -- one table, every year already in it).

LAYER 6 (Parcels in Use Value Program) -- rollback_exposure. `DEFERRED_VALUE` is the
present-use-deferred assessment (the amount a use-value-disqualification rollback would
recapture) -- live-confirmed real nonzero examples 2026-11-17: PARCEL_ID "2-018   -013", owner
"NORMAN, CATHY WHITFORD", DEFERRED_VALUE $65,290 of $98,320 MARKET_VALUE; 1,817 of the layer's
2,269 rows carry a positive value.

PARCEL JOIN. This county's board rows carry `parcel_id` as the GIS PID with every
non-alphanumeric character stripped -- live-confirmed against real board rows 2026-11-17 (PID
"6-213-L -213" -> board parcel_id "6213L213"; PID "7-104-A -038" -> "7104A038").
`_compact_pid()` applies the identical transform to each layer's own PID/PARCEL_ID so the two
sides always compare equal.

BULK, not per-row. Both layers are queried ONCE per run (paginated via `resultOffset`, already
filtered server-side to a nonzero balance / nonzero deferral so the matured-arrears page count
stays small -- 3,570 and 1,817 rows respectively, each well under one page at this vendor's own
5,000-row maxRecordCount) and grouped into {compact_pid: ...} dicts, then joined locally against
the board's already-known Craven NC rows -- no live per-row search, unlike Davidson's owner-name
vendor (enrichment_davidson_rollback_exposure.py, this same round). Free, public, no login, no
CAPTCHA/WAF (same ArcGIS REST pattern already read for Buncombe/Oconee/Pickens).

NOT INVENTED. `raw['multi_year_delinquent_tax']` is written only when a parcel has 2+ matured
delinquent years (SIMPLE_PRESENCE_COLS: presence IS the hit, so a 0-1-year parcel gets no key at
all there -- but DOES get the `_craven_tax_mydt_checked` shadow key, same convention as New
Hanover/Pasquotank/Gaston's own honest-negative screens, so it is never silently miscounted as
unchecked). `raw['two_year_delinquent']` is always written for a matched parcel (its own
`is_two_year_plus` flag carries the true/false answer, same as every other roll producer).
`raw['tax_aging_surfaced']` is written whenever at least one matured year is unpaid (this
column's own positive test is `status != "current" and years_delinquent > 0` -- ONE year is
already a hit, unlike the 2-year multi_year/two_year gate). `raw['rollback_exposure']` is
written only when DEFERRED_VALUE is positive, same "never invented" discipline as every sibling
rollback module.

WHAT THIS DOES NOT COVER. `atty_tax_verified_confirmed` is a verdict from a `tax_lien`
VERIFIER sweep (a separate system, `verification/verifiers/`) -- no Craven verifier exists yet
to turn this module's real `raw['multi_year_delinquent_tax']` hits into that column's own
positive signal. Out of scope here; the same honest, explicitly-flagged gap round 17 left open
for Vance's identical column.

Gate off entirely with FORECLOSURE_CRAVEN_TAX=0.
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Any, Iterable, Optional

import httpx
import structlog

from ...models import Listing
from ...tax_calendar import levy_year_is_delinquent

log = structlog.get_logger()

SLUG = "counties_nc.craven_tax_table"
STATE, COUNTY = "NC", "Craven"
HOST = "https://gis.cravencountync.gov"
SERVICE = f"{HOST}/arcgis/rest/services/mMaps/Property/MapServer"
LAYER_TAX_TABLE = 17
LAYER_USE_VALUE = 6

CHECKED_KEY = "_craven_tax_mydt_checked"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

#: a defensive ceiling on pagination -- the real matured-arrears set measured 2026-11-17 is
#: 3,570 rows (one page at this vendor's 5,000-row maxRecordCount); this bounds a future, much
#: larger backlog without an unbounded loop.
MAX_PAGES = int(os.getenv("CRAVEN_TAX_MAX_PAGES", "20"))
PAGE_SIZE = 2000

ENABLED = os.environ.get("FORECLOSURE_CRAVEN_TAX") != "0"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def _compact_pid(pid: Any) -> str:
    """The board's own parcel_id join key: every non-alphanumeric character stripped from the
    GIS PID/PARCEL_ID field, uppercased (live-confirmed transform, see module docstring)."""
    return _NON_ALNUM.sub("", str(pid or "")).upper()


def _matured_cutoff_year(today: Optional[date] = None) -> int:
    """The latest levy year whose delinquency date has already passed (NC's own Jan 6 of year+1
    rule, tax_calendar.levy_year_is_delinquent) -- keeps the bulk query to genuinely matured
    arrears, never the current not-yet-due bill."""
    today = today or date.today()
    cutoff = today.year - 1
    while not levy_year_is_delinquent(cutoff, STATE, COUNTY, today=today):
        cutoff -= 1
    return cutoff


async def _query_all(c: httpx.AsyncClient, layer: int, where: str, out_fields: str) -> list[dict]:
    """Every feature's attributes dict for one ArcGIS layer query, paginated via resultOffset.
    Stops when a page returns fewer than PAGE_SIZE rows, or at MAX_PAGES (defensive ceiling)."""
    out: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        params = {"where": where, "outFields": out_fields, "f": "json",
                  "resultRecordCount": str(PAGE_SIZE), "resultOffset": str(offset)}
        r = await c.get(f"{SERVICE}/{layer}/query", params=params)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"ArcGIS layer {layer} query error: {data['error']}")
        feats = data.get("features") or []
        out.extend(f.get("attributes", {}) for f in feats if isinstance(f, dict))
        # the server's OWN maxRecordCount, not the page size this call asked for, caps what one
        # response can hold (live-confirmed 2026-11-17: this vendor's own layers cap anywhere
        # from 1,000 to 5,000 regardless of a larger resultRecordCount) -- exceededTransferLimit
        # is the one reliable "there is more" signal; `len(feats) < PAGE_SIZE` alone stops one
        # page early whenever the real server-side cap is smaller than PAGE_SIZE (live-caught
        # 2026-11-17: Haywood's own layer 1 caps at 1,000 regardless of a 2,000-row ask, so this
        # bug alone would have silently dropped ~63% of its real rollback_exposure rows).
        if not feats or not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return out


async def fetch_delinquent_by_pid(c: httpx.AsyncClient,
                                  cutoff_year: Optional[int] = None) -> dict[str, dict]:
    """{compact_pid: {"years": sorted matured-delinquent years, "total_due": sum of their own
    outstanding balances, "source": SLUG}} from layer 17 (TaxTable), matured years only."""
    cutoff = cutoff_year if cutoff_year is not None else _matured_cutoff_year()
    rows = await _query_all(
        c, LAYER_TAX_TABLE, f"TaxRoll_TotalDue > 0 AND TaxYear <= {cutoff}",
        "PID,TaxYear,TaxRoll_TotalDue")
    by_pid: dict[str, dict] = {}
    for row in rows:
        pid = _compact_pid(row.get("PID"))
        year = row.get("TaxYear")
        due = row.get("TaxRoll_TotalDue")
        if not pid or year is None or not isinstance(due, (int, float)) or due <= 0:
            continue
        if not levy_year_is_delinquent(int(year), STATE, COUNTY):
            continue  # a defensive re-check in case the server-side cutoff and today's date drift
        rec = by_pid.setdefault(pid, {"years": set(), "total_due": 0.0, "source": SLUG})
        rec["years"].add(int(year))
        rec["total_due"] = round(rec["total_due"] + float(due), 2)
    for rec in by_pid.values():
        rec["years"] = sorted(rec["years"])
    return by_pid


async def fetch_rollback_by_pid(c: httpx.AsyncClient) -> dict[str, dict]:
    """{compact_pid: {"deferred_value", "market_value", "total_value", "approval_year"}} from
    layer 6 (Parcels in Use Value Program), positive deferrals only."""
    rows = await _query_all(
        c, LAYER_USE_VALUE, "DEFERRED_VALUE > 0",
        "PARCEL_ID,DEFERRED_VALUE,MARKET_VALUE,TOTAL_VALUE,APPROVAL_YEAR")
    by_pid: dict[str, dict] = {}
    for row in rows:
        pid = _compact_pid(row.get("PARCEL_ID"))
        deferred = row.get("DEFERRED_VALUE")
        if not pid or not isinstance(deferred, (int, float)) or deferred <= 0:
            continue
        by_pid[pid] = {"deferred_value": float(deferred), "market_value": row.get("MARKET_VALUE"),
                       "total_value": row.get("TOTAL_VALUE"),
                       "approval_year": row.get("APPROVAL_YEAR") or None}
    return by_pid


def build_two_year_block(years: list[int]) -> dict:
    return {"is_two_year_plus": len(years) >= 2, "years_delinquent": len(years),
           "years": years, "source": SLUG}


def build_multiyear_block(years: list[int], total_due: float) -> Optional[dict]:
    if len(years) < 2:
        return None
    return {"years": years, "years_delinquent": len(years), "total_due": total_due,
           "source": SLUG}


def build_aging_block(years: list[int], total_due: float) -> Optional[dict]:
    """None when there is nothing to report. NOTE on scope: `years` only ever reaches here
    non-empty, because the caller only looks this up for a `delinquent_by_pid` hit, and that
    dict is itself built from a TaxRoll_TotalDue > 0 filter -- a parcel with a fully clean
    matured history never appears in it at all (this module queries the DELINQUENT subset of
    layer 17 in bulk, not every parcel's full year history), so a genuinely clean Craven parcel
    gets no raw['tax_aging_surfaced'] stamp either way, never a false 'checked, clean' claim
    this module cannot actually back up."""
    if not years:
        return None
    return {"status": "delinquent", "years_delinquent": len(years), "total_due": total_due,
           "latest_delinquent_year": years[-1], "source": SLUG}


def build_rollback_block(rec: dict) -> Optional[dict]:
    deferred = rec.get("deferred_value")
    if not deferred or deferred <= 0:
        return None
    out: dict[str, Any] = {"deferred_value": round(float(deferred), 2),
                           "basis": "present_use_deferral", "county": COUNTY, "state": STATE,
                           "source": "gis.cravencountync.gov mMaps/Property MapServer, layer 6 "
                                      '("Deferred Value")',
                           "source_key": SLUG, "rollback_years": ROLLBACK_YEARS_NC,
                           "estimate_is_floor": True, "match_method": "parcel_id"}
    if rec.get("market_value"):
        out["market_value"] = rec["market_value"]
    if rec.get("approval_year"):
        out["puv_approval_year"] = rec["approval_year"]
    return out


def _is_craven_nc(li: Listing) -> bool:
    return li.state == STATE and (li.county or "").strip().lower() == COUNTY.lower()


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(SLUG), dict)


async def enrich_craven_tax(listings: Iterable[Listing]) -> dict[str, Any]:
    """Fetch Craven's TaxTable + Use Value Program layers ONCE (bulk, paginated), then join
    locally against every Craven NC board row by parcel_id. Writes raw['two_year_delinquent']
    (always, for a matched row), raw['multi_year_delinquent_tax']/raw['tax_aging_surfaced']
    (when a positive matured-arrears count applies), raw[CHECKED_KEY] (an honest 0-1-year
    negative screen, so it is never silently miscounted as unchecked), and
    raw['rollback_exposure'] (when DEFERRED_VALUE is positive)."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_CRAVEN_TAX=0)"}
    targets = [li for li in listings
              if _is_craven_nc(li) and (li.parcel_id or "").strip()
              and not _already_done(li.raw if isinstance(li.raw, dict) else {})]
    stats = {"eligible": len(targets), "delinquent_pids": 0, "rollback_pids": 0,
             "matched_delinquent": 0, "matched_two_year": 0, "matched_multiyear": 0,
             "matched_aging": 0, "matched_rollback": 0, "errors": 0}
    if not targets:
        return stats

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": _UA}) as c:
        try:
            delinquent_by_pid = await fetch_delinquent_by_pid(c)
            rollback_by_pid = await fetch_rollback_by_pid(c)
        except Exception:  # noqa: BLE001 - a failed fetch must not crash the run
            stats["errors"] += 1
            log.warning("craven_tax.fetch_failed")
            return stats
    stats["delinquent_pids"] = len(delinquent_by_pid)
    stats["rollback_pids"] = len(rollback_by_pid)

    for li in targets:
        if not isinstance(li.raw, dict):
            li.raw = {}
        pid = _compact_pid(li.parcel_id)
        hit = delinquent_by_pid.get(pid)
        if hit is not None:
            stats["matched_delinquent"] += 1
            li.raw["two_year_delinquent"] = build_two_year_block(hit["years"])
            stats["matched_two_year"] += 1
            mult = build_multiyear_block(hit["years"], hit["total_due"])
            if mult:
                li.raw["multi_year_delinquent_tax"] = mult
                stats["matched_multiyear"] += 1
            else:
                li.raw[CHECKED_KEY] = True
            aging = build_aging_block(hit["years"], hit["total_due"])
            if aging:
                li.raw["tax_aging_surfaced"] = aging
                stats["matched_aging"] += 1
        rb_hit = rollback_by_pid.get(pid)
        if rb_hit is not None:
            block = build_rollback_block(rb_hit)
            if block:
                li.raw["rollback_exposure"] = block
                stats["matched_rollback"] += 1
        li.raw[SLUG] = {"checked_at": date.today().isoformat()}

    log.info("craven_tax.done", **stats)
    return stats
