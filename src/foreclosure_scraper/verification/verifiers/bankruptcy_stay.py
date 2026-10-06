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
thousands. So the outcome is read from the entries. 26-10161 (Bryan Christopher Tallant, the
Buncombe row at 539 Deaverview Rd the board scored as an open Chapter 13) has date_terminated
null and entry 25 "Dismissal" on 2026-09-21. 15-31086 (Conrad, a board "long-open" match filed
2015) has date_terminated null, "Discharge" on 2022-05-25 and "Final Decree/Case Closed" on
2022-09-15.

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
co-owner of a joint owner string is checked separately ("LAW BRANDON PETER;LAW BRITTANY LENORA").

VERDICTS (core.py's meanings):
  confirmed    the case exists; a board owner name matches a debtor positionally with no middle
               conflict (middle agrees, or one side has no middle: production's bar); the court is
               in the row's state (production's _COURT_STATE check); no dismissal, discharge or
               closing in the entries or dateTerminated; and a docket entry in the last
               ACTIVE_DAYS, so the stay is live.
  stale        the same real match, but the case was dismissed, discharged or closed (a later
               reinstatement undoes a dismissal): the stay WAS live and has lifted.
  refuted      the debtor is a different person (a proven middle conflict, or no debtor in the
               case lines up with any board owner name), or the case does not exist.
  unconfirmed  cannot decide: no person name (no owner of record) on the board to compare; two
               board names disagree (one matches, another names someone else); an ALL-CAPS owner that matches only
               when read FIRST MIDDLE LAST (owner_last_first_middle reads ALL-CAPS surname-first,
               "KIMBERLY A GOODALL"); a match whose court is in another state (the one place a
               first+last match is not enough: production rejects it, nothing here says it is a
               different person); no docket entries, or none in ACTIVE_DAYS, so the status
               cannot be read; an API failure.

GOVERNS: a refuted or stale verdict removes the scorer's `bankruptcy` signal (raw.bankruptcy in
distress_score._collect and the lead-signal facet, and the `bankruptcy` listing type) and the
stay (`bankruptcy_stay`: the facet, and distress_score's F3 WARM cap via _stay_block). Both
follow the scorer's own reading of a lapsed bankruptcy: a case that is over is no signal and no
stay. A stale verdict on a stayed foreclosure is the useful one: the sale can resume.
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from ..core import VerificationResult, result

SIGNAL = "bankruptcy_stay"
VERSION = "v2"         # v2 (2026-10-06): a match in one board name beside a person in another
                       # who does not match (not only one who conflicts) is unconfirmed
TTL_DAYS = 30          # refuted/stale (the verdicts that change the score) are durable facts;
                       # a confirmed-open case is re-read monthly
RETRY_DAYS = 7
SOURCE = "courtlistener.com"
GOVERNS = ("bankruptcy", "bankruptcy_stay")

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
    first live sweep met defendant 'Cheryl Delaine Overcash' (the debtor) on a parcel whose
    owner_name is 'OVERCASH RODNEY A;OVERCASH FRANCINE M'."""
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
            errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")
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
            errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")
    if did:
        url = DOCKET_URL.format(id=did)
        look["asked"].append(url)
        try:
            return _hit_of(await client.get_json(url, headers=_headers())), look
        except Exception as exc:  # noqa: BLE001
            if _status_code(exc) == 404:
                look["not_found"] = True
                return None, look
            errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")
    if errors:
        look["error"] = "; ".join(errors)
        return None, look
    if not did and not (court and dn):
        look["error"] = "no_case_reference"
        return None, look
    look["not_found"] = True
    return None, look


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def _res(verdict: str, evidence: dict) -> VerificationResult:
    return result(SIGNAL, verdict, evidence, source=SOURCE, version=VERSION, verifier=_NAME)


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
    ev["match"] = {"rule": "name_normalize.debtor_positional_match + debtor_middle_verdict",
                   "field": ident["field"], "person": ident["person"],
                   "per_field": ident["per_field"]}
    v = ident["verdict"]
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
        return _res("stale", ev)
    if ev["status"] == "open":
        ev["decided_by"] = f"open+positional_match_{v}"
        return _res("confirmed", ev)
    return _res("unconfirmed", ev)
