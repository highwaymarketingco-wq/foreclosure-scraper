"""PoliteFetcher: the only way the intake code touches the network.

  * at least MIN_GAP_S (1.6 s) between two requests to the same host, whatever the method;
  * an ordinary desktop-browser User-Agent and Accept headers, nothing else (no TLS
    impersonation, no proxy, no cookie or token obtained any other way than by the site setting
    it on an ordinary page load);
  * every response is logged (fetchlog.jsonl beside the sheet) with its URL, method, status,
    size, sha256 prefix and UTC fetch time, and its body can be saved as an exhibit;
  * a CAPTCHA, a login form or a block page raises Walled. The caller records the step as
    'walled' and moves on. Nothing retries it, solves it or works around it.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlencode, urlsplit

from .model import Exhibit, utc_now

MIN_GAP_S = 1.6
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}

#: Text that marks a challenge, CAPTCHA, login wall or block page. Checked on every response.
_WALL_MARKERS = [
    (re.compile(r"cf-chl|challenge-platform|cdn-cgi/challenge|Just a moment\.\.\.", re.I), "challenge page"),
    # a challenge WIDGET the page presents. A script include alone is not a wall: the Buncombe
    # register loads Google's invisible reCAPTCHA v3 script on every page and presents no challenge.
    (re.compile(r"class=[\"'][^\"']*\b(g-recaptcha|h-captcha|cf-turnstile)\b|recaptcha/api2/anchor|"
                r"I'm not a robot|data-hcaptcha", re.I), "CAPTCHA"),
    (re.compile(r"px-captcha|_Incapsula_Resource|Request unsuccessful\. Incapsula", re.I), "bot-block page"),
    (re.compile(r"<title>\s*(Access Denied|Attention Required|403 Forbidden|Forbidden)\s*</title>", re.I),
     "block page"),
    (re.compile(r"Direct API access is not permitted", re.I), "API access refused"),
]
_LOGIN_URL = re.compile(r"/(log[-_]?in|sign[-_]?in|account/login)\b", re.I)
_PASSWORD_FIELD = re.compile(r"<input[^>]+type=[\"']?password", re.I)


class Walled(RuntimeError):
    """The source answered with a CAPTCHA, a login wall or a block page."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{reason}: {url}")
        self.url = url
        self.reason = reason


def detect_wall(status: int, final_url: str, text: str) -> Optional[str]:
    """Why a response is a wall, or None. Pure, so it is tested on canned bodies."""
    if status in (401, 402, 403, 407, 429):
        return f"HTTP {status}"
    head = text[:200_000] if text else ""
    for rx, why in _WALL_MARKERS:
        if rx.search(head):
            return why
    if _LOGIN_URL.search(urlsplit(final_url or "").path or "") and _PASSWORD_FIELD.search(head):
        return "login page"
    return None


@dataclass
class Response:
    status: int
    url: str
    final_url: str
    text: str
    content: bytes
    fetched: datetime
    sha256: str

    def json(self) -> Any:
        return json.loads(self.text)


class PoliteFetcher:
    def __init__(self, out_dir: Path, *, min_gap_s: float = MIN_GAP_S, timeout: float = 45.0,
                 session_factory: Optional[Callable[[], Any]] = None, sleep=time.sleep,
                 clock=time.monotonic) -> None:
        self.out_dir = Path(out_dir)
        self.exhibit_dir = self.out_dir / "exhibits"
        self.min_gap_s = min_gap_s
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self._sleep, self._clock = sleep, clock
        self._factory = session_factory or self._requests_session
        self.session = self._factory()
        self.requests_by_host: dict[str, int] = {}
        self.log_path = self.out_dir / "fetchlog.jsonl"

    @staticmethod
    def _requests_session() -> Any:
        import requests
        s = requests.Session()
        s.headers.update(HEADERS)
        return s

    def new_session(self) -> Any:
        """A fresh cookie jar (a new guest session on a form site)."""
        return self._factory()

    def _pace(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self.min_gap_s - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()

    def request(self, method: str, url: str, *, params: Optional[dict] = None,
                data: Optional[dict] = None, session: Any = None, tag: str = "",
                check_wall: bool = True) -> Response:
        host = (urlsplit(url).hostname or "").lower()
        self._pace(host)
        self.requests_by_host[host] = self.requests_by_host.get(host, 0) + 1
        ses = session or self.session
        t0 = utc_now()
        full = url + ("?" + urlencode(params) if params else "")
        try:
            r = ses.request(method, url, params=params, data=data, timeout=self.timeout)
            status, content, final = r.status_code, r.content, str(r.url)
            text = r.text
        except Exception as exc:  # noqa: BLE001 - logged, then re-raised to the step
            self._log(dict(url=full, method=method, tag=tag, status=-1, error=f"{type(exc).__name__}: {exc}"[:300],
                           fetched_utc=t0.strftime("%Y-%m-%dT%H:%M:%SZ")))
            raise
        sha = hashlib.sha256(content).hexdigest()
        self._log(dict(url=full, final_url=final, method=method, tag=tag, status=status, bytes=len(content),
                       sha256=sha[:16], fetched_utc=t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       started_utc_ms=t0.isoformat(timespec="milliseconds")))
        resp = Response(status, full, final, text, content, t0, sha)
        if check_wall:
            why = detect_wall(status, final, text)
            if why:
                raise Walled(full, why)
        return resp

    def get(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, data: dict, **kw: Any) -> Response:
        return self.request("POST", url, data=data, **kw)

    def save(self, name: str, content: bytes | str) -> str:
        """Write one exhibit file under exhibits/; returns the name relative to exhibits/."""
        self.exhibit_dir.mkdir(parents=True, exist_ok=True)
        p = self.exhibit_dir / name
        if isinstance(content, str):
            p.write_text(content, encoding="utf-8")
        else:
            p.write_bytes(content)
        return name

    def exhibit(self, ex: Exhibit, resp: Optional[Response], save_as: Optional[str] = None) -> Exhibit:
        """Fill an Exhibit from a response and save its body."""
        if resp is not None:
            ex.fetched, ex.http_status, ex.final_url = resp.fetched, resp.status, resp.final_url
            ex.sha256, ex.nbytes = resp.sha256[:16], len(resp.content)
            if save_as:
                ex.files.append(self.save(save_as, resp.content))
        return ex

    def _log(self, rec: dict) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
