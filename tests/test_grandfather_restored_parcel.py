"""The GRANDFATHER restore must not re-add a prior row that merge_prior_board folded into its own
re-scrape by its restored short parcel id (docs/HANDOFF.md items 69-71, 80; the same hazard class as
the condominium fold, fixed there by condo_units.drop_folded_prior).

THE HAZARD. main.run() with GRANDFATHER_CARRIED=1 snapshots the prior published board before the merge
and, right before the write, restores every snapshot row whose dedupe_key the final board lacks. A row
validation stripped of its short parcel id (Catawba's 5-digit tax accounts) publishes with parcel None
and the county roll's URL as its key ('url:<delinquent_advertisement_list PDF>', the SAME key on every row
of the roll); its re-scrape keys 'parcel:NC:catawba:65771'. merge_prior_board folds the two through the
restored key, so the live row carries the prior row's enrichment, but the snapshot still holds the
prior copy under the URL key, which the final board (address-synthesized, deduped, validated) does not
carry: the restore published every folded account a second time.

MEASURED (read-only replay, 2026-10-06, on the published board's 8,422 rows that carry a restorable short
id, re-scraped with the id restored): 7,930 fold through the restored key; with GRANDFATHER_CARRIED=1 the
restore re-added 7,870 of the 8,422 rows after address synthesis, dedupe2 and validation (Catawba 3,659,
Guilford ptscloud 2,716, Pitt ptscloud 1,467, ...). The default is off on every host (nothing sets it).

REAL SHAPES. The rows are the Catawba PDF scraper's own (nc_county_pdf_delinquent_tax._to_listing) for
account numbers 65771 and 33566 as the county's 2026 list gives them, published through validation
exactly as a run publishes them; the owners are replaced.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from foreclosure_scraper import dedupe as D
from foreclosure_scraper import board_persist as bp
from foreclosure_scraper.board_persist import drop_folded_prior, merge_prior_board
from foreclosure_scraper.enrichment_address_final import enrich_with_address_synthesis
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_nc import nc_county_pdf_delinquent_tax as PDF
from foreclosure_scraper.validation import validate

NOW = datetime(2026, 10, 7, 2, 0, 0)
PRIOR_T = datetime(2026, 9, 22, 15, 36, 39)
CFG = PDF.COUNTIES["Catawba"]
SOURCE = "counties_nc.nc_county_pdf_delinquent_tax"
# (owner, account number, amount owed) as the 2026 list gives them; owners are fictional
ACCOUNTS = [("SAMPLE OWNER ONE", "65771", 1036.0), ("SAMPLE OWNER TWO TRUST", "33566", 23.0),
            ("SAMPLE OWNER THREE", "40001", 310.0)]


def scrape(accounts=ACCOUNTS) -> list[Listing]:
    return [PDF._to_listing(o, i, a, "Catawba", CFG) for o, i, a in accounts]


def published(li: Listing, *, legacy: bool = False) -> Listing:
    p = li.model_copy(deep=True)
    p.first_seen = p.last_seen = PRIOR_T
    validate([p])                               # nulls the 5-digit account, records it
    if legacy:
        p.raw.pop("parcel_id_nulled", None)     # a row published before that field
    return p


def board(tmp_path, rows) -> object:
    (tmp_path / "listings.json").write_text(json.dumps([r.model_dump(mode="json") for r in rows]))
    return tmp_path


def snapshot_of(rows: list[Listing]) -> list[Listing]:
    """main.run()'s GRANDFATHER snapshot: the prior published board, validated into Listings."""
    return [Listing.model_validate(r.model_dump(mode="json")) for r in rows]


def final_board(merged: list[Listing]) -> list[Listing]:
    """The steps main.run() runs between the merge and the restore that decide a row's key: address
    synthesis, dedupe2, validation."""
    enrich_with_address_synthesis(merged)
    out = D.dedupe(merged)
    validate(out)
    return out


def restored_by(snapshot, final) -> list[Listing]:
    """main.run()'s restore: every snapshot row whose key the final board lacks."""
    keys = {li.dedupe_key() for li in final}
    return [li for li in snapshot if li.dedupe_key() not in keys]


# --------------------------------------------------------------------------- the published shapes
def test_a_published_catawba_account_shares_the_roll_url_as_its_key():
    rows = [published(li) for li in scrape()]
    assert {li.parcel_id for li in rows} == {None}
    assert {li.dedupe_key() for li in rows} == {f"url:{CFG['url']}"}      # one key for the whole roll
    assert {bp._restored_key_of(li) for li in rows} == {
        "parcel:NC:catawba:65771", "parcel:NC:catawba:33566", "parcel:NC:catawba:40001"}
    # a live row (a parcel id) has no restored key
    assert bp._restored_key_of(scrape()[0]) is None


# --------------------------------------------------------------------------- the fold is recorded
@pytest.mark.parametrize("legacy", [False, True], ids=["nulled-id-recorded", "legacy-row"])
def test_the_restored_fold_is_listed_for_the_grandfather_snapshot(tmp_path, legacy):
    prior = [published(li, legacy=legacy) for li in scrape()]
    _, st = merge_prior_board(scrape(), docs_dir=board(tmp_path, prior), now=NOW)
    assert st["matched_restored_parcel"] == 3
    assert sorted(st["folded_prior_keys"]) == sorted(
        [f"parcel:NC:catawba:{a}", SOURCE, "restored"] for _, a, _ in ACCOUNTS)


def test_a_condominium_fold_and_a_restored_fold_are_listed_side_by_side(tmp_path):
    prior = [published(li) for li in scrape()[:1]]
    _, st = merge_prior_board(scrape()[:1], docs_dir=board(tmp_path, prior), now=NOW)
    mixed = {"folded_prior_keys": st["folded_prior_keys"] + [["parcel:NC:buncombe:9627023924",
                                                              "counties_nc.buncombe_elderly"]]}
    snap = snapshot_of(prior)
    bare = Listing(source="counties_nc.buncombe_elderly", source_url="https://example.test/e",
                   listing_type=ListingType.ELDERLY_DISABLED, state="NC", county="Buncombe",
                   parcel_id="9627023924", first_seen=PRIOR_T, last_seen=PRIOR_T)
    kept = drop_folded_prior(snap + [bare], mixed)
    assert kept == []                      # the Catawba row by its account, the bare-pin row by its key


# --------------------------------------------------------------------------- the restore itself
def test_without_the_fix_the_restore_would_publish_every_folded_account_twice(tmp_path):
    """The replay of the hazard on today's pipeline steps: the live rows carry the synthesized address,
    the snapshot copies carry the roll URL, so a key comparison cannot see they are the same lead."""
    prior = [published(li) for li in scrape()]
    merged, st = merge_prior_board(scrape(), docs_dir=board(tmp_path, prior), now=NOW)
    final = final_board(merged)
    assert len(final) == 3 and {li.parcel_id for li in final} == {None}
    snapshot = drop_folded_prior(snapshot_of(prior), st)
    assert restored_by(snapshot, final) == []                  # before the fix: 3 rows, one per account


def test_the_restore_still_keeps_an_account_the_rescrape_did_not_list(tmp_path):
    """One shared key for the whole roll: an account the county dropped from its list is not folded
    into anything, so its snapshot copy must not be dropped with the others (it is the only copy a
    downstream filter could still evict)."""
    prior = [published(li) for li in scrape()]
    rescrape = scrape(ACCOUNTS[:2])                              # 40001 is no longer listed
    merged, st = merge_prior_board(rescrape, docs_dir=board(tmp_path, prior), now=NOW)
    assert (st["matched_restored_parcel"], st["prior_only_kept"]) == (2, 1)
    snapshot = drop_folded_prior(snapshot_of(prior), st)
    assert [bp._restored_key_of(li) for li in snapshot] == ["parcel:NC:catawba:40001"]


def test_another_sources_row_with_the_same_account_is_not_dropped(tmp_path):
    prior = [published(li) for li in scrape()[:1]]
    _, st = merge_prior_board(scrape()[:1], docs_dir=board(tmp_path, prior), now=NOW)
    other = published(scrape()[0])
    other.source = "counties_nc.nc_ptscloud_delinquent_tax"      # same short id, another source's roll
    other.raw.pop("nc_county_pdf_delinquent_tax")
    other.raw["nc_ptscloud_delinquent_tax"] = {"parcel": "65771"}
    kept = drop_folded_prior(snapshot_of(prior) + [other], st)
    assert [li.source for li in kept] == [other.source]


def test_a_snapshot_row_with_a_parcel_id_is_never_matched_by_a_restored_key(tmp_path):
    prior = [published(li) for li in scrape()[:1]]
    _, st = merge_prior_board(scrape()[:1], docs_dir=board(tmp_path, prior), now=NOW)
    live = scrape()[0]                                           # parcel '65771' as the scrape gives it
    assert drop_folded_prior([live], st) == [live]
