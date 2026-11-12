"""Smoke tests for the vendored AWS WAF solver port.

These don't talk to AWS — they pin behavior at the surfaces we depend
on so vendor syncs don't silently break us:
  - module imports and webgl.json resolves regardless of cwd
  - `AwsWaf.extract` raises ValueError on non-WAF HTML
  - PoW solvers return correct nonces for tiny difficulty
  - image-grid challenge type is the typed sentinel, not a bare string
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_vendor_imports_resolve_webgl_independent_of_cwd(tmp_path, monkeypatch):
    """fingerprint.py was patched to use __file__ for webgl.json; verify
    it loads when cwd is somewhere unrelated."""
    monkeypatch.chdir(tmp_path)
    # Fresh import to exercise the module-level `with open(...)`.
    import importlib
    import foreclosure_scraper._vendor.awswaf.fingerprint as fp
    importlib.reload(fp)
    assert isinstance(fp.gpus, list) and len(fp.gpus) > 0


def test_extract_rejects_non_waf_html():
    from foreclosure_scraper._vendor.awswaf.aws import AwsWaf
    with pytest.raises(ValueError):
        AwsWaf.extract("<html><body>not a WAF page</body></html>")


def test_extract_parses_valid_waf_payload():
    from foreclosure_scraper._vendor.awswaf.aws import AwsWaf
    html = (
        '<html><script src="https://challenge.us-east-1.captcha.awswaf.com/'
        'someid/challenge.js"></script>'
        '<script>window.gokuProps = {"key":"abc","v":1};</script></html>'
    )
    goku, host = AwsWaf.extract(html)
    assert goku == {"key": "abc", "v": 1}
    assert host == "challenge.us-east-1.captcha.awswaf.com/someid"


def test_hash_pow_finds_low_difficulty_nonce():
    """hash_pow should converge fast at difficulty=4 (any 4-bit prefix zero)."""
    from foreclosure_scraper._vendor.awswaf.verify import hash_pow
    nonce = hash_pow("input123", "checksum456", 4)
    assert nonce is not None
    assert int(nonce) >= 0


def test_challenge_types_map_has_mp_verify_sentinel():
    from foreclosure_scraper._vendor.awswaf.verify import CHALLENGE_TYPES, MP_VERIFY
    sentinels = [v for v in CHALLENGE_TYPES.values() if isinstance(v, str)]
    assert MP_VERIFY in sentinels


def test_unsupported_challenge_error_raised_for_image_grid():
    """build_payload must raise UnsupportedChallengeError when the
    challenge_type maps to the MP_VERIFY sentinel."""
    from foreclosure_scraper._vendor.awswaf.aws import AwsWaf, UnsupportedChallengeError
    waf = AwsWaf(goku_props={"x": 1}, endpoint="host", domain="d.example")
    # find the image-grid challenge-type id
    from foreclosure_scraper._vendor.awswaf.verify import CHALLENGE_TYPES, MP_VERIFY
    mp_id = next(k for k, v in CHALLENGE_TYPES.items() if v == MP_VERIFY)
    inputs = {
        "challenge_type": mp_id,
        "difficulty": 4,
        "challenge": {"input": "x"},
    }
    with pytest.raises(UnsupportedChallengeError):
        waf.build_payload(inputs)


def test_license_present_in_vendor_dir():
    """MIT requires we keep the LICENSE — fail loudly if it ever disappears."""
    lic = Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper" / "_vendor" / "awswaf" / "LICENSE"
    assert lic.exists(), "vendored awswaf LICENSE is missing"
    assert "MIT" in lic.read_text()
