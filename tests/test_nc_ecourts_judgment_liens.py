"""NC eCourts Judgment Search: docketed money judgments kept as 'judgment_lien' leads.

Hand-written hits (made-up names and case numbers) in the live hit shape read on
2026-10-07: no amount field anywhere, creditors often empty, location
'<County> District Court'.
"""
from __future__ import annotations

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_lis_pendens as mod


def _hit(cause, *, status="Active", debtor="TESTPERSON, ALEXANDRA", creditor="SAMPLE FINANCE LLC",
         case="26CV009999-590", location="Mecklenburg District Court"):
    return {
        "caseNumber": case, "location": location, "causeOfActionDesc": cause,
        "civilJudgmentStatus": status, "judgmentType": "Granted in Whole or Part",
        "caseCategoryKey": "CV", "caseID": 1, "judgmentId": 2,
        "orderedDate": "2026-09-28T23:00:00-05:00",
        "debtors": [{"name": debtor, "partyType": "D"}] if debtor else [],
        "creditors": [{"name": creditor}] if creditor else [],
    }


def test_money_owed_becomes_a_judgment_lien_lead():
    li = mod._judgment_lien_listing(_hit("CV - Money Owed"))
    assert li is not None
    assert li.source == mod.JUDGMENT_LIEN_SOURCE
    assert li.listing_type == ListingType.DISTRESSED
    assert li.county == "Mecklenburg" and li.state == "NC"
    assert li.case_number == "26CV009999-590"
    assert li.defendant == "TESTPERSON, ALEXANDRA" and li.plaintiff == "SAMPLE FINANCE LLC"
    assert li.judgment_amount is None
    b = li.raw["nc_ecourts"]
    assert b["signal"] == "judgment_lien" and b["court"] == "District"
    assert b["amount_published"] is False and b["lien_statute"] == "NCGS 1-234"
    assert b["orderedDate"].startswith("2026-09-28")
    assert "NCGS 1-234" in li.description


def test_blank_creditor_is_allowed_and_said_so():
    li = mod._judgment_lien_listing(_hit("CV - Collection on Account", creditor=None))
    assert li.plaintiff is None and "creditor not shown" in li.description


def test_terminal_status_missing_debtor_and_other_causes_are_dropped():
    assert mod._judgment_lien_listing(_hit("CV - Money Owed", status="Satisfied")) is None
    assert mod._judgment_lien_listing(_hit("CV - Money Owed", debtor=None)) is None
    assert mod._judgment_lien_listing(_hit("CV - Summary Ejectment")) is None
    assert mod._judgment_lien_listing(_hit("CV - Bond Forfeiture")) is None


def test_dv_safety_exclusion_applies():
    hit = _hit("CV - Money Owed", creditor="DOMESTIC VIOLENCE PROTECTIVE ORDER")
    assert mod._judgment_lien_listing(hit) is None


def test_foreclosure_causes_still_take_the_old_path():
    hit = _hit("CV - Lis Pendens")
    assert mod._judgment_lien_listing(hit) is None
    old = mod._hit_to_listing(hit, mod.NCECourtsLisPendens.slug)
    assert old.listing_type == ListingType.LIS_PENDENS
    assert old.source == "counties_nc.nc_ecourts_lis_pendens"
    assert mod._hit_to_listing(_hit("CV - Money Owed"), mod.NCECourtsLisPendens.slug) is None


def test_env_gate(monkeypatch):
    monkeypatch.delenv(mod.JUDGMENT_LIEN_ENV, raising=False)
    assert mod.judgment_liens_enabled() is True
    monkeypatch.setenv(mod.JUDGMENT_LIEN_ENV, "0")
    assert mod.judgment_liens_enabled() is False


def test_dateless_rows_survive_the_active_filter_by_prefix():
    li = mod._judgment_lien_listing(_hit("CV - Money Owed"))
    assert li.sale_date is None
    assert main._active_only(li, 120)


def test_scorer_names_the_signal_judgment_lien():
    li = mod._judgment_lien_listing(_hit("CV - Money Owed"))
    names = [s[0] for s in ds._signals_for(li)]
    assert "judgment_lien" in names and "distressed" not in names
    assert ds.SIGNAL_CATEGORY["judgment_lien"] == "FINANCIAL"
