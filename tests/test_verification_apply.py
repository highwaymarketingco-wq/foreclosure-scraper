"""verification.apply: the VM's no-network step that attaches raw['verification'] from the
ledgers. Never raises; matches rows on any key one entry claims; stamps expires_at/governs."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.verification import apply as A
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import ledger as L

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _li(pid="964912345600000", addr="5 Main St", raw=None, county="Buncombe"):
    return Listing(source="s", source_url="https://x/roll.pdf", listing_type=ListingType.TAX_LIEN,
                   state="NC", county=county, parcel_id=pid, street_address=addr, raw=raw or {})


def _ledger(tmp_path, signal, rows):
    led = L.Ledger(signal)
    for row, verdict, verifier in rows:
        led.record(row, core.result(signal, verdict, {"n": 1}, source="src", version="v1",
                                    verifier=verifier, now=T0),
                   ttl_days=10, governs=("stored_name",), now=T0)
    led.save(tmp_path / f"{signal}.json")
    return led


def test_attaches_the_latest_record_with_expiry_and_the_registry_governs(tmp_path):
    li = _li()
    _ledger(tmp_path, "tax_lien", [(li, "refuted", "tax_lien_buncombe")])
    out = A.apply_verification([li], tmp_path, now=T0)
    recs = li.raw["verification"]
    assert len(recs) == 1 and recs[0]["verdict"] == "refuted"
    # the module still exists: its CURRENT TTL (30 d) and GOVERNS win over the stored ones
    assert recs[0]["expires_at"] == core.iso_z(T0 + timedelta(days=30))
    assert "tax_lien" in recs[0]["governs"] and "stored_name" not in recs[0]["governs"]
    assert out["status"] == "ok" and out["rows"] == 1 and out["suppressing"] == 1
    assert out["signals"]["tax_lien"]["refuted"] == 1


def test_a_record_without_a_module_uses_what_the_entry_stored(tmp_path):
    li = _li()
    _ledger(tmp_path, "probate", [(li, "confirmed", "human_lane")])
    A.apply_verification([li], tmp_path, now=T0)
    rec = li.raw["verification"][0]
    assert rec["governs"] == ["stored_name"]
    assert rec["expires_at"] == core.iso_z(T0 + timedelta(days=10))


def test_matches_by_address_after_a_parcel_backfill_and_keeps_other_signals(tmp_path):
    checked = _li(pid=None)
    _ledger(tmp_path, "tax_lien", [(checked, "confirmed", "tax_lien_buncombe")])
    later = _li(pid="964912345600000", raw={"verification": [
        {"signal": "jail_booking", "verdict": "stale", "checked_at": "2026-10-01T00:00:00Z"},
        {"signal": "tax_lien", "verdict": "refuted", "checked_at": "2026-01-01T00:00:00Z"}]})
    A.apply_verification([later], tmp_path, now=T0)
    by = {r["signal"]: r for r in later.raw["verification"]}
    assert by["tax_lien"]["verdict"] == "confirmed"          # replaced from the ledger
    assert by["jail_booking"]["verdict"] == "stale"           # untouched
    assert [r["signal"] for r in later.raw["verification"]] == ["jail_booking", "tax_lien"]


def test_rows_of_the_same_property_share_the_verdict_and_others_are_untouched(tmp_path):
    a, b = _li(addr="5 Main St"), _li(addr="5 Main Street")
    other = _li(pid="964900000000000", addr="9 Elm St")
    _ledger(tmp_path, "tax_lien", [(a, "stale", "tax_lien_buncombe")])
    out = A.apply_verification([a, b, other], tmp_path, now=T0)
    assert a.raw["verification"][0]["verdict"] == b.raw["verification"][0]["verdict"] == "stale"
    assert "verification" not in other.raw
    assert out["rows"] == 2


def test_disabled_missing_and_empty(tmp_path, monkeypatch):
    li = _li()
    assert A.apply_verification([li], tmp_path / "nope")["status"] == "absent"
    assert A.apply_verification([li], tmp_path)["status"] == "empty"
    _ledger(tmp_path, "tax_lien", [(li, "refuted", "tax_lien_buncombe")])
    monkeypatch.setenv("VERIFICATION_APPLY", "0")
    assert A.apply_verification([li], tmp_path)["status"] == "disabled"
    assert "verification" not in li.raw


def test_an_unreadable_ledger_is_skipped_and_the_others_still_apply(tmp_path):
    li = _li()
    _ledger(tmp_path, "tax_lien", [(li, "confirmed", "tax_lien_buncombe")])
    (tmp_path / "broken.json").write_text("{nope")
    out = A.apply_verification([li], tmp_path, now=T0)
    assert out["status"] == "ok" and "broken.json" in out["unreadable"]
    assert li.raw["verification"][0]["verdict"] == "confirmed"


def test_never_raises(tmp_path, monkeypatch):
    li = _li()
    _ledger(tmp_path, "tax_lien", [(li, "confirmed", "tax_lien_buncombe")])

    def boom(*a, **k):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(A, "load_all", boom)
    out = A.apply_verification([li], tmp_path)
    assert out["status"] == "error" and "disk on fire" in out["error"]


def test_a_bad_row_does_not_stop_the_rest(tmp_path):
    good = _li()
    _ledger(tmp_path, "tax_lien", [(good, "confirmed", "tax_lien_buncombe")])

    class Weird:
        @property
        def state(self):
            raise RuntimeError("bad row")
    out = A.apply_verification([Weird(), good], tmp_path, now=T0)
    assert out.get("row_errors") == 1 and good.raw["verification"][0]["verdict"] == "confirmed"


def test_the_published_board_keeps_the_field():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert RAW_KEEP.get("verification") == "*"


def test_main_applies_before_scoring():
    src = (A.__file__.rsplit("/verification/", 1)[0] + "/main.py")
    text = open(src, encoding="utf-8").read()
    tail = text[text.index("async def run_enrich_tail("):]
    assert tail.index("apply_verification(enriched)") < tail.index("score_board(enriched")
    assert text.count("apply_verification(enriched)") == 1


def test_ledger_file_is_plain_json(tmp_path):
    li = _li()
    _ledger(tmp_path, "tax_lien", [(li, "confirmed", "tax_lien_buncombe")])
    data = json.loads((tmp_path / "tax_lien.json").read_text())
    assert data["counts"]["confirmed"] == 1
