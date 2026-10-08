"""Another lien's tax_lien row is not a property-tax claim (tax_lien_buncombe v3, _tax_common).

Rows typed tax_lien by a federal / state / lien-agent source (liensnc lien-agent filings, NC
eCourts "Federal Tax Lien" and "NC Certificate of Tax Liability" judgments, SC DEW and DOR liens)
were checked by tax_lien_buncombe against the county's PROPERTY-tax record, and a paid tax bill
refuted them. Covered here, on real rows from the 2026-10-06 board (board_stream, read-only):
names, filers, case and entry numbers and street addresses made up, every field and raw block
shape and every amount as the board carries it; the county pages are the real captures in
tests/fixtures/verification/ (owner names made up there too):

  * the guard: which Buncombe rows the verifier covers (1,078 board rows drop out, 16 that carry
    a county roll block of their own stay, nothing else changes);
  * a MIXED row (another lien's listing type plus a property-tax claim of its own) gets the
    county's verdict as it is; the retired downgrade to unconfirmed is gone from all three;
  * the scorer: a property-tax verdict ends tax_lien / tax_sale only where the row's claim is a
    property-tax one (GOVERNS "tax_lien:property_tax"), so the lien keeps its own signal, on its
    own row and on another row of the parcel, while the property-tax-derived signals end;
  * the offline restore of the ledger entries the retired downgrade wrote.
No network.
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper.enrichment_lead_signals import _facet_signals, _signal_stack
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
    # (495 asheville_str_permits rows carry one)
    str_permit = {"state": "NC", "county": "Buncombe", "source": "counties_nc.asheville_str_permits",
                  "listing_type": "unknown", "raw": {"buncombe_delinquent_tax": dict(ROLL_BLOCK)}}
    assert not tlb.applies(str_permit)
    # 2026-10-09 (audit tax_checkers_2): the call-ready gate waits on a county check for a tax_sale
    # row of a county source and for a row with a delinquent-tax balance of its own, so the
    # verifier covers them (before, 159 Buncombe rows waited on a check nothing would make)
    assert tlb.applies(roll_row(source="counties_nc.buncombe_tax", listing_type="tax_sale"))
    no_balance = roll_row(source="counties_nc.buncombe_tax", listing_type="tax_sale")
    no_balance["raw"].pop("tax_owed")
    assert tlb.applies(no_balance)
    assert tlb.applies({"state": "NC", "county": "Buncombe", "listing_type": "unknown", "source": "x",
                        "raw": {"tax_owed": {"balance": 50.0, "kind": "delinquent_tax"}}})
    # the two derived flags still cover any row type
    assert tlb.applies({"state": "NC", "county": "Buncombe", "listing_type": "unknown",
                        "raw": {"tax_aging_surfaced": {"status": "delinquent", "years_delinquent": 1}}})


def test_the_three_verifiers_never_cover_one_row_twice():
    rows = [liensnc_row(), ecourts_row(), ecourts_judgment_row(), roll_row(),
            ecourts_row(county="Henderson"), dict(roll_row(), county="Henderson")]
    for r in rows:
        assert sum(m.applies(r) for m in (tlb, tlp, tlq)) <= 1


# ---------------------------------------------------------------------------
# mixed rows: the county's verdict is published as it is (real county pages)
# ---------------------------------------------------------------------------

def page(name: str) -> str:
    return gzip.decompress((FIX / f"buncombe_tax_{name}.html.gz").read_bytes()).decode("utf-8")


RECHECK = json.loads(gzip.decompress((FIX / "buncombe_tax_recheck.json.gz").read_bytes()))


def served(*paths: str) -> dict:
    """The county pages by path: the 2026-10-06 recheck captures (one JSON of {url: page}), else
    the 2026-10-05 per-page captures."""
    out = {}
    for p in paths:
        url = f"{tlb.BASE}/{p}"
        out[url] = RECHECK[url] if url in RECHECK else page(p.replace("/", "_"))
    return out


def run(row, fetcher):
    return asyncio.run(tlb.verify(row, fetcher, today=TODAY))


def irs_mixed_row(parcel: str = "9686-05-3926-00000") -> dict:
    """nc_ecourts_judgments, Buncombe: an IRS federal tax lien judgment on a parcel, into which
    the county roll's block (and the multi-year unpaid-bill layers) merged, so it carries the
    parcel's PROPERTY-tax balance as tax_owed (2 such Buncombe rows, 2 in Henderson). Case
    number made up, every block as the board carries it."""
    return {"state": "NC", "county": "Buncombe", "source": "nc_ecourts_judgments",
            "listing_type": "tax_lien", "parcel_id": parcel, "case_number": "26M009996-100",
            "defendant": "EXAMPLE, ROBIN",
            "raw": {"nc_ecourts": {"source": "nc_ecourts_judgments",
                                   "cause_of_action": "CV - Federal Tax Lien",
                                   "court_name": "Buncombe District Court", "county": "Buncombe",
                                   "judgment_type": "Recorded", "civil_judgment_status": "Active"},
                    "buncombe_delinquent_tax": {"pin": "971265893300000", "principal_tax_due": 225.36,
                                                "tax_year": 2025},
                    "multi_year_delinquent_tax": dict(MULTI_YEAR_BLOCK, per_year={"2025": 266.38,
                                                                                  "2026": 247.02}),
                    "tax_owed": {"balance": 225.36, "kind": "delinquent_tax",
                                 "source": "nc_ecourts_judgments", "year": 2025,
                                 "basis": "own_record", "years_delinquent": 2},
                    "amount_owed": {"value": 225.36, "source": "tax_owed",
                                    "label": "Delinquent property tax owed", "confidence": "high",
                                    "is_actual_debt": True}}}


def dew_mixed_row() -> dict:
    """counties_sc.sc_dew_lien_registry, Colleton SC: a DEW unemployment-insurance tax lien whose
    row also carries the county's qPayBill delinquent-roll block for the parcel (20 such rows).
    Its tax_owed is the DEW balance; the DEW amount is a judgment-sourced amount_owed."""
    return {"state": "SC", "county": "Colleton", "source": "counties_sc.sc_dew_lien_registry",
            "listing_type": "tax_lien", "parcel_id": "163-07-00-075.000",
            "street_address": "117 EXAMPLE ST", "owner_name": "EXAMPLE FUNERAL SERVICES LLC",
            "description": "SC DEW UI-tax lien \u2014 balance $8,231", "judgment_amount": 8231.27,
            "raw": {"tax_owed": {"balance": 8231.27, "kind": "delinquent_tax",
                                 "source": "counties_sc.sc_dew_lien_registry", "year": None,
                                 "basis": "own_record", "years_delinquent": 1},
                    "amount_owed": {"value": 8231.27, "source": "judgment",
                                    "label": "Judgment / indebtedness", "confidence": "high",
                                    "is_actual_debt": True},
                    "sc_state_tax_lien": {"balance": 8231.27, "source": "sc_dew_lien_registry"},
                    "qpaybill_roll": {"identification_no": "163-07-00-075.000",
                                      "is_account_id_not_parcel": False, "county": "Colleton",
                                      "subdomain": "colleton", "balance_owed": 16923.86,
                                      "years_unpaid": ["2025"], "years_delinquent": 1,
                                      "is_two_year_plus": False, "statuses": ["Unpaid"],
                                      "notice_numbers": ["013300001", "013400001"], "rows": 2,
                                      "all_unpaid_years": ["2025", "2026"]}}}


#: 2614 Old Fort Rd (PIN 0646441079): nothing owed, the 2025 levy paid on time (2025-11-19). The
#: 3 Eastcrest Dr pair these tests used for `refuted` through v3 is not one: its 2024 and 2015
#: bills are in legal collection (See Legal), an unpaid balance (v4).
REFUTED_PAGES = ("Parcel/Details/064644107900000", "Bill/Details/0000768692-2025-2025-0000-00")
STALE_PAGES = ("Parcel/Details/963962247000000", "Bill/Details/0000739533-2025-2025-0000-00")


def test_the_real_mixed_rows_are_covered_by_their_county_verifier():
    assert tc.other_lien_listing(irs_mixed_row()) and tlb.applies(irs_mixed_row())
    assert tc.other_lien_listing(dew_mixed_row()) and tlq.applies(dew_mixed_row())
    assert not tlb.applies(dew_mixed_row()) and not tlq.applies(irs_mixed_row())


@pytest.mark.parametrize("pages,parcel,verdict,street", [
    (REFUTED_PAGES, "0646441079", "refuted", "2614 Old Fort Rd"),    # the 2025 levy paid on time
    (STALE_PAGES, "963962247000000", "stale", "40 Boone St"),        # the 2025 levy paid 2026-09-03 with interest
])
def test_a_mixed_row_gets_the_county_verdict_as_it_is(pages, parcel, verdict, street):
    genuine = run(roll_row(parcel_id=parcel, street_address=street), ReplayFetcher(served(*pages)))
    r = run(irs_mixed_row(parcel), ReplayFetcher(served(*pages)))
    assert genuine.verdict == r.verdict == verdict
    assert not {"property_tax_verdict", "listing_claim_source", "reason"} & set(r.evidence)
    assert r.evidence["bills_checked"] == genuine.evidence["bills_checked"]
    assert r.verifier_version == tlb.VERSION == "v6"


def test_confirmed_on_a_mixed_row():
    r = run(irs_mixed_row("9686540826"), ReplayFetcher(served("Parcel/Details/968654082600000")))
    assert r.verdict == "confirmed"


@pytest.mark.parametrize("mod", [tlb, tlp, tlq])
def test_no_verifier_downgrades_any_more(mod):
    for verdict in ("refuted", "stale", "confirmed"):
        assert mod._res(verdict, {"total_delinquent": 0}).verdict == verdict
    assert mod.GOVERNS == tc.GOVERNS
    assert not hasattr(tc, "other_lien_downgrade")


# ---------------------------------------------------------------------------
# the offline restore of what the retired downgrade wrote to the ledger
# ---------------------------------------------------------------------------

MIGRATED_AT = "2026-10-06T07:54:33Z"


def _entry(key, source, verdict, *, verifier="tax_lien_buncombe", version="v3",
           checked="2026-10-06T04:23:09Z", claimed=(), downgraded=None, migrated=False):
    """A ledger entry as docs/handoff/verification/tax_lien.json holds it (names already
    gone, the street dropped). downgraded="refuted"/"stale": the answer the retired downgrade
    published as unconfirmed; migrated=True: by the 2026-10-06 offline migration (c1abaf1d),
    which also moved checked_at to the migration time and kept the check's own in `migrated`."""
    ev = {"url": f"{tlb.BASE}/Parcel/Details/060629204000000", "pin": "060629204000000",
          "latest_levy_year": 2026, "delinquent_by_year": {}, "total_delinquent": 0,
          "years_delinquent": 0, "not_yet_delinquent_due": {"2026": 5787.21},
          "claimed_years": list(claimed), "owner_match": "same",
          "bills_checked": [{"paid_late": (downgraded or verdict) == "stale", "year": 2025,
                             "url": f"{tlb.BASE}/Bill/Details/0000753537-2025-2025-0000-00"}]}
    if verdict == "confirmed":
        ev.update(delinquent_by_year={"2019": 1261.52}, total_delinquent=1261.52,
                  years_delinquent=1, under_500=False)
    if downgraded:
        ev.update(property_tax_verdict=downgraded, reason="other_lien_listing",
                  listing_claim_source=source)
    rec = {"signal": "tax_lien", "verdict": verdict, "evidence": ev, "source": tlb.SOURCE,
           "checked_at": MIGRATED_AT if migrated else checked, "verifier_version": version,
           "verifier": verifier}
    pid = key.rsplit(":", 1)[-1]
    e = {"keys": [key], "checks": 1, "first_checked_at": checked, "history": [],
         "last_attempt": {"verdict": downgraded or verdict, "checked_at": checked}, "latest": rec,
         "governs": ["tax_lien", "tax_sale", "tax_lien_chronic", "recorded_debt:tax"],
         "ttl_days": 30.0,
         "row": {"state": "NC", "county": "Buncombe", "listing_type": "tax_lien",
                 "parcel_id": pid, "source": source}}
    if migrated:
        e["history"] = [{"verdict": downgraded, "checked_at": checked,
                         "verifier": verifier, "verifier_version": "v2"}]
        e["migrated"] = {"how": "offline: _tax_common.other_lien_downgrade, no request",
                         "at": MIGRATED_AT, "from_version": "v2", "from_verdict": downgraded,
                         "from_checked_at": checked}
    return e


def _ledger() -> L.Ledger:
    k = "parcel:NC:buncombe:"
    rows = {
        k + "0606292040": _entry(k + "0606292040", "liensnc", "unconfirmed", downgraded="refuted",
                                 migrated=True),
        k + "8792236335": _entry(k + "8792236335", "counties_generic.liensnc", "unconfirmed",
                                 downgraded="stale", migrated=True, claimed=(2026,),
                                 checked="2026-10-06T04:24:00Z"),
        k + "062577987400000": _entry(k + "062577987400000", "liensnc", "confirmed"),
        k + "061605416400000": _entry(k + "061605416400000", "counties_nc.buncombe_delinquent_tax",
                                      "refuted", version="v2", claimed=(2025,)),
        k + "0710500622": _entry(k + "0710500622", "liensnc", "unconfirmed"),
        # qpaybill's own live downgrade (v1, never migrated): an SC DEW row with a roll block
        "parcel:SC:colleton:163070007500": dict(
            _entry("parcel:SC:colleton:163070007500", "counties_sc.sc_dew_lien_registry",
                   "unconfirmed", downgraded="stale", verifier="tax_lien_qpaybill", version="v1",
                   checked="2026-10-06T07:18:40Z"),
            row={"state": "SC", "county": "Colleton", "listing_type": "tax_lien",
                 "source": "counties_sc.sc_dew_lien_registry"}),
    }
    return L.Ledger("tax_lien", copy.deepcopy(rows))


def test_restore_gives_back_exactly_the_downgraded_answers():
    led = _ledger()
    before = copy.deepcopy(led.rows)
    lines = tc.restore_property_tax_verdicts(led, NOW)
    assert sorted((ln["key"], ln["verdict"], ln["version"]) for ln in lines) == [
        ("parcel:NC:buncombe:0606292040", "refuted", "v3"),
        ("parcel:NC:buncombe:8792236335", "stale", "v3"),
        ("parcel:SC:colleton:163070007500", "stale", "v1")]
    for ln in lines:
        e, old = led.rows[ln["key"]], before[ln["key"]]
        lat, olat = e["latest"], old["latest"]
        assert lat["verdict"] == olat["evidence"]["property_tax_verdict"]
        assert lat["verifier_version"] == olat["verifier_version"]          # no bump
        # the county check's own time, not the migration's
        assert lat["checked_at"] == old.get("migrated", {}).get("from_checked_at", olat["checked_at"])
        assert lat["checked_at"] == old["last_attempt"]["checked_at"]
        # the evidence is the answer's, minus what the downgrade added
        assert lat["evidence"] == {k: v for k, v in olat["evidence"].items()
                                   if k not in ("property_tax_verdict", "reason",
                                                "listing_claim_source")}
        assert e["history"][0] == {k: olat[k] for k in ("verdict", "checked_at", "verifier",
                                                        "verifier_version")}
        assert e["history"][1:] == old["history"]
        assert e["migrated"]["restored"]["from_checked_at"] == olat["checked_at"]
        assert {k: e[k] for k in ("keys", "row", "checks", "first_checked_at", "last_attempt")} \
            == {k: old[k] for k in ("keys", "row", "checks", "first_checked_at", "last_attempt")}
    for k in set(before) - {ln["key"] for ln in lines}:
        assert led.rows[k] == before[k]
    assert tc.restore_property_tax_verdicts(led, NOW) == []


def test_no_version_bump_is_needed_to_keep_the_restore_through_a_merge():
    """The sweep merges the file on disk back into its copy (verification_sweep._save). A copy
    holding the downgraded answer (same version, later checked_at) never wins over the
    restored decisive one, in either direction."""
    old, new = _ledger(), _ledger()
    tc.restore_property_tax_verdicts(new, NOW)
    for k in ("parcel:NC:buncombe:0606292040", "parcel:SC:colleton:163070007500"):
        assert old.rows[k]["latest"]["checked_at"] >= new.rows[k]["latest"]["checked_at"]
        a = copy.deepcopy(new).merge_from(copy.deepcopy(old))
        b = copy.deepcopy(old).merge_from(copy.deepcopy(new))
        assert a.rows[k]["latest"] == b.rows[k]["latest"] == new.rows[k]["latest"]


def test_after_the_restore_the_verdict_is_due_on_its_own_ttl():
    # the entries are v3 answers: judge their TTL as the v3 verifier would (v4's bump alone makes
    # every v3 entry due as "version", which is the point of the bump)
    v = dataclasses.replace(from_module(tlb), version="v3")
    led = _ledger()
    tc.restore_property_tax_verdicts(led, NOW)
    e = led.rows["parcel:NC:buncombe:0606292040"]
    checked = core.parse_ts(e["latest"]["checked_at"])
    assert L.is_due(e, v, checked + timedelta(days=29)) == (False, "ttl")
    assert L.is_due(e, v, checked + timedelta(days=tlb.TTL_DAYS)) == (True, "ttl")
    assert L.is_due(led.rows["parcel:NC:buncombe:061605416400000"], v, NOW) == (True, "version")


def test_apply_attaches_the_restored_answer_and_it_ends_only_property_tax_signals(tmp_path):
    led = _ledger()
    tc.restore_property_tax_verdicts(led, NOW)
    led.save(tmp_path / "tax_lien.json")
    li = Listing.model_validate(dict(liensnc_row(parcel_id="0606292040",
                                                 street_address="62 Example Leaf Rd"),
                                     source_url="https://apps.liensnc.com/x"))
    A.apply_verification([li], tmp_path, now=NOW)
    (rec,) = li.raw["verification"]
    assert rec["verdict"] == "refuted" and rec["governs"] == list(tc.GOVERNS)
    assert core.suppressed_scorer_signals(li.raw, NOW) == set(tc.GOVERNS)


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


# ---------------------------------------------------------------------------
# a MIXED row under a refuted / stale property-tax verdict: the property-tax-derived signals
# end, the lien's own survive, in the scorer and in the lead-signal stack
# ---------------------------------------------------------------------------

def _record(res) -> dict:
    """A verifier's real answer as the VM's apply step attaches it (fixed stamps)."""
    checked = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return dict(res.to_dict(), checked_at=core.iso_z(checked),
                expires_at=core.iso_z(checked + timedelta(days=tlb.TTL_DAYS)),
                governs=list(tlb.GOVERNS))


@pytest.mark.parametrize("pages,verdict", [(REFUTED_PAGES, "refuted"), (STALE_PAGES, "stale")])
def test_irs_mixed_row_keeps_the_lien_and_loses_the_paid_property_tax(pages, verdict):
    parcel = {"refuted": "0646441079", "stale": "963962247000000"}[verdict]
    row = irs_mixed_row(parcel)
    res = run(row, ReplayFetcher(served(*pages)))
    assert res.verdict == verdict                      # the county's own answer, not downgraded
    plain, checked = _li(row), _li(row, [_record(res)])
    # scorer: before, the IRS lien (listing type) and the property-tax balance (tax_owed)
    assert {"tax_lien", "recorded_debt"} <= _names(plain)
    after = _names(checked)
    assert "tax_lien" in after                         # the IRS lien's own signal survives
    assert "recorded_debt" not in after                # the county says that tax is not owed
    # facets: the only debt facet was the property-tax balance
    assert "recorded_debt" in _facet_signals(plain, TODAY)
    assert "recorded_debt" not in _facet_signals(checked, TODAY)
    # the lead-signal stack (scorer signals + facets) after a full score_board (each row alone:
    # score_board unions a parcel's rows)
    ds.score_board([plain], previous_path=None)
    ds.score_board([checked], previous_path=None)
    assert {"tax_lien", "recorded_debt"} <= set(_signal_stack(plain, TODAY)["signals"])
    stack = set(_signal_stack(checked, TODAY)["signals"])
    assert "tax_lien" in stack and "recorded_debt" not in stack


@pytest.mark.parametrize("verdict", ["refuted", "stale"])
def test_dew_mixed_row_keeps_the_lien_and_its_debt(verdict):
    """qPayBill's verdict on the roll block (property tax) sits on the DEW lien's row. The DEW
    lien's listing type and its judgment amount are not property tax: both stay."""
    row = dew_mixed_row()
    plain, checked = _li(row), _li(row, [_vrec(verdict, verifier="tax_lien_qpaybill")])
    assert {"tax_lien", "recorded_debt"} <= _names(plain)
    assert {"tax_lien", "recorded_debt"} <= _names(checked)
    assert "recorded_debt" in _facet_signals(checked, TODAY)
    ds.score_board([checked], previous_path=None)
    assert {"tax_lien", "recorded_debt"} <= set(_signal_stack(checked, TODAY)["signals"])
    # the property-tax-derived facet on the same row would end (sc_tax_delinquent)
    checked.raw["sc_tax_delinquent"] = {"year": 2025}
    assert "tax_lien" not in _facet_signals(checked, TODAY)
    assert "tax_lien" in _signal_stack(checked, TODAY)["signals"]     # the lien's, from the scorer

