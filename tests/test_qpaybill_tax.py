"""qPayBill delinquent-tax enrichment — grid parse, surname, TMS match, gating."""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_qpaybill_tax as q
from foreclosure_scraper.models import Listing, ListingType

_ROW = ('<tr><td>175401253</td><td>SMITH X 148 COBB RD</td><td>2025</td><td>148 COBB RD</td>'
        '<td>2-37-00-035.53</td><td>RealEstate</td><td>{status}</td><td></td><td>${amt}</td><td>View</td></tr>')

# A real agricultural-use change-of-use rollback bill, same grid shape, Description
# reading "<year> ROLLBACK TAX..." instead of a situs address/lot description --
# live-confirmed 2026-11-05 against Calhoun map 053-00-01-112 (three such rows,
# tax years 2022/2023/2024, Paid).
_ROLLBACK_ROW = ('<tr><td>175401253</td><td>SMITH X 148 COBB RD</td><td>2024</td>'
                  '<td>2024 ROLLBACK TAX</td><td>2-37-00-035.53</td><td>RealEstate</td>'
                  '<td>{status}</td><td></td><td>${amt}</td><td>View</td></tr>')


def test_parse_grid_row():
    rows = q._parse_rows(_ROW.format(status="Unpaid", amt="508.70"))
    assert rows == [{"tms": "2-37-00-035.53", "year": "2025", "status": "Unpaid", "amount": 508.70,
                     "description": "148 COBB RD", "rollback": False}]


def test_parse_skips_sentinel_and_junk():
    assert q._parse_rows(_ROW.format(status="Unpaid", amt="99,999.00")) == []  # $99,999 sentinel
    assert q._parse_rows("<tr><td>no</td><td>cells</td></tr>") == []


def test_parse_grid_row_flags_rollback():
    # a rollback bill is commonly already Paid (the Calhoun example was) -- the flag
    # must not depend on status.
    rows = q._parse_rows(_ROLLBACK_ROW.format(status="Paid", amt="511.76"))
    assert rows == [{"tms": "2-37-00-035.53", "year": "2024", "status": "Paid", "amount": 511.76,
                     "description": "2024 ROLLBACK TAX", "rollback": True}]
    # case-insensitive, matches tax_lien_qpaybill.py's own "ROLLBACK" in c[3].upper() test
    rows_lower = q._parse_rows(
        _ROLLBACK_ROW.format(status="Unpaid", amt="18.11").replace("ROLLBACK", "Rollback"))
    assert rows_lower[0]["rollback"] is True


def test_surname_extraction():
    assert q._surname("MEADOWS ALFRED AAA WOFTMAN LLC") == "MEADOWS"
    assert q._surname("ADDIS PATRICIA CUDD TIFFANY (CS)") == "ADDIS"
    assert q._surname("  123 ") is None


def test_cherokee_pid_redash():
    # numeric 13-digit court-feed parcel -> dashed portal Identification-No.
    assert q._norm_cherokee_pid("0020000003000") == "002-00-00-003.000"
    assert q._norm_cherokee_pid("1030000083000") == "103-00-00-083.000"
    # already-dashed and 16-digit sub-parcels pass through untouched
    assert q._norm_cherokee_pid("029-00-00-028.001") == "029-00-00-028.001"
    assert q._norm_cherokee_pid("0981600030106001") == "0981600030106001"
    # dispatcher: Cherokee normalizes, other counties are identity
    assert q._norm_pid("SC", "Cherokee", "1030000083000") == "103-00-00-083.000"
    assert q._norm_pid("SC", "Spartanburg", "2-37-00-035.53") == "2-37-00-035.53"
    assert q.QPAYBILL_COUNTIES[("SC", "Cherokee")] == "cherokeecountysctax"


def test_barnwell_pid_redash():
    # digit-stripped 10-digit sc_heir_estate_parcel_cache id -> dashed portal
    # Identification-No. -- live-confirmed 2026-11-05: surname RYAN's grid row is
    # exactly "047-03-03-012", the predicted redash of board id "0470303012".
    assert q._norm_barnwell_pid("0470303012") == "047-03-03-012"
    assert q._norm_barnwell_pid("0450000021") == "045-00-00-021"
    # already-dashed ids, including a sub-parcel .NN suffix, pass through untouched
    assert q._norm_barnwell_pid("045-00-00-021.03") == "045-00-00-021.03"
    assert q._norm_barnwell_pid("047-07-09-005.01") == "047-07-09-005.01"
    assert q._norm_pid("SC", "Barnwell", "0470303012") == "047-03-03-012"


def test_new_sc_counties_registered():
    # live-verified 2026-11-05: real Type4 form + real grid rows on all four, and
    # the board's own existing parcel_id round-trips exactly against the live grid
    # (Williamsburg "45-061-009", Darlington "067-07-03-066", Kershaw
    # "238-00-00-148"; Barnwell via _norm_barnwell_pid above).
    assert q.QPAYBILL_COUNTIES[("SC", "Williamsburg")] == "williamsburgtreasurer"
    assert q.QPAYBILL_COUNTIES[("SC", "Darlington")] == "darlingtontreasurer"
    assert q.QPAYBILL_COUNTIES[("SC", "Barnwell")] == "barnwelltreasurer"
    assert q.QPAYBILL_COUNTIES[("SC", "Kershaw")] == "kershawcounty"


def test_cherokee_numeric_board_parcel_joins_dashed_grid(monkeypatch):
    """Cherokee court-feed parcels are numeric; the portal grid is dashed. The
    key normalizer must let the numeric board parcel join the dashed grid row."""
    monkeypatch.setattr(q, "_ENABLED", True)

    async def fake_search(client, sub, vs, surname):
        # portal returns the DASHED Identification-No.
        return [{"tms": "103-00-00-083.000", "year": "2025",
                 "status": "Unpaid", "amount": 69.94}]

    async def fake_get(url):
        class R:
            text = ('<input id="__VIEWSTATE" value="v">'
                    '<input id="__VIEWSTATEGENERATOR" value="g">'
                    '<input id="__EVENTVALIDATION" value="e">')
        return R()

    import httpx
    monkeypatch.setattr(q, "_search_surname", fake_search)
    monkeypatch.setattr(httpx.AsyncClient, "get", lambda self, url: fake_get(url))

    li = Listing(source="counties_sc.sc_public_index_lis_pendens", source_url="u",
                 listing_type=ListingType.TAX_SALE, state="SC", county="Cherokee",
                 parcel_id="1030000083000", owner_name="SMITH ALICE INMAN")
    out = asyncio.run(q.enrich_qpaybill_tax([li]))
    assert out["filled"] == 1
    t = li.raw["tax_owed"]
    assert t["balance"] == 69.94
    assert t["source"] == "qpaybill:cherokeecountysctax"
    assert t["years"] == ["2025"]


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr(q, "_ENABLED", False)
    li = Listing(source="counties_sc.spartanburg_delinquent_tax", source_url="u",
                 listing_type=ListingType.TAX_SALE, state="SC", county="Spartanburg",
                 parcel_id="2-37-00-035.53", owner_name="SMITH X")
    out = asyncio.run(q.enrich_qpaybill_tax([li]))
    assert out == {"targets": 0, "queries": 0, "filled": 0, "misses": 0, "rollback_found": 0}


def test_match_by_tms_and_sum_years(monkeypatch):
    monkeypatch.setattr(q, "_ENABLED", True)

    async def fake_search(client, sub, vs, surname):
        # two years owed on the target parcel + one unrelated parcel + one paid row
        return [
            {"tms": "2-37-00-035.53", "year": "2025", "status": "Unpaid", "amount": 500.0},
            {"tms": "2-37-00-035.53", "year": "2024", "status": "Unpaid", "amount": 300.0},
            {"tms": "9-99-99-999.99", "year": "2025", "status": "Unpaid", "amount": 111.0},
        ]

    async def fake_get(url):
        class R:  # minimal stub
            text = '<input id="__VIEWSTATE" value="v"><input id="__VIEWSTATEGENERATOR" value="g"><input id="__EVENTVALIDATION" value="e">'
        return R()

    monkeypatch.setattr(q, "_search_surname", fake_search)
    # patch the client GET via monkeypatching httpx is heavier; instead pre-seed vs by patching get_vs path:
    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "get", lambda self, url: fake_get(url))

    li = Listing(source="counties_sc.spartanburg_delinquent_tax", source_url="u",
                 listing_type=ListingType.TAX_SALE, state="SC", county="Spartanburg",
                 parcel_id="2-37-00-035.53", owner_name="ADDIS PATRICIA")
    out = asyncio.run(q.enrich_qpaybill_tax([li]))
    assert out["filled"] == 1
    t = li.raw["tax_owed"]
    assert t["balance"] == 800.0                 # summed across 2025 + 2024
    assert t["kind"] == "delinquent_tax" and t["years"] == ["2024", "2025"]
    assert t["source"] == "qpaybill:spartanburgcountytax"


def test_rollback_row_stamps_rollback_exposure_alongside_tax_owed(monkeypatch):
    """A parcel with one ordinary Unpaid row (fills tax_owed, as always) plus two
    already-Paid ROLLBACK TAX rows for prior years (Calhoun's real shape: paid
    rollback bills are still a real, already-billed exposure fact, not something
    the Unpaid-only tax_owed aggregation would ever see on its own)."""
    monkeypatch.setattr(q, "_ENABLED", True)

    async def fake_search(client, sub, vs, surname):
        return [
            {"tms": "053-00-01-112", "year": "2025", "status": "Unpaid", "amount": 286.05,
             "description": "", "rollback": False},
            {"tms": "053-00-01-112", "year": "2024", "status": "Paid", "amount": 517.12,
             "description": "2024 ROLLBACK TAX", "rollback": True},
            {"tms": "053-00-01-112", "year": "2022", "status": "Paid", "amount": 147.95,
             "description": "2022 ROLLBACK TAX", "rollback": True},
        ]

    async def fake_get(url):
        class R:
            text = ('<input id="__VIEWSTATE" value="v">'
                    '<input id="__VIEWSTATEGENERATOR" value="g">'
                    '<input id="__EVENTVALIDATION" value="e">')
        return R()

    import httpx
    monkeypatch.setattr(q, "_search_surname", fake_search)
    monkeypatch.setattr(httpx.AsyncClient, "get", lambda self, url: fake_get(url))

    # county is Spartanburg (already in QPAYBILL_COUNTIES) so the listing actually
    # enters the query flow -- the TMS itself is the real Calhoun map number from
    # tax_lien_qpaybill.py's own prior finding, reused here only as a fixture value.
    li = Listing(source="counties_sc.spartanburg_delinquent_tax", source_url="u",
                 listing_type=ListingType.TAX_SALE, state="SC", county="Spartanburg",
                 parcel_id="053-00-01-112", owner_name="DOE JOHN")
    out = asyncio.run(q.enrich_qpaybill_tax([li]))
    assert out["filled"] == 1
    assert out["rollback_found"] == 1
    assert li.raw["tax_owed"]["balance"] == 286.05        # the plain Unpaid row only
    rb = li.raw["rollback_exposure"]
    assert rb["rollback_already_billed"] == 665.07        # 517.12 + 147.95, paid or not
    assert rb["rollback_billed_years"] == ["2022", "2024"]
    assert rb["basis"] == "agricultural_use_deferral"
    assert rb["match_method"] == "parcel"
    assert rb["county"] == "Spartanburg" and rb["state"] == "SC"
    assert rb["estimated_rollback"] is None               # never a projection, see docstring
    assert rb["rollback_years"] == 3


def test_rollback_exposure_is_idempotent(monkeypatch):
    """A row that already carries raw['rollback_exposure'] is left untouched, same
    convention every sibling rollback_exposure producer uses."""
    monkeypatch.setattr(q, "_ENABLED", True)

    async def fake_search(client, sub, vs, surname):
        return [{"tms": "053-00-01-112", "year": "2024", "status": "Paid", "amount": 999.0,
                 "description": "2024 ROLLBACK TAX", "rollback": True}]

    async def fake_get(url):
        class R:
            text = ('<input id="__VIEWSTATE" value="v">'
                    '<input id="__VIEWSTATEGENERATOR" value="g">'
                    '<input id="__EVENTVALIDATION" value="e">')
        return R()

    import httpx
    monkeypatch.setattr(q, "_search_surname", fake_search)
    monkeypatch.setattr(httpx.AsyncClient, "get", lambda self, url: fake_get(url))

    li = Listing(source="counties_sc.spartanburg_delinquent_tax", source_url="u",
                 listing_type=ListingType.TAX_SALE, state="SC", county="Spartanburg",
                 parcel_id="053-00-01-112", owner_name="DOE JOHN",
                 raw={"rollback_exposure": {"rollback_already_billed": 1.0, "source_key": "preexisting"}})
    out = asyncio.run(q.enrich_qpaybill_tax([li]))
    assert out["rollback_found"] == 0
    assert li.raw["rollback_exposure"]["source_key"] == "preexisting"
