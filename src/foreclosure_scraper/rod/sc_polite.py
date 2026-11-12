"""Polite, wall-aware HTTP for the SC register-of-deeds name readers.

Shared by rod/publicsearch.py, rod/sc_online_record_system.py, rod/acclaim_names.py and
rod/anderson_acpass_rod.py. Three rules live here so no adapter can forget them:

  * Pace: at least MIN_GAP_S (1.6 s, env SC_ROD_MIN_GAP_S may only raise it) between two requests
    to the same host, whatever the method, and never two requests to one host at the same time
    (a per-host lock is held across pace + request, so the asyncio callers in
    enrichment_generic_rod.py, which run three lookups at once, still reach each host one by one).
    An ordinary desktop-browser User-Agent; no TLS impersonation, no proxy.
  * Walls: every response is checked by detect_wall(). A CAPTCHA, challenge page, bot check, login
    form or block status raises RodWalled, the county is recorded in WALLED for the rest of the
    process, and every later lookup for it returns at once without touching the network. Nothing
    here retries, solves or works around a wall.
  * Budget: LookupBudget caps owner lookups per county per run (env SC_ROD_MAX_LOOKUPS_PER_COUNTY,
    default 30). One top-level call (search_by_name, or one chain) is one lookup.

Nothing here writes fetched content anywhere.
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import structlog

log = structlog.get_logger()

MIN_GAP_S = max(1.6, float(os.environ.get("SC_ROD_MIN_GAP_S", "1.6")))
JITTER_S = 0.4
DEFAULT_MAX_LOOKUPS = 30
#: The sleep every pause goes through (looked up at call time, so tests can replace it).
SLEEP: Callable[[float], None] = time.sleep

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}


class RodWalled(RuntimeError):
    """The register answered with a CAPTCHA, a challenge or bot check, a login wall or a block."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{reason}: {url}")
        self.url = url
        self.reason = reason


# Text that marks a wall. Mirrors quiet_title/fetch.py (kept separate so the two packages do not
# depend on each other while both are being edited) plus the client-side bot check found on the
# Anderson SC Ingenuity site on 2026-10-07 (a script grades the browser and posts its verdict in
# a hidden field; a script that filled that field itself would be defeating a bot check).
_WALL_MARKERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"cf-chl|challenge-platform|cdn-cgi/challenge|Just a moment\.\.\.", re.I), "challenge page"),
    (re.compile(r"class=[\"'][^\"']*\b(g-recaptcha|h-captcha|cf-turnstile)\b|recaptcha/api2/anchor|"
                r"I'm not a robot|data-hcaptcha|BDC_CaptchaImage|LBD_CaptchaDiv", re.I), "CAPTCHA"),
    (re.compile(r"px-captcha|_Incapsula_Resource|Request unsuccessful\. Incapsula", re.I), "bot-block page"),
    (re.compile(r"hdnBotResult|Scripts/botdetect\.js|function\s+detectBot\s*\(", re.I), "bot check"),
    (re.compile(r"<title>\s*(Access Denied|Attention Required|403 Forbidden|Forbidden|"
                r"Request Rejected)\s*</title>", re.I), "block page"),
    (re.compile(r"Direct API access is not permitted", re.I), "API access refused"),
]
_LOGIN_URL = re.compile(r"/(log[-_]?in|sign[-_]?in|account/login|loginDisplay\.action)\b", re.I)
_PASSWORD_FIELD = re.compile(r"<input[^>]+type=[\"']?password", re.I)


def detect_wall(status: int, final_url: str, text: str) -> Optional[str]:
    """Why a response is a wall, or None. Pure, so it is tested on canned bodies."""
    if status in (401, 402, 403, 407, 429):
        return f"HTTP {status}"
    head = (text or "")[:200_000]
    for rx, why in _WALL_MARKERS:
        if rx.search(head):
            return why
    if _LOGIN_URL.search(urlsplit(final_url or "").path or "") and _PASSWORD_FIELD.search(head):
        return "login page"
    return None


# -- walled registry -------------------------------------------------------------------------
WALLED: dict[tuple[str, str], str] = {}
_walled_lock = threading.Lock()


def _ckey(state: str, county: str) -> tuple[str, str]:
    return ((state or "").strip().upper(), (county or "").strip().lower())


def mark_walled(state: str, county: str, reason: str) -> None:
    with _walled_lock:
        if _ckey(state, county) not in WALLED:
            log.warning("sc_rod.walled", state=state, county=county, reason=reason)
        WALLED[_ckey(state, county)] = reason


def walled_reason(state: str, county: str) -> Optional[str]:
    return WALLED.get(_ckey(state, county))


def reset_walled() -> None:
    with _walled_lock:
        WALLED.clear()


# -- per-county lookup budget -----------------------------------------------------------------
class LookupBudget:
    def __init__(self, cap: Optional[int] = None) -> None:
        self.cap = cap if cap is not None else int(
            os.environ.get("SC_ROD_MAX_LOOKUPS_PER_COUNTY", str(DEFAULT_MAX_LOOKUPS)))
        self.used: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def take(self, state: str, county: str) -> bool:
        """Spend one lookup for this county; False once the cap is reached."""
        k = _ckey(state, county)
        with self._lock:
            n = self.used.get(k, 0)
            if n >= self.cap:
                return False
            self.used[k] = n + 1
            return True

    def reset(self) -> None:
        with self._lock:
            self.used.clear()


BUDGET = LookupBudget()


# -- the paced session ------------------------------------------------------------------------
_host_last: dict[str, float] = {}
_host_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _host_lock(host: str) -> threading.Lock:
    with _locks_guard:
        lk = _host_locks.get(host)
        if lk is None:
            lk = _host_locks[host] = threading.Lock()
        return lk


class Resp:
    """The parts of a response the adapters read (no body is kept beyond the call)."""

    def __init__(self, status: int, url: str, text: str, headers: dict | None = None) -> None:
        self.status_code = status
        self.url = url
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        import json
        return json.loads(self.text)


class PoliteSession:
    """One cookie jar, paced per host, wall-checked on every response.

    `session` is anything with .request(method, url, **kw) returning an object with
    status_code, url, text and headers (requests.Session by default; tests pass a fake).
    """

    def __init__(self, *, session: Any = None, min_gap_s: float = MIN_GAP_S, timeout: float = 45.0,
                 sleep: Optional[Callable[[float], None]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if session is None:
            import requests
            session = requests.Session()
            session.headers.update(HEADERS)
        self.s = session
        self.min_gap_s = min_gap_s
        self.timeout = timeout
        self._sleep, self._clock = sleep, clock
        self.requests = 0

    def pace(self, host: str) -> None:
        last = _host_last.get(host)
        if last is not None:
            wait = self.min_gap_s + random.uniform(0, JITTER_S) - (self._clock() - last)
            if wait > 0:
                (self._sleep or SLEEP)(wait)
        _host_last[host] = self._clock()

    def request(self, method: str, url: str, *, check_wall: bool = True, **kw: Any) -> Resp:
        host = (urlsplit(url).hostname or "").lower()
        with _host_lock(host):
            self.pace(host)
            self.requests += 1
            r = self.s.request(method, url, timeout=self.timeout, **kw)
            _host_last[host] = self._clock()
        resp = Resp(int(getattr(r, "status_code", 0) or 0), str(getattr(r, "url", url) or url),
                    getattr(r, "text", "") or "", dict(getattr(r, "headers", {}) or {}))
        if check_wall:
            why = detect_wall(resp.status_code, resp.url, resp.text)
            if why:
                raise RodWalled(url, why)
        return resp

    def get(self, url: str, **kw: Any) -> Resp:
        return self.request("GET", url, **kw)

    def post(self, url: str, data: Any = None, **kw: Any) -> Resp:
        return self.request("POST", url, data=data, **kw)


def pace_host(host: str, *, min_gap_s: float = MIN_GAP_S, sleep: Optional[Callable[[float], None]] = None,
              clock: Callable[[], float] = time.monotonic) -> threading.Lock:
    """Wait out the gap for `host` and return its lock ALREADY HELD; the caller releases it after
    its request. For transports that are not a PoliteSession (the PublicSearch WebSocket)."""
    lk = _host_lock(host)
    lk.acquire()
    last = _host_last.get(host)
    if last is not None:
        wait = min_gap_s + random.uniform(0, JITTER_S) - (clock() - last)
        if wait > 0:
            (sleep or SLEEP)(wait)
    _host_last[host] = clock()
    return lk


def done_host(host: str, lk: threading.Lock, clock: Callable[[], float] = time.monotonic) -> None:
    _host_last[host] = clock()
    lk.release()
