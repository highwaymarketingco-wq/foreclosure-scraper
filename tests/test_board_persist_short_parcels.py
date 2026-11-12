"""merge_prior_board must not fold a prior row into the fresh row of ANOTHER parcel id of the same source,
however short the ids (docs/HANDOFF.md item 80; the merge-time twin of dedupe.different_source_parcels,
item 76).

THE GAP. dedupe.identity_conflict refuses two different parcel ids published by ONE source in one county,
however short (09779715), but board_persist._different_valid_parcels (the match merge_prior_board makes
between a published row and a fresh one) only compared VALID parcels. A published row whose short id
validation nulled (an id under 7 characters: Rutherford's 6-digit accounts, ptscloud's 6-digit bills)
carries parcel None, so it had nothing to compare; the fresh row, not yet validated at merge time, still
carries its own id. Any shared address signature then folded the prior row into the fresh row of a
different bill, handing it that lead's phone, skip trace and first_seen, and the prior row's own lead
vanished instead of aging.

REAL SHAPES. Each pair in RUTHERFORD is a real pair of rutherford_tax rows from the 10/5 fresh scrape (ids,
situs and zip as the county published them; they are the pairs of tests/test_dedupe_short_parcels.py whose
address signature the two rows share): one situs, two bills, two parcel ids, different tax amounts. MADISON
is the shape of the one pair the published board holds (223,832 stubs replayed): nc_ptscloud_delinquent_tax,
one taxpayer, one situs, a 2018 bill on a 10-digit PIN and a 2025 bill on a 6-digit account with its own
assessed value (its ids, situs and amounts are replaced here). Owner names are not used.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from foreclosure_scraper import board_persist as bp
from foreclosure_scraper.board_persist import merge_prior_board
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.validation import validate

NOW = datetime(2026, 10, 7, 2, 0, 0)
PRIOR_T = datetime(2026, 9, 22, 15, 36, 39)
RUTHERFORD_URL = ("https://www.rutherfordcountync.gov/TR-452%20Delinquent%20Bills%20Report%20w%20"
                  "Parcel%20Id.xlsx")
PTSCLOUD_URL = "https://bcpwa.ncptscloud.com/"

# (parcel, situs, zip) x 2: one source, two bills, two parcels, one address signature shared
RUTHERFORD = [
    (("915784", "139 INGLE HILL ST", "28114"), ("1637150", "139 INGLE HILL ST", "28114")),
    (("1626363", "146 WALDO LN", "28018"), ("320042", "146 WALDO LN", "28018")),
    (("1628211", "217 JORDON TRL", "28018"), ("713143", "217 JORDON TRL", "28018")),
    (("1622263", "147 SHASTA LN", "28114"), ("908154", "147 SHASTA LN", "28114")),
    (("329127", "183 LEDFORD RD", "28040"), ("1619686", "183 LEDFORD RD", "28040")),
    (("421048", "207 E TRADE ST", "28043"), ("422617", "207 E TRADE ST", "28043")),
    (("911936", "5040 US 221S HWY", "28043"), ("1647414", "5040 US 221S HWY", "28043")),
    (("323133", "667 WEBB RD", "28040"), ("317482", "667 WEBB RD", "28043")),
]
PAIRS = [pytest.param(a, b, id=f"{a[0]}-{b[0]}") for a, b in RUTHERFORD] + \
        [pytest.param(b, a, id=f"{b[0]}-{a[0]}") for a, b in RUTHERFORD]


def rtax(spec, **kw) -> Listing:
    parcel, addr, zip_code = spec
    base = dict(source="counties_nc.rutherford_tax", source_url=RUTHERFORD_URL,
                listing_type=ListingType.TAX_LIEN, state="NC", county="Rutherford",
                parcel_id=parcel, street_address=addr, zip_code=zip_code, first_seen=NOW,
                last_seen=NOW, raw={"rutherford_tax": {"parcel": parcel}})
    base.update(kw)
    return Listing(**base)


def published(li: Listing, *, legacy: bool = False, phone: str | None = "(828) 555-0100") -> Listing:
    """The row as a full run publishes it: validation nulls an id under 7 characters (and records it in
    raw['parcel_id_nulled']; legacy=True is a row published before that field). It carries an
    enrichment (a phone) a wrong fold would lend to another lead."""
    p = li.model_copy(deep=True)
    p.first_seen = p.last_seen = PRIOR_T
    validate([p])
    if legacy:
        p.raw.pop("parcel_id_nulled", None)
    if phone:
        p.raw["owner_phone"] = phone
    return p


def board(tmp_path, rows) -> object:
    (tmp_path / "listings.json").write_text(json.dumps([r.model_dump(mode="json") for r in rows]))
    return tmp_path


def _aged(li: Listing) -> bool:
    return bool((li.raw or {}).get("pulled_sale"))


# --------------------------------------------------------------------------- the real Rutherford pairs
@pytest.mark.parametrize("prior_spec,fresh_spec", PAIRS)
@pytest.mark.parametrize("legacy", [False, True], ids=["nulled-id-recorded", "legacy-row"])
def test_a_nulled_short_id_does_not_fold_into_another_bill_of_the_same_source(
        tmp_path, prior_spec, fresh_spec, legacy):
    prior = published(rtax(prior_spec), legacy=legacy)
    fresh = rtax(fresh_spec)
    merged, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [prior]), now=NOW)
    assert (st["matched"], st["refused_different_parcel"], st["prior_only_kept"]) == (0, 1, 1)
    assert len(merged) == 2
    (live,) = [li for li in merged if not _aged(li)]
    (old,) = [li for li in merged if _aged(li)]
    # the fresh bill did not take the other bill's enrichment or first_seen; the prior lead is still there
    assert live.first_seen == NOW and "owner_phone" not in live.raw
    assert old.raw["owner_phone"] == "(828) 555-0100" and old.first_seen == PRIOR_T


@pytest.mark.parametrize("prior_spec,fresh_spec", RUTHERFORD[:4])
def test_a_valid_prior_id_does_not_fold_into_another_short_id_of_its_source(
        tmp_path, prior_spec, fresh_spec):
    """The mirror case: the published row's id is 7 digits and stays (a valid parcel), the fresh row
    carries a 6-digit one. identity() sees a valid parcel on one side only."""
    prior_spec, fresh_spec = max(prior_spec, fresh_spec, key=lambda s: len(s[0])), \
        min(prior_spec, fresh_spec, key=lambda s: len(s[0]))
    assert len(prior_spec[0]) == 7 and len(fresh_spec[0]) == 6
    prior = published(rtax(prior_spec))
    assert prior.parcel_id == prior_spec[0]
    merged, st = merge_prior_board([rtax(fresh_spec)], docs_dir=board(tmp_path, [prior]), now=NOW)
    assert (st["matched"], st["refused_different_parcel"], st["prior_only_kept"]) == (0, 1, 1)
    assert sum(_aged(li) for li in merged) == 1


# --------------------------------------------------------------------------- what still matches
def test_the_same_bill_rescraped_still_matches_its_own_published_row(tmp_path):
    spec = RUTHERFORD[0][0]
    prior = published(rtax(spec))
    merged, st = merge_prior_board([rtax(spec)], docs_dir=board(tmp_path, [prior]), now=NOW)
    assert (st["matched"], st["refused_different_parcel"], st["prior_only_kept"]) == (1, 0, 0)
    (li,) = merged
    assert li.first_seen == PRIOR_T and li.raw["owner_phone"] == "(828) 555-0100" and not _aged(li)


def test_ids_of_two_different_sources_do_not_conflict(tmp_path):
    """One source's 6-digit account and another source's 7-digit parcel on one situs are two id systems
    (dedupe.different_source_parcels needs ONE source): the row still folds, as before."""
    prior_spec, fresh_spec = RUTHERFORD[0]
    prior = published(rtax(prior_spec))
    other = rtax(fresh_spec, source="counties_nc.nc_county_pdf_delinquent_tax",
                 raw={"nc_county_pdf_delinquent_tax": {"county_id": fresh_spec[0]}})
    _, st = merge_prior_board([other], docs_dir=board(tmp_path, [prior]), now=NOW)
    assert (st["matched"], st["refused_different_parcel"], st["prior_only_kept"]) == (1, 0, 0)


def test_a_resolver_attached_id_is_no_identity(tmp_path):
    """A parcel enrichment_parcel_from_address attached proves nothing (dedupe.source_parcel ignores
    it): the prior row, carrying a resolver's 7-digit id, still folds into the source's own bill."""
    prior_spec, fresh_spec = RUTHERFORD[0][1], RUTHERFORD[0][0]
    prior = published(rtax(prior_spec))
    prior.raw["parcel_from_address"] = {"matched": prior_spec[1]}
    _, st = merge_prior_board([rtax(fresh_spec)], docs_dir=board(tmp_path, [prior]), now=NOW)
    assert (st["matched"], st["refused_different_parcel"]) == (1, 0)


def test_two_house_numbers_still_never_match(tmp_path):
    """The house-number guard is untouched: it was refused before this rule and still is."""
    prior = published(rtax(("915784", "139 INGLE HILL ST", "28114")))
    fresh = rtax(("915784", "141 INGLE HILL ST", "28114"))
    _, st = merge_prior_board([fresh], docs_dir=board(tmp_path, [prior]), now=NOW)
    assert st["matched"] == 0 and st["prior_only_kept"] == 1


# --------------------------------------------------------------------------- the published board's pair
def _ptscloud(parcel, bill_year, amount, zip_code, assessed):
    return Listing(
        source="counties_nc.nc_ptscloud_delinquent_tax", source_url=PTSCLOUD_URL,
        listing_type=ListingType.TAX_LIEN, state="NC", county="Madison", parcel_id=parcel,
        street_address="1200 SAMPLE HWY", zip_code=zip_code, first_seen=NOW, last_seen=NOW,
        raw={"nc_ptscloud_delinquent_tax": {"tenant": "Madison", "parcel": parcel,
                                            "principal_tax_due": amount, "tax_year": bill_year,
                                            "assessed_value": assessed}})


def test_the_published_madison_pair_is_two_bills_not_one_property(tmp_path):
    """Published 2026-09-22: the 2018 bill on a 10-digit PIN (valid parcel) and the 2025 bill on a
    6-digit account (nulled). One taxpayer and one situs, but two ids of one source's roll with two
    assessed values: the fresh account bill no longer takes the PIN bill's published row."""
    pin_bill = published(_ptscloud("8800001234", "2018", 4000.0, None, 55000.0))
    fresh_account = _ptscloud("600001", "2025", 2000.0, "28700", 74000.0)
    merged, st = merge_prior_board([fresh_account], docs_dir=board(tmp_path, [pin_bill]), now=NOW)
    assert (st["matched"], st["refused_different_parcel"], st["prior_only_kept"]) == (0, 1, 1)
    assert {li.raw["nc_ptscloud_delinquent_tax"]["parcel"] for li in merged} == {"8800001234", "600001"}


def test_the_prior_identity_carries_the_nulled_id_and_nothing_else():
    prior = published(rtax(("915784", "139 INGLE HILL ST", "28114")))
    rec = prior.model_dump(mode="json")
    ident = bp._prior_identity(rec)
    assert prior.parcel_id is None and ident.pk is None
    assert ident.sp == frozenset({("NC|rutherford|915784", "counties_nc.rutherford_tax")})
    # a row that never had a parcel gets no id; a valid parcel keeps its own
    assert bp._prior_identity({**rec, "raw": {}, "source": "x"}).sp == frozenset()
    valid = published(rtax(("1637150", "139 INGLE HILL ST", "28114"))).model_dump(mode="json")
    assert bp._prior_identity(valid).sp == frozenset({("NC|rutherford|1637150",
                                                       "counties_nc.rutherford_tax")})
