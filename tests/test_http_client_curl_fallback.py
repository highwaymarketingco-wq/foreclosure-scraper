"""The curl fallback must keep request headers (an API token) out of argv, where `ps` shows them.

http_client._curl_fallback_text (used when httpx times out) passed headers as `-H` arguments, so
a CourtListener `Authorization: Token ...` was visible on the command line. Every option now
travels in a config on curl's stdin; argv is exactly CURL_ARGV. Placeholder token values only.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from foreclosure_scraper import http_client as H

TOKEN = "tok-PLACEHOLDER-0123456789abcdef"
HEADERS = {"Authorization": f"Token {TOKEN}", "Accept": "application/json",
           "X-Odd": 'has "quotes" and a \\ backslash'}
PROXY = "http://user:proxy-secret@127.0.0.1:9"
REFERER = "https://referer.example/page?k=referer-secret"
URL = "https://api.example/v4/search/?q=x&key=url-secret"
SECRETS = (TOKEN, "proxy-secret", "referer-secret", "url-secret", "quotes", "application/json")


class _FakeProc:
    def __init__(self, sink: dict):
        self.sink = sink
        self.returncode = 0

    async def communicate(self, data=None):
        self.sink["stdin"] = data
        return b"ok-body", b""

    def kill(self):
        pass


@pytest.fixture
def captured(monkeypatch):
    sink: dict = {}

    async def fake_exec(*argv, **kw):
        sink["argv"] = list(argv)
        sink["kw"] = kw
        return _FakeProc(sink)

    monkeypatch.setattr(H.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setenv("PROXY_URL", PROXY)
    return sink


def test_argv_carries_no_header_value_token_proxy_referer_or_url(captured):
    out = asyncio.run(H._curl_fallback_text(URL, timeout=30, headers=HEADERS, referer=REFERER))
    assert out == "ok-body"
    argv = captured["argv"]
    assert tuple(argv) == H.CURL_ARGV == ("curl", "--config", "-")
    joined = " ".join(argv)
    for secret in SECRETS:
        assert secret not in joined
    for v in HEADERS.values():
        assert v not in joined
    assert H._SESSION_UA not in joined
    assert captured["kw"]["stdin"] is asyncio.subprocess.PIPE
    cfg = captured["stdin"].decode()
    assert f'header = "Authorization: Token {TOKEN}"' in cfg
    assert 'header = "X-Odd: has \\"quotes\\" and a \\\\ backslash"' in cfg
    assert f'proxy = "{PROXY}"' in cfg and f'referer = "{REFERER}"' in cfg
    assert f'url = "{URL}"' in cfg and "max-time = 30" in cfg


def test_config_cannot_be_split_by_a_newline_in_a_value():
    cfg = H.curl_config("https://x.example/", timeout=5,
                        headers={"X-A": "one\nurl = https://evil.example/\r\nx"})
    lines = cfg.splitlines()
    assert sum(1 for ln in lines if ln.startswith("url = ")) == 1
    assert lines[-1] == 'url = "https://x.example/"'


class _Echo(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps({k: v for k, v in self.headers.items()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.mark.skipif(shutil.which("curl") is None, reason="no curl binary")
def test_real_curl_reads_the_stdin_config_and_sends_every_header(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.delenv("PROXY_URL", raising=False)
    real = asyncio.create_subprocess_exec
    seen: list = []

    async def spy(*argv, **kw):
        seen.append(list(argv))
        return await real(*argv, **kw)

    monkeypatch.setattr(H.asyncio, "create_subprocess_exec", spy)
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/echo?key=url-secret"
        got = json.loads(asyncio.run(H._curl_fallback_text(url, timeout=10, headers=HEADERS,
                                                           referer=REFERER)))
    finally:
        srv.shutdown()
    assert got["Authorization"] == f"Token {TOKEN}"
    assert got["X-Odd"] == HEADERS["X-Odd"]
    assert got["Referer"] == REFERER and got["User-Agent"] == H._SESSION_UA
    assert seen == [list(H.CURL_ARGV)]


def test_ingest_script_passes_the_token_on_stdin(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "ingest_courtlistener_bankruptcy.py"
    spec = importlib.util.spec_from_file_location("ingest_cl_bk", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []

    class R:
        stdout = '{"results": []}'

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        return R()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._curl_json(URL, {"Authorization": f"Token {TOKEN}"}) == {"results": []}
    argv, kw = calls[0]
    assert argv == list(H.CURL_ARGV)
    assert all(TOKEN not in a and "url-secret" not in a for a in argv)
    assert f'header = "Authorization: Token {TOKEN}"' in kw["input"]
