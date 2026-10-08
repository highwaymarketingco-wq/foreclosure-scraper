"""nc_ecourts_case, NC: is the court record the row was built from still in force at its source,
and is it about THIS row's owner?

THE CLAIMS. Four board sources build a lead from one hit of the NC AOC's open Judgment Search
(counties_nc.nc_ecourts_lis_pendens and its judgment_lien sub-slug, counties_nc.nc_ecourts_divorce,
nc_ecourts_judgments): a 'CV - Lis Pendens', 'CV - Claim of Lien', 'CV - Lien', 'CV - Transcript of
Judgment', tax-lien or condemnation judgment (listing type lis_pendens, scorer signal lis_pendens),
a docketed money judgment (signal judgment_lien), or a 'FAM - Divorce' judgment (listing type
divorce_notice plus raw.relationship_signal kind divorce: signals divorce_notice and divorce). The
scraper keeps a hit only while its civilJudgmentStatus is not terminal, but the board carries the
row for months after (the 2026-10-08 pre_publish checkpoint holds 8,794 NC lis_pendens rows from
these sources, 5,790 divorce rows), so nothing re-reads the status once the row exists.

THE SOURCE (open, no login, no CAPTCHA, no browser; the same endpoint and search object the
scraper uses, scrapers/counties_nc/nc_ecourts_lis_pendens.py):
    POST https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search
An empty POST returns the search-object template; the template with the county's District and
Superior Court Location buckets selected and a fromDate/toDate window returns every judgment of
that county ordered in the window. The free-text queryString does NOT match case numbers (read
live 2026-10-09: '26M001203-330', '26M001203330' and 'caseNumberSearch:...' all answer 0 hits), so
the case is found by its county and its own orderedDate: a three-day window around the date the
row stores (a few dozen hits in a mid-size county), paged when larger, and matched by caseNumber
plus judgmentId (or cause when the row has no judgmentId). One template request per process, one
search request per (county, window), cached for the run: rows of one county and day share it.

VERDICTS (core.py's meanings):
  confirmed    the judgment is in the index under the row's case number and cause, its status is
               not terminal, and the row's owner of record is not shown to be someone else.
  stale        the judgment is in the index and its status is now terminal (Canceled, Satisfied,
               Dismissed, Vacated, Withdrawn, Expired, Released, Terminated): it was in force when
               the row was built and is not any more. Read live 2026-10-09: a Forsyth claim of
               lien the board scored WARM (with an 'upset bid' window, see below) is Canceled.
  refuted      the judgment is real but the row's PROPERTY is someone else's: the row has a
               parcel or a numbered address, the county owner of record on the row names a person
               (or an entity), and no party of the judgment (the debtors; both spouses of a
               divorce) shares a surname (an entity: a distinctive word) with any owner name
               (property_binding 'conflict'). The judgment search names people, never property;
               the parcel came from the name resolver, and a different surname means it resolved
               to the wrong owner (read on the sample: a divorce whose party's surname differs
               by one letter from the parcel owner's).
  unconfirmed  the case is not in the index in its window (absence is not refutation: an
               expunged or re-dated judgment), the row's case number and its block's disagree
               (case_number_conflict: two records fused on one row), the cause differs, a party
               shares only a surname with the owner (surname_only: a relative or a namesake), or
               the service failed (fetch_failed / service_unhealthy / unreadable_answer, retried
               in 6 hours).
  wall         never: the endpoint is open. The CAPTCHA-walled Smart Search (special proceedings,
               estates) is not touched; its manual lanes are the walls_register cards nc_sp,
               nc_est and nc_verify.

property_binding (evidence): 'match' (a party matches an owner of record by production's
name_normalize.match_owner, exact or strong), 'conflict' (above), 'surname_only', 'unknown' (no
owner of record to compare), 'no_property' (the row has no parcel and no numbered address: the
claim names a person only and nothing about a property can be called).

GOVERNS (per record, governs_for): a divorce judgment governs ("divorce_notice", "divorce"); a
docketed money judgment ("judgment_lien",); every other cause ("lis_pendens", "upset_bid"). The
'upset_bid' is the scraper's own stamp: it treated a judgment's order date as a foreclosure sale
date and opened a 14-day upset-bid window on 1,146 rows of the 2026-10-08 checkpoint (claims of
lien, transcripts of judgment, tax liens; NC power-of-sale sales are special proceedings, which
this index does not hold). That stamp is removed at the source (scraper and enrich_upset_bid,
same commit); a stale or refuted verdict ends what a carried row still holds.

PRIVACY (the ledger is pushed to a PUBLIC repo): evidence holds the case number, county, cause,
statuses, dates, ids and the binding category with party and owner INITIALS only; never a party
or owner name. ROW_SUMMARY_EXCLUDE drops owner_name.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from ..core import VerificationResult, case_id, result

SIGNAL = "nc_ecourts_case"
VERSION = "v1"
TTL_DAYS = 14          # a lien is cancelled or satisfied, a judgment vacated, within weeks
RETRY_DAYS = 3
SOURCE = "portal-nc.tylertech.cloud (NC Judgment Search, open JSON)"
GOVERNS = ("lis_pendens", "upset_bid", "judgment_lien", "divorce_notice", "divorce")
ROW_SUMMARY_EXCLUDE = ("owner_name",)
IDENTITY = "case"
TRANSIENT_REASONS = ("fetch_failed", "service_unhealthy", "unreadable_answer")

SERVICE_URL = "https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search"
CLAIM_SOURCES = frozenset({
    "counties_nc.nc_ecourts_lis_pendens",
    "counties_nc.nc_ecourts_lis_pendens.judgment_lien",
    "counties_nc.nc_ecourts_divorce",
    "nc_ecourts_judgments",
})
CLAIM_TYPES = frozenset({"lis_pendens", "divorce_notice"})
PAGE_SIZE = 200
MAX_PAGES = 5                 # 1,000 hits in a three-day county window (Mecklenburg ~ 300)
WINDOW_BEFORE_DAYS = 1
WINDOW_AFTER_DAYS = 1
_CACHE_MAX = 512

_TERMINAL = re.compile(r"cancel|satisf|dismiss|vacat|withdr|expire|releas|terminat|closed|"
                       r"reversed|set aside", re.I)
_NAME = __name__.rsplit(".", 1)[-1]

#: per-process caches (the sweep is one process; tests reset them with reset_caches())
_TEMPLATE: dict = {}
_WINDOWS: dict = {}


def reset_caches() -> None:
    _TEMPLATE.clear()
    _WINDOWS.clear()


# ----------------------------------------------------------------------------------------------
# reading the row (dict from board_stream, or a models.Listing in the VM's apply step)
# ----------------------------------------------------------------------------------------------

def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def _raw(row: Any) -> dict:
    r = _get(row, "raw")
    return r if isinstance(r, dict) else {}


def _val(v: Any) -> Any:
    return getattr(v, "value", v)


def norm_case(v: Any) -> str:
    return re.sub(r"\s+", "", str(v or "")).upper()


def claim(row: Any) -> Optional[dict]:
    """The eCourts claim the row carries, normalized across the scrapers' two block shapes
    (nc_ecourts_lis_pendens / _divorce: cause, civilJudgmentStatus, caseID, judgmentId,
    orderedDate, location; nc_ecourts_judgments: case_number, cause_of_action,
    civil_judgment_status, case_id, judgment_id, judgment_date, court_name), or None."""
    raw = _raw(row)
    b = raw.get("nc_ecourts")
    if not isinstance(b, dict):
        return None
    cr = raw.get("court_record") if isinstance(raw.get("court_record"), dict) else {}
    row_case = norm_case(_get(row, "case_number"))
    blk_case = norm_case(b.get("case_number") or b.get("caseNumber"))
    cause = str(b.get("cause") or b.get("cause_of_action") or cr.get("cause") or "").strip()
    od = (b.get("orderedDate") or b.get("ordered_date_iso") or b.get("judgment_date")
          or cr.get("ordered_date"))
    location = str(b.get("location") or b.get("court_name") or cr.get("location") or "")
    county = str(_get(row, "county") or b.get("county") or "").strip()
    return {
        "case": row_case or blk_case,
        "row_case": row_case, "block_case": blk_case,
        "cause": cause,
        "ordered": str(od or "") or None,
        "location": location,
        "county": county,
        "status_scraped": str(b.get("civilJudgmentStatus") or b.get("civil_judgment_status") or ""),
        "judgment_id": b.get("judgmentId") or b.get("judgment_id"),
        "case_id": b.get("caseID") or b.get("case_id"),
        "signal": b.get("signal"),
    }


def claim_kind(c: dict, row: Any = None) -> str:
    """'divorce' | 'judgment_lien' | 'lien_or_lis_pendens'."""
    cause = (c or {}).get("cause") or ""
    if cause.startswith("FAM - Divorce"):
        return "divorce"
    src = str(_get(row, "source") or "") if row is not None else ""
    if (c or {}).get("signal") == "judgment_lien" or src.endswith(".judgment_lien"):
        return "judgment_lien"
    return "lien_or_lis_pendens"


def applies(row: dict) -> bool:
    """NC rows built from a Judgment Search hit (CLAIM_SOURCES) or typed lis_pendens /
    divorce_notice with the hit's block, with a case number, a county and an order date."""
    if str(_get(row, "state") or "").strip().upper() != "NC":
        return False
    c = claim(row)
    if not c or not c["case"] or not c["county"] or not c["ordered"] or not c["cause"]:
        return False
    src = str(_get(row, "source") or "")
    lt = str(_val(_get(row, "listing_type")) or "")
    return src in CLAIM_SOURCES or lt in CLAIM_TYPES


def case_identity(row: Any) -> Optional[str]:
    c = claim(row)
    if not c or not c["case"]:
        return None
    return case_id("ncj", "NC", c["county"].lower(), c["case"])


def priority(row: Any) -> int:
    """A row with a property (a parcel or a numbered address) first: the others name a person
    only and cannot be called about a property."""
    return 0 if has_property(row) else 1


# ----------------------------------------------------------------------------------------------
# the property and its owner of record
# ----------------------------------------------------------------------------------------------

def has_property(row: Any) -> bool:
    if str(_get(row, "parcel_id") or "").strip():
        return True
    a = str(_get(row, "street_address") or "").strip()
    m = re.match(r"(\d+)", a)
    return bool(m) and int(m.group(1)) > 0


def owner_names(row: Any) -> list[str]:
    """The owner-of-record strings the row carries (the board owner plus the county roll's,
    when the pipeline stored it), joint owners split. A string that IS a party name only (a
    divorce row's owner_name is the filing spouse until a resolver replaces it) is the caller's
    to drop."""
    raw = _raw(row)
    out: list[str] = []
    cands = [_get(row, "owner_name")]
    g = raw.get("gis")
    if isinstance(g, dict):
        cands.append(g.get("owner"))
    gf = raw.get("gis_attrs_full")
    if isinstance(gf, dict):
        cands.extend([gf.get("ownname"), gf.get("ownname2")])
    pa = raw.get("parcel_from_address")
    if isinstance(pa, dict):
        cands.append(pa.get("cache_owner"))
    for c in cands:
        for part in re.split(r";|\s&\s|\sAND\s|<br\s*/?>", str(c or ""), flags=re.I):
            p = part.strip(" ,")
            if p and p not in out:
                out.append(p)
    return out


def _tokens(name: str) -> set[str]:
    from ...name_normalize import core_tokens
    return set(core_tokens(name))


def _initials(name: str) -> str:
    from ...name_normalize import core_tokens
    return ".".join(t[0] for t in core_tokens(name)[:3])


def binding(parties: list[str], owners: list[str]) -> tuple[str, dict]:
    """(property_binding, detail) between the judgment's parties and the row's owner names."""
    from ...name_normalize import distinctive_tokens, is_entity, match_owner, owner_last_first_middle
    parties = [p for p in parties if str(p or "").strip()]
    owners = [o for o in owners if str(o or "").strip()]
    if not parties or not owners:
        return "unknown", {"parties": len(parties), "owners": len(owners)}
    detail: dict = {"parties": len(parties), "owners": len(owners)}
    surname_only = False
    for p in parties:
        for o in owners:
            m = match_owner(p, o)
            if m in ("exact", "strong"):
                detail.update(basis=m, party_initials=_initials(p), owner_initials=_initials(o))
                return "match", detail
            if is_entity(p) or is_entity(o):
                # an entity on either side: any shared distinctive word (a person's surname in a
                # family trust's or company's name) is not a conflict
                if set(distinctive_tokens(p)[:3]) & set(distinctive_tokens(o)[:3]):
                    surname_only = True
                continue
            pp, oo = owner_last_first_middle(p), owner_last_first_middle(o)
            plast = {pp[0]} if pp else set()
            olast = {oo[0]} if oo else set()
            # either reading of an un-comma'd roll name: its first token may be the surname
            if (plast | (_tokens(p) if not pp else set())) & (olast | _tokens(o)):
                surname_only = True
    if surname_only:
        return "surname_only", detail
    return "conflict", detail


# ----------------------------------------------------------------------------------------------
# the source
# ----------------------------------------------------------------------------------------------

def _day(v: Any) -> Optional[date]:
    s = str(v or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def window(ordered: Any) -> Optional[tuple[datetime, datetime]]:
    """The search window around the stored order date: the day before to the end of the day
    after (the stored value is the court's local date with a -05:00 offset)."""
    d = _day(ordered)
    if d is None:
        return None
    return (datetime(d.year, d.month, d.day) - timedelta(days=WINDOW_BEFORE_DAYS),
            datetime(d.year, d.month, d.day, 23, 59, 59) + timedelta(days=WINDOW_AFTER_DAYS))


def search_object(template: dict, county: str, w: tuple[datetime, datetime], page_from: int) -> dict:
    from ...scrapers.counties_nc.nc_ecourts_lis_pendens import _build_search_object
    return _build_search_object(template, counties=[county], from_date=w[0], to_date=w[1],
                                page_from=page_from, page_size=PAGE_SIZE)


def _headers() -> dict:
    from ...scrapers.counties_nc.nc_ecourts_lis_pendens import SERVICE_HEADERS
    return dict(SERVICE_HEADERS)


class _SourceError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def _parse(resp: Any) -> dict:
    status = getattr(resp, "status", 200)
    if status >= 500 or status in (403, 429):
        raise _SourceError("service_unhealthy", f"http {status}")
    if status >= 400:
        raise _SourceError("fetch_failed", f"http {status}")
    try:
        d = json.loads(getattr(resp, "text", "") or "")
    except (TypeError, ValueError):
        raise _SourceError("unreadable_answer", "not json") from None
    if not isinstance(d, dict):
        raise _SourceError("unreadable_answer", "not an object")
    return d


async def _template(s: Any) -> dict:
    if _TEMPLATE.get("t"):
        return _TEMPLATE["t"]
    d = _parse(await s.post_json(SERVICE_URL, None, headers=_headers()))
    if "searchResult" not in d or "facets" not in d:
        raise _SourceError("unreadable_answer", "no template")
    _TEMPLATE["t"] = d
    return d


async def _hits(s: Any, county: str, w: tuple[datetime, datetime], want_case: str) -> tuple[list[dict], dict]:
    """The county's hits in window w, paged until want_case is seen or the hits run out
    (cached per county and window)."""
    key = (county.lower(), w[0].isoformat(), w[1].isoformat())
    hit = _WINDOWS.get(key)
    if hit is not None and (hit["complete"] or any(norm_case(h.get("caseNumber")) == want_case
                                                   for h in hit["hits"])):
        return hit["hits"], {"total": hit["total"], "pages": hit["pages"], "cached": True}
    tpl = await _template(s)
    hits: list[dict] = list(hit["hits"]) if hit else []
    pages = hit["pages"] if hit else 0
    total = hit["total"] if hit else None
    complete = False
    while pages < MAX_PAGES:
        d = _parse(await s.post_json(SERVICE_URL, search_object(tpl, county, w, len(hits)),
                                     headers=_headers()))
        sr = d.get("searchResult") if isinstance(d.get("searchResult"), dict) else {}
        page = [h for h in (sr.get("hits") or []) if isinstance(h, dict)]
        pages += 1
        total = sr.get("totalHits") if isinstance(sr.get("totalHits"), int) else total
        hits.extend(page)
        if not page or (isinstance(total, int) and len(hits) >= total):
            complete = True
            break
        if any(norm_case(h.get("caseNumber")) == want_case for h in page):
            break
    if len(_WINDOWS) >= _CACHE_MAX:
        _WINDOWS.pop(next(iter(_WINDOWS)))
    _WINDOWS[key] = {"hits": hits, "total": total, "pages": pages, "complete": complete}
    return hits, {"total": total, "pages": pages, "cached": False, "complete": complete}


def pick(hits: list[dict], c: dict) -> tuple[Optional[dict], str]:
    """The hit that is the row's judgment: same case number in the row's county, then the same
    judgmentId, else the same cause. ('', reason) when none."""
    from ...scrapers.counties_nc.nc_ecourts_lis_pendens import _strip_court_suffix
    same = [h for h in hits if norm_case(h.get("caseNumber")) == c["case"]
            and _strip_court_suffix(h.get("location") or "").lower() == c["county"].lower()]
    if not same:
        return None, "case_not_in_index"
    jid = c.get("judgment_id")
    if jid not in (None, ""):
        by_id = [h for h in same if str(h.get("judgmentId")) == str(jid)]
        if by_id:
            return by_id[0], ""
    by_cause = [h for h in same if (h.get("causeOfActionDesc") or "") == c["cause"]]
    if not by_cause:
        return None, "cause_mismatch"
    live = [h for h in by_cause if not _TERMINAL.search(h.get("civilJudgmentStatus") or "")]
    return (live or by_cause)[0], ""


def _party_names(h: dict, kind: str) -> list[str]:
    deb = [str(p.get("name") or "") for p in (h.get("debtors") or []) if isinstance(p, dict)]
    if kind == "divorce":
        deb += [str(p.get("name") or "") for p in (h.get("creditors") or []) if isinstance(p, dict)]
    return [n for n in deb if n.strip()]


def governs_for(record: dict) -> tuple[str, ...]:
    kind = ((record or {}).get("evidence") or {}).get("claim_kind")
    if kind == "divorce":
        return ("divorce_notice", "divorce")
    if kind == "judgment_lien":
        return ("judgment_lien",)
    if kind == "lien_or_lis_pendens":
        return ("lis_pendens", "upset_bid")
    return GOVERNS


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client) -> VerificationResult:
    c = claim(row)
    if not c or not c["case"]:
        return _res("unconfirmed", {"reason": "no_case"})
    kind = claim_kind(c, row)
    ev: dict = {"case_number": c["case"], "county": c["county"], "cause": c["cause"],
                "claim_kind": kind, "ordered_date": str(c["ordered"])[:10],
                "status_scraped": c["status_scraped"] or None, "url": SERVICE_URL}
    if c["row_case"] and c["block_case"] and c["row_case"] != c["block_case"]:
        ev["reason"] = "case_number_conflict"
        return _res("unconfirmed", ev)
    w = window(c["ordered"])
    if w is None:
        ev["reason"] = "no_order_date"
        return _res("unconfirmed", ev)
    try:
        async with client.form_session() as s:
            hits, meta = await _hits(s, c["county"], w, c["case"])
    except _SourceError as exc:
        ev.update(reason=exc.reason, detail=exc.detail)
        return _res("unconfirmed", ev)
    except Exception as exc:  # noqa: BLE001 - any transport failure is a fetch failure
        ev.update(reason="fetch_failed", detail=f"{type(exc).__name__}: {str(exc)[:120]}")
        return _res("unconfirmed", ev)
    ev["window"] = [w[0].date().isoformat(), w[1].date().isoformat()]
    ev["window_hits"] = len(hits)
    ev["window_total"] = meta.get("total")
    h, why = pick(hits, c)
    if h is None:
        ev["reason"] = why
        if why == "case_not_in_index" and not meta.get("complete", True) and meta.get("total") \
                and len(hits) < meta["total"]:
            ev["reason"] = "window_truncated"
        return _res("unconfirmed", ev)
    status = str(h.get("civilJudgmentStatus") or "")
    ev.update(status_now=status or None, judgment_id=h.get("judgmentId"), case_id=h.get("caseID"),
              judgment_type=h.get("judgmentType"), location=h.get("location"),
              ordered_now=str(h.get("orderedDate") or "")[:10] or None)
    parties = _party_names(h, kind)
    if not has_property(row):
        pb, bd = "no_property", {"parties": len(parties)}
    else:
        owners = owner_names(row)
        ptoks = [_tokens(p) for p in parties]
        # a row whose only owner string IS a party (the scraper's own name, no roll owner) has
        # nothing independent to bind to
        owners = [o for o in owners if _tokens(o) and _tokens(o) not in ptoks] or (
            owners if str(_get(row, "parcel_id") or "").strip() else [])
        pb, bd = binding(parties, owners)
    ev["property_binding"] = pb
    ev["binding"] = bd
    if pb == "conflict":
        # the judgment is someone else's: the public ledger must not put its identifiers next to
        # this property (the bankruptcy verifier's rule for a refuted docket)
        for k in ("case_number", "judgment_id", "case_id", "binding"):
            ev.pop(k, None)
        ev["reason"] = "party_not_owner_of_record"
        return _res("refuted", ev)
    if _TERMINAL.search(status):
        ev["reason"] = "judgment_no_longer_in_force"
        return _res("stale", ev)
    if pb == "surname_only":
        ev["reason"] = "surname_only"
        return _res("unconfirmed", ev)
    return _res("confirmed", ev)
