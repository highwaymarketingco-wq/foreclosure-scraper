"""Shared browser-startup helpers for nodriver (undetected Chrome).

Centralises the browser-executable detection so every call site benefits
from the same fallback chain instead of each one hard-coding a path that
only works on a dev Mac.
"""
from __future__ import annotations

import os
import shutil
from typing import Any

__all__ = ["start_browser"]


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
