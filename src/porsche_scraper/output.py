"""Serialize listings to JSON / CSV."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Listing


CSV_FIELDS = (
    "project_tier",
    "source",
    "year",
    "model",
    "trim",
    "title",
    "price_usd",
    "current_bid_usd",
    "mileage",
    "title_status",
    "drivable",
    "location",
    "seller_type",
    "vin",
    "listing_id",
    "source_url",
    "photo_url",
    "first_seen",
)


def write_json(path: str | Path, listings: list[Listing]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = [json.loads(l.model_dump_json()) for l in listings]
    Path(path).write_text(json.dumps(data, indent=2, default=str))


def write_csv(path: str | Path, listings: list[Listing]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for l in listings:
            row = {k: getattr(l, k, None) for k in CSV_FIELDS}
            row["title_status"] = l.title_status.value if l.title_status else None
            w.writerow(row)
