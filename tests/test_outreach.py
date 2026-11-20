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
# 2026-11-19: a verification pass live-checked 20 of the 3,264 contactable rows where the
# board's top-level owner_name (identity.py-validated against the county's CURRENT record of
# THIS parcel) disagreed with raw['skip_trace']['owner_name'] (written once by
# enrichment_skip_trace.py with no such binding check, and never re-run afterward). Of the 18
# reached live: owner_name was correct 11/18 (61%), skip_trace 4/18 (22%, concentrated in
# builder-new-construction and heir/estate parcels -- too small a slice, and with no reliable
# flag to key off at this call site, to carve out as its own rule), neither 3/18. _owner() used
# to read skip_trace.owner_name FIRST and never consult li.owner_name at all, so every
# letter/SMS/email used the less-reliable, unvalidated name whenever the two disagreed. Fixed
# to prefer li.owner_name, falling back to skip_trace then defendant.
# ---------------------------------------------------------------------------

def test_owner_prefers_board_owner_name_over_stale_skip_trace():
    li = _li(skip={"owner_name": "WRONG STALE SKIPTRACE NAME"}, owner_name="RIGHT BOARD NAME")
    assert O._owner(li) == "RIGHT BOARD NAME"


def test_owner_falls_back_to_skip_trace_when_board_owner_name_missing():
    li = _li(skip={"owner_name": "SKIP TRACE NAME"}, owner_name=None)
    assert O._owner(li) == "SKIP TRACE NAME"


def test_owner_falls_back_to_defendant_when_owner_name_and_skip_trace_both_missing():
    li = _li(skip=None, owner_name=None, defendant="COURT DEFENDANT")
    assert O._owner(li) == "COURT DEFENDANT"


def test_owner_returns_none_when_nothing_available():
    li = _li(skip=None, owner_name=None, defendant=None)
    assert O._owner(li) is None


def test_generate_outreach_uses_board_owner_name_not_stale_skip_trace_end_to_end(tmp_path, monkeypatch):
    """Same fix, exercised through the real pipeline: the letter/SMS/email text and the
    raw['outreach']['owner'] field actually sent to the operator must reflect li.owner_name,
    not a disagreeing nested skip_trace copy."""
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "WRONG STALE NAME", "owner_mailing_address": "999 Far Rd, Charlotte NC"},
             owner_name="RIGHT BOARD NAME")
    O.generate_outreach([li])
    o = li.raw["outreach"]
    assert o["owner"] == "RIGHT BOARD NAME"
    assert "WRONG" not in o["letter"]
    assert "WRONG" not in o["sms"]
    assert "WRONG" not in o["email"]


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


# ---------------------------------------------------------------------------
# 2026-11-19 verification follow-up: PARTY-ROLE CONFUSION safety net. A verification sample
# found 3/18 rows where NEITHER li.owner_name NOR skip_trace.owner_name was the real owner -- a
# lienholder, government body, or (one real example) a literal job title ("Procurement
# Manager") read off a liensnc filing. _owner() now skips any candidate
# identity.suspicious_owner_name() flags, falling through to the next one (or the generic
# "Property Owner" default) instead of guessing.
# ---------------------------------------------------------------------------

def test_owner_skips_a_government_entity_and_falls_back_to_defendant():
    li = _li(skip=None, owner_name="CLEVELAND COUNTY", defendant="REAL HOMEOWNER")
    assert O._owner(li) == "REAL HOMEOWNER"


def test_owner_skips_a_job_title_from_skip_trace_and_falls_back_to_defendant():
    li = _li(skip={"owner_name": "Procurement Manager"}, owner_name=None,
              defendant="REAL HOMEOWNER")
    assert O._owner(li) == "REAL HOMEOWNER"


def test_owner_returns_none_when_every_candidate_is_suspicious():
    li = _li(skip={"owner_name": "Procurement Manager"}, owner_name="CLEVELAND COUNTY",
              defendant="CITY OF ROCK HILL")
    assert O._owner(li) is None


def test_owner_skips_an_entity_name_sourced_from_a_lien_filing():
    li = _li(skip=None, owner_name="ACME HOLDINGS LLC", defendant="REAL HOMEOWNER")
    li.raw["owner_mailing"] = {"owner": "ACME HOLDINGS LLC", "source": "liensnc_filing"}
    assert O._owner(li) == "REAL HOMEOWNER"


def test_owner_does_not_skip_an_entity_name_sourced_from_the_county_roll():
    # same entity-shaped name, but sourced from an actual tax roll -- an ordinary LLC owner
    li = _li(skip=None, owner_name="ACME HOLDINGS LLC", defendant="SOMEONE ELSE")
    li.raw["owner_mailing"] = {"owner": "ACME HOLDINGS LLC", "source": "county_gis"}
    assert O._owner(li) == "ACME HOLDINGS LLC"


# ---------------------------------------------------------------------------
# 2026-11-20 follow-up: the residual 22% gap f5eeab0d/f8aa709c scoped out by name (li.owner_name
# itself stale after a real sale -- a builder/developer entity or old grantor). A deed proven to
# this row's own parcel (identity.rod_chain_conveyance_owner()) now outranks even li.owner_name.
# ---------------------------------------------------------------------------

def test_owner_prefers_a_confirmed_rod_chain_conveyance_over_the_stale_board_owner_name():
    # the real JAG Development Company example: li.owner_name is a bulk-tract developer who
    # already conveyed THIS exact parcel away, proven by the row's own parcel id turning up
    # inside the conveyance's recorded description.
    li = _li(skip=None, owner_name="JAG DEVELOPMENT COMPANY", defendant="SOMEONE ELSE",
              parcel_id="546830142700")
    li.raw["rod_chain"] = {"status": "ok", "conveyed_out_since": [
        {"recorded": "2026-01-14", "book": "446", "page": "555",
         "description": "Parcel: 5468-30-1427-00 LOT 17 POLLOCKSVILLE TOWNSHIP",
         "grantors": ["JAG DEVELOPMENT COMPANY"], "grantees": ["COLONY CUSTOM BUILDERS LLC"]}]}
    assert O._owner(li) == "COLONY CUSTOM BUILDERS LLC"


def test_owner_falls_back_to_board_owner_name_when_the_conveyance_cannot_be_confirmed():
    # the real Byers Construction & Development LLC example: a conveyed_out_since deed exists,
    # but neither tie (book/page, embedded parcel id) ties it to THIS parcel -- li.owner_name
    # must be kept, not swapped for a namesake's or a different lot's buyer.
    li = _li(skip={"owner_name": "Brenten Byers"}, owner_name="BYERS CONSTRUCTION & DEVELOPMENT LLC",
              parcel_id="7640464099")
    li.raw["rod_chain"] = {"status": "ok", "conveyed_out_since": [
        {"recorded": "2024-06-04", "book": "2378", "page": "1236", "description": "WEBSTER 3.21 AC",
         "grantors": ["BYERS CONSTRUCTION & DEVELOPMENT, LLC"],
         "grantees": ["ELLIS, RANDALL S.", "ELLIS, TERRI S."]}]}
    li.raw["county_deed_ref"] = {"book": "2335", "page": "638"}
    assert O._owner(li) == "BYERS CONSTRUCTION & DEVELOPMENT LLC"


def test_generate_outreach_uses_a_confirmed_rod_chain_conveyance_end_to_end(tmp_path, monkeypatch):
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "WRONG STALE SKIPTRACE NAME",
                   "owner_mailing_address": "999 Far Rd, Charlotte NC"},
              owner_name="JAG DEVELOPMENT COMPANY", parcel_id="546830142700")
    li.raw["rod_chain"] = {"status": "ok", "conveyed_out_since": [
        {"recorded": "2026-01-14", "book": "446", "page": "555",
         "description": "Parcel: 5468-30-1427-00 LOT 17 POLLOCKSVILLE TOWNSHIP",
         "grantors": ["JAG DEVELOPMENT COMPANY"], "grantees": ["COLONY CUSTOM BUILDERS LLC"]}]}
    O.generate_outreach([li])
    o = li.raw["outreach"]
    assert o["owner"] == "COLONY CUSTOM BUILDERS LLC"
    assert "JAG" not in o["letter"]


def test_owner_identity_uncertain_flag_is_stamped_on_raw_end_to_end(tmp_path, monkeypatch):
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "Procurement Manager",
                   "owner_mailing_address": "999 Far Rd, Charlotte NC"},
              owner_name=None, defendant="REAL HOMEOWNER")
    O.generate_outreach([li])
    assert li.raw["owner_identity_uncertain"] is True
    # but the row is still contactable and still uses the safe fallback name
    assert li.raw["outreach"]["owner"] == "REAL HOMEOWNER"


def test_owner_identity_uncertain_flag_absent_for_an_ordinary_lead(tmp_path, monkeypatch):
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "SMITH JOHN",
                   "owner_mailing_address": "999 Far Rd, Charlotte NC"})
    O.generate_outreach([li])
    assert "owner_identity_uncertain" not in li.raw


def test_generate_outreach_excludes_a_lead_whose_every_owner_candidate_is_suspicious(tmp_path, monkeypatch):
    """A row with NO safe name anywhere must not be auto-generated outreach at all -- the
    existing contactable gate already enforces this once _owner() returns None."""
    _tmp_paths(tmp_path, monkeypatch)
    li = _li(skip={"owner_name": "Procurement Manager",
                   "owner_mailing_address": "999 Far Rd, Charlotte NC"},
              owner_name="CLEVELAND COUNTY", defendant="CITY OF ROCK HILL")
    stats = O.generate_outreach([li])
    assert stats["contactable"] == 0
    assert "outreach" not in li.raw
    assert li.raw["owner_identity_uncertain"] is True  # still flagged for audit, even though excluded
