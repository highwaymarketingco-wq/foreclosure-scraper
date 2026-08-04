"""Free, robots-CLEAN recorded-document IMAGE adapters — the only legal way to
reach a recorded Deed-of-Trust's ORIGINAL PRINCIPAL.

Why this module exists
----------------------
The Register-of-Deeds *index* (every adapter in this package) tells us a lead
HAS a mortgage but carries NO dollar figure — the principal is printed only
inside the recorded instrument image. Without it the equity engine has no
payoff basis and every downstream max-bid is soft.

Compliance is the whole story here, so it is enforced in ONE place: every
county in the registry below is gated on a live robots.txt evaluation before a
single byte is requested (`ensure_allowed`). There is deliberately **no env
switch to skip the robots check** — a walled county is a wall, not a flag.

Vendor landscape, live-verified 2026-08-03/04 (see COUNTY_IMAGE_STATUS)
----------------------------------------------------------------------
* i3 Verticals / Logan "The Lookup" (`*deeds.com`) — serves free
  `view_image.php?key=<hex>&type=pdf` PDFs with no cart and no login. BUT
  Spartanburg, Laurens, McDowell and Mitchell all publish::

      # Only allow the front page to be indexed.
      User-agent: *
      Allow: /$
      Disallow: /

  which is the SAME machine-readable no-automation directive rod/kofile.py
  already treats as a wall. Only **Transylvania** serves no robots.txt at all,
  so it is the one Logan tenant this module may touch.
* Courthouse Computer Systems (CCHS) — `GenerateSingleImageForPrint.asp`
  returns `image/tiff` free, no cart/login. The us5 install (Burke, Cleveland)
  publishes no robots.txt; the us4 install (Lincoln, Madison, Henderson) sends
  `Disallow: /` + `Disallow: /ProcessedImages/` -> walled.
* Cott/Aumentum (Buncombe, Gaston, Mecklenburg) — the image viewer runs the
  vendor shopping-cart flow ("Please confirm your purchase", "will print and
  charge"). PAYWALLED, not built.
* Harris AcclaimWeb (Pickens) — index is free and already scraped, but the
  image route is not reachable browserless and the app exposes live
  `/Cart` + `/ShoppingCart` controllers (HTTP 500 with params = present, 404
  for routes that do not exist). NOT confirmed free -> not built.
* Cott RecordRoom (Union) — `Disallow: /` + `Disallow: *.pdf` -> walled.
* Kofile (Oconee) — `Disallow: /` -> walled (already handled in rod/kofile.py).

Everything here is best-effort and returns [] on any failure, so a county going
down never breaks a run.
"""
from __future__ import annotations

import asyncio
import io
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse

import structlog

from ..http_client import client
from .cchs import CCHS_COUNTIES, _UA, _base, _field
from .models import RodDoc

log = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# County registry + the plain-English access verdict for every county we looked #
# at. `DOC_IMAGE_COUNTIES` is the ONLY thing the enricher iterates.             #
# --------------------------------------------------------------------------- #
#: (state, county) -> vendor key handled below. Entries here are (a) verified to
#: serve the document image free (no cart, no login, no payment) AND (b) verified
#: robots-clean. Adding a county requires BOTH.
DOC_IMAGE_COUNTIES: dict[tuple[str, str], str] = {
    ("NC", "Transylvania"): "logan",
    ("NC", "Burke"): "cchs",
    ("NC", "Cleveland"): "cchs",
}

#: Audit trail: every county whose recorder we probed, and why it is in or out.
#: Values are (verdict, evidence). Verdict is one of "free" / "paywalled" /
#: "login_walled" / "robots_disallow" / "unreachable" / "unconfirmed". Anything
#: other than "free" MUST stay out of DOC_IMAGE_COUNTIES (asserted in tests).
COUNTY_IMAGE_STATUS: dict[tuple[str, str], tuple[str, str]] = {
    ("NC", "Transylvania"): ("free", "Logan view_image.php?key=&type=pdf -> 200 application/pdf, no robots.txt"),
    ("NC", "Burke"): ("free", "CCHS us5 GenerateSingleImageForPrint.asp -> 200 image/tiff, no robots.txt"),
    ("NC", "Cleveland"): ("free", "CCHS us5, same host/app family as Burke, no robots.txt"),
    ("SC", "Spartanburg"): ("robots_disallow", "search.spartanburgdeeds.com robots.txt: Allow /$ + Disallow: /"),
    ("SC", "Laurens"): ("robots_disallow", "search.laurensdeeds.com robots.txt: Allow /$ + Disallow: /"),
    ("NC", "McDowell"): ("robots_disallow", "search.mcdowelldeeds.com robots.txt: Allow /$ + Disallow: /"),
    ("NC", "Mitchell"): ("robots_disallow", "search.mitchelldeeds.com robots.txt: Allow /$ + Disallow: /"),
    ("NC", "Lincoln"): ("robots_disallow", "us4.courthousecomputersystems.com: Disallow: / + /ProcessedImages/"),
    ("NC", "Madison"): ("robots_disallow", "us4.courthousecomputersystems.com: Disallow: / + /ProcessedImages/"),
    ("NC", "Henderson"): ("robots_disallow", "us4.courthousecomputersystems.com: Disallow: / + /ProcessedImages/"),
    ("SC", "Union"): ("robots_disallow", "recordroom.cottsystems.com: Disallow: / + Disallow: *.pdf"),
    ("SC", "Oconee"): ("robots_disallow", "oconee.sc.publicsearch.us: Disallow: / (see rod/kofile.py)"),
    ("NC", "Buncombe"): ("paywalled", "Aumentum HTML5Viewer: 'Please confirm your purchase' / 'will print and charge'"),
    ("NC", "Mecklenburg"): ("paywalled", "meckrod.manatron.com robots Disallow: / AND Aumentum cart flow"),
    ("NC", "Gaston"): ("unreachable", "deeds.gastongov.com did not complete a TLS connection during the probe"),
    ("NC", "Polk"): ("paywalled", "cotthosting.com search page carries the vendor ShoppingCart + 'purchase'/'charge' copy"),
    ("NC", "Rutherford"): ("login_walled", "cotthosting.com/NCRUTHERFORDEXTERNAL redirects to User/Login.aspx?ReturnUrl=..."),
    ("SC", "Pickens"): ("unconfirmed", "AcclaimWeb image route not reachable browserless; live /Cart + /ShoppingCart controllers"),
}

#: Logan tenants whose document images we are allowed to touch. Deliberately NOT
#: `logan.LOGAN_COUNTIES` — that map includes robots-disallowed hosts.
LOGAN_IMAGE_HOSTS: dict[tuple[str, str], str] = {
    ("NC", "Transylvania"): "https://search.transylvaniadeeds.com",
}

#: Logan instrument codes that denote the note securing a debt. NOTE: `TR/D` is
#: deliberately absent — on both Logan and CCHS it is the TRUSTEE'S DEED (the
#: post-foreclosure conveyance), whose dollar figure is the AUCTION SALE PRICE,
#: not a loan principal. Treating it as a note would feed the equity engine a
#: number that means the opposite of a payoff. (Live-caught 2026-08-03: Burke
#: bk2847/pg826 `TR/D` OCR'd to $170,640 with doc_type 'trustees_deed'.)
_LOGAN_DOT_CODES = ("D/T", "DT", "MTG", "MORT")

#: A records row is a Deed of Trust / mortgage-equivalent (the note that secures
#: the debt whose balance we amortize).
DOT_RE = re.compile(
    r"MORT|DEED OF TRUST|\bD/?T\b|\bMTG\b|SECURITY (?:DEED|AGREEMENT)", re.I)
#: Satisfactions / releases / assignments carry no principal — exclude them, and
#: with them the trustee's/foreclosure/tax deeds that carry a SALE price.
NOT_A_NOTE_RE = re.compile(
    r"SATISF|RELEASE|CANCEL|\bSAT\b|\bREL\b|ASSIGN|SUBORDINAT|MODIFICATION|"
    r"TRUSTEE|\bTR/?D\b|FORECLOS|TAX DEED|COMMISSION", re.I)

#: OCR-side backstop on the same failure mode: the county index can mislabel a
#: row, so we also reject when the DOCUMENT ITSELF reads as a conveyance rather
#: than a note.
OCR_NOT_A_NOTE_RE = re.compile(
    r"trustee|foreclos|tax[_ ]?(?:deed|sale)|warranty|quit ?claim|satisf|"
    r"release|assign", re.I)


def is_dot_type(doc_type: object) -> bool:
    s = str(doc_type or "")
    return bool(DOT_RE.search(s)) and not NOT_A_NOTE_RE.search(s)


def ocr_is_note(parsed: dict | None) -> bool:
    """True when the OCR'd document itself reads as a note (deed of trust /
    mortgage), not a conveyance. Unknown/absent doc_type passes — the index
    already filtered, this is only a backstop against a mislabeled row."""
    if not parsed:
        return False
    dt = parsed.get("doc_type")
    if not isinstance(dt, str) or not dt.strip():
        return True
    return not OCR_NOT_A_NOTE_RE.search(dt)


# --------------------------------------------------------------------------- #
# robots.txt gate — no bypass, by design                                        #
# --------------------------------------------------------------------------- #
_ROBOTS_CACHE: dict[str, str] = {}
_ROBOTS_LOCK = asyncio.Lock()


def path_disallowed(robots_body: str, path: str) -> bool:
    """Minimal `user-agent: *` robots evaluator: True when `path` is Disallowed
    and no more-specific Allow overrides it.

    Mirrors rod/kofile.py's evaluator so the project applies ONE rule. The
    vendor pattern we care about is `Allow: /$` + `Disallow: /`, where the
    anchored Allow covers only the bare root, so any real path is disallowed.
    """
    ua_star = False
    allows: list[str] = []
    disallows: list[str] = []
    for raw in (robots_body or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        value = value.strip()
        if field_name == "user-agent":
            ua_star = value == "*"
        elif ua_star and field_name == "allow" and value:
            allows.append(value)
        elif ua_star and field_name == "disallow" and value:
            disallows.append(value)

    def _match(rule: str) -> int:
        """Length of the matched prefix, or -1. Handles a trailing `$` anchor."""
        if rule.endswith("$"):
            return len(rule) - 1 if path == rule[:-1] else -1
        return len(rule) if path.startswith(rule) else -1

    best_allow = max((_match(r) for r in allows), default=-1)
    best_disallow = max((_match(r) for r in disallows), default=-1)
    return best_disallow > best_allow


async def _robots_body(origin: str) -> str:
    async with _ROBOTS_LOCK:
        if origin in _ROBOTS_CACHE:
            return _ROBOTS_CACHE[origin]
    body = ""
    try:
        async with client(timeout=15.0) as c:
            r = await c.get(f"{origin}/robots.txt", follow_redirects=True)
            # A 4xx (no robots.txt) means "no restrictions" per RFC 9309.
            if r.status_code == 200 and "text/plain" in (r.headers.get("content-type") or ""):
                body = r.text
    except Exception:  # noqa: BLE001 - unreachable robots -> treat as absent
        body = ""
    async with _ROBOTS_LOCK:
        _ROBOTS_CACHE[origin] = body
    return body


async def ensure_allowed(url: str) -> bool:
    """True when this exact URL is robots-allowed for `user-agent: *`.

    Called before EVERY document-image request. There is intentionally no env
    escape hatch: a `Disallow` is the site owner's machine-readable answer.
    """
    try:
        p = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if not p.scheme or not p.netloc:
        return False
    origin = f"{p.scheme}://{p.netloc}"
    body = await _robots_body(origin)
    if not body:
        return True
    return not path_disallowed(body, p.path or "/")


# --------------------------------------------------------------------------- #
# TIFF -> PNG (Gemini takes PDF and common image mimes, but not image/tiff)     #
# --------------------------------------------------------------------------- #
def rasterize_pdf_page1(data: bytes, resolution: int = 110) -> Optional[tuple[bytes, str]]:
    """Render page 1 of a PDF to PNG. None if it cannot be rendered.

    Gemini is the only free backend that accepts `application/pdf` directly, so
    when its keys are quota-exhausted a recorded note would be unreadable for
    the rest of the day. GitHub Models and Groq DO take images, so rasterizing
    page 1 (where "in the principal sum of $X" always sits) keeps the fallback
    chain alive instead of stalling on one provider's free tier."""
    if not data or data[:4] != b"%PDF":
        return None
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                return None
            im = pdf.pages[0].to_image(resolution=resolution)
            buf = io.BytesIO()
            im.original.convert("L").save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "image/png"
    except Exception:  # noqa: BLE001
        return None


def to_ocr_ready(data: bytes, mime: str) -> Optional[tuple[bytes, str]]:
    """Normalize a downloaded image to something the OCR providers accept.

    PDFs and jpeg/png pass through. A multi-page TIFF is converted to a PNG of
    PAGE 1 ONLY — the principal ("in the principal sum of $X") is always on the
    first page of a recorded note, and one page keeps the vision payload small.
    Returns None when the bytes are unusable.
    """
    if not data:
        return None
    if data[:4] == b"%PDF" or mime == "application/pdf":
        return data, "application/pdf"
    if mime in ("image/jpeg", "image/png", "image/webp"):
        return data, mime
    if mime in ("image/tiff", "image/tif") or data[:4] in (b"II*\x00", b"MM\x00*"):
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:
                im.seek(0)
                buf = io.BytesIO()
                im.convert("L").save(buf, format="PNG", optimize=True)
                return buf.getvalue(), "image/png"
        except Exception:  # noqa: BLE001
            return None
    return None


# --------------------------------------------------------------------------- #
# Name matching                                                                 #
# --------------------------------------------------------------------------- #
def name_parts(owner: str) -> tuple[str, str]:
    """('SMITH, JOHN A') -> ('SMITH', 'JOHN'); ('JOHN SMITH') -> ('JOHN','SMITH').

    Surname-first heuristic, identical to the other ROD enrichers.
    """
    o = re.sub(r"[^A-Za-z, ]", " ", owner or "").upper()
    o = re.sub(r"\s+", " ", o).strip()
    if not o:
        return "", ""
    if "," in o:
        a, b = o.split(",", 1)
        return a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    toks = o.split(" ")
    return toks[0], (toks[1] if len(toks) > 1 else "")


def owner_matches(doc: RodDoc, last: str, first: str) -> bool:
    blob = f"{doc.grantor or ''} {doc.grantee or ''}".upper()
    return bool(last) and last in blob and (not first or first in blob)


def rank_dot_docs(docs: list[RodDoc], last: str, first: str) -> list[RodDoc]:
    """Deed-of-Trust candidates, NEWEST note first (the newest note is the best
    payoff basis). Owner-matched rows preferred; falls back to all DOT rows when
    the party columns are blank/ambiguous."""
    dots = [d for d in docs if is_dot_type(d.doc_type)]
    if not dots:
        return []
    mine = [d for d in dots if owner_matches(d, last, first)] or dots
    return sorted(mine, key=lambda d: d.recorded_date or datetime.min, reverse=True)


# --------------------------------------------------------------------------- #
# Vendor: CCHS (Burke, Cleveland) — per-lead name search + free TIFF            #
# --------------------------------------------------------------------------- #
async def _cchs_owner_dots(state: str, county: str, owner: str,
                           max_candidates: int) -> list[tuple[bytes, str, RodDoc]]:
    cfg = CCHS_COUNTIES.get((state, county))
    if not cfg:
        return []
    host, app, root = cfg
    base = _base(host, app)
    if not await ensure_allowed(f"{base}/GenerateSingleImageForPrint.asp"):
        log.info("doc_images.robots_walled", county=county, vendor="cchs")
        return []
    last, first = name_parts(owner)
    if not last:
        return []
    xhr = {**_UA, "X-Requested-With": "XMLHttpRequest",
           "Referer": f"{base}/realestatesearch.asp"}
    out: list[tuple[bytes, str, RodDoc]] = []
    try:
        async with client(timeout=45.0, headers=_UA) as c:
            for u in (f"https://{host}.courthousecomputersystems.com/{root}/",
                      f"{base}/application.asp?resize=true",
                      f"{base}/realestatesearch.asp"):
                await c.get(u, follow_redirects=True)
            q = {"cmd": "search", "last": last, "given": first, "searchtype": 1,
                 "indextype": 1, "codetype": 0, "fromdate": "", "todate": "",
                 "instrumenttypes": "", "resultstype": 1, "maxrecordcount": 200,
                 "sortorder": 1, "sortfield": "docno", "rangetype": "name"}
            r = await c.get(f"{base}/SearchService.asp?{urlencode(q)}", headers=xhr)
            m = re.search(r"<recordcount>(\d+)</recordcount>", r.text, re.I)
            count = int(m.group(1)) if m else 0
            if count <= 0:
                return []
            r2 = await c.get(
                f"{base}/SearchService.asp?cmd=getall&start=0&offset={min(count, 200)}",
                headers=xhr)
            recs = re.findall(r"<r>(.*?)</r>", r2.text or "", re.S)
            docs: list[RodDoc] = []
            for rec in recs:
                ki = _field(rec, "ki")
                if not is_dot_type(ki):
                    continue
                # <im>I</im> == a scanned image exists for this instrument.
                if (_field(rec, "im") or "").upper() != "I":
                    continue
                try:
                    rd = datetime.strptime(_field(rec, "da"), "%m/%d/%Y")
                except (ValueError, TypeError):
                    rd = None
                docs.append(RodDoc(
                    county=county, state=state, doc_type=ki, recorded_date=rd,
                    book=_field(rec, "bk") or None, page=_field(rec, "pg") or None,
                    instrument_no=_field(rec, "dn") or None,
                    grantor=(f"{_field(rec, 'or')} {_field(rec, 'or1')}".strip() or None),
                    grantee=(f"{_field(rec, 'ee')} {_field(rec, 'ee1')}".strip() or None),
                    raw={"cchs_seq": _field(rec, "sn"), "vendor": "cchs"},
                ))
            for doc in rank_dot_docs(docs, last, first)[:max(1, max_candidates)]:
                img_q = {
                    "pagenumber": doc.page or "", "booknumber": doc.book or "",
                    "kind": doc.doc_type or "", "booktype": "",
                    "recdate": doc.recorded_date.strftime("%m/%d/%Y") if doc.recorded_date else "",
                    "searchresultsseqnumber": doc.raw.get("cchs_seq") or "1",
                    "searchresultscount": "1", "command": "view",
                    "returnTab": "0", "tif2pdf": "True",
                }
                url = f"{base}/GenerateSingleImageForPrint.asp?{urlencode(img_q)}"
                if not await ensure_allowed(url):
                    continue
                resp = await c.get(url, headers={**_UA, "Referer": f"{base}/viewimageframe.asp"},
                                   follow_redirects=True)
                ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                ready = to_ocr_ready(resp.content, ct) if resp.status_code == 200 else None
                if ready:
                    out.append((ready[0], ready[1], doc))
    except Exception:  # noqa: BLE001 - best-effort, retry next run
        return out
    return out


# --------------------------------------------------------------------------- #
# Vendor: Logan (Transylvania) — county-wide D/T sweep, joined by owner name    #
# --------------------------------------------------------------------------- #
# Per-lead name search on the newer Logan build needs the browser pick-list, so
# instead we sweep the instrument-type date index ONCE per run (browserless, one
# request per window) and join by grantor name. One sweep serves every lead in
# the county, which is both cheaper and far less fragile than a render per lead.
_LOGAN_TOKEN_RE = re.compile(r"content\.php\?(\d+)")
_LOGAN_LINK_RE = re.compile(r'id="link_(\d+)"[^>]*>\s*(\d{2}/\d{2}/\d{4})')
_LOGAN_CELL_RE = re.compile(r'<td class="summary" id="(\d+)">(.*?)</td>', re.S)
_LOGAN_KEY_RE = re.compile(
    r'id="link_(\d+)".{0,4000}?view_image\.php\?key=([0-9a-f]+)&(?:amp;)?type=pdf', re.S)


def _clean_cell(s: str) -> str:
    return re.sub(r"\s+", " ",
                  re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ")).strip()


def _party_groups(cells: list[str]) -> list[list[str]]:
    """Split one instrument's flat `<td class="summary">` run into per-PARTY
    groups.

    Logan repeats the whole cell block once per indexed party, and the block
    width VARIES by deployment (Spartanburg emits 6 cells incl. a Reverse Party
    column, Transylvania emits 5 and omits it). The old fixed `[:6]` slice
    therefore read the NEXT party's Book-Info cell as this row's Reverse Party,
    which is how grantor/grantee ended up as the literal string "DOC 1193 195".
    Detect the stride from the second occurrence of the leading Book-Info cell.
    """
    if not cells:
        return []
    head = cells[0]
    stride = next((i for i in range(1, len(cells)) if cells[i] == head), len(cells))
    if stride < 4:
        stride = len(cells)
    return [cells[i:i + stride] for i in range(0, len(cells), stride)]


def parse_logan_dot_rows(html: str, state: str, county: str) -> list[RodDoc]:
    """Parse a Logan `searchType=it` results page into Deed-of-Trust RodDocs
    carrying the free `view_image.php` PDF key in raw['image_key'].

    Cell order per party group: [Book Info, Doc Type, Legal Desc, Party Type,
    Searched Party, (Reverse Party)]. Every party group is folded into one
    RodDoc so the surname index sees BOTH borrowers on a joint note.
    """
    keys = dict((inst, k) for inst, k in _LOGAN_KEY_RE.findall(html or ""))
    links = dict(_LOGAN_LINK_RE.findall(html or ""))
    cells: dict[str, list[str]] = {}
    for inst, val in _LOGAN_CELL_RE.findall(html or ""):
        cells.setdefault(inst, []).append(_clean_cell(val))
    out: list[RodDoc] = []
    for inst, date_s in links.items():
        groups = _party_groups(cells.get(inst, []))
        if not groups:
            continue
        book_info = groups[0][0] if groups[0] else ""
        doc_type = groups[0][1] if len(groups[0]) > 1 else ""
        legal = groups[0][2] if len(groups[0]) > 2 else ""
        if not is_dot_type(doc_type):
            continue
        grantors: list[str] = []
        grantees: list[str] = []
        for g in groups:
            party_type = (g[3] if len(g) > 3 else "").upper()
            searched = g[4] if len(g) > 4 else ""
            reverse = g[5] if len(g) > 5 else ""
            if not searched:
                continue
            if "GRANTEE" in party_type or "INDIRECT" in party_type:
                grantees.append(searched)
                if reverse:
                    grantors.append(reverse)
            else:
                grantors.append(searched)
                if reverse:
                    grantees.append(reverse)
        try:
            rec = datetime.strptime(date_s, "%m/%d/%Y")
        except ValueError:
            rec = None
        bm = re.search(r"\d+", book_info or "")
        pm = re.search(r"\d+", (book_info or "")[bm.end():]) if bm else None
        out.append(RodDoc(
            county=county, state=state, doc_type=(doc_type or "").strip(),
            recorded_date=rec, book=(bm.group(0) if bm else None),
            page=(pm.group(0) if pm else None),
            grantor="; ".join(dict.fromkeys(grantors))[:200] or None,
            grantee="; ".join(dict.fromkeys(grantees))[:200] or None,
            instrument_no=inst, notes=(legal or None),
            raw={"image_key": keys.get(inst), "vendor": "logan",
                 "grantor_list": list(dict.fromkeys(grantors))},
        ))
    return [d for d in out if d.raw.get("image_key")]


class LoganImageSession:
    """One guest session against a robots-clean Logan tenant.

    The `view_image.php?key=` hash is scoped to the PHPSESSID that produced it —
    a fresh session gets a 0-byte body for the same key (live-verified). So the
    sweep AND every image download must share one open client, which is what
    this context manager holds.
    """

    def __init__(self, state: str, county: str):
        self.state, self.county = state, county
        self.host = LOGAN_IMAGE_HOSTS.get((state, county))
        self._cm = None
        self._c = None
        self._token: Optional[str] = None

    async def __aenter__(self) -> "LoganImageSession":
        if not self.host:
            return self
        if not await ensure_allowed(f"{self.host}/view_image.php"):
            log.info("doc_images.robots_walled", county=self.county, vendor="logan")
            self.host = None
            return self
        self._cm = client(timeout=90.0)
        self._c = await self._cm.__aenter__()
        try:
            await self._c.get(f"{self.host}/index.php")
            acc = await self._c.post(f"{self.host}/index.php", data={"Accept": "Accept"})
            m = _LOGAN_TOKEN_RE.search(acc.text or "")
            self._token = m.group(1) if m else None
        except Exception:  # noqa: BLE001
            self._token = None
        return self

    async def __aexit__(self, *exc) -> None:
        if self._cm is not None:
            try:
                await self._cm.__aexit__(*exc)
            except Exception:  # noqa: BLE001
                pass
            self._cm = self._c = None

    @property
    def live(self) -> bool:
        return bool(self.host and self._c is not None and self._token)

    async def sweep_dots(self, *, years_back: float = 6.0, window_days: int = 45,
                         max_windows: int = 60, budget_s: float = 300.0) -> list[RodDoc]:
        """Sweep the instrument-type index for Deed-of-Trust rows over
        [today - years_back, today] in `window_days` chunks.

        BOUNDED THREE WAYS (this pipeline has hung before on unbounded loops):
        `max_windows` request cap, `budget_s` wall clock, and the date floor.
        """
        if not self.live:
            return []
        codes = "&".join(f"instType[InstCodes][{c}]={c}" for c in _LOGAN_DOT_CODES)
        out: list[RodDoc] = []
        seen: set[str] = set()
        started = asyncio.get_event_loop().time()
        today = datetime.utcnow()
        earliest = today - timedelta(days=int(years_back * 365.25))
        cur, windows = today, 0
        try:
            while cur > earliest and windows < max_windows:
                if asyncio.get_event_loop().time() - started > budget_s:
                    log.info("doc_images.logan_budget_stop", county=self.county, windows=windows)
                    break
                windows += 1
                frm = max(earliest, cur - timedelta(days=window_days))
                fmt = lambda d: f"{d.month:02d}/{d.day:02d}/{d.year}"  # noqa: E731
                body = f"searchType=it&start_date={fmt(frm)}&end_date={fmt(cur)}&{codes}"
                r = await self._c.post(
                    f"{self.host}/content.php?{self._token}", content=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
                if r.status_code == 200 and "string(" not in r.text[:200]:
                    for d in parse_logan_dot_rows(r.text, self.state, self.county):
                        if d.instrument_no not in seen:
                            seen.add(d.instrument_no or "")
                            out.append(d)
                cur = frm - timedelta(days=1)
        except Exception:  # noqa: BLE001
            return out
        log.info("doc_images.logan_swept", county=self.county,
                 dot_docs=len(out), windows=windows)
        return out

    async def fetch_image(self, doc: RodDoc) -> Optional[tuple[bytes, str]]:
        """Download one swept D/T's free PDF using THIS session. None on failure."""
        key = (doc.raw or {}).get("image_key")
        if not self.live or not key:
            return None
        url = f"{self.host}/view_image.php?key={key}&type=pdf"
        if not await ensure_allowed(url):
            return None
        try:
            r = await self._c.get(url)
        except Exception:  # noqa: BLE001
            return None
        if r.status_code != 200 or not r.content:
            return None
        ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        return to_ocr_ready(r.content, ct)


# --------------------------------------------------------------------------- #
# Public façade                                                                 #
# --------------------------------------------------------------------------- #
async def owner_dot_documents(state: str, county: str, owner: str, *,
                              max_candidates: int = 3,
                              logan_index: Optional[dict] = None,
                              logan_session: Optional[LoganImageSession] = None
                              ) -> list[tuple[bytes, str, RodDoc]]:
    """Best-effort (bytes, mime, RodDoc) for this owner's Deed-of-Trust notes,
    NEWEST first. Returns [] for an unregistered/walled county.

    `logan_index` + `logan_session` are built once per county by the caller (see
    `open_logan_county`); the session must stay open because the image key is
    scoped to the session that produced it.
    """
    vendor = DOC_IMAGE_COUNTIES.get((state, county))
    if not vendor or not owner:
        return []
    if vendor == "cchs":
        return await _cchs_owner_dots(state, county, owner, max_candidates)
    if vendor == "logan":
        if not logan_index or logan_session is None or not logan_session.live:
            return []
        last, first = name_parts(owner)
        cands = rank_dot_docs(logan_index.get(last) or [], last, first)
        out: list[tuple[bytes, str, RodDoc]] = []
        for doc in cands[:max(1, max_candidates)]:
            got = await logan_session.fetch_image(doc)
            if got:
                out.append((got[0], got[1], doc))
        return out
    return []


def index_by_surname(docs: list[RodDoc]) -> dict[str, list[RodDoc]]:
    """Group swept docs by surname for the per-lead join.

    A joint note carries several parties with DIFFERENT surnames, so index every
    party separately (raw['grantor_list'] when the adapter kept it) rather than
    only the first token of a concatenated string — otherwise a co-borrower who
    is the actual board lead never matches.
    """
    idx: dict[str, list[RodDoc]] = {}
    for d in docs:
        names: list[str] = list((d.raw or {}).get("grantor_list") or [])
        for blob in (d.grantor, d.grantee):
            if blob:
                names.extend(part for part in str(blob).split(";") if part.strip())
        for nm in names:
            last, _ = name_parts(nm)
            if last and d not in idx.setdefault(last, []):
                idx[last].append(d)
    return idx
