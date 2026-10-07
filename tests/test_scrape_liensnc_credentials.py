"""The LiensNC login is never in the repo: it comes from the environment or the private .env file."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scrape_liensnc as sl  # noqa: E402


def _reset(monkeypatch, env_file):
    monkeypatch.setattr(sl, "LIENSNC_USER", "")
    monkeypatch.setattr(sl, "LIENSNC_PASS", "")
    monkeypatch.setattr(sl, "ENV_FILE", env_file)


def test_no_login_anywhere_stops_with_a_clear_message(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path / "missing.env")
    with pytest.raises(SystemExit) as e:
        sl.require_credentials()
    assert "LIENSNC_USER" in str(e.value) and ".env" in str(e.value)


def test_the_private_env_file_supplies_the_login(monkeypatch, tmp_path):
    f = tmp_path / ".env"
    f.write_text('OTHER=1\nLIENSNC_USER="demo-user"\nLIENSNC_PASS=demo-pass\n', encoding="utf-8")
    _reset(monkeypatch, f)
    sl.require_credentials()
    assert sl.LIENSNC_USER == "demo-user" and sl.LIENSNC_PASS == "demo-pass"


def test_the_environment_wins_over_the_env_file(monkeypatch, tmp_path):
    f = tmp_path / ".env"
    f.write_text("LIENSNC_USER=file-user\nLIENSNC_PASS=file-pass\n", encoding="utf-8")
    _reset(monkeypatch, f)
    monkeypatch.setattr(sl, "LIENSNC_USER", "env-user")
    monkeypatch.setattr(sl, "LIENSNC_PASS", "env-pass")
    sl.require_credentials()
    assert (sl.LIENSNC_USER, sl.LIENSNC_PASS) == ("env-user", "env-pass")


def test_no_password_literal_is_committed_in_the_script():
    src = Path(sl.__file__).read_text(encoding="utf-8")
    assert 'environ.get("LIENSNC_PASS", "")' in src and 'environ.get("LIENSNC_USER", "")' in src
