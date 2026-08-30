"""Surface contact info already present in raw data but not yet on the Listing.

Scans raw fields for:
  - Agent phones (distressed.agent_phones, distressed.office_phones)
  - Attorney phones/emails (notice_contact.phone, notice_contact.email)
  - Any phone/email patterns in raw text fields

Writes surfaced phones to li.raw["owner_phone"] (if not already set)
Writes surfaced emails to li.raw["owner_email"] (if not already set)

This is a FAST offline enricher — no network calls.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Sequence

import structlog

from .models import Listing

log = structlog.get_logger()

_PHONE_RE = re.compile(r'\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b')
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')


def _format_phone(digits: str) -> str:
    """Format 10-digit phone string."""
    d = re.sub(r'\D', '', digits)
    if len(d) == 10:
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    if len(d) == 11 and d.startswith('1'):
        return f"({d[1:4]}) {d[4:7]}-{d[7:]}"
    return digits


def _surface_phones_from_raw(raw: dict) -> list[dict]:
    """Find phone numbers in raw data that aren't surfaced yet.
    
    Returns list of {phone, source, type} dicts.
    """
    phones: list[dict] = []
    seen: set[str] = set()
    
    # 1. distressed.agent_phones (HomeHarvest — RE agent business phones)
    d = raw.get("distressed")
    if isinstance(d, dict):
        for ap in d.get("agent_phones") or []:
            if isinstance(ap, dict):
                num = str(ap.get("number") or "")
                if not num:
                    continue
                digits = re.sub(r'\D', '', num)
                if len(digits) >= 10 and digits[-10:] not in seen:
                    seen.add(digits[-10:])
                    phones.append({
                        "phone": _format_phone(digits[-10:]),
                        "source": "homeharvest_agent",
                        "type": ap.get("type", "BUSINESS_PHONE"),
                    })
        # 2. distressed.office_phones
        for op in d.get("office_phones") or []:
            if isinstance(op, dict):
                num = str(op.get("number") or "")
                if not num:
                    continue
                digits = re.sub(r'\D', '', num)
                if len(digits) >= 10 and digits[-10:] not in seen:
                    seen.add(digits[-10:])
                    phones.append({
                        "phone": _format_phone(digits[-10:]),
                        "source": "homeharvest_office",
                        "type": op.get("type", "OFFICE_PHONE"),
                    })
    
    # 3. notice_contact.phone (attorney/trustee phones from legal notices)
    nc = raw.get("notice_contact")
    if isinstance(nc, dict):
        ncp = str(nc.get("phone") or "")
        if ncp:
            digits = re.sub(r'\D', '', ncp)
            if len(digits) >= 10 and digits[-10:] not in seen:
                seen.add(digits[-10:])
                phones.append({
                    "phone": _format_phone(digits[-10:]),
                    "source": "notice_contact_attorney",
                    "type": "attorney",
                    "name": nc.get("name"),
                    "role": nc.get("contact_role"),
                })
    
    # 4. Scan raw text fields for any phone patterns
    for field in ("description", "notice_body", "notice_text"):
        val = raw.get(field)
        if isinstance(val, str):
            for m in _PHONE_RE.finditer(val):
                digits = re.sub(r'\D', '', m.group())
                if len(digits) >= 10 and digits[-10:] not in seen:
                    seen.add(digits[-10:])
                    phones.append({
                        "phone": _format_phone(digits[-10:]),
                        "source": f"raw.{field}",
                        "type": "unknown",
                    })
    
    return phones


def _surface_emails_from_raw(raw: dict) -> list[dict]:
    """Find emails in raw data not yet surfaced."""
    emails: list[dict] = []
    seen: set[str] = set()
    
    # 1. distressed.agent_email
    d = raw.get("distressed")
    if isinstance(d, dict):
        ae = d.get("agent_email")
        if ae and ae.lower() not in seen:
            seen.add(ae.lower())
            emails.append({
                "email": ae.lower().strip(),
                "source": "distressed.agent_email",
                "classification": "agent",
            })
    
    # 2. notice_contact.email
    nc = raw.get("notice_contact")
    if isinstance(nc, dict):
        nce = nc.get("email")
        if nce and nce.lower() not in seen:
            seen.add(nce.lower())
            emails.append({
                "email": nce.lower().strip(),
                "source": "notice_contact.email",
                "classification": "attorney",
            })
    
    # 3. Scan all raw for email patterns
    raw_str = json.dumps(raw, default=str)
    for m in _EMAIL_RE.finditer(raw_str):
        e = m.group().lower().strip(".")
        if e not in seen and not any(d in e for d in ("noreply", "no-reply", "example.com")):
            seen.add(e)
            emails.append({
                "email": e,
                "source": "raw_scan",
                "classification": "other",
            })
    
    return emails


def enrich_surface_contacts(listings: Sequence[Listing]) -> dict:
    """Surface contact phones and emails already in raw data.
    
    Fast offline enricher — no network calls.
    Writes to li.raw["owner_phone"] and li.raw["owner_email"].
    """
    stats = {
        "total": 0,
        "phones_found": 0,
        "listings_with_new_phones": 0,
        "emails_found": 0,
        "listings_with_new_emails": 0,
    }
    
    for li in listings:
        stats["total"] += 1
        raw = li.raw if isinstance(li.raw, dict) else {}
        
        # Surface phones
        existing_phone = (raw.get("owner_phone") or {}).get("phone")
        phones = _surface_phones_from_raw(raw)
        if phones:
            if not existing_phone:
                # Use best phone (prefer attorney > agent > office > unknown)
                priority = {"attorney": 0, "homeharvest_agent": 1, "homeharvest_office": 2}
                best = min(phones, key=lambda p: priority.get(p["source"], 99))
                raw["owner_phone"] = {
                    "phone": best["phone"],
                    "additional_phones": [p["phone"] for p in phones if p["phone"] != best["phone"]][:3],
                    "source": best["source"],
                    "line_type": "unknown",
                    "needs_dnc_scrub": True,
                    "match": best.get("type", "unknown"),
                    "contact_name": best.get("name"),
                    "contact_role": best.get("role"),
                    "surfaced_at": datetime.utcnow().isoformat(),
                }
                stats["listings_with_new_phones"] += 1
            else:
                # Add additional phones
                existing = raw.get("owner_phone", {})
                existing_addl = existing.get("additional_phones") or []
                for p in phones:
                    if p["phone"] != existing_phone and p["phone"] not in existing_addl:
                        existing_addl.append(p["phone"])
                existing["additional_phones"] = existing_addl[:5]
            
            stats["phones_found"] += len(phones)
        
        # Surface emails
        existing_emails = (raw.get("owner_email") or {}).get("emails")
        emails = _surface_emails_from_raw(raw)
        if emails:
            if not existing_emails:
                raw["owner_email"] = {
                    "emails": emails,
                    "best_email": emails[0]["email"],
                    "best_classification": emails[0]["classification"],
                    "surfaced_at": datetime.utcnow().isoformat(),
                }
                stats["listings_with_new_emails"] += 1
            stats["emails_found"] += len(emails)
    
    log.info(
        "surface_contacts.complete",
        total=stats["total"],
        phones=stats["phones_found"],
        new_phone_listings=stats["listings_with_new_phones"],
        emails=stats["emails_found"],
        new_email_listings=stats["listings_with_new_emails"],
    )
    
    return stats
