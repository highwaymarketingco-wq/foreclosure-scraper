"""v2: fixes a name-order bug in v1 (which reused rod.aumentum._split_name's
GIS surname-first heuristic -- wrong for these rows, whose owner_name is
mostly the LiensNC 'Owner' column in plain human First Last order, not GIS
Last-First order). v2 tries BOTH token orders as surname candidates, plus the
full string for entity names, unions results, and matches evidence against
ANY candidate token -- removing the guess instead of just re-guessing.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")

from foreclosure_scraper.rod import aumentum  # noqa: E402
from selectolax.parser import HTMLParser  # noqa: E402

SCRATCH = Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad")
POOL_PATH = SCRATCH / "builder_distress_pool.json"
OUT_PATH = SCRATCH / "builder_distress_validation_results.json"

BASE = aumentum.AUMENTUM_COUNTIES[("NC", "Buncombe")]
SAMPLE_N = 50
SEED = 20261002

_AGENT_RE = re.compile(r"LIEN\s*AGENT", re.I)
_GENUINE_LIEN_RE = re.compile(r"CLAIM\s*OF\s*LIEN|MECHANIC|NOTICE\s*OF\s*LIEN|LABOR\s*(AND|&)\s*MATERIAL", re.I)
_BARE_LIEN_RE = re.compile(r"\bLIEN\b", re.I)

_ENTITY_RE = re.compile(
    r"\b(LLC|L\.L\.C|INC|CORP|CO\.?|LP|LLP|COMPANY|CONSTRUCTION|HOMES|HOMEBUILD|BUILDERS?|"
    r"PARTNERSHIP|SERVICES|ASSOCIATES|DEPARTMENT|SCHOOL|BOARD OF EDUCATION|CONFERENCE|CHURCH|"
    r"ADVENTISTS?|PROPERTIES|GRADING|HEADQUARTERS|COUNTY|TRUST\b|FOUNDATION|MINISTR|CORP\.?)\b",
    re.I,
)


def _direct_tds(tr):
    out = []
    ch = tr.child
    while ch is not None:
        if ch.tag == "td":
            out.append(ch)
        ch = ch.next
    return out


def _cell(tds, i):
    if i < 0 or i >= len(tds):
        return ""
    return " ".join(tds[i].text(separator=" ", strip=True).split())


def parse_raw_grid(html: str) -> list[dict]:
    out = []
    if not html:
        return out
    tree = HTMLParser(html)
    grid = tree.css_first(f"table#{aumentum._GRID_ID}")
    if grid is None:
        for t in tree.css("table"):
            tid = t.attributes.get("id") or ""
            if tid.endswith("cpgvInstruments"):
                grid = t
                break
    if grid is None:
        return out
    for tr in grid.css(aumentum._ROW_SEL):
        tds = _direct_tds(tr)
        if len(tds) < 6:
            continue
        dtype_raw = _cell(tds, 3)
        grantor = _cell(tds, 4)
        grantee = _cell(tds, 5)
        if not (dtype_raw or grantor or grantee):
            continue
        out.append({
            "date_filed": _cell(tds, 1),
            "index": _cell(tds, 2),
            "type_raw": dtype_raw,
            "grantor": grantor,
            "grantee": grantee,
            "description": _cell(tds, 6),
            "file_number": _cell(tds, 7),
            "book_page": _cell(tds, 8),
        })
    return out


async def _raw_search(session, final_url: str, surname: str, given: str) -> list[dict]:
    r = await session.post(final_url, data=aumentum._name_body(surname, given),
                            headers={"Referer": final_url}, allow_redirects=True, timeout=60)
    rows = parse_raw_grid(r.text)
    if not rows and re.search(r"allowable results|maximum number", r.text or "", re.I):
        from datetime import datetime
        today = datetime.now().strftime("%m/%d/%Y")
        r2 = await session.post(final_url, data=aumentum._name_body(surname, given, "01/01/2000", today),
                                 headers={"Referer": final_url}, allow_redirects=True, timeout=60)
        rows = parse_raw_grid(r2.text)
    return rows


def candidate_name_pairs(name: str) -> tuple[list[tuple[str, str]], list[str], bool]:
    """Returns (list of (surname, given) pairs to try, list of all tokens to
    match evidence against, is_entity)."""
    name = (name or "").strip()
    if not name:
        return [], [], False
    primary = re.split(r"[,;]", name)[0].strip()  # first owner only
    is_entity = bool(_ENTITY_RE.search(name))
    if is_entity:
        return [(primary, "")], [t for t in re.split(r"\W+", primary) if len(t) > 2], True
    tokens = [t for t in primary.split() if t]
    all_tokens = [t for t in re.split(r"[\s,;]+", name) if len(t) > 1]
    if len(tokens) == 0:
        return [], [], False
    if len(tokens) == 1:
        return [(tokens[0], "")], all_tokens, False
    # Try BOTH orders: (first_tok, last_tok) treated as (surname, given), and
    # (last_tok, first_tok). Covers both GIS Last-First and human First-Last.
    pairs = [(tokens[0], tokens[1]), (tokens[-1], tokens[0])]
    # Dedupe
    seen = set()
    uniq_pairs = []
    for p in pairs:
        if p not in seen:
            seen.add(p)
            uniq_pairs.append(p)
    return uniq_pairs, all_tokens, False


def classify(rows: list[dict], match_tokens: list[str]) -> tuple[str, list[dict]]:
    if not rows:
        return "no_record", []
    toks_u = [t.upper() for t in match_tokens if len(t) > 1]
    def row_matches(r):
        blob = (r["grantor"] + " " + r["grantee"]).upper()
        return any(t in blob for t in toks_u)
    matched = [r for r in rows if row_matches(r)]
    pool = matched if matched else rows
    genuine = [r for r in pool if _GENUINE_LIEN_RE.search(r["type_raw"])
               or (_BARE_LIEN_RE.search(r["type_raw"]) and not _AGENT_RE.search(r["type_raw"]))]
    if genuine:
        return "genuine_lien", genuine
    if not matched:
        return "no_record", []
    return "routine", matched[:10]


async def search_owner(session, final_url: str, owner_name: str):
    pairs, match_tokens, is_entity = candidate_name_pairs(owner_name)
    if not pairs:
        return [], []
    all_rows = []
    seen_keys = set()
    for surname, given in pairs:
        try:
            rows = await _raw_search(session, final_url, surname, given)
        except Exception as exc:  # noqa: BLE001
            print(f"    query failed ({surname!r},{given!r}): {type(exc).__name__}: {str(exc)[:150]}")
            continue
        for r in rows:
            key = (r["book_page"], r["type_raw"], r["grantor"], r["grantee"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_rows.append(r)
        await asyncio.sleep(0.3)
    return all_rows, match_tokens


async def main():
    pool = json.loads(POOL_PATH.read_text())
    random.seed(SEED)
    sample = random.sample(pool, min(SAMPLE_N, len(pool)))
    print(f"Pool size: {len(pool)} | sampling: {len(sample)}")

    from curl_cffi.requests import AsyncSession

    results = []
    counts = {"genuine_lien": 0, "routine": 0, "no_record": 0, "query_failed": 0}
    cache: dict[str, tuple] = {}

    async with AsyncSession(verify=False, impersonate="chrome") as s:
        boot = await s.get(f"{BASE}/SrchName.aspx", allow_redirects=True, timeout=30)
        final_url = str(boot.url)
        if aumentum._is_login_wall(final_url):
            print("LOGIN WALL -- aborting")
            return

        for i, row in enumerate(sample, 1):
            owner = (row.get("owner_name") or "").strip()
            addr = row.get("street_address")
            print(f"[{i}/{len(sample)}] {owner!r} @ {addr!r}")
            if not owner:
                results.append({**row, "rod_category": "query_failed", "rod_reason": "no owner_name"})
                counts["query_failed"] += 1
                continue
            if owner not in cache:
                try:
                    cache[owner] = await search_owner(s, final_url, owner)
                except Exception as exc:  # noqa: BLE001
                    print(f"  EXCEPTION: {exc}")
                    cache[owner] = None
            entry = cache[owner]
            if entry is None:
                results.append({**row, "rod_category": "query_failed", "rod_reason": "exception"})
                counts["query_failed"] += 1
                continue
            rows, match_tokens = entry
            category, evidence = classify(rows, match_tokens)
            print(f"  -> {category} ({len(rows)} raw rows via {len(match_tokens)} tokens, {len(evidence)} evidence)")
            counts[category] += 1
            results.append({
                **row,
                "rod_category": category,
                "rod_raw_row_count": len(rows),
                "rod_match_tokens": match_tokens,
                "rod_evidence": evidence,
            })

    n_checked = len(sample) - counts["query_failed"]
    summary = {
        "pool_size_total": len(pool),
        "n_sampled": len(sample),
        "n_query_failed": counts["query_failed"],
        "n_successfully_checked": n_checked,
        "n_genuine_lien": counts["genuine_lien"],
        "n_routine": counts["routine"],
        "n_no_record": counts["no_record"],
        "pct_genuine_lien": round(100 * counts["genuine_lien"] / n_checked, 1) if n_checked else None,
        "pct_routine": round(100 * counts["routine"] / n_checked, 1) if n_checked else None,
        "pct_no_record": round(100 * counts["no_record"] / n_checked, 1) if n_checked else None,
    }
    print("\n=== SUMMARY (v2, fixed name-order) ===")
    print(json.dumps(summary, indent=2))
    OUT_PATH.write_text(json.dumps({"summary": summary, "results": results}, indent=2, default=str))
    print(f"\nwrote -> {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
