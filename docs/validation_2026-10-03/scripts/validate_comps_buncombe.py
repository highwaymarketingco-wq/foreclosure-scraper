"""Real, live, at-scale accuracy validator for `raw.comps` — the comparable-
sales array the HomeHarvest comp matcher (enrichment_comps.py) attaches to
every listing for ARV/valuation purposes. This has NEVER been directly
validated against live sold-property data before (prior sweeps on
2026-10-02 checked `assessed_value`/`market_value`, not `raw.comps`).

Scope: Buncombe County NC only, because Buncombe has a confirmed-working,
no-CAPTCHA parcel-resolution + sale-history source already shipped in this
repo: `src/foreclosure_scraper/assessor_cards/buncombe_nc.py` (county ArcGIS
for address->PIN resolution via plain httpx, then the Spatialest record-card
SPA rendered headless via scrapling.StealthyFetcher to pull the real
transfer history — the record-card JSON API 403s to direct httpx, this is
NOT a CAPTCHA, just a stealth-render requirement this repo already solved).

Method:
  1. Stream the board (`web_artifact._iter_board_records`), filter to
     Buncombe/NC rows carrying a non-empty `raw.comps` list.
  2. Random-sample up to 50 of those properties (fixed seed, reproducible).
  3. Flatten every comp entry (up to 3/property) from the sample. Dedupe by
     cleaned street address so an address shared by two subjects' comp lists
     is only fetched once live.
  4. For each unique comp address, resolve it to a real Buncombe parcel and
     pull its REAL recorded transfer history (saledate/saleprice/
     salesvalidity + building specs) via `buncombe_nc.fetch()`.
  5. Match the best real sale to the comp's CLAIMED sold_date, and compare:
     price (10% tolerance), sqft, beds, baths, year_built.
  6. Classify every comp instance (not just unique address) into a verdict,
     then recompute the property-level comp-derived ARV using ONLY verified-
     accurate comps vs. the board's own claimed comp values, in dollars.

Run serially (concurrency=1) by deliberate choice: this Mac is memory-
constrained (8GB, already observed at ~4.2GB swap / ~54MB free RSS at launch
time) and each fetch spins up a real headless browser (scrapling
StealthyFetcher/Camoufox) — stacking several at once risks the exact
kernel-panic failure mode already seen on this machine when heavy processes
are stacked. ~13-20s per unique address serially is an acceptable tradeoff
for a ~30-45 min one-shot validation run.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper import web_artifact
from foreclosure_scraper.assessor_cards import buncombe_nc

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")
N_PROPERTIES = 50
SEED = 20261004
PRICE_TOL = 0.10
SQFT_TOL = 0.10
MAX_DATE_GAP_DAYS = 200  # how far the matched real sale may sit from the claimed sold_date
PER_FETCH_TIMEOUT_S = 100

RESULTS_PATH = Path(
    "/private/tmp/claude-502/-Users-cashhigh-Desktop/"
    "b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad/comps_validation_results.json"
)

_MULTI_PARCEL_RE = re.compile(r"^\s*\d+\s+(and|&)\s+\d+\s", re.I)


def _collect_candidates() -> list[dict]:
    out = []
    for rec in web_artifact._iter_board_records(DOCS):
        if (rec.get("county") or "").strip() != "Buncombe":
            continue
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        raw = rec.get("raw") or {}
        comps = raw.get("comps")
        if not isinstance(comps, list) or not comps:
            continue
        out.append({
            "parcel_id": rec.get("parcel_id"),
            "owner_name": rec.get("owner_name"),
            "street_address": rec.get("street_address"),
            "living_sqft": rec.get("living_sqft"),
            "comp_median_ppsf": raw.get("comp_median_ppsf"),
            "market_value": rec.get("market_value") or rec.get("assessed_value"),
            "comps": comps,
        })
    return out


def _clean_address(addr: str) -> tuple[str, bool]:
    """Returns (cleaned_street, is_multi_parcel). Multi-parcel addresses
    ("78 and 80 Taylor St") are flagged, not guessed at."""
    a = (addr or "").strip()
    if "," in a:
        a = a.split(",")[0].strip()
    is_multi = bool(_MULTI_PARCEL_RE.match(a))
    return a, is_multi


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[: len(fmt) + 2].strip()[: len(s)], fmt)
        except ValueError:
            pass
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            return None
    return None


async def _fetch_address(addr: str) -> dict:
    """Live-fetch one address against Buncombe county GIS + Spatialest record
    card. Returns a plain-dict summary (CardResult isn't JSON-serializable
    directly)."""
    li = SimpleNamespace(parcel_id=None, street_address=addr)
    t0 = time.time()
    try:
        res = await asyncio.wait_for(buncombe_nc.fetch(li), timeout=PER_FETCH_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "elapsed_s": round(time.time() - t0, 1)}
    if res is None:
        # Not an error -- the fetch pipeline ran fine, it just found no real
        # parcel/card match for this address (genuinely nonexistent comp, or
        # unresolvable address). `ok=True` here means "no exception", distinct
        # from `found=True` meaning "a real parcel+card was located".
        return {"ok": True, "found": False, "elapsed_s": round(time.time() - t0, 1)}
    return {
        "ok": True,
        "found": True,
        "elapsed_s": round(time.time() - t0, 1),
        "source_url": res.source_url,
        "living_sqft": res.living_sqft,
        "year_built": res.year_built,
        "bedrooms": res.bedrooms,
        "bathrooms": res.bathrooms,
        "market_value": res.market_value,
        "sales": [s.as_dict() for s in res.sales],
    }


def _best_sale_match(sales: list[dict], claimed_date: datetime | None) -> dict | None:
    """Pick the real recorded sale closest to the comp's claimed sold_date.
    Falls back to the most recent sale if no claimed date is available."""
    if not sales:
        return None
    dated = []
    for s in sales:
        d = _parse_date(s.get("sale_date"))
        dated.append((d, s))
    if claimed_date is not None:
        with_date = [(d, s) for d, s in dated if d is not None]
        if with_date:
            best = min(with_date, key=lambda ds: abs((ds[0] - claimed_date).days))
            gap = abs((best[0] - claimed_date).days)
            return {**best[1], "_date_gap_days": gap}
    # fall back: most recent sale
    with_date = [(d, s) for d, s in dated if d is not None]
    if with_date:
        d, s = max(with_date, key=lambda ds: ds[0])
        gap = abs((d - claimed_date).days) if claimed_date else None
        return {**s, "_date_gap_days": gap}
    return {**dated[0][1], "_date_gap_days": None}


def _pct_err(real: float | None, claimed: float | None) -> float | None:
    if real is None or claimed is None or real == 0:
        return None
    return abs(real - claimed) / real


def _classify_comp(comp: dict, fetch_result: dict, is_multi: bool) -> dict:
    out = {
        "claimed": {
            "address": comp.get("address"),
            "sold_price": comp.get("sold_price"),
            "sold_date": comp.get("sold_date"),
            "sqft": comp.get("sqft"),
            "beds": comp.get("beds"),
            "baths": comp.get("baths"),
            "year_built": comp.get("year_built"),
            "match_quality": comp.get("match_quality"),
        },
    }
    if is_multi:
        out["verdict"] = "unparseable_multi_parcel_address"
        out["verified_accurate"] = False
        return out

    if not fetch_result.get("ok"):
        out["verdict"] = "fetch_error"
        out["fetch_error"] = fetch_result.get("error")
        out["verified_accurate"] = False
        return out
    if not fetch_result.get("found"):
        out["verdict"] = "not_found_no_real_parcel_match"
        out["verified_accurate"] = False
        return out

    sales = fetch_result.get("sales") or []
    if not sales:
        out["verdict"] = "found_parcel_no_sale_history"
        out["verified_accurate"] = False
        out["real"] = {
            "living_sqft": fetch_result.get("living_sqft"),
            "year_built": fetch_result.get("year_built"),
            "bedrooms": fetch_result.get("bedrooms"),
            "bathrooms": fetch_result.get("bathrooms"),
        }
        return out

    claimed_date = _parse_date(comp.get("sold_date"))
    match = _best_sale_match(sales, claimed_date)
    real_price = match.get("price") if match else None
    date_gap = match.get("_date_gap_days") if match else None

    price_err = _pct_err(real_price, comp.get("sold_price"))
    sqft_err = _pct_err(fetch_result.get("living_sqft"), comp.get("sqft"))
    beds_match = (
        fetch_result.get("bedrooms") is not None and comp.get("beds") is not None
        and abs(fetch_result["bedrooms"] - comp["beds"]) < 0.01
    )
    baths_match = (
        fetch_result.get("bathrooms") is not None and comp.get("baths") is not None
        and abs(fetch_result["bathrooms"] - comp["baths"]) <= 0.5
    )
    year_match = (
        fetch_result.get("year_built") is not None and comp.get("year_built") is not None
        and abs(fetch_result["year_built"] - comp["year_built"]) <= 1
    )

    out["real"] = {
        "matched_sale": match,
        "living_sqft": fetch_result.get("living_sqft"),
        "year_built": fetch_result.get("year_built"),
        "bedrooms": fetch_result.get("bedrooms"),
        "bathrooms": fetch_result.get("bathrooms"),
        "price_error_pct": round(price_err * 100, 1) if price_err is not None else None,
        "sqft_error_pct": round(sqft_err * 100, 1) if sqft_err is not None else None,
        "beds_match": beds_match,
        "baths_match": baths_match,
        "year_match": year_match,
        "date_gap_days": date_gap,
    }

    date_ok = date_gap is None or date_gap <= MAX_DATE_GAP_DAYS
    price_ok = price_err is not None and price_err <= PRICE_TOL
    out["verified_accurate"] = bool(price_ok and date_ok)
    if real_price is None:
        out["verdict"] = "sale_found_no_price_on_record"
    elif not date_ok:
        out["verdict"] = "sale_too_far_from_claimed_date"
    elif price_ok:
        out["verdict"] = "price_verified_accurate"
    else:
        out["verdict"] = "price_wrong"
    return out


async def main() -> None:
    print("Collecting Buncombe/NC candidates with non-empty raw.comps...", file=sys.stderr)
    candidates = _collect_candidates()
    print(f"Total candidates: {len(candidates)}", file=sys.stderr)

    random.seed(SEED)
    sample = random.sample(candidates, min(N_PROPERTIES, len(candidates)))
    print(f"Sampled {len(sample)} properties", file=sys.stderr)

    # Flatten + dedupe by cleaned address
    addr_cache: dict[str, dict] = {}
    unique_addrs: list[tuple[str, bool]] = []
    for prop in sample:
        for comp in prop["comps"][:3]:
            cleaned, is_multi = _clean_address(comp.get("address") or "")
            key = cleaned.lower()
            comp["_clean_addr"] = cleaned
            comp["_is_multi"] = is_multi
            if key and not is_multi and key not in addr_cache:
                addr_cache[key] = None  # placeholder
                unique_addrs.append((cleaned, key))

    print(f"Unique resolvable comp addresses to fetch live: {len(unique_addrs)}", file=sys.stderr)

    for i, (cleaned, key) in enumerate(unique_addrs, 1):
        t0 = time.time()
        res = await _fetch_address(cleaned)
        addr_cache[key] = res
        dt = time.time() - t0
        print(
            f"[{i}/{len(unique_addrs)}] {cleaned!r} -> "
            f"{'FOUND' if res.get('found') else 'not found'} "
            f"({dt:.1f}s, sales={len(res.get('sales') or [])})",
            file=sys.stderr,
        )

    # Classify every comp instance (not deduped) and build property-level results
    property_results = []
    for prop in sample:
        comp_results = []
        for comp in prop["comps"][:3]:
            key = (comp.get("_clean_addr") or "").lower()
            is_multi = comp.get("_is_multi", False)
            fetch_result = addr_cache.get(key) or {"ok": False, "found": False}
            comp_results.append(_classify_comp(comp, fetch_result, is_multi))
        property_results.append({
            "parcel_id": prop["parcel_id"],
            "owner_name": prop["owner_name"],
            "street_address": prop["street_address"],
            "living_sqft": prop["living_sqft"],
            "comp_median_ppsf": prop["comp_median_ppsf"],
            "board_market_value": prop["market_value"],
            "comps": comp_results,
        })

    # ---- Aggregate stats --------------------------------------------------
    all_comps = [c for p in property_results for c in p["comps"]]
    n_total = len(all_comps)
    n_unparseable = sum(1 for c in all_comps if c["verdict"] == "unparseable_multi_parcel_address")
    n_fetch_error = sum(1 for c in all_comps if c["verdict"] == "fetch_error")
    n_not_found = sum(1 for c in all_comps if c["verdict"] == "not_found_no_real_parcel_match")
    n_found_no_sales = sum(1 for c in all_comps if c["verdict"] == "found_parcel_no_sale_history")
    n_price_wrong = sum(1 for c in all_comps if c["verdict"] == "price_wrong")
    n_date_mismatch = sum(1 for c in all_comps if c["verdict"] == "sale_too_far_from_claimed_date")
    n_no_price_on_record = sum(1 for c in all_comps if c["verdict"] == "sale_found_no_price_on_record")
    n_verified = sum(1 for c in all_comps if c["verified_accurate"])

    checkable = [c for c in all_comps if c["verdict"] in (
        "price_verified_accurate", "price_wrong", "sale_too_far_from_claimed_date")]
    n_checkable = len(checkable)

    # ---- Dollar-impact: property-level comp-derived ARV -------------------
    per_property_dollar = []
    for p in property_results:
        board_prices = [c["claimed"]["sold_price"] for c in p["comps"] if c["claimed"].get("sold_price")]
        verified_real_prices = [
            c["real"]["matched_sale"].get("price")
            for c in p["comps"]
            if c.get("verified_accurate") and c.get("real") and c["real"].get("matched_sale")
            and c["real"]["matched_sale"].get("price")
        ]
        board_avg = sum(board_prices) / len(board_prices) if board_prices else None
        verified_avg = sum(verified_real_prices) / len(verified_real_prices) if verified_real_prices else None
        per_property_dollar.append({
            "parcel_id": p["parcel_id"],
            "board_comp_avg": round(board_avg, 0) if board_avg else None,
            "verified_comp_avg": round(verified_avg, 0) if verified_avg else None,
            "n_board_comps": len(board_prices),
            "n_verified_comps": len(verified_real_prices),
        })

    props_with_board_avg = [d for d in per_property_dollar if d["board_comp_avg"] is not None]
    props_with_verified_avg = [d for d in per_property_dollar if d["verified_comp_avg"] is not None]
    props_zero_verified = [d for d in per_property_dollar if d["n_verified_comps"] == 0]

    mean_board_avg = (
        sum(d["board_comp_avg"] for d in props_with_board_avg) / len(props_with_board_avg)
        if props_with_board_avg else None
    )
    mean_verified_avg = (
        sum(d["verified_comp_avg"] for d in props_with_verified_avg) / len(props_with_verified_avg)
        if props_with_verified_avg else None
    )

    both = [d for d in per_property_dollar if d["board_comp_avg"] is not None and d["verified_comp_avg"] is not None]
    deltas = [d["verified_comp_avg"] - d["board_comp_avg"] for d in both]
    pct_deltas = [
        (d["verified_comp_avg"] - d["board_comp_avg"]) / d["board_comp_avg"]
        for d in both if d["board_comp_avg"]
    ]

    summary = {
        "n_properties_sampled": len(sample),
        "n_total_candidates_buncombe_with_comps": len(candidates),
        "n_total_comp_entries_checked": n_total,
        "n_unique_addresses_fetched_live": len(unique_addrs),
        "comp_verdict_counts": {
            "unparseable_multi_parcel_address": n_unparseable,
            "fetch_error": n_fetch_error,
            "not_found_no_real_parcel_match": n_not_found,
            "found_parcel_no_sale_history": n_found_no_sales,
            "sale_found_no_price_on_record": n_no_price_on_record,
            "sale_too_far_from_claimed_date": n_date_mismatch,
            "price_wrong": n_price_wrong,
            "price_verified_accurate": n_verified,
        },
        "pct_verified_accurate_of_total": round(100 * n_verified / n_total, 1) if n_total else None,
        "pct_not_found_of_total": round(100 * n_not_found / n_total, 1) if n_total else None,
        "pct_price_wrong_of_checkable": round(100 * n_price_wrong / n_checkable, 1) if n_checkable else None,
        "pct_verified_of_checkable": round(100 * n_verified / n_checkable, 1) if n_checkable else None,
        "n_checkable_had_both_price_and_date": n_checkable,
        "dollar_impact": {
            "n_properties_with_board_comp_avg": len(props_with_board_avg),
            "n_properties_with_verified_comp_avg": len(props_with_verified_avg),
            "n_properties_zero_verified_comps": len(props_zero_verified),
            "pct_properties_zero_verified_comps_of_sampled": round(
                100 * len(props_zero_verified) / len(sample), 1) if sample else None,
            "mean_board_comp_avg_dollars": round(mean_board_avg, 0) if mean_board_avg else None,
            "mean_verified_comp_avg_dollars": round(mean_verified_avg, 0) if mean_verified_avg else None,
            "mean_delta_dollars_verified_minus_board_matched_pairs": (
                round(sum(deltas) / len(deltas), 0) if deltas else None
            ),
            "median_delta_dollars_matched_pairs": (
                round(sorted(deltas)[len(deltas) // 2], 0) if deltas else None
            ),
            "mean_pct_delta_matched_pairs": (
                round(100 * sum(pct_deltas) / len(pct_deltas), 1) if pct_deltas else None
            ),
            "n_matched_pairs_board_and_verified_both_present": len(both),
        },
    }

    output = {
        "summary": summary,
        "per_property_dollar_impact": per_property_dollar,
        "property_results": property_results,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nWrote results to {RESULTS_PATH}", file=sys.stderr)
    print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
