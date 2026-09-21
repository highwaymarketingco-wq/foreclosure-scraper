"""One normaliser for raw['owner_mailing'], in a module of its own.

WHY ITS OWN MODULE
    This helper first lived in enrichment_owner_mailing, which main.py imports
    at STARTUP. A long-running orchestrator therefore holds that module object
    in sys.modules for the whole run — so when a later, lazily-imported enricher
    (skip_trace at main.py:1410, incarceration at 1335, promote_owner at 1909)
    loads its NEW file from disk and asks for a name that was added to
    enrichment_owner_mailing mid-run, it gets the STALE object and dies:

        ImportError: cannot import name 'mailing_dict' from
                     'foreclosure_scraper.enrichment_owner_mailing'

    That took out three enrichers on the 2026-08-04 run. The file on disk was
    correct and the tests passed; the running process simply had an old copy.

    A leaf module fixes it for good: nothing imports this at startup, so a
    mid-run edit is always picked up fresh, and it can never be half-loaded.

WHAT IT NORMALISES
    raw['owner_mailing'] is usually a dict, but spartanburg_vacant,
    spartanburg_condemned and spartanburg_delinquent_tax write a bare STRING
    that IS the mailing address — 5,098 leads on the 2026-08-03 board. An
    "or {}" fallback cannot rescue a truthy str, so an unguarded .get() raises
    AttributeError and takes its whole pass down.
"""
from __future__ import annotations

from typing import Any

__all__ = ["mailing_dict", "mailing_of"]


def mailing_dict(obj: Any) -> dict:
    """`raw['owner_mailing']` as a dict, whatever the source actually wrote.

    Accepts a Listing, a raw dict, or the owner_mailing value itself. Always
    returns a dict, so callers can `.get()` without guarding.
    """
    raw = getattr(obj, "raw", obj)
    if isinstance(raw, dict) and "owner_mailing" in raw:
        om = raw.get("owner_mailing")
    else:
        om = raw
    if isinstance(om, dict):
        return om
    if isinstance(om, str) and om.strip():
        return {"mailing": om.strip()}
    return {}


def mailing_of(obj: Any) -> dict:
    """The owner-mailing dict OF a lead: strict about which key it reads.

    `mailing_dict` accepts either a raw dict or the owner_mailing value itself, so given a
    raw dict with no 'owner_mailing' key it returns the WHOLE raw dict as though it were the
    mailing block, and a caller then reads raw['absentee'] or raw['mailing'] off the wrong
    object. This reads only raw['owner_mailing'] and returns {} when that key is absent, so
    the scorer and the lead-signals enricher cannot be handed a lead's other data by
    mistake. Bare-string mailing addresses (the Spartanburg sources) still normalise to
    {"mailing": text}; audit 2026-09-21 F14: the scorer ignored them and 5,098 leads could
    never be HOT.
    """
    raw = getattr(obj, "raw", obj)
    if not isinstance(raw, dict):
        return {}
    return mailing_dict(raw.get("owner_mailing"))
