#!/usr/bin/env python
"""Re-process the persisted dashboard dataset (docs/listings.json) with the
CURRENT code — WITHOUT re-scraping. Applies today's SC enrichers (CAMA value+
specs, footprint sqft estimate), recomputes valuation + grade + data-quality,
drops county-less national records, and rewrites the dashboard artifact.

Use when code/enrichers changed but you don't need a fresh crawl. For brand-new
leads, run the full pipeline (main.py) instead.

Usage: python scripts/regenerate_dashboard.py
"""
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade  # noqa: E402
from foreclosure_scraper.enrichment_sc_cama import enrich_sc_cama  # noqa: E402
from foreclosure_scraper.enrichment_footprint_sqft import enrich_footprint_sqft  # noqa: E402
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality  # noqa: E402
from foreclosure_scraper.enrichment_assessor_card import enrich_assessor_card  # noqa: E402
from foreclosure_scraper.enrichment_multifamily_class import enrich_multifamily_class  # noqa: E402
from foreclosure_scraper.enrichment_property_kind import enrich_property_kind  # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact  # noqa: E402
from foreclosure_scraper.outreach import generate_outreach  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _countyless_national(li: Listing) -> bool:
    return (li.source or "").startswith("national.") and not (li.county or "").strip()


def main() -> int:
    raw = json.loads((DOCS / "listings.json").read_text())
    print(f"loaded {len(raw)} records")

    listings, bad = [], 0
    for d in raw:
        try:
            listings.append(Listing.model_validate(d))
        except Exception as e:  # noqa: BLE001
            bad += 1
            if bad <= 3:
                print(f"  skip (validate): {str(e)[:80]}")
    print(f"re-hydrated {len(listings)} ({bad} unparseable)")

    before = len(listings)
    listings = [li for li in listings if not _countyless_national(li)]
    print(f"dropped county-less national: {before - len(listings)} -> {len(listings)} kept")

    # Re-apply scope to EVERY lead (carryover from older runs predates scope
    # tightening, so stale out-of-footprint counties + countyless noise persist).
    from foreclosure_scraper.main import _in_scope  # noqa: E402
    before = len(listings)
    listings = [li for li in listings if _in_scope(li)]
    print(f"scope re-filter: dropped {before - len(listings)} out-of-footprint -> {len(listings)} kept")

    # Drop dead court records — a Canceled/Satisfied/Dismissed/Vacated lien or
    # judgment is no longer an actionable lead (NC eCourts civilJudgmentStatus).
    def _terminal_court(li: Listing) -> bool:
        st = (((li.raw or {}).get("nc_ecourts") or {}).get("civilJudgmentStatus") or "").lower()
        return any(t in st for t in ("cancel", "satisf", "dismiss", "vacat", "withdraw", "expired", "released"))
    before = len(listings)
    listings = [li for li in listings if not _terminal_court(li)]
    print(f"dropped terminal-status court records: {before - len(listings)} -> {len(listings)} kept")

    # GIS chain (async; each bounded so a slow endpoint can't hang the run):
    #   parcel_from_geo : lat/lng -> parcel_id (point-in-polygon) for geo-bearing
    #                     parcel-less leads, so the rest can resolve attrs.
    #   parcel_lookup   : parcel# -> address/sqft/acreage for address-less leads.
    #   gis_attrs       : parcel/point -> assessed+market value, owner_name, sqft,
    #                     year_built, acreage, land_use (value 6%->~30%, owner 0%->~80%).
    import asyncio
    from foreclosure_scraper.enrichment_parcel_from_geo import enrich_parcel_from_geo
    from foreclosure_scraper.enrichment_parcel_lookup import enrich_with_parcel_lookup
    from foreclosure_scraper.enrichment_gis_attrs import enrich_gis_attrs

    def _run_bounded(name, coro, timeout):
        try:
            asyncio.run(asyncio.wait_for(coro, timeout=timeout))
            print(f"{name}: done")
        except (asyncio.TimeoutError, TimeoutError):
            print(f"{name}: time-capped at {timeout}s (partial)")
        except Exception as e:  # noqa: BLE001
            print(f"{name}: ERROR", str(e)[:80])

    # regenerate is the manual THOROUGH re-enrich path, so caps are generous +
    # concurrency raised to let the GIS backfill complete (value/owner/sqft full
    # lift) rather than time-cap partway. Env-overridable for a quick pass.
    _t = lambda k, d: int(os.environ.get(k, d))
    # Generous pathological-hang backstops only — per-request timeouts (15-25s)
    # already bound each query, so these let the full batch enrich to completion
    # rather than time-capping legitimate work. Env-overridable.
    _run_bounded("parcel_from_geo", enrich_parcel_from_geo(listings, concurrency=16), _t("REGEN_PFG_TIMEOUT", 10800))
    _run_bounded("parcel_lookup", enrich_with_parcel_lookup(listings), _t("REGEN_PL_TIMEOUT", 7200))
    _run_bounded("gis_attrs", enrich_gis_attrs(listings, concurrency=16), _t("REGEN_GIS_TIMEOUT", 14400))
    from foreclosure_scraper.enrichment_situs_address import enrich_situs_address
    _run_bounded("situs_address", enrich_situs_address(listings, concurrency=16), _t("REGEN_SITUS_TIMEOUT", 7200))
    # Images after situs/geocode so freshly-addressed leads get an aerial.
    from foreclosure_scraper.enrichment_images import enrich_with_images
    _run_bounded("images", enrich_with_images(listings, use_mapillary=False), _t("REGEN_IMAGES_TIMEOUT", 7200))

    print("enrich_sc_cama:", enrich_sc_cama(listings))
    print("enrich_footprint_sqft:", enrich_footprint_sqft(listings))

    # Recompute valuation + grade with current logic (mirrors main.py).
    vfail = 0
    for li in listings:
        try:
            c = vcalc.compute(li)
            g = vgrade.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = vcalc.to_dict(c)
            li.raw["grade"] = vgrade.to_dict(g)
        except Exception:  # noqa: BLE001
            vfail += 1
    print(f"recomputed calc+grade ({vfail} failures)")

    # On-demand per-parcel assessor card (grade-gated B+) — fills real sqft + sale
    # price the bulk feed omits; re-grade touched leads so a real card sqft flips
    # ARV MEDIUM->HIGH. No-op unless ASSESSOR_CARD_ON=1 (mirrors main.py).
    s = enrich_assessor_card(listings)
    print("enrich_assessor_card:", s)
    if s:
        touched = [li for li in listings if isinstance(li.raw, dict) and "assessor_card" in li.raw]
        for li in touched:
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
            except Exception:  # noqa: BLE001
                pass
        print(f"re-graded {len(touched)} card-enriched leads")

    # Multifamily classifier BEFORE property_kind backfill (mirrors main.py):
    # promote apartment/multi-unit distress, then guarantee non-UNKNOWN coverage.
    mfs = enrich_multifamily_class(listings)
    print("enrich_multifamily_class:", {k: v for k, v in mfs.items()
                                        if k not in ("examples", "skipped_examples")})
    enrich_property_kind(listings)

    # Equity (ARV − payoff − senior liens) + distress score + derived signals.
    # Run after calc/grade so ARV is set; derived_signals (LTV, ppsf vs comp, etc.)
    # consume equity + the fresh GIS value, so they run last.
    from foreclosure_scraper.enrichment_equity import enrich_equity
    from foreclosure_scraper.distress_score import score_board
    from foreclosure_scraper.enrichment_derived_signals import enrich_derived_signals
    from foreclosure_scraper.enrichment_gis_derived import enrich_gis_derived
    print("enrich_gis_derived:", enrich_gis_derived(listings))  # last-sale/deed-age/tax-runway before equity
    print("enrich_equity:", enrich_equity(listings))
    print("distress score_board:", score_board(listings))
    print("enrich_derived_signals:", enrich_derived_signals(listings))

    print("enrich_data_quality:", enrich_data_quality(listings))

    # Promote a recoverable tax/GIS owner into any empty owner_name (unblocks mailing,
    # voter-phone, ROD name-search downstream). Runs BEFORE voter_phone + gaston_rod.
    try:
        from foreclosure_scraper.enrichment_promote_owner import enrich_promote_owner
        print("enrich_promote_owner:", enrich_promote_owner(listings))
    except Exception as e:  # noqa: BLE001
        print("enrich_promote_owner: ERROR", str(e)[:80])

    # Free NC owner-phone from the NCSBE voter file (name+address / name+county-unique).
    # No-op if data/ncvoter/ isn't present (degrades gracefully). DNC-gated downstream.
    try:
        from foreclosure_scraper.enrichment_voter_phone import enrich_voter_phone
        print("enrich_voter_phone:", enrich_voter_phone(listings))
    except Exception as e:  # noqa: BLE001
        print("enrich_voter_phone: ERROR", str(e)[:80])

    # Classify each owner_phone line-type (free LERG lookup) -> tcpa_class; landlines become the
    # compliant call lane. Async + bounded; runs after voter_phone so it sees the set numbers.
    try:
        from foreclosure_scraper.enrichment_line_type import enrich_line_type
        print("enrich_line_type:", _run_bounded("line_type", enrich_line_type(listings), _t("REGEN_LINETYPE_TIMEOUT", 600)))
    except Exception as e:  # noqa: BLE001
        print("enrich_line_type: ERROR", str(e)[:80])

    # Gaston NC Register of Deeds lien-existence by owner name (gated FORECLOSURE_GASTON_ROD=1;
    # free name-index search, 3-step session-seed). Attaches raw['rod'] (D/T mortgage + adverse liens).
    if os.environ.get("FORECLOSURE_GASTON_ROD") == "1":
        try:
            from foreclosure_scraper.enrichment_gaston_rod import enrich_gaston_rod
            print("enrich_gaston_rod:", asyncio.run(enrich_gaston_rod(listings)))
        except Exception as e:  # noqa: BLE001
            print("enrich_gaston_rod: ERROR", str(e)[:80])

    # Burke + Cleveland NC ROD lien-existence (CCHS) — default-on.
    try:
        from foreclosure_scraper.enrichment_cchs_rod import enrich_cchs_rod
        print("enrich_cchs_rod:", asyncio.run(enrich_cchs_rod(listings)))
    except Exception as e:  # noqa: BLE001
        print("enrich_cchs_rod: ERROR", str(e)[:80])

    # Buncombe NC ROD lien-existence (Cott/Aumentum v4) — default-on.
    try:
        from foreclosure_scraper.enrichment_aumentum_rod import enrich_aumentum_rod
        print("enrich_aumentum_rod:", asyncio.run(enrich_aumentum_rod(listings)))
    except Exception as e:  # noqa: BLE001
        print("enrich_aumentum_rod: ERROR", str(e)[:80])

    # Spartanburg SC ROD (render-based, HOT/WARM-first capped) — biggest SC county.
    try:
        from foreclosure_scraper.enrichment_spartanburg_rod import enrich_spartanburg_rod
        print("enrich_spartanburg_rod:", asyncio.run(enrich_spartanburg_rod(listings)))
    except Exception as e:  # noqa: BLE001
        print("enrich_spartanburg_rod: ERROR", str(e)[:80])

    # NC absolute-divorce (CVD) distress by owner party-name (render path; 50B DV
    # excluded). GATED OFF by default (FORECLOSURE_NC_DIVORCE=1) — NC eCourts
    # Smart Search is AWS-WAF/CAPTCHA-walled to automated renders today.
    if os.environ.get("FORECLOSURE_NC_DIVORCE") == "1":
        try:
            from foreclosure_scraper.enrichment_nc_divorce import enrich_nc_divorce
            print("enrich_nc_divorce:", asyncio.run(enrich_nc_divorce(listings)))
        except Exception as e:  # noqa: BLE001
            print("enrich_nc_divorce: ERROR", str(e)[:80])

    # SC divorce / marital-dissolution distress by owner party-name (SC Family
    # Court FCCMS PublicAccess portal — free public API). Default-ON in the live
    # pipeline; here it's gated behind FORECLOSURE_SC_DIVORCE=1 so a manual
    # regenerate only runs it when explicitly asked, bounded by _run_bounded.
    if os.environ.get("FORECLOSURE_SC_DIVORCE") == "1":
        try:
            from foreclosure_scraper.enrichment_sc_divorce import enrich_sc_divorce
            _run_bounded("sc_divorce", enrich_sc_divorce(listings),
                         _t("REGEN_SC_DIVORCE_TIMEOUT", 14400))
        except Exception as e:  # noqa: BLE001
            print("enrich_sc_divorce: ERROR", str(e)[:80])

    # Elderly/probate life-event tagging on owner_name (after promotion).
    try:
        from foreclosure_scraper.enrichment_life_events import enrich_life_events
        print("enrich_life_events:", enrich_life_events(listings))
    except Exception as e:  # noqa: BLE001
        print("enrich_life_events: ERROR", str(e)[:80])

    # Drop sold/removed snapshot-REO (Fannie) — stale carryover whose per-property
    # SPA URL renders a browser 404 once the uuid leaves inventory. Fail-safe.
    from foreclosure_scraper.enrichment_reo_freshness import prune_stale_reo
    try:
        listings, _pstats = asyncio.run(prune_stale_reo(listings))
        print("prune_stale_reo:", _pstats)
    except Exception as e:  # noqa: BLE001
        print("prune_stale_reo: ERROR", str(e)[:80])

    # Data-quality corrections (LAST, after tiers set): bbox/centroid geo guards,
    # auction_status normalization, presumed-withdrawn stale-case flag + HOT down-rank.
    try:
        from foreclosure_scraper.enrichment_board_quality import enrich_board_quality
        print("enrich_board_quality:", enrich_board_quality(listings))
    except Exception as e:  # noqa: BLE001
        print("enrich_board_quality: ERROR", str(e)[:80])

    # Post-enrich dedupe — mirrors merge_today_sources + main.py's H1 fix. GIS/parcel
    # backfill fills parcel_id AFTER the original scrape-time dedupe, so same-property
    # twins (a reverse-geo-resolved row + its synthetic-address sibling) only become
    # identical-key now; collapse them so duplicates never ship from a regenerate.
    from foreclosure_scraper.dedupe import dedupe  # noqa: E402
    _pre = len(listings)
    listings = dedupe(listings)
    print(f"post-enrich dedupe: {_pre} -> {len(listings)} (collapsed {_pre - len(listings)})")

    by_state = collections.Counter(li.state for li in listings if li.state)
    by_county = collections.Counter(f"{li.state}/{li.county}" for li in listings if li.county)
    by_source = collections.Counter(li.source for li in listings if li.source)
    summary = {
        "by_state": dict(by_state),
        "by_county_top": by_county.most_common(15),
        "by_source": dict(by_source),
        "notes": "regenerated in-place from persisted dataset (no re-scrape)",
    }
    # Refresh the outreach mail-merge list + CRM so the actionable direct-mail
    # batch stays current on every republish (was only refreshed by the full run).
    try:
        print("generate_outreach:", generate_outreach(listings))
    except Exception as e:  # noqa: BLE001
        print("generate_outreach: ERROR", str(e)[:80])
    lp, mp = write_artifact(listings, summary, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
