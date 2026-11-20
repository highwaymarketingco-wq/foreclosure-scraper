"""Campaign export — SMS / email / mail CSVs built from outreach.py's personalized text.

2026-11-19: _export_sms/_export_email/_export_mail each carried their own local
`st.get("owner_name") or li.defendant or li.owner_name` chain -- duplicated three times,
and ordered so the board's primary, identity.py-validated owner_name field (li.owner_name)
was read LAST: after the unvalidated nested skip_trace copy, and even after the court
defendant. A live verification pass found li.owner_name the live-confirmed-correct field
11/18 times vs. skip_trace.owner_name 4/18 when the two disagreed (see test_outreach.py for
the full evidence). Fixed by deleting the duplicated chains and delegating to the corrected
outreach._owner() (already imported here), so there is exactly one place this priority is
decided.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper import campaign_export as CE
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(skip=None, **kw):
    base = dict(source="t", source_url="http://x", listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.SINGLE_FAMILY, state="SC", county="Spartanburg",
                street_address="128 Boiler Rd", city="Spartanburg", case_number="2024CP4200111",
                defendant="SMITH JOHN", first_seen=datetime.utcnow(), last_seen=datetime.utcnow())
    base.update(kw)
    li = Listing(**base)
    li.raw = {}
    if skip:
        li.raw["skip_trace"] = skip
    return li


def test_sms_export_prefers_board_owner_name_over_stale_skip_trace(tmp_path):
    li = _li(skip={"owner_name": "WRONG STALE NAME", "phone_numbers": ["8645551212"]},
             owner_name="RIGHT BOARD NAME")
    path, n = CE._export_sms([li], tmp_path / "sms.csv")
    assert n == 1
    rows = path.read_text()
    assert "Board" in rows  # _first_name("RIGHT BOARD NAME") -> "Board"
    assert "WRONG" not in rows


def test_email_export_prefers_board_owner_name_over_stale_skip_trace(tmp_path):
    li = _li(skip={"owner_name": "WRONG STALE NAME"}, owner_name="RIGHT BOARD NAME")
    path, n = CE._export_email([li], tmp_path / "email.csv")
    assert n == 1
    rows = path.read_text()
    assert "Board" in rows
    assert "WRONG" not in rows


def test_mail_export_prefers_board_owner_name_over_stale_skip_trace(tmp_path):
    li = _li(skip={"owner_name": "WRONG STALE NAME", "owner_mailing_address": "999 Far Rd, Charlotte NC"},
             owner_name="RIGHT BOARD NAME")
    path, n = CE._export_mail([li], tmp_path / "mail.csv")
    assert n == 1
    rows = path.read_text()
    assert "RIGHT BOARD NAME" in rows
    assert "WRONG STALE NAME" not in rows


def test_exports_fall_back_to_skip_trace_when_board_owner_name_missing(tmp_path):
    """Preserves prior behavior: skip_trace.owner_name is still used (and still beats the court
    defendant) once li.owner_name itself is empty."""
    li = _li(skip={"owner_name": "SKIP TRACE NAME", "owner_mailing_address": "999 Far Rd, Charlotte NC"},
             owner_name=None)
    path, n = CE._export_mail([li], tmp_path / "mail.csv")
    assert n == 1
    assert "SKIP TRACE NAME" in path.read_text()


def test_exports_skipped_when_no_owner_name_available_at_all(tmp_path):
    li = _li(skip={"owner_mailing_address": "999 Far Rd, Charlotte NC"}, owner_name=None, defendant=None)
    path, n = CE._export_mail([li], tmp_path / "mail.csv")
    assert n == 0
