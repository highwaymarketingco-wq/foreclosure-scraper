"""NC Secretary of State registered-agent + officer enrichment.

For entity-owned leads (owner or defendant is an LLC/Inc/Corp), pull the free
public NC SOS business-registration profile so an otherwise contact-less entity
lead gets a real, mailable contact WITHOUT paying a skip-trace:

  - Registered agent name + registered office/mailing address
  - Principal office address (the business's real address)
  - Officers (Manager / Member / CEO / etc.) with names + addresses -- for a
    small distressed-property LLC these are usually the actual owner(s)

Value hierarchy for outreach: an officer (a real human) > registered agent (if
it is NOT a commercial agent service) > principal office address. We flag
`agent_is_service` so the dashboard can tell "this agent is CSC/CT, use the
officers" from "the agent IS the owner".

NC only. sosnc.gov sits behind Cloudflare, so this uses the same Scrapling
stealth render already proven by enrichment_sos_dissolution -- a real browser
that passes the JS challenge, NOT a CAPTCHA/paywall defeat. SC's
businessfilings.sc.gov is CAPTCHA-gated (compliance wall) so SC entities are
skipped, not scraped.

One stealth session handles a whole batch: Cloudflare is cleared once, then the
form is re-submitted per name. Bounded by a per-name timeout, an overall
wall-clock budget, and a consecutive-failure breaker (same guards as the
dissolution step). Network-heavy -> gated OFF by default (SOS_AGENT=1), meant
for the scheduled land-records pass, not the weekly crawl.

Free, no auth, public record, Scrapling stealth.

IDENTITY FRESHNESS (added 2026-10-03, PROVENANCE ONLY, not a gate): once resolved, a lead
is never re-checked (`if isinstance(raw.get("sos_agent"), dict): continue`) even after its
owner_name/defendant later changes. Live-checked against the board: at least 50.6% of 344
sos_agent rows (174) no longer read as the SAME business this profile was resolved for --
e.g. a Buncombe parcel whose owner/defendant is now "TRIVETTE, BRUCE" (a person) still
carries the registered agent for "Lentz Investments, LLC" (status: Dissolved); 7+ Lincoln
County parcels whose owner/defendant is now "LINCOLN COUNTY" (reverted after a tax sale)
still carry "BECM Properties LLC"'s agent. Unlike owner_phone (enrichment_voter_phone.py,
same date), there is no existing "do not use this contact" precedent to extend here --
owner_phone's gate exists because TCPA/do-not-dial is a hard compliance line for a PHONE;
a registered-agent MAILING contact has no such line, and whether a stale one should be
suppressed, kept with a warning, or actively re-resolved is a real outreach-policy call
this module does not make. What IS added: `resolved_for_entity` (the entity name actually
looked up) and `resolved_at` on every freshly-written profile, so a human or a later script
can compare it against the lead's current owner_name/defendant and decide for themselves --
nothing is auto-cleared or suppressed. A profile written before this fix has neither field
and is left exactly as it was.

MAC LOOKS UP, VM APPLIES (2026-10-05). The daily lookup runs on the Mac (residential IP,
scripts/sos_agent_refresh.py) and no longer writes the board: results go to the cumulative
hand-off file docs/handoff/sos_agent_results.json (sos_agent_handoff.py owns its format), and
the VM's pipeline attaches them with apply_sos_agent_handoff(), which calls THIS module's
propagate_profiles() -- the same matching (_entity_of + entity_key) and the same "one entity's
profile goes to every row it owns" propagation enrich_with_sos_agent() uses, not a copy of it.
What changed here for that: entity_key() (one normalized key for both sides), _prio() and
stamp_profile() lifted to module level so the Mac script imports them instead of duplicating
them, a polite randomized pause between lookups, a larger wall-clock budget, and
_batch_lookup(outcome=...) bookkeeping that tells an ANSWERED "no match" (a real miss) apart
from a lookup that never got an answer (timeout, exception, Cloudflare block page). The fetch
itself (_one: the stealth session, the form, the selectors) is unchanged.
"""
from __future__ import annotations

import asyncio
import copy
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

import structlog

from .models import Listing
from .enrichment_sos_dissolution import _is_business, _strip_business_suffix

log = structlog.get_logger()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()

_ENABLED = os.environ.get("SOS_AGENT") == "1"
_MAX_CHECK = int(os.environ.get("SOS_AGENT_MAX_CHECK", "60"))
_CALL_TIMEOUT_S = float(os.environ.get("SOS_AGENT_CALL_TIMEOUT_S", "45"))
# Wall-clock budget for one batch. Was 900 s, sized for 40 names with no pause. The daily
# cap is now up to 150 names with a 4-6 s polite pause between them (~9-10 s a name, about
# 25 minutes), so 45 minutes leaves real margin; scripts/sos_agent_refresh.sh's SOS_TIMEOUT
# (4200 s) sits above this plus the board scan and the git push.
_MAX_SECONDS = float(os.environ.get("SOS_AGENT_MAX_SECONDS", "2700"))
_BREAKER_FAILS = int(os.environ.get("SOS_AGENT_BREAKER_FAILS", "6"))
# Polite randomized pause between two lookups in the same session (not before the first).
_PAUSE_MIN_S = float(os.environ.get("SOS_AGENT_PAUSE_MIN_S", "4"))
_PAUSE_MAX_S = float(os.environ.get("SOS_AGENT_PAUSE_MAX_S", "6"))

# Page titles of a block/challenge interstitial instead of a real sosnc.gov page. A lookup
# that lands on one got NO answer (counts toward the breaker and is retried), which is
# different from an answered search with no matching entity (a real miss).
_BLOCK_TITLES = ("just a moment", "attention required", "access denied",
                 "too many requests", "verify you are human", "checking your browser")

_SEARCH_URL = "https://www.sosnc.gov/online_services/search/by_title/_Business_Registration"
_BASE = "https://www.sosnc.gov"

# Commercial registered-agent services -- when the agent is one of these, the
# agent address is a mailbox, not the owner; the officers are the real contact.
_AGENT_SERVICES = (
    "corporation service company", "c t corporation", "ct corporation",
    "registered agents inc", "cogency global", "national registered agents",
    "incorp services", "northwest registered agent", "united states corporation",
    "paracorp", "capitol services", "cscglobal", "csc-", "vcorp", "legalinc",
    "harbor compliance", "registered agent solutions", "interstate agent",
    "corporate creations network", "registered agent", "spiegel & utrera",
    "zenbusiness", "legalzoom", "a registered agent", "nrai",
)

# Trust / estate captions that are NOT in the business registry -- skip cleanly.
_NON_ENTITY = ("living trust", "revocable trust", "irrevocable trust", "family trust")


def _clean_entity(name: str) -> Optional[str]:
    """Reduce a raw owner/defendant string to a searchable NC entity name.

    Handles litigation captions ("Plaintiff v. Defendant LLC" -> the LLC),
    trustee tails (";COLE, GARY TRUSTEE"), and C/O prefixes. Returns None if the
    result is not a registrable business (e.g. a personal living trust).
    """
    if not name:
        return None
    s = name.strip()
    # litigation caption: keep the party on the defendant side of " v. "/" vs. "
    m = re.split(r"\s+v(?:s|\.|s\.)?\.?\s+", s, flags=re.I)
    if len(m) > 1:
        s = m[-1].strip()
    # drop trustee / secondary-party tails
    s = re.split(r"[;]", s)[0].strip()
    s = re.sub(r"^\s*c/o\s+", "", s, flags=re.I).strip()
    s = re.sub(r"\b(do not send|address is wrong|unknown)\b.*$", "", s, flags=re.I).strip(" ,.-")
    low = s.lower()
    if any(k in low for k in _NON_ENTITY):
        return None
    if not _is_business(s):
        return None
    return s or None


def _entity_of(li: Listing) -> Optional[str]:
    """The entity name to look up for a listing (owner preferred over defendant)."""
    for raw in (li.owner_name, li.defendant):
        c = _clean_entity(raw or "")
        if c:
            return c
    return None


def entity_key(name: str) -> str:
    """The one normalized key an entity is matched on, on the Mac (hand-off ledger) and the
    VM (apply) alike: case, punctuation and spacing do not matter ("ACME HOLDINGS, LLC" and
    "Acme Holdings LLC" are the same key; they send sosnc.gov the same search)."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (name or "").lower()).split())


def _prio(li: Listing) -> int:
    """HOT/WARM first, so a capped run spends its lookups on the best leads."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    tier = ((raw.get("distress_stack") or {}).get("tier")
            or (raw.get("grade") or {}).get("tier") or "")
    return {"HOT": 0, "WARM": 1}.get(str(tier).upper(), 2)


def stamp_profile(prof: dict, name: str) -> dict:
    """Provenance stamp on a freshly resolved profile (2026-10-03, see the module
    docstring): which entity it was resolved FOR, and when. Gates nothing."""
    prof["resolved_for_entity"] = name
    prof["resolved_at"] = _today_iso()
    return prof


def _unresolved_entity_rows(listings) -> Iterator[tuple[Listing, str]]:
    """(listing, entity name) for every NC entity-owned row that has no sos_agent yet. A row
    that already carries one is never touched (it is not re-checked or overwritten)."""
    for li in listings:
        if li.state != "NC":
            continue
        name = _entity_of(li)
        if not name:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        if isinstance(raw.get("sos_agent"), dict):
            continue
        yield li, name


def _attach(li: Listing, prof: dict) -> None:
    raw = li.raw if isinstance(li.raw, dict) else {}
    li.raw = raw
    li.raw["sos_agent"] = copy.deepcopy(prof)


def propagate_profiles(listings, profiles_by_key: dict[str, dict]) -> int:
    """Attach a resolved profile to EVERY unresolved NC row whose entity matches it (same
    entity -> same registered agent; free, no network). `profiles_by_key` is keyed by
    entity_key(). Used by enrich_with_sos_agent() for profiles already on the board and by
    sos_agent_handoff.apply_sos_agent_handoff() for the Mac's hand-off file. Returns the
    number of rows that received a profile."""
    if not profiles_by_key:
        return 0
    n = 0
    for li, name in _unresolved_entity_rows(listings):
        prof = profiles_by_key.get(entity_key(name))
        if prof is None:
            continue
        _attach(li, prof)
        n += 1
    return n


_ADDR_HEADERS = {
    "registered office address": "registered_office_address",
    "registered mailing address": "registered_mailing_address",
    "principal office address": "principal_office_address",
    "mailing address": "mailing_address",
}
_OFFICIALS = ("officers", "company officials", "officials")
_END = ("stock:", "return to top", "other agencies", "links of interest")
_STOP = set(_ADDR_HEADERS) | set(_OFFICIALS) | set(_END)
# role words that mark the start of a new officer/official block
_TITLE_RE = re.compile(
    r"\b(manager|member|president|vice|secretary|treasurer|officer|organizer|"
    r"director|chief|ceo|cfo|coo|governor|partner|principal|owner|incorporator)\b",
    re.I,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _parse_profile(text: str) -> dict:
    """Parse the NC SOS business-registration profile innerText into fields."""
    text = text.replace("\xa0", " ")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out: dict = {"checked": True, "source": "nc_sos"}
    officers: list[dict] = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        low = line.lower()
        if low.startswith("legal name:"):
            out["legal_name"] = line.split(":", 1)[1].strip()
        elif "sosid)" in low and ":" in line:
            out["sosid"] = line.split(":", 1)[1].strip()
        elif low.startswith("status:"):
            out["status"] = line.split(":", 1)[1].strip()
        elif low.startswith("registered agent:"):
            out["registered_agent"] = _norm(line.split(":", 1)[1])
        elif low in _ADDR_HEADERS:
            key = _ADDR_HEADERS[low]
            addr_lines = []
            j = i + 1
            while j < n and lines[j].lower() not in _STOP and len(addr_lines) < 2 \
                    and not re.match(r"^(legal name|status|registered agent|citizenship|"
                                     r"date formed|fiscal month|secretary of state)", lines[j], re.I):
                addr_lines.append(lines[j])
                j += 1
            if key not in out and addr_lines:
                out[key] = _norm(", ".join(addr_lines))
        elif low in _OFFICIALS:
            j = i + 1
            cur: dict | None = None
            while j < n and lines[j].lower() not in _END:
                lj = lines[j]
                low_j = lj.lower()
                # skip the statutory preamble ("All LLCs are managed ... N.C.G.S. ...")
                if low_j.startswith("all llcs") or "pursuant to" in low_j or "n.c.g.s" in low_j:
                    j += 1
                    continue
                if _TITLE_RE.search(lj) and len(lj) < 40:
                    if cur:
                        officers.append(cur)
                    cur = {"title": _norm(lj), "name": "", "address": ""}
                    # next line is the name
                    if j + 1 < n and lines[j + 1].lower() not in _END:
                        cur["name"] = _norm(lines[j + 1])
                        j += 2
                        continue
                elif cur is not None:
                    cur["address"] = _norm((cur["address"] + " " + lj).strip())
                j += 1
            if cur:
                officers.append(cur)
            i = j
            continue
        i += 1

    officers = [o for o in officers if o.get("name")]
    if officers:
        out["officers"] = officers[:6]

    # derive best outreach contact
    agent = (out.get("registered_agent") or "").lower()
    out["agent_is_service"] = bool(agent) and any(s in agent for s in _AGENT_SERVICES)
    best_name = best_addr = None
    if officers:
        best_name = officers[0]["name"]
        best_addr = officers[0]["address"] or None
    if not best_name and out.get("registered_agent") and not out["agent_is_service"]:
        best_name = out["registered_agent"]
        best_addr = out.get("registered_office_address")
    if not best_addr:
        best_addr = out.get("principal_office_address") or out.get("mailing_address")
    if best_name:
        out["best_contact_name"] = best_name
    if best_addr:
        out["best_contact_address"] = best_addr
    return out


async def _looks_blocked(page) -> bool:
    """True when the page is a challenge/block interstitial, not a sosnc.gov page."""
    try:
        title = (await page.title() or "").lower()
    except Exception:  # noqa: BLE001 - an unreadable title is not evidence of a block
        return False
    return any(t in title for t in _BLOCK_TITLES)


async def _pause() -> None:
    lo, hi = sorted((max(0.0, _PAUSE_MIN_S), max(0.0, _PAUSE_MAX_S)))
    if hi > 0:
        await asyncio.sleep(random.uniform(lo, hi))


async def _batch_lookup(names: list[str], outcome: Optional[dict] = None) -> dict:
    """One stealth session: clear Cloudflare once, then look up each name.

    Returns {name: profile-or-None} for every name ATTEMPTED (a name the deadline or the
    breaker stopped before is absent). When `outcome` is passed it is filled with how the
    batch went, for the caller's ledger and back-off:
      attempted       names actually looked up
      resolved/misses/errors   lists of names. A MISS is an answered search with no
                      matching entity; an ERROR got no answer (timeout, exception, a
                      Cloudflare block page, a profile page with no SOSID on it).
      breaker_tripped _BREAKER_FAILS errors in a row stopped the batch
      deadline_hit    the _MAX_SECONDS budget stopped the batch
      session_failed  the stealth session itself failed (nothing could be looked up)
      error           text of that session failure, if any

    THE BREAKER counts consecutive lookups that got no answer. It used to count an answered
    "no match" as a failure too, so six real misses in a row (normal: ~55% of names are not
    in the NC registry) stopped the batch. That is what happened on 2026-10-01 and 10-02:
    the same 7 names, the same 1 hit + 6 misses, both runs over in under a minute. A miss is
    the site answering, so it now resets the streak instead.
    """
    out = outcome if outcome is not None else {}
    out.update({"attempted": 0, "resolved": [], "misses": [], "errors": [],
                "breaker_tripped": False, "deadline_hit": False,
                "session_failed": False, "error": None})
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        out["session_failed"] = True
        out["error"] = "scrapling not installed"
        return {}

    results: dict = {}
    state = {"consec_fail": 0, "deadline": time.monotonic() + _MAX_SECONDS}

    async def page_action(page):
        for i, name in enumerate(names):
            if state["consec_fail"] >= _BREAKER_FAILS:
                out["breaker_tripped"] = True
                break
            if time.monotonic() > state["deadline"]:
                out["deadline_hit"] = True
                break
            if i:
                await _pause()
            core = _strip_business_suffix(name) or name
            out["attempted"] += 1
            try:
                await asyncio.wait_for(_one(page, name, core, results), timeout=_CALL_TIMEOUT_S)
                prof = results.get(name)
                if prof and prof.get("sosid"):
                    out["resolved"].append(name)
                    state["consec_fail"] = 0
                elif prof is None and not await _looks_blocked(page):
                    out["misses"].append(name)     # answered: no such NC entity
                    state["consec_fail"] = 0
                else:
                    out["errors"].append(name)     # block page, or a profile with no SOSID
                    state["consec_fail"] += 1
            except (Exception, asyncio.TimeoutError):
                state["consec_fail"] += 1
                results.setdefault(name, None)
                out["errors"].append(name)
        # six no-answers in a row is the rate-limit signal even when they were the last six
        if state["consec_fail"] >= _BREAKER_FAILS:
            out["breaker_tripped"] = True

    async def _one(page, name, core, results):
        await page.goto(_SEARCH_URL)
        await page.wait_for_selector("#SearchCriteria", timeout=20000)
        await page.fill("#SearchCriteria", core)
        await page.eval_on_selector(
            "form[action*='Business_Registration_Results']", "f=>f.submit()")
        await page.wait_for_load_state("networkidle", timeout=20000)
        links = await page.eval_on_selector_all(
            "a", "els=>els.map(e=>e.getAttribute('href'))"
            ".filter(h=>h&&h.toLowerCase().includes('business_registration_profile'))")
        links = list(dict.fromkeys([l for l in links if l]))
        if not links:
            results[name] = None
            return
        href = links[0]
        await page.goto(href if href.startswith("http") else _BASE + href)
        await page.wait_for_load_state("networkidle", timeout=20000)
        text = await page.inner_text("body")
        prof = _parse_profile(text)
        prof["profile_url"] = page.url
        prof["match_count"] = len(links)
        results[name] = prof

    try:
        coro = StealthyFetcher.async_fetch(
            _SEARCH_URL, headless=True, network_idle=True, timeout=60000,
            page_action=page_action,
        )
        await asyncio.wait_for(coro, timeout=_MAX_SECONDS + _CALL_TIMEOUT_S)
    except asyncio.TimeoutError:
        out["deadline_hit"] = True
    except Exception as exc:  # noqa: BLE001 - partial results below are still returned
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    if not out["attempted"] and names:
        out["session_failed"] = True
    return results


async def enrich_with_sos_agent(listings: list[Listing], max_check: int = _MAX_CHECK) -> dict:
    """Fill raw['sos_agent'] for entity-owned NC leads (bounded, gated OFF)."""
    counts = {"targets": 0, "resolved": 0, "with_contact": 0, "misses": 0}
    if not _ENABLED:
        return counts

    # unique NC entity names, HOT/WARM/graded first so the cap spends on the best leads
    name_to_listings: dict[str, list[Listing]] = {}
    ranked: list[tuple[int, str]] = []

    # Names already resolved on a prior pass — skip them so each run advances
    # the frontier to NEW entities instead of re-hitting the same top-priority
    # names, and propagate a resolved profile to any co-owned lead that lacks
    # one (same entity -> same registered agent; free, no network).
    resolved_profiles: dict[str, dict] = {}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        sa = raw.get("sos_agent")
        if isinstance(sa, dict) and sa.get("sosid"):
            nm = _entity_of(li)
            if nm:
                resolved_profiles.setdefault(entity_key(nm), sa)

    propagated = propagate_profiles(listings, resolved_profiles)

    # whatever is still unresolved after propagation is a lookup candidate; one lookup per
    # entity_key, under the first spelling seen
    key_to_name: dict[str, str] = {}
    for li, name in _unresolved_entity_rows(listings):
        k = entity_key(name)
        if k not in key_to_name:
            key_to_name[k] = name
            ranked.append((_prio(li), name))
        name_to_listings.setdefault(key_to_name[k], []).append(li)

    ranked.sort(key=lambda t: t[0])
    names = [n for _, n in ranked][:max_check]
    counts["targets"] = len(names)
    counts["propagated"] = propagated
    if not names:
        log.info("sos_agent.no_targets")
        return counts

    log.info("sos_agent.start", targets=len(names))
    results = await _batch_lookup(names)

    for name, prof in results.items():
        if not prof or not prof.get("sosid"):
            counts["misses"] += 1
            continue
        counts["resolved"] += 1
        if prof.get("best_contact_address") or prof.get("best_contact_name"):
            counts["with_contact"] += 1
        # Provenance only -- NOT a staleness gate (see this function's docstring and
        # docs/HANDOFF.md 2026-10-03). `name` is the entity this profile was actually
        # resolved FOR (_entity_of(li) at resolution time); `resolved_at` is when. Neither
        # auto-clears or suppresses anything -- a stale registered agent may still be a
        # real, reachable contact (e.g. the same person behind a related entity), and
        # deciding whether to suppress/warn/keep is an outreach-policy call this module
        # does not make. This only lets a human or a later script compare
        # sos_agent.resolved_for_entity against the lead's CURRENT owner_name/defendant
        # for themselves, the same live-checked gap owner_freshness.py's docstring
        # describes for owner_name: before this, nothing recorded which entity a
        # registered-agent lookup was even FOR, so a later ownership change (the lead's
        # owner/defendant moving on, e.g. to a bank or a county after a tax sale) left a
        # stranded contact with no way to tell it apart from a still-good one.
        stamp_profile(prof, name)
        for li in name_to_listings.get(name, []):
            _attach(li, prof)

    log.info("sos_agent.done", **counts)
    return counts
