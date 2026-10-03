"""County-jail booking enrichment — pre-trial / local-hold incarceration signal.

The state-prison match (enrichment_incarceration: NC DAC + SC SCDC) only catches
people already sentenced to state custody. County jail rosters catch the much
larger pool of PRE-TRIAL detainees and local holds — an owner sitting in the
county jail (can't manage the property, family needs liquidity, bond to make) is
a motivated seller the state rosters miss entirely.

We fetch each county's CURRENT in-custody roster once per run (free public
"jail viewer" APIs), index it by (last, first), and match resolved owner names.
Several rosters expose full DOB, which we keep for future disambiguation (we
still match name-only today since we have no owner DOB — so this stays a
LOW-confidence STACK signal, meaningful only combined with other distress).

Two access shapes:

BULK ROSTERS (fetch the whole current in-custody list once/run, index by name):
  * Zuercher portal  — Cherokee SC (dob+charges), Anderson SC (name+charges, no dob)
    and, added 2026-09-20, Laurens SC (charges, DOB blank on the tenant) and
    Oconee SC (dob+charges)
  * CentralSquare P2C jqGrid — Cleveland NC (dob+charges)
  * CentralSquare P2C (modern) — Buncombe NC (name+age+booking date+charge; the
    public roster redacts DOB). This build is the "session/token handshake"
    variant: the SPA at policetocitizen.com sets an XSRF-TOKEN cookie only after
    an app-route GET, which we then echo back as the X-XSRF-TOKEN header on the
    JSON /api/Inmates/<id> search POST. The endpoint caps Take at ~200 and never
    fills TotalCount, so we page in blocks of 200 until a short page. Free,
    compliant (open JSON-XHR + standard anti-forgery echo, no login/CAPTCHA/WAF
    defeat). Verified live 2026-07-01: 542 in custody.
  * Southern Software Citizen Connect — Henderson NC. PHP roster whose "Get
    Current Confinements" button XHRs fetch_current_confinements.php; the
    endpoint needs a PHP session seeded by one GET of the booking-search page
    (?AgencyID=HendersonCoNC) or it answers 500 "Session AgencyID not set".
    20 cards/page, pager posts IDX=<page>. Publishes FULL DOB. Verified live
    2026-07-31: 182 in custody, DOB on 182/182.
  * Tyler New World InmateInquiry — Gaston NC. Plain GET form, so
    ?InCustody=True&Page=<n> yields the whole roster 100 rows at a time with
    FULL DOB, the in-custody flag and the scheduled release date. This replaces
    Gaston's retired newworld.aegis.webportal InmateInquiry.aspx per-name
    search, which now 302s to Shared/Default.aspx and returns nothing. Verified
    live 2026-07-31: 695 in custody, DOB on 695/695.

PER-NAME SEARCH ROSTERS (no "show all"; we search each in-scope owner's last name):
  * Greenville SC — LANSA-for-the-Web WEBEVENT postback
    (app.greenvillecounty.org/cgi-bin/lansaweb, proc JAW_00 / func JAW00EX).
    GET the framed entry to get the session-scoped WEBEVENT action token + ~36
    hidden fields; POST them back with ASC_NML (last), ASC_NMF (first) and
    ASTDRENTST=SEARCH (what the page's Search link sets before HandleEvent). The
    grid is current detainees only: Name (LAST, FIRST MIDDLE) | Book Date | Race
    | Sex | Age | Height | Weight, headed by "Records Found: N". An Incapsula
    script is present but passive — the page and POST both complete with plain
    curl_cffi chrome impersonation (no WAF token solved/defeated). Greenville is
    the largest SC jail population. Verified live 2026-07-01: SMITH -> 28 records.

Adding a BULK county = one ROSTERS entry; a SEARCH county = one SEARCH_ROSTERS
entry, once its vendor endpoint is confirmed. Spartanburg SC has no entry
because its portal is offline, not because it is walled: the Sheriff's Bookings
Search 302s to http://mugshots.spartanburgsheriff.org/, whose host stopped
answering on :80 and :443 (last Internet Archive capture 2026-03-08), and the
county is not a Zuercher / P2C / JailTracker tenant.

Sets raw['jail_booking'] (detail) + raw['incarceration'] (so distress_score's
existing LEGAL incarceration signal, weight 8, picks it up). Free + compliant.

STANDING RE-QUERY (Dirty Deeds Tier B #36, 2026-09-29). Until this change every
run treated each roster fetch as an independent snapshot: match_rosters skips a
listing the moment raw['jail_booking'] is truthy, so a name was matched at most
ONCE, ever, with no durable memory of when it was first seen and no way to
notice the person later turning up on a DIFFERENT county's roster (the
synthesis's ep 069 fugitive-heir story -- a saved search re-fires on a booking
nowhere near the property). `jail_roster_history.py` is the fix: a small SQLite
sidecar (data/jail_roster_history.db, gitignored like every other sidecar in
this repo) that remembers every (state, county, name) this module has ever
fetched. `_load_roster` diffs each fetch against it and tags every roster record
with `is_new_booking` / `first_detected_at` -- "start the clock at detection"
for the 6-8 week approved-contact-registration mechanic. `match_cross_county`
then uses that sidecar-confirmed newness to flag raw['jail_booking_new'] when a
NEW booking's name matches a listing whose OWN property county is different from
the booking county -- a distinct signal, deliberately never written into
raw['jail_booking'] or raw['incarceration'], so it cannot change an existing
distress_score count or silently re-fire on the same cross-county pairing every
run forever (it only fires the run a name is new to that county).

FACILITY TYPE (Tier B #36's other ask): every source in ROSTERS/SEARCH_ROSTERS
is a county SHERIFF jail booking system (P2C, Zuercher, Citizen Connect, Tyler,
LANSA) -- pre-trial holds and short local sentences, never a state prison or
federal BOP facility. So `facility_type` here is a constant, source-level
inference ("jail"), not a per-record lookup; the state-prison lane
(enrichment_incarceration.py) tags "prison" and the federal lane
(enrichment_bop_federal.py) derives federal_prison / federal_detention /
community_confinement from BOP's own facility-type code. Jails restrict inbound
mail far more than prisons (synthesis: one jail would only accept a deed packet
from a licensed attorney in person) -- this field is what would drive an
outreach-channel decision downstream, though nothing reads it for that yet.

DRY-RUN SIDECAR BUG (fixed 2026-09-29). Reproduced via real before/after run
logs: `scripts/run_pending_signal_enrichers.py --dry-run` found 590 genuine
jail_booking_new cross-county matches; the REAL apply pass ~35 minutes later,
against the same counties, found 0 new matches. Cause: `_load_roster`
unconditionally called `jail_roster_history.diff_and_record(...)`, which
commits every fetch's diff to the sidecar regardless of whether the CALLING
script is a dry run -- so the dry run's own roster fetch got recorded as
"seen," and the real run's fetch of the same rosters 35 minutes later saw
`is_new=False` everywhere. Fix: `enrich_jail_bookings`/`_load_roster` now take
a `dry_run` parameter that reaches `diff_and_record(commit=not dry_run)` --
mirrors `foreclosure_docket_history.observe_case`'s `commit` parameter,
already used for the same "compute but don't commit" purpose. A dry run still
fetches every roster and still computes/reports accurate is_new_booking /
first_detected_at (so its own printed report is correct); it just never
persists that diff, so a real run afterward still sees the same bookings as
new. `scripts/run_pending_signal_enrichers.py` and
`scripts/catchup_failed_enrichers.py` both now pass their own `--dry-run` flag
through to this call.

CROSS-COUNTY NAME-ONLY FANOUT (fixed 2026-10-02). A real backfill run on
2026-10-02 found 12,337 board rows carrying raw['jail_booking_new'] against a
run-log "matched" figure of 639 — a ~19x gap. Root cause, confirmed by reading
`match_cross_county` as originally written (commit 9c16d8ee, 2026-09-29) and
its git history (unchanged since): the SAME-COUNTY tier (`match_rosters`,
confidence "name_only_low") only ever searches ONE county's roster against
THAT county's own leads, so its blast radius is capped by county population.
`match_cross_county` instead takes `_owner_name_index` -- every NC/SC listing
on the WHOLE BOARD keyed by (state, normalized last, normalized first) -- and
flags EVERY listing whose owner shares an exact first+last name with ANYONE
newly booked on ANY covered county's roster, with NO other corroborating
field: no middle name, no DOB, no county adjacency, nothing. This was true
from the moment the tier was introduced (2026-09-29); it is not a regression.
A common name (e.g. "JAMES HARRIS") newly booked in one county can sit on the
board under thousands of unrelated owners statewide, and the whole-board
index turns that one booking into thousands of false "this owner may be
incarcerated" stamps in a single run. The 639-vs-12,337 gap is consistent with
`scripts/run_pending_signal_enrichers.py` printing `jail_bookings`' own
"matched" key (the bounded same-county tier) as the headline number while
`cross_county` (printed in the same line, and again in the before/after delta
for raw key jail_booking_new) carried the real, much larger figure; it is
also consistent with the 2026-09-29-to-2026-10-02 window including the first
real run of this step against a cold (empty or near-empty)
`data/jail_roster_history.db` on the Oracle VM (idle since 2026-09-03, see
project_oracle_vm_revival note) -- `jail_roster_history.diff_and_record` marks
a name "is_new" on its FIRST-EVER INSERT for that (state, county, name) key,
so a sidecar with little or no prior history makes most or all of a county's
CURRENT roster register as "new" in one run, not just genuinely fresh
bookings -- amplifying the already-uncorroborated fanout further. Both
factors are explicitly called out as a follow-up verification, not asserted
as the full explanation: the fix below removes the structural cause (the
missing corroboration requirement) regardless of which amplified it on any
given run.

Fix: this project already has an established convention for exactly this
"common name, thin match" problem --
`name_normalize.party_middle_verdict`/`owner_last_first_middle`, built for
the SC-divorce party match (41% of comparable hits were a different person
with the same first+last name, audit 2026-09-21) and reused by
`enrichment_sc_phone.py`'s voter-phone identity gate, where an "unverified"
(no middle on one side) match is explicitly NOT good enough to dial.
`match_cross_county` never used it. It now does, via `_cross_county_corroborated`:
a cross-county stamp requires the booking's middle name (now captured by
`_split_zuercher_name` / `_split_comma_name`, previously parsed and thrown
away) to POSITIVELY AGREE with the board owner's middle initial --
`party_middle_verdict(...) == "agrees"`, not merely "not a conflict." This is
stricter than the divorce gate on purpose: that gate treats "unverified" as
passable (a county-matched voter phone can still corroborate); this tier has
no analogous second signal, so "unverified" is now rejected outright, the
same fail-closed default `name_normalize`'s own module docstring states as
this codebase's policy ("errs toward committing nothing"). The confidence tag
changes from "name_only_low_cross_county" to "middle_corroborated_cross_county"
so it reads as what it now is, and so no downstream code can confuse it with
the old, uncorroborated tier. `match_rosters`' same-county tier (confidence
"name_only_low") is deliberately left as-is: it is the tier the module's own
earlier docstring already discloses and accepts as a bounded, low-confidence
STACK signal (weight 8 in distress_score.py); it was not the source of this
incident and this fix does not change its behavior.

Checked whether any scorer compounds this: as of this fix, raw['jail_booking_new']
is read by nothing outside this module, its own tests, and
`scripts/run_pending_signal_enrichers.py` (which only counts/patches it) --
`distress_score.py` scores raw['jail_booking']/raw['incarceration'] (the
same-county tier) only, confirmed by grepping every reference to
"jail_booking_new" in the repo. So the already-written rows are inert for
scoring today; the risk is a human reading raw['jail_booking_new'] directly
off the board, or a future scorer wiring it in uncorroborated. See
docs/HANDOFF.md / the 2026-10-02 follow-up note for the precise scope of
correcting the rows this already wrote on the Oracle VM's uncommitted board.

STALE-MATCH INVALIDATION (2026-10-03, same bug shape as owner_name/bop_federal/
enrichment_incarceration's own state-prison lane, found during the same sweep):
`match_rosters` and the per-name SEARCH_ROSTERS lane both skip a listing the
moment raw['jail_booking'] is truthy, forever -- a later owner-name refresh
(a sale, an estate closing) never gets reconciled against a name-keyed match
stamped against whoever used to own the parcel. `_clear_stale_matches` (run
first, every call) drops a jail_booking match the current owner no longer
supports, and the shared raw['incarceration'] flag with it ONLY when that
flag's own `source` is a county-jail-roster entry this module itself set --
never an NC-DAC/SC-DOC or BOP match sharing the same key, each of which owns
clearing its own (enrichment_incarceration.py / enrichment_bop_federal.py).
See `_owner_still_supports_match` for the mechanism.
"""
from __future__ import annotations

import asyncio
import re
import traceback
from datetime import datetime, timezone
from typing import Optional

import structlog

from . import jail_roster_history

from .models import Listing
from .enrichment_incarceration import DAC_SOURCE, SCDC_SOURCE, _name_parts, _owner_of
from .enrichment_bop_federal import BOP_SOURCE
from .name_normalize import party_middle_verdict
# The Citizen Connect / Tyler fetchers are shared verbatim with the standalone
# jail-bookings scraper rather than duplicated here.
from .scrapers.national.jail_bookings import (
    _fetch_citizen_connect,
    _fetch_tyler_detail,
    _fetch_tyler_inmate_inquiry,
)

log = structlog.get_logger()

# (state, county, vendor, target) — target is the Zuercher subdomain, the P2C
# jqGrid base URL, the "<host>|<listId>" pair whose XHR search is
# /api/Inmates/<listId> (modern CentralSquare P2C), the
# "<AgencyID>|<JMSAgencyID>" pair (Citizen Connect), or the app base URL
# (Tyler New World InmateInquiry).
ROSTERS = [
    ("SC", "Cherokee", "zuercher", "cherokee-so-sc"),
    ("SC", "Anderson", "zuercher", "anderson-so-sc"),
    ("NC", "Cleveland", "p2c_jqgrid", "http://74.218.167.200/p2c"),
    ("NC", "Buncombe", "p2c_centralsquare",
     "https://buncombecountyso.policetocitizen.com|23"),
    ("NC", "Henderson", "citizen_connect", "HendersonCoNC|NC0450000"),
    ("NC", "Gaston", "tyler_inmate_inquiry",
     "https://tepsweb.cityofgastonia.com/NewWorld.InmateInquiry/GastonCounty"),
    # Added 2026-08-06. All three ride adapters that already existed — Polk and
    # Transylvania are the same Southern Software tenant as Henderson (only the
    # JMSAgencyID differs), Burke is the same CentralSquare P2C as Buncombe.
    # Verified live through the real adapters that day: Burke 175 in custody,
    # Transylvania 83, Polk 44. The incarceration signal covered 15 leads across
    # all 18 counties before this.
    ("NC", "Polk", "citizen_connect", "PolkCoNC|NC0750000"),
    ("NC", "Transylvania", "citizen_connect", "TransylvaniaCoNC|NC0880000"),
    ("NC", "Burke", "p2c_centralsquare",
     "https://morgantonpdnc.policetocitizen.com|342"),
    # Lincoln runs the SAME CentralSquare jqGrid build as Cleveland — only the
    # host differs. Verified live through the existing adapter: 173 in custody.
    # NB the vendor typos its own agency as 'Lncoln County'; there is also a
    # Lincoln County NEBRASKA P2C, so match on the host, never the agency string.
    ("NC", "Lincoln", "p2c_jqgrid", "http://p2c.lincolnsheriff.org"),
    # Added 2026-09-20 (build queue J-03). Laurens SC is the same Zuercher body the
    # Cherokee and Anderson tenants take; the DOB field is blank on this tenant.
    # Verified live through the existing adapter that day: 181 in custody.
    ("SC", "Laurens", "zuercher", "laurens-911-sc"),
    # Oconee SC (build queue J-04): the sheriff's own inmate-search page links to
    # oconee-so-sc.zuercherportal.com/#/inmates, so it is the same Zuercher body.
    # Verified live through the existing adapter 2026-09-20: 183 in custody, DOB on
    # every row. No state-prison-only gap left for Oconee once this rides.
    ("SC", "Oconee", "zuercher", "oconee-so-sc"),
]

# (state, county, vendor, target) for the PER-NAME search vendors — no bulk
# "show all", so we search each in-scope owner's last name at match time.
SEARCH_ROSTERS = [
    ("SC", "Greenville", "lansa",
     "https://app.greenvillecounty.org/cgi-bin/lansaweb?procfun+JAW_00+JAW00EX+GP1+eng"),
]


def _norm_key(last: str, first: str) -> tuple[str, str]:
    return (re.sub(r"[^A-Z]", "", (last or "").upper()),
            re.sub(r"[^A-Z]", "", (first or "").upper()))


def _split_zuercher_name(name: str) -> Optional[tuple[str, str, str]]:
    """'Adams, Bruce Edward' -> ('ADAMS', 'BRUCE', 'EDWARD').

    Middle is '' when the roster only carries one given name. Previously
    returned a 2-tuple and threw the middle token away; it is now kept so
    `match_cross_county` can require it as corroboration (see module
    docstring, "CROSS-COUNTY NAME-ONLY FANOUT").
    """
    if not name or "," not in name:
        return None
    last, _, rest = name.partition(",")
    toks = rest.strip().split()
    if not toks or not last.strip():
        return None
    middle = toks[1].strip().upper() if len(toks) > 1 else ""
    return last.strip().upper(), toks[0].strip().upper(), middle


async def _fetch_zuercher(subdomain: str) -> list[dict]:
    from curl_cffi.requests import AsyncSession
    url = f"https://{subdomain}.zuercherportal.com/api/portal/inmates/load"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {"name": "", "race": "all", "sex": "all", "cell_block": "all",
            "held_for_agency": "any", "in_custody": now,
            "paging": {"count": 2000, "start": 0},
            "sorting": {"sort_by_column_tag": "name", "sort_descending": False}}
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome") as s:
            r = await s.post(url, json=body, timeout=30)
            recs = (r.json() or {}).get("records") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail.zuercher_fail", subdomain=subdomain, error=str(exc)[:120])
        return []
    for rec in recs:
        parts = _split_zuercher_name(rec.get("name") or "")
        if not parts:
            continue
        last, first, middle = parts
        charges = rec.get("hold_reasons") or rec.get("charges") or ""
        if isinstance(charges, list):
            charges = "; ".join(str(x) for x in charges)[:300]
        out.append({"last": last, "first": first, "middle": middle, "dob": rec.get("dob"),
                    "arrest_date": rec.get("arrest_date"), "charge": str(charges)[:300]})
    return out


async def _fetch_p2c_jqgrid(base: str) -> list[dict]:
    from curl_cffi.requests import AsyncSession
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome") as s:
            await s.get(f"{base}/jailinmates.aspx", timeout=20)  # session cookie
            r = await s.post(f"{base}/jqHandler.ashx?op=s",
                             data={"t": "ii", "_search": "false", "rows": "2000",
                                   "page": "1", "sidx": "disp_name", "sord": "asc"},
                             timeout=30)
            rows = (r.json() or {}).get("rows") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail.p2c_fail", base=base, error=str(exc)[:120])
        return []
    for rw in rows:
        last = (rw.get("lastname") or "").strip().upper()
        first = (rw.get("firstname") or "").strip().upper()
        if not last or not first:
            continue
        out.append({"last": last, "first": first, "dob": rw.get("dob"),
                    "arrest_date": rw.get("disp_arrest_date"),
                    "charge": (rw.get("chrgdesc") or rw.get("disp_charge") or "")[:300]})
    return out


async def _fetch_p2c_centralsquare(target: str) -> list[dict]:
    """Modern CentralSquare P2C (policetocitizen.com) current-inmate roster.

    Handshake: GET an app route (/en/Inmates) so the SPA hands back an
    XSRF-TOKEN cookie, then echo it as the X-XSRF-TOKEN header on the JSON
    search POST to /api/Inmates/<listId>. The endpoint rejects Take>~200 with
    a 400 and never populates TotalCount, so page in blocks of 200 until a
    short page. DOB is redacted on the public feed; Age + ArrestDate survive.
    Compliant: open JSON-XHR + standard anti-forgery echo, no login/CAPTCHA.
    """
    from curl_cffi.requests import AsyncSession
    host, _, list_id = target.partition("|")
    list_id = list_id or "23"
    api = f"{host}/api/Inmates/{list_id}"
    page_size = 200
    out: list[dict] = []
    try:
        # verify=False mirrors the repo's other AsyncSession enrichers
        # (gaston_rod, sc_divorce): it tolerates a TLS-intercepting proxy in the
        # run environment, NOT a cert/WAF defeat on the source itself.
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            # 1) establish the XSRF-TOKEN cookie via an app-route GET
            await s.get(f"{host}/en/Inmates", timeout=25)
            token = s.cookies.get("XSRF-TOKEN")
            if not token:
                log.warning("jail.p2c_cs_no_token", host=host)
                return []
            hdr = {"X-XSRF-TOKEN": token,
                   "Content-Type": "application/json",
                   "Accept": "application/json, text/plain, */*",
                   "Referer": f"{host}/en/Inmates", "Origin": host}
            skip = 0
            while True:
                body = {
                    "FilterOptionsParameters": {
                        "IntersectionSearch": True, "SearchText": "",
                        "Parameters": []},
                    "IncludeCount": True,
                    "PagingOptions": {
                        "SortOptions": [{"Name": "ArrestDate",
                                         "SortDirection": "Descending",
                                         "Sequence": 1}],
                        "Take": page_size, "Skip": skip}}
                r = await s.post(api, headers=hdr, json=body, timeout=60)
                recs = (r.json() or {}).get("Inmates") or []
                if not recs:
                    break
                for rec in recs:
                    last = (rec.get("LastName") or "").strip().upper()
                    first = (rec.get("FirstName") or "").strip().upper()
                    if not last or not first:
                        continue
                    out.append({
                        "last": last, "first": first,
                        "dob": rec.get("DateOfBirth"),  # redacted on this feed
                        "age": rec.get("Age"),
                        "arrest_date": rec.get("ArrestDate"),
                        "charge": (rec.get("PrimaryChargeDescription") or "")[:300]})
                if len(recs) < page_size:
                    break
                skip += page_size
                if skip > 5000:  # safety cap; roster is ~540
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("jail.p2c_cs_fail", host=host, error=str(exc)[:120])
        return []
    return out


# ---- per-name search vendors -------------------------------------------------

_NAME_RE = re.compile(r'name=["\']([^"\']+)["\']')
_VALUE_RE = re.compile(r'value=["\']([^"\']*)["\']')


def _cell_text(cell_html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell_html or "")).replace(
        "&nbsp;", " ").replace("&quot;", '"').strip()


def _split_comma_name(name: str) -> Optional[tuple[str, str, str]]:
    """'Smith, Christopher Michael' -> ('SMITH', 'CHRISTOPHER', 'MICHAEL').

    Middle is '' when only one given name is present. See
    `_split_zuercher_name`'s docstring for why this is now a 3-tuple.
    """
    if not name or "," not in name:
        return None
    last, _, rest = name.partition(",")
    toks = rest.strip().split()
    if not toks or not last.strip():
        return None
    middle = toks[1].strip().upper() if len(toks) > 1 else ""
    return last.strip().upper(), toks[0].strip().upper(), middle


_GVL_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_GVL_ACTION_RE = re.compile(r'action=["\']([^"\']*WEBEVENT[^"\']*)["\']', re.I)


async def _search_lansa(entry: str, last: str, first: str = "") -> list[dict]:
    """Greenville SC LANSA-for-the-Web WEBEVENT inmate search.

    GET the framed entry -> session-scoped WEBEVENT action token + ~36 hidden
    fields. POST them back with ASC_NML (last name) + ASTDRENTST=SEARCH (what the
    page's Search link sets before HandleEvent). Grid is current detainees only:
    Name | Book Date | Race | Sex | Age | Height | Weight. Compliant: replays the
    page's own postback; the Incapsula script present on the page is passive (no
    token solved/defeated).

    We deliberately search by LAST NAME ONLY and filter first name client-side:
    the page's first-name box (ASC_NMF) is an unreliable exact/normalized match
    that returns 0 rows for names that plainly exist (verified: "SMITH, ALEX
    MATTHEW" is in the roster, yet ASC_NMF="ALEX" yields nothing), so echoing it
    would cause false negatives. The grid returns the alphabetical-by-first-name
    page 1 (~15 rows); LANSA's JS-driven WEBEVENT paging does not replay cleanly
    from a stateless POST, so for a very common surname a match beyond page 1 can
    be missed. That only costs RECALL — every row returned is a real current
    detainee (no false positives) — consistent with this module's LOW-confidence
    stack-signal philosophy. `first` is accepted for signature symmetry, unused.
    """
    from curl_cffi.requests import AsyncSession
    from urllib.parse import urlsplit, urlunsplit
    out: list[dict] = []
    if not last:
        return out
    sp = urlsplit(entry)
    origin = urlunsplit((sp.scheme, sp.netloc, "", "", ""))
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(entry, timeout=30,
                            headers={"Referer": origin + "/inmate_search.htm"})
            body = r.text or ""
            am = _GVL_ACTION_RE.search(body)
            if not am:
                log.warning("jail.lansa_no_action", entry=entry)
                return []
            # LANSA renders many inputs (not just type=hidden); pull them all.
            fields: dict = {}
            for im in re.finditer(r"<input[^>]*>", body, re.I):
                tag = im.group(0)
                n = _NAME_RE.search(tag)
                if not n:
                    continue
                v = _VALUE_RE.search(tag)
                fields[n.group(1)] = v.group(1) if v else ""
            fields["ASC_NML"] = last
            fields["ASC_NMF"] = ""              # see docstring: unreliable, skip
            fields["ASTDRENTST"] = "SEARCH"     # what the Search link sets
            action_url = origin + am.group(1)
            pr = await s.post(action_url, data=fields, timeout=45,
                              headers={"Referer": entry,
                                       "Content-Type": "application/x-www-form-urlencoded"})
            rbody = pr.text or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("jail.lansa_fail", entry=entry, error=str(exc)[:120])
        return []
    # Results table only: rows are Name | Book Date | Race | Sex | Age | Ht | Wt.
    # A data row's first cell is "LAST, FIRST ..." and its second a mm/dd/yyyy.
    for rowm in _GVL_ROW_RE.finditer(rbody):
        cells = [_cell_text(c) for c in
                 re.findall(r"<td[^>]*>(.*?)</td>", rowm.group(1), re.S)]
        cells = [c for c in cells if c]
        if len(cells) < 5:
            continue
        parts = _split_comma_name(cells[0])
        if not parts or not re.match(r"\d{1,2}/\d{1,2}/\d{4}$", cells[1]):
            continue
        last_n, first_n, middle_n = parts
        age = cells[4] if len(cells) > 4 and cells[4].isdigit() else None
        out.append({"last": last_n, "first": first_n, "middle": middle_n, "dob": None,
                    "age": age, "arrest_date": cells[1],  # Book Date
                    "race": cells[2] if len(cells) > 2 else "",
                    "sex": cells[3] if len(cells) > 3 else "", "charge": ""})
    return out


async def _search_vendor(vendor: str, target: str, last: str, first: str) -> list[dict]:
    if vendor == "lansa":
        return await _search_lansa(target, last, first)
    return []


async def _load_roster(state: str, county: str, vendor: str, target: str,
                       dry_run: bool = False):
    if vendor == "zuercher":
        recs = await _fetch_zuercher(target)
    elif vendor == "p2c_centralsquare":
        recs = await _fetch_p2c_centralsquare(target)
    elif vendor == "citizen_connect":
        recs = await _fetch_citizen_connect(target)
    elif vendor == "tyler_inmate_inquiry":
        recs = await _fetch_tyler_inmate_inquiry(target)
    else:
        recs = await _fetch_p2c_jqgrid(target)
    index: dict[tuple, dict] = {}
    for rec in recs:
        index.setdefault(_norm_key(rec["last"], rec["first"]), rec)
    if recs:
        # Diff against the sidecar so every record carries whether THIS is the
        # first time we have ever seen this name on this county's roster, plus
        # when. Guarded to never run on an empty fetch (jail_roster_history's
        # own docstring: an empty `recs` is indistinguishable from a failed
        # fetch, so it must never be read as "the roster emptied out").
        # Best-effort: a sidecar write failure must never block a real match.
        #
        # dry_run -> commit=False: still COMPUTE and report accurate is_new /
        # first_detected_at metadata (so a dry run's own printed counts are
        # correct), but never persist the diff. Fixes the 2026-09-29 bug where
        # `run_pending_signal_enrichers.py --dry-run`'s own roster fetch got
        # diffed-and-recorded as "seen" for real, so a genuine real run
        # shortly after found 0 new matches for names its dry run had already
        # consumed -- 590 real jail_booking_new detections lost in one run.
        try:
            con = jail_roster_history.connect()
            try:
                meta = jail_roster_history.diff_and_record(
                    con, state, county, vendor, recs, commit=not dry_run)
            finally:
                con.close()
            for key, rec in index.items():
                m = meta.get(key)
                if m:
                    rec["is_new_booking"] = m["is_new"]
                    rec["first_detected_at"] = m["first_seen_at"]
        except Exception:  # noqa: BLE001
            log.warning("jail_history.persist_failed", county=county, vendor=vendor,
                       traceback=traceback.format_exc())
    log.info("jail.roster", county=county, vendor=vendor, inmates=len(recs))
    return (state, county), index


def _plain_county(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().title()


async def _hydrate_tyler_hits(listings: list[Listing],
                              max_hydrations: int = 100) -> int:
    """Fill in booking date + charges for matched Tyler (Gaston) rows.

    The InmateInquiry grid carries DOB and the in-custody flag but keeps the
    booking date and charge list on each inmate's detail page. Fetching 700 of
    those every run would be rude and slow, so we fetch only the rows that
    actually matched an owner — normally a handful.
    """
    bases = {(s, c): t for s, c, v, t in ROSTERS if v == "tyler_inmate_inquiry"}
    done = 0
    for li in listings:
        if done >= max_hydrations:
            break
        jbk = (li.raw or {}).get("jail_booking") or {}
        detail_id = jbk.get("detail_id")
        base = bases.get((li.state, _plain_county(li)))
        if not detail_id or not base or jbk.get("arrest_date"):
            continue
        detail = await _fetch_tyler_detail(base, detail_id)
        if detail.get("arrest_date"):
            jbk["arrest_date"] = detail["arrest_date"]
        if detail.get("charge"):
            jbk["charge"] = detail["charge"]
        done += 1
        await asyncio.sleep(0.3)  # polite pacing
    if done:
        log.info("jail.tyler_hydrated", count=done)
    return done


def _apply_hit(li: Listing, county: str, first: str, last: str, hit: dict) -> None:
    """Attach the jail_booking detail + reuse the LEGAL incarceration signal."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    raw["jail_booking"] = {
        "county": county, "state": li.state,
        "matched_name": f"{first} {last}",
        "roster_dob": hit.get("dob"), "roster_age": hit.get("age"),
        "arrest_date": hit.get("arrest_date"),
        "charge": hit.get("charge"),
        "release_status": hit.get("release_status") or "in_custody",
        "scheduled_release": hit.get("scheduled_release"),
        # Vendor row id, kept only so _hydrate_tyler_hits can pull the booking
        # date + charges for this one person.
        "detail_id": hit.get("detail_id"),
        "confidence": "name_only_low",
        # Every ROSTERS/SEARCH_ROSTERS vendor is a county sheriff jail system —
        # see module docstring "FACILITY TYPE".
        "facility_type": "jail",
        # jail_roster_history.py sidecar metadata: True the run this name was
        # first ever seen on this county's roster; when the sidecar write
        # failed (best-effort — see _load_roster) both are None rather than a
        # guessed value.
        "is_new_booking": hit.get("is_new_booking"),
        "first_detected_at": hit.get("first_detected_at"),
    }
    raw.setdefault("incarceration", {
        "state": li.state, "source": f"{county} County jail roster",
        "matched_name": f"{first} {last}", "confidence": "name_only_low"})
    li.raw = raw


def _owner_still_supports_match(li: Listing) -> bool:
    """Same staleness check as enrichment_bop_federal._owner_still_supports_match
    and enrichment_incarceration._owner_still_supports_match (2026-10-03 sweep,
    same bug shape), for THIS module's own raw['jail_booking'] match: a county-
    jail hit, once stamped, was never revisited even after the owner on record
    changed -- both `match_rosters` and the per-name SEARCH_ROSTERS lane skip a
    listing the moment raw['jail_booking'] is truthy, forever, so a later
    owner-name refresh (a sale, an estate closing, a parcel_cache correction)
    never gets reconciled against a name-keyed match stamped against whoever
    used to own the parcel.

    Returns True ("leave it alone") when there is no jail_booking tag, or
    nothing to check it against; False only when the CURRENT owner no longer
    supports the matched_name this module stamped."""
    match = li.raw.get("jail_booking") if isinstance(li.raw, dict) else None
    if not isinstance(match, dict):
        return True
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
    """Pre-pass: drop any raw['jail_booking'] match the CURRENT owner no
    longer supports (see _owner_still_supports_match), so match_rosters / the
    per-name search lane below pick the row up again as if never checked.
    Also drops the shared raw['incarceration'] flag, but ONLY when its own
    `source` is a county-jail-roster entry THIS module itself set (the
    "{county} County jail roster" string _apply_hit writes) -- never an
    NC-DAC/SC-DOC match (enrichment_incarceration.py) or a BOP match
    (enrichment_bop_federal.py) sharing the same key; each of those owns
    clearing its own."""
    cleared = 0
    for li in listings:
        if li.state not in ("NC", "SC") or not isinstance(li.raw, dict):
            continue
        if not li.raw.get("jail_booking") or _owner_still_supports_match(li):
            continue
        li.raw.pop("jail_booking", None)
        inc = li.raw.get("incarceration")
        if isinstance(inc, dict) and inc.get("source") not in (DAC_SOURCE, SCDC_SOURCE, BOP_SOURCE):
            li.raw.pop("incarceration", None)
        cleared += 1
    return cleared


def match_rosters(listings: list[Listing], rosters: dict) -> list[Listing]:
    """Flag every listing whose owner is on its county's bulk roster.

    rosters maps (state, county) -> {(last, first): record}, as _load_roster
    builds it. Returns the listings it flagged. Shared by enrich_jail_bookings and
    scripts/backfill_jail_rosters.py so the standalone run cannot drift from the
    pipeline's match rule (name-only, exact last+first, person-owned, one booking
    per lead)."""
    matched: list[Listing] = []
    for li in listings:
        idx = rosters.get((li.state, _plain_county(li)))
        if not idx or (li.raw or {}).get("jail_booking"):
            continue
        parts = _name_parts(_owner_of(li) or "")
        if not parts:
            continue
        hit = idx.get(_norm_key(*parts))
        if not hit:
            continue
        _apply_hit(li, _plain_county(li), parts[1], parts[0], hit)
        matched.append(li)
    return matched


def _owner_name_index(listings: list[Listing]) -> dict[tuple, list[Listing]]:
    """(state, norm_last, norm_first) -> every NC/SC listing with that resolved
    owner, regardless of the listing's own county. Built once per run so
    match_cross_county can look a roster name up against the WHOLE board
    instead of just its own county's leads."""
    idx: dict[tuple, list[Listing]] = {}
    for li in listings:
        if li.state not in ("NC", "SC"):
            continue
        parts = _name_parts(_owner_of(li) or "")
        if not parts:
            continue
        idx.setdefault((li.state, *_norm_key(*parts)), []).append(li)
    return idx


def _cross_county_corroborated(owner: Optional[str], hit: dict) -> bool:
    """True only when the booking's middle name POSITIVELY AGREES with the
    board owner's middle initial — this tier's one corroborating signal.

    Reuses `name_normalize.party_middle_verdict`, this project's existing
    convention for the "common name, thin match" problem (built for the
    SC-divorce party match; also the voter-phone identity gate in
    enrichment_sc_phone.py). `match_cross_county` searches the WHOLE board
    for an exact first+last match with no county bound at all, so it is the
    single highest-fanout tier in this module — see module docstring,
    "CROSS-COUNTY NAME-ONLY FANOUT" — and unlike the divorce/voter-phone
    gates, it has no second corroborating channel (no county match possible
    by construction) if middle name fails, so "unverified" (no middle on one
    side — including every roster vendor that does not carry one, e.g.
    p2c_jqgrid/p2c_centralsquare/citizen_connect/tyler today) is REJECTED
    here, not passed through the way those other gates allow.
    """
    middle = (hit.get("middle") or "").strip()
    if not middle:
        return False
    party = f"{hit.get('first', '')} {middle} {hit.get('last', '')}"
    return party_middle_verdict(owner, [party]) == "agrees"


def match_cross_county(listings: list[Listing], rosters: dict) -> list[Listing]:
    """Flag a listing whose owner turns up on a covered county's roster that is
    NOT the listing's own property county — the ep 069 "fugitive heir" case
    from the Tier B #36 synthesis: a saved search re-fires on a booking nowhere
    near the property.

    Scoped to bookings jail_roster_history says are brand-new to that county
    this run (hit["is_new_booking"]), so a name that happens to sit on two
    counties' rosters permanently does not re-flag on every single run forever
    — it fires once, the run that pairing first appears, exactly the "standing
    re-query" the synthesis asks for.

    REQUIRES middle-name corroboration (`_cross_county_corroborated`) on top
    of the exact first+last match — fixed 2026-10-02 after a bare name-only
    whole-board match fanned one common booked name out to thousands of
    unrelated listings (see module docstring). A candidate pair that fails
    corroboration is counted but never written to the board.

    Writes a SEPARATE key, raw['jail_booking_new'], never raw['jail_booking'] or
    raw['incarceration'] — this must not change an existing same-county match or
    silently inflate distress_score's LEGAL incarceration count; it is a new,
    distinctly-actionable signal on top of what already existed.
    """
    owner_idx = _owner_name_index(listings)
    flagged: list[Listing] = []
    rejected_unverified = 0
    for (state, county), idx in rosters.items():
        for (last, first), hit in idx.items():
            if not hit.get("is_new_booking"):
                continue
            for li in owner_idx.get((state, last, first), ()):
                if _plain_county(li) == county:
                    continue                                  # same-county lane's job
                if (li.raw or {}).get("jail_booking_new"):
                    continue                                  # already flagged this run
                if not _cross_county_corroborated(_owner_of(li), hit):
                    rejected_unverified += 1
                    continue                                  # no/conflicting middle name
                raw = li.raw if isinstance(li.raw, dict) else {}
                raw["jail_booking_new"] = {
                    "county": county, "state": state,
                    "home_county": _plain_county(li),
                    "matched_name": f"{first} {last}",
                    "arrest_date": hit.get("arrest_date"),
                    "charge": hit.get("charge"),
                    "facility_type": "jail",
                    "cross_county": True,
                    "first_detected_at": hit.get("first_detected_at"),
                    # Renamed 2026-10-02 from "name_only_low_cross_county": a
                    # match now requires an agreeing middle name, so the old
                    # tag would misrepresent it as the uncorroborated tier it
                    # no longer is, and would let downstream code conflate
                    # pre-fix and post-fix rows written under the same string.
                    "confidence": "middle_corroborated_cross_county",
                    "middle_verdict": "agrees",
                }
                li.raw = raw
                flagged.append(li)
    if rejected_unverified:
        log.info("jail.cross_county_rejected_unverified", count=rejected_unverified)
    return flagged


async def enrich_jail_bookings(listings: list[Listing],
                               max_searches_per_county: int = 200,
                               dry_run: bool = False) -> dict:
    """Match resolved owner names against covered county jail rosters.

    Two lanes: BULK rosters (fetched once/run + indexed) and PER-NAME SEARCH
    rosters (Greenville), where we run one last-name lookup per in-scope
    owner (paced, capped per county).

    `dry_run` threads through to `_load_roster` -> `jail_roster_history.
    diff_and_record(commit=not dry_run)`: the bulk lane still fetches every
    covered roster and still computes/reports accurate is_new_booking /
    first_detected_at metadata on the listings it matches (so a caller's
    dry-run report is correct), but nothing is persisted to the sidecar. The
    per-name SEARCH_ROSTERS lane never touches jail_roster_history at all, so
    it needs no dry_run handling.

    Starts with a read-only-looking but mutating pre-pass (_clear_stale_matches)
    that drops any jail_booking match the CURRENT owner no longer supports, so
    a sale/estate-closing/parcel_cache correction since the match was stamped
    doesn't leave someone else's county-jail record sitting on the lead
    forever -- see _owner_still_supports_match for the real examples that
    found this.
    """
    stale_cleared = _clear_stale_matches(listings)

    bulk_covered = {(s, c) for s, c, _, _ in ROSTERS}
    search_covered = {(s, c): (v, t) for s, c, v, t in SEARCH_ROSTERS}
    covered = bulk_covered | set(search_covered)

    _county = _plain_county

    if not any((li.state, _county(li)) in covered for li in listings):
        log.info("jail.no_targets", stale_cleared=stale_cleared)
        return {"matched": 0, "stale_cleared": stale_cleared}

    counts = {"matched": 0, "stale_cleared": stale_cleared}

    # ---- lane 1: bulk rosters (fetch each once, index by name) ----
    bulk_needed = [(s, c, v, t) for s, c, v, t in ROSTERS
                   if any((li.state, _county(li)) == (s, c) for li in listings)]
    rosters = dict(await asyncio.gather(
        *[_load_roster(s, c, v, t, dry_run=dry_run)
          for s, c, v, t in bulk_needed])) if bulk_needed else {}
    counts["matched"] += len(match_rosters(listings, rosters))

    # Tyler grids omit booking date + charges; pull them for matched rows only.
    counts["hydrated"] = await _hydrate_tyler_hits(listings)

    # Cross-county re-identification: this run's rosters against every NC/SC
    # listing on the board, not just leads in that roster's own county.
    counts["cross_county"] = len(match_cross_county(listings, rosters))

    # ---- lane 2: per-name search rosters (one lookup per in-scope owner) ----
    for (state, county), (vendor, target) in search_covered.items():
        # De-dupe owner names so we hit the vendor once per distinct surname pair.
        by_name: dict[tuple, list[Listing]] = {}
        for li in listings:
            if (li.state, _county(li)) != (state, county):
                continue
            if (li.raw or {}).get("jail_booking"):
                continue
            parts = _name_parts(_owner_of(li) or "")
            if parts:
                by_name.setdefault(_norm_key(*parts), []).append(li)
        if not by_name:
            continue
        searched = 0
        for _key, lis in by_name.items():
            if searched >= max_searches_per_county:
                break
            parts = _name_parts(_owner_of(lis[0]) or "")
            if not parts:
                continue
            last, first = parts
            recs = await _search_vendor(vendor, target, last, first)
            searched += 1
            index: dict[tuple, dict] = {}
            for rec in recs:
                index.setdefault(_norm_key(rec["last"], rec["first"]), rec)
            hit = index.get(_norm_key(last, first))
            if hit:
                for li in lis:
                    _apply_hit(li, county, first, last, hit)
                    counts["matched"] += 1
            await asyncio.sleep(0.4)  # polite pacing
        log.info("jail.search_roster", county=county, vendor=vendor, searched=searched)

    log.info("jail.done", matched=counts["matched"])
    return counts
