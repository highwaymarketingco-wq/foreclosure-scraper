"""enrichment_dnc: the national-registry and company-list scrub (audit 2026-10-09, unwired_enrichers).

Every list file is a made-up one in tmp_path; every phone is a 555 number; nothing reads data/."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

import foreclosure_scraper.enrichment_dnc as D
from foreclosure_scraper.call_ready import dnc_status
from foreclosure_scraper.models import Listing

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
A, B, C = "8285550101", "8285550102", "8645550103"


def _li(*phones, owner_src="county_published", **raw) -> Listing:
    r = dict(raw)
    if phones:
        r["owner_phone"] = {"phone": phones[0], "source": owner_src, "match": "parcel_id"}
        if len(phones) > 1:
            r["skip_trace"] = {"phone_numbers": list(phones[1:])}
    return Listing(source="test", source_url="https://example.com/x", state="NC", county="Polk",
                   owner_name="ROE RICHARD", street_address="1 Elm St", raw=r)


@pytest.fixture
def lists(tmp_path, monkeypatch):
    """No registry, no company list, until a test writes one."""
    monkeypatch.setattr(D, "_DNC_SET", None)
    monkeypatch.setattr(D, "_INTERNAL_SET", None)
    monkeypatch.setattr(D, "_DNC_PATH", tmp_path / "dnc_registry.csv")
    monkeypatch.setattr(D, "_INTERNAL_PATH", tmp_path / "internal_dnc.csv")
    monkeypatch.setattr(D, "MIN_REGISTRY_NUMBERS", 2)

    class L:
        def registry(self, *lines, name=None):
            p = (tmp_path / "dnc_registry" / name) if name else (tmp_path / "dnc_registry.csv")
            p.parent.mkdir(exist_ok=True)
            p.write_text("\n".join(lines) + "\n")
            return p

        def internal(self, *lines):
            (tmp_path / "internal_dnc.csv").write_text("\n".join(lines) + "\n")
    return L()


def _status(li, phone=A):
    return {e["phone"]: e["dnc_status"] for e in li.raw["dnc_scrub"]}[phone]


def test_no_file_everything_stays_unverified(lists):
    li = _li(A, B)
    s = D.enrich_dnc_scrub([li], now=NOW)
    assert {e["dnc_status"] for e in li.raw["dnc_scrub"]} == {"unverified"}
    assert s["unverified"] == 2 and s["registry_files"] == 0 and not s["registry_complete"]
    snap = copy.deepcopy(li.raw)
    D.enrich_dnc_scrub([li], now=NOW + timedelta(days=1))        # still no file: nothing moves
    assert li.raw == snap


def test_second_call_without_a_file_never_clears(lists):
    """The old loader cached 'no file' as an EMPTY registry: the second call scrubbed every new
    phone clear."""
    D.enrich_dnc_scrub([_li(A)], now=NOW)
    li = _li(B)
    D.enrich_dnc_scrub([li], now=NOW)
    assert _status(li, B) == "unverified"


def test_registry_clear_and_on_registry_and_the_two_column_form(lists):
    lists.registry("828,5550101", "8645559999", "828,5550777")
    li = _li(A, B)
    s = D.enrich_dnc_scrub([li], now=NOW)
    assert _status(li, A) == "on_registry" and _status(li, B) == "clear"
    e = {x["phone"]: x for x in li.raw["dnc_scrub"]}
    assert e[A]["dnc_registered"] is True and e[B]["dnc_registered"] is False
    assert e[B]["registry_as_of"] and e[B]["scrubbed_at"].startswith("2026-10-09")
    assert s["registry_complete"] and s["registry_numbers"] == 3


def test_unverified_is_rescrubbed_when_the_registry_arrives(lists):
    li = _li(A, B)
    D.enrich_dnc_scrub([li], now=NOW)
    lists.registry(A, "8645559999")
    D.enrich_dnc_scrub([li], now=NOW + timedelta(hours=1))
    assert _status(li, A) == "on_registry" and _status(li, B) == "clear"


def test_clear_expires_after_31_days_and_is_rescrubbed(lists):
    lists.registry("8645559999", "8645559998")
    li = _li(B)
    D.enrich_dnc_scrub([li], now=NOW)
    first = li.raw["dnc_scrub"][0]["scrubbed_at"]
    D.enrich_dnc_scrub([li], now=NOW + timedelta(days=30))       # inside 31 days: kept as it is
    assert li.raw["dnc_scrub"][0]["scrubbed_at"] == first
    D.enrich_dnc_scrub([li], now=NOW + timedelta(days=32))       # older: a fresh answer
    assert li.raw["dnc_scrub"][0]["scrubbed_at"] != first and _status(li, B) == "clear"


def test_an_old_clear_with_no_registry_left_becomes_unverified(lists):
    p = lists.registry("8645559999", "8645559998")
    li = _li(B)
    D.enrich_dnc_scrub([li], now=NOW)
    p.unlink()
    D.enrich_dnc_scrub([li], now=NOW + timedelta(days=10))
    assert _status(li, B) == "clear"
    D.enrich_dnc_scrub([li], now=NOW + timedelta(days=40))
    assert _status(li, B) == "unverified"
    # and call_ready reads an expired clear as not scrubbed, whatever the entry says
    li.raw["dnc_scrub"][0].update(dnc_status="clear", dnc_registered=False,
                                  scrubbed_at=(NOW - timedelta(days=45)).isoformat())
    assert dnc_status(li.raw, B, now=NOW) == "unverified"


def test_a_new_registry_file_rescrubs(lists, tmp_path):
    import os
    p = lists.registry("8645559999", "8645559998")
    li = _li(A)
    D.enrich_dnc_scrub([li], now=NOW)
    assert _status(li) == "clear"
    p.write_text(f"{A}\n8645559999\n")
    os.utime(p, (NOW.timestamp() + 86400 * 3,) * 2)
    D.enrich_dnc_scrub([li], now=NOW + timedelta(days=3))
    assert _status(li) == "on_registry"


def test_company_list_always_applies_and_wins(lists):
    lists.internal("name,phone", f"x,({A[:3]}) {A[3:6]}-{A[6:]}")
    li = _li(A, B)
    D.enrich_dnc_scrub([li], now=NOW)                             # no registry: B unverified
    assert _status(li, A) == "on_internal_dnc" and _status(li, B) == "unverified"
    lists.registry("8645559999", "8645559998")
    D.enrich_dnc_scrub([li], now=NOW + timedelta(hours=1))
    assert _status(li, A) == "on_internal_dnc" and _status(li, B) == "clear"
    lists.internal(B)                                             # a new request: no 31-day wait
    D.enrich_dnc_scrub([li], now=NOW + timedelta(hours=2))
    assert _status(li, B) == "on_internal_dnc" and _status(li, A) == "clear"


def test_a_cut_short_read_never_proves_clear(lists):
    lists.registry(*[f"86455{i:05d}" for i in range(10)], B)
    li = _li(A)
    s = D.enrich_dnc_scrub([li], now=NOW, max_seconds=-1)
    assert not s["registry_complete"] and _status(li) == "unverified"


def test_a_too_small_registry_is_not_a_registry(lists, monkeypatch):
    monkeypatch.setattr(D, "MIN_REGISTRY_NUMBERS", 1000)
    lists.registry("8645559999")
    li = _li(A)
    D.enrich_dnc_scrub([li], now=NOW)
    assert _status(li) == "unverified"


def test_change_file_deletions_and_folder_files(lists):
    lists.registry("828,5550101,D,20261001", "8645559999", name="828.csv")
    lists.registry("864,5550103", "8645559998", name="864.txt")
    li = _li(A, C)
    D.enrich_dnc_scrub([li], now=NOW)
    assert _status(li, A) == "clear" and _status(li, C) == "on_registry"


def test_blocked_phones_stay_blocked_and_legacy_registered_is_renamed(lists):
    lists.registry("8645559999", "8645559998")
    walled = _li(A, owner_src="free_people_search")
    legacy = _li(B, dnc_scrub=[{"phone": B, "dnc_registered": True, "dnc_status": "registered"}])
    D.enrich_dnc_scrub([walled, legacy], now=NOW)
    assert _status(walled) == "do_not_dial"
    assert _status(legacy, B) == "clear"          # legacy entry had no date: re-scrubbed


def test_idempotent_and_drops_scrubs_of_gone_phones(lists):
    lists.registry(A, "8645559999")
    li = _li(A, B)
    D.enrich_dnc_scrub([li], now=NOW)
    snap = copy.deepcopy(li.raw["dnc_scrub"])
    D.enrich_dnc_scrub([li], now=NOW + timedelta(days=2))
    assert li.raw["dnc_scrub"] == snap
    del li.raw["skip_trace"]
    D.enrich_dnc_scrub([li], now=NOW + timedelta(days=2))
    assert [e["phone"] for e in li.raw["dnc_scrub"]] == [A]
    del li.raw["owner_phone"]
    D.enrich_dnc_scrub([li], now=NOW + timedelta(days=2))
    assert "dnc_scrub" not in li.raw


def test_numbers_in_line():
    assert D.numbers_in_line("8285550101") == ["8285550101"]
    assert D.numbers_in_line("828,5550101") == ["8285550101"]
    assert D.numbers_in_line("1-828-555-0101") == ["8285550101"]
    assert D.numbers_in_line("828,5550101,D,2026-10-01") == []
    assert D.numbers_in_line("area_code,phone_number") == []
