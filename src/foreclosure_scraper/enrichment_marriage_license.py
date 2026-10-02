"""Marriage license signal enricher — NC Register of Deeds cross-reference.

A distressed homeowner who recently filed for a marriage license is a life-event
signal: possible name change, joint ownership, or spousal motivation. This
enricher cross-references owner names against marriage license records from NC
county Register of Deeds offices (public records, free).

LIVE-VERIFIED 2026-10-02 (triage confirmed marriage_license at 0/148 counties;
this rewrite replaces the previous implementation, which only ever probed 5
hand-written URLs with a plain GET -- 2 of the 5 were dead DNS, 1 redirected to
a plain department homepage, 2 were bare 404s, so it always returned None and
that 0 was indistinguishable in logs from "genuinely no matches this run", the
project's own documented silent-success failure mode):

NC counties do NOT share one marriage-license access pattern -- verified
per-county, not assumed:

* Buncombe -- REUSED, confirmed LIVE. Its Cott/Aumentum eSearch v4 LandRecords
  index (`rod/aumentum.py`, the SAME vendor adapter `enrichment_aumentum_rod.py`
  already uses for deed/mortgage/lien lookups, re-verified by a concurrent
  session earlier today) quietly carries marriage records as a plain instrument
  type ("MARRIED") right alongside deeds and liens in the same name-search grid.
  Confirmed live by running `aumentum.search_by_name("NC", "Buncombe", "SMITH")`
  and finding real rows like
  `grantor=SMITH, MOLLY KATHRYN / grantee=ELIE-YORK, SEBASTIAN / doc_type=MARRIED`
  -- real spouse names, book/page present, only the recorded_date is masked
  ("**/**/YYYY", the same privacy treatment the vendor applies to death records).
  So: no new probe needed here -- just reuse the adapter and filter doc_type.

* Mecklenburg -- same vendor, same `AUMENTUM_COUNTIES` mapping
  (`meckrod.manatron.com`), so the identical reuse covers it the moment its
  backend is healthy. Right now it is NOT: every request (GET *and* POST, live-
  reproduced with a plain `curl` independent of this project's code, repeated
  minutes apart) returns a fatal ASP.NET error body --
  "System.Web.HttpException: Session state is not available in this context" --
  a county-side outage/misconfiguration, not a wall and not fixable from here.
  No code change is needed for this to start working again: it is in
  `aumentum.AUMENTUM_COUNTIES` today, so the next run after the county's server
  recovers will pick it up automatically.

* Wake, Durham, Forsyth -- confirmed WALLS, not dead URLs this module can fix
  (the old hardcoded URLs for all three were already dead/wrong, so removing
  them here is not a regression):
    - Wake (`rodrecords.wake.gov/web`): the entry disclaimer is reCAPTCHA-gated
      (`checkHuman` / `grecaptcha.getResponse()` in the page JS). CAPTCHA wall.
    - Durham (`rodweb.dconc.gov/web`): the SAME reCAPTCHA-gated disclaimer
      product, and its own page text says vital records (birth/death/MARRIAGE)
      specifically require "creating an online profile" -- i.e. a login --
      separate from the open real-estate index. CAPTCHA + login wall.
    - Forsyth (`forsythdeeds.com`): the real-estate name index itself is open
      (a bare "Accept" disclaimer with no login/CAPTCHA -- the same non-wall
      shape as Haywood/Yancey/Transylvania, which `rod/logan.py` already
      passes through with `Accept=Accept`), but its "Vital Records" button
      routes to `vital/login.php`, a real username+password login form with
      account registration ("Not a user? Click here to register"). Login wall,
      specific to marriage/vital records only.
  Per CLAUDE.md's compliance line a CAPTCHA and a login are both walls, so this
  module does not probe these three -- there's nothing a code fix can do here;
  it's a genuine, confirmed gap, not a bug.

Rate-limited: max MARRIAGE_LICENSE_MAX_REQUESTS (default 50) vendor searches per
run. Idempotent: a listing that has ever been checked (match OR confirmed no
match) is skipped on later runs -- the previous version only ever wrote
raw['marriage_license'] on a match, so an unmatched owner was silently
re-queried every single run forever.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import List

import structlog

from .models import Listing
from .name_normalize import first_last_parts
from .rod import aumentum
from .rod.models import RodDoc

log = structlog.get_logger()

MAX_REQUESTS = int(os.getenv("MARRIAGE_LICENSE_MAX_REQUESTS", "50"))

# A marriage record's doc_type on the vendor grid, live-verified on Buncombe as
# the bare word "MARRIED" -- matched loosely (substring, case-insensitive) in
# case a sibling Aumentum tenant renders it slightly differently (e.g. Gaston's
# terse-code convention for other doc types, per rod/aumentum.py's docstring).
_MARRIAGE_DOC_TYPE_RE = re.compile(r"MARRI", re.I)


def _name_parts(owner: str) -> tuple[str, str] | None:
    """(LAST, FIRST) from an owner_name string in either board convention.

    NOTE: the no-comma, all-caps branch below is SURNAME-FIRST ('SMITH JOHN' ->
    ('SMITH', 'JOHN')), matching `enrichment_aumentum_rod.py`'s own `_name_parts`
    (the project's proven convention for this exact ALL-CAPS GIS shape -- see
    `project_owner_name_conventions_and_divorce`). The *previous* version of
    this module had it backwards (`(parts[-1], parts[0])`, i.e. GIVEN-first),
    which would have silently misidentified or missed every all-caps-owner
    match even if the network path had worked -- fixed here, not just the
    network path.
    """
    if not owner:
        return None
    fl = first_last_parts(owner)
    if fl is not None:
        return fl
    o = re.sub(r"[^A-Za-z, ]", " ", owner).upper()
    o = re.sub(r"\s+", " ", o).strip()
    if not o:
        return None
    if "," in o:
        last, _, rest = o.partition(",")
        last = last.strip()
        first = rest.strip().split()[0] if rest.strip() else ""
        return (last, first) if last else None
    parts = o.split()
    if not parts:
        return None
    return (parts[0], parts[1] if len(parts) > 1 else "")


def _is_marriage_doc(doc_type: str | None) -> bool:
    return bool(doc_type) and bool(_MARRIAGE_DOC_TYPE_RE.search(doc_type))


def _spouse_from_doc(doc: RodDoc, last: str, first: str) -> dict | None:
    """A marriage-index row's grantor/grantee ARE the two spouses. Return
    whichever side is NOT the searched owner, confidence-rated on how much of
    the owner's name matched their side of the row."""
    grantor = (doc.grantor or "").upper()
    grantee = (doc.grantee or "").upper()
    if last and last in grantor:
        owner_side, other_side = grantor, doc.grantee
    elif last and last in grantee:
        owner_side, other_side = grantee, doc.grantor
    else:
        return None
    confidence = "high" if (first and first in owner_side) else "medium"
    return {
        "spouse_name": (other_side or "").strip().title(),
        "license_date": doc.recorded_date.date().isoformat() if doc.recorded_date else None,
        "county_issued": doc.county,
        "book": doc.book,
        "page": doc.page,
        "match_confidence": confidence,
        "searched_name": f"{last}, {first}",
        "source": "aumentum_rod",
    }


def _best_marriage_match(docs: list[RodDoc], last: str, first: str) -> dict | None:
    best: dict | None = None
    for d in docs:
        if not _is_marriage_doc(d.doc_type):
            continue
        hit = _spouse_from_doc(d, last, first)
        if not hit:
            continue
        if hit["match_confidence"] == "high":
            return hit
        if best is None:
            best = hit
    return best


async def _search_county(state: str, county: str, owner: str) -> tuple[dict | None, bool]:
    """Vendor-backed marriage-license lookup for a county the Aumentum ROD
    adapter already indexes.

    Returns (match, confident). `confident` is True only when the vendor
    actually returned rows for this name -- i.e. the search itself worked --
    so the caller can tell a real "searched, no marriage record" from "the
    fetch came back empty" (an exception, a down backend like Mecklenburg's
    right now, or curl_cffi being unavailable all surface as `[]` from
    `aumentum.search_by_name` -- it swallows its own errors, see its
    docstring/callers). `enrichment_aumentum_rod.py` hits this identical
    ambiguity and resolves it the same way: "if not docs: continue # fetch
    failed -> leave unstamped, retry next run". Locking in a false no-match
    here would make Mecklenburg permanently look checked-and-empty even after
    its server recovers.
    """
    parsed = _name_parts(owner)
    if not parsed:
        return None, False
    last, first = parsed
    if not last:
        return None, False
    try:
        docs = await aumentum.search_by_name(state, county, owner, max_docs=400)
    except Exception as exc:  # noqa: BLE001
        log.debug("marriage.fetch_error", county=county, error=str(exc)[:160])
        return None, False
    if not docs:
        return None, False
    return _best_marriage_match(docs, last, first), True


def _vendor_covered_counties(state: str) -> set[str]:
    """Counties the Aumentum ROD adapter covers for `state`, from its own
    registry -- new tenants it adds later (the adapter already parameterizes
    everything by `base` for exactly this reason) are picked up automatically,
    no change needed here."""
    return {c for (s, c) in aumentum.AUMENTUM_COUNTIES if s == state}


async def enrich_marriage_licenses(listings: List[Listing]) -> dict:
    """Cross-reference owner names against the ROD marriage-record index for
    counties whose vendor ROD platform is confirmed to carry them. See the
    module docstring for the per-county live-verification (which counties are
    reused via the adapter vs. confirmed walls this cannot fix)."""
    stats = {
        "total": len(listings),
        "with_owner": 0,
        "not_covered": 0,
        "queried": 0,
        "matches": 0,
        "confirmed_no_match": 0,
        "fetch_failed": 0,
        "skipped_existing": 0,
    }
    requests_made = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    covered_by_state: dict[str, set[str]] = {}

    for li in listings:
        if not isinstance(li.raw, dict):
            li.raw = {}
        raw = li.raw

        # Idempotent: a prior match OR a prior confirmed no-match both skip.
        if raw.get("marriage_license"):
            stats["skipped_existing"] += 1
            continue

        state = (li.state or "").upper()
        if not state:
            continue
        if state not in covered_by_state:
            covered_by_state[state] = _vendor_covered_counties(state)
        county = (li.county or "").replace(" County", "").strip()
        if county not in covered_by_state[state]:
            stats["not_covered"] += 1
            continue

        owner = li.owner_name or li.defendant or ""
        if not owner:
            continue
        stats["with_owner"] += 1

        if requests_made >= MAX_REQUESTS:
            log.info("marriage.rate_limit_reached", max=MAX_REQUESTS)
            break

        match, confident = await _search_county(state, county, owner)
        requests_made += 1
        stats["queried"] += 1

        if match:
            raw["marriage_license"] = match
            stats["matches"] += 1
        elif confident:
            # Confirmed no-match (the vendor returned real rows for this name,
            # just none tagged as a marriage record): a terminal state, so
            # later runs don't re-burn the request budget on the same owner
            # forever -- the gap the previous version left open (it only ever
            # wrote raw['marriage_license'] on a match).
            raw["marriage_license"] = {"status": "no_match", "checked_at": now_iso}
            stats["confirmed_no_match"] += 1
        else:
            # Empty/failed fetch (exception, or a down backend like
            # Mecklenburg's right now) -- leave unstamped so the NEXT run
            # retries once the county's server recovers, instead of locking
            # in a false no-match. Same resolution enrichment_aumentum_rod.py
            # uses for this identical ambiguity.
            stats["fetch_failed"] += 1

        await asyncio.sleep(0.2)

    log.info("marriage.done", **stats)
    return stats
