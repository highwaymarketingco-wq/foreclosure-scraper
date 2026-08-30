"""Funeral-home CMS obituary RSS feeds — pre-probate heir leads (net-new).

A property owner's DEATH is the earliest motivated-seller signal in the estate
funnel: it surfaces weeks before a probate creditor-notice publishes, and it also
catches estates that never formally probate. Individual funeral homes across the
core footprint publish their recent obituaries as plain RSS 2.0 feeds off two
common CMS platforms — free, no login, no WAF:

  (A) Frazer Consultants CMS -> ``HOST/feed``.  Channel title
      "Recent Obituaries for <HOME>", 20 <item>s.  <title> = "Full Name |
      MM/DD/YYYY" (split on ' | ' -> decedent name + death/publish date),
      <link> = HOST/obituary/<slug>?fh_id=<id>.
  (B) WordPress 'ltobits' obituary plugin -> ``HOST/?feed=rss2&post_type=ltobits``
      (the plain /feed is BLOG posts only — must pass the post_type param).
      Channel title "Obituaries Archive - <HOME>", 10 <item>s.  <title> =
      decedent full name (may carry HTML entities), <link> = HOST/obits/<slug>/.

Confirmed hosts (Western NC + Upstate SC core):
  grocefuneralhome.com        -> Buncombe (Asheville) NC   [ltobits]
  cecilmburtonfuneralhome.com -> Cleveland (Shelby)  NC    [Frazer]
  sullivanking.com            -> Anderson            SC    [Frazer]

One name-only lead per <item> (decedent -> Listing.defendant). The name->property
resolver then pins the decedent's parcel via the county GIS owner-name index (same
path as the Gannett obituaries + Spartan Weekly probate notices); decedents who
owned property in-county become real heir/estate leads, the rest stay unresolved
name-only and carry no value.

NET-NEW vs gannett_obituaries.py: that scraper parses 8 NEWSPAPER /obituaries/ HTML
listing pages; these are individual FUNERAL-HOME CMS RSS feeds — a different,
non-overlapping source class. To scale, probe more core-county homes with the same
two URL shapes and add them to the host map below.

Free, public, plain-HTTP. Gate off with FORECLOSURE_FUNERAL_RSS=0.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

try:  # feedparser handles entity decoding + malformed feeds; stdlib fallback below
    import feedparser  # type: ignore
except Exception:  # noqa: BLE001
    feedparser = None  # type: ignore

log = structlog.get_logger()

# kind: "frazer" -> HOST/feed, title "Name | MM/DD/YYYY";
#       "ltobits" -> HOST/?feed=rss2&post_type=ltobits, title bare name.
# host -> (county, state, kind) it covers, across the core footprint.
HOMES = {
    "grocefuneralhome.com": ("Buncombe", "NC", "ltobits"),
    "cecilmburtonfuneralhome.com": ("Cleveland", "NC", "frazer"),
    "sullivanking.com": ("Anderson", "SC", "frazer"),
}

# per-item HTML entities that survive when we fall back to stdlib XML parsing
_ENTITIES = {
    "&amp;": "&", "&#x26;": "&", "&#38;": "&",
    "&quot;": '"', "&#x22;": '"', "&#34;": '"',
    "&apos;": "'", "&#x27;": "'", "&#39;": "'",
    "&#8216;": "‘", "&#8217;": "’",
    "&#8220;": "“", "&#8221;": "”",
    "&#x2f;": "/", "&#47;": "/", "&#x2F;": "/",
    "&lt;": "<", "&gt;": ">", "&nbsp;": " ",
}

_ITEM_RE = re.compile(r"<item[ >].*?</item>", re.S | re.I)
_TAG_RE = {
    "title": re.compile(r"<title>(.*?)</title>", re.S | re.I),
    "link": re.compile(r"<link>(.*?)</link>", re.S | re.I),
    "pubDate": re.compile(r"<pubDate>(.*?)</pubDate>", re.S | re.I),
    # The RSS <description> / <content:encoded> carry the obituary body
    # (age / DOB / survivors / funeral-home) that title+link+date discard.
    "description": re.compile(r"<description>(.*?)</description>", re.S | re.I),
    "content": re.compile(r"<content:encoded>(.*?)</content:encoded>", re.S | re.I),
}
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
# Age ("87 years", "aged 87 years"); survivors clause ("survived by ...").
_AGE_RE = re.compile(r"\b(\d{1,3})\s+years?\b", re.I)
_SURVIVORS_RE = re.compile(
    r"(?:is|are|was|were)?\s*survived by\s+(.{5,240}?)(?:\.|;|$)", re.I
)
# Frazer titles append the death/publish date after a pipe: "Full Name | MM/DD/YYYY".
_TITLE_DATE_RE = re.compile(r"\|\s*(\d{1,2}/\d{1,2}/\d{2,4})")
_TAGSTRIP_RE = re.compile(r"<[^>]+>")


def _unescape(s: str) -> str:
    if not s:
        return ""
    m = _CDATA_RE.search(s)
    if m:
        s = m.group(1)
    for ent, ch in _ENTITIES.items():
        s = s.replace(ent, ch)
    # any leftover numeric entities -> best-effort strip to their char
    s = re.sub(r"&#x([0-9a-fA-F]+);", lambda mm: chr(int(mm.group(1), 16)), s)
    s = re.sub(r"&#(\d+);", lambda mm: chr(int(mm.group(1))), s)
    return re.sub(r"\s+", " ", s).strip()


def _name_from_title(title: str, kind: str) -> str:
    """Frazer titles are 'Full Name | MM/DD/YYYY' — keep the name half.
    ltobits titles are the bare decedent name. Strip a trailing dagger/date."""
    name = _unescape(title)
    if kind == "frazer" and "|" in name:
        name = name.split("|", 1)[0].strip()
    # drop a trailing ' - obituary' style suffix if any home appends one
    name = re.sub(r"\s*[-–]\s*obituar(?:y|ies)\s*$", "", name, flags=re.I)
    return name.strip()


def _date_from_title(title: str) -> str | None:
    """Pull the 'MM/DD/YYYY' the Frazer title carries after the pipe (kept as
    raw['obituary']['title_date'] instead of being discarded)."""
    m = _TITLE_DATE_RE.search(_unescape(title))
    return m.group(1) if m else None


def _summary_fields(summary_html: str) -> dict:
    """Parse the obituary body (RSS <description>/<content:encoded>) for the
    summary text + age + survivors. HTML/entities are stripped first."""
    if not summary_html:
        return {}
    # _unescape first (extracts CDATA + decodes entities), then strip tags, so a
    # stdlib-path <![CDATA[...]]> wrapper doesn't leave a "]]>" artifact behind.
    text = re.sub(r"\s+", " ", _TAGSTRIP_RE.sub(" ", _unescape(summary_html))).strip()
    if not text:
        return {}
    out: dict = {"summary": text[:800]}
    am = _AGE_RE.search(text)
    if am:
        try:
            age = int(am.group(1))
            if 1 <= age <= 120:
                out["age"] = age
        except (ValueError, TypeError):
            pass
    sm = _SURVIVORS_RE.search(text)
    if sm:
        surv = re.sub(r"\s+", " ", sm.group(1)).strip(" ,;")
        if len(surv) >= 5:
            out["survivors"] = surv[:240]
    return out


def _iter_entries(text: str, kind: str):
    """Yield (name, link, pubdate_raw, summary_html, title_date) per feed
    <item>. feedparser first, stdlib regex fallback so a missing dep never
    silences the source."""
    if feedparser is not None:
        parsed = feedparser.parse(text)
        for e in parsed.entries:
            raw_title = getattr(e, "title", "") or ""
            name = _name_from_title(raw_title, kind)
            link = (getattr(e, "link", "") or "").strip()
            pub = (getattr(e, "published", "") or "").strip()
            summary = getattr(e, "summary", "") or getattr(e, "description", "") or ""
            content = getattr(e, "content", None)
            if content:
                try:
                    summary = content[0].get("value") or summary
                except (AttributeError, IndexError, KeyError, TypeError):
                    pass
            yield name, link, pub, summary, _date_from_title(raw_title)
        return
    for block in _ITEM_RE.findall(text):
        tm = _TAG_RE["title"].search(block)
        lm = _TAG_RE["link"].search(block)
        pm = _TAG_RE["pubDate"].search(block)
        dm = _TAG_RE["content"].search(block) or _TAG_RE["description"].search(block)
        raw_title = tm.group(1) if tm else ""
        name = _name_from_title(raw_title, kind)
        link = _unescape(lm.group(1)) if lm else ""
        pub = _unescape(pm.group(1)) if pm else ""
        summary = dm.group(1) if dm else ""
        yield name, link, pub, summary, _date_from_title(raw_title)


class FuneralHomeRss(BaseScraper):
    slug = "public_notices.funeral_home_rss"
    name = "Funeral-Home RSS Obituaries (W-NC + Upstate-SC — pre-probate heir leads)"
    category = "motivated_seller"
    timeout_s = 120.0
    expected_min_count = 0  # feeds can drift / go empty — not a REGRESSION

    def _feed_url(self, host: str, kind: str) -> str:
        if kind == "ltobits":
            return f"https://www.{host}/?feed=rss2&post_type=ltobits"
        return f"https://www.{host}/feed"

    async def _collect(self) -> list[Listing]:
        if os.environ.get("FORECLOSURE_FUNERAL_RSS", "1") == "0":
            return []
        out: list[Listing] = []
        seen: set[tuple[str, str]] = set()  # dedupe by (name, url)
        now = datetime.utcnow()
        async with client(timeout=15.0) as c:
            for host, (county, state, kind) in HOMES.items():
                url = self._feed_url(host, kind)
                try:
                    r = await c.get(url)
                    if r.status_code != 200:
                        log.warning("funeral_rss.bad_status", host=host,
                                    status=r.status_code)
                        continue
                except Exception as exc:  # noqa: BLE001
                    log.warning("funeral_rss.fetch_failed", host=host,
                                error=str(exc)[:140])
                    continue

                kept = 0
                for name, link, pub, summary_html, title_date in _iter_entries(
                    r.text, kind
                ):
                    if len(name) < 5 or name.replace(" ", "").isdigit():
                        continue
                    if " " not in name:  # need at least first + last
                        continue
                    link = link or url
                    key = (name.lower(), link)
                    if key in seen:
                        continue
                    seen.add(key)
                    obituary = {"decedent": name, "home": host,
                                "county": county, "state": state,
                                "cms": kind, "pub_date": pub or None}
                    # Keep the Frazer title date instead of discarding it.
                    if title_date:
                        obituary["title_date"] = title_date
                    # Age / survivors / summary from the RSS body.
                    obituary.update(_summary_fields(summary_html))
                    out.append(Listing(
                        source=self.slug,
                        source_url=link,
                        listing_type=ListingType.PROBATE_NOTICE,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state, county=county,
                        defendant=name,  # decedent -> resolver pins parcel by owner-name
                        description=f"Obituary (death) — {name}, {county} County {state} "
                                    f"— pre-probate heir/estate signal (funeral-home feed)",
                        first_seen=now, last_seen=now,
                        raw={
                            "obituary": obituary,
                            "life_event": "death",
                            "relationship_signal": {"kind": "probate",
                                                    "keyword": "obituary"},
                        },
                    ))
                    kept += 1
                log.info("funeral_rss.home", host=host, county=county,
                         cms=kind, kept=kept)
        log.info("funeral_rss.done", leads=len(out))
        return out

    async def fetch(self) -> Iterable[Listing]:
        return await self._collect()
