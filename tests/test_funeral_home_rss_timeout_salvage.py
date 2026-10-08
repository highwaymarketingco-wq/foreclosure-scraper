"""funeral_home_rss: one slow host must not throw away the rows every other host returned.

Source-completeness audit 2026-10-08: the VM logged 8 finished hosts and then
scraper.timeout at 124 s, three runs in a row, so the board got 0 rows although
the feeds were up. The old loop read the 11 hosts one after another and returned
its rows only at the end. These tests fail on that code: a hung host either
starves the hosts after it, or the soft timeout discards what was collected.

Fixtures are invented (made-up names in the real Frazer RSS shape).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_OK, OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.public_notices import funeral_home_rss as M


def _feed(host: str, name: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss xmlns:obits="http://www.meaningfulfunerals.net/'
        'images/rss/obits.txt" version="2.0"><channel><title>Recent Obituaries for Test Home</title>'
        f'<link>https://www.{host}/</link><item><title>{name} | 09&#x2f;30&#x2f;2026</title>'
        f'<description>View The Obituary For {name}.</description>'
        f'<link>https://www.{host}/obituary/{name.lower().replace(" ", "-")}?fh_id=1</link>'
        '<pubDate>Wed, 30 Sep 2026 08:00:00 EDT</pubDate>'
        '<obits:birthDate>01&#x2f;02&#x2f;1940</obits:birthDate>'
        '<obits:deathDate>09&#x2f;30&#x2f;2026</obits:deathDate></item></channel></rss>'
    )


FEEDS = {
    "fast-one.example.com": _feed("fast-one.example.com", "Testa Quill Placeholder"),
    "fast-two.example.com": _feed("fast-two.example.com", "Morrow Example Sample"),
}


def _install(monkeypatch, homes: dict) -> None:
    async def fake_get_text(url, *, timeout=30.0, impersonate=False, **kw):
        for host, body in FEEDS.items():
            if host in url:
                return body
        await asyncio.sleep(3600)          # the hung host: never answers
        raise AssertionError("unreachable")

    monkeypatch.setattr(M, "get_text", fake_get_text)
    monkeypatch.setattr(M, "HOMES", homes)


def test_a_hung_first_host_does_not_starve_the_hosts_after_it(monkeypatch):
    _install(monkeypatch, {
        "hung.example.com": ("Union", "SC", "frazer"),
        "fast-one.example.com": ("Cleveland", "NC", "frazer"),
        "fast-two.example.com": ("Anderson", "SC", "frazer"),
    })
    s = M.FuneralHomeRss()
    s.timeout_s = 2.0
    s.host_deadline_s = 0.3
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == OUTCOME_OK
    assert sorted(li.county for li in rows) == ["Anderson", "Cleveland"]
    assert {li.raw["obituary"]["age"] for li in rows} == {86}


def test_a_soft_timeout_ships_the_hosts_that_already_finished(monkeypatch):
    _install(monkeypatch, {
        "fast-one.example.com": ("Cleveland", "NC", "frazer"),
        "fast-two.example.com": ("Anderson", "SC", "frazer"),
        "hung.example.com": ("Union", "SC", "frazer"),
    })
    s = M.FuneralHomeRss()
    s.timeout_s = 0.5
    s.host_deadline_s = 60.0               # the run's own timeout fires first
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == OUTCOME_PARTIAL
    assert sorted(li.county for li in rows) == ["Anderson", "Cleveland"]
