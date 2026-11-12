"""rutherford_wildfire_tax joins the PIN migration (audit 2026-10-09): its roll's 6-7 digit
Parcel_Number gave way to the 10-digit PIN, and parcel_alias / board_persist must fold the old
short-id rows into the new PIN rows instead of publishing both. Ids and addresses are made up."""
from __future__ import annotations

import json
from datetime import datetime

from foreclosure_scraper import parcel_alias as pa
from foreclosure_scraper.board_persist import _SOURCE_PARCEL_FIELDS, drop_folded_prior, merge_prior_board
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.validation import validate

SLUG = "counties_nc.rutherford_wildfire_tax"
NOW = datetime(2026, 10, 9, 2, 0, 0)
PRIOR_T = datetime(2026, 10, 7, 15, 0, 0)


def wild(parcel_id, short, addr="10 SAMPLE LN", url="https://example.invalid/w/1"):
    return Listing(source=SLUG, source_url=url, listing_type=ListingType.TAX_LIEN, state="NC",
                   county="Rutherford", parcel_id=parcel_id, street_address=addr, zip_code="28000",
                   first_seen=NOW, last_seen=NOW, raw={"rutherford_wildfire": {"parcel": short}})


def published(li: Listing, strip_nulled_marker: bool = False) -> Listing:
    p = li.model_copy(deep=True)
    p.first_seen = p.last_seen = PRIOR_T
    validate([p])
    if strip_nulled_marker:              # a row published before raw['parcel_id_nulled'] existed
        p.raw.pop("parcel_id_nulled", None)
    p.raw["owner_mailing"] = {"street": "1 EXAMPLE PO BOX"}
    return p


def board(tmp_path, rows):
    (tmp_path / "listings.json").write_text(json.dumps([r.model_dump(mode="json") for r in rows]))
    return tmp_path


def test_registered_in_both_tables():
    assert pa.ALIAS_SOURCES[SLUG] == ("rutherford_wildfire", "parcel")
    assert _SOURCE_PARCEL_FIELDS[SLUG] == ("rutherford_wildfire", "parcel")


def test_the_alias_table_maps_the_short_id_to_the_pin():
    table = pa.build([wild("0612345678", "123456")])
    assert table == {("NC", "rutherford", "123456"): "0612345678"}


def test_an_old_nulled_six_digit_row_folds_into_its_pin_row(tmp_path):
    old = published(wild("123456", "123456"))
    assert old.parcel_id is None
    fresh = wild("0612345678", "123456")
    merged, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [old]), now=NOW)
    assert len(merged) == 1 and merged[0].parcel_id == "0612345678"
    assert merged[0].raw.get("owner_mailing")
    assert drop_folded_prior([old], st) == []


def test_a_row_published_before_the_nulled_marker_still_folds(tmp_path):
    old = published(wild("123456", "123456"), strip_nulled_marker=True)
    assert old.parcel_id is None and "parcel_id_nulled" not in old.raw
    fresh = wild("0612345678", "123456")
    merged, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [old]), now=NOW)
    assert len(merged) == 1 and merged[0].parcel_id == "0612345678"


def test_two_different_parcels_stay_two_rows(tmp_path):
    old = published(wild("123456", "123456", addr="10 SAMPLE LN", url="https://example.invalid/w/1"))
    fresh = wild("0699999999", "654321", addr="99 OTHER RD", url="https://example.invalid/w/2")
    merged, _ = merge_prior_board([fresh], docs_dir=board(tmp_path, [old]), now=NOW)
    assert len(merged) == 2
