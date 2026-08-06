"""SC "Notice to Creditors" probate notices published in county newspapers.

WHY THIS IS THE STRONGEST PROBATE SIGNAL AVAILABLE FOR FREE IN SC
    SC PublicIndex, the actual probate docket, is ToS-walled (Rule 610) and is
    deliberately not automated by this engine. But SC Probate Code 62-3-801
    REQUIRES every estate to publish a Notice to Creditors in a county
    newspaper, and those papers put it on the open web. The notice carries, in
    plain text, exactly what the docket would have given us:

        Estate:                 the decedent (the owner of record)
        Date of Death:          when the property changed hands
        Case Number:            the real probate case, e.g. 2026ES3900446
        Personal Representative + Address: who to contact, and where

    A decedent's name plus a live case number is what the name->property
    resolver needs to pin the parcel, and the PR address is the mailing spine.

THE CASE NUMBER CARRIES THE COUNTY — so attribution is derived, never assumed
    An SC estate number is YYYY + "ES" + a two-digit COUNTY code + a sequence.
    2026ES1100303 is Cherokee (11); 2026ES3900446 is Pickens (39). County is
    read out of the case number rather than inferred from which paper ran the
    notice, so a Cherokee paper carrying a Spartanburg estate files correctly.
    An unrecognised code means out of footprint, and the row is dropped.

THREE PAPERS, THREE FIELD DIALECTS — all of them real, none of them documented
    Pickens   "Estate:"     "Date of Death: 5/30/2026"  "Personal Representative:"
    Cherokee  "Estate:"     "Death: 06/19/2026"         "PR:"
    Laurens   "ESTATE OF:"  "Date of Death: May 10, 2026" (spelled-out month)

    Cherokee also puts the PR address on bare unlabelled lines with no
    "Address:" prefix, so the address reader falls back to the first line that
    starts with a house number and then takes the "City, ST ZIP" line under it.

WHY THE HOSTS DIFFER IN ACCESS PATH
    Pickens and Laurens publish notices as ordinary WordPress posts, so the
    posts endpoint returns the body directly. The Gaffney Ledger files them
    under a custom post type whose REST route 404s and whose oht_article route
    returns 403. We do not go around that. We read the ordinary public article
    page instead, which is the same page a reader opens, and discover which
    pages to read through the site's own public search endpoint.

WP SEARCH IS FUZZY, so the phrase match is what actually filters
    /wp-json/wp/v2/search scores loose OR matches: searching "personal
    representative" on the Gaffney Ledger returns a story about a personal art
    collection. The reported totals in the hundreds are meaningless. Every body
    is confirmed to contain the literal phrase "notice to creditors" before a
    single lead is made, and every lead needs a well-formed ES case number.

PII POSTURE
    The PR name and mailing address are the operative content of a notice whose
    entire statutory purpose is public notification, and are the same class of
    data as the court record itself. There is no phone number, no SSN and no
    date of birth here, and none is sought.

ROBOTS, checked 2026-08-06
    All three allow this. Mitchell/Drupal-style /search/ paths are disallowed on
    some upstate papers, so discovery never uses a site's /search/ HTML page,
    only the JSON API and the article pages themselves.
"""
from __future__ import annotations

import asyncio
import html as _html
import os
import re
from datetime import datetime, timedelta
from typing import Iterable, NamedTuple, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


def body_text(raw: str) -> str:
    """HTML -> text, PRESERVING line breaks.

    The shared strip_html() collapses everything to spaces, which cannot be used
    here: these notices put the representative's name and the address on the
    lines FOLLOWING their labels, so losing <br> loses the field association.
    """
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw or "")
    t = re.sub(r"(?i)<(?:br\s*/?|/p|/div|/h\d|/li|/tr)>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = _html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)

#: Two-digit SC county codes as they appear inside an ES case number. Only the
#: footprint is listed; anything else is out of scope and dropped.
SC_COUNTY_CODE = {
    "04": "Anderson", "11": "Cherokee", "30": "Laurens",
    "37": "Oconee", "39": "Pickens", "42": "Spartanburg", "44": "Union",
}

#: How far back to read. Estates older than this are closed or cold.
LOOKBACK_DAYS = int(os.environ.get("FORECLOSURE_SC_PROBATE_LOOKBACK_DAYS", "550"))
#: Bound on article pages fetched per paper, so one paper cannot run away.
MAX_DOCS = int(os.environ.get("FORECLOSURE_SC_PROBATE_MAX_DOCS", "120"))

SEARCH_TERMS = ("notice+to+creditors", "estate+notice")


class Paper(NamedTuple):
    county_hint: str          # only for logging; real county comes from the case number
    host: str
    mode: str                 # "posts" = body inline, "search_html" = fetch the article page


PAPERS: tuple[Paper, ...] = (
    Paper("Pickens", "www.yourpickenscounty.com", "posts"),
    Paper("Laurens", "www.laurenscountyadvertiser.net", "posts"),
    Paper("Cherokee", "www.gaffneyledger.com", "search_html"),
)

_PHRASE = re.compile(r"notice\s+to\s+creditors", re.I)
# "Estate:" (Pickens/Cherokee) or "ESTATE OF:" (Laurens).
_SPLIT = re.compile(r"(?=\bESTATES?\s+OF\s*:|\bEstate\s*:)", re.I)
_NAME = re.compile(r"\bESTATES?\s+OF\s*:\s*(.+)|\bEstate\s*:\s*(.+)", re.I)
_CASE = re.compile(r"\bCase\s*(?:Number|No\.?|#)?\s*:?\s*(\d{4}\s?ES\s?\d{5,10})", re.I)
_DEATH = re.compile(
    r"\b(?:Date\s+of\s+Death|Death)\s*:?\s*("
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|(?:January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+\d{1,2},?\s*\d{4})", re.I)
_PR = re.compile(
    r"\b(?:Co-?Personal\s+Representatives?|Personal\s+Representatives?|PR)\s*:?\s*(.*)", re.I)
_ADDR_LABEL = re.compile(r"\bAddress\s*:\s*(.+)", re.I)
# A street line starts with a house number, but plenty of representatives give
# only a PO box, which has no house number and would otherwise be skipped.
_STREET = re.compile(r"^(?:\d+\s+\S|P\.?\s?O\.?\s+Box\b|Post\s+Office\s+Box\b)", re.I)
#: "Feb11,18,25" — the run of publication dates that closes each notice. It sits
#: where a name would sit and is not one.
_PUBRUN = re.compile(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d",
                     re.I)
_CITY = re.compile(r"^[A-Za-z .'\-]+,\s*[A-Z]{2}\.?\s*\d{5}")
#: A stray copy of the case-number tail sometimes rides along on the estate line
#: ("Estate: Ethel J. Hamrick 276" beside case 2026ES1100276). That is in the
#: published text, not a parsing fault, so it is trimmed rather than tolerated.
_TAIL_NUM = re.compile(r"\s+\d{2,6}$")
_LABELS = re.compile(r"\b(?:Date\s+of\s+Death|Death|Case|Address|Published)\b", re.I)


def _clean_name(s: str, case: str) -> Optional[str]:
    # Strip trailing separators but NOT a trailing period: it belongs to the
    # name in "Brouillette Jr." and in initials, and dropping it silently
    # rewrites the very string the name->property resolver matches on.
    name = re.sub(r"\s+", " ", s).strip(" ,:;-")
    m = _TAIL_NUM.search(name)
    if m and case.endswith(m.group(0).strip()):
        name = name[: m.start()].strip(" .,")
    if len(name) < 4 or len(name) > 90 or name.replace(" ", "").isdigit():
        return None
    return name


def _pr_and_address(chunk: str) -> tuple[Optional[str], Optional[str]]:
    lines = [ln.strip() for ln in chunk.splitlines()]
    pr: Optional[str] = None
    pr_idx = -1
    for i, ln in enumerate(lines):
        m = _PR.search(ln)
        if not m:
            continue
        pr_idx = i
        tail = (m.group(1) or "").strip(" .,:")
        # Pickens puts the name on the NEXT line; the others keep it inline.
        took_next = False
        if not tail or _LABELS.search(tail):
            tail = lines[i + 1].strip(" .,:") if i + 1 < len(lines) else ""
            pr_idx, took_next = i + 1, True
        # Guard against the two things that sit where a name sits and are not
        # names: the closing publication-date run, and a bare PO box.
        if (tail and not _LABELS.search(tail) and 3 < len(tail) <= 70
                and not _PUBRUN.match(tail) and not _STREET.match(tail)):
            pr = re.sub(r"\s+", " ", tail)
        elif took_next:
            # The line after the label was NOT a name (a PO box, or the closing
            # publication run). Give it back, because a PO box is the address.
            pr_idx = i
        break

    addr, start = None, pr_idx + 1
    for i in range(max(start, 0), len(lines)):
        m = _ADDR_LABEL.search(lines[i])
        if m:
            addr, start = m.group(1).strip(), i + 1
            break
        if _STREET.match(lines[i]):        # Cherokee: no "Address:" label at all
            addr, start = lines[i], i + 1
            break
    if not addr:
        return pr, None
    # The "City, ST ZIP" line usually sits directly under the street line.
    for i in range(start, min(start + 3, len(lines))):
        if _CITY.match(lines[i]):
            addr = f"{addr.rstrip(' ,')}, {lines[i]}"
            break
    return pr, re.sub(r"\s+", " ", addr).strip(" ,")


def parse_estates(body: str) -> list[dict]:
    """Pull every estate block out of one notice page. Pure, so it is testable."""
    if not _PHRASE.search(body or ""):
        return []                          # fuzzy search hit, not an actual notice
    out: list[dict] = []
    seen: set[str] = set()
    for chunk in _SPLIT.split(body)[1:]:
        nm = _NAME.search(chunk)
        cs = _CASE.search(chunk)
        if not nm or not cs:
            continue
        case = re.sub(r"\s+", "", cs.group(1)).upper()
        county = SC_COUNTY_CODE.get(case[6:8]) if case[4:6] == "ES" else None
        if not county:
            continue                       # outside the footprint
        name = _clean_name(nm.group(1) or nm.group(2) or "", case)
        if not name or case in seen:
            continue
        seen.add(case)
        d = _DEATH.search(chunk)
        pr, addr = _pr_and_address(chunk)
        out.append({"estate": name, "case_number": case, "county": county,
                    "date_of_death": d.group(1) if d else None,
                    "personal_representative": pr, "pr_address": addr})
    return out


def _to_listing(e: dict, source_url: str, slug: str) -> Listing:
    now = datetime.utcnow()
    bits = [e["estate"], e["case_number"]]
    if e.get("date_of_death"):
        bits.append(f"d. {e['date_of_death']}")
    return Listing(
        source=slug,
        source_url=source_url,
        listing_type=ListingType.PROBATE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC", county=e["county"],
        # No situs is published. The decedent name plus case number is what the
        # name->property resolver pins the parcel with, exactly as the obituary
        # and heir-estate sources do.
        owner_name=e["estate"], defendant=e["estate"],
        case_number=e["case_number"],
        foreclosure_process="probate",
        description=f"{e['county']} SC probate — Notice to Creditors — "
                    f"{' | '.join(bits)}"[:300],
        first_seen=now, last_seen=now,
        raw={
            "sc_probate_notice": {k: v for k, v in e.items() if v},
            "life_event": "death",
            "relationship_signal": {"kind": "probate",
                                    "keyword": "notice to creditors"},
            # The PR is the contact of record for the estate.
            "owner_mailing": ({"mailing": e["pr_address"],
                               "addressee": e.get("personal_representative")}
                              if e.get("pr_address") else {}),
        },
    )


async def _json(c, url: str):
    r = await c.get(url, timeout=60.0)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {url}")
    try:
        return r.json()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"non-JSON response from {url}") from exc


async def _fetch_paper(c, paper: Paper) -> list[Listing]:
    after = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT00:00:00")
    slug = f"counties_sc.sc_probate_notices.{paper.host.replace('www.', '').split('.')[0]}"
    docs: list[tuple[str, str]] = []       # (url, body text)

    if paper.mode == "posts":
        for term in SEARCH_TERMS:
            for page in (1, 2):
                url = (f"https://{paper.host}/wp-json/wp/v2/posts?search={term}"
                       f"&after={after}&per_page=50&page={page}"
                       f"&_fields=link,date,content")
                try:
                    rows = await _json(c, url)
                except RuntimeError:
                    break                  # past the last page, or term unsupported
                if not rows:
                    break
                for p in rows:
                    docs.append((p.get("link") or paper.host,
                                 body_text((p.get("content") or {}).get("rendered", ""))))
                if len(rows) < 50:
                    break
    else:
        urls: list[str] = []
        for term in SEARCH_TERMS:
            for page in (1, 2):
                url = (f"https://{paper.host}/wp-json/wp/v2/search?search={term}"
                       f"&per_page=50&page={page}&_fields=url")
                try:
                    rows = await _json(c, url)
                except RuntimeError:
                    break
                if not rows:
                    break
                urls += [r["url"] for r in rows if r.get("url")]
                if len(rows) < 50:
                    break
        for u in list(dict.fromkeys(urls))[:MAX_DOCS]:
            try:
                r = await c.get(u, timeout=60.0)
            except Exception:  # noqa: BLE001
                continue
            if r.status_code == 200:
                docs.append((u, body_text(r.text)))
            await asyncio.sleep(0.4)       # these are small-town servers

    out: list[Listing] = []
    seen: set[str] = set()
    hits = 0
    for url, body in docs[:MAX_DOCS]:
        estates = parse_estates(body)
        if estates:
            hits += 1
        for e in estates:
            if e["case_number"] in seen:
                continue                   # notices run 3 weeks; the same estate repeats
            seen.add(e["case_number"])
            out.append(_to_listing(e, url, slug))
    by_county: dict[str, int] = {}
    for li in out:
        by_county[li.county or "?"] = by_county.get(li.county or "?", 0) + 1
    log.info("sc_probate.paper_done", host=paper.host, docs=len(docs),
             notice_docs=hits, estates=len(out), by_county=by_county)
    return out


class SCProbateNotices(BaseScraper):
    slug = "counties_sc.sc_probate_notices"
    name = "SC Notice to Creditors probate notices (upstate county papers)"
    category = "probate"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_SC_PROBATE_NOTICES") == "0":
            return []
        out: list[Listing] = []
        # The two secondary papers are tolerated because they genuinely wobble:
        # the Gaffney Ledger is read through article pages and rate-limits, and
        # the Laurens Advertiser runs only a handful of notices at a time.
        # Pickens is NOT tolerated. It is the anchor, it is the richest, and if
        # it ever starts returning nothing that is a break we want to hear about
        # rather than a quiet drop to a third of the leads.
        guard = LayerHarvest(self.slug, [p.host for p in PAPERS], attempts=2,
                             tolerate=("www.gaffneyledger.com",
                                       "www.laurenscountyadvertiser.net"))
        async with client(timeout=60.0) as c:
            with guard:
                for paper in PAPERS:
                    out.extend(await guard.harvest(paper.host, self._one(c, paper)))
        return out

    @staticmethod
    def _one(c, paper: Paper):
        async def _run() -> list[Listing]:
            return await _fetch_paper(c, paper)
        return _run
