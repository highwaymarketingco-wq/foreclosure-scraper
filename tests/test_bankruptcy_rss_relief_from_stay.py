"""Bankruptcy CM/ECF public RSS -> relief-from-stay leads.

The RSS below is hand-written (made-up debtors, case numbers and trustees) in the
exact item shape the three courts served on 2026-10-07.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national import bankruptcy_rss_relief_from_stay as mod

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Recent Entries</title>
<item><title>26-09991-eg Alexandra Q. Testperson </title>
<link>https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?999001</link>
<description>Type: bk Office: 2 Chapter: 13 Trustee: Sample, Pat [Relief from Stay] ( 14 )</description>
<guid isPermaLink="true">https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?999001-40</guid>
<pubDate>Wed, 07 Oct 2026 15:00:00 GMT</pubDate></item>
<item><title>26-09991-eg Alexandra Q. Testperson </title>
<link>https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?999001</link>
<description>Type: bk Office: 2 Chapter: 13 Trustee: Sample, Pat [Receipt of Filing Fee for Relief from Stay] ( 15 )</description>
<guid isPermaLink="true">https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?999001-41</guid>
<pubDate>Wed, 07 Oct 2026 14:00:00 GMT</pubDate></item>
<item><title>26-09992-hb Robert Example and Mary Example</title>
<link>https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?999002</link>
<description>Type: bk Office: 6 Chapter: 7 Trustee: Placeholder, Lee [Order on Motion for Relief from Stay] (&#x3C;a href=&#x27;https://x/doc1/1&#x27;&#x3E;22&#x3C;/a&#x3E;)</description>
<guid isPermaLink="true">https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?999002-12</guid>
<pubDate>Wed, 07 Oct 2026 16:00:00 GMT</pubDate></item>
<item><title>26-09993-jd Fiction Holdings, LLC</title>
<link>https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?999003</link>
<description>Type: bk Office: 3 Chapter: 11 Trustee: Placeholder, Lee [Notice of Tentative Hearing] ( 9 )</description>
<guid isPermaLink="true">https://ecf.scb.uscourts.gov/cgi-bin/DktRpt.pl?999003-2</guid>
<pubDate>Wed, 07 Oct 2026 16:30:00 GMT</pubDate></item>
</channel></rss>"""

NOW = mod.datetime(2026, 10, 7, 20)


def test_parse_feed_reads_every_entry_and_its_metadata():
    entries = mod.parse_feed(RSS)
    assert len(entries) == 4
    e = entries[0]
    assert e["case_number"] == "26-09991-eg" and e["case_title"] == "Alexandra Q. Testperson"
    assert (e["chapter"], e["office"], e["event"]) == ("13", "2", "Relief from Stay")
    assert entries[2]["event"] == "Order on Motion for Relief from Stay"


def test_only_relief_from_stay_events_count_and_cases_are_grouped():
    cases = mod.group_cases(mod.parse_feed(RSS), "scb")
    by = {c["case_number"]: c for c in cases}
    assert set(by) == {"26-09991-eg", "26-09992-hb"}
    assert len(by["26-09991-eg"]["events"]) == 2
    assert by["26-09991-eg"]["first_seen_entry"].hour == 14
    assert by["26-09992-hb"]["has_order"] is True and by["26-09991-eg"]["has_order"] is False


def test_listing_is_a_debtor_name_bankruptcy_lead():
    case = next(c for c in mod.group_cases(mod.parse_feed(RSS), "scb") if c["case_number"] == "26-09991-eg")
    li = mod.build_listing(case, state="SC", district="District of South Carolina", now=NOW)
    assert li.listing_type == ListingType.BANKRUPTCY
    assert li.state == "SC" and li.county == "Statewide"
    assert li.defendant == "Alexandra Q. Testperson" and li.street_address is None
    assert li.source_url.endswith("DktRpt.pl?999001")
    b = li.raw["bankruptcy_relief_from_stay"]
    assert b["chapter"] == "13" and b["property_address"] is None and b["movant"] is None
    assert "asking to resume foreclosure" in li.description


def test_relief_regex_variants():
    for ev in ("Relief from Stay (fee)", "3-Relief from Stay, Abandonment (no fee)",
               "Motion for Relief from Co-Debtor Stay", "Motion to Lift Automatic Stay"):
        assert mod.is_relief_from_stay({"event": ev}), ev
    for ev in ("Discharge", "Notice of Tentative Hearing", "Motion to Extend Stay"):
        assert not mod.is_relief_from_stay({"event": ev}), ev


class _Resp:
    def __init__(self, text, status_code=200):
        self.text, self.status_code = text, status_code


class _Http:
    def __init__(self, by_host):
        self.by_host, self.calls = by_host, []

    async def get(self, url, **kw):
        self.calls.append(url)
        for frag, resp in self.by_host.items():
            if frag in url:
                return resp
        return _Resp("", 404)


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_fetch_reads_three_feeds_and_skips_a_non_rss_answer(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    http = _Http({"ecf.scb": _Resp(RSS), "ecf.ncmb": _Resp("<html>maintenance</html>"),
                  "ecf.ncwb": _Resp('<?xml version="1.0"?><rss><channel></channel></rss>')})
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.BankruptcyRssReliefFromStay().fetch())
    assert sorted(li.case_number for li in rows) == ["26-09991-eg", "26-09992-hb"]
    assert len(http.calls) == 3


def test_raw_block_survives_board_publication():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "bankruptcy_relief_from_stay" in RAW_KEEP
