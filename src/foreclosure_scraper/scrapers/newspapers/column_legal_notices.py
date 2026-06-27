"""Column unified legal-notice API — NC foreclosure + NC/SC estate/probate.

Column (column.us / enotice-production) runs the legal-notice publishing
back-end for hundreds of newspapers, including the NC + SC papers of record
across our footprint. It exposes a single public search endpoint that returns
the FULL OCR'd notice body, county, state, notice type, paper name, and a
direct PDF link — no auth, no key, no token (a bare JSON POST works).

This is the highest-value single source we have: instead of crawling each
paper's site individually, one endpoint covers every county. We pull three
notice classes:

  (1) NC "Foreclosure Sale" notices — the pre-auction power-of-sale signal.
      The body is label-structured ("Date of Sale", "Record Owners",
      "Address of Property", "Special Proceedings No.", "Substitute Trustee",
      "Deed of Trust Book/Page", "PIN"), so we parse a real Listing with
      address + owner + sale_date + trustee + case_number + parcel.

  (2) NC estate/decedent notices — the NC mortality lane. Column files NC
      estate notices under TWO noticetype strings (verified live 2026-06-26
      across the NC footprint, free/no-auth): "Estate (Probate) Filings" AND
      "Notice to Creditors" (~280 rows in the last 120 days; McDowell, Burke,
      Gaston, Buncombe, Onslow lead). Both bodies are the same NC-statutory
      creditor notice ("Having qualified as Executor/Administrator of the
      Estate of <decedent>, deceased ... File No: <NC estate file#> ... <PR>,
      Executor"), so one parser handles both. Emitted as PROBATE_NOTICE leads:
      owner_name = decedent, executor/PR + NC estate file# in raw["probate"],
      address-less OK (the owner-to-GIS enricher backfills the property address
      downstream from the decedent name).

  (3) SC "Estate (Probate) Filings" notices — SC has NO foreclosure notice
      type on Column (verified live 2026-06-26: the only SC notice types in
      footprint are '', 'Notice of Application', 'Summons', 'Notice of Sale',
      'Estate (Probate) Filings', 'Parental Action', etc.). Probate "Notice to
      Creditors" filings are emitted as PROBATE_NOTICE leads: owner_name =
      decedent (from "Estate:"), address-less is OK (the owner-to-GIS enricher
      backfills the property address downstream from the decedent name).

Endpoint behavior (verified live 2026-06-26):
  - POST https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices
  - body keys: search (""), allFilters (array of single-key objects:
    {state}, {county}, {noticetype}, {publishedtimestamp:{from,to}} in ms),
    noneFilters ([]), sort ([{publishedtimestamp:"desc"}]), pageSize, isDemo.
  - response: {results: [...], page, success}. Each item:
    text, county, state, noticetype, newspapername, publishedtimestamp (ms),
    pdfurl, filer, id, highlighted_text.
  - the server `page` param is unreliable (duplicate rows). We use ONE large
    pageSize per (county, type) over a ~120-day window and DEDUP on `id`.

Free + compliant: public endpoint, no login/CAPTCHA/token defeat. We read the
notice body the publisher posts publicly. Politeness is enforced by the shared
http_client per-host throttle.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Iterable

import structlog
from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

API_URL = (
    "https://us-central1-enotice-production.cloudfunctions.net"
    "/api/search/public-notices"
)

# Full state names — Column filters on the spelled-out state.
_NC = "North Carolina"
_SC = "South Carolina"

# NC footprint (mountains/foothills + coastal). Column wants exact-cased
# county names (no "County" suffix).
NC_FOOTPRINT = (
    "Buncombe", "Burke", "Cleveland", "Gaston", "Henderson", "Lincoln",
    "McDowell", "Mitchell", "Polk", "Rutherford", "Transylvania",
    # coastal
    "Brunswick", "New Hanover", "Onslow", "Carteret", "Pender", "Dare",
)

# SC footprint (upstate + coastal).
SC_FOOTPRINT = (
    "Anderson", "Cherokee", "Laurens", "Oconee", "Pickens", "Spartanburg",
    "Union",
    # coastal
    "Charleston", "Horry", "Beaufort", "Georgetown", "Colleton",
)

NC_FORECLOSURE_TYPE = "Foreclosure Sale"
# SC has no foreclosure type; probate is the actionable lead class. Verified
# live as the exact string Column uses.
SC_PROBATE_TYPE = "Estate (Probate) Filings"

# NC mortality lane — decedent/estate notices. Column files NC estate notices
# under TWO distinct noticetype strings (verified live 2026-06-26 across the NC
# footprint, free/no-auth): "Estate (Probate) Filings" AND "Notice to
# Creditors". Both bodies are the same NC-statutory creditor notice ("Having
# qualified as Executor/Administrator of the Estate of <decedent>, deceased ...
# File No: <NC estate file#> ... <PR name>, Executor"), so one parser handles
# both. ~280 rows in the last 120 days across the footprint (McDowell, Burke,
# Gaston, Buncombe, Onslow lead). Emitted as PROBATE_NOTICE leads:
# owner_name = decedent, address-less OK (owner-to-GIS enricher backfills the
# property from the decedent name downstream).
NC_ESTATE_TYPES = ("Estate (Probate) Filings", "Notice to Creditors")

# Recent window — about the last 120 days.
WINDOW_DAYS = 120
# One large page beats the unreliable `page` param (dup rows). 250 comfortably
# covers any single county's foreclosure/probate volume over 120 days (the
# busiest in-footprint county, Burke, returned ~26).
PAGE_SIZE = 250


# --------------------------------------------------------------------------- #
# NC foreclosure-notice text parsing
# --------------------------------------------------------------------------- #
# The body is OCR'd with hard line breaks; labels sit on their own fragments.
# We normalize whitespace first, then pull labelled values with anchored
# patterns. Two common templates exist:
#   A) SECU / Nodell-Glass: "Date of Sale: ...  Special Proceedings No. <case>
#      ...  Substitute Trustee: <name> ...  Record Owners: <name> ...
#      Address of Property: <addr> ...  Property Address: <addr>  PIN: <pin>"
#   B) Hutchens style ("Under and by virtue ..."): case in the header
#      ("26SP000132-110"), "RECORD OWNER(S): <name>", "ADDRESS/LOCATION: <addr>".

_WS = re.compile(r"\s+")

# Case / Special Proceedings number: "25SP001499-640", "26 SP 000132-110".
# Accept it (a) after the "Special Proceedings No." label, or (b) standing
# alone anywhere in the header.
_CASE_TOKEN = re.compile(r"\b(\d{2}\s?SP\s?\d{4,6}-?\d{0,3})\b", re.I)
_CASE_AFTER_LABEL = re.compile(
    r"Special Proceedings(?:\s+No\.?)?[:\s]*([0-9][0-9A-Za-z\- ]{4,20})", re.I
)

_DATE_OF_SALE = re.compile(
    r"Date of Sale[:\s]*([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})", re.I
)
_TIME_OF_SALE = re.compile(
    r"Time of Sale[:\s]*([\d: ]+[AaPp]\.?[Mm]\.?)", re.I
)

# Fallback sale-date pass — only used when the structured "Date of Sale:" label
# is absent (Hutchens / Green-Law / "Under and by virtue ..." templates bury the
# auction date in prose). Verified live 2026-06-27 across Burke/Gaston: the
# misses always phrase the date next to a sale-context cue, e.g.
#   "the sale will be held on June 23, 2026 at 2:00 p.m."
#   "...designated for foreclosure sales, at 2:30 PM on June 17, 2026 and will sell"
#   "...designated for foreclosure sales, on June 3, 2026 at 3:00 PM..."
#   "...courthouse for conducting the sale on March 11, 2026 at 1:00 PM..."
#   "...courthouse for conducting the sale, April 28, 2026 at 11:00 AM..."
# We REQUIRE the cue (and a short same-sentence window via [^.]{0,80}) so we never
# pick up the Deed-of-Trust "recorded on <date>", a signature "This the <date>",
# or a summons "no later than <date>" that also live in the body. Both a long
# "Month D, YYYY" and a numeric "m/d/yyyy" date are accepted.
_SALE_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t)?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)"
)
_SALE_DATE_LONG = rf"{_SALE_MONTH}\.?\s+\d{{1,2}},?\s+\d{{4}}"
_SALE_DATE_NUM = r"\d{1,2}/\d{1,2}/\d{2,4}"
_SALE_DATE_ANY = rf"(?:{_SALE_DATE_LONG}|{_SALE_DATE_NUM})"
_SALE_DATE_FALLBACK = re.compile(
    r"(?:will be (?:offered for sale|sold|held|exposed)|sale will be held|"
    r"conducting the sale|designated for foreclosure sales?|"
    r"will sell(?: to the highest bidder)?|offer (?:the property )?for sale|"
    r"sell the (?:above|property))"
    rf"[^.]{{0,80}}?(?:\bon\b|\bat\b|,)?\s*({_SALE_DATE_ANY})",
    re.I,
)

# Record owner(s) — stop at the next label or a comma-clause boundary.
_RECORD_OWNERS = re.compile(
    r"Record Owner(?:\(s\)|s)?[:\s]*"
    r"([A-Z][A-Za-z.,'&/\- ]+?)"
    r"(?=\s+(?:Address of Property|Property Address|ADDRESS|Deed of Trust|"
    r"CONDITIONS|Place of Sale|Description of Property)\b|,?\s*$)",
    re.I,
)

# Substitute Trustee NAME only — anchored to "Substitute Trustee:" with a name
# that follows. The bare phrase "Substitute Trustee will offer ..." is
# boilerplate, so we require a colon AND a CASE-SENSITIVE proper-name capture
# (Title-cased tokens) — this is what rejects "...substitute trustee agrees
# otherwise" / "or substitute trustee" boilerplate that a case-insensitive
# [A-Z] would otherwise swallow. The label itself stays case-insensitive; only
# the captured name is forced to look like a name.
# A proper name token: a leading capital, then only lowercase / apostrophe /
# hyphen (or an all-caps short token like a "P.A." / initials). The trailing
# `(?![a-z])` after the capital block stops an OCR run-on like "GlassNOTICE"
# from being swallowed as one token — a second capital after lowercase ends it.
_NAME_TOK = r"[A-Z][a-z'\-]+\.?|[A-Z]\.?"
# Only the LABELLED colon form is trusted ("Trustee: <Name>" / "Substitute
# Trustee: <Name>"). Hutchens-style notices that bury the trustee in prose are
# left with trustee=None rather than risk a boilerplate false-positive.
_TRUSTEE_GENERIC = re.compile(
    r"(?i:(?<![A-Za-z])Trustee:\s*)"
    rf"((?:{_NAME_TOK})(?:\s+(?:{_NAME_TOK})){{1,3}})"
)
_SUB_TRUSTEE = re.compile(
    r"(?i:Substitute Trustee:\s*)"
    rf"((?:{_NAME_TOK})(?:\s+(?:{_NAME_TOK})){{1,3}})"
)
# Reject obvious non-name captures (firm boilerplate, address tokens, verbs /
# legal-prose words that happen to be Title-cased mid-sentence).
_TRUSTEE_REJECT = re.compile(
    r"\b(Deed|Notice|Re-?notice|Will|Under|The|This|That|Said|Place|Date|Time|"
    r"Book|Page|County|Property|Sale|Description|Conditions|Exhibit|Box|PO|P\.O|"
    r"Attorney|Defendant|Defendants|Plaintiff|TO|Trustee|For)\b", re.I
)

# Address: prefer "Property Address" (usually the clean USPS form), fall back
# to "Address of Property".
_PROPERTY_ADDRESS = re.compile(
    r"Property Address[:\s]*"
    r"(\d+[A-Za-z0-9 .,'#\-]+?,\s*[A-Za-z .]+,\s*NC\s*\d{5})",
    re.I,
)
_ADDRESS_OF_PROPERTY = re.compile(
    r"Address of Property[:\s]*"
    r"(\d+[A-Za-z0-9 .,'#\-]+?)"
    r"(?=\s+(?:CONDITIONS|Deed of Trust|Description|Record Owner|$))",
    re.I,
)
# Hutchens "ADDRESS/LOCATION: 1245 Harrison Loop, ..." form.
_ADDRESS_LOCATION = re.compile(
    r"ADDRESS\s*/?\s*LOCATION[:\s]*"
    r"(\d+[A-Za-z0-9 .,'#\-]+?)(?=\s+(?:Present Record|Deed|Trustee|$))",
    re.I,
)

# Parcel: "PIN: 9647795873C0208", "Tax Parcel I. D. No. 11-44-1-25",
# "PIN NO. 1794384684".
_PIN = re.compile(
    r"(?:Tax Parcel(?:\s*I\.?\s*D\.?)?(?:\s*No\.?)?|PIN(?:\s*No\.?)?)"
    r"[:\s]*([0-9][0-9A-Za-z.\-]{4,})",
    re.I,
)
_DOT_BOOK_PAGE = re.compile(
    r"Deed of Trust[:\s]*(?:Book|recorded[^0-9]*Book)?\s*([0-9A-Za-z ]{1,12}?)"
    r"\s*Page[:\s]*([0-9]{1,8})",
    re.I,
)

# A residual zip we can salvage from any "..., NC 28409" tail in the body.
_ZIP_IN_ADDR = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


# OCR hyphenates words across line wraps: "McDow- ell" (cap+lower) and the
# Scottish-prefix case "Mc- Cracken" (cap+Cap). Join cap/lower fragment to a
# following lowercase letter, OR a 2-3 char prefix (Mc/Mac/O') to a Cap.
_OCR_HYPHEN = re.compile(r"([A-Za-z])-\s+([a-z])")
_OCR_HYPHEN_MC = re.compile(r"\b(Ma?c|O')-\s+([A-Z])")


def _norm(text: str) -> str:
    t = (text or "").replace("\xa0", " ")
    t = _WS.sub(" ", t).strip()
    # Heal hyphenated line-wrap breaks (run twice for chained breaks).
    t = _OCR_HYPHEN_MC.sub(r"\1\2", t)
    t = _OCR_HYPHEN.sub(r"\1\2", t)
    t = _OCR_HYPHEN.sub(r"\1\2", t)
    return t


def _clean_name(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip().strip(",.;:").strip()
    # OCR sometimes leaves a leading "s:" from "Owners:" splits — guard.
    s = re.sub(r"^s[:\s]+", "", s, flags=re.I).strip()
    return s or None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return dateparser.parse(s, fuzzy=True)
    except Exception:
        return None


def _split_addr(full: str | None) -> tuple[str | None, str | None, str | None]:
    """Split '7120 Myrtle Grove Rd., Wilmington, NC 28409' →
    (street, city, zip). Best-effort; street-only is fine."""
    if not full:
        return None, None, None
    full = full.strip().strip(",")
    zip_m = _ZIP_IN_ADDR.search(full)
    zip_code = zip_m.group(1) if zip_m else None
    parts = [p.strip() for p in full.split(",") if p.strip()]
    street = parts[0] if parts else full
    city = None
    if len(parts) >= 2:
        # city is the part before the "NC <zip>" tail
        for p in parts[1:]:
            if re.search(r"\bNC\b", p, re.I):
                break
            city = p
    return (street or None), city, zip_code


def _parse_nc_foreclosure(text: str) -> dict:
    """Extract structured fields from an NC foreclosure-sale notice body."""
    t = _norm(text)
    out: dict = {}

    # Case number — label form first, then a bare token.
    case = None
    m = _CASE_AFTER_LABEL.search(t)
    if m:
        cand = m.group(1).strip()
        if _CASE_TOKEN.search(cand):
            case = _CASE_TOKEN.search(cand).group(1)
    if not case:
        m = _CASE_TOKEN.search(t)
        if m:
            case = m.group(1)
    if case:
        out["case_number"] = re.sub(r"\s+", "", case).upper()

    m = _DATE_OF_SALE.search(t)
    if m:
        out["sale_date_raw"] = m.group(1).strip()
        out["sale_date"] = _parse_dt(m.group(1))
    else:
        # No structured "Date of Sale:" label — scan the prose for a sale-context
        # cue followed by a date (Hutchens / Green-Law / "Under and by virtue"
        # templates). Cue-gated so a Deed-of-Trust recording date / signature
        # date / summons deadline in the same body is never mistaken for it.
        m = _SALE_DATE_FALLBACK.search(t)
        if m:
            raw_date = m.group(1).strip()
            dt = _parse_dt(raw_date)
            if dt is not None:
                out["sale_date_raw"] = raw_date
                out["sale_date"] = dt
    m = _TIME_OF_SALE.search(t)
    if m:
        out["sale_time"] = _norm(m.group(1))

    m = _RECORD_OWNERS.search(t)
    if m:
        out["owner_name"] = _clean_name(m.group(1))

    # Trustee — the clean value is the header "Trustee: <Name>" form; the
    # bottom-of-notice "..., Substitute Trustee <FirmName>" is the signature
    # block (e.g. "Nodell, Glass & Haskell"), so try the named "Trustee:"
    # form FIRST and fall back to "Substitute Trustee: <Name>".
    for pat in (_TRUSTEE_GENERIC, _SUB_TRUSTEE):
        for m in pat.finditer(t):
            name = _clean_name(m.group(1))
            if not name:
                continue
            # Drop a trailing bare single capital (OCR run-on: "Glass N" from
            # "Glass NOTICE", "Glass R" from "Glass RE-NOTICE"). A real middle
            # initial is dotted ("A.") and sits between two name words.
            name = re.sub(r"\s+[A-Z]$", "", name).strip()
            # require a real multi-token proper name; reject firm/boilerplate
            # fragments and Title-cased non-name words.
            if " " in name and not _TRUSTEE_REJECT.search(name):
                out["trustee"] = name
                break
        if out.get("trustee"):
            break

    # Address — Property Address (clean) → Address of Property → ADDRESS/LOCATION
    addr = None
    m = _PROPERTY_ADDRESS.search(t)
    if m:
        addr = m.group(1)
    if not addr:
        m = _ADDRESS_OF_PROPERTY.search(t)
        if m:
            addr = m.group(1)
    if not addr:
        m = _ADDRESS_LOCATION.search(t)
        if m:
            addr = m.group(1)
    if addr:
        street, city, zip_code = _split_addr(addr)
        out["street_address"] = street
        out["city"] = city
        out["zip_code"] = zip_code

    m = _PIN.search(t)
    if m:
        out["parcel_id"] = m.group(1).strip().rstrip(".")

    m = _DOT_BOOK_PAGE.search(t)
    if m:
        out["dot_book"] = m.group(1).strip()
        out["dot_page"] = m.group(2).strip()

    return out


# --------------------------------------------------------------------------- #
# SC probate-notice text parsing
# --------------------------------------------------------------------------- #
# Decedent name from the two SC estate forms:
#   (a) "Notice to Creditors": "Estate: John Q. Public" (clean label form)
#   (b) quiet-title summons:   "the Estate of John Q. Public, Deceased, ..."
# Stop the name at a comma / "Deceased" / "Heirs" / a following label so we
# don't swallow the rest of the heir clause. Capture is forced case-sensitively
# (proper-name tokens) so lowercase prose isn't grabbed.
_DECEDENT_TOK = r"[A-Z][A-Za-z'\-]*\.?"
_ESTATE = re.compile(
    r"(?i:(?:the\s+)?Estate\s*(?:of|:)\s*)"
    rf"((?:{_DECEDENT_TOK})(?:\s+(?:{_DECEDENT_TOK})){{0,4}})"
    r"(?=\s*(?:,|;|\bDeceased\b|\bHeirs?\b|\bDate of Death\b|"
    r"\bCase\b|\bPersonal\b|\bAddress\b|\bAttorney\b)|$)"
)
_DOD = re.compile(
    r"Date of Death[:\s]*([A-Z]{3,9}\.?\s*\d{1,2}\s*,?\s*\d{4}"
    r"|[A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})",
    re.I,
)
# SC probate case number, e.g. "2026-ES-26-00984" — OCR often inserts a space
# after the year ("2026- ES-26-00984"), so tolerate whitespace around dashes.
_SC_CASE = re.compile(
    r"Case Number[:\s]*([0-9]{4}\s*-\s*ES\s*-\s*[0-9][0-9\s\-]*[0-9])", re.I
)
_PERSONAL_REP = re.compile(
    r"Personal\s+Representative[:\s]*([A-Z][A-Za-z.,'\- ]{3,60}?)"
    r"(?=\s+(?:Address|Attorney)\b|$)",
    re.I,
)


def _parse_sc_probate(text: str) -> dict:
    """Extract decedent + DOD + case + PR from an SC estate/probate notice."""
    t = _norm(text)
    out: dict = {}
    m = _ESTATE.search(t)
    if m:
        out["owner_name"] = _clean_name(m.group(1))
    m = _DOD.search(t)
    if m:
        raw = _norm(m.group(1))
        out["date_of_death_raw"] = raw
        out["date_of_death"] = _parse_dt(raw)
    m = _SC_CASE.search(t)
    if m:
        out["case_number"] = re.sub(r"\s+", "", m.group(1)).upper()
    m = _PERSONAL_REP.search(t)
    if m:
        out["personal_representative"] = _clean_name(m.group(1))
    return out


# --------------------------------------------------------------------------- #
# NC estate / decedent-notice text parsing  (NC mortality lane)
# --------------------------------------------------------------------------- #
# The NC creditor notice is highly templated (verified live 2026-06-26):
#   "[NOTICE TO CREDITORS] NORTH CAROLINA, <COUNTY> COUNTY  File No: <file#>
#    Having qualified as Executor/Administrator/Executrix of the Estate of
#    <DECEDENT>, deceased, this is to notify all persons ... This the <date>.
#    <PR NAME>, Executor  <pr address>  Publication Dates: ..."
# Two decedent phrasings appear: "Estate of <name>, deceased" and the Gaston
# variant "estate of <name>, deceased, late of <County> County". The PR
# (executor/administrator/executrix) shows up TWICE — a top header line
# "<PR> - Executor" and a signature line "<PR>, Executor" — we read either.
#
# Decedent: case-SENSITIVE proper-name capture. The label ("Estate of" /
# "estate of" / "ESTATE OF") is matched case-insensitively via an inline
# (?i:...) group, but the captured name is NOT (no global re.I) — a global
# re.I makes _DECEDENT_TOK's leading [A-Z] match lowercase, which over-captures
# trailing prose like "PADGETT deceased" when no comma stops it. Two decedent
# token shapes coexist in one body: Title-case ("Robert Ellis Harwood Sr") and
# ALL-CAPS ("JANICE REBECCA PARKER PADGETT"). _DECEDENT_TOK already allows both
# (a leading capital + any mix of letters), so a single case-sensitive pattern
# covers them. Stop the name at a comma / ; / "deceased"|"DECEASED" / "A/K/A"
# alias / "late of" clause so we don't swallow the rest of the sentence.
_NC_ESTATE = re.compile(
    r"(?i:Estate\s+of\s+)"
    rf"((?:{_DECEDENT_TOK})(?:\s+(?:{_DECEDENT_TOK})){{0,5}}?)"
    r"(?=\s*(?:,|;|[Dd]eceased\b|DECEASED\b|\bA\s*/\s*K\s*/\s*A\b|"
    r"\bAKA\b|\blate of\b)|$)"
)

# NC estate file number. Forms seen live:
#   labelled: "File No: 24E477", "File No: 26 E 210", "File No: 26E000231-580",
#             "File No: 26E00349-110", "Case Number: 26E000307- 350".
#   bare (Buncombe template): "NORTH CAROLINA BUNCOMBE COUNTY 25E001625-100".
# OCR inserts spaces around the 'E' and the trailing dash, so tolerate them.
# A bare file# must carry a dash-suffixed county code ("-100") so we don't grab
# random "<2 digits>E<digits>" tokens out of body prose; the labelled form is
# tried first and is the more permissive of the two.
_NC_FILE_NO = re.compile(
    r"(?:File\s*No\.?|Case\s*Number)[:\s]*"
    r"(\d{2}\s*E\s*[0-9][0-9\s\-]*\d)",
    re.I,
)
_NC_FILE_NO_BARE = re.compile(
    r"\bCOUNTY\b[\s:]*?(\d{2}\s*E\s*\d{3,7}\s*-\s*\d{2,4})\b",
    re.I,
)

# Personal representative + role. The role word (Executor/Executrix/
# Administrator/Administratrix/Co-Executor/Collector) anchors a real name that
# sits immediately before it on the header line ("Betina Renee Harwood -
# Executor") or after the closing date on the signature line ("... 2026.
# Carl Eric Resh, Executor"). We prefer the signature form (name then role).
_PR_ROLE = r"(?:Co-?\s*)?(?:Executor|Executrix|Administrator|Administratrix|Administrator\s+CTA|Collector)"
# Signature form: "<Name>, Executor" / "<Name> , Executrix"
_NC_PR_SIG = re.compile(
    rf"((?:{_DECEDENT_TOK})(?:\s+(?:{_DECEDENT_TOK})){{1,4}})\s*[,\-]\s*({_PR_ROLE})\b"
)
# Header form: "<Name> - Executor"
_NC_PR_HDR = re.compile(
    rf"((?:{_DECEDENT_TOK})(?:\s+(?:{_DECEDENT_TOK})){{1,4}})\s+[\-–]\s+({_PR_ROLE})\b"
)
# Reject captures that are really the boilerplate run-in ("Estate of X,
# deceased ... Having qualified as Executor") rather than a person name.
_PR_REJECT = re.compile(
    r"\b(Estate|Notice|Creditors|County|Carolina|Qualified|Having|Deceased|"
    r"Decedent|Said|This|Date|File|Court|Clerk|The|Of|As)\b", re.I
)


def _parse_nc_estate(text: str) -> dict:
    """Extract decedent + NC file# + executor/PR from an NC creditor notice.

    Address-less by design — owner_name = decedent drives the owner-to-GIS
    backfill downstream. Any address in the body is the PR's mailing address,
    NOT the decedent's property, so we deliberately do NOT parse it.
    """
    t = _norm(text)
    out: dict = {}

    m = _NC_ESTATE.search(t)
    if m:
        out["owner_name"] = _clean_name(m.group(1))

    m = _NC_FILE_NO.search(t) or _NC_FILE_NO_BARE.search(t)
    if m:
        # Collapse OCR whitespace; keep the dash structure ("26E000231-580").
        out["file_number"] = re.sub(r"\s+", "", m.group(1)).upper()

    # PR — signature form first (name precedes role), then header form. Reject
    # boilerplate fragments.
    for pat in (_NC_PR_SIG, _NC_PR_HDR):
        for m in pat.finditer(t):
            name = _clean_name(m.group(1))
            role = m.group(2).strip()
            if not name or " " not in name:
                continue
            if _PR_REJECT.search(name):
                continue
            out["personal_representative"] = name
            out["pr_role"] = role
            break
        if out.get("personal_representative"):
            break

    return out


# --------------------------------------------------------------------------- #
# API call
# --------------------------------------------------------------------------- #
async def _query(
    c, state: str, county: str, noticetype: str, from_ms: int, to_ms: int
) -> list[dict]:
    """One POST for a (state, county, noticetype) window. Returns raw items."""
    body = {
        "search": "",
        "allFilters": [
            {"state": state},
            {"county": county},
            {"noticetype": noticetype},
            {"publishedtimestamp": {"from": from_ms, "to": to_ms}},
        ],
        "noneFilters": [],
        "sort": [{"publishedtimestamp": "desc"}],
        "pageSize": PAGE_SIZE,
        "isDemo": False,
    }
    try:
        r = await c.post(
            API_URL,
            json=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("column.post_fail", county=county, type=noticetype, error=str(exc)[:160])
        return []
    if r.status_code != 200:
        log.warning("column.bad_status", county=county, type=noticetype, code=r.status_code)
        # raise so safe_run classifies block/server-error correctly
        r.raise_for_status()
        return []
    try:
        data = r.json()
    except Exception:
        return []
    results = data.get("results") if isinstance(data, dict) else data
    return results if isinstance(results, list) else []


class ColumnLegalNotices(BaseScraper):
    slug = "counties.column_legal_notices"
    name = "Column Unified Legal Notices (NC foreclosure + SC probate)"
    category = "newspaper_legal"
    requires_apify = False
    # Legal-notice volume swings week-to-week; some weeks a small county runs 0
    # foreclosure notices. A true regression (endpoint down / shape change) is
    # surfaced via the block-signal + outcome classifier, not this floor.
    expected_min_count = 0
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        now_ms = int(time.time() * 1000)
        from_ms = now_ms - WINDOW_DAYS * 24 * 3600 * 1000

        out: list[Listing] = []
        seen_ids: set[str] = set()

        async with client(timeout=60.0) as c:
            # (1) NC foreclosure sales across the NC footprint.
            for county in NC_FOOTPRINT:
                items = await _query(
                    c, _NC, county, NC_FORECLOSURE_TYPE, from_ms, now_ms
                )
                for it in items:
                    li = self._nc_listing(it, county)
                    if li is not None:
                        out.append(li)
                        # dedup tracked inside _nc_listing via seen_ids closure
                # NOTE: dedup handled below in a single pass to keep id set unified
            # (2) NC estate/decedent notices across the NC footprint — the NC
            # mortality lane. Column files these under TWO noticetype strings
            # ("Estate (Probate) Filings" + "Notice to Creditors"), so loop both
            # per county. Emitted as PROBATE_NOTICE leads (decedent = owner_name,
            # address-less OK). Base-id dedup below collapses any overlap between
            # the two noticetypes / publication runs.
            for county in NC_FOOTPRINT:
                for ntype in NC_ESTATE_TYPES:
                    items = await _query(c, _NC, county, ntype, from_ms, now_ms)
                    for it in items:
                        li = self._nc_estate_listing(it, county)
                        if li is not None:
                            out.append(li)
            # (3) SC estate/probate filings across the SC footprint.
            for county in SC_FOOTPRINT:
                items = await _query(
                    c, _SC, county, SC_PROBATE_TYPE, from_ms, now_ms
                )
                for it in items:
                    li = self._sc_probate_listing(it, county)
                    if li is not None:
                        out.append(li)

        # Dedup on Column `id`. Every id carries a "-N" publication-run suffix
        # (verified live: the SAME notice reappears as "...-0", "...-1" across
        # publication dates), so we collapse on the BASE id (suffix stripped).
        # Results arrive newest-first (sort desc by publishedtimestamp), so the
        # first row per base id is the most recent run — keep it.
        deduped: list[Listing] = []
        for li in out:
            cid = (li.raw.get("column", {}) or {}).get("id") or ""
            base = re.sub(r"-\d+$", "", cid) if cid else ""
            key = base or li.source_url
            if key in seen_ids:
                continue
            seen_ids.add(key)
            deduped.append(li)

        log.info(
            "column.done",
            total=len(out), deduped=len(deduped),
            nc_counties=len(NC_FOOTPRINT), sc_counties=len(SC_FOOTPRINT),
        )
        return deduped

    # ----------------------------------------------------------------- #
    def _common_raw(self, it: dict) -> dict:
        return {
            "column": {
                "id": it.get("id"),
                "newspapername": it.get("newspapername"),
                "filer": it.get("filer"),
                "pdfurl": it.get("pdfurl"),
                "noticetype": it.get("noticetype"),
                "publishedtimestamp": it.get("publishedtimestamp"),
            }
        }

    def _published_dt(self, it: dict) -> datetime:
        ts = it.get("publishedtimestamp")
        try:
            return datetime.utcfromtimestamp(int(ts) / 1000.0)
        except Exception:
            return datetime.utcnow()

    def _nc_listing(self, it: dict, county: str) -> Listing | None:
        text = it.get("text") or ""
        if not text.strip():
            return None
        parsed = _parse_nc_foreclosure(text)
        raw = self._common_raw(it)
        raw["column"]["snippet"] = _norm(text)[:800]
        if parsed.get("sale_date_raw"):
            raw["column"]["sale_date_raw"] = parsed["sale_date_raw"]
        if parsed.get("dot_book"):
            raw["column"]["deed_of_trust"] = {
                "book": parsed.get("dot_book"), "page": parsed.get("dot_page")
            }
        # pdfurl is the reachable detail link; fall back to the API URL anchored
        # by id so source_url is always unique + dedupe-safe.
        src_url = it.get("pdfurl") or f"{API_URL}#{it.get('id') or ''}"
        published = self._published_dt(it)
        return Listing(
            source=self.slug,
            source_url=src_url,
            listing_type=ListingType.FORECLOSURE_SALE,
            property_kind=PropertyKind.UNKNOWN,
            foreclosure_process="power_of_sale",
            state="NC",
            county=county,
            street_address=parsed.get("street_address"),
            city=parsed.get("city"),
            zip_code=parsed.get("zip_code"),
            parcel_id=parsed.get("parcel_id"),
            owner_name=parsed.get("owner_name"),
            trustee=parsed.get("trustee"),
            case_number=parsed.get("case_number"),
            sale_date=parsed.get("sale_date"),
            sale_time=parsed.get("sale_time"),
            description=_norm(text)[:500],
            first_seen=published,
            last_seen=datetime.utcnow(),
            raw=raw,
        )

    def _sc_probate_listing(self, it: dict, county: str) -> Listing | None:
        text = it.get("text") or ""
        if not text.strip():
            return None
        parsed = _parse_sc_probate(text)
        raw = self._common_raw(it)
        raw["column"]["snippet"] = _norm(text)[:800]
        probate: dict = {}
        if parsed.get("date_of_death_raw"):
            probate["date_of_death"] = parsed["date_of_death_raw"]
        if parsed.get("personal_representative"):
            probate["personal_representative"] = parsed["personal_representative"]
        if probate:
            raw["probate"] = probate
        src_url = it.get("pdfurl") or f"{API_URL}#{it.get('id') or ''}"
        published = self._published_dt(it)
        # Probate leads are address-less by design; the owner-to-GIS enricher
        # backfills the property from the decedent name. owner_name = decedent.
        return Listing(
            source=self.slug,
            source_url=src_url,
            listing_type=ListingType.PROBATE_NOTICE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC",
            county=county,
            owner_name=parsed.get("owner_name"),
            defendant=parsed.get("owner_name"),  # decedent — drives name backfill
            case_number=parsed.get("case_number"),
            description=_norm(text)[:500],
            first_seen=published,
            last_seen=datetime.utcnow(),
            raw=raw,
        )

    def _nc_estate_listing(self, it: dict, county: str) -> Listing | None:
        """NC decedent/estate notice -> PROBATE_NOTICE lead (NC mortality lane).

        Same emit shape as the SC probate lead: owner_name = decedent (drives
        the owner-to-GIS address backfill), address-less by design. Executor/PR
        + NC estate file number land in raw["probate"]. The NC estate file# is
        NOT a foreclosure SP case number, so it goes in raw, not case_number,
        to avoid polluting cross-source case-number dedup.
        """
        text = it.get("text") or ""
        if not text.strip():
            return None
        parsed = _parse_nc_estate(text)
        # A real lead needs at least a decedent name; skip un-parseable bodies
        # (the snippet still records the raw notice for audit).
        if not parsed.get("owner_name"):
            return None
        raw = self._common_raw(it)
        raw["column"]["snippet"] = _norm(text)[:800]
        probate: dict = {}
        if parsed.get("file_number"):
            probate["nc_estate_file_no"] = parsed["file_number"]
        if parsed.get("personal_representative"):
            probate["personal_representative"] = parsed["personal_representative"]
        if parsed.get("pr_role"):
            probate["pr_role"] = parsed["pr_role"]
        if probate:
            raw["probate"] = probate
        src_url = it.get("pdfurl") or f"{API_URL}#{it.get('id') or ''}"
        published = self._published_dt(it)
        return Listing(
            source=self.slug,
            source_url=src_url,
            listing_type=ListingType.PROBATE_NOTICE,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county=county,
            owner_name=parsed.get("owner_name"),
            defendant=parsed.get("owner_name"),  # decedent — drives name backfill
            description=_norm(text)[:500],
            first_seen=published,
            last_seen=datetime.utcnow(),
            raw=raw,
        )
