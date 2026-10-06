"""jail_booking, the same-county county-jail tier: is the owner the board matched still on the
county jail roster today, and is the inmate the same person as the owner?

Evolved from docs/validation_2026-10-02/scripts/validate_live.py (FINDINGS.md section 5, the
full population of 322 rows on 2026-10-02: 85.4% still on the roster, 14.6% gone from it, and
12.9% of the middle-checkable current matches a different person with the same first + last
name). Every fetch and every name rule is enrichment_jail_bookings' own, so the verifier and
the pipeline cannot read a roster differently:

  * the roster: enrichment_jail_bookings._load_roster (the ROSTERS vendor fetchers: Zuercher,
    P2C jqGrid, P2C CentralSquare, Citizen Connect, Tyler; the middle-name placeholder clean-up;
    RosterIndex.same_name) with jail_roster_history.assess_roster_health as the health judge;
  * the identity: _owner_of / _name_parts / _owner_still_supports_match for the owner, and
    _roster_candidates + _pick_hit (party_middle_verdict through _hit_middle_verdict) for the
    middle-name verdict, exactly as the run's re-evaluation (_reevaluate_stamp) uses them.

ONE FETCH PER COUNTY PER SWEEP. The rosters are whole-county lists, so the first row of a county
loads it and every later row of that county in the same sweep reads the in-memory copy (keyed by
the sweep's `client`, which the sweep creates once per run). Never a request per row. A county
whose vendor has no bulk roster (Greenville's LANSA is a per-name search) is not queried.

WHICH ROWS (applies). NC/SC rows whose raw['jail_booking'] is this pipeline's own same-county
stamp (enrichment_jail_bookings._is_own_same_county_stamp: confidence name_only_low or
middle_corroborated, a matched_name, the row's own county, never the national.jail_bookings
scraper's inmate-as-lead rows) and that still claim custody (signal_freshness.custody_ended is
False). raw['jail_booking_new'] (the cross-county tier) is not covered.

VERDICTS (core.py's meanings). The roster is searched for the stamp's matched_name, the claim's
subject (the same key the run uses while the owner still yields that name):
  confirmed    on today's roster and the inmate's middle name AGREES with the owner's initial.
  refuted      the matched first + last name is on today's roster but every same-name inmate's
               middle name CONFLICTS with the owner's: a different person, so the match never
               was this owner.
  stale        not on today's roster AND the roster load is healthy AND the stay in this jail was
               under JAIL_LONG_STAY_DAYS (released or bonded out; a longer stay may be a move to
               state prison: unconfirmed, possible_transfer_to_prison). Like confirmed and
               refuted, only while the board's owner still yields the matched name.
  unconfirmed  on the roster but no middle name on one side to compare ("middle_unverifiable");
               the board's current owner no longer yields the matched name, on the roster or
               not ("owner_no_longer_matches": a sale or a resolver correction; the roster can
               answer for the person, not for this property's owner, and the ledger is keyed by
               property; the run's _clear_stale_matches drops that stamp); the roster failed,
               came back empty or was
               judged unhealthy ("roster_unavailable", "roster_unhealthy": never "stale" from
               such a roster); or the county's vendor has no bulk roster
               ("per_name_search_vendor", "no_roster_for_county").

SHARED RULES. The spelling-drift and long-stay rules below live in jail_matching, a neutral pure
module the pipeline's own stamp (enrichment_jail_bookings._reevaluate_stamp) imports too, so the
two cannot read the same roster differently.

SPELLING DRIFT (v2). The exact first + last name lookup missed a person who IS on the roster whose
first name the vendor later respelled by one character (Henderson, 2026-10-06: the stamp's name
and the roster's differed by one inserted letter; the verifier read "absent" and said stale).
When no roster record has the stamp's exact name, a record that agrees on the LAST name, the
BOOKING DATE and (the date of birth when both sides carry one, else the age) with a first name
within edit distance 2 (1 for a name under 5 letters, exact under 3), or one that shares the
first letter and is a prefix of / prefixed by the other (3 or more letters: ROB / ROBERT), is the
same person. Exactly one such record decides (on_roster, the middle-name rule as for an exact
match, name_variant true in the evidence); two are ambiguous and unconfirmed. Nothing else is
loosened: a different last name, booking day, date of birth or age is a different person (a
same-first-name, same-day, same-age inmate with another last name, booking time and charge, met
on the Buncombe roster, stays a different person).

LONG STAYS (v2). A county roster cannot tell a release from a transfer to state prison. When the
stay in this county jail, from the booking date to the last time the pipeline saw the person on
the roster (the stamp's last_confirmed_on_roster; today when the stamp has none), was
JAIL_LONG_STAY_DAYS (60) or more, an absence from a healthy roster is NOT stale (that would take
an incarceration signal away from someone who may be in prison now): unconfirmed, reason
possible_transfer_to_prison.

ROSTER HEALTH. jail_roster_history.assess_roster_health: non-empty, >= HEALTH_MIN_ROSTER names,
>= HEALTH_MIN_RATIO of the median of the county's recent fetch sizes, and no history means NOT
healthy. The verifier keeps its own history file (VERIFY_JAIL_HISTORY_DB, default
data/verification_jail_roster_history.db, gitignored) through _load_roster's `history_path`, so
a sweep never writes the pipeline's sidecar (its is_new_booking memory and its size baseline:
the 2026-09-29 dry-run bug class). Consequence: on a machine's first sweep every roster is
"no_history", absent rows come out unconfirmed and are retried after RETRY_DAYS; from the
second sweep on, absence is judged.

GOVERNS "incarceration:jail", a partial rule (signal_freshness.incarceration_active, called by
distress_score._collect and enrichment_lead_signals._facet_signals): a refuted or stale verdict
ends raw['incarceration'] only when that flag is jail-sourced ("<county> County jail roster" or
a legacy source-less flag). A NC DAC / SC DOC / BOP flag is checked first and always stands, so
the commonest stale case, a person moved from the county jail to state prison, keeps the prison
match scored. The rule is read at scoring time from the row as it is then, not from the row the
sweep saw.

TTL 3 days, retry 1 day: custody changes daily. A stale verdict for someone re-booked inside
the TTL under-counts that row until it expires (the pipeline's own re-evaluation restores the
booking on its next run); a flaky roster cannot erase a decisive verdict inside its TTL (the
ledger's rule).

EVIDENCE: the decision basis only, never a third party's details (the ledger is pushed to a
PUBLIC repo; public_evidence() is the one whitelist, applied to every answer and to the stored
ledger by migrate_ledger()). Every verdict: state, county, vendor, roster host / size / health
(reason, baseline, basis), fetched_at, the incarceration flag's source and whether it is
prison-sourced (whether this verdict can touch the score at all), and `reason` when there is one.
  confirmed    + on_roster, same_name_count, middle_agrees, the owner's and the inmate's middle
               INITIAL, and the booking date (freshness). No name, no charge, no DOB, no age:
               the board's own raw['jail_booking'] already carries the matched name.
  refuted      + on_roster, same_name_count, middle_conflict, the owner's middle initial and the
               conflicting inmates' middle INITIALS. Nothing else about the inmate (someone
               else): no name, charge, booking date, DOB or age.
  stale        + on_roster false. Nothing about anyone.
  unconfirmed  + middle_missing_on / on_roster / same_name_count where they decided it; for
               owner_no_longer_matches only the reason (the roster answer would be about
               someone other than this property's owner).
ROW_SUMMARY_EXCLUDE drops owner_name from the ledger's row summary (scripts/verification_sweep.py
honours it): an owner-changed entry would otherwise name a matched person next to a property
that is not theirs, and the board carries the names anyway.

CASE IDENTITY (IDENTITY = "case", 2026-10-06). The ledger is keyed by the booking (case_identity:
state + county + booking id, or matched name + arrest date, hashed) and the property, not by the
property alone: 91 Anderson court-case rows sit on one city-owned parcel on the 2026-10-05
board, and a property key gave all of them one verdict.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import weakref
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from urllib.parse import urlsplit

from ... import jail_matching as _jm
from ...jail_matching import first_name_variant, spelling_variants, stay_days  # noqa: F401 (re-exported)
from ..core import VerificationResult, iso_z, result, utc_now

SIGNAL = "jail_booking"
VERSION = "v2"         # v2 (2026-10-06): first-name spelling drift; long stays are not stale
TTL_DAYS = 3           # custody changes daily
RETRY_DAYS = 1         # a roster that failed or had no history is retried the next day
SOURCE = "county jail rosters"
GOVERNS = ("incarceration:jail",)
ROW_SUMMARY_EXCLUDE = ("owner_name",)     # see EVIDENCE in the docstring
IDENTITY = "case"      # one verdict per booking and property (case_identity), not per property
#: a stay in the county jail of this many days or more cannot be read as a release when the person
#: is no longer on the roster (a county roster cannot tell a release from a transfer to state
#: prison): the answer is unconfirmed, possible_transfer_to_prison. The number and the rule live in
#: jail_matching (shared with the pipeline's stamp); this is the verifier's name for it.
JAIL_LONG_STAY_DAYS = _jm.JAIL_LONG_STAY_DAYS

_NAME = __name__.rsplit(".", 1)[-1]
_REPO = Path(__file__).resolve().parents[4]
DEFAULT_HISTORY_DB = _REPO / "data" / "verification_jail_roster_history.db"


def history_db() -> Path:
    """The verifier's own roster-size history (never the pipeline's sidecar)."""
    return Path(os.environ.get("VERIFY_JAIL_HISTORY_DB") or DEFAULT_HISTORY_DB)


def _jb():
    """enrichment_jail_bookings, imported on first use (the registry imports every verifier)."""
    from ... import enrichment_jail_bookings
    return enrichment_jail_bookings


# ---------------------------------------------------------------------------
# which rows
# ---------------------------------------------------------------------------

def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def as_listing(row: dict) -> SimpleNamespace:
    """The attributes the jail module's helpers read off a Listing (state, county, raw,
    defendant), for a board dict as board_stream yields it."""
    return SimpleNamespace(state=str(row.get("state") or "").strip().upper(),
                           county=row.get("county"), raw=_raw(row),
                           defendant=row.get("defendant"))


def applies(row: dict) -> bool:
    li = as_listing(row)
    if li.state not in ("NC", "SC"):
        return False
    jbk = li.raw.get("jail_booking")
    if not isinstance(jbk, dict) or not _jb()._is_own_same_county_stamp(li, jbk):
        return False
    from ...signal_freshness import custody_ended
    return not custody_ended(jbk)


def case_identity(row: Any) -> Optional[str]:
    """The booking the row's stamp claims, as a hashed core.case_id ("jail:<16 hex>"): state +
    county + the vendor's booking id (`detail_id`, Tyler) when the stamp has one, else state +
    county + the matched name + the arrest date (307 of the 322 stamps on the 2026-10-05 board
    carry no booking id). Hashed: the ledger is public and a refuted verdict is about someone
    else. A re-booking (a new id or arrest date) is a new case. Works on a board dict and on a
    Listing."""
    from ..core import case_id
    raw = row.get("raw") if isinstance(row, dict) else getattr(row, "raw", None)
    jbk = raw.get("jail_booking") if isinstance(raw, dict) else None
    if not isinstance(jbk, dict) or not jbk.get("matched_name"):
        return None                     # not a matched stamp (e.g. the jail scraper's own rows)
    get = row.get if isinstance(row, dict) else (lambda k: getattr(row, k, None))
    state = str(jbk.get("state") or get("state") or "").strip().upper()
    county = str(jbk.get("county") or "").strip() or \
        re.sub(r"\s+county$", "", str(get("county") or "").strip(), flags=re.I)
    if jbk.get("detail_id"):
        return case_id("jail", state, county, "id", jbk["detail_id"])
    return case_id("jail", state, county, "name", jbk["matched_name"], jbk.get("arrest_date"))


def roster_spec(state: str, county: str) -> Optional[tuple[str, str]]:
    """(vendor, target) of the county's BULK roster, else None."""
    for s, c, v, t in _jb().ROSTERS:
        if (s, c) == (state, county):
            return v, t
    return None


def search_vendor(state: str, county: str) -> Optional[str]:
    for s, c, v, _t in _jb().SEARCH_ROSTERS:
        if (s, c) == (state, county):
            return v
    return None


def roster_host(vendor: str, target: str) -> str:
    if vendor == "zuercher":
        return f"{target}.zuercherportal.com"
    if vendor == "citizen_connect":
        from ...scrapers.national.jail_bookings import CITIZEN_CONNECT_BASE
        return urlsplit(CITIZEN_CONNECT_BASE).hostname or ""
    return urlsplit(target.split("|", 1)[0]).hostname or ""


# ---------------------------------------------------------------------------
# the roster, once per county per sweep
# ---------------------------------------------------------------------------

@dataclass
class Roster:
    state: str
    county: str
    vendor: str
    host: str
    index: Any                          # enrichment_jail_bookings.RosterIndex
    fetched_at: str
    health: dict = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def size(self) -> int:
        return len(self.index)

    @property
    def healthy(self) -> bool:
        return bool(getattr(self.index, "healthy", False)) and self.size > 0

    def evidence(self) -> dict:
        h = self.health or {}
        out = {"roster_host": self.host, "roster_size": self.size,
               "roster_healthy": self.healthy, "roster_health_reason": h.get("reason"),
               "roster_baseline": h.get("baseline"), "roster_health_basis": h.get("basis"),
               "fetched_at": self.fetched_at}
        if self.error:
            out["roster_error"] = self.error
        return out


# client -> {(state, county): Roster | asyncio.Task}. The sweep makes one Fetcher per run, so
# this is a per-run cache; it dies with the client.
_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _count(client: Any, host: str, ok: bool) -> None:
    for attr, hit in (("requests", True), ("errors", not ok)):
        c = getattr(client, attr, None)
        if hit and isinstance(c, Counter):
            c[f"roster:{host}"] += 1


async def _load(client: Any, state: str, county: str, vendor: str, target: str) -> Roster:
    jb = _jb()
    host = roster_host(vendor, target)
    err = None
    try:
        _, idx = await jb._load_roster(state, county, vendor, target, dry_run=False,
                                       history_path=history_db())
    except Exception as exc:  # noqa: BLE001 - _load_roster already catches; belt and braces
        idx, err = jb.RosterIndex(), f"{type(exc).__name__}: {str(exc)[:160]}"
    _count(client, host, ok=len(idx) > 0)
    return Roster(state=state, county=county, vendor=vendor, host=host, index=idx,
                  fetched_at=iso_z(utc_now()), health=dict(getattr(idx, "health", {}) or {}),
                  error=err)


async def roster_for(client: Any, state: str, county: str, vendor: str, target: str) -> Roster:
    """The county's roster for this sweep run: loaded by the first row that needs it, shared by
    every later row (and by concurrent callers) of the same `client`."""
    try:
        per_run = _RUNS.setdefault(client, {})
    except TypeError:                                   # not weak-referenceable: no sharing
        per_run = {}
    key = (state, county)
    entry = per_run.get(key)
    if isinstance(entry, Roster):
        return entry
    loop = asyncio.get_running_loop()
    if not (isinstance(entry, asyncio.Task) and entry.get_loop() is loop):
        entry = loop.create_task(_load(client, state, county, vendor, target))
        per_run[key] = entry

        def _done(t: asyncio.Task, per_run=per_run, key=key) -> None:
            if not t.cancelled() and t.exception() is None:
                per_run[key] = t.result()
        entry.add_done_callback(_done)
    # shield: a row timing out while its county loads must not cancel the load for the rest
    return await asyncio.shield(entry)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_COMMON = ("state", "county", "vendor", "roster_host", "roster_size", "roster_healthy",
           "roster_health_reason", "roster_baseline", "roster_health_basis", "fetched_at",
           "roster_error", "incarceration_source", "incarceration_prison_sourced", "reason",
           "stay_days", "long_stay_days", "name_variant", "first_name_edit_distance",
           "name_variant_basis")


def _initial(m: Any) -> Optional[str]:
    m = "".join(ch for ch in str(m or "").upper() if ch.isalpha())
    return m[0] if m else None


def public_evidence(verdict: str, ev: dict) -> dict:
    """The evidence a verdict may publish (see EVIDENCE in the module docstring): a whitelist,
    so nothing new can leak by being added to the working dict. Idempotent, and it reads both
    the working shape and the pre-2026-10-06 stored shape (`inmate`, `conflicting_middles`,
    `same_name_on_roster`), which is how migrate_ledger() rewrites the stored ledger."""
    out = {k: ev[k] for k in _COMMON if k in ev}
    n = ev.get("same_name_count", ev.get("same_name_on_roster"))
    hit = ev.get("hit") or ev.get("inmate") or {}
    reason = ev.get("reason")
    if verdict == "confirmed":
        out.update(on_roster=True, same_name_count=n, middle_agrees=True,
                   owner_middle_initial=_initial(ev.get("owner_middle_initial")),
                   roster_middle_initial=_initial(hit.get("middle")
                                                  or ev.get("roster_middle_initial")),
                   booking_date=hit.get("arrest_date") or ev.get("booking_date"))
    elif verdict == "refuted":
        mids = ev.get("conflicting_middles") or ev.get("roster_middle_initials") or []
        out.update(on_roster=True, same_name_count=n, middle_conflict=True,
                   owner_middle_initial=_initial(ev.get("owner_middle_initial")),
                   roster_middle_initials=sorted({i for i in map(_initial, mids) if i}))
    elif verdict == "stale":
        out["on_roster"] = False
    elif reason == "middle_unverifiable":
        out.update(on_roster=True, same_name_count=n,
                   middle_missing_on=ev.get("middle_missing_on"))
    elif reason in ("roster_unhealthy", "possible_transfer_to_prison"):
        out["on_roster"] = False
    return {k: v for k, v in out.items() if v is not None}


def _res(verdict: str, evidence: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(verdict, evidence),
                  source=evidence.get("roster_host") or SOURCE, version=VERSION, verifier=_NAME)


def migrate_ledger(led: Any) -> int:
    """Rewrite a loaded jail_booking Ledger in place to the published shape: every entry's
    latest.evidence through public_evidence(), ROW_SUMMARY_EXCLUDE dropped from its row
    summary. No fetch, verdicts and stamps unchanged (history entries carry stamps only).
    Returns the number of entries changed."""
    changed = 0
    for e in led.rows.values():
        before = json.dumps(e, sort_keys=True, default=str)
        lat = e.get("latest")
        if isinstance(lat, dict) and isinstance(lat.get("evidence"), dict):
            lat["evidence"] = public_evidence(str(lat.get("verdict")), lat["evidence"])
        if isinstance(e.get("row"), dict):
            for f in ROW_SUMMARY_EXCLUDE:
                e["row"].pop(f, None)
        changed += json.dumps(e, sort_keys=True, default=str) != before
    return changed


def matched_parts(matched_name: Any) -> Optional[tuple[str, str]]:
    """(last, first) from the stamp's matched_name, which _apply_hit writes as
    f"{first} {last}" (first is one token; a surname may have several: "JOHN VAN DYKE")."""
    toks = str(matched_name or "").split()
    if len(toks) < 2:
        return None
    return " ".join(toks[1:]), toks[0]


def _owner_middle(owner: Optional[str]) -> str:
    from ...name_normalize import owner_last_first_middle
    jb = _jb()
    p = owner_last_first_middle(jb._OWNER_NOISE_RE.sub(" ", str(owner or "")))
    return p[2] if p else ""


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    from ...signal_freshness import is_prison_sourced
    jb = _jb()
    li = as_listing(row)
    jbk = li.raw.get("jail_booking") if isinstance(li.raw.get("jail_booking"), dict) else {}
    inc = li.raw.get("incarceration")
    county = jb._plain_county(li)
    # the working dict; _res() publishes only public_evidence()'s whitelist of it
    ev: dict[str, Any] = {
        "state": li.state, "county": county,
        "incarceration_source": inc.get("source") if isinstance(inc, dict) else None,
        "incarceration_prison_sourced": is_prison_sourced(inc),
    }
    spec = roster_spec(li.state, county)
    if spec is None:
        sv = search_vendor(li.state, county)
        ev["vendor"] = sv
        ev["reason"] = "per_name_search_vendor" if sv else "no_roster_for_county"
        return _res("unconfirmed", ev)
    vendor, target = spec
    ev["vendor"] = vendor
    owner = jb._owner_of(li)
    claimed = matched_parts(jbk.get("matched_name"))
    if claimed is None:
        ev["roster_host"] = roster_host(vendor, target)
        ev["reason"] = "no_matched_name"
        return _res("unconfirmed", ev)
    # the run's own rule: the stamp names the current owner only while _name_parts(owner)
    # still gives the matched name (when it does, the lookup key below is the same either way)
    owner_ok = bool(jb._name_parts(owner or "")) and jb._owner_still_supports_match(li)

    roster = await roster_for(client, li.state, county, vendor, target)
    ev.update(roster.evidence())
    if roster.size == 0:
        ev["reason"] = "roster_unavailable"
        return _res("unconfirmed", ev)

    candidates = jb._roster_candidates(roster.index, jb._norm_key(*claimed))
    variant: Optional[dict] = None
    if not candidates:
        found = spelling_variants(roster.index, jbk, claimed)
        if len(found) > 1:
            ev["same_name_count"] = len(found)
            ev["on_roster"] = True
            ev["reason"] = "ambiguous_name_variant"
            return _res("unconfirmed", ev)
        if found:
            variant = found[0]
            # the middle-name rule reads the roster's first name against the owner's; give it the
            # stamp's own spelling so only the middle name is judged
            candidates = [_jm.variant_candidate(variant, claimed)]
            ev.update(name_variant=True, first_name_edit_distance=variant["distance"],
                      name_variant_basis=variant["basis"])
    ev["same_name_count"] = len(candidates)
    if not owner_ok:
        # The board's owner is no longer the matched person (a sale, a resolver correction;
        # on the 2026-10-06 board, 91 Anderson court-case rows whose address resolved to one
        # city-owned parcel). The roster can say whether the matched PERSON is in custody,
        # not whether this property's owner is. So never decisive, and the roster answer is
        # NOT published (it would be about someone other than this property's owner). The
        # run's _clear_stale_matches drops such a stamp on its next pass. (Since the ledger
        # became case-scoped, IDENTITY, those 91 rows are 91 entries, not one.)
        ev["on_roster"] = bool(candidates)
        ev["reason"] = "owner_no_longer_matches"
        return _res("unconfirmed", ev)
    hit, verdict = jb._pick_hit(owner, candidates)
    if hit is not None:
        ev["on_roster"] = True
        ev["owner_middle_initial"] = _owner_middle(owner) or None
        ev["hit"] = hit                     # internal only: public_evidence() keeps initials/date
        if verdict == "agrees":
            return _res("confirmed", ev)
        if verdict == "conflict":
            ev["conflicting_middles"] = [jb._clean_middle(c.get("middle")) for c in candidates]
            return _res("refuted", ev)
        ev["reason"] = "middle_unverifiable"
        ev["middle_missing_on"] = ("roster" if not jb._clean_middle(hit.get("middle"))
                                   else "owner" if not ev["owner_middle_initial"]
                                   else "neither_positional_mismatch")
        return _res("unconfirmed", ev)
    ev["on_roster"] = False
    if roster.healthy:
        days = _jm.long_stay(jbk, today or date.today())
        if days is not None:
            ev.update(stay_days=days, long_stay_days=JAIL_LONG_STAY_DAYS,
                      reason=_jm.POSSIBLE_TRANSFER)
            return _res("unconfirmed", ev)
        return _res("stale", ev)
    ev["reason"] = "roster_unhealthy"
    return _res("unconfirmed", ev)
