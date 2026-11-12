"""Ingest a skip-trace / contact export (Propwire, BatchSkipTracing, any CSV) and
attach phones/emails/mailing to matching board leads.

This is the COMPLIANT contact path: instead of scraping ToS/bot-walled consumer
people-search sites, the operator exports skip-traces from their own account
(within that tool's free or paid quota) and drops the file here — same pattern as
the NC-court manual export. We match each row to a lead by parcel_id (preferred)
or normalized property address, then stamp:

    raw['contact'] = {
        phones: [...], emails: [...], mailing_address, name,
        source, needs_dnc_scrub: True, ingested_at
    }

Phones are ALWAYS tagged needs_dnc_scrub — nothing here is call/text-ready until a
DNC/TCPA scrub runs. Header matching is fuzzy so it tolerates whatever column names
the export uses. Pure-Python, idempotent (re-ingesting updates in place).
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from .models import Listing

# fuzzy header -> canonical field. Matched against a lowercased, de-punctuated header.
_HEADER_ALIASES = {
    "name": ("ownername", "owner", "name", "fullname", "contactname", "defendant"),
    "mailing": ("mailingaddress", "mailaddress", "mailing", "owneraddress", "ownermailing"),
    "prop_addr": ("propertyaddress", "propaddress", "situsaddress", "situs", "address",
                  "siteaddress", "streetaddress"),
    "parcel": ("parcel", "parcelid", "apn", "parcelnumber", "tms", "pin", "taxid"),
    "phone": ("phone", "phonenumber", "mobile", "cell", "telephone", "phone1", "phone2",
              "phone3", "phone4", "phone5", "landline", "wireless"),
    "email": ("email", "emailaddress", "email1", "email2", "email3"),
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def _classify_header(h: str) -> Optional[str]:
    n = _norm_header(h)
    for field, aliases in _HEADER_ALIASES.items():
        if n in aliases:
            return field
    # prefix match for numbered phone/email columns (phone_1, email2, etc.)
    if n.startswith("phone") or n.startswith("cell") or n.startswith("mobile"):
        return "phone"
    if n.startswith("email"):
        return "email"
    return None


def _digits(s: str) -> Optional[str]:
    d = re.sub(r"\D", "", s or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else None


def _pkey(pid: Optional[str]) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", pid or "").upper()


def _akey(addr: Optional[str]) -> str:
    """Loose address key: house-number + first street token, upper, no punctuation."""
    s = re.sub(r"[^0-9A-Za-z ]", " ", (addr or "").upper())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def map_row(row: dict) -> dict:
    """Normalize one CSV row dict -> {name, mailing, prop_addr, parcel, phones[], emails[]}."""
    out = {"name": None, "mailing": None, "prop_addr": None, "parcel": None,
           "phones": [], "emails": []}
    for header, val in row.items():
        if val in (None, ""):
            continue
        field = _classify_header(header)
        if field == "phone":
            d = _digits(str(val))
            if d and d not in out["phones"]:
                out["phones"].append(d)
        elif field == "email":
            e = str(val).strip().lower()
            if "@" in e and e not in out["emails"]:
                out["emails"].append(e)
        elif field and out[field] is None:
            out[field] = str(val).strip()
    return out


def ingest_contacts(listings: Iterable[Listing], rows: Iterable[dict],
                    source: str = "skip_trace_export", ingested_at: str = "") -> dict:
    """Attach mapped contact rows to matching leads. rows are raw CSV dicts."""
    listings = list(listings)
    by_parcel: dict[str, Listing] = {}
    by_addr: dict[str, Listing] = {}
    for li in listings:
        if (li.parcel_id or "").strip():
            by_parcel.setdefault(_pkey(li.parcel_id), li)
        if (li.street_address or "").strip():
            by_addr.setdefault(_akey(li.street_address), li)

    matched = phones = emails = unmatched = 0
    for raw_row in rows:
        m = map_row(raw_row)
        li = None
        if m["parcel"]:
            li = by_parcel.get(_pkey(m["parcel"]))
        if li is None and m["prop_addr"]:
            li = by_addr.get(_akey(m["prop_addr"]))
        if li is None:
            unmatched += 1
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        prior = li.raw.get("contact") or {}
        ph = sorted(set((prior.get("phones") or []) + m["phones"]))
        em = sorted(set((prior.get("emails") or []) + m["emails"]))
        li.raw["contact"] = {
            "phones": ph, "emails": em,
            "mailing_address": m["mailing"] or prior.get("mailing_address"),
            "name": m["name"] or prior.get("name"),
            "source": source, "needs_dnc_scrub": True,
            "ingested_at": ingested_at or prior.get("ingested_at"),
        }
        matched += 1
        phones += len(m["phones"])
        emails += len(m["emails"])

    return {"matched": matched, "unmatched": unmatched,
            "phones_added": phones, "emails_added": emails}
