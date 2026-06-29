"""Paid skip-trace enrichment — the ONLY bulk path to individual owner phones + emails (NC AND
SC). Off by default; activates when SKIPTRACE_API_KEY is set. No key -> no-op, no cost.

WHY PAID: individual owner phones/emails exist only behind CAPTCHA-walled aggregators (we don't
defeat bot-detection) or paywalls. A licensed skip-trace API is the compliant bulk source —
~$0.05-0.25/hit, no-hit-no-charge, real-estate "locate to transact" (non-FCRA) purpose.

ACTIVATE:
  1. Open an account with a real-estate-permissible provider (BatchData recommended — cheapest
     bulk). Fund a small budget.
  2. export SKIPTRACE_API_KEY=...   (optionally SKIPTRACE_PROVIDER=batchdata, SKIPTRACE_MAX=...)
  3. python scripts/fill_skiptrace.py   (or it runs inside the full pipeline)

Built to BatchData's documented v1 skip-trace shape; verify the endpoint/field map against your
provider's current docs (the _parse_* funcs are the only thing to adjust per provider).

COMPLIANCE: every number is tagged needs_dnc_scrub=True. NEVER call/text until scrubbed against
the National DNC Registry (re-scrub >=31 days) + internal DNC, 8a-9p local, TCPA wireless screen,
SC+NC mini-TCPA. The outreach stack gates dialing; this only appends data.
"""
from __future__ import annotations

import asyncio
import os

try:
    from curl_cffi.requests import AsyncSession
except Exception:  # pragma: no cover
    AsyncSession = None

_PROVIDERS = {
    # provider -> (url, auth_header_fn)
    "batchdata": ("https://api.batchdata.com/api/v1/property/skip-trace",
                  lambda k: {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}),
}


def _payload_batchdata(li) -> dict:
    return {"requests": [{
        "propertyAddress": {
            "street": li.street_address or "",
            "city": li.city or "",
            "state": li.state or "",
            "zip": (li.zip_code or "")[:5],
        },
        "name": {"first": "", "last": ""},  # provider matches on address; name optional
    }]}


def _parse_batchdata(j: dict) -> dict:
    """-> {phones: [..], emails: [..]} from a BatchData skip-trace response."""
    out = {"phones": [], "emails": []}
    try:
        persons = (((j.get("results") or {}).get("persons")) or j.get("persons") or [])
        for p in persons:
            for ph in (p.get("phoneNumbers") or p.get("phones") or []):
                num = ph.get("number") if isinstance(ph, dict) else ph
                if num:
                    out["phones"].append({"number": str(num),
                                          "type": (ph.get("type") if isinstance(ph, dict) else None)})
            for em in (p.get("emails") or p.get("emailAddresses") or []):
                addr = em.get("email") if isinstance(em, dict) else em
                if addr:
                    out["emails"].append(str(addr))
    except Exception:  # noqa: BLE001
        pass
    return out


async def enrich_skiptrace(listings) -> dict:
    key = os.environ.get("SKIPTRACE_API_KEY")
    if not key or AsyncSession is None:
        return {"enabled": False, "note": "no SKIPTRACE_API_KEY -> skip-trace disabled (no cost)"}
    provider = os.environ.get("SKIPTRACE_PROVIDER", "batchdata").lower()
    url, auth = _PROVIDERS.get(provider, _PROVIDERS["batchdata"])
    cap = int(os.environ.get("SKIPTRACE_MAX", "100000"))
    payload = globals().get(f"_payload_{provider}", _payload_batchdata)
    parse = globals().get(f"_parse_{provider}", _parse_batchdata)

    targets = [li for li in listings if li.street_address and li.state and li.city
               and not ((li.raw or {}).get("owner_phone") if isinstance(li.raw, dict) else None)]
    stats = {"enabled": True, "provider": provider, "queried": 0, "phones": 0, "emails": 0}
    async with AsyncSession() as s:
        for li in targets[:cap]:
            try:
                r = await s.post(url, headers=auth(key), json=payload(li), impersonate="chrome", timeout=25)
                stats["queried"] += 1
                if r.status_code != 200:
                    continue
                got = parse(r.json())
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            if got["phones"]:
                ph = got["phones"][0]["number"]
                li.raw["owner_phone"] = {"phone": ph, "source": f"skiptrace:{provider}",
                                         "line_type": got["phones"][0].get("type") or "unknown",
                                         "needs_dnc_scrub": True, "match": "skiptrace"}
                stats["phones"] += 1
            if got["emails"]:
                li.raw["owner_email"] = {"email": got["emails"][0], "source": f"skiptrace:{provider}"}
                stats["emails"] += 1
            await asyncio.sleep(0.15)
    return stats
