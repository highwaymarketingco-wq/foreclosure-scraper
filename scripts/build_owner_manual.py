#!/usr/bin/env python
"""Regenerate the owner's manual of walled sources from structured data.

    uv run python scripts/build_owner_manual.py            # rebuild the .md, the Desktop HTML and PDF
    uv run python scripts/build_owner_manual.py --check    # exit 1 and say what changed if the manual is stale
    uv run python scripts/build_owner_manual.py --no-pdf --offline

Writes docs/OWNER_MANUAL_LANES.md (public), ~/Desktop/Owner_Manual_Lanes_and_Walls.html and .pdf
(private copies, same content) and docs/owner_manual_inputs.json (what this build read, so --check
can tell when an input moved).

Nothing is typed twice. The hand-maintained text (the how-to cards, decisions, prices, appendix rows)
lives in docs/walls_register.json. Everything that can be read from the repo is computed:

* county access per register of deeds, estate search and tax site: docs/county_records/
  county_records_matrix.json, overridden by the 'Person needed' tables of
  docs/county_records/{nc,sc}_rod_platform_clusters.md (live checks) and by the deed adapters
  registered in src/foreclosure_scraper/enrichment_generic_rod.py (read with ast, never imported);
* the click-through rule: a plain 'I agree', disclaimer, disclosure popup or a guest button that
  asks for no credentials is allowed and never counted as a wall (classify_text / classify_access);
* every walled record in docs/new_sources_*.json, listed with the card that covers it;
* DORMANT and blocked scrapers from the live run_meta.json source_status (docs/run_meta.json when
  offline);
* thin county-signal cells from the newest docs/gap_matrix/county_signal_coverage_<date>.csv.

Read-only apart from the three outputs and the inputs ledger. One HTTP GET (the dashboard's
run_meta.json) unless --offline.
"""
from __future__ import annotations

import argparse
import ast
import csv
import glob
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUN_META_URL = "https://highwaymarketingco-wq.github.io/foreclosure-scraper/run_meta.json"
DESKTOP = Path.home() / "Desktop"
LOW = 1.0  # a county-signal cell is thin when under 1% of the county's rows carry it

# ----------------------------------------------------------------------------- the rule

ALLOWED = "allowed"          # 'I agree', disclaimer, disclosure popup, credential-free guest button, terms, robots
CAPTCHA, BOT, LOGIN, PAID, NONE = "captcha", "bot", "login", "paid", "none"
KIND_OF = {CAPTCHA: "A", BOT: "A", LOGIN: "A", PAID: "B", ALLOWED: "C"}

_GUEST = re.compile(r"sign in as a guest|guest (button|click|sign-?in|access|user)|as a guest", re.I)
_CLICK = re.compile(r"\bi agree\b|\bi accept\b|disclaimer|disclosure|click-?through|accept(ed)? the terms|terms[- ]only|robots\.txt", re.I)


def classify_access(code: str | None) -> str:
    """The county matrix's access code -> allowed / captcha / bot / login / paid / none."""
    c = (code or "").strip().lower()
    if c in ("open", "disclaimer_click", "guest", "open_checked"):
        return ALLOWED
    if c == "captcha":
        return CAPTCHA
    if c == "blocked":
        return BOT
    if c == "login":
        return LOGIN
    if c in ("payment", "paywall", "paid"):
        return PAID
    return NONE


def classify_text(text: str) -> str:
    """A free-text wall description -> the same classes. A credential-free guest button or a plain
    click is allowed even when the page also shows a password form, because the rule is about what
    a visitor must supply, and a guest button asks for nothing."""
    t = text or ""
    # a fee for document images does not make the search itself paid
    t = re.sub(r"\b(deed )?images?\b[^;,)]*?\b(paid|costs?|fees?)\b", " ", t, flags=re.I)
    t = re.sub(r"\b(every|each) (deed )?image costs?[^;,)]*", " ", t, flags=re.I)
    if re.search(r"no online (index|system)|unreachable|not checked|not online", t, re.I) and not re.search(r"captcha|cloudflare|login|paid", t, re.I):
        return NONE
    if _GUEST.search(t):
        return ALLOWED
    if re.search(r"paid|subscription|\$\d|per page|per day|fee", t, re.I):
        return PAID
    if re.search(r"captcha|arithmetic|math question", t, re.I):
        return CAPTCHA
    if re.search(r"cloudflare|bot check|bot-check|challenge|access denied|blocked|\b40[36]\b|akamai|imperva|datadome|waf", t, re.I):
        return BOT
    if re.search(r"login|log in|sign in|account|password|register", t, re.I):
        return LOGIN
    if _CLICK.search(t):
        return ALLOWED
    return NONE


def classify_source_access(access_class: str) -> str:
    """new_sources_*.json access_class -> class."""
    a = (access_class or "").strip().lower()
    return {"captcha": CAPTCHA, "bot-check": BOT, "login": LOGIN, "paid": PAID,
            "terms-only": ALLOWED, "disclaimer-click": ALLOWED, "open": ALLOWED, "js-app": ALLOWED}.get(a, NONE)


# ----------------------------------------------------------------------------- inputs

def norm(c: str) -> str:
    s = re.sub(r"[-_]+", " ", (c or "").strip().lower())
    s = re.sub(r"\s+county$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def file_date(repo: Path, path: Path) -> str:
    rel = os.path.relpath(path, repo)
    d = _git(repo, "log", "-1", "--format=%cs", "--", rel)
    if d and not _git(repo, "status", "--porcelain", "--", rel):
        return d
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M") + " (file time)"
    except OSError:
        return "missing"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "missing"


def load_registry(repo: Path) -> list[dict]:
    """The deed adapters registered in enrichment_generic_rod.py, read with ast (no import)."""
    p = repo / "src" / "foreclosure_scraper" / "enrichment_generic_rod.py"
    if not p.exists():
        return []
    tree = ast.parse(p.read_text())
    found: dict[tuple, dict] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if not name.endswith("CONFIG") or not isinstance(node.value, ast.Dict):
                continue
            try:
                d = ast.literal_eval(node.value)
            except ValueError:
                continue
            chain_only = "CHAIN_ONLY" in name
            for (st, county), spec in d.items():
                module, flag = spec[0], spec[1]
                default = spec[2] if len(spec) > 2 else "1"
                key = (st, norm(county), module)
                rec = found.setdefault(key, {"state": st, "county": county, "module": module, "flag": flag,
                                             "default_on": default == "1", "chain_only": chain_only})
                rec["chain_only"] = rec["chain_only"] and chain_only
    return sorted(found.values(), key=lambda r: (r["state"], norm(r["county"]), r["module"]))


def parse_person_needed(md_path: Path, state: str) -> dict[str, tuple[str, str]]:
    """'Person needed' table of a platform cluster doc -> {county: (class, wall text)}."""
    out: dict[str, tuple[str, str]] = {}
    if not md_path.exists():
        return out
    in_sec = False
    for line in md_path.read_text().splitlines():
        if line.startswith("## "):
            in_sec = line.lower().startswith("## person needed")
            continue
        if not in_sec or not line.startswith("|") or line.startswith("|---") or line.lower().startswith("| county"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        counties = re.sub(r"\([^)]*\)", "", cells[0])
        wall = " ".join(cells[1:])
        klass = classify_text(wall)
        for c in re.split(r",| and ", counties):
            c = c.strip()
            if c and c.lower() not in ("county",):
                out[norm(c)] = (klass, wall)
    return out


def latest(pattern: str) -> Path | None:
    files = sorted(glob.glob(pattern))
    return Path(files[-1]) if files else None


def load_coverage(path: Path | None):
    cov, rows, unknown = {}, {}, {}
    if not path or not path.exists():
        return cov, rows, unknown
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["County"] == "UNKNOWN":
                unknown[r["State"]] = r
                continue
            cov[(r["State"], norm(r["County"]))] = r
            rows[(r["State"], norm(r["County"]))] = int(float(r["Rows"] or 0))
    return cov, rows, unknown


def _rel(repo: Path, p: Path) -> str:
    try:
        r = os.path.relpath(Path(p).resolve(), repo)
    except ValueError:
        return str(p)
    return str(p) if r.startswith("..") else r


def load_run_meta(repo: Path, offline: bool, path: Path | None = None) -> tuple[dict, str]:
    if path:
        return json.loads(Path(path).read_text()), _rel(repo, Path(path))
    if not offline:
        try:
            import urllib.request
            req = urllib.request.Request(RUN_META_URL, headers={"User-Agent": "Mozilla/5.0 (Macintosh) owner-manual-builder"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode()), RUN_META_URL
        except Exception:  # noqa: BLE001
            pass
    local = repo / "docs" / "run_meta.json"
    if local.exists():
        return json.loads(local.read_text()), _rel(repo, local) + " (local copy)"
    return {}, "none"


def run_status(meta: dict) -> dict[str, str]:
    return {k: str(v) for k, v in (meta.get("source_status") or {}).items()}


def dormant(meta: dict) -> list[dict]:
    out = []
    for k, v in sorted(run_status(meta).items()):
        if v.startswith("DORMANT"):
            reason = re.sub(r"^DORMANT\s*[-—]\s*(disabled:\s*)?", "", v)
            out.append({"source": k, "reason": reason, "class": classify_text(reason)})
    return out


def blocked_now(meta: dict) -> list[dict]:
    return [{"source": k, "status": v} for k, v in sorted(run_status(meta).items()) if "BLOCKED" in v]


def load_new_sources(repo: Path) -> list[dict]:
    recs = []
    for f in sorted(glob.glob(str(repo / "docs" / "new_sources_*.json"))):
        try:
            d = json.loads(Path(f).read_text())
        except ValueError:
            continue
        items = d.get("sources") if isinstance(d, dict) else d
        for r in items or []:
            if not isinstance(r, dict):
                continue
            where = r.get("geography") or ", ".join(x for x in (r.get("city"), r.get("county"), r.get("state")) if x)
            recs.append({"file": Path(f).name, "id": r.get("id") or "", "name": r.get("name") or "",
                         "where": where or "", "state": r.get("state") or "", "county": r.get("county") or "",
                         "access_class": r.get("access_class") or "", "class": classify_source_access(r.get("access_class")),
                         "price": r.get("price") or "", "manual": r.get("manual_steps") or "", "url": r.get("url") or ""})
    return recs


def load_gap_matrix(repo: Path) -> dict:
    p = latest(str(repo / "docs" / "gap_matrix" / "gap_matrix_*.json"))
    if not p:
        return {}
    try:
        g = json.loads(p.read_text())
    except ValueError:
        return {}
    s = g.get("summary") or {}
    walled = defaultdict(int)
    gl = g.get("gaps") or {}
    hdr, rows = gl.get("header") or [], gl.get("rows") or []
    if "gap_class" in hdr:
        i = hdr.index("gap_class")
        for r in rows:
            if str(r[i]).startswith("walled"):
                walled[str(r[i])] += 1
    return {"path": p, "date": g.get("date"), "unknown": s.get("unknown_county_rows") or {},
            "baseline_unknown": s.get("baseline_unknown_rows") or {}, "walled": dict(walled)}


# ----------------------------------------------------------------------------- the model

def build_model(repo: Path, offline: bool = False, run_meta_path: Path | None = None, coverage_path: Path | None = None) -> dict:
    reg = json.loads((repo / "docs" / "walls_register.json").read_text())
    matrix_p = repo / "docs" / "county_records" / "county_records_matrix.json"
    matrix = json.loads(matrix_p.read_text())["counties"] if matrix_p.exists() else []
    clusters = {}
    for st in ("nc", "sc"):
        clusters.update({(st.upper(), k): v for k, v in parse_person_needed(
            repo / "docs" / "county_records" / f"{st}_rod_platform_clusters.md", st.upper()).items()})
    registry = load_registry(repo)
    reg_by_county = defaultdict(list)
    for a in registry:
        reg_by_county[(a["state"], norm(a["county"]))].append(a)
    cov_p = coverage_path or latest(str(repo / "docs" / "gap_matrix" / "county_signal_coverage_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].csv"))
    if not cov_p:
        alt = DESKTOP / "county_signal_coverage_FINAL.csv"
        cov_p = alt if alt.exists() else None
    cov, rows, unknown = load_coverage(cov_p)
    meta, meta_src = load_run_meta(repo, offline, run_meta_path)
    status = run_status(meta)
    news = load_new_sources(repo)
    gap = load_gap_matrix(repo)
    overrides = {tuple(k.split("|")): v for k, v in (reg.get("access_overrides") or {}).items()}

    # county systems
    counties = []
    tally = defaultdict(int)
    for c in matrix:
        st, k = c["state"], norm(c["county"])
        rec = {"state": st, "county": c["county"].replace("-", " ").title(), "key": k,
               "rows": rows.get((st, k), 0), "manual_lane": c.get("manual_lane") or "", "sys": {}}
        for sec in ("rod", "probate", "tax"):
            d = c.get(sec) or {}
            klass = classify_access(d.get("access"))
            why = {"open": "Free, open", "disclaimer_click": "Free after an 'I accept' click"}.get(d.get("access") or "", "")
            ov = overrides.get((st, k, sec))
            if sec == "rod" and (st, k) in clusters:
                klass, wall = clusters[(st, k)]
                why = wall
            if ov:
                klass, why = ov[0], ov[1]
            adapters = reg_by_county.get((st, k), []) if sec == "rod" else []
            if adapters and klass != ALLOWED and klass != NONE:
                why = (why + "; ") if why else ""
                why += "a registered reader covers part of it"
            rec["sys"][sec] = {"class": klass, "why": why, "url": d.get("url") or "", "adapters": adapters}
            if sec == "probate" and st == "NC" and klass == CAPTCHA:
                tally["nc_estates"] += 1
                continue
            built = bool(adapters) and klass in (ALLOWED, NONE)
            tally["built" if built else klass] += 1
        counties.append(rec)

    # cards
    cards = []
    for card in reg["cards"]:
        card = dict(card)
        wc = card.get("wall_class") or BOT
        if wc in (ALLOWED, "click", "guest", "terms"):
            card["_demoted"] = True   # never a wall: shown in appendix C
        watch = card.get("watch_sources") or []
        card["_live"] = [(s, status.get(s, "not in the last run")) for s in watch]
        card["_readers_ok"] = bool(watch) and all(v.startswith(("OK", "EMPTY")) for _, v in card["_live"])
        cells, weighted, ncount = 0, 0.0, set()
        for st, cty in card.get("scope") or []:
            r = cov.get((st, norm(cty)))
            for col in card.get("signal_columns") or []:
                try:
                    v = float(r[col]) if r and r.get(col) not in (None, "") else None
                except ValueError:
                    v = None
                if v is not None and v < LOW:
                    cells += 1
                    weighted += min(1.0, rows.get((st, norm(cty)), 0) / 1000.0)
                    ncount.add((st, cty))
        card["_cells_possible"] = cells
        if card.get("loads") == "crm":
            cells, weighted = 0, 0.0
        card["_cells"], card["_wcells"], card["_ncounties"] = cells, weighted, len(ncount)
        mm = card.get("minutes_month") or 0
        card["_per_hour"] = weighted / mm * 60 if mm else 0.0
        cards.append(card)
    by_id = {c["id"]: c for c in cards}

    # coverage of source-hunt records by cards
    claim = {}
    for c in cards:
        for x in c.get("covers") or []:
            claim[x.lower()] = c["id"]
    walled_news = []
    for r in news:
        if r["class"] in (CAPTCHA, BOT, LOGIN, PAID):
            r = dict(r)
            r["card"] = claim.get(r["id"].lower()) or claim.get(r["name"].lower())
            walled_news.append(r)

    # built: adapters (computed) + register items with evidence checks
    built = []
    mods = defaultdict(list)
    for a in registry:
        mods[(a["module"], a["flag"], a["default_on"])].append(f"{a['county']} {a['state']}" + (" (chain only)" if a["chain_only"] else ""))
    for (m, flag, on), cs in sorted(mods.items()):
        built.append({"title": f"Deed reader {m}.", "text": f"{len(cs)} counties: {', '.join(cs)}. Switch {flag}, {'on' if on else 'off'} by default.",
                      "check": "registered in enrichment_generic_rod.py"})
    for b in reg.get("built_static") or []:
        missing = []
        for ev in b.get("evidence") or []:
            p = repo / ev["path"]
            if not p.exists() or (ev.get("regex") and not re.search(ev["regex"], p.read_text(errors="replace"))):
                missing.append(ev["path"])
        built.append({"title": b["title"], "text": b["text"],
                      "check": ("NOT FOUND in the repo: " + ", ".join(missing)) if missing else ("checked in the repo" if b.get("evidence") else "")})

    # top 15
    top = []
    for t in reg["top15"]:
        ids = t["cards"]
        es = [by_id[i] for i in ids if i in by_id]
        if ids == ["foia"]:
            cells, why, load = "not in sheet", "Judgment dollar amounts and SC evictions, which are not online anywhere.", "No loader yet"
        else:
            if es and all(e.get("_readers_ok") for e in es):
                continue  # our readers work again; not a task this week
            cells = str(sum(e["_cells"] for e in es)) if any(e.get("signal_columns") for e in es) else "n/a"
            why = t.get("brings") or "; ".join(e.get("leads") or "" for e in es)
            loads = {e.get("loads") for e in es}
            load = "Small loader first" if "small" in loads else ("Loads today" if loads == {"yes"} else "CRM notes")
        top.append({"label": t["task"], "minutes": t["minutes"], "often": t["often"], "cells": cells, "why": why,
                    "card": ids[0], "load": load})
    top = top[:15]

    cards_for = defaultdict(set)
    for c in cards:
        for st, cty in c.get("scope") or []:
            cards_for[(st, norm(cty))].add(c["id"])

    inputs = collect_inputs(repo, cov_p, meta_src)
    return {"reg": reg, "counties": counties, "tally": dict(tally), "cards": cards, "by_id": by_id, "registry": registry,
            "dormant": dormant(meta), "blocked": blocked_now(meta), "meta_src": meta_src, "meta_time": meta.get("run_time"),
            "walled_news": walled_news, "news_count": len(news), "gap": gap, "unknown": unknown, "coverage": cov_p,
            "built": built, "top": top, "cards_for": cards_for, "inputs": inputs,
            "commit": _git(repo, "rev-parse", "--short", "HEAD") or "unknown",
            "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")}


def collect_inputs(repo: Path, cov_p: Path | None, meta_src: str) -> list[dict]:
    paths = [repo / "docs" / "walls_register.json", repo / "docs" / "county_records" / "county_records_matrix.json"]
    paths += [Path(p) for p in sorted(glob.glob(str(repo / "docs" / "county_records" / "*_rod_platform_clusters.md")))]
    paths += [Path(p) for p in sorted(glob.glob(str(repo / "docs" / "new_sources_*.json")))]
    paths += [Path(p) for p in sorted(glob.glob(str(repo / "docs" / "gap_matrix" / "*.json")))]
    if cov_p:
        paths.append(Path(cov_p))
    out = []
    for p in paths:
        try:
            rel = os.path.relpath(p, repo)
        except ValueError:
            rel = str(p)
        if rel.startswith(".."):
            rel = str(p)
        out.append({"path": rel, "sha": sha(p), "date": file_date(repo, p) if p.exists() else "missing"})
    return out


def fingerprint(model: dict) -> dict:
    return {
        "inputs": {i["path"]: i["sha"] for i in model["inputs"]},
        "adapters": [f"{a['state']}|{a['county']}|{a['module']}|{a['flag']}|{'on' if a['default_on'] else 'off'}" for a in model["registry"]],
        "dormant": [d["source"] for d in model["dormant"]],
        "new_source_files": sorted({r["file"] for r in model["walled_news"]}),
    }


def diff_fingerprint(old: dict, new: dict) -> list[str]:
    msgs = []
    oi, ni = old.get("inputs") or {}, new.get("inputs") or {}
    for p in sorted(set(oi) | set(ni)):
        if p not in oi:
            msgs.append(f"new input file: {p}")
        elif p not in ni:
            msgs.append(f"input file gone: {p}")
        elif oi[p] != ni[p]:
            msgs.append(f"input file changed: {p}")
    for key, label in (("adapters", "registered deed adapter"), ("dormant", "DORMANT scraper in the live run")):
        o, n = set(old.get(key) or []), set(new.get(key) or [])
        msgs += [f"{label} added: {x}" for x in sorted(n - o)]
        msgs += [f"{label} removed: {x}" for x in sorted(o - n)]
    return msgs


# ----------------------------------------------------------------------------- rendering

def anchor(eid: str) -> str:
    return "card-" + eid.replace("_", "-")


def _bold(m):
    x = m.group(1)
    if "&lt;" in x or x.startswith("http") or x.startswith("~/") or re.search(r"\.(html|csv|pdf)$", x) or ("/" in x and " " not in x):
        return "`" + x + "`"
    return "**" + x + "**"


def md_text(s: str) -> str:
    s = re.sub(r"<b>(.*?)</b>", _bold, str(s))
    s = re.sub(r"<[^>]+>", "", s)
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def md_cell(s) -> str:
    return md_text(str(s)).replace("|", "/").replace("\n", " ")


def h(s) -> str:
    return html.escape(str(s), quote=False)


KIND_WORD = {"A": "A: a person passes it in a browser", "B": "B: paid or attorney-only", "C": "C: allowed"}
GROUP_TITLE = {"national": "Nationwide", "nc": "Statewide sources: North Carolina", "sc": "Statewide sources: South Carolina",
               "county": "Per county (walled items with a how-to card)", "city": "Per city"}
CLASS_WORD = {ALLOWED: "Free (open, or a plain click)", CAPTCHA: "CAPTCHA: a person passes it", BOT: "Bot check: a person in a normal browser",
              LOGIN: "Login: a person signs in to an account", PAID: "Paid", NONE: "No online system found: call or visit"}
LOAD_WORD = {"yes": "Loads today", "small": "Needs a small loader first (about an hour of engineering)",
             "crm": "Goes into your CRM notes only; does not reach the dashboard"}


def sys_word(s: dict, sec: str, st: str) -> str:
    if sec == "probate" and st == "NC" and s["class"] == CAPTCHA:
        return "NC eCourts: picture CAPTCHA, a person passes it"
    w = CLASS_WORD[s["class"]]
    if s["class"] == ALLOWED and s["why"]:
        w = "Free after a 'Sign in as a Guest' click" if _GUEST.search(s["why"]) else (s["why"] if len(s["why"]) < 90 else w)
    if s["adapters"]:
        names = ", ".join(sorted({f"{a['module']} ({a['flag']}, {'on' if a['default_on'] else 'off'})" for a in s["adapters"]}))
        w += f". Reader: {names}"
    return w


def card_rows(e: dict) -> list[tuple[str, str]]:
    rows = [("Place", e["place"]), ("The wall", e["wall"]), ("Start here", e["url"]), ("What it is, what we lose", e["what"]),
            ("Step by step", None), ("What to pull", e["pull"]), ("How to save it", e["save"]), ("How it gets loaded", e["lane"]),
            ("Time, how often", f"{e['time']} {e['often']}"), ("What we gain", e["gain"]),
            ("Reaches the dashboard?", LOAD_WORD.get(e.get("loads") or "crm"))]
    if e.get("_live"):
        live = "; ".join(f"{s}: {v[:90]}" for s, v in e["_live"])
        if e.get("_readers_ok"):
            live = "Our readers worked in the last run (" + live + "). Do this only if they fail again."
        rows.append(("Live status (last run)", live))
    if e.get("signal_columns"):
        if e.get("loads") == "crm":
            rows.append(("Thin cells it fills", f"0 as things stand (notes only). If a loader were built: {e['_cells_possible']}."))
        elif e["_cells"] == 0:
            rows.append(("Thin cells it fills", "0 (these cells are already filled in the counties it covers)."))
        else:
            rows.append(("Thin cells it fills", f"{e['_cells']} in {e['_ncounties']} counties (value score {e['_wcells']:.1f} for about {e['minutes_month']} minutes a month)."))
    rows.append(("Who else could do it", e["others"]))
    return rows


def counts(m: dict) -> dict:
    live = [c for c in m["cards"] if not c.get("_demoted")]
    k = defaultdict(int)
    for c in live:
        k[c["kind"]] += 1
    return {"A": k["A"], "B": k["B"], "paid": len(m["reg"]["paid"]), "appx": len(m["reg"]["appendix_c"]) + sum(1 for c in m["cards"] if c.get("_demoted")),
            "county_A": sum(m["tally"].get(x, 0) for x in (CAPTCHA, BOT, LOGIN)), "county_B": m["tally"].get(PAID, 0),
            "county_allowed": m["tally"].get(ALLOWED, 0), "county_built": m["tally"].get("built", 0),
            "county_none": m["tally"].get(NONE, 0), "systems": len(m["counties"]) * 3}


def totals_text(m: dict) -> str:
    n = counts(m)
    return (f"{n['A']} step-by-step cards of type A and {n['B']} of type B (type C items are not walls, so they get no card); "
            f"{n['paid']} paid or attorney-only items in the price table; {n['appx']} allowed items in appendix C. "
            f"Across the {len(m['counties'])} researched counties (deeds, estates and tax bills = {n['systems']} county systems), "
            f"{n['county_A']} county systems really need a person (CAPTCHA, bot check or a real login) and {n['county_B']} need payment; "
            f"add to that the one statewide NC eCourts estate search (a CAPTCHA), which serves all 100 NC counties. "
            f"{n['county_allowed']} open freely or after a plain 'I accept' or 'Sign in as a Guest' click, {n['county_built']} more are read by a registered "
            f"deed reader, and {n['county_none']} have no online system or did not answer (call or visit). "
            f"The source hunts list {len(m['walled_news'])} walled records ({sum(1 for r in m['walled_news'] if r['card'])} covered by a card).")


def unknown_text(m: dict) -> str:
    u, g = m["unknown"], m["gap"]
    parts = []
    if u.get("NC") and u.get("SC"):
        nc, sc = u["NC"], u["SC"]
        nb = round(int(float(nc["Rows"])) * float(nc.get("lt_bankruptcy") or 0) / 100)
        nl = round(int(float(nc["Rows"])) * float(nc.get("lt_tax_lien") or 0) / 100)
        sb = round(int(float(sc["Rows"])) * float(sc.get("lt_bankruptcy") or 0) / 100)
        parts.append(f"The coverage file ({os.path.basename(str(m['coverage']))}) has {int(float(nc['Rows'])):,} NC rows and {int(float(sc['Rows'])):,} SC rows with no county: "
                     f"in NC about {nb:,} bankruptcy cases and about {nl:,} LiensNC lien-agent filings (tagged as tax liens); in SC about {sb:,} bankruptcy cases.")
    if g.get("unknown"):
        parts.append(f"The gap matrix of {g.get('date')} counts NC {g['unknown'].get('NC', 0):,} and SC {g['unknown'].get('SC', 0):,} (the 10/01 baseline was NC {g['baseline_unknown'].get('NC', 0):,}, SC {g['baseline_unknown'].get('SC', 0):,}).")
    return " ".join(parts)


def file_map(reg: dict) -> list[dict]:
    """The one-page 'Where every file goes' table: the register's rows, each naming its cards, then one
    row for every other card that needs a loader and one for CRM-only cards. Every card lands in a row."""
    fm = reg["file_map"]
    by_id = {c["id"]: c for c in reg["cards"]}
    named: set[str] = set()
    rows = []
    for r in fm["rows"]:
        ids = r.get("cards", [])
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise SystemExit(f"file_map row '{r['what']}' names unknown cards: {missing}")
        named.update(ids)
        rows.append(dict(r, names=[by_id[i]["short"] for i in ids]))
    for key, loads in (("small_row", ("small", "yes")), ("crm_row", ("crm", None))):
        rest = [c["short"] for c in reg["cards"] if c["id"] not in named and (c.get("loads") or "crm") in loads]
        if rest:
            rows.append(dict(fm[key], names=rest))
    return rows


FILE_MAP_COLS = ("What you pulled", "Where you got it", "How to save it", "Exact folder or path", "What to do next", "What changes on the board")


def _fm_cells(r: dict) -> list[str]:
    what = r["what"] + (f" (cards: {', '.join(r['names'])})" if r["names"] else "")
    return [what, r["from"], r["save"], r["where"], r["next"], r["board"]]


def build_md(m: dict) -> str:
    reg = m["reg"]
    L: list[str] = []
    a = L.append
    a("# What you can do by hand: every walled source, and exactly how")
    a("")
    a(f"**Generated {m['generated']} from commit {m['commit']}** by `scripts/build_owner_manual.py`. Do not edit this file by hand: edit `docs/walls_register.json` (or the data inputs) and rerun. `uv run python scripts/build_owner_manual.py --check` says whether it is stale.")
    a("")
    a("**What changed since the last version**")
    a("")
    for ln in reg["what_changed"]:
        a(f"- {md_text(ln)}")
    a("")
    a("**Data inputs**")
    a("")
    for i in m["inputs"]:
        a(f"- `{i['path']}` ({i['date']})")
    a(f"- Live run status: {m['meta_src']} (run {m['meta_time'] or 'unknown'})")
    a(f"- Deed adapters registered in `src/foreclosure_scraper/enrichment_generic_rod.py` at commit {m['commit']}: {len(m['registry'])}")
    a("")
    a("Owner's manual. Plain words. For every source we meet that has a CAPTCHA, a bot check, a real login or a paywall: where to start, the clicks, what to pull, how to save it, where to put the file so the engine loads it, how long it takes, what you gain, and who else could do it. Plain click-throughs and terms-only limits are not walls; they are listed as allowed.")
    a("")
    a("**The rule we keep:** our code never solves a CAPTCHA, never gets past a bot check or a paywall, and never creates accounts. The only stored login is LiensNC's, by the owner's choice. Everything below that needs a person, you do in a normal browser; our tools read the files you save.")
    a("")
    titles = ["Where every file goes (one page)", "How to read this", "Owner decisions in force", "Built (computed from the repo)", "What I need from you, in order",
              "How saving and loading works", "What really stays manual"] + [GROUP_TITLE[g] for g in GROUP_TITLE] + [
              "Every walled record in the source hunts", "Scrapers switched off or blocked in the last run", "The UNKNOWN-county rows",
              "Every county at a glance", "Paid or attorney-only (type B): prices", "Appendix C: allowed, built or buildable (not walls)",
              "Data that does not exist anywhere", "Stop doing these (already automatic or useless)", "Gaps and disagreements in our notes", "Where this came from"]
    a("## Contents")
    a("")
    for t in titles:
        a(f"- [{t}](#{re.sub(r'[^a-z0-9 -]', '', t.lower()).replace(' ', '-')})")
    a("")
    a("## Where every file goes (one page)")
    a("")
    a(md_text(reg["file_map"]["intro"]))
    a("")
    a("| " + " | ".join(FILE_MAP_COLS) + " |")
    a("|" + "---|" * len(FILE_MAP_COLS))
    for r in file_map(reg):
        a("| " + " | ".join(md_cell(x) for x in _fm_cells(r)) + " |")
    a("")
    a("## How to read this")
    a("")
    for k in ("A", "B", "C"):
        a(f"- {md_text(reg['kind_def'][k])}")
    a("")
    a(f"**Totals:** {totals_text(m)}")
    a("")
    a(f"**How the ranking works.** The coverage file shows, per county and signal, the share of rows that carry it. A cell is **thin** when it is under {LOW:g}%. For each card we count the thin cells it would fill in the counties it covers (a county with under 1,000 rows counts as a fraction). The checklist puts new leads first, then thin cells per minute of your time.")
    a("")
    a("## Owner decisions in force")
    a("")
    for t, x in reg["decisions"]:
        a(f"- **{t}** {md_text(x)}")
    a("")
    a("## Built (computed from the repo)")
    a("")
    a("Deed readers come from the adapter registry; the other items are checked against files in the repo. Most new readers sit behind an on/off switch until you turn them on.")
    a("")
    for b in m["built"]:
        a(f"- **{md_text(b['title'])}** {md_text(b['text'])}" + (f" ({b['check']})" if b["check"] else ""))
    a("")
    a("## What I need from you, in order")
    a("")
    a("| # | Task | Minutes | How often | Thin cells | Loads? | What it brings |")
    a("|---|---|---|---|---|---|---|")
    for i, t in enumerate(m["top"], 1):
        a(f"| {i} | {md_cell(t['label'])} ([card](#{anchor(t['card'])})) | {t['minutes']} | {t['often']} | {t['cells']} | {t['load']} | {md_cell(t['why'])} |")
    a("")
    a(f"Weekly items add up to about {sum(t['minutes'] for t in m['top'] if t['often'] == 'weekly')} minutes a week. Do them in order; stop when your time runs out.")
    a("")
    a("## How saving and loading works")
    a("")
    for ln in reg["saving_md"]:
        a(ln)
    a("")
    a("## What really stays manual")
    a("")
    a(md_text(reg["manual_intro"]))
    a("")
    live = [c for c in m["cards"] if not c.get("_demoted")]
    for grp in GROUP_TITLE:
        a(f"## {GROUP_TITLE[grp]}")
        a("")
        items = sorted([c for c in live if c["group"] == grp], key=lambda e: (-e["_per_hour"], e.get("minutes_month") or 0))
        if grp == "county":
            for st, title in (("NC", "North Carolina counties"), ("SC", "South Carolina counties")):
                a(f"### {title}")
                a("")
                for e in [x for x in items if x.get("state") == st]:
                    md_card(a, e, 4)
        else:
            for e in items:
                md_card(a, e, 3)
        if grp == "sc":
            f = reg["foia"]
            a(f'<a id="{anchor("foia")}"></a>')
            a("")
            a("### Records requests (FOIA)")
            a("")
            a(md_text(f["text"]))
            a("")
            a(f"Time: {f['minutes']}. Kind: not a wall (the data is not online).")
            a("")
    a("## Every walled record in the source hunts")
    a("")
    a(f"Generated from every `docs/new_sources_*.json` ({m['news_count']} records). Only CAPTCHA, bot-check, login and paid records are listed; open, terms-only, click-through and script-only pages are not walls. 'no card yet' means a person can follow the record's own manual step until a card is written.")
    a("")
    a("| Kind | Source | Where | What a person does | Card |")
    a("|---|---|---|---|---|")
    for r in sorted(m["walled_news"], key=lambda r: (r["state"] or "~", r["county"] or "~", r["name"])):
        card = f"[{m['by_id'][r['card']].get('short', r['card'])}](#{anchor(r['card'])})" if r["card"] else "no card yet"
        a(f"| {KIND_OF[r['class']]} ({r['access_class']}) | {md_cell(r['name'])} | {md_cell(r['where'])} | {md_cell((r['manual'] or r['price'])[:300])} | {card} |")
    a("")
    a("## Scrapers switched off or blocked in the last run")
    a("")
    a(f"From the run status ({m['meta_src']}, run {m['meta_time'] or 'unknown'}). A DORMANT reason that names a CAPTCHA, a bot check, a login or a payment is a wall; the rest are switched off for other reasons (dead page, duplicate, season).")
    a("")
    a("| Scraper | Why | Wall? |")
    a("|---|---|---|")
    for d in m["dormant"]:
        a(f"| {d['source']} | {md_cell(d['reason'][:240])} | {('yes: ' + CLASS_WORD[d['class']]) if d['class'] in (CAPTCHA, BOT, LOGIN, PAID) else 'no'} |")
    for b in m["blocked"]:
        a(f"| {b['source']} | {md_cell(b['status'][:240])} | blocked in this run (may be temporary) |")
    a("")
    a("## The UNKNOWN-county rows")
    a("")
    a(unknown_text(m))
    a("")
    for ln in reg["unknown_bullets"]:
        a(f"- {md_text(ln)}")
    a("")
    a("## Every county at a glance")
    a("")
    a("Computed from the county matrix, the 'Person needed' tables of the platform cluster docs and the registered deed readers. 'Rows' is from the coverage file.")
    a("")
    for st in ("NC", "SC"):
        a(f"### {'North Carolina' if st == 'NC' else 'South Carolina'}")
        a("")
        a("| County | Rows | Deeds | Estates | Tax bills | What a person does | Cards |")
        a("|---|---|---|---|---|---|---|")
        for c in sorted([c for c in m["counties"] if c["state"] == st], key=lambda c: c["key"]):
            cards = ", ".join(f"[{m['by_id'][x].get('short', x)}](#{anchor(x)})" for x in sorted(m["cards_for"].get((st, c["key"]), [])) if not m["by_id"][x].get("_demoted"))
            a(f"| {c['county']} | {c['rows']:,} | {md_cell(sys_word(c['sys']['rod'], 'rod', st))} | {md_cell(sys_word(c['sys']['probate'], 'probate', st))} | "
              f"{md_cell(sys_word(c['sys']['tax'], 'tax', st))} | {md_cell(fix_ml(c['manual_lane'], reg) or 'Nothing needed beyond the free sites.')} | {cards} |")
        a("")
    a("## Paid or attorney-only (type B): prices")
    a("")
    a("Prices come from our notes and are not re-checked; confirm before buying.")
    a("")
    a("| What | Price | What it gets | Free alternative |")
    a("|---|---|---|---|")
    for row in reg["paid"]:
        a("| " + " | ".join(md_cell(x) for x in row) + " |")
    a("")
    a("## Appendix C: allowed, built or buildable (not walls)")
    a("")
    a(md_text(reg["appendix_c_intro"]))
    a("")
    a("| Source | The restriction | Status |")
    a("|---|---|---|")
    for row in reg["appendix_c"]:
        a("| " + " | ".join(md_cell(x) for x in row) + " |")
    for c in m["cards"]:
        if c.get("_demoted"):
            a(f"| {md_cell(c['name'])} | {md_cell(c['wall'])} | Allowed (a plain click or terms only): the card's steps still work by hand |")
    a("")
    a("## Data that does not exist anywhere")
    a("")
    for w, why in reg["does_not_exist"]:
        a(f"- **{md_text(w)}.** {md_text(why)}")
    a("")
    a("## Stop doing these (already automatic or useless)")
    a("")
    for w, why in reg["stop"]:
        a(f"- **{md_text(w)}.** {md_text(why)}")
    a("")
    a("## Gaps and disagreements in our notes")
    a("")
    for g in reg["gaps"]:
        a(f"- {md_text(g)}")
    if m["gap"].get("walled"):
        a("- Gap matrix walled cells by reason (" + str(m["gap"].get("date")) + "): " + "; ".join(f"{k} {v}" for k, v in sorted(m["gap"]["walled"].items(), key=lambda x: -x[1])) + ".")
    a("")
    a("## Where this came from")
    a("")
    for s in reg["sources_static"]:
        a(f"- {md_text(s)}")
    a("")
    return "\n".join(L) + "\n"


def fix_ml(t: str, reg: dict) -> str:
    for x, y in reg.get("manual_lane_fixes") or []:
        t = t.replace(x, y)
    return t


def md_card(a, e: dict, level: int) -> None:
    a(f'<a id="{anchor(e["id"])}"></a>')
    a("")
    a("#" * level + f" {md_text(e['name'])}")
    a("")
    for k, v in card_rows(e):
        if k == "Step by step":
            a("")
            a("**Step by step**")
            a("")
            for i, s in enumerate(e["steps"], 1):
                a(f"{i}. {md_text(s)}")
            a("")
        elif k == "Place":
            a(f"- **Place:** {md_text(v)}")
            a(f"- **Kind:** {KIND_WORD[e['kind']]}")
        else:
            a(f"- **{k}:** {md_text(v)}")
    a("")


CSS = r"""
@page { size: Letter; margin: 0.7in 0.65in 0.75in 0.65in;
  @bottom-left { content: "Owner manual, generated by scripts/build_owner_manual.py"; font: 8pt Georgia, serif; color: #666; }
  @bottom-right { content: "Page " counter(page); font: 8pt Georgia, serif; color: #666; } }
:root { color-scheme: light; }
* { box-sizing: border-box; }
html { background: #fff; }
body { margin: 0 auto; max-width: 8.3in; padding: 0 0.2in; font: 10.5pt/1.45 Georgia, "Times New Roman", serif; color: #111; background: #fff; }
h1, h2, h3, h4 { break-after: avoid; font-family: "Helvetica Neue", Arial, sans-serif; color: #0b2545; line-height: 1.2; }
h2 { font-size: 15pt; margin: 18pt 0 6pt; border-bottom: 1px solid #9aa4b2; padding-bottom: 3pt; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; }
p { margin: 0 0 7pt; }
.small { font-size: 9pt; color: #333; }
.url { font-family: Menlo, Consolas, monospace; font-size: 8.3pt; word-break: break-all; }
table { border-collapse: collapse; width: 100%; margin: 5pt 0 9pt; font-size: 9pt; }
th, td { border: 1px solid #9aa4b2; padding: 3pt 5pt; vertical-align: top; text-align: left; overflow-wrap: anywhere; }
thead th { background: #e9edf3; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 8.5pt; }
tr { break-inside: avoid; }
table.card > tbody > tr > th { width: 17%; background: #f3f5f8; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 8.5pt; }
table.county, table.dense { font-size: 7.4pt; } table.county td, table.county th, table.dense td, table.dense th { padding: 2pt 3pt; }
table.county .url { font-size: 6.4pt; }
ol.steps { margin: 2pt 0 2pt 16pt; padding: 0; } ol.steps li { margin-bottom: 2pt; }
.kind { font: 700 8pt "Helvetica Neue", Arial, sans-serif; padding: 1.5pt 6pt; border-radius: 8pt; margin-left: 6pt; vertical-align: 1pt; white-space: nowrap; }
.kA { background: #fdf0d2; color: #6b4a00; border: 1px solid #c9a04a; }
.kB { background: #f8dede; color: #7a1f1f; border: 1px solid #c58080; }
.kC { background: #e1f3e4; color: #1d5c2c; border: 1px solid #62a373; }
.box { border-left: 4px solid #0b2545; background: #f5f7fa; padding: 6pt 9pt; margin: 8pt 0; font-size: 9.8pt; break-inside: avoid; }
.cover .title { font: 700 25pt/1.15 "Helvetica Neue", Arial, sans-serif; color: #0b2545; margin: 0.15in 0 4pt; }
.cover .kicker { font: 600 10pt "Helvetica Neue", Arial, sans-serif; letter-spacing: 1.5pt; text-transform: uppercase; color: #666; }
.toc ol { columns: 2; column-gap: 24pt; font-size: 9.5pt; margin: 4pt 0 0 14pt; padding: 0; }
.toc li { margin-bottom: 2pt; break-inside: avoid; }
.card-wrap { margin: 6pt 0 12pt; }
a { color: #0b2545; text-decoration: none; }
section.part { break-before: page; }
table.fmap { font-size: 6pt; line-height: 1.1; table-layout: fixed; width: 100%; } table.fmap td, table.fmap th { padding: 1px 3px; vertical-align: top; overflow-wrap: anywhere; }
table.fmap th:nth-child(1) { width: 20%; } table.fmap th:nth-child(2) { width: 13%; } table.fmap th:nth-child(3) { width: 18%; } table.fmap th:nth-child(4) { width: 16%; } table.fmap th:nth-child(5) { width: 17%; } table.fmap th:nth-child(6) { width: 16%; }
@media print { body { padding: 0; max-width: none; } a { color: #000; } }
"""


def html_card(e: dict) -> str:
    out = []
    for k, v in card_rows(e):
        if k == "Step by step":
            v = "<ol class='steps'>" + "".join(f"<li>{s}</li>" for s in e["steps"]) + "</ol>"
        elif k == "Start here":
            v = f"<span class='url'>{h(v)}</span>" if str(v).startswith("http") else h(v)
        elif k == "Live status (last run)":
            v = h(v)
        out.append(f"<tr><th>{h(k)}</th><td>{v}</td></tr>")
    return (f"<div class='card-wrap' id='{anchor(e['id'])}'><h3>{e['name']} <span class='kind k{e['kind']}'>{h(KIND_WORD[e['kind']])}</span></h3>"
            f"<table class='card'><tbody>{''.join(out)}</tbody></table></div>")


def build_html(m: dict) -> str:
    reg = m["reg"]
    P: list[str] = []
    a = P.append
    a("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
      "<title>Owner Manual Lanes</title><style>" + CSS + "</style></head><body>")
    a("<section class='cover'><div class='kicker'>Owner's manual</div><div class='title'>What you can do by hand: every walled source, and exactly how</div>"
      f"<p><b>Generated {h(m['generated'])} from commit {h(m['commit'])}</b> by scripts/build_owner_manual.py. Public copy: docs/OWNER_MANUAL_LANES.md.</p>"
      "<div class='box'><b>What changed since the last version</b><ol class='steps'>" + "".join(f"<li>{x}</li>" for x in reg["what_changed"]) + "</ol></div>"
      "<div class='box'><b>Data inputs</b><ul class='small'>" + "".join(f"<li>{h(i['path'])} ({h(i['date'])})</li>" for i in m["inputs"])
      + f"<li>Live run status: {h(m['meta_src'])} (run {h(m['meta_time'] or 'unknown')})</li>"
      + f"<li>Deed adapters registered in enrichment_generic_rod.py: {len(m['registry'])}</li></ul></div>"
      "<div class='box'><b>The rule we keep.</b> Our code never solves a CAPTCHA, never gets past a bot check or a paywall, and never creates accounts. "
      "The only stored login is LiensNC's, by the owner's choice. Everything here that needs a person, you do in a normal browser; our tools read the files you save.</div></section>")
    toc = [("filemap", "Where every file goes (one page)"), ("read", "How to read this"), ("decisions", "Owner decisions in force"), ("built", "Built (computed from the repo)"),
           ("top15", "What I need from you, in order"), ("saving", "How saving and loading works"), ("manual", "What really stays manual")]
    toc += [("grp-" + g, GROUP_TITLE[g]) for g in GROUP_TITLE]
    toc += [("news", "Every walled record in the source hunts"), ("dormant", "Scrapers switched off or blocked"), ("unknown", "The UNKNOWN-county rows"),
            ("counties", "Every county at a glance"), ("paid", "Paid or attorney-only: prices"), ("appxc", "Appendix C: allowed (not walls)"),
            ("absent", "Data that does not exist"), ("stop", "Stop doing these"), ("gaps", "Gaps and disagreements"), ("sources", "Where this came from")]
    a("<section class='toc'><h2>Contents</h2><ol>" + "".join(f"<li><a href='#{i}'>{h(t)}</a></li>" for i, t in toc) + "</ol></section>")
    a(f"<section id='filemap' class='part'><h2>Where every file goes (one page)</h2><p class='small'>{reg['file_map']['intro']}</p><table class='fmap'><thead><tr>"
      + "".join(f"<th>{h(c)}</th>" for c in FILE_MAP_COLS) + "</tr></thead><tbody>"
      + "".join("<tr>" + "".join(f"<td>{x}</td>" for x in _fm_cells(r)) + "</tr>" for r in file_map(reg)) + "</tbody></table></section>")
    a("<section id='read'><h2>How to read this</h2><ul>" + "".join(f"<li><span class='kind k{k}'>{k}</span> {reg['kind_def'][k]}</li>" for k in ("A", "B", "C")) + "</ul>")
    a(f"<p><b>Totals:</b> {h(totals_text(m))}</p>")
    a(f"<p><b>How the ranking works.</b> The coverage file shows, per county and signal, the share of rows that carry it. A cell is <b>thin</b> when it is under {LOW:g}%. "
      "For each card we count the thin cells it would fill in the counties it covers (a county with under 1,000 rows counts as a fraction). The checklist puts new leads first, then thin cells per minute of your time.</p></section>")
    a("<section id='decisions'><h2>Owner decisions in force</h2><ul>" + "".join(f"<li><b>{h(t)}</b> {x}</li>" for t, x in reg["decisions"]) + "</ul></section>")
    a("<section id='built'><h2>Built (computed from the repo)</h2><p class='small'>Deed readers come from the adapter registry; the other items are checked against files in the repo. Most new readers sit behind an on/off switch until you turn them on.</p><ul>"
      + "".join(f"<li><b>{h(b['title'])}</b> {b['text']}" + (f" <span class='small'>({h(b['check'])})</span>" if b["check"] else "") + "</li>" for b in m["built"]) + "</ul></section>")
    a("<section id='top15' class='part'><h2>What I need from you, in order</h2>")
    a("<table><thead><tr><th>#</th><th>Done</th><th>Task</th><th>Minutes</th><th>How often</th><th>Thin cells</th><th>Loads?</th><th>What it brings</th></tr></thead><tbody>")
    for i, t in enumerate(m["top"], 1):
        a(f"<tr><td>{i}</td><td>&#9744;</td><td><a href='#{anchor(t['card'])}'>{h(t['label'])}</a></td><td>{t['minutes']}</td><td>{h(t['often'])}</td><td>{h(t['cells'])}</td><td>{h(t['load'])}</td><td>{t['why']}</td></tr>")
    a("</tbody></table>")
    a(f"<p>Weekly items add up to about {sum(t['minutes'] for t in m['top'] if t['often'] == 'weekly')} minutes a week. Do them in order; stop when your time runs out.</p></section>")
    a("<section id='saving'><h2>How saving and loading works</h2>" + "".join(reg["saving_html"]) + "</section>")
    a(f"<section id='manual'><h2>What really stays manual</h2><p>{h(reg['manual_intro'])}</p></section>")
    live = [c for c in m["cards"] if not c.get("_demoted")]
    for grp in GROUP_TITLE:
        a(f"<section id='grp-{grp}' class='part'><h2>{h(GROUP_TITLE[grp])}</h2>")
        items = sorted([c for c in live if c["group"] == grp], key=lambda e: (-e["_per_hour"], e.get("minutes_month") or 0))
        if grp == "county":
            for st, title in (("NC", "North Carolina counties"), ("SC", "South Carolina counties")):
                a(f"<h2 style='font-size:13pt;border:0'>{title}</h2>")
                for e in [x for x in items if x.get("state") == st]:
                    a(html_card(e))
        else:
            for e in items:
                a(html_card(e))
        if grp == "sc":
            f = reg["foia"]
            a(f"<div class='card-wrap' id='{anchor('foia')}'><h3>Records requests (FOIA) <span class='kind kC'>not a wall: data not online</span></h3><p>{f['text']}</p><p><b>Time:</b> {h(f['minutes'])}.</p></div>")
        a("</section>")
    a(f"<section id='news' class='part'><h2>Every walled record in the source hunts</h2><p class='small'>Generated from every docs/new_sources_*.json ({m['news_count']} records). Only CAPTCHA, bot-check, login and paid records are listed. 'no card yet' means a person can follow the record's own manual step until a card is written.</p>")
    a("<table class='dense'><thead><tr><th>Kind</th><th>Source</th><th>Where</th><th>What a person does</th><th>Card</th></tr></thead><tbody>")
    for r in sorted(m["walled_news"], key=lambda r: (r["state"] or "~", r["county"] or "~", r["name"])):
        card = f"<a href='#{anchor(r['card'])}'>{h(m['by_id'][r['card']].get('short', r['card']))}</a>" if r["card"] else "no card yet"
        a(f"<tr><td>{KIND_OF[r['class']]} ({h(r['access_class'])})</td><td>{h(r['name'])}</td><td>{h(r['where'])}</td><td>{h((r['manual'] or r['price'])[:300])}</td><td>{card}</td></tr>")
    a("</tbody></table></section>")
    a(f"<section id='dormant'><h2>Scrapers switched off or blocked in the last run</h2><p class='small'>From {h(m['meta_src'])} (run {h(m['meta_time'] or 'unknown')}). A DORMANT reason that names a CAPTCHA, a bot check, a login or a payment is a wall; the rest are off for other reasons.</p>")
    a("<table class='dense'><thead><tr><th>Scraper</th><th>Why</th><th>Wall?</th></tr></thead><tbody>")
    for d in m["dormant"]:
        a(f"<tr><td>{h(d['source'])}</td><td>{h(d['reason'][:240])}</td><td>{h(('yes: ' + CLASS_WORD[d['class']]) if d['class'] in (CAPTCHA, BOT, LOGIN, PAID) else 'no')}</td></tr>")
    for b in m["blocked"]:
        a(f"<tr><td>{h(b['source'])}</td><td>{h(b['status'][:240])}</td><td>blocked in this run (may be temporary)</td></tr>")
    a("</tbody></table></section>")
    a(f"<section id='unknown'><h2>The UNKNOWN-county rows</h2><p>{h(unknown_text(m))}</p><ul>" + "".join(f"<li>{x}</li>" for x in reg["unknown_bullets"]) + "</ul></section>")
    a("<section id='counties' class='part'><h2>Every county at a glance</h2><p class='small'>Computed from the county matrix, the 'Person needed' tables of the platform cluster docs and the registered deed readers.</p>")
    for st in ("NC", "SC"):
        a(f"<h3>{'North Carolina' if st == 'NC' else 'South Carolina'}</h3>")
        a("<table class='county' style='table-layout:fixed'><colgroup><col style='width:11%'><col style='width:22%'><col style='width:15%'><col style='width:17%'><col style='width:25%'><col style='width:10%'></colgroup>"
          "<thead><tr><th>County, rows</th><th>Deeds (start page)</th><th>Estates</th><th>Tax bills (start page)</th><th>What a person does</th><th>Cards</th></tr></thead><tbody>")
        for c in sorted([c for c in m["counties"] if c["state"] == st], key=lambda c: c["key"]):
            cards = ", ".join(f"<a href='#{anchor(x)}'>{h(m['by_id'][x].get('short', x))}</a>" for x in sorted(m["cards_for"].get((st, c["key"]), [])) if not m["by_id"][x].get("_demoted"))
            s = c["sys"]
            a(f"<tr><td><b>{h(c['county'])}</b><br>{c['rows']:,} rows</td><td>{h(sys_word(s['rod'], 'rod', st))}<br><span class='url'>{h(s['rod']['url'])}</span></td>"
              f"<td>{h(sys_word(s['probate'], 'probate', st))}</td><td>{h(sys_word(s['tax'], 'tax', st))}<br><span class='url'>{h(s['tax']['url'])}</span></td>"
              f"<td>{h(fix_ml(c['manual_lane'], reg) or 'Nothing needed beyond the free sites.')}</td><td>{cards}</td></tr>")
        a("</tbody></table>")
    a("</section>")
    a("<section id='paid' class='part'><h2>Paid or attorney-only (type B): prices</h2><p class='small'>Prices come from our notes and are not re-checked; confirm before buying.</p>"
      "<table><thead><tr><th>What</th><th>Price</th><th>What it gets</th><th>Free alternative</th></tr></thead><tbody>"
      + "".join("<tr>" + "".join(f"<td>{x}</td>" for x in row) + "</tr>" for row in reg["paid"]) + "</tbody></table></section>")
    rows = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in row) + "</tr>" for row in reg["appendix_c"])
    rows += "".join(f"<tr><td>{c['name']}</td><td>{c['wall']}</td><td>Allowed (a plain click or terms only)</td></tr>" for c in m["cards"] if c.get("_demoted"))
    a(f"<section id='appxc'><h2>Appendix C: allowed, built or buildable (not walls)</h2><p class='small'>{h(reg['appendix_c_intro'])}</p>"
      f"<table><thead><tr><th>Source</th><th>The restriction</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></section>")
    a("<section id='absent'><h2>Data that does not exist anywhere</h2><ul>" + "".join(f"<li><b>{w}.</b> {why}</li>" for w, why in reg["does_not_exist"]) + "</ul></section>")
    a("<section id='stop'><h2>Stop doing these (already automatic or useless)</h2><ul>" + "".join(f"<li><b>{w}.</b> {why}</li>" for w, why in reg["stop"]) + "</ul></section>")
    gaps = list(reg["gaps"])
    if m["gap"].get("walled"):
        gaps.append("Gap matrix walled cells by reason (" + str(m["gap"].get("date")) + "): " + "; ".join(f"{k} {v}" for k, v in sorted(m["gap"]["walled"].items(), key=lambda x: -x[1])) + ".")
    a("<section id='gaps'><h2>Gaps and disagreements in our notes</h2><ul>" + "".join(f"<li>{g}</li>" for g in gaps) + "</ul></section>")
    a("<section id='sources'><h2>Where this came from</h2><ul>" + "".join(f"<li class='small'>{h(s)}</li>" for s in reg["sources_static"]) + "</ul></section>")
    a("</body></html>")
    return "\n".join(P)


def render_pdf(html_path: Path, pdf_path: Path) -> bool:
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome).exists():
        chrome = shutil.which("google-chrome") or shutil.which("chromium") or ""
    if not chrome:
        print("no Chrome found; PDF not rendered", file=sys.stderr)
        return False
    if pdf_path.exists():
        pdf_path.unlink()
    prof = tempfile.mkdtemp(prefix="owner_manual_chrome_")
    proc = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                             f"--user-data-dir={prof}", "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", f"file://{html_path}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        time.sleep(1)
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            time.sleep(2)
            break
        if proc.poll() is not None:
            break
    proc.kill()
    shutil.rmtree(prof, ignore_errors=True)
    return pdf_path.exists() and pdf_path.stat().st_size > 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--check", action="store_true", help="exit 1 and print what changed if the manual is stale")
    ap.add_argument("--offline", action="store_true", help="read docs/run_meta.json instead of the live dashboard copy")
    ap.add_argument("--run-meta", default=None, help="a run_meta.json to read instead")
    ap.add_argument("--coverage", default=None, help="coverage CSV (default: newest docs/gap_matrix/county_signal_coverage_<date>.csv)")
    ap.add_argument("--md", default=None)
    ap.add_argument("--html", default=str(DESKTOP / "Owner_Manual_Lanes_and_Walls.html"))
    ap.add_argument("--pdf", default=str(DESKTOP / "Owner_Manual_Lanes_and_Walls.pdf"))
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    model = build_model(repo, offline=args.offline, run_meta_path=Path(args.run_meta) if args.run_meta else None,
                        coverage_path=Path(args.coverage) if args.coverage else None)
    ledger = repo / "docs" / "owner_manual_inputs.json"
    fp = fingerprint(model)
    if args.check:
        if not ledger.exists():
            print("no previous build recorded (docs/owner_manual_inputs.json missing): run the builder")
            return 1
        old = json.loads(ledger.read_text())
        msgs = diff_fingerprint(old.get("fingerprint") or {}, fp)
        if msgs:
            print("the owner manual is stale; changed since the build of " + str(old.get("generated")) + ":")
            for x in msgs:
                print("  - " + x)
            print("rerun: uv run python scripts/build_owner_manual.py")
            return 1
        print(f"the owner manual is up to date (built {old.get('generated')} from commit {old.get('commit')})")
        return 0
    md_path = Path(args.md) if args.md else repo / "docs" / "OWNER_MANUAL_LANES.md"
    md_path.write_text(build_md(model))
    html_path = Path(args.html)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_html(model))
    pdf_ok = False
    if not args.no_pdf:
        pdf_ok = render_pdf(html_path.resolve(), Path(args.pdf))
    ledger.write_text(json.dumps({"generated": model["generated"], "commit": model["commit"], "fingerprint": fp,
                                  "inputs": model["inputs"], "run_meta": {"source": model["meta_src"], "run_time": model["meta_time"]}},
                                 indent=1) + "\n")
    n = counts(model)
    print(f"wrote {md_path} and {html_path}" + (f" and {args.pdf}" if pdf_ok else ""))
    print(f"cards A {n['A']} B {n['B']}; county systems needing a person {n['county_A']}, paid {n['county_B']}, built {n['county_built']}; "
          f"walled source-hunt records {len(model['walled_news'])}; DORMANT {len(model['dormant'])}; adapters {len(model['registry'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
