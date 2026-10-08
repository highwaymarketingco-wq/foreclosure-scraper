"""CourtListener bankruptcy filings scraper (NC W/M/E + SC bankruptcy courts).

Pulls Chapter 7, 11, 13 bankruptcy filings from the past 90 days for the
4 federal bankruptcy courts covering our footprint:
  - ncwb : NC Western District (Charlotte, Asheville, Statesville)
  - ncmb : NC Middle District (Greensboro, Winston-Salem, Durham)
  - nceb : NC Eastern District (Raleigh, Wilson, Greenville)
  - scb  : SC District (Columbia, Charleston, Spartanburg)

Why this matters for flippers: a Chapter 13 filer is usually trying to STOP a
state-court foreclosure with the automatic stay. ~30% of Ch.13 cases convert
to Ch.7 within 18 months, at which point the property is liquidated. These
are pre-foreclosure leads with even more lead time than NOD recordings.

Emission strategy: bankruptcy dockets do NOT carry debtor addresses (verified
via direct API probe — bankruptcy_information has chapter but no address).
So we emit every filing from these 4 courts as a state-level lead with the
debtor name as `defendant`. A county is tagged only when the debtor is an
ORGANIZATION named for its town (never from a person's name, which is a surname
that merely equals a place; see `_county_from_text`'s docstring). The
cross-reference enrichment in `enrichment_bankruptcy.py` then matches these
debtor names to existing foreclosure-listing defendants for the BIG-signal
join.

2026-09-23 (docs/coverage_gap_build_plan_2026-09-23.md item 3): county
attribution now covers all 146 NC+SC counties via
`_bankruptcy_city_to_county.py`, up from a hardcoded 21-county/~28-town
dict. All 4 federal bankruptcy districts already partition the entirety of
both states — every county's dockets were always being fetched — so this
is a pure attribution-gazetteer fix, zero new scraping or API calls.

Auth: FREE and ANONYMOUS-capable. The v4 /search/ endpoint answers without a
token; a token (free account) is sent when present purely to raise the rate
limit. See https://www.courtlistener.com/sign-up/ ->
https://www.courtlistener.com/profile/api/ -> echo "TOKEN" >
.secrets/courtlistener_token.txt (or env COURTLISTENER_TOKEN=...).

2026-08-02 TIMEOUT FIX (source had been failing with "exceeded soft timeout
900s" and returning nothing at all):

  ROOT CAUSE — an N+1 API call per docket. The /dockets/ endpoint does NOT
  carry the bankruptcy chapter, and for these three courts `cause` and
  `nature_of_suit` are empty strings, so the cheap text-mine ALWAYS failed and
  every docket fell through to a separate /bankruptcy-information/ fetch. With
  ~3,900 dockets in a 90-day window, and http_client's per-host throttle
  spacing every courtlistener.com request ~1.15s apart (concurrency cannot beat
  a per-host rate limiter), that is ~75 minutes of sequential calls. The
  700-lookup cap did not save it: 700 x 1.15s = ~805s, which already blows the
  900s soft timeout before the third court is even reached.

  FIX — pull from /search/?type=r instead. That endpoint returns `chapter`
  INLINE on every result (live probe 2026-08-02: 795/800 scb rows populated,
  99.4%), so the per-docket lookup disappears entirely. Cost is 20 results per
  page instead of 200, but 194 pages x ~1.7s = ~330s for all three courts with
  ZERO follow-up calls — comfortably inside the timeout, and it returns ~3,900
  dockets instead of 0. A wall-clock deadline bounds it regardless of how the
  courts grow.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import structlog

from ..._bankruptcy_city_to_county import KNOWN_CITIES, bankruptcy_county_for
from ...base_scraper import BaseScraper
from ...document_links import stamp_documents
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...signal_freshness import bankruptcy_case_age

log = structlog.get_logger()

API_BASE = "https://www.courtlistener.com/api/rest/v4"
COURTS = ("ncwb", "ncmb", "nceb", "scb")
LOOKBACK_DAYS = 90
# /search/ hard-caps page_size at 20 regardless of what we ask for (verified:
# page_size=100 and page_size=200 both return 20). Pages are cheap because each
# one already carries the chapter, so no follow-up call is needed.
SEARCH_PAGE_SIZE = 20
# ~1,600 dockets/court/90d today -> ~80 pages. 200 leaves 2.5x headroom.
MAX_SEARCH_PAGES_PER_COURT = int(os.environ.get("BANKRUPTCY_MAX_PAGES", "200"))
# /dockets/ page size + page cap. No longer used by THIS scraper, but
# courtlistener_civil imports both — leave them at their original values.
PAGE_SIZE = 200
MAX_PAGES_PER_COURT = 10
# Hard wall-clock budget for the whole pass, well under timeout_s. Results are
# ordered newest-first, so running out of budget drops the OLDEST filings.
# 2026-10-08 (source-completeness audit): 600 -> 780 and shared fairly between
# the courts (see fetch()). Measured live 2026-10-08: the 90-day corpus is
# ncwb 811 + ncmb 670 + nceb 1,498 + scb 1,600 = 4,579 dockets (229 pages at
# 20/page, ~2.0-2.4 s per page from this host), and the gated run of
# 2026-10-08 stopped at exactly 600 s with 3,386 rows: the budget bound, and
# because the courts ran in order the whole cut fell on scb (SC), the last one.
FETCH_BUDGET_S = float(os.environ.get("BANKRUPTCY_BUDGET_S", "780"))
# Attempts per search page before abandoning the court.
_PAGE_RETRIES = 3


def _load_token() -> str | None:
    tok = os.environ.get("COURTLISTENER_TOKEN") or os.environ.get("COURTLISTENER_API_TOKEN")
    if tok:
        return tok.strip()
    f = Path(".secrets/courtlistener_token.txt")
    if f.exists():
        try:
            return f.read_text().strip()
        except Exception:
            return None
    return None


# Court → default state (so listings always carry at least state). Every
# docket's state is authoritative from the court it was filed in (a debtor
# files in the district covering where they live), so a city keyword found
# in the case name is used ONLY to recover the COUNTY within that state --
# never to override the state itself. (This also fixes a latent bug: the
# old CITY_TO_COUNTY dict returned its own hardcoded state per keyword,
# which for a shared name like "Clinton" -- a real town in BOTH Sampson
# County NC and Laurens County SC -- meant an ncwb/ncmb/nceb docket
# mentioning "Clinton" could have had its state silently flipped to SC.)
COURT_STATE = {"ncwb": "NC", "ncmb": "NC", "nceb": "NC", "scb": "SC"}


# Corporate-form markers: the ONLY positive evidence that a case name is an
# organization rather than a person. Deliberately narrow: "Trust", "Estate of",
# "Church", "Farms", "Plumbing" and the like also name individuals' family
# trusts, estates and sole proprietorships, so they are NOT evidence (a name
# with no corporate-form marker is treated as a person or as unknown).
# "Co", "P.A." and "P.C." count only in their punctuated, capitalised written
# form, because bare "Co", "Pa" and "Pc" are also real given names and surnames.
_ORG_FORM_RE = re.compile(
    r"(?<![A-Za-z])(?:l\.?l\.?c|l\.?l\.?l\.?p|l\.?l\.?p|l\.?p|p\.?l\.?l\.?c|p\.?l\.?l\.?p|"
    r"inc|incorporated|corp|corporation|company|ltd|limited)(?![A-Za-z])",
    re.I,
)
_ORG_FORM_PUNCT_RE = re.compile(r"(?<![A-Za-z])(?:Co|P\.A|P\.C)\.")

# A true adversary-proceeding caption, "<Plaintiff> v. <Defendant>". CASE-SENSITIVE
# on purpose: CourtListener writes the connector in lower case ("v." / "vs."),
# while an upper-case "V." is a middle initial ("Jane V. Doe"), a person's name.
# Measured on the published board (2026-10-06): 110 lower-case captions, and 6
# debtor names with a "V." middle initial that a case-insensitive match would
# have split into a fake plaintiff and defendant.
_ADVERSARY_CAPTION_RE = re.compile(r"\s(?:v|vs)\.\s")


def _is_adversary_caption(case_name: str | None) -> bool:
    """True for an adversary-proceeding caption ("<Plaintiff> v. <Defendant>").

    Such a docket is not a debtor's petition: it is a lawsuit INSIDE a
    bankruptcy (a trustee suing a lender, a creditor contesting a discharge,
    ...), and neither party is known to be the person who filed. Measured on the
    110 published captions: 37 have a trustee, committee or bankruptcy
    administrator as plaintiff, 66 name an organization on the second side, and
    the debtor is sometimes the plaintiff (student-loan dischargeability suits)
    and sometimes the defendant, so a "Debtor:" label is wrong half the time."""
    return bool(case_name) and bool(_ADVERSARY_CAPTION_RE.search(case_name))


def _is_organization(name: str) -> bool:
    """True only on positive corporate-form evidence (LLC, Inc, Corp, Ltd, ...)."""
    return bool(_ORG_FORM_RE.search(name.replace(".", ""))
                or _ORG_FORM_PUNCT_RE.search(name))


def _county_from_text(text: str, state: str) -> str | None:
    """County recovered from a city word in a case name, scoped to the docket's
    ALREADY-KNOWN state (from COURT_STATE) so a same-named town in the other
    state is never consulted. Covers all 146 NC+SC counties via
    _bankruptcy_city_to_county.py -- see that module's docstring for how it
    handles cross-state/cross-county name collisions (Camden, Columbia,
    Greenville, Henderson, Clinton, etc.).

    A bankruptcy docket's case name is the DEBTOR'S name, not an address. A
    town word in it is a location hint ONLY when the debtor is an organization
    named for its town ("Acme Widgets of Raleigh, Inc."). For a person it is a
    surname or given name that happens to equal a place ("Wilson", "Marion",
    "Jackson", "Clinton", "Charlotte"): the county that produced was unrelated to
    where they live. Measured 2026-10-06 against the published board: of the 147
    bankruptcy rows whose county came from this function, 123 matched a whole
    word in a person's name, 15 matched inside a longer word, and only 3 were an
    organization; 110 carried no street or parcel at all (their county was
    nothing but that word) and 34 carried a parcel pinned at that wrong county's
    point. So:

      * a person, or a name with no corporate-form marker: never (None);
      * a two-party caption ("A v. B"): never -- which party is the debtor is
        unknown;
      * an organization: the town must be a WHOLE word (never the middle of
        "Vanderson" or "Camdenton"), and every whole-word town in the
        name must agree on one county, else None. A missing county is far
        better than a wrong one.
    """
    if not text or not state:
        return None
    if _is_adversary_caption(text):
        return None
    name = _IN_RE_RE.sub("", text).strip()
    if not name or not _is_organization(name):
        return None
    counties = {
        county
        for city in KNOWN_CITIES
        if re.search(r"(?<![A-Za-z])" + re.escape(city) + r"(?![A-Za-z])", name, re.I)
        and (county := bankruptcy_county_for(city, state))
    }
    # "North Charleston" also contains the whole word "Charleston": today every
    # such nested pair maps to one county, and a future pair that did not would
    # land here as a disagreement, i.e. None -- the safe direction.
    return next(iter(counties)) if len(counties) == 1 else None


# A CourtListener case_name is NOT always "In re <Debtor>" — the /search/
# endpoint's RECAP results for a bankruptcy COURT also surface true adversary-
# proceeding-style captions, "<Plaintiff> v. <Defendant>" (live-verified
# 2026-10-01 against ncwb: "Taylor v. Honeycutt", "United States v. Bingham").
# The old code dumped the WHOLE case_name into `defendant` -- the field nearly
# every name-resolution enricher reads as "the person to search"
# (enrichment_free_phones, enrichment_probate_search, enrichment_nc_doj,
# enrichment_resolve_name_to_property, ...) -- so a two-party caption became a
# single nonsense name ("United States v. Bingham"), and worse: when a
# mortgage servicer or federal agency is itself the captioned party, that
# institution's own name could land where a homeowner's name belongs
# (extraction_gaps.md: "servicer/GSE as owner_name ... SERVICEMAC/FNMA/
# case-caption"). Split the caption, and never let an institution occupy a
# name-resolution field regardless of which side of "v." it was on.
_CAPTION_RE = re.compile(r"^(.*?)\s+(?:v|vs)\.\s+(.*)$")  # case-sensitive: see _ADVERSARY_CAPTION_RE
_IN_RE_RE = re.compile(r"^\s*in\s+re[:\s]+", re.I)
_CAPTION_ETAL_RE = re.compile(r"\bet\.?\s*al\.?\b.*$", re.I)
_INSTITUTION_RE = re.compile(
    r"\b(mortgage|\bbank\b|n\.?a\.?\b|servicing|financial\s+corp|funding\s+(?:llc|corp)|"
    r"capital\s+(?:llc|corp)|credit\s+union|trust\s+co(?:mpany)?|"
    r"federal\s+national\s+mortgage|federal\s+home\s+loan\s+mortgage|"
    r"fannie\s+mae|freddie\s+mac|\bfnma\b|\bfhlmc\b|\bfdic\b|\bhud\b|"
    r"united\s+states(?:\s+of\s+america)?|department\s+of\b|internal\s+revenue|"
    # Named mortgage servicers/GSEs that carry no generic keyword of their own
    # (a brand like "NewRez" or "ServiceMac" would otherwise slip the keyword
    # gate above) -- live-verified 2026-10-01 against a real federal
    # real-property caption, "Washington v. NewRez, LLC". Not exhaustive; the
    # keyword gate above catches most new ones ("X Mortgage LLC", "Y Bank").
    r"servicemac|newrez|nationstar|\bocwen\b|pennymac|carrington\s+mortgage|"
    r"rushmore\s+loan|selene\s+finance|freedom\s+mortgage|\bloancare\b|"
    r"specialized\s+loan\s+servicing|\bshellpoint\b|\bphh\b|\bcenlar\b|"
    r"\bflagstar\b|planet\s+home\s+lending|\bditech\b|lakeview\s+loan|"
    r"select\s+portfolio\s+servicing|fay\s+servicing|\bmidfirst\b|"
    r"mr\.?\s*cooper|wells\s+fargo|jpmorgan|\bchase\b|deutsche\s+bank|"
    r"citimortgage|\bcitibank\b|\bpnc\b|\bsuntrust\b|\btruist\b|\bhsbc\b|"
    r"wilmington\s+(?:savings|trust)|\bmers\b|mortgage\s+electronic\s+registration)\b",
    re.I,
)


def _is_institution(name: str | None) -> bool:
    """True when `name` looks like a bank / servicer / GSE / government party
    rather than an individual — such a name must never be treated as the
    owner/debtor to search."""
    return bool(name) and bool(_INSTITUTION_RE.search(name))


def _split_caption(case_name: str | None) -> tuple[str | None, str | None]:
    """(plaintiff, defendant) parsed from a CourtListener case_name.

    Handles both real shapes this feed returns: a true two-party caption
    ("<Plaintiff> v. <Defendant>") and a plain bankruptcy caption ("In re
    <Debtor>", no "v." at all — the common case, left exactly as the old
    code's behavior for it). An institution is never returned on either side
    of a name-resolution field.
    """
    text = (case_name or "").strip()
    if not text:
        return None, None
    m = _CAPTION_RE.match(text)
    if not m:
        debtor = _IN_RE_RE.sub("", text).strip() or None
        return None, (None if _is_institution(debtor) else debtor)
    plaintiff = m.group(1).strip(" ,.") or None
    defendant = _CAPTION_ETAL_RE.sub("", m.group(2)).strip(" ,.") or None
    if _is_institution(plaintiff):
        plaintiff = None
    if _is_institution(defendant):
        defendant = None
    return plaintiff, defendant


def _chapter_from_text(*texts: str) -> str:
    blob = " ".join(t.lower() for t in texts if t)
    for kw, ch in (
        ("chapter 7", "7"),
        ("chapter 11", "11"),
        ("chapter 13", "13"),
        ("ch.7", "7"),
        ("ch.11", "11"),
        ("ch.13", "13"),
        ("ch 7", "7"),
        ("ch 11", "11"),
        ("ch 13", "13"),
    ):
        if kw in blob:
            return ch
    return "?"


async def _fetch_chapter(c, docket: dict, token: str) -> str:
    """Fetch chapter from the bankruptcy_information endpoint when available.
    Falls back to text-mining cause/nature_of_suit. Best-effort, never raises.
    """
    bi_url = docket.get("bankruptcy_information")
    if bi_url and isinstance(bi_url, str):
        try:
            r = await c.get(
                bi_url,
                headers={"Authorization": f"Token {token}", "Accept": "application/json"},
                timeout=10.0,
            )
            if r.status_code == 200:
                bi = r.json()
                ch = bi.get("chapter")
                if ch:
                    return str(ch).strip()
        except Exception:
            pass
    return _chapter_from_text(docket.get("cause"), docket.get("nature_of_suit"))


def _auth_headers(token: str | None) -> dict:
    """Token is OPTIONAL — /search/ answers anonymously; the header only raises
    the rate limit when a free account token is configured."""
    h = {"Accept": "application/json"}
    if token:
        h["Authorization"] = f"Token {token}"
    return h


def _recap_pdf_urls(hit: dict) -> list[str]:
    """Free, already-archived PDF URLs off a /search/?type=r hit's nested
    `recap_documents[]`.

    Found 2026-10-04 (national.* extraction-completeness audit, batch 15):
    every recap_documents[] entry carries `is_available` + `filepath_local`,
    but neither was ever read -- this scraper (and its civil/adversary
    siblings) kept only text metadata (short_description etc.), discarding
    the one field that says whether a REAL document exists. Live-verified:
    `is_available=True` + a `filepath_local` means CourtListener already
    holds that PACER document for free in the public RECAP archive (someone
    else already paid PACER and donated it) at
    `https://storage.courtlistener.com/<filepath_local>` -- confirmed live
    2026-10-04 with a direct fetch (200, `application/pdf`, real PDF bytes).
    Sampled across all 4 courts x the adversary scraper's 3 phrases: 42 of
    199 recap_documents (21%) qualify -- lift-stay motions, orders, §363
    sale motions, the exact documents HERMES sec 8 calls "THE most common
    miss." The remaining 79% have `is_available=False` (CourtListener does
    NOT have a free copy) -- deliberately NOT fetched, since getting one
    would mean buying it from PACER (out of scope, HERMES rule 1 FREE-only).
    """
    urls: list[str] = []
    for rd in hit.get("recap_documents") or []:
        if not isinstance(rd, dict):
            continue
        fp = rd.get("filepath_local")
        if rd.get("is_available") and fp:
            urls.append(f"https://storage.courtlistener.com/{fp}")
    return urls


def _normalize_search_hit(hit: dict, court: str) -> dict:
    """Map a /search/?type=r result onto the docket shape the rest of this
    module (and its tests) already speak, carrying `chapter` through inline."""
    absolute_url = hit.get("docket_absolute_url") or ""
    return {
        "case_name": hit.get("caseName") or hit.get("case_name_full") or "",
        "docket_number": hit.get("docketNumber") or "",
        "date_filed": hit.get("dateFiled"),
        "absolute_url": absolute_url,
        "cause": hit.get("cause") or "",
        "nature_of_suit": hit.get("suitNature") or "",
        "chapter": (hit.get("chapter") or "").strip(),
        "court_id": hit.get("court_id") or court,
        "docket_id": hit.get("docket_id"),
        "trustee": hit.get("trustee_str") or "",
        "party": hit.get("party"),
        "attorney": hit.get("attorney") or hit.get("attorney_str") or "",
        "firm": hit.get("firm") or hit.get("firm_str") or "",
        "date_terminated": hit.get("dateTerminated"),
        "pacer_case_id": hit.get("pacer_case_id"),
        # 2026-10-04 fix (see _recap_pdf_urls docstring): free RECAP PDF
        # URLs for this docket's documents, if any are already archived.
        "recap_pdfs": _recap_pdf_urls(hit),
    }


async def _fetch_court(c, court: str, token: str | None, deadline: float | None = None) -> list[dict]:
    """Pull recent bankruptcy dockets from one court, paginated.

    Uses the v4 /search/ endpoint (type=r = RECAP dockets) because it returns
    the bankruptcy `chapter` inline — the /dockets/ endpoint does not, and the
    per-docket chapter lookup it forced is what blew the soft timeout. Ordered
    newest-first so a budget cut-off sheds the oldest filings, not the freshest.
    """
    cutoff = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    out: list[dict] = []
    next_url: str | None = (
        f"{API_BASE}/search/?type=r&court={court}&filed_after={cutoff}"
        f"&page_size={SEARCH_PAGE_SIZE}&order_by=dateFiled%20desc"
    )
    headers = _auth_headers(token)
    page = 0
    while next_url and page < MAX_SEARCH_PAGES_PER_COURT:
        if deadline is not None and time.monotonic() > deadline:
            log.warning("courtlistener.budget_exhausted", court=court,
                        pages=page, rows=len(out))
            break
        # A single dropped page used to abandon the whole court (live smoke:
        # ncwb bailed after page 1 on a bare ReadTimeout and yielded 20 of 767
        # rows). Retry the page before giving up.
        data = None
        for attempt in range(_PAGE_RETRIES):
            try:
                r = await c.get(next_url, headers=headers)
                if r.status_code != 200:
                    log.warning("courtlistener.error", court=court, status=r.status_code)
                    break
                data = r.json()
                break
            except Exception as exc:  # noqa: BLE001 — transient network/read timeout
                log.warning("courtlistener.fetch_error", court=court, page=page,
                            attempt=attempt + 1,
                            error=f"{type(exc).__name__}: {str(exc)[:100]}")
                if attempt + 1 < _PAGE_RETRIES:
                    await asyncio.sleep(2.0 * (attempt + 1))
        if data is None:
            break
        for hit in data.get("results") or []:
            out.append(_normalize_search_hit(hit, court))
        next_url = data.get("next")
        page += 1
    return out


class CourtListenerBankruptcy(BaseScraper):
    slug = "national.courtlistener_bankruptcy"
    name = "CourtListener Bankruptcy (NC W/M/E + SC, Ch 7/11/13)"
    category = "national_aggregator"
    expected_min_count = 0  # graceful when the API is unreachable
    requires_apify = False
    # /search/ carries the chapter inline, so the pass is pure pagination
    # (~330s for all three courts). FETCH_BUDGET_S cuts it off well before this
    # ceiling; the ceiling only exists so a slow network can't trip the alarm.
    timeout_s = 1020.0

    async def fetch(self) -> Iterable[Listing]:
        # Token is optional: /search/ answers anonymously. When present it only
        # buys a higher rate limit, so a missing token is no longer fatal.
        token = _load_token()
        if not token:
            log.info("courtlistener.no_token",
                     hint="running anonymously; a free token raises the rate limit")

        out: list[Listing] = []
        chapter_lookups = 0
        # Chapter now arrives inline on ~99% of rows. This bounded fallback only
        # covers the handful that come back blank (adversary proceedings etc).
        MAX_CHAPTER_LOOKUPS = int(os.environ.get("BANKRUPTCY_CHAPTER_LOOKUPS", "50"))
        deadline = time.monotonic() + FETCH_BUDGET_S

        # Dedup tracker — CourtListener pagination occasionally returns the
        # same docket twice (cursor-based with overlap on edits, and /search/
        # can surface one docket under several matching documents). Without
        # this guard the audit measured 181 duplicate case_numbers per run.
        # Key is (court, docket_no) — same docket# across different courts
        # is legitimate and must NOT be deduped (NCWB 26-02017 is a
        # different case from NCEB 26-02017).
        seen_keys: set[tuple[str, str]] = set()
        dedup_dropped = 0
        # Adversary-proceeding captions ("<Plaintiff> v. <Defendant>") are not
        # debtor petitions -- see _is_adversary_caption. Counted, not emitted.
        adversary_skipped = 0

        async with client(timeout=45.0) as c:
            for court_idx, court in enumerate(COURTS):
                # Fair share of what is left of the budget: a court that finishes
                # early hands its unused time to the next one, and no court can
                # starve the ones after it (before 2026-10-08 the last court, scb,
                # took the whole cut whenever the budget bound).
                now = time.monotonic()
                court_deadline = now + max(0.0, deadline - now) / (len(COURTS) - court_idx)
                dockets = await _fetch_court(c, court, token, court_deadline)
                state_default = COURT_STATE.get(court, "NC")

                for d in dockets:
                    case_name = d.get("case_name") or ""
                    docket_no = d.get("docket_number") or ""
                    if not case_name and not docket_no:
                        continue

                    # This source's job is a PERSON'S OWN petition (the signal is
                    # "this owner filed"). An adversary proceeding is a lawsuit
                    # inside someone's bankruptcy: it says nothing about whether
                    # either named party filed, and its second party is often a
                    # lender, vendor or insurer rather than a distressed owner.
                    # The /search/ feed mixes them in (measured 2026-10-06: 110
                    # of 4,779 published rows, 84 with no county), where they
                    # used to publish as "Debtor: <caption>" bankruptcy leads.
                    # The lift-stay / sec.363 / abandonment motions that matter
                    # for real property are the separate national.courtlistener_
                    # adversary scraper's job, and it works on the main
                    # "In re <Debtor>" dockets, not on these captions.
                    if _is_adversary_caption(case_name):
                        adversary_skipped += 1
                        continue

                    # Skip duplicates within the same scrape pass.
                    if docket_no:
                        key = (court, docket_no.strip())
                        if key in seen_keys:
                            dedup_dropped += 1
                            continue
                        seen_keys.add(key)

                    # State is authoritative from the court (a debtor files where
                    # they live); a city keyword in the case name only ever
                    # recovers the COUNTY within that state (rare hit; mostly None).
                    state = state_default
                    county = _county_from_text(case_name, state)

                    # Chapter detection. /search/ hands it to us inline, which is
                    # the whole point of the endpoint switch — Ch.13 = trying to
                    # stop a foreclosure, Ch.7 = liquidation. Fall back to the
                    # cheap text-mine, then (rarely, and bounded) to the
                    # bankruptcy_information sub-resource.
                    chapter = (d.get("chapter") or "").strip()
                    if not chapter or chapter == "?":
                        chapter = _chapter_from_text(d.get("cause"), d.get("nature_of_suit"))
                    if chapter == "?" and chapter_lookups < MAX_CHAPTER_LOOKUPS:
                        chapter = await _fetch_chapter(c, d, token)
                        chapter_lookups += 1

                    date_filed = d.get("date_filed")
                    desc = (
                        f"Ch.{chapter} bankruptcy filed {date_filed or '?'} ({court.upper()}) "
                        f"— Debtor: {case_name[:160]}"
                    )

                    # Case age / "still open a long time" flag (Tier B #28: "bankruptcies
                    # open 10-15 years are the strongest variant"). This scraper only ever
                    # pulls the last LOOKBACK_DAYS=90 days of FILINGS, so is_long_open will
                    # always be False on rows it emits itself (a case filed 90 days ago
                    # cannot also be 10 years old) — computed anyway, from data already
                    # captured, so the field exists and is correct if this scraper's window
                    # is ever widened. The actual 10-15-year-old discovery path is
                    # enrichment_bankruptcy.py's long-open cross-reference query, which
                    # looks at a completely different (old) filing window.
                    age_flags = bankruptcy_case_age(
                        {"date_filed": date_filed, "date_terminated": d.get("date_terminated")}
                    )

                    # Split the caption so a two-party case_name doesn't become
                    # one nonsense `defendant`, and so a bank/servicer/GSE/
                    # government party never lands in a name-resolution field.
                    cap_plaintiff, cap_defendant = _split_caption(case_name)

                    li = Listing(
                        source=self.slug,
                        source_url=("https://www.courtlistener.com" + d["absolute_url"]) if d.get("absolute_url") else "",
                        listing_type=ListingType.BANKRUPTCY,  # 2026-06-19: was mislabeled LIS_PENDENS
                        property_kind=PropertyKind.UNKNOWN,
                        state=state,
                        county=county,
                        case_number=docket_no,
                        plaintiff=cap_plaintiff[:200] if cap_plaintiff else None,
                        defendant=cap_defendant[:200] if cap_defendant else None,
                        trustee=d.get("trustee") or None,  # §363 seller / disposition trustee
                        description=desc,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={
                            "courtlistener": {
                                "court": court,
                                "docket_number": docket_no,
                                "chapter": chapter,
                                "case_name": case_name,
                                "date_filed": date_filed,
                                "nature_of_suit": d.get("nature_of_suit"),
                                "cause": d.get("cause"),
                                "absolute_url": d.get("absolute_url"),
                                "bankruptcy_information": d.get("bankruptcy_information"),
                                "docket_id": d.get("docket_id"),
                                "trustee": d.get("trustee") or None,
                                "party": d.get("party") or None,  # joint filers = co-owners
                                "attorney": d.get("attorney") or None,
                                "firm": d.get("firm") or None,
                                "date_terminated": d.get("date_terminated"),
                                "pacer_case_id": d.get("pacer_case_id"),
                                **age_flags,
                            },
                        },
                    )
                    # 2026-10-04 fix: wire any free RECAP PDFs already
                    # archived for this docket (see _recap_pdf_urls).
                    stamp_documents(li, d.get("recap_pdfs") or [])
                    out.append(li)

        log.info(
            "courtlistener.done",
            listings=len(out),
            courts=len(COURTS),
            lookback_days=LOOKBACK_DAYS,
            chapter_api_lookups=chapter_lookups,
            dedup_dropped=dedup_dropped,
            adversary_captions_skipped=adversary_skipped,
        )
        return out
