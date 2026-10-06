"""The human-assisted lane writes its verdicts into the verification ledger the VM applies
(verification_human_lane.record_to_ledger), and its CLI never writes the board."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from foreclosure_scraper import verification_human_lane as lane
from foreclosure_scraper.verification import apply as A
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import ledger as L
from foreclosure_scraper.models import Listing, ListingType

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
ROW = {"state": "NC", "county": "Buncombe", "parcel_id": "9639622470", "listing_type": "estate_lead",
       "street_address": "50 Boone St", "source_url": "https://x/estates", "owner_name": "DOE JOHN"}


def _wall(now=T0):
    return lane.make_verification_record(signal="probate", verdict="wall",
                                         evidence={"reason": "queued"}, source="ecourts", now=now)


def test_the_wall_placeholder_lands_in_the_signal_ledger(tmp_path):
    p = lane.record_to_ledger(ROW, _wall(), directory=tmp_path, now=T0)
    assert p == tmp_path / "probate.json"
    led = L.Ledger.load("probate", tmp_path)
    key, e = led.find_row(ROW)
    assert key == core.row_key(ROW)
    assert e["latest"]["verdict"] == "wall" and e["latest"]["verifier"] == "human_lane"
    assert e["ttl_days"] == lane.LEDGER_TTL_DAYS["probate"]
    assert e["governs"] == list(lane.LEDGER_GOVERNS["probate"])


def test_the_real_verdict_replaces_the_placeholder_and_a_later_wall_never_displaces_it(tmp_path):
    lane.record_to_ledger(ROW, _wall(), directory=tmp_path, now=T0)
    t1 = T0 + timedelta(hours=1)
    done = lane.make_verification_record(signal="probate", verdict="confirmed",
                                         evidence={"case_number": "26E000100-320"},
                                         source="ecourts", now=t1)
    lane.record_to_ledger(ROW, done, directory=tmp_path, now=t1)
    t2 = T0 + timedelta(days=2)
    lane.record_to_ledger(ROW, _wall(t2), directory=tmp_path, now=t2)
    e = L.Ledger.load("probate", tmp_path).find_row(ROW)[1]
    assert e["latest"]["verdict"] == "confirmed"
    assert e["latest"]["evidence"] == {"case_number": "26E000100-320"}
    assert [h["verdict"] for h in e["history"]] == ["wall", "wall"]
    assert e["checks"] == 3


def test_sos_records_get_their_own_ledger(tmp_path):
    rec = lane.make_verification_record(signal="sos_entity", verdict="refuted",
                                        evidence={"status": "Dissolved"}, source="sosnc", now=T0)
    lane.record_to_ledger(ROW, rec, directory=tmp_path, now=T0)
    assert (tmp_path / "sos_entity.json").exists()
    assert L.Ledger.load("sos_entity", tmp_path).find_row(ROW)[1]["governs"] == []


def test_the_vm_apply_attaches_the_human_verdict(tmp_path):
    done = lane.make_verification_record(signal="probate", verdict="confirmed",
                                         evidence={}, source="ecourts", now=T0)
    lane.record_to_ledger(ROW, done, directory=tmp_path, now=T0)
    li = Listing(source="s", source_url=ROW["source_url"], listing_type=ListingType.ESTATE_LEAD,
                 state="NC", county="Buncombe", parcel_id="9639622470", street_address="50 Boone St")
    A.apply_verification([li], tmp_path, now=T0)
    rec = li.raw["verification"][0]
    assert rec["signal"] == "probate" and rec["verdict"] == "confirmed"
    assert rec["expires_at"] == core.iso_z(T0 + timedelta(days=lane.LEDGER_TTL_DAYS["probate"]))


def test_the_cli_writes_the_ledger_and_never_the_board():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "verify_lead_human_assisted.py").read_text()
    assert "record_to_ledger" in src and "publish_ledgers" in src
    for banned in ("patch_existing_rows(", "write_artifact(", "load_board("):
        assert banned not in src
