#!/usr/bin/env python3
"""Re-probe the sources recorded as blocked or dormant, and say what changed.

WHY THIS EXISTS
    docs/blocked_sources_forensic.md classifies a source CANT / WONT / ABSENT
    once, and nothing ever re-checks it. Re-probed on 2026-08-11, EIGHT of the
    thirteen "technical wall" entries answered 200 — seven of them with plain
    httpx and no trick whatsoever:

        Cherokee      recorded "403 Cloudflare"    -> 200 with curl_cffi (JA3, not a wall)
        Laurens       recorded "404 CMS migration" -> 200 plain
        Anderson      recorded "403 auth"          -> 200 plain
        foreclosure.com  "GET + curl_cffi + stealth all tried" -> 200 plain
        Oconee, Pickens, irsauctions, echovita     -> 200 plain

    A "403" got written down as a verdict rather than as a fingerprint, and the
    entry stopped being questioned. Some of those walls had been down for months.

    The second thing it catches is the opposite error. Reachable is not the same
    as useful: Cherokee returns 263 KB and carries no delinquent list at all —
    its only documents are a collections-agency notice and expired bidder
    instructions. SC counties publish these seasonally, ahead of an autumn tax
    sale, and the measured cadence for the class is ONE publication day in 180
    (see the cadence section of docs/SOURCE_REGISTER.md). So the useful question
    is not "is it up" but "has a list appeared yet".

WHAT IT REPORTS
    reachability  can we fetch it, and does it need impersonation
    payload       has a LIST-LIKE document appeared (delinquent / tax sale /
                  bidder / forfeited / upset), with its URL

    Exit 1 when a source that had no list now has one — that is the signal worth
    interrupting someone for. Everything else is exit 0, because a dormant
    county being dormant is not news.

USAGE
    uv run python scripts/probe_dormant_sources.py
    uv run python scripts/probe_dormant_sources.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "logs" / "dormant_probe_state.json"

#: (label, url). Kept here rather than imported from the scrapers because this
#: deliberately probes things NO scraper currently drives — the whole point is
#: to notice when a source stops being dead.
TARGETS: list[tuple[str, str]] = [
    ("cherokee_delinquent",    "https://cherokeecountysc.gov/delinquent-tax/"),
    ("spartanburg_taxsale",    "https://www.spartanburgcounty.gov/640/2025-Tax-Sale-Info"),
    ("spartanburg_procedures", "https://www.spartanburgcounty.gov/408/Tax-Procedures"),
    ("laurens_delinquent",     "https://www.laurenscountysc.gov/departments/treasurer/delinquent_taxes.php"),
    ("oconee_delinquent",      "https://oconeesc.com/delinquent-tax"),
    ("pickens_delinquent",     "https://www.co.pickens.sc.us/departments/delinquent_tax/index.php"),
    ("anderson_treasurer",     "https://www.andersoncountysc.org/departments-a-z/treasurer/"),
    ("union_treasurer",        "https://www.countyofunion.com/treasurer"),
    ("sc_public_notices",      "https://www.scpublicnotices.com/"),
    ("irsauctions",            "https://www.irsauctions.gov/"),
]

#: A document worth waking someone for. Deliberately narrow: matching on "pdf"
#: alone would fire on every privacy policy and recycling-centre map on a county
#: site, and a prober that cries wolf gets ignored, which is how these entries
#: went unchecked in the first place.
#: "FLC" is Forfeited Land Commission and is how SC counties actually name these
#: files — the live example is "2026-FLC-LIST---UPDATED-MAY-2026-PDF", which
#: matched none of delinq/tax-sale/bidder/forfeit/upset because the county never
#: spells the word out. Caught by testing the detector against a page that
#: genuinely publishes a list rather than trusting the keyword set.
LIST_RE = re.compile(
    r"delinq|tax.?sale|bidder|forfeit|\bflc\b|upset|sale.?list|[-_]list\b", re.I
)

#: Documents are matched TWO ways, because half these counties serve them without
#: a file extension and an extension-only regex is blind to them.
#:
#: Found by testing the detector against a page known to publish a list:
#: gtcountysc.gov/415/Forfeited-Land-Commission carries
#:     /DocumentCenter/View/3019/2026-FLC-LIST---UPDATED-MAY-2026-PDF
#: a current 2026 forfeited-land list — and the extension regex matched ZERO
#: links on that page, because CivicPlus DocumentCenter URLs end in "-PDF", not
#: ".pdf". A watcher that cannot see the thing it watches for is worse than none;
#: it reports "no list published" forever and everyone believes it.
DOC_RE = re.compile(
    r'href="([^"]+\.(?:pdf|xlsx|xls|csv)|'
    r'[^"]*(?:DocumentCenter/View|/media/|ViewFile|DownloadFile|download\.aspx)[^"]*)"',
    re.I,
)

#: Documents that LOOK list-like by filename but are known not to be. Cherokee's
#: bidder-registration sheet matches "bidder" and contains zero parcels.
NOISE_RE = re.compile(r"privacy|policy|recycling|bidder.?website.?info|application", re.I)


def _fetch(url: str) -> tuple[int | None, str, str]:
    """(status, html, how) — plain httpx first, then a Chrome TLS fingerprint."""
    try:
        import httpx
        r = httpx.get(url, timeout=25, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return r.status_code, r.text, "plain"
        first = r.status_code
    except Exception as exc:  # noqa: BLE001
        first = None
        _ = exc
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, impersonate="chrome", timeout=30)
        if r.status_code == 200:
            return r.status_code, r.text, "impersonate"
        return r.status_code, "", "impersonate-failed"
    except Exception:  # noqa: BLE001
        return first, "", "unreachable"


def probe(label: str, url: str) -> dict:
    status, html, how = _fetch(url)
    docs = [d for d in dict.fromkeys(DOC_RE.findall(html))] if html else []
    listish = [d for d in docs if LIST_RE.search(d) and not NOISE_RE.search(d)]
    return {
        "label": label, "url": url, "status": status, "how": how,
        "bytes": len(html), "docs": len(docs),
        "list_docs": listish[:5], "has_list": bool(listish),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    prior = {}
    if STATE.exists():
        try:
            prior = {r["label"]: r for r in json.loads(STATE.read_text())}
        except Exception:  # noqa: BLE001
            prior = {}

    results = [probe(lbl, u) for lbl, u in TARGETS]
    newly = [r for r in results
             if r["has_list"] and not prior.get(r["label"], {}).get("has_list")]

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(results, indent=1))

    if args.json:
        print(json.dumps({"results": results,
                          "newly_publishing": [r["label"] for r in newly]}, indent=1))
        return 1 if newly else 0

    print(f"{'source':24} {'fetch':>14} {'size':>8} {'docs':>5}  list published?")
    for r in results:
        fetch = (f"{r['status']} {r['how']}" if r["status"] else r["how"])
        size = f"{r['bytes']//1024}k" if r["bytes"] else "-"
        mark = "YES" if r["has_list"] else ("no" if r["bytes"] else "unreachable")
        print(f"  {r['label']:22} {fetch:>14} {size:>8} {r['docs']:>5}  {mark}")
        for d in r["list_docs"]:
            print(f"      {d[:96]}")

    if newly:
        print("\nNEWLY PUBLISHING — a list appeared where there was none:")
        for r in newly:
            print(f"  {r['label']}  {r['url']}")
            for d in r["list_docs"]:
                print(f"      {d[:96]}")
        print("\nRun the SC tax scraper to pick these up.")
        return 1

    print("\nNo source newly published a list. Reachability above is still worth")
    print("reading: a source that flips to 'unreachable' has broken since the last run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
