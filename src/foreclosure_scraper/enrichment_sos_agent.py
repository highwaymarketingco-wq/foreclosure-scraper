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

RESULT SELECTION (2026-10-05, second change that day). _one() used to open the FIRST search
hit. sosnc.gov's business search is a "Starting With" search, so a generic name returns every
entity whose name merely begins with it: "COVENANT PRESBYTERIAN CHURCH" (a Buncombe owner)
returned 7 churches and the first one, "Covenant Presbyterian Church of the Associate Reformed
Presbyterian Church" (Jacksonville), was attached to the lead. Now _one() reads the result
list it already has on screen (parse_search_results(): each result is an accordion block with
"Legal name", "Prev Legal name", "Sosid", "Status", "Citizenship", "Business type" and the
profile link; no county, city or address appears anywhere in the list), and select_result()
picks one only when it is the same entity:
  1. NAME: the result's Legal name and the searched name must have the same sos_core_key():
     case, punctuation, apostrophes, spacing, "&" vs "AND", dotted acronyms (L.L.C.), a
     leading "THE" and trailing entity designators (LLC, L.L.C., INC, INCORPORATED, CORP,
     CORPORATION, CO, COMPANY, LTD, LP, LLP, PLLC, PA, PC, "LIMITED LIABILITY COMPANY", ...)
     do not count. A longer or shorter name never matches ("Covenant Presbyterian Church
     Kannapolis" is not "Covenant Presbyterian Church"), and "Prev Legal name" is not used.
  2. ENTITY TYPE: when both names carry a designator that fixes the type (LLC-type, corporation
     type, partnership type), the types must agree, so "DB HOMES LLC" never takes "DB Homes,
     Inc.". CO/COMPANY/LTD/LIMITED say nothing about the type, and a name with no designator
     (most county owner fields for churches and associations) matches any type.
  3. TIE-BREAKS among several matches: the same designator type as the searched name, then an
     active status ("Current - Active", "Active/Failure to Pay Fee"). The result list exposes
     no location, so there is no county/city tie-break to apply; several matches left after
     these two steps is AMBIGUOUS.
  No match, or an unbroken tie, is AMBIGUOUS: nothing is opened or attached, and the batch
  outcome lists the name under `ambiguous` with the candidate count and the first few
  candidate names (sos_agent_handoff records it; it is never applied). The opened profile's
  own Legal name is checked against the searched name once more before it is accepted.
  An ambiguous answer is still an answer: like a miss, it resets the breaker streak.
CONTACT PARSING (same day): placeholders such as "Not Listed" are no contact (dropped from the
registered agent, officers and addresses); a commercial registered-agent service stays as
`registered_agent` with `agent_is_service: true`, is never `best_contact_name`, and neither its
registered office nor a mailing address that names the service becomes `best_contact_address`.
clean_contact() applies the same rules to a profile already stored (ledger, board rows).
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
from .name_normalize import normalize_name

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
# The same idea on normalize_name()'d text (upper case, punctuation gone, dotted/spaced
# acronyms joined), matched on whole words. Catches spellings the substrings above miss:
# "U S Corporation Co" (a live 2026-10-05 profile that came back as best_contact_name),
# "U.S. Corporation Company", "The Corporation Trust Company".
_AGENT_SERVICE_PHRASES = (
    "US CORPORATION", "UNITED STATES CORPORATION", "CORPORATION SERVICE", "CT CORPORATION",
    "CORPORATION TRUST", "COGENCY GLOBAL", "NATIONAL REGISTERED AGENTS", "REGISTERED AGENTS",
    "REGISTERED AGENT", "INCORP SERVICES", "INCORPORATING SERVICE", "INCORPORATING SERVICES",
    "CORPORATE CREATIONS", "CAPITOL SERVICES", "BUSINESS FILINGS", "NATIONAL CORPORATE RESEARCH",
    "UNITED AGENT GROUP", "HARBOR COMPLIANCE", "CSC GLOBAL", "CSCGLOBAL", "LEGALINC", "VCORP",
    "PARACORP", "ZENBUSINESS", "LEGALZOOM", "NRAI", "INTERSTATE AGENT", "SUNDOC FILINGS",
)

# Stamped on every profile select_result() chose (profiles without it predate the rule).
MATCH_RULE = "exact_name_v1"

# Values the profile page prints where there is no data ("Registered agent:  Not Listed").
_PLACEHOLDERS = {"not listed", "none", "none listed", "n/a", "na", "not applicable",
                 "unknown", "not available", "not provided", "null", "-", "--"}

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


# ---------------------------------------------------------------------------
# result selection: which search hit IS the entity (see the module docstring)
# ---------------------------------------------------------------------------

# Entity designators, longest first, as normalize_name() token tuples, with the entity TYPE
# each one fixes: "llc", "corp", "lp", or None when the word says nothing about the type
# (NC corporations AND LLCs both use "Company"/"Co."; "Limited"/"Ltd." likewise).
_DESIGNATORS: tuple[tuple[tuple[str, ...], Optional[str]], ...] = tuple(sorted((
    (("PROFESSIONAL", "LIMITED", "LIABILITY", "COMPANY"), "llc"),
    (("LIMITED", "LIABILITY", "LIMITED", "PARTNERSHIP"), "lp"),
    (("LIMITED", "LIABILITY", "COMPANY"), "llc"),
    (("LTD", "LIABILITY", "COMPANY"), "llc"),
    (("LIMITED", "LIABILITY", "CO"), "llc"),
    (("LTD", "LIABILITY", "CO"), "llc"),
    (("LIMITED", "LIABILITY", "PARTNERSHIP"), "lp"),
    (("LIMITED", "PARTNERSHIP"), "lp"),
    (("PROFESSIONAL", "CORPORATION"), "corp"),
    (("PROFESSIONAL", "ASSOCIATION"), "corp"),
    (("LLC",), "llc"), (("PLLC",), "llc"),
    (("LP",), "lp"), (("LLP",), "lp"), (("LLLP",), "lp"),
    (("INC",), "corp"), (("INCORPORATED",), "corp"), (("CORP",), "corp"),
    (("CORPORATION",), "corp"), (("PC",), "corp"), (("PA",), "corp"),
    (("CO",), None), (("COMPANY",), None), (("LTD",), None), (("LIMITED",), None),
), key=lambda d: -len(d[0])))
_DOTTED_ACRONYM_RE = re.compile(r"\b(?:[A-Za-z]\.\s?){2,}")
_SPACED_DESIGNATORS = {"LLC", "LLP", "LLLP", "PLLC", "LP", "PA", "PC", "INC"}


def _sos_tokens(name: Optional[str]) -> list[str]:
    """normalize_name() tokens with "&" read as AND and dotted acronyms joined
    ("L.L.C." -> LLC, "U.S." -> US), plus a trailing run of spaced single letters that
    spells a designator ("L L C") joined."""
    s = _DOTTED_ACRONYM_RE.sub(lambda m: re.sub(r"[.\s]", "", m.group(0)) + " ", str(name or ""))
    s = s.replace("&", " AND ").replace("+", " AND ")
    toks = normalize_name(s).split()
    i = len(toks)
    while i > 0 and len(toks[i - 1]) == 1 and toks[i - 1].isalpha():
        i -= 1
    if len(toks) - i >= 2 and "".join(toks[i:]) in _SPACED_DESIGNATORS:
        toks = toks[:i] + ["".join(toks[i:])]
    return toks


def _split_designators(name: Optional[str]) -> tuple[list[str], list[Optional[str]]]:
    """(core tokens, designator types found at the end, outermost first). A leading or
    trailing THE is dropped; the core is never stripped to nothing."""
    toks = _sos_tokens(name)
    types: list[Optional[str]] = []
    changed = True
    while changed and len(toks) > 1:
        changed = False
        if toks[-1] == "THE":
            toks = toks[:-1]
            changed = True
            continue
        for words, typ in _DESIGNATORS:
            n = len(words)
            if len(toks) > n and tuple(toks[-n:]) == words:
                toks = toks[:-n]
                types.append(typ)
                changed = True
                break
    if len(toks) > 1 and toks[0] == "THE":
        toks = toks[1:]
    return toks, types


def sos_core_key(name: Optional[str]) -> str:
    """The identity an NC registry name is matched on: normalize_name() (case, punctuation,
    apostrophes), "&" = AND, dotted acronyms joined, leading/trailing THE and trailing
    designators dropped, then the spaces removed ("Nature`s Way" = "NATURE S WAY",
    "Dana-hill Corporation" = "DANA HILL CORP"). NC's own name-distinguishability rule ignores
    exactly these differences."""
    toks, _ = _split_designators(name)
    return "".join(toks)


def designator_type(name: Optional[str]) -> Optional[str]:
    """"llc" | "corp" | "lp" from the outermost designator that fixes the type, else None."""
    _, types = _split_designators(name)
    for t in types:
        if t:
            return t
    return None


def names_match(searched: Optional[str], legal_name: Optional[str]) -> bool:
    """True when a registry Legal name is the searched entity: the same sos_core_key() and no
    conflicting entity type ("X LLC" is not "X, Inc."; "X" or "X Co" matches either)."""
    a, b = sos_core_key(searched), sos_core_key(legal_name)
    if not a or a != b:
        return False
    ta, tb = designator_type(searched), designator_type(legal_name)
    return ta is None or tb is None or ta == tb


def is_active_status(status: Optional[str]) -> bool:
    """"Current - Active", "Current-Active", "Active/Failure to Pay Fee" -> True;
    dissolved / withdrawn / merged / revoked / "Multiple" -> False."""
    s = re.sub(r"\s+", " ", str(status or "").replace("\xa0", " ")).lower()
    return bool(re.search(r"\bactive\b", s)) and "inactive" not in s


def _clean_text(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("\xa0", " ")).strip()


def parse_search_results(html: str) -> dict:
    """The candidates on a sosnc.gov Business Registration search-results page, in page order.

    Real markup (captured 2026-10-05, tests/fixtures/sosnc_search_*.html): a "BRD Search:
    Records Found: N" line, then one accordion per entity inside #resultsSection: a heading
    button (div.searchHeader = "Name • SOSID", div.searchSubHeader = "Status • Type") that
    controls a hidden div.usa-accordion__content holding "Legal name:", optional "Prev Legal
    name:", "Sosid:", "Date formed:", "Status:", "Citizenship:", "Business type:" rows and the
    "More information" link to Business_Registration_profile/<id>. No address or county.

    Returns {"records_found": int | None, "candidates": [{legal_name, prev_legal_name, sosid,
    status, citizenship, business_type, profile_href}, ...]}."""
    import lxml.html

    out: dict = {"records_found": None, "candidates": []}
    if not html:
        return out
    try:
        doc = lxml.html.fromstring(html)
    except Exception:  # noqa: BLE001 - an unparseable page has no candidates
        return out
    m = re.search(r"Records\s*Found:\s*(\d+)", _clean_text(doc.text_content()), re.I)
    if m:
        out["records_found"] = int(m.group(1))

    headings = {}
    for btn in doc.xpath("//button[@aria-controls]"):
        head = btn.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' searchHeader ')]")
        sub = btn.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' searchSubHeader ')]")
        headings[btn.get("aria-controls")] = (
            _clean_text(head[0].text_content()) if head else "",
            _clean_text(sub[0].text_content()) if sub else "")

    boxes = doc.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), "
                      "' usa-accordion__content ')]")
    for box in boxes:
        fields: dict[str, str] = {}
        for row in box.xpath(".//div[contains(concat(' ', normalize-space(@class), ' '), ' para-small ')]"):
            label = row.xpath("./span[contains(concat(' ', normalize-space(@class), ' '), ' boldSpan ')]")
            if not label:
                continue
            key = _clean_text(label[0].text_content()).rstrip(":").strip().lower()
            whole = _clean_text(row.text_content())
            lab = _clean_text(label[0].text_content())
            fields[key] = whole[len(lab):].strip() if whole.startswith(lab) else whole
        hrefs = [a.get("href") for a in box.xpath(".//a[@href]")
                 if "business_registration_profile" in (a.get("href") or "").lower()]
        head, sub = headings.get(box.get("id"), ("", ""))
        head_name, _, head_sosid = head.rpartition("•") if "•" in head else (head, "", "")
        sub_status = sub.split("•")[0].strip() if sub else ""
        sub_type = sub.split("•")[1].strip() if sub.count("•") >= 1 else ""
        cand = {
            "legal_name": fields.get("legal name") or head_name.strip(),
            "prev_legal_name": fields.get("prev legal name") or "",
            "sosid": fields.get("sosid") or head_sosid.strip(),
            "status": fields.get("status") or sub_status,
            "citizenship": fields.get("citizenship") or "",
            "business_type": fields.get("business type") or sub_type,
            "profile_href": hrefs[0] if hrefs else "",
        }
        if cand["legal_name"] and cand["profile_href"]:
            out["candidates"].append(cand)
    return out


def select_result(searched: str, candidates: list[dict]) -> tuple[Optional[dict], dict]:
    """(the candidate that IS `searched`, or None; detail). detail["verdict"] is "match" or
    "ambiguous"; it also carries the candidate count, how many matched on name, how many of
    those are active, the reason when nothing was chosen, and the first few candidates (for a
    human to review in the ledger). Rules: the module docstring, RESULT SELECTION."""
    exact = [c for c in candidates if names_match(searched, c.get("legal_name"))]
    detail: dict = {"candidates": len(candidates), "exact": len(exact),
                    "active_exact": sum(1 for c in exact if is_active_status(c.get("status")))}
    pool = exact
    want = designator_type(searched)
    if len(pool) > 1 and want:
        same = [c for c in pool if designator_type(c.get("legal_name")) == want]
        if same:
            pool = same
    if len(pool) > 1:
        active = [c for c in pool if is_active_status(c.get("status"))]
        if active:
            pool = active
    if len(pool) == 1:
        detail["verdict"] = "match"
        return pool[0], detail
    detail["verdict"] = "ambiguous"
    detail["reason"] = "no_exact_name_match" if not exact else "several_exact_matches"
    detail["top"] = [f"{_clean_text(c.get('legal_name'))[:120]} ({c.get('sosid') or '?'}, "
                     f"{_clean_text(c.get('status'))[:40]})" for c in (pool or candidates)[:5]]
    return None, detail


def _is_placeholder(value) -> bool:
    return _clean_text(value).strip(" .").lower() in _PLACEHOLDERS


def is_agent_service(name: Optional[str]) -> bool:
    """A commercial registered-agent service (CSC, CT, Registered Agents Inc, U S Corporation
    Co, ...), i.e. a mailbox, not the owner."""
    low = (name or "").lower()
    if not low.strip():
        return False
    if any(s in low for s in _AGENT_SERVICES):
        return True
    norm = f" {' '.join(_join_letter_runs(_sos_tokens(name)))} "
    return any(f" {p} " in norm for p in _AGENT_SERVICE_PHRASES)


def _join_letter_runs(toks: list[str]) -> list[str]:
    """["U", "S", "CORPORATION"] -> ["US", "CORPORATION"]: consecutive single letters join."""
    out: list[str] = []
    run = False
    for t in toks:
        single = len(t) == 1 and t.isalpha()
        if single and run:
            out[-1] += t
        else:
            out.append(t)
        run = single
    return out


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
            agent = _norm(line.split(":", 1)[1])
            if agent and not _is_placeholder(agent):      # "Not Listed" is no agent
                out["registered_agent"] = agent
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

    for o in officers:
        if _is_placeholder(o.get("address")):
            o["address"] = ""
    officers = [o for o in officers if o.get("name") and not _is_placeholder(o["name"])]
    if officers:
        out["officers"] = officers[:6]
    for key in _ADDR_HEADERS.values():
        if key in out and _is_placeholder(out[key]):
            del out[key]

    # derive best outreach contact
    out["agent_is_service"] = is_agent_service(out.get("registered_agent"))
    best_name, best_addr = _best_contact(out)
    if best_name:
        out["best_contact_name"] = best_name
    if best_addr:
        out["best_contact_address"] = best_addr
    return out


def _is_service_address(prof: dict, addr: Optional[str]) -> bool:
    """An address that belongs to a commercial agent service: the service's registered
    office/mailing address, or any address that names a service ("U S Corporation Company
    229 S State St, Dover, DE")."""
    if not addr:
        return False
    if prof.get("agent_is_service") and addr in (prof.get("registered_office_address"),
                                                 prof.get("registered_mailing_address")):
        return True
    return is_agent_service(addr)


def _best_contact(prof: dict) -> tuple[Optional[str], Optional[str]]:
    """Value hierarchy for outreach (module docstring): the first officer (a real person, or the
    parent entity of a manager-managed LLC) > the registered agent when it is NOT a commercial
    service > the principal office / mailing address. Never a placeholder, never a service."""
    best_name = best_addr = None
    officers = [o for o in (prof.get("officers") or [])
                if isinstance(o, dict) and o.get("name") and not _is_placeholder(o["name"])]
    agent = prof.get("registered_agent")
    if agent and _is_placeholder(agent):
        agent = None
    if officers:
        best_name = officers[0]["name"]
        best_addr = officers[0].get("address") or None
    if not best_name and agent and not prof.get("agent_is_service") and not is_agent_service(agent):
        best_name = agent
        best_addr = prof.get("registered_office_address")
    if not best_addr or _is_placeholder(best_addr) or _is_service_address(prof, best_addr):
        best_addr = None
        for key in ("principal_office_address", "mailing_address"):
            a = prof.get(key)
            if a and not _is_placeholder(a) and not _is_service_address(prof, a):
                best_addr = a
                break
    return best_name, best_addr


def clean_contact(prof: dict) -> bool:
    """Apply the contact-parsing rules to a profile that is ALREADY stored (ledger entry,
    board row), in place, conservatively: a placeholder registered agent is dropped, a
    recognised agent service gets agent_is_service=True, and best_contact_name /
    best_contact_address are recomputed ONLY when they are a placeholder or the service (its
    name, its registered office). Everything else, legacy fields included, is left exactly as
    it is. Returns True when something changed."""
    if not isinstance(prof, dict):
        return False
    before = copy.deepcopy(prof)
    ra = prof.get("registered_agent")
    if isinstance(ra, str) and _is_placeholder(ra):
        del prof["registered_agent"]
    if prof.get("registered_agent") and not prof.get("agent_is_service") \
            and is_agent_service(prof["registered_agent"]):
        prof["agent_is_service"] = True
    name, addr = prof.get("best_contact_name"), prof.get("best_contact_address")
    bad_name = bool(name) and (_is_placeholder(name) or (
        prof.get("agent_is_service") and (name == ra or is_agent_service(name))))
    bad_addr = bool(addr) and (_is_placeholder(addr) or _is_service_address(prof, addr))
    if bad_name or bad_addr:
        new_name, new_addr = _best_contact(prof)
        if bad_name:
            if new_name:
                prof["best_contact_name"] = new_name
            else:
                prof.pop("best_contact_name", None)
            # the address that went with a rejected name goes with it
            bad_addr = bad_addr or (bool(addr) and addr in (prof.get("registered_office_address"),
                                                            prof.get("registered_mailing_address")))
        if bad_addr or (bad_name and new_addr and not prof.get("best_contact_address")):
            if new_addr:
                prof["best_contact_address"] = new_addr
            else:
                prof.pop("best_contact_address", None)
    return prof != before


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
                      Cloudflare block page, a profile page with no SOSID on it, a result
                      list with profile links that parse_search_results() could not read).
      ambiguous       names whose search ANSWERED with candidates but none of them is
                      confidently the searched entity (select_result(): no same-name result,
                      or a tie it cannot break). Nothing was opened or attached.
      ambiguous_detail  {name: select_result()'s detail} for those names: candidate count,
                      same-name count, reason, the first few candidates.
      breaker_tripped _BREAKER_FAILS errors in a row stopped the batch
      deadline_hit    the _MAX_SECONDS budget stopped the batch
      session_failed  the stealth session itself failed (nothing could be looked up)
      error           text of that session failure, if any

    THE BREAKER counts consecutive lookups that got no answer. It used to count an answered
    "no match" as a failure too, so six real misses in a row (normal: ~55% of names are not
    in the NC registry) stopped the batch. That is what happened on 2026-10-01 and 10-02:
    the same 7 names, the same 1 hit + 6 misses, both runs over in under a minute. A miss is
    the site answering, so it now resets the streak instead; so does an ambiguous answer.
    """
    out = outcome if outcome is not None else {}
    out.update({"attempted": 0, "resolved": [], "misses": [], "errors": [],
                "ambiguous": [], "ambiguous_detail": {},
                "breaker_tripped": False, "deadline_hit": False,
                "session_failed": False, "error": None})
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        out["session_failed"] = True
        out["error"] = "scrapling not installed"
        return {}

    results: dict = {}
    selection: dict = {}      # name -> select_result() detail (or {"verdict": "unparsed"})
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
                sel = selection.get(name) or {}
                if prof and prof.get("sosid"):
                    out["resolved"].append(name)
                    state["consec_fail"] = 0
                elif sel.get("verdict") == "ambiguous":
                    out["ambiguous"].append(name)  # answered, but no confident match
                    out["ambiguous_detail"][name] = sel
                    state["consec_fail"] = 0
                elif prof is None and sel.get("verdict") != "unparsed" \
                        and not await _looks_blocked(page):
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
        # Which hit IS the entity (module docstring, RESULT SELECTION): read the result list
        # already on screen -- no extra request -- instead of opening links[0].
        parsed = parse_search_results(await page.content())
        if not parsed["candidates"]:
            selection[name] = {"verdict": "unparsed", "links": len(links)}
            results[name] = None
            return
        pick, detail = select_result(name, parsed["candidates"])
        if parsed.get("records_found") is not None:
            detail["records_found"] = parsed["records_found"]
        selection[name] = detail
        if pick is None:
            results[name] = None
            return
        href = pick["profile_href"]
        await page.goto(href if href.startswith("http") else _BASE + href)
        await page.wait_for_load_state("networkidle", timeout=20000)
        text = await page.inner_text("body")
        prof = _parse_profile(text)
        prof["profile_url"] = page.url
        prof["match_count"] = len(links)
        prof["match_rule"] = MATCH_RULE
        prof["exact_matches"] = detail["exact"]
        if prof.get("sosid") and not names_match(name, prof.get("legal_name")):
            # the profile page itself names another entity: never attach it
            selection[name] = dict(detail, verdict="ambiguous", reason="profile_name_differs",
                                   top=[f"{_clean_text(prof.get('legal_name'))[:120]} "
                                        f"({prof.get('sosid')})"])
            results[name] = None
            return
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
