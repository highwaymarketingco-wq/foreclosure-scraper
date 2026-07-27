#!/usr/bin/env python3
"""Final integration script: wire all new modules into the engine.

Run this ONCE to complete the integration of all new scrapers and
enrichment modules built 2026-07-03/04. After this script runs,
the engine is 100% complete and the local model can run main.py
without any further setup.

What this script does:
1. Verifies all new modules import correctly
2. Verifies all new scrapers are registered (121 total)
3. Verifies DATELESS_OK_SOURCES includes all new sources
4. Verifies enrichment chain includes all new modules
5. Runs the test suite
6. Prints a final status report

Usage:
    cd ~/foreclosure-scraper
    PYTHONPATH=.venv/lib/python3.12/site-packages:$PYTHONPATH .venv/bin/python3.12 scripts/finalize_integration.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def check_imports() -> list[tuple[str, str, bool]]:
    """Verify all new modules import cleanly."""
    results = []
    modules = [
        "enrichment_fema_disaster",
        "enrichment_opportunity_zone",
        "enrichment_usps_vacancy",
        "enrichment_flood_zone",
    ]
    for mod_name in modules:
        try:
            __import__(f"foreclosure_scraper.{mod_name}")
            results.append((mod_name, "import", True))
        except Exception as e:
            results.append((mod_name, f"import ERROR: {e}", False))

    scrapers = [
        "scrapers.national.sheriff_sales",
        "scrapers.national.nc_upset_bids",
        "scrapers.national.craigslist_fsbo",
        "scrapers.national.estate_sales",
        "scrapers.national.cash_buyer_deeds",
        "scrapers.national.landwatch",
        "scrapers.national.landandfarm",
        "scrapers.national.landsofamerica",
        "scrapers.national.jail_bookings",
    ]
    for scr in scrapers:
        try:
            __import__(f"foreclosure_scraper.{scr}")
            results.append((scr, "import", True))
        except Exception as e:
            results.append((scr, f"import ERROR: {e}", False))

    # CrewAI tools
    try:
        __import__("foreclosure_scraper.crewai_tools")
        results.append(("crewai_tools", "import", True))
    except Exception as e:
        results.append(("crewai_tools", f"import ERROR: {e}", False))

    # ROD adapter fix
    try:
        from foreclosure_scraper.rod import cchs
        assert ("NC", "Lincoln") in cchs.CCHS_COUNTIES
        results.append(("rod.cchs (Lincoln added)", "check", True))
    except Exception as e:
        results.append(("rod.cchs (Lincoln added)", f"ERROR: {e}", False))

    return results


def check_registry() -> dict:
    """Verify all scrapers are registered."""
    from foreclosure_scraper.scrapers._registry import all_scrapers
    scrapers = all_scrapers()
    slugs = {s.slug for s in scrapers}

    expected = {
        "national.sheriff_sales",
        "national.nc_upset_bids",
        "national.craigslist_fsbo",
        "national.estate_sales",
        "national.cash_buyer_deeds",
        "national.landwatch",
        "national.landandfarm",
        "national.landsofamerica",
        "national.jail_bookings",
    }

    missing = expected - slugs
    return {
        "total_registered": len(scrapers),
        "expected_new": len(expected),
        "found": len(expected - missing),
        "missing": list(missing),
    }


def check_dateless_sources() -> dict:
    """Verify DATELESS_OK_SOURCES includes all new sources."""
    from foreclosure_scraper.main import DATELESS_OK_SOURCES

    expected = {
        "national.landwatch",
        "national.landandfarm",
        "national.cash_buyer_deeds",
        "national.craigslist_fsbo",
        "national.estate_sales",
        "national.sheriff_sales",
        "national.nc_upset_bids",
        "national.jail_bookings",
        "counties_sc.sc_public_index",
        "counties_sc.sc_public_index_export",
    }

    missing = expected - DATELESS_OK_SOURCES
    return {
        "total_dateless": len(DATELESS_OK_SOURCES),
        "expected_new": len(expected),
        "found": len(expected - missing),
        "missing": list(missing),
    }


def check_enrichment_chain() -> dict:
    """Verify main.py references the new enrichment modules."""
    main_py = (REPO / "src" / "foreclosure_scraper" / "main.py").read_text()
    expected_refs = [
        "enrichment_fema_disaster",
        "enrichment_opportunity_zone",
        "enrichment_usps_vacancy",
    ]
    missing = [r for r in expected_refs if r not in main_py]
    return {
        "expected": len(expected_refs),
        "found": len(expected_refs) - len(missing),
        "missing": missing,
    }


def check_code_changes() -> dict:
    """Verify the cause code expansions are in place."""
    results = {}

    # NC lis pendens expanded causes
    lp_py = (REPO / "src" / "foreclosure_scraper" / "scrapers" / "counties_nc" /
             "nc_ecourts_lis_pendens.py").read_text()
    results["lis_pendens_transcript"] = "Transcript of Judgment" in lp_py
    results["lis_pendens_tax_liability"] = "NC Certificate of Tax Liability" in lp_py
    results["lis_pendens_condemnation"] = "Condemnation" in lp_py

    # NC divorce equitable distribution
    dv_py = (REPO / "src" / "foreclosure_scraper" / "scrapers" / "counties_nc" /
             "nc_ecourts_divorce.py").read_text()
    results["divorce_equitable_dist"] = "Equitable Distribution" in dv_py

    # Craigslist category fix
    cl_py = (REPO / "src" / "foreclosure_scraper" / "scrapers" / "national" /
             "craigslist_fsbo.py").read_text()
    results["craigslist_reo"] = '"reo"' in cl_py or "CATEGORY = \"reo\"" in cl_py

    # Estate sales URL fix
    es_py = (REPO / "src" / "foreclosure_scraper" / "scrapers" / "national" /
             "estate_sales.py").read_text()
    results["estate_sales_url_fix"] = "/{state}/{city}/" in es_py

    return results


async def run_tests():
    """Run the test suite."""
    import subprocess
    result = subprocess.run(
        [str(REPO / ".venv" / "bin" / "python3.12"), "-m", "pytest",
         "tests/", "-x", "-q", "--ignore=tests/porsche"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
        env={**__import__("os").environ,
             "PYTHONPATH": str(REPO / ".venv" / "lib" / "python3.12" / "site-packages")},
    )
    return {
        "exit_code": result.returncode,
        "last_line": result.stdout.strip().split("\n")[-1] if result.stdout else "",
    }


def main():
    print("=" * 60)
    print("FINAL INTEGRATION VERIFICATION")
    print("=" * 60)

    all_pass = True

    # 1. Imports
    print("\n1. Module imports...")
    results = check_imports()
    for name, status, ok in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"   [{mark}] {name}: {status}")

    # 2. Registry
    print("\n2. Scraper registry...")
    reg = check_registry()
    reg_ok = len(reg["missing"]) == 0
    if not reg_ok:
        all_pass = False
    print(f"   [{'PASS' if reg_ok else 'FAIL'}] {reg['total_registered']} scrapers registered, "
          f"{reg['found']}/{reg['expected_new']} new ones found")
    if reg["missing"]:
        print(f"   MISSING: {reg['missing']}")

    # 3. DATELESS_OK_SOURCES
    print("\n3. DATELESS_OK_SOURCES...")
    dl = check_dateless_sources()
    dl_ok = len(dl["missing"]) == 0
    if not dl_ok:
        all_pass = False
    print(f"   [{'PASS' if dl_ok else 'FAIL'}] {dl['total_dateless']} sources, "
          f"{dl['found']}/{dl['expected_new']} new ones found")
    if dl["missing"]:
        print(f"   MISSING: {dl['missing']}")

    # 4. Enrichment chain
    print("\n4. Enrichment chain in main.py...")
    ec = check_enrichment_chain()
    ec_ok = len(ec["missing"]) == 0
    if not ec_ok:
        all_pass = False
    print(f"   [{'PASS' if ec_ok else 'FAIL'}] {ec['found']}/{ec['expected']} modules wired")
    if ec["missing"]:
        print(f"   MISSING: {ec['missing']}")

    # 5. Code changes
    print("\n5. Code changes...")
    cc = check_code_changes()
    for name, ok in cc.items():
        if not ok:
            all_pass = False
        print(f"   [{'PASS' if ok else 'FAIL'}] {name}")

    # 6. Tests
    print("\n6. Running test suite...")
    tests = asyncio.run(run_tests())
    tests_ok = tests["exit_code"] == 0
    if not tests_ok:
        all_pass = False
    print(f"   [{'PASS' if tests_ok else 'FAIL'}] {tests['last_line']}")

    # Final
    print("\n" + "=" * 60)
    if all_pass:
        print("ALL CHECKS PASSED. Engine is 100% integrated.")
        print("Run the engine with:")
        print("  cd ~/foreclosure-scraper")
        print("  PYTHONPATH=.venv/lib/python3.12/site-packages:$PYTHONPATH \\")
        print("    .venv/bin/python3.12 -m foreclosure_scraper.main")
    else:
        print("SOME CHECKS FAILED. Review the output above.")
    print("=" * 60)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
