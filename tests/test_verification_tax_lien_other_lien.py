"""Another lien's tax_lien row is not a property-tax claim (tax_lien_buncombe v3, _tax_common).

Rows typed tax_lien by a federal / state / lien-agent source (liensnc lien-agent filings, NC
eCourts "Federal Tax Lien" and "NC Certificate of Tax Liability" judgments, SC DEW and DOR liens)
were checked by tax_lien_buncombe against the county's PROPERTY-tax record, and a paid tax bill
refuted them. Covered here, on real rows from the 2026-10-06 board (board_stream, read-only):
names, filers, case and entry numbers and street addresses made up, every field and raw block
shape and every amount as the board carries it; the county pages are the real captures in
tests/fixtures/verification/:

  * the guard: which Buncombe rows the verifier covers (1,078 board rows drop out, 16 that carry
    a county roll block of their own stay, nothing else changes);
  * the mixed-row downgrade: refuted/stale on such a row is published unconfirmed, by the one
    shared function all three tax_lien verifiers call;
  * the offline ledger migration of the v2 entries, and why it needs the VERSION bump;
  * the scorer: a property-tax verdict ends tax_lien / tax_sale only where the row's claim is a
    property-tax one (GOVERNS "tax_lien:property_tax"), so another lien's row on the same parcel
    keeps its signal.
No network.
"""
from __future__ import annotations

import asyncio
import copy
import gzip
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper.enrichment_lead_signals import _facet_signals
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.verification import apply as A
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import ledger as L
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import from_module
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_buncombe as tlb
from foreclosure_scraper.verification.verifiers import tax_lien_ptscloud as tlp
from foreclosure_scraper.verification.verifiers import tax_lien_qpaybill as tlq

FIX = Path(__file__).parent / "fixtures" / "verification"
TODAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 6, 18, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# real board rows (pseudonymized)
# ---------------------------------------------------------------------------

def liensnc_row(**kw) -> dict:
    """A Buncombe `liensnc` row: an Appointment of Lien Agent filing, typed tax_lien by the
    scraper (734 such rows on the 10/6 board, 220 more from counties_generic.liensnc)."""
    row = {"state": "NC", "county": "Buncombe", "source": "liensnc", "listing_type": "tax_lien",
           "parcel_id": "966748739600000", "street_address": "17 Example Ridge Dr",
           "city": "Asheville", "zip_code": "28803", "owner_name": "PAT Q EXAMPLE",
           "case_number": "2600001", "sale_date": "2026-08-26T00:00:00",
           "raw": {"liensnc": {"entry_number": "2600001", "filing_type": "Appointment of Lien Agent",
                               "filing_date": "08/26/2026", "related_filings": "Yes",
                               "source": "liensnc"},
                   "amount_owed": {"value": 136100.0, "source": "assessed_value",
                                   "label": "Tax value (not debt)", "is_actual_debt": False}}}
    row.update(kw)
    return row


#: the county roll's own block as it sits merged into a liensnc row (16 such rows)
ROLL_BLOCK = {"pin": "063617987500000", "principal_tax_due": 173.71, "tax_year": 2025,
              "owner": "JO EXAMPLE (HEIRS)"}
MULTI_YEAR_BLOCK = {"years": [2025, 2026], "per_year": {"2025": 160.2, "2026": 166.52},
                    "years_delinquent": 2, "matured_years": [2025], "total_due": 326.72,
                    "amount_basis": "annual_bill"}


def ecourts_row(county="Buncombe", **kw) -> dict:
    """counties_nc.nc_ecourts_lis_pendens: an IRS federal tax lien recorded in District Court
    (56 Buncombe rows; its derived aging blocks say current, so no property-tax claim)."""
    row = {"state": "NC", "county": county, "source": "counties_nc.nc_ecourts_lis_pendens",
           "listing_type": "tax_lien", "parcel_id": "9714979402",
           "street_address": "8 EXAMPLE FIELDS DR", "zip_code": "28701", "owner_name": "LEE EXAMPLE",
           "case_number": "26M009999-100",
           "description": f"CV - Federal Tax Lien judgment in {county} District Court: 26M009999-100",
           "raw": {"two_year_delinquent": {"is_two_year_plus": False, "tax_year": None,
                                           "source": "default"},
                   "tax_aging_surfaced": {"tax_year": None, "years_delinquent": 0,
                                          "status": "current", "source": "default"},
                   "amount_owed": {"value": 208500.0, "source": "assessed_value",
                                   "label": "Tax-assessed value (not debt)", "is_actual_debt": False},
                   "nc_ecourts": {"cause": "CV - Federal Tax Lien", "judgmentType": "Recorded",
                                  "civilJudgmentStatus": "Active", "caseCategoryKey": "CV",
                                  "location": f"{county} District Court"}}}
    row.update(kw)
    return row


def ecourts_judgment_row() -> dict:
    """nc_ecourts_judgments: the same index, no property on the row (68 Buncombe rows)."""
    return {"state": "NC", "county": "Buncombe", "source": "nc_ecourts_judgments",
            "listing_type": "tax_lien", "parcel_id": None, "case_number": "25M009998-100",
            "defendant": "EXAMPLE GRADING LLC",
            "raw": {"nc_ecourts": {"source": "nc_ecourts_judgments",
                                   "cause_of_action": "CV - Federal Tax Lien",
                                   "court_name": "Buncombe District Court", "county": "Buncombe",
                                   "judgment_type": "Recorded", "civil_judgment_status": "Active"}}}


def roll_row(**kw) -> dict:
    """counties_nc.buncombe_delinquent_tax: the county's own delinquent roll (a property-tax claim)."""
    row = {"state": "NC", "county": "Buncombe", "source": "counties_nc.buncombe_delinquent_tax",
           "listing_type": "tax_lien", "parcel_id": "867991795700000",
           "street_address": "40 EXAMPLE WALLOW TRL", "zip_code": "28748",
           "owner_name": "KIM A EXAMPLE", "judgment_amount": 1024.17,
           "raw": {"buncombe_delinquent_tax": dict(ROLL_BLOCK, tax_year=2025),
                   "tax_owed": {"balance": 775.59, "kind": "delinquent_tax", "year": 2025},
                   "amount_owed": {"value": 775.59, "source": "tax_owed", "is_actual_debt": True}}}
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# the guard: which rows tax_lien_buncombe covers
# ---------------------------------------------------------------------------

def test_another_liens_tax_lien_row_is_not_covered():
    assert not tlb.applies(liensnc_row())
    assert not tlb.applies(liensnc_row(source="counties_generic.liensnc"))
    assert not tlb.applies(ecourts_row())             # aging blocks present but "current"
    assert not tlb.applies(ecourts_judgment_row())


def test_it_stays_covered_with_a_property_tax_claim_of_its_own():
    """A county roll block merged into the row (16 board rows) or a real delinquency flag."""
    with_roll = liensnc_row()
    with_roll["raw"]["buncombe_delinquent_tax"] = dict(ROLL_BLOCK)
    assert tlb.applies(with_roll)
    with_multi = liensnc_row(source="counties_generic.liensnc")
    with_multi["raw"]["multi_year_delinquent_tax"] = dict(MULTI_YEAR_BLOCK)
    assert tlb.applies(with_multi)
    flagged = ecourts_row()
    flagged["raw"]["two_year_delinquent"] = {"is_two_year_plus": True, "tax_year": 2024}
    assert tlb.applies(flagged)


def test_the_rest_of_the_selection_is_unchanged():
    assert tlb.applies(roll_row())
    assert tlb.applies(roll_row(source="counties_generic.arcgis_distress.buncombe_unpaid_bills",
                                raw={}))
    # a county roll block on a row that is not typed tax_lien was never covered and still is not
    # (495 asheville_str_permits rows carry one); nor is a tax_sale row (21, counties_nc.buncombe_tax)
    str_permit = {"state": "NC", "county": "Buncombe", "source": "counties_nc.asheville_str_permits",
                  "listing_type": "unknown", "raw": {"buncombe_delinquent_tax": dict(ROLL_BLOCK)}}
    assert not tlb.applies(str_permit)
    assert not tlb.applies(roll_row(source="counties_nc.buncombe_tax", listing_type="tax_sale"))
    # the two derived flags still cover any row type
    assert tlb.applies({"state": "NC", "county": "Buncombe", "listing_type": "unknown",
                        "raw": {"tax_aging_surfaced": {"status": "delinquent", "years_delinquent": 1}}})


def test_the_three_verifiers_never_cover_one_row_twice():
    rows = [liensnc_row(), ecourts_row(), ecourts_judgment_row(), roll_row(),
            ecourts_row(county="Henderson"), dict(roll_row(), county="Henderson")]
    for r in rows:
        assert sum(m.applies(r) for m in (tlb, tlp, tlq)) <= 1


# ---------------------------------------------------------------------------
# the mixed-row downgrade, on real county pages
# ---------------------------------------------------------------------------

def page(name: str) -> str:
    return gzip.decompress((FIX / f"buncombe_tax_{name}.html.gz").read_bytes()).decode("utf-8")


def served(*paths: str) -> dict:
    return {f"{tlb.BASE}/{p}": page(p.replace("/", "_")) for p in paths}


def run(row, fetcher):
    return asyncio.run(tlb.verify(row, fetcher, today=TODAY))


def _covered_liensnc(parcel: str) -> dict:
    row = liensnc_row(parcel_id=parcel)
    row["raw"]["buncombe_delinquent_tax"] = dict(ROLL_BLOCK, tax_year=2025)
    assert tlb.applies(row)
    return row


REFUTED_PAGES = ("Parcel/Details/968605392600000", "Bill/Details/0000667232-2025-2025-0000-00")
STALE_PAGES = ("Parcel/Details/963962247000000", "Bill/Details/0000739533-2025-2025-0000-00")


@pytest.mark.parametrize("pages,parcel,verdict", [
    (REFUTED_PAGES, "9686-05-3926-00000", "refuted"),   # the 2025 levy paid on time
    (STALE_PAGES, "963962247000000", "stale"),          # the 2025 levy paid 2026-09-03 with interest
])
def test_refuted_or_stale_on_another_liens_row_is_unconfirmed(pages, parcel, verdict):
    genuine = run(roll_row(parcel_id=parcel), ReplayFetcher(served(*pages)))
    assert genuine.verdict == verdict                    # the property-tax answer itself
    r = run(_covered_liensnc(parcel), ReplayFetcher(served(*pages)))
    assert r.verdict == "unconfirmed"
    ev = r.evidence
    assert ev["reason"] == "other_lien_listing" and ev["property_tax_verdict"] == verdict
    assert ev["listing_claim_source"] == "liensnc"
    assert ev["bills_checked"] == genuine.evidence["bills_checked"]      # the answer is kept
    assert r.verifier_version == tlb.VERSION == "v3"


def test_confirmed_on_another_liens_row_passes_through():
    row = _covered_liensnc("9686540826")
    r = run(row, ReplayFetcher(served("Parcel/Details/968654082600000")))
    assert r.verdict == "confirmed" and "property_tax_verdict" not in r.evidence


@pytest.mark.parametrize("mod", [tlb, tlp, tlq])
def test_one_shared_rule_for_all_three_verifiers(mod):
    for row in (liensnc_row(), ecourts_row(), {"source": "counties_sc.sc_dew_lien_registry",
                                                "listing_type": "tax_lien"}):
        for verdict in ("refuted", "stale"):
            r = mod._res(verdict, {"total_delinquent": 0}, row)
            assert r.verdict == "unconfirmed"
            assert r.evidence["property_tax_verdict"] == verdict
            assert r.evidence["reason"] == "other_lien_listing"
        assert mod._res("confirmed", {}, row).verdict == "confirmed"
    assert mod._res("refuted", {}, roll_row()).verdict == "refuted"
    assert mod.GOVERNS == tc.GOVERNS


# ---------------------------------------------------------------------------
# the offline ledger migration (v2 entries written before the guard)
# ---------------------------------------------------------------------------

def _entry(key, source, verdict, *, verifier="tax_lien_buncombe", version="v2",
           checked="2026-10-06T04:23:09Z", claimed=()):
    """A ledger entry as the 10/6 sweep wrote it (docs/handoff/verification/tax_lien.json),
    owner names and the street dropped."""
    ev = {"url": f"{tlb.BASE}/Parcel/Details/060629204000000", "pin": "060629204000000",
          "latest_levy_year": 2026, "delinquent_by_year": {}, "total_delinquent": 0,
          "years_delinquent": 0, "not_yet_delinquent_due": {"2026": 5787.21},
          "claimed_years": list(claimed), "owner_match": "same",
          "bills_checked": [{"paid_late": verdict == "stale", "year": 2025,
                             "url": f"{tlb.BASE}/Bill/Details/0000753537-2025-2025-0000-00"}]}
    if verdict == "confirmed":
        ev.update(delinquent_by_year={"2019": 1261.52}, total_delinquent=1261.52,
                  years_delinquent=1, under_500=False)
    rec = {"signal": "tax_lien", "verdict": verdict, "evidence": ev, "source": tlb.SOURCE,
           "checked_at": checked, "verifier_version": version, "verifier": verifier}
    pid = key.rsplit(":", 1)[-1]
    return {"keys": [key], "checks": 1, "first_checked_at": checked, "history": [],
            "last_attempt": {"verdict": verdict, "checked_at": checked}, "latest": rec,
            "governs": ["tax_lien", "tax_sale", "tax_lien_chronic", "recorded_debt:tax"],
            "ttl_days": 30.0,
            "row": {"state": "NC", "county": "Buncombe", "listing_type": "tax_lien",
                    "parcel_id": pid, "source": source}}


def _ledger() -> L.Ledger:
    rows = {
        "parcel:NC:buncombe:0606292040": _entry("parcel:NC:buncombe:0606292040", "liensnc", "refuted"),
        "parcel:NC:buncombe:8792236335": _entry("parcel:NC:buncombe:8792236335",
                                                "counties_generic.liensnc", "stale", claimed=(2026,)),
        "parcel:NC:buncombe:062577987400000": _entry("parcel:NC:buncombe:062577987400000",
                                                     "liensnc", "confirmed"),
        "parcel:NC:buncombe:061605416400000": _entry("parcel:NC:buncombe:061605416400000",
                                                     "counties_nc.buncombe_delinquent_tax",
                                                     "refuted", claimed=(2025,)),
        "parcel:NC:buncombe:0710500622": _entry("parcel:NC:buncombe:0710500622", "liensnc",
                                                "unconfirmed"),
        "parcel:NC:henderson:9528188660": dict(
            _entry("parcel:NC:henderson:9528188660", "counties_nc.nc_ecourts_lis_pendens", "stale",
                   verifier="tax_lien_ptscloud", version="v1"),
            row={"state": "NC", "county": "Henderson", "listing_type": "tax_lien",
                 "source": "counties_nc.nc_ptscloud_delinquent_tax"}),
    }
    return L.Ledger("tax_lien", copy.deepcopy(rows))


def test_migration_downgrades_exactly_the_other_lien_refuted_and_stale_entries():
    led = _ledger()
    before = copy.deepcopy(led.rows)
    lines = tc.downgrade_other_lien_entries(led, "tax_lien_buncombe", tlb.VERSION, NOW)
    assert sorted((ln["key"], ln["from_verdict"]) for ln in lines) == [
        ("parcel:NC:buncombe:0606292040", "refuted"), ("parcel:NC:buncombe:8792236335", "stale")]
    for ln in lines:
        e, old = led.rows[ln["key"]], before[ln["key"]]
        lat = e["latest"]
        # exactly what the verifier now publishes for that row: the shared rule's output
        assert lat["verdict"] == "unconfirmed" and lat["verifier_version"] == "v3"
        assert lat["evidence"]["property_tax_verdict"] == old["latest"]["verdict"]
        assert lat["evidence"]["reason"] == "other_lien_listing"
        assert lat["evidence"]["listing_claim_source"] == old["row"]["source"]
        assert lat["evidence"]["bills_checked"] == old["latest"]["evidence"]["bills_checked"]
        assert lat["checked_at"] == core.iso_z(NOW)
        assert e["history"][0] == {"verdict": old["latest"]["verdict"],
                                   "checked_at": old["latest"]["checked_at"],
                                   "verifier": "tax_lien_buncombe", "verifier_version": "v2"}
        assert e["migrated"]["from_checked_at"] == old["latest"]["checked_at"]
        assert e["keys"] == old["keys"] and e["row"] == old["row"]
    # everything else is untouched: a confirmed other-lien entry, a genuine roll entry, an
    # unconfirmed one, another verifier's
    for k in set(before) - {ln["key"] for ln in lines}:
        assert led.rows[k] == before[k]
    assert tc.downgrade_other_lien_entries(led, "tax_lien_buncombe", tlb.VERSION, NOW) == []


def test_the_version_bump_is_what_keeps_the_downgrade_through_a_merge():
    """The sweep merges the file on disk back into its copy (verification_sweep._save). A copy
    loaded before the migration must not bring the refuted answer back, in either direction."""
    old = _ledger()
    new = _ledger()
    tc.downgrade_other_lien_entries(new, "tax_lien_buncombe", tlb.VERSION, NOW)
    k = "parcel:NC:buncombe:0606292040"
    a = copy.deepcopy(new).merge_from(copy.deepcopy(old))
    b = copy.deepcopy(old).merge_from(copy.deepcopy(new))
    assert a.rows[k]["latest"]["verdict"] == b.rows[k]["latest"]["verdict"] == "unconfirmed"
    # without the bump (same version) a decisive answer beats the unconfirmed one: reverted
    same = dict(new.rows[k]["latest"], verifier_version="v2")
    assert L._better(old.rows[k]["latest"], same)


def test_after_the_migration_a_covered_row_is_retried_and_v2_entries_are_due():
    v = from_module(tlb)
    led = _ledger()
    tc.downgrade_other_lien_entries(led, "tax_lien_buncombe", tlb.VERSION, NOW)
    migrated = led.rows["parcel:NC:buncombe:0606292040"]
    assert L.is_due(migrated, v, NOW) == (False, "retry")
    assert L.is_due(migrated, v, NOW + timedelta(days=tlb.RETRY_DAYS)) == (True, "retry")
    assert L.is_due(led.rows["parcel:NC:buncombe:061605416400000"], v, NOW) == (True, "version")


def test_apply_attaches_the_migrated_answer_and_it_suppresses_nothing(tmp_path):
    led = _ledger()
    tc.downgrade_other_lien_entries(led, "tax_lien_buncombe", tlb.VERSION, NOW)
    led.save(tmp_path / "tax_lien.json")
    li = Listing.model_validate(dict(liensnc_row(parcel_id="0606292040",
                                                 street_address="62 Example Leaf Rd"),
                                     source_url="https://apps.liensnc.com/x"))
    A.apply_verification([li], tmp_path, now=NOW)
    (rec,) = li.raw["verification"]
    assert rec["verdict"] == "unconfirmed" and rec["governs"] == list(tc.GOVERNS)
    assert core.suppressed_scorer_signals(li.raw, NOW) == set()


# ---------------------------------------------------------------------------
# the scorer: a property-tax verdict ends only property-tax-derived tax_lien / tax_sale
# ---------------------------------------------------------------------------

def _vrec(verdict="refuted", governs=tc.GOVERNS, verifier="tax_lien_ptscloud"):
    checked = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return {"signal": "tax_lien", "verdict": verdict, "evidence": {}, "source": "x",
            "checked_at": core.iso_z(checked), "verifier_version": "v1", "verifier": verifier,
            "expires_at": core.iso_z(checked + timedelta(days=30)), "governs": list(governs)}


def _li(row: dict, verification=None) -> Listing:
    d = copy.deepcopy(row)
    if verification is not None:
        d["raw"]["verification"] = verification
    d.setdefault("source_url", "https://example.invalid/row")
    return Listing.model_validate(d)


def _names(li):
    return {n for n, _c, _w in ds._signals_for(li, today=TODAY)}


#: Henderson NC, a ptscloud tenant: an IRS lien row, and an NCDOR Certificate of Tax Liability
#: row carrying the parcel's PROPERTY-tax balance cross-referenced from the roll
IRS_ROW = ecourts_row(county="Henderson", parcel_id="9528188660")
NCDOR_ROW = ecourts_row(
    county="Henderson", parcel_id="9568788616",
    description="CV - NC Certificate of Tax Liability judgment in Henderson District Court: 26M009997-440",
    raw={"tax_owed": {"balance": 1820.38, "kind": "delinquent_tax",
                      "source": "counties_nc.nc_ptscloud_delinquent_tax", "year": 2025,
                      "basis": "parcel_cross_ref"},
         "amount_owed": {"value": 742.53, "source": "tax_owed",
                         "label": "Delinquent property tax owed", "is_actual_debt": True},
         "nc_ecourts": {"cause": "CV - NC Certificate of Tax Liability",
                        "civilJudgmentStatus": "Active"}})
#: Spartanburg SC, a qPayBill county: an SC DEW unemployment-insurance tax lien
DEW_ROW = {"state": "SC", "county": "Spartanburg", "source": "counties_sc.sc_dew_lien_registry",
           "listing_type": "tax_lien", "parcel_id": "2-44-01-021.02",
           "street_address": "99 Example Springs Rd", "city": "Boiling Springs", "zip_code": "29316",
           "owner_name": "EXAMPLE & SONS LLC", "description": "SC DEW UI-tax lien — balance $3,576",
           "judgment_amount": 3575.68,
           "raw": {"tax_owed": {"balance": 628.86, "kind": "delinquent_tax",
                                "source": "counties_sc.sc_dew_lien_registry", "year": None,
                                "basis": "own_record"},
                   "amount_owed": {"value": 3575.68, "source": "judgment",
                                   "label": "Judgment / indebtedness", "confidence": "high",
                                   "is_actual_debt": True},
                   "sc_state_tax_lien": {"owner": "EXAMPLE & SONS LLC", "balance": 628.86,
                                         "source": "sc_dew_lien_registry"}}}


@pytest.mark.parametrize("verdict", ["refuted", "stale"])
def test_the_property_tax_row_still_loses_its_tax_signals(verdict):
    base = _names(_li(roll_row()))
    assert {"tax_lien", "recorded_debt"} <= base
    after = _names(_li(roll_row(), [_vrec(verdict, verifier="tax_lien_buncombe")]))
    assert "tax_lien" not in after and "recorded_debt" not in after


@pytest.mark.parametrize("row", [IRS_ROW, NCDOR_ROW, DEW_ROW], ids=["irs", "ncdor", "sc_dew"])
def test_another_liens_row_on_the_parcel_keeps_its_tax_lien(row):
    assert "tax_lien" in _names(_li(row))
    assert "tax_lien" in _names(_li(row, [_vrec("refuted")]))
    assert "tax_lien" in _names(_li(row, [_vrec("stale")]))
    # a verdict that governs the plain name (any other verifier's) still ends it: generic rule
    assert "tax_lien" not in _names(_li(row, [_vrec("refuted", governs=("tax_lien",))]))


def test_recorded_debt_tax_still_reads_the_debt_source():
    # the NCDOR row's debt IS the parcel's property-tax balance (cross-referenced): it goes
    assert "recorded_debt" in _names(_li(NCDOR_ROW))
    assert "recorded_debt" not in _names(_li(NCDOR_ROW, [_vrec("refuted")]))
    # the DEW lien's balance is a judgment-sourced amount_owed: it stays
    assert "recorded_debt" in _names(_li(DEW_ROW, [_vrec("refuted")]))


def test_tax_sale_follows_the_same_rule():
    sale = roll_row(source="counties_nc.buncombe_tax", listing_type="tax_sale")
    assert "tax_sale" in _names(_li(sale))
    assert "tax_sale" not in _names(_li(sale, [_vrec("refuted", verifier="tax_lien_buncombe")]))


def test_a_parcel_group_keeps_the_other_liens_signal():
    """score_board unions a parcel's rows. The ledger is per property, so both rows carry the
    property-tax verdict; the group still scores the IRS lien."""
    on_parcel = {"county": "Henderson", "parcel_id": "9528188660",
                 "street_address": IRS_ROW["street_address"]}
    roll = _li(dict(roll_row(), **on_parcel), [_vrec("refuted")])
    irs = _li(IRS_ROW, [_vrec("refuted")])
    alone = _li(dict(roll_row(), county="Henderson", parcel_id="9528188661"), [_vrec("refuted")])
    ds.score_board([roll, irs, alone], previous_path=None)
    assert "tax_lien" in roll.raw["distress_stack"]["signals"]
    assert "tax_lien" in irs.raw["distress_stack"]["signals"]
    assert "tax_lien" not in (alone.raw["distress_stack"].get("signals") or [])


def test_lead_signal_facets():
    sc = _li(dict(DEW_ROW, raw=dict(DEW_ROW["raw"], sc_tax_delinquent={"year": 2025})))
    assert {"tax_lien", "recorded_debt"} <= _facet_signals(sc, TODAY)
    sc.raw["verification"] = [_vrec("stale", verifier="tax_lien_qpaybill")]
    after = _facet_signals(sc, TODAY)
    assert "tax_lien" not in after                 # sc_tax_delinquent is the property-tax roll
    assert "recorded_debt" in after                # the DEW judgment amount is not tax_owed
    sc.raw["verification"] = [_vrec("confirmed", verifier="tax_lien_qpaybill")]
    assert {"tax_lien", "recorded_debt"} <= _facet_signals(sc, TODAY)
