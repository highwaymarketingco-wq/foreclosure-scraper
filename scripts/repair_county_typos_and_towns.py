#!/usr/bin/env python3
"""Recover rows whose `county` is a typo or a TOWN name rather than a county.

`county` drives routing, scope_repass and every per-county count, so a row whose
county is not a real county is unroutable and silently inflates coverage tallies with
fake counties. Measured on the live board 2026-09-10: 1,355 rows (1.4%), all from the
liensnc pool, spread over ~505 distinct bad values. They are builder-typed values on
self-filed LiensNC appointments, so they are exactly what humans produce:

    typos          Bumcombe / Buncombee / Buncomb -> Buncombe
                   Caarrus -> Cabarrus,  Mcdonnell -> McDowell
    town for county Rutherfordton -> Rutherford,  Hendersonville -> Henderson
                   Lincolnton -> Lincoln,  Stanley -> Gaston/Lincoln area

`scripts/fix_liensnc_bogus_county.py` already handles a DIFFERENT case (county
literally reading "Nc" / "North Carolina") and does not touch these.

THE TRAP THIS SCRIPT EXISTS TO AVOID
    "Stanley" fuzzy-matches "Stanly" at 0.92 -- and Stanly County NC is real, but it
    is 90 miles from the town of Stanley, which sits on the Gaston/Lincoln line. A
    naive fuzzy pass would confidently file those rows in the wrong county, which is
    worse than leaving them unroutable: a wrong county passes scope_repass and lands
    a lead in a county the operator does not work.

    So the order is: CITY LOOKUP FIRST (authoritative), fuzzy only as a fallback, and
    the fuzzy pass refuses any candidate that is a known town name. Anything still
    unresolved is CLEARED rather than guessed -- a countyless row is honest and
    scope_repass cannot misjudge it, which is how these rows behaved before the
    re-parse introduced the bad values.

Fills and clears only. Never adds or removes a row, so the count guard is untouched.

    python scripts/repair_county_typos_and_towns.py --dry-run
    python scripts/repair_county_typos_and_towns.py
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# Official county lists. A "real county" test cannot use the footprint list -- an
# out-of-footprint but genuine county (Wake, Mecklenburg) must not be treated as junk.
#
# COMPLETENESS IS LOAD-BEARING, NOT COSMETIC. An omission here does not fail loudly:
# a real county missing from this set is judged "not a real county", falls through to
# fuzzy (which cannot match a name that is not in the pool) and is CLEARED. The first
# draft of this file omitted "polk" -- a FOOTPRINT county -- and the dry run was about
# to blank the county on 1,217 rows, Polk NC among them. NC has 100 counties and SC
# has 46; tests/test_county_typo_repair.py now asserts both counts and asserts every
# config.ALL_COUNTIES entry appears here, so the next omission fails a test instead of
# erasing a county.
NC_ALL = {
    "alamance", "alexander", "alleghany", "anson", "ashe", "avery", "beaufort", "bertie",
    "bladen", "brunswick", "buncombe", "burke", "cabarrus", "caldwell", "camden",
    "carteret", "caswell", "catawba", "chatham", "cherokee", "chowan", "clay",
    "cleveland", "columbus", "craven", "cumberland", "currituck", "dare", "davidson",
    "davie", "duplin", "durham", "edgecombe", "forsyth", "franklin", "gaston", "gates",
    "graham", "granville", "greene", "guilford", "halifax", "harnett", "haywood",
    "henderson", "hertford", "hoke", "hyde", "iredell", "jackson", "johnston", "jones",
    "lee", "lenoir", "lincoln", "macon", "madison", "martin", "mcdowell", "mecklenburg",
    "mitchell", "montgomery", "moore", "nash", "new hanover", "northampton", "onslow",
    "orange", "pamlico", "pasquotank", "pender", "perquimans", "person", "pitt",
    "polk", "randolph", "richmond", "robeson", "rockingham", "rowan", "rutherford", "sampson",
    "scotland", "stanly", "stokes", "surry", "swain", "transylvania", "tyrrell", "union",
    "vance", "wake", "warren", "washington", "watauga", "wayne", "wilkes", "wilson",
    "yadkin", "yancey",
}
SC_ALL = {
    "abbeville", "aiken", "allendale", "anderson", "bamberg", "barnwell", "beaufort",
    "berkeley", "calhoun", "charleston", "cherokee", "chester", "chesterfield",
    "clarendon", "colleton", "darlington", "dillon", "dorchester", "edgefield",
    "fairfield", "florence", "georgetown", "greenville", "greenwood", "hampton",
    "horry", "jasper", "kershaw", "lancaster", "laurens", "lee", "lexington", "marion",
    "marlboro", "mccormick", "newberry", "oconee", "orangeburg", "pickens", "richland",
    "saluda", "spartanburg", "sumter", "union", "williamsburg", "york",
}

# TOWN names that fuzzy-match a real county but belong to a DIFFERENT one. The fuzzy
# pass must refuse these outright; the city lookup resolves them correctly or nothing
# does. Extend this list rather than loosening the threshold.
TOWN_NOT_COUNTY = {
    "stanley",          # town on the Gaston/Lincoln line; Stanly County is 90mi away
    "rutherfordton",    # seat of Rutherford
    "hendersonville",   # seat of Henderson
    "lincolnton",       # seat of Lincoln
    "marion",           # seat of McDowell NC, but Marion County SC also exists
    "columbus",         # seat of Polk NC, but Columbus County NC also exists
    "jackson",          # town in Northampton; Jackson County also exists
    "union",            # town in Union SC; also counties in both states
    "washington",       # town in Beaufort NC; Washington County also exists
    "clinton",          # seat of Sampson
    "lexington",        # seat of Davidson NC; Lexington County SC also exists
    "camden",           # town in Kershaw SC; Camden County NC also exists
    "florence",         # city in Florence SC -- same name, so harmless, listed for clarity
    "leland",           # town in BRUNSWICK; fuzzy-matches "cleveland" at 80
}

# AMBIGUOUS VALUES: a name that is BOTH a real town and a plausible misspelling of a
# DIFFERENT real county. A flat seat lookup misfiles these, which is worse than
# clearing them. Measured on the live board 2026-09-10: "Stanley" appeared on 43 rows,
# and 41 of them carried a city in STANLY County (35x Albemarle -- Stanly's own county
# seat -- and 6x Locust). A bare seat lookup sent all 43 to Gaston.
#
# So for these values the row's CITY decides, and if the city is in neither set the
# value is cleared rather than guessed. `upstate_county_for` cannot arbitrate: it knows
# Upstate SC and Western NC, and Albemarle/Locust are Charlotte-metro.
AMBIGUOUS_SEAT: dict[str, dict[str, set[str]]] = {
    "stanley": {
        # the TOWN of Stanley, Gaston County
        "Gaston": {"stanley", "mount holly", "dallas", "high shoals", "gastonia",
                   "cherryville", "bessemer city", "lowell", "belmont", "kings mountain"},
        # STANLY County, ~90 miles east -- Albemarle is its seat
        "Stanly": {"albemarle", "locust", "oakboro", "norwood", "richfield",
                   "new london", "stanfield", "misenheimer", "aquadale", "badin"},
    },
}

# Abbreviations builders actually type. Not fuzzy-reachable: "meck" scores 44 against
# "mecklenburg", far below any threshold that is safe for real misspellings.
ABBREV: dict[str, tuple[str, str]] = {
    "meck": ("Mecklenburg", "NC"),
    "mecklenberg co": ("Mecklenburg", "NC"),
    "new hanover co": ("New Hanover", "NC"),
    "buncombe co": ("Buncombe", "NC"),
}

# A county seat / town -> its county, for the values the city resolver does not know.
SEAT_TO_COUNTY: dict[str, tuple[str, str]] = {
    "rutherfordton": ("Rutherford", "NC"),
    "hendersonville": ("Henderson", "NC"),
    "lincolnton": ("Lincoln", "NC"),
    "stanley": ("Gaston", "NC"),
    "shelby": ("Cleveland", "NC"),
    "morganton": ("Burke", "NC"),
    "brevard": ("Transylvania", "NC"),
    "bakersville": ("Mitchell", "NC"),
    "asheville": ("Buncombe", "NC"),
    "gastonia": ("Gaston", "NC"),
    "spindale": ("Rutherford", "NC"),
    "leland": ("Brunswick", "NC"),
    "candler": ("Buncombe", "NC"),
    "leicester": ("Buncombe", "NC"),
    "arden": ("Buncombe", "NC"),
    "fletcher": ("Henderson", "NC"),
    "columbus": ("Polk", "NC"),
    "tryon": ("Polk", "NC"),
    "marion": ("Mcdowell", "NC"),
    "forest city": ("Rutherford", "NC"),
    "old fort": ("Mcdowell", "NC"),   # 'Mcdonnell' rows carry city=Old Fort
    "raleigh": ("Wake", "NC"),
    "hope mills": ("Cumberland", "NC"),
    "sanford": ("Lee", "NC"),
    "charlotte": ("Mecklenburg", "NC"),
    "concord": ("Cabarrus", "NC"),
    "winston salem": ("Forsyth", "NC"),
    "greensboro": ("Guilford", "NC"),
    "wilmington": ("New Hanover", "NC"),
    "fayetteville": ("Cumberland", "NC"),
    # DELIBERATELY ABSENT: "lenior". It looks like a typo of Lenoir, but the CITY of
    # Lenoir is in CALDWELL County while Lenoir County is 200 miles east, so the value
    # names two different places and neither can be chosen from the string. It scores
    # 83 against "lenoir" -- just under the 85 threshold -- so it clears, which is the
    # correct outcome and is the reason that threshold is not loosened.
    "walhalla": ("Oconee", "SC"),
    "gaffney": ("Cherokee", "SC"),
    "seneca": ("Oconee", "SC"),
    "easley": ("Pickens", "SC"),
    "greer": ("Greenville", "SC"),
    "clemson": ("Pickens", "SC"),
}


def is_real(name: str, state: str) -> bool:
    n = name.replace(" County", "").strip().lower()
    if not n:
        return False
    st = (state or "").upper()
    if st == "NC":
        return n in NC_ALL
    if st == "SC":
        return n in SC_ALL
    return n in NC_ALL or n in SC_ALL


def resolve(name: str, state: str, city: str | None, city_lookup) -> tuple[str | None, str]:
    """Return (county_or_None, how). None means clear the field."""
    raw = (name or "").replace(" County", "").strip()
    low = raw.lower()
    st = (state or "").upper()

    # 1. The row's own CITY field, via the project's city->county resolver. This is
    #    authoritative and must run before any fuzzy guessing.
    if city:
        got = city_lookup(city)
        if got:
            return got, "city_field"
        # The project resolver knows Upstate SC and Western NC only, so a row whose
        # city sits outside that window (Albemarle, Old Fort, Raleigh) fell through to
        # guessing from the bad county string. The seat table already holds those
        # towns, so consult it on the CITY too -- the row's own city outranks any
        # inference from a misspelled county.
        got2 = SEAT_TO_COUNTY.get((city or "").strip().lower())
        if got2 and (not st or st == got2[1]):
            return got2[0], "city_via_seat_table"

    # 2. An abbreviation the fuzzy pass cannot reach.
    if low in ABBREV:
        cty, cst = ABBREV[low]
        if not st or st == cst:
            return cty, "abbrev"

    # 3. AMBIGUOUS town/county names -- the row's own city arbitrates, or we clear.
    #    Deliberately before the plain seat lookup, which would misfile these.
    if low in AMBIGUOUS_SEAT:
        city_low = (city or "").strip().lower()
        for cty, towns in AMBIGUOUS_SEAT[low].items():
            if city_low in towns:
                return cty, "ambiguous_city_decided"
        return None, "cleared_ambiguous"

    # 4. The bad county value is itself a known town/seat.
    if low in SEAT_TO_COUNTY:
        cty, cst = SEAT_TO_COUNTY[low]
        if not st or st == cst:
            return cty, "seat_lookup"

    # 5. The bad value may be a town the city resolver knows.
    got = city_lookup(raw)
    if got:
        return got, "town_via_resolver"

    # 6. Fuzzy, refusing known towns -- see the Stanley/Stanly trap above.
    if low not in TOWN_NOT_COUNTY:
        pool = sorted(NC_ALL if st == "NC" else SC_ALL if st == "SC" else NC_ALL | SC_ALL)
        try:
            from rapidfuzz import process, fuzz
            best = process.extractOne(low, pool, scorer=fuzz.ratio)
        except ImportError:
            import difflib
            m = difflib.get_close_matches(low, pool, n=1, cutoff=0.88)
            best = (m[0], 90, 0) if m else None
        # Threshold 85, chosen from the ACTUAL 425 bad values on the board rather than
        # guessed (logs/threshold_check.txt). At 85 every match is an unambiguous
        # misspelling: Guiford/Guildford->guilford, six spellings of mecklenburg,
        # five of buncombe, Catwaba->catawba, New Hannover->new hanover. Going LOWER
        # is what breaks it: "Leland" scores 80 against "cleveland" and Leland is a
        # town in BRUNSWICK, so an 80 threshold files those rows in the wrong county.
        if best and best[1] >= 85 and best[0] not in TOWN_NOT_COUNTY:
            return best[0].title(), f"fuzzy_{int(best[1])}"

    # 7. PARSED LEGAL PROSE. The single largest group of unresolvable values is not
    #    typos at all -- it is deed/plat language the re-parse captured into `county`,
    #    with the county name sitting inside it:
    #        "In The Harnett" (37 rows)   "Parcel In Wake" (15)
    #        "In The Office Of The Register Of Deeds For Columbus" (15)
    #        "Which Said Plat Is Now On File In The ... Register Of Deeds Of Durham" (7)
    #    A whole-word scan recovers these exactly, with two conditions that keep it safe:
    #      * MULTI-TOKEN ONLY. A bare "Columbus" is genuinely ambiguous (town in Polk vs
    #        Columbus County) and must keep falling through; embedded in "Register of
    #        Deeds for Columbus" it unambiguously names the county.
    #      * EXACTLY ONE distinct county matched. "Deeds for Union recorded in Lee"
    #        names two and is not resolvable from the string alone.
    if len(low.split()) > 1:
        pool = NC_ALL if st == "NC" else SC_ALL if st == "SC" else NC_ALL | SC_ALL
        # Longest first so "new hanover" wins over a bare "hanover"-style substring.
        hits = {c for c in sorted(pool, key=len, reverse=True)
                if re.search(rf"(?<![a-z]){re.escape(c)}(?![a-z])", low)}
        # Drop names wholly contained in a longer hit ("union" inside nothing here, but
        # "lee" sits inside "leesville"-style values, which the word boundary already
        # blocks; this only removes true subset county names).
        hits = {h for h in hits if not any(h != o and h in o for o in hits)}
        if len(hits) == 1:
            return hits.pop().title(), "county_inside_prose"

    # 8. Honest failure: clear it. A countyless row cannot be misfiled.
    return None, "cleared"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import contextlib
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact
    try:
        from foreclosure_scraper._upstate_city_to_county import upstate_county_for
    except ImportError:
        upstate_county_for = lambda _c: None  # noqa: E731

    def city_lookup(c):
        try:
            got = upstate_county_for((c or "").strip())
        except Exception:  # noqa: BLE001
            return None
        if not got:
            return None
        return got[0] if isinstance(got, (tuple, list)) else got

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO)
    with lock:
        listings = load_board(REPO / "docs")
        before = len(listings)
        print(f"board rows: {before:,}")

        how = Counter()
        by_src = Counter()
        samples = []
        for li in listings:
            cty = (li.county or "").strip()
            if not cty or is_real(cty, li.state or ""):
                continue
            by_src[li.source or "?"] += 1
            new, method = resolve(cty, li.state or "", li.city, city_lookup)
            how[method] += 1
            if len(samples) < 16:
                samples.append((cty, li.city, li.state, new, method))
            if args.dry_run:
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["county_repaired_from"] = cty
            li.county = new

        total = sum(how.values())
        print(f"\nrows with a non-county `county`: {total:,}")
        for m, n in how.most_common():
            print(f"   {n:>6,}  {m}")
        recovered = total - how["cleared"]
        print(f"\n  RECOVERED to a real county: {recovered:,}")
        print(f"  cleared (honest unknown)  : {how['cleared']:,}")
        print("\n--- by source ---")
        for s, n in by_src.most_common(6):
            print(f"   {n:>6,}  {s}")
        print("\n--- samples ---")
        for cty, city, st, new, m in samples:
            print(f"   {cty[:26]!r:<28} city={str(city)[:18]:<20} {st} -> {new!r:<16} [{m}]")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        assert len(listings) == before, "repair must not change the row count"
        write_artifact(listings, {
            "total": len(listings),
            "notes": (f"county typo/town repair: {recovered:,} recovered, "
                      f"{how['cleared']:,} cleared, {before:,} rows unchanged"),
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
