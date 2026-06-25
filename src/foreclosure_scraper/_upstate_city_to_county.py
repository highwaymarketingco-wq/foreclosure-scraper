"""City -> county lookup for the upstate-SC / western-NC footprint (+ the
common out-of-footprint NC/SC metros), used to attribute Crexi multifamily
slugs to a county at scrape time.

Crexi detail slugs carry a city or property name but never a county, and the
orchestrator's ``_in_scope`` gate runs at INGEST, *before* the geocode / GIS
enrichers — and the geocoder only fills lat/lng (it needs ``county`` to already
be set). So a Crexi row with no county is dropped before anything can attribute
it. This gazetteer lets the scraper set ``county`` from the city it parsed out
of the slug, so the in-footprint upstate/WNC rows survive the gate while the
statewide Charlotte / Columbia / Raleigh / Charleston rows are correctly
filtered out (they map to their real, out-of-scope county).

Lowercased city -> (county, state). Query via ``upstate_county_for``.

Coverage goal: every incorporated place + common CDP in the 18 in-footprint
counties, plus the high-volume out-of-footprint metros that dominate a
statewide Crexi multifamily search (so they get a real county and are denied
rather than slipping through the blank-county zip fallback).
"""
from __future__ import annotations


_LOOKUP: dict[str, tuple[str, str]] = {}


def _add(state: str, county: str, *cities: str) -> None:
    for c in cities:
        _LOOKUP[c.lower()] = (county, state)


# ---------------------------------------------------------------------------
# IN-FOOTPRINT — SC upstate (7 counties)
# ---------------------------------------------------------------------------
_add("SC", "Spartanburg", "Spartanburg", "Boiling Springs", "Inman", "Duncan",
     "Lyman", "Wellford", "Greer", "Landrum", "Campobello", "Chesnee",
     "Cowpens", "Pacolet", "Woodruff", "Roebuck", "Moore", "Reidville",
     "Startex", "Una", "Valley Falls")
_add("SC", "Anderson", "Anderson", "Belton", "Honea Path", "Williamston",
     "Pendleton", "Iva", "Pelzer", "West Pelzer", "Starr", "Townville",
     "Sandy Springs", "Powdersville", "Centerville", "Homeland Park")
_add("SC", "Pickens", "Pickens", "Clemson", "Easley", "Liberty", "Central",
     "Six Mile", "Norris", "Dacusville", "Pumpkintown")
_add("SC", "Oconee", "Walhalla", "Seneca", "Westminster", "West Union",
     "Salem", "Newry", "Fair Play", "Mountain Rest", "Tamassee", "Long Creek",
     "Oconee")
_add("SC", "Cherokee", "Gaffney", "Blacksburg", "Cherokee", "Chesnee")
_add("SC", "Union", "Union", "Jonesville", "Carlisle", "Lockhart", "Buffalo")
_add("SC", "Laurens", "Laurens", "Clinton", "Gray Court", "Fountain Inn",
     "Cross Hill", "Waterloo", "Ware Shoals", "Joanna", "Mountville",
     "Princeton")

# ---------------------------------------------------------------------------
# IN-FOOTPRINT — western NC (11 counties)
# ---------------------------------------------------------------------------
_add("NC", "Rutherford", "Rutherfordton", "Forest City", "Spindale",
     "Rutherford", "Lake Lure", "Chimney Rock", "Bostic", "Ellenboro",
     "Ruth", "Caroleen", "Henrietta", "Cliffside", "Union Mills")
_add("NC", "Cleveland", "Shelby", "Kings Mountain", "Boiling Springs",
     "Lawndale", "Fallston", "Casar", "Belwood", "Polkville", "Grover",
     "Earl", "Mooresboro", "Lattimore", "Waco", "Cleveland")
_add("NC", "Henderson", "Hendersonville", "Flat Rock", "Fletcher",
     "Laurel Park", "Mills River", "Etowah", "Edneyville", "Dana", "Zirconia",
     "Bat Cave", "Gerton", "Horse Shoe", "East Flat Rock", "Henderson")
_add("NC", "Polk", "Columbus", "Tryon", "Saluda", "Mill Spring", "Polk",
     "Lynn", "Green Creek")
_add("NC", "Gaston", "Gastonia", "Belmont", "Mount Holly", "Bessemer City",
     "Cherryville", "Dallas", "Stanley", "Lowell", "Ranlo", "McAdenville",
     "Cramerton", "Mount Holly", "High Shoals", "Spencer Mountain", "Gaston")
_add("NC", "Buncombe", "Asheville", "Black Mountain", "Weaverville",
     "Montreat", "Woodfin", "Biltmore Forest", "Swannanoa", "Fairview",
     "Candler", "Arden", "Leicester", "Barnardsville", "Enka", "Buncombe")
_add("NC", "Transylvania", "Brevard", "Rosman", "Pisgah Forest",
     "Lake Toxaway", "Cedar Mountain", "Transylvania", "Penrose", "Quebec",
     "Balsam Grove")
_add("NC", "McDowell", "Marion", "Old Fort", "Nebo", "Dysartsville",
     "Mcdowell", "Sugar Hill", "Glenwood", "Pleasant Gardens")
_add("NC", "Lincoln", "Lincolnton", "Denver", "Iron Station", "Vale",
     "Maiden", "Lincoln", "Crouse", "Boger City")
_add("NC", "Mitchell", "Bakersville", "Spruce Pine", "Mitchell", "Ledger",
     "Penland", "Little Switzerland")
_add("NC", "Burke", "Morganton", "Valdese", "Drexel", "Rutherford College",
     "Connelly Springs", "Glen Alpine", "Hildebran", "Long View", "Burke",
     "Icard", "Salem", "Hickory")   # Long View / Hickory straddle Burke/Catawba

# ---------------------------------------------------------------------------
# OUT-OF-FOOTPRINT but HIGH-VOLUME on a statewide Crexi MF search.
# These resolve to their REAL county so ``in_scope`` denies them deterministically
# (rather than letting a blank-county row sneak through the zip fallback).
# ---------------------------------------------------------------------------
# NC metros / common cities east of the footprint
_add("NC", "Mecklenburg", "Charlotte", "Matthews", "Huntersville",
     "Cornelius", "Davidson", "Pineville", "Mint Hill", "Mecklenburg")
_add("NC", "Wake", "Raleigh", "Cary", "Apex", "Wake Forest", "Morrisville",
     "Garner", "Holly Springs", "Fuquay Varina", "Wendell", "Knightdale")
_add("NC", "Forsyth", "Winston Salem", "Winston-Salem", "Kernersville",
     "Clemmons", "Forsyth")
_add("NC", "Guilford", "Greensboro", "High Point", "Jamestown", "Guilford")
_add("NC", "Durham", "Durham")
_add("NC", "Cumberland", "Fayetteville", "Cumberland", "Hope Mills")
_add("NC", "Catawba", "Hickory", "Newton", "Conover", "Catawba", "Claremont",
     "Maiden")
_add("NC", "Iredell", "Statesville", "Mooresville", "Iredell", "Troutman")
_add("NC", "Cabarrus", "Concord", "Kannapolis", "Cabarrus", "Harrisburg")
_add("NC", "New Hanover", "Wilmington")
_add("NC", "Pitt", "Greenville")    # NB: NC Greenville is Pitt; SC Greenville added below

# SC metros / common cities outside the upstate footprint
_add("SC", "Greenville", "Greenville", "Greer", "Mauldin", "Simpsonville",
     "Fountain Inn", "Travelers Rest", "Taylors", "Berea", "Wade Hampton")
# NOTE: Greer + Fountain Inn straddle county lines; the in-footprint adds above
# (Spartanburg/Laurens) are inserted first, then these Greenville entries
# OVERWRITE for the Greenville-side default. We re-assert the in-footprint
# winners explicitly at the bottom so footprint wins on true ties.
_add("SC", "Richland", "Columbia", "Forest Acres", "Dentsville",
     "St Andrews", "Richland")
_add("SC", "Lexington", "Lexington", "West Columbia", "Cayce", "Irmo",
     "Chapin", "Batesburg", "Leesville", "Gilbert", "Swansea")
_add("SC", "Charleston", "Charleston", "North Charleston", "Mount Pleasant",
     "Summerville", "Hanahan", "Goose Creek", "Ladson")
_add("SC", "Florence", "Florence", "Lake City", "Timmonsville", "Johnsonville")
_add("SC", "Horry", "Myrtle Beach", "Conway", "North Myrtle Beach",
     "Surfside Beach", "Loris")
_add("SC", "York", "Rock Hill", "Fort Mill", "York", "Clover", "Tega Cay")
_add("SC", "Aiken", "Aiken", "North Augusta")
_add("SC", "Sumter", "Sumter")
_add("SC", "Orangeburg", "Orangeburg")
_add("SC", "Chesterfield", "Chesterfield", "Cheraw", "Pageland")
_add("SC", "Darlington", "Darlington", "Hartsville", "Society Hill")
_add("SC", "Beaufort", "Beaufort", "Bluffton", "Hilton Head", "Port Royal")
_add("SC", "Newberry", "Newberry")
_add("SC", "Greenwood", "Greenwood")

# ---------------------------------------------------------------------------
# Re-assert in-footprint winners for ambiguous straddle cities so the
# footprint county wins on a true tie (call order safety net).
# ---------------------------------------------------------------------------
_LOOKUP["clinton"] = ("Laurens", "SC")          # not Clinton-the-other
_LOOKUP["fountain inn"] = ("Laurens", "SC")     # split Greenville/Laurens -> keep in-footprint
_LOOKUP["seneca"] = ("Oconee", "SC")
_LOOKUP["chesnee"] = ("Spartanburg", "SC")      # split Spartanburg/Cherokee -> Spartanburg
_LOOKUP["boiling springs"] = ("Spartanburg", "SC")  # SC Boiling Springs = Spartanburg
_LOOKUP["greer"] = ("Spartanburg", "SC")        # split Greenville/Spartanburg -> in-footprint


def upstate_county_for(city: str | None, state: str | None) -> str | None:
    """County for a known NC/SC city in or near the upstate/WNC footprint, or
    None. Case-insensitive on city; state-verified to avoid cross-state
    collisions (e.g. ``Greenville`` is Pitt in NC but Greenville in SC, and
    ``Boiling Springs`` exists in both states)."""
    if not city or not state:
        return None
    hit = _LOOKUP.get(city.strip().lower())
    if hit is None:
        return None
    county, st = hit
    if st != state.strip().upper():
        return None
    return county


#: All known city names (lowercased), longest first, so a multi-word city
#: ("north charleston", "boiling springs") is matched before a single token.
KNOWN_CITIES: tuple[str, ...] = tuple(
    sorted(_LOOKUP.keys(), key=lambda s: (-len(s.split()), -len(s)))
)
