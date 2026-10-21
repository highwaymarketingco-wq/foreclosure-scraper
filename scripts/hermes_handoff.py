#!/usr/bin/env python3
"""Split gap_matrix.py's "walled" bucket into the four piles it actually contains, instead of
handing Hermes one undifferentiated list. Read before building anything against this output --
only pile 1 is a Hermes hand-off; pile 2 is scraper engineering work for US (this project, not
Hermes); piles 3 and 4 aren't scrape targets at all.

  1. HERMES LANE -- CAPTCHA or a required login account. Only these two actually need Hermes
     (an interactive solve, or credentials this project should not hold/enter itself).
  2. BOT-WALL, BUILD IN-HOUSE -- a Cloudflare/WAF challenge on a GET-only page, no login and no
     CAPTCHA puzzle involved. This project already has stealth-browser/WAF-bypass code (see
     feedback_foreclosure_keep_bypass_code.md -- it's kept precisely for cases like this); the
     gap here is wiring/tuning that code against this specific county's page, which is ordinary
     scraper build work for this session, not a Hermes hand-off.
  3. HUMAN JUDGMENT CALL, NOT A SCRAPE TARGET -- either a declared policy wall already set by a
     person for a reason that bypassing any TECHNICAL wall would not change (see
     divorce_sc_wall.py's privacy rationale -- publishing a divorce party's name without consent
     stays a human decision no matter how easy the site is to automate), or the wall is a ToS/
     terms-forbid-automation claim on COURT/legal records specifically, which this project treats
     more carefully than an ordinary commercial ToS (c.f. feedback_tos_not_a_wall_lawyer_ok.md --
     that ruling was for ordinary commercial sites, not explicitly re-extended to court-record
     indexes). Also covers "paywall"/"the list is sold" -- a real purchase, not a CAPTCHA.
  4. STALE SCOPE, NEEDS PERIODIC RECHECK, NOT A WALL AT ALL -- a probe result from a past date
     that may no longer hold (a county's lane showing empty because a ONE-TIME check found
     nothing, not because anything blocks it). This project found one of these live tonight: the
     SC estate-notice lane's "28 of 46 counties probed once 2026-10-02, found empty" scope -- a
     fresh re-check found Aiken has a real notice right now. These need a scheduled re-probe, not
     a CAPTCHA solver.

Usage: python scripts/hermes_handoff.py [--gap-list PATH] [--out PATH]
Reads the most recent gap_list_*.csv in docs/gap_matrix/ by default.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Reason-text substrings -> pile. Checked in order; first match wins. Extend this, don't
# hand-maintain the markdown -- regenerate it from a fresh gap_list instead.
_HERMES_LANE = (
    "CAPTCHA",
    "login",
)
_BOT_WALL_INHOUSE = (
    "bot check (Cloudflare/WAF)",
    "Cloudflare check on the county property card",
)
_HUMAN_JUDGMENT = (
    "verifier is a declared wall",
    "terms forbid automation",
    "terms forbid automated querying",
    "is sold",
    "paywall",
    "only on the deed image",
)
_STALE_SCOPE = (
    "probed once",
)


def _pile(reason: str) -> str:
    for pat in _STALE_SCOPE:
        if pat in reason:
            return "stale_scope"
    for pat in _HERMES_LANE:
        if pat in reason:
            return "hermes_lane"
    for pat in _BOT_WALL_INHOUSE:
        if pat in reason:
            return "bot_wall_inhouse"
    for pat in _HUMAN_JUDGMENT:
        if pat in reason:
            return "human_judgment"
    return "unclassified"


def _latest_gap_list(docs_gap_matrix: Path) -> Path:
    cands = sorted(docs_gap_matrix.glob("gap_list_*.csv"))
    if not cands:
        raise SystemExit(f"no gap_list_*.csv found in {docs_gap_matrix}")
    return cands[-1]


def build(gap_list: Path) -> dict:
    piles: dict[str, list[dict]] = defaultdict(list)
    with gap_list.open(newline="") as f:
        for row in csv.DictReader(f):
            cls = row.get("gap_class", "")
            if not cls.startswith("walled"):
                continue
            reason = cls[len("walled ("):-1] if cls.startswith("walled (") else cls
            pile = _pile(reason)
            piles[pile].append({
                "state": row["state"], "county": row["county"], "column": row["column"],
                "est_rows_affected": int(row["est_rows_affected"] or 0),
                "reason": reason, "source": row.get("source", ""),
            })
    for p in piles.values():
        p.sort(key=lambda r: -r["est_rows_affected"])
    return piles


def render_markdown(piles: dict, gap_list: Path) -> str:
    lines = [
        "# Hermes hand-off -- the walled bucket, triaged",
        "",
        f"Generated from `{gap_list.name}`. Regenerate with "
        "`python scripts/hermes_handoff.py` any time the gap list changes -- this file is a "
        "derived view, not hand-maintained.",
        "",
        "Only **Hermes lane** (CAPTCHA or a required login) actually goes to Hermes. "
        "**Bot-wall, build in-house** is ordinary scraper work for this project (existing "
        "WAF-bypass/stealth-browser code, applied per-site) -- not a Hermes hand-off. The "
        "last two piles need a human policy call or a scheduled recheck, not a scraper at "
        "all -- see this script's own module docstring for why.",
        "",
    ]
    order = [("hermes_lane", "## 1. Hermes lane -- CAPTCHA or required login"),
             ("bot_wall_inhouse", "## 2. Bot-wall, build in-house -- Cloudflare/WAF, not Hermes"),
             ("human_judgment", "## 3. Human judgment call -- NOT a scrape target"),
             ("stale_scope", "## 4. Stale scope -- needs a periodic recheck, not a wall"),
             ("unclassified", "## Unclassified -- new reason text this script doesn't recognize yet")]
    for key, header in order:
        rows = piles.get(key, [])
        if not rows:
            continue
        total = sum(r["est_rows_affected"] for r in rows)
        lines.append(header)
        lines.append(f"\n{len(rows):,} cells, {total:,} est_rows_affected combined.\n")
        lines.append("| state | county | column | est_rows | reason | source |")
        lines.append("|---|---|---|---|---|---|")
        for r in rows[:200]:
            lines.append(f"| {r['state']} | {r['county']} | {r['column']} | "
                         f"{r['est_rows_affected']:,} | {r['reason'][:100]} | "
                         f"{r['source'][:60]} |")
        if len(rows) > 200:
            lines.append(f"\n...and {len(rows) - 200:,} more rows in this pile (full set in "
                         f"the source gap_list CSV, filtered to this reason pattern).")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap-list", default="")
    ap.add_argument("--out", default=str(REPO / "docs" / "gap_matrix" / "hermes_handoff.md"))
    args = ap.parse_args(argv)

    gap_matrix_dir = REPO / "docs" / "gap_matrix"
    gap_list = Path(args.gap_list) if args.gap_list else _latest_gap_list(gap_matrix_dir)
    piles = build(gap_list)
    out_path = Path(args.out)
    out_path.write_text(render_markdown(piles, gap_list))
    print(f"wrote {out_path}")
    for key in ("hermes_lane", "bot_wall_inhouse", "human_judgment", "stale_scope", "unclassified"):
        rows = piles.get(key, [])
        print(f"  {key}: {len(rows):,} cells, "
              f"{sum(r['est_rows_affected'] for r in rows):,} est_rows_affected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
