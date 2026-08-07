#!/usr/bin/env python
"""Generate docs/SOURCE_REGISTER.md — the single master list of every source.

WHY THIS IS GENERATED AND NOT HAND-WRITTEN
    The repo already had ~39 source docs and not one of them answered "what do
    we have, what is left, and what will we never build" in one place. The
    closest, docs/net_new_source_register.md, is physically truncated (it starts
    mid-table-row and its sections 1.1-1.14 do not exist) and was never
    committed. Hand-written registers rot the moment a scraper lands.

    So the BUILT half of this register is read from the live registry and the
    live board every time it is generated: slug, declared counties, the URLs
    actually present in the module, and the row count that source contributed.
    Re-run it and it is current.

    The NOT-BUILT and WILL-NOT-BUILD halves cannot be derived from code (a
    source that does not exist has no module), so those are curated below and
    cross-linked to docs/blocked_sources_forensic.md, which holds the full
    123-row forensic table with the exact blocker and the manual workaround for
    each.

Usage:  uv run python scripts/gen_source_register.py [--board PATH]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import inspect
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from foreclosure_scraper.scrapers._registry import discover  # noqa: E402

OUT = ROOT / "docs" / "SOURCE_REGISTER.md"
DEFAULT_BOARD = ROOT / "data" / "checkpoint" / "board.json.gz"
FALLBACK_BOARD = ROOT / "docs" / "listings.json.gz"

_URL = re.compile(r"https?://[^\s\"'<>)\]}\\]+")
_NOISE = re.compile(r"(schemas\.|w3\.org|python\.org|github\.com/pypa|example\.com)", re.I)

#: Sources confirmed real, compliant and NOT yet built. Each survived an
#: adversarial refutation pass on 2026-08-06 whose default was "refuted": a
#: claim only lands here if a verifier failed to kill it on all of already
#: built / ToS-blocked / not-a-signal / duplicate / dead.
NOT_BUILT = [
    ("Greenville Journal MIE adverts",
     "https://mie.greenvillejournal.com/wp-sitemap-posts-advert-1.xml",
     "Greenville SC", "foreclosure + JUDGMENT DEBT",
     "~722 notices 2016-2026, ~170/yr",
     "The only free source found that carries total judgment debt keyed to a TMS. "
     "Only 27 of 47,125 board rows currently have a judgment amount. "
     "BLOCKED BY POLICY, NOT TECH: Greenville is in SCOPE_DENY_COUNTIES, so it "
     "ships zero leads until the operator widens the footprint."),
    ("Senior / disabled exemption rolls beyond Buncombe",
     "county ArcGIS parcel layers carrying ELD/DIS/BLD/VET exemption codes",
     "all footprint counties except Buncombe NC", "elderly_disabled",
     "Buncombe alone yields 3,548",
     "The elderly_disabled lane is 3,548 rows and 100% ONE county. The generic "
     "reader already exists in enrichment_gis_attrs.py and already runs against "
     "17 counties returning zero, so this is pointing it at layers that carry "
     "the field, not 15 new scrapers. Caveat: 2,864 of the Buncombe 3,548 are "
     "cold single-signal, so it multiplies weak volume unless stacked."),
    ("RealtyBid", "https://www.realtybid.com", "NC + SC statewide", "reo / auction",
     "unstated",
     "Whole REO/auction lane is thin (311 reo + 69 auction rows). Two "
     "conflicting build profiles in the docs: one says clean ColdFusion "
     "pagination, three later probes say SPA with unmapped XHR. Effort M."),
    ("Williams & Williams auctions", "https://www.williamsauction.com",
     "NC + SC", "auction", "unstated", "Same thin REO/auction lane."),
    ("Bank of America REO public JSON", "https://bankofamerica.reo.com",
     "SC confirmed", "reo (bank-direct)", "low volume",
     "Bank-direct REO, no equivalent source built."),
    ("Regional bank / CU REO: First Bank, Founders FCU, United Community Bank",
     "localfirstbank.com / foundersfcu.com / ucbi.com",
     "NC + Upstate SC", "reo (owner-lead)", "Founders ~9 properties",
     "Small but these are owner-direct leads. UCBI currently empty."),
    ("Burke parcel-history snapshots",
     "https://gis.burkenc.org/arcgis/rest/services/Hosted/Burke_Parcel_History_v3/FeatureServer",
     "Burke NC", "ownership-change / structure-loss diffing",
     "11 annual layers over a 59,433-row CAMA base",
     "VERIFIED LIVE 2026-08-06: service responds, layers 0-10 are '2025 Parcels' "
     "through '2015 Parcels'. Build as ENRICHMENT, not a lead scraper. Burke has "
     "260 leads and its NCPTS delinquent tenant now returns zero blobs. "
     "NOTE the host is gis.burkenc.org, NOT the services3.arcgis.com URL the "
     "backlog recorded."),
    ("Cherokee SC wp-json media search",
     "https://www.cherokeecountysc.gov/wp-json/wp/v2/media?search=tax%20sale",
     "Cherokee SC", "tax_sale", "529-parcel 2024 ledger",
     "Cherokee's tax cell is 1 lead. THIN: the only known ledger is the Nov-2024 "
     "sale, already past SC's 12-month redemption, so live yield may be 0."),
    ("Transylvania CAD calls for service",
     "ArcGIS CAD_Calls_For_Service_Closed_view (exact URL NOT yet resolved)",
     "Transylvania NC", "distress proxy", "305,856 geocoded calls",
     "WEAK SIGNAL and the URL in the backlog is wrong: probing it on 2026-08-06 "
     "returned ArcGIS error 400 'Invalid URL'. Emergency-call volume is a proxy, "
     "not a distress event, and 305k rows would swamp the board. Build only as a "
     "scoring input, if at all."),
]

#: The blocked corpus lives in a dedicated forensic doc. Summarised here so this
#: register is a real index rather than a pointer to a pointer.
BLOCKED_DOC = "docs/blocked_sources_forensic.md"
BLOCKED_SUMMARY = [
    ("WONT", "Compliance choice. A bypass exists and would work (CAPTCHA solver, "
             "login, paid API, subscriber wall) but riding it to sustain "
             "automation is off-limits. Fingerprinting stealth that runs the "
             "page's own JS is permitted; defeating a CAPTCHA, login, WAF "
             "bot-check or ToS scraper-prohibition is not.",
     ["SC PublicIndex broad sweep (ToS prohibits automated/repetitive querying; "
      "Rule 610 is per-held-case)",
      "NC eCourts power-of-sale lane (real browser works; won't ride a "
      "human-solved CAPTCHA)",
      "Sites whose robots.txt names ClaudeBot / anthropic-ai / GPTBot: "
      "SeeClickFix (511 code cases), Transylvania Times TNCMS (2,301 notices)",
      "Kofile / Oconee ROD, Anderson ACPASS, Rutherford Sturgis+Avalon "
      "(all robots Disallow: /)",
      "landwatch / land.com (Akamai; its robots.txt itself 403s)"]),
    ("CANT", "Technical. 403 / dead / SPA with bot-protected backend / "
             "challenge-response, no free path found.",
     ["NC eCourts Smart Search estates + divorce (AWS-WAF escalating image-grid "
      "CAPTCHA; the vision solver clears 2 puzzles and the WAF issues more)",
      "Cherokee SC delinquent tax (Cloudflare 403)",
      "Spartanburg / Laurens delinquent-tax URLs (404, CivicEngage migration)",
      "Union SC delinquent tax (DNS failure)",
      "SCDOT SC_Parcels (now token-walled, returns silent 200 + error)",
      "Transylvania TaxBillSearch (endpoint answers 200 with a ZERO-length body "
      "to every model shape, including bounded single-surname searches)",
      "PropWire (DataDome), mewborn_deselms (Cloudflare 403)"]),
    ("ABSENT", "The data is legally or structurally not published. Nobody, free "
               "or paid, extracts what does not exist.",
     ["SC deed sale price on exempt deeds (SC 12-24-70 states no value)",
      "NC power-of-sale debt $ (notices legally state only terms/deposit/upset "
      "bid; the SP file dollar lives at the Clerk's office, not online)",
      "SC magistrate eviction rosters (portal exposes only Circuit roster types; "
      "magistrate courts are county-operated with no free bulk feed)",
      "Live mortgage payoff balance (servicer PII)",
      "SC Family Court divorce (separate access-restricted system, not on the "
      "public portal at all)"]),
    ("DEAD", "Decommissioned. Do not re-chase.",
     ["homesales.gov (gone), US Marshals (403), IRS auctions (403), "
      "GSA /api/properties (302 to login), SBA REO (no portal exists)",
      "Gaston 'delinquent taxes' document (it is a library storytime flyer)",
      "Burke NCPTS delinquent tenant (valid tenant, now returns ZERO blobs)",
      "Aggregator dropdown probate for Cherokee/Oconee/Georgetown/Colleton "
      "(0 records; a dropdown is not data)"]),
]

#: Checked and rejected as NOT a distress signal, so they are not backlog.
NOT_A_SIGNAL = [
    ("Burke County BurkeNC_2026_Billing.zip",
     "https://www.burkenc.org/DocumentCenter/View/5147/BurkeNC_2026_BillingZIP",
     "A print-image feed for the bill-printing vendor holding EVERY 2026 tax "
     "bill (56,536 REI + 9,095 IND + 3,330 BUS sampled), all tax year 2026, "
     "billed 07/01/2026 with a delinquency date of 01/06/2027 that has not "
     "arrived. No paid/unpaid flag, no prior-year balance. An apparent 'PAID' "
     "match is the phrase 'if paid' in the discount line. Being sent a tax bill "
     "is not distress. STILL USEFUL AS ENRICHMENT: owner name, owner mailing "
     "address, situs, parcel, assessed value and acreage for every Burke parcel."),
    ("Mitchell News-Journal legals",
     "https://www.mitchellnews.com/classified/legals",
     "Redundant. Mitchell NC probate is already carried by nc_notices_counties, "
     "ncpublicnotices and column_legal_notices, and the page held one notice."),
    ("Spartanburg tarp requests (2,096 rows)", "(ArcGIS)",
     "Deliberately not built. Disaster victims who requested aid. A business "
     "call, not a technical one."),
]


def module_urls(cls) -> list[str]:
    try:
        text = inspect.getsource(sys.modules[cls.__module__])
    except Exception:  # noqa: BLE001
        return []
    seen, out = set(), []
    for u in _URL.findall(text):
        u = u.rstrip(".,;")
        if _NOISE.search(u) or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def load_board(path: Path):
    for p in (path, FALLBACK_BOARD):
        if p and p.exists():
            with gzip.open(p, "rt") as fh:
                return json.load(fh), p
    return [], None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    args = ap.parse_args()

    rows, board_path = load_board(args.board)
    counts = collections.Counter(r.get("source") for r in rows)
    by_src_county = collections.defaultdict(collections.Counter)
    for r in rows:
        if r.get("county"):
            by_src_county[r.get("source")][f"{r['county']} {r.get('state','')}".strip()] += 1

    classes = sorted(discover(), key=lambda c: c.slug)
    live = [c for c in classes if counts.get(c.slug)]
    zero = [c for c in classes if not counts.get(c.slug)]

    L = []
    w = L.append
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    w("# MASTER SOURCE REGISTER")
    w("")
    w(f"Generated {now} by `scripts/gen_source_register.py`. **Re-run it instead of "
      "editing this file** — the built half is read from the live registry and the "
      "live board, so hand edits are overwritten and go stale.")
    w("")
    w(f"- Scrapers in the registry: **{len(classes)}**")
    w(f"- Producing rows on the board: **{len(live)}**")
    w(f"- Registered but contributing ZERO rows: **{len(zero)}**")
    w(f"- Confirmed real and not yet built: **{len(NOT_BUILT)}**")
    w(f"- Board read: `{board_path.relative_to(ROOT) if board_path else 'NONE FOUND'}`"
      f" ({len(rows):,} rows)")
    w("")
    w("Sections: [1 Built and producing](#1-built-and-producing) · "
      "[2 Built but zero rows](#2-built-but-producing-zero-rows) · "
      "[3 Not built yet](#3-not-built-yet) · "
      "[4 Will not / cannot build](#4-will-not-build-cannot-build-not-published) · "
      "[5 Checked and rejected](#5-checked-and-rejected-not-a-distress-signal)")
    w("")
    w("---")
    w("")
    w("## 1. Built and producing")
    w("")
    w("Live row counts are what the source actually contributed to the board read "
      "above, not a capacity estimate.")
    w("")
    w("| Slug | Rows | Top counties | URLs in the module |")
    w("|---|---:|---|---|")
    for c in sorted(live, key=lambda x: -counts[x.slug]):
        urls = module_urls(c)
        shown = "<br>".join(f"`{u}`" for u in urls[:3]) or "_(no literal URL in module)_"
        if len(urls) > 3:
            shown += f"<br>_+{len(urls) - 3} more_"
        top = ", ".join(f"{k} ({v})" for k, v in by_src_county[c.slug].most_common(3)) or "-"
        w(f"| `{c.slug}` | {counts[c.slug]:,} | {top} | {shown} |")
    w("")
    w("## 2. Built but producing zero rows")
    w("")
    w("Registered and importable, contributing nothing to the board read above. "
      "A zero here is NOT automatically a bug: it can mean the upstream is "
      "genuinely empty right now, the source is seasonal, it is gated off, it is "
      "blocked (see section 4), or it simply was not in the last run's source list.")
    w("")
    w("| Slug | URLs in the module |")
    w("|---|---|")
    for c in zero:
        urls = module_urls(c)
        shown = "<br>".join(f"`{u}`" for u in urls[:2]) or "_(no literal URL in module)_"
        if len(urls) > 2:
            shown += f"<br>_+{len(urls) - 2} more_"
        w(f"| `{c.slug}` | {shown} |")
    w("")
    w("## 3. Not built yet")
    w("")
    w("Each of these survived an adversarial refutation pass whose DEFAULT was "
      "\"refuted\". A candidate only appears here if a verifier failed to kill it "
      "on every one of: already built, ToS/robots blocked, not a distress signal, "
      "duplicate of an existing source, upstream dead. 14 other doc-claimed "
      "candidates were killed by that pass and are deliberately absent.")
    w("")
    for name, url, counties, signal, est, why in NOT_BUILT:
        w(f"### {name}")
        w("")
        w(f"- **URL**: `{url}`")
        w(f"- **Counties**: {counties}")
        w(f"- **Signal**: {signal}")
        w(f"- **Estimated volume**: {est}")
        w(f"- **Why / caveats**: {why}")
        w("")
    w("## 4. Will not build, cannot build, not published")
    w("")
    w(f"Summary only. The full forensic table lives in **`{BLOCKED_DOC}`** "
      "(123 rows), with columns: Source | Category | Bypass that would work | "
      "Exact error/blocker | Why I didn't | Your manual step. That doc is the "
      "authority; this is the index.")
    w("")
    for cat, meaning, items in BLOCKED_SUMMARY:
        w(f"### {cat}")
        w("")
        w(meaning)
        w("")
        for it in items:
            w(f"- {it}")
        w("")
    w("## 5. Checked and rejected (not a distress signal)")
    w("")
    w("Investigated, found real and reachable, and deliberately NOT turned into "
      "leads. Recorded so they are not re-chased.")
    w("")
    for name, url, why in NOT_A_SIGNAL:
        w(f"- **{name}** (`{url}`) — {why}")
    w("")
    w("---")
    w("")
    w("### Related docs")
    w("")
    w(f"- `{BLOCKED_DOC}` — the full 123-row blocked/dead/manual forensic table.")
    w("- `docs/gap_ledger.md` — per-signal gap ledger, the do-not-re-chase list, "
      "and the discards with evidence.")
    w("- `docs/manual_playbook_and_limits.md` — what stays manual and the exact "
      "operator steps for each manual lane.")
    w("- `docs/net_new_source_register.md` — deep per-county URL register. "
      "**WARNING: physically truncated** — it begins mid-table-row and its "
      "sections 1.1 through 1.14 (all 11 NC counties) do not exist anywhere.")
    w("")

    OUT.write_text("\n".join(L) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(L)} lines")
    print(f"  built+producing {len(live)} | zero-row {len(zero)} | not-built {len(NOT_BUILT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
