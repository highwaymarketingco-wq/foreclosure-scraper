"""Single source of truth for the residential-vs-datacenter source split.

Cloud-split deploy (2026-08): the engine runs in two places.
  * The Mac (residential IP) runs the browser-stealth scrapers, whose target
    sites (Cloudflare / F5-Shape / DataDome) score a datacenter IP as a bot
    before browser-fingerprint stealth even applies. Those only work from a
    clean residential IP, which the home Mac provides for free.
  * A free Oracle Always-Free VM (datacenter IP, 24 GB RAM, always-on) runs
    every other source plus all the RAM-heavy enrichment + the board publish.

Which sources are residential-IP-sensitive is DERIVED FROM THE CODE, not a
hand-kept list: any scraper whose module drives the Scrapling stealth browser
(StealthyFetcher / nodriver, directly or via render.fetch_rendered) needs the
residential host. curl_cffi impersonate (http_client.get_text_impersonate) is
TLS-fingerprint stealth, not a browser and not location-bound, so those stay on
the VM. Add or remove a scraper and the split re-derives correctly.

A scraper can also declare ``mac_only = True``: it is not a stealth browser, but it has to
run on the Mac for another reason (counties_generic.liensnc logs in with the owner's own
account, which is used on the Mac only). It is counted with the residential sources, so the
Mac's hand-off lane runs it and the VM skips it.
"""
from __future__ import annotations

import functools
import inspect

from .scrapers._registry import all_scrapers

# Presence of any of these in a scraper's MODULE source means it drives a real
# stealth browser and depends on a residential IP to clear the site's bot wall.
RESIDENTIAL_MARKERS = ("StealthyFetcher", "nodriver", "undetected", "fetch_rendered")


def _module_source(scraper) -> str:
    mod = inspect.getmodule(type(scraper))
    if mod is None:
        return ""
    try:
        return inspect.getsource(mod)
    except (OSError, TypeError):
        return ""


def needs_mac(scraper) -> bool:
    """True when the scraper must run on the residential host: it drives a stealth browser
    (RESIDENTIAL_MARKERS in its module) or declares ``mac_only``."""
    if getattr(scraper, "mac_only", False):
        return True
    src = _module_source(scraper)
    return any(m in src for m in RESIDENTIAL_MARKERS)


@functools.lru_cache(maxsize=1)
def _classify() -> tuple[frozenset, frozenset]:
    residential: set[str] = set()
    datacenter: set[str] = set()
    for s in all_scrapers():
        target = residential if needs_mac(s) else datacenter
        target.add(s.slug)
    return frozenset(residential), frozenset(datacenter)


def residential_slugs() -> frozenset:
    """Slugs that MUST run on the residential-IP host (the Mac)."""
    return _classify()[0]


def datacenter_safe_slugs() -> frozenset:
    """Slugs safe to run from a datacenter IP (the Oracle VM)."""
    return _classify()[1]


if __name__ == "__main__":  # `python -m foreclosure_scraper.source_split`
    res = residential_slugs()
    dc = datacenter_safe_slugs()
    print(f"residential (Mac):     {len(res)}")
    print(f"datacenter-safe (VM):  {len(dc)}")
    print(f"total registered:      {len(res) + len(dc)}")
    print("\n-- residential slugs (run on the Mac) --")
    for s in sorted(res):
        print(" ", s)
