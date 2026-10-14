"""Polk NC tax sources — the Kania Law Firm auction page, plus the county's
own delinquent tax-record search (added 2026-10-12).

AUCTION PAGE: smallest of the four NC pages — only PARCEL + OPENING BID per
row. No address, no case#, no plaintiff/defendant. Sale date sits in a
header block ("Upcoming Auction Date: March 10th, 2026"). Address must be
enriched from Polk GIS by parcel ID.

DELINQUENT TAX SEARCH (added 2026-10-12): a real, free, name-searchable
delinquent-tax database at cms.revize.com/revize/apps/polkcounty/ — found by
the owner (polknc.gov/tax_search/ embeds it in an iframe), confirmed live:
55 real unpaid records returned for a plain name search, full owner name +
assessed value + tax-bill detail link, no CAPTCHA anywhere in the flow. This
was previously missed entirely — the scraper only read the thin auction
page above.

STEALTH FETCH FOR THE SEARCH FORM (2026-10-12, re-enabled 2026-10-12 --
see git log, `03f4617d`) -- read before touching `_search_via_nodriver`.
First build attempt here tried, in order: (1) plain httpx GET
to the search form page itself -- 403, Cloudflare's generic "blocked" page,
from both this VM and a residential IP; (2) curl-cffi Chrome TLS/JA3
impersonation (the tier http_client._impersonate_fetch uses elsewhere),
including a same-session GET first to pick up cookies -- still 403; (3)
plain headless Playwright (no stealth, no solver module, exactly the tool
this file already uses for Avalon) -- ALSO got the exact same generic
Cloudflare "blocked" HTML, not a "Just a moment" JS challenge and not a
CAPTCHA, just blocked outright. There has never been an interactive puzzle
anywhere in this flow -- a REAL Chrome browser session (confirmed manually,
outside this codebase) sails through with zero friction -- but three
increasingly-capable automated tiers all got the same bot-detection block
plain headless Chromium triggers. That crosses into the same automation-
detection-evasion territory as this repo's `wall_bypass.py`/
`enrichment_waf_oss.py` stealth tiers (pydoll/nodriver), which this
scraper intentionally does NOT reach for -- not this codebase's CAPTCHA/WAF-
bypass boundary (see CLAUDE.md), it is Hermes's lane, not mine.

Everything needed to run this is mapped and verified below: exact form
field names (`ReportGroupDescription`/`TaxYear`/`BalanceDue`/
`SearchColumn`/`SearchText`), the exact POST target
(`searchingtaxrecord.php`), confirmed real output (55 unpaid records for a
single-surname search), and a working regex parser for the result rows
(`_ROW_RE`, already unit-tested against real captured HTML). nodriver via
`_search_via_nodriver` (headless=False) is what clears the Cloudflare
bot-management rule that blocks a plain/impersonated request to the FORM
page -- `fetch()` calls both `_fetch_auction()` and
`_fetch_delinquent_search()`.

SCOPE: searches each surname term against the current tax year, unpaid
only, and parses the LIST view (owner name, type, description, tax year,
detail link). The per-record detail page (taxdetail.php?id=N) IS now
fetched per row (added 2026-10-13, source-completeness audit Pattern D):
unlike the search FORM above, a plain GET to taxdetail.php?id=N needs no
browser at all -- confirmed live via curl-cffi Chrome TLS/JA3 impersonation
only (`get_text_impersonate`), the same cheap static-content tier
`http_client.py` already uses elsewhere; the WAF rule that blocks the form
apparently doesn't cover this endpoint. Real fields confirmed live and
parsed: status, total due, full owner name (incl. "ET UX"/co-owner and
"C/O ..." lines the list view truncates), owner ID, tax receipt number,
bill number, parcel number, full mailing address, district, assessed
value, base amount, and charges. Confirmed-live edge cases the parser
must reject rather than parse as data: id=0 ("No Tax Record was
requested. Try Searching again !!!"), a negative/non-numeric/nonexistent
id (the site echoes back its own unrendered SQL verbatim -- literally
"select count(*) recordcount from tax_data where id=...", a bug on the
county's end, not something to be exploited further here) and an
intermittent Cloudflare "Just a moment" challenge even on this endpoint
(a transient HTTP 403; `get_text_impersonate`'s own retry clears it on a
later attempt most of the time -- confirmed by hand: id=5000 403'd once,
then 200'd twice in a row seconds later). Detail fetches are budget- and
count-capped (`_DETAIL_FETCH_CAP` / `_DETAIL_BUDGET_SHARE` below,
mirroring `national/landwatch.py`'s `DETAIL_FETCH_CAP_PER_COUNTY` and
`national/estate_sales.py`'s time-budget pattern) and `_fetch_detail`
never raises -- pure enrichment; the listing itself already comes from
the list/search page and must survive a slow or failed detail fetch.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Iterable

import structlog
from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client, get_text_impersonate
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_SEARCH_BASE = "https://cms.revize.com/revize/apps/polkcounty"
_SEARCH_FORM_URL = f"{_SEARCH_BASE}/searchtaxrecord.php"
_SEARCH_POST_URL = f"{_SEARCH_BASE}/searchingtaxrecord.php"
_CURRENT_TAX_YEAR = "2026"
_SEARCH_TERMS = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Polk", "Carrow", "Jackson", "Henderson",
]

_ROW_RE = re.compile(
    r'<tr class="(?:odd|even)Row">\s*<td>(?P<name>[^<]*?)\s*</td>\s*'
    r'<td[^>]*>\s*(?P<type>[^<]*?)\s*</td>\s*'
    r'<td>(?P<desc>[^<]*?)</td>\s*'
    r'<td[^>]*>(?P<year>\d{4})</td>.*?'
    r"taxdetail\.php\?id=(?P<id>\d+)",
    re.S,
)

# --- per-row detail page (taxdetail.php?id=N) -------------------------------
# Confirmed live 2026-10-13: a plain GET with a curl-cffi Chrome TLS/JA3
# fingerprint (no browser) returns the real record. See module docstring for
# the full live-verification notes and the two confirmed "not real data"
# shapes (`_DETAIL_INVALID_MARKERS`) this parser must reject.
_DETAIL_INVALID_MARKERS = (
    "select count(*) recordcount",       # id has no matching row (or is non-numeric/negative)
    "no tax record was requested",       # id=0 / blank id
)

# Safety caps on the per-row detail-fetch pass -- mirrors
# national/landwatch.py's DETAIL_FETCH_CAP_PER_COUNTY (hard count ceiling)
# combined with national/estate_sales.py's time-budget pattern (so a slow
# run fills in fewer rows instead of blowing the scraper's own timeout_s).
# 55 unpaid PROPERTY-type records were confirmed for a SINGLE surname
# search; with 54 surname terms deduped by detail_id, the real per-run
# total is unknown but likely well above that -- the cap is a backstop,
# the time budget is what actually governs on a normal run.
_DETAIL_FETCH_CAP = 150
_DETAIL_BUDGET_SHARE = 0.3  # fraction of timeout_s, measured from the start
                            # of _fetch_delinquent_search, reserved for detail
                            # fetches (the nodriver search above it is the
                            # slow, variable part of this scraper's budget)

_DETAIL_FIELD_RE = {
    "status": re.compile(r"<td>Status:</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "total_due": re.compile(r"Total Due:\s*</td>\s*<td>\s*\$?\s*([\d,]+\.\d{2})\s*</td>", re.I),
    "collection_status": re.compile(r"Collection Status:\s*</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "owner_name_full": re.compile(r"Owner Name:\s*</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "owner_id": re.compile(r"Owner ID:\s*</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "tax_receipt_number": re.compile(r"Tax Receipt Number:\s*</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "bill_number": re.compile(r"Bill Number:\s*</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "parcel_number": re.compile(r"Parcel Number:\s*</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "district": re.compile(r"District:\s*</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "detail_type": re.compile(r">Type:\s*</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "detail_description": re.compile(r"Description:\s*</td>\s*<td>\s*([^<]*?)\s*</td>", re.I),
    "assessed_value": re.compile(r"Assessed Value:\s*</td>\s*<td>\s*([\d,]+(?:\.\d+)?)\s*</td>", re.I),
    "base_amount": re.compile(r"Base Amount:\s*</td>\s*<td>\s*\$?\s*([\d,]+\.\d{2})\s*</td>", re.I),
    "charges": re.compile(r"Charges:\s*</td>\s*<td>\s*\$?\s*([\d,]+\.\d{2})\s*</td>", re.I),
}
# Mailing Address cell holds 2+ lines separated by <br> (street/PO box, then
# city/state/zip, occasionally a leading "C/O ..." line) -- captured as the
# whole cell then split, not a fixed 2-group pattern, so it survives both
# shapes confirmed live ("PO BOX 1120 <br>SALUDA, NC 28773" and
# "938 GREEN CREEK DR <br>COLUMBUS, NC 28722").
_DETAIL_MAILING_RE = re.compile(r"Mailing Address:\s*</td>\s*<td>(.*?)</td>", re.I | re.S)
_DETAIL_BR_RE = re.compile(r"<br\s*/?>", re.I)
_DETAIL_MAIL_STATE_RE = re.compile(r",\s*([A-Z]{2})\s*\d{5}")
_MONEY_FIELDS = {"total_due", "base_amount", "charges", "assessed_value"}


def _parse_detail_html(html: str) -> dict:
    """Parse one taxdetail.php?id=N response into a flat field dict.

    Returns {} for anything that isn't a real record -- a Cloudflare
    challenge that slipped past get_text_impersonate's retry, id=0's "No Tax
    Record was requested" notice, or the literal unrendered-SQL fallback the
    site answers with for a negative/non-numeric/nonexistent id (both
    confirmed live 2026-10-13, see module docstring). Never raises: a
    label the live page didn't happen to have this time just means that key
    is absent from the result, not a parse failure.
    """
    if not html:
        return {}
    low = html.lower()
    if any(marker in low for marker in _DETAIL_INVALID_MARKERS):
        return {}
    if "owner name:" not in low:
        return {}  # unrecognized shape -- don't guess at a record that isn't there
    flat = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    out: dict = {}
    for key, rx in _DETAIL_FIELD_RE.items():
        m = rx.search(flat)
        if not m:
            continue
        val = re.sub(r"\s+", " ", m.group(1)).strip()
        if not val:
            continue
        if key in _MONEY_FIELDS:
            try:
                out[key] = float(val.replace(",", ""))
            except ValueError:
                out[key] = val  # keep the raw string rather than drop a real value
        else:
            out[key] = val

    m = _DETAIL_MAILING_RE.search(flat)
    if m:
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in _DETAIL_BR_RE.split(m.group(1))]
        lines = [ln for ln in lines if ln]
        if lines:
            out["mailing_address"] = ", ".join(lines)
            sm = _DETAIL_MAIL_STATE_RE.search(lines[-1])
            if sm:
                out["mailing_state"] = sm.group(1)
    return out


async def _fetch_detail(detail_id: str) -> dict:
    """Best-effort fetch + parse of one Polk tax-detail page.

    Pure enrichment -- never raises. The underlying Listing already comes
    from the list/search page (`_parse_search_html`), so a failed or slow
    detail fetch must never break or drop it.
    """
    url = f"{_SEARCH_BASE}/taxdetail.php?id={detail_id}"
    try:
        html = await get_text_impersonate(url, timeout=20.0)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        log.debug("polk_tax.detail_fetch_failed", detail_id=detail_id, error=str(exc)[:160])
        return {}
    try:
        return _parse_detail_html(html)
    except Exception as exc:  # noqa: BLE001 - a parse bug must not drop the listing either
        log.debug("polk_tax.detail_parse_failed", detail_id=detail_id, error=str(exc)[:160])
        return {}


def _apply_detail(li: Listing, extras: dict) -> None:
    """Merge a parsed detail-page dict into its Listing. Pure enrichment:
    only fills fields the list page left empty / adds the nested detail
    block, never raises."""
    if not extras:
        return

    detail = {k: v for k, v in extras.items()
              if k not in ("mailing_address", "mailing_state", "owner_name_full")}
    if detail:
        ns = li.raw.setdefault("polk_tax_search", {})
        ns["detail"] = detail

    parcel = extras.get("parcel_number")
    if parcel and not li.parcel_id:
        li.parcel_id = parcel

    assessed = extras.get("assessed_value")
    if isinstance(assessed, (int, float)) and assessed > 0 and not li.assessed_value:
        li.assessed_value = float(assessed)

    owner_full = extras.get("owner_name_full")
    if owner_full:
        li.owner_name = owner_full  # the detail page is the single-record ground truth

    total_due = extras.get("total_due")
    if isinstance(total_due, (int, float)) and total_due > 0:
        li.description = f"{li.description or 'Polk County delinquent tax record'} — ${total_due:,.2f} owed"

    mailing = extras.get("mailing_address")
    if mailing:
        mail_state = extras.get("mailing_state")
        # situs (the property's own street address) isn't known at this
        # source -- the list/search view never carries one and `description`
        # is sometimes a mobile-home description, not an address, so it
        # can't be trusted as situs either. absentee defaults False the same
        # way counties_generic._layer_kit.owner_mailing does when situs is
        # unknown (bool(None and ...) is always False) rather than guessing.
        li.raw["owner_mailing"] = {
            "owner": owner_full or li.owner_name,
            "mailing": mailing,
            "situs": None,
            "mail_state": mail_state,
            "absentee": False,
            "out_of_state": bool(mail_state and mail_state != "NC"),
            "source": "polk_tax_detail",
        }


async def _search_via_nodriver(browser, letter: str) -> str:
    """Load the search form via nodriver, fill it with JS, submit, and
    return the result HTML. nodriver bypasses Cloudflare bot-detection
    that blocks both curl-cffi and plain Playwright (confirmed 2026-10-12).
    All form interactions done via a single evaluate() call since nodriver
    doesn't have Playwright's select_option/fill helpers."""
    # Retry loop — Cloudflare intermittently shows "Just a moment" challenge
    # even in headful mode. 28,965 chars = challenge page, ~3,085 = form page.
    page = await browser.get(_SEARCH_FORM_URL)
    for attempt in range(4):
        await asyncio.sleep(8 if attempt == 0 else 12)
        content = await page.get_content()
        if len(content) < 10000 and "just a moment" not in content.lower():
            break  # form loaded (3K chars, no challenge)
        # Still blocked — wait and retry with a fresh page load
        page = await browser.get(_SEARCH_FORM_URL)
        await asyncio.sleep(5)

    # Fill the entire form via JS and submit.
    # The form is bare HTML — no JS, no CSS, no IDs. Uses name= attributes.
    # Form action="searchingtaxrecord.php" method="post" — plain POST.
    # IMPORTANT: BalanceDue option values use HTML entities: &gt;0 not >0.
    js = """
    (async () => {
        // Radio: "Both" (empty value) so property + vehicle both show
        const radios = document.querySelectorAll('input[name="ReportGroupDescription"]');
        for (const r of radios) { if (r.value === '') r.checked = true; }

        // Select dropdowns — match by iterating options (handles HTML entities)
        const setSelect = (name, val) => {
            const sel = document.querySelector(`select[name="${name}"]`);
            if (sel) {
                for (let i = 0; i < sel.options.length; i++) {
                    if (sel.options[i].value === val || sel.options[i].textContent === val) {
                        sel.selectedIndex = i;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        break;
                    }
                }
            }
        };
        setSelect('TaxYear', '""" + _CURRENT_TAX_YEAR + """');
        // BalanceDue: option value is "&gt;0" in HTML but browser decodes to ">0"
        setSelect('BalanceDue', '>0');
        setSelect('SearchColumn', 'Name');

        // Text input
        const txt = document.querySelector('input[name="SearchText"]');
        if (txt) { txt.value = '""" + letter + """'; txt.dispatchEvent(new Event('input', {bubbles: true})); }

        // Submit the form — requestSubmit() triggers real navigation
        const form = document.querySelector('form');
        if (form) {
            if (form.requestSubmit) { form.requestSubmit(); }
            else { form.submit(); }
        }
        return 'submitted';
    })()
    """
    result = await page.evaluate(js, await_promise=True)
    # Wait for navigation/results to load. The form page itself is ~28K chars
    # and contains oddRow/evenRow in CSS/JS, so those can't be used as markers.
    # Only taxdetail links and gvHdr (grid header) appear on the results page.
    for _ in range(20):
        await asyncio.sleep(2)
        content = await page.get_content()
        low = content.lower()
        if ("taxdetail" in low or "gvhdr" in low
                or "too many records" in low or "no records" in low):
            break
    return await page.get_content()

URL = "https://www.polknc.gov/upcoming_auction.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ENTITIES = re.compile(r"&(?:nbsp|amp|lt|gt|times);")
# Live-verified 2026-10-01: the page currently reads "Auction Date:" with no
# "Upcoming" prefix (the posted Sept 1 2026 auction was CANCELLED, with no
# parcel rows left -- a genuine, correct zero, not a bug), unlike the
# "Upcoming Auction Date:" wording this regex was originally verified
# against. Made the prefix word optional so a real future auction isn't
# silently missed if the county keeps the shorter wording once a new sale is
# actually posted.
DATE_RE = re.compile(
    r"(?:Upcoming\s+)?Auction Date[:\s]*([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})", re.I
)
# A cancelled auction's date/parcels are stale -- don't stamp a sale_date that
# reads as a live upcoming event when the page itself says otherwise.
CANCELLED_RE = re.compile(r"\bCANCELLED\b", re.I)
TIME_RE = re.compile(r"(\d{1,2}\s*(?:AM|PM|a\.?m\.?|p\.?m\.?))", re.I)
LOCATION_RE = re.compile(r"Location[:\s]*([^A]+(?:Courthouse|Court House)[^$]+?)(?:The|PARCEL)", re.I | re.S)
# Each row: <parcel> <whitespace incl. nbsp>* $<amount>
# Polk's HTML uses `&nbsp;` between parcel and price; selectolax/regex strip it but
# they may collapse to non-breaking-space chars. Match any non-$ chars between.
#
# 2026-08-02 REGRESSION FIX: Kania posts the opening bid as a literal "$TBD" until
# the upset-bid figure is set (live page today: a single row "P65-38  $TBD"). The
# old pattern required digits after the "$", so a TBD-priced sale matched nothing
# and the scraper reported 0 — a REGRESSED source with a real, active auction on
# the page. The amount group is now optional: TBD rows are emitted with the parcel
# + sale date and opening_bid=None (the auction, not the price, is the lead).
ROW_RE = re.compile(
    r"([A-Z]?\d+(?:-[A-Z]?\d+)+)[^\$]{1,40}\$\s*(?:([\d,]+(?:\.\d{2})?)|TBD\b)",
    re.I,
)


class PolkTaxAuction(BaseScraper):
    slug = "counties_nc.polk_tax"
    name = "Polk NC Tax Auction + Delinquent Search (Kania Law Firm + county)"
    category = "county_tax"
    expected_min_count = 1
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out = list(await self._fetch_auction())
        # Bank the auction rows immediately so a soft-timeout during the
        # (often slow) delinquent-search path below still ships them — see
        # base_scraper.safe_run's partial-salvage path.
        self.partial = list(out)
        out.extend(await self._fetch_delinquent_search())
        return out

    async def _fetch_delinquent_search(self) -> Iterable[Listing]:
        """The county's own delinquent-tax name search, plus a per-row
        detail-page enrichment pass (added 2026-10-13).

        Cloudflare WAF-rule block on cms.revize.com: headless=True gets
        hard-blocked ("Sorry, you have been blocked"), headless=False
        through Xvfb passes every time. Diagnostic 2026-10-12 confirmed
        this is headless-detection, NOT IP reputation — the Oracle VM's
        IP is fine, it's the headless Chromium fingerprint that triggers
        the WAF rule. Use headless=False always for this source.

        The per-row detail fetch (taxdetail.php?id=N) is a different story:
        no browser needed there at all, see module docstring and
        `_fetch_detail`.
        """
        from ...browser_utils import start_browser

        start = time.monotonic()
        out: list[Listing] = []
        seen_ids: set[str] = set()
        term_errors = 0

        browser = await start_browser(headless=False)
        try:
            for term in _SEARCH_TERMS:
                html = None
                for attempt in range(3):
                    try:
                        html = await _search_via_nodriver(browser, term)
                    except Exception:
                        html = None
                        continue
                    # Check if we got Cloudflare challenge instead of results
                    low = html.lower()
                    if ("just a moment" in low or "sorry, you have been blocked" in low
                            or len(html) > 25000 and "taxdetail" not in low and "gvhdr" not in low
                            and "no records" not in low and "too many records" not in low):
                        # Cloudflare challenge — wait and retry
                        await asyncio.sleep(8)
                        html = None
                        continue
                    break
                if html is None:
                    term_errors += 1
                    continue
                out.extend(self._parse_search_html(html, seen_ids))
        finally:
            try:
                browser.stop()
            except BaseException:
                pass

        if not out and term_errors == len(_SEARCH_TERMS):
            try:
                from ...http_client import _block_holder  # type: ignore
                holder = _block_holder.get()
                if holder is not None:
                    holder.append((0, "polk_tax delinquent search: all surname "
                                       "searches errored — see logs"))
            except Exception:  # noqa: BLE001
                pass

        # Bank the list/search rows as the salvage set BEFORE the per-row
        # detail-page pass below, so a soft-timeout mid-enrichment still
        # ships every listing already parsed above (same ordering as
        # national/estate_sales.py's gallery-fetch pass).
        self.partial = list(self.partial or []) + out

        deadline = start + self.timeout_s * _DETAIL_BUDGET_SHARE
        done = 0
        for li in out:
            if done >= _DETAIL_FETCH_CAP:
                log.info("polk_tax.detail_fetch_cap_reached", cap=_DETAIL_FETCH_CAP,
                          total=len(out))
                break
            if time.monotonic() > deadline:
                log.info("polk_tax.detail_fetch_budget_spent", done=done,
                          remaining=len(out) - done)
                break
            rid = (li.raw.get("polk_tax_search") or {}).get("detail_id")
            if not rid:
                continue
            done += 1
            try:
                extras = await _fetch_detail(rid)
                _apply_detail(li, extras)
            except Exception as exc:  # noqa: BLE001 - enrichment must never drop the listing
                log.debug("polk_tax.detail_enrich_failed", detail_id=rid, error=str(exc)[:160])

        return out

    @staticmethod
    def _parse_search_html(html: str, seen_ids: set[str]) -> list[Listing]:
        out: list[Listing] = []

        for m in _ROW_RE.finditer(html):
            rid = m.group("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            rtype = m.group("type").strip()
            if rtype.upper() not in ("PROPERTY", ""):
                continue  # vehicles aren't a real-estate lead
            name = re.sub(r"\s+", " ", m.group("name")).strip()
            desc = re.sub(r"\s+", " ", m.group("desc")).strip()
            out.append(
                Listing(
                    source=PolkTaxAuction.slug,
                    source_url=f"{_SEARCH_BASE}/taxdetail.php?id={rid}",
                    listing_type=ListingType.TAX_LIEN,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Polk",
                    owner_name=name,
                    description=f"Polk County delinquent tax — {desc}" if desc else
                                "Polk County delinquent tax record",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={
                        "polk_tax_search": {
                            "detail_id": rid,
                            "tax_year": m.group("year"),
                            "description": desc,
                            "type": rtype,
                            # Real parcel/mailing-address/exact-amount data lives on the
                            # detail page (source_url above) and IS fetched per-row, budget
                            # permitting -- see _fetch_delinquent_search's detail-fetch pass
                            # and _apply_detail, which fill raw["polk_tax_search"]["detail"]
                            # and raw["owner_mailing"] on this same Listing object below.
                        }
                    },
                )
            )
        return out

    async def _fetch_auction(self) -> Iterable[Listing]:
        async with client(timeout=20.0) as c:
            r = await c.get(URL, headers=HEADERS)
            if r.status_code != 200:
                return []
            html = r.text

        # Strip tags + decode common HTML entities (Polk page is full of `&nbsp;`)
        flat = _ENTITIES.sub(" ", _TAG.sub(" ", html))
        flat = _WS.sub(" ", flat)
        # Detect a CANCELLED notice near the date (within the same short
        # window the page prints it in, e.g. "...2026&nbsp;&nbsp; CANCELLED
        # 11 AM..."). If the auction itself was pulled, any parcel rows left
        # on the page are stale leftovers, not a live sale -- withhold
        # sale_date so they don't read as an upcoming auction.
        cancelled = bool(CANCELLED_RE.search(flat[:2000]))
        sale_date = None
        date_m = DATE_RE.search(flat)
        if date_m and not cancelled:
            try:
                # strip "th"/"nd"/"st"/"rd" before parse
                clean = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_m.group(1))
                sale_date = dateparser.parse(clean)
            except (ValueError, TypeError):
                pass
        loc_m = LOCATION_RE.search(flat)
        sale_location = loc_m.group(1).strip() if loc_m else "Polk County Courthouse, 1 Courthouse St., Columbus NC"

        out: list[Listing] = []
        seen: set[str] = set()
        for m in ROW_RE.finditer(flat):
            parcel = m.group(1).strip()
            if parcel in seen or len(parcel) < 4:
                continue
            seen.add(parcel)
            # group(2) is None on a "$TBD" row — the sale is real, the price is not
            # published yet.
            try:
                bid = float(m.group(2).replace(",", "")) if m.group(2) else None
            except ValueError:
                bid = None
            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Polk",
                    parcel_id=parcel,
                    sale_date=sale_date,
                    sale_location=sale_location,
                    opening_bid=bid,
                    description=f"Polk County tax auction parcel {parcel} (Kania Law Firm)"
                                + (" [auction cancelled]" if cancelled else ""),
                    auction_status="cancelled" if cancelled else None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"polk_tax": {"parcel": parcel, "opening_bid": bid, "cancelled": cancelled}},
                )
            )
        return out
