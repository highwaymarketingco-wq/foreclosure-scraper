"""Recorded Deed-of-Trust ORIGINAL PRINCIPAL via free document-image OCR — the
one input that turns raw['rod'] lien EXISTENCE into an equity number.

The problem
-----------
Every Register-of-Deeds INDEX in this repo tells us a lead HAS a mortgage but
carries NO dollar figure: the principal is printed only inside the recorded
instrument image. Without it the equity engine has no payoff basis, so every
downstream max-bid is soft.

What this does
--------------
Per eligible lead, in a county whose recorder serves the document image FREE and
ROBOTS-CLEAN (`rod/doc_images.DOC_IMAGE_COUNTIES`):

  1. resolve the owner's Deed-of-Trust recordings (per-vendor, see rod/doc_images);
  2. download the free image (PDF, or a TIFF normalized to a PNG of page 1);
  3. OCR it for the "principal sum of $X" via enrichment_doc_ocr's FREE
     Gemini-first path (recorded pages are scans with no text layer);
  4. write raw['loan_amount'] + raw['dot_ocr'] AND append a rod_docs entry
     (doc_type='DEED OF TRUST', amount, recorded_date) so
     enrichment_equity._recorded_dt picks it up as the amortization basis;
  5. stamp the labelled ESTIMATED current balance (valuation.amortize
     .estimate_current_balance) onto raw['dot_ocr']['estimated_balance'].

The recorded principal is a FACT. The current balance is an ESTIMATE — a true
payoff is borrower-only under TILA/RESPA — and is labelled as such everywhere.

Compliance
----------
County access is gated in ONE place: `rod/doc_images.ensure_allowed`, a live
robots.txt evaluation run before every request, with NO env bypass. The four
i3 Verticals / Logan tenants this module used to target (Spartanburg, Laurens,
McDowell, Mitchell) all publish `Allow: /$` + `Disallow: /` — the same
machine-readable no-automation directive rod/kofile.py already treats as a wall
— so the legacy Spartanburg render path below is retained but can no longer
fire. It reactivates by itself the day the county relaxes robots.

Bounding (this pipeline has hung on unbounded per-lead loops before)
--------------------------------------------------------------------
Four independent limits, all env-tunable:
  FORECLOSURE_DOT_OCR_MAX          total leads per run       (default 400)
  FORECLOSURE_DOT_OCR_COUNTY_MAX   leads per county per run  (default 200)
  FORECLOSURE_DOT_OCR_BUDGET_S     wall clock for the whole enricher (1800)
  FORECLOSURE_DOT_OCR_SWEEP_BUDGET_S  wall clock per county index sweep (300)

Gating: the old HOT/WARM-only grade gate is GONE (a cold lead's equity is
exactly what tells you it is not cold). Set FORECLOSURE_DOT_OCR_TIERS to a
comma list, e.g. "HOT,WARM", to re-narrow. Disable with FORECLOSURE_DOT_OCR=0.
Idempotent: skips leads already carrying raw['dot_ocr'] younger than
FORECLOSURE_DOT_OCR_REFRESH_DAYS unless FORECLOSURE_DOT_OCR_FORCE=1.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import structlog

from .http_client import client as http_client
from .rod import doc_images as di
from .rod.doc_images import DOC_IMAGE_COUNTIES, LoganImageSession
from .rod.logan_render import LOGAN_RENDER_COUNTIES, _SUMMARY_RE

log = structlog.get_logger(__name__)

# Legacy render target. Kept so it flips back on for free if the county relaxes
# robots; `ensure_allowed` currently short-circuits it (Disallow: /).
_TARGET = ("SC", "Spartanburg")

# Re-exported so existing importers/tests keep working; the canonical
# definitions now live in rod/doc_images so every vendor shares one rule.
_DOT_RE = di.DOT_RE
_NOT_A_NOTE_RE = di.NOT_A_NOTE_RE

# A real recorded mortgage note is well above this; nominal deed/satisfaction
# consideration ("$1", "$10 and other valuable consideration") and stray page or
# tax figures fall below it and must NOT be accepted as a loan amount.
_MIN_LOAN = float(os.environ.get("FORECLOSURE_DOT_OCR_MIN_LOAN", "1000"))
# Ceiling guard: an OCR misread of a parcel id / book+page concatenation would
# otherwise become a billion-dollar "principal" and drive equity to nonsense.
_MAX_LOAN = float(os.environ.get("FORECLOSURE_DOT_OCR_MAX_LOAN", "20000000"))


def _name_parts(owner: str) -> tuple[str, str]:
    return di.name_parts(owner)


def _parse_image_rows(html: str) -> list[dict]:
    """Parse the Spartanburg Logan records grid into per-instrument rows carrying
    the free view_image.php key.

    Each row emits a `copyToClipboard('<inst>','<date>','<book_info>','<DOC_TYPE>',
    '<legal>','<party_type>','<searched>','<reverse>',...,'...view_image.php?key=
    <hash>...')` call — the DOC TYPE and the image key are both right there.
    Retained for the legacy (currently robots-walled) render path."""
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
    best amortization basis). Owner-matched rows preferred; falls back to all DOT
    rows when party columns are blank/ambiguous.

    Returns a LIST because county indexes mislabel some satisfactions as plain
    'MORTGAGE' — the doc_type filter can't catch those, so the caller OCRs
    candidates in order and keeps the first that yields a real dollar amount."""
    dots = [r for r in rows if di.is_dot_type(r.get("doc_type", "")) and r.get("key")]
    if not dots:
        return []
    mine = [r for r in dots if _owner_row(r, last, first)] or dots

    def _key(r):
        return _parse_date(r.get("date", "")) or datetime.min
    return sorted(mine, key=_key, reverse=True)


def _pick_dot_row(rows: list[dict], last: str, first: str) -> Optional[dict]:
    """Best single DOT candidate (newest note)."""
    ranked = _rank_dot_rows(rows, last, first)
    return ranked[0] if ranked else None


async def _render_owner_dot_pdfs(owner: str, max_candidates: int = 3,
                                 timeout_ms: int = 90000
                                 ) -> list[tuple[bytes, dict]]:
    """LEGACY Spartanburg render path — robots-GATED and currently a no-op.

    search.spartanburgdeeds.com publishes `Allow: /$` + `Disallow: /`, so the
    guard below returns [] before any request is made. The flow is kept intact
    (it was live-verified before the robots file was read) so the county
    relaxing its robots.txt re-enables it with no code change."""
    base = LOGAN_RENDER_COUNTIES.get(_TARGET)
    if not base or not owner:
        return []
    if not await di.ensure_allowed(f"{base}/view_image.php"):
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
            # the guest PHPSESSID; a session-less GET gets 200 + 0 bytes).
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


# --------------------------------------------------------------------------- #
# Write-back                                                                    #
# --------------------------------------------------------------------------- #
def _apply(li, loan: float, row: dict, ocr: dict) -> None:
    """Write raw['loan_amount'] + raw['dot_ocr'] and append a rod_docs entry so
    the equity engine (_recorded_dt) reads the amortization basis.

    `row` keys: doc_type, date (MM/DD/YYYY) or recorded_date (datetime),
    book_info/book/page, instrument_no, key, grantor, grantee, county, state,
    source.
    """
    from .valuation.amortize import estimate_current_balance

    if not isinstance(li.raw, dict):
        li.raw = {}
    rec = row.get("recorded_date")
    if not isinstance(rec, datetime):
        rec = _parse_date(row.get("date", "") or "")
    county = row.get("county") or (li.county or "")
    state = row.get("state") or (li.state or "")
    est = estimate_current_balance(loan, rec, basis="recorded_principal") if rec else None
    li.raw["loan_amount"] = loan
    li.raw["dot_ocr"] = {
        "loan_amount": loan,                 # recorded ORIGINAL principal (a fact)
        "is_original_principal": True,
        "estimated_balance": (est or {}).get("estimated_balance"),
        "estimated_balance_confidence": (est or {}).get("confidence"),
        "estimated_balance_detail": est,
        "not_a_payoff": ("recorded original principal + modeled amortization; a "
                         "true payoff is borrower-only under TILA/RESPA"),
        "doc_type": row.get("doc_type"),
        "recorded_date": rec.date().isoformat() if rec else None,
        "book": row.get("book"), "page": row.get("page"),
        "book_info": row.get("book_info"),
        "instrument_no": row.get("instrument_no"),
        "image_key": row.get("key"),
        "ocr_owner": ocr.get("owner_name"),
        "ocr_property_address": ocr.get("property_address"),
        "provider": ocr.get("_provider"),
        "county": county, "state": state,
        "source": row.get("source") or "rod_dot_ocr",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    # Feed the equity engine via the ALREADY-allowlisted rod_docs list (append,
    # don't clobber a real ROD sweep). doc_type + amount + recorded_date are what
    # enrichment_equity._recorded_dt keys on.
    docs = li.raw.get("rod_docs")
    if not isinstance(docs, list):
        docs = []
    inst = row.get("instrument_no")
    if not any(isinstance(d, dict) and d.get("instrument_no") == inst
               and d.get("source", "").endswith("dot_ocr") for d in docs):
        docs.append({
            "doc_type": row.get("doc_type") or "DEED OF TRUST",
            "amount": loan,
            "recorded_date": rec.isoformat() if rec else None,
            "book": row.get("book"), "page": row.get("page"),
            "grantor": row.get("grantor") or None,
            "grantee": row.get("grantee") or None,
            "county": county, "state": state,
            "instrument_no": inst,
            "source": row.get("source") or "rod_dot_ocr",
        })
    li.raw["rod_docs"] = docs


def _row_from_doc(doc) -> dict:
    """RodDoc -> the flat row dict `_apply` writes from."""
    return {
        "doc_type": doc.doc_type,
        "recorded_date": doc.recorded_date,
        "book": doc.book, "page": doc.page,
        "book_info": f"{doc.book or ''} {doc.page or ''}".strip() or None,
        "instrument_no": doc.instrument_no,
        "key": (doc.raw or {}).get("image_key"),
        "grantor": doc.grantor, "grantee": doc.grantee,
        "county": doc.county, "state": doc.state,
        "source": f"{(doc.raw or {}).get('vendor') or 'rod'}_dot_ocr",
    }


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


def _tier(li) -> Optional[str]:
    return ((li.raw or {}).get("distress_stack") or {}).get("tier")


def _has_mortgage_signal(li) -> bool:
    """Prefer leads the ROD index already flagged as carrying a mortgage. When
    the ROD hasn't run yet we don't know, so treat unknown as eligible."""
    rod = (li.raw or {}).get("rod") if isinstance(li.raw, dict) else None
    if isinstance(rod, dict) and "has_mortgage" in rod:
        return bool(rod.get("has_mortgage"))
    return True  # ROD not yet fetched -> allow, the lookup itself confirms


# --------------------------------------------------------------------------- #
# Entry point                                                                   #
# --------------------------------------------------------------------------- #
async def enrich_dot_ocr(listings, max_lookups: Optional[int] = None) -> dict:
    """Best-effort recorded-principal OCR across every free + robots-clean county."""
    if os.environ.get("FORECLOSURE_DOT_OCR", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_DOT_OCR=0)"}

    # Provider check up front — no free Gemini key = nothing to OCR with.
    from .enrichment_vision import _parse_gemini_keys
    gemini_keys = _parse_gemini_keys()
    if not gemini_keys:
        return {"skipped": "no Gemini key (set GEMINI_API_KEY_n)"}

    force = os.environ.get("FORECLOSURE_DOT_OCR_FORCE", "0") == "1"
    cap = max_lookups if max_lookups is not None else int(
        os.environ.get("FORECLOSURE_DOT_OCR_MAX", "400"))
    county_cap = int(os.environ.get("FORECLOSURE_DOT_OCR_COUNTY_MAX", "200"))
    refresh_days = float(os.environ.get("FORECLOSURE_DOT_OCR_REFRESH_DAYS", "30"))
    budget_s = float(os.environ.get("FORECLOSURE_DOT_OCR_BUDGET_S", "1800"))
    sweep_budget_s = float(os.environ.get("FORECLOSURE_DOT_OCR_SWEEP_BUDGET_S", "300"))
    sweep_years = float(os.environ.get("FORECLOSURE_DOT_OCR_SWEEP_YEARS", "6"))
    sweep_window = int(os.environ.get("FORECLOSURE_DOT_OCR_SWEEP_WINDOW_DAYS", "60"))
    max_candidates = int(os.environ.get("FORECLOSURE_DOT_OCR_CANDIDATES", "3"))
    # Empty (the default) = NO grade gate. The old HOT/WARM-only rule hid equity
    # from exactly the leads whose grade was low BECAUSE equity was unknown.
    tiers = {t.strip().upper() for t in
             os.environ.get("FORECLOSURE_DOT_OCR_TIERS", "").split(",") if t.strip()}
    now = datetime.now(timezone.utc)
    t0 = time.monotonic()

    def _eligible(li) -> bool:
        key = ((li.state or "").strip(), (li.county or "").strip())
        if key not in DOC_IMAGE_COUNTIES:
            return False
        if not (li.owner_name or "").strip():
            return False
        if tiers and _tier(li) not in tiers:
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

    stats = {"pending": total_pending, "targets": 0, "searched": 0, "image_ok": 0,
             "loan_found": 0, "rejected_not_note": 0, "budget_exhausted": False,
             "gemini_quota_exhausted": False, "fallback_ocr": 0,
             "counties": {}, "walled_counties": sorted(
                 f"{s}:{c}" for (s, c), (v, _) in di.COUNTY_IMAGE_STATUS.items()
                 if v != "free")}
    if not targets:
        log.info("dot_ocr.done", **stats)
        return stats

    # Group by county so a per-county index sweep is paid ONCE, not per lead.
    by_county: dict[tuple[str, str], list] = {}
    for li in targets:
        by_county.setdefault(((li.state or "").strip(), (li.county or "").strip()), []).append(li)

    from . import enrichment_doc_ocr as ocr

    gh_token = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    groq_token = os.environ.get("GROQ_API_KEY")

    async def _ocr_amount(data: bytes, mime: str):
        """OCR one document across the FREE provider chain; return (loan, parsed).

        Gemini first (the only free backend that takes `application/pdf`), then
        GitHub Models and Groq. A live Burke/Cleveland/Transylvania run on
        2026-08-04 OCR'd 10 notes and then produced ZERO from the next 108
        downloaded documents — all nine Gemini keys were quota-exhausted, and
        with no fallback the rest of the run was wasted network. So when Gemini
        is out we rasterize page 1 to PNG (the compat backends take images, not
        PDFs) and keep going.

        loan is None when the page carries no plausible principal (a
        satisfaction) or when the document reads as a conveyance, not a note.
        """
        parsed = None
        quota_out = 0
        for k in gemini_keys:
            try:
                parsed = await ocr._gemini_call(k, [(data, mime)], is_text=False)
            except ocr._QuotaOut:
                quota_out += 1
                continue
            except Exception:  # noqa: BLE001
                parsed = None
            if parsed:
                break
        if not parsed and quota_out == len(gemini_keys) and (gh_token or groq_token):
            stats["gemini_quota_exhausted"] = True
            blocks = None
            if mime == "application/pdf":
                png = di.rasterize_pdf_page1(data)
                if png:
                    blocks = [png]
            else:
                blocks = [(data, mime)]
            for name, url, key, model in (
                    ("github", ocr.GITHUB_MODELS_URL, gh_token, ocr.GITHUB_MODELS_MODEL),
                    ("groq", ocr.GROQ_URL, groq_token, ocr.GROQ_MODEL)):
                if not key or not blocks:
                    continue
                try:
                    async with http_client(timeout=90.0) as hc:
                        parsed = await ocr._openai_compat_call(hc, name, url, key,
                                                               model, blocks)
                except ocr._QuotaOut:
                    continue
                except Exception:  # noqa: BLE001
                    parsed = None
                if parsed:
                    stats["fallback_ocr"] = stats.get("fallback_ocr", 0) + 1
                    break
        if not parsed:
            return None, None
        if not di.ocr_is_note(parsed):
            # e.g. an index row mislabeled a trustee's deed as a note; its dollar
            # figure is the AUCTION price, the opposite of a payoff basis.
            return None, parsed
        loan = ocr._clean_amount(parsed.get("amount"))
        if loan and _MIN_LOAN <= loan <= _MAX_LOAN:
            return loan, parsed
        return None, parsed

    async def _run_county(state: str, county: str, leads: list) -> None:
        leads = leads[:county_cap]
        stats["targets"] += len(leads)
        vendor = DOC_IMAGE_COUNTIES.get((state, county))
        cstat = {"leads": len(leads), "image_ok": 0, "loan_found": 0}
        stats["counties"][f"{state}:{county}"] = cstat

        logan_index = None
        sess = None
        try:
            if vendor == "logan":
                sess = LoganImageSession(state, county)
                await sess.__aenter__()
                if not sess.live:
                    return
                remaining = max(30.0, min(sweep_budget_s, budget_s - (time.monotonic() - t0)))
                swept = await sess.sweep_dots(years_back=sweep_years,
                                              window_days=sweep_window,
                                              budget_s=remaining)
                logan_index = di.index_by_surname(swept)
                cstat["swept_docs"] = len(swept)

            for li in leads:
                if time.monotonic() - t0 > budget_s or stats["searched"] >= cap:
                    stats["budget_exhausted"] = True
                    return
                stats["searched"] += 1
                try:
                    cands = await di.owner_dot_documents(
                        state, county, li.owner_name, max_candidates=max_candidates,
                        logan_index=logan_index, logan_session=sess)
                except Exception:  # noqa: BLE001
                    cands = []
                if not cands:
                    continue
                stats["image_ok"] += 1
                cstat["image_ok"] += 1
                for data, mime, doc in cands:
                    loan, parsed = await _ocr_amount(data, mime)
                    if loan:
                        _apply(li, loan, _row_from_doc(doc), parsed or {})
                        stats["loan_found"] += 1
                        cstat["loan_found"] += 1
                        break
                    if parsed and not di.ocr_is_note(parsed):
                        stats["rejected_not_note"] += 1
        finally:
            if sess is not None:
                await sess.__aexit__(None, None, None)

    for (state, county), leads in by_county.items():
        if time.monotonic() - t0 > budget_s or stats["searched"] >= cap:
            stats["budget_exhausted"] = True
            break
        try:
            await _run_county(state, county, leads)
        except Exception:  # noqa: BLE001 - one county must never kill the run
            log.warning("dot_ocr.county_failed", state=state, county=county)

    log.info("dot_ocr.done", **stats)
    return stats
