"""Incarceration distress signal — match property owners against inmate rosters.

An owner who is in prison/jail is a motivated seller (can't manage the property,
family needs liquidity). This is an ENRICHMENT, not a listing source: it takes
the owner names we resolved via #0 (owner_mailing) / the defendant field and
checks them against the state corrections roster, flagging raw['incarceration'].

NC: NC DAC Offender Public Information — queryable by last+first name
(webapps.doc.state.nc.us/opi/offendersearch.do), parseable HTML results.
SC: SCDC inmate search — the React SPA's backing servlet
(public.doc.state.sc.us/scdc-public/inmateSearch.do, params in the query string,
method=POST) returns a JSON offender array. Wired via _scdc_match (verified live
2026-07-01: 250 records for lastName=SMITH). Same single-exact-match noise gate
as NC. Both are STATE-PRISON rosters; county-jail bookings (pre-trial + local
holds, several exposing full DOB) are a separate net-new lane — see
docs/ or project_gap_analysis for the P2C/Zuercher/Southern-Software endpoints.

HONEST CAVEAT: this is a NAME-ONLY match (we have no owner DOB), so common
names produce false positives. It is therefore emitted as a LOW-confidence
STACK signal (confidence='name_only') — meaningful only when combined with
other distress on the same property, never as a standalone "this owner is in
prison" claim. Capped + paced to be polite to the state server.

NEGATIVE STAMPS (J-01, 2026-09-20): a miss used to leave nothing on the lead, so
every run re-queried the same first 150 non-matching owners and never got past
them (Mitchell, Oconee and Union, which have no county roster, stayed at zero).
A lookup the state actually answered with no match now writes
raw['incarceration_check'] = {checked_at, name, source, result}. Leads
with a fresh stamp are skipped, never-checked leads go first, then the oldest
stamps, and the per-run budget is shared round-robin across counties (footprint
counties before the rest) with a per-county cap. A lookup that FAILED (timeout,
5xx, an unrecognised page) is never stamped: that would repeat the divorce
enricher's 2026-09-18 bug, where an unsearched lead read as "checked, no
match". A host that answers 403/429 or a challenge page is left alone for the
rest of the run. The stamp is deliberately a separate key: raw['incarceration']
is the signal itself (distress_score weight 8) and must stay truthy only for a
real name match.

STALE-MATCH INVALIDATION (2026-10-03, same bug shape as owner_name/bop_federal/
owner_name_signal, found during the sweep that fixed those three): a match,
once stamped, was never revisited even after the owner on record changed —
`if (li.raw or {}).get("incarceration"): continue` treated any existing match
as permanent. Live-checked against the real board: 11 rows carry
raw['incarceration'] naming someone with zero relation to the CURRENT owner,
now a bank/city/HOA/LLC entity, plus several more where the current owner
parses to a different real person. `_clear_stale_matches` (run first, every
call) drops a match the current owner no longer supports so the row becomes
an ordinary candidate again — see `_owner_still_supports_match` for the real
examples. It only ever touches a match this module itself stamped (gated on
`source` in (DAC_SOURCE, SCDC_SOURCE)); a BOP or county-jail-roster match
sharing the same raw['incarceration'] key is left for enrichment_bop_federal.py
/ enrichment_jail_bookings.py to own.
"""
from __future__ import annotations

import asyncio
import os
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import certifi
import httpx
import structlog

from .config import in_scope_distressed
from .models import Listing
from .mailing_shape import mailing_dict
from .signal_freshness import incarceration_active

log = structlog.get_logger()

DAC_URL = "https://webapps.doc.state.nc.us/opi/offendersearch.do"
# SC Dept of Corrections public inmate search. The React SPA calls this with
# the query params in the URL (NOT the POST body) + method=POST; it returns a
# JSON array of inmate records. Verified live 2026-06-21.
SCDC_URL = "https://public.doc.state.sc.us/scdc-public/inmateSearch.do"
DAC_SOURCE = "NC DAC offender search"
SCDC_SOURCE = "SC DOC inmate search"

# Owner strings that aren't a person → no one to incarcerate, skip.
_ENTITY = re.compile(r"\b(LLC|L\.L\.C|INC|CORP|COMPANY|CO\b|TRUST|ESTATE|HEIRS|BANK|"
                     r"ASSOC|PARTNERS|LP\b|LLP|CHURCH|MINISTR|HOLDINGS|PROPERTIES|"
                     r"FUND|GROUP|AUTHORITY|COUNTY|CITY OF|STATE OF)\b", re.I)


def _name_parts(owner: str) -> Optional[tuple[str, str]]:
    """Return (last, first) from an owner string, or None if not a usable person.
    Handles 'LAST, FIRST M' and 'LAST FIRST M' (county GIS often stores either)."""
    if not owner or _ENTITY.search(owner):
        return None
    o = re.split(r"[;&]| and ", owner)[0].strip()  # first owner of a joint pair
    raw_o = o
    o = re.sub(r"[^A-Za-z, ]", " ", o).strip()
    if "," in o:
        # "LAST, FIRST M" — reliable
        last, _, rest = o.partition(",")
        toks = rest.strip().split()
        first = toks[0] if toks else ""
    else:
        toks = o.split()
        if len(toks) < 2:
            return None
        # Casing heuristic: ALL-CAPS no-comma is the GIS "LAST FIRST [MIDDLE]"
        # convention; mixed/Title-case is human "FIRST [MIDDLE] LAST".
        if raw_o.isupper():
            last, first = toks[0], toks[1]
        else:
            first, last = toks[0], toks[-1]
    last, first = last.strip().upper(), first.strip().upper()
    if len(last) < 2 or len(first) < 2:
        return None
    if len(last) >= 25 or len(first) >= 25:
        # A joint-owner mailing name with no separator before a comma-joined final
        # owner (e.g. "SMITH JOHN DOE JANE, WILL") makes the comma-partition above
        # swallow every prior owner into `last`. Not a real person's name either
        # way, and BOP's own form rejects at exactly 25 chars per field, despite
        # its own message saying "exceeds the allowed size of 25" -- live-verified
        # 2026-10-29: 24 chars passes, 25 chars fails, on both fields -- so every
        # such query was doomed
        # before it was sent, tripping bop_federal's host_failing breaker on a
        # deterministic input bug, not a real host problem.
        return None
    return last, first


_OFFENDER_LINK = re.compile(r"offenderID=\d+", re.I)
_NAME_CELL = re.compile(r"<td[^>]*>\s*([A-Z][A-Z .'-]{1,40}?)\s*</td>")
# Heading of the OPI results page. It is on a page with rows AND on the "No
# offenders found." page (checked live 2026-09-20 with a nonsense name), so it
# separates "the state answered: nobody" from a WAF / error page that says nothing.
_DAC_RESULTS_PAGE = re.compile(r"Offender\s+Search\s+Results", re.I)
# A host that shows one of these is telling us to stop, not answering the query.
_CHALLENGE = re.compile(r"captcha|access denied|just a moment|attention required|"
                        r"request unsuccessful|verify you are human|unusual traffic", re.I)
_BLOCK_STATUS = (401, 403, 407, 429)


@dataclass
class _Lookup:
    """One state-roster query, with the three facts the stamp logic needs.

    match      a name-only match that passed the single-exact-result gate, or None
    answered   the state gave a usable answer (a hit OR a real "nobody"); False for
               a timeout, a non-200, or a page we do not recognise. Only an answered
               miss may be stamped.
    blocked    403 / 429 / login / challenge: stop querying this host for the run
    candidates result rows the state returned (a miss on 24 "Robert Morgan"s is an
               answered miss, not an error)
    """
    match: Optional[dict] = None
    answered: bool = False
    blocked: bool = False
    candidates: int = 0


def _blocked_response(r) -> bool:
    return getattr(r, "status_code", 200) in _BLOCK_STATUS


async def _dac_lookup(http: httpx.AsyncClient, last: str, first: str) -> _Lookup:
    """Search NC DAC by name; a match needs the same last+first on EXACTLY ONE row."""
    params = {"method": "list", "searchLastName": last, "searchFirstName": first}
    try:
        r = await http.get(DAC_URL, params=params, timeout=25.0,
                            headers={"User-Agent": "Mozilla/5.0"})
        if _blocked_response(r):
            return _Lookup(blocked=True)
        if r.status_code != 200:
            return _Lookup()
        html = r.text
    except Exception:
        return _Lookup()
    if not _OFFENDER_LINK.search(html):
        if _DAC_RESULTS_PAGE.search(html):
            return _Lookup(answered=True)          # "No offenders found."
        return _Lookup(blocked=bool(_CHALLENGE.search(html)))  # unknown page: no answer
    # Confirm a result row actually carries this last AND first name (the search
    # can be loose); the result table lists last/first in adjacent cells.
    n_results = len(_OFFENDER_LINK.findall(html))
    cells = [c.strip().upper() for c in _NAME_CELL.findall(html)]
    has_last = any(c == last for c in cells)
    has_first = any(c == first for c in cells)
    # Only flag a NEAR-UNIQUE name. A name returning many offenders (e.g. 24
    # "Robert Morgan"s) is noise; 1-2 exact matches is a usable lead. Even then
    # it's name-only (no DOB) → low confidence, stack-signal only.
    # 2026-06-19: require EXACTLY ONE result. With 2+ result rows, has_last and
    # has_first can match DIFFERENT offenders (cross-row), producing hard name
    # mismatches (e.g. last from row A + first from row B). A single result row
    # makes cross-row contamination impossible, so the name match is reliable.
    max_results = int(os.environ.get("INCARCERATION_MAX_RESULTS", "1"))
    if has_last and has_first and 1 <= n_results <= max_results:
        return _Lookup(match={"state": "NC", "source": DAC_SOURCE,
                              "matched_name": f"{first} {last}", "results": n_results,
                              # NC DAC is the state prison system — never a
                              # county jail (see enrichment_jail_bookings.py)
                              # or federal BOP (see enrichment_bop_federal.py).
                              "facility_type": "prison",
                              "confidence": "name_only_low"},
                       answered=True, candidates=n_results)
    return _Lookup(answered=True, candidates=n_results)


# SC TLS CHAIN FIX (2026-11-23, found live: every _scdc_lookup call was failing
# `ssl.SSLCertVerificationError: unable to get local issuer certificate`, 100% of the
# time, which enrich_incarceration()'s circuit breaker correctly read as "unanswered" and
# tripped on after INCARCERATION_MAX_FAILURES (default 8) consecutive misses -- abandoning
# the rest of every run's SC candidates with zero effect, hence SC's candidate pool never
# advanced). Root cause, confirmed with openssl s_client + the leaf cert's own Authority
# Information Access extension: public.doc.state.sc.us serves ONLY its leaf certificate
# (*.doc.state.sc.us), omitting the "GoDaddy TLS Intermediate CA DV - R1v1" it actually
# chains to -- a server-side misconfiguration (the intermediate was never bundled into
# their TLS config), not a WAF/CAPTCHA block (that is a DIFFERENT, already-handled path --
# see res.blocked/host_blocked above) and not a parsing bug. The chain verifies
# cryptographically end-to-end (openssl verify: OK) once completed; it just is not yet in
# certifi's Mozilla-derived root bundle (both certs below are dated 2025-08-28 -- a new
# GoDaddy root generation, root-program inclusion lags real deployment by design).
#
# Fetched directly from the leaf cert's own AIA "CA Issuers" URLs (the same authoritative
# source a browser's own AIA-chasing would use, not a third-party mirror):
#   intermediate: http://certificates.godaddy.com/repository/gd_tls_issuing_dv-r1v1.crt
#   root:         http://certificates.godaddy.com/repository/gd_tls_root-r1.crt
# Completing the real chain (rather than disabling verification) matters here precisely
# because this enricher feeds raw['incarceration'] matches straight into distress_score --
# an unverified connection could have a MITM silently substitute fabricated match data.
# Scoped to ONLY this module's httpx client (see _ssl_context() below); NC's DAC lookups
# already verify fine against the stock certifi bundle and are unaffected.
_GODADDY_TLS_INTERMEDIATE_DV_R1V1 = """-----BEGIN CERTIFICATE-----
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
-----END CERTIFICATE-----
"""

_GODADDY_TLS_ROOT_R1 = """-----BEGIN CERTIFICATE-----
MIIFWTCCA0GgAwIBAgIRANpi/54mGbElekgJNo7o4/cwDQYJKoZIhvcNAQELBQAw
RjELMAkGA1UEBhMCVVMxFDASBgNVBAoTC0dvRGFkZHkuY29tMSEwHwYDVQQDExhH
b0RhZGR5IFRMUyBSb290IENBIC0gUjEwHhcNMjUwODI4MTIwMDAwWhcNNDAwODI0
MTE1OTU5WjBGMQswCQYDVQQGEwJVUzEUMBIGA1UEChMLR29EYWRkeS5jb20xITAf
BgNVBAMTGEdvRGFkZHkgVExTIFJvb3QgQ0EgLSBSMTCCAiIwDQYJKoZIhvcNAQEB
BQADggIPADCCAgoCggIBAMLrcp3XnknkTvY9I1IzsQA8K/vp5TJRiYsCZWMitXxG
H+yD1+dPuC5nVzu6BLlXWZ8f7E7cs7lGBUeygeb2CsrESx1uFtB8R3JR4UOAMNE/
KrlYFwHBydF1JhcttMEEkojBqt9If+Ks8Go2Be4rIAj495yFzArAPc8Ax2kyGgqf
9Sl0S1SUbxkuvNRomsb3uNg+rcSWg4zUVixQijIZm2AIBxNW9gzaghs6dnog6rgq
wBYKk7WNhZOfATkq/GHU9glnmiiMMeFPK2kqo9YNWk17NzEYmrBp6ELJwMwhuupX
LifmoOAL2axvkO1ci66WKBxPB5OPgy5WfdhYp7l2Az8d9MDKWCYwPTpRjwf41AgG
KhrwMjEJ+H/tG+wu7vWH0Bk+Bfl2gBtNyGjvObGJHMgJusPASDbWThBaw4PrA6sK
TNPaQCYtVCYi6h/JXB39P2ilTixeC9hiEFmPkwplgjf/t/7CvF6XoCRIFkU2vUYN
5WQ9upLYRTMZIVrHOxHOcxevvbD2jSuIz2ZydWWdwSzoQb8g5/bmhfrXwLPlCAZh
hx+E5ljM/OLlkaySoi35mGE4MVOfld94J7m11UeY76t43RIGW0HF7fwm556C3thd
70RZ3KWwSiOBJQGzDMzjY+R53kJnUljPSlSqDemUE1fsG7evOPgrZSXc8rP2WTAx
AgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBhjAPBgNVHRMBAf8EBTADAQH/MB0GA1Ud
DgQWBBTsUhGVcHMZyN7KSEOXSxw1JCJDUDANBgkqhkiG9w0BAQsFAAOCAgEAndbU
wF1KXURZgNLhfC0UkO0qBS2tHXhqJ2AGVMrOkX2+WFwPZ4jOqDTQoobcOXRBlE6O
eLSGYquyTEW43gWHVy6+UKP1jnBLhpcaib56F5Wp8Fi3eZpT+3MojZEofMtZg7rG
Jmn6vf1QLztm66JBb7uh1yVruHZupfT0TXZ8Sbpf8xVVWnq+owgVzTFsfSjWyBps
5G9e/IWYfl6r9rmAPmPdo8LqxUmJXfjL06RlZ2K7HghBQgefEuBjUkSXFR73SyZH
f8IR+CRbwjV0hmhn2NWDos1MB9TLKm/C8HQ49acBybtLmsTai+i+RT/N6UB1TNTw
Ts+eZ42z5Danmw+KDO7JI6m/WrlDOuDkyRmY2TKI8vvEeKHfaBehGHUMEWQZe2d2
AHFvmAonhB10aXUhjAbUMZs4SCo241iuz28FMoVCC6pa07l8A84IRbUfu9OMRkmm
Ydmd5Pa4ggfkhtJwFxMbR/3bhsDi8tRwkgS6XNOixXK/azf9TA2RqyOsiiJFjffO
xS4nnYkLtgzqf7hs+Qe3D5UDWUgJyx8AYiwKJIMDlLz+CO8yYIx+YMsKS8jHvclI
X5DePkFKKNWCUz5x2wlfPbXUPhTjsKO2m3F6009Gf4bQgBL60rzBOuo1Wp6fSlDE
b9J1nSdKq7qIj1IJ5icFCDhzV+P1LjVv77My5Rw=
-----END CERTIFICATE-----
"""


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    """The default certifi trust store PLUS the two GoDaddy certs above -- see the
    SC TLS CHAIN FIX comment. Adding extra trusted certs never weakens verification for
    any OTHER site (NC's DAC lookups are unaffected); it only completes the one chain
    public.doc.state.sc.us fails to serve in full. Cached: built once per process, not
    once per lookup."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cadata=_GODADDY_TLS_INTERMEDIATE_DV_R1V1)
    ctx.load_verify_locations(cadata=_GODADDY_TLS_ROOT_R1)
    return ctx


async def _scdc_lookup(http: httpx.AsyncClient, last: str, first: str) -> _Lookup:
    """Search SC DOC by name; a match needs EXACTLY ONE exact last+first record."""
    params = {"lastName": last, "firstName": first, "scdcId": "", "sid": "",
              "phoneticMatch": ""}
    try:
        # SCDC wants the params in the QUERY STRING with method=POST (mirrors
        # the SPA's own fetch); a body POST returns an empty 200.
        r = await http.post(SCDC_URL, params=params, timeout=25.0,
                            headers={"User-Agent": "Mozilla/5.0",
                                     "Accept": "application/json, text/plain, */*"})
        if _blocked_response(r):
            return _Lookup(blocked=True)
        if r.status_code != 200:
            return _Lookup()
        recs = r.json()
    except Exception:
        return _Lookup()
    if not isinstance(recs, list):
        return _Lookup()                           # HTML / error body, not an answer
    if not recs:
        return _Lookup(answered=True)              # "[]": the state says nobody
    # Exact last+first (fields are space-padded in the feed). Require EXACTLY one
    # so a common name returning several offenders is treated as noise, not a hit.
    exact = [x for x in recs
             if str(x.get("lname") or "").strip().upper() == last
             and str(x.get("fname") or "").strip().upper() == first]
    max_results = int(os.environ.get("INCARCERATION_MAX_RESULTS", "1"))
    if 1 <= len(exact) <= max_results:
        rec = exact[0]
        return _Lookup(match={"state": "SC", "source": SCDC_SOURCE,
                              "matched_name": f"{first} {last}", "results": len(exact),
                              "scdc_id": str(rec.get("scdcId") or "").strip() or None,
                              # SC DOC (SCDC) is the state prison system.
                              "facility_type": "prison",
                              "confidence": "name_only_low"},
                       answered=True, candidates=len(recs))
    return _Lookup(answered=True, candidates=len(recs))


async def _dac_match(http: httpx.AsyncClient, last: str, first: str) -> Optional[dict]:
    """Match info if NC DAC lists exactly one offender with this last+first, else None."""
    return (await _dac_lookup(http, last, first)).match


async def _scdc_match(http: httpx.AsyncClient, last: str, first: str) -> Optional[dict]:
    """Match info if SC DOC lists exactly one offender with this last+first, else None."""
    return (await _scdc_lookup(http, last, first)).match


def _owner_of(li: Listing) -> Optional[str]:
    om = mailing_dict(li)
    return om.get("owner") or li.defendant or None


def _owner_still_supports_match(li: Listing) -> bool:
    """A stale state-prison match is worse than no tag -- same "missing-only,
    never revisited" shape commit 9e3fd2c9 fixed for enrichment_bop_federal.py
    the same day, one lane over: this module's own
    `if (li.raw or {}).get("incarceration"): continue` guard treats ANY
    existing NC DAC / SC DOC match as permanent, so a later owner-name refresh
    (a sale, an estate closing, a parcel_cache correction) never gets
    reconciled against a name-keyed match stamped against whoever used to own
    the parcel. Live-checked 2026-10-03 against the real board: 11 rows carry
    raw['incarceration'] naming someone with zero relation to the CURRENT
    owner, which is now an unrelated entity (a bank, a city, an HOA, an LLC --
    e.g. a Henderson parcel matched "MICHAEL PEAK" but now reads
    "FIRST CITIZENS BANK & TRUST CO"; a Gaston parcel matched "DEANA WILSON"
    but now reads "GASTONIA CITY OF"), plus several more rows where the
    current owner parses to a different real person entirely.

    Returns True ("leave it alone") when raw['incarceration'] is absent, was
    stamped by a DIFFERENT enricher (BOP federal or a county jail roster --
    each owns clearing its own, see enrichment_bop_federal.py /
    enrichment_jail_bookings.py), or still names a person the CURRENT owner
    supports. Returns False only when THIS module's own NC DAC/SC DOC match no
    longer matches the current owner name -- the caller clears the stale tag
    so the row becomes an ordinary candidate again instead of quietly keeping
    someone else's state-custody record forever."""
    match = li.raw.get("incarceration") if isinstance(li.raw, dict) else None
    if not isinstance(match, dict) or match.get("source") not in (DAC_SOURCE, SCDC_SOURCE):
        return True                     # not this module's match -- don't touch it
    queried = str(match.get("matched_name") or "").strip().upper()
    if not queried:
        return True                     # nothing to check against -- don't touch it
    owner = _owner_of(li)
    parts = _name_parts(owner) if owner else None
    if not parts:
        return False                    # current owner isn't even a person anymore
    last, first = parts
    return queried == f"{first} {last}"


def _clear_stale_matches(listings: list[Listing]) -> int:
    """Pre-pass: drop any NC-DAC/SC-DOC raw['incarceration'] match the CURRENT
    owner no longer supports (see _owner_still_supports_match), so the normal
    candidate-selection loop below picks the row up again as if never checked.
    Only ever removes a match THIS module itself set (checked by `source`) --
    never touches a BOP or county-jail-roster entry sharing the same key."""
    cleared = 0
    for li in listings:
        if li.state not in ("NC", "SC") or not isinstance(li.raw, dict):
            continue
        if _owner_still_supports_match(li):
            continue
        li.raw.pop("incarceration", None)
        cleared += 1
    return cleared


# ---- negative stamps, selection and rotation ---------------------------------

def _recheck_days() -> float:
    """How long an answered miss stays fresh. A person can be sentenced at any
    time, so a "no" is not permanent; 30 days matches the divorce enricher."""
    try:
        return float(os.environ.get("INCARCERATION_RECHECK_DAYS", "30"))
    except ValueError:
        return 30.0


def _county_key(li: Listing) -> tuple[str, str]:
    return (li.state or "", (li.county or "").replace(" County", "").strip().title())


def _stamp_of(li: Listing, name: str) -> Optional[datetime]:
    """When this lead's CURRENT owner name was last checked, or None if never.
    A stamp for a different name (the owner was re-resolved since) does not count."""
    st = li.raw.get("incarceration_check") if isinstance(li.raw, dict) else None
    if not isinstance(st, dict) or st.get("name") != name:
        return None
    try:
        dt = datetime.fromisoformat(str(st.get("checked_at")))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _round_robin(groups: dict, keys: list, budget: int, cap: int) -> list:
    """Take one lead per county per pass, so one big county cannot eat the budget."""
    out: list = []
    depth = 0
    while len(out) < budget:
        moved = False
        for k in keys:
            g = groups[k]
            if depth < len(g) and (cap <= 0 or depth < cap):
                out.append(g[depth])
                moved = True
                if len(out) >= budget:
                    break
        if not moved:
            break
        depth += 1
    return out


def _select_targets(cands: list, max_queries: int, per_county_cap: int,
                    now: datetime) -> list:
    """Pick this run's leads from (lead, name, last_checked) candidates.

    Within a county: never-checked leads first (board order), then the oldest
    stamps. Across counties: round-robin, the 146-county distressed footprint
    (config.in_scope_distressed) before the rest, each county capped at
    per_county_cap. The county order rotates daily so the partial last pass
    does not always favour the same ones.
    """
    groups: dict[tuple[str, str], list] = {}
    for li, _name, checked in cands:
        groups.setdefault(_county_key(li), []).append((checked, li))
    for k, g in groups.items():
        # stable sort: unstamped (None) keep board order and sit ahead of stamped
        g.sort(key=lambda t: (t[0] is not None, t[0].timestamp() if t[0] else 0.0))
        groups[k] = [li for _c, li in g]
    keys = sorted(groups)
    spin = now.toordinal() % len(keys) if keys else 0
    keys = keys[spin:] + keys[:spin]
    # An incarcerated owner is a motivated-seller LEAD signal, not a flip-listing gate
    # (this module's own docstring) -- config.py's own docstring says every such signal
    # must use the 146-county in_scope_distressed(), not the 18-county flip-only
    # in_scope(). The old in_scope() call meant this module's budget was almost entirely
    # absorbed by 18 of 143 gap-listed counties every run (audit 2026-10-16).
    core = [k for k in keys if in_scope_distressed(k[1], k[0])]
    rest = [k for k in keys if k not in core]
    picked = _round_robin(groups, core, max_queries, per_county_cap)
    if len(picked) < max_queries:
        picked += _round_robin(groups, rest, max_queries - len(picked), per_county_cap)
    return picked


def _stamp_miss(li: Listing, name: str, source: str, now: datetime) -> None:
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["incarceration_check"] = {
        "checked_at": now.replace(microsecond=0).isoformat(), "name": name,
        "source": source, "result": "no_match"}


async def enrich_incarceration(listings: list[Listing], max_queries: Optional[int] = None,
                               per_county_cap: Optional[int] = None,
                               recheck_days: Optional[float] = None) -> dict:
    """Flag listings whose owner matches a state corrections roster (NC + SC).

    max_queries     total lookups this run (env INCARCERATION_MAX_QUERIES, default 150)
    per_county_cap  most leads any one county may take (env INCARCERATION_PER_COUNTY_CAP,
                    default 50; 0 = no cap)
    recheck_days    how long an answered miss stays fresh (env INCARCERATION_RECHECK_DAYS,
                    default 30)

    Starts with a read-only-looking but mutating pre-pass (_clear_stale_matches)
    that drops any NC-DAC/SC-DOC match the CURRENT owner no longer supports, so
    a sale/estate-closing/parcel_cache correction since the match was stamped
    doesn't leave someone else's state-custody record sitting on the lead
    forever -- see _owner_still_supports_match for the real example that
    found this.
    """
    if max_queries is None:
        max_queries = int(os.environ.get("INCARCERATION_MAX_QUERIES", "150"))
    if per_county_cap is None:
        per_county_cap = int(os.environ.get("INCARCERATION_PER_COUNTY_CAP", "50"))
    window = _recheck_days() if recheck_days is None else float(recheck_days)
    now = datetime.now(timezone.utc)

    stale_cleared = _clear_stale_matches(listings)

    cands, fresh = [], 0
    for li in listings:
        if li.state not in ("NC", "SC"):
            continue
        raw = li.raw or {}
        # An ended county-jail flag no longer blocks the lookup: that is exactly the person
        # who may have moved on to state prison.
        if incarceration_active(raw.get("incarceration"), raw.get("jail_booking")):
            continue
        owner = _owner_of(li)
        parts = _name_parts(owner) if owner else None
        if not parts:
            continue
        name = f"{parts[1]} {parts[0]}"
        checked = _stamp_of(li, name)
        if checked is not None and (now - checked).total_seconds() < window * 86400:
            fresh += 1
            continue
        cands.append((li, name, checked))
    targets = _select_targets(cands, max_queries, per_county_cap, now)
    if not targets:
        log.info("incarceration.no_targets", skipped_fresh=fresh, stale_cleared=stale_cleared)
        return {"queried": 0, "matched": 0, "stale_cleared": stale_cleared}

    sem = asyncio.Semaphore(int(os.environ.get("INCARCERATION_CONCURRENCY", "1")))
    delay = float(os.environ.get("INCARCERATION_DELAY", "1.0"))
    counts = {"queried": 0, "matched": 0, "matched_nc": 0, "matched_sc": 0,
              "stamped_miss": 0, "failed": 0, "skipped_fresh": fresh,
              "candidates": len(cands), "selected": len(targets), "blocked_hosts": 0,
              "stale_cleared": stale_cleared}
    tripped: set[str] = set()      # states whose host we stopped asking this run
    strikes = {"NC": 0, "SC": 0}   # consecutive unusable answers per state
    cache: dict[tuple, asyncio.Future] = {}
    max_strikes = int(os.environ.get("INCARCERATION_MAX_FAILURES", "8"))

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True,
                                  verify=_ssl_context()) as http:
        async def lookup(state: str, last: str, first: str) -> Optional[_Lookup]:
            async with sem:
                if state in tripped:
                    return None
                counts["queried"] += 1
                # Route to the right state's corrections roster.
                res = await (_scdc_lookup if state == "SC" else _dac_lookup)(http, last, first)
                if res.blocked:
                    tripped.add(state)
                    counts["blocked_hosts"] += 1
                    log.warning("incarceration.host_blocked", state=state)
                elif res.answered:
                    strikes[state] = 0
                else:
                    strikes[state] += 1
                    if strikes[state] >= max_strikes:
                        tripped.add(state)
                        log.warning("incarceration.host_failing", state=state)
                if delay:
                    await asyncio.sleep(delay)
                return res

        async def one(li: Listing):
            last, first = _name_parts(_owner_of(li))
            key = (li.state, last, first)
            # The same owner often holds several parcels: ask the state once.
            if key not in cache:
                cache[key] = asyncio.ensure_future(lookup(li.state, last, first))
            res = await cache[key]
            if res is None or res.blocked:
                return                         # not asked: leave the lead unstamped
            if res.match:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["incarceration"] = res.match
                li.raw.pop("incarceration_check", None)
                counts["matched"] += 1
                counts["matched_sc" if li.state == "SC" else "matched_nc"] += 1
            elif res.answered:
                # A miss the state actually answered: remember it so the next run
                # moves on to leads it has not checked.
                _stamp_miss(li, f"{first} {last}",
                            SCDC_SOURCE if li.state == "SC" else DAC_SOURCE, now)
                counts["stamped_miss"] += 1
            else:
                counts["failed"] += 1          # no answer: never stamped
        await asyncio.gather(*(one(li) for li in targets))
    log.info("incarceration.done", **counts)
    return counts
