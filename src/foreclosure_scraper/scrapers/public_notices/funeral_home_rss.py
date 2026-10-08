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

Confirmed hosts, round 2 (2026-09-27 probate/estate coverage sweep, see
docs/coverage_gap_build_plan_2026-09-23.md #2.4): all found via a
"meaningfulfunerals.net" web search per gap county (that domain is the
underlying Frazer/CFML obituary backend most Frazer clients proxy at their
own HOST/feed), then verified live against the funeral home's own domain --
not the WNC/Upstate-SC core, but the wider 141-of-146-county probate/estate
gap the docstring above calls out as the scaling target:
  lambfh.com                   -> Cabarrus    NC   [Frazer]
  edwardscares.com              -> Wilson      NC   [Frazer]
  willoughbyfuneralhomes.com    -> Edgecombe   NC   [Frazer]
  caseyfh.com                   -> Johnston    NC   [Frazer] (physical address
                                    is Princeton NC, which sits in Johnston Co.)
  dukesharleyfuneralhome.com    -> Orangeburg  SC   [Frazer]
  nesmithpinckneyfuneralhome.com-> Williamsburg SC  [Frazer]
  dychesfuneralhome.com         -> Barnwell    SC   [Frazer-shaped: this one is
                                    a plain WordPress site whose default
                                    HOST/feed happens to be all-"Obituaries"-
                                    category posts with bare-name titles (no
                                    Frazer backend, no ltobits plugin) -- kept
                                    under kind="frazer" because that is the
                                    URL shape that fetches it and the title
                                    has no pipe for _name_from_title to split
                                    on, so parsing is a no-op pass-through.

A ~90-candidate sweep across roughly 48 gap counties (see
docs/coverage_gap_build_plan_2026-09-23.md #2.4 revision notes / the commit
that added this) found these 7 to be the live, current hits. The large
majority of candidates tried in Western NC's deep mountain counties (Madison,
Haywood, Jackson, Macon, Swain, Graham, Cherokee, Clay, Yancey, Watauga, Ashe,
Avery, Wilkes, Caldwell, Alexander, Alleghany, Surry, Stokes) and several
Piedmont/Upstate counties immediately outside the core footprint (Iredell,
Rowan, Catawba, York, Chester, Newberry, Greenwood) came up empty: those
funeral homes run on other CMS platforms entirely (a shared vendor whose
generated markup starts with `<!doctype html ><html ... class="ios-preview-
native-scroll">` and a base64 `SiteType` -- decodes to "DUDAONE", i.e. the
Duda site builder -- is especially common there, and returns HTTP 200 with
plain HTML for both probe URLs, never RSS), or sit behind a Cloudflare
challenge page ("Just a moment...") on every path including /feed. One
additional live Frazer hit, abbevillewhitemortuary.com (Abbeville Co. SC),
was found and verified but is NOT wired here: its feed's newest item is dated
04/14/2025, so it has posted nothing in the ~17 months before this sweep --
wiring a feed that is not actively publishing would not add any real forward
coverage, so it is recorded here rather than added to HOMES.

Confirmed host, round 3 (2026-09-28 sweep of 15 populous NC+SC counties with
zero funeral_home_rss coverage -- Mecklenburg, Wake, Guilford, Forsyth,
Cumberland, Durham, Gaston, New Hanover, Greenville, Charleston, Richland,
Horry, Spartanburg, Lexington, Berkeley -- ~55 candidate domains tried, both
URL shapes each):
  dial-murrayfuneralhome.com   -> Berkeley    SC   [Frazer] (Moncks Corner;
                                   verified live, newest item 09/19/2026)

Round 3's 1-of-15-counties hit rate (vs round 2's 7-of-~48) is a genuine
finding, not an under-search: independent/family-run homes on Frazer or
WordPress+ltobits are a *rural and small-town* phenomenon. The 14 counties
that came up empty are exactly the state's biggest metros, where funeral
homes cluster on three other patterns instead: (1) large corporate rollups
(Dignity Memorial/SCI, "memorialplanning.com" network sites like
siskbutler.com) whose obituary pages live on the parent's own domain/CMS,
not the local site; (2) funeral-vertical SaaS platforms with no RSS at all
-- Tukios (`tukios_fhid` in page markup, e.g. alexanderfunerals.com) and
custom-PHP obituary modules (`allobituaries.php`, e.g.
moseleyfuneralservice.com / kornegayandmoseley.com) both return HTTP 200
plain HTML, never XML, for both probe shapes; (3) a real minority sit behind
bot-protection that 403s every path including /feed (aegriersonsfcc.com,
houseofrosadalecharlotte.com, fergusonfs.com, carltonlgrayfuneral.com,
salemfh.com, hmcolvin.com, clementsfuneralservice.com, hollowaymemorial.com,
wilmingtoncares.com, andrewsmortuary.com, robinsonfuneralhomes.com,
wmsmithmcnealfuneralhome.com, aadicksfuneralhome.com, mcleanfuneral.com,
hardwickfh.com, goldfinchfuneralhome.com, costnerfuneralhome.com) -- a real
wall under the repo's own compliance policy (CAPTCHA/login/WAF-challenge is
a wall; a plain robots.txt Disallow is not), so these were left alone rather
than bypassed. A handful of WordPress sites (rfhr.com, jhenrystuhr.com)
returned RSS_TAG=1 on both shapes but were confirmed-by-fetch false
positives: the ltobits plugin isn't installed, so `?post_type=ltobits`
silently falls back to the site's ordinary BLOG feed (WordPress ignores an
unknown post_type rather than erroring) -- same failure mode the module
docstring already warns about for the plain /feed shape, just one query
param later. leevy.com and seawright-funeralhome.com returned a genuine,
structurally valid, but completely empty RSS channel on both shapes (no
posts of any type), and siskbutler.com's feed is a memorialplanning.com
rollup echo (also empty). None of these five are usable hits.

One name-only lead per <item> (decedent -> Listing.defendant). The name->property
resolver then pins the decedent's parcel via the county GIS owner-name index (same
path as the Gannett obituaries + Spartan Weekly probate notices); decedents who
owned property in-county become real heir/estate leads, the rest stay unresolved
name-only and carry no value.

NET-NEW vs gannett_obituaries.py: that scraper parses 8 NEWSPAPER /obituaries/ HTML
listing pages; these are individual FUNERAL-HOME CMS RSS feeds — a different,
non-overlapping source class. To scale, probe more core-county homes with the same
two URL shapes and add them to the host map below.

WHY 50 ROWS PER RUN NEVER LANDED (diagnosed 2026-09-21; the reconciliation's "no county"
reading is wrong). Every row DOES carry county and state (set from the host map above: Buncombe
NC, Cleveland NC, Anderson SC, 10 + 20 + 20 rows live today) and all 50 pass ``main._in_scope``
(PROBATE_NOTICE is a distress type, so the any-NC/SC rule applies). What drops them is
``main._active_only``: an obituary has no sale date, and ``public_notices.funeral_home_rss`` is
NOT in ``main.DATELESS_OK_SOURCES`` (its sibling ``public_notices.gannett_obituaries`` is), so
0 of 50 survive. The fix is one line in main.py, written out in
docs/scraper_revival_2026-09-21.md; nothing a scraper can set on a row changes
``_active_only`` for a dateless lead. All 50 already resolve as name-resolver targets
(``enrichment_resolve_name_to_property._is_target``: name, state NC/SC, no address/parcel, core
county), and the record owner is now also written to ``owner_name`` (the resolver reads
owner_name first, then defendant) and ``raw.dateless=True`` marks the row as intentionally
dateless.

Free, public, plain-HTTP. Gate off with FORECLOSURE_FUNERAL_RSS=0.

EXTRACTION-COMPLETENESS AUDIT (2026-10-04, final batch). Two confirmed live
findings, both fixed here:

1. **2 of the 11 real hosts were silently returning nothing.** This module
   fetched with the bare ``client()`` (plain httpx only -- the shared
   ``http_client.client()``'s ``impersonate_browser`` kwarg is accepted but
   never actually used by that function, confirmed by reading it; it never
   escalates). Live-confirmed 2026-10-04: ``sullivanking.com`` and
   ``dial-murrayfuneralhome.com`` both now sit behind a Cloudflare
   "Just a moment..." JS challenge that plain httpx 403s on every request,
   while ``get_text_impersonate()`` (a real Chrome TLS/JA3 fingerprint, no
   CAPTCHA solving, no login -- the same compliant bypass class this
   codebase already uses elsewhere) sails through with a clean 200 and the
   real feed. Both hosts were silently producing zero rows, every run, with
   nothing distinguishing it from "no new obituaries this week." Switched to
   ``get_text(..., impersonate=True)`` per host.
2. **Every Frazer-kind feed (9 of 11 hosts) carries a rich ``obits:``
   RSS-namespace extension that was never read at all.** Live-confirmed
   across all 9: ``obits:birthDate``/``obits:deathDate`` (exact MM/DD/YYYY,
   feedparser exposes them as ``entry.obits_birthdate``/``obits_deathdate``),
   ``obits:deceased_city``/``obits:deceased_state`` (the DECEDENT's own city,
   independently useful -- confirmed it sometimes differs from the funeral
   home's own ``obits:fh_city``, e.g. a real Edgecombe Co. item: fh_city
   Tarboro, deceased_city Rocky Mount), and ``obits:fh_name``. The existing
   ``_summary_fields()`` (age/survivors from the RSS ``<description>``) is a
   complete no-op on every Frazer feed -- confirmed live: Frazer's
   ``<description>`` is pure boilerplate ("View The Obituary For X. Please
   join us...") with zero age/survivor signal, so this was the ONLY age
   source available for 9 of 11 hosts and it was silently empty on all of
   them. Now parsed into a precise ``age`` (computed from birth+death date,
   more reliable than any regex) plus ``birth_date``/``death_date``/
   ``deceased_city``/``deceased_state``/``fh_name`` in ``raw['obituary']``.

SOURCE-COMPLETENESS AUDIT (2026-10-08): 0 rows for 3 runs (was 40-50) was a
TIMEOUT that threw collected rows away, not dead feeds. All 11 feeds answered
200 to one ordinary request from the Mac that day (190 items, every host under
1.5 s). The VM's gated run of 2026-10-08 logged 8 ``funeral_rss.home`` events
(8 hosts finished) and then ``scraper.timeout`` at 124 s: the hosts were read
one after another, one slow host can cost about 2 minutes inside ``get_text``
(3 plain attempts, the curl fallback, 3 impersonate attempts, 15 s each), and
every row sat in a local list returned only at the end, so the soft timeout
discarded the finished hosts' rows too. Now the hosts are read concurrently
(still one request at a time per host), each host has its own wall-clock
deadline (``host_deadline_s``) inside ``timeout_s``, and each finished host's
rows go into ``self.partial`` at once, so a timeout still ships them. Run time
is the slowest host (at most 45 s), not the sum.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
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
    # Round 2 (2026-09-27 gap sweep, see module docstring above for how these
    # were found and the ~90 misses that didn't make it in).
    "lambfh.com": ("Cabarrus", "NC", "frazer"),
    "edwardscares.com": ("Wilson", "NC", "frazer"),
    "willoughbyfuneralhomes.com": ("Edgecombe", "NC", "frazer"),
    "caseyfh.com": ("Johnston", "NC", "frazer"),
    "dukesharleyfuneralhome.com": ("Orangeburg", "SC", "frazer"),
    "nesmithpinckneyfuneralhome.com": ("Williamsburg", "SC", "frazer"),
    "dychesfuneralhome.com": ("Barnwell", "SC", "frazer"),
    # Round 3 (2026-09-28 15-county populous-metro sweep, see module docstring
    # above -- 1 confirmed hit out of ~55 candidate domains tried).
    "dial-murrayfuneralhome.com": ("Berkeley", "SC", "frazer"),
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


def _age_from_dates(birth: str | None, death: str | None) -> int | None:
    """Precise age in completed years from MM/DD/YYYY birth + death dates.

    More reliable than any regex over free text -- this is exact arithmetic
    on the Frazer feed's own structured dates, not an inference."""
    if not birth or not death:
        return None
    try:
        b = datetime.strptime(birth.strip(), "%m/%d/%Y")
        d = datetime.strptime(death.strip(), "%m/%d/%Y")
    except ValueError:
        return None
    age = d.year - b.year - ((d.month, d.day) < (b.month, b.day))
    return age if 0 <= age <= 120 else None


def _obits_namespace_fields(entry) -> dict:
    """Pull the Frazer ``obits:`` RSS-namespace extension fields feedparser
    exposes as ``obits_birthdate``/``obits_deathdate``/etc. -- present on
    every Frazer-kind feed (live-confirmed 2026-10-04 across 9 of this
    module's 11 hosts) but never read before this fix. {} when the entry
    carries none (the ltobits / plain-WordPress hosts have no such
    namespace -- ``_summary_fields()``'s free-text regex is still their only
    source, unchanged)."""
    out: dict = {}
    bd = (getattr(entry, "obits_birthdate", "") or "").strip()
    dd = (getattr(entry, "obits_deathdate", "") or "").strip()
    if bd:
        out["birth_date"] = bd
    if dd:
        out["death_date"] = dd
    age = _age_from_dates(bd, dd)
    if age is not None:
        out["age"] = age
    # The DECEDENT's own city/state -- distinct from the funeral home's city
    # (obits:fh_city), confirmed live to sometimes differ (e.g. a real
    # Edgecombe Co. item: fh_city Tarboro, deceased_city Rocky Mount).
    dc = (getattr(entry, "obits_deceased_city", "") or "").strip()
    ds = (getattr(entry, "obits_deceased_state", "") or "").strip()
    if dc:
        out["deceased_city"] = dc
    if ds:
        out["deceased_state"] = ds
    fh_name = (getattr(entry, "obits_fh_name", "") or "").strip()
    if fh_name:
        out["fh_name"] = fh_name
    return out


def _iter_entries(text: str, kind: str):
    """Yield (name, link, pubdate_raw, summary_html, title_date, extra) per
    feed <item>. feedparser first, stdlib regex fallback so a missing dep
    never silences the source. ``extra`` carries the Frazer ``obits:``
    namespace fields (see ``_obits_namespace_fields``) when present, else
    {} (the stdlib fallback path also yields {} -- it has no namespace
    handling, a defensive-only code path for a missing feedparser dep)."""
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
            yield name, link, pub, summary, _date_from_title(raw_title), _obits_namespace_fields(e)
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
        yield name, link, pub, summary, _date_from_title(raw_title), {}


class FuneralHomeRss(BaseScraper):
    slug = "public_notices.funeral_home_rss"
    name = "Funeral-Home RSS Obituaries (W-NC + Upstate-SC — pre-probate heir leads)"
    category = "motivated_seller"
    timeout_s = 120.0
    expected_min_count = 0  # feeds can drift / go empty — not a REGRESSION
    #: Wall-clock cap on ONE host's fetch (all of get_text's retries and
    #: fallbacks included). Hosts run concurrently, so the whole run takes
    #: about the slowest host, bounded by this, well inside timeout_s.
    host_deadline_s = 45.0

    def _feed_url(self, host: str, kind: str) -> str:
        if kind == "ltobits":
            return f"https://www.{host}/?feed=rss2&post_type=ltobits"
        return f"https://www.{host}/feed"

    async def _fetch_feed(self, host: str, kind: str) -> tuple[str, str, str | None]:
        """(host, feed url, feed text or None). Never raises."""
        url = self._feed_url(host, kind)
        try:
            # impersonate=True: plain httpx first, escalating to a real
            # Chrome TLS fingerprint only on a 403/406 block (see module
            # docstring finding #1 -- 2 of 11 real hosts need this today).
            text = await asyncio.wait_for(
                get_text(url, timeout=15.0, impersonate=True),
                timeout=self.host_deadline_s,
            )
            return host, url, text
        except asyncio.TimeoutError:
            log.warning("funeral_rss.host_deadline", host=host,
                        deadline_s=self.host_deadline_s)
        except Exception as exc:  # noqa: BLE001
            log.warning("funeral_rss.fetch_failed", host=host,
                        error=str(exc)[:140])
        return host, url, None

    async def _collect(self) -> list[Listing]:
        if os.environ.get("FORECLOSURE_FUNERAL_RSS", "1") == "0":
            return []
        out: list[Listing] = []
        seen: set[tuple[str, str]] = set()  # dedupe by (name, url)
        now = datetime.utcnow()
        # One task per host (different hosts, one request each): the run costs the
        # slowest host, not the sum, and a hung host cannot starve the others.
        tasks = [asyncio.ensure_future(self._fetch_feed(host, kind))
                 for host, (_county, _state, kind) in HOMES.items()]
        try:
            for fut in asyncio.as_completed(tasks):
                host, url, text = await fut
                if text is None:
                    continue
                county, state, kind = HOMES[host]
                got = self._parse_host(text, host, url, county, state, kind, seen, now)
                out.extend(got)
                self.partial.extend(got)   # a soft timeout ships every finished host
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        log.info("funeral_rss.done", leads=len(out))
        return out

    def _parse_host(self, text: str, host: str, url: str, county: str, state: str,
                    kind: str, seen: set, now: datetime) -> list[Listing]:
        out: list[Listing] = []
        kept = 0
        for name, link, pub, summary_html, title_date, extra in _iter_entries(
            text, kind
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
            # Age / survivors / summary from the RSS body (ltobits /
            # plain-WordPress hosts' only source of either).
            obituary.update(_summary_fields(summary_html))
            # Frazer's own obits: namespace (birth/death dates, precise
            # age, decedent's own city/state) -- applied LAST so its
            # exact age wins over the free-text regex guess above on any
            # host that happens to carry both.
            obituary.update(extra)
            out.append(Listing(
                source=self.slug,
                source_url=link,
                listing_type=ListingType.PROBATE_NOTICE,
                property_kind=PropertyKind.UNKNOWN,
                state=state, county=county,
                defendant=name,  # decedent -> resolver pins parcel by owner-name
                owner_name=name,  # the resolver reads owner_name first, then defendant
                description=f"Obituary (death) — {name}, {county} County {state} "
                            f"— pre-probate heir/estate signal (funeral-home feed)",
                first_seen=now, last_seen=now,
                raw={
                    "obituary": obituary,
                    "life_event": "death",
                    "dateless": True,   # a death has no sale date; needs DATELESS_OK_SOURCES
                    "relationship_signal": {"kind": "probate",
                                            "keyword": "obituary"},
                },
            ))
            kept += 1
        log.info("funeral_rss.home", host=host, county=county,
                 cms=kind, kept=kept)
        return out

    async def fetch(self) -> Iterable[Listing]:
        return await self._collect()
