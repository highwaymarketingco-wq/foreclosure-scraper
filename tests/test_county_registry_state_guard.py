"""A county name shared with another state must not be adopted silently.

`<county>deeds.com` never states which state it is, and county names repeat.
Two hosts were one step from being adopted as NC register-of-deeds sources
purely because the URL pattern matched:

    hendersondeeds.com  ->  Henderson County KENTUCKY
    wilsondeeds.com     ->  Wilson County TENNESSEE

The first version of this guard only compared NC against SC, so both of those
came back "undetermined" -- it missed the exact case it was written for.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "bcr", Path(__file__).resolve().parent.parent / "scripts/build_county_registry.py")
bcr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bcr)


def test_unique_county_names_need_no_evidence():
    """Only one Yancey County exists in the US, so the name alone settles it."""
    assert bcr.state_confirmed("yancey", "NC", "https://x", "") is True


@pytest.mark.parametrize("county,state,html", [
    ("henderson", "NC", "Henderson County Clerk, Kentucky"),
    ("wilson", "NC", "Wilson County, Tennessee Register of Deeds"),
    ("york", "SC", "York County, Pennsylvania Recorder"),
    ("dorchester", "SC", "Dorchester County, Maryland"),
])
def test_another_state_named_means_wrong_county(county, state, html):
    assert bcr.state_confirmed(county, state, "https://x", html) is False


def test_vendor_asset_path_gives_the_state_away():
    """hendersondeeds.com names no state in prose but loads its CSS from
    cdn.bisonline.com/assets/css/ky/henderson/."""
    html = '<link href="https://cdn.bisonline.com/assets/css/ky/henderson/main.css">'
    assert bcr.state_confirmed("henderson", "NC", "https://x", html) is False


@pytest.mark.parametrize("html", [
    "Haywood County, North Carolina Register of Deeds",
    '<a href="https://www.deeds.claync.us/">Land Records</a>',
])
def test_our_state_named_or_state_qualified_domain_confirms(html):
    assert bcr.state_confirmed("haywood", "NC", "https://x", html) is True


def test_silence_is_undetermined_not_a_pass():
    """A shared-name page that states nothing must NOT read as confirmed --
    'unverified' is the whole point, so it gets checked by hand."""
    assert bcr.state_confirmed("haywood", "NC", "https://x",
                               "Haywood County Online Record System") is None


def test_ambiguous_list_covers_the_hosts_actually_in_use():
    for c in ("clay", "haywood", "york", "florence", "berkeley", "dorchester",
              "henderson", "wilson"):
        assert c in bcr.AMBIGUOUS_NAMES, f"{c} shares its name and is unguarded"


# --- denylist -------------------------------------------------------------
# Rejecting a domain on its homepage text is not enough. The sweep then finds
# the search subdomain, which may name no state at all and so comes back
# "undetermined" -- which is how Wilson TN got re-adopted as Wilson NC after
# the base domain had already been rejected.

@pytest.mark.parametrize("url", [
    "https://wilsondeeds.com/",
    "https://search.wilsondeeds.com/",
    "https://www.wilsondeeds.com/index.php",
    "https://hendersondeeds.com/",
    "https://search.hendersondeeds.com/",
])
def test_known_wrong_state_domains_are_rejected_on_every_subdomain(url):
    county = "wilson" if "wilson" in url else "henderson"
    assert bcr.state_confirmed(county, "NC", url, "") is False


def test_denylist_entries_carry_their_evidence():
    """A bare denylist rots. Each entry states how it was established."""
    for dom, why in bcr.KNOWN_WRONG_STATE.items():
        assert len(why) > 20, f"{dom} has no evidence recorded"


def test_denylist_does_not_reject_legitimate_hosts():
    for url in ("http://search.haywooddeeds.com/", "https://www.deeds.claync.us/",
                "http://search.yanceydeeds.com/"):
        assert bcr.state_confirmed("haywood", "NC", url, "North Carolina") is not False
