"""Real, live, at-scale accuracy validator for the `elderly_disabled` signal,
Buncombe County NC.

BACKGROUND (prior manual check, 2026-10-02): a single elderly_disabled lead --
30 Laurel Branch Dr, owner Penny Mayronne -- turned out to have NO real
distress: paid off, no liens, and she is an ACTIVE, continuously-voting
Buncombe resident who voted in person 7 months ago (confirmed live via
vt.ncsbe.gov). Read: the statutory age/disability tax exemption alone is a
proxy for *possible* future motivation, not current distress, unless there is
a real corroborating problem -- genuine tax delinquency, or the owner no
longer showing up as an active local voter (suggesting a move to assisted
living, incapacity, or death).

This script checks that at scale, two ways, for every sampled Buncombe
elderly_disabled lead:

  (a) TAX: re-fetch https://tax.buncombenc.gov/Parcel/Details/{15-digit pin}
      (plain HTML, no auth) and look for real unpaid PRIOR-year tax bills --
      reusing validate_tax_lien_buncombe.py's tested fetch/parse logic
      directly (imported, not re-implemented). NOTE: Buncombe's GIS "pin"
      field used by the elderly-exemption source is the 10-digit form; the
      tax site's URL needs the 15-digit pinnum = 10-digit pin + "00000" (see
      enrichment_assessor_photo.buncombe_pin_variants -- confirmed live here:
      the bare 10-digit pin 400s on tax.buncombenc.gov).

  (b) VOTER: run the owner name through the new, reusable
      enrichment_nc_voter_lookup.nc_voter_lookup() point-lookup against
      vt.ncsbe.gov/RegLkup and check ACTIVE-registered-voter status +
      most-recent vote.

Streams the board via web_artifact._iter_board_records (never materializes the
full 200k+-row board), samples up to N_SAMPLE, runs both checks concurrently
per lead under a modest semaphore, and reports real percentages.
"""
import asyncio
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper import web_artifact
from foreclosure_scraper.enrichment_nc_voter_lookup import nc_voter_lookup, split_owner_name

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")
SCRATCH = Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad")
OUT_JSON = SCRATCH / "elderly_validation_results.json"
N_SAMPLE = 5
TRIVIAL_ARREARS_USD = 100.0  # below this, "delinquency" is rounding/fee noise, not real distress

# --- reuse the ALREADY-WORKING tax validator's tested fetch/parse logic directly ---
_spec = importlib.util.spec_from_file_location(
    "validate_tax_lien_buncombe", str(SCRATCH / "validate_tax_lien_buncombe.py")
)
taxmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(taxmod)  # module-level code only defines funcs/regexes; __main__ guarded

_ENTITY_RE = re.compile(
    r"\b(LLC|INC|CORP|TRUST|TRUSTEE|ESTATE|LP|LLP|CO|COMPANY|BANK|CHURCH|"
    r"FOUNDATION|ASSOC|PARTNERSHIP|VFW|HOLDINGS|MINISTR|APARTMENTS|PROPERTIES)\b",
    re.I,
)


def buncombe_pin15(pin10: str) -> str | None:
    d = re.sub(r"\D", "", pin10 or "")
    if len(d) == 10:
        return d + "00000"
    if len(d) == 15:
        return d
    return None


def collect_candidates() -> list[dict]:
    rows = []
    for rec in web_artifact._iter_board_records(DOCS):
        if (rec.get("county") or "").strip() != "Buncombe":
            continue
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        if rec.get("listing_type") != "elderly_disabled":
            continue
        owner = (rec.get("owner_name") or "").strip()
        if not owner or _ENTITY_RE.search(owner):
            continue  # entity/trust-owned: no personal voter record to check
        name = split_owner_name(owner)
        if not name:
            continue
        pin10 = rec.get("parcel_id")
        pin15 = buncombe_pin15(pin10) if pin10 else None
        if not pin15:
            continue
        first, last = name
        rows.append({
            "parcel_id": pin10,
            "parcel_id_15": pin15,
            "owner_name_board": owner,
            "first_name": first,
            "last_name": last,
            "street_address": rec.get("street_address"),
            "city": rec.get("city"),
            "board_assessed_value": rec.get("assessed_value") or rec.get("market_value"),
            "gis_exempt": (rec.get("raw") or {}).get("gis_exempt"),
        })
    return rows


async def check_one(row: dict, tax_sem: asyncio.Semaphore, voter_sem: asyncio.Semaphore) -> dict:
    out = dict(row)

    async def do_tax():
        async with tax_sem:
            r = await taxmod.fetch_one({"parcel_id": row["parcel_id_15"]})
            await asyncio.sleep(0.3)
            return r

    async def do_voter():
        async with voter_sem:
            r = await nc_voter_lookup(
                row["first_name"], row["last_name"], "BUNCOMBE",
                match_city=row.get("city"), include_history=True,
            )
            await asyncio.sleep(0.3)
            return r

    tax_res, voter_res = await asyncio.gather(do_tax(), do_voter())
    out["tax"] = tax_res
    out["voter"] = voter_res
    return out


async def main():
    candidates = collect_candidates()
    print(f"Total Buncombe elderly_disabled candidates (personal owners, usable parcel id): "
          f"{len(candidates)}", file=sys.stderr)

    random.seed(20261002)
    sample = random.sample(candidates, min(N_SAMPLE, len(candidates)))
    print(f"Sampling {len(sample)}", file=sys.stderr)

    tax_sem = asyncio.Semaphore(5)
    voter_sem = asyncio.Semaphore(4)
    results = await asyncio.gather(*[check_one(r, tax_sem, voter_sem) for r in sample])

    OUT_JSON.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nWrote {len(results)} rows to {OUT_JSON}", file=sys.stderr)

    # --- aggregate real numbers ---
    n = len(results)
    tax_ok = [r for r in results if r["tax"].get("fetch_ok")]
    voter_ok = [r for r in results if r["voter"].get("ok")]
    both_ok = [r for r in results if r["tax"].get("fetch_ok") and r["voter"].get("ok")]

    any_delinquent = [
        r for r in tax_ok
        if (r["tax"].get("real_prior_years_delinquent") or 0) >= 1
    ]
    real_delinquent = [
        r for r in any_delinquent
        if (r["tax"].get("real_total_prior_arrears") or 0) >= TRIVIAL_ARREARS_USD
    ]

    active_voters = [r for r in voter_ok if r["voter"].get("status") == "active"]
    not_active = [r for r in voter_ok if r["voter"].get("status") == "not_active"]
    not_found = [r for r in voter_ok if r["voter"].get("status") == "not_found"]
    ambiguous = [r for r in voter_ok if r["voter"].get("status") == "ambiguous"]
    worth_flagging = not_active + not_found  # no corroborating liveness signal

    any_corroboration = [
        r for r in both_ok
        if (r["tax"].get("real_prior_years_delinquent") or 0) >= 1
        or r["voter"].get("status") in ("not_active", "not_found")
    ]
    clean_like_penny = [
        r for r in both_ok
        if (r["tax"].get("real_prior_years_delinquent") or 0) == 0
        and r["voter"].get("status") == "active"
    ]

    def pct(k, d):
        return f"{k}/{d} ({100*k/d:.1f}%)" if d else f"{k}/0 (n/a)"

    print("\n=== ELDERLY_DISABLED VALIDATOR, BUNCOMBE COUNTY NC ===", file=sys.stderr)
    print(f"N sampled: {n}", file=sys.stderr)
    print(f"N tax fetch ok: {len(tax_ok)}  |  N voter lookup ok: {len(voter_ok)}  |  "
          f"N BOTH ok: {len(both_ok)}", file=sys.stderr)

    print(f"\nTax delinquency (of {len(tax_ok)} tax-checked):", file=sys.stderr)
    print(f"  Any prior-year unpaid balance        : {pct(len(any_delinquent), len(tax_ok))}", file=sys.stderr)
    print(f"  Non-trivial (>=${TRIVIAL_ARREARS_USD:.0f}) prior-year arrears: "
          f"{pct(len(real_delinquent), len(tax_ok))}", file=sys.stderr)

    print(f"\nVoter status (of {len(voter_ok)} voter-checked):", file=sys.stderr)
    print(f"  ACTIVE registered voter (liveness, argues AGAINST urgency): "
          f"{pct(len(active_voters), len(voter_ok))}", file=sys.stderr)
    print(f"  NOT ACTIVE (removed/inactive/denied)  : {pct(len(not_active), len(voter_ok))}", file=sys.stderr)
    print(f"  NOT FOUND in voter file                : {pct(len(not_found), len(voter_ok))}", file=sys.stderr)
    print(f"  Ambiguous (multiple same-name matches) : {pct(len(ambiguous), len(voter_ok))}", file=sys.stderr)
    print(f"  Worth flagging (not_active + not_found): {pct(len(worth_flagging), len(voter_ok))}", file=sys.stderr)

    print(f"\nCombined read (of {len(both_ok)} checked BOTH ways):", file=sys.stderr)
    print(f"  ANY real corroborating distress signal (tax delinquent OR not an active voter): "
          f"{pct(len(any_corroboration), len(both_ok))}", file=sys.stderr)
    print(f"  Clean like Penny Mayronne (no tax delinquency AND confirmed active voter): "
          f"{pct(len(clean_like_penny), len(both_ok))}", file=sys.stderr)

    print("\nDONE", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
