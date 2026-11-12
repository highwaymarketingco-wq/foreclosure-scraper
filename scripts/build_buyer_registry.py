"""Data-driven buy-box + gator-lender registry from recorded deeds.

The static data/land_buyers.json is a hand-curated buyer universe. This harvester
adds the EMPIRICAL layer the dispo side was missing: who is ACTUALLY buying and
ACTUALLY private-lending in the footprint right now, mined free from the county
Register-of-Deeds recorded-document indexes we already reach browserlessly.

Two registries, both free + compliant (public ROD JSON, no login/CAPTCHA/pay):
  * data/discovered_cash_buyers.json — repeat ENTITY grantees on DEEDs. These are
    the live cash buyers / builders / land developers to flip a lead to (wholesale
    dispo). Ranked by deal count.
  * data/private_lenders.json — NON-BANK grantees (beneficiaries) on MORTGAGES /
    deeds of trust. These are the private / hard-money / "gator" funders to bring
    a subject-to or fix-flip deal to. Individuals + hard-money LLCs, banks removed.

Sources (extensible — add any free ROD vendor county here):
  * Acclaim (Harris) — deeds + mortgages, grantor/grantee/parcel. SC: Pickens.
  * CCHS (courthousecomputersystems) — deeds. NC: Burke, Cleveland, Madison, Henderson.

Run cadence: monthly (standing inventory, not an event feed). Reads back through
nothing — writes two standalone JSON registries that enrichment_buyer_match.py
loads to surface live buyers + a gator-lender lane on the card.

  uv run python scripts/build_buyer_registry.py [--days 120] [--min-deals 2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from foreclosure_scraper.http_client import client
from foreclosure_scraper.rod import acclaim, cchs

DATA = Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper" / "data"

# An entity name = a company that buys/lends (vs a natural person). Individuals are
# kept for lenders (private "gator" money is often a person) but not for buyers
# (a person buying one house is a homeowner, not a dispo target).
_ENTITY = re.compile(
    r"\b(LLC|L\.?L\.?C|INC|LP|LLLP|LLP|TRUST|HOLDINGS?|PROPERT|CAPITAL|GROUP|"
    r"HOMES?|INVEST|REAL ESTATE|VENTURES?|PARTNERS?|BUILDERS?|DEVELOP|EQUITY|"
    r"ENTERPRISE|ACQUISITION|RENTALS?|FUND|CONSTRUCT|LAND CO|ASSET)\b", re.I)

# Institutional lenders to REMOVE from the gator/private-lender registry — we only
# want private money (individuals + hard-money shops), not banks/servicers/GSEs.
# Anything with a lending/finance/bank token is institutional. This is deliberately
# aggressive: the private-money needle (an individual, or a bare-name LLC) has NONE
# of these tokens, so over-filtering here costs nothing and precision is everything.
_BANKISH = re.compile(
    r"\bBANK|CREDIT UNION|\bCU\b|F\.?C\.?U|S\.?E\.?C\.?U|MORTGAGE|"
    r"MORTG|ELECTRONIC REGISTRATION|\bMERS\b|LENDING|\bLOANS?\b|LOANDEPOT|"
    r"FINANC|FUNDING|\bCAPITAL\b|SAVINGS|BANCORP|BANCSHARES|"
    r"N\.?A\.?$|NATIONAL ASSOC|FEDERAL|GUARANTEED RATE|PRIMELENDING|ROCKET|"
    r"FREEDOM|WELLS FARGO|TRUIST|QUICKEN|PENNYMAC|CALIBER|MOVEMENT|\bCMG\b|"
    r"FAIRWAY|NAVY|MUTUAL OF OMAHA|LONGBRIDGE|NEWREZ|\bPHH\b|REVERSE MORTGAGE|"
    r"SECRETARY OF HOUSING|FANNIE|FREDDIE|USDA|VETERANS|\bSBA\b|FARM CREDIT|"
    r"AGSOUTH|AGCAROLINA|VANDERBILT|SUNTRUST|BB&T|\bPNC\b|REGIONS|SYNOVUS|"
    r"UNITED COMMUNITY|FIRST CITIZENS|SOUTH STATE|PARK NATIONAL|HOMETRUST|"
    r"SKYLINE|CHASE|CITIBANK|U\.?S\.? BANK|\bALLY\b|CARDINAL|CROSSCOUNTRY|"
    r"NETWORK FUNDING|CLEARPATH|CLEAR ?PATH|SERVICE ?LINK|LOANCARE|"
    r"MR\.? COOPER|CENLAR|BROKER SOLUTIONS|BARRETT FINANCIAL", re.I)

# A natural person recorded as "LASTNAME, FIRSTNAME [MIDDLE]" — an individual private
# lender (the purest "gator"/private-money signal: person lending to person).
_PERSON = re.compile(r"^[A-Z][A-Za-z'\-]+,\s+[A-Z][A-Za-z'\-]+")

# Land vs improved — coarse tag so buyer_match can route land buyers to land leads.
_LAND_HINT = re.compile(r"\b(LOT|ACRE|TRACT|PARCEL|VACANT|UNIMPROVED|LAND)\b", re.I)


def _norm(name: str) -> str:
    """Canonical key for aggregating name variants."""
    s = re.sub(r"[^A-Z0-9 &]", " ", (name or "").upper())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_entity(name: str) -> bool:
    return bool(_ENTITY.search(name or ""))


def _is_bankish(name: str) -> bool:
    return bool(_BANKISH.search(name or ""))


# Doc-type classification per vendor. Acclaim uses 'DEED'/'MTG'; CCHS spells them out.
_DEED_TOKENS = ("DEED", "WARRANTY", "TITLE TO REAL")
_MTG_TOKENS = ("MTG", "MORTGAGE", "DEED OF TRUST", "SECURITY DEED", " DOT")
# Exclude non-arms-length / non-purchase deed subtypes from the BUYER registry.
_DEED_EXCLUDE = ("DIST", "DEATH", "TIMBER", "EASE", "ROW", "MEMO", "POA", "MH T",
                 "TAX", "CORRECT", "QUIT", "GIFT", "TRUSTEE", "SHERIFF", "COMMISSIONER")


def _classify(doc_type: str) -> str | None:
    s = (doc_type or "").upper()
    if any(t in s for t in _MTG_TOKENS):
        return "lender"
    if any(t in s for t in _DEED_TOKENS) and not any(x in s for x in _DEED_EXCLUDE):
        return "buyer"
    return None


async def _harvest_acclaim(state: str, county: str, days: int) -> list[tuple[str, str, str, str]]:
    """Return (role, grantee_name, parcel, legal_note) rows from an Acclaim county."""
    base = acclaim.ACCLAIM_COUNTIES.get((state, county))
    if not base:
        return []
    today = datetime.utcnow()
    earliest = today - timedelta(days=days)
    out: list[tuple[str, str, str, str]] = []
    async with client(timeout=45.0) as c:
        await c.get(f"{base}/search/SearchTypeDocType")
        cur, first = today, True
        while cur > earliest:
            if not first:
                await asyncio.sleep(1.0)
            first = False
            frm = max(earliest, cur - timedelta(days=acclaim._CHUNK_DAYS))
            rows = await acclaim._search_chunk(c, base, frm, cur)
            for r in rows:
                role = _classify(r.get("DocType") or "")
                if not role:
                    continue
                grantee = (r.get("IndirectName") or "").strip()
                if grantee:
                    out.append((role, grantee, (r.get("ParcelNumber") or "").strip(),
                                (r.get("Comments") or "")[:120]))
            cur = frm - timedelta(days=1)
    return out


async def _harvest_cchs(state: str, county: str, days: int) -> list[tuple[str, str, str, str]]:
    """CCHS deeds (buyers). CCHS mortgage tokens vary by county; deeds are reliable."""
    today = datetime.utcnow()
    docs = await cchs._cchs_fetch(
        state, county, "DEED,WARRANTY DEED,GENERAL WARRANTY,SPECIAL WARRANTY DEED",
        today - timedelta(days=days), today, 1500, sold=False)
    out: list[tuple[str, str, str, str]] = []
    for d in docs:
        role = _classify(d.doc_type or "")
        if role != "buyer":
            continue
        if d.grantee:
            out.append(("buyer", d.grantee.strip(), (d.parcel_id or ""), (d.notes or "")[:120]))
    return out


ACCLAIM_TARGETS = [("SC", "Pickens")]
CCHS_TARGETS = [("NC", "Burke"), ("NC", "Cleveland"), ("NC", "Madison"), ("NC", "Henderson")]


async def build(days: int, min_deals: int) -> tuple[dict, dict]:
    buyers: dict[str, dict] = defaultdict(
        lambda: {"deals": 0, "counties": defaultdict(int), "land": 0, "improved": 0,
                 "sample_parcels": []})
    lenders: dict[str, dict] = defaultdict(
        lambda: {"loans": 0, "counties": defaultdict(int), "sample_parcels": []})

    tasks = ([_harvest_acclaim(s, c, days) for s, c in ACCLAIM_TARGETS]
             + [_harvest_cchs(s, c, days) for s, c in CCHS_TARGETS])
    labels = [f"{c},{s}" for s, c in ACCLAIM_TARGETS] + [f"{c},{s}" for s, c in CCHS_TARGETS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for label, res in zip(labels, results):
        if isinstance(res, Exception):
            print(f"  {label}: ERROR {type(res).__name__}: {str(res)[:80]}")
            continue
        print(f"  {label}: {len(res)} deed/mortgage grantee rows")
        for role, name, parcel, legal in res:
            key = _norm(name)
            if not key:
                continue
            if role == "buyer":
                if not _is_entity(name):
                    continue  # a person buying one house is not a dispo target
                b = buyers[key]
                b["name"] = name
                b["deals"] += 1
                b["counties"][label] += 1
                if _LAND_HINT.search(legal):
                    b["land"] += 1
                else:
                    b["improved"] += 1
                if parcel and len(b["sample_parcels"]) < 3:
                    b["sample_parcels"].append(f"{label}:{parcel}")
            else:  # lender
                if _is_bankish(name):
                    continue  # keep only private / gator money
                # A private lender is either a natural person OR a bare-name LLC/trust
                # with no lending/finance token. Anything else is noise, drop it.
                is_person = bool(_PERSON.match(name))
                if not (is_person or _is_entity(name)):
                    continue
                lo = lenders[key]
                lo["name"] = name
                lo["loans"] += 1
                lo["counties"][label] += 1
                lo["is_individual"] = is_person
                if parcel and len(lo["sample_parcels"]) < 3:
                    lo["sample_parcels"].append(f"{label}:{parcel}")

    # Rank + filter. Buyers: repeat (>= min_deals) are the real active buyers; keep
    # single-deal entities too but flag tier so the card can prefer repeaters.
    buyer_list = []
    for b in buyers.values():
        tier = "active" if b["deals"] >= min_deals else "single"
        buyer_list.append({
            "name": b["name"], "deals": b["deals"], "tier": tier,
            "counties": dict(b["counties"]),
            "buys": "land" if b["land"] > b["improved"] else "improved",
            "sample_parcels": b["sample_parcels"],
        })
    buyer_list.sort(key=lambda x: (-x["deals"], x["name"]))

    lender_list = []
    for lo in lenders.values():
        lender_list.append({
            "name": lo["name"], "loans": lo["loans"],
            "kind": "individual" if lo.get("is_individual") else "private_fund",
            "counties": dict(lo["counties"]), "sample_parcels": lo["sample_parcels"],
        })
    # Individuals (person-to-person private notes) rank above funds — purest gator money.
    lender_list.sort(key=lambda x: (x["kind"] != "individual", -x["loans"], x["name"]))

    stamp = datetime.utcnow().strftime("%Y-%m-%d")
    return (
        {"generated": stamp, "window_days": days, "min_deals": min_deals,
         "note": "Repeat entity grantees on recorded DEEDs = live cash buyers (wholesale dispo). "
                 "Free ROD mining; contact via SoS registered-agent (LLC) or skip-trace.",
         "buyers": buyer_list},
        {"generated": stamp, "window_days": days,
         "note": "Non-bank grantees on recorded MORTGAGES = private/gator lenders "
                 "(subject-to / fix-flip funding). Banks/GSEs/servicers removed.",
         "lenders": lender_list},
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--min-deals", type=int, default=2)
    args = ap.parse_args()

    print(f"Harvesting recorded deeds/mortgages ({args.days}d) from free ROD indexes...")
    buyers_doc, lenders_doc = await build(args.days, args.min_deals)

    (DATA / "discovered_cash_buyers.json").write_text(json.dumps(buyers_doc, indent=2))
    (DATA / "private_lenders.json").write_text(json.dumps(lenders_doc, indent=2))
    nb = len(buyers_doc["buyers"])
    active = sum(1 for b in buyers_doc["buyers"] if b["tier"] == "active")
    nl = len(lenders_doc["lenders"])
    print(f"\nWROTE data/discovered_cash_buyers.json: {nb} entity buyers ({active} repeat/active)")
    print(f"WROTE data/private_lenders.json: {nl} private/gator lenders")
    print("\nTop active buyers:")
    for b in buyers_doc["buyers"][:10]:
        print(f"  {b['deals']}x  {b['name'][:52]:52} buys={b['buys']} {list(b['counties'])}")
    print("Top private lenders:")
    for lo in lenders_doc["lenders"][:10]:
        print(f"  {lo['loans']}x  {lo['name'][:52]:52} ({lo['kind']})")


if __name__ == "__main__":
    asyncio.run(main())
