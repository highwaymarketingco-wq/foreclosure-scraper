"""Withdrawn tags that stick to rows the run saw, and the 10/5 publish repair (2026-10-06).

Measured on the whole 10/5 pre_publish checkpoint (270,481 rows, streamed on the VM) against the
board that run merged (223,832 rows, newest last_seen 2026-10-02T21:47:35.693631):

  * 6,414 rows with last_seen at or after the run start still carried raw['pulled_sale'].
    merge_prior_board() itself clears the tag on a row it matches; what did it here is that it
    did NOT match. validation nulls a parcel id under 7 characters before publish, so Catawba's
    tax-account rows (parcel '65771' in the scrape) publish with parcel None and key
    'url:<county PDF>'. Their re-scrape keys 'parcel:NC:catawba:65771'; no signature matched,
    the published copy was aged, and dedupe2 met the two again through the synthesized
    'Parcel - <owner> ...' address and fused the live row INTO the aged copy (3,737 Catawba rows;
    all 3,519 that carry their account number were still on the county's list on 10/6).
    Under dedupe()'s identity rule (240b8de9) dedupe2 no longer fuses those two, so the same miss
    would keep the live row AND an aged copy. merge_prior_board now rebuilds the published row's
    key from the id validation nulled (raw['parcel_id_nulled'], or the source's own raw block for
    rows published before that key existed).
  * 266 tagged rows came from the Mac's stealth hand-off: they keep the Mac's scrape time
    (10/4 19:55 - 21:13), before the run start, so a run-start cutoff misses them.
  * 143 fannie_homepath rows were seen by enrichment_reo_freshness on 10/6 (HomePath still
    listed them): it set last_seen and kept the tag.
  * 7,741 rows the run re-scraped carried no tag but kept raw['stale_case'] (merge_prior_board
    cleared pulled_sale and the status, not stale_case). The dashboard reads stale_case as
    "presumed withdrawn" and lead_signals caps intent at 69 on it.
  * Placeholder twins: of the 325 planned groups only 69 old copies carried a county situs
    (raw['situs_address_source'] = 'parcel_cache:exact'); 208 carried the owner's MAILING address
    as the street, the rest another street, a reverse geocode, a map reference or a legal
    description. Folding those in published the wrong address.

Every row below is real (values copied from the checkpoint, the prior board, the parcel cache and
the 10/4 hand-off file).
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime

import pytest

import foreclosure_scraper.main as main_mod
from foreclosure_scraper import dedupe as D
from foreclosure_scraper import enrichment_reo_freshness as reo
from foreclosure_scraper import placeholder_twins as PT
from foreclosure_scraper.board_persist import merge_prior_board
from foreclosure_scraper.enrichment_address_final import enrich_with_address_synthesis
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_nc import nc_county_pdf_delinquent_tax as PDF
from foreclosure_scraper.validation import validate

MERGE_NOW = datetime(2026, 10, 5, 2, 18, 47)       # merge_prior_board's clock in the 10/5 run
PRIOR_T = datetime(2026, 9, 22, 15, 36, 39)        # the Catawba rows' published last_seen
RUN_START = "2026-10-05T01:27:29Z"                  # orchestrator.start of the 10/5 VM run
HANDOFF_FIRST = "2026-10-04T19:34:31Z"              # oldest last_seen in hand-off 3e418a6d
TODAY = date(2026, 10, 6)

# (owner, account #, amount owed) as the Catawba 2026 delinquent PDF lists them.
CATAWBA = [("IKERD ZANE GREY", "65771", 1036.0), ("013 10TH STREET TRUST", "33566", 23.0)]

BUNCOMBE_TAX = dict(source="counties_nc.buncombe_delinquent_tax",
                    source_url="https://media.buncombenc.gov/common/tax/buncombe-county-tax-"
                               "department-advertisement-of-tax-liens.pdf",
                    listing_type=ListingType.TAX_LIEN, state="NC", county="Buncombe")
SPBG = dict(source_url="https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/"
                       "City_Owned_and_Vacant_Properties/FeatureServer/0",
            listing_type=ListingType.UNKNOWN, state="SC", county="Spartanburg")
VACANT = "counties_sc.spartanburg_vacant"
INFILL = "counties_generic.arcgis_distress.spartanburg_infill_eligible"


def _tag(consec=1, first_missed="2026-10-05T02:18:47.694504Z", src=None) -> dict:
    return {"first_missed_at": first_missed, "consecutive_misses": consec,
            "presumed_withdrawn": True, "last_seen_source": src, "last_seen_sale_date": None}


def _catawba_scrape() -> list[Listing]:
    return [PDF._to_listing(o, i, a, "Catawba", PDF.COUNTIES["Catawba"]) for o, i, a in CATAWBA]


def _published(li: Listing, *, legacy: bool = False) -> Listing:
    """The row as a full run publishes it: validation nulls the 5-digit account. legacy=True is
    a row published before 2026-10-06 (no raw['parcel_id_nulled'])."""
    p = li.model_copy(deep=True)
    p.first_seen = p.last_seen = PRIOR_T
    validate([p])
    if legacy:
        p.raw.pop("parcel_id_nulled", None)
    return p


def _board(tmp_path, rows):
    (tmp_path / "listings.json").write_text(json.dumps([r.model_dump(mode="json") for r in rows]))
    return tmp_path


def _tail(merged: list[Listing]) -> list[Listing]:
    """main.run()'s steps between the merge and the publish that decide this (in its order):
    address synthesis (main.py:1826), dedupe2 (:1879), validation (:2742)."""
    enrich_with_address_synthesis(merged)
    out = D.dedupe(merged)
    validate(out)
    return out


def _tagged(li: Listing) -> bool:
    return bool((li.raw or {}).get("pulled_sale")) or li.auction_status == "presumed_withdrawn"


# ----------------------------------------------------- the identity mismatch (3,737 Catawba rows)
def test_catawba_rescrape_and_its_published_copy_key_differently():
    fresh = _catawba_scrape()[0]
    pub = _published(_catawba_scrape()[0])
    assert fresh.parcel_id == "65771" and pub.parcel_id is None
    assert fresh.dedupe_key() == "parcel:NC:catawba:65771"
    assert pub.dedupe_key() == f"url:{PDF.COUNTIES['Catawba']['url']}"
    assert pub.raw["parcel_id_nulled"] == {"value": "65771", "reason": "too_short"}


def test_without_a_restored_key_the_live_row_and_an_aged_copy_both_survive(tmp_path):
    """What the 10/5 run did up to dedupe2, replayed on today's dedupe(): the published copies
    are aged, and dedupe2 no longer fuses them (identity rule), so each property is on the board
    twice, once 'presumed withdrawn'. (The rows lose their restorable ids here on purpose.)"""
    prior = [_published(li, legacy=True) for li in _catawba_scrape()]
    for p in prior:
        p.raw.pop("nc_county_pdf_delinquent_tax")
    merged, st = merge_prior_board(_catawba_scrape(), docs_dir=_board(tmp_path, prior),
                                   now=MERGE_NOW)
    assert (st["matched"], st["prior_only_kept"], st["matched_restored_parcel"]) == (0, 2, 0)
    out = _tail(merged)
    assert len(out) == 4 and sum(_tagged(li) for li in out) == 2


def test_rescrape_matches_a_legacy_published_copy_through_the_sources_raw_block(tmp_path):
    """Rows published before raw['parcel_id_nulled'] (the whole 10/5 board): the PDF scraper's
    own raw block holds the id it wrote as parcel_id (county_id)."""
    prior = [_published(li, legacy=True) for li in _catawba_scrape()]
    merged, st = merge_prior_board(_catawba_scrape(), docs_dir=_board(tmp_path, prior),
                                   now=MERGE_NOW)
    assert (st["matched"], st["prior_only_kept"], st["matched_restored_parcel"]) == (2, 0, 2)
    out = _tail(merged)
    assert len(out) == 2 and not any(_tagged(li) for li in out)
    assert {li.raw["parcel_id_nulled"]["value"] for li in out} == {"65771", "33566"}
    assert all(li.first_seen == PRIOR_T for li in out)          # the published copy was carried


def test_rescrape_matches_through_raw_parcel_id_nulled(tmp_path):
    prior = [_published(li) for li in _catawba_scrape()]
    for p in prior:
        p.raw.pop("nc_county_pdf_delinquent_tax")            # only the new key is left
    _, st = merge_prior_board(_catawba_scrape(), docs_dir=_board(tmp_path, prior), now=MERGE_NOW)
    assert (st["matched"], st["matched_restored_parcel"], st["prior_only_kept"]) == (2, 2, 0)


def test_a_restored_key_matches_only_the_same_source(tmp_path):
    other = _published(_catawba_scrape()[0])
    other.source = "counties_nc.nc_ptscloud_delinquent_tax"   # same short id, another roll
    other.raw.pop("nc_county_pdf_delinquent_tax")
    _, st = merge_prior_board(_catawba_scrape()[:1], docs_dir=_board(tmp_path, [other]),
                              now=MERGE_NOW)
    assert (st["matched"], st["matched_restored_parcel"], st["prior_only_kept"]) == (0, 0, 1)


def test_a_weak_or_ambiguous_restored_id_never_matches(tmp_path):
    """An id like '123' keys many rows of a county, and two fresh rows under one restored key
    cannot say which is the prior row's: both stay unmatched (aged, as before)."""
    cfg = PDF.COUNTIES["Catawba"]
    weak_dir = tmp_path / "weak"
    weak_dir.mkdir()
    weak = _published(PDF._to_listing("A OWNER", "123", 10.0, "Catawba", cfg))
    _, st = merge_prior_board([PDF._to_listing("A OWNER", "123", 10.0, "Catawba", cfg)],
                              docs_dir=_board(weak_dir, [weak]), now=MERGE_NOW)
    assert (st["matched"], st["matched_restored_parcel"]) == (0, 0)
    twice = _catawba_scrape()[:1] + _catawba_scrape()[:1]
    twice[1].owner_name = "SOMEONE ELSE"
    prior = [_published(_catawba_scrape()[0], legacy=True)]
    _, st = merge_prior_board(twice, docs_dir=_board(tmp_path, prior), now=MERGE_NOW)
    assert (st["matched_restored_parcel"], st["prior_only_kept"]) == (0, 1)


# ----------------------------------------------- what a matched row must not inherit (merge time)
def _noland(**kw) -> Listing:
    """counties_nc.buncombe_delinquent_tax 879224994500000, one of the 7,741 rows the 10/5 run
    re-scraped that still carried stale_case."""
    return Listing(**BUNCOMBE_TAX, street_address="64 NOLAND HILLS DR",
                   parcel_id="879224994500000", case_number="fc-65567667", **kw)


@pytest.mark.parametrize("prior_raw,prior_status", [
    ({"stale_case": True}, None),                                     # stale_case alone (7,741)
    ({"pulled_sale": _tag(2), "stale_case": True}, "presumed_withdrawn"),
    ({"stale_case": True}, "presumed_withdrawn"),                     # status without a counter
])
def test_a_matched_row_drops_every_inherited_withdrawn_mark(tmp_path, prior_raw, prior_status):
    prior = _noland(first_seen=datetime(2026, 6, 24, 19, 12, 3), last_seen=PRIOR_T,
                    auction_status=prior_status, raw={**prior_raw, "vision": {"condition": "fair"}})
    fresh = _noland(first_seen=MERGE_NOW, last_seen=MERGE_NOW)
    (li,), st = merge_prior_board([fresh], docs_dir=_board(tmp_path, [prior]), now=MERGE_NOW)
    assert st["matched"] == 1 and st["reappeared_untagged"] == 1
    assert "stale_case" not in li.raw and "pulled_sale" not in li.raw
    assert li.auction_status is None
    assert li.raw["vision"] == {"condition": "fair"}               # enrichment still carried


def test_a_rescraped_row_does_not_inherit_an_old_carryover_marker(tmp_path):
    old = {"from_run": "2026-09-22T14:44:00+00:00", "stale": True, "reason": "source produced 0"}
    prior = _noland(first_seen=datetime(2026, 6, 24), last_seen=PRIOR_T, raw={"carryover": old})
    (li,), _ = merge_prior_board([_noland(first_seen=MERGE_NOW, last_seen=MERGE_NOW)],
                                 docs_dir=_board(tmp_path, [prior]), now=MERGE_NOW)
    assert "carryover" not in li.raw


def test_this_runs_carryover_replay_keeps_its_marker(tmp_path):
    mine = {"from_run": "2026-10-05T01:18:39+00:00", "stale": True, "reason": "source produced 0"}
    prior = _noland(first_seen=datetime(2026, 6, 24), last_seen=PRIOR_T)
    replay = _noland(first_seen=datetime(2026, 6, 24), last_seen=PRIOR_T, raw={"carryover": mine})
    (li,), _ = merge_prior_board([replay], docs_dir=_board(tmp_path, [prior]), now=MERGE_NOW)
    assert li.raw["carryover"] == mine


# ------------------------------------------------------- reo_freshness (143 fannie_homepath rows)
def _homepath(addr, uuid, status, raw) -> Listing:
    return Listing(source="national.fannie_homepath", listing_type=ListingType.REO, state="SC",
                   county="Anderson", city="Anderson", street_address=addr,
                   source_url=f"https://homepath.fanniemae.com/property/{uuid}",
                   case_number=f"fannie-{uuid}", auction_status=status, raw=raw)


def test_reo_freshness_untags_a_property_homepath_still_lists(monkeypatch):
    class _Pull:
        slug = "national.fannie_homepath"

        async def safe_run(self):
            return [_homepath("115 Combine Lane", "fb73c5b6-8a1d-4e2c-86b4-dcca951ec68c", None, {}),
                    _homepath("622 Jackson Road", "f486fd7e-eca6-45c3-a8ba-1df6d3a8300d", None, {})]

    tag = _tag(2, "2026-09-22T15:59:20.950113Z", "national.fannie_homepath")
    board = [_homepath("115 Combine Lane", "fb73c5b6-8a1d-4e2c-86b4-dcca951ec68c", "pending",
                       {"pulled_sale": dict(tag), "stale_case": True}),
             _homepath("622 Jackson Road", "f486fd7e-eca6-45c3-a8ba-1df6d3a8300d",
                       "presumed_withdrawn", {"pulled_sale": dict(tag), "stale_case": True})]
    monkeypatch.setattr(main_mod, "_in_scope", lambda li: True)
    monkeypatch.setattr(reo, "all_scrapers", lambda: [_Pull()])
    kept, stats = asyncio.run(reo.prune_stale_reo(board))
    assert len(kept) == 2 and stats["untagged"] == 2 and stats["landed"]["matched"] == 2
    for li in kept:
        assert "pulled_sale" not in li.raw and "stale_case" not in li.raw
        assert "intent_score" in li.raw                            # re-scored without the tag
    assert [li.auction_status for li in kept] == ["pending", None]  # its own status is kept


# ------------------------------------------------------------- the 10/5 publish repair (planner)
def _seen(source, addr, last, *, county, state="NC", case=None, parcel=None, tagged=True,
          stale=True, first="2026-08-27T12:55:53.992936", **raw) -> Listing:
    r = dict(raw)
    if tagged:
        r["pulled_sale"] = _tag(1, src=source)
    if stale:
        r["stale_case"] = True
    return Listing(source=source, source_url="https://example.invalid/" + source, state=state,
                   county=county, street_address=addr, case_number=case, parcel_id=parcel,
                   first_seen=datetime.fromisoformat(first),
                   last_seen=datetime.fromisoformat(last),
                   auction_status="presumed_withdrawn" if tagged else None, raw=r)


def _board_at_publish() -> list[Listing]:
    return [
        # hand-off rows: last_seen is the Mac's scrape time on 10/4 (exact stamps from 3e418a6d)
        _seen("counties_nc.nc_ecourts_lis_pendens",
              "Lis Pendens 26M000487-090 — Pegram Built Homes, LLC; Pegram, Ronald Lee, Jr.",
              "2026-10-04T19:55:27.536713", county="Brunswick", case="26M000487-090"),
        _seen("public_notices.nc_notices_counties", "2026 as Administrator of the Est",
              "2026-10-04T21:13:24.838028", county="Polk", first="2026-09-22T15:30:36.272887"),
        # a row the VM run scraped (Catawba, last_seen 10/5 01:32)
        _seen("counties_nc.nc_county_pdf_delinquent_tax",
              "Parcel — IKERD ZANE GREY — Catawba NC delinquent tax $1,036 owed (65771)",
              "2026-10-05T01:32:52.284750", county="Catawba", first="2026-09-22T15:36:39.280641"),
        # aged rows the run did NOT see: the prior board's newest stamps (10/2)
        _seen("counties.column_legal_notices", "Martha Ann Bergbauer",
              "2026-10-02T21:31:37.918686", county="Scotland", first="2026-06-06T00:00:00"),
        # a re-scraped row with no tag but an inherited stale_case (one of the 7,741)
        _seen("counties_nc.buncombe_delinquent_tax", "64 NOLAND HILLS DR",
              "2026-10-05T01:36:03.960196", county="Buncombe", case="fc-65567667",
              parcel="879224994500000", tagged=False, first="2026-06-24T19:12:03.799644"),
        # an old untagged row with stale_case (a carryover replay): not seen, left alone
        _seen("counties_sc.dillon_delinquent_tax", "1 MAIN ST", "2026-09-22T15:36:18.641916",
              county="Dillon", state="SC", tagged=False, first="2026-08-31T00:00:00"),
    ]


def test_the_run_start_cutoff_misses_the_hand_off_rows():
    plan = PT.plan_collapse(lambda: _board_at_publish(), seen_since=RUN_START)
    assert sorted(v.idx for v in plan.reseen) == [2, 4]
    # the evidence that flagged it on 10/6: a tagged row stamped 10/4, after the prior board
    assert plan.evidence["newest_tagged_last_seen_before_cutoff"] == "2026-10-04T21:13:24.838028"


def test_the_hand_off_cutoff_covers_every_row_the_run_saw_and_no_aged_row():
    plan = PT.plan_collapse(lambda: _board_at_publish(), seen_since=HANDOFF_FIRST)
    assert sorted(v.idx for v in plan.reseen) == [0, 1, 2, 4]
    ev = plan.evidence
    assert ev["newest_tagged_last_seen_before_cutoff"] == "2026-10-02T21:31:37.918686"
    assert ev["oldest_tagged_last_seen_at_or_after_cutoff"] == "2026-10-04T19:55:27.536713"
    assert ev["tagged_rows_before_cutoff_newest_days"] == {"2026-10-02": 1}
    assert ev["stale_case_only_rows_at_or_after_cutoff"] == 1
    s = plan.summary()["reseen"]
    assert (s["tagged_rows"], s["stale_case_only_rows"]) == (3, 1)
    assert s["stale_case_only_by_source"] == {"counties_nc.buncombe_delinquent_tax": 1}


def test_apply_repairs_the_tagged_and_the_stale_case_only_rows():
    rows = _board_at_publish()
    rows[4].raw["intent_score"], rows[4].raw["intent_band"] = 24, "cool"
    plan = PT.plan_collapse(lambda: rows, seen_since=HANDOFF_FIRST)
    res = PT.apply_collapse(rows, plan, today=TODAY)
    assert res["reseen_repaired"] == 4 and res["reseen"]["stale_case_only"] == 1
    for i in (0, 1, 2, 4):
        assert not _tagged(rows[i]) and "stale_case" not in rows[i].raw
    assert _tagged(rows[3]) and rows[3].raw["stale_case"]           # aged: untouched
    assert rows[5].raw["stale_case"]                                # old, not seen: untouched
    assert "intent_score" in rows[4].raw


def test_apply_refuses_when_a_stale_case_only_row_changed():
    rows = _board_at_publish()
    plan = PT.plan_collapse(lambda: rows, seen_since=HANDOFF_FIRST)
    rows[4].raw.pop("stale_case")
    with pytest.raises(PT.CollapsePlanMismatch):
        PT.apply_collapse(rows, plan, today=TODAY)
    assert rows[0].raw["pulled_sale"]                                # nothing changed


def test_digest_covers_the_cutoff_and_the_stale_case_only_rows():
    a = PT.plan_collapse(lambda: _board_at_publish(), seen_since=RUN_START).digest()
    b = PT.plan_collapse(lambda: _board_at_publish(), seen_since=HANDOFF_FIRST).digest()
    rows = _board_at_publish()
    rows[4].raw.pop("stale_case")
    c = PT.plan_collapse(lambda: rows, seen_since=HANDOFF_FIRST).digest()
    assert len({a, b, c}) == 3


# ---------------------------------------------------------- placeholder twins: the address rule
def _twin_pair(parcel, live_addr, live_owner, old_addr, *, live_src=INFILL, old_src=VACANT,
               old_raw=None, live_raw=None):
    """A live placeholder row and the aging copy the 10/5 merge left beside it."""
    live = Listing(source=live_src, **SPBG, parcel_id=parcel, street_address=live_addr,
                   owner_name=live_owner, first_seen=datetime(2026, 10, 5, 1, 32, 20),
                   last_seen=datetime(2026, 10, 5, 1, 33, 55),
                   raw={"also_seen_in": [{"source": old_src}], **(live_raw or {})})
    old = Listing(source=old_src, **SPBG, parcel_id=parcel, street_address=old_addr,
                  owner_name="HALLIDAY Q STANFORD IV", first_seen=datetime(2026, 7, 22, 20, 42, 30),
                  last_seen=datetime(2026, 9, 22, 15, 43, 56), auction_status="presumed_withdrawn",
                  raw={"pulled_sale": _tag(1, src=old_src), "stale_case": True,
                       "vision": {"condition": "poor"}, **(old_raw or {})})
    return [old, live]


def test_an_owner_mailing_address_on_the_old_copy_is_not_published():
    """710297267572: county situs 'CONVAIR DR' (no number); the old copy's '717 TABERNACLE LN'
    is the owner's mailing address ('717 TABERNACLE LN LYMAN SC 29365' in the parcel cache)."""
    rows = _twin_pair("710297267572", "0 CONVAIR DR SPARTANBURG", "DARABAN CORNEL &",
                      "717 TABERNACLE LN",
                      old_raw={"owner_mailing": "1701 JOHN B WHITE SR BLVD SPARTANBURG SC 29301-5459",
                               "situs_road_only": {"road": "CONVAIR DR",
                                                   "reason": "sentinel_house_number:0"}},
                      live_raw={"owner_mailing": {"name": "DARABAN CORNEL &",
                                                  "mailing": "SPARTANBURG SC"}})
    plan = PT.plan_collapse(lambda: rows)
    assert len(plan.groups) == 1
    res = PT.apply_collapse(rows, plan, today=TODAY)
    (li,) = rows
    assert res["addresses_restored"] == 0
    assert li.street_address == "0 CONVAIR DR SPARTANBURG" and li.owner_name == "DARABAN CORNEL &"
    assert li.raw["owner_mailing"] == {"name": "DARABAN CORNEL &", "mailing": "SPARTANBURG SC"}
    assert "vision" not in li.raw                     # nothing the live row lacks comes from the copy
    assert not _tagged(li) and "stale_case" not in li.raw


def test_a_gis_situs_number_the_county_does_not_have_is_not_taken():
    """712290427499: 'gis_parcel_situs' wrote '419 DELLWATER WAY'; the county's own record is
    'DELLWATER WAY' with no number."""
    rows = _twin_pair("712290427499", "0 DELLWATER WAY SPARTANBURG", "HOWITT FOSTER M",
                      "419 DELLWATER WAY SPARTANBURG",
                      old_raw={"situs_address_source": "gis_parcel_situs"})
    PT.apply_collapse(rows, PT.plan_collapse(lambda: rows), today=TODAY)
    assert [li.street_address for li in rows] == ["0 DELLWATER WAY SPARTANBURG"]


def test_a_county_situs_still_replaces_the_sentinel():
    """710274436843: the parcel cache's situs is '329 LONDONBERRY DR SPARTANBURG'."""
    rows = _twin_pair("710274436843", "0 LONDONBERRY DR SPARTANBURG", "TIERMAN SANDRA LEE",
                      "329 LONDONBERRY DR SPARTANBURG",
                      old_raw={"situs_address_source": "parcel_cache:exact"})
    res = PT.apply_collapse(rows, PT.plan_collapse(lambda: rows), today=TODAY)
    assert res["addresses_restored"] == 1
    assert [li.street_address for li in rows] == ["329 LONDONBERRY DR SPARTANBURG"]


def test_a_legal_description_is_not_backfilled_into_an_empty_address():
    """SC|oconee|1450003017: the live sc_public_index row has no street; the qpaybill copy's
    '1244 HIGHLANDS 2802252' is a legal description."""
    live = Listing(source="counties_sc.sc_public_index", state="SC", county="Oconee",
                   source_url="https://publicindex.sccourts.org/Oconee/PublicIndex/CaseDetails."
                              "aspx?CaseNum=2026-CP-37-00812",
                   parcel_id="145-00-03-017", case_number="2026-CP-37-00812",
                   owner_name="Gross Drainage And Excavation Llc",
                   first_seen=datetime(2026, 8, 31), last_seen=datetime(2026, 10, 4, 20, 7, 54))
    old = Listing(source="counties_sc.qpaybill_delinquent_roll", state="SC", county="Oconee",
                  source_url="https://oconeesctax.qpaybill.com/Taxes/TaxesDefaultType4.aspx",
                  parcel_id="145-00-03-017", case_number="2026-CP-37-00812",
                  street_address="1244 HIGHLANDS 2802252",
                  owner_name="GROSS DRAINAGE & EXCAVATION LLC", first_seen=datetime(2026, 8, 31),
                  last_seen=datetime(2026, 9, 22, 15, 36, 18),
                  raw={"pulled_sale": _tag(1), "also_seen_in": [
                      {"source": "counties_sc.sc_public_index"}]})
    rows = [old, live]
    plan = PT.plan_collapse(lambda: rows)
    assert len(plan.groups) == 1
    PT.apply_collapse(rows, plan, today=TODAY)
    assert [li.street_address for li in rows] == [None]


def test_merge_prior_board_twin_fold_keeps_the_sentinel_over_a_mailing_address(tmp_path):
    old, live = _twin_pair("710297267572", "0 CONVAIR DR SPARTANBURG", "DARABAN CORNEL &",
                           "717 TABERNACLE LN")
    old.raw.pop("pulled_sale")
    old.auction_status = None
    (li,), st = merge_prior_board([live], docs_dir=_board(tmp_path, [old]), now=MERGE_NOW)
    assert st["matched_placeholder_twin"] == 1
    assert li.street_address == "0 CONVAIR DR SPARTANBURG" and "stale_case" not in li.raw


@pytest.mark.parametrize("live_addr", ["0 CONVAIR DR SPARTANBURG", None])
def test_dedupe_does_not_hand_a_live_row_an_aged_copys_mailing_address(live_addr):
    old, live = _twin_pair("710297267572", live_addr, "DARABAN CORNEL &", "717 TABERNACLE LN")
    (li,) = D.dedupe([old, live])
    assert li.street_address == live_addr and not _tagged(li)


def test_dedupe_still_takes_an_aged_copys_county_situs():
    old, live = _twin_pair("710274436843", "0 LONDONBERRY DR SPARTANBURG", "TIERMAN SANDRA LEE",
                           "329 LONDONBERRY DR SPARTANBURG",
                           old_raw={"situs_address_source": "parcel_cache:exact"})
    (li,) = D.dedupe([old, live])
    assert li.street_address == "329 LONDONBERRY DR SPARTANBURG"
