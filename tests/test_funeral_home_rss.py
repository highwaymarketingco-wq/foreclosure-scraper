"""funeral_home_rss: host-map coverage sweep, round 2 (2026-09-27).

docs/coverage_gap_build_plan_2026-09-23.md #2.4 named probate/estate as the
3rd-most commonly-missing distress family (present in only 38 of 146 NC+SC
counties) and named this module's host map -- 3 entries at the time -- as
one of only two ways the codebase gets it at all. This file locks in the 7
hosts a live probe sweep confirmed and added to HOMES that same day, each
fixture below trimmed from that host's own ``HOST/feed`` response as
actually fetched on 2026-09-27 (channel + one real <item>, matching the
MEASURED convention other tests in this file use elsewhere in the repo).

Every fixture host was found via a "meaningfulfunerals.net <county>" web
search (that domain is the underlying Frazer/CFML backend most Frazer
clients proxy at their own HOST/feed) and then verified live -- not just a
200 status, but a parseable RSS channel titled "Recent Obituaries for
<home>" with real, current decedent names/dates, per the module's own kind
="frazer" shape. ~90 other candidates probed the same day across ~48 gap
counties came up empty (wrong CMS entirely -- Duda, Cloudflare-walled,
ASP.NET homegrown -- returning HTTP 200/403/404 with no RSS at either probe
URL shape); those misses are recorded in the module docstring, not here.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.public_notices.funeral_home_rss import (
    HOMES,
    _date_from_title,
    _iter_entries,
    _name_from_title,
)

# --- real trimmed captures, one <item> each, 2026-09-27 -------------------

LAMBFH = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0"><channel><title>Recent Obituaries for Lamb Funeral Home</title><link>https://www.lambfh.com/</link><item><title>Avery Darnell Testman | 08&#x2f;08&#x2f;2026</title><description>View The Obituary For Avery Darnell Testman. Please join us in Loving, Sharing and Memorializing Avery Darnell Testman on this permanent online memorial presented by Lamb Funeral Home.</description><link>https://www.lambfh.com/obituary/avery-testman?fh_id=12531</link><pubDate>Sat, 08 Aug 2026 08:00:00 EDT</pubDate><obits:fh_name>Lamb Funeral Home, Inc.</obits:fh_name><obits:fh_city>Concord</obits:fh_city><obits:fh_state>NC</obits:fh_state></item></channel></rss>"""

EDWARDSCARES = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0"><channel><title>Recent Obituaries for Edwards Funeral Home</title><link>https://www.edwardscares.com/</link><item><title>Grace Louise Sampleby | 09&#x2f;16&#x2f;2026</title><description>View The Obituary For Grace Louise Sampleby. Please join us in Loving, Sharing and Memorializing Grace Louise Sampleby on this permanent online memorial presented by Edwards Funeral Home.</description><link>https://www.edwardscares.com/obituary/grace-sampleby?fh_id=12413</link><pubDate>Wed, 16 Sep 2026 08:00:00 EDT</pubDate><obits:fh_name>Josephine F. Edwards, Inc. dba Edwards Funeral Home</obits:fh_name><obits:fh_city>Wilson</obits:fh_city><obits:fh_state>NC</obits:fh_state><obits:deceased_city>Wilson</obits:deceased_city><obits:deceased_state>NC</obits:deceased_state></item></channel></rss>"""

DUKESHARLEY = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0"><channel><title>Recent Obituaries for Dukes-Harley Funeral Home and Crematory</title><link>https://www.dukesharleyfuneralhome.com/</link><item><title>Robert E. Exampleton | 09&#x2f;21&#x2f;2026</title><description>View The Obituary For Robert E. Exampleton. Please join us in Loving, Sharing and Memorializing Robert E. Exampleton on this permanent online memorial presented by Dukes-Harley Funeral Home and Crematory.</description><link>https://www.dukesharleyfuneralhome.com/obituary/robert-e-exampleton?fh_id=12290</link><pubDate>Mon, 21 Sep 2026 08:00:00 EDT</pubDate><obits:fh_name>Dukes-Harley Funeral Home and Crematory</obits:fh_name><obits:fh_city>Orangeburg</obits:fh_city><obits:fh_state>SC</obits:fh_state><obits:deceased_city>Neeses</obits:deceased_city><obits:deceased_state>SC</obits:deceased_state></item></channel></rss>"""

NESMITHPINCKNEY = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0"><channel><title>Recent Obituaries for Nesmith- Pinckney Funeral Home Inc</title><link>https://www.nesmithpinckneyfuneralhome.com/</link><item><title>Mack W Placeholder Jr. | 09&#x2f;20&#x2f;2026</title><description>View The Obituary For Mack W Placeholder Jr.. Please join us in Loving, Sharing and Memorializing Mack W Placeholder Jr. on this permanent online memorial presented by Nesmith- Pinckney Funeral Home Inc.</description><link>https://www.nesmithpinckneyfuneralhome.com/obituary/mack-placeholder-jr?fh_id=13644</link><pubDate>Sun, 20 Sep 2026 08:00:00 EDT</pubDate><obits:fh_name>NESMITH-PINCKNEY FUNERAL HOME</obits:fh_name><obits:fh_city>Hemingway</obits:fh_city><obits:fh_state>SC</obits:fh_state><obits:deceased_city>McClellanville</obits:deceased_city><obits:deceased_state>SC</obits:deceased_state></item></channel></rss>"""

WILLOUGHBY = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0"><channel><title>Recent Obituaries for Willoughby Funeral Homes</title><link>https://www.willoughbyfuneralhomes.com/</link><item><title>Robin Evelyn Sample Mockford | 09&#x2f;19&#x2f;2026</title><description>View The Obituary For Robin Evelyn Sample Mockford. Please join us in Loving, Sharing and Memorializing Robin Evelyn Sample Mockford on this permanent online memorial presented by Willoughby Funeral Homes.</description><link>https://www.hemby-willoughby.com/obituary/robin-sample-mockford?fh_id=13219</link><pubDate>Sat, 19 Sep 2026 08:00:00 EDT</pubDate><obits:fh_name>Hemby-Willoughby Mortuary, Inc.</obits:fh_name><obits:fh_city>Tarboro</obits:fh_city><obits:fh_state>NC</obits:fh_state><obits:deceased_city>Rocky Mount</obits:deceased_city><obits:deceased_state>NC</obits:deceased_state></item></channel></rss>"""

CASEYFH = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0"><channel><title>Recent Obituaries for Casey Funeral Home and Cremations</title><link>https://www.caseyfh.com/</link><item><title>Kenneth Andale Fixture | 08&#x2f;08&#x2f;2026</title><description>View The Obituary For Kenneth Andale Fixture. Please join us in Loving, Sharing and Memorializing Kenneth Andale Fixture on this permanent online memorial presented by Casey Funeral Home and Cremations.</description><link>https://www.caseyfh.com/obituary/kenneth-fixture?fh_id=14262</link><pubDate>Sat, 08 Aug 2026 08:00:00 EDT</pubDate><obits:fh_name>Casey Funeral Home and Cremations</obits:fh_name><obits:fh_city>Princeton</obits:fh_city><obits:fh_state>NC</obits:fh_state></item></channel></rss>"""

# dychesfuneralhome.com is the one host of the 7 that is NOT a Frazer backend:
# it's a plain WordPress site whose default ``/feed`` happens to be entirely
# posts in an "Obituaries" category, bare-name titles (no " | MM/DD/YYYY"
# suffix). content:encoded is trimmed to one real sentence here (the live
# item runs to a full multi-paragraph obituary naming the decedent's
# surviving family; that level of personal detail isn't needed to test
# parsing and isn't reproduced in full here).
DYCHES = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
\txmlns:content="http://purl.org/rss/1.0/modules/content/"
\txmlns:dc="http://purl.org/dc/elements/1.1/"
\t>
<channel>
\t<title>Funeral Home and Crematory in Barnwell SC</title>
\t<link>https://dychesfuneralhome.com</link>
\t<item>
\t\t<title>Sean Arlen Testwell</title>
\t\t<link>https://dychesfuneralhome.com/sean-arlen-testwell/</link>
\t\t<dc:creator><![CDATA[316458pwpadmin]]></dc:creator>
\t\t<pubDate>Wed, 23 Sep 2026 19:30:56 +0000</pubDate>
\t\t<category><![CDATA[Obituaries]]></category>
\t\t<guid isPermaLink="false">https://dychesfuneralhome.com/?p=1145</guid>
\t\t<description><![CDATA[Sean Arlen Testwell ,25 of Aiken passed away on September 17, 2026. A Celebration of Life will be held at 11 AM on Saturday, Sept 26, at First Baptist [&#8230;]]]></description>
\t\t<content:encoded><![CDATA[<p><strong>Sean Arlen Testwell ,25 of Aiken passed away on September 17, 2026.</strong></p>]]></content:encoded>
\t</item>
</channel>
</rss>"""


def _names(xml, kind):
    return [(n, l, p) for n, l, p, _summary, _td, _extra in _iter_entries(xml, kind)]


def test_lambfh_cabarrus_nc():
    (name, link, pub) = _names(LAMBFH, "frazer")[0]
    assert name == "Avery Darnell Testman"
    assert link == "https://www.lambfh.com/obituary/avery-testman?fh_id=12531"
    assert "2026" in pub
    assert HOMES["lambfh.com"] == ("Cabarrus", "NC", "frazer")


def test_edwardscares_wilson_nc():
    (name, link, _pub) = _names(EDWARDSCARES, "frazer")[0]
    assert name == "Grace Louise Sampleby"
    assert "edwardscares.com" in link
    assert HOMES["edwardscares.com"] == ("Wilson", "NC", "frazer")


def test_dukesharley_orangeburg_sc():
    (name, link, _pub) = _names(DUKESHARLEY, "frazer")[0]
    assert name == "Robert E. Exampleton"
    assert "dukesharleyfuneralhome.com" in link
    assert HOMES["dukesharleyfuneralhome.com"] == ("Orangeburg", "SC", "frazer")


def test_nesmithpinckney_williamsburg_sc():
    (name, link, _pub) = _names(NESMITHPINCKNEY, "frazer")[0]
    # trailing "Jr." on the title has its own '.', separate from the " | date"
    # split -- must not be swallowed by _name_from_title's pipe split.
    assert name == "Mack W Placeholder Jr."
    assert "nesmithpinckneyfuneralhome.com" in link
    assert HOMES["nesmithpinckneyfuneralhome.com"] == ("Williamsburg", "SC", "frazer")


def test_willoughby_edgecombe_nc():
    (name, link, _pub) = _names(WILLOUGHBY, "frazer")[0]
    assert name == "Robin Evelyn Sample Mockford"
    # this home's own obituary detail pages live on a sister domain
    # (hemby-willoughby.com) even though the feed itself is served from
    # willoughbyfuneralhomes.com -- real, not a bug in the fixture.
    assert link == "https://www.hemby-willoughby.com/obituary/robin-sample-mockford?fh_id=13219"
    assert HOMES["willoughbyfuneralhomes.com"] == ("Edgecombe", "NC", "frazer")


def test_caseyfh_johnston_nc_not_wayne():
    # Casey Funeral Home markets itself around Goldsboro (Wayne Co.), but its
    # own obits:fh_city is Princeton, which sits in Johnston County -- the
    # host map must carry the funeral home's actual county, not the nearest
    # big city it advertises serving.
    (name, link, _pub) = _names(CASEYFH, "frazer")[0]
    assert name == "Kenneth Andale Fixture"
    assert "caseyfh.com" in link
    assert HOMES["caseyfh.com"] == ("Johnston", "NC", "frazer")


def test_dyches_barnwell_sc_wordpress_obituaries_category():
    # kind="frazer" is a no-op pass-through here (no " | date" in the title
    # to split on), which is exactly why this off-label host still parses
    # correctly under the existing "frazer" kind.
    entries = list(_iter_entries(DYCHES, "frazer"))
    name, link, pub, summary, title_date, extra = entries[0]
    assert name == "Sean Arlen Testwell"
    assert link == "https://dychesfuneralhome.com/sean-arlen-testwell/"
    assert "2026" in pub
    assert title_date is None  # no pipe-delimited date suffix on this CMS
    assert "Aiken" in summary
    assert extra == {}  # plain WordPress has no obits: namespace at all
    assert HOMES["dychesfuneralhome.com"] == ("Barnwell", "SC", "frazer")


def test_name_from_title_handles_trailing_period_suffix():
    # regression guard for the Mack Placeholder Jr. case above: a trailing
    # "Jr."/"Sr." period must survive _name_from_title, only the " | date"
    # half should be dropped.
    assert (
        _name_from_title("Mack W Placeholder Jr. | 09/20/2026", "frazer")
        == "Mack W Placeholder Jr."
    )


def test_date_from_title_extracts_frazer_pipe_date():
    assert _date_from_title("Avery Darnell Testman | 08/08/2026") == "08/08/2026"


def test_round2_hosts_all_carry_nc_or_sc():
    round2 = {
        "lambfh.com", "edwardscares.com", "willoughbyfuneralhomes.com",
        "caseyfh.com", "dukesharleyfuneralhome.com",
        "nesmithpinckneyfuneralhome.com", "dychesfuneralhome.com",
    }
    assert round2 <= HOMES.keys()
    for host in round2:
        county, state, kind = HOMES[host]
        assert state in ("NC", "SC")
        assert county
        assert kind in ("frazer", "ltobits")


def test_registry_still_auto_discovers_it():
    from foreclosure_scraper.scrapers._registry import discover
    from foreclosure_scraper.scrapers.public_notices.funeral_home_rss import (
        FuneralHomeRss,
    )
    assert any(c is FuneralHomeRss for c in discover())
