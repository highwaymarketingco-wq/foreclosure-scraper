"""Parse-time geo gate for the STATEWIDE trustee-firm sale calendars.

Brock & Scott and Hutchens/Foundation publish every pending NC + SC sale on one
page — ~660 rows, of which only ~90 sit inside the 18-county footprint. Gating at
parse time keeps the other ~85% out of the run entirely instead of carrying them
through dedupe + every enrichment just so `main._in_scope` can drop them at the end.

The gate is FOOTPRINT ∪ COASTAL, not footprint alone. `main._in_scope` already
admits coastal-county rows from these firms via the oceanfront lane: they carry a
street address, so `_oceanfront_pending` keeps them until the geocoder can test the
near-beach rule, and the post-geocode re-pass drops the inland ones. Gating to the
18 counties alone would delete those rows before the engine could judge them (the
current board carries ~45 such rows from these two sources), so coastal counties
pass the parse-time gate and the engine still makes the final call.
"""
from __future__ import annotations

from ...config import ALL_COUNTIES, in_scope

#: Mirror of `main.OCEANFRONT_COASTAL_COUNTIES`. Kept local because a scraper
#: module must never import `main` — main imports the scraper registry, so that
#: would be circular. `tests/test_law_firm_footprint.py` asserts the two sets stay
#: identical, so drift is caught by the suite rather than in production.
COASTAL_COUNTIES: frozenset[tuple[str, str]] = frozenset({
    ("Currituck", "NC"), ("Dare", "NC"), ("Hyde", "NC"), ("Carteret", "NC"),
    ("Onslow", "NC"), ("Pender", "NC"), ("New Hanover", "NC"), ("Brunswick", "NC"),
    ("Horry", "SC"), ("Georgetown", "SC"), ("Charleston", "SC"),
    ("Beaufort", "SC"), ("Colleton", "SC"),
})


#: lowercase name -> the CANONICAL spelling. `.title()` alone is not safe here:
#: it turns "mcdowell" (Brock's county slug) into "Mcdowell", and a dozen
#: enrichments key on the exact string "McDowell" (ArcGIS parcel layer, FHFA
#: value, geocode centroid, buyer match, Helene damage), so a title-cased row
#: would silently miss all of them.
_CANONICAL: dict[str, str] = {c.name.lower(): c.name for c in ALL_COUNTIES}
_CANONICAL.update({name.lower(): name for name, _state in COASTAL_COUNTIES})


def normalize_county(county: str | None) -> str | None:
    """Strip a ' County' suffix / trailing state code and canonicalize the name.

    Both firms write the county with the state glued on ("Yadkin, NC",
    "Gaston County") or as a URL slug ("new-hanover"), so every caller needs the
    same normalization before it can compare against the footprint.
    """
    if not county:
        return None
    name = county.strip()
    if not name:
        return None
    name = name.split(",")[0].strip()          # "Yadkin, NC" -> "Yadkin"
    if name.lower().endswith(" county"):
        name = name[: -len(" county")].strip()
    if not name:
        return None
    return _CANONICAL.get(name.lower(), name.title())


def in_footprint(county: str | None, state: str | None) -> bool:
    """True when (county, state) is one of the 18 tracked counties."""
    return in_scope(normalize_county(county), state)


def is_coastal(county: str | None, state: str | None) -> bool:
    """True for the coastal counties the oceanfront lane may still admit."""
    name = normalize_county(county)
    if not name or not state:
        return False
    return (name, state.upper()) in COASTAL_COUNTIES


def keep(county: str | None, state: str | None) -> bool:
    """Parse-time admission test: in-footprint, or a coastal-lane candidate."""
    return in_footprint(county, state) or is_coastal(county, state)
