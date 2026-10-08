"""Is a street_address a usable situs, or a placeholder / entity name the pipeline should withhold?

main.run()'s SITUS SANITY guard nulls a row's street_address when this says junk, keeping the
original in raw['situs_nulled'] (and raw['situs_quality'] = 'low'). It used to live in main.py as
_situs_is_junk(); this module is the same rule plus one exemption, and main.py imports it.

THE DEFECT (audit 2026-10-09, drops_lineage). The 2026-10-08 gated run nulled 8,606 addresses.
Classified from the run's own dot_ocr checkpoint (raw['situs_nulled'], one pass, scratch only):
6,218 were title placeholders ('Parcel — <owner> — <county> NC delinquent tax $N owed (...)',
'Lis Pendens <case> — <party>', 'Vacant parcel — ...'), 2,239 were an owner or entity name with no
road word ('<NAME> LLC', '<NAME> OIL CO INC — UST...'): both rightly withheld. 82 (0.95%) were REAL
locations, nulled because the old rule only recognised a road when its suffix was the LAST word of
the first comma part, and each contains a word the entity list treats as a business ('church',
'club', 'golf', 'academy', 'college', 'chapel', 'temple', 'motel', 'university'):
  * a house number after the street: Dorchester BillTrax '<NAME> ACADEMY RD <number>' (13 of 13 nulled rows);
  * a direction or an acreage after the suffix: '<NAME> GOLF COURSE DR S', '<NAME> CHURCH RD  .33'
    (Transylvania vacant 27 of 78, Lincoln vacant 7 of 7, Gaston vacant 1 of 1);
  * an intersection or a route: 'CHURCH ST & HWY <n>', '<NAME> CHURCH RD/HWY <n>' (NC UST incidents
    22 of 44, NC inactive hazardous sites 3 of 11, SC UST registry 4 of 453, EPA SEMS 1 of 32);
  * a lot on a named road: HomePath 2 of 2; qPayBill 2 of 1,423 ('ACADEMY ST N' form).

THE EXEMPTION. The first comma part names a road (a road-type word anywhere in it, or a numbered
route 'HWY 47' / 'US 301' / 'SR 1527'), carries no corporate-form word (LLC, INC, CORP, COMPANY,
HOLDINGS, PROPERTIES, ASSOCIATES, ...), and is not a title placeholder (no ' — ' separator, does not
start with 'Parcel' / 'Lis Pendens' / 'Vacant parcel'). Such a string is a location, not a business
name: it is kept. Everything the old rule kept is still kept; an entity name that merely contains a
road word ('<NAME> DRIVE PROPERTIES INC', '<NAME> ROAD LLC') is still withheld.
"""
from __future__ import annotations

import re

_VACANT_RE = re.compile(r"^\s*vacant parcel\b", re.I)
#: A token-group that ENDS in a street/road suffix is a road name, never junk.
_ROAD_SUFFIX_END_RE = re.compile(
    r"\b(st|street|rd|road|ave|avenue|dr|drive|ln|lane|blvd|boulevard|ct|court|"
    r"cir|circle|way|pl|place|pkwy|parkway|hwy|highway|trl|trail|loop|run|path|"
    r"row|terrace|ter|pike|cove|cv|crossing|xing|bend|ridge|sq|square|alley|aly|"
    r"walk|connector|extension|ext)\.?$",
    re.I,
)
#: Strong business / institution words: a residential situs never STARTS here.
_ENTITY_RE = re.compile(
    r"\b(inn|motel|hotel|baptist|methodist|presbyterian|lutheran|episcopal|"
    r"ministr\w*|temple|tabernacle|chapel|church|synagogue|mosque|llc|l\.l\.c\.?|"
    r"inc|incorporated|corp|corporation|company|brewing|brewery|winery|distillery|"
    r"restaurant|cafe|diner|funeral|crematory|club|lodge|academy|university|"
    r"college|bank|associat\w*|foundation|society|cemetery|photography|holdings|"
    r"enterprises|outfitters|thrift|store|salon|barber|civic center|senior center|"
    r"conference center|retreat|golf)\b",
    re.I,
)
#: An embedded "<house#> <words> <road-suffix>" anywhere => a recoverable situs.
_EMBEDDED_ADDR_RE = re.compile(
    r"\d+\s+\w[\w .-]*\b(st|street|rd|road|ave|avenue|dr|drive|ln|lane|blvd|ct|"
    r"court|cir|circle|way|pl|place|hwy|highway|pkwy|trl|trail|loop|run|path|pike)\b",
    re.I,
)
#: A road-type word anywhere in the first comma part (not only at its end), or a numbered route.
_ROAD_WORD_RE = re.compile(
    r"\b(st|street|rd|road|ave|avenue|dr|drive|ln|lane|blvd|boulevard|ct|court|cir|circle|"
    r"pkwy|parkway|hwy|highway|trl|trail|pike|terrace|ter|ext|extension|bypass|byp)\b\.?"
    r"|\b(us|nc|sc|sr|hwy|highway|i)[\s-]*\d{1,4}\b",
    re.I,
)
#: Corporate-form words: a string carrying one is an owner/entity name, even with a road word in it.
_CORP_RE = re.compile(
    r"\b(llc|l\.l\.c\.?|inc|incorporated|corp|corporation|company|holdings|enterprises|"
    r"associat\w*|assoc|properties|partners|partnership|ltd|lp|llp|development|investments?|"
    r"group|foundation|ministries|trust)\b",
    re.I,
)
#: The title placeholders scrapers write when they have no situs ('Parcel — ...').
_TITLE_RE = re.compile(r"^\s*(parcel\b|lis pendens\b|vacant parcel\b)|\s—\s", re.I)
#: A leading 'ST' / 'ST.' / 'SAINT' is a saint's name ('ST <NAME> CHURCH OF GOD'), not a street.
_SAINT_RE = re.compile(r"^\s*(st\.?|saint)\s+", re.I)


def is_road_location(first: str, whole: str | None = None) -> bool:
    """`first` (the first comma part) names a road or a road intersection and the address carries
    nothing corporate (`whole`, default `first`): '<NAME> ACADEMY RD <number>', '<NAME> GOLF COURSE
    DR S', 'CHURCH ST & HWY <n>'. Pure."""
    whole = first if whole is None else whole
    if not first or _TITLE_RE.search(whole):
        return False
    return bool(_ROAD_WORD_RE.search(_SAINT_RE.sub("", first))) and not _CORP_RE.search(whole)


def situs_is_junk(address: str | None) -> bool:
    """True when `address` is not a usable residential situs: a 'Vacant parcel' placeholder or a
    leading business/entity name (geocoder POI artifact, owner name in the address slot).
    Conservative: real road names, road locations and name-prefixed strings that still embed a
    real street address are NOT flagged. Pure."""
    a = (address or "").strip()
    if not a:
        return False
    if _VACANT_RE.match(a):
        return True
    first = a.split(",")[0].strip()
    if not first:
        return False
    if first[0].isdigit():
        return False  # normal house-numbered address
    if _ROAD_SUFFIX_END_RE.search(first):
        return False  # a road name (may contain 'church'/'academy' etc.)
    if _EMBEDDED_ADDR_RE.search(a):
        return False  # name prefix but a real situs is recoverable after it
    if is_road_location(first, a):
        return False  # 2026-10-09: a road with a trailing number/direction/acreage, or a crossing
    return bool(_ENTITY_RE.search(first))
