"""verification_human_lane.py -- the per-lead, human-assisted NC eCourts / NC
SOS verification lane (docs/validation_2026-10-02/VERIFICATION_PIPELINE_SPEC.md
section 4, option 2). Everything exercised here is the PURE query-building and
result-parsing logic; the actual human-in-the-loop step (opening a real
browser, a human clearing a CAPTCHA, saving a page) is not live-exercised in
this session -- same convention as tests/test_nc_ecourts_estates.py's own
docstring for the sibling WAF-walled scraper. `check_new_names_liveness` hits
a live NC voter-lookup network call in production; here it is exercised with
the real function monkeypatched out, never a live call.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper import verification_human_lane as lane
from foreclosure_scraper import enrichment_nc_voter_lookup


# --------------------------------------------------------------------------- #
# classify_signal
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("listing_type,expected", [
    ("probate_notice", "probate"),
    ("estate_lead", "probate"),
    ("divorce_notice", "divorce"),
    ("lis_pendens", "lis_pendens"),
    ("foreclosure_sale", "lis_pendens"),
    ("sheriff_sale", "lis_pendens"),
    ("auction", "lis_pendens"),
    ("tax_lien", None),
    (None, None),
])
def test_classify_signal(listing_type, expected):
    assert lane.classify_signal({"listing_type": listing_type}) == expected


# --------------------------------------------------------------------------- #
# _match_row (the pure predicate find_lead streams the board through)
# --------------------------------------------------------------------------- #
def _row(**overrides):
    base = {
        "source_url": "https://example.com/a",
        "parcel_id": "9688-19-9972",
        "case_number": "26E000100-320",
        "street_address": "123 Main St",
        "county": "Buncombe",
        "zip_code": "28801",
        "state": "NC",
        "listing_type": "probate_notice",
        "owner_name": "MARTHA MCDONALD (HEIRS)",
        "defendant": "MARTHA MCDONALD (HEIRS)",
        "plaintiff": None,
    }
    base.update(overrides)
    return base


def test_match_row_parcel_id_normalizes_punctuation():
    row = _row()
    assert lane._match_row(row, parcel_id="968819 9972")
    assert not lane._match_row(row, parcel_id="0000000000")


def test_match_row_case_number_case_insensitive():
    row = _row()
    assert lane._match_row(row, case_number="26e000100-320")
    assert not lane._match_row(row, case_number="99E000000-000")


def test_match_row_requires_every_given_identifier():
    row = _row()
    assert lane._match_row(row, parcel_id="9688199972", county="Buncombe")
    assert not lane._match_row(row, parcel_id="9688199972", county="Henderson")


def test_match_row_street_address_and_zip():
    row = _row()
    assert lane._match_row(row, street_address="123 MAIN ST", zip_code="28801-1234")
    assert not lane._match_row(row, street_address="999 Other Ave")


# --------------------------------------------------------------------------- #
# find_lead -- isolated from board_stream/board_parts file-format mechanics
# (already covered elsewhere) by monkeypatching iter_board_rows itself.
# --------------------------------------------------------------------------- #
def test_find_lead_returns_first_match_and_stops(monkeypatch):
    rows = [_row(parcel_id="1"), _row(parcel_id="2"), _row(parcel_id="3")]
    seen = []

    def fake_iter(path):
        for r in rows:
            seen.append(r["parcel_id"])
            yield r

    monkeypatch.setattr(lane.board_stream, "iter_board_rows", fake_iter)
    found = lane.find_lead(docs_dir="docs", parcel_id="2")
    assert found["parcel_id"] == "2"
    assert seen == ["1", "2"]  # stopped as soon as it matched -- never read row 3


def test_find_lead_returns_none_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(lane.board_stream, "iter_board_rows", lambda path: iter([_row(parcel_id="1")]))
    assert lane.find_lead(docs_dir="docs", parcel_id="no-such-parcel") is None


def test_find_lead_requires_an_identifier():
    with pytest.raises(ValueError):
        lane.find_lead(docs_dir="docs")


# --------------------------------------------------------------------------- #
# build_check_specs -- pure, no I/O
# --------------------------------------------------------------------------- #
def test_build_check_specs_probate_row_no_case_number():
    row = _row(case_number=None)
    ecourts, sos, err = lane.build_check_specs(row)
    assert err is None
    assert ecourts.signal == "probate"
    assert ecourts.county == "Buncombe"
    assert ecourts.case_number is None
    assert ecourts.search_name == "MARTHA MCDONALD"  # "(HEIRS)" stripped
    assert ecourts.category_name == "Estate / Special Proceedings"
    assert any("4b. Or search by name" in line for line in ecourts.instructions)
    assert sos is None  # a person, not a business


def test_build_check_specs_probate_row_with_case_number_prefers_case_number_instruction():
    row = _row(case_number="26E000100-320")
    ecourts, _, err = lane.build_check_specs(row)
    assert err is None
    assert ecourts.case_number == "26E000100-320"
    assert any("26E000100-320" in line for line in ecourts.instructions)


def test_build_check_specs_lis_pendens_row_prefers_defendant():
    row = _row(
        listing_type="lis_pendens", owner_name="BANK OF AMERICA NA",
        defendant="Jane Q Homeowner", case_number="25CV000484-260",
    )
    ecourts, sos, err = lane.build_check_specs(row)
    assert err is None
    assert ecourts.signal == "lis_pendens"
    assert ecourts.search_name == "Jane Q Homeowner"
    assert sos is None


def test_build_check_specs_divorce_row_uses_divorce_category():
    row = _row(listing_type="divorce_notice", owner_name=None,
               defendant="Freelon, Tra'vone Donte", plaintiff="Freelon, Lacie",
               case_number="25CV000484-260")
    ecourts, _, err = lane.build_check_specs(row)
    assert err is None
    assert ecourts.signal == "divorce"
    assert ecourts.category_name == "Family / Civil Action"
    assert ecourts.search_name == "Freelon, Tra'vone Donte"


def test_build_check_specs_entity_defendant_also_builds_sos_spec():
    row = _row(listing_type="lis_pendens", defendant="SMITH FAMILY HOLDINGS LLC")
    ecourts, sos, err = lane.build_check_specs(row)
    assert err is None
    assert sos is not None
    assert sos.entity_name == "SMITH FAMILY HOLDINGS LLC"
    assert "sosnc.gov" in sos.portal_url


def test_build_check_specs_refuses_non_nc_rows():
    row = _row(state="SC")
    ecourts, sos, err = lane.build_check_specs(row)
    assert ecourts is None and sos is None
    assert "not NC" in err


def test_build_check_specs_refuses_out_of_scope_listing_type():
    row = _row(listing_type="tax_lien")
    ecourts, sos, err = lane.build_check_specs(row)
    assert ecourts is None and sos is None
    assert "not one of the probate" in err


def test_build_check_specs_refuses_rows_with_no_county():
    row = _row(county=None)
    ecourts, sos, err = lane.build_check_specs(row)
    assert ecourts is None and sos is None
    assert "no county" in err


# --------------------------------------------------------------------------- #
# make_verification_record / pending_wall_record
# --------------------------------------------------------------------------- #
def test_make_verification_record_shape():
    rec = lane.make_verification_record(
        signal="probate", verdict="confirmed", evidence={"x": 1}, source="nc_ecourts",
    )
    assert set(rec) == {"signal", "checked_at", "verdict", "evidence", "source", "verifier_version"}
    assert rec["verifier_version"] == "v1"
    assert rec["checked_at"].endswith("Z")


def test_make_verification_record_rejects_bad_verdict():
    with pytest.raises(ValueError):
        lane.make_verification_record(signal="probate", verdict="definitely_true",
                                       evidence={}, source="x")


def test_pending_wall_record_for_ecourts_spec():
    row = _row(case_number=None)
    ecourts, _, _ = lane.build_check_specs(row)
    rec = lane.pending_wall_record(ecourts)
    assert rec["signal"] == "probate"
    assert rec["verdict"] == "wall"
    assert rec["evidence"]["query"]["county"] == "Buncombe"


def test_pending_wall_record_for_sos_spec():
    row = _row(listing_type="lis_pendens", defendant="SMITH FAMILY HOLDINGS LLC")
    _, sos, _ = lane.build_check_specs(row)
    rec = lane.pending_wall_record(sos)
    assert rec["signal"] == "sos_entity"
    assert rec["verdict"] == "wall"
    assert rec["evidence"]["query"]["entity_name"] == "SMITH FAMILY HOLDINGS LLC"


# --------------------------------------------------------------------------- #
# parse_saved_ecourts_page -- reuses scripts/parse_nc_ecourts_export.py's
# real Smart-Search-grid parser against a synthetic saved page built to the
# documented tr.k-master-row / .party-case-* class contract.
# --------------------------------------------------------------------------- #
_SMARTSEARCH_GRID_HTML = """
<table>
  <tr class="k-master-row">
    <td class="party-case-caseid"><a title="26E000100-320">26E000100-320</a></td>
    <td class="party-case-style">Estate of John Smith</td>
    <td class="party-case-type">Estate</td>
    <td class="party-case-location">Buncombe District Court</td>
    <td class="party-case-filedate"><span title="01/15/2026">01/15/2026</span></td>
    <td class="party-case-partyname">Robert Smith Heir</td>
  </tr>
</table>
"""

_NO_RESULTS_HTML = "<html><body><p>No cases match your search.</p></body></html>"


def test_parse_saved_ecourts_page_finds_case_and_new_name():
    row = _row(case_number="26E000100-320", owner_name="John Smith", defendant="John Smith", plaintiff=None)
    ecourts, _, _ = lane.build_check_specs(row)
    rec = lane.parse_saved_ecourts_page(_SMARTSEARCH_GRID_HTML, ecourts, row)
    assert rec["verdict"] == "confirmed"
    assert rec["signal"] == "probate"
    assert rec["evidence"]["cases_found"] == 1
    # "Robert Smith Heir" was on the saved page but not in owner/defendant/plaintiff
    assert "ROBERT SMITH HEIR" in rec["evidence"]["newly_discovered_names"]
    assert "JOHN SMITH" in rec["evidence"]["already_known_on_board"]


def test_parse_saved_ecourts_page_narrows_to_matching_case_number():
    rows_html = _SMARTSEARCH_GRID_HTML.replace(
        "</table>",
        '<tr class="k-master-row">'
        '<td class="party-case-caseid"><a title="99E999999-999">99E999999-999</a></td>'
        '<td class="party-case-style">Estate of Someone Else</td>'
        '<td class="party-case-type">Estate</td>'
        '<td class="party-case-location">Buncombe District Court</td>'
        '<td class="party-case-filedate"><span title="02/01/2026">02/01/2026</span></td>'
        '<td class="party-case-partyname">Unrelated Person</td>'
        '</tr></table>',
    )
    row = _row(case_number="26E000100-320", owner_name="John Smith")
    ecourts, _, _ = lane.build_check_specs(row)
    rec = lane.parse_saved_ecourts_page(rows_html, ecourts, row)
    assert rec["evidence"]["cases_found"] == 2  # both cases parsed off the page
    names = {c["case_number"] for c in rec["evidence"]["matched_cases"]}
    assert names == {"26E000100-320"}  # but only the requested case matched


def test_parse_saved_ecourts_page_no_results_is_unconfirmed_not_refuted():
    row = _row()
    ecourts, _, _ = lane.build_check_specs(row)
    rec = lane.parse_saved_ecourts_page(_NO_RESULTS_HTML, ecourts, row)
    assert rec["verdict"] == "unconfirmed"
    assert rec["evidence"]["cases_found"] == 0


# --------------------------------------------------------------------------- #
# parse_saved_sos_page -- reuses enrichment_sos_agent._parse_profile verbatim
# --------------------------------------------------------------------------- #
_SOS_ACTIVE_TEXT = """
Legal Name: SMITH FAMILY HOLDINGS LLC
Status: Current-Active
Registered Agent: John Smith
Registered Office Address
123 Main St
Asheville, NC 28801
"""

_SOS_DISSOLVED_TEXT = """
Legal Name: LENTZ INVESTMENTS LLC
Status: Dissolved
Registered Agent: Ethel P. Lentz
Registered Office Address
456 Oak St
Asheville, NC 28803
"""


def _html_of(text: str) -> str:
    return f"<html><body><pre>{text}</pre></body></html>"


def test_parse_saved_sos_page_active_entity_is_confirmed():
    row = _row(listing_type="lis_pendens", defendant="SMITH FAMILY HOLDINGS LLC")
    _, sos, _ = lane.build_check_specs(row)
    rec = lane.parse_saved_sos_page(_html_of(_SOS_ACTIVE_TEXT), sos)
    assert rec["signal"] == "sos_entity"
    assert rec["verdict"] == "confirmed"
    assert rec["evidence"]["profile"]["status"] == "Current-Active"


def test_parse_saved_sos_page_dissolved_entity_is_refuted():
    row = _row(listing_type="lis_pendens", defendant="LENTZ INVESTMENTS LLC")
    _, sos, _ = lane.build_check_specs(row)
    rec = lane.parse_saved_sos_page(_html_of(_SOS_DISSOLVED_TEXT), sos)
    assert rec["verdict"] == "refuted"


def test_parse_saved_sos_page_empty_page_is_unconfirmed():
    row = _row(listing_type="lis_pendens", defendant="NOBODY HOME LLC")
    _, sos, _ = lane.build_check_specs(row)
    rec = lane.parse_saved_sos_page("<html><body>nothing here</body></html>", sos)
    assert rec["verdict"] == "unconfirmed"


# --------------------------------------------------------------------------- #
# check_new_names_liveness / verify_ecourts_from_saved_page -- the free,
# no-CAPTCHA NC voter-file check layered on top of a human-cleared eCourts
# page. nc_voter_lookup is monkeypatched: never a live network call here.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_check_new_names_liveness_maps_statuses(monkeypatch):
    async def fake_lookup(first, last, county, *, match_city=None, include_history=True):
        return {"ok": True, "status": "active", "match": {"full_name": f"{last}, {first}"}}

    monkeypatch.setattr(enrichment_nc_voter_lookup, "nc_voter_lookup", fake_lookup)
    result = await lane.check_new_names_liveness(["ROBERT SMITH"])
    assert result["ROBERT SMITH"]["category"] == "confirmed_active_locatable"


@pytest.mark.asyncio
async def test_check_new_names_liveness_handles_unparseable_single_token(monkeypatch):
    # No lookup should even be attempted for a single-token name.
    async def boom(*a, **k):
        raise AssertionError("should not be called for an unparseable name")

    monkeypatch.setattr(enrichment_nc_voter_lookup, "nc_voter_lookup", boom)
    result = await lane.check_new_names_liveness(["MADONNA"])
    assert result["MADONNA"]["category"] == "unparseable_name"


@pytest.mark.asyncio
async def test_verify_ecourts_from_saved_page_runs_liveness_for_probate(monkeypatch):
    async def fake_lookup(first, last, county, *, match_city=None, include_history=True):
        return {"ok": True, "status": "not_active"}

    monkeypatch.setattr(enrichment_nc_voter_lookup, "nc_voter_lookup", fake_lookup)
    row = _row(case_number="26E000100-320", owner_name="John Smith", defendant="John Smith", plaintiff=None)
    ecourts, _, _ = lane.build_check_specs(row)
    rec = await lane.verify_ecourts_from_saved_page(_SMARTSEARCH_GRID_HTML, ecourts, row)
    assert "new_name_liveness" in rec["evidence"]
    assert rec["evidence"]["new_name_liveness"]["ROBERT SMITH HEIR"]["category"] == "found_but_not_active"


@pytest.mark.asyncio
async def test_verify_ecourts_from_saved_page_skips_liveness_for_lis_pendens(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("liveness check should not run for lis_pendens/divorce")

    monkeypatch.setattr(enrichment_nc_voter_lookup, "nc_voter_lookup", boom)
    row = _row(listing_type="lis_pendens", owner_name="Bank of America",
               defendant="John Smith", case_number="26E000100-320")
    ecourts, _, _ = lane.build_check_specs(row)
    rec = await lane.verify_ecourts_from_saved_page(_SMARTSEARCH_GRID_HTML, ecourts, row)
    assert "new_name_liveness" not in rec["evidence"]


# --------------------------------------------------------------------------- #
# build_patch_preview -- never calls patch_existing_rows(), just previews it
# --------------------------------------------------------------------------- #
def test_build_patch_preview_merges_by_signal_replacing_same_signal():
    row = _row()
    row["raw"] = {"verification": [
        {"signal": "probate", "verdict": "wall", "checked_at": "x", "evidence": {}, "source": "s", "verifier_version": "v1"},
        {"signal": "tax_lien", "verdict": "confirmed", "checked_at": "x", "evidence": {}, "source": "s", "verifier_version": "v1"},
    ]}
    new_record = lane.make_verification_record(
        signal="probate", verdict="confirmed", evidence={"found": True}, source="nc_ecourts",
    )
    preview = lane.build_patch_preview(row, new_record)
    assert preview["row_identity"]["parcel_id"] == row["parcel_id"]
    signals = {r["signal"] for r in preview["raw_patch"]["verification"]}
    assert signals == {"probate", "tax_lien"}
    probate_entry = next(r for r in preview["raw_patch"]["verification"] if r["signal"] == "probate")
    assert probate_entry["verdict"] == "confirmed"  # replaced the old "wall" entry
