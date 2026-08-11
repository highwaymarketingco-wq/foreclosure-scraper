#!/usr/bin/env python3
"""Triage the 51 registered-but-zero-row scrapers.

SOURCE_REGISTER says 51 of 137 scrapers contribute zero rows, and warns that a
zero "is NOT automatically a bug." Nobody has ever separated the buckets, so all
51 look equally like work. They are not.

Proven case (2026-08-06): `law_firms.zacchaeus` returns **210 live rows** and
contributes zero because every ZLS county is either on SCOPE_DENY_COUNTIES
(Guilford, Cabarrus, Forsyth, Iredell, Onslow) or simply outside the 18-county
footprint. The module is perfect. Debugging it would have been wasted days.

This classifies every zero-row module into one of five buckets:

  POLICY      returns rows, but 0 survive the footprint/deny filter
              -> DO NOT DEBUG. Revisit only if the footprint widens.
  PIPELINE    returns in-footprint rows, yet the board has none
              -> real bug, and the highest-value kind: the data is already there
  EMPTY       fetches fine, upstream genuinely has nothing right now
              -> seasonal or exhausted; recheck on its cycle
  BROKEN      raises, times out, or returns nothing with an error
              -> real work, prioritize by expected volume
  NOENTRY     no callable fetch path found; needs a human read

    python3 scripts/triage_zero_row_sources.py                  # all
    python3 scripts/triage_zero_row_sources.py law_firms.alaw   # specific
    python3 scripts/triage_zero_row_sources.py --timeout 90
"""
import argparse, asyncio, importlib, inspect, json, os, sys, time, traceback
from collections import Counter
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

def load_secrets():
    """Mirror run_local.sh: export .secrets/*.txt as UPPERCASE env vars.

    Without this the triage reports false BROKEN verdicts — sc_flc raises
    "no OCR key is configured" when run bare, but has its key in production.
    """
    d = os.path.join(ROOT, '.secrets')
    if not os.path.isdir(d):
        return 0
    n = 0
    for f in os.listdir(d):
        if not f.endswith('.txt'):
            continue
        key = f[:-4].upper()
        if os.environ.get(key):
            continue
        try:
            val = open(os.path.join(d, f)).read().strip()
        except Exception:
            continue
        if val:
            os.environ[key] = val
            n += 1
    return n

load_secrets()

# From SOURCE_REGISTER section 2 (built but producing zero rows).
ZERO_ROW = """
city_websites.search
counties.sitemap_walker
counties_generic.arcgis_distress_layers
counties_generic.epa_frs_sites
counties_generic.state_contamination
counties_nc.brunswick_legal_notices
counties_nc.buncombe_tax_foreclosure
counties_nc.gaston_surplus_properties
counties_nc.henderson_tax
counties_nc.nc_coastal_tax_foreclosure
counties_nc.nc_ecourts_estates
counties_nc.new_hanover_foreclosures
counties_nc.polk_tax
counties_nc.rutherford_wildfire_tax
counties_sc.charleston_delinquent_tax
counties_sc.cherokee_delinquent_tax
counties_sc.colleton_tax_sale
counties_sc.greenville_tax_distress
counties_sc.oconee_tax_sale
counties_sc.pickens_tax_sale
counties_sc.sc_coastal_rosters
counties_sc.sc_delinquent_tax_list
counties_sc.sc_dew_lien_registry
counties_sc.sc_flc
counties_sc.sc_probate_notices
counties_sc.sc_tax_delinquent
counties_sc.sc_ust_registry
law_firms.alaw
law_firms.aldridge_pite
law_firms.finkel
law_firms.ingle_firm
law_firms.korn
law_firms.mewborn_deselms
law_firms.zacchaeus
national.bid4assets
national.craigslist_fsbo
national.first_citizens_reo
national.gsa_realproperty
national.landsofamerica
national.probate_foreclosure_leads
national.propwire
newspapers.daily_courier
newspapers.hendersonville_lightning
newspapers.index_journal
newspapers.post_and_courier
newspapers.shelby_star
newspapers.tryon_bulletin
public_notices.funeral_home_rss
public_notices.publicnoticesc
reo.treasury_seized
reo.usda_rd
""".split()

def load_scope():
    """Return (in_scope_fn, deny_set) from config, tolerating shape changes."""
    from foreclosure_scraper import config
    deny = set()
    for raw in (getattr(config, 'SCOPE_DENY_COUNTIES', None) or []):
        if isinstance(raw, (tuple, list)) and len(raw) >= 2:
            deny.add((str(raw[0]).lower(), str(raw[1]).upper()))
    fn = None
    for name in ('_in_scope', 'in_scope', 'is_in_scope'):
        if hasattr(config, name):
            fn = getattr(config, name); break
    return fn, deny

def county_of(listing):
    for attr in ('county', 'county_name'):
        v = getattr(listing, attr, None) or (listing.get(attr) if isinstance(listing, dict) else None)
        if v: return str(v)
    return ''

def state_of(listing):
    for attr in ('state', 'state_code'):
        v = getattr(listing, attr, None) or (listing.get(attr) if isinstance(listing, dict) else None)
        if v: return str(v).upper()
    return ''

async def run_module(slug, timeout):
    """Import and invoke a scraper, returning (rows, error)."""
    mod = importlib.import_module(f'foreclosure_scraper.scrapers.{slug}')

    # Their scrapers are BaseScraper subclasses exposing `async fetch()`.
    # safe_run() swallows exceptions, so call fetch() directly — we WANT the error.
    from foreclosure_scraper.base_scraper import BaseScraper
    cls = None
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if (obj is not BaseScraper and issubclass(obj, BaseScraper)
                and obj.__module__ == mod.__name__ and not inspect.isabstract(obj)):
            cls = obj; break
    try:
        if cls:
            res = cls().fetch()
        else:
            fn = next((getattr(mod, n) for n in ('_fetch_rows', 'fetch_rows', 'fetch', 'scrape')
                       if hasattr(mod, n)), None)
            if fn is None:
                return None, 'NOENTRY'
            res = fn()
        rows = await asyncio.wait_for(res, timeout) if inspect.isawaitable(res) else list(res)
        return list(rows or []), None
    except asyncio.TimeoutError:
        return None, f'timeout>{timeout}s'
    except Exception as e:
        return None, f'{type(e).__name__}: {str(e)[:160]}'

def classify(rows, err, in_scope_fn, deny):
    if err == 'NOENTRY':
        return 'NOENTRY', 'no callable fetch path; needs a human read', {}
    if err:
        return 'BROKEN', err, {}
    if not rows:
        return 'EMPTY', 'fetched clean, upstream returned nothing', {}

    counties = Counter()
    kept = 0
    for r in rows:
        c, s = county_of(r), state_of(r)
        counties[f'{c} {s}'.strip()] += 1
        ok = None
        if in_scope_fn:
            try: ok = bool(in_scope_fn(c, s))
            except Exception: ok = None
        if ok is None:
            ok = (c.lower(), s) not in deny and bool(c)
        if ok: kept += 1

    top = dict(counties.most_common(6))
    if kept == 0:
        return 'POLICY', f'{len(rows)} rows, 0 in footprint', top
    return 'PIPELINE', f'{len(rows)} rows, {kept} IN FOOTPRINT but board has none', top

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('slugs', nargs='*')
    ap.add_argument('--timeout', type=float, default=120.0)
    a = ap.parse_args()

    in_scope_fn, deny = load_scope()
    targets = a.slugs or ZERO_ROW
    print(f'triaging {len(targets)} zero-row sources, {a.timeout:.0f}s cap each\n')

    out, buckets = {}, Counter()
    for slug in targets:
        t0 = time.time()
        try:
            rows, err = asyncio.run(run_module(slug, a.timeout))
        except Exception as e:
            rows, err = None, f'{type(e).__name__}: {str(e)[:160]}'
        bucket, detail, top = classify(rows, err, in_scope_fn, deny)
        buckets[bucket] += 1
        out[slug] = {'bucket': bucket, 'detail': detail, 'counties': top,
                     'secs': round(time.time() - t0, 1)}
        print(f'  {bucket:9} {slug:48} {detail}')
        if bucket in ('POLICY', 'PIPELINE') and top:
            print(f'            counties: {top}')

    p = os.path.join(ROOT, 'docs', 'zero_row_triage.json')
    json.dump({'run': str(date.today()), 'results': out}, open(p, 'w'), indent=1)

    print(f'\n=== {dict(buckets)}')
    print('\nWORK QUEUE, highest value first:')
    for b, why in (('PIPELINE', 'data already fetched and in-footprint — fix the write path'),
                   ('BROKEN',   'real repairs, prioritize by expected volume'),
                   ('NOENTRY',  'needs a human read'),
                   ('EMPTY',    'recheck on the source cycle, do not debug'),
                   ('POLICY',   'DO NOT DEBUG — revisit only if the footprint widens')):
        hits = [s for s, v in out.items() if v['bucket'] == b]
        if hits:
            print(f'  [{b}] {why}')
            for s in hits: print(f'      {s}')
    print(f'\nstate: {p}')

if __name__ == '__main__':
    main()
