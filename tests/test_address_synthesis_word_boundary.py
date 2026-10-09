"""enrichment_address_final.ADDR_RE takes a street suffix only as a WHOLE word.

THE BUG THIS PINS (found 2026-10-06 auditing the 2026-10-05 VM run)
    The old pattern's greedy body ran to the last "st"/"dr"/"pl" INSIDE any word, so the
    final address-synthesis pass turned notice text into street addresses:

        Column probate notice  "File No: 26E009966-120 Having qualified as Executor of the
                                Estate of ..."      -> "120 Having qualified as Executor of the Est"
        Florence tax-sale list  "2000 BELLCREST 28X60 | 2026 Tax Sale List ..." -> "2000 BELLCREST"
                                "1997 PEACH STATE 24X50" -> "1997 PEACH ST"

    Every notice of a county then carried the same "address" and house number, and dedupe()
    merged them, the 2026-10-06 identity rule included (it trusts two rows with one real house
    number and no parcels): replaying that rule on the 10/5 board's Cabarrus notices put 76
    different decedents in one row.

Notice text below is the real structure from that board, with names replaced.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.enrichment_address_final import (
    ADDR_RE, _synth_for_listing, enrich_with_address_synthesis,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

CABARRUS = ("Notice to Creditors NORTH CAROLINA, CABARRUS COUNTY File No: 26E009966-120 Having "
            "qualified as Executor of the Estate of JANE Q DOE, deceased, this is to notify all "
            "persons, firms and corporations having claims")
CABARRUS_ADMIN = ("Notice to Creditors NORTH CAROLINA, CABARRUS COUNTY File No: 25E009643-120 "
                  "Having qualified as Administrator of the Estate of JOHN R ROE, deceased, this "
                  "is to notify all persons")
JOHNSTON = ("26 E 000860-500 THE UNDERSIGNED having qualified as Executor for the estate of "
            "MARY SMITH, deceased")


@pytest.mark.parametrize("text", [
    CABARRUS, CABARRUS_ADMIN, JOHNSTON,
    "DOE JANE | 2000 BELLCREST 28X60 | 2026 Tax Sale List Mobile Homes 9-1-26.pdf",
    "ROE JOHN | 1997 PEACH STATE 24X50 | 2026 Tax Sale List Mobile Homes 9-1-26.pdf",
    "SMITH MARY | 1983 TITAN PLUS 24X52 | 2026 Tax Sale List Mobile Homes 9-1-26.pdf",
    "DOE JOHN | 1999 MASTERPIECE 16X76 | 2026 Tax Sale List Mobile Homes 9-1-26.pdf",
])
def test_a_suffix_inside_a_word_is_not_a_street(text):
    assert ADDR_RE.search(text) is None


@pytest.mark.parametrize("text,want", [
    ("Sale of the property at 4850 Dana Example Ave, Morganton", "4850 Dana Example Ave"),
    ("located at 123 N Main St. Shelby NC", "123 N Main St."),
    ("45 Oak Street Hendersonville", "45 Oak Street"),
    ("parcel at 100 Old Fort Rd near the river", "100 Old Fort Rd"),
    ("7 Court St", "7 Court St"),
    ("12 Sampleton Street", "12 Sampleton Street"),
])
def test_real_street_addresses_still_match(text, want):
    m = ADDR_RE.search(text)
    assert m is not None and m.group(1) == want


def _notice(n, county, description):
    return Listing(
        source="counties.column_legal_notices",
        source_url=f"https://us-central1-enotice-production.cloudfunctions.net/api/search/"
                   f"public-notices#notice{n}-3",
        listing_type=ListingType.PROBATE_NOTICE, property_kind=PropertyKind.UNKNOWN,
        county=county, state="NC", description=description, raw={},
    )


def test_synthesis_does_not_turn_notice_text_into_an_address():
    li = _notice(1, "Cabarrus", CABARRUS)
    synth = _synth_for_listing(li)
    assert not (synth or "").startswith("120 ")


def test_two_different_estates_stay_two_rows_through_synthesis_and_dedupe():
    other = CABARRUS.replace("26E000966", "26E000971").replace("JANE Q DOE", "RICHARD SAMPLE")
    rows = [_notice(1, "Cabarrus", CABARRUS), _notice(2, "Cabarrus", other)]
    enrich_with_address_synthesis(rows)
    assert len(dedupe(rows)) == 2
