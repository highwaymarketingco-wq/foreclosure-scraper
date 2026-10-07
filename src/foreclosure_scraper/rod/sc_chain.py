"""The deed chain and lien-existence read for one owner, from any register that can search by name.

The attorney's quiet-title intake needs, per listing:
  * lien existence: mortgages, satisfactions, lis pendens (and other liens: judgments, tax and
    mechanics liens) naming the owner;
  * the deed chain: the last deed into the owner plus up to three earlier deeds, each with
    book/page, recording date, type, grantor, grantee and the index's short description.

Every SC platform adapter (rod/publicsearch.py, rod/sc_online_record_system.py,
rod/acclaim_names.py, rod/anderson_acpass_rod.py) supplies one function, a *searcher*:

    searcher(q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]

side is "grantee", "grantor" or "both"; date_to limits to instruments recorded on or before that
day when the register can (the builder filters by date again either way). A searcher raises
sc_polite.RodWalled when the register shows a wall; build_chain records it and stops.

build_chain() is pure apart from the searcher, so it is tested with canned RodDocs. How a link is
picked (mirrors quiet_title/intake.build_chain so the two read the same way):
  1. search the owner on both sides; the latest conveyance whose GRANTEE fits the owner's name is
     the last deed;
  2. its first grantor (when the deed names three or fewer) is searched as a grantee, on or before
     that deed's date; the latest conveyance into that name is the deed before; repeat, up to
     max_prior times.
Name fit: surname equal, given name equal or an initial of it, middle initials not in conflict.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Optional

from ..name_normalize import is_entity, normalize_name, owner_last_first_middle
from .inst_class import classify_instrument, is_deed_class
from .models import RodDoc
from .sc_polite import BUDGET, LookupBudget, RodWalled, mark_walled, walled_reason

MAX_PRIOR = 3
LIST_CAP = 15

# -- names ------------------------------------------------------------------------------------
_SUFFIX = {"JR", "SR", "II", "III", "IV", "V", "ETAL", "ET", "AL", "ETUX", "UX", "ETVIR", "VIR",
           "DEC", "DECD", "DECEASED", "EST", "ESTATE", "HEIRS", "HEIR", "TR", "TRS", "TRUSTEE",
           "TRUSTEES", "TTEE", "AKA", "FKA", "NKA", "MR", "MRS", "MS", "DR"}
_TAG = re.compile(r"<[^>]+>")
_ENTITY_RX = re.compile(r"\bL\.?\s?L\.?\s?[CP]\b|\bINC\b|\bCORP|\bLTD\b|\bCOMPANY\b|\bBANK\b|\bTRUST\b|"
                        r"\bHOLDINGS?\b|\bPROPERTIES\b|\bHOMES\b|\bASSOC|\bCHURCH\b|\bPARTNERS|\bFUND\b|"
                        r"\bCREDIT UNION\b|\bMORTGAGE\b|\bCOUNTY\b|\bCITY OF\b|\bSTATE OF\b|\bAUTHORITY\b", re.I)


def looks_entity(name: str) -> bool:
    """A company, trust, bank or public body rather than a person."""
    return is_entity(name) or bool(_ENTITY_RX.search(_TAG.sub(" ", name or "")))


@dataclass(frozen=True)
class NameQuery:
    """A name to look up. term is what is typed into the register's name box."""
    display: str
    term: str
    last: str = ""
    first: str = ""
    middle: str = ""        # initial or ''
    entity: bool = False
    tokens: tuple[str, ...] = ()   # entity: identity-bearing tokens


def _clean(s: str) -> str:
    return normalize_name(_TAG.sub(" ", s or ""))


def index_parts(name: str) -> Optional[tuple[str, str, str]]:
    """(LAST, FIRST, MIDDLE-INITIAL) of a register index name: always surname first
    ('SMITH JOHN A', 'SMITH, JOHN A'), suffixes dropped."""
    raw = _TAG.sub(" ", name or "")
    if "," in raw:
        last_part, _, rest = raw.partition(",")
        last = normalize_name(last_part).replace(" ", "")
        toks = [t for t in normalize_name(rest).split() if t not in _SUFFIX]
    else:
        toks = [t for t in normalize_name(raw).split() if t not in _SUFFIX]
        if not toks:
            return None
        last, toks = toks[0], toks[1:]
    if not last or not toks:
        return None
    return last, toks[0], (toks[1][0] if len(toks) > 1 else "")


def owner_query(owner: str) -> Optional[NameQuery]:
    """A query for a board owner name (Title Case FIRST LAST or ALL-CAPS SURNAME FIRST)."""
    first_party = re.split(r";|<br\s*/?>", owner or "", maxsplit=1)[0]
    if looks_entity(first_party):
        return entity_query(first_party)
    raw = re.split(r" & | AND | \+ ", first_party, maxsplit=1, flags=re.I)[0]
    if not _clean(raw):
        return None
    p = owner_last_first_middle(raw)
    if p is None:
        return None
    last, first, mid = p
    return NameQuery(display=_clean(raw), term=f"{last} {first}", last=last, first=first, middle=mid)


def index_query(name: str) -> Optional[NameQuery]:
    """A query for a name read off the register itself (a grantor to follow back)."""
    if looks_entity(name):
        return entity_query(name)
    p = index_parts(name)
    if p is None:
        return None
    last, first, mid = p
    return NameQuery(display=_clean(name), term=f"{last} {first}", last=last, first=first, middle=mid)


_ENTITY_FORM = {"LLC", "L", "C", "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LP",
                "LLP", "LTD", "LIMITED", "PLLC", "PA", "NA", "THE"}


def entity_tokens(name: str) -> tuple[str, ...]:
    """An entity's words without its form ('LLC', 'INC', 'THE' ...): 'ABC Holdings, L.L.C.' ->
    ('ABC', 'HOLDINGS')."""
    return tuple(t for t in _clean(name).split() if t not in _ENTITY_FORM)


def entity_query(name: str) -> Optional[NameQuery]:
    toks = entity_tokens(name)
    if not toks:
        return None
    return NameQuery(display=_clean(name), term=" ".join(toks[:3]), entity=True, tokens=toks)


def name_fit(q: NameQuery, party: str) -> Optional[str]:
    """'full' | 'compatible' | None: does an index party name fit the query?"""
    if not party or not party.strip():
        return None
    if q.entity:
        pt = list(entity_tokens(party))
        if not pt:
            return None
        if tuple(pt) == q.tokens:
            return "full"
        short, long_ = (pt, list(q.tokens)) if len(pt) <= len(q.tokens) else (list(q.tokens), pt)
        if len(short) >= 2 and long_[:len(short)] == short:
            return "compatible"
        return None
    if looks_entity(party):
        return None
    p = index_parts(party)
    if p is None:
        return None
    last, first, mid = p
    if last != q.last:
        return None
    if first == q.first:
        fit = "full"
    elif (len(first) == 1 and q.first.startswith(first)) or (len(q.first) == 1 and first.startswith(q.first)):
        fit = "compatible"
    else:
        return None
    if mid and q.middle and mid != q.middle:
        return None
    if fit == "full" and mid != q.middle:
        fit = "compatible"
    return fit


def parties(s: Optional[str]) -> list[str]:
    return [p.strip() for p in re.split(r";|\|", s or "") if p.strip()]


def best_fit(q: NameQuery, names: list[str]) -> Optional[str]:
    fits = [name_fit(q, n) for n in names]
    if "full" in fits:
        return "full"
    if "compatible" in fits:
        return "compatible"
    return None


# -- instrument kinds -------------------------------------------------------------------------
_LP = re.compile(r"LIS\s*PEND|\bL\s*/\s*P\b|\bLISP\b", re.I)
_RELEASE = re.compile(r"SATISF|\bSATS?\b|SAT/|/SAT|\bRELEASE|\bREL\b|\bRELS?/|CANCEL|DISCHARGE|"
                      r"RECONVEY|TERMINAT|WITHDRAW|DISMISS", re.I)
_MORTGAGE = re.compile(r"MORTGAGE|\bMTG\b|\bMORT\b|DEED OF TRUST|\bD\s*/\s*T\b|\bDOT\b|SECURITY DEED|HELOC",
                       re.I)
_NOT_NEW_MORTGAGE = re.compile(r"ASSIGN|ASGN|\bASI\b|MODIF|SUBORD|AMEND|TRANSFER|EXTEN|CORRECT|AGREE|"
                               r"WAIVER|AFFI|ORDER|UCC|BOND|PLEDGE|MANUFACTURED", re.I)
_LIEN = re.compile(r"JUDG|\bLIENS?\b|/LIEN|LIEN/|EXECUTION|MECHANIC|TAX\s+LIEN|LIS\s+LIEN|"
                   r"\bHOA\b.*LIEN|LEVY|SEIZURE", re.I)
_NOT_REALTY = re.compile(r"AIRPLANE|AIRCRAFT|\bUCC\b|VESSEL|\bBOAT\b|MENTAL HEALTH|CHILD SUPPORT", re.I)
_NOT_CONVEYANCE = re.compile(r"DEED BOOK|BOOK - NO CHARGE|POWER OF ATTORNEY|\bP\s*/\s*ATTY\b|EASEMENT|"
                             r"RESTRICT|DECLARATION|\bPLAT\b|AFFIDAVIT|\bLEASE\b|OPTION|MEMORANDUM|"
                             r"TIME\s*SHARE|TIMESHARE|ASSIGN|^MASTER DEED$", re.I)
KINDS = ("deed", "mortgage", "satisfaction", "lis_pendens", "lis_pendens_release", "foreclosure_notice", "lien",
         "lien_release", "other")
_FCL_NOTICE = re.compile(r"NOTICE OF (?:FORECLOSURE|SALE|DEFAULT)|FORECLOSURE NOTICE", re.I)


def kind_of(doc: RodDoc) -> str:
    """deed | mortgage | satisfaction | lis_pendens | lis_pendens_release | lien | lien_release | other."""
    raw = doc.raw if isinstance(doc.raw, dict) else {}
    if raw.get("kind_hint") in KINDS:          # an adapter that knows its county's codes
        return raw["kind_hint"]
    label = " ".join(x for x in (doc.doc_type, raw.get("doc_type_label"), raw.get("doc_type_code")) if x)
    s = label.upper()
    if not s.strip() or re.search(r"\bUCC\b", s):
        return "other"
    if _LP.search(s):
        return "lis_pendens_release" if _RELEASE.search(s) else "lis_pendens"
    if _FCL_NOTICE.search(s):
        return "other" if _RELEASE.search(s) else "foreclosure_notice"
    if _RELEASE.search(s):
        if _LIEN.search(s) or re.search(r"\bTAX\b|JUDG", s):
            return "lien_release" if not _NOT_REALTY.search(s) else "other"
        if re.search(r"POWER OF ATTORNEY|\bPOA\b|P/ATTY|TRUST AGREEMENT|PARTNERSHIP", s):
            return "other"
        return "satisfaction"
    if _MORTGAGE.search(s):
        return "other" if _NOT_NEW_MORTGAGE.search(s) else "mortgage"
    if _LIEN.search(s) and not _NOT_REALTY.search(s):
        return "lien"
    if _NOT_CONVEYANCE.search(s):
        return "other"
    if is_deed_class(classify_instrument(doc.doc_type, raw.get("doc_type_code"), raw.get("doc_type_label"))):
        return "deed"
    if re.search(r"\b(QCD|WD|SWD|GWD|LWD)\b", s):
        return "deed"
    return "other"


# -- the result -------------------------------------------------------------------------------
CAVEAT = ("Name-index entries, not a title opinion: a namesake can appear; read the deed images before "
          "relying on any link.")


@dataclass
class ChainEntry:
    book: Optional[str]
    page: Optional[str]
    recorded: Optional[str]          # ISO date
    doc_type: str
    grantor: Optional[str]
    grantee: Optional[str]
    description: Optional[str] = None
    instrument_no: Optional[str] = None
    kind: str = "other"
    name_fit: Optional[str] = None
    tie: Optional[str] = None
    since_last_deed: Optional[bool] = None

    @classmethod
    def from_doc(cls, d: RodDoc, kind: Optional[str] = None) -> "ChainEntry":
        desc = d.notes
        if isinstance(d.raw, dict) and not desc:
            desc = d.raw.get("description")
        return cls(book=d.book or None, page=d.page or None,
                   recorded=d.recorded_date.date().isoformat() if d.recorded_date else None,
                   doc_type=(isinstance(d.raw, dict) and d.raw.get("doc_type_label")) or d.doc_type or "",
                   grantor=d.grantor, grantee=d.grantee,
                   description=(desc or None) and str(desc)[:200],
                   instrument_no=d.instrument_no, kind=kind or kind_of(d))

    def to_dict(self) -> dict:
        """One instrument, in the shape rod/nc_chain.py uses (type, grantors[], grantees[], ...)."""
        d = {"recorded": self.recorded, "book": self.book, "page": self.page,
             "instrument_no": self.instrument_no, "type": self.doc_type, "kind": self.kind,
             "grantors": parties(self.grantor), "grantees": parties(self.grantee),
             "description": self.description, "name_fit": self.name_fit, "tie": self.tie,
             "since_last_deed": self.since_last_deed}
        return {k: v for k, v in d.items() if v not in (None, "", [])}


class Docs(list):
    """A searcher's result list; truncated=True when the register found more than it returned."""
    truncated: bool = False


@dataclass
class ChainResult:
    state: str
    county: str
    owner_name: str
    platform: str
    owner_searched: Optional[str] = None
    last_deed: Optional[ChainEntry] = None
    prior: list[ChainEntry] = field(default_factory=list)
    mortgages: list[ChainEntry] = field(default_factory=list)
    satisfactions: list[ChainEntry] = field(default_factory=list)
    lis_pendens: list[ChainEntry] = field(default_factory=list)
    foreclosure_notices: list[ChainEntry] = field(default_factory=list)
    other_liens: list[ChainEntry] = field(default_factory=list)
    walled: bool = False
    wall_reason: Optional[str] = None
    skipped: Optional[str] = None      # 'lookup cap reached', 'county walled earlier', ...
    chain_stopped: Optional[str] = None
    owner_instruments: int = 0
    searches: int = 0
    truncated: bool = False
    source_url: str = ""
    notes: list[str] = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def stop(self, why: str) -> None:
        self.chain_stopped = why
        self.notes.append(why)

    @property
    def status(self) -> str:
        """ok | partial | not_found | walled | capped | error | no_owner_name (the rod/nc_chain.py
        statuses, so enrichment_rod_chain.py reads both states the same way)."""
        sk = self.skipped or ""
        if sk.startswith("lookup cap"):
            return "capped"
        if sk.startswith("fetch failed"):
            return "error"
        if sk.startswith("owner name"):
            return "no_owner_name"
        if self.walled:
            return "partial" if self.last_deed is not None else "walled"
        if self.owner_instruments == 0:
            return "not_found"
        if self.last_deed is None:
            return "partial"
        return "ok"

    @property
    def reason(self) -> Optional[str]:
        st = self.status
        if st == "ok":
            return None
        if self.walled:
            return self.wall_reason
        if self.skipped:
            return self.skipped
        if st == "not_found":
            return "no entry in the online index names this owner"
        return ("no deed into this owner in the online index (inherited, older than the index, or "
                "indexed under another name)")

    def lien_summary(self) -> dict:
        def since(xs):
            return sum(1 for x in xs if x.since_last_deed is not False)
        lp = [x for x in self.lis_pendens if x.kind == "lis_pendens"]
        lp_rel = [x for x in self.lis_pendens if x.kind == "lis_pendens_release"]
        return {
            "has_mortgage": bool(self.mortgages),
            "mortgages_since_last_deed": since(self.mortgages),
            "satisfactions_since_last_deed": since(self.satisfactions),
            "open_mortgages_est": max(0, since(self.mortgages) - since(self.satisfactions)),
            "lis_pendens_since_last_deed": since(lp),
            "lis_pendens_open_est": max(0, since(lp) - since(lp_rel)),
            "other_liens_since_last_deed": since([x for x in self.other_liens if x.kind == "lien"]),
        }

    def to_dict(self) -> dict:
        """The shared raw['rod_chain'] shape (rod/nc_chain.py), plus SC's other_liens and summary.
        In SC the security instrument is a mortgage: mortgages sit under liens.deeds_of_trust (the
        shared key) with kind 'mortgage'."""
        summ = self.lien_summary()
        since = self.last_deed.recorded if self.last_deed else None
        return {
            "state": self.state, "county": self.county, "platform": self.platform,
            "owner_searched": self.owner_searched, "fetched_at": self.fetched_at,
            "status": self.status, "reason": self.reason,
            "last_deed": self.last_deed.to_dict() if self.last_deed else None,
            "prior_instruments": [x.to_dict() for x in self.prior],
            "chain_stopped": self.chain_stopped,
            "liens": {"deeds_of_trust": [x.to_dict() for x in self.mortgages],
                      "satisfactions": [x.to_dict() for x in self.satisfactions],
                      "lis_pendens": [x.to_dict() for x in self.lis_pendens],
                      "substitutions_of_trustee": [],
                      "foreclosure_notices": [x.to_dict() for x in self.foreclosure_notices],
                      "other_liens": [x.to_dict() for x in self.other_liens],
                      "open_deeds_of_trust_est": summ["open_mortgages_est"],
                      "since": since, "security_instrument": "mortgage", "summary": summ},
            "owner_instruments": self.owner_instruments, "searches": self.searches,
            "truncated": self.truncated, "source_url": self.source_url, "caveat": CAVEAT,
            "notes": list(self.notes),
        }


Searcher = Callable[[NameQuery, str, Optional[date]], list[RodDoc]]


def _day(d: RodDoc) -> Optional[date]:
    return d.recorded_date.date() if d.recorded_date else None


def _key(d: RodDoc) -> tuple:
    return (d.book or "", d.page or "", d.instrument_no or "", _day(d), (d.doc_type or "").upper())


def _dedupe(docs: list[RodDoc]) -> list[RodDoc]:
    """One row per instrument; when a register lists an instrument once per party pair, the
    grantor and grantee lists are merged."""
    out: dict[tuple, RodDoc] = {}
    for d in docs:
        k = _key(d)
        if k not in out:
            out[k] = RodDoc(**{**d.__dict__})
            continue
        cur = out[k]
        for side in ("grantor", "grantee"):
            have = parties(getattr(cur, side))
            for p in parties(getattr(d, side)):
                if p not in have:
                    have.append(p)
            setattr(cur, side, "; ".join(have) or None)
    return list(out.values())


def _deeds_into(q: NameQuery, docs: list[RodDoc], on_or_before: Optional[date],
                exclude: Optional[tuple] = None) -> list[tuple[RodDoc, str]]:
    out = []
    for d in docs:
        if kind_of(d) != "deed":
            continue
        if exclude and (d.book, d.page) == exclude and d.book:
            continue
        day = _day(d)
        if on_or_before and day and day > on_or_before:
            continue
        fit = best_fit(q, parties(d.grantee))
        if fit:
            out.append((d, fit))
    out.sort(key=lambda x: (_day(x[0]) or date.min, x[0].book or "", x[0].page or ""))
    return out


def _chain_grantor(e: ChainEntry) -> tuple[Optional[str], str]:
    gs = parties(e.grantor)
    if not gs:
        return None, f"The {e.recorded or 'undated'} deed names no grantor in the index; the chain stops there."
    if len(gs) > 3:
        return None, (f"The {e.recorded} deed ({e.book}/{e.page}) has {len(gs)} grantors; which of them "
                      f"held title before needs the abstract. The chain stops there.")
    g = gs[0]
    if re.search(r"\b(MASTER IN EQUITY|SHERIFF|CLERK OF COURT|FORFEITED LAND COMMISSION|TAX COLLECTOR|"
                 r"DELINQUENT TAX)\b", g.upper()):
        return None, (f"The {e.recorded} deed ({e.book}/{e.page}) is from {g} (a forced sale); the owner "
                      f"before it is the defendant in that case, which the index does not name. The chain "
                      f"stops there.")
    return g, ""


def build_chain(searcher: Searcher, *, state: str, county: str, owner_name: str, platform: str,
                max_prior: int = MAX_PRIOR, today: Optional[date] = None) -> ChainResult:
    res = ChainResult(state=state, county=county, owner_name=owner_name, platform=platform)
    q = owner_query(owner_name)
    if q is None:
        res.skipped = "owner name not readable as a person or an entity"
        return res
    res.owner_searched = q.display
    try:
        res.searches += 1
        found = searcher(q, "both", today)
        res.truncated = bool(getattr(found, "truncated", False))
        owner_docs = _dedupe(found)
    except RodWalled as w:
        res.walled, res.wall_reason = True, w.reason
        res.notes.append(f"The register showed a wall ({w.reason}); nothing was retried.")
        return res

    mine = [d for d in owner_docs
            if best_fit(q, parties(d.grantor)) or best_fit(q, parties(d.grantee))]
    res.owner_instruments = len(mine)
    vest = _deeds_into(q, mine, today)
    if vest:
        d, fit = vest[-1]
        res.last_deed = ChainEntry.from_doc(d, "deed")
        res.last_deed.name_fit = fit
        if len(vest) > 1:
            res.notes.append(f"{len(vest) - 1} earlier deed(s) into the owner's name are in the index; the latest "
                             f"is taken as the last deed.")
    else:
        res.notes.append("No deed into the owner's name was found in the online index.")
    cut = date.fromisoformat(res.last_deed.recorded) if res.last_deed and res.last_deed.recorded else None

    buckets = {"mortgage": res.mortgages, "satisfaction": res.satisfactions,
               "lis_pendens": res.lis_pendens, "lis_pendens_release": res.lis_pendens,
               "foreclosure_notice": res.foreclosure_notices,
               "lien": res.other_liens, "lien_release": res.other_liens}
    for d in sorted(mine, key=lambda x: _day(x) or date.min, reverse=True):
        k = kind_of(d)
        if k not in buckets or len(buckets[k]) >= LIST_CAP:
            continue
        e = ChainEntry.from_doc(d, k)
        e.name_fit = best_fit(q, parties(d.grantor) + parties(d.grantee))
        day = _day(d)
        e.since_last_deed = (day >= cut) if (cut and day) else None
        buckets[k].append(e)

    cur = res.last_deed
    step = 0
    while cur is not None and step < max_prior:
        step += 1
        g, why = _chain_grantor(cur)
        if not g:
            res.stop(why)
            break
        gq = index_query(g)
        if gq is None:
            res.stop(f"The grantor name '{g}' could not be read as a person or entity; the chain stops.")
            break
        upto = date.fromisoformat(cur.recorded) if cur.recorded else None
        try:
            res.searches += 1
            found = searcher(gq, "grantee", upto)
            res.truncated = res.truncated or bool(getattr(found, "truncated", False))
            docs = _dedupe(found)
        except RodWalled as w:
            res.walled, res.wall_reason = True, w.reason
            res.stop(f"Chain step {step} stopped at a wall ({w.reason}); nothing was retried.")
            break
        except Exception as exc:  # noqa: BLE001 - a slow or failed step keeps what was found
            res.stop(f"Chain step {step}: the register did not answer the search for {g} "
                     f"({type(exc).__name__}); the chain stops there.")
            break
        cands = _deeds_into(gq, docs, upto, exclude=(cur.book, cur.page))
        if not cands:
            res.stop(f"No earlier deed into {g} was found in the online index (chain step {step}); "
                     f"older links may sit in books the online index does not reach.")
            break
        d, fit = cands[-1]
        e = ChainEntry.from_doc(d, "deed")
        e.name_fit = fit
        e.tie = f"grantee {gq.display} is the grantor of the {cur.recorded} deed ({cur.book}/{cur.page})"
        res.prior.append(e)
        cur = e
    else:
        if cur is not None and step >= max_prior:
            res.notes.append(f"The chain stops after {max_prior} earlier deeds by design.")
    return res


# -- the two entry points every adapter wraps ---------------------------------------------------
#: Per-process result cache: enrich_generic_rod (raw['rod']) and enrichment_rod_chain
#: (raw['rod_chain']) both open with the owner's both-sides search; the second one reads it from
#: here instead of the register, and does not spend a second lookup of the county's cap.
_CACHE: dict[tuple, list[RodDoc]] = {}
_CACHE_MAX = 2000


def clear_cache() -> None:
    _CACHE.clear()


class _CachingSearcher:
    """Wraps an adapter's searcher factory: a session is opened only on the first cache miss."""

    def __init__(self, platform: str, state: str, county: str, make_searcher: Callable[[], Searcher]) -> None:
        self.prefix = (platform, state.upper(), county.lower())
        self.make = make_searcher
        self.real: Optional[Searcher] = None

    def key(self, q: NameQuery, side: str, date_to: Optional[date]) -> tuple:
        return self.prefix + (q.term, side, date_to)

    def __call__(self, q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]:
        k = self.key(q, side, date_to)
        if k in _CACHE:
            return _CACHE[k]
        if self.real is None:
            self.real = self.make()
        out = self.real(q, side, date_to)
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[k] = out
        return out


def run_chain(*, platform: str, state: str, county: str, owner_name: str,
              make_searcher: Callable[[], Searcher], max_prior: int = MAX_PRIOR,
              budget: Optional[LookupBudget] = None, today: Optional[date] = None,
              source_url: str = "") -> ChainResult:
    """One chain lookup with the walled registry, the result cache and the per-county cap applied."""
    budget = budget or BUDGET
    why = walled_reason(state, county)
    if why:
        return ChainResult(state=state, county=county, owner_name=owner_name, platform=platform,
                           walled=True, wall_reason=why, skipped="county walled earlier this run")
    searcher = _CachingSearcher(platform, state, county, make_searcher)
    q = owner_query(owner_name)
    cached = q is not None and searcher.key(q, "both", today) in _CACHE
    if not cached and not budget.take(state, county):
        return ChainResult(state=state, county=county, owner_name=owner_name, platform=platform,
                           skipped=f"lookup cap reached ({budget.cap} per county per run)")
    try:
        res = build_chain(searcher, state=state, county=county, owner_name=owner_name,
                          platform=platform, max_prior=max_prior, today=today)
    except RodWalled as w:          # a wall while opening the session
        mark_walled(state, county, w.reason)
        return ChainResult(state=state, county=county, owner_name=owner_name, platform=platform,
                           walled=True, wall_reason=w.reason)
    except Exception as exc:  # noqa: BLE001 - a lookup must never kill a run
        return ChainResult(state=state, county=county, owner_name=owner_name, platform=platform,
                           skipped=f"fetch failed ({type(exc).__name__}: {str(exc)[:80]})")
    if res.walled and res.wall_reason:
        mark_walled(state, county, res.wall_reason)
    res.source_url = source_url
    return res


def run_search(*, platform: str = "", state: str, county: str, name: str,
               make_searcher: Callable[[], Searcher], max_docs: int = 50,
               budget: Optional[LookupBudget] = None) -> list[RodDoc]:
    """All instruments naming `name` on either side, newest first; [] on a wall, a cap or a failure."""
    budget = budget or BUDGET
    if walled_reason(state, county) or not name or not name.strip():
        return []
    q = owner_query(name)
    if q is None:
        return []
    searcher = _CachingSearcher(platform, state, county, make_searcher)
    if searcher.key(q, "both", None) not in _CACHE and not budget.take(state, county):
        return []
    try:
        docs = _dedupe(list(searcher(q, "both", None)))
    except RodWalled as w:
        mark_walled(state, county, w.reason)
        return []
    except Exception:  # noqa: BLE001
        return []
    docs.sort(key=lambda d: d.recorded_date or datetime.min, reverse=True)
    return docs[:max_docs]
