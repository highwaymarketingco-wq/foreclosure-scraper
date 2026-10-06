"""verification.ledger: merge rules, TTL/version due logic, re-keying, atomic save/load."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import ledger as L
from foreclosure_scraper.verification.registry import Verifier

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
ROW = {"state": "NC", "county": "Buncombe", "parcel_id": "877295969900000",
       "street_address": "98 Turner Cove Rd", "listing_type": "tax_lien", "owner_name": "FLORES JESUS"}


def _res(verdict, at, version="v1", verifier="tax_lien_buncombe", **ev):
    return core.result("tax_lien", verdict, ev, source="s", version=version, verifier=verifier, now=at)


def _verifier(version="v1", ttl=30, retry=7):
    async def verify(row, client):  # pragma: no cover - never called here
        raise AssertionError
    return Verifier(name="tax_lien_buncombe", signal="tax_lien", version=version, ttl_days=ttl,
                    applies=lambda r: True, verify=verify, retry_days=retry)


def test_first_answer_becomes_latest_with_keys_and_row_summary():
    led = L.Ledger("tax_lien")
    e = led.record(ROW, _res("confirmed", T0, total=12.0), ttl_days=30, governs=("tax_lien",), now=T0)
    key = core.row_key(ROW)
    assert led.rows[key] is e
    assert e["latest"]["verdict"] == "confirmed" and e["latest"]["evidence"] == {"total": 12.0}
    assert e["keys"][0] == key and any(k.startswith("addr:") for k in e["keys"])
    assert e["row"]["parcel_id"] == "877295969900000" and e["governs"] == ["tax_lien"]
    assert e["checks"] == 1 and e["ttl_days"] == 30.0


def test_a_decisive_answer_replaces_and_the_old_one_goes_to_history():
    led = L.Ledger("tax_lien")
    led.record(ROW, _res("confirmed", T0), ttl_days=30, now=T0)
    e = led.record(ROW, _res("refuted", T0 + timedelta(days=31)), ttl_days=30, now=T0 + timedelta(days=31))
    assert e["latest"]["verdict"] == "refuted"
    assert e["history"][0]["verdict"] == "confirmed" and "evidence" not in e["history"][0]
    assert e["checks"] == 2


def test_a_flaky_page_never_erases_a_fresh_verdict():
    led = L.Ledger("tax_lien")
    led.record(ROW, _res("refuted", T0), ttl_days=30, now=T0)
    t = T0 + timedelta(days=2)
    e = led.record(ROW, _res("unconfirmed", t, reason="fetch_failed"), ttl_days=30, now=t)
    assert e["latest"]["verdict"] == "refuted"
    assert e["last_attempt"] == {"verdict": "unconfirmed", "checked_at": core.iso_z(t)}
    assert e["history"][0]["verdict"] == "unconfirmed"


def test_a_non_decisive_answer_replaces_an_expired_or_old_version_verdict():
    led = L.Ledger("tax_lien")
    led.record(ROW, _res("refuted", T0), ttl_days=30, now=T0)
    t = T0 + timedelta(days=40)
    assert led.record(ROW, _res("unconfirmed", t), ttl_days=30, now=t)["latest"]["verdict"] == "unconfirmed"
    led2 = L.Ledger("tax_lien")
    led2.record(ROW, _res("refuted", T0), ttl_days=30, now=T0)
    e = led2.record(ROW, _res("wall", T0 + timedelta(days=1), version="v2"), ttl_days=30,
                    now=T0 + timedelta(days=1))
    assert e["latest"]["verdict"] == "wall"


def test_history_is_bounded():
    led = L.Ledger("tax_lien")
    for i in range(20):
        t = T0 + timedelta(days=31 * i)
        e = led.record(ROW, _res("confirmed" if i % 2 else "refuted", t), ttl_days=30, now=t)
    assert len(e["history"]) == L.HISTORY_MAX
    assert e["checks"] == 20


def test_a_backfilled_parcel_rekeys_the_same_entry_instead_of_duplicating_it():
    before = {k: v for k, v in ROW.items() if k != "parcel_id"}
    led = L.Ledger("tax_lien")
    led.record(before, _res("confirmed", T0), ttl_days=30, now=T0)
    assert list(led.rows) == [core.row_key(before)]
    t = T0 + timedelta(days=31)
    led.record(ROW, _res("refuted", t), ttl_days=30, now=t)
    assert list(led.rows) == [core.row_key(ROW)]          # one entry, now under the parcel key
    e = led.rows[core.row_key(ROW)]
    assert e["history"][0]["verdict"] == "confirmed"
    assert led.find(core.row_keys(before))[1] is e        # still found by the address


def test_a_key_two_entries_claim_identifies_neither():
    led = L.Ledger("tax_lien", {
        "parcel:NC:buncombe:1": {"keys": ["parcel:NC:buncombe:1", "addr:NC:buncombe:5 main st"],
                                 "latest": {"verdict": "confirmed"}},
        "parcel:NC:buncombe:2": {"keys": ["parcel:NC:buncombe:2", "addr:NC:buncombe:5 main st"],
                                 "latest": {"verdict": "refuted"}}})
    assert led.find(["addr:NC:buncombe:5 main st"]) == (None, None)
    assert led.find(["parcel:NC:buncombe:2"])[1]["latest"]["verdict"] == "refuted"


def test_wrong_signal_is_refused():
    with pytest.raises(ValueError):
        L.Ledger("probate").record(ROW, _res("confirmed", T0))


def test_merge_never_loses_entries_and_the_better_latest_wins():
    a, b = L.Ledger("tax_lien"), L.Ledger("tax_lien")
    other = dict(ROW, parcel_id="964912345600000", street_address="5 Main St")
    a.record(ROW, _res("confirmed", T0), ttl_days=30, now=T0)
    b.record(ROW, _res("refuted", T0 + timedelta(days=31)), ttl_days=30, now=T0 + timedelta(days=31))
    b.record(other, _res("confirmed", T0), ttl_days=30, now=T0)
    a.record(other, _res("unconfirmed", T0 + timedelta(days=60)), ttl_days=30, now=T0 + timedelta(days=60))
    a.merge_from(b)
    assert len(a.rows) == 2
    assert a.rows[core.row_key(ROW)]["latest"]["verdict"] == "refuted"          # newer decisive
    assert a.rows[core.row_key(other)]["latest"]["verdict"] == "confirmed"      # decisive > unconfirmed
    assert {h["verdict"] for h in a.rows[core.row_key(ROW)]["history"]} == {"confirmed"}


def test_save_is_atomic_one_entry_per_line_and_round_trips(tmp_path):
    led = L.Ledger("tax_lien")
    led.record(ROW, _res("confirmed", T0, total=1.5), ttl_days=30, governs=("tax_lien",), now=T0)
    led.last_run = {"at": "x"}
    p = led.save(tmp_path / "tax_lien.json", host="h", now=T0)
    text = p.read_text()
    assert not list(tmp_path.glob("*.tmp"))
    data = json.loads(text)
    assert data["kind"] == "verification_ledger" and data["signal"] == "tax_lien"
    assert data["counts"]["rows"] == 1 and data["counts"]["confirmed"] == 1
    assert sum(1 for line in text.splitlines() if line.startswith('"parcel:')) == 1
    back = L.Ledger.load("tax_lien", tmp_path)
    assert back.rows == json.loads(json.dumps(led.rows)) and back.last_run == {"at": "x"}


def test_missing_file_is_empty_and_a_broken_one_is_refused(tmp_path):
    assert L.Ledger.load("tax_lien", tmp_path).rows == {}
    (tmp_path / "tax_lien.json").write_text("{not json")
    with pytest.raises(L.LedgerUnreadable):
        L.Ledger.load("tax_lien", tmp_path)
    (tmp_path / "x.json").write_text(json.dumps({"kind": "other", "rows": {}}))
    leds, bad = L.load_all(tmp_path)
    assert leds == {} and set(bad) == {"tax_lien.json", "x.json"}


def test_is_due_new_version_ttl_and_retry():
    v = _verifier()
    assert L.is_due(None, v, T0) == (True, "new")
    e = {"latest": _res("confirmed", T0).to_dict()}
    assert L.is_due(e, v, T0 + timedelta(days=29))[0] is False
    assert L.is_due(e, v, T0 + timedelta(days=30)) == (True, "ttl")
    assert L.is_due(e, _verifier(version="v2"), T0 + timedelta(days=1)) == (True, "version")
    u = {"latest": _res("unconfirmed", T0).to_dict()}
    assert L.is_due(u, v, T0 + timedelta(days=6))[0] is False
    assert L.is_due(u, v, T0 + timedelta(days=7)) == (True, "retry")
    other = {"latest": _res("confirmed", T0, verifier="tax_lien_other").to_dict()}
    assert L.is_due(other, v, T0 + timedelta(days=1)) == (True, "version")


def test_publish_is_skipped_with_handoff_push_0(monkeypatch, tmp_path):
    monkeypatch.setenv("HANDOFF_PUSH", "0")
    assert L.publish_ledgers([tmp_path / "x.json"], "msg") == ("skipped", "HANDOFF_PUSH=0")


def test_a_shared_address_never_joins_two_different_parcels():
    """The 2026-10-06 recheck: rows on different parcels that share an address key must not
    land in (or re-key) one another's entry."""
    led = L.Ledger("tax_lien")
    a = dict(ROW, parcel_id="111111111100000", street_address="7 Eastwood Rd")
    b = dict(ROW, parcel_id="222222222200000", street_address="7 Eastwood Rd")
    led.record(a, _res("confirmed", T0, pin="a"), ttl_days=30, now=T0)
    assert led.find(core.row_keys(b)) == (None, None)
    led.record(b, _res("refuted", T0, pin="b"), ttl_days=30, now=T0)
    assert len(led.rows) == 2
    assert led.find_row(a)[1]["latest"]["evidence"]["pin"] == "a"
    assert led.find_row(b)[1]["latest"]["evidence"]["pin"] == "b"
    # the address alone (no parcel) is now ambiguous: it identifies neither
    assert led.find(["addr:NC:buncombe:7 eastwood rd"]) == (None, None)
