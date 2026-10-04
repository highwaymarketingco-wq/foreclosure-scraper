"""SC DEW Lien Registry: the same footprint-artifact bug class as
test_terry_howe_flc_statewide_widen.py and test_nc_ecourts_statewide_widen.py --
found while investigating docs/completeness_audit_2026-09-29.md's 17-county
"zero tax_delinquent AND zero liens" cluster (item 6 of that follow-up task).

BUG. `_to_listing()`'s admission gate used `config.in_scope(county, "SC")`, the
narrow 7-county SC flip footprint (Spartanburg/Anderson/Pickens/Oconee/Cherokee/
Union/Laurens) plus a 5-county hand-picked coastal allowlist (`_SC_COASTAL`).
This module emits `ListingType.TAX_LIEN` rows, which is not in
`main._FLIP_LISTING_TYPES` -- a distress signal, not a flip -- so per the
2026-09-15 owner rule ("if its a distressed property its anywhere in nc and
sc") it belongs on `config.in_scope_distressed()` instead, same as every other
distress-type source already routes through `main._county_in_scope`. The old
gate silently dropped a real, named, in-state DEW lien for any of the ~39
non-footprint SC counties, including all 17 of the completeness audit's thin-
coverage cluster (Abbeville, Allendale, Bamberg, Barnwell, Calhoun, Chester,
Chesterfield, Darlington, Dillon, Dorchester, Edgefield, Fairfield, Greenwood,
Lee, Marlboro, McCormick, Williamsburg) -- both as a potential standalone lien
record and, more importantly in practice (this scraper is `disabled=True` as a
board source; see its class docstring), as a cross-reference candidate inside
`enrichment_dew_liens.enrich_dew_liens`, which calls `.fetch()` directly to
attach lien/debt data to EXISTING board leads by owner name. A Chester County
lead from `qpaybill_delinquent_roll` (or Dorchester, or any other non-footprint
county) could never have a DEW lien attached to it, because the DEW fetch threw
the matching lien row away before the enricher ever saw it.

The 2026-06-26 comment's original problem ("~8k address-less rows bloated the
board") is preserved unchanged: `bool(county)` still requires a real, named
county before a row is kept at all. Only the SECOND condition (which counties
count) was widened, from the flip footprint to the full distressed scope.
"""
from __future__ import annotations

from foreclosure_scraper.config import in_scope, in_scope_distressed
from foreclosure_scraper.validation import SC_COUNTIES as ALL_SC_COUNTIES
from foreclosure_scraper.scrapers.counties_sc.sc_dew_lien_registry import (
    _to_listing,
    _SC_COASTAL,
)

_SLUG = "counties_sc.sc_dew_lien_registry"

# The 17 counties docs/completeness_audit_2026-09-29.md section 3 flags as
# missing BOTH tax_delinquent and liens board-wide.
_THIN_CLUSTER = [
    "Abbeville", "Allendale", "Bamberg", "Barnwell", "Calhoun", "Chester",
    "Chesterfield", "Darlington", "Dillon", "Dorchester", "Edgefield",
    "Fairfield", "Greenwood", "Lee", "Marlboro", "McCormick", "Williamsburg",
]


def _row(county: str, name: str = "TEST DEBTOR LLC") -> dict:
    return {
        "TaxpayerName": name,
        "LienID": "X123",
        "LienType": "UI Tax",
        "LienStatus": "Active",
        "BalanceAmount": "500.00",
        "LienDateFiled": "2026-01-15",
        "EmployerAddress": f"123 MAIN ST, {county.upper()} COUNTY, SOMEWHERE SC 29706",
        "LienIssued": county,
    }


def test_thin_cluster_counties_are_outside_the_old_flip_footprint():
    # Confirms these are a real regression target: the OLD gate (in_scope, the
    # 7-county flip footprint) genuinely rejects every one of them, and none is
    # rescued by the coastal allowlist either -- so pre-fix, none could ever
    # have been kept by _to_listing.
    for c in _THIN_CLUSTER:
        assert not in_scope(c, "SC"), f"{c} unexpectedly IS in the flip footprint"
        assert c not in _SC_COASTAL, f"{c} unexpectedly IS in the coastal allowlist"


def test_thin_cluster_counties_pass_the_real_distressed_gate():
    # And confirms the NEW gate (in_scope_distressed) accepts every one of them,
    # i.e. the fix is not a no-op.
    for c in _THIN_CLUSTER:
        assert in_scope_distressed(c, "SC"), (
            f"{c} fails in_scope_distressed -- the widened gate would still drop it"
        )


def test_thin_cluster_lien_rows_now_survive_to_listing():
    for c in _THIN_CLUSTER:
        li = _to_listing(_row(c), _SLUG)
        assert li is not None, f"{c} DEW lien row was dropped by _to_listing"
        # str.title() mangles "McCormick" -> "Mccormick" (same known quirk flagged
        # in qpaybill_delinquent_roll.QPAYBILL_SUBS) -- compare case-insensitively
        # rather than assert an exact string this module never claimed to produce.
        assert li.county.lower() == c.lower()
        assert li.state == "SC"
        assert li.listing_type.value == "tax_lien"


def test_every_real_sc_county_passes():
    # Broader than the 17-county cluster: the fix widens coverage to the whole
    # 46-county SC gazetteer, not just the counties this specific audit named.
    for c in ALL_SC_COUNTIES:
        li = _to_listing(_row(c), _SLUG)
        assert li is not None, f"{c} DEW lien row was dropped by _to_listing"


def test_countyless_row_is_still_dropped():
    # The ORIGINAL 2026-06-26 fix (bloat from address-less statewide rows) must
    # still hold: a row with no resolvable county is dropped regardless of the
    # footprint-vs-distressed question.
    row = _row("Chester")
    row["EmployerAddress"] = None
    row["LienIssued"] = ""
    assert _to_listing(row, _SLUG) is None


def test_non_sc_state_is_still_dropped():
    row = _row("Chester")
    row["EmployerAddress"] = "123 MAIN ST, CHESTER COUNTY, SOMEWHERE NC 28601"
    assert _to_listing(row, _SLUG) is None


def test_row_with_no_name_is_still_dropped():
    row = _row("Chester", name="")
    row["DBAName"] = ""
    assert _to_listing(row, _SLUG) is None


def test_debt_breakdown_fields_are_captured():
    # 2026-10-01 per-source audit: live-verified against an 8,000-row real
    # Export_All_Ind pull that TaxAmount/InterestAmount/PenaltyAmount are
    # populated on the large majority of rows (7445/7342/7961 of 8000) but were
    # never read by _to_listing, even though BalanceAmount/LeinAmount already
    # were. LienID/LienStatus/LienDateFiled are genuinely null on every one of
    # those 8,000 rows on the bulk export endpoint -- not a parsing gap.
    row = _row("Chester")
    row["TaxAmount"] = "300.00"
    row["InterestAmount"] = "150.00"
    row["PenaltyAmount"] = "50.00"
    row["Cost_FeesAmount"] = "0.00"
    li = _to_listing(row, _SLUG)
    assert li is not None
    d = li.raw["sc_dew_lien_registry"]
    assert d["tax_principal"] == 300.0
    assert d["interest"] == 150.0
    assert d["penalty"] == 50.0
    assert d["cost_fees"] is None  # 0.00 -> falsy, _money() returns None by design


def test_last_updated_and_lien_periods_are_captured():
    # 2026-10-04 extraction-completeness audit: the NAME-SEARCH fallback path
    # (fired whenever the bulk Export_All_Ind pull times out) returns a richer
    # row than the bulk export. Live-verified on 220 real ACTIVE rows from a
    # capped SMITH name search: LienLastUpdated populated 220/220 and never
    # equal to LienDateFiled (a genuinely distinct date), LiendPeriods real
    # free text on 159/220 (e.g. "Q3-2009, Q4-2009, Q1-2010, Q2-2010, ...").
    row = _row("Chester")
    row["LienLastUpdated"] = "8/7/2020 12:00:00 AM"
    row["LiendPeriods"] = " Q3-2009, Q4-2009, Q1-2010"
    li = _to_listing(row, _SLUG)
    assert li is not None
    d = li.raw["sc_dew_lien_registry"]
    assert d["date_last_updated"] == "2020-08-07T00:00:00"
    assert d["lien_periods"] == "Q3-2009, Q4-2009, Q1-2010"


def test_payoff_button_label_is_not_mistaken_for_data():
    """'Payoff' is a static UI link label the SPA always sends as the literal
    string 'PayOff' (220/220 live) -- never a per-row fact. No field reads it;
    this just pins that nothing in _to_listing's raw dict is sourced from it."""
    row = _row("Chester")
    row["Payoff"] = "PayOff"
    li = _to_listing(row, _SLUG)
    assert li is not None
    assert "PayOff" not in str(li.raw["sc_dew_lien_registry"])


def test_no_last_updated_leaves_the_field_absent():
    row = _row("Chester")
    li = _to_listing(row, _SLUG)
    assert li is not None
    d = li.raw["sc_dew_lien_registry"]
    assert d["date_last_updated"] is None
    assert d["lien_periods"] is None
