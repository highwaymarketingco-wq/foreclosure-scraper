#!/usr/bin/env python3
"""Enrich Reddit post IDs with the fields Eric asked for on 2026-07-16:
full post text, direct link, image links, top comments, scan timestamp,
removed/locked status.

Reads Reddit's public .json through the opencli browser bridge (a real Chrome
session) because curl-cffi/stealth gets 403 on those endpoints and the in-app
browser blocks reddit.com by policy.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ENV = {**os.environ, "PATH": os.path.expanduser("~/.npm-global/bin") + ":" + os.environ["PATH"]}
SESSION = "enrich1"
COMMENT_LIMIT = 50


def run(args: list[str], timeout: int = 180) -> str:
    p = subprocess.run(args, env=ENV, capture_output=True, text=True, timeout=timeout)
    return p.stdout


def fetch_json(post_id: str) -> dict | None:
    url = (
        f"https://www.reddit.com/comments/{post_id}.json"
        f"?limit={COMMENT_LIMIT}&sort=top&raw_json=1"
    )
    run(["opencli", "browser", SESSION, "open", url])
    time.sleep(1.5)
    out = run(["opencli", "browser", SESSION, "get", "text", "body"])
    try:
        env = json.loads(out)
    except json.JSONDecodeError:
        return None
    raw = env.get("value")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def image_links(d: dict) -> list[str]:
    imgs: list[str] = []
    if d.get("url_overridden_by_dest", "").startswith("http"):
        u = d["url_overridden_by_dest"]
        if any(u.lower().endswith(e) for e in (".jpg", ".jpeg", ".png", ".gif", ".webp")) or "i.redd.it" in u:
            imgs.append(u)
    for item in (d.get("gallery_data") or {}).get("items", []) or []:
        mid = item.get("media_id")
        meta = (d.get("media_metadata") or {}).get(mid, {})
        src = (meta.get("s") or {}).get("u") or (meta.get("s") or {}).get("gif")
        if src:
            imgs.append(src.replace("&amp;", "&"))
    if not imgs:
        prev = ((d.get("preview") or {}).get("images") or [{}])[0]
        src = (prev.get("source") or {}).get("url")
        if src:
            imgs.append(src.replace("&amp;", "&"))
    # selftext-embedded images
    for token in (d.get("selftext") or "").split():
        if token.startswith("https://preview.redd.it") or token.startswith("https://i.redd.it"):
            imgs.append(token.rstrip(")").rstrip(","))
    seen, out = set(), []
    for u in imgs:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def status(d: dict) -> str:
    bits = []
    if d.get("locked"):
        bits.append("LOCKED (no new replies)")
    if d.get("archived"):
        bits.append("ARCHIVED (no new replies)")
    if d.get("removed_by_category"):
        bits.append(f"REMOVED ({d['removed_by_category']})")
    body = (d.get("selftext") or "").strip()
    if body in ("[removed]", "[deleted]"):
        bits.append("BODY REMOVED")
    if (d.get("author") or "") == "[deleted]":
        bits.append("AUTHOR DELETED")
    return ", ".join(bits) if bits else "Open (not locked, archived, or removed)"


def top_comments(listing: list) -> list[dict]:
    out = []
    if len(listing) < 2:
        return out
    for c in (listing[1].get("data") or {}).get("children", []) or []:
        if c.get("kind") != "t1":
            continue
        d = c.get("data") or {}
        body = (d.get("body") or "").strip()
        if not body or body in ("[removed]", "[deleted]"):
            continue
        out.append({
            "author": d.get("author"),
            "score": d.get("score"),
            "body": body,
            "stickied": bool(d.get("stickied")),
        })
    out.sort(key=lambda c: (not c["stickied"], -(c["score"] or 0)))
    return out[:20]


def enrich(post_id: str) -> dict:
    listing = fetch_json(post_id)
    if not listing:
        return {"id": post_id, "error": "fetch failed"}
    d = (listing[0].get("data") or {}).get("children", [{}])[0].get("data") or {}
    if not d:
        return {"id": post_id, "error": "no post data"}
    created = d.get("created_utc") or 0
    return {
        "id": post_id,
        "title": d.get("title"),
        "permalink": "https://www.reddit.com" + (d.get("permalink") or ""),
        "subreddit": "r/" + (d.get("subreddit") or ""),
        "author": "u/" + (d.get("author") or ""),
        "created_utc": created,
        "created_iso": datetime.fromtimestamp(created, tz=timezone.utc).isoformat(),
        "age_days": round((time.time() - created) / 86400, 1),
        "score": d.get("score"),
        "upvote_ratio": d.get("upvote_ratio"),
        "num_comments": d.get("num_comments"),
        "flair": d.get("link_flair_text"),
        "selftext": (d.get("selftext") or "").strip(),
        "link_out": d.get("url_overridden_by_dest") or "",
        "images": image_links(d),
        "status": status(d),
        "top_comments": top_comments(listing),
    }


def main() -> None:
    ids = sys.argv[2:]
    outpath = sys.argv[1]
    results = []
    for i, pid in enumerate(ids, 1):
        print(f"[{i}/{len(ids)}] {pid}", flush=True)
        try:
            r = enrich(pid)
        except Exception as e:  # keep going, report per-thread
            r = {"id": pid, "error": f"{type(e).__name__}: {e}"}
        if r.get("error"):
            print("   !", r["error"], flush=True)
        else:
            print(f"   {r['status']} | {r['num_comments']} comments | {len(r['images'])} imgs", flush=True)
        results.append(r)
    payload = {
        "scanned_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "threads": results,
    }
    with open(outpath, "w") as fh:
        json.dump(payload, fh, indent=2)
    print("wrote", outpath)


if __name__ == "__main__":
    main()
