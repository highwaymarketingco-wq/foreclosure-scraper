"""SOS registered-agent enrichment — entity cleaning + profile parsing.

The parser runs against the real NC SOS profile innerText shape (non-breaking
spaces, "Company officials" for LLCs, 2-line officer addresses). The cleaner
must survive litigation captions and drop personal trusts (not in the registry).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_sos_agent as sa
from foreclosure_scraper.models import Listing, ListingType


# real NC LLC profile innerText (nbsp-laden, "Company officials" section)
_LLC_TEXT = (
    "Legal name:  LMTDBHG, LLC\n"
    "Secretary of State Identification Number (SOSID):  1354295\n"
    "Status:  Current-Active\n"
    "Citizenship:  Domestic\n"
    "Date formed:  1/1/2014\n"
    "Registered agent:   Jeremy Champion\n\n"
    "Mailing address\n1804 Kings Road\nShelby, NC 28150-6128\n"
    "Principal Office address\n1804 Kings Road\nShelby, NC 28150-6128\n"
    "Registered Office address\n1804 Kings Road\nShelby, NC 28150-6128\n\n"
    "Company officials\n\n"
    "All LLCs are managed by their managers pursuant to N.C.G.S. 57D-3-20.\n\n"
    "General Manager  \nJeremy  Champion \nP.O. Box 3076\nShelby NC 28151\n\n"
    "Return to top\n"
)


def test_parse_llc_profile_extracts_owner_contact():
    p = sa._parse_profile(_LLC_TEXT)
    assert p["sosid"] == "1354295"
    assert p["status"] == "Current-Active"
    assert p["registered_agent"] == "Jeremy Champion"
    assert p["agent_is_service"] is False
    assert p["principal_office_address"] == "1804 Kings Road, Shelby, NC 28150-6128"
    assert p["officers"][0] == {
        "title": "General Manager", "name": "Jeremy Champion",
        "address": "P.O. Box 3076 Shelby NC 28151",
    }
    # an officer (real human) is the best outreach contact
    assert p["best_contact_name"] == "Jeremy Champion"
    assert "P.O. Box 3076" in p["best_contact_address"]


def test_agent_service_flagged_and_officer_preferred():
    text = (
        "Status:  Admin. Dissolved\n"
        "Registered agent:   Registered Agents Inc\n"
        "Principal Office address\n322 Balmy Lane\nRutherfordton, NC 28139\n"
        "Company officials\n\n"
        "Member\nCharles M Dillon\n3345 Bixler Road\nDiscovery Bay CA 94505\n\n"
        "Return to top\n"
    )
    # needs a sosid to be considered resolved elsewhere, but parsing is standalone
    p = sa._parse_profile("Secretary of State Identification Number (SOSID):  9\n" + text)
    assert p["agent_is_service"] is True
    # a commercial agent is skipped in favor of the named member (absentee CA owner)
    assert p["best_contact_name"] == "Charles M Dillon"
    assert "Discovery Bay" in p["best_contact_address"]


def test_clean_entity_handles_captions_and_trusts():
    assert sa._clean_entity("SERVICEMAC LLC") == "SERVICEMAC LLC"
    assert sa._clean_entity("Schadel v. 360 Equipment Finance LLC") == "360 Equipment Finance LLC"
    assert sa._clean_entity("Resident Research, LLC v. Fortifi, LLC") == "Fortifi, LLC"
    assert sa._clean_entity("142 JOSIAH LANE REVOCABLE TRUST;COLE, GARY TRUSTEE") is None
    assert sa._clean_entity("SEEN LILY LOO LIVING TRUST") is None
    assert sa._clean_entity("John Q. Homeowner") is None


def test_non_nc_and_non_entity_skipped(monkeypatch):
    calls = {"n": 0}

    async def fake_batch(names):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(sa, "_ENABLED", True)
    monkeypatch.setattr(sa, "_batch_lookup", fake_batch)
    listings = [
        Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                state="SC", county="Spartanburg", owner_name="Palmetto Holdings LLC"),
        Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                state="NC", county="Gaston", owner_name="Jane Q. Person"),
    ]
    out = asyncio.run(sa.enrich_with_sos_agent(listings))
    # SC entity (captcha-walled) + NC individual both excluded -> no targets, no lookup
    assert out["targets"] == 0
    assert calls["n"] == 0


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr(sa, "_ENABLED", False)
    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Gaston", owner_name="Acme Holdings LLC")
    out = asyncio.run(sa.enrich_with_sos_agent([li]))
    assert out == {"targets": 0, "resolved": 0, "with_contact": 0, "misses": 0}
