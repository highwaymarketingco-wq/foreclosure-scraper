#!/usr/bin/env python3
"""The closers' daily call list: lane A (owner call: delinquent tax) and lane B (heir lane) leads,
from the live board plus today's verification ledgers, written OUTSIDE the repo.

  uv run python scripts/call_list_daily.py                      # live board -> ~/Desktop/Call_Sheets/
  uv run python scripts/call_list_daily.py --count-only --board <checkpoint dir>   # counts only

WHAT IT DOES
  1. loads docs/handoff/verification/* (read-only) and attaches each row's current verdicts the way
     verification.apply does on the VM (Ledger.find on the row's property keys; case-scoped
     signals by case id), so a check made after the last publish counts today;
  2. streams the board once (board_stream / the checkpoint reader, one row at a time): computes
     call_ready.call_ready() per row, counts lanes x tiers and the unmet conditions, keeps the lane
     A / B rows, and counts which phones sit on rows of more than one owner (patched in after);
  3. writes Call_List_<date>.csv (lane A tiers A-B, lane B tiers A-C: the rows a closer works),
     Call_List_<date>_not_ready.csv (lane A / B rows at tier D, with the reasons) and
     Call_List_<date>_summary.json (the counts) to ~/Desktop/Call_Sheets/. One row per property
     (the best tier, then the highest rank). Private: names, phones and addresses; never in the repo.

The board itself is not changed. Memory: one row at a time plus the kept lane A / B rows (a few
thousand), the phone counter and the ledgers (~25 MB on disk today).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Optional

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from foreclosure_scraper import call_ready as CR  # noqa: E402

OUT_DIR = Path.home() / "Desktop" / "Call_Sheets"
TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}

COLUMNS = [
    # the pilot sheet's columns (Pilot_Call_Sheet_2026-10-08_v2.csv), same names and order
    "state", "county", "parcel_id", "property_address", "owner_of_record", "owner_mailing_address",
    "absentee_owner", "phone", "line_type", "phone_source", "phone_match", "tcpa_class", "needs_dnc_scrub",
    "county_confirmed_years_delinquent", "county_confirmed_total_owed", "county_checked_at",
    "county_site_verifier", "assessed_value", "year_built", "say_this", "before_dialing", "phone_check",
    "mailing_check", "phone_also_on_other_rows", "tier",
    # the call-ready gate
    "lane", "lane_name", "tier_name", "rank", "reason", "unmet", "dnc_status", "checks",
    "county_tax_url", "estate_contact", "heir_candidates", "lawyer_list", "evidence_sheet_cmd",
]


# ---------------------------------------------------------------------------------------------
# today's ledgers on a streamed (dict) row
# ---------------------------------------------------------------------------------------------

class LedgerAttacher:
    """verification.apply's matching, for dict rows: raw['verification'] gets each ledger's current
    record for the row (non-matching signals keep what the row had)."""

    def __init__(self, directory: Optional[Path] = None):
        from foreclosure_scraper.verification.apply import _case_scoped, _verifier_meta
        from foreclosure_scraper.verification.ledger import ledger_dir, load_all
        d = Path(directory or ledger_dir())
        ledgers, self.unreadable = load_all(d)
        self.meta = _verifier_meta()
        self.case_scoped = _case_scoped(self.meta)
        self.active = [(s, led) for s, led in sorted(ledgers.items()) if led.rows]
        for _s, led in self.active:
            led.index()
        self.entries = {s: len(led.rows) for s, led in self.active}
        self.attached = Counter()

    def attach(self, row: dict) -> None:
        from foreclosure_scraper.verification.apply import attachable, find_entry
        from foreclosure_scraper.verification.core import records_of, row_keys
        try:
            keys = row_keys(row)
        except Exception:  # noqa: BLE001
            return
        found = {}
        for sig, led in self.active:
            try:
                _k, entry = find_entry(led, row, keys, self.case_scoped.get(sig))
            except Exception:  # noqa: BLE001
                continue
            if entry is None:
                continue
            rec = attachable(entry, self.meta)
            if rec is not None:
                found[sig] = rec
        if not found:
            return
        raw = row.get("raw")
        if not isinstance(raw, dict):
            raw = row["raw"] = {}
        keep = [r for r in records_of(raw) if r.get("signal") not in found]
        raw["verification"] = sorted(keep + list(found.values()), key=lambda r: str(r.get("signal")))
        for s in found:
            self.attached[s] += 1


# ---------------------------------------------------------------------------------------------
# reading a board or a checkpoint
# ---------------------------------------------------------------------------------------------

def iter_rows(path: Optional[Path]) -> Iterator[dict]:
    """The live board (docs/) or a checkpoint directory (board.json.gz + manifest.json), one row at a
    time, in the published shape (a checkpoint row goes through web_artifact._to_dict)."""
    if path is not None and (Path(path) / "board.json.gz").is_file() and (Path(path) / "manifest.json").is_file():
        from board_selfcheck import _checkpoint_rows
        yield from _checkpoint_rows(Path(path))
        return
    from foreclosure_scraper.board_stream import iter_board_rows
    src = Path(path) / "listings.json.gz" if path is not None else REPO / "docs" / "listings.json.gz"
    yield from iter_board_rows(src)


def digits10(v: Any) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d[1:] if len(d) == 11 and d.startswith("1") else d


def property_key(row: dict) -> str:
    from foreclosure_scraper.verification.core import row_key
    try:
        return row_key(row)
    except Exception:  # noqa: BLE001
        return f"row:{row.get('source_url')}"


# ---------------------------------------------------------------------------------------------
# the sheet's words (built only from checked facts)
# ---------------------------------------------------------------------------------------------

def _first_name(owner: str) -> str:
    """A best-effort first name for 'Hi, is this ...?' from a roll name (LAST, FIRST or LAST FIRST)."""
    s = re.sub(r"\s+", " ", str(owner or "")).strip()
    if "," in s:
        rest = s.split(",", 1)[1].strip().split(" ")
        return rest[0].title() if rest and rest[0] else ""
    parts = s.split(" ")
    if s.isupper() and len(parts) >= 2:
        return parts[1].title()           # county rolls write LAST FIRST
    return parts[0].title() if parts else ""


def say_this(row: dict, blk: dict) -> str:
    """The call opener (Fullmer / Ajay, ep 021 and the book: ask if it is a bad time, say who you are
    plainly, name the problem from the record, ask for five minutes), from checked facts only."""
    f = blk.get("facts") or {}
    addr = row.get("street_address") or "your property"
    lane = blk.get("lane")
    if lane == "A":
        n = f.get("years_delinquent") or 0
        problem = (f"the county tax office shows {n} year{'s' if n != 1 else ''} of unpaid property tax on "
                   f"{addr}, about ${f.get('total_delinquent') or 0:,.0f} in total, as of {f.get('tax_checked_on')}")
    elif lane == "B":
        problem = (f"the county has the estate of the owner of {addr} in probate, and I understand you may be "
                   f"handling it")
    else:
        problem = f"the county record for {addr}"
    who = _first_name(row.get("owner_name") or "")
    hello = f"Hi, is this {who}? " if who and lane == "A" else "Hi, "
    confirm = ("Before anything else, can I confirm I'm speaking with the owner of the property? "
               if blk.get("tier") == "B" else "")
    return (f"{hello}Is this a bad time? {confirm}My name is ___, I'm a local real estate operator, not an "
            f"attorney. I'm calling because {problem}. I work with owners to clear that kind of problem "
            f"and can buy the property as it is, or simply point you to the right people. Would it be "
            f"worth five minutes to talk about it?")


def before_dialing(row: dict, blk: dict, shared: int) -> str:
    f = blk.get("facts") or {}
    steps = []
    if blk.get("lane") == "A":
        steps.append(f"Open the county tax site, search parcel {row.get('parcel_id') or row.get('street_address')}, "
                     f"confirm the unpaid years still show (checked {f.get('tax_checked_on')}); skip if paid.")
    if blk.get("lane") == "B":
        steps.append("Confirm the estate is still open on the clerk's estate index before writing or calling.")
    if blk.get("tier") in ("A", "B") and blk.get("dnc") in (None, "not_scrubbed", "unverified"):
        steps.append("Scrub the number against the National Do Not Call list first.")
    if blk.get("tier") == "C":
        steps.append("Mail first (no phone a closer may dial is tied to this lead); use the opener if they call back.")
    if blk.get("tier") == "B":
        steps.append("The phone matches by name only: confirm identity in the first sentence.")
    if shared:
        steps.append(f"This number is also on records of {shared} other owner name(s): confirm the person.")
    return " ".join(steps)


PHONE_CHECK = {"tied": "tied to this property/owner record",
               "name_match_only": "name match only: confirm you have the right person at the start of the call",
               "other_record": "phone record is another person's or property's: do not use",
               "not_owner": "not the owner's phone (agent, people-search or do-not-dial)",
               "unlinked": "nothing ties this phone to the owner", "none": "no phone"}
MAIL_CHECK = {"ok": "ok", "missing": "no mailing address on record",
              "other_record": "mailing record is for another property: verify the mailing address",
              "malformed": "mailing address incomplete"}


def estate_contact(raw: dict) -> str:
    out = []
    for key in ("probate", "sc_probate_notice"):
        b = raw.get(key)
        if isinstance(b, dict) and str(b.get("personal_representative") or "").strip():
            out.append(f"{b.get('personal_representative')} ({b.get('pr_role') or 'personal representative'})"
                       + (f", {b.get('pr_address')}" if b.get("pr_address") else ""))
    he = raw.get("heir_estate")
    if isinstance(he, dict) and he.get("care_of"):
        out.append(f"care of {he.get('care_of')}" + (f", {he.get('mailing')}" if he.get("mailing") else ""))
    return " | ".join(dict.fromkeys(out))


def heir_text(raw: dict) -> str:
    hc = raw.get("heir_candidates")
    if not isinstance(hc, list):
        return ""
    return " | ".join(f"{c.get('name')} ({c.get('relation')}, {c.get('source_kind')}, {c.get('source_date') or 'undated'})"
                      for c in hc if isinstance(c, dict) and c.get("name"))[:600]


def checks_text(blk: dict) -> str:
    return "; ".join(f"{c.get('check')}: {c.get('result')} on {c.get('on')} ({c.get('source')})"
                     for c in blk.get("checks") or [])


def tax_url(raw: dict) -> str:
    rec = CR.record(raw, "tax_lien")
    ev = (rec or {}).get("evidence") or {}
    return str(ev.get("page_url") or ev.get("url") or "")


def sheet_row(row: dict, blk: dict, shared: int) -> dict:
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    op = raw.get("owner_phone") if isinstance(raw.get("owner_phone"), dict) else {}
    om = raw.get("owner_mailing") if isinstance(raw.get("owner_mailing"), dict) else {}
    f = blk.get("facts") or {}
    rec = CR.record(raw, "tax_lien") or {}
    usable_phone = blk.get("phone") in ("tied", "name_match_only")
    return {
        "state": row.get("state"), "county": row.get("county"), "parcel_id": row.get("parcel_id"),
        "property_address": row.get("street_address"), "owner_of_record": row.get("owner_name"),
        "owner_mailing_address": CR.mailing_text(raw), "absentee_owner": om.get("absentee"),
        "phone": op.get("phone") if usable_phone else "", "line_type": op.get("line_type"),
        "phone_source": op.get("source"), "phone_match": op.get("match"), "tcpa_class": op.get("tcpa_class"),
        "needs_dnc_scrub": op.get("needs_dnc_scrub"),
        "county_confirmed_years_delinquent": f.get("years_delinquent") if f.get("tax_verdict") == "confirmed" else "",
        "county_confirmed_total_owed": f.get("total_delinquent") if f.get("tax_verdict") == "confirmed" else "",
        "county_checked_at": rec.get("checked_at") or "", "county_site_verifier": rec.get("verifier") or "",
        "assessed_value": row.get("assessed_value"), "year_built": row.get("year_built"),
        "say_this": say_this(row, blk), "before_dialing": before_dialing(row, blk, shared),
        "phone_check": PHONE_CHECK.get(blk.get("phone") or "none", ""),
        "mailing_check": MAIL_CHECK.get(blk.get("mail") or "missing", ""),
        "phone_also_on_other_rows": (f"yes ({shared} other owner names)" if shared else "no") if usable_phone else "",
        "tier": blk.get("tier"), "lane": blk.get("lane"), "lane_name": CR.LANES.get(blk.get("lane"), ""),
        "tier_name": CR.TIERS.get(blk.get("tier"), ""), "rank": blk.get("rank"), "reason": blk.get("reason"),
        "unmet": "; ".join(CR.unmet_words(blk.get("unmet") or [])), "dnc_status": blk.get("dnc") or "",
        "checks": checks_text(blk), "county_tax_url": tax_url(raw), "estate_contact": estate_contact(raw),
        "heir_candidates": heir_text(raw),
        "lawyer_list": "; ".join(f"{k}: {v}" for k, v in (blk.get("lawyer") or {}).items()),
        "evidence_sheet_cmd": (f"uv run python scripts/lead_evidence_sheet.py --parcel "
                               f"'{row.get('parcel_id') or ''}' --county '{row.get('county') or ''}'"),
    }


# ---------------------------------------------------------------------------------------------
# the passes
# ---------------------------------------------------------------------------------------------

class PhoneOwners:
    """phone digits -> how many DIFFERENT owner names (token sets sharing no token) carry it on
    owner_phone across the board. Bounded: at most 50 name sets per phone."""

    def __init__(self):
        self.owners: dict[str, set] = defaultdict(set)

    def feed(self, row: dict) -> None:
        from foreclosure_scraper.block_binding import name_tokens
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        op = raw.get("owner_phone")
        if isinstance(op, dict):
            d = digits10(op.get("phone"))
            if len(d) == 10:
                t = name_tokens(row.get("owner_name"))
                if t and len(self.owners[d]) < 50:
                    self.owners[d].add(t)

    def counts(self) -> dict[str, int]:
        out = {}
        for d, sets in self.owners.items():
            groups: list[frozenset] = []
            for s in sets:
                if not any(s & g for g in groups):
                    groups.append(s)
            if len(groups) > 1:
                out[d] = len(groups)
        return out


def phone_owner_counts(path: Optional[Path]) -> dict[str, int]:
    po = PhoneOwners()
    for row in iter_rows(path):
        po.feed(row)
    return po.counts()


def run(path: Optional[Path], today: date, attach: bool, keep_rows: bool, ledger_dir: Optional[Path] = None) -> dict:
    """One pass: counts for every row, the lane A / B rows kept (one per property), and the phones'
    owner counts (patched into the kept rows after the pass)."""
    att = LedgerAttacher(ledger_dir) if attach else None
    po = PhoneOwners() if keep_rows else None
    lane_tier: Counter = Counter()
    unmet_by_lane: dict[str, Counter] = defaultdict(Counter)
    first_unmet: dict[str, Counter] = defaultdict(Counter)
    only_unmet: dict[str, Counter] = defaultdict(Counter)        # the one condition between a row and readiness
    only_by_county: Counter = Counter()                          # lane A: tax check missing, nothing else
    lawyer_combo: Counter = Counter()
    by_state: Counter = Counter()
    errors = Counter()
    kept: dict[str, tuple] = {}
    n = 0
    t0 = time.time()
    for row in iter_rows(path):
        n += 1
        if po is not None:
            po.feed(row)
        if att is not None:
            att.attach(row)
        blk = CR.call_ready(row, today)
        if blk.get("error"):
            errors[blk["error"]] += 1
        lane, tier = blk.get("lane") or "-", blk.get("tier")
        lane_tier[f"{lane}/{tier}"] += 1
        if lane != "-":
            by_state[f"{row.get('state')}:{lane}/{tier}"] += 1
            if tier != "A":
                for u in blk.get("unmet") or []:
                    unmet_by_lane[lane][u] += 1
                hard = CR.hard_unmet(blk)
                if hard:
                    first_unmet[lane][hard[0]] += 1
                if tier == "D" and len(hard) == 1:
                    only_unmet[lane][hard[0]] += 1
                    if lane == "A" and hard[0] == "tax_check_missing":
                        only_by_county[f"{row.get('state')}:{row.get('county')}:{blk.get('phone')}"] += 1
            if lane == "C":
                lawyer_combo[",".join(k + ("(walled)" if v == "walled" else "") for k, v in (blk.get("lawyer") or {}).items()
                                     if v in ("missing", "walled")) or "complete"] += 1
        if keep_rows and lane in ("A", "B"):
            k = property_key(row)
            score = (TIER_ORDER.get(tier, 9), -(blk.get("rank") or 0))
            if k not in kept or score < kept[k][0]:
                raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
                op = raw.get("owner_phone") if isinstance(raw.get("owner_phone"), dict) else {}
                mini = {"parcel_id": row.get("parcel_id"), "street_address": row.get("street_address")}
                kept[k] = (score, sheet_row(row, blk, 0), digits10(op.get("phone")), mini, blk)
    if po is not None:
        phones = po.counts()
        for k, (score, sheet, d, mini, blk) in list(kept.items()):
            shared = max(0, phones.get(d, 0) - 1)
            if shared and sheet.get("phone"):
                sheet["phone_also_on_other_rows"] = f"yes ({shared} other owner names)"
                sheet["before_dialing"] = before_dialing(mini, blk, shared)
            kept[k] = (score, sheet)
    return {"rows": n, "seconds": round(time.time() - t0), "lane_tier": dict(sorted(lane_tier.items())),
            "by_state": dict(sorted(by_state.items())),
            "unmet_by_lane": {k: dict(v.most_common(25)) for k, v in sorted(unmet_by_lane.items())},
            "first_unmet_by_lane": {k: dict(v.most_common(15)) for k, v in sorted(first_unmet.items())},
            "only_unmet_by_lane": {k: dict(v.most_common(15)) for k, v in sorted(only_unmet.items())},
            "lane_a_only_tax_check_missing_by_county_phone": dict(only_by_county.most_common(40)),
            "lane_c_lawyer_missing_combos": dict(lawyer_combo.most_common(12)),
            "errors": dict(errors), "ledgers": (att.entries if att else {}),
            "attached": (dict(att.attached) if att else {}), "kept": kept}


def write_outputs(res: dict, today: date, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [r for _s, r in sorted(res["kept"].values(), key=lambda x: (x[0], -(float(x[1].get("county_confirmed_total_owed") or 0))))]
    ready = [r for r in rows if r["tier"] in ("A", "B") or (r["lane"] == "B" and r["tier"] == "C")]
    not_ready = [r for r in rows if r not in ready]
    paths = {"ready": out_dir / f"Call_List_{today.isoformat()}.csv",
             "not_ready": out_dir / f"Call_List_{today.isoformat()}_not_ready.csv",
             "summary": out_dir / f"Call_List_{today.isoformat()}_summary.json"}
    for key, data in (("ready", ready), ("not_ready", not_ready)):
        with open(paths[key], "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
    summ = {k: v for k, v in res.items() if k != "kept"}
    summ.update({"date": today.isoformat(), "ready_rows": len(ready), "not_ready_rows": len(not_ready),
                 "ready_by_lane_tier": dict(Counter(f"{r['lane']}/{r['tier']}" for r in ready))})
    paths["summary"].write_text(json.dumps(summ, indent=1, default=str))
    return {k: str(v) for k, v in paths.items()} | {"ready_rows": len(ready), "not_ready_rows": len(not_ready)}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", help="a board directory (docs/) or a checkpoint directory; default the live board")
    ap.add_argument("--out", default=str(OUT_DIR), help="output folder (default ~/Desktop/Call_Sheets)")
    ap.add_argument("--date", help="the day to judge against (YYYY-MM-DD; default today, local)")
    ap.add_argument("--no-ledgers", action="store_true", help="judge the rows as published (no ledger attach)")
    ap.add_argument("--ledger-dir", help="verification ledger directory (default docs/handoff/verification)")
    ap.add_argument("--count-only", action="store_true", help="print the counts as JSON; write nothing")
    a = ap.parse_args(argv)
    today = date.fromisoformat(a.date) if a.date else date.today()
    path = Path(a.board).expanduser() if a.board else None
    out = Path(a.out).expanduser()
    try:
        out.resolve().relative_to(REPO)
        if not a.count_only:
            print("Refusing to write the call list inside the repository (it holds names and phones).",
                  file=sys.stderr)
            return 2
    except ValueError:
        pass
    res = run(path, today, attach=not a.no_ledgers, keep_rows=not a.count_only,
              ledger_dir=Path(a.ledger_dir) if a.ledger_dir else None)
    if a.count_only:
        print(json.dumps({k: v for k, v in res.items() if k != "kept"}, indent=1, default=str))
        return 0
    paths = write_outputs(res, today, out)
    print(json.dumps({"lane_tier": res["lane_tier"], **paths}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
