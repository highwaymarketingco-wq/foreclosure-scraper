"""Shared types + helpers for per-parcel assessor-card adapters."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

_MONEY = re.compile(r"[\d,]+(?:\.\d+)?")


def cf_solving_disabled() -> bool:
    """Global kill-switch for Cloudflare/Turnstile SOLVING in the render-based card
    adapters (qpublic_render, buncombe_nc, cherokee_sc).

    When FORECLOSURE_NO_CF_SOLVE=1, those adapters pass solve_cloudflare=False, so a
    challenged page (e.g. qPublic Turnstile) simply FAILS to render rather than being
    solved — a compliant pass that still lets NON-challenged renders (Buncombe
    Spatialest) work normally. Default OFF preserves existing behaviour for the
    operator's own full runs; set it when a run must not defeat human-verification.
    """
    return os.environ.get("FORECLOSURE_NO_CF_SOLVE", "").strip().lower() in ("1", "true", "yes")

# A transfer at/below this is a nominal/family/exempt move, not an arms-length sale.
ARMS_LENGTH_MIN = 1000.0
_NON_ARMS = ("not valid", "family", "exempt", "quitclaim", "gift", "plat reference",
             "does not match", "intra")


def money(v) -> float | None:
    """Parse a dollar value from a number or a string like '$1,840,000.00'."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v and v > 0 else None
    m = _MONEY.search(str(v).replace("$", ""))
    if not m:
        return None
    try:
        f = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return f if f > 0 else None


def epoch_ms_to_iso(v) -> str | None:
    """Esri epoch-milliseconds -> 'YYYY-MM-DD'."""
    try:
        ms = int(v)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return None


@dataclass
class CardSale:
    sale_date: str | None = None
    price: float | None = None
    book: str | None = None
    page: str | None = None
    reason: str | None = None        # arms-length / family / exempt code, etc.
    grantor: str | None = None
    grantee: str | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


@dataclass
class CardResult:
    """Normalized per-parcel card payload. `sales` MUST be newest-first."""
    source_url: str
    living_sqft: float | None = None
    living_sqft_is_heated: bool = False   # True = heated/finished area (not gross)
    year_built: int | None = None
    bedrooms: float | None = None
    bathrooms: float | None = None
    market_value: float | None = None     # card's appraised total
    sales: list[CardSale] = field(default_factory=list)

    def arms_length_sale(self) -> CardSale | None:
        """Most-recent arms-length sale (price over the nominal-transfer floor,
        not flagged family/exempt). `sales` is newest-first."""
        for s in self.sales:
            if not s.price or s.price < ARMS_LENGTH_MIN:
                continue
            if s.reason and any(x in s.reason.lower() for x in _NON_ARMS):
                continue
            return s
        return None

    def best_sale_price(self) -> float | None:
        s = self.arms_length_sale()
        return s.price if s else None

    def has_fill(self) -> bool:
        return bool(self.living_sqft or self.sales or self.market_value)
