"""Skip-trace enrichment: homeowner contact info for short-sale outreach.

Dad's note #7 — investors want to contact the homeowner BEFORE the
foreclosure sale to offer a short-sale buyout. We have the defendant
name (from court records) and property address; we need phone / email /
mailing address.

Provider-pluggable design — pick one via SKIP_TRACE_PROVIDER env:
  - "none" (default): skip-trace disabled; pipeline runs without it
  - "tax_records_only": FREE. Cross-references defendant name + property
    address against county tax assessor mailing address. If mailing
    address differs from property address (absentee landlord / out-of-
    state owner), surface it. ~30-50% of defendants have an absentee
    mailing address on file.
  - "batchskiptracing": PAID. Posts (name, property_address) to
    api.batchskiptracing.com → returns phone, email, alternative
    addresses. ~$0.05-0.20/lead.
  - "spokeo": PAID. Spokeo API. Similar pricing.

All providers populate the same output shape on listing.raw:

    raw["skip_trace"] = {
        "provider": "...",
        "owner_mailing_address": "...",        # if available
        "owner_mailing_diff_from_property": bool,
        "phone_numbers": ["..."],              # paid only
        "email_addresses": ["..."],            # paid only
        "additional_owners": [...],            # related parties
        "skip_trace_at": ISO timestamp,
        "confidence": "high" | "medium" | "low",
    }

Cost & rate-limit control:
  - max_per_run (default 100): caps API calls per workflow execution
  - Prioritizes by sale_date proximity (closer to sale = higher priority
    since outreach time is short)
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional, Protocol

import httpx
import structlog

from .models import Listing
from .enrichment_owner_mailing import mailing_dict

log = structlog.get_logger()


class SkipTraceProvider(Protocol):
    """Each provider implements lookup() returning a normalized dict
    suitable for li.raw['skip_trace']. None = no result."""

    name: str

    async def lookup(self, li: Listing) -> Optional[dict]: ...


# -------------- Provider implementations --------------


class NoopProvider:
    """Default — does nothing. Used when SKIP_TRACE_PROVIDER is unset
    or explicitly 'none'. Lets the rest of the pipeline run without
    accidentally racking up API costs."""
    name = "none"

    async def lookup(self, li: Listing) -> Optional[dict]:
        return None


class TaxRecordsOnlyProvider:
    """Free path — relies on data we ALREADY have from county GIS
    enrichment. county GIS layers expose the property's owner mailing
    address (from the tax assessor). When that mailing address differs
    from the property address, the owner is absentee — a strong
    motivated-seller signal (or at least confirms they don't live at
    the property and have to be contacted elsewhere).

    No HTTP calls — pure read of li.raw['gis'] populated upstream.
    """
    name = "tax_records_only"

    async def lookup(self, li: Listing) -> Optional[dict]:
        raw = li.raw if isinstance(li.raw, dict) else {}
        # PRIMARY source: enrichment_owner_mailing writes the county-GIS owner +
        # MAILING address (and an authoritative absentee flag) to
        # raw["owner_mailing"]. The skip-trace step used to read raw["gis"],
        # which the contactability spine never populates with mailing — that
        # storage-key mismatch is why this free path produced almost nothing.
        # We now read owner_mailing first and fall back to the older gis shape.
        om = mailing_dict(raw)
        gis = raw.get("gis") or {}
        mailing = (
            om.get("mailing")
            or gis.get("mailing")
            or gis.get("owner_mailing_address")
            or gis.get("mailing_address")
            or gis.get("Owner_Mailing_Address")
        )
        owner = (
            om.get("owner")
            or gis.get("owner")
            or gis.get("Owner")
            or li.defendant
        )
        if not mailing and not owner:
            return None

        # Prefer the spine's already-computed absentee/out-of-state flags (they
        # compare against the GIS situs and are owner-occupancy-suppressed);
        # fall back to a substring compare against the listing's own address.
        if "absentee" in om:
            diff = bool(om.get("absentee"))
        else:
            prop_addr = (li.street_address or "").lower().strip()
            mailing_clean = str(mailing or "").lower().strip()
            diff = bool(prop_addr) and bool(mailing_clean) and \
                prop_addr not in mailing_clean and mailing_clean not in prop_addr

        return {
            "provider": self.name,
            "owner_name": str(owner) if owner else None,
            "owner_mailing_address": str(mailing) if mailing else None,
            "owner_mailing_diff_from_property": diff,
            "absentee_owner": diff,
            "out_of_state_owner": bool(om.get("out_of_state")),
            "parcel_id": om.get("parcel_id"),
            "mail_state": om.get("mail_state"),
            "phone_numbers": [],
            "email_addresses": [],
            "additional_owners": [],
            "skip_trace_at": datetime.utcnow().isoformat() + "Z",
            "confidence": "medium" if diff else "low",
        }


class FreePeopleSearchProvider:
    """Best-effort FREE phone lookup via a public people-search site,
    driven by the local stealth browser (these sites are bot-protected).

    Keyed on owner/defendant name + property city/state. Accuracy is
    lower than paid credit-header data (~50-70%), and results are clearly
    marked low/medium confidence. Bounded + slow (real browser per lookup),
    so it's only used for the highest-priority listings.

    Set FREE_SKIPTRACE_SITE to override the base query URL if a site
    changes. Returns {} (not None) so the combined provider can still
    attach the reliable tax-records data.
    """
    name = "free_people_search"
    # FastPeopleSearch: name + city/state query, phones rendered in the card.
    BASE = os.environ.get(
        "FREE_SKIPTRACE_SITE",
        "https://www.fastpeoplesearch.com/name/{name}_{city}-{state}",
    )

    _PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")

    async def lookup(self, li: Listing) -> Optional[dict]:
        name = (li.defendant or "").strip()
        if not name or not li.city or not li.state:
            return None
        # Normalize "LAST FIRST" / "First Last" → "first-last" slug.
        parts = re.sub(r"[^A-Za-z\s]", " ", name).split()
        if len(parts) < 2:
            return None
        slug = "-".join(p.lower() for p in parts[:3])
        city_slug = re.sub(r"\s+", "-", li.city.strip().lower())
        url = self.BASE.format(name=slug, city=city_slug, state=li.state.lower())

        try:
            from .render import fetch_rendered
            text = await fetch_rendered(url)
        except Exception as exc:
            log.debug("skip_trace.people_search.error", error=str(exc)[:120])
            return None
        if not text:
            return None

        phones = []
        for m in self._PHONE_RE.finditer(text):
            p = re.sub(r"[^\d]", "", m.group(0))
            if len(p) == 10 and p not in phones:
                phones.append(p)
            if len(phones) >= 4:
                break
        if not phones:
            return None
        return {
            "provider": self.name,
            "phone_numbers": phones,
            "phone_confidence": "low",   # free-site match, unverified
            "phone_source_url": url,
            "skip_trace_at": datetime.utcnow().isoformat() + "Z",
        }


class FreeProvider:
    """Combined FREE skip trace: reliable tax-records owner + mailing
    address, PLUS best-effort people-search phone for the most
    time-sensitive listings. Zero cost. This is the default 'free' mode."""
    name = "free"

    def __init__(self):
        self.tax = TaxRecordsOnlyProvider()
        self.people = FreePeopleSearchProvider()
        # People-search is slow (real browser); only attempt it for the
        # top N closest-to-sale listings to keep run time sane.
        self.phone_budget = int(os.environ.get("FREE_SKIPTRACE_PHONE_MAX", "40"))
        self._phone_used = 0

    async def lookup(self, li: Listing) -> Optional[dict]:
        result = await self.tax.lookup(li)  # reliable, free, no network
        # Try a phone only for imminent sales, within budget.
        want_phone = (
            self._phone_used < self.phone_budget
            and li.defendant and li.city and li.state
        )
        if want_phone:
            self._phone_used += 1
            phone_res = await self.people.lookup(li)
            if phone_res:
                result = result or {"provider": "free"}
                result["phone_numbers"] = phone_res["phone_numbers"]
                result["phone_confidence"] = phone_res.get("phone_confidence", "low")
                result["phone_source_url"] = phone_res.get("phone_source_url")
        return result


class BatchSkipTracingProvider:
    """Paid integration with batchskiptracing.com.
    Set SKIP_TRACE_API_KEY env. Pricing ~$0.05-0.20/lead.

    NOT TESTED LIVE — API contract based on public docs. Adjust the
    request/response shape after first run if needed.
    """
    name = "batchskiptracing"
    BASE_URL = "https://api.batchskiptracing.com/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def lookup(self, li: Listing) -> Optional[dict]:
        if not li.defendant or not li.street_address:
            return None
        # Build the request shape per BatchSkipTracing's docs. They
        # accept a JSON array of {first_name, last_name, address}.
        name_parts = (li.defendant or "").split(maxsplit=1)
        first = name_parts[0] if name_parts else ""
        last = name_parts[1] if len(name_parts) > 1 else ""
        payload = {
            "requests": [{
                "first_name": first,
                "last_name": last,
                "address": li.street_address,
                "city": li.city or "",
                "state": li.state or "",
                "zip": li.zip_code or "",
            }],
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{self.BASE_URL}/skiptrace",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if r.status_code != 200:
                    log.warning(
                        "skip_trace.api_error",
                        provider=self.name,
                        status=r.status_code,
                        body=r.text[:200],
                    )
                    return None
                data = r.json()
        except Exception as exc:
            log.warning("skip_trace.exception", provider=self.name, error=str(exc)[:200])
            return None

        # Normalize the response. BatchSkipTracing returns
        # {"results": [{...}]} with phones, emails, alt addresses.
        results = (data.get("results") or [{}])[0] if isinstance(data.get("results"), list) else {}
        phones = results.get("phones") or []
        emails = results.get("emails") or []
        return {
            "provider": self.name,
            "owner_mailing_address": results.get("address") or li.street_address,
            "owner_mailing_diff_from_property": False,  # API doesn't expose this directly
            "phone_numbers": [str(p) for p in phones][:5],
            "email_addresses": [str(e) for e in emails][:5],
            "additional_owners": results.get("alternate_owners") or [],
            "skip_trace_at": datetime.utcnow().isoformat() + "Z",
            "confidence": "high" if phones or emails else "low",
        }


# -------------- Dispatch --------------


def _resolve_provider() -> SkipTraceProvider:
    """Pick the provider from env. Defaults to noop (free, no-op)."""
    name = (os.environ.get("SKIP_TRACE_PROVIDER") or "none").strip().lower()
    if name == "free":
        return FreeProvider()
    if name == "tax_records_only":
        return TaxRecordsOnlyProvider()
    if name == "batchskiptracing":
        key = os.environ.get("SKIP_TRACE_API_KEY")
        if not key:
            log.warning("skip_trace.no_api_key", provider=name)
            return NoopProvider()
        return BatchSkipTracingProvider(key)
    # 'spokeo' / other paid providers can be added similarly when needed.
    return NoopProvider()


def _priority(li: Listing) -> tuple:
    """Sort key: lower priority value = run first. Closer-to-sale
    listings get traced first so the limited budget hits the most
    time-sensitive leads."""
    sale_date = li.sale_date
    if sale_date is None:
        return (3, 0)  # no date — least urgent
    if hasattr(sale_date, "tzinfo") and sale_date.tzinfo is not None:
        sale_date = sale_date.replace(tzinfo=None)
    now = datetime.utcnow()
    days = (sale_date - now).days
    if days < 0:
        return (2, abs(days))  # already past sale
    if days <= 7:
        return (0, days)       # imminent
    return (1, days)            # future


async def enrich_with_skip_trace(
    listings: list[Listing],
    max_per_run: Optional[int] = None,
) -> dict:
    """Enrich listings with skip-trace data via the configured provider.

    Cap: max_per_run (default 100, env SKIP_TRACE_MAX_PER_RUN).
    Selection priority: closer-to-sale listings first.

    Returns stats dict for run_health.json.
    """
    provider = _resolve_provider()
    stats = {
        "provider": provider.name,
        "skipped": 0,
        "attempted": 0,
        "succeeded": 0,
        "absentee_owners_found": 0,
    }
    if isinstance(provider, NoopProvider):
        log.info("skip_trace.disabled", provider="none")
        return stats

    if max_per_run is None:
        max_per_run = int(os.environ.get("SKIP_TRACE_MAX_PER_RUN", "100"))

    # Filter eligible: must have street_address; prioritize ones with
    # a defendant name (paid lookups need both).
    eligible = [
        li for li in listings
        if li.street_address
        and not (li.raw or {}).get("skip_trace")  # don't re-run
    ]
    eligible.sort(key=_priority)
    targets = eligible[:max_per_run]
    stats["skipped"] = max(0, len(eligible) - len(targets))

    log.info(
        "skip_trace.start",
        provider=provider.name,
        eligible=len(eligible),
        targets=len(targets),
        max_per_run=max_per_run,
    )

    for li in targets:
        stats["attempted"] += 1
        try:
            result = await provider.lookup(li)
        except Exception as exc:
            log.warning(
                "skip_trace.lookup_failed",
                provider=provider.name,
                source_url=li.source_url,
                error=str(exc)[:200],
            )
            continue
        if not result:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["skip_trace"] = result
        stats["succeeded"] += 1
        if result.get("owner_mailing_diff_from_property"):
            stats["absentee_owners_found"] += 1

    log.info("skip_trace.done", **stats)
    return stats
