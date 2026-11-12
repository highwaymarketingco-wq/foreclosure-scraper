"""NC SOS registered-agent hand-off: the Mac looks entities up, the VM applies them.

WHY (2026-10-05). The daily SOS lookup (scripts/sos_agent_refresh.py, launchd
`com.highway.foreclosure.sosagent`, 14:00 ET on the Mac) worked -- 17 to 27 entities resolved
with a contact every day -- and then failed at the save step every day with BoardLoadTooLarge
(patch_existing_rows refuses a 2,652 MB board over its 2,300 MB ceiling). Nothing cached the
finds, so about 20 real LLC contacts a day were thrown away from late September on, and the
board stayed at 344 rows with `sos_agent`. The Mac cannot write the board any more; the Oracle
VM is the single board writer.

So the work is split the same way as the stealth scrapers (national.stealth_handoff):

  Mac  scripts/sos_agent_refresh.py streams the board read-only (board_stream), picks targets
       with the same selection logic as before, looks them up (stealth session, unchanged), and
       merges every answer into the CUMULATIVE ledger docs/handoff/sos_agent_results.json,
       which it commits and pushes on its own (nothing else in that commit).
  VM   main.py calls apply_sos_agent_handoff() during the nightly run: no network, it reads
       the ledger and attaches raw['sos_agent'] to every NC row owned by a resolved entity
       through enrichment_sos_agent.propagate_profiles(), the module's own matching and
       propagation.

THE LEDGER (docs/handoff/sos_agent_results.json, schema 1). One JSON object; `entities` is keyed
by enrichment_sos_agent.entity_key() (case/punctuation/spacing-insensitive) and written one
entity per line, sorted, so a day's commit diffs as a few added lines:

    {"schema": 1, "kind": "sos_agent_results", "generated_at": <UTC ISO>, "host": ...,
     "counts": {"entities", "resolved", "miss", "error"}, "last_run": {...},
     "entities": {
       "acme holdings llc": {
         "entity": "ACME HOLDINGS LLC",     # the spelling actually searched / seeded
         "status": "resolved",             # resolved | ambiguous | miss | mismatch | error
         "last_attempt": "resolved",       # outcome of the most recent lookup
         "checked_at": "2026-10-05",       # date of the most recent lookup
         "first_checked_at": "2026-10-05",
         "checks": 1,
         "source": "lookup",               # or "board_seed" (already on the board)
         "profile": {...}                  # resolved only: EXACTLY what goes in raw['sos_agent']
       }, ...}}

Entries are never dropped, and a lookup never downgrades a resolved entry. RECHECK (mirrors the
codebase's answered-miss convention, e.g. BOP_RECHECK_DAYS / INCARCERATION_RECHECK_DAYS = 30,
and the module's own "a resolved lead is never re-checked"): resolved -> never again; an
answered miss or an ambiguous answer -> after SOS_AGENT_RECHECK_DAYS (30); a lookup that got
no answer (timeout, block page) -> after SOS_AGENT_ERROR_RECHECK_DAYS (3); a mismatch -> at
the next run, ahead of every other target.

STATUSES (2026-10-05, result-selection fix; rules in enrichment_sos_agent's docstring):
  resolved   a profile select_result() chose, or an older profile that passes
             profile_confirmed(); the only status the VM applies.
  ambiguous  the search answered with candidates but none is confidently this entity
             (`ambiguity`: reason, candidate count, same-name count, the first few
             candidates). Never applied.
  miss       the search answered with no candidates at all.
  mismatch   a profile that WAS resolved and fails profile_confirmed() under the new rule
             (`mismatch`: reason, date, the legal name; the profile moves to
             `rejected_profile`, its SOSID into `rejected_sosids`). Never applied; re-queried
             first thing at the next run. recheck_resolved() does this, on the Mac, every run.
  error      no answer (timeout, block page, unreadable page).
`rejected_sosids` stays on the entry after a re-query resolves it, so the VM can still take
the rejected profile off rows that carry it (apply_sos_agent_handoff, clear step).

THE PROFILE SHAPE is the module's: _parse_profile() + profile_url + match_count (+ match_rule and
exact_matches on a profile chosen by select_result()), stamped with
resolved_for_entity/resolved_at exactly as enrich_with_sos_agent() stamps a fresh resolution
(2026-10-03). Profiles seeded from rows already on the board are copied as they are, legacy
ones without the stamps included -- nothing is back-filled or invented.

BACK-OFF (Mac, local state data/sos_agent_backoff.json, never committed): the daily cap starts
at SOS_AGENT_MAX_CHECK (150). If the breaker trips, the session fails outright, or more than
half the attempted lookups got no answer, the next run uses half the cap (floor
SOS_AGENT_MIN_CHECK, 40). After a clean run (no breaker, <=10% no-answers, not cut short by
the time budget) the cap steps up by SOS_AGENT_CAP_STEP (25) toward the max. Anything in
between holds. Every run logs the cap it used and why.
"""
from __future__ import annotations

import copy
import json
import os
import re
import socket
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

from .enrichment_sos_agent import (
    _clean_entity, _entity_of, clean_contact, entity_key, is_active_status, names_match,
    propagate_profiles, sos_core_key,
)

log = structlog.get_logger()

SCHEMA = 1
KIND = "sos_agent_results"
REPO = Path(__file__).resolve().parents[2]
HANDOFF_FILE = REPO / "docs" / "handoff" / "sos_agent_results.json"
BACKOFF_FILE = REPO / "data" / "sos_agent_backoff.json"

# Best answer known. A lookup outcome replaces the status when it ranks higher; between the
# two answered non-resolutions (miss, ambiguous) the latest one wins. "mismatch" is not a lookup
# outcome: recheck_resolved() sets it, and any answer replaces it (a no-answer does not).
_RANK = {"resolved": 3, "ambiguous": 2, "miss": 2, "mismatch": 1, "error": 0}
_OUTCOMES = ("resolved", "ambiguous", "miss", "error")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def handoff_path() -> Path:
    return Path(os.environ.get("SOS_AGENT_HANDOFF_FILE") or HANDOFF_FILE)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# ledger: load / save / merge
# ---------------------------------------------------------------------------

class LedgerUnreadable(RuntimeError):
    """The ledger exists but is not a valid ledger. The Mac refuses to overwrite it (that
    would lose every entry); the VM logs it and carries on."""


def empty_ledger() -> dict:
    return {"schema": SCHEMA, "kind": KIND, "entities": {}}


def load_ledger(path: Optional[Path] = None) -> dict:
    """The ledger at `path`, or an empty one when the file does not exist yet. Raises
    LedgerUnreadable for a file that exists but cannot be parsed as a ledger."""
    p = Path(path) if path is not None else handoff_path()
    if not p.exists():
        return empty_ledger()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise LedgerUnreadable(f"{p}: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entities"), dict):
        raise LedgerUnreadable(f"{p}: not a {KIND} ledger (no 'entities' object)")
    return data


def ledger_counts(entities: dict) -> dict:
    c = {"entities": len(entities), "resolved": 0, "miss": 0, "error": 0, "ambiguous": 0,
         "mismatch": 0}
    for e in entities.values():
        st = e.get("status")
        if st in c:
            c[st] += 1
    return c


def save_ledger(ledger: dict, path: Optional[Path] = None, *, host: Optional[str] = None,
                now: Optional[datetime] = None) -> Path:
    """Write atomically (tmp + rename), one entity per line, keys sorted."""
    p = Path(path) if path is not None else handoff_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    entities = ledger.get("entities") or {}
    head = {
        "schema": SCHEMA,
        "kind": KIND,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "host": host or socket.gethostname(),
        "counts": ledger_counts(entities),
        "last_run": ledger.get("last_run") or {},
    }
    lines = ["{"]
    for k, v in head.items():
        lines.append(f"{json.dumps(k)}: {json.dumps(v, sort_keys=True, default=str)},")
    lines.append('"entities": {')
    keys = sorted(entities)
    for i, k in enumerate(keys):
        sep = "," if i < len(keys) - 1 else ""
        lines.append(f"{json.dumps(k)}: "
                     f"{json.dumps(entities[k], sort_keys=True, separators=(',', ':'), default=str)}{sep}")
    lines.append("}")
    lines.append("}")
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    ledger["generated_at"] = head["generated_at"]
    ledger["counts"] = head["counts"]
    return p


def record_result(entities: dict, name: str, outcome: str, profile: Optional[dict] = None,
                  *, today: Optional[str] = None, source: str = "lookup",
                  detail: Optional[dict] = None) -> dict:
    """Merge ONE answer for `name` into `entities` without ever losing what is known.

    outcome: "resolved" (needs a profile with a sosid), "ambiguous" (answered with candidates,
    none confidently this entity; `detail` is select_result()'s detail, kept as `ambiguity`),
    "miss" (answered, no such entity) or "error" (no answer). The entry's `status` is the best
    answer recorded (resolved > ambiguous/miss > mismatch > error; see _RANK) and a resolved
    profile is never replaced by a later answer; `last_attempt`/`checked_at` always describe
    the latest lookup (which drives the recheck).
    """
    if outcome not in _OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    if outcome == "resolved" and not (isinstance(profile, dict) and profile.get("sosid")):
        raise ValueError("a resolved outcome needs a profile with a sosid")
    key = entity_key(name)
    if not key:
        raise ValueError(f"empty entity key for {name!r}")
    day = today or _today()
    cur = entities.get(key)
    if cur is None:
        cur = {"entity": name, "status": outcome, "first_checked_at": day, "checks": 0,
               "source": source}
        entities[key] = cur
    cur["checks"] = int(cur.get("checks") or 0) + 1
    cur["checked_at"] = day
    cur["last_attempt"] = outcome
    rank, have = _RANK[outcome], _RANK.get(cur.get("status"), -1)
    if rank > have or (rank == have and outcome in ("miss", "ambiguous")):
        cur["status"] = outcome
    if outcome == "ambiguous" and cur["status"] == "ambiguous":
        cur["ambiguity"] = copy.deepcopy(detail or {})
    elif cur["status"] in ("resolved", "miss"):
        cur.pop("ambiguity", None)
    if outcome == "resolved" and not (isinstance(cur.get("profile"), dict)
                                      and cur["profile"].get("sosid")):
        cur["profile"] = copy.deepcopy(profile)
        cur["entity"] = name
        cur["source"] = source
    return cur


def merge_ledgers(base: dict, other: dict) -> dict:
    """Union of two ledgers' entities (in place into `base`), entry by entry: the better
    status wins, a resolved profile is kept, the later check date and the larger check count
    are kept. Used when the file on disk and an in-memory ledger both carry entries."""
    be = base.setdefault("entities", {})
    for k, o in (other.get("entities") or {}).items():
        b = be.get(k)
        if b is None:
            be[k] = copy.deepcopy(o)
            continue
        rejected = sorted(set(b.get("rejected_sosids") or []) | set(o.get("rejected_sosids") or []))
        o_prof = o.get("profile") if isinstance(o.get("profile"), dict) else None
        # a profile one side already rejected never wins, unless a re-query under the new rule
        # chose that same entity again (match_rule stamped)
        o_rejected = bool(o_prof) and str(o_prof.get("sosid")) in rejected \
            and not o_prof.get("match_rule")
        o_rank = _RANK.get(o.get("status"), -1)
        if o.get("status") == "resolved" and o_rejected:
            o_rank = _RANK["mismatch"]
        if o_rank > _RANK.get(b.get("status"), -1):
            for f in ("status", "entity", "source", "ambiguity", "mismatch"):
                if f in o:
                    b[f] = copy.deepcopy(o[f])
        if rejected:
            b["rejected_sosids"] = rejected
        if "rejected_profile" not in b and isinstance(o.get("rejected_profile"), dict):
            b["rejected_profile"] = copy.deepcopy(o["rejected_profile"])
        if not (isinstance(b.get("profile"), dict) and b["profile"].get("sosid")) \
                and o_prof and o_prof.get("sosid") and not o_rejected:
            b["profile"] = copy.deepcopy(o["profile"])
        if str(o.get("checked_at") or "") > str(b.get("checked_at") or ""):
            b["checked_at"] = o.get("checked_at")
            b["last_attempt"] = o.get("last_attempt", b.get("last_attempt"))
        firsts = [x for x in (b.get("first_checked_at"), o.get("first_checked_at")) if x]
        if firsts:
            b["first_checked_at"] = min(firsts)
        b["checks"] = max(int(b.get("checks") or 0), int(o.get("checks") or 0))
    return base


def is_due(entry: Optional[dict], today: Optional[str] = None) -> bool:
    """Should this entity be looked up (again) today?"""
    if not entry:
        return True
    if entry.get("status") == "resolved":
        return False
    day = date.fromisoformat(today or _today())
    try:
        last = date.fromisoformat(str(entry.get("checked_at") or "")[:10])
    except ValueError:
        return True
    if entry.get("status") == "mismatch" and entry.get("last_attempt") != "error":
        return True       # the profile it had was rejected: re-query at the very next run
    if entry.get("last_attempt", entry.get("status")) == "error":
        wait = _env_float("SOS_AGENT_ERROR_RECHECK_DAYS", 3)
    else:
        wait = _env_float("SOS_AGENT_RECHECK_DAYS", 30)
    return (day - last) >= timedelta(days=wait)


def profile_confirmed(searched: Optional[str], prof: Optional[dict]) -> tuple[bool, str]:
    """Would the 2026-10-05 result-selection rule stand behind this profile for `searched`?
    (True, "") or (False, reason):
      legal_name_differs   the profile's Legal name is not the searched entity
                           (enrichment_sos_agent.names_match(): same core name, no
                           conflicting LLC/corporation/partnership type);
      inactive_first_hit   chosen by the old first-hit rule from a search with several
                           candidates, and not active: an active entity of the same name may
                           have been passed over (live 2026-10-05: "Asheville West, LLC" is on
                           the board as the Dissolved one of two same-name entities).
    A profile select_result() chose (match_rule set), one from a search with a single
    candidate, or an active one, is confirmed once the name matches."""
    if not isinstance(prof, dict) or not prof.get("sosid"):
        return False, "no_profile"
    if not names_match(searched, prof.get("legal_name")):
        return False, "legal_name_differs"
    if prof.get("match_rule"):
        return True, ""
    mc = prof.get("match_count")
    if not isinstance(mc, int) or mc <= 1 or is_active_status(prof.get("status")):
        return True, ""
    return False, "inactive_first_hit"


def _entry_name(key: str, entry: dict) -> str:
    return entry.get("entity") or key


def resolved_profiles(ledger: dict) -> dict[str, dict]:
    """entity_key -> profile, for every resolved entry with a usable profile that passes
    profile_confirmed() (so even a ledger the Mac has not re-checked never puts a rejected
    profile on a row)."""
    out = {}
    for k, e in (ledger.get("entities") or {}).items():
        prof = e.get("profile")
        if e.get("status") == "resolved" and isinstance(prof, dict) and prof.get("sosid") \
                and profile_confirmed(_entry_name(k, e), prof)[0]:
            out[k] = prof
    return out


def recheck_resolved(entities: dict, today: Optional[str] = None) -> dict:
    """Re-check every resolved entry against the current rules, in place:
      * a profile that fails profile_confirmed() -> status "mismatch": the profile moves to
        `rejected_profile`, its SOSID joins `rejected_sosids`, `mismatch` records why and
        when. The VM stops applying it and clears it from the rows that carry it; the next
        Mac run re-queries the entity first.
      * a confirmed profile gets clean_contact() (placeholder agent/contact dropped, a
        commercial agent service flagged and never the best contact).
    Idempotent. Returns {"mismatch": [keys], "by_reason": {reason: n}, "contacts_cleaned":
    [keys]}."""
    day = today or _today()
    out: dict[str, Any] = {"mismatch": [], "by_reason": {}, "contacts_cleaned": []}
    for k in sorted(entities):
        e = entities[k]
        if e.get("status") != "resolved":
            continue
        prof = e.get("profile")
        ok, why = profile_confirmed(_entry_name(k, e), prof)
        if not ok:
            e["status"] = "mismatch"
            e["mismatch"] = {"reason": why, "at": day, "legal_name": (prof or {}).get("legal_name"),
                             "sosid": (prof or {}).get("sosid"),
                             "match_count": (prof or {}).get("match_count")}
            if isinstance(prof, dict):
                e["rejected_profile"] = prof
                if prof.get("sosid"):
                    e["rejected_sosids"] = sorted(set(e.get("rejected_sosids") or [])
                                                  | {prof["sosid"]})
            e.pop("profile", None)
            out["mismatch"].append(k)
            out["by_reason"][why] = out["by_reason"].get(why, 0) + 1
        elif clean_contact(prof):
            out["contacts_cleaned"].append(k)
    return out


def register_board_profile_mismatch(entities: dict, profile: Any, current_entity: Optional[str],
                                    today: Optional[str] = None) -> Optional[str]:
    """The board-row side of recheck_resolved(). A profile on a board row was looked up for
    its resolved_for_entity, or (an older profile with no stamp) evidently for the row's own
    entity when that has the same core name as the profile's Legal name ("J AND M FAMILY HOMES
    LLC" carrying "J & M Family Homes, Inc."). When profile_confirmed() rejects it for that
    entity, the SOSID is recorded as rejected under that entity's key (a new "mismatch" entry,
    source "board_check", when the ledger has none), so the VM clears it from those rows and
    the Mac re-queries the entity. A row whose owner is now a different entity is not
    touched (docs/HANDOFF.md item 57). Returns the entity key it registered, else None;
    idempotent."""
    if not isinstance(profile, dict) or not profile.get("sosid"):
        return None
    legal = profile.get("legal_name")
    searched = profile.get("resolved_for_entity")
    if not searched and current_entity and legal \
            and sos_core_key(current_entity) == sos_core_key(legal):
        searched = current_entity
    if not searched:
        return None
    ok, why = profile_confirmed(searched, profile)
    k = entity_key(searched)
    if ok or not k:
        return None
    sid = str(profile["sosid"])
    e = entities.get(k)
    if e is not None:
        if e.get("status") == "resolved" and str((e.get("profile") or {}).get("sosid")) == sid:
            return None       # the ledger re-confirmed this very entity under the rule
        if sid in set(e.get("rejected_sosids") or []):
            return None
    day = today or _today()
    if e is None:
        e = {"entity": searched, "status": "mismatch", "source": "board_check", "checks": 0,
             "first_checked_at": day}
        entities[k] = e
    e["rejected_sosids"] = sorted(set(e.get("rejected_sosids") or []) | {sid})
    if e.get("status") not in ("resolved", "ambiguous", "miss"):
        e["status"] = "mismatch"
        e["mismatch"] = {"reason": why, "at": day, "legal_name": legal, "sosid": sid,
                         "match_count": profile.get("match_count"), "found_on": "board_row"}
        e.setdefault("rejected_profile", copy.deepcopy(profile))
    return k


def rejected_sosids_by_key(ledger: dict) -> dict[str, set[str]]:
    """SOSID -> the entity keys it is known to be WRONG for: every entry's rejected_sosids,
    plus the profile of a resolved entry that fails profile_confirmed() (the VM's own check,
    for a ledger the Mac has not re-checked), minus the entry's current confirmed profile."""
    out: dict[str, set[str]] = {}
    for k, e in (ledger.get("entities") or {}).items():
        sids = set(e.get("rejected_sosids") or [])
        prof = e.get("profile") if isinstance(e.get("profile"), dict) else None
        if prof and prof.get("sosid"):
            if e.get("status") == "resolved" and profile_confirmed(_entry_name(k, e), prof)[0]:
                sids.discard(prof["sosid"])
            else:
                sids.add(prof["sosid"])
        for sid in sids:
            out.setdefault(str(sid), set()).add(k)
    return out


def row_profile_rejected(prof: Any, current_entity: Optional[str],
                         rejected: dict[str, set[str]]) -> bool:
    """Does this row carry a profile the ledger rejected for the entity it was attached for?
    That entity is the profile's resolved_for_entity (stamped since 2026-10-03), or for an
    older profile the row's current entity. A profile on a row whose owner has since changed
    to someone else is NOT this check's business (docs/HANDOFF.md item 57)."""
    if not isinstance(prof, dict) or not prof.get("sosid") or not rejected:
        return False
    keys = rejected.get(str(prof["sosid"]))
    if not keys:
        return False
    who = prof.get("resolved_for_entity") or current_entity
    return bool(who) and entity_key(who) in keys


# ---------------------------------------------------------------------------
# seeding from profiles already on the board
# ---------------------------------------------------------------------------

def seed_names_for_board_profile(profile: dict, current_entity: Optional[str]) -> list[str]:
    """The entity names a profile ALREADY ON THE BOARD can be filed under in the ledger.

    Docs/HANDOFF.md item 57 measured at least 174 of the 344 board profiles as no longer
    belonging to the row's CURRENT owner (the owner changed after the lookup), so a profile is
    NOT simply filed under the row's current owner -- that would spread one LLC's agent to
    every row of a different owner. Instead:
      * resolved_for_entity (stamped since 2026-10-03) names the entity it was looked up for;
      * otherwise the registry's own legal_name names the entity it IS;
      * the row's current entity is added too, but only when it is the same entity as the
        legal name (enrichment_sos_agent.names_match(), 2026-10-05).
    Every name must pass profile_confirmed() (2026-10-05): a profile resolved for a different
    entity, or an unconfirmed first hit, is never filed, so a wrong profile still sitting on
    board rows cannot re-seed an entry recheck_resolved() rejected.
    """
    if not isinstance(profile, dict) or not profile.get("sosid"):
        return []
    names: list[str] = []
    rfe = profile.get("resolved_for_entity")
    legal = profile.get("legal_name")
    if rfe:
        names.append(rfe)
    elif legal:
        names.append(legal)
    if current_entity and legal and not rfe and names_match(current_entity, legal):
        names.append(current_entity)
    names = [n for n in names if profile_confirmed(n, profile)[0]]
    seen, out = set(), []
    for n in names:
        k = entity_key(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def seed_from_board_profile(entities: dict, profile: dict, current_entity: Optional[str],
                            *, today: Optional[str] = None) -> int:
    """File a board profile under its seed names unless the ledger already has them
    resolved. Returns how many new resolved entries this created/upgraded."""
    added = 0
    for name in seed_names_for_board_profile(profile, current_entity):
        cur = entities.get(entity_key(name))
        if cur and cur.get("status") == "resolved":
            continue
        if cur and str(profile.get("sosid")) in set(cur.get("rejected_sosids") or []):
            continue      # the ledger already rejected this exact profile for this entity
        day = (str(profile.get("resolved_at") or "")[:10]) or (today or _today())
        e = record_result(entities, name, "resolved", profile, today=day, source="board_seed")
        e["checks"] = max(0, int(e.get("checks") or 1) - 1)   # a seed is not a lookup
        added += 1
    return added


# ---------------------------------------------------------------------------
# adaptive daily cap
# ---------------------------------------------------------------------------

def cap_limits() -> tuple[int, int, int]:
    """(max, min, step) from the environment; min never above max."""
    mx = max(1, _env_int("SOS_AGENT_MAX_CHECK", 150))
    mn = max(1, min(_env_int("SOS_AGENT_MIN_CHECK", 40), mx))
    step = max(1, _env_int("SOS_AGENT_CAP_STEP", 25))
    return mx, mn, step


def load_backoff(path: Optional[Path] = None) -> dict:
    p = Path(path) if path is not None else BACKOFF_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - missing or unreadable state = start fresh
        return {}


def save_backoff(state: dict, path: Optional[Path] = None) -> None:
    p = Path(path) if path is not None else BACKOFF_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, p)


def choose_cap(state: dict, limits: Optional[tuple[int, int, int]] = None) -> tuple[int, str]:
    """The cap for THIS run, and why."""
    mx, mn, _ = limits or cap_limits()
    if not state or state.get("cap") is None:
        return mx, f"no back-off state yet: the max ({mx})"
    try:
        stored = int(state["cap"])
    except (TypeError, ValueError):
        return mx, f"unreadable back-off state: the max ({mx})"
    cap = max(mn, min(mx, stored))
    why = state.get("reason") or "carried from the last run"
    if cap != stored:
        why += f" (stored {stored}, clamped to {mn}..{mx})"
    return cap, why


def next_cap(cap_used: int, outcome: dict, targets: int,
             limits: Optional[tuple[int, int, int]] = None) -> tuple[int, str, str]:
    """(next cap, verdict, reason) after a run that used `cap_used` with this `outcome`
    (enrichment_sos_agent._batch_lookup's outcome dict). verdict: back_off | step_up | hold."""
    mx, mn, step = limits or cap_limits()
    cap_used = max(mn, min(mx, int(cap_used)))
    if targets <= 0:
        return cap_used, "hold", "no targets this run"
    attempted = int(outcome.get("attempted") or 0)
    errors = len(outcome.get("errors") or [])
    err_rate = (errors / attempted) if attempted else 1.0
    if outcome.get("breaker_tripped"):
        why = f"breaker tripped ({errors} no-answer lookups of {attempted})"
    elif outcome.get("session_failed") or attempted == 0:
        why = "the stealth session failed: nothing was looked up" + (
            f" ({outcome.get('error')})" if outcome.get("error") else "")
    elif err_rate > 0.5:
        why = f"most lookups got no answer ({errors}/{attempted})"
    else:
        why = ""
    if why:
        nxt = max(mn, cap_used // 2)
        return nxt, "back_off", f"{why}: half the cap, {cap_used} -> {nxt} (floor {mn})"
    if err_rate <= 0.10 and not outcome.get("deadline_hit"):
        nxt = min(mx, cap_used + step)
        if nxt == cap_used:
            return nxt, "hold", f"clean run ({errors}/{attempted} no-answers), already at the max {mx}"
        return nxt, "step_up", (f"clean run ({errors}/{attempted} no-answers): "
                                f"step up {cap_used} -> {nxt} (max {mx})")
    if outcome.get("deadline_hit"):
        return cap_used, "hold", f"time budget ran out after {attempted} lookups: hold at {cap_used}"
    return cap_used, "hold", f"{errors}/{attempted} lookups got no answer: hold at {cap_used}"


# ---------------------------------------------------------------------------
# VM side: apply the hand-off during the pipeline run (no network)
# ---------------------------------------------------------------------------

def profile_bound_to_row(prof: Any, li: Any) -> bool:
    """Whether a row's raw['sos_agent'] profile is about one of the row's own entities: its legal
    name matches (names_match) the owner, the defendant or the county GIS owner (each reduced by
    _clean_entity), or the entity it was stamped for (resolved_for_entity) is one of them. A
    profile with no legal name has nothing to judge and is kept."""
    if not isinstance(prof, dict):
        return True
    legal = prof.get("legal_name")
    if not legal:
        return True
    raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
    gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
    ents = [e for e in (_clean_entity(str(n or "")) for n in
                        (getattr(li, "owner_name", None), getattr(li, "defendant", None), gis.get("owner")))
            if e]
    if any(names_match(e, legal) for e in ents):
        return True
    rfe = prof.get("resolved_for_entity")
    return bool(rfe) and any(sos_core_key(rfe) == sos_core_key(e) for e in ents)


_GOVERNMENT_RE = re.compile(
    r"\b(COUNTY|CITY OF|TOWN OF|VILLAGE OF|STATE OF|BOARD OF EDUCATION|BOARD OF COMMISSIONERS|"
    r"ABC BOARD|HOUSING AUTHORITY|REDEVELOPMENT|UNITED STATES|USA|DEPARTMENT OF|DEPT OF|"
    r"SCHOOL DISTRICT|PUBLIC SCHOOLS|NORTH CAROLINA|SOUTH CAROLINA)\b", re.I)


def government_owned(li: Any) -> bool:
    """The row's owner of record (owner_name, else the county GIS owner) reads as a government
    body and no part of it is a registrable business."""
    raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
    gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
    owner = getattr(li, "owner_name", None) or gis.get("owner") or ""
    return bool(owner) and bool(_GOVERNMENT_RE.search(str(owner))) and _clean_entity(str(owner)) is None


def apply_sos_agent_handoff(listings: Iterable, path: Optional[Path] = None,
                            now: Optional[datetime] = None) -> dict:
    """Attach raw['sos_agent'] from the Mac's ledger to every NC row owned by a resolved
    entity that has no profile yet. Never raises: a missing, stale or unreadable file is
    logged and the run carries on (a stale file is still applied -- a registered agent does
    not go bad in days, and stale contacts beat none, same as national.stealth_handoff).
    SOS_AGENT_HANDOFF_APPLY=0 turns the step off.

    Before attaching (2026-10-05, result-selection fix), two passes over rows that already
    carry a profile:
      cleared   a profile the ledger rejected for the entity it was attached for
                (rejected_sosids_by_key() + row_profile_rejected(): e.g. the Jacksonville
                church's profile on a Buncombe "COVENANT PRESBYTERIAN CHURCH" row) is removed,
                so the row can take the entity's confirmed profile below, or none;
      cleaned   clean_contact() on the profile left in place ("Not Listed" contact dropped,
                a commercial agent service flagged and never the best contact);
      unbound   (audit 2026-10-09, additions_verify) a profile on a GOVERNMENT-owned row (the
                owner of record is a county, city, town, state, school board, housing authority
                ...) whose legal name is none of the row's own entities is removed: a carried
                pre-hand-off block published one LLC's officers as the contact on 120 Lincoln
                county-owned parcels (the 10/3-fixed 'Linc-oln' substring bug made the county
                look like a business). A government parcel never has an LLC's registered agent as
                its contact. Other unbound legacy profiles (199 of 809 rows on the 10/8
                checkpoint, mostly a person owner after an LLC sold) are counted as
                unbound_kept and left: HANDOFF item 57 made stale owner-change profiles the
                owner's outreach-policy call.
    Only ledger-confirmed profiles are attached (resolved_profiles())."""
    p = Path(path) if path is not None else handoff_path()
    counts: dict[str, Any] = {"file": str(p), "status": "ok", "entities": 0,
                              "resolved_entities": 0, "attached": 0, "cleared": 0,
                              "unbound_cleared": 0, "unbound_kept": 0, "cleaned": 0}
    try:
        if os.environ.get("SOS_AGENT_HANDOFF_APPLY") == "0":
            counts["status"] = "disabled"
            log.info("sos_agent_handoff.disabled")
            return counts
        if not p.exists():
            counts["status"] = "absent"
            log.warning("sos_agent_handoff.absent", path=str(p),
                        note="the Mac has not pushed a SOS hand-off yet; nothing to apply")
            return counts
        try:
            ledger = load_ledger(p)
        except LedgerUnreadable as exc:
            counts["status"] = "unreadable"
            log.warning("sos_agent_handoff.unreadable", path=str(p), error=str(exc)[:300])
            return counts
        gen = ledger.get("generated_at")
        if gen:
            try:
                age_h = ((now or datetime.now(timezone.utc))
                         - datetime.fromisoformat(gen)).total_seconds() / 3600
                counts["age_hours"] = round(age_h, 1)
                stale_h = _env_float("SOS_AGENT_HANDOFF_STALE_HOURS", 72)
                if age_h > stale_h:
                    counts["status"] = "stale"
                    log.warning("sos_agent_handoff.stale", hours=round(age_h, 1),
                                stale_after=stale_h, generated_at=gen,
                                note="the Mac's daily SOS job (scripts/sos_agent_refresh.sh) "
                                     "has not pushed recently; applying the stale file anyway")
            except Exception:  # noqa: BLE001 - an odd timestamp is not a reason to skip
                counts["status"] = "undated"
        else:
            counts["status"] = "undated"
        profiles = {k: copy.deepcopy(v) for k, v in resolved_profiles(ledger).items()}
        for prof in profiles.values():
            clean_contact(prof)
        counts["entities"] = len(ledger.get("entities") or {})
        counts["resolved_entities"] = len(profiles)
        listings = listings if isinstance(listings, list) else list(listings)
        rejected = rejected_sosids_by_key(ledger)
        for li in listings:
            raw = li.raw if isinstance(getattr(li, "raw", None), dict) else None
            prof = raw.get("sos_agent") if raw else None
            if not isinstance(prof, dict):
                continue
            if row_profile_rejected(prof, _entity_of(li), rejected):
                del raw["sos_agent"]
                counts["cleared"] += 1
            elif not profile_bound_to_row(prof, li):
                if government_owned(li):
                    del raw["sos_agent"]
                    counts["unbound_cleared"] += 1
                else:
                    counts["unbound_kept"] += 1
                    if clean_contact(prof):
                        counts["cleaned"] += 1
            elif clean_contact(prof):
                counts["cleaned"] += 1
        counts["attached"] = propagate_profiles(listings, profiles)
        log.info("sos_agent_handoff.applied", **counts)
    except Exception as exc:  # noqa: BLE001 - this step must never fail the run
        counts["status"] = "error"
        counts["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        log.error("sos_agent_handoff.failed", error=counts["error"])
    return counts
