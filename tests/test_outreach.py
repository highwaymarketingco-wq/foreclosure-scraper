"""Outreach stack — CRM / Email / SMS / Name Search.

Converts enriched leads into owner-contact actions + a postcard mail-merge,
with persistent CRM status that survives the weekly re-scrape.
"""
from __future__ import annotations

from datetime import datetime

import foreclosure_scraper.outreach as O
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(skip=None, **kw):
    base = dict(source="t", source_url="http://x", listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.SINGLE_FAMILY, state="SC", county="Spartanburg",
                street_address="128 Boiler Rd", city="Spartanburg", case_number="2024CP4200111",
                defendant="SMITH JOHN", first_seen=datetime.utcnow(), last_seen=datetime.utcnow())
    base.update(kw)
    li = Listing(**base)
    li.raw = {}
    if skip:
        li.raw["skip_trace"] = skip
    return li


def _tmp_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "CRM_PATH", tmp_path / "crm.json")
    monkeypatch.setattr(O, "MAILLIST_PATH", tmp_path / "mail.csv")


def test_first_name_handles_gis_and_court_formats():
    assert O._first_name("SMITH JOHN") == "John"      # GIS LAST FIRST
    assert O._first_name("John Smith") == "John"       # court First Last
    assert O._first_name(None) == "Property Owner"


def test_contactable_lead_gets_channels_and_messages(tmp_path, monkeypatch):
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "SMITH JOHN", "owner_mailing_address": "999 Far Rd, Charlotte NC",
                   "absentee_owner": True, "phone_numbers": ["8645551212"]})
    stats = O.generate_outreach([li])
    assert stats["contactable"] == 1 and stats["with_phone"] == 1 and stats["with_mailing"] == 1
    o = li.raw["outreach"]
    assert o["channels"] == ["sms", "mail", "email"]
    assert "John" in o["sms"] and "128 Boiler Rd" in o["sms"]
    assert li.raw["crm"]["status"] == "new"


def test_uncontactable_lead_skipped(tmp_path, monkeypatch):
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip=None, defendant=None)
    stats = O.generate_outreach([li])
    assert stats["contactable"] == 0
    assert "outreach" not in li.raw


def test_crm_status_persists_across_runs(tmp_path, monkeypatch):
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "SMITH JOHN", "phone_numbers": ["8645551212"]})
    O.generate_outreach([li])
    # Operator marks it contacted
    crm = O.load_crm()
    key = li.dedupe_key()
    crm[key]["status"] = "negotiating"
    O.save_crm(crm)
    # Re-scrape: same listing, fresh object
    li2 = _li(skip={"owner_name": "SMITH JOHN", "phone_numbers": ["8645551212"]})
    O.generate_outreach([li2])
    assert li2.raw["crm"]["status"] == "negotiating"   # survived re-scrape


def test_maillist_written_for_mailing_leads(tmp_path, monkeypatch):
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "SMITH JOHN", "owner_mailing_address": "999 Far Rd, Charlotte NC"})
    li.raw["calc"] = {"arv": 180000, "max_bid": 95000, "verdict": "GREAT"}
    O.generate_outreach([li])
    rows = (tmp_path / "mail.csv").read_text()
    assert "SMITH JOHN" in rows and "128 Boiler Rd" in rows and "GREAT" in rows


def test_name_search():
    a = _li(skip={"owner_name": "SMITH JOHN"})
    b = _li(skip={"owner_name": "DOE JANE"}, defendant="DOE JANE")
    assert len(O.find_by_owner([a, b], "smith")) == 1
    assert len(O.find_by_owner([a, b], "doe")) == 1
    assert len(O.find_by_owner([a, b], "xyz")) == 0


# ---------------------------------------------------------------------------
# 2026-10-16: skip_trace.phone_numbers is a PAID-provider-only field -- never populated in
# this free-only project (0 of 353,609 real board rows). The real, free phone pipeline
# (voter_phone, county_phone, surface_contacts, liensnc, free_phones, sc_voter_xref) lands at
# raw['owner_phone'], which _contact() never read at all -- outreach.done's with_phone stat
# has always been 0. Fixed to read it, gated on enrichment_dnc.py's own TSR-compliance verdict
# (dnc_status "clear") so a phone is only ever offered once that module has actually confirmed
# it dial-safe -- never on presence alone.
# ---------------------------------------------------------------------------

def test_owner_phone_is_surfaced_once_dnc_scrub_says_clear(tmp_path, monkeypatch):
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "SMITH JOHN", "owner_mailing_address": "999 Far Rd, Charlotte NC"})
    li.raw["owner_phone"] = {"phone": "(864) 555-1212", "source": "voter_phone"}
    li.raw["dnc_scrub"] = [{"phone": "8645551212", "dnc_status": "clear"}]
    stats = O.generate_outreach([li])
    assert stats["with_phone"] == 1
    assert li.raw["outreach"]["phones"] == ["(864) 555-1212"]
    assert li.raw["outreach"]["channels"][0] == "sms"


def test_owner_phone_is_withheld_while_unverified_or_blocked(tmp_path, monkeypatch):
    """The honest, currently-real case on the live board: no data/dnc_registry.csv is
    installed, so enrichment_dnc.py can never answer "clear" yet -- every real phone today
    is "unverified" or "blocked", and none of them must be offered for dialing."""
    _tmp_paths(tmp_path, monkeypatch)
    for status in ("unverified", "on_registry", "on_internal_dnc", "do_not_dial", "not_owner_contact"):
        li = _li(skip={"owner_name": "SMITH JOHN"})
        li.raw["owner_phone"] = {"phone": "(864) 555-1212"}
        li.raw["dnc_scrub"] = [{"phone": "8645551212", "dnc_status": status}]
        stats = O.generate_outreach([li])
        assert stats["with_phone"] == 0, status
        assert "outreach" not in li.raw or li.raw["outreach"]["phones"] == [], status


def test_owner_phone_with_no_dnc_scrub_at_all_is_withheld_fail_closed(tmp_path, monkeypatch):
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "SMITH JOHN"})
    li.raw["owner_phone"] = {"phone": "(864) 555-1212"}
    # no raw['dnc_scrub'] key at all -- never scrubbed yet
    stats = O.generate_outreach([li])
    assert stats["with_phone"] == 0


def test_skip_trace_and_owner_phone_both_contribute_when_both_are_present(tmp_path, monkeypatch):
    """skip_trace.phone_numbers is confirmed never populated on the real board today (paid-
    provider-only), so this is a belt-and-suspenders case, not a live one: if it ever were
    populated, its phones are kept alongside owner_phone's DNC-cleared ones, deduped only on
    an EXACT string match (the two sources format phones differently -- skip_trace raw digits,
    owner_phone "(xxx) xxx-xxxx" -- so the same real number from both sources currently
    appears twice, in each source's own format; not solving that here since skip_trace's half
    of it has zero real instances to lose correctness over)."""
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "SMITH JOHN", "phone_numbers": ["9195553434"]})
    li.raw["owner_phone"] = {"phone": "(864) 555-1212"}
    li.raw["dnc_scrub"] = [{"phone": "8645551212", "dnc_status": "clear"}]
    O.generate_outreach([li])
    assert li.raw["outreach"]["phones"] == ["9195553434", "(864) 555-1212"]
