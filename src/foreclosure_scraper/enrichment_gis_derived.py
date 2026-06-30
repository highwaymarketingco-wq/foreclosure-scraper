"""GIS-DERIVED enrichment — mine the FULL parcel-attribute bag for signals the
generic gis_attrs mapper leaves on the table. Zero new HTTP: it reads only
raw['gis_attrs_full'] (the whole outFields=* dict that enrichment_gis_attrs
already fetched and now stashes).

Two derived products, both per-county because the field names vary wildly:

  1. LAST SALE (amount + date, plus deed book/page when present) -> written into
     raw['gis']['last_sale'] = {amount, date, book, page, source}. This is the
     EXACT shape the equity engine's _payoff path 3 reads (gis['last_sale']
     {'amount','date'}), so it lights up the last-sale-amortized payoff on the
     SC counties that have no assessor card and no recorded Deed of Trust feed
     (Greenville/Charleston/Spartanburg/Pickens/Anderson/Laurens). We also emit a
     DEED-AGE signal (years since last transfer) under raw['gis']['deed_age'].

  2. TAX-DELINQUENCY RUNWAY (Greenville layer) — PAIDDATE (epoch-ms -> the date
     property tax was last paid) + TOTTAX (annual tax billed) ->
     raw['tax_status'] = {paid_through, amount, source}. A stale paid_through is a
     leading distress indicator (taxes lapsing before the foreclosure even files).

Per-county field names (live-verified against SCDOT SC_Parcels MapServer):
  Greenville  : SLPRICE / DEEDDATE(epoch-ms) / CUBOOK / CUPAGE ; PAIDDATE / TOTTAX
  Charleston  : SALE_PRICE / RECORDED_D(epoch-ms) / DEED_BOOK_ (combined book-page)
  Spartanburg : SaleAmount / SaleDate(epoch-ms) / DeedBook / DeedPage
  Pickens     : SALEP / SALEDT
  Anderson    : SALE_PRICE / SALE_YEAR(year int) / DBOOK / DPAGE
  Laurens     : True_Sale(Y/N gate) / TransferDa(epoch-ms) / Deed_Book / Deed_Page

Defensive throughout: missing-only (never clobbers a better last_sale already on
the listing), type-guards denormalized-float junk (Spartanburg's SaleAmount
returns uninitialized doubles like 1065353216 / 1.2e9 for blank cells), screens
non-arms-length $1/$10 deeds, and rejects out-of-range dates/amounts.

Wiring (orchestrator owns the single write; do NOT wire here): must run AFTER
gis_attrs (which populates raw['gis_attrs_full']) and BEFORE enrich_equity (so the
fresh last_sale feeds the payoff path). In scripts/merge_today_sources.py add
    from foreclosure_scraper.enrichment_gis_derived import enrich_gis_derived
    print("enrich_gis_derived:", enrich_gis_derived(merged))
immediately before the `enrich_equity(merged)` call.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

import structlog

from .models import Listing
from .valuation.amortize import _as_date

log = structlog.get_logger()


# Per-county field tables. Each tuple: (price, date, book, page, year, gate).
# `date` is the transfer/recorded date (epoch-ms or string); `year` is a bare
# year int used when no full date field exists (Anderson); `gate` is an optional
# arms-length flag field whose value must NOT be a clear "no" before we trust it.
_SALE_FIELDS: dict[str, dict[str, Any]] = {
    "Greenville": {"price": "SLPRICE", "date": "DEEDDATE",
                   "book": "CUBOOK", "page": "CUPAGE"},
    "Charleston": {"price": "SALE_PRICE", "date": "RECORDED_D",
                   "book": "DEED_BOOK_", "page": None},
    "Spartanburg": {"price": "SaleAmount", "date": "SaleDate",
                    "book": "DeedBook", "page": "DeedPage"},
    "Pickens": {"price": "SALEP", "date": "SALEDT",
                "book": None, "page": None},
    "Anderson": {"price": "SALE_PRICE", "date": None, "year": "SALE_YEAR",
                 "book": "DBOOK", "page": "DPAGE"},
    "Laurens": {"price": None, "date": "TransferDa",
                "book": "Deed_Book", "page": "Deed_Page", "gate": "True_Sale"},
}

# Greenville is the one SCDOT layer that publishes a tax-paid date + annual bill.
_TAX_FIELDS: dict[str, dict[str, str]] = {
    "Greenville": {"paid": "PAIDDATE", "amount": "TOTTAX"},
}

# Spartanburg's SaleAmount returns uninitialized doubles (denormalized junk) like
# 1065353216 / 1.2e9 for blank cells; cap any sale amount well under that.
_MAX_SALE = 100_000_000.0
_MIN_ARMS_LENGTH = 1000.0   # screen $1 / $10 quitclaim & estate deeds

# Generic sale field-name fallback for counties not in _SALE_FIELDS (price tuple, date tuple).
_GEN_SALE_PRICE = ("SALE_PRICE", "SALEPRICE", "SALE_AMT", "SALEAMT", "SaleAmount", "SALE_AMOUNT",
                   "TOTSALEPRICE", "PKG_SALE_PRICE", "LASTSALEAMT", "SLPRICE", "SALEP", "PRICE",
                   "DEED_PRICE", "CONSIDERATION", "SALEPRICE1", "LASTSALE")
_GEN_SALE_DATE = ("SALE_DATE", "SALEDATE", "SaleDate", "DEED_DATE", "DEEDDATE", "RECORDED_D",
                  "SALEDT", "TransferDa", "LASTSALEDATE", "DEEDDT", "SALE_DT", "REC_DATE", "DOS")
# Owner-occupancy: SC assessment ratio (4% = legal residence / owner-occupied; 6% = other) +
# homestead/legal-residence exemption text (NC + SC).
# Real SC field names (live-verified across the SCDOT shared MapServer): Spartanburg AssessmentCode
# (4%OO / 6%VAC), Anderson RATIO, plus the generic candidates.
_RATIO_FIELDS = ("RATIO", "AssessmentCode", "ASSESSMENTCODE", "ASSESS_CD", "ASMT_CODE", "USE_CODE",
                 "ASMT_RATIO", "ASSESSMENT_RATIO", "ASSESS_RT", "TAXRATIO", "ASSMT_RAT", "ASSESSRAT",
                 "RATIO_CD", "RATIOCODE", "ASSESSMENTRATIO", "ASR", "ASMTRATIO", "RC")
_EXEMPT_FIELDS = ("EXEMPTSTAT", "TaxExempti", "Exempt_Par", "EXEMPT_PAR", "EXEMPTPAR", "EXEMPTION",
                  "EXEMPT_DESC", "EXEMPTION_DESC", "EXEMPTIONS", "HOMESTEAD", "LEGAL_RES", "LEGALRES",
                  "RESIDENCE", "EXEMPT_CD", "EXEMPTCODE", "Exempt")


def _derive_owner_occupied(attrs: dict) -> Optional[bool]:
    """SC 4% assessment ratio / AssessmentCode '4%OO' => owner-occupied legal residence; 6%/VAC =>
    not. Plus homestead/elderly/veteran/legal-residence exemption text. None when no usable signal."""
    for f in _RATIO_FIELDS:
        v = _ci_get(attrs, f)
        if v in (None, ""):
            continue
        s = str(v).strip().upper()
        if len(s) > 12:
            continue  # not a ratio code (probably a value field collision)
        if "OWNER" in s or "LEGAL RES" in s or "OO" in s or "4%" in s or s in ("4", "4.0", "0.04", ".04", "RC"):
            return True
        if "VAC" in s or "OTHER" in s or "NON" in s or "6%" in s or s in ("6", "6.0", "0.06", ".06"):
            return False
    for f in _EXEMPT_FIELDS:
        v = _ci_get(attrs, f)
        if v and any(t in str(v).upper() for t in ("HOMESTEAD", "LEGAL RES", "OWNER OCC", "ELD", "VET")):
            return True
    return None


def _ci_get(attrs: dict[str, Any], key: Optional[str]) -> Any:
    """Case-insensitive attribute lookup (SCDOT field casing is inconsistent)."""
    if not key:
        return None
    if key in attrs:
        return attrs[key]
    lk = key.lower()
    for k, v in attrs.items():
        if k.lower() == lk:
            return v
    return None


def _num(v: Any) -> Optional[float]:
    """Parse money/number, rejecting NaN, denormalized junk, and blanks."""
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None
    if f != f:  # NaN
        return None
    if 0 < abs(f) < 1e-6:  # denormalized junk
        return None
    return f


def _county(li: Listing) -> str:
    c = (li.county or "").replace(" County", "").strip()
    for sfx in (", NC", ", SC", ",NC", ",SC"):
        if c.upper().endswith(sfx):
            c = c[: -len(sfx)].strip()
    return c.split(",")[0].strip().title()


def _clean_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _derive_last_sale(county: str, attrs: dict[str, Any]) -> Optional[dict]:
    """Build {amount, date, book, page, source} from county-specific fields.

    Returns None unless we have at least a usable amount OR (date + deed ref).
    The equity engine only consumes amount+date; book/page ride along for
    provenance and a future recorded-comps cross-check.
    """
    cfg = _SALE_FIELDS.get(county)
    if not cfg:
        # Generic fallback: try common ArcGIS sale field names so UNLISTED counties
        # (Oconee, Georgetown, NC) still light up a last_sale + deed-age.
        g_amt = None
        for pf in _GEN_SALE_PRICE:
            v = _num(_ci_get(attrs, pf))
            if v is not None and _MIN_ARMS_LENGTH <= v <= _MAX_SALE:
                g_amt = round(v, 2)
                break
        g_dt = None
        for df in _GEN_SALE_DATE:
            d = _as_date(_ci_get(attrs, df))
            if isinstance(d, date) and 1900 <= d.year <= date.today().year:
                g_dt = d
                break
        if g_amt is None and g_dt is None:
            return None
        out: dict[str, Any] = {"source": "gis_derived:generic"}
        if g_amt is not None:
            out["amount"] = g_amt
        if isinstance(g_dt, date):
            out["date"] = g_dt.isoformat()
        return out

    # Arms-length gate (Laurens True_Sale = 'N' means NOT a market sale).
    gate = cfg.get("gate")
    if gate:
        gv = _clean_str(_ci_get(attrs, gate))
        if gv and gv.upper() in ("N", "NO", "FALSE", "0"):
            return None

    amount = None
    raw_price = _num(_ci_get(attrs, cfg.get("price")))
    if raw_price is not None and _MIN_ARMS_LENGTH <= raw_price <= _MAX_SALE:
        amount = round(raw_price, 2)

    # Date: prefer a real date field; fall back to a bare year (Anderson) -> mid-year.
    sale_date: Any = None
    dt = _as_date(_ci_get(attrs, cfg.get("date")))
    if dt is not None:
        sale_date = dt
    elif cfg.get("year"):
        yv = _num(_ci_get(attrs, cfg.get("year")))
        if yv and 1900 <= int(yv) <= date.today().year:
            sale_date = date(int(yv), 6, 30)
    # Sanity: a parsed date must be plausible (not epoch-0, not future).
    if isinstance(sale_date, date):
        if sale_date.year < 1900 or sale_date > date.today():
            sale_date = None

    if amount is None and sale_date is None:
        return None

    out: dict[str, Any] = {"source": f"gis_derived:{county.lower()}"}
    if amount is not None:
        out["amount"] = amount
    if isinstance(sale_date, date):
        out["date"] = sale_date.isoformat()
    book = _clean_str(_ci_get(attrs, cfg.get("book")))
    page = _clean_str(_ci_get(attrs, cfg.get("page")))
    # Charleston packs "book-page" into one field (DEED_BOOK_), no separate page.
    if book:
        out["book"] = book
    if page:
        out["page"] = page
    return out


def _qualified_sale_from_card(card: dict[str, Any]) -> Optional[tuple[float, Optional[str]]]:
    """Pull a usable (amount, date) from a qPublic-style assessor_card.

    Order: a top-level 'sale_price' first (the card's headline last sale), else
    the most-recent QUALIFIED arms-length entry in card['sales'][]. An entry is
    QUALIFIED only when its 'reason' contains 'QUALIF' but NOT 'NOT QUALIF'
    (the board carries both 'DEED QUALIFIED'/'QUALIFIED SALE' and 'NOT QUALIFIED'
    — the naive substring check would wrongly accept the latter) AND it carries a
    real 'price'. $1/$10 non-arms-length transfers are screened by _MIN_ARMS_LENGTH.
    """
    if not isinstance(card, dict):
        return None
    # Headline sale_price on the card (paired with the most-recent sale's date if any).
    sp = _num(card.get("sale_price"))
    if sp is not None and _MIN_ARMS_LENGTH <= sp <= _MAX_SALE:
        sdate = None
        sales = card.get("sales")
        if isinstance(sales, list):
            for s in sales:
                if isinstance(s, dict) and _num(s.get("price")) == round(sp, 2):
                    sdate = _clean_str(s.get("sale_date"))
                    break
            if sdate is None and sales and isinstance(sales[0], dict):
                sdate = _clean_str(sales[0].get("sale_date"))
        return round(sp, 2), sdate

    # Else: most-recent QUALIFIED arms-length sale with a price.
    sales = card.get("sales")
    if not isinstance(sales, list):
        return None
    best: Optional[tuple] = None  # (sortkey, amount, date_str)
    for s in sales:
        if not isinstance(s, dict):
            continue
        reason = (s.get("reason") or "").upper()
        if "QUALIF" not in reason or "NOT QUALIF" in reason:
            continue
        amt = _num(s.get("price"))
        if amt is None or not (_MIN_ARMS_LENGTH <= amt <= _MAX_SALE):
            continue
        ds = _clean_str(s.get("sale_date"))
        d = _as_date(ds)
        sortkey = d.isoformat() if isinstance(d, date) else "0000"
        if best is None or sortkey > best[0]:
            best = (sortkey, round(amt, 2), ds)
    if best is not None:
        return best[1], best[2]
    return None


def _consolidate_sale_amount(li: Listing) -> Optional[dict]:
    """Recover a recorded sale AMOUNT (+date/source) for the ARV floor when
    gis.last_sale carries no usable amount.

    The board-wide Gosnell bug: calc.py's ARV floor reads ONLY raw.gis.last_sale
    .amount, so 84 leads whose recorded sale lives in raw.cama / raw.assessor_card
    (but not on the GIS parcel layer) get an ARV *below* a known sale. Waterfall:
      1) raw.cama  : last_sale_amount / last_sale_price (+ last_sale_date)
      2) raw.assessor_card : sale_price, else most-recent QUALIFIED sales[] entry
    Returns {amount, date?, source} or None. Amount/date are screened the same way
    as _derive_last_sale (arms-length floor, plausible date).
    """
    raw = li.raw if isinstance(li.raw, dict) else {}

    # 1) CAMA recorded sale.
    cama = raw.get("cama")
    if isinstance(cama, dict):
        amt = None
        for f in ("last_sale_amount", "last_sale_price"):
            v = _num(cama.get(f))
            if v is not None and _MIN_ARMS_LENGTH <= v <= _MAX_SALE:
                amt = round(v, 2)
                break
        if amt is not None:
            out: dict[str, Any] = {"amount": amt, "source": "cama"}
            d = _as_date(cama.get("last_sale_date"))
            if isinstance(d, date) and 1900 <= d.year <= date.today().year:
                out["date"] = d.isoformat()
            return out

    # 2) Assessor card (sale_price / qualified sales[]).
    card = raw.get("assessor_card")
    qc = _qualified_sale_from_card(card) if isinstance(card, dict) else None
    if qc is not None:
        amt, ds = qc
        out = {"amount": amt, "source": "assessor_card"}
        d = _as_date(ds)
        if isinstance(d, date) and 1900 <= d.year <= date.today().year:
            out["date"] = d.isoformat()
        return out

    return None


def _derive_tax_status(county: str, attrs: dict[str, Any]) -> Optional[dict]:
    """Greenville PAIDDATE (epoch-ms) + TOTTAX -> {paid_through, amount, source}."""
    cfg = _TAX_FIELDS.get(county)
    if not cfg:
        return None
    paid_dt = _as_date(_ci_get(attrs, cfg.get("paid")))
    amount = _num(_ci_get(attrs, cfg.get("amount")))
    out: dict[str, Any] = {}
    if isinstance(paid_dt, date) and 1990 <= paid_dt.year <= date.today().year + 1:
        out["paid_through"] = paid_dt.isoformat()
    if amount is not None and 0 < amount <= 1_000_000:
        out["amount"] = round(amount, 2)
    if not out:
        return None
    out["source"] = f"gis_derived:{county.lower()}"
    return out


def enrich_gis_derived(listings: list[Listing]) -> dict:
    """Mine raw['gis_attrs_full'] for last-sale + tax-status. Returns coverage stats.

    Must run AFTER enrich_gis_attrs (populates gis_attrs_full) and BEFORE
    enrich_equity (consumes raw['gis']['last_sale']).
    """
    stats = {"scanned": 0, "last_sale": 0, "deed_age": 0, "tax_status": 0,
             "sale_consolidated": 0}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        # Scrub any carried-over implausible last_sale.amount (e.g. Spartanburg GIS
        # returns an uninitialized-double ~$1.2B in its sale field) regardless of which
        # run/source wrote it, BEFORE the attrs gate — the "missing-only, never clobber"
        # logic below would otherwise preserve a pre-cap corrupt value forever, and the
        # address-less carryover rows have no gis_attrs_full so they'd skip the gate.
        _ls = (raw.get("gis") or {}).get("last_sale")
        if isinstance(_ls, dict) and _ls.get("amount") and _ls["amount"] > 50_000_000:
            _ls.pop("amount", None)

        # --- SALE CONSOLIDATION (runs for EVERY listing, BEFORE the attrs gate) ---
        # The board-wide Gosnell bug: calc.py's ARV floor reads ONLY
        # gis.last_sale.amount, so leads whose recorded sale only lives in raw.cama /
        # raw.assessor_card (many courtlistener/bankruptcy rows have NO gis_attrs_full)
        # get an ARV below a known sale. When gis.last_sale lacks a usable AMOUNT,
        # fall back to cama/assessor_card and write amount/date/source into
        # gis.last_sale so the PRE-valuation ARV floor + equity see it.
        _gis = raw.get("gis")
        _cur = _gis.get("last_sale") if isinstance(_gis, dict) else None
        _has_amount = isinstance(_cur, dict) and _cur.get("amount")
        if not _has_amount:
            consol = _consolidate_sale_amount(li)
            if consol is not None:
                g = raw.setdefault("gis", {})
                cur = g.get("last_sale")
                if isinstance(cur, dict):
                    # Preserve any existing date/book/page provenance; only fill amount
                    # (+date when the existing entry has none).
                    cur["amount"] = consol["amount"]
                    if "date" in consol and not cur.get("date"):
                        cur["date"] = consol["date"]
                    cur["amount_source"] = consol["source"]
                else:
                    g["last_sale"] = {
                        "amount": consol["amount"],
                        **({"date": consol["date"]} if "date" in consol else {}),
                        "source": f"gis_derived:consolidated:{consol['source']}",
                    }
                stats["sale_consolidated"] += 1
                li.raw = raw

        attrs = raw.get("gis_attrs_full")
        if not isinstance(attrs, dict) or not attrs:
            continue
        stats["scanned"] += 1
        county = _county(li)

        gis = raw.setdefault("gis", {})

        # --- Last sale (missing-only; never clobber a better existing source) ---
        existing = gis.get("last_sale")
        has_usable = isinstance(existing, dict) and (
            existing.get("amount") or existing.get("date"))
        if not has_usable:
            ls = _derive_last_sale(county, attrs)
            if ls:
                gis["last_sale"] = ls
                stats["last_sale"] += 1
                # Deed-age signal (years since last recorded transfer).
                d = _as_date(ls.get("date"))
                if isinstance(d, date):
                    age = round((date.today() - d).days / 365.25, 1)
                    if 0 <= age <= 200 and "deed_age" not in gis:
                        gis["deed_age"] = {"years": age, "last_transfer": d.isoformat()}
                        stats["deed_age"] += 1

        # --- Owner-occupancy from assessment ratio / homestead exemption (net-new) ---
        if "owner_occupied" not in gis:
            oo = _derive_owner_occupied(attrs)
            if oo is not None:
                gis["owner_occupied"] = oo
                stats["owner_occupied"] = stats.get("owner_occupied", 0) + 1

        # --- Tax-delinquency runway (Greenville) — missing-only ---
        if not isinstance(raw.get("tax_status"), dict):
            ts = _derive_tax_status(county, attrs)
            if ts:
                raw["tax_status"] = ts
                stats["tax_status"] += 1

        li.raw = raw

    log.info("gis_derived.done", **stats)
    return stats
