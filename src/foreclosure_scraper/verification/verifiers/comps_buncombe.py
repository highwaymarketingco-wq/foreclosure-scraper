"""comps, Buncombe County NC: do the board's sold comps match the county's own record of those
sales? A DRIFT DETECTOR, the lowest-priority verifier in the spec: the comps were 93.7%
accurate when validated (docs/validation_2026-10-03/, 133 of 142 comp entries on 50 random
Buncombe properties; the one confirmed real error was an external MLS miskey, 140 Old Leicester
Rd: HomeHarvest $140,000, the county $160,000 = 320 stamps x $500). This keeps checking so a
regression in HomeHarvest, the comp matcher or the county correction shows up as a verdict.

THE SOURCE. Buncombe's parcel layer, property_bc_dis/MapServer/1 (anonymous ArcGIS, no login,
no CAPTCHA): the parcel's latest deed, SalePrice / DeedDate / Stamps (NC excise tax: $1 per $500
of consideration, so Stamps x 500 is the recorded price to the next $500). Queried exactly as
the pipeline's own county correction queries it (enrichment_gis_sale_crosscheck, d16fb8be): the
same layer, `parse_address` / `street_where` / `narrow_candidates` / `_disambiguate`, the same
tolerances (PRICE_DISAGREEMENT_TOLERANCE 8%, DATE_TOLERANCE_DAYS 45) and the same columns
(situs and sale only: never owner, CareOf, or Address/CityName, which are the owner's MAILING
address). One query per distinct comp address per sweep run (a per-run cache keyed by the
sweep's client): the 8,957 Buncombe rows with comps on the 10/5 board name only 1,127 distinct
comp addresses (6 Weaver St is a comp on 742 rows). A street spelled differently from the
county's ("Hemlock Rd" is "HEMLOCK DR" there) gets one broader retry on the street's longest
word before the comp counts as not found.

WHICH ROWS (applies). NC Buncombe rows whose raw carries sold comps (`raw.comps`, a non-empty
list). The published board keeps comps in the lazy-detail sidecar, so the module declares
DETAIL_KEYS = ("comps",) and the sweep merges them in (board_stream.iter_board_rows_with_detail).

PER COMP (status in the evidence):
  match        the comp's parcel is identified, its latest deed is within 45 days of the comp's
               sold_date (the SAME closing), and the county price is within 8% of the board's.
  mismatch     the same, but the prices disagree by more than 8% and the board carries no
               county correction for it (`sold_price_homeharvest` absent), and the deed conveys
               this one parcel (a DeedBook/DeedPage count; a deed over several parcels records
               their combined price on each: 117 Lookout Rd, $205,000 on 3 parcels vs the MLS
               $135,000). Only a parcel identified by its street (house number + street,
               narrowed by the situs columns) can mismatch: a parcel picked among several by
               deed date alone, or found only by the broad retry, can match (date AND price
               agree) but never refute.
  not_found    the comp sale is not on the county's record at all: no parcel at the address
               (the street query and the broad retry both empty), AND no parcel anywhere in the
               county has a deed within 1% of the comp's price within 45 days of its date, for
               a sale at least 90 days old (the layer lags recent deeds) in a ZIP wholly in
               Buncombe (28704 Arden, 28732 Fletcher, 28787 Weaverville reach into Henderson /
               Madison). An address alone is not enough: 12 Killian Ln ($95,000, 2026-04-23)
               has no parcel, but its sale is on record as 3 "99999 TATOOINE LN" lots.
  unresolvable no single parcel ('78 and 80 Taylor St', no house number, the placeholder 99999
               of an unaddressed lot), a missing address whose sale IS on record elsewhere, a
               not-found comp that is recent or in a border ZIP, several candidates
               the deed date cannot separate, the latest deed is a LATER sale (a resale: the
               layer only holds the latest) or the claimed sale is not recorded within 45 days
               (the layer can lag a deed: 205 Linden St), a $0 / unpriced deed, no sold_date, a
               deed over several parcels, or a corrected comp the county has changed since.
  lookup_failed the query failed (network, an ArcGIS error).

VERDICT for the row's comp set (core.py's meanings):
  refuted      at least one comp is a mismatch or not_found: a comp price the county's record
               contradicts and the pipeline did not correct, or a comp sale with no parcel.
  stale        nothing refuted, but every dated comp sold more than FRESHNESS_WINDOW_DAYS (180,
               the sold pool's past_days in enrichment_comps) before today: the set WAS a
               recent-sales set and the pipeline would not pick any of it today.
  confirmed    nothing refuted or stale, and every resolvable comp (at least one) matches.
  unconfirmed  no comp resolvable, a lookup failed (and nothing refuted), or no comps.

GOVERNS = () (informational). A refuted comp set says the ARV input was off, not that the
property's distress was: no scorer signal in distress_score._collect, _LISTING_TYPE_SIGNAL or the
lead-signal facets is computed from comps. Comps reach the score only through calc's ARV -> the
equity band of the tier gate, and the verification read side (core.suppressed_scorer_signals)
can only remove named distress signals; it has no way to say "distrust this ARV", and inventing
one (an arv_flag, an equity retraction) would be a new scoring effect. The verdict, its badge
(core.verdict_badges -> {"comps": ...}) and the per-comp deltas are for a reader, and for
measuring drift run over run.

TTL 30 days, retry 14: a deed changes rarely and this is a drift check.

EVIDENCE (public_evidence(): a whitelist; the ledger is in a PUBLIC repo). Comps are sales, so
addresses and prices only: per comp the address, the board price, the county price, the delta
and delta %, the claimed sold date, the deed date and the gap, the stamps and the price they
imply, the county PIN, how the parcel was identified (match basis), the status and its reason.
No buyer, seller or owner name, no mailing address; the layer's owner columns are never
requested. ROW_SUMMARY_EXCLUDE drops the subject's owner_name from the ledger row summary.
"""
from __future__ import annotations

import hashlib
import json
import weakref
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from ... import enrichment_gis_sale_crosscheck as xc
from ..core import VerificationResult, result

SIGNAL = "comps"
VERSION = "v2"         # v2 (2026-10-06, same night): not_found refutes only when no deed of that
                       # price was recorded near that date anywhere in the county (12 Killian Ln:
                       # a new address, the sale is on record as 3 "99999 TATOOINE LN" lots);
                       # placeholder house numbers (99999, 0) are unresolvable
TTL_DAYS = 30
RETRY_DAYS = 14
SOURCE = "Buncombe County parcel layer (gis.buncombecounty.org property_bc_dis)"
GOVERNS: tuple[str, ...] = ()
DETAIL_KEYS = ("comps",)
ROW_SUMMARY_EXCLUDE = ("owner_name",)

#: enrichment_comps' sold pool: scrape_property(listing_type="sold", past_days=180),
#: SOLD_WINDOW_MONTHS = 6.0 (a test pins the two equal).
FRESHNESS_WINDOW_DAYS = 180
PRICE_TOLERANCE = xc.PRICE_DISAGREEMENT_TOLERANCE
DATE_TOLERANCE_DAYS = xc.DATE_TOLERANCE_DAYS
#: a comp sale this recent may not be on the layer yet (205 Linden St: a 2026-09-01 deed in the
#: county's record-card history was not on the layer on 10/4), so its absence decides nothing
RECORDING_LAG_DAYS = 90
#: the county-wide search for a not-found comp's sale: a deed within this fraction of its price
SALE_SEARCH_PRICE_BAND = 0.01
LAYER_QUERY = xc.BUNCOMBE_PARCELS
LAYER = LAYER_QUERY.rsplit("/query", 1)[0]
RESULT_COUNT = "10"

#: ZIPs whose area lies wholly in Buncombe County. A comp not found on the county layer refutes
#: only in one of these; 28704 (Arden), 28732 (Fletcher) and 28787 (Weaverville) reach into
#: Henderson / Madison, so a miss there may be another county's parcel.
BUNCOMBE_ONLY_ZIPS = frozenset({
    "28701", "28709", "28711", "28715", "28728", "28730", "28748", "28757", "28770", "28776",
    "28778", "28801", "28802", "28803", "28804", "28805", "28806", "28810", "28813", "28814",
    "28815", "28816"})

_NAME = __name__.rsplit(".", 1)[-1]

#: per-comp evidence fields that may be published
_COMP_FIELDS = ("address", "status", "reason", "board_price", "county_price", "delta",
                "delta_pct", "claimed_sold_date", "deed_date", "date_gap_days", "county_stamps",
                "stamps_price", "county_pin", "match_basis", "candidates",
                "county_correction_applied", "homeharvest_price", "zip", "deed",
                "deed_parcels", "county_sales_matching", "error")
_TOP_FIELDS = ("layer", "as_of", "price_tolerance_pct", "date_tolerance_days",
               "freshness_window_days", "comp_set_id", "comps_total", "comps_matched",
               "comps_mismatched", "comps_not_found", "comps_unresolvable",
               "comps_lookup_failed", "comps_outside_window", "newest_comp_sold",
               "window_ends", "reason", "requests_this_row")


# ---------------------------------------------------------------------------
# which rows
# ---------------------------------------------------------------------------

def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def comps_of(row: Any) -> list[dict]:
    raw = _get(row, "raw")
    comps = raw.get("comps") if isinstance(raw, dict) else None
    if not isinstance(comps, list):
        return []
    return [c for c in comps if isinstance(c, dict)]


def applies(row: dict) -> bool:
    if str(_get(row, "state") or "").strip().upper() != "NC":
        return False
    county = str(_get(row, "county") or "").strip().lower()
    if county.endswith(" county"):
        county = county[: -len(" county")]
    if county != "buncombe":
        return False
    return any(c.get("address") for c in comps_of(row))


# ---------------------------------------------------------------------------
# the layer, one query per distinct WHERE per sweep run
# ---------------------------------------------------------------------------

def query_url(where: str) -> str:
    """The helper's query, as a URL (same parameters, same order)."""
    return LAYER_QUERY + "?" + urlencode({"where": where, "outFields": xc._BUNCOMBE_FIELDS,
                                          "returnGeometry": "false", "f": "json",
                                          "resultRecordCount": RESULT_COUNT})


# client -> {where: ("ok", [attrs]) | ("error", msg)}; dies with the sweep's client.
_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _cache(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {})
    except TypeError:                       # not weak-referenceable: no sharing
        return {}


def count_url(where: str) -> str:
    """The helper's deed-parcel count query (_deed_parcel_count), as a URL."""
    return LAYER_QUERY + "?" + urlencode({"where": where, "returnCountOnly": "true",
                                          "f": "json"})


async def _query(client: Any, where: str, counter: list, *, count: bool = False
                 ) -> tuple[str, Any]:
    """("ok", [attribute dicts]) or, count=True, ("ok", n); ("error", message) on a failure.
    One request per distinct query per sweep run."""
    cache = _cache(client)
    key = ("count:" if count else "rows:") + where
    if key in cache:
        return cache[key]
    counter[0] += 1
    try:
        data = await client.get_json(count_url(where) if count else query_url(where))
        if not isinstance(data, dict) or data.get("error"):
            err = (data or {}).get("error") if isinstance(data, dict) else type(data).__name__
            out: tuple[str, Any] = ("error", f"ArcGIS error: {str(err)[:160]}")
        elif count:
            out = ("ok", int(data["count"]))
        else:
            out = ("ok", [f.get("attributes") or {} for f in (data.get("features") or [])
                          if isinstance(f, dict)])
    except Exception as exc:  # noqa: BLE001 - the comp answers lookup_failed
        out = ("error", f"{type(exc).__name__}: {str(exc)[:160]}")
    cache[key] = out
    return out


# ---------------------------------------------------------------------------
# one comp
# ---------------------------------------------------------------------------

def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _zip(comp: dict) -> Optional[str]:
    z = "".join(ch for ch in str(comp.get("zip") or "") if ch.isdigit())[:5]
    return z if len(z) == 5 else None


def _done(view: dict, status: str, reason: Optional[str] = None) -> dict:
    view["status"] = status
    if reason:
        view["reason"] = reason
    return view


def sale_where(claimed: date, price: float) -> str:
    """Every parcel whose latest deed is within DATE_TOLERANCE_DAYS of `claimed` and within
    SALE_SEARCH_PRICE_BAND of `price`, county-wide (DeedDate is a YYYYMMDD string)."""
    lo = (claimed - timedelta(days=DATE_TOLERANCE_DAYS)).strftime("%Y%m%d")
    hi = (claimed + timedelta(days=DATE_TOLERANCE_DAYS)).strftime("%Y%m%d")
    plo = int(price * (1 - SALE_SEARCH_PRICE_BAND))
    phi = int(price * (1 + SALE_SEARCH_PRICE_BAND)) + 1
    return (f"DeedDate >= '{lo}' AND DeedDate <= '{hi}' AND SalePrice >= {plo} "
            f"AND SalePrice <= {phi}")


async def _not_found(view: dict, claimed: Optional[date], price: Optional[float], client: Any,
                     counter: list, today: date) -> dict:
    """No parcel at the comp's address. That alone does not make the comp a sale that never
    happened: a newly assigned address is not on the layer (12 Killian Ln, $95,000 on
    2026-04-23, is on record as the 3 "99999 TATOOINE LN" lots of deed 6586/1409), and the layer
    lags recent deeds. So the comp is not_found (refuting) only when its ZIP is wholly in
    Buncombe, its sale is at least RECORDING_LAG_DAYS old, and NO parcel in the county has a
    deed within 1% of its price within DATE_TOLERANCE_DAYS of its date."""
    z = view.get("zip")
    if z not in BUNCOMBE_ONLY_ZIPS:
        return _done(view, "unresolvable", "not_found_border_zip" if z else "not_found_no_zip")
    if claimed is None or price is None:
        return _done(view, "unresolvable", "not_found_undated")
    if (today - claimed).days < RECORDING_LAG_DAYS:
        return _done(view, "unresolvable", "not_found_recent_sale")
    st, n = await _query(client, sale_where(claimed, price), counter, count=True)
    if st != "ok":
        view["error"] = n
        return _done(view, "lookup_failed", "sale_search_error")
    view["county_sales_matching"] = n
    if n:
        return _done(view, "unresolvable", "sale_on_record_at_another_address")
    return _done(view, "not_found", "no_parcel_and_no_such_sale")


async def check_comp(comp: dict, client: Any, counter: list, today: date) -> dict:
    addr = str(comp.get("address") or "").split(",")[0].strip()
    claimed = xc.parse_any_date(comp.get("sold_date"))
    board_price = _num(comp.get("sold_price"))
    view: dict[str, Any] = {"address": addr or None, "board_price": board_price,
                            "claimed_sold_date": claimed.isoformat() if claimed else None,
                            "zip": _zip(comp)}
    corrected = comp.get("sold_price_homeharvest") is not None
    if corrected:
        view["county_correction_applied"] = True
        view["homeharvest_price"] = _num(comp.get("sold_price_homeharvest"))
    if not addr:
        return _done(view, "unresolvable", "no_address")
    parts = xc.parse_address(addr)
    if parts is None:
        if xc._MULTI_PARCEL_RE.match(addr):
            return _done(view, "unresolvable", "multi_parcel_address")
        m = xc._HOUSE_RE.match(addr)
        if m and xc.is_placeholder_house(m.group(1)):
            return _done(view, "unresolvable", "placeholder_house_number")
        return _done(view, "unresolvable", "no_house_number")

    where = xc.street_where(parts)
    st, feats = await _query(client, where, counter)
    if st != "ok":
        view["error"] = feats
        return _done(view, "lookup_failed", "lookup_error")
    identified = "street"
    if not feats:
        broad = xc.street_where(parts, broad=True)
        if broad != where:
            st, feats = await _query(client, broad, counter)
            if st != "ok":
                view["error"] = feats
                return _done(view, "lookup_failed", "lookup_error")
            identified = "street_broad"
    if not feats:
        return await _not_found(view, claimed, board_price, client, counter, today)

    cands = xc.narrow_candidates(feats, parts)
    if len(cands) > 1:
        rec = xc._disambiguate(cands, claimed)
        view["candidates"] = len(cands)
        if rec is None:
            return _done(view, "unresolvable", "ambiguous_parcel")
        identified += "+date_pin"
    else:
        rec = cands[0]

    county_price = _num(rec.get("SalePrice"))
    deed = xc.parse_any_date(xc._deed_date_iso(rec.get("DeedDate")))
    stamps = _num(rec.get("Stamps"))
    book, page = str(rec.get("DeedBook") or "").strip(), str(rec.get("DeedPage") or "").strip()
    view.update(county_pin=str(rec.get("pinnum") or "") or None, county_price=county_price,
                deed_date=deed.isoformat() if deed else None, county_stamps=stamps,
                stamps_price=round(stamps * xc.NC_STAMP_PER_DOLLARS) if stamps else None,
                deed=f"{book}/{page}" if book and page else None)
    if deed is None or claimed is None:
        return _done(view, "unresolvable", "no_date")
    gap = (deed - claimed).days
    view["date_gap_days"] = gap
    if abs(gap) > DATE_TOLERANCE_DAYS:
        if identified.startswith("street_broad"):
            return _done(view, "unresolvable", "no_exact_street_match")
        return _done(view, "unresolvable",
                     "later_sale_on_record" if gap > 0 else "claimed_sale_not_recorded")
    if county_price is None:
        return _done(view, "unresolvable", "no_price_on_record")
    if board_price is None:
        return _done(view, "unresolvable", "no_board_price")

    delta = county_price - board_price
    pct = abs(delta) / county_price
    view.update(delta=round(delta, 2), delta_pct=round(100.0 * delta / county_price, 1))
    basis = [identified, "date", "price"]
    if stamps and abs(stamps * xc.NC_STAMP_PER_DOLLARS - county_price) < xc.NC_STAMP_PER_DOLLARS:
        basis.append("stamps")
    if corrected:
        basis.append("county_corrected")
    view["match_basis"] = "+".join(basis)
    if pct <= PRICE_TOLERANCE:
        return _done(view, "match")
    if corrected:
        return _done(view, "unresolvable", "county_changed_since_correction")
    if identified != "street":
        return _done(view, "unresolvable", "price_differs_identity_by_date_only")
    # A deed that conveys several parcels records their combined price on each (xc.deed_where):
    # not this comp's price. One count request, only for a prospective mismatch.
    dw = xc.deed_where(rec)
    if not dw:
        return _done(view, "unresolvable", "price_differs_deed_unidentified")
    st, n = await _query(client, dw, counter, count=True)
    if st != "ok":
        view["error"] = n
        return _done(view, "lookup_failed", "deed_count_error")
    view["deed_parcels"] = n
    if n > 1:
        return _done(view, "unresolvable", "deed_covers_several_parcels")
    return _done(view, "mismatch", "price_differs_uncorrected")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def comp_set_id(comps: list[dict]) -> str:
    """A short id of the comp set checked (address, price, date), so a later run can tell
    whether the board's set changed under the verdict."""
    key = sorted((str(c.get("address") or ""), str(c.get("sold_price") or ""),
                  str(c.get("sold_date") or "")[:10]) for c in comps)
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]


def public_comp(view: dict) -> dict:
    return {k: view[k] for k in _COMP_FIELDS if view.get(k) is not None}


def public_evidence(ev: dict) -> dict:
    """The evidence a verdict publishes: a whitelist (the ledger is in a PUBLIC repo)."""
    out = {k: ev[k] for k in _TOP_FIELDS if ev.get(k) is not None}
    out["comps"] = [public_comp(v) for v in ev.get("comps") or []]
    return out


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(ev), source=SOURCE, version=VERSION,
                  verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    comps = comps_of(row)
    ev: dict[str, Any] = {"layer": LAYER, "as_of": today.isoformat(),
                          "price_tolerance_pct": round(100 * PRICE_TOLERANCE, 1),
                          "date_tolerance_days": DATE_TOLERANCE_DAYS,
                          "freshness_window_days": FRESHNESS_WINDOW_DAYS,
                          "comps_total": len(comps)}
    if not comps:
        ev["reason"] = "no_comps"
        return _res("unconfirmed", ev)
    ev["comp_set_id"] = comp_set_id(comps)

    counter = [0]
    views = [await check_comp(c, client, counter, today) for c in comps]
    ev["comps"] = views
    ev["requests_this_row"] = counter[0]
    by = {s: [v for v in views if v["status"] == s]
          for s in ("match", "mismatch", "not_found", "unresolvable", "lookup_failed")}
    ev.update(comps_matched=len(by["match"]), comps_mismatched=len(by["mismatch"]),
              comps_not_found=len(by["not_found"]), comps_unresolvable=len(by["unresolvable"]),
              comps_lookup_failed=len(by["lookup_failed"]))

    sold = [d for d in (xc.parse_any_date(c.get("sold_date")) for c in comps) if d]
    cutoff = today - timedelta(days=FRESHNESS_WINDOW_DAYS)
    if sold:
        newest = max(sold)
        ev.update(newest_comp_sold=newest.isoformat(),
                  window_ends=(newest + timedelta(days=FRESHNESS_WINDOW_DAYS)).isoformat(),
                  comps_outside_window=sum(1 for d in sold if d < cutoff))

    if by["mismatch"] or by["not_found"]:
        why = []
        if by["mismatch"]:
            why.append("price_mismatch")
        if by["not_found"]:
            why.append("comp_not_on_county_record")
        ev["reason"] = "+".join(why)
        return _res("refuted", ev)
    if by["lookup_failed"]:
        ev["reason"] = "lookup_failed"
        return _res("unconfirmed", ev)
    if sold and max(sold) < cutoff:
        ev["reason"] = "comps_outside_freshness_window"
        return _res("stale", ev)
    if by["match"]:
        return _res("confirmed", ev)
    ev["reason"] = "no_comp_resolvable"
    return _res("unconfirmed", ev)
