"""The Columbia Star Master's Sales (Richland MIE) - hand-written feed and notices.

Notice wording follows the forms printed in the live feed on 2026-10-07 ("C/A No.",
"Civil Action No.", bare docket after the heading, "vs." / "against", two address
labels, TMS variants); every party, street and number is made up.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.newspapers import columbia_star as mod

N1 = ("MASTER’S SALE C/A No. 2026CP4099001 BY VIRTUE of a decree heretofore granted in the case of: "
      "Sample Mortgage Servicing, LLC vs. Alexandra Q. Testperson; Robert Testperson; C/A No.2026CP4099001 "
      "I, the undersigned Master for Richland County, will sell on November 2, 2026, at 12:00 Noon, "
      "2500 Decker Boulevard, Columbia, SC 29206; to the highest bidder: All that certain piece, parcel "
      "or lot of land ... Property Address: 123 Example Meadow Dr Derivation: Book R9999 at Page 123 "
      "TMS/PIN# R99999-01-02 TERMS OF SALE: The successful bidder ... no personal or deficiency "
      "judgment being demanded, the bidding will not remain open after the date of sale.")
N2 = ("MASTER’S SALE Civil Action No. 2025-CP-40- 09002 BY VIRTUE of a decree heretofore granted in "
      "Civil Action No. 2025-CP-40-09002 in the case of: Fiction Bank, N.A. against Lee Placeholder, the "
      "undersigned Master in Equity for Richland County, South Carolina, will sell on Monday, "
      "November 2, 2026 at 12:00 PM ... ADDRESS OF PROPERTY: 45 Pretend Ct, Columbia, SC 29209 "
      "TMS: 19999-03-04 TERMS OF SALE: ... deficiency judgment being expressly waived by the Plaintiff.")
N3 = "MASTER’S SALE without any docket number at all, will sell on November 2, 2026."
CONTENT = "<p>" + "</p><p>".join((N1, N2, N3, "Master’s Sales continued on Classified page.")) + "</p>"

FEED = f"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Public Notices</title>
<item><title>Master’s Sales</title><link>https://www.thecolumbiastar.com/articles/masters-sales-999/</link>
<pubDate>Thu, 01 Oct 2026 14:00:00 +0000</pubDate><content:encoded><![CDATA[{CONTENT}]]></content:encoded></item>
<item><title>Storage Auctions</title><link>https://www.thecolumbiastar.com/articles/storage-auctions-999/</link>
<pubDate>Thu, 01 Oct 2026 14:00:00 +0000</pubDate><content:encoded><![CDATA[<p>Unit 12 contents</p>]]></content:encoded></item>
</channel></rss>"""

NOW = mod.datetime(2026, 10, 7)


def test_notice_split_and_field_parse():
    texts = mod.notice_texts(CONTENT)
    assert len(texts) == 4
    r1 = mod.parse_notice(texts[0])
    assert r1["case_number"] == "2026CP4099001" and r1["county"] == "Richland"
    assert r1["plaintiff"] == "Sample Mortgage Servicing, LLC"
    assert r1["owner"] == "Alexandra Q. Testperson"
    assert r1["sale_date"].date().isoformat() == "2026-11-02"
    assert r1["street"] == "123 Example Meadow Dr" and r1["tms"] == "R99999-01-02"
    assert r1["deficiency"] == "demanded"
    r2 = mod.parse_notice(texts[1])
    assert r2["case_number"] == "2025CP4009002" and r2["owner"] == "Lee Placeholder"
    assert (r2["street"], r2["city"], r2["zip"]) == ("45 Pretend Ct", "Columbia", "29209")
    assert r2["tms"] == "19999-03-04" and r2["deficiency"] == "waived"
    assert r2["sale_date"].date().isoformat() == "2026-11-02"
    assert mod.parse_notice(texts[2]) is None and mod.parse_notice(texts[3]) is None


def test_listing_is_remapped_to_lis_pendens_outside_the_flip_footprint_and_survives():
    text = mod.notice_texts(CONTENT)[0]
    li = mod.build_listing(mod.parse_notice(text), article_url="https://x/a/", published=None, text=text, now=NOW)
    assert li.listing_type == ListingType.LIS_PENDENS        # Richland is not a flip county
    assert li.foreclosure_process == "judicial" and li.parcel_id == "R99999-01-02"
    assert li.owner_name == li.defendant == "Alexandra Q. Testperson"
    assert li.raw["public_notice"]["kind"] == "mie_sale"
    assert main._in_scope(li)
    assert main._active_only(li, 120, now=mod.datetime(2026, 10, 7))


def test_feed_only_reads_masters_sales_items():
    items = mod.parse_feed(FEED)
    assert [mod.is_masters_sales(i["title"]) for i in items] == [True, False]
    assert items[0]["published"].date().isoformat() == "2026-10-01"


class _Resp:
    def __init__(self, text, status_code=200):
        self.text, self.status_code = text, status_code


class _Http:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def get(self, url, **kw):
        self.calls.append(url)
        return self.pages.get(url, _Resp("", 404))


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_fetch_reads_feed_pages_and_dedupes_cases(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    monkeypatch.setattr(mod, "_PAUSE_S", 0)
    monkeypatch.setattr(mod, "MAX_FEED_PAGES", 2)
    http = _Http({mod.FEED: _Resp(FEED), f"{mod.FEED}?paged=2": _Resp(FEED)})
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.ColumbiaStarMastersSales().fetch())
    assert sorted(li.case_number for li in rows) == ["2025CP4009002", "2026CP4099001"]
    assert len(http.calls) == 2
