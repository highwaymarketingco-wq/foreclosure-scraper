"""foreclosure_rod, Buncombe NC: does the Register of Deeds show the foreclosure the board claims
on THIS property, for THIS owner, and is it still going?

Evolved from docs/validation_2026-10-02/scripts/validate_lis_pendens_buncombe.py (FINDINGS.md #8:
39.4% of 33 checked rows showed "any real active lien/judgment/notice", 22% of the lis_pendens
rows; 93.9% had an unrelated same-surname person in the ROD results). That script searched a
surname, matched a first name, and called any instrument whose type held a keyword ("NOTICE",
"CLAIM", "LIEN"...) corroboration, whenever it was recorded. Live reading on 2026-10-06 showed what
that rule counts: REQUEST FOR NOTICE (a lender asking to be told of a sale) and QUIT CLAIM DEED
both matched, and the person matched was often another same-name person on another parcel. This
verifier reads the chain of instruments that belongs to the board's parcel instead.

WHAT ROD CAN AND CANNOT SAY (the domain, and why absence is never refutation).
  * In NC a lis pendens is filed with the Clerk of Superior Court (G.S. 1-116), not recorded at
    the Register of Deeds; the foreclosure case itself (a power-of-sale special proceeding "SP",
    or a civil action "CV") lives in NC eCourts, which is the human lane
    (verification_human_lane.py, scripts/verify_lead_human_assisted.py, signal `lis_pendens`).
  * ROD records the INSTRUMENTS of a power-of-sale foreclosure: the APPOINTMENT OF SUBSTITUTE
    TRUSTEE (index type "SUBSTITUTE TRUSTEE", recorded before the hearing; its Ref column holds
    the book/page of the deed of trust being foreclosed), and at the end the TRUSTEE DEED to the
    sale buyer (the borrowers are indexed as grantors beside the "<trustee>/ TR"; Ref = the same
    deed of trust), usually with a "FORECLOSURE" instrument the same day or soon after (read live:
    1410 Double Knob Loop, 16 Overlook Dr). A payoff records a DEED OF TRUST SATISFACTION whose
    Ref (or, before ~2005, a "DT <book>/<page>" description) names the deed of trust it satisfies.
  * Nothing at ROD for a property therefore says nothing about a civil lis pendens or an HOA /
    tax foreclosure, and a reinstatement (the borrower catches up, the clerk dismisses) records
    nothing at all. So "no foreclosure instrument at ROD" is `unconfirmed`, pointing to the
    human lane for the court-case check.

PROPERTY IDENTITY. The parcel comes from the county itself: the Buncombe parcel layer
(gis.buncombecounty.org property_bc_dis/MapServer/1, live, UpdateDate on every record), by the
row's PIN (tax_lien_buncombe.pin_of) or, failing that, by its house number and street. It gives
the owner of record, the vesting deed (DeedBook/DeedPage/DeedDate), the subdivision, lot, block
and plat, and the street. An ROD instrument is tied to the parcel by:
    vesting_deed     its book/page is the parcel's vesting deed (strong)
    subdivision_lot  its description names the parcel's subdivision and lot (strong)
    plat_lot         its description names the parcel's plat book/page and lot (strong)
    ref_chain        it refers (Ref column, or "DT b/p" in the description) to a tied deed of
                     trust (as strong as that deed of trust's tie)
    street           its description names the parcel's street (weak: neighbours share it)
A row with no resolvable parcel and no cited ROD instrument is `unconfirmed`
(no_property_identity) WITHOUT a name search: FINDINGS measured 93.9% same-surname collisions,
and the name -> property resolver is exactly what this verifier must not re-run.

PERSON IDENTITY (name_normalize, production's verdicts). The ROD name index is searched (surname
+ first name, "Begins With", Consolidated Real Property, newest first) for the parcel's owner of
record from the county layer and, when it names someone else, the claim's own person (defendant,
owner_name, or the cited instrument's first grantor). A result is that person's only when its
matched (bold) party has the same LAST and FIRST name (positional, owner_last_first_middle on
both sides) and name_normalize.party_middle_verdict is not "conflict" against the person's middle
initial, or against the middle initial on the parcel's vesting deed when the board name has none
(the property anchors the middle: "BURTON, RICHARD B" owns the parcel, "BURTON, RICHARD A" holds
other parcels on another road). Every decisive verdict also needs the instruments that decide it
to be tied to the parcel. Other same-surname and same-name people are only COUNTED.

VERDICTS (core.py's meanings). "The claim's earliest date" C0 is the earliest dated fact the row
carries for the claim (the case number's year for "YYSP"/"YYCV"/"YYM" cases, the cited
instrument's recording date, an eCourts order date, the sale date, first_seen); "recent" means
on or after C0 - RECENT_DAYS (two years: a substitute trustee is often appointed months before
the SP case is filed).
  confirmed    a foreclosure-initiation instrument (SUBSTITUTE TRUSTEE, LIS PENDENS, NOTICE OF
               DEFAULT / FORECLOSURE notice) tied to the parcel and recorded recently, for the
               owner (identity not in conflict), with no trustee deed or satisfaction of its deed
               of trust after it and no conveyance of the parcel since. A row whose claim IS an ROD
               instrument (counties.nod_discovery: book/page in raw.nod) is confirmed when that
               exact book/page is on the record under the named person and nothing concluded it.
  stale        the foreclosure visibly concluded: a TRUSTEE DEED tied to the parcel with the owner
               among its grantors, recorded after the owner acquired it and recently relative to
               the claim (and, when it is old enough to have reached the county layer, the layer
               agrees: the parcel's vesting deed is that trustee deed or the owner of record is no
               longer the borrower); or the deed of trust a recent substitute-trustee appointment
               refers to was satisfied after the appointment (payoff, refinance or sale), and the
               satisfaction was not rescinded.
  refuted      ONLY on positive contrary evidence, three precise cases:
               (a) cited_instrument_other_county: the row's own cited ROD instrument (raw.nod) was
                   recorded in another county's register, and the parcel's owner of record is not
                   its grantor. NC records a deed of trust and its foreclosure instruments in the
                   county where the land lies (G.S. 47-20, 45-21.17), so that foreclosure is not on
                   this Buncombe parcel.
               (b) no_open_deed_of_trust: the claim is a deed-of-trust foreclosure (a substitute
                   trustee / trustee-firm source, or a notice naming a deed of trust; NOT a civil
                   lis pendens, NOT foreclosure.com's mixed feed), the parcel's owner of record is
                   the claim's person, the owner's search is complete (every result on the page)
                   and holds the parcel's vesting deed (recorded 1996 or later, so every deed of
                   trust since is in the CRP index), every deed of trust the owner granted on the
                   parcel since acquiring it has a satisfaction (by Ref) recorded before C0, none
                   was granted after the last satisfaction, and no foreclosure instrument exists
                   for the parcel. There is then nothing to foreclose by power of sale.
               (c) conveyed_before_claim: the claim's person conveyed the parcel (a deed tied to
                   it, strong tie) to an unrelated grantee at least CONVEYED_MARGIN_DAYS before C0,
                   the county layer shows someone else as owner, every deed of trust that person
                   granted on the parcel was satisfied before C0 (complete search), and the
                   current owner's own search shows no foreclosure instrument on the parcel. The
                   person had neither title nor a loan on it when the claim was made.
  unconfirmed  everything else, always with `reason` and the human-lane pointer: no foreclosure
               instrument at ROD ("absence is not refutation"), a conveyance after the
               initiation with no satisfaction yet, a trustee deed the county layer contradicts,
               an incomplete or truncated search, no person to search, no parcel, a fetch error.
  wall         the ROD started challenging or blocking (a login redirect, HTTP 401/403/429/503, or
               a page asking for a CAPTCHA token): the sweep stops querying it for the rest of the
               run and every later row answers `wall` (reason rod_blocked) without a request. No
               reCAPTCHA token is ever obtained, solved or forged (FINDINGS: reCAPTCHA v3 is loaded
               in the page head but the search form carries no token field).

GOVERNS ("lis_pendens", "foreclosure_sale"), the listing-type signal names in
distress_score._LISTING_TYPE_SIGNAL of the rows this verifier covers. Suppression is
deliberately narrow: only a recorded conclusion of THIS parcel's foreclosure (stale) or one of the
three positive contradictions above (refuted) removes them; absence never does. sheriff_sale (0
Buncombe rows on 2026-10-06), auction (servicelink trustee AND REO auctions: a bank-owned auction
is expected to follow a trustee deed, and suppressing it would be wrong) and court_sale /
upset_bid (their own dates already end them) are not governed.

SIGNAL "foreclosure_rod", not "lis_pendens": the human lane writes its eCourts verdicts to
docs/handoff/verification/lis_pendens.json; sharing that ledger would let a ROD re-check
(is_due: "checked by another verifier") overwrite a human's court-record verdict. Separate
ledgers, both attached to the row.

WHAT IS PUBLISHED (the ledger is pushed to a PUBLIC repo): public_evidence() is the whitelist.
Document types, recorded dates, book/page and Ref numbers, the tie basis, the identity basis as
INITIALS plus the middle verdict, counts of other same-surname / same-name people, the parcel's
PIN, vesting deed and its date, and the claim's dates. Never a grantor's, grantee's, owner's or
other person's name, never a lender, never the owner of record. ROW_SUMMARY_EXCLUDE drops
owner_name from the ledger row summary.

POLITENESS. One row at a time through the sweep's Fetcher (per-host pacing, 1.5 s default): per
row one GIS query, then one GET of the search page and one POST per person searched (at most
MAX_SEARCHES). The search page is plain ASP.NET WebForms; the session is a cookie jar, the POST
body is rod/aumentum.py's (__VIEWSTATE intentionally empty, as the vendor serves it).
"""
from __future__ import annotations

import re
import weakref
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional
from urllib.parse import urlencode

from ..core import VerificationResult, result

SIGNAL = "foreclosure_rod"
VERSION = "v2"         # v2 (2026-10-06, before any v1 verdict was used): a trustee deed is
                       # judged against its own borrower's acquisition (not the later buyer's),
                       # a description naming another lot never ties, no-chain reason split out
TTL_DAYS = 14          # a sale, a trustee deed or a payoff can land within weeks
RETRY_DAYS = 7
SOURCE = "registerofdeeds.buncombenc.gov"
GOVERNS = ("lis_pendens", "foreclosure_sale")
ROW_SUMMARY_EXCLUDE = ("owner_name",)

LISTING_TYPES = ("lis_pendens", "foreclosure_sale")

ROD_BASE = "https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4"
SEARCH_URL = ROD_BASE + "/SrchName.aspx"
GIS_LAYER = "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1"
GIS_FIELDS = ("pin,pinext,owner,HouseNumber,streetname,StreetType,DeedBook,DeedPage,DeedDate,"
              "Instrument,SubName,SubLot,SubBlock,PlatBook,PlatPage,Stamps,SalePrice,UpdateDate")

RECENT_DAYS = 730            # an initiation within two years before the claim is "recent"
CONVEYED_MARGIN_DAYS = 365   # (c): the conveyance must precede the claim by at least a year
GIS_LAG_DAYS = 90            # a trustee deed older than this should be on the county layer
CRP_SINCE = date(1996, 1, 1) # pre-1995 deeds of trust are in another index (PRE 95 / DTR)
MAX_SEARCHES = 2

_NAME = __name__.rsplit(".", 1)[-1]
_P = "ctl00$cphMain$tcMain$tpNewSearch$ucSrchNames$"
_GRID_ID = "ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments"
HUMAN_LANE = ("NC eCourts case check (the court file of a lis pendens / SP foreclosure is not at "
              "ROD): scripts/verify_lead_human_assisted.py, signal lis_pendens")

# --------------------------------------------------------------------------------------------
# doc-type classes (the Buncombe vendor's literal Type column; the full list is the Advanced
# Name tab's instrument-type checkboxes, read live 2026-10-06)
# --------------------------------------------------------------------------------------------
INITIATION_TYPES = {"SUBSTITUTE TRUSTEE", "LIS PENDENS", "DEFAULT", "MEMORANDUM OF ACTION"}
CONCLUSION_TYPES = {"TRUSTEE DEED"}
FORECLOSURE_TYPE = "FORECLOSURE"        # recorded with / after the trustee deed (see docstring)
SATISFACTION_TYPES = {"DEED OF TRUST SATISFACTION", "SATISFACTION", "CANCELLATION"}
RESCISSION_TYPES = {"RESCISSION OF SATISFACTION"}
DOT_TYPES = {"DEED OF TRUST"}
CONVEYANCE_TYPES = {"DEED", "QUIT CLAIM DEED", "TRUSTEE DEED", "GIFT"}
_NOTICE_FORECLOSURE = re.compile(r"FORECLOS|DEFAULT|POWER OF SALE", re.I)


def _norm_type(t: Any) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip().upper()


def is_initiation(doc: dict) -> bool:
    t = _norm_type(doc.get("type"))
    if t in INITIATION_TYPES:
        return True
    return t == "NOTICE" and bool(_NOTICE_FORECLOSURE.search(doc.get("desc") or ""))


# --------------------------------------------------------------------------------------------
# which rows, and what they claim (pure)
# --------------------------------------------------------------------------------------------

def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def applies(row: dict) -> bool:
    return (str(row.get("state") or "").strip().upper() == "NC"
            and str(row.get("county") or "").strip().lower() == "buncombe"
            and row.get("listing_type") in LISTING_TYPES)


_CASE = re.compile(r"^\s*(\d{2})\s*(SP|CVS|CVD|CV|M|E|SPS)\s*0*(\d+)", re.I)


def to_date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    if m:
        try:
            return date.fromisoformat(m.group(0))
        except ValueError:
            return None
    m = re.search(r"\d{1,2}/\d{1,2}/\d{4}", s)
    if m:
        try:
            return datetime.strptime(m.group(0), "%m/%d/%Y").date()
        except ValueError:
            return None
    if re.fullmatch(r"\d{8}", s):
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def claim_of(row: dict) -> dict:
    """What the row claims, from the board row alone: the case kind and year, the cited ROD
    instrument, the claim's dated facts and their earliest (C0), and whether it is a
    deed-of-trust (power-of-sale) foreclosure on its face."""
    raw = _raw(row)
    out: dict[str, Any] = {"listing_type": row.get("listing_type"), "source": row.get("source")}
    m = _CASE.match(str(row.get("case_number") or ""))
    dates: dict[str, str] = {}
    if m:
        out["case_kind"] = m.group(2).upper()
        out["case_year"] = 2000 + int(m.group(1))
        dates["case_year"] = f"{out['case_year']}-01-01"
    nod = raw.get("nod") if isinstance(raw.get("nod"), dict) else None
    if nod and nod.get("book") and nod.get("page"):
        rec = to_date(nod.get("recorded_date"))
        out["cited"] = {"county": str(nod.get("county") or "").strip(),
                        "book_page": bp_key(nod.get("book"), nod.get("page")),
                        "doc_type": _norm_type(nod.get("doc_type")),
                        "recorded": rec.isoformat() if rec else None}
        if rec:
            dates["cited_recorded"] = rec.isoformat()
    ec = raw.get("nc_ecourts") if isinstance(raw.get("nc_ecourts"), dict) else {}
    for k in ("ordered_date_iso", "orderedDate", "judgment_date"):
        d = to_date(ec.get(k))
        if d:
            dates["ecourts_ordered"] = d.isoformat()
            break
    for k in ("sale_date", "first_seen"):
        d = to_date(row.get(k))
        if d:
            dates[k] = d.isoformat()
    out["dates"] = dates
    ds = [date.fromisoformat(v) for v in dates.values()]
    out["earliest"] = min(ds).isoformat() if ds else None
    src = str(row.get("source") or "")
    text = " ".join(str(x or "") for x in (row.get("description"), row.get("street_address"),
                                            row.get("legal_description"))).lower()
    out["dot_foreclosure"] = bool(
        src.startswith("law_firms.")
        or (nod and _norm_type(nod.get("doc_type")) in ("SUBSTITUTE TRUSTEE",))
        or "deed of trust" in text)
    return out


# --------------------------------------------------------------------------------------------
# names (pure)
# --------------------------------------------------------------------------------------------

_SUFFIX = {"JR", "SR", "II", "III", "IV", "V"}
_BAD_NAME = re.compile(r"[@\d]|\bTRUST\b|\bESTATE\b|\bHEIRS?\b|\bUNKNOWN\b", re.I)
_PARTICLES = r"(?:(?:VAN|VON|DE|DEL|DELA|LA|LE|MC|MAC|ST|DI|DA|DU|O)\s)?"
_COMMA_PERSON = re.compile(r"(?<![A-Z'\-])(" + _PARTICLES + r"[A-Z][A-Z'\-]+),\s*([A-Z][A-Z'\-]+)")
_PAREN = re.compile(r"\([^)]*\)")

Person = tuple  # (LAST, FIRST, MIDDLE-INITIAL or "")

# foreclosure.com's `defendant` is the recorded borrower when it is a 'LAST, FIRST' name (66 Walton
# St: the 2019 substitute-trustee grantor, the parcel passed by will in 2020), and a contact or a
# handle otherwise ("KevinKerr", an e-mail address): only the comma form is a claim person
COMMA_ONLY_DEFENDANT_SOURCES = {"national.foreclosure_dot_com"}


_PARTICLE_WORDS = {"VAN", "VON", "DE", "DEL", "DELA", "LA", "LE", "MC", "MAC", "ST", "DI", "DA",
                   "DU", "O", "VANDER", "VANDEN", "TEN", "TER"}


def person_parts(name: Any, *, surname_first_caps: bool = True) -> Optional[Person]:
    """(LAST, FIRST, MIDDLE-INITIAL or '') of one person's name, or None for an entity, an
    estate/trust/heirs string, or a name without two real words. The conventions are
    name_normalize.owner_last_first_middle's: a comma is LAST, FIRST; Title Case is FIRST [MIDDLE]
    LAST; ALL CAPS without a comma is SURNAME-FIRST (the county layer) unless surname_first_caps is
    False (a court/notice field), when it is read FIRST [MIDDLE] LAST. Two things it adds for ROD
    searching: a surname particle stays with the surname ("VAN DOOREN ELIZABETH ADRIENNE" ->
    ('VAN DOOREN', 'ELIZABETH', 'A'), searched as "VAN DOOREN"), and "(LE)", "(ETAL)" markers
    are dropped. Compare surnames with surname_key()."""
    from ...name_normalize import is_entity
    s = re.sub(r"\s+", " ", _PAREN.sub(" ", str(name or ""))).strip(" ,;")
    if not s or is_entity(s) or _BAD_NAME.search(s):
        return None

    def toks(x: str) -> list[str]:
        return [t for t in re.sub(r"[^A-Za-z ]", " ", x.replace("'", "")).upper().split() if t not in _SUFFIX]

    if "," in s:
        last_part, _, rest = s.partition(",")
        last, given = " ".join(toks(last_part)), toks(rest)
        if not last or not given:
            return None
        first, mid = given[0], (given[1][0] if len(given) > 1 else "")
    else:
        t = toks(s)
        if len(t) < 2:
            return None
        if re.search(r"[a-z]", s) or not surname_first_caps:          # FIRST [MIDDLE] LAST
            k = 2 if len(t) >= 3 and t[-2] in _PARTICLE_WORDS else 1
            last, given = " ".join(t[-k:]), t[:-k]
        else:                                                           # SURNAME FIRST [MIDDLE]
            k = 2 if len(t) >= 3 and t[0] in _PARTICLE_WORDS else 1
            last, given = " ".join(t[:k]), t[k:]
        if not given:
            return None
        first = given[0]
        mid = given[1][0] if len(given) > 1 else ""
    if len(surname_key(last)) < 2 or len(first) < 2:
        return None
    return last, first, mid


def surname_key(last: Any) -> str:
    """A surname for comparison: letters only ('VAN DOOREN' == 'VANDOOREN', "O'NEAL" == 'ONEAL')."""
    return re.sub(r"[^A-Z]", "", str(last or "").upper())


def persons_in(value: Any, *, surname_first_caps: bool = True) -> list[Person]:
    """Every person in one board name field: a county-style ';' list ("WALLIN THOMAS J;WALLIN
    SHIRLEY M"), a Title Case "X and Y", or an ROD-style run of 'LAST, FIRST ...' parties
    ("FREDRICH, CHAD FREDRICH, TIA", or a substitute-trustee grantor string with the lender after
    the borrowers). In a run only LAST and FIRST are kept: where one party ends and the next
    begins is not knowable, so no middle name is guessed from it."""
    s = re.sub(r"\s+", " ", str(value or "")).strip()
    if not s:
        return []
    out: list[Person] = []
    if s.count(",") >= 2 or (s.count(",") == 1 and len(s.split(",", 1)[1].split()) > 3):
        for last, first in _COMMA_PERSON.findall(_PAREN.sub(" ", s).upper()):
            p = person_parts(f"{last}, {first}")
            if p:
                out.append((p[0], p[1], ""))
    else:
        for seg in re.split(r"\s*;\s*|\s+(?:and|&)\s+", s, flags=re.I):
            p = person_parts(seg, surname_first_caps=surname_first_caps)
            if p:
                out.append(p)
    seen, uniq = set(), []
    for p in out:
        if (p[0], p[1]) not in seen:
            seen.add((p[0], p[1]))
            uniq.append(p)
    return uniq


def initials(p: Optional[Person]) -> Optional[str]:
    """'R.B.B.' for (BURTON, RICHARD, B): the identity basis the ledger publishes."""
    if not p:
        return None
    return ".".join(x[0] for x in (p[1], p[2], p[0]) if x) + "."


def rod_name_parts(name: str) -> Optional[Person]:
    """An ROD party ('BURTON, RICHARD B.', 'LANIER, JEFFREY HUNTER/ TR') as (LAST, FIRST, MI)."""
    n = re.sub(r"/.*$", "", str(name or "")).strip()
    if "," not in n:
        return None
    return person_parts(n)


def name_relation(a: Optional[Person], b: Optional[Person]) -> str:
    """'agrees' | 'unverified' | 'conflict' | 'none' between two parsed people: same LAST and FIRST
    (positional), then the middle initials (production's rule: both present and different is a
    different person; one missing proves nothing)."""
    if not a or not b or surname_key(a[0]) != surname_key(b[0]) or a[1] != b[1]:
        return "none"
    if a[2] and b[2]:
        return "agrees" if a[2] == b[2] else "conflict"
    return "unverified"


def middle_verdict(subject: Person, rod_name: str) -> str:
    """'agrees' | 'unverified' | 'conflict' for an ROD party positionally equal to the subject:
    name_normalize.party_middle_verdict, the production rule, with the party written FIRST
    MIDDLE LAST (its court-caption convention)."""
    from ...name_normalize import party_middle_verdict
    party = re.sub(r"/.*$", "", str(rod_name or "")).split(",", 1)
    if len(party) != 2:
        return "unverified"
    last, first, mid = subject
    subj = f"{surname_key(last)}, {first}" + (f" {mid}" if mid else "")
    return party_middle_verdict(subj, [f"{party[1].strip()} {surname_key(party[0])}"])


_REL_RANK = {"agrees": 3, "unverified": 2, "conflict": 1, "none": 0}


def owner_relation(owners: list[Person], claimed: Optional[Person],
                   claimed_raw: str = "") -> Optional[str]:
    """How the parcel's owner of record relates to the claim's person: 'entity' (the county
    names no person), the best name_relation over the co-owners, or None (no claim person). An
    ALL-CAPS claim name without a comma is also tried in the other reading order (county style
    vs notice style), so a reading-order difference is never taken for a different person."""
    if claimed is None:
        return None
    if not owners:
        return "entity"
    cands = [claimed]
    if claimed_raw and "," not in claimed_raw and not re.search(r"[a-z]", claimed_raw):
        for seg in re.split(r"\s*;\s*|\s+(?:AND|&)\s+", claimed_raw)[:1]:
            cands += [x for x in (person_parts(seg, surname_first_caps=False),
                                  person_parts(seg, surname_first_caps=True)) if x]
    best = "none"
    for o in owners:
        for c in cands:
            r = name_relation(o, c)
            if _REL_RANK[r] > _REL_RANK[best]:
                best = r
    return best


def claim_persons(row: dict) -> list[tuple[str, str, Person]]:
    """(field, raw value, person) for the claim's people, best first: the cited instrument's
    first grantor (counties.nod_discovery), the defendant, owner_name. foreclosure.com's
    `defendant` counts only in 'LAST, FIRST' form (COMMA_ONLY_DEFENDANT_SOURCES). Court/notice ALL-CAPS names without a comma read FIRST ... LAST, owner_name (county style)
    surname-first."""
    raw = _raw(row)
    nod = raw.get("nod") if isinstance(raw.get("nod"), dict) else {}
    fields = [("nod.grantor", nod.get("grantor"), True)]
    dfn = row.get("defendant")
    if str(row.get("source") or "") not in COMMA_ONLY_DEFENDANT_SOURCES or "," in str(dfn or ""):
        fields.append(("defendant", dfn, False))
    fields.append(("owner_name", row.get("owner_name"), True))
    out = []
    for field, val, sfc in fields:
        for p in persons_in(val, surname_first_caps=sfc)[:1]:
            out.append((field, str(val), p))
    return out


# --------------------------------------------------------------------------------------------
# book/page, the results grid, the county layer (pure)
# --------------------------------------------------------------------------------------------

_BP = re.compile(r"(\d{1,5})\s*/\s*(\d{1,5})")
_DT_REF = re.compile(r"\bD/?T\s*(\d{1,5})\s*/\s*(\d{1,5})", re.I)


def bp_key(book: Any, page: Any) -> Optional[str]:
    try:
        return f"{int(str(book).strip())}/{int(str(page).strip())}"
    except (TypeError, ValueError):
        return None


def parse_grid(text: str) -> dict:
    """{'count': the page's own "search returned N" (None when absent), 'docs': [...], 'zero':
    bool}. Each doc: n, date (ISO or None), type (literal), grantors/grantees [names], matched
    [the bold parties: the searched name], desc, bp, refs [book/page keys from the Ref column and
    any "DT b/p" in the description]. Nested party tables are read cell by cell (rod/aumentum.py:
    regex-on-<tr> breaks on them)."""
    from selectolax.parser import HTMLParser
    out: dict[str, Any] = {"count": None, "docs": [], "zero": False}
    m = re.search(r"search returned\s*<strong>\s*([\d,]+)", text or "", re.S | re.I)
    if m:
        out["count"] = int(m.group(1).replace(",", ""))
        out["zero"] = out["count"] == 0
    tree = HTMLParser(text or "")
    grid = tree.css_first(f"table#{_GRID_ID}")
    if grid is None:
        return out

    def direct_tds(tr):
        res, ch = [], tr.child
        while ch is not None:
            if ch.tag == "td":
                res.append(ch)
            ch = ch.next
        return res

    def txt(node) -> str:
        return " ".join(node.text(separator=" ", strip=True).split())

    def parties(td) -> tuple[list[str], list[str]]:
        names, bold = [], []
        for tr in td.css("tr"):
            cells = direct_tds(tr)
            if not cells:
                continue
            nm = txt(cells[0])
            if nm and nm != "-----":
                names.append(nm)
                if cells[0].css_first("b") is not None:
                    bold.append(nm)
        if not names:
            nm = txt(td)
            if nm and nm != "-----":
                names.append(nm)
        return names, bold

    for tr in grid.css("tr"):
        cls = tr.attributes.get("class") or ""
        if cls not in ("cottPagedGridViewRowStyle", "cottPagedGridViewAltRowStyle"):
            continue
        tds = direct_tds(tr)
        if len(tds) < 10:
            continue
        gr, grb = parties(tds[4])
        ge, geb = parties(tds[5])
        desc = txt(tds[6])
        refs = [bp_key(a, b) for a, b in _BP.findall(txt(tds[9]))]
        refs += [bp_key(a, b) for a, b in _DT_REF.findall(desc)]
        bpm = _BP.search(txt(tds[8]))
        d = to_date(txt(tds[1]))
        try:
            n = int(txt(tds[0]) or 0)
        except ValueError:
            n = 0
        out["docs"].append({
            "n": n, "date": d.isoformat() if d else None, "type": _norm_type(txt(tds[3])),
            "grantors": gr, "grantees": ge, "matched": grb + [x for x in geb if x not in grb],
            "matched_side": ("grantor" if grb else "") + ("grantee" if geb else ""),
            "desc": desc, "bp": bp_key(*bpm.groups()) if bpm else None,
            "refs": sorted({r for r in refs if r}),
        })
    out["docs"].sort(key=lambda d: d["n"])
    return out


def gis_url_pin(pin15: str) -> str:
    return (f"{GIS_LAYER}/query?" + urlencode({
        "where": f"pin='{pin15[:10]}' AND pinext='{pin15[10:]}'", "outFields": GIS_FIELDS,
        "returnGeometry": "false", "f": "json"}))


_SUFFIXES = {"ST", "STREET", "RD", "ROAD", "DR", "DRIVE", "AVE", "AVENUE", "LN", "LANE", "CT",
             "COURT", "CIR", "CIRCLE", "TRL", "TRAIL", "WAY", "PL", "PLACE", "HWY", "HIGHWAY",
             "BLVD", "LOOP", "PKWY", "TER", "TERRACE", "RUN", "PATH", "XING", "COVE", "CV",
             "RDG", "RIDGE", "HL", "HOLW", "VW", "PT", "SQ", "ALY", "EXT"}
_DIRS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST"}


def house_and_street(addr: Any) -> Optional[tuple[str, str]]:
    """('101', 'GREENWELLS GLORY') from '101 Greenwells Glory Dr' (a house number > 0, the
    street words without a leading direction or the trailing suffix); None otherwise."""
    s = re.sub(r"[^A-Za-z0-9 ]", " ", str(addr or "")).upper().split()
    if len(s) < 2 or not re.fullmatch(r"\d+", s[0]) or int(s[0]) <= 0:
        return None
    words = s[1:]
    while words and words[0].isdigit():      # "131 1/2 WYATT ST": the half-number
        words = words[1:]
    while words and words[0] in _DIRS and len(words) > 1:
        words = words[1:]
    while len(words) > 1 and words[-1] in _SUFFIXES:
        words = words[:-1]
    if not words or len(words) > 4:          # notice text parsed as an address ("100 UNDER AND BY ...")
        return None
    return str(int(s[0])), " ".join(words)


def gis_url_address(house: str, street: str) -> str:
    st = street.replace("'", "''")
    return (f"{GIS_LAYER}/query?" + urlencode({
        "where": f"HouseNumber='{house}' AND streetname LIKE '{st}%'", "outFields": GIS_FIELDS,
        "returnGeometry": "false", "f": "json"}))


def parcel_from_gis(data: Any) -> tuple[Optional[dict], int]:
    """(the one parcel's attributes, feature count). A count other than 1 is no identity."""
    feats = (data or {}).get("features") if isinstance(data, dict) else None
    if not isinstance(feats, list):
        return None, -1
    attrs = [f.get("attributes") or {} for f in feats if isinstance(f, dict)]
    pins = {(a.get("pin"), a.get("pinext")) for a in attrs}
    if len(pins) != 1:
        return None, len(pins)
    return attrs[0], 1


def parcel_summary(a: dict) -> dict:
    """The county layer's facts this verifier publishes (the owner's name stays in memory)."""
    vd, up = to_date(a.get("DeedDate")), to_date(a.get("UpdateDate"))
    out = {"pin": f"{a.get('pin') or ''}{a.get('pinext') or ''}" or None,
           "vesting_deed": bp_key(a.get("DeedBook"), a.get("DeedPage")),
           "vesting_date": vd.isoformat() if vd else None,
           "vesting_instrument": a.get("Instrument") or None,
           "vesting_stamps": a.get("Stamps"),
           "layer_updated": up.isoformat() if up else None}
    return {k: v for k, v in out.items() if v not in (None, "")}


# --------------------------------------------------------------------------------------------
# tying an instrument to the parcel (pure)
# --------------------------------------------------------------------------------------------

_LOT = re.compile(r"\b(?:LOT|LOTS|LT|LTS)\s*:?\s*([0-9A-Z]+(?:\s*(?:&|,|AND)\s*[0-9A-Z]+)*)", re.I)
_PB = re.compile(r"\bPB\s*(\d+)\s*/\s*(\d+)", re.I)


def _lots(desc: str) -> set[str]:
    out = set()
    for grp in _LOT.findall(desc or ""):
        for t in re.split(r"\s*(?:&|,|AND)\s*", grp.upper()):
            t = t.strip().lstrip("0")
            if t:
                out.add(t)
    return out


def _words(s: Any) -> list[str]:
    return re.sub(r"[^A-Z0-9 ]", " ", str(s or "").upper()).split()


def desc_tie(desc: str, a: dict) -> Optional[str]:
    """'subdivision_lot' | 'plat_lot' | 'street' | None for an instrument description against
    the parcel's county attributes."""
    if not desc:
        return None
    D = " ".join(_words(desc))
    mine = {t.strip().lstrip("0") for t in re.split(r"\s*(?:&|,|AND)\s*", str(a.get("SubLot") or "").upper())
            if t.strip().lstrip("0")}
    lots = _lots(desc)
    if mine and lots and not (mine & lots):
        return None              # another lot (an investor's lot 15 on the same street is not lots 1 & 2)
    lot_ok = bool(mine & lots)
    sub = " ".join(w for w in _words(a.get("SubName")) if w not in ("SUBDIVISION", "SUB"))
    if lot_ok and sub and f" {sub} " in f" {D} ":
        return "subdivision_lot"
    pb, pp = a.get("PlatBook"), a.get("PlatPage")
    try:
        want = (int(pb), int(pp))
    except (TypeError, ValueError):
        want = None
    plat = bool(want and want != (0, 0) and any((int(x), int(y)) == want for x, y in _PB.findall(desc)))
    if lot_ok and plat:
        return "plat_lot"
    st = " ".join(_words(a.get("streetname")))
    if st and f" {st} " in f" {D} ":
        return "plat_street" if plat else "street"
    return None


STRONG = {"vesting_deed", "subdivision_lot", "plat_lot", "plat_street"}


def tie_docs(docs: list[dict], a: dict) -> dict[str, dict]:
    """book/page -> {'tie', 'strength'} for every doc tied to the parcel, the Ref chain resolved
    to a fixed point (a satisfaction or substitute-trustee appointment inherits the tie of the
    deed of trust it refers to)."""
    vest = bp_key(a.get("DeedBook"), a.get("DeedPage"))
    ties: dict[str, dict] = {}
    for d in docs:
        if not d.get("bp"):
            continue
        t = "vesting_deed" if vest and d["bp"] == vest else desc_tie(d.get("desc") or "", a)
        if t:
            prev = ties.get(d["bp"])
            s = "strong" if t in STRONG else "weak"
            if not prev or (prev["strength"] == "weak" and s == "strong"):
                ties[d["bp"]] = {"tie": t, "strength": s}
    changed = True
    while changed:
        changed = False
        for d in docs:
            bp = d.get("bp")
            if not bp:
                continue
            for r in d.get("refs") or []:
                src = ties.get(r)
                if not src:
                    continue
                cur = ties.get(bp)
                if not cur or (cur["strength"] == "weak" and src["strength"] == "strong"):
                    ties[bp] = {"tie": "ref_chain", "strength": src["strength"], "via": r}
                    changed = True
    return ties


# --------------------------------------------------------------------------------------------
# the decision (pure): what was fetched -> (verdict, evidence)
# --------------------------------------------------------------------------------------------

def _dd(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _key(d: dict) -> tuple:
    return (d.get("bp"), d.get("type"), d.get("date"))


def _doc_pub(d: dict, ties: dict, ident: Optional[str] = None) -> dict:
    """One instrument as the ledger may show it: type, date, book/page, refs, tie, side,
    identity verdict. Never a party name."""
    t = ties.get(d.get("bp") or "") or {}
    out = {"type": d.get("type"), "recorded": d.get("date"), "book_page": d.get("bp"),
           "refs": d.get("refs") or None, "tie": t.get("tie"), "tie_strength": t.get("strength"),
           "party_side": d.get("matched_side") or None, "identity": ident}
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def subject_docs(grid: dict, subject: Person, anchor_mid: str = "") -> tuple[dict, dict]:
    """{doc key: middle verdict} for the docs whose matched (bold) party is the subject: same
    LAST and FIRST, middle not in conflict with the subject's middle initial, or with the
    vesting deed's when the subject has none (anchor_mid). Plus the collision counts (numbers
    only): other first names under the surname, and same-name people whose middle conflicts."""
    keep: dict[tuple, str] = {}
    others: set[str] = set()
    conflicts: set[str] = set()
    subj = (subject[0], subject[1], subject[2] or anchor_mid)
    for d in grid.get("docs") or []:
        best = None
        for nm in d.get("matched") or []:
            p = rod_name_parts(nm)
            if not p or surname_key(p[0]) != surname_key(subj[0]):
                continue
            if p[1] != subj[1]:
                others.add(p[1])
                continue
            v = middle_verdict(subj, nm)
            if v == "conflict":
                conflicts.add(p[2])
                continue
            if best is None or (best == "unverified" and v == "agrees"):
                best = v
        if best:
            keep[_key(d)] = best
    return keep, {"other_first_names": len(others), "same_name_middle_conflicts": len(conflicts)}


def _anchor_middle(grid: dict, subject: Person, vest: Optional[str]) -> str:
    """The middle initial on the parcel's vesting deed for the subject's name, when the subject
    has none and the deed has one: the property anchors which same-name person is the owner."""
    if not vest or subject[2]:
        return ""
    for d in grid.get("docs") or []:
        if d.get("bp") != vest:
            continue
        for nm in d.get("matched") or []:
            p = rod_name_parts(nm)
            if p and surname_key(p[0]) == surname_key(subject[0]) and p[1] == subject[1] and p[2]:
                return p[2]
    return ""


def _sats_of(bps: set, docs: list[dict], after: str = "") -> list[dict]:
    return [d for d in docs if d.get("type") in SATISFACTION_TYPES and bps & set(d.get("refs") or [])
            and (d.get("date") or "") >= after and not _rescinded(d, docs)]


def _rescinded(sat: dict, docs: Iterable[dict]) -> bool:
    """A satisfaction that a later RESCISSION OF SATISFACTION points at (its own book/page, or
    the same deed of trust)."""
    for d in docs:
        if d.get("type") in RESCISSION_TYPES and (d.get("date") or "") >= (sat.get("date") or ""):
            refs = set(d.get("refs") or [])
            if sat.get("bp") in refs or refs & set(sat.get("refs") or []):
                return True
    return False


def decide(claim: dict, parcel: Optional[dict], searches: list[dict], *, today: date,
           owner_rel: Optional[str] = None) -> tuple[str, dict]:
    """The verdict from what was fetched (the module docstring's VERDICTS, in that order).

    `searches`: [{'role': 'owner'|'co_owner'|'claim_person', 'subject': Person,
    'grid': parse_grid(...), 'complete': bool, 'narrowed': bool}]. `owner_rel`: owner_relation()
    of the parcel's owner of record to the claim's person ('entity', 'agrees', 'unverified',
    'conflict', 'none', or None when the row names no person)."""
    ev: dict[str, Any] = {}
    c0 = _dd(claim.get("earliest")) or today
    recent_from = c0 - timedelta(days=RECENT_DAYS)
    live_from = today - timedelta(days=RECENT_DAYS)
    # an initiation older than two years before TODAY (a 2021 substitute trustee for a 22SP case)
    # still confirms when the claim itself is current: a dated sale / order / recording this year
    claim_current = any(_dd(v) and _dd(v) >= today - timedelta(days=365)
                        for k, v in (claim.get("dates") or {}).items()
                        if k in ("sale_date", "cited_recorded", "ecourts_ordered"))
    a = parcel or {}
    vest = bp_key(a.get("DeedBook"), a.get("DeedPage")) if parcel else None
    gis_vest_date = to_date(a.get("DeedDate")) if parcel else None
    owner_changed = owner_rel in ("entity", "none", "conflict")

    all_docs: list[dict] = []
    seen: set = set()
    for s in searches:
        for d in (s.get("grid") or {}).get("docs") or []:
            if s["role"] == "owner_entity" and d.get("bp") != vest:
                continue           # an entity owner (a lender) is searched for its vesting deed only
            if _key(d) not in seen:
                seen.add(_key(d))
                all_docs.append(d)
    ties = tie_docs(all_docs, a) if parcel else {}

    mine: dict[tuple, str] = {}               # doc key -> best middle verdict, any subject
    by_role: dict[str, dict] = {}             # role -> {doc key: verdict}
    infos = []
    for s in searches:
        grid = s.get("grid") or {}
        if s["role"] == "owner_entity":
            hit = [d for d in grid.get("docs") or [] if d.get("bp") == vest]
            for d in hit:
                mine.setdefault(_key(d), "vesting_deed")
            infos.append({"role": "owner_entity", "results": len(grid.get("docs") or []),
                          "vesting_deed_found": bool(hit), "complete": bool(s.get("complete")),
                          "date_window": s.get("window")})
            continue
        anchor = _anchor_middle(grid, s["subject"], vest)
        keep, coll = subject_docs(grid, s["subject"], anchor)
        by_role.setdefault(s["role"], {}).update(keep)
        for k, v in keep.items():
            if v == "agrees" or k not in mine:
                mine[k] = v
        infos.append({"role": s["role"], "initials": initials(s["subject"]),
                      "results": len(grid.get("docs") or []), "own_results": len(keep),
                      "complete": bool(s.get("complete")), "narrowed": bool(s.get("narrowed")),
                      "anchored_on_vesting_deed": bool(anchor), **coll})
    if infos:
        ev["searches"] = infos

    def ident(d: dict) -> Optional[str]:
        return mine.get(_key(d))

    # ---- (1) the row's claim is an ROD instrument (counties.nod_discovery) ---------------------
    cited = claim.get("cited")
    if cited:
        ev["cited_instrument"] = {k: cited.get(k) for k in ("county", "book_page", "doc_type", "recorded")
                                  if cited.get(k)}
        if (cited.get("county") or "buncombe").lower() != "buncombe":
            if parcel and owner_rel in ("none", "conflict") and not claim.get("owner_shares_surname"):
                ev["decided_by"] = "cited_instrument_other_county"
                return "refuted", ev
            ev["reason"] = "cited_instrument_other_county_owner_unchecked"
            return "unconfirmed", ev
        hit = next((d for d in all_docs if d.get("bp") == cited.get("book_page") and ident(d)), None)
        if hit is None:
            ev["reason"] = "cited_instrument_not_found_under_person"
            return "unconfirmed", ev
        ev["cited_found"] = _doc_pub(hit, ties, ident(hit))
        refs = set(hit.get("refs") or [])
        after = [d for d in all_docs if d is not hit and refs & set(d.get("refs") or [])
                 and (d.get("date") or "") >= (hit.get("date") or "")]
        tds = [d for d in after if d["type"] in CONCLUSION_TYPES]
        if hit["type"] in CONCLUSION_TYPES:
            tds.append(hit)
        if tds:
            ev["decided_by"] = "trustee_deed_recorded"
            ev["deciding"] = [_doc_pub(d, ties, ident(d)) for d in tds[:2]]
            return "stale", ev
        sats = _sats_of(refs, all_docs, hit.get("date") or "") if refs else []
        if sats:
            ev["decided_by"] = "foreclosed_loan_satisfied"
            ev["deciding"] = [_doc_pub(d, ties, ident(d)) for d in sats[:2]]
            return "stale", ev
        if hit["type"] == FORECLOSURE_TYPE:
            ev["reason"] = "foreclosure_record_without_trustee_deed"
            return "unconfirmed", ev
        hd = _dd(hit.get("date"))
        if hd and hd >= recent_from and hd >= live_from:
            ev["decided_by"] = "cited_instrument_on_record"
            return "confirmed", ev
        ev["reason"] = "cited_instrument_old_no_outcome_at_rod"
        return "unconfirmed", ev

    if not parcel:
        ev["reason"] = "no_property_identity"
        return "unconfirmed", ev

    # ---- (2) the parcel's own chain -------------------------------------------------------------
    tied = [d for d in all_docs if d.get("bp") in ties]
    dots = [d for d in tied if d["type"] in DOT_TYPES and ident(d)]
    dot_bps = {d["bp"] for d in dots}
    inits = [d for d in tied if is_initiation(d) and (ident(d) or set(d.get("refs") or []) & dot_bps)]
    # a foreclosure trustee deed refers (Ref) to the deed of trust it forecloses: every one read
    # live does, and a living trust's trustee conveying its own land has nothing to refer to.
    # It counts when a searched person (the borrower) is among its grantors, or when it is the
    # parcel's own vesting deed on the county layer (the county says title came from it).
    tdeeds = [d for d in tied if d["type"] in CONCLUSION_TYPES and d.get("refs")
              and ((ident(d) and "grantor" in (d.get("matched_side") or "")) or d.get("bp") == vest)]
    fcls = [d for d in tied if d["type"] == FORECLOSURE_TYPE]
    def acquired_before(t: dict) -> Optional[str]:
        """When the trustee deed's grantor (a searched person) last took title to the parcel: a
        tied conveyance in that person's own results with them on the grantee side. A later
        buyer's acquisition (the sale that followed the foreclosure) is not theirs."""
        roles = [r for r, keys in by_role.items() if _key(t) in keys]
        dates = [d["date"] for d in tied for r in roles
                 if _key(d) in by_role[r] and d["type"] in CONVEYANCE_TYPES and d is not t
                 and "grantee" in (d.get("matched_side") or "") and d.get("date")]
        return max(dates, default=None)
    ev["chain"] = {"tied_instruments": len(tied), "deeds_of_trust": len(dots),
                   "initiations": len(inits), "trustee_deeds": len(tdeeds),
                   "foreclosure_records": len(fcls)}
    latest_init = max(inits, key=lambda d: d.get("date") or "", default=None)

    # stale (a): a trustee deed for this parcel, the owner among its grantors
    for t in sorted(tdeeds, key=lambda d: d.get("date") or "", reverse=True):
        td = _dd(t.get("date"))
        if td is None or td < recent_from:
            continue
        acquired = acquired_before(t)
        if (acquired and t["date"] < acquired) or (latest_init and t["date"] < (latest_init.get("date") or "")):
            continue
        strong = (ties.get(t["bp"]) or {}).get("strength") == "strong"
        county_agrees = vest == t["bp"] or (owner_changed and gis_vest_date is not None and gis_vest_date >= td)
        # the trustee deed ends the very foreclosure an initiation on this parcel began (same deed
        # of trust in both Refs): as tied as the initiation that would otherwise confirm it
        chain = bool(latest_init and set(t.get("refs") or []) & set(latest_init.get("refs") or []))
        if not strong and not county_agrees and not chain:
            continue
        if not county_agrees and (today - td).days > GIS_LAG_DAYS:
            ev["reason"] = "trustee_deed_not_reflected_on_parcel"
            ev["deciding"] = [_doc_pub(t, ties, ident(t))]
            return "unconfirmed", ev
        ev["decided_by"] = "trustee_deed_recorded"
        same = [f for f in fcls if set(f.get("refs") or []) & set(t.get("refs") or [])]
        ev["deciding"] = [_doc_pub(t, ties, ident(t))] + [_doc_pub(f, ties, ident(f)) for f in same[:1]]
        ev["county_layer_agrees"] = county_agrees
        ev["ends_initiation"] = chain or None
        return "stale", ev

    # stale (b) / confirmed: the latest initiation and what happened to its deed of trust
    if latest_init is not None:
        li = _dd(latest_init.get("date"))
        ev["latest_initiation"] = _doc_pub(latest_init, ties, ident(latest_init))
        if li and li >= recent_from:
            refs = set(latest_init.get("refs") or [])
            sats = _sats_of(refs, all_docs, latest_init.get("date") or "") if refs else []
            if sats:
                ev["decided_by"] = "foreclosed_loan_satisfied"
                ev["deciding"] = [_doc_pub(d, ties, ident(d)) for d in sats[:2]]
                return "stale", ev
            if owner_changed and gis_vest_date and gis_vest_date > li:
                ev["reason"] = "conveyed_after_initiation_no_satisfaction_yet"
                return "unconfirmed", ev
            if li >= live_from or claim_current:
                ev["decided_by"] = "initiation_on_record"
                return "confirmed", ev
            ev["reason"] = "initiation_old_no_outcome_at_rod"
            return "unconfirmed", ev

    no_fc = not inits and not tdeeds and not fcls
    # a refutation compares against WHEN the claim was made: only a dated claim (a case-number
    # year, a cited recording, an eCourts order) has one; first_seen is when the board noticed
    anchored = any(k in (claim.get("dates") or {}) for k in ("case_year", "cited_recorded", "ecourts_ordered"))

    # refuted (b): the owner of record is the claim's person and every loan was paid off
    own_keys: dict[tuple, str] = {**by_role.get("owner", {}), **by_role.get("co_owner", {})}
    own_searches = [s for s in searches if s["role"] in ("owner", "co_owner")]
    if (anchored and claim.get("dot_foreclosure") and owner_rel in ("agrees", "unverified") and own_searches
            and all(s.get("complete") and not s.get("narrowed") for s in own_searches)
            and vest and gis_vest_date and gis_vest_date >= CRP_SINCE and no_fc):
        vest_found = any(d.get("bp") == vest and "grantee" in (d.get("matched_side") or "")
                         and _key(d) in own_keys for d in all_docs)
        floor = (gis_vest_date - timedelta(days=30)).isoformat()
        since = [d for d in dots if _key(d) in own_keys and (d.get("date") or "") >= floor]
        if vest_found and since:
            sat_docs: Optional[list[dict]] = []
            for d in since:
                s = sorted((x for x in _sats_of({d["bp"]}, all_docs) if x.get("date")),
                           key=lambda x: x["date"])
                if not s:
                    sat_docs = None
                    break
                sat_docs.append(s[0])
            last_sat = max((x["date"] for x in sat_docs), default=None) if sat_docs else None
            if last_sat and _dd(last_sat) < c0:
                ev["decided_by"] = "no_open_deed_of_trust"
                ev["deeds_of_trust_since_vesting"] = len(since)
                ev["last_satisfaction"] = last_sat
                ev["deciding"] = [_doc_pub(d, ties, ident(d)) for d in since[:3]] + \
                    [_doc_pub(x, ties, ident(x)) for x in sat_docs[:3]]
                return "refuted", ev

    # refuted (c): the claim's person had conveyed the parcel, loans paid, long before the claim
    cp_keys = by_role.get("claim_person", {})
    cp_search = next((s for s in searches if s["role"] == "claim_person"), None)
    if (anchored and cp_search and own_searches and owner_rel in ("none", "conflict") and no_fc
            and cp_search.get("complete") and not cp_search.get("narrowed")):
        cp_last = cp_search["subject"][0]
        cutoff = c0 - timedelta(days=CONVEYED_MARGIN_DAYS)
        conv = [d for d in tied if _key(d) in cp_keys and d["type"] in CONVEYANCE_TYPES
                and d["type"] != "TRUSTEE DEED" and "grantor" in (d.get("matched_side") or "")
                and (ties.get(d["bp"]) or {}).get("strength") == "strong"
                and not any(surname_key((rod_name_parts(g) or ("",))[0]) == surname_key(cp_last)
                            for g in d.get("grantees") or [])
                and _dd(d.get("date")) and _dd(d["date"]) <= cutoff]
        cp_dots = [d for d in dots if _key(d) in cp_keys]
        unpaid = [d for d in cp_dots if not [x for x in _sats_of({d["bp"]}, all_docs)
                                             if _dd(x.get("date")) and _dd(x["date"]) < c0]]
        if conv and not unpaid:
            ev["decided_by"] = "conveyed_before_claim"
            ev["deciding"] = [_doc_pub(d, ties, ident(d)) for d in conv[:2]]
            ev["claim_person_deeds_of_trust"] = len(cp_dots)
            return "refuted", ev

    if not tied:
        ev["reason"] = "parcel_chain_not_found_at_rod"
    elif fcls and not tdeeds:
        ev["reason"] = "foreclosure_record_without_trustee_deed"
    elif no_fc:
        ev["reason"] = "no_foreclosure_instrument_at_rod"
    else:
        ev["reason"] = "foreclosure_instruments_not_recent"
    return "unconfirmed", ev


# --------------------------------------------------------------------------------------------
# what is published (pure)
# --------------------------------------------------------------------------------------------

_PUBLIC = ("decided_by", "reason", "claim", "parcel", "searches", "chain", "deciding",
           "cited_instrument", "cited_found", "latest_initiation", "county_layer_agrees",
           "ends_initiation",
           "owner_relation", "deeds_of_trust_since_vesting", "last_satisfaction",
           "claim_person_deeds_of_trust", "human_lane", "url", "error", "blocked")
_CLAIM_PUBLIC = ("listing_type", "source", "case_kind", "case_year", "earliest", "dates",
                 "dot_foreclosure")


def public_evidence(verdict: str, ev: dict) -> dict:
    """The whitelist (WHAT IS PUBLISHED): no person names anywhere; types, dates, book/pages,
    tie bases, initials and verdicts, counts. Idempotent."""
    out = {k: ev.get(k) for k in _PUBLIC if ev.get(k) not in (None, "", [], {})}
    if isinstance(out.get("claim"), dict):
        out["claim"] = {k: out["claim"][k] for k in _CLAIM_PUBLIC
                        if out["claim"].get(k) not in (None, "", {})}
    if isinstance(out.get("error"), str):
        out["error"] = out["error"].split(":", 1)[0][:60]
    if verdict in ("unconfirmed", "wall"):
        out.setdefault("human_lane", HUMAN_LANE)
    return out


# --------------------------------------------------------------------------------------------
# the source
# --------------------------------------------------------------------------------------------

# client -> {"blocked": reason}: once the ROD challenges or blocks, the rest of the run is wall
_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run_state(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {})
    except TypeError:                                   # not weak-referenceable: no sharing
        return {}


class Blocked(Exception):
    pass


_CHALLENGE = re.compile(r"g-recaptcha-response|name=\"captcha|verify you are (?:a )?human|"
                        r"access denied|request unsuccessful|incapsula|cf-chl", re.I)


def check_block(resp: Any) -> Optional[str]:
    """A reason when a response is a login wall, a block or a challenge page; None for a page
    the search can read. reCAPTCHA v3's <script> in every page head is NOT a challenge (the form
    carries no token field); a page asking for one is."""
    if "/User/Login.aspx" in (resp.url or ""):
        return "login_redirect"
    if resp.status in (401, 403, 429, 503):
        return f"http_{resp.status}"
    t = resp.text or ""
    if _CHALLENGE.search(t) and "search returned" not in t and _GRID_ID not in t \
            and "ucSrchNames" not in t:
        return "challenge_page"
    return None


def name_body(last: str, first: str, dfrom: str = "", dthru: str = "") -> dict:
    """rod/aumentum.py's live-verified name-search body, restricted to Consolidated Real
    Property (deeds, deeds of trust, satisfactions, substitute trustees, trustee deeds)."""
    from ...rod import aumentum
    b = aumentum._name_body(last, first, dfrom, dthru)
    b[_P + "ddlIndexType"] = "CRP"
    return b


async def rod_search(session: Any, entry_url: str, subject: Person, *,
                     narrow_from: Optional[date], today: date,
                     window: Optional[tuple[date, date]] = None) -> dict:
    """One name search on an open form session: {'grid', 'complete', 'narrowed'} or {'error'}.
    Raises Blocked on a wall. A name over the vendor's result limit is retried once with a
    filed-date window (narrowed: then it is never complete enough to refute). `window` searches
    a fixed filed-date range from the start (an entity owner around its vesting deed's date)."""
    w = (window[0].strftime("%m/%d/%Y"), window[1].strftime("%m/%d/%Y")) if window else ("", "")
    r = await session.post_form(entry_url, name_body(subject[0], subject[1], *w),
                                headers={"Referer": entry_url})
    why = check_block(r)
    if why:
        raise Blocked(why)
    if "v2Error.aspx" in (r.url or ""):
        return {"error": "vendor_error_page"}
    narrowed = False
    if re.search(r"allowable results|maximum number of", r.text or "", re.I):
        if narrow_from is None or window:
            return {"error": "too_many_results"}
        r = await session.post_form(entry_url, name_body(subject[0], subject[1],
                                                         narrow_from.strftime("%m/%d/%Y"),
                                                         today.strftime("%m/%d/%Y")),
                                    headers={"Referer": entry_url})
        why = check_block(r)
        if why:
            raise Blocked(why)
        narrowed = True
        if re.search(r"allowable results|maximum number of", r.text or "", re.I):
            return {"error": "too_many_results"}
    g = parse_grid(r.text)
    if g["count"] is None and not g["docs"]:
        return {"error": "unparseable_results"}
    return {"grid": g, "complete": g["count"] is not None and g["count"] == len(g["docs"]),
            "narrowed": narrowed}


_ENTITY_TAIL = {"LLC", "L", "C", "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LP", "LLP",
                "NA", "N", "A", "THE", "OF", "AND", "TRUST", "TRUSTEE", "NATIONAL", "ASSOCIATION"}


def entity_key(owner: Any) -> Optional[str]:
    """The 'Begins With' search key for an entity owner of record: its first words up to three,
    without a leading THE or the trailing form words ("VMC REO LLC" -> "VMC REO", "JPMORGAN CHASE
    BANK NATIONAL ASSOCIATION" -> "JPMORGAN CHASE BANK")."""
    w = re.sub(r"[^A-Z0-9 ]", " ", str(owner or "").upper().split(";")[0]).split()
    if w and w[0] == "THE":
        w = w[1:]
    w = w[:3]
    while w and w[-1] in _ENTITY_TAIL:
        w = w[:-1]
    key = " ".join(w)
    return key if len(key) >= 3 else None


def _res(verdict: str, evidence: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(verdict, evidence), source=SOURCE,
                  version=VERSION, verifier=_NAME)


async def find_parcel(row: dict, client) -> tuple[Optional[dict], Optional[str]]:
    """(the county layer's record for the row's parcel, 'pin'|'address'), by the row's PIN,
    else its house number and street; (None, None) when neither gives exactly one parcel."""
    from .tax_lien_buncombe import pin_of
    pin = pin_of(row)
    if pin:
        parcel, _ = parcel_from_gis(await client.get_json(gis_url_pin(pin)))
        if parcel:
            return parcel, "pin"
    hs = house_and_street(row.get("street_address"))
    if hs:
        parcel, _ = parcel_from_gis(await client.get_json(gis_url_address(*hs)))
        if parcel:
            return parcel, "address"
    return None, None


def _address_agrees(row: dict, a: dict) -> Optional[bool]:
    hs = house_and_street(row.get("street_address"))
    if not hs or not a.get("HouseNumber"):
        return None
    return (hs[0] == str(a.get("HouseNumber")).strip().lstrip("0")
            and " ".join(_words(a.get("streetname"))).startswith(hs[1].split()[0]))


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    claim = claim_of(row)
    ev: dict[str, Any] = {"claim": claim, "url": SEARCH_URL}
    state = _run_state(client)
    if state.get("blocked"):
        ev["blocked"] = state["blocked"]
        ev["reason"] = "rod_blocked_earlier_this_run"
        return _res("wall", ev)
    cited = claim.get("cited")

    # the parcel, from the county layer (rows citing an ROD instrument may have none)
    try:
        parcel, how = await find_parcel(row, client)
    except Exception as exc:  # noqa: BLE001
        ev["reason"] = "county_layer_failed"
        ev["error"] = type(exc).__name__
        return _res("unconfirmed", ev)
    if parcel is not None:
        ev["parcel"] = {"resolved_by": how, **parcel_summary(parcel),
                        "board_address_agrees": _address_agrees(row, parcel)}
    elif not cited:
        ev["reason"] = "no_property_identity"
        return _res("unconfirmed", ev)

    # who the parcel belongs to, and who the claim names
    owners = persons_in(parcel.get("owner"), surname_first_caps=True) if parcel else []
    claimers = claim_persons(row)
    cp = claimers[0] if claimers else None
    rel = owner_relation(owners, cp[2] if cp else None, cp[1] if cp else "") if parcel else None
    ev["owner_relation"] = rel
    if cited and cp and owners:
        toks = {surname_key(t) for t in re.sub(r"[^A-Z ]", " ", cp[1].upper()).split()}
        claim["owner_shares_surname"] = any(surname_key(o[0]) in toks for o in owners)

    if cited and (cited.get("county") or "buncombe").lower() != "buncombe":
        verdict, dev = decide(claim, parcel, [], today=today, owner_rel=rel)
        ev.update(dev)
        return _res(verdict, ev)

    subjects: list[tuple[str, Person]] = []
    window = None
    if cited:
        if cp:
            subjects.append(("claim_person", cp[2]))
    else:
        vd = to_date(parcel.get("DeedDate")) if parcel else None
        c0 = to_date(claim.get("earliest")) or today
        ekey = entity_key(parcel.get("owner")) if parcel and not owners else None
        if owners:
            subjects.append(("owner", owners[0]))
        elif ekey and vd and vd >= c0 - timedelta(days=RECENT_DAYS):
            # an entity (a lender, an investor) took title recently: was it by trustee deed?
            subjects.append(("owner_entity", (ekey, "", "")))
            window = (vd - timedelta(days=7), vd + timedelta(days=7))
        if cp and rel in ("entity", "none", "conflict"):
            subjects.append(("claim_person", cp[2]))
    subjects = subjects[:MAX_SEARCHES]
    if not subjects:
        ev["reason"] = "no_person_to_search"
        return _res("unconfirmed", ev)

    narrow_from = None
    if parcel and to_date(parcel.get("DeedDate")):
        narrow_from = to_date(parcel.get("DeedDate")) - timedelta(days=366)
    elif claim.get("earliest"):
        narrow_from = date.fromisoformat(claim["earliest"]) - timedelta(days=RECENT_DAYS + 366)

    searches: list[dict] = []
    try:
        async with client.form_session() as s:
            boot = await s.get(SEARCH_URL)
            why = check_block(boot)
            if why:
                raise Blocked(why)
            entry = boot.url or SEARCH_URL

            async def run(role: str, subj: Person) -> Optional[dict]:
                win = window if role == "owner_entity" else None
                got = await rod_search(s, entry, subj, narrow_from=narrow_from, today=today,
                                       window=win)
                if got.get("error"):
                    ev["reason"] = got["error"]
                    ev["searches"] = [{"role": role, "initials": initials(subj) if subj[1] else None}]
                    return None
                searches.append({"role": role, "subject": subj, **got,
                                 "window": [w.isoformat() for w in win] if win else None})
                return got

            for role, subj in subjects:
                if await run(role, subj) is None:
                    return _res("unconfirmed", ev)
            verdict, dev = decide(claim, parcel, searches, today=today, owner_rel=rel)
            # a refutation from the owner's loans must cover every co-owner who could have
            # signed a deed of trust: search the next one before publishing it
            if verdict == "refuted" and dev.get("decided_by") == "no_open_deed_of_trust":
                for o in owners[1:2]:
                    if await run("co_owner", o) is None:
                        return _res("unconfirmed", ev)
                    verdict, dev = decide(claim, parcel, searches, today=today, owner_rel=rel)
    except Blocked as b:
        state["blocked"] = str(b)
        ev["blocked"] = str(b)
        ev["reason"] = "rod_blocked"
        return _res("wall", ev)
    except Exception as exc:  # noqa: BLE001
        ev["reason"] = "rod_fetch_failed"
        ev["error"] = type(exc).__name__
        return _res("unconfirmed", ev)
    ev.update(dev)
    return _res(verdict, ev)
