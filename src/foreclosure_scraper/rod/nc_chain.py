"""The deed chain and lien picture for one owner, built from a register's name index. Shared by the
NC platform adapters (nc_cott_v4, nc_lookup, nc_ors); each adapter supplies only a search
function that returns IndexRecords.

WHAT chain() RETURNS (the attorney's quiet-title list)
    {
      "state", "county", "platform", "owner_searched", "fetched_at",
      "status": ok | partial | not_found | walled | capped | error | no_owner_name,
      "reason": why it is not ok (wall reason, cap, error text), or None,
      "last_deed": the most recent conveyance INTO the owner, or None,
      "prior_instruments": up to `depth` earlier conveyances, newest first, found by searching each
                           grantor's name as a grantee recorded on or before the deed that followed,
      "chain_stopped": why the walk back stopped before `depth`, or None,
      "liens": {"deeds_of_trust": [...], "satisfactions": [...], "lis_pendens": [...],
                "substitutions_of_trustee": [...], "foreclosure_notices": [...], "open_deeds_of_trust_est": int,
                "since": ISO date of the last deed the counts are measured from, or None},
      "owner_instruments": how many index entries name the owner, "searches": lookups spent,
      "truncated": True when a search answered with more rows than it showed,
      "source_url": the search page a person opens to check it,
    }
    Each instrument: {recorded (YYYY-MM-DD), book, page, instrument_no, type (as indexed), kind,
                      grantors [...], grantees [...], description (when the index shows one), xref}.

HONEST LIMITS, also carried in the result
    * A name index matches names, not parcels: a namesake's instruments can appear. Every entry is
      the index's own row; the sheet should be checked against the deed images.
    * The walk back follows the grantor's NAME. It stops (and says so) at a sale officer's deed
      (trustee, commissioner, sheriff, tax), an estate deed, an entity whose earlier name is
      unknown, a name the index does not have before that date, a wall, or the lookup cap.
    * open_deeds_of_trust_est is deeds of trust minus satisfactions recorded since the last deed;
      it is an estimate, not a payoff letter.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from ..name_normalize import is_entity, owner_last_first_middle
from .inst_class import EXECUTOR_DEED, DISTRIBUTION_DEED, LOSS_CLASSES, OTHER, classify_instrument
from .models import RodDoc

# kinds
DEED = "deed"
DEED_OF_TRUST = "deed_of_trust"
SATISFACTION = "satisfaction"
LIS_PENDENS = "lis_pendens"
SUBSTITUTION = "substitution_of_trustee"
ASSIGNMENT = "assignment"
FORECLOSURE = "foreclosure_notice"
OTHER_KIND = "other"

_RX_LIS = re.compile(r"LIS\s*/?\s*P|\bL\s*/\s*P\b|\bLP\b|PENDENS")
_RX_SUB = re.compile(r"SUBST|\bS\s*/\s*T\b|\bSUB\s*/?\s*TR|\bSUB\s+TRUSTEE|\bS\s*/\s*TR\b|APPT?\.?\s*(OF\s*)?(SUB|SUCC)\w*\s*TR")
_RX_SAT = re.compile(r"SATIS|\bSAT\b|CANCEL|\bCAN\b|\bCANC\b|RELEASE|\bREL\b|CERT\s*/\s*SAT")
_RX_ASSIGN = re.compile(r"ASSIGN|\bASGM?T?\b|\bASSGN\b|\bASN\b|\bASG\b")
_RX_DOT = re.compile(r"DEED OF TRUST|\bD\s*/\s*T\b|\bDT\b|\bDOT\b|\bD OF T\b|MORTGAGE|\bMTG\b|\bMORT\b|SECURITY DEED|DOFTR")
_RX_FCL = re.compile(r"FORECLOS|\bFORCL\b|\bFCL\b|NOTICE OF (?:FORECLOSURE )?SALE|\bNOS\b|NOTICE OF HEARING|"
                     r"NOTICE OF DEFAULT")
_RX_NOT_NEW_DOT = re.compile(r"MODIF|SUBORD|AMEND|EXTEN|CORRECT|ADDEN")

#: Lookup / Online Record System category names (instType[CATEGORY][CODE]) when the county
#: publishes its code list
_CATEGORY_KIND = {"DEED": DEED, "DEED OF TRUST": DEED_OF_TRUST, "CANCELLATION": SATISFACTION,
                  "SATISFACTION": SATISFACTION}

_SALE_OFFICER = re.compile(r"\bTRUSTEE|/\s*TR\b|/\s*SUB\s*TR\b|\bSUBSTITUTE\b|\bCOMMISSIONER|\bSHERIFF|\bCLERK\b|\bTAX COLLECTOR|"
                           r"\bMASTER\b|\bEXECUT|\bADMINISTRAT|\bPERSONAL REP|\bGUARDIAN|\bESTATE OF\b|\bHEIRS\b")


def classify_kind(label: Optional[str], category: Optional[str] = None) -> str:
    """deed | deed_of_trust | satisfaction | lis_pendens | substitution_of_trustee | assignment |
    foreclosure_notice | other, from the index's own type label (full words or a vendor short code) and, when the county
    publishes one, the code's category."""
    s = re.sub(r"\s+", " ", (label or "").upper().replace("’", "'")).strip()
    cat = (category or "").upper().strip()
    if s and classify_instrument(s) in LOSS_CLASSES:
        return DEED                     # a trustee's / commissioner's / sheriff's / tax deed conveys
    if _RX_SUB.search(s) and "DEED" not in s.replace("DEED OF TRUST", ""):
        return SUBSTITUTION
    if _RX_LIS.search(s):
        return LIS_PENDENS
    if _RX_FCL.search(s):
        return FORECLOSURE
    if cat in _CATEGORY_KIND:           # the county's own code list says what the code is
        kind = _CATEGORY_KIND[cat]
        if kind == DEED_OF_TRUST and _RX_NOT_NEW_DOT.search(s):
            return OTHER_KIND
        return kind
    if _RX_SAT.search(s):
        return SATISFACTION
    if _RX_ASSIGN.search(s):
        return ASSIGNMENT
    if _RX_DOT.search(s) and not _RX_NOT_NEW_DOT.search(s):
        return DEED_OF_TRUST
    if classify_instrument(s) != OTHER:
        return DEED
    if s in ("D", "WD", "QD", "QCD", "GD", "SWD", "DB", "CD", "TD", "ED", "EXD", "D/D"):
        return DEED
    return OTHER_KIND


@dataclass
class IndexRecord:
    """One entry of a register's name index, the same shape for every platform."""
    recorded: Optional[str] = None            # ISO YYYY-MM-DD; None when the index masks the date
    book: Optional[str] = None
    page: Optional[str] = None
    instrument_no: Optional[str] = None
    doc_type: str = ""                         # as the index shows it
    category: Optional[str] = None             # the county's own code category, when published
    description: Optional[str] = None
    grantors: list[str] = field(default_factory=list)
    grantees: list[str] = field(default_factory=list)
    xref: Optional[str] = None                 # the instrument this one refers to, when indexed
    index_code: Optional[str] = None

    @property
    def kind(self) -> str:
        return classify_kind(self.doc_type, self.category)

    @property
    def inst_class(self) -> str:
        return classify_instrument(self.doc_type)

    def key(self) -> tuple:
        return (self.book or "", self.page or "", (self.instrument_no or "").upper(), self.recorded or "",
                self.doc_type.upper())

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("category", None)
        d.pop("index_code", None)
        d["type"] = d.pop("doc_type")
        d["kind"] = self.kind
        if d["kind"] == DEED and self.inst_class not in (OTHER, "DEED"):
            d["inst_class"] = self.inst_class
        return {k: v for k, v in d.items() if v not in (None, "", [])}


@dataclass
class SearchResult:
    records: list[IndexRecord] = field(default_factory=list)
    status: str = "ok"                         # ok | walled | capped | error | too_many
    reason: Optional[str] = None
    total: Optional[int] = None                # what the register says it found, when it says
    truncated: bool = False                    # the register found more than it showed
    url: str = ""


def mdy_to_iso(s: Optional[str]) -> Optional[str]:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None


def iso_to_mdy(s: Optional[str]) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    return f"{m.group(2)}/{m.group(3)}/{m.group(1)}" if m else ""


def merge_records(records: list[IndexRecord]) -> list[IndexRecord]:
    """One record per instrument: rows of the same instrument (one per party on some platforms)
    fold together, their parties unioned in order."""
    out: dict[tuple, IndexRecord] = {}
    for r in records:
        k = (r.book or "", r.page or "", (r.instrument_no or "").upper(), r.recorded or "")
        if not any(k):
            k = (id(r),)
        have = out.get(k)
        if have is None:
            out[k] = IndexRecord(**{**asdict(r), "grantors": list(r.grantors), "grantees": list(r.grantees)})
            continue
        for src, dst in ((r.grantors, have.grantors), (r.grantees, have.grantees)):
            for n in src:
                if n and n not in dst:
                    dst.append(n)
        have.description = have.description or r.description
        have.xref = have.xref or r.xref
        have.doc_type = have.doc_type or r.doc_type
    return list(out.values())


# ------------------------------------------------------------------------------------------------
# names
# ------------------------------------------------------------------------------------------------

@dataclass
class OwnerName:
    raw: str
    last: str
    first: str = ""
    middle: str = ""
    entity: bool = False

    @property
    def label(self) -> str:
        return self.last if self.entity else f"{self.last}, {self.first}".strip(", ")


def _clean_entity(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9& ]", " ", name or "").upper()
    return re.sub(r"\s+", " ", s).strip()


def parse_owner(owner: Optional[str]) -> Optional[OwnerName]:
    """The first person (or the entity) named in a board owner string, in either convention the
    board holds (county rolls SURNAME FIRST, court sources First Last)."""
    raw = (owner or "").strip()
    if not raw:
        return None
    first_part = re.split(r"[;]|\s&\s|\sAND\s", raw, maxsplit=1, flags=re.I)[0].strip()
    if is_entity(first_part) or is_entity(raw):
        ent = _clean_entity(first_part if is_entity(first_part) else raw)
        return OwnerName(raw=raw, last=ent, entity=True) if ent else None
    p = owner_last_first_middle(raw)
    if p:
        return OwnerName(raw=raw, last=p[0], first=p[1], middle=p[2])
    toks = re.sub(r"[^A-Za-z ]", " ", raw).upper().split()
    return OwnerName(raw=raw, last=toks[0]) if toks else None


def party_name(party: str) -> Optional[OwnerName]:
    """An index party string ('SMITH, JOHN A', 'SMITH JOHN A', 'ABC LLC') as an OwnerName. Index
    names are always surname first."""
    p = (party or "").strip()
    if not p:
        return None
    if is_entity(p):
        return OwnerName(raw=p, last=_clean_entity(p), entity=True)
    if "," in p:
        last, _, rest = p.partition(",")
        toks = re.sub(r"[^A-Za-z ]", " ", rest).upper().split()
        return OwnerName(raw=p, last=re.sub(r"[^A-Za-z]", "", last).upper(),
                         first=toks[0] if toks else "", middle=(toks[1][0] if len(toks) > 1 else ""))
    toks = re.sub(r"[^A-Za-z ]", " ", p).upper().split()
    if not toks:
        return None
    return OwnerName(raw=p, last=toks[0], first=toks[1] if len(toks) > 1 else "",
                     middle=(toks[2][0] if len(toks) > 2 else ""))


def _first_fits(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def same_party(owner: OwnerName, party: str) -> bool:
    """Whether an index party string names this owner (surname exact, given name equal or an
    initial of it; for an entity, the cleaned names equal or one begins the other)."""
    pn = party_name(party)
    if pn is None:
        return False
    if owner.entity or pn.entity:
        if not (owner.entity and pn.entity):
            return False
        a, b = owner.last, pn.last
        return a == b or a.startswith(b + " ") or b.startswith(a + " ")
    if pn.last != owner.last:
        return False
    if not owner.first:
        return True
    return _first_fits(owner.first, pn.first)


def names_owner(owner: OwnerName, names: list[str]) -> bool:
    return any(same_party(owner, n) for n in names)


def is_sale_officer(name: str) -> bool:
    return bool(_SALE_OFFICER.search((name or "").upper()))


# ------------------------------------------------------------------------------------------------
# RodDoc bridge (the shared search_by_name interface)
# ------------------------------------------------------------------------------------------------

def to_rod_doc(r: IndexRecord, state: str, county: str, platform: str) -> RodDoc:
    try:
        rec = datetime.strptime(r.recorded, "%Y-%m-%d") if r.recorded else None
    except ValueError:
        rec = None
    return RodDoc(
        county=county, state=state, doc_type=(r.doc_type or "").strip(), recorded_date=rec,
        book=r.book, page=r.page, grantor="; ".join(r.grantors) or None,
        grantee="; ".join(r.grantees) or None, instrument_no=r.instrument_no,
        notes=r.description or None,
        raw={"ki": r.doc_type, "platform": platform, "kind": r.kind, "grantors": list(r.grantors),
             "grantees": list(r.grantees), **({"xref": r.xref} if r.xref else {})},
    )


# ------------------------------------------------------------------------------------------------
# the chain
# ------------------------------------------------------------------------------------------------

#: search(name, side, date_thru_iso) -> SearchResult. side: both | grantor | grantee
SearchFn = Callable[[OwnerName, str, Optional[str]], SearchResult]

_STATUS_BLOCKING = ("walled", "capped", "error")


def _sort_key(r: IndexRecord) -> str:
    return r.recorded or ""


def _newest_deed_into(records: list[IndexRecord], who: OwnerName, *, on_or_before: Optional[str] = None,
                      exclude: Optional[tuple] = None) -> Optional[IndexRecord]:
    best = None
    for r in records:
        if r.kind != DEED or not names_owner(who, r.grantees):
            continue
        if exclude is not None and r.key() == exclude:
            continue
        if on_or_before and r.recorded and r.recorded > on_or_before:
            continue
        if best is None or _sort_key(r) > _sort_key(best):
            best = r
    return best


def _grantor_to_follow(deed: IndexRecord) -> tuple[Optional[OwnerName], Optional[str]]:
    """(the grantor whose earlier deed the walk looks for, or None and why it stops)."""
    cls = deed.inst_class
    if cls in LOSS_CLASSES:
        return None, ("the last link is a sale officer's deed (trustee, commissioner, sheriff or tax); "
                      "the prior owner is named in the deed text, not as its grantor")
    if cls in (EXECUTOR_DEED, DISTRIBUTION_DEED):
        return None, "the last link is an estate deed; the prior owner is the decedent named in the deed or estate file"
    if not deed.grantors:
        return None, "the deed has no grantor in the index"
    for g in deed.grantors:
        if is_sale_officer(g):
            continue
        pn = party_name(g)
        if pn is not None and pn.last:
            return pn, None
    return None, "every grantor on the deed is a trustee, officer or estate; follow the deed text"


def _liens(records: list[IndexRecord], owner: OwnerName, since: Optional[str]) -> dict:
    out: dict = {"deeds_of_trust": [], "satisfactions": [], "lis_pendens": [], "substitutions_of_trustee": [],
                 "foreclosure_notices": []}
    bucket = {DEED_OF_TRUST: "deeds_of_trust", SATISFACTION: "satisfactions", LIS_PENDENS: "lis_pendens",
              SUBSTITUTION: "substitutions_of_trustee", FORECLOSURE: "foreclosure_notices"}
    for r in sorted(records, key=_sort_key, reverse=True):
        b = bucket.get(r.kind)
        if not b:
            continue
        if b == "deeds_of_trust" and r.grantors and not names_owner(owner, r.grantors):
            continue                     # a deed of trust the owner took as lender, not as borrower
        out[b].append(r.to_dict())
    dots = sum(1 for r in records if r.kind == DEED_OF_TRUST and names_owner(owner, r.grantors or r.grantees)
               and (not since or (r.recorded or "") >= since))
    sats = sum(1 for r in records if r.kind == SATISFACTION and (not since or (r.recorded or "") >= since))
    out["open_deeds_of_trust_est"] = max(0, dots - sats)
    out["since"] = since
    return out


def build_chain(*, platform: str, state: str, county: str, owner_name: Optional[str], search: SearchFn,
                depth: int = 3, source_url: str = "") -> dict:
    """The quiet-title picture for one owner (see the module docstring for the shape)."""
    out: dict = {"state": state, "county": county, "platform": platform, "owner_searched": None,
                 "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "status": "ok", "reason": None, "last_deed": None, "prior_instruments": [],
                 "chain_stopped": None, "liens": None, "owner_instruments": 0, "searches": 0,
                 "truncated": False, "source_url": source_url,
                 "caveat": ("Name-index entries, not a title opinion: a namesake can appear; read the deed "
                            "images before relying on any link.")}
    owner = parse_owner(owner_name)
    if owner is None:
        out.update(status="no_owner_name", reason="no usable owner name")
        return out
    out["owner_searched"] = owner.label

    res = search(owner, "both", None)
    out["searches"] += 1
    out["truncated"] = res.truncated
    if res.status in _STATUS_BLOCKING:
        out.update(status=res.status, reason=res.reason)
        return out
    if res.status == "too_many":
        out.update(status="error", reason=res.reason or "the register found too many entries for this name")
        return out
    mine = [r for r in res.records if names_owner(owner, r.grantors) or names_owner(owner, r.grantees)]
    out["owner_instruments"] = len(mine)
    last = _newest_deed_into(mine, owner)
    out["liens"] = _liens(mine, owner, last.recorded if last else None)
    if last is None:
        out.update(status="not_found" if not mine else "partial",
                   reason=("no entry in the online index names this owner" if not mine else
                           "no deed into this owner in the online index (inherited, older than the index, "
                           "or indexed under another name)"))
        return out
    out["last_deed"] = last.to_dict()

    cur = last
    seen = {last.key()}
    for _ in range(max(0, depth)):
        who, why = _grantor_to_follow(cur)
        if who is None:
            out["chain_stopped"] = why
            break
        r2 = search(who, "grantee", cur.recorded)
        out["searches"] += 1
        out["truncated"] = out["truncated"] or r2.truncated
        if r2.status in _STATUS_BLOCKING or r2.status == "too_many":
            out["chain_stopped"] = f"search for {who.label} stopped: {r2.reason or r2.status}"
            if r2.status == "walled":
                out.update(status="partial", reason=r2.reason)
            break
        prev = _newest_deed_into(r2.records, who, on_or_before=cur.recorded, exclude=cur.key())
        if prev is None or prev.key() in seen:
            out["chain_stopped"] = (f"no earlier deed into {who.label} in the online index on or before "
                                    f"{cur.recorded or 'that date'}")
            break
        seen.add(prev.key())
        out["prior_instruments"].append(prev.to_dict())
        cur = prev
    return out
