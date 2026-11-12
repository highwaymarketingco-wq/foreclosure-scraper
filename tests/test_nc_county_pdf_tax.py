"""Unit tests for the NC county PDF delinquent-tax parser (no network)."""
from foreclosure_scraper.scrapers.counties_nc import nc_county_pdf_delinquent_tax as m


def test_name_id_amt_layout():
    text = (
        "Column1 Column2 Column3\n"
        "ABERNATHY JOHN DAVID          90537 174.99\n"
        "120 HICKORY LLC               26326 12693.24\n"
        "ZERO OWED LLC                 11111 0\n"          # zero-owed dropped
        "some prose line with no id\n"
    )
    rows = m._parse_name_id_amt(text, (1, 7))
    ids = {r[1]: r for r in rows}
    assert set(ids) == {"90537", "26326"}
    assert ids["90537"][0] == "ABERNATHY JOHN DAVID"
    assert ids["120" if False else "26326"][2] == 12693.24


def test_parcel_amt_owner_layout():
    text = (
        "079700586730              $5,847.85\n"
        "307 BLUERIDGE DR S UT1 LND TST\n"
        "077000420045               $829.95\n"
        "7F RENOVATIONS LLC\n"
    )
    rows = m._parse_parcel_amt_owner(text)
    by = {r[1]: r for r in rows}
    assert set(by) == {"079700586730", "077000420045"}
    assert by["079700586730"][0] == "307 BLUERIDGE DR S UT1 LND TST"
    assert by["079700586730"][2] == 5847.85


def test_to_listing_parcel_flag():
    cfg_pin = {"url": "u", "id_is_parcel": True}
    cfg_acct = {"url": "u", "id_is_parcel": False}
    li_pin = m._to_listing("A B", "90537", 100.0, "Lincoln", cfg_pin)
    li_acct = m._to_listing("C D", "33566", 100.0, "Catawba", cfg_acct)
    assert li_pin.parcel_id == "90537"
    # Catawba's id is set as parcel_id (dedup key) but flagged non-GIS in raw
    assert li_acct.parcel_id == "33566"
    assert li_acct.raw["nc_county_pdf_delinquent_tax"]["id_is_parcel"] is False
    assert li_acct.raw["nc_county_pdf_delinquent_tax"]["county_id"] == "33566"
    assert li_pin.listing_type.value == "tax_lien"


def test_money_and_owner():
    assert m._money("1,234.50") == 1234.50
    assert m._money("0") is None
    assert m._clean_owner("  SMITH,  JOHN ;") == "SMITH, JOHN"
    assert m._clean_owner("") is None


# --- 2026-10-07 extraction audit: the live McDowell list prints the owner BEFORE its
# parcel line, so reading the next line gave every row its neighbour's owner. ---

_OWNER_FIRST = (
    "OWNER-NAME\n"
    "PARCEL                          TOTAL DUE\n"
    "SAMPLE HOLDINGS LLC\n"
    "079700000001              $1,234.56\n"
    "DOE JANE Q\n"
    "079700000002               $99.10\n"
    "EXAMPLE PAT AND A VERY LONG NAME THAT\n"
    "WRAPS ONTO A SECOND LINE\n"
    "0797 00000003                $10.00\n"
)


def test_owner_before_parcel_layout_pairs_each_parcel_with_its_own_owner():
    by = {r[1]: r for r in m._parse_parcel_amt_owner(_OWNER_FIRST)}
    assert by["079700000001"][0] == "SAMPLE HOLDINGS LLC"
    assert by["079700000001"][2] == 1234.56
    assert by["079700000002"][0] == "DOE JANE Q"


def test_a_wrapped_owner_is_joined_and_a_spaced_parcel_is_read():
    by = {r[1]: r for r in m._parse_parcel_amt_owner(_OWNER_FIRST)}
    assert by["079700000003"][0] == "EXAMPLE PAT AND A VERY LONG NAME THAT WRAPS ONTO A SECOND LINE"
    assert by["079700000003"][2] == 10.0


def test_header_lines_are_never_an_owner():
    rows = m._parse_parcel_amt_owner(_OWNER_FIRST)
    assert not any("OWNER-NAME" in (r[0] or "") or "TOTAL DUE" in (r[0] or "") for r in rows)


def test_every_advertised_line_of_one_account_is_summed_not_first_wins():
    """Catawba's id is the taxpayer's ACCOUNT number; an account owning several parcels is
    advertised once per parcel. The old first-wins de-dupe kept $56.94 of $618.21 here."""
    text = "\n".join([
        "DOE JOHN Q 12391 56.94",
        "DOE JOHN Q 12391 504.82",
        "ROE RICHARD 4455 10.00",
        "DOE JOHN Q 12391 56.45",
    ])
    cfg = m.COUNTIES["Catawba"]
    leads = m._aggregate(m._parse_name_id_amt(text, cfg["id_digits"]), "Catawba", cfg)
    assert len(leads) == 2
    doe = next(li for li in leads if li.parcel_id == "12391")
    blk = doe.raw["nc_county_pdf_delinquent_tax"]
    assert blk["principal_tax_due"] == 618.21
    assert blk["line_count"] == 3 and [x["amount"] for x in blk["lines"]] == [56.94, 504.82, 56.45]
    roe = next(li for li in leads if li.parcel_id == "4455")
    assert roe.raw["nc_county_pdf_delinquent_tax"]["principal_tax_due"] == 10.0
    assert "lines" not in roe.raw["nc_county_pdf_delinquent_tax"]
