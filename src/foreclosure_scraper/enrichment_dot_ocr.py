"""Deed-of-Trust loan-amount OCR for Spartanburg SC leads — the missing $ that
turns raw['rod'] lien EXISTENCE into an equity number (the #1 flipper metric).

The Spartanburg Logan ROD index (enrichment_spartanburg_rod) tells us a lead HAS
a mortgage but carries NO dollar figure — the loan amount lives only inside the
recorded document image. Spartanburg's Logan "The Lookup" exposes each recorded
instrument's scanned page for FREE at `view_image.php?key=<hash>`
(content-type application/pdf, NO cart, NO login, NO payment) — the key is
embedded in the records grid right next to each row. So per HOT/WARM Spartanburg
lead we:

  1. render the owner's ROD (reuses rod/logan_render's exact search flow —
     Accept -> name search -> pick-list -> records frame), keeping the browser
     OPEN so the guest-session PHPSESSID cookie is still live;
  2. parse the records grid for the DEED-OF-TRUST / MORTGAGE row belonging to the
     owner and grab its view_image.php key (from the row's copyToClipboard call);
  3. download that ONE instrument's free PDF via the render session's own cookies
     (a bare httpx GET returns 200 application/pdf with 0 bytes — the image is
     tied to the guest session, so we must fetch it inside the browser context);
  4. OCR page 1 for the "principal sum of $X" via enrichment_doc_ocr's FREE
     Gemini path (scanned pages have no text layer);
  5. write raw['loan_amount'] + raw['dot_ocr'] AND append a rod_docs entry
     (doc_type='DEED OF TRUST', amount=loan, recorded_date) so
     enrichment_equity._recorded_dt picks it up as the amortized-payoff basis.

Compliant: free public image, guest session, no CAPTCHA/WAF/login defeated —
just the JS the page itself runs plus a cookie-scoped download. Best-effort and
graceful: any render/download/OCR failure leaves the lead untouched so it retries
next run. Bounded: HOT/WARM Spartanburg only, capped N leads/run (render is
~25-40s/owner and flaky), idempotent (skips leads already carrying
raw['dot_ocr'] unless FORECLOSURE_DOT_OCR_FORCE=1), wall-clock budget-bailed.

Live-verified 2026-07-01 (GARRETT, JAMES): records grid 56 DEED / 39 MORTGAGE /
4 LIEN / 1 UCC; picked a MORTGAGE row; view_image.php -> 200 application/pdf
374,906 bytes (4pp scanned, 0 text layer); Gemini OCR -> amount 56097.80,
owner 'James V. Garrett', property '120 Kenmatt Drive, Chesnee SC 29323'.

Disable with FORECLOSURE_DOT_OCR=0. Env: FORECLOSURE_DOT_OCR_MAX (default 25),
FORECLOSURE_DOT_OCR_BUDGET_S (default 1800), FORECLOSURE_DOT_OCR_REFRESH_DAYS.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import structlog

from .rod.logan_render import LOGAN_RENDER_COUNTIES, _SUMMARY_RE

log = structlog.get_logger(__name__)

# Only Spartanburg is a render-based Logan county with free view_image PDFs today.
_TARGET = ("SC", "Spartanburg")

# A records-grid row is a Deed of Trust / mortgage-equivalent (the note that
# secures the debt whose balance we amortize for the payoff).
_DOT_RE = re.compile(
    r"MORT|DEED OF TRUST|\bD/?T\b|\bMTG\b|SECURITY (?:DEED|AGREEMENT)|TR/?D", re.I)
# Satisfactions / releases / cancellations / assignments carry NO loan amount —
# they're the PAYOFF or transfer record, not the original note. "MORTGAGE
# SATISFACTION" matches _DOT_RE (contains "MORT") but OCRs to a null amount, so
# exclude these and keep only the note that actually secures a dollar figure.
_NOT_A_NOTE_RE = re.compile(
    r"SATISF|RELEASE|CANCEL|\bSAT\b|\bREL\b|ASSIGN|SUBORDINAT|MODIFICATION", re.I)
# A real recorded mortgage note is well above this; nominal deed/satisfaction
# consideration ("$1", "$10 and other valuable consideration") and stray page/tax
# figures fall below it and must NOT be accepted as a loan amount.
_MIN_LOAN = float(os.environ.get("FORECLOSURE_DOT_OCR_MIN_LOAN", "1000"))


def _name_parts(owner: str) -> tuple[str, str]:
    o = re.sub(r"[^A-Za-z, ]", " ", owner or "").upper()
    o = re.sub(r"\s+", " ", o).strip()
    if not o:
        return "", ""
    if "," in o:
        a, b = o.split(",", 1)
        return a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    toks = o.split(" ")
    return toks[0], (toks[1] if len(toks) > 1 else "")


def _parse_image_rows(html: str) -> list[dict]:
    """Parse the Spartanburg Logan records grid into per-instrument rows carrying
    the free view_image.php key.

    Each row emits a `copyToClipboard('<inst>','<date>','<book_info>','<DOC_TYPE>',
    '<legal>','<party_type>','<searched>','<reverse>',...,'...view_image.php?key=
    <hash>...')` call — the DOC TYPE and the image key are both right there, so we
    read the row straight from that call (more robust than re-associating the
    summary <td> cells with the separate anchor)."""
    rows: list[dict] = []
    for call in re.findall(r"copyToClipboard\((.*?)\);", html, re.S):
        args = re.findall(r"'((?:[^'\\]|\\.)*)'", call)
        if len(args) < 4:
            continue
        keym = re.search(r"view_image\.php\?key=([0-9a-f]+)", call)
        if not keym:
            continue
        rows.append({
            "instrument_no": args[0],
            "date": args[1].strip(),
            "book_info": args[2].strip(),
            "doc_type": args[3].strip(),
            "grantor": (args[6].strip() if len(args) > 6 else ""),
            "grantee": (args[7].strip() if len(args) > 7 else ""),
            "key": keym.group(1),
        })
    return rows


def _owner_row(row: dict, last: str, first: str) -> bool:
    blob = f"{row.get('grantor', '')} {row.get('grantee', '')}".upper()
    return bool(last) and last in blob and (not first or first in blob)


def _parse_date(s: str):
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _rank_dot_rows(rows: list[dict], last: str, first: str) -> list[dict]:
    """Ranked Deed-of-Trust candidate rows, newest note first (most recent note =
    best payoff basis). Owner-matched rows preferred; falls back to all DOT rows
    when party columns are blank/ambiguous.

    Returns a LIST (not one row) because Spartanburg's index mislabels some
    satisfactions as plain 'MORTGAGE' — the doc_type filter can't catch those, so
    the caller OCRs candidates in order and keeps the first that yields a real
    dollar amount (a satisfaction OCRs to a null amount)."""
    dots = [r for r in rows
            if _DOT_RE.search(r.get("doc_type", ""))
            and not _NOT_A_NOTE_RE.search(r.get("doc_type", ""))
            and r.get("key")]
    if not dots:
        return []
    mine = [r for r in dots if _owner_row(r, last, first)] or dots

    def _key(r):
        d = _parse_date(r.get("date", ""))
        return d or datetime.min
    return sorted(mine, key=_key, reverse=True)


def _pick_dot_row(rows: list[dict], last: str, first: str) -> Optional[dict]:
    """Best single DOT candidate (newest note). Thin wrapper over _rank_dot_rows
    for callers/tests that want just the top pick."""
    ranked = _rank_dot_rows(rows, last, first)
    return ranked[0] if ranked else None


async def _render_owner_dot_pdfs(owner: str, max_candidates: int = 3,
                                 timeout_ms: int = 90000
                                 ) -> list[tuple[bytes, dict]]:
    """Render the owner's Spartanburg ROD and download the free view_image.php PDF
    for up to `max_candidates` ranked Deed-of-Trust rows (newest note first),
    using the render session's cookies.

    Returns a list of (pdf_bytes, row_dict), newest note first, or []. Mirrors
    rod/logan_render's proven Accept -> name-search -> pick-list -> records-frame
    flow, but keeps the browser OPEN to do the cookie-scoped image download
    (view_image.php returns 200 + 0 bytes to a session-less request). Multiple
    candidates are downloaded because Spartanburg's index mislabels some
    satisfactions as plain 'MORTGAGE'; the caller OCRs them in order and keeps the
    first with a real amount."""
    base = LOGAN_RENDER_COUNTIES.get(_TARGET)
    if not base or not owner:
        return []
    last, first = _name_parts(owner)
    if not last:
        return []
    try:
        from playwright.async_api import async_playwright
    except Exception:  # pragma: no cover - playwright optional
        return []

    try:
        async with async_playwright() as p:
            br = await p.chromium.launch(headless=True)
            ctx = await br.new_context(ignore_https_errors=True)
            pg = await ctx.new_page()
            pg.set_default_timeout(timeout_ms)
            await pg.goto(base + "/index.php", wait_until="domcontentloaded", timeout=30000)
            await pg.wait_for_timeout(1800)
            el = await pg.query_selector("input[name=Accept]")
            if el:
                await el.click()
            # Search form frame loads via JS AFTER Accept — poll for it.
            tgt = None
            for _ in range(14):
                await pg.wait_for_timeout(2500)
                for fr in pg.frames:
                    try:
                        if await fr.query_selector("input[name=last_name]"):
                            tgt = fr
                            break
                    except Exception:
                        pass
                if tgt:
                    break
            if tgt is None:
                await br.close()
                return []
            try:
                await tgt.eval_on_selector("a[onclick*=\"setSearch('name')\"]", "e=>e.click()")
            except Exception:
                pass
            await pg.wait_for_timeout(600)
            await tgt.fill("input[name=last_name]", last)
            if first:
                try:
                    await tgt.fill("input[name=first_name]", first)
                except Exception:
                    pass
            await tgt.eval_on_selector_all(
                "a", "els=>{const e=els.find(x=>/Search \\(F2\\)/.test(x.innerText));if(e)e.click();}")
            await pg.wait_for_timeout(9000)
            # pick-list frame -> select all -> submit
            rf = None
            for _ in range(6):
                for fr in pg.frames:
                    try:
                        n = await fr.evaluate(
                            "()=>{const pl=document.querySelector('#plresults');"
                            "return pl?pl.querySelectorAll('tbody tr').length:0;}")
                        if n and n > 0:
                            rf = fr
                            break
                    except Exception:
                        pass
                if rf:
                    break
                await pg.wait_for_timeout(2500)
            if rf is not None:
                await rf.evaluate("()=>{try{if(window.checkAllPickList)checkAllPickList();}catch(e){}}")
                await pg.wait_for_timeout(1200)
                await rf.evaluate("()=>{try{if(window.submitPickList)submitPickList();}catch(e){}}")
            # records frame (>=3 summary cells)
            html = ""
            for _ in range(12):
                await pg.wait_for_timeout(3000)
                for fr in pg.frames:
                    try:
                        h = await fr.content()
                    except Exception:
                        continue
                    if len(_SUMMARY_RE.findall(h)) >= 3:
                        html = h
                        break
                if html:
                    break
            if not html:
                await br.close()
                return []
            rows = _parse_image_rows(html)
            ranked = _rank_dot_rows(rows, last, first)
            if not ranked:
                await br.close()
                return []
            # Cookie-scoped download inside the render session (page.request shares
            # the guest PHPSESSID; a session-less GET gets 200 + 0 bytes). Grab up
            # to max_candidates ranked notes so the caller can skip an index-
            # mislabeled satisfaction and fall through to the real note.
            out: list[tuple[bytes, dict]] = []
            for row in ranked[:max(1, max_candidates)]:
                try:
                    resp = await pg.request.get(f"{base}/view_image.php?key={row['key']}")
                    body = await resp.body()
                except Exception:  # noqa: BLE001
                    continue
                if resp.status == 200 and body[:4] == b"%PDF":
                    out.append((body, row))
            await br.close()
            return out
    except Exception:  # noqa: BLE001 - best-effort, retry next run
        return []
    return []


def _apply(li, loan: float, row: dict, ocr: dict) -> None:
    """Write raw['loan_amount'] + raw['dot_ocr'] and append a rod_docs entry so
    the equity engine (_recorded_dt) reads the amortized-payoff basis."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    rec = _parse_date(row.get("date", ""))
    li.raw["loan_amount"] = loan
    li.raw["dot_ocr"] = {
        "loan_amount": loan,
        "doc_type": row.get("doc_type"),
        "recorded_date": rec.date().isoformat() if rec else None,
        "book_info": row.get("book_info"),
        "instrument_no": row.get("instrument_no"),
        "image_key": row.get("key"),
        "ocr_owner": ocr.get("owner_name"),
        "ocr_property_address": ocr.get("property_address"),
        "provider": ocr.get("_provider"),
        "source": "spartanburg_dot_ocr",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    # Feed the equity engine via the ALREADY-allowlisted rod_docs list (append,
    # don't clobber a real ROD sweep). doc_type + amount + recorded_date are what
    # enrichment_equity._recorded_dt keys on.
    docs = li.raw.get("rod_docs")
    if not isinstance(docs, list):
        docs = []
    docs.append({
        "doc_type": row.get("doc_type") or "DEED OF TRUST",
        "amount": loan,
        "recorded_date": rec.isoformat() if rec else None,
        "book": None, "page": None,
        "grantor": row.get("grantor") or None,
        "grantee": row.get("grantee") or None,
        "county": "Spartanburg", "state": "SC",
        "instrument_no": row.get("instrument_no"),
        "source": "spartanburg_dot_ocr",
    })
    li.raw["rod_docs"] = docs


def _dot_age_days(li, now: datetime) -> Optional[float]:
    d = (li.raw or {}).get("dot_ocr") if isinstance(li.raw, dict) else None
    fa = (d or {}).get("fetched_at")
    if not fa:
        return None
    try:
        dt = datetime.fromisoformat(fa)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds() / 86400.0
    except Exception:  # noqa: BLE001
        return None


def _is_hot_warm(li) -> bool:
    tier = ((li.raw or {}).get("distress_stack") or {}).get("tier")
    return tier in ("HOT", "WARM")


def _has_mortgage_signal(li) -> bool:
    """Prefer leads the ROD index already flagged as carrying a mortgage — no
    point rendering a DOT search for a lead with no mortgage on file. When the
    ROD hasn't run yet we don't know, so treat unknown as eligible (best-effort).
    """
    rod = (li.raw or {}).get("rod") if isinstance(li.raw, dict) else None
    if isinstance(rod, dict) and "has_mortgage" in rod:
        return bool(rod.get("has_mortgage"))
    return True  # ROD not yet fetched -> allow, the render itself confirms


async def enrich_dot_ocr(listings, max_lookups: Optional[int] = None) -> dict:
    """Best-effort DOT loan-amount OCR for HOT/WARM Spartanburg leads."""
    if os.environ.get("FORECLOSURE_DOT_OCR", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_DOT_OCR=0)"}

    # Provider check up front — no free Gemini key = nothing to OCR with.
    from .enrichment_vision import _parse_gemini_keys
    gemini_keys = _parse_gemini_keys()
    if not gemini_keys:
        return {"skipped": "no Gemini key (set GEMINI_API_KEY_n)"}

    force = os.environ.get("FORECLOSURE_DOT_OCR_FORCE", "0") == "1"
    cap = max_lookups if max_lookups is not None else int(
        os.environ.get("FORECLOSURE_DOT_OCR_MAX", "25"))
    refresh_days = float(os.environ.get("FORECLOSURE_DOT_OCR_REFRESH_DAYS", "30"))
    budget_s = float(os.environ.get("FORECLOSURE_DOT_OCR_BUDGET_S", "1800"))  # 30m safety
    now = datetime.now(timezone.utc)
    t0 = time.monotonic()

    def _eligible(li) -> bool:
        if li.state != "SC" or (li.county or "").strip() != "Spartanburg":
            return False
        if not li.owner_name or not _is_hot_warm(li):
            return False
        if not _has_mortgage_signal(li):
            return False
        if force:
            return True
        age = _dot_age_days(li, now)
        return age is None or age >= refresh_days

    targets = [li for li in listings if _eligible(li)]
    # Never-fetched first, then stalest — a budget-trimmed run still progresses.
    targets.sort(key=lambda li: (_dot_age_days(li, now) is not None,
                                 -(_dot_age_days(li, now) or 1e9)))
    total_pending = len(targets)
    targets = targets[:cap]

    stats = {"pending": total_pending, "targets": len(targets), "searched": 0,
             "pdf_ok": 0, "loan_found": 0, "budget_exhausted": False}
    if not targets:
        return stats

    from . import enrichment_doc_ocr as ocr
    max_candidates = int(os.environ.get("FORECLOSURE_DOT_OCR_CANDIDATES", "3"))

    async def _ocr_amount(pdf: bytes):
        """OCR one scanned DOT PDF via the shared FREE Gemini path; return
        (loan, parsed) with loan=None when no dollar amount (e.g. a satisfaction)."""
        parsed = None
        for k in gemini_keys:
            try:
                parsed = await ocr._gemini_call(k, [(pdf, "application/pdf")], is_text=False)
            except ocr._QuotaOut:
                continue
            except Exception:  # noqa: BLE001
                parsed = None
            if parsed:
                break
        if not parsed:
            return None, None
        loan = ocr._clean_amount(parsed.get("amount"))
        # Reject implausibly small figures. A satisfaction/release carries no loan
        # amount, but its document body often contains nominal boilerplate
        # ("$1.00", "$10.00 and other valuable consideration") or a stray page/tax
        # figure — treat anything below the floor as "no real loan" so the loop
        # falls through to the next candidate (the actual note).
        return (loan if loan and loan >= _MIN_LOAN else None), parsed

    for li in targets:
        if time.monotonic() - t0 > budget_s:
            stats["budget_exhausted"] = True
            break
        stats["searched"] += 1
        try:
            candidates = await _render_owner_dot_pdfs(li.owner_name, max_candidates)
        except Exception:  # noqa: BLE001
            candidates = []
        if not candidates:
            continue  # render/download failed -> leave unstamped, retry next run
        stats["pdf_ok"] += 1
        # OCR candidates newest-first; keep the first with a real dollar amount
        # (skips an index-mislabeled satisfaction, which OCRs to a null amount).
        for pdf, row in candidates:
            loan, parsed = await _ocr_amount(pdf)
            if loan:
                _apply(li, loan, row, parsed)
                stats["loan_found"] += 1
                break

    log.info("dot_ocr.done", **stats)
    return stats
