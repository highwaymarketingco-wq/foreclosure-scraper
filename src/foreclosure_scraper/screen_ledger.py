"""Screen ledger: which (signal column, county) cells a run SCREENED, including the ones where the
screen found nothing.

WHY. The coverage cube (scripts/gap_matrix.py) asks of every county-, state- and feed-scope
signal column "did we check this county?". The board alone cannot answer it when the answer is
"yes, and nothing was found": a county jail roster read in full with no owner on it, a county
delinquent-tax roll read in full that lists none of the county's board parcels, a statewide
auction feed that carried no sale in that county. Those cells read as never checked (class
built-but-low-yield) although the run did the work. This module records the screen itself, at
the granularity the cube measures it (state, county, column), from the run's own per-source
status (docs/run_health.json): a source whose status says it ran to completion (OK / EMPTY
(verified)) screened every county it covers; a source that alarmed, timed out, was dormant or
carried rows over did not.

WHAT COUNTS AS A SCREEN (conservative on purpose; an over-claim here is the presence-check
inflation bug again):
  * the source's status this run is OK (n) or EMPTY (verified);
  * the source covers the WHOLE county for that column: a county-wide roster, list or layer, or a
    declared statewide source (SPECS.statewide in gap_matrix). City-only registries (a city's
    vacant or condemned list) do not screen their county; budgeted or pager-lossy enumerations
    (qPayBill, REQUEST_BUDGET_PER_COUNTY) do not either;
  * coverage comes from the producer's own configuration (a county in its file name under
    counties_nc/ or counties_sc/, or the module's county table), never from where its rows
    happened to land.

Written next to run_health.json (write_ledger) as docs/screen_ledger.json; read by gap_matrix
(--screens) and by scripts/audit_checks/cube.py. Counts, county names, column names and source
slugs only: nothing private.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .validation import NC_COUNTIES, SC_COUNTIES

SCHEMA = "screen-ledger-v1"
PKG = Path(__file__).resolve().parent
SCRAPERS = PKG / "scrapers"
STATE_COUNTIES = {"NC": tuple(NC_COUNTIES), "SC": tuple(SC_COUNTIES)}
#: A ledger older than this (days, against the date the cube measures) screens nothing.
MAX_AGE_DAYS = 14

#: listing type -> the cube's feed column
FEED_COLUMN = {
    "foreclosure_sale": "lt_foreclosure_sale", "sheriff_sale": "lt_sheriff_sale",
    "lis_pendens": "lt_lis_pendens", "tax_lien": "lt_tax_lien", "tax_sale": "lt_tax_sale",
    "auction": "lt_auction", "reo": "lt_reo", "hoa_sale": "lt_hoa_sale",
    "distressed": "lt_distressed", "divorce_notice": "lt_divorce_notice",
    "probate_notice": "lt_probate_notice", "estate_lead": "lt_estate_lead",
    "elderly_disabled": "lt_elderly_disabled", "tax_sale_overage": "lt_tax_sale_overage",
    "bankruptcy": "lt_bankruptcy",
}

#: Row-scope columns a county-complete roster screens: a parcel absent from the county's full
#: delinquent roll is not delinquent on it, so the roll's read is the row's negative result.
TAX_COLUMNS = ("multi_year_delinquent_tax", "two_year_delinquent", "tax_aging_surfaced")
COUNTY_ROSTER_ROW_COLUMNS = frozenset(TAX_COLUMNS)


def status_ok(status: Any) -> bool:
    """The run_health status of a source that ran to completion this run."""
    s = str(status or "").strip()
    return s.startswith("OK") or s.startswith("EMPTY (verified)")


# ---------------------------------------------------------------------------------------------
# Coverage resolvers
# ---------------------------------------------------------------------------------------------

def _state(st: str) -> Callable[[], set]:
    return lambda: {(st, c) for c in STATE_COUNTIES[st]}


def _named(st: str, *counties: str) -> Callable[[], set]:
    return lambda: {(st, c) for c in counties}


def _module_counties(modname: str, expr: Callable[[Any], Iterable], st: Optional[str] = None) -> Callable[[], set]:
    """Counties from the producer's own table (imported lazily; an import failure covers nothing)."""
    def f() -> set:
        import importlib
        try:
            mod = importlib.import_module(f"{__package__}.{modname}")
            got = list(expr(mod))
        except Exception:  # noqa: BLE001 - a module that will not import screened nothing
            return set()
        out = set()
        for g in got:
            if isinstance(g, tuple) and len(g) == 2:
                out.add((str(g[0]).upper(), str(g[1])))
            elif st:
                out.add((st, str(g)))
        return {k for k in out if k[1] in STATE_COUNTIES.get(k[0], ())}
    return f


@dataclass(frozen=True)
class Screen:
    slug: str                       # run_health source slug
    columns: tuple                  # cube columns a completed run screens
    coverage: Callable[[], set]     # (state, county) pairs it covers in full
    note: str = ""


def _column_sc_probate(mod) -> Iterable:
    return [("SC", c) for c in (*mod.SC_FOOTPRINT, *mod.SC_DISTRESSED_ONLY, *mod.SC_PROBATE_EXTRA_COUNTIES)]


def _jail_rosters(mod) -> Iterable:
    return [(s, c) for s, c, _v, _t in mod.ROSTERS]


#: Declared screens for sources whose coverage is not one county in a counties_nc/ or
#: counties_sc/ file name. Every entry was read against the producer before it went in.
DECLARED: tuple[Screen, ...] = (
    # federal: CourtListener carries every NC/SC bankruptcy court (SPECS.statewide)
    Screen("national.courtlistener_bankruptcy", ("lt_bankruptcy",), lambda: _state("NC")() | _state("SC")(),
           "statewide federal bankruptcy feed"),
    # national auction / REO sites list by property; a completed pull covers both states
    *(Screen(s, ("lt_auction",), lambda: _state("NC")() | _state("SC")(), "national auction site")
      for s in ("national.hibid_real_estate", "national.bid4assets", "national.servicelink_auction",
                "national.auction_bank_reo", "national.williams", "national.realtor_foreclosures",
                "national.govdeals")),
    *(Screen(s, ("lt_reo",), lambda: _state("NC")() | _state("SC")(), "national REO inventory")
      for s in ("national.homepath_json", "national.fannie_homepath", "national.hubzu",
                "national.usda_properties", "reo.usda_rd", "reo.vrm_va_reo", "reo.treasury_seized")),
    # SC quiet-title suits naming heirs ride the SC estate lane of Column (parsed only there)
    Screen("counties.column_legal_notices", ("heir_naming_publication", "quiet_title"),
           _module_counties("scrapers.newspapers.column_legal_notices", _column_sc_probate),
           "SC estate lane counties only; Column tags SC notices by newspaper region"),
    # NC quiet-title / heir-naming notices: Column's statewide API, queried by notice text (top-80
    # build list 2026-10-09). Covered = NC counties with at least one Column notice in 365 days
    # (nc_heir_notices.COLUMN_NC_COUNTIES); the other 25 have no Column paper (verdict, not gap).
    Screen("public_notices.nc_heir_notices", ("heir_naming_publication", "quiet_title"),
           _module_counties("scrapers.public_notices.nc_heir_notices",
                            lambda m: [("NC", c) for c in m.COLUMN_NC_COUNTIES]),
           "NC counties with a Column paper; notices searched by text"),
    # NC ITSPublic tax-bill portals (top-80 2026-10-09): Onslow, Graham and ten counties of the newer
    # build. The run reads each county's whole unpaid real-property roll for the newest delinquent year
    # (older years within a time budget). A county that failed, or ran out of time before its newest
    # year was complete, makes the run PARTIAL (not an OK status), so nothing is claimed on a half read.
    Screen("counties_nc.nc_its_public_tax", TAX_COLUMNS,
           _module_counties("scrapers.counties_nc.nc_its_public_tax", lambda m: [("NC", c) for c in m.PORTALS]),
           "full unpaid real-property roll per county (ITSPublic portals)"),
    # county jail rosters (bulk, county-wide); unhealthy rosters are removed in build()
    Screen("national.jail_bookings", ("jail_booking",),
           _module_counties("scrapers.national.jail_bookings", _jail_rosters),
           "county jail rosters; rosters_unhealthy removed"),
    # county delinquent rolls, complete per county
    Screen("counties_nc.nc_county_csv_delinquent_tax", TAX_COLUMNS,
           _module_counties("scrapers.counties_nc.nc_county_csv_delinquent_tax", lambda m: m.COUNTIES, "NC"),
           "full NCGS 105-369 roll per county"),
    Screen("counties_sc.sc_catalis_delinquent_roll", TAX_COLUMNS,
           _module_counties("scrapers.counties_sc.sc_catalis_delinquent_roll", lambda m: m.CATALIS_COUNTIES, "SC"),
           "full unpaid roll per county"),
    # county-wide condemned roll (the city one does not screen the county)
    Screen("counties_sc.spartanburg_condemned", ("condemned",), _named("SC", "Spartanburg"),
           "county condemned/dilapidated roll"),
    # SC probate courts on southcarolinaprobate.net (estate index per county)
    Screen("counties_sc.sc_probate_net", ("probate",),
           _module_counties("scrapers.counties_sc.sc_probate_net",
                            lambda m: [(s, c) for _n, c, s, marriage in m.COUNTIES if not marriage]),
           "county estate index"),
)

#: Enrichments that screen whole counties and say which ones in their run stats
#: (run_health['enrichments'][name]['screened'] = {column: ["NC|County", ...]}). A county is listed
#: only when the enrichment finished its sweep of that county without a failed page.
ENRICHMENT_SCREENS: dict[str, tuple[str, ...]] = {
    "onemap_sweeps": ("heir_estate", "rollback_exposure"),     # enrichment_onemap_sweeps (top-80 2026-10-09)
    "probate_spartan": ("probate",),                           # enrichment_probate_spartan (top-80 2026-10-09)
}

#: Sources that never screen a county, with the reason (kept so the exclusion is visible)
EXCLUDED = {
    "counties_sc.qpaybill_delinquent_roll": "budgeted, pager-lossy enumeration (REQUEST_BUDGET_PER_COUNTY)",
    "counties_sc.spartanburg_vacant": "City of Spartanburg registry, not the county",
    "counties_sc.spartanburg_city_condemned": "city registry, not the county",
    "city_websites.charlotte_open_data": "city of Charlotte only",
    "counties_nc.hendersonville_vacant_structures": "city of Hendersonville only",
}

_LT_RX = re.compile(r"ListingType\.([A-Z_]+)\b|listing_type\s*=\s*['\"]([a-z_]+)['\"]")
_COUNTY_DIR = {"counties_nc": "NC", "counties_sc": "SC"}


def _file_for(slug: str) -> Optional[Path]:
    if "." not in slug:
        return None
    pkg, name = slug.split(".", 1)
    p = SCRAPERS / pkg / f"{name}.py"
    if p.is_file():
        return p
    hits = sorted(SCRAPERS.rglob(f"{name}.py"))
    return hits[0] if len(hits) == 1 else None


def county_in_filename(path: Path) -> Optional[tuple[str, str]]:
    """(state, county) when the producer sits in counties_nc/ or counties_sc/ and its file name
    starts with exactly one county name ('dillon_sheriff' -> SC Dillon). Longest name wins, so
    'new_hanover_tax' is New Hanover, not a county called New."""
    st = _COUNTY_DIR.get(path.parent.name)
    if not st:
        return None
    stem = path.stem.lower()
    best = None
    for c in STATE_COUNTIES[st]:
        key = c.lower().replace(" ", "_")
        if (stem == key or stem.startswith(key + "_")) and (best is None or len(c) > len(best)):
            best = c
    return (st, best) if best else None


def feed_columns_of(path: Path) -> set[str]:
    """The feed columns a producer can emit: the listing types its code names."""
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return set()
    out = set()
    for a, b in _LT_RX.findall(text):
        lt = (a or b).lower()
        if lt in FEED_COLUMN:
            out.add(FEED_COLUMN[lt])
    return out


def _tax_roll(path: Path) -> bool:
    """A county-named delinquent-tax roll (the file says so in its name)."""
    return "delinquent" in path.stem


def screens_for(slug: str) -> list[tuple[tuple, set, str]]:
    """[(columns, coverage, basis)] a completed run of `slug` screens. Pure apart from reading
    the producer's source file."""
    if slug in EXCLUDED:
        return []
    out = [(s.columns, s.coverage(), s.note or "declared") for s in DECLARED if s.slug == slug]
    if out:
        return out
    p = _file_for(slug)
    if p is None:
        return []
    cty = county_in_filename(p)
    if not cty:
        return []
    cols = feed_columns_of(p)
    if _tax_roll(p):
        cols |= set(TAX_COLUMNS)
    return [(tuple(sorted(cols)), {cty}, "county-named producer")] if cols else []


# ---------------------------------------------------------------------------------------------
# Build / write / read
# ---------------------------------------------------------------------------------------------

def build(run_health: dict, *, generated_at: Optional[str] = None) -> dict:
    """The ledger for one run, from its run_health dict. Pure apart from reading producer files."""
    run_at = str(run_health.get("generated_at") or "")
    unhealthy_jail = set((run_health.get("enrichments") or {}).get("jail_bookings", {}).get("rosters_unhealthy") or [])
    screens: dict[str, dict[str, dict]] = {}
    failed: dict[str, dict[str, str]] = {}
    for s in run_health.get("sources") or []:
        slug, status = str(s.get("source") or ""), s.get("status")
        for cols, cov, basis in screens_for(slug):
            if slug == "national.jail_bookings":
                cov = {k for k in cov if k[1] not in unhealthy_jail}
            for col in cols:
                for st, co in sorted(cov):
                    key = f"{st}|{co}"
                    if status_ok(status):
                        e = screens.setdefault(col, {}).setdefault(key, {"sources": [], "basis": basis})
                        if slug not in e["sources"]:
                            e["sources"].append(slug)
                    else:
                        failed.setdefault(col, {}).setdefault(key, f"{slug}: {str(status)[:80]}")
    enr = run_health.get("enrichments") or {}
    for name, cols in ENRICHMENT_SCREENS.items():
        got = ((enr.get(name) or {}).get("screened")) or {}
        for col in cols:
            for key in got.get(col) or []:
                st, _, co = str(key).partition("|")
                if co and co in STATE_COUNTIES.get(st, ()):
                    e = screens.setdefault(col, {}).setdefault(
                        f"{st}|{co}", {"sources": [], "basis": "county-wide sweep (enrichment)"})
                    if f"enrichment:{name}" not in e["sources"]:
                        e["sources"].append(f"enrichment:{name}")
    for col, by in failed.items():               # a county another source screened is screened
        for key in list(by):
            if key in screens.get(col, {}):
                del by[key]
    return {
        "schema": SCHEMA,
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_at": run_at,
        "screens": {c: dict(sorted(v.items())) for c, v in sorted(screens.items())},
        "not_screened": {c: dict(sorted(v.items())) for c, v in sorted(failed.items()) if v},
        "excluded_sources": EXCLUDED,
        "cells_screened": sum(len(v) for v in screens.values()),
    }


def write_ledger(run_health: dict, out_path: Path) -> Path:
    """Write docs/screen_ledger.json beside run_health.json (same run)."""
    doc = build(run_health)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1, sort_keys=False))
    return out_path


def load(path: Path | str) -> dict:
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) and d.get("schema") == SCHEMA else {}


def fresh(ledger: dict, today: date, max_age_days: int = MAX_AGE_DAYS) -> bool:
    """The ledger describes a run no older than max_age_days before `today` (and not after it)."""
    ra = str(ledger.get("run_at") or "")[:10]
    try:
        d = date.fromisoformat(ra)
    except ValueError:
        return False
    return 0 <= (today - d).days <= max_age_days


def screened(ledger: dict, column: str, state: str, county: str) -> bool:
    return f"{state}|{county}" in ((ledger.get("screens") or {}).get(column) or {})
