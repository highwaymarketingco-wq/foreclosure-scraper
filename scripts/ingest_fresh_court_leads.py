#!/usr/bin/env python
"""Ingest docs/fresh_court_leads.json (manually-gathered public court/land leads)
into the dashboard with the SAME late-stage enrichment chain main.py runs — WITHOUT
re-scraping. Mirrors scripts/merge_today_sources.py, but the lead source is the
serialized-Listing JSON file instead of live scrapers.

Provenance: these rows were collected by the operator via the manual public-records
lane (they run the normal public search in their own browser and save the results;
offline parsers turn the saved pages into serialized Listing dicts). We only load
and merge what they already retrieved.

Two modes:
  MERGE_FAST=1  -> LOCAL landing only (dedupe + CAMA/tax/equity/calc/grade/score).
                  No per-lead GIS/image/geocode network loops -> can't hang. Use to
                  land the leads on the board fast; depth fills on a later pass.
  (default)     -> full address-resolution + GIS + images chain (bounded by the
                  MERGE_*_TIMEOUT caps), same as merge_today_sources.

Usage:
  MERGE_FAST=1 uv run python scripts/ingest_fresh_court_leads.py
"""
import asyncio
import collections
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.config import RuntimeConfig  # noqa: E402
from foreclosure_scraper.dedupe import dedupe  # noqa: E402
from foreclosure_scraper.main import _in_scope  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade  # noqa: E402
from foreclosure_scraper.enrichment_geocode import enrich as enrich_geocode  # noqa: E402
from foreclosure_scraper.enrichment_address_backfill import enrich_addresses_from_owner  # noqa: E402
from foreclosure_scraper.enrichment_parcel_lookup import enrich_with_parcel_lookup  # noqa: E402
from foreclosure_scraper.enrichment_parcel_from_geo import enrich_parcel_from_geo  # noqa: E402
from foreclosure_scraper.enrichment_gis_attrs import enrich_gis_attrs  # noqa: E402
from foreclosure_scraper.enrichment_gis_derived import enrich_gis_derived  # noqa: E402
from foreclosure_scraper.enrichment_situs_address import enrich_situs_address  # noqa: E402
from foreclosure_scraper.enrichment_derived_signals import enrich_derived_signals  # noqa: E402
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
FRESH = DOCS / "fresh_court_leads.json"

# Terminal / closed dispositions — the matter is resolved, not an actionable lead.
# Mirrors main._active_only's terminal set.
_TERMINAL = {
    "withdrawn", "cancelled", "canceled", "rescinded", "sold", "completed",
    "redeemed", "dismissed", "dismissed/settled", "satisfied", "disposed", "closed",
}


def _load_fresh() -> list[Listing]:
    raw = json.loads(FRESH.read_text())
    out, bad = [], 0
    for rec in raw:
        try:
            li = Listing.model_validate(rec)
            if not li.source:
                continue
            out.append(li)
        except Exception:  # noqa: BLE001
            bad += 1
    print(f"loaded {len(out)} listings from {FRESH.name} ({bad} unparseable skipped)")
    return out


def _active_keep(li: Listing) -> bool:
    """Inclusive active-filter for manually-gathered leads: drop only TERMINAL
    dispositions and clearly-stale past-dated sales. Unlike main._active_only we do
    NOT drop dateless leads by source whitelist — lis-pendens / divorce / probate
    are dateless by nature and are exactly the motivated-seller signals to keep."""
    if li.auction_status and li.auction_status.lower() in _TERMINAL:
        return False
    if li.sale_date is None:
        return True  # dateless motivated-seller signal — keep
    sale = li.sale_date
    if sale.tzinfo is not None:
        sale = sale.replace(tzinfo=None)
    grace = 14 if li.state in ("NC", "SC") else 2
    if sale < datetime.utcnow() - timedelta(days=grace):
        return False  # the sale already happened -> stale
    return True


def _scope_keep(li: Listing) -> bool:
    """_in_scope, but keep county-sourced court leads whose county isn't resolved
    yet (they belong to a specific footprint county by construction; the resolver
    + next full run will place/re-scope them)."""
    if _in_scope(li):
        return True
    if not (li.county or "").strip() and (li.source or "").startswith("counties_"):
        return True
    return False


async def _resolve(existing: list[Listing], cfg) -> list[Listing]:
    fresh = _load_fresh()
    n_term = sum(1 for li in fresh if not _active_keep(li))
    fresh = [li for li in fresh if _active_keep(li)]
    print(f"active filter: dropped {n_term} terminal/stale -> {len(fresh)} kept")

    merged = dedupe(existing + fresh)
    before_scope = len(merged)
    merged = [li for li in merged if _scope_keep(li)]
    print(f"merged+deduped: {len(existing)} existing + fresh -> {before_scope} "
          f"| scope-filter -> {len(merged)} (dropped {before_scope - len(merged)})")

    FAST = os.environ.get("MERGE_FAST") == "1"

    async def _step(name, coro):
        try:
            r = await coro
            print(f"  {name}: {r if isinstance(r, dict) else 'ok'}")
        except Exception as e:  # noqa: BLE001
            print(f"  {name}: ERROR {str(e)[:90]}")

    _cap = lambda k, d: int(os.environ.get(k, d))
    await _step("hud_reac_address", enrich_hud_reac_address(merged))
    from foreclosure_scraper.enrichment_lrcpwa_parcel import enrich_lrcpwa_parcel
    await _step("lrcpwa_parcel", enrich_lrcpwa_parcel(merged))
    if not FAST:
        await _step("geocode#1", enrich_geocode(merged))
        await _step("parcel_from_geo", asyncio.wait_for(enrich_parcel_from_geo(merged, concurrency=16), timeout=_cap("MERGE_PFG_TIMEOUT", 1800)))
        await _step("parcel_lookup", asyncio.wait_for(enrich_with_parcel_lookup(merged), timeout=_cap("MERGE_PL_TIMEOUT", 1800)))
        await _step("gis_attrs", asyncio.wait_for(enrich_gis_attrs(merged, concurrency=16), timeout=_cap("MERGE_GIS_TIMEOUT", 2400)))
        await _step("situs_address", asyncio.wait_for(enrich_situs_address(merged, concurrency=16), timeout=_cap("MERGE_SITUS_TIMEOUT", 1800)))
        await _step("address_backfill", enrich_addresses_from_owner(merged))
        await _step("aggressive_address", enrich_with_aggressive_address(merged))
        await _step("parcel_reverse_geo", enrich_parcel_reverse_geo(merged))
        await _step("geocode#2", enrich_geocode(merged))
        await _step("owner_mailing", enrich_owner_mailing(merged))
        from foreclosure_scraper.enrichment_images import enrich_with_images
        await _step("images", asyncio.wait_for(enrich_with_images(merged, use_mapillary=False), timeout=_cap("MERGE_IMAGES_TIMEOUT", 2400)))
        await _step("fhfa_value", enrich_fhfa_value(merged))
        await _step("dew_liens", enrich_dew_liens(merged))
        await _step("resolve_name_to_property", enrich_resolve_name_to_property(merged))
        from foreclosure_scraper.enrichment_doc_ocr import enrich_doc_ocr
        await _step("doc_ocr", enrich_doc_ocr(merged))
    return merged


def main() -> int:
    cfg = RuntimeConfig.from_env()
    _FAST = os.environ.get("MERGE_FAST") == "1"
    # load_board() folds the lazy-detail sidecar (vision/comps/cama) back into each
    # lead's .raw so write_artifact re-emits it intact instead of wiping it.
    existing = load_board(DOCS)
    print(f"existing dashboard: {len(existing)}")

    merged = asyncio.run(_resolve(existing, cfg))

    print("enrich_sc_cama:", enrich_sc_cama(merged))
    if not _FAST:
        print("enrich_footprint_sqft:", enrich_footprint_sqft(merged))
    print("enrich_court_owner_verify:", enrich_court_owner_verify(merged))
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

    print("enrich_gis_derived:", enrich_gis_derived(merged))
    from foreclosure_scraper.enrichment_tenure import enrich_tenure
    print("enrich_tenure:", enrich_tenure(merged))
    print("enrich_equity:", enrich_equity(merged))
    print("enrich_title_risk:", enrich_title_risk(merged))
    print("distress score_board:", score_board(merged))
    from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit
    print("strategy_fit:", enrich_strategy_fit(merged))
    from foreclosure_scraper.enrichment_buyer_match import enrich_buyer_match
    print("buyer_match:", enrich_buyer_match(merged))
    mfs = enrich_multifamily_class(merged)
    print("enrich_multifamily_class:", {k: v for k, v in mfs.items()
                                        if k not in ("examples", "skipped_examples")})
    enrich_property_kind(merged)
    print("enrich_derived_signals:", enrich_derived_signals(merged))
    print("enrich_data_quality:", enrich_data_quality(merged))

    _pre = len(merged)
    merged = dedupe(merged)
    print(f"post-enrich dedupe: {_pre} -> {len(merged)} (collapsed {_pre - len(merged)})")

    summary = {
        "by_source": dict(collections.Counter(li.source for li in merged if li.source)),
        "notes": "ingest fresh_court_leads.json (manual public-records lane) + enrichment"
                 + (" [FAST land]" if _FAST else ""),
    }
    try:
        print("generate_outreach:", generate_outreach(merged))
    except Exception as e:  # noqa: BLE001
        print("generate_outreach: ERROR", str(e)[:80])
    lp, mp = write_artifact(merged, summary, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name} | total leads: {len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
