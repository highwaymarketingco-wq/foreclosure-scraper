"""Albemarle Observer NC delinquent-tax list republications (added 2026-09-21).

Each county's list is laid out differently. The post bodies below are hand-built from the
shapes read live (Tyrrell <li>, Washington <li> with an account number, Gates <p> rows with a
year and a situs, Bertie <table>); every name, parcel, account and amount is invented.

Chowan/Hyde/Perquimans-Hertford-Winfall (added 2026-10-03, extraction-completeness audit):
the scraper's own INDEX_URL query was already returning these 3 posts every run, but no
Target matched their titles, so the data was fetched and thrown away. Chowan <table> (parcel +
situs + 2 owner-name columns + mailing city/state), Hyde <table> (name + free-text property
description, no parcel), Perquimans/Hertford/Winfall <li> (one joint notice, name+amount+parcel
run together). Shapes below are hand-built from the real live layout; names/parcels/amounts
invented.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

import foreclosure_scraper.scrapers.counties_nc.albemarle_observer_tax_lists as m
from foreclosure_scraper.models import ListingType

TYRRELL = """<p class="wp-block-paragraph">COLUMBIA - Published below is the delinquent property tax.</p>
<ul class="wp-block-list"><li>AGUILAR, HILDA C00415005 485.94</li>
<li>ARMSTRONG, RANDY G &amp; PAULA G T07103008 4,629.92</li>
<li>BAILEY, LOUIS W &#8211; ESTATE T17501003 420.79</li>
<li>Note: this line has no amount</li></ul>"""

WASHINGTON = """<p>NOTICE OF ADVERTISEMENT OF TAX LIENS ON REAL PROPERTY WASHINGTON COUNTY/TOWN OF CRESWELL</p>
<ul><li>Jones, Joe Willie Heirs 27790 1,052.39 *</li><li>Jones, Katie (hudson) Heirs 27820 304.37</li></ul>
<ul><li>Smith, Pat 30001 12.50</li></ul>"""

PLYMOUTH = "<ul><li>731 INVESTMENTS LLC $397.00</li><li>BROWN, ARONIUS $85.86</li><li>BROWN, ARONIUS $22.14</li></ul>"

GATES = """<p class="wp-block-paragraph">Under and by virtue of the authority vested in me by Section 105-369.</p>
<p>KNIGHT, ANDREW, HEIRS 2025 RD #1306 GOODMAN RD $172.83&nbsp;</p>
<p>KNIGHT, ANDREW, HEIRS 2024 RD #1306 GOODMAN RD $237.52&nbsp;</p>
<p>KELLY, TRACY 2025 42 HARRELL CHURCH RD $203.51&nbsp;</p>
<p>KELLY, TRACY 2024 42 HARRELL CHURCH RD $231.96
KELLY, TRACY 2023 42 HARRELL CHURCH RD $250.00</p>
<p>KENDALL, BETTY 2025 95 TYLER RD $268.05 KING, DONNIE 2025 $131.31&nbsp;</p>"""

BERTIE = """<table><thead><tr><th>Current Owner</th><th>PIN</th><th>Amount</th></tr></thead><tbody>
<tr><td>ALSTON ANNETTE &amp; JORDAN BRYON M</td><td>25A5869412801</td><td>$66.87</td></tr>
<tr><td>A AND E HOMES INC</td><td>25A690026869002</td><td>101.65</td></tr>
<tr><td>NOT A PIN</td><td>hello</td><td>$1.00</td></tr></tbody></table>"""

CHOWAN = """<p>Published below is the delinquent property tax list for Chowan County.</p>
<table><tbody>
<tr><td>Parcel Number</td><td>Property Address</td><td>Name1</td><td>Name 2</td><td>City</td><td>State</td><td>Total Due</td></tr>
<tr><td>697007792923</td><td>100 CHEYENNE TRL</td><td>3B DEVELOPMENT INC</td><td></td><td>WASHINGTON</td><td>NC</td><td>86.79</td></tr>
<tr><td>780520706376</td><td>124 E CARTERET ST</td><td>AHMAD, JALEES</td><td>AHMAD, MARIAM</td><td>DURHAM</td><td>NC</td><td>2746.86</td></tr>
<tr><td>699200136763</td><td>108 RYLAND RD</td><td>AINSLEY, BONNIE</td><td></td><td>KITTREDGE</td><td>CO</td><td>241.21</td></tr>
<tr><td>689412877469</td><td></td><td>ADAMS, RAYMOND, III</td><td></td><td>EDENTON</td><td>NC</td><td>543.38</td></tr>
<tr><td>780518306324</td><td>101 CHOWAN CT</td><td>BELFIELD, CARROLL L</td><td>BELFIELD, JOLYQUIN A</td><td>EDENTON</td><td>NC</td><td>2142</td></tr>
<tr><td></td><td>NO PARCEL ROW</td><td>NOBODY</td><td></td><td>EDENTON</td><td>NC</td><td>9.99</td></tr>
</tbody></table>"""

HYDE = """<p>Published below is the delinquent property tax list for Hyde County for 2025.</p>
<table><tbody>
<tr><td>Name</td><td>Property</td><td>Amount Owed</td></tr>
<tr><td>ABRAMS, SHELIA MCCULLOUGH</td><td>LOT &amp; HOUSE</td><td>$1,001.93</td></tr>
<tr><td>ADAMS, MONNIE</td><td>2.50 AC. CLAYTON</td><td>$57.07</td></tr>
<tr><td>ADAMS, MONNIE</td><td>1/2 INT.IN 48 AC.</td><td>$103.04</td></tr>
<tr><td>NO NAME HERE</td><td></td><td></td></tr>
</tbody></table>"""

PERQUIMANS_HERTFORD_WINFALL = (
    "<p>NOTICE OF ADVERTISEMENT OF TAX LIENS ON REAL PROPERTY PERQUIMANS COUNTY, HERTFORD AND WINFALL</p>"
    "<ul>"
    "<li>ABREGO, ARELY &amp; HUSBAND, &nbsp; &nbsp; 399.50 2-D070-0022-BF&nbsp;</li>"
    "<li>ALBEMARLE PRESERVE, LLC, &nbsp; &nbsp; 417.45 P-D082-Y018-AP</li>"
    "<li>Note: this line has no amount or parcel</li>"
    "</ul>"
)


def _post(title, date="2026-05-26T09:00:00"):
    return {"id": 1, "date": date, "link": "https://albemarleobserver.news/x/", "title": {"rendered": title}}


# --------------------------------------------------------------------------- row parsers

def test_tyrrell_rows_carry_a_parcel():
    b = m.parse_tyrrell(TYRRELL)
    assert [(x["owner"], x["parcel"], x["amount"]) for x in b] == [
        ("AGUILAR, HILDA", "C00415005", 485.94),
        ("ARMSTRONG, RANDY G & PAULA G", "T07103008", 4629.92),
        ("BAILEY, LOUIS W – ESTATE", "T17501003", 420.79)]


def test_washington_rows_carry_an_account_and_a_flag():
    b = m.parse_washington(WASHINGTON)
    assert [(x["owner"], x["account"], x["amount"], x["flag"]) for x in b] == [
        ("Jones, Joe Willie Heirs", "27790", 1052.39, True),
        ("Jones, Katie (hudson) Heirs", "27820", 304.37, False),
        ("Smith, Pat", "30001", 12.5, False)]
    # The joint heading is not used to attribute a row to a town.
    assert {x["jurisdiction"] for x in b} == {"WASHINGTON COUNTY"}


def test_plymouth_rows_are_name_and_amount_only():
    b = m.parse_plymouth(PLYMOUTH)
    assert len(b) == 3 and b[0]["owner"] == "731 INVESTMENTS LLC" and b[0]["amount"] == 397.0
    assert {x["jurisdiction"] for x in b} == {"TOWN OF PLYMOUTH"}


def test_gates_rows_split_on_newlines_and_skip_a_run_together_row():
    b = m.parse_gates(GATES)
    got = [(x["owner"], x["year"], x["situs"], x["amount"]) for x in b]
    assert ("KNIGHT, ANDREW, HEIRS", 2025, "RD #1306 GOODMAN RD", 172.83) in got
    # Two rows in one <p>, separated by a newline: both are read.
    assert ("KELLY, TRACY", 2024, "42 HARRELL CHURCH RD", 231.96) in got
    assert ("KELLY, TRACY", 2023, "42 HARRELL CHURCH RD", 250.0) in got
    # The source's own glitch (two rows merged, second missing its situs) is skipped whole,
    # not read as a lead whose situs is another person's row.
    assert not any("KENDALL" in g[0] for g in got)
    assert not any("$" in g[2] for g in got)


def test_bertie_pins_drop_the_25a_prefix_and_keep_longer_parcel_numbers():
    b = m.parse_bertie(BERTIE)
    assert [(x["parcel"], x["account"], x["amount"]) for x in b] == [
        ("5869412801", "25A5869412801", 66.87), ("690026869002", "25A690026869002", 101.65)]


def test_chowan_rows_carry_parcel_situs_and_mailing_city_state():
    b = m.parse_chowan(CHOWAN)
    # The row with no parcel number is dropped; the row with no situs keeps parsing
    # (parcel-keyed, not situs-keyed) with situs=None rather than an empty string.
    assert len(b) == 5
    first = next(x for x in b if x["parcel"] == "697007792923")
    assert first == {"owner": "3B DEVELOPMENT INC", "parcel": "697007792923", "amount": 86.79,
                      "situs": "100 CHEYENNE TRL", "mail_city": "WASHINGTON", "mail_state": "NC"}
    co_owned = next(x for x in b if x["parcel"] == "780520706376")
    assert co_owned["owner"] == "AHMAD, JALEES & AHMAD, MARIAM"
    no_situs = next(x for x in b if x["parcel"] == "689412877469")
    assert no_situs["situs"] is None
    out_of_state = next(x for x in b if x["parcel"] == "699200136763")
    assert out_of_state["mail_city"] == "KITTREDGE" and out_of_state["mail_state"] == "CO"


def test_chowan_amount_is_not_truncated_when_it_has_no_decimal_or_comma():
    """2142 (no decimal, no comma) must parse whole -- a \\d{1,3}(?:,\\d{3})* style
    alternation would partial-match just '214' and silently drop the trailing digit."""
    b = m.parse_chowan(CHOWAN)
    whole = next(x for x in b if x["parcel"] == "780518306324")
    assert whole["amount"] == 2142.0


def test_hyde_rows_have_no_parcel_and_keep_distinct_properties_per_owner():
    b = m.parse_hyde(HYDE)
    assert len(b) == 3  # the blank name/amount row is dropped
    assert all(x.get("parcel") is None for x in b) and all("parcel" not in x for x in b)
    monnie = [x for x in b if x["owner"] == "ADAMS, MONNIE"]
    assert len(monnie) == 2
    assert {x["property"] for x in monnie} == {"2.50 AC. CLAYTON", "1/2 INT.IN 48 AC."}
    assert {x["amount"] for x in monnie} == {57.07, 103.04}


def test_perquimans_rows_accept_a_letter_leading_parcel_id():
    b = m.parse_perquimans(PERQUIMANS_HERTFORD_WINFALL)
    assert [(x["owner"], x["parcel"], x["amount"]) for x in b] == [
        ("ABREGO, ARELY & HUSBAND", "2-D070-0022-BF", 399.50),
        ("ALBEMARLE PRESERVE, LLC", "P-D082-Y018-AP", 417.45),
    ]


# --------------------------------------------------------------------------- selection

INDEX = [
    {"id": 1, "date": "2026-06-11T10:00:00", "link": "u1", "title": {"rendered": "Plymouth&#8217;s Delinquent Tax List — Have You Paid Your Taxes?"}},
    {"id": 2, "date": "2026-06-09T10:00:00", "link": "u2", "title": {"rendered": "Washington County Delinquent Property Tax List — Have you paid your taxes?"}},
    {"id": 3, "date": "2026-07-10T10:00:00", "link": "u3", "title": {"rendered": "Washington County Commissioners Tackle Recreational and Infrastructure Needs"}},
    {"id": 4, "date": "2025-05-26T10:00:00", "link": "u4", "title": {"rendered": "Gates County Delinquent Property Tax List"}},          # last year's
    {"id": 5, "date": "2026-05-26T10:00:00", "link": "u5", "title": {"rendered": "Gates County Delinquent Property Tax List — Have you paid your taxes?"}},
    {"id": 6, "date": "2026-06-05T10:00:00", "link": "u6", "title": {"rendered": "Bertie County 2025 delinquent personal property tax list"}},
    {"id": 7, "date": "2026-04-27T10:00:00", "link": "u7", "title": {"rendered": "Public Record: Tyrrell County 2025 Unpaid Taxes List"}},
    {"id": 8, "date": "2026-04-16T10:00:00", "link": "u8", "title": {"rendered": "Chowan County Delinquent Property Tax List — Have you paid your taxes?"}},
    {"id": 9, "date": "2026-09-10T10:00:00", "link": "u9", "title": {"rendered": "Chowan County commissioners weigh pros and cons of data centers"}},
    {"id": 10, "date": "2026-07-14T10:00:00", "link": "u10", "title": {"rendered": "Hyde County Delinquent Property Tax List — Have you paid your taxes?"}},
    {"id": 11, "date": "2026-06-11T10:00:00", "link": "u11", "title": {"rendered": "Perquimans Co, Hertford and Winfall — Have You Paid Your Taxes?"}},
]
TODAY = datetime(2026, 9, 21)


def test_the_right_post_is_picked_per_target():
    want = {"Tyrrell": 7, "Gates": 5, "Bertie": 6, "Chowan": 8, "Hyde": 10, "Perquimans": 11}
    for t in m.TARGETS:
        p = m.pick_post(INDEX, t, today=TODAY)
        if t.county in want:
            assert p["id"] == want[t.county]
    wash = [m.pick_post(INDEX, t, today=TODAY)["id"] for t in m.TARGETS if t.county == "Washington"]
    assert wash == [2, 1]                     # the county list, then Plymouth's; never the commissioners story


def test_a_list_older_than_400_days_is_not_read():
    gates = next(t for t in m.TARGETS if t.county == "Gates")
    assert m.pick_post([INDEX[3]], gates, today=TODAY) is None
    assert m.pick_post([], gates, today=TODAY) is None


def test_the_newest_of_two_matching_posts_wins():
    gates = next(t for t in m.TARGETS if t.county == "Gates")
    assert m.pick_post([INDEX[3], INDEX[4]], gates, today=TODAY)["id"] == 5


def test_list_year_prefers_the_body_then_the_title_then_the_post_year():
    d = datetime(2026, 5, 26)
    assert m.list_year("x", d, "advertising tax liens for the year 2025 upon") == 2025
    assert m.list_year("Tyrrell County 2025 Unpaid Taxes List", d, "") == 2025
    assert m.list_year("Gates County list", d, "") == 2025


# --------------------------------------------------------------------------- leads

def test_gates_leads_group_by_owner_and_situs_and_sum_the_years():
    t = next(t for t in m.TARGETS if t.county == "Gates")
    leads = m.to_listings(t, m.parse_gates(GATES), post=_post("Gates County Delinquent Property Tax List"),
                          content="advertising tax liens for the year 2025")
    by = {(l.owner_name, l.raw["albemarle_observer_tax_list"]["situs_text"]): l for l in leads}
    kt = by[("KELLY, TRACY", "42 HARRELL CHURCH RD")]
    assert kt.raw["albemarle_observer_tax_list"]["years"] == [2023, 2024, 2025]
    assert kt.raw["tax_owed"]["balance"] == 685.47 and kt.raw["albemarle_observer_tax_list"]["is_two_year_plus"]
    assert kt.street_address == "42 HARRELL CHURCH RD" and kt.parcel_id is None
    assert kt.raw["two_year_delinquent"]["is_two_year_plus"] is True and kt.raw["two_year_delinquent"]["years"] == 3
    road = by[("KNIGHT, ANDREW, HEIRS", "RD #1306 GOODMAN RD")]
    assert road.street_address is None and road.legal_description == "RD #1306 GOODMAN RD"
    assert all(l.listing_type == ListingType.TAX_LIEN and l.sale_date is None for l in leads)
    assert all(l.source == "counties_nc.albemarle_observer_tax_lists" and l.state == "NC"
               and l.county == "Gates" for l in leads)


def test_tyrrell_and_bertie_leads_carry_a_parcel_and_the_principal_only_flag():
    t = next(t for t in m.TARGETS if t.county == "Tyrrell")
    (a, *_rest) = m.to_listings(t, m.parse_tyrrell(TYRRELL), post=_post("Tyrrell County 2025 Unpaid Taxes List",
                                                                          "2026-04-27T09:00:00"), content="")
    assert a.parcel_id == "C00415005" and a.raw["tax_owed"]["balance"] == 485.94
    assert "two_year_delinquent" not in a.raw          # one list year says nothing about age
    assert a.raw["albemarle_observer_tax_list"]["principal_only"] is True
    assert a.raw["albemarle_observer_tax_list"]["post_url"] == "https://albemarleobserver.news/x/"
    assert a.source_url.startswith("https://albemarleobserver.news/x/#")


def test_chowan_leads_carry_street_address_and_absentee_owner_signal():
    t = next(t for t in m.TARGETS if t.county == "Chowan")
    leads = m.to_listings(t, m.parse_chowan(CHOWAN), post=_post("Chowan County Delinquent Property Tax List"),
                          content="")
    local = next(l for l in leads if l.parcel_id == "697007792923")
    assert local.street_address == "100 CHEYENNE TRL" and "absentee_owner" in local.raw
    assert local.raw["absentee_owner"]["out_of_state"] is False
    oos = next(l for l in leads if l.parcel_id == "699200136763")
    assert oos.raw["absentee_owner"] == {"mail_city": "KITTREDGE", "mail_state": "CO",
                                         "out_of_state": True, "source": m.SLUG}
    no_situs = next(l for l in leads if l.parcel_id == "689412877469")
    assert no_situs.street_address is None and no_situs.legal_description is None


def test_hyde_leads_have_no_street_but_carry_the_property_text_as_legal_description():
    t = next(t for t in m.TARGETS if t.county == "Hyde")
    leads = m.to_listings(t, m.parse_hyde(HYDE), post=_post("Hyde County Delinquent Property Tax List"),
                          content="")
    assert len(leads) == 3  # Monnie's two distinct tracts are NOT merged
    assert all(l.street_address is None and l.parcel_id is None for l in leads)
    assert {l.legal_description for l in leads} == {"LOT & HOUSE", "2.50 AC. CLAYTON", "1/2 INT.IN 48 AC."}
    assert len({l.dedupe_key() for l in leads}) == 3  # distinct dedupe keys despite no parcel


def test_perquimans_leads_carry_a_parcel_and_county_label():
    t = next(t for t in m.TARGETS if t.county == "Perquimans")
    leads = m.to_listings(t, m.parse_perquimans(PERQUIMANS_HERTFORD_WINFALL),
                          post=_post("Perquimans Co, Hertford and Winfall — Have You Paid Your Taxes?"), content="")
    assert len(leads) == 2 and all(l.county == "Perquimans" and l.state == "NC" for l in leads)
    assert {l.parcel_id for l in leads} == {"2-D070-0022-BF", "P-D082-Y018-AP"}


def test_washington_leads_group_by_account_and_plymouth_by_owner():
    tw = next(t for t in m.TARGETS if t.parser is m.parse_washington)
    leads = m.to_listings(tw, m.parse_washington(WASHINGTON), post=_post("Washington County Delinquent Property Tax List"), content="")
    assert len(leads) == 3 and all(l.parcel_id is None for l in leads)
    tp = next(t for t in m.TARGETS if t.parser is m.parse_plymouth)
    pl = m.to_listings(tp, m.parse_plymouth(PLYMOUTH), post=_post("Plymouth's Delinquent Tax List"), content="")
    brown = next(l for l in pl if l.owner_name == "BROWN, ARONIUS")
    assert brown.raw["tax_owed"]["balance"] == 108.0 and len(pl) == 2


# --------------------------------------------------------------------------- the crawl

def _transport(posts: dict[int, str], seen: list, index=None):
    def handler(req: httpx.Request):
        seen.append(str(req.url))
        if "search=delinquent" in str(req.url):
            return httpx.Response(200, json=index if index is not None else INDEX)
        pid = int(req.url.path.rsplit("/", 1)[1])
        if pid not in posts:
            return httpx.Response(404)
        return httpx.Response(200, json={"id": pid, "content": {"rendered": posts[pid]}})
    return httpx.MockTransport(handler)


def _patch(monkeypatch, transport):
    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    monkeypatch.setattr(m, "PACE_S", 0.0)
    monkeypatch.setattr(m, "datetime", type("D", (datetime,), {"utcnow": staticmethod(lambda: TODAY)}))


_ALL_POSTS = {7: TYRRELL, 2: WASHINGTON, 1: PLYMOUTH, 5: GATES, 6: BERTIE,
              8: CHOWAN, 10: HYDE, 11: PERQUIMANS_HERTFORD_WINFALL}


def test_the_scraper_reads_the_index_then_only_the_current_posts(monkeypatch):
    seen: list = []
    _patch(monkeypatch, _transport(_ALL_POSTS, seen))
    out = asyncio.run(m.AlbemarleObserverTaxLists().fetch())
    counties = sorted({l.county for l in out})
    assert counties == ["Bertie", "Chowan", "Gates", "Hyde", "Perquimans", "Tyrrell", "Washington"]
    # One index request plus eight posts (one per Target); the stale Gates post (id 4), the
    # Washington commissioners story (id 3) and the Chowan commissioners story (id 9) are
    # never fetched even though the index returns them too.
    assert len(seen) == 9
    assert not any(u.endswith("/4?_fields=id,date,link,title,content") for u in seen)
    assert not any(u.endswith("/9?_fields=id,date,link,title,content") for u in seen)


def test_a_post_whose_layout_changed_is_named_not_silently_empty(monkeypatch):
    seen: list = []
    posts = dict(_ALL_POSTS)
    posts[7] = "<p>We redesigned the page, no list here</p>"
    _patch(monkeypatch, _transport(posts, seen))
    out = asyncio.run(m.AlbemarleObserverTaxLists().fetch())
    assert "Tyrrell" not in {l.county for l in out} and "Gates" in {l.county for l in out}


def test_a_dead_index_is_an_empty_run_not_a_crash(monkeypatch):
    def handler(req):
        return httpx.Response(503)
    _patch(monkeypatch, httpx.MockTransport(handler))
    assert asyncio.run(m.AlbemarleObserverTaxLists().fetch()) == []


def test_a_sample_limit_caps_each_list(monkeypatch):
    seen: list = []
    _patch(monkeypatch, _transport(_ALL_POSTS, seen))
    s = m.AlbemarleObserverTaxLists()
    s.limit = 1
    out = asyncio.run(s.fetch())
    assert len(out) == 8                      # one lead from each of the eight lists


def test_rows_with_no_parcel_and_no_address_keep_distinct_dedupe_keys():
    """Listing.dedupe_key() falls back to source_url. If every row of a post shared one URL the
    board's dedupe would collapse Washington's 1,206 name-and-account rows into a single lead."""
    tw = next(t for t in m.TARGETS if t.parser is m.parse_washington)
    leads = m.to_listings(tw, m.parse_washington(WASHINGTON), post=_post("Washington County Delinquent Property Tax List"), content="")
    assert len({li.dedupe_key() for li in leads}) == len(leads) == 3
    from foreclosure_scraper.dedupe import dedupe
    assert len(dedupe(leads)) == 3
    tg = next(t for t in m.TARGETS if t.county == "Gates")
    road = [l for l in m.to_listings(tg, m.parse_gates(GATES), post=_post("Gates County Delinquent"), content="")
            if not l.street_address]
    assert road and len({l.dedupe_key() for l in road}) == len(road)
