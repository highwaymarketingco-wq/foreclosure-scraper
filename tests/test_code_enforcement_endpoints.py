"""Code-enforcement endpoints must serve the city they claim to.

THE INCIDENT THIS GUARDS. A former "Charlotte" entry pointed at
    services5.arcgis.com/86gdKBxZf7GIt2Or/.../Code_Enforcement_Cases
which is the City of YUCAIPA, CALIFORNIA -- out of footprint by about 2,000 miles.
It was disabled, correctly. But the note left behind said "no in-footprint NC/SC city
code-enforcement feed has been verified yet", and that stopped being true without anyone
re-checking: Charlotte publishes its own on gis.charlottenc.gov, and Asheville on
gis.ashevillenc.gov. code_vacancy was present in only 2 of 18 footprint counties on the
live board -- the worst-covered lane in the engine -- while a working feed sat unwired.

So this file asserts two different things:
  * every endpoint is on a host that plausibly belongs to its own city (the Yucaipa test)
  * the config shape is complete, so a half-wired entry fails here instead of silently
    tagging nothing
"""
from __future__ import annotations

import re

import pytest

from foreclosure_scraper.enrichment_code_enforcement import CITY_ENDPOINTS, SEVERE_ENDPOINTS

ALL = {**{f"{k} (cases)": v for k, v in CITY_ENDPOINTS.items()},
       **{f"{k} (severe)": v for k, v in SEVERE_ENDPOINTS.items()}}

#: The host must contain the city's own name, or be an ArcGIS Online org id that a human
#: has verified. Bare services*.arcgis.com entries are exactly how Yucaipa got in.
CITY_HOST_TOKEN = {"Asheville": "ashevillenc", "Charlotte": "charlottenc"}


@pytest.mark.parametrize("label", sorted(ALL))
def test_the_endpoint_host_belongs_to_its_own_city(label):
    city = label.split(" (")[0]
    url = ALL[label]["url"]
    token = CITY_HOST_TOKEN.get(city)
    assert token, f"{city} has no verified host token -- add one deliberately, do not guess"
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    assert token in host, (
        f"{label} points at {host!r}, which does not carry {token!r}. This is the Yucaipa "
        f"check: a generic services*.arcgis.com host can serve ANY city in the country."
    )


@pytest.mark.parametrize("label", sorted(ALL))
def test_every_endpoint_is_a_layer_url_not_a_query_url(label):
    """_fetch_violations_for_listing appends /query itself; a url that already ends in
    /query produces .../query/query and silently returns nothing."""
    url = ALL[label]["url"]
    assert not url.rstrip("/").endswith("/query"), f"{label} must be the LAYER url"
    assert re.search(r"/(MapServer|FeatureServer)/\d+$", url.rstrip("/")), (
        f"{label} must end in a numeric layer id")


@pytest.mark.parametrize("label", sorted(ALL))
def test_every_endpoint_declares_the_fields_the_enricher_reads(label):
    cfg = ALL[label]
    for key in ("addr_fields", "violation_fields", "status_fields", "date_fields"):
        assert key in cfg, f"{label} is missing {key}"
        assert isinstance(cfg[key], tuple) and cfg[key], f"{label}.{key} must be a non-empty tuple"
        assert all(isinstance(f, str) and f for f in cfg[key])


def test_charlotte_carries_a_parcel_join_key():
    """Charlotte rows carry ParcelId, a direct Mecklenburg parcel key. That is far
    stronger than the 250ft lat/lng proximity fallback this enricher otherwise uses."""
    assert CITY_ENDPOINTS["Charlotte"]["parcel_field"] == "ParcelId"


def test_the_demolition_layer_is_kept_separate_and_carries_its_severity():
    """A standing order to demolish is a terminal condition, not an ordinary Housing
    case: the owner is about to lose the improvement and keep the lot. Averaging it in
    with 3,966 routine cases would bury the strongest signal in the lane."""
    sev = SEVERE_ENDPOINTS["Charlotte"]
    assert sev["severity"] == "order_to_demolish"
    assert "Demolish" in sev["url"]
    assert sev["url"] != CITY_ENDPOINTS["Charlotte"]["url"]


def test_asheville_was_not_disturbed():
    """It was the only wired city and it works; this change must not have touched it."""
    a = CITY_ENDPOINTS["Asheville"]
    assert "ashevillenc.gov" in a["url"]
    assert a["addr_fields"] == ("address",)
    assert a["status_fields"] == ("record_status",)
