"""probate_heir, Buncombe NC: is the person the board names as dead really dead on the county's
own record, and is THIS property still in that person's estate (unsettled), or has the estate
already conveyed it?

Evolved from docs/validation_2026-10-03/scripts/validate_probate_heir_buncombe.py (N=55: a death
record for 81.8%, a transfer pattern consistent with an heir/estate for 89.3% of the 28 parcels it
could read, named-party voter liveness on 9.4% of the pool, 66.7% of those active). That script
counted a death record when the first and last name appeared anywhere in the record's grantor
cell (a same-name person with another middle name counted: live 2026-10-06, the notice of one
"B. D." decedent returned only a different "B. J." of the same name and an infant's record naming
him as the PARENT), and read the transfer history from the Spatialest card in a headless browser.
This verifier reads the same two public sources the Register of Deeds and the county keep, with
production's identity rule, one person at a time.

AUTOMATED ONLY. Discovering NEW heirs (the "9th heir" of 50 Boone St) needs the estate file in NC
eCourts, which is CAPTCHA-walled: that stays the human lane (verification_human_lane.py,
scripts/verify_lead_human_assisted.py, signals probate / heir_estate; docs/HANDOFF.md item 61).

THE CLAIMS IT COVERS (applies(); Buncombe NC rows only), exactly what the scorer reads:
  * listing_type probate_notice / estate_lead (distress_score._LISTING_TYPE_SIGNAL),
  * a real raw.probate / raw.estate block (signal_freshness.has_real_probate -> "probate"),
  * raw.heir_estate (the county roll titles the parcel to "<name> HEIRS" / "ESTATE OF <name>"),
  * raw.life_events "estate_probate" on an owner name that names a death (the facet "probate").
The relationship_signal kind "probate" (scorer name "probate_deed") is not a claim of its own on
these rows: on all 257 covered rows that carry it (2026-10-06 board) it is a keyword tag of the
same notice or roll ("obituary", "ADMINISTRATOR", "EXECUTOR", "heir_estate_owner_of_record",
"ESTATE OF", "notice_to_creditors"), so it is governed with them (see GOVERNS).

THE DECEDENT (decedent_of(); pure). The first usable name of: raw.probate.decedent / raw.estate,
raw.obituary.decedent, raw.heir_estate.heir_names (a role "heir"/"estate" entry is the person
WHOSE heirs or estate hold title, i.e. the decedent, not an heir), heir_estate.owner_of_record, an
owner name that names a death, the notice's defendant / owner name, and "Estate of <name>" in the
notice text. Junk ("deceased", "Said Deceased To Exhibit") is skipped. Title Case reads FIRST
[MIDDLE] LAST; ALL CAPS is read FIRST ... LAST first (every "<name> HEIRS" on the 10/6 board but
one is in that order) and surname-first second; a parcel owner of record that names the person
in either order fixes the order. Initial-only given names ("J A STEPP") cannot be searched.

CHECK 1, THE DEATH RECORD. The ROD DEATHS index (registerofdeeds.buncombenc.gov SrchName.aspx,
ddlIndexType "DTH", the same vendor session and POST body as rod/aumentum.py and the
foreclosure_rod verifier; dates are masked to the year, "**/**/2023"; the decedent is the
grantor, the parents are the grantees; the page states the index's "Valid ... Thru" date). A
record is the decedent's only when a matched (bold) GRANTOR party has the same LAST and FIRST
name and its middle initial does not conflict (core rule of name_normalize.party_middle_verdict:
both present and different = another person; two different generational suffixes, JR vs SR, are
two people too; a wife indexed under her husband's name, "COOK, SAMUEL D MRS", is not him),
recorded no later than the claim says the person was dead (death_by) and, for an estate file
"YYE...", no more than DEATH_BEFORE_CASE_YEARS before it. One such record = matched (basis
middle_agrees, first_last, or middle_and_suffix_agree when the board name's suffix picks one of
several agreeing records); several = ambiguous (live: common names with no middle on the board
read two or three different people); only other-middle records = conflict_only; none =
not_found. A death outside Buncombe is recorded in that county, so not_found is never evidence
against the claim.

CHECK 2, THE TRANSFER PATTERN. The county parcel layer (gis.buncombecounty.org property_bc_dis/
MapServer/1, by PIN else house number + street; foreclosure_rod_buncombe.find_parcel) gives the
owner of record today and the vesting deed (book/page, date, instrument, excise stamps, price);
the ROD name index (Consolidated Real Property) searched for the decedent gives the instruments
the decedent signed or received, tied to the parcel as foreclosure_rod ties them (the vesting
deed's book/page, subdivision + lot, plat + lot: strong; street: weak). Categories (published):
  titled_to_decedent   the owner of record names the decedent personally (alone or with others)
  heirs_of_record      the owner of record is "<the decedent> HEIRS" / "ESTATE OF <the decedent>"
  heirs_of_other       the owner of record is the heirs of a DIFFERENT person
  family               the owner of record shares a surname with the decedent / care-of / PR
  conveyed_out         an unrelated owner whose vesting deed came out of the decedent or the
                       estate after the death, for value (see stale)
  conveyed_before_death  an unrelated owner whose vesting deed the decedent signed, alive, at
                       least two years before the death record (see refuted)
  conveyed_no_consideration / conveyed_timing_unclear / unrelated_no_tie   the rest
"Unsettled" = titled_to_decedent or heirs_of_record, with no deed out of the decedent on the
ROD index after the death that the county layer has not caught up with.

VERDICTS (core.py's meanings):
  confirmed    the death record matched AND the estate looks unsettled (titled_to_decedent or
               heirs_of_record, no recorded conveyance out after the death).
  stale        the property has already been conveyed out of the estate, to a third party for
               value: the owner of record is unrelated to the decedent (no shared surname with
               the decedent, the care-of or the personal representative), the vesting deed
               carries excise stamps or a price, and the conveyance is shown to follow the death
               by one of ("after the death" = on or after the record's own date when the index
               shows one, else from the January after its year: the vendor masks most dates to
               the year, and a deed in the death's own year may precede it):
               (A) the vesting deed is in the decedent's ROD results with the decedent (or the
               estate) as grantor, recorded after the death, or marked as an estate conveyance;
               (B) the decedent acquired the parcel (a strongly tied deed with the decedent as
               grantee) and the vesting deed is dated after the death; (C) the claim is the
               county roll's own "<decedent> HEIRS" on
               this PIN and the vesting deed is dated after the roll was read (first_seen); or (D)
               the county still shows the decedent / heirs but the ROD index holds a strongly
               tied deed out of the decedent or estate to an unrelated grantee, after the death,
               within the last LAYER_LAG_DAYS (the layer has not caught up).
  refuted      ONLY on positive contrary evidence, three precise cases:
               (R0) no_death_word_on_roll: the row's only claim is an heir-roll block whose own
                    roll string and heir entries carry no death word at all (no HEIR / HEIRS /
                    ESTATE / EST OF token, no role heir/estate entry; nothing else on the row
                    names a death), and the county layer by the row's PIN shows no death word on
                    the owner either. On the 10/6 board these are the scraper's pre-word-boundary
                    substring matches ("...HEIR..." inside a surname, match "heirs"): the county
                    never titled the parcel to anyone's heirs.
               R1 and R2 need the decedent's ROD search complete (not truncated or narrowed)
               and the deciding instrument's grantor party to AGREE with the decedent's middle
               initial, both present; an estate-marked party never refutes:
               (R1) conveyed_before_death: the parcel's vesting deed per the county layer is in
                    the decedent's results with the decedent as grantor, to grantees who share no
                    surname with the decedent, recorded at least two calendar years before the
                    matched death record. The decedent sold the property while alive: it was
                    never in the estate.
               (R2) decedent_acted_after_death_claim: no death record matched, and the named
                    decedent personally signed (grantor side) a deed / deed of trust tied
                    strongly to THIS parcel, recorded at least ACTED_AFTER_DAYS after the date by
                    which the claim says the person was dead (the notice / roll / obituary first
                    seen, the end of the estate file's year): the "decedent" was alive and acting
                    on this property, so the claim is not true of it.
  unconfirmed  everything else, always with `reason` (no property identity, no decedent name,
               no death record yet, an ambiguous record, an unrelated owner with nothing tying
               the decedent to the parcel, a conveyance to family or without consideration, a
               fetch error) and the human-lane pointer.
  wall         the ROD started challenging or blocking (shared with foreclosure_rod through
               foreclosure_rod_buncombe._run_state: one block stops both for the rest of the run).

HEIR LIVENESS (evidence only; it never changes the verdict and no scorer reads it). Every named
party the row carries is searched on vt.ncsbe.gov (enrichment_nc_voter_lookup.nc_voter_search,
Registered AND Removed-or-Denied, statewide, a fresh client per search), classified with
elderly_disabled.classify_voters (registered first: one -> active / inactive, several -> the
city picks one, else ambiguous; else any removed -> removed; else not_found). Groups: the
heir_names entries (role heir/estate = the decedent named on the roll; other/trustee = a co-owner
named beside the heirs), the county's care-of, the personal representative. Published as COUNTS
per group and status only (heir_liveness), at most MAX_VOTER_SEARCHES per row.

IDENTITY "case": the claim is "the estate of THIS decedent holds THIS property". case_identity =
core.case_id("estate", state, county, the decedent's last and first name sorted, so "ALICE
METCALF HEIRS" and "METCALF ALICE HEIRS" are one estate), scoped by the property as every
case-scoped verifier is. Two decedents' claims on one parcel (a notice the name resolver put on a
placeholder parcel, an heir block merged onto a neighbour's row: both on the 10/6 board) get two
verdicts; an estate notice and an obituary of the same person on the same property share one.

GOVERNS ("probate", "probate_notice", "estate_lead", "probate_deed"): every scorer name these
claims feed (distress_score._collect + _LISTING_TYPE_SIGNAL, enrichment_lead_signals facets).
probate_deed is included because on these rows it is a keyword tag of the same claim (above):
left out, a stale estate would keep its LIFE_EVENT 20 under that name.

SIGNAL "probate_heir", not "probate" / "heir_estate": those are the human lane's eCourts ledgers;
a ROD re-check must never overwrite a human's court-record verdict.

PRIVACY (the ledger is a committed file in a PUBLIC repo; decedents AND their living heirs).
public_evidence() is the whitelist: death-record existence, its recorded year (or date), book/
page, the index's valid-thru date, the identity basis as INITIALS plus the middle verdict, counts
of same-name records; the transfer category, the PIN, the vesting deed's book/page / date /
instrument / whether it carried consideration, the deciding instruments' types, dates, book/pages
and tie basis; heir counts by voter status. Never a name (decedent, heir, owner, grantee, parent,
representative), never a voter id, NCID, DOB, age or address. ROW_SUMMARY_EXCLUDE drops owner_name
AND street_address from the ledger's row summary (a notice row's street_address can hold notice
text with names, e.g. "<decedent> - Case 26E...").

POLITENESS. One row at a time through the sweep's Fetcher (1.5 s per host): per row at most one
GIS query, one GET of the ROD search page, MAX_DEATH_SEARCHES DEATHS POSTs, one CRP POST, and
MAX_VOTER_SEARCHES voter searches (3 requests each, another host). A row with no decedent name
makes no request.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Optional

from ..core import VerificationResult, case_id, result
from . import foreclosure_rod_buncombe as F

SIGNAL = "probate_heir"
VERSION = "v2"         # v2 (2026-10-06, the same night as v1's first sweep): a row's PIN is
                       # authoritative (no address fallback: an unpaid-bill row's street_address
                       # can be the owner's MAILING address), and an ArcGIS error body is a
                       # fetch failure (one retry), never "no parcel"
TTL_DAYS = 30          # an estate sale or a distribution deed can land within weeks
RETRY_DAYS = 7
SOURCE = "registerofdeeds.buncombenc.gov + gis.buncombecounty.org"
GOVERNS = ("probate", "probate_notice", "estate_lead", "probate_deed")
ROW_SUMMARY_EXCLUDE = ("owner_name", "street_address")
IDENTITY = "case"

LISTING_TYPES = ("probate_notice", "estate_lead")
VOTER_HOST = "vt.ncsbe.gov"

DEATH_BEFORE_CASE_YEARS = 5    # an estate file is opened within a few years of the death
ACTED_AFTER_DAYS = 90          # (R2): a deed signed before the death can be recorded weeks later
LAYER_LAG_DAYS = 365           # (D): a deed out the county layer has not caught up with
MAX_DEATH_SEARCHES = 2
MAX_VOTER_SEARCHES = 3

_NAME = __name__.rsplit(".", 1)[-1]
HUMAN_LANE = ("NC eCourts estate file (heirs, personal representative, closing): "
              "scripts/verify_lead_human_assisted.py, signal probate / heir_estate")

# --------------------------------------------------------------------------------------------
# which rows, and the decedent (pure)
# --------------------------------------------------------------------------------------------

_ID_FIELDS = ("state", "county", "source", "listing_type", "case_number", "owner_name",
              "defendant", "description", "first_seen", "parcel_id", "street_address", "city",
              "raw")


def _d(row: Any) -> dict:
    """A board dict as is; a models.Listing as a dict of the fields read here (the VM's apply
    calls case_identity on Listings)."""
    if isinstance(row, dict):
        return row
    out = {k: getattr(row, k, None) for k in _ID_FIELDS}
    lt = out.get("listing_type")
    out["listing_type"] = getattr(lt, "value", lt)
    return out


def _raw(d: dict) -> dict:
    r = d.get("raw")
    return r if isinstance(r, dict) else {}


def carries_claim(d: dict) -> bool:
    from ...signal_freshness import has_real_probate, owner_names_a_death
    raw = _raw(d)
    lt = d.get("listing_type")
    lt = getattr(lt, "value", lt)
    if lt in LISTING_TYPES:
        return True
    if has_real_probate(raw.get("probate")) or has_real_probate(raw.get("estate")):
        return True
    he = raw.get("heir_estate")
    if isinstance(he, dict) and (he.get("owner_of_record") or he.get("heir_names")):
        return True
    le = raw.get("life_events")
    return (isinstance(le, (list, tuple)) and "estate_probate" in le
            and owner_names_a_death(d.get("owner_name")))


def applies(row: dict) -> bool:
    d = _d(row)
    return (str(d.get("state") or "").strip().upper() == "NC"
            and str(d.get("county") or "").strip().lower() == "buncombe"
            and carries_claim(d))


_DEATH_TOKENS = re.compile(r"\(\s*HEIRS?\s*\)|\bHEIRS?\s+OF\b|\bHEIRS?\b|\bESTATE\s+OF\b|"
                           r"\bEST\s+OF\b|\bESTATE\b|\bEST\b|\bDECEASED\b|\bDEC'?D\b", re.I)
_TRAILING_NOISE = re.compile(r"(?:\d+\s*/\s*\d+|\bET\s*(?:AL|UX|VIR)\.?|\bOF|\(LE\))\s*$", re.I)
_AKA = re.compile(r"\s+(?:A/K/A|AKA|F/K/A|FKA|N/K/A)\b.*$", re.I)
_QUOTED = re.compile(r"[\"“”][^\"“”]{1,20}[\"“”]|(?<![A-Za-z])'[A-Za-z .]{1,20}'(?![A-Za-z])")
_JUNK = re.compile(r"\b(?:DECEASED|SAID|EXHIBIT|CREDITORS?|NOTICE|EXECUT(?:OR|RIX)|"
                   r"ADMINISTRAT(?:OR|RIX)|QUALIFIED|COUNTY|STATE|UNDERSIGNED|PERSONS?|"
                   r"CLAIMS?|CEMETERY|CHURCH|UNKNOWN)\b", re.I)
_ESTATE_OF = re.compile(r"\b(?:Estate\s+of|claims\s+against)\s+(?:the\s+estate\s+of\s+)?"
                        r"(?:the\s+(?:late\s+|deceased\s+)?)?"
                        r"([A-Z][A-Za-z.'’\- ]{3,60}?)(?=,|\s+a/?k/?a\b|\s+deceased\b|"
                        r"\s+late\b|\s+of\s+[A-Z][a-z]+\s+County|$)", re.I)
_NOTICE_TAIL = re.compile(r"\b(?:NOTICE\s+TO\s+CREDITORS|CREDITOR'?S\s+NOTICE)\b.*$", re.I)
#: a death word in a roll / owner string (HEIR, HEIRS, ESTATE, EST OF); a surname that merely
#: contains the letters ("...HEIR..." inside a name) is not one
_ROLL_DEATH = re.compile(r"\bHEIRS?\b|\bESTATE\b|\bEST\s+OF\b", re.I)

Person = tuple   # (LAST, FIRST, MIDDLE-INITIAL or "")


_ROLE_PAREN = re.compile(r"\(\s*(?:HEIRS?|ESTATE|EST)?\s*\)", re.I)
#: Buncombe's surname-first heirs line: "NIX (HEIRS) WILLIAM EDWARDS", and the heir_names entry
#: the scraper derives from it with the token stripped, "GRAHAM ( ) LULA M"
_SURNAME_PAREN = re.compile(r"^\s*([A-Z][A-Z'\-]+)\s*\(\s*(?:HEIRS?|ESTATE|EST)?\s*\)\s+([A-Z].*)$")


def clean_name(s: Any) -> str:
    """A name string without death/role tokens, nicknames in quotes, a/k/a tails and noise.
    "SURNAME (HEIRS) GIVEN ..." becomes "SURNAME, GIVEN ..." (its reading order is known); a
    line naming two decedents ("A B SMITH ( ) C SMITH ( )") keeps the first."""
    t = str(s or "").replace("’", "'").replace("‘", "'")
    t = _NOTICE_TAIL.sub("", t)
    t = _AKA.sub("", t)
    t = _QUOTED.sub(" ", t)
    m = _SURNAME_PAREN.match(t)
    if m and "," not in t:
        t = f"{m.group(1)}, {_ROLE_PAREN.sub(' ', m.group(2))}"
    else:
        parts = [x for x in _ROLE_PAREN.split(t) if x.strip(" ,;")]
        t = parts[0] if parts else ""
    t = _DEATH_TOKENS.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,;")
    t = re.sub(r"^(?:OF|THE)\s+", "", t, flags=re.I)          # "HEIRS OF X" -> "OF X" -> "X"
    t = re.sub(r",?\s*\b(?:JR|SR|II|III|IV)\b\.?\s*$", "", t, flags=re.I)   # "X, SR." (suffix_of keeps it)
    t = _TRAILING_NOISE.sub("", t).strip(" ,;")
    return re.sub(r"\s+", " ", t).strip(" ,;")


def candidates(name: Any) -> list[Person]:
    """The readings of one person's name, best first: a comma = LAST, FIRST; Title Case = FIRST
    [MIDDLE] LAST; ALL CAPS = FIRST ... LAST, then surname-first. Empty for junk, an entity, or
    a name without a two-letter first name and surname."""
    s = clean_name(str(name or "").split(";")[0])
    if not s or _JUNK.search(s):
        return []
    out: list[Person] = []
    if "," in s:
        p = F.person_parts(s)
        out = [p] if p else []
    elif re.search(r"[a-z]", s):
        p = F.person_parts(s, surname_first_caps=False)
        out = [p] if p else []
    else:
        for sfc in (False, True):
            p = F.person_parts(s, surname_first_caps=sfc)
            if p and p not in out:
                out.append(p)
    return out


def _probate_name(raw: dict) -> Optional[str]:
    for k in ("probate", "estate"):
        b = raw.get(k)
        if isinstance(b, dict) and str(b.get("decedent") or "").strip():
            return str(b["decedent"]).split(";")[0]
    return None


def decedent_of(row: Any) -> Optional[dict]:
    """{'field', 'raw', 'persons': [Person, ...]} for the first source that names a usable
    decedent (module docstring, THE DECEDENT), or {'field', 'raw', 'persons': []} for the best
    name that could not be read (initials only), or None when the row names nobody."""
    from ...signal_freshness import owner_names_a_death
    d = _d(row)
    raw = _raw(d)
    tried: list[tuple[str, str]] = []
    pn = _probate_name(raw)
    if pn:
        tried.append(("probate.decedent", pn))
    ob = raw.get("obituary")
    if isinstance(ob, dict) and ob.get("decedent"):
        tried.append(("obituary.decedent", str(ob["decedent"])))
    he = raw.get("heir_estate") if isinstance(raw.get("heir_estate"), dict) else {}
    for h in he.get("heir_names") or []:
        if isinstance(h, dict) and h.get("role") in ("heir", "estate") and h.get("name"):
            tried.append(("heir_estate.heir_names", str(h["name"])))
            break
    oor = str(he.get("owner_of_record") or "")
    for seg in oor.split(";"):
        if _DEATH_TOKENS.search(seg):
            tried.append(("heir_estate.owner_of_record", seg))
            break
    for k in ("owner_name", "defendant"):
        if owner_names_a_death(d.get(k)):
            tried.append((k, str(d.get(k))))
    lt = d.get("listing_type")
    if lt == "probate_notice":
        for k in ("defendant", "owner_name"):
            if d.get(k):
                tried.append((k, str(d.get(k))))
        m = _ESTATE_OF.search(str(d.get("description") or ""))
        if m:
            tried.append(("description", m.group(1)))
    best = None
    for field, val in tried:
        ps = candidates(val)
        if ps:
            return {"field": field, "raw": val, "persons": ps}
        if best is None and clean_name(val) and not _JUNK.search(clean_name(val)):
            best = {"field": field, "raw": val, "persons": []}
    return best


def roll_only_without_death_word(row: Any) -> bool:
    """The row's only claim is an heir-roll block (raw.heir_estate) whose roll string and heir
    entries carry no death word at all: no HEIR/HEIRS/ESTATE/EST OF token, no role heir/estate
    entry, and nothing else on the row names a death (no real probate block, no obituary, not a
    probate notice, no owner / defendant naming a death). On the 10/6 board these are the
    scraper's pre-word-boundary substring matches ("...HEIR..." inside a surname, match="heirs")."""
    from ...signal_freshness import has_real_probate, owner_names_a_death
    d = _d(row)
    raw = _raw(d)
    he = raw.get("heir_estate")
    if not isinstance(he, dict) or not he.get("owner_of_record"):
        return False
    if _ROLL_DEATH.search(str(he.get("owner_of_record"))):
        return False
    if any(isinstance(h, dict) and (h.get("role") in ("heir", "estate")
                                    or _ROLL_DEATH.search(str(h.get("raw") or "")))
           for h in he.get("heir_names") or []):
        return False
    if (d.get("listing_type") == "probate_notice" or has_real_probate(raw.get("probate"))
            or has_real_probate(raw.get("estate")) or isinstance(raw.get("obituary"), dict)
            or owner_names_a_death(d.get("owner_name")) or owner_names_a_death(d.get("defendant"))):
        return False
    return True


def case_identity(row: Any) -> Optional[str]:
    """The estate claim this row makes, hashed (core.case_id "estate:<16 hex>"; the ledger is
    public): state + county + the decedent's last and first name SORTED (reading-order free),
    else the unreadable name's letters, else the estate file number, else the source's claim.
    None for a row this verifier does not cover. Works on a board dict and a models.Listing."""
    d = _d(row)
    if not applies(d):
        return None
    st, co = str(d.get("state") or "").upper(), str(d.get("county") or "").lower()
    dec = decedent_of(d)
    if dec and dec["persons"]:
        p = dec["persons"][0]
        return case_id("estate", st, co, *sorted([F.surname_key(p[0]), p[1]]))
    if dec and dec.get("raw"):
        letters = re.sub(r"[^A-Z]", "", clean_name(dec["raw"]).upper())
        if letters:
            return case_id("estate", st, co, "name", letters)
    if str(d.get("case_number") or "").strip():
        return case_id("estate", st, co, "case", d.get("case_number"))
    return case_id("estate", st, co, "src", d.get("source"), d.get("listing_type"))


# --------------------------------------------------------------------------------------------
# the claim's dates (pure)
# --------------------------------------------------------------------------------------------

_ESTATE_CASE = re.compile(r"^\s*(\d{2})\s*E\s*0*\d+", re.I)


def _pub_date(v: Any) -> Optional[date]:
    d = F.to_date(v)
    if d:
        return d
    try:
        return parsedate_to_datetime(str(v)).date() if v else None
    except (TypeError, ValueError, IndexError):
        return None


def claim_of(row: Any) -> dict:
    """What the row claims, from the row alone: kind, the estate file's year, the dates by which
    the claim says the person was dead (death_by = the earliest of them), whether the claim is
    the county roll's own heirs title. No names."""
    d = _d(row)
    raw = _raw(d)
    out: dict[str, Any] = {"listing_type": d.get("listing_type"), "source": d.get("source")}
    dates: dict[str, str] = {}
    m = _ESTATE_CASE.match(str(d.get("case_number") or ""))
    if m:
        out["case_kind"] = "E"
        out["case_year"] = 2000 + int(m.group(1))
        dates["case_year_end"] = f"{out['case_year']}-12-31"
    ob = raw.get("obituary") if isinstance(raw.get("obituary"), dict) else {}
    pd = _pub_date(ob.get("pub_date"))
    if pd:
        dates["obituary_published"] = pd.isoformat()
    fs = F.to_date(d.get("first_seen"))
    if fs:
        dates["first_seen"] = fs.isoformat()
    out["dates"] = dates
    ds = [date.fromisoformat(v) for v in dates.values()]
    out["death_by"] = min(ds).isoformat() if ds else None
    he = raw.get("heir_estate") if isinstance(raw.get("heir_estate"), dict) else {}
    out["heir_roll"] = bool(he.get("owner_of_record"))
    out["heir_names"] = len([h for h in he.get("heir_names") or [] if isinstance(h, dict)])
    return out


# --------------------------------------------------------------------------------------------
# the DEATHS index (pure)
# --------------------------------------------------------------------------------------------

_VALID = re.compile(r"DEATHS\s*</strong>\s*Valid From\s*<strong>\s*([\d/]+)\s*</strong>\s*Thru\s*"
                    r"<strong>\s*([\d/]+)", re.I)
_YEAR_CELL = re.compile(r"(?:\*\*|\d{1,2})/(?:\*\*|\d{1,2})/(\d{4})")


def parse_deaths(text: str) -> dict:
    """foreclosure_rod_buncombe.parse_grid on a DEATHS result page, plus each record's year
    (the vendor masks the day and month: "**/**/2023") and the index's valid-thru date."""
    g = F.parse_grid(text)
    years: list[Optional[int]] = []
    from selectolax.parser import HTMLParser
    grid = HTMLParser(text or "").css_first(f"table#{F._GRID_ID}")
    if grid is not None:
        for tr in grid.css("tr"):
            if (tr.attributes.get("class") or "") not in ("cottPagedGridViewRowStyle",
                                                          "cottPagedGridViewAltRowStyle"):
                continue
            tds = [c for c in tr.iter() if c.tag == "td"]
            cell = tds[1].text(separator=" ", strip=True) if len(tds) > 1 else ""
            m = _YEAR_CELL.search(cell)
            years.append(int(m.group(1)) if m else None)
    for i, doc in enumerate(g["docs"]):
        y = years[i] if i < len(years) else None
        doc["year"] = y or (int(doc["date"][:4]) if doc.get("date") else None)
    vm = _VALID.search(text or "")
    if vm:
        thru = F.to_date(vm.group(2))
        g["valid_thru"] = thru.isoformat() if thru else None
    return g


_SFX = re.compile(r"\b(JR|SR|II|III|IV)\b\.?", re.I)


def suffix_of(name: Any) -> Optional[str]:
    """The generational suffix of a name string (JR / SR / II / III / IV), or None."""
    m = _SFX.search(re.sub(r"/.*$", "", str(name or "")))
    return m.group(1).upper() if m else None


def rod_party(name: Any) -> tuple[Optional[Person], bool]:
    """(LAST, FIRST, MI) of an ROD party and whether it carries an estate marker ("SMITH, JOHN
    ESTATE", "SMITH, JOHN DECD", "SMITH, JOHN BY EXR"); the trustee/agent part after "/" and the
    marker are dropped before reading the name. A wife indexed under her husband's name
    ("COOK, SAMUEL D MRS", read live on the DEATHS index) is not that person: None."""
    n = re.sub(r"/.*$", "", str(name or "")).strip()
    if re.search(r"\bMRS\b", n, re.I):
        return None, False
    marker = bool(re.search(r"\b(?:ESTATE|EST|DECD|DECEASED|HEIRS?|EXR|EXECUT(?:OR|RIX)|ADMR|"
                            r"ADMINISTRAT(?:OR|RIX)|PERS(?:ONAL)? REP)\b", n, re.I))
    n = re.sub(r"\b(?:ESTATE|EST|DECD|DECEASED|HEIRS?|BY|EXR|EXECUT(?:OR|RIX)|ADMR|"
               r"ADMINISTRAT(?:OR|RIX)|PERS(?:ONAL)?|REP)\b", " ", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" ,")
    if "," not in n:
        return None, marker
    return F.person_parts(n), marker


def relation(a: Optional[Person], b: Optional[Person], a_sfx: Optional[str] = None,
             b_sfx: Optional[str] = None) -> str:
    """foreclosure_rod_buncombe.name_relation: 'agrees' | 'unverified' | 'conflict' | 'none';
    two different generational suffixes (JR vs SR) are two people: 'conflict'."""
    r = F.name_relation(a, b)
    if r in ("agrees", "unverified") and a_sfx and b_sfx and a_sfx != b_sfx:
        return "conflict"
    return r


def death_match(grid: dict, subject: Person, claim: dict, subject_sfx: Optional[str] = None) -> dict:
    """Which DEATHS records are the subject's (module docstring, CHECK 1). Returns the public
    summary: match, basis, the record's year and book/page, the identity (initials + verdict),
    counts of same-name records."""
    death_by = F.to_date(claim.get("death_by"))
    cy = claim.get("case_year")
    keep: list[tuple[str, dict, Person]] = []
    conflicts = 0
    implausible = 0
    as_parent = 0
    for doc in grid.get("docs") or []:
        if "grantor" not in (doc.get("matched_side") or ""):
            if doc.get("matched"):
                as_parent += 1       # the searched name is a parent on someone else's record
            continue
        best: Optional[tuple[str, Person]] = None
        best_sfx: Optional[str] = None
        for nm in doc.get("matched") or []:
            if nm not in (doc.get("grantors") or []):
                continue
            p, _ = rod_party(nm)
            r = relation(subject, p, subject_sfx, suffix_of(nm))
            if r == "none":
                continue
            if r == "conflict":
                conflicts += 1
                continue
            if best is None or (best[0] == "unverified" and r == "agrees"):
                best, best_sfx = (r, p), suffix_of(nm)
        if best is None:
            continue
        y = doc.get("year")
        if y and ((death_by and y > death_by.year)
                  or (cy and y < cy - DEATH_BEFORE_CASE_YEARS)):
            implausible += 1
            continue
        keep.append((best[0], doc, best[1], best_sfx))
    out: dict[str, Any] = {"records": len(grid.get("docs") or []), "same_name": len(keep),
                           "other_middle": conflicts}
    if implausible:
        out["outside_claim_dates"] = implausible
    if as_parent:
        out["named_as_parent"] = as_parent
    agrees = [k for k in keep if k[0] == "agrees"]
    pick = agrees if len(agrees) == 1 else (keep if len(keep) == 1 else None)
    basis = None
    if pick is None and subject_sfx and len(agrees) > 1:
        # "W T SMITH JR": among several agreeing records, the one with the same suffix
        same = [k for k in agrees if k[3] == subject_sfx]
        if len(same) == 1:
            pick, basis = same, "middle_and_suffix_agree"
    if not keep:
        out["match"] = "conflict_only" if conflicts else "not_found"
        return out
    if pick is None:
        out["match"] = "ambiguous"
        return out
    verdict, doc, p, _ = pick[0]
    out.update({"match": "matched",
                "basis": basis or ("middle_agrees" if verdict == "agrees" else "first_last"),
                "recorded_year": doc.get("year"), "recorded": doc.get("date"),
                "book_page": doc.get("bp"),
                "identity": {"subject": F.initials(subject), "record": F.initials(p),
                             "middle": verdict}})
    return {k: v for k, v in out.items() if v not in (None, "")}


# --------------------------------------------------------------------------------------------
# the owner of record against the decedent (pure)
# --------------------------------------------------------------------------------------------

def owner_relation(owner: Any, dec: Person, others: list[Person]) -> dict:
    """{'relation': titled_to_decedent | heirs_of_record | heirs_of_other | family | entity |
    unrelated | none, 'co_owners': n, 'person': the reading of the decedent the owner field
    confirms (or None)}. `others`: the care-of / personal representative, whose surname makes
    an owner family too."""
    from ...name_normalize import is_entity
    s = str(owner or "").strip()
    if not s:
        return {"relation": "none", "co_owners": 0, "person": None}
    segs = [x.strip() for x in s.split(";") if x.strip()]
    best = None
    heirs_other = False
    surnames = {F.surname_key(dec[0])} | {F.surname_key(o[0]) for o in others if o}
    family = False
    for seg in segs:
        death = bool(_DEATH_TOKENS.search(seg))
        reads = []
        base = clean_name(seg)
        for sfc in (True, False):           # the layer is surname-first; heirs lines are not
            p = F.person_parts(base, surname_first_caps=sfc) if base else None
            if p and p not in reads:
                reads.append(p)
        hit = next((p for p in reads if relation(dec, p) in ("agrees", "unverified")), None)
        if hit:
            rel = "heirs_of_record" if death else "titled_to_decedent"
            if best is None or (best[0] == "titled_to_decedent" and rel == "heirs_of_record"):
                best = (rel, hit)
            continue
        if death and reads:
            heirs_other = True
        if any(F.surname_key(p[0]) in surnames for p in reads):
            family = True
    if best:
        rel, person = best
    elif heirs_other:
        rel, person = "heirs_of_other", None
    elif family:
        rel, person = "family", None
    elif is_entity(s):
        rel, person = "entity", None
    else:
        rel, person = "unrelated", None
    return {"relation": rel, "co_owners": len(segs), "person": person}


def other_parties(row: Any) -> list[Person]:
    """The care-of and the personal representative, read as people (for the family test)."""
    raw = _raw(_d(row))
    out = []
    he = raw.get("heir_estate") if isinstance(raw.get("heir_estate"), dict) else {}
    pr = raw.get("probate") if isinstance(raw.get("probate"), dict) else {}
    for v in (he.get("care_of"), pr.get("personal_representative")):
        out += candidates(v)[:2]
    return out


# --------------------------------------------------------------------------------------------
# the decision (pure)
# --------------------------------------------------------------------------------------------

PERSONAL_ACTS = {"DEED", "DEED OF TRUST", "QUIT CLAIM DEED", "GIFT", "EASEMENT",
                 "RIGHT OF WAY", "AGREEMENT", "LEASE", "MEMORANDUM", "POWER OF ATTORNEY"}
OUT_DEEDS = {"DEED", "QUIT CLAIM DEED", "GIFT", "EXECUTORS DEED", "EXECUTOR DEED",
             "ADMINISTRATORS DEED", "ESTATE DEED", "DEED OF DISTRIBUTION"}


def _consideration(a: dict) -> bool:
    try:
        return float(a.get("Stamps") or 0) > 0 or float(a.get("SalePrice") or 0) > 0
    except (TypeError, ValueError):
        return False


def _grantees_unrelated(doc: dict, dec: Person) -> bool:
    ge = doc.get("grantees") or []
    if not ge:
        return False
    sk = F.surname_key(dec[0])
    for g in ge:
        p, _ = rod_party(g)
        last = F.surname_key(p[0] if p else re.split(r"[ ,]", str(g).strip())[0])
        if last == sk:
            return False
    return True


def _dec_parties(doc: dict, dec: Person, side: str, sfx: Optional[str] = None
                 ) -> list[tuple[str, bool]]:
    """(identity verdict, estate marker) of each matched party on `side` that is the decedent
    (`sfx`: the decedent's generational suffix, when the board name carries one)."""
    pool = doc.get("grantors") if side == "grantor" else doc.get("grantees")
    out = []
    for nm in doc.get("matched") or []:
        if nm not in (pool or []):
            continue
        p, marker = rod_party(nm)
        r = relation(dec, p, sfx, suffix_of(nm))
        if r in ("agrees", "unverified"):
            out.append((r, marker))
    return out


def _pub(doc: dict, ties: dict, ident: Optional[str] = None, marker: bool = False) -> dict:
    out = F._doc_pub(doc, ties, ident)
    if marker:
        out["estate_marker"] = True
    return out


def decide(claim: dict, parcel: Optional[dict], dec: Person, death: dict,
           chain: Optional[dict], *, others: list[Person], today: date,
           sfx: Optional[str] = None) -> tuple[str, dict]:
    """The verdict (module docstring, VERDICTS) from what was fetched. `death`: death_match()'s
    summary (or {'match': 'not_checked', ...}); `chain`: {'grid', 'complete', 'narrowed'} of
    the decedent's CRP search, {'error'} or None when not searched."""
    ev: dict[str, Any] = {}
    if parcel is None:
        ev["reason"] = "no_property_identity"
        return "unconfirmed", ev
    a = parcel
    rel = owner_relation(a.get("owner"), dec, others)
    ev["owner_relation"] = rel["relation"]
    if rel["co_owners"] > 1:
        ev["owner_co_owners"] = rel["co_owners"]
    vest = F.bp_key(a.get("DeedBook"), a.get("DeedPage"))
    vdate = F.to_date(a.get("DeedDate"))
    consideration = _consideration(a)
    transfer: dict[str, Any] = {"vesting_deed": vest,
                                "vesting_date": vdate.isoformat() if vdate else None,
                                "vesting_instrument": a.get("Instrument") or None,
                                "consideration": consideration}
    death_year = death.get("recorded_year") if death.get("match") == "matched" else None
    # "after the death": on or after the record's own date when the index shows one, else from
    # the next January (the vendor masks most dates to the year: a deed in the same year may
    # precede the death and is "timing unclear")
    death_date = F.to_date(death.get("recorded")) if death_year else None
    after_death = death_date or (date(death_year + 1, 1, 1) if death_year else None)
    death_by = F.to_date(claim.get("death_by"))

    docs = (chain or {}).get("grid", {}).get("docs") or [] if chain and not chain.get("error") else []
    complete = bool(chain and not chain.get("error") and chain.get("complete")
                    and not chain.get("narrowed"))
    if chain is not None:
        transfer["chain"] = ({"searched": True, "results": len(docs), "complete": complete}
                             if not chain.get("error") else
                             {"searched": False, "reason": chain.get("error")})
    ties = F.tie_docs(docs, a) if docs else {}
    strong = {bp for bp, t in ties.items() if t.get("strength") == "strong"}

    def finish(verdict: str, category: str, **kw: Any) -> tuple[str, dict]:
        transfer["category"] = category
        ev["transfer"] = {k: v for k, v in transfer.items() if v not in (None, "", [])}
        ev.update(kw)
        return verdict, ev

    # ---- (R2) the "decedent" acted on this parcel after the claim says they were dead -------
    if death.get("match") in ("not_found", "conflict_only") and complete and death_by:
        cutoff = death_by + timedelta(days=ACTED_AFTER_DAYS)
        for doc in sorted(docs, key=lambda x: x.get("date") or "", reverse=True):
            dd = F.to_date(doc.get("date"))
            if not dd or dd < cutoff or doc.get("type") not in PERSONAL_ACTS:
                continue
            if doc.get("bp") not in strong and doc.get("bp") != vest:
                continue
            ps = _dec_parties(doc, dec, "grantor", sfx)
            if any(r == "agrees" and not mk for r, mk in ps):
                return finish("refuted", "decedent_acted_after_death_claim",
                              decided_by="decedent_acted_after_death_claim",
                              deciding=[_pub(doc, ties, "agrees")])

    # ---- the county still titles the parcel to the decedent / the heirs ------------------------
    if rel["relation"] in ("titled_to_decedent", "heirs_of_record"):
        # (D) a deed out the county layer has not caught up with
        after = after_death
        for doc in sorted(docs, key=lambda x: x.get("date") or "", reverse=True):
            dd = F.to_date(doc.get("date"))
            if (not dd or doc.get("type") not in OUT_DEEDS or doc.get("bp") not in strong
                    or doc.get("bp") == vest or (today - dd).days > LAYER_LAG_DAYS
                    or (vdate and dd <= vdate)):
                continue
            ps = _dec_parties(doc, dec, "grantor", sfx)
            if not ps or not _grantees_unrelated(doc, dec):
                continue
            estate = any(mk for _, mk in ps)
            if estate or (after and dd >= after):
                return finish("stale", "conveyed_out", decided_by="deed_out_not_yet_on_layer",
                              deciding=[_pub(doc, ties, ps[0][0], estate)])
        if death.get("match") == "matched":
            return finish("confirmed", rel["relation"], decided_by="death_record_and_" + rel["relation"])
        ev["reason"] = {"ambiguous": "death_record_ambiguous",
                        "conflict_only": "death_record_not_found",
                        "not_found": "death_record_not_found"}.get(death.get("match"),
                                                                    "death_record_not_checked")
        return finish("unconfirmed", rel["relation"])

    if rel["relation"] == "heirs_of_other":
        ev["reason"] = "parcel_heirs_of_other_person"
        return finish("unconfirmed", "heirs_of_other")
    if rel["relation"] == "family":
        ev["reason"] = "owner_shares_decedent_surname"
        return finish("unconfirmed", "family")

    # ---- an unrelated owner (a person or an entity) -------------------------------------------
    vest_doc = next((x for x in docs if x.get("bp") == vest and vest), None)
    out_parties = _dec_parties(vest_doc, dec, "grantor", sfx) if vest_doc else []
    if vest_doc is not None and out_parties:
        ident, marker = out_parties[0][0], any(mk for _, mk in out_parties)
        unrelated = _grantees_unrelated(vest_doc, dec)
        dpub = _pub(vest_doc, ties, ident, marker)
        if not unrelated:
            ev["reason"] = "conveyed_to_decedent_surname"
            return finish("unconfirmed", "family", deciding=[dpub])
        # (R1) the decedent sold it, alive, years before the death
        if (death_year and vdate and vdate.year <= death_year - 2 and not marker
                and complete and any(r == "agrees" and not mk for r, mk in out_parties)):
            return finish("refuted", "conveyed_before_death", decided_by="conveyed_before_death",
                          deciding=[dpub])
        # (A) out of the estate, after the death, for value
        if consideration and ((after_death and vdate and vdate >= after_death) or marker):
            return finish("stale", "conveyed_out", decided_by="vesting_deed_from_decedent_after_death",
                          deciding=[dpub])
        if not consideration:
            ev["reason"] = "conveyed_without_consideration"
            return finish("unconfirmed", "conveyed_no_consideration", deciding=[dpub])
        ev["reason"] = "conveyance_timing_unclear"
        return finish("unconfirmed", "conveyed_timing_unclear", deciding=[dpub])

    # (B) the decedent acquired the parcel; an unrelated owner took title after the death
    acq = [x for x in docs if x.get("bp") in strong and x.get("bp") != vest
           and x.get("type") in F.CONVEYANCE_TYPES and _dec_parties(x, dec, "grantee", sfx)]
    if acq and after_death and vdate and vdate >= after_death:
        if consideration:
            last_acq = sorted(acq, key=lambda x: x.get("date") or "")[-1]
            return finish("stale", "conveyed_out", decided_by="conveyed_after_death",
                          deciding=[_pub(last_acq, ties, _dec_parties(last_acq, dec, "grantee", sfx)[0][0])])
        ev["reason"] = "conveyed_without_consideration"
        return finish("unconfirmed", "conveyed_no_consideration")

    # (C) the claim is the county roll's own heirs title on this PIN, conveyed since
    fs = F.to_date((claim.get("dates") or {}).get("first_seen"))
    if claim.get("heir_roll_on_pin") and fs and vdate and vdate > fs:
        if consideration:
            return finish("stale", "conveyed_out", decided_by="conveyed_after_heirs_of_record")
        ev["reason"] = "conveyed_without_consideration"
        return finish("unconfirmed", "conveyed_no_consideration")

    ev["reason"] = "owner_unrelated_no_tie" if rel["relation"] != "entity" else "owner_entity_no_tie"
    return finish("unconfirmed", "unrelated_no_tie")


# --------------------------------------------------------------------------------------------
# heir liveness (evidence only)
# --------------------------------------------------------------------------------------------

def named_parties(row: Any, dec: Optional[Person]) -> list[tuple[str, Person, Optional[str]]]:
    """(group, person, city) for every named party the row carries: heir_names entries
    ('decedent_named' when the entry names the decedent / is role heir or estate, else
    'co_owner_named'), the care-of, the personal representative. Deduplicated by name."""
    d = _d(row)
    raw = _raw(d)
    he = raw.get("heir_estate") if isinstance(raw.get("heir_estate"), dict) else {}
    pr = raw.get("probate") if isinstance(raw.get("probate"), dict) else {}
    mail_city = _city_of(he.get("mailing"))
    prop_city = str(d.get("city") or "").strip() or None
    out: list[tuple[str, Person, Optional[str]]] = []
    seen: set = set()

    def add(group: str, val: Any, city: Optional[str]) -> None:
        ps = candidates(val)
        if not ps:
            return
        p = ps[0]
        if dec and any(relation(dec, q) in ("agrees", "unverified") for q in ps):
            p, group = dec, "decedent_named" if group != "care_of" else group
        k = (F.surname_key(p[0]), p[1])
        if k in seen:
            return
        seen.add(k)
        out.append((group, p, city))

    for h in he.get("heir_names") or []:
        if isinstance(h, dict) and h.get("name"):
            g = "decedent_named" if h.get("role") in ("heir", "estate") else "co_owner_named"
            add(g, h["name"], prop_city or mail_city)
    if he.get("care_of"):
        add("care_of", he["care_of"], mail_city)
    if pr.get("personal_representative"):
        add("personal_representative", pr["personal_representative"], None)
    return out


_CITY = re.compile(r"([A-Za-z][A-Za-z .'-]*?)\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$")


def _city_of(mailing: Any) -> Optional[str]:
    m = _CITY.search(str(mailing or "").strip())
    if not m:
        return None
    words = m.group(1).split()
    # "116 CARRIAGE PARK CT ASHEVILLE" -> the last word(s) after a street suffix
    for i in range(len(words) - 1, -1, -1):
        if words[i].upper() in F._SUFFIXES or words[i].isdigit():
            return " ".join(words[i + 1:]) or None
    return " ".join(words[-2:]) if len(words) > 1 else words[0]


async def _voter(person: Person, city: Optional[str], client) -> dict:
    """classify_voters over a statewide Registered + Removed search; elderly_disabled's
    replay/live plumbing (client.voter_search in tests; a live Fetcher's pacing otherwise)."""
    from .elderly_disabled import classify_voters
    last, first, mid = person
    search = getattr(client, "voter_search", None)
    if search is None:
        from ..fetch import Fetcher
        if not isinstance(client, Fetcher):
            return {"status": "not_checked"}
        from ...enrichment_nc_voter_lookup import nc_voter_search

        async def _pace() -> None:
            await client._pace(VOTER_HOST)
            client.requests[VOTER_HOST] += 1

        async def search(f: str, la: str, county: str) -> dict:
            res = await nc_voter_search(f, la, county, include_registered=True,
                                        include_removed=True, pace=_pace)
            if not res.get("ok"):
                client.errors[VOTER_HOST] += 1
            elif client.capture_dir:
                import json
                from urllib.parse import urlencode
                client._capture(f"https://{VOTER_HOST}/RegLkup/SearchResults?"
                                + urlencode({"first": f, "last": la, "county": county}),
                                json.dumps(res))
            return res
    try:
        res = await search(first.title(), last.title(), "ALL")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": type(exc).__name__}
    if not isinstance(res, dict) or not res.get("ok"):
        return {"status": "error"}
    return classify_voters(res.get("rows") or [], F.surname_key(last), first, mid, city)


async def heir_liveness(row: Any, dec: Optional[Person], client) -> dict:
    """{'searched': n, 'skipped': n, '<group>': {status: count}} over named_parties(); COUNTS
    only."""
    parties = named_parties(row, dec)
    out: dict[str, Any] = {"named": len(parties), "searched": 0}
    for group, person, city in parties[:MAX_VOTER_SEARCHES]:
        st = await _voter(person, city, client)
        out["searched"] += 1
        g = out.setdefault(group, {})
        s = str(st.get("status") or "error")
        g[s] = g.get(s, 0) + 1
    if len(parties) > MAX_VOTER_SEARCHES:
        out["not_searched"] = len(parties) - MAX_VOTER_SEARCHES
    return out


# --------------------------------------------------------------------------------------------
# what is published (pure)
# --------------------------------------------------------------------------------------------

_PUBLIC = ("decided_by", "reason", "claim", "decedent", "parcel", "death", "owner_relation",
           "owner_co_owners", "transfer", "deciding", "heir_liveness", "human_lane", "url",
           "error", "blocked")
_CLAIM_PUBLIC = ("listing_type", "source", "case_kind", "case_year", "death_by", "dates",
                 "heir_roll", "heir_names", "heir_roll_death_word")
_DECEDENT_PUBLIC = ("field", "initials", "readings", "order_fixed_by_owner")
_DEATH_PUBLIC = ("searched", "match", "basis", "recorded_year", "recorded", "book_page",
                 "identity", "records", "same_name", "other_middle", "outside_claim_dates",
                 "named_as_parent", "valid_thru", "complete", "reason")
_LIVENESS_STATUSES = {"active", "inactive", "removed", "not_found", "ambiguous", "error",
                      "not_checked"}


def public_evidence(verdict: str, ev: dict) -> dict:
    """The whitelist (module docstring, PRIVACY). Idempotent."""
    out = {k: ev.get(k) for k in _PUBLIC if ev.get(k) not in (None, "", [], {})}
    if isinstance(out.get("claim"), dict):
        out["claim"] = {k: out["claim"][k] for k in _CLAIM_PUBLIC
                        if out["claim"].get(k) not in (None, "", {})}
    if isinstance(out.get("decedent"), dict):
        out["decedent"] = {k: out["decedent"][k] for k in _DECEDENT_PUBLIC
                           if out["decedent"].get(k) not in (None, "")}
    if isinstance(out.get("death"), dict):
        dth = {k: out["death"][k] for k in _DEATH_PUBLIC if out["death"].get(k) not in (None, "")}
        if isinstance(dth.get("identity"), dict):
            dth["identity"] = {k: dth["identity"].get(k) for k in ("subject", "record", "middle")}
        out["death"] = dth
    if isinstance(out.get("heir_liveness"), dict):
        hl = {}
        for k, v in out["heir_liveness"].items():
            if isinstance(v, dict):
                hl[k] = {s: int(n) for s, n in v.items() if s in _LIVENESS_STATUSES}
            elif isinstance(v, int):
                hl[k] = v
        out["heir_liveness"] = hl
    if isinstance(out.get("error"), str):
        out["error"] = out["error"].split(":", 1)[0][:60]
    if verdict in ("unconfirmed", "wall"):
        out.setdefault("human_lane", HUMAN_LANE)
    return out


def _res(verdict: str, evidence: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(verdict, evidence), source=SOURCE,
                  version=VERSION, verifier=_NAME)


# --------------------------------------------------------------------------------------------
# the source
# --------------------------------------------------------------------------------------------

def death_body(last: str, first: str) -> dict:
    """rod/aumentum.py's name-search body on the DEATHS index."""
    b = F.name_body(last, first)
    b[F._P + "ddlIndexType"] = "DTH"
    return b


async def death_search(session: Any, entry_url: str, subject: Person) -> dict:
    """One DEATHS search: {'grid', 'complete'} or {'error'}; raises F.Blocked on a wall."""
    r = await session.post_form(entry_url, death_body(subject[0], subject[1]),
                                headers={"Referer": entry_url})
    why = F.check_block(r)
    if why:
        raise F.Blocked(why)
    if "v2Error.aspx" in (r.url or ""):
        return {"error": "vendor_error_page"}
    if re.search(r"allowable results|maximum number of", r.text or "", re.I):
        return {"error": "too_many_results"}
    g = parse_deaths(r.text)
    if g["count"] is None and not g["docs"]:
        return {"error": "unparseable_results"}
    return {"grid": g, "complete": g["count"] is not None and g["count"] == len(g["docs"])}


class LayerError(Exception):
    pass


async def _layer(client, url: str) -> dict:
    """One county-layer query; an ArcGIS error body ({"error": {...}}, served with HTTP 200) is
    retried once, then raised as LayerError (a fetch failure, never "no parcel")."""
    for attempt in (1, 2):
        data = await client.get_json(url)
        if isinstance(data, dict) and isinstance(data.get("features"), list):
            return data
        if attempt == 2:
            raise LayerError(str((data or {}).get("error", {}).get("code") if isinstance(data, dict) else "bad"))
    raise LayerError("unreachable")


async def find_parcel(row: dict, client) -> tuple[Optional[dict], Optional[str]]:
    """(the county layer's record, 'pin'|'address') for the row's property. A row with a
    resolvable PIN is looked up by the PIN ONLY: on Buncombe's unpaid-bill rows street_address
    can be the owner's mailing address (live 2026-10-06: a transient layer error on the PIN
    query, then the address fallback of foreclosure_rod_buncombe.find_parcel, resolved the
    mailing address's parcel). Only a row without a PIN is looked up by house number + street.
    Raises LayerError on a layer error."""
    from .tax_lien_buncombe import pin_of
    pin = pin_of(row)
    if pin:
        parcel, _ = F.parcel_from_gis(await _layer(client, F.gis_url_pin(pin)))
        return (parcel, "pin") if parcel else (None, None)
    hs = F.house_and_street(row.get("street_address"))
    if hs:
        parcel, _ = F.parcel_from_gis(await _layer(client, F.gis_url_address(*hs)))
        if parcel:
            return parcel, "address"
    return None, None


def _heir_roll_on_pin(row: dict, parcel: Optional[dict], how: Optional[str]) -> bool:
    """The claim is the county layer's own heirs title read on this PIN (nc_heir_estate_parcels
    reads property_bc_dis by `pin`)."""
    raw = _raw(row)
    if not (isinstance(raw.get("heir_estate"), dict) and parcel and how == "pin"):
        return False
    srcs = {str(row.get("source") or "")} | {str((x or {}).get("source") or "")
                                             for x in raw.get("also_seen_in") or []
                                             if isinstance(x, dict)}
    return "counties_nc.nc_heir_estate_parcels" in srcs


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    claim = claim_of(row)
    ev: dict[str, Any] = {"claim": claim, "url": F.SEARCH_URL}
    state = F._run_state(client)
    if roll_only_without_death_word(row):
        # (R0) the claim's own roll string titles nobody's heirs or estate: check the county
        # layer still shows no death word on this PIN, and refute
        claim["heir_roll_death_word"] = False
        try:
            parcel, how = await find_parcel(row, client)
        except Exception as exc:  # noqa: BLE001
            ev["reason"] = "county_layer_failed"
            ev["error"] = type(exc).__name__
            return _res("unconfirmed", ev)
        if parcel is None or how != "pin":
            ev["reason"] = "no_property_identity"
            return _res("unconfirmed", ev)
        ev["parcel"] = {"resolved_by": how, **F.parcel_summary(parcel)}
        if _ROLL_DEATH.search(str(parcel.get("owner") or "")):
            ev["reason"] = "county_shows_death_word_now"
            return _res("unconfirmed", ev)
        ev["decided_by"] = "no_death_word_on_roll"
        ev["transfer"] = {"category": "no_heirs_or_estate_title"}
        return _res("refuted", ev)
    dec = decedent_of(row)
    if not dec or not dec["persons"]:
        ev["reason"] = "no_decedent_name" if not dec else "decedent_name_unreadable"
        if dec:
            ev["decedent"] = {"field": dec["field"]}
        return _res("unconfirmed", ev)
    if state.get("blocked"):
        # the ROD challenged or blocked earlier this run: no request at all for this row
        ev["blocked"] = state["blocked"]
        ev["reason"] = "rod_blocked_earlier_this_run"
        return _res("wall", ev)
    readings = list(dec["persons"])
    sfx = suffix_of(dec["raw"])
    ev["decedent"] = {"field": dec["field"], "initials": F.initials(readings[0]),
                      "readings": len(readings)}
    others = other_parties(row)

    # the parcel (county layer), and the reading of the name the owner of record confirms
    parcel, how = None, None
    try:
        parcel, how = await find_parcel(row, client)
    except Exception as exc:  # noqa: BLE001
        ev["parcel_error"] = type(exc).__name__
    if parcel is not None:
        ev["parcel"] = {"resolved_by": how, **F.parcel_summary(parcel),
                        "board_address_agrees": F._address_agrees(row, parcel)}
        claim["heir_roll_on_pin"] = _heir_roll_on_pin(row, parcel, how)
        # the owner of record fixes the reading order only when exactly one reading is the
        # owner (a roll line that IS the claim's own text matches both readings: no help)
        hits = [p for p in readings
                if owner_relation(parcel.get("owner"), p, others)["person"] is not None]
        if len(hits) == 1:
            readings = hits + [q for q in readings if q != hits[0]]
            ev["decedent"]["order_fixed_by_owner"] = True

    death: dict[str, Any] = {"match": "not_checked"}
    chain: Optional[dict] = None
    dec_p = readings[0]
    try:
        async with client.form_session() as s:
            boot = await s.get(F.SEARCH_URL)
            why = F.check_block(boot)
            if why:
                raise F.Blocked(why)
            entry = boot.url or F.SEARCH_URL
            # the preferred reading first; the other reading of an ALL-CAPS name only when the
            # first found nothing and no owner of record fixed the order. The second replaces the
            # first only when it found the record.
            for i, p in enumerate(readings[:MAX_DEATH_SEARCHES]):
                got = await death_search(s, entry, p)
                if got.get("error"):
                    if i == 0:
                        death = {"match": "not_checked", "reason": got["error"], "searched": 1}
                    break
                dm = death_match(got["grid"], p, claim, sfx)
                dm.update({"searched": i + 1, "valid_thru": got["grid"].get("valid_thru"),
                           "complete": got["complete"]})
                if i == 0 or dm.get("match") in ("matched", "ambiguous"):
                    death, dec_p = dm, p
                else:
                    death["searched"] = i + 1
                if (dm.get("match") in ("matched", "ambiguous")
                        or ev["decedent"].get("order_fixed_by_owner")):
                    break
            if parcel is not None:
                narrow = None
                vd = F.to_date(parcel.get("DeedDate"))
                if vd:
                    narrow = vd - timedelta(days=366)
                chain = await F.rod_search(s, entry, dec_p, narrow_from=narrow, today=today)
    except F.Blocked as b:
        state["blocked"] = str(b)
        ev["blocked"] = str(b)
        ev["reason"] = "rod_blocked"
        return _res("wall", ev)
    except Exception as exc:  # noqa: BLE001
        ev["reason"] = "rod_fetch_failed"
        ev["error"] = type(exc).__name__
        ev["death"] = death
        return _res("unconfirmed", ev)
    ev["decedent"]["initials"] = F.initials(dec_p)
    ev["death"] = death
    verdict, dev = decide(claim, parcel, dec_p, death, chain, others=others, today=today,
                          sfx=sfx)
    ev.update(dev)
    if ev.get("parcel_error") and parcel is None:
        ev["reason"] = "county_layer_failed"
    ev.pop("parcel_error", None)
    try:
        ev["heir_liveness"] = await heir_liveness(row, dec_p, client)
    except Exception as exc:  # noqa: BLE001 - evidence only, never the verdict
        ev["heir_liveness"] = {"error": 1}
    return _res(verdict, ev)
