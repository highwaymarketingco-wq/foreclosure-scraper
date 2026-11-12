"""enrichment_prior_correction, correction 5: an exemption claim that is another parcel's.

raw['gis_exempt'] {code, tag} is the statutory elderly / disabled / blind / veteran exemption of ONE
parcel and does not say which. counties_nc.buncombe_elderly writes it for its own row's parcel; a row of
any other source got it by the old address-key dedupe merge of an elderly row into a row of another
parcel (the elderly entry, with its pin in the layer URL, stays in raw['also_seen_in']) or by
enrichment_gis_attrs copying the code off the polygon a point fell in (ee824ffc stops that; a row carried
from the prior board keeps what it has). Row shapes are the real board rows of 2026-10-05 (4,481 claim
rows: 3,898 the scraper's own, 156 a same-parcel merge, 371 merged into another parcel, 51 by point, 5
outside Buncombe); every name, pin and street here is invented.
"""
from __future__ import annotations

import json
from datetime import date

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper import enrichment_lead_signals as ls
from foreclosure_scraper import enrichment_prior_correction as pc
from foreclosure_scraper.models import Listing, ListingType

ELD = "counties_nc.buncombe_elderly"
TODAY = date(2026, 10, 6)
TAG = {"ELD": "elderly_exemption", "DIS": "disabled_exemption", "BLD": "blind_exemption",
       "VET": "disabled_veteran_exemption"}

# the county's exempt list in these tests (the elderly scraper's rows): pin -> street
EXEMPT = {"9000000100": "18 SAMPLE RIDGE RD", "9000000200": "7 EXAMPLE LN", "9000000300": "410 CEDAR TEST DR",
          "9000000400": "52 LOWER TEST CREEK RD"}


class FakeCache(pc.CacheReader):
    """parcel_cache stand-in: {(county, pid): row}; with no rows no county has a cache file."""

    def __init__(self, rows=None):
        self.rows = rows or {}
        super().__init__(lookup=lambda c, p, s: ((dict(self.rows[(c, str(p))]), "exact") if (c, str(p)) in self.rows
                                                 else (None, None)),
                         available=lambda c, s: bool(self.rows))


def _url(pin: str) -> str:
    return ("https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query"
            f"?where=pin%3D%27{pin}%27&outFields=*&f=html")


def _elderly(pin: str, street: str | None, code: str = "ELD", aged: bool = False, **kw) -> Listing:
    """The scraper's own row: its claim (care_of included), marker and life_events tag."""
    raw = {"gis_exempt": {"code": code, "tag": TAG[code], "care_of": "SAMPLE C/O PERSON"},
           "life_event": "elderly_disabled_homestead", "life_events": [TAG[code]],
           "owner_mailing": {"owner": "SAMPLE OWNER A", "mailing": "1 MAIL ST ASHEVILLE NC 28801", "situs": street,
                             "parcel_id": pin, "source": "buncombe_elderly_gis"}}
    if aged:
        raw["pulled_sale"] = {"presumed_withdrawn": True}
    base = dict(source=ELD, source_url=_url(pin), listing_type=ListingType.ELDERLY_DISABLED, state="NC",
                county="Buncombe", parcel_id=pin, street_address=street, owner_name="SAMPLE OWNER A", raw=raw)
    base.update(kw)
    return Listing(**base)


def _row(pin="9000000999", street="31 UNRELATED WAY", merged=(), code="ELD", source="counties_nc.buncombe_delinquent_tax",
         life=True, marker=False, extra=None, **kw) -> Listing:
    """A row of another source that carries the claim; `merged` are the pins of elderly rows merged into it."""
    raw = {"gis_exempt": {"code": code, "tag": TAG[code]},
           "also_seen_in": [{"source": "liensnc", "url": "https://liensnc.test/scr/appointment/details.html?entryNumber=1"}]}
    raw["also_seen_in"] += [{"source": ELD, "url": _url(p)} for p in merged]
    if life:
        raw["life_events"] = [TAG[code]]
    if marker:
        raw["life_event"] = "elderly_disabled_homestead"
    raw.update(extra or {})
    base = dict(source=source, source_url="https://example.test/bill/1", listing_type=ListingType.TAX_LIEN, state="NC",
                county="Buncombe", parcel_id=pin, street_address=street, owner_name="SAMPLE DEBTOR B", raw=raw)
    base.update(kw)
    return Listing(**base)


def _list(*rows, n_exempt=None):
    """The board the step sees: `rows` beside the exempt list (the scraper's rows of EXEMPT)."""
    return list(rows) + [_elderly(p, s) for p, s in EXEMPT.items()][:n_exempt]


def _run(rows, **kw):
    kw.setdefault("min_exempt_rows", 1)
    return pc.correct_prior_rows(rows, cache=FakeCache(), **kw)


def _dump(li: Listing) -> str:
    return json.dumps(li.model_dump(mode="json"), sort_keys=True, default=str)


# ------------------------------------------------------------------------------ withdrawn rows
def test_a_claim_merged_in_from_another_parcel_is_withdrawn_with_what_derives_from_it():
    li = _row(merged=("9000000100",), marker=True,
              extra={"tax_relief": {"kind": "elderly", "basis": "elderly_disabled_exclusion", "code": "ELD",
                                    "county": "Buncombe"}})
    li.raw["life_events"] = ["estate_probate", "elderly_exemption"]          # an owner-name tag beside the claim's
    before_asi = json.dumps(li.raw["also_seen_in"])
    stats = _run(_list(li))
    assert stats["exempt_claim_withdrawn"] == 1 and stats["exempt_claim_by_reason"] == {"merged_from_another_parcel": 1}
    for gone in ("gis_exempt", "tax_relief", "life_event"):
        assert gone not in li.raw
    assert li.raw["life_events"] == ["estate_probate"]                       # only the claim's own tag goes
    # nothing else: the owner, parcel, address, values and the merge provenance stay
    assert (li.parcel_id, li.street_address, li.owner_name) == ("9000000999", "31 UNRELATED WAY", "SAMPLE DEBTOR B")
    assert json.dumps(li.raw["also_seen_in"]) == before_asi
    a = li.raw[pc.EXEMPT_KEY]
    assert a["reason"] == "merged_from_another_parcel" and a["claim"] == {"code": "ELD", "tag": "elderly_exemption"}
    assert a["merged_pins"] == ["9000000100"] and a["row_pin"] == "9000000999" and a["numbered_address"] is True
    assert a["cleared"] == {"tax_relief": {"kind": "elderly", "basis": "elderly_disabled_exclusion", "code": "ELD",
                                           "county": "Buncombe"},
                            "life_events": ["elderly_exemption"], "life_event": "elderly_disabled_homestead"}
    assert stats["exempt_claim_fields_cleared"] == {"gis_exempt": 1, "tax_relief": 1, "life_events": 1, "life_event": 1}


def test_a_life_events_list_that_held_only_the_claims_tag_is_removed_whole():
    li = _row(merged=("9000000100",))
    _run(_list(li))
    assert "life_events" not in li.raw and pc.EXEMPT_KEY in li.raw


def test_a_point_attached_claim_on_a_parcel_not_on_the_exempt_list_is_withdrawn():
    # enrichment_gis_attrs copied the code off a polygon at the row's point: no merge trace, a parcel that
    # the county does not list as exempt
    li = _row(pin="9000000777", street="9 OTHER TEST RD", code="VET", merged=())
    stats = _run(_list(li))
    assert "gis_exempt" not in li.raw and "life_events" not in li.raw
    a = li.raw[pc.EXEMPT_KEY]
    assert a["reason"] == "parcel_not_on_exempt_list" and a["claim"]["code"] == "VET" and a["merged_pins"] == []
    assert stats["exempt_claim_by_reason"] == {"parcel_not_on_exempt_list": 1}


def test_a_merge_with_the_exempt_parcel_of_another_county_is_withdrawn_but_an_unmerged_foreign_claim_is_left():
    crossed = _row(pin="R02510002023000", state="NC", county="New Hanover", merged=("9000000100",),
                   source="counties_nc.nc_county_csv_delinquent_tax")
    foreign = _row(pin="1654116", state="NC", county="Rutherford", merged=(), source="counties_nc.rutherford_tax")
    sc = _row(pin="4100000001", state="SC", county="Anderson", merged=("9000000200",), source="counties_sc.sc_example")
    f_before = _dump(foreign)
    stats = _run(_list(crossed, foreign, sc))
    assert crossed.raw[pc.EXEMPT_KEY]["reason"] == "merged_from_other_county" and "gis_exempt" not in crossed.raw
    assert sc.raw[pc.EXEMPT_KEY]["reason"] == "merged_from_other_county"
    assert _dump(foreign) == f_before and stats["exempt_claim_skipped"] == {"other_county_not_merged": 1}


def test_a_row_with_no_tax_parcel_of_its_own_loses_a_merged_in_claim():
    # nc_dam_safety: the parcel id is the dam's NID id and there is no street; an elderly row was merged in
    li = _row(pin="NC00123", street=None, merged=("9000000300", "9000000400"),
              source="counties_generic.state_contamination.nc_dam_safety")
    _run(_list(li))
    assert li.raw[pc.EXEMPT_KEY]["reason"] == "merged_from_another_parcel" and "gis_exempt" not in li.raw
    assert li.raw[pc.EXEMPT_KEY]["numbered_address"] is False and li.raw[pc.EXEMPT_KEY]["row_pin"] is None


def test_a_row_whose_point_parcel_correction_1_took_back_loses_a_point_attached_claim():
    # the parcel and the claim came from the same fallback point; once the parcel is withdrawn nothing is left
    # to compare, which must not keep the claim
    li = _row(pin=None, street=None, merged=(), extra={pc.FALLBACK_KEY: {"parcel_id": "9000000888", "reason": "county_seat_point"}})
    lin = _row(pin=None, street=None, merged=(), state="NC", county="Lincoln", source="counties_nc.lincoln_vacant",
               extra={pc.FALLBACK_KEY: {"parcel_id": "3600000001", "reason": "county_seat_point"}})
    stats = _run(_list(li, lin))
    assert li.raw[pc.EXEMPT_KEY]["reason"] == "parcel_withdrawn_fallback_point"
    assert lin.raw[pc.EXEMPT_KEY]["reason"] == "parcel_withdrawn_fallback_point"
    assert stats["exempt_claim_withdrawn"] == 2


# ------------------------------------------------------------------------------ untouched rows
def test_the_elderly_scrapers_own_rows_are_untouched_whatever_the_list_holds():
    own = _elderly("9000000500", "3 NOT LISTED LN")                       # its parcel is on no other row's list
    unit = _elderly("9627023924C0102", "88 TEST COURT UNIT 3", code="DIS")
    aged = _elderly("9000000600", None, aged=True)
    rows = _list(own, unit, aged)
    before = [_dump(r) for r in rows]
    stats = _run(rows)
    assert [_dump(r) for r in rows] == before
    assert stats["exempt_claim_withdrawn"] == 0 and stats["exempt_claim_kept"] == {} and stats["exempt_list_rows"] == 7


def test_a_same_parcel_merge_is_untouched():
    plain = _row(pin="9000000100", street="999 MISMATCHED ST", merged=("9000000100",))
    padded = _row(pin="9000-00-0200-00000", street=None, merged=("9000000200",))
    unit = _row(pin="9000000300C0116", street="410 CEDAR TEST DR UNIT 116", merged=("9000000300",))   # the building's entry
    rows = _list(plain, padded, unit)
    before = [_dump(r) for r in (plain, padded, unit)]
    stats = _run(rows)
    assert [_dump(r) for r in (plain, padded, unit)] == before
    assert stats["exempt_claim_withdrawn"] == 0 and sum(stats["exempt_claim_kept"].values()) == 3
    assert all("same_parcel_merge" in k for k in stats["exempt_claim_kept"])


def test_a_row_whose_own_parcel_is_exempt_keeps_a_point_attached_claim_and_its_tax_relief():
    # enrichment_tax_relief writes the bridge's own shape for a row's OWN parcel: indistinguishable, so it stays
    li = _row(pin="9000000400", street="no street here", merged=(),
              extra={"tax_relief": {"kind": "elderly", "basis": "elderly_disabled_exclusion", "code": "ELD",
                                    "county": "Buncombe"}})
    before = _dump(li)
    stats = _run(_list(li))
    assert _dump(li) == before and stats["exempt_claim_kept"] == {"parcel_on_exempt_list": 1}


def test_a_merged_claim_whose_row_parcel_is_exempt_today_is_kept():
    # an elderly row of ANOTHER parcel was merged in, but the row's own parcel is on the list too
    li = _row(pin="9000000200", street="1 NOWHERE RD", merged=("9000000100",))
    before = _dump(li)
    stats = _run(_list(li))
    assert _dump(li) == before and stats["exempt_claim_kept"] == {"parcel_on_exempt_list": 1}


def test_a_row_at_an_exempt_parcels_address_or_lien_parcel_is_left_to_the_verifier():
    at_addr = _row(pin="9000000888", street="52 Lower Test Creek Road", merged=("9000000400",))     # same property, another id
    lien = _row(pin="9000000889", street="4 ELSEWHERE AVE", merged=(), extra={"arcgis_distress": {"pin": "9000000300"}})
    tax_roll = _row(pin="9000000890", street=None, merged=(),
                    extra={"owner_mailing": {"source": "county_tax_roll", "parcel_id": "9000000100"}})
    rows = _list(at_addr, lien, tax_roll)
    before = [_dump(r) for r in (at_addr, lien, tax_roll)]
    stats = _run(rows)
    assert [_dump(r) for r in (at_addr, lien, tax_roll)] == before
    assert stats["exempt_claim_kept"] == {"address_on_exempt_list": 1, "lien_parcel_on_exempt_list": 2}
    # a different house number on the same street is another property
    other = _row(pin="9000000891", street="54 LOWER TEST CREEK RD", merged=("9000000400",))
    _run(_list(other))
    assert other.raw[pc.EXEMPT_KEY]["reason"] == "merged_from_another_parcel"


def test_rows_without_a_claim_and_other_exemption_records_are_untouched():
    no_claim = _row(life=False)
    del no_claim.raw["gis_exempt"]
    deferral = _row(pin="9000000777", merged=("9000000100",),
                    extra={"tax_relief": {"kind": "use_value_deferral", "basis": "present_use_rollback_lien"}})
    stats = _run(_list(no_claim, deferral))
    assert pc.EXEMPT_KEY not in no_claim.raw and "life_events" not in no_claim.raw
    # the withdrawn row keeps a deferral (not an exemption bridge)
    assert deferral.raw["tax_relief"]["kind"] == "use_value_deferral" and "gis_exempt" not in deferral.raw
    assert stats["exempt_claim_withdrawn"] == 1 and "tax_relief" not in deferral.raw[pc.EXEMPT_KEY]["cleared"]


def test_a_point_attached_claim_with_nothing_to_compare_is_left():
    li = _row(pin=None, street=None, merged=())
    before = _dump(li)
    stats = _run(_list(li))
    assert _dump(li) == before and stats["exempt_claim_skipped"] == {"no_identity": 1}


def test_a_merged_entry_without_a_pin_in_its_url_is_left():
    li = _row(merged=())
    li.raw["also_seen_in"].append({"source": ELD, "url": "https://gis.example.test/layer/1"})
    before = _dump(li)
    stats = _run(_list(li))
    assert _dump(li) == before and stats["exempt_claim_skipped"] == {"merged_entry_without_pin": 1}


# ---------------------------------------------------------------- the exempt list and the order
def test_a_small_exempt_list_skips_the_step():
    # the elderly source did not run: every other row's claim would look foreign
    li = _row(merged=("9000000100",))
    before = _dump(li)
    stats = pc.correct_prior_rows(_list(li), cache=FakeCache())                       # the real floor
    assert _dump(li) == before and stats["exempt_claim_withdrawn"] == 0
    assert stats["exempt_claim_skipped"] == {"exempt_list_too_small": 5}
    assert stats["exempt_list_rows"] == 4


def test_aged_elderly_rows_stay_on_the_list():
    # a scrape that came back short ages the prior rows; they must still count as the county's list
    li = _row(pin="9000000600", street="1 NOWHERE RD", merged=())
    rows = [li] + [_elderly(p, s, aged=True) for p, s in EXEMPT.items()] + [_elderly("9000000600", None, aged=True)]
    stats = _run(rows)
    assert pc.EXEMPT_KEY not in li.raw and stats["exempt_claim_kept"] == {"parcel_on_exempt_list": 1}


def test_the_street_it_reads_is_the_one_correction_2_left():
    # a lien bill whose street was the owner's MAILING address, which is an exempt parcel's situs: that merge
    # was the address key's; once correction 2 restores the bill's own situs there is no address evidence
    li = _row(pin="9686540826", street="18 SAMPLE RIDGE RD", merged=("9000000100",),
              source="counties_generic.arcgis_distress.buncombe_unpaid_bills", listing_type=ListingType.TAX_LIEN)
    cache = FakeCache({("Buncombe", "9686540826"): {"owner": "SAMPLE DEBTOR B", "address": "40 SAMPLE RIDGE RD",
                                                    "owner_mailing": "18 SAMPLE RIDGE RD FAIRVIEW NC 28730"}})
    stats = pc.correct_prior_rows(_list(li), cache=cache, min_exempt_rows=1)
    assert li.street_address == "40 SAMPLE RIDGE RD" and pc.MAILING_KEY in li.raw
    assert li.raw[pc.EXEMPT_KEY]["reason"] == "merged_from_another_parcel" and "gis_exempt" not in li.raw
    assert stats["mailing_corrected"] == 1 and stats["exempt_claim_withdrawn"] == 1


# ------------------------------------------------------------------ idempotence, audit, scorer
def test_a_second_pass_changes_nothing_more():
    rows = _list(_row(merged=("9000000100",), marker=True), _row(pin="9000000777", code="DIS"),
                 _row(pin="9000000200", merged=("9000000100",)), _row(pin="NC00123", street=None, merged=("9000000300",)),
                 _row(pin="9000000555", life=False))
    first = _run(rows)
    snap = [_dump(r) for r in rows]
    second = _run(rows)
    assert [_dump(r) for r in rows] == snap
    # withdrawn: the merged-in one, the point-attached one, the dam and the claim without a tag; kept: the
    # merged-in one whose own parcel is on the list
    assert first["exempt_claim_withdrawn"] == 4 and second["exempt_claim_withdrawn"] == 0
    assert second["fallback_withdrawn"] == 0 and second["mailing_corrected"] == 0


def test_a_claim_attached_again_and_withdrawn_again_keeps_the_earlier_audit():
    li = _row(merged=("9000000100",))
    _run(_list(li))
    first = dict(li.raw[pc.EXEMPT_KEY])
    li.raw["gis_exempt"] = {"code": "BLD", "tag": TAG["BLD"]}
    _run(_list(li))
    a = li.raw[pc.EXEMPT_KEY]
    assert a["claim"]["code"] == "BLD" and a["earlier"] == first and "earlier" not in a["earlier"]


def test_the_audit_key_is_protected_and_survives_the_publish_slim():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert RAW_KEEP.get(pc.EXEMPT_KEY) == "*" and pc.EXEMPT_KEY in pc._PROTECTED_RAW
    assert pc.EXEMPT_KEY == "exempt_claim_withdrawn"


def test_correction_1_never_removes_the_audit_record():
    # a row whose parcel is a fallback parcel keeps an exempt audit written by an earlier run
    li = _row(pin="9000000999", merged=("9000000100",))
    _run(_list(li))
    audit = json.dumps(li.raw[pc.EXEMPT_KEY], sort_keys=True)
    li.raw["parcel_from_geo"] = {"source": "nc_onemap_point", "lat": 35.5951, "lng": -82.5515}
    pc.withdraw_fallback_parcel(li, pc.Counter({(35.5951, -82.5515): 99}), 8, FakeCache(), force_reason="shared_point")
    assert json.dumps(li.raw[pc.EXEMPT_KEY], sort_keys=True) == audit


def test_the_next_scoring_pass_drops_senior_exemption_from_a_withdrawn_row_and_keeps_the_scrapers_own():
    withdrawn = _row(merged=("9000000100",), marker=True,
                     extra={"tax_relief": {"kind": "elderly", "basis": "elderly_disabled_exclusion", "code": "ELD",
                                           "county": "Buncombe"}})
    own = _elderly("9000000500", "3 NOT LISTED LN")

    def names(li):
        return ({n for n, _c, _w in ds._signals_for(li, None, TODAY)}, ls._facet_signals(li, TODAY))
    w_ds, w_facets = names(withdrawn)
    o_ds, o_facets = names(own)
    assert "senior_exemption" in w_ds and "senior_exemption" in w_facets            # the bridge and the tag, before
    assert "elderly_disabled" in o_ds and "senior_exemption" in o_facets
    _run(_list(withdrawn, own))
    w_ds, w_facets = names(withdrawn)
    assert "senior_exemption" not in w_ds and "senior_exemption" not in w_facets    # gone from both scorer paths
    assert "elderly_disabled" in names(own)[0] and "senior_exemption" in names(own)[1]
    # the lead-signals chip a pass later
    ls.enrich_lead_signals([withdrawn])
    assert "senior_exemption" not in withdrawn.raw["signal_stack"]["signals"]


def test_stats_and_samples_name_no_one():
    rows = _list(_row(merged=("9000000100",)), _row(pin="9000000777"))
    stats = _run(rows)
    assert stats["exempt_claim_withdrawn"] == 2 and stats["exempt_claim_by_source"] == {
        "counties_nc.buncombe_delinquent_tax": 2}
    assert stats["samples"]["exempt"][0] == ("buncombe_delinquent_tax", "Buncombe", "merged_from_another_parcel", ["life_events"])
    assert "SAMPLE" not in json.dumps(stats, default=str)


def test_a_row_that_raises_never_stops_the_step_and_is_left_whole(monkeypatch):
    real = pc.withdraw_foreign_exempt_claim

    def boom(li, reg):
        if li.parcel_id == "9000000666":
            raise ValueError("malformed row")
        return real(li, reg)
    monkeypatch.setattr(pc, "withdraw_foreign_exempt_claim", boom)
    bad, good = _row(pin="9000000666", merged=("9000000100",)), _row(pin="9000000777")
    before = _dump(bad)
    stats = _run(_list(bad, good))
    assert _dump(bad) == before and stats["exempt_claim_row_errors"] == 1
    assert good.raw[pc.EXEMPT_KEY]["reason"] == "parcel_not_on_exempt_list" and stats["exempt_claim_withdrawn"] == 1
