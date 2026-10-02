"""Tests for name_normalize.classify_entity_type + enrichment_entity_type.

GAP this closes: owner entity type was computed on the fly by ~10 call sites
(all sharing name_normalize.is_entity(), confirmed no drift 2026-10-02) and
never persisted. classify_entity_type() is the richer individual/entity/
trust/estate/government/unknown classifier built on that same marker set;
enrich_entity_type() is the one place that computes it per listing and
stamps raw['entity_type'].
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.name_normalize import classify_entity_type, is_entity
from foreclosure_scraper.enrichment_entity_type import enrich_entity_type
from foreclosure_scraper.enrichment_owner_cluster import _is_entity_like
from foreclosure_scraper.models import Listing, ListingType


@pytest.mark.parametrize("name,expected", [
    (None, "unknown"),
    ("", "unknown"),
    ("   ", "unknown"),
    ("SMITH JOHN C", "individual"),
    ("Sandra L Byrd", "individual"),
    ("SAR 6 LLC", "entity"),
    ("Allied Of Spartanburg, Llc", "entity"),
    ("ACME HOLDINGS INC", "entity"),
    ("FIRST CITIZENS BANK & TRUST CO", "trust"),   # TRUST token wins over BANK
    ("SMITH JOHN REVOCABLE TRUST", "trust"),
    # TRUSTEE is a fiduciary ROLE suffix, not the TRUST marker itself (it is a
    # _NOISE token in name_normalize.py, stripped rather than matched) -- a
    # real board owner_name (seen live on a DIVORCE_NOTICE row 2026-10-02)
    # that is_entity() does not flag, so this does not either.
    ("LEATHAM CASSANDRA TRUSTEE", "individual"),
    ("SMITH JOHN ESTATE", "estate"),
    ("ESTATE OF JOHN SMITH", "estate"),
    ("SMITH JOHN HEIRS", "estate"),
    ("SMITH JOHN LIFE ESTATE", "individual"),      # a living person's interest, not a decedent's estate
    ("LINCOLN COUNTY", "government"),
    ("CITY OF SPARTANBURG", "government"),
    ("TOWN OF MOUNT PLEASANT", "government"),
    ("SPARTANBURG COUNTY SCHOOL DISTRICT", "government"),  # DISTRICT -> government, not flat 'entity'
    ("HOUSING AUTHORITY OF THE CITY OF GREER", "government"),
])
def test_classify_entity_type(name, expected):
    assert classify_entity_type(name) == expected


def test_classify_entity_type_consistent_with_is_entity_for_the_flat_cases():
    # Every name is_entity() flags True for must land in SOME non-individual
    # bucket here (never silently fall back to 'individual') -- that is the
    # one invariant linking the two functions.
    for name in ("SAR 6 LLC", "FIRST CITIZENS BANK & TRUST CO", "SMITH JOHN ESTATE",
                 "LINCOLN COUNTY", "CITY OF SPARTANBURG"):
        if is_entity(name):
            assert classify_entity_type(name) != "individual"


def _mk(owner_name, raw=None):
    return Listing(
        source="s", source_url=f"https://example.com/{owner_name}",
        listing_type=ListingType.TAX_LIEN, state="NC", county="Buncombe",
        owner_name=owner_name, raw=raw if raw is not None else {},
    )


def test_enrich_entity_type_stamps_every_listing():
    rows = [
        _mk("SMITH JOHN C"),
        _mk("SAR 6 LLC"),
        _mk("SMITH JOHN ESTATE"),
        _mk("LINCOLN COUNTY"),
        _mk(None),
    ]
    stats = enrich_entity_type(rows)
    assert [li.raw["entity_type"] for li in rows] == [
        "individual", "entity", "estate", "government", "unknown",
    ]
    assert stats["tagged_rows"] == 5
    assert stats["individual"] == 1
    assert stats["entity"] == 1
    assert stats["estate"] == 1
    assert stats["government"] == 1
    assert stats["unknown"] == 1


def test_enrich_entity_type_overwrites_a_stale_prior_value():
    li = _mk("SMITH JOHN C", raw={"entity_type": "entity"})
    enrich_entity_type([li])
    assert li.raw["entity_type"] == "individual"


def test_enrich_entity_type_does_not_clobber_other_raw_keys():
    li = _mk("SAR 6 LLC", raw={"divorce": {"case_count": 0}})
    enrich_entity_type([li])
    assert li.raw["entity_type"] == "entity"
    assert li.raw["divorce"] == {"case_count": 0}


# ---- owner_cluster's consumer: prefer the persisted field, fall back fresh -----

def test_owner_cluster_prefers_persisted_entity_type_over_recompute():
    # A listing stamped 'entity' by the new phase must be excluded from
    # clustering even though its bare name would read as a person to
    # is_entity() alone -- proves the persisted field, not a fresh
    # recompute, is what this call site now consults.
    li = _mk("SMITH JOHN C", raw={"entity_type": "entity"})
    assert _is_entity_like(li) is True


def test_owner_cluster_falls_back_to_fresh_compute_when_field_absent():
    # No raw['entity_type'] at all (e.g. a standalone dry-run that never ran
    # the new phase) -- must behave exactly as before this change.
    assert _is_entity_like(_mk("SMITH JOHN C")) is False
    assert _is_entity_like(_mk("SAR 6 LLC")) is True
