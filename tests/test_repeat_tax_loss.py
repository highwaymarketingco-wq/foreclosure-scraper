"""Tests for enrichment_repeat_tax_loss -- Dirty Deeds Tier A #34.

"Match tax-deed grantors back to the current owner index. A proven
non-payer with proven capitulation."
"""
from __future__ import annotations

import pytest

from foreclosure_scraper import deed_index
from foreclosure_scraper.deed_index import DeedInstrument, Party
from foreclosure_scraper.enrichment_deed_chain import enrich_deed_chain
from foreclosure_scraper.enrichment_repeat_tax_loss import (
    count_candidate_owners, enrich_repeat_tax_loss,
)
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.rod import cchs
from foreclosure_scraper.rod import inst_class as ic
from foreclosure_scraper.web_artifact import RAW_KEEP


@pytest.fixture(autouse=True)
def _no_real_sidecar(tmp_path, monkeypatch):
    """enrich_repeat_tax_loss reads data/deed_index.db by default. Once the owner
    has run the sweep that file exists, and these tests must not see it."""
    monkeypatch.setattr(deed_index, "DB_PATH", tmp_path / "absent" / "deed_index.db")


def _mk(owner_name, county="Buncombe", state="NC", parcel_id=None,
        deed_chain=None, source="s", source_url=None):
    return Listing(
        source=source, source_url=source_url or f"https://example.com/{owner_name}-{parcel_id}",
        listing_type=ListingType.TAX_LIEN, state=state, county=county,
        owner_name=owner_name, parcel_id=parcel_id,
        raw={"deed_chain": deed_chain} if deed_chain else {},
    )


def _dc(grantor, doc_type, date="2020-01-01"):
    return {
        "summary": {
            "prior_owner": grantor,
            "distress_transfers": [
                {"date": date, "doc_type": doc_type, "grantor": grantor, "price": None, "source": "rod"},
            ],
        }
    }


def test_owner_who_lost_a_parcel_and_holds_another_is_flagged():
    # SMITH JOHN lost parcel P1 to a tax deed in 2020...
    lost = _mk("SMITH JOHN", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "TAX DEED"))
    # ...and currently owns a DIFFERENT parcel P2, same county/state.
    current = _mk("SMITH JOHN", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["losses_indexed"] == 1
    assert stats["tagged_rows"] == 1
    assert "repeat_tax_loss" not in (lost.raw or {})
    assert current.raw["repeat_tax_loss"]["prior_losses"] == 1
    assert current.raw["repeat_tax_loss"]["most_recent_loss_doc_type"] == "TAX DEED"


def test_redemption_of_the_same_parcel_is_not_flagged():
    # The SAME parcel, same owner, same property key -- a buy-back/
    # redemption, not "still holds another property".
    lost = _mk("SMITH JOHN", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "TAX DEED"))
    stats = enrich_repeat_tax_loss([lost])
    assert stats["tagged_rows"] == 0
    assert "repeat_tax_loss" not in (lost.raw or {})


def test_non_loss_doc_type_is_ignored():
    # A quitclaim in distress_transfers is real distress but not a tax/
    # foreclosure-sale LOSS -- must not seed the loser index.
    lost = _mk("SMITH JOHN", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "QUITCLAIM"))
    current = _mk("SMITH JOHN", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["losses_indexed"] == 0
    assert "repeat_tax_loss" not in (current.raw or {})


def test_different_county_does_not_match():
    lost = _mk("SMITH JOHN", county="Buncombe", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "TAX DEED"))
    current = _mk("SMITH JOHN", county="Henderson", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["tagged_rows"] == 0


def test_entity_owner_never_matches():
    lost = _mk("ABC HOLDINGS LLC", parcel_id="P1", deed_chain=_dc("ABC HOLDINGS LLC", "TAX DEED"))
    current = _mk("ABC HOLDINGS LLC", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["losses_indexed"] == 0
    assert stats["tagged_rows"] == 0


def test_no_deed_chain_is_a_no_op_not_an_error():
    a = _mk("SMITH JOHN", parcel_id="P1")
    b = _mk("SMITH JOHN", parcel_id="P2")
    stats = enrich_repeat_tax_loss([a, b])
    assert stats["losses_indexed"] == 0
    assert stats["tagged_rows"] == 0


def test_most_recent_loss_picked_when_multiple():
    lost1 = _mk("SMITH JOHN", parcel_id="P1", deed_chain=_dc("SMITH JOHN", "TAX DEED", date="2018-01-01"))
    lost2 = _mk("SMITH JOHN", parcel_id="P2", deed_chain=_dc("SMITH JOHN", "SHERIFF'S DEED", date="2022-06-01"))
    current = _mk("SMITH JOHN", parcel_id="P3")
    stats = enrich_repeat_tax_loss([lost1, lost2, current])
    assert current.raw["repeat_tax_loss"]["prior_losses"] == 2
    assert current.raw["repeat_tax_loss"]["most_recent_loss_date"] == "2022-06-01"
    assert current.raw["repeat_tax_loss"]["most_recent_loss_doc_type"] == "SHERIFF'S DEED"


# ---------------------------------------------------------------------------------
# 2026-09-20: the four defects that kept the signal at 0 after data existed
# (docs/deed_index_scoping_2026-09-20.md, F1 to F5).
# ---------------------------------------------------------------------------------
FIRM = "PLACEHOLDER TRUSTEE SERVICES PLLC"


def _chain(entries, prior_owner=None):
    return {"summary": {"prior_owner": prior_owner, "distress_transfers": entries}}


def _entry(doc_type, grantors=None, grantor=None, date="2022-03-01", **extra):
    e = {"date": date, "doc_type": doc_type, "price": None, "source": "rod_docs", **extra}
    if grantors is not None:
        e["grantors"] = grantors
    if grantor is not None:
        e["grantor"] = grantor
    return e


@pytest.mark.parametrize("doc_type", ["TR/D", "TRUSTEES DEED", "TRUSTEE'S DEED", "SUBSTITUTE TRUSTEES DEED"])
def test_f1_trustee_deed_in_any_spelling_seeds_the_loser_index(doc_type):
    """TR/D matched nothing, and TRUSTEES DEED (CCHS drops the apostrophe) did not
    match TRUSTEE'S DEED."""
    lost = _mk("DOE JOHN", parcel_id="P1",
               deed_chain=_chain([_entry(doc_type, grantors=[FIRM, "DOE JOHN"])]))
    current = _mk("DOE JOHN", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["losses_indexed"] == 1 and stats["tagged_rows"] == 1
    assert current.raw["repeat_tax_loss"]["most_recent_loss_class"] == ic.TRUSTEE_DEED
    assert current.raw["repeat_tax_loss"]["most_recent_loss_doc_type"] == doc_type


@pytest.mark.parametrize("doc_type,cls", [("COM/D", ic.COMMISSIONER_DEED),
                                          ("COMMISSIONER'S DEED", ic.COMMISSIONER_DEED),
                                          ("SHF/D", ic.SHERIFF_DEED),
                                          ("SHERIFFS DEED", ic.SHERIFF_DEED),
                                          ("TAX DEED", ic.TAX_DEED)])
def test_f1_the_other_loss_codes_are_recognized(doc_type, cls):
    lost = _mk("DOE JOHN", parcel_id="P1", deed_chain=_chain([_entry(doc_type, grantors=["DOE JOHN"])]))
    current = _mk("DOE JOHN", parcel_id="P2")
    assert enrich_repeat_tax_loss([lost, current])["tagged_rows"] == 1
    assert current.raw["repeat_tax_loss"]["most_recent_loss_class"] == cls


def test_f1_a_trustee_deed_that_is_not_a_loss_is_not_indexed():
    # only a trust conveys: no borrower on the instrument
    lost = _mk("DOE JOHN", parcel_id="P1",
               deed_chain=_chain([_entry("TR/D", grantors=["SAMPLE FAMILY LIVING TRUST"])]))
    current = _mk("DOE JOHN", parcel_id="P2")
    assert enrich_repeat_tax_loss([lost, current])["losses_indexed"] == 0


def test_f3_no_grantor_on_the_transfer_means_no_loser_not_the_prior_owner():
    """The old code fell back to summary.prior_owner: the grantor of the newest
    transfer that has one, rarely the person who lost THIS parcel."""
    lost = _mk("DOE JOHN", parcel_id="P1",
               deed_chain=_chain([_entry("TAX DEED")], prior_owner="DOE JOHN"))
    current = _mk("DOE JOHN", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current])
    assert stats["losses_indexed"] == 0 and "repeat_tax_loss" not in (current.raw or {})


def test_f3_deed_chain_keeps_the_loser_on_the_distress_entry():
    li = Listing(source="s", source_url="https://example.com/1", listing_type=ListingType.TAX_LIEN,
                 state="SC", county="Anderson", owner_name="X", parcel_id="P1",
                 raw={"assessor_card": {"sales": [{
                     "sale_date": "2021-04-02", "price": 0, "grantor": "DOE JOHN",
                     "grantee": "EXAMPLE COUNTY", "reason": "TAX DEED", "book": "8000", "page": "12"}]}})
    enrich_deed_chain([li])
    (t,) = li.raw["deed_chain"]["summary"]["distress_transfers"]
    assert t["grantor"] == "DOE JOHN" and t["grantee"] == "EXAMPLE COUNTY"
    assert (t["book"], t["page"], t["inst_class"]) == ("8000", "12", ic.TAX_DEED)


def test_f1_and_f3_deed_chain_takes_a_cchs_trustee_deed_from_rod_docs_with_all_its_parties():
    """A CCHS document read by _parse_rows: doc_type is the vendor code and the
    normalized label carries no 'DEED'. It used to be filtered out of the chain."""
    xml = ('<r><da>03/14/2025</da><ki>TR/D</ki><bk>9001</bk><pg>101</pg><dn>2025000101</dn>'
           '<or>PLACEHOLDER TRUSTEE SERVICES PLLC</or><ee>EXAMPLE MORTGAGE HOLDINGS LLC</ee><mo>$135.00</mo></r>'
           '<r><da>03/14/2025</da><ki>TR/D</ki><bk>9001</bk><pg>101</pg><dn>2025000101</dn>'
           '<or>DOE</or><or1>JOHN</or1><ee>EXAMPLE MORTGAGE HOLDINGS LLC</ee><mo>$135.00</mo></r>')
    (doc,) = cchs._parse_rows(xml, "NC", "Burke", sold=True)
    li = Listing(source="s", source_url="https://example.com/2", listing_type=ListingType.TAX_LIEN,
                 state="NC", county="Burke", owner_name="X", parcel_id="P1",
                 raw={"rod_docs": [doc.to_dict()]})
    enrich_deed_chain([li])
    (t,) = li.raw["deed_chain"]["summary"]["distress_transfers"]
    assert t["inst_class"] == ic.TRUSTEE_DEED
    assert t["grantors"] == ["PLACEHOLDER TRUSTEE SERVICES PLLC", "DOE JOHN"]
    assert (t["book"], t["page"]) == ("9001", "101")
    # and the join finds the borrower, not the firm
    other = _mk("DOE JOHN", county="Burke", parcel_id="P2")
    assert enrich_repeat_tax_loss([li, other])["tagged_rows"] == 1


def test_a_deed_of_trust_in_rod_docs_does_not_make_the_owner_his_own_prior_owner():
    li = Listing(source="s", source_url="https://example.com/3", listing_type=ListingType.TAX_LIEN,
                 state="NC", county="Burke", owner_name="DOE JOHN", parcel_id="P1",
                 raw={"rod_docs": [{"doc_type": "DEED OF TRUST", "recorded_date": "2020-01-01",
                                    "book": "1", "page": "2", "grantor": "DOE JOHN", "raw": {"ki": "D/T"}}]})
    enrich_deed_chain([li])
    assert li.raw["deed_chain"]["summary"]["prior_owner"] is None


# --- F5: the sidecar ----------------------------------------------------------------
def _row(names, county="Burke", state="NC", date="2024-05-01", book="9001", page="101",
         parcel="9-1000001", code="TR/D", cls=ic.TRUSTEE_DEED):
    return {"county": county, "state": state, "recorded_date": date, "book": book, "page": page,
            "parcel_id": parcel, "inst_code": code, "inst_class": cls, "loser_names": names,
            "doc_key": f"{county}|{state}|{book}|{page}||{code}"}


def test_f5_a_loss_on_a_parcel_that_is_not_on_the_board_still_flags_the_owner():
    """The whole point of the sweep: nobody put the parcel he lost on the board."""
    current = _mk("DOE JOHN Q", county="Burke", parcel_id="P2")
    stats = enrich_repeat_tax_loss([current], deed_index_rows=[_row(["DOE JOHN Q"])])
    assert stats["losses_indexed"] == 1 and stats["index_rows"] == 1 and stats["tagged_rows"] == 1
    rtl = current.raw["repeat_tax_loss"]
    assert rtl["prior_losses"] == 1 and rtl["most_recent_loss_date"] == "2024-05-01"
    assert rtl["most_recent_loss_doc_type"] == "TR/D" and rtl["most_recent_loss_class"] == ic.TRUSTEE_DEED
    # the recorded instrument behind the tag, for someone to pull at the recorder
    assert current.raw["deed_index"] == [{"inst_class": ic.TRUSTEE_DEED, "date": "2024-05-01",
                                          "book": "9001", "page": "101", "role": "grantor",
                                          "county": "BURKE"}]


def test_f5_the_name_join_stays_inside_one_county_and_state():
    other_county = _mk("DOE JOHN Q", county="Henderson", parcel_id="P2")
    other_state = _mk("DOE JOHN Q", county="Burke", state="SC", parcel_id="P3")
    stats = enrich_repeat_tax_loss([other_county, other_state],
                                   deed_index_rows=[_row(["DOE JOHN Q"], county="Burke", state="NC")])
    assert stats["tagged_rows"] == 0


def test_f5_an_entity_or_initial_only_name_in_the_sidecar_never_matches():
    llc = _mk("SAMPLE HOLDINGS LLC", parcel_id="P2")
    initial = _mk("DOE J", parcel_id="P3")
    stats = enrich_repeat_tax_loss([llc, initial],
                                   deed_index_rows=[_row(["SAMPLE HOLDINGS LLC"]), _row(["DOE J"], page="102")])
    assert stats["losses_indexed"] == 0 and stats["tagged_rows"] == 0


def test_f5_the_parcel_he_lost_is_not_another_property_by_parcel_key():
    """Vendor key 1-3405501 and board key 13405501 are the same parcel."""
    same = _mk("DOE JOHN Q", county="Burke", parcel_id="13405501")
    assert enrich_repeat_tax_loss([same], deed_index_rows=[_row(["DOE JOHN Q"], parcel="1-3405501")])["tagged_rows"] == 0


def test_f5_the_parcel_he_lost_is_not_another_property_by_book_and_page():
    """The vendor's parcel key is not the board's PIN, so book/page decides: the
    listing's own chain already holds the very deed that took the parcel."""
    li = _mk("DOE JOHN Q", county="Burke", parcel_id="PIN-NOT-THE-VENDOR-KEY")
    li.raw = {"deed_chain": {"transfers": [{"date": "2024-05-01", "book": "09001", "page": "101"}],
                             "summary": {"distress_transfers": []}}}
    assert enrich_repeat_tax_loss([li], deed_index_rows=[_row(["DOE JOHN Q"])])["tagged_rows"] == 0
    other = _mk("DOE JOHN Q", county="Burke", parcel_id="PIN-NOT-THE-VENDOR-KEY")
    other.raw = {"deed_chain": {"transfers": [{"date": "2019-01-01", "book": "7", "page": "8"}],
                                "summary": {"distress_transfers": []}}}
    assert enrich_repeat_tax_loss([other], deed_index_rows=[_row(["DOE JOHN Q"])])["tagged_rows"] == 1


def test_f5_the_same_deed_from_the_board_and_the_sidecar_counts_once():
    lost = _mk("DOE JOHN Q", county="Burke", parcel_id="P1", deed_chain=_chain([
        _entry("TR/D", grantors=[FIRM, "DOE JOHN Q"], date="2024-05-01", book="9001", page="101")]))
    current = _mk("DOE JOHN Q", county="Burke", parcel_id="P2")
    stats = enrich_repeat_tax_loss([lost, current], deed_index_rows=[_row(["DOE JOHN Q"])])
    assert stats["losses_indexed"] == 1
    assert current.raw["repeat_tax_loss"]["prior_losses"] == 1


def test_f5_two_different_losses_count_twice_newest_first():
    current = _mk("DOE JOHN Q", county="Burke", parcel_id="P9")
    enrich_repeat_tax_loss([current], deed_index_rows=[
        _row(["DOE JOHN Q"], date="2018-02-01", page="5"),
        _row(["DOE JOHN Q"], date="2023-07-01", page="6", code="COM/D", cls=ic.COMMISSIONER_DEED)])
    assert current.raw["repeat_tax_loss"]["prior_losses"] == 2
    assert current.raw["repeat_tax_loss"]["most_recent_loss_date"] == "2023-07-01"
    assert [d["date"] for d in current.raw["deed_index"]] == ["2023-07-01", "2018-02-01"]


def test_f5_evidence_is_capped():
    current = _mk("DOE JOHN Q", county="Burke", parcel_id="P9")
    enrich_repeat_tax_loss([current], deed_index_rows=[_row(["DOE JOHN Q"], page=str(n), date=f"20{10 + n}-01-01")
                                                      for n in range(8)])
    assert current.raw["repeat_tax_loss"]["prior_losses"] == 8
    assert len(current.raw["deed_index"]) == 5


def test_f5_the_default_reads_the_sidecar_file_and_a_missing_file_is_harmless(tmp_path, monkeypatch):
    current = _mk("SAMPLE ALEX B", county="Burke", parcel_id="P2")
    assert enrich_repeat_tax_loss([current])["index_rows"] == 0            # no sidecar yet
    db = tmp_path / "deed_index.db"
    monkeypatch.setattr(deed_index, "DB_PATH", db)
    con = deed_index.connect(db)
    parties = [Party("ROE RICHARD T", kind="I", suffix="COMM"), Party("SAMPLE ALEX B", kind="I")]
    kind, losers = deed_index.derive_loss(ic.COMMISSIONER_DEED, parties, "TAX FORECLOSURE")
    deed_index.upsert(con, [DeedInstrument(
        county="Burke", state="NC", source="cchs_classic", inst_code="COM/D", inst_class=ic.COMMISSIONER_DEED,
        recorded_date="2025-06-02", book="9001", page="240", instrument_no="2025000240",
        grantors=[p.name for p in parties], grantor_parties=parties, parcel_id="9-1000002",
        description="TAX FORECLOSURE", loss_kind=kind, loser_names=losers)])
    stats = enrich_repeat_tax_loss([current])
    assert stats["index_rows"] == 1 and stats["tagged_rows"] == 1
    assert current.raw["repeat_tax_loss"]["most_recent_loss_class"] == ic.COMMISSIONER_DEED


def test_count_candidate_owners_previews_a_streamed_board_without_the_guard():
    rows = [{"owner_name": "DOE JOHN Q", "county": "Burke", "state": "NC"},
            {"owner_name": "DOE JOHN Q", "county": "Lincoln", "state": "NC"},
            {"owner_name": "SAMPLE HOLDINGS LLC", "county": "Burke", "state": "NC"},
            {"owner_name": None, "county": "Burke", "state": "NC"},
            {"owner_name": "DOE JOHN Q", "county": None, "state": "NC"}]
    got = count_candidate_owners(iter(rows), [_row(["DOE JOHN Q", "SAMPLE HOLDINGS LLC"])])
    assert got == {"rows_scanned": 5, "loser_keys": 1, "candidate_rows": 1}
    assert count_candidate_owners(iter(rows), [])["candidate_rows"] == 0


def test_the_raw_keys_this_enricher_writes_survive_the_publish_slim():
    """_slim_raw() silently drops any raw key that is not in RAW_KEEP."""
    assert "repeat_tax_loss" in RAW_KEEP and "deed_index" in RAW_KEEP


def test_a_tax_deed_whose_doc_type_was_flattened_to_deed_is_still_a_distress_transfer():
    """An older normalize_doc_type stored 'DEED' for a raw 'TAX DEED'. The record
    carries the class read from raw['ki'], and the chain must honour it."""
    li = Listing(source="s", source_url="https://example.com/4", listing_type=ListingType.TAX_LIEN,
                 state="SC", county="Anderson", owner_name="X", parcel_id="P1",
                 raw={"rod_docs": [{"doc_type": "DEED", "recorded_date": "2021-04-02", "book": "8000",
                                    "page": "12", "grantor": "DOE JOHN", "grantee": "EXAMPLE COUNTY",
                                    "raw": {"ki": "TAX DEED"}}]})
    enrich_deed_chain([li])
    (t,) = li.raw["deed_chain"]["summary"]["distress_transfers"]
    assert t["inst_class"] == ic.TAX_DEED and t["grantor"] == "DOE JOHN"
