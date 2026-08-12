"""Register-of-deeds lookup across the three verified "The Lookup" counties.

WHAT THIS READS
    The county register of deeds — where deeds of trust, substitutions of
    trustee, trustee's deeds and satisfactions are recorded. It is the primary
    distress record and this project has never read a county-run one.

    Doc-type vocabulary confirmed live against Haywood NC:

        S/T       substitution of trustee — in NC this is filed when a lender
                  STARTS a foreclosure. The earliest public signal there is.
        TR/D      trustee's deed — the foreclosure sale completed
        D/T       deed of trust (the mortgage itself)
        CAN D/T   cancelled deed of trust  } the loan is gone; a lien the board
        SAT D/T   satisfied deed of trust  } still shows is stale
        ASGM      assignment (servicer change)
        DEED      ordinary conveyance

    S/T and CAN/SAT D/T are the two that change a decision: one says a
    foreclosure has begun, the others say a debt this engine may still be
    counting has been paid off.

WHY THIS IS AN ENRICHER AND NOT A SCRAPER
    The platform has a `received` search that takes a date range — the obvious
    "what was filed this week" bulk path. It also requires `received_from`, a
    free-text field naming the party who SUBMITTED the document. Wildcards
    ("%", "A") return an empty body, so it cannot be walked without knowing the
    filer. Until that is solved this reads by NAME, which means it can only
    enrich leads already on the board.

    That limit is worth stating plainly: it makes this a lookup, not a source of
    new leads. Clay, Haywood and Yancey hold ZERO board leads today, so with a
    name-keyed reader alone this enricher has nothing to enrich — the bulk path
    below is what would actually open them.

    The `browse` search is that path: it returns the full party index with a
    document count per name and needs no name in advance. Walking it is how
    these three counties become a source rather than a lookup, and it is the
    single highest-value piece of unbuilt work this module points at.

ACCESS — the three traps, every one of which returns HTTP 200
    1. GET, never POST. A POST to content.php returns a 2,065-byte tab shell for
       every search type, including a valid name search.
    2. `embed=1` is required and appears in NO form on the page. It was found by
       reading the row links inside a working browse result.
    3. The disclaimer is cleared with GET index.php?Accept=Accept, not by
       POSTing the Accept button the form advertises.
    See docs/ROD_PORTAL_ACCESS.md for the full derivation.

POLITENESS
    These are small county servers and one already timed out under three
    back-to-back requests. Every call is rate-limited and the whole pass is
    capped; a lookup is cached permanently because a recorded instrument does
    not change.
"""
from __future__ import annotations

import os
import re
import time
from typing import Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

#: county -> search host, VERIFIED BY FETCHING, not by URL pattern.
#:
#: A previous version of this file listed twelve counties here. Nine of them do
#: not run this platform at all: they 404 on content.php and serve a different
#: system ("<County> County Online Record System", entered at NameSearch.php),
#: which lives in scrapers/counties_sc/sc_rod_name_index.py. Bertie NC serves
#: only a 2,617-byte disclaimer loop.
#:
#: Every one of those nine returned HTTP 200 to the accept step, so the wrong
#: list looked healthy and this enricher would have reported "no records" for
#: them forever. The three below are the ones where a browse actually returns
#: rows. Verify before adding a fourth — see docs/ROD_PORTAL_ACCESS.md.
#:
#: All three are core-footprint Western NC counties that currently hold ZERO
#: board leads, which is exactly where new coverage is worth the most.
LOOKUP_HOSTS: dict[tuple[str, str], str] = {
    ("clay", "NC"): "http://search.claydeeds.com",
    ("haywood", "NC"): "http://search.haywooddeeds.com",
    ("yancey", "NC"): "http://search.yanceydeeds.com",
}

#: Same-named counties exist in other states and `<county>deeds.com` does not
#: say which one it is. hendersondeeds.com is Henderson County KENTUCKY and
#: wilsondeeds.com is Wilson County TENNESSEE; both were nearly adopted as NC
#: sources by pattern matching alone. Each host above was confirmed against the
#: county's own government site: haywoodcountync.gov links haywooddeeds.com, and
#: claydeeds.com resolves to deeds.claync.us. Yancey is the only Yancey County
#: in the United States, so its name is unambiguous.
VERIFIED_AGAINST = {
    ("clay", "NC"): "www.clayconc.com -> deeds.claync.us",
    ("haywood", "NC"): "www.haywoodcountync.gov links haywooddeeds.com",
    ("yancey", "NC"): "nationally unique county name",
}

#: Instruments that change a decision, mapped to what they mean. Codes confirmed
#: live in bulk windows: a Haywood pick-list run returns DEED, P/A, SAT, D/T,
#: EASE, AFDVT, S/T, M/A — note the bare "SAT", which an earlier version of this
#: map missed because it only listed "SAT D/T".
DISTRESS_DOC_TYPES = {
    "S/T": "substitution_of_trustee",
    "SUB TRUSTEE": "substitution_of_trustee",
    "TR/D": "trustees_deed",
    "TRUSTEE DEED": "trustees_deed",
    "CAN D/T": "deed_of_trust_cancelled",
    "SAT": "deed_of_trust_satisfied",
    "SAT D/T": "deed_of_trust_satisfied",
    "CERT/SAT": "deed_of_trust_satisfied",
    "D/T": "deed_of_trust",
}

_MIN_INTERVAL_S = float(os.environ.get("ROD_LOOKUP_INTERVAL_S", "4.0"))
_MAX_LOOKUPS = int(os.environ.get("ROD_LOOKUP_MAX", "150"))
_TIMEOUT_S = float(os.environ.get("ROD_LOOKUP_TIMEOUT_S", "90"))

_last_call: dict[str, float] = {}


def _throttle(host: str) -> None:
    """One request per host per _MIN_INTERVAL_S. Haywood timed out at three
    back-to-back requests, so this is a real constraint, not decoration."""
    prev = _last_call.get(host)
    if prev is not None:
        wait = _MIN_INTERVAL_S - (time.monotonic() - prev)
        if wait > 0:
            time.sleep(wait)
    _last_call[host] = time.monotonic()


def _session(host: str):
    """Accept the disclaimer once and return a session holding the PHPSESSID."""
    from curl_cffi import requests as creq
    s = creq.Session(impersonate="chrome")
    _throttle(host)
    r = s.get(f"{host}/index.php?Accept=Accept", timeout=_TIMEOUT_S)
    if r.status_code != 200 or "lookup" not in r.text.lower():
        raise RuntimeError(f"disclaimer not cleared for {host} ({r.status_code})")
    return s


def _rows(html: str) -> list[dict]:
    """Parse the result table. Column order confirmed live:
    Date | Book Info | Doc Type | Property Desc | Search Party Type |
    Searched Party | Reverse Party | XRef | Clipboard | Image?"""
    out: list[dict] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).replace("\xa0", " ")
            .replace("&nbsp;", " ").strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        ]
        if len(cells) < 7 or not cells[0]:
            continue
        # The header row survives the <td> filter on this platform.
        if cells[0].lower().startswith("date") or cells[2] == "Party Type":
            continue
        m = re.match(r"(\d{8})\s+(\d{2}/\d{2}/\d{4})", cells[0])
        out.append({
            "recorded": m.group(2) if m else cells[0],
            "book_info": cells[1],
            "doc_type": cells[2],
            "property_desc": cells[3],
            "party_role": cells[4],
            "party": cells[5],
            "reverse_party": cells[6],
            "kind": DISTRESS_DOC_TYPES.get(cells[2].upper().strip()),
        })
    return out


def lookup_name(county: str, state: str, name: str) -> list[dict]:
    """Recorded instruments for one party. [] when the county is not on this
    platform or the lookup fails — never raises into a run."""
    host = LOOKUP_HOSTS.get((county.strip().lower(), state.strip().upper()))
    if not host or not name.strip():
        return []
    try:
        s = _session(host)
        _throttle(host)
        r = s.get(
            f"{host}/content.php",
            params={
                "embed": "1",                 # REQUIRED and in no form on the page
                "display_name": name.strip(),
                "party_type": "", "entity_type": "",
                "searchType": "name", "wildCard": "Exact",
            },
            headers={"Referer": f"{host}/index.php?Accept=Accept"},
            timeout=_TIMEOUT_S,
        )
        if r.status_code != 200:
            return []
        # A 2,065-byte tab shell is what a REJECTED search returns with status
        # 200. Treating it as "no records" would report an empty county forever.
        if len(r.text) < 4000 and "content_tabs-1" in r.text:
            log.warning("rod_lookup.shell_response", county=county, name=name[:40])
            return []
        return _rows(r.text)
    except Exception as exc:  # noqa: BLE001 - a lookup must never kill a run
        log.warning("rod_lookup.failed", county=county, name=name[:40],
                    error=f"{type(exc).__name__}: {str(exc)[:90]}")
        return []


#: The pick list truncates. Haywood returned EXACTLY 1000 parties for a 21-day
#: window while a 3-day window returned 385, so 1000 is a cap and not a count.
#: A capped window silently drops filings, which for a foreclosure-start feed
#: means missing the very leads the source exists to find.
PICK_LIST_CAP = 1000


def _split(start: str, end: str) -> list[tuple[str, str]]:
    """Halve a MM/DD/YYYY window. [] when it is already a single day."""
    from datetime import datetime, timedelta
    a = datetime.strptime(start, "%m/%d/%Y")
    b = datetime.strptime(end, "%m/%d/%Y")
    if (b - a).days < 1:
        return []
    mid = a + (b - a) / 2
    return [(a.strftime("%m/%d/%Y"), mid.strftime("%m/%d/%Y")),
            ((mid + timedelta(days=1)).strftime("%m/%d/%Y"), b.strftime("%m/%d/%Y"))]


def bulk_by_date(county: str, state: str, start: str, end: str,
                 batch: int = 30, _depth: int = 0) -> list[dict]:
    """Every instrument recorded in a window, no name needed. MM/DD/YYYY.

    This is the path that turns these counties into a SOURCE. It is a name
    search with the name left blank, which the platform accepts, plus
    `show_pick_list=1`:

        1. GET content.php searchType=name last_name= start_date= end_date=
           show_pick_list=1        -> pick list: entityID[] + hidden fields
        2. GET content.php <hidden fields> entityID[]=... (repeated)
           -> the documents

    Step 2 must be GET. Posting the pick-list form the way the page's own
    `method="post"` declares returns the 2,065-byte shell.

    Batches are small on purpose: step 2 with 30 ids already returns 1.7 MB.
    """
    from urllib.parse import urlencode  # noqa: F401  (kept for clarity of intent)

    key = (county.strip().lower(), state.strip().upper())
    host = LOOKUP_HOSTS.get(key)
    if not host:
        return []
    try:
        s = _session(host)
        _throttle(host)
        r = s.get(f"{host}/content.php", params={
            "embed": "1", "searchType": "name", "last_name": "", "first_name": "",
            "party_type": "", "entity_type": "", "start_date": start,
            "end_date": end, "exact_match": "", "search_type": "Standard",
            "sort_type": "Date", "show_pick_list": "1"},
            headers={"Referer": f"{host}/index.php?Accept=Accept"},
            timeout=_TIMEOUT_S)
        if r.status_code != 200:
            return []
        ids = re.findall(r'name="entityID\[\]" value="(\d+)"', r.text)
        hidden = dict(re.findall(
            r'<input type="hidden" name="(\w+)" value="([^"]*)"', r.text))
        if not ids:
            return []

        # Capped: this window is truncated, so halve it and read both halves.
        # Returning the capped rows would look like a complete window.
        if len(ids) >= PICK_LIST_CAP and _depth < 6:
            halves = _split(start, end)
            if halves:
                log.info("rod_lookup.window_capped", county=county, start=start,
                         end=end, parties=len(ids), splitting_into=halves)
                out: list[dict] = []
                for a2, b2 in halves:
                    out += bulk_by_date(county, state, a2, b2, batch, _depth + 1)
                return out
            log.warning("rod_lookup.single_day_capped", county=county,
                        day=start, parties=len(ids),
                        reason="one day exceeds the pick-list cap; filings dropped")

        rows: list[dict] = []
        for i in range(0, len(ids), batch):
            q = [*hidden.items(), ("embed", "1")]
            q += [("entityID[]", e) for e in ids[i:i + batch]]
            _throttle(host)
            rr = s.get(f"{host}/content.php", params=q,
                       headers={"Referer": f"{host}/content.php"},
                       timeout=_TIMEOUT_S)
            if rr.status_code == 200 and len(rr.text) > 4000:
                rows += _rows(rr.text)

        log.info("rod_lookup.bulk", county=county, state=state, start=start,
                 end=end, parties=len(ids), rows=len(rows),
                 substitution_of_trustee=sum(
                     1 for x in rows if x["kind"] == "substitution_of_trustee"))
        return rows
    except Exception as exc:  # noqa: BLE001
        log.warning("rod_lookup.bulk_failed", county=county,
                    error=f"{type(exc).__name__}: {str(exc)[:90]}")
        return []


def enrich_rod_lookup(listings: Iterable[Listing]) -> dict:
    """Attach raw['rod_lookup'] to leads in the twelve covered counties.

    Only leads with an owner name are looked up, results are cached per
    (county, state, name) for the life of the process, and the pass stops at
    ROD_LOOKUP_MAX so a run cannot hammer a county server.
    """
    stats = {"eligible": 0, "looked_up": 0, "with_records": 0,
             "substitution_of_trustee": 0, "trustees_deed": 0,
             "deed_of_trust": 0, "satisfied_or_cancelled": 0, "skipped_cap": 0}
    cache: dict[tuple[str, str, str], list[dict]] = {}

    for li in listings:
        county = (getattr(li, "county", "") or "").strip().lower()
        state = (getattr(li, "state", "") or "").strip().upper()
        if (county, state) not in LOOKUP_HOSTS:
            continue
        owner = (getattr(li, "owner_name", "") or "").strip()
        if not owner:
            continue
        stats["eligible"] += 1
        if stats["looked_up"] >= _MAX_LOOKUPS:
            stats["skipped_cap"] += 1
            continue

        key = (county, state, owner.upper())
        if key not in cache:
            cache[key] = lookup_name(county, state, owner)
            stats["looked_up"] += 1
        recs = cache[key]
        if not recs:
            continue

        stats["with_records"] += 1
        kinds = {r["kind"] for r in recs if r["kind"]}
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["rod_lookup"] = {
            "county": county, "state": state, "matched_name": owner,
            "records": recs[:40],
            "has_substitution_of_trustee": "substitution_of_trustee" in kinds,
            "has_trustees_deed": "trustees_deed" in kinds,
            "open_deed_of_trust": "deed_of_trust" in kinds,
            "satisfied_or_cancelled": bool(
                {"deed_of_trust_cancelled", "deed_of_trust_satisfied"} & kinds),
        }
        if "substitution_of_trustee" in kinds:
            stats["substitution_of_trustee"] += 1
        if "trustees_deed" in kinds:
            stats["trustees_deed"] += 1
        if "deed_of_trust" in kinds:
            stats["deed_of_trust"] += 1
        if {"deed_of_trust_cancelled", "deed_of_trust_satisfied"} & kinds:
            stats["satisfied_or_cancelled"] += 1

    log.info("rod_lookup.done", **stats)
    return stats
