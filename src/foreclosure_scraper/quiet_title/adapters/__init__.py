"""County adapters. Adding a county = one CountyAdapter subclass + one line in ADAPTERS.

A North Carolina county with no adapter of its own gets NcOneMapAdapter (the statewide parcel layer
for the parcel record; the register, tax and probate sites are given as links for a person)."""
from __future__ import annotations

from .base import CountyAdapter
from .buncombe import BuncombeAdapter
from .nc_onemap import NcOneMapAdapter, canonical_county

ADAPTERS: dict[tuple[str, str], type[CountyAdapter]] = {
    ("NC", "buncombe"): BuncombeAdapter,
}


def adapter_class(county: str, state: str = "NC") -> type[CountyAdapter]:
    key = (state.strip().upper(), county.strip().lower().removesuffix(" county"))
    if key in ADAPTERS:
        return ADAPTERS[key]
    if key[0] == "NC" and canonical_county(county):
        return NcOneMapAdapter.for_county(county)
    have = ", ".join(f"{c.title()} {s}" for s, c in sorted(ADAPTERS))
    raise SystemExit(f"No intake adapter for {county} {state}. Available: {have}, and any NC county through the "
                     f"statewide parcel layer.") from None


__all__ = ["ADAPTERS", "CountyAdapter", "BuncombeAdapter", "NcOneMapAdapter", "adapter_class"]
