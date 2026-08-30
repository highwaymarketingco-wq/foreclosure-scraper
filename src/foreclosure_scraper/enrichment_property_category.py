"""Property categorization — classifies every listing into exactly one
primary distress category so the operator can filter and prioritize.

Categories (one per listing, priority-ordered):

  1. foreclosure        — formal foreclosure proceedings underway.
                          Includes: foreclosure_sale, sheriff_sale,
                          hoa_sale, LIS_PENDENS filings, court sale_status
                          (sale_noticed/sold_unconfirmed/confirmed), ROD
                          foreclosure documents, and any case with a
                          foreclosure plaintiff.

  2. preforeclosure     — early-stage distress BEFORE formal foreclosure.
                          Includes: distressed MLS (withdrawn/expired/stale),
                          divorce_notice, code_enforcement (pre-foreclosure
                          pressure), elderly_disabled (downsizing pressure),
                          estate_lead (heir situation not yet in probate),
                          and mortgage default signals without a court filing.

  3. tax_delinquency    — delinquent property taxes, tax liens, tax sales.
                          Includes: tax_sale, tax_lien, delinquent tax
                          records, upset bids, tax judgment.

  4. distressed_property — motivated-seller / as-is / cash-only listings
                          and properties with distress signals that don't
                          fit a specific category above. The catch-all.
                          Includes: DISTRESSED, probate_notice (estate sale
                          pressure), bankruptcy, REO (bank-owned, already
                          foreclosed), tired_landlord, free_and_clear.

The category is stored in raw['property_category'] = {
    "category": str,       # foreclosure | preforeclosure | tax_delinquency | distressed_property
    "subcategory": str,    # more specific type (e.g. "hoa_foreclosure", "tax_sale", "divorce")
    "signals": list[str],  # all signals that contributed
    "confidence": str,     # high | medium | low
}

Pure computation over existing board data. No I/O, no network calls.
"""
from __future__ import annotations

import structlog
from typing import Optional

from .models import Listing, ListingType

log = structlog.get_logger()


def _categorize(li: Listing) -> Optional[dict]:
    """Determine the primary property category for a single listing."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    signals: list[str] = []
    lt = (li.listing_type.value if li.listing_type else "") if hasattr(li.listing_type, "value") else str(li.listing_type or "")
    src = (li.source or "").lower()

    # ---- 1. FORECLOSURE (highest priority — formal proceedings) --------
    foreclosure_signals: list[str] = []

    # ListingType directly says foreclosure
    if lt in ("foreclosure_sale", "sheriff_sale", "hoa_sale"):
        foreclosure_signals.append(f"listing_type:{lt}")
    elif lt == "lis_pendens":
        foreclosure_signals.append("lis_pendens")

    # Court sale status from case detail parser
    sale_status = raw.get("sale_status") or ((raw.get("court_detail") or {}).get("sale_status"))
    if sale_status in ("sale_noticed", "sold_unconfirmed", "confirmed", "judgment"):
        foreclosure_signals.append(f"sale_status:{sale_status}")

    # Court documents (from case detail parser)
    docs = raw.get("documents") or ((raw.get("court_detail") or {}).get("documents")) or []
    if isinstance(docs, list) and docs:
        foreclosure_doc_types = {
            "notice of sale", "judgment", "writ of execution",
            "order of confirmation", "master's deed", "report of sale",
            "case filed", "motion for default",
        }
        for d in docs:
            if isinstance(d, dict):
                dtype = (d.get("type") or "").lower()
                if dtype in foreclosure_doc_types:
                    foreclosure_signals.append(f"court_doc:{dtype}")

    # ROD foreclosure instruments
    rod = raw.get("rod") or {}
    if isinstance(rod, dict):
        adverse_types = rod.get("adverse_types") or []
        if isinstance(adverse_types, list):
            for at in adverse_types:
                if "FORECLOS" in str(at).upper():
                    foreclosure_signals.append(f"rod_foreclosure:{at}")

    # HOA foreclosure from ROD
    if isinstance(rod, dict) and rod.get("has_hoa_lien"):
        foreclosure_signals.append("hoa_lien")

    # Plaintiff is a foreclosure trustee / bank
    plaintiff = (li.plaintiff or "").lower()
    if plaintiff and any(kw in plaintiff for kw in (
            "mortgage", "bank", "credit union", "fannie", "freddie",
            "hud", "va ", "trustee", "servicing", "financial", "loan")):
        if lt in ("foreclosure_sale", "lis_pendens") or sale_status:
            foreclosure_signals.append(f"foreclosure_plaintiff:{plaintiff[:50]}")

    # Source indicates foreclosure — but only if the listing_type isn't
    # already a non-foreclosure distress type (DISTRESSED, DIVORCE, etc.)
    _non_foreclosure_types = {"distressed", "divorce_notice", "probate_notice",
                              "estate_lead", "elderly_disabled", "bankruptcy", "reo"}
    if lt not in _non_foreclosure_types:
        if any(kw in src for kw in ("foreclosure", "shapiro", "brock_scott", "hutchens",
                                    "rogers_townsend", "bell_carrington", "kania",
                                    "mcmichael", "ingle", "servicelink", "auction.com",
                                    "sheriff")):
            if not foreclosure_signals:  # don't double-count
                foreclosure_signals.append(f"source:{src}")

    # SC Public Index / ROD with foreclosure case type
    case_type = (raw.get("case_type") or "").lower()
    if "foreclosure" in case_type or "fp" in case_type:
        foreclosure_signals.append(f"case_type:{case_type}")

    if foreclosure_signals:
        # Subcategory
        subcat = "foreclosure"
        if "hoa_lien" in foreclosure_signals or lt == "hoa_sale":
            subcat = "hoa_foreclosure"
        elif "lis_pendens" in " ".join(foreclosure_signals):
            subcat = "lis_pendens"
        elif "sheriff" in " ".join(foreclosure_signals):
            subcat = "sheriff_sale"
        elif "source:" in " ".join(foreclosure_signals) and "auction" in src:
            subcat = "auction_foreclosure"
        return {
            "category": "foreclosure",
            "subcategory": subcat,
            "signals": foreclosure_signals,
            "confidence": "high" if len(foreclosure_signals) >= 2 else "medium",
        }

    # ---- 2. TAX DELINQUENCY (second priority) --------------------------
    tax_signals: list[str] = []

    if lt in ("tax_sale", "tax_lien"):
        tax_signals.append(f"listing_type:{lt}")

    # Delinquent tax data
    for key in ("tax_owed", "delinquent_tax", "tax_delinquent"):
        val = raw.get(key)
        if val is not None:
            if isinstance(val, dict):
                if val.get("amount") or val.get("value") or val.get("total_owed"):
                    tax_signals.append(f"delinquent_tax:{key}")
            elif isinstance(val, (int, float)) and val > 0:
                tax_signals.append(f"delinquent_tax:{key}")

    # Tax year delinquency from enricher
    tax_year = raw.get("tax_year")
    if tax_year and isinstance(tax_year, dict) and tax_year.get("delinquent"):
        tax_signals.append("tax_year_delinquent")

    # Upset bid (NC tax sale mechanism)
    if raw.get("upset_bid"):
        tax_signals.append("upset_bid")

    # Tax judgment from court
    if sale_status == "judgment" and "tax" in (raw.get("case_caption") or "").lower():
        tax_signals.append("tax_judgment")

    # Source is tax-related
    if any(kw in src for kw in ("tax_sale", "delinquent_tax", "upset_bid",
                                "delinquent", "tax_lien", "tax")):
        if not tax_signals:
            tax_signals.append(f"source:{src}")

    if tax_signals:
        subcat = "tax_sale" if lt == "tax_sale" else "tax_delinquent"
        return {
            "category": "tax_delinquency",
            "subcategory": subcat,
            "signals": tax_signals,
            "confidence": "high" if len(tax_signals) >= 2 else "medium",
        }

    # ---- 3. PREFORECLOSURE (early-stage distress) ----------------------
    pre_signals: list[str] = []

    if lt == "distressed":
        pre_signals.append("distressed_mls")
    elif lt == "divorce_notice":
        pre_signals.append("divorce_notice")
    elif lt == "elderly_disabled":
        pre_signals.append("elderly_disabled")
    elif lt == "estate_lead":
        pre_signals.append("estate_lead")

    # MLS lifecycle distress (from distress_score signals)
    mls = (raw.get("homeharvest") or raw.get("distressed") or {})
    if isinstance(mls, dict):
        status = str(mls.get("mls_status") or "").lower()
        if status in ("expired", "withdrawn", "cancelled", "canceled"):
            pre_signals.append(f"mls_{status}")
        dom = mls.get("days_on_mls")
        try:
            dom = float(dom) if dom is not None else None
        except (TypeError, ValueError):
            dom = None
        if dom and dom >= 120:
            pre_signals.append(f"mls_stale_{int(dom)}d")

    # Price cut
    if (raw.get("distress_stack") or {}).get("signals"):
        ds_signals = (raw.get("distress_stack") or {}).get("signals", [])
        if isinstance(ds_signals, list):
            for s in ds_signals:
                if isinstance(s, str) and "price_cut" in s:
                    pre_signals.append("price_cut")
                elif isinstance(s, str) and "stale_on_market" in s:
                    if "mls_stale" not in " ".join(pre_signals):
                        pre_signals.append("stale_on_market")
                elif isinstance(s, str) and "withdrawn" in s:
                    if "mls_" not in " ".join(pre_signals):
                        pre_signals.append("mls_withdrawn")

    # Code enforcement (pre-foreclosure pressure)
    if raw.get("code_enforcement") or raw.get("condemned"):
        pre_signals.append("code_enforcement")

    # Mortgage default signals (late payments, NOD without full foreclosure)
    if raw.get("mortgage_default") or raw.get("notice_of_default"):
        pre_signals.append("mortgage_default")

    # Child support lien (financial distress, pre-foreclosure)
    court_detail = raw.get("court_detail") or {}
    if isinstance(court_detail, dict) and court_detail.get("child_support"):
        pre_signals.append("child_support")

    if pre_signals:
        subcat = lt if lt != "unknown" else "early_distress"
        return {
            "category": "preforeclosure",
            "subcategory": subcat,
            "signals": pre_signals,
            "confidence": "medium" if len(pre_signals) >= 2 else "low",
        }

    # ---- 4. DISTRESSED PROPERTY (catch-all) -----------------------------
    distressed_signals: list[str] = []

    if lt == "probate_notice":
        distressed_signals.append("probate_notice")
    elif lt == "bankruptcy":
        distressed_signals.append("bankruptcy")
    elif lt == "reo":
        distressed_signals.append("reo_bank_owned")
    elif lt == "auction":
        distressed_signals.append("auction")
    elif lt == "divorce_notice":  # already caught above, but safety net
        distressed_signals.append("divorce_notice")

    # Derivation flags
    dflags = raw.get("derivation_flags") or {}
    if isinstance(dflags, dict):
        if dflags.get("free_and_clear"):
            distressed_signals.append("free_and_clear")
        if dflags.get("tired_landlord"):
            distressed_signals.append("tired_landlord")
        if dflags.get("divorce"):
            distressed_signals.append("divorce_flag")

    # Probate / estate
    if raw.get("probate") or raw.get("estate"):
        distressed_signals.append("probate")
    rs = raw.get("relationship_signal")
    if isinstance(rs, dict) and rs.get("kind"):
        distressed_signals.append(f"relationship:{rs['kind']}")

    # Bankruptcy
    if raw.get("bankruptcy"):
        distressed_signals.append("bankruptcy_flag")

    # HOA lien (non-foreclosure)
    if isinstance(rod, dict) and rod.get("has_hoa_lien"):
        distressed_signals.append("hoa_lien")

    # Mechanic lien
    if isinstance(rod, dict) and rod.get("has_mechanic_lien"):
        distressed_signals.append("mechanic_lien")

    # General adverse lien
    if isinstance(rod, dict) and rod.get("has_adverse_lien"):
        distressed_signals.append("adverse_lien")

    # Source-based catch-all
    if any(kw in src for kw in ("probate", "estate", "obituar", "heir")):
        distressed_signals.append(f"source:{src}")
    elif any(kw in src for kw in ("zillow", "realtor", "trulia")):
        if not distressed_signals:
            distressed_signals.append(f"source:{src}")

    # If we have ANY signal, categorize as distressed_property
    if distressed_signals:
        subcat = lt if lt != "unknown" else "distressed"
        return {
            "category": "distressed_property",
            "subcategory": subcat,
            "signals": distressed_signals,
            "confidence": "low",
        }

    # ---- FALLBACK: unclassified listing --------------------------------
    # If nothing matched, it's still on the board for a reason — default
    # to distressed_property with low confidence so it shows up in filters.
    return {
        "category": "distressed_property",
        "subcategory": "uncategorized",
        "signals": [f"source:{src}"] if src else ["unknown"],
        "confidence": "low",
    }


def enrich_property_category(listings: list[Listing]) -> dict:
    """Attach raw['property_category'] to every listing.

    Pure compute over existing board data. Idempotent — re-running
    overwrites the category with a fresh computation.
    """
    counts = {
        "foreclosure": 0,
        "preforeclosure": 0,
        "tax_delinquency": 0,
        "distressed_property": 0,
    }
    subcat_counts: dict[str, int] = {}
    n_high = n_med = n_low = 0

    for li in listings:
        result = _categorize(li)
        if result is None:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["property_category"] = result
        cat = result.get("category", "distressed_property")
        counts[cat] = counts.get(cat, 0) + 1
        sub = result.get("subcategory", "unknown")
        subcat_counts[sub] = subcat_counts.get(sub, 0) + 1
        conf = result.get("confidence", "low")
        if conf == "high":
            n_high += 1
        elif conf == "medium":
            n_med += 1
        else:
            n_low += 1

    log.info("property_category.done",
             foreclosure=counts["foreclosure"],
             preforeclosure=counts["preforeclosure"],
             tax_delinquency=counts["tax_delinquency"],
             distressed_property=counts["distressed_property"],
             high_confidence=n_high, medium=n_med, low=n_low,
             total=len(listings))
    return {
        "categories": counts,
        "subcategories": subcat_counts,
        "confidence": {"high": n_high, "medium": n_med, "low": n_low},
        "rows": len(listings),
    }
