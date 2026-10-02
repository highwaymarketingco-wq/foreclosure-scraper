"""counties_sc.sc_probate_net — gvDocket sub-grid (2026-10-02 extension).

HERMES sec 8 asked whether SC probate case detail carries an estate dollar
value (inventory/bond amount) or any mechanism naming heirs. Live-queried
southcarolinaprobate.net (Charleston Probate + York Probate, real "Smith"
searches) and found a THIRD sub-grid, `..._gvDocket`, shipped in the same
response as the existing `cgvCases`/`..._gvParties` grids but never parsed at
all. It is a document/activity TYPE log (never a dollar figure anywhere,
confirmed across ~800 live rows) that nonetheless carries two real signals
this project did not have before:

  - "INVENTORY/APPRAISEMENT" (and "SUPPLEMENTAL INVENTORY & APPRAISEMENT") --
    whether the estate's asset inventory was filed at all. Not the value.
  - "INFORMATION TO HEIRS AND DEVISEES" / "POD - INFO TO HEIRS" -- SC's
    statutory notice to known heirs/devisees (62-3-705/-706) was filed. Not
    their names.

Also found live: York/Dorchester's docket is a DIFFERENT shape than
Charleston's -- 3 columns (Document, Activity, Description) vs Charleston's
2 (Activity, Description) -- and York's "Document" column links to a
GleamTech DocumentUltimate viewer confirmed, live, to be a PAID ("Add to
Cart" / watermark-removed-on-purchase) preview, not a free document image.
The link is captured as `document_url` purely as an informational pointer; it
is never fetched (FREE-only rule).

These fixtures mirror both real shapes 1:1 (same header strings). No network.
"""
from __future__ import annotations

from selectolax.parser import HTMLParser

from foreclosure_scraper.scrapers.counties_sc.sc_probate_net import (
    _docket_entries,
    _docket_flags,
    _parse_probate,
)

CASE_HEADER = (
    '<tr><td></td><td>Case Number</td><td>Case Name</td><td>Party</td>'
    '<td>Type of Case</td><td>Filing Date</td><td>County</td>'
    '<td>Appointment Date</td><td>Creditor Claim Due</td><td>Case Status</td></tr>'
)
PARTY_HEADER = (
    "<tr><th>First Name</th><th>Last Name</th><th>Middle Name</th><th>Suffix</th>"
    "<th>Address 1</th><th>Address 2</th><th>City</th><th>State</th><th>Zip</th>"
    "<th>Type</th></tr>"
)


def _case_row(case_number="2025ES1000772") -> str:
    return (f"<tr><td></td><td>{case_number}</td><td>SMITH, JANE</td>"
            f"<td>Attorney: DOE, JOHN</td><td>STANDARD ESTATE TESTATE</td>"
            f"<td>07/25/2025</td><td>Charleston Probate</td><td></td><td></td>"
            f"<td>Open</td></tr>")


def _party_table(table_id: str) -> str:
    pr_row = ("<tr><td>JANE</td><td>DOE</td><td></td><td></td>"
              "<td>1 MAIN ST</td><td></td><td>CHARLESTON</td><td>SC</td>"
              "<td>29401</td><td>PERSONAL REPRESENTATIVE</td></tr>")
    return f'<table id="{table_id}">{PARTY_HEADER}{pr_row}</table>'


def _docket_2col(table_id: str, *descriptions: str) -> str:
    """Charleston shape: (Activity, Description), Activity usually blank."""
    header = "<tr><th>Activity</th><th>Description</th></tr>"
    rows = "".join(f"<tr><td>&nbsp;</td><td>{d}</td></tr>" for d in descriptions)
    return f'<table id="{table_id}">{header}{rows}</table>'


def _docket_3col(table_id: str, *rows: tuple[str, str | None]) -> str:
    """York/Dorchester shape: (Document[link], Activity, Description)."""
    header = "<tr><th>Document</th><th>Activity</th><th>Description</th></tr>"
    body = ""
    for desc, doc_id in rows:
        doc_cell = (f"<td><a href='ViewImage.aspx?id={doc_id}' target='_blank'>"
                    f"View Image</a></td>" if doc_id else "<td>Not Available</td>")
        body += f"<tr>{doc_cell}<td>&nbsp;</td><td>{desc}</td></tr>"
    return f'<table id="{table_id}">{header}{body}</table>'


def _page(case_rows: str, sub_tables: str) -> str:
    return (f'<table id="ctl00_ContentPlaceHolder1_cgvCases">{CASE_HEADER}'
            f"{case_rows}</table>{sub_tables}")


# --------------------------------------------------------------------------- _docket_entries


def test_docket_entries_charleston_two_column_shape():
    html = _docket_2col("t1", "DEATH CERTIFICATE", "CREDITORS NOTICE",
                         "INVENTORY/APPRAISEMENT")
    tree = HTMLParser(html)
    entries = _docket_entries(tree.css_first("table"))
    assert entries == [
        {"activity": None, "description": "DEATH CERTIFICATE"},
        {"activity": None, "description": "CREDITORS NOTICE"},
        {"activity": None, "description": "INVENTORY/APPRAISEMENT"},
    ]


def test_docket_entries_york_three_column_shape_keeps_document_url():
    html = _docket_3col(
        "t1",
        ("DEATH CERTIFICATE", None),
        ("PAID NOTICE TO CREDITORS FEE", "13e3e1cc-12e5-44f6-b63b-ce839c9f1c8e"),
    )
    tree = HTMLParser(html)
    entries = _docket_entries(tree.css_first("table"))
    assert entries[0] == {"activity": None, "description": "DEATH CERTIFICATE"}
    assert entries[1]["description"] == "PAID NOTICE TO CREDITORS FEE"
    assert entries[1]["document_url"] == (
        "ViewImage.aspx?id=13e3e1cc-12e5-44f6-b63b-ce839c9f1c8e"
    )


def test_docket_entries_returns_empty_list_for_a_missing_table():
    assert _docket_entries(None) == []


def test_docket_entries_header_only_table_is_empty():
    html = _docket_2col("t1")
    tree = HTMLParser(html)
    assert _docket_entries(tree.css_first("table")) == []


# --------------------------------------------------------------------------- _docket_flags


def test_docket_flags_detects_inventory_and_info_to_heirs():
    entries = [
        {"activity": None, "description": "DEATH CERTIFICATE"},
        {"activity": None, "description": "INVENTORY/APPRAISEMENT"},
        {"activity": None, "description": "INFORMATION TO HEIRS AND DEVISEES"},
    ]
    flags = _docket_flags(entries)
    assert flags["has_inventory_appraisement"] is True
    assert flags["has_info_to_heirs"] is True
    assert flags["has_bond_waiver"] is False
    assert flags["has_renunciation"] is False


def test_docket_flags_all_false_when_none_filed():
    entries = [{"activity": None, "description": "DEATH CERTIFICATE"},
               {"activity": None, "description": "APPLICATION"}]
    flags = _docket_flags(entries)
    assert not any(flags.values())


def test_docket_flags_recognizes_supplemental_inventory_and_pod_info_to_heirs():
    """Real live-captured description variants, not just the canonical form."""
    entries = [{"activity": None, "description": "SUPPLEMENTAL INVENTORY & APPRAISEMENT"},
               {"activity": None, "description": "POD - INFO TO HEIRS"},
               {"activity": None, "description": "BOND WAIVER 344ES"},
               {"activity": None, "description": "RENUNCIATION FORM 302ES"}]
    flags = _docket_flags(entries)
    assert flags["has_inventory_appraisement"] is True
    assert flags["has_info_to_heirs"] is True
    assert flags["has_bond_waiver"] is True
    assert flags["has_renunciation"] is True


def test_docket_flags_empty_list_is_all_false():
    assert not any(_docket_flags([]).values())


# --------------------------------------------------------------------------- end-to-end via _parse_probate


def test_parse_probate_carries_docket_and_flags_into_raw():
    html = _page(
        _case_row(),
        _party_table("ctl00_ContentPlaceHolder1_cgvCases_ctl24_gvParties")
        + _docket_2col(
            "ctl00_ContentPlaceHolder1_cgvCases_ctl24_gvDocket",
            "DEATH CERTIFICATE", "INVENTORY/APPRAISEMENT",
            "INFORMATION TO HEIRS AND DEVISEES",
        ),
    )
    rows = _parse_probate(html, "Charleston", "SC")
    assert len(rows) == 1
    d = rows[0].raw["sc_probate_net"]
    assert d["docket"] == [
        {"activity": None, "description": "DEATH CERTIFICATE"},
        {"activity": None, "description": "INVENTORY/APPRAISEMENT"},
        {"activity": None, "description": "INFORMATION TO HEIRS AND DEVISEES"},
    ]
    assert d["has_inventory_appraisement"] is True
    assert d["has_info_to_heirs"] is True
    assert d["has_bond_waiver"] is False


def test_parse_probate_docket_is_none_when_no_docket_table_present():
    """A case row with no paired gvDocket sub-grid must not crash; docket
    stays None rather than []  -- consistent with this module's existing
    "absent, not falsely empty" convention for optional sub-grids."""
    html = _page(
        _case_row(),
        _party_table("ctl00_ContentPlaceHolder1_cgvCases_ctl24_gvParties"),
    )
    rows = _parse_probate(html, "Charleston", "SC")
    assert len(rows) == 1
    d = rows[0].raw["sc_probate_net"]
    assert d["docket"] is None
    assert d["has_inventory_appraisement"] is False
