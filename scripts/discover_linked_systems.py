#!/usr/bin/env python3
"""Crawl the sites we already scrape and list the record systems they link to.

WHY THIS EXISTS
    Every source in this project arrived because someone went looking for it.
    Nothing ever crawled the sites we ALREADY use to see what else they point at
    — and county sites point at a lot. The operator found six systems in a few
    minutes just by searching within cherokeecountysc.gov:

        qpublic.schneidercorp.com   parcel/CAMA search
        southcarolinaprobate.net    statewide probate index
        sclandrecords.com           land records
        cherokeesc.avenuinsights.com  register-of-deeds instrument grid
        mydorway.dor.sc.gov         state tax
        ris.scdot.org               road/situs finder

    None of those were in the scraper set. The gap was method, not effort: the
    source list was being AUDITED (is this URL still up?) rather than the sites
    being EXPLORED (what else is here?). A first pass over 18 county homepages
    then turned up four more register-of-deeds portals nobody had touched —
    sc.ingcountyapps.com/anderson_rod, catawbarod.org, lincolnrod.com and
    greenvillecounty.org/rod/searchrecords.aspx.

WHAT IT DOES
    For each seed site: fetch the homepage, follow same-host navigation one hop,
    collect every link, and report the ones that look like a RECORD SYSTEM —
    matched against the vendor platforms these counties actually use plus the
    record-type words. Then flag which of those already appear somewhere in
    src/, so the output is "here is what you are NOT using".

    It does not scrape any of them. Discovery only; whether a system is usable
    is a separate question of terms, gates and payload.

WHAT IT DELIBERATELY DOES NOT DO
    No login walls, no CAPTCHA solving, no depth beyond one hop (a full crawl of
    a CivicPlus site is thousands of pages and mostly minutes-of-meetings).
    Politeness: one worker per host, short timeouts, no retries.

USAGE
    uv run python scripts/discover_linked_systems.py
    uv run python scripts/discover_linked_systems.py --json
    uv run python scripts/discover_linked_systems.py --seeds extra.txt
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

#: In-footprint county portals, SC Upstate + NC West. These are entry points,
#: not sources — the point is what they LINK to.
SEEDS = [
    "https://cherokeecountysc.gov/", "https://www.spartanburgcounty.gov/",
    "https://www.andersoncountysc.org/", "https://oconeesc.com/",
    "https://www.co.pickens.sc.us/", "https://www.laurenscountysc.gov/",
    "https://greenvillecounty.org/", "https://www.gtcountysc.gov/",
    "https://www.buncombecounty.org/", "https://www.hendersoncountync.gov/",
    "https://www.rutherfordcountync.gov/", "https://www.clevelandcountync.gov/",
    "https://www.lincolncountync.gov/", "https://www.mcdowellnc.gov/",
    "https://www.burkenc.org/", "https://www.polknc.gov/",
    "https://www.transylvaniacounty.org/", "https://www.catawbacountync.gov/",
    "https://www.charlestoncounty.org/", "https://www.horrycountysc.gov/",
    "https://www.colletoncounty.org/", "https://www.brunswickcountync.gov/",
    "https://www.onslowcountync.gov/", "https://www.carteretcountync.gov/",
    "https://www.nhcgov.com/", "https://www.mecklenburgcountync.gov/",
]

#: Platforms these counties actually run their records on, plus record-type
#: words. Vendor names matter more than keywords: "qpublic" or "cotthosting" in
#: a URL is almost always a real records system, where "search" is noise.
VENDOR_RE = re.compile(
    r"qpublic|schneidercorp|avenuinsights|tylertech|tylerhost|devnet|grantstreet|"
    r"govtechservices|cotthosting|acclaim|landmarkweb|idocmarket|fidlar|laredo|"
    r"tapestry|kofile|uslandrecords|titlesearcher|beacon|axisgis|patriotproperties|"
    r"vgsi|munisselfservice|ingcountyapps|permitium|policetocitizen|zuercherportal|"
    r"ncptscloud|sclandrecords|southcarolinaprobate|probate|register.?of.?deeds|"
    r"\brod\b|landrecords|deeds|delinquent|tax.?sale|foreclos|forfeit|upset.?bid|"
    r"sheriff.?sale|estate|surplus",
    re.I,
)

#: Pages that match the words above but are never a lead source.
NOISE_RE = re.compile(
    r"passport|marriage|birth|death.?certificate|notary|veteran|military|"
    r"sweetheart|employment|job|agenda|minutes|calendar|holiday|vaccine|"
    r"recycling|library|park|animal|fee.?schedule|forms?$|faq|contact|"
    # Social share widgets carry the PAGE url as a query param, so a share link
    # on a probate page matches every records keyword. First run surfaced
    # reddit.com/submit?url=...probate_court and plus.google.com/share as
    # "new record systems".
    r"reddit\.com/submit|plus\.google|facebook\.com/share|twitter\.com/intent|"
    r"linkedin\.com/share|pinterest\.com/pin|addthis|sharer\.php|"
    # CMS vendor admin logins reached from a footer, not public records.
    r"cms\d*\.revize\.com|/revize/security|jotfor\.ms|"
    # Staff directories and judge listings are people, not records.
    r"probJudgeList|staff.?director|department.?director",
    re.I,
)


def _fetch(url: str) -> tuple[str, str]:
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, impersonate="chrome", timeout=20)
        return (str(r.url), r.text) if r.status_code == 200 else (url, "")
    except Exception:  # noqa: BLE001
        return url, ""


def _links(base: str, html: str) -> list[str]:
    out = []
    for h in re.findall(r'href="([^"#]+)"', html):
        try:
            u = urljoin(base, h)
        except Exception:  # noqa: BLE001
            continue
        if urlparse(u).scheme.startswith("http"):
            out.append(u)
    return out


def explore(seed: str, hops: int = 1) -> set[str]:
    """Homepage plus one hop through same-host nav. Returns candidate links."""
    host = urlparse(seed).netloc
    base, html = _fetch(seed)
    if not html:
        return set()
    first = _links(base, html)
    cand = {u for u in first if VENDOR_RE.search(u) and not NOISE_RE.search(u)}

    if hops > 0:
        # Follow only same-host pages whose URL already looks records-ish, so a
        # second hop stays cheap and on-topic instead of walking the whole CMS.
        nxt = [u for u in first
               if urlparse(u).netloc == host and VENDOR_RE.search(u)
               and not NOISE_RE.search(u)][:6]
        for u in nxt:
            b2, h2 = _fetch(u)
            if not h2:
                continue
            cand |= {x for x in _links(b2, h2)
                     if VENDOR_RE.search(x) and not NOISE_RE.search(x)}
    return cand


def already_used(url: str) -> bool:
    """Is this host referenced anywhere in src/ already?"""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if not host:
        return False
    r = subprocess.run(["grep", "-rl", host, str(SRC)],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--seeds", help="file with extra seed URLs, one per line")
    args = ap.parse_args()

    seeds = list(SEEDS)
    if args.seeds:
        seeds += [ln.strip() for ln in Path(args.seeds).read_text().splitlines()
                  if ln.strip() and not ln.startswith("#")]

    found: dict[str, set[str]] = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for seed, cands in zip(seeds, ex.map(explore, seeds)):
            if cands:
                found[urlparse(seed).netloc] = cands

    # Dedupe to one row per (host, path-ish system) and split by whether src/
    # already references the host.
    seen_hosts: dict[str, bool] = {}
    rows = []
    for seed_host, urls in found.items():
        for u in sorted(urls):
            h = urlparse(u).netloc.lower().removeprefix("www.")
            if h not in seen_hosts:
                seen_hosts[h] = already_used(u)
            rows.append({"seed": seed_host, "url": u, "host": h,
                         "already_in_src": seen_hosts[h]})

    new = [r for r in rows if not r["already_in_src"]]
    new_hosts = sorted({r["host"] for r in new})

    if args.json:
        print(json.dumps({"rows": rows, "new_hosts": new_hosts}, indent=1))
        return 0

    print(f"Explored {len(seeds)} county portals, "
          f"{len(rows)} record-system links, "
          f"{len(new_hosts)} host(s) NOT referenced anywhere in src/.\n")
    print("=== NOT CURRENTLY USED — worth triaging ===")
    for h in new_hosts:
        ex_urls = [r["url"] for r in new if r["host"] == h][:2]
        print(f"  {h}")
        for u in ex_urls:
            print(f"      {u[:112]}")
    print("\n=== already referenced in src/ (no action) ===")
    for h in sorted({r['host'] for r in rows if r['already_in_src']}):
        print(f"  {h}")
    print("\nDiscovery only — none of these were scraped. Whether a system is")
    print("usable is a separate question of terms, gates and whether it")
    print("actually publishes anything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
