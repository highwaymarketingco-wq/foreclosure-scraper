"""Unified Porsche listing schema."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


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
# the SUV / sedan lines are filtered out. Cayenne was un-excluded
# 2026-05-13 at user request — they're fine seeing those alongside the
# sports cars. Macan + Panamera stay out.
EXCLUDED_MODELS = ("panamera", "macan")


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
# Order matters: "k-mile" / "k-Mile" must match before bare "mile".
_MILES_RE = re.compile(
    r"([\d][\d,]*)\s*-?\s*(k-mile|k-miles|k\s*mi|k\s*miles|mi\b|miles?\b|mile\b)",
    re.IGNORECASE,
)
# Matches a bare numeric-only string like "85,000" or "85000".
_BARE_NUM_RE = re.compile(r"^[\d,]+$")
# Tight US-dollar regex: matches standard thousands formatting only
# (`XXX` or `X,XXX` or `XX,XXX,XXX`), not arbitrary runs of digits-
# and-commas. Without this, "$84,99538,000" — a price + mileage smushed
# together by DOM .text() concatenation — would match as one huge
# captured "price" of $8,499,538,000.
_PRICE_RE = re.compile(
    r"\$\s*(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d{2})?)"
)


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
    """Extract a mileage value from free text.

    Only commits if we either see a unit token ("mi", "miles", "k-mile", etc.)
    or the input is a bare numeric string. Free prose with multiple digit
    groups but no unit returns None — otherwise we'd concatenate
    year + listing-id digits into a bogus mileage.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    s = str(text).strip().lower()
    if not s:
        return None
    m = _MILES_RE.search(s)
    if m:
        num = m.group(1).replace(",", "")
        unit = m.group(2)
        val = float(num)
        if "k" in unit and val < 1000:  # "85k-mile"
            val *= 1000
        return int(val)
    if _BARE_NUM_RE.match(s):
        return int(s.replace(",", ""))
    return None


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

    @computed_field
    @property
    def project_tier(self) -> str:
        """Bucket the listing into a project-worthiness tier for the dashboard.

        - "salvage"  — salvage / flood / parts-only title  (cheapest, most work)
        - "rebuilt"  — rebuilt / reconstructed title       (paperwork done, drives)
        - "damaged"  — clean title but description mentions damage / project /
                      light damage / theft recovery / hail / non-running
        - "clean"    — no damage signal (showroom condition)
        """
        s = (self.title or "").lower()
        if self.title_status in (TitleStatus.SALVAGE, TitleStatus.PARTS_ONLY,
                                  TitleStatus.FLOOD, TitleStatus.LEMON):
            return "salvage"
        if self.title_status == TitleStatus.REBUILT:
            return "rebuilt"
        damaged_keywords = (
            "salvage", "rebuilt", "reconstructed", "project", "needs", "damage",
            "damaged", "hail", "theft", "theft recovery", "light damage",
            "front-end", "rear-end", "side impact", "rolled", "burned",
            "fire", "flood", "water", "non-running", "non running",
            "blown", "seized", "tlc", "as-is", "as is", "no reserve",
            "rough", "barn find", "estate sale", "mechanic special",
            "parts car", "for parts", "shell",
        )
        if any(k in s for k in damaged_keywords):
            return "damaged"
        return "clean"

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
