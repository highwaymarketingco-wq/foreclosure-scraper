"""Richland County SC Estate Inquiry -- a county-run probate case search, separate from and
NOT redundant with southcarolinaprobate.net (Richland is confirmed NOT in that aggregator's own
county dropdown -- sc_probate_net.py's own COUNTIES tuple never named it).

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-28.csv). SC Richland "probate" (1,546
applicable) showed sourced-not-built, source "probate: www7.richlandcountysc.gov" -- a real,
different, free county system from the statewide aggregator this project already reads.

THE SITE: https://www7.richlandcountysc.gov/EstateInquiry/main.aspx, a plain ASP.NET WebForms
page (no master-page control-name prefix, unlike southcarolinaprobate.net's
``ctl00$ContentPlaceHolder1$`` convention). No login, no CAPTCHA, no disclaimer click-through.

THE REAL GOTCHA, live-verified 2026-10-28 via the built-in browser (not curl guessing): BOTH
``txtLastName`` AND ``txtFirstName`` are REQUIRED fields (first name needs >= 2 characters) --
submitting last name alone always gets the generic "Please enter the decedent's name" message,
which looks identical to a validation failure and is easy to mistake for "the search doesn't
work at all." Once both are filled it answers for real: Last="SIMS" First="ISOM" returned two
genuine cases ("1985-ES40-00304 Sims, Isom" and "1991-ES40-00827 Sims, Isom Jr"). First name
also appears to be a PREFIX match (ISOM matched both "Isom" and "Isom Jr"), so this module sweeps
a short list of common first-INITIAL-pair prefixes per surname rather than needing exact first
names -- the same "a handful of common names covers a large slice of the index" trade
sc_probate_net.py's own SURNAMES sweep makes, just two-dimensional here since there is no
bulk/list-all endpoint on this site either.

NO SESSION COOKIE AT ALL (confirmed: a GET sets none) -- this is a load-balanced server with no
sticky-session affinity, so the VIEWSTATE from one GET occasionally fails MAC validation on the
immediately-following POST if it lands on a different backend (live-reproduced, cleared on
retry 3/3 times). ``_search`` below retries once on that specific failure before giving up on a
name pair, rather than treating it as "this name has no cases."

Each result row carries Case Number, Decedent's Name (Last/First/Middle/Suffix spans), Date of
Death, Date Opened, Date Closed -- emitted as address-less ``ListingType.PROBATE_NOTICE`` leads,
same shape sc_probate_net.py already uses (a decedent + an open estate is a classic
motivated-seller signal, backfilled to a property by the downstream owner->GIS enricher). The
"View Parties" sub-grid (the estate's Personal Representative / attorney) needs its own
postback per case and is NOT read here -- a real, documented gap, not attempted on a first pass.

Only open or recently-closed estates are useful leads; a case closed decades ago is not an active
motivated-seller signal. ``MAX_CLOSED_AGE_DAYS`` filters those out the same way sc_probate_net.py
filters stale closed/old records.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Iterable, Optional

import httpx
import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...config import RuntimeConfig
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE_URL = "https://www7.richlandcountysc.gov/EstateInquiry/main.aspx"
COUNTY = "Richland"
STATE = "SC"

#: Common SC surnames, same list sc_probate_net.py already uses for its own 1-D sweep.
SURNAMES: tuple[str, ...] = (
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Davis", "Wilson", "Moore", "Taylor", "White",
)
#: First-name prefixes (>= 2 chars, the site's own minimum) covering the most common SC given
#: names across both sexes and generations -- this site's first-name field is required and
#: appears to be a prefix match, so these few cover a real slice without an exhaustive A-Z sweep.
FIRST_PREFIXES: tuple[str, ...] = ("Ja", "Jo", "Ma", "Mi", "Ro", "Wi", "Ba", "Be", "Ch", "Da")

MAX_CLOSED_AGE_DAYS = 730  # same order of magnitude as sc_probate_net.py's MAX_AGE_DAYS
_REQUEST_PAUSE_S = 1.0

_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")


def _hidden_fields(html: str) -> dict[str, str]:
    tree = HTMLParser(html)
    out: dict[str, str] = {}
    for inp in tree.css("input[type=hidden]"):
        name = inp.attributes.get("name")
        if name:
            out[name] = inp.attributes.get("value") or ""
    return out


def _parse_results(html: str) -> list[dict]:
    """Pure: one dict per row of the ``gvEstates`` grid, or [] on "no records"/a re-rendered
    search form. Never raises on unexpected markup."""
    tree = HTMLParser(html)
    grid = tree.css_first("#gvEstates")
    if grid is None:
        return []
    out: list[dict] = []
    for tr in grid.css("tr"):
        cells = tr.css("td")
        if len(cells) < 6:
            continue
        case_no_text = cells[1].text(strip=True)
        if not case_no_text or "-ES" not in case_no_text.upper():
            continue
        last = cells[2].css_first("span[id*=lblDecedentLastName]")
        first = cells[2].css_first("span[id*=lblDecedentFirstName]")
        middle = cells[2].css_first("span[id*=lblDecedentMiddleName]")
        suffix = cells[2].css_first("span[id*=lblNameSuffix]")
        last_n = (last.text(strip=True) if last else "").strip()
        first_n = (first.text(strip=True) if first else "").strip()
        middle_n = (middle.text(strip=True) if middle else "").strip()
        suffix_n = (suffix.text(strip=True) if suffix else "").strip()
        decedent = " ".join(x for x in (first_n, middle_n, last_n, suffix_n) if x)
        dates = [c.text(strip=True) for c in cells[3:6]]
        dates = [d if _DATE_RE.fullmatch(d) else None for d in dates]
        out.append({
            "case_number": case_no_text,
            "decedent": decedent or None,
            "decedent_last": last_n or None,
            "decedent_first": first_n or None,
            "date_of_death": dates[0],
            "date_opened": dates[1],
            "date_closed": dates[2],
        })
    return out


def _parse_us_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%m/%d/%Y")
    except ValueError:
        return None


def _is_current(row: dict, now: datetime) -> bool:
    closed = _parse_us_date(row.get("date_closed"))
    if closed is None:
        return True  # an open (or undated-closed) estate is kept
    return (now - closed).days <= MAX_CLOSED_AGE_DAYS


async def _search(client: httpx.AsyncClient, last: str, first: str) -> list[dict]:
    """One (last, first) search, with one retry on the load-balanced-server viewstate-MAC
    failure this site's own lack of a session cookie causes intermittently (module docstring)."""
    for attempt in range(2):
        try:
            r = await client.get(BASE_URL)
            r.raise_for_status()
            fields = _hidden_fields(r.text)
            fields.update({"txtLastName": last, "txtFirstName": first, "btnSubmit": "Search"})
            r2 = await client.post(BASE_URL, data=fields)
            r2.raise_for_status()
        except httpx.HTTPError:
            continue
        if "Validation of viewstate" in r2.text:
            continue
        return _parse_results(r2.text)
    return []


class SCRichlandProbate(BaseScraper):
    """Richland County SC Estate Inquiry -- county-run probate case search."""

    slug = "counties_sc.sc_richland_probate"
    name = "SC Richland Probate (Estate Inquiry)"
    category = "probate"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        cfg = RuntimeConfig.from_env()
        out: list[Listing] = self.partial
        seen: set[str] = set()
        now = datetime.utcnow()

        async with httpx.AsyncClient(
            headers={"User-Agent": cfg.user_agent},
            follow_redirects=True,
            timeout=cfg.request_timeout_s + 15.0,
        ) as client:
            for last in SURNAMES:
                for first in FIRST_PREFIXES:
                    try:
                        rows = await _search(client, last, first)
                    except Exception:  # noqa: BLE001 - one name pair never kills the sweep
                        log.warning("sc_richland_probate.search_failed", last=last, first=first,
                                   traceback=True)
                        continue
                    for row in rows:
                        case_no = row.get("case_number")
                        if not case_no or case_no in seen:
                            continue
                        seen.add(case_no)
                        if not _is_current(row, now):
                            continue
                        decedent = row.get("decedent")
                        desc = f"SC probate estate {case_no} (Richland County)"
                        if decedent:
                            desc += f" — decedent {decedent}"
                        out.append(Listing(
                            source=self.slug,
                            source_url=BASE_URL,
                            listing_type=ListingType.PROBATE_NOTICE,
                            property_kind=PropertyKind.UNKNOWN,
                            state=STATE,
                            county=COUNTY,
                            owner_name=decedent,
                            case_number=case_no,
                            description=desc[:500],
                            first_seen=now,
                            last_seen=now,
                            raw={"sc_richland_probate": {
                                "record_kind": "probate",
                                "decedent": decedent,
                                "date_of_death": row.get("date_of_death"),
                                "date_opened": row.get("date_opened"),
                                "date_closed": row.get("date_closed"),
                            }},
                        ))
                    await asyncio.sleep(_REQUEST_PAUSE_S)
            log.info("sc_richland_probate.done", kept=len(out), seen=len(seen))
        return out
