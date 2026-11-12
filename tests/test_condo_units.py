"""Condominium units in Buncombe's parcel layer (docs/HANDOFF.md, the 2026-10-06 condo-pin entry).

Every unit of a condominium carries the building's 10-digit `pin` plus its own `pinext`
(`pinnum` = pin + pinext: 9627023924 is the 00000 common area plus 225 units). counties_nc.
buncombe_elderly wrote parcel_id = pin, so every exempt unit of a building was one property. These
tests pin: the scraper's new id, what that does to dedupe, and the carry-over of the 9 published
bare-pin rows of the same buildings (merge_prior_board), since without it the next full run adds a
row per unit and ages the old ones as presumed withdrawn.

REAL SHAPES. tests/fixtures/buncombe_elderly_condo_layer.json holds the live layer's attributes for
three buildings (captured 2026-10-06 with the scraper's own query) and two plain parcels, and the
published 10/5 board's rows of the same buildings (owner, street, first_seen, source_url). Owners
are replaced token by token (the same token maps to the same fictional one on both sides, so the
life-estate marker and the co-owner lists keep their shape); the owner's mailing block is replaced.
Parcel ids, situs and sale amounts are the public record's. Real cases the fixture holds:
  * 9645995181: units C0007 and C0013 share house number 201 (suffix 7 / 13): dedupe merged them
    into one row, so one owner's lead never reached the board;
  * 9627023924 C0102: the published row's street is the owner's mailing address, not the unit's;
  * 9627023924 C3804: the owner's name changed form between the board and the layer ('X Y (LE)' ->
    'Y X', a 2026-10-01 deed);
  * 9654438960 CB201: a unit with no published row.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from foreclosure_scraper import condo_units as C
from foreclosure_scraper.assessor_cards import buncombe_nc as card
from foreclosure_scraper.board_persist import drop_folded_prior, merge_prior_board
from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.enrichment_assessor_photo import buncombe_pin_variants
from foreclosure_scraper.models import Listing, ListingType, PropertyKind, _normalize_parcel
from foreclosure_scraper.parcel_cache import _lookup_candidates
from foreclosure_scraper.scrapers.counties_nc import buncombe_elderly as m
from foreclosure_scraper.validation import validate
from foreclosure_scraper.verification.core import row_keys
from foreclosure_scraper.verification.verifiers import elderly_disabled as ED
from foreclosure_scraper.verification.verifiers.tax_lien_buncombe import pin_of
from tests._arcgis_fakes import FakeHttp

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "buncombe_elderly_condo_layer.json")
                     .read_text())
NOW = datetime(2026, 10, 6, 12, 0, 0)
UNIT_PINNUMS = {f["attributes"]["pinnum"] for f in FIXTURE["features"]
                if f["attributes"]["pinnum"][10:] != "00000"}
ORDINARY = [f["attributes"] for f in FIXTURE["features"] if f["attributes"]["pinnum"][10:] == "00000"]


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _scrape(features=None) -> tuple[list[Listing], FakeHttp]:
    feats = FIXTURE["features"] if features is None else features
    http = FakeHttp(pages=[{"features": feats}, {"features": []}])
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        out = asyncio.run(m.BuncombeElderly().fetch())
    finally:
        m.client = original
    for li in out:
        li.first_seen = li.last_seen = NOW
    return list(out), http


def _by_pinnum(rows: list[Listing]) -> dict[str, Listing]:
    return {r.parcel_id: r for r in rows}


# --------------------------------------------------------------------------- the id
def test_unit_parts_and_the_published_parcel_id():
    assert C.unit_parts("9627023924C0102") == ("9627023924", "C0102")
    assert C.unit_parts("9627-02-3924-c0102") == ("9627023924", "C0102")
    assert C.unit_parts("9658814565C1000") == ("9658814565", "C1000")
    for plain in ("9627023924", "962702392400000", "9627023924-00000", "", None, "SC-1234"):
        assert C.unit_parts(plain) is None
    assert C.board_parcel_id("9627023924", "9627023924C0102") == "9627023924C0102"
    assert C.board_parcel_id("9627023924", "962702392400000") == "9627023924"   # same key, same string
    assert C.board_parcel_id("9627023924", None) == "9627023924"
    assert C.board_parcel_id("9627023924", "9645995181C0007") == "9627023924"   # another building's: not ours
    assert C.board_parcel_id("", "9627023924C0102") == "9627023924C0102"


def test_a_unit_pinnum_stays_a_distinct_dedupe_key_and_a_plain_pad_still_collapses():
    keys = {_normalize_parcel(p) for p in UNIT_PINNUMS}
    assert len(keys) == len(UNIT_PINNUMS)
    assert not keys & {"9627023924", "9645995181", "9654438960"}
    assert _normalize_parcel("962702392400000") == _normalize_parcel("9627023924") == "9627023924"
    # the one layer pinnum ending in 000 (C1000, no exemption today): the legacy '.000' rule shortens
    # it, it is still its own key and no other unit's
    assert _normalize_parcel("9658814565C1000") == "9658814565c1"
    assert _normalize_parcel("9658814565C1000") not in {_normalize_parcel("9658814565C0001"), "9658814565"}


# --------------------------------------------------------------------------- the scraper
def test_each_unit_is_its_own_property_and_a_plain_parcel_is_unchanged():
    rows, http = _scrape()
    assert len(rows) == 13
    by = _by_pinnum(rows)
    assert UNIT_PINNUMS <= set(by) and len(UNIT_PINNUMS) == 11
    # plain parcels: pinnum '<pin>00000' publishes the bare pin, exactly as before
    assert {a["pin"] for a in ORDINARY} == {"0609715480", "0605880879"} <= set(by)
    assert len({li.dedupe_key() for li in rows}) == 13
    for pn in UNIT_PINNUMS:
        assert by[pn].dedupe_key() == f"parcel:NC:buncombe:{pn.lower()}"
        assert by[pn].raw["owner_mailing"]["parcel_id"] == pn
    assert by["0609715480"].dedupe_key() == "parcel:NC:buncombe:0609715480"
    assert by["0609715480"].raw["owner_mailing"]["parcel_id"] == "0609715480"
    # the situs is the unit's own, not the owner's mailing block
    assert by["9627023924C0102"].street_address == "102 ROUGH POINT CT"
    # paging is stable inside a building: the layer's order has pinnum after pin
    assert http.calls[0][2]["orderByFields"] == "pin,pinnum"


def test_a_unit_row_survives_validation_and_a_second_dedupe():
    rows, _ = _scrape()
    validate(rows)
    assert UNIT_PINNUMS <= {li.parcel_id for li in rows}
    assert len(dedupe(rows)) == 13


def test_the_old_key_fused_two_owners_into_one_row_and_the_new_one_does_not():
    """9645995181: units C0007 and C0013 both read '201 RACQUET CLUB RD' (suffix 7 / 13) under one
    parcel id, so dedupe made them one lead. Replayed with the parcel_id the scraper used to
    write."""
    rows, _ = _scrape()
    pair = [li for li in rows if li.parcel_id.startswith("9645995181")]
    assert len(pair) == 2 and len({li.owner_name for li in pair}) == 2
    old = [li.model_copy(deep=True) for li in pair]
    for li in old:
        li.parcel_id = "9645995181"
    assert len(dedupe(old)) == 1                      # before: one of the two owners is gone
    assert len(dedupe([li.model_copy(deep=True) for li in pair])) == 2


def test_the_source_url_names_the_unit_and_still_satisfies_the_verifiers_check():
    rows, _ = _scrape()
    by = _by_pinnum(rows)
    unit = by["9627023924C3804"]
    assert "pin%3D%279627023924%27+AND+pinnum%3D%279627023924C3804%27" in unit.source_url
    plain = by["0609715480"]
    assert plain.source_url == (m.QUERY_URL + "?where=pin%3D%270609715480%27&outFields=*&f=html")
    for li in (unit, plain):
        row = li.model_dump(mode="json")
        assert ED.scraped_from_layer(row, li.parcel_id)
    # and the verifier looks a unit up by its pinnum, a plain parcel by its pin, as before
    assert ED.layer_query({"parcel_id": unit.parcel_id}) == ("pinnum", "9627023924C3804")
    assert ED.layer_query({"parcel_id": plain.parcel_id}) == ("pin", "0609715480")


def test_a_layer_row_without_pinnum_keeps_the_pin():
    (li,), _ = _scrape([{"attributes": {**ORDINARY[0], "pinnum": None}}])
    assert li.parcel_id == ORDINARY[0]["pin"]


# --------------------------------------------------------------------------- the joins
def test_the_joins_that_read_the_parcel_id_take_a_unit_pinnum_whole():
    unit = "9627023924C0102"
    # Spatialest image host: the unit's own key (live: a different image from the common area's)
    assert buncombe_pin_variants(unit) == [unit]
    assert buncombe_pin_variants("9627-02-3924-c0102") == [unit]
    assert buncombe_pin_variants("9639454911") == ["963945491100000", "9639454911"]    # unchanged
    # tax site and the verifiers
    assert pin_of({"parcel_id": unit}) == unit
    keys = {r: row_keys({"state": "NC", "county": "Buncombe", "parcel_id": r})[0] for r in UNIT_PINNUMS}
    assert len(set(keys.values())) == len(UNIT_PINNUMS)                         # one ledger key per unit
    assert row_keys({"state": "NC", "county": "Buncombe", "parcel_id": "0609715480"})[0] == \
        "parcel:NC:buncombe:0609715480"
    # the parcel cache is indexed by pinnum ('9627023924c0102' is a row of it): exact id, and no
    # fall back to the building's pin or its common area
    assert _lookup_candidates(unit) == [("9627023924c0102", "exact")]
    # assessor record card (Spatialest key = pinnum, letters included)
    assert card._pin_candidate(Listing(source="x", source_url="u", listing_type=ListingType.UNKNOWN,
                                       first_seen=NOW, last_seen=NOW, parcel_id=unit)) == unit
    assert card._pin_from_attrs({"pinnum": unit}) == unit
    assert card._pin_from_attrs(
        {"pinnum": None, "propcard": "https://prc-buncombe.spatialest.com/#/property/9645995181C0013"}
    ) == "9645995181C0013"
    assert card._pin_from_attrs({"pinnum": "962702392400000"}) == "962702392400000"


# --------------------------------------------------------------------------- the matcher
V = C.View


def test_owner_tiers():
    assert C.owner_tier("FENTON FAIRCLOTH (LE)", "FAIRCLOTH FENTON") == 3          # title marker, order
    assert C.owner_tier("QUINN RUTLEDGE;QUINN ROSALIND", "QUINN ROSALIND;QUINN RUTLEDGE") == 3
    assert C.owner_tier("SPIVEY SILAS D", "SPIVEY SILAS D;SPIVEY TILLERY G") == 2   # co-owner added
    assert C.owner_tier("SPIVEY SILAS", "SPIVEY TILLERY") == 0                      # a shared surname only
    assert C.owner_tier("", "SPIVEY SILAS") == 0 and C.owner_tier(None, None) == 0


def test_match_units_picks_the_unique_best_and_leaves_ties_unmatched():
    units = [V("ALPHA ONE", "10 A ST"), V("BRAVO TWO", "20 A ST"), V("CHARLIE THREE", "30 A ST")]
    assert C.match_units([V("BRAVO TWO", None)], units) == [1]
    assert C.match_units([V("DELTA FOUR", "10 A ST")], units) == [None]            # situs alone is no match
    # two units of one owner: the situs breaks the tie, else the row stays unmatched
    twin = [V("ALPHA ONE", "10 A ST"), V("ALPHA ONE", "11 A ST")]
    assert C.match_units([V("ALPHA ONE", "11 A ST")], twin) == [1]
    assert C.match_units([V("ALPHA ONE", "stale mailing street")], twin) == [None]
    # an exact owner beats a co-owner-added one
    mixed = [V("ALPHA ONE;ALPHA TWO", None), V("ALPHA ONE", None)]
    assert C.match_units([V("ALPHA ONE", None)], mixed) == [1]


def test_the_real_published_rows_each_pair_with_their_unit():
    prior = [V(p["owner_name"], p["street_address"]) for p in FIXTURE["prior_rows"]]
    by_pin: dict[str, list[int]] = {}
    for i, p in enumerate(FIXTURE["prior_rows"]):
        by_pin.setdefault(p["pin"], []).append(i)
    assert len(prior) == 9
    for pin, idxs in by_pin.items():
        feats = [f["attributes"] for f in FIXTURE["features"] if f["attributes"]["pin"] == pin]
        units = [V(a["owner"], " ".join(str(a[k] or "") for k in ("HouseNumber", "NumberSuffix", "streetname")))
                 for a in feats]
        picks = C.match_units([prior[i] for i in idxs], units)
        assert None not in picks and len(set(picks)) == len(picks)


# --------------------------------------------------------------------------- merge_prior_board
def _stale_raw(i: int) -> dict:
    """What the 10/5 board carried on these rows besides the scraper's own fields: the owner-keyed
    enrichment that is lost if the row is not carried over (the phone is a marker per row)."""
    return {"gis_exempt": {"code": "ELD", "tag": "elderly_exemption"},
            "life_event": "elderly_disabled_homestead",
            "owner_phone": {"phone": f"(828) 555-01{i:02d}", "source": "ncsbe_voter",
                            "match": "name+address"},
            "skip_trace": {"confidence": "medium", "email_addresses": [f"owner{i}@example.com"]},
            "images": {"aerial": "https://tiles.example/a.jpg", "primary": "https://tiles.example/a.jpg"}}


def _published_rows() -> list[Listing]:
    """The 10/5 board's rows of these buildings, as the old scraper wrote them (parcel_id = pin),
    plus the two plain parcels (same key before and after)."""
    out = []
    for i, p in enumerate(FIXTURE["prior_rows"]):
        out.append(Listing(
            source=m.BuncombeElderly.slug, source_url=p["source_url"],
            listing_type=ListingType.ELDERLY_DISABLED, property_kind=PropertyKind.UNKNOWN,
            owner_name=p["owner_name"], street_address=p["street_address"], state="NC",
            county="Buncombe", parcel_id=p["pin"],
            first_seen=datetime.fromisoformat(p["first_seen"]),
            last_seen=datetime.fromisoformat(p["last_seen"]), raw=_stale_raw(i)))
    for j, a in enumerate(ORDINARY):
        out.append(Listing(
            source=m.BuncombeElderly.slug,
            source_url=m.QUERY_URL + f"?where=pin%3D%27{a['pin']}%27&outFields=*&f=html",
            listing_type=ListingType.ELDERLY_DISABLED, owner_name=a["owner"], state="NC",
            county="Buncombe", parcel_id=a["pin"], first_seen=datetime(2026, 9, 22),
            last_seen=datetime(2026, 9, 22), raw=_stale_raw(50 + j)))
    return out


def _board(tmp_path, rows: list[Listing]) -> Path:
    (tmp_path / "listings.json").write_text(json.dumps([r.model_dump(mode="json") for r in rows]))
    return tmp_path


def _phone(li: Listing):
    return ((li.raw or {}).get("owner_phone") or {}).get("phone")


def test_the_published_bare_pin_rows_become_their_units_rows(tmp_path):
    prior = _published_rows()
    assert len(prior) == 11
    fresh, _ = _scrape()
    merged, st = merge_prior_board(fresh, docs_dir=_board(tmp_path, prior), now=NOW)

    # 13 units + plain parcels in, 13 rows out: no row added beside an old one, none aged
    assert len(merged) == 13 and len({li.dedupe_key() for li in merged}) == 13
    assert st["matched_condo_unit"] == 9 and st["condo_unit_unmatched"] == 0
    assert st["matched"] == 11 and st["fresh_only"] == 2 and st["prior_only_kept"] == 0
    assert not any(li.parcel_id in ("9627023924", "9645995181", "9654438960") for li in merged)
    assert not any((li.raw or {}).get("pulled_sale") for li in merged)

    by = _by_pinnum(merged)
    expect = {p["owner_name"]: _phone(prior[i]) for i, p in enumerate(FIXTURE["prior_rows"])}
    # each unit got ITS owner's carried enrichment, whatever the published row's street said
    assert _phone(by["9627023924C3606"]) == expect["ABERNATHY ADELINE BRANTLEY"]
    assert _phone(by["9645995181C0007"]) == expect["GILLIAM GRETA HARGROVE"]
    assert _phone(by["9654438960CD407"]) == expect["JARRETT(LE) JASPER"]
    assert _phone(by["9654438960CA102"]) == expect["KILPATRICK KENDRA B"]
    assert _phone(by["9627023924C0102"]) == expect["CORINNE DARNELL DELMAR;CORINNE EMBRY ELOISE"]
    # the owner's name changed form ('X Y (LE)' -> 'Y X'): still the same lead; fresh fields win
    assert _phone(by["9627023924C3804"]) == expect["FENTON FAIRCLOTH (LE)"]
    assert by["9627023924C3804"].owner_name == "FAIRCLOTH FENTON"
    # the published street was the owner's mailing address: the unit's own situs wins
    assert by["9627023924C0102"].street_address == "102 ROUGH POINT CT"
    assert "SAMPLE WAY" not in (by["9627023924C0102"].street_address or "")
    # first_seen is carried from the published row; a unit with no published row is new
    assert by["9627023924C3606"].first_seen == datetime(2026, 9, 22, 15, 36, 7, 845782)
    for new in ("9645995181C0013", "9654438960CB201"):
        assert _phone(by[new]) is None and by[new].first_seen == NOW
    # the plain parcels matched by their unchanged key
    assert _phone(by["0609715480"]) == "(828) 555-0150" and _phone(by["0605880879"]) == "(828) 555-0151"

    # the keys the GRANDFATHER snapshot must not restore: the 9 old building keys of this source
    folded = st["folded_prior_keys"]
    assert len(folded) == 9 and {s for _, s in folded} == {m.BuncombeElderly.slug}
    assert {k for k, _ in folded} == {"parcel:NC:buncombe:9627023924", "parcel:NC:buncombe:9645995181",
                                      "parcel:NC:buncombe:9654438960"}


def test_without_the_migration_the_next_run_would_double_every_unit(tmp_path, monkeypatch):
    """The hazard this change is guarded against (FULLRUN_PERSIST_CONDO_UNITS=0 is the old
    matching): every unit's row is added and the 9 published rows are aged as presumed withdrawn."""
    monkeypatch.setenv("FULLRUN_PERSIST_CONDO_UNITS", "0")
    fresh, _ = _scrape()
    merged, st = merge_prior_board(fresh, docs_dir=_board(tmp_path, _published_rows()), now=NOW)
    assert st["matched_condo_unit"] == 0 and st["prior_only_kept"] == 9 and st["matched"] == 2
    assert len(merged) == 22
    aged = [li for li in merged if (li.raw or {}).get("pulled_sale")]
    assert len(aged) == 9 and {li.parcel_id for li in aged} == {"9627023924", "9645995181", "9654438960"}


def test_a_published_row_whose_owner_holds_no_unit_of_the_building_ages_as_before(tmp_path):
    prior = _published_rows()
    gone = prior[0]
    gone.owner_name = "NOBODY FICTIONAL"
    gone.street_address = "3606 FLORHAM PL"        # the unit's own street does not make it the same lead
    fresh, _ = _scrape()
    merged, st = merge_prior_board(fresh, docs_dir=_board(tmp_path, prior), now=NOW)
    assert st["matched_condo_unit"] == 8 and st["condo_unit_unmatched"] == 1
    (old,) = [li for li in merged if li.parcel_id == "9627023924"]
    assert old.raw["pulled_sale"]["consecutive_misses"] == 1 and old.owner_name == "NOBODY FICTIONAL"
    assert _phone(_by_pinnum(merged)["9627023924C3606"]) is None        # its enrichment is not lent to another owner
    assert len(st["folded_prior_keys"]) == 8


def test_another_sources_row_on_the_building_pin_is_not_folded_into_a_unit(tmp_path):
    other = Listing(source="counties_generic.state_contamination.nc_ust_incidents",
                    source_url="https://example.org/ust/1", listing_type=ListingType.UNKNOWN,
                    owner_name="GILLIAM GRETA HARGROVE", street_address="201 RACQUET CLUB RD",
                    state="NC", county="Buncombe", parcel_id="9645995181",
                    first_seen=datetime(2026, 9, 22), last_seen=datetime(2026, 9, 22))
    fresh, _ = _scrape()
    merged, st = merge_prior_board(fresh, docs_dir=_board(tmp_path, [other]), now=NOW)
    assert st["matched_condo_unit"] == 0 and st["prior_only_kept"] == 1
    assert _phone(_by_pinnum(merged)["9645995181C0007"]) is None
    assert [li.source for li in merged if li.parcel_id == "9645995181"] == [other.source]


def test_a_building_the_fresh_scrape_does_not_list_ages_as_before(tmp_path):
    """A scrape that returns none of a building's units (source down, pin retired) is no evidence
    of a migration: its published bare-pin rows age like every other row not re-scraped."""
    fresh, _ = _scrape([f for f in FIXTURE["features"] if f["attributes"]["pin"] != "9654438960"])
    merged, st = merge_prior_board(fresh, docs_dir=_board(tmp_path, _published_rows()), now=NOW)
    assert st["matched_condo_unit"] == 5 and st["condo_unit_unmatched"] == 0
    assert st["prior_only_kept"] == 4
    assert len([li for li in merged if li.parcel_id == "9654438960"]) == 4


def test_drop_folded_prior_leaves_only_what_the_board_does_not_hold(tmp_path):
    prior = _published_rows()
    fresh, _ = _scrape()
    _, st = merge_prior_board(fresh, docs_dir=_board(tmp_path, prior), now=NOW)
    ust = Listing(source="counties_generic.state_contamination.nc_ust_incidents",
                  source_url="https://example.org/ust/1", listing_type=ListingType.UNKNOWN,
                  state="NC", county="Buncombe", parcel_id="9645995181",
                  first_seen=datetime(2026, 9, 22), last_seen=datetime(2026, 9, 22))
    snapshot = prior + [ust]
    kept = drop_folded_prior(snapshot, st)
    # the 9 folded rows go; the plain parcels (matched by their own key) and another source's row stay
    assert len(kept) == len(snapshot) - 9 and ust in kept
    assert not any(li.parcel_id in ("9627023924", "9645995181", "9654438960")
                   and li.source == m.BuncombeElderly.slug for li in kept)
    assert drop_folded_prior(snapshot, {}) is snapshot
    assert drop_folded_prior(snapshot, {"folded_prior_keys": []}) is snapshot
