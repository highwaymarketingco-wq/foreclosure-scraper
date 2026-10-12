"""Export the wall punch list: every board listing this pipeline's polite verification cannot
check, one row per listing, for the separate bypass-capable platform to re-check (and write its
answers back into the same ledgers). Read-only: no network, no ledger writes.

WHAT GOES IN (docs/VERIFICATION_HANDOFF_PLAN.md has the full contract):

  category "wall"       the listing's verdict for a signal is a wall, by the existing taxonomy:
      wall_state "recorded"            the ledger entry's latest verdict is `wall` (core.VERDICTS;
                                       court_walls, lien_registry_wall, divorce_sc_wall, and the
                                       ROD / probate verifiers' "rod_blocked" answer)
      wall_state "unconfirmed_blocked" latest verdict `unconfirmed` whose evidence says the source
                                       refused the script (is_blocked_evidence(): the ROD/probate
                                       `blocked` field and check_block() reasons login_redirect /
                                       http_401 / http_403; qPayBill's Health.blocked, i.e. a
                                       TenantDown "circuit blocked" or HTTP 401/403). A 503, an
                                       error page or a timeout is NOT a wall: the verifiers list
                                       those as TRANSIENT_REASONS and this pipeline retries them.
      wall_state "not_yet_labelled"    a WALL = True verifier applies to the row but the sweep has
                                       not written its label yet; its reason is the verifier's own
                                       (verify() of a WALL verifier never touches the network)
  category "uncovered"  no verifier's applies() takes the row for any signal: nothing exists to
                        check it with yet (kept separate; this is a build gap, not a wall).

Rows a polite verifier applies to (checked or still due) are not in the list: this pipeline
checks those itself.

Usage: uv run python scripts/export_wall_punchlist.py [--board docs/listings.json.gz]
           [--ledger-dir docs/handoff/verification] [--out-dir data/handoff]
           [--summary docs/handoff/wall_punchlist_summary.json] [--no-uncovered]
"""
from __future__ import annotations

import argparse
import csv
import json
import resource
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_parts import BoardIntegrityError  # noqa: E402
from foreclosure_scraper.board_stream import (  # noqa: E402
    detail_source, iter_board_rows, iter_board_rows_with_detail)
from foreclosure_scraper.verification.core import (  # noqa: E402
    looks_like_address, row_key, row_keys, tier_of)
from foreclosure_scraper.verification.ledger import ledger_dir, load_all  # noqa: E402
from foreclosure_scraper.verification.registry import discover  # noqa: E402

FORMAT_VERSION = 1
COLUMNS = ("category", "signal", "wall_state", "wall_path", "wall_reason", "verifier",
           "ledger_key", "row_keys", "state", "county", "parcel_id", "case_number",
           "street_address", "listing_type", "source", "source_url", "checked_url",
           "last_attempted_at", "first_checked_at", "checks", "tier")

#: check_block() reasons (foreclosure_rod_buncombe / probate_heir_buncombe) and qPayBill Health
#: kinds that mean the source refused the script, not that it was briefly down
BLOCK_REASONS = frozenset({"login_redirect", "http_401", "http_403", "rod_blocked"})
BLOCK_HTTP = frozenset({401, 403})


def is_blocked_evidence(ev: Any) -> bool:
    """True when an `unconfirmed` record's evidence says the source walled the request."""
    if not isinstance(ev, dict):
        return False
    if ev.get("blocked"):
        return True
    if str(ev.get("reason") or "") in BLOCK_REASONS:
        return True
    if ev.get("tenant_state") == "blocked" or "circuit blocked" in str(ev.get("tenant_health") or ""):
        return True
    try:
        return int(ev.get("http_status") or 0) in BLOCK_HTTP
    except (TypeError, ValueError):
        return False


def _wall_result(v, row: dict) -> Optional[dict]:
    """The answer a WALL verifier gives for the row, without a network (its verify() never
    awaits anything; a coroutine that does is closed and None returned)."""
    coro = v.verify(row, None)
    try:
        coro.send(None)
    except StopIteration as stop:
        res = stop.value
        return res.to_dict() if res is not None else None
    except Exception:  # noqa: BLE001
        return None
    coro.close()
    return None


def _path_of(v_name: str, ev: dict) -> str:
    """Which manual / bypass lane the listing needs: the walls_register card when the verifier
    names one, else the verifier module (divorce_sc_wall, foreclosure_rod_buncombe ...)."""
    return str(ev.get("card") or v_name or "")


def _reason_of(ev: dict, verdict: str) -> str:
    r = str(ev.get("reason") or "")
    extra = ev.get("blocked") or ev.get("tenant_health") or ""
    if verdict == "unconfirmed" and extra and str(extra) not in r:
        r = f"{r}: {extra}" if r else str(extra)
    return r[:300]


def _base(row: dict, keys: list[str]) -> dict:
    addr = row.get("street_address")
    return {"row_keys": keys, "state": row.get("state") or "", "county": row.get("county") or "",
            "parcel_id": row.get("parcel_id") or "", "case_number": row.get("case_number") or "",
            "street_address": addr if looks_like_address(addr) else "",
            "listing_type": str(getattr(row.get("listing_type"), "value", row.get("listing_type")) or ""),
            "source": row.get("source") or "", "source_url": row.get("source_url") or "",
            "tier": tier_of(row) or ""}


def classify(row: dict, verifiers: list, ledgers: dict) -> tuple[list[dict], bool]:
    """(punch-list items for this row, covered?). Mirrors verification_sweep's selection: the
    first applicable verifier of a signal owns the row; its ledger entry is found by the
    verifier's ledger_keys() with Ledger.find()."""
    items: list[dict] = []
    done: set[str] = set()
    for v in verifiers:
        if v.signal in done or not v.safe_applies(row):
            continue
        done.add(v.signal)
        led = ledgers.get(v.signal)
        ek, entry = (led.find(v.ledger_keys(row), address=row.get("street_address"))
                     if led is not None else (None, None))
        lat = (entry or {}).get("latest") or {}
        ev = lat.get("evidence") if isinstance(lat.get("evidence"), dict) else {}
        verdict = lat.get("verdict")
        state = None
        if verdict == "wall":
            state = "recorded"
        elif verdict == "unconfirmed" and is_blocked_evidence(ev):
            state = "unconfirmed_blocked"
        elif entry is None and v.wall:
            state = "not_yet_labelled"
            lat = _wall_result(v, row) or {"verdict": "wall", "evidence": {}, "verifier": v.name}
            ev = lat.get("evidence") or {}
            verdict = "wall"
        if state is None:
            continue
        name = str(lat.get("verifier") or v.name)
        last = (entry or {}).get("last_attempt") or {}
        items.append({
            "category": "wall", "signal": v.signal, "wall_state": state,
            "wall_path": _path_of(name, ev), "wall_reason": _reason_of(ev, verdict),
            "verifier": name, "ledger_key": ek or v.ledger_keys(row)[0],
            **_base(row, v.ledger_keys(row)),
            "checked_url": str(ev.get("url") or ""),
            "last_attempted_at": str(last.get("checked_at") or (lat.get("checked_at") if entry else "") or ""),
            "first_checked_at": str((entry or {}).get("first_checked_at") or ""),
            "checks": int((entry or {}).get("checks") or 0),
        })
    return items, bool(done)


def _uncovered_item(row: dict) -> dict:
    keys = row_keys(row)
    return {"category": "uncovered", "signal": "", "wall_state": "", "wall_path": "",
            "wall_reason": "no verifier applies to this listing", "verifier": "",
            "ledger_key": keys[0], **_base(row, keys), "checked_url": "",
            "last_attempted_at": "", "first_checked_at": "", "checks": 0}


def _rows(board: Path, verifiers: list) -> Iterable[dict]:
    dk = sorted({k for v in verifiers for k in (v.detail_keys or ())})
    if dk:
        try:
            detail_source(board.parent)
            return iter_board_rows_with_detail(board, dk)
        except (FileNotFoundError, BoardIntegrityError) as exc:
            print(f"!! lazy-detail sidecar unavailable ({exc}); rows carry no {dk}", flush=True)
    return iter_board_rows(board)


def peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024 * 1024) if sys.platform == "darwin" else r / 1024


def export(board: Path, ledger_directory: Path, out_dir: Path, summary_path: Optional[Path],
           include_uncovered: bool = True, verifiers: Optional[list] = None,
           exclude_sources: frozenset[str] = frozenset()) -> dict:
    verifiers = verifiers if verifiers is not None else discover()
    ledgers, bad = load_all(ledger_directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    jp, cp = out_dir / "wall_punchlist.json", out_dir / "wall_punchlist.csv"
    jtmp, ctmp = jp.with_suffix(".json.tmp"), cp.with_suffix(".csv.tmp")
    seen: set[tuple[str, str]] = set()
    by_cat: Counter = Counter()
    by_signal: Counter = Counter()
    by_path: Counter = Counter()
    by_state: Counter = Counter()
    by_source: Counter = Counter()
    by_county: Counter = Counter()
    by_uncov_source: Counter = Counter()
    by_uncov_county: Counter = Counter()
    board_rows = 0
    n = 0
    with open(jtmp, "w", encoding="utf-8") as jf, open(ctmp, "w", encoding="utf-8", newline="") as cf:
        cw = csv.DictWriter(cf, fieldnames=COLUMNS)
        cw.writeheader()
        jf.write("[")
        for row in _rows(board, verifiers):
            board_rows += 1
            if exclude_sources and str(getattr(row, "source", "") or "") in exclude_sources:
                continue
            items, covered = classify(row, verifiers, ledgers)
            if not covered and include_uncovered:
                items = [_uncovered_item(row)]
            for it in items:
                k = (it["category"] + ":" + it["signal"], it["ledger_key"])
                if k in seen:
                    continue
                seen.add(k)
                jf.write(("\n" if n == 0 else ",\n")
                         + json.dumps(it, sort_keys=True, separators=(",", ":"), default=str))
                cw.writerow({c: ("|".join(it[c]) if isinstance(it[c], list) else it[c]) for c in COLUMNS})
                n += 1
                by_cat[it["category"]] += 1
                cty = f"{it['state']}:{str(it['county']).lower()}"
                if it["category"] == "wall":
                    by_signal[it["signal"]] += 1
                    by_path[it["wall_path"]] += 1
                    by_state[it["wall_state"]] += 1
                    by_source[it["source"]] += 1
                    by_county[cty] += 1
                else:
                    by_uncov_source[it["source"]] += 1
                    by_uncov_county[cty] += 1
        jf.write("\n]\n")
    jtmp.replace(jp)
    ctmp.replace(cp)
    summary = {
        "format_version": FORMAT_VERSION,
        "kind": "wall_punchlist_summary",
        "board_rows": board_rows,
        "ledgers": {s: {"entries": len(l.rows), "generated_at": l.generated_at}
                    for s, l in sorted(ledgers.items())},
        "ledger_problems": bad,
        "listings": n,
        "by_category": dict(sorted(by_cat.items())),
        "wall": {"by_signal": dict(by_signal.most_common()),
                 "by_wall_path": dict(by_path.most_common()),
                 "by_wall_state": dict(by_state.most_common()),
                 "by_scraper_source": dict(by_source.most_common()),
                 "top_counties": dict(by_county.most_common(15))},
        "uncovered": {"by_scraper_source": dict(by_uncov_source.most_common(40)),
                      "top_counties": dict(by_uncov_county.most_common(15))},
    }
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return summary


READY_KIND = "wall_punchlist_ready"


def write_ready_marker(out_dir: Path, summary: dict, *, now: Optional[str] = None) -> Path:
    """data/handoff/wall_punchlist.ready: written (atomically) only after both output files are
    complete, so a watcher that sees a new marker can read the punch list at once. Its
    `punchlist_sha256` changes exactly when the punch list does; a consumer remembers the last
    value it processed and skips a marker it has seen."""
    import hashlib
    from datetime import datetime, timezone
    jp = out_dir / "wall_punchlist.json"
    h = hashlib.sha256()
    with open(jp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    marker = {"kind": READY_KIND, "format_version": FORMAT_VERSION,
              "generated_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "json": str(jp), "csv": str(out_dir / "wall_punchlist.csv"),
              "punchlist_sha256": h.hexdigest(), "listings": summary["listings"],
              "by_category": summary["by_category"], "board_rows": summary["board_rows"]}
    mp = out_dir / "wall_punchlist.ready"
    tmp = out_dir / ".wall_punchlist.ready.tmp"
    tmp.write_text(json.dumps(marker, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(mp)
    return mp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--board", default=str(REPO / "docs" / "listings.json.gz"))
    ap.add_argument("--ledger-dir", default=str(ledger_dir()))
    ap.add_argument("--out-dir", default=str(REPO / "data" / "handoff"))
    ap.add_argument("--summary", default=str(REPO / "docs" / "handoff" / "wall_punchlist_summary.json"))
    ap.add_argument("--no-uncovered", action="store_true")
    ap.add_argument("--exclude-source", action="append", default=[],
                    help="board source(s) to leave out entirely (repeatable); owner decision "
                         "2026-10-12: LiensNC (counties_generic.liensnc, liensnc) is construction "
                         "lien-agent filings, not a distress signal -- it is not a punch-list item")
    ap.add_argument("--ready-marker", action="store_true",
                    help="after a complete export, write <out-dir>/wall_punchlist.ready")
    a = ap.parse_args(argv)
    s = export(Path(a.board), Path(a.ledger_dir), Path(a.out_dir), Path(a.summary) if a.summary else None,
               include_uncovered=not a.no_uncovered, exclude_sources=frozenset(a.exclude_source))
    print(json.dumps({k: s[k] for k in ("board_rows", "listings", "by_category")}, sort_keys=True))
    print(json.dumps(s["wall"], indent=1))
    if a.ready_marker:
        print(f"ready marker: {write_ready_marker(Path(a.out_dir), s)}")
    print(f"peak_rss_mb={peak_rss_mb():.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
