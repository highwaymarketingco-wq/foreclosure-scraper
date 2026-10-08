#!/usr/bin/env python3
"""One-page EVIDENCE SHEET per lead: the facts, where each came from and when it was checked, the
attorney's intake list, where to look in the county, and the call opener. Written OUTSIDE the repo.

  uv run python scripts/lead_evidence_sheet.py --parcel 9686-54-0826-00000 [--parcel ...] [--county Buncombe]
  uv run python scripts/lead_evidence_sheet.py --from-csv ~/Desktop/Call_Sheets/Call_List_2026-10-08.csv --top 20

Reads the live board (or --board <dir>: a board directory or a checkpoint) once, one row at a time,
attaches today's verification ledgers (scripts/call_list_daily.LedgerAttacher), computes the
call-ready gate (call_ready.call_ready) and writes, per lead, <out>/<County>_<parcel>.html and .pdf
(headless Chrome, quiet_title.render.print_pdf; --no-pdf skips it). Default out:
~/Desktop/Call_Sheets/sheets/<date>/. No network: the sheet prints what the board and the ledgers
hold, with their dates and links; quiet_title_intake.py is the tool that reads the latest deed live.

Private (owner names, phones, heir candidates in their published form only): the script refuses to
write inside the repository.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from foreclosure_scraper import call_ready as CR  # noqa: E402

import call_list_daily as DL  # noqa: E402

OUT_ROOT = Path.home() / "Desktop" / "Call_Sheets" / "sheets"
TIER_COLOR = {"A": "#1b7f3b", "B": "#b07a00", "C": "#2a5d9f", "D": "#8a8a8a"}


def norm(v: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(v or "")).upper()


def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def link(url: Any, text: Any = None) -> str:
    u = str(url or "")
    if not re.match(r"^https?://", u):
        return esc(text or u)
    return f'<a href="{esc(u)}">{esc(text or u)}</a>'


def money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------------------------------------
# the sections
# ---------------------------------------------------------------------------------------------

def issue_rows(row: dict, blk: dict) -> list[tuple[str, str, str, str]]:
    """(what, result, checked on, source) for every check behind the lead."""
    raw = row.get("raw") or {}
    out = []
    rec = CR.record(raw, "tax_lien")
    if rec:
        ev = rec.get("evidence") or {}
        dby = ev.get("delinquent_by_year") if isinstance(ev.get("delinquent_by_year"), dict) else {}
        years = ", ".join(f"{y}: {money(a)}" for y, a in sorted(dby.items()) if (DL.CR._num(a) or 0) > 0)
        pend = ev.get("not_yet_delinquent_due") if isinstance(ev.get("not_yet_delinquent_due"), dict) else {}
        res = (f"{rec.get('verdict')}: {money(ev.get('total_delinquent'))} past due over "
               f"{ev.get('years_delinquent') or 0} year(s)" + (f" ({years})" if years else ""))
        if pend:
            res += "; not late yet: " + ", ".join(f"{y} {money(a)}" for y, a in pend.items())
        if ev.get("sold_at_tax_sale_years"):
            res += f"; sold at tax sale: {ev.get('sold_at_tax_sale_years')}"
        out.append(("County tax site", res, str(rec.get("checked_at") or "")[:10],
                    link(ev.get("page_url") or ev.get("url"), rec.get("source") or "county site")
                    + f" ({esc(rec.get('verifier'))} {esc(rec.get('verifier_version'))})"))
    for sig, label in (("probate_heir", "Death index + deeds"), ("bankruptcy_stay", "Bankruptcy court"),
                       ("foreclosure_rod", "Register of deeds (foreclosure)"),
                       ("code_enforcement", "Code enforcement case"), ("vacant_structure", "Vacant structure register"),
                       ("elderly_disabled", "Elderly / disabled exemption"), ("jail_booking", "Jail roster")):
        r = CR.record(raw, sig)
        if r:
            ev = r.get("evidence") or {}
            why = ev.get("reason") or ev.get("decided_by") or ev.get("owner_relation") or ""
            out.append((label, f"{r.get('verdict')}" + (f" ({why})" if why else ""), str(r.get("checked_at") or "")[:10],
                        link(ev.get("url"), r.get("source") or sig)))
    f = blk.get("facts") or {}
    if f.get("window"):
        when = f"sale {f.get('sale_on')}" if f.get("sale_on") else ""
        if f.get("upset_deadline"):
            when += f"; upset-bid window open until {f.get('upset_deadline')}"
        out.append(("Sale status", f"{f.get('window')}: {when}", f.get("last_seen") or "",
                    link(row.get("source_url"), row.get("source"))))
    out.append(("This row's source", str(row.get("listing_type") or ""), str(row.get("first_seen") or "")[:10],
                link(row.get("source_url"), row.get("source"))))
    return out


def contact_rows(row: dict, blk: dict, shared: int) -> list[tuple[str, str]]:
    raw = row.get("raw") or {}
    op = raw.get("owner_phone") if isinstance(raw.get("owner_phone"), dict) else {}
    om = raw.get("owner_mailing") if isinstance(raw.get("owner_mailing"), dict) else {}
    out = [("Owner of record", f"{row.get('owner_name') or 'none on the row'} ({CR.owner_kind(row)})"),
           ("Mailing address", f"{CR.mailing_text(raw) or 'none'} | check: {DL.MAIL_CHECK.get(blk.get('mail') or 'missing')}"
                               + (" | absentee" if om.get("absentee") else ""))]
    if op.get("phone"):
        usable = blk.get("phone") in ("tied", "name_match_only")
        out.append(("Phone", f"{op.get('phone') if usable else '(not to be dialed)'} | {DL.PHONE_CHECK.get(blk.get('phone') or 'none')}"
                             f" | {op.get('line_type') or 'line type unknown'} ({op.get('tcpa_class') or 'tcpa class unknown'})"
                             f" | matched by {op.get('match') or '?'} from {op.get('source') or '?'}"
                             f" | DNC: {blk.get('dnc') or 'not scrubbed'}"
                             + (f" | also on records of {shared} other owner name(s)" if shared else "")))
    else:
        out.append(("Phone", "none on the row"))
    return out


def estate_rows(row: dict) -> list[tuple[str, str]]:
    raw = row.get("raw") or {}
    out = []
    ec = DL.estate_contact(raw)
    if ec:
        out.append(("Estate contact (probate record / roll care-of)", ec))
    for key, label in (("probate", "Probate record"), ("sc_probate_notice", "SC probate notice")):
        b = raw.get(key)
        if isinstance(b, dict):
            bits = [f"{k}: {b.get(k)}" for k in ("decedent", "estate", "es_case_number", "nc_estate_file_no",
                                                 "case_number", "date_of_death", "county") if b.get(k)]
            if bits:
                out.append((label, "; ".join(bits)))
    hc = raw.get("heir_candidates")
    if isinstance(hc, list) and hc:
        items = [f"{c.get('name')} ({c.get('relation')}; {c.get('source_kind')}; {c.get('source_date') or 'undated'}"
                 + (f"; {c.get('source_url')}" if c.get("source_url") else "") + ")"
                 for c in hc[:8] if isinstance(c, dict)]
        out.append(("Heir candidates (candidates, not findings)", " | ".join(items)))
    he = raw.get("heir_estate")
    if isinstance(he, dict) and he.get("owner_of_record"):
        out.append(("County roll (heirs / estate)", f"{he.get('owner_of_record')}"
                    + (f"; care of {he.get('care_of')}" if he.get("care_of") else "")))
    return out


LAWYER_LABELS = [("parcel", "Parcel number"), ("legal_description", "Legal description (+ the latest deed)"),
                 ("deed_chain", "Deed chain"), ("taxpayer", "Taxpayer of record"), ("heirs", "Possible heirs"),
                 ("rod_checked", "Records checked: register of deeds"), ("tax_checked", "Records checked: tax"),
                 ("probate_checked", "Records checked: probate"), ("obituaries_checked", "Records checked: obituaries")]


def lawyer_rows(row: dict, blk: dict) -> list[tuple[str, str, str]]:
    raw = row.get("raw") or {}
    death = CR.death_fact(row)
    estate = CR.estate_fact(row, date.today()) if (death["record"] or death["weak"]) else {}
    ll = blk.get("lawyer") or CR.lawyer_list(row, CR.tax_fact(row, date.today()), death, estate)
    deed = CR._latest_deed(raw) or {}
    dc = raw.get("deed_chain") if isinstance(raw.get("deed_chain"), dict) else {}
    tr = [t for t in (dc.get("transfers") or []) if isinstance(t, dict)][-5:]
    detail = {
        "parcel": str(row.get("parcel_id") or ""),
        "legal_description": (str(row.get("legal_description") or "")[:220]
                              + (f" | latest deed: {deed.get('book') or ''}/{deed.get('page') or ''}{deed.get('book_page') or ''}"
                                 f" {deed.get('date') or ''}" if deed else " | latest deed: not on the row")),
        "deed_chain": " ; ".join(f"{t.get('date') or '?'} {t.get('doc_type') or t.get('type') or ''} "
                                 f"{t.get('book') or ''}/{t.get('page') or ''} ({t.get('source') or ''})" for t in tr),
        "taxpayer": f"{row.get('owner_name') or ''}",
        "heirs": (f"{len(raw.get('heir_candidates') or [])} heir candidate(s) on the board"
                  + ("; a personal representative is on the probate record" if DL.estate_contact(raw) else "")),
    }
    out = []
    for k, label in LAWYER_LABELS:
        v = ll.get(k, "missing")
        status = "ok" if v == "ok" else ("n/a" if v == "n/a" else ("missing" if v == "missing" else f"checked {v}"))
        out.append((label, status, detail.get(k, "")))
    return out


def where_rows(row: dict) -> list[tuple[str, str]]:
    from foreclosure_scraper.quiet_title.county_records import where_to_look
    try:
        w = where_to_look(str(row.get("county") or ""), str(row.get("state") or "NC"))
    except Exception:  # noqa: BLE001
        return []
    return [(a, b) for a, b in w.rows if a in ("Register of deeds portal", "Person needed for the register",
                                               "Probate (estates)", "County tax site", "County map layer")]


CSS = """
@page { size: letter; margin: 0.45in; }
body { font: 10px/1.32 -apple-system, Helvetica, Arial, sans-serif; color: #111; margin: 0; }
h1 { font-size: 15px; margin: 0 0 2px; }
.sub { color: #444; margin-bottom: 6px; }
.badge { display: inline-block; color: #fff; border-radius: 3px; padding: 1px 6px; font-weight: 600; margin-right: 4px; }
.reason { border-left: 4px solid #333; padding: 4px 8px; background: #f4f4f4; margin: 6px 0; font-size: 11px; }
h2 { font-size: 11px; margin: 8px 0 2px; border-bottom: 1px solid #bbb; text-transform: uppercase; letter-spacing: .03em; }
table { border-collapse: collapse; width: 100%; }
td, th { border-bottom: 1px solid #e3e3e3; padding: 2px 4px; vertical-align: top; text-align: left; }
th { background: #fafafa; font-weight: 600; }
td.k { width: 26%; color: #333; font-weight: 600; }
.ok { color: #1b7f3b; font-weight: 600; } .missing { color: #b00020; font-weight: 600; }
.small { font-size: 8.5px; color: #555; }
.say { background: #eef6ee; padding: 5px 8px; border-radius: 3px; }
a { color: #1a4fa0; text-decoration: none; word-break: break-all; }
"""


def render(row: dict, blk: dict, shared: int, meta: dict) -> str:
    lane, tier = blk.get("lane") or "-", blk.get("tier") or "D"
    addr = ", ".join(str(x) for x in (row.get("street_address"), row.get("city"),
                                      f"{row.get('county')} County {row.get('state')}") if x)
    h = [f"<!doctype html><html><head><meta charset='utf-8'><title>Evidence sheet {esc(row.get('parcel_id'))}</title>"
         f"<style>{CSS}</style></head><body>"]
    h.append(f"<h1>{esc(addr)}</h1><div class='sub'>Parcel <b>{esc(row.get('parcel_id') or 'none')}</b> &middot; "
             f"<span class='badge' style='background:#333'>Lane {esc(lane)}: {esc(CR.LANES.get(lane, 'no lane'))}</span>"
             f"<span class='badge' style='background:{TIER_COLOR.get(tier, '#888')}'>Tier {esc(tier)}: {esc(CR.TIERS.get(tier))}</span>"
             f" rank {esc(blk.get('rank', ''))}/100</div>")
    h.append(f"<div class='reason'>{esc(blk.get('reason') or 'No call lane for this row.')}</div>")
    h.append("<h2>The issue, as checked</h2><table><tr><th>Check</th><th>Result</th><th>Checked on</th><th>Source</th></tr>")
    for a, b, c, d in issue_rows(row, blk):
        h.append(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{esc(c)}</td><td>{d}</td></tr>")
    h.append("</table><h2>Owner and contact</h2><table>")
    for a, b in contact_rows(row, blk, shared):
        h.append(f"<tr><td class='k'>{esc(a)}</td><td>{esc(b)}</td></tr>")
    h.append("</table>")
    er = estate_rows(row)
    if er:
        h.append("<h2>Estate and heirs</h2><table>")
        for a, b in er:
            h.append(f"<tr><td class='k'>{esc(a)}</td><td>{esc(b)}</td></tr>")
        h.append("</table>")
    h.append("<h2>The attorney's intake list</h2><table><tr><th>Item</th><th>Status</th><th>What the board holds</th></tr>")
    for a, b, c in lawyer_rows(row, blk):
        cls = "ok" if b in ("ok", "n/a") or b.startswith("checked") else "missing"
        h.append(f"<tr><td>{esc(a)}</td><td class='{cls}'>{esc(b)}</td><td>{esc(c)}</td></tr>")
    h.append("</table>")
    wr = where_rows(row)
    if wr:
        h.append("<h2>Where to look in this county</h2><table>")
        for a, b in wr:
            b2 = re.sub(r"(https?://\S+?)([).,;]?(\s|$))", lambda m: f'<a href="{esc(m.group(1))}">{esc(m.group(1))}</a>{m.group(2)}', esc(b))
            h.append(f"<tr><td class='k'>{esc(a)}</td><td>{b2}</td></tr>")
        h.append("</table>")
    if blk.get("lane") in ("A", "B", "D", "E") and blk.get("tier") in ("A", "B", "C"):
        title = "Call opener" if blk.get("tier") in ("A", "B") else "Opener (for the letter, or if they call back)"
        h.append(f"<h2>{title}</h2><div class='say'>{esc(DL.say_this(row, blk))}</div>")
        h.append(f"<h2>Before dialing or writing</h2><div>{esc(DL.before_dialing(row, blk, shared))}</div>")
    if blk.get("unmet"):
        h.append("<h2>Not yet met</h2><ul>" + "".join(f"<li>{esc(w)}</li>" for w in CR.unmet_words(blk["unmet"])) + "</ul>")
    h.append(f"<div class='small'>Generated {esc(meta.get('generated'))} from the board of {esc(meta.get('board_run'))} "
             f"and the verification ledgers on disk (newest tax check {esc(meta.get('newest_tax'))}). Every fact above is "
             f"from a public record, with the day it was read; heir candidates are candidates, not findings. "
             f"The latest deed's own text is read by scripts/quiet_title_intake.py.</div></body></html>")
    return "".join(h)


def find_rows(path: Optional[Path], parcels: set[str], county: Optional[str], att, po=None) -> dict[str, list[dict]]:
    want = {norm(p) for p in parcels if norm(p)}
    got: dict[str, list[dict]] = {}
    for row in DL.iter_rows(path):
        if po is not None:
            po.feed(row)
        p = norm(row.get("parcel_id"))
        if p not in want:
            continue
        if county and str(row.get("county") or "").strip().lower() != county.strip().lower():
            continue
        att.attach(row)
        got.setdefault(p, []).append(row)
    return got


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parcel", action="append", default=[], help="parcel id (repeatable)")
    ap.add_argument("--county", help="only rows in this county")
    ap.add_argument("--from-csv", help="take parcel ids from a call list CSV (column parcel_id)")
    ap.add_argument("--top", type=int, default=20, help="with --from-csv: the first N rows (default 20)")
    ap.add_argument("--board", help="board or checkpoint directory (default the live board)")
    ap.add_argument("--out", help="output folder (default ~/Desktop/Call_Sheets/sheets/<date>/)")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)
    parcels = list(a.parcel)
    if a.from_csv:
        with open(Path(a.from_csv).expanduser(), newline="", encoding="utf-8") as fh:
            for i, r in enumerate(csv.DictReader(fh)):
                if i >= a.top:
                    break
                if r.get("parcel_id"):
                    parcels.append(r["parcel_id"])
    if not parcels:
        ap.error("give --parcel or --from-csv")
    today = date.today()
    out = Path(a.out).expanduser() if a.out else OUT_ROOT / today.isoformat()
    try:
        out.resolve().relative_to(REPO)
        print("Refusing to write evidence sheets inside the repository (they hold names and phones).", file=sys.stderr)
        return 2
    except ValueError:
        pass
    out.mkdir(parents=True, exist_ok=True)
    att = DL.LedgerAttacher()
    tax_led = next((led for s, led in att.active if s == "tax_lien"), None)
    newest = max((str((e.get("latest") or {}).get("checked_at") or "") for e in tax_led.rows.values()),
                 default="") if tax_led else ""
    try:
        board_run = json.loads((REPO / "docs" / "run_meta.json").read_text()).get("run_time")
    except (OSError, ValueError):
        board_run = "unknown"
    meta = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "board_run": a.board or board_run, "newest_tax": newest[:16]}
    path = Path(a.board).expanduser() if a.board else None
    po = DL.PhoneOwners()
    found = find_rows(path, set(parcels), a.county, att, po)
    phones = po.counts()
    written = []
    for p in dict.fromkeys(norm(x) for x in parcels):
        rows = found.get(p) or []
        if not rows:
            print(f"not on the board: {p}")
            continue
        scored = sorted(((CR.call_ready(r, today), r) for r in rows),
                        key=lambda br: (DL.TIER_ORDER.get(br[0].get("tier"), 9), -(br[0].get("rank") or 0)))
        blk, row = scored[0]
        raw = row.get("raw") or {}
        op = raw.get("owner_phone") if isinstance(raw.get("owner_phone"), dict) else {}
        shared = max(0, phones.get(DL.digits10(op.get("phone")), 0) - 1)
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{row.get('county') or 'county'}_{row.get('parcel_id') or p}")
        hp = out / f"{stem}.html"
        hp.write_text(render(row, blk, shared, meta), encoding="utf-8")
        pdf = None
        if not a.no_pdf:
            from foreclosure_scraper.quiet_title.render import print_pdf
            pp = out / f"{stem}.pdf"
            pdf = pp if print_pdf(hp, pp) else None
        written.append({"parcel": row.get("parcel_id"), "lane": blk.get("lane"), "tier": blk.get("tier"),
                        "html": str(hp), "pdf": str(pdf) if pdf else None, "board_rows": len(rows)})
    print(json.dumps(written, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
