#!/usr/bin/env python3
"""Put back, into a pre_publish checkpoint, the owner phones the comparison's best-of-both list
says the live board held and the candidate lost, when the CURRENT binding rules keep them.

WHY (audit 2026-10-09, phones_lost; docs/audit_2026-10-09/phones_lost.md)
    scripts/compare_boards.py writes `--best-of-both-out`: one JSON line per good live value the
    candidate lost ({"field", "candidate_ref", "baseline_ref"}). For the phone field most of those
    losses were block_binding removing another person's phone on purpose; some were defects since
    fixed (address_key read the row's own house as another address; the scrub judged a person on a
    block it removed in the same round). A fixed rule only acts on the NEXT run; this puts the good
    phones back into the checkpoint that is about to be published, without a run.

WHAT IT DOES (three streaming passes, one row at a time; nothing is loaded whole)
    1. the live board: the rows behind the phone entries' baseline refs (owner_phone kept);
    2. the checkpoint, read as compare_boards reads it (Listing.model_validate + _to_dict): the
       rows behind the candidate refs, and every LiensNC-filing phone on the board (filer's line);
    3. decides per entry: the candidate row has no phone; the live row's owner_phone (with its
       LiensNC filing when the candidate lacks one) is put on a copy of the candidate row and
       block_binding.scrub_row keeps it; a filing phone is not the filer's line
       (block_binding.filing_line_rows over the checkpoint plus this row);
    4. writes <out>/board.json.gz (the checkpoint's own rows, the restored blocks added, each
       marked owner_phone['restored'] = {'from': 'live_board', 'by': this script}) and copies the
       manifest (adding best_of_both_restored), resume_state.json and sold_pool.json.gz, so
       vm_resume.sh --publish-only and compare_boards read it like the original.
    It never writes to the input checkpoint, docs/ or the VM. --dry-run decides and reports only.

USAGE
    python3 scripts/restore_best_of_both_phones.py --best-of-both logs/compare-X.best_of_both.jsonl \
        --live docs --checkpoint data/checkpoint --out data/checkpoint_restored [--dry-run]
Prints a JSON summary (counts by decision; no names, phones or addresses).
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import compare_boards as CB  # noqa: E402
from foreclosure_scraper import block_binding as BB  # noqa: E402
from foreclosure_scraper.board_parts import iter_gz_rows  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.verification.core import row_keys  # noqa: E402
from foreclosure_scraper.web_artifact import _to_dict  # noqa: E402

#: blocks the phone came from (block_binding._dependents): put back with it when the candidate lacks
#: them (the filing for a liensnc_filing phone; the OCR for an ocr_* phone, which is then refused)
WITH_PHONE = ("liensnc", "ocr_extraction")


def _raw(rec: dict) -> dict:
    r = rec.get("raw")
    return r if isinstance(r, dict) else {}


def _digits(op) -> str:
    import re
    return re.sub(r"\D", "", str((op or {}).get("phone") or ""))[-10:] if isinstance(op, dict) else ""


def refs_of(rec: dict) -> set[str]:
    """Both refs compare_boards may have written for a row: row_ref on its row_keys and on its join
    keys without the fingerprint (Facts.ref)."""
    out = set()
    try:
        out.add(CB.row_ref(rec, row_keys(rec)))
    except Exception:  # noqa: BLE001
        pass
    try:
        out.add(CB.row_ref(rec, [k for k in CB.join_keys(rec) if not k.startswith("fp:")] or None))
    except Exception:  # noqa: BLE001
        pass
    return out


def load_entries(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if '"phone"' not in line:
                continue
            d = json.loads(line)
            if d.get("field") == "phone":
                out.append(d)
    return out


def published(rec: dict):
    try:
        return _to_dict(Listing.model_validate(rec))
    except Exception:  # noqa: BLE001 - checkpoint.load() skips such a row too
        return None


def candidate_block(live: dict, cand: dict) -> dict:
    """{block: value} to put on the candidate row: the live owner_phone and the blocks it came
    from that the candidate lacks."""
    lraw, craw = _raw(live), _raw(cand)
    op = lraw["owner_phone"]
    out = {"owner_phone": copy.deepcopy(op)}
    src = str(op.get("source") or "")
    for k in WITH_PHONE:
        mine = (k == "liensnc" and src in BB._FILING_SOURCES) or (k == "ocr_extraction" and src.startswith("ocr_"))
        if mine and k in lraw and k not in craw:
            out[k] = copy.deepcopy(lraw[k])
    return out


def kept_by_rules(cand_pub: dict, blocks: dict) -> bool:
    row = copy.deepcopy(cand_pub)
    row.setdefault("raw", {}).update(copy.deepcopy(blocks))
    rec: list = []
    BB.scrub_row(row, BB.row_verdicts(row, set()), None, rec, 0, unbound=set(), points=set())
    return "owner_phone" in _raw(row)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--best-of-both", type=Path, required=True)
    ap.add_argument("--live", type=Path, default=REPO / "docs")
    ap.add_argument("--checkpoint", type=Path, default=REPO / "data" / "checkpoint")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.dry_run and not a.out:
        ap.error("--out is required unless --dry-run")
    if a.out and a.out.resolve() == a.checkpoint.resolve():
        ap.error("--out must not be the input checkpoint")

    entries = load_entries(a.best_of_both)
    want_live = {e["baseline_ref"] for e in entries}
    want_cand = {e["candidate_ref"] for e in entries}

    # 1. live rows behind the baseline refs
    live: dict[str, list[dict]] = defaultdict(list)
    for rec in iter_board_rows(a.live / "listings.json.gz"):
        if not _digits(_raw(rec).get("owner_phone")):
            continue
        for r in refs_of(rec) & want_live:
            if len(live[r]) < 8:
                live[r].append(rec)

    # 2. candidate rows behind the candidate refs (published shape) + filing phones board-wide
    cand: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    lines: dict[str, list] = defaultdict(list)
    holders: dict[str, list] = defaultdict(list)      # phone -> owner tokens of rows carrying it
    board = a.checkpoint / "board.json.gz"
    for i, rec in enumerate(iter_gz_rows(board)):
        pub = published(rec)
        if pub is None:
            continue
        op = _raw(pub).get("owner_phone")
        d = _digits(op)
        if d and len(holders[d]) < 20:
            holders[d].append(BB.name_tokens(pub.get("owner_name")))
        v = BB.filing_contact_value("owner_phone", op)
        if v:
            fo = BB.filing_persons(pub, "owner_phone", op)
            lines[v].append((i, BB.name_tokens(fo[0]) if fo else frozenset()))
        for r in refs_of(pub) & want_cand:
            if len(cand[r]) < 8:
                cand[r].append((i, pub))

    # 3. decide
    restore: dict[int, dict] = {}
    why: Counter = Counter()
    for e in entries:
        lrows, crows = live.get(e["baseline_ref"], []), cand.get(e["candidate_ref"], [])
        if not lrows or not crows:
            why["not_found"] += 1
            continue
        lv = lrows[0]
        same = [c for c in crows if c[1].get("source") == lv.get("source")
                and c[1].get("street_address") == lv.get("street_address")]
        same = same or [c for c in crows if c[1].get("source") == lv.get("source")] or crows
        idx, pub = same[0]
        if any(_digits(_raw(p).get("owner_phone")) for _i, p in crows):
            why["candidate_has_a_phone"] += 1
            continue
        if idx in restore:
            why["duplicate_entry"] += 1
            continue
        if BB.names_disagree(lv.get("owner_name"), pub.get("owner_name")):
            # the row's owner changed between the boards: the phone was found for the old one
            why["owner_changed"] += 1
            continue
        blocks = candidate_block(lv, pub)
        if "ocr_extraction" in blocks:
            # the run's OCR scrub took the document off the row (a roster many rows share:
            # enrichment_ocr.shared_documents); its phone is the office's, not the owner's
            why["source_document_scrubbed"] += 1
            continue
        own = BB.name_tokens(pub.get("owner_name"))
        if any(t and own and not (t & own) for t in holders.get(_digits(blocks["owner_phone"]), [])):
            # the same number is another owner's on the checkpoint (block_binding's shared test)
            why["shared_with_another_owner"] += 1
            continue
        if not kept_by_rules(pub, blocks):
            why["removed_by_current_rules"] += 1
            continue
        op = blocks["owner_phone"]
        v = BB.filing_contact_value("owner_phone", op)
        if v:
            row = copy.deepcopy(pub)
            row.setdefault("raw", {}).update(blocks)
            fo = BB.filing_persons(row, "owner_phone", op)
            members = lines.get(v, []) + [(-1 - idx, BB.name_tokens(fo[0]) if fo else frozenset())]
            if (-1 - idx) in BB.filing_line_rows(members):
                why["filers_line"] += 1
                continue
        op["restored"] = {"from": "live_board", "by": "restore_best_of_both_phones"}
        restore[idx] = blocks
        why["restored"] += 1
        why["restored:" + str(op.get("source") or "-")] += 1

    summary = {"entries": len(entries), "decisions": dict(why), "rows_restored": len(restore),
               "dry_run": a.dry_run}
    if a.dry_run:
        print(json.dumps(summary, indent=1))
        return 0

    # 4. write the new checkpoint
    a.out.mkdir(parents=True, exist_ok=True)
    tmp = a.out / "board.json.gz.tmp"
    n = 0
    with gzip.open(tmp, "wt", encoding="utf-8") as out:
        out.write("[")
        for i, rec in enumerate(iter_gz_rows(board)):
            if i in restore:
                raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
                raw.update(restore[i])
                rec["raw"] = raw
            if n:
                out.write(", ")
            out.write(json.dumps(rec))
            n += 1
        out.write("]")
    tmp.replace(a.out / "board.json.gz")
    man = json.loads((a.checkpoint / "manifest.json").read_text())
    if man.get("count") != n:
        print(f"refused: wrote {n} rows, the manifest says {man.get('count')}", file=sys.stderr)
        return 1
    man["best_of_both_restored"] = {"phone": len(restore), "from": a.best_of_both.name}
    (a.out / "manifest.json").write_text(json.dumps(man, indent=1))
    for f in ("resume_state.json", "sold_pool.json.gz"):
        if (a.checkpoint / f).exists():
            shutil.copy2(a.checkpoint / f, a.out / f)
    summary["out"] = str(a.out)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
