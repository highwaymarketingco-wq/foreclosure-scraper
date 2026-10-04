"""Real, live, at-scale accuracy validator for the `probate` / `heir_estate`
signal types -- Buncombe County NC -- closing the gap the task brief
identifies: a single fully-manual N=1 case (50 Boone St) held up, but
probate/heir has never been checked at the N=50-60 scale this project uses
for every other signal type (see docs/validation_2026-10-02/FINDINGS.md).

Three checks, matching the Boone St methodology as closely as the free/no-
CAPTCHA surface allows:

  1. DEATH RECORD -- does the named decedent have a real entry in Buncombe
     Register of Deeds' own DEATHS index (Cott/Aumentum eSearch v4,
     ddlIndexType="DTH" -- confirmed live 2026-10-03, same vendor/session
     protocol as rod/aumentum.py, no CAPTCHA)?

  2. TRANSFER PATTERN -- does the parcel's recorded sale history (Buncombe
     Spatialest record-card via assessor_cards.buncombe_nc.fetch(), reused
     verbatim -- it already resolves the PIN and renders the card through a
     stealth headless browser, since the JSON API 403s direct httpx) show a
     transfer pattern consistent with an heir/estate move (no sale since the
     claimed case year, or a $0/exempt/family/quitclaim transfer) -- or
     inconsistent (a normal arm's-length sale after the claimed case year,
     meaning the property already left the family's hands)?

  3. NAMED-HEIR LIVENESS -- for whichever rows actually carry a named
     individual (NOT bare presence of the probate/heir_estate block itself --
     most rows carry only a decedent name and a case number, no heir names at
     all; see the pool-shape inspection in this script's collect_pool()),
     run that name through enrichment_nc_voter_lookup.nc_voter_lookup() and
     report what fraction resolve to a confirmed, locatable, active voter.

NC eCourts (the Boone St case's heir-count/name source) is CAPTCHA-walled --
per the task brief, this script does NOT attempt it. Check 1 substitutes a
different free, live, no-CAPTCHA primary source for "is this death real."

Pool-shape finding (2026-10-03, inspected ~254 raw Buncombe probate/heir rows
before writing this script): raw['probate'] blocks carry `personal_representative`
on only 4/202 probate_notice rows; raw['heir_estate'] blocks carry `care_of` on
20/52 estate_lead rows. `heir_estate.heir_names` -- a structured per-heir list the
current nc_heir_estate_parcels.py scraper code is DESIGNED to emit -- is present
on ZERO rows in the live board snapshot used here, meaning either the board was
built from code older than that feature or something drops it before the board
is written; worth a separate look, out of scope for this validator. Given that,
the only named individuals checkable at all are `personal_representative` (PR/
executor -- a real party but not necessarily an heir) and `care_of` (an heir's
or agent's name the county tax roll captured) -- 24 rows board-wide in Buncombe,
checked here as a FULL CENSUS of that sub-population, not a sample.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")

from foreclosure_scraper import web_artifact  # noqa: E402
from foreclosure_scraper.signal_freshness import has_real_probate  # noqa: E402
from foreclosure_scraper.enrichment_nc_voter_lookup import nc_voter_lookup  # noqa: E402
from foreclosure_scraper.rod import aumentum  # noqa: E402
from foreclosure_scraper.assessor_cards import buncombe_nc  # noqa: E402
from foreclosure_scraper.assessor_cards.base import ARMS_LENGTH_MIN, _NON_ARMS  # noqa: E402

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")
SCRATCH = Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad")
OUT_JSON = SCRATCH / "probate_heir_validation_results.json"

SEED = 20261003
N_SAMPLE = 55  # drawn from the checkable-decedent-name pool, for checks 1+2

_ENTITY_RE = re.compile(
    r"\b(LLC|L\.L\.C|INC|CORP|CO\.?|LP|LLP|COMPANY|CHURCH|BANK|TRUST|TRUSTEE|"
    r"FOUNDATION|MINISTR|APARTMENTS|PROPERTIES|ASSOCIATES|PARTNERSHIP)\b", re.I,
)
_HEIR_SUFFIX_RE = re.compile(
    r"\(HEIRS\)|\bHEIRS?\s*OF\b|\bHEIRS?\b|\bESTATE\s+OF\b|\bESTATE\b|\bTRUSTEE\b", re.I,
)
_TRAILING_NOISE_RE = re.compile(r"(?:\d+\s*/\s*\d+|ET\s*AL\.?|\bOF)\s*$", re.I)


# --------------------------------------------------------------------------- #
# Pool collection
# --------------------------------------------------------------------------- #
def _derive_decedent_name(rec: dict) -> tuple[str | None, str]:
    """Returns (decedent_name, source) where source in
    {"probate.decedent","heir_estate.owner_of_record","owner_name","none"}."""
    raw = rec.get("raw") or {}
    lt = rec.get("listing_type")
    pr = raw.get("probate")
    he = raw.get("heir_estate")

    if isinstance(pr, dict) and has_real_probate(pr):
        dec = (pr.get("decedent") or "").strip().split(";")[0].strip()
        if dec:
            return dec, "probate.decedent"
        # has a case/file number but no decedent name -- not checkable for
        # check 1 (no name to search), but still a real positive for the pool.
        return None, "probate_no_decedent_name"

    if isinstance(he, dict) and he.get("owner_of_record"):
        first_owner = he["owner_of_record"].split(";")[0].strip()
        stripped = _HEIR_SUFFIX_RE.sub(" ", first_owner)
        stripped = _TRAILING_NOISE_RE.sub("", stripped)
        stripped = re.sub(r"\s+", " ", stripped).strip(" ,;")
        if stripped and not _ENTITY_RE.search(stripped):
            return stripped, "heir_estate.owner_of_record"
        return None, "heir_estate_entity_or_empty"

    if lt in ("probate_notice", "estate_lead"):
        owner = (rec.get("owner_name") or "").strip().split(";")[0].strip()
        if owner and not _ENTITY_RE.search(owner):
            return owner, "owner_name_fallback"
        return None, "no_name_at_all"

    return None, "none"


def collect_pool() -> list[dict]:
    rows = []
    stats = {"total_buncombe_positive": 0, "by_listing_type": {}, "checkable_decedent_name": 0,
             "n_personal_representative": 0, "n_care_of": 0}
    for rec in web_artifact._iter_board_records(DOCS):
        if (rec.get("county") or "").strip() != "Buncombe":
            continue
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        raw = rec.get("raw") or {}
        pr = raw.get("probate")
        he = raw.get("heir_estate")
        lt = rec.get("listing_type")
        is_pos = (
            (isinstance(pr, dict) and has_real_probate(pr))
            or (isinstance(he, dict) and (he.get("decedent") or he.get("case_number")
                                           or he.get("es_case_number") or he.get("nc_estate_file_no")))
            or lt in ("probate_notice", "estate_lead")
        )
        if not is_pos:
            continue
        stats["total_buncombe_positive"] += 1
        stats["by_listing_type"][lt] = stats["by_listing_type"].get(lt, 0) + 1

        decedent, source = _derive_decedent_name(rec)
        pid = rec.get("parcel_id")
        pid_digits = re.sub(r"\D", "", pid or "")
        usable_parcel = pid_digits if len(pid_digits) in (10, 15) else None

        pr_name = (pr.get("personal_representative") or "").strip() if isinstance(pr, dict) else ""
        care_of = (he.get("care_of") or "").strip() if isinstance(he, dict) else ""
        mailing = (he.get("mailing") or "") if isinstance(he, dict) else ""
        if pr_name:
            stats["n_personal_representative"] += 1
        if care_of:
            stats["n_care_of"] += 1

        if decedent:
            stats["checkable_decedent_name"] += 1

        rows.append({
            "listing_type": lt,
            "owner_name": rec.get("owner_name"),
            "street_address": rec.get("street_address"),
            "parcel_id": pid,
            "parcel_id_usable": usable_parcel,
            "decedent_name": decedent,
            "decedent_source": source,
            "es_case_number": (pr.get("es_case_number") if isinstance(pr, dict) else None),
            "nc_estate_file_no": (pr.get("nc_estate_file_no") if isinstance(pr, dict) else None),
            "personal_representative": pr_name or None,
            "pr_role": (pr.get("pr_role") if isinstance(pr, dict) else None),
            "heir_estate_care_of": care_of or None,
            "heir_estate_mailing": mailing or None,
            "heir_estate_match": (he.get("match") if isinstance(he, dict) else None),
        })
    return rows, stats


# --------------------------------------------------------------------------- #
# Check 1: Register of Deeds DEATHS index (Cott/Aumentum ddlIndexType=DTH)
# --------------------------------------------------------------------------- #
BASE = aumentum.AUMENTUM_COUNTIES[("NC", "Buncombe")]
_SUFFIX_RE = re.compile(r"\b(JR|SR|II|III|IV)\b\.?", re.I)


def _name_tokens(name: str) -> list[str]:
    name = _SUFFIX_RE.sub(" ", name or "")
    name = re.sub(r"[.,]", " ", name)
    name = re.sub(r"\s+", " ", name).strip().upper()
    return [t for t in name.split() if t]


def _candidate_pairs(name: str) -> list[tuple[str, str]]:
    """Human-order decedent names are mostly 'First [Middle] Last'; some
    estate_lead-derived candidates may still be GIS surname-first. Try both
    (last-token-as-surname) and (first-token-as-surname), deduped."""
    toks = _name_tokens(name)
    toks = [t for t in toks if len(t) > 1]  # drop bare initials for the surname/given slots
    if not toks:
        return []
    if len(toks) == 1:
        return [(toks[0], "")]
    pairs = [(toks[-1], toks[0]), (toks[0], toks[1] if len(toks) > 1 else "")]
    seen, out = set(), []
    for p in pairs:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _death_search_body(last: str, first: str) -> dict:
    body = aumentum._name_body(last, first)
    body[aumentum._P_NAME + "ddlIndexType"] = "DTH"
    return body


async def _death_search_one(session, final_url: str, last: str, first: str) -> list:
    r = await session.post(final_url, data=_death_search_body(last, first),
                            headers={"Referer": final_url}, allow_redirects=True, timeout=60)
    return aumentum._parse_instruments_grid(r.text, "Buncombe", "NC")


def _match_quality(decedent_tokens: list[str], grantor_field: str) -> str:
    """decedent_tokens already filtered to len>1 tokens (first/middle/last,
    no bare initials -- e.g. 'J G Huntsinger' reduces to just ['HUNTSINGER']).

    'full' = all decedent tokens present in grantor field (>=2 tokens, i.e. at
    least first+last verified). 'first_last' = first AND last token both
    present (middle, if any, unmatched) -- also requires >=2 tokens.
    'surname_only' = decedent_tokens has exactly ONE real token (every given/
    middle name on the board was a bare initial) -- the surname is present but
    there is NO way to verify first-name agreement; caught live during this
    validator's dry run ('J G HUNTSINGER' surname-only-matched a real but
    unrelated 'Judy Marie Huntsinger' out of 130 same-surname DEATHS rows) --
    callers must NOT treat this the same as a verified match. 'weak' = even
    the surname isn't present (shouldn't normally happen since the search
    itself was keyed on a surname candidate, but can if only the OTHER
    candidate-pair's surname guess was right)."""
    g = (grantor_field or "").upper()
    g_toks = set(re.sub(r"[.,]", " ", g).split())
    if len(decedent_tokens) == 1:
        return "surname_only" if decedent_tokens[0] in g_toks else "weak"
    present = [t for t in decedent_tokens if t in g_toks]
    if len(present) == len(decedent_tokens) and decedent_tokens:
        return "full"
    first, last = decedent_tokens[0], decedent_tokens[-1]
    if first in g_toks and last in g_toks:
        return "first_last"
    return "weak"


_QUALITY_RANK = {"full": 2, "first_last": 1, "surname_only": 0}


async def death_index_check(session, final_url: str, row: dict, cache: dict) -> dict:
    name = row["decedent_name"]
    if not name:
        return {"category": "not_checkable", "reason": row["decedent_source"]}
    pairs = _candidate_pairs(name)
    dtoks = [t for t in _name_tokens(name) if len(t) > 1]
    if not pairs or not dtoks:
        return {"category": "not_checkable", "reason": "no_usable_tokens"}

    key = name.strip().upper()
    if key not in cache:
        all_rows = []
        seen = set()
        for last, first in pairs:
            try:
                rows = await _death_search_one(session, final_url, last, first)
            except Exception as exc:  # noqa: BLE001
                print(f"    death-search failed ({last!r},{first!r}): {type(exc).__name__}: {str(exc)[:150]}")
                continue
            for r in rows:
                k = (r.book, r.page, r.grantor, r.grantee)
                if k in seen:
                    continue
                seen.add(k)
                all_rows.append(r)
            await asyncio.sleep(0.25)
        cache[key] = all_rows
    rows = cache[key]

    if not rows:
        return {"category": "no_record", "n_raw_rows": 0}

    scored = []
    for r in rows:
        q = _match_quality(dtoks, r.grantor or "")
        if q == "weak":
            continue
        try:
            book_num = int(re.sub(r"\D", "", r.book or "0") or 0)
        except ValueError:
            book_num = 0
        scored.append((_QUALITY_RANK[q], book_num, q, r))
    if not scored:
        return {"category": "no_matching_record", "n_raw_rows": len(rows)}
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    rank, book_num, quality, best = scored[0]

    if quality == "surname_only" and len(rows) > 3:
        # Only an initials-only decedent name to go on, AND a common-enough
        # surname that a real match can't be told apart from a same-surname
        # stranger -- do not count this as confirmed either way.
        category = "ambiguous_insufficient_name_data"
    else:
        category = "death_confirmed"
    return {
        "category": category,
        "match_quality": quality,
        "n_raw_rows": len(rows),
        "n_candidate_matches": len(scored),
        "matched_grantor": best.grantor,
        "matched_grantee": best.grantee,
        "matched_book": best.book,
        "matched_page": best.page,
    }


# --------------------------------------------------------------------------- #
# Check 2: recorded transfer history via Buncombe Spatialest record-card
# --------------------------------------------------------------------------- #
def _case_year(row: dict) -> int | None:
    for k in ("es_case_number", "nc_estate_file_no"):
        v = row.get(k)
        m = re.match(r"^\s*(\d{2})[A-Za-z]", v or "")
        if m:
            yy = int(m.group(1))
            return 2000 + yy
    return None


def _sale_is_arms_length(sale) -> bool:
    price_ok = (sale.price or 0) >= ARMS_LENGTH_MIN
    reason = (sale.reason or "").lower()
    non_arms = any(tok in reason for tok in _NON_ARMS)
    return price_ok and not non_arms


CURRENT_YEAR = 2026
# When there's no case-number year to anchor on (heir_estate/owner_name_fallback
# rows never carry one), only a sale within this many years of today counts as
# live counter-evidence that the property already left the family's hands --
# an old sale (e.g. 2009) sitting as the single most-recent record on file is
# NOT evidence of anything current; it just means nothing has moved since,
# which argues FOR the heir/estate framing, not against it. Without this
# window, the most-recent-sale-is-newest-first fact alone was silently
# mis-scoring decades-old qualified sales as "already sold, heir-framing
# stale" -- caught and fixed during this validator's own dry run, 2026-10-03.
RECENCY_WINDOW_YEARS = 3


async def transfer_check(row: dict) -> dict:
    pid = row.get("parcel_id_usable")
    if not pid:
        return {"category": "not_checkable", "reason": "no_usable_parcel_id"}
    li = types.SimpleNamespace(parcel_id=pid, street_address=row.get("street_address"))
    try:
        card = await buncombe_nc.fetch(li)
    except Exception as exc:  # noqa: BLE001
        return {"category": "fetch_error", "reason": f"{type(exc).__name__}: {str(exc)[:150]}"}
    if card is None:
        return {"category": "no_card_data"}

    sales = card.sales or []
    case_year = _case_year(row)
    out = {
        "category": None,
        "market_value": card.market_value,
        "n_sales_on_record": len(sales),
        "case_year_proxy": case_year,
        "sales": [s.as_dict() for s in sales[:5]],
    }
    if not sales:
        out["category"] = "no_sales_on_record"
        return out

    most_recent = sales[0]
    recent_year = None
    if most_recent.sale_date:
        m = re.match(r"^(\d{4})", most_recent.sale_date)
        if m:
            recent_year = int(m.group(1))

    threshold_year = case_year if case_year else (CURRENT_YEAR - RECENCY_WINDOW_YEARS)
    if not recent_year or recent_year < threshold_year:
        out["category"] = "no_recent_transfer"
        return out

    if _sale_is_arms_length(most_recent):
        out["category"] = "inconsistent_arms_length_sale"
    else:
        out["category"] = "consistent_nonarms_length_or_exempt"
    return out


# --------------------------------------------------------------------------- #
# Check 3: named-heir/PR liveness via NC voter lookup (full census of the
# small sub-population that carries ANY named individual)
# --------------------------------------------------------------------------- #
_CITY_FROM_MAILING_RE = re.compile(r"([A-Za-z'-]+)\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$")


def _split_human_name(name: str) -> tuple[str, str] | None:
    toks = [t for t in re.sub(r"[.,]", " ", name or "").split() if t]
    if len(toks) < 2:
        return None
    return toks[0], toks[-1]


def _city_from_mailing(mailing: str | None) -> str | None:
    if not mailing:
        return None
    m = _CITY_FROM_MAILING_RE.search(mailing.strip())
    return m.group(1).strip() if m else None


async def heir_voter_check(row: dict) -> dict:
    name = row.get("personal_representative") or row.get("heir_estate_care_of")
    role = "personal_representative" if row.get("personal_representative") else "care_of"
    if not name:
        return None
    split = _split_human_name(name)
    if not split:
        return {"role": role, "name": name, "category": "unparseable_name"}
    first, last = split
    city = _city_from_mailing(row.get("heir_estate_mailing"))
    try:
        res = await nc_voter_lookup(first, last, "ALL", match_city=city, include_history=True)
    except Exception as exc:  # noqa: BLE001
        return {"role": role, "name": name, "category": "lookup_error", "error": f"{type(exc).__name__}: {str(exc)[:150]}"}
    if not res.get("ok"):
        return {"role": role, "name": name, "category": "lookup_error", "error": res.get("error")}
    status = res.get("status")
    category = {
        "active": "confirmed_active_locatable",
        "not_active": "found_but_not_active",
        "not_found": "not_found",
        "ambiguous": "ambiguous_common_name",
    }.get(status, status)
    return {
        "role": role, "name": name, "category": category,
        "match_city_hint": city, "voter_result": res,
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
async def main():
    print("Collecting Buncombe NC probate/heir pool from board...", file=sys.stderr)
    pool, pool_stats = collect_pool()
    print(json.dumps(pool_stats, indent=2), file=sys.stderr)

    checkable = [r for r in pool if r["decedent_name"]]
    random.seed(SEED)
    sample = random.sample(checkable, min(N_SAMPLE, len(checkable)))
    print(f"Pool total={len(pool)} | checkable-decedent-name={len(checkable)} | sampling={len(sample)}",
          file=sys.stderr)

    from curl_cffi.requests import AsyncSession

    # --- Check 1: DEATHS index, concurrency-safe within one curl_cffi session ---
    death_results = {}
    death_cache: dict = {}
    async with AsyncSession(verify=False, impersonate="chrome") as s:
        boot = await s.get(f"{BASE}/SrchName.aspx", allow_redirects=True, timeout=30)
        final_url = str(boot.url)
        if aumentum._is_login_wall(final_url):
            print("LOGIN WALL on SrchName.aspx -- aborting check 1", file=sys.stderr)
        else:
            for i, row in enumerate(sample, 1):
                print(f"[death {i}/{len(sample)}] {row['decedent_name']!r}", file=sys.stderr)
                res = await death_index_check(s, final_url, row, death_cache)
                death_results[id(row)] = res
                print(f"    -> {res.get('category')}", file=sys.stderr)

    # --- Check 2: transfer history via headless record-card render, low concurrency ---
    transfer_sem = asyncio.Semaphore(3)

    async def bound_transfer(row):
        async with transfer_sem:
            r = await transfer_check(row)
            await asyncio.sleep(0.3)
            return r

    print("\nRunning transfer-history checks...", file=sys.stderr)
    transfer_list = await asyncio.gather(*[bound_transfer(r) for r in sample])
    transfer_results = {id(row): res for row, res in zip(sample, transfer_list)}

    # --- Check 3: full census of rows carrying a named individual ---
    named_pool = [r for r in pool if r.get("personal_representative") or r.get("heir_estate_care_of")]
    print(f"\nNamed-individual sub-population (full census): {len(named_pool)} rows", file=sys.stderr)
    voter_sem = asyncio.Semaphore(4)

    async def bound_voter(row):
        async with voter_sem:
            r = await heir_voter_check(row)
            await asyncio.sleep(0.3)
            return r

    voter_list = await asyncio.gather(*[bound_voter(r) for r in named_pool])

    # --- assemble per-row sample output ---
    sample_out = []
    for row in sample:
        sample_out.append({
            **row,
            "death_check": death_results.get(id(row)),
            "transfer_check": transfer_results.get(id(row)),
        })

    named_out = [{**row, "voter_check": vc} for row, vc in zip(named_pool, voter_list) if vc is not None]

    # --- aggregate numbers ---
    def pct(k, d):
        return round(100 * k / d, 1) if d else None

    n_sample = len(sample_out)
    death_confirmed = [r for r in sample_out if r["death_check"]["category"] == "death_confirmed"]
    death_no_record = [r for r in sample_out if r["death_check"]["category"] in ("no_record", "no_matching_record")]
    death_ambiguous = [r for r in sample_out if r["death_check"]["category"] == "ambiguous_insufficient_name_data"]
    death_not_checkable = [r for r in sample_out if r["death_check"]["category"] == "not_checkable"]
    death_checked_n = n_sample - len(death_not_checkable)

    xfer_checked = [r for r in sample_out if r["transfer_check"]["category"] not in ("not_checkable", "fetch_error", "no_card_data")]
    xfer_consistent = [r for r in xfer_checked if r["transfer_check"]["category"] in
                       ("no_recent_transfer", "consistent_nonarms_length_or_exempt", "no_sales_on_record")]
    xfer_inconsistent = [r for r in xfer_checked if r["transfer_check"]["category"] == "inconsistent_arms_length_sale"]

    voter_checked = [r for r in named_out if r["voter_check"]["category"] not in ("lookup_error", "unparseable_name")]
    voter_confirmed_active = [r for r in voter_checked if r["voter_check"]["category"] == "confirmed_active_locatable"]

    summary = {
        "pool_stats": pool_stats,
        "n_checkable_decedent_name": len(checkable),
        "pct_pool_with_checkable_decedent_name": pct(len(checkable), len(pool)),
        "n_sampled": n_sample,

        "check1_death_record": {
            "n_checked": death_checked_n,
            "n_not_checkable_no_name": len(death_not_checkable),
            "n_confirmed_real_death_record": len(death_confirmed),
            "pct_confirmed_real_death_record": pct(len(death_confirmed), death_checked_n),
            "n_no_record_found": len(death_no_record),
            "pct_no_record_found": pct(len(death_no_record), death_checked_n),
            "n_ambiguous_insufficient_name_data": len(death_ambiguous),
            "pct_ambiguous_insufficient_name_data": pct(len(death_ambiguous), death_checked_n),
        },
        "check2_transfer_pattern": {
            "n_checked": len(xfer_checked),
            "n_not_checkable_no_parcel_or_fetch_error": n_sample - len(xfer_checked),
            "n_consistent_with_heir_estate": len(xfer_consistent),
            "pct_consistent_with_heir_estate": pct(len(xfer_consistent), len(xfer_checked)),
            "n_inconsistent_already_sold_arms_length": len(xfer_inconsistent),
            "pct_inconsistent_already_sold_arms_length": pct(len(xfer_inconsistent), len(xfer_checked)),
        },
        "check3_named_heir_voter_liveness": {
            "n_pool_rows_with_any_named_individual": len(named_pool),
            "pct_of_total_pool_with_any_named_individual": pct(len(named_pool), len(pool)),
            "n_checked": len(voter_checked),
            "n_confirmed_active_locatable": len(voter_confirmed_active),
            "pct_confirmed_active_locatable": pct(len(voter_confirmed_active), len(voter_checked)),
        },
    }

    print("\n=== SUMMARY ===", file=sys.stderr)
    print(json.dumps(summary, indent=2), file=sys.stderr)

    OUT_JSON.write_text(json.dumps({
        "summary": summary,
        "sample_results": sample_out,
        "named_individual_census_results": named_out,
    }, indent=2, default=str))
    print(f"\nwrote -> {OUT_JSON}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
