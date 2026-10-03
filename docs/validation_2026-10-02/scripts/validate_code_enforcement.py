#!/usr/bin/env python3
"""Henderson County NC code-enforcement / vacancy signal validator.

Streams the real board (never list()-ing it — the board is 2.5GB+/219k rows and
the project's own memory-safety notes forbid materializing it), collects every
Henderson County, NC row carrying a code-enforcement or vacancy-class signal,
takes a random sample of up to 60, and cross-checks each one against the LIVE
public ArcGIS source(s) the board's own scrapers read from:

  - Henderson County's own Ordinance Violations Tracking dashboard
    (OVT_PublicDashboard_View/FeatureServer/1) — this is the feed behind
    `counties_nc.henderson_code_violations`, and the one implicated in the known
    202 Arbor Ln false positive (a "Zoning" case surfaced as a vacant/distress
    signal). Classified live by `violationType` (Zoning vs genuinely
    vacancy-adjacent: Vacant/Condemned/Nuisance/Minimum Housing) and by
    `dispositionStatus` (open vs closed/resolved), using the SAME closed-status
    regex the production scraper uses (imported, not re-implemented).

  - City of Hendersonville's own vacant-structures register
    (VACANT_STRUCTURES_7_24_24/FeatureServer/0) — this is the feed behind
    `counties_nc.hendersonville_vacant_structures`. It is a code officer's
    direct on-site confirmation (OCCUPIED/BOARDED_UP/CONDEMNED columns), not a
    generic violation-type bucket, so there is no "Zoning-style" miscategorization
    risk here; the live check instead asks whether the record is still standing
    on the register and whether OCCUPIED/CONDEMNED status has changed since the
    board snapshot (staleness).

Both endpoints are free, public, anonymous ArcGIS REST FeatureServers (no auth,
no CAPTCHA) — fetched with foreclosure_scraper.http_client.get_text(url,
impersonate=True), never the interactive browser, so this scales.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")

from foreclosure_scraper.web_artifact import _iter_board_records  # noqa: E402
from foreclosure_scraper.http_client import get_text  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.henderson_code_violations import (  # noqa: E402
    is_closed as ovt_is_closed,
    _norm_pin as ovt_norm_pin,
    LAYER as OVT_LAYER,
)
from foreclosure_scraper.scrapers.counties_nc.hendersonville_vacant_structures import (  # noqa: E402
    LAYER as VSR_LAYER,
)

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")
OUT_PATH = Path(
    "/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/"
    "scratchpad/code_enforcement_validation_results.json"
)
SAMPLE_SIZE = 60
SEED = 20261002  # fixed seed for reproducibility

OVT_QUERY_URL = OVT_LAYER + "/query"
VSR_QUERY_URL = VSR_LAYER + "/query"
OVT_OUT_FIELDS = "OBJECTID,caseID,complaintID,dateReceived,parcelOwner,address,violationType,PIN,dispositionStatus,dispositionDate"
VSR_OUT_FIELDS = "FID,DATE,ADDRESS,OCCUPIED,BOARDED_UP,CONDEMNED,DELINQUENT_TAX,UTILITIES,NOV___CONTACT_LETTER_SENT,CODE_COLOR,NOTES"

# Per the task's own wording: genuinely vacancy-adjacent violation types vs
# everything else (Zoning, Solid Waste, Junkyard, Vehicle/Manufactured-Home
# Graveyard, ...) which is a different category being bucketed as distress.
VACANCY_ADJACENT_RE = re.compile(r"(vacant|condemn|nuisance|minimum\s*housing)", re.I)


def _sql_quote(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


async def _arcgis_query(url: str, where: str, out_fields: str) -> dict:
    qs = urlencode({
        "where": where,
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
    })
    full_url = f"{url}?{qs}"
    text = await get_text(full_url, impersonate=True, timeout=30.0)
    data = json.loads(text)
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"ArcGIS error: {str(data['error'])[:300]}")
    return data


async def query_ovt_by_pin_or_address(pin: str | None, address: str | None) -> dict:
    if pin:
        where = f"PIN = {_sql_quote(pin)}"
        data = await _arcgis_query(OVT_QUERY_URL, where, OVT_OUT_FIELDS)
        feats = data.get("features") or []
        if feats:
            return {"matched_by": "pin", "where": where, "features": feats}
    if address:
        addr_u = address.upper().strip()
        where = f"UPPER(address) LIKE {_sql_quote('%' + addr_u + '%')}"
        data = await _arcgis_query(OVT_QUERY_URL, where, OVT_OUT_FIELDS)
        feats = data.get("features") or []
        return {"matched_by": "address" if feats else "none", "where": where, "features": feats}
    return {"matched_by": "none", "where": None, "features": []}


async def query_vsr_by_address(address: str | None) -> dict:
    if not address:
        return {"matched_by": "none", "where": None, "features": []}
    addr_u = address.upper().strip()
    where = f"UPPER(ADDRESS) LIKE {_sql_quote('%' + addr_u + '%')}"
    data = await _arcgis_query(VSR_QUERY_URL, where, VSR_OUT_FIELDS)
    feats = data.get("features") or []
    return {"matched_by": "address" if feats else "none", "where": where, "features": feats}


def collect_candidates() -> list[dict]:
    """Stream the board once; never list() the whole thing. Returns only the
    small subset of Henderson County NC rows carrying the signal in question."""
    out = []
    n_total = 0
    for rec in _iter_board_records(DOCS):
        n_total += 1
        county = (rec.get("county") or "").strip().lower()
        state = (rec.get("state") or "").strip().upper()
        if county != "henderson" or state != "NC":
            continue
        raw = rec.get("raw") or {}
        ce = raw.get("code_enforcement")
        vac = raw.get("vacancy")
        source = rec.get("source") or ""
        if ce or vac or source == "counties_nc.henderson_code_violations":
            out.append({
                "source": source,
                "parcel_id": rec.get("parcel_id"),
                "street_address": rec.get("street_address"),
                "owner_name": rec.get("owner_name") or rec.get("defendant"),
                "case_number": rec.get("case_number"),
                "board_code_enforcement": ce,
                "board_vacancy": vac,
            })
    print(f"[scan] total board rows: {n_total}", file=sys.stderr)
    return out


async def validate_one(cand: dict) -> dict:
    ce = cand.get("board_code_enforcement") or {}
    ce_source = (ce.get("source") or "").strip() if isinstance(ce, dict) else ""
    pin = cand.get("parcel_id")
    addr = cand.get("street_address")
    result = {
        "source": cand["source"],
        "parcel_id": pin,
        "street_address": addr,
        "owner_name": cand.get("owner_name"),
        "board_violation_types": (ce or {}).get("violation_types"),
        "board_has_open": (ce or {}).get("has_open"),
        "board_ce_source": ce_source,
        "route": None,
        "fetch_ok": False,
        "error": None,
    }

    try:
        if ce_source == "hendersonville_vacant_structures_register":
            result["route"] = "hendersonville_vacant_structures_register"
            resp = await query_vsr_by_address(addr)
            result["live_matched_by"] = resp["matched_by"]
            result["live_where"] = resp["where"]
            feats = resp["features"]
            result["fetch_ok"] = True
            if not feats:
                result["live_classification"] = "not_found_on_live_register"
            else:
                attrs = [f.get("attributes") or {} for f in feats]
                occupied_vals = [a.get("OCCUPIED") for a in attrs]
                condemned_vals = [a.get("CONDEMNED") for a in attrs]
                boarded_vals = [a.get("BOARDED_UP") for a in attrs]
                result["live_occupied"] = occupied_vals
                result["live_condemned"] = condemned_vals
                result["live_boarded_up"] = boarded_vals
                still_vacant = any(
                    str(v).strip().lower() in ("no", "n", "false", "0") or v is False
                    for v in occupied_vals
                )
                result["live_classification"] = (
                    "still_vacant_on_live_register" if still_vacant
                    else "record_found_but_shows_occupied"
                )
        else:
            # Default / dominant route: the county OVT dashboard layer, source of
            # the known Zoning-vs-vacant miscategorization.
            result["route"] = "henderson_ordinance_violations_tracking"
            norm_pin = ovt_norm_pin(pin) if pin else None
            resp = await query_ovt_by_pin_or_address(norm_pin, addr)
            result["live_matched_by"] = resp["matched_by"]
            result["live_where"] = resp["where"]
            feats = resp["features"]
            result["fetch_ok"] = True
            if not feats:
                result["live_classification"] = "not_found_live"
            else:
                attrs = [f.get("attributes") or {} for f in feats]
                live_types = sorted({
                    (a.get("violationType") or "unknown") for a in attrs
                })
                live_statuses = sorted({
                    (a.get("dispositionStatus") or "unknown") for a in attrs
                })
                any_open = any(not ovt_is_closed(a.get("dispositionStatus")) for a in attrs)
                any_vacancy_adjacent = any(
                    VACANCY_ADJACENT_RE.search(t) for t in live_types if t and t != "unknown"
                )
                result["live_violation_types"] = live_types
                result["live_disposition_statuses"] = live_statuses
                result["live_any_case_open"] = any_open
                result["live_any_vacancy_adjacent"] = any_vacancy_adjacent
                result["live_classification"] = (
                    "vacancy_adjacent" if any_vacancy_adjacent else "unrelated_category"
                )
                result["live_status_classification"] = "open" if any_open else "closed_or_resolved"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"

    return result


async def main() -> None:
    t0 = time.time()
    candidates = collect_candidates()
    print(f"[scan] Henderson NC candidates with code-enforcement/vacancy signal: {len(candidates)}",
          file=sys.stderr)

    rng = random.Random(SEED)
    if len(candidates) <= SAMPLE_SIZE:
        sample = candidates
    else:
        sample = rng.sample(candidates, SAMPLE_SIZE)
    print(f"[scan] sampling {len(sample)} of {len(candidates)} (seed={SEED})", file=sys.stderr)

    results = []
    for i, cand in enumerate(sample, 1):
        r = await validate_one(cand)
        results.append(r)
        print(f"[{i}/{len(sample)}] {cand['source'][:45]:45} pin={cand.get('parcel_id') or '-':11} "
              f"-> {r.get('live_classification')} ({r.get('live_matched_by')}) "
              f"err={r.get('error')}", file=sys.stderr)
        await asyncio.sleep(0.2)  # polite pacing against a shared ArcGIS Online host

    n_sampled = len(results)
    n_fetched = sum(1 for r in results if r["fetch_ok"])
    n_found = sum(1 for r in results if r["fetch_ok"] and r.get("live_classification") not in
                  ("not_found_live", "not_found_on_live_register"))

    ovt_results = [r for r in results if r["route"] == "henderson_ordinance_violations_tracking"
                   and r["fetch_ok"] and r.get("live_classification") in
                   ("vacancy_adjacent", "unrelated_category")]
    n_ovt_vacancy_adjacent = sum(1 for r in ovt_results if r["live_classification"] == "vacancy_adjacent")
    n_ovt_unrelated = sum(1 for r in ovt_results if r["live_classification"] == "unrelated_category")
    n_ovt_closed = sum(1 for r in ovt_results if r.get("live_status_classification") == "closed_or_resolved")
    n_ovt_open = sum(1 for r in ovt_results if r.get("live_status_classification") == "open")

    vsr_results = [r for r in results if r["route"] == "hendersonville_vacant_structures_register"
                   and r["fetch_ok"]]
    n_vsr_still_vacant = sum(1 for r in vsr_results if r.get("live_classification") == "still_vacant_on_live_register")
    n_vsr_now_occupied = sum(1 for r in vsr_results if r.get("live_classification") == "record_found_but_shows_occupied")
    n_vsr_not_found = sum(1 for r in vsr_results if r.get("live_classification") == "not_found_on_live_register")

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - t0, 1),
        "seed": SEED,
        "total_board_rows_scanned_note": "see stderr scan log",
        "total_candidates_henderson_nc": len(candidates),
        "n_sampled": n_sampled,
        "n_fetch_ok": n_fetched,
        "n_live_record_found": n_found,
        "ovt_dashboard_route": {
            "n_in_sample": sum(1 for r in results if r["route"] == "henderson_ordinance_violations_tracking"),
            "n_with_live_case_found": len(ovt_results),
            "n_vacancy_adjacent": n_ovt_vacancy_adjacent,
            "n_unrelated_category_mislabeled": n_ovt_unrelated,
            "pct_vacancy_adjacent": round(100 * n_ovt_vacancy_adjacent / len(ovt_results), 1) if ovt_results else None,
            "pct_mislabeled": round(100 * n_ovt_unrelated / len(ovt_results), 1) if ovt_results else None,
            "n_open": n_ovt_open,
            "n_closed_or_resolved": n_ovt_closed,
            "pct_closed_or_resolved": round(100 * n_ovt_closed / len(ovt_results), 1) if ovt_results else None,
        },
        "hendersonville_vacant_register_route": {
            "n_in_sample": len(vsr_results),
            "n_still_vacant_confirmed": n_vsr_still_vacant,
            "n_now_shows_occupied": n_vsr_now_occupied,
            "n_not_found_on_live_register": n_vsr_not_found,
        },
        "candidate_source_breakdown": {},
    }
    for c in candidates:
        src = c["source"]
        summary["candidate_source_breakdown"][src] = summary["candidate_source_breakdown"].get(src, 0) + 1

    out_payload = {"summary": summary, "per_row_results": results}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out_payload, indent=2, default=str))
    print(f"\n[done] wrote {OUT_PATH}", file=sys.stderr)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
