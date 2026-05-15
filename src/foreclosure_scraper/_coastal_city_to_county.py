"""City -> county lookup for NC + SC coastal towns.

Zillow's __NEXT_DATA__ doesn't carry county on listing items (only city,
state, zip, lat/lng, zpid). Without county we can't trip the
OCEANFRONT_COASTAL_COUNTIES override in main._in_scope. This tiny lookup
fills the gap for the coastal towns we actually care about.

Lowercased city -> (county, state). Use ``coastal_county_for`` to query.
"""
from __future__ import annotations


_LOOKUP: dict[str, tuple[str, str]] = {}


def _add(state: str, county: str, *cities: str) -> None:
    for c in cities:
        _LOOKUP[c.lower()] = (county, state)


# NC coast (north -> south)
_add("NC", "Currituck", "Corolla", "Carova", "Duck", "Currituck")
_add("NC", "Dare", "Southern Shores", "Kitty Hawk", "Kill Devil Hills",
     "Nags Head", "Manteo", "Wanchese", "Avon", "Salvo", "Rodanthe",
     "Waves", "Buxton", "Frisco", "Hatteras")
_add("NC", "Hyde", "Ocracoke", "Engelhard", "Swan Quarter")
_add("NC", "Carteret", "Atlantic Beach", "Pine Knoll Shores",
     "Indian Beach", "Salter Path", "Emerald Isle", "Beaufort",
     "Morehead City", "Newport")
_add("NC", "Onslow", "North Topsail Beach", "Sneads Ferry", "Jacksonville",
     "Holly Ridge", "Hubert", "Stella")
_add("NC", "Pender", "Topsail Beach", "Surf City", "Burgaw", "Hampstead",
     "Rocky Point")
_add("NC", "New Hanover", "Wrightsville Beach", "Carolina Beach",
     "Kure Beach", "Wilmington", "Castle Hayne")
_add("NC", "Brunswick", "Bald Head Island", "Oak Island", "Caswell Beach",
     "Southport", "Holden Beach", "Ocean Isle Beach", "Sunset Beach",
     "Calabash", "Shallotte", "Boiling Spring Lakes", "Leland",
     "Saint James", "St James")

# SC coast (north -> south)
_add("SC", "Horry", "North Myrtle Beach", "Cherry Grove", "Myrtle Beach",
     "Surfside Beach", "Garden City", "Conway", "Loris", "Little River",
     "Murrells Inlet")  # Murrells is split Horry/Georgetown; default Horry
_add("SC", "Georgetown", "Pawleys Island", "Litchfield Beach", "Litchfield",
     "Georgetown", "DeBordieu", "Andrews")
_add("SC", "Charleston", "Folly Beach", "Isle of Palms", "Sullivans Island",
     "Sullivan's Island", "Kiawah Island", "Seabrook Island", "Charleston",
     "Mount Pleasant", "James Island", "Johns Island", "Wadmalaw Island")
_add("SC", "Beaufort", "Hilton Head", "Hilton Head Island", "Fripp Island",
     "Hunting Island", "Daufuskie Island", "Beaufort", "Bluffton",
     "Port Royal", "Lady's Island", "Ladys Island", "Saint Helena Island",
     "St Helena Island")
_add("SC", "Colleton", "Edisto Beach", "Edisto Island", "Walterboro",
     "Cottageville")


def coastal_county_for(city: str | None, state: str | None) -> str | None:
    """Return the county name for a known NC/SC coastal town, or None.
    Match is case-insensitive on city; state is verified to prevent
    cross-state collisions (e.g. "Beaufort" exists in both NC and SC)."""
    if not city or not state:
        return None
    hit = _LOOKUP.get(city.strip().lower())
    if hit is None:
        return None
    county, st = hit
    if st != state.strip().upper():
        return None
    return county
