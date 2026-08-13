"""Guard for the NC eCourts Smart Search (26SP* operator lane) grid parser.

Verified against a live 26SP* results page 2026-08-13: the generic strategies
mangled the Kendo grid (case# <- style, defendant <- file date, county null), so
scripts/parse_nc_ecourts_export.py got a dedicated Strategy 0 that reads the
stable .party-case-* cell classes. This fixture pins that format so a future
Odyssey markup tweak fails loud instead of silently producing garbage leads.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "parse_nc_ecourts_export",
    Path(__file__).resolve().parent.parent / "scripts" / "parse_nc_ecourts_export.py",
)
P = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(P)

# Two rows in the exact Smart Search Kendo shape: one foreclosure SP, one generic
# SP (towing). Real column classes + the "Clerk of Superior Court" location text.
_GRID = """
<div id="CasesGrid" class="k-grid"><table><tbody>
<tr class="k-master-row" role="row">
  <td class="card-heading party-case-caseid"><a class="caseLink" title="26SP000174-540">26SP000174-540</a></td>
  <td class="card-subheading party-case-style"><div class="big-search-type">IN THE MATTER OF THE FORECLOSURE OF A DEED OF TRUST Dorothy C. Pless</div></td>
  <td class="card-data party-case-filedate" data-label="File Date"><span title="08/12/2026">08/12/2026</span></td>
  <td class="card-data party-case-type" data-label="Type">Foreclosure (Special Proceeding)</td>
  <td class="card-data party-case-location" data-label="Location">Lincoln Clerk of Superior Court</td>
  <td class="card-data party-case-partyname" data-label="Party Name">Pless, Dorothy C.</td>
  <td class="card-data" data-label="Party Type">Defendant</td>
</tr>
<tr class="k-detail-row"><td class="k-detail-cell">disposition placeholder</td></tr>
<tr class="k-alt k-master-row" role="row">
  <td class="card-heading party-case-caseid"><a class="caseLink" title="26SP000426-660">26SP000426-660</a></td>
  <td class="card-subheading party-case-style"><div class="big-search-type">IN THE MATTER OF Smith &amp; Sons Towing LLC vs Eddie Leo Brown</div></td>
  <td class="card-data party-case-filedate" data-label="File Date"><span title="08/13/2026">08/13/2026</span></td>
  <td class="card-data party-case-type" data-label="Type">Special Proceeding</td>
  <td class="card-data party-case-location" data-label="Location">Onslow Clerk of Superior Court</td>
  <td class="card-data party-case-partyname" data-label="Party Name">Brown, Eddie Leo</td>
  <td class="card-data" data-label="Party Type">Defendant</td>
</tr>
</tbody></table></div>
"""


def test_smartsearch_grid_extracts_clean_fields():
    recs = P.parse_nc_ecourts_html(_GRID)
    by_case = {r["case_number"]: r for r in recs}
    assert set(by_case) == {"26SP000174-540", "26SP000426-660"}  # detail-rows skipped
    fc = by_case["26SP000174-540"]
    assert fc["defendant"] == "Pless, Dorothy C."          # NOT the file date
    assert fc["county"] == "Lincoln"                        # suffix fully stripped
    assert fc["case_type"] == "Foreclosure (Special Proceeding)"
    assert fc["filing_date"] == "08/12/2026"


def test_foreclosure_filter_and_listing_shape():
    recs = P.parse_nc_ecourts_html(_GRID)
    forc = [r for r in recs if "Foreclosure" in (r.get("case_type") or "")]
    assert len(forc) == 1 and forc[0]["case_number"] == "26SP000174-540"
    li = P.record_to_listing_dict(forc[0])
    assert li["owner_name"] == "Pless, Dorothy C."          # resolver reads owner_name
    assert li["county"] == "Lincoln" and li["state"] == "NC"
    assert li["case_number"] == "26SP000174-540"
