"""Shared parsing for the state Press Association public-notice platform.

scpublicnotices.com (SC Press Association) and ncnotices.com (NC Press
Association) run the SAME vendor product: an ASP.NET WebForms app with a
cookieless session path segment (/(S(id))/), an advanced-search sidebar of
accordion filter groups, and a WSExtendedGrid results GridView.

Every result row is one ``<table class="nested">`` holding:

  * a view button whose onclick is ``location.href='Details.aspx?SID=..&ID=<n>'``
  * ``<div class="left"><strong>Publication</strong><br>Weekday, Month D, YYYY</div>``
  * ``<div class="right" style="display:none">City: <br>County: </div>``
  * a sibling ``<td colspan>`` holding the TRUNCATED preview body, which ends in
    "... click 'view' to open the full text."

The full body lives on Details.aspx behind an "I Agree" + reCAPTCHA gate on
both sites, so the preview (~300 chars) is all we parse. That is enough for the
notice's caption, case number, party name and subject county.

Everything here is pure HTML->dict: no browser, no network, so it unit-tests
against a saved fixture. The per-site modules own the render/driving logic
because the two sites' search UIs diverge (SC drives a popular-search dropdown,
NC drives the county checkbox list).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ENTITIES = (("&nbsp;", " "), ("&amp;", "&"), ("&#39;", "'"), ("&quot;", '"'),
             ("&rsquo;", "'"), ("&lsquo;", "'"), ("&ldquo;", '"'), ("&rdquo;", '"'),
             ("&#8217;", "'"), ("&ndash;", "-"), ("&mdash;", "-"))

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_NESTED_RE = re.compile(r'<table class="nested".*?</table>', re.S)
_ID_RE = re.compile(r"Details\.aspx\?SID=[^&']+&(?:amp;)?ID=(\d+)")
_PK_RE = re.compile(r'hdnPKValue"\s+value="(\d+)"')
# <div class="left"><strong>Pub Name</strong><br>Friday, July 31, 2026</div>
_LEFT_RE = re.compile(r'<div class="left">\s*<strong>(.*?)</strong>\s*<br\s*/?>(.*?)</div>', re.S)
# The live render puts City:/County: in their own <div>s, so each value ends at
# the next tag. Flat single-cell fixtures put BOTH labels in one cell, so each
# value must also stop at its sibling label — otherwise "City: Marion County:
# McDowell" reads back as the city "Marion County: McDowell".
_RIGHT_CITY_RE = re.compile(r"City:\s*(.*?)\s*(?:County:|<)", re.I | re.S)
_RIGHT_COUNTY_RE = re.compile(r"County:\s*(.*?)\s*(?:City:|<)", re.I | re.S)
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b|"
                      r"\b([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\b")
_TRUNC_RE = re.compile(r"\s*\.{2,}\s*click 'view' to open the full text\.?\s*$", re.I)
_TOTAL_PAGES_RE = re.compile(r'lblTotalPages"[^>]*>\s*of\s*(\d+)\s*Pages', re.I)
_CUR_PAGE_RE = re.compile(r'lblCurrentPage"[^>]*>\s*(\d+)\s*<', re.I)

_DATE_FORMATS = ("%m/%d/%Y", "%A, %B %d, %Y", "%B %d, %Y", "%b %d, %Y")


def clean_text(raw: str | None) -> str:
    """Strip tags + entities and collapse whitespace."""
    s = raw or ""
    for ent, rep in _ENTITIES:
        s = s.replace(ent, rep)
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", s)).strip()


def parse_date(value: str | None) -> datetime | None:
    """Parse the platform's publication-date strings; None when unparseable."""
    s = (value or "").strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def total_pages(html: str) -> int | None:
    """The grid's "of N Pages" label, or None when the grid is unpaged."""
    m = _TOTAL_PAGES_RE.search(html or "")
    return int(m.group(1)) if m else None


def current_page(html: str) -> int | None:
    m = _CUR_PAGE_RE.search(html or "")
    return int(m.group(1)) if m else None


def result_blocks(html: str) -> Iterable[str]:
    """Yield one HTML fragment per result row.

    The live render wraps each result in its own ``<table class="nested">``;
    hand-written fixtures use a flat single ``<tr>`` per result. Prefer the
    nested tables, fall back to per-row so both shapes parse.
    """
    blocks = _NESTED_RE.findall(html or "")
    if blocks:
        yield from blocks
        return
    yield from _ROW_RE.findall(html or "")


def _body_text(block: str) -> str:
    """The notice preview: the widest non-metadata cell, minus the truncation trailer."""
    cells = [clean_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)]
    cells = [c for c in cells if c and "javascript" not in c.lower()]
    body = max((c for c in cells if "county:" not in c.lower()), key=len, default="")
    return _TRUNC_RE.sub("", body)


def parse_grid(html: str) -> list[dict]:
    """Parse a results-grid page into notice dicts.

    Keys: notice_id, publication, date_text, published_at, county_meta,
    city_meta, text. ``county_meta`` is the PUBLICATION's county (the paper that
    carried the ad), which is often NOT the county the notice is about — callers
    that need the subject county must read it out of ``text`` first.
    """
    out: list[dict] = []
    for block in result_blocks(html):
        m = _ID_RE.search(block) or _PK_RE.search(block)
        if not m:
            continue
        left = _LEFT_RE.search(block)
        publication = clean_text(left.group(1)) if left else ""
        date_text = clean_text(left.group(2)) if left else ""
        county = _RIGHT_COUNTY_RE.search(block)
        city = _RIGHT_CITY_RE.search(block)
        county_meta = clean_text(county.group(1)) if county else ""
        city_meta = clean_text(city.group(1)) if city else ""
        text = _body_text(block)
        if not left:
            # Flat fixture shape: publication/date/city/county share one cell.
            meta = next((clean_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)
                         if "county:" in clean_text(c).lower()), "")
            publication = publication or " ".join(meta.split()[:3])
            if not date_text:
                dm = _DATE_RE.search(meta)
                date_text = (dm.group(1) or dm.group(2)) if dm else ""
        if not date_text:
            dm = _DATE_RE.search(block)
            date_text = (dm.group(1) or dm.group(2)) if dm else ""
        out.append({
            "notice_id": m.group(1),
            "publication": publication,
            "date_text": date_text,
            "published_at": parse_date(date_text),
            "county_meta": county_meta,
            "city_meta": city_meta,
            "text": text,
        })
    return out
