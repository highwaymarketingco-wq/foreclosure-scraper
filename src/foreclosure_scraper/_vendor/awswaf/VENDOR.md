# Vendored: AWS WAF Solver

- Upstream: https://github.com/xKiian/awswaf
- License: MIT (see LICENSE in this directory)
- Synced commit: 2026-05-14 (depth=1 clone of `main`)

## What this is
Pure-Python reverse implementation of AWS WAF's invisible/PoW challenge
protocol. Produces an `aws-waf-token` cookie without launching a browser.

## Local patches vs upstream
- Absolute imports (`from awswaf.x import ...`) → package-relative
  (`from .x import ...`) so this works as a Python package, not just
  the upstream's top-level scripts.
- `gpus = json.load(open("../webgl.json"))` → `Path(__file__).parent /
  "webgl.json"` so the import works no matter the cwd.
- `mp_verify` (image-grid CAPTCHA) sentinel now raises a typed
  `UnsupportedChallengeError` from `aws.py`. Upstream had this entry
  point as a literal string in the challenge-type dict that would
  crash with `TypeError: 'str' object is not callable` if served.
- `AwsWaf.extract` raises `ValueError` instead of crashing with
  `IndexError` when the page isn't a WAF challenge.

## How to sync
1. `git clone --depth 1 https://github.com/xKiian/awswaf /tmp/awswaf_src`
2. Diff `/tmp/awswaf_src/python/awswaf/` against this directory.
3. Re-apply the local patches above.
4. Update the synced-commit date.

## Why vendored, not pip-installed
Upstream doesn't ship a pyproject.toml; not on PyPI.
