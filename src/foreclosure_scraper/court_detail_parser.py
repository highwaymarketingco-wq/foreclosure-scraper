"""Parse the rich detail off a Tyler RegisterOfActions / case-summary page.

Tyler (NC eCourts) renders a per-case page that contains the judgment amount,
the live balance due, the full docket of "Case Events", and — most valuably —
the sale documents (Notice of Sale, Report of Sale, Order of Confirmation,
Writ of Execution) with their dates. We already fetch this page in
enrichment_nc_case_status_tyler; historically we only regex'd a coarse status
+ sold price off it. This module turns its *visible text* into structured data:

  - judgment_amount / principal_amount  (the real debt)
  - balance_due (+ as-of date)           (debt incl. accrued interest)
  - documents: [{date, type, available}] (the sale paper trail)
  - sale_status: confirmed | sold_unconfirmed | sale_noticed | judgment | None
  - docket: [{date, event}]              (timeline)

sale_status is the high-value signal: a case with an "Order of Confirmation of
Sale" has already sold at auction — it should be filtered off the live board.

Pure functions, no I/O — fed either the page's visible text or raw HTML
(strip_html handles tag removal so callers can pass either).
"""
from __future__ import annotations

import re
from typing import Optional

# Sale-document types we care about, most-advanced (latest in the lifecycle)
# first — the first one present determines sale_status. Covers BOTH NC eCourts
# (Tyler) and SC Public Index (Master-in-Equity) foreclosure vocabularies.
_DOC_TYPES = [
    # confirmed / title transferred (sale is final)
    "Order of Confirmation of Sale",
    "Order Confirming Sale",
    "Order of Confirmation",
    "Master in Equity Deed",
    "Master's Deed",
    "Title to Real Estate",
    # sold, pending confirmation
    "Master's Report of Sale",
    "Report of Sale",
    # sale scheduled / noticed
    "Notice of Foreclosure Sale",
    "Notice Of Sale/Resale",
    "Notice of Sale/Resale",
    "Notice of Sale",
    # judgment entered (pre-sale)
    "Judgment of Foreclosure",
    "Order of Foreclosure and Sale",
    "Decree of Foreclosure",
    "Writ of Execution",
    "Judgment for Taxes",
    "Case Filed",
]

# Which sale_status a given (most-advanced) document implies.
_STATUS_BY_DOC = {
    "Order of Confirmation of Sale": "confirmed",
    "Order Confirming Sale": "confirmed",
    "Order of Confirmation": "confirmed",
    "Master in Equity Deed": "confirmed",
    "Master's Deed": "confirmed",
    "Title to Real Estate": "confirmed",
    "Master's Report of Sale": "sold_unconfirmed",
    "Report of Sale": "sold_unconfirmed",
    "Notice of Foreclosure Sale": "sale_noticed",
    "Notice Of Sale/Resale": "sale_noticed",
    "Notice of Sale/Resale": "sale_noticed",
    "Notice of Sale": "sale_noticed",
}

_MONEY = r"\$?\s*([\d,]+\.\d{2})"
_DATE = r"(\d{1,2}/\d{1,2}/\d{2,4})"


def strip_html(s: str) -> str:
    """Crude tag strip → visible text. Good enough for label/value regexes."""
    if "<" not in s:
        return s
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"[ \t]+", " ", s)


def _money(pattern: str, text: str) -> Optional[float]:
    m = re.search(pattern, text, re.I)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except (ValueError, IndexError):
        return None


def parse_register_of_actions(content: str) -> dict:
    """Extract structured court detail from a Tyler case page (text or HTML)."""
    text = strip_html(content)
    out: dict = {}

    # --- money -------------------------------------------------------------
    total = _money(r"Total Judgment:\s*" + _MONEY, text)
    principal = _money(r"Principal Amount:\s*" + _MONEY, text)
    if total is not None:
        out["judgment_amount"] = total
    if principal is not None:
        out["principal_amount"] = principal

    m = re.search(r"Balance Due as of\s*" + _DATE + r"\s*" + _MONEY, text, re.I)
    if m:
        out["balance_due_as_of"] = m.group(1)
        try:
            out["balance_due"] = float(m.group(2).replace(",", ""))
        except ValueError:
            pass

    # --- documents ---------------------------------------------------------
    # Each "Case Events" entry looks like:
    #   <date> [A document is available...] <Type...> Created: <ts> Index # <n>
    # We capture, per document type occurrence, its Created date + whether a
    # viewable document is attached.
    docs: list[dict] = []
    seen_types: set[str] = set()
    for dtype in _DOC_TYPES:
        for m in re.finditer(re.escape(dtype), text):
            seg = text[m.start(): m.start() + 400]
            cm = re.search(r"Created:\s*" + _DATE, seg)
            date = cm.group(1) if cm else None
            # "A document is available" appears just BEFORE the type heading.
            pre = text[max(0, m.start() - 160): m.start()]
            available = "document is available" in pre.lower()
            key = (dtype, date)
            if key in seen_types:
                continue
            seen_types.add(key)
            docs.append({"type": dtype, "date": date, "available": available})
    if docs:
        out["documents"] = docs

    # --- sale_status (from the most-advanced document present) -------------
    low = text.lower()
    status = None
    for dtype, st in _STATUS_BY_DOC.items():
        if dtype.lower() in low:
            status = st
            break
    if status is None and re.search(r"judgment for taxes|final judgment", low):
        status = "judgment"
    if status:
        out["sale_status"] = status

    # --- docket timeline (date + following short label) --------------------
    docket = []
    for m in re.finditer(_DATE + r"\s+([A-Z][\w \-/,.()&'\"]{4,60})", text):
        label = m.group(2).strip()
        if label.lower().startswith(("transaction", "calculated interest", "courthouse")):
            continue
        docket.append({"date": m.group(1), "event": label})
        if len(docket) >= 25:
            break
    if docket:
        out["docket"] = docket

    return out
