"""FREE derivation flags — pure computation over data already on the board.

Five motivated-seller signals that cost nothing to derive:

1. free_and_clear — no mortgage recordings in ROD history. A property with
   zero open mortgages is owned outright, making it a prime wholesale /
   subject-to target (no lender payoff to negotiate, clean title transfer).

2. unreleased_mortgage — the inverse of free_and_clear: ROD history shows at
   least one mortgage/DOT recording with no matching satisfaction
   (open_mortgages_est >= 1). A genuine lender-payoff-required signal, the
   mirror image of (1), and just as free to compute from the same ROD data.

3. tired_landlord — absentee owner (mailing address different from property
   address) who has owned the property for 10+ years. Long-tenure absentee
   owners are the classic "tired landlord" motivated-seller profile.

4. divorce_flag — NC eCourts FAM case filings already on the board via
   the nc_ecourts_divorce scraper. This flag also cross-references any
   listing whose owner name matches a party in a divorce filing.

5. subordinate_lien_foreclosure — the foreclosing party is suing on a 2nd
   mortgage / HELOC, not the 1st. Rebuilds RodDoc objects from the
   rod.instruments list classify_rod_docs() already collected (no new
   network call), runs them through rod.priority.compute_priority() to get
   the lien stack in recording order, and confirms the foreclosing party's
   name (enrichment_title_risk._party_text) matches the grantee (lender) on
   the most-recently-recorded active mortgage before trusting that it is the
   one in foreclosure. If that mortgage sits behind an older, still-active
   mortgage, the foreclosure is on a SUBORDINATE lien — an early-distress
   signal (the 1st-mortgage lender hasn't moved yet) genuinely missed by
   title_risk's party-name-only classifier, which never looks at the deed
   stack.

All five are read-only computations over existing raw[] fields. No I/O.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import structlog

from .enrichment_title_risk import _party_text
from .models import Listing
from .name_normalize import first_last_parts
from .rod.models import RodDoc
from .rod.priority import compute_priority

log = structlog.get_logger()


# ROD enrichers whose owner-name parser read every name surname-first until
# 2026-09-18. For a Title Case FIRST-LAST owner ('Joshua D Smith') they searched
# last=JOSHUA, first=D, so the instruments they "found" belonged to somebody else
# and "no mortgage among them" says nothing about this owner. A stamp fetched
# before the fix, on such a name, must not produce a free_and_clear claim; a
# re-fetch with the fixed parser clears the condition on its own (new fetched_at).
_ROD_SURNAME_FIRST_SOURCES = {"spartanburg_rod_render", "aumentum_rod", "cchs_rod", "generic_rod"}
_ROD_PARSER_FIX_DATE = "2026-09-18"


def _rod_name_order_suspect(li: Listing, rod: dict) -> bool:
    if rod.get("source") not in _ROD_SURNAME_FIRST_SOURCES:
        return False
    if str(rod.get("fetched_at") or "")[:10] >= _ROD_PARSER_FIX_DATE:
        return False  # fetched with the fixed parser
    return first_last_parts(li.owner_name) is not None


def _free_and_clear(li: Listing) -> Optional[dict]:
    """No open mortgages in ROD history means the property is owned outright."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    rod = raw.get("rod")
    if not isinstance(rod, dict):
        return None
    if _rod_name_order_suspect(li, rod):
        return None
    # Need ROD data to make the claim — absence of ROD is NOT absence of mortgage
    if not rod.get("instrument_count"):
        return None
    open_mtg = rod.get("open_mortgages_est", 0)
    has_mtg = rod.get("has_mortgage", False)
    if open_mtg == 0 and not has_mtg:
        return {
            "flag": True,
            "reason": "no_mortgage_recordings",
            "instrument_count": rod.get("instrument_count"),
            "source": rod.get("source"),
        }
    return None


def _unreleased_mortgage(li: Listing) -> Optional[dict]:
    """At least one open (unsatisfied) mortgage/DOT recorded — the inverse of
    free_and_clear. Mirrors _free_and_clear's exact pattern/guards."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    rod = raw.get("rod")
    if not isinstance(rod, dict):
        return None
    if _rod_name_order_suspect(li, rod):
        return None
    # Need ROD data to make the claim — absence of ROD is NOT evidence of a mortgage
    if not rod.get("instrument_count"):
        return None
    open_mtg = rod.get("open_mortgages_est", 0)
    has_mtg = rod.get("has_mortgage", False)
    if has_mtg and open_mtg >= 1:
        return {
            "flag": True,
            "open_mortgages_est": open_mtg,
            "mortgage_count": rod.get("mortgage_count"),
            "satisfaction_count": rod.get("satisfaction_count"),
            "instrument_count": rod.get("instrument_count"),
            "source": rod.get("source"),
        }
    return None


def _tired_landlord(li: Listing) -> Optional[dict]:
    """Absentee owner (mailing != property) with 10+ years ownership."""
    raw = li.raw if isinstance(li.raw, dict) else {}

    # Check absentee status — owner_mailing must differ from property address
    mailing = (raw.get("owner_mailing") or {}).get("address", "") if isinstance(raw.get("owner_mailing"), dict) else raw.get("owner_mailing", "")
    prop_addr = (raw.get("property_address") or li.street_address or "").strip().lower()
    if not mailing or not prop_addr:
        return None
    mailing_lower = mailing.strip().lower() if isinstance(mailing, str) else ""
    if not mailing_lower:
        return None

    # Absentee = mailing address does not contain the property street
    # (simple check: different first 10 chars of normalized address)
    is_absentee = False
    # Check owner_occupied flag if present
    if isinstance(raw.get("gis_attrs"), dict):
        if raw["gis_attrs"].get("owner_occupied") is False:
            is_absentee = True
    if not is_absentee:
        # Heuristic: if mailing city/state differs from property city/state
        prop_city = (raw.get("property_city") or li.city or "").strip().lower()
        prop_state = (raw.get("property_state") or li.state or "").strip().lower()
        # Check if mailing is out-of-state or different city
        if prop_state and prop_state not in mailing_lower:
            is_absentee = True
        elif prop_city and prop_city not in mailing_lower and len(mailing_lower) > 5:
            is_absentee = True

    if not is_absentee:
        return None

    # Check ownership tenure — need 10+ years
    # Try ROD earliest instrument date, or last_sale_date, or gis sale_date
    tenure_years = None
    rod = raw.get("rod") or {}
    instruments = rod.get("instruments") if isinstance(rod, dict) else None
    if instruments:
        # Earliest instrument date as a proxy for ownership start
        dates = [i.get("date") for i in instruments if i.get("date")]
        if dates:
            dates.sort(key=lambda d: str(d))
            from datetime import date
            try:
                earliest = date.fromisoformat(dates[0][:10])
                tenure_years = (date.today() - earliest).days / 365.25
            except Exception:
                pass

    # Fallback: last_sale_date from recorded sales
    if tenure_years is None:
        sales = raw.get("recorded_sales") or []
        if sales and isinstance(sales, list):
            sale_dates = [s.get("date") for s in sales if isinstance(s, dict) and s.get("date")]
            if sale_dates:
                sale_dates.sort(key=lambda d: str(d))
                from datetime import date
                try:
                    earliest = date.fromisoformat(sale_dates[0][:10])
                    tenure_years = (date.today() - earliest).days / 365.25
                except Exception:
                    pass

    if tenure_years is None or tenure_years < 10:
        return None

    return {
        "flag": True,
        "tenure_years": round(tenure_years, 1),
        "absentee": True,
        "mailing": mailing[:80] if isinstance(mailing, str) else None,
    }


def _divorce_flag(li: Listing) -> Optional[dict]:
    """Flag listings from the divorce scraper or with divorce case cross-reference."""
    raw = li.raw if isinstance(li.raw, dict) else {}

    # Direct: listing came from the divorce scraper
    src = (li.source or "").lower()
    if "divorce" in src or "fam" in src:
        return {
            "flag": True,
            "source": "ecourts_divorce",
            "case_id": raw.get("case_id"),
        }

    # Check listing_type
    lt = str(li.listing_type) if li.listing_type else ""
    if "DIVORCE" in lt.upper():
        return {
            "flag": True,
            "source": "listing_type",
            "case_id": raw.get("case_id"),
        }

    return None


# Generic entity words stripped before matching a plaintiff's name against a
# recorded DOT grantee (lender). Both strings are messy free text ("Wells
# Fargo Bank, N.A." vs "WELLS FARGO BANK NA"); comparing on the remaining
# distinctive tokens avoids both false negatives from formatting noise and
# false positives from matching on "bank"/"trust"/"na" alone.
_GENERIC_ENTITY_WORDS = frozenset({
    "bank", "na", "n", "a", "mortgage", "llc", "inc", "incorporated", "corp",
    "corporation", "company", "co", "trust", "association", "assn", "assoc",
    "loan", "loans", "servicing", "national", "federal", "credit", "union",
    "the", "and", "of", "for", "fund", "funding", "capital", "financial",
    "lp", "ltd", "fsb", "systems", "system", "services", "service",
})


def _sig_tokens(s: str) -> set[str]:
    s = re.sub(r"[^a-z0-9\s]", " ", (s or "").lower())
    return {t for t in s.split() if len(t) > 2 and t not in _GENERIC_ENTITY_WORDS}


def _names_match(a: str, b: str) -> bool:
    """True when two entity strings share a distinctive token (e.g. a brand
    name). Deliberately loose — this only gates a flag that is also behind
    the structural lien-position check, not a standalone identity claim."""
    ta, tb = _sig_tokens(a), _sig_tokens(b)
    return bool(ta and tb and (ta & tb))


def _instruments_to_roddocs(li: Listing, rod: dict) -> list[RodDoc]:
    """Adapt the already-collected rod['instruments'] list (classify.py's
    reduced per-instrument dicts: date/type/grantor/grantee/book/page) back
    into RodDoc objects so rod.priority.compute_priority() can run over data
    that is already on the board — no new network call."""
    instruments = rod.get("instruments")
    if not isinstance(instruments, list):
        return []
    state = (li.state or "").upper() or "NC"
    county = li.county or ""
    docs: list[RodDoc] = []
    for inst in instruments:
        if not isinstance(inst, dict):
            continue
        rd = None
        d = inst.get("date")
        if d:
            try:
                rd = datetime.fromisoformat(str(d)[:10])
            except (ValueError, TypeError):
                rd = None
        docs.append(RodDoc(
            county=county, state=state,
            doc_type=inst.get("type") or "",
            recorded_date=rd,
            book=inst.get("book"), page=inst.get("page"),
            grantor=inst.get("grantor"), grantee=inst.get("grantee"),
        ))
    return docs


def _subordinate_lien_foreclosure(li: Listing) -> Optional[dict]:
    """Foreclosure running on a 2nd mortgage / HELOC, not the 1st.

    compute_priority(), given no known foreclosing book/page, infers the
    foreclosing instrument as the most-recently-recorded ACTIVE mortgage.
    We only trust that inference — and only flag — when the foreclosing
    party's own name actually matches the grantee (lender) recorded on that
    instrument; otherwise we'd be flagging on a guess compounded on a guess.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    rod = raw.get("rod")
    if not isinstance(rod, dict):
        return None
    if _rod_name_order_suspect(li, rod):
        return None
    docs = _instruments_to_roddocs(li, rod)
    if len(docs) < 2:
        return None  # need at least two instruments for a senior/junior stack

    party = _party_text(li)
    if not party:
        return None

    pos = compute_priority(docs, state=(li.state or "NC").upper())
    if not pos.foreclosing_position or pos.foreclosing_position <= 1:
        return None  # 1st position (or unknown) — not a subordinate-lien case
    if not pos.foreclosing_doc:
        return None
    grantee = (pos.foreclosing_doc.get("grantee") or "").strip()
    if not grantee or not _names_match(party, grantee):
        return None  # inferred foreclosing instrument doesn't match the plaintiff

    return {
        "flag": True,
        "foreclosing_position": pos.foreclosing_position,
        "senior_lien_count": len(pos.senior_liens),
        "total_senior_amount": pos.total_senior_amount,
        "foreclosing_grantee": grantee[:120],
        "matched_party": party[:120],
    }


def enrich_derivation_flags(listings: list[Listing]) -> dict:
    """Attach raw['derivation_flags'] = {free_and_clear?, tired_landlord?, divorce?}.

    Pure compute over ROD + GIS + court data already on the board.
    """
    n_fcl = n_um = n_tl = n_div = n_sub = n_any = n_dropped = 0
    for li in listings:
        out: dict = {}
        fcl = _free_and_clear(li)
        if fcl:
            out["free_and_clear"] = fcl
            n_fcl += 1
        um = _unreleased_mortgage(li)
        if um:
            out["unreleased_mortgage"] = um
            n_um += 1
        tl = _tired_landlord(li)
        if tl:
            out["tired_landlord"] = tl
            n_tl += 1
        div = _divorce_flag(li)
        if div:
            out["divorce"] = div
            n_div += 1
        sub = _subordinate_lien_foreclosure(li)
        if sub:
            out["subordinate_lien_foreclosure"] = sub
            n_sub += 1
        if out:
            raw = li.raw if isinstance(li.raw, dict) else {}
            raw["derivation_flags"] = out
            li.raw = raw
            n_any += 1
        elif isinstance(li.raw, dict) and "derivation_flags" in li.raw:
            # Nothing applies now, so an old block is stale: it was written when
            # the inputs said otherwise (a ROD re-fetch later showed open
            # mortgages, a divorce stamp was cleared, ...). Before 2026-09-18
            # these were never removed -- 116 leads sat flagged free_and_clear
            # with has_mortgage=True and up to 77 instruments on file.
            del li.raw["derivation_flags"]
            n_dropped += 1

    log.info("derivation_flags.done", free_and_clear=n_fcl, unreleased_mortgage=n_um,
             tired_landlord=n_tl, divorce=n_div, subordinate_lien_foreclosure=n_sub,
             any=n_any, dropped_stale=n_dropped, total=len(listings))
    return {
        "free_and_clear": n_fcl,
        "unreleased_mortgage": n_um,
        "tired_landlord": n_tl,
        "divorce": n_div,
        "subordinate_lien_foreclosure": n_sub,
        "rows": n_any,
        "dropped_stale": n_dropped,
    }
