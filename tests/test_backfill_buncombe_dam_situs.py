"""scripts/backfill_buncombe_dam_situs.py corrects ALREADY-PUBLISHED board rows from
buncombe_unpaid_bills[_2024] and nc_dam_safety written BEFORE their forward-only fixes
(26dc41a3, 09cac01a) landed -- those fixes only changed what a FUTURE scrape writes.

This is new matching/collision logic layered on top of the already-tested _to_listing()
functions in arcgis_distress_layers.py / state_contamination.py (that reuse is deliberate --
see the script's own docstring), so these tests cover what's actually new here:

  1. _buncombe_is_old_shape() / _dam_is_old_shape(): the pre- vs post-fix raw-shape
     classifier that decides which rows are even candidates.
  2. _build_dam_index() / _dam_lookup(): the (Dam_Name, County, Owner) live-match logic
     that stands in for nc_dam_safety's missing pre-fix NID_ID.
  3. _collect_targets()'s collision guard: a board row whose dedupe_key() is shared with
     ANY other board row (not just another target-source row) must never be patched --
     confirmed against the real live board 2026-09-30 to be the dominant case (a
     buncombe_unpaid_bills row sharing its parcel-keyed identity with an already-correct
     counties.multi_year_delinquent_tax row for the same parcel).
  4. main() end-to-end with the network mocked out: patches land via patch_existing_rows()
     only for uniquely-keyed, live-matched rows; collisions and live-fetch misses are
     skipped, not guessed at; --dry-run never touches the board.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_buncombe_dam_situs as B  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


# --------------------------------------------------------------------------- #
# _buncombe_is_old_shape / _dam_is_old_shape
# --------------------------------------------------------------------------- #

def test_buncombe_old_shape_detected_when_house_num_absent():
    raw = {"arcgis_distress": {"layer": "buncombe_unpaid_bills", "pin": "1-2-3",
                                "address_line1": "1 MAIN ST", "city": "ASHEVILLE"}}
    assert B._buncombe_is_old_shape(raw) is True


def test_buncombe_new_shape_not_flagged_once_rescraped():
    raw = {"arcgis_distress": {"layer": "buncombe_unpaid_bills", "pin": "1-2-3",
                                "house_num": "1", "street_name": "MAIN", "street_type": "ST"},
           "owner_mailing": {"mailing": "1 MAIN ST ASHEVILLE NC"}}
    assert B._buncombe_is_old_shape(raw) is False


def test_buncombe_missing_raw_block_is_not_a_candidate():
    assert B._buncombe_is_old_shape({}) is False
    assert B._buncombe_is_old_shape({"arcgis_distress": {}}) is False


def test_dam_old_shape_detected_when_nid_and_lat_absent():
    raw = {"state_contamination": {"Dam_Name": "Test Dam", "Owner": "Jane Doe",
                                    "ADDR_LINE1": "1 Elm St", "COUNTY": "Rutherford"}}
    assert B._dam_is_old_shape(raw) is True


def test_dam_new_shape_not_flagged_once_rescraped():
    raw = {"state_contamination": {"Dam_Name": "Test Dam", "NID_ID": "NC00001",
                                    "LATITUDE": 35.2, "LONGITUDE": -81.9}}
    assert B._dam_is_old_shape(raw) is False


# --------------------------------------------------------------------------- #
# _build_dam_index / _dam_lookup
# --------------------------------------------------------------------------- #

_LIVE_DAMS = [
    {"Dam_Name": "Neighbors Dam", "Owner": "Jo Anne Neighbors", "COUNTY": "Caswell",
     "NID_ID": "NC04782", "LATITUDE": 36.47, "LONGITUDE": -79.39},
    # Same (Dam_Name, County) as a second dam, different owner -- the confirmed-live
    # ambiguity case (5 such pairs exist in the real footprint data).
    {"Dam_Name": "Harris Pond Dam", "Owner": "Alice Harris", "COUNTY": "Burke",
     "NID_ID": "NC01111", "LATITUDE": 35.7, "LONGITUDE": -81.7},
    {"Dam_Name": "Harris Pond Dam", "Owner": "Bob Harris", "COUNTY": "Burke",
     "NID_ID": "NC01112", "LATITUDE": 35.71, "LONGITUDE": -81.71},
]


def test_dam_lookup_matches_on_exact_triple():
    idx = B._build_dam_index(_LIVE_DAMS)
    a = B._dam_lookup(idx, "neighbors dam", "Caswell", "jo anne neighbors")
    assert a is not None and a["NID_ID"] == "NC04782"


def test_dam_lookup_falls_back_to_unique_name_county_pair_when_owner_drifts():
    idx = B._build_dam_index(_LIVE_DAMS)
    # Owner string on the old board row doesn't match live formatting exactly, but
    # (Dam_Name, County) is unique for Neighbors Dam -- safe to fall back.
    a = B._dam_lookup(idx, "Neighbors Dam", "Caswell", "J. Neighbors (Trustee)")
    assert a is not None and a["NID_ID"] == "NC04782"


def test_dam_lookup_refuses_to_guess_when_name_county_pair_is_ambiguous():
    idx = B._build_dam_index(_LIVE_DAMS)
    # "Harris Pond Dam" + "Burke" matches TWO live dams and the owner string given
    # doesn't exactly match either -- must return None, never guess.
    a = B._dam_lookup(idx, "Harris Pond Dam", "Burke", "H. Harris")
    assert a is None


def test_dam_lookup_returns_none_for_a_dam_that_no_longer_exists_live():
    idx = B._build_dam_index(_LIVE_DAMS)
    assert B._dam_lookup(idx, "Nonexistent Dam", "Polk", "Nobody") is None


# --------------------------------------------------------------------------- #
# _collect_targets(): collision guard + candidate collection, end-to-end against a
# real (tiny) board via board_stream/web_artifact -- no network involved.
# --------------------------------------------------------------------------- #

def _buncombe_row(pin: str, mailing_addr: str, mailing_city: str, mailing_zip: str,
                   **extra) -> Listing:
    raw = {"arcgis_distress": {"layer": "buncombe_unpaid_bills", "pin": pin,
                                "address_line1": mailing_addr, "city": mailing_city,
                                "postal_code": mailing_zip, "owner1_last_name": "SMITH"}}
    return Listing(source="counties_generic.arcgis_distress.buncombe_unpaid_bills",
                   source_url="https://example.test/buncombe",
                   listing_type=ListingType.TAX_LIEN, state="NC", county="Buncombe",
                   parcel_id=pin, street_address=mailing_addr, city=mailing_city,
                   zip_code=mailing_zip, raw=raw, **extra)


def _dam_row(name: str, owner: str, county: str, mailing_addr: str, parcel_id=None,
             **extra) -> Listing:
    raw = {"state_contamination": {"Dam_Name": name, "Owner": owner, "COUNTY": county,
                                    "ADDR_LINE1": mailing_addr}}
    return Listing(source="counties_generic.state_contamination.nc_dam_safety",
                   source_url="https://example.test/dam",
                   listing_type=ListingType.DISTRESSED, state="NC", county=county,
                   parcel_id=parcel_id, street_address=mailing_addr, raw=raw, **extra)


def test_collect_targets_finds_old_shape_rows_and_skips_new_shape_ones(tmp_path):
    docs = tmp_path / "docs"
    old_row = _buncombe_row("1234-56-7890-00000", "1 MAILING LN", "ASHEVILLE", "28801")
    already_fixed = _buncombe_row("9999-99-9999-00000", "9 MAILING LN", "ASHEVILLE", "28801")
    already_fixed.raw["arcgis_distress"]["house_num"] = "9"
    already_fixed.raw["owner_mailing"] = {"mailing": "9 MAILING LN"}
    dam_old = _dam_row("Old Dam", "Owner A", "Rutherford", "1 Owner Way")
    unrelated = Listing(source="some.other.source", source_url="https://example.test/x",
                        listing_type=ListingType.TAX_LIEN, state="NC", county="Gaston",
                        street_address="5 Other St", raw={})
    wa.write_artifact([old_row, already_fixed, dam_old, unrelated],
                       {"notes": "test seed"}, docs_dir=docs)

    scanned, key_counts, buncombe_cands, dam_cands = B._collect_targets(docs)
    assert scanned == 4
    assert [c[2] for c in buncombe_cands] == ["1234-56-7890-00000"]
    assert [(c[1], c[2]) for c in dam_cands] == [("Old Dam", "Rutherford")]


def test_collect_targets_collision_guard_flags_shared_identity(tmp_path):
    """Two board rows (a buncombe_unpaid_bills row and an unrelated source) that share the
    SAME parcel -> SAME dedupe_key(). main() must drop this key from patching entirely
    rather than risk stamping arcgis_distress-shaped raw onto the unrelated sibling --
    this is the dominant real-world case (a multi_year_delinquent_tax row for the same
    parcel), confirmed live 2026-09-30."""
    docs = tmp_path / "docs"
    pin = "5555-55-5555-00000"
    target = _buncombe_row(pin, "1 MAILING LN", "ASHEVILLE", "28801")
    sibling = Listing(source="counties.multi_year_delinquent_tax",
                      source_url="https://example.test/mydt",
                      listing_type=ListingType.TAX_LIEN, state="NC", county="Buncombe",
                      parcel_id=pin, street_address="1 REAL SITUS RD", raw={})
    wa.write_artifact([target, sibling], {"notes": "collision seed"}, docs_dir=docs)

    scanned, key_counts, buncombe_cands, dam_cands = B._collect_targets(docs)
    assert len(buncombe_cands) == 1
    key = buncombe_cands[0][0]
    assert key_counts[key] == 2   # target + sibling share it -- must not be patched


# --------------------------------------------------------------------------- #
# main() end-to-end, network mocked out entirely.
# --------------------------------------------------------------------------- #

@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(B, "REPO", repo)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def _fake_buncombe_layer_attrs(pin: str) -> dict:
    return {"pin": pin, "house_num": "42", "street_direction": None,
            "street_name": "REAL SITUS", "street_type": "RD",
            "address_line1": "1 MAILING LN", "city": "ASHEVILLE", "state": "NC",
            "postal_code": "28801", "owner1_last_name": "SMITH", "owner1_first_name": "JO",
            "real_value": 100000.0, "total_value": 100000.0}


async def _fake_fetch_buncombe(slug: str, pins) -> dict:
    return {p: _fake_buncombe_layer_attrs(p) for p in pins}


async def _fake_fetch_dam_registry() -> list:
    return [{"Dam_Name": "Old Dam", "Owner": "Owner A", "COUNTY": "Rutherford",
             "NID_ID": "NC09999", "LATITUDE": 35.3, "LONGITUDE": -81.9,
             "ADDR_LINE1": "1 Owner Way", "STATE": "NC"}]


def _fake_geocode_batch(addresses):
    # Deterministic fake coordinate so the test doesn't touch the network.
    return {a: (35.6, -82.6) for a in addresses}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(B, "_fetch_buncombe_by_pin", _fake_fetch_buncombe)
    monkeypatch.setattr(B, "_fetch_dam_registry", _fake_fetch_dam_registry)
    monkeypatch.setattr(B, "geocode_batch_census", _fake_geocode_batch)


def test_main_patches_matched_rows_and_skips_collisions(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    pin = "1234-56-7890-00000"
    target = _buncombe_row(pin, "1 MAILING LN", "ASHEVILLE", "28801",
                           latitude=35.0, longitude=-82.0)  # stale mailing-derived coord
    dam_old = _dam_row("Old Dam", "Owner A", "Rutherford", "1 Owner Way",
                       parcel_id="WRONG-PARCEL-1", latitude=33.0, longitude=-84.0)
    unrelated = Listing(source="some.other.source", source_url="https://example.test/x",
                        listing_type=ListingType.TAX_LIEN, state="NC", county="Gaston",
                        street_address="5 Other St", raw={})
    wa.write_artifact([target, dam_old, unrelated], {"notes": "main seed"}, docs_dir=docs)

    monkeypatch.setattr(sys, "argv", ["backfill_buncombe_dam_situs.py"])
    rc = B.main()
    assert rc == 0

    rows = {li.parcel_id: li for li in wa.load_board(docs) if li.parcel_id}
    fixed = rows[pin]
    assert fixed.street_address == "42 REAL SITUS RD"
    assert fixed.city is None and fixed.zip_code is None
    assert fixed.latitude == 35.6 and fixed.longitude == -82.6   # from the fake geocoder
    assert fixed.raw["owner_mailing"]["mailing"] == "1 MAILING LN ASHEVILLE NC 28801"
    assert fixed.raw["arcgis_distress"]["house_num"] == "42"

    fixed_dam = rows["NC09999"]
    assert fixed_dam.latitude == 35.3 and fixed_dam.longitude == -81.9
    assert fixed_dam.street_address is None
    assert fixed_dam.raw["state_contamination"]["NID_ID"] == "NC09999"
    assert fixed_dam.raw["state_contamination"]["owner_mailing"]["ADDR_LINE1"] == "1 Owner Way"

    # unrelated row untouched
    untouched = [li for li in wa.load_board(docs) if li.source == "some.other.source"][0]
    assert untouched.street_address == "5 Other St"


def test_dry_run_never_writes_the_board(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    pin = "1234-56-7890-00000"
    target = _buncombe_row(pin, "1 MAILING LN", "ASHEVILLE", "28801")
    wa.write_artifact([target], {"notes": "dry run seed"}, docs_dir=docs)
    before = (docs / "listings.json").read_bytes()

    monkeypatch.setattr(sys, "argv", ["backfill_buncombe_dam_situs.py", "--dry-run"])
    rc = B.main()
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before
