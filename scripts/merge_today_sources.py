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
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Own checkpoint directory, separate from the main engine's data/checkpoint/.
# They never run concurrently — this script's caller waits for the main run
# to release the board first — but a distinct directory means a checkpoint
# here is never ambiguous about which process it belongs to. Must be set
# BEFORE importing foreclosure_scraper.checkpoint: CHECKPOINT_DIR is a
# module-level constant read from the env once, at import time.
os.environ.setdefault("FORECLOSURE_CHECKPOINT_DIR", "data/checkpoint_merge")

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper import checkpoint  # noqa: E402
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
from foreclosure_scraper.enrichment_dew_liens import enrich_dew_liens  # noqa: E402
from foreclosure_scraper.enrichment_hud_reac_address import enrich_hud_reac_address  # noqa: E402
from foreclosure_scraper.enrichment_resolve_name_to_property import enrich_resolve_name_to_property  # noqa: E402
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed  # noqa: E402
from foreclosure_scraper.enrichment_court_owner_verify import enrich_court_owner_verify  # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact, load_board  # noqa: E402
from foreclosure_scraper.outreach import generate_outreach  # noqa: E402

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
    "public_notices.ncnotices",
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
    "counties_nc.nc_govdeals_real_property", "counties_nc.gaston_surplus_properties",
    "counties_nc.nc_ecourts_estates", "counties_nc.nc_ecourts_divorce",
    "counties_nc.new_hanover_foreclosures", "newspapers.coastland_times",
    "counties_nc.brunswick_legal_notices",
    "counties.column_legal_notices", "law_firms.mewborn_deselms",
    "law_firms.zacchaeus",
    # net-new (2026-06-27): Greenwood newspaper + Spartanburg FLC tax-sale PDF
    "newspapers.index_journal", "counties_sc.spartanburg_flc",
    # motivated-seller life-event + delinquency sources (2026-06-30): these were
    # pipeline-wired (DATELESS_OK + main.py) but never added here, so the partial
    # merge never LANDED them onto the board. The ~8.6k un-landed leads live here.
    "counties_nc.buncombe_elderly", "counties_nc.buncombe_delinquent_tax",
    "counties_nc.asheville_helene", "counties_sc.spartanburg_delinquent_tax",
    "counties_sc.cherokee_delinquent_tax", "public_notices.gannett_obituaries",
    "national.servicelink_auction", "national.gsa_realproperty",
    # net-new (2026-06-30 pm): funeral-home CMS obituary RSS (Frazer + ltobits) —
    # pre-probate heir leads, non-overlapping with the Gannett newspaper obituaries.
    "public_notices.funeral_home_rss",
    # net-new (2026-06-30 night): NC delinquent-tax breadth — the full 105-369
    # rolls for non-Buncombe W-NC counties, closing the NC-vs-SC gap. PTS Cloud
    # API (Madison/Henderson ~3k) + county .gov PDFs (Lincoln/Catawba/McDowell ~9k).
    "counties_nc.nc_ptscloud_delinquent_tax",
    "counties_nc.nc_county_pdf_delinquent_tax",
    # net-new (2026-08-06): contamination spine + the SC probate answer.
    # sc_probate_notices is the important one — 886 estates, 885 net-new even
    # compared on decedent NAME, and 884 of them carry a personal-representative
    # mailing address, which is the field the board is thinnest on.
    "counties_sc.sc_probate_notices",
    "counties_sc.sc_ust_registry",
    "counties_generic.state_contamination",
    "counties_generic.epa_frs_sites",
    "counties_generic.arcgis_distress_layers",
    "national.auction_bank_reo",
}


def _countyless_national(li: Listing) -> bool:
    return (li.source or "").startswith("national.") and not (li.county or "").strip()


async def _scrape_new() -> list[Listing]:
    import os
    only = os.environ.get("MERGE_ONLY_SOURCES")
    active = set(only.split(",")) if only else NEW_SOURCES
    scrapers = [s for s in all_scrapers() if s.slug in active]
    # A slug that matches nothing contributes zero leads and says nothing about
    # it, so the merge looks like it ran when a source was never touched. That
    # is how "public_notices.ncpublicnotices" (real slug: ...ncnotices) sat in
    # this list contributing nothing. Unknown slugs are now loud.
    unknown = sorted(active - {s.slug for s in scrapers})
    if unknown:
        raise SystemExit(
            f"merge_today_sources: {len(unknown)} slug(s) match no scraper and "
            f"would silently contribute nothing: {unknown}")
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
    # HUD REAC complex name -> real street + lat/lng (before geocode/parcel so the
    # filled geo unlocks the GIS chain), then the standard address chain.
    import os as _os0
    _FAST = _os0.environ.get("MERGE_FAST") == "1"
    await _step("hud_reac_address", enrich_hud_reac_address(merged))  # ONE bulk query, safe
    # NC PTS Cloud land-records: parcel# -> situs address + assessed value for the
    # Henderson/Rutherford/Burke delinquent-tax leads (they land with no address).
    # Reliable Azure-hosted JSON API (not the flaky county GIS), so it runs even in
    # FAST mode — it's the thing that gives those leads an address to geocode/image.
    from foreclosure_scraper.enrichment_lrcpwa_parcel import enrich_lrcpwa_parcel
    await _step("lrcpwa_parcel", enrich_lrcpwa_parcel(merged))
    # geocode#1 is a per-lead network LOOP — on a flaky connection a single wedged
    # socket blocks the event loop and the budget-bail can't fire (observed tonight).
    # Skip in FAST so the post-scrape chain is local-only (CAMA CSV + pure-python calc).
    if not _FAST:
        await _step("geocode#1", enrich_geocode(merged))
    # GIS steps: each individual query is already bounded (15-25s per-request
    # timeout + concurrency), so a hung county endpoint skips ONE lead, not the
    # batch. The wait_for here is only a GENEROUS pathological-hang backstop — NOT
    # a work budget — so big batches enrich to completion. Env-overridable.
    import os as _os
    _cap = lambda k, d: int(_os.environ.get(k, d))
    # MERGE_FAST=1 — skip the ENTIRE per-lead GIS/address/image chain. Those steps
    # (parcel_from_geo, parcel_lookup, gis_attrs, situs, owner-search backfill,
    # aggressive-address, Nominatim reverse-geo, 2nd geocode, owner-mailing, images,
    # fhfa, dew) hit gov GIS endpoints that intermittently EVENT-LOOP-BLOCK — a sync
    # hang the asyncio.wait_for can NOT cancel (observed twice, 45min+ silent past a
    # 15min timeout). We keep the proven-bounded value path: geocode#1 (budget-bailed),
    # SC CAMA (bulk CSV), the name-resolver (budget-bailed) below, then calc/grade.
    # GIS parcel/value/address depth fills on the next STABLE full run.
    FAST = _os.environ.get("MERGE_FAST") == "1"
    if not FAST:
        await _step("parcel_from_geo", asyncio.wait_for(enrich_parcel_from_geo(merged, concurrency=16), timeout=_cap("MERGE_PFG_TIMEOUT", 10800)))
        await _step("parcel_lookup", asyncio.wait_for(enrich_with_parcel_lookup(merged), timeout=_cap("MERGE_PL_TIMEOUT", 7200)))
        await _step("gis_attrs", asyncio.wait_for(enrich_gis_attrs(merged, concurrency=16), timeout=_cap("MERGE_GIS_TIMEOUT", 14400)))
        await _step("situs_address", asyncio.wait_for(enrich_situs_address(merged, concurrency=16), timeout=_cap("MERGE_SITUS_TIMEOUT", 7200)))  # parcel/GIS situs -> street_address
        await _step("address_backfill", enrich_addresses_from_owner(merged))
        await _step("aggressive_address", enrich_with_aggressive_address(merged))
        await _step("parcel_reverse_geo", enrich_parcel_reverse_geo(merged))
        await _step("geocode#2", enrich_geocode(merged))
        await _step("owner_mailing", enrich_owner_mailing(merged))
        # Images LAST — after every address/situs/geocode step. Mapillary off here.
        from foreclosure_scraper.enrichment_images import enrich_with_images
        await _step("images", asyncio.wait_for(enrich_with_images(merged, use_mapillary=False), timeout=_cap("MERGE_IMAGES_TIMEOUT", 7200)))
        # FHFA-HPI fallback value + SC DEW lien cross-ref.
        await _step("fhfa_value", enrich_fhfa_value(merged))
        await _step("dew_liens", enrich_dew_liens(merged))
    # name->property RESOLVER — pins obituary/probate/elderly NAME-ONLY leads to a
    # parcel via the county GIS owner-name index. Also per-lead GIS, so in FAST mode
    # it runs as a SEPARATE pass after the merge lands (decoupled from the risky GIS).
    if not FAST:
        await _step("resolve_name_to_property", enrich_resolve_name_to_property(merged))
        # Document OCR — free (Gemini/GitHub/Groq), lifts owner+address+debt$ out of
        # scanned notice/deed docs. Per-lead network, so FAST landing skips it too.
        from foreclosure_scraper.enrichment_doc_ocr import enrich_doc_ocr
        await _step("doc_ocr", enrich_doc_ocr(merged))

    # This is the expensive part — the async chain above measured 16+ hours on
    # 2026-08-08, and a laptop power loss killed it with zero disk writes:
    # the exact "44.6h run, nothing saved" failure checkpoint.py exists to
    # prevent, just never wired into THIS script. Checkpoint the instant the
    # chain finishes so a crash in the sync valuation/scoring phase below
    # only costs that phase, never a re-run of this one.
    checkpoint.save(merged, "resolved")
    return merged


def main() -> int:
    cfg = RuntimeConfig.from_env()
    # FAST landing: also skip the two per-lead NETWORK steps in the sync value
    # chain (footprint_sqft hits SC ArcGIS per-lead; assessor_card fetches cards).
    # On a flaky link these turn a landing into a multi-hour slog. Leads still land
    # fully valued via sc_cama + tax_owed + equity + tenure; these SC refinements
    # come on the stable weekly full run.
    import os as _osm
    _FAST = _osm.environ.get("MERGE_FAST") == "1"
    # Resume onto a checkpoint from a killed prior attempt, if one is fresh
    # enough. The enrichers this script runs are all idempotent (they only
    # target leads still missing the field they fill), so it is always safe
    # to skip straight to the sync valuation/scoring phase on a checkpointed
    # board rather than re-running the ~16h address-resolution chain that
    # already completed once. checkpoint.load() returns None on no checkpoint,
    # a checkpoint older than FORECLOSURE_CHECKPOINT_MAX_AGE_H (default 48h),
    # or a corrupt file — any of which falls through to the normal cold start.
    resumed = checkpoint.load()
    if resumed:
        age = checkpoint.age_hours()
        print(f"RESUMING from checkpoint: {len(resumed)} leads, "
              f"{f'{age:.1f}h old' if age is not None else 'age unknown'} — "
              f"skipping the address-resolution chain")
        merged = resumed
    else:
        # Load via load_board() so the lazy-detail sidecar (listings_detail.json:
        # vision/comps/cama/foreclosure_sold_comps/rent_comps) is merged back into
        # each lead's .raw. A plain json.loads of listings.json alone would strip
        # those keys, and write_artifact would then re-emit an EMPTY sidecar,
        # wiping the detail. load_board returns Listing objects with the sidecar
        # already folded in (it silently skips unparseable records).
        existing = load_board(DOCS)
        print(f"existing dashboard: {len(existing)}")
        merged = asyncio.run(_resolve(existing, cfg))

    # Value + score chain (sync; enrich_assessor_card runs its own loop, so it must
    # be OUTSIDE the async phase above).
    print("enrich_sc_cama:", enrich_sc_cama(merged))
    if not _FAST:
        print("enrich_footprint_sqft:", enrich_footprint_sqft(merged))
    else:
        print("enrich_footprint_sqft: SKIPPED (MERGE_FAST)")
    # Strip wrong-property geo-snaps off court leads (defendant surname mismatch)
    # BEFORE valuation so a stripped lead doesn't keep a bogus ARV.
    print("enrich_court_owner_verify:", enrich_court_owner_verify(merged))
    # Fold each tax source's owed amount into raw['tax_owed'] + cross-ref by parcel.
    print("enrich_tax_owed:", enrich_tax_owed(merged))

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

    if not _FAST:
        s = enrich_assessor_card(merged)
        print("enrich_assessor_card:", s)
        if s:
            touched = [li for li in merged if isinstance(li.raw, dict) and "assessor_card" in li.raw]
            _regrade(touched)
            print(f"re-graded {len(touched)} card-enriched leads")
    else:
        print("enrich_assessor_card: SKIPPED (MERGE_FAST)")

    # GIS-derived last-sale/deed-age + tax-runway from the full attr bag, BEFORE
    # equity so _payoff can use the recovered sale data on no-card SC counties.
    print("enrich_gis_derived:", enrich_gis_derived(merged))
    # Owner tenure (long-held = high-equity proxy) — local, from the GIS sale year.
    from foreclosure_scraper.enrichment_tenure import enrich_tenure
    print("enrich_tenure:", enrich_tenure(merged))
    # Each scoring/tagging step is wrapped: one lead's edge-case data must never
    # crash the run before write_artifact — a multi-hour scrape has to always land.
    def _safe(label, fn):
        try:
            r = fn()
            if isinstance(r, dict):
                r = {k: v for k, v in r.items() if k not in ("examples", "skipped_examples")}
            print(f"{label}:", r)
        except Exception as e:  # noqa: BLE001
            print(f"{label}: ERROR {type(e).__name__}: {str(e)[:120]}")
    from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit
    from foreclosure_scraper.enrichment_buyer_match import enrich_buyer_match
    _safe("enrich_equity", lambda: enrich_equity(merged))
    _safe("enrich_title_risk", lambda: enrich_title_risk(merged))
    _safe("distress score_board", lambda: score_board(merged))
    _safe("strategy_fit", lambda: enrich_strategy_fit(merged))
    _safe("buyer_match", lambda: enrich_buyer_match(merged))
    _safe("enrich_multifamily_class", lambda: enrich_multifamily_class(merged))
    _safe("enrich_property_kind", lambda: enrich_property_kind(merged))
    _safe("enrich_derived_signals", lambda: enrich_derived_signals(merged))
    _safe("enrich_data_quality", lambda: enrich_data_quality(merged))

    # Final post-enrich dedupe — mirrors main.py's H1 FIX (main.py ~896). The
    # dedupe at _resolve() ran BEFORE parcel/GIS backfill filled parcel_id, so
    # rows for the same property fell through dedupe_key()'s 'url:' branch and
    # survived. Re-running here, after the whole chain nailed parcel/county,
    # collapses those late-revealed twins so duplicate-property rows don't ship.
    _pre_dedupe2 = len(merged)
    merged = dedupe(merged)
    print(f"post-enrich dedupe: {_pre_dedupe2} -> {len(merged)} "
          f"(collapsed {_pre_dedupe2 - len(merged)})")

    # Second checkpoint — the sync valuation/scoring phase above is shorter
    # than the address-resolution chain but not instant (assessor_card runs
    # its own per-lead loop), so this covers a crash there too.
    checkpoint.save(merged, "scored")

    summary = {
        "by_source": dict(collections.Counter(li.source for li in merged if li.source)),
        "notes": "partial merge: today's new/fixed sources + full enrichment (no full re-scrape)",
    }
    # Refresh outreach mail-merge list + CRM so the direct-mail batch stays current.
    try:
        print("generate_outreach:", generate_outreach(merged))
    except Exception as e:  # noqa: BLE001
        print("generate_outreach: ERROR", str(e)[:80])
    lp, mp = write_artifact(merged, summary, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name}")
    # Published successfully — drop the checkpoint so the NEXT invocation of
    # this script starts clean instead of resuming onto a board that already
    # shipped (which would silently republish stale data as if fresh).
    checkpoint.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
