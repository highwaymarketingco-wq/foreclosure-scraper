"""avalon_tax verifier: a request that FAILED must never become the verdict "stale".

Regression for 2026-10-13: a bulk run verified ~3,400 Rutherford parcels; ~590 were answered
normally (93% confirmed), then CloudFront started returning HTTP 403 and the old code stamped the
remaining ~2,840 "stale" (core.py: a stale verdict removes the row's scorer signals).
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.verification.verifiers import avalon_tax as av


class _Resp:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code = status
        self._payload = payload
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(av.time, "sleep", lambda *_: None)
    av._fail_streak = 0
    av._blocked_until = 0.0
    yield
    av._fail_streak = 0
    av._blocked_until = 0.0


def _row(parcel="1010622", addr="1 MAIN ST"):
    return {"parcel_id": parcel, "street_address": addr,
            "source": "counties_nc.rutherford_tax", "listing_type": "tax_lien"}


def _run(row):
    return asyncio.run(av.verify(row))


def _script(monkeypatch, responses):
    """Feed requests.post a fixed sequence; the last response repeats."""
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        i = min(len(calls) - 1, len(responses) - 1)
        r = responses[i]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(av.requests, "post", fake_post)
    return calls


def test_http_403_is_unconfirmed_not_stale(monkeypatch):
    _script(monkeypatch, [_Resp(403)])
    res = _run(_row())
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "fetch_failed"


def test_network_error_is_unconfirmed_not_stale(monkeypatch):
    import requests as rq
    _script(monkeypatch, [rq.ConnectionError("boom")])
    assert _run(_row()).verdict == "unconfirmed"


def test_unparseable_200_is_unconfirmed(monkeypatch):
    _script(monkeypatch, [_Resp(200, bad_json=True)])
    assert _run(_row()).verdict == "unconfirmed"


def test_zero_unpaid_and_parcel_exists_is_stale(monkeypatch):
    zero = _Resp(200, {"Records": [], "TotalRecords": 0})
    exists = _Resp(200, {"TotalRecords": 1, "Records": [
        {"ParcelNumber": "1010622", "BillYear": 2025}]})
    _script(monkeypatch, [zero, exists])
    res = _run(_row())
    assert res.verdict == "stale"
    assert res.evidence["bills_seen_years"] == ["2025"]


def test_zero_unpaid_but_parcel_not_in_lookup_is_unconfirmed(monkeypatch):
    zero = _Resp(200, {"Records": [], "TotalRecords": 0})
    other = _Resp(200, {"TotalRecords": 1, "Records": [{"ParcelNumber": "9999999"}]})
    _script(monkeypatch, [zero, other])
    res = _run(_row())
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "parcel_not_found"


def test_zero_unpaid_then_existence_check_fails_is_unconfirmed(monkeypatch):
    zero = _Resp(200, {"Records": [], "TotalRecords": 0})
    _script(monkeypatch, [zero, _Resp(403)])
    res = _run(_row())
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "fetch_failed"


def test_address_only_row_can_never_be_stale(monkeypatch):
    zero = _Resp(200, {"Records": [], "TotalRecords": 0})
    _script(monkeypatch, [zero])
    res = _run(_row(parcel="", addr="122 MCCROW RD"))
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "no_parcel_id"


def test_unpaid_records_confirm(monkeypatch):
    hit = _Resp(200, {"TotalRecords": 1, "SearchToken": "t", "Records": [
        {"ParcelNumber": "1010622", "BillYear": 2025, "OwnerName1": "DOE, J",
         "CartPaymentAmount": 412.5, "FlagsString": "ADVERTISED"}]})
    _script(monkeypatch, [hit])
    res = _run(_row())
    assert res.verdict == "confirmed"
    assert res.evidence["advertised"] is True


def test_circuit_breaker_stops_hammering_and_never_says_stale(monkeypatch):
    calls = _script(monkeypatch, [_Resp(403)])
    verdicts = [_run(_row(parcel=str(1000000 + i))).verdict for i in range(av._MAX_FAIL_STREAK + 4)]
    assert set(verdicts) == {"unconfirmed"}
    n_after_trip = len(calls)
    res = _run(_row(parcel="2000000"))
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "source_refusing"
    assert len(calls) == n_after_trip          # breaker open: no further request was made


def test_failure_reasons_are_transient_so_they_retry_in_hours():
    assert set(av.TRANSIENT_REASONS) == {"fetch_failed", "source_refusing"}
