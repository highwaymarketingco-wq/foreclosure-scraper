"""Email extraction enricher — surfaces emails already present in raw data.

Emails are scattered across multiple raw fields from different scrapers:
  - raw["distressed"]["agent_email"]    — RE agent/broker emails (HomeHarvest)
  - raw["notice_contact"]               — attorney/trustee emails (legal notices)
  - raw["homeharvest"]["agent_email"]    — agent emails from non-distressed HomeHarvest
  - raw["skip_trace"]["emails"]          — owner emails from skip trace (if any)
  - raw["owner_email"]                  — already-extracted emails

This enricher:
  1. Scans all raw fields for email patterns
  2. Classifies each email: owner / agent / attorney / broker / other
  3. Writes a unified raw["owner_email"] block with classified emails
  4. Optionally hunts for more emails on listing source pages (rate-limited)

Free, no paid services. Uses stdlib re + urllib.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime
from typing import Sequence

import structlog

from .models import Listing

log = structlog.get_logger()

# Email regex — standard RFC 5322 simplified
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# Domains that are clearly not lead emails (notifications, noreply, etc.)
_NOISE_DOMAINS = frozenset({
    "noreply.com", "no-reply.com", "donotreply.com",
    "example.com", "test.com", "localhost",
})

# Attorney/law firm domain indicators
_LAW_DOMAINS = re.compile(r"law|legal|atty|attorney|counsel|esq", re.I)

# Broker/realty domain indicators
_REALTY_DOMAINS = re.compile(r"realty|realestate|realto|broker|property|homes", re.I)

# Fields to scan for emails (in priority order)
_SCAN_FIELDS = (
    "distressed",
    "homeharvest",
    "notice_contact",
    "skip_trace",
    "owner_phone",
    "zillow",
    "realtor",
    "trulia",
    "redfin",
)


def _classify_email(email: str, context_field: str = "") -> str:
    """Classify an email by domain and context.
    
    Returns: "owner" | "agent" | "attorney" | "broker" | "other"
    """
    domain = email.split("@")[-1].lower() if "@" in email else ""
    
    if domain in _NOISE_DOMAINS:
        return "other"
    
    if context_field in ("notice_contact",):
        return "attorney"
    
    if context_field in ("distressed", "homeharvest"):
        # Check sub-field name
        if _LAW_DOMAINS.search(domain):
            return "attorney"
        if _REALTY_DOMAINS.search(domain):
            return "broker"
        return "agent"
    
    if context_field in ("skip_trace", "owner_phone"):
        return "owner"
    
    if _LAW_DOMAINS.search(domain):
        return "attorney"
    if _REALTY_DOMAINS.search(domain):
        return "broker"
    
    return "other"


def _scan_raw_for_emails(raw: dict) -> list[dict]:
    """Scan all raw fields for email addresses.
    
    Returns list of {email, source_field, classification} dicts.
    """
    found: list[dict] = []
    seen_emails: set[str] = set()
    
    def _extract_from_value(val, field_path: str):
        """Recursively extract emails from any value."""
        if isinstance(val, str):
            for m in _EMAIL_RE.findall(val):
                email = m.lower().strip(".")
                if email not in seen_emails and email.split("@")[-1] not in _NOISE_DOMAINS:
                    seen_emails.add(email)
                    found.append({
                        "email": email,
                        "source_field": field_path,
                        "classification": _classify_email(email, field_path),
                    })
        elif isinstance(val, dict):
            for k, v in val.items():
                _extract_from_value(v, f"{field_path}.{k}" if field_path else k)
        elif isinstance(val, list):
            for i, item in enumerate(val):
                _extract_from_value(item, f"{field_path}[{i}]")
    
    # Scan known fields first
    for field in _SCAN_FIELDS:
        if field in raw:
            _extract_from_value(raw[field], field)
    
    # Also scan description and any remaining string fields
    if "description" in raw:
        _extract_from_value(raw["description"], "description")
    
    # Scan the entire raw dict for any missed emails
    for key, val in raw.items():
        if key not in _SCAN_FIELDS and key != "description" and key != "owner_email":
            if isinstance(val, (str, dict, list)):
                _extract_from_value(val, key)
    
    return found


def _fetch_page_emails(url: str, timeout: float = 10.0) -> list[str]:
    """Fetch a URL and extract emails from the HTML (rate-limited, best-effort).
    
    Only used for source pages that might have contact emails.
    Returns empty list on any error.
    """
    import urllib.request
    import ssl
    
    if not url or not url.startswith("http"):
        return []
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            if resp.status != 200:
                return []
            html = resp.read(200_000).decode("utf-8", errors="ignore")  # 200KB max
        
        return list(set(_EMAIL_RE.findall(html.lower())))
    except Exception:
        return []


def enrich_extract_emails(listings: Sequence[Listing], fetch_pages: bool = False) -> dict:
    """Extract and classify all emails from listing raw data.
    
    Args:
        listings: Board of Listing objects
        fetch_pages: If True, also fetch source pages to hunt for more emails
                     (rate-limited, slow — only for targeted campaigns)
    
    Returns:
        Stats dict with counts by classification
    """
    stats = {
        "listings_scanned": 0,
        "listings_with_emails": 0,
        "total_emails": 0,
        "by_classification": {
            "owner": 0,
            "agent": 0,
            "attorney": 0,
            "broker": 0,
            "other": 0,
        },
        "source_fields": {},
        "fetched_pages": 0,
        "page_emails_found": 0,
    }
    
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        stats["listings_scanned"] += 1
        
        # Check if already enriched (idempotent)
        existing = raw.get("owner_email")
        if isinstance(existing, dict) and existing.get("emails"):
            stats["listings_with_emails"] += 1
            stats["total_emails"] += len(existing.get("emails", []))
            for e in existing.get("emails", []):
                cls = e.get("classification", "other") if isinstance(e, dict) else "other"
                stats["by_classification"][cls] = stats["by_classification"].get(cls, 0) + 1
            continue
        
        emails = _scan_raw_for_emails(raw)
        
        # Optionally fetch source page for more emails
        if fetch_pages and not emails and li.source_url:
            page_emails = _fetch_page_emails(li.source_url)
            stats["fetched_pages"] += 1
            for pe in page_emails:
                if pe not in {e["email"] for e in emails}:
                    emails.append({
                        "email": pe,
                        "source_field": "source_page",
                        "classification": _classify_email(pe, "source_page"),
                    })
                    stats["page_emails_found"] += 1
        
        if emails:
            stats["listings_with_emails"] += 1
            stats["total_emails"] += len(emails)
            for e in emails:
                cls = e["classification"]
                stats["by_classification"][cls] = stats["by_classification"].get(cls, 0) + 1
                sf = e["source_field"]
                stats["source_fields"][sf] = stats["source_fields"].get(sf, 0) + 1
            
            # Pick best email for owner_email field
            # Priority: owner > attorney > agent > broker > other
            priority = {"owner": 0, "attorney": 1, "agent": 2, "broker": 3, "other": 4}
            best = min(emails, key=lambda e: priority.get(e["classification"], 99))
            
            raw["owner_email"] = {
                "emails": emails,
                "best_email": best["email"],
                "best_classification": best["classification"],
                "extracted_at": datetime.utcnow().isoformat(),
            }
        else:
            # Mark as scanned (empty) so we don't re-scan
            raw["owner_email"] = {
                "emails": [],
                "best_email": None,
                "best_classification": None,
                "extracted_at": datetime.utcnow().isoformat(),
            }
    
    log.info(
        "email_extraction.complete",
        scanned=stats["listings_scanned"],
        with_emails=stats["listings_with_emails"],
        total=stats["total_emails"],
        by_class=stats["by_classification"],
    )
    
    return stats
