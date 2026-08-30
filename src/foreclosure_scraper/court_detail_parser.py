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

    # --- child support detection (Tyler text format) --------------------
    _CS_RE = re.compile(
        r"\bCHILD\s*SUPPORT\b|\bC\.?S\.?\b|\bSPOUSAL\s*SUPPORT\b|\bALIMONY\b"
        r"|\bFAMILY\s*SUPPORT\b|\bSUPPORT\s*OBLIGATION\b|\bARREARS?\s*\(?"
        r"|CHILD\s*ABDUCTION.*SUPPORT|\bDSS\s*.*SUPPORT", re.I)
    cs_hits: list[dict] = []
    # Check docket events
    for d in docket:
        if _CS_RE.search(d.get("event", "")):
            cs_hits.append({"source": "docket_event", "description": d.get("event"),
                            "date": d.get("date")})
    # Check judgment/total/principal labels in the text
    if _CS_RE.search(text):
        # More specific: look for child support in the balance/judgment context
        for m in re.finditer(r"(?i)(child\s*support|spousal\s*support|alimony|family\s*support|support\s*obligation|arrears?)[^\n]{0,200}", text):
            cs_hits.append({"source": "text_scan", "description": m.group(0).strip()[:200]})
    if cs_hits:
        # Dedupe by description
        seen_cs: set[str] = set()
        deduped_cs = [h for h in cs_hits if h.get("description", "") not in seen_cs and not seen_cs.add(h.get("description", ""))]
        out["child_support"] = {
            "flag": True,
            "hits": deduped_cs,
            "count": len(deduped_cs),
        }

    return out


# ---------------------------------------------------------------------------
# SC Public Index — selectolax table parser
# ---------------------------------------------------------------------------
# SC case detail pages use ASP.NET AJAX tab panels with <table class="detailsSection">.
# Tables appear in pairs: an "all-in-one" view (outside tab panels) + per-tab copies.
# We dedupe by table signature (header row + first data row).
#
# Table types (identified by header row):
#   - parties:   Name | Address | Race | Sex | Year Of Birth | Party Type | Party Status | Last Updated
#   - judgment:   For: | <plaintiff> | Against: | <defendant> | Judg. Amount: | $xxx | Judgment Date: | <date>
#   - judg_detail: Judgment Details → Claims Code | Detail Desc. | Detail Amount | Detail Date
#   - docket:     Name | Description | Type | Motion Roster | Begin Date | Completion Date | Documents
#   - summary:    Summary → Fine/Costs: | Total Paid: | Balance Due:
#   - costs:      Costs → Description | Cost Code | Amount | Charge Action | Disbursed Amount
#   - payments:   Payments → Payment Date | Receipt Number | Entered By | Transaction Type Code | Payment Amount
#   - property:   Agency name | Tax Map Number | Tax Map Description  (foreclosure cases only)
#   - associated:  Case Number | Court Agency | Case Type | Filed Date | ...  (cross-references)

def _table_signature(table_node) -> tuple:
    """Return (header texts, first-data-row texts) for dedup."""
    rows = table_node.css("tr")
    if not rows:
        return ((), ())
    hdr = tuple(c.text(strip=True) for c in rows[0].css("th, td"))
    first_data = ()
    if len(rows) > 1:
        first_data = tuple(c.text(strip=True) for c in rows[1].css("th, td"))
    return (hdr, first_data)


def _parse_parties_table(table_node) -> list[dict]:
    """Party roster: Name, Address, Race, Sex, Year Of Birth, Party Type, Party Status, Last Updated."""
    rows = table_node.css("tr")
    parties = []
    for row in rows[1:]:  # skip header
        cells = [c.text(strip=True) for c in row.css("td, th")]
        if len(cells) < 7:
            continue
        name = cells[0].strip()
        if not name or name == "Name":
            continue
        parties.append({
            "name": name,
            "address": cells[1].strip() if len(cells) > 1 else "",
            "race": cells[2].strip() if len(cells) > 2 else "",
            "sex": cells[3].strip() if len(cells) > 3 else "",
            "year_of_birth": cells[4].strip() if len(cells) > 4 else "",
            "party_type": cells[5].strip() if len(cells) > 5 else "",
            "party_status": cells[6].strip() if len(cells) > 6 else "",
            "last_updated": cells[7].strip() if len(cells) > 7 else "",
        })
    return parties


def _parse_judgment_table(table_node) -> dict:
    """Judgment header: For: | plaintiff | Against: | defendant | Judg. Amount: | $xxx | Judgment Date: | date
    Plus rows: Description, Disposition, Notes."""
    rows = table_node.css("tr")
    out: dict = {}
    # Row 0: header with For/Against/Judg Amount/Judgment Date
    if rows:
        cells = [c.text(strip=True) for c in rows[0].css("th, td")]
        i = 0
        while i < len(cells):
            label = cells[i].rstrip(":").strip().lower()
            val = cells[i + 1].strip() if i + 1 < len(cells) else ""
            if label == "for":
                out["plaintiff"] = val
            elif label == "against":
                out["defendant"] = val
            elif label in ("judg amount", "judg. amount", "judgment amount"):
                out["judgment_amount"] = _parse_money(val)
            elif label in ("judgment date", "judg date"):
                out["judgment_date"] = val
            i += 2
    # Subsequent rows: Description, Disposition, Disp. Date, Notes
    for row in rows[1:]:
        cells = [c.text(strip=True) for c in row.css("th, td")]
        if len(cells) >= 2:
            label = cells[0].rstrip(":").strip().lower()
            val = cells[1].strip()
            if label == "description":
                out["description"] = val
            elif label == "disposition":
                out["disposition"] = val
            elif label in ("disp date", "disp. date"):
                out["disposition_date"] = val
            elif label == "date entered/last changed":
                out["date_entered"] = val
            elif label == "notes":
                out["notes"] = val
    return out


def _parse_judgment_details_table(table_node) -> list[dict]:
    """Judgment Details: Claims Code | Detail Desc. | Detail Amount | Detail Date."""
    rows = table_node.css("tr")
    if len(rows) < 3:
        return []
    # Row 0: "Judgment Details" title, Row 1: column headers, Row 2+: data
    details = []
    for row in rows[2:]:
        cells = [c.text(strip=True) for c in row.css("td, th")]
        if len(cells) < 4:
            continue
        if cells[0].strip().lower() == "none":
            break
        details.append({
            "claims_code": cells[0].strip(),
            "description": cells[1].strip(),
            "amount": _parse_money(cells[2]) if len(cells) > 2 else None,
            "date": cells[3].strip() if len(cells) > 3 else "",
        })
    return details


def _parse_docket_table(table_node) -> list[dict]:
    """Docket/Register of Actions: Name | Description | Type | Motion Roster | Begin Date | Completion Date | Documents."""
    rows = table_node.css("tr")
    docket = []
    for row in rows[1:]:  # skip header
        cells = [c.text(strip=True) for c in row.css("td, th")]
        if len(cells) < 7:
            continue
        name = cells[0].strip()
        if not name or name == "Name":
            continue
        # Extract document links
        doc_links = []
        for a in row.css("a"):
            href = a.attrs.get("href", "")
            text = a.text(strip=True)
            if href and ("PIImageDisplay" in href or "View" in text):
                doc_links.append({"text": text, "href": href})
        docket.append({
            "name": name,
            "description": cells[1].strip(),
            "type": cells[2].strip(),
            "motion_roster": cells[3].strip(),
            "begin_date": cells[4].strip(),
            "completion_date": cells[5].strip(),
            "documents": doc_links if doc_links else (cells[6].strip() if len(cells) > 6 else ""),
        })
    return docket


def _parse_summary_table(table_node) -> dict:
    """Summary: Fine/Costs | Total Paid | Balance Due."""
    rows = table_node.css("tr")
    out: dict = {}
    for row in rows:
        cells = [c.text(strip=True) for c in row.css("th, td")]
        i = 0
        while i < len(cells):
            label = cells[i].rstrip(":").strip().lower()
            val = cells[i + 1].strip() if i + 1 < len(cells) else ""
            if "fine" in label and "cost" in label:
                out["fine_costs"] = _parse_money(val)
            elif "total paid" in label:
                out["total_paid"] = _parse_money(val)
            elif "balance" in label:
                out["balance_due"] = _parse_money(val)
            i += 2
    return out


def _parse_costs_table(table_node) -> list[dict]:
    """Costs: Description | Cost Code | Amount | Charge Action | Disbursed Amount."""
    rows = table_node.css("tr")
    costs = []
    for row in rows[1:]:  # skip header (may be row 0 or row 1 depending on title)
        cells = [c.text(strip=True) for c in row.css("td, th")]
        if len(cells) < 5:
            continue
        desc = cells[0].strip()
        if not desc or desc.lower() in ("description", "none"):
            continue
        costs.append({
            "description": desc,
            "cost_code": cells[1].strip(),
            "amount": _parse_money(cells[2]),
            "charge_action": cells[3].strip(),
            "disbursed_amount": _parse_money(cells[4]),
        })
    return costs


def _parse_payments_table(table_node) -> list[dict]:
    """Payments: Payment Date | Receipt Number | Entered By | Transaction Type Code | Payment Amount."""
    rows = table_node.css("tr")
    payments = []
    for row in rows[1:]:
        cells = [c.text(strip=True) for c in row.css("td, th")]
        if len(cells) < 5:
            continue
        date = cells[0].strip()
        if not date or date.lower() in ("payment date", "none"):
            continue
        payments.append({
            "payment_date": date,
            "receipt_number": cells[1].strip(),
            "entered_by": cells[2].strip(),
            "transaction_type_code": cells[3].strip(),
            "payment_amount": _parse_money(cells[4]),
        })
    return payments


def _parse_property_table(table_node) -> dict:
    """Property: Agency name | Tax Map Number | Tax Map Description."""
    rows = table_node.css("tr")
    out: dict = {}
    for row in rows:
        cells = [c.text(strip=True) for c in row.css("td, th")]
        if len(cells) >= 2:
            label = cells[0].rstrip(":").strip().lower()
            val = cells[1].strip()
            if "agency" in label:
                out["agency_name"] = val
            elif "tax map" in label and "number" in label:
                out["tax_map_number"] = val
            elif "tax map" in label and "description" in label:
                out["tax_map_description"] = val
    return out


def _parse_money(s: str) -> Optional[float]:
    """Parse a money string like '$1,550.88' or '35.00' into float."""
    if not s:
        return None
    m = re.search(r"[\d,]+\.?\d*", s.replace("$", "").replace(" ", ""))
    if m:
        try:
            return float(m.group(0).replace(",", ""))
        except ValueError:
            pass
    return None


def _classify_table(hdr: tuple, table_node=None) -> str:
    """Classify a detailsSection table by its header row.
    For single-cell headers, fall back to the table's full text."""
    # Strip colons/periods and lowercase for matching
    hdr_clean = tuple(h.rstrip(":.").strip().lower() for h in hdr)
    hdr_text = " ".join(hdr_clean)

    if not hdr or not hdr[0]:
        return "unknown"

    # Party roster
    if "name" in hdr_clean and "party type" in hdr_clean:
        return "parties"
    # Judgment header (For: ... Against: ... Judg. Amount: ...)
    if "for" in hdr_clean and any("against" in h for h in hdr_clean):
        return "judgment"
    # Judgment Details
    if "judgment details" in hdr_text:
        return "judg_detail"
    # Docket
    if "motion roster" in hdr_text or ("begin date" in hdr_text and "completion date" in hdr_text):
        return "docket"
    # Summary
    if "summary" in hdr_text and ("fine" in hdr_text or "balance" in hdr_text):
        return "summary"
    # Costs
    if "costs" in hdr_text or ("cost code" in hdr_text and "disbursed" in hdr_text):
        return "costs"
    # Payments
    if "payments" in hdr_text or ("receipt number" in hdr_text and "payment amount" in hdr_text):
        return "payments"
    # Property
    if "tax map" in hdr_text or "agency name" in hdr_text:
        return "property"
    # Associated cases
    if "case number" in hdr_text and "court agency" in hdr_text:
        return "associated"
    # Title/header table (case caption)
    if "vs" in hdr_text or " v. " in hdr_text or " v " in hdr_text:
        return "caption"

    # --- Fallback for single-cell headers: check full table text ---
    if len(hdr) == 1 and table_node is not None:
        full = table_node.text(separator=" ", strip=True).lower()
        if "judgment details" in full:
            return "judg_detail"
        if "fine/costs" in full or "balance due" in full:
            return "summary"
        if "cost code" in full or "disbursed amount" in full:
            return "costs"
        if "receipt number" in full or "payment amount" in full:
            return "payments"
        if "tax map" in full:
            return "property"
        if "case number" in full and "court agency" in full:
            return "associated"

    return "unknown"


def parse_sc_case_detail(html: str) -> dict:
    """Parse an SC Public Index case detail page (HTML) into structured data.

    Extracts all ``<table class="detailsSection">`` tables, deduplicates the
    pairs (all-in-one view + per-tab copies), and returns a dict with keys:

      - case_caption:  str          (e.g. "St Franklin Financial VS Amy Buchanan")
      - parties:       list[dict]   (full party roster with addresses, types)
      - judgment:      dict         (plaintiff, defendant, amount, date, disposition)
      - judgment_details: list[dict] (claims code, description, amount, date)
      - docket:        list[dict]   (full register of actions — NO 25-entry cap)
      - summary:       dict         (fine/costs, total paid, balance due)
      - costs:         list[dict]   (cost code, amount, charge action, disbursed)
      - payments:      list[dict]   (date, receipt #, entered by, type, amount)
      - property:      dict         (agency name, tax map number, description)
      - associated_cases: list[dict]
      - documents:     list[dict]   (sale documents extracted from docket entries)
      - sale_status:   str | None   (confirmed | sold_unconfirmed | sale_noticed | judgment | None)
      - judgment_amount: float | None  (backward compat with parse_register_of_actions)
      - balance_due:   float | None
      - court_documents: list[dict]
    """
    if not html or len(html) < 50:
        return {}

    try:
        from selectolax.parser import HTMLParser
    except ImportError:
        # Fallback: use the regex parser on stripped text
        return parse_register_of_actions(html)

    tree = HTMLParser(html)
    tables = tree.css("table.detailsSection")
    if not tables:
        # Maybe it's Tyler text format, not SC HTML
        return parse_register_of_actions(html)

    out: dict = {}
    seen_sigs: set[tuple] = set()

    # Collect one copy of each table type (dedupe the all-in-one + tab-panel pairs)
    classified: dict[str, list] = {}
    for t in tables:
        sig = _table_signature(t)
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        kind = _classify_table(sig[0], t)
        if kind == "unknown":
            continue
        classified.setdefault(kind, []).append(t)

    # Parse each type
    if "caption" in classified:
        for t in classified["caption"]:
            # The caption table's first cell has "Plaintiff VS Defendant"
            # plus case metadata. Extract just the VS line.
            raw = t.text(separator=" ", strip=True).strip()
            # Try to extract the "A VS B" portion before "Case Number:"
            m = re.match(r"(.+?\s+VS\s+.+?)(?:\s+Case Number:|$)", raw, re.I)
            if m:
                out["case_caption"] = m.group(1).strip()
            elif raw:
                # Fallback: first 100 chars
                out["case_caption"] = raw[:100].strip()
            # Also extract case number from caption metadata
            cn = re.search(r"Case Number:\s*(\S+)", raw)
            if cn and "case_number" not in out:
                out["case_number"] = cn.group(1).strip()
            break

    if "parties" in classified:
        all_parties: list[dict] = []
        for t in classified["parties"]:
            all_parties.extend(_parse_parties_table(t))
        # Dedupe by (name, party_type) — same person may appear multiple times
        seen_party: set[tuple] = set()
        deduped_parties: list[dict] = []
        for p in all_parties:
            key = (p.get("name", ""), p.get("party_type", ""))
            if key not in seen_party:
                seen_party.add(key)
                deduped_parties.append(p)
        if deduped_parties:
            out["parties"] = deduped_parties

    if "judgment" in classified:
        # Take the first non-empty judgment table
        for t in classified["judgment"]:
            jd = _parse_judgment_table(t)
            if jd:
                out["judgment"] = jd
                # Backward-compat fields
                if jd.get("judgment_amount"):
                    out["judgment_amount"] = jd["judgment_amount"]
                break

    if "judg_detail" in classified:
        all_jd: list[dict] = []
        for t in classified["judg_detail"]:
            all_jd.extend(_parse_judgment_details_table(t))
        if all_jd:
            out["judgment_details"] = all_jd

    # --- child support detection ------------------------------------------
    # SC family court judgment details and case captions may reveal child
    # support obligations. We scan judgment detail descriptions, the case
    # caption, the judgment description, and docket entries for child-support
    # keywords. This sets a top-level flag + the matching detail rows.
    _CS_RE = re.compile(
        r"\bCHILD\s*SUPPORT\b|\bC\.?S\.?\b|\bSPOUSAL\s*SUPPORT\b|\bALIMONY\b"
        r"|\bFAMILY\s*SUPPORT\b|\bSUPPORT\s*OBLIGATION\b|\bARREARS?\s*\(?"
        r"|CHILD\s*ABDUCTION.*SUPPORT|\bDSS\s*.*SUPPORT", re.I)
    cs_hits: list[dict] = []
    # Check judgment details
    for jd in out.get("judgment_details", []):
        desc = f"{jd.get('description', '')} {jd.get('claims_code', '')}"
        if _CS_RE.search(desc):
            cs_hits.append({"source": "judgment_detail", "description": jd.get("description"),
                            "amount": jd.get("amount"), "date": jd.get("date")})
    # Check judgment description/notes
    jdb = out.get("judgment") or {}
    for fld in ("description", "notes", "disposition"):
        val = jdb.get(fld, "")
        if val and _CS_RE.search(str(val)):
            cs_hits.append({"source": f"judgment.{fld}", "description": str(val)[:200]})
    # Check case caption
    cap = out.get("case_caption", "")
    if cap and _CS_RE.search(str(cap)):
        cs_hits.append({"source": "case_caption", "description": str(cap)[:200]})
    # Check docket entries
    for d in out.get("docket") or []:
        combined = f"{d.get('name', '')} {d.get('description', '')}"
        if _CS_RE.search(combined):
            cs_hits.append({"source": "docket", "description": d.get("description"),
                            "date": d.get("begin_date") or d.get("completion_date")})
    if cs_hits:
        out["child_support"] = {
            "flag": True,
            "hits": cs_hits,
            "count": len(cs_hits),
        }

    if "docket" in classified:
        all_docket: list[dict] = []
        for t in classified["docket"]:
            all_docket.extend(_parse_docket_table(t))
        # Dedupe by (name, description, begin_date)
        seen_dkt: set[tuple] = set()
        deduped_docket: list[dict] = []
        for d in all_docket:
            key = (d.get("name", ""), d.get("description", ""), d.get("begin_date", ""))
            if key not in seen_dkt:
                seen_dkt.add(key)
                deduped_docket.append(d)
        if deduped_docket:
            out["docket"] = deduped_docket

            # Extract sale documents from docket descriptions
            docs: list[dict] = []
            seen_doc_types: set[str] = set()
            for entry in deduped_docket:
                desc = entry.get("description", "")
                name = entry.get("name", "")
                combined = f"{name} {desc}"
                for dtype in _DOC_TYPES:
                    if dtype.lower() in combined.lower():
                        if dtype not in seen_doc_types:
                            seen_doc_types.add(dtype)
                            doc_entry = {
                                "type": dtype,
                                "date": entry.get("completion_date") or entry.get("begin_date"),
                                "available": bool(entry.get("documents")),
                            }
                            docs.append(doc_entry)
                            break
            if docs:
                out["documents"] = docs
                out["court_documents"] = docs  # backward compat key

            # Sale status from most-advanced document
            low = " ".join(d.get("description", "").lower() for d in deduped_docket)
            status = None
            for dtype, st in _STATUS_BY_DOC.items():
                if dtype.lower() in low:
                    status = st
                    break
            if status is None and re.search(r"judgment for taxes|final judgment", low):
                status = "judgment"
            if status:
                out["sale_status"] = status

    if "summary" in classified:
        for t in classified["summary"]:
            sm = _parse_summary_table(t)
            if sm:
                out["summary"] = sm
                if sm.get("balance_due") is not None:
                    out["balance_due"] = sm["balance_due"]
                break

    if "costs" in classified:
        all_costs: list[dict] = []
        for t in classified["costs"]:
            all_costs.extend(_parse_costs_table(t))
        # Dedupe by (description, cost_code)
        seen_cost: set[tuple] = set()
        deduped_costs: list[dict] = []
        for c in all_costs:
            key = (c.get("description", ""), c.get("cost_code", ""))
            if key not in seen_cost:
                seen_cost.add(key)
                deduped_costs.append(c)
        if deduped_costs:
            out["costs"] = deduped_costs

    if "payments" in classified:
        all_pmt: list[dict] = []
        for t in classified["payments"]:
            all_pmt.extend(_parse_payments_table(t))
        # Dedupe by (payment_date, receipt_number)
        seen_pmt: set[tuple] = set()
        deduped_pmt: list[dict] = []
        for p in all_pmt:
            key = (p.get("payment_date", ""), p.get("receipt_number", ""))
            if key not in seen_pmt:
                seen_pmt.add(key)
                deduped_pmt.append(p)
        if deduped_pmt:
            out["payments"] = deduped_pmt

    if "property" in classified:
        for t in classified["property"]:
            prop = _parse_property_table(t)
            if prop:
                out["property"] = prop
                break

    if "associated" in classified:
        assoc: list[dict] = []
        for t in classified["associated"]:
            rows = t.css("tr")
            for row in rows[1:]:
                cells = [c.text(strip=True) for c in row.css("td, th")]
                if len(cells) >= 3 and cells[0]:
                    assoc.append({
                        "case_number": cells[0],
                        "court_agency": cells[1] if len(cells) > 1 else "",
                        "case_type": cells[2] if len(cells) > 2 else "",
                    })
        if assoc:
            out["associated_cases"] = assoc

    return out
