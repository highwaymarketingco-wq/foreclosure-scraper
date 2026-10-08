"""Lincoln and Rutherford switch to the 10-digit PIN (owner decision 2026-10-07) without
publishing any property twice. All ids, addresses and phones below are made up.

The migration a full run meets: the published board holds the OLD rows (Lincoln keyed by its
5-6 character PARCELID, nulled by validation; Rutherford by its 6-7 digit Parcel_Number, the
6-digit ones nulled), and the fresh scrape carries the NEW rows (parcel_id = PIN, the short id
kept in the source's raw block). merge_prior_board must fold each old row into its new row and
record its old key, so the GRANDFATHER snapshot does not put it back.
"""
from __future__ import annotations

import json
from datetime import datetime

from foreclosure_scraper import parcel_alias as pa
from foreclosure_scraper.board_persist import drop_folded_prior, merge_prior_board
from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.validation import validate

NOW = datetime(2026, 10, 7, 2, 0, 0)
PRIOR_T = datetime(2026, 9, 22, 15, 0, 0)


def lincoln(parcel_id, parcelid="00777", pin="3600000001", addr="TEST RD"):
    return Listing(source="counties_nc.lincoln_vacant", source_url="https://example.invalid/l",
                   listing_type=ListingType.UNKNOWN, state="NC", county="Lincoln",
                   parcel_id=parcel_id, street_address=addr, first_seen=NOW, last_seen=NOW,
                   raw={"lincoln_vacant": {"PARCELID": parcelid, "PIN": pin}})


def ruth(parcel_id, short, pin=None, addr="10 SAMPLE LN", zip_code="28000"):
    blk = {"parcel": short}
    if pin:
        blk["pin"] = pin
    return Listing(source="counties_nc.rutherford_tax", source_url="https://example.invalid/r.xlsx",
                   listing_type=ListingType.TAX_LIEN, state="NC", county="Rutherford",
                   parcel_id=parcel_id, street_address=addr, zip_code=zip_code,
                   first_seen=NOW, last_seen=NOW, raw={"rutherford_tax": blk})


def published(li: Listing) -> Listing:
    """As a full run published it: validated (short ids nulled), with an enrichment."""
    p = li.model_copy(deep=True)
    p.first_seen = p.last_seen = PRIOR_T
    validate([p])
    p.raw["owner_phone"] = "(000) 555-0100"
    return p


def board(tmp_path, rows):
    (tmp_path / "listings.json").write_text(json.dumps([r.model_dump(mode="json") for r in rows]))
    return tmp_path


def _one_row_for(merged, pin):
    rows = [li for li in merged if li.parcel_id == pin or
            ((li.raw or {}).get("parcel_id_nulled") or {}).get("value")]
    return rows


def test_alias_table_is_built_from_rows_carrying_both_ids():
    t = pa.build([lincoln("3600000001"), ruth("1600000002", "123456", pin="1600000002")])
    assert pa.lookup(t, "NC", "Lincoln", "00777") == "3600000001"
    assert pa.lookup(t, "NC", "rutherford", "123456") == "1600000002"
    assert pa.lookup(t, "NC", "Rutherford", "999999") is None


def test_a_short_id_with_two_pins_is_ambiguous_and_left_out():
    t = pa.build([ruth("1600000002", "123456", pin="1600000002"),
                  ruth("1600000003", "123456", pin="1600000003")])
    assert pa.lookup(t, "NC", "Rutherford", "123456") is None


def test_lincoln_old_parcelid_row_and_new_pin_row_merge_into_one(tmp_path):
    old = published(lincoln("00777"))                    # PARCELID: nulled as too short
    assert old.parcel_id is None
    fresh = lincoln("3600000001")
    merged, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [old]), now=NOW)
    assert len(merged) == 1
    assert merged[0].parcel_id == "3600000001"
    assert merged[0].raw.get("owner_phone") == "(000) 555-0100"     # enrichment carried
    assert not merged[0].raw.get("pulled_sale")
    assert st["matched_parcel_alias"] == 1
    # GRANDFATHER: the snapshot copy of the old row must not come back
    assert drop_folded_prior([old], st) == []


def test_rutherford_valid_seven_digit_row_merges_with_its_pin_row(tmp_path):
    old = published(ruth("1234567", "1234567"))
    assert old.parcel_id == "1234567"
    fresh = ruth("1600000002", "1234567", pin="1600000002")
    merged, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [old]), now=NOW)
    assert len(merged) == 1 and merged[0].parcel_id == "1600000002"
    assert merged[0].raw.get("owner_phone")
    assert st["matched_parcel_alias"] == 1
    assert drop_folded_prior([old], st) == []


def test_rutherford_nulled_six_digit_row_merges_with_its_pin_row(tmp_path):
    old = published(ruth("123456", "123456"))
    assert old.parcel_id is None
    fresh = ruth("1600000003", "123456", pin="1600000003")
    merged, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [old]), now=NOW)
    assert len(merged) == 1 and merged[0].parcel_id == "1600000003"
    assert st["matched_parcel_alias"] == 1
    assert drop_folded_prior([old], st) == []


def test_reverse_a_pin_row_meets_a_fresh_row_that_fell_back_to_the_short_id(tmp_path):
    old = published(ruth("1600000004", "1234568", pin="1600000004"))
    fresh = ruth("1234568", "1234568")                   # the PIN map could not be read this run
    merged, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [old]), now=NOW)
    assert len(merged) == 1
    assert st["matched_parcel_alias"] == 1


def test_two_different_properties_are_never_merged_by_the_alias(tmp_path):
    old = published(ruth("123457", "123457", addr="1 OTHER RD"))
    fresh = ruth("1600000005", "123458", pin="1600000005", addr="2 ELSE RD")
    merged, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [old]), now=NOW)
    assert len(merged) == 2
    assert st["matched_parcel_alias"] == 0


def test_dedupe_meets_another_rutherford_source_on_the_pin():
    other = Listing(source="counties_nc.rutherford_wildfire_tax", source_url="https://example.invalid/w",
                    listing_type=ListingType.TAX_LIEN, state="NC", county="Rutherford",
                    parcel_id="1234569", street_address="20 SAMPLE LN", first_seen=NOW, last_seen=NOW,
                    raw={})
    fresh = ruth("1600000006", "1234569", pin="1600000006", addr="20 SAMPLE LN")
    out = dedupe([fresh, other])
    assert len(out) == 1 and out[0].parcel_id == "1600000006"


def test_rows_without_an_alias_are_untouched():
    li = ruth("7654321", "7654321")
    assert pa.apply([li], pa.build([li])) == 0 and li.parcel_id == "7654321"


def test_an_aliased_prior_row_that_does_not_match_is_still_never_restored(tmp_path):
    """A prior row whose short id maps to a PIN but which the house-number guard keeps apart
    from the fresh row is kept (aged) under the PIN; its OLD key must not come back too."""
    old = published(ruth("1234570", "1234570", addr="5 SAMPLE LN"))
    fresh = ruth("1600000007", "1234570", pin="1600000007", addr="7 SAMPLE LN")
    merged, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [old]), now=NOW)
    assert st["prior_parcel_aliased"] == 1
    assert drop_folded_prior([old], st) == []


def test_a_short_id_never_maps_to_another_short_id():
    """A carried Rutherford row whose parcel_id is another 7-digit county number (not a PIN) must
    not enter the alias table: on 10/8 such rows gave 53 rows a different property's id."""
    t = pa.build([ruth("1600009", "1600001"), ruth("1600000002", "123456", pin="1600000002")])
    assert pa.lookup(t, "NC", "Rutherford", "1600001") is None
    assert pa.lookup(t, "NC", "Rutherford", "123456") == "1600000002"
    assert pa.is_pin("1600-00-0002") and not pa.is_pin("1600009") and not pa.is_pin("16000000021")
