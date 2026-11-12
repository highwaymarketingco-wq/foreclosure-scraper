"""tax_lien_johnston: Johnston County NC's myJohnstonCountyNC guest portal (PayIt Gov).

The HTML fixtures below are genuine markup fragments, trimmed -- captured live 2026-10-19 from a
real read-only guest-browser walkthrough (no account created, no payment) of 8 real Johnston
parcels, documented in the module's own docstring. Every dollar figure, due date and flag in the
assertions below is read straight off that live session, not invented:

  * 01011021A, W BRANCH ST, "SMITH, D. CHESTER HEIRS" -- chronic delinquent: 2024's bill (due
    Jan 6, 2025) $388.94 OVERDUE, 2025's (due Jan 5, 2026) $499.85 OVERDUE, 2026's (due
    Jan 5, 2027) $453.60 not yet due, cumulative portal total $7,286.64.
  * 01023008, 504 E HILL ST, "CAGLE, NEIL C" -- fully current: a decade of Billing History rows
    all $0.00, only the not-yet-due 2026 bill ($1,790.99) owed.

verify() itself is tested with the browser-driving steps monkeypatched out (no real Chrome): the
pure parsers above are what actually reads the real markup, and are tested directly against it.
"""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.verifiers import tax_lien_johnston as V

TODAY = date(2026, 10, 19)


def run(coro):
    return asyncio.run(coro)


def _row(parcel_id="01011021A", county="Johnston", state="NC", **kw) -> dict:
    r = {"state": state, "county": county, "parcel_id": parcel_id, "owner_name": "EXAMPLE OWNER",
        "listing_type": "tax_lien", "source": "counties_generic.nc_onemap", "raw": {}}
    r.update(kw)
    return r


# ---------------------------------------------------------------------------
# real captured markup
# ---------------------------------------------------------------------------

HEADER_HTML_HEIRS = (
    '<dl class="g"><div class="i"><dt class="t"><span>Account/Parcel Number</span></dt>'
    '<dd class="v">01011021A</dd></div><div class="i"><dt class="t"><span>Owner Name</span></dt>'
    '<dd class="v">SMITH, D. CHESTER HEIRS</dd></div><div class="i"><dt class="t">'
    '<span>Account Number</span></dt><dd class="v">002000217480</dd></div></dl>'
)

HEADER_HTML_CLEAN = (
    '<dl class="g"><div class="i"><dt class="t"><span>Account/Parcel Number</span></dt>'
    '<dd class="v">01023008</dd></div><div class="i"><dt class="t"><span>Owner Name</span></dt>'
    '<dd class="v">CAGLE, NEIL C</dd></div><div class="i"><dt class="t">'
    '<span>Account Number</span></dt><dd class="v">002000182218</dd></div></dl>'
)


def _bill_row(due: str, amount: str, *flags: str) -> str:
    """One Available-Bills row -- a trimmed but real shape: the checkbox aria-label (the only
    place a row's due date and amount are NOT duplicated mobile/desktop, module docstring) plus
    the real status-badge span markup for each flag."""
    flag_html = "".join(
        f'<span data-status-column-item="true" class="CoolConstUI_StatusBadge-styles_x">{f}</span>'
        for f in flags)
    return (
        f'<input type="checkbox" aria-label="Select bill due {due} totalling ${amount}. '
        f'Expands additional payment options below">{flag_html}'
    )


#: real shape (module docstring): W Branch St, 3 of its 15 real bills (the other 12 are the
#: "Ineligible for Online Payment" sub-table further down the same combined page).
BILLS_HTML_HEIRS = (
    '<div class="Payment Information"><span>Total</span><span>$7,286.64</span></div>'
    + _bill_row("Jan 6, 2025", "388.94", "Overdue")
    + _bill_row("Jan 5, 2026", "499.85", "Overdue")
    + _bill_row("Jan 5, 2027", "453.60")
)

#: real shape: 504 E Hill St, the one open (not-yet-due) bill only.
BILLS_HTML_CLEAN = _bill_row("Jan 5, 2027", "1,790.99")

HISTORY_HTML_CLEAN = "".join(
    f'<a data-testid="primaryLink" href="x"><div><span>{d}</span><span>504 E HILL ST</span>'
    f'<div>${a}</div></div></a>'
    for d, a in [("Jan 5, 2026", "0.00"), ("Jan 6, 2025", "0.00"), ("Jan 5, 2024", "0.00")]
)


# ---------------------------------------------------------------------------
# pure parsers
# ---------------------------------------------------------------------------

def test_parse_header_reads_the_real_dl_shape():
    h = V.parse_header(HEADER_HTML_HEIRS)
    assert h == {"Account/Parcel Number": "01011021A", "Owner Name": "SMITH, D. CHESTER HEIRS",
                "Account Number": "002000217480"}


def test_parse_bill_rows_reads_due_date_amount_and_flags():
    bills = V.parse_bill_rows(BILLS_HTML_HEIRS)
    assert [b["amount"] for b in bills] == [388.94, 499.85, 453.60]
    assert bills[0]["due_date"] == date(2025, 1, 6)
    assert bills[0]["flags"] == ["OVERDUE"]
    assert bills[2]["flags"] == []     # the current, not-yet-due bill carries no status flag


def test_parse_bill_rows_reads_not_payable_too():
    row = _bill_row("Jan 7, 2013", "461.99", "Overdue", "NOT PAYABLE")
    bills = V.parse_bill_rows(row)
    assert bills[0]["flags"] == ["NOT PAYABLE", "OVERDUE"]


def test_parse_bill_rows_two_adjacent_rows_do_not_bleed_flags():
    """A clean current-year row right after an overdue one must not inherit the first row's
    flags (the window is bounded by the NEXT row's own aria-label)."""
    html = _bill_row("Jan 6, 2025", "388.94", "Overdue") + _bill_row("Jan 5, 2027", "453.60")
    bills = V.parse_bill_rows(html)
    assert bills[0]["flags"] == ["OVERDUE"]
    assert bills[1]["flags"] == []


def test_parse_billing_history_reads_the_real_shape():
    rows = V.parse_billing_history_rows(HISTORY_HTML_CLEAN)
    assert [(r["due_date"], r["amount"]) for r in rows] == [
        (date(2026, 1, 5), 0.0), (date(2025, 1, 6), 0.0), (date(2024, 1, 5), 0.0)]


def test_parse_total_reads_the_portals_own_cumulative_figure():
    assert V.parse_total(BILLS_HTML_HEIRS) == 7286.64
    assert V.parse_total(BILLS_HTML_CLEAN) is None   # no Total block on this fixture


# ---------------------------------------------------------------------------
# the account page's COMPACT Available Bills widget -- a different, simpler shape than the full
# table page (<a data-testid="primaryLink"> list items, no checkbox/aria-label at all), found
# live 2026-10-19 AFTER this verifier's first live run against the real portal mis-parsed it as
# zero bills -- real shape confirmed straight off that live account page.
# ---------------------------------------------------------------------------

#: real shape, trimmed (01011021A's account page, live 2026-10-19): one overdue inline row.
INLINE_BILL_ITEM_OVERDUE = (
    '<li role="listitem"><a data-testid="primaryLink" class="CoolConstUI_BillItem-styles_wrapper_x">'
    '<div><div><span data-status-column-item="true" class="CoolConstUI_StatusBadge-styles_x">'
    'Overdue</span></div><span>Jan 6, 2025</span></div>'
    '<div class="CoolConstUI_BillItem-styles_rightSection_x">'
    '<div class="CoolWebUI_styles_heading6_x"><span>$388.94</span></div></div></a></li>'
)

ACCOUNT_PAGE_WITH_INLINE_WIDGETS = (
    HEADER_HTML_CLEAN
    + '<h2><span>Available Bills</span></h2>' + INLINE_BILL_ITEM_OVERDUE
    + '<h2><span>Billing History</span></h2>' + HISTORY_HTML_CLEAN
)


def test_available_bills_section_excludes_billing_history_rows():
    section = V._available_bills_section(ACCOUNT_PAGE_WITH_INLINE_WIDGETS)
    assert "388.94" in section
    assert "504 E HILL ST" not in section    # that text only appears in the Billing History rows


def test_available_bills_section_ignores_the_i18n_config_blob():
    """The app embeds "Available Bills" a second time as a quoted JSON config string
    (module docstring / source comment) -- never rendered with a ">" right before it, so it must
    not be mistaken for the real heading."""
    noise = '"availableBillsPageTitle":{"en":"Available Bills"}' + ACCOUNT_PAGE_WITH_INLINE_WIDGETS
    section = V._available_bills_section(noise)
    assert "388.94" in section


def test_billing_history_section_excludes_available_bills_rows():
    section = V._billing_history_section(ACCOUNT_PAGE_WITH_INLINE_WIDGETS)
    assert "504 E HILL ST" in section
    assert "388.94" not in section


def test_parse_inline_bill_items_reads_the_compact_widget_shape():
    items = V.parse_inline_bill_items(ACCOUNT_PAGE_WITH_INLINE_WIDGETS)
    assert items == [{"due_date": date(2025, 1, 6), "amount": 388.94, "flags": ["OVERDUE"]}]


def test_parse_inline_bill_items_never_leaks_billing_history_rows():
    """A parcel whose only content is a resolved Billing History (the clean examples' decade of
    $0.00 rows) must never be misread as zero CURRENT bills owed from a cross-contaminated list --
    parse_inline_bill_items reads nothing when there is no real Available Bills section."""
    assert V.parse_inline_bill_items(HISTORY_HTML_CLEAN) == []


# ---------------------------------------------------------------------------
# applies / parcel_of
# ---------------------------------------------------------------------------

def test_registered_with_the_shared_tax_lien_contract():
    v = {x.name: x for x in registry.discover()}["tax_lien_johnston"]
    assert v.signal == "tax_lien" and v.governs and not v.wall


def test_applies_only_to_johnston_nc_rows_with_a_tax_claim():
    assert V.applies(_row())
    assert not V.applies(_row(county="Wake"))
    assert not V.applies(_row(state="SC"))
    assert not V.applies(_row(listing_type="distressed", raw={}))


def test_parcel_of_recognizes_the_real_shapes_and_rejects_junk():
    assert V.parcel_of(_row(parcel_id="01E08015R")) == "01E08015R"
    assert V.parcel_of(_row(parcel_id="01011021a")) == "01011021A"   # case-normalized
    assert V.parcel_of(_row(parcel_id=None)) is None
    assert V.parcel_of(_row(parcel_id="not a parcel")) is None


# ---------------------------------------------------------------------------
# verify: end to end, browser-driving steps monkeypatched (no real Chrome)
# ---------------------------------------------------------------------------

def _patch_flow(monkeypatch, *, account_html, bills_html=None, history_html=None,
                connect_fails=False, session_fails=False):
    async def fake_ensure_browser(st):
        if session_fails:
            raise V.PortalDown("simulated portal outage")
        return object()

    async def fake_new_guest_page(browser):
        return object()

    async def fake_open_form(page):
        return None

    async def fake_search(page, parcel):
        return "<div>Select properties to connect</div>"

    async def fake_connect_and_view(page, parcel):
        if connect_fails:
            raise V.PortalDown("no_exact_parcel_match")
        return account_html

    async def fake_read_all_bills(page, account_html_):
        html = bills_html if bills_html is not None else account_html_
        return V.parse_bill_rows(html), V.parse_total(html)

    async def fake_read_history(page, account_html_):
        html = history_html if history_html is not None else account_html_
        return V.parse_billing_history_rows(html)

    monkeypatch.setattr(V, "_ensure_browser", fake_ensure_browser)
    monkeypatch.setattr(V, "_new_guest_page", fake_new_guest_page)
    monkeypatch.setattr(V, "_open_connect_form", fake_open_form)
    monkeypatch.setattr(V, "_search_parcel", fake_search)
    monkeypatch.setattr(V, "_connect_and_view", fake_connect_and_view)
    monkeypatch.setattr(V, "_read_all_bills", fake_read_all_bills)
    monkeypatch.setattr(V, "_read_billing_history", fake_read_history)


def test_confirmed_on_the_real_chronic_delinquent_parcel(monkeypatch):
    _patch_flow(monkeypatch, account_html=HEADER_HTML_HEIRS + BILLS_HTML_HEIRS,
                bills_html=BILLS_HTML_HEIRS)
    r = run(V.verify(_row(parcel_id="01011021A"), object(), today=TODAY))
    assert r.verdict == "confirmed"
    assert r.evidence["delinquent_by_year"] == {"2024": 388.94, "2025": 499.85}
    assert r.evidence["total_delinquent"] == 888.79
    assert r.evidence["years_delinquent"] == 2
    assert r.evidence["portal_total_owed"] == 7286.64
    assert r.evidence["not_yet_delinquent_due"] == {"2026": 453.60}
    assert "owner" not in str(r.evidence).lower()        # public ledger
    assert "smith" not in str(r.evidence).lower()


def test_stale_on_the_real_clean_parcel_with_a_claimed_resolved_year(monkeypatch):
    _patch_flow(monkeypatch, account_html=HEADER_HTML_CLEAN + BILLS_HTML_CLEAN,
                bills_html=BILLS_HTML_CLEAN, history_html=HISTORY_HTML_CLEAN)
    row = _row(parcel_id="01023008",
              raw={"tax_aging_surfaced": {"status": "delinquent", "years_delinquent": 1,
                                          "tax_year": 2024}})
    r = run(V.verify(row, object(), today=TODAY))
    assert r.verdict == "stale"
    assert r.evidence["resolved_claimed_years"] == [2024]
    assert r.evidence["not_yet_delinquent_due"] == {"2026": 1790.99}


def test_unconfirmed_when_the_claimed_year_is_not_in_bill_history(monkeypatch):
    _patch_flow(monkeypatch, account_html=HEADER_HTML_CLEAN + BILLS_HTML_CLEAN,
                bills_html=BILLS_HTML_CLEAN, history_html="<p>no rows here</p>")
    row = _row(parcel_id="01023008", raw={"tax_aging_surfaced": {"status": "delinquent",
                                                                 "years_delinquent": 1,
                                                                 "tax_year": 2024}})
    r = run(V.verify(row, object(), today=TODAY))
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "claimed_year_not_in_bill_history"


def test_no_parcel_is_unconfirmed_with_no_browser_session_at_all(monkeypatch):
    called = False

    async def fake_ensure_browser(st):
        nonlocal called
        called = True
        return object()
    monkeypatch.setattr(V, "_ensure_browser", fake_ensure_browser)
    r = run(V.verify(_row(parcel_id=None), object(), today=TODAY))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_parcel"
    assert called is False


def test_portal_down_is_unconfirmed_not_raised(monkeypatch):
    _patch_flow(monkeypatch, account_html="", session_fails=True)
    r = run(V.verify(_row(), object(), today=TODAY))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "portal_unhealthy"
    assert "portal_unhealthy" in V.TRANSIENT_REASONS   # retried soon, not treated as a real miss


def test_no_exact_parcel_match_is_unconfirmed_parcel_not_found(monkeypatch):
    _patch_flow(monkeypatch, account_html="", connect_fails=True)
    r = run(V.verify(_row(), object(), today=TODAY))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "parcel_not_found"


def test_identity_conflict_when_the_account_page_names_a_different_parcel(monkeypatch):
    other_header = HEADER_HTML_CLEAN.replace("01023008", "01099999")
    _patch_flow(monkeypatch, account_html=other_header + BILLS_HTML_CLEAN)
    r = run(V.verify(_row(parcel_id="01023008"), object(), today=TODAY))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "identity_conflict"


def test_run_state_is_cached_per_client_and_closed_on_gc():
    """The weakref session cache (module docstring): the SAME dict comes back for the same
    client object, a fresh one for a different object, and browser.stop() fires when the client
    is collected."""
    stopped = []

    class FakeBrowser:
        def stop(self):
            stopped.append(True)

    class FakeClient:
        """A plain object() cannot be weak-referenced; a verifier's real `client` (a Fetcher) can
        be, same as this stand-in."""

    client_a, client_b = FakeClient(), FakeClient()
    st_a1 = V._run(client_a)
    st_a1["browser"] = FakeBrowser()
    st_a2 = V._run(client_a)
    assert st_a1 is st_a2
    st_b = V._run(client_b)
    assert st_b is not st_a1
    del client_a
    import gc
    gc.collect()
    assert stopped == [True]
