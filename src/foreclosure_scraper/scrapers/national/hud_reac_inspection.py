"""HUD REAC physical-inspection scores — distressed multifamily (NC + SC).

Fills the national_multifamily track with a *condition-distress* signal that no
other source provides: HUD's Real Estate Assessment Center publishes the
physical-inspection score history for every HUD-assisted/insured multifamily
property. A low REAC score (failing health/safety + capital-needs inspection)
is a hard motivated-owner / forced-disposition signal — chronically failing
properties get put up for sale, transferred, or pushed into enforcement.

Source (live-verified 2026-06)
------------------------------
``https://www.hud.gov/sites/default/files/Housing/documents/MF-Inspection-Report.xls``
is a free, no-login ~8 MB legacy OLE2/BIFF8 ``.xls`` (linked from the HUD
"Multifamily Housing - Physical Inspection Scores By State" page,
hud.gov/stat/mfh/inspection-scores). One worksheet, ~26,077 data rows nationally
(1,005 NC + 448 SC). Columns:

    REMS Property Id | has_active_financing_ind | has_active_assistance_ind |
    Inspection Id 1 | Inspection Score1 | Release Date 1 |
    Inspection Id 2 | Inspection Score2 | Release Date 2 |
    Inspection Id 3 | Inspection Score3 | Release Date 3 |
    Property Name | state_name_text | City | state_code

"Inspection Score1" is the *latest* of the (up to) three inspections. Scores are
strings like ``"91a"`` / ``"72c"`` / ``"46"`` — a 0-100 number with an optional
trailing grade letter (a/b/c). We parse the leading integer as the score.
"Release Date N" is an Excel 1900-system serial number.

Parsing
-------
The venv ships no Excel engine (``xlrd`` 2.x dropped ``.xls`` anyway), so the
file is decoded by the self-contained OLE2/BIFF8 reader in
``foreclosure_scraper._vendor.xls`` — free, offline, zero install risk at the
daily run.

Emit model
----------
  * Filter ``state_code in (NC, SC)`` AND map City -> in-footprint county
    (upstate/WNC gazetteer + coastal lookup). Rows whose city can't be mapped to
    an in-footprint county are dropped (county stays None -> denied by the
    orchestrator scope gate), matching the project's footprint rule.
  * Every kept row -> ``property_kind=MULTI_FAMILY``, ``listing_type=DISTRESSED``,
    ``owner_name`` + a Property-Name-as-street so the row displays/dedupes on
    something stable, ``case_number = "reac-<REMS id>"``.
  * Distress flag: ``raw.reac.distressed = True`` when the latest score <= 60
    (the HUD failing-condition threshold). 61 such NC/SC properties exist in the
    current file (e.g. Spartanburg Scattered Sites = 46).
  * ``source_url`` = the HUD multifamily inspection-scores page (the dataset),
    since the .xls carries no per-property detail page.

Free, no auth, no Apify, no CAPTCHA/login defeat.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes
from ...models import Listing, ListingType, PropertyKind
from ..._upstate_city_to_county import upstate_county_for
from ..._coastal_city_to_county import coastal_county_for
from ..._vendor.xls import XlsParseError, read_first_sheet

log = structlog.get_logger()

# Direct download (legacy OLE2 .xls) + the human dataset page used as source_url.
XLS_URL = (
    "https://www.hud.gov/sites/default/files/Housing/documents/"
    "MF-Inspection-Report.xls"
)
DATASET_URL = "https://www.hud.gov/stat/mfh/inspection-scores"

# HUD's failing-condition line. A latest score at or below this flags distress.
DISTRESS_THRESHOLD = 60

# Excel 1900 date system epoch (with the well-known 1900-leap-year off-by-one:
# serial 1 == 1900-01-01, so the base is 1899-12-30).
_EXCEL_EPOCH = datetime(1899, 12, 30)

_SCORE_RE = re.compile(r"(\d+)")


def _parse_score(raw) -> int | None:
    """'91a' / '72c' / '46' / 91.0 -> leading integer score, else None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return int(raw)
        except (ValueError, OverflowError):
            return None
    m = _SCORE_RE.search(str(raw))
    return int(m.group(1)) if m else None


def _excel_serial_to_dt(raw) -> datetime | None:
    """Excel 1900-system serial number -> datetime, or None."""
    if raw is None:
        return None
    try:
        serial = float(raw)
    except (TypeError, ValueError):
        return None
    if serial <= 0:
        return None
    try:
        return _EXCEL_EPOCH + timedelta(days=serial)
    except (OverflowError, ValueError):
        return None


def _county_for(city: str | None, state: str) -> str | None:
    """In-footprint county for a city, or None (upstate/WNC then coastal)."""
    if not city:
        return None
    return upstate_county_for(city, state) or coastal_county_for(city, state)


def _row_to_listing(row: dict) -> Listing | None:
    state = (row.get("state_code") or "").strip().upper()
    if state not in ("NC", "SC"):
        return None

    city = (row.get("City") or "").strip() or None
    county = _county_for(city, state)
    if not county:
        # Out-of-footprint (or unmappable city) — would be denied by the scope
        # gate anyway. Drop here so we don't emit thousands of dead rows.
        return None

    name = (row.get("Property Name") or "").strip() or None
    if not name:
        return None

    rems_raw = row.get("REMS Property Id")
    try:
        rems = str(int(float(rems_raw))) if rems_raw is not None else None
    except (TypeError, ValueError):
        rems = str(rems_raw).strip() if rems_raw is not None else None

    # The three (score, release-date) pairs, newest first (column "1" = latest).
    inspections = []
    for n in (1, 2, 3):
        sc = _parse_score(row.get(f"Inspection Score{n}"))
        dt = _excel_serial_to_dt(row.get(f"Release Date {n}"))
        insp_id = row.get(f"Inspection Id {n}")
        if sc is None and dt is None:
            continue
        try:
            insp_id = str(int(float(insp_id))) if insp_id is not None else None
        except (TypeError, ValueError):
            insp_id = str(insp_id).strip() if insp_id is not None else None
        inspections.append(
            {
                "n": n,
                "score": sc,
                "inspection_id": insp_id,
                "release_date": dt.date().isoformat() if dt else None,
            }
        )

    latest_score = next((i["score"] for i in inspections if i["score"] is not None), None)
    latest_dt = next((i["release_date"] for i in inspections if i["release_date"]), None)
    # Distress = literal latest score <= 60 (HUD failing-condition line). Kept
    # literal so the count matches HUD's published view exactly.
    distressed = latest_score is not None and latest_score <= DISTRESS_THRESHOLD
    # A handful of rows carry a latest score of 0 while an earlier cycle has a
    # real score (e.g. "0" then "47") — that 0 is a not-scored placeholder, not
    # a genuine failing inspection. Flag it so a downstream consumer can choose
    # to fall back to the prior real score instead of trusting the 0.
    prior_real = next(
        (i["score"] for i in inspections if i["score"] is not None and i["score"] > 0),
        None,
    )
    latest_is_placeholder_zero = latest_score == 0 and prior_real is not None

    sale_date = None
    if latest_dt:
        try:
            sale_date = datetime.fromisoformat(latest_dt)
        except ValueError:
            sale_date = None

    desc_bits = ["HUD REAC physical-inspection multifamily"]
    if latest_score is not None:
        desc_bits.append(f"latest score {latest_score}")
    if distressed:
        desc_bits.append(f"FAILING (<= {DISTRESS_THRESHOLD})")
    description = " — ".join(desc_bits)

    now = datetime.utcnow()
    return Listing(
        source="national.hud_reac_inspection",
        source_url=DATASET_URL,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.MULTI_FAMILY,
        # No street address in the dataset — use the property name so the row
        # has a stable display + dedupe value (parcel/address are absent).
        street_address=name,
        city=city,
        county=county,
        state=state,
        owner_name=name,
        case_number=f"reac-{rems}" if rems else None,
        sale_date=sale_date,  # latest inspection release date (best available)
        description=description,
        first_seen=now,
        last_seen=now,
        raw={
            "reac": {
                "rems_property_id": rems,
                "property_name": name,
                "latest_score": latest_score,
                "latest_release_date": latest_dt,
                "prior_real_score": prior_real,
                "latest_is_placeholder_zero": latest_is_placeholder_zero,
                "distressed": distressed,
                "distress_threshold": DISTRESS_THRESHOLD,
                "scores": inspections,
                "has_active_financing": row.get("has_active_financing_ind"),
                "has_active_assistance": row.get("has_active_assistance_ind"),
                "xls_source": XLS_URL,
            }
        },
    )


class HudReacInspection(BaseScraper):
    slug = "national.hud_reac_inspection"
    name = "HUD REAC Inspection Scores (Multifamily, NC/SC)"
    category = "national_multifamily"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    # One ~8 MB download + an in-memory BIFF8 parse of ~26k rows. Generous
    # headroom for a slow HUD CDN response.
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        data = await get_bytes(XLS_URL, timeout=120.0)
        log.info("hud_reac.downloaded", bytes=len(data))
        try:
            rows = read_first_sheet(data)
        except XlsParseError as exc:
            log.warning("hud_reac.parse_failed", error=str(exc)[:200])
            return []
        log.info("hud_reac.rows", total=len(rows))

        out: list[Listing] = []
        distressed = 0
        for row in rows:
            li = _row_to_listing(row)
            if li is None:
                continue
            out.append(li)
            if li.raw.get("reac", {}).get("distressed"):
                distressed += 1
        log.info(
            "hud_reac.done",
            in_footprint=len(out),
            distressed=distressed,
            nc=sum(1 for li in out if li.state == "NC"),
            sc=sum(1 for li in out if li.state == "SC"),
        )
        return out
