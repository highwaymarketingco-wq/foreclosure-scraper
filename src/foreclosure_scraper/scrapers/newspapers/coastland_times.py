"""The Coastland Times (Manteo, NC) — Dare County public-notice foreclosures.

The Coastland Times is the legal-notice paper of record for Dare County, NC
(the Outer Banks: Manteo, Nags Head, Kill Devil Hills, Rodanthe, Hatteras) —
part of the coastal NC footprint. Its public-notices section carries the NC
substitute-trustee foreclosure-sale notices ("NOTICE OF FORECLOSURE SALE" /
"NOTICE OF SALE") published days-to-weeks BEFORE the auction — the pre-auction
signal we want.

Unlike most of our newspaper sources, the Coastland Times does NOT run on
TownNews/RSS — it's a custom pubgen.ai CMS. The notice index lives at
`/tags/public-notices` (mirrored at `/sections/public-notices`); each notice is
a `/public-notices/<slug>-<hash>` detail page whose body is server-rendered
inside the `<main>` element (no JS needed for the data we read).

Compliance note: the index 403s on a bare httpx request (no `User-Agent`). It
serves normally once we present a real desktop-browser header set — this is the
exact same StealthyFetcher-style fingerprint the shared client already uses, NOT
a CAPTCHA/WAF solver. We pass that header set through `get_text(headers=...)`;
plain GETs over HTTP/2 with a real UA clear the 403 (verified live).

NC substitute-trustee notices reliably carry, in prose:
  - the property street address ("said property being located at
    22083 Sea Gull Street, Rodanthe, North Carolina");
  - the county Register of Deeds / sale courthouse ("courthouse door in Manteo,
    Dare County, North Carolina");
  - the sale date + time ("at 10:30 AM on June 23, 2026");
  - the substitute trustee ("Substitute Trustee Services, Inc.");
  - the county tax parcel ("Dare County Parcel Number 012458006").

Verified live (2026-06-26): the public-notices index listed two current
foreclosure notices; the foreclosure-sale notice parsed to 22083 Sea Gull St,
Rodanthe (Dare NC), sale 2026-06-23 10:30 AM, trustee Substitute Trustee
Services Inc., parcel 012458006 — a clean pre-auction coastal lead.

Free, no login, no WAF solver, no JS for the data we read.

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 1),
all confirmed live, none previously documented:

1. **A severe, 100%-dead-on-arrival scope bug, present since this scraper's
   creation.** Every row was classified `ListingType.FORECLOSURE_SALE` (a
   "flip" type) and hardcoded `county="Dare"`. Dare is never in the 18-county
   WNC+Upstate-SC flip footprint, and `main._flip_outside_footprint()`
   rejects any flip-type row outside that footprint unconditionally, before
   any oceanfront/coastal-bypass carve-out runs. Confirmed by calling the
   real `main._in_scope()` directly: `county="Dare", listing_type=
   FORECLOSURE_SALE` -> `False`, every time. `main.py` already lists
   `"newspapers.coastland_times"` in `COASTAL_COUNTY_BYPASS_SOURCES` (a
   dedicated admission path built for exactly this source), but that
   bypass's own `if _is_flip(li): return False` guard made the registration
   dead code as long as this module kept emitting a flip type. Rows are now
   classified `TAX_SALE` (county Commissioner's tax sale) or `LIS_PENDENS`
   (private substitute-trustee power-of-sale notice) — both non-flip, both
   confirmed live via `main._in_scope()` to reach the board (via the
   dedicated coastal bypass for Dare, or the unrestricted NC/SC distressed
   scope for any other county this paper names). See `_parse_detail()`.
2. **A real county-mislabeling correctness bug.** The Coastland Times also
   carries notices for neighboring counties — live-confirmed on a real
   current "NOTICE OF TAX FORECLOSURE SALE" naming Tyrrell County 3 times in
   its own body text ("District Court of Tyrrell County"... "courthouse door
   in Tyrrell County"... "Tyrrell County Register of Deeds"), which this
   module stamped `county="Dare"` regardless. Now resolved from the notice's
   own text via `_resolve_notice_county()`, falling back to "Dare" (this
   paper's home county) only when no county is named.
3. **A real parcel-ID extraction miss.** The same live Tyrrell notice states
   "Parcel Identification Number: C005 19 010" in plain text — `PARCEL_RE`
   required "Parcel" to be followed directly by "Number/No/ID" (no
   "Identification") and had no way to match a space-separated ID, so this
   real, stated parcel number was silently dropped. Fixed (see `PARCEL_RE`).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ._townnews import NC_CASE_RE
from .column_legal_notices import _notice_email

BASE = "https://www.thecoastlandtimes.com"
# Both the tag view and the section view list the same notices; we read both and
# dedupe by detail URL so a layout change to one doesn't silently zero the run.
INDEX_URLS = (
    f"{BASE}/tags/public-notices",
    f"{BASE}/sections/public-notices",
)

# Real desktop-browser header set. The bare default httpx request (no UA) gets a
# 403 from the CMS edge; presenting a normal browser fingerprint serves the page
# (compliant — no solver, no challenge bypass). Mirrors http_client.DEFAULT_HEADERS.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": f"{BASE}/",
    "Upgrade-Insecure-Requests": "1",
}

# A detail link under /public-notices/. We keep only those whose slug hints at a
# foreclosure / trustee sale (the body is re-checked on the detail page anyway).
DETAIL_RE = re.compile(r'href="(/public-notices/[^"#?]+)"', re.I)
FORECLOSURE_SLUG_HINTS = ("foreclosure", "notice-of-sale", "trustee", "substitute")

# Phrases that confirm a detail page is actually a foreclosure/trustee sale.
FORECLOSURE_BODY_HINTS = (
    "foreclos",
    "substitute trustee",
    "power of sale",
    "deed of trust",
    "trustee will offer for sale",
    "offered for sale",
)

# "said property being located at 22083 Sea Gull Street, Rodanthe, North Carolina"
LOCATED_AT_RE = re.compile(
    r"located\s+at\s+(\d{1,6}\s+[A-Za-z0-9][\w .'\-]*?),\s*"
    r"([A-Za-z][A-Za-z .'\-]+?),\s*(?:North Carolina|NC)\b",
    re.I,
)
# Fallback bare street address anywhere in the body.
_SUFFIX = (
    r"Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|Highway|Hwy|Boulevard|Blvd|"
    r"Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy|Terrace|Ter|Loop|Cove"
)
ADDR_RE = re.compile(
    rf"\b(\d{{1,6}}\s+[A-Za-z][\w .'\-]*?\s+(?:{_SUFFIX})\.?)\b", re.I
)
# "Dare County Parcel Number 012458006" / "Parcel Number: 012458006" /
# "Parcel Identification Number: C005 19 010" (tax-foreclosure notices use
# this longer label and a SPACE-separated ID, e.g. "C005 19 010" -- found
# live 2026-10-04 on a real current Tyrrell County notice: the old pattern
# required "Parcel" to be followed directly by "Number/No/ID" and had no way
# to match an ID with an internal space, so this real, plainly-stated parcel
# number was silently dropped. Each group must contain a digit (the `(?=...)`
# lookahead) so a following plain word like "The" (as in "...010 The
# undersigned Commissioner...") can't be absorbed as a spurious extra group.
_PARCEL_GROUP = r"(?=[A-Za-z0-9\-\.]*\d)[A-Za-z0-9\-\.]{1,20}"
PARCEL_RE = re.compile(
    rf"(?:County\s+)?Parcel\s+(?:Identification\s+)?(?:Number|No\.?|ID)?\s*[:#]?\s*"
    rf"({_PARCEL_GROUP}(?:\s+{_PARCEL_GROUP}){{0,3}})",
    re.I,
)
# "at 10:30 AM on June 23, 2026"  -> capture time + date together.
SALE_DT_RE = re.compile(
    r"at\s+(\d{1,2}:\d{2}\s*(?:AM|PM))\s+on\s+"
    r"((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})",
    re.I,
)
# Bare date fallback ("on June 23, 2026").
DATE_RE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})",
    re.I,
)
SALE_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b", re.I)
ZIP_RE = re.compile(r"\b(27\d{3})(?:-\d{4})?\b")  # Dare/OBX zips are all 27xxx
# Substitute-trustee / firm name. The borrower's own LLC also appears ("made by
# Sea Strand LLC"), so we DON'T do a generic firm-suffix grab. Instead we anchor
# directly on the named trustee-service firms (self-contained names; no arbitrary
# leading capture that could swallow the preceding clause). Up to 3 capitalized
# name tokens may precede the "...Trustee Services, Inc." tail.
TRUSTEE_NAMED_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z.'\-]+\s+){0,3}"
    r"(?:Substitute\s+)?Trustee\s+Services,?\s*Inc\.?)",
)
# "Substitute Trustee: <Firm>" label form, firm ends in a corporate suffix and
# is limited to 4 name tokens so it can't run into the next sentence.
TRUSTEE_LABEL_RE = re.compile(
    r"Substitute\s+Trustee[:\s]+"
    r"((?:[A-Z][A-Za-z.'\-]+[,\s]+){1,4}"
    r"(?:Inc\.?|LLC|LLP|PLLC|P\.?A\.?|P\.?C\.?|Law\s+Offices?))",
)
# Grantor of the foreclosed Deed of Trust = the current record owner ("...Deed
# of Trust executed and delivered by Jackie H. Willis" / "made by Sea Strand LLC").
# Stop at the clause boundary so we don't swallow "to <Trustee>, dated ...".
GRANTOR_RE = re.compile(
    r"(?:executed(?:\s+and\s+delivered)?|made|given)\s+by\s+"
    r"([A-Z][A-Za-z0-9.'\- ]{2,70}?)"
    r"(?:\s*\(|,|;|\s+(?:dated|to\s+[A-Z]|and\s+recorded|in\s+favor|"
    r"as\s+grantor|Trustee)|$)",
    re.I,
)
# Many NC substitute-trustee notices use a labeled-field template instead of
# the "said property being located at <street>" prose LOCATED_AT_RE expects:
#   "... Record Owners: Heirs of Janson Fros Address of Property: 4013 Mill
#   Landing Road Wanchese, NC 27981 ... Grantors: Janson Fros, unmarried ..."
# Found live 2026-10-01: before these labels were read, LOCATED_AT_RE/ADDR_RE
# fell through to matching "10:30 a.m. Place of Sale" as if it were a street
# address ("30 a.m. Place") -- a fabricated, wrong value in a REAL listing --
# while the genuine address sat a few words later under its own clean label.
# These labels are unambiguous, so they take priority over the prose/fallback
# patterns when present.
RECORD_OWNERS_LABEL_RE = re.compile(
    r"Record\s+Owners?:\s*(.+?)\s*(?=Address\s+of\s+Property:|$)", re.I
)
ADDRESS_OF_PROPERTY_LABEL_RE = re.compile(
    rf"Address\s+of\s+Property:\s*(\d{{1,6}}\s+[\w .'\-]*?(?:{_SUFFIX}))\.?,?\s+"
    r"([A-Za-z][A-Za-z .'\-]*?),?\s*(?:NC|North Carolina)\s+(\d{5})",
    re.I,
)
GRANTORS_LABEL_RE = re.compile(
    r"Grantors?:\s*(.+?)\s*(?=Original\s+Beneficiary:|Dated:|Book\s*:|$)", re.I
)
# Tax-foreclosure notices (Commissioner's sale, not a substitute trustee) date
# the sale as an ordinal clause instead of "on <Month> <day>, <year>":
#   "...will on the 17th day of July, 2026, offer for sale..."
# plus an "o'clock" time form ("at 12:00 o'clock, noon").
ORDINAL_DATE_RE = re.compile(
    r"\bon\s+the\s+(\d{1,2})(?:st|nd|rd|th)\s+day\s+of\s+"
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s*,?\s*(\d{4})",
    re.I,
)
OCLOCK_TIME_RE = re.compile(
    r"\bat\s+(\d{1,2}(?::\d{2})?)\s*o.?clock,?\s*(noon|midnight|[ap]\.?m\.?)?",
    re.I,
)
# FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 1):
# this module hardcoded county="Dare" on every row, but The Coastland Times
# also carries notices for neighboring counties -- live-confirmed on a real
# current notice ("NOTICE OF TAX FORECLOSURE SALE... District Court of
# Tyrrell County, North Carolina... courthouse door in Tyrrell County...
# Tyrrell County Register of Deeds") that was being mislabeled county="Dare"
# despite the body explicitly, repeatedly naming Tyrrell. The notice always
# states its own county plainly (a tax-foreclosure's "<County> County
# Register of Deeds" closing line, or a trustee notice's "courthouse door in
# <County>, <State>" clause) -- extracted here and used when present, with
# "Dare" (this paper's home county) kept as the fallback default.
COUNTY_NAMED_RE = re.compile(r"\b([A-Z][a-z]+)\s+County\b")
# "NOTICE OF TAX FORECLOSURE SALE" -- a county Commissioner's ad valorem tax
# sale, distinct from a private substitute-trustee power-of-sale notice.
# models.ListingType.TAX_SALE already exists for exactly this and (like
# LIS_PENDENS) is not a "flip" type -- see the listing_type comment below.
_TAX_FORECLOSURE_RE = re.compile(r"tax\s+foreclos", re.I)


def _resolve_notice_county(blob: str) -> str:
    """Best-effort real county from the notice's own text; "Dare" (this
    paper's home county) when none is named. Validated against the real NC
    county list so a false match (e.g. a law-firm name that happens to
    contain "<Word> County") can't silently mislabel a row."""
    from ...validation import NC_COUNTIES

    names = {c.lower(): c for c in NC_COUNTIES}
    for m in COUNTY_NAMED_RE.finditer(blob):
        cand = m.group(1).strip().lower()
        hit = names.get(cand)
        if hit:
            return hit
    return "Dare"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _is_foreclosure(text: str) -> bool:
    t = text.lower()
    return any(h in t for h in FORECLOSURE_BODY_HINTS)


def _extract_body(html: str) -> tuple[str, str]:
    """Return (headline, body_text) from a notice detail page.

    Body = concatenated <p> text inside <main> (the rendered notice). JSON-LD
    blobs and page chrome are dropped first so they don't pollute the parse.
    """
    tree = HTMLParser(html)
    for tag in tree.css("script, style, nav, header, footer"):
        tag.decompose()
    h1 = tree.css_first("h1")
    headline = _clean(h1.text(strip=True)) if h1 else ""
    main = tree.css_first("main") or tree.body
    if main is None:
        return headline, ""
    paras = [
        _clean(p.text(separator=" "))
        for p in main.css("p")
        if len(_clean(p.text(separator=" "))) > 15
    ]
    return headline, " ".join(paras)


def _parse_detail(html: str, url: str, slug: str) -> Listing | None:
    headline, body = _extract_body(html)
    blob = f"{headline} {body}".strip()
    if not blob or not _is_foreclosure(blob):
        return None

    # Address: prefer the unambiguous "Address of Property:" LABEL when the
    # notice uses that template -- checked FIRST, before the prose/fallback
    # patterns, because those were matching "10:30 a.m. Place of Sale" as a
    # fabricated street address ("30 a.m. Place") on this template (found
    # live 2026-10-01) while the genuine address sat a few words later under
    # its own clean label.
    street = city = None
    zip_code = None
    aop_m = ADDRESS_OF_PROPERTY_LABEL_RE.search(body)
    if aop_m:
        street = _clean(aop_m.group(1)).rstrip(".,")
        cand_city = _clean(aop_m.group(2)).rstrip(".,")
        if cand_city.isupper():
            cand_city = cand_city.title()
        if 2 <= len(cand_city) <= 40:
            city = cand_city
        zip_code = aop_m.group(3)
    if not street:
        m = LOCATED_AT_RE.search(body)
        if m:
            street = _clean(m.group(1)).rstrip(".,")
            cand_city = _clean(m.group(2)).rstrip(".,")
            if cand_city.isupper():
                cand_city = cand_city.title()
            if 2 <= len(cand_city) <= 40:
                city = cand_city
    if not street:
        am = ADDR_RE.search(body)
        if am:
            cand = _clean(am.group(1)).rstrip(".,")
            # Reject the "10:30 a.m. Place of Sale" boilerplate phrase this
            # template's own time-of-sale clause produces ("30 a.m. Place")
            # -- a fabricated address this ADDR_RE fallback would otherwise
            # accept on any notice using this time/place wording that lacks
            # the "Address of Property:" label handled above.
            if len(cand) >= 6 and re.search(r"[A-Za-z]{3,}", cand) and not re.search(
                r"^\d+\s*[ap]\.?m\.?\s+Place\b", cand, re.I
            ):
                street = cand

    if zip_code is None:
        zm = ZIP_RE.search(body)
        if zm:
            zip_code = zm.group(1)

    parcel = None
    pm = PARCEL_RE.search(body)
    if pm:
        cand = pm.group(1).strip().rstrip(".,")
        if re.search(r"\d", cand):
            parcel = cand

    # Sale date + time: the combined "at <time> on <date>" form is the trustee
    # sale; fall back to a bare date if the combined form isn't present.
    sale_date = None
    sale_time = None
    dt_m = SALE_DT_RE.search(body)
    if dt_m:
        sale_time = _clean(dt_m.group(1)).upper().replace(" ", " ")
        try:
            sale_date = dateparser.parse(dt_m.group(2), fuzzy=True)
        except (ValueError, TypeError, OverflowError):
            sale_date = None
    if sale_date is None:
        dm = DATE_RE.search(body)
        if dm:
            try:
                sale_date = dateparser.parse(dm.group(1), fuzzy=True)
            except (ValueError, TypeError, OverflowError):
                sale_date = None
    if sale_date is None:
        # Tax-foreclosure (Commissioner's sale) notices date the sale as an
        # ordinal clause ("...will on the 17th day of July, 2026, offer for
        # sale...") rather than "on <Month> <day>, <year>" -- found live
        # 2026-10-01 on a Tyrrell County tax-foreclosure notice, where
        # sale_date was silently None despite the date being plainly stated.
        om = ORDINAL_DATE_RE.search(body)
        if om:
            try:
                sale_date = dateparser.parse(f"{om.group(2)} {om.group(1)}, {om.group(3)}")
            except (ValueError, TypeError, OverflowError):
                sale_date = None
    if sale_time is None:
        tm = SALE_TIME_RE.search(body)
        if tm:
            sale_time = _clean(tm.group(1)).upper()
    if sale_time is None:
        # "...at 12:00 o'clock, noon" -- the ordinal-date template's own time
        # form, distinct from the "10:30 AM" form SALE_TIME_RE expects.
        ocm = OCLOCK_TIME_RE.search(body)
        if ocm:
            hm = ocm.group(1)
            suffix = (ocm.group(2) or "").strip().upper().rstrip(".")
            if suffix == "NOON":
                sale_time = "12:00 PM" if hm.startswith("12") else f"{hm} PM"
            elif suffix == "MIDNIGHT":
                sale_time = "12:00 AM" if hm.startswith("12") else f"{hm} AM"
            elif suffix in {"AM", "PM"}:
                sale_time = f"{hm} {suffix}"

    trustee = None
    tr_m = TRUSTEE_NAMED_RE.search(body) or TRUSTEE_LABEL_RE.search(body)
    if tr_m:
        cand = _clean(tr_m.group(1))[:160]
        # Strip a leading "the"/"undersigned" the named-form may carry in.
        cand = re.sub(r"^(?:the|undersigned)\s+", "", cand, flags=re.I).strip()
        if len(cand) > 4 and cand.lower() not in {"the", "this"}:
            trustee = cand

    # NC Special-Proceedings case number ("26 SP 000132-110").
    case_number = None
    cn_m = NC_CASE_RE.search(blob)
    if cn_m:
        case_number = re.sub(r"\s+", "", cn_m.group(1)).upper()

    # Owner/grantor of the foreclosed Deed of Trust = the current record
    # owner. Prefer the explicit "Record Owners:" label (most direct), then
    # "Grantors:" (also labeled), then the "executed by <name>" prose form.
    owner_name = None
    defendant = None
    ro_m = RECORD_OWNERS_LABEL_RE.search(body)
    if ro_m:
        cand = _clean(ro_m.group(1)).rstrip(",.;: ")
        if len(cand) >= 3 and re.search(r"[A-Za-z]{2}", cand):
            owner_name = cand
            defendant = cand
    if owner_name is None:
        gr_m = GRANTORS_LABEL_RE.search(body)
        if gr_m:
            cand = _clean(gr_m.group(1)).rstrip(",.;: ")
            if len(cand) >= 3 and re.search(r"[A-Za-z]{2}", cand):
                owner_name = cand
                defendant = cand
    if owner_name is None:
        g_m = GRANTOR_RE.search(body)
        if g_m:
            cand = _clean(g_m.group(1)).rstrip(",.;: ")
            if len(cand) >= 3 and re.search(r"[A-Za-z]{2}", cand):
                owner_name = cand
                defendant = cand

    # Attorney/trustee phone + email printed in the notice foot (a reachable
    # case contact, NOT the owner). Reuses the Column gold-standard extractor
    # so parcel-PIN / case-number digit runs can't leak in as a phantom phone.
    raw = {
        "coastland_times": {
            "headline": headline,
            "body": body[:1500],
        }
    }
    contact = _notice_email(body)
    if contact:
        raw["notice_contact"] = contact

    county = _resolve_notice_county(body)
    is_tax = bool(_TAX_FORECLOSURE_RE.search(blob))
    # FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers
    # batch 1): county is NEVER Dare in the 18-county flip footprint (nor is
    # any other NC county this paper names -- Tyrrell included), and
    # ListingType.FORECLOSURE_SALE is a "flip" type that main.py's
    # `_flip_outside_footprint()` rejects unconditionally outside that
    # footprint, before any oceanfront/coastal carve-out even runs --
    # confirmed live by calling the real `main._in_scope()`:
    # county="Dare"/state="NC"/listing_type=FORECLOSURE_SALE -> False, every
    # time; listing_type=LIS_PENDENS or TAX_SALE -> True (admitted via the
    # unrestricted distressed scope `main.in_scope_distressed()`, OR -- for
    # Dare specifically -- via `main.COASTAL_COUNTY_BYPASS_SOURCES`, which
    # already explicitly lists "newspapers.coastland_times" today but was
    # dead code for this source because FORECLOSURE_SALE made
    # `main._coastal_county_source()`'s own `if _is_flip(li): return False`
    # guard reject every row before that bypass could ever fire). So every
    # single real row this scraper has ever produced was silently dropped at
    # the board gate. A county tax-Commissioner's sale is classified
    # TAX_SALE (the existing, more precise type for exactly this -- the
    # headline/body literally says "NOTICE OF TAX FORECLOSURE SALE"); a
    # private substitute-trustee power-of-sale notice is classified
    # LIS_PENDENS (the same non-flip, pre-execution-sale bucket the sibling
    # SC newspaper scrapers use for their own judicial foreclosure notices).
    # Neither is a "flip" type, so both now actually reach the board.
    listing_type = ListingType.TAX_SALE if is_tax else ListingType.LIS_PENDENS
    sale_location = (
        f"{county} County Courthouse, North Carolina"
        if county != "Dare"
        else "Dare County Courthouse, Manteo NC"
    )
    return Listing(
        source=slug,
        source_url=url,
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        street_address=street,
        city=city,
        zip_code=zip_code,
        parcel_id=parcel,
        sale_date=sale_date,
        sale_time=sale_time,
        sale_location=sale_location,
        foreclosure_process="tax_foreclosure" if is_tax else "power_of_sale",
        case_number=case_number,
        owner_name=owner_name,
        defendant=defendant,
        trustee=trustee,
        description=(headline or body)[:500] or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw=raw,
    )


def _index_detail_urls(html: str) -> list[str]:
    """Foreclosure-looking /public-notices/ detail URLs from an index page."""
    out: list[str] = []
    seen: set[str] = set()
    for m in DETAIL_RE.finditer(html):
        path = m.group(1)
        low = path.lower()
        if not any(h in low for h in FORECLOSURE_SLUG_HINTS):
            continue
        url = f"{BASE}{path}"
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


class CoastlandTimesForeclosures(BaseScraper):
    slug = "newspapers.coastland_times"
    name = "The Coastland Times Public Notices (Dare NC)"
    category = "newspaper_legal"
    requires_apify = False
    # Legal-notice volume swings week to week; a quiet week with 0 foreclosure
    # notices is data reality. A real regression is the index 403ing again (the
    # block-signal classifier surfaces that separately) or the detail layout
    # changing so no body parses.
    expected_min_count = 0
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_urls: set[str] = set()
        detail_urls: list[str] = []
        for index_url in INDEX_URLS:
            try:
                html = await get_text(index_url, timeout=30.0, headers=BROWSER_HEADERS)
            except Exception:
                continue
            for u in _index_detail_urls(html):
                if u not in seen_urls:
                    seen_urls.add(u)
                    detail_urls.append(u)

        for url in detail_urls:
            try:
                page = await get_text(url, timeout=30.0, headers=BROWSER_HEADERS)
            except Exception:
                continue
            li = _parse_detail(page, url, self.slug)
            if li is not None:
                out.append(li)
        return out
