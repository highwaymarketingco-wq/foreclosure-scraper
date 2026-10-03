"""NC Voter Search point-lookup — a reusable liveness/occupancy check, and a
future building-block for heir-tracing.

NCSBE's public voter-lookup site (vt.ncsbe.gov/RegLkup) is a plain ASP.NET Core
MVC form with NO CAPTCHA (confirmed by extensive live browser use). It is
distinct from `enrichment_voter_phone.py` / `enrichment_sc_voter_xref.py`,
which match against the static BULK voter-file CSV download (data/ncvoter/) --
this module instead does a live, single-name, point-in-time lookup against the
SAME site a person would use by hand, which is useful when the bulk file is
stale, not yet downloaded for a county, or when only a single name needs
checking instead of a full-file join.

ENDPOINT FLOW (discovered via live browser network inspection, 2026-10-02):

  1. GET  https://vt.ncsbe.gov/RegLkup/
         -> sets session cookies (LoupeSessionId, .AspNetCore.Antiforgery.*)
            and embeds a hidden `__RequestVerificationToken` (ASP.NET Core
            antiforgery) in the search form's HTML.
  2. POST https://vt.ncsbe.gov/RegLkup
         -> form body: VoterSearchFilter.FirstName/LastName/MiddleInitial/
            BirthYear/SelectedCountyId, VoterSearchFilter.IsRegistered,
            VoterSearchFilter.IsRemovedOrDenied, __RequestVerificationToken.
            Sets server-side SESSION search-criteria state; 302s to
            /RegLkup/SearchResults.
  3. GET  https://vt.ncsbe.gov/RegLkup/SearchResults?handler=LoadResults&sort=&group=&filter=
         -> JSON {"Data":[{VoterRegNum,CountyId,CountyName,FullName,NCID,
            ResAddressCSZ,StatusDesc,StatusLbl}], "Total": N}. This is the
            Kendo grid's AJAX "read" action -- it ignores query params and
            reads criteria from the session set in step 2.
  4. GET  https://vt.ncsbe.gov/RegLkup/SearchResults?handler=RedirectToVoterInfo
              &voterRegNum=...&countyId=...
         -> 302s to /RegLkup/VoterInfo, which renders full voter detail
            including "YOUR VOTER HISTORY": the per-election vote-method
            history is embedded inline as JSON inside the page's
            `kendoGrid({... "data":{"Data":[...]} ...})` init script for
            `#gridVoterHistory`, ordered most-recent-first.

IMPORTANT -- SESSION IS STICKY AND MUST BE ISOLATED PER LOOKUP. Live-tested
2026-10-02: reusing one httpx.AsyncClient (one cookie jar) for a SECOND search
-- even with a fresh antiforgery token -- returns the FIRST search's cached
results again (the server's session-keyed search state does not get
overwritten by a later POST in ways a plain httpx re-POST can trigger). A
brand-new AsyncClient (fresh cookie jar => fresh server session) per lookup
reliably returns the correct, distinct result every time. `nc_voter_lookup()`
therefore opens and tears down its own client per call; callers doing a batch
should run calls concurrently under a modest semaphore (see
`validate_elderly_disabled_buncombe.py`), not sequentially share one client.

No TLS-fingerprint blocking observed on this host in any prior manual check,
so plain httpx + a real browser UA is sufficient -- no curl-cffi impersonation
needed here (unlike tax.buncombenc.gov and other WAF-fronted hosts elsewhere
in this project).
"""
from __future__ import annotations

import re
from typing import Any

import httpx

SEARCH_URL = "https://vt.ncsbe.gov/RegLkup"
FORM_PAGE_URL = "https://vt.ncsbe.gov/RegLkup/"
RESULTS_URL = "https://vt.ncsbe.gov/RegLkup/SearchResults"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')

# Full NC county -> SelectedCountyId map, read live off the <select id="County">
# options on vt.ncsbe.gov/RegLkup/ (2026-10-02). "ALL" -> 0 is the no-filter case.
NC_COUNTY_IDS: dict[str, str] = {
    "ALL": "0", "ALAMANCE": "1", "ALEXANDER": "2", "ALLEGHANY": "3", "ANSON": "4",
    "ASHE": "5", "AVERY": "6", "BEAUFORT": "7", "BERTIE": "8", "BLADEN": "9",
    "BRUNSWICK": "10", "BUNCOMBE": "11", "BURKE": "12", "CABARRUS": "13",
    "CALDWELL": "14", "CAMDEN": "15", "CARTERET": "16", "CASWELL": "17",
    "CATAWBA": "18", "CHATHAM": "19", "CHEROKEE": "20", "CHOWAN": "21",
    "CLAY": "22", "CLEVELAND": "23", "COLUMBUS": "24", "CRAVEN": "25",
    "CUMBERLAND": "26", "CURRITUCK": "27", "DARE": "28", "DAVIDSON": "29",
    "DAVIE": "30", "DUPLIN": "31", "DURHAM": "32", "EDGECOMBE": "33",
    "FORSYTH": "34", "FRANKLIN": "35", "GASTON": "36", "GATES": "37",
    "GRAHAM": "38", "GRANVILLE": "39", "GREENE": "40", "GUILFORD": "41",
    "HALIFAX": "42", "HARNETT": "43", "HAYWOOD": "44", "HENDERSON": "45",
    "HERTFORD": "46", "HOKE": "47", "HYDE": "48", "IREDELL": "49",
    "JACKSON": "50", "JOHNSTON": "51", "JONES": "52", "LEE": "53",
    "LENOIR": "54", "LINCOLN": "55", "MACON": "56", "MADISON": "57",
    "MARTIN": "58", "MCDOWELL": "59", "MECKLENBURG": "60", "MITCHELL": "61",
    "MONTGOMERY": "62", "MOORE": "63", "NASH": "64", "NEW HANOVER": "65",
    "NORTHAMPTON": "66", "ONSLOW": "67", "ORANGE": "68", "PAMLICO": "69",
    "PASQUOTANK": "70", "PENDER": "71", "PERQUIMANS": "72", "PERSON": "73",
    "PITT": "74", "POLK": "75", "RANDOLPH": "76", "RICHMOND": "77",
    "ROBESON": "78", "ROCKINGHAM": "79", "ROWAN": "80", "RUTHERFORD": "81",
    "SAMPSON": "82", "SCOTLAND": "83", "STANLY": "84", "STOKES": "85",
    "SURRY": "86", "SWAIN": "87", "TRANSYLVANIA": "88", "TYRRELL": "89",
    "UNION": "90", "VANCE": "91", "WAKE": "92", "WARREN": "93",
    "WASHINGTON": "94", "WATAUGA": "95", "WAYNE": "96", "WILKES": "97",
    "WILSON": "98", "YADKIN": "99", "YANCEY": "100",
}

# The VoterInfo page embeds voter history as a JSON literal inside the
# #gridVoterHistory kendoGrid() init call. Scoping the search to start at that
# grid's init (not #gridBallots, which has similar-shaped fields earlier in
# the page) and taking the FIRST {"Election":...} object gets the most recent
# entry, since NCSBE renders the list most-recent-first.
_VOTER_HISTORY_BLOCK_RE = re.compile(
    # literal is jQuery("#gridVoterHistory").kendoGrid({... -- note the jQuery
    # ID-selector '#' inside the quotes, easy to miss and silently never match.
    r'gridVoterHistory"\)\.kendoGrid\(.*?"data":\{"Data":\[(.*?)\],"Total"',
    re.S,
)
_VOTE_ROW_RE = re.compile(
    r'\{"Election":"([^"]*)","ElectionSort":"[^"]*","VotedCountyName":"([^"]*)",'
    r'"VotingMethod":"([^"]*)","VotedPartyLbl":"([^"]*)"'
)


def _most_recent_vote(html: str) -> dict[str, str] | None:
    block = _VOTER_HISTORY_BLOCK_RE.search(html)
    if not block:
        return None
    row = _VOTE_ROW_RE.search(block.group(1))
    if not row:
        return None
    election, county, method, party = row.groups()
    return {
        "election": election,
        "voted_county": county,
        "voted_method": method,
        "voted_party": party or None,
    }


async def nc_voter_lookup(
    first_name: str,
    last_name: str,
    county: str = "ALL",
    *,
    match_city: str | None = None,
    include_history: bool = True,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Live point-lookup against vt.ncsbe.gov/RegLkup for one (first, last[, county]).

    Returns a dict (never raises for a normal not-found/ambiguous result --
    only a network/parse failure sets ok=False):

      ok: bool                     -- the HTTP round-trip + parse succeeded
      error: str | None
      total_matches: int           -- NCSBE's raw match count (0 if not found)
      status: "active" | "not_active" | "not_found" | "ambiguous"
      match: {full_name, status_desc, county_name, voter_reg_num, ncid,
              res_address_csz} | None   -- the single resolved match, if any
      disambiguated_by_city: bool  -- True if `match` was picked out of several
                                       candidates by `match_city`
      candidates: [...]            -- up to 10 raw rows, only when ambiguous
      most_recent_vote: {election, voted_county, voted_method, voted_party}
                         | None    -- only fetched when `include_history` and a
                                      single confident match was found

    `county` accepts a county name (case-insensitive) or "ALL". `match_city`
    is an optional city name (as it would appear in ResAddressCSZ, e.g.
    "Black Mountain") used to pick a single winner out of multiple same-name
    matches -- pass the property's city for the elderly/heir-tracing use case.
    """
    county_id = NC_COUNTY_IDS.get((county or "ALL").strip().upper(), "0")
    out: dict[str, Any] = {
        "first_name": first_name, "last_name": last_name, "county": county,
        "ok": False, "error": None, "total_matches": 0, "status": "not_found",
        "match": None, "disambiguated_by_city": False, "candidates": [],
        "most_recent_vote": None,
    }
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA}, follow_redirects=True, timeout=timeout,
        ) as c:
            r1 = await c.get(FORM_PAGE_URL)
            r1.raise_for_status()
            m = _TOKEN_RE.search(r1.text)
            if not m:
                out["error"] = "antiforgery token not found on form page"
                return out
            token = m.group(1)

            body = {
                "VoterSearchEntryId": "",
                "VoterSearchFilter.FirstName": first_name,
                "VoterSearchFilter.MiddleInitial": "",
                "VoterSearchFilter.LastName": last_name,
                "VoterSearchFilter.BirthYear": "",
                "VoterSearchFilter.SelectedCountyId": county_id,
                "VoterSearchFilter.IsRegistered": "true",
                "VoterSearchFilter.IsRemovedOrDenied": "false",
                "__RequestVerificationToken": token,
            }
            r2 = await c.post(SEARCH_URL, data=body)
            r2.raise_for_status()

            r3 = await c.get(
                RESULTS_URL,
                params={"handler": "LoadResults", "sort": "", "group": "", "filter": ""},
            )
            r3.raise_for_status()
            data = r3.json()
            rows = data.get("Data") or []
            total = data.get("Total") or 0
            out["ok"] = True
            out["total_matches"] = total

            if not rows:
                out["status"] = "not_found"
                return out

            chosen = None
            if len(rows) == 1:
                chosen = rows[0]
            elif match_city:
                city_u = match_city.strip().upper()
                hits = [row for row in rows if city_u in (row.get("ResAddressCSZ") or "").upper()]
                if len(hits) == 1:
                    chosen = hits[0]
                    out["disambiguated_by_city"] = True

            if chosen is None:
                out["status"] = "ambiguous"
                out["candidates"] = rows[:10]
                return out

            out["match"] = {
                "full_name": chosen.get("FullName"),
                "status_desc": chosen.get("StatusDesc"),
                "county_name": chosen.get("CountyName"),
                "voter_reg_num": chosen.get("VoterRegNum"),
                "ncid": chosen.get("NCID"),
                "res_address_csz": chosen.get("ResAddressCSZ"),
            }
            out["status"] = "active" if (chosen.get("StatusDesc") or "").upper() == "ACTIVE" else "not_active"

            if include_history and chosen.get("VoterRegNum"):
                r4 = await c.get(
                    RESULTS_URL,
                    params={
                        "handler": "RedirectToVoterInfo",
                        "voterRegNum": chosen["VoterRegNum"],
                        "countyId": chosen.get("CountyId"),
                    },
                )
                if r4.status_code == 200:
                    out["most_recent_vote"] = _most_recent_vote(r4.text)

            return out
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:300]
        return out


def split_owner_name(owner_name: str) -> tuple[str, str] | None:
    """Best-effort (first, last) split of this project's GIS-convention owner
    strings: "LASTNAME FIRSTNAME [MIDDLE/SUFFIX ...]", first owner only when
    multiple owners are ';'-joined (see project_owner_name_conventions_and_divorce.md).
    Returns None if the string doesn't look like at least two name tokens.
    """
    if not owner_name:
        return None
    first_owner = owner_name.split(";")[0].strip()
    parts = first_owner.split()
    if len(parts) < 2:
        return None
    last, first = parts[0], parts[1]
    if not last.isalpha() or not first.isalpha():
        return None
    return first.title(), last.title()
