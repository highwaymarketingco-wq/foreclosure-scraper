"""scripts/ingest_new_county_sources.py: the dry run, the key scan, and the additive merge.

Nothing here touches the live board, takes the real lock or reaches the network: the fetch,
the scope gate and the board writers are replaced with stand-ins that record how they were called.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ingest_new_county_sources", REPO / "scripts" / "ingest_new_county_sources.py")
ing = importlib.util.module_from_spec(_spec)
sys.modules["ingest_new_county_sources"] = ing
_spec.loader.exec_module(ing)


def L(**kw) -> Listing:
    base = dict(source="counties_nc.nc_its_public_tax", source_url="https://example.invalid/x",
                listing_type=ListingType.TAX_LIEN, state="NC", county="Onslow")
    base.update(kw)
    return Listing(**base)


# --------------------------------------------------------------------------- keys

@pytest.mark.parametrize("li", [
    L(parcel_id="801-154"),
    L(parcel_id="1116-53", street_address="2478 PINEY GREEN RD", zip_code="28544"),
    L(street_address="1008 1st Street", zip_code="28445-8620"),
    L(street_address="1008 1st Street", county="Onslow"),
])
def test_row_keys_contain_the_primary_dedupe_key(li):
    assert li.dedupe_key() in ing.listing_keys(li)


def test_a_parcel_and_its_padded_twin_share_a_key():
    assert ing.listing_keys(L(parcel_id="801-154")) & ing.listing_keys(L(parcel_id=" 801154 "))


def test_a_digitless_parcel_is_not_a_key():
    """models._normalize_parcel rejects it, so it must not become a merge key here either."""
    assert not any(k.startswith("parcel:") for k in ing.listing_keys(L(parcel_id="ehurst")))


def test_no_parcel_and_no_address_yields_no_keys():
    assert ing.listing_keys(L()) == set()


def _write_board(path: Path, rows: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rows, f)


def test_scan_board_streams_once_and_keeps_only_the_counties_in_play(tmp_path):
    board = tmp_path / "listings.json.gz"
    _write_board(board, [
        {"state": "NC", "county": "Onslow", "parcel_id": "801-154"},
        {"state": "NC", "county": "Onslow County", "parcel_id": "9-9"},        # not the same spelling
        {"state": "NC", "county": "Wake", "parcel_id": "801-154"},             # another county
        {"state": "SC", "county": "Horry", "street_address": "5 Main St", "zip_code": "29577"},
    ])
    keys, total, per = ing.scan_board(board, {("NC", "onslow")})
    assert total == 4 and per == Counter({("NC", "onslow"): 1})
    assert keys == {"parcel:NC:onslow:801154"}


# --------------------------------------------------------------------------- apply_rows

def test_new_rows_are_appended_and_existing_rows_are_left_exactly_alone():
    a = L(parcel_id="1-1", source="counties_generic.liensnc", owner_name="EXISTING")
    b = L(parcel_id="2-2", owner_name="EXISTING TWO")
    rows = [a, b]
    keep = list(rows)
    stats = ing.apply_rows(rows, [L(parcel_id="3-3", owner_name="NEW"), L(parcel_id="4-4", owner_name="NEW2")])
    assert stats["added"] == 2 and stats["before"] == 2 and stats["after"] == 4 == len(rows)
    assert rows[:2] == keep and rows[0] is a and rows[1] is b          # same objects, same order
    assert [r.parcel_id for r in rows[2:]] == ["3-3", "4-4"]
    assert stats["existing_rows_unchanged"] is True
    assert stats["added_by_source"] == {"counties_nc.nc_its_public_tax": 2}


def test_a_match_on_the_parcel_key_is_not_added_and_does_not_touch_the_twin():
    twin = L(parcel_id="801-154", source="counties_generic.liensnc", owner_name=None)
    rows = [twin]
    stats = ing.apply_rows(rows, [L(parcel_id="801154", owner_name="FILL ME")])
    assert stats["added"] == 0 and stats["matched_untouched"] == 1 and len(rows) == 1
    assert rows[0] is twin and twin.owner_name is None                 # NOT merged by default


def test_a_match_on_a_strong_signature_is_found_too():
    """Same street and zip, no parcel on either side: dedupe._strong_sigs links them."""
    twin = L(street_address="1008 1st St", zip_code="28445", source="counties_generic.liensnc")
    rows = [twin]
    stats = ing.apply_rows(rows, [L(street_address="1008 1st Street", zip_code="28445")])
    assert stats["added"] == 0 and stats["matched_untouched"] == 1


def test_duplicates_inside_the_new_batch_collapse():
    rows: list[Listing] = []
    stats = ing.apply_rows(rows, [L(parcel_id="5-5", owner_name="A"), L(parcel_id="5-5", owner_name=None)])
    assert stats["added"] == 1 and stats["dup_within_new"] == 1 and len(rows) == 1
    assert rows[0].owner_name == "A"


def test_merge_matches_fills_a_blank_but_never_overwrites_a_value():
    twin = L(parcel_id="801-154", source="counties_generic.liensnc", owner_name="KEEP ME", city=None)
    rows = [twin]
    stats = ing.apply_rows(rows, [L(parcel_id="801-154", owner_name="OVERWRITE", city="Surf City")],
                           merge_matches=True)
    assert stats["matched_merged"] == 1 and stats["added"] == 0
    assert twin.owner_name == "KEEP ME"
    assert twin.city == "Surf City"


def test_the_unchanged_guard_fires_if_an_existing_row_moves(monkeypatch):
    real = ing._fp
    n = {"i": 0}

    def drifting(li):
        n["i"] += 1
        return (n["i"],)

    monkeypatch.setattr(ing, "_fp", drifting)
    with pytest.raises(AssertionError, match="existing row changed"):
        ing.apply_rows([L(parcel_id="1-1")], [L(parcel_id="2-2")])
    monkeypatch.setattr(ing, "_fp", real)


def test_apply_rows_with_an_empty_board_and_an_empty_batch():
    assert ing.apply_rows([], [])["added"] == 0
    rows: list[Listing] = []
    assert ing.apply_rows(rows, [L(parcel_id="1-1")])["after"] == 1


def test_a_thousand_name_only_rows_from_one_post_stay_a_thousand():
    """Rows with no parcel and no address key on source_url; per-row fragments keep them apart."""
    new = [L(source="counties_nc.albemarle_observer_tax_lists", county="Washington",
             source_url=f"https://albemarleobserver.news/p/#acct-{i}", owner_name=f"OWNER {i}")
           for i in range(1000)]
    rows: list[Listing] = []
    assert ing.apply_rows(rows, new)["added"] == 1000


# --------------------------------------------------------------------------- scope

def test_a_dateless_roll_skips_active_only_and_a_dated_sale_does_not(monkeypatch):
    asked = []

    def in_scope(li):
        return li.county != "Nowhere"

    def active(li, horizon, *, now=None):
        asked.append(li.parcel_id)
        return li.parcel_id != "stale"

    monkeypatch.setattr(ing, "scope_fns", lambda: (in_scope, active))
    rows = [L(parcel_id="roll"),                                        # dateless standing roll
            L(parcel_id="live", sale_date=datetime.utcnow() + timedelta(days=30)),
            L(parcel_id="stale", sale_date=datetime.utcnow() - timedelta(days=90)),
            L(parcel_id="out", county="Nowhere")]
    kept, dropped = ing.in_scope_and_live(rows)
    assert [li.parcel_id for li in kept] == ["roll", "live"]
    assert asked == ["live", "stale"]                                   # never asked about the roll
    assert sum(dropped.values()) == 2


def test_the_real_scope_gate_keeps_distress_anywhere_and_drops_a_flip_outside_the_footprint():
    """Not a stand-in: main._in_scope itself (the owner rule)."""
    kept, dropped = ing.in_scope_and_live([
        L(parcel_id="a", county="Onslow"),                                          # tax lien anywhere
        L(county="Florence", state="SC", listing_type=ListingType.PROBATE_NOTICE, parcel_id="b"),
        L(county="Martin", listing_type=ListingType.TAX_SALE, parcel_id="c",
          sale_date=datetime.utcnow() + timedelta(days=20)),
        L(county="Martin", listing_type=ListingType.FORECLOSURE_SALE, parcel_id="d",   # a flip, not a footprint county
          sale_date=datetime.utcnow() + timedelta(days=20)),
    ])
    assert sorted(li.parcel_id for li in kept) == ["a", "b", "c"]
    assert sum(dropped.values()) == 1


# --------------------------------------------------------------------------- source filters

def test_column_keeps_only_the_new_counties_and_never_a_foreclosure_sale():
    keep = ing.SPECS["column"].keep
    assert keep(L(county="Washington", listing_type=ListingType.TAX_SALE)) is True
    assert keep(L(county="Northampton", listing_type=ListingType.TAX_SALE)) is True
    assert keep(L(county="Florence", state="SC", listing_type=ListingType.PROBATE_NOTICE)) is True
    assert keep(L(county="Washington", listing_type=ListingType.FORECLOSURE_SALE)) is False
    assert keep(L(county="Burke", listing_type=ListingType.TAX_SALE)) is False        # existing footprint lane
    assert keep(L(county="Charleston", state="SC", listing_type=ListingType.PROBATE_NOTICE)) is False


def test_catalis_keeps_only_the_counties_asked_for(monkeypatch):
    monkeypatch.delenv("CATALIS_ROLL_COUNTIES", raising=False)
    keep = ing.SPECS["catalis"].keep
    assert keep(L(county="Chester", state="SC")) and not keep(L(county="Pickens", state="SC"))
    monkeypatch.setenv("CATALIS_ROLL_COUNTIES", "Pickens")
    assert keep(L(county="Pickens", state="SC"))


def test_every_spec_slug_is_a_registered_scraper():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    slugs = {s.slug for s in all_scrapers()}
    for spec in ing.SPECS.values():
        assert spec.slug in slugs, spec.slug


# --------------------------------------------------------------------------- the CLI

@pytest.fixture
def stubs(monkeypatch):
    """Replace the network fetch and the board writers; record every call."""
    calls: list = []
    import foreclosure_scraper.web_artifact as wa

    def fake_fetch(spec, limit):
        async def go():
            calls.append(("fetch", spec.key, limit))
            return ([L(parcel_id=f"{spec.key}-1", source=spec.slug), L(parcel_id=f"{spec.key}-2", source=spec.slug)],
                    {"fetched": 2, "kept": 2, "seconds": 0.0, "error": None})
        return go()

    class Lock:
        def __enter__(self):
            calls.append(("lock",))
            return self

        def __exit__(self, *a):
            calls.append(("unlock",))

    board: list[Listing] = [L(parcel_id="existing-1", source="counties_generic.liensnc")]

    def fake_load(docs):
        calls.append(("load",))
        return board

    def fake_write(rows, summary, docs_dir=None):
        calls.append(("write", len(rows), summary["total"]))

    monkeypatch.setattr(ing, "fetch_source", fake_fetch)
    monkeypatch.setattr(ing, "scope_fns", lambda: ((lambda li: True), (lambda li, h, now=None: True)))
    monkeypatch.setattr(wa, "board_lock", lambda *a, **kw: Lock())
    monkeypatch.setattr(wa, "load_board", fake_load)
    monkeypatch.setattr(wa, "write_artifact", fake_write)
    return calls, board


def test_an_unknown_source_is_refused(capsys):
    assert ing.main(["--sources", "nope"]) == 2


def test_the_default_is_a_dry_run_that_never_locks_loads_or_writes(stubs, capsys):
    calls, board = stubs
    rc = ing.main(["--no-scan", "--sources", "its,horry", "--limit", "7"])
    assert rc == 0
    assert [c[0] for c in calls] == ["fetch", "fetch"]
    assert all(c[2] == 7 for c in calls)                                  # sample limit passed through
    assert len(board) == 1
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "nothing written" in out


def test_a_dry_run_reports_new_versus_on_board_from_one_key_scan(stubs, tmp_path, capsys):
    calls, board = stubs
    b = tmp_path / "listings.json.gz"
    _write_board(b, [{"state": "NC", "county": "Onslow", "parcel_id": "its-1"}])
    assert ing.main(["--sources", "its", "--board", str(b)]) == 0
    out = capsys.readouterr().out
    assert "1 new, 1 already on the board" in out
    assert "board scan: 1 rows streamed once" in out


def test_a_dry_run_masks_owner_names_unless_asked(monkeypatch, stubs, capsys):
    monkeypatch.setattr(ing, "fetch_source", lambda spec, limit: _one(L(parcel_id="p", owner_name="ROE JANE")))
    ing.main(["--no-scan", "--sources", "its"])
    assert "ROE JANE" not in capsys.readouterr().out
    ing.main(["--no-scan", "--sources", "its", "--show-pii"])
    assert "ROE JANE" in capsys.readouterr().out


def _one(li):
    async def go():
        return [li], {"fetched": 1, "kept": 1, "seconds": 0.0, "error": None}
    return go()


def test_apply_fetches_first_then_locks_loads_merges_and_writes(stubs, capsys):
    calls, board = stubs
    rc = ing.main(["--apply", "--sources", "its,horry"])
    assert rc == 0
    kinds = [c[0] for c in calls]
    assert kinds == ["fetch", "fetch", "lock", "load", "write", "unlock"]   # fetch BEFORE the lock
    assert calls[0][2] is None and calls[1][2] is None                       # full fetch, no sample limit
    assert calls[4] == ("write", 5, 5)                                       # 1 existing + 4 new
    assert board[0].parcel_id == "existing-1" and len(board) == 5


def test_apply_writes_a_harvest_and_reuses_it_without_fetching(stubs, tmp_path):
    calls, board = stubs
    h = tmp_path / "harvest.json"
    assert ing.main(["--apply", "--sources", "its", "--harvest", str(h)]) == 0
    assert h.exists() and [c[0] for c in calls].count("fetch") == 1
    calls.clear()
    board[:] = board[:1]
    assert ing.main(["--apply", "--sources", "its", "--harvest", str(h)]) == 0
    assert [c[0] for c in calls].count("fetch") == 0                          # served from the harvest
    assert len(board) == 3                                                    # rows still land


def test_apply_with_nothing_fetched_aborts_without_touching_the_board(stubs, monkeypatch):
    calls, board = stubs

    def empty(spec, limit):
        async def go():
            return [], {"fetched": 0, "kept": 0, "seconds": 0.0, "error": "boom"}
        return go()

    monkeypatch.setattr(ing, "fetch_source", empty)
    assert ing.main(["--apply", "--sources", "its"]) == 1
    assert not any(c[0] in ("lock", "load", "write") for c in calls)


def test_a_failed_scraper_keeps_what_it_had_collected():
    """fetch_source: an exception mid-run returns the scraper's own partial rows, with the error."""
    import asyncio

    class Boom:
        partial = [L(parcel_id="kept-1")]

        async def fetch(self):
            raise RuntimeError("host went away")

    spec = ing.Spec("x", "counties_nc.nc_its_public_tax", lambda: Boom(), lambda s, n: None)
    rows, meta = asyncio.run(ing.fetch_source(spec, None))
    assert [r.parcel_id for r in rows] == ["kept-1"] and "RuntimeError" in meta["error"]


# --------------------------------------------------------------------------- harvest round trip

def test_harvest_round_trips_a_listing(tmp_path):
    p = tmp_path / "h.json"
    li = L(parcel_id="1-1", owner_name="ROE", raw={"tax_owed": {"balance": 5.0}}, sale_date=datetime(2026, 11, 9))
    ing.save_harvest(p, [li])
    (back,) = ing.load_harvest(p)
    assert back.parcel_id == "1-1" and back.raw["tax_owed"]["balance"] == 5.0
    assert back.sale_date == datetime(2026, 11, 9) and back.listing_type == ListingType.TAX_LIEN


def test_apply_without_sources_skips_catalis_but_a_dry_run_includes_it(stubs, capsys):
    calls, board = stubs
    ing.main(["--no-scan"])
    assert {c[1] for c in calls if c[0] == "fetch"} == set(ing.SPECS)
    calls.clear()
    board[:] = board[:1]
    ing.main(["--apply"])
    fetched = {c[1] for c in calls if c[0] == "fetch"}
    assert "catalis" not in fetched and fetched == set(ing.SPECS) - {"catalis"}
    assert "except catalis" in capsys.readouterr().out


def test_a_short_parcel_in_another_county_does_not_hide_a_new_lead():
    """dedupe._strong_sigs has a STATE-wide parcel signature. Onslow's "801-154" and a Wake row
    numbered 801154 share it. The primary key is county-qualified, and that is the one used."""
    wake = L(parcel_id="801154", county="Wake", source="counties_generic.liensnc")
    rows = [wake]
    stats = ing.apply_rows(rows, [L(parcel_id="801-154", county="Onslow")])
    assert stats["added"] == 1 and stats["matched_untouched"] == 0 and len(rows) == 2


def test_the_batch_dedupe_keeps_two_houses_that_share_a_bad_parcel():
    a = L(parcel_id="9-9", street_address="306 Fountain Way")
    b = L(parcel_id="9-9", street_address="346 Fountain Way")
    assert len(ing._dedupe_batch([a, b])) == 2
    assert len(ing._dedupe_batch([a, L(parcel_id="9-9", street_address="306 Fountain Way")])) == 1


def test_the_batch_dedupe_does_not_fuse_rows_across_counties_on_a_state_wide_parcel_signature():
    rows = [L(parcel_id="801154", county="Onslow"), L(parcel_id="801-154", county="Graham")]
    assert len(ing._dedupe_batch(rows)) == 2
