#!/usr/bin/env python3
"""Comprehensive enrichment pass on the existing 40k board.

Runs every free enricher that doesn't need a paid API key.
Focuses on filling gaps in per-listing investment data:
- Equity (ARV - payoff - liens)
- Amount owed (cross-source debt waterfall)
- Title risk
- Strategy fit
- ROD mortgage history (free county endpoints)
- Court records (free NC eCourts)
- Bankruptcy (free CourtListener)
- Recorded comps / sales (free county GIS)
- Foreclosure sold comps
- Valuation / ARV recompute (offline)
- And 30+ more offline enrichers

Writes the enriched board back to docs/listings.json.
"""
import asyncio
import os
import sys
import time
import traceback
from pathlib import Path
from collections import Counter

# --- Load API keys from .secrets/ directory ----------------------------------
# Each file in .secrets/ contains a single API key. The filename (minus
# extension) maps to the env var. E.g. anthropic_api_key.txt -> ANTHROPIC_API_KEY
_SECRETS_DIR = Path(__file__).resolve().parent.parent / ".secrets"
if _SECRETS_DIR.is_dir():
    for _kf in sorted(_SECRETS_DIR.glob("*.txt")):
        _env_name = _kf.stem.upper()  # anthropic_api_key -> ANTHROPIC_API_KEY
        if _env_name not in os.environ:
            _val = _kf.read_text().strip()
            if _val:
                os.environ[_env_name] = _val
    # Also handle keys that need a different env var name than the filename
    _ENV_REMAP = {
        "GITHUB_MODELS_TOKEN": "GITHUB_MODELS_TOKEN",  # already correct
        "GROQ_API_KEY": "GROQ_API_KEY",
        "NVIDIA_API_KEY": "NVIDIA_API_KEY",
        "MISTRAL_API_KEY": "MISTRAL_API_KEY",
        "ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY",
    }
    # Gemini keys: gemini_api_key_1.txt -> GEMINI_API_KEY_1, etc.
    # These are loaded by _parse_gemini_keys in enrichment_vision.py which
    # reads GEMINI_API_KEY_1..9 from env. The .secrets/ files already have
    # the right names so the loop above picks them up.

# Setup paths
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact
from foreclosure_scraper.models import Listing


def _coverage(board: list[Listing]) -> dict:
    """Snapshot enrichment coverage."""
    total = len(board)
    fields = {}
    for li in board:
        raw = li.raw if hasattr(li, 'raw') and isinstance(li.raw, dict) else {}
        for k, v in raw.items():
            if v is not None and v != "" and v != [] and v != {}:
                fields[k] = fields.get(k, 0) + 1
    return {k: (v, round(100*v/total, 1)) for k, v in sorted(fields.items(), key=lambda x: -x[1])}


async def main():
    docs_dir = Path(__file__).parent.parent / "docs"
    t0 = time.time()

    # 1. Load existing board
    print("=" * 70)
    print("COMPREHENSIVE ENRICHMENT PASS")
    print("=" * 70)
    print("\n[1] Loading existing board...")
    board = load_board(docs_dir)
    print(f"    Board: {len(board)} listings")

    before = _coverage(board)
    print(f"\n    BEFORE: {len(before)} enrichment fields present")
    for k, (n, pct) in list(before.items())[:25]:
        print(f"      {k:40s} {n:6d}  {pct:5.1f}%")

    stats = {}

    # 2. OFFLINE enrichers (no network needed, seconds)
    print("\n[2] OFFLINE enrichers (no network needed)...")

    async def _run_offline(name, func, *args, timeout_s=600, **kwargs):
        print(f"  [{name}]...", end=" ", flush=True)
        try:
            import inspect
            if inspect.iscoroutinefunction(func):
                s = await asyncio.wait_for(func(board, *args, **kwargs), timeout=timeout_s)
            else:
                async def _wrap():
                    return func(board, *args, **kwargs)
                s = await asyncio.wait_for(_wrap(), timeout=timeout_s)
            stats[name] = s
            # Truncate to avoid multi-GB log files when enrichers return
            # large objects (e.g. prune_stale_reo returns a list of 40k Listings)
            s_str = str(s)
            if len(s_str) > 500:
                s_str = s_str[:500] + f"... (truncated, {len(s_str)} chars)"
            print(f"OK: {s_str}")
        except asyncio.TimeoutError:
            stats[name] = f"TIMEOUT ({timeout_s}s)"
            print(f"TIMEOUT ({timeout_s}s)")
        except Exception as e:
            stats[name] = f"ERR: {e}"
            print(f"ERR: {e}")

    async def _run_async(name, func, timeout_s=300, *args, **kwargs):
        print(f"  [{name}]... ", end="", flush=True)
        try:
            import inspect
            if inspect.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(board, *args, **kwargs), timeout=timeout_s)
            else:
                # Sync function — run directly (it returns a dict, not a coroutine).
                # Wrap in a coroutine so wait_for can enforce the timeout.
                async def _wrap():
                    return func(board, *args, **kwargs)
                result = await asyncio.wait_for(_wrap(), timeout=timeout_s)
            stats[name] = "OK"
            print("OK")
            return result
        except asyncio.TimeoutError:
            stats[name] = f"TIMEOUT ({timeout_s}s)"
            print(f"TIMEOUT ({timeout_s}s)")
            return None
        except Exception as e:
            stats[name] = f"ERR: {e}"
            print(f"ERR: {e}")
            return None

    # 2a. Address synthesis
    from foreclosure_scraper.enrichment_address_final import enrich_with_address_synthesis
    await _run_offline("address_final", enrich_with_address_synthesis)

    # 2b. County pin enforcement
    from foreclosure_scraper.enrichment_county_pin import enforce_case_pinned_county
    await _run_offline("county_pin", enforce_case_pinned_county)

    # 2c. GIS derived (sqft from GIS data) — SKIP on large boards, causes OOM on 8GB RAM
    print("  [gis_attrs] SKIP — causes OOM on 8GB RAM with 53k+ listings")
    # from foreclosure_scraper.enrichment_gis_attrs import enrich_gis_attrs
    # await _run_async("gis_attrs", enrich_gis_attrs, 1800)

    from foreclosure_scraper.enrichment_gis_derived import enrich_gis_derived
    await _run_offline("gis_derived", enrich_gis_derived)

    # 2d. Situs address normalization (async)
    from foreclosure_scraper.enrichment_situs_address import enrich_situs_address
    await _run_async("situs_address", enrich_situs_address, 120)

    # 2e. Footprint sqft
    try:
        from foreclosure_scraper.enrichment_footprint_sqft import enrich_footprint_sqft
        await _run_offline("footprint_sqft", enrich_footprint_sqft)
    except ImportError:
        print("  [footprint_sqft] SKIP - module not found")

    # 2f. Tax owed normalization
    from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed
    await _run_offline("tax_owed", enrich_tax_owed)

    # 2f2. Deed chain history (offline — synthesizes from existing data)
    from foreclosure_scraper.enrichment_deed_chain import enrich_deed_chain
    await _run_offline("deed_chain", enrich_deed_chain)

    # INTERMEDIATE SAVE — preserve enrichment progress to survive OOM kills
    import gc
    print("  [checkpoint] Saving intermediate board...")
    try:
        write_artifact(board, {"checkpoint": True}, docs_dir)
        gc.collect()
        print("  [checkpoint] OK")
    except Exception as e:
        print(f"  [checkpoint] ERR: {e}")

    # 2g. Tax relief / exemptions — SKIP, causes OOM on 8GB with 53k listings
    print("  [tax_relief] SKIP — low yield (1 tag per 600 leads), saves memory")

    # 2h. Tenure calculation
    from foreclosure_scraper.enrichment_tenure import enrich_tenure
    await _run_offline("tenure", enrich_tenure)

    # 2i. FHFA value estimate (async)
    gc.collect()  # Free memory before network enrichers
    try:
        from foreclosure_scraper.enrichment_fhfa_value import enrich_fhfa_value
        await _run_async("fhfa_value", enrich_fhfa_value, 120)
    except ImportError:
        print("  [fhfa_value] SKIP - module not found")

    # 2j. Flood zone
    from foreclosure_scraper.enrichment_flood_zone import enrich_flood_zones
    await _run_offline("flood_zone", enrich_flood_zones, timeout_s=600)

    # CHECKPOINT flood — save after flood_zone (OOM death point)
    print("  [checkpoint_flood] Saving after flood_zone...")
    try:
        write_artifact(board, {"checkpoint": True}, docs_dir)
        gc.collect()
        print("  [checkpoint_flood] OK")
    except Exception as e:
        print(f"  [checkpoint_flood] ERR: {e}")

    # 2k. Vacant land use
    from foreclosure_scraper.enrichment_vacant_landuse import enrich_vacant_landuse
    await _run_offline("vacant_landuse", enrich_vacant_landuse)

    # 2l. Bankruptcy stay analysis
    from foreclosure_scraper.enrichment_bankruptcy_stay import enrich_bankruptcy_stay
    await _run_offline("bankruptcy_stay", enrich_bankruptcy_stay)

    # 2m. Court owner verify
    from foreclosure_scraper.enrichment_court_owner_verify import enrich_court_owner_verify
    await _run_offline("court_owner_verify", enrich_court_owner_verify)

    # 2n. Foreclosure sold comps
    from foreclosure_scraper.enrichment_foreclosure_sold_comps import enrich_foreclosure_sold_comps
    await _run_offline("foreclosure_sold_comps", enrich_foreclosure_sold_comps, [])

    # 2o. Amount owed (debt waterfall)
    from foreclosure_scraper.enrichment_amount_owed import enrich_amount_owed
    await _run_offline("amount_owed", enrich_amount_owed)

    # CHECKPOINT amount — save after amount_owed
    print("  [checkpoint_amt] Saving after amount_owed...")
    try:
        write_artifact(board, {"checkpoint": True}, docs_dir)
        gc.collect()
        print("  [checkpoint_amt] OK")
    except Exception as e:
        print(f"  [checkpoint_amt] ERR: {e}")

    # 2p. Property kind classification
    from foreclosure_scraper.enrichment_property_kind import enrich_property_kind
    await _run_offline("property_kind", enrich_property_kind)

    # 2q. Line type classification
    from foreclosure_scraper.enrichment_line_type import enrich_line_type
    await _run_offline("line_type", enrich_line_type)

    # 2r. Derivation flags
    from foreclosure_scraper.enrichment_derivation_flags import enrich_derivation_flags
    await _run_offline("derivation_flags", enrich_derivation_flags)

    # 2s. Derived signals
    from foreclosure_scraper.enrichment_derived_signals import enrich_derived_signals
    await _run_offline("derived_signals", enrich_derived_signals)

    # 2t. Relationship signal (probate/divorce/partition)
    from foreclosure_scraper.enrichment_relationship_deeds import enrich_with_relationship_deeds
    print("  [relationship_deeds]...", end=" ", flush=True)
    try:
        derived = enrich_with_relationship_deeds(board, sold_pool=None)
        stats["relationship_deeds"] = {"derived": len(derived) if derived else 0}
        print(f"OK: {len(derived) if derived else 0} derived")
    except Exception as e:
        stats["relationship_deeds"] = f"ERR: {e}"
        print(f"ERR: {e}")

    # 2u. CAMA condition/grade/year (open ArcGIS) — backfills year_built + condition
    from foreclosure_scraper.enrichment_cama_condition import enrich_cama_condition
    await _run_async("cama_condition", enrich_cama_condition, 300)

    # 2u. SC CAMA (Spartanburg/Pickens/Anderson per-parcel condition)
    from foreclosure_scraper.enrichment_sc_cama import enrich_sc_cama
    await _run_offline("sc_cama", enrich_sc_cama)

    # 2u1. Process timing / redemption clock (offline, pure compute)
    from foreclosure_scraper.enrichment_process_timing import enrich_process_timing
    await _run_offline("process_timing", enrich_process_timing)

    # 2u2. Life events / probate / elderly (offline, pure compute)
    from foreclosure_scraper.enrichment_life_events import enrich_life_events
    await _run_offline("life_events", enrich_life_events)

    # CHECKPOINT life — save after life_events
    print("  [checkpoint_life] Saving after life_events...")
    try:
        write_artifact(board, {"checkpoint": True}, docs_dir)
        gc.collect()
        print("  [checkpoint_life] OK")
    except Exception as e:
        print(f"  [checkpoint_life] ERR: {e}")

    # 2u3. Promote recoverable owner name (offline, pure compute)
    from foreclosure_scraper.enrichment_promote_owner import enrich_promote_owner
    await _run_offline("promote_owner", enrich_promote_owner)

    # 2u4. Census ACS rent estimate (free, no API key needed)
    from foreclosure_scraper.enrichment_census_rent import enrich_census_rent
    await _run_offline("census_rent", enrich_census_rent)

    # 2t2. Burke County parcel history (ownership changes, structure loss)
    from foreclosure_scraper.enrichment_burke_history import enrich_burke_parcel_history
    await _run_offline("burke_history", enrich_burke_parcel_history, timeout_s=300)

    # 2u. Valuation / ARV recompute (offline, uses comps + sqft + condition)
    print("  [valuation]...", end=" ", flush=True)
    try:
        from foreclosure_scraper.valuation import calc as vcalc
        from foreclosure_scraper.valuation import grading as vgrade
        errs = 0
        for li in board:
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
            except Exception:
                errs += 1
        stats["valuation"] = f"OK ({errs} lead errors)"
        print(f"OK ({errs} lead errors)")
    except Exception as e:
        stats["valuation"] = f"ERR: {e}"
        print(f"ERR: {e}")

    # 2v. Equity computation (ARV - payoff - liens)
    from foreclosure_scraper.enrichment_equity import enrich_equity
    await _run_offline("equity", enrich_equity)

    # CHECKPOINT equity — save after equity (heaviest compute section done)
    print("  [checkpoint_equity] Saving after equity...")
    try:
        write_artifact(board, {"checkpoint": True}, docs_dir)
        gc.collect()
        print("  [checkpoint_equity] OK")
    except Exception as e:
        print(f"  [checkpoint_equity] ERR: {e}")

    # 2w. Title risk
    from foreclosure_scraper.enrichment_title_risk import enrich_title_risk
    await _run_offline("title_risk", enrich_title_risk)

    # 2x. Distress stack / score board
    from foreclosure_scraper.distress_score import score_board
    await _run_offline("distress_score", score_board)

    # 2y. Strategy fit
    from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit
    await _run_offline("strategy_fit", enrich_strategy_fit)

    # CHECKPOINT 2 — save after offline enrichment group (survive OOM before network)
    print("  [checkpoint2] Saving after offline enrichers...")
    try:
        write_artifact(board, {"checkpoint": True}, docs_dir)
        gc.collect()
        print("  [checkpoint2] OK")
    except Exception as e:
        print(f"  [checkpoint2] ERR: {e}")

    # 2z. Eviction market
    try:
        from foreclosure_scraper.enrichment_eviction_market import enrich_eviction_market
        await _run_offline("eviction_market", enrich_eviction_market)
    except ImportError:
        print("  [eviction_market] SKIP - module not found")

    # 2aa. Corroboration
    from foreclosure_scraper.enrichment_corroboration import enrich_corroboration
    await _run_offline("corroboration", enrich_corroboration)

    # 2ab. Competition
    from foreclosure_scraper.enrichment_competition import enrich_competition
    await _run_offline("competition", enrich_competition)

    # 2ac. Lead signals
    from foreclosure_scraper.enrichment_lead_signals import enrich_lead_signals
    await _run_offline("lead_signals", enrich_lead_signals)

    # 2ad. Buyer match
    from foreclosure_scraper.enrichment_buyer_match import enrich_buyer_match
    await _run_offline("buyer_match", enrich_buyer_match)

    # 2ae. Opportunity zones
    from foreclosure_scraper.enrichment_opportunity_zone import enrich_opportunity_zones
    await _run_offline("opportunity_zone", enrich_opportunity_zones)

    # 2af. USPS vacancy
    try:
        from foreclosure_scraper.enrichment_usps_vacancy import enrich_usps_vacancy
        await _run_offline("usps_vacancy", enrich_usps_vacancy)
    except ImportError:
        print("  [usps_vacancy] SKIP - module not found")

    # 2ag. Data quality
    from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
    await _run_offline("data_quality", enrich_data_quality)

    # 2ah. Board quality
    from foreclosure_scraper.enrichment_board_quality import enrich_board_quality
    await _run_offline("board_quality", enrich_board_quality)

    # 2ai. Last sale
    from foreclosure_scraper.enrichment_last_sale import enrich_last_sale
    await _run_offline("last_sale", enrich_last_sale)

    # 2aj. Board QA
    from foreclosure_scraper.enrichment_board_qa import enrich_board_qa
    await _run_offline("board_qa", enrich_board_qa)

    # 2ak. Source link
    from foreclosure_scraper.enrichment_source_link import enrich_source_link
    await _run_offline("source_link", enrich_source_link)

    # 2al. Source consistency
    from foreclosure_scraper.enrichment_source_consistency import enrich_source_consistency
    await _run_offline("source_consistency", enrich_source_consistency)

    # 2am. Pulled sales (returns tuple)
    print("  [pulled_sales]...", end=" ", flush=True)
    try:
        from foreclosure_scraper.enrichment_pulled_sales import enrich_with_pulled_sales
        board2, s = enrich_with_pulled_sales(board)
        stats["pulled_sales"] = s
        print(f"OK: {s}")
    except Exception as e:
        stats["pulled_sales"] = f"ERR: {e}"
        print(f"ERR: {e}")

    # 2an. REO freshness — SKIPPED on the enrich-only / VM path. It prunes leads
    # by re-checking REO liveness, which false-drops from a datacenter IP (the
    # residential REO sources 403 the VM). Enrich-only must NEVER drop a lead;
    # the Mac's residential runs do the real REO aging. (Env ENRICH_ONLY_KEEP_ALL
    # left as the default here.)
    print("  [reo_freshness] SKIP - enrich-only must not drop leads")

    # 2ao. Multifamily classification
    try:
        from foreclosure_scraper.enrichment_multifamily_class import enrich_multifamily_class
        await _run_offline("multifamily_class", enrich_multifamily_class)
    except ImportError:
        print("  [multifamily_class] SKIP - module not found")

    # 3. NETWORK enrichers (free government endpoints, no API key)
    print("\n[3] NETWORK enrichers (free government endpoints)...")

    # CHECKPOINT 3 — save before network enrichers (most OOM-prone section)
    print("  [checkpoint3] Saving before network enrichers...")
    try:
        write_artifact(board, {"checkpoint": True}, docs_dir)
        gc.collect()
        print("  [checkpoint3] OK")
    except Exception as e:
        print(f"  [checkpoint3] ERR: {e}")

    # 3a. ROD mortgage lookups
    print("  [rod_lookup]...", end=" ", flush=True)
    try:
        from foreclosure_scraper.enrichment_rod_lookup import enrich_rod_lookup
        s = enrich_rod_lookup(board)
        stats["rod_lookup"] = s
        print(f"OK: {s}")
    except Exception as e:
        stats["rod_lookup"] = f"ERR: {e}"
        print(f"ERR: {e}")

    # 3b. NC eCourts judgment search (free, keyless)
    from foreclosure_scraper.enrichment_courts import enrich_with_court_records
    await _run_async("courts", enrich_with_court_records, 600)

    # 3c. Bankruptcy (CourtListener, free)
    from foreclosure_scraper.enrichment_bankruptcy import enrich_with_bankruptcy
    await _run_async("bankruptcy", enrich_with_bankruptcy, 300)

    # CHECKPOINT 4 — save after courts+bankruptcy (heavy network enrichers done)
    print("  [checkpoint4] Saving after courts/bankruptcy...")
    try:
        write_artifact(board, {"checkpoint": True}, docs_dir)
        gc.collect()
        print("  [checkpoint4] OK")
    except Exception as e:
        print(f"  [checkpoint4] ERR: {e}")

    # 3d. DOW liens (SC)
    try:
        from foreclosure_scraper.enrichment_dew_liens import enrich_dew_liens
        await _run_async("dew_liens", enrich_dew_liens, 300)
    except ImportError:
        print("  [dew_liens] SKIP - module not found")

    # 3e. SOS dissolution (NC SOS, free)
    from foreclosure_scraper.enrichment_sos_dissolution import enrich_with_sos_dissolution
    print("  [sos_dissolution]...", end=" ", flush=True)
    try:
        await asyncio.wait_for(enrich_with_sos_dissolution(board, max_check=200), timeout=300)
        stats["sos_dissolution"] = "OK"
        print("OK")
    except asyncio.TimeoutError:
        stats["sos_dissolution"] = "TIMEOUT (300s)"
        print("TIMEOUT (300s)")
    except Exception as e:
        stats["soss_dissolution"] = f"ERR: {e}"
        print(f"ERR: {e}")

    # 3f. SOS registered agent (NC SOS, free)
    from foreclosure_scraper.enrichment_sos_agent import enrich_with_sos_agent
    print("  [sos_agent]...", end=" ", flush=True)
    try:
        s = await asyncio.wait_for(enrich_with_sos_agent(board, max_check=200), timeout=300)
        stats["sos_agent"] = s
        print(f"OK: {s}")
    except asyncio.TimeoutError:
        stats["soss_agent"] = "TIMEOUT (300s)"
        print("TIMEOUT (300s)")
    except Exception as e:
        stats["sos_agent"] = f"ERR: {e}"
        print(f"ERR: {e}")

    # 3g. Incarceration (NC DAC, free)
    from foreclosure_scraper.enrichment_incarceration import enrich_incarceration
    await _run_async("incarceration", enrich_incarceration, 300)

    # 3h. FEMA disaster (free)
    try:
        from foreclosure_scraper.enrichment_fema_disaster import enrich_with_fema_disaster
        await _run_async("fema_disaster", enrich_with_fema_disaster, 300)
    except ImportError:
        print("  [fema_disaster] SKIP - module not found")

    # 3i. FEMA repetitive loss (free)
    try:
        from foreclosure_scraper.enrichment_fema_repetitive_loss import enrich_with_fema_repetitive_loss
        await _run_async("fema_repetitive_loss", enrich_with_fema_repetitive_loss, 300)
    except ImportError:
        print("  [fema_repetitive_loss] SKIP - module not found")

    # 3j. Environmental (EPA ECHO, free)
    try:
        from foreclosure_scraper.enrichment_environmental import enrich_with_environmental
        await _run_async("environmental", enrich_with_environmental, 900)
    except ImportError:
        print("  [environmental] SKIP - module not found")

    # 3k. Building permits (free city APIs)
    try:
        from foreclosure_scraper.enrichment_building_permits import enrich_with_building_permits
        await _run_async("building_permits", enrich_with_building_permits, 300)
    except ImportError:
        print("  [building_permits] SKIP - module not found")

    # 3l. Code enforcement (free city APIs)
    try:
        from foreclosure_scraper.enrichment_code_enforcement import enrich_with_code_enforcement
        await _run_async("code_enforcement", enrich_with_code_enforcement, 300)
    except ImportError:
        print("  [code_enforcement] SKIP - module not found")

    # 3m. Helene damage (free)
    try:
        from foreclosure_scraper.enrichment_helene_damage import enrich_with_helene_damage
        await _run_async("helene_damage", enrich_with_helene_damage, 300)
    except ImportError:
        print("  [helene_damage] SKIP - module not found")

    # 3n. Voter phone (NC voter file, free)
    try:
        from foreclosure_scraper.enrichment_voter_phone import enrich_voter_phone
        await _run_async("voter_phone", enrich_voter_phone, 600)
    except ImportError:
        print("  [voter_phone] SKIP - module not found")

    # 3o. Lien stack
    try:
        from foreclosure_scraper.enrichment_lien_stack import enrich_lien_stack
        await _run_async("lien_stack", enrich_lien_stack, 300)
    except ImportError:
        print("  [lien_stack] SKIP - module not found")

    # 3o-bis. IRS / federal tax lien search via CourtListener RECAP
    try:
        from foreclosure_scraper.enrichment_irs_lien import enrich_irs_liens
        await _run_async("irs_lien", enrich_irs_liens, 600)
    except ImportError:
        print("  [irs_lien] SKIP - module not found")

    # 3o-bis2. Probate court case search for estate/inherited properties
    try:
        from foreclosure_scraper.enrichment_probate_search import enrich_probate_search
        await _run_async("probate_search", enrich_probate_search, 600)
    except ImportError:
        print("  [probate_search] SKIP - module not found")

    # 3o-bis3. RECAP document pull — fetch motion PDFs from CourtListener archive
    # for adversary proceedings (contains property address, lender balance, lien priority).
    try:
        from foreclosure_scraper.enrichment_recap_document import enrich_recap_documents
        await _run_async("recap_documents", enrich_recap_documents, 300)
    except ImportError:
        print("  [recap_documents] SKIP - module not found")

    # 3p. DOT OCR (deed of trust loan amounts) — 9 Gemini keys + Groq fallback
    # Boost: 400→2000 leads, 1800s→3600s budget to cover more of 14k eligible
    os.environ.setdefault("FORECLOSURE_DOT_OCR_MAX", "2000")
    os.environ.setdefault("FORECLOSURE_DOT_OCR_BUDGET_S", "3600")
    os.environ.setdefault("FORECLOSURE_DOT_OCR_COUNTY_MAX", "800")
    try:
        print("  [dot_ocr] SKIP - causes OOM kill, disabled to prevent enrichment crash")
        # from foreclosure_scraper.enrichment_dot_ocr import enrich_dot_ocr
        # await _run_async("dot_ocr", enrich_dot_ocr, 3600)
    except ModuleNotFoundError:
        print("  [dot_ocr] SKIP - module not found")

    # 3q. Recorded sales (county GIS)
    try:
        from foreclosure_scraper.enrichment_recorded_sales import enrich as enrich_recorded_sales
        await _run_async("recorded_sales", enrich_recorded_sales, 1200)
    except ImportError:
        print("  [recorded_sales] SKIP - module not found")

    # 3r. Recorded comps (county GIS)
    try:
        from foreclosure_scraper.enrichment_recorded_comps import enrich as enrich_recorded_comps
        await _run_async("recorded_comps", enrich_recorded_comps, 1200)
    except ImportError:
        print("  [recorded_comps] SKIP - module not found")

    # 3s. Assessor comps
    try:
        from foreclosure_scraper.enrichment_assessor_comps import enrich_assessor_comps
        await _run_offline("assessor_comps", enrich_assessor_comps)
    except ImportError:
        print("  [assessor_comps] SKIP - module not found")

    # 3t. Assessor card
    try:
        from foreclosure_scraper.enrichment_assessor_card import enrich_assessor_card
        await _run_offline("assessor_card", enrich_assessor_card)
    except ImportError:
        print("  [assessor_card] SKIP - module not found")

    # 3u. County sales roll
    try:
        from foreclosure_scraper.enrichment_county_sales import enrich_county_sales
        await _run_async("county_sales", enrich_county_sales, 600)
    except ImportError:
        print("  [county_sales] SKIP - module not found")

    # 3v. LRCPWA parcel
    try:
        from foreclosure_scraper.enrichment_lrcpwa_parcel import enrich_lrcpwa_parcel
        await _run_async("lrcpwa_parcel", enrich_lrcpwa_parcel, 600)
    except ImportError:
        print("  [lrcpwa_parcel] SKIP - module not found")

    # 3w. NC case status (Tyler)
    try:
        from foreclosure_scraper.enrichment_nc_case_status import enrich_with_nc_case_status_dispatched
        await _run_async("nc_case_status", enrich_with_nc_case_status_dispatched, 600)
    except ImportError:
        print("  [nc_case_status] SKIP - module not found")

    # 3x. Court balance due / judgment amount
    try:
        from foreclosure_scraper.enrichment_judgment_amount import enrich_judgment_amount
        await _run_async("judgment_amount", enrich_judgment_amount, 300)
    except ImportError:
        print("  [judgment_amount] SKIP - module not found")

    # 3y-bis. Judgment detail pages — fetch law-firm detail pages for missing
    # judgment_amounts (only for sources with known detail-page URLs).
    try:
        from foreclosure_scraper.enrichment_judgment_detail import enrich_judgment_amount_via_detail_pages
        await _run_async("judgment_detail", enrich_judgment_amount_via_detail_pages, 300)
    except ImportError:
        print("  [judgment_detail] SKIP - module not found")

    # 3y-bis2. SC case-detail page rendering — resolves placeholder lis pendens
    # addresses + captures court sale status / judgment from Public Index.
    try:
        from foreclosure_scraper.enrichment_case_detail import enrich_case_detail_addresses
        await _run_async("case_detail", enrich_case_detail_addresses, 600)
    except ImportError:
        print("  [case_detail] SKIP - module not found")

    # 3y. Upset bid window
    try:
        from foreclosure_scraper.enrichment_upset_bid import enrich_upset_bid
        await _run_offline("upset_bid", enrich_upset_bid)
    except ImportError:
        print("  [upset_bid] SKIP - module not found")

    # 3z. Court bid
    try:
        from foreclosure_scraper.enrichment_court_bid import enrich_court_bid
        await _run_async("court_bid", enrich_court_bid, 300)
    except ImportError:
        print("  [court_bid] SKIP - module not found")

    # 3aa. NC divorce
    try:
        from foreclosure_scraper.enrichment_nc_divorce import enrich_nc_divorce
        await _run_async("nc_divorce", enrich_nc_divorce, 300)
    except ImportError:
        print("  [nc_divorce] SKIP - module not found")

    # 3ab. SC divorce
    try:
        from foreclosure_scraper.enrichment_sc_divorce import enrich_sc_divorce
        await _run_async("sc_divorce", enrich_sc_divorce, 600)
    except ImportError:
        print("  [sc_divorce] SKIP - module not found")

    # 3ac. Rollback deferral exposure
    try:
        # Enable Anderson SC agricultural rollback (PDF parse, ~11k rows/book)
        os.environ.setdefault("ROLLBACK_ANDERSON", "1")
        os.environ.setdefault("ROLLBACK_ANDERSON_BOOKS", "2")
        from foreclosure_scraper.enrichment_rollback_deferral import enrich_with_rollback_exposure
        await _run_async("rollback_deferral", enrich_with_rollback_exposure, 300)
    except ImportError:
        print("  [rollback_deferral] SKIP - module not found")

    # 3ad. Septic status
    try:
        from foreclosure_scraper.enrichment_septic_status import enrich_with_septic_status
        await _run_async("septic_status", enrich_with_septic_status, 300)
    except ImportError:
        print("  [septic_status] SKIP - module not found")

    # 3ae. Rent comps extra
    try:
        from foreclosure_scraper.enrichment_rent_comps_extra import enrich_with_extra_rent_comps
        await _run_async("rent_comps_extra", enrich_with_extra_rent_comps, 900)
    except ImportError:
        print("  [rent_comps_extra] SKIP - module not found")

    # 3af. Geocode (free Census/Nominatim — backfills lat/lon)
    try:
        from foreclosure_scraper.enrichment_geocode import enrich as enrich_geocode
        await _run_async("geocode", enrich_geocode, 600)
    except ImportError:
        print("  [geocode] SKIP - module not found")

    # 3ag. County phone (free county-published owner phone)
    try:
        from foreclosure_scraper.enrichment_county_phone import enrich_county_phone
        await _run_async("county_phone", enrich_county_phone, 600)
    except ImportError:
        print("  [county_phone] SKIP - module not found")

    # 3ag-bis. SC phone via NC voter file cross-reference (free)
    try:
        from foreclosure_scraper.enrichment_sc_voter_xref import enrich_sc_phone_xref
        await _run_offline("sc_voter_xref", enrich_sc_phone_xref, timeout_s=600)
    except ImportError:
        print("  [sc_voter_xref] SKIP - module not found")

    # 3ag-ter. Free people-search phones (TruePeopleSearch/FastPeopleSearch — covers SC gaps)
    try:
        from foreclosure_scraper.enrichment_free_phones import enrich_free_phones
        await _run_async("free_phones", enrich_free_phones, 900)
    except ImportError:
        print("  [free_phones] SKIP - module not found")

    # 3ah. Owner mailing (free county GIS owner+mailing address)
    try:
        from foreclosure_scraper.enrichment_owner_mailing import enrich_owner_mailing
        await _run_async("owner_mailing", enrich_owner_mailing, 900)
    except ImportError:
        print("  [owner_mailing] SKIP - module not found")

    # 3ai. Parcel from geo (resolve parcel_id from lat/lon)
    try:
        from foreclosure_scraper.enrichment_parcel_from_geo import enrich_parcel_from_geo
        await _run_async("parcel_from_geo", enrich_parcel_from_geo, 600)
    except ImportError:
        print("  [parcel_from_geo] SKIP - module not found")

    # 3aj. Parcel reverse geo (reverse geocode for missing addresses)
    try:
        from foreclosure_scraper.enrichment_parcel_reverse_geo import enrich_parcel_reverse_geo
        await _run_async("parcel_reverse_geo", enrich_parcel_reverse_geo, 600)
    except ImportError:
        print("  [parcel_reverse_geo] SKIP - module not found")

    # 3ak. Assessor photo (free county assessor property photos)
    try:
        from foreclosure_scraper.enrichment_assessor_photo import enrich_assessor_photo
        await _run_async("assessor_photo", enrich_assessor_photo, 600)
    except ImportError:
        print("  [assessor_photo] SKIP - module not found")

    # 3al. Streetview (free Google Street View static images)
    try:
        from foreclosure_scraper.enrichment_streetview import enrich_streetview
        await _run_async("streetview", enrich_streetview, 600)
    except ImportError:
        print("  [streetview] SKIP - module not found")

    # 3am. QPayBill tax (free SC county tax portals — Spartanburg, Cherokee,
    # Laurens, Union, Oconee). ~8,400 SC listings need tax_owed balances.
    # Previously self-gated on QPAYBILL_TAX=1 (never set → enricher did nothing).
    os.environ.setdefault("QPAYBILL_TAX", "1")
    os.environ.setdefault("QPAYBILL_MAX_QUERIES", "2000")
    os.environ.setdefault("QPAYBILL_MAX_SECONDS", "1800")
    try:
        from foreclosure_scraper.enrichment_qpaybill_tax import enrich_qpaybill_tax
        await _run_async("qpaybill_tax", enrich_qpaybill_tax, 1800)
    except ImportError:
        print("  [qpaybill_tax] SKIP - module not found")

    # 3an. Aumentum ROD (free register of deeds — Buncombe etc.)
    try:
        from foreclosure_scraper.enrichment_aumentum_rod import enrich_aumentum_rod
        await _run_async("aumentum_rod", enrich_aumentum_rod, 900)
    except ImportError:
        print("  [aumentum_rod] SKIP - module not found")

    # 3ao. CCHS ROD (free register of deeds — Cleveland etc.)
    try:
        from foreclosure_scraper.enrichment_cchs_rod import enrich_cchs_rod
        await _run_async("cchs_rod", enrich_cchs_rod, 900)
    except ImportError:
        print("  [cchs_rod] SKIP - module not found")

    # 3ap. Gaston ROD (free Gaston County register of deeds)
    try:
        from foreclosure_scraper.enrichment_gaston_rod import enrich_gaston_rod
        await _run_async("gaston_rod", enrich_gaston_rod, 600)
    except ImportError:
        print("  [gaston_rod] SKIP - module not found")

    # 3aq. Spartanburg ROD (free Spartanburg County register of deeds)
    try:
        from foreclosure_scraper.enrichment_spartanburg_rod import enrich_spartanburg_rod
        await _run_async("spartanburg_rod", enrich_spartanburg_rod, 600)
    except ImportError:
        print("  [spartanburg_rod] SKIP - module not found")

    # 3aq-bis. Generic ROD (COTT + Kofile + Acclaim — Polk NC, Pickens SC, Oconee SC)
    try:
        from foreclosure_scraper.enrichment_generic_rod import enrich_generic_rod
        await _run_async("generic_rod", enrich_generic_rod, 900)
    except ImportError:
        print("  [generic_rod] SKIP - module not found")

    # 3ar. Bankruptcy property (free PACER search)
    try:
        from foreclosure_scraper.enrichment_bankruptcy_property import enrich_bankruptcy_property
        await _run_async("bankruptcy_property", enrich_bankruptcy_property, 600)
    except ImportError:
        print("  [bankruptcy_property] SKIP - module not found")

    # 3as. HUD REAC address (free HUD REAC inspection records)
    try:
        from foreclosure_scraper.enrichment_hud_reac_address import enrich_hud_reac_address
        await _run_async("hud_reac_address", enrich_hud_reac_address, 300)
    except ImportError:
        print("  [hud_reac_address] SKIP - module not found")

    # 3at. NCPTS LRC CAMA (free, all 100 NC counties, full CAMA data)
    try:
        from foreclosure_scraper.enrichment_ncpts_lrc import enrich_batch_ncpts_lrc
        await _run_async("ncpts_lrc", enrich_batch_ncpts_lrc, 900)
    except ImportError:
        print("  [ncpts_lrc] SKIP - module not found")

    # 3au. Census Geocoder (free address standardization + lat/lon + tract)
    try:
        from foreclosure_scraper.enrichment_census_geocoder import enrich_batch_census_geocoder
        await _run_async("census_geocoder", enrich_batch_census_geocoder, 600)
    except ImportError:
        print("  [census_geocoder] SKIP - module not found")

    # 3av. EPA EnviroFacts (free environmental hazard overlay)
    try:
        from foreclosure_scraper.enrichment_envirofacts import enrich_batch_envirofacts
        await _run_async("envirofacts", enrich_batch_envirofacts, 600)
    except ImportError:
        print("  [envirofacts] SKIP - module not found")

    # 3aw. Address owner v2 (free address-based owner resolution)
    try:
        from foreclosure_scraper.enrichment_address_owner_v2 import enrich_addresses_from_owner_v2
        await _run_async("address_owner_v2", enrich_addresses_from_owner_v2, 300)
    except ImportError:
        print("  [address_owner_v2] SKIP - module not found")

    # 3ax. ROD name index (free register of deeds name-based search)
    try:
        from foreclosure_scraper.enrichment_rod_name_index import enrich_rod_name_index
        await _run_async("rod_name_index", enrich_rod_name_index, 300)
    except ImportError:
        print("  [rod_name_index] SKIP - module not found")
    except Exception as e:
        stats["rod_name_index"] = f"ERR: {e}"
        print(f" ERR: {e}")

    # 3ay. USFWS Wetlands (free, no key)
    try:
        from foreclosure_scraper.enrichment_usfws_wetlands import enrich_batch_usfws_wetlands
        await _run_async("usfws_wetlands", enrich_batch_usfws_wetlands, 300, max_concurrent=3)
        stats["usfws_wetlands"] = "OK"
    except ImportError:
        print("  [usfws_wetlands] SKIP - module not found")
        stats["usfws_wetlands"] = "SKIP"
    except Exception as e:
        stats["usfws_wetlands"] = f"ERR: {e}"
        print(f" ERR: usfws_wetlands: {e}")

    # 3az. NC OneMap geospatial (free, NC only)
    try:
        from foreclosure_scraper.enrichment_nc_onemap import enrich_batch_nc_onemap
        await _run_async("nc_onemap", enrich_batch_nc_onemap, 300, max_concurrent=3)
        stats["nc_onemap"] = "OK"
    except ImportError:
        print("  [nc_onemap] SKIP - module not found")
        stats["nc_onemap"] = "SKIP"
    except Exception as e:
        stats["nc_onemap"] = f"ERR: {e}"
        print(f" ERR: nc_onemap: {e}")

    # 3ba. Redfin Data Center (free ZIP-level CSV)
    try:
        from foreclosure_scraper.enrichment_redfin_datacenter import enrich_batch_redfin_datacenter
        await _run_async("redfin_datacenter", enrich_batch_redfin_datacenter, 300, max_concurrent=3)
        stats["redfin_datacenter"] = "OK"
    except ImportError:
        print("  [redfin_datacenter] SKIP - module not found")
        stats["redfin_datacenter"] = "SKIP"
    except Exception as e:
        stats["redfin_datacenter"] = f"ERR: {e}"
        print(f" ERR: redfin_datacenter: {e}")

    # 3bb. FBI UCR (needs FBI_API_KEY in .env)
    try:
        from foreclosure_scraper.enrichment_fbi_ucr import enrich_batch_fbi_ucr
        await _run_async("fbi_ucr", enrich_batch_fbi_ucr, 300, max_concurrent=3)
        stats["fbi_ucr"] = "OK"
    except ImportError:
        print("  [fbi_ucr] SKIP - module not found")
        stats["fbi_ucr"] = "SKIP"
    except Exception as e:
        stats["fbi_ucr"] = f"ERR: {e}"
        print(f" ERR: fbi_ucr: {e}")

    # 3bc. Realtor.com Data Library (free CSV)
    try:
        from foreclosure_scraper.enrichment_realtor_data import enrich_batch_realtor_data
        await _run_async("realtor_data", enrich_batch_realtor_data, 300, max_concurrent=3)
        stats["realtor_data"] = "OK"
    except ImportError:
        print("  [realtor_data] SKIP - module not found")
        stats["realtor_data"] = "SKIP"
    except Exception as e:
        stats["realtor_data"] = f"ERR: {e}"
        print(f" ERR: realtor_data: {e}")

    # 3bd. USDA ERS (optional USDA_API_KEY)
    try:
        from foreclosure_scraper.enrichment_usda_ers import enrich_batch_usda_ers
        await _run_async("usda_ers", enrich_batch_usda_ers, 300, max_concurrent=3)
        stats["usda_ers"] = "OK"
    except ImportError:
        print("  [usda_ers] SKIP - module not found")
        stats["usda_ers"] = "SKIP"
    except Exception as e:
        stats["usda_ers"] = f"ERR: {e}"
        print(f" ERR: usda_ers: {e}")

    # 3be. NC SOS business entity search (403-bypass)
    try:
        from foreclosure_scraper.enrichment_nc_sos import enrich_batch_nc_sos
        await _run_async("nc_sos", enrich_batch_nc_sos, 300, max_concurrent=3)
        stats["nc_sos"] = "OK"
    except ImportError:
        print("  [nc_sos] SKIP - module not found")
        stats["nc_sos"] = "SKIP"
    except Exception as e:
        stats["nc_sos"] = f"ERR: {e}"
        print(f" ERR: nc_sos: {e}")

    # 3bf. NC DOJ consumer protection (403-bypass)
    try:
        from foreclosure_scraper.enrichment_nc_doj import enrich_batch_nc_doj
        await _run_async("nc_doj", enrich_batch_nc_doj, 300, max_concurrent=3)
        stats["nc_doj"] = "OK"
    except ImportError:
        print("  [nc_doj] SKIP - module not found")
        stats["nc_doj"] = "SKIP"
    except Exception as e:
        stats["nc_doj"] = f"ERR: {e}"
        print(f" ERR: nc_doj: {e}")

    # 3bg. Charlotte code enforcement (403-bypass)
    try:
        from foreclosure_scraper.enrichment_charlotte_code import enrich_batch_charlotte_code
        await _run_async("charlotte_code", enrich_batch_charlotte_code, 300, max_concurrent=3)
        stats["charlotte_code"] = "OK"
    except ImportError:
        print("  [charlotte_code] SKIP - module not found")
        stats["charlotte_code"] = "SKIP"
    except Exception as e:
        stats["charlotte_code"] = f"ERR: {e}"
        print(f" ERR: charlotte_code: {e}")

    # 3bh. Greensboro code enforcement (403-bypass)
    try:
        from foreclosure_scraper.enrichment_greensboro_code import enrich_batch_greensboro_code
        await _run_async("greensboro_code", enrich_batch_greensboro_code, 300, max_concurrent=3)
        stats["greensboro_code"] = "OK"
        print(" OK: greensboro_code")
    except ImportError:
        print("  [greensboro_code] SKIP - module not found")
    except Exception as e:
        stats["greensboro_code"] = f"ERR: {e}"
        print(f" ERR: greensboro_code: {e}")

    # 3bi. DNC scrub (FTC Do Not Call Registry - free)
    try:
        from foreclosure_scraper.enrichment_dnc import enrich_dnc_scrub
        await _run_offline("dnc_scrub", enrich_dnc_scrub)
    except ImportError:
        print("  [dnc_scrub] SKIP - module not found")
    except Exception as e:
        stats["dnc_scrub"] = f"ERR: {e}"
        print(f" ERR: dnc_scrub: {e}")

    # 3bj. Marriage license signals (NC ROD - free public records)
    try:
        from foreclosure_scraper.enrichment_marriage_license import enrich_marriage_licenses
        await _run_offline("marriage_licenses", enrich_marriage_licenses)
    except ImportError:
        print("  [marriage_licenses] SKIP - module not found")
    except Exception as e:
        stats["marriage_licenses"] = f"ERR: {e}"
        print(f" ERR: marriage_licenses: {e}")

    # 3bk. Workflow automation (if-this-then-that triggers)
    try:
        from foreclosure_scraper.workflow_engine import evaluate_workflows
        wf_result = evaluate_workflows(board)
        stats["workflows"] = f"OK ({wf_result['total_matches']} matches)"
        print(f" OK: workflows ({wf_result['total_matches']} matches)")
    except ImportError:
        print("  [workflows] SKIP - module not found")
    except Exception as e:
        stats["workflows"] = f"ERR: {e}"
        print(f" ERR: workflows: {e}")

    # 3bl. Analytics dashboard
    try:
        from foreclosure_scraper.analytics_dashboard import generate_dashboard
        dash_path = generate_dashboard(board)
        stats["analytics_dashboard"] = f"OK ({dash_path})"
        print(f" OK: analytics_dashboard -> {dash_path}")
    except ImportError:
        print("  [analytics_dashboard] SKIP - module not found")
    except Exception as e:
        stats["analytics_dashboard"] = f"ERR: {e}"
        print(f" ERR: analytics_dashboard: {e}")

    # 3bm. Email extraction (surface emails already in raw data)
    try:
        from foreclosure_scraper.enrichment_email_extract import enrich_extract_emails
        email_result = enrich_extract_emails(board)
        stats["email_extraction"] = f"OK ({email_result['listings_with_emails']} listings, {email_result['total_emails']} emails)"
        print(f" OK: email_extraction ({email_result['listings_with_emails']} listings, {email_result['total_emails']} emails)")
    except ImportError:
        print("  [email_extraction] SKIP - module not found")
    except Exception as e:
        stats["email_extraction"] = f"ERR: {e}"
        print(f" ERR: email_extraction: {e}")

    # 3bn. Surface contact phones/emails already in raw data
    try:
        from foreclosure_scraper.enrichment_surface_contacts import enrich_surface_contacts
        contact_result = enrich_surface_contacts(board)
        stats["surface_contacts"] = f"OK ({contact_result['listings_with_new_phones']} phones, {contact_result['listings_with_new_emails']} emails)"
        print(f" OK: surface_contacts ({contact_result['listings_with_new_phones']} phones, {contact_result['listings_with_new_emails']} emails)")
    except ImportError:
        print("  [surface_contacts] SKIP - module not found")
    except Exception as e:
        stats["surface_contacts"] = f"ERR: {e}"
        print(f" ERR: surface_contacts: {e}")

    # 3bo. HUD FMR rent estimates (free, no API key needed)
    try:
        from foreclosure_scraper.enrichment_hud_fmr import enrich_hud_fmr
        fmr_result = await _run_async("hud_fmr", enrich_hud_fmr, 300)
        if isinstance(fmr_result, dict):
            stats["hud_fmr"] = f"OK ({fmr_result.get('listings_with_rent', 0)} rent estimates)"
            print(f" OK: hud_fmr ({fmr_result.get('listings_with_rent', 0)} rent estimates)")
        else:
            stats["hud_fmr"] = "OK"
    except ImportError:
        print("  [hud_fmr] SKIP - module not found")
        stats["hud_fmr"] = "SKIP"
    except Exception as e:
        stats["hud_fmr"] = f"ERR: {e}"
        print(f" ERR: hud_fmr: {e}")

    # 3bp. OCR extraction on legal notice PDFs/images
    try:
        from foreclosure_scraper.enrichment_ocr import enrich_ocr_extraction
        ocr_result = enrich_ocr_extraction(board)
        stats["ocr_extraction"] = f"OK ({ocr_result.get('processed', 0)} processed, {ocr_result.get('extracted_case', 0)} cases, {ocr_result.get('extracted_date', 0)} dates)"
        print(f" OK: ocr_extraction ({ocr_result.get('processed', 0)} processed, {ocr_result.get('extracted_case', 0)} cases, {ocr_result.get('extracted_date', 0)} dates, {ocr_result.get('extracted_phone', 0)} phones, {ocr_result.get('extracted_email', 0)} emails)")
    except ImportError:
        print("  [ocr_extraction] SKIP - module not found")
    except Exception as e:
        stats["ocr_extraction"] = f"ERR: {e}"
        print(f" ERR: ocr_extraction: {e}")

    # 3bq. SC phone cross-reference (SC owners vs NC voter file)
    try:
        from foreclosure_scraper.enrichment_sc_voter_xref import enrich_sc_phone_xref
        xref_result = enrich_sc_phone_xref(board)
        stats["sc_voter_xref"] = f"OK ({xref_result.get('matched', 0)} SC phones from NC voter xref)"
        print(f" OK: sc_voter_xref ({xref_result.get('matched', 0)} SC phones from NC voter xref)")
    except ImportError:
        print("  [sc_voter_xref] SKIP - module not found")
    except Exception as e:
        stats["sc_voter_xref"] = f"ERR: {e}"
        print(f" ERR: sc_voter_xref: {e}")

    # 4. POST-NETWORK offline enrichers (second pass, with new data)
    print("\n[4] POST-NETWORK recompute (second pass with new data)...")

    # Re-run equity with new ROD/debt data
    await _run_offline("equity_recompute", enrich_equity)
    # Re-run amount owed
    await _run_offline("amount_owed_recompute", enrich_amount_owed)
    # Re-run title risk
    await _run_offline("title_risk_recompute", enrich_title_risk)
    # Re-run distress stack
    await _run_offline("distress_recompute", score_board)
    # Re-run strategy fit
    await _run_offline("strategy_fit_recompute", enrich_strategy_fit)
    # Re-run derivation flags
    await _run_offline("derivation_flags_recompute", enrich_derivation_flags)
    # Re-run derived signals
    await _run_offline("derived_signals_recompute", enrich_derived_signals)
    # Re-run corroboration
    await _run_offline("corroboration_recompute", enrich_corroboration)
    # Re-run competition
    await _run_offline("competition_recompute", enrich_competition)
    # Re-run lead signals
    await _run_offline("lead_signals_recompute", enrich_lead_signals)
    # Re-run buyer match
    await _run_offline("buyer_match_recompute", enrich_buyer_match)
    # Re-run data quality
    await _run_offline("data_quality_recompute", enrich_data_quality)
    # Re-run board quality
    await _run_offline("board_quality_recompute", enrich_board_quality)
    # Re-run last sale
    await _run_offline("last_sale_recompute", enrich_last_sale)
    # Re-run board QA
    await _run_offline("board_qa_recompute", enrich_board_qa)
    # Re-run source link
    await _run_offline("source_link_recompute", enrich_source_link)
    # Re-run source consistency
    await _run_offline("source_consistency_recompute", enrich_source_consistency)

    # Property categorization (must run AFTER all other enrichers so it can
    # read sale_status, rod flags, distress_stack, derivation_flags, etc.)
    from foreclosure_scraper.enrichment_property_category import enrich_property_category
    await _run_offline("property_category", enrich_property_category)

    # 5. AFTER snapshot
    after = _coverage(board)
    print(f"\n[5] AFTER: {len(after)} enrichment fields present")
    for k, (n, pct) in list(after.items())[:25]:
        before_vals = before.get(k, (0, 0))
        delta = n - before_vals[0]
        delta_str = f" (+{delta})" if delta > 0 else (f" ({delta})" if delta < 0 else "")
        print(f"  {k:40s} {n:6d}  {pct:5.1f}%{delta_str}")

    # 6. Print enricher results
    print(f"\n[6] ENRICHER RESULTS:")
    for k, v in sorted(stats.items()):
        print(f"  {k:40s} {v}")

    # 7. Write board
    by_state = Counter(li.state or "?" for li in board)
    by_county = Counter(f"{li.county or '?'}/{li.state or '?'}" for li in board)
    by_source = Counter(li.source or "?" for li in board)

    summary = {
        "total": len(board),
        "enrichment_pass": "comprehensive",
        "enrichers": {k: str(v) for k, v in stats.items()},
        "by_state": dict(by_state),
        "by_county_top": by_county.most_common(20),
        "by_source_top": by_source.most_common(20),
        "notes": "comprehensive enrichment pass: all free enrichers run against existing board",
    }

    # Deduplicate using Listing.dedupe_key() — same logic board_selfcheck uses.
    seen_keys: set[str] = set()
    deduped: list = []
    for li in board:
        key = li.dedupe_key()
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        deduped.append(li)
    if len(deduped) < len(board):
        print(f"\n  Dedup: {len(board)} -> {len(deduped)} ({len(board) - len(deduped)} duplicates removed)")
        board = deduped

    print(f"\n[7] Writing board: {len(board)} listings...")
    write_artifact(board, summary, docs_dir)
    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print(f"COMPLETE: {len(board)} listings enriched in {elapsed:.0f}s")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
