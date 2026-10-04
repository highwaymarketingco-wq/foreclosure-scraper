"""Spartan Weekly News legal notices — the FREE, bulk, no-WAF route to
Spartanburg-County foreclosure / probate / tax leads.

Why this source exists alongside sc_public_notices.py:
  * The SC court Public Index (lis pendens) is Rule-610 prohibited for commercial
    bulk + WAF-defended — not a free/legal bulk route.
  * Spartanburg ROD (search.spartanburgdeeds.com, newer Logan) is in a county-side
    empty-index state AND holds only POST-sale deeds (see rod/logan.py).
  * scpublicnotices.com's per-county advanced search 500s server-side and
    publicnoticesc.com has a challenge-response that defeats httpx + Scrapling.
  * Spartanburg's legal notices are ALSO published by The Spartan Weekly (the
    paper the Master-in-Equity uses), at /legal-notices/?page=N — plain paginated
    HTML, no anti-bot, address in the URL slug, case # + notice type in the row.

Mechanism (browserless, verified 2026-06-24):
  GET {HOST}/legal-notices/?page=N  ->  repeated article blocks:
    <div class="article ..."><h6>{TYPE}</h6>
      <h4><a href="/legal-notices/{slug}">{STREET ADDRESS}</a></h4>
      <p> Case #:{2025CP42…}<br> {Mon DD, YYYY} </p></div>
  TYPE is "Master In Equity" (foreclosure), "Probate Court", or "All Other".
  Detail page ({HOST}{href}) carries the full legal text -> defendant (vs.) and,
  for sale notices, the sale date/amount. We page until a page adds no new rows,
  then best-effort enrich each kept notice from its detail page (failures are
  non-fatal — list-row data already yields address + case# + type).

AUDITED 2026-10-01 -- THE SITE CAME BACK, REDESIGNED, AND BROKE TWO THINGS.
    www.spartanweeklyonline.com was marked DEAD 2026-08-24 (404 everywhere).
    Confirmed live: it is back, with real fresh notices (checked: October 1,
    2026 probate filings on page 1) -- re-verifying a DEAD source before
    trusting it, per this repo's own standing rule, is what caught this.

    But the template changed since this module was built, in two ways that
    together made every row silently wrong rather than silently empty:

    1. THE "ADDRESS" ANCHOR TEXT IS NOW A CATEGORY LABEL, NOT AN ADDRESS.
       <h4><a href="...">{STREET ADDRESS}</a></h4> used to hold the real
       address. Live now it holds things like "Legal Notice", "Abandoned
       vehicle", "Summons and Notices", "Notice of Hearing" -- a restatement
       of the notice's own sub-type, not a street. The old code took this
       text as `street_address` unconditionally, so EVERY row shipped a
       fabricated address (the literal string "Summons and Notices" as a
       mailable address). Fixed: `address` is only kept when the text looks
       like a real address (anchored on a leading house number); otherwise
       it is None, same posture as every other SC source audited today that
       won't fabricate an address from legal-description-shaped or label-
       shaped text.

    2. THE TYPE TAXONOMY COLLAPSED, SILENTLY DROPPING FORECLOSURE CLASSIFICATION.
       The old h6 TYPE ("Master In Equity") is GONE from live output --
       checked 5 pages, every row is now "Probate Court" or "All Other
       Notices". A live detail page filed under "All Other Notices" /
       "Summons and Notices" reads, in full: "STATE OF SOUTH CAROLINA COUNTY
       OF SPARTANBURG IN THE COURT OF COMMON PLEAS C/A No.: 2026-CP-42-02855
       MidFirst Bank, Plaintiff, v. Michael Ronald Pressley; Granite St. Land
       Trust, Defendant(s). Summons and Notices (Non-Jury) Foreclosure of
       Real Estate Mortgage" -- an ordinary mortgage-foreclosure summons that
       the old code could never recognize as one, because `_classify()` only
       ever looked at the h6 label, never the body. kind stayed "other" and
       lt stayed UNKNOWN for every foreclosure notice on the site, and the
       sale-date/judgment-amount/plaintiff extraction block (gated on
       `kind == "foreclosure"`, set only from the stale label) never ran even
       though the enrichment pass had the real body in hand. Fixed:
       `_reclassify_from_body()` re-derives kind/lt from the fetched body's
       own language (independent of the row's h6 label) during enrichment, so
       a real foreclosure notice is recognized and gets the sale-date/amount/
       plaintiff pass regardless of which generic bucket the site filed it
       under.
"""
from __future__ import annotations

import asyncio
import html as _html
import re
import time
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# AUDITED 2026-10-01: the site came back from its 2026-08-24 DEAD state (see
# that audit's note in the module docstring above). This host is live.
_HOST = "https://www.spartanweeklyonline.com"
_LIST = _HOST + "/legal-notices/?page={page}"
_MAX_PAGES = 40          # safety cap; loop also stops when a page adds nothing new
_ENRICH_DETAILS = True   # follow each notice to its detail page for the body text
_MAX_DETAIL_FETCH = 250  # bound detail fetches so a big run never blows timeout_s
_DETAIL_BUDGET_S = 150   # hard wall-clock cap on the (throttled) detail-enrich pass

# Sentinel `_row_to_listing(enrich=True)` returns to mean "the body CONFIRMS
# this notice is junk, drop it" -- distinct from returning None, which means
# "enrichment failed/hasn't run; keep whatever the no-network base pass
# already shipped". Collapsing both into None would un-drop a confirmed-junk
# row the moment its pre-enrichment stub had already been banked.
_JUNK = object()

_ARTICLE_RE = re.compile(
    r'<div class="article[^"]*">\s*'
    r'<h6>\s*(?P<type>[^<]*?)\s*</h6>\s*'
    r'<h4>\s*<a href="(?P<href>/legal-notices/[^"]+)">\s*(?P<addr>[^<]+?)\s*</a>\s*</h4>\s*'
    r'<p>(?P<meta>.*?)</p>',
    re.S,
)
_CASE_RE = re.compile(r"Case\s*#?:?\s*(20\d{2}CP\d{6,9})", re.I)
_DATE_RE = re.compile(r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})")
# defendant from the legal-notice body: "...Plaintiff, vs. <NAME>, Defendant(s)..."
# SC Master-in-Equity sale notices read: "...in the case of PLAINTIFF v.
# DEFENDANTS, I, the undersigned as Master-in-Equity ... will sell on DATE...".
# Capture the defendant block between "v." and the "I, the undersigned" / "will
# sell" close — keeps multi-party lists and middle initials ("Thomas J. Lee").
_VS_RE = re.compile(
    # opener: "v." / "vs." / "against"; SC captions also read "... against NAME et al"
    r"\b(?:vs?\.?|against)\s+([A-Z][A-Za-z0-9 .,;'&#/()-]{3,250}?)"
    # close on the caption terminator — "; et.al.", ", I, the undersigned/Master", "will sell"
    r"\s*[;,]?\s*(?:et\.?\s*al\.?|I,?\s+the\s+(?:undersigned|Master)|the\s+undersigned"
    r"|will\s+sell|TO THE\b)",
    re.I,
)
_ESTATE_RE = re.compile(
    r"(?:estate of|in re:?|decedent:?)\s+([A-Z][A-Za-z .,'-]{3,70}?)"
    r"(?:,|\s+deceased|\s+date of death|\s*\()",
    re.I,
)
# Caption plaintiff. SC master's-sale notices read "...in the case of PLAINTIFF
# v. DEFENDANT..." or "PLAINTIFF, Plaintiff(s), vs. DEFENDANT, Defendant(s)".
# Primary anchors on "case/matter/action of ... v."; fallback on the ", Plaintiff"
# label. Both best-effort — only set when matched.
_PLAINTIFF_RE = re.compile(
    r"\b(?:case|matter|action)\s+of\s+"
    r"([A-Z][A-Za-z0-9 .,'&#/()\-]{3,150}?)"
    r"\s+(?:vs?\.?|against)\s+[A-Z]",
    re.I,
)
_PLAINTIFF_KW_RE = re.compile(
    r"(?:^|[.;]\s+|\bof\s+)"
    r"([A-Z][A-Za-z0-9 .,'&#/()\-]{3,150}?)"
    r"\s*,?\s+Plaintiff[s]?\b",
    re.I,
)
_SALE_RE = re.compile(r"\b(master'?s sale|notice of sale|will be sold|will sell|public auction|sold to the highest)\b", re.I)
# "will sell on Monday, July 6, 2026 ..." / "will sell on July 6, 2026" — skip the
# optional weekday between "on" and the month-name date, then capture "Month D, YYYY".
_SALEDATE_RE = re.compile(
    r"will\s+sell\b.{0,40}?\b((?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},?\s+\d{4})", re.I)
_AMOUNT_RE = re.compile(r"\$[\d,]{4,}(?:\.\d{2})?")
# Probate "Notice to Creditors" fields: "Estate: <DECEDENT> Date of Death: <DATE>
# Case Number: <ES#> Personal Representative: <PR NAME> <PR ADDRESS>".
_PROBATE_ESTATE = re.compile(
    r"\bEstate:\s*([A-Z][A-Za-z .,'\-]{3,60}?)\s+(?:Date of Death|Case Number|a/?k/?a|aka)\b", re.I)
_PROBATE_DOD = re.compile(r"Date of Death:\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})", re.I)
# PR name + mailing address. Accepts ANY US state (executors who inherited often
# live out of state — an absentee heir is a STRONGER seller, not one to drop) and
# PO-Box mailing addresses (the old SC|NC|GA + house-number-only pattern dropped
# ~28% of PRs: out-of-state IA/DC/etc. and "Post Office Box N" lines).
_PROBATE_PR = re.compile(
    r"Personal Representative[s]?:?\s*([A-Z][A-Za-z .,'\-]{3,55}?)\s+"
    r"((?:P\.?\s*O\.?\s*Box|Post\s+Office\s+Box|\d{1,6})"
    r"[A-Za-z0-9 .,'#\-]*?,?\s*[A-Z]{2}\.?\s*\d{5})", re.I)
_ES_CASE_RE = re.compile(r"\b(20\d{2}ES\d{6,9})\b")
# SC's "deposit of will" probate filing ("The Will of <NAME>, Deceased, was
# delivered to me and filed <DATE>. No proceedings for the probate of said
# Will have begun.") carries no "Estate:"/"ESTATE OF:" label at all -- the
# standard _ESTATE_RE/_PROBATE_ESTATE patterns never match it. AUDITED
# 2026-10-04: this is NOT a rare variant -- live, it was 12 of 72 probate
# notices in one run (the single most common PROBATE_NOTICE sub-type after
# the standard Notice-to-Creditors format), every one of which shipped with
# defendant=None before this fix.
_WILL_DEPOSIT_RE = re.compile(
    r"\bWill\s+of\s+([A-Z][A-Za-z .,'\-]{3,70}?),?\s+Deceased\b", re.I)
# "IN THE MATTER OF: <NAME> (Decedent)" -- the caption SC Probate Court uses
# on a Notice of Hearing (e.g. an "Application for Successor Personal
# Representative"). AUDITED 2026-10-04: live-confirmed this body carries a
# real decedent name, case number, and a petitioner's own name/address/
# phone/email -- the OLD code filed this under _classify()'s generic "other"
# fallback (h6 label "All Other Notices") and shipped it as a bare
# ListingType.UNKNOWN row with every field None, discarding all of that.
_MATTER_OF_RE = re.compile(
    r"\bIN\s+THE\s+MATTER\s+OF:?\s*([A-Z][A-Za-z .,'\-]{3,70}?)\s*\(Decedent\)", re.I)
_PROBATE_HEARING_TOPIC_RE = re.compile(
    r"\(Decedent\)|Relationship\s+to\s+Decedent/Estate|Successor\s+Personal\s+Representative",
    re.I)
# Petitioner contact on a Notice of Hearing: best-effort, anchored on the
# Phone:/Email: labels the court form always prints (confirmed live on a real
# "Application for Successor Personal Representative" notice).
_PETITIONER_SIGNATURE_RE = re.compile(
    r"\bs/\s*([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*){0,3})")
_PETITIONER_ADDR_RE = re.compile(
    r"(\d{1,6}\s+[A-Za-z0-9 .,'\-]+?,?\s*[A-Z]{2}\.?\s*\d{5})\s+Phone:", re.I)
_PETITIONER_PHONE_RE = re.compile(r"\bPhone:?\s*([\d().\-\s]{7,20}?)(?=\s+Email:|\s+Relationship|$)", re.I)
_PETITIONER_EMAIL_RE = re.compile(r"\bEmail:?\s*([\w.+\-]+@[\w.\-]+\.\w+)", re.I)
# Confirmed junk, live 2026-10-04: a city "Abandoned vehicle" impound notice
# (make/model/VIN/towing cost, no property, no party). The site's taxonomy
# collapse (see module docstring) files these under the same "All Other
# Notices" h6 as every other non-probate notice, so a bare label check can't
# tell them from a real foreclosure summons -- the body always can.
_VEHICLE_JUNK_RE = re.compile(r"\bVin:\s*[A-Z0-9]{8,}|\bAbandoned\s+vehicle\b", re.I)
# A quiet-title/heir-action caption has NO "will sell"/"et al"/"I, the
# undersigned" closing marker _VS_RE requires (those are foreclosure-sale-
# specific) -- live-confirmed on 2 real captions, _VS_RE matches neither.
# Anchor on the SAME heirs-of-Defendant phrase _QUIET_TITLE_TOPIC_RE already
# uses to classify the notice ("all"/"any" both occur on real notices).
_QUIET_TITLE_DEFENDANT_RE = re.compile(
    r"\bvs?\.?\s+(.+?)\s*,?\s*and\s+(?:all|any)\s+known\s+and\s+unknown\s+heirs", re.I)


def _clean(s: str) -> str:
    # AUDITED 2026-10-04: this used to hand-roll three entity replacements
    # (&nbsp;/&amp;/&#39;) and leave every OTHER named entity -- notably the
    # CMS's own typographic &rsquo; for an apostrophe in a name -- as the
    # LITERAL 7-character string "&rsquo;" in the cleaned text. That breaks
    # every [A-Za-z .,'\-]-shaped name/address regex in this module outright
    # (not just drops the apostrophe): confirmed live on THREE real
    # Notice-to-Creditors decedents in one run -- "Ahsad U&rsquo;Real Logan",
    # "La&rsquo;Shauna Davette Long", "Marquise Asant&rsquo;e Browning" --
    # _PROBATE_ESTATE/_ESTATE_RE matched NONE of them; every one shipped with
    # defendant=None despite the real name sitting in the fetched body.
    # html.unescape() decodes every named/numeric entity (not just three),
    # and the curly-quote/dash normalization below maps the result back to
    # the plain ASCII forms this module's regexes already expect.
    t = re.sub(r"<[^>]+>", " ", s or "")
    t = _html.unescape(t)
    t = (t.replace("’", "'").replace("‘", "'")
         .replace("“", '"').replace("”", '"')
         .replace("–", "-").replace("—", "-"))
    return re.sub(r"\s+", " ", t).strip()


def _classify(notice_type: str) -> tuple[ListingType, str]:
    t = (notice_type or "").lower()
    if "master" in t or "equity" in t or "foreclos" in t:
        return ListingType.LIS_PENDENS, "foreclosure"
    if "probate" in t or "estate" in t:
        return ListingType.PROBATE_NOTICE, "probate"
    if "tax" in t:
        return ListingType.TAX_SALE, "tax"
    return ListingType.UNKNOWN, "other"


# AUDITED 2026-10-01: the site's h6 TYPE taxonomy collapsed to just "Probate
# Court" / "All Other Notices" -- it no longer labels a row "Master In
# Equity", so _classify() (label-only) can no longer recognize a real
# foreclosure notice at all. The notice BODY still says so in plain language
# every time, so a real foreclosure summons/sale notice is detected from the
# fetched text instead of trusting the (now uninformative) label.
_FORECLOSURE_TOPIC_RE = re.compile(
    r"\bforeclosur\w+|deed\s+of\s+trust|master[\s-]in[\s-]equity|master'?s\s+sale|"
    r"special\s+referee|order\s+of\s+reference\b", re.I)

# AUDITED 2026-10-04: a second real sub-type the same collapsed "All Other
# Notices" bucket hides -- a QUIET TITLE / partition-style civil action
# against "all known and unknown heirs" of prior owners. Live-confirmed on 3
# real Spartanburg notices (one explicitly labeled "(Quiet Title)", all 3
# sharing the same boilerplate caption below) -- these are real-property
# actions naming heir-defendants, exactly the tangled-title / heir-property
# shape this project's motivated-seller engine already targets elsewhere.
# The OLD code shipped them as ListingType.UNKNOWN with every field None.
_QUIET_TITLE_TOPIC_RE = re.compile(
    r"\bquiet\s+title\b|"
    r"\bknown\s+and\s+unknown\s+heirs\s+of\s+any\s+named\s+or\s+unnamed\s+Defendant", re.I)


def _reclassify_from_body(lt: ListingType, kind: str, body: str) -> tuple[ListingType, str]:
    """Upgrade (lt, kind) using the notice's own body text, independent of
    the row's (possibly uninformative) h6 label. Never downgrades probate or
    tax, which the label already identifies reliably."""
    if kind in ("probate", "tax"):
        return lt, kind
    # Checked before the foreclosure topic: a Notice of Hearing names a
    # "(Decedent)" and never mentions foreclosure language, so there is no
    # real ordering conflict, but probate is the more specific/useful type.
    if _PROBATE_HEARING_TOPIC_RE.search(body or ""):
        return ListingType.PROBATE_NOTICE, "probate"
    if _FORECLOSURE_TOPIC_RE.search(body or ""):
        return ListingType.LIS_PENDENS, "foreclosure"
    if _QUIET_TITLE_TOPIC_RE.search(body or ""):
        return ListingType.LIS_PENDENS, "quiet_title"
    return lt, kind


# A real address is anchored on a leading house number; the site's current
# anchor text is a category restatement ("Legal Notice", "Summons and
# Notices", "Abandoned vehicle", "Notice of Hearing") with no digits at all.
_ADDR_SHAPE_RE = re.compile(r"^\d{1,6}\b")


def _looks_like_address(text: str | None) -> bool:
    return bool(text and _ADDR_SHAPE_RE.match(text.strip()))


def _defendant(body: str, kind: str) -> str | None:
    if kind == "probate":
        # AUDITED 2026-10-04: _ESTATE_RE alone missed 2 of the site's own
        # probate sub-formats -- the "Will of X, Deceased" deposit-of-will
        # filing (no "Estate:"/"estate of" label at all) and a Notice of
        # Hearing's "IN THE MATTER OF: X (Decedent)" caption. Both tried as
        # fallbacks, in the order a human would recognize them.
        m = _ESTATE_RE.search(body) or _WILL_DEPOSIT_RE.search(body) or _MATTER_OF_RE.search(body)
    elif kind == "quiet_title":
        # AUDITED 2026-10-04: _VS_RE requires a foreclosure-sale-specific
        # closing marker ("will sell" / "et al" / "I, the undersigned") that
        # a quiet-title/heir-action caption never prints -- confirmed live,
        # it matches neither of 2 real captions. _QUIET_TITLE_DEFENDANT_RE
        # anchors on the heirs-of-Defendant phrase instead.
        m = _QUIET_TITLE_DEFENDANT_RE.search(body)
    else:
        m = _VS_RE.search(body)
    return _clean(m.group(1)).strip(" ,;") if m else None


def _plaintiff(body: str) -> str | None:
    """Caption plaintiff from a foreclosure sale-notice body, best-effort."""
    m = _PLAINTIFF_RE.search(body) or _PLAINTIFF_KW_RE.search(body)
    return _clean(m.group(1)) if m else None


def _parse_notice_date(s: str | None) -> datetime | None:
    """A 'Month D, YYYY' notice-date string -> datetime (None on failure)."""
    if not s:
        return None
    t = re.sub(r"\s+", " ", s.replace(",", " ")).strip()
    try:
        return datetime.strptime(t, "%B %d %Y")
    except (ValueError, TypeError):
        return None


def _parse_amount(s: str | None) -> float | None:
    """A '$453,617.57' amount string -> float (None on failure / zero)."""
    if not s:
        return None
    digits = re.sub(r"[^\d.]", "", s)
    try:
        return float(digits) or None
    except (ValueError, TypeError):
        return None


class SpartanWeeklyLegals(BaseScraper):
    slug = "counties_sc.spartan_weekly_legals"
    name = "Spartan Weekly legal notices (Spartanburg foreclosure/probate/tax)"
    category = "public_notices"
    expected_min_count = 0
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        rows: list[dict] = []
        seen: set[str] = set()
        async with client(timeout=60.0) as c:
            for page in range(1, _MAX_PAGES + 1):
                try:
                    r = await c.get(_LIST.format(page=page))
                except Exception:
                    log.warning("spartan_weekly.page_fetch_failed", page=page)
                    break
                if r.status_code != 200:
                    break
                page_rows = [m.groupdict() for m in _ARTICLE_RE.finditer(r.text)]
                fresh = 0
                for row in page_rows:
                    key = row["href"].strip()
                    if key in seen:
                        continue
                    seen.add(key)
                    fresh += 1
                    rows.append(row)
                if not page_rows or fresh == 0:   # clamped/empty -> end of notices
                    break

            # 1) Emit a base lead for EVERY notice FIRST (network-free), so all of
            #    them land even if detail enrichment is slow or cut off. The old
            #    single loop detail-fetched sequentially under the per-host throttle
            #    and stalled before reaching the probate notices (which sit later in
            #    the list) — dropping every Spartanburg probate lead.
            listings: list[Listing] = [
                await self._row_to_listing(row, c, enrich=False) for row in rows
            ]

            # 2) Best-effort, TIME-BOXED detail enrichment — PROBATE FIRST (those need
            #    the decedent/PR/address from the body; foreclosure rows already carry
            #    an address from the list row). A slow/failed fetch never drops a lead.
            if _ENRICH_DETAILS:
                order = sorted(
                    range(len(rows)),
                    key=lambda j: 0 if _classify(rows[j]["type"])[1] == "probate" else 1,
                )
                t0 = time.monotonic()
                enriched_n = 0
                for j in order[:_MAX_DETAIL_FETCH]:
                    if time.monotonic() - t0 > _DETAIL_BUDGET_S:
                        break
                    try:
                        full = await self._row_to_listing(rows[j], c, enrich=True)
                    except Exception:
                        full = None
                    if full is _JUNK:
                        # Confirmed junk by the body text itself -- explicitly
                        # drop, overwriting the base pass's stub. A plain
                        # `None` here would mean "enrichment didn't run",
                        # which must NOT un-drop a row already banked.
                        listings[j] = None
                    elif full:
                        listings[j] = full
                        enriched_n += 1
                log.info("spartan_weekly.enriched", enriched=enriched_n, of=len(rows))
        listings = [li for li in listings if li]
        log.info("spartan_weekly.done", notices=len(rows), leads=len(listings))
        return listings

    async def _row_to_listing(self, row: dict, c, enrich: bool):
        # Returns a Listing, None (no news yet / fetch failed, caller keeps
        # whatever it already has), or the module-level `_JUNK` sentinel
        # (enrich=True only: the body CONFIRMS this notice should be dropped).
        lt, kind = _classify(row["type"])
        meta = _clean(row["meta"])
        case_m = _CASE_RE.search(meta)
        date_m = _DATE_RE.search(meta)
        # AUDITED 2026-10-01: the anchor text is now a category restatement
        # ("Summons and Notices", "Abandoned vehicle", ...), not a street --
        # see the module docstring. Only keep it when it is actually
        # address-shaped; otherwise this field has no real value to offer
        # before enrichment runs.
        addr_raw = _clean(row["addr"])
        address = addr_raw if _looks_like_address(addr_raw) else None
        source_url = _HOST + row["href"]

        body, defendant, sale_date, amount = "", None, None, None
        sale_date_dt = None
        judgment_amount = None
        plaintiff = None
        probate = None
        es_case = None
        if enrich:
            try:
                d = await c.get(source_url)
                if d.status_code == 200:
                    body = _clean(d.text)
                    # AUDITED 2026-10-01: the site's TYPE taxonomy collapsed
                    # (see module docstring), so re-derive kind/lt from the
                    # body BEFORE using kind for anything below -- otherwise
                    # a real foreclosure notice filed under "All Other
                    # Notices" never gets its sale-date/amount/plaintiff
                    # extraction, which is gated on kind == "foreclosure".
                    lt, kind = _reclassify_from_body(lt, kind, body)
                    defendant = _defendant(body, kind)
                    if kind == "foreclosure" and _SALE_RE.search(body):
                        lt = ListingType.FORECLOSURE_SALE
                        sm = _SALEDATE_RE.search(body)
                        sale_date = sm.group(1) if sm else None
                        am = _AMOUNT_RE.search(body)
                        amount = am.group(0) if am else None
                        # Promote the parsed strings to first-class fields (were
                        # dropped into raw-only before): sale_date -> datetime,
                        # amount -> judgment_amount, plus the caption plaintiff.
                        sale_date_dt = _parse_notice_date(sale_date)
                        judgment_amount = _parse_amount(amount)
                        plaintiff = _plaintiff(body)
                    if kind == "probate":
                        em = _PROBATE_ESTATE.search(body)
                        decedent = _clean(em.group(1)) if em else defendant
                        if decedent:
                            # The DECEDENT is the property owner — putting them in
                            # `defendant` lets enrichment_address_backfill resolve the
                            # property by owner-name (the notice has no address).
                            defendant = decedent
                        prm = _PROBATE_PR.search(body)
                        dod = _PROBATE_DOD.search(body)
                        esm = _ES_CASE_RE.search(body)
                        es_case = esm.group(1) if esm else None
                        probate = {
                            "decedent": decedent or None,
                            "date_of_death": (dod.group(1) if dod else None),
                            "personal_representative": (_clean(prm.group(1)) if prm else None),
                            "pr_address": (_clean(prm.group(2)) if prm else None),
                            "es_case_number": es_case,
                        }
                        # A Notice of Hearing (e.g. an "Application for Successor
                        # Personal Representative") carries a PETITIONER's own
                        # name/address/phone/email instead of a standard PR block
                        # -- capture it too when present. Live-confirmed real:
                        # name, mailing address, phone AND email all on one
                        # notice, which _PROBATE_PR (built for the plain
                        # Notice-to-Creditors shape) never looks for. Stored
                        # separately from `raw['owner_phone']` on purpose: that
                        # key is a contract several enrichers (enrichment_dnc,
                        # enrichment_line_type) read as already DNC-gate-shaped
                        # (needs_dnc_scrub/do_not_dial flags); a court filing's
                        # self-disclosed number is real data worth keeping, but
                        # wiring it into that gated contract is a separate
                        # enrichment decision this single-source audit should
                        # not make unilaterally.
                        if _PROBATE_HEARING_TOPIC_RE.search(body):
                            pm = _PETITIONER_SIGNATURE_RE.search(body)
                            pam = _PETITIONER_ADDR_RE.search(body)
                            phm = _PETITIONER_PHONE_RE.search(body)
                            ehm = _PETITIONER_EMAIL_RE.search(body)
                            mm = _MATTER_OF_RE.search(body)
                            if pm or pam or phm or ehm:
                                probate["petitioner"] = {
                                    "name": _clean(pm.group(1)) if pm else None,
                                    "address": _clean(pam.group(1)) if pam else None,
                                    "phone": _clean(phm.group(1)) if phm else None,
                                    "email": (ehm.group(1).strip() if ehm else None),
                                }
                            if mm and not decedent:
                                probate["decedent"] = _clean(mm.group(1))
                        # No property address in a probate notice — clear the notice
                        # title so the owner-name backfill fires on the decedent.
                        address = None
                    if kind == "other" and _VEHICLE_JUNK_RE.search(body):
                        # Confirmed junk (see module docstring): a city vehicle-
                        # impound notice carries no property and no party --
                        # drop it rather than ship an all-None UNKNOWN row.
                        return _JUNK
            except Exception:
                log.debug("spartan_weekly.detail_failed", url=source_url[:120])

        raw: dict = {"public_notice": {
            "source": "spartanweeklyonline.com",
            "notice_type": row["type"].strip(),
            "published": (date_m.group(1) if date_m else None),
            "sale_date": sale_date, "amount_text": amount,
            "address_slug": row["href"].rsplit("/", 1)[-1],
        }}
        if body:
            raw["public_notice"]["text"] = body[:4000]
        if kind == "probate":
            raw["relationship_signal"] = {"kind": "probate", "keyword": "public_notice",
                                          "tagged_at": datetime.utcnow().isoformat() + "Z"}
            if probate:
                raw["probate"] = probate

        return Listing(
            source=self.slug, source_url=source_url,
            listing_type=lt, property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Spartanburg",
            defendant=defendant,
            plaintiff=plaintiff,
            sale_date=sale_date_dt,
            judgment_amount=judgment_amount,
            street_address=address or None,
            case_number=(es_case or (case_m.group(1) if case_m else None)),
            description=(f"{row['type'].strip()}"
                         + (f" — {address}" if address else "")
                         + (f" — {defendant}" if defendant else "")),
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw=raw,
        )
