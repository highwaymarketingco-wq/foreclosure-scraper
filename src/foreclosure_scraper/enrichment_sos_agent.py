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
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Optional

import structlog

from .models import Listing
from .enrichment_sos_dissolution import _is_business, _strip_business_suffix

log = structlog.get_logger()

_ENABLED = os.environ.get("SOS_AGENT") == "1"
_MAX_CHECK = int(os.environ.get("SOS_AGENT_MAX_CHECK", "60"))
_CALL_TIMEOUT_S = float(os.environ.get("SOS_AGENT_CALL_TIMEOUT_S", "45"))
_MAX_SECONDS = float(os.environ.get("SOS_AGENT_MAX_SECONDS", "900"))
_BREAKER_FAILS = int(os.environ.get("SOS_AGENT_BREAKER_FAILS", "6"))

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


async def _batch_lookup(names: list[str]) -> dict:
    """One stealth session: clear Cloudflare once, then look up each name."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return {}

    results: dict = {}
    state = {"consec_fail": 0, "deadline": time.monotonic() + _MAX_SECONDS}

    async def page_action(page):
        for name in names:
            if time.monotonic() > state["deadline"] or state["consec_fail"] >= _BREAKER_FAILS:
                break
            core = _strip_business_suffix(name) or name
            try:
                await asyncio.wait_for(_one(page, name, core, results), timeout=_CALL_TIMEOUT_S)
                if name in results and results[name]:
                    state["consec_fail"] = 0
                else:
                    state["consec_fail"] += 1
            except (Exception, asyncio.TimeoutError):
                state["consec_fail"] += 1
                results.setdefault(name, None)

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
    except (Exception, asyncio.TimeoutError):
        pass
    return results


async def enrich_with_sos_agent(listings: list[Listing], max_check: int = _MAX_CHECK) -> dict:
    """Fill raw['sos_agent'] for entity-owned NC leads (bounded, gated OFF)."""
    counts = {"targets": 0, "resolved": 0, "with_contact": 0, "misses": 0}
    if not _ENABLED:
        return counts

    # unique NC entity names, HOT/WARM/graded first so the cap spends on the best leads
    name_to_listings: dict[str, list[Listing]] = {}
    ranked: list[tuple[int, str]] = []

    def _prio(li: Listing) -> int:
        raw = li.raw if isinstance(li.raw, dict) else {}
        tier = ((raw.get("distress_stack") or {}).get("tier")
                or (raw.get("grade") or {}).get("tier") or "")
        return {"HOT": 0, "WARM": 1}.get(str(tier).upper(), 2)

    for li in listings:
        if li.state != "NC":
            continue
        name = _entity_of(li)
        if not name:
            continue
        if name not in name_to_listings:
            ranked.append((_prio(li), name))
        name_to_listings.setdefault(name, []).append(li)

    ranked.sort(key=lambda t: t[0])
    names = [n for _, n in ranked][:max_check]
    counts["targets"] = len(names)
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
        for li in name_to_listings.get(name, []):
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["sos_agent"] = prof

    log.info("sos_agent.done", **counts)
    return counts
