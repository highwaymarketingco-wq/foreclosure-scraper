"""The county-independent intake steps. An adapter answers the primitive questions; this module
decides nothing about title. It picks the deed the county cites out of the book/page entries,
walks the chain back by name search, reads the owner names, applies the full-name rule to the
death index, and builds the records-checked table.

THE CHAIN. From the deed the county cites, each step searches the register for deeds INTO that
deed's first grantor filed on or before its date (grantee side, name filter = names.name_compat),
and takes the latest. A step is shown with how it ties to the next one: always the name; and the
index-description words both entries share, if any (township, acreage, lot, plat). The tie is a
lead for the abstract, never a finding that two deeds describe the same land.
"""
from __future__ import annotations

import re
import sys
import traceback
from datetime import date
from typing import Optional

from .adapters.base import CountyAdapter
from .fetch import Walled
from .model import (DeathSearch, Instrument, IntakeResult, NameSearch, RecordCheck, TaxBill, TaxStatus,
                    utc_now)
from .names import (PersonName, clean, death_fit, is_entity, name_compat, parse_indexed, parse_roll,
                    roll_markers, roll_tokens, split_owners)
from .taxyears import interest_date

MAX_CHAIN = 3
MAX_PEOPLE = 2
_NOT_LAND = {"DTR", "DTH", "BTH", "MAR", "FIN", "PLA", "MAP", "CPL", "COR"}
_VITAL = {"DTH", "BTH", "MAR"}
#: an old index entry with no instrument code whose free-text description names something that is
#: not a deed (a court order or judgment, an easement, a lease, an agreement, a power of attorney)
_NOT_DEED_TEXT = re.compile(r"\s*(ORDER|JUDG|EASEMENT|EASE\b|R/W|RIGHT OF WAY|LEASE|AGREE|AGMT|AGRMT|CONTRACT|"
                            r"P\s*O\s*A\b|POWER OF ATT|AFFIDAVIT|AFF\b|RELEASE|SATISF|CANCEL|MAP\b|PLAT\b|"
                            r"ASSIGN|LIEN|NOTICE|CERTIF|RESOLUTION|ORDINANCE|ANNEX|OPTION|MEMO)")


# ---------------------------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------------------------

def is_conveyance(inst: Instrument) -> bool:
    """A deed (a conveyance of land), as the index labels it. Deeds of trust, powers of attorney,
    satisfactions, plats and vital records are not."""
    idx = (inst.index_code or "").upper()
    if idx in _NOT_LAND:
        return False
    desc = (inst.description or "").upper()
    m = re.match(r"\s*\[([^\]]*)\]", desc)
    if m:
        k = m.group(1)
        return "DEED" in k and "D/T" not in k and "TRUST" not in k
    if _NOT_DEED_TEXT.match(desc):
        return False
    kind = (inst.kind or "").upper()
    if kind:
        return ("DEED" in kind and not any(w in kind for w in ("TRUST", "SATISF", "RELEASE", "CANCEL"))) \
            or kind in ("D", "WD", "QCD", "WARRANTY", "QUITCLAIM")
    return idx == "DEE"


_STOP = {"ACRE", "ACRES", "AC", "DEED", "TWNP", "TS", "TRACT", "TRACTS", "PART", "PARTS", "LAND", "PROPERTY", "LOTS", "THE",
         "AND", "OF", "W/DEED", "Q/C", "NON", "WARR", "WARRANTY", "SPECIAL", "TWP", "TOWNSHIP", "PORTION",
         "ASHEVILLE", "UNIT", "NONE", "PLAT", "BOOK", "PAGE"}


def desc_marks(desc: Optional[str]) -> set[str]:
    """The words of an index description that can place an entry on land: acreage, lot, block,
    plat book/page, township, and other words of four letters or more."""
    s = re.sub(r"^\s*\[[^\]]*\]", " ", (desc or "").upper())
    s = re.sub(r"\bCRK\b", "CREEK", s)
    out: set[str] = set()
    for m in re.finditer(r"(\d*\.\d+|\d+(?:\.\d+)?)\s*(?:AC|ACRE|ACRES)\b", s):
        out.add(f"{float(m.group(1)):g} ACRES")
    for m in re.finditer(r"\b(LOT|LT|BLK|BLOCK)\s*:?\s*([A-Z0-9\-]+)", s):
        out.add(f"{'LOT' if m.group(1) in ('LOT', 'LT') else 'BLOCK'} {m.group(2)}")
    for m in re.finditer(r"\b(?:P\s*B|PL)\s*(\d+)\s*(?:/|\s+P\s+)\s*(\d+)", s):
        out.add(f"PLAT BOOK {m.group(1)}/{m.group(2)}")
    for m in re.finditer(r"\b([A-Z]+(?:\s+[A-Z]+)?)\s+(?:TWP|TWNP|TOWNSHIP)\b", s):
        words = [w for w in m.group(1).split() if w not in _STOP]
        if words:
            out.add(" ".join(words) + " TWP")
    for w in re.findall(r"[A-Z]{4,}", s):
        if w not in _STOP:
            out.add(w)
    return out


def shared_marks(a: Optional[str], b: Optional[str]) -> list[str]:
    """Marks both descriptions carry, without single words already inside a shared phrase."""
    sh = desc_marks(a) & desc_marks(b)
    phrases = [x for x in sh if " " in x]
    return sorted(x for x in sh if " " in x or not any(x in p.split() for p in phrases))


def tie_note(earlier: Instrument, later: Instrument, name: str, others: int) -> str:
    fit = {"full": "the full name agrees", "compatible": "the name agrees in part (an initial or a missing "
           "middle name)"}.get(earlier.name_fit or "", "the name agrees")
    shared = shared_marks(earlier.description, later.description)
    words = (f"Both index descriptions mention {', '.join(shared)}." if shared else
             "The two index descriptions share no words that place them on the same land; the tie is by name only.")
    more = (f" {others} other deed{'s' if others != 1 else ''} into this name filed on or before that date "
            f"{'are' if others != 1 else 'is'} in the search result; the latest is shown." if others else "")
    return (f"Grantee {name} is the grantor of the {later.date} entry ({later.book_page}); {fit}. {words}{more}")


def is_plat(inst: Instrument) -> bool:
    return (inst.index_code or "").upper() in ("PLA", "MAP", "CPL") or \
        any(w in (inst.kind or "").upper() for w in ("PLAT", "MAP"))


def chain_grantor(inst: Instrument) -> tuple[Optional[str], str]:
    """Whose earlier deed to look for: a grantor the index marks deceased (the estate's decedent:
    an heirs' or executors' deed); else the first grantor when there are at most three; else
    none (a many-party conveyance needs the abstract)."""
    gs = [g for g in inst.grantors if g.strip()]
    if not gs:
        return None, f"The {inst.date} entry names no grantor in the index; the chain stops there."
    dead = [g for g in gs if (parse_indexed(g) or PersonName("")).deceased]
    if dead:
        return dead[0], ""
    if len(gs) <= 3:
        return gs[0], ""
    return None, (f"The {inst.date} entry ({inst.book_page}) has {len(gs)} grantors and none is marked deceased "
                  f"in the index; which of them held title before needs the abstract. The chain stops there.")


def best_fit(person: PersonName, names: list[str]):
    order = {"fit": 0, "candidate": 1, "other_person": 2}
    best = None
    for n in names:
        pn = parse_indexed(n)
        if pn is None:
            continue
        f = death_fit(person, pn)
        if best is None or order[f.verdict] < order[best[0].verdict]:
            best = (f, n)
    return best


def classify_deaths(ds: DeathSearch, person: PersonName, vesting_year: Optional[int]) -> None:
    for e in ds.entries:
        if e.matched_as == "parent":
            e.fit = "parent_only"
            e.reasons = ["the searched name appears among the parents on this entry, not as the decedent"]
            continue
        b = best_fit(person, e.decedent_names)
        if b is None:
            e.fit, e.reasons = "candidate", ["the decedent name on the entry could not be read as LAST, FIRST"]
            continue
        f, used = b
        e.fit, e.reasons = f.verdict, list(f.reasons)
        others = [n for n in e.decedent_names if n != used]
        if others:
            e.observations.append("also indexed as " + "; ".join(others))
        if vesting_year and e.year and e.year < vesting_year:
            e.observations.append(f"indexed in {e.year}, before the {vesting_year} deed into the owner of record")
        for par in e.parents:
            pp = parse_indexed(par)
            if pp and pp.last in person.middles:
                e.observations.append(f"a parent on the entry ({par}) has the surname {pp.last}, the same word "
                                      f"as the middle name on the record")


def owner_people(owner: Optional[str], bill_owners: list[str], grantees: list[str]
                 ) -> list[dict]:
    """The people named as owner of record, each read as LAST, FIRST MIDDLE, with how it was read.
    Entities are listed with person=None."""
    out: list[dict] = []
    markers = roll_markers(owner)
    for s in split_owners(owner)[:MAX_PEOPLE + 1]:
        if is_entity(s):
            out.append({"roll": s, "person": None, "reading": "an entity, not a person: no death search"})
            continue
        toks = roll_tokens(s)
        hit = None
        for g in grantees:
            pn = parse_indexed(g)
            if pn and {pn.last, *pn.given} == toks:
                hit = (pn, f"read from the register's index, which writes the grantee of the deed the county cites "
                           f"as {g}; its words equal the county roll's")
                break
        if hit is None:
            gw = [w for w in re.sub(r"[(),]", " ", clean(s)).split() if w in toks]
            for bo in bill_owners:
                bw = [w for w in re.sub(r"[(),]", " ", clean(bo)).split() if w in roll_tokens(bo)]
                if set(bw) == toks and len(gw) >= 2 and gw[0] == bw[-1] and gw[0] != bw[0]:
                    pn = parse_roll(s, "last_first")
                    if pn:
                        hit = (pn, f"the county layer writes '{s}' and the tax bill writes '{bo}', so the surname "
                                   f"is {pn.last}")
                    break
        if hit is None:
            if markers:
                pn = parse_roll(s, "first_last")
                why = (f"read as FIRST ... LAST, the usual order of an heirs or estate entry on this roll ('{s}'); "
                       f"the order is not confirmed by another record")
            else:
                pn = parse_roll(s, "last_first")
                why = (f"read as LAST FIRST, the county layer's usual order ('{s}'); the order is not confirmed by "
                       f"another record")
            hit = (pn, why) if pn else None
        if hit is None:
            out.append({"roll": s, "person": None, "reading": "could not be read as a person's name"})
        else:
            out.append({"roll": s, "person": hit[0], "reading": hit[1]})
    return out


def later_summary(res: IntakeResult) -> Optional[str]:
    """Counts, by kind, of the owner-name index entries filed AFTER the deed the county cites.
    Index facts only: an entry under a compatible name may be another person's."""
    if not res.after_vesting or res.vesting is None or not res.vesting.date_iso:
        return None
    after = [r for ns in res.after_vesting for r in ns.rows if r.date_iso and r.date_iso > res.vesting.date_iso]
    c: dict[str, int] = {}
    for r in after:
        k = f"{(r.kind or '').upper()} {(r.description or '').upper()}"
        if "SUBSTITUT" in k:
            lab = "substitution of trustee"
        elif "SAT" in k or "CANCEL" in k or "RELEASE" in k:
            lab = "satisfaction or release"
        elif "D/T" in k or "DEED OF TRUST" in k or (r.index_code or "").upper() == "DTR":
            lab = "deed of trust"
        elif "ASSIGN" in k:
            lab = "assignment"
        elif "RESCISSION" in k:
            lab = "rescission"
        elif is_conveyance(r):
            lab = "deed"
        else:
            lab = "other"
        c[lab] = c.get(lab, 0) + 1
    if not after:
        return "none found under the owner's name after that deed (index name search)"
    plural = {"substitution of trustee": "substitutions of trustee", "satisfaction or release":
              "satisfactions or releases", "deed of trust": "deeds of trust", "assignment": "assignments",
              "rescission": "rescissions", "deed": "deeds", "other": "others"}
    parts = ", ".join(f"{n} {k if n == 1 else plural[k]}" for k, n in sorted(c.items(), key=lambda kv: -kv[1]))
    full = sum(1 for r in after if r.name_fit == "full")
    last = max(after, key=lambda r: r.date_iso)
    return (f"{len(after)} entries under the owner's name after {res.vesting.date} ({full} with the full name, "
            f"{len(after) - full} with the name in part, which may be another person): {parts}; the latest filed "
            f"{last.date} ({last.kind or last.index_code}, book {last.book_page})")


def tax_rows(ts: TaxStatus, today: date, state: str) -> dict:
    """The three-year table, the current bill and the older bills, as the sheet prints them."""
    by_year: dict[int, TaxBill] = {}
    for b in ts.bills:
        if b.regular and b.levy_year and b.levy_year not in by_year:
            by_year[b.levy_year] = b
    rows = []
    for y in ts.completed_years:
        b = by_year.get(y)
        rows.append(_tax_row(y, b, today, state))
    cur = _tax_row(ts.current_year, by_year.get(ts.current_year), today, state) if ts.current_year else None
    shown = set(ts.completed_years) | ({ts.current_year} if ts.current_year else set())
    older = [b for b in ts.bills if b.regular and b.levy_year and b.levy_year not in shown]
    older_open = [b for b in older if b.amount_due is None or abs(b.amount_due) > 0.004]
    other = [b for b in ts.bills if not b.regular]
    unpaid = [r for r in rows if r["state"] in ("unpaid", "unpaid (amount not shown)", "part paid")]
    total = round(sum(r["due"] for r in unpaid if r["due"] is not None), 2)
    return {"rows": rows, "current": cur, "older": older, "older_open": older_open, "other": other,
            "unpaid_years": [r["year"] for r in unpaid], "unpaid_total": total,
            "unpaid_amount_unknown": any(r["due"] is None for r in unpaid)}


def _tax_row(y: Optional[int], b: Optional[TaxBill], today: date, state: str) -> dict:
    if b is None:
        return {"year": y, "bill": None, "state": "no bill on the list", "due": None, "due_text": "",
                "billed": "", "tax": None, "interest": None, "cost": None, "total": None, "payments": "",
                "exhibit": None, "late_since": None, "owner": None}
    due = b.amount_due
    pays = b.payments
    if due is None:
        st = "unpaid (amount not shown)" if b.amount_due_text else "unknown"
    elif abs(due) < 0.005:
        st = "paid"
    elif pays:
        st = "part paid"
    else:
        st = "unpaid"
    ptxt = []
    idate = interest_date(b.levy_year, state) if b.levy_year else None
    for p in pays:
        when = p.date
        late = ""
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", p.date or "")
        if m and idate:
            d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            late = " (after interest began)" if d >= idate else " (before interest began)"
        ptxt.append(f"{p.type.title()} {when}{late}: {_m(p.total)}")
    return {"year": y, "bill": b.bill, "state": st, "due": due, "due_text": b.amount_due_text or "",
            "billed": b.billed_on or "", "tax": b.component("tax"), "interest": b.component("interest"),
            "cost": b.component("cost"), "total": b.component("total"), "payments": "; ".join(ptxt) or "none",
            "exhibit": b.exhibit, "late_since": idate.isoformat() if idate and today >= idate else None,
            "owner": b.owner, "detail_read": b.detail_read}


def _m(v: Optional[float]) -> str:
    if v is None:
        return ""
    return f"(${-v:,.2f})" if v < 0 else f"${v:,.2f}"


# ---------------------------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------------------------

def _wall(res: IntakeResult, what: str, w: Walled) -> None:
    res.walls.append(f"{what}: {w.reason} ({w.url})")


def run_intake(adapter: CountyAdapter, pin: str, today: date, *, max_chain: int = MAX_CHAIN) -> IntakeResult:
    res = adapter.result
    try:
        _run(adapter, res, pin, today, max_chain)
    except Walled as w:
        _wall(res, "a step stopped at a wall", w)
    except Exception as exc:  # noqa: BLE001 - the sheet records the failure instead of dying
        res.notes.append(f"The run stopped early on an error: {type(exc).__name__}: {str(exc)[:300]}")
        print(traceback.format_exc(limit=4), file=sys.stderr)
    res.records = records_table(res, adapter)
    res.how_to = adapter.how_to(res)
    res.sources = adapter.sources()
    res.not_established = adapter.not_established()
    for ex in res.exhibits.values():
        if ex.walled:
            res.walls.append(f"{ex.label}: {ex.wall_reason} ({ex.url})")
    res.finished = utc_now()
    return res


def _guard(res: IntakeResult, what: str, fn, default=None):
    """Run one step; a wall or an error is recorded on the sheet and the run goes on."""
    try:
        return fn()
    except Walled as w:
        _wall(res, what, w)
    except Exception as exc:  # noqa: BLE001
        res.notes.append(f"{what}: stopped on an error ({type(exc).__name__}: {str(exc)[:200]}).")
    return default


def _run(adapter: CountyAdapter, res: IntakeResult, pin: str, today: date, max_chain: int) -> None:
    p = adapter.parcel(pin)
    res.parcel = p
    if not p.found:
        res.notes.append(f"The county parcel layer returned no parcel for PIN {pin}. Nothing else was searched.")
        return
    got = _guard(res, "situs vs mailing check", lambda: adapter.parcels_at_mailing_number(p))
    if got:
        res.mailing_parcels, res.mailing_check_note = got

    res.tax = _guard(res, "tax bills", lambda: adapter.tax(p, today))
    res.roll_markers = roll_markers(p.owner)
    for b in (res.tax.bills[:3] if res.tax else []):
        for mk in roll_markers(b.owner):
            if mk not in res.roll_markers:
                res.roll_markers.append(mk)

    # the deed the county cites
    if p.deed_book and p.deed_page:
        got = _guard(res, "register book/page search", lambda: adapter.deed_at(p.deed_book, p.deed_page))
        if got:
            rows, link = got
            res.deed_rows, res.deed_link = rows, link
            same = [r for r in rows if p.deed_date and r.date_iso == p.deed_date]
            if len(same) == 1:
                res.vesting = same[0]
                res.vesting_note = (f"The entry at book {p.deed_book} page {p.deed_page} dated {same[0].date} "
                                    f"matches the county's deed date ({p.deed_date}).")
            elif len(same) > 1:
                res.vesting_note = (f"{len(same)} entries at book {p.deed_book} page {p.deed_page} carry the "
                                    f"county's deed date; none is picked.")
            else:
                res.vesting_note = (f"No entry at book {p.deed_book} page {p.deed_page} carries the county's deed "
                                    f"date ({p.deed_date or 'none on the record'}); the entries found are listed.")
            if res.vesting is not None:
                res.vesting_detail_url = _guard(res, "register Document Details",
                                                lambda: adapter.deed_detail(res.vesting))
    else:
        res.vesting_note = "The county record cites no deed book and page."
    if p.plat_book and p.plat_page:
        got = _guard(res, "register plat book/page search", lambda: adapter.plat_at(p.plat_book, p.plat_page))
        if got:
            rows, res.plat_link = got
            res.plat_rows = [r for r in rows if is_plat(r)]
            if len(rows) != len(res.plat_rows):
                k = len(res.plat_rows)
                res.notes.append(f"The plat book/page search returned {len(rows)} entries across the register's book "
                                 f"series; {k} {'is a plat or map and is' if k == 1 else 'are plats or maps and are'} "
                                 f"shown in section 2.")

    # the people on the roll
    bill_owners = [b.owner for b in (res.tax.bills if res.tax else []) if b.owner][:3]
    grantees = res.vesting.grantees if res.vesting else []
    res.owner_people = owner_people(p.owner, bill_owners, grantees)
    people = [d["person"] for d in res.owner_people if d["person"] is not None][:MAX_PEOPLE]

    # instruments under the owner's name (all dates, both sides)
    for person in people:
        ns = _guard(res, f"register name search for {person.indexed()}",
                    lambda: adapter.name_search(f"instruments naming {person.indexed()} (owner of record)", person,
                                                side="both"))
        if ns is not None:
            _filter_names(ns, person)
            res.after_vesting.append(ns)

    # the chain back from the deed the county cites
    if res.vesting is not None:
        res.chain = _guard(res, "deed chain", lambda: build_chain(adapter, res, res.vesting, max_chain), []) or []

    # deaths index
    vy = int(res.vesting.date_iso[:4]) if res.vesting and res.vesting.date_iso else None
    for d in res.owner_people:
        person = d["person"]
        if person is None or len(res.death_searches) >= MAX_PEOPLE:
            continue
        ds = _guard(res, f"deaths index for {person.indexed()}", lambda: adapter.death_search(person, d["reading"]))
        if ds is not None:
            classify_deaths(ds, person, vy)
            res.death_searches.append(ds)

    res.obituary = adapter.obituary(people)


def _filter_names(ns: NameSearch, person: PersonName) -> None:
    keep, dropped, vital = [], 0, 0
    for r in ns.rows:
        if (r.index_code or "").upper() in _VITAL:
            vital += 1
            continue
        fits = [name_compat(person, x) for x in (parse_indexed(m) for m in r.matched) if x is not None]
        fit = "full" if "full" in fits else ("compatible" if "compatible" in fits else None)
        if fit is None:
            dropped += 1
            continue
        r.name_fit = fit
        keep.append(r)
    ns.rows = keep
    ns.shown = len(keep)
    bits = []
    if dropped:
        bits.append(f"{dropped} rows dropped because the indexed name conflicts with the owner's")
    if vital:
        bits.append(f"{vital} birth, marriage or death entries left to the deaths-index section")
    ns.purpose += f" ({'; '.join(bits)})" if bits else ""


def build_chain(adapter: CountyAdapter, res: IntakeResult, start: Instrument, max_steps: int) -> list[Instrument]:
    out: list[Instrument] = []
    cur = start
    for step in range(1, max_steps + 1):
        name, why_stop = chain_grantor(cur)
        if not name:
            res.chain_note = why_stop
            break
        pn = parse_indexed(name)
        who: PersonName | str = pn if pn is not None else name
        thru = cur.date if re.match(r"\d{2}/\d{2}/\d{4}$", cur.date or "") else ""
        ns = adapter.name_search(f"chain step {step}: deeds into {name} filed on or before {cur.date}", who,
                                 side="grantee", date_thru=thru)
        res.searches.append(ns)
        if ns.walled:
            res.chain_note = f"The register search for step {step} stopped at a wall ({ns.wall_reason})."
            break
        cands = []
        for r in ns.rows:
            if not is_conveyance(r):
                continue
            if (r.book, r.page) == (cur.book, cur.page):
                continue
            if r.date_iso and cur.date_iso and r.date_iso > cur.date_iso:
                continue
            on_grantee = [m for m in r.matched if m in r.grantees]
            if pn is not None:
                fits = [name_compat(pn, x) for x in (parse_indexed(m) for m in on_grantee) if x is not None]
                fit = "full" if "full" in fits else ("compatible" if "compatible" in fits else None)
            else:
                fit = "full" if any(clean(m) == clean(name) for m in on_grantee) else None
            if fit is None:
                continue
            r.name_fit = fit
            cands.append(r)
        if not cands:
            res.chain_note = (f"No earlier deed into {name} was found in the online index (chain step {step}, "
                              f"Exhibit {ns.exhibit}). Older instruments may sit in books the online index does "
                              f"not reach; an abstractor covers those.")
            break
        cands.sort(key=lambda r: (r.date_iso or "", r.book, r.page))
        pick = cands[-1]
        pick.tie = tie_note(pick, cur, pn.indexed() if pn is not None else name, len(cands) - 1)
        out.append(pick)
        cur = pick
    else:
        res.chain_note = (f"The chain stops after {max_steps} steps by design; earlier deeds can be followed the "
                          f"same way.")
    return out


def records_table(res: IntakeResult, adapter: CountyAdapter) -> list[RecordCheck]:
    out: list[RecordCheck] = []
    p = res.parcel
    if p is not None:
        out.append(RecordCheck("County parcel record (tax parcel layer)", "checked",
                               f"Query by PIN {res.pin} (Exhibit {p.exhibit}).",
                               "Parcel found." if p.found else "No parcel returned for this PIN."))
    ts = res.tax
    if ts is not None:
        if ts.walled:
            out.append(RecordCheck("Tax records (county tax bills)", "walled", "Parcel tax page", ts.wall_reason or ""))
        else:
            n = sum(1 for b in ts.bills if b.detail_read)
            out.append(RecordCheck("Tax records (county tax bills)", "checked",
                                   f"The parcel's billing list ({len(ts.bills)} bills) and {n} bill detail pages.",
                                   "See the tax section."))
    if res.deed_link is not None or res.vesting_note:
        out.append(RecordCheck("Register of Deeds index: the deed the county cites", "checked" if res.deed_link else "not run",
                               "Book/page search of the deed the county cites.", res.vesting_note or ""))
    if res.plat_link:
        out.append(RecordCheck("Register of Deeds index: the plat the county cites", "checked",
                               "Book/page search of the plat reference.", f"{len(res.plat_rows)} entries listed."))
    if res.searches or res.vesting is not None:
        out.append(RecordCheck("Register of Deeds index: the chain before that deed", "checked in part",
                               f"{len(res.searches)} name search(es), grantee side, filed on or before each deed.",
                               f"{len(res.chain)} earlier deed(s) found. {res.chain_note or ''}".strip()))
    if res.after_vesting:
        out.append(RecordCheck("Register of Deeds index: instruments naming the owner of record", "checked in part",
                               "Name search, both sides, all dates (index only; other spellings not searched).",
                               "; ".join(f"{ns.last}, {ns.first}: {ns.shown} entries kept of {ns.total if ns.total is not None else '?'} returned"
                                         for ns in res.after_vesting)))
    if res.death_searches:
        out.append(RecordCheck("Register of Deeds deaths index", "checked",
                               "Surname exactly, given name begins with, per owner of record.",
                               "; ".join(f"{d.person}: {len(d.entries)} entries" + (" (walled)" if d.walled else "")
                                         for d in res.death_searches)))
    elif p is not None and p.found:
        out.append(RecordCheck("Register of Deeds deaths index", "not run",
                               "No owner of record could be read as a person's name.", ""))
    ob = res.obituary or {}
    if ob:
        out.append(RecordCheck("Obituaries", "checked" if ob.get("run") else "not run",
                               "; ".join(ob.get("searches") or []) or "none", ob.get("reason") or ""))
    out.extend(adapter.static_records())
    return out
