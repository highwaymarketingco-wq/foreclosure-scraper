"""Google Sheets writer. Service-account auth, idempotent re-write of the Listings tab."""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Iterable

import gspread
import structlog
from google.oauth2.service_account import Credentials

from .models import Listing

log = structlog.get_logger()

# 2026-09-23: a single `ws.update()` call with all 192,805 leads (32 cols, ~6.2M cells) hit
# gspread.exceptions.APIError: [500] Internal error -- the payload (one JSON body with every
# row) is too large for one values.update call. Writing 5,000 rows a call keeps each request
# small and lets one bad chunk retry without redoing the whole sheet.
SHEET_CHUNK_ROWS = 5000
# A spreadsheet (all its tabs combined) is capped at 10,000,000 cells by Google. The Listings
# tab is 32 columns, so today's 192,805 leads is already 6.17M cells -- most of that budget.
# 9,500,000 leaves room for the Run Log tab (tiny: 500 x 6) and about 104,000 more rows of
# growth (to ~296,875 total) before truncation would trigger, while not capping so low that a
# normal-sized board gets truncated for no reason -- the first version of this fix picked
# 4,000,000 and would have silently dropped 67,806 of today's real leads. Above the cap, write
# only the top rows (already sorted deadline-first, so the leads that matter today survive) and
# say plainly what was cut. The board itself hit this exact shape of bug once already (the git
# payload size limit, audit O1); this is the same trap in a different product, so revisit this
# constant, not just raise it again, once the board is within a run or two of it.
SHEET_CELL_CAP = 9_500_000

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

    def _sort_key(li: Listing) -> tuple:
        # Normalize sale_date to tz-naive so we can mix listings from sources
        # that emit tz-aware datetimes (e.g. ones parsed via dateutil with TZ
        # info) with sources that emit naive datetimes. Without this, sorted()
        # raises "can't compare offset-naive and offset-aware datetimes".
        sd = li.sale_date
        if sd is not None and getattr(sd, "tzinfo", None) is not None:
            sd = sd.replace(tzinfo=None)
        return (sd or datetime.max, li.state or "", li.county or "")

    listings_list = sorted(list(listings), key=_sort_key)
    for li in listings_list:
        rows.append([_to_cell(li, attr) for _, attr in COLUMNS])

    n_cols = len(COLUMNS)
    max_rows = max(1, SHEET_CELL_CAP // n_cols)
    truncated = 0
    if len(rows) > max_rows:
        truncated = len(rows) - max_rows
        rows = rows[:max_rows]
        log.warning("sheets.truncated", kept=len(rows) - 1, dropped=truncated,
                    note="over the cell cap; kept the header + earliest-deadline rows")

    # gspread auto-expands the grid on write, but resizing up front makes the row count
    # deterministic and lets a SHRINK (fewer leads than last run) drop the old trailing
    # rows too -- ws.clear() above only blanks cell content, it does not shrink the grid.
    ws.resize(rows=len(rows), cols=n_cols)

    for start in range(0, len(rows), SHEET_CHUNK_ROWS):
        chunk = rows[start:start + SHEET_CHUNK_ROWS]
        for attempt in (1, 2):
            try:
                ws.update(values=chunk, range_name=f"A{start + 1}", value_input_option="USER_ENTERED")
                break
            except gspread.exceptions.APIError:
                if attempt == 2:
                    raise
                log.warning("sheets.chunk_retry", start_row=start + 1, rows=len(chunk))
                time.sleep(5)
        if start + SHEET_CHUNK_ROWS < len(rows):
            time.sleep(1.1)  # stay comfortably under the Sheets API's per-minute write quota
    log.info("sheets.written", rows=len(rows) - 1, chunks=-(-len(rows) // SHEET_CHUNK_ROWS), truncated=truncated)

    if truncated:
        # A blank row plus a one-cell note just past the data makes a silent truncation
        # visible to whoever opens the sheet, not just to the log.
        try:
            ws.update(values=[[f"... {truncated:,} more leads not shown (cell cap). "
                                f"See the published dashboard for the full board."]],
                      range_name=f"A{len(rows) + 2}", value_input_option="USER_ENTERED")
        except gspread.exceptions.APIError:
            pass

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
