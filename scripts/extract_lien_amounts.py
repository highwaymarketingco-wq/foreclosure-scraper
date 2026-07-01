#!/usr/bin/env python3
"""Local ROD lien-amount extractor (FREE, offline-first).

The Register-of-Deeds INDEX carries the instrument (deed of trust, lien,
judgment) but not the dollar figure — the amount lives only inside the
recorded document. The document images are free to download from the county;
you just can't get the $ from the index API. So: manually (or via the county's
free bulk export) drop the recorded PDFs in a folder and run this. It lifts the
secured/loan/judgment amount out of each PDF with pdfplumber + targeted regex,
and OCRs scanned pages via Gemini (free tier) only when there's no text layer.

Usage:
    uv run python scripts/extract_lien_amounts.py <pdf_dir> [--out out.csv] [--no-ocr]

Costs nothing but CPU (text-layer PDFs) and a little free Gemini quota (scans).
Output: CSV with the best-guess loan/lien amount, every dollar figure found,
the instrument type, grantor/grantee if present, book/page, and the method used.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
from pathlib import Path
from typing import Optional

# make the package importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_MONEY = re.compile(r"\$\s?[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?")
# phrases that immediately precede the SECURED / LOAN / JUDGMENT amount — the
# figure we actually want, distinct from incidental $ (fees, tax stamps).
_LOAN_CUES = re.compile(
    r"(principal\s+sum\s+of|indebtedness[^.$]{0,40}|in\s+the\s+(?:original\s+)?(?:principal\s+)?"
    r"amount\s+of|secured[^.$]{0,40}|note\s+in\s+the\s+amount\s+of|judgment[^.$]{0,40}|"
    r"sum\s+of|principal\s+balance[^.$]{0,20})\s*(\$\s?[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)",
    re.I)
_INSTRUMENT = re.compile(
    r"\b(deed\s+of\s+trust|mortgage|assignment|satisfaction|lien|judgment|"
    r"lis\s+pendens|notice\s+of\s+sale|substitute\s+trustee|release|"
    r"power\s+of\s+attorney|deed)\b", re.I)
_BOOKPAGE = re.compile(r"\b(?:book|bk)\s*[:#]?\s*(\d+)[,\s]+(?:page|pg)\s*[:#]?\s*(\d+)", re.I)
_GRANTOR = re.compile(r"\b(?:grantor|borrower|trustor|mortgagor|debtor)\s*[:\-]?\s*([A-Z][A-Za-z,.'&\s]{3,60})", re.I)


def _to_float(s: str) -> Optional[float]:
    try:
        return float(re.sub(r"[^0-9.]", "", s) or 0) or None
    except Exception:
        return None


def _pdf_text(path: Path) -> Optional[str]:
    try:
        import pdfplumber
        chunks = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:4]:
                t = page.extract_text() or ""
                if t:
                    chunks.append(t)
        text = "\n".join(chunks).strip()
        return text if len(text) >= 120 else None
    except Exception:
        return None


def _parse_text(text: str) -> dict:
    """Pull the loan/lien amount + metadata out of a text-layer document."""
    all_amts = [_to_float(m.group(0)) for m in _MONEY.finditer(text)]
    all_amts = [a for a in all_amts if a]
    cued = [(_to_float(m.group(2)), m.group(1).strip()[:40]) for m in _LOAN_CUES.finditer(text)]
    cued = [(a, c) for a, c in cued if a]
    # best loan guess: the largest cue-anchored amount; else the largest overall
    loan = max((a for a, _ in cued), default=None) or (max(all_amts) if all_amts else None)
    cue = next((c for a, c in cued if a == loan), None)
    inst = _INSTRUMENT.search(text)
    bp = _BOOKPAGE.search(text)
    gr = _GRANTOR.search(text)
    return {
        "loan_amount": loan,
        "loan_cue": cue,
        "all_amounts": ";".join(f"{a:,.2f}" for a in sorted(set(all_amts), reverse=True)[:12]),
        "instrument_type": inst.group(1).lower() if inst else None,
        "book": bp.group(1) if bp else None,
        "page": bp.group(2) if bp else None,
        "grantor": (gr.group(1).strip() if gr else None),
        "method": "text",
    }


async def _ocr_scanned(path: Path) -> dict:
    """Scanned PDF (no text layer) -> Gemini OCR (free). Returns amount+meta."""
    try:
        from foreclosure_scraper import enrichment_doc_ocr as ocr
        keys = ocr._parse_gemini_keys()
        if not keys:
            return {"method": "ocr_skipped_no_key"}
        data = path.read_bytes()
        for k in keys:
            try:
                res = await ocr._gemini_call(k, [(data, "application/pdf")], is_text=False)
            except ocr._QuotaOut:
                continue
            if res:
                return {
                    "loan_amount": ocr._clean_amount(res.get("amount")),
                    "loan_cue": None,
                    "all_amounts": "",
                    "instrument_type": res.get("doc_type"),
                    "book": None, "page": None,
                    "grantor": res.get("owner_name"),
                    "method": "ocr_gemini",
                }
        return {"method": "ocr_failed"}
    except Exception as e:  # noqa: BLE001
        return {"method": f"ocr_error:{str(e)[:40]}"}


async def extract_from_pdf(path: Path, allow_ocr: bool = True) -> dict:
    row = {"file": path.name, "loan_amount": None, "loan_cue": None,
           "all_amounts": "", "instrument_type": None, "book": None,
           "page": None, "grantor": None, "method": "none"}
    text = _pdf_text(path)
    if text:
        row.update(_parse_text(text))
    elif allow_ocr:
        row.update(await _ocr_scanned(path))
    else:
        row["method"] = "scanned_no_ocr"
    return row


async def main():
    ap = argparse.ArgumentParser(description="Extract lien/loan $ from recorded PDF documents")
    ap.add_argument("pdf_dir", help="folder of recorded-document PDFs")
    ap.add_argument("--out", default="lien_amounts.csv", help="output CSV path")
    ap.add_argument("--no-ocr", action="store_true", help="skip Gemini OCR of scanned pages")
    args = ap.parse_args()

    root = Path(args.pdf_dir).expanduser()
    pdfs = sorted(root.glob("*.pdf")) if root.is_dir() else ([root] if root.suffix.lower() == ".pdf" else [])
    if not pdfs:
        print(f"No PDFs found in {root}")
        return
    # load Gemini keys from .secrets if present and not already in env
    secrets = Path(__file__).resolve().parent.parent / ".secrets"
    for i in range(1, 10):
        f = secrets / f"gemini_api_key_{i}.txt"
        if f.exists() and not os.environ.get(f"GEMINI_API_KEY_{i}"):
            os.environ[f"GEMINI_API_KEY_{i}"] = f.read_text().strip()

    rows = []
    for p in pdfs:
        row = await extract_from_pdf(p, allow_ocr=not args.no_ocr)
        rows.append(row)
        amt = f"${row['loan_amount']:,.2f}" if row["loan_amount"] else "—"
        print(f"  {p.name:<40} {amt:>16}  [{row['method']}] {row.get('instrument_type') or ''}")

    cols = ["file", "loan_amount", "loan_cue", "instrument_type", "grantor",
            "book", "page", "all_amounts", "method"]
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in cols})
    hit = sum(1 for r in rows if r["loan_amount"])
    print(f"\n{hit}/{len(rows)} documents yielded an amount -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
