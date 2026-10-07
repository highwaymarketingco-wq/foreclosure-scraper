"""'Party 1' / 'Party 2' sides and <br>-split party cells on Spartanburg's Logan build.

Until 2026-10-07 rod/logan._parse_records (the Spartanburg render reader's parser, feeding
enrichment_spartanburg_rod's raw['rod']) and enrichment_dot_ocr._parse_image_rows put the searched
owner on the GRANTOR side of every row: a deed INTO the owner ('Party 2') read as a sale BY the
owner, and co-owners listed in one cell glued into one name. Hand-written fixtures, made-up names."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from foreclosure_scraper import enrichment_dot_ocr as dm
from foreclosure_scraper import enrichment_spartanburg_rod as sr
from foreclosure_scraper.models import Listing
from foreclosure_scraper.rod import logan


def row(inst, mdy, book_info, typ, legal, role, searched, reverse):
    return (f'<tr id="{inst}"><td><a href="javascript: loadDetailsScreen(\'{inst}\');" id="link_{inst}"> '
            f'{mdy}&nbsp;</a></td>'
            f'<td class="summary" id="{inst}"> {book_info} &nbsp; </td>'
            f'<td class="summary" id="{inst}">{typ}&nbsp;</td>'
            f'<td class="summary" id="{inst}"> {legal}<br> &nbsp; </td>'
            f'<td class="summary" id="{inst}"> {role}&nbsp;</td>'
            f'<td class="summary" id="{inst}"> {" <br> ".join(searched)} <br> &nbsp; </td>'
            f'<td class="summary" id="{inst}"> {" <br> ".join(reverse)} <br> </td></tr>')


OWNER = "VELLACOTT PRUE A"
SPOUSE = "VELLACOTT DORIAN B"
SELLER = "ARKWRIGHT TOBIAS"
SPARTANBURG = "<table>" + "".join([
    row("2019001111", "03/04/2019", "DEE 120-K 45", "DEED", "LOT 8", "Party 2", [OWNER, SPOUSE], [SELLER]),
    row("2019001112", "03/04/2019", "MTG 5500 12", "MORTGAGE", "LOT 8", "Party 1", [OWNER, SPOUSE],
        ["TESTBANK OF NOWHERE NA"]),
    row("2024009999", "06/01/2024", "DEE 140-B 2", "DEED", "LOT 8", "Party 1", [OWNER], ["NEWBUYER CORA"]),
]) + "</table>"


def test_party_2_deed_is_a_purchase_by_the_owner():
    deed_in, mtg, deed_out = logan._parse_records(SPARTANBURG, "SC", "Spartanburg")
    assert deed_in.grantor == SELLER and deed_in.grantee == f"{OWNER}; {SPOUSE}"     # was swapped and glued
    assert mtg.grantor == f"{OWNER}; {SPOUSE}" and mtg.grantee == "TESTBANK OF NOWHERE NA"
    assert deed_out.grantor == OWNER and deed_out.grantee == "NEWBUYER CORA"
    assert deed_in.raw["logan"]["grantees"] == [OWNER, SPOUSE]


def test_grantee_side_words():
    assert logan.grantee_side("Party 2") and logan.grantee_side("GRANTEE") and logan.grantee_side("Indirect")
    assert not logan.grantee_side("Party 1") and not logan.grantee_side("GRANTOR")
    assert not logan.grantee_side("Party 12")
    assert logan.party_names("A B <br> C D&lt;br&gt;E F <br>") == ["A B", "C D", "E F"]


def test_nc_grantor_grantee_rows_unchanged():
    nc = "<table>" + row("1999000001", "01/02/1999", "DT 296 343", "D/T", "PD", "GRANTOR",
                         ["TESTER ALVIN Q"], ["ENKA TEST CREDIT UNION"]) \
        + row("1999000002", "01/02/1999", "DEE 296 340", "DEED", "PD", "GRANTEE",
              ["TESTER ALVIN Q"], ["OLDOWNER MAE"]) + "</table>"
    dt, deed = logan._parse_records(nc, "NC", "Transylvania")
    assert (dt.grantor, dt.grantee) == ("TESTER ALVIN Q", "ENKA TEST CREDIT UNION")
    assert (deed.grantor, deed.grantee) == ("OLDOWNER MAE", "TESTER ALVIN Q")


def clip(inst, typ, role, searched, reverse):
    return (f"<a href=\"javascript: copyToClipboard('{inst}', '03/04/2019', 'DEE 120-K 45 ', '{typ}', "
            f"'LOT 8&lt;br&gt;', '{role}', '{searched}', '{reverse}', '', '',"
            f"'&lt;a href=\\'view_image.php?key=0123456789abcdef0123456789abcdef\\' target=\\'_blank\\'"
            f"&gt;View Image&lt;/a&gt; &nbsp;');\">Copy to Clipboard</a>")


def test_dot_ocr_rows_use_the_role():
    rows = dm._parse_image_rows(
        clip("1", "DEED", "Party 2", f"{OWNER} &lt;br&gt;{SPOUSE} &lt;br&gt;", f" {SELLER} &lt;br&gt;")
        + clip("2", "MORTGAGE", "Party 1", f"{OWNER} &lt;br&gt;", " TESTBANK OF NOWHERE NA &lt;br&gt;"))
    deed, mtg = rows
    assert deed["grantor"] == SELLER and deed["grantee"] == f"{OWNER}; {SPOUSE}"
    assert mtg["grantor"] == OWNER and mtg["grantee"] == "TESTBANK OF NOWHERE NA"


def _lead(rod=None):
    li = Listing(source="x", source_url="u", state="SC", county="Spartanburg", owner_name=OWNER, raw={})
    if rod is not None:
        li.raw["rod"] = rod
    return li


def test_stamps_read_before_the_fix_are_refetched_first():
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    old = _lead({"source": "spartanburg_rod_render", "fetched_at": "2026-10-07T01:00:00+00:00"})
    new = _lead({"source": "spartanburg_rod_render", "fetched_at": "2026-10-07T23:00:00+00:00",
                 "party_sides": sr.PARTY_SIDES})
    assert sr._rod_age_days(old, now) is None            # treated like a never-fetched lead
    assert sr._rod_age_days(new, now) is not None


def test_enricher_stamps_the_fixed_parser(monkeypatch):
    async def fake_render(state, county, name):
        return logan._parse_records(SPARTANBURG, state, county)
    monkeypatch.setattr(sr, "search_by_name_render", fake_render)
    li = _lead({"source": "spartanburg_rod_render", "fetched_at": "2026-08-01T00:00:00+00:00"})
    asyncio.run(sr.enrich_spartanburg_rod([li]))
    rod = li.raw["rod"]
    assert rod["party_sides"] == sr.PARTY_SIDES
    deed = next(i for i in rod["instruments"] if i["book"] == "120-K")
    assert deed["grantor"] == SELLER and OWNER in deed["grantee"]
