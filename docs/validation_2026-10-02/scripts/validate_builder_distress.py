"""Live Buncombe ROD validator for board-flagged `builder_distress` rows.

For a sample of board rows where raw.builder_distress is truthy (NC/Buncombe),
query the LIVE Buncombe Register of Deeds (Cott eSearch v4, same vendor/protocol
already live-verified in foreclosure_scraper.rod.aumentum) by the board's
resolved owner name, and classify what's actually recorded:
  (a) genuine mechanic's/contractor's lien or claim of nonpayment -> REAL DISTRESS
  (b) only a routine "Appointment of Lien Agent"-type signal and/or ordinary
      deed/deed-of-trust/satisfaction activity near the filing date -> ROUTINE
  (c) nothing found under that name at all -> NO RECORD (stale/wrong match)

Reuses rod.aumentum's live-verified GET+POST handshake (session-cookie based,
curl_cffi chrome impersonation, no CAPTCHA, no login wall on Buncombe) but
parses the RAW vendor "Type" column text (not normalize_doc_type's collapsed
bucket) because normalize_doc_type() collapses both "Notice of Appointment of
Lien Agent" and "Claim of Lien" into the same "lien" bucket -- exactly the
distinction this check needs to preserve.
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
OUT_PATH = Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad/builder_distress_validation_results.json")

BASE = aumentum.AUMENTUM_COUNTIES[("NC", "Buncombe")]
SAMPLE_N = 50
SEED = 20261002

# Raw vendor "Type" text keyword rules (checked BEFORE normalize_doc_type bucketing).
_AGENT_RE = re.compile(r"LIEN\s*AGENT", re.I)
_GENUINE_LIEN_RE = re.compile(r"CLAIM\s*OF\s*LIEN|MECHANIC|NOTICE\s*OF\s*LIEN|LABOR\s*(AND|&)\s*MATERIAL", re.I)
_BARE_LIEN_RE = re.compile(r"\bLIEN\b", re.I)


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
    """Same grid/row selectors as aumentum._parse_instruments_grid, but keeps the
    RAW vendor Type-column text instead of collapsing it via normalize_doc_type."""
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


async def search_raw_by_name(name: str, max_rows: int = 200) -> list[dict]:
    """Same handshake as aumentum._search_by_name_at, but returns RAW grid rows
    (vendor's own Type text preserved) instead of normalized RodDocs."""
    if not name or not name.strip():
        return []
    url = f"{BASE}/SrchName.aspx"
    last, first = aumentum._split_name(name.strip())
    if not last:
        return []
    try:
        from curl_cffi.requests import AsyncSession
    except Exception as exc:  # noqa: BLE001
        print(f"  curl_cffi unavailable: {exc}")
        return []
    try:
        async with AsyncSession(verify=False, impersonate="chrome") as s:
            r = await s.get(url, allow_redirects=True, timeout=30)
            final = str(r.url)
            if aumentum._is_login_wall(final):
                print(f"  LOGIN WALL on {final} (unexpected for Buncombe)")
                return []
            r2 = await s.post(final, data=aumentum._name_body(last, first),
                               headers={"Referer": final}, allow_redirects=True, timeout=60)
            rows = parse_raw_grid(r2.text)
            if not rows and re.search(r"allowable results|maximum number", r2.text or "", re.I):
                from datetime import datetime
                today = datetime.now().strftime("%m/%d/%Y")
                r3 = await s.post(final, data=aumentum._name_body(last, first, "01/01/2000", today),
                                   headers={"Referer": final}, allow_redirects=True, timeout=60)
                rows = parse_raw_grid(r3.text)
    except Exception as exc:  # noqa: BLE001
        print(f"  search_raw_by_name FAILED for {name!r}: {type(exc).__name__}: {str(exc)[:200]}")
        return []
    return rows[:max_rows]


def classify(rows: list[dict], surname: str) -> tuple[str, list[dict]]:
    """Returns (category, evidence_rows) where category is one of:
    'genuine_lien' (a), 'routine' (b), 'no_record' (c)."""
    if not rows:
        return "no_record", []
    surname_u = surname.upper().strip()
    # Loose name-match filter: keep rows where the searched surname actually
    # appears in grantor or grantee (the vendor's "All Matches" search can be
    # broad on common surnames).
    matched = [r for r in rows
               if surname_u and (surname_u in r["grantor"].upper() or surname_u in r["grantee"].upper())]
    pool = matched if matched else rows
    genuine = [r for r in pool if _GENUINE_LIEN_RE.search(r["type_raw"])
               or (_BARE_LIEN_RE.search(r["type_raw"]) and not _AGENT_RE.search(r["type_raw"]))]
    if genuine:
        return "genuine_lien", genuine
    if not matched:
        return "no_record", []
    return "routine", matched[:8]


async def main():
    pool = json.loads(POOL_PATH.read_text())
    random.seed(SEED)
    sample = random.sample(pool, min(SAMPLE_N, len(pool)))
    print(f"Pool size: {len(pool)} | sampling: {len(sample)}")

    results = []
    counts = {"genuine_lien": 0, "routine": 0, "no_record": 0, "query_failed": 0}
    cache: dict[str, list[dict]] = {}

    for i, row in enumerate(sample, 1):
        owner = (row.get("owner_name") or "").strip()
        addr = row.get("street_address")
        print(f"[{i}/{len(sample)}] {owner!r} @ {addr!r}")
        if not owner:
            results.append({**row, "rod_category": "query_failed", "rod_reason": "no owner_name"})
            counts["query_failed"] += 1
            continue
        surname = aumentum._split_name(owner)[0]
        if owner not in cache:
            try:
                cache[owner] = await search_raw_by_name(owner)
            except Exception as exc:  # noqa: BLE001
                print(f"  EXCEPTION: {exc}")
                cache[owner] = None
            await asyncio.sleep(0.4)
        rows = cache[owner]
        if rows is None:
            results.append({**row, "rod_category": "query_failed", "rod_reason": "exception"})
            counts["query_failed"] += 1
            continue
        category, evidence = classify(rows, surname)
        print(f"  -> {category} ({len(rows)} raw rows, {len(evidence)} evidence rows)")
        counts[category] += 1
        results.append({
            **row,
            "rod_category": category,
            "rod_raw_row_count": len(rows),
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
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))

    OUT_PATH.write_text(json.dumps({"summary": summary, "results": results}, indent=2, default=str))
    print(f"\nwrote -> {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
