"""One-shot helper: create the destination Google Sheet, share with both recipients.

Usage:
    GOOGLE_SERVICE_ACCOUNT_JSON='{...}' python scripts/bootstrap_sheet.py

It prints the new Sheet ID; paste that into the SHEET_ID GitHub Action secret.
"""
from __future__ import annotations

import json
import os
import sys

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
RECIPIENTS = ["greghhigh@gmail.com", "cashrandolphhigh@gmail.com"]
SHEET_TITLE = "Foreclosure Listings (Auto-Updated Weekly)"


def main() -> int:
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        print("ERROR: set GOOGLE_SERVICE_ACCOUNT_JSON env var to the full JSON value of your service account key.")
        return 2
    info = json.loads(sa_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.create(SHEET_TITLE)
    sh.share(value=None, perm_type="anyone", role="reader", with_link=True)  # link-shareable for visibility
    for r in RECIPIENTS:
        sh.share(r, perm_type="user", role="writer", notify=True)
    print(f"\nSheet created: https://docs.google.com/spreadsheets/d/{sh.id}/edit")
    print(f"\nSHEET_ID = {sh.id}\n")
    print("Paste that ID into your GitHub Actions secret named SHEET_ID.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
