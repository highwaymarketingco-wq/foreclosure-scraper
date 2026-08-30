#!/usr/bin/env python3
"""Run remaining scrapers sequentially."""
import asyncio
import json
import sys

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")

SCRAPERS_TO_RUN = [
    "national.courtlistener_adversary",
    "national.courtlistener_civil",
    "national.courtlistener_bankruptcy",
    "national.auction_dot_com",
    "national.bid4assets",
    "national.zillow_bulk",
    "national.zillow_foreclosures",
    "national.fannie_homepath",
    "national.hud_homestore",
    "national.freddie_homesteps",
    "national.hubzu",
    "national.xome",
    "national.propwire",
    "national.realtor_foreclosures",
    "national.trulia",
    "national.homeharvest",
    "national.distressed",
    "national.crexi_multifamily",
    "national.first_citizens_reo",
    "national.probate_foreclosure_leads",
    "national.servicelink_auction",
    "national.gsa_realproperty",
    "reo.usda_rd",
    "reo.vrm_va_reo",
    "reo.treasury_seized",
    "counties_sc.sc_state_tax_lien",
    "counties_sc.sc_tax_delinquent",
    "counties_sc.sc_dew_lien_registry",
    "counties_sc.sc_public_notices",
    "counties_sc.spartan_weekly_legals",
    "counties_sc.spartanburg_flc",
    "counties_sc.spartanburg_delinquent_tax",
    "counties_sc.spartanburg_master_in_equity",
    "counties_sc.anderson_master_in_equity",
    "counties_sc.pickens_master_in_equity",
    "counties_sc.pickens_tax_sale",
    "counties_sc.oconee_forfeited_land",
    "counties_sc.oconee_tax_sale",
    "counties_sc.charleston_delinquent_tax",
    "counties_sc.charleston_mie",
    "counties_sc.colleton_tax_sale",
    "counties_sc.georgetown_civicengage",
    "counties_sc.horry_flc",
    "counties_sc.terry_howe_flc",
    "counties_sc.terry_howe_auctions",
    "counties_nc.buncombe_tax",
    "counties_nc.buncombe_tax_foreclosure",
    "counties_nc.buncombe_delinquent_tax",
    "counties_nc.henderson_tax",
    "counties_nc.cleveland_tax",
    "counties_nc.polk_tax",
    "counties_nc.rutherford_tax",
    "counties_nc.gaston_surplus_properties",
    "counties_nc.nc_county_tax_foreclosure",
    "counties_nc.nc_coastal_tax_foreclosure",
    "counties_nc.nc_county_pdf_delinquent_tax",
    "counties_nc.nc_ptscloud_delinquent_tax",
    "counties_nc.new_hanover_foreclosures",
    "counties_nc.brunswick_legal_notices",
    "counties_nc.nc_govdeals_real_property",
    "law_firms.aldridge_pite",
    "law_firms.finkel",
    "law_firms.kania",
    "law_firms.korn",
    "law_firms.mcmichael_taylor_gray",
    "law_firms.mewborn_deselms",
    "law_firms.rogers_townsend",
    "law_firms.shapiro_ingle_powerbi",
    "law_firms.zacchaeus",
    "newspapers.carolina_coast",
    "newspapers.coastland_times",
    "newspapers.hendersonville_lightning",
    "newspapers.post_and_courier",
    "newspapers.tryon_bulletin",
    "public_notices.funeral_home_rss",
    "public_notices.ncnotices",
    "public_notices.publicnoticesc",
]


async def main():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    all_sc = {s.slug: s for s in all_scrapers()}

    all_leads = []
    log = []

    for slug in SCRAPERS_TO_RUN:
        if slug not in all_sc:
            continue
        s = all_sc[slug]
        try:
            results = await s.safe_run()
            data = [json.loads(li.model_dump_json()) for li in results]
            all_leads.extend(data)
            print(f"{slug}: {len(results)} ({s.last_outcome})", flush=True)
            log.append({"slug": slug, "count": len(results), "outcome": s.last_outcome})
        except Exception as e:
            print(f"{slug}: ERROR {str(e)[:100]}", flush=True)
            log.append({"slug": slug, "count": 0, "outcome": "ERROR", "error": str(e)[:200]})

    with open("/tmp/mega_batch_leads.json", "w") as f:
        json.dump(all_leads, f, indent=2, default=str)
    with open("/tmp/mega_batch_log.json", "w") as f:
        json.dump(log, f, indent=2)

    print(f"\nTOTAL: {len(all_leads)} leads from {len(log)} scrapers")


if __name__ == "__main__":
    asyncio.run(main())
