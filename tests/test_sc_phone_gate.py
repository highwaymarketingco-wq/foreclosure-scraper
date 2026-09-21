"""SC phone identity gate (src/foreclosure_scraper/enrichment_sc_phone.py). Offline.

Every Listing is hand built and every voter record is either added directly to a
VoterIdentityIndex or written to a tiny synthetic ncvoter file in tmp_path. Nothing touches
data/ncvoter, the network, or the board.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

import foreclosure_scraper.enrichment_dnc as dnc_mod
import foreclosure_scraper.enrichment_sc_phone as G
import foreclosure_scraper.enrichment_sc_voter_xref as X
from foreclosure_scraper.campaign_export import _apply_filters, _export_sms
from foreclosure_scraper.models import Listing
from foreclosure_scraper.workflow_engine import _check_trigger

PHONE = "9195551234"
FMT = "(919) 555-1234"


def _listing(state="SC", county="Spartanburg", owner="SMITH JOHN A", raw=None, **kw) -> Listing:
    return Listing(source=kw.pop("source", "test"), source_url="https://example.com/x", state=state,
                   county=county, owner_name=owner, street_address=kw.pop("street", "10 Elm St"),
                   raw=raw if raw is not None else {}, **kw)


def _xref(match="nc_xref:SMITH,JOHN", phone=FMT, **extra) -> dict:
    return {"phone": phone, "source": "ncsbe_voter_xref", "line_type": "unknown",
            "needs_dnc_scrub": True, "match": match, **extra}


def _mailing(text, state) -> dict:
    return {"mailing": text, "mail_state": state, "absentee": True}


def _rec(last="SMITH", first="JOHN", middle="ANDREW", county="WAKE", res="1124 TYLER FARMS DR",
         phone=PHONE) -> G.VoterRec:
    return G.VoterRec(last=last, first=first, middle=middle, county=county,
                      street_key=G._street_key(res), phone=phone)


def _index(*recs: G.VoterRec, tmp: Path | None = None) -> G.VoterIdentityIndex:
    """An index that never reads the real voter files: an empty dir, records added by hand."""
    idx = G.VoterIdentityIndex(voter_dir=tmp if tmp is not None else "/nonexistent-voter-dir")
    for r in recs:
        idx.add(r)
    return idx


# --------------------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------------------
def test_contradicted_when_voter_name_is_not_in_the_current_owner():
    """The row's owner_name was promoted to someone else after the phone was stamped."""
    li = _listing(owner="BRANSON BRADY D", raw={"owner_phone": _xref("nc_xref:BOYD,JOHN")})
    res = G.xref_identity_check(li, index=_index())
    assert res["verdict"] == G.CONTRADICTED
    assert res["reason"] == "voter_name_not_in_owner"
    assert G.xref_identity_verdict(li, index=_index()) == "contradicted"


def test_contradicted_needs_both_first_and_last():
    li = _listing(owner="SMITH MARY", raw={"owner_phone": _xref("nc_xref:SMITH,JOHN")})
    assert G.xref_identity_verdict(li, index=_index()) == G.CONTRADICTED


@pytest.mark.parametrize("owner", [
    "SAR 6 LLC",
    "C.L.C. PROPERTIES, INC.",
    "VFW POST 5555",
    "SMITH JOHN A TRUST",
    "FIRST BAPTIST CHURCH",
    "SMITH JOHN ESTATE",
    "ESTATE OF SMITH JOHN A",
    "SMITH JOHN ET AL HEIRS",
    "TOWN OF WESTMINSTER",
])
def test_contradicted_when_the_owner_is_an_entity_or_estate(owner):
    """A person's phone on an LLC, a VFW post or an estate, even when the voter's name is in the string."""
    li = _listing(owner=owner, raw={"owner_phone": _xref("nc_xref:SMITH,JOHN")})
    res = G.xref_identity_check(li, index=_index(_rec()))
    assert res["verdict"] == G.CONTRADICTED
    assert res["reason"] in ("entity_or_estate_owner", "owner_name_missing")


@pytest.mark.parametrize("owner", ["POST WILLIAM D", "SMITH JOHN A LIFE ESTATE", "SMITH JOHN A"])
def test_a_person_is_not_an_entity(owner):
    """POST is a surname; LIFE ESTATE is an interest a living person holds."""
    assert G.owner_is_non_person(owner) is False


def test_entity_detection_reuses_name_normalize():
    from foreclosure_scraper.name_normalize import is_entity
    for name in ("SAR 6 LLC", "ACME HOLDINGS", "JONES PARTNERS LP", "SMITH FAMILY TRUST"):
        assert is_entity(name) and G.owner_is_non_person(name)


def test_corroborated_when_owner_mails_to_the_voters_nc_street():
    li = _listing(owner="SMITH JOHN A", raw={
        "owner_phone": _xref(),
        "owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")})
    res = G.xref_identity_check(li, index=_index(_rec()))
    assert res["verdict"] == G.CORROBORATED
    assert res["reason"] == "nc_mailing_street_matches_voter"


def test_corroborated_by_address_reads_state_off_the_mailing_string_when_mail_state_is_missing():
    li = _listing(owner="SMITH JOHN A", raw={
        "owner_phone": _xref(),
        "owner_mailing": {"mailing": "1124 TYLER FARMS DR, RALEIGH NC, 27612"}})
    assert G.xref_identity_verdict(li, index=_index(_rec())) == G.CORROBORATED


@pytest.mark.parametrize("mailing,state,voter,why", [
    ("1124 TYLER FARMS DR SPARTANBURG SC 29301", "SC", _rec(), "an SC mailing address is not NC residency"),
    ("55 OTHER ROAD RALEIGH NC 27612", "NC", _rec(), "NC mailing address, different street"),
    ("PO BOX 12 RALEIGH NC 27612", "NC", _rec(), "a PO box has no street key"),
    ("1124 TYLER FARMS DR RALEIGH NC 27612", "NC", _rec(phone="9195559999"),
     "the voter at that street carries a different phone than the one stored"),
])
def test_address_path_does_not_corroborate_without_the_same_nc_street(mailing, state, voter, why):
    li = _listing(owner="SMITH JOHN A", raw={"owner_phone": _xref(), "owner_mailing": _mailing(mailing, state)})
    assert G.xref_identity_verdict(li, index=_index(voter)) == G.UNVERIFIED, why


def test_same_street_but_a_different_middle_initial_is_not_corroboration():
    """John B Smith mails to the house where John A Smith votes: a father and son, not one person."""
    li = _listing(owner="SMITH JOHN B", raw={
        "owner_phone": _xref(), "owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")})
    res = G.xref_identity_check(li, index=_index(_rec(middle="ANDREW")))
    assert (res["verdict"], res["reason"]) == (G.UNVERIFIED, "middle_initial_conflict")
    # the same initial, or no initial on the owner, still corroborates on the street
    for owner in ("SMITH JOHN A", "SMITH JOHN"):
        li = _listing(owner=owner, raw={
            "owner_phone": _xref(), "owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")})
        assert G.xref_identity_verdict(li, index=_index(_rec(middle="ANDREW"))) == G.CORROBORATED


def test_corroborated_by_name_middle_initial_and_county_for_an_nc_lead():
    li = _listing(state="NC", county="Wake", owner="SMITH JOHN A",
                  raw={"owner_phone": _xref()})
    res = G.xref_identity_check(li, index=_index(_rec(middle="ANDREW", county="WAKE")))
    assert res["verdict"] == G.CORROBORATED
    assert res["reason"] == "name_middle_county_agree"


def test_middle_initial_conflict_wrong_county_or_no_middle_is_only_unverified():
    base = dict(state="NC", county="Wake", raw={"owner_phone": _xref()})
    # a different middle initial: a different John Smith
    assert G.xref_identity_verdict(_listing(owner="SMITH JOHN B", **copy.deepcopy(base)),
                                   index=_index(_rec(middle="ANDREW"))) == G.UNVERIFIED
    # right person, wrong county
    assert G.xref_identity_verdict(_listing(owner="SMITH JOHN A", **copy.deepcopy(base)),
                                   index=_index(_rec(county="DURHAM"))) == G.UNVERIFIED
    # the owner carries no middle initial: nothing says it is right
    assert G.xref_identity_verdict(_listing(owner="SMITH JOHN", **copy.deepcopy(base)),
                                   index=_index(_rec())) == G.UNVERIFIED
    # the voter carries no middle name
    assert G.xref_identity_verdict(_listing(owner="SMITH JOHN A", **copy.deepcopy(base)),
                                   index=_index(_rec(middle=""))) == G.UNVERIFIED


def test_same_county_name_across_the_state_line_is_not_corroboration():
    """Union, Cherokee and Lee exist in both states. An SC lead never shares a county with an NC voter."""
    li = _listing(state="SC", county="Union", owner="SMITH JOHN A", raw={"owner_phone": _xref()})
    assert G.xref_identity_verdict(li, index=_index(_rec(county="UNION"))) == G.UNVERIFIED


def test_unverified_when_the_name_matches_but_nothing_else_does():
    li = _listing(owner="SMITH JOHN A", raw={
        "owner_phone": _xref(), "owner_mailing": _mailing("22 MAIN ST SPARTANBURG SC 29301", "SC")})
    res = G.xref_identity_check(li, index=_index(_rec()))
    assert res["verdict"] == G.UNVERIFIED and res["reason"] == "no_corroboration"


def test_unverified_when_there_is_no_match_key_or_no_voter_record():
    li = _listing(raw={"owner_phone": _xref(match="")})
    assert G.xref_identity_check(li, index=_index())["reason"] == "no_match_key"
    li = _listing(raw={"owner_phone": _xref()})
    assert G.xref_identity_check(li, index=_index())["reason"] == "voter_record_not_found"


def test_a_row_with_no_xref_phone_is_unverified_not_an_error():
    assert G.xref_identity_verdict(_listing(raw={}), index=_index()) == G.UNVERIFIED
    assert G.xref_identity_verdict(_listing(raw={"owner_phone": {"phone": FMT, "source": "liensnc_filing"}}),
                                   index=_index()) == G.UNVERIFIED


# --------------------------------------------------------------------------------------
# apply, report-only default, idempotence
# --------------------------------------------------------------------------------------
def _board() -> list[Listing]:
    return [
        # contradicted
        _listing(owner="BRANSON BRADY D", county="Spartanburg", raw={"owner_phone": _xref("nc_xref:BOYD,JOHN")}),
        # unverified
        _listing(owner="SMITH JOHN A", county="Pickens", raw={
            "owner_phone": _xref(), "owner_mailing": _mailing("22 MAIN ST GREER SC 29650", "SC")}),
        # corroborated
        _listing(owner="SMITH JOHN A", county="Oconee", raw={
            "owner_phone": _xref(), "owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")}),
        # not an xref phone: never touched by the verdict
        _listing(owner="ROE RICHARD", raw={"owner_phone": {"phone": FMT, "source": "liensnc_filing"}}),
    ]


def test_default_is_report_only_and_mutates_nothing():
    board = _board()
    before = copy.deepcopy([li.raw for li in board])
    stats = G.flag_unverified_xref_phones(board, index=_index(_rec(), _rec(last="BOYD", first="JOHN")))
    assert [li.raw for li in board] == before
    assert stats["applied"] is False
    assert (stats["xref_phones"], stats["corroborated"], stats["unverified"], stats["contradicted"]) == (3, 1, 1, 1)
    assert stats["do_not_dial"] == 2
    assert stats["changed"] == 3                       # what an apply WOULD stamp: identity_check on all three
    assert stats["by_county"]["Pickens"] == {"unverified": 1}


def test_apply_stamps_the_verdict_and_do_not_dial_and_keeps_the_phone():
    board = _board()
    stats = G.flag_unverified_xref_phones(board, apply=True, index=_index(_rec(), _rec(last="BOYD", first="JOHN")))
    contradicted, unverified, corroborated, other = (li.raw["owner_phone"] for li in board)
    assert contradicted["identity_check"] == "contradicted" and contradicted["do_not_dial"] is True
    assert unverified["identity_check"] == "unverified" and unverified["do_not_dial"] is True
    assert corroborated["identity_check"] == "corroborated" and "do_not_dial" not in corroborated
    for op in (contradicted, unverified, corroborated):
        assert op["phone"] == FMT                     # nothing is lost
    assert "identity_check" not in other and "do_not_dial" not in other
    assert stats["applied"] is True and stats["changed"] == 3


def test_apply_is_idempotent():
    board = _board()
    idx = _index(_rec(), _rec(last="BOYD", first="JOHN"))
    G.flag_unverified_xref_phones(board, apply=True, index=idx)
    once = copy.deepcopy([li.raw for li in board])
    again = G.flag_unverified_xref_phones(board, apply=True, index=idx)
    assert [li.raw for li in board] == once
    assert again["changed"] == 0
    assert (again["corroborated"], again["unverified"], again["contradicted"]) == (1, 1, 1)


def test_a_later_corroboration_clears_the_gates_own_flag_but_never_a_foreign_one():
    li = _listing(owner="SMITH JOHN A", raw={"owner_phone": _xref()})
    idx = _index(_rec())
    G.flag_unverified_xref_phones([li], apply=True, index=idx)
    assert li.raw["owner_phone"]["do_not_dial"] is True and li.raw["owner_phone"]["identity_check"] == "unverified"
    # the assessor mailing address arrives later, in NC, on the voter's street
    li.raw["owner_mailing"] = _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")
    G.flag_unverified_xref_phones([li], apply=True, index=idx)
    op = li.raw["owner_phone"]
    assert op["identity_check"] == "corroborated" and "do_not_dial" not in op and "do_not_dial_reason" not in op

    other = _listing(owner="SMITH JOHN A", raw={
        "owner_phone": _xref(do_not_dial=True, do_not_dial_reason="operator_hold"),
        "owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")})
    G.flag_unverified_xref_phones([other], apply=True, index=idx)
    assert other.raw["owner_phone"]["do_not_dial"] is True                # somebody else's flag stays
    assert other.raw["owner_phone"]["do_not_dial_reason"] == "operator_hold"


def test_a_stale_corroboration_is_revoked_when_the_owner_changes():
    li = _listing(owner="SMITH JOHN A", raw={
        "owner_phone": _xref(), "owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")})
    idx = _index(_rec())
    G.flag_unverified_xref_phones([li], apply=True, index=idx)
    assert li.raw["owner_phone"]["identity_check"] == "corroborated"
    li.owner_name = "TRIPP BONNIE"                                         # assessor owner promoted after the stamp
    G.flag_unverified_xref_phones([li], apply=True, index=idx)
    assert li.raw["owner_phone"]["identity_check"] == "contradicted"
    assert li.raw["owner_phone"]["do_not_dial"] is True


def test_sc_voter_xref_block_follows_the_same_gate():
    li = _listing(owner="BRANSON BRADY D", raw={"sc_voter_xref": {
        "phone": FMT, "source": "ncsbe_voter_xref", "match": "nc_xref:BOYD,JOHN", "needs_dnc_scrub": True}})
    stats = G.flag_unverified_xref_phones([li], apply=True, index=_index())
    assert stats["xref_phones"] == 1
    assert li.raw["sc_voter_xref"]["do_not_dial"] is True


# --------------------------------------------------------------------------------------
# lane rules
# --------------------------------------------------------------------------------------
def test_people_search_is_walled_agents_are_tagged_and_liensnc_is_kept():
    ps = _listing(raw={"owner_phone": {"phone": FMT, "source": "free_people_search", "match": "name+location"},
                       "free_phones": [{"phone": "(704) 555-0101", "source": "truepeoplesearch"}]})
    agent = _listing(raw={"owner_phone": {"phone": FMT, "source": "homeharvest_agent", "match": "Mobile"}})
    atty = _listing(raw={"owner_phone": {"phone": FMT, "source": "notice_contact_attorney", "match": "attorney"}})
    ocr = _listing(raw={"owner_phone": {"phone": FMT, "source": "ocr_legal_notice", "match": "attorney_in_notice"}})
    own = _listing(raw={"owner_phone": {"phone": FMT, "source": "liensnc_filing",
                                        "match": "self_filed_lien_agent_appointment"}})
    board = [ps, agent, atty, ocr, own]
    dry = G.flag_lane_phones(board)
    assert dry["applied"] is False and all("do_not_dial" not in li.raw["owner_phone"] for li in board)
    stats = G.flag_lane_phones(board, apply=True)
    assert ps.raw["owner_phone"]["do_not_dial"] is True
    assert ps.raw["owner_phone"]["do_not_dial_reason"] == G.WALLED_REASON
    assert ps.raw["free_phones"][0]["do_not_dial"] is True
    for li in (agent, atty, ocr):
        assert li.raw["owner_phone"]["role"] == "agent"
        assert "do_not_dial" not in li.raw["owner_phone"]          # a real contact for the sale, not a DNC flag
    assert "role" not in own.raw["owner_phone"] and "do_not_dial" not in own.raw["owner_phone"]
    assert (stats["walled_flagged"], stats["agent_tagged"], stats["free_phones_flagged"]) == (1, 3, 1)
    again = G.flag_lane_phones(board, apply=True)
    assert again["changed"] == 0                                   # idempotent


def test_block_reason_covers_every_lane_and_fails_closed_on_an_unstamped_xref_phone():
    r = G.owner_phone_block_reason
    assert r({"phone": FMT, "source": "liensnc_filing"}) is None
    assert r({"phone": FMT, "source": "ncsbe_voter", "match": "name+address"}) is None
    assert r({"phone": FMT, "source": "buncombe_accela", "county_published": True}) is None
    assert r({"phone": FMT}) is None
    assert r({"phone": FMT, "source": "ncsbe_voter_xref"}) == "sc_xref_identity_unchecked"   # never stamped
    assert r({"phone": FMT, "source": "ncsbe_voter_xref", "identity_check": "corroborated"}) is None
    assert r({"phone": FMT, "source": "ncsbe_voter_xref", "identity_check": "corroborated",
              "do_not_dial": True}) == "do_not_dial"
    assert r({"phone": FMT, "source": "free_people_search"}) == G.WALLED_REASON
    assert r({"phone": FMT, "source": "homeharvest_agent"}) == "agent_contact"
    assert r({"phone": FMT, "source": "raw.description"}) == "agent_contact"
    assert r({"phone": FMT, "source": "liensnc_filing", "role": "agent"}) is None            # the owner's own number
    assert r(None) == "no_phone" and r({"source": "liensnc_filing"}) == "no_phone"
    assert G.usable_owner_phone({"owner_phone": {"phone": FMT, "source": "homeharvest_agent"}}) == ""
    assert G.usable_owner_phone({"owner_phone": {"phone": FMT, "source": "liensnc_filing"}}) == FMT


# --------------------------------------------------------------------------------------
# exports skip what must not be dialed
# --------------------------------------------------------------------------------------
def _export_board() -> dict[str, Listing]:
    return {
        "owner": _listing(owner="ROE RICHARD", state="NC", county="Wake",
                          raw={"owner_phone": {"phone": "(919) 555-0001", "source": "liensnc_filing"}}),
        "flagged": _listing(owner="POE PAT", raw={"owner_phone": _xref(
            phone="(919) 555-0002", identity_check="unverified", do_not_dial=True)}),
        "legacy_xref": _listing(owner="DOE JANE", raw={"owner_phone": _xref(phone="(919) 555-0003")}),
        "corroborated": _listing(owner="KAY KIM", raw={"owner_phone": _xref(
            phone="(919) 555-0004", identity_check="corroborated")}),
        "agent": _listing(owner="LEE LEO", raw={"owner_phone": {
            "phone": "(919) 555-0005", "source": "homeharvest_agent", "match": "Mobile"}}),
        "walled": _listing(owner="MAY MEL", raw={"owner_phone": {
            "phone": "(919) 555-0006", "source": "free_people_search"}}),
        "skip_trace": _listing(owner="ORR OLA", raw={"skip_trace": {"phone_numbers": ["9195550007"]}}),
    }


def test_sms_export_skips_do_not_dial_unchecked_xref_walled_and_agent_phones(tmp_path):
    board = _export_board()
    path, n = _export_sms(list(board.values()), tmp_path / "sms.csv")
    text = path.read_text()
    assert n == 3
    for kept in ("(919) 555-0001", "(919) 555-0004", "9195550007"):
        assert kept in text
    for skipped in ("(919) 555-0002", "(919) 555-0003", "(919) 555-0005", "(919) 555-0006"):
        assert skipped not in text


def test_has_phone_filter_and_workflow_trigger_ignore_blocked_phones():
    board = _export_board()
    kept = _apply_filters(list(board.values()), {"has_phone": True})
    assert {li.owner_name for li in kept} == {"ROE RICHARD", "KAY KIM", "ORR OLA"}
    for name in ("flagged", "legacy_xref", "agent", "walled"):
        assert _check_trigger(board[name], {"has_phone": True}) is False
    for name in ("owner", "corroborated", "skip_trace"):
        assert _check_trigger(board[name], {"has_phone": True}) is True


def test_api_marks_a_blocked_owner_phone_without_mutating_the_listing():
    from foreclosure_scraper.api_server import _filter_leads, _listing_to_dict
    board = _export_board()
    li = board["legacy_xref"]
    before = copy.deepcopy(li.raw)
    out = _listing_to_dict(li)
    assert li.raw == before
    # owner_phone is in the API keep-list; it must come back marked
    op = out["raw"]["owner_phone"]
    assert op["dialable"] is False and op["do_not_dial"] is True and op["block_reason"].startswith("sc_xref_identity")
    assert _listing_to_dict(board["owner"])["raw"]["owner_phone"]["dialable"] is True
    assert _listing_to_dict(board["agent"])["raw"]["owner_phone"]["block_reason"] == "agent_contact"
    assert {x.owner_name for x in _filter_leads(list(board.values()), {"has_phone": True})} == {
        "ROE RICHARD", "KAY KIM", "ORR OLA"}


# --------------------------------------------------------------------------------------
# DNC scrubber
# --------------------------------------------------------------------------------------
@pytest.fixture
def dnc_registry(monkeypatch):
    monkeypatch.setattr(dnc_mod, "_DNC_SET", {"9195550099"})            # a loaded registry, not "no file"
    monkeypatch.setattr(dnc_mod, "_DNC_PATH", Path("/nonexistent/dnc_registry.csv"))


def test_dnc_never_scrubs_a_blocked_phone_as_clear(dnc_registry):
    board = _export_board()
    stats = dnc_mod.enrich_dnc_scrub(list(board.values()))
    status = {k: {e["phone"]: e["dnc_status"] for e in v.raw["dnc_scrub"]} for k, v in board.items()
              if v.raw.get("dnc_scrub")}
    assert status["owner"] == {"9195550001": "clear"}
    assert status["corroborated"] == {"9195550004": "clear"}
    assert status["flagged"] == {"9195550002": "do_not_dial"}
    assert status["legacy_xref"] == {"9195550003": "do_not_dial"}
    assert status["walled"] == {"9195550006": "do_not_dial"}
    assert status["agent"] == {"9195550005": "not_owner_contact"}
    assert board["flagged"].raw["dnc_scrub"][0]["block_reason"] == "do_not_dial"
    assert stats["blocked"] == 4 and stats["clear"] == 3               # 2 owners + the skip-trace number
    assert board["agent"].raw["owner_phone"]["role"] == "agent"        # the lane rule was stamped too


def test_dnc_downgrades_a_clear_result_from_before_the_phone_was_gated(dnc_registry):
    li = _listing(raw={"owner_phone": _xref(phone="(919) 555-0003"),
                       "dnc_scrub": [{"phone": "9195550003", "dnc_registered": False, "dnc_status": "clear"}]})
    dnc_mod.enrich_dnc_scrub([li])
    assert li.raw["dnc_scrub"][0]["dnc_status"] == "do_not_dial"
    assert len(li.raw["dnc_scrub"]) == 1


def test_dnc_rescrubs_a_phone_once_its_block_is_lifted_and_is_idempotent(dnc_registry):
    li = _listing(owner="SMITH JOHN A", raw={"owner_phone": _xref(phone="(919) 555-0003")})
    dnc_mod.enrich_dnc_scrub([li])
    assert li.raw["dnc_scrub"][0]["dnc_status"] == "do_not_dial"
    li.raw["owner_phone"]["identity_check"] = "corroborated"           # the gate cleared it
    dnc_mod.enrich_dnc_scrub([li])
    assert li.raw["dnc_scrub"][0]["dnc_status"] == "clear" and len(li.raw["dnc_scrub"]) == 1
    snap = copy.deepcopy(li.raw["dnc_scrub"])
    dnc_mod.enrich_dnc_scrub([li])
    assert li.raw["dnc_scrub"] == snap


# --------------------------------------------------------------------------------------
# write-time gate in enrichment_sc_voter_xref
# --------------------------------------------------------------------------------------
@pytest.fixture
def xref_env(monkeypatch):
    monkeypatch.setattr(X, "_NAME_INDEX", {("SMITH", "JOHN"): PHONE})
    idx = _index(_rec())
    monkeypatch.setattr(G, "_DEFAULT_INDEX", idx)
    return idx


def test_write_time_gate_stores_an_unverified_match_flagged_not_dialable(xref_env):
    li = _listing(owner="SMITH JOHN A", raw={"owner_mailing": _mailing("22 MAIN ST GREER SC 29650", "SC")})
    stats = X.enrich_sc_phone_xref([li])
    op = li.raw["owner_phone"]
    assert op["phone"] == FMT and op["source"] == "ncsbe_voter_xref"        # the number is kept
    assert op["identity_check"] == "unverified" and op["do_not_dial"] is True
    assert G.is_owner_phone_usable(op) is False
    assert (stats["matched"], stats["unverified"], stats["corroborated"]) == (1, 1, 0)


def test_write_time_gate_leaves_a_corroborated_match_dialable(xref_env):
    li = _listing(owner="SMITH JOHN A",
                  raw={"owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")})
    stats = X.enrich_sc_phone_xref([li])
    op = li.raw["owner_phone"]
    assert op["identity_check"] == "corroborated" and "do_not_dial" not in op
    assert G.is_owner_phone_usable(op) is True
    assert stats["corroborated"] == 1


def test_write_time_gate_never_matches_an_entity(xref_env):
    li = _listing(owner="SMITH JOHN A TRUST")
    stats = X.enrich_sc_phone_xref([li])
    assert "owner_phone" not in li.raw
    assert stats["skipped_entity"] == 1 and stats["matched"] == 0


def test_write_time_gate_regates_a_phone_stamped_by_an_earlier_run(xref_env):
    old = _listing(owner="BRANSON BRADY D", raw={"owner_phone": _xref("nc_xref:SMITH,JOHN", phone=FMT)})
    keep = _listing(owner="ROE RICHARD", raw={"owner_phone": {"phone": "(919) 555-0001", "source": "liensnc_filing"}})
    stats = X.enrich_sc_phone_xref([old, keep])
    assert old.raw["owner_phone"]["identity_check"] == "contradicted"
    assert old.raw["owner_phone"]["do_not_dial"] is True
    assert "identity_check" not in keep.raw["owner_phone"]                  # another source: never clobbered or gated
    assert stats["regated"] == 1 and stats["matched"] == 0 and stats["contradicted"] == 1


def test_write_time_gate_still_skips_non_sc_rows_and_rows_with_a_phone(xref_env):
    nc = _listing(state="NC", county="Wake", owner="SMITH JOHN A")
    sc_has = _listing(owner="SMITH JOHN A", raw={"owner_phone": {"phone": "(704) 555-0100", "source": "liensnc_filing"}})
    X.enrich_sc_phone_xref([nc, sc_has])
    assert "owner_phone" not in nc.raw
    assert sc_has.raw["owner_phone"]["phone"] == "(704) 555-0100"


# --------------------------------------------------------------------------------------
# the targeted voter scan
# --------------------------------------------------------------------------------------
def _write_voter_file(path: Path, rows: list[dict]) -> None:
    header = ["c%d" % i for i in range(30)]
    lines = ["\t".join('"%s"' % h for h in header)]
    for r in rows:
        cols = [""] * 30
        cols[1], cols[4], cols[5], cols[6] = r["county"], r["last"], r["first"], r.get("middle", "")
        cols[8], cols[12], cols[23] = r.get("status", "A"), r["street"], r.get("phone", "")
        lines.append("\t".join('"%s"' % c for c in cols))
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")


def test_targeted_scan_keeps_only_the_wanted_active_voters_with_a_phone(tmp_path):
    _write_voter_file(tmp_path / "ncvoter92.txt", [
        {"county": "WAKE", "last": "SMITH", "first": "JOHN", "middle": "ANDREW",
         "street": "1124  TYLER FARMS DR   ", "phone": "9195551234"},
        {"county": "WAKE", "last": "SMITH", "first": "JOHN", "middle": "", "status": "I",
         "street": "9 INACTIVE RD", "phone": "9195550000"},                    # inactive
        {"county": "WAKE", "last": "SMITH", "first": "JOHN", "middle": "", "street": "9 NO PHONE RD", "phone": ""},
        {"county": "WAKE", "last": "JONES", "first": "MARY", "street": "1 OTHER ST", "phone": "9195557777"},  # not asked
    ])
    idx = G.VoterIdentityIndex(voter_dir=tmp_path)
    idx.ensure([("SMITH", "JOHN")])
    recs = idx.records("SMITH", "JOHN")
    assert len(recs) == 1
    assert (recs[0].county, recs[0].middle, recs[0].phone) == ("WAKE", "ANDREW", "9195551234")
    assert recs[0].street_key == ("1124", "TYLER")
    assert idx.records("JONES", "MARY") == [] and idx.files_scanned == 1
    idx.ensure([("SMITH", "JOHN")])                                            # already covered: no second scan
    assert idx.files_scanned == 1


def test_verdict_end_to_end_through_a_scanned_voter_file(tmp_path):
    _write_voter_file(tmp_path / "ncvoter92.txt", [
        {"county": "WAKE", "last": "SMITH", "first": "JOHN", "middle": "ANDREW",
         "street": "1124 TYLER FARMS DR", "phone": PHONE}])
    li = _listing(owner="SMITH JOHN A", raw={
        "owner_phone": _xref(), "owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")})
    idx = G.VoterIdentityIndex(voter_dir=tmp_path)
    stats = G.flag_unverified_xref_phones([li], apply=True, index=idx)
    assert li.raw["owner_phone"]["identity_check"] == "corroborated"
    assert stats["voter_files_scanned"] == 1


def test_a_missing_voter_directory_degrades_to_unverified_never_corroborated(tmp_path):
    li = _listing(owner="SMITH JOHN A", raw={
        "owner_phone": _xref(), "owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")})
    idx = G.VoterIdentityIndex(voter_dir=tmp_path / "does-not-exist")
    assert G.xref_identity_verdict(li, index=idx) == G.UNVERIFIED


# --------------------------------------------------------------------------------------
# behaviour that existed before the gate must not change (mirrors tests/test_goliath_gap_modules.py)
# --------------------------------------------------------------------------------------
def test_dnc_without_a_registry_file_still_tags_an_unsourced_phone_unverified(monkeypatch):
    monkeypatch.setattr(dnc_mod, "_DNC_SET", None)
    monkeypatch.setattr(dnc_mod, "_DNC_PATH", Path("/nonexistent/dnc_registry.csv"))
    li = _listing(state="NC", county="Wake", raw={"owner_phone": {"phone": "919-555-1234"}})
    stats = dnc_mod.enrich_dnc_scrub([li])
    assert stats["listings_with_phone"] == 1 and stats["unverified"] >= 1
    assert li.raw["dnc_scrub"][0]["dnc_status"] == "unverified"
    assert li.raw["dnc_scrub"][0]["dnc_registered"] is None


def test_dnc_still_counts_an_already_scrubbed_listing_once(monkeypatch):
    monkeypatch.setattr(dnc_mod, "_DNC_SET", set())
    monkeypatch.setattr(dnc_mod, "_DNC_PATH", Path("/nonexistent/dnc_registry.csv"))
    li = _listing(state="NC", county="Wake", raw={
        "owner_phone": {"phone": "9195551234"},
        "dnc_scrub": [{"phone": "9195551234", "dnc_status": "clear"}]})
    stats = dnc_mod.enrich_dnc_scrub([li])
    assert stats["scrubbed"] == 1
    assert li.raw["dnc_scrub"] == [{"phone": "9195551234", "dnc_status": "clear"}]      # untouched


def test_a_phone_with_no_source_still_counts_for_the_workflow_trigger_and_the_sms_export(tmp_path):
    li = _listing(state="NC", county="Wake", owner="SMITH JOHN", raw={"owner_phone": {"phone": "9195551234"}})
    assert _check_trigger(li, {"has_phone": True}) is True
    path, n = _export_sms([li], tmp_path / "sms.csv")
    assert n == 1 and "9195551234" in path.read_text()


# --------------------------------------------------------------------------------------
# scripts/flag_unverified_sc_phones.py
# --------------------------------------------------------------------------------------
def _load_script():
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "scripts" / "flag_unverified_sc_phones.py"
    spec = importlib.util.spec_from_file_location("flag_unverified_sc_phones_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(state, county, owner, source, raw):
    return {"state": state, "county": county, "owner_name": owner, "source": source, "raw": raw}


def test_script_dry_run_counts_by_lane_verdict_and_segment(tmp_path, monkeypatch):
    """A synthetic board through measure(): no board read, no write, the real voter scan on a tiny file."""
    _write_voter_file(tmp_path / "ncvoter92.txt", [
        {"county": "WAKE", "last": "SMITH", "first": "JOHN", "middle": "ANDREW",
         "street": "1124 TYLER FARMS DR", "phone": PHONE}])
    hot = {"distress_stack": {"tier": "HOT"}}
    rows = [
        # SC: one corroborated xref, one unverified, one contradicted (entity), one agent
        _row("SC", "Oconee", "SMITH JOHN A", "sc.a", {**hot, "owner_phone": _xref(),
             "owner_mailing": _mailing("1124 TYLER FARMS DR RALEIGH NC 27612", "NC")}),
        _row("SC", "Pickens", "SMITH JOHN A", "sc.a", {"owner_phone": _xref(),
             "owner_mailing": _mailing("22 MAIN ST GREER SC 29650", "SC")}),
        _row("SC", "Spartanburg", "SMITH JOHN A LLC", "sc.a", {"owner_phone": _xref()}),
        _row("SC", "Anderson", "ROE RICHARD", "sc.a", {"owner_phone": {
            "phone": "(864) 555-0001", "source": "homeharvest_agent", "match": "Mobile"}}),
        _row("SC", "Anderson", "NO PHONE", "sc.a", {}),
        # NC: liensnc owner phone (kept), name-address voter (kept), name-only voter (kept, not strict)
        _row("NC", "Wake", "OWN ER", "counties_generic.liensnc", {"owner_phone": {
            "phone": "(919) 555-0001", "source": "liensnc_filing"}}),
        _row("NC", "Wake", "VOT ER", "nc.a", {"owner_phone": {
            "phone": "(919) 555-0002", "source": "ncsbe_voter", "match": "name+address"}}),
        _row("NC", "Wake", "NAM ER", "nc.a", {"owner_phone": {
            "phone": "(919) 555-0003", "source": "ncsbe_voter", "match": "name+county-unique"}}),
        _row("TX", "Bexar", "OUT STATE", "tx.a", {"owner_phone": {"phone": "(210) 555-0001", "source": "x"}}),
    ]
    script = _load_script()
    import foreclosure_scraper.board_stream as bs
    monkeypatch.setattr(bs, "iter_board_rows", lambda *a, **k: iter(copy.deepcopy(rows)))
    m = script.measure(voter_dir=tmp_path)
    assert m["rows_read"] == 9
    g = m["gate"]
    assert (g["xref_phones"], g["corroborated"], g["unverified"], g["contradicted"]) == (3, 1, 1, 1)
    assert m["rows_seg"]["SC"] == 5 and m["rows_seg"]["NC"] == 3
    assert m["rows_seg"]["NC_liensnc"] == 1 and m["rows_seg"]["NC_no_liensnc"] == 2
    assert m["rows_seg"]["SC_HOT"] == 1
    # SC: 4 rows carry a phone, only the corroborated xref phone survives the gate
    assert (m["before"]["SC"], m["after"]["SC"], m["after_strict"]["SC"]) == (4, 1, 1)
    assert (m["before"]["SC_HOT"], m["after"]["SC_HOT"]) == (1, 1)
    # NC: all three stay; the name-only fallback drops out of the strict count only
    assert (m["before"]["NC"], m["after"]["NC"], m["after_strict"]["NC"]) == (3, 3, 2)
    assert m["after_strict"]["NC_no_liensnc"] == 1 and m["after"]["NC_liensnc"] == 1
    assert m["blocked_by"]["SC|agent_contact"] == 1
    assert m["blocked_by"]["SC|sc_xref_identity_unverified"] == 1
    assert m["blocked_by"]["SC|sc_xref_identity_contradicted"] == 1
    assert len(m["samples"]) == 1 and m["samples"][0]["reason"] == "entity_or_estate_owner"
    assert m["xref_mail_state"] == {"NC": 1, "SC": 1, "no mailing": 1}
    script._print(m)                                                        # the report renders


def test_script_apply_holds_the_lock_stamps_the_rows_and_writes_once(monkeypatch):
    """--apply wiring with fakes for board_lock / load_board / write_artifact: nothing real is touched."""
    import contextlib
    import foreclosure_scraper.web_artifact as wa
    rows = [_listing(owner="SMITH JOHN A", raw={"owner_phone": _xref()}),
            _listing(owner="ROE RICHARD", raw={"owner_phone": {"phone": FMT, "source": "homeharvest_agent"}}),
            _listing(owner="POE PAT", raw={"owner_phone": {"phone": FMT, "source": "free_people_search"}})]
    events = []

    @contextlib.contextmanager
    def fake_lock(root, owner="", **kw):
        events.append(("lock", owner))
        try:
            yield
        finally:
            events.append(("unlock", owner))

    monkeypatch.setattr(wa, "board_lock", fake_lock)
    monkeypatch.setattr(wa, "load_board", lambda docs: (events.append(("load", str(docs))), rows)[1])
    monkeypatch.setattr(wa, "write_artifact",
                        lambda listings, summary, docs_dir=None: (events.append(("write", summary)), None)[1])
    script = _load_script()
    monkeypatch.setattr(G, "_DEFAULT_INDEX", _index(_rec()))                # never scan the real voter files
    assert script._apply() == 0
    assert [e[0] for e in events] == ["lock", "load", "write", "unlock"]
    assert events[0][1] == "flag_unverified_sc_phones"
    summary = events[2][1]["flag_unverified_sc_phones"]
    assert (summary["xref_phones"], summary["unverified"], summary["agent_tagged"], summary["walled_flagged"]) == (1, 1, 1, 1)
    assert rows[0].raw["owner_phone"]["do_not_dial"] is True and rows[0].raw["owner_phone"]["phone"] == FMT
    assert rows[1].raw["owner_phone"]["role"] == "agent"
    assert rows[2].raw["owner_phone"]["do_not_dial"] is True
