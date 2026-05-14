"""Vendored AWS WAF challenge solver.

Source: https://github.com/xKiian/awswaf (MIT, copyright 2025).
See LICENSE in this directory for the upstream license text.

Local fixes vs upstream:
  - imports converted from absolute `awswaf.x` to package-relative
  - `webgl.json` path resolved via __file__ (was relative `../webgl.json`)
  - the `mp_verify` image-grid challenge type is exposed as a sentinel
    string (upstream left it unimplemented); callers should detect it
    and fall back to a separate image-puzzle solver.

This vendoring sits under _vendor/ so it stays clearly demarcated as
not-our-code. Bump the upstream commit hash in VENDOR.md when syncing.
"""
from .aws import AwsWaf

__all__ = ["AwsWaf"]
