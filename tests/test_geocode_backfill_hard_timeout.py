"""Regression tests for the 2026-09-30 audit of resolver_backfill_geocode.py's
Census batch-geocoder POST for the same hang class fixed tonight in
resolver_backfill_parcel.py (commit 02a67221, see
tests/test_arc_query_hard_timeout.py).

Incident being guarded against (not yet observed in production for THIS
script, unlike the ArcGIS one -- this is a pre-emptive audit): the script's
only network call is a synchronous `httpx.post(CENSUS_BATCH_URL, ...,
timeout=180.0)` in `geocode_batch_census()`. httpx 0.28.1 / httpcore 1.0.9
(same versions as the ArcGIS incident) turn a single float `timeout=` into
`httpx.Timeout(180.0)`, which bounds each individual connect/write/read
*operation*, not the total request -- httpcore issues a fresh
`read(timeout=...)` for every chunk of the response body, so a peer that
trickles bytes slowly enough (or just often enough to keep resetting that
per-chunk clock) never trips it, no matter how long the request actually
takes. Identical mechanism to the ArcGIS bug, on the sync transport instead
of the async one.

Fix: `_post_with_hard_timeout()` runs the blocking `httpx.post()` on a daemon
thread and bounds the WAIT with `Thread.join(hard_timeout)` -- this script is
synchronous (no asyncio event loop), so there's no `asyncio.wait_for()` to
reach for; a joined daemon thread is the equivalent backstop.

These tests spin up a tiny local TCP server that answers with a valid
HTTP/1.1 response trickled one byte at a time (same shape as
test_arc_query_hard_timeout.py's async trickle server, ported to a plain
`socket`/`threading` server since this script has no event loop) and prove
the fix against it, plus empirically verify SIGINT behavior against the real
(synchronous, no custom signal handler) code path -- per the audit's
requirement to test rather than assume Python's default SIGINT handling is
sufficient here.
"""
from __future__ import annotations

import contextlib
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = str(REPO / "src")
SCRIPTS = str(REPO / "scripts")


def _start_trickle_server(body: bytes, *, byte_delay: float):
    """A raw TCP server that answers every connection with a valid HTTP/1.1
    200 response, sent ONE BYTE AT A TIME, `byte_delay` seconds apart. From
    httpx's point of view the connection is always making forward progress
    (each read eventually gets its byte), so a per-operation read timeout
    longer than `byte_delay` is never tripped -- the diagnosed failure shape.

    Doesn't bother reading/parsing the incoming request: the test POSTs are
    tiny (well under OS socket buffer size), so the client's writes complete
    without the server needing to drain them, and this test is about
    bounding a slow *response* read, the same thing the real incident hit.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(30)
    host, port = srv.getsockname()

    def _serve_one() -> None:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        try:
            header = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/csv\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n"
            )
            conn.sendall(header)
            for byte in body:
                conn.sendall(bytes([byte]))
                time.sleep(byte_delay)
        except OSError:
            pass
        finally:
            with contextlib.suppress(Exception):
                conn.close()

    t = threading.Thread(target=_serve_one, daemon=True)
    t.start()
    return srv, host, port


@pytest.fixture(autouse=True)
def _repo_src_on_path():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, SCRIPTS)
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    yield


def test_raw_httpx_post_timeout_does_not_bound_a_trickling_response():
    """Diagnostic proof of the actual root cause, independent of this
    codebase's own fix: a bare httpx.post() configured with a 1s timeout
    still SUCCEEDS reading a response that takes several seconds to arrive,
    because each individual read gets its own fresh 1s budget. If this
    assertion ever starts failing (httpx raises ReadTimeout here), the
    upstream library's timeout semantics changed and
    _post_with_hard_timeout() is doing double duty rather than covering a
    real gap -- worth re-reading before deleting it."""
    import httpx

    body = b"x" * 20  # 20 bytes
    srv, host, port = _start_trickle_server(body, byte_delay=0.3)  # ~6s total
    try:
        t0 = time.monotonic()
        r = httpx.post(f"http://{host}:{port}/", data={"a": "b"}, timeout=1.0)
        elapsed = time.monotonic() - t0
    finally:
        srv.close()

    assert r.status_code == 200
    assert r.content == body
    # The whole response took much longer than the configured "timeout" --
    # proof the timeout is per-operation, not a total-request bound.
    assert elapsed > 1.0, f"expected the per-op timeout to be defeated, took only {elapsed:.2f}s"


def test_post_with_hard_timeout_cuts_off_a_trickling_host():
    """_post_with_hard_timeout must not hang past `hard_timeout` even against
    a host that never stops answering, just slowly enough to dodge httpx's
    own per-operation timeout."""
    from resolver_backfill_geocode import _post_with_hard_timeout

    body = b"x" * 50
    srv, host, port = _start_trickle_server(body, byte_delay=2.0)  # 100s total
    try:
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            _post_with_hard_timeout(
                f"http://{host}:{port}/", data={"a": "b"}, files={},
                timeout=180.0, hard_timeout=1.0,
            )
        elapsed = time.monotonic() - t0
    finally:
        srv.close()

    # Cut off at ~1s (hard_timeout), nowhere near the 100s trickle or the
    # 180s per-operation httpx timeout that would otherwise never fire.
    assert elapsed < 5.0, f"expected a bounded failure near hard_timeout=1.0s, took {elapsed:.1f}s"


def test_geocode_batch_census_stays_bounded_against_a_trickling_host():
    """End-to-end: geocode_batch_census() (the actual call site) against a
    trickling peer returns an empty match dict within a bounded time instead
    of hanging, with CENSUS_HARD_TIMEOUT_S patched down so the test doesn't
    wait out the real 240s default."""
    import resolver_backfill_geocode as mod

    body = b"x" * 50
    srv, host, port = _start_trickle_server(body, byte_delay=2.0)
    old_url, old_hard = mod.CENSUS_BATCH_URL, mod.CENSUS_HARD_TIMEOUT_S
    mod.CENSUS_BATCH_URL = f"http://{host}:{port}/"
    mod.CENSUS_HARD_TIMEOUT_S = 1.0
    try:
        t0 = time.monotonic()
        results = mod.geocode_batch_census(["123 Main St, Asheville, NC 28801"])
        elapsed = time.monotonic() - t0
    finally:
        srv.close()
        mod.CENSUS_BATCH_URL = old_url
        mod.CENSUS_HARD_TIMEOUT_S = old_hard

    assert results == {}  # bounded failure, not a crash, not a hang
    assert elapsed < 5.0, f"expected a bounded failure near hard_timeout=1.0s, took {elapsed:.1f}s"


def test_sigint_kills_a_hung_sync_census_call_within_a_few_seconds(tmp_path):
    """Empirical check (per the audit's instruction to test, not assume):
    this script installs no custom SIGINT handler and has no bare `except:`
    that could swallow KeyboardInterrupt. Confirm a real invocation of
    geocode_batch_census() -- the actual shipped code path, thread-join and
    all -- blocked against a trickling peer is still interrupted by SIGINT
    within a few seconds, using a long hard_timeout so the hard-timeout
    backstop itself can't be what stops it (this test is about signal
    delivery, not the wall-clock fix above)."""
    srv, host, port = _start_trickle_server(b"x" * 50, byte_delay=5.0)  # 250s total
    try:
        script = tmp_path / "hung_geocode_worker.py"
        script.write_text(textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {SCRIPTS!r})
            import resolver_backfill_geocode as mod

            mod.CENSUS_BATCH_URL = "http://{host}:{port}/"
            # Long enough that ONLY a SIGINT (not the hard-timeout backstop)
            # can end this run within the test's own wait window.
            mod.CENSUS_HARD_TIMEOUT_S = 120.0
            mod.geocode_batch_census(["123 Main St, Asheville, NC 28801"])
            print("UNEXPECTED: returned without being interrupted")
        """))
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            time.sleep(1.0)  # let it connect and start the trickle read
            assert proc.poll() is None, "worker exited before we could test SIGINT on it"

            proc.send_signal(signal.SIGINT)
            t0 = time.monotonic()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
                pytest.fail(
                    "process did not exit within 5s of SIGINT -- default "
                    "Python SIGINT handling is NOT sufficient for this "
                    "script's synchronous httpx.post()+thread.join() call "
                    "path; needs an install_hard_sigint_kill()-style fix"
                )
            elapsed = time.monotonic() - t0
            assert elapsed < 5.0, f"SIGINT took {elapsed:.1f}s to take effect"
            assert proc.returncode != 0  # interrupted, not a clean exit
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5.0)
    finally:
        srv.close()
