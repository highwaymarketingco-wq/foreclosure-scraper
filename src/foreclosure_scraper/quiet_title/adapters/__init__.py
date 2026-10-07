"""County adapters. Adding a county = one CountyAdapter subclass + one line in ADAPTERS."""
from __future__ import annotations

from .base import CountyAdapter
from .buncombe import BuncombeAdapter

ADAPTERS: dict[tuple[str, str], type[CountyAdapter]] = {
    ("NC", "buncombe"): BuncombeAdapter,
}


def adapter_class(county: str, state: str = "NC") -> type[CountyAdapter]:
    key = (state.strip().upper(), county.strip().lower().removesuffix(" county"))
    try:
        return ADAPTERS[key]
    except KeyError:
        have = ", ".join(f"{c.title()} {s}" for s, c in sorted(ADAPTERS))
        raise SystemExit(f"No intake adapter for {county} {state}. Available: {have}.") from None


__all__ = ["ADAPTERS", "CountyAdapter", "BuncombeAdapter", "adapter_class"]
