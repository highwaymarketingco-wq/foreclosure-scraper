"""Two rows with different house numbers are two houses, and must never merge.

MEASURED ON THE LIVE BOARD 2026-09-11. The union-find pass merges 7,336 groups. 6,841
of them share one address and are legitimate -- '11 carefree lane' vs '11 carefree ln',
'90 indiana ave' vs '90 indiana avenue', the same Buncombe house arriving from liensnc,
buncombe_elderly and buncombe_delinquent_tax. But 384 groups merge rows whose addresses
genuinely differ, and the clearest are:

    '306 fountain way'            + '346 fountain way'             parcel 9698372180
    '545 dillingham panoview rd'  + '562 dillingham panoview rd'

Two separate houses fused because one carries the other's parcel id. The signature doing
it is ('p', parcel, STATE) from _strong_sigs -- state-scoped, so one wrong parcel value
reaches across a whole state. This is the third instance of the same shape on this
project: a degenerate identity value silently deleting properties, with nothing in any
log to show for it.

The guard cannot repair a bad parcel. It stops the MERGE, which is the half that loses
data, and it logs how often it fired.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def L(addr, parcel=None, county="Buncombe", state="NC", src="a", zip_code=None):
    return Listing(source=src, source_url="u", listing_type=ListingType.TAX_SALE,
                   property_kind=PropertyKind.UNKNOWN, state=state, county=county,
                   parcel_id=parcel, street_address=addr, zip_code=zip_code,
                   first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw={})


def test_two_houses_sharing_one_parcel_id_stay_two_rows():
    """THE case, verbatim from the board."""
    out = dedupe([L("306 Fountain Way", "9698372180", src="liensnc"),
                  L("346 Fountain Way", "9698372180", src="buncombe_elderly")])
    assert len(out) == 2, "different house numbers are different houses"


def test_the_second_real_case():
    out = dedupe([L("545 Dillingham Panoview Rd", "969849748000000"),
                  L("562 Dillingham Panoview Rd", "969849748000000")])
    assert len(out) == 2


def test_the_same_house_written_differently_still_merges():
    """93% of real merge groups are this. The guard must not cost them."""
    for a, b in [("318 Fairfax Ave", "318 Fairfax Ave."),
                 ("11 Carefree Lane", "11 Carefree Ln"),
                 ("90 Indiana Ave", "90 Indiana Avenue"),
                 ("4 Austin Ave", "4 Austin Avenue")]:
        out = dedupe([L(a, "9638108274", src="x"), L(b, "9638108274", src="y")])
        assert len(out) == 1, f"{a!r} and {b!r} are the same house and should merge"


def test_a_row_without_a_house_number_is_not_blocked():
    """The guard only fires when BOTH rows carry a number. A row with a bare street
    name must still be free to merge -- we cannot prove it is a different property."""
    out = dedupe([L("Fountain Way", "9698372180"), L("306 Fountain Way", "9698372180")])
    assert len(out) == 1


def test_rows_with_no_address_at_all_still_merge_on_parcel():
    """Parcel-only rows (bankruptcy, court feeds) have no address to compare."""
    out = dedupe([L(None, "9698372180", src="x"), L(None, "9698372180", src="y")])
    assert len(out) == 1


def test_the_same_house_number_on_different_streets_is_not_forced_together():
    """The guard blocks on a DIFFERENT number; it never merges on a matching one."""
    out = dedupe([L("306 Fountain Way", "111111111"), L("306 Oak St", "222222222")])
    assert len(out) == 2


@pytest.mark.parametrize("a,b,same", [
    ("100 Main St", "100 Main St", True),
    ("100 Main St", "200 Main St", False),
    ("100 Main St", "1000 Main St", False),   # not a prefix match
    ("7 Elm", "07 Elm", False),               # '7' != '07' -- conservative, splits rather than fuses
])
def test_house_number_comparison_is_exact(a, b, same):
    out = dedupe([L(a, "5555555555"), L(b, "5555555555")])
    assert (len(out) == 1) is same
