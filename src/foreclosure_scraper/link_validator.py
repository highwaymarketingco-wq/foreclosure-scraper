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
from datetime import datetime
import os
from urllib.parse import urlparse

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


#: How long an "ok" verdict stays trusted. A source_url that resolved cleanly a
#: few days ago is overwhelmingly still fine, and re-proving it is the single
#: most expensive avoidable step in the run.
LINK_RECHECK_DAYS = float(os.environ.get("LINK_RECHECK_DAYS", "7"))

#: Concurrent requests allowed against any ONE hostname. The global worker pool
#: can stay wide because the board spans hundreds of hosts; what hurt was
#: pointing all 24 workers at whichever host happened to dominate the queue.
PER_HOST_WORKERS = int(os.environ.get("LINK_PER_HOST_WORKERS", "4"))


def _needs_recheck(li: Listing, now: datetime) -> bool:
    """True when this listing's link must actually be fetched this run.

    Every other slow enricher already skips work it has done (gis_attrs targets
    ~18% of the board, geocode ~28%). Link validation did not: it re-fetched all
    32,143 source_urls every run, which the 2026-07-31 profile put at 7.7 hours,
    the second-largest block in a 42.8-hour run. The stored verdict carried no
    timestamp, so there was no way to tell a link checked an hour ago from one
    never seen.

    Policy: only a fresh "ok" is trusted. Anything broken, auth-walled or
    unreachable is re-checked every run, because those are exactly the states
    that change and that the operator acts on. A missing timestamp means the
    verdict predates this change, so it is re-checked once and stamped.
    """
    lc = li.raw.get("link_check") if isinstance(li.raw, dict) else None
    if not isinstance(lc, dict) or lc.get("status") != "ok":
        return True
    ts = lc.get("checked")
    if not ts:
        return True
    try:
        when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is not None:
        when = when.replace(tzinfo=None)
    return (now - when).total_seconds() > LINK_RECHECK_DAYS * 86400


async def validate(listings: list[Listing], *, workers: int = 24) -> list[Listing]:
    """Tag every listing with its link health status. No listings are dropped.

    Each listing receives ``raw["link_check"] = {"status": <label>, "http": int|None,
    "checked": <iso8601>}`` so dashboard / sheets / email consumers can warn when
    links are broken without losing the underlying foreclosure data.

    Incremental: a lead whose link was "ok" within LINK_RECHECK_DAYS keeps its
    verdict untouched. Set LINK_RECHECK_DAYS=0 to force a full re-validation.

    Deduplicated: each distinct URL is fetched once per run and the verdict is
    applied to every listing that shares it. Whole sources hang off a single
    document — 2,095 Spartanburg leads share one tax-sale PDF, 3,307 Asheville
    leads share one ArcGIS layer — so 57.5% of an undeduplicated pass was the
    same request repeated. That is slow, and it points a few thousand identical
    HEADs at one county server, which is exactly how a polite scraper gets its
    IP blocked.

    Throttled per host: `workers` is the global ceiling, PER_HOST_WORKERS the
    per-hostname one. 24-way concurrency against a single host drew 1,043 of
    3,349 courtlistener.com responses as 429 — a third of them — and every one
    of those leads got tagged link_check.status="auth". That is a quality
    signal we manufactured ourselves: the URLs were fine, we simply asked too
    fast, and the operator would have read it as a wall.
    """
    if not listings:
        return []
    now = datetime.utcnow()
    stamp = now.isoformat(timespec="seconds") + "Z"
    todo = [li for li in listings if _needs_recheck(li, now)]
    reused = len(listings) - len(todo)

    by_url: dict[str, list[Listing]] = {}
    for li in todo:
        by_url.setdefault(li.source_url, []).append(li)

    sem = asyncio.Semaphore(workers)
    host_sems: dict[str, asyncio.Semaphore] = {}
    counts = {"skipped": 0, "ok": 0, "auth": 0, "anti-bot": 0,
              "dead": 0, "server": 0, "other": 0, "unreachable": 0}

    def _host_sem(url: str) -> asyncio.Semaphore:
        try:
            host = urlparse(url).hostname or ""
        except ValueError:
            host = ""
        if host not in host_sems:
            host_sems[host] = asyncio.Semaphore(PER_HOST_WORKERS)
        return host_sems[host]

    async with client(timeout=20.0) as c:

        async def task(url: str, sharing: list[Listing]) -> None:
            async with sem, _host_sem(url):
                label, status = await _check_one(c, url)
            counts[label] += len(sharing)
            for listing in sharing:
                if not isinstance(listing.raw, dict):
                    listing.raw = {}
                listing.raw["link_check"] = {
                    "status": label, "http": status, "checked": stamp,
                }

        await asyncio.gather(*(task(u, ls) for u, ls in by_url.items()))

    log.info("link.validate.done", total=len(listings), checked=len(todo),
             fetched=len(by_url), reused_fresh=reused,
             recheck_days=LINK_RECHECK_DAYS, **counts)
    return listings  # KEEP ALL — tagging only, no drops
