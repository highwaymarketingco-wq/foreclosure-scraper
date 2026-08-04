"""Greenville County SC hard-distress parcels — BUILT BUT NOT TURNED ON.

STATUS: **behind a flag, default OFF.** Greenville is not in ``config.SC_COUNTIES``
and is in ``config.SCOPE_DENY_COUNTIES`` (pruned 2026-05-14 by operator
direction). Nothing here changes that. This module exists so that IF the operator
later decides to expand, the county is a switch-flip rather than a build. It
self-gates on::

    FORECLOSURE_INCLUDE_GREENVILLE=1

With the flag unset the scraper returns [] and reports DORMANT.

  !! WIRING NOTE FOR WHOEVER TURNS THIS ON: the flag alone is not enough.
     ``main._in_scope`` drops every Greenville row at its SCOPE_DENY_COUNTIES
     check before anything else can see it. Turning the county on needs a
     matching flag-gated bypass there. That edit is deliberately NOT made here.

WHAT "HARD DISTRESS" MEANS HERE
    Only signals that mean the owner has an unpaid obligation or a court event
    against the property. Absentee/out-of-state ownership is NOT counted as
    distress — it is an ownership attribute, it is enormous in Greenville, and
    counting it as leads is exactly the over-count this engine has been burned by
    before. Absentee is recorded as a per-lead attribute and never as a lane.

SOURCES (every one verified open 2026-08-03: anonymous, no key, no login, no
CAPTCHA/WAF, and not disallowed by the host's robots.txt)

  1. Parcels + tax  gcgis.org .../Map_Layers_JS/MapServer/52   (243,750 parcels)
     ``TOTTAX > 0 AND PAIDDATE IS NULL`` = **5,014** unpaid-tax parcels, carrying
     $13,024,627.12 of owed tax (median bill $1,031.11). 5,014/5,014 have an
     owner of record, 5,012 a mailing address, 4,890 a situs, 5,014 a polygon.
     This is the spine: it is the only one of the four sources that gives owner
     + mailing + situs + value + geometry in one hop.

  2. Sales        .../MapServer/5   (361,562 sales, PURNAME/SELLNAME/TRUESALE)
     NOT a lead source — a sale is not distress. Joined by PIN to backfill the
     last ARMS-LENGTH sale (``TRUESALE='YES'``) plus the street TYPE, which
     layer 52 omits (52 stores "506"/"WILTON", 5 supplies the "ST").

  3. Tax sale     greenvillecounty.org/appsAS400/Taxsale/     (**3,648** rows)
     The county's published delinquent tax-sale roster: Item #, Map #, Owner,
     Amount Due. 3,409 distinct parcels, of which 3,321 are already in (1) and
     **88 are not** — parcels the live tax roll no longer shows as unpaid but
     that still sit on the sale list. Those 88 are net-new and are backfilled
     from layer 52 by PIN so they arrive as full leads.
     CAVEAT, measured: the page currently serves the **November 3-4, 2025** sale.
     It is the county's own current publication, but it is a past sale date; the
     roster refreshes when the next sale is advertised. Treated as dateless.

  4. Probate      greenvillecounty.org/appsAS400/Probate/     (447,481 parties)
     A NAME index — case number, name, party type. No address, no parcel, no
     property, and no date column (the year is encoded in the case number:
     ``2023ES2302000``). Two consequences that decide the design:
       * It cannot be a lane of its own. With no property on the record, a
         probate row only becomes a lead by matching a name we already hold.
         So it runs as a MODIFIER over the owners found in (1), never as an
         additive source. Any count of "probate leads" that treats 447k names
         as leads is fiction.
       * The unfiltered result page is a single **252 MB** HTML document. We
         never fetch it. We POST one surname at a time to ``Default.aspx``
         (party type ``EST`` = "Deceased Person"), which returns a small
         filtered page. That is ~1,700 requests for the delinquent-owner set,
         so it is behind its own second flag ``FORECLOSURE_GREENVILLE_PROBATE=1``
         and is off even when the county flag is on.

     PRIVACY — DELIBERATE EXCLUSION: the same form exposes party types
     ``NCM`` (Incapacitated Person), ``PAT`` (Patient), ``MIN``/``MN2`` (Minor),
     and the guardian/conservator types. Those describe the capacity, health or
     minority of a living private individual and are not property facts. This
     module queries ``EST`` only and must never be widened to them.

  NOT BUILT AGAINST, by direction and by test: ``www2.greenvillecounty.org`` and
  ``app.greenvillecounty.org`` are Incapsula-walled. No attempt is made to reach
  either, and no bypass exists in this file.

EMISSION MODEL
    One Listing per PARCEL, keyed on ``parcel_id`` so a parcel carrying both an
    unpaid balance and a tax-sale row is ONE lead with both facts, not two rows.
    Dateless (an unpaid balance is a standing state, not a dated event), so the
    slug must be added to ``main.DATELESS_OK_SOURCES`` when the county is turned
    on or every row is filtered out.

    The slug deliberately contains "tax": ``enrichment_tax_owed``'s generic scan
    only fires for slugs matching tax/flc/forfeited/delinquent/lien, and without
    it ``raw['greenville_distress']['amount_owed']`` would never be normalized
    into ``raw['tax_owed']`` and every lead would ship with no balance.

PRIVACY: fields are enumerated explicitly — never ``outFields=*``. Everything
taken from the GIS is a property/assessment record field (owner of record, owner
mailing address, situs, value, tax owed). No phone, email, SSN, DL or DOB is
requested or stored anywhere in this module.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, NamedTuple

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind, _normalize_parcel

log = structlog.get_logger()

#: Master switch. Default OFF — the operator has not decided to expand.
ENV_ON = "FORECLOSURE_INCLUDE_GREENVILLE"
#: Second switch for the ~1,700-request probate name pass. Off even when ENV_ON.
ENV_PROBATE = "FORECLOSURE_GREENVILLE_PROBATE"

GIS = "https://www.gcgis.org/arcgis/rest/services/GreenvilleJS/Map_Layers_JS/MapServer"
PARCEL_LAYER = f"{GIS}/52"
SALES_LAYER = f"{GIS}/5"

TAXSALE_URL = "https://www.greenvillecounty.org/appsAS400/Taxsale/"
PROBATE_BASE = "https://www.greenvillecounty.org/appsAS400/Probate/"

#: The tax-office landing page a human should open for one of these leads.
PAGE_URL = "https://www.greenvillecounty.org/RealPropertyServices/"

#: Explicit field lists — never '*'.
PARCEL_FIELDS = (
    "OBJECTID,PIN,OWNAM1,OWNAM2,STREET,CITY,STATE,ZIP5,STRNUM,LOCATE,DESCR,"
    "SUBDIV,LANDUSE,PROPTYPE,IMPROVED,TOTTAX,PAIDDATE,SLPRICE,DEEDDATE,"
    "FAIRMKTVAL,TAXMKTVAL,TACRES,SQFEET,BEDROOMS,BATHRMS,HALFBATH"
)
SALES_FIELDS = (
    "OBJECTID,PIN,STREET,STRPRE,STRTYP,STRSUF,SALETYPE,TRUESALE,SALEDATE,"
    "SALEPRICE,PROPTYPE,LOTSIZE,SQFEET"
)

#: `TOTTAX > 0 AND PAIDDATE IS NULL` — an assessed bill with no payment recorded.
DELINQUENT_WHERE = "TOTTAX > 0 AND PAIDDATE IS NULL"

_PAGE = 1000
_MAX_RECORDS = 40000
#: PINs per `PIN IN (...)` chunk on the sales join. Keeps the WHERE well under
#: the length at which arcgis_webmap switches to POST and the server's own limit.
_PIN_CHUNK = 150

#: Probate party type "Deceased Person". See PRIVACY in the module docstring —
#: this is the ONLY party type this module is permitted to request.
PROBATE_PARTY_DECEASED = "EST"
#: Only estates opened this recently are treated as an actionable heir signal.
PROBATE_MIN_YEAR = 2020
_PROBATE_CASE_YEAR = re.compile(r"^(\d{4})(ES|GC)", re.I)

#: Non-seller owners. Government, schools, churches and the county itself.
_GOV = re.compile(
    r"\b(CITY OF|TOWN OF|COUNTY OF|STATE OF|GREENVILLE COUNTY|HOUSING AUTHORITY|"
    r"SCHOOL DISTRICT|UNITED STATES|SECRETARY OF|DEPARTMENT OF|FORFEITED LAND|"
    r"MUNICIPAL|SC DEPARTMENT|SC DEPT)\b", re.I)

#: Owner strings that are organisations, not people. Used ONLY to decide whether
#: a probate NAME lookup makes sense — never to drop a lead.
_ENTITY = re.compile(
    r"\b(LLC|L L C|INC|CORP|COMPANY|TRUST|LP|LLP|PARTNERS|ASSOC|CHURCH|BANK|"
    r"HOLDINGS|PROPERTIES|ENTERPRISES|GROUP|FUND|HOA|HOMEOWNERS|MINISTR|LTD)\b",
    re.I)

_PROPTYPE_KIND = {
    "RESIDENTIAL": PropertyKind.SINGLE_FAMILY,
    "MULTI-FAMILY": PropertyKind.MULTI_FAMILY,
    "MOBILE HOME": PropertyKind.MOBILE,
    "COMMERCIAL": PropertyKind.COMMERCIAL,
    "INDUSTRIAL": PropertyKind.COMMERCIAL,
    "AGRICULTURAL": PropertyKind.LAND,
}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _clean(v: Any) -> str | None:
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _money(v: Any) -> float | None:
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


def _zip5(v: Any) -> str | None:
    if v in (None, "", " ", 0, "0"):
        return None
    s = re.sub(r"\D", "", str(v).split(".")[0])
    return s[:5] if len(s) >= 5 and s[:5] != "00000" else None


def _epoch_ms(v: Any) -> datetime | None:
    if v in (None, "", 0):
        return None
    try:
        ms = int(v)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt if 1900 <= dt.year <= 2100 else None


def _centroid(geom: dict[str, Any] | None) -> tuple[float, float] | None:
    """Mean of a polygon's ring vertices -> (lat, lng). Geometry is WGS84."""
    rings = (geom or {}).get("rings") or []
    pts = [p for ring in rings for p in ring if len(p) >= 2]
    if not pts:
        return None
    return (sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts))


def _situs(strnum: Any, locate: Any, strtyp: Any = None) -> str | None:
    """Layer 52 splits the situs into house number + street NAME with no street
    type; layer 5 supplies the type. '00000' is the county's vacant-lot filler
    and must not become a house number."""
    num = _clean(strnum)
    if num and set(num) <= {"0"}:
        num = None
    name = _clean(locate)
    if not name:
        return None
    typ = _clean(strtyp)
    return " ".join(x for x in (num, name, typ) if x)


def _is_absentee(mail_street: str | None, mail_state: str | None,
                 situs: str | None) -> bool:
    """Ownership attribute only. Never counted as distress — see the module
    docstring. Recorded so an operator can sort by it after the fact."""
    st = (mail_state or "").strip().upper()
    if st and st != "SC":
        return True
    street = (mail_street or "").strip().upper()
    if re.search(r"\bP\.?\s?O\.?\s?BOX\b", street):
        return True
    if street and situs:
        return street.split()[:2] != situs.strip().upper().split()[:2]
    return False


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
class TaxSaleRow(NamedTuple):
    item: str | None
    pin: str            # normalized
    map_number: str     # as published
    owner: str | None
    amount: float | None


class TaxSaleParse(NamedTuple):
    """Parsed roster plus the count we deliberately could not use.

    ``unmapped`` is not an error: the roster interleaves ~229 MOBILE-HOME /
    personal-property items (item numbers 91xxx) that carry a name and an amount
    but a BLANK Map #. They are not real-property leads and cannot be joined to
    a parcel, so they are dropped — but the count is surfaced rather than
    silently swallowed, so a future format change that starts blanking real
    Map #s shows up as a spike instead of as quiet data loss.
    """
    rows: list[TaxSaleRow]
    unmapped: int


def parse_tax_sale(html: str) -> TaxSaleParse:
    """Rows off the county's tax-sale roster table (Item #, Map #, Name, Amount).

    The page is one big ASP.NET table with no ids, so rows are taken structurally
    and the header row is discarded by its own text rather than by position.
    """
    out: list[TaxSaleRow] = []
    unmapped = 0
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
        if len(cells) < 4:
            continue
        v = [" ".join(re.sub(r"<[^>]+>", " ", c).split()) for c in cells]
        if v[0].lower().startswith("item"):
            continue
        pin = _normalize_parcel(v[1])
        if not pin:
            unmapped += 1
            continue
        out.append(TaxSaleRow(
            item=_clean(v[0]), pin=pin, map_number=v[1].strip(),
            owner=_clean(v[2]), amount=_money(v[3]),
        ))
    return TaxSaleParse(rows=out, unmapped=unmapped)


def parse_probate_rows(html: str) -> list[dict[str, str]]:
    """(case, name, party) triples off a probate SearchResults table."""
    out: list[dict[str, str]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
        if len(cells) < 3:
            continue
        v = [" ".join(re.sub(r"<[^>]+>", " ", c).split()) for c in cells]
        if v[0].lower().startswith("case"):
            continue
        out.append({"case": v[0], "name": v[1], "party": v[2]})
    return out


def _name_tokens(s: str | None) -> list[str]:
    return [t for t in re.sub(r"[^A-Z ]", " ", (s or "").upper()).split() if len(t) > 1]


#: Generational suffixes that are not given names.
_SUFFIX = frozenset({"JR", "SR", "II", "III", "IV", "V", "MD", "DDS", "ESQ"})


def _split_probate_name(name: str | None) -> tuple[str | None, list[str]]:
    """'JONES , DAVID DANIEL JR' -> ('JONES', ['DAVID', 'DANIEL'])."""
    parts = (name or "").split(",", 1)
    surname = next(iter(_name_tokens(parts[0])), None)
    given = [t for t in _name_tokens(parts[1] if len(parts) > 1 else "")
             if t not in _SUFFIX]
    return surname, given


def probate_match(owner: str | None, rows: list[dict[str, str]]) -> dict | None:
    """The decedent record matching this owner, or None.

    GIS owner is ``SURNAME FIRST MIDDLE``; probate is ``SURNAME , FIRST MIDDLE``.

    The bar is SURNAME + FIRST GIVEN NAME, both exact and both positional. A
    looser "do the owner's two names appear anywhere in the decedent's name"
    test was tried against the live index and produced a steady stream of wrong
    people — ``SMITH WILLIAM R`` matched ``SMITH , ELRAMA WILLIAM JR``,
    ``SMITH TODD A`` matched ``SMITH , ELOISE TODD``, ``JONES ROY`` matched
    ``JONES , BOBBY ROY`` — because a middle name was being read as a first
    name. Attaching a stranger's death to a live owner's parcel is the worst
    error this source can make, so the match is positional.

    A shared middle name on top of that is recorded as ``confidence: "high"``;
    first+last alone is ``"medium"``. Nothing below first+last is emitted.
    Only estates opened in/after :data:`PROBATE_MIN_YEAR` count.
    """
    ot = _name_tokens(owner)
    ot = [t for t in ot if t not in _SUFFIX]
    if len(ot) < 2:
        return None
    o_sur, o_first, o_rest = ot[0], ot[1], set(ot[2:])
    for r in rows:
        if "DECEASED" not in (r.get("party") or "").upper():
            continue
        m = _PROBATE_CASE_YEAR.match((r.get("case") or "").strip())
        if not m or int(m.group(1)) < PROBATE_MIN_YEAR:
            continue
        d_sur, d_given = _split_probate_name(r.get("name"))
        if not d_sur or not d_given:
            continue
        if d_sur != o_sur or d_given[0] != o_first:
            continue
        shared_middle = bool(o_rest & set(d_given[1:]))
        return {"case": (r.get("case") or "").strip(),
                "name": " ".join((r.get("name") or "").split()),
                "year": int(m.group(1)),
                "confidence": "high" if shared_middle else "medium"}
    return None


def build_listing(pin: str, attrs: dict, geom: dict | None,
                  sale: dict | None = None,
                  tax_sale: TaxSaleRow | None = None,
                  probate: dict | None = None,
                  now: datetime | None = None) -> Listing | None:
    """One parcel -> one hard-distress Listing, or None if it is not a lead."""
    now = now or datetime.utcnow()
    owner = _clean(attrs.get("OWNAM1"))
    owner2 = _clean(attrs.get("OWNAM2"))
    if owner and _GOV.search(owner):
        return None

    # TOTTAX is the billed amount whether or not it was paid. A bill is only
    # DELINQUENT when the roll carries no PAIDDATE. The tax-sale-only parcels
    # backfilled by PIN do carry a TOTTAX with a PAIDDATE set — without this
    # check they would be mislabelled into the delinquent lane and inflate it.
    billed = _money(attrs.get("TOTTAX"))
    paid_date = _epoch_ms(attrs.get("PAIDDATE"))
    tax_owed = billed if (billed and paid_date is None) else None
    sale_amount = _money(tax_sale.amount) if tax_sale else None
    if not (tax_owed or sale_amount):
        return None            # neither lane fired -> not hard distress

    situs = _situs(attrs.get("STRNUM"), attrs.get("LOCATE"),
                   (sale or {}).get("STRTYP"))
    mail_street = _clean(attrs.get("STREET"))
    mail_state = _clean(attrs.get("STATE"))
    lat = lng = None
    c = _centroid(geom)
    if c:
        lat, lng = c

    proptype = (_clean(attrs.get("PROPTYPE")) or "").upper()
    improved = (_clean(attrs.get("IMPROVED")) or "").upper()
    kind = _PROPTYPE_KIND.get(proptype, PropertyKind.UNKNOWN)
    if improved == "NO" and kind in (PropertyKind.UNKNOWN, PropertyKind.SINGLE_FAMILY):
        kind = PropertyKind.LAND

    lanes: list[str] = []
    if tax_owed:
        lanes.append("delinquent_tax")
    if tax_sale:
        lanes.append("tax_sale_roster")
    if probate:
        lanes.append("probate_decedent_owner")

    gv: dict[str, Any] = {
        "county": "Greenville",
        "parcel_id": pin,
        "pin_published": _clean(attrs.get("PIN")),
        "lanes": lanes,
        # enrichment_tax_owed normalizes this into raw['tax_owed'].
        "amount_owed": tax_owed or sale_amount,
        "tax_billed_unpaid": tax_owed,
        "tax_billed": billed,
        "tax_paid_date": paid_date.date().isoformat() if paid_date else None,
        "land_use_code": _clean(attrs.get("LANDUSE")),
        "property_type": _clean(attrs.get("PROPTYPE")),
        "improved": improved or None,
        "acres": _money(attrs.get("TACRES")),
        "heated_sqft": _money(attrs.get("SQFEET")),
        "bedrooms": attrs.get("BEDROOMS") or None,
        "bathrooms": attrs.get("BATHRMS") or None,
        "subdivision": _clean(attrs.get("SUBDIV")),
        "legal_note": _clean(attrs.get("DESCR")),
        "source": "greenville_county_gis_and_tax_apps",
    }
    if tax_sale:
        gv["tax_sale"] = {
            "item": tax_sale.item,
            "map_number": tax_sale.map_number,
            "owner_as_published": tax_sale.owner,
            "amount_due": tax_sale.amount,
            "roster_url": TAXSALE_URL,
        }
    if probate:
        gv["probate"] = {**probate, "party_type": "Deceased Person",
                         "note": "owner of record matches a probate decedent; "
                                 "heirs likely hold the property"}
    if sale:
        gv["last_sale"] = {
            "price": _money(sale.get("SALEPRICE")),
            "date": (_epoch_ms(sale.get("SALEDATE")).date().isoformat()
                     if _epoch_ms(sale.get("SALEDATE")) else None),
            "type": _clean(sale.get("SALETYPE")),
            "arms_length": (_clean(sale.get("TRUESALE")) or "").upper() == "YES",
        }

    raw: dict[str, Any] = {"greenville_distress": gv}
    if mail_street:
        raw["owner_mailing"] = {
            "street": mail_street,
            "city": _clean(attrs.get("CITY")),
            "state": mail_state,
            "zip": _zip5(attrs.get("ZIP5")),
            "source": "greenville_tax_parcel_layer",
        }
        # Attribute, not a lane. Never counted in the hard-distress total.
        if _is_absentee(mail_street, mail_state, situs):
            raw["absentee_owner"] = True
    if probate or (tax_sale and tax_owed):
        raw["distressed"] = True

    fmv = _money(attrs.get("FAIRMKTVAL"))
    tmv = _money(attrs.get("TAXMKTVAL"))

    bits = [f"Greenville County SC parcel {pin}"]
    if tax_owed:
        bits.append(f"${tax_owed:,.2f} property tax billed and unpaid")
    if tax_sale:
        bits.append(f"on the county delinquent tax-sale roster (item {tax_sale.item})")
    if probate:
        bits.append(f"owner of record matches probate estate {probate['case']}")

    return Listing(
        source=GreenvilleHardDistress.slug,
        source_url=PAGE_URL,
        listing_type=ListingType.TAX_LIEN,
        property_kind=kind,
        state="SC",
        county="Greenville",
        city=None,
        street_address=situs,
        zip_code=None,
        parcel_id=pin,
        defendant=owner,
        owner_name=" & ".join(x for x in (owner, owner2) if x) or None,
        sale_date=None,
        latitude=lat,
        longitude=lng,
        # The unpaid balance is NOT a property value — it stays in
        # raw['greenville_distress']['amount_owed']. tax_value carries the
        # assessor's own market value so calc.py prices off the right number.
        tax_value=tmv,
        market_value=fmv,
        foreclosure_process="tax",
        description="; ".join(bits),
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #
async def fetch_delinquent_parcels(http) -> list[dict]:
    return await agw.query_features(
        http, PARCEL_LAYER, where=DELINQUENT_WHERE, out_fields=PARCEL_FIELDS,
        return_geometry=True, out_sr=4326, page=_PAGE, max_records=_MAX_RECORDS,
        # objectIdField is null on this MapServer, so an explicit sort is
        # REQUIRED for resultOffset paging to be stable.
        order_by="OBJECTID ASC", timeout=90.0)


async def fetch_parcels_by_pin(http, pins: list[str]) -> list[dict]:
    """Layer-52 rows for an explicit PIN list (used for tax-sale-only parcels)."""
    out: list[dict] = []
    for i in range(0, len(pins), _PIN_CHUNK):
        chunk = [p for p in pins[i:i + _PIN_CHUNK] if re.fullmatch(r"[A-Za-z0-9]+", p)]
        if not chunk:
            continue
        where = "PIN IN (" + ",".join(f"'{p}'" for p in chunk) + ")"
        try:
            out += await agw.query_features(
                http, PARCEL_LAYER, where=where, out_fields=PARCEL_FIELDS,
                return_geometry=True, out_sr=4326, page=_PAGE,
                max_records=_MAX_RECORDS, order_by="OBJECTID ASC", timeout=90.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("greenville.pin_chunk_fail", n=len(chunk), error=str(exc)[:160])
    return out


async def fetch_sales_by_pin(http, pins: list[str]) -> dict[str, dict]:
    """Latest ARMS-LENGTH sale per PIN, from layer 5. Best-effort: the join only
    adds context (street type + last true sale), so a failed chunk is logged and
    skipped rather than failing the scrape."""
    best: dict[str, dict] = {}
    for i in range(0, len(pins), _PIN_CHUNK):
        chunk = [p for p in pins[i:i + _PIN_CHUNK] if re.fullmatch(r"[A-Za-z0-9]+", p)]
        if not chunk:
            continue
        where = "PIN IN (" + ",".join(f"'{p}'" for p in chunk) + ")"
        try:
            feats = await agw.query_features(
                http, SALES_LAYER, where=where, out_fields=SALES_FIELDS,
                return_geometry=False, page=_PAGE, max_records=_MAX_RECORDS,
                order_by="OBJECTID ASC", timeout=90.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("greenville.sales_chunk_fail", n=len(chunk), error=str(exc)[:160])
            continue
        for f in feats:
            a = f.get("attributes") or {}
            pin = _normalize_parcel(a.get("PIN"))
            if not pin:
                continue
            cur = best.get(pin)
            # Prefer an arms-length sale; among equals prefer the newest.
            def rank(x: dict) -> tuple[int, int]:
                return ((_clean(x.get("TRUESALE")) or "").upper() == "YES",
                        int(x.get("SALEDATE") or 0))
            if cur is None or rank(a) > rank(cur):
                best[pin] = a
    return best


async def fetch_tax_sale(http) -> TaxSaleParse:
    r = await http.get(TAXSALE_URL, timeout=90.0)
    if r.status_code != 200:
        log.warning("greenville.taxsale_http", status=r.status_code)
        return TaxSaleParse(rows=[], unmapped=0)
    return parse_tax_sale(r.text)


def _hidden_fields(html: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(
        r'<input type="hidden" name="([^"]+)"[^>]*value="([^"]*)"', html or "")}


async def probate_search(http, state: dict[str, str], surname: str) -> list[dict[str, str]]:
    """One surname -> decedent rows. POSTs the county's own search form so we get
    a small filtered page instead of the 252 MB unfiltered index."""
    data = dict(state)
    data.update({
        "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
        "ctl00$body$txt_Name": surname,
        "ctl00$body$txt_CaseNumber": "",
        "ctl00$body$ddl_PartyTypes": PROBATE_PARTY_DECEASED,
        "ctl00$body$btn_Search": "Search",
    })
    r = await http.post(PROBATE_BASE + "Default.aspx", data=data,
                        headers={"Content-Type": "application/x-www-form-urlencoded",
                                 "Referer": PROBATE_BASE + "Default.aspx"},
                        follow_redirects=True, timeout=90.0)
    if r.status_code != 200:
        return []
    return parse_probate_rows(r.text)


async def collect_probate(http, owners_by_surname: dict[str, list[str]],
                          cap: int = 2500) -> dict[str, list[dict[str, str]]]:
    """Surname -> decedent rows, for every surname we actually hold."""
    try:
        r = await http.get(PROBATE_BASE + "Default.aspx", timeout=60.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("greenville.probate_form_fail", error=str(exc)[:160])
        return {}
    state = {k: v for k, v in _hidden_fields(r.text).items()
             if k in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")}
    if not state.get("__VIEWSTATE"):
        log.warning("greenville.probate_no_viewstate")
        return {}

    surnames = sorted(owners_by_surname)[:cap]
    sem = asyncio.Semaphore(3)
    out: dict[str, list[dict[str, str]]] = {}

    async def one(s: str) -> None:
        async with sem:
            try:
                out[s] = await probate_search(http, state, s)
            except Exception:  # noqa: BLE001
                out[s] = []
            await asyncio.sleep(0.25)      # deliberate pacing on a county server

    await asyncio.gather(*(one(s) for s in surnames))
    return out


# --------------------------------------------------------------------------- #
# scraper
# --------------------------------------------------------------------------- #
class GreenvilleHardDistress(BaseScraper):
    slug = "counties_sc.greenville_tax_distress"
    name = "Greenville County SC hard-distress parcels (delinquent tax + tax-sale roster + probate-matched owners)"
    category = "motivated_seller"
    expected_min_count = 0        # OFF by default; 0 is the normal outcome
    timeout_s = 900.0
    requires_apify = False
    optional = True

    def __init__(self) -> None:
        # Read the flag at construction so the base class reports DORMANT (an
        # intentional skip) rather than ZERO_RESULT (a source that ran and found
        # nothing). The run report must not show an out-of-scope county as a
        # suspicious zero every week.
        super().__init__()
        if os.environ.get(ENV_ON) != "1":
            self.disabled = True
            self.disabled_reason = (
                f"{ENV_ON} not set — Greenville SC is out of scope by operator "
                "direction (config.SCOPE_DENY_COUNTIES)")

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_ON) != "1":
            log.info("greenville.disabled",
                     reason=f"{ENV_ON} not set; county is out of scope by operator direction")
            return []

        now = datetime.utcnow()
        async with client(timeout=120.0) as http:
            feats = await fetch_delinquent_parcels(http)
            by_pin: dict[str, tuple[dict, dict | None]] = {}
            for f in feats:
                a = f.get("attributes") or {}
                pin = _normalize_parcel(a.get("PIN"))
                if pin:
                    by_pin[pin] = (a, f.get("geometry"))
            log.info("greenville.delinquent", features=len(feats), parcels=len(by_pin))

            try:
                ts = await fetch_tax_sale(http)
            except Exception as exc:  # noqa: BLE001
                log.warning("greenville.taxsale_fail", error=str(exc)[:160])
                ts = TaxSaleParse(rows=[], unmapped=0)
            ts_by_pin: dict[str, TaxSaleRow] = {}
            for row in ts.rows:
                ts_by_pin.setdefault(row.pin, row)
            missing = [p for p in ts_by_pin if p not in by_pin]
            log.info("greenville.tax_sale", rows=len(ts.rows), parcels=len(ts_by_pin),
                     mobile_home_or_unmapped=ts.unmapped,
                     not_in_delinquent=len(missing))

            # Tax-sale parcels the live tax roll no longer flags — pull their
            # parcel record so they arrive as full leads, not bare PINs.
            if missing:
                published = [ts_by_pin[p].map_number for p in missing]
                for f in await fetch_parcels_by_pin(http, published):
                    a = f.get("attributes") or {}
                    pin = _normalize_parcel(a.get("PIN"))
                    if pin and pin not in by_pin:
                        by_pin[pin] = (a, f.get("geometry"))

            sales = await fetch_sales_by_pin(http, [a.get("PIN") or ""
                                                    for a, _ in by_pin.values()])
            log.info("greenville.sales_join", parcels_with_sale=len(sales))

            probate_by_surname: dict[str, list[dict[str, str]]] = {}
            if os.environ.get(ENV_PROBATE) == "1":
                surs: dict[str, list[str]] = {}
                for a, _ in by_pin.values():
                    o = _clean(a.get("OWNAM1"))
                    if not o or _ENTITY.search(o) or _GOV.search(o):
                        continue
                    parts = o.split()
                    if parts:
                        surs.setdefault(parts[0], []).append(o)
                log.info("greenville.probate_start", surnames=len(surs))
                probate_by_surname = await collect_probate(http, surs)

        out: list[Listing] = []
        for pin, (attrs, geom) in by_pin.items():
            owner = _clean(attrs.get("OWNAM1"))
            pro = None
            if probate_by_surname and owner and not _ENTITY.search(owner):
                parts = owner.split()
                if parts:
                    pro = probate_match(owner, probate_by_surname.get(parts[0]) or [])
            li = build_listing(pin, attrs, geom,
                               sale=sales.get(pin),
                               tax_sale=ts_by_pin.get(pin),
                               probate=pro, now=now)
            if li:
                out.append(li)

        lanes = {"delinquent_tax": 0, "tax_sale_roster": 0, "probate_decedent_owner": 0}
        for li in out:
            for lane in li.raw["greenville_distress"]["lanes"]:
                lanes[lane] = lanes.get(lane, 0) + 1
        log.info("greenville.parsed", listings=len(out), **lanes,
                 absentee_attribute=sum(1 for li in out if li.raw.get("absentee_owner")),
                 with_situs=sum(1 for li in out if li.street_address),
                 with_coords=sum(1 for li in out if li.latitude is not None))
        return out


if __name__ == "__main__":
    async def _main() -> None:
        s = GreenvilleHardDistress()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} reason={s.last_reason!r} listings={len(rows)}")
        if not rows:
            return
        lanes: dict[str, int] = {}
        for li in rows:
            for lane in li.raw["greenville_distress"]["lanes"]:
                lanes[lane] = lanes.get(lane, 0) + 1
        print("HARD-DISTRESS lanes:", lanes)
        print("absentee (ATTRIBUTE, not a lead lane):",
              sum(1 for li in rows if li.raw.get("absentee_owner")))
        print("with situs:", sum(1 for li in rows if li.street_address),
              "with coords:", sum(1 for li in rows if li.latitude is not None),
              "with mailing:", sum(1 for li in rows if li.raw.get("owner_mailing")))
        tot = sum(li.raw["greenville_distress"]["amount_owed"] or 0 for li in rows)
        print(f"total owed: ${tot:,.2f}")
        for li in sorted(rows, key=lambda x: -(x.raw["greenville_distress"]["amount_owed"] or 0))[:10]:
            d = li.raw["greenville_distress"]
            print(f"  {li.parcel_id}  ${d['amount_owed'] or 0:>12,.2f}  "
                  f"{','.join(d['lanes']):28} {(li.owner_name or '-')[:30]:30} "
                  f"{(li.street_address or '-')[:28]}")

    asyncio.run(_main())
