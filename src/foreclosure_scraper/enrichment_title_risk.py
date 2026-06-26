"""Foreclosing-party title-risk classifier — pure compute, zero new scrape.

The single most expensive mistake a foreclosure buyer makes is bidding at a
JUNIOR-lien sale (HOA dues, a 2nd mortgage, a credit-union signature loan, a
municipal code-fine) believing they are buying the property free and clear. At a
junior sale the senior 1st-mortgage SURVIVES — the winning bidder takes title
subject to that bank's deed of trust, which can then foreclose and wipe them out.
The reverse is the safe case: when the foreclosing party IS the senior 1st-
mortgage holder (a major bank/servicer or its securitization trustee), the sale
generally extinguishes everything junior and the buyer gets clean-ish title.

This enricher inspects the party text we already collect (li.plaintiff /
li.trustee, falling back to raw['plaintiff'], raw['creditors'], raw['attorney'],
raw['firm_name'], raw['court_record']) and classifies the FORECLOSING PARTY into:

  - senior_lien_foreclosure   -> surviving_senior_debt = False        (bank/servicer)
  - junior_lien_foreclosure   -> surviving_senior_debt_risk = True    (HOA/CU/muni/individual)
  - unknown                   -> nothing bankable; left for a human    (conservative default)

Design notes / house style:
  * Pure-Python, no network, no I/O. Mirrors enrichment_derived_signals.py.
  * SENIOR is checked FIRST. Real data has "U.S. Bank Trust National Association"
    (a securitization TRUSTEE = senior) sitting right next to "Fernbrook III
    Homeowners Association" (junior). A naive "association" match would mis-flag
    the bank, so the bank/servicer table wins ties and the HOA pattern requires a
    qualifier ("homeowners"/"property owners"/"community"/"condo"/"POA"), never a
    bare "association".
  * Conservative: when the party text is missing or matches nothing, we emit
    'unknown' rather than guess. A false "clear title" flag is far costlier than
    an honest "unknown".
  * Per spec, MUNICIPAL tax/code-fine foreclosures are routed to junior-risk so
    the operator manually verifies priority (NC/SC tax sales are usually super-
    priority, but a city CODE-FINE lien is not, and the two are easy to confuse
    in the party string). Erring toward "verify the senior debt" is the safe call.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# SENIOR — major 1st-mortgage servicers / banks / GSEs / govt guarantors and
# the securitization trustees that foreclose on their behalf. A sale by ANY of
# these is a senior-lien foreclosure: buying it generally clears junior liens.
#
# Patterns are matched against a lowercased, entity-normalized party string
# (ampersands, punctuation and "national association"/"n.a." noise stripped).
# Word boundaries keep "pnc" from matching inside other tokens; multi-word
# brands are matched as phrases.
# ---------------------------------------------------------------------------
_SENIOR_PATTERNS: tuple[tuple[str, str], ...] = (
    # --- big-name servicers seen in live data ---
    (r"pennymac", "PennyMac"),
    (r"wells\s*fargo", "Wells Fargo"),
    (r"\b(?:jpmorgan|jp\s*morgan|chase)\b", "JPMorgan Chase"),
    (r"lakeview\s+loan", "Lakeview Loan Servicing"),
    (r"freedom\s+mortgage", "Freedom Mortgage"),
    (r"\b(?:nationstar|mr\.?\s*cooper)\b", "Nationstar / Mr. Cooper"),
    (r"carrington\s+mortgage", "Carrington Mortgage Services"),
    (r"\brocket\s+mortgage\b", "Rocket Mortgage"),
    (r"\bquicken\s+loans\b", "Quicken Loans / Rocket"),
    (r"\bu\.?\s*s\.?\s+bank\b", "U.S. Bank"),
    (r"\bbank\s+of\s+america\b", "Bank of America"),
    (r"\btruist\b", "Truist"),
    (r"\bbb&?\s*t\b", "BB&T / Truist"),
    (r"\bsuntrust\b", "SunTrust / Truist"),
    (r"specialized\s+loan\s+servicing|\bsls\b", "Specialized Loan Servicing"),
    (r"\bshellpoint\b", "Shellpoint"),
    (r"newrez", "NewRez / Shellpoint"),
    (r"select\s+portfolio|\bsps\b", "Select Portfolio Servicing"),
    (r"\bnewrez\b", "NewRez"),
    # --- GSEs / govt guarantors ---
    (r"\bfannie\s*mae\b|federal\s+national\s+mortgage", "Fannie Mae"),
    (r"\bfreddie\s*mac\b|federal\s+home\s+loan\s+mortgage", "Freddie Mac"),
    (r"\bginnie\s*mae\b|government\s+national\s+mortgage", "Ginnie Mae"),
    (r"department\s+of\s+housing|\bhud\b|\bfha\b", "HUD / FHA"),
    (r"veterans?\s+affairs|\bv\.?a\.?\s+loan\b|secretary\s+of\s+veterans", "Dept. of Veterans Affairs"),
    (r"\bsmall\s+business\s+administration\b|\bsba\b", "SBA"),
    (r"\bus(?:da)?\s+rural|rural\s+(?:housing|development)", "USDA Rural Development"),
    # --- securitization trustees (foreclose FOR a senior MBS pool) ---
    (r"deutsche\s+bank", "Deutsche Bank (trustee)"),
    (r"wilmington\s+(?:savings|trust)", "Wilmington Savings Fund Society (trustee)"),
    (r"\bbank\s+of\s+new\s+york|\bbny\s+mellon\b", "BNY Mellon (trustee)"),
    (r"\bhsbc\b", "HSBC (trustee)"),
    (r"\bcitibank\b|\bcitigroup\b|\bcitimortgage\b", "Citi"),
    (r"\bpnc\s+bank\b", "PNC Bank"),
    (r"\bregions\s+bank\b", "Regions Bank"),
    (r"fifth\s+third", "Fifth Third Bank"),
    (r"\bmidfirst\b", "MidFirst Bank"),
    (r"\bameri\s*home\b", "AmeriHome Mortgage"),
    (r"\bnewamerican\b|new\s+american\s+funding", "New American Funding"),
    (r"village\s+capital", "Village Capital & Investment"),
    (r"planet\s+home\s+lending", "Planet Home Lending"),
    (r"\bselene\s+finance\b", "Selene Finance"),
    (r"\bguild\s+mortgage\b", "Guild Mortgage"),
    (r"nations?\s+direct\s+mortgage", "Nations Direct Mortgage"),
    (r"nations?\s+lending", "Nations Lending"),
    (r"atlantic\s+bay\s+mortgage", "Atlantic Bay Mortgage"),
    (r"\b21st\s+mortgage\b", "21st Mortgage"),
    (r"vanderbilt\s+mortgage", "Vanderbilt Mortgage"),
    (r"\bdata\s+mortgage\b", "Data Mortgage"),
    (r"\bamerisave\b", "AmeriSave"),
    (r"\bloandepot\b|loan\s*depot", "loanDepot"),
    (r"\bcaliber\s+home\s+loans\b", "Caliber Home Loans"),
    (r"\bditech\b|green\s*tree\s+servicing", "Ditech / GreenTree"),
    (r"\bocwen\b|\bphh\s+mortgage\b", "Ocwen / PHH"),
    (r"\bflagstar\b", "Flagstar Bank"),
    (r"\bsouthstate\b|south\s+state\s+bank", "SouthState Bank"),
    (r"state\s+housing\s+finance|housing\s+finance\s+(?:and\s+development\s+)?authority",
     "State Housing Finance Authority"),
    # --- ag / specialty 1st-lien lenders ---
    (r"farm\s+credit\b|\bag\s*south\b|\bagfirst\b", "Farm Credit System"),
    (r"\btd\s+bank\b", "TD Bank"),
    (r"citizens\s+bank", "Citizens Bank"),
    (r"first\s*citizens\s+bank", "First Citizens Bank"),
    (r"\bnorthpointe\s+bank\b", "Northpointe Bank"),
    (r"first\s+national\s+bank", "First National Bank"),
    (r"\brbc\b", "RBC Bank"),
    (r"\bfirstbank\b", "FirstBank"),
    (r"united\s+wholesale\s+mortgage", "United Wholesale Mortgage"),
    (r"ruoff\s+mortgage", "Ruoff Mortgage"),
    (r"plaza\s+home\s+mortgage", "Plaza Home Mortgage"),
    (r"primelending", "PrimeLending"),
    (r"countryplace\s+mortgage", "CountryPlace Mortgage"),
)

# ---------------------------------------------------------------------------
# JUNIOR — parties whose lien is BEHIND a senior 1st mortgage. Foreclosing on
# any of these does NOT clear the bank's deed of trust: it likely SURVIVES the
# sale (a bidding trap). HOA/POA/condo, credit unions, municipal tax/code-fine
# bodies, and private individuals.
#
# NOTE: the HOA pattern requires a HOA-specific qualifier so it never swallows a
# bank trustee that happens to carry "national association" in its name.
# ---------------------------------------------------------------------------
_JUNIOR_PATTERNS: tuple[tuple[str, str], ...] = (
    # HOA / POA / condo / community / townhome associations
    (r"home\s*owners?\s+association|homeowners\b", "homeowners association"),
    (r"property\s+owners?\s+association|\bp\.?o\.?a\.?\b", "property owners association"),
    (r"community\s+association|\bh\.?o\.?a\.?\b", "community / HOA"),
    (r"condominium(?:\s+(?:owners?|association))?|condo\s+association", "condominium association"),
    (r"townh(?:ome|ouse)s?\s+(?:owners?\s+)?association", "townhome association"),
    (r"\bowners'?\s+association\b", "owners association"),
    # Credit unions (foreclose on signature / 2nd-lien loans junior to a bank 1st)
    (r"credit\s+union|\bf\.?c\.?u\.?\b|\bc\.?u\.?\b(?!\s*stom)", "credit union"),
    # Municipal tax / code-fine bodies (priority varies — verify the senior debt)
    (r"\bcity\s+of\b|\btown\s+of\b", "municipality"),
    (r"\bcounty\b(?!\s+(?:bank|trust|mortgage))", "county / municipal"),
    (r"tax\s+collector|delinquent\s+tax|tax\s+commissioner", "tax authority"),
    (r"code\s+enforcement|nuisance\s+abatement|\blien\s+for\s+(?:fines|penalt)",
     "code-fine / nuisance lien"),
)

# Generic corporate/legal tokens that, in isolation, do NOT indicate a senior
# bank. Used so a bare "...LLC" or a trustee LAW FIRM (which appears as
# li.trustee) isn't mistaken for the lender itself.
_LAW_FIRM_HINTS = re.compile(
    r"\b(?:law\s+(?:firm|office|group)|attorneys?\s+at\s+law|pllc|\bp\.?a\.?\b|"
    r"& (?:scott|corley|gregg|associates)|brock|rogers\s+townsend|bell\s+carrington)\b",
    re.I,
)

# An entity that is clearly a company (one of these legal suffixes) but matched
# NO senior pattern is still ambiguous — could be a private LLC junior lender or
# a small bank. We stay 'unknown' for these rather than guess either way.
_CORP_SUFFIX = re.compile(
    r"\b(?:llc|l\.l\.c\.|inc|incorporated|corp|corporation|company|co|lp|l\.p\.|"
    r"ltd|fsb|n\.a\.|na|bank|trust|mortgage|servicing|lending|loans?|financial|"
    r"finance|capital|fund|funding|federal)\b",
    re.I,
)

# Generic 1st-lien LENDER tokens. A string that wasn't matched by the named
# table but clearly contains one of these (e.g. "Firstbank", "Countybank",
# "TD Bank N.A.", "Northpointe Bank", "Ruoff Mortgage Company") is still a bank /
# mortgage lender foreclosing its own deed of trust = senior. Deliberately
# NARROW: 'bank'/'bancorp'/'savings bank'/'mortgage'/'home loans'/'farm credit'
# only — NOT 'financial'/'funding'/'capital'/'loan fund', which are commonly
# private hard-money / junior lenders we want to leave UNKNOWN. Matched with a
# lower-confidence label so the operator knows it's a token hit, not a brand.
_GENERIC_LENDER = re.compile(
    r"\b(?:bank|bancorp|bancshares)\b|bank\b|savings\s+(?:and\s+loan|bank)|"
    r"\bs&l\b|\bmortgage\b|home\s+loans?\b|farm\s+credit\b|"
    r"\b(?:federal\s+)?savings\b",
    re.I,
)

# Non-person institutional tokens that must NOT be treated as a "bare personal
# name" even though they lack a corporate suffix (court, agency, county dept).
_NOT_A_PERSON = re.compile(
    r"\b(?:court|bankruptcy|trustee|county|state|department|dept|agency|"
    r"authority|commission|district|board|bureau|office|service|services|"
    r"system|systems|fund|trust|estate|properties|company|corp)\b",
    re.I,
)

# A bare personal name (FIRST LAST / LAST, FIRST), no corporate suffix at all,
# is a private individual foreclosing a junior/seller-financed note -> junior.
_PERSON_LIKE = re.compile(r"^[a-z][a-z.\-' ]+$", re.I)

_COMPILED_SENIOR = tuple((re.compile(p, re.I), label) for p, label in _SENIOR_PATTERNS)
_COMPILED_JUNIOR = tuple((re.compile(p, re.I), label) for p, label in _JUNIOR_PATTERNS)


def _party_text(li: Listing) -> str:
    """Best available foreclosing-party string.

    Prefers the structured plaintiff (the foreclosing creditor); the trustee is
    usually the LAW FIRM running the sale, not the lien holder, so it's a weak
    fallback. Also reaches into raw for creditor / attorney / court-record text
    the field columns may not have surfaced.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    candidates = [
        li.plaintiff,
        raw.get("plaintiff"),
        raw.get("creditors"),
        raw.get("creditor"),
        (raw.get("court_record") or {}).get("creditors") if isinstance(raw.get("court_record"), dict) else None,
        li.trustee,                 # weak — often the firm; checked last
        raw.get("trustee"),
        raw.get("attorney"),
        raw.get("firm_name"),
        raw.get("foreclosing_party"),
    ]
    for c in candidates:
        if c and str(c).strip():
            return str(c)
    return ""


def _normalize_party(s: str) -> str:
    """Lowercase + strip HTML-entity / punctuation noise for matching.

    Real data carries '&amp;', stray commas, and ', plaintiff, et al' tails.
    Collapse those so patterns match the brand, not the formatting.
    """
    s = s.lower()
    s = s.replace("&amp;", " and ").replace("&", " and ")
    s = re.sub(r",?\s*plaintiff,?\s*et al\.?", " ", s)
    s = re.sub(r"\bnot\s+in\s+its\s+individual\b.*", " ", s)  # trustee boilerplate tail
    s = re.sub(r"[^\w\s.&']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _classify(party: str) -> Optional[dict]:
    """Classify a raw foreclosing-party string. Returns the title_risk dict or
    None when there is no usable party text at all."""
    if not party or not party.strip():
        return None
    norm = _normalize_party(party)
    if not norm:
        return None

    # 1) SENIOR wins ties (a bank trustee carrying "association" must not be
    #    swept up by the junior HOA pattern below).
    for rx, label in _COMPILED_SENIOR:
        if rx.search(norm):
            return {
                "kind": "senior_lien_foreclosure",
                "surviving_senior_debt": False,
                "matched": label,
                "party": party[:200],
            }

    # 2) JUNIOR — HOA/CU/municipal/code-fine.
    for rx, label in _COMPILED_JUNIOR:
        if rx.search(norm):
            return {
                "kind": "junior_lien_foreclosure",
                "surviving_senior_debt_risk": True,
                "matched": label,
                "party": party[:200],
            }

    # 3) Generic 1st-lien lender token (a "...bank" / "...mortgage" the named
    #    table didn't list). Still a senior deed-of-trust holder = clears junior
    #    liens. Lower-confidence label so the operator knows it's a token hit.
    #    Guard out the junior-ish institutions already excluded above (credit
    #    unions / HOAs were handled in step 2) and law-firm-only strings.
    if _GENERIC_LENDER.search(norm) and not _LAW_FIRM_HINTS.search(norm):
        return {
            "kind": "senior_lien_foreclosure",
            "surviving_senior_debt": False,
            "matched": "generic bank / mortgage lender",
            "party": party[:200],
        }

    # 4) Bare personal name, no corporate suffix -> private individual junior /
    #    seller-financed note holder. The senior bank 1st likely survives.
    #    Excludes courts/agencies/depts (institutional, not a person) and
    #    law-firm strings.
    if _PERSON_LIKE.match(norm) and not _CORP_SUFFIX.search(norm) \
            and not _NOT_A_PERSON.search(norm) \
            and not _LAW_FIRM_HINTS.search(norm) and len(norm.split()) <= 4:
        return {
            "kind": "junior_lien_foreclosure",
            "surviving_senior_debt_risk": True,
            "matched": "private individual",
            "party": party[:200],
        }

    # 5) Anything else (unrecognized LLC, title co, contractor lien, MERS, a
    #    law-firm-only string) is left UNKNOWN — conservative by design.
    return {"kind": "unknown", "party": party[:200]}


def enrich_title_risk(listings: list[Listing]) -> dict:
    """Attach raw['title_risk'] classifying the foreclosing party's lien seniority.

    Pure compute over party text already on each listing (no network, no I/O).

      raw['title_risk'] = {
          kind: 'senior_lien_foreclosure',
          surviving_senior_debt: False,           # clears junior liens
          matched: 'PennyMac', party: '...'
      }
      raw['title_risk'] = {
          kind: 'junior_lien_foreclosure',
          surviving_senior_debt_risk: True,        # senior bank likely SURVIVES — trap
          matched: 'homeowners association', party: '...'
      }
      raw['title_risk'] = {kind: 'unknown', party: '...'}   # too ambiguous to bank

    Returns a coverage histogram for the run report.
    """
    stats = {"senior": 0, "junior_risk": 0, "unknown": 0, "no_party": 0,
             "rows": len(listings)}
    for li in listings:
        party = _party_text(li)
        result = _classify(party)
        if result is None:
            stats["no_party"] += 1
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        raw["title_risk"] = result
        li.raw = raw
        kind = result["kind"]
        if kind == "senior_lien_foreclosure":
            stats["senior"] += 1
        elif kind == "junior_lien_foreclosure":
            stats["junior_risk"] += 1
        else:
            stats["unknown"] += 1
    log.info("title_risk.done", **stats)
    return stats
