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

WHICH PARCELS (v4, 2026-10-06; the live re-check of the 34 refuted entries found 3 wrong). The
claim is "the row's owner has the exclusion". A row's parcel id and its street address can name
DIFFERENT parcels (a lien row whose parcel id is another parcel's, a street address that is the
taxpayer's mailing address, a '99999 <road>' placeholder parcel, an elderly row merged into a
row of another parcel by the old address-key merge), so v3 judged a parcel that was not the row's
and refuted real claims (31 MLK Jr Dr, 87 Elkwood Ave) or called a removed relief never-on-record
(29 Ravenwood Dr). Now up to three parcels are judged, each by the same rules, and combined:
  * the ADDRESS parcel: the one parcel that carries the row's address, exact house number and
    street name after normalization (_tax_common.address_relation), found on the same county layer by
    its situs columns (HouseNumber + streetname; a different house number is never followed to)
    and, when the layer has none, by the tax site's address search (Search/Results?QueryType=
    Address), then read from the layer by pinnum;
  * the BOARD parcel: the row's parcel_id (the ledger key), as v3;
  * the LIEN-BILL parcel: raw['arcgis_distress']['pin'] (or the county-tax-roll owner_mailing
    parcel), when it is a third parcel.
The verdict is the best of them: confirmed if any parcel shows the relief today with the row's
owner (or the lien bill's owner) among its owners; else stale if any had it earlier; else refuted
only if every judged parcel never showed it; else unconfirmed. When the address parcel is not the
board parcel, evidence carries address_pin / board_pin (/ lien_pin) and a `parcels` list. An
address parcel that is not the board's and is owned by someone else entirely (the row's address
is the taxpayer's old mailing address) is NEUTRAL: nothing of it is read and it neither
confirms nor blocks; a partial match (a shared surname) is not a confirmation either, and keeps
the signal (`owner_differs_relief_present`) when that parcel shows the relief.
A parcel whose layer carries another exemption code (EXO: a church, a government parcel) owns
every exclusion its bills show, whatever their size: none of it is this relief (the first live
run of v4 confirmed RIVERVIEW CHURCH RD from a $37,100 parcel excluded whole, the shape of the
elderly exclusion on a residence worth under $45,000, until its EXO code was read).
BILL LOOK-BACK (v4). The "never" in refuted is read from every levy bill of the parcel from
LOOKBACK_YEARS back (2022 in 2026) to now, not the latest two: 9686053926 had half its value
excluded on its 2022 to 2024 bills and none on 2025 and 2026 (v3 read 2025 and 2026 and said
refuted; it is stale). The two newest bills still decide a confirmed or a stale as before; the
older ones are read only when the answer would otherwise be "never".

VERDICTS (core.py's meanings):
  confirmed    today's layer shows ELD/DIS/BLD/VET on a judged parcel and the county owner is the
               board's owner (name_normalize match, or the same household: a surviving spouse).
               On the ADDRESS parcel, when it is not the board parcel, the row's owner (or the
               lien owner) must be among the parcel's owners: basis `exemption_on_address_parcel`.
               A changed code inside the set (ELD -> DIS) is still confirmed (`type_changed`).
  stale        the relief WAS on the record and is not today: (a) the owner changed since (a deed
               after the board first saw the row, or a different owner) and the relief is gone,
               or (b) same owner, relief removed. "Was" = a relief-shaped Exempt Value on a levy
               bill of the look-back window, or the row is the buncombe_elderly scraper's own row
               (it read this layer, by this PIN, with the code on it). "Gone" is read from the
               BILLS: when the layer's Exempt flag is blank the newest levy bill decides (v3; the
               flag alone called 1406 Hardscrabble Rd stale while its 8/15/2026 bill, paid,
               excluded 103,900 = half of 207,800, owners unchanged). The newest bill with an
               Exempt Value above zero (and the billing record reaching last year) is
               `confirmed` ("exemption_on_latest_bill", `layer_flag_blank` noted); an unreadable
               newest bill cannot show the relief removed (`unconfirmed`, bills_unreadable).
               A same-owner removal on the newest bill stays stale (11 Cardinal Cove Rd: 118,350
               on the 2025 bill, 0 on 2026): whether that should end the signal is a scoring
               decision, so the evidence carries `exempt_value_by_year` and `owner_unchanged_since`
               (the earliest levy year of the unbroken run of bills naming the newest bill's owner)
               to make the call visible.
  refuted      no judged parcel shows it today, and none of the levy bills since LOOKBACK_YEARS
               ago (2022 to now) carried a relief-shaped exclusion (the claim was attached to a
               parcel whose record never showed it during the board's lifetime: a spatial-join
               neighbour, a wrong parcel). A relief that WAS on an earlier bill is stale.
  unconfirmed  no resolvable PIN; the layer unreadable or the PIN not in it (a retired PIN);
               several parcels under the board's 10-digit pin ("pin_shared_by_units": the
               units of a condominium all carry the building's pin, so the board row and its
               ledger key cannot say which unit; the owner's own unit, when found, is evidence);
               a billing record that ended before last year ("parcel_record_ended");
               the relief is on the parcel but for an owner who is not the board's
               ("owner_differs_relief_present": the property fact holds, the board's person does
               not; never suppresses; the address parcel's own owner only when that is a
               shared surname); the bills unreadable when they were needed; a parcel that could
               not be read, the address parcel ("address_parcel_unreadable"), the lien bill's
               ("lien_parcel_unreadable") or several parcels carrying the row's address with none
               the board's ("address_shared_by_parcels"), which also stops another parcel's stale
               or refuted from standing alone (it might show the relief today); or an Exempt
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
birth, age, address, voting history, or any other person's name. ROW_SUMMARY_EXCLUDE keeps the
board's owner_name out of the ledger's row summaries too (the sweep honours it; migrate_ledger()
rewrote the entries written before it, offline).

COST (the per-host spacing is 1.5 s): a row whose board parcel's layer record shows the relief is
one layer query. Otherwise: the address query (and, when it finds nothing, the site's address
search), the lien parcel's layer query, then per parcel one parcel page and the two newest bills
(the rest of the 2022 window only when those say "never": 5 bills): about 12 to 20 requests of the
tax site, a minute at worst, inside the sweep's per-row timeout.

TTL 60 days (an exemption changes on a death, a sale or the annual application), retry 7.
"""
from __future__ import annotations

import asyncio
import html as _html
import re
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import quote_plus, urlencode

from ..core import VerificationResult, result
from ._tax_common import address_key, address_query, address_relation
from .tax_lien_buncombe import (BILL_URL, PARCEL_URL, SEARCH_URL, money, owner_match,
                                parse_parcel_page, parse_search_results, pin_of)

SIGNAL = "elderly_disabled"
VERSION = "v5"         # v5 (2026-10-06): relief gone from the newest bill with the SAME owner is
                       # unconfirmed (relief_removed_same_owner), not stale: the signal keeps scoring
                       # (owner decision). v4 (2026-10-06): the check is bound to the parcel that carries the row's
                       # ADDRESS as well as the board and lien-bill parcels (a confirmed there is
                       # `exemption_on_address_parcel`), and the "never" is read from every levy
                       # bill since 2022, not the latest two (an earlier relief is stale)
                       # v2 (2026-10-06): a 10-digit board pin is looked up as pin= (it can
                       # cover many condominium units: unconfirmed), not padded to the
                       # common-area pinnum; a billing record that ended is unconfirmed
                       # v3 (2026-10-06): the bills decide, not the GIS flag: an exclusion on the
                       # newest bill is `confirmed` (exemption_on_latest_bill) whatever the
                       # layer's Exempt flag says; stale needs the newest bill read and
                       # showing no exclusion. Evidence adds exempt_value_by_year and
                       # owner_unchanged_since
TTL_DAYS = 60
RETRY_DAYS = 7
SOURCE = "gis.buncombecounty.org + tax.buncombenc.gov"
GOVERNS = ("elderly_disabled", "senior_exemption")
ROW_SUMMARY_EXCLUDE = ("owner_name",)    # the ledger is public; see PRIVACY above

_NAME = __name__.rsplit(".", 1)[-1]

#: counties_nc.buncombe_elderly.QUERY_URL (a test pins them equal; not imported, so the registry
#: does not pull the scraper stack in)
LAYER_URL = "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query"
LAYER_FIELDS = "pinnum,pin,owner,TaxYear,UpdateDate,Exempt,AppraisedValue,DeedDate,Class"
#: the address lookup also asks for the situs columns (the layer's own: Address / CityName are
#: the OWNER'S MAILING address, see buncombe_elderly)
ADDRESS_FIELDS = LAYER_FIELDS + ",HouseNumber,NumberSuffix,direction,streetname,StreetType,PostDirection"
ELDERLY_SOURCE = "counties_nc.buncombe_elderly"
VOTER_HOST = "vt.ncsbe.gov"
MAX_BILL_CHECKS = 2        # the newest bills that decide a confirmed or a stale (as in v3)
LOOKBACK_YEARS = 4         # the "never" reads the levy bills of today.year - 4 .. today (2022 on)
MAX_BILL_FETCHES = 8       # per parcel: the window's bills, discovery bills included
MAX_ADDRESS_CANDIDATES = 3  # parcels the tax site's address search may add to the answer
LAYER_TRIES = 3            # the county layer answers an HTTP 200 {"error": {"code": 500}} now and
LAYER_RETRY_WAIT_S = 4.0   # then (11 of 35 rows in one recheck window): retried, spaced, before
                           # a parcel is called unreadable

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


async def get_layer(client, url: str) -> list[dict]:
    """parse_layer(the layer's answer to `url`), retried LAYER_TRIES times, LAYER_RETRY_WAIT_S
    apart, when the county's server answers with an error payload or a transport error. A URL a
    replay has no recording for (LookupError) is never retried."""
    last: Optional[BaseException] = None
    for i in range(LAYER_TRIES):
        try:
            return parse_layer(await client.get_json(url))
        except LookupError:
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < LAYER_TRIES:
                await asyncio.sleep(LAYER_RETRY_WAIT_S * (i + 1))
    assert last is not None
    raise last


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
                    "appraised": money(a.get("AppraisedValue")), "situs": _situs(a)})
    return out


def _situs(a: dict) -> Optional[str]:
    """The parcel's own address from the layer's situs columns ("87 ELKWOOD AVE"); None when the
    query did not ask for them or the parcel has no house number."""
    hn = str(a.get("HouseNumber") or "").strip()
    if not hn:
        return None
    parts = [hn + str(a.get("NumberSuffix") or "").strip(), a.get("direction"),
             a.get("streetname"), a.get("StreetType"), a.get("PostDirection")]
    return " ".join(str(p).strip() for p in parts if p and str(p).strip()) or None


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
    less than the exclusion: at most $45,000), else 'other'. None when nothing is exempt."""
    if not exempt or exempt <= 0:
        return None
    if real and abs(exempt - real) < 1:
        # a residence worth less than the exclusion is excluded whole; a larger value excluded
        # whole is another exemption (a church, a government parcel: layer code EXO), not this
        return "full_value" if real <= 45000 else "other"
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


def lien_pin_query(row: dict) -> Optional[tuple[str, str]]:
    """How to find the LIEN-BILL parcel on the layer, as layer_query() does for the board's:
    the parcel the lien bill is for (raw['arcgis_distress']['pin'] of the county's unpaid-bill
    layers, or the parcel of a county-tax-roll owner_mailing block). None when the row carries
    none. It is a different parcel from the board's on 16 of the 32 refuted rows that carry one
    (an elderly or tax row merged into a row of another parcel by the old address-key merge)."""
    raw = _raw(row)
    ad, om = raw.get("arcgis_distress"), raw.get("owner_mailing")
    cands = []
    if isinstance(ad, dict) and ad.get("pin"):
        cands.append(ad["pin"])
    if isinstance(om, dict) and om.get("source") == "county_tax_roll" and om.get("parcel_id"):
        cands.append(om["parcel_id"])
    for c in cands:
        q = layer_query({"parcel_id": c})
        if q:
            return q
    return None


def owner_candidates(row: dict) -> list[str]:
    """The owners whose exclusion the row claims: the board's owner and the lien bill's owner
    ("LAST FIRST" of the county's unpaid-bill layer, or the tax-roll owner_mailing's owner). The
    board's owner can be a later county-GIS refresh (enrichment_gis_attrs), so the lien bill's is
    the person the lead was about."""
    raw = _raw(row)
    out = []
    for name in (row.get("owner_name"),):
        if name:
            out.append(str(name))
    om, ad = raw.get("owner_mailing"), raw.get("arcgis_distress")
    if isinstance(om, dict) and om.get("source") == "county_tax_roll" and om.get("owner"):
        out.append(str(om["owner"]))
    if isinstance(ad, dict):
        nm = " ".join(str(ad.get(k)).strip() for k in ("owner1_last_name", "owner1_first_name")
                      if ad.get(k))
        if nm:
            out.append(nm)
    return list(dict.fromkeys(out))


_OWNER_RANK = {"same": 3, "partial": 2, "different": 1}


def owner_category(candidates: list[str], county_owner: Optional[str]) -> Optional[str]:
    """The best owner_match category between any of the row's owners and the county's owner
    string, which names several owners with ';' (a household): the whole string and each owner
    are compared. 'same' = a candidate IS one of the county's owners. The names never leave this
    function."""
    if not county_owner:
        return None
    pieces = [county_owner] + [p.strip() for p in str(county_owner).split(";") if p.strip()]
    best: Optional[str] = None
    for cand in candidates:
        for piece in dict.fromkeys(pieces):
            m = owner_match(cand, piece)
            if m and (best is None or _OWNER_RANK[m] > _OWNER_RANK[best]):
                best = m
    return best


def owner_state(row: dict, layer: dict) -> dict:
    """{'owner_match', 'transferred_since', 'owner_changed'}: owner_match is tax_lien_buncombe's
    category (same / partial / different / None), best over the row's owners (owner_candidates)
    and the county's owner list; transferred_since is a deed recorded after the board first saw
    the row; owner_changed is a different owner, or a partial one (a shared surname) with a deed
    since (an heir, a relative)."""
    om = owner_category(owner_candidates(row), layer.get("owner"))
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


def migrate_ledger(led: Any) -> int:
    """Drop ROW_SUMMARY_EXCLUDE from every entry's row summary of a loaded elderly_disabled
    Ledger, in place. No fetch; verdicts, evidence and stamps unchanged. Returns the number of
    entries changed."""
    changed = 0
    for entry in led.rows.values():
        row = entry.get("row")
        if isinstance(row, dict) and any(f in row for f in ROW_SUMMARY_EXCLUDE):
            for f in ROW_SUMMARY_EXCLUDE:
                row.pop(f, None)
            changed += 1
    return changed


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def _res(verdict: str, evidence: dict) -> VerificationResult:
    return result(SIGNAL, verdict, evidence, source=SOURCE, version=VERSION, verifier=_NAME)


def _owner_key(owner: Any) -> tuple:
    """A bill's owner string as a comparable set of words (order, case and punctuation do not
    matter; a life-estate marker or a second owner does)."""
    return tuple(sorted(set(re.sub(r"[^A-Z0-9 ]", " ", str(owner or "").upper()).split())))


def owner_unchanged_since(bills: list[dict]) -> Optional[int]:
    """The earliest levy year of the unbroken run of bills (newest first) that name the newest
    bill's owner, or None when the newest bill names none. Words of the owner string only, so a
    second owner who dropped off (or joined) ends the run. The name itself is never returned."""
    rows = [b for b in sorted(bills, key=lambda b: b.get("year") or 0, reverse=True)
            if b.get("year")]
    if not rows or not _owner_key(rows[0].get("owner")):
        return None
    want, since = _owner_key(rows[0].get("owner")), rows[0]["year"]
    for b in rows[1:]:
        if _owner_key(b.get("owner")) != want:
            break
        since = b["year"]
    return since


async def _bill_page(pin: str, client) -> tuple[Optional[dict], Optional[str]]:
    """(the parsed parcel page, None) or (None, why it could not be read)."""
    try:
        page = parse_parcel_page(await client.get_text(PARCEL_URL.format(pin=pin)))
    except Exception as exc:  # noqa: BLE001
        return None, f"parcel_page: {type(exc).__name__}"
    if not page["bills"]:
        return None, "parcel_page: no_bills_parsed"
    return page, None


async def _read_bills(bills: list[dict], client) -> list[dict]:
    """Each bill's Exempt Value: [{year, exempt_value, shape[, deferred_value]} or {year, error}]."""
    out = []
    for b in bills:
        burl = BILL_URL.format(bill=b["bill"])
        try:
            v = parse_bill_values(await client.get_text(burl))
        except Exception as exc:  # noqa: BLE001
            out.append({"year": b["year"], "error": type(exc).__name__})
            continue
        if not v["readable"]:
            out.append({"year": b["year"], "error": "values_unreadable"})
            continue
        rec = {"year": b["year"], "exempt_value": v["exempt"],
               "shape": relief_shape(v["real"], v["exempt"])}
        if v["deferred"]:
            rec["deferred_value"] = v["deferred"]
        out.append(rec)
    return out


def _decide_bills(*, own: dict, bills: list[dict], latest: Optional[int], since: Optional[int],
                  today: date, from_layer: bool, explained: bool, strict_owner: bool
                  ) -> tuple[str, dict]:
    """The verdict the levy bills read so far give for ONE parcel whose layer shows no relief
    code: (status, info). status: confirmed | owner_differs | stale | unconfirmed | refuted.
    `bills` are the ones read (newest first), `latest` the newest levy year on the parcel's page,
    `since` the first year of the unbroken run of bills naming the newest owner. Pure."""
    # the bills speak for the board's lifetime (2026 rows) only when they reach last year
    recent = latest is not None and latest >= today.year - 1
    read = [b for b in bills if "error" not in b]
    shapes = [b.get("shape") for b in read]
    # a non-relief exemption code on the layer (EXO: a church, a government parcel) owns every
    # exclusion the parcel's bills show, whatever their size (a $37,100 parcel excluded whole is
    # as much a "full value" as a residence worth less than the elderly exclusion): none of them
    # is this relief
    def relief(b: dict) -> bool:
        return not explained and b.get("shape") in RELIEF_SHAPES
    relief_years = sorted({b["year"] for b in read if relief(b)}, reverse=True)
    info: dict[str, Any] = {}
    if relief_years:
        info["relief_years"] = relief_years
    claimed_before = (recent and bool(relief_years)) or from_layer
    # the newest levy bill is the county's current word on the exclusion; the layer's Exempt
    # flag is not (a blank flag over a bill that excludes half the value: 1406 Hardscrabble Rd)
    newest = next((b for b in bills if b.get("year") == latest), None)
    newest_ok = newest is not None and "error" not in newest
    newest_excludes = newest_ok and (newest.get("exempt_value") or 0) > 0
    newest_zero = newest_ok and not newest_excludes
    # (an exclusion that matches no relief formula counts only on the scraper's own row of this
    # parcel; on a merged-in claim it stays "exempt_value_unexplained" below)
    relief_now = newest_excludes and recent and (relief(newest) or (from_layer and not explained))
    if relief_now and not own["owner_changed"]:
        info.update(latest_bill_shape=newest.get("shape"), layer_flag_blank=True)
        if strict_owner and own["owner_match"] != "same":
            info["reason"] = "owner_differs_relief_present"
            return "owner_differs", info
        info["basis"] = "exemption_on_latest_bill"
        return "confirmed", info
    if own["owner_changed"] and claimed_before:
        info["basis"] = "owner_changed"
        return "stale", info
    if claimed_before and newest_zero:
        # relief gone from the newest bill. Was it THIS owner's? Relief only on bills of an
        # earlier owner (before the run of bills that name today's) is stale all the same (it
        # was on the record), but the evidence says whose it was.
        mine = [y for y in relief_years if since is None or y >= since]
        if relief_years and not mine and not from_layer:
            info.update(basis="owner_changed", relief_under_earlier_owner=True)
            return "stale", info
        # The relief was this owner's and is gone from the newest bill, and the owner has not changed
        # (no deed): the exclusion may have lapsed over income or paperwork while the person is
        # still elderly or disabled. The owner decided on 2026-10-06 to keep such a lead scoring
        # (11 Cardinal Cove Rd, 29 Ravenwood Dr), so this is unconfirmed (scores as before), not
        # stale (which would remove the signal).
        info["reason"] = "relief_removed_same_owner"
        return "unconfirmed", info
    if claimed_before and not newest_ok:
        # the bills cannot say the relief is gone when the newest one was not read, and the
        # layer's flag alone is not proof (it can go blank over a bill that still excludes)
        info["reason"] = "bills_unreadable"
        return "unconfirmed", info
    if latest is not None and not recent:
        # the parcel's billing stopped years ago (a retired PIN): it cannot say "never"
        info["reason"] = "parcel_record_ended"
        return "unconfirmed", info
    if not shapes or len(shapes) < len(bills):
        # "never" needs every bill looked at: one unreadable year could be the one with it
        info["reason"] = "bills_unreadable"
        return "unconfirmed", info
    if not explained and any(s == "other" for s in shapes):
        info["reason"] = "exempt_value_unexplained"
        return "unconfirmed", info
    info["basis"] = "never_on_record"
    return "refuted", info


def _layer_evidence(layer: dict, own: dict, claimed: list[str], pinnum: str) -> dict:
    code = layer["code"]
    ev: dict[str, Any] = {"pinnum": pinnum, "county_code": code,
                          "exemption_type": CODE_TYPE.get(code or ""),
                          "tax_year": layer["tax_year"], "layer_updated": layer["updated"],
                          "owner_match": own["owner_match"]}
    if own["owner_changed"] or own["transferred_since"]:
        ev["deed_date"] = layer["deed_date"]
        ev["transferred_since"] = own["transferred_since"]
    if code in CODE_TYPE and claimed and code not in claimed:
        ev["type_changed"] = True
    return ev


def _by_layer(row: dict, layer: dict, pinnum: str, role: str, claimed: list[str], *,
              strict_owner: bool) -> dict:
    """One parcel judged from its layer record alone. status is 'confirmed' or 'owner_differs'
    when the layer shows a relief code, else None (the bills decide: _by_bills)."""
    own = owner_state(row, layer)
    j: dict[str, Any] = {"role": role, "pinnum": pinnum, "layer": layer, "own": own,
                         "ev": _layer_evidence(layer, own, claimed, pinnum), "status": None}
    if strict_owner and own["owner_match"] == "different":
        # the parcel at the row's address, which is not the board's, is another person's (the row
        # carries the taxpayer's MAILING address, or a stale one): whatever it shows is not this
        # owner's claim, for or against. Nothing of it is read further.
        j["status"], j["ev"]["reason"] = "neutral", "address_parcel_other_owner"
        return j
    if layer["code"] in CODE_TYPE:
        if own["owner_changed"] or (strict_owner and own["owner_match"] != "same"):
            j["status"], j["ev"]["reason"] = "owner_differs", "owner_differs_relief_present"
        else:
            j["status"], j["ev"]["basis"] = "confirmed", "exemption_on_record"
    return j


async def _by_bills(row: dict, client, j: dict, today: date, *, strict_owner: bool) -> None:
    """Judge the parcel from its levy bills (j: a _by_layer() record without a status). The two
    newest bills decide a confirmed or a stale as in v3; when they say "never", the rest of the
    look-back window is read before that is believed."""
    layer, pinnum, own, ev = j["layer"], j["pinnum"], j["own"], j["ev"]
    page, error = await _bill_page(pinnum, client)
    bills: list[dict] = []
    latest = since = None
    window: list[dict] = []
    if page is not None:
        raddr = row.get("street_address")
        if address_query(raddr):
            ev["address_relation"] = address_relation(raddr, page.get("situs"))
        latest = max((b["year"] for b in page["bills"]), default=None)
        since = owner_unchanged_since(page["bills"])
        window = [b for b in page["bills"]
                  if b["year"] >= today.year - LOOKBACK_YEARS][:MAX_BILL_FETCHES]
        bills = await _read_bills(window[:MAX_BILL_CHECKS], client)
    from_layer = scraped_from_layer(row, pinnum)
    # a non-relief exemption code (EXO: a church or government parcel) explains an exclusion
    # that matches no relief formula; it is not this relief and not an unexplained value
    code = layer["code"]
    explained = bool(code) and code not in CODE_TYPE

    def decide() -> tuple[str, dict]:
        return _decide_bills(own=own, bills=bills, latest=latest, since=since, today=today,
                             from_layer=from_layer, explained=explained, strict_owner=strict_owner)

    status, info = decide()
    if status == "refuted" and len(window) > MAX_BILL_CHECKS:
        bills = bills + await _read_bills(window[MAX_BILL_CHECKS:], client)
        status, info = decide()
    by_year: dict[str, float] = {}
    for b in bills:
        if "error" not in b and b.get("exempt_value") is not None:
            k = str(b["year"])
            by_year[k] = max(by_year.get(k, 0.0), b["exempt_value"])
    ev["bills_checked"] = bills
    if by_year:
        ev["exempt_value_by_year"] = by_year
    if since:
        ev["owner_unchanged_since"] = since
    if from_layer:
        ev["layer_showed_it_on"] = str(row.get("last_seen") or "")[:10] or None
    if explained:
        ev["other_exemption_code"] = code
    ev.update(info)
    if status == "unconfirmed" and info.get("reason") == "bills_unreadable" and error:
        ev["error"] = error
    j["status"] = status


#: reasons for which a parcel could not be READ: it might show the relief today, so no other
#: parcel's stale or refuted answer may stand beside it
_NOT_READ = frozenset({"bills_unreadable", "address_parcel_unreadable", "lien_parcel_unreadable",
                       "address_shared_by_parcels"})


def _combine(judged: list[dict]) -> tuple[str, dict]:
    """(verdict, the judgement that decides it) from the judged parcels (address, board, lien
    order): confirmed if any parcel confirms; stale if any is stale and every parcel could be
    read; refuted only if every parcel is refuted (a neutral one, another person's parcel at the
    row's address, counts for nothing); else unconfirmed (an owner-differs answer, the property
    fact holding for someone near the owner, first)."""
    live = [j for j in judged if j["status"] != "neutral"]
    for j in live:
        if j["status"] == "confirmed":
            return "confirmed", j
    unread = any(j["status"] == "unconfirmed" and j["ev"].get("reason") in _NOT_READ
                 for j in live)
    if not unread:
        for j in live:
            if j["status"] == "stale":
                return "stale", j
        if live and all(j["status"] == "refuted" for j in live):
            return "refuted", live[0]
    for status in ("owner_differs", "unconfirmed", "stale", "neutral"):
        for j in judged:
            if j["status"] == status:
                return "unconfirmed", j
    return "unconfirmed", judged[0]


# ---------------------------------------------------------------------------
# the parcel that carries the row's address
# ---------------------------------------------------------------------------

def address_layer_url(address: Any) -> Optional[str]:
    """The layer query for the parcels that may carry a street address: its house number and one
    word of the street name against the layer's own situs columns (exact matching is
    address_relation()'s, after the query). None when the address has no house number."""
    number, name, _tail = address_key(address)
    if not number or not name or not address_query(address):
        return None
    digits = re.match(r"\d+", number).group(0)
    word = max(sorted(name), key=len)
    nums = ",".join(f"'{n}'" for n in dict.fromkeys([digits, digits.zfill(5)]))
    where = f"HouseNumber IN ({nums}) AND streetname LIKE '%{word}%'"
    return LAYER_URL + "?" + urlencode({"where": where, "outFields": ADDRESS_FIELDS,
                                        "returnGeometry": "false", "f": "json"})


async def _address_parcels(row: dict, client, ev: dict) -> tuple[str, list[dict], Optional[str]]:
    """(state, parcels, how): the layer records of the parcels that carry the row's address,
    exact house number and street name after normalization. state: 'ok' (>= 1 parcel), 'none'
    (the sources were read and nothing carries it), 'unreadable', 'no_address' (the row has no
    house-numbered address: nothing to bind). The layer's situs columns first; when they find
    nothing, the tax site's address search, each hit then read from the layer by pinnum. A
    parcel whose house number differs from the row's is never returned."""
    addr = row.get("street_address")
    url = address_layer_url(addr)
    if not url:
        return "no_address", [], None
    ev["address_url"] = url
    try:
        feats = await get_layer(client, url)
    except Exception as exc:  # noqa: BLE001
        ev["address_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return "unreadable", [], None
    match = [f for f in feats if address_relation(addr, f.get("situs")) == "match"]
    if match:
        return "ok", match, "layer_situs"
    surl = SEARCH_URL.format(q=quote_plus(address_query(addr)))
    ev["address_search_url"] = surl
    try:
        found = parse_search_results(await client.get_text(surl))
    except Exception as exc:  # noqa: BLE001
        ev["address_search_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return "none", [], None
    if found is None:
        ev["address_search_error"] = "unreadable"
        return "none", [], None
    pins = list(dict.fromkeys(f["pin"] for f in found
                              if address_relation(addr, f["address"]) == "match"))
    feats = []
    for pin in pins[:MAX_ADDRESS_CANDIDATES]:
        try:
            feats.extend(await get_layer(client, layer_url("pinnum", pin)))
        except Exception as exc:  # noqa: BLE001
            ev["address_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            return "unreadable", [], None
    return ("ok", feats, "site_search") if feats else ("none", [], None)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    claimed = claimed_codes(row)
    q = layer_query(row)
    lien_q = lien_pin_query(row)
    has_addr = address_layer_url(row.get("street_address")) is not None
    ev: dict[str, Any] = {"county": "Buncombe", "claimed_codes": claimed}
    if not q and not lien_q and not has_addr:
        return _res("unconfirmed", {**ev, "reason": "parcel_unresolvable",
                                    "parcel_id": row.get("parcel_id")})

    # -- the board parcel (the row's parcel_id, the ledger key)
    board: Optional[dict] = None
    board_pin: Optional[str] = None
    if q:
        url = layer_url(*q)
        ev.update({q[0]: q[1], "url": url})
        try:
            feats = await get_layer(client, url)
        except Exception as exc:  # noqa: BLE001
            return _res("unconfirmed", {**ev, "reason": "layer_unreadable",
                                        "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
        if len(feats) > 1:
            # several parcels under the board's 10-digit pin (condominium units): the board's
            # parcel id, and so the ledger key every unit's row shares, cannot say which unit the
            # claim is about, so no verdict here may speak for all of them. What the board
            # owner's own unit shows is kept as evidence.
            mine = [f for f in feats if owner_match(row.get("owner_name"), f["owner"]) == "same"]
            ev.update({"reason": "pin_shared_by_units", "parcels_under_pin": len(feats),
                       "coded_parcels_under_pin": sum(1 for f in feats if f["code"] in CODE_TYPE)})
            if len(mine) == 1:
                ev.update({"owner_unit": mine[0]["pinnum"], "owner_unit_code": mine[0]["code"]})
            return _res("unconfirmed", ev)
        if feats:
            board = feats[0]
            board_pin = board["pinnum"] or (q[1] if q[0] == "pinnum" else q[1] + "00000")
        else:
            ev["board_pin_not_in_county_layer"] = True
    judged: list[dict] = []
    if board is not None:
        jb = _by_layer(row, board, board_pin, "board", claimed, strict_owner=False)
        if jb["status"] == "confirmed":          # the layer shows the relief on the board's parcel
            return await _finish(row, client, ev, [jb], jb, "confirmed")
        judged.append(jb)

    # -- the parcel that carries the row's address
    astate, afeats, how = await _address_parcels(row, client, ev)
    if astate == "ok":
        same = [f for f in afeats if board_pin and f["pinnum"] == board_pin]
        mine = [f for f in afeats if owner_category(owner_candidates(row), f["owner"]) == "same"]
        pick = same[0] if same else (afeats[0] if len(afeats) == 1
                                     else (mine[0] if len(mine) == 1 else None))
        if pick is None:
            ev["address_parcels"] = len(afeats)
            judged.insert(0, {"role": "address", "pinnum": None, "status": "unconfirmed",
                              "ev": {"reason": "address_shared_by_parcels"}})
            ev["address_binding"] = "ambiguous"
        elif same:
            ev["address_binding"] = "board_parcel"
            if judged:
                judged[0]["role"] = "board+address"
        else:
            ev["address_binding"] = how
            judged.insert(0, _by_layer(row, pick, pick["pinnum"], "address", claimed,
                                       strict_owner=True))
    elif astate == "unreadable":
        ev["address_binding"] = "unreadable"
        judged.insert(0, {"role": "address", "pinnum": None, "status": "unconfirmed",
                          "ev": {"reason": "address_parcel_unreadable"}})
    else:
        ev["address_binding"] = "none_found" if astate == "none" else "no_row_address"

    # -- the lien bill's parcel, when it is a third one
    known = {j["pinnum"] for j in judged if j.get("pinnum")}
    if lien_q and not (lien_q == q or (lien_q[0] == "pinnum" and lien_q[1] in known)
                       or (lien_q[0] == "pin" and any(k[:10] == lien_q[1] for k in known))):
        lurl = layer_url(*lien_q)
        try:
            lfeats = await get_layer(client, lurl)
        except Exception as exc:  # noqa: BLE001
            ev["lien_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            lfeats = None
        if lfeats is None:
            judged.append({"role": "lien_bill", "pinnum": None, "status": "unconfirmed",
                           "ev": {"reason": "lien_parcel_unreadable"}})
        elif len(lfeats) == 1 and lfeats[0]["pinnum"] not in known:
            judged.append(_by_layer(row, lfeats[0], lfeats[0]["pinnum"], "lien_bill", claimed,
                                    strict_owner=False))
        elif not lfeats:
            ev["lien_pin_not_in_county_layer"] = True

    if not judged:
        return _res("unconfirmed", {**ev, "reason": "parcel_not_in_county_layer" if q
                                    else "parcel_unresolvable", "parcel_id": row.get("parcel_id")})

    # -- a relief code on the layer decides without reading any bill
    for j in judged:
        if j["status"] == "confirmed":
            return await _finish(row, client, ev, judged, j, "confirmed")
    # -- the rest by their levy bills
    for j in judged:
        if j["status"] is None:
            await _by_bills(row, client, j, today, strict_owner=j["role"] == "address")
    verdict, deciding = _combine(judged)
    return await _finish(row, client, ev, judged, deciding, verdict)


async def _finish(row: dict, client, ev: dict, judged: list[dict], deciding: dict,
                  verdict: str) -> VerificationResult:
    """Put the deciding parcel's evidence on the answer, name the parcels when they differ, and
    add the voter status."""
    ev.update(deciding["ev"])
    pins = {j["role"]: j["pinnum"] for j in judged if j.get("pinnum")}
    if len(set(pins.values())) > 1:
        for role in ("address", "board", "board+address", "lien_bill"):
            if role in pins:
                key = {"board+address": "board", "lien_bill": "lien"}.get(role, role)
                ev[f"{key}_pin"] = pins[role]
        ev["parcels"] = [
            {k: v for k, v in {
                "role": j["role"], "pinnum": j.get("pinnum"), "status": j["status"] or "not_read",
                "basis": j["ev"].get("basis"), "reason": j["ev"].get("reason"),
                "county_code": j["ev"].get("county_code"),
                "owner_match": j["ev"].get("owner_match"),
                "exempt_value_by_year": j["ev"].get("exempt_value_by_year"),
                "relief_years": j["ev"].get("relief_years")}.items() if v is not None}
            for j in judged]
    if verdict == "confirmed" and deciding["role"] == "address":
        ev["address_parcel_basis"] = ev.get("basis")
        ev["basis"] = "exemption_on_address_parcel"
    if verdict == "confirmed" and deciding["role"] == "lien_bill":
        ev["lien_parcel_basis"] = ev.get("basis")
        ev["basis"] = "exemption_on_lien_parcel"
    if verdict == "unconfirmed" and "reason" not in ev:
        ev["reason"] = "not_decidable"
    ev["voter"] = await voter_status(row, client)
    return _res(verdict, ev)
