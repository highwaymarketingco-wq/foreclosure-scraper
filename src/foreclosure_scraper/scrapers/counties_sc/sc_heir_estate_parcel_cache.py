"""Heir / estate owner-of-record parcels for SC, read from the already-downloaded
`parcel_cache` SQLite files instead of a live GIS query.

nc_heir_estate_parcels.py (NC statewide + 8 Upstate/broader SC counties) proved the
same owner-of-record retitling signal ("<NAME> HEIRS", "ESTATE OF <NAME>") works
across many SC county GIS layers. But that producer's SC coverage runs through
`enrichment_owner_mailing.COUNTY_GIS`, a DIFFERENT county registry from
`parcel_cache.PARCEL_LAYERS` (the one this project already bulk-downloads for
mailing-address/vacant-lot/comps work). As of 2026-10-19, 18 of parcel_cache's SC
counties carry a cached `owner` column that `nc_heir_estate_parcels.py` never reads at
all (York/Charleston/Beaufort are the only overlap, and those three stay on the live
producer) -- the data was already on disk, just never scanned for this signal.

Live-sampled all 18 (`scripts/` scratch scan, 2026-10-19, pure local, zero network)
with the SAME classifiers nc_heir_estate_parcels.py uses (`_is_decedent`/
`_excluded_row`, imported here, not reimplemented): ~8,100 real decedent-titled
parcels after exclusions, cleanly separated from noise (LLC/HOA/church/bank names,
"LIFE ESTATE"/"REAL ESTATE"/"ESTATES" false positives). Greenville alone came back to
38 after fixing a real gap the sampling found in the shared classifier (Greenville's
cache spells it "LIFE-ESTATE", hyphen, which the old `_EXCLUDE` tuple's literal
"LIFE ESTATE" substring never matched -- see that module's 2026-10-19 comment) --
matching the ~40 Greenville parcels an entirely separate live check already found and
reported in project_gap_matrix_sweep1_2026-10-18.md. That match is the calibration
check for this module: the same signal, read a different way, lands on the same
number.

Pure-local, no network, no rate-limit risk: reads a SQLite file already on disk. Each
physical parcel is indexed under 1-3 id-format variants in the cache (one row per
variant) -- rows are deduped on (owner, address, acreage, market_value, tax_value,
sale_date) before classification so one parcel emits exactly one Listing.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ... import parcel_cache
from ..counties_nc.nc_heir_estate_parcels import (
    _excluded_row,
    _heir_names,
    _is_decedent,
    _HEIR_TOKEN,
)

log = structlog.get_logger()

#: SC counties already served live by nc_heir_estate_parcels.py's own
#: `_HEIR_COUNTIES` (enrichment_owner_mailing.COUNTY_GIS, a different registry from
#: parcel_cache) -- never double-source the same county from two producers.
_ALREADY_LIVE_COVERED = frozenset({"York", "Charleston", "Beaufort"})

#: Every parcel_cache SC county (PARCEL_LAYERS + the SC half of SC_DUAL_LAYERS) whose
#: `map` carries an `owner` field, minus the three already live-covered above.
#: Resolved at import time from parcel_cache's own config, not hand-copied, so a county
#: added to parcel_cache with an owner field is picked up here automatically.
def _candidate_counties() -> tuple[str, ...]:
    out: set[str] = set()
    for name, cfg in parcel_cache.PARCEL_LAYERS.items():
        if cfg.get("state") == "SC" and "owner" in (cfg.get("map") or {}):
            out.add(name)
    for name, cfg in parcel_cache.SC_DUAL_LAYERS.items():
        if "owner" in (cfg.get("map") or {}):
            out.add(name)
    return tuple(sorted(out - _ALREADY_LIVE_COVERED))


#: Columns read from the cache's `parcels` table (all live in parcel_cache._COLS),
#: plus the table's own `id` (one of the county's id_fields, re-keyed per variant).
_READ_COLS = ("owner", "address", "owner_mailing", "acreage", "market_value",
              "tax_value", "sale_date", "land_use")
#: The dedup key: a physical parcel's 1-3 id-variant rows share identical values here
#: (they are the SAME source record, just re-keyed by id format), so grouping on this
#: tuple collapses variants to one row per real parcel without needing to know each
#: county's own id_fields order.
_DEDUP_COLS = ("owner", "address", "acreage", "market_value", "tax_value", "sale_date")


def _county_rows(county: str) -> list[dict]:
    """One deduped row per physical parcel for `county`'s cache, or [] if the cache
    file is missing/unreadable (never raises -- a missing cache is a skip, not a
    scraper failure).

    `id` is picked as the SHORTEST of each physical parcel's 1-3 id-variant strings
    (observed live across Berkeley/Sumter/Dorchester/Horry: the zero-expanded long
    form is always a variant of a shorter dashed/undashed form that matches the
    board's own parcel_id convention for that county -- a best-effort pick, not
    verified per-county the way parcel_cache.py's own per-county comments are, so a
    county whose convention differs just gets an id string that still identifies the
    right physical parcel for GIS/cache re-lookup even if it isn't the exact string
    another board row for the same parcel already uses).
    """
    try:
        path = parcel_cache._db_path(county, "SC")  # noqa: SLF001
    except Exception:  # noqa: BLE001 - no SC layer configured for this name
        return []
    if not path.exists():
        return []
    cols_sql = ", ".join(_READ_COLS)
    groups: dict[tuple, dict] = {}
    try:
        con = sqlite3.connect(str(path))
        try:
            rows = con.execute(
                f"SELECT id, {cols_sql} FROM parcels "
                "WHERE owner IS NOT NULL AND owner != ''"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error as exc:  # noqa: BLE001 - a corrupt/locked cache is a skip
        log.warning("sc_heir_cache.read_fail", county=county, error=str(exc)[:160])
        return []
    for row in rows:
        pid, *rest = row
        key = tuple(dict(zip(_READ_COLS, rest)).get(c) for c in _DEDUP_COLS)
        existing = groups.get(key)
        if existing is None:
            rec = dict(zip(_READ_COLS, rest))
            rec["_id"] = pid
            groups[key] = rec
        elif pid and (not existing.get("_id") or len(str(pid)) < len(str(existing["_id"]))):
            existing["_id"] = pid
    return list(groups.values())


def _parse_iso_date(v) -> datetime | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt)
        except ValueError:
            continue
    return None


class SCHeirEstateParcelCache(BaseScraper):
    slug = "counties_sc.sc_heir_estate_parcel_cache"
    name = "SC Heir / Estate Owner-of-Record Parcels (parcel_cache, dateless)"
    category = "motivated_seller"
    expected_min_count = 5
    # Pure local SQLite reads across ~18 counties (largest, Horry, is ~280k deduped
    # owner rows) -- no network wait, but still generous: a slow disk / cold cache
    # file should not look like a scraper failure.
    timeout_s = 120.0
    requires_apify = False
    optional = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.run_stats: dict = {"counties": 0, "rows_read": 0, "kept": 0}

    async def fetch(self) -> Iterable[Listing]:
        out = self.partial
        for county in _candidate_counties():
            rows = _county_rows(county)
            if not rows:
                continue
            self.run_stats["counties"] += 1
            self.run_stats["rows_read"] += len(rows)
            kept = 0
            cfg = parcel_cache.resolve_layer_cfg(county, "SC") or {}
            source_url = cfg.get("url") or ""
            for rec in rows:
                owner = (rec.get("owner") or "").strip()
                if not owner:
                    continue
                owner_fields = [owner]
                if not _is_decedent(owner_fields) or _excluded_row(owner_fields):
                    continue
                mailing = rec.get("owner_mailing")
                mail = str(mailing).strip() if mailing else None
                # Same convention as enrichment_vacant_landuse.py: a bare numeric DOR
                # code (Horry's LandUseCode) is not human-readable text, so it is never
                # written to Listing.land_use -- left for that enrichment's own
                # improvement-value-based reading instead.
                lu_raw = str(rec.get("land_use") or "").strip()
                lu = lu_raw if (lu_raw and not lu_raw.isdigit()) else None
                li = Listing(
                    source=self.slug,
                    source_url=source_url,
                    acreage=rec.get("acreage"),
                    market_value=rec.get("market_value"),
                    tax_value=rec.get("tax_value"),
                    land_use=lu,
                    listing_type=ListingType.ESTATE_LEAD,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county=county,
                    street_address=(rec.get("address") or None),
                    parcel_id=(str(rec["_id"]).strip() if rec.get("_id") else None),
                    defendant=owner,
                    sale_date=_parse_iso_date(rec.get("sale_date")),
                    description=f"Heir/estate owner of record ({owner}) in "
                                f"{county} County, SC",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={
                        "heir_estate": {
                            "owner_of_record": owner,
                            "heir_names": _heir_names(owner_fields),
                            "mailing": mail,
                            "match": "heirs" if _HEIR_TOKEN.search(owner) else "estate",
                            "source": "parcel_cache",
                        },
                        "relationship_signal": {
                            "kind": "probate",
                            "keyword": "heir_estate_owner_of_record",
                            "source": self.slug,
                        },
                    },
                )
                out.append(li)
                kept += 1
            self.run_stats["kept"] += kept
            log.info("sc_heir_cache.county", county=county, rows=len(rows), kept=kept)
        log.info("sc_heir_cache.done", listings=len(out), **self.run_stats)
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = SCHeirEstateParcelCache()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)} stats={s.run_stats}")
        for li in rows[:12]:
            print(f"  {li.county:12} {(li.defendant or '')[:40]:40} "
                  f"situs={(li.street_address or '')[:34]}")

    asyncio.run(_main())
