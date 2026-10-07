"""Bankruptcy-court CM/ECF public RSS: motions and orders for relief from the automatic stay.

Source
------
Three U.S. Bankruptcy Courts publish their CM/ECF "recent entries" feed to the public,
no PACER login, no fee for the feed itself:

    https://ecf.scb.uscourts.gov/cgi-bin/rss_outside.pl    District of South Carolina
    https://ecf.ncmb.uscourts.gov/cgi-bin/rss_outside.pl   Middle District of North Carolina
    https://ecf.ncwb.uscourts.gov/cgi-bin/rss_outside.pl   Western District of North Carolina

(The Eastern District of NC answers the same URL with an empty body: it publishes no
public feed. Its relief-from-stay motions stay reachable only through CourtListener /
PACER.) Each item is one docket entry from the last ~24 hours:

    <title>26-04005-eg JOHN Q SAMPLE</title>                  case number + case title
    <description>Type: bk Office: 2 Chapter: 7 Trustee: ...
                 [Relief from Stay] ( 14 )</description>         event short name, doc #
    <link>.../cgi-bin/DktRpt.pl?<case id></link>               the docket (PACER, paid)
    <guid>...DktRpt.pl?<case id>-<entry seq></guid>
    <pubDate>...</pubDate>

Read live 2026-10-07 (one GET per feed): SC 784 entries / 10 relief-from-stay,
MDNC 302 / 5, WDNC 89 / 3 -- about 18 a day across the three. A motion for relief from
stay is the secured creditor (usually the mortgage servicer) asking the bankruptcy judge
to let its foreclosure resume; an order on it is the judge deciding. Either is the
strongest public sign that a bankrupt owner's house is headed back to foreclosure.

What the feed does NOT carry: the movant's name, the property address or the docket
text -- only the event's short name. So every row here is tied to the DEBTOR NAME +
DISTRICT (+ the court's office code), never to a property; the downstream bankruptcy
name match (enrichment_bankruptcy) joins it to a board row for the same person. County
is "Statewide" because the feed does not say which county the debtor lives in.

Cadence: the feed is a rolling window, so a run that skips a day loses that day's
entries; CourtListener (already read) keeps the history. Access: open, three GETs per
run, ordinary User-Agent. Gate with FORECLOSURE_BK_RSS_RFS=0.
"""
from __future__ import annotations

import html
import os
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

#: (court id, state, district label, feed url)
FEEDS: tuple[tuple[str, str, str, str], ...] = (
    ("scb", "SC", "District of South Carolina", "https://ecf.scb.uscourts.gov/cgi-bin/rss_outside.pl"),
    ("ncmb", "NC", "Middle District of North Carolina", "https://ecf.ncmb.uscourts.gov/cgi-bin/rss_outside.pl"),
    ("ncwb", "NC", "Western District of North Carolina", "https://ecf.ncwb.uscourts.gov/cgi-bin/rss_outside.pl"),
)
ENV_OFF = "FORECLOSURE_BK_RSS_RFS"

_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S | re.I)
_TAG_RE = {t: re.compile(rf"<{t}>(.*?)</{t}>", re.S | re.I)
           for t in ("title", "link", "description", "guid", "pubDate")}
_RFS_RE = re.compile(r"relief\s+from\s+(?:the\s+)?(?:automatic\s+|co-?\s?debtor\s+)?stay|"
                     r"lift(?:ing)?\s+(?:the\s+)?(?:automatic\s+)?stay", re.I)
_EVENT_RE = re.compile(r"\[([^\]]+)\]")
_CASE_RE = re.compile(r"^\s*(\d{2}-\d{4,6}(?:-[a-z]{2,4})?)\s+(.*)$", re.I)
_META_RE = {
    "type": re.compile(r"Type:\s*(\S+)", re.I),
    "office": re.compile(r"Office:\s*(\S+)", re.I),
    "chapter": re.compile(r"Chapter:\s*(\S+)", re.I),
}


def _tag(item: str, name: str) -> str:
    m = _TAG_RE[name].search(item)
    return html.unescape(m.group(1)).strip() if m else ""


def parse_feed(xml: str) -> list[dict[str, Any]]:
    """RSS text -> list of entry dicts (all events, unfiltered)."""
    out: list[dict[str, Any]] = []
    for raw in _ITEM_RE.findall(xml or ""):
        title = re.sub(r"\s+", " ", _tag(raw, "title"))
        desc = _tag(raw, "description")
        desc_text = re.sub(r"<[^>]+>", " ", desc)
        m = _CASE_RE.match(title)
        events = _EVENT_RE.findall(desc_text)
        rec = {
            "case_number": m.group(1) if m else None,
            "case_title": (m.group(2).strip() if m else title) or None,
            "event": events[0].strip() if events else None,
            "link": _tag(raw, "link") or None,
            "guid": _tag(raw, "guid") or None,
            "pub_date": _tag(raw, "pubDate") or None,
        }
        for k, rx in _META_RE.items():
            mm = rx.search(desc_text)
            rec[k] = mm.group(1) if mm else None
        out.append(rec)
    return out


def is_relief_from_stay(rec: dict[str, Any]) -> bool:
    return bool(rec.get("event") and _RFS_RE.search(rec["event"]))


def _pub(rec: dict[str, Any]) -> datetime | None:
    try:
        dt = parsedate_to_datetime(rec.get("pub_date") or "")
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


def group_cases(entries: list[dict[str, Any]], court: str) -> list[dict[str, Any]]:
    """Relief-from-stay entries of one feed, one record per case (a case often logs the
    motion, its fee receipt and a hearing notice within the same day)."""
    by_case: dict[str, dict[str, Any]] = {}
    for rec in entries:
        if not is_relief_from_stay(rec) or not rec.get("case_number"):
            continue
        cur = by_case.setdefault(rec["case_number"], {
            "court": court, "case_number": rec["case_number"], "debtor": rec.get("case_title"),
            "chapter": rec.get("chapter"), "office": rec.get("office"), "docket_url": rec.get("link"),
            "events": [], "first_seen_entry": None, "has_order": False,
        })
        cur["events"].append(rec["event"])
        if re.search(r"\border\b", rec["event"], re.I):
            cur["has_order"] = True
        dt = _pub(rec)
        if dt and (cur["first_seen_entry"] is None or dt < cur["first_seen_entry"]):
            cur["first_seen_entry"] = dt
    return list(by_case.values())


def build_listing(case: dict[str, Any], *, state: str, district: str,
                  now: datetime) -> Listing | None:
    debtor = (case.get("debtor") or "").strip()
    if not debtor:
        return None
    entry_dt = case.get("first_seen_entry")
    kind = "order on relief from stay" if case.get("has_order") else "motion for relief from stay"
    return Listing(
        source=BankruptcyRssReliefFromStay.slug,
        source_url=case.get("docket_url") or dict((c, u) for c, _, _, u in FEEDS)[case["court"]],
        listing_type=ListingType.BANKRUPTCY,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county="Statewide",
        case_number=case["case_number"],
        defendant=debtor,
        description=(f"{district} bankruptcy {case['case_number']} (ch. {case.get('chapter') or '?'}): "
                     f"{kind} - " + ("the court ruled on a secured creditor's request to resume "
                                     "foreclosure on the debtor's collateral" if case.get("has_order")
                                     else "a secured creditor is asking to resume foreclosure on "
                                     "the debtor's collateral") + f" ({debtor})")[:300],
        first_seen=now,
        last_seen=now,
        raw={"bankruptcy_relief_from_stay": {
            "court": case["court"],
            "district": district,
            "case_number": case["case_number"],
            "debtor": debtor,
            "chapter": case.get("chapter"),
            "office": case.get("office"),
            "events": case["events"],
            "has_order": bool(case.get("has_order")),
            "entry_date": entry_dt.isoformat() if entry_dt else None,
            "property_address": None,   # the feed never carries one
            "movant": None,             # nor the creditor's name
            "signal": "bankruptcy_relief_from_stay",
        }},
    )


class BankruptcyRssReliefFromStay(BaseScraper):
    slug = "national.bankruptcy_rss_relief_from_stay"
    name = "Bankruptcy CM/ECF public RSS: relief-from-stay motions (SC, MDNC, WDNC)"
    category = "bankruptcy"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("bk_rss_rfs.disabled")
            return []
        now = datetime.utcnow()
        out: list[Listing] = []
        async with client(timeout=45.0) as http:
            for court, state, district, url in FEEDS:
                try:
                    r = await http.get(url)
                except Exception as exc:  # noqa: BLE001
                    log.warning("bk_rss_rfs.fetch_failed", court=court, error=str(exc)[:160])
                    continue
                if r.status_code != 200 or "<rss" not in r.text[:500].lower():
                    log.warning("bk_rss_rfs.not_rss", court=court, status=r.status_code)
                    continue
                entries = parse_feed(r.text)
                cases = group_cases(entries, court)
                for case in cases:
                    li = build_listing(case, state=state, district=district, now=now)
                    if li is not None:
                        out.append(li)
                log.info("bk_rss_rfs.parsed", court=court, entries=len(entries), cases=len(cases))
        return out


if __name__ == "__main__":
    import asyncio
    from collections import Counter

    async def _main() -> None:
        s = BankruptcyRssReliefFromStay()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        print(Counter(li.raw["bankruptcy_relief_from_stay"]["court"] for li in rows).most_common())
        print("orders", sum(1 for li in rows if li.raw["bankruptcy_relief_from_stay"]["has_order"]),
              "chapters", Counter(li.raw["bankruptcy_relief_from_stay"]["chapter"] for li in rows).most_common())

    asyncio.run(_main())
