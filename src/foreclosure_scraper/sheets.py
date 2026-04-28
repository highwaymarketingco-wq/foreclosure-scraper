"""Google Sheets writer. Service-account auth, idempotent re-write of the Listings tab."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

import gspread
import structlog
from google.oauth2.service_account import Credentials

from .models import Listing

log = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Sheet column order. Keep stable so users can save filter views.
COLUMNS: list[tuple[str, str]] = [
    ("Sale Date", "sale_date"),
    ("Type", "listing_type"),
    ("Property Kind", "property_kind"),
    ("Address", "_display_address"),
    ("County", "county"),
    ("State", "state"),
    ("ZIP", "zip_code"),
    ("Parcel ID", "parcel_id"),
    ("Opening Bid", "opening_bid"),
    ("Judgment", "judgment_amount"),
    ("Zillow Zestimate (ceiling)", "_zest"),
    ("Tax Assessed Value", "tax_value"),
    ("Bid / Zestimate %", "_bid_to_zest"),
    ("Flags", "_flags"),
    ("Bedrooms", "bedrooms"),
    ("Bathrooms", "bathrooms"),
    ("Living SqFt", "living_sqft"),
    ("Year Built", "year_built"),
    ("Acreage", "acreage"),
    ("Zoning", "zoning"),
    ("Description", "description"),
    ("Plaintiff", "plaintiff"),
    ("Defendant", "defendant"),
    ("Trustee", "trustee"),
    ("Case Number", "case_number"),
    ("Sale Time", "sale_time"),
    ("Sale Location", "sale_location"),
    ("Auction Status", "auction_status"),
    ("Source", "source"),
    ("Source URL", "source_url"),
    ("First Seen", "first_seen"),
    ("Last Seen", "last_seen"),
]


def _to_cell(li: Listing, attr: str) -> str:
    if attr == "_display_address":
        return li.display_address()
    if attr == "_zest":
        z = (li.raw.get("zillow") or {}) if isinstance(li.raw, dict) else {}
        v = z.get("zestimate") or li.market_value
        return str(int(v)) if v else ""
    if attr == "_bid_to_zest":
        z = (li.raw.get("zillow") or {}) if isinstance(li.raw, dict) else {}
        zest = z.get("zestimate") or li.market_value
        if zest and li.opening_bid:
            return f"{(li.opening_bid / zest * 100):.0f}%"
        return ""
    if attr == "_flags":
        flags = li.raw.get("flags") if isinstance(li.raw, dict) else []
        return ", ".join(flags[:6]) if flags else ""
    val = getattr(li, attr, None)
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    if hasattr(val, "value"):  # Enum
        return str(val.value)
    return str(val)


def _credentials(service_account_json: str) -> Credentials:
    info = json.loads(service_account_json)
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def write_listings(
    *,
    sheet_id: str,
    service_account_json: str,
    listings: Iterable[Listing],
    run_summary: dict,
) -> str:
    """Write listings to the Sheet. Returns the Sheet URL."""
    creds = _credentials(service_account_json)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    log.info("sheets.opened", title=sh.title)

    # Listings tab
    try:
        ws = sh.worksheet("Listings")
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Listings", rows="2000", cols=str(len(COLUMNS)))

    rows: list[list[str]] = [[label for label, _ in COLUMNS]]
    listings_list = sorted(
        list(listings),
        key=lambda li: (li.sale_date or datetime.max, li.state or "", li.county or ""),
    )
    for li in listings_list:
        rows.append([_to_cell(li, attr) for _, attr in COLUMNS])

    ws.update(values=rows, range_name="A1", value_input_option="USER_ENTERED")

    # Format header + freeze
    sheet_meta = sh.fetch_sheet_metadata()
    ws_id = next(s["properties"]["sheetId"] for s in sheet_meta["sheets"] if s["properties"]["title"] == "Listings")
    sh.batch_update(
        {
            "requests": [
                {
                    "repeatCell": {
                        "range": {"sheetId": ws_id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.83},
                                "textFormat": {"bold": True},
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)",
                    }
                },
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": ws_id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": ws_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": len(COLUMNS),
                        }
                    }
                },
            ]
        }
    )

    # Run Log tab
    try:
        log_ws = sh.worksheet("Run Log")
    except gspread.WorksheetNotFound:
        log_ws = sh.add_worksheet(title="Run Log", rows="500", cols="6")
        log_ws.update(
            values=[["Run Time (UTC)", "Total Listings", "By State", "By Source", "Errors", "Notes"]],
            range_name="A1",
        )
    log_ws.append_row(
        [
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            run_summary.get("total", 0),
            json.dumps(run_summary.get("by_state", {})),
            json.dumps(run_summary.get("by_source", {})),
            json.dumps(run_summary.get("errors", [])),
            run_summary.get("notes", ""),
        ],
        value_input_option="USER_ENTERED",
    )

    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
