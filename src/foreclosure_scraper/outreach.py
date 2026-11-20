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
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import structlog

from .identity import rod_chain_conveyance_owner, suspicious_owner_name
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

def _owner_candidates(li: Listing) -> list[tuple[str | None, str | None]]:
    """Every owner-name source _owner() will consider, in its reliability order, each paired
    with the provenance tag suspicious_owner_name() needs for the entity_from_lien_filing rule
    (raw['owner_mailing']['source']). li.owner_name and skip_trace.owner_name share that same
    tag: on a row liensnc_handoff.py originated, BOTH fields were set from that filing's own
    unvalidated owner_text parse, so either one can carry that same provenance. li.defendant
    (the court filing's own party name) carries none.

    identity.rod_chain_conveyance_owner() goes FIRST, ahead of li.owner_name itself: unlike
    every other candidate here (all read off a county roll or tax-record snapshot that can go
    stale after a real sale -- see _owner()'s docstring), it is a specific recorded deed,
    independently tied to THIS row's own parcel, naming whoever the county register's OWN index
    says holds title today. Its provenance tag is 'rod_chain_conveyance', never a
    _LIEN_FILING_SOURCES value, so an entity-suffixed grantee from this source is never wrongly
    caught by the entity_from_lien_filing rule the way a lien filing's own unvalidated parse is."""
    raw = li.raw or {}
    st = raw.get("skip_trace") or {}
    om = raw.get("owner_mailing")
    lien_source = om.get("source") if isinstance(om, dict) else None
    conveyance = rod_chain_conveyance_owner(li)
    return [
        (conveyance.get("name") if conveyance else None, "rod_chain_conveyance"),
        (li.owner_name, lien_source),
        (st.get("owner_name"), lien_source),
        (li.defendant, None),
    ]


def _owner(li: Listing) -> str | None:
    """Best available owner name for outreach: the first candidate, in reliability order, that
    does NOT read as a non-owner party (suspicious_owner_name() -- a lienholder, government
    body, or job title; see identity.py's module docstring, "PARTY-ROLE CONFUSION"). A flagged
    candidate is skipped, never returned -- this fails safe by falling through to the next
    candidate, or to the generic "Property Owner" default (via _first_name(None)) when every
    candidate is empty or flagged. Reliability order:

    1. identity.rod_chain_conveyance_owner() — a register deed PROVEN (not merely name-matched)
       to be THIS parcel's, naming whoever the county's own index says the prior owner (li.
       owner_name's own source, further down this chain) already conveyed it to. None on the
       overwhelming majority of rows (rod_chain is off by default and covers a small slice of
       NC counties) -- this is the one candidate that can be MORE current than li.owner_name
       itself, see 2026-11-20 below.
    2. li.owner_name — the board's primary, actively-maintained owner field.
       identity.py's resolve_owner()/owner_verdict() keep it bound to the
       county's CURRENT record of THIS parcel (classifying every contradicting
       claim as bound/unbound/foreign/historical before trusting it) and
       correct it in place when the county disagrees.
    3. raw['skip_trace']['owner_name'] — written by enrichment_skip_trace.py's
       TaxRecordsOnlyProvider, which (2026-11-19) now itself prefers
       li.owner_name over the unvalidated owner_mailing/gis claim, and is
       re-run (not frozen forever) on a row PROVABLY carrying a name
       identity.py has since rejected (see that module's
       _skip_trace_owner_is_stale()). Used only when li.owner_name itself is
       empty or flagged.
    4. li.defendant — the court filing's defendant name; last resort.

    2026-11-19 verification (20 rows sampled from 3,264 contactable rows where
    li.owner_name and skip_trace.owner_name disagreed, 18 live-confirmed against county
    sources): li.owner_name was right 11/18 (61%), skip_trace.owner_name 4/18 (22%,
    concentrated in builder-owned new-construction and heir/estate parcels), NEITHER 3/18 --
    a lienholder/government/job-title name read as the owner, the different "party-role
    confusion" defect suspicious_owner_name() exists to catch. Before the first fix, _owner()
    read skip_trace.owner_name first and never looked at li.owner_name at all.

    2026-11-20 follow-up on that 22% ("too small a slice, and with no reliable flag to key off
    at this call site" per the fix's own commit message): live-checked again this session
    against 24,154 real rows whose owner_name reads as a builder/developer entity -- this
    board's deed_chain has no usable grantor/grantee signal for that population at all (0 of
    4,268 rows with any deed_chain have the entity as a transfer's grantor paired with a
    different grantee), so there is genuinely nothing safe to key off there; identity.py's
    module docstring has the measurement. raw['rod_chain']['conveyed_out_since'] (a different,
    narrower enrichment, off by default) DOES carry a real signal, but only when independently
    tied to this exact parcel -- identity.rod_chain_conveyance_owner()/_conveyance_confirmed()
    is that check, and candidate 1 above is its result. Everything that fails it (today, nearly
    every row) falls straight through to li.owner_name exactly as before.
    """
    for name, source in _owner_candidates(li):
        if name and not suspicious_owner_name(name, source=source):
            return name
    return None


def _owner_identity_uncertain(li: Listing) -> bool:
    """True when at least one of this listing's owner candidates was suspicious enough that
    _owner() had to skip past it. Purely an audit signal -- stamped onto
    raw['owner_identity_uncertain'] by generate_outreach() so a flagged row is visible/reviewable
    later; _owner() itself already fails safe on its own and never consults this flag."""
    return any(name and suspicious_owner_name(name, source=source)
               for name, source in _owner_candidates(li))


def _dnc_clear_phones(raw: dict) -> list[str]:
    """Every phone this listing's raw['dnc_scrub'] (enrichment_dnc.py) has actually confirmed
    safe to dial -- dnc_status "clear", nothing else. unverified/blocked/on_registry/
    on_internal_dnc phones are never returned here, however confident the name match was: the
    TSR compliance call (16 CFR 310.4(b)(3)(iv)) belongs entirely to enrichment_dnc.py, this
    only reads its verdict, never re-derives or loosens one. 2026-10-16: as of writing, this
    returns [] for every listing on the real board, correctly -- no data/dnc_registry.csv is
    installed (an operator-side FTC registry subscription, not something this codebase can
    obtain), so enrichment_dnc.py can never answer "clear" for anyone yet, only "unverified" or
    "blocked". That is not a bug in this function; it is the honest, compliant answer with the
    inputs available. Formatted (xxx) xxx-xxxx to match owner_phone/skip_trace's own shape."""
    scrub = raw.get("dnc_scrub")
    if not isinstance(scrub, list):
        return []
    out = []
    for e in scrub:
        if not (isinstance(e, dict) and e.get("dnc_status") == "clear"):
            continue
        p = re.sub(r"\D", "", str(e.get("phone") or ""))
        if len(p) == 10:
            out.append(f"({p[:3]}) {p[3:6]}-{p[6:]}")
    return out


def _contact(li: Listing) -> dict:
    raw = li.raw or {}
    st = raw.get("skip_trace") or {}
    # skip_trace['phone_numbers'] is a PAID-skip-trace-provider-only field (that module's own
    # docstring: "paid only") -- this project is free-only (docs/HERMES.md), so in practice it
    # is never populated (confirmed: 0 of 353,609 board rows, 2026-10-16). The real, free phone
    # pipeline (voter_phone / county_phone / surface_contacts / liensnc / free_phones /
    # sc_voter_xref -- see enrichment_dnc._get_phone_records for the full list) lands at
    # raw['owner_phone'] instead, and this function never looked there at all -- found while
    # investigating why outreach.done's own with_phone stat has always read 0 across every run.
    # Merged rather than falling back to one or the other, in case skip_trace is ever turned on
    # for real: a phone appearing in both is not double-counted.
    phones = list(dict.fromkeys((st.get("phone_numbers") or []) + _dnc_clear_phones(raw)))
    return {
        "owner": _owner(li),
        "mailing_address": st.get("owner_mailing_address"),
        "absentee": st.get("absentee_owner", False),
        "phones": phones,
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
        if _owner_identity_uncertain(li):
            li.raw["owner_identity_uncertain"] = True
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
