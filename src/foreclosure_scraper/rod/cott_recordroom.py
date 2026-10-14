"""Cott Systems "RecordRoom" Register-of-Deeds adapter (browserless, free).

Distinct from rod/cott.py (which handles the older cotthosting.com / Manatron
ASP.NET portals for NC Polk/Rutherford). RecordRoom is the newer
recordroom.cottsystems.com app with a DataTables JSON results endpoint. Guest
access to the INDEX is fully open. Returns party NAMES + doc type + book/page —
actionable leads like the Pickens/Acclaim path. SC is judicial, so ROD distress
here is PROBATE (deed of distribution / death) + LIENS. Reusable for any
RecordRoom county via COTT_RR_COUNTIES.

Flow (verified live), through the shared cookie-persisting client:
  1. GET  /{slug}/guest/Search/records      -> .ASPXANONYMOUS + session cookies
  2. POST /{slug}/search/Records (form FromDate/ThruDate/Type=""/Page=1)
        -> 302 PRG; stores the search server-side in session
  3. POST /{slug}/Search/Records/Result/ (JSON DataTables payload; the columns
        array is REQUIRED) -> {recordsTotal, data:[{Type, PartyOne, PartyTwo,
        RecordingDate, Property, FileNumber, BookPage}, ...]}; paginate via start.

Document images (CORRECTED 2026-10-14 — this module's own docstring previously
claimed "document images are pay-per-view"; that was never live-checked and
turned out wrong, the same way sc_rod_acclaim.py's/sc_rod_walled.py's "needs
login" flags did earlier the same session). Live-verified against 3 real Union
documents spanning every category this adapter classifies (a DEATH
CERTIFICATE/PROBATE_NOTICE, a $540,000 DEED, and a $42,000 MTG/deed-of-trust):
  * `/{slug}/Imaging/Document/KeyFromImage?IndexId=` (the URL the UI's "View
    Document Details" button opens in a new window) DOES 302 to
    `Portal/Account/LoginRoute` on a cold request — this is the one fact that
    made the original "pay-per-view" docstring plausible. It is NOT used here.
  * The real per-page image the Details page itself renders is served by a
    DIFFERENT, genuinely free, no-login, no-payment route:
      a. GET `/{slug}/Imaging/Document/Thumbnails?indexId=<IndexId>&indexAction=Search`
         (XHR, `Referer: /{slug}/Guest/Search/Records/Details?IndexId=<IndexId>`
         — REQUIRED here too, not just on the image fetch: live-caught
         2026-10-14, an otherwise-identical request without it IIS-401s
         "Access is denied due to invalid credentials" even with valid
         session cookies) -> JSON array, one entry per scanned page, each
         carrying a fabric.js `Serialized` blob whose `"src"` field is the
         complete, ready-to-fetch image URL (`Imaging/Document/Image?
         PageId=...&imageAction=...&DocumentId=...&Version=...&VolumeId=...&
         Name=...&r=...`).
      b. GET that `src` URL with the SAME `Referer` -> 200 `image/png`,
         full-resolution (2550x3300, ~300dpi) scanned page.
    Both requests only need the plain anonymous `.ASPXANONYMOUS` cookie step 1
    above already sets plus that Referer — no account, no CAPTCHA, no
    purchase, no browser. `imageAction`'s exact value does not matter
    (confirmed by substituting an arbitrary string) and the Referer's IndexId
    does not need to belong to a prior search in THIS session (confirmed
    cold: step 1 + the two Referer-bearing requests, nothing else) — it only
    has to match the IndexId in the request itself. A Referer naming a
    DIFFERENT (even nonexistent) IndexId fails the same way on both requests,
    so the Referer is a real, mandatory gate, not cosmetic.
  See `image_fetch_recipe`/`document_image_url`/`fetch_document_image` below,
  and docs/source_completeness_audit_2026-10-13.md's "Needs YOU logged in"
  section for the full settled writeup.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import structlog

from ..http_client import client
from .models import RodDoc

log = structlog.get_logger()

COTT_RR_HOST = "https://recordroom.cottsystems.com"
COTT_RR_COUNTIES: dict[tuple[str, str], str] = {
    ("SC", "Union"): "unionsc",
}

# Distress KindCodes (probate + liens). Matched as substrings; resolutions out.
# "DIS STMT" was REMOVED 2026-10-04 (extraction-completeness audit, batch 13):
# live-pulled every "DEE DIS STMT" row Union has recorded in the last 90 days
# (37 of them -- 74% of this adapter's entire live "distress" output) and 37/37
# are "HOMEOWNERS DISCLOSURE STATEMENT" filings with the Department of Building
# Safety / City of Union Planning Department as the counterparty (a routine
# manufactured-home-to-real-property titling disclosure), NOT an estate
# "distribution statement" -- the abbreviation this token was added for. Every
# one was shipping live as a PROBATE_NOTICE with the homeowner tagged as a
# decedent. "DISTRIB" (a real "DEED OF DISTRIBUTION" would contain it) is kept;
# it never matched a single live row in a full 1-year sweep, but it is not a
# false-positive risk the way "DIS STMT" was.
_DISTRESS = ("DOD", "DEED OF DIST", "DEATH", "DISTRIB",
             "TAX LIEN", "LIEN", "MECH", "JUDG", "EXECUTION")
_RESOLVED = ("SAT", "REL", "TERM", "CANCEL", "RESC", "SUBORD", "WITHDRAW")

# Markup inside the "Property"/"PartyTwo" cells (see module docstring: each is
# raw vendor HTML, not plain text). Parcel #, the property's own situs address,
# the legal-description "Remarks", and a deed's $ consideration are each a
# separate <strong>Label:</strong> <span class="indexdetail_data">...</span>
# run inside the same cell _clean() used to flatten to one soup string --
# confirmed live 2026-10-04 on a real "DEE DOD" (deed of distribution) row:
# Parcel # "074-10-02-003" + situs "709 PERRIN AVENUE  UNION, SC 29379" were
# both present and both thrown away, the heir-defendant's own OWN mailing
# address (on PartyTwo, same markup) too. Regex, not an HTML parser, to match
# this module's own existing _clean() convention for these small vendor cells.
_PARCEL_RE = re.compile(r'Parcel\s*#:</strong>\s*<span[^>]*>\s*<a[^>]*>([^<]+)</a>', re.I)
_REMARKS_RE = re.compile(r'Remarks:</strong>\s*<span[^>]*>([^<]+)</span>', re.I)
_AMOUNT_RE = re.compile(r'Amount:</strong>\s*\$\s*([\d,]+(?:\.\d+)?)', re.I)
# Property's own address div uses <strong>Address:</strong>; a party's (grantor/
# grantee) uses <span class="indexdetail_label">Address: </span> -- both close
# with the same indexdetail_address > indexdetail_data pair, so one pattern
# anchored on the wrapper class covers both markups.
_ADDR_BLOCK_RE = re.compile(
    r'class="indexdetail_address">.*?class="indexdetail_data">([^<]+)</span>',
    re.I | re.S)


def _extract_parcel(html: str | None) -> str | None:
    m = _PARCEL_RE.search(html or "")
    return _clean(m.group(1)) or None if m else None


def _extract_remarks(html: str | None) -> str | None:
    m = _REMARKS_RE.search(html or "")
    return _clean(m.group(1)) or None if m else None


def _extract_amount(html: str | None) -> float | None:
    m = _AMOUNT_RE.search(html or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _extract_block_address(html: str | None) -> str | None:
    m = _ADDR_BLOCK_RE.search(html or "")
    return _clean(m.group(1)) or None if m else None


# --------------------------------------------------------------------------- #
# Document images — free, no login (see module docstring for the live        #
# verification evidence).                                                     #
# --------------------------------------------------------------------------- #
# The complete `Imaging/Document/Image?...` URL the Thumbnails JSON embeds
# inside each page's fabric.js `Serialized` blob (as a `"src":"..."` string).
_IMG_SRC_RE = re.compile(r'"src"\s*:\s*"(https?://[^"]*/Imaging/Document/Image\?[^"]+)"')


def image_fetch_recipe(base: str, index_id: object) -> dict | None:
    """The free, no-login recipe to resolve + fetch one document's scanned
    page image, keyed only off `index_id` (the `IndexId` every search-grid row
    already carries). Pure/no I/O -- the caller does the two GETs themselves
    (see `fetch_document_image`) or a later enrichment pass replays this
    recipe. None when `index_id` is not a usable id.

    Two requests, both needing only the plain anonymous session cookie `GET
    /{slug}/guest/Search/records` already sets (no account):
      1. GET `thumbnails_url` (XHR) -> JSON page list; each page's own
         `Serialized` field embeds the real `Imaging/Document/Image` URL
         (see `document_image_url`).
      2. GET that URL with `Referer: details_referer` -> 200 image/png.
    The Referer's IndexId must match `index_id` (a mismatched or made-up one
    302s to a login route) -- this recipe keeps both in lockstep by
    construction.
    """
    if index_id is None or (isinstance(index_id, str) and not index_id.strip()):
        return None
    try:
        idx = int(float(index_id))
    except (TypeError, ValueError):
        return None
    if idx <= 0:
        return None
    b = base.rstrip("/")
    return {
        "method": "GET",
        "thumbnails_url": f"{b}/Imaging/Document/Thumbnails?indexId={idx}&indexAction=Search",
        "details_referer": f"{b}/Guest/Search/Records/Details?IndexId={idx}",
        "index_id": idx,
    }


def document_image_url(thumbnails_json: object, *, page_number: int = 1) -> str | None:
    """Pull one page's free `Imaging/Document/Image` URL out of a parsed
    `Imaging/Document/Thumbnails` JSON response (a list of page dicts, each
    carrying a `Serialized` fabric.js blob with a `"src"` field -- see the
    module docstring). `&amp;`-escaped query separators (as the vendor itself
    sometimes emits inside the JSON string) are un-escaped. None when the page
    isn't present or carries no recognizable `src`."""
    if not isinstance(thumbnails_json, list):
        return None
    for page in thumbnails_json:
        if not isinstance(page, dict):
            continue
        try:
            if int(page.get("PageNumber") or 0) != page_number:
                continue
        except (TypeError, ValueError):
            continue
        m = _IMG_SRC_RE.search(str(page.get("Serialized") or ""))
        if m:
            return m.group(1).replace("&amp;", "&")
    return None


async def fetch_document_image(c, base: str, index_id: object, *,
                                page_number: int = 1) -> tuple[bytes, str] | None:
    """Fetch one page's free scanned-document PNG for `index_id` through an
    ALREADY-OPEN client `c` that has visited `{base}/guest/Search/records` at
    least once this session (the anonymous session cookie `fetch_document_image`
    relies on -- see module docstring). Best-effort: None on any failure,
    including a non-image response (e.g. the login-route redirect a wrong/
    missing Referer produces, which `client()`'s default `follow_redirects`
    would otherwise silently turn into a 200 HTML page)."""
    recipe = image_fetch_recipe(base, index_id)
    if not recipe:
        return None
    try:
        # The Thumbnails endpoint ALSO gates on Referer (not just Image) --
        # live-caught 2026-10-14: an otherwise-identical request without it
        # IIS-401s ("Access is denied due to invalid credentials") even with
        # valid session cookies. Both requests need it, matching Referer only.
        r = await c.get(recipe["thumbnails_url"],
                        headers={"X-Requested-With": "XMLHttpRequest",
                                 "Referer": recipe["details_referer"]})
        if r.status_code != 200:
            return None
        pages = r.json()
    except Exception:  # noqa: BLE001 - best-effort, a county going down never breaks a run
        return None
    url = document_image_url(pages, page_number=page_number)
    if not url:
        return None
    try:
        r2 = await c.get(url, headers={"Referer": recipe["details_referer"]})
    except Exception:  # noqa: BLE001
        return None
    ct = (r2.headers.get("content-type") or "").split(";")[0].strip().lower()
    if r2.status_code != 200 or not r2.content or not ct.startswith("image/"):
        return None
    return r2.content, ct


# DataTables column order the endpoint requires (3 render-only cols + fields).
_COLS = ["", "", "", "ScanPages", "RecordingDate", "Type",
         "PartyOne", "PartyTwo", "Property", "FileNumber", "BookPage"]
_DATE_RE = re.compile(r"/Date\((\d+)")


def _clean(v) -> str:
    """RecordRoom returns HTML-formatted cells (<div>, <br/>); strip to text."""
    import html as _html
    s = re.sub(r"<[^>]+>", " ", str(v or ""))
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def is_distress(doc_type: str | None) -> bool:
    s = _clean(doc_type).upper()
    return any(k in s for k in _DISTRESS) and not any(k in s for k in _RESOLVED)


def _parse_date(v) -> datetime | None:
    if not v:
        return None
    m = _DATE_RE.search(str(v))
    if m:
        try:
            return datetime.utcfromtimestamp(int(m.group(1)) / 1000)
        except (ValueError, OverflowError):
            return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v)[:10], fmt)
        except ValueError:
            continue
    return None


def _columns() -> list[dict]:
    return [{"data": d, "name": "", "searchable": True, "orderable": True,
             "search": {"value": "", "regex": False}} for d in _COLS]


async def discover_recent_nods(state: str, county: str, days_back: int = 45,
                               max_docs: int = 600) -> list[RodDoc]:
    slug = COTT_RR_COUNTIES.get((state, county))
    if not slug:
        return []
    today = datetime.utcnow()
    frm = today - timedelta(days=max(1, days_back))
    fmt = lambda d: f"{d.month}/{d.day}/{d.year}"  # noqa: E731
    base = f"{COTT_RR_HOST}/{slug}"
    out: list[RodDoc] = []
    seen: set[str] = set()
    try:
        async with client(timeout=60.0) as c:
            await c.get(f"{base}/guest/Search/records")
            await c.post(f"{base}/search/Records",
                         data={"FromDate": fmt(frm), "ThruDate": fmt(today), "Type": "", "Page": "1"},
                         headers={"X-Requested-With": "XMLHttpRequest"})
            for start in range(0, max_docs, 100):
                payload = {"draw": 1, "columns": _columns(),
                           "order": [{"column": 4, "dir": "asc"}],
                           "start": start, "length": 100,
                           "search": {"value": "", "regex": False}, "Filters": []}
                r = await c.post(f"{base}/Search/Records/Result/", json=payload,
                                 headers={"X-Requested-With": "XMLHttpRequest"})
                if r.status_code != 200:
                    break
                try:
                    rows = (r.json() or {}).get("data") or []
                except Exception:
                    break
                if not rows:
                    break
                for row in rows:
                    if not is_distress(row.get("Type")):
                        continue
                    inst = _clean(row.get("FileNumber"))
                    bp = _clean(row.get("BookPage"))
                    bm = re.findall(r"\d+", bp)
                    key = inst or bp
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    prop_html = row.get("Property") or ""
                    party2_html = row.get("PartyTwo") or ""
                    # Remarks (legal description) when the structured field parses;
                    # fall back to the old whole-cell soup so a markup change never
                    # drops the text outright, just loses its structure.
                    remarks = _extract_remarks(prop_html) or (_clean(prop_html) or None)
                    grantee_addr = _extract_block_address(party2_html)
                    raw_block: dict = {"type": _clean(row.get("Type"))}
                    # IndexId/HasFiledImage/ScanPages ride along on every grid row
                    # (the backend returns them whether or not _COLS asked for them
                    # by name -- live-verified 2026-10-14) and are what unlocks the
                    # free per-page scanned image (see module docstring +
                    # image_fetch_recipe). Previously captured nowhere at all on
                    # this adapter, unlike the sibling rod/sc_recordroom.py (name
                    # search), which already kept IndexId as raw['index_id'] but
                    # never used it for an image fetch either.
                    index_id = row.get("IndexId")
                    if index_id is not None:
                        raw_block["index_id"] = index_id
                    raw_block["has_filed_image"] = bool(row.get("HasFiledImage"))
                    if row.get("ScanPages") is not None:
                        raw_block["scan_pages"] = row.get("ScanPages")
                    if row.get("HasFiledImage"):
                        recipe = image_fetch_recipe(base, index_id)
                        if recipe:
                            raw_block["image_fetch"] = recipe
                    if grantee_addr:
                        # The grantee's (PartyTwo's) OWN mailing address -- for a
                        # probate deed of distribution this is the heir's address,
                        # which can differ from the inherited property's situs
                        # (a real absentee-heir signal). Deliberately kept here as
                        # provenance only, NOT bridged into raw['owner_mailing'] --
                        # for a lien/judgment row PartyTwo is the CREDITOR, not the
                        # owner, and this adapter cannot tell which kind of row it
                        # is from the address block alone. Same "flag, don't wire"
                        # call as batch 12's spartan_weekly_legals petitioner block.
                        raw_block["grantee_address"] = grantee_addr
                    amount = _extract_amount(prop_html)
                    if amount is not None:
                        raw_block["consideration_amount"] = amount
                    out.append(RodDoc(
                        county=county, state=state,
                        doc_type=_clean(row.get("Type")),
                        recorded_date=_parse_date(row.get("RecordingDate")),
                        book=bm[0] if bm else None, page=bm[1] if len(bm) > 1 else None,
                        grantor=_clean(row.get("PartyOne")) or None,
                        grantee=_clean(row.get("PartyTwo")) or None,
                        instrument_no=inst or None,
                        parcel_id=_extract_parcel(prop_html),
                        property_address=_extract_block_address(prop_html),
                        consideration_amount=amount,
                        notes=remarks,
                        raw={"cott_recordroom": raw_block},
                    ))
                if len(rows) < 100:
                    break
    except Exception:
        log.warning("cott_rr.discover_failed", state=state, county=county)
        return []
    log.info("cott_rr.discovered", county=county, distress=len(out))
    return out[:max_docs]
