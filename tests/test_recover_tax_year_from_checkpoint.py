"""scripts/recover_tax_year_from_checkpoint.py's identity-key matching (2026-10-02).

Root cause, confirmed live against both the real board and the retained
checkpoint (data/checkpoint/board.json.gz): `_keys()` used to try
`("u", source_url)` BEFORE `("p", parcel_id, county)`. Every row scraped from
one bulk single-document source (e.g. every counties_nc.buncombe_delinquent_tax
row carries the SAME PDF_URL) shares that "u" key, so it is the LEAST specific
identity signal available for those sources, not the most -- yet it was tried
first. Combined with `idx.setdefault(k, payload)` (first-donor-wins), this
collapsed EVERY matching board row from such a source onto ONE donor's
own tax data.

Live-confirmed blast radius: 610 of 829 Buncombe tax-delinquency board rows
carry the IDENTICAL principal_tax_due ($775.59 — the real value of exactly one
parcel, PIN 961895417300000, owner "125 PISGAH VIEW LLC") despite being 610
different real parcels, each with its own different, live-verified-correct
amount on today's advertisement. The retained checkpoint shows the same
signature: 791 duplicate copies of that one donor record under the
buncombe_delinquent_tax key, all sharing the single PDF source_url.

Fix: `_keys()` now lists parcel_id/address/case_number before source_url, and
`_build_index()` additionally refuses any key that maps to more than one
DISTINCT donor payload (an ambiguous key is dropped rather than resolved by
first-insert-wins) -- so even a coincidental non-parcel collision on some
OTHER source cannot silently mis-attribute one parcel's dollar figures onto
another's."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import recover_tax_year_from_checkpoint as R  # noqa: E402


def _rec(parcel_id=None, county=None, street_address=None, zip_code=None,
         case_number=None, source_url=None):
    return {"parcel_id": parcel_id, "county": county, "street_address": street_address,
            "zip_code": zip_code, "case_number": case_number, "source_url": source_url}


# ---- _keys() ordering -----------------------------------------------------

def test_keys_tries_parcel_before_source_url():
    rec = _rec(parcel_id="961895417300000", county="Buncombe",
               source_url="https://media.buncombenc.gov/common/tax/advert.pdf")
    keys = R._keys(rec)
    tags = [k[0] for k in keys]
    assert tags.index("p") < tags.index("u")


def test_keys_tries_address_and_case_before_source_url():
    rec = _rec(street_address="1 OAK ST", zip_code="28801", case_number="26CVD001234",
               source_url="https://media.buncombenc.gov/common/tax/advert.pdf")
    keys = R._keys(rec)
    tags = [k[0] for k in keys]
    assert tags.index("a") < tags.index("u")
    assert tags.index("c") < tags.index("u")


# ---- _build_index() ambiguity guard ---------------------------------------

def test_shared_source_url_no_longer_collapses_distinct_parcels():
    """Reproduces the real Buncombe bug: many donor rows share ONE source_url
    (one PDF) but each has its own parcel_id and its own real tax figure. The
    old first-wins index would hand every one of them the FIRST donor's
    payload via the shared url key; the fixed index must resolve each by its
    own parcel key instead, and the ambiguous url key must serve nobody."""
    url = "https://media.buncombenc.gov/common/tax/advert.pdf"
    donors = [
        ([("p", "961895417300000", "buncombe"), ("u", url)],
         {"buncombe_delinquent_tax": {"principal_tax_due": 775.59}}),
        ([("p", "973039948300000", "buncombe"), ("u", url)],
         {"buncombe_delinquent_tax": {"principal_tax_due": 46.70}}),
        ([("p", "966875394500000", "buncombe"), ("u", url)],
         {"buncombe_delinquent_tax": {"principal_tax_due": 34.23}}),
    ]
    idx = R._build_index(donors)

    # Each parcel's OWN payload is reachable by its own specific key.
    assert idx[("p", "961895417300000", "buncombe")]["buncombe_delinquent_tax"]["principal_tax_due"] == 775.59
    assert idx[("p", "973039948300000", "buncombe")]["buncombe_delinquent_tax"]["principal_tax_due"] == 46.70
    assert idx[("p", "966875394500000", "buncombe")]["buncombe_delinquent_tax"]["principal_tax_due"] == 34.23

    # The shared, ambiguous url key must not resolve to ANY one donor's payload.
    assert ("u", url) not in idx


def test_a_truly_duplicate_donor_still_resolves_via_its_shared_key():
    """Two donor rows that are genuine duplicates (same payload) sharing a key is
    NOT the bug -- that key should still resolve, since there is no ambiguity
    about which payload it means."""
    payload = {"buncombe_delinquent_tax": {"principal_tax_due": 775.59}}
    donors = [
        ([("p", "961895417300000", "buncombe")], payload),
        ([("p", "961895417300000", "buncombe")], dict(payload)),   # re-scraped, identical
    ]
    idx = R._build_index(donors)
    assert idx[("p", "961895417300000", "buncombe")]["buncombe_delinquent_tax"]["principal_tax_due"] == 775.59


def test_board_row_matching_picks_the_parcel_specific_payload_not_the_shared_one():
    """End-to-end shape of the bug: a board 'rec' (dict, same _keys() contract)
    with ONLY a parcel_id+county+source_url (no address/case) must match its OWN
    donor via the parcel key, not fall through to an ambiguous shared url key."""
    url = "https://media.buncombenc.gov/common/tax/advert.pdf"
    donors = [
        ([("p", "961895417300000", "buncombe"), ("u", url)],
         {"buncombe_delinquent_tax": {"principal_tax_due": 775.59}}),
        ([("p", "973039948300000", "buncombe"), ("u", url)],
         {"buncombe_delinquent_tax": {"principal_tax_due": 46.70}}),
    ]
    idx = R._build_index(donors)

    board_row = _rec(parcel_id="973039948300000", county="Buncombe", source_url=url)
    payload = None
    for k in R._keys(board_row):
        payload = idx.get(k)
        if payload:
            break
    assert payload is not None
    assert payload["buncombe_delinquent_tax"]["principal_tax_due"] == 46.70   # ITS OWN value
