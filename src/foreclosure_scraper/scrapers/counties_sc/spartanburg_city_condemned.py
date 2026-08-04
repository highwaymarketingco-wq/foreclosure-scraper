"""City of Spartanburg SC Master Condemnation List — fully-resolved condemned leads.

DISTINCT from ``counties_sc.spartanburg_condemned``, which is the COUNTY
assessor's ConditionFactor='DL' dilapidation proxy keyed on the GIS PIN
(``7143-82-7790.79``). This is the CITY's actual condemnation docket: a formal
legal action taken against a specific structure, published as a free, public,
no-login PDF from the city's document center. A condemned structure is the
strongest single property-condition signal there is — the city has declared the
building unfit and the owner is on the clock to repair or demolish.

Each row is already resolved end to end, which is rare for a code source:

    PROPERTY ADDRESS | TAX MAP | OWNER | OWNER ADDRESS | DATE CONDEMNED | INSPECTOR

so we get situs + parcel + owner-of-record + owner MAILING address + the
condemnation date in one pull, with no downstream resolver needed.

JOIN KEY: the TAX MAP column is the Spartanburg County TMS (``7-12-09-058.11``),
which is the SAME namespace ``counties_sc.spartanburg_delinquent_tax`` and
``counties_sc.spartanburg_flc`` already write (``7-16-09-062.00``). So
``parcel_id`` puts these on ``parcel:SC:spartanburg:<tms>`` and a condemned
structure MERGES onto the delinquent-tax lead at the same parcel — condemned
AND behind on taxes is about as motivated as a seller gets. (The county
``spartanburg_condemned`` source keys on the grid-style GIS PIN instead, a
pre-existing namespace split that is not bridged here.)

PARSING: the PDF is a landscape table with no ruling lines, and a single record
routinely spans several physical lines — a property with four heirs prints one
line per owner. Text-order extraction interleaves them unusably, so the parser
works off word x-coordinates: every word is assigned to a column by its x0
against boundaries measured from the real document, and a record is closed by
the line carrying the TAX MAP token. Continuation lines (extra owners, extra
owner addresses, a second line of the property address) PRECEDE their anchor
line in this document, so they are buffered and flushed into the record the
tax-map line opens.

Free + compliant: plain GET of a .gov DocumentCenter PDF. ``/DocumentCenter``
is not disallowed by https://www.cityofspartanburg.org/robots.txt (checked
2026-08-03; the file blocks /admin, /search, /map and two named bots).

Dateless for board purposes — ``date_condemned`` is the enforcement date, not a
sale date, so the slug must be in ``main.DATELESS_OK_SOURCES`` or every row is
filtered out. Gate with FORECLOSURE_SPARTANBURG_CITY_CONDEMNED=0.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Any, Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_SPARTANBURG_CITY_CONDEMNED"

PDF_URL = ("https://www.cityofspartanburg.org/DocumentCenter/View/1901/"
           "City-of-Spartanburg-Master-Condemnation-List-")
PAGE_URL = "https://www.cityofspartanburg.org/"

#: Column boundaries in PDF points, measured off the real document's word-x0
#: histogram (clean empty gutters at 130-160, 240-250, 360-370, 545-560,
#: 610-670). Landscape letter, 792pt wide.
_COLS: tuple[tuple[str, float, float], ...] = (
    ("address", 0.0, 145.0),
    ("tax_map", 145.0, 246.0),
    ("owner", 246.0, 368.0),
    ("owner_address", 368.0, 557.0),
    ("date_condemned", 557.0, 640.0),
    ("inspector", 640.0, 1e6),
)

#: Spartanburg County TMS. The list prints both '7-12-09-058.11' and the
#: dash-variant '7-12-09-058-14'; both normalize to the same dedupe key.
_TMS_RE = re.compile(r"\b(\d-\d{2}-\d{2}-\d{3}[.\-]\d{2})\b")

_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")

#: Header / footer / disclaimer chrome that must never become a record. Hitting
#: one of these also CLEARS the continuation buffer: page 1 opens with a
#: six-line disclaimer paragraph whose words spill across every column, and
#: without the reset those lines would be swept into the first real record's
#: owner list (measured: they were, before this guard).
_CHROME = re.compile(
    r"(City of Spartanburg - Condemned|DISCLAIMER|PROPERTY ADDRESS|"
    r"Updated as of|warranty|responsibility of the data user|reliability|"
    r"processed successfully on a computer|aggregate use with other data|"
    r"act of distribution|general or scientific purposes|"
    r"individual use of the data|no warranty expressed)", re.I)

#: Owners that are not sellers.
_GOV = re.compile(
    r"\b(CITY OF SPARTANBURG|COUNTY OF|STATE OF|HOUSING AUTHORITY|"
    r"REDEVELOPMENT|SCHOOL DISTRICT|UNITED STATES|SECRETARY OF)\b", re.I)

#: Structure hints printed inside the property-address cell.
_DUPLEX_RE = re.compile(r"\b(duplex|triplex|quad|apartment|apt)\b", re.I)


def _clean(v: Any) -> str | None:
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip(" ,;")
    return s or None


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    mo, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if yr < 100:
        yr += 2000
    try:
        return datetime(yr, mo, day)
    except ValueError:
        return None


def _norm_tms(s: str | None) -> str | None:
    """'7-12-09-058-14' -> '7-12-09-058.14' so both printed spellings land on
    one parcel key and match the dotted form the other Spartanburg sources use."""
    if not s:
        return None
    m = _TMS_RE.search(s)
    if not m:
        return None
    v = m.group(1)
    # The TMS is fixed-width 'D-DD-DD-DDD?DD'; the final separator is always at
    # index 11 and is printed as either '.' or '-'. Rewrite it to the dotted
    # form unconditionally so both spellings render identically (the dedupe key
    # strips punctuation and already matched, but the displayed parcel_id did
    # not, and downstream joins compare the string).
    return v[:11] + "." + v[12:]


def split_columns(words: list[dict]) -> dict[str, str]:
    """Assign one physical line's words to columns by x0."""
    cells: dict[str, list[str]] = {name: [] for name, _lo, _hi in _COLS}
    for w in sorted(words, key=lambda w: w["x0"]):
        x = w["x0"]
        for name, lo, hi in _COLS:
            if lo <= x < hi:
                cells[name].append(w["text"])
                break
    return {k: " ".join(v).strip() for k, v in cells.items()}


def is_chrome(cells: dict[str, str]) -> bool:
    return bool(_CHROME.search(" ".join(v for v in cells.values() if v)))


def page_lines(page) -> list[dict[str, str]]:
    """One dict of column cells per physical text line, top to bottom.

    Words are grouped on rounded ``top`` because pdfplumber reports sub-point
    jitter within a rendered line; the document's line pitch is ~7pt, so a 3pt
    bucket keeps distinct lines apart while collapsing jitter. Chrome lines are
    KEPT here — ``records_from_lines`` needs to see them in order to reset its
    continuation buffer at a page boundary.
    """
    buckets: dict[int, list[dict]] = {}
    for w in page.extract_words():
        buckets.setdefault(round(w["top"] / 3.0), []).append(w)
    out = []
    for key in sorted(buckets):
        cells = split_columns(buckets[key])
        if any(v for v in cells.values()):
            out.append(cells)
    return out


def records_from_lines(lines: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    """Fold physical lines into records. A line carrying a TAX MAP closes one;
    everything buffered before it is that record's continuation lines.

    OWNER AMBIGUITY (documented, not guessed at): a record with several owner
    lines is either several owners of record (heirs, joint owners, an LLC plus
    its registered agent) or ONE owner whose name wrapped. The PDF does not
    distinguish them — 'Spartanburg County Youth' / 'Sports' is a wrap, while
    'Gary & Anita Morton' / 'Cari Rodriguez' is two owners, and both print
    identically. So both readings are preserved: ``owners`` keeps the document's
    own per-line split (used for owner_name and for name->property resolution)
    and ``owner_block`` keeps the joined text (used when the split truncated a
    single long name). Nothing is thrown away and nothing is invented.
    """
    recs: list[dict[str, Any]] = []
    buf: list[dict[str, str]] = []
    for cells in lines:
        if is_chrome(cells):
            buf = []
            continue
        tms = _norm_tms(cells.get("tax_map"))
        if not tms:
            buf.append(cells)
            continue
        block = buf + [cells]
        buf = []
        addr_parts, owners, owner_addrs = [], [], []
        for c in block:
            if c.get("address"):
                addr_parts.append(c["address"])
            if c.get("owner"):
                owners.append(_clean(c["owner"]))
            if c.get("owner_address"):
                owner_addrs.append(_clean(c["owner_address"]))
        owners = [o for o in owners if o]
        recs.append({
            "tax_map": tms,
            "address": _clean(" ".join(addr_parts)),
            "owners": owners,
            "owner_block": _clean(" ".join(owners)),
            "owner_addresses": [a for a in owner_addrs if a],
            "date_condemned": _parse_date(cells.get("date_condemned")),
            "inspector": _clean(cells.get("inspector")),
        })
    return recs


def parse_pdf(data: bytes) -> list[dict[str, Any]]:
    import pdfplumber

    recs: list[dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            recs.extend(records_from_lines(page_lines(page)))
    return recs


def build_listing(rec: dict[str, Any], now: datetime | None = None) -> Listing | None:
    now = now or datetime.utcnow()
    tms = rec.get("tax_map")
    address = rec.get("address")
    if not tms and not address:
        return None

    owners = rec.get("owners") or []
    owner = owners[0] if owners else None
    if owner and _GOV.search(owner):
        return None

    mail = (rec.get("owner_addresses") or [None])[0]
    when = rec.get("date_condemned")

    raw: dict[str, Any] = {
        # raw['condemned'] is what distress_score reads as the PROPERTY
        # code_enforcement signal (w=14) — same contract the county
        # spartanburg_condemned source uses.
        "condemned": True,
        "code_enforcement": {
            "jurisdiction": "City of Spartanburg",
            "kind": "condemnation",
            "has_open": True,
            "severe": True,
            "condemned": True,
            "date_condemned": when.date().isoformat() if when else None,
            "inspector": rec.get("inspector"),
            "tax_map": tms,
            "owners": owners,
            # Joined reading of the owner cell, for the case where the per-line
            # split cut one long name in half (see records_from_lines).
            "owner_block": rec.get("owner_block"),
            "owner_addresses": rec.get("owner_addresses") or [],
            "owner_count": len(owners),
            "violation_types": ["Condemnation"],
            "open_violations": 1,
            "total_violations": 1,
            "prior_cases": 0,
            "repeat_offender": False,
            "source": "spartanburg_city_master_condemnation_list",
        },
        # A condemned structure is by definition a distressed physical asset.
        "distressed": True,
    }
    if mail:
        raw["owner_mailing"] = {
            "raw": mail,
            "source": "spartanburg_city_condemnation_list",
        }
    if len(owners) > 1:
        # Several names on one condemnation case is the classic tangled-title /
        # heirs shape — worth surfacing for the title-risk enricher.
        raw["multiple_owners"] = True

    desc = (
        "Condemned structure, City of Spartanburg SC"
        + (f" — {address}" if address else "")
        + (f"; condemned {when.date().isoformat()}" if when else "")
        + (f"; {len(owners)} owners of record" if len(owners) > 1 else "")
    )

    kind = PropertyKind.MULTI_FAMILY if address and _DUPLEX_RE.search(address) \
        else PropertyKind.UNKNOWN

    return Listing(
        source=SpartanburgCityCondemned.slug,
        source_url=PDF_URL,
        listing_type=ListingType.UNKNOWN,
        property_kind=kind,
        state="SC",
        county="Spartanburg",
        city="Spartanburg",
        street_address=address,
        parcel_id=tms,
        defendant=owner,
        owner_name=owner,
        sale_date=None,
        description=desc[:300],
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


class SpartanburgCityCondemned(BaseScraper):
    slug = "counties_sc.spartanburg_city_condemned"
    name = "City of Spartanburg SC Master Condemnation List"
    category = "motivated_seller"
    expected_min_count = 60
    timeout_s = 120.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("spartanburg_city_condemned.disabled")
            return []

        data = await get_bytes(PDF_URL, timeout=60.0)
        if not data or not data[:5].startswith(b"%PDF"):
            log.warning("spartanburg_city_condemned.not_a_pdf",
                        bytes=len(data or b""))
            return []

        recs = parse_pdf(data)
        now = datetime.utcnow()
        out: list[Listing] = []
        seen: set[str] = set()
        for rec in recs:
            li = build_listing(rec, now=now)
            if li is None:
                continue
            key = li.parcel_id or (li.street_address or "").upper()
            if key in seen:
                continue
            seen.add(key)
            out.append(li)

        log.info("spartanburg_city_condemned.parsed", records=len(recs),
                 listings=len(out),
                 with_parcel=sum(1 for li in out if li.parcel_id),
                 with_owner=sum(1 for li in out if li.owner_name),
                 with_mailing=sum(1 for li in out if li.raw.get("owner_mailing")),
                 with_date=sum(1 for li in out
                               if li.raw["code_enforcement"]["date_condemned"]))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = SpartanburgCityCondemned()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)} "
              f"parcel={sum(1 for li in rows if li.parcel_id)} "
              f"owner={sum(1 for li in rows if li.owner_name)} "
              f"mailing={sum(1 for li in rows if li.raw.get('owner_mailing'))} "
              f"dated={sum(1 for li in rows if li.raw['code_enforcement']['date_condemned'])}")
        for li in rows[:20]:
            ce = li.raw["code_enforcement"]
            print(f"  {(li.street_address or '-')[:30]:30} {li.parcel_id or '-':15} "
                  f"{ce['date_condemned'] or '-':10} n={ce['owner_count']} "
                  f"{(li.owner_name or '-')[:32]}")

    asyncio.run(_main())
