#!/usr/bin/env python
"""Partial merge — fold today's NEW/FIXED source leads into the existing dashboard
with the FULL late-stage enrichment chain, WITHOUT re-scraping the ~50 unchanged
sources (their leads are preserved from docs/listings.json).

Runs only the sources we built/fixed today, scope-filters their leads, dedupes them
into the persisted dataset, then runs the same address-resolution + value + scoring
enrichers main.py runs (so probate/defendant names resolve to properties, parcels
reverse-geocode, ARV/grade/equity/distress recompute). Vision is NOT run here — the
nightly daily-vision job fills photos/condition on new leads.

Usage: ASSESSOR_CARD_ON=1 ASSESSOR_CARD_SKIP_RENDER=1 python scripts/merge_today_sources.py
"""
import asyncio
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.config import RuntimeConfig  # noqa: E402
from foreclosure_scraper.scrapers._registry import all_scrapers  # noqa: E402
from foreclosure_scraper.dedupe import dedupe  # noqa: E402
from foreclosure_scraper.main import _in_scope, _active_only  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade  # noqa: E402
from foreclosure_scraper.enrichment_geocode import enrich as enrich_geocode  # noqa: E402
from foreclosure_scraper.enrichment_address_backfill import enrich_addresses_from_owner  # noqa: E402
from foreclosure_scraper.enrichment_parcel_lookup import enrich_with_parcel_lookup  # noqa: E402
from foreclosure_scraper.enrichment_parcel_from_geo import enrich_parcel_from_geo  # noqa: E402
from foreclosure_scraper.enrichment_gis_attrs import enrich_gis_attrs  # noqa: E402
from foreclosure_scraper.enrichment_gis_derived import enrich_gis_derived  # noqa: E402
from foreclosure_scraper.enrichment_situs_address import enrich_situs_address  # noqa: E402
from foreclosure_scraper.enrichment_derived_signals import enrich_derived_signals  # noqa: E402
from foreclosure_scraper.enrichment_reo_freshness import prune_stale_reo  # noqa: E402
from foreclosure_scraper.enrichment_aggressive_address import enrich_with_aggressive_address  # noqa: E402
from foreclosure_scraper.enrichment_parcel_reverse_geo import enrich_parcel_reverse_geo  # noqa: E402
from foreclosure_scraper.enrichment_owner_mailing import enrich_owner_mailing  # noqa: E402
from foreclosure_scraper.enrichment_sc_cama import enrich_sc_cama  # noqa: E402
from foreclosure_scraper.enrichment_footprint_sqft import enrich_footprint_sqft  # noqa: E402
from foreclosure_scraper.enrichment_assessor_card import enrich_assessor_card  # noqa: E402
from foreclosure_scraper.enrichment_equity import enrich_equity  # noqa: E402
from foreclosure_scraper.distress_score import score_board  # noqa: E402
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality  # noqa: E402
from foreclosure_scraper.enrichment_multifamily_class import enrich_multifamily_class  # noqa: E402
from foreclosure_scraper.enrichment_property_kind import enrich_property_kind  # noqa: E402
from foreclosure_scraper.enrichment_fhfa_value import enrich_fhfa_value  # noqa: E402
from foreclosure_scraper.enrichment_title_risk import enrich_title_risk  # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"

# Every source we built or fixed today (2026-06-24). Unchanged sources are carried
# over from the persisted dashboard, not re-scraped.
NEW_SOURCES = {
    "national.hubzu", "national.freddie_homesteps", "national.courtlistener_adversary",
    "national.auction_dot_com", "national.xome",
    "reo.treasury_seized", "reo.usda_rd",
    "counties_sc.terry_howe_flc", "counties_sc.spartan_weekly_legals",
    "counties_sc.sc_tax_delinquent", "counties_sc.pickens_master_in_equity",
    "counties_sc.spartanburg_master_in_equity", "counties_sc.sc_public_notices",
    "counties_sc.sc_county_rosters",
    "counties_nc.nc_rod_substitute_trustee", "counties_nc.nc_rod_logan",
    "public_notices.ncpublicnotices",
    # net-new multifamily + coastal sources (2026-06-25)
    "national.crexi_multifamily", "counties_sc.sc_coastal_rosters",
    # net-new + recovered sources (2026-06-25 pm): fixed CourtListener lift-stay,
    # HUD multifamily (REAC + Section8), Charleston MIE, + dormant-but-healthy
    # county sources that scrape fine but were never surfaced + DATELESS leak fixes.
    "national.courtlistener_adversary", "national.hud_reac_inspection",
    "national.hud_section8_contracts", "counties_sc.charleston_mie",
    "counties_sc.sc_rod_acclaim", "counties_nc.cleveland_tax",
    "counties_sc.sc_state_tax_lien",
    # net-new coastal NC + newspapers (2026-06-25 eve)
    "counties_nc.nc_coastal_tax_foreclosure", "counties_nc.nc_county_tax_foreclosure",
    "counties_nc.rutherford_tax", "newspapers.post_and_courier", "newspapers.carolina_coast",
    # net-new sources (2026-06-26): SC FLC/tax + probate + DEW liens, NC GovDeals +
    # surplus + eCourts estates/divorce, New Hanover (Kania mirror), Coastland Times.
    "counties_sc.charleston_delinquent_tax", "counties_sc.horry_flc",
    "counties_sc.georgetown_civicengage", "counties_sc.colleton_tax_sale",
    "counties_sc.oconee_forfeited_land", "counties_sc.sc_probate_net",
    "counties_sc.sc_dew_lien_registry",
    "counties_nc.nc_govdeals_real_property", "counties_nc.gaston_surplus_properties",
    "counties_nc.nc_ecourts_estates", "counties_nc.nc_ecourts_divorce",
    "counties_nc.new_hanover_foreclosures", "newspapers.coastland_times",
    "counties_nc.brunswick_legal_notices",
    "counties.column_legal_notices", "law_firms.mewborn_deselms",
    "law_firms.zacchaeus",
}


def _countyless_national(li: Listing) -> bool:
    return (li.source or "").startswith("national.") and not (li.county or "").strip()


async def _scrape_new() -> list[Listing]:
    import os
    only = os.environ.get("MERGE_ONLY_SOURCES")
    active = set(only.split(",")) if only else NEW_SOURCES
    scrapers = [s for s in all_scrapers() if s.slug in active]
    print("running new/fixed scrapers:", sorted(s.slug for s in scrapers))
    out: list[Listing] = []
    for s in scrapers:
        try:
            leads = list(await s.safe_run())
        except Exception as e:  # noqa: BLE001
            print(f"  {s.slug}: ERROR {str(e)[:80]}")
            continue
        print(f"  {s.slug}: {len(leads)} ({getattr(s, 'last_outcome', '?')})")
        for li in leads:
            if not li.source:
                li.source = s.slug
            out.append(li)
    return out


# Sources whose scraper was just fixed to PURGE junk (post-sale RESULT PDFs /
# nav-chrome) — their existing carryover rows are the old junk, so drop them and
# let the fresh (purged) scrape fully replace them. Otherwise dedupe keeps the
# stale junk (the ~1216 Pickens post-sale sc_tax_delinquent rows + 18 sc_flc).
REPLACE_SOURCES = {"counties_sc.sc_tax_delinquent", "counties_sc.sc_flc"}


async def _resolve(existing: list[Listing], cfg) -> list[Listing]:
    _pre = len(existing)
    existing = [li for li in existing if li.source not in REPLACE_SOURCES]
    if _pre != len(existing):
        print(f"replace-drop: removed {_pre - len(existing)} carryover rows from purged sources (sc_tax_delinquent/sc_flc)")
    new = await _scrape_new()
    n_scope = sum(1 for li in new if _in_scope(li))
    n_active = sum(1 for li in new if _active_only(li, cfg.sale_horizon_days))
    n_cl = sum(1 for li in new if _countyless_national(li))
    print(f"new-lead filter breakdown: in_scope={n_scope}/{len(new)} active={n_active}/{len(new)} countyless={n_cl}")
    keep = [li for li in new
            if _in_scope(li) and not _countyless_national(li)
            and _active_only(li, cfg.sale_horizon_days)]
    print(f"new leads: {len(new)} -> {len(keep)} kept after scope/active filter")
    merged = dedupe(existing + keep)
    merged = [li for li in merged if not _countyless_national(li)]
    # Re-scope EVERY lead, not just the new ones — carryover from older runs
    # predates scope tightening, so out-of-footprint counties leak otherwise.
    before_scope = len(merged)
    merged = [li for li in merged if _in_scope(li)]
    print(f"merged+deduped -> {before_scope} | scope re-filter dropped {before_scope - len(merged)} -> {len(merged)}")

    # Drop sold/removed snapshot-REO (Fannie) carryover whose per-property URL
    # 404s in-browser once the uuid leaves inventory. Fail-safe (empty pull = skip).
    merged, _pstats = await prune_stale_reo(merged)
    print(f"  prune_stale_reo: {_pstats}")

    # Address-resolution chain (async) — mirrors main.py: name->property for probate/
    # defendant leads, parcel reverse-geo for stranded ones, geocode + owner contact.
    async def _step(name, coro):
        try:
            r = await coro
            print(f"  {name}: {r if isinstance(r, dict) else 'ok'}")
        except Exception as e:  # noqa: BLE001
            print(f"  {name}: ERROR {str(e)[:80]}")
    await _step("geocode#1", enrich_geocode(merged))
    # GIS steps: each individual query is already bounded (15-25s per-request
    # timeout + concurrency), so a hung county endpoint skips ONE lead, not the
    # batch. The wait_for here is only a GENEROUS pathological-hang backstop — NOT
    # a work budget — so big batches enrich to completion. Env-overridable.
    import os as _os
    _cap = lambda k, d: int(_os.environ.get(k, d))
    await _step("parcel_from_geo", asyncio.wait_for(enrich_parcel_from_geo(merged, concurrency=16), timeout=_cap("MERGE_PFG_TIMEOUT", 10800)))
    await _step("parcel_lookup", asyncio.wait_for(enrich_with_parcel_lookup(merged), timeout=_cap("MERGE_PL_TIMEOUT", 7200)))
    await _step("gis_attrs", asyncio.wait_for(enrich_gis_attrs(merged, concurrency=16), timeout=_cap("MERGE_GIS_TIMEOUT", 14400)))
    await _step("situs_address", asyncio.wait_for(enrich_situs_address(merged, concurrency=16), timeout=_cap("MERGE_SITUS_TIMEOUT", 7200)))  # parcel/GIS situs -> street_address
    await _step("address_backfill", enrich_addresses_from_owner(merged))
    await _step("aggressive_address", enrich_with_aggressive_address(merged))
    await _step("parcel_reverse_geo", enrich_parcel_reverse_geo(merged))
    await _step("geocode#2", enrich_geocode(merged))
    await _step("owner_mailing", enrich_owner_mailing(merged))
    # Images LAST — after every address/situs/geocode step, so the freshly-written
    # addresses get an aerial. Goal: an image for every addressed lead. Mapillary
    # off here (per-point street-view is slow; aerial+map+real give the coverage).
    from foreclosure_scraper.enrichment_images import enrich_with_images
    await _step("images", asyncio.wait_for(enrich_with_images(merged, use_mapillary=False), timeout=_cap("MERGE_IMAGES_TIMEOUT", 7200)))
    # FHFA-HPI fallback value (free CSV AVM) — runs after gis_attrs/sale-price so it
    # can rescale a known last sale to today's market; feeds the calc ARV ladder below.
    await _step("fhfa_value", enrich_fhfa_value(merged))
    return merged


def main() -> int:
    cfg = RuntimeConfig.from_env()
    raw = json.loads((DOCS / "listings.json").read_text())
    existing, bad = [], 0
    for d in raw:
        try:
            existing.append(Listing.model_validate(d))
        except Exception:  # noqa: BLE001
            bad += 1
    print(f"existing dashboard: {len(existing)} ({bad} unparseable)")

    merged = asyncio.run(_resolve(existing, cfg))

    # Value + score chain (sync; enrich_assessor_card runs its own loop, so it must
    # be OUTSIDE the async phase above).
    print("enrich_sc_cama:", enrich_sc_cama(merged))
    print("enrich_footprint_sqft:", enrich_footprint_sqft(merged))

    def _regrade(rows):
        vfail = 0
        for li in rows:
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
            except Exception:  # noqa: BLE001
                vfail += 1
        return vfail
    print(f"calc+grade ({_regrade(merged)} failures)")

    s = enrich_assessor_card(merged)
    print("enrich_assessor_card:", s)
    if s:
        touched = [li for li in merged if isinstance(li.raw, dict) and "assessor_card" in li.raw]
        _regrade(touched)
        print(f"re-graded {len(touched)} card-enriched leads")

    # GIS-derived last-sale/deed-age + tax-runway from the full attr bag, BEFORE
    # equity so _payoff can use the recovered sale data on no-card SC counties.
    print("enrich_gis_derived:", enrich_gis_derived(merged))
    print("enrich_equity:", enrich_equity(merged))
    print("enrich_title_risk:", enrich_title_risk(merged))
    print("distress score_board:", score_board(merged))
    # Multifamily classifier BEFORE property_kind backfill (mirrors main.py):
    # promote apartment/multi-unit distress, then guarantee non-UNKNOWN coverage.
    mfs = enrich_multifamily_class(merged)
    print("enrich_multifamily_class:", {k: v for k, v in mfs.items()
                                        if k not in ("examples", "skipped_examples")})
    enrich_property_kind(merged)
    print("enrich_derived_signals:", enrich_derived_signals(merged))
    print("enrich_data_quality:", enrich_data_quality(merged))

    summary = {
        "by_source": dict(collections.Counter(li.source for li in merged if li.source)),
        "notes": "partial merge: today's new/fixed sources + full enrichment (no full re-scrape)",
    }
    lp, mp = write_artifact(merged, summary, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
