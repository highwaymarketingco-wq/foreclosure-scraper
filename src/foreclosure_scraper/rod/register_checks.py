"""Register 'checked' verdicts for the Cott eSearch v4 / BIS Online Record System / Tyler / Cott eSearch
(SC) counties (audit 2026-10-09, top-80 build list, group register_other).

THREE THINGS THE EXISTING ADAPTERS DID NOT GIVE THE BOARD
  1. The shape of a looked-at-and-found-nothing verdict (empty_rod_block). enrichment_generic_rod
     stamps it (screened_none_found) when a module reports a status; the Cott v4, Tyler, Polk and
     Marlboro modules now do (search_by_name_status), so an owner with a clean title no longer looks
     like an owner nobody searched. A failed, walled, capped or too-many answer stays unstamped.
  2. The marriage index. The Cott eSearch v4 guest search carries the county's MARRIAGES index in six
     tenants (Onslow, Alamance, Alexander, Pamlico, Edgecombe, Rutherford; the 'Index Type' list says
     MARRIAGES, code MAR). CottV4Marriage runs the same guest name search with that one index
     selected; a hit gives raw['marriage_license'] in the shape enrichment_marriage_license wrote
     (spouse_name, license_date, book/page), a clean answer the dated {'status': 'no_match',
     'checked_at'} wrapper the cube reads as a check. Counties whose register has no marriage index
     (or hides it behind a login) are recorded in MARRIAGE_VERDICTS and never stamped.
  3. Ground truth for the audit check: MARRIAGE_VERDICTS names, per county, why a marriage cell is a
     check, a no-source verdict or a wall, with the live evidence date.

Nothing here retries, solves or goes around a challenge. Rowan (a challenge page on the Cott sign-in
page, re-fetched once on 2026-10-09 and still a challenge page) and Forsyth's vital-records login
(re-fetched once, a login page) stay walls.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from .nc_chain import IndexRecord, OwnerName, SearchResult
from .nc_cott_v4 import PLATFORM as COTT_PLATFORM
from .nc_cott_v4 import CottV4, CottCounty, COUNTIES as COTT_COUNTIES, name_form, parse_grid, too_many
from .nc_cott_v4 import _P as _COTT_P

SOURCE = "register_checks"
MARRIAGE_PLATFORM = COTT_PLATFORM + "_marriage"
MARRIAGE_INDEX_CODE = "MAR"            # the 'Index Type' list's own code for MARRIAGES

# (state, county) -> what a marriage cell means there. verdict:
#   index        the guest search has a MARRIAGES index and the answer carries marriage rows: CHECK
#   no_index     the county register's online search carries no marriage index: no free source online
#   wall         the register's marriage records sit behind a login / challenge: a person does it
#   not_returned the form lists a marriage category but 2026-10-09 name searches returned none
MARRIAGE_VERDICTS: dict[tuple[str, str], dict[str, str]] = {
    ("NC", "Onslow"): {"verdict": "index", "via": "cott_mar",
                       "evidence": "Index Type list has MARRIAGES (MAR); 3 common-name searches returned marriage rows"},
    ("NC", "Alamance"): {"verdict": "index", "via": "cott_mar",
                         "evidence": "Index Type list has MARRIAGES (MAR)"},
    ("NC", "Alexander"): {"verdict": "index", "via": "cott_mar",
                          "evidence": "Index Type list has MARRIAGES (MAR)"},
    ("NC", "Pamlico"): {"verdict": "index", "via": "cott_mar",
                        "evidence": "Index Type list has MARRIAGES (MAR); marriage rows returned"},
    ("NC", "Edgecombe"): {"verdict": "index", "via": "cott_mar",
                          "evidence": "Index Type list has MARRIAGES (MAR); marriage rows returned"},
    ("NC", "Rutherford"): {"verdict": "index", "via": "cott_mar",
                           "evidence": "Index Type list has MARRIAGES (MAR); marriage rows returned"},
    ("NC", "Pitt"): {"verdict": "no_index",
                     "evidence": "guest search Index Type list (2026-10-09) has no marriage, birth or death index"},
    ("NC", "Polk"): {"verdict": "no_index",
                     "evidence": "guest search Index Type list (2026-10-09): CONSOLIDATED REAL PROPERTY, PRE 95 REAL ESTATE only"},
    ("NC", "Graham"): {"verdict": "no_index",
                       "evidence": "guest search Index Type list (2026-10-09) has no marriage index"},
    ("NC", "Nash"): {"verdict": "no_index",
                     "evidence": "guest search Index Type list (2026-10-09) has no marriage index"},
    ("NC", "Rowan"): {"verdict": "wall",
                      "evidence": "the sign-in page answers a script with a challenge page (re-fetched once 2026-10-09)"},
    ("NC", "Forsyth"): {"verdict": "wall",
                        "evidence": "marriage records are under 'Vital Records', a username/password login "
                                    "(vital/login.php, re-fetched once 2026-10-09: login page)"},
    ("NC", "Davidson"): {"verdict": "not_returned",
                         "evidence": "the name search lists a MARRIAGE code under MISCELLANEOUS, but 4 common-name "
                                     "searches (558 instruments) returned no marriage row (2026-10-09)"},
}

_MARRIAGE_RX = re.compile(r"marri", re.I)


def marriage_verdict(state: str, county: str) -> Optional[dict[str, str]]:
    k = ((state or "").upper(), " ".join((county or "").replace(" County", "").split()).title())
    return MARRIAGE_VERDICTS.get(k)


def marriage_stampable(state: str, county: str) -> bool:
    """Only an `index` county may carry a marriage_license no-match: anywhere else a clean answer
    would say nothing about marriages."""
    v = marriage_verdict(state, county)
    return bool(v and v["verdict"] == "index")


def is_marriage_record(rec: Any) -> bool:
    if rec is None:
        return False
    if str(getattr(rec, "index_code", "") or "").strip().upper() == MARRIAGE_INDEX_CODE:
        return True
    for attr in ("doc_type", "index_code", "category", "description"):
        v = getattr(rec, attr, None)
        if v and _MARRIAGE_RX.search(str(v)):
            return True
    return False


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z ]", " ", (s or "").upper())


def _side_has(names: Iterable[str], who: OwnerName) -> bool:
    if who.entity:                              # an entity: its first two words must all appear
        want = [t for t in _norm(who.last).split() if t][:2]
        return bool(want) and any(all(t in _norm(n).split() for t in want) for n in names or ())
    for n in names or ():
        toks = _norm(n).split()
        if who.last and who.last.upper() in toks and (not who.first or any(
                t.startswith(who.first.upper()[:3]) for t in toks)):
            return True
    return False


def marriage_block(records: list[IndexRecord], who: OwnerName, *, county: str, now_iso: str) -> Optional[dict]:
    """The best marriage row naming the owner as one spouse -> the raw['marriage_license'] match
    block (same keys enrichment_marriage_license wrote), or None when no marriage row names them."""
    best: Optional[dict] = None
    for r in records:
        if not is_marriage_record(r):
            continue
        on_a = _side_has(r.grantors, who)
        on_b = _side_has(r.grantees, who)
        if not (on_a or on_b):
            continue
        other = (r.grantees if on_a else r.grantors) or []
        first_given = bool(who.first)
        block = {
            "spouse_name": (other[0] if other else "").strip().title(),
            "license_date": r.recorded,
            "county_issued": county,
            "book": r.book, "page": r.page,
            "match_confidence": "high" if first_given else "medium",
            "searched_name": f"{who.last}, {who.first}".strip(", "),
            "source": SOURCE,
            "checked_at": now_iso,
        }
        if block["match_confidence"] == "high":
            return block
        best = best or block
    return best


def no_match_block(now_iso: str) -> dict:
    return {"status": "no_match", "checked_at": now_iso, "source": SOURCE}


def owner_instruments(records: list[IndexRecord], who: OwnerName) -> list[IndexRecord]:
    """Instruments in which the owner's surname (and first-name stem) sits on either side."""
    return [r for r in records if _side_has(r.grantors, who) or _side_has(r.grantees, who)]


def empty_rod_block(now_iso: str, platform: str) -> dict:
    """raw['rod'] for 'the register answered and holds no instrument for this owner' -- the shape
    enrichment_generic_rod stamps (its `_EMPTY` plus screened_none_found, fetched_at, platform).
    Kept here so the audit check and the tests share one definition."""
    return {"instrument_count": 0, "kinds": {}, "has_mortgage": False, "has_adverse_lien": False,
            "adverse_types": [], "mortgage_count": 0, "satisfaction_count": 0, "open_mortgages_est": 0,
            "instruments": [], "source": "generic_rod", "platform": platform, "screened_none_found": True,
            "fetched_at": now_iso}


# ------------------------------------------------------------------------------------------------
# the marriage-index search: the Cott v4 guest name search with Index Type = MARRIAGES
# ------------------------------------------------------------------------------------------------

class CottV4Marriage(CottV4):
    """Same tenants, same guest click-through, same pacing, one difference: the 'Index Type' list is
    set to MARRIAGES. Its own platform string keeps its per-county lookup budget apart from the
    deed/lien search's."""
    platform = MARRIAGE_PLATFORM
    counties = {k: v for k, v in COTT_COUNTIES.items()
                if marriage_stampable("NC", k)}

    def _search(self, client, cfg: CottCounty, ctx, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        url = cfg.base + "SrchName.aspx"
        form = self._form(client, cfg)
        post_url = form.final_url or url
        data = name_form(form.text, who, side, date_thru)
        data[_COTT_P + "ddlIndexType"] = MARRIAGE_INDEX_CODE
        page = client.post(post_url, data, headers={"Referer": post_url})
        if too_many(page.text):
            return SearchResult(status="too_many", url=url,
                                reason="the register found more marriages than it will list for this name")
        if page.status >= 400:
            return SearchResult(status="error", url=url, reason=f"HTTP {page.status}")
        rows, total = parse_grid(page.text)
        if total is None and not rows:
            return SearchResult(status="error", url=url, reason="the answer was not a results grid")
        for r in rows:                       # the Index Type filter makes every row a marriage; some
            if not r.doc_type:               # tenants leave the Type cell blank
                r.doc_type = "MARRIAGE"
        return SearchResult(records=rows, total=total, url=url,
                            truncated=bool(total is not None and total > len(rows)))


MARRIAGE_ADAPTER = CottV4Marriage()
