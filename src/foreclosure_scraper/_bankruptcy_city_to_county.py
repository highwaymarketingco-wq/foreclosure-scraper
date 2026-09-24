"""City -> county lookup for ALL 146 NC + SC counties, used by
national/courtlistener_bankruptcy.py to attribute a bankruptcy filing's
county from a city name found in the case caption.

Why this exists (2026-09-23, docs/coverage_gap_build_plan_2026-09-23.md
item 3): CourtListener's bankruptcy dockets have no address field, and the
4 federal bankruptcy districts covering NC+SC (ncwb/ncmb/nceb/scb) already
partition the entirety of both states structurally — there is no per-county
restriction at the API layer. The only thing standing between "we already
fetch every county's dockets" and "we can attribute them to a county" was
a hardcoded 21-county/~28-town dict in courtlistener_bankruptcy.py itself.
This module replaces that dict with full 146-county coverage.

Reuse decision: this repo already has two similar city->county gazetteers,
`_upstate_city_to_county.py` (18-county WNC/upstate footprint + common
out-of-footprint metros, flat ``city -> (county, state)`` dict) and
`_coastal_city_to_county.py` (NC+SC coastal towns, ``(city, state) ->
county``). Neither was imported/merged into this module:

  * Shape mismatch — one is keyed by city only (with state carried in the
    value), the other by (city, state); building a third, self-contained,
    consistently-keyed table was less error-prone than reconciling two
    different key shapes into a merge.
  * Curation intent differs — those two files intentionally list many small
    alternate/CDP town names for PARCEL-level slug/address matching (Crexi,
    Zillow). A caption-substring matcher doesn't need that density and
    inherits false-positive risk from it (a small town name is more likely
    to coincidentally appear in unrelated text).
  * A live collision was found while cross-checking coverage: upstate file's
    Henderson-County entry self-adds the bare county name ("Henderson") as
    one of Henderson County's own matched cities (its own last _add() call:
    ``_add("NC", "Henderson", "Hendersonville", ..., "Henderson")``). But
    the actual TOWN of Henderson, NC is Vance County's seat, not Henderson
    County's (Henderson County's seat is the differently-named
    Hendersonville). Reusing that entry as-is would have misattributed
    Vance County bankruptcy filers whose caption says "Henderson" to
    Henderson County instead. This module maps ("henderson", "NC") to Vance
    County (see below) independently of that file, since it is never
    consulted for this module's resolution.

So: a fresh, complete table, following the SAME safety pattern as
`_coastal_city_to_county.py` (state is part of the key — required because
county-seat names collide across NC/SC constantly: Greenville, Camden,
Marion, Columbia, Lexington, Clinton, Williamston all name a real place in
BOTH states or two different counties of the SAME state). Coverage is each
county's SEAT plus, for the larger/better-known counties, 1-2 additional
well-known towns — kept deliberately narrower than exhaustive-CDP coverage
where a town's county is genuinely split/ambiguous in reality (e.g. Hickory
straddles Catawba/Burke/Alexander/Caldwell; Rocky Mount straddles Nash/
Edgecombe; Summerville and Goose Creek straddle Charleston/Berkeley/
Dorchester) — those are left unmapped rather than asserting an unverified
single-county guess.

Query via ``bankruptcy_county_for(city, state)``.
"""
from __future__ import annotations


_LOOKUP: dict[tuple[str, str], str] = {}


def _add(state: str, county: str, *cities: str) -> None:
    st = state.strip().upper()
    for c in cities:
        _LOOKUP[(c.lower(), st)] = county


# =============================================================================
# NORTH CAROLINA — all 100 counties
# =============================================================================

_add("NC", "Alamance", "Graham", "Burlington")  # Burlington is Alamance's
                                                 # largest city (bigger than
                                                 # the seat, Graham).
_add("NC", "Alexander", "Taylorsville")
_add("NC", "Alleghany", "Sparta")
_add("NC", "Anson", "Wadesboro")
_add("NC", "Ashe", "Jefferson")
_add("NC", "Avery", "Newland")
_add("NC", "Beaufort", "Washington")  # NC town Washington = Beaufort Co
                                       # seat, NOT Washington County (see
                                       # Washington County below — its seat
                                       # is the differently-named Plymouth).
_add("NC", "Bertie", "Windsor")
_add("NC", "Bladen", "Elizabethtown")
_add("NC", "Brunswick", "Bolivia", "Shallotte", "Southport")
_add("NC", "Buncombe", "Asheville")
_add("NC", "Burke", "Morganton")
_add("NC", "Cabarrus", "Concord", "Kannapolis")
_add("NC", "Caldwell", "Lenoir")
_add("NC", "Camden", "Camden")  # NC COUNTY seat -- distinct from Camden, SC
                                # (Kershaw County's seat, added below).
_add("NC", "Carteret", "Beaufort")  # NC TOWN Beaufort = Carteret's seat,
                                     # distinct from Beaufort COUNTY (NC,
                                     # above) and Beaufort, SC (below).
_add("NC", "Caswell", "Yanceyville")
_add("NC", "Catawba", "Newton", "Conover")  # Hickory deliberately omitted --
                                             # its downtown straddles
                                             # Catawba/Burke/Alexander/
                                             # Caldwell; no single-county
                                             # answer is safe to assert.
_add("NC", "Chatham", "Pittsboro", "Siler City")
_add("NC", "Cherokee", "Murphy")  # NC COUNTY -- distinct from Cherokee, SC
                                   # (Gaffney, below).
_add("NC", "Chowan", "Edenton")
_add("NC", "Clay", "Hayesville")
_add("NC", "Cleveland", "Shelby")
_add("NC", "Columbus", "Whiteville")  # Columbus COUNTY's seat is Whiteville
                                       # -- "Columbus" the TOWN is Polk
                                       # County's seat (below); kept apart.
_add("NC", "Craven", "New Bern")
_add("NC", "Cumberland", "Fayetteville")
_add("NC", "Currituck", "Currituck")
_add("NC", "Dare", "Manteo")
_add("NC", "Davidson", "Lexington")  # NC TOWN Lexington -- distinct from
                                      # Lexington, SC (Lexington County's
                                      # seat, below).
_add("NC", "Davie", "Mocksville")
_add("NC", "Duplin", "Kenansville", "Warsaw")
_add("NC", "Durham", "Durham")
_add("NC", "Edgecombe", "Tarboro")  # Rocky Mount omitted -- straddles
                                     # Nash/Edgecombe, no safe single answer.
_add("NC", "Forsyth", "Winston-Salem", "Winston Salem", "Kernersville")
_add("NC", "Franklin", "Louisburg")
_add("NC", "Gaston", "Gastonia")
_add("NC", "Gates", "Gatesville")
_add("NC", "Graham", "Robbinsville")
_add("NC", "Granville", "Oxford")
_add("NC", "Greene", "Snow Hill")
_add("NC", "Guilford", "Greensboro", "High Point")
_add("NC", "Halifax", "Halifax", "Roanoke Rapids")
_add("NC", "Harnett", "Lillington", "Dunn")
_add("NC", "Haywood", "Waynesville")
_add("NC", "Henderson", "Hendersonville")  # Henderson COUNTY's seat --
                                            # "Henderson" the TOWN is Vance
                                            # County's seat (below); kept
                                            # apart (see module docstring).
_add("NC", "Hertford", "Winton")
_add("NC", "Hoke", "Raeford")
_add("NC", "Hyde", "Swan Quarter")
_add("NC", "Iredell", "Statesville", "Mooresville")
_add("NC", "Jackson", "Sylva", "Cullowhee")
_add("NC", "Johnston", "Smithfield", "Clayton")
_add("NC", "Jones", "Trenton")
_add("NC", "Lee", "Sanford")  # NC COUNTY -- distinct from Lee, SC
                               # (Bishopville, below).
_add("NC", "Lenoir", "Kinston")
_add("NC", "Lincoln", "Lincolnton")
_add("NC", "Macon", "Franklin")  # NC TOWN Franklin = Macon's seat --
                                  # distinct from Franklin COUNTY (seat
                                  # Louisburg, above).
_add("NC", "Madison", "Marshall")
_add("NC", "Martin", "Williamston")  # NC TOWN Williamston -- distinct from
                                      # Williamston, SC (an Anderson County
                                      # town).
_add("NC", "McDowell", "Marion")  # NC TOWN Marion -- distinct from Marion,
                                   # SC (Marion County's seat, below).
_add("NC", "Mecklenburg", "Charlotte")
_add("NC", "Mitchell", "Bakersville")
_add("NC", "Montgomery", "Troy")
_add("NC", "Moore", "Carthage", "Pinehurst", "Southern Pines")
_add("NC", "Nash", "Nashville")  # Rocky Mount omitted -- see Edgecombe.
_add("NC", "New Hanover", "Wilmington")
_add("NC", "Northampton", "Jackson")  # NC TOWN Jackson = Northampton's
                                       # seat -- distinct from Jackson
                                       # COUNTY (seat Sylva, above).
_add("NC", "Onslow", "Jacksonville")
_add("NC", "Orange", "Hillsborough", "Chapel Hill")
_add("NC", "Pamlico", "Bayboro")
_add("NC", "Pasquotank", "Elizabeth City")
_add("NC", "Pender", "Burgaw")
_add("NC", "Perquimans", "Hertford")  # NC TOWN Hertford = Perquimans' seat
                                       # -- distinct from Hertford COUNTY
                                       # (seat Winton, above).
_add("NC", "Person", "Roxboro")
_add("NC", "Pitt", "Greenville")  # NC TOWN Greenville -- distinct from
                                   # Greenville, SC (below).
_add("NC", "Polk", "Columbus", "Tryon")  # NC TOWN Columbus = Polk's seat --
                                          # distinct from Columbus COUNTY
                                          # (seat Whiteville, above).
_add("NC", "Randolph", "Asheboro")
_add("NC", "Richmond", "Rockingham", "Hamlet")  # NC TOWN Rockingham =
                                                 # Richmond's seat --
                                                 # distinct from Rockingham
                                                 # COUNTY (seat Wentworth,
                                                 # below).
_add("NC", "Robeson", "Lumberton", "Pembroke")
_add("NC", "Rockingham", "Wentworth", "Reidsville", "Eden")
_add("NC", "Rowan", "Salisbury")
_add("NC", "Rutherford", "Rutherfordton")
_add("NC", "Sampson", "Clinton")  # NC TOWN Clinton -- distinct from
                                   # Clinton, SC (a Laurens County town).
_add("NC", "Scotland", "Laurinburg")
_add("NC", "Stanly", "Albemarle")
_add("NC", "Stokes", "Danbury")
_add("NC", "Surry", "Dobson", "Mount Airy")
_add("NC", "Swain", "Bryson City")
_add("NC", "Transylvania", "Brevard")
_add("NC", "Tyrrell", "Columbia")  # NC TOWN Columbia -- distinct from
                                    # Columbia, SC (Richland County's seat
                                    # and state capital, below).
_add("NC", "Union", "Monroe")  # NC COUNTY -- distinct from Union, SC
                                # (below).
_add("NC", "Vance", "Henderson")  # NC TOWN Henderson = Vance's seat --
                                   # see module docstring re: the upstate
                                   # gazetteer's differing Henderson entry.
_add("NC", "Wake", "Raleigh")
_add("NC", "Warren", "Warrenton")
_add("NC", "Washington", "Plymouth")  # Washington COUNTY's seat is
                                       # Plymouth -- "Washington" the TOWN
                                       # is Beaufort County's seat (above).
_add("NC", "Watauga", "Boone")
_add("NC", "Wayne", "Goldsboro", "Mount Olive")
_add("NC", "Wilkes", "Wilkesboro")
_add("NC", "Wilson", "Wilson")
_add("NC", "Yadkin", "Yadkinville")
_add("NC", "Yancey", "Burnsville")

# =============================================================================
# SOUTH CAROLINA — all 46 counties
# =============================================================================

_add("SC", "Abbeville", "Abbeville")
_add("SC", "Aiken", "Aiken", "North Augusta")
_add("SC", "Allendale", "Allendale")
_add("SC", "Anderson", "Anderson", "Belton", "Williamston")
_add("SC", "Bamberg", "Bamberg")
_add("SC", "Barnwell", "Barnwell")
_add("SC", "Beaufort", "Beaufort", "Bluffton", "Hilton Head Island")
_add("SC", "Berkeley", "Moncks Corner")  # Goose Creek/Summerville omitted --
                                          # both straddle Berkeley/
                                          # Charleston/Dorchester.
_add("SC", "Calhoun", "St Matthews", "Saint Matthews")
_add("SC", "Charleston", "Charleston", "North Charleston", "Mount Pleasant")
_add("SC", "Cherokee", "Gaffney")  # SC COUNTY -- distinct from Cherokee,
                                    # NC (Murphy, above).
_add("SC", "Chester", "Chester")
_add("SC", "Chesterfield", "Chesterfield", "Cheraw")
_add("SC", "Clarendon", "Manning")
_add("SC", "Colleton", "Walterboro")
_add("SC", "Darlington", "Darlington", "Hartsville")
_add("SC", "Dillon", "Dillon")
_add("SC", "Dorchester", "St George", "Saint George")  # Summerville
                                                         # omitted -- see
                                                         # Berkeley note.
_add("SC", "Edgefield", "Edgefield")
_add("SC", "Fairfield", "Winnsboro")
_add("SC", "Florence", "Florence")
_add("SC", "Georgetown", "Georgetown")
_add("SC", "Greenville", "Greenville", "Greer", "Mauldin", "Simpsonville")
_add("SC", "Greenwood", "Greenwood")
_add("SC", "Hampton", "Hampton")
_add("SC", "Horry", "Conway")  # SC COUNTY seat -- Myrtle Beach is the
                                # famous/populous city but Conway is the
                                # actual seat; Horry is denied in the flip
                                # footprint but not in scope for distress
                                # leads (bankruptcy is state-wide).
_add("SC", "Jasper", "Ridgeland")
_add("SC", "Kershaw", "Camden")  # SC TOWN Camden -- distinct from Camden,
                                  # NC (a whole county, above).
_add("SC", "Lancaster", "Lancaster")
_add("SC", "Laurens", "Laurens", "Clinton")
_add("SC", "Lee", "Bishopville")  # SC COUNTY -- distinct from Lee, NC
                                   # (Sanford, above).
_add("SC", "Lexington", "Lexington", "Cayce", "Irmo")  # SC COUNTY -- distinct
                                                         # from Lexington, NC
                                                         # (a Davidson County
                                                         # town, above).
_add("SC", "Marion", "Marion")  # SC COUNTY -- distinct from Marion, NC
                                  # (a McDowell County town, above).
_add("SC", "Marlboro", "Bennettsville")
_add("SC", "McCormick", "McCormick")
_add("SC", "Newberry", "Newberry")
_add("SC", "Oconee", "Walhalla", "Seneca")
_add("SC", "Orangeburg", "Orangeburg")
_add("SC", "Pickens", "Pickens", "Easley", "Clemson")
_add("SC", "Richland", "Columbia", "Forest Acres")  # SC state capital --
                                                      # distinct from
                                                      # Columbia, NC (a
                                                      # Tyrrell County town,
                                                      # above).
_add("SC", "Saluda", "Saluda")
_add("SC", "Spartanburg", "Spartanburg", "Boiling Springs")
_add("SC", "Sumter", "Sumter")
_add("SC", "Union", "Union")  # SC COUNTY -- distinct from Union, NC
                               # (Monroe, above).
_add("SC", "Williamsburg", "Kingstree")
_add("SC", "York", "York", "Rock Hill", "Fort Mill")


def bankruptcy_county_for(city: str | None, state: str | None) -> str | None:
    """County for a known NC/SC city, or None. Case-insensitive on city;
    state is part of the key so cross-state (and cross-county, same-state)
    collisions are resolved correctly instead of one clobbering the other
    -- e.g. "Camden" is a whole county in NC but a town (Kershaw's seat) in
    SC; "Columbia" is NC's tiny Tyrrell-county seat AND South Carolina's
    state capital. A flat city-only dict would let one silently clobber the
    other; see module docstring for the ("henderson", "NC") case this
    protects specifically."""
    if not city or not state:
        return None
    return _LOOKUP.get((city.strip().lower(), state.strip().upper()))


#: All known (city, state) pairs' city names, longest first, so a multi-word
#: city ("high point", "mount airy") is matched before a shorter substring
#: that might otherwise match first inside it.
KNOWN_CITIES: tuple[str, ...] = tuple(
    sorted({c for c, _ in _LOOKUP.keys()}, key=lambda s: (-len(s.split()), -len(s)))
)
