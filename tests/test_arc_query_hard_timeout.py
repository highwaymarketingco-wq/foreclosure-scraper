"""Regression tests for the 2026-09-30 ArcGIS-query hang + SIGINT hardening.

Incident: scripts/resolver_backfill_parcel.py wedged on a real ArcGIS host —
chunk 2 stalled with a TCP connection sitting ESTABLISHED, unchanged, for
4.5+ minutes, well past the module's own documented worst case (25s timeout x
3 tenacity retries ~= 80-160s). SIGINT did not produce a clean shutdown even
after 18s; SIGTERM was needed.

Root cause (verified against the installed httpcore 1.0.9 source —
`httpcore/_async/http11.py`'s `_receive_event`/`_receive_response_body` issue
a FRESH `network_stream.read(timeout=...)` for every chunk of a response):
httpx's `timeout=` (and a client-level `httpx.Timeout`) bounds each
individual connect/write/read *operation*, not the total request. A peer
that answers slowly enough to keep resetting that per-operation clock —
without ever finishing — defeats the configured timeout with no exception
ever raised, no matter how long it runs. `enrichment_parcel_from_geo._arc_query`
now wraps every attempt in `asyncio.wait_for()`, a backstop that doesn't care
what httpx's own bookkeeping thinks is happening.

Separately, `http_client.install_hard_sigint_kill()` makes the owning process
killable by SIGINT within a beat regardless of what is wedged inside
asyncio/httpx (Python's default SIGINT handling needs the interpreter to
unwind cleanly through whatever is hung; this handler skips that entirely and
exits at the OS level).

These tests spin up a tiny local TCP server that answers with a valid HTTP/1.1
response trickled one byte at a time — the same shape as the diagnosed
incident (a connection that looks perfectly healthy to httpx the whole time) —
and prove the fix against it.
"""
from __future__ import annotations

import asyncio
import contextlib
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from foreclosure_scraper.enrichment_parcel_from_geo import _arc_query
from foreclosure_scraper.http_client import client

SRC = str(Path(__file__).resolve().parent.parent / "src")


async def _start_trickle_server(body: bytes, *, byte_delay: float):
    """A raw TCP server that answers every connection with a valid HTTP/1.1 200
    JSON response sent ONE BYTE AT A TIME, `byte_delay` seconds apart, however
    long that takes. From httpx's point of view the connection is always making
    forward progress (each read call the client issues eventually gets its
    byte), so a naive per-operation read timeout longer than `byte_delay` is
    never tripped — exactly the diagnosed failure shape."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break
            header = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n"
            )
            writer.write(header)
            await writer.drain()
            for byte in body:
                writer.write(bytes([byte]))
                await writer.drain()
                await asyncio.sleep(byte_delay)
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError, OSError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


@pytest.mark.asyncio
async def test_arc_query_hard_timeout_cuts_off_a_trickling_host():
    """_arc_query must not hang past its `hard_timeout` x 3-retries budget even
    against a host that never stops answering just slowly enough to dodge a
    naive per-chunk read timeout."""
    server = await _start_trickle_server(b'{"features": []}', byte_delay=2.0)
    host, port = server.sockets[0].getsockname()[:2]
    try:
        async with client(timeout=60.0) as c:
            t0 = time.monotonic()
            # hard_timeout well under byte_delay: every attempt must be cut off
            # by asyncio.wait_for before even the first trickled byte lands.
            result = await _arc_query(
                c, f"http://{host}:{port}/query", {"f": "json"}, hard_timeout=0.4
            )
            elapsed = time.monotonic() - t0
    finally:
        server.close()
        await server.wait_closed()

    assert result is None  # a hard-timeout trip is a clean failure, not a crash
    # 3 attempts x 0.4s + tenacity's exponential-jitter backoff between them
    # (initial=1, max=8) is a few seconds — nowhere near the minutes-long hang
    # this reproduces the shape of.
    assert elapsed < 15.0, f"expected a bounded failure, took {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_raw_httpx_timeout_does_not_bound_a_trickling_response():
    """Diagnostic proof of the actual root cause, independent of this
    codebase's own retry/backstop code: a bare httpx client configured with a
    1s timeout still SUCCEEDS reading a response that takes several seconds to
    arrive, because each individual read gets its own fresh 1s budget. If this
    assertion ever starts failing (i.e. httpx raises ReadTimeout here), the
    upstream library's timeout semantics changed and `_arc_query`'s
    asyncio.wait_for backstop is doing double duty rather than covering a real
    gap — worth re-reading before deleting it."""
    body = b'{"features": []}'  # 17 bytes
    server = await _start_trickle_server(body, byte_delay=0.3)
    host, port = server.sockets[0].getsockname()[:2]
    try:
        async with client(timeout=1.0) as c:  # a 1s timeout...
            t0 = time.monotonic()
            r = await c.get(f"http://{host}:{port}/query")  # ...against a ~5s trickle
            elapsed = time.monotonic() - t0
    finally:
        server.close()
        await server.wait_closed()

    assert r.status_code == 200
    assert r.content == body
    # The whole response took much longer than the configured "timeout" —
    # proof the timeout is per-operation, not a total-request bound.
    assert elapsed > 1.0


@pytest.mark.asyncio
async def test_sigint_kills_a_wedged_process_within_a_few_seconds(tmp_path):
    """A process that installs install_hard_sigint_kill() and then wedges on a
    real (never-completing-fast-enough) network read must still exit within a
    few seconds of SIGINT — the exact gap the 2026-09-30 incident found (SIGINT
    did not work even after 18s; SIGTERM was needed)."""
    server = await _start_trickle_server(b'{"features": []}', byte_delay=5.0)
    host, port = server.sockets[0].getsockname()[:2]
    try:
        script = tmp_path / "hung_worker.py"
        script.write_text(textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {SRC!r})
            import asyncio
            from foreclosure_scraper.http_client import client, install_hard_sigint_kill

            install_hard_sigint_kill(reason="test_sigint_kills_a_wedged_process")

            async def hang():
                # A generous 120s client-level timeout: without the SIGINT
                # handler, only SIGTERM/SIGKILL (or waiting out the full 120s)
                # would stop this — the real incident's shape.
                async with client(timeout=120.0) as c:
                    await c.get("http://{host}:{port}/query")

            asyncio.run(hang())
        """))
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            # Let it actually connect and start waiting on the trickle.
            await asyncio.sleep(1.0)
            assert proc.poll() is None, "worker exited before we could test SIGINT on it"

            proc.send_signal(signal.SIGINT)
            t0 = time.monotonic()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
                pytest.fail("process did not exit within 5s of SIGINT — the "
                            "2026-09-30 regression (SIGTERM required) is back")
            elapsed = time.monotonic() - t0
            assert elapsed < 5.0, f"SIGINT took {elapsed:.1f}s to take effect"
            assert proc.returncode == 130
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5.0)
    finally:
        server.close()
        await server.wait_closed()
