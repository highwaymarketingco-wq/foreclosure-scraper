#!/usr/bin/env python3
"""Scan active zero-row sources for URLs and class structure."""
import os, re

SCRAPERS_DIR = 'src/foreclosure_scraper/scrapers'

ACTIVE_SOURCES = [
    'city_websites.asheville_min_housing',
    'counties_nc.asheville_code_enforcement',
    'counties_nc.brunswick_legal_notices',
    'counties_nc.buncombe_tax_foreclosure',
    'counties_nc.cumberland_delinquent_tax',
    'counties_nc.gaston_surplus_properties',
    'counties_nc.gaston_tax_foreclosures',
    'counties_nc.gaston_vacant',
    'counties_nc.haywood_tax_foreclosures',
    'counties_nc.henderson_tax',
    'counties_nc.iredell_delinquent_tax',
    'counties_nc.kinston_proposed_demolition',
    'counties_nc.lincoln_vacant',
    'counties_nc.mcdowell_probate',
    'counties_nc.mecklenburg_delinquent_tax',
    'counties_nc.mecklenburg_tax_foreclosures',
    'counties_nc.nc_bankruptcy_sales',
    'counties_nc.nc_cchs_deeds',
    'counties_nc.nc_county_csv_delinquent_tax',
    'counties_nc.nc_county_pdf_delinquent_tax',
    'counties_nc.nc_deq_dsca',
    'counties_nc.nc_metro_demolition_permits',
    'counties_nc.nc_rod_captcha',
    'counties_nc.nc_rod_logan',
    'counties_nc.nc_rowan_cott',
    'counties_nc.nchfa_reo',
    'counties_nc.rutherford_wildfire_tax',
    'counties_nc.wake_code_cases',
    'counties_nc.wnc_rod_foreclosure_starts',
    'counties_nc.wnc_tax_foreclosures',
    'counties_sc.anderson_sheriff',
    'counties_sc.bamberg_sheriff',
    'counties_sc.barnwell_sheriff',
    'counties_sc.charleston_energov_history',
    'counties_sc.cherokee_rod',
    'counties_sc.colleton_tax_sale',
    'counties_sc.dillon_sheriff',
    'counties_sc.greenville_mie_adverts',
    'counties_sc.greenwood_corebtpay_delinquent_tax',
    'counties_sc.horry_delinquent_xlsx',
    'counties_sc.horry_probate',
    'counties_sc.laurens_delinquent_tax',
    'counties_sc.laurens_overage_claims',
    'counties_sc.lexington_flc',
    'counties_sc.mccormick_flc',
    'counties_sc.meares_auctions',
    'counties_sc.oconee_tax_sale',
    'counties_sc.orangeburg_overage_claims',
    'counties_sc.pickens_tax_sale',
    'counties_sc.richland_flc',
    'counties_sc.sc_catalis_delinquent_roll',
    'counties_sc.sc_flc',
    'counties_sc.sc_rod_acclaim',
    'counties_sc.sc_rod_cott',
    'counties_sc.sc_tax_walled',
    'counties_sc.sc_ust_registry',
    'counties_sc.spartan_weekly_legals',
    'counties_sc.spartanburg_flc',
    'counties_sc.spartanburg_master_in_equity',
    'counties_sc.terry_howe_auctions',
    'counties_sc.terry_howe_flc',
    'counties_sc.union_delinquent_tax',
    'counties_sc.york_tax_sale_parcels',
    'counties_sc.zombie_properties',
    'law_firms.alaw',
    'law_firms.aldridge_pite',
    'national.cash_buyer_deeds',
    'national.foreclosure_dot_com',
    'national.hud_reac_inspection',
    'national.legacy_obituaries',
    'national.nc_unclaimed',
    'national.sheriff_sales',
    'national.usmarshals_realproperty',
    'national.williams',
    'newspapers.aiken_standard',
    'newspapers.berkeley_independent',
    'newspapers.carolina_coast',
    'newspapers.index_journal',
    'newspapers.journal_scene',
    'newspapers.post_and_courier',
    'newspapers.shelby_star',
    'newspapers.tryon_bulletin',
    'public_notices.echovita_obituaries',
    'public_notices.funeral_home_rss',
    'public_notices.nc_heir_notices',
]

for slug in ACTIVE_SOURCES:
    parts = slug.split('.')
    pkg, mod = parts[0], parts[1]
    path = os.path.join(SCRAPERS_DIR, pkg, mod + '.py')
    if not os.path.exists(path):
        print(f'MISSING  {slug}')
        continue
    content = open(path).read()
    # Find URL lines
    urls = re.findall(r'(?:URL|url|BASE_URL|base_url)\s*=\s*["\x27](https?://[^"\']+)["\x27]', content)
    lines = content.split('\n')
    doc_lines = [l for l in lines[:5] if l.strip() and '"""' in l or l.strip().startswith('#')]
    url_str = urls[0][:80] if urls else 'NO_URL'
    # Check for scope filter patterns
    has_in_footprint = 'footprint' in content.lower() or 'in_scope' in content.lower()
    has_county_filter = 'county' in content.lower()
    # Check board_count hint in source
    scope_hint = 'footprint-filtered' if has_in_footprint else ''
    print(f'  {slug}: {url_str}')
