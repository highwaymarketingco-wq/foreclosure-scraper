"""Daily refresh of the browserless (plain HTTP/JSON) sources.

The weekly crawl runs everything incl. the slow stealth-browser sources. But
the cheap JSON-API sources — Fannie HomePath REO, foreclosure.com, HUD, VA REO,
CourtListener, etc. — churn DAILY: REO sells and leaves inventory, so by the
time you click a day-old listing its detail page 404s ("property not found").

This re-runs ONLY the browserless sources (s.requires_render is False), then
MERGES them into the existing docs/listings.json:
  - listings from refreshed sources are REPLACED with current inventory
    (so sold/removed REO drops out, new REO appears),
  - listings from browser-scraped sources are kept intact (with their
    enrichment: vision, comps, court detail, grade, …),
then re-dedupes, (re)grades the fresh ones, marks new, and republishes.

No stealth browser → fast, and could even run in the cloud. Schedule daily.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers._registry import all_scrapers
from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.valuation import calc as vcalc
from foreclosure_scraper.valuation import grading as vgrade
from foreclosure_scraper.web_artifact import write_artifact, _to_dict

try:
    from foreclosure_scraper.new_listings import mark_new_listings
except Exception:  # pragma: no cover - optional
    mark_new_listings = None


def _hydrate(d: dict) -> Listing | None:
    fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    for ef, enum in (("listing_type", ListingType), ("property_kind", PropertyKind)):
        if isinstance(fields.get(ef), str):
            try:
                fields[ef] = enum(fields[ef])
            except ValueError:
                fields.pop(ef, None)
    try:
        li = Listing.model_validate(fields)
    except Exception:
        return None
    li.raw = d.get("raw") or {}
    return li


def _regrade(li: Listing) -> None:
    try:
        c = vcalc.compute(li)
        g = vgrade.grade(li, c)
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["calc"] = vcalc.to_dict(c)
        li.raw["grade"] = vgrade.to_dict(g)
    except Exception:
        pass


async def main() -> int:
    path = Path("docs/listings.json")
    prior_dicts = json.loads(path.read_text()) if path.exists() else []
    prior = [li for li in (_hydrate(d) for d in prior_dicts) if li]
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(prior)} prior listings", flush=True)

    # Explicit allowlist of confirmed plain-HTTP/JSON sources. The
    # requires_render flag isn't reliably set on every scraper (some browser
    # scrapers default it to False), so we name the browserless ones outright.
    # These are the churning REO/API feeds where daily freshness matters most.
    # Only the churning REO / for-sale-inventory feeds that go 404 when a
    # property sells. NOT courtlistener_* (court-record feeds, not inventory —
    # those accumulate value over time and belong to the weekly crawl).
    DEFAULT_SLUGS = {
        "national.fannie_homepath", "national.foreclosure_dot_com",
        "national.hud_homestore", "national.freddie_homesteps",
        "national.realtor_foreclosures", "national.homeharvest", "national.distressed",
        "reo.vrm_va_reo", "reo.usda_rd", "reo.treasury_seized",
    }
    env_slugs = os.environ.get("DAILY_REFRESH_SLUGS", "").strip()
    allow = set(s.strip() for s in env_slugs.split(",") if s.strip()) or DEFAULT_SLUGS
    scrapers = all_scrapers()
    fresh_scrapers = [s for s in scrapers if s.slug in allow]
    refreshed_slugs = {s.slug for s in fresh_scrapers}
    print(f"[{time.strftime('%H:%M:%S')}] refreshing {len(fresh_scrapers)} browserless sources: "
          + ", ".join(sorted(refreshed_slugs)), flush=True)

    async def run(s):
        try:
            return s.slug, await s.safe_run()
        except Exception as exc:
            print(f"  ! {s.slug} failed: {str(exc)[:120]}", flush=True)
            return s.slug, []

    results = await asyncio.gather(*(run(s) for s in fresh_scrapers))
    fresh: list[Listing] = []
    for slug, listings in results:
        for li in listings or []:
            if not li.source:
                li.source = slug
            fresh.append(li)
    by_src: dict[str, int] = {}
    for li in fresh:
        by_src[li.source] = by_src.get(li.source, 0) + 1
    print(f"[{time.strftime('%H:%M:%S')}] fresh: {len(fresh)} listings — {by_src}", flush=True)

    if not fresh:
        print("no fresh listings scraped — aborting (won't wipe refreshed sources).", flush=True)
        return 1

    # Decide, per refreshed source, whether the fresh pull is HEALTHY enough to
    # replace prior. If a source returned too few (<3 — site down / parse break),
    # treat it as a transient failure and CARRY OVER its prior listings instead
    # of wiping them. Mirrors the main pipeline's carryover guard. Without this,
    # one flaky source silently deletes all its listings.
    HEALTHY_MIN = 3
    healthy = {s for s in refreshed_slugs if by_src.get(s, 0) >= HEALTHY_MIN}
    failed = refreshed_slugs - healthy
    if failed:
        print(f"[{time.strftime('%H:%M:%S')}] ⚠ carryover (fresh<{HEALTHY_MIN}, keeping prior): "
              + ", ".join(f"{s}={by_src.get(s,0)}" for s in sorted(failed)), flush=True)

    # Only use fresh listings from healthy sources (failed ones are empty/partial).
    fresh = [li for li in fresh if li.source in healthy]

    # Match fresh↔prior on the normalized ADDRESS — the ONLY stable identity.
    # Fannie's propertyUuid ROTATES between pulls, so case_number ("fannie-<uuid>")
    # AND source_url both change for the SAME property day to day — which is
    # exactly why day-old Fannie links 404 (stale uuid). dedupe_key is also
    # unstable (changes once a listing gains a parcel via enrichment). The street
    # address is stable, so we match on (source, normalized_addr, state) and, on
    # a match, REFRESH source_url + case_number to the current uuid → kills the
    # 404 — while keeping the enriched prior row.
    from foreclosure_scraper.models import _normalize_addr
    def _sid(li: Listing):
        a = _normalize_addr(li.street_address or "")
        if a:
            return (li.source, "addr", a, (li.state or "").upper())
        if li.source_url and li.source_url.strip():
            return (li.source, "url", li.source_url.strip())
        return (li.source, "key", li.dedupe_key())

    fresh_by_id = {_sid(li): li for li in fresh}

    # Consecutive-miss drop. One pull isn't authoritative (Fannie caps ~400/bbox),
    # so we never drop on a single absence. Each prior REO listing carries
    # raw['refresh_misses']: 0 when present in a fresh pull, +1 when absent; drop
    # only after MISS_LIMIT consecutive daily misses (confidently sold, not
    # pagination noise). Still-listed properties stay as the ENRICHED prior (we
    # only refresh volatile fields from fresh) → no parallel rows, no lost vision.
    MISS_LIMIT = int(os.environ.get("REFRESH_MISS_LIMIT", "4"))
    today = time.strftime("%Y-%m-%d")
    out: list[Listing] = []
    matched: set = set()
    dropped = updated = 0
    for li in prior:
        if li.source not in healthy:
            out.append(li)
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        sid = _sid(li)
        fr = fresh_by_id.get(sid)
        if fr is not None:                       # still in inventory
            matched.add(sid)
            # Refresh the link to the CURRENT uuid — this is the 404 fix.
            if fr.source_url:
                li.source_url = fr.source_url
            if fr.case_number:
                li.case_number = fr.case_number
            if fr.opening_bid:
                li.opening_bid = fr.opening_bid  # refresh volatile price
            if fr.last_seen:
                li.last_seen = fr.last_seen
            li.raw["refresh_misses"] = 0
            li.raw["last_refresh_seen"] = today
            out.append(li)
            updated += 1
        else:                                    # absent this pull
            misses = int(li.raw.get("refresh_misses", 0)) + 1
            if misses >= MISS_LIMIT:
                dropped += 1                     # confidently sold/removed
            else:
                li.raw["refresh_misses"] = misses
                out.append(li)
    # Add only genuinely-new fresh listings (no prior twin).
    added = 0
    for sid, fr in fresh_by_id.items():
        if sid not in matched:
            if not isinstance(fr.raw, dict):
                fr.raw = {}
            fr.raw["last_refresh_seen"] = today
            fr.raw["refresh_misses"] = 0
            out.append(fr)
            added += 1
    print(f"[{time.strftime('%H:%M:%S')}] kept+updated {updated} still-listed (enriched preserved); "
          f"added {added} new; dropped {dropped} (missed ≥{MISS_LIMIT} pulls)", flush=True)

    merged = dedupe(out)
    print(f"[{time.strftime('%H:%M:%S')}] merged+deduped → {len(merged)}", flush=True)

    # Safety: never publish a gutted dataset. If the merge lost >35% vs prior,
    # something broke broadly — abort without writing so the good board stands.
    if prior and len(merged) < 0.65 * len(prior):
        print(f"[{time.strftime('%H:%M:%S')}] ABORT: merged {len(merged)} < 65% of prior "
              f"{len(prior)} — refusing to overwrite. Investigate.", flush=True)
        return 2

    # Grade the fresh/unscored ones (kept ones already carry their grade).
    for li in merged:
        if not (li.raw or {}).get("grade"):
            _regrade(li)

    if mark_new_listings:
        try:
            mark_new_listings(merged)
        except Exception:
            pass

    write_artifact(merged, summary={"refresh": "daily_api", "sources": sorted(refreshed_slugs)})
    print(f"[{time.strftime('%H:%M:%S')}] wrote docs/listings.json ({len(merged)} listings)", flush=True)

    if os.environ.get("REFRESH_PUBLISH", "1") == "1":
        import subprocess
        root = str(Path(__file__).parent.parent)
        try:
            subprocess.run(["git", "add", "docs/listings.json", "docs/run_meta.json"], cwd=root, check=False)
            if subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=root).returncode != 0:
                subprocess.run(["git", "commit", "-q", "-m",
                                f"daily api refresh: {len(merged)} listings ({time.strftime('%Y-%m-%d')})"],
                               cwd=root, check=False)
                subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"], cwd=root, check=False)
                p = subprocess.run(["git", "push", "origin", "main"], cwd=root)
                print("dashboard published ✓" if p.returncode == 0 else "push failed ⚠", flush=True)
        except Exception as exc:
            print(f"publish error: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
