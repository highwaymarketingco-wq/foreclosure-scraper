"""raw['owner_mailing'] is not always a dict, and pretending it is has cost twice.

Most sources write a dict. Three Spartanburg sources (spartanburg_vacant,
spartanburg_condemned, spartanburg_delinquent_tax) write a bare STRING that IS
the mailing address — 5,098 leads on the 2026-08-03 board.

`or {}` cannot rescue a truthy str, so `(raw.get("owner_mailing") or {}).get(x)`
raises AttributeError. That killed the whole mail spine on the 2026-07-31 run
(enrichment_owner_mailing.py:494) and the SAME pattern was still live in five
other places, including enrich_promote_owner — the one enricher whose entire job
is filling the blank owner_name field that blocks outreach.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_owner_mailing import mailing_dict
from foreclosure_scraper.enrichment_promote_owner import _cand, enrich_promote_owner


class _Lead:
    def __init__(self, raw, owner_name=None):
        self.raw = raw
        self.owner_name = owner_name


@pytest.mark.parametrize("value,expected", [
    ({"owner": "SMITH JOHN", "mailing": "1 A ST"}, {"owner": "SMITH JOHN", "mailing": "1 A ST"}),
    ("123 MAIN ST, ASHEVILLE NC", {"mailing": "123 MAIN ST, ASHEVILLE NC"}),
    ("", {}),
    ("   ", {}),
    (None, {}),
    (["not", "a", "dict"], {}),
    (42, {}),
])
def test_mailing_dict_normalises_every_shape_seen_in_the_wild(value, expected):
    assert mailing_dict({"owner_mailing": value}) == expected


def test_mailing_dict_accepts_a_lead_or_a_raw_dict():
    li = _Lead({"owner_mailing": {"owner": "DOE JANE"}})
    assert mailing_dict(li)["owner"] == "DOE JANE"
    assert mailing_dict(li.raw)["owner"] == "DOE JANE"


def test_promote_owner_survives_a_string_owner_mailing():
    """The exact crash: a truthy str reaching .get()."""
    assert _cand(_Lead({"owner_mailing": "123 MAIN ST, ASHEVILLE NC"})) is None


def test_promote_owner_survives_a_non_dict_gis_block():
    assert _cand(_Lead({"gis": "not-a-dict"})) is None


def test_promote_owner_still_promotes_from_a_dict():
    assert _cand(_Lead({"owner_mailing": {"owner": "CRANK BETTY GARVIN HEIRS"}})) \
        == "CRANK BETTY GARVIN HEIRS"


def test_promote_owner_prefers_the_tax_owner_over_the_gis_owner():
    lead = _Lead({"owner_mailing": {"owner": "TAX OWNER"}, "gis": {"owner": "GIS OWNER"}})
    assert _cand(lead) == "TAX OWNER"


def test_one_string_lead_cannot_take_down_the_whole_pass():
    """The failure that matters: the pass used to die on the first string-typed
    lead, so every lead after it kept a blank owner_name and stayed unmailable."""
    leads = [
        _Lead({"owner_mailing": "1 STRING ST"}),                    # the landmine
        _Lead({"owner_mailing": {"owner": "SMITH JOHN"}}),
        _Lead({"gis": {"owner": "JONES MARY"}}),
    ]
    stats = enrich_promote_owner(leads)
    assert stats["promoted"] == 2, stats
    assert leads[1].owner_name == "SMITH JOHN"
    assert leads[2].owner_name == "JONES MARY"


def test_promote_never_overwrites_an_existing_owner():
    lead = _Lead({"owner_mailing": {"owner": "TAX OWNER"}}, owner_name="PARSED DEFENDANT")
    enrich_promote_owner([lead])
    assert lead.owner_name == "PARSED DEFENDANT"
