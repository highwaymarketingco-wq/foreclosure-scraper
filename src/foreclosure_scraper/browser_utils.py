"""Shared browser-startup helpers for nodriver (undetected Chrome).

Centralises the browser-executable detection so every call site benefits
from the same fallback chain instead of each one hard-coding a path that
only works on a dev Mac.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

__all__ = ["start_browser"]


def _ensure_display() -> None:
    """On Linux without a DISPLAY, start Xvfb so headed Chrome works.

    sc_public_index and other WAF-protected sites require headless=False
    Chrome. On a headless server (no X server), this auto-starts Xvfb.
    """
    if os.name != "posix" or not shutil.which("Xvfb"):
        return
    if os.environ.get("DISPLAY"):
        return
    # Check if Xvfb is already running on :99
    try:
        result = subprocess.run(
            ["pgrep", "-f", "Xvfb :99"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            os.environ["DISPLAY"] = ":99"
            return
    except Exception:
        pass
    # Start Xvfb
    try:
        subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "1920x1080x24"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = ":99"
    except Exception:
        pass


def _find_chrome_binary() -> str | None:
    """Return the first Chrome/Chromium binary that exists on this machine."""
    # Explicit env override always wins.
    env_path = os.environ.get("CHROME_BINARY")
    if env_path and os.path.isfile(env_path):
        return env_path

    candidates = [
        "/snap/bin/chromium",            # Ubuntu snap (VM)
        "/usr/bin/chromium-browser",     # Ubuntu wrapper
        "/usr/bin/google-chrome",
        "/usr/bin/chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    # Last resort: PATH lookup
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
        found = shutil.which(name)
        if found:
            return found

    return None


async def start_browser(headless: bool = True, **extra: Any):
    """Start nodriver with automatic browser-path and sandbox detection.

    Wraps ``nodriver.start()`` so every caller gets the right
    ``browser_executable_path`` and ``sandbox=False`` on Linux/snap without
    having to know those details.

    Parameters
    ----------
    headless : bool
        Forwarded to ``nodriver.start()``.
    **extra
        Additional keyword arguments forwarded to ``nodriver.start()``.
    """
    import nodriver as uc

    # On Linux servers, ensure a virtual display for headed Chrome.
    if not headless:
        _ensure_display()

    kwargs: dict[str, Any] = {"headless": headless}

    chrome_path = _find_chrome_binary()
    if chrome_path:
        kwargs["browser_executable_path"] = chrome_path

    # On snap Chromium, sandbox doesn't work (no access to kernel namespaces).
    # Detect snap and disable sandbox.  Also disable when running as root.
    is_snap = chrome_path is not None and "snap" in (chrome_path or "")
    is_root = os.geteuid() == 0 if hasattr(os, "geteuid") else False
    if is_snap or is_root:
        kwargs["sandbox"] = False

    kwargs.update(extra)
    return await uc.start(**kwargs)
