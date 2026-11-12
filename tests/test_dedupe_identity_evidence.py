"""dedupe() must never merge two DIFFERENT properties on address similarity (2026-10-06).

THE DEFECT. The first dedupe() of a full run (main.run(), over the fresh scrape) folded different
properties into one row, and those leads vanished from the board every run. Replayed on a fresh
four-source scrape (spartanburg_vacant, spartanburg_condemned, buncombe_delinquent_tax,
rutherford_tax; 16,932 records): 755 output rows had absorbed 2,596 records of other properties
(2,339 distinct valid parcels). The matching rules that did it:

  * pass 2 (fuzzy, token_set_ratio >= 92 in one zip or county). The house-number guard
    (_provably_different_property) fires only when BOTH rows carry DIFFERENT numbers. A county's
    "no house number" sentinel reads as the number "0"/"99999" on both sides, so 33 different
    "0 SOUTHPORT RD" lots (33 parcels) became one row; a numberless street ("LOOKOUT RD") has no
    number at all, so it matched every house on its road; same-number different-street pairs
    ('128 GEORGE ST' / '128 GEORGIA ST') score >= 92 too.
  * pass 3 (signatures). The canonical-street signature ('0 southport rd', county, state) joined
    the ROEBUCK lots to the SPARTANBURG ones; '123 WILLIAMS ST SPARTANBURG' to '123 WILLIAMS ST
    WOODRUFF'.

THE FIX (dedupe.identity_conflict, applied to every merge in all three passes, group against
group): two different real house numbers, or two different VALID parcels (placeholder_twins.
parcel_key, not resolver-attached), never merge; a row with no real house number (none, or a
sentinel) needs agreeing valid parcels to match a numbered row, or to match another unnumbered
row on address evidence alone.

Every fixture row below is a REAL row from that scrape (source, parcel, situs, owner) unless it
says otherwise.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from rapidfuzz import fuzz

from foreclosure_scraper import dedupe as D
from foreclosure_scraper.board_dedupe_stream import find_dedupe_merge_groups
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import _to_dict, write_artifact

T = datetime(2026, 10, 5, 20, 5)

SPBG_VACANT = ("counties_sc.spartanburg_vacant",
               "https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/"
               "City_Owned_and_Vacant_Properties/FeatureServer/0", ListingType.UNKNOWN, "SC",
               "Spartanburg", None)
SPBG_CONDEMNED = ("counties_sc.spartanburg_condemned",
                  "https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/"
                  "FeatureServer/0", ListingType.UNKNOWN, "SC", "Spartanburg", None)
SPBG_TAX = ("counties_sc.spartanburg_delinquent_tax",
            "https://www.spartanburgcounty.org/delinquent-tax", ListingType.TAX_LIEN, "SC",
            "Spartanburg", None)
BUNCOMBE_DT = ("counties_nc.buncombe_delinquent_tax",
               "https://media.buncombenc.gov/common/tax/"
               "buncombe-county-tax-department-advertisement-of-tax-liens.pdf",
               ListingType.TAX_LIEN, "NC", "Buncombe", None)
BUNCOMBE_ELDERLY = ("counties_nc.buncombe_elderly", "https://gis.buncombecounty.org/elderly",
                    ListingType.UNKNOWN, "NC", "Buncombe", None)
RUTHERFORD = ("counties_nc.rutherford_tax",
              "https://www.rutherfordcountync.gov/TR-452%20Delinquent%20Bills%20Report%20w%20"
              "Parcel%20Id.xlsx", ListingType.TAX_LIEN, "NC", "Rutherford", "28043")
RUTHERFORD_WILDFIRE = ("counties_nc.rutherford_wildfire_tax", "https://www.rutherfordcountync.gov/wildfire",
                       ListingType.TAX_LIEN, "NC", "Rutherford", None)


def row(src, parcel, addr, owner=None, **kw) -> Listing:
    source, url, lt, st, county, zip_code = src
    base = dict(source=source, source_url=url, listing_type=lt, state=st, county=county,
                zip_code=zip_code, parcel_id=parcel, street_address=addr, owner_name=owner,
                first_seen=T, last_seen=T)
    base.update(kw)
    return Listing(**base)


def parcels(out) -> list:
    return sorted(li.parcel_id for li in out)


# --------------------------------------------------------------------------- the 33 lots
# Every "0 SOUTHPORT RD" lot in spartanburg_vacant's scrape: 30 SPARTANBURG + 3 ROEBUCK, 33
# different county parcels. The old dedupe() returned ONE row for all 33.
SOUTHPORT_LOTS = [
    ("710284676520", "0 SOUTHPORT RD SPARTANBURG"), ("711220615817", "0 SOUTHPORT RD ROEBUCK"),
    ("713213957176", "0 SOUTHPORT RD SPARTANBURG"), ("711168574618", "0 SOUTHPORT RD SPARTANBURG"),
    ("710285913885", "0 SOUTHPORT RD SPARTANBURG"), ("710284789999", "0 SOUTHPORT RD SPARTANBURG"),
    ("714234782126", "0 SOUTHPORT RD SPARTANBURG"), ("712282997407", "0 SOUTHPORT RD SPARTANBURG"),
    ("711189224086", "0 SOUTHPORT RD SPARTANBURG"), ("712129845645", "0 SOUTHPORT RD SPARTANBURG"),
    ("712210315658", "0 SOUTHPORT RD SPARTANBURG"), ("712261025967", "0 SOUTHPORT RD SPARTANBURG"),
    ("710294105119", "0 SOUTHPORT RD SPARTANBURG"), ("713224941709", "0 SOUTHPORT RD SPARTANBURG"),
    ("710294329873", "0 SOUTHPORT RD SPARTANBURG"), ("711199059796", "0 SOUTHPORT RD SPARTANBURG"),
    ("712261240559", "0 SOUTHPORT RD SPARTANBURG"), ("711250750014", "0 SOUTHPORT RD ROEBUCK"),
    ("711220202663", "0 SOUTHPORT RD ROEBUCK"), ("713224432859", "0 SOUTHPORT RD SPARTANBURG"),
    ("711168862035", "0 SOUTHPORT RD SPARTANBURG"), ("714262092033", "0 SOUTHPORT RD SPARTANBURG"),
    ("713254348062", "0 SOUTHPORT RD SPARTANBURG"), ("710292409725", "0 SOUTHPORT RD SPARTANBURG"),
    ("710282877776", "0 SOUTHPORT RD SPARTANBURG"), ("710282931055", "0 SOUTHPORT RD SPARTANBURG"),
    ("710291143639", "0 SOUTHPORT RD SPARTANBURG"), ("712271287439", "0 SOUTHPORT RD SPARTANBURG"),
    ("712261673429", "0 SOUTHPORT RD SPARTANBURG"), ("712270995035", "0 SOUTHPORT RD SPARTANBURG"),
    ("711189486597", "0 SOUTHPORT RD SPARTANBURG"), ("712138699137", "0 SOUTHPORT RD SPARTANBURG"),
    ("713212593352", "0 SOUTHPORT RD SPARTANBURG"),
]
# Numbered Southport rows of the same scrape, including two situs that each carry TWO parcels.
SOUTHPORT_NUMBERED = [
    ("712282562530", "1665 SOUTHPORT RD SPARTANBURG"), ("711250006385", "640 SOUTHPORT RD ROEBUCK"),
    ("710294491882", "115 SOUTHPORT RD SPARTANBURG"), ("710294464234", "115 SOUTHPORT RD SPARTANBURG"),
    ("711202299812", "221 SOUTHPORT RD SPARTANBURG"), ("710292942975", "221 SOUTHPORT RD SPARTANBURG"),
    ("710294141471", "116 SOUTHPORT RD SPARTANBURG"), ("711118481588", "491 SOUTHPORT RD ROEBUCK"),
]


def test_the_rule_that_fused_them():
    """Pinned: the old guard sees '0' == '0' (no conflict) and the fuzzy score is 100, so pass 2
    merged every pair; pass 3's canonical-street signature is the same for SPARTANBURG and
    ROEBUCK lots."""
    a, b = (row(SPBG_VACANT, p, s) for p, s in SOUTHPORT_LOTS[:2])
    assert D._provably_different_property(a, b) is False
    assert fuzz.token_set_ratio(D._norm_addr(a.street_address),
                                D._norm_addr(SOUTHPORT_LOTS[2][1])) == 100
    assert {s for s in D._strong_sigs(a) if s[0] == "s"} == {s for s in D._strong_sigs(b)
                                                             if s[0] == "s"}
    assert D.identity_conflict(D.identity(a), D.identity(b)) == "parcel"


def test_33_southport_lots_stay_33_rows():
    rows = [row(SPBG_VACANT, p, s) for p, s in SOUTHPORT_LOTS]
    out = D.dedupe(rows)
    assert len(out) == 33
    assert parcels(out) == sorted(p for p, _ in SOUTHPORT_LOTS)


def test_southport_lots_and_houses_together_every_parcel_once():
    rows = [row(SPBG_VACANT, p, s) for p, s in SOUTHPORT_LOTS + SOUTHPORT_NUMBERED]
    out = D.dedupe(rows)
    assert parcels(out) == sorted(p for p, _ in SOUTHPORT_LOTS + SOUTHPORT_NUMBERED)


# ------------------------------------------------------------ the other real fusion shapes
REAL_DIFFERENT = {
    # numbered house + numberless road, different parcels (pass 2)
    "banks_town": [(BUNCOMBE_DT, "974213621500000", "67 BANKS TOWN RD", "67 BANKS TOWN ROAD TRUST"),
                   (BUNCOMBE_DT, "974204604700000", "BANKS TOWN RD", "BARNES, WILLIAM A JR")],
    "misty_ln": [(BUNCOMBE_DT, "960673381000000", "31 MISTY LN", "ALLISON, L MARLENE"),
                 (BUNCOMBE_DT, "960673095900000", "MISTY LN", "LUELLA M ALLISON ET AL")],
    # item 64's pair: the live 'LOOKOUT RD' and the neighbour it was fused with
    "lookout_rd": [(BUNCOMBE_DT, "072025785900000", "LOOKOUT RD", "BLANTON, LEENETA"),
                   (BUNCOMBE_DT, "072005966600000", "328 LOOKOUT RD", "HINSON-BAROODY REVOCABLE TRUSTE")],
    # numberless vs numberless, four parcels
    "campbell_st": [(BUNCOMBE_DT, "969819933500000", "CAMPBELL ST", "ARSZYLA, JOHN C"),
                    (BUNCOMBE_DT, "969819933400000", "CAMPBELL ST", "ARSZYLA, JOHN C"),
                    (BUNCOMBE_DT, "969819934100000", "CAMPBELL ST", "BLANKET FORT PROPERTIES LLC"),
                    (BUNCOMBE_DT, "969819934000000", "CAMPBELL ST", "BLANKET FORT PROPERTIES LLC")],
    # numberless vs sentinel
    "us_70": [(BUNCOMBE_DT, "969970983500000", "US 70 HWY", "BORIN WASTE MANAGEMENT INC"),
              (BUNCOMBE_DT, "968849046600000", "99999 US 70 HWY", "MICKEY N. GRAY JR. LIVING TRUST")],
    "turkey_creek": [(BUNCOMBE_DT, "878059826700000", "S TURKEY CREEK RD", "BOZA, ELLEN C"),
                     (BUNCOMBE_DT, "879390336400000", "99999 TURKEY CREEK RD", "FULLER, ZEBAKIAH IDAHO"),
                     (BUNCOMBE_DT, "879298583800000", "99999 TURKEY CREEK RD", "FULLER, ZEBAKIAH IDAHO")],
    # same number, different street (fuzzy >= 92)
    "george_georgia": [(SPBG_VACANT, "712249498152", "128 GEORGE ST SPARTANBURG", "B I G BARBRY INVESTING GROUP LLC"),
                       (SPBG_VACANT, "712249981468", "128 GEORGIA ST SPARTANBURG", "ANTHONY L MATHIS REV TRUST")],
    "butler_bunker": [(SPBG_VACANT, "711284114098", "209 BUTLER ST SPARTANBURG", "CHURCH OF JESUS CHRIST OF SPARTANBURG"),
                      (SPBG_VACANT, "711371964410", "209 BUNKER ST SPARTANBURG", "NORTHSIDE DEVELOPMENT CORPORATION")],
    # sentinel lots on look-alike streets
    "high_hugh": [(SPBG_VACANT, "712244588319", "0 HIGH ST SPARTANBURG", "GIBBS ENGLISH L J"),
                  (SPBG_VACANT, "712245402440", "0 HIGH ST SPARTANBURG", "WOFFORD WALTERS H"),
                  (SPBG_VACANT, "711362129228", "0 S HIGH POINT RD SPARTANBURG", "ISLAM SHAFIQUIL &"),
                  (SPBG_VACANT, "711346354840", "0 HUGH ST SPARTANBURG", "BIGGERSTAFF BOBBY S JR"),
                  (SPBG_VACANT, "711347194715", "0 HUGH ST SPARTANBURG", "DARBY GEORGE D JR ETAL")],
    # pass 3, canonical-street signature across two towns
    "williams_st": [(SPBG_VACANT, "711327515174", "123 WILLIAMS ST SPARTANBURG", "THOMPSON SHANNON"),
                    (SPBG_CONDEMNED[:5] + ("29388",), "6085-95-5980.61", "123 WILLIAMS ST WOODRUFF", "BROWNING JOHN C")],
}


@pytest.mark.parametrize("name", sorted(REAL_DIFFERENT))
@pytest.mark.parametrize("reverse", [False, True], ids=["as_scraped", "reversed"])
def test_real_different_properties_stay_apart(name, reverse):
    rows = [row(src, p, a, o) for src, p, a, o in REAL_DIFFERENT[name]]
    out = D.dedupe(rows[::-1] if reverse else rows)
    assert parcels(out) == sorted(r.parcel_id for r in rows)
    for li in out:                                  # each row still shows its own property
        src = next(r for r in rows if r.parcel_id == li.parcel_id)
        assert (li.street_address, li.owner_name) == (src.street_address, src.owner_name)


def test_rutherford_unnumbered_lots_with_short_parcels_stay_apart():
    """'0 E MAIN ST' in Forest City: five different Rutherford parcels. Their 6-digit ids are not
    valid parcels (under 7 chars) and the address has no real number, so nothing proves they are
    one property; the old fuzzy pass merged all five."""
    rows = [row(RUTHERFORD, p, "0 E MAIN ST", o, city="Forest City") for p, o in [
        ("421904", "STEMBRIDGE, HENRY H III"), ("426770", "STEMBRIDGE, HENRY H III"),
        ("421309", "COLLINS, WILLIAM BERRY"), ("422798", "COLLINS, WILLIAM BARRY"),
        ("430028", "SISK, DAVID REID JR")]]
    assert len(D.dedupe(rows)) == 5
    # the same short parcel twice IS one property (pass 1 parcel key, not address evidence)
    assert len(D.dedupe(rows[:1] + [rows[0].model_copy()])) == 1


# ---------------------------------------------------------------- legitimate merges stay
def test_placeholder_and_numbered_with_the_same_valid_parcel_merge_and_show_the_number():
    """The item-63 twins, as two sources in one fresh scrape: same valid parcel, one side a
    sentinel. One row, and it shows the numbered situs (the sentinel is nulled on publish)."""
    for src_a, src_b, pid, ph, num in [
            (SPBG_VACANT, SPBG_TAX, "714252203123", "0 PATCH DR SPARTANBURG", "499 PATCH DR SPARTANBURG"),
            (BUNCOMBE_DT, BUNCOMBE_ELDERLY, "879362599800000", "99999 PINEY KNOB RD", "560 PINEY KNOB RD"),
            (RUTHERFORD, RUTHERFORD_WILDFIRE, "1647690", "0 COBB RD", "212 COBB RD")]:
        for order in (0, 1):
            pair = [row(src_a, pid, ph, "OWNER"), row(src_b, pid, num, "OWNER")]
            out = D.dedupe(pair if order == 0 else pair[::-1])
            assert len(out) == 1, (pid, order)
            assert out[0].street_address == num
            assert _to_dict(out[0])["street_address"] == num


def test_numberless_row_sharing_the_numbered_rows_valid_parcel_merges():
    out = D.dedupe([row(BUNCOMBE_DT, "072025785900000", "LOOKOUT RD", "BLANTON, LEENETA"),
                    row(BUNCOMBE_ELDERLY, "0720257859", "18 LOOKOUT RD", "BLANTON, LEENETA")])
    assert len(out) == 1 and out[0].street_address == "18 LOOKOUT RD"


@pytest.mark.parametrize("a,b", [
    ("7037-51-0954.56", "703751095456"),          # dashes / dot
    ("967806998600000", "9678069986"),            # zero-padded 15-digit vs bare 10-digit
])
def test_parcel_formatting_variants_still_merge(a, b):
    out = D.dedupe([row(SPBG_CONDEMNED if "-" in a else BUNCOMBE_DT, a, "1312 BLACKSTOCK RD PAULINE"),
                    row(SPBG_TAX if "-" in a else BUNCOMBE_ELDERLY, b, "1312 BLACKSTOCK RD PAULINE")])
    assert len(out) == 1


def test_one_county_written_two_ways_still_agrees():
    """The board writes one county two ways (test_digitless_parcel_guard's 'Rutherford' /
    'Rutherfordton' pair for parcel 1201147); the two spellings of the same parcel still agree.
    The numberless copy here is constructed."""
    a = Listing(source="counties_nc.rutherford_tax", source_url="http://x", street_address="135 GRACE ST",
                city="Rutherfordton", county="Rutherford", state="NC", parcel_id="1201147")
    b = Listing(source="counties_generic.liensnc", source_url="http://y", street_address="GRACE ST",
                city="Rutherfordton", county="Rutherfordton", state="NC", parcel_id="1201147")
    out = D.dedupe([b, a])
    assert len(out) == 1 and out[0].street_address == "135 GRACE ST"


def test_the_same_parcel_number_in_two_counties_is_two_properties():
    """Real (fresh scrape 2026-10-06): an Oconee heir-estate parcel and a Berkeley tax bill both
    carry parcel number 097-00-02-002. The state-scoped ('p', parcel, state) signature joined them,
    and the Oconee lead (no situs) took the Berkeley address."""
    oconee = Listing(source="counties_nc.nc_heir_estate_parcels",
                     source_url="https://arcserver2.oconeesc.com/arcgis/rest/services/CitizenServe/MapServer/5",
                     state="SC", county="Oconee", parcel_id="097-00-02-002")
    berkeley = Listing(source="counties_sc.berkeley_paystar_tax",
                       source_url="https://berkeleycountysc.paystar.io/app/invoices/MjAyNS0wMDE4NTc3",
                       state="SC", county="Berkeley", parcel_id="097-00-02-002",
                       street_address="420 FANTAIL AV", owner_name="BAXTER ELIZABETH & DASBIAN")
    out = D.dedupe([oconee, berkeley])
    assert sorted(li.county for li in out) == ["Berkeley", "Oconee"]
    assert next(li for li in out if li.county == "Oconee").street_address is None


def test_same_house_written_differently_across_sources_still_merges():
    zip_src = BUNCOMBE_ELDERLY[:5] + ("28801",)
    for a, b in [("123 Main St", "123 MAIN STREET"), ("11 Carefree Lane", "11 Carefree Ln"),
                 ("318 Fairfax Ave", "318 Fairfax Ave.")]:
        # parcel on one side only: address evidence with a real house number is enough
        out = D.dedupe([row(BUNCOMBE_DT[:5] + ("28801",), "9638108274", a),
                        row(zip_src, None, b)])
        assert len(out) == 1, (a, b)
        # both without a parcel
        assert len(D.dedupe([row(zip_src, None, a), row(zip_src, None, b, source="x.y")])) == 1


def test_address_less_rows_sharing_a_case_number_still_merge():
    court = ("counties_nc.nc_ecourts_lis_pendens", "https://ec/26SP1", ListingType.UNKNOWN, "NC",
             "Buncombe", None)
    a = row(court, None, None, case_number="26SP001")
    b = row(court, None, None, case_number="26-SP-001", source_url="https://ec/other")
    assert len(D.dedupe([a, b])) == 1


# ------------------------------------------------------- a merged group cannot chain houses
def test_a_numberless_row_cannot_carry_two_houses_into_one_row():
    """test_dedupe_house_number_guard's real pair (two houses sharing parcel 9698372180) behind a
    numberless row with the same parcel: the old pass 1 kept the numberless base address, so it
    absorbed BOTH houses. Now the group takes the first house's number and refuses the second."""
    rows = [row(BUNCOMBE_DT, "9698372180", "FOUNTAIN WAY"),
            row(BUNCOMBE_DT, "9698372180", "306 FOUNTAIN WAY", source="liensnc"),
            row(BUNCOMBE_DT, "9698372180", "346 FOUNTAIN WAY", source="buncombe_elderly")]
    out = D.dedupe(rows)
    assert sorted(li.street_address for li in out) == ["306 FOUNTAIN WAY", "346 FOUNTAIN WAY"]


def test_union_find_cannot_chain_two_parcels_through_a_parcelless_row():
    """'115 SOUTHPORT RD' is two parcels in the vacant registry; a third, parcel-less copy of the
    address matches both by signature. At most one of them may absorb it."""
    zip_src = SPBG_VACANT[:5] + ("29301",)
    rows = [row(zip_src, None, "115 SOUTHPORT RD SPARTANBURG", source="x.notice"),
            row(zip_src, "710294491882", "115 SOUTHPORT RD SPARTANBURG"),
            row(zip_src, "710294464234", "115 SOUTHPORT RD SPARTANBURG")]
    for order in ([0, 1, 2], [1, 0, 2], [1, 2, 0]):
        out = D.dedupe([rows[i] for i in order])
        assert sorted(filter(None, (li.parcel_id for li in out))) == ["710294464234", "710294491882"]
        assert len(out) == 2


def test_a_refused_row_is_never_dropped_in_pass_one():
    """The old pass 1 parked a refused row under '<key>#hn<number>', and a second row with that
    number OVERWROTE the first there. Here the second '346' copy now merges into the first."""
    rows = [row(BUNCOMBE_DT, "9698372180", "306 FOUNTAIN WAY"),
            row(BUNCOMBE_DT, "9698372180", "346 FOUNTAIN WAY", "FIRST", source="a.first",
                source_url="https://a/1"),
            row(BUNCOMBE_DT, "9698372180", "346 FOUNTAIN WAY", "SECOND", source="b.second",
                source_url="https://b/2")]
    out = D.dedupe(rows)
    assert len(out) == 2
    li = next(li for li in out if li.street_address == "346 FOUNTAIN WAY")
    assert li.owner_name == "FIRST"
    assert [d["source"] for d in li.raw["also_seen_in"]] == ["b.second"]


# ----------------------------------------------------- resolver-attached parcels are not evidence
def test_a_resolver_parcel_neither_proves_nor_disproves():
    zip_src = BUNCOMBE_ELDERLY[:5] + ("28801",)
    src_row = row(BUNCOMBE_DT[:5] + ("28801",), "9638108274", "90 INDIANA AVE")
    geo_row = row(zip_src, "9638108999", "90 Indiana Avenue",
                  raw={"parcel_from_geo": {"source": "nc_onemap_point"}})
    assert len(D.dedupe([src_row, geo_row])) == 1          # a resolver's neighbour parcel
    road = row(zip_src, "9638108274", "INDIANA AVE",
               raw={"parcel_from_geo": {"source": "nc_onemap_point"}})   # road centroid
    assert len(D.dedupe([src_row, road])) == 2


def test_streamed_finder_reads_the_resolver_flag_like_dedupe(tmp_path):
    """board_dedupe_stream builds light Listings for dedupe(); they must carry the resolver flag
    or the streamed finder and dedupe() disagree about the road-centroid row above."""
    rows = [row(BUNCOMBE_DT[:5] + ("28801",), "9638108274", "90 INDIANA AVE"),
            row(BUNCOMBE_ELDERLY[:5] + ("28801",), "9638108274", "INDIANA AVE",
                raw={"parcel_from_geo": {"source": "nc_onemap_point"}})]
    write_artifact(rows, {"notes": "seed"}, docs_dir=tmp_path)
    real = D.dedupe([li.model_copy(deep=True) for li in rows])
    groups, stats = find_dedupe_merge_groups(tmp_path)
    assert len(real) == 2 and groups == [] and stats["skipped"] == 0


# --------------------------------------------- merge_prior_board: no fold across two parcels
def _board(docs, rows):
    import json
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "listings.json").write_text(json.dumps([li.model_dump(mode="json") for li in rows]))


def test_prior_row_of_another_parcel_is_not_folded_through_an_address_signature(tmp_path):
    """'115 SOUTHPORT RD SPARTANBURG' is two parcels. When only one is re-scraped, the other's
    prior row used to match it through the canonical-street signature and vanish into it; it now
    ages as the prior-only lead it is."""
    from foreclosure_scraper.board_persist import merge_prior_board
    prior = row(SPBG_VACANT, "710294464234", "115 SOUTHPORT RD SPARTANBURG", "PRIOR OWNER",
                first_seen=datetime(2026, 9, 1), last_seen=datetime(2026, 9, 22))
    fresh = row(SPBG_VACANT, "710294491882", "115 SOUTHPORT RD SPARTANBURG", "FRESH OWNER")
    _board(tmp_path, [prior])
    out, st = merge_prior_board([fresh], docs_dir=tmp_path, now=datetime(2026, 10, 6))
    assert st["matched"] == 0 and st["prior_only_kept"] == 1 and st["refused_different_parcel"] == 1
    by = {li.parcel_id: li for li in out}
    assert by["710294491882"].owner_name == "FRESH OWNER"
    assert by["710294464234"].raw["pulled_sale"]["presumed_withdrawn"] is True
    # both re-scraped: each prior row finds its own parcel
    _board(tmp_path, [prior])
    both = [fresh, row(SPBG_VACANT, "710294464234", "115 SOUTHPORT RD SPARTANBURG", "OWNER 2")]
    out, st = merge_prior_board(both, docs_dir=tmp_path, now=datetime(2026, 10, 6))
    assert st["matched"] == 1 and st["prior_only_kept"] == 0 and len(out) == 2
    assert {li.parcel_id: li.first_seen for li in out}["710294464234"] == datetime(2026, 9, 1)
