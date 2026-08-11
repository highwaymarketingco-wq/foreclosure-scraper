"""OFFLINE source-consistency verification: the places where a lead's own record
contradicts ITSELF. Pure-Python, no network, runs over the whole board.

WHY THIS EXISTS AND WHY IT NEEDS NO NETWORK
    The obvious way to verify a lead against its source is to re-fetch the source
    page. That is not available: it is 38,500 fetches (a full scrape), and 6 of
    10 hand spot-checks came back WAF-blocked. It is also unnecessary, because
    the record has already copied enough of the source into itself to be checked
    against itself.

    Board index 0 is the whole argument. `source_url` is
    ".../510-kings-rd-shelby-nc-2141050" and `city` says CLEVELAND. Shelby is
    the city; Cleveland is the COUNTY. Nothing had to be fetched to know that —
    the two fields were sitting on the same record disagreeing, and the board
    published a $204,800 max bid over the top of it.

    So every check below compares two fields of ONE record (or one record
    against a vocabulary the board itself supplies) and fires only when they
    cannot both be describing the same property.

WHAT THIS PASS DOES NOT DO — AND THE THREE CANDIDATES IT REJECTED ON MEASUREMENT
    Rejecting a check is a result, not a gap. Each of these was implemented,
    measured on the live 38,500-lead board, and deleted:

      city == county  (4,347 leads).  NOT a contradiction. The three biggest
        contributors are Spartanburg SC (3,701), Pickens SC (338) and Anderson
        SC (135) — all of them REAL cities that share their county's name, so a
        property in the City of Spartanburg, Spartanburg County trips it while
        being perfectly correct. Firing on 11.3% of the board to catch an
        unknown handful is the exact "warning on correct data" failure this
        project has already been burned by twice. The genuine defect underneath
        it — a source stamping the county name into `city` — is caught instead
        by `address_city_conflict` and `source_url_city_conflict`, which convict
        only the 114 + 13 leads that carry their own evidence.

      property_kind == land carrying a living_sqft  (316 leads).  ALREADY DONE,
        upstream and better: valuation/calc.py:1679 emits
        `arv_land_sqft_mismatch` on exactly this condition, grading.py has it in
        ARV_FLAGS_CONTRADICTED, and the money is consequently already gone: it
        flags 294 of the 316 and 0 of those 294 publish a max bid. Re-flagging
        it here would be a second name for one fact, which is how five silent
        reader/writer mismatches happened in this project.

      NC market_value vs tax_value disagreeing by >3x  (1,163 leads, 929 with a
        bid).  Looked like a strong arithmetic contradiction and is not one:
        tax_value is the SMALLER number on 1,081 of the 1,163 (92.9%). A
        one-sided gap is a semantic difference (land-only value, or a prior
        year), not two fields disagreeing about the same quantity. The board's
        own distribution says the same thing — p50 1.06 but p90 4.19, so a 3x
        gap is the ordinary shape of the data, not an anomaly in it.

    Also measured and dropped for carrying no signal at all: county-named-in-the
    -URL-host vs the county field (21,696 agree, 2 disagree), county vs state by
    board consensus (0 violations), year_built / bed / bath out of any plausible
    band (0), living_sqft vs zillow.livingArea (0 — the zillow block is
    essentially absent), and opening_bid == judgment_amount (29, all one source,
    and a judicial opening bid set AT the judgment is normal practice, not an
    error).

NOTHING HERE GATES MONEY, AND THAT IS DELIBERATE — see EVERY flag's own note.
    A wrong city does not make an ARV wrong. The one candidate that could
    plausibly have earned a retraction is `land_use_kind_conflict`, and the
    board's own numbers argue against it: 550 of the 648 leads that carry it
    WITH a max bid have no living_sqft at all, so their ARV was never priced off
    a building — it came from the county's own valuation of the parcel, which
    already prices whatever is (or is not) standing on it. Blanking those bids
    would be gutting the normal case to punish a label. None of these four
    strings appears in valuation.grading.ARV_FLAGS_CONTRADICTED or
    ARV_FLAGS_WEAK_EVIDENCE, and none should be added there without a
    measurement that separates "the label is wrong" from "the value is wrong".

ORDERING — THIS PASS MUST RUN AFTER enrichment_board_qa.
    `enrich_board_qa` ASSIGNS `li.raw['qa_flags'] = flags` (it does not extend
    it). Run this first and every flag below is silently deleted a moment later
    by an assignment that looks completely innocent. This module only ever
    EXTENDS the existing list, so the two compose in one direction and not the
    other. scripts/recompute_valuation.py calls it in that order.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import unquote, urlparse

import structlog

log = structlog.get_logger()

# ===========================================================================
# FLAG STRINGS INTRODUCED HERE. THIS LIST IS THE INTERFACE — five silent
# failures in this project were reader/writer name mismatches, so every string
# is named once, here, and never re-spelled at a call site.
#
# ALL FOUR ARE WRITTEN TO raw['qa_flags'] AND NOWHERE ELSE.
#
# WHO MUST READ THEM
#   docs/dashboard.js  — the only reader. `qa_flags` is already whitelisted for
#       publication (web_artifact.RAW_KEEP:431 and the slim allowlist at :675),
#       and dashboard.js:2259 feeds every entry to arvFlagClass with
#       inArvFlags=false. That classifier's contract is: a name from a MIXED
#       namespace is treated as an ARV claim ONLY if it contains "arv"
#       (dashboard.js:2174). None of these four does, and none contains a word
#       from _ARV_BAD_WORDS (above|below|exceed|extreme|outlier|suspect|unverif|
#       unreliab|implausib|ceiling|inflat|mismatch|withheld|suppress|overrid|
#       contradict) — note in particular that "mismatch" is in that list, which
#       is why every name here says "conflict". So they render as neutral flags
#       and cannot paint a red "do not bid off this ARV" over a valuation none
#       of them impugns. Giving them captions in dashboard.js is that file
#       owner's call; until then they are correctly silent rather than wrong.
#   valuation/grading.py — must NOT read them. See the module docstring.
#   valuation/calc.py    — must NOT read them; this pass runs long after calc.
# ===========================================================================

#: The property URL the source itself published names a different CITY than the
#: `city` field. Evidence: the slug's own city slot. 13 leads.
URL_CITY_CONFLICT = "source_url_city_conflict"

#: `street_address` ends in "<street-type> <CITY>" and that trailing city is not
#: the `city` field. Evidence: the record's own address string. 114 leads.
ADDR_CITY_CONFLICT = "address_city_conflict"

#: `zip_code` does not belong to `state`. Evidence: the board's own zip->state
#: consensus, falling back to the NC/SC ZIP ranges. 320 leads.
ZIP_STATE_CONFLICT = "zip_state_conflict"

#: The assessor's `land_use` string and `property_kind` describe different kinds
#: of parcel (a dwelling on a "land" record, or vacant dirt on a house record).
#: 891 leads.
LAND_USE_KIND_CONFLICT = "land_use_kind_conflict"

ALL_FLAGS = (URL_CITY_CONFLICT, ADDR_CITY_CONFLICT, ZIP_STATE_CONFLICT,
             LAND_USE_KIND_CONFLICT)


def _norm_city(s) -> str:
    """Lowercase, letters and single spaces only. 'Boiling Springs' -> 'boiling springs'."""
    return " ".join(re.sub(r"[^a-z ]", " ", (s or "").lower()).split())


def _slug(s) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


# ===========================================================================
# CITY NAMES THAT ARE THE SAME PLACE SPELLED TWO WAYS
#
# The whole point of a conflict flag is that the two strings name DIFFERENT
# places, so an abbreviation must never convict. Measured on the board, `city`
# carries at least "boiling spgs" alongside "boiling springs". A shared first
# token, or one string containing the other, is the signature of every such
# pair and of none of the real conflicts found (Roebuck/Spartanburg,
# Shelby/Cleveland, Inman/Campobello share nothing).
# ===========================================================================
def same_place(a: str, b: str) -> bool:
    """True when two city strings are plausibly the same place, spelled differently."""
    a, b = _norm_city(a), _norm_city(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta, tb = a.split(), b.split()
    return bool(ta and tb and ta[0] == tb[0])


# ===========================================================================
# CHECK 1 — THE URL THE SOURCE PUBLISHED NAMES ANOTHER CITY
#
# THE MEASUREMENT THAT SHAPED THIS. The first pass at it used a loose regex over
# every source_url and reported that the URL and the `city` field disagree on
# ~93% of the leads whose URL encodes a city. That number was an artifact: the
# regex captured the street and the city together, so "423-camden-lee-court-
# inman-sc" read as a disagreement when the city (Inman) is right there in it.
#
# Re-measured with the parse below: of 762 address-slug URLs, 524 AGREE, 141
# name the county rather than a city, 25 carry the city somewhere other than the
# tail, and 13 genuinely disagree. The true rate is 13/537 = 2.4%, not 93%.
#
# TWO RESTRICTIONS DO ALL THE WORK.
#
# (a) ADDRESS-SLUG HOSTS ONLY. The parse is only defined for hosts whose detail
#     URL is built FROM the address. The counterexample is landandfarm.com,
#     whose slugs are marketing headlines: "custom-built-home-near-boiling-
#     springs-nc", "2-08-acres-in-nc", "34-8-acres-on-river-road-in-columbus-
#     nc". Twenty-three of those tripped an unrestricted parse and every one is
#     a FALSE POSITIVE — "near Boiling Springs" on a Shelby property is a true
#     sentence about a property 9 miles from Boiling Springs, not a claim about
#     its city. There is no way to tell a headline from an address slug by
#     shape, so the host list is the gate.
#
# (b) A ONE-WAY TEST. The check never tries to segment the slug into street and
#     city — that is the ambiguity that produced the 93%. It asks only whether
#     the record's OWN city sits where a city belongs: immediately before the
#     state token. If it does, agree. If the city appears anywhere else in the
#     slug, say nothing. Only when the record's city is absent from the slug
#     entirely does this fire, and then the tail is quoted as the evidence.
#
# WHAT A LEGITIMATE LEAD THAT TRIPS IT WOULD LOOK LIKE, AND WHY NONE DOES:
#   - a nearby-town headline  -> excluded by (a)
#   - the slug naming the county ("...-in-buncombe-county-nc-...") -> excluded
#     explicitly; a county slug makes no city claim
#   - an abbreviation ("boiling spgs" vs "boiling-springs") -> excluded by
#     same_place()
#   - a USPS postal city that differs from the municipality -> would survive,
#     and is the one residual risk. It does not appear in the 13: 9 of them have
#     `city` set to the COUNTY NAME (CLEVELAND, McDowell, SPARTANBURG, Pickens,
#     Henderson, CHEROKEE, Spartanburg, BUNCOMBE, Cherokee) while the slug names
#     the actual town (shelby, w-marion, landrum, marietta, flat-rock, gaffney,
#     inman, asheville, gaffney), which is the index-0 defect exactly.
# ===========================================================================
_ADDR_SLUG_HOSTS = frozenset({
    "auction.com", "realtor.com", "zillow.com", "foreclosure.com", "xome.com",
    "hubzu.com", "trulia.com", "servicelinkauction.com", "vrmproperties.com",
    "homesteps.com",
})
_STATE_TOK = re.compile(
    r"(?:^|[-_])(al|ar|az|ca|co|ct|de|fl|ga|ia|id|il|in|ks|ky|la|ma|md|me|mi|"
    r"mn|mo|ms|mt|nc|nd|ne|nh|nj|nm|nv|ny|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|va|vt|"
    r"wa|wi|wv|wy)(?:[-_]|$)", re.I)


def url_slug_geo(url: str | None) -> tuple[str, str] | None:
    """``(state, city_zone)`` parsed from an address-slug property URL, else None.

    ``city_zone`` is the slug text BEFORE the state token — street and city
    still joined. Deliberately not segmented; see restriction (b) above.
    """
    try:
        p = urlparse(unquote(url or ""))
    except (ValueError, AttributeError):
        return None
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _ADDR_SLUG_HOSTS:
        return None
    cand = None
    for seg in reversed([s for s in p.path.split("/") if s]):
        if _STATE_TOK.search(seg):
            cand = seg
            break
    if not cand:
        return None
    m = None
    for m2 in _STATE_TOK.finditer(cand):
        m = m2                      # LAST state token: "...-kings-rd-shelby-nc-"
    zone = _slug(cand[:m.start(1)])
    # A trailing 5-digit ZIP belongs to neither the street nor the city.
    zone = re.sub(r"-?\d{5}$", "", zone)
    return (m.group(1).upper(), zone) if zone else None


def url_city_conflict(source_url, city, county) -> str | None:
    """The slug's city zone when it contradicts `city`, else None."""
    g = url_slug_geo(source_url)
    if not g:
        return None
    _st, zone = g
    c, cty = _slug(city), _slug(county)
    if not c:
        return None                 # nothing to contradict
    if cty and (zone == cty or zone == cty + "-county"
                or zone.endswith("-" + cty) or zone.endswith("-" + cty + "-county")):
        return None                 # names the COUNTY, makes no city claim
    if zone == c or zone.endswith("-" + c) or c in zone:
        return None
    # The abbreviation guard, run over the slug's TAIL rather than its last
    # token: "12-main-st-boiling-springs" against a `city` of "Boiling Spgs"
    # only matches when two tokens are compared, and a one-token comparison
    # ("springs" vs "boiling spgs") would wrongly convict a spelling variant.
    tokens = zone.replace("-", " ").split()
    for k in (3, 2, 1):
        if len(tokens) >= k and same_place(" ".join(tokens[-k:]), city):
            return None
    return zone


# ===========================================================================
# CHECK 2 — THE STREET ADDRESS NAMES ONE TOWN AND THE CITY FIELD NAMES ANOTHER
#
# This is the check that convicts the `city` defect at board scale, and it is
# the disciplined replacement for the city == county dragnet.
#
# THE SIGNATURE. Several sources append the town to the street line:
# "111 FORTUNE DR ROEBUCK", "532 ALVERSON RD INMAN", "11900 HIGHWAY 56 CROSS
# ANCHOR". So the address string carries a second, independent opinion about the
# city, sitting on the same record as `city`. Measured: 2,421 leads AGREE, 1,472
# have the town in the address and nothing in `city` at all (a recovery
# opportunity, not a contradiction — not flagged), and 114 DISAGREE.
#
# 100 of the 114 are counties_sc.spartanburg_vacant, the source whose 3,309
# leads every one say city="Spartanburg" — and their own addresses say Roebuck,
# Moore, Inman, Duncan, Woodruff. That is the proof that source defaults `city`
# to the county name. Note what this check does NOT do with that proof: it flags
# the 100 leads that carry the evidence and leaves the other 3,209 alone,
# because for those the record says nothing either way and a source-wide
# accusation is not a per-lead fact.
#
# The other 14 are a different defect with the same shape — the OWNER'S MAILING
# city in the property's city field: "1852 OLD FURNACE RD BOILING SPRINGS" with
# city=SUWANEE (Georgia), "790 BERRY SHOALS RD DUNCAN" with city=Livermore.
#
# WHY THE STREET-TYPE SUFFIX IS REQUIRED. The trailing token only means "city"
# if the street name has already ended. "100 GREER ST" must not fire (Greer is a
# real town AND this street's name); "100 CHELSEA ST MOORE" must. Requiring a
# street-type token immediately before the candidate is what separates them, and
# it is why the check reads the LAST tokens rather than searching the string —
# "2226 HARRIS HENRIETTA RD" contains the town Henrietta mid-name and correctly
# says nothing.
#
# WHAT A LEGITIMATE LEAD THAT TRIPS IT LOOKS LIKE, AND HOW IT IS EXCLUDED:
#   - an abbreviated spelling of the same town -> same_place()
#   - a street type that is also a place name ("... RD PARK") -> the vocabulary
#     is built from real observed city values with support, and generic words
#     are additionally denied below
#   - a unit/suite trailer -> too short (>= 4 letters required) or not a city
#   - a PLACEHOLDER that happens to contain a town name. The board carries
#     "Vacant parcel — D Dist Recorded 2026 06 03 Babcock Michael Lance Estate
#     103 Barkley St Easley", which is a court-index blob, not an address. It is
#     excluded by requiring the string to BEGIN with a house number, which is
#     the same discipline as refusing to read a city out of a landandfarm
#     marketing headline: only parse geography out of something that is
#     structurally an address. 92.0% of the board's street lines start with a
#     digit, and every one of the 114 real hits does.
#   - a genuinely different USPS postal city vs municipality -> would survive,
#     and is the residual risk; it is also, on this board, indistinguishable
#     from the real defect, which is why this flag reports a CONFLICT and never
#     asserts which side is right.
# ===========================================================================
_STREET_TYPE = re.compile(
    r"\b(rd|road|st|street|ave|avenue|dr|drive|ln|lane|ct|court|blvd|boulevard|"
    r"hwy|highway|way|pl|place|cir|circle|ter|terrace|pkwy|parkway|loop|trl|"
    r"trail|run|ext|extension|byp|bypass|pike|row|walk|path|ridge|creek|branch|"
    r"hill|cove|point|crossing|xing|bnd|bend|sq|square|plz|plaza)\b\.?$")
_ROUTE_TAIL = re.compile(r"\b(?:highway|hwy|route|rt|us|nc|sc)\s+\d+[a-z]?$")
#: Words that are common city names AND common address furniture. Never allowed
#: to be the trailing "city" on their own.
_CITY_STOPWORDS = frozenset({"park", "ridge", "hill", "hills", "point", "cove",
                             "creek", "forest", "lake", "lakes", "valley",
                             "grove", "springs", "heights", "view", "north",
                             "south", "east", "west", "center", "centre"})
_MIN_CITY_SUPPORT = 5


def city_vocabulary(listings) -> dict[str, set]:
    """``{state: {city names}}`` — the board's own gazetteer, plus the repo's.

    Board-observed names need ``_MIN_CITY_SUPPORT`` sightings so one typo cannot
    become vocabulary. The repo gazetteers are unioned in because they are real
    place lists that do NOT come from the field under suspicion: a source that
    gets `city` wrong on every one of its leads still cannot suppress a town
    name that ``_upstate_city_to_county`` already knows.
    """
    seen: dict[str, Counter] = defaultdict(Counter)
    for li in listings:
        c, s = _norm_city(getattr(li, "city", None)), getattr(li, "state", None)
        if c and s and len(c) >= 4:
            seen[s][c] += 1
    voc: dict[str, set] = {s: {c for c, n in ctr.items() if n >= _MIN_CITY_SUPPORT}
                           for s, ctr in seen.items()}
    try:
        from ._upstate_city_to_county import _LOOKUP as _UP
        for city, (_county, st) in _UP.items():
            c = _norm_city(city)
            if len(c) >= 4:
                voc.setdefault(st, set()).add(c)
    except Exception:  # noqa: BLE001 - a missing gazetteer must not void the pass
        pass
    try:
        from ._coastal_city_to_county import _LOOKUP as _CO
        for (city, st), _county in _CO.items():
            c = _norm_city(city)
            if len(c) >= 4:
                voc.setdefault(st, set()).add(c)
    except Exception:  # noqa: BLE001
        pass
    for st in voc:
        voc[st] -= _CITY_STOPWORDS
    return voc


def address_trailing_city(street_address, state, vocab: dict[str, set]) -> str | None:
    """The town appended to the end of a street line, or None.

    Requires a street-type token (or a numbered route) immediately before it, so
    the street name has demonstrably ended. Longest name wins, so "cross anchor"
    beats "anchor".
    """
    s = (street_address or "").strip()
    known = vocab.get(state or "") or set()
    if not s or not known or not s[0].isdigit():
        return None                 # not structurally an address -> not evidence
    a = _norm_city(s)
    toks = a.split()
    if len(toks) < 3:
        return None
    for k in (3, 2, 1):
        if len(toks) <= k:
            continue
        cand = " ".join(toks[-k:])
        if cand not in known:
            continue
        head = " ".join(toks[:-k])
        if _STREET_TYPE.search(head) or _ROUTE_TAIL.search(head):
            return cand
    return None


# ===========================================================================
# CHECK 3 — THE ZIP DOES NOT BELONG TO THE STATE
#
# 320 leads, 174 of them publishing a max bid. What it catches, from the board:
#
#   6055 OLD MEADOW CT / city Mechanicsvlle / zip 23111 / state NC / county
#   Buncombe / max bid $218,200.  23111 is Mechanicsville VIRGINIA. The OWNER'S
#   MAILING ADDRESS has been written into the property's address fields, and the
#   card prices a Buncombe County property while showing a Virginia one. The
#   same source also carries Damariscotta ME 04543 ($228,400) and Alton IL 62002
#   ($548,800). counties_nc.asheville_helene contributes 102 with Chicago,
#   Orlando and New Orleans ZIPs; counties_sc.spartanburg_condemned 114.
#
# TWO INSTRUMENTS, IN THIS ORDER, AND THE ORDER IS THE FALSE-POSITIVE DEFENCE.
#
#   1. THE BOARD'S OWN ZIP->STATE CONSENSUS, when the ZIP has real support. This
#      exists to protect the genuine border case. USPS ZIP boundaries do cross
#      state lines, and a range table would convict a real NC property that
#      legitimately carries an SC ZIP. A border-crossing ZIP shows BOTH states on
#      a 38,500-lead board and therefore never reaches 98% agreement, so
#      consensus declines to convict exactly where a table would be wrong.
#   2. THE NC/SC ZIP RANGES, only for ZIPs the board has too little to say about.
#      NC is 270xx-289xx and SC is 290xx-299xx; a 23111 or a 62002 on an NC
#      record is not a border case in any reading.
#
# EXCLUDED BY NAME: placeholder ZIPs. counties_nc.rutherford_tax writes "00000"
# on 13 leads. That is a MISSING value wearing a number, and calling it a
# contradiction would be a false positive on a record that never made a claim.
# ===========================================================================
_NC_PREFIX = frozenset(f"{i:03d}" for i in range(270, 290))
_SC_PREFIX = frozenset(f"{i:03d}" for i in range(290, 300))
_ZIP_PLACEHOLDER = re.compile(r"^0+$|^(?:12345|99999)$")
_ZIP_MIN_SUPPORT = 25
_ZIP_CONSENSUS = 0.98
_ZIP_MINORITY_MAX = 2


def _zip5(z) -> str:
    z = (z or "").strip()[:5]
    return z if len(z) == 5 and z.isdigit() and not _ZIP_PLACEHOLDER.match(z) else ""


def zip_state_consensus(listings) -> dict[str, Counter]:
    """``{zip5: Counter(state)}`` built from the board itself."""
    out: dict[str, Counter] = defaultdict(Counter)
    for li in listings:
        z, s = _zip5(getattr(li, "zip_code", None)), getattr(li, "state", None)
        if z and s:
            out[z][s] += 1
    return out


def zip_state_conflict(zip_code, state, consensus: dict[str, Counter]) -> str | None:
    """``"board_consensus"`` / ``"zip_range"`` when the ZIP cannot be in `state`."""
    z = _zip5(zip_code)
    if not z or not state:
        return None
    ctr = consensus.get(z) or Counter()
    total = sum(ctr.values())
    if total >= _ZIP_MIN_SUPPORT:
        top, ntop = ctr.most_common(1)[0]
        if top != state and ntop / total >= _ZIP_CONSENSUS and ctr[state] <= _ZIP_MINORITY_MAX:
            return "board_consensus"
        return None                 # the board has spoken and it is fine
    p = z[:3]
    if state == "NC" and p not in _NC_PREFIX:
        return "zip_range"
    if state == "SC" and p not in _SC_PREFIX:
        return "zip_range"
    return None


# ===========================================================================
# CHECK 4 — THE ASSESSOR'S OWN LAND USE AND THE PROPERTY KIND DESCRIBE
#           DIFFERENT PARCELS
#
# 891 leads (562 + 329), 648 of them publishing a max bid. `land_use` is the
# county's classification string, carried straight off the assessor row;
# `property_kind` is what the pipeline decided this lead is. When one says there
# is a building and the other says there is not, they cannot both be about this
# parcel — and `property_kind` is what valuation/calc.py reads to choose between
# the $/sqft house path and the $/acre land path.
#
# Example: 521 Zion Hill Rd, land_use "Undeveloped Land", property_kind
# single_family, living_sqft 1,800, max bid $332,000.
#
# THE TAXONOMY IS WHAT MAKES THIS SAFE. These county land-use vocabularies
# distinguish improved from vacant THEMSELVES — the same board carries
# "Residential - Single Family" (275) AND "Residential Subdivision Undeveloped
# Lot" (153) AND "Residential Vacant Lot" from the same counties. So
# "Residential - Single Family" is not a zoning label that a bare lot might also
# wear; it is the assessor asserting a house. That is the entire basis for
# reading a conflict rather than a difference in resolution.
#
# WHAT A LEGITIMATE LEAD THAT TRIPS IT LOOKS LIKE, AND HOW IT IS EXCLUDED:
#   - "Mobile Home Lot" (578 on the board) and "Mobile Home Combined With Land"
#     — genuinely ambiguous about whether a dwelling is present. EXCLUDED by
#     _LU_AMBIGUOUS; including them added 291 leads of pure argument.
#   - "Farms-General" (187) — a farm normally has a farmhouse AND acres of
#     undeveloped land, so neither reading is a contradiction. EXCLUDED.
#   - a house demolished after the class was set, or a class not yet updated
#     after a build — REAL, and the reason this flag names a conflict instead of
#     picking a winner. The record does not say which side is stale.
#   - already-known cases: 24 of these leads carry calc's own
#     `arv_land_sqft_mismatch` and 38 carry `cama_class_mismatch`. Those are a
#     different claim on the same lead (sqft vs class, commercial CAMA row vs
#     kind) and both are already CONTRADICTED tier, so this flag adds a reason,
#     never a second copy of an existing one.
# ===========================================================================
_LU_STRUCTURE = re.compile(
    r"single[ -]family|duplex|triplex|quadplex|apartment|condominium|townhouse|"
    r"dwelling|eating (?:&|and) drinking|eating place|restaurant|motel|hotel|"
    r"warehous|office build|department store|retail store|supermarket", re.I)
_LU_VACANT = re.compile(r"vacant|undeveloped|unimproved", re.I)
_LU_AMBIGUOUS = re.compile(r"mobile home|farm|combined with land|acreage", re.I)
_DWELLING_KINDS = frozenset({"single_family", "condo", "townhouse",
                             "multi_family", "mobile"})


def land_use_kind_conflict(property_kind, land_use) -> str | None:
    """``"structure_on_land_parcel"`` / ``"vacant_lot_priced_as_dwelling"`` / None."""
    lu = (land_use or "").strip()
    kind = getattr(property_kind, "value", property_kind)
    if not lu or _LU_AMBIGUOUS.search(lu):
        return None
    structure = bool(_LU_STRUCTURE.search(lu))
    vacant = bool(_LU_VACANT.search(lu))
    if structure == vacant:         # both or neither -> the string is not deciding
        return None
    if kind == "land" and structure:
        return "structure_on_land_parcel"
    if kind in _DWELLING_KINDS and vacant:
        return "vacant_lot_priced_as_dwelling"
    return None


# ===========================================================================
def enrich_source_consistency(listings) -> dict:
    """Verify each lead against ITSELF; EXTEND ``raw['qa_flags']``; return counts.

    Pure-Python, no network. Must run AFTER ``enrich_board_qa`` — that pass
    assigns ``raw['qa_flags']`` outright and would delete these. Idempotent: a
    flag already present is never appended twice.
    """
    summary: Counter = Counter()
    if not listings:
        return {}

    vocab = city_vocabulary(listings)
    zipcons = zip_state_consensus(listings)

    for li in listings:
        found: list[str] = []

        zone = url_city_conflict(getattr(li, "source_url", None),
                                 getattr(li, "city", None),
                                 getattr(li, "county", None))
        if zone:
            found.append(URL_CITY_CONFLICT)

        trailing = address_trailing_city(getattr(li, "street_address", None),
                                         getattr(li, "state", None), vocab)
        if trailing:
            city = getattr(li, "city", None)
            if not _norm_city(city):
                # The address knows the town and the field is empty. Recoverable
                # data, NOT a contradiction — 1,472 leads. Counted, not flagged.
                summary["address_city_recoverable"] += 1
            elif not same_place(trailing, city):
                found.append(ADDR_CITY_CONFLICT)
                summary[f"{ADDR_CITY_CONFLICT}:{'to_county_name' if _norm_city(city) == _norm_city(getattr(li, 'county', None)) else 'other_city'}"] += 1

        basis = zip_state_conflict(getattr(li, "zip_code", None),
                                   getattr(li, "state", None), zipcons)
        if basis:
            found.append(ZIP_STATE_CONFLICT)
            summary[f"{ZIP_STATE_CONFLICT}:{basis}"] += 1

        lu = land_use_kind_conflict(getattr(li, "property_kind", None),
                                    getattr(li, "land_use", None))
        if lu:
            found.append(LAND_USE_KIND_CONFLICT)
            summary[f"{LAND_USE_KIND_CONFLICT}:{lu}"] += 1

        if not found:
            continue
        if not isinstance(getattr(li, "raw", None), dict):
            li.raw = {}
        existing = li.raw.get("qa_flags")
        flags = list(existing) if isinstance(existing, list) else []
        for f in found:
            if f not in flags:          # idempotent across repeated republishes
                flags.append(f)
            summary[f] += 1
        li.raw["qa_flags"] = flags

    out = dict(summary)
    if out:
        log.info("source_consistency.summary", **out)
    return out
