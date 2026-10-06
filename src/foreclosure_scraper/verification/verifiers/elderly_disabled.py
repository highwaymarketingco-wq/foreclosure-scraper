"""elderly_disabled, Buncombe County NC: does the county record still show the statutory
elderly / disabled / blind / disabled-veteran property-tax relief on this parcel, for this owner?

Evolved from docs/validation_2026-10-02/scripts/validate_elderly_disabled_buncombe.py (FINDINGS.md
section 6: N=50 Buncombe elderly_disabled leads, 0% with a real prior-year tax delinquency; voter
status split 64% active, 26% inactive/removed/not-found, 10% ambiguous). That script checked the
leads' tax balance and voter status. This verifier checks the CLAIM itself (the exemption), and
records the voter status beside it as corroborating evidence only.

WHICH ROWS CARRY THE CLAIM (measured on the 2026-10-05 board with board_stream: 4,481 rows, all
but 5 in Buncombe, 4,399 Buncombe properties):
  * listing_type == "elderly_disabled" (3,898 rows, all counties_nc.buncombe_elderly: one bulk
    query of the county parcel layer, Exempt IN ('ELD','DIS','BLD','VET')), and
  * raw['gis_exempt'] {code ELD/DIS/BLD/VET} (enrichment_gis_attrs, or the scraper itself), which
    enrichment_life_events folds into raw['life_events'] as elderly_exemption /
    disabled_exemption / blind_exemption / disabled_veteran_exemption (4,481 rows), and
  * raw['tax_relief'] {kind elderly/disabled/blind} (enrichment_tax_relief, Buncombe's
    Property_2025 layer, or the gis_attrs bridge; not published on the board, present at
    scoring time on the VM).
They feed exactly two scorer names, which are this verifier's GOVERNS:
  * "elderly_disabled": the listing-type signal (distress_score._LISTING_TYPE_SIGNAL, LIFE_EVENT 8;
    on 3,907 of these rows' distress_stack), and
  * "senior_exemption": distress_score._collect's tax_relief path (LIFE_EVENT 8) and
    enrichment_lead_signals._facet_signals' life_events tag path (on 4,471 rows' signal_stack).
applies() covers Buncombe NC rows only: the county publishes the exemption code per parcel and
the tax bills per levy year (the endpoints below). The 5 rows elsewhere (Lincoln, New Hanover,
Catawba, Guilford, Rutherford) have no proven endpoint; enrichment_tax_relief documents that no
other NC county layer publishes a personal exemption.

ENDPOINTS (free, no login, no CAPTCHA, both live-checked 2026-10-06):
  https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query
      the county parcel layer the claim came from (counties_nc.buncombe_elderly.QUERY_URL), by
      pin='<10 digits>' as the scraper queries it (or pinnum for a full 15-character PIN): Exempt
      (ELD/DIS/BLD/VET), owner, TaxYear, UpdateDate, DeedDate. One JSON request.
  https://tax.buncombenc.gov/Parcel/Details/{pin} and /Bill/Details/{bill}
      only when today's record lacks the relief: the latest two levy bills' Exempt Value, to tell
      a relief that was on the record and is gone (stale) from one that never was (refuted).
      NC G.S. 105-277.1 excludes the greater of $25,000 or half the appraised value (live:
      $52,600 -> $26,300 exempt), G.S. 105-277.1C the first $45,000 for a disabled veteran.

VERDICTS (core.py's meanings):
  confirmed    today's layer shows ELD/DIS/BLD/VET on the parcel and the county owner is the
               board's owner (name_normalize match, or the same household: a surviving spouse).
               A changed code inside the set (ELD -> DIS) is still confirmed (`type_changed`).
  stale        the relief WAS on the record and is not today: (a) the owner changed since (a deed
               after the board first saw the row, or a different owner) and the relief is gone,
               or (b) same owner, relief removed. "Was" = a relief-shaped Exempt Value on one of
               the latest two levy bills, or the row is the buncombe_elderly scraper's own row
               (it read this layer, by this PIN, with the code on it).
  refuted      today's layer does not show it and neither of the latest two levy bills carried a
               relief-shaped exclusion (the claim was attached to a parcel whose record never
               showed it during the board's lifetime: a spatial-join neighbour, a wrong parcel).
  unconfirmed  no resolvable PIN; the layer unreadable or the PIN not in it (a retired PIN);
               several parcels under the board's 10-digit pin ("pin_shared_by_units": the
               units of a condominium all carry the building's pin, so the board row and its
               ledger key cannot say which unit; the owner's own unit, when found, is evidence);
               a billing record that ended before last year ("parcel_record_ended");
               the relief is on the parcel but for an owner who is not the board's
               ("owner_differs_relief_present": the property fact holds, the board's person does
               not; never suppresses); the bills unreadable when they were needed; or an Exempt
               Value that matches no relief formula ("exempt_value_unexplained").

VOTER STATUS (evidence only; it never changes the verdict and no scorer reads it; whether it
should weigh in is the owner's scoring-policy decision). The board owner's first person
(name_normalize.owner_last_first_middle; entities, trusts, estates and government owners are
skipped) is searched on vt.ncsbe.gov in Buncombe with BOTH "Registered" and "Removed or Denied"
(enrichment_nc_voter_lookup.nc_voter_search, a fresh client per search: the sticky-session
gotcha). Records whose LAST and FIRST equal the owner's are kept; one whose middle initial
conflicts with the owner's is dropped. Registered records decide first, as in FINDINGS: one ->
"active" / "inactive"; several -> the property's city picks one, else "ambiguous". No registered
record: any removed/denied record -> "removed", none -> "not_found". FINDINGS' "not_found" is
this "removed" + "not_found" (its search left out removed records).

PRIVACY (the ledger is a committed file in a public repo). Evidence keeps the verdict basis,
county, PIN, exemption codes and type, tax/levy years and exempt amounts, an owner-match
CATEGORY (never the county's owner name), a deed date only as the evidence of a transfer, and the
voter STATUS with a count of same-name records. Never a voter registration number, NCID, date of
birth, age, address, voting history, or any other person's name.

TTL 60 days (an exemption changes on a death, a sale or the annual application), retry 7.
"""
from __future__ import annotations

import html as _html
import re
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from ..core import VerificationResult, result
from .tax_lien_buncombe import (BILL_URL, PARCEL_URL, money, owner_match, parse_parcel_page,
                                pin_of)

SIGNAL = "elderly_disabled"
VERSION = "v2"         # v2 (2026-10-06): a 10-digit board pin is looked up as pin= (it can
                       # cover many condominium units: unconfirmed), not padded to the
                       # common-area pinnum; a billing record that ended is unconfirmed
TTL_DAYS = 60
RETRY_DAYS = 7
SOURCE = "gis.buncombecounty.org + tax.buncombenc.gov"
GOVERNS = ("elderly_disabled", "senior_exemption")

_NAME = __name__.rsplit(".", 1)[-1]

#: counties_nc.buncombe_elderly.QUERY_URL (a test pins them equal; not imported, so the registry
#: does not pull the scraper stack in)
LAYER_URL = "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query"
LAYER_FIELDS = "pinnum,pin,owner,TaxYear,UpdateDate,Exempt,AppraisedValue,DeedDate,Class"
ELDERLY_SOURCE = "counties_nc.buncombe_elderly"
VOTER_HOST = "vt.ncsbe.gov"
MAX_BILL_CHECKS = 2

#: the claim's codes and what each means (the scraper's _TAGS, enrichment_tax_relief's kinds)
CODE_TYPE = {"ELD": "elderly", "DIS": "disabled", "BLD": "blind", "VET": "disabled_veteran"}
_TAG_CODE = {"elderly_exemption": "ELD", "disabled_exemption": "DIS",
             "blind_exemption": "BLD", "disabled_veteran_exemption": "VET"}
_KIND_CODE = {"elderly": "ELD", "disabled": "DIS", "blind": "BLD"}
#: exclusion shapes that are this relief (relief_shape)
RELIEF_SHAPES = frozenset({"elderly_disabled_half", "elderly_disabled_25000", "veteran_45000",
                           "full_value"})


# ---------------------------------------------------------------------------
# which rows
# ---------------------------------------------------------------------------

def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def claimed_codes(row: dict) -> list[str]:
    """The exemption codes the board's row claims (gis_exempt, tax_relief, life_events tags)."""
    raw = _raw(row)
    codes: set[str] = set()
    ge = raw.get("gis_exempt")
    if isinstance(ge, dict):
        c = str(ge.get("code") or "").strip().upper()[:3]
        if c in CODE_TYPE:
            codes.add(c)
    tr = raw.get("tax_relief")
    if isinstance(tr, dict) and tr.get("kind") in _KIND_CODE:
        codes.add(_KIND_CODE[tr["kind"]])
    le = raw.get("life_events")
    if isinstance(le, (list, tuple)):
        codes.update(_TAG_CODE[t] for t in le if t in _TAG_CODE)
    return sorted(codes)


def carries_claim(row: dict) -> bool:
    return row.get("listing_type") == "elderly_disabled" or bool(claimed_codes(row))


def applies(row: dict) -> bool:
    return (str(row.get("state") or "").strip().upper() == "NC"
            and str(row.get("county") or "").strip().lower() == "buncombe"
            and carries_claim(row))


# ---------------------------------------------------------------------------
# parsing and rules (pure)
# ---------------------------------------------------------------------------

def layer_query(row: dict) -> Optional[tuple[str, str]]:
    """How to find the row's parcel on the layer: ("pinnum", <15 chars>) when the board's parcel id
    is a full PIN (15 digits, or a condominium unit "9648623059C0401"), else ("pin", <10 digits>)
    for the 10-digit form the buncombe_elderly scraper writes (its own query is pin='...').
    A 10-digit pin can be shared by many parcels: every unit of a condominium carries its own
    pinext under the building's pin (live 2026-10-06: 9627023924 = the 00000 common area plus
    ~230 C#### units), so it is never padded to pinnum <pin>00000 (that is the common area)."""
    an = re.sub(r"[^0-9A-Za-z]", "", str(row.get("parcel_id") or "")).upper()
    if re.fullmatch(r"\d{15}", an) or re.fullmatch(r"\d{10}[A-Z][0-9A-Z]{4}", an):
        return "pinnum", an
    p = pin_of(row)
    return ("pin", p[:10]) if p else None


def layer_url(field: str, value: str) -> str:
    return LAYER_URL + "?" + urlencode({"where": f"{field}='{value}'", "outFields": LAYER_FIELDS,
                                        "returnGeometry": "false", "f": "json"})


def _ymd(v: Any) -> Optional[str]:
    """'20240920' -> '2024-09-20'; junk -> None."""
    s = re.sub(r"\D", "", str(v or ""))
    if len(s) != 8:
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _tax_year(v: Any) -> Optional[int]:
    """The layer's TaxYear ('26') as a year (2026)."""
    s = re.sub(r"\D", "", str(v or ""))
    if len(s) == 2:
        return 2000 + int(s)
    if len(s) == 4:
        return int(s)
    return None


def parse_layer(data: Any) -> list[dict]:
    """Every parcel the layer's JSON holds (empty when none). Raises ValueError for an error
    payload or a response that is not a layer query result."""
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    if data.get("error"):
        raise ValueError(f"layer error: {str(data['error'])[:160]}")
    feats = data.get("features")
    if not isinstance(feats, list):
        raise ValueError("no features array")
    out = []
    for ft in feats:
        a = (ft or {}).get("attributes") or {}
        code = str(a.get("Exempt") or "").strip().upper()[:3]
        out.append({"pinnum": (a.get("pinnum") or "").strip() or None,
                    "owner": (a.get("owner") or "").strip() or None,
                    "code": code or None, "tax_year": _tax_year(a.get("TaxYear")),
                    "updated": _ymd(a.get("UpdateDate")), "deed_date": _ymd(a.get("DeedDate")),
                    "appraised": money(a.get("AppraisedValue"))})
    return out


_VALUE_ROW = re.compile(r"<th>\s*(Real Value|Deferred Value|Exempt Value|Total Value|Levy Year)"
                        r":?\s*</th>\s*<td[^>]*>\s*([^<]*?)\s*</td>", re.S)


def parse_bill_values(text: str) -> dict:
    """{'levy_year', 'real', 'deferred', 'exempt', 'total', 'readable'} from a Bill Details page."""
    vals = {k: _html.unescape(v) for k, v in _VALUE_ROW.findall(text)}
    yr = re.sub(r"\D", "", vals.get("Levy Year", ""))
    out = {"levy_year": int(yr) if len(yr) == 4 else None,
           "real": money(vals.get("Real Value")), "deferred": money(vals.get("Deferred Value")),
           "exempt": money(vals.get("Exempt Value")), "total": money(vals.get("Total Value"))}
    out["readable"] = out["exempt"] is not None and out["real"] is not None
    return out


def relief_shape(real: Optional[float], exempt: Optional[float]) -> Optional[str]:
    """Which exclusion an Exempt Value is: half the value or $25,000 (G.S. 105-277.1, elderly /
    disabled), $45,000 (G.S. 105-277.1C, disabled veteran), the whole value (a residence worth
    less than the exclusion), else 'other'. None when nothing is exempt."""
    if not exempt or exempt <= 0:
        return None
    if real and abs(exempt - real) < 1:
        return "full_value"
    if abs(exempt - 45000) < 1:
        return "veteran_45000"
    if abs(exempt - 25000) < 1:
        return "elderly_disabled_25000"
    if real:
        half = max(25000.0, real / 2.0)
        if abs(exempt - half) <= max(2.0, 0.005 * half):
            return "elderly_disabled_half"
    return "other"


def _first_seen(row: dict) -> Optional[str]:
    v = str(row.get("first_seen") or "")[:10]
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None


def scraped_from_layer(row: dict, pin: str) -> bool:
    """The row is the buncombe_elderly scraper's own read of this layer for THIS pin (its
    source_url is the layer query `pin='<10-digit pin>'`). A row that only carries the claim
    through a merge (raw['also_seen_in']) does not count: the 2026-10-06 sweep met HOT rows whose
    merged-in elderly claim belonged to another parcel."""
    if row.get("source") != ELDERLY_SOURCE:
        return False
    return f"pin%3D%27{pin[:10]}%27" in str(row.get("source_url") or "")


def owner_state(row: dict, layer: dict) -> dict:
    """{'owner_match', 'transferred_since', 'owner_changed'}: owner_match is tax_lien_buncombe's
    category (same / partial / different / None); transferred_since is a deed recorded after the
    board first saw the row; owner_changed is a different owner, or a partial one (a shared
    surname) with a deed since (an heir, a relative)."""
    om = owner_match(row.get("owner_name"), layer.get("owner"))
    fs, dd = _first_seen(row), layer.get("deed_date")
    moved = bool(fs and dd and dd > fs)
    return {"owner_match": om, "transferred_since": moved,
            "owner_changed": om == "different" or (om == "partial" and moved)}


# ---------------------------------------------------------------------------
# voter status (evidence only)
# ---------------------------------------------------------------------------

_REGISTERED = {"ACTIVE": "active", "INACTIVE": "inactive", "TEMPORARY": "active"}
_REMOVED = frozenset({"REMOVED", "DENIED"})


def voter_subject(owner: Optional[str]) -> Optional[tuple[str, str, str]]:
    """(LAST, FIRST, MIDDLE-INITIAL or '') of the owner's first person, or None for an entity /
    trust / estate / government owner or a name that does not split."""
    from ...name_normalize import classify_entity_type, owner_last_first_middle
    if classify_entity_type(owner) != "individual":
        return None
    return owner_last_first_middle(owner)


def classify_voters(rows: list, last: str, first: str, mid: str, city: Optional[str]) -> dict:
    """The status of (last, first[, middle]) among NCSBE result rows. Returns only a status, a
    count of same-name records, and how the pick was made; nothing about any person."""
    from ...name_normalize import owner_last_first_middle
    cands = []
    for r in rows or ():
        p = owner_last_first_middle(str((r or {}).get("FullName") or ""))
        if not p or p[0] != last or p[1] != first:
            continue
        csz = str(r.get("ResAddressCSZ") or "").upper()
        cands.append((p[2], str(r.get("StatusDesc") or "").strip().upper(),
                      csz.split(",")[0].strip()))
    out: dict[str, Any] = {"same_name": len(cands), "by": []}
    if mid:
        kept = [c for c in cands if not c[0] or c[0] == mid]
        if len(kept) < len(cands):
            out["by"].append("middle")
            out["middle_excluded"] = len(cands) - len(kept)
        cands = kept
    reg = [c for c in cands if c[1] in _REGISTERED]
    rem = [c for c in cands if c[1] in _REMOVED]
    if reg:
        if len(reg) > 1 and city:
            here = [c for c in reg if c[2] == city.strip().upper()]
            if len(here) == 1:
                reg = here
                out["by"].append("city")
        if len(reg) == 1:
            out["status"] = _REGISTERED[reg[0][1]]
        else:
            out["status"] = "ambiguous"
            out["matches"] = len(reg)
        return out
    out["status"] = "removed" if rem else "not_found"
    if len(rem) > 1:
        out["matches"] = len(rem)
    return out


async def voter_status(row: dict, client) -> dict:
    """Search the board owner on vt.ncsbe.gov (Buncombe); see the module docstring.
    `client.voter_search(first, last, county)` when the client has one (tests replay recorded
    searches that way); else a live search, only through a live Fetcher, paced by its per-host
    spacing and counted in its request stats."""
    subj = voter_subject(row.get("owner_name"))
    if not subj:
        from ...name_normalize import classify_entity_type
        kind = classify_entity_type(row.get("owner_name"))
        return {"status": "skipped",
                "reason": f"{kind}_owner" if kind not in ("individual", "unknown") else
                ("no_owner" if kind == "unknown" else "name_unsplittable")}
    last, first, mid = subj
    search = getattr(client, "voter_search", None)
    if search is None:
        from ..fetch import Fetcher
        if not isinstance(client, Fetcher):
            return {"status": "not_checked", "reason": "no_voter_client"}
        from ...enrichment_nc_voter_lookup import nc_voter_search

        async def _pace() -> None:
            await client._pace(VOTER_HOST)
            client.requests[VOTER_HOST] += 1

        async def search(f: str, la: str, county: str) -> dict:
            res = await nc_voter_search(f, la, county, include_registered=True,
                                        include_removed=True, pace=_pace)
            if not res.get("ok"):
                client.errors[VOTER_HOST] += 1
            elif client.capture_dir:
                # the sweep's --capture-dir (a local scratch dir, never committed: fixtures
                # are made from it pseudonymized)
                import json
                client._capture(f"https://{VOTER_HOST}/RegLkup/SearchResults?"
                                + urlencode({"first": f, "last": la, "county": county}),
                                json.dumps(res))
            return res
    try:
        res = await search(first.title(), last.title(), "BUNCOMBE")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"{type(exc).__name__}"}
    if not isinstance(res, dict) or not res.get("ok"):
        err = str((res or {}).get("error") or "search_failed") if isinstance(res, dict) else "bad_result"
        return {"status": "error", "error": err.split(":")[0][:60]}
    return classify_voters(res.get("rows") or [], last, first, mid, row.get("city"))


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def _res(verdict: str, evidence: dict) -> VerificationResult:
    return result(SIGNAL, verdict, evidence, source=SOURCE, version=VERSION, verifier=_NAME)


async def _bill_history(pin: str, client) -> dict:
    """The latest MAX_BILL_CHECKS levy bills' Exempt Value: {'bills': [...], 'error': str|None}."""
    url = PARCEL_URL.format(pin=pin)
    try:
        page = parse_parcel_page(await client.get_text(url))
    except Exception as exc:  # noqa: BLE001
        return {"bills": [], "error": f"parcel_page: {type(exc).__name__}"}
    if not page["bills"]:
        return {"bills": [], "error": "parcel_page: no_bills_parsed"}
    out = []
    for b in page["bills"][:MAX_BILL_CHECKS]:
        burl = BILL_URL.format(bill=b["bill"])
        try:
            v = parse_bill_values(await client.get_text(burl))
        except Exception as exc:  # noqa: BLE001
            out.append({"year": b["year"], "error": type(exc).__name__})
            continue
        if not v["readable"]:
            out.append({"year": b["year"], "error": "values_unreadable"})
            continue
        shape = relief_shape(v["real"], v["exempt"])
        rec = {"year": b["year"], "exempt_value": v["exempt"], "shape": shape}
        if v["deferred"]:
            rec["deferred_value"] = v["deferred"]
        out.append(rec)
    return {"bills": out, "error": None}


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    claimed = claimed_codes(row)
    q = layer_query(row)
    ev: dict[str, Any] = {"county": "Buncombe", "claimed_codes": claimed}
    if not q:
        return _res("unconfirmed", {**ev, "reason": "parcel_unresolvable",
                                    "parcel_id": row.get("parcel_id")})
    url = layer_url(*q)
    ev.update({q[0]: q[1], "url": url})
    try:
        feats = parse_layer(await client.get_json(url))
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", {**ev, "reason": "layer_unreadable",
                                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
    if not feats:
        return _res("unconfirmed", {**ev, "reason": "parcel_not_in_county_layer"})
    if len(feats) > 1:
        # several parcels under the board's 10-digit pin (condominium units): the board's
        # parcel id, and so the ledger key every unit's row shares, cannot say which unit the
        # claim is about, so no verdict here may speak for all of them. What the board owner's
        # own unit shows is kept as evidence.
        mine = [f for f in feats if owner_match(row.get("owner_name"), f["owner"]) == "same"]
        ev.update({"reason": "pin_shared_by_units", "parcels_under_pin": len(feats),
                   "coded_parcels_under_pin": sum(1 for f in feats if f["code"] in CODE_TYPE)})
        if len(mine) == 1:
            ev.update({"owner_unit": mine[0]["pinnum"], "owner_unit_code": mine[0]["code"]})
        return _res("unconfirmed", ev)

    layer = feats[0]
    pinnum = layer["pinnum"] or (q[1] if q[0] == "pinnum" else q[1] + "00000")
    ev["pinnum"] = pinnum
    code = layer["code"]
    own = owner_state(row, layer)
    ev.update({"county_code": code, "exemption_type": CODE_TYPE.get(code or ""),
               "tax_year": layer["tax_year"], "layer_updated": layer["updated"],
               "owner_match": own["owner_match"]})
    if own["owner_changed"] or own["transferred_since"]:
        ev["deed_date"] = layer["deed_date"]
        ev["transferred_since"] = own["transferred_since"]
    if code in CODE_TYPE and claimed and code not in claimed:
        ev["type_changed"] = True

    verdict: str
    if code in CODE_TYPE:
        if own["owner_changed"]:
            verdict, ev["reason"] = "unconfirmed", "owner_differs_relief_present"
        else:
            verdict, ev["basis"] = "confirmed", "exemption_on_record"
    else:
        hist = await _bill_history(pinnum, client)
        ev["bills_checked"] = hist["bills"]
        latest = max((b["year"] for b in hist["bills"]), default=None)
        # the bills speak for the board's lifetime (2026 rows) only when they reach last year
        recent = latest is not None and latest >= today.year - 1
        shapes = [b.get("shape") for b in hist["bills"] if "error" not in b]
        was_billed = recent and any(s in RELIEF_SHAPES for s in shapes)
        from_layer = scraped_from_layer(row, pinnum)
        if from_layer:
            ev["layer_showed_it_on"] = str(row.get("last_seen") or "")[:10] or None
        if was_billed or from_layer:
            verdict = "stale"
            ev["basis"] = "owner_changed" if own["owner_changed"] else "relief_removed"
        elif latest is not None and not recent:
            # the parcel's billing stopped years ago (a retired PIN): it cannot say "never"
            verdict, ev["reason"] = "unconfirmed", "parcel_record_ended"
        elif not shapes or len(shapes) < len(hist["bills"]):
            # "never" needs every bill looked at: one unreadable year could be the one with it
            verdict, ev["reason"] = "unconfirmed", "bills_unreadable"
            if hist["error"]:
                ev["error"] = hist["error"]
        elif any(s == "other" for s in shapes):
            verdict, ev["reason"] = "unconfirmed", "exempt_value_unexplained"
        else:
            verdict, ev["basis"] = "refuted", "never_on_record"

    ev["voter"] = await voter_status(row, client)
    return _res(verdict, ev)
