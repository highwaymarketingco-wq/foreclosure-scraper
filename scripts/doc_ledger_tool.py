#!/usr/bin/env python3
"""The processed-documents ledger (src/foreclosure_scraper/doc_ledger.py): seed, merge, report.

    # record what the published board already carries (doc_ocr, dot_ocr, vision results), so
    # the ledger starts complete and the documents_images audit can require an entry for every
    # processed document. One streamed, read-only board pass; idempotent (an entry that exists
    # is left alone).
    .venv/bin/python scripts/doc_ledger_tool.py seed [--board docs/listings.json.gz]

    # merge another copy of a lane's ledger (the VM's, a backup) into the repo's
    .venv/bin/python scripts/doc_ledger_tool.py merge --lane doc_ocr path/to/doc_ocr.json

    # counts by lane, outcome, source and reason
    .venv/bin/python scripts/doc_ledger_tool.py report

Public-safe: seeding writes only hashes, outcomes and PUBLIC_VALUE_KEYS values to
docs/handoff/documents/; names and addresses read off documents go to the git-ignored
data/doc_ledger/ private store.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import doc_inventory as inv  # noqa: E402
from foreclosure_scraper import doc_ledger as dl  # noqa: E402


class _Row:
    """The attribute view of a board row the vision selectors need."""

    def __init__(self, row: dict) -> None:
        self.raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        self.source_url = row.get("source_url")


def _board_time(board: Path) -> str:
    try:
        man = json.loads((board.parent / "board.manifest.json").read_text())
        return str(man.get("run_time") or man.get("written_at") or "")[:19] + "Z"
    except Exception:  # noqa: BLE001
        return dl._iso(dl._utc_now())


def seed(board: Path) -> dict:
    from foreclosure_scraper.board_stream import iter_board_rows_with_detail
    from foreclosure_scraper.enrichment_vision import (VISION_LEDGER_VERSION, _ledger_values,
                                                       _select_image_urls)
    # The doc and dot reads on a board before 2026-10-09 were made by the earlier extractors:
    # seeded under v1 so the next run re-reads them once with the current rules (doc OCR:
    # notice-to-creditors dates and addresses, the lead-binding check, lot numbers in rosters;
    # see docs/audit_2026-10-09/documents_images.md). The vision grading is unchanged.
    DOC_OCR_VERSION, DOC_OCR_AGG_VERSION, DOT_OCR_VERSION = (
        "doc_ocr-v1", "doc_ocr_agg-v1", "dot_ocr-v1")

    when = dl._parse(_board_time(board)) or dl._utc_now()
    reason = f"seeded_from_board_{when.date().isoformat()}"
    leds = {lane: dl.DocLedger.load(lane) for lane in dl.LANES}
    for led in leds.values():
        led.persistent = True
        led.private.persistent = True
    c = Counter()
    rows_per_roster: Counter = Counter()
    roster_filled: Counter = Counter()
    roster_meta: dict = {}
    for row in iter_board_rows_with_detail(str(board), keys=("vision",)):
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        src = row.get("source")
        county = f"{row.get('state') or '?'}:{row.get('county') or '?'}"
        d = raw.get("doc_ocr")
        if isinstance(d, dict):
            # the document the pre-2026-10-09 reader actually read was the legacy primary
            urls = inv.legacy_ocr_doc_urls(row) or inv.ocr_doc_urls(row)
            if urls:
                key = inv.doc_key(urls[0])
                if d.get("_source") == "aggregate_row_match":
                    rows_per_roster[key] += 1
                    roster_filled[key] += 1
                    roster_meta.setdefault(key, (urls[0], src))
                elif key not in leds["doc_ocr"].rows:
                    fields = [k for k in ("owner_name", "co_owner_name", "property_address", "city",
                                          "zip", "sale_date", "amount", "case_number", "doc_type")
                              if d.get(k) not in (None, "", [], {})]
                    leds["doc_ocr"].record(key, outcome="extracted" if fields else "no_fields",
                                           version=DOC_OCR_VERSION, category="notice",
                                           url=urls[0], source=src, county=county,
                                           provider=d.get("_provider"), fields=fields,
                                           values=d, reason=reason, now=when)
                    c["doc_ocr"] += 1
        if isinstance(raw.get("dot_ocr"), dict) and str(row.get("owner_name") or "").strip():
            dd = raw["dot_ocr"]
            key = inv.owner_search_key(str(row.get("state") or ""), str(row.get("county") or ""),
                                       str(row.get("owner_name") or ""))
            if key not in leds["dot_ocr"].rows:
                leds["dot_ocr"].record(key, outcome="loan_found", version=DOT_OCR_VERSION,
                                       category="dot_image", source=src, county=county,
                                       provider=dd.get("provider"), fields=["loan_amount"],
                                       landed=["loan_amount", "rod_docs"],
                                       values={"loan_amount": dd.get("loan_amount"),
                                               "doc_type": dd.get("doc_type"),
                                               "recorded_date": dd.get("recorded_date"),
                                               "book": dd.get("book"), "page": dd.get("page"),
                                               "instrument_no": dd.get("instrument_no")},
                                       reason=reason, now=when)
                c["dot_ocr"] += 1
        v = raw.get("vision")
        if isinstance(v, dict):
            # the row's current image set, else the set the report says it graded
            urls = _select_image_urls(_Row(row)) or [u for u in (v.get("_image_urls") or [])
                                                       if isinstance(u, str)]
            if urls:
                key = inv.image_set_key(urls)
                if key not in leds["vision"].rows:
                    landed = ["condition_tier"] if str(raw.get("condition_source") or "").startswith("vision") else []
                    leds["vision"].record(key, outcome="graded", version=VISION_LEDGER_VERSION,
                                          source=src, county=county,
                                          provider=v.get("_provider"),
                                          landed=landed, values=_ledger_values(v),
                                          reason=reason, now=when)
                    c["vision"] += 1
    for key, n in rows_per_roster.items():
        if key in leds["doc_ocr"].rows:
            continue
        url, src = roster_meta[key]
        leds["doc_ocr"].record(key, outcome="aggregate_read", version=DOC_OCR_AGG_VERSION,
                               category="roster", url=url, source=src,
                               fields=["street_address"], landed=["street_address"],
                               values={"rows_filled": roster_filled[key]},
                               reason=reason, now=when)
        c["doc_ocr_roster"] += 1
    for lane, led in leds.items():
        led.last_run = {"at": dl._iso(dl._utc_now()), "seeded": dict(c), "board_time": _board_time(board)}
        led.save()
    return dict(c)


def report() -> dict:
    out = {}
    for lane in dl.LANES:
        led = dl.DocLedger.load(lane)
        by = Counter()
        reasons = Counter()
        for e in led.rows.values():
            by[(e.get("outcome"), e.get("source") or "?")] += 1
            if e.get("reason"):
                reasons[(e.get("outcome"), e["reason"].split(":")[0][:40])] += 1
        out[lane] = {"counts": led.counts(),
                     "by_outcome_source": {f"{o}|{s}": n for (o, s), n in by.most_common(40)},
                     "reasons": {f"{o}|{r}": n for (o, r), n in reasons.most_common(20)}}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--board", default=str(REPO / "docs" / "listings.json.gz"))
    m = sub.add_parser("merge")
    m.add_argument("--lane", required=True, choices=dl.LANES)
    m.add_argument("path")
    sub.add_parser("report")
    a = ap.parse_args()
    if a.cmd == "seed":
        print(json.dumps(seed(Path(a.board)), indent=1))
    elif a.cmd == "merge":
        led = dl.DocLedger.load(a.lane)
        led.persistent = True
        led.merge_from(dl.DocLedger.load_file(Path(a.path), a.lane))
        print(led.save(), led.counts())
    else:
        print(json.dumps(report(), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
