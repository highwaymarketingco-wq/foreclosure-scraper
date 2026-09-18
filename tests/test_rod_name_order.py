"""Title Case FIRST-LAST owners must be searched in the right order.

sc_public_index and sc_probate_notices.* store 'Joshua D Smith'; county GIS
stores 'BYRD SANDRA D'. Four ROD enrichers and both divorce enrichers parsed
surname-first only, searching last=JOSHUA, first=D for the former. Found
2026-09-18 while fixing the SC divorce enricher.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper import (
    enrichment_aumentum_rod as aum,
    enrichment_cchs_rod as cchs,
    enrichment_generic_rod as gen,
    enrichment_nc_divorce as ncd,
    enrichment_sc_divorce as scd,
    enrichment_spartanburg_rod as spt,
)
from foreclosure_scraper.enrichment_derivation_flags import _free_and_clear
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.name_normalize import first_last_parts

_PARSERS = [aum._name_parts, cchs._name_parts, gen._name_parts, spt._name_parts,
            ncd._name_parts, scd._name_parts]


@pytest.mark.parametrize("owner,expected", [
    ("Joshua D Smith", ("SMITH", "JOSHUA")),
    ("Krystal  Henderson", ("HENDERSON", "KRYSTAL")),
    ("Rex Allen Chappell Jr", ("CHAPPELL", "REX")),
    ("Tina Lopez & John Lopez", ("LOPEZ", "TINA")),
])
def test_helper_and_every_parser_read_title_case_first_last(owner, expected):
    assert first_last_parts(owner) == expected
    for parse in _PARSERS:
        assert parse(owner) == expected, parse.__module__


@pytest.mark.parametrize("owner,expected", [
    ("BYRD SANDRA D", ("BYRD", "SANDRA")),                 # GIS surname-first, unchanged
    ("SMITH JOHN C & MELINDA P", ("SMITH", "JOHN")),
    ("Roper, John A., Jr.", ("ROPER", "JOHN")),            # comma always means LAST, FIRST
])
def test_gis_and_comma_formats_are_unchanged(owner, expected):
    assert first_last_parts(owner) is None
    for parse in _PARSERS:
        assert parse(owner) == expected, parse.__module__


def test_helper_declines_degenerate_input():
    assert first_last_parts(None) is None
    assert first_last_parts("") is None
    assert first_last_parts("Madonna") is None             # one token: caller's own parse


def _rod(source, fetched_at, mortgage=False):
    return {"instrument_count": 2, "has_mortgage": mortgage, "open_mortgages_est": 0,
            "source": source, "fetched_at": fetched_at}


def _lead(owner, rod):
    return Listing(source="x", source_url="u", listing_type=ListingType.TAX_LIEN,
                   state="SC", county="Spartanburg", owner_name=owner, raw={"rod": rod})


def test_old_rod_stamp_on_a_title_case_owner_does_not_claim_free_and_clear():
    li = _lead("Joshua D Smith", _rod("spartanburg_rod_render", "2026-08-01T18:19:23+00:00"))
    assert _free_and_clear(li) is None


def test_same_owner_stamped_after_the_fix_is_trusted_again():
    li = _lead("Joshua D Smith", _rod("spartanburg_rod_render", "2026-09-19T01:00:00+00:00"))
    assert _free_and_clear(li)["flag"] is True


def test_gis_order_owner_with_an_old_stamp_is_untouched():
    li = _lead("BYRD SANDRA D", _rod("cchs_rod", "2026-08-01T18:19:23+00:00"))
    assert _free_and_clear(li)["flag"] is True


def test_source_that_never_had_the_bug_is_untouched():
    li = _lead("Joshua D Smith", _rod("gaston_rod", "2026-08-01T18:19:23+00:00"))
    assert _free_and_clear(li)["flag"] is True
