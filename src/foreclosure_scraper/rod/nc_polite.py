"""Polite transport shared by the NC register-of-deeds platform adapters (nc_cott_v4, nc_lookup,
nc_ors).

THE RULES THIS MODULE ENFORCES, so no adapter can forget one
  * Plain HTTP with an ordinary desktop-browser User-Agent (the same headers the quiet-title
    intake sends). No TLS impersonation, no proxy, no cookie obtained any other way than by the
    site setting it on a normal page load.
  * At least MIN_GAP_S (1.6 s) between two requests to the same host, from any session or thread
    in this process, and never two requests to one host at the same time (a per-host lock is held
    for the whole request).
  * A per-run cap on lookups per county (NC_ROD_MAX_LOOKUPS_PER_COUNTY, default 30). One lookup is
    one name search, however many requests it takes. The cap is shared by every caller in the
    process, so the lien enricher and the chain enricher together never exceed it.
  * A CAPTCHA, a login page, a challenge page or a block status ends that county for the run:
    the county is recorded as walled, the adapter returns an empty result marked walled, and no
    later call in the process sends another request to it. Nothing retries it, solves it or works
    around it.

Wall detection is the quiet-title intake's own detect_wall (quiet_title/fetch.py) plus a few
markers that intake does not need (a 503 status, the 'Please Verify You are Not a Robot' gate the
newer Courthouse Computer Systems tenants show).
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import structlog

from ..quiet_title.fetch import HEADERS, detect_wall as _intake_detect_wall

log = structlog.get_logger()

MIN_GAP_S = 1.6
DEFAULT_TIMEOUT_S = 90.0
DEFAULT_MAX_LOOKUPS_PER_COUNTY = 30

_EXTRA_WALLS = [
    (re.compile(r"Please\s+Verify\s+You\s+are\s+Not\s+a\s+Robot|complete the CAPTCHA", re.I), "CAPTCHA"),
    (re.compile(r"<title>\s*Just a moment", re.I), "challenge page"),
]


def wall_reason(status: int, final_url: str, text: str) -> Optional[str]:
    """Why a response is a wall, or None. Pure, so it is tested on canned bodies."""
    if status == 503:
        return "HTTP 503"
    why = _intake_detect_wall(status, final_url or "", text or "")
    if why:
        return why
    head = (text or "")[:200_000]
    for rx, reason in _EXTRA_WALLS:
        if rx.search(head):
            return reason
    return None


class RodWalled(RuntimeError):
    """The county answered with a CAPTCHA, a login page, a challenge or a block status."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{reason}: {url}")
        self.url = url
        self.reason = reason


# ------------------------------------------------------------------------------------------------
# process-wide state: pacing, host locks, lookup budget, walled counties
# ------------------------------------------------------------------------------------------------

_state_lock = threading.Lock()
_host_locks: dict[str, threading.Lock] = {}
_last_request: dict[str, float] = {}
_lookups: dict[tuple[str, str, str], int] = {}
_walled: dict[tuple[str, str, str], str] = {}

#: test seams: tests replace these to run without real time passing
sleep: Callable[[float], None] = time.sleep
clock: Callable[[], float] = time.monotonic


def _host_lock(host: str) -> threading.Lock:
    with _state_lock:
        lk = _host_locks.get(host)
        if lk is None:
            lk = _host_locks[host] = threading.Lock()
        return lk


def max_lookups_per_county() -> int:
    try:
        return max(0, int(os.environ.get("NC_ROD_MAX_LOOKUPS_PER_COUNTY", DEFAULT_MAX_LOOKUPS_PER_COUNTY)))
    except ValueError:
        return DEFAULT_MAX_LOOKUPS_PER_COUNTY


def _key(platform: str, state: str, county: str) -> tuple[str, str, str]:
    return (platform, (state or "").upper(), (county or "").strip().lower())


def take_lookup(platform: str, state: str, county: str) -> bool:
    """Spend one lookup from the county's per-run budget. False when the budget is used up."""
    k = _key(platform, state, county)
    with _state_lock:
        n = _lookups.get(k, 0)
        if n >= max_lookups_per_county():
            return False
        _lookups[k] = n + 1
        return True


def lookups_used(platform: str, state: str, county: str) -> int:
    return _lookups.get(_key(platform, state, county), 0)


def mark_walled(platform: str, state: str, county: str, reason: str) -> None:
    k = _key(platform, state, county)
    with _state_lock:
        if k not in _walled:
            _walled[k] = reason
            log.warning("nc_rod.walled", platform=platform, state=state, county=county, reason=reason)


def walled_reason(platform: str, state: str, county: str) -> Optional[str]:
    return _walled.get(_key(platform, state, county))


def walled_counties() -> dict[tuple[str, str, str], str]:
    return dict(_walled)


def reset_state() -> None:
    """Forget pacing, budgets and walls (a new run; also used by tests)."""
    with _state_lock:
        _last_request.clear()
        _lookups.clear()
        _walled.clear()


# ------------------------------------------------------------------------------------------------
# the client
# ------------------------------------------------------------------------------------------------

@dataclass
class Page:
    status: int
    url: str
    final_url: str
    text: str


def _requests_session() -> Any:
    import requests
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


#: test seam: tests replace this with a factory returning a canned-response session
session_factory: Callable[[], Any] = _requests_session


class PoliteClient:
    """One cookie session against one county's register, for one platform."""

    def __init__(self, platform: str, state: str, county: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self.platform, self.state, self.county = platform, state, county
        self.timeout = timeout
        self.session = session_factory()
        self.requests = 0
        self.opened = clock()

    def _pace(self, host: str) -> None:
        last = _last_request.get(host)
        if last is not None:
            wait = MIN_GAP_S - (clock() - last)
            if wait > 0:
                sleep(wait)
        _last_request[host] = clock()

    def request(self, method: str, url: str, *, params: Any = None, data: Any = None,
                headers: Optional[dict] = None,
                accept_signin: Optional[Callable[[Page], bool]] = None) -> Page:
        """accept_signin: for a register whose public search sits behind a no-credential guest
        button (ruled a click-through on 2026-10-07). A page the wall detector reads as a login
        page is returned instead of raising ONLY when this callable says it is such a guest page;
        a CAPTCHA, a challenge or a block status still walls the county."""
        why = walled_reason(self.platform, self.state, self.county)
        if why:
            raise RodWalled(url, why)
        host = (urlsplit(url).hostname or "").lower()
        with _host_lock(host):
            self._pace(host)
            self.requests += 1
            try:
                r = self.session.request(method, url, params=params, data=data, headers=headers or {},
                                         timeout=self.timeout, allow_redirects=True)
            finally:
                _last_request[host] = clock()   # the gap runs from the END of a slow answer too
        page = Page(int(r.status_code), url, str(getattr(r, "url", url)), r.text or "")
        why = wall_reason(page.status, page.final_url, page.text)
        if why == "login page" and accept_signin is not None and accept_signin(page):
            return page
        if why:
            mark_walled(self.platform, self.state, self.county, why)
            raise RodWalled(page.final_url or url, why)
        return page

    def get(self, url: str, **kw: Any) -> Page:
        return self.request("GET", url, **kw)

    def post(self, url: str, data: Any, **kw: Any) -> Page:
        return self.request("POST", url, data=data, **kw)
