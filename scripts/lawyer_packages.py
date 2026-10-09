"""The attorney's quiet-title packages for lane C (call_ready.py), written OUTSIDE the repository.

  uv run python scripts/lawyer_packages.py [--board <board or checkpoint>] [--out DIR] [--near 4]
        [--owner-inputs DIR] [--intake-root DIR] [--no-pdf]

For every lane C row (recomputed with call_ready on the row as published) it merges three sources
per item of the attorney's list (lawyer_lane.ITEMS):
  1. the board row itself (lawyer_lane.items: sourced and dated, or missing / walled);
  2. the live intake sheet, when one was run for the parcel (scripts/quiet_title_intake.py writes
     ~/Desktop/Lawyer_Review/intake/<PIN>/*_facts.json): the county parcel record, the latest deed
     the county cites (book/page, index description), the chain, the tax bills, the records table;
  3. what the owner pulled by hand (docs/walls_register.json card 'lawyer_owner_pulls'):
     <owner-inputs>/<PIN>/items.json = {"<item>": {"on": "YYYY-MM-DD", "source": "...", "file": "..."}}
     with the saved documents next to it. Re-running this script regenerates the package.
A lead is READY when every item is sourced and dated after the merge. Ready leads get a package
(HTML, and PDF when Chrome is installed) in <out>/<date>/packages/; every lane C row with at most
--near items open is listed in <out>/<date>/lane_c_<date>.csv with each item's status and who must
act (script / owner); <out>/<date>/summary_<date>.json has the counts. Default out:
~/Desktop/Call_Sheets/lawyer/. Refuses to write inside the repository (names, addresses).
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import call_ready as CR  # noqa: E402
from foreclosure_scraper import lawyer_lane as LL  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402

OUT_DEFAULT = Path.home() / "Desktop" / "Call_Sheets" / "lawyer"
INTAKE_DEFAULT = Path.home() / "Desktop" / "Lawyer_Review" / "intake"


def _inside_repo(p: Path) -> bool:
    try:
        p.resolve().relative_to(REPO)
        return True
    except ValueError:
        return False


def pin_key(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isalnum()).upper()


# ---------------------------------------------------------------------------------------------
# the intake sheet's facts -> items
# ---------------------------------------------------------------------------------------------

def intake_items(facts: dict) -> dict:
    """{item: {status, on, source, why}} from one intake facts JSON (only what it established)."""
    out: dict = {}
    on = str(facts.get("finished") or facts.get("started") or "")[:10] or None
    src = f"intake sheet ({facts.get('county')} {facts.get('state')})"
    p = facts.get("parcel") or {}
    if p.get("found") and on:
        out["parcel"] = LL._src("sourced", on, src)
        if p.get("owner"):
            out["taxpayer"] = LL._src("sourced", on, src + ": county parcel record")
    v = facts.get("vesting") or {}
    if v.get("book") and v.get("date_iso") and on:
        if str(v.get("description") or "").strip():
            out["legal_description"] = LL._src("sourced", on, src + ": register index",
                                                f"latest deed {v['book']}/{v.get('page')} recorded {v['date_iso']}")
        if facts.get("chain"):
            out["deed_chain"] = LL._src("sourced", on, src + ": register index",
                                        f"{1 + len(facts['chain'])} deeds")
    if (facts.get("register_fetched") or v.get("book")) and on:
        out["rod_checked"] = LL._src("sourced", on, src)
    t = facts.get("tax") or {}
    if t.get("bills") and on:
        out["tax_checked"] = LL._src("sourced", on, src + ": county tax bills")
    elif t.get("walled"):
        out["tax_checked"] = LL._src("walled", why=str(t.get("wall_reason") or "tax site walled"))
    return out


def load_intake(root: Path, pin: str) -> dict:
    d = root / pin_key(pin)
    if not d.is_dir():
        return {}
    for f in sorted(d.glob("*_facts.json")):
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            return {}
    return {}


def owner_items(root: Path, pin: str) -> dict:
    """What the owner pulled by hand: <root>/<PIN>/items.json (see the module doc)."""
    f = root / pin_key(pin) / "items.json"
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in (data or {}).items():
        if k in LL.ITEMS and isinstance(v, dict) and LL.to_date(v.get("on")):
            out[k] = LL._src("sourced", LL._iso(LL.to_date(v["on"])), "owner: " + str(v.get("source") or "by hand"),
                             str(v.get("file") or ""))
    return out


def merge(*layers: dict) -> dict:
    """Per item: the latest sourced entry; else walled over missing (a person is needed)."""
    out: dict = {}
    for k in LL.ITEMS:
        cands = [lay[k] for lay in layers if k in lay]
        src = [c for c in cands if c["status"] == "sourced"]
        if src:
            out[k] = max(src, key=lambda c: c["on"] or "")
        elif any(c["status"] == "walled" for c in cands):
            out[k] = next(c for c in cands if c["status"] == "walled")
        elif cands:
            out[k] = cands[0]
        else:
            out[k] = LL._src("missing")
    return out


# ---------------------------------------------------------------------------------------------
# the package
# ---------------------------------------------------------------------------------------------

CSS = """body{font:11px/1.4 -apple-system,Helvetica,Arial,sans-serif;color:#111;margin:24px}
h1{font-size:16px;margin:0 0 4px}h2{font-size:13px;margin:16px 0 6px}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #bbb;padding:4px 6px;vertical-align:top;text-align:left}th{background:#eee}
.ok{color:#0a5c2b;font-weight:600}.muted{color:#555}"""


def package_html(row: dict, its: dict, facts: dict, blk: dict) -> str:
    e = html.escape
    raw = row.get("raw") or {}
    dl = raw.get("deed_latest") if isinstance(raw.get("deed_latest"), dict) else {}
    v = (facts or {}).get("vesting") or {}
    rows = "".join(f"<tr><td>{e(LL.LABELS[k])}</td><td class='ok'>{e(str(its[k]['on']))}</td>"
                   f"<td>{e(its[k]['source'])}</td><td>{e(its[k]['why'])}</td></tr>" for k in LL.ITEMS)
    deed = ""
    if dl:
        deed = (f"<p>Latest deed (register, bound to this parcel by {e(str(dl.get('bound')))}): "
                f"{e(str(dl.get('doc_id')))} recorded {e(str(dl.get('recorded')))}, {e(str(dl.get('type') or ''))}; "
                f"grantor {e('; '.join(dl.get('grantors') or []))}; grantee {e('; '.join(dl.get('grantees') or []))}.<br>"
                f"Index description: {e(str(dl.get('legal_description') or ''))}<br>"
                f"<span class='muted'>Source: {e(str(dl.get('source_url') or ''))}, read {e(str(dl.get('fetched_at') or ''))}"
                f"</span></p>")
    elif v:
        deed = (f"<p>Latest deed the county cites: book {e(str(v.get('book')))} page {e(str(v.get('page')))} recorded "
                f"{e(str(v.get('date_iso')))}; grantor {e('; '.join(v.get('grantors') or []))}; grantee "
                f"{e('; '.join(v.get('grantees') or []))}.<br>Index description: {e(str(v.get('description') or ''))}</p>")
    heirs = "".join(f"<li>{e(str(c.get('name')))} ({e(str(c.get('relation')))}; {e(str(c.get('source_kind')))}, "
                    f"{e(str(c.get('source_date')))})</li>"
                    for c in (raw.get("heir_candidates") or []) if isinstance(c, dict)
                    and str(c.get("relation") or "").lower() in __import__(
                        "foreclosure_scraper.enrichment_heir_candidates", fromlist=["x"]).PUBLISHABLE_HEIR_RELATIONS)
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Quiet title package {e(str(row.get('parcel_id')))}"
            f"</title><style>{CSS}</style></head><body>"
            f"<h1>Quiet-title intake: {e(str(row.get('county')))} County {e(str(row.get('state')))}, parcel "
            f"{e(str(row.get('parcel_id')))}</h1>"
            f"<p>{e(str(row.get('street_address') or ''))}. Owner of record: {e(str(row.get('owner_name') or ''))}.</p>"
            f"<p>{e(str(blk.get('reason') or ''))}</p>"
            f"<h2>The attorney's list (every item sourced and dated)</h2><table><tr><th>Item</th><th>Sourced on</th>"
            f"<th>Source</th><th>Detail</th></tr>{rows}</table>"
            f"<h2>Latest deed and legal description</h2>{deed or '<p>See the intake sheet.</p>'}"
            f"<p class='muted'>The description is the register index's; the deed image carries the full legal "
            f"description and is attached when the owner pulled it.</p>"
            f"<h2>Possible heirs</h2><ul>{heirs or '<li>See the probate record.</li>'}</ul>"
            f"<p class='muted'>Generated {datetime.now().isoformat(timespec='minutes')} by scripts/lawyer_packages.py. "
            f"Private: not for the public board.</p></body></html>")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", default=str(REPO / "docs" / "listings.json.gz"))
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--owner-inputs", default=None, help="default <out>/owner_inputs")
    ap.add_argument("--intake-root", default=str(INTAKE_DEFAULT))
    ap.add_argument("--near", type=int, default=4, help="list lane C rows with at most this many items open")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)
    out_root = Path(a.out).expanduser()
    if _inside_repo(out_root):
        print("Refusing to write lawyer packages inside the repository.", file=sys.stderr)
        return 2
    today = date.today()
    day = out_root / today.isoformat()
    (day / "packages").mkdir(parents=True, exist_ok=True)
    owner_root = Path(a.owner_inputs).expanduser() if a.owner_inputs else out_root / "owner_inputs"
    owner_root.mkdir(parents=True, exist_ok=True)
    intake_root = Path(a.intake_root).expanduser()

    counts: Counter = Counter()
    open_items: Counter = Counter()
    by_county: Counter = Counter()
    ready_by_county: Counter = Counter()
    listed = []
    written = 0
    for r in iter_board_rows(a.board):
        blk = CR.call_ready(r, today)
        if blk.get("lane") != "C":
            continue
        counts["lane_c"] += 1
        co = f"{r.get('state')}|{r.get('county')}"
        by_county[co] += 1
        pin = r.get("parcel_id")
        facts = load_intake(intake_root, pin) if pin else {}
        its = merge(LL.items(r, today), intake_items(facts) if facts else {}, owner_items(owner_root, pin) if pin else {})
        if facts:
            counts["with_intake"] += 1
        miss = [k for k in LL.ITEMS if its[k]["status"] != "sourced"]
        # the lane's own conditions besides the list (the decedent tied to the parcel, a property,
        # no deed after the death, a mailing address)
        other = [u for u in CR.hard_unmet(blk) if not u.startswith("lawyer_")]
        for k in miss:
            open_items[f"{k}:{its[k]['status']}"] += 1
        for u in other:
            open_items[f"lane:{u}"] += 1
        if not miss and not other:
            counts["ready"] += 1
            ready_by_county[co] += 1
            name = f"QuietTitle_Package_{r.get('county')}_{pin_key(pin)}"
            hp = day / "packages" / f"{name}.html"
            hp.write_text(package_html(r, its, facts, blk))
            if not a.no_pdf:
                from foreclosure_scraper.quiet_title.render import print_pdf
                print_pdf(hp, hp.with_suffix(".pdf"))
            written += 1
        if len(miss) + len(other) <= a.near:
            listed.append({"state": r.get("state"), "county": r.get("county"), "parcel_id": pin,
                           "owner_name": r.get("owner_name"), "street_address": r.get("street_address"),
                           "ready": not miss and not other, "open_items": len(miss) + len(other),
                           "lane_unmet": ",".join(other),
                           "who_must_act": "; ".join(f"{k}: {'owner' if its[k]['status'] == 'walled' else 'script'}"
                                                    for k in miss),
                           **{k: (its[k]["on"] if its[k]["status"] == "sourced" else its[k]["status"]) for k in LL.ITEMS},
                           "intake_cmd": (f"uv run python scripts/quiet_title_intake.py --pin {pin_key(pin)} "
                                          f"--county \"{r.get('county')}\"") if pin and r.get("state") == "NC" else ""})
    listed.sort(key=lambda d: (d["open_items"], str(d["county"])))
    csv_p = day / f"lane_c_{today.isoformat()}.csv"
    cols = ["state", "county", "parcel_id", "owner_name", "street_address", "ready", "open_items", "lane_unmet",
            "who_must_act",
            *LL.ITEMS, "intake_cmd"]
    with csv_p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(listed)
    summary = {"board": str(a.board), "computed_on": today.isoformat(), "lane_c_rows": counts["lane_c"],
               "ready": counts["ready"], "packages_written": written, "with_intake_sheet": counts["with_intake"],
               "listed_near_ready": len(listed), "open_items": dict(open_items.most_common()),
               "lane_c_by_county": dict(by_county.most_common()), "ready_by_county": dict(ready_by_county),
               "owner_inputs": str(owner_root)}
    (day / f"summary_{today.isoformat()}.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("lane_c_by_county",)}, indent=1))
    print(f"csv: {csv_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
