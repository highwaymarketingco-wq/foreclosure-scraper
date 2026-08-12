"""Register-of-deeds reader for the SC "Online Record System" platform.

WHAT THIS IS, AND WHY IT IS A SECOND MODULE
    Eight SC counties run a platform that is NOT "The Lookup" (see
    enrichment_rod_lookup.py). It was mistaken for the same system because both
    live on `<county>deeds.com` and both answer HTTP 200 to an accept step. They
    share no endpoints at all:

        The Lookup            index.php?Accept=Accept  -> content.php  (GET)
        Online Record System  NameSearch.php?Accept=…  -> NamePick.php (POST)
                                                      -> NameDisplay.php (POST)

    Pointing the Lookup reader at these hosts returns 404 with a 16-byte body,
    which a status-code check reads as "county has no records".

THE THREE-STEP FLOW, confirmed live against Georgetown SC
    1. GET  NameSearch.php?Accept=Accept       clears the disclaimer, sets PHPSESSID
    2. POST NamePick.php                        -> the PARTY index for the query
    3. POST NameDisplay.php                     -> the actual DOCUMENTS

    Step 2 is a picker, not a result set: it returns one checkbox per party with
    a document count. Step 3 takes those checkboxes back and returns the rows.
    Step 3 accepts ONLY the picker's own fields — igheader, igquerystring,
    displaybutton and the entityID boxes. Echoing the original search parameters
    back to it returns a 21-byte rejection.

WHAT A DOCUMENT ROW CARRIES
    Date | Code-Book-Page | Type | Description | Amount | Reverse Party |
    Cross-Ref | Img?

    Note the **Amount** column. The Lookup's index has no dollar figure at all,
    so for these counties a recorded amount is readable without OCRing the
    document image — see docs/ROD_PORTAL_ACCESS.md.

THE DATE FILTER IS HONOURED BY ONLY TWO OF THE EIGHT
    `searchLimit = 2000` is declared in the page. Five counties return exactly
    2000 (or 1996) parties for *every* window, including a single day, which for
    Colleton (population ~38k) is not a real day of recording. Those counties are
    returning the head of the whole index and ignoring the dates.

    This matters more than it looks: an unfiltered 2000-row response is large,
    well-formed and HTTP 200. Treating it as "last week's filings" would publish
    years-old instruments as fresh distress. Hence DATE_FILTER below is a
    measured fact per county, and bulk_by_date refuses to run where it is False.
"""
from __future__ import annotations

import os
import re
import time
from typing import Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

#: county -> host. Confirmed by fetching NameSearch.php and seeing a real search
#: UI (110-470 KB with an instType enumeration), not by URL pattern.
NAME_INDEX_HOSTS: dict[tuple[str, str], str] = {
    ("abbeville", "SC"): "http://search.abbevilledeeds.com",
    ("barnwell", "SC"): "https://barnwelldeeds.com",
    ("berkeley", "SC"): "http://search.berkeleydeeds.com",
    ("colleton", "SC"): "http://search.colletondeeds.com",
    ("dorchester", "SC"): "http://search.dorchesterdeeds.com",
    ("florence", "SC"): "http://search.florencedeeds.com",
    ("georgetown", "SC"): "https://georgetowndeeds.com",
    ("york", "SC"): "http://search.yorkdeeds.com",
}

#: Does the county actually apply start_date/end_date? MEASURED, by comparing a
#: one-day window against a one-month window on a fresh session each time.
#: True  -> counts differ and sit below the cap; the window is real.
#: False -> identical counts at the 2000 cap for every window; dates ignored.
#: None  -> not established (York timed out repeatedly on its 470 KB page).
DATE_FILTER: dict[tuple[str, str], bool | None] = {
    ("barnwell", "SC"): True,     # 24 in 7 days vs 230 in January
    ("georgetown", "SC"): True,   # 161 / 527 / 1374 across three windows
    ("abbeville", "SC"): False,   # 2000 for a single day
    ("berkeley", "SC"): False,    # 2000 for a single day
    ("colleton", "SC"): False,    # 2000 for a single day
    ("dorchester", "SC"): False,  # 1996 for every window
    ("florence", "SC"): False,    # 1973 for every window
    ("york", "SC"): None,         # unestablished — timeout, not a wall
}

SEARCH_LIMIT = 2000

#: Instruments that signal distress, matched against the row's Type. Built from
#: the instType enumerations these eight counties actually publish (111-318 types
#: each), not from a generic vocabulary.
DISTRESS_TYPE_RE = re.compile(
    r"LIS\s*PEND|FORECLOS|NOT(?:ICE)?\s*OF\s*LEVY|NOTICE\s*OF\s*SEIZURE|"
    r"SEIZURE|TAX\s*LIEN|JUDG|EXECUTION|MECH(?:ANIC)?S?\s*LIEN|"
    r"MASTER\s*IN\s*EQUITY|SHERIFF",
    re.I,
)

_MIN_INTERVAL_S = float(os.environ.get("ROD_NAME_INDEX_INTERVAL_S", "4.0"))
_TIMEOUT_S = float(os.environ.get("ROD_NAME_INDEX_TIMEOUT_S", "90"))
_MAX_ENTITIES = int(os.environ.get("ROD_NAME_INDEX_MAX_ENTITIES", "60"))

_last_call: dict[str, float] = {}


def _throttle(host: str) -> None:
    prev = _last_call.get(host)
    if prev is not None:
        wait = _MIN_INTERVAL_S - (time.monotonic() - prev)
        if wait > 0:
            time.sleep(wait)
    _last_call[host] = time.monotonic()


def _session(host: str):
    """Clear the disclaimer and return a session holding the PHPSESSID."""
    from curl_cffi import requests as creq
    s = creq.Session(impersonate="chrome")
    _throttle(host)
    r = s.get(f"{host}/NameSearch.php?Accept=Accept", timeout=_TIMEOUT_S)
    if r.status_code != 200 or len(r.text) < 20000:
        # The disclaimer itself is ~4.7 KB; a real search UI is 110 KB+. A small
        # 200 means we are still looking at the gate.
        raise RuntimeError(f"search UI not reached for {host} "
                           f"({r.status_code}, {len(r.text)}b)")
    return s


def _pick(s, host: str, **params) -> list[str]:
    """POST the search, return the entity IDs of the party picker."""
    data = {"search_type": "Standard", "sort_type": "Date", "entity_type": "Both",
            "instType[ALL]": "ALL", "tor_last_name": "", "tee_last_name": "",
            **params}
    _throttle(host)
    r = s.post(f"{host}/NamePick.php", data=data,
               headers={"Referer": f"{host}/NameSearch.php?Accept=Accept"},
               timeout=_TIMEOUT_S)
    if r.status_code != 200:
        return []
    return re.findall(r"name = 'entityID\[([^\]]+)\]'", r.text)


def _display(s, host: str, entity_ids: list[str]) -> list[dict]:
    """POST the picker's own fields back to get document rows.

    Only igheader, igquerystring, displaybutton and the entityID boxes — echoing
    the original search parameters here returns a 21-byte rejection.
    """
    if not entity_ids:
        return []
    data: list[tuple[str, str]] = [
        ("igheader", "ALL"), ("igquerystring", ""),
        ("displaybutton", "Display Detail Listing"),
    ]
    data += [(f"entityID[{e}]", e) for e in entity_ids]
    _throttle(host)
    r = s.post(f"{host}/NameDisplay.php", data=data,
               headers={"Referer": f"{host}/NamePick.php"}, timeout=_TIMEOUT_S)
    if r.status_code != 200 or len(r.text) < 1000:
        return []
    return _rows(r.text)


def _rows(html: str) -> list[dict]:
    """Parse document rows. The header repeats between date groups, so rows are
    identified by a leading MM/DD/YYYY rather than by position."""
    out: list[dict] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c))
            .replace("&nbsp;", " ").replace("\xa0", " ").strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        ]
        if len(cells) < 6 or not re.match(r"\d{2}/\d{2}/\d{4}$", cells[0] or ""):
            continue
        doc_type = cells[2]
        out.append({
            "recorded": cells[0],
            "book_page": cells[1],
            "doc_type": doc_type,
            "description": cells[3],
            "amount": cells[4] or None,
            "reverse_party": cells[5],
            "is_distress": bool(DISTRESS_TYPE_RE.search(doc_type)
                                or DISTRESS_TYPE_RE.search(cells[3])),
        })
    return out


def lookup_name(county: str, state: str, name: str) -> list[dict]:
    """Recorded instruments for one party. [] on any failure — never raises."""
    key = (county.strip().lower(), state.strip().upper())
    host = NAME_INDEX_HOSTS.get(key)
    if not host or not name.strip():
        return []
    try:
        s = _session(host)
        ids = _pick(s, host, tor_last_name=name.strip())
        if not ids:
            return []
        if len(ids) >= SEARCH_LIMIT:
            # Truncated at the cap: the rows we would return are the head of the
            # index, not this party's records. Saying nothing beats saying wrong.
            log.warning("rod_name_index.capped", county=county, name=name[:40],
                        entities=len(ids))
            return []
        return _display(s, host, ids[:_MAX_ENTITIES])
    except Exception as exc:  # noqa: BLE001 - a lookup must never kill a run
        log.warning("rod_name_index.failed", county=county, name=name[:40],
                    error=f"{type(exc).__name__}: {str(exc)[:90]}")
        return []


def bulk_by_date(county: str, state: str, start: str, end: str) -> list[dict]:
    """Every instrument recorded in a window, no name needed.

    Refuses to run where DATE_FILTER is not True, because those counties return
    the head of the whole index for any window and the result would be
    indistinguishable from a week of real filings.

    start/end are MM/DD/YYYY.
    """
    key = (county.strip().lower(), state.strip().upper())
    host = NAME_INDEX_HOSTS.get(key)
    if not host:
        return []
    if DATE_FILTER.get(key) is not True:
        log.info("rod_name_index.bulk_refused", county=county,
                 date_filter=DATE_FILTER.get(key),
                 reason="county ignores the date window; see module docstring")
        return []
    try:
        s = _session(host)
        ids = _pick(s, host, start_date=start, end_date=end)
        if len(ids) >= SEARCH_LIMIT:
            log.warning("rod_name_index.window_capped", county=county,
                        start=start, end=end, entities=len(ids),
                        reason="narrow the window and retry")
            return []
        # Batch through ALL parties. Reading only the first _MAX_ENTITIES would
        # return a partial window that looks exactly like a complete one.
        rows: list[dict] = []
        for i in range(0, len(ids), _MAX_ENTITIES):
            rows += _display(s, host, ids[i:i + _MAX_ENTITIES])
        log.info("rod_name_index.bulk", county=county, start=start, end=end,
                 parties=len(ids), batches=-(-len(ids) // _MAX_ENTITIES),
                 rows=len(rows),
                 distress=sum(1 for r in rows if r["is_distress"]))
        return rows
    except Exception as exc:  # noqa: BLE001
        log.warning("rod_name_index.bulk_failed", county=county,
                    error=f"{type(exc).__name__}: {str(exc)[:90]}")
        return []


def enrich_rod_name_index(listings: Iterable[Listing]) -> dict:
    """Attach raw['rod_name_index'] to leads in the eight covered counties."""
    stats = {"eligible": 0, "looked_up": 0, "with_records": 0, "distress": 0}
    cache: dict[tuple[str, str, str], list[dict]] = {}

    for li in listings:
        county = (getattr(li, "county", "") or "").strip().lower()
        state = (getattr(li, "state", "") or "").strip().upper()
        if (county, state) not in NAME_INDEX_HOSTS:
            continue
        owner = (getattr(li, "owner_name", "") or "").strip()
        if not owner:
            continue
        stats["eligible"] += 1

        key = (county, state, owner.upper())
        if key not in cache:
            cache[key] = lookup_name(county, state, owner)
            stats["looked_up"] += 1
        recs = cache[key]
        if not recs:
            continue

        stats["with_records"] += 1
        distress = [r for r in recs if r["is_distress"]]
        if distress:
            stats["distress"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["rod_name_index"] = {
            "county": county, "state": state, "matched_name": owner,
            "records": recs[:40],
            "distress_instruments": [r["doc_type"] for r in distress][:10],
        }

    log.info("rod_name_index.done", **stats)
    return stats
