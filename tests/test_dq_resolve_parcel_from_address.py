"""resolve_parcel_from_address: street parsing, the full-name agreement rule, uniqueness over the parcel cache's
duplicate id rows, the unit / suffix / direction / city / ZIP guards, id choice, source and county guards, the
apply_rows contract, and the hold-out. Everything runs on synthetic caches in a temp dir: no board, no network."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _dq_common as C  # noqa: E402
import resolve_parcel_from_address as R  # noqa: E402
from foreclosure_scraper import parcel_cache as pc  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402

COLS = "id TEXT, owner TEXT, address TEXT, owner_mailing TEXT, market_value REAL, tax_value REAL, acreage REAL, " \
       "living_sqft REAL, land_use TEXT, sale_price REAL, sale_date TEXT"


def P(text):
    st, why = R.parse_street(text)
    assert st is not None, (text, why)
    return st


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture
def caches(tmp_path, monkeypatch):
    """A temp parcel-cache dir plus a writer. parcel_cache keeps one open connection per file NAME, so it is reset."""
    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(pc, "_CONN", {})

    def make(county, parcels, state=None):
        """parcels: [(ids, owner, address, mailing, market_value)]. Every id is one cache row, like the real builds."""
        path = pc._db_path(county, state)
        con = sqlite3.connect(path)
        con.execute(f"CREATE TABLE parcels({COLS})")
        for ids, owner, address, mailing, mv in parcels:
            for i in ids:
                con.execute("INSERT INTO parcels VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (i, owner, address, mailing, mv, None, 0.3, 1800.0, None, None, None))
        con.execute("CREATE INDEX idx_id ON parcels(id)")
        con.commit()
        con.close()
    return make


@pytest.fixture
def registered(monkeypatch):
    monkeypatch.setattr(C, "missing_raw_keep", lambda keys: [])


def _li(**kw):
    base = dict(source="national.liensnc", source_url="https://example.invalid/1", listing_type=ListingType.TAX_LIEN,
                state="NC", county="Wake", raw={})
    base.update(kw)
    return Listing(**base)


def _resolve(leads_cache_county="Wake", state="NC", **lead):
    """Resolve one lead street through a real CountyIndex over whatever the caches fixture wrote."""
    st = P(lead["street"])
    idx = R.CountyIndex.build(leads_cache_county, state, {(st.num, R.anchor_word(st))})
    try:
        return idx.resolve(st, city=lead.get("city", ""), zip_code=lead.get("zip", ""))
    finally:
        idx.close()


# ------------------------------------------------------------------------------------------ parse_street
@pytest.mark.parametrize("text,num,numsuf,dirs,name,suffix,unit", [
    ("3700 Taylor Glen Lane", 3700, "", set(), ("TAYLOR", "GLN"), "LN", ""),
    ("000141 LEVI DR", 141, "", set(), ("LEVI",), "DR", ""),                                   # McDowell pads the number
    ("12C TOXAWAY FALLS DR     .86", 12, "C", set(), ("TOXAWAY", "FLS"), "DR", ""),          # the county appends acreage
    ("100 N Main St NW", 100, "", {"N", "NW"}, ("MAIN",), "ST", ""),
    ("100 East St", 100, "", set(), ("EAST",), "ST", ""),                                     # EAST is the name here
    ("221 St James Pl", 221, "", set(), ("SAINT", "JAMES"), "PL", ""),
    ("330 old boiling springs road", 330, "", set(), ("OLD", "BOILING", "SPRINGS"), "RD", ""),
    ("1000 E WOODLAWN RD, 203 CHARLOTTE NC", 1000, "", {"E"}, ("WOODLAWN",), "RD", "203"),
    ("228 norman Ridge LN TWNH 187", 228, "", set(), ("NORMAN", "RDG"), "LN", "187"),
    ("3101 Camden Dr Apt 4", 3101, "", set(), ("CAMDEN",), "DR", "4"),
    ("12-B Main St", 12, "B", set(), ("MAIN",), "ST", ""),
    ("6 Bv Bridge Way", 6, "", set(), ("BLVD", "BRG"), "WAY", ""),                            # BV: Charlotte's spelling of BLVD
])
def test_parse_street(text, num, numsuf, dirs, name, suffix, unit):
    s = P(text)
    assert (s.num, s.numsuf, set(s.dirs), s.name, s.suffix, s.unit) == (num, numsuf, dirs, name, suffix, unit)


@pytest.mark.parametrize("text,why", [
    ("", "empty"), (None, "empty"), ("831/833 N Oak St", "range"), ("831-833 N Oak St", "range"),
    ("123 1/2 Main St", "range"), ("PO BOX 5", "no_number"), ("MEADOW RD", "no_number"),
    ("0 CALHOUN TRL", "sentinel"), ("99999 DUCKERS VW", "sentinel"), ("1163", "no_street_name"),
])
def test_parse_street_rejects_what_is_not_one_numbered_address(text, why):
    assert R.parse_street(text) == (None, why)


def test_a_route_number_stays_in_the_road_name_and_a_city_after_the_suffix_does_not():
    assert P("1500 NC HWY 74 W").name == ("NC", "HWY", "74", "W") and P("1500 NC HWY 74 W").suffix == ""
    assert P("1500 NC HWY 27 W").name != P("1500 NC HWY 74 W").name
    s = P("1101 PARTRIDGE RD SPARTANBURG")
    assert s.name == ("PARTRIDGE",) and s.suffix == "RD" and s.trail == ("SPARTANBURG",)
    assert P("4417 LARKHAVEN VILLAGE DR UNINC NC").trail == ("UNINC",)


# --------------------------------------------------------------------------------------- street_agrees
def _agree(lead, cache, city=""):
    return R.street_agrees(P(lead), P(cache), R._city_words(city))


def test_the_whole_street_name_must_agree_not_one_shared_word():
    assert _agree("12 Oak Hill Rd", "12 OAK HILL RD")
    assert not _agree("12 Oak Rd", "12 OAK HILL RD")                # the older Burke rule accepted this
    assert not _agree("12 Hill Rd", "12 OAK HILL RD")
    assert not _agree("12 Oak Rd", "13 OAK RD")                     # house number
    assert not _agree("12C Oak Rd", "12 OAK RD") and not _agree("12 Oak Rd", "12C OAK RD")
    assert _agree("141 Levi Dr", "000141 LEVI DR")


def test_two_different_suffixes_never_agree_but_one_side_may_omit_its_suffix():
    assert not _agree("12 Oak St", "12 OAK CT")
    assert not _agree("341 Allen St.", "341 ALLEN CT SPARTANBURG")
    assert _agree("12 Oak", "12 OAK ST") and _agree("12 Oak St", "12 OAK")
    assert _agree("3270 Beaver Creek", "3270 BEAVER CREEK DR")     # CREEK is a suffix word, here the end of the name
    assert _agree("1541 Salt Pond Way", "1541 SALT POND WAY SW")   # a quadrant is not a different street


def test_a_direction_must_agree_and_may_not_be_stated_on_one_side_only_except_a_quadrant():
    assert not _agree("100 N Main St", "100 S MAIN ST")
    assert not _agree("100 Main St", "100 N MAIN ST") and not _agree("100 N Main St", "100 MAIN ST")
    assert _agree("100 N Main St", "100 N MAIN ST") and _agree("100 Main St NW", "100 MAIN ST NW")
    assert _agree("1157 Sabel Loop", "1157 SABEL LOOP SE")                    # a county-wide quadrant the lead left off
    assert not _agree("1157 Sabel Loop SE", "1157 SABEL LOOP")                # but a lead that states one must be matched
    assert not _agree("1157 Sabel Loop SE", "1157 SABEL LOOP NW")


def test_town_conflicts_reject_a_missing_town_does_not():
    assert _agree("1101 Partridge Rd", "1101 PARTRIDGE RD SPARTANBURG")                       # no lead city: not judged
    assert _agree("1101 Partridge Rd", "1101 PARTRIDGE RD SPARTANBURG", city="Spartanburg")
    assert not _agree("1101 Partridge Rd", "1101 PARTRIDGE RD SPARTANBURG", city="Boiling Springs")
    assert _agree("4417 Walter Nelson rd", "4417 WALTER NELSON RD MINT HILL NC", city="Mint hill")   # HILL is a suffix word
    assert not _agree("4417 Walter Nelson rd", "4417 WALTER NELSON RD MINT HILL NC", city="Charlotte")
    assert _agree("4417 Larkhaven Village Dr", "4417 LARKHAVEN VILLAGE DR UNINC NC", city="Charlotte")   # UNINC is no town
    assert _agree("70 Fox Wood", "70  FOX WOOD   SANFORD", city="Sanford")     # town in place of a suffix
    assert not _agree("70 Fox Wood", "70  FOX WOOD   SANFORD", city="Angier")


# -------------------------------------------------------------------------------------- uniqueness rules
def test_unique_match_groups_the_duplicate_id_rows_of_one_parcel(caches):
    caches("Wake", [(("1736642838", "0448960", "371830695327712"), "MERITAGE HOMES LLC", "5918 FALLOWFIELD LN", "PO BOX 1 CARY NC", 500000.0),
                    (("1111111111",), "OTHER OWNER", "5920 FALLOWFIELD LN", None, 1.0)])
    r = _resolve(street="5918 Fallowfield Lane")
    assert r.status == "unique" and set(r.ids) == {"1736642838", "0448960", "371830695327712"}
    assert r.group.owner == "MERITAGE HOMES LLC"


def test_two_parcels_at_one_address_are_ambiguous(caches):
    caches("Wake", [(("A1", "A2"), "ONE", "55 PINE ST", None, 1.0), (("B1", "B2"), "TWO", "55 PINE ST", None, 2.0)])
    r = _resolve(street="55 Pine St")
    assert r.status == "ambiguous"


def test_two_groups_that_share_a_specific_id_are_one_parcel(caches):
    """One PIN published twice with different attributes (a multi-part parcel): the address still names that parcel,
    and only the id both rows carry is written."""
    caches("Wake", [(("p1", "p1alt"), "OWNER", "9 ELM ST", None, 1.0), (("p1", "p1alt2"), "OWNER", "9 ELM ST", None, 2.0)])
    r = _resolve(street="9 Elm St")
    assert r.status == "unique" and r.ids == ("p1",)


def test_a_placeholder_id_is_never_written_and_a_parcel_that_has_only_one_is_refused(caches):
    """Cumberland's '37051' sits on thousands of rows. It is not a parcel."""
    junk = [(("37051",), f"OWNER {i}", f"{i + 100} JUNK ST", None, 1.0) for i in range(6)]
    caches("Wake", junk + [(("37051", "REAL0001"), "GOOD OWNER", "500 REAL ST", None, 1.0)])
    r = _resolve(street="500 Real St")
    assert r.status == "unique" and r.ids == ("REAL0001",)
    r = _resolve(street="103 Junk St")
    assert r.status == "no_specific_id"


def test_unit_rules(caches):
    caches("Wake", [(("U1",), "A", "100 MAIN ST, 1 CITY NC", None, 1.0), (("U2",), "B", "100 MAIN ST, 2 CITY NC", None, 1.0),
                    (("E1",), "C", "100 ELM ST", None, 1.0), (("F1",), "D", "200 FIR ST", None, 1.0),
                    (("F2",), "E", "200 FIR ST, 5 CITY NC", None, 1.0)])
    r = _resolve(street="100 Main St Apt 2")
    assert r.status == "unique" and r.ids == ("U2",)                                    # the one parcel carrying that unit
    assert _resolve(street="100 Main St").status == "unit_rejected"                     # no unit: never a unit parcel
    assert _resolve(street="100 Main St Unit 9").status == "unit_rejected"              # unit the cache does not know
    assert _resolve(street="100 Elm St Apt 4").status == "unique"                       # every candidate unit-less, exactly one
    r = _resolve(street="200 Fir St")
    assert r.status == "unique" and r.ids == ("F1",)                                    # the unit-less parcel, not the unit one


def test_zip_conflict_needs_the_owner_to_mail_to_the_property(caches):
    caches("Wake", [(("Z1",), "OWNER", "12 OAK ST", "12 OAK ST RALEIGH NC 27601", 1.0),
                    (("Z2",), "LANDLORD", "14 OAK ST", "PO BOX 9 CARY NC 27511", 1.0)])
    assert _resolve(street="12 Oak St", zip="27601").status == "unique"
    assert _resolve(street="12 Oak St", zip="27601-1234").status == "unique"
    assert _resolve(street="12 Oak St", zip="27502").status == "zip_conflict"           # same street in another town
    assert _resolve(street="14 Oak St", zip="27502").status == "unique"                 # a mailing elsewhere proves nothing


# ------------------------------------------------------------------------------------------- id choice
def test_choose_id_prefers_the_board_spelling_then_the_common_length():
    bmap = {"0448960": "0448960"}
    assert R.choose_id(["1736642838", "0448960", "371830695327712"], bmap, R.Counter({10: 5, 7: 1})) == ("0448960", "board_existing")
    pid, basis = R.choose_id(["1736642838", "0448960", "371830695327712"], {}, R.Counter({10: 5, 7: 1}))
    assert (pid, basis) == ("1736642838", "cache_form")
    assert R.choose_id(["01006002b", "3717901006002b"], {}, R.Counter({9: 3}))[0] == "01006002B"


def test_board_id_map_links_a_tolerant_spelling_to_the_boards_own_string():
    m = R.board_id_map(["4871515266.000"])
    assert m["4871515266000"] == "4871515266.000" and m.get("4871515266") == "4871515266.000"


def test_owner_verdict():
    assert R.owner_verdict("Meritage Homes", "MERITAGE HOMES OF THE CAROLINAS INC") is True
    assert R.owner_verdict("Ganesh Panchapagesan", "PANCHAPAGESAN, GANESH JA") is True
    assert R.owner_verdict("Revolution Homes", "CHILDREN OF JULIE LLC") is False
    assert R.owner_verdict("", "SOMEONE") is None and R.owner_verdict("A B", None) is None
    assert R.owner_verdict("UNKNOWN OWNER", "SOMEONE ELSE") is None


# --------------------------------------------------------------------------------------------- apply_rows
def _wake_cache(caches):
    caches("Wake", [(("1736642838", "0448960"), "MERITAGE HOMES LLC", "5918 FALLOWFIELD LN", "PO BOX 1 CARY NC 27511", 500000.0),
                    (("1764941327",), "SOMEONE ELSE", "764 LUNAR LIGHT DR", None, 1.0),
                    (("1800000001",), "X", "1 OTHER RD", None, 1.0), (("1800000002",), "X", "2 OTHER RD", None, 1.0),
                    (("1800000003",), "X", "3 OTHER RD", None, 1.0)])


def test_apply_rows_dry_run_mutates_nothing_and_a_real_run_fills(caches, registered):
    _wake_cache(caches)
    rows = [_li(street_address="5918 Fallowfield Lane", owner_name="Meritage Homes"),
            _li(street_address="764 Lunar Light Drive", owner_name="Garman Homes"),
            _li(street_address="12 Nowhere Ave"),
            _li(street_address="1 Other Road", parcel_id="1800000001")]      # the county's board ids are 10 digits
    before = [r.model_dump(mode="json") for r in rows]
    res = R.apply_rows(rows, dry_run=True)
    assert [r.model_dump(mode="json") for r in rows] == before
    assert res["resolved"] == 2 and res["no_match"] == 1 and res["owner_agrees_True"] == 1 and res["owner_agrees_False"] == 1
    res = R.apply_rows(rows)
    assert len(rows) == 4 and "_backup" not in res
    assert rows[0].parcel_id == "1736642838" and rows[1].parcel_id == "1764941327" and rows[2].parcel_id is None
    blk = rows[0].raw["parcel_from_address"]
    assert blk["source"] == "parcel_cache_situs_address" and blk["matched_situs"] == "5918 FALLOWFIELD LN"
    assert blk["owner_agrees"] is True and blk["county"] == "Wake" and blk["state"] == "NC"
    assert rows[1].raw["parcel_from_address"]["owner_agrees"] is False
    assert "parcel_from_address" not in rows[2].raw
    assert R.apply_rows(rows)["skip_has_parcel"] == 3                         # idempotent: resolved leads are now skipped


def test_the_board_spelling_of_a_parcel_already_on_the_board_is_reused(caches, registered):
    _wake_cache(caches)
    rows = [_li(street_address="5918 Fallowfield Lane"),
            _li(street_address="1 Other Road", parcel_id="1800000001"), _li(street_address="2 Other Road", parcel_id="1800000002"),
            _li(street_address="3 Other Road", parcel_id="1800000003"),
            _li(street_address="99 Somewhere Rd", parcel_id="0448960")]       # the same parcel, on the board under its REID
    R.apply_rows(rows)
    assert rows[0].parcel_id == "0448960" and rows[0].raw["parcel_from_address"]["id_basis"] == "board_existing"


def test_guards_leave_these_leads_alone(caches, registered):
    _wake_cache(caches)
    rows = [_li(street_address="5918 Fallowfield Lane", parcel_id="9999999"),                          # a parcel already
            _li(street_address="5918 Fallowfield Lane", county=None),                                  # no county
            _li(street_address="5918 Fallowfield Lane", county="Buncombe"),                            # no cache for the county
            _li(street_address="5918 Fallowfield Lane", listing_type=ListingType.TAX_SALE_OVERAGE),    # cache owner is not the claimant
            _li(street_address="5918 Fallowfield Lane", state="SC"),                                   # Wake is not an SC county
            _li(street_address="5918 Fallowfield Lane", source="counties_nc.landwatch"),               # its street is not the situs
            _li(street_address="", county="Wake"),
            _li(street_address="MEADOW RD"), _li(street_address="831/833 N Oak St")]
    res = R.apply_rows(rows)
    assert res.get("resolved", 0) == 0
    assert res["skip_has_parcel"] == 1 and res["skip_no_county"] == 1 and res["no_cache"] == 1
    assert res["skip_tax_sale_overage"] == 1 and res["skip_county_not_in_state"] == 1
    assert res["skip_source_street_is_not_situs"] == 1 and res["skip_no_address"] == 1 and res["rejected_street"] == 2
    assert [r.parcel_id for r in rows] == ["9999999"] + [None] * 8


def test_a_dual_state_county_reads_only_its_own_states_cache(caches, registered):
    caches("Cherokee", [(("NC0001",), "NC OWNER", "5 ELM ST", None, 1.0)], state="NC")
    caches("Cherokee", [(("SC0001",), "SC OWNER", "5 ELM ST", None, 1.0)], state="SC")
    rows = [_li(county="Cherokee", state="NC", street_address="5 Elm St"), _li(county="Cherokee", state="SC", street_address="5 Elm St"),
            _li(county="Cherokee", state=None, street_address="5 Elm St")]
    R.apply_rows(rows)
    assert rows[0].parcel_id == "NC0001" and rows[1].parcel_id == "SC0001" and rows[2].parcel_id is None


def test_a_real_run_refuses_before_touching_any_row_when_the_raw_key_is_unregistered(caches, monkeypatch):
    _wake_cache(caches)
    monkeypatch.setattr(C, "missing_raw_keep", lambda keys: list(keys))
    rows = [_li(street_address="5918 Fallowfield Lane")]
    with pytest.raises(RuntimeError, match="parcel_from_address"):
        R.apply_rows(rows)
    assert rows[0].parcel_id is None and rows[0].raw == {}
    assert R.apply_rows(rows, dry_run=True)["resolved"] == 1                  # a dry run needs no registration


def test_the_module_declares_the_raw_key_it_stamps():
    assert R.REQUIRED_RAW_KEYS == ["parcel_from_address"] and callable(R.apply_rows)


# ----------------------------------------------------------------------------------------------- hold-out
def test_holdout_counts_correct_wrong_and_ignores_a_parcel_that_is_not_at_the_address(caches):
    caches("Wake", [(("t1", "t1b"), "A", "12 OAK HILL RD", None, 1.0),            # lead 1: correct
                    (("t2",), "B", "99 ZZ RD", None, 1.0),                        # lead 2's own parcel is elsewhere: no truth
                    (("t3",), "C", "30 PINE ST", None, 1.0), (("t3x",), "D", "30 PINE ST", None, 1.0),   # lead 3: ambiguous
                    (("t4",), "E", "50 CEDAR LN ANGIER", None, 1.0),              # lead 4's own parcel (town ANGIER)
                    (("t5",), "F", "50 CEDAR LN", None, 1.0)])                    # a different parcel with no town
    rows = [{"source": "counties_nc.tax_roll", "state": "NC", "county": "Wake", "parcel_id": "t1", "street_address": "12 Oak Hill Rd"},
            {"source": "counties_nc.tax_roll", "state": "NC", "county": "Wake", "parcel_id": "t2", "street_address": "7 Elm St"},
            {"source": "counties_nc.tax_roll", "state": "NC", "county": "Wake", "parcel_id": "t3", "street_address": "30 Pine St"},
            {"source": "counties_nc.tax_roll", "state": "NC", "county": "Wake", "parcel_id": "t4", "street_address": "50 Cedar Ln",
             "city": "Erwin"}]
    corpus = R.collect_dicts(rows)
    h = R.evaluate_holdout(corpus)
    c = h["per"][("NC", "Wake")]
    assert c["pop"] == 3 and c["own_parcel_elsewhere"] == 1
    assert c["resolved"] == 2 and c["correct"] == 1 and c["ambiguous"] == 1
    assert c["wrong"] == 1                                    # the lead named Erwin: T4 (ANGIER) is rejected, T5 is unique but not its parcel
    assert h["wrong_samples"][0][2] == "t4"


def test_holdout_leaves_out_a_street_that_came_from_a_cache_or_a_parcel_from_coordinates(caches):
    caches("Wake", [(("T1",), "A", "12 OAK HILL RD", None, 1.0)])
    base = {"source": "counties_nc.x", "state": "NC", "county": "Wake", "parcel_id": "T1", "street_address": "12 Oak Hill Rd"}
    rows = [dict(base, raw={"situs_address_source": "parcel_cache:exact"}), dict(base, raw={"parcel_from_geo": {"source": "x"}}),
            dict(base, raw={"resolved_from_name": {"a": 1}})]
    assert R.collect_dicts(rows).holdout == []
    assert len(R.collect_dicts([base]).holdout) == 1


# --------------------------------------------------------------------------------- lift and the report
def test_expected_fills_count_only_what_the_lead_lacks_and_the_parcel_has(caches):
    caches("Wake", [(("1736642838", "0448960"), "MERITAGE HOMES LLC", "5918 FALLOWFIELD LN", "PO BOX 1 CARY NC 27511", 500000.0)])
    rows = [{"source": "national.liensnc", "state": "NC", "county": "Wake", "street_address": "5918 Fallowfield Lane",
             "owner_name": "Meritage Homes", "raw": {"owner_mailing": {"mailing": "1 X ST"}}},
            {"source": "counties_nc.x", "state": "NC", "county": "Wake", "street_address": "5918 Fallowfield Lane", "owner_name": ""}]
    corpus = R.collect_dicts(rows)
    results, per = R.resolve_targets(corpus)
    add = R.lift(corpus, results)["NC"]
    assert add["resolved"] == 2 and add["mailing"] == 1 and add["owner"] == 1 and add["market_value"] == 2
    assert per[("NC", "Wake")]["unique"] == 2
    lines: list = []
    R.print_report(corpus, results, per, None, out=lines.append)
    assert any("EXPECTED FILLS" in ln for ln in lines) and any("NC (2 rows" in ln for ln in lines)


def test_a_county_with_no_cache_is_counted_not_resolved(caches):
    rows = [{"source": "national.liensnc", "state": "SC", "county": "Beaufort", "street_address": "5 Elm St"}]
    results, per = R.resolve_targets(R.collect_dicts(rows))
    assert per[("SC", "Beaufort")]["no_cache"] == 1 and results[0][1].status == "no_cache"
