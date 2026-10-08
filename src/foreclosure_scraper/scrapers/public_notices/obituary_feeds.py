"""Open newspaper and funeral-home obituary feeds (Western NC + Upstate SC first) with survivors.

WHY. funeral_home_rss.py and gannett_obituaries.py give a decedent's NAME (and sometimes age); the
attorney also needs the people the obituary names as survivors, which only the full obituary text
carries. These feeds were verified live on 2026-10-07 with an ordinary request (no impersonation,
no cookies, >= 1.6 s between requests to one host) and either carry the full text in the feed
(WordPress <content:encoded>) or link to an open article page that does.

  host                              county         kind      what the feed gives
  tryondailybulletin.com            Polk NC        wp        full text in the feed
  laurenscountyadvertiser.net       Laurens SC     wp        full text in the feed
  edgefieldadvertiser.com           Edgefield SC   wp        excerpt; article page has the text
  grocefuneralhome.com              Buncombe NC    ltobits   excerpt; obituary page has the text
  wataugademocrat.com               Watauga NC     townnews  name + date only (article pages 403)
  averyjournal.com                  Avery NC       townnews  name + date only (article pages 403)

Checked and left out (live run 2026-10-07): yourpickenscounty.com (Pickens SC) posts one weekly
round-up ('Obituaries 10-7-26') holding several obituaries, which needs a per-obituary splitter
this reader does not have; salisburypost.com's obituary category carries news headlines, not
obituaries; bladenjournal.com's items have empty or surname-only titles.

The county a row carries is the decedent's own residence county when the obituary prints a town
the city tables know, else the paper's / funeral home's county. Walled hosts (TownNews papers that
answer 429 to a first request, Cloudflare-challenged funeral homes, paywalled 402 papers) are not
here: see docs/new_sources_2026-10-07_heirs_obits.md.

Each item -> one PROBATE_NOTICE row (decedent as owner, raw['obituary'] public, survivors in
raw['obituary_private'] which never publishes; see _obit_common.py). Article pages are fetched only
when the feed lacks the text, capped per host per run (OBIT_FEEDS_DETAIL_MAX, default 25), and an
obituary already in the private store with its survivors is not fetched again.

Gate off with FORECLOSURE_OBIT_FEEDS=0.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, NamedTuple, Optional

import structlog

from ...base_scraper import BaseScraper
from ...quiet_title.fetch import Walled
from ._obit_common import PoliteFetcher, decedent_from_title, looks_like_obituary, obituary_listing

try:
    import feedparser  # type: ignore
except Exception:  # noqa: BLE001
    feedparser = None  # type: ignore

log = structlog.get_logger()


class Feed(NamedTuple):
    host: str
    url: str
    county: str
    state: str
    kind: str          # wp | ltobits | townnews
    publisher: str
    detail: bool       # fetch the article page when the feed lacks the text


FEEDS: tuple[Feed, ...] = (
    Feed("tryondailybulletin.com", "https://www.tryondailybulletin.com/category/obituaries/feed/",
         "Polk", "NC", "wp", "Tryon Daily Bulletin", True),
    Feed("laurenscountyadvertiser.net", "https://www.laurenscountyadvertiser.net/category/obituaries/feed/",
         "Laurens", "SC", "wp", "The Laurens County Advertiser", True),
    Feed("edgefieldadvertiser.com", "https://www.edgefieldadvertiser.com/category/obituaries/feed/",
         "Edgefield", "SC", "wp", "The Edgefield Advertiser", True),
    Feed("grocefuneralhome.com", "https://www.grocefuneralhome.com/?feed=rss2&post_type=ltobits",
         "Buncombe", "NC", "ltobits", "Groce Funeral Home", True),
    Feed("wataugademocrat.com", "https://www.wataugademocrat.com/search/?f=rss&t=article&c=obituaries&l=50"
                                "&s=start_time&sd=desc", "Watauga", "NC", "townnews", "Watauga Democrat", False),
    Feed("averyjournal.com", "https://www.averyjournal.com/search/?f=rss&t=article&c=obituaries&l=50"
                             "&s=start_time&sd=desc", "Avery", "NC", "townnews", "Avery Journal-Times", False),
)

DETAIL_MAX = int(os.environ.get("OBIT_FEEDS_DETAIL_MAX", "25"))
_TRIGGER_HINT = re.compile(r"surviv|left to cherish|leaves behind|leaves to cherish", re.I)
_CONTENT_START = re.compile(
    r'<(?:div|section)[^>]+class="[^"]*\b(?:entry-content|post-content|td-post-content|article-content|'
    r'single-content|obituary-text|obit-text|obituary-content|tribute-text|elementor-widget-theme-post-content|'
    r'ObituaryDescText)\b[^"]*"[^>]*>|<(?:div|section)[^>]+id="obituary"[^>]*>', re.I)
_CONTENT_END = re.compile(
    r'class="[^"]*(?:sharedaddy|jp-relatedposts|entry-footer|post-tags|share-buttons|related-posts|'
    r'comments-area|post-navigation|guestbook|condolence)|<footer\b|<aside\b|id="comments"', re.I)


def article_text(html: str) -> str:
    """The obituary body of an article page: from the theme's content block to the first share /
    related-posts / footer marker after it; else the first <article>. A whole page (sidebars full
    of other obituaries) is never read as one obituary."""
    h = re.sub(r"(?is)<(script|style|nav|header|form)[^>]*>.*?</\1>", " ", html or "")
    m = _CONTENT_START.search(h)
    if m:
        chunk = h[m.end():m.end() + 30000]
        e = _CONTENT_END.search(chunk)
        if e:
            chunk = chunk[:chunk.rfind("<", 0, e.start() + 1) if "<" in chunk[:e.start() + 1] else e.start()]
        if len(chunk) > 200:
            return chunk
    a = re.search(r"<article[^>]*>(.*?)</article>", h, re.S | re.I)
    if a and len(a.group(1)) > 200:
        body = a.group(1)
        e = _CONTENT_END.search(body)
        return body[:body.rfind("<", 0, e.start() + 1)] if e and "<" in body[:e.start() + 1] else body
    return ""


def strip_town_suffix(name: Optional[str], state: Optional[str]) -> Optional[str]:
    """'Jane Q Sample-Edgefield' -> 'Jane Q Sample': some papers title an obituary 'Name-Town'
    (the Edgefield Advertiser: 7 of 9 sampled rows carried the town in the decedent's name; audit
    2026-10-09 additions_verify). The suffix is cut only when it is a known town of the feed's
    state, so a hyphenated surname stays."""
    if not name or "-" not in name:
        return name
    head, _, tail = name.rpartition("-")
    tail = tail.strip()
    if head.strip() and tail and " " not in head.strip()[-1:]:
        from ...enrichment_obituary_match import counties_for_city
        if counties_for_city(tail, state):
            return head.strip(" -")
    return name


def feed_items(text: str) -> list[dict]:
    """[{title, link, published, content}] from an RSS/Atom feed."""
    out: list[dict] = []
    if feedparser is not None:
        for e in feedparser.parse(text).entries:
            content = ""
            if getattr(e, "content", None):
                try:
                    content = e.content[0].get("value") or ""
                except (AttributeError, IndexError, KeyError, TypeError):
                    content = ""
            content = content or getattr(e, "summary", "") or ""
            out.append({"title": getattr(e, "title", "") or "", "link": (getattr(e, "link", "") or "").strip(),
                        "published": (getattr(e, "published", "") or "").strip(), "content": content})
        return out
    for block in re.findall(r"<item[ >].*?</item>", text or "", re.S | re.I):
        def tag(t: str) -> str:
            m = re.search(rf"<{t}>(.*?)</{t}>", block, re.S | re.I)
            v = m.group(1) if m else ""
            cm = re.search(r"<!\[CDATA\[(.*?)\]\]>", v, re.S)
            return cm.group(1) if cm else v
        out.append({"title": tag("title"), "link": tag("link").strip(), "published": tag("pubDate").strip(),
                    "content": tag("content:encoded") or tag("description")})
    return out


def _county_for(feed: Feed, residence: Optional[str]) -> str:
    return _place_for(feed, residence)[0]


def _place_for(feed: Feed, residence: Optional[str]) -> tuple[str, str]:
    """(county, state) of the decedent's residence when it names one county in the feed's state,
    else in the other Carolina (a Tryon NC paper prints Landrum SC deaths: audit 2026-10-09, the
    county was the paper's on rows whose decedent lived across the line), else the feed's own."""
    if residence:
        from ...enrichment_obituary_match import counties_for_city
        for st in (feed.state, "SC" if feed.state == "NC" else "NC"):
            cs = counties_for_city(residence, st)
            if len(cs) == 1:
                return next(iter(cs)), st
    return feed.county, feed.state


def _known_with_survivors() -> set[str]:
    try:
        from ...heirs_store import ObituaryStore
        return {u for u, r in ObituaryStore().load().records.items() if r.get("survivors")}
    except Exception:  # noqa: BLE001
        return set()


class ObituaryFeeds(BaseScraper):
    slug = "public_notices.obituary_feeds"
    name = "Open obituary feeds (W-NC + Upstate SC papers / funeral homes) with survivor lists"
    category = "motivated_seller"
    timeout_s = 600.0
    expected_min_count = 0

    async def fetch(self) -> Iterable:
        if os.environ.get("FORECLOSURE_OBIT_FEEDS", "1") == "0":
            return []
        out = self.partial
        seen: set[str] = set()
        known = _known_with_survivors()
        stats: dict[str, dict] = {}
        async with PoliteFetcher() as pf:
            for feed in FEEDS:
                st = stats.setdefault(feed.host, {"items": 0, "rows": 0, "detail": 0, "with_survivors": 0})
                try:
                    text = await pf.get(feed.url)
                except Walled as w:
                    st["walled"] = w.reason
                    continue
                except Exception as exc:  # noqa: BLE001
                    st["error"] = str(exc)[:120]
                    continue
                details = 0
                for it in feed_items(text):
                    st["items"] += 1
                    dec = strip_town_suffix(decedent_from_title(it["title"]), feed.state)
                    link = it["link"]
                    if not dec or not link or link in seen:
                        continue
                    seen.add(link)
                    body = it["content"] or ""
                    if (feed.detail and not _TRIGGER_HINT.search(body) and details < DETAIL_MAX
                            and link not in known and feed.host not in pf.walled):
                        try:
                            page = await pf.get(link, content_rx=_CONTENT_START)
                            details += 1
                            st["detail"] += 1
                            body = article_text(page) or body
                        except Walled as w:
                            st["walled_detail"] = w.reason
                        except Exception:  # noqa: BLE001
                            pass
                    if feed.kind != "townnews" and not looks_like_obituary(body):
                        st["not_obituary"] = st.get("not_obituary", 0) + 1
                        continue
                    from ...obituary_text import clean_text, parse_obituary_lede
                    lede = parse_obituary_lede(clean_text(body)) if body else {}
                    place_county, place_state = _place_for(feed, lede.get("residence"))
                    li = obituary_listing(
                        source=self.slug, url=link, decedent=dec, state=place_state,
                        county=place_county, publisher=feed.publisher,
                        text=body if feed.kind != "townnews" else "", published=it["published"] or None,
                        extra_public={"feed_host": feed.host, "feed_kind": feed.kind})
                    out.append(li)
                    st["rows"] += 1
                    if li.raw["obituary"].get("survivor_names_parsed"):
                        st["with_survivors"] += 1
        log.info("obituary_feeds.done", rows=len(out), hosts=stats)
        self.last_stats = stats
        return out
