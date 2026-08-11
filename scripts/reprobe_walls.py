#!/usr/bin/env python3
"""Quarterly wall re-probe.

`honest_operator_manual.md` says: "Eleven of eighteen top walls were stale or
misdiagnosed... A quarterly re-probe job would have caught all eleven. That job
does not exist yet." This is that job.

Walls flip in BOTH directions and the manual's own snapshot is already drifting
(verified 2026-08-06): BusinessesForSale went back to 403, USDA RD now 500s,
Aldridge Pite's URL 404s, while Greenville probate and LOGS are still wide open.
A source you wrote off as dead is a source your competitors are still working.

Two request tiers, same as the manual's methodology:
  tier 1  plain HTTP (requests)
  tier 2  browser-parity headers; if that still fails and Playwright is
          installed, a real headless fetch

Writes docs/wall_status.json and prints only CHANGES vs the last run, so
running it is cheap and the output is short.

    python3 scripts/reprobe_walls.py            # probe all
    python3 scripts/reprobe_walls.py --full     # print every row, not just changes
"""
import json, os, sys, time
from datetime import date
import requests as rq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'docs', 'wall_status.json')

PLAIN = {'User-Agent': 'python-requests/2.31'}
PARITY = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Sec-Fetch-Dest': 'document', 'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none', 'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1', 'Connection': 'keep-alive',
}

# name -> (url, bucket, note). Bucket mirrors the manual's A-E taxonomy.
WALLS = {
    # --- E: solvable, reachable, not built. Highest value to re-check. ---
    'greenville_sc_probate':   ('https://www.greenvillecounty.org/appsAS400/Probate/Search.aspx', 'E', 'manual ranks this the largest free win on the board'),
    'irsauctions':             ('https://www.irsauctions.gov/auction/items?state=NC', 'E', 'accepts ?state=NC'),
    'logs_shapiro':            ('https://www.logs.com/nc-upcoming-sales-report.html', 'E', 'PowerBI embed, NC trustee sales'),
    'govdeals':                ('https://www.govdeals.com/', 'E', 're-key'),
    'usda_rd_resales':         ('https://properties.sc.egov.usda.gov/resales/public/RealEstate', 'E', 'was 200, now 500 as of 2026-08-06'),
    'businessesforsale_nc':    ('https://www.businessesforsale.com/us/search/businesses-for-sale-in-north-carolina', 'E', 'manual said 200; flipped back to 403 on 2026-08-06'),
    'legacy_obits_nc':         ('https://www.legacy.com/us/obituaries/local/north-carolina', 'E', 'manual said 288 links; URL 404s as of 2026-08-06, find new path'),
    'fannie_homepath':         ('https://www.homepath.com/', 'E', 're-resolver'),
    'aldridge_pite':           ('https://www.aldridgepite.com/', 'E', 'sales URL 404s, find current path'),

    # --- A/B: known walls. Confirm they are STILL walls before anyone re-spends time. ---
    'nc_ecourts_portal':       ('https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29', 'A', 'AWS WAF image grid'),
    'nc_judgment_search':      ('https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/', 'B', 'open JSON, serves FAM-Divorce cause filter'),
    'sc_publicindex':          ('https://publicindex.sccourts.org/Spartanburg/PublicIndex/', 'A', 'F5/Shape + Rule 610 ToS ban. DO NOT WIDEN'),
    'sc_sos_business':         ('https://businessfilings.sc.gov/BusinessFiling/Entity/Search', 'A', 'reCAPTCHA'),
    'nc_sos':                  ('https://www.sosnc.gov/online_services/search/by_title/_Business_Registration', 'A', 'Cloudflare; stealth-only'),
    'propwire':                ('https://propwire.com/', 'A', 'DataDome'),
    'kofile_oconee_rod':       ('https://oconee.sc.publicsearch.us/', 'A', 'robots.txt Disallow: / — belongs in bucket A, not BUILD_NOW'),
    'scdot_parcels':           ('https://services2.arcgis.com/XZg2efAbaieYAXmu/arcgis/rest/services/SC_Parcels/FeatureServer/0?f=json', 'A', 'went token-required; watch for re-open'),

    # --- Live production sources. Early warning if one silently dies. ---
    'hutchens':                ('https://sales.hutchenslawfirm.com/NCfcSalesList.aspx', 'LIVE', 'largest NC trustee feed'),
    'brock_scott':             ('https://www.brockandscott.com/foreclosure-sales/', 'LIVE', 'NC+SC'),
    'ingle_firm':              ('https://www.theinglefirm.com/Sales.aspx', 'LIVE', 'carries postponement dates'),
    'kania':                   ('https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/', 'LIVE', 'NC tax FC, 25 counties'),
    'zls':                     ('https://www.zls-nc.com/listings', 'LIVE', 'Blazor; needs browser'),
    'ncnotices':               ('https://www.ncnotices.com/', 'LIVE', 'WebForms viewstate'),
    'scpublicnotices':         ('https://www.scpublicnotices.com/', 'LIVE', 'saved-search email alerts'),
    'nc_onemap_parcels':       ('https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1?f=json', 'LIVE', 'join spine'),
    'ncsbe_voter':             ('https://dl.ncsbe.gov/?prefix=data/', 'LIVE', 'weekly Saturday refresh'),
}

def probe(url):
    """Return (tier, status, size). tier: plain | parity | browser | dead."""
    for tier, hdrs in (('plain', PLAIN), ('parity', PARITY)):
        try:
            r = rq.get(url, headers=hdrs, timeout=30, allow_redirects=True)
            if r.status_code == 200 and len(r.content) > 500:
                return tier, r.status_code, len(r.content)
            last = (r.status_code, len(r.content))
        except Exception:
            last = (0, 0)
        time.sleep(1)
    # optional third tier
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page()
            pg.goto(url, wait_until='domcontentloaded', timeout=45000)
            pg.wait_for_timeout(2500)
            n = len(pg.content())
            b.close()
            if n > 2000:
                return 'browser', 200, n
    except Exception:
        pass
    return 'dead', last[0], last[1]

def main():
    full = '--full' in sys.argv
    prev = {}
    if os.path.exists(STATE):
        prev = json.load(open(STATE)).get('walls', {})

    out, changes = {}, []
    for name, (url, bucket, note) in WALLS.items():
        tier, status, size = probe(url)
        out[name] = {'url': url, 'bucket': bucket, 'note': note,
                     'tier': tier, 'status': status, 'size': size}
        old = prev.get(name, {})
        if old and old.get('tier') != tier:
            changes.append(f"  {name}: {old.get('tier')} -> {tier} "
                           f"(HTTP {old.get('status')} -> {status})  [{bucket}] {note}")
        elif not old:
            changes.append(f"  {name}: NEW baseline = {tier} (HTTP {status}, {size}b)  [{bucket}]")
        if full:
            print(f"  {tier:8} {status:4} {size:>9}b  {name}")
        time.sleep(1.5)

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({'probed': str(date.today()), 'walls': out}, open(STATE, 'w'), indent=1)

    print(f"\n=== wall re-probe {date.today()} — {len(out)} sources")
    reachable = [n for n, v in out.items() if v['tier'] in ('plain', 'parity', 'browser')]
    print(f"reachable: {len(reachable)}/{len(out)}")
    if changes:
        print("\nCHANGES since last run:")
        for c in changes:
            print(c)
    else:
        print("\nNo status changes since last run.")

    # the thing that actually matters: bucket-E items that are reachable and unbuilt
    e_open = [n for n, v in out.items() if v['bucket'] == 'E' and v['tier'] != 'dead']
    if e_open:
        print(f"\nBUCKET E reachable and unbuilt ({len(e_open)}): {', '.join(e_open)}")
    dead_live = [n for n, v in out.items() if v['bucket'] == 'LIVE' and v['tier'] == 'dead']
    if dead_live:
        print(f"\n!! PRODUCTION SOURCE DOWN: {', '.join(dead_live)}")
    print(f"\nstate: {STATE}")

if __name__ == '__main__':
    main()
