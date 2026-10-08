"""obituary_feeds / echovita_obituaries / _obit_common on hand-written fixtures (made-up names,
markup modelled on the live pages checked 2026-10-07). No network: the fetcher is replaced."""
from __future__ import annotations

import asyncio
import json

import pytest

from foreclosure_scraper.quiet_title.fetch import Walled
from foreclosure_scraper.scrapers.public_notices import echovita_obituaries as ev
from foreclosure_scraper.scrapers.public_notices import obituary_feeds as of
from foreclosure_scraper.scrapers.public_notices._obit_common import (
    decedent_from_title,
    obituary_listing,
    wall_reason,
)

WP_FEED = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>Obituaries</title>
<item><title>Obituary: Velma Juno Crisp, 87</title><link>https://www.example-paper.test/2026/10/01/velma-crisp/</link>
<pubDate>Thu, 01 Oct 2026 10:00:00 +0000</pubDate><description>Velma Juno Crisp, 87, of Tryon...</description>
<content:encoded><![CDATA[<p>Velma Juno Crisp, 87, of Tryon, passed away on September 29, 2026.</p>
<p>She is survived by her son, Walt Crisp of Columbus; a daughter, Ione Crisp Barlow and husband Ned;
and five grandchildren.</p><p>A graveside service will be held Saturday.</p>]]></content:encoded></item>
<item><title>Board of Commissioners meets Tuesday</title><link>https://www.example-paper.test/news/1</link>
<content:encoded><![CDATA[<p>Agenda.</p>]]></content:encoded></item>
<item><title>Ansel Pike</title><link>https://www.example-paper.test/2026/10/02/ansel-pike/</link>
<description>Ansel Pike of Saluda died Sunday.</description></item>
</channel></rss>"""

ARTICLE = """<html><body><aside class="sidebar"><h3>Recent obituaries</h3><p>Is survived by Zed Q. Nobody</p></aside>
<article><div class="entry-content"><p>Ansel Pike, 70, of Saluda, died September 27, 2026.</p>
<p>He is survived by his wife, Opal Pike; and a brother, Rafe Pike.</p></div>
<div class="sharedaddy">Share this</div></article><footer>Footer names Zed Q. Nobody</footer></body></html>"""

LISTING = """<div class="obit-list-wrapper">
<a class="text-name-obit-in-list text-color-default" href="/us/obituaries/nc/weaverville/orvel-tandry-111" title="Read the obituary of Orvel Quimby Tandry">Orvel Quimby Tandry</a>
<p class="text-info-obit-in-list"><a class="text-primary" title="Obituaries - Weaverville, North Carolina" href="/us/obituaries/nc/weaverville">Weaverville</a></p>
<p class="text-info-obit-in-list"><span class="my-auto">March 2, 1942 - September 28, 2026</span><span class=" ml-1">(84 years old)</span></p></div>
<div class="obit-list-wrapper">
<a class="text-name-obit-in-list text-color-default" href="/us/obituaries/nc/roxboro/bonnie-wil-222" title="Read the obituary of Bonnie Wil">Bonnie Wil</a>
<p class="text-info-obit-in-list"><a class="text-primary" title="Obituaries - Roxboro, North Carolina" href="/us/obituaries/nc/roxboro">Roxboro</a></p>
<p class="text-info-obit-in-list"><span class="my-auto">2026</span></p></div>"""

OBIT_PAGE = """<html><head><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebPage","mainEntity":
{"@type":"Person","name":"Orvel Quimby Tandry","birthDate":"1942-03-02","deathDate":"2026-09-28",
"address":{"@type":"PostalAddress","addressLocality":"Weaverville","addressRegion":"NC"}}}</script></head>
<body><div id="obituary" class="ObituaryDescText"><h1>Orvel Quimby Tandry</h1><p>He is survived by his wife of 61
years, Lunetta Brask Tandry; two sons, Corwin Tandry and Bratt Tandry.</p></div>
<div class="condolences">Sympathy from Zed Nobody</div></body></html>"""


class FakeFetcher:
    def __init__(self, pages: dict, walled: dict | None = None):
        self.pages = pages
        self.walled_map = walled or {}
        self.walled: dict = {}
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get(self, url, params=None, content_rx=None):
        self.calls.append(url)
        for k, why in self.walled_map.items():
            if k in url:
                self.walled[k] = why
                raise Walled(url, why)
        if url in self.pages:
            return self.pages[url]
        for k, v in self.pages.items():
            if url.startswith(k + "?"):
                return v
        raise RuntimeError(f"no fixture for {url}")


def test_wall_reason():
    assert wall_reason(200, "https://x.test/", OBIT_PAGE) is None
    assert wall_reason(200, "https://x.test/", "<title>Just a moment...</title><div class='cf-chl'>") == "challenge page"
    assert wall_reason(429, "https://x.test/", "Too many") == "HTTP 429"
    assert wall_reason(402, "https://x.test/", "Access Restricted") == "HTTP 402"


def test_captcha_in_a_share_form_on_a_served_page_is_not_a_gate():
    served = OBIT_PAGE.replace("</body>", '<form id="share-obituary-form"><div class="g-recaptcha" '
                                            'data-sitekey="x"></div></form></body>')
    assert wall_reason(200, "https://x.test/", served) == "CAPTCHA"            # no content check: a wall
    assert wall_reason(200, "https://x.test/", served, ev.CONTENT_RX) is None  # content is on the page
    gate = ('<html><body><form id="gate"><div class="g-recaptcha"></div></form>'
            '<div id="obituary"></div></body></html>')
    assert wall_reason(200, "https://x.test/", gate, ev.CONTENT_RX) == "CAPTCHA"  # nothing served: a wall
    assert wall_reason(403, "https://x.test/", served, ev.CONTENT_RX) == "HTTP 403"


def test_decedent_from_title():
    assert decedent_from_title("Obituary: Velma Juno Crisp, 87") == "Velma Juno Crisp"
    assert decedent_from_title("Orvel Tandry | 09/28/2026") == "Orvel Tandry"
    assert decedent_from_title("Ansel Pike (1956 - 2026)") == "Ansel Pike"
    assert decedent_from_title("Board of Commissioners meets Tuesday") is None
    assert decedent_from_title("2026 obituaries") is None


def test_listing_shape_keeps_names_private():
    li = obituary_listing(source="public_notices.obituary_feeds", url="https://p.test/o/1", decedent="Ansel Pike",
                          state="NC", county="Polk", publisher="Test Paper",
                          text="He is survived by his wife, Opal Pike; and a brother, Rafe Pike.")
    pub = li.raw["obituary"]
    assert pub["survivor_names_parsed"] == 2 and pub["has_survivor_list"] is True
    assert "Opal" not in json.dumps(pub) and "Rafe" not in json.dumps(pub)
    assert [s["name"] for s in li.raw["obituary_private"]["survivors"]] == ["Opal Pike", "Rafe Pike"]
    from foreclosure_scraper.web_artifact import _slim_raw
    assert "obituary_private" not in _slim_raw(li.raw)
    assert "Opal" not in json.dumps(_slim_raw(li.raw))


def test_article_text_skips_sidebars_and_footer():
    body = of.article_text(ARTICLE)
    assert "Opal Pike" in body and "Nobody" not in body


def test_obituary_feeds_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))
    monkeypatch.setattr(of, "FEEDS", (of.Feed("example-paper.test", "https://www.example-paper.test/feed/", "Polk",
                                              "NC", "wp", "Test Paper", True),
                                      of.Feed("walled.test", "https://walled.test/feed/", "Avery", "NC",
                                              "townnews", "Walled Paper", False)))
    fake = FakeFetcher({"https://www.example-paper.test/feed/": WP_FEED,
                        "https://www.example-paper.test/2026/10/02/ansel-pike/": ARTICLE},
                       walled={"walled.test": "HTTP 429"})
    monkeypatch.setattr(of, "PoliteFetcher", lambda: fake)
    s = of.ObituaryFeeds()
    rows = asyncio.run(s.fetch())
    names = sorted(r.owner_name for r in rows)
    assert names == ["Ansel Pike", "Velma Juno Crisp"]
    velma = next(r for r in rows if r.owner_name == "Velma Juno Crisp")
    assert [p["name"] for p in velma.raw["obituary_private"]["survivors"]] == ["Walt Crisp", "Ione Crisp Barlow", "Ned"]
    assert velma.county == "Polk" and velma.raw["obituary"]["death_date"] == "September 29, 2026"
    ansel = next(r for r in rows if r.owner_name == "Ansel Pike")
    # the feed had no survivor text, so the article page was read; the sidebar was not
    assert [p["name"] for p in ansel.raw["obituary_private"]["survivors"]] == ["Opal Pike", "Rafe Pike"]
    assert s.last_stats["walled.test"]["walled"] == "HTTP 429"
    # 'Ned' came from 'and husband Ned': an in-law, which enrichment_heir_candidates leaves out
    assert velma.raw["obituary_private"]["survivors"][2]["relation"] == "in_law"


def test_echovita_parsers():
    cards = ev.parse_listing(LISTING)
    assert [(c["name"], c["city"], c["age"]) for c in cards] == [("Orvel Quimby Tandry", "Weaverville", 84),
                                                                  ("Bonnie Wil", "Roxboro", None)]
    page = ev.parse_obituary_page(OBIT_PAGE)
    assert page["death_date"] == "2026-09-28" and page["city"] == "Weaverville"
    assert "Lunetta" in page["text"] and "Zed" not in page["text"]


def test_echovita_end_to_end_core_first_and_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))
    monkeypatch.setattr(ev, "MAX_PAGES", 1)
    monkeypatch.setattr(ev, "MAX_DETAIL", 1)
    fake = FakeFetcher({"https://www.echovita.com/us/obituaries/nc": LISTING,
                        "https://www.echovita.com/us/obituaries/sc": "<html></html>",
                        "https://www.echovita.com/us/obituaries/nc/weaverville/orvel-tandry-111": OBIT_PAGE})
    monkeypatch.setattr(ev, "PoliteFetcher", lambda: fake)
    s = ev.EchovitaObituaries()
    rows = asyncio.run(s.fetch())
    assert len(rows) == 2
    orvel = next(r for r in rows if r.owner_name == "Orvel Quimby Tandry")
    assert orvel.county == "Buncombe"                               # Weaverville -> Buncombe
    assert orvel.raw["obituary"]["survivor_names_parsed"] == 3
    assert orvel.raw["obituary"]["death_date"] == "2026-09-28"
    # the cap of 1 went to the footprint county (Buncombe) before Roxboro (Person, not in the footprint)
    assert not any("roxboro/" in u for u in fake.calls)
    assert s.last_stats["detail"] == 1


def test_echovita_stops_on_a_wall(monkeypatch, tmp_path):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))
    fake = FakeFetcher({}, walled={"echovita.com": "challenge page"})
    monkeypatch.setattr(ev, "PoliteFetcher", lambda: fake)
    s = ev.EchovitaObituaries()
    assert asyncio.run(s.fetch()) == []
    assert s.last_stats["walled"] == "challenge page" and len(fake.calls) == 1



def test_feed_title_town_suffix_and_cross_state_residence():
    """Audit 2026-10-09: 'Name-Town' titles (Edgefield) kept the town in the decedent's name, and a
    residence across the state line kept the paper's county. Made-up names."""
    from foreclosure_scraper.scrapers.public_notices import obituary_feeds as OF
    assert OF.strip_town_suffix("Jane Q Sample-Edgefield", "SC") == "Jane Q Sample"
    assert OF.strip_town_suffix("Mary Sample-Exampleton", "SC") == "Mary Sample-Exampleton"
    assert OF.strip_town_suffix(None, "SC") is None
    feed = OF.Feed("x.example", "https://x.example/feed", "Polk", "NC", "wp", "X", False)
    assert OF._place_for(feed, "Landrum") == ("Spartanburg", "SC")
    assert OF._place_for(feed, None) == ("Polk", "NC")
