"""tax_lien_ustaxdata: the ustaxdata.com tax-bill search against real board rows, both
registry paths (TENANTS direct-parcel, NAME_SEARCH_TENANTS owner+address), against REAL
responses captured 2026-11-16 through the real Fetcher (tests/fixtures/verification/
tax_lien_ustaxdata.json.gz)."""
from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import tax_lien_ustaxdata as V

FIX = Path(__file__).parent / "fixtures" / "verification"


def _bundle() -> dict:
    with gzip.open(FIX / "tax_lien_ustaxdata.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)["responses"]


RESP = _bundle()


def run(coro):
    return asyncio.run(coro)


def _row(*, state="NC", county="Rockingham", owner=None, addr=None, parcel=None,
         years_delinquent=1, status="delinquent", **extra) -> dict:
    raw = {"tax_aging_surfaced": {"tax_year": 2026, "years_delinquent": years_delinquent,
                                  "status": status}}
    raw.update(extra)
    row = {"state": state, "county": county, "owner_name": owner, "street_address": addr,
          "parcel_id": parcel, "raw": raw}
    return row


def _check(row: dict):
    return run(V.verify(row, ReplayFetcher(RESP)))


# --------------------------------------------------------------------------- contract

def test_discovered_with_contract():
    vs = {v.name: v for v in registry.discover()}
    v = vs["tax_lien_ustaxdata"]
    assert (v.signal, v.ttl_days, v.retry_days) == ("tax_lien", 14, 7)
    assert v.governs == V.GOVERNS


# --------------------------------------------------------------------------- applies()

def test_applies_name_search_tenant_with_aging_claim():
    assert V.applies(_row(county="Rockingham"))
    assert V.applies(_row(county="alexander"))  # case-insensitive, via the live registry


def test_applies_direct_parcel_tenant():
    assert V.applies(_row(county="Robeson", parcel="021903073"))


def test_applies_rejects_sc_and_unknown_county_and_no_claim():
    assert not V.applies(_row(state="SC", county="Rockingham"))
    assert not V.applies(_row(county="Guilford"))  # real NC county, not a ustaxdata tenant
    assert not V.applies(_row(county="Rockingham", years_delinquent=0, status="current"))


# --------------------------------------------------------------------------- verify(): NAME_SEARCH_TENANTS

def test_confirmed_real_unpaid_rockingham_webster():
    row = _row(county="Rockingham", owner="WEBSTER RICHARD (HEIRS)", addr="1090 K FORK RD")
    r = _check(row)
    assert r.verdict == "confirmed"
    assert r.evidence["account"] == "18027"
    assert r.evidence["amount_due"] == 747.88   # 366.07 (2026) + 381.81 (2025), real site figures


def test_confirmed_real_unpaid_rockingham_hall():
    row = _row(county="Rockingham", owner="HALL ELMA WATKINS ESTATE", addr="1398 ANGLIN MILL RD")
    r = _check(row)
    assert r.verdict == "confirmed"
    assert r.evidence["account"] == "1290878"
    assert r.evidence["amount_due"] == 633.81


def test_confirmed_real_unpaid_rockingham_dillard_three_years():
    row = _row(county="Rockingham", owner="DILLARD S ARTHUR HEIRS", addr="1535 PRICE RD")
    r = _check(row)
    assert r.verdict == "confirmed"
    assert r.evidence["account"] == "25061"
    assert r.evidence["amount_due"] == 990.57   # 297.09 + 336.25 + 357.23, 3 real unpaid years


def test_unconfirmed_no_owner_name():
    row = _row(county="Rockingham", owner=None, addr="1090 K FORK RD")
    r = _check(row)
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "owner_unresolvable"


def test_unconfirmed_no_street_address_cannot_confirm_account():
    row = _row(county="Rockingham", owner="WEBSTER RICHARD (HEIRS)", addr=None)
    r = _check(row)
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "ambiguous_account"


def test_unconfirmed_address_does_not_match_any_account():
    row = _row(county="Rockingham", owner="WEBSTER RICHARD (HEIRS)", addr="999 NOWHERE LN")
    r = _check(row)
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "ambiguous_account"


# --------------------------------------------------------------------------- verify(): TENANTS (direct parcel)

def test_stale_robeson_all_paid():
    row = _row(county="Robeson", parcel="021903073")
    r = _check(row)
    assert r.verdict == "stale"
    assert r.evidence["reason"] == "paid_since_snapshot"
    assert r.evidence["account"] is not None


def test_unconfirmed_robeson_parcel_not_found():
    row = _row(county="Robeson", parcel="00000000X")
    r = _check(row)
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "parcel_not_found"


def test_unconfirmed_robeson_no_parcel_id():
    row = _row(county="Robeson", parcel=None)
    r = _check(row)
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "parcel_unresolvable"


# --------------------------------------------------------------------------- never refuted / public evidence

def test_never_refuted_and_evidence_is_whitelisted():
    for row in (
        _row(county="Rockingham", owner="WEBSTER RICHARD (HEIRS)", addr="1090 K FORK RD"),
        _row(county="Robeson", parcel="021903073"),
        _row(county="Robeson", parcel="00000000X"),
    ):
        r = _check(row)
        assert r.verdict != "refuted"
        assert set(r.evidence) <= set(V._KEYS)
