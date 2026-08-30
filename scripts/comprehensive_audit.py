#!/usr/bin/env python3
"""Comprehensive audit: county breakdown, source/avenue breakdown, distressed signal gaps."""
import json, gzip
from collections import Counter, defaultdict
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

with gzip.open(DOCS / "listings.json.gz", "rt") as f:
    data = json.load(f)

n = len(data)
print(f"TOTAL LISTINGS: {n:,}\n")

# ── COUNTY BREAKDOWN ──
print("=" * 120)
print("COUNTY BREAKDOWN")
print("=" * 120)

header_fields = ["coords", "sqft", "flood", "amount_owed", "assessed", "equity",
                 "red_flags", "deed_chain", "title_risk", "life_events",
                 "tax_delinq", "bankruptcy", "liens", "code_enf",
                 "mortgage", "comps", "own_mism", "vacant",
                 "storm", "septic", "evict", "incarc",
                 "probate", "divorce"]

county_data = {}  # county -> {field: count}

for d in data:
    c = d.get("county", "Unknown")
    raw = d.get("raw") or {}
    if c not in county_data:
        county_data[c] = {f: 0 for f in header_fields}
        county_data[c]["total"] = 0
    s = county_data[c]
    s["total"] += 1
    if d.get("latitude") and d.get("longitude"): s["coords"] += 1
    if d.get("living_sqft") and d["living_sqft"] > 0: s["sqft"] += 1
    if raw.get("flood_zone"): s["flood"] += 1
    if raw.get("amount_owed"): s["amount_owed"] += 1
    if d.get("assessed_value") and d["assessed_value"] > 0: s["assessed"] += 1
    if raw.get("equity"): s["equity"] += 1
    if raw.get("red_flags"): s["red_flags"] += 1
    dc = raw.get("deed_chain") or {}
    if dc.get("transfers"): s["deed_chain"] += 1
    if raw.get("title_risk"): s["title_risk"] += 1
    if raw.get("life_events"): s["life_events"] += 1
    if (raw.get("sc_tax_delinquent") or raw.get("nc_ptscloud_delinquent_tax")
            or raw.get("two_year_delinquent") == "yes"):
        s["tax_delinq"] += 1
    bk = raw.get("bankruptcy_stay") or {}
    if bk.get("chapter") or raw.get("bankruptcy"):
        s["bankruptcy"] += 1
    if raw.get("liens"): s["liens"] += 1
    if raw.get("code_enforcement"): s["code_enf"] += 1
    le = raw.get("life_events") or []
    if any("probate" in str(e).lower() for e in le): s["probate"] += 1
    if any("divorce" in str(e).lower() for e in le): s["divorce"] += 1
    if d.get("loan_amount") or raw.get("loan_amount"): s["mortgage"] += 1
    if raw.get("comps"): s["comps"] += 1
    if raw.get("owner_mismatch"): s["own_mism"] += 1
    if raw.get("vacant_lot"): s["vacant"] += 1
    if raw.get("storm_damage"): s["storm"] += 1
    if raw.get("septic"): s["septic"] += 1
    em = raw.get("eviction_market") or {}
    if em.get("tier"): s["evict"] += 1
    inc = raw.get("incarceration") or {}
    if inc.get("state"): s["incarc"] += 1

# Print county table
print(f"\n{'County':<16} {'Total':>6}", end="")
for f in header_fields:
    print(f" {f:>7}", end="")
print()
print("-" * (22 + 8 * len(header_fields)))

for c in sorted(county_data, key=lambda x: -(county_data[x].get("total") or 0)):
    s = county_data[c]
    t = s.get("total") or 0
    c = str(c) if c else "Unknown"
    print(f"{c:<16} {t:>6,}", end="")
    for f in header_fields:
        v = s.get(f, 0) or 0
        print(f" {v:>7,}", end="")
    print()

# Totals
print("-" * (22 + 8 * len(header_fields)))
print(f"{'TOTAL':<16} {n:>6,}", end="")
for f in header_fields:
    total = sum(county_data[c].get(f, 0) for c in county_data)
    print(f" {total:>7,}", end="")
print()

# Percentages
print(f"\n{'PERCENT':<16} {'':>6}", end="")
for f in header_fields:
    total = sum(county_data[c].get(f, 0) for c in county_data)
    pct = total / n * 100 if n > 0 else 0
    print(f" {pct:>6.1f}%", end="")
print()

# ── SOURCE/AVENUE BREAKDOWN ──
print("\n" + "=" * 120)
print("SOURCE / AVENUE BREAKDOWN")
print("=" * 120)

source_counts = Counter()
source_state = defaultdict(lambda: defaultdict(int))
for d in data:
    src = d.get("source", "unknown")
    source_counts[src] += 1
    state = d.get("state", "")
    source_state[src][state] += 1

print(f"\n{'Source':<45} {'Total':>8} {'States':>30}")
print("-" * 85)
for src, cnt in source_counts.most_common():
    states = ", ".join(f"{s}:{c}" for s, c in sorted(source_state[src].items(), key=lambda x: -x[1]))
    print(f"{src:<45} {cnt:>8,} {states}")

# ── STATE BREAKDOWN ──
print("\n" + "=" * 120)
print("STATE BREAKDOWN")
print("=" * 120)
state_counts = Counter(d.get("state", "Unknown") for d in data)
for st, cnt in state_counts.most_common():
    print(f"  {st}: {cnt:,} ({cnt/n*100:.1f}%)")

# ── DISTRESSED SIGNAL GAPS ──
print("\n" + "=" * 120)
print("DISTRESSED SIGNAL GAPS — What We're Missing")
print("=" * 120)

signal_fields = [
    ("deed_chain", "Deed chain (ownership history)"),
    ("title_risk", "Title risk (junior/senior liens)"),
    ("life_events", "Life events (death, divorce, probate)"),
    ("bankruptcy", "Bankruptcy filings/stays"),
    ("liens", "Liens (utility, tax, mechanics)"),
    ("code_enforcement", "Code enforcement violations"),
    ("mortgage", "Mortgage/loan amount remaining"),
    ("comps", "Comparable sales (comps)"),
    ("owner_mismatch", "Owner mismatch (mailing vs property)"),
    ("vacant", "Vacant lot/property"),
    ("storm_damage", "Storm damage history"),
    ("septic", "Septic system issues"),
    ("eviction", "Eviction market data"),
    ("incarceration", "Incarcerated owner"),
    ("probate", "Probate proceedings"),
    ("divorce", "Divorce filings"),
    ("red_flags", "Red flags (any)"),
    ("tax_delinq", "Tax delinquency"),
    ("upset_bid", "Upset bid (NC auction)"),
    ("fema_repetitive_loss", "FEMA repetitive loss"),
    ("sos_dissolution", "LLC dissolution (SOS)"),
]

print(f"\n{'Signal':<35} {'Have':>8} {'Missing':>8} {'Coverage':>10} {'Gap':>10}")
print("-" * 75)
for field, label in signal_fields:
    have = 0
    for d in data:
        raw = d.get("raw") or {}
        if field == "deed_chain":
            dc = raw.get("deed_chain") or {}
            if dc.get("transfers"): have += 1
        elif field == "bankruptcy":
            bk = raw.get("bankruptcy_stay") or {}
            if bk.get("chapter") or raw.get("bankruptcy"): have += 1
        elif field == "mortgage":
            if d.get("loan_amount") or raw.get("loan_amount"): have += 1
        elif field == "upset_bid":
            ub = raw.get("upset_bid") or {}
            if ub.get("in_window"): have += 1
        elif field == "fema_repetitive_loss":
            if raw.get("fema_repetitive_loss"): have += 1
        elif field == "sos_dissolution":
            if raw.get("sos_dissolution"): have += 1
        elif field == "vacant":
            if raw.get("vacant_lot"): have += 1
        elif field == "eviction":
            em = raw.get("eviction_market") or {}
            if em.get("tier"): have += 1
        elif field == "incarceration":
            inc = raw.get("incarceration") or {}
            if inc.get("state"): have += 1
        elif field == "title_risk":
            tr = raw.get("title_risk") or {}
            if tr.get("kind"): have += 1
        elif field == "probate":
            le = raw.get("life_events") or []
            if any("probate" in str(e).lower() for e in le): have += 1
        elif field == "divorce":
            le = raw.get("life_events") or []
            if any("divorce" in str(e).lower() for e in le): have += 1
        elif field == "red_flags":
            if raw.get("red_flags"): have += 1
        elif field == "tax_delinq":
            if (raw.get("sc_tax_delinquent") or raw.get("nc_ptscloud_delinquent_tax")
                    or raw.get("two_year_delinquent") == "yes"):
                have += 1
        else:
            if raw.get(field): have += 1
    missing = n - have
    pct = have / n * 100 if n > 0 else 0
    print(f"{label:<35} {have:>8,} {missing:>8,} {pct:>9.1f}% {missing:>10,}")

# ── PROPERTY TYPE BREAKDOWN ──
print("\n" + "=" * 120)
print("PROPERTY TYPE BREAKDOWN")
print("=" * 120)
kind_counts = Counter(d.get("property_kind", "unknown") for d in data)
for k, cnt in kind_counts.most_common():
    print(f"  {k}: {cnt:,} ({cnt/n*100:.1f}%)")

# ── EQUITY DISTRIBUTION ──
print("\n" + "=" * 120)
print("EQUITY DISTRIBUTION")
print("=" * 120)
eq_buckets = {"Deep equity (>50%)": 0, "Moderate (20-50%)": 0, "Thin (0-20%)": 0, "Underwater (<0%)": 0, "Unknown": 0}
for d in data:
    raw = d.get("raw") or {}
    eq = raw.get("equity")
    if eq is None:
        eq_buckets["Unknown"] += 1
        continue
    if isinstance(eq, dict):
        eq = eq.get("value")
    if eq is None:
        eq_buckets["Unknown"] += 1
    elif eq > 0.5:
        eq_buckets["Deep equity (>50%)"] += 1
    elif eq > 0.2:
        eq_buckets["Moderate (20-50%)"] += 1
    elif eq >= 0:
        eq_buckets["Thin (0-20%)"] += 1
    else:
        eq_buckets["Underwater (<0%)"] += 1
for b, c in eq_buckets.items():
    print(f"  {b}: {c:,} ({c/n*100:.1f}%)")

# ── RED FLAG SEVERITY ──
print("\n" + "=" * 120)
print("RED FLAG SEVERITY BREAKDOWN")
print("=" * 120)
sev = Counter()
flag_types = Counter()
for d in data:
    raw = d.get("raw") or {}
    flags = raw.get("red_flags") or []
    for flag in flags:
        if isinstance(flag, dict):
            sev[flag.get("severity", "UNKNOWN")] += 1
            flag_types[flag.get("type", "unknown")] += 1
        else:
            sev["UNKNOWN"] += 1

print("\nBy Severity:")
for s, cnt in sev.most_common():
    print(f"  {s}: {cnt:,}")
print("\nBy Type:")
for t, cnt in flag_types.most_common():
    print(f"  {t}: {cnt:,}")

# ── ALL RAW KEYS ──
print("\n" + "=" * 120)
print("ALL DATA KEYS PRESENT IN BOARD")
print("=" * 120)
all_keys = set()
for d in data[:2000]:
    raw = d.get("raw") or {}
    all_keys.update(raw.keys())
    for k in d.keys():
        if k != "raw":
            all_keys.add(k)
print(f"\n{len(all_keys)} unique keys:")
for k in sorted(all_keys):
    print(f"  {k}")

# ── COMPETITIVE ANALYSIS: What competitors have ──
print("\n" + "=" * 120)
print("COMPETITIVE GAP ANALYSIS — What Goliath/PropStream/etc have vs us")
print("=" * 120)
print("""
PLATFORMS & THEIR FEATURES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
PropStream:
  ✅ Property records (we have)
  ✅ Comps (we have, limited)
  ✅ Equity estimate (we have)
  ✅ Mortgage history (PARTIAL — loan_amount only, no full chain)
  ❌ MLS integration (we don't have)
  ❌ List-driving (skip tracing tools)
  ❌ Direct mail integration

Goliath (REI):
  ✅ Pre-foreclosures (we have)
  ✅ Foreclosure auctions (we have)
  ❌ Mortgage assignments
  ❌ lis pendens filings (pre-foreclosure notices)
  ❌ Notice of default tracking

BatchLeads/Privy:
  ❌ Phone numbers / skip tracing
  ❌ Email addresses
  ❌ Owner contact info beyond name

RealtyTrac/Reonomy:
  ❌ Commercial property data
  ❌ Building permits
  ❌ Zoning data
  ❌ Environmental hazards

WHAT WE HAVE THAT OTHERS DON'T:
  ✅ FEMA repetitive loss properties
  ✅ Septic system violations
  ✅ Eviction market tier data
  ✅ Incarcerated owner detection
  ✅ Storm damage history
  ✅ NC SOS LLC dissolution status
  ✅ Upset bid window tracking
  ✅ Owner mismatch (mailing vs property)
  ✅ 27 red flag types (most platforms have 3-5)

WHAT WE'RE MISSING (high-value gaps):
  1. lis pendens / notice of default (pre-foreclosure notice)
  2. Full mortgage chain (origination date, refis, HELOCs)
  3. Building permits / code violations (only 884 Asheville)
  4. MLS / listing history (on-market data)
  5. Owner phone numbers / skip trace
  6. Zoning / land use restrictions
  7. Environmental hazards (radon, brownfields)
  8. School district ratings
  9. Walkability / crime stats
  10. Insurance claim history (CLUE report)
  11. Utility lien details (beyond boolean)
  12. HOA information / liens
  13. Tenant occupancy status
  14. Property condition / repair estimate
  15. Demographic data (neighborhood)
""")
