"""A county column that looks like an SSN, licence or birth date is dropped when the response is read.

Lincoln NC has exposed TCSSN1/TCSSN2 (and TCDLC1/TCDLC2) on a public layer. The enrichers that ask a
layer for every column and keep the whole bag (raw['gis_attrs_full']) must never store one.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from foreclosure_scraper import enrichment_arcgis as ea
from foreclosure_scraper.sensitive_fields import drop_sensitive, is_sensitive_field

SENSITIVE = ["TCSSN1", "TCSSN2", "TCDLC1", "TCDLC2", "SSN", "ssn", "OWNER_SSN", "SSN_LAST4", "SocialSecurity",
             "SOCIAL_SEC_NO", "DriversLicense", "DRIVER_LIC_NO", "DL_NUM", "DLNUM", "DOB", "dob", "owner_dob",
             "DATE_OF_BIRTH", "DateOfBirth", "BirthDate", "BIRTH_DATE"]
KEEP = ["CLASSNAME", "LANDCLASSNAME", "ClassCode", "PARNO", "OWNNAME", "SITEADD", "ASSESSMENT", "LESSNAME",
        "GROSSNET", "ADOBE_STYLE", "TaxableValue", "OBJECTID", "DEEDBOOK", "TCNAM1", "TCADR1", "TCPHON"]


@pytest.mark.parametrize("name", SENSITIVE)
def test_sensitive_names_are_recognised(name):
    assert is_sensitive_field(name)


@pytest.mark.parametrize("name", KEEP)
def test_ordinary_columns_are_kept(name):
    assert not is_sensitive_field(name)


def test_drop_sensitive_keeps_the_rest_and_does_not_modify_its_input():
    bag = {"PARNO": "1", "TCSSN1": "x", "CLASSNAME": "RESIDENTIAL", "TCDLC1": "y", "OWNNAME": "A B"}
    out = drop_sensitive(bag)
    assert out == {"PARNO": "1", "CLASSNAME": "RESIDENTIAL", "OWNNAME": "A B"}
    assert "TCSSN1" in bag


class _Resp:
    status_code = 200

    def __init__(self, attrs):
        self._attrs = attrs

    def json(self):
        return {"features": [{"attributes": dict(self._attrs), "geometry": {"x": -82.1, "y": 35.2}}]}


class _Client:
    def __init__(self, attrs):
        self.attrs = attrs

    async def get(self, url, params=None, timeout=None, **kw):
        return _Resp(self.attrs)


def test_the_address_query_never_returns_a_sensitive_column():
    bag = {"PHYS_ADDR": "1 TEST RD", "OWNNAME": "A B", "CLASSNAME": "RES", "TCSSN1": "123", "DOB": "1900"}
    out = asyncio.run(ea._arcgis_query(_Client(bag), "http://x/arcgis/rest/services/s/MapServer/0/query",
                                       "PHYS_ADDR", "TEST RD", "1"))
    assert out, "the fake layer should have answered"
    for attrs in out:
        assert "TCSSN1" not in attrs and "DOB" not in attrs
        assert attrs["CLASSNAME"] == "RES" and attrs["OWNNAME"] == "A B"


def test_the_parcel_attribute_bag_is_filtered_before_it_is_stashed(monkeypatch):
    from foreclosure_scraper import enrichment_gis_attrs as ga

    bag = {"PIN": "1", "TCSSN2": "9", "CLASSNAME": "RES", "TCDLC2": "z"}

    @asynccontextmanager
    async def fake_client(**kw):
        yield _Client(bag)

    monkeypatch.setattr(ga, "client", fake_client)
    src = open(ga.__file__, encoding="utf-8").read()
    assert 'li.raw["gis_attrs_full"] = drop_sensitive(attrs)' in src
    assert src.count("return drop_sensitive(feats[0][\"attributes\"])") == 2
