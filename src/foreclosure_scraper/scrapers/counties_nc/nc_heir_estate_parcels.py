"""Heir / estate owner-of-record parcels — a net-new motivated-seller signal.

When a property owner dies, the county parcel roll often re-titles the owner of
record to "<SURNAME> HEIRS", "HEIRS OF <NAME>", or "<NAME> ESTATE" / "ESTATE OF
<NAME>" long before (or instead of) any probate case is opened. Those parcels are
classic tangled-title / pre-probate leads: undivided heir interests, no single
decision-maker, frequently vacant and tax-delinquent — owners motivated to
liquidate but stuck.

This is property-keyed at the source: one ArcGIS query per county parcel layer
returns owner + full situs + PIN + mailing in a single call, so every lead lands
already resolved to a parcel (no downstream GIS round-trip needed). It reuses the
COUNTY_GIS field map + _query helper from enrichment_owner_mailing, so adding a
county here is free once its parcel layer is in COUNTY_GIS.

Scope: 11 NC + 4 Upstate SC counties (Spartanburg, Pickens, Laurens, Union) whose
COUNTY_GIS owner layer retitles decedent parcels. Oconee's owner field does not
retitle to HEIRS/ESTATE (0 hits) and is omitted; SCDOT-statewide + Greenville
carry no queryable owner name. Add a county by dropping its key into _HEIR_COUNTIES
once its COUNTY_GIS parcel layer is confirmed to return hits.

Distress signal: emits ListingType.ESTATE_LEAD with raw['relationship_signal']
= {kind: 'probate'} so distress_score scores it (LIFE_EVENT). Dateless — routed
via DATELESS_OK_SOURCES. LIFE ESTATE is excluded (that is an estate-planning deed
on a LIVING owner, not a decedent).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...enrichment_owner_mailing import COUNTY_GIS, _query

log = structlog.get_logger()

# Counties whose COUNTY_GIS layer exposes a queryable owner-name field that
# retitles decedent parcels to "<name> HEIRS" / "ESTATE OF". NC is broad; SC
# adds the four Upstate layers that return real hits (Oconee's owner field does
# not retitle -> 0, so it's omitted).
_HEIR_COUNTIES = [
    "NC:Buncombe", "NC:Henderson", "NC:Rutherford", "NC:Gaston", "NC:Transylvania",
    "NC:Polk", "NC:Lincoln", "NC:Mitchell", "NC:Burke", "NC:McDowell", "NC:Cleveland",
    "SC:Spartanburg", "SC:Pickens", "SC:Laurens", "SC:Union",
]

# Owner-of-record patterns that indicate a decedent/heir title. HEIR catches
# HEIRS/HEIR/HEIR OF; ESTATE catches singular "<name> ESTATE"/"ESTATE OF".
_MATCH_TOKENS = ("HEIR", "ESTATE")
# SQL-level exclusions. Plural "ESTATES" + "REAL ESTATE" are almost always a
# subdivision/HOA/brokerage, not a decedent; "LIFE ESTATE" is a living owner.
_EXCLUDE = ("LIFE ESTATE", "REAL ESTATE", "ESTATES")

_PER_COUNTY_CAP = 80

# Python-side belt-and-suspenders: an "ESTATE" hit is only a decedent when it is
# NOT an entity (LLC/HOA/church/etc.). HEIR hits are accepted outright.
_ENTITY_SUFFIX = re.compile(
    r"\b(LLC|L L C|INC|CORP|COMPANY|\bCO\b|LP|LLP|LLLP|TRUST|HOLDINGS?|"
    r"PROPERTIES|PARTNERS?|ASSOC|ASSN|HOA|HOMEOWNERS?|CHURCH|MINISTR|"
    r"DEVELOP|VENTURES?|GROUP|FARMS?|ENTERPRISE|BANK)\b", re.I)


def _is_decedent(owner: str) -> bool:
    u = (owner or "").upper()
    # An entity that merely contains HEIR/ESTATE in its NAME (e.g. "HEIRS LAW LLC",
    # "REAL ESTATE HOLDINGS") is never a decedent — exclude entities from BOTH tokens.
    if _ENTITY_SUFFIX.search(owner or ""):
        return False
    return "HEIR" in u or "ESTATE" in u


def _county_name(key: str) -> str:
    return key.split(":", 1)[1]


def _where(spec: dict, county: str) -> str:
    owner_fields = spec.get("owner") or []
    if not owner_fields:
        return ""
    pos = " OR ".join(
        f"UPPER({f}) LIKE '%{tok}%'" for f in owner_fields for tok in _MATCH_TOKENS)
    neg = " AND ".join(
        f"UPPER({f}) NOT LIKE '%{ex}%'" for f in owner_fields for ex in _EXCLUDE)
    where = f"({pos})"
    if neg:
        where += f" AND {neg}"
    # Shared statewide layers (NC OneMap) need the county pinned.
    cf = spec.get("county_field")
    if cf:
        where += f" AND UPPER({cf}) = '{county.upper()}'"
    return where


def _html(s: str) -> str:
    """Strip embedded tags some SC layers put in owner/situs (Laurens: '<br>&')."""
    return re.sub(r"<[^>]+>", " ", s or "")


def _stitch(spec: dict, attrs: dict, fields_key: str) -> str | None:
    parts = []
    for f in spec.get(fields_key) or []:
        v = attrs.get(f)
        if v not in (None, "", " "):
            parts.append(_html(str(v)).strip())
    out = " ".join(p for p in parts if p).strip()
    return re.sub(r"\s+", " ", out) or None


def _owner(spec: dict, attrs: dict) -> str | None:
    for f in spec.get("owner") or []:
        v = attrs.get(f)
        if v and str(v).strip():
            return re.sub(r"\s+", " ", _html(str(v))).strip()
    return None


class NCHeirEstateParcels(BaseScraper):
    slug = "counties_nc.nc_heir_estate_parcels"
    name = "Heir / Estate Owner-of-Record Parcels (NC + Upstate SC county GIS)"
    category = "motivated_seller"
    expected_min_count = 5
    timeout_s = 240.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=25.0) as http:
            for key in _HEIR_COUNTIES:
                spec = COUNTY_GIS.get(key)
                if not spec:
                    continue
                state = key.split(":", 1)[0]
                county = _county_name(key)
                where = _where(spec, county)
                if not where:
                    continue
                try:
                    rows = await _query(http, spec["url"], where, out_fields="*",
                                        count=_PER_COUNTY_CAP)
                except Exception as exc:  # noqa: BLE001
                    log.warning("nc_heir.county_fail", county=county, error=str(exc)[:120])
                    continue
                kept = 0
                for attrs in rows:
                    owner = _owner(spec, attrs)
                    if not owner or not _is_decedent(owner):
                        continue
                    situs = _stitch(spec, attrs, "situs")
                    mail = _stitch(spec, attrs, "mail")
                    parcel = attrs.get(spec.get("parcel")) if spec.get("parcel") else None
                    # Care-of / attn line (e.g. Buncombe "CareOf") — the executor
                    # or heir's agent, a resolvable contact. Spec-declared field
                    # name only (no guessing); absent on counties that don't map it.
                    care_of_field = spec.get("care_of")
                    care_of = None
                    if care_of_field:
                        cv = attrs.get(care_of_field)
                        if cv and str(cv).strip():
                            care_of = re.sub(r"\s+", " ", _html(str(cv))).strip() or None
                    li = Listing(
                        source=self.slug,
                        source_url=spec["url"],
                        listing_type=ListingType.ESTATE_LEAD,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state,
                        county=county,
                        street_address=situs,
                        parcel_id=str(parcel).strip() if parcel else None,
                        defendant=owner,
                        sale_date=None,
                        description=f"Heir/estate owner of record ({owner}) in {county} County, {state}",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={
                            "heir_estate": {
                                "owner_of_record": owner,
                                "mailing": mail,
                                "care_of": care_of,
                                "match": "heirs" if "HEIR" in owner.upper() else "estate",
                            },
                            # Score as a probate/life-event distress signal.
                            "relationship_signal": {
                                "kind": "probate",
                                "keyword": "heir_estate_owner_of_record",
                                "source": self.slug,
                            },
                        },
                    )
                    out.append(li)
                    kept += 1
                log.info("nc_heir.county", county=county, kept=kept)
        log.info("nc_heir.parsed", listings=len(out))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = NCHeirEstateParcels()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        for li in rows[:12]:
            print(f"  {li.county:14} {(li.defendant or '')[:34]:34} "
                  f"situs={(li.street_address or '')[:34]} pin={li.parcel_id}")

    asyncio.run(_main())
