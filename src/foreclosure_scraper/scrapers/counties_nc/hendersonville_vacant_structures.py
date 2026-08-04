"""City of Hendersonville NC vacant / condemned structures register.

The city's code-enforcement office maintains a standing register of vacant
structures it is working cases on, published as a free, public, anonymous
ArcGIS FeatureServer (``VACANT_STRUCTURES_7_24_24``, layer alias "VACANT
PROPERTIES"). Every row is a structure a code officer has physically visited
and written up: whether anyone is living in it, whether it is boarded, whether
it has been condemned, whether the taxes are behind, what the utility meter is
doing, and whether a Notice of Violation has gone out — plus the owner of
record and the owner's mailing address.

That combination is the highest-intent shape in the whole book: an empty,
deteriorating building whose owner is not local and has already been sent a
letter by the city. It is also a proper public record — a code-enforcement
case file, the same class of document as the Henderson County ordinance
violations already wired up in ``counties_nc.henderson_code_violations``.

PRIVACY — DELIBERATE FIELD OMISSION (this is load-bearing, do not "fix" it):
    This layer also carries ``PHONE__`` and ``EMAIL`` columns, and an unlabeled
    ``column19`` of unknown contents. None of the three are requested. Personal
    contact details are NOT property-record data and are out of scope for this
    engine regardless of the fact that the endpoint would hand them over.
    ``outFields`` is enumerated explicitly and ``arcgis_webmap.query_features``
    hard-rejects ``"*"``, so there is no path by which those columns can be
    pulled in by accident. OWNER and MAILING_ADDRESS ARE taken: those are the
    owner of record and service address on a condemnation case, i.e. ordinary
    property-record fields.

    Separately: this dataset is NOT the city's utility-billing system. The
    ``UTILITIES`` column here is a code officer's free-text case note about the
    meter ("METER PULLED FEB 2020", "NO WATER USAGE IN 3 YRS") — a vacancy-
    duration observation. It carries no account numbers and no customer
    identifiers, and nothing in this module touches a billing endpoint.

    Omitting the contact COLUMNS is necessary but NOT sufficient: officers type
    contact details into the free-text cells. One live row carries an owner's
    personal email inside ``NOTES`` ("BUILDING IS VACANT - <address>@att.net").
    So every free-text value that survives into ``raw`` is run through
    :func:`scrub_contact`, which strips email addresses and phone numbers
    before the value is ever written. ``test_hendersonville_vacant_structures``
    asserts on the live payload that neither pattern can reach the board.

JOIN KEY — ADDRESS, NOT PARCEL: the layer publishes no PIN, so these land on
the ``addr:<normalized street>|NC:henderson`` dedupe key. ``zip_code`` is left
NULL on purpose: the only ZIP in the row is the OWNER'S MAILING zip, and
stamping that onto the listing would build the dedupe key off the wrong
property and both miss real merges and invent false ones.

Free + compliant: anonymous ArcGIS REST, no key, no login, no CAPTCHA/WAF.
Dateless standing register -> the slug must be in ``main.DATELESS_OK_SOURCES``
or every row is filtered out. Gate with FORECLOSURE_HENDERSONVILLE_VACANT=0.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Iterable

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_HENDERSONVILLE_VACANT"

LAYER = ("https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/"
         "VACANT_STRUCTURES_7_24_24/FeatureServer/0")

PAGE_URL = "https://www.hvlnc.gov/departments/development-assistance"

#: EXPLICIT allow-list. PHONE__, EMAIL and column19 exist on the layer and are
#: intentionally absent — see the PRIVACY note in the module docstring.
_FIELDS = (
    "FID", "DATE", "ADDRESS", "City", "State",
    "OCCUPIED", "BOARDED_UP", "CONDEMNED", "DELINQUENT_TAX", "UTILITIES",
    "NOV___CONTACT_LETTER_SENT", "CODE_COLOR", "NOTES",
    "OWNER", "MAILING_ADDRESS", "MAIL_CITY", "ST", "ZIP",
)
_OUT_FIELDS = ",".join(_FIELDS)

#: Columns on this layer that must never be requested.
FORBIDDEN_FIELDS = ("PHONE__", "EMAIL", "column19")

_PAGE = 1000

_NO = re.compile(r"^(no|n|none|n/?a|0)$", re.I)
_YES = re.compile(r"^(yes|y|true)$", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONEY_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
_DEMO_RE = re.compile(r"\bdemo(?:ed|lished|lition)?\b", re.I)

#: Government / institutional owners are not sellers.
_GOV = re.compile(
    r"\b(CITY OF|TOWN OF|COUNTY OF|STATE OF|HOUSING AUTHORITY|NCDOT|"
    r"SCHOOL|UNITED STATES|DEPARTMENT OF|HENDERSON COUNTY)\b", re.I)


#: Personal-contact patterns that must never survive out of a free-text cell.
#: The layer's dedicated PHONE__/EMAIL columns are simply not requested, but
#: officers also paste contact details into NOTES/UTILITIES free text, so every
#: free-text value is scrubbed on the way into raw. Live example (2026-08-03):
#: 115 RHODES ST carries an owner's personal email inside NOTES.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")


def scrub_contact(s: str | None) -> str | None:
    """Remove email addresses and phone numbers from a free-text cell.

    Returns None if scrubbing empties the value. Deliberately blunt: a false
    positive costs a note, a false negative puts personal contact data on the
    board. Cheap side benefit — a bare 10-digit run is stripped too, and no
    field on this layer legitimately carries one.
    """
    if s is None:
        return None
    out = _PHONE_RE.sub("[redacted]", _EMAIL_RE.sub("[redacted]", s))
    out = re.sub(r"[\s,;:/-]*\[redacted\]", " [redacted]", out)
    out = re.sub(r"\s+", " ", out).strip(" ,;:-")
    return out or None


def _clean(v: Any) -> str | None:
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _text(v: Any) -> str | None:
    """:func:`_clean` for values that reach ``raw`` as free text — scrubbed."""
    return scrub_contact(_clean(v))


def _tri(v: Any) -> bool | None:
    """A YES/NO/blank column -> True / False / None (unknown). Anything that is
    neither (a date, 'PRTL', 'POSSIBLY IN 2022') reads as True: the officer
    wrote something affirmative in a yes/no box."""
    s = _clean(v)
    if s is None:
        return None
    if _NO.match(s):
        return False
    if _YES.match(s):
        return True
    if s.upper() in ("UNKNOWN", "UNK", "?"):
        return None
    return True


def _date_in(v: Any) -> str | None:
    """ISO date out of a free-text cell ('6/30/2022 12:00:00 AM', '11/9/2022
    POSTED') or an ArcGIS DateOnly string ('2023-07-25')."""
    s = _clean(v)
    if not s:
        return None
    m = _DATE_RE.search(s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(1)),
                            int(m.group(2))).date().isoformat()
        except ValueError:
            return None
    m2 = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    return m2.group(0) if m2 else None


def _tax_note(v: Any) -> dict[str, Any] | None:
    """The DELINQUENT_TAX cell is free text: '2022 - DUE $659.41',
    '2022- $612.87  2021 - $726.94', 'PAID', 'CURRENT', 'DEMOED', 'NO', '0'."""
    s = _clean(v)
    if not s:
        return None
    up = s.upper()
    amounts = [float(a.replace(",", "")) for a in _MONEY_RE.findall(s)]
    delinquent = bool(amounts)
    if not delinquent and up not in ("PAID", "CURRENT", "DEMOED") and not _NO.match(s):
        # Something was written that is neither a clearance nor a dollar figure.
        delinquent = None
    return {
        "note": scrub_contact(s),
        "delinquent": delinquent,
        "amount_owed": max(amounts) if amounts else None,
        "total_noted": round(sum(amounts), 2) if amounts else None,
        "years": sorted({int(y) for y in re.findall(r"\b(20\d{2})\b", s)}) or None,
    }


def _is_absentee(a: dict) -> bool:
    """Owner mails from outside Hendersonville, from another state, or a PO box."""
    st = (a.get("ST") or "").strip().upper()
    if st and st != "NC":
        return True
    street = (a.get("MAILING_ADDRESS") or "").strip().upper()
    if re.search(r"\bP\.?\s?O\.?\s?BOX\b", street):
        return True
    city = (a.get("MAIL_CITY") or "").strip().upper()
    if city and city != "HENDERSONVILLE":
        return True
    # Same city but a different street than the vacant structure.
    situs = (a.get("ADDRESS") or "").strip().upper()
    if street and situs and street.split()[:2] != situs.split()[:2]:
        return True
    return False


def build_listing(feat: dict, now: datetime | None = None) -> Listing | None:
    now = now or datetime.utcnow()
    a = feat.get("attributes") or {}
    address = _clean(a.get("ADDRESS"))
    if not address:
        return None

    owner = _text(a.get("OWNER"))
    if owner and _GOV.search(owner):
        return None

    occupied = _tri(a.get("OCCUPIED"))
    boarded = _tri(a.get("BOARDED_UP"))
    condemned = _tri(a.get("CONDEMNED"))
    condemned_on = _date_in(a.get("CONDEMNED"))
    nov = _tri(a.get("NOV___CONTACT_LETTER_SENT"))
    nov_on = _date_in(a.get("NOV___CONTACT_LETTER_SENT"))
    # Free text -> scrubbed of emails/phone numbers before it can reach raw.
    notes = _text(a.get("NOTES"))
    utilities = _text(a.get("UTILITIES"))
    tax = _tax_note(a.get("DELINQUENT_TAX"))
    demolished = bool(_DEMO_RE.search(" ".join(
        x for x in (notes, _clean(a.get("DELINQUENT_TAX"))) if x)))

    geom = feat.get("geometry") or {}
    lat = float(geom["y"]) if geom.get("y") is not None else None
    lng = float(geom["x"]) if geom.get("x") is not None else None

    raw: dict[str, Any] = {
        # Same contract distress_score reads for the PROPERTY signal (w=14).
        "code_enforcement": {
            "jurisdiction": "City of Hendersonville",
            "kind": "vacant_structure_register",
            "has_open": not demolished,
            "condemned": condemned,
            "condemned_date": condemned_on,
            "boarded_up": boarded,
            "occupied": occupied,
            "nov_sent": nov,
            "nov_date": nov_on,
            "code_color": _text(a.get("CODE_COLOR")),
            "utility_status": utilities,
            "notes": notes,
            "demolished": demolished,
            "listed_date": _date_in(a.get("DATE")),
            "violation_types": ["Vacant Structure"] + (["Condemnation"] if condemned else []),
            "open_violations": 0 if demolished else 1,
            "source": "hendersonville_vacant_structures_register",
        },
        "vacancy": {
            # occupied is False -> confirmed vacant by a code officer on site.
            "vacant": (occupied is False) or None,
            "boarded_up": boarded,
            "utility_status": utilities,
            "source": "hendersonville_vacant_structures_register",
        },
    }
    if condemned:
        raw["condemned"] = True
    if (occupied is False) or boarded or condemned:
        raw["distressed"] = True
    if tax:
        raw["hendersonville_delinquent_tax"] = tax
    if owner:
        raw["owner_mailing"] = {
            "street": _text(a.get("MAILING_ADDRESS")),
            "city": _clean(a.get("MAIL_CITY")),
            "state": _clean(a.get("ST")),
            "zip": (_clean(a.get("ZIP")) or "")[:5] or None,
            "source": "hendersonville_vacant_structures_register",
        }
        if _is_absentee(a):
            raw["absentee_owner"] = True
    if demolished:
        # The structure is gone; the LOT and its absentee owner remain a lead.
        raw["code_enforcement"]["has_open"] = False

    bits = []
    if occupied is False:
        bits.append("vacant")
    if boarded:
        bits.append("boarded up")
    if condemned:
        bits.append("condemned" + (f" {condemned_on}" if condemned_on else ""))
    if tax and tax.get("delinquent"):
        bits.append("delinquent taxes"
                    + (f" ${tax['amount_owed']:,.2f}" if tax.get("amount_owed") else ""))
    if nov:
        bits.append("notice of violation sent")
    if demolished:
        bits.append("structure demolished")
    desc = ("Hendersonville NC vacant-structure register — "
            + (", ".join(bits) if bits else "open case")
            + (f"; owner {owner}" if owner else ""))

    return Listing(
        source=HendersonvilleVacantStructures.slug,
        source_url=PAGE_URL,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.LAND if demolished else PropertyKind.UNKNOWN,
        state="NC",
        county="Henderson",
        city=_clean(a.get("City")) or "Hendersonville",
        street_address=address,
        # zip_code stays NULL — the row's only ZIP is the OWNER'S mailing zip
        # and using it would key the listing off the wrong property.
        zip_code=None,
        parcel_id=None,
        defendant=owner,
        owner_name=owner,
        sale_date=None,
        latitude=lat,
        longitude=lng,
        description=desc[:300],
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


class HendersonvilleVacantStructures(BaseScraper):
    slug = "counties_nc.hendersonville_vacant_structures"
    name = "City of Hendersonville NC Vacant / Condemned Structures Register"
    category = "motivated_seller"
    expected_min_count = 40
    timeout_s = 120.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("hendersonville_vacant.disabled")
            return []

        assert not any(f in _OUT_FIELDS for f in FORBIDDEN_FIELDS), \
            "personal-contact columns must never be requested"

        async with client(timeout=45.0) as http:
            feats = await agw.query_features(
                http, LAYER, where="1=1", out_fields=_OUT_FIELDS,
                return_geometry=True, out_sr=4326, order_by="FID ASC",
                page=_PAGE, max_records=5000)

        now = datetime.utcnow()
        out: list[Listing] = []
        seen: set[str] = set()
        for ft in feats:
            li = build_listing(ft, now=now)
            if li is None:
                continue
            key = (li.street_address or "").upper()
            if key in seen:
                continue
            seen.add(key)
            out.append(li)

        log.info("hendersonville_vacant.parsed", features=len(feats), listings=len(out),
                 vacant=sum(1 for li in out if li.raw["vacancy"]["vacant"]),
                 condemned=sum(1 for li in out if li.raw.get("condemned")),
                 boarded=sum(1 for li in out if li.raw["vacancy"]["boarded_up"]),
                 tax=sum(1 for li in out if li.raw.get("hendersonville_delinquent_tax")),
                 absentee=sum(1 for li in out if li.raw.get("absentee_owner")),
                 with_owner=sum(1 for li in out if li.owner_name))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = HendersonvilleVacantStructures()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)} "
              f"vacant={sum(1 for li in rows if li.raw['vacancy']['vacant'])} "
              f"condemned={sum(1 for li in rows if li.raw.get('condemned'))} "
              f"boarded={sum(1 for li in rows if li.raw['vacancy']['boarded_up'])} "
              f"tax={sum(1 for li in rows if li.raw.get('hendersonville_delinquent_tax'))} "
              f"absentee={sum(1 for li in rows if li.raw.get('absentee_owner'))} "
              f"owner={sum(1 for li in rows if li.owner_name)}")
        for li in rows[:20]:
            ce = li.raw["code_enforcement"]
            print(f"  {(li.street_address or '-')[:26]:26} "
                  f"vac={str(li.raw['vacancy']['vacant']):5} "
                  f"cond={str(ce['condemned']):5} brd={str(ce['boarded_up']):5} "
                  f"{'ABS' if li.raw.get('absentee_owner') else '   '} "
                  f"{(li.owner_name or '-')[:30]}")

    asyncio.run(_main())
