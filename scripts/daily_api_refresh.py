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
from foreclosure_scraper.distress_score import score_board
from foreclosure_scraper.enrichment_title_risk import enrich_title_risk
from foreclosure_scraper.web_artifact import write_artifact, _to_dict, load_board

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
    # load_board() merges the lazy-detail sidecar (listings_detail.json) back into
    # each listing's raw BEFORE we re-split on write. Without it, write_artifact
    # re-emits an empty sidecar and wipes vision/comps/cama (the sidecar-wipe
    # regression fixed elsewhere this session). Mirrors the other refresh scripts.
    _docs = Path(__file__).resolve().parent.parent / "docs"
    prior = load_board(_docs)
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(prior)} prior listings (sidecar merged)", flush=True)

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

    # Drop national records that never resolved to an in-scope county (nationwide
    # Fannie/HUD/etc. REO + bankruptcy that can't be routed to the 18 counties).
    # Mirrors the full pipeline's filter so the daily path doesn't reintroduce
    # county-less noise the main run strips.
    _pre = len(merged)
    merged = [li for li in merged
              if not ((li.source or "").startswith("national.") and not (li.county or "").strip())]
    if _pre != len(merged):
        print(f"[{time.strftime('%H:%M:%S')}] dropped {_pre - len(merged)} county-less national", flush=True)

    # Full footprint re-scope (not just county-less national) — carryover from
    # older runs predates scope tightening, so out-of-footprint counties leak
    # otherwise (this path reintroduced 684 on 2026-06-25). Mirrors merge/regen.
    from foreclosure_scraper.main import _in_scope
    _pre = len(merged)
    merged = [li for li in merged if _in_scope(li)]
    if _pre != len(merged):
        print(f"[{time.strftime('%H:%M:%S')}] scope re-filter dropped {_pre - len(merged)} out-of-footprint", flush=True)

    # Drop dead court records (Canceled/Satisfied/Dismissed NC eCourts liens).
    def _terminal_court(li):
        st = (((li.raw or {}).get("nc_ecourts") or {}).get("civilJudgmentStatus") or "").lower()
        return any(t in st for t in ("cancel", "satisf", "dismiss", "vacat", "withdraw", "expired", "released"))
    _pre = len(merged)
    merged = [li for li in merged if not _terminal_court(li)]
    if _pre != len(merged):
        print(f"[{time.strftime('%H:%M:%S')}] dropped {_pre - len(merged)} terminal-status court records", flush=True)

    # Prune sold/removed Fannie REO (per-property SPA URL 404s once the uuid leaves
    # inventory). The daily refresh already re-scrapes Fannie, so this is cheap.
    # NOTE: no local `import asyncio` here — it shadowed the module-level import,
    # making `asyncio` function-local and crashing main() at its FIRST use
    # (UnboundLocalError at the gather above). And main() is already async, so
    # this must await, not asyncio.run() (which raises inside a running loop).
    try:
        from foreclosure_scraper.enrichment_reo_freshness import prune_stale_reo
        merged, _pstats = await prune_stale_reo(merged)
        if _pstats.get("pruned"):
            print(f"[{time.strftime('%H:%M:%S')}] prune_stale_reo: {_pstats}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[{time.strftime('%H:%M:%S')}] prune_stale_reo skipped: {str(e)[:80]}", flush=True)

    # Safety: never publish a gutted dataset. If the merge lost >35% vs prior,
    # something broke broadly — abort without writing so the good board stands.
    if prior and len(merged) < 0.65 * len(prior):
        print(f"[{time.strftime('%H:%M:%S')}] ABORT: merged {len(merged)} < 65% of prior "
              f"{len(prior)} — refusing to overwrite. Investigate.", flush=True)
        return 2

    # Full re-grade of EVERY row, not just the unscored ones. The old "grade
    # only if missing" left HOT/WARM/COLD + title-trap stale on daily days:
    # equity/derived signals recompute below for the whole board, so calc/grade
    # must too — otherwise kept rows keep yesterday's ARV/grade against today's
    # equity. Cheap (pure compute), so re-grade all.
    for li in merged:
        _regrade(li)

    # Recompute equity (self-cleaning — clears stale billion-dollar payoffs the
    # upper-bound gate now rejects), derived signals (LTV etc.), and data-quality.
    # All in-memory/cheap; keeps the daily board correct without the slow GIS pass.
    try:
        from foreclosure_scraper.enrichment_equity import enrich_equity
        from foreclosure_scraper.enrichment_derived_signals import enrich_derived_signals
        from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
        enrich_equity(merged)
        enrich_derived_signals(merged)
        enrich_data_quality(merged)
    except Exception as e:  # noqa: BLE001
        print(f"[{time.strftime('%H:%M:%S')}] equity/derived/dq skipped: {str(e)[:80]}", flush=True)

    # Full board re-scoring AFTER equity — mirrors main.py's tail. Without this
    # the daily path leaves HOT/WARM/COLD tiers and the title-trap flag stale on
    # carried-over rows (score_board/enrich_title_risk only ever ran on the
    # weekly crawl). title_risk first (HOT gates on it), then score_board.
    try:
        enrich_title_risk(merged)
        _prev = Path(__file__).resolve().parent.parent / "docs" / "listings.json"
        tiers = score_board(merged, previous_path=_prev)
        print(f"[{time.strftime('%H:%M:%S')}] re-scored board: {tiers}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[{time.strftime('%H:%M:%S')}] title_risk/score_board skipped: {str(e)[:80]}", flush=True)

    # Final post-enrich dedupe — mirrors main.py's H1 FIX (main.py ~896). The
    # merge dedupe above ran before this re-grade/equity pass; re-running here,
    # after the whole chain, collapses any same-property twins that survived the
    # early dedupe so duplicate-property rows don't ship.
    _pre_dedupe2 = len(merged)
    merged = dedupe(merged)
    print(f"[{time.strftime('%H:%M:%S')}] post-enrich dedupe: {_pre_dedupe2} -> {len(merged)} "
          f"(collapsed {_pre_dedupe2 - len(merged)})", flush=True)

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
            # .gz twins only (the dashboard fetches those). The uncompressed
            # listings.json/.detail.json are gitignored — over GitHub's 100MB
            # limit, excluded from Pages; load_board rebuilds from the .gz. A
            # gitignored path in git add fails the whole command, so keep it out.
            # listings_slim.json.gz is the mobile payload write_artifact() emits.
            # Appended ONLY IF IT EXISTS: a pathspec matching no file makes
            # `git add` exit 128 and stage NOTHING AT ALL, which would silently
            # stop publishing the dashboard on a checkout where the slim emitter
            # has not run yet.
            pub = ["docs/listings.json.gz", "docs/listings_detail.json.gz",
                   "docs/run_meta.json"]
            # "exists" alone is the wrong gate once it IS tracked: the emitter
            # deletes both slim files if projection fails, and that DELETION has
            # to be staged or phones keep being served the last published slim
            # beside a board that has moved on. The 128-exit only fires when the
            # path is absent AND untracked, so test for both.
            if (Path(root) / "docs" / "listings_slim.json.gz").exists() or subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "docs/listings_slim.json.gz"],
                    cwd=root, capture_output=True).returncode == 0:
                pub.append("docs/listings_slim.json.gz")
            subprocess.run(["git", "add", *pub], cwd=root, check=False)
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
