"""2026-10-03 condition-code reconnaissance: Greenwood SC CAMA condemned layer.

Continuation of the condemned/code_enforcement breadth work in commit
6e00d55b, which explicitly left "is there a Spartanburg-style CAMA condition
field in any OTHER county" as scoped but not attempted. A 35-county live field
sweep (?f=json on each already-wired county's parcel/CAMA layer root) found
one genuine, previously-unwired hit: Greenwood SC's own CAMA layer carries a
real, populated Condition/ConditionText field (719 of 39,547 parcels rated
'Badly Worn' or 'Worn Out', live-verified by direct count query). Everything
else checked (Rutherford, Cleveland, Polk, Gaston, McDowell, Lincoln, Madison,
Mitchell, Carteret, Onslow, Brunswick, Pender, Laurens, Pickens, Colleton,
Beaufort, Georgetown, Charleston, Anderson, Oconee, Union, Horry, Aiken,
Barnwell, Berkeley, Calhoun, Chester, Darlington, Florence, Hampton,
Lancaster, Lexington, Saluda, Sumter, plus the NC OneMap statewide fallback)
was either a genuine negative (no such field exists) or already wired
elsewhere (Gaston's VacantImpro, Lincoln's VACANT -- both vacant-LAND, not
condition; Carteret -- already in enrichment_cama_condition.CAMA_SOURCES).

This also pins the Layer.condemned field's generalization: 2026-10-02 only
needed a hardcoded `lay.slug == "rockhill_code_demolition"` check (see
tests/test_code_enforcement_breadth_2026_10_02.py); this is the second real
case, so it is now an explicit per-layer field instead.
"""
from __future__ import annotations

import foreclosure_scraper.scrapers.counties_generic.arcgis_distress_layers as M


def _lay(slug):
    return next(x for x in M.LAYERS if x.slug == slug)


def test_greenwood_layer_is_registered_with_the_expected_shape():
    lay = _lay("greenwood_cama_condemned")
    assert lay.state == "SC"
    assert lay.county == "Greenwood"
    # a condition rating, not a condemnation (audit 2026-10-09)
    assert lay.condemned is False and lay.condition_rating is True
    assert lay.process == "poor_condition"
    # never a code_enforcement layer -- this is an appraiser rating, not a case
    assert lay.process != "code_enforcement"
    assert "ConditionText" in lay.where
    assert lay.parcel == "PIN"
    assert lay.situs == "SiteAddress"
    assert lay.value == "TaxValue_Total"


def test_greenwood_worn_out_row_is_a_poor_condition_not_a_condemnation():
    lay = _lay("greenwood_cama_condemned")
    li = M._to_listing({
        "PIN": "6999-999-001", "Owner": "EXAMPLE HOLDINGS LLC",
        "SiteAddress": "117 SAMPLE RD", "ConditionText": "Badly Worn",
        "YearBuilt": 0, "TaxValue_Total": 5000,
        "MailAddress": "720 EXAMPLE AVE STE 122",
        "MailCityState": "GREENWOOD, SC 29649-0000",
    }, lay)
    assert li is not None
    assert "condemned" not in li.raw and "code_enforcement" not in li.raw
    assert li.raw["distressed"] is True
    assert li.raw["condition_cama"] == {"source": "greenwood_cama_condemned", "condition": "Badly Worn",
                                        "condition_code": "Badly Worn", "distressed": True}
    assert li.parcel_id == "6999-999-001"
    assert li.owner_name == "EXAMPLE HOLDINGS LLC"
    assert li.street_address == "117 SAMPLE RD"
    assert li.tax_value == 5000
    assert li.foreclosure_process == "poor_condition"
    assert li.raw["arcgis_distress"]["layer"] == "greenwood_cama_condemned"


def test_greenwood_owner_mailing_block_is_built():
    lay = _lay("greenwood_cama_condemned")
    li = M._to_listing({
        "PIN": "6923-654-657", "Owner": "V S L M ENTERPRISES OF GREENWOOD",
        "SiteAddress": "59 HONEA PATH ST E", "ConditionText": "Worn Out",
        "YearBuilt": 1940, "TaxValue_Total": 23000,
        "MailAddress": "5317 HWY 178 S", "MailCityState": "NINETY SIX, SC 29666-0000",
    }, lay)
    om = li.raw["owner_mailing"]
    assert om["owner"] == "V S L M ENTERPRISES OF GREENWOOD"
    assert "5317 HWY 178 S" in om["mailing"]
    assert om["source"] == "greenwood_cama_condemned"


def test_greenwood_missing_address_and_parcel_drops_row():
    lay = _lay("greenwood_cama_condemned")
    li = M._to_listing({"PIN": "", "Owner": "X", "SiteAddress": "",
                        "ConditionText": "Worn Out"}, lay)
    assert li is None


# --------------------------------------------------------------------------
# Generalized Layer.condemned field (replaces the 2026-10-02 slug hardcode).
# --------------------------------------------------------------------------

def test_rockhill_demolition_still_stamps_condemned_via_the_generalized_field():
    lay = _lay("rockhill_code_demolition")
    assert lay.condemned is True
    li = M._to_listing({"CaseNumber": "CN-2026009", "Status": "Open",
                        "AddressText": "500 BIRCH ST"}, lay)
    assert li.raw["condemned"] is True
    assert "code_enforcement" not in li.raw


def test_new_hanover_demolition_permits_still_excluded():
    """Same process string ('demolition_permit') as Rock Hill's layer, but a
    homeowner's own voluntary teardown application, not a condemnation --
    condemned defaults to False and must NOT be set just because the process
    string matches."""
    lay = _lay("new_hanover_demolition_permits")
    assert lay.condemned is False
    li = M._to_listing({"PID": "R12345", "PERMIT_STATUS": "Issued",
                        "NUMBER": "600", "STREET": "CEDAR ST"}, lay)
    assert "condemned" not in li.raw


def test_only_rock_hill_opts_into_condemned():
    flagged = sorted(lay.slug for lay in M.LAYERS if lay.condemned)
    assert flagged == ["rockhill_code_demolition"]
