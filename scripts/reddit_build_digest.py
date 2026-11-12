#!/usr/bin/env python3
"""Render the Lifetime Reddit GEO digest in the format Eric asked for on
2026-07-16: full post text, direct un-wrapped Reddit links, image links, top
existing comments, exact scan timestamp, and removed/locked status.

HTML body (not plaintext) so Gmail leaves the Reddit URLs alone instead of
rewriting them into google.com/url?q= tracking wrappers.
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone

MAX_COMMENTS = 3
COMMENT_CHARS = 420


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def fmt_posted(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%b %-d, %Y at %H:%M UTC")


def status_html(status: str) -> str:
    ok = status.startswith("Open")
    color = "#1a7f37" if ok else "#b3261e"
    weight = "normal" if ok else "bold"
    return f'<span style="color:{color};font-weight:{weight}">{esc(status)}</span>'


def render_thread(n: int, t: dict, note: dict) -> str:
    p: list[str] = []
    p.append('<div style="margin:0 0 34px 0;padding:0 0 26px 0;border-bottom:1px solid #ddd">')
    p.append(
        f'<div style="font-size:17px;font-weight:bold;margin-bottom:6px">'
        f'{n}. <a href="{esc(t["permalink"])}" style="color:#0b57d0">{esc(t["title"])}</a></div>'
    )

    meta = (
        f'{esc(t["subreddit"])} &middot; posted {fmt_posted(t["created_iso"])} '
        f'({t["age_days"]} days ago) &middot; {esc(t["author"])} &middot; '
        f'{t["score"]} points ({int((t.get("upvote_ratio") or 0) * 100)}% upvoted) &middot; '
        f'{t["num_comments"]} comments'
    )
    if t.get("flair"):
        meta += f' &middot; flair: {esc(t["flair"])}'
    p.append(f'<div style="font-size:13px;color:#555;margin-bottom:4px">{meta}</div>')
    p.append(
        f'<div style="font-size:13px;margin-bottom:10px">Status: {status_html(t["status"])}</div>'
    )

    p.append(
        f'<div style="font-size:13px;margin-bottom:10px">Direct link: '
        f'<a href="{esc(t["permalink"])}" style="color:#0b57d0">{esc(t["permalink"])}</a></div>'
    )

    if t.get("images"):
        p.append('<div style="font-size:13px;margin-bottom:10px">Images:<br>')
        for u in t["images"]:
            p.append(f'&nbsp;&nbsp;<a href="{esc(u)}" style="color:#0b57d0">{esc(u[:110])}</a><br>')
        p.append("</div>")

    if t.get("link_out") and t["link_out"] not in t.get("images", []):
        p.append(
            f'<div style="font-size:13px;margin-bottom:10px">Links out to: '
            f'<a href="{esc(t["link_out"])}" style="color:#0b57d0">{esc(t["link_out"][:110])}</a></div>'
        )

    body = t.get("selftext") or ""
    p.append('<div style="font-size:13px;font-weight:bold;margin:12px 0 4px">Full post text</div>')
    if body.strip():
        safe = esc(body).replace("\n", "<br>")
        p.append(
            '<div style="border-left:3px solid #ccc;padding:8px 12px;margin-bottom:12px;'
            f'font-size:14px;white-space:normal">{safe}</div>'
        )
    else:
        p.append(
            '<div style="border-left:3px solid #ccc;padding:8px 12px;margin-bottom:12px;'
            'font-size:14px;color:#666">No body text. This is an image or link post, so the '
            'title plus the linked image is the whole question.</div>'
        )

    coms = t.get("top_comments") or []
    p.append(
        '<div style="font-size:13px;font-weight:bold;margin:12px 0 4px">'
        f'Top existing comments (showing {len(coms)}, thread has {t["num_comments"]})</div>'
    )
    if coms:
        for c in coms[:MAX_COMMENTS]:
            txt = c["body"]
            if len(txt) > COMMENT_CHARS:
                txt = txt[:COMMENT_CHARS].rstrip() + " [...]"
            tag = " (stickied)" if c.get("stickied") else ""
            p.append(
                '<div style="margin:0 0 8px 0;font-size:13px">'
                f'<span style="color:#555">{c["score"]} pts &middot; u/{esc(c["author"] or "")}{tag}</span><br>'
                f'{esc(txt).replace(chr(10), "<br>")}</div>'
            )
    elif t["num_comments"]:
        p.append(
            '<div style="font-size:13px;color:#555;margin-bottom:8px">'
            f"No readable comments. The {t['num_comments']} on the counter " + ("is" if t["num_comments"] == 1 else "are") + " deleted, removed, "
            'or automod boilerplate, so the question is effectively unanswered.</div>'
        )
    else:
        p.append(
            '<div style="font-size:13px;color:#1a7f37;margin-bottom:8px">'
            'No comments at all. First substantive answer owns the thread.</div>'
        )

    p.append(
        '<div style="font-size:13px;margin-top:12px"><b>Why it matters:</b> '
        f'{esc(note["why"])}</div>'
    )
    p.append(
        '<div style="font-size:13px;margin-top:6px"><b>Suggested response angle:</b> '
        f'{esc(note["angle"])}</div>'
    )
    p.append("</div>")
    return "".join(p)


REMINDER = (
    "Reminder: every reply must add genuine expert value and disclose that you work in the "
    "window/door trade &mdash; no salesy pitches. r/HomeImprovement, r/DIY, and r/homeowners "
    "actively remove contractor self-promotion, so the play is a genuinely helpful, "
    "clearly-identified-pro answer. The AI-citation value comes from the helpful answer existing "
    "in the thread, not from a sales pitch."
)


def build(data: dict, order: list[str], notes: dict, intro_html: str) -> str:
    by_id = {t["id"]: t for t in data["threads"] if not t.get("error")}
    out = ['<div style="font-family:Arial,Helvetica,sans-serif;color:#111;max-width:760px">']
    out.append(intro_html)
    out.append(
        f'<div style="font-size:13px;color:#555;margin:0 0 22px 0">'
        f'Reddit re-scanned for this email: <b>{esc(data["scanned_utc"])}</b>. '
        f'Scores, comment counts, and locked/removed status are as of that moment.</div>'
    )
    for i, pid in enumerate(order, 1):
        if pid in by_id:
            out.append(render_thread(i, by_id[pid], notes[pid]))
    out.append(f'<div style="font-size:13px;color:#333;margin-top:20px">{REMINDER}</div>')
    out.append("</div>")
    return "".join(out)


if __name__ == "__main__":
    src, dest, which = sys.argv[1], sys.argv[2], sys.argv[3]
    data = json.load(open(src))
    mod = __import__(f"notes_{which}")
    html_out = build(data, mod.ORDER, mod.NOTES, mod.INTRO)
    open(dest, "w").write(html_out)
    print("wrote", dest, len(html_out), "chars")
