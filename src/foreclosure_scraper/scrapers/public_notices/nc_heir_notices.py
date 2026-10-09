"""NC quiet-title and heir-naming court notices, statewide, from the Column legal-notice API.

WHY THIS EXISTS (top-80 build list 2026-10-09, items 2 and 3: heir_naming_publication and
quiet_title, 20 NC cells each). The SC half of this signal is parsed by
scrapers/newspapers/column_legal_notices.py (_parse_sc_quiet_title: a tax-deed holder's
quiet-tax-title suit that serves the decedent's heirs by publication). Nothing read the NC half,
although the same open endpoint carries it: Column (enotice-production) is the publishing back end
of most NC papers of record and answers a bare JSON POST with the full notice text (no key, no
login, no CAPTCHA; the endpoint column_legal_notices already reads). Three NC shapes, all of which
name a decedent's heirs in a court notice, read live 2026-10-09:

  quiet_title            a Special Proceeding to quiet title: "NOTICE TO UNKNOWN HEIRS AND
                         UNLOCATEABLE HEIRS OF <decedent> ... Quiet Title Action under <county>
                         File No: 25SP000393-500 regarding ... Parcel Identification Number ...
                         The hearing will be held on <date>".
  tax_foreclosure_heirs  a county tax foreclosure (G.S. 105-375(c)(4)b) that serves "HEIRS OF
                         <decedent> (DECEASED: <date>), ..." by publication, with the parcel
                         number and a property description. The county is the plaintiff.
  unknown_heirs_notice   any other notice that names "unknown heirs" / "heirs at law of <decedent>"
                         with a decedent's name (partition, declaratory action, probate matter).

A notice that merely says "quiet title" against living defendants (a lender's declaratory
action) is counted as a quiet-title notice, but names no decedent, parcel or address and so
carries no lead: it is not emitted (is_quiet_title still counts for the cube when a row holds it).

WHAT IT EMITS. One PROBATE_NOTICE row per distinct notice (republications of one case collapse):
owner_name and defendant = the first named decedent (drives the same owner-to-GIS backfill the SC
and NC estate rows use), county from the notice body, parcel id and case number when printed,
plaintiff for a county tax foreclosure, and raw.heir_naming_publication with the keys the SC
parser writes ({is_quiet_title, plaintiff, case_number, county, parcel_id, decedents[],
named_heirs[]}) plus kind, hearing_date and statute. enrichment_heir_candidates already reads
raw.heir_naming_publication.named_heirs.

COVERAGE (the screen ledger entry in screen_ledger.py reads COLUMN_NC_COUNTIES): Column tags a
notice by the newspaper's county. Measured 2026-10-09 with one request per NC county over 365 days:
75 of 100 counties carry at least one Column notice; 25 carry none (Alleghany, Ashe, Camden,
Currituck, Edgecombe, Graham, Greene, Harnett, Hoke, Hyde, Jackson, Jones, Macon, Orange, Swain,
Surry, Tyrrell, Yancey, Person, Pender, Carteret, Northampton, Brunswick, Lincoln, Mitchell).
For those 25 the only other statewide aggregator is ncnotices.com, whose notice bodies are
CAPTCHA-walled (walls_register.json card nc_notice_body): they are a verdict, not a gap.

Polite: the shared http_client per-host throttle; a handful of POSTs per run.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...validation import NC_COUNTIES

log = structlog.get_logger()

API_URL = ("https://us-central1-enotice-production.cloudfunctions.net"
           "/api/search/public-notices")
WINDOW_DAYS = 180
PAGE_SIZE = 200
#: free-text queries (the endpoint matches the notice body); each is one POST per window slice
QUERIES = ("quiet title", "unknown heirs", "unlocatable heirs", "heirs at law", "heirs of")
MAX_SPLIT_DEPTH = 3

#: NC counties with at least one Column notice in the 365 days before 2026-10-09 (one count
#: request per county, see the module doc). The screen ledger credits a completed run with these.
COLUMN_NC_COUNTIES = (
    "Alamance", "Alexander", "Anson", "Avery", "Beaufort", "Bertie", "Bladen", "Buncombe", "Burke",
    "Cabarrus", "Caldwell", "Caswell", "Catawba", "Chatham", "Cherokee", "Chowan", "Clay",
    "Cleveland", "Columbus", "Craven", "Cumberland", "Dare", "Davidson", "Davie", "Duplin",
    "Durham", "Forsyth", "Franklin", "Gaston", "Gates", "Granville", "Guilford", "Halifax",
    "Haywood", "Henderson", "Hertford", "Iredell", "Johnston", "Lee", "Lenoir", "Madison",
    "Martin", "McDowell", "Mecklenburg", "Montgomery", "Moore", "Nash", "New Hanover", "Onslow",
    "Pamlico", "Pasquotank", "Perquimans", "Pitt", "Polk", "Randolph", "Richmond", "Robeson",
    "Rockingham", "Rowan", "Rutherford", "Sampson", "Scotland", "Stanly", "Stokes",
    "Transylvania", "Union", "Vance", "Wake", "Warren", "Washington", "Watauga", "Wayne",
    "Wilkes", "Wilson", "Yadkin",
)

_WS = re.compile(r"\s+")
_QT = re.compile(r"quiet\s+(?:tax\s+)?title", re.I)
_UNKNOWN_HEIRS = re.compile(r"unknown\s+(?:and\s+)?(?:un-?locat\w*\s+)?heirs|un-?locat\w*\s+heirs|"
                            r"heirs[- ]at[- ]law", re.I)
_STATUTE = re.compile(r"G\.?\s?S\.?\s*(105-375|105-374|41-10|1-?39|1-?74)", re.I)

_TOK = r"[A-Z][A-Za-z.'\-]*\.?"
#: "Heirs of Francis Green AKA Francis Bean, deceased", "HEIRS OF ROY MAYNOR (DECEASED: ...",
#: "unknown heirs of John Q. Public". Only the label is case-insensitive: the name must be capitalised.
_HEIRS_OF = re.compile(
    rf"(?i:heirs?(?:[- ]at[- ]law)?\s+of\s+(?:the\s+(?:estate\s+of\s+)?)?)({_TOK}(?:\s+{_TOK}){{0,4}}?)"
    r"(?<!\s[A-Z])(?=\s*(?:\(|,|;|\.|:|\bA\s*/?\s*K\s*/?\s*A\b|\bAKA\b|(?i:deceased)|(?i:and)\b|(?i:late of)|(?i:if)\b)|\s*$)")
#: a "NAME (DECEASED: 07/13/2023)" entry of a G.S. 105-375 tax-foreclosure caption
_DECEASED_ENTRY = re.compile(
    rf"(?:^|[,;]|\band\b|\bAND\b)\s*((?:HEIRS\s+OF\s+)?{_TOK}(?:\s+{_TOK}){{1,4}}?)\s*\(\s*DECEASED\s*:?\s*"
    r"(\d{1,2}/\d{1,2}/\d{2,4})?\s*\)")
_NOTICE_GIVEN_TO = re.compile(r"notice\s+is\s+hereby\s+given\s+to\s*:", re.I)
_REGION_END = re.compile(r"if\s+they\s+be\s+deceased|that\s+a\s+judgment|property\s+description", re.I)
_CASE = re.compile(r"\b(\d{2})\s?(SP|CVD|CVS|CV|E)\s?(\d{4,7})(?:\s?-\s?(\d{3}))?\b", re.I)
_PARCEL = re.compile(
    r"(?:parcel\s+(?:identification\s+)?(?:number|no\.?|#|id)|\bPIN|\bPID|\bparcel)\s*[:#]?\s*"
    r"([0-9][0-9A-Za-z.\-]{5,24})", re.I)
_PLAINTIFF_COUNTY = re.compile(r"\b(COUNTY\s+OF\s+[A-Z][A-Za-z ]{2,20}?)\s*,\s*a\s+political\s+sub", re.I)
_HEARING = re.compile(r"hearing\s+(?:will\s+be\s+held\s+)?on\s+([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})", re.I)
_NAME_BLOCK = re.compile(
    r"\b(Bank|Corp|Inc|LLC|LLP|Trust|Association|Company|Servicing|Mortgage|County|Department|"
    r"United\s+States|Unknown|Estate|Heirs|Devisees|Deceased|Successors|Assigns|Court|Clerk|"
    r"Notice|Plaintiff|Defendants?|Petitioner|Attorney|the|to|and|of)\b", re.I)
_TAX_FC = re.compile(r"ad\s+valorem|delinquent\s+(?:property\s+)?tax|tax\s+lien|105-3(?:6|7)\d|tax\s+foreclos|"
                     r"in\s+rem", re.I)

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)}


def norm(text: Any) -> str:
    return _WS.sub(" ", str(text or "").replace("\xa0", " ")).strip()


def _name(s: str) -> Optional[str]:
    s = re.sub(r"^(?:heirs?\s+of\s+)", "", norm(s).strip(" ,.;:()"), flags=re.I)
    if not s or len(s) > 60 or _NAME_BLOCK.search(s):
        return None
    toks = s.split()
    if not 2 <= len(toks) <= 5:
        return None
    return s


def _drop_prefix_names(names: list[str]) -> list[str]:
    """'Dottie L' beside 'Dottie L. Vain': a name that is only the start of another listed name
    is an OCR/regex fragment."""
    low = [n.lower() for n in names]
    return [n for i, n in enumerate(names)
            if not any(j != i and low[j].startswith(low[i]) and len(low[j]) > len(low[i]) for j in range(len(low)))]


def _iso_date(s: str) -> Optional[str]:
    s = norm(s).replace(",", "")
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})$", s)
    if m and m.group(1).lower() in _MONTHS:
        return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", s)
    if m:
        y = int(m.group(3))
        y += 2000 if y < 100 else 0
        return f"{y:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def county_of(text: str, hint: Optional[str] = None) -> Optional[str]:
    """The NC county the notice is about: the most-named county in its first 600 characters
    (caption: 'COUNTY OF ROBESON', 'Johnston County'), else Column's own tag when valid."""
    head = norm(text)[:600]
    best, hits = None, 0
    for c in NC_COUNTIES:
        n = len(re.findall(rf"\b{re.escape(c)}\b", head, re.I))
        if n > hits:
            best, hits = c, n
    if best:
        return best
    return hint if hint in NC_COUNTIES else None


def parse_nc_heir_notice(text: Any, county_hint: Optional[str] = None) -> Optional[dict]:
    """The heir-naming facts of one NC notice body, or None when the notice is neither a
    quiet-title notice nor names a decedent's heirs. Conservative: never emits a guessed name."""
    t = norm(text)
    if not t:
        return None
    is_qt = bool(_QT.search(t))
    decedents: list[str] = []
    died: list[str] = []
    # (1) G.S. 105-375 tax foreclosure caption: 'notice is hereby given to: HEIRS OF A (DECEASED: d), B (DECEASED: d)'
    kind = None
    m = _NOTICE_GIVEN_TO.search(t)
    if m:
        region = t[m.end(): m.end() + 900]
        end = _REGION_END.search(region)
        region = region[: end.start()] if end else region
        for em in _DECEASED_ENTRY.finditer(region):
            nm = _name(em.group(1))
            if nm and nm.lower() not in [d.lower() for d in decedents]:
                decedents.append(nm)
                iso = _iso_date(em.group(2) or "")
                if iso:
                    died.append(iso)
        if decedents and _STATUTE.search(t):
            kind = "tax_foreclosure_heirs"
    # (2) 'heirs of <decedent>' anywhere
    if not decedents:
        for hm in _HEIRS_OF.finditer(t):
            nm = _name(hm.group(1))
            if nm and nm.lower() not in [d.lower() for d in decedents]:
                decedents.append(nm)
    has_unknown = bool(_UNKNOWN_HEIRS.search(t))
    if not is_qt and not decedents:
        return None
    if kind is None:
        if is_qt:
            kind = "quiet_title"
        elif decedents and _TAX_FC.search(t):
            kind = "tax_foreclosure_heirs"
        else:
            kind = "unknown_heirs_notice"
    decedents = _drop_prefix_names(decedents)
    out: dict[str, Any] = {"is_quiet_title": is_qt, "kind": kind, "source": "column_nc"}
    cm = _CASE.search(t)
    if cm:
        out["case_number"] = (f"{cm.group(1)}{cm.group(2).upper()}{cm.group(3)}"
                              + (f"-{cm.group(4)}" if cm.group(4) else ""))
    cty = county_of(t, county_hint)
    if cty:
        out["county"] = cty
    pm = _PARCEL.search(t)
    if pm:
        out["parcel_id"] = pm.group(1).strip(".-")
    pl = _PLAINTIFF_COUNTY.search(t)
    if pl:
        out["plaintiff"] = pl.group(1).title().replace("County Of", "County of")
    if decedents:
        out["decedents"] = decedents
    if died:
        out["died"] = died
    hd = _HEARING.search(t)
    if hd and _iso_date(hd.group(1)):
        out["hearing_date"] = _iso_date(hd.group(1))
    sm = _STATUTE.search(t)
    if sm:
        out["statute"] = f"G.S. {sm.group(1)}"
    out["unknown_heirs"] = has_unknown
    return out


def emits_lead(parsed: Optional[dict]) -> bool:
    """A notice is a lead only when it names a decedent (the owner to look up) or a parcel."""
    return bool(parsed and (parsed.get("decedents") or parsed.get("parcel_id")))


def dedupe_key(parsed: dict) -> str:
    """Republications of one case collapse: case number, else county + parcel, else the decedent."""
    if parsed.get("case_number"):
        return f"case:{parsed['case_number']}:{parsed.get('county')}"
    if parsed.get("parcel_id"):
        return f"parcel:{parsed.get('county')}:{parsed['parcel_id']}"
    return f"dec:{parsed.get('county')}:{(parsed.get('decedents') or ['?'])[0].lower()}"


# ----------------------------------------------------------------------------------------------
# fetch
# ----------------------------------------------------------------------------------------------

async def _query(c, search: str, from_ms: int, to_ms: int, depth: int = 0) -> list[dict]:
    """All items of one (query, window): the window is halved while the server says it holds
    more than one page (the same rule column_legal_notices._query applies)."""
    body = {
        "search": search,
        "allFilters": [{"state": "North Carolina"}, {"publishedtimestamp": {"from": from_ms, "to": to_ms}}],
        "noneFilters": [], "sort": [{"publishedtimestamp": "desc"}], "pageSize": PAGE_SIZE, "isDemo": False,
    }
    try:
        r = await c.post(API_URL, json=body,
                         headers={"Content-Type": "application/json", "Accept": "application/json"})
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_heir_notices.post_fail", query=search, error=str(exc)[:160])
        return []
    if r.status_code != 200:
        r.raise_for_status()
        return []
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return []
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    total = ((data.get("page") or {}).get("total_results")) if isinstance(data, dict) else None
    if isinstance(total, int) and total > len(results) >= PAGE_SIZE and depth < MAX_SPLIT_DEPTH:
        mid = from_ms + (to_ms - from_ms) // 2
        return (await _query(c, search, mid + 1, to_ms, depth + 1)
                + await _query(c, search, from_ms, mid, depth + 1))
    return results


class NcHeirNotices(BaseScraper):
    slug = "public_notices.nc_heir_notices"
    name = "NC quiet-title and heir-naming court notices (Column legal-notice API, statewide)"
    category = "newspaper_legal"
    requires_apify = False
    expected_min_count = 0
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        now_ms = int(time.time() * 1000)
        from_ms = now_ms - WINDOW_DAYS * 24 * 3600 * 1000
        out = self.partial
        items: dict[str, dict] = {}
        async with client(timeout=60.0) as c:
            for q in QUERIES:
                for it in await _query(c, q, from_ms, now_ms):
                    if it.get("id") is not None:
                        items.setdefault(str(it["id"]), it)
        seen: set[str] = set()
        for it in sorted(items.values(), key=lambda x: -(x.get("publishedtimestamp") or 0)):
            li = self.listing_for(it)
            if li is None:
                continue
            k = dedupe_key(li.raw["heir_naming_publication"])
            if k in seen:
                continue
            seen.add(k)
            out.append(li)
        log.info("nc_heir_notices.done", notices=len(items), leads=len(out))
        return out

    def listing_for(self, it: dict) -> Optional[Listing]:
        text = it.get("text") or ""
        parsed = parse_nc_heir_notice(text, it.get("county"))
        if not emits_lead(parsed) or not parsed.get("county"):
            return None
        decs = parsed.get("decedents") or []
        owner = decs[0].title() if decs and decs[0].isupper() else (decs[0] if decs else None)
        ts = it.get("publishedtimestamp")
        try:
            published = datetime.utcfromtimestamp(int(ts) / 1000.0)
        except Exception:  # noqa: BLE001
            published = datetime.utcnow()
        full = norm(text)
        raw: dict[str, Any] = {
            "heir_naming_publication": parsed,
            "column": {"id": it.get("id"), "newspapername": it.get("newspapername"),
                       "noticetype": it.get("noticetype"), "publishedtimestamp": ts,
                       "pdfurl": it.get("pdfurl"), "text": full[:4000], "text_len": len(full)},
        }
        pdf = it.get("pdfurl")
        if isinstance(pdf, str) and pdf.startswith("http"):
            raw["documents"] = [pdf]
        return Listing(
            source=self.slug,
            source_url=pdf if isinstance(pdf, str) and pdf.startswith("http") else f"{API_URL}#{it.get('id') or ''}",
            listing_type=ListingType.PROBATE_NOTICE,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county=parsed["county"],
            parcel_id=parsed.get("parcel_id"),
            plaintiff=parsed.get("plaintiff"),
            owner_name=owner,
            defendant=owner,
            case_number=parsed.get("case_number"),
            description=full[:500],
            first_seen=published,
            last_seen=datetime.utcnow(),
            raw=raw,
        )
