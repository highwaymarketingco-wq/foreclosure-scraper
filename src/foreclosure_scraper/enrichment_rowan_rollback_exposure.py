"""Rowan County NC ``tax.rowancountync.gov`` (iasWorld) Datalet "Deferred Land" field ->
the shared raw['rollback_exposure'] contract enrichment_rollback_deferral.py established and
gap_matrix.py's own checked_columns()/positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-21.csv, read before writing a line here).
    rollback_exposure shows sourced-not-built for Rowan (4,594 applicable), source "tax/property
    card: tax.rowancountync.gov", built=no, next_action guessing a brand-new tax-roll reader is
    needed. THAT PREMISE IS WRONG: a live tax-roll reader for this exact host already exists and
    already runs -- verification/verifiers/tax_lien_rowan.py (shipped 2026-10-18), which drives
    the SAME iasWorld "commonsearch.aspx" search + Datalet detail page this module reuses
    verbatim (search(), _session(), BASE, SEARCH_URL -- never re-implemented here). The gap list's
    "built=no" is correct only for the ROLLBACK ENRICHMENT on top of that reader, not for the base
    reader itself -- the same shape every other NC rollback correction tonight (Nash, Hyde,
    Harnett) already found for their own counties.

    LIVE-VERIFIED 2026-10-21 (real search + detail-page fetches against the real host, read-only,
    no board touched, 17 real Rowan board parcels streamed via board_stream and searched). The
    Datalet's own in-page nav for a REAL (non-fixture) parcel lists these modes:
    address, advanced, https, link, own_hist, parcel_history, profileall, realprop, sales,
    sales_summary, sketch, tax_bills_int, value_history -- a DIFFERENT tab set from Nash's
    CAMA-only iasWorld tenant (enrichment_nash_multiyear_tax.py's own docstring: profileall,
    sales, land, residential, commercial, oby, valuesall, comapt, comuse, sketch) because Rowan's
    tenant is the TAX side of the same vendor product, not the assessor-CAMA side; "land" and
    "valuesall" are NOT real tabs here (fetching them silently returns the default/blank page,
    confirmed live) -- the right tab is `value_history`.

    GET {BASE}/Datalets/Datalet.aspx?mode=value_history&sIndex=<N>&idx=<M> -> a per-tax-year
    table, newest year first (2026 down to 2017 observed), columns in order: Tax Year, Appr Land,
    "Deferred Land", Appr Bldg, Assessed Total, Exempt, SR Exclusion, Vet Exclusion, Taxable
    Total. "Deferred Land" is the exact present-use/ag-deferral VALUE line this project's
    rollback family already keys on by NAME (the same evidentiary bar Wake's "Total Deferred
    Value" and Transylvania's "Deferred Value :" lines cleared) -- NOT an inferred market-minus-
    use subtraction (the NC PTS Cloud trap enrichment_rollback_deferral.py's own docstring warns
    against). profileall's own "Deferred:" side-heading line (DataletSideHeading/DataletData,
    single current value, no history) agrees with value_history's own current-year figure on
    every parcel checked and is NOT used here -- value_history is strictly more useful (it also
    carries the matching year's Assessed/Taxable Total needed to derive a rate, see below).

    LIVE-MEASURED 2026-10-21, 17 real Rowan board parcels (owner_name withheld; parcel + county
    only, already public): 2 of 17 (11.8%) carry a real, nonzero, CURRENT-year Deferred Land
    value -- parcel "388 022" (owner redacted here, not in evidence below), $75,943 deferred for
    2024-2026 (was $0 2020-2023, i.e. the parcel entered present-use mid-window); parcel "758 052"
    (owner redacted), $58,045-$54,003 deferred across 2019-2026, every year of its own online
    history. The other 15 carry $0 Deferred Land on every year on file. This is a REAL rate, not
    a guessed one -- board-wide the applicable count (4,594) should be read as a ceiling, not an
    expectation that most of it will carry a positive figure, the same caveat every sibling
    rollback module's own docstring already states for its own county.

RATE, NEVER ASSUMED (same convention enrichment_harnett_rollback_exposure.py and
    enrichment_hyde_rollback_exposure.py already use, imported verbatim from
    enrichment_rollback_deferral's _RATE_MIN/_RATE_MAX band). The matching tax year's own billed
    amount comes from tax_lien_rowan.detail() -- the SAME tax_bills_int Datalet fetch that
    module's own verify() already performs for the tax_lien signal, reused here rather than
    re-implemented (one extra GET, same session, same sIndex/idx this module's own search already
    produced). rate = that year's original_bill / value_history's own Assessed Total for the
    SAME year; kept only inside the sane band. No new network call beyond the one detail() fetch;
    a parcel whose rate doesn't land in the band, or has no matching bill year, still gets its
    real deferred_value, just without a derived annual/estimated-rollback figure.

MATCH METHOD: parcel_id only, by EXACT match (never prefix -- tax_lien_rowan.search()'s own
    inpParid matches by PREFIX, so this module filters to the row whose own Parcel ID column is
    an exact alnum match, the identical discipline tax_lien_rowan.verify() already applies).
    Rowan's own board parcel_id shape ("242 007", "137C018") IS iasWorld's short PARID -- no
    reformatting needed, unlike Brunswick/Harnett's 12-digit-PIN-vs-short-id mismatch (this
    county's board rows already carry the county's own short id, confirmed live against 17 real
    rows, 0 shape mismatches).

CONCURRENCY: deliberately sequential (CONCURRENCY default 1), unlike the httpx-based sibling
    modules. tax_lien_rowan's own session plumbing (_session/_RUNS) keeps ONE mutable ASP.NET
    WebForms viewstate per client, refreshed after every POST (search()'s own `fresh = hidden_
    fields(...)` write) -- concurrent calls against the SAME shared client would race on that
    mutable state (one row's POST overwriting another's in-flight viewstate). tax_lien_rowan.py
    itself is never modified to fix this (out of scope here, and its own production call pattern
    was not audited); this module simply avoids creating the hazard for itself by not running
    concurrent calls against one client instance.

GATE. Only a positive `deferred_value` off an EXACT-parcel-matched value_history row qualifies --
    build_block() never invents one, matching every sibling in this family.

Bounded, opt-in, free, public, no login, no CAPTCHA (same host tax_lien_rowan.py already reads
every scheduled run). Gate off entirely with FORECLOSURE_ROWAN_ROLLBACK=0.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import date
from typing import Any, Iterable, Optional

import structlog

from .enrichment_rollback_deferral import _RATE_MAX, _RATE_MIN
from .models import Listing
from .verification.fetch import Fetcher
from .verification.verifiers import _tax_common as tc
from .verification.verifiers import tax_lien_rowan as rowan

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "rowan_iasworld"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("ROWAN_ROLLBACK_MAX", "300"))
BUDGET_S = float(os.getenv("ROWAN_ROLLBACK_BUDGET_S", "900"))
#: sequential by default -- see module docstring (shared ASP.NET viewstate hazard).
_CONCURRENCY = int(os.getenv("ROWAN_ROLLBACK_CONCURRENCY", "1"))

ENABLED = os.environ.get("FORECLOSURE_ROWAN_ROLLBACK") != "0"

_CELL_RE = re.compile(r'class="DataletData">([^<]*)')
_YEAR_RE = re.compile(r"^\d{4}$")


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(RAW_KEY), dict)


def _eligible(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    return bool(
        li.state == "NC" and (li.county or "").strip().lower() == "rowan"
        and tc.alnum(str(li.parcel_id or "")) and not _already_done(raw)
    )


def _positive(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def parse_value_history(html: str) -> list[dict]:
    """[{year, appr_land, deferred_land, appr_bldg, assessed_total, exempt, sr_exclusion,
    vet_exclusion, taxable_total}] off the VALUE_HISTORY datalet, in the page's own printed order
    (newest-year-first, live-confirmed 2026-10-21) -- [] when the datalet itself isn't on the
    page (bad sIndex/idx, or a session that expired between the search and this fetch)."""
    i = html.find("Tax Year")
    if i < 0:
        return []
    cells = _CELL_RE.findall(html[i:i + 20000])
    rows = []
    for k in range(0, len(cells) - 8, 9):
        chunk = [c.strip() for c in cells[k:k + 9]]
        if not _YEAR_RE.match(chunk[0]):
            break
        rows.append({
            "year": int(chunk[0]), "appr_land": _money(chunk[1]),
            "deferred_land": _money(chunk[2]), "appr_bldg": _money(chunk[3]),
            "assessed_total": _money(chunk[4]), "exempt": _money(chunk[5]),
            "sr_exclusion": _money(chunk[6]), "vet_exclusion": _money(chunk[7]),
            "taxable_total": _money(chunk[8]),
        })
    return rows


def _money(v: Any) -> float:
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    if not s or s in (".", "-"):
        return 0.0
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


async def value_history(client: Any, sIndex: str, idx: str) -> list[dict]:
    """The value_history table for one search result's (sIndex, idx), cached per run -- same
    cache/session reuse discipline as tax_lien_rowan.detail()."""
    run = rowan._run(client)
    ck = ("value_history", sIndex, idx)
    if ck in run["cache"]:
        return run["cache"][ck]
    s, _hidden = await rowan._session(client)
    url = f"{rowan.BASE}/Datalets/Datalet.aspx?mode=value_history&sIndex={sIndex}&idx={idx}"
    r = await s.get(url, timeout=rowan.TIMEOUT_S)
    if r.status != 200:
        raise RuntimeError(f"value_history HTTP {r.status}")
    rows = parse_value_history(r.text)
    run["cache"][ck] = rows
    return rows


def build_block(vh_rows: list[dict], bills: Optional[list[dict]]) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] record from Rowan's own value_history 'Deferred Land'
    line for the most recent year that carries one, or None when every year on file is zero/
    blank -- never invented. Rate is derived from the matching year's tax_bills_int bill divided
    into value_history's own Assessed Total for that SAME year, never a hard-coded millage, kept
    only inside the shared sane band."""
    candidates = [(r["year"], r["deferred_land"], r.get("assessed_total"))
                  for r in vh_rows if _positive(r.get("deferred_land"))]
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    year, deferred, assessed_total = candidates[0]
    rec: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "basis": "present_use_deferral",
        "county": "Rowan",
        "state": "NC",
        "source": 'tax.rowancountync.gov (iasWorld) Datalet value_history "Deferred Land"',
        "source_key": SOURCE_KEY,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,       # statutory interest not modelled
        "match_method": "parcel_id",
        "tax_year": year,
    }
    bill = next((b for b in (bills or ()) if b.get("year") == year), None)
    assessed = _positive(assessed_total)
    if bill and assessed:
        levy = _positive(bill.get("original_bill"))
        if levy:
            rate = levy / assessed
            if _RATE_MIN <= rate <= _RATE_MAX:
                annual = round(deferred * rate, 2)
                rec.update(effective_tax_rate=round(rate, 6), tax_rate_source="rowan_tax_bills_int",
                           annual_deferred_tax=annual,
                           estimated_rollback=round(annual * ROLLBACK_YEARS_NC, 2))
    return rec


async def enrich_rowan_rollback_exposure(listings: Iterable[Listing], *,
                                         client: Optional[Any] = None) -> dict[str, Any]:
    """Walk not-yet-checked Rowan NC board rows, search tax.rowancountync.gov by exact parcel_id
    (prefix-matched then filtered to an exact Parcel-ID-column hit, same as tax_lien_rowan.py),
    fetch that result's value_history + tax_bills_int tabs, and restate a positive 'Deferred
    Land' line into raw['rollback_exposure']. Writes raw['rollback_exposure']. `client` is
    exposed for tests; the real pipeline always lets it default (a fresh Fetcher)."""
    stats = {"eligible": 0, "searched": 0, "parcel_not_found": 0, "ambiguous_parcel": 0,
             "errors": 0, "deferred_found": 0, "skipped_budget": 0}
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_ROWAN_ROLLBACK=0)"}
    targets = [li for li in listings if _eligible(li)]
    stats["eligible"] = len(targets)
    if not targets:
        return stats
    targets = targets[:MAX_LISTINGS]

    cli = client or Fetcher(min_interval_s=0.5)
    start = time.monotonic()
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(li: Listing) -> None:
        if (time.monotonic() - start) > BUDGET_S:
            stats["skipped_budget"] += 1
            return
        pid = str(li.parcel_id or "").strip()
        norm = tc.alnum(pid)
        async with sem:
            try:
                found = await rowan.search(cli, pid)
            except Exception:  # noqa: BLE001 - one lead never kills the pass
                stats["errors"] += 1
                return
            stats["searched"] += 1
            matches = [r for r in found if tc.alnum(r["parcel_id"]) == norm]
            if not matches:
                stats["parcel_not_found"] += 1
                return
            if len(matches) > 1:
                stats["ambiguous_parcel"] += 1
                return
            match = matches[0]
            try:
                vh_rows = await value_history(cli, match["sIndex"], match["idx"])
            except Exception:  # noqa: BLE001
                stats["errors"] += 1
                return
            bills: Optional[list[dict]] = None
            try:
                bills = await rowan.detail(cli, match["sIndex"], match["idx"])
            except Exception:  # noqa: BLE001
                bills = None
        block = build_block(vh_rows, bills)
        if not block:
            return
        stats["deferred_found"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw[RAW_KEY] = block

    await asyncio.gather(*(one(li) for li in targets))
    log.info("rowan_rollback.done", **stats)
    return stats
