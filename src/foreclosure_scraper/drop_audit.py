"""Which scrapers lost EVERY row to the scope / active / flip filters, counted by row identity.

main.run() warns 'orchestrator.source_all_filtered' for a scraper that returned rows of which none
reached dedupe, so a mis-routed source (a DATELESS_OK_SOURCES omission dropping every dateless row)
is caught instead of reading 'OK (N)'. It counted the survivors by `li.source` and compared that to
the scraper's slug, which is wrong for every scraper whose rows carry another source string:

  * per-layer / per-registry slugs: counties_generic.arcgis_distress_layers emits
    'counties_generic.arcgis_distress.<layer>', state_contamination '...state_contamination.<registry>',
    epa_frs_sites 'counties_generic.epa_frs.<program>', sc_probate_notices '....<newspaper>';
  * scrapers that emit under another module's name: kinston_proposed_demolition, the Raleigh
    structure fires and the Rocky Mount survey publish as arcgis_distress layers;
  * national.stealth_handoff replays the Mac's rows under their own sources.

On the 2026-10-08 gated run 26 sources were warned about. 7 of them had rows on that run's dot_ocr
checkpoint under the source strings they emit (state_contamination 53,827 scraped, arcgis_distress_
layers 14,538, epa_frs_sites 3,714, sc_probate_notices 890, rocky_mount_blight_survey 618,
raleigh_structure_fires 396, kinston_proposed_demolition 45) and stealth_handoff (27,888) keeps each
row's own source by design: false alarms that bury the real ones (gaston_tax_foreclosures 81
scraped, 0 kept; cws_marketing 17; henderson_tax 15; ...).

all_filtered_sources() counts by object identity: a scraper's rows are the Listing objects its
safe_run() returned, and the filters keep or drop those same objects, so no slug matching is needed.
Sources added outside the scraper results (carryover replays, lis-pendens discovery) fall back to
the slug test, now prefix-aware.
"""
from __future__ import annotations

from typing import Iterable, Mapping


def all_filtered_sources(results: Iterable[tuple[str, list]], by_source: Mapping[str, int],
                         survivors: Iterable) -> list[tuple[str, int]]:
    """[(slug, scraped)] for every source that scraped rows of which none survived.

    `results`: main.run()'s [(slug, listings)] from the scrapers; `by_source`: its per-slug scrape
    counts (also holds the carryover / discovery slugs); `survivors`: the rows left after the
    scope, active and flip filters. Pure; holds one set of object ids."""
    alive = list(survivors)
    alive_ids = {id(li) for li in alive}
    out: list[tuple[str, int]] = []
    judged: set[str] = set()
    for slug, listings in results:
        rows = listings or []
        if not rows:
            continue        # an empty scrape: a carryover replay may still be counted below
        judged.add(slug)
        if not any(id(li) in alive_ids for li in rows):
            out.append((slug, len(rows)))
    names = None
    for slug, n in by_source.items():
        if slug in judged or not n:
            continue
        if names is None:
            names = {str(getattr(li, "source", "") or "") for li in alive}
        if not any(s == slug or s.startswith(slug + ".") for s in names):
            out.append((slug, int(n)))
    return out


# ---------------------------------------------------------------------------------------------
# Countyless national / REO rows (main.run: orchestrator.drop_countyless_national, 3,767 rows on
# the 2026-10-08 gated run). The drop is right for a row nothing can place, but main.run has no
# ZIP/city -> county step (scripts/backfill_missing_county.py is a manual board pass), so a
# national row that arrives with a city and no county is dropped although its county is known.
# Measured on the Mac stealth hand-off of 2026-10-08 (51,730 rows): 906 national rows had no
# county; every one carried a city and 898 an NC/SC ZIP (landandfarm 645, zillow_foreclosures
# 199, xome 27, trulia 13, ...). The 146-county city gazetteer (_bankruptcy_city_to_county, the
# table fdic_failed_banks and the obituary matcher already use) and the ZIP table built offline
# from the parcel caches (_zip_to_county, scripts/build_zip_county_table.py, 543 one-county ZIPs)
# place 605 of them (city 156, ZIP 213, both agreeing 236; the 3 where they disagree are left).
# ---------------------------------------------------------------------------------------------

def is_countyless_national(li) -> bool:
    """main.run's _countyless_national rule: a national.* / reo.* row with no county."""
    src = str(getattr(li, "source", "") or "")
    return (src.startswith("national.") or src.startswith("reo.")) and not str(
        getattr(li, "county", "") or "").strip()


def fill_county_from_city(listings) -> dict:
    """Give every countyless national / REO row the county its (city, state) names in the NC/SC
    gazetteer, or failing that the one county its ZIP lies in (_zip_to_county, built offline from
    the parcel caches by scripts/build_zip_county_table.py), stamped raw['county_backfill'] =
    {county, evidence: 'city' | 'zip' | 'city+zip', basis}. When city and ZIP name different
    counties the row is left alone. Must run BEFORE the post-enrichment scope re-pass, so a flip
    placed this way is still judged against the footprint. Never overwrites a county.
    Returns {'filled': n, 'by_source': {...}, 'by_evidence': {...}, 'conflicts': n, 'left': n}."""
    from ._bankruptcy_city_to_county import bankruptcy_county_for
    from ._zip_to_county import county_for_zip
    filled: dict[str, int] = {}
    by_ev: dict[str, int] = {}
    left = conflicts = 0
    for li in listings:
        if not is_countyless_national(li):
            continue
        st = getattr(li, "state", None)
        by_city = bankruptcy_county_for(getattr(li, "city", None), st)
        by_zip = county_for_zip(getattr(li, "zip_code", None), st)
        if by_city and by_zip and by_city != by_zip:
            conflicts += 1
            continue
        cty = by_city or by_zip
        if not cty:
            left += 1
            continue
        ev = "city+zip" if (by_city and by_zip) else ("city" if by_city else "zip")
        li.county = cty
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw.setdefault("county_backfill", {
            "county": cty, "evidence": ev,
            "basis": "_bankruptcy_city_to_county gazetteer / _zip_to_county (parcel caches)"})
        filled[li.source] = filled.get(li.source, 0) + 1
        by_ev[ev] = by_ev.get(ev, 0) + 1
    return {"filled": sum(filled.values()), "by_source": filled, "by_evidence": by_ev,
            "conflicts": conflicts, "left": left}


def count_by_source(listings, pred) -> dict[str, int]:
    """{source: rows} of the rows `pred` selects, biggest first: what a drop removes, per source."""
    out: dict[str, int] = {}
    for li in listings:
        try:
            if pred(li):
                s = str(getattr(li, "source", "") or "?")
                out[s] = out.get(s, 0) + 1
        except Exception:  # noqa: BLE001 - a row the predicate chokes on is not counted
            continue
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def removed_by_source(before, after, top: int = 15) -> dict[str, int]:
    """{source: rows} of the rows in `before` that are not in `after` (by object identity), biggest
    first, at most `top` sources: what one filter removed, per source, without re-running its
    predicate. For the in_scope / active / flip log lines of main.run (fresh rows are not persisted,
    so these counts are the only record of what each filter took)."""
    kept = {id(li) for li in after}
    out: dict[str, int] = {}
    for li in before:
        if id(li) not in kept:
            s = str(getattr(li, "source", "") or "?")
            out[s] = out.get(s, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:top])
