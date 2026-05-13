"""Tag every listing's source_url with reachability state.

Investor-grade policy: NEVER drop a listing on link-validation alone.
The scraper already parsed real data from the source; a degraded link
doesn't invalidate the listing. Instead we tag listings with their HTTP
status and let the dashboard / consumer surface a warning indicator
when the link is broken.

The 2026-05 SC Public Index incident: link_validator was issuing HEAD
to publicindex.sccourts.org URLs, getting 406 (Not Acceptable) due to
F5/Shape header negotiation, retrying as GET, getting 406 again, and
DROPPING the listing. ~245 SC lis-pendens listings vanished from the
dashboard despite the underlying scraper having pulled them perfectly.
This module no longer drops on any HTTP code.
"""
from __future__ import annotations

import asyncio

import httpx
import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()


# Hosts where HEAD/GET from a naive httpx client will fail (anti-bot, JS-
# rendered, F5/Shape, paywalled). Skip the network check entirely — listings
# from these hosts are kept on the strength of the scraper having parsed
# them in the same run.
KNOWN_ANTI_BOT_HOSTS = (
    "publicindex.sccourts.org",     # F5/Shape returns 406 on default headers
    "portal-nc.tylertech.cloud",    # Tyler React SPA, requires JS
    "www.realtor.com",              # 429s under sustained HEAD load
    "ap.rdcpix.com",                # Realtor photo CDN, sometimes 403s
    "www.foreclosure.com",          # auth-walled
    "vrmproperties.com",            # JS-rendered SPA
    "aldridgepite.com",             # disclaimer cookie required
    "kornlawfirm.com",              # JS-rendered
    "mtglaw.com",                   # AJAX-loaded
)


async def _check_one(c: httpx.AsyncClient, url: str) -> tuple[str, int | None]:
    """Return (status_label, http_status_code).

    status_label is one of:
      "skipped"     — host known anti-bot, network check skipped
      "ok"          — 2xx/3xx response
      "auth"        — 401/403/429 (auth gate or rate-limited; URL is real)
      "anti-bot"    — 406/415/418/422 (server rejected our request shape)
      "dead"        — 404/410/451 (URL gone)
      "server"      — 5xx (server-side problem, transient)
      "other"       — 4xx not covered above
      "unreachable" — connection failure (DNS, timeout, refused)

    Listing is ALWAYS kept; the label is tagged on raw for downstream display.
    """
    if any(h in url for h in KNOWN_ANTI_BOT_HOSTS):
        return "skipped", None
    # Relative URLs (e.g. CourtListener "/docket/.../") have no scheme.
    # httpx + httpcore raise plain ValueError on these, which bubbles up
    # through asyncio.gather and brings down the entire weekly orchestrator
    # before vision/Tyler/email run. Treat schemeless URLs as unreachable.
    if not (url.startswith("http://") or url.startswith("https://")):
        return "unreachable", None
    try:
        r = await c.head(url, follow_redirects=True, timeout=15.0)
        if r.status_code == 405:
            r = await c.get(url, follow_redirects=True, timeout=20.0)
        status = r.status_code
        if 200 <= status < 400:
            return "ok", status
        if status in (401, 403, 429):
            return "auth", status
        if status in (406, 415, 418, 422):
            return "anti-bot", status
        if status in (404, 410, 451):
            return "dead", status
        if 500 <= status < 600:
            return "server", status
        return "other", status
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return "unreachable", None


async def validate(listings: list[Listing], *, workers: int = 24) -> list[Listing]:
    """Tag every listing with its link health status. No listings are dropped.

    Each listing receives ``raw["link_check"] = {"status": <label>, "http": int|None}``
    so dashboard / sheets / email consumers can warn when links are broken
    without losing the underlying foreclosure data.
    """
    if not listings:
        return []
    sem = asyncio.Semaphore(workers)
    counts = {"skipped": 0, "ok": 0, "auth": 0, "anti-bot": 0,
              "dead": 0, "server": 0, "other": 0, "unreachable": 0}

    async with client(timeout=20.0) as c:

        async def task(listing: Listing) -> None:
            async with sem:
                label, status = await _check_one(c, listing.source_url)
                counts[label] += 1
                if not isinstance(listing.raw, dict):
                    listing.raw = {}
                listing.raw["link_check"] = {"status": label, "http": status}

        await asyncio.gather(*(task(li) for li in listings))

    log.info("link.validate.done", total=len(listings), **counts)
    return listings  # KEEP ALL — tagging only, no drops
