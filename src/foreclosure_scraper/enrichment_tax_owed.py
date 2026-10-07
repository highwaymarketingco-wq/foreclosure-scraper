"""Normalize per-source delinquent-tax amounts into one raw['tax_owed'] field and
cross-reference it onto matching parcels.

The tax-distress scrapers each capture the owed amount under their own raw key —
Buncombe `principal_tax_due`, SC state liens `balance`, Oconee FLC `fll_bid` — and
nothing on the board reads a unified figure. The assessor/GIS feed only ever gives
assessed/market VALUE, never the delinquent BALANCE, so this is the only place a
real taxes-OWED number lands.

Two passes, both free + pure-Python + idempotent:
  1. Normalize: each tax lead's own amount -> raw['tax_owed'] =
     {balance, kind, source, year, basis:'own_record', years_delinquent?} —
     years_delinquent is read from a sibling source block that lists the unpaid
     years or states a count (raw['multi_year_delinquent_tax'], raw['qpaybill_roll']),
     never invented. Since 2026-10-07 it counts only the LATE levy years
     (tax_calendar: past their delinquent date and unpaid); the raw count of unpaid
     bills is unpaid_bill_years, and the bills not late yet are not_yet_late_years
     (+ not_yet_late_amount when the source states the per-year amounts).
  2. Cross-reference: build a (state, county, parcel) -> tax_owed index from those,
     then stamp it onto ANY lead (court/probate/foreclosure) resolved to the same
     parcel that doesn't already carry one (basis:'parcel_cross_ref'). A court lead
     the resolver just pinned to a parcel that is ALSO on a delinquent-tax list
     inherits the owed balance — a strong, free motivated-seller signal.

Gate off with FORECLOSURE_TAX_OWED=0.
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Iterable, Optional

import structlog

from . import tax_calendar as _cal
from .models import Listing
from .verification.verifiers._tax_common import NON_PROPERTY_TAX_SOURCES

log = structlog.get_logger()

# source-substring -> (raw subkey, amount field, kind)
_SOURCES = {
    "buncombe_delinquent_tax": ("buncombe_delinquent_tax", "principal_tax_due", "delinquent_tax"),
    "sc_state_tax_lien": ("sc_state_tax_lien", "balance", "state_tax_lien"),
    "oconee_forfeited_land": ("oconee_forfeited_land", "fll_bid", "flc_opening_bid"),
    "nc_ptscloud_delinquent_tax": ("nc_ptscloud_delinquent_tax", "principal_tax_due", "delinquent_tax"),
    "nc_county_pdf_delinquent_tax": ("nc_county_pdf_delinquent_tax", "total_due", "delinquent_tax"),
    "nc_county_csv_delinquent_tax": ("nc_county_csv_delinquent_tax", "total_due", "delinquent_tax"),
    "rutherford_wildfire": ("rutherford_wildfire", "taxes_owed", "delinquent_tax"),
    "multi_year_delinquent_tax": ("multi_year_delinquent_tax", "total_due", "delinquent_tax"),
    "spartanburg_delinquent_tax": ("spartanburg_delinquent_tax", "balance", "delinquent_tax"),
    "chesterfield_delinquent_tax": ("chesterfield_delinquent_tax", "total_due", "delinquent_tax"),
    "york_delinquent_tax": ("york_delinquent_tax", "total_due", "delinquent_tax"),
    "florence_delinquent_tax": ("florence_delinquent_tax", "total_due", "delinquent_tax"),
    "sumter_delinquent_tax": ("sumter_delinquent_tax", "total_due", "delinquent_tax"),
    # Georgetown's FLC (Forfeited-Land-Commission) rows carry a real, county-published
    # over-the-counter opening-bid price (same convention as oconee_forfeited_land's
    # fll_bid, above). The block key is shared by all three Georgetown CivicEngage docs
    # (FLC/Tax-Sale/MIE) but only FLC rows set "opening_bid", so this entry is a no-op
    # for the other two -- the Tax-Sale list genuinely carries no dollar figure at all
    # (confirmed 2026-09-29, see georgetown_civicengage.py's docstring) and MIE rows use
    # a different raw shape. Added 2026-09-29 auditing the 355-row "no tax amount" gap.
    "georgetown_civicengage": ("georgetown_civicengage", "opening_bid", "flc_opening_bid"),
    # Horry's delinquent tax sale workbooks gained an "FLC Bid Amount" column (October 2026
    # editions, every row): the county's own minimum bid, same convention as above.
    "horry_delinquent_xlsx": ("horry_delinquent_xlsx", "flc_bid_amount", "flc_opening_bid"),
}

# generic amount keys scanned for any other tax/FLC/lien source subdict
# `balance_owed` (added 2026-09-20) is the real delinquent balance carried by
# raw['qpaybill_roll'] (19 SC counties) and raw['transylvania_tax']. Every one of
# their ~40,000 rows has it, yet only a few hundred reached raw['tax_owed'], so
# Spartanburg showed 288 of 4,280 rows with a known debt. It goes last so it
# never outranks a more specific key on a block that carries both.
_GENERIC_KEYS = (
    "principal_tax_due", "tax_due", "taxes_owed", "amount_owed", "total_due",
    "balance", "lien_amount", "fll_bid", "flc_bid", "opening_bid", "balance_owed",
)
_TAXISH = ("tax", "flc", "forfeited", "delinquent", "lien")


def _money(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = re.sub(r"[^\d.]", "", str(v))
    if not s or s == ".":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f > 0 else None


def _pkey(pid: Optional[str]) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", pid or "").upper()


def _county_county_key(li: Listing) -> tuple:
    return (li.state, (li.county or "").replace(" County", "").strip().title(),
            _pkey(li.parcel_id))


_YEAR_KEYS = ("year", "tax_year", "taxyear", "bill_year", "bill_years",
              "year_span", "latest_cycle", "first_cycle")

# Depth audit 2026-10-02 (per-signal completeness check, not the 2026-09-21 per-
# source extraction audit): raw['tax_owed'] normalizes a balance + a single year
# but drops the multi-year delinquency history that several source blocks sitting
# right next to it already carry -- raw['multi_year_delinquent_tax']['years_delinquent']
# (Buncombe-area multi-year engine) and raw['qpaybill_roll']['years_delinquent']
# (19 SC counties via qPayBill) are both already on the board, just never promoted.
# Measured: 46,037 of 88,927 raw['tax_owed'] rows are sourced from one of these
# multi-year-capable blocks; none of them exposed years_delinquent before this.
# A plain int count, when the source states one directly; _YEARS_LIST_KEYS is the
# fallback (count the years a source lists, e.g. qpaybill_roll['years_unpaid']).
_YEARS_DELINQUENT_KEYS = ("years_delinquent", "matured_years_delinquent")
_YEARS_LIST_KEYS = ("years_unpaid", "years")


def _coerce_year(val) -> Optional[int]:
    """Extract a 4-digit year from int, str, list, or None."""
    if val is None:
        return None
    if isinstance(val, (list, tuple)):
        # bill_years is a list like ['2023', '2024', '2025'] — take the oldest
        for v in sorted(val):
            y = _coerce_year(v)
            if y:
                return y
        return None
    try:
        s = str(val).strip()
        # year_span like "2023-2025" — take the first year
        if "-" in s:
            s = s.split("-")[0].strip()
        y = int(s[:4])
        return y if 1990 <= y <= 2030 else None
    except (ValueError, TypeError):
        return None


def _extract(li: Listing) -> tuple[Optional[float], Optional[str], object]:
    """(balance, kind, year) from a lead's OWN source record, else (None, None, None)."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    src = li.source or ""

    # --- Pass A: explicit source mapping ---
    for sub, (key, fld, kind) in _SOURCES.items():
        if sub in src:
            blk = raw.get(key) or {}
            bal = _money(blk.get(fld))
            if bal:
                year = None
                for yk in _YEAR_KEYS:
                    year = _coerce_year(blk.get(yk))
                    if year:
                        break
                return bal, kind, year

    # --- Pass B: generic scan for any other tax-ish source ---
    # Gate per-BLOCK, not once on the lead's own `src`: a tax-ish raw sub-block
    # can arrive on a lead whose PRIMARY source isn't tax-named at all, when
    # dedupe() merges a tax-delinquent record into a foreclosure/court lead
    # for the same parcel (merge() keeps the bucket-holder's source/source_url,
    # per its own docstring). Found 2026-09-14: a Greenville parcel merged from
    # greenville_mie_adverts (a foreclosure lead) + greenville_delinquent_tax
    # carried a real raw["greenville_delinquent_tax"]["total_due"] that this
    # function silently never saw, because the old gate checked only
    # `li.source` ("greenville_mie_adverts" -- no "tax"/"delinquent"
    # substring) before ever looking at block names. Checking each block's own
    # name is a strict superset of the old behavior: every row that used to
    # match (tax-ish `src`) still does, and non-tax merged-in blocks on an
    # unrelated lead still don't spuriously match on _GENERIC_KEYS alone.
    src_is_taxish = any(k in src for k in _TAXISH)
    for blk_name, blk in raw.items():
        if blk_name == "tax_owed":  # skip pre-existing tax_owed from prior runs
            continue
        if not (src_is_taxish or any(k in blk_name for k in _TAXISH)):
            continue
        if isinstance(blk, dict):
            for gk in _GENERIC_KEYS:
                bal = _money(blk.get(gk))
                if bal:
                    year = None
                    for yk in _YEAR_KEYS:
                        year = _coerce_year(blk.get(yk))
                        if year:
                            break
                    return bal, "delinquent_tax", year

    # --- Pass C: fallback — pre-existing tax_owed balance with year=None ---
    # On board re-runs, source sub-dicts may be stripped but tax_owed survived.
    # Try to find a year in ANY remaining raw sub-dict (lrcpwa, gis, cama, etc.).
    to = raw.get("tax_owed")
    if isinstance(to, dict) and to.get("balance"):
        bal = _money(to["balance"])
        if bal:
            year = None
            # Check lrcpwa (has tax_year from PTS roll)
            for blk_name, blk in raw.items():
                if blk_name == "tax_owed":
                    continue
                if isinstance(blk, dict):
                    for yk in _YEAR_KEYS:
                        year = _coerce_year(blk.get(yk))
                        if year:
                            break
                    if year:
                        break
            return bal, to.get("kind", "delinquent_tax"), year

    return None, None, None


def _find_years_delinquent(raw: dict) -> Optional[int]:
    """The count of unpaid years a sibling source block STATES, as the source counted it (same
    "don't trust a single block name, scan them all" shape as the year search above). An explicit
    count key wins; a years-list key's length is the fallback (qpaybill_roll['years_unpaid'] is a
    list of year strings, not a count). A source's own count can include the current bill that is
    not late yet (multi_year_delinquent_tax counts len(years)), so enrich_tax_owed no longer
    stamps this: it stamps tax_year_status()'s late-years count."""
    if not isinstance(raw, dict):
        return None
    for blk_name, blk in raw.items():
        if blk_name == "tax_owed" or not isinstance(blk, dict):
            continue
        for k in _YEARS_DELINQUENT_KEYS:
            v = blk.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return int(v)
        for k in _YEARS_LIST_KEYS:
            v = blk.get(k)
            if isinstance(v, list) and v:
                return len(v)
    return None


# ---------------------------------------------------------------------------
# Which unpaid levy years are LATE (tax_calendar). 2026-10-07, owner + attorney rule: a current-
# year bill that is not late yet is not a delinquency. Measured on the 10/7 board: the multi-year
# Buncombe engine lists the current levy in `years` (its `years_delinquent` = len(years)), so
# 478+66 buncombe_unpaid_bills rows read "2 or 3 years" for unpaid 2025 + 2026 when only 2025 was
# late, and 1,085 property-tax rows carried a 2026 levy year (400-odd of them nothing older).
# ---------------------------------------------------------------------------
#: blocks that are this module's (or tax_aging's) own outputs, never a source's year list
_DERIVED_TAX_BLOCKS = frozenset({"tax_owed", "tax_aging_surfaced", "two_year_delinquent"})
#: keys a source block lists its UNPAID levy years under (qpaybill_roll keeps the not-yet-late
#: current year apart in all_unpaid_years; the others list every unpaid year in `years`)
_UNPAID_YEAR_LIST_KEYS = ("all_unpaid_years", "years_unpaid", "years", "bill_years")
#: per-bill lists and the year / amount keys their entries carry (catalis_roll, billtrax, greenwood,
#: nc_ptscloud by_year)
_BILL_LIST_KEYS = ("bills", "by_year")
_BILL_YEAR_KEYS = ("year", "tax_year")
_BILL_AMOUNT_KEYS = ("total_due", "total_due_now", "amount", "balance")


def _is_tax_source_block(name: str) -> bool:
    """A source's own tax block: tax-ish by name (the Pass B rule) or a county roll block
    (qpaybill_roll, catalis_roll)."""
    return name not in _DERIVED_TAX_BLOCKS and (any(k in name for k in _TAXISH) or name.endswith("_roll"))


#: Blocks read from a county's LIVE bill roll (what is unpaid today). On the same row they beat a
#: published delinquent-list history (multi_year_delinquent_tax's Oconee/Pickens lists name the
#: years a parcel was ADVERTISED, a later redemption included): 99 rows of the 10/7 board carried
#: both, and every one disagreed with its qpaybill_roll.
_LIVE_ROLL_BLOCKS = frozenset({"qpaybill_roll", "catalis_roll", "nc_ptscloud_delinquent_tax",
                               "billtrax_dorchester_delinquent_tax",
                               "greenwood_corebtpay_delinquent_tax"})


_PTS_BILL_RE = re.compile(r"^\d+-(\d{4})-(\d{4})-")
_DUE_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_PTS = "nc_ptscloud_delinquent_tax"


def ptscloud_levy_year(bill: dict) -> Optional[int]:
    """The LEVY year of a PTS Cloud bill (one roll row, or the block's representative row).

    TAX_YEAR is not always it. 218 rows of the 10/7 board carried TAX_YEAR 2026 on a bill numbered
    "<account>-2026-2025-0070-00" and due 09/01/2025: the 2025 levy (an NC bill is due September 1
    of its levy year, G.S. 105-360), late since January 6, 2026, not a current bill. Ordinary bills
    read "<account>-2025-2025-0000-00". So: the due date's year (a due date before July is the
    previous year's levy), else the bill number's second year, else TAX_YEAR."""
    if not isinstance(bill, dict):
        return None
    m = _DUE_DATE_RE.search(str(bill.get("bill_due_date") or ""))
    if m:
        y = int(m.group(3)) - (1 if int(m.group(1)) < 7 else 0)
        if _cal.levy_year(y):
            return y
    m = _PTS_BILL_RE.match(str(bill.get("bill_number") or ""))
    if m and _cal.levy_year(m.group(2)):
        return int(m.group(2))
    return _cal.levy_year(bill.get("tax_year"))


def _unpaid_bill_layer_year(name: str, blk: dict) -> Optional[int]:
    """An ArcGIS unpaid-bill layer row (arcgis_distress_layers.py buncombe_unpaid_bills*: one row
    per unpaid bill of a past levy) names its bill's levy year."""
    if name == "arcgis_distress" and "unpaid" in str(blk.get("layer") or ""):
        return _cal.levy_year(blk.get("levy_year"))
    return None


def unpaid_levy_years(raw: dict) -> list[int]:
    """Every unpaid levy year the row's tax source blocks LIST, oldest first: the union across the
    live-roll blocks when one lists years (_LIVE_ROLL_BLOCKS), else across every tax source block
    (a merged row's blocks describe the same parcel's bills). [] when no block lists years. PTS Cloud
    bills count by their levy year (ptscloud_levy_year), an ArcGIS unpaid-bill row by its own."""
    if not isinstance(raw, dict):
        return []
    def listed(v) -> set[int]:
        return {y for y in (_cal.levy_year(x) for x in v) if y is not None} if isinstance(v, list) else set()

    live: set[int] = set()
    years: set[int] = set()
    for name, blk in raw.items():
        if not isinstance(blk, dict):
            continue
        layer_year = _unpaid_bill_layer_year(name, blk)
        if layer_year is not None:
            years.add(layer_year)
            continue
        if not _is_tax_source_block(name):
            continue
        if name == _PTS and isinstance(blk.get("by_year"), list) and blk["by_year"]:
            got = {y for y in (ptscloud_levy_year(b) for b in blk["by_year"]) if y is not None}
            years |= got
            live |= got
            continue
        got: set[int] = set()
        for k in _UNPAID_YEAR_LIST_KEYS:
            got |= listed(blk.get(k))
        late, every = listed(blk.get("years_unpaid")), listed(blk.get("all_unpaid_years"))
        if late and every and not late <= every:
            # all_unpaid_years is a superset of years_unpaid within one read; when it is not, the
            # block merged two reads (126 qpaybill_roll blocks on the 10/7 board). years_unpaid is
            # what balance_owed was summed over, so it stands, plus any newer year from the other.
            got = late | {y for y in every if y > max(late)}
        years |= got
        if name in _LIVE_ROLL_BLOCKS:
            live |= got
    return sorted(live or years)


def _amounts_by_year(raw: dict) -> dict[int, float]:
    """The unpaid amount per levy year, where a source block states it (multi_year per_year, or a
    per-bill list). Blocks overlap on a merged row, so the largest figure per year is kept."""
    out: dict[int, float] = {}

    def put(y, amt):
        y, amt = _cal.levy_year(y), _money(amt)
        if y is not None and amt:
            out[y] = max(out.get(y, 0.0), amt)

    for name, blk in raw.items():
        if not isinstance(blk, dict) or not _is_tax_source_block(name):
            continue
        per = blk.get("per_year")
        if isinstance(per, dict):
            for y, amt in per.items():
                put(y, amt)
        for lk in _BILL_LIST_KEYS:
            bills = blk.get(lk)
            if not isinstance(bills, list):
                continue
            for b in bills:
                if not isinstance(b, dict):
                    continue
                y = next((b.get(k) for k in _BILL_YEAR_KEYS if b.get(k)), None)
                amt = next((b.get(k) for k in _BILL_AMOUNT_KEYS if _money(b.get(k))), None)
                put(y, amt)
    return out


_SCALAR_YEAR_KEYS = ("year", "tax_year", "levy_year", "bill_year", "taxyear", "latest_year")


def _source_names_year(raw: dict, year: int) -> bool:
    """A tax source block on the row states `year` in a scalar year key."""
    for name, blk in raw.items():
        if isinstance(blk, dict) and (_is_tax_source_block(name) or _unpaid_bill_layer_year(name, blk)):
            if any(_cal.levy_year(blk.get(k)) == year for k in _SCALAR_YEAR_KEYS):
                return True
    return False


def tax_year_status(raw: dict, state: Optional[str], county: Optional[str],
                    today: Optional[date] = None) -> Optional[dict]:
    """How many levy years the row's tax record shows as LATE, and which unpaid bills are not late
    yet. None when nothing on the row names a levy year or a count.

      years_delinquent    levy years past their delinquent date AND unpaid (tax_calendar)
      unpaid_bill_years   the raw count of unpaid levy years, the not-yet-late one included
                          (None when only a single year is known)
      not_yet_late_years  the unpaid levy years that are not late yet
      not_yet_late_amount the part of the tax_owed balance that is those bills, when the data
                          says (the whole balance when nothing else is unpaid); else absent
      basis               year_list (a source lists the unpaid years), stated_count (a count
                          and the newest year only), single_year (one year: delinquent since then,
                          tax_calendar.years_since_levy)
      year_from_source    single_year only: a source block names that year (else only tax_owed)
    """
    if not isinstance(raw, dict):
        return None
    today = today or date.today()

    def late(y: int) -> bool:
        return _cal.levy_year_is_delinquent(y, state, county, today)

    to = raw.get("tax_owed") if isinstance(raw.get("tax_owed"), dict) else {}
    years = unpaid_levy_years(raw)
    if years:
        done = [y for y in years if late(y)]
        out = {"basis": "year_list", "unpaid_bill_years": len(years), "years_delinquent": len(done),
               "delinquent_years": done, "not_yet_late_years": [y for y in years if not late(y)]}
    else:
        # the newest year: a PTS Cloud roll's own levy year beats its TAX_YEAR label on tax_owed
        pts_year = ptscloud_levy_year(raw.get(_PTS))
        top_year = pts_year or _cal.levy_year(to.get("year"))
        stamped = to.get("years_basis") in ("year_list", "stated_count")
        # the raw count: this module's own stamp, or a count an older run promoted as stated
        n = to.get("unpaid_bill_years") if stamped else to.get("years_delinquent")
        n = int(n) if isinstance(n, (int, float)) and not isinstance(n, bool) and n > 0 else None
        if n:
            prior = to.get("not_yet_late_years") if stamped else None
            if isinstance(prior, list):
                pending = [y for y in (_cal.levy_year(p) for p in prior) if y is not None and not late(y)]
            else:
                pending = [top_year] if top_year is not None and not late(top_year) else []
            out = {"basis": "stated_count", "unpaid_bill_years": n,
                   "years_delinquent": max(0, n - len(pending)), "not_yet_late_years": pending}
        else:
            y = top_year
            if y is None or y > today.year + 1:
                return None
            if late(y):
                out = {"basis": "single_year", "unpaid_bill_years": None,
                       "years_delinquent": _cal.years_since_levy(y, state, county, today),
                       "not_yet_late_years": []}
            else:
                out = {"basis": "single_year", "unpaid_bill_years": 1, "years_delinquent": 0,
                       "not_yet_late_years": [y]}
            # whether a source block names the year, or only tax_owed does (a year an older run
            # carried forward from a block that is gone, or read off an unrelated block)
            out["year_from_source"] = bool(pts_year) or _source_names_year(raw, y)
    pending = out["not_yet_late_years"]
    if pending:
        bal = _money(to.get("balance"))
        amounts = _amounts_by_year(raw)
        if out["years_delinquent"] == 0 and bal:
            out["not_yet_late_amount"] = round(bal, 2)
        elif amounts and all(y in amounts for y in pending):
            out["not_yet_late_amount"] = round(sum(amounts[y] for y in pending), 2)
    return out


#: A row whose tax_owed is not a county PROPERTY-tax balance: the verification registry's other
#: liens (_tax_common.NON_PROPERTY_TAX_SOURCES: SC DEW and DOR liens, LiensNC, eCourts judgments)
#: and the UST registries (their tax_owed is a merged-in SC state lien). Matched on the row's
#: source and on tax_owed's own source.
_NOT_PROPERTY_TAX_MARKS = ("sc_dew_lien_registry", "sc_state_tax_lien", "ust_registry",
                           "ust_incidents", "liensnc", "ecourts")
#: Sources that emit a parcel only when one of its levy years is already late, so a row from one (or
#: merged with one, raw['also_seen_in']) is never "only a current bill" whatever is left of its year
#: list: multi_year_delinquent_tax drops a parcel with no matured year (its build_listing), and 57
#: buncombe_elderly rows of the 10/7 board merged with it read only "2026" once its block was gone;
#: buncombe_delinquent_tax is the county's advertisement of delinquent taxes (G.S. 105-369).
_PAST_DUE_ONLY_SOURCES = frozenset({"counties.multi_year_delinquent_tax",
                                    "counties_nc.buncombe_delinquent_tax"})


def property_tax_balance(raw: dict, source: Optional[str] = None) -> Optional[float]:
    """raw['tax_owed']'s balance when it is a county property-tax delinquency (kind delinquent_tax,
    not another lien, see _NOT_PROPERTY_TAX_MARKS); else None."""
    to = raw.get("tax_owed") if isinstance(raw, dict) else None
    if not isinstance(to, dict) or to.get("kind") != "delinquent_tax":
        return None
    srcs = (str(source or ""), str(to.get("source") or ""))
    if any(m in s for s in srcs for m in _NOT_PROPERTY_TAX_MARKS) or srcs[0] in NON_PROPERTY_TAX_SOURCES:
        return None
    return _money(to.get("balance"))


def _past_due_source(raw: dict, source: Optional[str]) -> bool:
    """The row, its tax_owed, or a source merged into it (raw['also_seen_in']) is one of
    _PAST_DUE_ONLY_SOURCES."""
    to = raw.get("tax_owed") if isinstance(raw.get("tax_owed"), dict) else {}
    seen = raw.get("also_seen_in") if isinstance(raw.get("also_seen_in"), list) else []
    srcs = {source, to.get("source")} | {e.get("source") for e in seen if isinstance(e, dict)}
    return bool(srcs & _PAST_DUE_ONLY_SOURCES)


def tax_not_yet_late(raw: dict, state: Optional[str], county: Optional[str],
                     source: Optional[str] = None, today: Optional[date] = None) -> bool:
    """True when the row's ONLY unpaid property-tax bill is one that is not late yet (the current
    levy, tax_calendar): such a row earns no tax credit (distress_score, lead_signals, fullmer_rank,
    the amount_owed promotion) and stays on the board as context with raw['tax_not_yet_late'].
    A row with an older unpaid year as well keeps its credit.

    It takes evidence, not the absence of it: the not-late year has to come from a source block
    (a year list, a stated count, or a block naming the year), not only from tax_owed.year, and
    nothing on the row may show a late bill (a past-due source, a PTS Cloud roll charging interest,
    which only a bill past its delinquent date does)."""
    if not isinstance(raw, dict) or _past_due_source(raw, source):
        return False
    to = raw.get("tax_owed")
    pts = raw.get(_PTS)
    if isinstance(to, dict) and _money(to.get("balance")):
        if property_tax_balance(raw, source) is None:
            return False
    elif not isinstance(pts, dict):
        return False
    if isinstance(pts, dict) and _money(pts.get("interest_due")):
        return False
    st = tax_year_status(raw, state, county, today)
    if not st or st["years_delinquent"] != 0 or not st["not_yet_late_years"]:
        return False
    return st["basis"] != "single_year" or bool(st.get("year_from_source"))


def _years_fields(status: Optional[dict]) -> dict:
    """The year fields raw['tax_owed'] carries. Only from a source that lists the years or states a
    count; a single stated year is left to enrichment_tax_aging, as before (never invented here)."""
    if not status or status["basis"] not in ("year_list", "stated_count"):
        return {}
    out = {"years_delinquent": status["years_delinquent"],
           "unpaid_bill_years": status["unpaid_bill_years"],
           "not_yet_late_years": status["not_yet_late_years"],
           "years_basis": status["basis"]}
    if "not_yet_late_amount" in status:
        out["not_yet_late_amount"] = status["not_yet_late_amount"]
    return out


def enrich_tax_owed(listings: Iterable[Listing], today: Optional[date] = None) -> dict:
    if os.environ.get("FORECLOSURE_TAX_OWED", "1") == "0":
        return {"stamped": 0, "skipped": "disabled"}

    listings = list(listings)
    stamped = 0
    index: dict[tuple, dict] = {}
    today = today or date.today()

    # Pass 1 — normalize each tax lead's own amount.
    for li in listings:
        bal, kind, year = _extract(li)
        if bal is None:
            continue
        # Preserve existing year if _extract couldn't find one (source sub-dict stripped on re-run)
        if year is None and isinstance(li.raw, dict):
            prev = li.raw.get("tax_owed")
            if isinstance(prev, dict) and prev.get("year"):
                year = prev["year"]
        if not isinstance(li.raw, dict):
            li.raw = {}
        # Years delinquent = LATE unpaid levy years (tax_calendar), read before the old tax_owed is
        # replaced: a row whose source block is gone keeps the count an earlier run stamped.
        prev = li.raw.get("tax_owed") if isinstance(li.raw.get("tax_owed"), dict) else {}
        status = tax_year_status({**li.raw, "tax_owed": {**prev, "balance": bal, "year": year}},
                                 li.state, li.county, today)
        years = _years_fields(status)
        li.raw["tax_owed"] = {
            "balance": bal, "kind": kind, "source": li.source,
            "year": year, "basis": "own_record", **years,
        }
        stamped += 1
        if (li.parcel_id or "").strip():
            entry = {"balance": bal, "kind": kind, "source": li.source, "year": year, **years}
            index.setdefault(_county_county_key(li), entry)

    # Pass 2 — cross-reference onto same-parcel leads from other sources.
    xref = 0
    for li in listings:
        if not isinstance(li.raw, dict) or li.raw.get("tax_owed"):
            continue
        if not (li.parcel_id or "").strip():
            continue
        hit = index.get(_county_county_key(li))
        if hit:
            li.raw["tax_owed"] = {**hit, "basis": "parcel_cross_ref"}
            xref += 1

    log.info("tax_owed.done", stamped=stamped, cross_referenced=xref,
             parcels_indexed=len(index))
    return {"stamped": stamped, "cross_referenced": xref, "parcels_indexed": len(index)}
