"""counties_nc.polk_tax -- per-row detail-page enrichment (source-completeness
audit, Pattern D, 2026-10-13).

The module's own docstring + a code comment on `raw["polk_tax_search"]`
admitted the per-record detail page (taxdetail.php?id=N) was never fetched:
"not fetched per-row this pass ... a follow-up if parcel/address-level
detail is wanted here." Live-verified 2026-10-13 against the real site:

  * The detail page needs NO browser at all -- unlike the search FORM
    (searchtaxrecord.php / searchingtaxrecord.php), which is WAF-blocked for
    everything except a real/nodriver-driven browser, a plain GET to
    taxdetail.php?id=N answers 200 to curl-cffi Chrome TLS/JA3 impersonation
    (`get_text_impersonate`) -- confirmed on ids 1, 2, 3, 7, 10, 15, 33, 50,
    77, 120, 250, 500, 10000, 20000.
  * Real fields present: Status, Total Due, Collection Status, Owner Name
    (full, incl. "ET UX" / co-owner / "C/O ..." lines the list view
    truncates), Owner ID, Tax Receipt Number, Bill Number, Parcel Number
    (populated for real-estate parcels like id=120's "P118-20", blank for
    others e.g. mobile-home-only bills like id=1), Mailing Address (2+
    lines joined by <br>), District, Type, Description, Assessed Value,
    Base Amount, Charges.
  * Two confirmed-live "not a real record" shapes that must be rejected,
    not parsed as data: id=0 answers "No Tax Record was requested. Try
    Searching again !!!" (plus a re-rendered copy of the search FORM markup
    below it); a negative/non-numeric/nonexistent id answers the site's own
    unrendered SQL verbatim -- literally "select count(*) recordcount from
    tax_data where id=...". Also confirmed live: an intermittent Cloudflare
    "Just a moment" challenge even on this endpoint (id=5000 403'd once,
    then 200'd twice in a row seconds later) -- get_text_impersonate's own
    retry clears most of these before `_parse_detail_html` ever sees one,
    but a slipped-through challenge page must still come back as "no data",
    never as a crash or a fabricated record.

The HTML fixtures below are trimmed-but-real captures from the live site.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.scrapers.counties_nc.polk_tax import (
    PolkTaxAuction,
    _apply_detail,
    _DETAIL_BUDGET_SHARE,
    _DETAIL_FETCH_CAP,
    _fetch_detail,
    _parse_detail_html,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

# --- real captures ----------------------------------------------------------

# id=1: unpaid mobile-home bill, no parcel number, blank collection status.
_DETAIL_HTML_NO_PARCEL = """
<div style="width:100%;">
    <table style="border: solid 2px #003A00; font-weight: bold; width: 300px;" cellpadding="3" cellspacing="0">
         <tbody>
              <tr>
                   <td>Status:</td>
                   <td>
                                                               Unpaid  <!-- Add CSS -->
                                                     </td>
              </tr>
              <tr>
                   <td>Total Due:</td>
                   <td>$41.50</td>
              </tr>
              <tr>
                   <td>Date Paid:</td>
                   <td>

                   </td>
              </tr>
              <tr>
                   <td>Amount Paid:</td>
                   <td>
                                         </td>
              </tr>
              <tr>
                   <td> Collection Status:</td>
                   <td>
                                         </td>
              </tr>
         </tbody>
    </table>
    <table style="border: 0; font-size: .9em; margin: 20px 0;" cellpadding="0" cellspacing="0">
         <tbody>
              <tr>
                   <td style="width: 33%;">
                        <table cellpadding="5" cellspacing="0">
                             <tbody>
                                  <tr>
                                       <td style="width: 140px;"> Owner Name: </td>
                                       <td>
                                           JOHNSON CLARENCE GARY ET UX / JOHNSON AUDREY                                       </td>
                                  </tr>
                                  <tr>
                                       <td style="width: 140px;">Owner ID:</td>
                                       <td>1000147</td>
                                  </tr>
                                  <tr>
                                       <td>Tax Receipt Number:</td>
                                       <td>723968</td>
                                  </tr>
                                  <tr>
                                       <td>Bill Number:</td>
                                       <td>617004</td>
                                  </tr>
                                  <tr>
                                       <td>Parcel Number:</td>
                                       <td></td>
                                  </tr>
                                  <tr>
                                      <td>Mailing Address:</td>
                                      <td>PO BOX 1120 <br>SALUDA, NC 28773</td>
                                  <tr>
                                       <td>District:</td>
                                       <td>007</td>
                                  </tr>                  <tr>
                                  <tr>
                                       <td>Type:</td>
                                       <td>
                                           Property                                       </td>
                                  </tr>
                                  <tr>
                                       <td>Description:</td>
                                       <td>1979 FLEETWOOD 00012 00065</td>
                                  </tr>
                             </tbody>
                        </table>
                   </td>
                   <td style="width: 33%;">
                        <table cellpadding="5" cellspacing="0">
                             <tbody>
                                  <tr>
                                       <td>Assessed Value:</td>
                                       <td>1000</td>
                                  </tr>
                                  <tr>
                                       <td>Base Amount:</td>
                                       <td>$40.91</td>
                                  </tr>
                                  <tr>
                                       <td>Charges:</td>
                                       <td>
                                       $0.59                                       </td>
                                  </tr>
                             </tbody></table>
                   </td>
        </tr>
    </tbody></table>
</div>
"""

# id=120: unpaid real-estate parcel, parcel number + collection status blank,
# a real street-looking Description.
_DETAIL_HTML_WITH_PARCEL = """
<div style="width:100%;">
    <table style="border: solid 2px #003A00; font-weight: bold; width: 300px;" cellpadding="3" cellspacing="0">
         <tbody>
              <tr>
                   <td>Status:</td>
                   <td>
                                                               Unpaid  <!-- Add CSS -->
                                                     </td>
              </tr>
              <tr>
                   <td>Total Due:</td>
                   <td>$879.25</td>
              </tr>
              <tr>
                   <td> Collection Status:</td>
                   <td>
                                         </td>
              </tr>
         </tbody>
    </table>
    <table style="border: 0; font-size: .9em; margin: 20px 0;" cellpadding="0" cellspacing="0">
         <tbody>
              <tr>
                   <td style="width: 33%;">
                        <table cellpadding="5" cellspacing="0">
                             <tbody>
                                  <tr>
                                       <td style="width: 140px;"> Owner Name: </td>
                                       <td>
                                           SKIPPER RONALD E / SKIPPER TERESA E                                       </td>
                                  </tr>
                                  <tr>
                                       <td style="width: 140px;">Owner ID:</td>
                                       <td>10172</td>
                                  </tr>
                                  <tr>
                                       <td>Tax Receipt Number:</td>
                                       <td>724192</td>
                                  </tr>
                                  <tr>
                                       <td>Bill Number:</td>
                                       <td>617163</td>
                                  </tr>
                                  <tr>
                                       <td>Parcel Number:</td>
                                       <td>P118-20</td>
                                  </tr>
                                  <tr>
                                      <td>Mailing Address:</td>
                                      <td>938 GREEN CREEK DR <br>COLUMBUS, NC 28722</td>
                                  <tr>
                                       <td>District:</td>
                                       <td>005</td>
                                  </tr>                  <tr>
                                  <tr>
                                       <td>Type:</td>
                                       <td>
                                           Property                                       </td>
                                  </tr>
                                  <tr>
                                       <td>Description:</td>
                                       <td>938 GREEN CREEK RD</td>
                                  </tr>
                             </tbody>
                        </table>
                   </td>
                   <td style="width: 33%;">
                        <table cellpadding="5" cellspacing="0">
                             <tbody>
                                  <tr>
                                       <td>Assessed Value:</td>
                                       <td>233981</td>
                                  </tr>
                                  <tr>
                                       <td>Base Amount:</td>
                                       <td>$879.25</td>
                                  </tr>
                                  <tr>
                                       <td>Charges:</td>
                                       <td>
                                       $0.00                                       </td>
                                  </tr>
                             </tbody></table>
                   </td>
        </tr>
    </tbody></table>
</div>
"""

# id=0, captured verbatim (minus the trailing re-rendered search form, which
# is irrelevant to the assertion but real on the live page too).
_DETAIL_HTML_NO_RECORD_REQUESTED = (
    '<b><font color="red"> No Tax Record was requested. Try Searching again '
    '!!! </font></b><form action="searchingtaxrecord.php" method="post">...</form>'
)

# A nonexistent / negative / non-numeric id, captured verbatim.
_DETAIL_HTML_SQL_LEAK = "select count(*) recordcount from tax_data where id=999999"

# A trimmed real Cloudflare "Just a moment" challenge body (id=5000, one of
# three live attempts -- the other two 200'd on retry).
_DETAIL_HTML_CLOUDFLARE_CHALLENGE = (
    '<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>'
    '<meta http-equiv="content-security-policy" content="default-src \'none\'; '
    "script-src 'nonce-mQyTkGPizOmwJg2SWa2dn1' 'unsafe-eval' "
    'https://challenges.cloudflare.com"></head><body>'
    '<div class="main-wrapper" role="main"></div></body></html>'
)


# --- _parse_detail_html ------------------------------------------------------

def test_parse_detail_html_no_parcel_record():
    extras = _parse_detail_html(_DETAIL_HTML_NO_PARCEL)
    assert extras["status"] == "Unpaid"
    assert extras["total_due"] == pytest.approx(41.50)
    assert extras["owner_name_full"] == "JOHNSON CLARENCE GARY ET UX / JOHNSON AUDREY"
    assert extras["owner_id"] == "1000147"
    assert extras["tax_receipt_number"] == "723968"
    assert extras["bill_number"] == "617004"
    assert extras["district"] == "007"
    assert extras["detail_type"] == "Property"
    assert extras["detail_description"] == "1979 FLEETWOOD 00012 00065"
    assert extras["assessed_value"] == pytest.approx(1000.0)
    assert extras["base_amount"] == pytest.approx(40.91)
    assert extras["charges"] == pytest.approx(0.59)
    assert extras["mailing_address"] == "PO BOX 1120, SALUDA, NC 28773"
    assert extras["mailing_state"] == "NC"
    # A genuinely blank field on the live page must not appear at all.
    assert "parcel_number" not in extras
    assert "collection_status" not in extras


def test_parse_detail_html_with_parcel_record():
    extras = _parse_detail_html(_DETAIL_HTML_WITH_PARCEL)
    assert extras["parcel_number"] == "P118-20"
    assert extras["total_due"] == pytest.approx(879.25)
    assert extras["assessed_value"] == pytest.approx(233981.0)
    assert extras["mailing_address"] == "938 GREEN CREEK DR, COLUMBUS, NC 28722"
    assert extras["owner_name_full"] == "SKIPPER RONALD E / SKIPPER TERESA E"


def test_parse_detail_html_rejects_no_record_notice():
    """id=0's confirmed-live response must never be parsed as a record."""
    assert _parse_detail_html(_DETAIL_HTML_NO_RECORD_REQUESTED) == {}


def test_parse_detail_html_rejects_sql_leak_response():
    """A negative/non-numeric/nonexistent id's confirmed-live response (the
    site's own unrendered SQL fragment) must never be parsed as a record."""
    assert _parse_detail_html(_DETAIL_HTML_SQL_LEAK) == {}
    assert _parse_detail_html("select count(*) recordcount from tax_data where id=-1") == {}
    assert _parse_detail_html("select count(*) recordcount from tax_data where id=abc") == {}


def test_parse_detail_html_rejects_cloudflare_challenge():
    """A Cloudflare challenge page that slipped past get_text_impersonate's
    own retry must come back as no data, never as a crash or a fake record."""
    assert _parse_detail_html(_DETAIL_HTML_CLOUDFLARE_CHALLENGE) == {}


def test_parse_detail_html_empty_input():
    assert _parse_detail_html("") == {}
    assert _parse_detail_html(None) == {}


def test_parse_detail_html_three_line_mailing_address():
    """Not yet seen live, but the parser must not assume exactly 2 lines."""
    html = _DETAIL_HTML_WITH_PARCEL.replace(
        "938 GREEN CREEK DR <br>COLUMBUS, NC 28722",
        "C/O JANE DOE <br>938 GREEN CREEK DR <br>COLUMBUS, NC 28722",
    )
    extras = _parse_detail_html(html)
    assert extras["mailing_address"] == "C/O JANE DOE, 938 GREEN CREEK DR, COLUMBUS, NC 28722"
    assert extras["mailing_state"] == "NC"


# --- _fetch_detail (network layer) ------------------------------------------

def test_fetch_detail_returns_empty_dict_on_fetch_failure(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("network down")

    import foreclosure_scraper.scrapers.counties_nc.polk_tax as mod
    monkeypatch.setattr(mod, "get_text_impersonate", _boom)
    extras = asyncio.run(_fetch_detail("120"))
    assert extras == {}


def test_fetch_detail_returns_empty_dict_on_unparseable_html(monkeypatch):
    async def _garbage(*a, **k):
        return "<html>not a tax record at all</html>"

    import foreclosure_scraper.scrapers.counties_nc.polk_tax as mod
    monkeypatch.setattr(mod, "get_text_impersonate", _garbage)
    extras = asyncio.run(_fetch_detail("120"))
    assert extras == {}


def test_fetch_detail_never_raises_even_on_parser_bug(monkeypatch):
    """Belt-and-suspenders: even a bug inside the parser must not propagate
    past _fetch_detail -- it is pure enrichment."""
    async def _ok(*a, **k):
        return _DETAIL_HTML_WITH_PARCEL

    import foreclosure_scraper.scrapers.counties_nc.polk_tax as mod
    monkeypatch.setattr(mod, "get_text_impersonate", _ok)

    def _boom(html):
        raise ValueError("parser exploded")

    monkeypatch.setattr(mod, "_parse_detail_html", _boom)
    extras = asyncio.run(_fetch_detail("120"))
    assert extras == {}


# --- _apply_detail ------------------------------------------------------------

def _base_listing(**overrides) -> Listing:
    from datetime import datetime, timezone
    kwargs = dict(
        source=PolkTaxAuction.slug,
        source_url="https://cms.revize.com/revize/apps/polkcounty/taxdetail.php?id=120",
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Polk",
        owner_name="SKIPPER RONALD E",
        description="Polk County delinquent tax — 938 GREEN CREEK RD",
        first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
        raw={"polk_tax_search": {"detail_id": "120", "tax_year": "2026",
                                  "description": "938 GREEN CREEK RD", "type": "Property"}},
    )
    kwargs.update(overrides)
    return Listing(**kwargs)


def test_apply_detail_noop_on_empty_extras():
    li = _base_listing()
    before = li.model_copy(deep=True)
    _apply_detail(li, {})
    assert li == before


def test_apply_detail_fills_parcel_assessed_mailing_and_amount():
    li = _base_listing()
    extras = _parse_detail_html(_DETAIL_HTML_WITH_PARCEL)
    _apply_detail(li, extras)

    assert li.parcel_id == "P118-20"
    assert li.assessed_value == pytest.approx(233981.0)
    assert li.owner_name == "SKIPPER RONALD E / SKIPPER TERESA E"
    assert "$879.25 owed" in li.description
    assert li.raw["polk_tax_search"]["detail"]["bill_number"] == "617163"
    assert li.raw["polk_tax_search"]["detail"]["status"] == "Unpaid"
    # Mailing/owner-name-full are surfaced via owner_mailing/owner_name, not
    # duplicated inside the nested detail block.
    assert "mailing_address" not in li.raw["polk_tax_search"]["detail"]
    assert "owner_name_full" not in li.raw["polk_tax_search"]["detail"]

    om = li.raw["owner_mailing"]
    assert om["mailing"] == "938 GREEN CREEK DR, COLUMBUS, NC 28722"
    assert om["owner"] == "SKIPPER RONALD E / SKIPPER TERESA E"
    assert om["situs"] is None
    assert om["mail_state"] == "NC"
    assert om["absentee"] is False
    assert om["out_of_state"] is False
    assert om["source"] == "polk_tax_detail"


def test_apply_detail_does_not_overwrite_existing_parcel_id():
    li = _base_listing(parcel_id="P999-99")
    extras = _parse_detail_html(_DETAIL_HTML_WITH_PARCEL)
    _apply_detail(li, extras)
    assert li.parcel_id == "P999-99"


def test_apply_detail_does_not_overwrite_existing_assessed_value():
    li = _base_listing(assessed_value=5.0)
    extras = _parse_detail_html(_DETAIL_HTML_WITH_PARCEL)
    _apply_detail(li, extras)
    assert li.assessed_value == 5.0


def test_apply_detail_out_of_state_flag_when_mail_state_not_nc():
    li = _base_listing()
    extras = dict(_parse_detail_html(_DETAIL_HTML_WITH_PARCEL))
    extras["mailing_address"] = "123 MAIN ST, GREENVILLE, SC 29601"
    extras["mailing_state"] = "SC"
    _apply_detail(li, extras)
    om = li.raw["owner_mailing"]
    assert om["mail_state"] == "SC"
    assert om["out_of_state"] is True


def test_apply_detail_blank_parcel_record_sets_no_parcel_but_sets_mailing():
    li = _base_listing(parcel_id=None)
    extras = _parse_detail_html(_DETAIL_HTML_NO_PARCEL)
    _apply_detail(li, extras)
    assert li.parcel_id is None
    assert li.raw["owner_mailing"]["mailing"] == "PO BOX 1120, SALUDA, NC 28773"


def test_apply_detail_zero_total_due_does_not_annotate_description():
    li = _base_listing()
    extras = dict(_parse_detail_html(_DETAIL_HTML_WITH_PARCEL))
    extras["total_due"] = 0.0
    before_desc = li.description
    _apply_detail(li, extras)
    assert li.description == before_desc


# --- detail-fetch volume cap / budget (_fetch_delinquent_search) ------------

def _search_results_html(ids: list[int]) -> str:
    rows = "".join(
        f'<tr class="oddRow"><td>OWNER {i}</td><td>Property</td>'
        f'<td>DESC {i}</td><td>2026</td>'
        f'<td><a href="taxdetail.php?id={i}">View</a></td></tr>'
        for i in ids
    )
    return f"<html><body><table>{rows}</table></body></html>"


class _FakeBrowser:
    def stop(self):
        pass


def test_detail_fetch_cap_limits_enrichment_without_dropping_listings(monkeypatch):
    """The cap must bound how many detail pages get fetched, never how many
    listings are returned -- every row from the search results page ships
    regardless of how much detail enrichment it got."""
    import foreclosure_scraper.scrapers.counties_nc.polk_tax as mod

    ids = list(range(2001, 2006))  # 5 distinct rows
    html = _search_results_html(ids)

    async def _fake_start_browser(**kw):
        return _FakeBrowser()

    async def _fake_search_via_nodriver(browser, term):
        # Only the first search term returns rows; the rest come back empty
        # so the loop finishes fast and deterministically.
        return html if term == mod._SEARCH_TERMS[0] else "<html></html>"

    calls: list[str] = []

    async def _counting_fetch_detail(detail_id):
        calls.append(detail_id)
        return {"status": "Unpaid", "total_due": 10.0}

    monkeypatch.setattr("foreclosure_scraper.browser_utils.start_browser", _fake_start_browser)
    monkeypatch.setattr(mod, "_search_via_nodriver", _fake_search_via_nodriver)
    monkeypatch.setattr(mod, "_fetch_detail", _counting_fetch_detail)
    monkeypatch.setattr(mod, "_DETAIL_FETCH_CAP", 2)

    scraper = PolkTaxAuction()
    scraper.partial = []
    rows = asyncio.run(scraper._fetch_delinquent_search())

    assert len(rows) == 5, "the cap must not drop any listing, only limit enrichment"
    assert len(calls) == 2, "the cap must bound how many detail pages get fetched"
    # Listings past the cap are untouched by detail enrichment.
    enriched = [r for r in rows if "detail" in r.raw.get("polk_tax_search", {})]
    assert len(enriched) == 2


def test_detail_fetch_budget_exhausted_still_ships_all_listings(monkeypatch):
    """A near-zero time budget must still ship every listing from the
    search-results page -- the budget only governs enrichment."""
    import foreclosure_scraper.scrapers.counties_nc.polk_tax as mod

    ids = list(range(3001, 3004))
    html = _search_results_html(ids)

    async def _fake_start_browser(**kw):
        return _FakeBrowser()

    async def _fake_search_via_nodriver(browser, term):
        return html if term == mod._SEARCH_TERMS[0] else "<html></html>"

    called = []

    async def _counting_fetch_detail(detail_id):
        called.append(detail_id)
        return {}

    monkeypatch.setattr("foreclosure_scraper.browser_utils.start_browser", _fake_start_browser)
    monkeypatch.setattr(mod, "_search_via_nodriver", _fake_search_via_nodriver)
    monkeypatch.setattr(mod, "_fetch_detail", _counting_fetch_detail)
    monkeypatch.setattr(mod, "_DETAIL_BUDGET_SHARE", 0.0)  # no time left for detail fetches

    scraper = PolkTaxAuction()
    scraper.partial = []
    rows = asyncio.run(scraper._fetch_delinquent_search())

    assert len(rows) == 3
    assert called == []  # budget was already spent before the loop started


def test_partial_banked_before_detail_enrichment(monkeypatch):
    """self.partial must hold every search-result listing BEFORE the
    detail-fetch pass runs, so a soft-timeout mid-enrichment still ships
    them (base_scraper.safe_run's partial-salvage path)."""
    import foreclosure_scraper.scrapers.counties_nc.polk_tax as mod

    ids = [4001, 4002]
    html = _search_results_html(ids)
    seen_partial_during_detail_fetch = []

    async def _fake_start_browser(**kw):
        return _FakeBrowser()

    async def _fake_search_via_nodriver(browser, term):
        return html if term == mod._SEARCH_TERMS[0] else "<html></html>"

    scraper = PolkTaxAuction()
    scraper.partial = []

    async def _recording_fetch_detail(detail_id):
        # self.partial must already carry both rows by the time ANY detail
        # fetch is attempted.
        seen_partial_during_detail_fetch.append(len(scraper.partial))
        return {}

    monkeypatch.setattr("foreclosure_scraper.browser_utils.start_browser", _fake_start_browser)
    monkeypatch.setattr(mod, "_search_via_nodriver", _fake_search_via_nodriver)
    monkeypatch.setattr(mod, "_fetch_detail", _recording_fetch_detail)

    rows = asyncio.run(scraper._fetch_delinquent_search())
    assert len(rows) == 2
    assert seen_partial_during_detail_fetch == [2, 2]


def test_detail_fetch_cap_and_budget_share_are_sane_constants():
    assert isinstance(_DETAIL_FETCH_CAP, int) and _DETAIL_FETCH_CAP > 0
    assert 0.0 <= _DETAIL_BUDGET_SHARE <= 1.0
