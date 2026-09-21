"""SC phone identity gate: keep NC-voter-file phones off SC owners they do not belong to.

WHY THIS EXISTS
    enrichment_sc_voter_xref matches an SC property owner to an NC voter on FIRST + LAST
    NAME ALONE, across a state line. "Unique in the NC voter file" means one NC voter has
    that name, not that the SC owner IS that voter. Measured 2026-09-21 on the live board
    (numbers in docs/phone_gate_2026-09-21.md): the lane holds 1,671 SC phones, most of them
    a stranger's, stamped when owner_name held something else (a VFW post, an LLC, a trustee)
    and never re-checked. Those phones must not be dialed.

THE VERDICT  xref_identity_verdict(li) -> "corroborated" | "unverified" | "contradicted"

    contradicted   the voter the phone was matched to is not the current owner: the matched
                   voter's first AND last name are not both tokens of the current owner_name,
                   or the owner is an entity or an estate (LLC, INC, VFW POST, TRUST, ...).
    corroborated   independent evidence that the voter and the owner are one person:
                     (i)  the owner MAILS to an NC address whose house number + street token
                          equals that voter's residential street key (same _street_key the
                          voter-phone enricher uses), unless the two carry provably different
                          middle initials (a father and son sharing a house), or
                     (ii) the owner name agrees with the voter INCLUDING the middle initial
                          (name_normalize.party_middle_verdict == "agrees") AND the voter's
                          county is the lead's county.
                   In both cases the voter record must carry the phone that is stored.
    unverified     everything else. A name-only match with an SC mailing address lands here.

    Path (ii) requires the LEAD to be in NC. The voter file is NC-only, so an SC lead can
    never share a county with a voter; "Union", "Cherokee" and "Lee" exist in both states
    and a bare county-name comparison would corroborate a stranger across the line.

WHAT IS NOT DIALABLE  (owner_phone_block_reason / is_owner_phone_usable)
    * do_not_dial True (set by this gate, or by anyone else),
    * an xref-sourced phone whose identity_check is not "corroborated" (fail closed: a
      legacy phone that was never stamped is blocked at export time before --apply runs),
    * a people-search phone (source free_people_search / enrichment_free_phones): walled,
    * an agent phone (HomeHarvest listing agent or office, a notice's attorney or trustee):
      role "agent", a real contact for the sale, never the OWNER's number.
    liensnc_filing is the OWNER's own phone from the lien-agent appointment and is kept.

MEMORY
    The verdict needs each matched voter's residential street, middle name and county. The
    existing enrichment_voter_phone._build_index() holds every active NC voter in several
    dicts (gigabytes, on an 8 GB Mac) and has no middle names, so this module scans the
    cached voter files ONCE, line by line, and keeps only the voters whose (LAST, FIRST) is
    in the set being checked (VoterIdentityIndex.ensure). Tens of kilobytes resident.

    xref_identity_verdict() on a single listing scans the files if its name is not loaded
    yet; batch through flag_unverified_xref_phones() (one scan for the whole set).

Never writes the board. flag_unverified_xref_phones(apply=True) mutates the Listing objects
it is given; the caller decides whether to persist (scripts/flag_unverified_sc_phones.py).
"""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from foreclosure_scraper.enrichment_voter_phone import _DATA as _VOTER_DIR
from foreclosure_scraper.enrichment_voter_phone import _street_key
from foreclosure_scraper.name_normalize import is_entity, normalize_name, party_middle_verdict

CORROBORATED = "corroborated"
UNVERIFIED = "unverified"
CONTRADICTED = "contradicted"

#: Phones stamped by the NC-voter-file cross-reference. These follow the identity gate.
XREF_SOURCES = frozenset({"ncsbe_voter_xref", "sc_voter_xref"})

#: The people-search lane is walled (TruePeopleSearch serves a captcha, FastPeopleSearch's
#: terms bar bots). enrichment_free_phones writes source "free_people_search".
WALLED_SOURCES = frozenset({"free_people_search", "enrichment_free_phones", "free_phones"})
_WALLED_HINTS = ("people_search", "peoplesearch", "truepeople", "fastpeople")

#: Phones that belong to a listing agent, an office, an attorney or a trustee, not the owner.
AGENT_SOURCES = frozenset({
    "homeharvest_agent", "homeharvest_office", "notice_contact_attorney", "ocr_legal_notice",
})
_AGENT_MATCHES = frozenset({"attorney", "attorney_in_notice", "trustee", "listing_agent"})

#: The owner's own number, from the owner block of a lien-agent appointment filing.
OWNER_OWN_SOURCES = frozenset({"liensnc_filing"})

#: do_not_dial_reason values the gate wrote itself. Only these are cleared again when a phone
#: later becomes corroborated; a flag somebody else set is never cleared here.
GATE_REASON_PREFIX = "sc_xref_identity_"
WALLED_REASON = "people_search_walled"

# --------------------------------------------------------------------------------------
# entity / estate detection
# --------------------------------------------------------------------------------------
# name_normalize.is_entity() is THE entity detector (LLC, INC, CORP, CO, LP, LLP, TRUST,
# ASSOCIATION, CHURCH, MINISTRIES, HOLDINGS, PROPERTIES, PARTNERS, BANK, ...). It has no
# marker for a VFW post, a club, an estate or a government owner, so this adds those on top,
# the same way enrichment_owner_cluster does. It is a supplement, not a second detector.
_EXTRA_ANY_POSITION = frozenset({
    "ESTATE", "HEIRS", "HEIR", "DECEASED", "DECD",       # not a living individual
    "CLUB", "SOCIETY", "HOA", "CEMETERY", "SCHOOL", "HOSPITAL", "UNIVERSITY", "COLLEGE",
    "COUNTY",
})
# POST and LODGE are also surnames ("POST WILLIAM"), so they only count after the first token.
_EXTRA_NOT_FIRST = frozenset({"POST", "LODGE"})
_GOV_RE = re.compile(r"\b(?:CITY|TOWN|STATE)\s+OF\b")


def owner_is_non_person(name: Optional[str]) -> bool:
    """True when the owner is an entity, an estate, a post or club, or a government body."""
    if is_entity(name):
        return True
    norm = normalize_name(name)
    if not norm:
        return False
    toks = norm.split()
    # "LIFE ESTATE" is an interest held by a living person, not a decedent's estate
    live = [t for i, t in enumerate(toks) if not (t == "ESTATE" and i > 0 and toks[i - 1] == "LIFE")]
    if _EXTRA_ANY_POSITION & set(live):
        return True
    if _EXTRA_NOT_FIRST & set(toks[1:]):
        return True
    return bool(_GOV_RE.search(norm))


# --------------------------------------------------------------------------------------
# NC voter identity records (targeted scan)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class VoterRec:
    last: str
    first: str
    middle: str
    county: str                       # NC county, upper case, no "COUNTY"
    street_key: Optional[tuple]       # _street_key(res_street_address)
    phone: str                        # 10 digits


class VoterIdentityIndex:
    """(LAST, FIRST) -> the active NC voters with a phone who carry that name.

    Loaded on demand and only for the names asked about: ensure() makes one pass over the
    cached ncvoter*.txt files and keeps just the matching rows. Same row rules as
    enrichment_voter_phone._build_index: status "A", a 10 digit phone, both names present.
    """

    def __init__(self, voter_dir: Path | str | None = None):
        self.voter_dir = Path(voter_dir) if voter_dir is not None else _VOTER_DIR
        self._by_name: dict[tuple[str, str], list[VoterRec]] = defaultdict(list)
        self._covered: set[tuple[str, str]] = set()
        self.files_scanned = 0
        self.rows_scanned = 0

    def add(self, rec: VoterRec) -> None:
        """Test hook: register a voter without touching disk."""
        self._by_name[(rec.last, rec.first)].append(rec)
        self._covered.add((rec.last, rec.first))

    def records(self, last: str, first: str) -> list[VoterRec]:
        return list(self._by_name.get((last, first), ()))

    def ensure(self, names: Iterable[tuple[str, str]]) -> None:
        want = {n for n in names if n and n not in self._covered}
        if not want:
            return
        self._covered |= want
        want_last = {last for last, _ in want}
        for f in sorted(self.voter_dir.glob("ncvoter*.txt")):
            try:
                with open(f, encoding="latin-1", newline="") as fh:
                    reader = csv.reader(fh, delimiter="\t")
                    next(reader, None)                                  # header
                    for row in reader:
                        self.rows_scanned += 1
                        if len(row) < 24:
                            continue
                        last = row[4].strip().upper()
                        if last not in want_last:
                            continue
                        first = row[5].strip().upper()
                        if (last, first) not in want or row[8].strip() != "A":
                            continue
                        phone = re.sub(r"\D", "", row[23] or "")
                        if len(phone) != 10:
                            continue
                        self._by_name[(last, first)].append(VoterRec(
                            last=last, first=first, middle=row[6].strip().upper(),
                            county=_county_key(row[1]), street_key=_street_key(row[12]),
                            phone=phone))
            except OSError:
                continue
            self.files_scanned += 1


_DEFAULT_INDEX: VoterIdentityIndex | None = None


def default_index() -> VoterIdentityIndex:
    global _DEFAULT_INDEX
    if _DEFAULT_INDEX is None:
        _DEFAULT_INDEX = VoterIdentityIndex()
    return _DEFAULT_INDEX


# --------------------------------------------------------------------------------------
# small parsers
# --------------------------------------------------------------------------------------
_MATCH_RE = re.compile(r"^(?:NC_XREF:)?\s*([A-Z][A-Z ]*?)\s*,\s*([A-Z][A-Z ]*?)\s*$")
_STATE_TAIL_RE = re.compile(r"\b([A-Z]{2})[\s,]+\d{5}(?:-\d{4})?\s*$")


def _digits(s) -> str:
    d = re.sub(r"\D", "", str(s or ""))
    return d[1:] if len(d) == 11 and d.startswith("1") else d


def _county_key(s) -> str:
    return re.sub(r"\s+COUNTY$", "", str(s or "").strip().upper())


def _voter_name(block: dict) -> Optional[tuple[str, str]]:
    """(LAST, FIRST) of the voter the phone was matched to, from match 'nc_xref:LAST,FIRST'."""
    m = _MATCH_RE.match(str(block.get("match") or "").strip().upper())
    return (m.group(1), m.group(2)) if m else None


def _owner_tokens(owner: str) -> set[str]:
    """Tokens of the owner name under both normalisations in play: name_normalize's
    (O'BRIEN -> OBRIEN) and the letters-only split _name_candidates used to make the match
    (O'BRIEN -> O BRIEN)."""
    return set(normalize_name(owner).split()) | set(re.sub(r"[^A-Za-z]+", " ", owner).upper().split())


def _mail_state(om: dict) -> str:
    ms = str(om.get("mail_state") or "").strip().upper()
    if ms:
        return ms
    m = _STATE_TAIL_RE.search(str(om.get("mailing") or "").upper())
    return m.group(1) if m else ""


def _middle_verdict(owner: str, rec: "VoterRec") -> str:
    """name_normalize.party_middle_verdict of the owner against one voter: 'agrees' when both
    carry the same middle initial, 'conflict' when both carry one and they differ, else
    'unverified' (no middle on one side)."""
    party = f"{rec.first} {rec.middle} {rec.last}" if rec.middle else f"{rec.first} {rec.last}"
    return party_middle_verdict(owner, [party])


def _xref_blocks(raw: dict) -> list[dict]:
    """The phone blocks on a row that came from the NC voter cross-reference."""
    out: list[dict] = []
    op = raw.get("owner_phone")
    if isinstance(op, dict) and op.get("phone") and str(op.get("source") or "") in XREF_SOURCES:
        out.append(op)
    sx = raw.get("sc_voter_xref")
    if isinstance(sx, dict) and sx.get("phone"):
        out.append(sx)
    return out


# --------------------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------------------
def xref_identity_check(li, block: Optional[dict] = None,
                        index: Optional[VoterIdentityIndex] = None) -> dict:
    """{"verdict", "reason", "voter": (LAST, FIRST) | None} for one xref phone.

    `block` defaults to the row's first xref phone block. `index` defaults to the module
    index (scans the voter files on first use of a name; batch with
    flag_unverified_xref_phones for more than a handful of rows).
    """
    raw = getattr(li, "raw", None)
    raw = raw if isinstance(raw, dict) else {}
    if block is None:
        blocks = _xref_blocks(raw)
        if not blocks:
            return {"verdict": UNVERIFIED, "reason": "no_xref_phone", "voter": None}
        block = blocks[0]
    return _check(li, raw, block, index)


def xref_identity_verdict(li, index: Optional[VoterIdentityIndex] = None) -> str:
    """'corroborated' | 'unverified' | 'contradicted' for the row's NC-voter-xref phone."""
    return xref_identity_check(li, index=index)["verdict"]


def _check(li, raw: dict, block: dict, index: Optional[VoterIdentityIndex]) -> dict:
    owner = str(getattr(li, "owner_name", None) or "").strip()
    voter = _voter_name(block)

    def out(verdict: str, reason: str) -> dict:
        return {"verdict": verdict, "reason": reason, "voter": voter}

    # contradicted: the phone cannot be a living individual owner's
    if not owner:
        return out(CONTRADICTED, "owner_name_missing")
    if owner_is_non_person(owner):
        return out(CONTRADICTED, "entity_or_estate_owner")
    if voter is None:
        return out(UNVERIFIED, "no_match_key")
    last, first = voter
    tokens = _owner_tokens(owner)
    if last not in tokens or first not in tokens:
        return out(CONTRADICTED, "voter_name_not_in_owner")

    # corroborated: independent evidence the voter and the owner are one person
    idx = index if index is not None else default_index()
    idx.ensure([voter])
    stored = _digits(block.get("phone"))
    recs = [r for r in idx.records(last, first) if r.phone == stored]
    if not recs:
        return out(UNVERIFIED, "voter_record_not_found")

    om = raw.get("owner_mailing")
    if isinstance(om, dict) and _mail_state(om) == "NC":
        key = _street_key(str(om.get("mailing") or ""))
        at_street = [r for r in recs if key and r.street_key == key]
        if at_street:
            # Same street, but two provably different middle initials is a father and son
            # sharing a house (or a Jr and Sr), and the phone may be the other one's.
            if any(_middle_verdict(owner, r) != "conflict" for r in at_street):
                return out(CORROBORATED, "nc_mailing_street_matches_voter")
            return out(UNVERIFIED, "middle_initial_conflict")

    if str(getattr(li, "state", None) or "").upper() == "NC":
        lead_county = _county_key(getattr(li, "county", None))
        for r in recs:
            if r.middle and lead_county and r.county == lead_county and _middle_verdict(owner, r) == "agrees":
                return out(CORROBORATED, "name_middle_county_agree")

    return out(UNVERIFIED, "no_corroboration")


# --------------------------------------------------------------------------------------
# what may be dialed
# --------------------------------------------------------------------------------------
def _is_walled(source: str) -> bool:
    s = source.lower()
    return s in WALLED_SOURCES or any(h in s for h in _WALLED_HINTS)


def _is_agent(op: dict) -> bool:
    src = str(op.get("source") or "")
    if src in OWNER_OWN_SOURCES:
        return False
    if op.get("role") == "agent":
        return True
    if src in AGENT_SOURCES or src.startswith("raw."):
        return True
    return str(op.get("match") or "").lower() in _AGENT_MATCHES


def phone_lane(op) -> str:
    """Which lane an owner_phone block came from, for reporting and the gate.

    liensnc_filing | sc_voter_xref | people_search | agent | voter_name_address |
    voter_name_only | county_published | other
    """
    if not isinstance(op, dict):
        return "other"
    src = str(op.get("source") or "")
    if src in OWNER_OWN_SOURCES:
        return "liensnc_filing"
    if src in XREF_SOURCES:
        return "sc_voter_xref"
    if _is_walled(src):
        return "people_search"
    if _is_agent(op):
        return "agent"
    if src == "ncsbe_voter":
        return ("voter_name_address" if str(op.get("match") or "") in ("name+address", "fuzzy:soundex+addr")
                else "voter_name_only")
    if op.get("county_published"):
        return "county_published"
    return "other"


def owner_phone_block_reason(op) -> Optional[str]:
    """Why this owner_phone block must not be dialed or exported as an OWNER contact, or None.

    Works on an unstamped legacy block: the lane is read from source/match, and an xref phone
    with no corroborated identity_check fails closed.
    """
    if not isinstance(op, dict) or not op.get("phone"):
        return "no_phone"
    if op.get("do_not_dial"):
        return str(op.get("do_not_dial_reason") or "do_not_dial")
    src = str(op.get("source") or "")
    if src not in OWNER_OWN_SOURCES:
        if _is_walled(src):
            return WALLED_REASON
        if _is_agent(op):
            return "agent_contact"
    if src in XREF_SOURCES and op.get("identity_check") != CORROBORATED:
        return GATE_REASON_PREFIX + str(op.get("identity_check") or "unchecked")
    return None


def is_owner_phone_usable(op) -> bool:
    """True when the block carries a phone that may be offered as the OWNER's number."""
    return owner_phone_block_reason(op) is None


def usable_owner_phone(raw) -> str:
    """The owner phone string on a row's raw dict when it is usable, else ''."""
    op = raw.get("owner_phone") if isinstance(raw, dict) else None
    return str(op.get("phone")) if is_owner_phone_usable(op) else ""


# --------------------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------------------
def _set(d: dict, key: str, value) -> bool:
    """d[key] = value; True when that changed d."""
    if key in d and d[key] == value:
        return False
    d[key] = value
    return True


def _drop(d: dict, key: str) -> bool:
    return d.pop(key, _MISSING) is not _MISSING


_MISSING = object()


def flag_unverified_xref_phones(listings, apply: bool = False,
                                index: Optional[VoterIdentityIndex] = None) -> dict:
    """Verdict every NC-voter-xref phone; with apply=True stamp it.

    apply=False (default) is report-only: nothing is written to any listing.
    apply=True sets owner_phone["identity_check"] to the verdict and
    owner_phone["do_not_dial"] = True (plus do_not_dial_reason) for anything not
    corroborated. The phone value is kept. A corroborated phone whose do_not_dial was set by
    this gate is cleared again; a flag set by anyone else is left alone. Idempotent.

    Returns counts: xref_phones, corroborated, unverified, contradicted, changed (blocks that
    were, or in a dry run would be, modified), do_not_dial (blocks that end up flagged),
    reasons, by_county {county: {verdict: n}}.
    """
    idx = index if index is not None else default_index()
    targets: list[tuple[object, dict, dict]] = []
    scanned = 0
    for li in listings:
        scanned += 1
        raw = getattr(li, "raw", None)
        if not isinstance(raw, dict):
            continue
        for block in _xref_blocks(raw):
            targets.append((li, raw, block))
    idx.ensure({v for _, _, b in targets if (v := _voter_name(b))})

    verdicts: Counter = Counter()
    reasons: Counter = Counter()
    by_county: dict[str, Counter] = defaultdict(Counter)
    changed = flagged = 0
    for li, raw, block in targets:
        res = _check(li, raw, block, idx)
        verdict = res["verdict"]
        verdicts[verdict] += 1
        reasons[res["reason"]] += 1
        by_county[str(getattr(li, "county", None) or "?")][verdict] += 1
        want_flag = verdict != CORROBORATED
        flagged += want_flag
        # what the block would look like after the stamp, computed on a copy for a dry run
        b = block if apply else dict(block)
        touched = _set(b, "identity_check", verdict)
        if want_flag:
            touched |= _set(b, "do_not_dial", True)
            touched |= _set(b, "do_not_dial_reason", GATE_REASON_PREFIX + verdict)
        elif b.get("do_not_dial") and str(b.get("do_not_dial_reason") or "").startswith(GATE_REASON_PREFIX):
            touched |= _drop(b, "do_not_dial")
            touched |= _drop(b, "do_not_dial_reason")
        changed += touched
    return {
        "applied": bool(apply),
        "scanned": scanned,
        "xref_phones": len(targets),
        "corroborated": verdicts[CORROBORATED],
        "unverified": verdicts[UNVERIFIED],
        "contradicted": verdicts[CONTRADICTED],
        "do_not_dial": flagged,
        "changed": changed,
        "reasons": dict(reasons),
        "by_county": {c: dict(v) for c, v in sorted(by_county.items())},
        "voter_files_scanned": idx.files_scanned,
    }


def flag_lane_phones(listings, apply: bool = False) -> dict:
    """Lane rules that need no voter data.

    * A people-search phone (owner_phone source free_people_search, and every raw.free_phones
      entry) gets do_not_dial True: that lane is walled.
    * A listing-agent, office, attorney or trustee phone gets role "agent": it is a contact
      for the sale, never counted as the owner's number.
    liensnc_filing (the owner's own number) is never touched. apply=False counts only.
    """
    stats = {"applied": bool(apply), "scanned": 0, "owner_phones": 0, "walled_flagged": 0,
             "free_phones_flagged": 0, "agent_tagged": 0, "changed": 0}
    for li in listings:
        stats["scanned"] += 1
        raw = getattr(li, "raw", None)
        if not isinstance(raw, dict):
            continue
        op = raw.get("owner_phone")
        if isinstance(op, dict) and op.get("phone"):
            stats["owner_phones"] += 1
            src = str(op.get("source") or "")
            if src not in OWNER_OWN_SOURCES:
                if _is_walled(src):
                    b = op if apply else dict(op)
                    t = _set(b, "do_not_dial", True)
                    t |= _set(b, "do_not_dial_reason", WALLED_REASON)
                    stats["walled_flagged"] += 1
                    stats["changed"] += t
                elif _is_agent(op):
                    b = op if apply else dict(op)
                    t = _set(b, "role", "agent")
                    stats["agent_tagged"] += 1
                    stats["changed"] += t
        fp = raw.get("free_phones")
        if isinstance(fp, list):
            for entry in fp:
                if isinstance(entry, dict) and entry.get("phone"):
                    b = entry if apply else dict(entry)
                    t = _set(b, "do_not_dial", True)
                    t |= _set(b, "do_not_dial_reason", WALLED_REASON)
                    stats["free_phones_flagged"] += 1
                    stats["changed"] += t
    return stats
