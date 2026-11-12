#!/usr/bin/env python3
"""Aggregate all title/risk signals into a unified `red_flags` array on each listing.

This doesn't make API calls — it reads existing enriched data from the board
and surfaces a composite red_flags array with severity levels:
  - CRITICAL: IRS liens, bankruptcy stay, probate, condemned, severe tax delinquency
  - HIGH: code enforcement, FEMA repetitive loss, incarceration, DEW/utility liens,
          senior lien foreclosure, bankruptcy (chapter 7/11/13)
  - MEDIUM: old mortgage, eviction market (high tier), vacant land, SOS dissolution,
            divorce, owner_mismatch, out_of_state owner, high LTV
  - LOW: storm damage, septic issues, junior lien foreclosure, mobile/manufactured

Each flag has: type, severity, description, source field.
"""
import gc, json, os, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("PATH", os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", ""))

from foreclosure_scraper.web_artifact import load_board, _to_dict, write_artifact

DOCS = REPO / "docs"


def build_red_flags(li, li_dict):
    """Aggregate all risk signals into a unified red_flags array.

    li: listing object (for attribute access)
    li_dict: listing as dict (for top-level + raw dict access)
    """
    raw = li_dict.get("raw", {}) if isinstance(li_dict, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    flags = []

    def add(severity, ftype, desc, source):
        flags.append({"severity": severity, "type": ftype, "description": desc, "source": source})

    # ──────────────────────────────────────────────────────────────────
    # CRITICAL
    # ──────────────────────────────────────────────────────────────────

    # Condemned property
    if raw.get("condemned"):
        add("CRITICAL", "condemned", "Property condemned by code enforcement", "condemned")

    # Bankruptcy stay (automatic stay active)
    bs = raw.get("bankruptcy_stay")
    if bs and isinstance(bs, dict) and bs.get("status") == "stayed":
        ch = bs.get("chapter", "?")
        risk = bs.get("resume_risk", "unknown")
        add("CRITICAL", "bankruptcy_stay",
            f"Bankruptcy stay active (Ch {ch}), resume risk: {risk}",
            "bankruptcy_stay")

    # Bankruptcy (from title search step)
    bk = raw.get("bankruptcy")
    if bk and isinstance(bk, dict) and bk.get("chapter"):
        add("CRITICAL", "bankruptcy",
            f"Bankruptcy: Chapter {bk['chapter']}",
            "bankruptcy")

    # Probate / estate — from relationship_signal
    rs = raw.get("relationship_signal")
    if rs and isinstance(rs, dict) and rs.get("kind") == "probate":
        add("CRITICAL", "probate",
            f"Estate/probate: {rs.get('keyword', 'notice to creditors')}",
            "relationship_signal")

    # Life events list containing estate_probate
    le = raw.get("life_events")
    if isinstance(le, list) and any("estate" in str(x).lower() or "probate" in str(x).lower() for x in le):
        add("CRITICAL", "probate_life_event",
            "Estate/probate detected in life events",
            "life_events")

    # Severe tax delinquency — from tax_owed balance > $10k
    tw = raw.get("tax_owed")
    if tw and isinstance(tw, dict) and tw.get("balance"):
        bal = tw["balance"]
        if isinstance(bal, (int, float)) and bal > 10000:
            add("CRITICAL", "severe_tax_delinquency",
                f"Tax delinquency: ${bal:,.0f} owed",
                "tax_owed")

    # NC delinquent tax with high principal
    nc_tax = raw.get("nc_ptscloud_delinquent_tax")
    if nc_tax and isinstance(nc_tax, dict):
        principal = nc_tax.get("principal_tax_due", 0)
        if isinstance(principal, (int, float)) and principal > 5000:
            add("CRITICAL", "nc_tax_delinquent",
                f"NC tax delinquent: ${principal:,.0f} principal",
                "nc_ptscloud_delinquent_tax")

    # ──────────────────────────────────────────────────────────────────
    # HIGH
    # ──────────────────────────────────────────────────────────────────

    # Code enforcement violation
    if raw.get("code_enforcement"):
        add("HIGH", "code_violation", "Code enforcement action on property", "code_enforcement")

    # FEMA repetitive loss
    frpl = raw.get("fema_repetitive_loss")
    if frpl and isinstance(frpl, dict) and frpl.get("nfip_repetitive_loss"):
        flood_zone = frpl.get("flood_zone", "?")
        add("HIGH", "fema_repetitive_loss",
            f"FEMA repetitive-loss property (flood zone {flood_zone})",
            "fema_repetitive_loss")

    # Incarceration
    inc = raw.get("incarceration")
    if inc and isinstance(inc, dict) and inc.get("results"):
        add("HIGH", "incarcerated_owner",
            f"Owner may be incarcerated: {inc.get('matched_name', '?')} ({inc.get('state', '?')})",
            "incarceration")

    # DEW/utility liens
    liens = raw.get("liens")
    if isinstance(liens, list) and liens:
        for lien in liens:
            if isinstance(lien, dict):
                ltype = lien.get("type", "unknown")
                amount = lien.get("amount", 0)
                holder = lien.get("holder", "")
                super_p = lien.get("super_priority", False)
                sev = "HIGH" if super_p else "MEDIUM"
                add(sev, "utility_lien",
                    f"{ltype}: ${amount:,.0f} ({holder})" + (" — super priority" if super_p else ""),
                    "liens")

    # Title risk — senior lien foreclosure (surviving debt risk)
    tr = raw.get("title_risk")
    if tr and isinstance(tr, dict):
        kind = tr.get("kind", "")
        if kind == "senior_lien_foreclosure" or tr.get("surviving_senior_debt_risk"):
            add("HIGH", "senior_lien_foreclosure",
                f"Senior lien foreclosure: surviving debt risk ({tr.get('matched', '?')})",
                "title_risk")

    # IRS liens (from courtlistener)
    cl = raw.get("courtlistener")
    if cl and isinstance(cl, dict) and cl.get("irs_lien"):
        add("HIGH", "irs_lien",
            f"IRS tax lien found via CourtListener",
            "courtlistener")

    # ──────────────────────────────────────────────────────────────────
    # MEDIUM
    # ──────────────────────────────────────────────────────────────────

    # Junior lien foreclosure
    if tr and isinstance(tr, dict) and tr.get("kind") == "junior_lien_foreclosure":
        add("MEDIUM", "junior_lien_foreclosure",
            f"Junior lien foreclosure: {tr.get('matched', '?')}",
            "title_risk")

    # Eviction market — high tier
    ev = raw.get("eviction_market")
    if ev and isinstance(ev, dict):
        tier = ev.get("tier", "")
        rate = ev.get("rate", 0)
        if tier == "high":
            add("MEDIUM", "eviction_market_high",
                f"High eviction market: {rate}% rate/100 renter HH",
                "eviction_market")

    # Vacant lot
    vl = raw.get("vacant_lot")
    if vl and isinstance(vl, dict) and vl.get("land_use"):
        add("MEDIUM", "vacant_land",
            f"Vacant/undeveloped land: {vl.get('land_use', '?')}",
            "vacant_lot")

    # Divorce proceedings
    dv = raw.get("divorce")
    if dv and isinstance(dv, dict) and dv.get("case_count", 0) > 0:
        add("MEDIUM", "divorce",
            f"Divorce proceedings: {dv.get('case_count', 0)} case(s)",
            "divorce")

    # Owner mismatch (defendant name ≠ property owner)
    om = raw.get("owner_mismatch")
    if om and isinstance(om, dict) and om.get("snapped_owner"):
        add("MEDIUM", "owner_mismatch",
            f"Owner mismatch: defendant vs {om.get('snapped_owner', 'record owner')}",
            "owner_mismatch")

    # High LTV (from derived_signals)
    ds = raw.get("derived_signals")
    if ds and isinstance(ds, dict):
        ltv_info = ds.get("lien_to_value", {})
        if isinstance(ltv_info, dict):
            ltv = ltv_info.get("ltv", 1.0)
            band = ltv_info.get("band", "")
            if isinstance(ltv, (int, float)):
                if ltv >= 0.85:
                    add("MEDIUM", "high_ltv",
                        f"High LTV: {ltv*100:.0f}% ({band}) — limited equity margin",
                        "derived_signals")

    # Out-of-state / absentee owner
    oms = raw.get("owner_mailing")
    if oms and isinstance(oms, dict):
        if oms.get("out_of_state"):
            add("MEDIUM", "out_of_state_owner",
                f"Out-of-state owner: {oms.get('mail_state', '?')}",
                "owner_mailing")
        elif oms.get("absentee"):
            add("LOW", "absentee_owner",
                "Absentee owner (mailing differs from property)",
                "owner_mailing")

    # Skip trace absentee
    st = raw.get("skip_trace")
    if st and isinstance(st, dict):
        if st.get("out_of_state_owner"):
            add("MEDIUM", "out_of_state_owner",
                f"Out-of-state owner: {st.get('mail_state', '?')}",
                "skip_trace")
        elif st.get("absentee_owner") and not any(f["type"] == "absentee_owner" for f in flags):
            add("LOW", "absentee_owner",
                "Absentee owner",
                "skip_trace")

    # Old mortgage (loan amount recorded, last sale 15+ years ago)
    loan = raw.get("loan_amount")
    dc = raw.get("deed_chain")
    if isinstance(loan, (int, float)) and loan > 0:
        # Check deed chain for old last sale
        if dc and isinstance(dc, dict):
            transfers = dc.get("transfers", [])
            if isinstance(transfers, list) and transfers:
                last_transfer = transfers[-1] if isinstance(transfers[-1], dict) else {}
                sale_date = last_transfer.get("date", "")
                if isinstance(sale_date, str) and len(sale_date) >= 4:
                    try:
                        sale_year = int(sale_date[:4])
                        if 1900 < sale_year < 2011:
                            add("MEDIUM", "old_mortgage",
                                f"Last sale {sale_year}, loan ${loan:,.0f} — likely paid down",
                                "loan_amount")
                    except ValueError:
                        pass

    # ROD docs — deed of trust recorded
    rod = raw.get("rod_docs")
    if isinstance(rod, list) and rod:
        for doc in rod:
            if isinstance(doc, dict) and "DEED OF TRUST" in (doc.get("doc_type", "") or "").upper():
                add("MEDIUM", "deed_of_trust",
                    f"Deed of trust recorded: {doc.get('book', '?')}/{doc.get('page', '?')}",
                    "rod_docs")
                break

    # ──────────────────────────────────────────────────────────────────
    # LOW
    # ──────────────────────────────────────────────────────────────────

    # Storm damage (Hurricane Helene)
    sd = raw.get("storm_damage")
    if sd and isinstance(sd, dict) and sd.get("damage_level"):
        add("LOW", "storm_damage",
            f"Storm damage: {sd.get('damage_level', '?')}",
            "storm_damage")

    # Septic system issues
    sp = raw.get("septic")
    if sp and isinstance(sp, dict):
        status_class = sp.get("latest_status_class", "")
        days = sp.get("days_since_last_action", 0)
        if status_class and "favourable" not in status_class.lower():
            add("LOW", "septic_issue",
                f"Septic status: {sp.get('latest_status', '?')} ({status_class})",
                "septic")
        elif isinstance(days, (int, float)) and days > 5000:
            add("LOW", "septic_old",
                f"Septic system {days:.0f} days since last action (~{days/365:.0f} years)",
                "septic")

    # Upset bid window active
    ub = raw.get("upset_bid")
    if ub and isinstance(ub, dict) and ub.get("in_window"):
        days_left = ub.get("days_remaining", 0)
        add("LOW", "upset_bid_window",
            f"Upset bid window: {days_left} days remaining (deadline {ub.get('deadline_iso', '?')[:10]})",
            "upset_bid")

    # Title risk — unknown classification
    if tr and isinstance(tr, dict) and tr.get("kind") == "unknown":
        add("LOW", "title_risk_unknown",
            "Title risk classified as unknown — needs manual review",
            "title_risk")

    # Sort by severity
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    flags.sort(key=lambda x: severity_order.get(x["severity"], 9))
    return flags


def main():
    print("Loading board...", flush=True)
    board = load_board(DOCS)
    print(f"Board: {len(board)} listings", flush=True)

    t0 = time.time()
    stats = {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "listings_with_flags": 0}
    flag_type_counts = {}

    for i, li in enumerate(board):
        # Get dict representation for field access
        li_dict = _to_dict(li)
        flags = build_red_flags(li, li_dict)
        if flags:
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["red_flags"] = flags
            stats["listings_with_flags"] += 1
            for f in flags:
                stats["total"] += 1
                stats[f["severity"].lower()] += 1
                ft = f["type"]
                flag_type_counts[ft] = flag_type_counts.get(ft, 0) + 1
        else:
            if isinstance(li.raw, dict):
                li.raw.pop("red_flags", None)

        if (i + 1) % 10000 == 0:
            print(f"  ...{i+1}/{len(board)} ({stats['listings_with_flags']} flagged)", flush=True)
            gc.collect()

    print(f"\n✅ Red flag aggregation complete ({time.time()-t0:.1f}s)")
    print(f"  Total flags: {stats['total']:,}")
    print(f"  Listings with flags: {stats['listings_with_flags']:,} ({stats['listings_with_flags']/len(board)*100:.1f}%)")
    print(f"  CRITICAL: {stats['critical']:,}")
    print(f"  HIGH: {stats['high']:,}")
    print(f"  MEDIUM: {stats['medium']:,}")
    print(f"  LOW: {stats['low']:,}")
    print(f"\n  Flag type breakdown:")
    for ft, cnt in sorted(flag_type_counts.items(), key=lambda x: -x[1]):
        print(f"    {ft}: {cnt:,}")

    print("\n  Saving board with write_artifact()...", flush=True)
    write_artifact(board, {})
    print("  Done!")


if __name__ == "__main__":
    main()
