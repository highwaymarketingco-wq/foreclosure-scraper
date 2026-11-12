"""Reliable fallback links for aggregator (per-property) leads.

WHY THIS EXISTS
---------------
The single biggest "dead link" offender on the operator board is the
per-property page on a national aggregator — realtor.com, zillow.com,
trulia.com, homes.com, foreclosure.com. Two problems compound:

  1. These hosts hard-block bots (zillow → 403, realtor → 429,
     foreclosure.com → 403). A quantified 40-URL sample (2026-06) found
     ZERO genuine 404s among aggregator leads — they were uniformly
     bot-blocked, i.e. they still resolve in a real browser *as long as
     the listing is live*. There is no free/compliant way to confirm a
     delist programmatically.
  2. When a property actually delists, the per-property URL eventually
     302s to a search page or 404s — and that happens silently. Carryover
     leads replayed from older runs (first_seen Mar–May, ~1.3k rows) are
     the population most likely to have delisted since first capture.

So for these leads we do NOT touch the original source_url (it may still
be the best link). Instead we ADD reliable, never-stale fallback links to
``raw.fallback_links`` so the operator always has a working way to find
the property:

  * ``parcel_gis`` — county GIS/parcel viewer search (when county known)
  * ``google``     — Google search for the full address (always works)
  * ``maps``       — Google Maps lookup for the address (always works)

We also tag ``raw.link_may_be_stale = True`` when the lead is OLD carryover
(>= STALE_AGE_DAYS unconfirmed) so the dashboard / email can show a
"verify link" hint without us ever deleting a lead.

This module is pure (no network, no I/O) and deterministic, so it is safe
to run at artifact-write time and trivial to unit-test.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse

# Per-property aggregator hosts whose deep links go stale when a listing
# delists AND which block bots (so we can't verify them for free). A lead
# on one of these gets fallback links added.
AGGREGATOR_HOST_SUBSTRINGS = (
    "realtor.com",
    "zillow.com",
    "trulia.com",
    "homes.com",
    "redfin.com",
    "foreclosure.com",
)

# A lead whose link hasn't been confirmed live in this many days is flagged
# ``link_may_be_stale``. 45d matches the carryover-risk window in the brief
# (first_seen Mar–May carryover rows are the main offenders).
STALE_AGE_DAYS = 45

# County GIS / parcel-viewer search URLs, keyed by lowercased county name.
# These land the operator on the county's public property-search page where
# they can look up by address — a link that never goes stale. Where a county
# has no clean public search URL we fall back to Google (always added).
# NC = qPublic/Schneider GIS; SC = county GIS or qPublic. Kept conservative:
# only counties we are confident about.
_COUNTY_GIS_SEARCH = {
    # --- South Carolina ---
    "anderson": "https://www.andersoncountysc.org/property-search/",
    "pickens": "https://www.co.pickens.sc.us/Departments/Assessor.aspx",
    "spartanburg": "https://www.spartanburgcounty.org/166/Assessor",
    "greenville": "https://www.greenvillecounty.org/appraisal/RealPropertySearch.aspx",
    "oconee": "https://docs.oconeesc.com/AssessorPropertySearch/",
    "cherokee": "https://qpublic.schneidercorp.com/Application.aspx?AppID=1043",
    "laurens": "https://qpublic.schneidercorp.com/Application.aspx?AppID=950",
    # --- North Carolina ---
    "buncombe": "https://tax.buncombecounty.org/",
    "henderson": "https://www.hendersoncountync.gov/tax/page/property-search",
    "gaston": "https://gis.gastongov.com/propertysearch/",
    "lincoln": "https://www.lincolncounty.org/166/Tax-Property-Search",
    "cleveland": "https://gis.clevelandcounty.com/",
    "mcdowell": "https://search.mcdowelldeeds.com/",
    "burke": "https://www.burkenc.org/166/Tax-Administration",
    "rutherford": "https://www.rutherfordcountync.gov/tax",
    "polk": "https://www.polknc.org/tax_administration",
    "mecklenburg": "https://property.spatialest.com/nc/mecklenburg/",
    "transylvania": "https://search.transylvaniadeeds.com/",
    "mitchell": "https://www.mitchellcounty.org/",
    "haywood": "https://www.haywoodcountync.gov/166/Tax",
}


def is_aggregator_url(url: str | None) -> bool:
    """True if ``url`` is a per-property page on a stale-prone aggregator."""
    if not isinstance(url, str) or not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001 — never raise on bad input
        return False
    if not host:
        return False
    return any(sub in host for sub in AGGREGATOR_HOST_SUBSTRINGS)


def _full_address(
    street: str | None,
    city: str | None,
    state: str | None,
    zip_code: str | None,
) -> str:
    """Best-effort single-line address for search queries."""
    parts: list[str] = []
    if street and street.strip():
        parts.append(street.strip())
    locality = ", ".join(p for p in (city, state) if p and p.strip())
    if locality:
        parts.append(locality)
    if zip_code and str(zip_code).strip():
        parts.append(str(zip_code).strip()[:5])
    return " ".join(parts).strip()


def build_fallback_links(
    *,
    street_address: str | None,
    city: str | None,
    state: str | None,
    zip_code: str | None,
    county: str | None,
) -> dict[str, str]:
    """Build a dict of reliable fallback links for a property.

    Always returns a ``google`` link if there is anything addressable to
    search on (full address, else parcel-less city/state). Adds ``maps``
    when we have a usable address, and ``parcel_gis`` when the county has a
    known public property-search URL. Pure/deterministic.
    """
    out: dict[str, str] = {}
    addr = _full_address(street_address, city, state, zip_code)

    # Google web search — the universal "always works" fallback.
    if addr:
        out["google"] = (
            "https://www.google.com/search?q=" + quote_plus(addr)
        )
        out["maps"] = (
            "https://www.google.com/maps/search/?api=1&query=" + quote_plus(addr)
        )

    # County GIS / parcel viewer — never goes stale, authoritative.
    if county:
        key = re.sub(r"\s+county\s*$", "", county.strip().lower())
        gis = _COUNTY_GIS_SEARCH.get(key)
        if gis:
            out["parcel_gis"] = gis

    return out


def _age_days(first_seen: datetime | str | None) -> int | None:
    """Days since first_seen, or None if unparseable."""
    if first_seen is None:
        return None
    dt: datetime | None = None
    if isinstance(first_seen, datetime):
        dt = first_seen
    elif isinstance(first_seen, str):
        try:
            dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


def annotate_stale_links(record: dict) -> dict:
    """Mutate & return a *serialized* listing dict, adding fallback links and
    a stale flag for aggregator/per-property leads.

    Conservative contract:
      * Never removes or rewrites ``source_url``.
      * Only acts when ``source_url`` is a per-property aggregator link.
      * ``raw.fallback_links`` is added/merged (never clobbers existing keys).
      * ``raw.link_may_be_stale`` set True when the lead is old carryover
        (>= STALE_AGE_DAYS) OR already carries a carryover marker, OR the
        link_check status is one of the not-OK states. Otherwise left unset.

    Safe on any dict shape — bad/missing fields just yield fewer links.
    """
    if not isinstance(record, dict):
        return record

    url = record.get("source_url")
    if not is_aggregator_url(url):
        return record

    raw = record.get("raw")
    if not isinstance(raw, dict):
        raw = {}
        record["raw"] = raw

    links = build_fallback_links(
        street_address=record.get("street_address"),
        city=record.get("city"),
        state=record.get("state"),
        zip_code=record.get("zip_code"),
        county=record.get("county"),
    )
    if links:
        existing = raw.get("fallback_links")
        if isinstance(existing, dict):
            # Don't overwrite anything an upstream step already set.
            for k, v in links.items():
                existing.setdefault(k, v)
        else:
            raw["fallback_links"] = links

    # Staleness signal — never delete, just hint.
    stale = False
    if raw.get("carryover"):
        stale = True
    age = _age_days(record.get("first_seen"))
    if age is not None and age >= STALE_AGE_DAYS:
        stale = True
    lc = raw.get("link_check")
    if isinstance(lc, dict) and lc.get("status") in {
        "dead", "auth", "anti-bot", "unreachable", "server", "other",
    }:
        stale = True
    if stale:
        raw["link_may_be_stale"] = True

    return record
