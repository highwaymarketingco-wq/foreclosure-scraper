"""Outreach stack — turn distressed-property leads into owner contact actions.

Foreclosure investors contact owners BEFORE the sale (cash offer / short-sale
buyout). This module converts each enriched listing into ready-to-send
outreach across four channels, plus a persistent lightweight CRM so lead
status survives the weekly re-scrape.

Components (per the owner's request: CRM / SMS / Email / Name Search):
  * NAME SEARCH  — find_by_owner(): look up leads by owner/defendant name.
  * CRM          — load_crm()/save_crm() persist {status, notes, history}
                   keyed by the listing's stable dedupe_key in docs/crm.json,
                   merged back onto each listing as raw["crm"]. Status
                   survives re-scrapes (a re-found listing keeps its status).
  * EMAIL/LETTER — personalized cash-offer letter + email text per lead.
  * SMS          — short personalized text per lead.
  * MAIL LIST    — docs/outreach_maillist.csv for postcard/letter mail-merge
                   (the #1 foreclosure outreach channel). Owner + mailing
                   address come from the free skip-trace (tax-records).

All generation is local + free. Actually SENDING (Gmail/Twilio/print-mail)
is left to the operator — we produce the content + the contact list.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

CRM_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "crm.json"
MAILLIST_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "outreach_maillist.csv"

# CRM lifecycle. A re-scraped listing keeps whatever status the operator set.
VALID_STATUSES = (
    "new", "queued", "contacted", "offer_made", "negotiating",
    "under_contract", "won", "dead", "not_interested",
)
DEFAULT_STATUS = "new"


# ---- CRM persistence -------------------------------------------------------

def load_crm() -> dict:
    """Load the persistent CRM state {dedupe_key: {status, notes, history,...}}."""
    if CRM_PATH.exists():
        try:
            return json.loads(CRM_PATH.read_text(encoding="utf-8"))
        except Exception:
            log.warning("crm.load_failed")
    return {}


def save_crm(crm: dict) -> None:
    CRM_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRM_PATH.write_text(json.dumps(crm, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ---- helpers ---------------------------------------------------------------

def _owner(li: Listing) -> str | None:
    st = (li.raw or {}).get("skip_trace") or {}
    return st.get("owner_name") or li.defendant or None


def _contact(li: Listing) -> dict:
    st = (li.raw or {}).get("skip_trace") or {}
    return {
        "owner": _owner(li),
        "mailing_address": st.get("owner_mailing_address"),
        "absentee": st.get("absentee_owner", False),
        "phones": st.get("phone_numbers") or [],
    }


def _money(v) -> str:
    try:
        return f"${float(v):,.0f}" if v else ""
    except (TypeError, ValueError):
        return ""


def _first_name(owner: str | None) -> str:
    if not owner:
        return "Property Owner"
    # GIS owners are "LAST FIRST" or "LAST, FIRST"; court defendants "First Last".
    o = owner.replace(",", " ").split()
    if len(o) >= 2:
        # Heuristic: if all-caps GIS style "SMITH JOHN", first name is 2nd token.
        return o[1].title() if owner.isupper() else o[0].title()
    return o[0].title() if o else "Property Owner"


# ---- message generation ----------------------------------------------------

def letter_text(li: Listing) -> str:
    name = _first_name(_owner(li))
    addr = li.street_address or "your property"
    city = f", {li.city}" if li.city else ""
    return (
        f"Dear {name},\n\n"
        f"I'm a local real-estate investor and I'm reaching out about {addr}{city}. "
        f"I understand the property may be facing a foreclosure or tax sale, and I "
        f"wanted you to know you have options before the sale date.\n\n"
        f"I can make a fair cash offer, close on your timeline, and help you avoid "
        f"the sale appearing on your record. There's no obligation and no fees.\n\n"
        f"If you'd like to talk through your options, please call or text me anytime.\n\n"
        f"Sincerely,\nYour Name\nYour Phone"
    )


def email_text(li: Listing) -> str:
    name = _first_name(_owner(li))
    addr = li.street_address or "your property"
    return (
        f"Subject: A fair cash option for {addr} before the sale\n\n"
        f"Hi {name},\n\n"
        f"I work with homeowners in {li.county or 'your'} County who are facing a "
        f"foreclosure or tax sale. I can present a no-obligation cash offer on "
        f"{addr} and close on your schedule — often before the sale date.\n\n"
        f"Would you be open to a quick call this week?\n\n"
        f"Best,\nYour Name — Your Phone"
    )


def sms_text(li: Listing) -> str:
    name = _first_name(_owner(li))
    addr = li.street_address or "your property"
    return (
        f"Hi {name}, I'm a local investor. I can make a no-obligation cash offer on "
        f"{addr} before the sale and close on your timeline. Open to a quick call? "
        f"Reply STOP to opt out."
    )


# ---- main entry point ------------------------------------------------------

def generate_outreach(listings: list[Listing]) -> dict:
    """Attach raw['outreach'] + raw['crm'] to every contactable distressed
    listing, persist CRM state, and return stats."""
    crm = load_crm()
    now = datetime.utcnow().isoformat() + "Z"
    stats = {"contactable": 0, "with_phone": 0, "with_mailing": 0, "crm_tracked": 0}

    for li in listings:
        if not isinstance(li.raw, dict):
            li.raw = {}
        contact = _contact(li)
        # Contactable = we have at least an owner name + (mailing addr or phone).
        contactable = bool(contact["owner"]) and bool(
            contact["mailing_address"] or contact["phones"]
        )
        if not contactable:
            continue
        stats["contactable"] += 1
        if contact["phones"]:
            stats["with_phone"] += 1
        if contact["mailing_address"]:
            stats["with_mailing"] += 1

        # Channel priority: phone (fastest) > mail (reliable) > none.
        channels = []
        if contact["phones"]:
            channels.append("sms")
        if contact["mailing_address"]:
            channels.append("mail")
        channels.append("email")  # always draftable

        li.raw["outreach"] = {
            "owner": contact["owner"],
            "mailing_address": contact["mailing_address"],
            "phones": contact["phones"],
            "absentee": contact["absentee"],
            "channels": channels,
            "letter": letter_text(li),
            "email": email_text(li),
            "sms": sms_text(li),
        }

        # CRM: keyed by stable dedupe identity so status survives re-scrapes.
        key = li.dedupe_key()
        rec = crm.get(key)
        if rec is None:
            rec = {
                "status": DEFAULT_STATUS,
                "owner": contact["owner"],
                "property": li.street_address,
                "county": li.county,
                "first_seen": now,
                "last_seen": now,
                "notes": "",
                "history": [{"at": now, "event": "lead_created"}],
            }
            crm[key] = rec
        else:
            rec["last_seen"] = now
            rec.setdefault("status", DEFAULT_STATUS)
        li.raw["crm"] = {"status": rec.get("status", DEFAULT_STATUS),
                         "notes": rec.get("notes", "")}
        stats["crm_tracked"] += 1

    save_crm(crm)
    write_maillist(listings)
    log.info("outreach.done", **stats)
    return stats


def write_maillist(listings: list[Listing], path: Path | None = None) -> int:
    """Write a postcard/letter mail-merge CSV for every listing with an owner
    + mailing address. Returns row count."""
    path = path or MAILLIST_PATH
    rows = []
    for li in listings:
        o = (li.raw or {}).get("outreach") or {}
        if not o.get("mailing_address"):
            continue
        calc = (li.raw or {}).get("calc") or {}
        rows.append({
            "owner": o.get("owner") or "",
            "mailing_address": o.get("mailing_address") or "",
            "property_address": li.street_address or "",
            "city": li.city or "",
            "county": li.county or "",
            "state": li.state or "",
            "listing_type": li.listing_type.value if li.listing_type else "",
            "sale_date": li.sale_date.date().isoformat() if li.sale_date else "",
            "est_arv": _money(calc.get("arv")),
            "max_bid": _money(calc.get("max_bid")),
            "deal_verdict": calc.get("verdict") or (li.raw or {}).get("grade", {}).get("overall", ""),
            "phone": ";".join(o.get("phones") or []),
            "absentee": "Y" if o.get("absentee") else "",
            "source_url": li.source_url or "",
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    log.info("outreach.maillist", rows=len(rows), path=str(path))
    return len(rows)


# ---- Name Search -----------------------------------------------------------

def find_by_owner(listings: list[Listing], query: str) -> list[Listing]:
    """Name Search: return listings whose owner/defendant matches `query`
    (case-insensitive substring on either the GIS owner or court defendant)."""
    q = query.strip().lower()
    if not q:
        return []
    out = []
    for li in listings:
        owner = (_owner(li) or "").lower()
        if q in owner:
            out.append(li)
    return out
