#!/usr/bin/env python3
"""Inventory of every document and image URL on the published board, and what became of it.

One read-only streamed pass (board_stream.iter_board_rows_with_detail, with the 'vision' detail
key), counts only: no names, no notice text, no URLs in the output. Repeatable:

    .venv/bin/python scripts/doc_image_inventory.py [--board docs/listings.json.gz]
        [--out docs/audit_2026-10-09/documents_images_inventory.json] [--no-ledger]

For each document category (doc_inventory.DOC_CATEGORIES) and image category, by source and by
county: rows holding a URL, rows whose URL was processed (doc OCR / dot OCR / vision / the
scraper's own parse / the assessor-card parser), rows where a processed result landed in a
column, and the unprocessed backlog with its reason:

  outer_phase_cap      enrich_doc_ocr was cut by main._await_capped's 900 s default before its own
                       2400 s budget (2026-10-07 full run: enrich.time_capped phase=doc_ocr)
  aggregate_never_run  a roster row lacking an address whose roster the aggregate pass never
                       reached (it ran after the per-lead loop, inside the same cut budget)
  count_cap / breaker  vision: past VISION_MAX_LISTINGS, or inside the cap but left when the
                       fetch-failing breaker stopped the pass
  fetch_failed         vision_fetch_failed marker on the row
  no_reader            nothing in the pipeline reads this category (deed/plat images)
  not_a_document       a search link (env_search) or an HTML page
  card_unparsed        an assessor card URL with no parsed field
  ledger_*             the processed-documents ledger's own outcome, when it has one
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import doc_inventory as inv  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows_with_detail  # noqa: E402

DOT_COUNTIES = None


def _dot_counties() -> set:
    global DOT_COUNTIES
    if DOT_COUNTIES is None:
        try:
            from foreclosure_scraper.rod.doc_images import DOC_IMAGE_COUNTIES
            DOT_COUNTIES = set(DOC_IMAGE_COUNTIES)
        except Exception:  # noqa: BLE001
            DOT_COUNTIES = set()
    return DOT_COUNTIES


def _norm(s) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _tier(raw: dict) -> str:
    ds = raw.get("distress_stack")
    return str((ds or {}).get("tier") or "COLD") if isinstance(ds, dict) else "COLD"


class Tally:
    """Nested counters: tally[category][dimension][value][measure]."""

    def __init__(self) -> None:
        self.t: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))

    def add(self, cat: str, source: str, county: str, measure: str, n: int = 1) -> None:
        self.t[cat]["total"]["all"][measure] += n
        self.t[cat]["source"][source][measure] += n
        self.t[cat]["county"][county][measure] += n

    def as_dict(self, top: int = 40) -> dict:
        out = {}
        for cat, dims in self.t.items():
            o = {"total": dict(dims["total"]["all"])}
            for dim in ("source", "county"):
                items = sorted(dims[dim].items(), key=lambda kv: -kv[1].get("rows", 0))
                o[dim] = {k: dict(v) for k, v in items[:top]}
                o[f"{dim}_count"] = len(items)
            out[cat] = o
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default=str(REPO / "docs" / "listings.json.gz"))
    ap.add_argument("--out", default=str(REPO / "docs" / "audit_2026-10-09" /
                                         "documents_images_inventory.json"))
    ap.add_argument("--vision-cap", type=int, default=2500,
                    help="VISION_MAX_LISTINGS of the run that produced the board")
    ap.add_argument("--no-ledger", action="store_true",
                    help="the board alone (what the run left), ignoring the processed-documents ledger")
    args = ap.parse_args()

    try:
        if args.no_ledger:
            raise RuntimeError("--no-ledger")
        from foreclosure_scraper import doc_ledger
        ledgers = {lane: doc_ledger.DocLedger.load(lane) for lane in doc_ledger.LANES}
    except Exception:  # noqa: BLE001
        ledgers = {}

    t0 = time.time()
    docs = Tally()
    imgs = Tally()
    ocr_rows: list = []              # rows with a doc-OCR document (compact, no names)
    url_rows: Counter = Counter()    # normalized primary OCR url -> rows
    vis_backlog: list = []           # gradable-photo rows without a vision result
    landing = Counter()
    dot = Counter()
    n = 0
    for row in iter_board_rows_with_detail(args.board, keys=("vision",)):
        n += 1
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        src = str(row.get("source") or "?")
        county = f"{row.get('state') or '?'}:{row.get('county') or '?'}"
        tier = _tier(raw)

        # ---------------- documents ----------------
        refs = inv.document_refs(row)
        cats = Counter(c for c, _ in refs)
        dococr = raw.get("doc_ocr") if isinstance(raw.get("doc_ocr"), dict) else None
        for cat in cats:
            docs.add(cat, src, county, "rows")
            docs.add(cat, src, county, "urls", cats[cat])
        if cats.get("deed_image"):
            docs.add("deed_image", src, county, "backlog_no_reader")
        if cats.get("env_search"):
            docs.add("env_search", src, county, "backlog_not_a_document")
        if cats.get("assessor_card"):
            ac = raw.get("assessor_card") if isinstance(raw.get("assessor_card"), dict) else {}
            btc = raw.get("bt_appraisal_card") if isinstance(raw.get("bt_appraisal_card"), dict) else {}
            parsed = any(v not in (None, "", [], {}) for k, v in ac.items() if k != "source_url") \
                or any(v not in (None, "", [], {}) for k, v in btc.items() if k != "card_url")
            docs.add("assessor_card", src, county, "processed" if parsed else "backlog_card_unparsed")
        if cats.get("list"):
            docs.add("list", src, county, "read_by_scraper")
        why = inv.unreadable_notice_reason(row)
        if why and not inv.ocr_doc_urls(row):
            docs.add("notice", src, county, f"backlog_{why}")
        ocr_urls = inv.ocr_doc_urls(row)
        if ocr_urls:
            primary = inv.normalize_url(ocr_urls[0])
            url_rows[primary] += 1
            ocr_rows.append((src, county, tier, primary, bool(dococr),
                             (dococr or {}).get("_source"),
                             bool(str(row.get("street_address") or "").strip()),
                             len(ocr_urls), inv.url_ext(ocr_urls[0]) or "none",
                             inv.doc_key(ocr_urls[0]), bool(inv.legacy_ocr_doc_urls(row))))
        if dococr:
            # did the extracted fields reach the row's columns?
            for f, cols in (("owner_name", ("owner_name", "defendant")),
                            ("property_address", ("street_address",)),
                            ("amount", ("judgment_amount", "opening_bid")),
                            ("sale_date", ("sale_date",)),
                            ("case_number", ("case_number",))):
                v = dococr.get(f)
                if v in (None, "", [], {}):
                    continue
                landing[(f, "extracted")] += 1
                vals = [row.get(c) for c in cols]
                if f == "amount":
                    try:
                        fv = float(str(v).replace(",", "").replace("$", ""))
                    except ValueError:
                        fv = None
                    same = any(x is not None and fv is not None and abs(float(x) - fv) < 1
                               for x in vals if isinstance(x, (int, float)))
                elif f == "sale_date":
                    same = any(str(x or "")[:10] == str(v)[:10] for x in vals)
                else:
                    same = any(_norm(x) and _norm(x) == _norm(v) for x in vals)
                other = any(x not in (None, "") for x in vals)
                landing[(f, "landed" if same else ("row_has_other_value" if other else "not_on_row"))] += 1
            for f in ("fields",):
                for x in dococr.get(f) or []:
                    landing[("aggregate_filled", str(x))] += 1

        # ---------------- dot (recorded deed-of-trust images, resolved at run time) -------
        key = (str(row.get("state") or "").strip(), str(row.get("county") or "").strip())
        if key in _dot_counties() and str(row.get("owner_name") or "").strip():
            rod = raw.get("rod") if isinstance(raw.get("rod"), dict) else None
            has_mtg = bool(rod.get("has_mortgage")) if (rod and "has_mortgage" in rod) else True
            if has_mtg:
                dot[(county, "eligible")] += 1
                if raw.get("dot_ocr"):
                    dot[(county, "processed")] += 1
                    if raw.get("loan_amount"):
                        dot[(county, "loan_amount_on_row")] += 1

        # ---------------- images ----------------
        irefs = inv.image_refs(row)
        icats = Counter(c for c, _ in irefs)
        vis = raw.get("vision") if isinstance(raw.get("vision"), dict) else None
        vff = raw.get("vision_fetch_failed") if isinstance(raw.get("vision_fetch_failed"), dict) else None
        for cat in icats:
            imgs.add(cat, src, county, "rows")
            imgs.add(cat, src, county, "urls", icats[cat])
        gradable = [c for c in icats if c in inv.GRADABLE_IMAGE_CATEGORIES]
        if gradable:
            best = ("listing_photo" if "listing_photo" in icats else
                    "assessor_photo" if "assessor_photo" in icats else
                    "street" if "street" in icats else "aerial")
            imgs.add("any_gradable", src, county, "rows")
            imgs.add(f"best_{best}", src, county, "rows")
            if vis:
                imgs.add("any_gradable", src, county, "vision_read")
                imgs.add(f"best_{best}", src, county, "vision_read")
                if str(raw.get("condition_source") or "").startswith("vision"):
                    imgs.add("any_gradable", src, county, "condition_tier_landed")
                    imgs.add(f"best_{best}", src, county, "condition_tier_landed")
            else:
                if vff:
                    reason = "fetch_failed"
                else:
                    reason = None
                vis_backlog.append((src, county, tier, best, reason,
                                    str(row.get("sale_date") or "")[:10]))
        elif icats.get("map"):
            imgs.add("map_only", src, county, "rows")
        if n % 50000 == 0:
            print(n, round(time.time() - t0), "s",
                  resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // (1 << 20), "MB", flush=True)

    # ---- doc OCR backlog with reasons (needs the share counts of the whole board) ----
    share_max = 3
    led_ocr = ledgers.get("doc_ocr")
    for (src, county, tier, primary, done, osrc, has_addr, nurls, ext, dkey, legacy) in ocr_rows:
        agg = url_rows[primary] > share_max
        cat = "ocr_roster" if agg else "ocr_per_lead"
        docs.add(cat, src, county, "rows")
        docs.add(cat, src, county, f"ext_{ext}")
        if nurls > 1:
            docs.add(cat, src, county, "rows_with_more_than_one_doc")
        if tier in ("HOT", "WARM"):
            docs.add(cat, src, county, f"rows_{tier.lower()}")
        if done:
            docs.add(cat, src, county, "processed")
            continue
        entry = led_ocr.rows.get(dkey) if led_ocr is not None else None
        if entry:
            docs.add(cat, src, county, f"ledger_{entry.get('outcome')}")
            continue
        if agg:
            if has_addr:
                docs.add(cat, src, county, "not_needed_address_present")
            else:
                docs.add(cat, src, county, "backlog_aggregate_never_run")
        elif not legacy:
            docs.add(cat, src, county, "backlog_field_not_read_by_doc_ocr")
        else:
            # attempted and failed, or never reached before the 900 s cut: the old reader left
            # no mark either way
            docs.add(cat, src, county, "backlog_cut_or_failed_unrecorded")

    # ---- vision backlog: simulate _vpri on the unscored rows (HOT, WARM, rest; sale date) ---
    rank = {"HOT": 0, "WARM": 1}
    vis_backlog.sort(key=lambda r: (rank.get(r[2], 2), 0 if r[5] else 1, r[5] or "9999"))
    for i, (src, county, tier, best, reason, _sd) in enumerate(vis_backlog):
        if reason is None:
            reason = "breaker_or_budget_inside_cap" if i < args.vision_cap else "count_cap"
        imgs.add("any_gradable", src, county, f"backlog_{reason}")
        imgs.add(f"best_{best}", src, county, f"backlog_{reason}")
        if tier in ("HOT", "WARM"):
            imgs.add("any_gradable", src, county, f"backlog_{tier.lower()}")

    dot_by_county: dict = defaultdict(dict)
    for (c, m), v in dot.items():
        dot_by_county[c][m] = v

    out = {
        "board": str(args.board), "rows": n, "seconds": round(time.time() - t0),
        "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // (1 << 20),
        "documents": docs.as_dict(),
        "images": imgs.as_dict(),
        "doc_ocr_field_landing": {f"{a}:{b}": v for (a, b), v in sorted(landing.items())},
        "dot_ocr_by_county": dict(dot_by_county),
        "ocr_primary_urls": {"distinct": len(url_rows),
                             "shared_over_3": sum(1 for c in url_rows.values() if c > share_max),
                             "rows_on_shared": sum(c for c in url_rows.values() if c > share_max)},
        "ledgers_loaded": sorted(ledgers),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print("wrote", args.out, n, "rows", out["seconds"], "s", out["peak_rss_mb"], "MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
