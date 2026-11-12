"""funeral_home_rss: 2026-10-04 final-batch extraction-completeness audit.

Two confirmed live findings (see the module's own docstring for the full
investigation): (1) 2 of 11 real hosts (sullivanking.com,
dial-murrayfuneralhome.com) now sit behind a Cloudflare JS challenge that
blocks plain httpx but not a real Chrome TLS fingerprint -- fixed by routing
through ``get_text(..., impersonate=True)``; (2) every Frazer-kind feed (9 of
11 hosts) carries an ``obits:`` RSS-namespace extension (birth/death dates,
the decedent's own city/state, funeral-home name) that was never read at all.

``CECILMBURTON`` below is a real, live-captured item (2026-10-04,
cecilmburtonfuneralhome.com/feed) -- the full obits: namespace as feedparser
actually exposes it, trimmed to one item.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.public_notices import funeral_home_rss as M

CECILMBURTON = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0"><channel><title>Obituaries</title><link>https://www.cecilmburtonfuneralhome.com/</link><item><title>Holly E. Sampleman | 07&#x2f;03&#x2f;2026</title><description>View The Obituary For Holly E. Sampleman. Please join us in Loving, Sharing and Memorializing Holly E. Sampleman on this permanent online memorial presented by CECIL M. BURTON FUNERAL HOME &#x26; CREMATORY.</description><link>https://www.cecilmburtonfuneralhome.com/obituary/holly-sampleman?fh_id=16118</link><pubDate>Fri, 03 Jul 2026 08:00:00 EDT</pubDate><obits:birthDate>01&#x2f;05&#x2f;1967</obits:birthDate><obits:deathDate>07&#x2f;03&#x2f;2026</obits:deathDate><obits:first>Holly</obits:first><obits:middle>E.</obits:middle><obits:last>Sampleman</obits:last><obits:fh_name>Cecil M. Burton Funeral Home and Crematory</obits:fh_name><obits:fh_city>Shelby</obits:fh_city><obits:fh_state>NC</obits:fh_state><obits:deceased_city>Shelby</obits:deceased_city><obits:deceased_state>NC</obits:deceased_state><obits:date_created>July 3, 2026, 12:00:00 AM EDT</obits:date_created></item></channel></rss>"""

# Real shape (2026-10-04, willoughbyfuneralhomes.com) where deceased_city
# genuinely differs from the funeral home's own fh_city -- the independently
# useful case this fix is meant to surface.
WILLOUGHBY_DIFFERENT_CITY = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0"><channel><title>Obituaries</title><link>https://www.willoughbyfuneralhomes.com/</link><item><title>Robin Evelyn Sample Mockford | 09&#x2f;19&#x2f;2026</title><description>View The Obituary For Robin Evelyn Sample Mockford.</description><link>https://www.hemby-willoughby.com/obituary/robin-sample-mockford?fh_id=13219</link><pubDate>Sat, 19 Sep 2026 08:00:00 EDT</pubDate><obits:birthDate>03&#x2f;06&#x2f;1950</obits:birthDate><obits:deathDate>09&#x2f;19&#x2f;2026</obits:deathDate><obits:fh_name>Hemby-Willoughby Mortuary, Inc.</obits:fh_name><obits:fh_city>Tarboro</obits:fh_city><obits:fh_state>NC</obits:fh_state><obits:deceased_city>Rocky Mount</obits:deceased_city><obits:deceased_state>NC</obits:deceased_state></item></channel></rss>"""

# A Frazer item with no birthDate at all (occasionally blank live, e.g.
# dukesharleyfuneralhome.com's own real feed) -- age must come back None, not
# a divide-by-zero / garbage value.
NO_BIRTHDATE = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0"><channel><title>Obituaries</title><link>https://www.x.com/</link><item><title>Gladys Diane Sample Exampleby | 09&#x2f;30&#x2f;2026</title><description>View.</description><link>https://www.x.com/obituary/gladys-exampleby</link><pubDate>Wed, 30 Sep 2026 08:00:00 EDT</pubDate><obits:birthDate></obits:birthDate><obits:deathDate>09&#x2f;30&#x2f;2026</obits:deathDate><obits:fh_name>X Funeral Home</obits:fh_name></item></channel></rss>"""


def test_obits_namespace_fields_parsed():
    entries = list(M._iter_entries(CECILMBURTON, "frazer"))
    assert len(entries) == 1
    name, link, pub, summary, title_date, extra = entries[0]
    assert name == "Holly E. Sampleman"
    assert extra["birth_date"] == "01/05/1967"
    assert extra["death_date"] == "07/03/2026"
    assert extra["age"] == 59  # exact: 1967-01-05 -> 2026-07-03
    assert extra["deceased_city"] == "Shelby"
    assert extra["deceased_state"] == "NC"
    assert extra["fh_name"] == "Cecil M. Burton Funeral Home and Crematory"


def test_deceased_city_can_differ_from_funeral_home_city():
    """The independently-useful real-world case: the decedent's own city is
    NOT always the funeral home's city."""
    entries = list(M._iter_entries(WILLOUGHBY_DIFFERENT_CITY, "frazer"))
    _name, _link, _pub, _summary, _td, extra = entries[0]
    assert extra["deceased_city"] == "Rocky Mount"
    # The HOMES map's own county assignment for this host is keyed off the
    # funeral home's county (Edgecombe, for Tarboro) -- documented as a known
    # approximation in the module docstring; this test only proves the richer
    # signal is now captured and available, not that county assignment uses it.


def test_age_computation_handles_birthday_not_yet_reached():
    assert M._age_from_dates("07/10/1960", "07/03/2026") == 65  # birthday 7 days away
    assert M._age_from_dates("06/01/1960", "07/03/2026") == 66  # birthday already passed


def test_age_from_dates_none_on_missing_or_bad_input():
    assert M._age_from_dates(None, "07/03/2026") is None
    assert M._age_from_dates("07/10/1960", None) is None
    assert M._age_from_dates("not-a-date", "07/03/2026") is None


def test_missing_birthdate_yields_no_age_but_keeps_death_date():
    entries = list(M._iter_entries(NO_BIRTHDATE, "frazer"))
    _name, _link, _pub, _summary, _td, extra = entries[0]
    assert "age" not in extra
    assert "birth_date" not in extra
    assert extra["death_date"] == "09/30/2026"
    assert extra["fh_name"] == "X Funeral Home"


def test_fetch_escalates_to_impersonate_on_a_blocked_host(monkeypatch):
    """The real finding: sullivanking.com / dial-murrayfuneralhome.com both
    403 plain httpx today (Cloudflare JS challenge) but a real Chrome TLS
    fingerprint gets through clean. get_text(..., impersonate=True) is the
    module's fetch call now -- this proves fetch() actually uses it (not just
    that the helper exists) by making the fake call record its kwargs."""
    calls = []

    async def fake_get_text(url, *, timeout=30.0, impersonate=False, **kw):
        calls.append({"url": url, "timeout": timeout, "impersonate": impersonate})
        return CECILMBURTON

    monkeypatch.setattr(M, "get_text", fake_get_text)
    monkeypatch.setattr(M, "HOMES", {
        "sullivanking.com": ("Anderson", "SC", "frazer"),
    })

    result = asyncio.run(M.FuneralHomeRss().fetch())
    result = list(result)
    assert len(calls) == 1
    assert calls[0]["impersonate"] is True
    assert len(result) == 1
    assert result[0].raw["obituary"]["age"] == 59


def test_a_fetch_failure_on_one_host_does_not_drop_the_others(monkeypatch):
    async def fake_get_text(url, *, timeout=30.0, impersonate=False, **kw):
        if "blocked" in url:
            raise RuntimeError("impersonate got 403 for " + url)
        return CECILMBURTON

    monkeypatch.setattr(M, "get_text", fake_get_text)
    monkeypatch.setattr(M, "HOMES", {
        "blocked.example.com": ("Union", "SC", "frazer"),
        "cecilmburtonfuneralhome.com": ("Cleveland", "NC", "frazer"),
    })

    result = list(asyncio.run(M.FuneralHomeRss().fetch()))
    assert len(result) == 1
    assert result[0].county == "Cleveland"


def test_precise_obits_age_overrides_the_free_text_regex_guess():
    """When BOTH the free-text regex and the obits: namespace could produce
    an age (shouldn't really co-occur on a real feed, but the merge order
    must still be deterministic), the namespace's exact value wins."""
    item_with_both = (
        '<?xml version="1.0"?><rss xmlns:obits="http://www.meaningfulfunerals.net/images/rss/obits.txt" version="2.0">'
        '<channel><title>T</title><link>https://x.com/</link>'
        '<item><title>Jane Doe | 01&#x2f;01&#x2f;2026</title>'
        '<description>Survived by many. 99 years old per the free text.</description>'
        '<link>https://x.com/obituary/jane-doe</link>'
        '<pubDate>Thu, 01 Jan 2026 08:00:00 EDT</pubDate>'
        '<obits:birthDate>01&#x2f;01&#x2f;1946</obits:birthDate>'
        '<obits:deathDate>01&#x2f;01&#x2f;2026</obits:deathDate>'
        '</item></channel></rss>'
    )
    entries = list(M._iter_entries(item_with_both, "frazer"))
    _name, _link, _pub, summary, _td, extra = entries[0]
    assert extra["age"] == 80  # the exact namespace value, not the free-text "99"
    merged = {}
    merged.update(M._summary_fields(summary))
    merged.update(extra)
    assert merged["age"] == 80


def test_row_county_follows_the_decedents_own_city():
    """Audit 2026-10-09: the funeral home's county stood on rows whose feed said the decedent lived
    elsewhere. One NC/SC county for the city -> that county; a split town stays with the funeral
    home; another state stays too and is flagged."""
    ob = {"deceased_city": "Wilmington", "deceased_state": "NC"}
    assert M._residence_place(ob, "Edgecombe", "NC") == ("New Hanover", "NC")
    split = {"deceased_city": "Rocky Mount", "deceased_state": "NC"}
    assert M._residence_place(split, "Edgecombe", "NC") == ("Edgecombe", "NC")
    away = {"deceased_city": "Brooklyn", "deceased_state": "NY"}
    assert M._residence_place(away, "Buncombe", "NC") == ("Buncombe", "NC")
    assert away["residence_out_of_area"] is True
    assert M._residence_place({}, "Buncombe", "NC") == ("Buncombe", "NC")
