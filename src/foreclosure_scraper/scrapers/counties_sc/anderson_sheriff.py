"""Anderson County SC - Sheriff Sale properties.

Anderson County Sheriff's Office posts real estate auction listings
for properties being sold via court-ordered sheriff sales. Properties
come from mortgage foreclosures and judgment executions.

WHY THIS TIMED OUT 3 OF 3 RUNS (diagnosed live 2026-09-21)
  The host is down on its own side, not slow. ``www.andersonsheriff.com`` resolves to
  192.155.253.203, and port 443 there does not answer: a TCP connect from this Mac times out
  (25 s, no SYN-ACK) and a connect from a second network (the WebFetch tool's) is refused
  outright (ECONNREFUSED). The bare ``andersonsheriff.com`` does not resolve at all. The old
  code went through ``get_text(impersonate=True)``, which retries 3 times (8 s connect timeout
  each plus backoff), then a 45 s curl fallback, then 3 more impersonated tries: comfortably
  past the 120 s soft limit, so a dead host was reported as TIMEOUT.

  Now: one plain GET with the shared 8 s connect timeout. A connect failure is raised
  immediately, so ``safe_run`` classifies it in seconds as BLOCKED ("connection refused/
  dropped") or TIMEOUT ("network timeout (ConnectTimeout)") instead of burning the whole
  budget. The curl-cffi Chrome tier is used ONLY when the host answers with a block status
  (401/403/406/409), which is what it exists for. The parser is unchanged and could not be
  re-verified against a live page (there is none); when the host comes back, check it first.

  Anderson's real foreclosure sales are already covered by ``anderson_master_in_equity``
  (Sale-List and Sale-Results PDFs on andersoncountysc.org). A sheriff's sale here is a
  judgment execution and rare, so nothing material is lost while this host is down.

Free, public, no login.
Slug: counties_sc.anderson_sheriff
Category: sheriff_sale
ListingType: SHERIFF_SALE
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client, get_text_impersonate
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.andersonsheriff.com/sheriff-sales"


class AndersonSheriff(BaseScraper):
    slug = "counties_sc.anderson_sheriff"
    name = "Anderson County SC Sheriff Sales"
    category = "sheriff_sale"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def _get_html(self) -> str:
        """One plain GET. Connect/read failures PROPAGATE (fail fast, classified by
        safe_run); only a block status escalates to the Chrome-fingerprint tier."""
        async with client(timeout=25.0) as c:
            r = await c.get(PAGE_URL)
        if r.status_code == 200:
            return r.text or ""
        if r.status_code in (401, 403, 406, 409):
            return await get_text_impersonate(PAGE_URL, timeout=30.0)
        log.warning("anderson_sheriff.bad_status", status=r.status_code)
        return ""

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await self._get_html()
        except Exception as exc:
            log.warning("anderson_sheriff.fetch_fail", error=str(exc)[:160],
                        exc_type=type(exc).__name__)
            raise

        if not html or len(html) < 200:
            return out

        # Find sale entries - sheriff sale pages typically use tables or divs
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("case", "defendant", "plaintiff", "#")):
                continue
            if not any(re.search(r"\d", c) for c in clean):
                continue

            # Extract case number
            case_no = None
            for c in clean:
                m = re.search(r"\b(\d{2,4}[-\s]?(?:CP|CV|CA|GS|CR|L)[-\s]?\d+(?:-\d+)*)\b", c, re.I)
                if m:
                    case_no = m.group(1)
                    break

            # Extract address
            addr = None
            for c in clean:
                if re.search(r"\d+\s+\w+", c):
                    addr = c
                    break

            out.append(Listing(
                source="counties_sc.anderson_sheriff",
                source_url=PAGE_URL,
                listing_type=ListingType.SHERIFF_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Anderson",
                case_number=case_no,
                street_address=addr,
                defendant=clean[0] if clean else None,
                description=" | ".join(clean[:6]),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"anderson_sheriff": {"cells": clean[:10]}},
            ))

        log.info("anderson_sheriff.done", count=len(out))
        return out
