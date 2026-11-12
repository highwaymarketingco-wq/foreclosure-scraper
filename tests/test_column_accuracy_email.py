"""The e-mail column means the OWNER's address (audit 2026-10-09, column_accuracy).

Fixtures are made up."""
from __future__ import annotations

from foreclosure_scraper.enrichment_email_extract import (
    emails_in_raw, normalized_owner_email_block, repair_escape_artifact)
from foreclosure_scraper.enrichment_surface_contacts import enrich_surface_contacts
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import _to_dict


def _li(raw):
    li = Listing(source="liensnc", source_url="u", listing_type=ListingType.TAX_LIEN, state="NC",
                 county="Wake")
    li.raw = raw
    return li


def test_raw_scan_reads_strings_not_a_json_dump():
    # a newline before the address: json.dumps writes '\n', the old scan read 'npat@...'
    raw = {"liensnc": {"owner_text": "BUILDER LLC\npat@builder.test\n555 Main St"}}
    assert emails_in_raw(raw) == {"pat@builder.test"}
    li = _li(dict(raw))
    enrich_surface_contacts([li])
    got = {e["email"] for e in li.raw["owner_email"]["emails"]}
    assert "npat@builder.test" not in got and "pat@builder.test" in got
    # the filing's owner block is the owner's address
    assert li.raw["owner_email"]["best_email"] == "pat@builder.test"
    assert li.raw["owner_email"]["best_classification"] == "owner"


def test_repair_only_when_the_row_proves_the_artifact():
    raw = {"x": "contact: pat@builder.test"}
    assert repair_escape_artifact("npat@builder.test", raw) == "pat@builder.test"
    # a real address that starts with n is never touched
    assert repair_escape_artifact("nora@home.test", {"x": "nora@home.test"}) == "nora@home.test"
    assert repair_escape_artifact("nora@home.test", {}) == "nora@home.test"


def test_carried_block_normalized_at_publish():
    raw = {
        "liensnc": {"owner_text": "OWNER NAME\npat@builder.test"},
        "notices": [{"claimant": "SUB CO\ncrew@contractor.test"}],
        "owner_email": {"emails": [{"email": "ncrew@contractor.test", "classification": "other"},
                                   {"email": "npat@builder.test", "classification": "other"}],
                        "best_email": "ncrew@contractor.test", "best_classification": "other"},
    }
    blk = normalized_owner_email_block(raw)
    assert blk["best_email"] == "pat@builder.test" and blk["best_classification"] == "owner"
    by = {e["email"]: e["classification"] for e in blk["emails"]}
    assert by == {"crew@contractor.test": "other", "pat@builder.test": "owner"}
    # raw is not modified
    assert raw["owner_email"]["best_email"] == "ncrew@contractor.test"
    d = _to_dict(_li(raw))
    assert d["raw"]["owner_email"]["best_email"] == "pat@builder.test"


def test_agent_only_block_publishes_no_owner_email():
    raw = {"distressed": {"agent_email": "agent@realty.test"},
           "owner_email": {"emails": [{"email": "agent@realty.test", "source_field": "distressed.agent_email",
                                       "classification": "other"}],
                           "best_email": "agent@realty.test", "best_classification": "other"}}
    blk = normalized_owner_email_block(raw)
    assert blk["best_email"] is None and blk["best_classification"] is None
    assert blk["emails"][0]["email"] == "agent@realty.test"      # kept, just not as the owner's


def test_liensnc_handoff_shape_kept():
    raw = {"owner_email": {"email": "Owner@Home.test", "source": "liensnc_filing"}}
    blk = normalized_owner_email_block(raw)
    assert blk == {"email": "owner@home.test", "source": "liensnc_filing"}


def test_sc_assessed_equal_to_market_is_withheld_at_publish():
    li = Listing(source="s", source_url="u", listing_type=ListingType.TAX_LIEN, state="SC", county="York",
                 assessed_value=150000.0, market_value=150000.0)
    assert _to_dict(li)["assessed_value"] is None
    assert li.assessed_value == 150000.0
    ok = Listing(source="s", source_url="u", listing_type=ListingType.TAX_LIEN, state="SC", county="York",
                 assessed_value=6000.0, market_value=150000.0)
    assert _to_dict(ok)["assessed_value"] == 6000.0
    nc = Listing(source="s", source_url="u", listing_type=ListingType.TAX_LIEN, state="NC", county="Wake",
                 assessed_value=150000.0, market_value=150000.0)
    assert _to_dict(nc)["assessed_value"] == 150000.0     # NC assesses at 100%
