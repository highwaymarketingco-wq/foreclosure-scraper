"""Beaufort County SC Register of Deeds — "BrowserViewDMP" (New Vision Systems)
AngularJS portal adapter.

Live-verified 2026-10-14, cold (fresh client, zero prior requests), with NO
WAF, NO CAPTCHA, and NO login anywhere on this deployment:

  GET  api/search/clientinfo  -> {"authentication":"0","encryptData":"0",
      "useRecaptcha":null,"useRecaptchaV3":null,"freeAccessWithoutLogin":"0", ...}

`authentication`, `useRecaptcha(V3)` and `encryptData` are all OFF for this
specific county's deployment (confirmed live via its own config endpoint, not
assumed from the vendor's shared, feature-flagged JS bundle, which supports
all three when a *different* county turns them on). With `encryptData` off,
the Angular app's own `documentService.Encrypt(n)` is a documented passthrough
(`return this.Globals.encryptData ? this.Encryptor.encrypt(n) : n` — see
bundles/ControllerDefaultJs) — i.e. every "encrypted" field the client sends
(`ID`, `Book`, `Page`, dates, ...) is really sent in PLAIN TEXT on this site.

This was previously flagged (source_completeness_audit_2026-10-13.md, Pattern
C) only as "detail/image page never fetched" by sc_rod_walled.py's generic
Playwright DOM-table scraper (itself fragile against this county's ag-Grid
Angular SPA, which does not render as plain `<table><tr>` rows). Reading the
vendor's own minified JS (bundles/ControllerDefaultJs) instead of scraping its
rendered DOM exposes the real, free, browserless REST API underneath:

  POST api/search            {DocTypes, FromDate, ToDate, MaxRows, RowsPerPage,
                               StartRow, token} (YYYYMMDD dates; comma-joined
                               doc-type codes; Accept: application/json or the
                               service answers an empty-array XML envelope
                               instead) -> JSON array of rows, each already
                               carrying doc_id, party_name (direct/filing
                               party), cross_party_name (indirect party),
                               rec_date, doc_type, file_num, book, page,
                               legal_1, consid_1.
  POST api/pdf                {Token, ID: " "+doc_id} -> 200 application/pdf,
                               the COMPLETE scanned document (StartPage/Pages
                               are accepted but do not truncate it — verified
                               against 3 live documents of 1/3/5 pages: the
                               same full-page-count PDF came back whether
                               Pages was omitted, "1", or "50").

Doc-type codes come from the deployment's own api/document/doctypes (105
codes total for Beaufort); `DISTRESS_CODES` below whitelists the ones that
are an acquisition/motivated-seller signal (active liens + a death
certificate, mirroring rod/acclaim.py's probate+lien philosophy for the
sibling AcclaimWeb vendor) and deliberately excludes every satisfaction/
release/withdrawal counterpart code (MLR/MLSAT/RELCB/RELSB, SCEX/SCSAT/
SCPAREL/SCWD, USEX/USSAT/USPAREL/USWD, BTLS/BTLW, CANCEL, TERM, VOID, EXP) —
those are resolutions, not distress, and (unlike AcclaimWeb's freeform
DocType text) Beaufort's codes are an exact enumerated vocabulary, so a
whitelist needs no separate "RESOLVED" substring filter.

Live counts 2026-10-14, 2026-01-01..2026-10-14: LIEN=123, MECH=71, US=21,
DC=296 rows (SC/BNKRUPCY/CONDEM returned 0 in this window — kept in the
whitelist on the vendor's own taxonomy, not dropped for lack of a live
example). Confirmed real, differently-sized scanned PDFs for one doc of each
of LIEN/MECH/US/DC (1-5 pages, 51KB-545KB, correct %PDF-1.4 header every
time).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog

from .models import RodDoc

log = structlog.get_logger()

BASE = "https://rod.beaufortcountysc.gov/BrowserViewDMP"

_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json; charset=UTF-8",
}

#: code -> (canonical bucket, lead "kind") — see module docstring for the
#: live-verification evidence behind this whitelist. Public: scrapers/
#: counties_sc/sc_rod_walled.py reads the bucket to pick a ListingType.
DISTRESS_CODES: dict[str, tuple[str, str]] = {
    "LIEN": ("lien", "lien"),
    "MECH": ("mechanics_lien", "lien"),
    "SC": ("tax_lien", "lien"),       # SC TAX LIEN
    "US": ("tax_lien", "lien"),       # US/IRS TAX LIEN
    "DC": ("probate_deed", "probate"),  # DEATH CERTIFICATE
    "BNKRUPCY": ("bankruptcy", "bankruptcy"),
}


def pdf_url_and_body(doc_id: object) -> tuple[str, dict] | None:
    """The free, no-login POST recipe for one row's complete scanned PDF.

    `api/pdf` is a POST-only endpoint (a plain GET 405s) — there is no flat
    GET URL to stamp via document_links.stamp_documents the way the sibling
    AcclaimWeb counties do. Returns (url, json_body) for the caller to POST
    itself, or None when `doc_id` is not a usable row id.
    """
    if doc_id is None:
        return None
    try:
        did = int(float(doc_id))
    except (TypeError, ValueError):
        return None
    if did <= 0:
        return None
    return f"{BASE}/api/pdf", {"Token": None, "ID": f" {did}"}


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # e.g. "2026-01-16T00:00:00"
        return datetime.fromisoformat(s.split(".")[0])
    except ValueError:
        return None


def _row_to_doc(row: dict, state: str, county: str) -> RodDoc:
    doc_id = row.get("doc_id")
    raw: dict[str, Any] = {"beaufort_rod": row}
    fetch = pdf_url_and_body(doc_id)
    if fetch:
        url, body = fetch
        raw["beaufort_pdf_fetch"] = {"method": "POST", "url": url, "body": body}
    return RodDoc(
        county=county, state=state,
        doc_type=(row.get("doc_type") or "").strip(),
        recorded_date=_parse_date(row.get("rec_date")),
        book=str(row["book"]) if row.get("book") is not None else None,
        page=str(row["page"]) if row.get("page") is not None else None,
        grantor=(row.get("party_name") or "").strip() or None,
        grantee=(row.get("cross_party_name") or "").strip() or None,
        consideration_amount=row.get("consid_1") or None,
        instrument_no=(row.get("file_num") or "").strip() or None,
        notes=(row.get("legal_1") or "").strip() or None,
        raw=raw,
    )


async def discover_recent_distress(
    state: str = "SC", county: str = "Beaufort",
    days_back: int = 365, max_docs: int = 300,
) -> list[RodDoc]:
    """Sweep Beaufort's real JSON search API for recent distress recordings.

    One call covers the whole window (no AcclaimWeb-style per-request row cap
    was hit for this code set at 9.5 months of history — 511 rows, well under
    the ~1000-row ceiling this deployment appears to apply). days_back
    defaults generously to 365: live 2026-10-14, this deployment's own
    indexed `rec_date` values topped out around 2026-02-18 (recording-to-
    index lag, not a code issue) — a short lookback window can land entirely
    before the site's actual most-recent indexed data and silently return
    zero rows."""
    today = datetime.utcnow()
    frm = today - timedelta(days=max(1, days_back))
    body = {
        "DocTypes": ",".join(DISTRESS_CODES.keys()),
        "FromDate": frm.strftime("%Y%m%d"),
        "ToDate": today.strftime("%Y%m%d"),
        "MaxRows": 0, "RowsPerPage": 0, "StartRow": 0,
        "token": None,
    }
    out: list[RodDoc] = []
    scanned = 0
    try:
        # rod.beaufortcountysc.gov serves an EXPIRED TLS cert (not a WAF —
        # plain httpx/curl fail the handshake, not the request); verify=False
        # on curl-cffi's AsyncSession is this repo's existing convention for
        # that exact situation (enrichment_gaston_rod.py, enrichment_jail_
        # bookings.py, enrichment_sc_divorce.py all do the same for their own
        # expired-cert county sites). The shared http_client.client() has no
        # verify toggle, so it is not used here.
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120", timeout=45, verify=False) as c:
            r = await c.post(f"{BASE}/api/search", json=body, headers=_HEADERS)
            if r.status_code != 200:
                log.warning("beaufort_dmp.search_failed", status=r.status_code)
                return out
            try:
                rows = r.json()
            except ValueError:
                log.warning("beaufort_dmp.search_not_json", body=r.text[:200])
                return out
            scanned = len(rows)
            # Each document is indexed once per named party (party_name /
            # cross_party_name), so the SAME doc_id shows up as >=2 grid rows
            # (e.g. a death certificate indexed under both the decedent and
            # the co-owner) — dedupe on doc_id, the grid's real document key,
            # not instrument number (shared across parties too).
            seen: set = set()
            for row in rows:
                code = (row.get("doc_type") or "").strip()
                if code not in DISTRESS_CODES:
                    continue
                doc_id = row.get("doc_id")
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                out.append(_row_to_doc(row, state, county))
                if len(out) >= max_docs:
                    break
    except Exception:
        log.warning("beaufort_dmp.discover_failed", county=county)
        return out
    log.info("beaufort_dmp.discovered", county=county, scanned=scanned, distress=len(out))
    return out
