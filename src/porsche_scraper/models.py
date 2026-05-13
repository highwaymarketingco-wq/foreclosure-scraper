"""Unified Porsche listing schema."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TitleStatus(str, Enum):
    CLEAN = "clean"
    SALVAGE = "salvage"
    REBUILT = "rebuilt"
    PARTS_ONLY = "parts_only"
    FLOOD = "flood"
    LEMON = "lemon"
    UNKNOWN = "unknown"


# Models we explicitly DO NOT want. Lower-cased substring match against
# title + model fields. "718" Cayman/Boxster and "911" are wanted; only
# the SUV / sedan lines are filtered out.
EXCLUDED_MODELS = ("panamera", "cayenne", "macan")


# Words in the title that suggest the car is not drivable as-is.
# Used both as a filter signal and to set Listing.drivable=False.
NON_DRIVABLE_KEYWORDS = (
    "parts only",
    "parts car",
    "for parts",
    "no motor",
    "no engine",
    "no transmission",
    "non running",
    "non-running",
    "non runner",
    "not running",
    "doesn't run",
    "does not run",
    "won't start",
    "blown engine",
    "blown motor",
    "seized engine",
    "seized motor",
    "needs engine",
    "shell only",
    "rolling shell",
    "rolling chassis",
    "stripped",
    "burned",
    "burnt",
    "fire damage",
)


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MILES_RE = re.compile(r"([\d,]+)\s*(?:mi|miles|mile|k\b)", re.IGNORECASE)
_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


def parse_year(text: str | None) -> int | None:
    if not text:
        return None
    m = _YEAR_RE.search(text)
    return int(m.group(0)) if m else None


def parse_price(text: str | None) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = _PRICE_RE.search(str(text))
    if not m:
        # Try a raw number fallback ("45000")
        digits = re.sub(r"[^\d.]", "", str(text))
        return float(digits) if digits else None
    return float(m.group(1).replace(",", ""))


def parse_miles(text: str | None) -> int | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    s = str(text).strip().lower()
    m = _MILES_RE.search(s)
    if not m:
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else None
    num = m.group(1).replace(",", "")
    val = float(num)
    if "k" in s and val < 1000:  # "85k mi"
        val *= 1000
    return int(val)


def infer_title_status(text: str | None) -> TitleStatus:
    if not text:
        return TitleStatus.UNKNOWN
    s = text.lower()
    if "parts only" in s or "parts car" in s:
        return TitleStatus.PARTS_ONLY
    if "rebuilt" in s or "reconstructed" in s:
        return TitleStatus.REBUILT
    if "salvage" in s:
        return TitleStatus.SALVAGE
    if "flood" in s:
        return TitleStatus.FLOOD
    if "lemon" in s:
        return TitleStatus.LEMON
    if "clean" in s or "clear" in s:
        return TitleStatus.CLEAN
    return TitleStatus.UNKNOWN


def infer_drivable(title: str | None, title_status: TitleStatus) -> bool | None:
    """Return False if known non-drivable, True if known drivable, None if unclear.

    Title-status PARTS_ONLY always implies non-drivable. Otherwise we look
    for keywords in the listing title.
    """
    if title_status == TitleStatus.PARTS_ONLY:
        return False
    if not title:
        return None
    s = title.lower()
    if any(kw in s for kw in NON_DRIVABLE_KEYWORDS):
        return False
    return None  # Default to unknown; filter treats unknown as acceptable.


class Listing(BaseModel):
    """A single Porsche for sale across any source."""

    model_config = ConfigDict(extra="ignore")

    source: str  # e.g. "cars_com", "bring_a_trailer"
    source_url: str
    listing_id: str | None = None  # Source-stable id (VIN, stock #, lot #)

    title: str
    year: int | None = None
    make: str = "Porsche"
    model: str | None = None  # "911", "Cayman", "Boxster", "718", "924", ...
    trim: str | None = None

    price_usd: float | None = None
    current_bid_usd: float | None = None  # For auction listings
    mileage: int | None = None

    location: str | None = None  # "Charlotte, NC" or "Yard 123, FL"
    seller_type: str | None = None  # dealer | private | auction | salvage_auction

    title_status: TitleStatus = TitleStatus.UNKNOWN
    drivable: bool | None = None  # True/False/None=unknown

    photo_url: str | None = None
    vin: str | None = None

    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def _strip_url(cls, v: str) -> str:
        return v.strip()

    @property
    def effective_price(self) -> float | None:
        """Best-available price signal: BIN/asking price, else current bid."""
        return self.price_usd if self.price_usd is not None else self.current_bid_usd

    def dedupe_key(self) -> str:
        """Stable hash across sources for dedupe.

        Prefer VIN if present (only used cars publish them on most sites).
        Fall back to (source, listing_id) and finally a hash of the URL.
        """
        if self.vin:
            return f"vin:{self.vin.upper()}"
        if self.listing_id:
            return f"{self.source}:{self.listing_id}"
        return "url:" + hashlib.sha1(self.source_url.encode()).hexdigest()[:16]
