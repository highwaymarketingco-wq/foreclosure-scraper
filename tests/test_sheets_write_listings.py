"""write_listings must not lose to Google Sheets' own limits the way it did on 2026-09-23.

MEASURED that day: a single `ws.update()` call with all 192,805 leads (32 columns, about 6.2M
cells) raised `gspread.exceptions.APIError: [500] Internal error` -- one values.update request
with every row is too large. The run finished anyway (the digest email still went out), but the
"Auto-Updated Weekly" sheet Greg and Cash actually look at silently never got today's numbers.
Nothing else in the pipeline is gated on the Sheet write succeeding, so this failure mode is
easy to miss unless it is tested directly.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import gspread
import pytest

from foreclosure_scraper import sheets
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _api_error():
    resp = Mock()
    resp.json.side_effect = Exception("no body")
    resp.text = "Internal error"
    return gspread.exceptions.APIError(resp)


def _lead(i):
    return Listing(source=f"src{i}", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                    property_kind=PropertyKind.SINGLE_FAMILY, state="NC", county="Gaston",
                    street_address=f"{i} Main St", parcel_id=str(i),
                    first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw={})


class _FakeWorksheet:
    def __init__(self, existing=False):
        self.existing = existing
        self.update_calls: list[dict] = []
        self.resize_calls: list[tuple[int, int]] = []
        self.cleared = False
        self.fail_once_at_row = None   # a range_name start row to fail on the first attempt

    def clear(self):
        self.cleared = True

    def resize(self, rows=None, cols=None):
        self.resize_calls.append((rows, cols))

    def update(self, values, range_name=None, value_input_option=None):
        if self.fail_once_at_row and range_name == self.fail_once_at_row:
            self.fail_once_at_row = None  # only fail the first attempt at that range
            raise _api_error()
        self.update_calls.append({"values": values, "range_name": range_name})

    def append_row(self, values, **kwargs):
        self.update_calls.append({"append": values})


class _FakeSpreadsheet:
    def __init__(self, listings_ws, log_ws_exists=False):
        self.title = "Foreclosure Listings (Auto-Updated Weekly)"
        self._listings_ws = listings_ws
        self._log_ws_exists = log_ws_exists
        self.batch_update_calls = []

    def worksheet(self, name):
        if name == "Listings":
            return self._listings_ws
        if name == "Run Log" and self._log_ws_exists:
            return self._fake_log_ws
        raise gspread.WorksheetNotFound(name)

    def add_worksheet(self, title, rows, cols):
        ws = _FakeWorksheet()
        if title == "Run Log":
            self._fake_log_ws = ws
            self._log_ws_exists = True
        return ws

    def fetch_sheet_metadata(self):
        return {"sheets": [{"properties": {"sheetId": 1, "title": "Listings"}}]}

    def batch_update(self, body):
        self.batch_update_calls.append(body)


def _run(monkeypatch, n_listings, chunk_rows=None, cell_cap=None, fail_first_chunk=False):
    ws = _FakeWorksheet()
    if fail_first_chunk:
        ws.fail_once_at_row = "A1"
    sh = _FakeSpreadsheet(ws)
    monkeypatch.setattr(sheets, "_credentials", lambda _j: object())
    monkeypatch.setattr(gspread, "authorize", lambda _c: Mock(open_by_key=lambda _id: sh))
    monkeypatch.setattr(sheets.time, "sleep", lambda _s: None)
    if chunk_rows:
        monkeypatch.setattr(sheets, "SHEET_CHUNK_ROWS", chunk_rows)
    if cell_cap:
        monkeypatch.setattr(sheets, "SHEET_CELL_CAP", cell_cap)
    listings = [_lead(i) for i in range(n_listings)]
    url = sheets.write_listings(sheet_id="x", service_account_json="{}", listings=listings,
                                 run_summary={"total": n_listings})
    return ws, sh, url


def test_a_small_write_is_one_chunk_starting_at_a1(monkeypatch):
    ws, _sh, _url = _run(monkeypatch, 10, chunk_rows=5000)
    data_calls = [c for c in ws.update_calls if "values" in c and c["range_name"] != "A12"]
    assert len(data_calls) == 1
    assert data_calls[0]["range_name"] == "A1"
    assert len(data_calls[0]["values"]) == 11  # header + 10 rows


def test_a_large_write_splits_into_multiple_chunks_at_the_right_offsets(monkeypatch):
    ws, _sh, _url = _run(monkeypatch, 12000, chunk_rows=5000)
    ranges = [c["range_name"] for c in ws.update_calls]
    assert ranges == ["A1", "A5001", "A10001"]
    assert sum(len(c["values"]) for c in ws.update_calls) == 12001  # header + 12,000 rows


def test_the_worksheet_is_resized_before_writing_so_a_shrink_drops_old_rows(monkeypatch):
    ws, _sh, _url = _run(monkeypatch, 50, chunk_rows=5000)
    assert ws.resize_calls == [(51, 32)]  # header + 50 rows, 32 columns
    assert ws.cleared is True


def test_a_failed_chunk_retries_once_and_then_succeeds(monkeypatch):
    ws, _sh, _url = _run(monkeypatch, 10, chunk_rows=5000, fail_first_chunk=True)
    a1_writes = [c for c in ws.update_calls if c.get("range_name") == "A1"]
    assert len(a1_writes) == 1  # the retry succeeded; only the successful attempt is recorded


def test_a_chunk_that_fails_twice_raises(monkeypatch):
    ws = _FakeWorksheet()
    real_update = ws.update
    calls = {"n": 0}

    def _always_fail(values, range_name=None, value_input_option=None):
        calls["n"] += 1
        raise _api_error()

    ws.update = _always_fail
    sh = _FakeSpreadsheet(ws)
    monkeypatch.setattr(sheets, "_credentials", lambda _j: object())
    monkeypatch.setattr(gspread, "authorize", lambda _c: Mock(open_by_key=lambda _id: sh))
    monkeypatch.setattr(sheets.time, "sleep", lambda _s: None)
    with pytest.raises(gspread.exceptions.APIError):
        sheets.write_listings(sheet_id="x", service_account_json="{}",
                               listings=[_lead(1)], run_summary={})
    assert calls["n"] == 2  # exactly one retry, then it gives up


def test_over_the_cell_cap_truncates_and_leaves_a_visible_note(monkeypatch):
    # 32 columns; cap of 320 cells keeps 10 rows (320 // 32) including the header
    ws, _sh, _url = _run(monkeypatch, 50, chunk_rows=5000, cell_cap=320)
    data_calls = [c for c in ws.update_calls if c["range_name"] == "A1"]
    assert len(data_calls[0]["values"]) == 10  # header + 9 kept rows, not 51
    note_calls = [c for c in ws.update_calls if c["range_name"] not in ("A1",) and "values" in c]
    assert any("more leads not shown" in c["values"][0][0] for c in note_calls)


def test_under_the_cap_writes_everything_with_no_truncation_note(monkeypatch):
    ws, _sh, _url = _run(monkeypatch, 50, chunk_rows=5000, cell_cap=4_000_000)
    assert not any("more leads not shown" in str(c.get("values")) for c in ws.update_calls)


def test_192805_leads_writes_in_full_at_the_real_chunk_size_and_cap(monkeypatch):
    # the actual number from the 2026-09-23 failure: 192,805 rows x 32 cols = 6,169,792 cells,
    # comfortably under the real SHEET_CELL_CAP (9,500,000) -- must not be truncated
    ws, _sh, _url = _run(monkeypatch, 192805)
    data_calls = [c for c in ws.update_calls if "values" in c]
    assert sum(len(c["values"]) for c in data_calls) == 192806  # header + all 192,805 rows
    assert not any("more leads not shown" in str(c["values"]) for c in data_calls)
    assert len(data_calls) == 39  # ceil(192806 / 5000)
    assert max(len(c["values"]) for c in data_calls) <= 5000
