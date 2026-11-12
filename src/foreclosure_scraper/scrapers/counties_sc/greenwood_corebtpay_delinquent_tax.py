"""Greenwood County SC — standing delinquent real-property tax roll via the
county's CORE/eGov payment portal (greenwoodco.corebtpay.com).

WHY THIS EXISTS
    Greenwood is one of the ~16 SC counties `docs/completeness_audit_2026-09-29-
    evening.md` (Section 6) flags as still missing the "tax delinquent" family —
    a STANDING roll of who currently owes back taxes, as distinct from
    `counties_sc.greenwood_delinquent_tax` (already in this repo), which scrapes
    the county's ANNUAL tax-SALE list (a different page, a different listing_type,
    only live Oct-Jan). `qpaybill_delinquent_roll.py`'s own docstring already
    closes off the obvious next guess: "Greenwood was probed for this item
    ... and is a CONFIRMED MISS ... its tax payment/search system is entirely on
    corebtpay.com ... Do not re-probe qPayBill subdomain guesses for Greenwood."
    This module is that unexplored corebtpay.com path, built and verified live
    2026-09-30.

THE SITE
    greenwoodcounty-sc.gov's own Treasurer page links
    https://greenwoodco.corebtpay.com/egov/apps/payment/center.egov — CORE's
    "eGov" white-label payment platform (the same `Payments powered by CORE`
    footer, a different product from BillTrax/Catalis/qPayBill/paystar, the
    four other SC tax vendors already in this repo). The real search page is
    the "Property Tax Payments" nav link: `/egov/apps/bill/pay.egov?
    view=search;itemid=1` (itemid=1 is real-property tax; itemid=3 is vehicle,
    itemid=2 is watercraft — separate categories, not scraped here).

    That search page has NO "browse the whole roll" option (unlike BillTrax's
    blank-query-returns-everything, or qPayBill/Catalis's Type4/GUID forms) —
    it only accepts a Map/Account Number lookup or a Last Name (+ optional
    First Name) lookup. But a LAST-NAME-ONLY, case-insensitive PREFIX works
    (confirmed live): POSTing the form's `ebillSearch_fullNameFld` field as
    `"<PREFIX>|"` (the JS's own `LAST|FIRST` join with FIRST left blank)
    returns every account whose name starts with PREFIX, same shape as the
    qPayBill A-Z sweep this repo already uses elsewhere in this file's sibling
    modules.

    FORM FIELDS THAT MATTER (verified live 2026-09-30, no browser, no cookies,
    no session token — a cold POST with no prior page load returns real data):
        itemid=1, view=search, eGov_functionJS=Find Account, from=,
        ebillSearch_fullNameFld=<PREFIX>|, eGov_function=Find Account
    POST to the search page's own URL (it posts to itself, no separate API
    endpoint). Returns a normal server-rendered HTML page with a
    `<table class="eGov_listContent">` of matches — no JSON, no JS execution
    needed.

    SINGLE-LETTER PREFIXES ARE TOO BROAD FOR THIS SERVER. Verified live: a
    1-char prefix ("S|") took over 2 minutes and then the connection died
    mid-response (`HTTP/2 stream ... INTERNAL_ERROR`) — the server appears to
    choke rendering that many rows as one HTML page, not a block (headers had
    already sent `HTTP 200`). A 2-char prefix ("SM|") reliably returns in
    ~10s (1,471 rows for "SM" alone). So this module's BASE sweep unit is the
    full 2-letter alphabet space (A-Z x A-Z = 676 prefixes) rather than a
    qPayBill-style "start at 1, deepen only if capped" walk — depth 1 is
    unsafe here, not merely slower.

    THERE IS A REAL 5,000-ROW CAP, verified live and NOT assumed just because
    it is round (CLAUDE.md: "never accept a status code — or a label — as
    evidence"). "JO" returned exactly 5,000 rows; "JOH" ALONE (one of 26
    three-letter children of "JO") returned 2,817 — more than half of "JO"'s
    supposed total from a single child prefix, which is only possible if
    "JO" was truncated. This portal has no visible pager (unlike qPayBill),
    so a capped prefix cannot be paged deeper the way qPayBill's `_walk_prefix`
    does — the only recovery is re-querying with a longer prefix. `_sweep()`
    below detects `len(rows) >= PAGE_CAP` and deepens that ONE prefix into its
    26 three-letter children (discarding the capped, unreliable-coverage read
    rather than keeping a partial slice of it), up to `MAX_PREFIX_DEPTH`. Most
    2-letter prefixes never hit this (measured: "SM" 1,471, well under the
    cap) — only the handful matching very common SC surname starts do.

    ROBOTS / ACCESS POSTURE, checked 2026-09-30: robots.txt Disallows
    /egov/help, /egov/imgs, /egov/include, /egov/apps/events — NOT
    /egov/apps/bill (what this module uses) or /egov/apps/payment. Per
    CLAUDE.md a Disallow is not a wall regardless. The one thing worth
    respecting even though it is not a hard wall: `Crawl-delay: 300` is set
    site-wide. Taken literally that is one request per 5 minutes, which is
    not how this module runs (a full 676-prefix sweep at that pace would take
    weeks) — but the site's own server is independently slow (~10s per
    2-letter query, observed, not throttling on our end) and this module adds
    its own explicit pace on top of that rather than hammering it the instant
    each slow response returns, in the same spirit as `_PACE_S` in
    `dorchester_billtrax_delinquent_tax.py`.

    NO CAPTCHA, NO LOGIN, NO CLICK-THROUGH TERMS on the search or detail path.
    An optional account-login exists ("My Account") purely for the payer's own
    convenience (saved payment methods) — guest search and guest bill lookup
    are the primary, unauthenticated, intended use of the page and is all this
    module does.

THE YEAR-SUFFIX DISCOVERY (the reason this source needs its own aggregation
logic, not a reused copy of Dorchester's or qPayBill's)
    Unlike every other SC tax-roll source in this repo, Greenwood's search
    results do NOT show one row per parcel with a list of years — they show
    one row per BILL, and the "Account Number" the portal returns is NOT
    stable across years for the same parcel. Verified directly on real,
    live, multi-year data (owner "SMITH JAMES M", 2026-09-30 capture):
        67144500019  tax year 2019   67144500018  tax year 2018
        67144500017  tax year 2017
    and (owner "SMITH JOSHUA S"):
        84526800018  tax year 2018   84526800017  tax year 2017
        84526800016  tax year 2016
    In every multi-year case checked, the account number's LAST TWO DIGITS
    equal the tax year mod 100, and the remaining prefix is IDENTICAL across
    years for the same parcel. So the real, stable parcel identifier is
    `account[:-2]`, not the raw account number — `_parcel_prefix()` below
    strips it, with a sanity check (the stripped suffix must actually equal
    the row's own Tax Year mod 100) so a row that doesn't fit this shape is
    kept as its own un-aggregated lead instead of silently mis-grouped.

WHAT A RECORD CARRIES
    Search results: Account (bill-level id), Tax Year, Name on Account,
    Status (Paid / Unpaid, a Font-Awesome check/times icon + text — matched
    on the text, not the icon class, since icon classes are a thinner,
    easier-to-typo signal), Date Paid, Amount Due. The "Amount Due" column
    for a PAID row is the historical amount that bill was for, not a current
    balance — exactly the kind of label-vs-value trap CLAUDE.md warns about,
    so this module filters on the Status TEXT plus a positive Amount Due,
    never trusting one without the other (mirrors Dorchester's TotalDueNow
    check).

    Search results carry NO address. A second GET per unique parcel resolves
    it — but NOT the `view=detail` page this module originally used.

    THE BILL PAGE CARRIES THE REAL SITUS (fixed 2026-10-04, a real
    correctness bug, not just a missing field): `view=detail`'s one address
    field is labeled "Service Address", and the ORIGINAL build (2026-09-30)
    took that at face value and published it as `street_address`. Live
    re-verification 2026-10-04 proved it is actually the OWNER'S MAILING
    address, not the property's situs — for an owner-occupant the two
    happen to coincide (e.g. CREASMAN JOSHUA S AS TRUST: "213 KAYAK POINT,
    GREENWOOD, SC" both ways), but for every absentee/commercial owner they
    diverge: MUSSMAN STEVEN PATRICK's "Service Address" was his own
    Simpsonville, SC mailing address, while his actual Greenwood parcel sits
    at a completely different "512 SAND SHORE DR"; WW PLASMA IV LLC's was a
    Birmingham, AL suite. Every absentee-owner lead (precisely the
    population this project's motivated-seller engine most wants a mailing
    channel AND a real property address for) was carrying the WRONG address
    as `street_address`.

    The fix: fetch `pay.egov?view=bill;account=<account>;id=1;itemid=1`
    instead (`id=1` is a fixed literal, verified live across many accounts,
    not a per-account lookup value — no `view=detail` fetch is needed first).
    This "View This Bill" page is a strict superset of `view=detail`: the
    SAME owner name + mailing address (as a 3-line `<br>`-joined mail-merge
    block), PLUS the real `LOCATION:` (situs — genuinely blank on some
    commercial/pipeline parcels with no single address, e.g. CAROLINA GAS
    TRANSMISSION; a blank LOCATION is kept as None, never backfilled from the
    mailing address), PROPERTY DESCRIPTION (legal description), DISTRICT,
    BLDGS/LOTS/ACRES, and a full valuation block (ASSESSED VALUE, TAX VALUE
    = fair market value, the 4%-vs-6% owner-occupied/legal-residence
    assessment-ratio split, and LESS HOMESTEAD EXEMPTION) — none of which
    `view=detail` ever exposed. `street_address` is now the real LOCATION;
    the mailing address moves to `raw['owner_mailing']` (the canonical key
    `mailing_shape.mailing_of()` / `enrichment_lead_signals.py`'s absentee-
    owner check actually read — publishing it only as `street_address`
    made it invisible to that whole facet). Fetching the bill page also
    REPLACES the `view=detail` fetch rather than adding to it, so this halves
    the per-parcel request count against an already-slow, pacing-limited
    server, not just adding fields.

    A SEASONAL OBSERVATION (not a code bug, logged for the next auditor):
    live-swept 7 different 2-letter prefixes (~22,000+ rows) on 2026-10-04
    and found ZERO "Unpaid" rows anywhere — every current row (tax years
    2024/2025 only; the portal appears to retain roughly a 2-year window,
    since the 2026-09-30 build's own SMITH JAMES M multi-year 2017-2019
    example is no longer resolvable at all, even via a direct account-number
    search) is "Paid". Likely explanation, not confirmed with county staff:
    SC tax sales for a given tax year's delinquent bills run Oct-Dec of the
    FOLLOWING year, so a genuinely-still-unpaid 2025 bill is right about now
    being pulled off the "pay your bill online" portal and handed to the
    Treasurer's execution/tax-sale process — which would make a 0-row sweep
    this time of year a true, temporary reflection of the source, not a
    scraper defect. Re-checked the sibling `greenwood_delinquent_tax`'s own
    Treasurer tax-SALE page the same day for an alternative live source: it
    is STILL office-info-only (re-confirmed 2026-10-04), so there is
    currently no public substitute either. The sweep/parse/filter logic
    itself is unchanged and will correctly pick up real Unpaid rows the
    moment the portal carries any again (confirmed by construction: the
    Unpaid-detection test fixtures are untouched and still pass).

    No listing_type on this portal distinguishes real estate from business
    personal property the way Dorchester's BillNumber R-/M- prefix or
    Catalis's RealPropertyType field do — itemid=1 is simply Greenwood's own
    "Property Tax Payments" category (vehicle and watercraft are separate
    itemid pages, 3 and 2, never queried here). Business-named accounts seen
    in this category (e.g. "SMART TRAX AUTOMOTIVE LLC", service address "445
    BYPASS 72 NW, GREENWOOD, SC") read as a business's real property (a shop,
    a lot), not a misrouted personal-property bill, so they are kept — a
    company owning taxable real estate is a legitimate lead, the same way
    this repo already keeps commercial owners on every other county tax
    roll.

Free, public, no login, no CAPTCHA.
Slug: counties_sc.greenwood_corebtpay_delinquent_tax
Category: county_tax
ListingType: TAX_LIEN (standing roll — no scheduled sale/redemption date on
this source; same convention as dorchester_billtrax_delinquent_tax.py).
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper, OUTCOME_OK, OUTCOME_BLOCKED, OUTCOME_PARTIAL, OUTCOME_ZERO
from ...http_client import client as throttled_client
from ...models import Listing, ListingType, PropertyKind
from ...tax_calendar import completed_delinquent_years

log = structlog.get_logger()

SLUG = "counties_sc.greenwood_corebtpay_delinquent_tax"

SITE_URL = "https://greenwoodco.corebtpay.com/egov/apps/bill/pay.egov"
SEARCH_URL = SITE_URL + "?view=search;itemid=1"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: 2-letter last-name prefixes only — see module docstring, "SINGLE-LETTER
#: PREFIXES ARE TOO BROAD". Exposed via env override so a targeted/small run
#: (tests, a manual probe) doesn't have to pay for the full 676-prefix sweep.
_PREFIX_OVERRIDE = os.getenv("GREENWOOD_COREBTPAY_PREFIXES", "").strip()
if _PREFIX_OVERRIDE:
    PREFIXES: list[str] = [p.strip().upper() for p in _PREFIX_OVERRIDE.split(",") if p.strip()]
else:
    PREFIXES = [a + b for a in _ALPHABET for b in _ALPHABET]

#: Hard ceiling on prefixes swept in one run — a safety valve independent of
#: PREFIXES's own length, and the practical way to bound a run's wall time
#: (the full 676-prefix sweep at ~10-15s/request plus pacing is measured in
#: hours, not minutes; this lets a partial run still ship real rows rather
#: than needing to complete the whole alphabet to produce anything).
MAX_PREFIXES = int(os.getenv("GREENWOOD_COREBTPAY_MAX_PREFIXES", str(len(PREFIXES))))

#: Observed server-side result-set size where a query reads as truncated —
#: see module docstring's "REAL 5,000-ROW CAP" note. A prefix returning this
#: many rows (or more) is deepened into its 3-letter children instead of
#: trusted as complete.
PAGE_CAP = int(os.getenv("GREENWOOD_COREBTPAY_PAGE_CAP", "5000"))

#: How many characters deep a capped prefix may be walked (2 -> 3 -> 4...).
#: Kept small: this portal's cap is only hit by a handful of very common
#: 2-letter starts, and a 3rd letter has always been enough in spot checks
#: (see docstring: "JOH" alone, one of 26 children of capped "JO", returned
#: well under the cap at 2,817).
MAX_PREFIX_DEPTH = int(os.getenv("GREENWOOD_COREBTPAY_MAX_DEPTH", "3"))

#: Absolute ceiling on search requests for one run, independent of how many
#: base prefixes there are — covers the full 676-prefix base sweep plus room
#: for a generous number of capped prefixes each deepening into 26 children
#: (measured: only a handful of 2-letter prefixes hit PAGE_CAP at all).
MAX_REQUESTS = int(os.getenv("GREENWOOD_COREBTPAY_MAX_REQUESTS", str(len(PREFIXES) + 26 * 60)))

#: Gentle pace between search requests, ON TOP OF the server's own ~10s
#: response time (see module docstring re: Crawl-delay: 300). Not a promise
#: to literally honor a 5-minute crawl-delay — that would make a useful sweep
#: impossible — but an explicit, deliberate gap rather than firing the next
#: request the instant a slow response returns.
_PACE_S = float(os.getenv("GREENWOOD_COREBTPAY_PACE_S", "3.0"))
_DETAIL_PACE_S = float(os.getenv("GREENWOOD_COREBTPAY_DETAIL_PACE_S", "1.5"))

_REQUEST_TIMEOUT = float(os.getenv("GREENWOOD_COREBTPAY_TIMEOUT_S", "60.0"))

#: Off-season stop (2026-10-09 source audit). From about October to the next January the
#: portal lists only PAID bills (module docstring, "A SEASONAL OBSERVATION"): the 10/8 VM
#: run read 69 prefixes, about 110,000 rows, every one Paid, and then hit the 1,800 s
#: timeout with 0 rows; a live check of two more prefixes the same day was all Paid too.
#: Delinquency is not ordered by name, so when the first SEASON_PROBE_PREFIXES prefixes
#: hold at least SEASON_PROBE_MIN_ROWS bills and none is unpaid, the portal carries no
#: unpaid bills and the sweep stops (about 12 requests instead of 30 minutes).
SEASON_PROBE_PREFIXES = int(os.getenv("GREENWOOD_COREBTPAY_SEASON_PROBE", "12"))
SEASON_PROBE_MIN_ROWS = int(os.getenv("GREENWOOD_COREBTPAY_SEASON_MIN_ROWS", "10000"))
_BACKOFF_S = 5.0

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")

# --- the per-account "View This Bill" page (pay.egov?view=bill;...) ---------
# See module docstring's "THE BILL PAGE CARRIES THE REAL SITUS" note: this is
# a distinct, richer page from `view=detail` (never fetched before this
# audit) that carries the property's actual LOCATION (situs), legal
# description, building/lot/acreage counts and a full valuation breakdown —
# none of which `_parse_detail` below can see. `id=1` in the URL is a fixed
# literal (verified live across many different accounts), not a per-account
# lookup value, so the URL is built directly from the account number alone.
_BILL_TAXMAP_RE = re.compile(r'id="taxMapNumberContainer">\s*<div>TAX MAP NUMBER\s*([0-9]+)\s*</div>', re.I)
_BILL_LOCATION_RE = re.compile(r"<div>LOCATION:\s*([^<]*)</div>", re.I)
_BILL_CUSTADDR_RE = re.compile(r'class="custAddrStyle">(.*?)</div>', re.I | re.S)


def _bill_field_re(label: str) -> re.Pattern:
    """A `taxTableLabelIndent`/`taxTableValueIndent` label/value pair. The
    label match is anchored right after the opening '>' so e.g. 'ASSESSED
    VALUE' can never accidentally match inside the DIFFERENT '4% ASSESSED
    VALUE' / '6% ASSESSED VALUE' rows (those render as one text node each,
    so '>ASSESSED VALUE<' is not a substring of '>4% ASSESSED VALUE<')."""
    return re.compile(
        rf'class="taxTableLabelIndent">{re.escape(label)}</div>\s*'
        rf'<div class="taxTableValueIndent">([^<]*)</div>', re.I)


_BILL_DISTRICT_RE = _bill_field_re("DISTRICT")
_BILL_PROPDESC_RE = _bill_field_re("PROPERTY DESCRIPTION")
_BILL_BLDGS_RE = _bill_field_re("BLDGS")
_BILL_LOTS_RE = _bill_field_re("LOTS")
_BILL_ACRES_RE = _bill_field_re("ACRES")
_BILL_ASSESSED_RE = _bill_field_re("ASSESSED VALUE")
_BILL_TAXVALUE_RE = _bill_field_re("TAX VALUE")
_BILL_PCT4_RE = _bill_field_re("4% ASSESSED VALUE")
_BILL_PCT6_RE = _bill_field_re("6% ASSESSED VALUE")
_BILL_HOMESTEAD_RE = re.compile(
    r'LESS HOMESTEAD EXEMPTION</td>\s*<td class="textRight">([^<]*)</td>', re.I)


class GreenwoodCorebtpayBlocked(RuntimeError):
    """The host answered 403/429 or otherwise refused the request — a wall,
    not a rate limit to route around. Same posture as
    dorchester_billtrax_delinquent_tax.BillTraxBlocked and the CLAUDE.md
    compliance line."""


def _clean(cell_html: str) -> str:
    return _TAG_RE.sub(" ", cell_html).strip()


def _parse_amount(text: str) -> float | None:
    if not text:
        return None
    s = text.replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _is_unpaid(status_text: str) -> bool:
    """Matches on the TEXT ('Unpaid'/'Paid'), not the Font-Awesome icon
    class — see module docstring's "label vs value" note. Case-insensitive,
    substring match (the cell also carries the icon's own alt-less markup,
    already stripped by the time this is called)."""
    return "unpaid" in (status_text or "").lower()


def _parse_search_table(html: str) -> list[dict]:
    """Parse the `<table class="eGov_listContent">` search-results grid into
    row dicts. Returns [] (not an error) if the table is absent — a genuinely
    empty result for a prefix with no matches renders the page without that
    table at all (verified live: an intentionally nonsense prefix search)."""
    m = re.search(r'<table class="eGov_listContent".*?</table>', html, re.I | re.S)
    if not m:
        return []
    rows = _ROW_RE.findall(m.group(0))
    out: list[dict] = []
    for r in rows:
        cells = _CELL_RE.findall(r)
        if len(cells) < 7:
            continue
        clean = [_clean(c) for c in cells]
        account, tax_year, name, status, date_paid, amount = (
            clean[1], clean[2], clean[3], clean[4], clean[5], clean[6])
        if not re.match(r"^\d+$", account) or not re.match(r"^\d{4}$", tax_year):
            continue  # header row or a shape this parser doesn't recognize
        out.append({
            "account": account,
            "tax_year": int(tax_year),
            "name": name,
            "unpaid": _is_unpaid(status),
            "status_text": status,
            "date_paid": date_paid or None,
            "amount": _parse_amount(amount),
        })
    return out


def _parse_detail(html: str) -> dict:
    """Parse the `view=detail` account page's label/value table. Returns
    {} if the expected structure isn't found (host changed shape, or the
    account id was rejected) rather than raising — a missing address should
    not lose an otherwise-real delinquent-tax lead."""
    out: dict = {}
    for label, value in re.findall(
        r"<td>([^<]+):</td>\s*<td>(.*?)</td>", html, re.I | re.S,
    ):
        key = label.strip().lower()
        val = _clean(value)
        if key == "service address":
            out["service_address"] = val or None
        elif key == "account name":
            out["account_name"] = val or None
        elif key == "account number":
            out["account_number"] = val or None
    return out


def _parse_bill(html: str) -> dict:
    """Parse the `view=bill` per-account tax-notice page.

    Returns {} if the page doesn't look like a real bill (host changed shape,
    or the account id was rejected) — same "don't lose an otherwise-real lead
    over a missing enrichment field" posture as `_parse_detail`.
    """
    if not html or "taxMapNumberContainer" not in html:
        return {}
    out: dict = {}

    m = _BILL_TAXMAP_RE.search(html)
    if m:
        out["tax_map_number"] = m.group(1).strip() or None

    m = _BILL_LOCATION_RE.search(html)
    if m:
        out["situs_address"] = _clean(m.group(1)) or None  # genuinely blank on many commercial/pipeline parcels

    m = _BILL_CUSTADDR_RE.search(html)
    if m:
        # 3 <br>-joined lines: owner name, mailing street, mailing city/state/zip.
        lines = [ln.strip() for ln in re.split(r"<br\s*/?>", m.group(1), flags=re.I)]
        lines = [re.sub(r"\s+", " ", _clean(ln)) for ln in lines if _clean(ln)]
        if len(lines) >= 2:
            out["mailing_address"] = ", ".join(lines[1:])  # drop the name line

    m = _BILL_PROPDESC_RE.search(html)
    if m:
        out["legal_description"] = _clean(m.group(1)) or None

    m = _BILL_DISTRICT_RE.search(html)
    if m:
        out["district"] = _clean(m.group(1)) or None

    for key, rx in (("bldgs", _BILL_BLDGS_RE), ("lots", _BILL_LOTS_RE)):
        m = rx.search(html)
        if m:
            val = _clean(m.group(1))
            try:
                out[key] = int(val)
            except ValueError:
                pass

    m = _BILL_ACRES_RE.search(html)
    if m:
        try:
            out["acres"] = float(_clean(m.group(1)))
        except ValueError:
            pass

    for key, rx in (("assessed_value", _BILL_ASSESSED_RE), ("tax_value", _BILL_TAXVALUE_RE),
                    ("pct4_assessed_value", _BILL_PCT4_RE), ("pct6_assessed_value", _BILL_PCT6_RE),
                    ("homestead_exemption", _BILL_HOMESTEAD_RE)):
        m = rx.search(html)
        if m:
            out[key] = _parse_amount(_clean(m.group(1)))

    return out


def _parcel_prefix(account: str, tax_year: int) -> tuple[str, bool]:
    """Strip the trailing 2-digit tax-year suffix (`tax_year % 100`) off an
    Account Number to recover the STABLE per-parcel id — see the module
    docstring's "YEAR-SUFFIX DISCOVERY". Returns (parcel_id, stripped) so a
    non-matching shape can be kept un-aggregated (own lead) instead of
    silently grouped wrong. Requires at least 3 digits left after stripping
    (a 1-2 digit "prefix" would collide constantly across unrelated parcels)."""
    suffix = f"{tax_year % 100:02d}"
    if len(account) > 4 and account.endswith(suffix):
        return account[:-2], True
    return account, False


def _aggregate(rows: Iterable[dict], detail_by_account: dict[str, dict]) -> list[Listing]:
    """One Listing per parcel (grouped by `_parcel_prefix`), balances summed
    across bill-years still unpaid — same shape as
    dorchester_billtrax_delinquent_tax._aggregate /
    sc_catalis_delinquent_roll.aggregate_bills.

    `detail_by_account` is keyed by the LATEST bill-year's account number and
    holds whatever `_parse_bill` recovered from that account's "View This
    Bill" page (situs, mailing, legal description, property characteristics,
    valuation) — see module docstring's "THE BILL PAGE CARRIES THE REAL
    SITUS" note. `street_address` is the real property LOCATION, never the
    owner's mailing address (a correctness bug fixed 2026-10-04: the old code
    published the detail page's "Service Address" — which is actually the
    owner's MAILING address — as street_address, so every absentee/commercial
    owner's lead carried a wrong, often out-of-state, "property" address).
    """
    by_parcel: dict[str, list[dict]] = {}
    for r in rows:
        if not r["unpaid"] or not r["amount"] or r["amount"] <= 0:
            continue
        parcel_id, stripped = _parcel_prefix(r["account"], r["tax_year"])
        r = dict(r, parcel_id=parcel_id, year_suffix_stripped=stripped)
        by_parcel.setdefault(parcel_id, []).append(r)

    now = datetime.utcnow()
    out: list[Listing] = []
    for parcel_id, group in by_parcel.items():
        group = sorted(group, key=lambda g: g["tax_year"], reverse=True)
        latest = group[0]
        owner = latest["name"] or None
        bill = detail_by_account.get(latest["account"], {})
        situs = bill.get("situs_address")
        mailing = bill.get("mailing_address")

        years = sorted({g["tax_year"] for g in group})
        total_due = round(sum(g["amount"] for g in group), 2) or None
        bills = [{"account": g["account"], "year": g["tax_year"], "amount": g["amount"],
                  "status": g["status_text"]} for g in group]

        # BLDGS==0 on the latest bill is a real "no structure" signal (same
        # sparse-omission convention batch 9's dillon_delinquent_tax fix
        # established) — anything else stays UNKNOWN, since nothing on this
        # page distinguishes single-family from commercial/mobile.
        kind = PropertyKind.UNKNOWN
        if bill.get("bldgs") == 0:
            kind = PropertyKind.LAND

        raw_block = {
            "parcel_id": parcel_id,
            "latest_account": latest["account"],
            "owner": owner,
            "service_address": situs,  # back-compat alias; see 'situs_address' for the honest name
            "situs_address": situs,
            "bills": bills,
            "years": years,
            # LATE unpaid levy years (tax_calendar, 2026-10-07); the raw count apart
            "years_delinquent": len(completed_delinquent_years(years, "SC", "Greenwood")),
            "unpaid_bill_years": len(years),
            "is_two_year_plus": len(completed_delinquent_years(years, "SC", "Greenwood")) >= 2,
            "total_due": total_due,
            "year_suffix_stripped": latest["year_suffix_stripped"],
        }
        if bill:
            raw_block["bill"] = {k: v for k, v in bill.items() if k not in ("situs_address", "mailing_address")}
        raw: dict = {"greenwood_corebtpay_delinquent_tax": raw_block}
        if total_due:
            raw["tax_owed"] = {"balance": total_due, "kind": "delinquent_tax", "source": SLUG,
                               "year": years[-1] if years else None, "basis": "own_record"}
        if mailing:
            # Bare-string convention (mailing_shape.mailing_dict) — same shape
            # spartanburg_vacant/spartanburg_delinquent_tax already use.
            raw["owner_mailing"] = mailing

        span = f"{years[0]}-{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "")
        out.append(Listing(
            source=SLUG,
            source_url=SITE_URL + f"?view=bill;account={latest['account']};id=1;itemid=1",
            listing_type=ListingType.TAX_LIEN,
            property_kind=kind,
            state="SC",
            county="Greenwood",
            parcel_id=parcel_id,
            defendant=owner,
            owner_name=owner,
            street_address=situs,
            legal_description=bill.get("legal_description"),
            acreage=bill.get("acres"),
            assessed_value=bill.get("assessed_value"),
            market_value=bill.get("tax_value"),
            description=(f"Delinquent property tax {span}"
                         f" ({len(years)} bill{'s' if len(years) != 1 else ''})"
                         + (f": ${total_due:,.2f} due" if total_due else "")),
            first_seen=now, last_seen=now,
            raw=raw,
        ))
    return out


async def _post_search(cli: httpx.AsyncClient, prefix: str) -> str:
    body = {
        "itemid": "1",
        "view": "search",
        "eGov_functionJS": "Find Account",
        "from": "",
        "ebillSearch_fullNameFld": f"{prefix}|",
        "eGov_function": "Find Account",
    }
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            r = await cli.post(SEARCH_URL, data=body)
        except httpx.HTTPError as exc:
            last_exc = exc
            await asyncio.sleep(_BACKOFF_S * (attempt + 1))
            continue
        if r.status_code in (403, 429):
            raise GreenwoodCorebtpayBlocked(f"HTTP {r.status_code} for prefix {prefix}")
        if r.status_code >= 500:
            log.info("greenwood_corebtpay.retry", prefix=prefix, status=r.status_code,
                     attempt=attempt + 1)
            await asyncio.sleep(_BACKOFF_S * (attempt + 1))
            continue
        r.raise_for_status()
        return r.text
    raise last_exc or RuntimeError(f"gave up on prefix {prefix} after retries")


async def _get_detail(cli: httpx.AsyncClient, account: str) -> str:
    url = SITE_URL + f"?view=detail;account={account};itemid=1"
    for attempt in range(3):
        try:
            r = await cli.get(url)
        except httpx.HTTPError:
            await asyncio.sleep(_BACKOFF_S)
            continue
        if r.status_code in (403, 429):
            raise GreenwoodCorebtpayBlocked(f"HTTP {r.status_code} for detail {account}")
        if r.status_code >= 500:
            await asyncio.sleep(_BACKOFF_S)
            continue
        r.raise_for_status()
        return r.text
    return ""


async def _get_bill(cli: httpx.AsyncClient, account: str) -> str:
    """Fetch the `view=bill` page directly from the account number — no
    `view=detail` fetch needed first (see module docstring; `id=1` is a
    fixed literal, verified live across many accounts, not a lookup key)."""
    url = SITE_URL + f"?view=bill;account={account};id=1;itemid=1"
    for attempt in range(3):
        try:
            r = await cli.get(url)
        except httpx.HTTPError:
            await asyncio.sleep(_BACKOFF_S)
            continue
        if r.status_code in (403, 429):
            raise GreenwoodCorebtpayBlocked(f"HTTP {r.status_code} for bill {account}")
        if r.status_code >= 500:
            await asyncio.sleep(_BACKOFF_S)
            continue
        r.raise_for_status()
        return r.text
    return ""


async def _sweep(cli: httpx.AsyncClient, prefixes: list[str], max_requests: int,
                  on_progress=None) -> tuple[list[dict], dict]:
    """Frontier BFS over `prefixes`, deepening any prefix whose result hits
    PAGE_CAP into its 26 three-letter children instead of trusting a
    possibly-truncated read — see module docstring's "REAL 5,000-ROW CAP".
    Returns (rows, stats). `on_progress(prefix, rows, stats)` is called after
    every successful prefix fetch, so the caller can ship `self.partial`
    incrementally (mirrors dorchester_billtrax_delinquent_tax's per-page
    `self.partial` updates)."""
    stats = {"requests": 0, "capped": 0, "depth_truncated": 0, "errors": 0,
             "lost_prefixes": [], "rows_seen": 0, "unpaid_seen": 0, "season_empty": False}
    all_rows: list[dict] = []
    frontier = list(prefixes)
    depth = 2
    first = True
    while frontier:
        nxt: list[str] = []
        for prefix in frontier:
            if stats["requests"] >= max_requests:
                stats["depth_truncated"] += len(frontier) - frontier.index(prefix)
                log.warning("greenwood_corebtpay.budget_exhausted",
                           remaining=len(frontier) - frontier.index(prefix))
                return all_rows, stats
            if not first:
                await asyncio.sleep(_PACE_S)
            first = False
            try:
                html = await _post_search(cli, prefix)
            except GreenwoodCorebtpayBlocked:
                raise
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                stats["lost_prefixes"].append(prefix)
                log.warning("greenwood_corebtpay.prefix_error", prefix=prefix,
                           error=str(exc)[:160])
                continue
            stats["requests"] += 1
            rows = _parse_search_table(html)
            stats["rows_seen"] += len(rows)
            stats["unpaid_seen"] += sum(1 for r in rows if r["unpaid"])
            if (stats["requests"] >= SEASON_PROBE_PREFIXES
                    and stats["rows_seen"] >= SEASON_PROBE_MIN_ROWS
                    and stats["unpaid_seen"] == 0):
                stats["season_empty"] = True
                log.info("greenwood_corebtpay.season_empty", requests=stats["requests"],
                         rows_seen=stats["rows_seen"],
                         note="every bill on the portal is Paid; stopping the sweep")
                return all_rows, stats
            if len(rows) >= PAGE_CAP and depth < MAX_PREFIX_DEPTH:
                # Truncated read: do NOT absorb it (coverage past the cut is
                # unknown), deepen instead.
                stats["capped"] += 1
                log.info("greenwood_corebtpay.prefix_capped_deepening", prefix=prefix,
                         rows=len(rows), depth=depth)
                nxt.extend(prefix + ch for ch in _ALPHABET)
                continue
            if len(rows) >= PAGE_CAP:
                # Hit MAX_PREFIX_DEPTH still capped: ship it anyway (better than
                # losing it outright) but say so loudly, same posture as
                # qpaybill_delinquent_roll's depth_truncated warning — this is row
                # LOSS for names past whatever this portal's own internal order
                # cuts off, not a cosmetic cap.
                log.warning("greenwood_corebtpay.still_capped_at_max_depth",
                           prefix=prefix, rows=len(rows),
                           note="kept anyway; rows past this portal's own cutoff "
                                "for this prefix are missing")
            all_rows.extend(rows)
            if on_progress:
                on_progress(prefix, rows, stats)
        frontier = nxt
        depth += 1
    return all_rows, stats


class GreenwoodCorebtpayDelinquentTax(BaseScraper):
    slug = SLUG
    name = "Greenwood County SC Delinquent Tax (CORE/eGov)"
    category = "county_tax"
    timeout_s = 1800.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        t0 = time.monotonic()
        prefixes = PREFIXES[:MAX_PREFIXES]
        all_rows_so_far: list[dict] = []

        def _tracking_progress(prefix: str, rows: list[dict], stats: dict) -> None:
            all_rows_so_far.extend(rows)
            unpaid_so_far = sum(1 for r in all_rows_so_far if r["unpaid"] and r["amount"])
            log.info("greenwood_corebtpay.prefix_done", prefix=prefix, rows=len(rows),
                     unpaid_running_total=unpaid_so_far, requests=stats["requests"])
            # Ship partial aggregation (without address lookups yet) as we go, so a
            # soft-timeout mid-sweep still lands real, if address-thin, rows.
            self.partial = _aggregate(all_rows_so_far, {})

        async with throttled_client(
            timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _UA, "Referer": SEARCH_URL},
            impersonate_browser=False, http2=False,
        ) as cli:
            try:
                all_rows, stats = await _sweep(cli, prefixes, MAX_REQUESTS,
                                               on_progress=_tracking_progress)
            except GreenwoodCorebtpayBlocked as exc:
                log.warning("greenwood_corebtpay.blocked", error=str(exc))
                if all_rows_so_far:
                    self.partial = _aggregate(all_rows_so_far, {})
                    self.last_outcome = OUTCOME_PARTIAL
                    self.last_reason = str(exc)[:200]
                    return self.partial
                self.last_outcome = OUTCOME_BLOCKED
                self.last_reason = str(exc)[:200]
                return []

            # Bill-page pass: one GET per unique aggregated parcel (not per
            # bill-year), fetching `view=bill` DIRECTLY off the account number
            # — see module docstring's "THE BILL PAGE CARRIES THE REAL SITUS"
            # note. This replaces the old `view=detail` fetch outright: the
            # bill page is a strict superset (same owner/mailing info, PLUS
            # the real situs, legal description, property characteristics and
            # valuation `view=detail` never had), so there is no longer any
            # reason to fetch `view=detail` at all.
            listings_no_addr = _aggregate(all_rows, {})
            bill_by_account: dict[str, dict] = {}
            accounts_needed = [
                li.raw["greenwood_corebtpay_delinquent_tax"]["latest_account"]
                for li in listings_no_addr
            ]
            detail_blocked = False
            for j, acct in enumerate(accounts_needed):
                if j:
                    await asyncio.sleep(_DETAIL_PACE_S)
                try:
                    bhtml = await _get_bill(cli, acct)
                    bill_by_account[acct] = _parse_bill(bhtml)
                except GreenwoodCorebtpayBlocked as exc:
                    log.warning("greenwood_corebtpay.detail_blocked", account=acct,
                               error=str(exc))
                    detail_blocked = True
                    break  # stop detail pass, still ship what address data we have
                except Exception as exc:  # noqa: BLE001
                    log.warning("greenwood_corebtpay.detail_error", account=acct,
                               error=str(exc)[:160])

        listings = _aggregate(all_rows, bill_by_account)
        self.partial = listings
        elapsed = round(time.monotonic() - t0, 1)
        log.info("greenwood_corebtpay.done", requests=stats["requests"],
                 capped_prefixes_deepened=stats["capped"], errors=stats["errors"],
                 lost_prefixes=stats["lost_prefixes"][:10], raw_bills=len(all_rows),
                 parcels=len(listings), elapsed_s=elapsed)
        if stats.get("season_empty") and not listings:
            self.last_outcome = OUTCOME_ZERO
            self.last_reason = (f"portal lists only paid bills ({stats['rows_seen']} read over "
                                f"{stats['requests']} prefixes, 0 unpaid): off-season")
            return listings
        if stats["errors"] or detail_blocked:
            self.last_outcome = OUTCOME_PARTIAL if listings else OUTCOME_ZERO
            self.last_reason = (f"{stats['errors']} prefix error(s)"
                                + (", detail lookups blocked mid-pass" if detail_blocked else ""))
        else:
            self.last_outcome = OUTCOME_OK if listings else OUTCOME_ZERO
        return listings
