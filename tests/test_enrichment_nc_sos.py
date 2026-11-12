"""Regression tests for enrichment_nc_sos.py's _is_business().

Byte-for-byte duplicate of the bug fixed in enrichment_sos_dissolution.py
(commit 0ae2a7ab, 2026-10-03): despite a comment claiming this module "reuses"
the business-entity detection proven there, it had actually duplicated a bare,
unanchored substring scan instead of delegating to it. "inc" and "lp" as raw
substrings match plenty of real surnames/given names -- "Vincent", "Lincoln",
"Prince", "Alphonso", "Randolph", "Delphine" all contain one -- so ordinary
people were misrouted into NC SOS entity lookups. Fixed by delegating to
name_normalize.is_entity(), the word-boundary-safe token check this codebase
already uses for exactly this question (see test_sos_dissolution.py's sibling
test, test_is_business_no_substring_false_positives, for the original find).
"""
from foreclosure_scraper import enrichment_nc_sos as nc_sos


def test_is_business_no_substring_false_positives():
    not_businesses = [
        "Vincent, James", "John Vincent", "Lincoln, Mary", "Mary Lincoln",
        "St Vincent de Paul", "Randolph, Carter", "Alphonso Gaines",
        "Delphine Walton", "Prince, Keisha", "Anderson Myron Vincent",
    ]
    for name in not_businesses:
        assert nc_sos._is_business(name) is False, f"{name!r} is a person, not a business"

    real_businesses = [
        "Smith LLC", "Jones Inc", "Principal Investments LLC", "Marcos Inc",
        "Smith Corp", "ABC Co", "Acme Holdings LLC",
    ]
    for name in real_businesses:
        assert nc_sos._is_business(name) is True, f"{name!r} should still read as a business"


def test_entity_of_skips_false_positive_person_names():
    """The real call site this bug fed: _entity_of() used to route plain
    people named Vincent/Lincoln/etc. into an NC SOS entity lookup because
    _is_business() misclassified them. It must no longer do that."""
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Gaston", owner_name="Vincent, James",
                 defendant="James Vincent")
    assert nc_sos._entity_of(li) is None


def test_entity_of_still_finds_real_business():
    from foreclosure_scraper.models import Listing, ListingType

    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Gaston", owner_name=None,
                 defendant="Acme Holdings LLC")
    assert nc_sos._entity_of(li) == "Acme Holdings LLC"
