"""Real, live, at-scale accuracy validator for the `tax_lien` signal, Buncombe County.

Endpoints discovered live (browser network inspection, 2026-10-02), no auth, no CAPTCHA:
  - https://prc-buncombe.spatialest.com/api/v1/recordcard/{parcel}   (JSON: owner, value, building)
  - https://tax.buncombenc.gov/Parcel/Details/{parcel}               (HTML: year-by-year billing history)

Samples N real board rows flagged with a tax-delinquency-class signal in Buncombe
County, re-fetches both live sources per parcel, and reports a real accuracy
percentage instead of a one-property anecdote.
"""
import asyncio
import random
import re
import sys
import json
from pathlib import Path

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper import web_artifact
from foreclosure_scraper.http_client import get_text
import httpx

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")
N_SAMPLE = 60
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

BILL_RE = re.compile(
    r'/Bill/Details/(\d{10}-(\d{4})-\d{4}-\d{4}-\d{2})".*?'
    r'Amount Due</small>\s*<div class="fw-semibold">\$([\d,]+\.\d{2})</div>',
    re.S,
)
OWNER_RE = re.compile(r'Owner</small>\s*<div class="fw-semibold">\s*([^<]+?)\s*</div>')
VALUE_RE = re.compile(r'Value</small>\s*<div class="fw-semibold">\$([\d,]+)</div>')


def collect_candidates():
    rows = []
    for rec in web_artifact._iter_board_records(DOCS):
        if (rec.get("county") or "").strip() != "Buncombe":
            continue
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        raw = rec.get("raw") or {}
        ty = raw.get("two_year_delinquent")
        ta = raw.get("tax_aging_surfaced")
        lt = rec.get("listing_type")
        flagged = (
            (isinstance(ty, dict) and ty.get("is_two_year_plus"))
            or (isinstance(ta, dict) and ta.get("status") != "current" and (ta.get("years_delinquent") or 0) > 0)
            or lt == "tax_lien"
        )
        if not flagged:
            continue
        pid = rec.get("parcel_id")
        if not pid or not re.fullmatch(r"\d{15}", pid):
            continue
        rows.append({
            "parcel_id": pid,
            "owner_name": rec.get("owner_name"),
            "street_address": rec.get("street_address"),
            "board_value": rec.get("assessed_value") or rec.get("market_value") or rec.get("tax_value"),
            "board_listing_type": lt,
            "board_two_year": ty if isinstance(ty, dict) else None,
            "board_tax_aging": ta if isinstance(ta, dict) else None,
        })
    return rows


async def fetch_one(row: dict) -> dict:
    pid = row["parcel_id"]
    out = {**row, "fetch_ok": False}

    try:
        text2 = await get_text(
            f"https://tax.buncombenc.gov/Parcel/Details/{pid}",
            timeout=20, impersonate=True,
        )
        om = OWNER_RE.search(text2)
        vm = VALUE_RE.search(text2)
        out["real_owner"] = om.group(1).strip() if om else None
        out["real_value_str"] = vm.group(1) if vm else None
        bills = {}
        for m in BILL_RE.finditer(text2):
            year = int(m.group(2))
            amt = float(m.group(3).replace(",", ""))
            bills[year] = amt
        out["bills_by_year"] = bills
        if bills:
            this_year = max(bills.keys())
            prior_years_owed = {y: a for y, a in bills.items() if y < this_year and a > 0}
            out["real_prior_years_delinquent"] = len(prior_years_owed)
            out["real_prior_years_owed_detail"] = prior_years_owed
            out["real_total_prior_arrears"] = round(sum(prior_years_owed.values()), 2)
            out["fetch_ok"] = True
        else:
            out["tax_page_no_bills_parsed"] = True
            out["tax_page_len"] = len(text2)
    except Exception as e:
        out["tax_error"] = str(e)[:200]

    return out


async def main():
    candidates = collect_candidates()
    print(f"Total Buncombe tax-flagged candidates on board: {len(candidates)}", file=sys.stderr)
    random.seed(20261002)
    sample = random.sample(candidates, min(N_SAMPLE, len(candidates)))
    print(f"Sampling {len(sample)}", file=sys.stderr)

    sem = asyncio.Semaphore(5)

    async def bound_fetch(row):
        async with sem:
            r = await fetch_one(row)
            await asyncio.sleep(0.4)
            return r

    results = await asyncio.gather(*[bound_fetch(r) for r in sample])

    Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad/tax_lien_validation_results.json").write_text(
        json.dumps(results, indent=2, default=str)
    )

    ok = [r for r in results if r.get("fetch_ok")]
    print(f"\nFetched successfully: {len(ok)}/{len(results)}", file=sys.stderr)

    real_delinquent = [r for r in ok if (r.get("real_prior_years_delinquent") or 0) >= 1]
    real_multiyear = [r for r in ok if (r.get("real_prior_years_delinquent") or 0) >= 2]
    print(f"Board claims 'multi-year delinquent' type signal, N={len(ok)} checked:", file=sys.stderr)
    print(f"  Real: at least 1 real unpaid PRIOR year  : {len(real_delinquent)}/{len(ok)} ({100*len(real_delinquent)/max(len(ok),1):.1f}%)", file=sys.stderr)
    print(f"  Real: at least 2 real unpaid PRIOR years  : {len(real_multiyear)}/{len(ok)} ({100*len(real_multiyear)/max(len(ok),1):.1f}%)", file=sys.stderr)
    trivial = [r for r in real_delinquent if (r.get("real_total_prior_arrears") or 0) < 500]
    print(f"  Of those with >=1 prior-year arrears, trivial (<$500 total): {len(trivial)}/{len(real_delinquent) or 1}", file=sys.stderr)

    # value accuracy
    val_pairs = []
    for r in ok:
        bv = r.get("board_value")
        rv_str = r.get("real_value_str") or ""
        rv = None
        m = re.search(r"[\d,]+", rv_str)
        if m:
            try:
                rv = float(m.group(0).replace(",", ""))
            except ValueError:
                rv = None
        if bv and rv:
            val_pairs.append((bv, rv))
    if val_pairs:
        errs = [abs(bv - rv) / rv for bv, rv in val_pairs if rv]
        within10 = sum(1 for e in errs if e <= 0.10)
        print(f"\nValue accuracy, N={len(val_pairs)}:", file=sys.stderr)
        print(f"  Within 10% of real assessed value: {within10}/{len(val_pairs)} ({100*within10/len(val_pairs):.1f}%)", file=sys.stderr)
        print(f"  Median abs error: {sorted(errs)[len(errs)//2]*100:.1f}%", file=sys.stderr)
        print(f"  Max abs error: {max(errs)*100:.1f}%", file=sys.stderr)

    print("\nDONE", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
