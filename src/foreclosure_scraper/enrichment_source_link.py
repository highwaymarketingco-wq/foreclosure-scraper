"""Classify each lead's source_url so the dashboard never shows a dead/misleading link.

Three kinds:
  'record' — a real per-record page (CourtListener docket, Spartan Weekly notice, a hosted PDF, a
             county sale-list PDF). Show it as the clickable source.
  'search' — the source only exposes a SEARCH portal, not a per-record URL (SC probate net, AcclaimWeb
             ROD), OR our scraper stored a synthetic '#notice-<hash>' placeholder (ncnotices linkless
             cards). For these we set search_url to the portal base so the dashboard can say
             "Search <portal> for <name>" instead of pretending it's a record link.

Pure-Python, no network. Sets raw['link_kind'] and (for search) raw['search_url'].
"""
from __future__ import annotations

import re

_PLACEHOLDER = re.compile(r"#notice-", re.I)
_SEARCH = re.compile(r"/search/?(\?|$)|AcclaimWeb|southcarolinaprobate\.net", re.I)


def _base(u: str) -> str:
    m = re.match(r"(https?://[^/]+)", u or "")
    return m.group(1) + "/" if m else (u or "")


def enrich_source_link(listings) -> dict:
    stats = {"record": 0, "search": 0}
    for li in listings:
        u = li.source_url or ""
        raw = li.raw if isinstance(li.raw, dict) else {}
        if _PLACEHOLDER.search(u):
            raw["link_kind"] = "search"           # synthetic placeholder -> not a real record link
            raw["search_url"] = _base(u)
            stats["search"] += 1
        elif _SEARCH.search(u):
            raw["link_kind"] = "search"           # the URL already IS the portal's search page
            raw["search_url"] = u
            stats["search"] += 1
        elif u.startswith("http"):
            raw["link_kind"] = "record"           # a genuine per-record link
            stats["record"] += 1
        else:
            raw["link_kind"] = "search"
            raw["search_url"] = u or None
            stats["search"] += 1
        li.raw = raw
    return stats
