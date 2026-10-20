"""tax_lien, Johnston County NC: is there a real delinquent property-tax balance on this parcel,
read live from the county's myJohnstonCountyNC guest portal (PayIt Gov)?

WHY (2026-10-19 live investigation, orchestrating session). Johnston NC had NO tax scraper or
verifier of any kind -- its old portal (bttaxpayerportal.com/ITSPublicJO) is dead; the county has
since migrated to a PayIt Gov consumer app at https://my.johnstonnc.gov. This file was built from
a live, read-only, no-payment browser walkthrough of that app (no account created beyond the free
"guest connect" step PayIt itself offers with no login).

THE REAL CAPABILITY: VERIFY-ONLY, NOT DISCOVER-CAPABLE. The Connect Property form
(https://my.johnstonnc.gov/form/4e007c95-491d-4dc1-8bb1-8c3e107c3de0) offers exactly five search
methods -- Bill Number, Parcel Number, Account Number, Owner Name, Business Name -- and nothing
else: no "browse all delinquent parcels", no balance-due filter, no sort-by-amount-owed, no way to
list the county's delinquent roll. Every path requires an identifier the caller already has. This
means this source can CONFIRM a parcel already suspected (searched by its own board parcel_id) but
cannot DISCOVER a new delinquent parcel on its own -- a materially narrower role than this
project's bulk scrapers (scrapers/counties_nc/*.py), which is why this ships as a verifier
(verification/verifiers/) in the shape of tax_lien_wake / tax_lien_billtrax, not a scraper.
Parcel Number search is an exact match (confirmed live: searching "01E08015R" returned exactly
the one account for that parcel) -- the fastest, most precise of the five for this use case, and
the one this verifier uses.

WHY BROWSER AUTOMATION, NOT A PLAIN HTTP CALL. The app's data calls all go through
service-api.payitgov.com's persisted-query GraphQL gateway
(.../v1/api/graphql-gateway-proxy/query/<hash>) behind an ephemeral guest customer created by
POST https://8443-app.mobilgov.com/accounts/guest -- an opaque, session-scoped, multi-service
backend (mobilgov.com cart/payment-account/log hosts besides the gateway) that is not a stable,
replayable REST shape the way most of this project's sources are. The UI flow itself is simple
and stable (plain labelled form fields, a real DOM, no CAPTCHA, no WAF challenge: confirmed
headless-safe). This verifier drives that UI directly with this project's existing stealth-browser
tooling (browser_utils.start_browser, nodriver/undetected Chrome -- the same tool
scrapers/counties_nc/nc_avalon_tax.py and scrapers/counties_nc/polk_tax.py already use for a
JS-rendered SPA), the same pattern those two files use: one browser, page.evaluate() JS to fill
and submit forms and click through screens, poll page content for the next screen's markers.

THE FLOW (every step live-verified 2026-10-19; a plain https://... GET to any of these pages
resets the guest session, so every step after step 1 is driven by a real <a>/button .click()
the app's own router intercepts (in-SPA navigation), never a fresh page load. Also live-confirmed
the SAME day: an EARLIER version of this verifier tried to also reuse one already-logged-in
session's PAGE across several different board rows in one sweep run (to save the ~10s a full
"Pay as Guest" login costs) -- live testing caught it leaking one row's account-page content into
the NEXT row's read (a search for an unrelated, clean parcel came back holding the PREVIOUS
parcel's dollar figures once, after an earlier row's flow had broken off mid-way through a step).
That risk was not worth the savings, so this verifier re-logs in as a fresh guest for EVERY
single row (_new_guest_page) -- the only thing reused across a sweep run is the Chrome PROCESS
itself (_ensure_browser), never a session or a page):
  1. GET https://my.johnstonnc.gov/ , click "Pay as Guest" -> lands on
     /service/johnston_county_property_tax (creates the guest customer).
  2. Click the Connect Property link (href starts with "/form/") ->
     /form/4e007c95-491d-4dc1-8bb1-8c3e107c3de0.
  3. Click the "Parcel Number" radio (input[type=radio], stable id "...-opt-1", matched by its
     label text so a form re-order does not silently break this), type the parcel into the
     text input it reveals (React-controlled: set via the native HTMLInputElement value setter +
     an 'input' event, the standard trick for a framework-controlled field -- same technique
     scrapers/counties_nc/polk_tax.py uses), click Search.
  4. Each result is one <fieldset> with one checkbox (id "form-result-<uuid>") and the parcel
     number as plain text inside it: select the checkbox whose fieldset text contains the exact
     parcel string, click "Connect Properties" (a free guest "connect", no login/account creation
     -- the step this task's brief and this project's safety rules call already-proven-safe),
     then click "View Properties" -> /service/johnston_county_property_tax/account/<uuid>.
  5. The account page's <dl> carries Owner Name / Account Number / Account-Parcel Number as plain
     <dt>/<dd> pairs (parse_header below). Its "Available Bills" block shows the top few bills;
     when there are more than fit, a [data-testid="view-all-link"] anchor opens
     /service/johnston_county_property_tax/bills/account/<uuid> -- ONE page carrying BOTH the
     payable bills table AND a second "Ineligible for Online Payment" table (very old bills the
     county has moved to collections / a law firm and no longer accepts online; still a real
     unpaid balance), the second one paginated 10 rows/page. Every bill row carries its due date,
     dollar amount and zero or more status flags ("Overdue", "NOT PAYABLE") in one checkbox
     aria-label ("Select bill due <date> totalling $<amount>.") plus nearby flag spans --
     parse_bill_rows below reads this directly off the real captured markup, not a guess.
     "Billing History" is a SEPARATE section of resolved ($0.00) past bills; it carries no
     payment DATE (same gap tax_lien_wake documents for Wake), so, like every other NC tax_lien
     verifier here, a bill's lateness is decided by tax_calendar (the due date's year minus one is
     the levy year; delinquent once tax_calendar.levy_year_is_delinquent says so) rather than by
     trusting the site's own "Overdue" wording verbatim -- the badge is kept in evidence only.

CONFIRMED LIVE, 2026-10-19 (8 real Johnston parcels sampled; see tests/test_verification_tax_lien_
johnston.py for the exact captured markup these assertions are read from):
  * 01011021A, W BRANCH ST, owner "SMITH, D. CHESTER HEIRS" -- a genuinely, severely chronic
    delinquent parcel: an unbroken OVERDUE bill every year 2013-2026 (14 years), $388.94-$574.43
    each, cumulative unpaid total $7,286.64 shown by the portal itself ("Payment Information:
    Total"). This is the shape confirmed/chronic_claim below is built to recognize.
  * 01E08015R (SMITH, MICHAEL, 42 Copperhead Ln) and 01023008 (CAGLE, NEIL C / "JONES, SHEILA
    CAGLE" in the owner-name index, 504 E Hill St) -- both fully current: a decade of Billing
    History rows all $0.00, only the not-yet-due current levy year owed. A real, honest "not
    delinquent" result, same as this project's other tax verifiers report routinely.
  * 6 more Jones-surname parcels sampled for their current-year bill only (all a future-dated,
    not-yet-late 2026 levy bill $1,370-$3,322 -- ordinary, not delinquent by itself).

VERDICTS (same vocabulary as every other tax_lien verifier here):
  confirmed    at least one bill (payable or "ineligible for online payment", either table) whose
               due-date-derived levy year tax_calendar says is delinquent and whose amount > 0.
  stale        nothing currently owed, and the claimed year's resolved ($0.00) Billing History row
               confirms it was paid (late or not -- no payment date here, so, like tax_lien_wake,
               never refuted on that alone).
  refuted      never. No payment-DATE column exists anywhere on this portal (bill rows show only
               a due date and the current amount due), so there is no way to tell a bill paid
               before its delinquency date from one paid after it -- same gap tax_lien_wake and
               tax_lien_rowan document for their own sources.
  unconfirmed  no parcel on the row, the parcel search found no exact match, the guest-session
               flow could not reach a screen it needed, or the live site failed / was unreachable.

Evidence is a whitelist (public ledger): no owner names, no account numbers, no bill numbers.
"""
from __future__ import annotations

import asyncio
import json
import re
import weakref
from datetime import date
from typing import Any, Optional

from ... import tax_calendar
from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 21
RETRY_DAYS = 7
SOURCE = "my.johnstonnc.gov (Johnston County property tax, PayIt Gov guest portal)"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed", "portal_unhealthy", "session_failed")
TRANSIENT_RETRY_DAYS = 0.25

COUNTY = "johnston"
BASE = "https://my.johnstonnc.gov"
HOME_URL = BASE + "/"
CONNECT_FORM_PATH_PREFIX = "/form/"
SERVICE_PATH = "/service/johnston_county_property_tax"

#: Johnston's own parcel-number shape, as printed throughout the portal: two digits, an optional
#: section letter, more digits, an optional one/two letter suffix ("01011006", "01E08015R",
#: "01011021A"). Used only to sanity-check a row's parcel before spending a browser session on it.
_PARCEL_RE = re.compile(r"^\d{2}[A-Z]?\d{4,7}[A-Z]{0,2}$")

_NAME = __name__.rsplit(".", 1)[-1]


def applies(row: dict) -> bool:
    if str(tc.g(row, "state") or "").strip().upper() != "NC":
        return False
    if str(tc.g(row, "county") or "").strip().replace(" County", "").lower() != COUNTY:
        return False
    return tc.claims_property_tax(row, False)


def claimed_years(row: Any) -> list[int]:
    return sorted(tc.claimed_years_common(row) | tc.source_block_years(row), reverse=True)


def parcel_of(row: Any) -> Optional[str]:
    """The row's parcel_id, normalized (whitespace/case) and shape-checked against Johnston's own
    parcel format; None for anything that does not look like one (this verifier never guesses)."""
    s = re.sub(r"\s+", "", str(tc.g(row, "parcel_id") or "")).upper()
    return s if s and _PARCEL_RE.match(s) else None


# ---------------------------------------------------------------------------
# pure parsing (no I/O) -- read straight off real captured markup, see module docstring
# ---------------------------------------------------------------------------

_HEADER_FIELD_RE = re.compile(
    r"<dt[^>]*><span>([^<]+)</span></dt>\s*<dd[^>]*>([^<]*)</dd>", re.S)


def parse_header(html: str) -> dict[str, str]:
    """{"Account/Parcel Number": ..., "Owner Name": ..., "Account Number": ...} off an account
    page's <dl> (module docstring step 5): a label -> value map, whatever labels are present."""
    out: dict[str, str] = {}
    for label, value in _HEADER_FIELD_RE.findall(html or ""):
        out[label.strip()] = re.sub(r"\s+", " ", value).strip()
    return out


#: one checkbox per bill row, its aria-label carrying the due date and amount together (module
#: docstring step 5) -- the one piece of the row that is never duplicated between the mobile and
#: desktop copies of the same <tr> (every other cell's text is printed twice).
_BILL_ARIA_RE = re.compile(
    r'aria-label="Select bill due ([A-Za-z]{3} \d{1,2}, \d{4}) totalling \$([\d,]+\.\d{2})\.')
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))}
_DATE_RE = re.compile(r"([A-Za-z]{3}) (\d{1,2}), (\d{4})")
#: how far past one bill's aria-label its own status-flag spans can appear, bounded by the next
#: bill's aria-label (or this many chars, whichever comes first) so one row's flags never bleed
#: into the next row's. Generous: a real <tr> duplicates its whole row twice (a CSS-hidden mobile
#: copy and a CSS-hidden desktop copy, both always in the DOM -- module docstring), measured at
#: several thousand characters end to end with heavy inline-SVG icon markup; the real boundary
#: that matters is the next row's own aria-label, not this number.
_FLAG_WINDOW = 6000
_FLAG_RE = re.compile(r">\s*(Overdue|NOT PAYABLE)\s*<", re.I)


def _parse_due_date(text: str) -> Optional[date]:
    m = _DATE_RE.match(text)
    if not m or m.group(1) not in _MONTHS:
        return None
    try:
        return date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
    except ValueError:
        return None


def parse_bill_rows(html: str) -> list[dict]:
    """[{due_date: date, amount: float, flags: [...]}] of every bill row on a page carrying the
    Available Bills / Ineligible-for-Online-Payment tables (module docstring step 5), in the
    page's own order. One entry per checkbox aria-label; a row with no parseable date is skipped
    rather than guessed at."""
    html = html or ""
    matches = list(_BILL_ARIA_RE.finditer(html))
    out: list[dict] = []
    for i, m in enumerate(matches):
        due = _parse_due_date(m.group(1))
        if due is None:
            continue
        try:
            amount = round(float(m.group(2).replace(",", "")), 2)
        except ValueError:
            continue
        window_end = min(m.end() + _FLAG_WINDOW,
                          matches[i + 1].start() if i + 1 < len(matches) else len(html))
        flags = sorted({f.strip().upper() for f in _FLAG_RE.findall(html[m.end():window_end])})
        out.append({"due_date": due, "amount": amount, "flags": flags})
    return out


#: the portal's own cumulative-balance figure on the combined bills page ("Payment Information
#: Total $N" -- module docstring, CONFIRMED LIVE): kept as corroborating evidence only, never the
#: verdict itself (a verdict is decided per claimed/eligible levy year, like every other verifier
#: here).
_TOTAL_RE = re.compile(r"Total\b.{0,200}?\$([\d,]+\.\d{2})", re.S)


def parse_total(html: str) -> Optional[float]:
    m = _TOTAL_RE.search(html or "")
    if not m:
        return None
    try:
        return round(float(m.group(1).replace(",", "")), 2)
    except ValueError:
        return None


_HAS_NEXT_PAGE_RE = re.compile(r'data-testid="next-page(?:-link|-button)?"|>\s*Next Page\s*<', re.I)

#: Billing History rows are a DIFFERENT, simpler shape than Available Bills (module docstring
#: step 5): a plain link per RESOLVED ($0.00, almost always) past bill, no checkbox/aria-label at
#: all -- confirmed live on the two clean parcels in the module docstring (a decade of $0.00 rows
#: each). One <a data-testid="primaryLink"> per row, carrying the due date and amount as plain
#: text inside it.
_HISTORY_ITEM_RE = re.compile(r'data-testid="primaryLink"[^>]*>(.*?)</a>', re.S)
_HISTORY_DATE_RE = re.compile(r">([A-Za-z]{3} \d{1,2}, \d{4})<")
_HISTORY_AMOUNT_RE = re.compile(r"\$([\d,]+\.\d{2})")


def parse_billing_history_rows(html: str) -> list[dict]:
    """[{due_date: date, amount: float}] of every Billing History row on a page (module docstring
    step 5's second, simpler table) -- used only to confirm a claimed year was PAID (resolved,
    amount 0.0), never to find a new delinquency (Available Bills is read for that)."""
    out: list[dict] = []
    for m in _HISTORY_ITEM_RE.finditer(html or ""):
        block = m.group(1)
        dm = _HISTORY_DATE_RE.search(block)
        am = _HISTORY_AMOUNT_RE.search(block)
        if not dm or not am:
            continue
        due = _parse_due_date(dm.group(1))
        if due is None:
            continue
        try:
            amount = round(float(am.group(1).replace(",", "")), 2)
        except ValueError:
            continue
        out.append({"due_date": due, "amount": amount})
    return out


_SECTION_START_RE = re.compile(r">\s*Available Bills\s*[\(<]")
_SECTION_END_RE = re.compile(r">\s*Billing History\s*[\(<]")


def _available_bills_section(html: str) -> str:
    """The slice of an account page between its rendered "Available Bills" heading and its
    "Billing History" heading (or the end of the page). Scopes parse_inline_bill_items below to
    just that section -- both widgets share the same data-testid="primaryLink" row marker, and a
    resolved Billing History row must never be read as a current unpaid bill. Matches only a
    RENDERED heading (">Available Bills(" / "<") -- the app's own i18n config blob carries the
    same English phrase too, but as a quoted JSON value, never preceded by ">"."""
    html = html or ""
    start = _SECTION_START_RE.search(html)
    if not start:
        return ""
    end = _SECTION_END_RE.search(html, start.end())
    return html[start.end():end.start() if end else len(html)]


def _billing_history_section(html: str) -> str:
    """The slice of a page from its rendered "Billing History" heading onward -- scopes
    parse_billing_history_rows so, when called on the WHOLE account page (which also carries the
    Available Bills widget, sharing the same primaryLink row marker), an open unpaid bill is never
    misread as a resolved one. A page that is only the dedicated billing-history subpage (no
    Available Bills widget on it at all) scopes to itself unchanged."""
    html = html or ""
    start = _SECTION_END_RE.search(html)
    return html[start.end():] if start else html


def parse_inline_bill_items(html: str) -> list[dict]:
    """[{due_date, amount, flags}] read directly off an account page's compact Available Bills
    widget (module docstring step 5: a simpler <a data-testid="primaryLink"> list, the same shape
    Billing History uses, NOT the full table's checkbox/aria-label shape parse_bill_rows reads) --
    used only when there is no "view all" link (everything already fits here: the clean examples
    in the module docstring had just the one open bill, no link to a fuller table at all)."""
    section = _available_bills_section(html)
    out: list[dict] = []
    for m in _HISTORY_ITEM_RE.finditer(section):
        block = m.group(1)
        dm = _HISTORY_DATE_RE.search(block)
        am = _HISTORY_AMOUNT_RE.search(block)
        if not dm or not am:
            continue
        due = _parse_due_date(dm.group(1))
        if due is None:
            continue
        try:
            amount = round(float(am.group(1).replace(",", "")), 2)
        except ValueError:
            continue
        flags = sorted({f.strip().upper() for f in _FLAG_RE.findall(block)})
        out.append({"due_date": due, "amount": amount, "flags": flags})
    return out


# ---------------------------------------------------------------------------
# browser automation (nodriver via browser_utils.start_browser) -- the live, multi-step guest
# flow, module docstring. Every selector below was exercised live, 2026-10-19, against the real
# app (the fieldset/dt-dd/data-testid shapes quoted in comments are genuine, not assumed).
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _close_session(st: dict) -> None:
    browser = st.get("browser")
    if browser is None:
        return
    try:
        browser.stop()
    except Exception:  # noqa: BLE001 - best-effort cleanup only
        pass


def _run(client: Any) -> dict:
    """Per-sweep-run state, cached on `client` (the same weakref.WeakKeyDictionary pattern
    tax_lien_billtrax / tax_lien_wake use for their own per-run session cache): ONE Chrome process
    is started on the first row this run checks and reused for every later row (module docstring,
    _ensure_browser) -- but never a cached logged-in PAGE across rows, see _ensure_browser's own
    docstring for why. Closed via weakref.finalize when `client` (the sweep's Fetcher) is
    garbage-collected at the end of the run."""
    try:
        st = _RUNS.get(client)
        if st is None:
            st = {"browser": None, "failures": 0}
            _RUNS[client] = st
            weakref.finalize(client, _close_session, st)
        return st
    except TypeError:          # client not weak-referenceable: no sharing, still correct
        return {"browser": None, "failures": 0}


def _js_click_leaf_text(text: str) -> str:
    return (
        "(() => {\n"
        f"  const target = {json.dumps(text)};\n"
        "  const all = document.querySelectorAll('button, a, [role=\"button\"], div, span, label');\n"
        "  for (const el of all) {\n"
        "    if (el.children.length === 0 && el.textContent.trim() === target) { el.click(); return true; }\n"
        "  }\n"
        "  return false;\n"
        "})()"
    )


_JS_CLICK_PAY_AS_GUEST = _js_click_leaf_text("Pay as Guest")
_JS_CLICK_CONNECT_PROPERTIES = _js_click_leaf_text("Connect Properties")
_JS_CLICK_VIEW_PROPERTIES = _js_click_leaf_text("View Properties")

_JS_CLICK_FORM_LINK = (
    "(() => {\n"
    f"  const prefix = {json.dumps(CONNECT_FORM_PATH_PREFIX)};\n"
    "  const a = Array.from(document.querySelectorAll('a'))\n"
    "    .find(a => (a.getAttribute('href') || '').startsWith(prefix));\n"
    "  if (!a) return false;\n"
    "  a.click();\n"
    "  return true;\n"
    "})()"
)

#: Every radio/checkbox in this app's own design system (CoolWebUI/CoolConstUI) renders the real
#: <input> itself DISABLED (live-confirmed 2026-10-19: a native .click() or the Python-level
#: nodriver Element.click() both silently do nothing on it -- a disabled form control cannot be
#: activated at all, by a real user or a script) with a separate, enabled <label for="its-id">
#: carrying the actual onClick selection logic. Every click-a-radio/checkbox helper below must
#: target that label, never the input.
_JS_LABEL_FOR = "(document.querySelector(`label[for=\"${id}\"]`) || input.closest('label'))"

#: the Parcel Number radio is matched by its own label text, not a fixed index -- a form
#: re-order (the live form had Bill/Parcel/Account/Owner/Business in that order, 2026-10-19)
#: never silently selects the wrong search method.
_JS_SELECT_PARCEL_RADIO = (
    "(() => {\n"
    "  const radios = document.querySelectorAll('input[type=\"radio\"]');\n"
    "  const input = Array.from(radios).find(r =>\n"
    "    (r.closest('label')?.textContent || r.parentElement?.textContent || '')"
    ".includes('Parcel Number'));\n"
    "  if (!input) return false;\n"
    "  const id = input.id;\n"
    f"  const label = {_JS_LABEL_FOR};\n"
    "  if (!label) return false;\n"
    "  label.click();\n"
    "  return true;\n"
    "})()"
)


def _js_fill_and_submit_parcel(parcel: str) -> str:
    """Sets the (React-controlled) text field via the native HTMLInputElement value setter + an
    'input' event -- a plain .value= assignment is invisible to a controlled component, the same
    trick scrapers/counties_nc/polk_tax.py's own JS form-fill already uses."""
    return (
        "(() => {\n"
        "  const inp = document.querySelector('input[type=\"text\"]');\n"
        "  if (!inp) return false;\n"
        "  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;\n"
        f"  setter.call(inp, {json.dumps(parcel)});\n"
        "  inp.dispatchEvent(new Event('input', {bubbles: true}));\n"
        "  const btn = Array.from(document.querySelectorAll('button'))\n"
        "    .find(b => b.type === 'submit' || b.textContent.trim() === 'Search');\n"
        "  if (!btn) return false;\n"
        "  btn.click();\n"
        "  return true;\n"
        "})()"
    )


def _js_select_result_checkbox(parcel_upper: str) -> str:
    """Selects the ONE search-result card whose own text contains the exact parcel string
    (module docstring step 4: each result is a <fieldset> with one checkbox, the parcel number
    printed as plain text inside it) -- never a fuzzy match. Clicks the checkbox's own label (the
    real <input> is disabled, module docstring note on _JS_LABEL_FOR)."""
    return (
        "(() => {\n"
        f"  const target = {json.dumps(parcel_upper)};\n"
        "  const cbs = document.querySelectorAll('input[type=\"checkbox\"]');\n"
        "  for (const input of cbs) {\n"
        "    const card = input.closest('fieldset') || input.closest('li') || input.parentElement;\n"
        "    const text = (card && card.textContent || '').toUpperCase();\n"
        "    if (text.indexOf(target) === -1) continue;\n"
        "    const id = input.id;\n"
        f"    const label = {_JS_LABEL_FOR};\n"
        "    if (!label) return false;\n"
        "    label.click();\n"
        "    return true;\n"
        "  }\n"
        "  return false;\n"
        "})()"
    )


def _js_click_view_all(href_substring: str) -> str:
    """Clicks the [data-testid="view-all-link"] whose href contains `href_substring` -- the
    account page can carry TWO such links (Available Bills' and Billing History's), so a bare
    querySelector would risk clicking the wrong one."""
    return (
        "(() => {\n"
        f"  const needle = {json.dumps(href_substring)};\n"
        "  const links = document.querySelectorAll('[data-testid=\"view-all-link\"]');\n"
        "  for (const a of links) {\n"
        "    if ((a.getAttribute('href') || '').includes(needle)) { a.click(); return true; }\n"
        "  }\n"
        "  return false;\n"
        "})()"
    )


_JS_CLICK_NEXT_PAGE = (
    "(() => {\n"
    "  const el = Array.from(document.querySelectorAll('button, a'))\n"
    "    .find(el => el.textContent.trim() === 'Next Page' && !el.disabled\n"
    "                && el.getAttribute('aria-disabled') !== 'true');\n"
    "  if (!el) return false;\n"
    "  el.click();\n"
    "  return true;\n"
    "})()"
)


async def _eval(page: Any, js: str, *, attempts: int = 3, interval_s: float = 1.0) -> Any:
    """page.evaluate(), retried a few times when it comes back falsy (0/false/None/""): a SPA
    click target that a moment ago was confirmed present in page.get_content() can still lose a
    race against React re-rendering the splash/transition state the instant before this runs
    (live-observed 2026-10-19: a first live run of this exact verifier hit "Pay as Guest control
    not found" on one call even though the content poll just before it had already seen that
    text) -- cheap insurance against that one JS-engine timing gap, not a sign the selector itself
    is wrong."""
    result = None
    for attempt in range(attempts):
        result = await page.evaluate(js, await_promise=True)
        if result:
            return result
        if attempt + 1 < attempts:
            await asyncio.sleep(interval_s)
    return result


async def _poll(page: Any, predicate, *, attempts: int = 12, interval_s: float = 1.5) -> str:
    """Polls page.get_content() until `predicate(html)` is true or attempts run out; returns the
    last HTML seen either way -- a timeout is evidence for the caller to act on, not a crash, the
    same discipline scrapers/counties_nc/polk_tax.py's own content-polling loops use."""
    html = ""
    for _ in range(attempts):
        html = await page.get_content()
        if predicate(html):
            return html
        await asyncio.sleep(interval_s)
    return html


async def _ensure_browser(st: dict) -> Any:
    """The one Chrome PROCESS for this sweep run (module docstring step 1), reused across rows to
    avoid repeated process-spawn cost (a few seconds each). Deliberately does NOT cache a
    logged-in page/session across rows: an early version of this verifier tried that and, live
    2026-10-19, one row's account-page state leaked into the NEXT row's read (a search for a
    clean parcel came back with the previous, unrelated parcel's dollar figures) -- a correctness
    risk this verifier will not accept for a speed gain, so _new_guest_page below starts every
    single row from a completely fresh "Pay as Guest" session instead. Raises PortalDown on
    failure; the caller turns that into `unconfirmed`/portal_unhealthy."""
    if st.get("browser") is not None:
        return st["browser"]
    from ...browser_utils import start_browser
    last_exc: Optional[BaseException] = None
    for attempt in range(2):   # a cold Chrome spawn can lose the first connect race
        try:
            st["browser"] = await start_browser(headless=True)
            return st["browser"]
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            await asyncio.sleep(2.0)
    raise PortalDown(f"{type(last_exc).__name__}: {str(last_exc)[:200]}") from last_exc


async def _new_guest_page(browser: Any) -> Any:
    """A fresh guest session, EVERY row (module docstring step 1): HOME_URL -> "Pay as Guest" ->
    the property-tax service page. `browser.get(url)` (new_tab=False, nodriver's default)
    navigates the SAME tab in place rather than accumulating a new one per row. Raises
    PortalDown; the caller turns that into `unconfirmed`."""
    try:
        page = await browser.get(HOME_URL)
        html = await _poll(page, lambda h: "Pay as Guest" in h, attempts=10, interval_s=1.0)
        if "Pay as Guest" not in html:
            raise PortalDown("home page never showed Pay as Guest")
        if not await _eval(page, _JS_CLICK_PAY_AS_GUEST):
            raise PortalDown("Pay as Guest control not found")
        html = await _poll(page, lambda h: "Connect Property" in h, attempts=12, interval_s=1.5)
        if "Connect Property" not in html:
            raise PortalDown("guest session did not reach the property-tax service page")
        return page
    except PortalDown:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PortalDown(f"{type(exc).__name__}: {str(exc)[:200]}") from exc


async def _open_connect_form(page: Any) -> None:
    """Opens the Connect Property form (module docstring step 2) off a just-started guest session
    (_new_guest_page): the form link is on the service page every such session lands on."""
    if not await _eval(page, _JS_CLICK_FORM_LINK):
        raise PortalDown("Connect Property form link not found")
    html = await _poll(page, lambda h: "Find Your Property" in h or "Choose a search method" in h)
    if "Find Your Property" not in html and "Choose a search method" not in html:
        raise PortalDown("Connect Property form did not load")
    # the search-method radios are a separate, slightly slower render than the heading above
    # (same class of hydration gap as the Available Bills widget, module docstring) -- wait for
    # them too before the caller tries to select one.
    html = await _poll(page, lambda h: 'type="radio"' in h, attempts=10, interval_s=1.0)
    if 'type="radio"' not in html:
        raise PortalDown("Connect Property form's search options never rendered")


async def _search_parcel(page: Any, parcel: str) -> str:
    """Submits the Parcel Number search (module docstring step 3) and returns the results-page
    HTML. A clean zero-results answer is returned as ordinary HTML for the caller to read (never
    raised here); PortalDown is only for a flow step the page itself could not perform."""
    if not await _eval(page, _JS_SELECT_PARCEL_RADIO):
        raise PortalDown("Parcel Number search option not found")
    # the text field the radio reveals is its own, slightly slower render (same hydration gap
    # class as the search-method radios themselves, module docstring) -- wait for it directly
    # rather than a fixed sleep.
    html = await _poll(page, lambda h: 'type="text"' in h, attempts=12, interval_s=1.0)
    if 'type="text"' not in html:
        raise PortalDown("parcel search text field never rendered")
    if not await _eval(page, _js_fill_and_submit_parcel(parcel)):
        raise PortalDown("parcel search field/button not found")
    return await _poll(
        page,
        lambda h: ("Select properties to connect" in h or "Connect Properties" in h
                   or "no properties" in h.lower() or "no results" in h.lower()
                   or "not what you" in h.lower()),
        attempts=12, interval_s=1.5)


async def _connect_and_view(page: Any, parcel: str) -> str:
    """Selects the search-result card for `parcel` (module docstring step 4), connects it (the
    free guest "connect" step) and opens its account page; returns the account page HTML. Raises
    PortalDown("no_exact_parcel_match") when no result card named this exact parcel (a zero- or
    off-target search)."""
    if not await _eval(page, _js_select_result_checkbox(parcel.upper())):
        raise PortalDown("no_exact_parcel_match")
    await asyncio.sleep(0.3)
    if not await _eval(page, _JS_CLICK_CONNECT_PROPERTIES):
        raise PortalDown("Connect Properties control not found")
    html = await _poll(page, lambda h: "been connected" in h.lower() or "view properties" in h.lower())
    if "been connected" not in html.lower():
        raise PortalDown("connect step did not confirm")
    if not await _eval(page, _JS_CLICK_VIEW_PROPERTIES):
        raise PortalDown("View Properties control not found")
    html = await _poll(page, lambda h: "Account/Parcel Number" in h or "Owner Name" in h)
    if "Account/Parcel Number" not in html:
        raise PortalDown("account page did not load")
    # The header renders first; the Available Bills widget is a separate, slightly slower data
    # fetch (live-observed 2026-10-19: the header alone was ready ~3s before the bill rows /
    # "view all" link were) -- wait for that too, so a caller never reads a half-rendered page.
    html = await _poll(page, lambda h: ('data-testid="primaryLink"' in h
                                        or 'data-testid="view-all-link"' in h
                                        or "you have no" in h.lower()),
                       attempts=15, interval_s=1.5)
    return html


async def _read_all_bills(page: Any, account_html: str) -> tuple[list[dict], Optional[float]]:
    """Every Available Bills row for this account (module docstring step 5), parsed with the
    shape that matches where it was read: the account page's own compact widget
    (parse_inline_bill_items, a simple <a data-testid="primaryLink"> list -- the clean examples
    in the module docstring never had anything more) when there is no "view all" link, else the
    full checkbox/aria-label table page (parse_bill_rows) that link opens, following "Next Page"
    up to a generous, bounded number of pages (the W Branch St example needed 2 of them for 15
    bills) so a chronic decade-plus delinquency is read in full without an unbounded loop on a
    page that could in principle keep paginating forever. The click is tried directly (not gated
    on a prior HTML substring check): the app's own i18n config blob embeds "Available Bills" /
    "Billing History" as plain JSON strings too, so a text check alone is not reliable evidence a
    link is actually on the page -- data-testid="view-all-link" is."""
    if await _eval(page, _js_click_view_all("/bills/")):
        html = await _poll(page, lambda h: "Available Bills" in h or "ineligible" in h.lower())
        combined = html
        for _ in range(4):   # up to 5 pages total, ~50 bills -- generous over any real history
            if not _HAS_NEXT_PAGE_RE.search(html):
                break
            if not await _eval(page, _JS_CLICK_NEXT_PAGE):
                break
            html = await _poll(page, lambda h: "Showing" in h)
            combined += html
        return parse_bill_rows(combined), parse_total(combined)
    return parse_inline_bill_items(account_html), parse_total(account_html)


async def _read_billing_history(page: Any, account_html: str) -> list[dict]:
    """Every Billing History row for this account (module docstring step 5's second, simpler
    table): only fetched when Available Bills found nothing currently delinquent, to decide
    `stale` vs `unconfirmed` -- the account page's own inline rows when there is no "View All"
    for this section, else that page's rows (same shape either way: parse_billing_history_rows)."""
    if await _eval(page, _js_click_view_all("billing-history")):
        html = await _poll(page, lambda h: "Billing History" in h)
        return parse_billing_history_rows(_billing_history_section(html))
    return parse_billing_history_rows(_billing_history_section(account_html))


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "parcel", "latest_levy_year", "delinquent_by_year", "total_delinquent",
         "years_delinquent", "not_yet_delinquent_due", "claimed_years", "resolved_claimed_years",
         "portal_total_owed", "bills_read", "chronic_claim", "late_levy_years",
         "history_from_levy", "history_complete", "error")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION,
                 verifier=_NAME)


async def verify(row: dict, client: Any, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    claimed = claimed_years(row)
    ev: dict[str, Any] = {"claimed_years": claimed}
    parcel = parcel_of(row)
    if not parcel:
        return _res("unconfirmed", dict(ev, reason="no_parcel"))
    ev["parcel"] = parcel
    ev["url"] = BASE + CONNECT_FORM_PATH_PREFIX + "4e007c95-491d-4dc1-8bb1-8c3e107c3de0"

    st = _run(client)
    try:
        browser = await _ensure_browser(st)
    except PortalDown as exc:
        return _res("unconfirmed", dict(ev, reason="portal_unhealthy", error=str(exc)[:200]))

    # The whole live flow is retried once on a failure (or an empty-bills read, module docstring
    # TIMING NOTE below): several of this SPA's screens render their real content a few seconds
    # AFTER the markers this verifier already polls for (the page's header loads before its data
    # table does); live-measured 2026-10-19, most such gaps clear well inside the existing polls,
    # but an occasional slower one does not -- the whole flow is cheap enough (a few seconds) that
    # a couple of clean retries from a fresh guest session is simpler and more robust than chasing
    # every individual wait threshold higher.
    last_exc: Optional[BaseException] = None
    for attempt in range(3):
        try:
            page = await _new_guest_page(browser)
            await _open_connect_form(page)
            await _search_parcel(page, parcel)
            account_html = await _connect_and_view(page, parcel)
            header = parse_header(account_html)
            header_parcel = re.sub(r"\s+", "", header.get("Account/Parcel Number") or "").upper()
            if header_parcel and header_parcel != parcel:
                return _res("unconfirmed", dict(ev, reason="identity_conflict"))
            try:
                bills, total = await _read_all_bills(page, account_html)
            except Exception:  # noqa: BLE001 - the account page's own bills still decide
                bills, total = parse_inline_bill_items(account_html), parse_total(account_html)
            if bills:
                st["failures"] = 0
                break
            last_exc = None   # a clean, decisive empty read is still worth one retry below
        except PortalDown as exc:
            reason = str(exc)
            if reason == "no_exact_parcel_match":
                return _res("unconfirmed", dict(ev, reason="parcel_not_found"))
            last_exc = exc
        except Exception as exc:  # noqa: BLE001
            return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                            error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    else:
        st["failures"] = st.get("failures", 0) + 1
        if st["failures"] >= 3:
            st["browser"] = None   # force a fresh Chrome process on the next row, not just a retry
        if last_exc is not None:
            return _res("unconfirmed", dict(ev, reason="session_failed", error=str(last_exc)[:200]))
        return _res("unconfirmed", dict(ev, reason="no_bills"))

    ev["bills_read"] = len(bills)
    if total is not None:
        ev["portal_total_owed"] = total

    delinquent: dict[str, float] = {}
    current: dict[str, float] = {}
    late_levy_years: list[int] = []
    for b in bills:
        levy_year = b["due_date"].year - 1
        late = tax_calendar.levy_year_is_delinquent(levy_year, "NC", "Johnston", today)
        if late:
            late_levy_years.append(levy_year)
        if b["amount"] > 0 and late:
            delinquent[str(levy_year)] = round(delinquent.get(str(levy_year), 0.0) + b["amount"], 2)
        elif b["amount"] > 0:
            current[str(levy_year)] = round(current.get(str(levy_year), 0.0) + b["amount"], 2)

    ev["latest_levy_year"] = max(b["due_date"].year - 1 for b in bills)
    ev.update(history_from_levy=tc.HISTORY_FROM_LEVY, history_complete=False,
              late_levy_years=sorted({y for y in late_levy_years if y >= tc.HISTORY_FROM_LEVY}),
              chronic_claim=tc.history_claims(late_levy_years, False))
    if current:
        ev["not_yet_delinquent_due"] = current
    if delinquent:
        ev.update(delinquent_by_year=dict(sorted(delinquent.items(), reverse=True)),
                  total_delinquent=tc.money_total(delinquent), years_delinquent=len(delinquent))
        return _res("confirmed", ev)

    # nothing currently owed and late -- check Billing History for a resolved claimed year
    try:
        history_rows = await _read_billing_history(page, account_html)
    except Exception:  # noqa: BLE001
        history_rows = []
    resolved_claimed = sorted({h["due_date"].year - 1 for h in history_rows
                               if h["amount"] == 0 and (h["due_date"].year - 1) in claimed},
                              reverse=True)
    if resolved_claimed:
        ev["resolved_claimed_years"] = resolved_claimed
        return _res("stale", ev)
    return _res("unconfirmed", dict(ev, reason="claimed_year_not_in_bill_history"))
