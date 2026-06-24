#!/usr/bin/env python3
"""Reddit GEO opportunity scraper for HWM clients (e.g. Lifetime Windows & Doors).

Reuses the foreclosure-scraper stealth stack (porsche_scraper.http_client:
curl-cffi TLS impersonation) to read Reddit's per-subreddit *new* RSS feeds —
the one Reddit surface still readable for free without an API key. Reddit's
*.json search/listing endpoints now 403 automated clients (even a real
browser), pullpush.io is a year+ stale with no live vote counts, and the new
web UI loads results via JS that a snapshot misses. RSS new-feeds give fresh,
dated posts; we keyword-filter them for window/door/siding intent and rank by
recency + locality.

No upvote/comment counts (RSS omits them; brand-new posts have ~0 anyway), so
ranking is recency + locality + intent — which is what "answer it while the
thread is fresh" actually needs.

Run:  uv run python reddit_geo_scraper.py --client lifetime
Free, local, no API keys, no Apify / Bright Data.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import html
import json
import os
import re
import sys
import time

import feedparser  # bundled dep of the foreclosure project

from porsche_scraper.http_client import fetch_text_stealth  # noqa: E402

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)

CLIENTS = {
    "lifetime": {
        # Subs where "window"/"door" always means a house window/door.
        "home_subreddits": [
            "HomeImprovement", "homeowners", "HomeMaintenance", "DIY",
            "Renovations", "Construction", "buildingscience", "hvacadvice",
        ],
        # Subs whose entire topic is on-target — every post counts, no
        # title keyword needed. (r/replacementwindows looked ideal but is a
        # dead sub: its "new" feed returns 2018-era posts, so it's dropped.)
        "topic_subreddits": [],
        # Lifetime's Oregon / SW-Washington footprint.
        "local_subreddits": [
            "Portland", "askportland", "oregon", "bendoregon",
            "SalemOregon", "eugene", "Corvallis", "vancouverwa",
        ],
        # Inherently home-improvement phrases — strong relevance on any sub.
        "strong_phrases": [
            "replacement window", "window replacement", "replace window",
            "replacing window", "new windows", "window install",
            "install window", "window quote", "window estimate",
            "window company", "window contractor", "window installer",
            "foggy window", "fogged window", "condensation between",
            "double pane", "triple pane", "double-pane", "triple-pane",
            "casement", "egress", "bay window", "bow window",
            "patio door", "sliding door", "sliding glass", "french door",
            "storm door", "entry door", "exterior door", "front door replace",
            "vinyl window", "fiberglass window", "milgard", "simonton",
            "andersen window", "pella", "marvin window", "cascade window",
            "siding", "james hardie", "hardie", "moving glass wall",
        ],
        # Bare terms accepted only inside home subs (too ambiguous on local subs).
        "bare_terms": [
            "window", "windows", "door", "doors", "patio", "pane",
        ],
        "local_tokens": [
            "portland", "oregon", "bend, or", "bend or", "salem",
            "beaverton", "eugene", "corvallis", "vancouver wa",
            "vancouver, wa", "oregon city", "tigard", "hillsboro",
            "gresham", "tualatin", "lake oswego", "milwaukie",
            "willamette", "pacific northwest", " pnw ",
        ],
        "intent_terms": [
            "recommend", "installer", "install", "quote", "estimate",
            "cost", "price", "replace", "worth it", "company", "contractor",
            " vs ", "best ", "advice", "help", "looking for",
        ],
        # A bare product term only counts as an opportunity when paired
        # with one of these — kills barn doors, shower glass, patio roofs,
        # curtain rods, "should I use A/C", etc.
        "context_terms": [
            "replace", "replacement", "install", "quote", "estimate",
            "cost", "price", "recommend", "contractor", "company",
            "installer", "draft", "drafty", "leak", "leaking", "rot",
            "rotten", "rotted", "foggy", "fog", "condensation", "seal",
            "energy", "efficient", "single pane", "double pane",
            "triple pane", "old window", "new window", "egress", "code",
            "u-factor", "argon", "low-e", "low e",
        ],
    }
}
# Drop the placeholder home sub if present.
CLIENTS["lifetime"]["home_subreddits"] = [
    s for s in CLIENTS["lifetime"]["home_subreddits"] if s != "Windows10"
]

_TAG_RE = re.compile(r"<[^>]+>")


def _norm_url(u: str) -> str:
    return (u or "").split("?")[0].rstrip("/")


def _clean(text: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", text or "")).strip()


async def fetch_feed(subreddit: str, *, limit: int, retries: int = 4) -> list[dict]:
    """Fetch a subreddit's new RSS feed via the stealth transport.

    Reddit rate-limits RSS per IP, so we back off and retry on failure.
    Returns [] if the feed can't be read this run (next run catches it).
    """
    url = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit={limit}"
    for attempt in range(retries):
        try:
            text = await fetch_text_stealth(
                url, timeout=40.0,
                headers={"User-Agent": UA,
                         "Accept": "application/atom+xml,application/xml,text/xml"},
                impersonate="chrome120",
            )
            feed = feedparser.parse(text)
            if feed.entries:
                return list(feed.entries)
            # Empty feed: could be a transient block; retry.
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                print(f"  ! r/{subreddit} feed failed: {exc}", file=sys.stderr)
        await asyncio.sleep(5.0 * (attempt + 1))
    return []


def entry_to_post(entry, subreddit: str) -> dict | None:
    link = _norm_url(getattr(entry, "link", "") or "")
    if "/comments/" not in link:
        return None
    pp = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    created = float(calendar.timegm(pp)) if pp else 0.0
    return {
        "title": _clean(getattr(entry, "title", "")),
        "url": link,
        "subreddit": subreddit,
        "created_utc": created,
        "selftext": _clean(getattr(entry, "summary", ""))[:600],
        "author": _clean(getattr(entry, "author", "")),
    }


def is_relevant(post: dict, cfg: dict) -> bool:
    if post["subreddit"].lower() in {s.lower() for s in cfg.get("topic_subreddits", [])}:
        return True
    # Title-only: the body mentions "window/door" incidentally too often
    # (HVAC units near a window, etc.), so match on the thread's stated topic.
    t = post["title"].lower()
    if any(ph in t for ph in cfg["strong_phrases"]):
        return True
    has_bare = any(re.search(rf"\b{re.escape(b)}\b", t) for b in cfg["bare_terms"])
    if has_bare and any(ctx in t for ctx in cfg["context_terms"]):
        return True
    return False


def score_post(post: dict, cfg: dict) -> tuple[int, str]:
    s, parts = 0, []
    if post["subreddit"].lower() in {x.lower() for x in cfg.get("topic_subreddits", [])}:
        s += 2; parts.append("topicsub:+2")
    age = (time.time() - post["created_utc"]) / 86400 if post["created_utc"] else 9999
    if age <= 2:
        s += 3; parts.append("<=2d:+3")
    elif age <= 7:
        s += 2; parts.append("<=7d:+2")
    elif age <= 30:
        s += 1; parts.append("<=30d:+1")
    title_l = post["title"].lower()
    local = (post["subreddit"].lower() in {s.lower() for s in cfg["local_subreddits"]}
             or any(tok in title_l for tok in cfg["local_tokens"]))
    if local:
        s += 2; parts.append("local:+2")
    if any(ph in title_l for ph in cfg["strong_phrases"]):
        s += 1; parts.append("strong:+1")
    if any(t in title_l for t in cfg["intent_terms"]):
        s += 1; parts.append("intent:+1")
    post["age_days"] = round(age, 1)
    post["is_local"] = local
    return s, ",".join(parts)


def load_seen(path: str) -> set[str]:
    if not path or not os.path.exists(path):
        return set()
    with open(path) as f:
        return {_norm_url(ln.strip()) for ln in f if ln.strip()}


def _prepend_log(path: str, results: list[dict], client: str) -> None:
    """Prepend a dated section of new threads to the rolling doc (newest on top)."""
    stamp = time.strftime("%Y-%m-%d %H:%M")
    lines = [f"## {stamp} — {len(results)} new ({client})", ""]
    for p in results:
        loc = " **[LOCAL]**" if p.get("is_local") else ""
        lines.append(f"- **{p['title']}** — r/{p['subreddit']}, "
                     f"{p['age_days']:.0f}d, score {p['score']}{loc}")
        lines.append(f"  {p['url']}")
    lines.append("\n---\n")
    block = "\n".join(lines)
    header = "# Lifetime Windows & Doors — Reddit GEO Opportunities (rolling)\n\n"
    existing = ""
    if os.path.exists(path):
        existing = open(path).read()
        if existing.startswith(header):
            existing = existing[len(header):]
    with open(path, "w") as f:
        f.write(header + block + "\n" + existing)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="lifetime", choices=list(CLIENTS))
    ap.add_argument("--seen", default=os.path.expanduser("~/Desktop/lifetime_reddit_seen.txt"))
    ap.add_argument("--out", default=os.path.expanduser("~/Desktop/lifetime_reddit_results.json"))
    ap.add_argument("--min-score", type=int, default=2)
    ap.add_argument("--max-age-days", type=int, default=30, help="0 = no cap")
    ap.add_argument("--feed-limit", type=int, default=100)
    ap.add_argument("--delay", type=float, default=7.0, help="seconds between feeds")
    ap.add_argument("--pending", default=os.path.expanduser("~/Desktop/lifetime_geo_pending.json"),
                    help="accumulates new threads between weekly digests")
    ap.add_argument("--log", default=os.path.expanduser("~/Desktop/lifetime_reddit_opportunities.md"),
                    help="continuously-updated human-readable rolling doc")
    ap.add_argument("--no-mark-seen", action="store_true",
                    help="don't append this run's threads to the seen-list (for testing)")
    args = ap.parse_args()

    cfg = CLIENTS[args.client]
    seen = load_seen(args.seen)
    home = set(cfg["home_subreddits"])
    subs = cfg["home_subreddits"] + cfg["local_subreddits"]

    by_url: dict[str, dict] = {}
    failed = 0
    for i, sub in enumerate(subs, 1):
        print(f"[{i}/{len(subs)}] r/{sub}", file=sys.stderr)
        entries = await fetch_feed(sub, limit=args.feed_limit)
        if not entries:
            failed += 1
        kept = 0
        for e in entries:
            p = entry_to_post(e, sub)
            if not p:
                continue
            if not is_relevant(p, cfg):
                continue
            if p["url"] not in by_url:
                by_url[p["url"]] = p
                kept += 1
        print(f"      {len(entries)} entries, {kept} relevant", file=sys.stderr)
        if i < len(subs):
            await asyncio.sleep(args.delay)

    results = []
    for url, p in by_url.items():
        if url in seen:
            continue
        score, why = score_post(p, cfg)
        is_topic = p["subreddit"].lower() in {x.lower() for x in cfg.get("topic_subreddits", [])}
        cap = 180 if is_topic else args.max_age_days  # pure-topic subs get a longer window
        if cap and p["age_days"] > cap:
            continue
        if score < args.min_score:
            continue
        p["score"], p["score_detail"] = score, why
        results.append(p)
    results.sort(key=lambda x: (x["is_local"], x["score"], -x["age_days"]), reverse=True)

    out = {
        "client": args.client,
        "generated_utc": int(time.time()),
        "feeds_read": len(subs) - failed,
        "feeds_failed": failed,
        "new_thread_count": len(results),
        "threads": results,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    # Mark this run's threads as seen so they never resurface.
    if results and not args.no_mark_seen:
        with open(args.seen, "a") as f:
            for p in results:
                f.write(p["url"] + "\n")

    # Accumulate into the weekly "pending" digest (dedup by url).
    if results:
        pend = []
        if os.path.exists(args.pending):
            try:
                pend = json.load(open(args.pending)).get("threads", [])
            except Exception:
                pend = []
        have = {p["url"] for p in pend}
        for p in results:
            if p["url"] not in have:
                pend.append(p); have.add(p["url"])
        with open(args.pending, "w") as f:
            json.dump({"threads": pend, "updated_utc": int(time.time())}, f, indent=2)
        _prepend_log(args.log, results, args.client)

    print(json.dumps(out, indent=2))
    print(f"\n{len(results)} new threads -> {args.out} "
          f"({failed}/{len(subs)} feeds failed)", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
