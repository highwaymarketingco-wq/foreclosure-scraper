"""City -> county lookup for NC + SC coastal towns.

Zillow's __NEXT_DATA__ doesn't carry county on listing items (only city,
state, zip, lat/lng, zpid). Without county we can't trip the
OCEANFRONT_COASTAL_COUNTIES override in main._in_scope. This tiny lookup
fills the gap for the coastal towns we actually care about.

Keyed by ``(lowercased city, uppercased state)`` -> county. Keying on the
state is required because the same town name lives in both states (e.g.
"Beaufort" the TOWN is in Carteret County NC, while "Beaufort" is also a
COUNTY in SC, with a town of the same name). A flat city-only dict would
let one state's entry silently clobber the other's. Use
``coastal_county_for`` to query.
"""
from __future__ import annotations


_LOOKUP: dict[tuple[str, str], str] = {}


def _add(state: str, county: str, *cities: str) -> None:
    st = state.strip().upper()
    for c in cities:
        _LOOKUP[(c.lower(), st)] = county


# NC coast (north -> south)
# Currituck: Duck is NOT here — Duck is in Dare County (see below).
_add("NC", "Currituck", "Corolla", "Carova", "Currituck")
_add("NC", "Dare", "Southern Shores", "Kitty Hawk", "Kill Devil Hills",
     "Nags Head", "Manteo", "Wanchese", "Avon", "Salvo", "Rodanthe",
     "Waves", "Buxton", "Frisco", "Hatteras", "Duck")
_add("NC", "Hyde", "Ocracoke", "Engelhard", "Swan Quarter")
# Carteret: includes Beaufort the TOWN (NC), Cape Carteret, and Swansboro's
# Carteret-side border — but Swansboro proper is billed to Onslow (below).
_add("NC", "Carteret", "Atlantic Beach", "Pine Knoll Shores",
     "Indian Beach", "Salter Path", "Emerald Isle", "Beaufort",
     "Morehead City", "Newport", "Cape Carteret", "Cedar Point")
# Onslow: Swansboro straddles the Onslow/Carteret line; bill it to Onslow.
_add("NC", "Onslow", "North Topsail Beach", "Sneads Ferry", "Jacksonville",
     "Holly Ridge", "Hubert", "Stella", "Swansboro", "Richlands")
_add("NC", "Pender", "Topsail Beach", "Surf City", "Burgaw", "Hampstead",
     "Rocky Point", "Scotts Hill")
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
# Beaufort SC: the COUNTY. "Beaufort" the town here is the SC seat, distinct
# from Beaufort the town in Carteret County NC (above) — kept apart by state.
_add("SC", "Beaufort", "Hilton Head", "Hilton Head Island", "Fripp Island",
     "Hunting Island", "Daufuskie Island", "Beaufort", "Bluffton",
     "Port Royal", "Lady's Island", "Ladys Island", "Saint Helena Island",
     "St Helena Island")
_add("SC", "Colleton", "Edisto Beach", "Edisto Island", "Walterboro",
     "Cottageville")


def coastal_county_for(city: str | None, state: str | None) -> str | None:
    """Return the county name for a known NC/SC coastal town, or None.
    Match is case-insensitive on city; state is part of the key so
    cross-state collisions (e.g. "Beaufort" exists in both NC and SC) are
    resolved correctly rather than one clobbering the other."""
    if not city or not state:
        return None
    return _LOOKUP.get((city.strip().lower(), state.strip().upper()))
