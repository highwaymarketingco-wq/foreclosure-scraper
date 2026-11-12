"""Real, live, at-scale accuracy validator for lis-pendens/foreclosure-flagged rows,
Buncombe County NC.

Checks, per the live 101 Greenwells Glory Dr / Richard Burton manual finding, on TWO
checkable dimensions:
  (a) VALUE ACCURACY   -- board-claimed value vs tax.buncombenc.gov/Parcel/Details/{pid}
                           real current assessed value (same regexes as the prior
                           validate_tax_lien_buncombe.py reference script).
  (b) ROD CORROBORATION -- does the Buncombe Register of Deeds (registerofdeeds.buncombenc.gov,
                           Cott Systems "eSearch" app) show ANY real recent corroborating
                           recorded instrument (lien, judgment, unsatisfied DOT-adjacent
                           distress filing, foreclosure notice) for that specific owner,
                           versus a clean/resolved record (e.g. mortgage satisfied, nothing
                           since) -- and whether multiple unrelated same-surname people show
                           up in the ROD results (name-collision risk).

ROD endpoint, reverse-engineered live (2026-10-02) via the browser's network tab + DOM
inspection: this is NOT a JSON API -- it's a classic ASP.NET WebForms app
(registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4/SrchName.aspx), a plain
form POST, no ViewState-blob requirement (EnableViewState is effectively off for the fields
that matter), no CAPTCHA token in the form at all (the reCAPTCHA v3 <script> tag is loaded
in <head> but no g-recaptcha-response field exists anywhere in aspnetForm, and a clean POST
succeeds without one). The one real trap: the `ctl00_cphMain_tcMain_ClientState` hidden
field's value attribute is HTML-entity-escaped JSON (`&quot;` etc) in the raw markup -- POST
that back VERBATIM (not html.unescape()'d) and the server throws and redirects to a generic
v2Error.aspx with no useful message. html.unescape() every hidden-field value before
resubmitting and it works first try. The two watermark-style text inputs
(txtFiledFrom/txtFiledThru) also literally submit the strings "From"/"Thru" when left at
their placeholder state -- empty string is wrong and also errors.

Search is restricted to Index Type = CRP (Consolidated Real Property: deeds, deeds of
trust, satisfactions, assignments, liens, notices, judgments post-1995 -- the one index
type NC's G.S. 1-116/1-120 cross-indexing would land a lis pendens notice in), sorted Date
Descending, default page size (250 rows) -- plenty for a single surname's post-1995 history
in one page, confirmed against the real "Burton" test case below.
"""
import asyncio
import html
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper import web_artifact
from foreclosure_scraper.http_client import get_text

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")
OUT_PATH = Path(
    "/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/"
    "scratchpad/lis_pendens_validation_results.json"
)
N_SAMPLE = 50
LISTING_TYPES = ("foreclosure_sale", "lis_pendens", "sheriff_sale", "auction")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

# ---- value-accuracy regexes, reused verbatim from validate_tax_lien_buncombe.py --------
OWNER_RE = re.compile(r'Owner</small>\s*<div class="fw-semibold">\s*([^<]+?)\s*</div>')
VALUE_RE = re.compile(r'Value</small>\s*<div class="fw-semibold">\$([\d,]+)</div>')

# ---- ROD (registerofdeeds.buncombenc.gov) ------------------------------------------------
ROD_BASE = "https://registerofdeeds.buncombenc.gov"
ROD_LOGIN = f"{ROD_BASE}/External/User/Login.aspx"
ROD_SEARCH_PATH = "/External/LandRecords/protected/v4/SrchName.aspx"
ROD_FORM = "ctl00$cphMain$tcMain$tpNewSearch$ucSrchNames$"

DISTRESS_KEYWORDS = (
    "LIS PENDENS", "JUDGMENT", "JUDGEMENT", "LIEN", "NOTICE", "FORECLOSURE",
    "SUBSTITUTE TRUSTEE", "TRUSTEE DEED", "CLAIM", "ATTACHMENT", "EXECUTION",
    "LEVY", "SHERIFF",
)
BENIGN_RESOLUTION_KEYWORDS = ("SATISFACTION", "CANCELLATION", "RESCISSION", "RELEASE", "REAFFIRMATION")

ENTITY_RE = re.compile(
    r"\b(LLC|L\.L\.C|INC|CORP|COMPANY|CO\.|L\.P|LLP|TRUSTEE|TRUST\b|BANK|N\.A|"
    r"ASSOCIATION|HOLDINGS|GROUP|PARTNERS|CHURCH|MINISTR|FOUNDATION|ESTATE OF|"
    r"ENTERPRISE|PROPERTIES|HOMES\b|CONSTRUCTION|SERVICES|SOLUTIONS|LANDSCAPING|"
    r"GRADING|LOGISTICS|SYSTEMS|CORPORATION|HYDROSEEDING)\b",
    re.I,
)


def parse_hidden(page_html: str) -> dict:
    out = {}
    for m in re.finditer(r'<input\s+([^>]*type="hidden"[^>]*)/?>', page_html, re.I):
        attrs = m.group(1)
        name_m = re.search(r'name="([^"]+)"', attrs)
        val_m = re.search(r'value="([^"]*)"', attrs)
        if name_m:
            out[name_m.group(1)] = html.unescape(val_m.group(1)) if val_m else ""
    return out


async def rod_search_surname(client: httpx.AsyncClient, surname_or_firm: str) -> list[dict] | None:
    """Run one real Quick Name (Index Type=CRP, Date Descending, All Matches) search
    against the live Buncombe ROD and return parsed instrument rows, or None on failure."""
    try:
        r1 = await client.get(ROD_LOGIN, timeout=30)
        hidden = parse_hidden(r1.text)
        if "ctl00_cphMain_tcMain_ClientState" not in hidden or not hidden.get("__SCROLLPOSITIONX", "0"):
            pass  # best-effort; fields default to "0" via dict.get below anyway
        form = dict(hidden)
        form.update({
            "ctl00$ddlCountySelect": "",
            f"{ROD_FORM}txtFirmSurname": surname_or_firm,
            f"{ROD_FORM}ddlWildcardLast": "0",       # Begins With
            f"{ROD_FORM}txtGivenName": "",
            f"{ROD_FORM}ddlWildcardFirst": "0",
            f"{ROD_FORM}ddlSide": "-1",               # Both Sides
            f"{ROD_FORM}ddlType": "-1",                # Any (human/nonhuman)
            f"{ROD_FORM}ddlIndexType": "CRP",          # Consolidated Real Property
            f"{ROD_FORM}txtFiledFrom": "From",         # literal watermark text, NOT ""
            f"{ROD_FORM}txtFiledThru": "Thru",
            f"{ROD_FORM}ddlSortDir": "Date Descending",
            f"{ROD_FORM}btnInstruments": "Search (All Matches)",
            "ctl00$txtJobReference": "",
        })
        r2 = await client.post(
            f"{ROD_BASE}{ROD_SEARCH_PATH}",
            data=form,
            headers={
                "Referer": str(r1.url),
                "Origin": ROD_BASE,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=45,
        )
        if "v2Error.aspx" in str(r2.url) or r2.status_code != 200:
            return None
        soup = BeautifulSoup(r2.text, "lxml")
        table = soup.find(
            "table",
            id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments",
        )
        if table is None:
            # 0 results is a real, valid outcome (rare surname) -- distinguish from a
            # genuine fetch failure by checking we at least got the Documents tab shell.
            if "ucInstrumentsGridV2" in r2.text or "No records" in r2.text:
                return []
            return None
        rows_out = []
        for tr in table.find_all("tr", class_="cottPagedGridViewRowStyle"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 6:
                continue
            rows_out.append({
                "date": tds[1].get_text(strip=True),
                "index": tds[2].get_text(strip=True),
                "type": tds[3].get_text(strip=True),
                "grantor_bold": [b.get_text(strip=True) for b in tds[4].find_all("b")],
                "grantee_bold": [b.get_text(strip=True) for b in tds[5].find_all("b")],
            })
        return rows_out
    except Exception:
        return None


def split_parties(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r";", raw or "") if p.strip()]


def parse_one_party(p: str) -> dict | None:
    p = p.strip()
    if not p:
        return None
    is_entity = bool(ENTITY_RE.search(p))
    if "," in p:
        surname, given = p.split(",", 1)
        surname, given = surname.strip(), given.strip()
    else:
        toks = p.split()
        if not toks:
            return None
        if len(toks) == 1:
            surname, given = toks[0], ""
        elif p.upper() == p:  # ALL CAPS GIS style: "SURNAME FIRST MIDDLE"
            surname, given = toks[0], " ".join(toks[1:])
        else:  # Title Case "First Last"
            surname, given = toks[-1], " ".join(toks[:-1])
    return {"raw": p, "surname": surname, "given": given, "is_entity": is_entity}


def primary_party(rec: dict) -> dict | None:
    for field in ("defendant", "owner_name"):
        raw = rec.get(field)
        if not raw:
            continue
        for p in split_parties(raw):
            parsed = parse_one_party(p)
            if parsed and not parsed["is_entity"]:
                return parsed
        # all parties were entities -- fall back to the first one anyway
        parties = split_parties(raw)
        if parties:
            return parse_one_party(parties[0])
    return None


def row_party_matches(bold_name: str, surname: str, given_first_token: str) -> bool:
    if "," not in bold_name:
        return bold_name.strip().upper() == surname.strip().upper()
    row_sur, row_given = bold_name.split(",", 1)
    if row_sur.strip().upper() != surname.strip().upper():
        return False
    if not given_first_token:
        return True
    row_first = row_given.strip().upper().split()[0] if row_given.strip() else ""
    if not row_first:
        return False
    if row_first == given_first_token:
        return True
    # Prefix-matching ("RICH" vs "RICHARD") is only meaningful once both sides are a
    # real name fragment, not a bare initial -- "J" vs "JAMES"/"JEFFREY"/"JOHN" would
    # all false-positive-match via naive .startswith() on a single character. Found
    # live via a messy merged defendant string ("WRIGHT, J RILEY WRIGHT, BARBARA")
    # whose given_first_token collapsed to just "J".
    if min(len(row_first), len(given_first_token)) < 3:
        return False
    return row_first.startswith(given_first_token) or given_first_token.startswith(row_first)


def classify_rod(rows: list[dict], party: dict) -> dict:
    surname = party["surname"]
    given_first = (party["given"].split()[0].upper() if party.get("given") else "")
    matched = []
    other_people = set()
    for row in rows:
        names = row["grantor_bold"] + row["grantee_bold"]
        row_is_match = False
        for n in names:
            if "," not in n:
                continue
            row_sur = n.split(",", 1)[0].strip().upper()
            if row_sur != surname.strip().upper():
                continue
            if row_party_matches(n, surname, given_first):
                row_is_match = True
            else:
                other_people.add(n.strip().upper())
        if row_is_match:
            matched.append(row)

    distress_hits = [
        r for r in matched
        if any(k in r["type"].upper() for k in DISTRESS_KEYWORDS)
    ]
    benign_hits = [
        r for r in matched
        if any(k in r["type"].upper() for k in BENIGN_RESOLUTION_KEYWORDS)
    ]

    if distress_hits:
        status = "active_corroboration"
    elif matched:
        status = "clean_resolved_or_neutral"
    else:
        status = "no_record_for_person"

    return {
        "status": status,
        "n_total_surname_rows": len(rows),
        "n_matched_person_rows": len(matched),
        "matched_rows": matched[:10],
        "distress_hits": distress_hits[:5],
        "benign_hits": benign_hits[:5],
        "n_other_same_surname_people": len(other_people),
        "collision_risk": len(other_people) >= 1,
        "collision_risk_strong": len(other_people) >= 2,
        "sample_other_people": sorted(other_people)[:8],
    }


def collect_candidates() -> list[dict]:
    rows = []
    for rec in web_artifact._iter_board_records(DOCS):
        if (rec.get("county") or "").strip() != "Buncombe":
            continue
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        if rec.get("listing_type") not in LISTING_TYPES:
            continue
        rows.append({
            "source": rec.get("source"),
            "listing_type": rec.get("listing_type"),
            "parcel_id": rec.get("parcel_id"),
            "street_address": rec.get("street_address"),
            "owner_name": rec.get("owner_name"),
            "defendant": rec.get("defendant"),
            "case_number": rec.get("case_number"),
            "board_value": rec.get("assessed_value") or rec.get("market_value") or rec.get("tax_value"),
            "first_seen": rec.get("first_seen"),
        })
    return rows


async def fetch_value(row: dict) -> None:
    pid = row.get("parcel_id")
    row["value_check"] = {"attempted": False}
    if not pid or not re.fullmatch(r"\d{15}", pid):
        row["value_check"] = {"attempted": False, "reason": "no_15digit_parcel_id"}
        return
    try:
        text = await get_text(
            f"https://tax.buncombenc.gov/Parcel/Details/{pid}", timeout=20, impersonate=True
        )
        om = OWNER_RE.search(text)
        vm = VALUE_RE.search(text)
        real_value = float(vm.group(1).replace(",", "")) if vm else None
        row["value_check"] = {
            "attempted": True,
            "fetch_ok": bool(om or vm),
            "real_owner": om.group(1).strip() if om else None,
            "real_value": real_value,
        }
        bv = row.get("board_value")
        if bv and real_value:
            row["value_check"]["abs_pct_error"] = round(abs(bv - real_value) / real_value * 100, 1)
            row["value_check"]["board_higher"] = bv > real_value
    except Exception as e:
        row["value_check"] = {"attempted": True, "fetch_ok": False, "error": str(e)[:200]}


_rod_cache: dict[str, list[dict] | None] = {}


async def fetch_rod(client: httpx.AsyncClient, row: dict) -> None:
    party = primary_party(row)
    if party is None:
        row["rod_check"] = {"attempted": False, "reason": "no_owner_or_defendant_name"}
        return
    if party["is_entity"]:
        row["rod_check"] = {"attempted": False, "reason": "entity_defendant_skipped", "party": party["raw"]}
        return
    key = party["surname"].strip().upper()
    if key not in _rod_cache:
        _rod_cache[key] = await rod_search_surname(client, party["surname"])
        await asyncio.sleep(0.8)
    rows = _rod_cache[key]
    if rows is None:
        row["rod_check"] = {"attempted": True, "fetch_ok": False, "party": party["raw"]}
        return
    classification = classify_rod(rows, party)
    row["rod_check"] = {"attempted": True, "fetch_ok": True, "party": party["raw"], **classification}


async def main():
    candidates = collect_candidates()
    print(f"Total Buncombe NC lis-pendens/foreclosure-class candidates on board: {len(candidates)}", file=sys.stderr)
    random.seed(20261002)
    sample = random.sample(candidates, min(N_SAMPLE, len(candidates)))
    print(f"Sampling {len(sample)}", file=sys.stderr)

    # value checks, bounded concurrency via the shared http_client
    val_sem = asyncio.Semaphore(5)

    async def bound_value(row):
        async with val_sem:
            await fetch_value(row)
            await asyncio.sleep(0.3)

    await asyncio.gather(*[bound_value(r) for r in sample])
    print("value checks done", file=sys.stderr)

    # ROD checks: sequential-ish (shared cache by surname, be polite to a county server)
    async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True, timeout=45) as client:
        for row in sample:
            await fetch_rod(client, row)
    print("ROD checks done", file=sys.stderr)

    OUT_PATH.write_text(json.dumps(sample, indent=2, default=str))
    print(f"Saved raw results to {OUT_PATH}", file=sys.stderr)

    # ---- summary stats ----
    n = len(sample)
    vchecked = [r for r in sample if r["value_check"].get("fetch_ok")]
    with_err = [r for r in vchecked if "abs_pct_error" in r["value_check"]]
    print(f"\n=== VALUE ACCURACY (N sampled={n}, N tax-site fetched OK={len(vchecked)}, N with board+real value pair={len(with_err)}) ===", file=sys.stderr)
    if with_err:
        errs = sorted(r["value_check"]["abs_pct_error"] for r in with_err)
        within10 = sum(1 for e in errs if e <= 10)
        within25 = sum(1 for e in errs if e <= 25)
        median = errs[len(errs) // 2]
        higher = sum(1 for r in with_err if r["value_check"]["board_higher"])
        print(f"  Within 10%: {within10}/{len(errs)} ({100*within10/len(errs):.1f}%)", file=sys.stderr)
        print(f"  Within 25%: {within25}/{len(errs)} ({100*within25/len(errs):.1f}%)", file=sys.stderr)
        print(f"  Median abs error: {median:.1f}%   Max: {errs[-1]:.1f}%", file=sys.stderr)
        print(f"  Board OVERSTATES value in {higher}/{len(errs)} ({100*higher/len(errs):.1f}%) of mismatches", file=sys.stderr)

    rchecked = [r for r in sample if r["rod_check"].get("fetch_ok")]
    statuses = Counter(r["rod_check"].get("status") for r in rchecked)
    collisions = sum(1 for r in rchecked if r["rod_check"].get("collision_risk"))
    collisions_strong = sum(1 for r in rchecked if r["rod_check"].get("collision_risk_strong"))
    print(f"\n=== ROD CORROBORATION (N sampled={n}, N ROD-searchable (human party, fetch OK)={len(rchecked)}) ===", file=sys.stderr)
    for status, cnt in statuses.most_common():
        print(f"  {status}: {cnt}/{len(rchecked)} ({100*cnt/max(len(rchecked),1):.1f}%)", file=sys.stderr)
    print(f"  Same-surname collision risk (>=1 other person in ROD results): {collisions}/{len(rchecked)} ({100*collisions/max(len(rchecked),1):.1f}%)", file=sys.stderr)
    print(f"  Strong collision risk (>=2 other people): {collisions_strong}/{len(rchecked)} ({100*collisions_strong/max(len(rchecked),1):.1f}%)", file=sys.stderr)

    skipped_entity = sum(1 for r in sample if r["rod_check"].get("reason") == "entity_defendant_skipped")
    skipped_noname = sum(1 for r in sample if r["rod_check"].get("reason") == "no_owner_or_defendant_name")
    skipped_parcel = sum(1 for r in sample if r["value_check"].get("reason") == "no_15digit_parcel_id")
    print(f"\n  (skipped from ROD: {skipped_entity} entity defendants, {skipped_noname} no name at all)", file=sys.stderr)
    print(f"  (skipped from value check: {skipped_parcel} no usable 15-digit parcel_id)", file=sys.stderr)
    print("\nDONE", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
