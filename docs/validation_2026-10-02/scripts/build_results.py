import json
from pathlib import Path

SCRATCH = Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad")
to_check = json.loads((SCRATCH / "to_check.json").read_text())

# live-check verdicts, in the same order as to_check.json (60 entries, idx 0-59)
# verdict: CONFIRMED / NOT_CONFIRMED / INCONCLUSIVE_CAPPED / SKIPPED_NO_NAME
# live_rows: total rows returned by the live Public Index search (None if skipped)
live = [
    # (county, search_last, search_first, verdict, live_rows, note)
    ("Spartanburg", "Sosbee", "Harold", "NOT_CONFIRMED", 12, "12 non-divorce cases (criminal/civil/judgment), no family-court entry"),
    ("Spartanburg", "Duncan", "John", "NOT_CONFIRMED", 126, "126 cases incl. 'Duncan III, John' (the matched spouse name); zero family rows"),
    ("Spartanburg", "Guyton", "Wilburn", "NOT_CONFIRMED", 1, "single case, not family-court"),
    ("Spartanburg", "Dodd", "Brandon", "NOT_CONFIRMED", 34, "owner_name middle='Terrill', matched FCCMS case middle='Jamaine' -- different person; zero family rows for either"),
    ("Spartanburg", "Turner", "Jerry", "NOT_CONFIRMED", 39, "no family rows"),
    ("Spartanburg", "Blackwell", "Jeffrey", "NOT_CONFIRMED", 83, "no family rows"),
    ("Spartanburg", "Hudson", "Michael", "NOT_CONFIRMED", 24, "no family rows"),
    ("Spartanburg", "Turner", "Cole", "NOT_CONFIRMED", 37, "no family rows"),
    ("Spartanburg", "Duckworth", "Angela", "NOT_CONFIRMED", 0, "zero records at all under this name in Spartanburg"),
    ("Spartanburg", "Gentry", "Willie", "NOT_CONFIRMED", 106, "no family rows"),
    ("Spartanburg", "Odom", "Robert", "NOT_CONFIRMED", 33, "no family rows"),
    ("Spartanburg", "Gregory", "Wayne", "NOT_CONFIRMED", 55, "no family rows"),
    ("Spartanburg", "Adkins", "Michael", "NOT_CONFIRMED", 50, "owner matched to 'Michael WAYNE Adkins'; live shows only 'Michael RAY Adkins' -- different person"),
    ("Spartanburg", "Brice", "James", "NOT_CONFIRMED", 9, "no family rows"),
    ("Spartanburg", "Miller", "Joseph", "NOT_CONFIRMED", 80, "no family rows"),
    ("Spartanburg", "Miller", "Amy", "NOT_CONFIRMED", 108, "owner matched to 'Amy Hicks Miller'; live shows 'Amy Hopper Miller' (different), no family rows regardless"),
    ("Spartanburg", "Watson", "Donald", "NOT_CONFIRMED", 7, "no family rows"),
    ("Spartanburg", "Chism", "Henry", "NOT_CONFIRMED", 23, "no family rows"),
    ("Spartanburg", "Walker", "Elizabeth", "NOT_CONFIRMED", 60, "control: owner_name on board is 'W G ARTHUR INC' (a company); matched to a human divorce case; no family rows live either"),
    ("Spartanburg", "Honest", "Home", "NOT_CONFIRMED", 0, "control: owner is 'HONEST HOME SALES LLC', not a person; zero records"),
    ("Spartanburg", None, None, "SKIPPED_NO_NAME", None, "control: board record has no owner_name at all"),
    ("Spartanburg", "Cromer", "Kimberly", "NOT_CONFIRMED", 13, "no family rows"),
    ("Spartanburg", None, None, "SKIPPED_NO_NAME", None, "control: board record has no owner_name at all"),
    ("Spartanburg", "Turner", "Matthew", "NOT_CONFIRMED", 30, "no family rows"),
    ("Pickens", "Weimer", "Matthew", "NOT_CONFIRMED", 5, "no family rows"),
    ("Pickens", "Turner", "Robert", "NOT_CONFIRMED", 41, "no family rows"),
    ("Pickens", "Leroy", "Jacob", "NOT_CONFIRMED", 3, "no family rows"),
    ("Pickens", "Spearman", "Ernest", "NOT_CONFIRMED", 13, "no family rows"),
    ("Pickens", "Terry", "William", "NOT_CONFIRMED", 22, "no family rows"),
    ("Pickens", "Brissey", "Judy", "NOT_CONFIRMED", 6, "owner matched to 'Judy M Brissey'; live shows 'Judy Elaine Brissey' (middle mismatch); no family rows regardless"),
    ("Pickens", "Cobb", "John", "INCONCLUSIVE_CAPPED", 250, "common name, portal caps at 250 rows and refuses to return the rest; no family rows in the visible 250, but not a full enumeration -- narrowing by suffix did not help"),
    ("Pickens", "Kennedy", "Barbara", "NOT_CONFIRMED", 0, "zero records at all"),
    ("Pickens", "Holcombe", "Janis", "NOT_CONFIRMED", 0, "zero records at all"),
    ("Pickens", "Harris", "Sherry", "NOT_CONFIRMED", 0, "zero records at all"),
    ("Pickens", "Newton", "Ronald", "NOT_CONFIRMED", 1, "single case, not family-court"),
    ("Greenville", "Edge", "Lisa", "NOT_CONFIRMED", 0, "zero records at all"),
    ("Greenville", "Williams", "Misty", "NOT_CONFIRMED", 1, "single case, not family-court"),
    ("Greenville", "Poore", "Margaret", "NOT_CONFIRMED", 0, "zero records at all"),
    ("Greenville", "Corral", "Emidio", "NOT_CONFIRMED", 0, "zero records at all"),
    ("Greenville", "Mahaffey", "Caroline", "NOT_CONFIRMED", 1, "exact full-name match to matched FCCMS case party; single case, not family-court"),
    ("Greenville", "Moore", "Gordon", "NOT_CONFIRMED", 0, "zero records at all"),
    ("Greenville", "Greene", "Amanda", "NOT_CONFIRMED", 0, "control: zero records"),
    ("Greenville", "Julian", "Family", "NOT_CONFIRMED", 0, "control: owner is 'JULIAN FAMILY LIVING TRUST', not a person; zero records"),
    ("Cherokee", "York", "Thomas", "NOT_CONFIRMED", 4, "owner matched to 'Thomas JOHN York'; live shows 'Thomas Franklin York III' / 'Thomas Justin York' -- different people"),
    ("Cherokee", "Nolan", "Teresa", "NOT_CONFIRMED", 6, "no family rows"),
    ("Cherokee", "Smith", "Christopher", "NOT_CONFIRMED", 124, "no family rows"),
    ("Cherokee", "Bishop", "Cherryl", "NOT_CONFIRMED", 1, "single case, not family-court"),
    ("Cherokee", "Chambers", "John", "NOT_CONFIRMED", 13, "no family rows"),
    ("Cherokee", "Johnson", "Steven", "NOT_CONFIRMED", 42, "no family rows"),
    ("Oconee", "Dunn", "Kristy", "NOT_CONFIRMED", 32, "exact full-name match to matched FCCMS case party (board's strongest-confidence match, 'match':'agrees'); 32 live records, zero family-court"),
    ("Oconee", "Martin", "Nicholas", "NOT_CONFIRMED", 6, "no family rows"),
    ("Oconee", "Chapman", "Shirley", "NOT_CONFIRMED", 4, "no family rows"),
    ("Oconee", "Perego", "Janice", "NOT_CONFIRMED", 27, "exact match to matched case party; no family rows"),
    ("Oconee", "Jenkins", "Kalena", "NOT_CONFIRMED", 33, "control: no family rows"),
    ("Anderson", "Gentle", "Leah", "NOT_CONFIRMED", 7, "no family rows"),
    ("Anderson", "Speight", "Debbie", "NOT_CONFIRMED", 0, "zero records at all"),
    ("Anderson", "Gaugler", "Warner", "NOT_CONFIRMED", 13, "exact match to matched case party; no family rows"),
    ("Laurens", "Johnson", "Richard", "NOT_CONFIRMED", 28, "control: owner is 'JOHNSON CAROL B', matched to 'Richard Johnson'; no family rows"),
    ("Union", "Dow", "Thomas", "NOT_CONFIRMED", 88, "no family rows"),
    ("Union", "Nave", "Crystal", "NOT_CONFIRMED", 50, "no family rows"),
]

assert len(live) == len(to_check) == 60, (len(live), len(to_check))

results = []
for entry, (county, s_last, s_first, verdict, rows, note) in zip(to_check, live):
    rec = dict(entry)
    rec["live_check"] = {
        "portal": "publicindex.sccourts.org",
        "county_searched": county,
        "search_last_name": s_last,
        "search_first_name": s_first,
        "verdict": verdict,
        "live_total_rows": rows,
        "note": note,
    }
    results.append(rec)

n_sampled = len(results)
n_skipped = sum(1 for r in results if r["live_check"]["verdict"] == "SKIPPED_NO_NAME")
n_checked = n_sampled - n_skipped
n_confirmed = sum(1 for r in results if r["live_check"]["verdict"] == "CONFIRMED")
n_not_confirmed = sum(1 for r in results if r["live_check"]["verdict"] == "NOT_CONFIRMED")
n_inconclusive = sum(1 for r in results if r["live_check"]["verdict"] == "INCONCLUSIVE_CAPPED")

summary = {
    "methodology": (
        "Population: SC board rows with raw['divorce'] real-positive "
        "((case_count or 0) > 0 OR cases list non-empty) -- 5,052 total across 8 SC core counties. "
        "Local pre-check (free, no network): re-applied the repo's own current "
        "enrichment_sc_divorce._owner_in_case() namesake-match logic to each record's CURRENT "
        "board owner_name against its matched FCCMS case parties text, plus flagged leads whose "
        "only matched case role(s) were Attorney/Guardian-ad-Litem (not an actual party). "
        "Random sample of 60 (seed=42 for the 50 'plausible positive' pool that passes both local "
        "checks; seed=43 for a 10-record 'locally bad' control group that already fails them) was "
        "then checked LIVE against the SC Public Index (publicindex.sccourts.org), per-county, by "
        "name search (Last+First, All Courts/All Case Types/All Case Sub-Types) -- the exact portal "
        "and method used in the original 116 Frey Rd manual check. No CAPTCHA was ever encountered; "
        "the only block hit was a per-county 250-row display cap on one very common name."
    ),
    "n_sampled": n_sampled,
    "n_skipped_no_owner_name": n_skipped,
    "n_checked_live": n_checked,
    "n_confirmed_real_divorce": n_confirmed,
    "n_not_confirmed": n_not_confirmed,
    "n_inconclusive_capped": n_inconclusive,
    "pct_confirmed_of_checked": round(100 * n_confirmed / n_checked, 1),
    "pct_not_confirmed_of_checked": round(100 * n_not_confirmed / n_checked, 1),
    "pct_inconclusive_of_checked": round(100 * n_inconclusive / n_checked, 1),
    "local_precheck_stats": {
        "total_real_positive_population": 5052,
        "locally_bad_namesake_fail_or_attorney_gal_only_role": 177,
        "pct_locally_bad": round(100 * 177 / 5052, 1),
        "passes_both_local_checks_plausible_pool": 4875,
        "pct_plausible": round(100 * 4875 / 5052, 1),
    },
}

out = {"summary": summary, "sample": results}
outp = SCRATCH / "divorce_validation_results.json"
outp.write_text(json.dumps(out, indent=2, default=str))
print(json.dumps(summary, indent=2))
print("\nWrote", len(results), "records to", outp)
