"""bankruptcy_stay, NC + SC federal bankruptcy courts (CourtListener / RECAP): is the board owner
really this case's debtor, and is the case still open (the automatic stay live)?

Evolved from docs/validation_2026-10-02/scripts/validate_bankruptcy_namematch.py (FINDINGS.md #2:
of the 234 rows carrying both an owner and a bankruptcy case name, 56.0% were a strong match,
38.5% weak (almost certainly the wrong person), 5.6% shared no token). That script was local
only; this one asks the source. Same free API the scraper and the enricher use:

    https://www.courtlistener.com/api/rest/v4/search/?type=r&q=docket_id:{id}&format=json
        the docket as the RECAP search index holds it: caseName (the debtor names, joint filers
        joined by a bare "and"), docketNumber, court_id, dateFiled, dateTerminated, chapter,
        party. Answers without a token. A docket_id that matches nothing is re-asked by
        court + docket_number, then at /dockets/{id}/, before the case is called missing.
    https://www.courtlistener.com/api/rest/v4/docket-entries/?docket={id}&order_by=-date_filed
        the newest 20 docket entries (short descriptions only, via `fields=`). Needs the token.

WHY THE ENTRIES AND NOT dateTerminated. CourtListener fills dateTerminated only when someone pulls
the docket from PACER; the bankruptcy courts' RSS feeds add entries but not that date. Measured
2026-10-06: the RECAP index held 3 ncwb cases filed in 2026 with a dateTerminated, out of
thousands. So the outcome is read from the entries. Two live examples: a Buncombe Chapter 13 the
board scored as an open stay has date_terminated null and an entry "Dismissal" (2026-09-21); a
2015 Chapter 13 the board carries as "long-open" has date_terminated null, "Discharge"
(2022-05-25) and "Final Decree/Case Closed" (2022-09-15).

THE MATCH IS PRODUCTION'S (enrichment_bankruptcy.py since e78fc0ae, 2026-10-02):
`name_normalize.debtor_positional_match` (a debtor segment of the case name, split on a bare
"and", has the owner's FIRST name first and LAST name last) and `debtor_middle_verdict`
("conflict" = same first and last, every such debtor has a middle initial, none is the owner's:
a different person). Every row on the board still carries the pre-fix bag-of-tokens match
(`match_strategy: strict_subset`, all 617 raw.bankruptcy rows on 2026-10-06), so this is the
first time the fixed rule judges them. The verifier only chooses which board names to feed it:
`owner_name` and `defendant` for a cross-reference match (the enricher matched the defendant);
for a listing-type bankruptcy row (a scraped filing the pipeline tied to a parcel, scored by F11)
the parcel's owner of record from the county data on the row, never its owner_name when that is
only the debtor's name copied (see board_names: 188 of 393 such rows, and the snapped parcel of
many belongs to someone else, recorded by enrich_court_owner_verify in raw.owner_mismatch). Each
co-owner of a joint owner string is checked separately ("SMITH JOHN A;SMITH MARY B").

VERDICTS (core.py's meanings):
  confirmed    the case exists; a board owner name matches a debtor positionally with no middle
               conflict (middle agrees, or one side has no middle: production's bar); the court is
               in the row's state (production's _COURT_STATE check); no dismissal, discharge or
               closing in the entries or dateTerminated; and a docket entry in the last
               ACTIVE_DAYS, so the stay is live.
  stale        the same real match, but the case was dismissed, discharged or closed (a later
               reinstatement undoes a dismissal): the stay WAS live and has lifted. Needs a
               VERIFIED identity (v3): a first + last match with no middle name to compare on
               one side ("unverified", decided_by positional_match_unverified) is unconfirmed
               (identity_unverified) unless the verifier itself corroborates the person from
               the repo's own data (CORROBORATION below).
  refuted      the debtor is a different person (a proven middle conflict, or no debtor in the
               case lines up with any board owner name, and no NAME PATTERN below says the owner
               may be the debtor under another name), or the case does not exist.
  unconfirmed  cannot decide: no person name (no owner of record) on the board to compare; a
               NAME PATTERN fires in a court that can cover the property (v4); two
               board names disagree (one matches, another names someone else); an ALL-CAPS owner
               that matches only when read FIRST MIDDLE LAST (owner_last_first_middle reads
               ALL-CAPS surname-first, "MARY A SMITH"); a match whose court is in another state (the one place a
               first+last match is not enough: production rejects it, nothing here says it is a
               different person); no docket entries, or none in ACTIVE_DAYS, so the status
               cannot be read; an API failure.

WRONG DISTRICT (v3). Each NC county belongs to one federal bankruptcy district (E.D.N.C. nceb,
M.D.N.C. ncmb, W.D.N.C. ncwb; five counties are split with the Fort Bragg / Butner reservations
and hold two courts) and SC is one district (scb): NC_COUNTY_COURTS, from 28 U.S.C. 113. A docket
whose court cannot cover the property's county is not this owner's as far as this verifier can
tell: unconfirmed, reason wrong_district, whatever the case's status (a debtor can file where
they live, so it is never refuted on this alone). The first live sweep called a completed
M.D.N.C. Chapter 13 stale for a McDowell County (W.D.N.C.) row whose docket caption had no middle
name and was attached by name to five board rows.

NAME PATTERNS (v4). The positional matcher compares first and last name in their places, so it
cannot see a person who filed and owns under different names, and refuted removes the bankruptcy
signal from the lead's score. A live re-check of 42 of the 75 refuted entries (2026-10-06, an
independent agent) held 36 and found 2 plausibly the same person and 4 undecidable, all of one of
these shapes (a names-only screen of all 75 found about 20 of them):
  maiden_name      the owner has the debtor's FIRST name and the debtor's spelled-out MIDDLE name
                   (3+ letters) is the owner's SURNAME: a woman who filed under a married name and
                   owns under another. The first name may differ by one edit (4+ letters).
  middle_as_first  the owner has the debtor's SURNAME and the debtor's spelled-out middle name
                   (3+ letters) as FIRST name: a person who goes by the middle name.
  across_debtors   (maiden_name only) in a joint filing the owner's first name is one debtor's and
                   the owner's surname is the OTHER debtor's middle name. The first name of one
                   debtor with the SURNAME of another is the phantom production's matcher exists
                   to reject; a middle name is the extra coincidence that makes this one undecided.
A name with no comma has no known order (capitals are surname first on the county rolls, but a
Title Case roll entry is too), so both orders are read, the other one with exact first names only
(a surname is not a typo of a first name): owner_readings.
A pattern is only a reason NOT TO REFUTE: it runs when the plain match says none or conflict, and it
counts only when the debtor's court can cover the property (the right state, a district that holds
the county: wrong_district) and, where the board knows it, the owner's mailing state is the court's
state. Then the verdict is unconfirmed, reason name_pattern_possible_same_person, so the claim keeps
scoring; the case's status is not read (a closed case could not be called stale either: the identity
is unverified). A court that cannot cover the property, a first-name-only or a same-surname-only
overlap, a plain middle-name conflict and an entity debtor stay exactly as they were (refuted). The
evidence names the pattern, never the names.

CORROBORATION (v3, offline). A stale answer on an "unverified" name match stands only when the
debtor's caption names a middle name or initial and, in the property's county, EITHER the NC
voter file (data/ncvoter, 13 counties, VERIFY_NCVOTER_DIR) holds exactly one ACTIVE / INACTIVE
registrant with the debtor's first name, middle and last name AND that registrant lives at the
row's address, OR the parcel owner roll (data/parcel_cache/<county>.sqlite) names exactly one
person on the row's parcel, with that full name. Neither source is asked for a name: they only
corroborate the identity the docket and the board already claim, and nothing from them is
published (evidence says only identity_corroborated_by).

GOVERNS: a refuted or stale verdict removes the scorer's `bankruptcy` signal (raw.bankruptcy in
distress_score._collect and the lead-signal facet, and the `bankruptcy` listing type) and the
stay (`bankruptcy_stay`: the facet, and distress_score's F3 WARM cap via _stay_block). Both
follow the scorer's own reading of a lapsed bankruptcy: a case that is over is no signal and no
stay. A stale verdict on a stayed foreclosure is the useful one: the sale can resume.

WHAT IS PUBLISHED (the ledger is pushed to a PUBLIC repo, and the VM attaches it to the board):
public_evidence() is a whitelist every answer goes through, the decision basis only, no person
names. A refuted verdict means the debtor is someone else: naming them, or their docket, next to
a property they have nothing to do with would create a false association, so a refuted record
says only how it was decided (and, for a middle conflict, the two middle INITIALS). confirmed
and stale (the case IS this owner's, as the board's raw.bankruptcy already says) add the court,
docket number and id, chapter, filing date, the terminal event's kind and date, last activity
and the dates of relief-from-stay entries. unconfirmed adds its reason and the status fields.
ROW_SUMMARY_EXCLUDE keeps owner_name out of the ledger's row summary; migrate_ledger() rewrites
a stored ledger to this shape offline.

CASE IDENTITY (IDENTITY = "case", 2026-10-06). The ledger is keyed by the claimed case (court +
docket number, hashed: case_identity) and the property, not by the property alone: a
geo-snapped placeholder parcel holds many unrelated filings (about 37 on one Anderson SC parcel,
3 on one Lincoln parcel on the 2026-10-05 board), and a property key gave all of them one
verdict. The same case on two rows of one property still shares one.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from ..core import VerificationResult, result

SIGNAL = "bankruptcy_stay"
VERSION = "v4"         # v4 (2026-10-06): NAME PATTERNS (maiden name, middle name as first name)
                       # are unconfirmed, not refuted. v3: wrong_district; stale needs a verified identity.
                       # v2: a match in one board name beside a person in another
                       # who does not match (not only one who conflicts) is unconfirmed
TTL_DAYS = 30          # refuted/stale (the verdicts that change the score) are durable facts;
                       # a confirmed-open case is re-read monthly
RETRY_DAYS = 7
SOURCE = "courtlistener.com"
GOVERNS = ("bankruptcy", "bankruptcy_stay")
ROW_SUMMARY_EXCLUDE = ("owner_name",)   # the ledger is public; see WHAT IS PUBLISHED
IDENTITY = "case"      # one verdict per case and property (case_identity), not per property

SITE = "https://www.courtlistener.com"
API = SITE + "/api/rest/v4"
SEARCH_BY_ID = API + "/search/?type=r&q=docket_id%3A{id}&format=json"
SEARCH_BY_NUMBER = API + "/search/?type=r&court={court}&docket_number={dn}&format=json"
DOCKET_URL = (API + "/dockets/{id}/?fields=id,court_id,docket_number,case_name,date_filed,"
              "date_terminated,date_last_filing,absolute_url&format=json")
ENTRIES_URL = (API + "/docket-entries/?docket={id}&order_by=-date_filed&page_size=20"
               "&fields=date_filed,entry_number,description,recap_documents__description"
               "&format=json")
ACTIVE_DAYS = 180      # an open case's docket moves at least twice a year (trustee motions,
                       # claims, plan modifications)

_NAME = __name__.rsplit(".", 1)[-1]
_REPO = Path(__file__).resolve().parents[4]
_DOCKET_ID = re.compile(r"/docket/(\d+)/")
_TOKEN: Optional[str] = None
_TOKEN_LOADED = False


# ---------------------------------------------------------------------------
# which rows, and what they claim
# ---------------------------------------------------------------------------

def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def docket_id_of(url: Any) -> Optional[int]:
    m = _DOCKET_ID.search(str(url or ""))
    return int(m.group(1)) if m else None


def claim_of(row: dict) -> Optional[dict]:
    """The case the row claims, or None. In order: the cross-reference match
    (raw.bankruptcy, written by enrichment_bankruptcy), the stay derived from it
    (raw.bankruptcy_stay), and a listing-type bankruptcy row that is tied to a property (the
    only kind distress_score scores, F11)."""
    raw = _raw(row)
    bk, st = raw.get("bankruptcy"), raw.get("bankruptcy_stay")
    stay = st.get("status") if isinstance(st, dict) else None
    if isinstance(bk, dict) and (bk.get("docket_number") or docket_id_of(bk.get("absolute_url"))):
        return {"from": "raw.bankruptcy", "court": bk.get("court"),
                "docket_number": bk.get("docket_number"),
                "docket_id": docket_id_of(bk.get("absolute_url")),
                "case_name": bk.get("case_name"), "date_filed": bk.get("date_filed"),
                "chapter": bk.get("chapter"), "stay_status": stay}
    if isinstance(st, dict) and st.get("docket"):
        return {"from": "raw.bankruptcy_stay", "court": st.get("court"),
                "docket_number": st.get("docket"), "docket_id": None, "case_name": st.get("case"),
                "date_filed": st.get("date_filed"), "chapter": st.get("chapter"),
                "stay_status": stay}
    if row.get("listing_type") == "bankruptcy" and (row.get("parcel_id") or row.get("street_address")):
        cl = raw.get("courtlistener") if isinstance(raw.get("courtlistener"), dict) else {}
        did = docket_id_of(row.get("source_url"))
        if did or (row.get("case_number") and cl.get("court")):
            return {"from": "listing", "court": cl.get("court"),
                    "docket_number": row.get("case_number"), "docket_id": did,
                    "case_name": row.get("defendant"), "date_filed": None,
                    "chapter": cl.get("chapter"), "stay_status": None}
    return None


def applies(row: dict) -> bool:
    return claim_of(row) is not None


_CLAIM_FIELDS = ("raw", "listing_type", "parcel_id", "street_address", "source_url",
                 "case_number", "defendant")


def _as_dict(row: Any) -> dict:
    """A board dict as is; a models.Listing (the VM's apply step) as the dict claim_of reads."""
    if isinstance(row, dict):
        return row
    out = {k: getattr(row, k, None) for k in _CLAIM_FIELDS}
    lt = out.get("listing_type")
    out["listing_type"] = getattr(lt, "value", lt)
    return out


def _case_id(court: Any, docket_number: Any, docket_id: Any) -> Optional[str]:
    from ..core import case_id
    court = str(court or "").strip().lower()
    dn = str(docket_number or "").strip()
    if court and dn:
        return case_id("bk", court, dn)
    return case_id("bk", "courtlistener", docket_id) if docket_id else None


def case_identity(row: Any) -> Optional[str]:
    """The case the row claims (claim_of): court + docket number, else CourtListener's docket
    id, as a hashed core.case_id ("bk:<16 hex>"; the ledger publishes no docket identifiers on
    a refuted record, so neither may its keys). Every claim on the 2026-10-05 board has court +
    docket number but one (a docket id only). Works on a board dict and on a Listing."""
    claim = claim_of(_as_dict(row))
    if claim is None:
        return None
    return _case_id(claim.get("court"), claim.get("docket_number"), claim.get("docket_id"))


def case_identity_of_record(record: dict) -> Optional[str]:
    """The case a stored record's evidence names: confirmed and stale publish court + docket
    number (public_evidence); refuted and unconfirmed do not. For the case-scope migration."""
    ev = (record or {}).get("evidence") or {}
    if (record or {}).get("verdict") not in ("confirmed", "stale"):
        return None
    return _case_id(ev.get("court"), ev.get("docket_number"), ev.get("docket_id"))


# ---------------------------------------------------------------------------
# identity: production's matcher, fed every board name (pure)
# ---------------------------------------------------------------------------

_PERSON_SPLIT = re.compile(r"\s*(?:;|&|\+|<br\s*/?>|\band\b)\s*", re.I)
_RANK = {"agrees": 4, "unverified": 3, "conflict": 2, "order_ambiguous": 1, "none": 0}


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def board_names(row: dict, claim: dict) -> list[tuple[str, str]]:
    """(field, name) pairs to compare with the debtor.

    A cross-reference match (raw.bankruptcy / raw.bankruptcy_stay): owner_name and defendant,
    the names enrichment_bankruptcy matched.

    A listing-type bankruptcy row: its defendant IS the debtor, and its owner_name is very often
    that same name copied over (measured 2026-10-06: 188 of the 393 property-tied rows), so the
    property's owner of record comes from the county data on the row: the snapped parcel's
    owner that enrichment_court_owner_verify recorded in raw.owner_mismatch (when present it is
    THE parcel's owner, and it decides), else raw.gis.owner, owner_name and the name resolver's
    matched_owner. A value that is just the debtor's own name copied is not a record of anything
    and is left out."""
    raw = _raw(row)
    if claim.get("from") == "listing":
        debtor = _norm(row.get("defendant")).upper()
        om = raw.get("owner_mismatch")
        g = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
        rf = raw.get("resolved_from_name") if isinstance(raw.get("resolved_from_name"), dict) else {}
        if isinstance(om, dict) and om.get("snapped_owner"):
            cands = [("owner_mismatch.snapped_owner", om.get("snapped_owner"))]
        else:
            cands = [("gis.owner", g.get("owner")), ("owner_name", row.get("owner_name")),
                     ("resolved_from_name.matched_owner", rf.get("matched_owner"))]
        cands = [(f, v) for f, v in cands if _norm(v) and _norm(v).upper() != debtor]
    else:
        cands = [("owner_name", row.get("owner_name")), ("defendant", row.get("defendant"))]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for f, v in cands:
        v = _norm(v)
        if v and v.upper() not in seen:
            seen.add(v.upper())
            out.append((f, v))
    return out


def persons_of(name: str) -> list[str]:
    """The individual people in one board name string. Joint owners are split on ; & + and a
    bare "and"; a comma list of surname-first names ("MCDOWELL JAMES C JR, BRUCE JOHN, ...":
    two or more commas, or three or more words before the first) is split on its commas, while
    one comma stays the LAST, FIRST it is ("BROWN, ROBERT E JR"). Entities are dropped."""
    from ...name_normalize import core_tokens, is_entity
    out: list[str] = []
    for seg in _PERSON_SPLIT.split(str(name or "")):
        seg = seg.strip(" ,")
        if not seg:
            continue
        if seg.count(",") >= 2 or ("," in seg and len(core_tokens(seg.split(",", 1)[0])) >= 3):
            out.extend(p.strip() for p in seg.split(",") if p.strip())
        else:
            out.append(seg)
    return [p for p in out if not is_entity(p) and len(core_tokens(p)) >= 2]


def person_verdict(person: str, debtors: list[str]) -> str:
    """'agrees' | 'unverified' | 'conflict' (production's two calls), 'order_ambiguous' (no
    match as read, but an ALL-CAPS name without a comma matches when read FIRST MIDDLE LAST),
    or 'none'."""
    from ...name_normalize import debtor_middle_verdict, debtor_positional_match
    if debtor_positional_match(person, debtors):
        return debtor_middle_verdict(person, debtors)
    if "," not in person and not re.search(r"[a-z]", person) and \
            debtor_positional_match(person.title(), debtors):
        return "order_ambiguous"
    return "none"


def judge_identity(row: dict, claim: dict, debtors: list[str]) -> dict:
    """{'verdict': agrees|unverified|conflict|names_disagree|order_ambiguous|none|no_person,
    'field', 'person', 'per_field'}. Within one field the best co-owner counts (a joint owner
    string names several people). Across fields, a match beside a field naming someone else
    (a conflict, or a person who does not line up at all) is a disagreement, not a match: the
    first live sweep met a defendant who is the debtor on a parcel whose owner_name names two
    other people of the same family."""
    per_field: dict[str, dict] = {}
    for field, name in board_names(row, claim):
        persons = persons_of(name)
        if not persons:
            continue
        scored = [(person_verdict(p, debtors), p) for p in persons]
        v, p = max(scored, key=lambda vp: _RANK[vp[0]])
        per_field[field] = {"name": name, "verdict": v, "person": p}
    if not per_field:
        return {"verdict": "no_person", "field": None, "person": None, "per_field": per_field}
    matches = [(f, d) for f, d in per_field.items() if d["verdict"] in ("agrees", "unverified")]
    others =[f for f, d in per_field.items() if d["verdict"] in ("conflict", "none")]
    if matches and others:
        return {"verdict": "names_disagree", "field": None, "person": None, "per_field": per_field}
    if matches:
        f, d = max(matches, key=lambda fd: _RANK[fd[1]["verdict"]])
        return {"verdict": d["verdict"], "field": f, "person": d["person"], "per_field": per_field}
    best_f, best = max(per_field.items(), key=lambda fd: _RANK[fd[1]["verdict"]])
    return {"verdict": best["verdict"], "field": best_f, "person": best["person"],
            "per_field": per_field}


# ---------------------------------------------------------------------------
# status: what the docket entries say (pure)
# ---------------------------------------------------------------------------

_NOT_AN_ORDER = re.compile(
    r"\b(?:motions?|objections?|response|hearing|withdraw\w*|request|application|stipulat\w*|"
    r"complaint|adversary|show cause|appeal|claims?|party|creditor)\b")
_CLOSED = re.compile(r"\bfinal decree\b|\bcase closed\b|\bclosed without discharge\b|"
                     r"\bclos(?:e|ed|ing) (?:the )?(?:bankruptcy )?case\b")
_DISCHARGE = re.compile(r"\bdischarg(?:e|ed|ing)\b")
_NOT_DISCHARGE = re.compile(r"nondischarg|dischargeab|\bden(?:y|ied|ying)\b|\brevok|\bwaiv|"
                            r"\bwithout\b|\bno discharge\b|\bineligib|\bnot eligible\b|\bcertific|"
                            r"\brequire\w*|\bcourse\b|\bintent\b|\btrustee\b")
_DISMISS = re.compile(r"\bdismiss(?:al|ed|ing)?\b")
_GRANT_DISMISS = re.compile(r"\border\b.*\bgrant\w*\b.*\bdismiss")
_REINSTATE = re.compile(r"\breinstat\w*|\bvacat\w*\b.*\bdismiss|\bset(?:ting)? aside\b.*\bdismiss")
_CONVERT = re.compile(r"\bconver(?:t|ted|ting|sion)\b")
_RELIEF = re.compile(r"relief from (?:the )?(?:automatic )?stay|\blift(?:ing)? (?:the )?(?:automatic )?stay|"
                     r"\bstay relief\b|\bterminat\w* (?:the )?(?:automatic )?stay")


def entry_text(entry: dict) -> str:
    """An entry's short description(s): the RSS-fed entries carry it on the RECAP document."""
    parts = [str(entry.get("description") or "")]
    for rd in entry.get("recap_documents") or []:
        if isinstance(rd, dict):
            parts.append(str(rd.get("description") or ""))
    return " | ".join(p.strip() for p in parts if p and p.strip())


def classify_entry(text: str) -> Optional[str]:
    """'closed' | 'discharge' | 'dismissal' | 'reinstated' | 'converted' | 'relief_from_stay' |
    None. Motions, objections, hearings and notices of them never close a case; an order
    GRANTING a motion to dismiss does."""
    d = text.lower()
    if not d:
        return None
    if _REINSTATE.search(d) and not re.search(r"\bmotions?\b", d):
        return "reinstated"
    if _CLOSED.search(d):
        return "closed"
    motionish = bool(_NOT_AN_ORDER.search(d))
    if _DISCHARGE.search(d) and not motionish and not _NOT_DISCHARGE.search(d):
        return "discharge"
    if _DISMISS.search(d) and (not motionish or _GRANT_DISMISS.search(d)) \
            and not re.search(r"\badversary\b|\bappeal\b|\bclaims?\b", d):
        return "dismissal"
    if _RELIEF.search(d):
        return "relief_from_stay"
    if _CONVERT.search(d) and not motionish:
        return "converted"
    return None


def _d(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def case_status(hit: dict, entries: list[dict], today: date) -> dict:
    """{'status': 'open'|'closed'|'unknown', 'event', 'last_activity', 'entries_seen', ...}.
    closed: dateTerminated, or a dismissal/discharge/closing entry no later reinstatement undid.
    open: none of that, and an entry within ACTIVE_DAYS. unknown: no entries, or none recent."""
    rows = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        txt = entry_text(e)
        rows.append({"date": str(e.get("date_filed") or "")[:10] or None,
                     "entry_number": e.get("entry_number"), "description": txt[:160],
                     "kind": classify_entry(txt)})
    rows.sort(key=lambda r: (r["date"] or "", r["entry_number"] or 0), reverse=True)
    out: dict[str, Any] = {"entries_seen": len(rows)}
    dated = [r["date"] for r in rows if r["date"]]
    out["last_activity"] = dated[0] if dated else None
    relief = [{"date": r["date"], "description": r["description"]} for r in rows
              if r["kind"] == "relief_from_stay"]
    if relief:
        out["relief_from_stay_entries"] = relief[:5]
    conv = next((r for r in rows if r["kind"] == "converted"), None)
    if conv:
        out["converted"] = {"date": conv["date"], "description": conv["description"]}
    terminal = [r for r in rows if r["kind"] in ("closed", "discharge", "dismissal")]
    reinst = next((r for r in rows if r["kind"] == "reinstated"), None)
    if terminal:
        out["terminal_entries"] = [{k: r[k] for k in ("date", "entry_number", "kind", "description")}
                                   for r in terminal[:4]]
    term = hit.get("date_terminated")
    if term:
        out.update(status="closed", event={"kind": "date_terminated", "date": str(term)[:10]})
        return out
    if terminal:
        t = terminal[0]
        if reinst and (reinst["date"] or "") > (t["date"] or ""):
            out["reinstated"] = {"date": reinst["date"], "description": reinst["description"]}
        else:
            out.update(status="closed", event={k: t[k] for k in ("kind", "date", "entry_number",
                                                                   "description")})
            return out
    if not rows:
        out["status"] = "unknown"
        out["reason"] = "no_docket_entries"
        return out
    last = _d(out["last_activity"])
    if last is not None and (today - last).days <= ACTIVE_DAYS:
        out["status"] = "open"
    else:
        out["status"] = "unknown"
        out["reason"] = "no_recent_docket_activity"
    return out


# ---------------------------------------------------------------------------
# the source
# ---------------------------------------------------------------------------

def _token() -> Optional[str]:
    """COURTLISTENER_TOKEN / COURTLISTENER_API_TOKEN, else .secrets/courtlistener_token.txt: the
    same loader enrichment_bankruptcy uses (scripts/run_local.sh exports the file as
    COURTLISTENER_TOKEN), plus the repo-absolute path so the sweep works from any cwd."""
    global _TOKEN, _TOKEN_LOADED
    if _TOKEN_LOADED:
        return _TOKEN
    tok = (os.environ.get("COURTLISTENER_TOKEN") or os.environ.get("COURTLISTENER_API_TOKEN") or "").strip()
    if not tok:
        for f in (Path(".secrets/courtlistener_token.txt"), _REPO / ".secrets" / "courtlistener_token.txt"):
            try:
                if f.is_file():
                    tok = f.read_text().strip()
                    break
            except OSError:
                continue
    _TOKEN, _TOKEN_LOADED = (tok or None), True
    return _TOKEN


def _headers() -> dict:
    h = {"Accept": "application/json"}
    tok = _token()
    if tok:
        h["Authorization"] = f"Token {tok}"
    return h


def _status_code(exc: BaseException) -> Optional[int]:
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None)


def _hit_of(h: dict) -> dict:
    """A /search/?type=r result or a /dockets/{id}/ record, in one shape."""
    if "caseName" in h or "docketNumber" in h:
        return {"case_name": h.get("caseName") or h.get("case_name_full") or "",
                "docket_number": h.get("docketNumber") or "", "court": h.get("court_id") or "",
                "docket_id": h.get("docket_id"), "date_filed": h.get("dateFiled"),
                "date_terminated": h.get("dateTerminated"), "chapter": (h.get("chapter") or "").strip(),
                "parties": [p for p in (h.get("party") or []) if p][:8],
                "absolute_url": h.get("docket_absolute_url") or ""}
    return {"case_name": h.get("case_name") or "", "docket_number": h.get("docket_number") or "",
            "court": h.get("court_id") or "", "docket_id": h.get("id"),
            "date_filed": h.get("date_filed"), "date_terminated": h.get("date_terminated"),
            "chapter": "", "parties": [], "absolute_url": h.get("absolute_url") or ""}


async def find_case(client, claim: dict) -> tuple[Optional[dict], dict]:
    """(hit, lookup evidence). hit None with lookup['not_found'] = the source has no such case;
    with lookup['error'] = it could not be asked."""
    look: dict[str, Any] = {"asked": []}
    did, court, dn = claim.get("docket_id"), (claim.get("court") or "").strip(), (claim.get("docket_number") or "").strip()
    errors = []
    if did:
        url = SEARCH_BY_ID.format(id=did)
        look["asked"].append(url)
        try:
            res = (await client.get_json(url, headers=_headers())).get("results") or []
            if res:
                return _hit_of(res[0]), look
        except Exception as exc:  # noqa: BLE001
            errors.append(type(exc).__name__)       # no message: it carries the URL
    if court and dn:
        url = SEARCH_BY_NUMBER.format(court=quote(court), dn=quote(dn))
        look["asked"].append(url)
        try:
            res = (await client.get_json(url, headers=_headers())).get("results") or []
            if res:
                want = (claim.get("case_name") or "").strip().lower()
                same = [h for h in res if (h.get("caseName") or "").strip().lower() == want]
                if len(res) > 1 and not same:
                    look["error"] = "ambiguous_docket_number"
                    look["candidates"] = [h.get("caseName") for h in res[:5]]
                    return None, look
                return _hit_of((same or res)[0]), look
        except Exception as exc:  # noqa: BLE001
            errors.append(type(exc).__name__)       # no message: it carries the URL
    if did:
        url = DOCKET_URL.format(id=did)
        look["asked"].append(url)
        try:
            return _hit_of(await client.get_json(url, headers=_headers())), look
        except Exception as exc:  # noqa: BLE001
            if _status_code(exc) == 404:
                look["not_found"] = True
                return None, look
            errors.append(type(exc).__name__)       # no message: it carries the URL
    if errors:
        look["error"] = "; ".join(errors)
        return None, look
    if not did and not (court and dn):
        look["error"] = "no_case_reference"
        return None, look
    look["not_found"] = True
    return None, look


# ---------------------------------------------------------------------------
# district / county consistency (pure) and identity corroboration (offline)
# ---------------------------------------------------------------------------

#: 28 U.S.C. 113(a)-(c), the counties of the three NC federal districts (the bankruptcy courts
#: sit in the same districts). Verified against the statute text 2026-10-06.
_NC_EASTERN = (
    "Beaufort Bertie Bladen Brunswick Camden Carteret Chowan Columbus Craven Cumberland Currituck "
    "Dare Duplin Edgecombe Franklin Gates Granville Greene Halifax Harnett Hertford Hyde Johnston "
    "Jones Lenoir Martin Nash|New_Hanover Northampton Onslow Pamlico Pasquotank Pender Perquimans "
    "Pitt Robeson Sampson Tyrrell Vance Wake Warren Washington Wayne Wilson")
_NC_MIDDLE = (
    "Alamance Cabarrus Caswell Chatham Davidson Davie Durham Forsyth Guilford Hoke Lee Montgomery "
    "Moore Orange Person Randolph Richmond Rockingham Rowan Scotland Stanly Stokes Surry Yadkin")
_NC_WESTERN = (
    "Alexander Alleghany Anson Ashe Avery Buncombe Burke Caldwell Catawba Cherokee Clay Cleveland "
    "Gaston Graham Haywood Henderson Iredell Jackson Lincoln McDowell Macon Madison Mecklenburg "
    "Mitchell Polk Rutherford Swain Transylvania Union Watauga Wilkes Yancey")
#: counties the statute splits: the Fort Bragg Military Reservation and Camp Mackall (parts of
#: Hoke, Moore, Richmond, Scotland) and the Butner FCI (part of Durham) are in the Eastern District
_NC_SPLIT = frozenset({"durham", "hoke", "moore", "richmond", "scotland"})


def _county_set(text: str) -> set[str]:
    out = set()
    for tok in text.replace("|", " ").split():
        out.add(tok.replace("_", " ").lower())
    return out


def _build_nc_courts() -> dict[str, frozenset]:
    out: dict[str, frozenset] = {}
    for court, names in (("nceb", _NC_EASTERN), ("ncmb", _NC_MIDDLE), ("ncwb", _NC_WESTERN)):
        for c in _county_set(names):
            out[c] = frozenset(out.get(c, frozenset()) | {court})
    for c in _NC_SPLIT:
        out[c] = frozenset({"ncmb", "nceb"})
    return out


NC_COUNTY_COURTS: dict[str, frozenset] = _build_nc_courts()
SC_COURT = "scb"


def expected_courts(state: Any, county: Any) -> Optional[frozenset]:
    """The bankruptcy court(s) that cover a county, or None when the state / county is not one
    this table knows (nothing is then claimed)."""
    st = str(state or "").strip().upper()
    co = re.sub(r"\s+county$", "", str(county or "").strip(), flags=re.I).lower()
    if st == "SC" and co:
        return frozenset({SC_COURT})
    if st == "NC":
        return NC_COUNTY_COURTS.get(co)
    return None


def wrong_district(court: Any, state: Any, county: Any) -> Optional[frozenset]:
    """The expected courts when `court` cannot cover the county, else None (covers, or unknown)."""
    exp = expected_courts(state, county)
    c = str(court or "").strip().lower()
    return exp if exp and c and c not in exp else None


VOTER_DIR = _REPO / "data" / "ncvoter"
_VOTER_STATUS_OK = frozenset({"ACTIVE", "INACTIVE"})


def _letters(s: Any) -> str:
    return re.sub(r"[^A-Z]", "", str(s or "").upper())


def debtor_full_name(person: Optional[str], case_name: str) -> Optional[tuple[str, str, str]]:
    """(first, middle, last), upper case, of the debtor in the case caption whose first and last
    name line up with the board person, or None when the caption names no middle name."""
    from ...name_normalize import owner_last_first_middle
    parts = owner_last_first_middle(person) if person else None
    if not parts:
        return None
    last, first, _mid = parts
    for side in re.split(r"\s+and\s+", str(case_name or ""), flags=re.I):
        toks = [t for t in re.sub(r"[^A-Za-z ]", " ", side).upper().split() if t not in _SUFFIXES]
        if len(toks) > 2 and toks[-1] == last and toks[0] == first:
            return first, toks[1], last
    return None


def _middle_agrees(debtor_mid: str, other_mid: str) -> bool:
    """Full middle names must be equal; when either side is an initial, the initials."""
    a, b = _letters(debtor_mid), _letters(other_mid)
    if not a or not b:
        return False
    return a == b if len(a) > 1 and len(b) > 1 else a[0] == b[0]


def _voter_matches(county: str, full: tuple[str, str, str], voter_dir: Path) -> Optional[list[dict]]:
    """The ACTIVE / INACTIVE registrants of the county's voter file with this full name, each
    {address}; None when the county has no file here."""
    import csv
    from ...enrichment_nc_voter_lookup import NC_COUNTY_IDS
    cid = NC_COUNTY_IDS.get(re.sub(r"\s+county$", "", county.strip(), flags=re.I).upper())
    path = voter_dir / f"ncvoter{cid}.txt" if cid else None
    if path is None or not path.is_file():
        return None
    first, mid, last = full
    needle = max(re.findall(r"[A-Z]+", last) or [last], key=len).encode()
    out = []
    with open(path, "rb") as fh:
        header = next(csv.reader([fh.readline().decode("utf-8", "replace")], delimiter="\t"))
        ix = {h: i for i, h in enumerate(header)}
        need = ("last_name", "first_name", "middle_name", "voter_status_desc", "res_street_address")
        if not all(k in ix for k in need):
            return None
        for line in fh:
            if needle not in line:
                continue
            cells = next(csv.reader([line.decode("utf-8", "replace")], delimiter="\t"))
            if len(cells) < len(header) or cells[ix["voter_status_desc"]].strip().upper() not in _VOTER_STATUS_OK:
                continue
            if _letters(cells[ix["last_name"]]) == _letters(last) and \
                    _letters(cells[ix["first_name"]]) == _letters(first) and \
                    _middle_agrees(mid, cells[ix["middle_name"]]):
                out.append({"address": re.sub(r"\s+", " ", cells[ix["res_street_address"]]).strip()})
    return out


def _roll_owner(row: dict) -> Optional[str]:
    from ... import parcel_cache
    try:
        rec = parcel_cache.lookup(str(row.get("county") or ""), str(row.get("parcel_id") or ""),
                                  str(row.get("state") or "") or None)
    except Exception:  # noqa: BLE001
        return None
    return str((rec or {}).get("owner") or "") or None


def corroborate_identity(row: dict, person: Optional[str], case_name: str, *,
                         voter_dir: Optional[Path] = None, roll_owner: Any = None
                         ) -> Optional[str]:
    """'ncvoter' | 'parcel_roll' | None: does the repo's own data show exactly ONE person with
    the debtor's full name (middle name or initial included) living at or owning the row's
    property? See CORROBORATION in the module docstring. Offline; never raises."""
    try:
        full = debtor_full_name(person, case_name)
        if full is None or str(row.get("state") or "").strip().upper() != "NC":
            return None
        first, mid, last = full
        addr = row.get("street_address")
        from . import _tax_common as tc
        vdir = Path(voter_dir or os.environ.get("VERIFY_NCVOTER_DIR") or VOTER_DIR)
        regs = _voter_matches(str(row.get("county") or ""), full, vdir)
        if regs is not None and len(regs) == 1 and tc.address_query(addr) and \
                tc.address_relation(addr, regs[0]["address"]) == "match":
            return "ncvoter"
        owner = (roll_owner or _roll_owner)(row)
        if owner and not re.search(r"deceased|decd|estate|\bet\s*al\b|\betux\b", owner, re.I):
            from ...name_normalize import owner_last_first_middle
            people = persons_of(owner)
            if len(people) == 1:
                p = owner_last_first_middle(people[0])
                if p and p[0] == last and p[1] == first and p[2] and _middle_agrees(mid, p[2]):
                    return "parcel_roll"
    except Exception:  # noqa: BLE001 - corroboration is a bonus, never a failure
        return None
    return None


# ---------------------------------------------------------------------------
# name patterns the positional matcher cannot see (pure); see NAME PATTERNS in the docstring
# ---------------------------------------------------------------------------

_MIN_FULL_NAME = 3        # a spelled-out middle name: an initial or a two-letter token proves nothing
_MIN_EDIT_NAME = 4        # a first name may differ by one edit only when the longer one has 4+ letters
_AND_SEGMENT = re.compile(r"\s+and\s+", re.I)
_ALIAS_SEGMENT = re.compile(r"\s+(?:a/?k/?a|f/?k/?a|n/?k/?a|d/?b/?a)\s+", re.I)
_US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
    "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
_MAIL_TAIL = re.compile(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\s*$")
NAME_PATTERN_REASON = "name_pattern_possible_same_person"


def debtor_segments(case_name: Any) -> list[tuple[str, tuple[str, ...], str]]:
    """(first, (middle names...), last), upper case, of every one-person segment of a case caption:
    split on a bare "and" (joint filers) and on aka / fka / nka / dba; suffixes dropped; an entity
    segment and a segment of fewer than two words left out."""
    from ...name_normalize import is_entity
    out: list[tuple[str, tuple[str, ...], str]] = []
    for side in _AND_SEGMENT.split(str(case_name or "")):
        for part in _ALIAS_SEGMENT.split(side.replace(".", "")):
            if not part.strip() or is_entity(part):
                continue
            toks = [t for t in re.sub(r"[^A-Za-z ]", " ", part).upper().split() if t not in _SUFFIXES]
            if len(toks) >= 2:
                out.append((toks[0], tuple(toks[1:-1]), toks[-1]))
    return out


def _same_given(a: str, b: str, typo_ok: bool = True) -> bool:
    """A first name: equal, or (typo_ok, the longer one 4+ letters) one substitution, insertion or
    deletion apart. No nickname table: this is not a person-matching rule, only the tolerance of
    a typo."""
    if len(a) < 2 or len(b) < 2:
        return False
    if a == b:
        return True
    if not typo_ok:
        return False
    short, long_ = sorted((a, b), key=len)
    if len(long_) < _MIN_EDIT_NAME or len(long_) - len(short) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def _full_middles(mids: tuple[str, ...]) -> set[str]:
    return {m for m in mids if len(m) >= _MIN_FULL_NAME}


def owner_readings(person: Optional[str]) -> list[tuple[str, str, bool]]:
    """The (SURNAME, FIRST, typo_ok) readings of one board person for the pattern check. A comma
    settles the order (name_normalize.owner_last_first_middle). Without one it is genuinely
    ambiguous (the county rolls write SURNAME FIRST MIDDLE, in capitals and sometimes in Title
    Case; the courts FIRST MIDDLE LAST), so both are read: the board's own convention first (capitals
    = surname first, any lower case = first name first, as owner_last_first_middle reads it), the
    other order second and only with exact first names (typo_ok False: a surname read as a first
    name is not a typo of one). A pattern needs two names to line up, which a wrong reading rarely
    does by chance, and a pattern only keeps a claim from being refuted."""
    from ...name_normalize import owner_last_first_middle
    raw = re.split(r"[;]|<br\s*/?>", str(person or ""), maxsplit=1)[0]
    if not raw.strip():
        return []
    if "," in raw:
        parts = owner_last_first_middle(raw)
        return [(parts[0], parts[1], True)] if parts else []
    toks = [t for t in re.sub(r"[^A-Za-z ]", " ", raw).upper().split() if t not in _SUFFIXES]
    if len(toks) < 2:
        return []
    surname_first, first_first = (toks[0], toks[1]), (toks[-1], toks[0])
    order = [first_first, surname_first] if re.search(r"[a-z]", raw) else [surname_first, first_first]
    out = [(order[0][0], order[0][1], True)]
    if order[1] != order[0]:
        out.append((order[1][0], order[1][1], False))
    return out


def name_pattern(person: Optional[str], case_name: Any) -> Optional[dict]:
    """{'pattern': 'maiden_name' | 'middle_as_first', 'across_debtors': bool} when the board
    person's name stands in one of the two shapes of NAME PATTERNS to a debtor of the case caption
    (under any owner_readings reading), else None. Pure. It says nothing about the court: see
    pattern_court_ok."""
    segs = debtor_segments(case_name)
    found: list[dict] = []
    for last, first, typo_ok in owner_readings(person):
        for f, mids, surname in segs:                          # one debtor's own names
            if last in _full_middles(mids) and _same_given(first, f, typo_ok):
                found.append({"pattern": "maiden_name", "across_debtors": False})
            if last == surname and first in _full_middles(mids):
                found.append({"pattern": "middle_as_first", "across_debtors": False})
        for i, (f, _m, _l) in enumerate(segs):                 # joint filers: first name of one,
            if _same_given(first, f, typo_ok) and any(         # middle name of the other as surname
                    j != i and last in _full_middles(mids)
                    for j, (_f, mids, _l2) in enumerate(segs)):
                found.append({"pattern": "maiden_name", "across_debtors": True})
    found.sort(key=lambda h: h["across_debtors"])
    return found[0] if found else None


def row_name_pattern(row: dict, claim: dict, case_name: Any) -> Optional[dict]:
    """name_pattern() over every person of every board name (board_names + persons_of), the
    first debtor-internal hit before an across-debtors one; adds the board field it came from."""
    hits = []
    for field, name in board_names(row, claim):
        for person in persons_of(name):
            p = name_pattern(person, case_name)
            if p:
                hits.append({**p, "field": field})
    hits.sort(key=lambda h: h["across_debtors"])
    return hits[0] if hits else None


def owner_mailing_state(row: dict) -> Optional[str]:
    """The two-letter state of the owner's mailing address as the board knows it (the county
    record's mail_state / state, skip-trace's mail_state, else the state and ZIP at the end of the
    mailing line), or None. A state code is only read off a mailing line when a ZIP follows it
    ("12 ELM CT" is a court, not Connecticut)."""
    raw = _raw(row)

    def sub(k: str) -> dict:
        v = raw.get(k)
        return v if isinstance(v, dict) else {}

    om, st, g = sub("owner_mailing"), sub("skip_trace"), sub("gis")
    for v in (om.get("mail_state"), om.get("state"), st.get("mail_state")):
        s = str(v or "").strip().upper()
        if s in _US_STATES:
            return s
    for v in (om.get("mailing"), st.get("owner_mailing_address"), g.get("mailing")):
        m = _MAIL_TAIL.search(re.sub(r"\s+", " ", str(v or "").upper()).strip())
        if m and m.group(1) in _US_STATES:
            return m.group(1)
    return None


def pattern_court_ok(court: Any, court_state: Optional[str], row_state: Optional[str],
                     county: Any, mail_state: Optional[str]) -> bool:
    """May a name pattern count in this court? The court's state is the row's state (as
    production's _COURT_STATE check), the court holds the property's county (wrong_district), and,
    where the board knows it, the owner's mailing state is the court's state."""
    if court_state and row_state and court_state != row_state:
        return False
    if wrong_district(court, row_state, county):
        return False
    if court_state and mail_state and court_state != mail_state:
        return False
    return True


# ---------------------------------------------------------------------------
# what is published (pure)
# ---------------------------------------------------------------------------

_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}


def middle_initials(person: Optional[str], debtor: str) -> tuple[Optional[str], list[str]]:
    """(the board person's middle initial, the middle initials of the debtors whose first and
    last name line up with that person): the evidence behind a middle verdict, initials only."""
    from ...name_normalize import owner_last_first_middle
    parts = owner_last_first_middle(person) if person else None
    if not parts:
        return None, []
    last, first, mid = parts
    out = []
    for side in re.split(r"\s+and\s+", str(debtor or ""), flags=re.I):
        toks = [t for t in re.sub(r"[^A-Za-z ]", " ", side).upper().split() if t not in _SUFFIXES]
        if len(toks) > 2 and toks[-1] == last and toks[0] == first:
            out.append(toks[1][0])
    return (mid or None), sorted(set(out))


_PUBLIC_COMMON = ("decided_by", "reason", "owner_match", "match_field", "compared_fields",
                  "claimed_from", "court", "court_state", "expected_courts",
                  "identity_corroborated_by", "name_pattern", "name_pattern_across_debtors")
_PUBLIC_CASE = ("docket_number", "docket_id", "chapter", "date_filed", "date_terminated")
_PUBLIC_STATUS = ("status", "last_activity", "entries_seen")


def public_evidence(verdict: str, ev: dict) -> dict:
    """The evidence a verdict may publish (WHAT IS PUBLISHED in the module docstring): a
    whitelist, so nothing new leaks by being added to the working dict. Idempotent, so
    migrate_ledger() can run it over entries already stored in either shape."""
    ev = dict(ev or {})
    m = ev.get("match") if isinstance(ev.get("match"), dict) else {}
    if m:
        ev.setdefault("match_field", m.get("field"))
        ev.setdefault("compared_fields", sorted((m.get("per_field") or {}).keys()))
    claimed = ev.get("claimed") if isinstance(ev.get("claimed"), dict) else {}
    if claimed.get("from"):
        ev.setdefault("claimed_from", claimed["from"])
    out = {k: ev.get(k) for k in _PUBLIC_COMMON}
    if verdict in ("confirmed", "stale"):
        out.update({k: ev.get(k) for k in _PUBLIC_CASE + _PUBLIC_STATUS})
        out["owner_middle_initial"] = ev.get("owner_middle_initial")
        out["debtor_middle_initials"] = ev.get("debtor_middle_initials")
        relief = ev.get("relief_from_stay_entries") or ev.get("relief_from_stay_dates") or []
        out["relief_from_stay_dates"] = [r.get("date") if isinstance(r, dict) else r for r in relief]
        conv = ev.get("converted")
        out["converted_on"] = conv.get("date") if isinstance(conv, dict) else ev.get("converted_on")
        rein = ev.get("reinstated")
        out["reinstated_on"] = rein.get("date") if isinstance(rein, dict) else ev.get("reinstated_on")
        evt = ev.get("event")
        if isinstance(evt, dict):
            out["event"] = {k: evt.get(k) for k in ("kind", "date", "entry_number") if evt.get(k)}
        term = ev.get("terminal_entries") or ev.get("terminal_events") or []
        out["terminal_events"] = [{"kind": t.get("kind"), "date": t.get("date")}
                                  for t in term if isinstance(t, dict)]
    elif verdict == "refuted":
        out["debtor_count"] = ev.get("debtor_count")
        if ev.get("decided_by") == "middle_conflict":
            out["owner_middle_initial"] = ev.get("owner_middle_initial")
            out["debtor_middle_initials"] = ev.get("debtor_middle_initials")
    else:
        out.update({k: ev.get(k) for k in _PUBLIC_STATUS})
        err = ev.get("error")
        if err:
            out["error"] = str(err).split(":", 1)[0][:60]      # the exception type, no URL
    return {k: v for k, v in out.items() if v not in (None, "", [], {})}


def migrate_ledger(led: Any) -> int:
    """Rewrite a loaded bankruptcy_stay Ledger in place to the published shape: every entry's
    latest.evidence through public_evidence(), ROW_SUMMARY_EXCLUDE dropped from its row summary.
    No fetch; verdicts and stamps unchanged (history entries carry stamps only). Returns the
    number of entries changed."""
    changed = 0
    for e in led.rows.values():
        before = json.dumps(e, sort_keys=True, default=str)
        lat = e.get("latest")
        if isinstance(lat, dict) and isinstance(lat.get("evidence"), dict):
            lat["evidence"] = public_evidence(str(lat.get("verdict")), lat["evidence"])
        if isinstance(e.get("row"), dict):
            for f in ROW_SUMMARY_EXCLUDE:
                e["row"].pop(f, None)
        changed += json.dumps(e, sort_keys=True, default=str) != before
    return changed


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def _res(verdict: str, evidence: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(verdict, evidence), source=SOURCE,
                  version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    claim = claim_of(row)
    if claim is None:
        return _res("unconfirmed", {"reason": "no_bankruptcy_claim"})
    claimed = {k: v for k, v in claim.items() if v not in (None, "")}
    names = board_names(row, claim)
    if not any(persons_of(n) for _, n in names):
        reason = ("no_owner_of_record_on_board" if claim["from"] == "listing"
                  else "no_person_owner_on_board")
        return _res("unconfirmed", {"reason": reason, "claimed": claimed,
                                    "board_names": dict(names)})

    hit, look = await find_case(client, claim)
    ev: dict[str, Any] = {"claimed": claimed, "lookup": look["asked"]}
    if hit is None:
        if look.get("not_found"):
            ev["decided_by"] = "case_not_found"
            return _res("refuted", ev)
        ev["reason"] = look.get("error") or "lookup_failed"
        if look.get("candidates"):
            ev["candidates"] = look["candidates"]
        return _res("unconfirmed", ev)

    from ...enrichment_bankruptcy import _COURT_STATE
    court_state = _COURT_STATE.get(hit["court"])
    row_state = str(row.get("state") or "").strip().upper() or None
    ev.update({
        "url": (SITE + hit["absolute_url"]) if hit["absolute_url"] else None,
        "court": hit["court"], "court_state": court_state, "docket_number": hit["docket_number"],
        "docket_id": hit["docket_id"], "chapter": hit["chapter"] or None,
        "date_filed": hit["date_filed"], "date_terminated": hit["date_terminated"],
        "debtor_case_name": hit["case_name"], "parties": hit["parties"],
    })
    if claim.get("docket_number") and hit["docket_number"] and \
            claim["docket_number"].strip() != hit["docket_number"].strip():
        ev["docket_number_mismatch"] = True

    ident = judge_identity(row, claim, [hit["case_name"]])
    ev["owner_match"] = ident["verdict"]
    ev["debtor_count"] = len([s for s in re.split(r"\s+and\s+", hit["case_name"], flags=re.I) if s.strip()])
    ev["owner_middle_initial"], ev["debtor_middle_initials"] = middle_initials(ident["person"], hit["case_name"])
    ev["match"] = {"rule": "name_normalize.debtor_positional_match + debtor_middle_verdict",
                   "field": ident["field"], "person": ident["person"],
                   "per_field": ident["per_field"]}
    v = ident["verdict"]
    if v in ("conflict", "none"):
        # a pattern the positional matcher cannot see (a maiden name, a middle name used as the
        # first name) in a court that can cover the property: not a different person, undecided
        pat = row_name_pattern(row, claim, hit["case_name"])
        if pat is not None and pattern_court_ok(hit["court"], court_state, row_state,
                                                row.get("county"), owner_mailing_state(row)):
            ev["name_pattern"] = pat["pattern"]
            if pat["across_debtors"]:
                ev["name_pattern_across_debtors"] = True
            ev["reason"] = NAME_PATTERN_REASON
            return _res("unconfirmed", ev)
    if v == "conflict":
        ev["decided_by"] = "middle_conflict"
        return _res("refuted", ev)
    if v == "none":
        ev["decided_by"] = "no_positional_match"
        return _res("refuted", ev)
    if v in ("names_disagree", "order_ambiguous", "no_person"):
        ev["reason"] = {"names_disagree": "board_names_disagree",
                        "order_ambiguous": "owner_name_order_ambiguous",
                        "no_person": "no_person_owner_on_board"}[v]
        return _res("unconfirmed", ev)
    if court_state and row_state and court_state != row_state:
        ev["reason"] = "court_state_differs"
        return _res("unconfirmed", ev)
    exp = wrong_district(hit["court"], row_state, row.get("county"))
    if exp:
        ev["expected_courts"] = sorted(exp)
        ev["reason"] = "wrong_district"      # this court cannot cover the property's county
        return _res("unconfirmed", ev)

    if not hit["docket_id"]:
        ev["reason"] = "no_docket_id"
        return _res("unconfirmed", ev)
    eurl = ENTRIES_URL.format(id=hit["docket_id"])
    ev["entries_url"] = eurl
    try:
        data = await client.get_json(eurl, headers=_headers())
        entries = data.get("results") or []
    except Exception as exc:  # noqa: BLE001
        code = _status_code(exc)
        ev["reason"] = ("no_courtlistener_token" if code in (401, 403) and not _token()
                        else "entries_fetch_failed")
        ev["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return _res("unconfirmed", ev)
    st = case_status(hit, entries, today)
    ev["status"] = st.pop("status")
    ev.update(st)
    if ev["status"] == "closed":
        ev["decided_by"] = f"{ev['event']['kind']}+positional_match_{v}"
        if v != "agrees":
            # "the case is over" needs a verified debtor: a first + last match with no middle
            # name to compare is not one, unless the repo's own data corroborates the person
            via = await asyncio.to_thread(corroborate_identity, row, ident["person"],
                                          hit["case_name"])
            if via is None:
                ev["reason"] = "identity_unverified"
                return _res("unconfirmed", ev)
            ev["identity_corroborated_by"] = via
        return _res("stale", ev)
    if ev["status"] == "open":
        ev["decided_by"] = f"open+positional_match_{v}"
        return _res("confirmed", ev)
    return _res("unconfirmed", ev)
