"""County adapters. Adding a county = one CountyAdapter subclass + one line in ADAPTERS.

A North Carolina county with no adapter of its own gets NcOneMapAdapter (the statewide parcel layer
for the parcel record; the register, tax and probate sites are given as links for a person)."""
from __future__ import annotations

from .base import CountyAdapter
from .buncombe import BuncombeAdapter
from .cott_onemap import OPEN_COTT, CottOneMapAdapter
from .nc_onemap import NcOneMapAdapter, canonical_county
from .polk import PolkAdapter

ADAPTERS: dict[tuple[str, str], type[CountyAdapter]] = {
    ("NC", "buncombe"): BuncombeAdapter,
    ("NC", "polk"): PolkAdapter,          # statewide parcel record + the county's open Cott register
}


def adapter_class(county: str, state: str = "NC") -> type[CountyAdapter]:
    key = (state.strip().upper(), county.strip().lower().removesuffix(" county"))
    if key in ADAPTERS:
        return ADAPTERS[key]
    # an open Cott v4 register (no guest button): parcel record + the register read live
    cott = {c.lower(): c for c in OPEN_COTT}.get(key[1])
    if key[0] == "NC" and cott:
        return CottOneMapAdapter.for_cott_county(cott)
    if key[0] == "NC" and canonical_county(county):
        return NcOneMapAdapter.for_county(county)
    have = ", ".join(f"{c.title()} {s}" for s, c in sorted(ADAPTERS))
    raise SystemExit(f"No intake adapter for {county} {state}. Available: {have}, and any NC county through the "
                     f"statewide parcel layer.") from None


__all__ = ["ADAPTERS", "CountyAdapter", "BuncombeAdapter", "CottOneMapAdapter", "NcOneMapAdapter", "PolkAdapter", "adapter_class"]
