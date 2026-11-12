"""deed_index: the sidecar, and the rule that says who LOST the parcel.

The grantor list of a forced-sale deed is not the list of losers. A trustee's
deed lists the foreclosing law firm next to the borrowers; a commissioner's deed
lists the attorney commissioner next to the delinquent taxpayer. Every name here
is a placeholder.
"""
from __future__ import annotations

import sqlite3

import pytest

from foreclosure_scraper import deed_index as di
from foreclosure_scraper.deed_index import DeedInstrument, Party, derive_loss
from foreclosure_scraper.rod import inst_class as ic

FIRM = Party("PLACEHOLDER TRUSTEE SERVICES PLLC", kind="F")
DOE_J = Party("DOE JOHN Q", kind="I")
DOE_JA = Party("DOE JANE R", kind="I")


# --- derive_loss -----------------------------------------------------------------
def test_trustee_deed_losers_are_the_borrowers_beside_the_firm():
    kind, losers = derive_loss(ic.TRUSTEE_DEED, [FIRM, DOE_J, DOE_JA], "8123/456")
    assert kind == "mortgage_foreclosure"
    assert losers == ["DOE JOHN Q", "DOE JANE R"]


def test_trustee_deed_whose_only_grantor_is_a_trust_is_not_a_loss():
    trust = Party("SAMPLE FAMILY LIVING TRUST", kind="F")
    assert derive_loss(ic.TRUSTEE_DEED, [trust], "8123/456") == ("unknown", [])


def test_trustee_deed_needs_a_firm_or_a_deed_of_trust_cross_reference():
    # A lone person with neither is more likely the attorney trustee than the borrower.
    assert derive_loss(ic.TRUSTEE_DEED, [DOE_J], "") == ("unknown", [])
    # The description names the foreclosed deed of trust: enough.
    assert derive_loss(ic.TRUSTEE_DEED, [DOE_J], "DT 1347/484") == ("mortgage_foreclosure", ["DOE JOHN Q"])


def test_trustee_deed_officer_flagged_by_the_vendor_suffix_is_not_a_loser():
    atty = Party("ROE RICHARD T", kind="I", suffix="TR")
    kind, losers = derive_loss(ic.TRUSTEE_DEED, [atty, DOE_J], "")
    assert (kind, losers) == ("mortgage_foreclosure", ["DOE JOHN Q"])


def test_commissioner_deed_drops_the_commissioner_and_keeps_the_taxpayer():
    commissioner = Party("ROE RICHARD T", kind="I", suffix="COMM")
    taxpayer = Party("SAMPLE ALEX B", kind="I")
    assert derive_loss(ic.COMMISSIONER_DEED, [commissioner, taxpayer], "TAX FORECLOSURE") == \
        ("tax_foreclosure", ["SAMPLE ALEX B"])
    assert derive_loss(ic.COMMISSIONER_DEED, [commissioner, taxpayer], "") == \
        ("judicial_sale", ["SAMPLE ALEX B"])


def test_sheriff_and_master_deeds_drop_the_officer():
    sheriff = Party("EXAMPLE COUNTY SHERIFF", kind="F")
    assert derive_loss(ic.SHERIFF_DEED, [sheriff, DOE_J], "") == ("judicial_sale", ["DOE JOHN Q"])
    assert derive_loss(ic.MASTER_DEED, [DOE_J], "") == ("judicial_sale", ["DOE JOHN Q"])


def test_tax_deed_kind():
    assert derive_loss(ic.TAX_DEED, [DOE_J], "") == ("tax_deed", ["DOE JOHN Q"])


def test_an_entity_grantor_is_never_a_loser():
    llc = Party("SAMPLE HOLDINGS LLC", kind="F")
    assert derive_loss(ic.SHERIFF_DEED, [llc], "") == ("unknown", [])
    # even when the vendor did not flag it
    assert derive_loss(ic.SHERIFF_DEED, [Party("SAMPLE HOLDINGS LLC")], "") == ("unknown", [])


def test_a_pa_suffix_is_a_firm_but_two_middle_initials_are_not():
    assert derive_loss(ic.TRUSTEE_DEED, [Party("SMITH AND JONES P.A."), DOE_J], "") == \
        ("mortgage_foreclosure", ["DOE JOHN Q"])
    assert derive_loss(ic.SHERIFF_DEED, [Party("DOE JOHN P A")], "") == ("judicial_sale", ["DOE JOHN P A"])


@pytest.mark.parametrize("cls", [ic.DEED, ic.QUITCLAIM, ic.OTHER, ic.EXECUTOR_DEED])
def test_non_loss_classes_never_yield_losers(cls):
    assert derive_loss(cls, [FIRM, DOE_J], "8123/456") == ("unknown", [])


# --- standing officers -----------------------------------------------------------
def test_standing_officer_needs_both_a_count_and_a_share():
    assert di.standing_officers({"A": 20}, 40) == {"A"}            # 20 docs, 50 percent
    assert di.standing_officers({"A": 7}, 20) == frozenset()       # under 8 docs
    assert di.standing_officers({"A": 8}, 100) == frozenset()      # 8 percent share
    assert di.standing_officers({"A": 8}, 0) == frozenset()


def _inst(n, grantors, cls=ic.COMMISSIONER_DEED, county="Burke", code="COM/D", desc="TAX FORECLOSURE"):
    parties = [Party(g, kind="I") for g in grantors]
    kind, losers = derive_loss(cls, parties, desc)
    return DeedInstrument(
        county=county, state="NC", source="cchs_classic", inst_code=code, inst_class=cls,
        recorded_date=f"2025-{(n % 12) + 1:02d}-01", book="9001", page=str(n),
        instrument_no=f"2025{n:06d}", grantors=list(grantors), grantor_parties=parties,
        grantees=["EXAMPLE COUNTY"], description=desc, loss_kind=kind, loser_names=losers)


def test_refresh_drops_a_standing_officer_and_keeps_a_real_repeat_loser(tmp_path):
    con = di.connect(tmp_path / "d.db")
    docs = []
    # The commissioner is on every deed. Nobody can tell which grantor he is from
    # one document alone, so before the refresh he is listed as a loser too.
    for n in range(1, 21):
        taxpayer = "REPEAT LOSER" if n in (3, 9, 14) else f"TAXPAYER{n:02d} PERSON"
        docs.append(_inst(n, ["ROE RICHARD T", taxpayer]))
    di.upsert(con, docs)
    before = {r["book"] + "/" + r["page"]: r for r in di.load_loss_rows(tmp_path / "d.db")}
    assert "ROE RICHARD T" in before["9001/3"]["loser_names"]

    stats = di.refresh_losers(con)
    assert stats["officers"] == {"Burke, NC": ["ROE RICHARD T"]}
    rows = {r["page"]: r for r in di.load_loss_rows(tmp_path / "d.db")}
    assert rows["3"]["loser_names"] == ["REPEAT LOSER"]
    assert rows["9"]["loser_names"] == ["REPEAT LOSER"]
    assert all("ROE RICHARD T" not in r["loser_names"] for r in rows.values())
    assert di.refresh_losers(con)["updated"] == 0                # idempotent


def test_refresh_is_per_county(tmp_path):
    con = di.connect(tmp_path / "d.db")
    burke = [_inst(n, ["ROE RICHARD T", f"TAXPAYER{n:02d} PERSON"]) for n in range(1, 21)]
    lincoln = [_inst(n, ["ROE RICHARD T", f"OTHER{n:02d} PERSON"], county="Lincoln") for n in range(1, 4)]
    di.upsert(con, burke + lincoln)
    di.refresh_losers(con)
    lin = [r for r in di.load_loss_rows(tmp_path / "d.db") if r["county"] == "Lincoln"]
    # three deeds is not enough to call him an officer in Lincoln
    assert all("ROE RICHARD T" in r["loser_names"] for r in lin)


# --- sqlite ------------------------------------------------------------------------
def test_upsert_replaces_on_the_document_key(tmp_path):
    con = di.connect(tmp_path / "d.db")
    a = _inst(1, ["ROE RICHARD T", "DOE JOHN Q"])
    assert di.upsert(con, [a]) == 1
    assert di.upsert(con, [a]) == 1
    assert con.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] == 1
    assert a.doc_key == "Burke|NC|9001|1|2025000001|COM/D"


def test_load_loss_rows_skips_rows_that_name_nobody_and_non_loss_classes(tmp_path):
    con = di.connect(tmp_path / "d.db")
    named = _inst(1, ["ROE RICHARD T", "DOE JOHN Q"])
    nobody = _inst(2, ["SAMPLE FAMILY LIVING TRUST"], cls=ic.TRUSTEE_DEED, code="TR/D", desc="")
    deed = _inst(3, ["DOE JOHN Q"], cls=ic.DEED, code="DEED", desc="")
    di.upsert(con, [named, nobody, deed])
    rows = di.load_loss_rows(tmp_path / "d.db")
    assert [r["page"] for r in rows] == ["1"]
    r = rows[0]
    # No role marker on either grantor, so both are listed until refresh_losers
    # has enough of the county's deeds to spot the commissioner.
    assert r["loser_names"] == ["ROE RICHARD T", "DOE JOHN Q"]
    assert r["inst_class"] == ic.COMMISSIONER_DEED and r["state"] == "NC"


def test_a_missing_sidecar_is_an_empty_list_and_is_not_created(tmp_path):
    p = tmp_path / "nope.db"
    assert di.load_loss_rows(p) == []
    assert not p.exists()


def test_a_file_that_is_not_a_sidecar_reads_as_empty_not_as_a_crash(tmp_path):
    p = tmp_path / "other.db"
    sqlite3.connect(p).close()                       # exists, has no instruments table
    assert di.load_loss_rows(p) == []


def test_default_path_is_next_to_the_other_sidecars():
    assert di.DB_PATH.name == "deed_index.db"
    assert di.DB_PATH.parent.name == "data"


def test_coverage_reports_the_date_span_per_county(tmp_path):
    con = di.connect(tmp_path / "d.db")
    di.upsert(con, [_inst(1, ["ROE RICHARD T", "DOE JOHN Q"]),
                    _inst(2, ["SAMPLE FAMILY LIVING TRUST"], cls=ic.TRUSTEE_DEED, code="TR/D", desc="")])
    (row,) = di.coverage(con)
    assert (row["county"], row["state"], row["docs"], row["loss_docs"], row["with_losers"]) == \
        ("Burke", "NC", 2, 2, 1)
    assert row["min_date"] == "2025-02-01" and row["max_date"] == "2025-03-01"


def test_schema_matches_the_scoping_doc(tmp_path):
    con = di.connect(tmp_path / "d.db")
    cols = {r[1] for r in con.execute("PRAGMA table_info(instruments)")}
    assert {"doc_key", "county", "state", "source", "instrument_no", "book", "page", "recorded_date",
            "inst_code", "inst_class", "grantors", "grantees", "excise_stamp", "parcel_id",
            "description", "loss_kind", "loser_names", "fetched_at"} <= cols
    assert isinstance(con, sqlite3.Connection)
