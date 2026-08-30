"""Shared parser for TownNews (TNCMS) legal-classifieds RSS feeds.

Many SC/NC community papers run on the TownNews / BLOX (TNCMS) platform, which
exposes every classifieds category as an RSS feed via `?f=rss`. Adding a free
keyword filter (`&q=foreclosure`) returns ONLY the foreclosure / trustee-sale /
mortgage-foreclosure legal notices — published days-to-weeks BEFORE the auction,
which is exactly the pre-auction signal we want.

Why RSS and not the HTML detail page: the TownNews ad detail body is rendered
client-side (the server HTML ships an empty `.asset-body` div). The notice text
we need is, however, fully present in two server-side places:

  1. the RSS `<title>` — TownNews uses the FIRST line of the legal ad as the
     title, so for trustee-SALE notices it carries the case number AND the
     property street address (e.g. "NOTICE OF SUBSTITUTE TRUSTEE'S FORECLOSURE
     SALE OF REAL PROPERTY 26SP000053-150 294 CAPE LOOKOUT DR HARKERS ISLAND,
     NC ..."); for SC mortgage-foreclosure summonses it carries the county +
     C/A number.
  2. the RSS `<description>` — the opening ~250 chars of the body, which adds
     the parties (plaintiff / defendant).

Both are static server-rendered XML — no JS, no login, no WAF. Compliant.

This module is import-safe (no `BaseScraper` subclass), so the registry's
auto-discovery skips it (the registry only picks up concrete subclasses, and
underscore-prefixed module names are excluded anyway).
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...models import Listing, ListingType, PropertyKind

# Street suffix alternation, shared by the address matcher.
_SUFFIX = (
    r"Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|Highway|Hwy|"
    r"Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|"
    r"Parkway|Pkwy|Terrace|Ter|Loop|Cove|Cv|Run|Pass|Point|Pt|Path|"
    r"Crossing|Xing|Landing|Ldg|Bay|Walk"
)
# A street address embedded in a legal-notice headline / body.
# The street NAME must start with a letter (so a bare suffix immediately after
# the house number — e.g. "001497 ... ST" from a mangled case number — won't
# match). 1-4 name tokens before the suffix.
ADDR_RE = re.compile(
    r"\b(\d{1,6}\s+[A-Za-z][A-Za-z0-9.'\-]*"
    r"(?:\s+[A-Za-z][A-Za-z0-9.'\-]*){0,3}\s+"
    rf"(?:{_SUFFIX})\.?)\b",
    re.I,
)
# NC: 26SP000053-150 / 24 SP 123
NC_CASE_RE = re.compile(
    r"\b(\d{2,4}\s?-?\s?(?:SP|CVD|CVS|CV|M)\s?-?\s?\d{1,6}(?:-\d{2,4})?)\b",
    re.I,
)
# SC: 2026-CP-10-01481 / 2026CP1001636 / "Case No: 2025-CP-10-01481"
SC_CASE_RE = re.compile(
    r"\b(\d{4}\s?-?\s?CP\s?-?\s?\d{2}\s?-?\s?\d{3,6})\b",
    re.I,
)
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
# City directly preceding the state token. Allow ALL-CAPS or Title-case names.
CITY_STATE_RE = re.compile(
    r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2}),\s*(NC|SC)\b"
)
SALE_DATE_RE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})"
    # Optional clock time that follows the date ("... on June 23, 2026 at 2:00 PM").
    r"(?:,?\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*[AaPp]\.?[Mm]\.?))?",
    re.I,
)
# A county name explicitly stated in the notice ("COUNTY OF BERKELEY",
# "BERKELEY COUNTY", "CARTERET COUNTY").
COUNTY_OF_RE = re.compile(r"COUNTY\s+OF\s+([A-Z][A-Za-z]+)", re.I)
COUNTY_SUFFIX_RE = re.compile(r"\b([A-Z][A-Za-z]+)\s+COUNTY\b", re.I)

# Substitute-trustee / firm name often appears in the body.
TRUSTEE_RE = re.compile(
    r"([A-Z][A-Za-z &,.'\-]+?(?:LLC|LLP|PLLC|P\.?A\.?|P\.?C\.?|Law Firm|"
    r"Attorneys?|Trustee Services|Default Services))",
)

# --- Party captions (plaintiff / defendant / record owner) ------------------
# SC civil captions read "<Plaintiff>, Plaintiff ... vs. <Defendant>, Defendant".
# The name char-class deliberately excludes '/' ':' '(' ')' so a capture can't run
# backward through the court-caption boilerplate ("... COMMON PLEAS C/A NO: 2026CP...
# (NON-JURY MORTGAGE FORECLOSURE)"); any leftover boilerplate prefix that survives
# ("SUMMONS AND NOTICES") is trimmed by _strip_caption().
PLAINTIFF_RE = re.compile(
    r"([A-Z][A-Za-z0-9 &,.'\-]{2,70}?),?\s+Plaintiffs?\b", re.I
)
DEFENDANT_RE = re.compile(
    r"\bvs?\.?\s+([A-Z][A-Za-z0-9 &,.'\-]{2,70}?),?\s+Defendants?\b", re.I
)
# NC substitute-trustee notices name the current owner under this label.
RECORD_OWNER_RE = re.compile(
    r"PRESENT RECORD OWNER\(?S?\)?\s*:?\s*"
    r"([A-Z][A-Za-z.'\- ]{2,70}?)(?:\)|,|\s+to\s+|$)", re.I
)
# Boilerplate that may cling to the FRONT of a captured party name — trimmed off.
_CAPTION_BOILER_RE = re.compile(
    r".*\b(?:COMMON PLEAS|SUMMONS(?:\s+AND\s+NOTICES?)?|NOTICES?|CIVIL ACTION|"
    r"FORECLOSURE)\)?\s*", re.I | re.S
)
# A stripped name still carrying caption words is not a real party -> reject.
_PARTY_REJECT_RE = re.compile(
    r"\b(STATE OF|COUNTY OF|COURT|VIRTUE|JUDGMENT|COMMON PLEAS|NOTICE|"
    r"SUMMONS|CIVIL ACTION|PLEAS|IN THE)\b", re.I
)

FORECLOSURE_HINTS = (
    "foreclos",
    "substitute trustee",
    "trustee's sale",
    "trustees sale",
    "master in equity",
    "notice of sale",
    "mortgage fore",
    "sale of real",
    "judicial sale",
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _strip_caption(name: str | None) -> str | None:
    """Trim leading court-caption boilerplate off a captured party name and
    reject a capture that is really boilerplate (not a person/entity)."""
    if not name:
        return None
    n = _CAPTION_BOILER_RE.sub("", name).strip(" ,.;:-")
    n = re.sub(r"\s+", " ", n)
    if len(n) < 3 or not re.search(r"[A-Za-z]{2}", n):
        return None
    if _PARTY_REJECT_RE.search(n):
        return None
    return n


def _is_foreclosure(text: str) -> bool:
    t = text.lower()
    return any(h in t for h in FORECLOSURE_HINTS)


def _classify(text: str) -> ListingType:
    t = text.lower()
    if "master in equity" in t:
        return ListingType.FORECLOSURE_SALE
    if "substitute trustee" in t or "trustee's sale" in t or "trustees sale" in t:
        return ListingType.FORECLOSURE_SALE
    if "notice of sale" in t or "sale of real" in t:
        return ListingType.FORECLOSURE_SALE
    # SC mortgage-foreclosure summons = lis-pendens-stage (pre-sale) signal
    if "summons" in t and "foreclos" in t:
        return ListingType.LIS_PENDENS
    return ListingType.FORECLOSURE_SALE


def _process(text: str, state: str) -> str | None:
    t = text.lower()
    if state == "SC" or "master in equity" in t or "common pleas" in t:
        return "judicial"
    if "substitute trustee" in t or "power of sale" in t or "deed of trust" in t:
        return "power_of_sale"
    return None


def parse_rss_items(
    xml: str,
    *,
    source_slug: str,
    default_state: str,
    default_county: str | None,
    allowed_states: tuple[str, ...] = ("NC", "SC"),
    sale_location: str | None = None,
) -> Iterable[Listing]:
    """Parse a TownNews legal-classifieds RSS feed into foreclosure Listings.

    `default_county` is the paper's home county (used when the notice text
    doesn't name a county explicitly). Notices that DO name a county override it,
    so a regional paper that publishes a neighboring county's notice is routed
    correctly.
    """
    out: list[Listing] = []
    seen: set[str] = set()
    items = re.findall(r"<item>(.*?)</item>", xml, re.S | re.I)
    for raw_item in items:
        title_m = re.search(r"<title>(.*?)</title>", raw_item, re.S | re.I)
        link_m = re.search(r"<link>(.*?)</link>", raw_item, re.S | re.I)
        desc_m = re.search(r"<description>(.*?)</description>", raw_item, re.S | re.I)
        date_m = re.search(r"<pubDate>(.*?)</pubDate>", raw_item, re.S | re.I)

        title = _clean(title_m.group(1)) if title_m else ""
        link = _clean(link_m.group(1)) if link_m else ""
        desc = _clean(desc_m.group(1)) if desc_m else ""
        blob = f"{title} {desc}".strip()
        if not blob or not link:
            continue
        if not _is_foreclosure(blob):
            continue

        key = link
        if key in seen:
            continue
        seen.add(key)

        # State: prefer an explicit state token in the notice.
        st = default_state
        st_m = re.search(r"\b(NORTH CAROLINA|SOUTH CAROLINA|\bNC\b|\bSC\b)", blob, re.I)
        if st_m:
            tok = st_m.group(1).upper()
            st = "NC" if "NORTH" in tok or tok == "NC" else "SC"
        if allowed_states and st not in allowed_states:
            continue

        # County: explicit "COUNTY OF X" / "X COUNTY" wins over the paper default.
        county = default_county
        c_m = COUNTY_OF_RE.search(blob) or COUNTY_SUFFIX_RE.search(blob)
        if c_m:
            cand = c_m.group(1).strip().title()
            # Guard against grabbing court words.
            if cand.lower() not in {"common", "general", "the", "this"}:
                county = cand

        # Case number: try the full SC C/A form first (so we don't truncate
        # 2025-CP-10-01481 to 2025-CP-10), then the NC SP/CV forms.
        case_number = None
        case_raw = None
        sc_m = SC_CASE_RE.search(blob)
        nc_m = NC_CASE_RE.search(blob)
        if st == "SC" and sc_m:
            case_raw, case_number = sc_m.group(1), re.sub(r"\s+", "", sc_m.group(1)).upper()
        elif st == "NC" and nc_m:
            case_raw, case_number = nc_m.group(1), re.sub(r"\s+", "", nc_m.group(1)).upper()
        elif sc_m:
            case_raw, case_number = sc_m.group(1), re.sub(r"\s+", "", sc_m.group(1)).upper()
        elif nc_m:
            case_raw, case_number = nc_m.group(1), re.sub(r"\s+", "", nc_m.group(1)).upper()

        # Remove the literal case number from the text before address parsing —
        # otherwise the case suffix digits (e.g. "...053-150 294 CAPE LOOKOUT
        # DR") glue onto the house number and corrupt the address.
        addr_blob = blob.replace(case_raw, " ", 1) if case_raw else blob

        addr_m = ADDR_RE.search(addr_blob)
        street = addr_m.group(1).strip() if addr_m else None
        if street:
            street = re.sub(r"\s+", " ", street).rstrip(".,").strip()
            # Reject obvious non-addresses (a bare suffix word, or all-caps
            # legal boilerplate that slipped through).
            if len(street) < 6 or not re.search(r"[A-Za-z]{3,}", street):
                street = None

        city = None
        zip_code = None
        cs_m = CITY_STATE_RE.search(addr_blob)
        if cs_m:
            cand = cs_m.group(1).strip()
            # Drop a leading street-suffix token misread as part of the city
            # ("DR HARKERS ISLAND" -> "HARKERS ISLAND").
            cand = re.sub(rf"^(?:{_SUFFIX})\s+", "", cand, flags=re.I).strip()
            # Title-case ALL-CAPS city names for consistency with other sources.
            if cand.isupper():
                cand = cand.title()
            if 2 <= len(cand) <= 40:
                city = cand or None
        z_m = ZIP_RE.search(addr_blob)
        if z_m:
            zip_code = z_m.group(1)

        sale_date = None
        sale_time = None
        sd_m = SALE_DATE_RE.search(blob)
        if sd_m:
            try:
                sale_date = dateparser.parse(sd_m.group(1), fuzzy=True)
            except (ValueError, TypeError, OverflowError):
                sale_date = None
            if sd_m.group(2):
                sale_time = re.sub(r"\s+", " ", sd_m.group(2)).strip().upper().rstrip(".")

        # Parties: NC "PRESENT RECORD OWNER(S)" names the owner directly; SC civil
        # captions carry "<Plaintiff>, Plaintiff ... vs. <Defendant>, Defendant".
        # owner_name mirrors the defendant/record-owner (the property owner).
        plaintiff = None
        pl_m = PLAINTIFF_RE.search(blob)
        if pl_m:
            plaintiff = _strip_caption(pl_m.group(1))

        defendant = None
        owner_name = None
        ro_m = RECORD_OWNER_RE.search(blob)
        if ro_m:
            cand = _clean(ro_m.group(1)).rstrip(",.;: ")
            if len(cand) >= 3 and re.search(r"[A-Za-z]{2}", cand):
                owner_name = cand
                defendant = cand
        if defendant is None:
            df_m = DEFENDANT_RE.search(blob)
            if df_m:
                cand = _strip_caption(df_m.group(1))
                if cand:
                    defendant = cand
                    owner_name = cand

        trustee = None
        tr_m = TRUSTEE_RE.search(desc) or TRUSTEE_RE.search(title)
        if tr_m:
            cand = tr_m.group(1).strip()[:160]
            if len(cand) > 4 and cand.lower() not in {"the", "this"}:
                trustee = cand

        listing_type = _classify(blob)
        proc = _process(blob, st)

        pub_dt = None
        if date_m:
            try:
                pub_dt = dateparser.parse(_clean(date_m.group(1)))
            except (ValueError, TypeError, OverflowError):
                pub_dt = None

        out.append(
            Listing(
                source=source_slug,
                source_url=link,
                listing_type=listing_type,
                property_kind=PropertyKind.UNKNOWN,
                state=st,
                county=county,
                street_address=street,
                city=city,
                zip_code=zip_code,
                sale_date=sale_date,
                sale_time=sale_time,
                sale_location=sale_location,
                foreclosure_process=proc,
                case_number=case_number,
                plaintiff=plaintiff,
                defendant=defendant,
                owner_name=owner_name,
                trustee=trustee,
                description=(title or desc)[:500] or None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "townnews_legal": {
                        "title": title,
                        "desc": desc[:1500],
                        "published": pub_dt.isoformat() if pub_dt else None,
                    }
                },
            )
        )
    return out
