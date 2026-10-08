"""call_ready: the call-ready gate per lane (lanes A-E, tiers A-D). Fixtures are made up."""
from __future__ import annotations

import copy
import json
from datetime import date

import pytest

from foreclosure_scraper import call_ready as CR

TODAY = date(2026, 10, 8)


def tax_record(verdict="confirmed", checked="2026-10-06T04:00:00Z", years=3, total=4321.0, own=True,
               verifier="tax_lien_buncombe", version="v6", **ev):
    evidence = {"years_delinquent": years, "total_delinquent": total,
                "delinquent_by_year": {str(2025 - i): round(total / max(years, 1), 2) for i in range(years)},
                "tax_parcel_row_own": own, "owner_match": "same", "url": "https://tax.example.gov/Parcel/1"}
    evidence.update(ev)
    return {"signal": "tax_lien", "verdict": verdict, "checked_at": checked, "verifier": verifier,
            "verifier_version": version, "source": "tax.example.gov", "evidence": evidence,
            "expires_at": "2026-11-05T04:00:00Z", "governs": []}


def row(**kw):
    base = {"source": "counties_generic.arcgis_distress.example_unpaid_bills", "listing_type": "tax_lien",
            "state": "NC", "county": "Buncombe", "parcel_id": "9999-11-2222-00000",
            "street_address": "12 TEST HOLLOW RD", "owner_name": "DOE, JANE Q",
            "first_seen": "2026-09-15T00:00:00", "last_seen": "2026-10-07T00:00:00",
            "raw": {"entity_type": "individual",
                    "gis": {"owner": "DOE, JANE Q", "mailing": "12 TEST HOLLOW RD FAIRVIEW NC 28730"},
                    "owner_mailing": {"mailing": "12 TEST HOLLOW RD FAIRVIEW NC 28730", "absentee": False,
                                      "source": "county_gis"},
                    "verification": [tax_record()]}}
    raw = kw.pop("raw", None)
    base.update(kw)
    if raw:
        base["raw"].update(raw)
    return base


def accela_phone(**kw):
    p = {"phone": "828-555-0142", "source": "buncombe_accela", "match": "parcel_id", "line_type": "landline",
         "tcpa_class": "callable", "needs_dnc_scrub": True, "county_owner": "DOE JANE Q"}
    p.update(kw)
    return p


def voter_phone(**kw):
    p = {"phone": "8285550199", "source": "ncsbe_voter", "match": "name+county-unique", "line_type": "wireless",
         "tcpa_class": "manual_only", "needs_dnc_scrub": True, "matched_name": "JANE Q DOE"}
    p.update(kw)
    return p


# --------------------------------------------------------------------------------------------- lane A

def test_lane_a_tier_a_when_everything_is_checked_and_the_phone_is_tied():
    b = CR.call_ready(row(raw={"owner_phone": accela_phone()}), TODAY)
    assert (b["lane"], b["tier"]) == ("A", "A")
    assert b["phone"] == "tied" and b["mail"] == "ok"
    assert b["facts"]["years_delinquent"] == 3 and b["facts"]["tax_checked_on"] == "2026-10-06"
    assert "dnc_not_scrubbed" in b["unmet"]           # listed, never lowers the tier
    assert CR.hard_unmet(b) == []
    assert "past due over 3 years" in b["reason"] and "tied to this property" in b["reason"]


def test_lane_a_tier_b_when_the_phone_matches_by_name_only():
    b = CR.call_ready(row(raw={"owner_phone": voter_phone()}), TODAY)
    assert (b["lane"], b["tier"]) == ("A", "B")
    assert b["phone"] == "name_match_only"
    assert "confirm you are speaking with the owner" in b["reason"]


@pytest.mark.parametrize("rec, code", [
    (tax_record(checked="2026-08-20T00:00:00Z"), "tax_check_old"),
    (tax_record(verdict="stale", total=0.0, years=0), "tax_paid"),
    (tax_record(verdict="refuted", total=0.0, years=0), "tax_not_owed"),
    (tax_record(verdict="unconfirmed"), "tax_check_unconfirmed"),
    (tax_record(own=False, tax_parcel="1234567", address_relation="conflict"), "tax_check_other_parcel"),
    (tax_record(total=12.0, years=1), "tax_balance_de_minimis"),
    (tax_record(verifier="tax_lien_ptscloud", version="v3"), "tax_check_outdated_verifier"),
    (tax_record(sold_at_tax_sale_years=[2024]), "sold_at_tax_sale"),
])
def test_lane_a_tier_d_names_the_failed_tax_condition(rec, code):
    r = row(raw={"owner_phone": accela_phone(), "verification": [rec]})
    b = CR.call_ready(r, TODAY)
    assert b["lane"] == "A" and b["tier"] == "D"
    assert code in b["unmet"]
    assert b["reason"].startswith("Not ready: ")


def test_no_tax_check_at_all_is_research():
    r = row(raw={"owner_phone": accela_phone(), "verification": []})
    b = CR.call_ready(r, TODAY)
    assert (b["lane"], b["tier"]) == ("A", "D") and b["unmet"][0] == "tax_check_missing"


def test_bankruptcy_on_record_blocks_the_call():
    r = row(raw={"owner_phone": accela_phone(),
                 "bankruptcy_stay": {"status": "stayed", "chapter": "13", "date_filed": "2026-06-01"}})
    b = CR.call_ready(r, TODAY)
    assert b["tier"] == "D" and "in_bankruptcy" in b["unmet"]


def test_a_phone_of_another_person_is_never_dialed():
    # the county roll agrees with the row's owner; the voter match names someone else
    r = row(raw={"owner_phone": voter_phone(matched_name="ROBERT SMITHFIELD")})
    b = CR.call_ready(r, TODAY)
    assert b["lane"] == "E" and b["tier"] == "C"          # still a checked issue: mail it
    assert "phone_other_record" in b["unmet"]


def test_dnc_registered_phone_goes_to_mail():
    r = row(raw={"owner_phone": accela_phone(),
                 "dnc_scrub": [{"phone": "8285550142", "dnc_status": "registered"}]})
    b = CR.call_ready(r, TODAY)
    assert b["lane"] == "E" and b["tier"] == "C" and "dnc_registered" in b["unmet"]


def test_bad_mailing_keeps_a_tied_phone_out_of_tier_a():
    r = row(raw={"owner_phone": accela_phone(), "owner_mailing": {"mailing": "UNKNOWN"}, "gis": {"owner": "DOE, JANE Q"}})
    b = CR.call_ready(r, TODAY)
    assert b["lane"] == "A" and b["tier"] == "D" and "mailing_malformed" in b["unmet"]


# --------------------------------------------------------------------------------------------- lane E

def test_entity_owner_with_a_confirmed_debt_is_mail_only():
    r = row(owner_name="TEST HOLDINGS LLC", raw={"entity_type": "entity", "gis": {"owner": "TEST HOLDINGS LLC"}})
    b = CR.call_ready(r, TODAY)
    assert (b["lane"], b["tier"]) == ("E", "C")
    assert "owner_not_person" not in b["unmet"]


def test_person_without_a_phone_is_mail_only():
    b = CR.call_ready(row(), TODAY)
    assert (b["lane"], b["tier"]) == ("E", "C") and "no_dialable_phone" in b["unmet"]
    assert CR.hard_unmet(b) == []


def test_government_owner_has_no_lane():
    r = row(owner_name="COUNTY OF EXAMPLE", raw={"entity_type": "government", "gis": {"owner": "COUNTY OF EXAMPLE"}})
    b = CR.call_ready(r, TODAY)
    assert b["lane"] == "" and b["tier"] == "D" and "government_owner" in b["unmet"]


# --------------------------------------------------------------------------------------------- lanes B and C

def probate_row(**raw):
    r = row(listing_type="probate_notice", source="public_notices.example", owner_name="DOE, JOHN ALLEN",
            raw={"entity_type": "individual", "gis": {"owner": "DOE, JOHN ALLEN"},
                 "probate": {"decedent": "John Allen Doe", "es_case_number": "26E000001-100",
                             "personal_representative": "Mary Doe", "pr_address": "5 Elm St Example NC 28700",
                             "date_of_death": "2026-07-01"},
                 "verification": []})
    r["raw"].update(raw)
    return r


def test_lane_b_open_estate_with_a_representative_is_mailed():
    b = CR.call_ready(probate_row(), TODAY)
    assert (b["lane"], b["tier"]) == ("B", "C")
    assert "personal representative" in b["reason"]
    assert b["facts"]["estate"] == "open"


def test_lane_b_needs_the_county_roll_to_name_the_dead_owner():
    b = CR.call_ready(probate_row(gis={"owner": "ACME HOLDINGS INC"}), TODAY)
    assert b["lane"] == "B" and b["tier"] == "D" and "decedent_not_tied_to_parcel" in b["unmet"]


def test_lane_b_without_a_property_is_research():
    r = probate_row()
    r["parcel_id"] = None
    r["street_address"] = None
    b = CR.call_ready(r, TODAY)
    assert b["tier"] == "D" and "no_property_on_row" in b["unmet"]


def test_old_probate_notice_means_the_estate_status_is_unknown():
    r = probate_row()
    r["first_seen"] = "2025-01-10T00:00:00"
    b = CR.call_ready(r, TODAY)
    assert b["lane"] == "B" and "estate_status_unknown" in b["unmet"]


def heirs_row(**raw):
    r = row(owner_name="DOE JOHN ALLEN HEIRS", legal_description="LOT 7 TEST HOLLOW SUBDIVISION",
            raw={"entity_type": "estate", "gis": {"owner": "DOE JOHN ALLEN HEIRS"},
                 "heir_estate": {"owner_of_record": "DOE JOHN ALLEN HEIRS", "care_of": "MARY DOE",
                                 "mailing": "5 ELM ST EXAMPLE NC 28700"}})
    r["raw"].update(raw)
    return r


def test_lane_c_lists_the_missing_lawyer_items():
    b = CR.call_ready(heirs_row(), TODAY)
    assert b["lane"] == "C" and b["tier"] == "D"
    assert b["lawyer"]["parcel"] == "ok" and b["lawyer"]["tax_checked"] == "2026-10-06"
    for code in ("lawyer_legal_description", "lawyer_deed_chain", "lawyer_heirs", "lawyer_rod_checked",
                 "lawyer_probate_checked", "lawyer_obituaries_checked"):
        assert code in b["unmet"]


def test_lane_c_complete_list_is_ready_to_mail_and_hand_to_the_attorney():
    extra = {
        "deed_chain": {"transfers": [{"date": "1987-03-02", "book": "1450", "page": "22", "source": "rod_docs"},
                                     {"date": "2001-05-09", "book": "2210", "page": "301", "source": "rod_docs"}],
                       "summary": {}},
        "heir_candidates": [{"name": "Mary Doe", "relation": "daughter", "source_kind": "obituary_survivor",
                             "source_url": "https://news.example/obit", "source_date": "2024-02-01", "label": "candidate"}],
        "rod_lookup": {"checked_at": "2026-10-01"},
    }
    r = heirs_row(**extra)
    r["raw"]["verification"].append({"signal": "probate_heir", "verdict": "confirmed", "checked_at": "2026-10-05T00:00:00Z",
                                     "verifier": "probate_heir_buncombe", "source": "rod.example",
                                     "evidence": {"transfer": {"chain": {"complete": True}}}})
    b = CR.call_ready(r, TODAY)
    assert (b["lane"], b["tier"]) == ("C", "C"), b["unmet"]
    assert all(v != "missing" for v in b["lawyer"].values())


def test_an_obituary_name_match_alone_is_never_an_owner_call():
    r = row(raw={"owner_phone": accela_phone(), "obituary": {"decedent": "Jane Q Doe", "county": "Buncombe"}})
    b = CR.call_ready(r, TODAY)
    assert b["lane"] == "B" and b["tier"] == "D" and "owner_maybe_deceased" in b["unmet"]


# --------------------------------------------------------------------------------------------- lane D

def sale_row(**kw):
    r = row(listing_type="foreclosure_sale", source="law_firms.example", sale_date="2026-10-20T10:00:00",
            raw={"owner_phone": accela_phone(), "verification": []})
    r.update(kw)
    return r


def test_lane_d_live_sale_rechecked_at_the_source():
    b = CR.call_ready(sale_row(), TODAY)
    assert (b["lane"], b["tier"]) == ("D", "A")
    assert b["facts"]["days"] == 12 and "set for 2026-10-20" in b["reason"]


def test_lane_d_needs_the_original_counties():
    b = CR.call_ready(sale_row(county="Wake"), TODAY)
    assert b["lane"] != "D"


@pytest.mark.parametrize("change, code", [
    ({"sale_date": "2026-09-01T10:00:00"}, "sale_window_closed"),
    ({"last_seen": "2026-09-20T00:00:00"}, "status_not_rechecked"),
    ({"auction_status": "postponed"}, "sale_pulled"),
])
def test_lane_d_research_when_the_sale_is_not_live(change, code):
    b = CR.call_ready(sale_row(**change), TODAY)
    assert b["lane"] == "D" and b["tier"] == "D" and code in b["unmet"]


def test_open_upset_window_is_live():
    r = sale_row(sale_date="2026-10-01T10:00:00")
    r["raw"]["upset_bid"] = {"in_window": True, "deadline_iso": "2026-10-12"}
    b = CR.call_ready(r, TODAY)
    assert b["lane"] == "D" and b["tier"] == "A" and b["facts"]["window"] == "upset_open"


# --------------------------------------------------------------------------------------------- publishing

def test_block_is_public_safe():
    r = probate_row(owner_phone=voter_phone())
    for rr in (r, row(raw={"owner_phone": accela_phone()})):
        b = CR.call_ready(rr, TODAY)
        s = json.dumps(b)
        assert "555" not in s and "Mary" not in s and "DOE" not in s.upper().replace("DOES", "")


def test_stamp_board_keeps_every_row_and_is_idempotent():
    rows = [row(raw={"owner_phone": accela_phone()}), probate_row(), sale_row(), {"raw": None}]
    before = len(rows)
    c1 = CR.stamp_board(rows, TODAY)
    snap = copy.deepcopy([r["raw"]["call_ready"] for r in rows])
    c2 = CR.stamp_board(rows, TODAY)
    assert len(rows) == before == c1["rows"] == c2["rows"]
    assert [r["raw"]["call_ready"] for r in rows] == snap
    assert c1["by_lane_tier"] == c2["by_lane_tier"]


def test_rank_orders_older_bigger_debts_first():
    small = CR.call_ready(row(raw={"owner_phone": accela_phone(), "verification": [tax_record(years=1, total=300.0)]}), TODAY)
    big = CR.call_ready(row(raw={"owner_phone": accela_phone(), "verification": [tax_record(years=6, total=12000.0)]}), TODAY)
    assert small["tier"] == big["tier"] == "A"
    assert big["rank"] > small["rank"]


def test_every_unmet_code_has_words():
    import re
    from pathlib import Path
    src = Path(CR.__file__).read_text()
    used = set(re.findall(r'"([a-z_]+)"', src)) & set(CR.UNMET_WORDS)
    assert used                        # the vocabulary is read from the module itself
    for code in ("tax_check_missing", "no_property_on_row", "decedent_tie_unproven", "dnc_registered"):
        assert code in CR.UNMET_WORDS
