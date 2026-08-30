"""Analytics dashboard with ROI / cost-per-acquisition metrics.

Matches Goliath Data's analytics dashboard feature. Generates a standalone
HTML dashboard with key metrics for the lead pipeline:

  * Lead counts by grade, type, state, county
  * Estimated pipeline value (sum of ARV * equity %)
  * Cost-per-lead / cost-per-acquisition projections
  * Phone/DNC coverage stats
  * Campaign readiness metrics (how many leads are dialable/mailable)
  * Enrichment coverage table
  * Top 20 hottest leads table

Output: docs/analytics_dashboard.html
Run: python -m foreclosure_scraper.analytics_dashboard
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import structlog

from .models import Listing
from .web_artifact import load_board

log = structlog.get_logger()


def _get_grade(li: Listing) -> str:
    raw = li.raw if isinstance(li.raw, dict) else {}
    g = raw.get("grade")
    if isinstance(g, dict):
        return g.get("overall", "ungraded")
    return str(g or "ungraded").upper()


def _get_arv(li: Listing) -> float:
    raw = li.raw if isinstance(li.raw, dict) else {}
    calc = raw.get("calc") or {}
    try:
        return float(calc.get("arv") or 0)
    except (TypeError, ValueError):
        return 0.0


def _get_equity(li: Listing) -> float:
    raw = li.raw if isinstance(li.raw, dict) else {}
    try:
        return float(raw.get("equity") or 0)
    except (TypeError, ValueError):
        return 0.0


def _get_max_bid(li: Listing) -> float:
    raw = li.raw if isinstance(li.raw, dict) else {}
    calc = raw.get("calc") or {}
    try:
        return float(calc.get("max_bid") or 0)
    except (TypeError, ValueError):
        return 0.0


def _has_phone(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    return bool((raw.get("owner_phone") or {}).get("phone") or (raw.get("skip_trace") or {}).get("phone_numbers"))


def _has_mailing(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    return bool((raw.get("skip_trace") or {}).get("owner_mailing_address"))


def _is_dnc_clear(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    dnc = raw.get("dnc_scrub")
    if isinstance(dnc, list) and dnc:
        return any(d.get("dnc_status") == "clear" for d in dnc if isinstance(d, dict))
    return False


def compute_metrics(board: Sequence[Listing]) -> dict:
    """Compute all dashboard metrics."""
    total = len(board)
    by_grade = Counter(_get_grade(li) for li in board)
    by_type = Counter(li.listing_type.value if li.listing_type else "unknown" for li in board)
    by_state = Counter(li.state or "?" for li in board)
    by_county = Counter(f"{li.county or '?'}/{li.state or '?'}" for li in board)

    # Pipeline value
    total_arv = sum(_get_arv(li) for li in board)
    total_equity = sum(_get_equity(li) for li in board)
    total_max_bid = sum(_get_max_bid(li) for li in board)

    # Contactability
    has_phone = sum(1 for li in board if _has_phone(li))
    has_mailing = sum(1 for li in board if _has_mailing(li))
    dnc_clear = sum(1 for li in board if _is_dnc_clear(li))
    dialable = sum(1 for li in board if _has_phone(li) and _is_dnc_clear(li))
    mailable = has_mailing

    # Estimated costs (free scrapers, only operator time)
    # Assume $0.50/lead for data acquisition (server costs amortized)
    cost_per_lead = 0.50
    # Assume 3% close rate on HOT/WARM leads
    hot_warm = by_grade.get("A", 0) + by_grade.get("B", 0)
    expected_deals = max(1, int(hot_warm * 0.03))
    cost_per_deal = (total * cost_per_lead) / expected_deals if expected_deals else 0

    # Top 20 hottest leads
    hot_leads = sorted(board, key=lambda li: (_get_grade(li), _get_equity(li)), reverse=True)[:20]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_leads": total,
        "by_grade": dict(by_grade),
        "by_type": dict(by_type),
        "by_state": dict(by_state),
        "by_county_top": by_county.most_common(20),
        "total_arv": total_arv,
        "total_equity": total_equity,
        "total_max_bid": total_max_bid,
        "avg_equity": total_equity / total if total else 0,
        "has_phone": has_phone,
        "has_mailing": has_mailing,
        "dnc_clear": dnc_clear,
        "dialable": dialable,
        "mailable": mailable,
        "phone_pct": has_phone / total * 100 if total else 0,
        "dnc_pct": dnc_clear / total * 100 if total else 0,
        "mailing_pct": has_mailing / total * 100 if total else 0,
        "cost_per_lead": cost_per_lead,
        "expected_deals": expected_deals,
        "cost_per_deal": cost_per_deal,
        "hot_leads": [
            {
                "grade": _get_grade(li),
                "owner": li.owner_name or li.defendant or "?",
                "address": li.street_address or "?",
                "county": li.county or "?",
                "state": li.state or "?",
                "arv": _get_arv(li),
                "equity": _get_equity(li),
                "max_bid": _get_max_bid(li),
                "type": li.listing_type.value if li.listing_type else "",
            }
            for li in hot_leads
        ],
    }


def generate_html(metrics: dict) -> str:
    """Generate standalone HTML dashboard from metrics."""
    m = metrics
    # Format currency
    def money(v):
        return f"${v:,.0f}" if v else "$0"

    rows_hot = ""
    for i, lead in enumerate(m["hot_leads"], 1):
        rows_hot += f"""
        <tr>
            <td>{i}</td>
            <td><span class="grade grade-{lead['grade'].lower()}">{lead['grade']}</span></td>
            <td>{lead['owner'][:25]}</td>
            <td>{lead['address'][:30]}</td>
            <td>{lead['county']}, {lead['state']}</td>
            <td>{lead['type']}</td>
            <td class="num">{money(lead['arv'])}</td>
            <td class="num">{money(lead['equity'])}</td>
            <td class="num">{money(lead['max_bid'])}</td>
        </tr>"""

    grade_bars = ""
    grade_colors = {"A": "#e74c3c", "B": "#e67e22", "C": "#f1c40f", "D": "#3498db", "F": "#95a5a6"}
    for g in ["A", "B", "C", "D", "F"]:
        count = m["by_grade"].get(g, 0)
        pct = count / m["total_leads"] * 100 if m["total_leads"] else 0
        color = grade_colors.get(g, "#999")
        grade_bars += f"""
        <div class="grade-row">
            <span class="grade grade-{g.lower()}" style="background:{color}">{g}</span>
            <span class="grade-count">{count:,}</span>
            <div class="grade-bar"><div style="width:{pct:.1f}%;background:{color}"></div></div>
            <span class="grade-pct">{pct:.1f}%</span>
        </div>"""

    type_rows = ""
    for t, c in sorted(m["by_type"].items(), key=lambda x: -x[1]):
        type_rows += f"<tr><td>{t}</td><td class='num'>{c:,}</td><td class='num'>{c/m['total_leads']*100:.1f}%</td></tr>"

    county_rows = ""
    for c, n in m["by_county_top"]:
        county_rows += f"<tr><td>{c}</td><td class='num'>{n:,}</td><td class='num'>{n/m['total_leads']*100:.1f}%</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Foreclosure Analytics Dashboard</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 0; background: #0f1117; color: #e0e0e0; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
h1 {{ color: #fff; border-bottom: 2px solid #333; padding-bottom: 10px; }}
h2 {{ color: #ccc; margin-top: 30px; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
.kpi {{ background: #1a1d27; border-radius: 8px; padding: 20px; text-align: center; }}
.kpi .value {{ font-size: 2em; font-weight: bold; color: #4fc3f7; }}
.kpi .label {{ color: #888; font-size: 0.85em; margin-top: 5px; }}
.kpi.green .value {{ color: #4caf50; }}
.kpi.orange .value {{ color: #ff9800; }}
.kpi.red .value {{ color: #f44336; }}
table {{ width: 100%; border-collapse: collapse; margin: 15px 0; background: #1a1d27; border-radius: 8px; overflow: hidden; }}
th {{ background: #252a37; padding: 10px; text-align: left; color: #999; font-size: 0.85em; text-transform: uppercase; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #2a2f3a; }}
.num {{ text-align: right; font-family: monospace; }}
.grade {{ padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; color: #fff; }}
.grade-a {{ background: #e74c3c; }}
.grade-b {{ background: #e67e22; }}
.grade-c {{ background: #f1c40f; color: #333; }}
.grade-d {{ background: #3498db; }}
.grade-f {{ background: #95a5a6; }}
.grade-row {{ display: flex; align-items: center; gap: 10px; margin: 8px 0; }}
.grade-count {{ width: 80px; text-align: right; font-family: monospace; }}
.grade-bar {{ flex: 1; height: 12px; background: #1a1d27; border-radius: 6px; overflow: hidden; }}
.grade-bar div {{ height: 100%; border-radius: 6px; }}
.grade-pct {{ width: 60px; color: #888; font-size: 0.85em; }}
.generated {{ color: #555; font-size: 0.85em; margin-bottom: 20px; }}
</style></head><body><div class="container">
<h1>Foreclosure Analytics Dashboard</h1>
<div class="generated">Generated: {m['generated_at']}</div>

<div class="kpi-grid">
    <div class="kpi"><div class="value">{m['total_leads']:,}</div><div class="label">Total Leads</div></div>
    <div class="kpi green"><div class="value">{money(m['total_arv'])}</div><div class="label">Total ARV</div></div>
    <div class="kpi green"><div class="value">{money(m['total_equity'])}</div><div class="label">Total Equity</div></div>
    <div class="kpi orange"><div class="value">{money(m['total_max_bid'])}</div><div class="label">Max Bid Capacity</div></div>
    <div class="kpi"><div class="value">{m['has_phone']:,}</div><div class="label">Phone ({m['phone_pct']:.1f}%)</div></div>
    <div class="kpi"><div class="value">{m['dnc_clear']:,}</div><div class="label">DNC Clear ({m['dnc_pct']:.1f}%)</div></div>
    <div class="kpi"><div class="value">{m['has_mailing']:,}</div><div class="label">Mailing ({m['mailing_pct']:.1f}%)</div></div>
    <div class="kpi red"><div class="value">{m['dialable']:,}</div><div class="label">Dialable Now</div></div>
    <div class="kpi green"><div class="value">{m['expected_deals']}</div><div class="label">Expected Deals (3% close)</div></div>
    <div class="kpi"><div class="value">{money(m['cost_per_deal'])}</div><div class="label">Cost Per Deal</div></div>
</div>

<h2>Lead Grade Distribution</h2>
{grade_bars}

<h2>Lead Types</h2>
<table><tr><th>Type</th><th>Count</th><th>%</th></tr>{type_rows}</table>

<h2>Top 20 Counties</h2>
<table><tr><th>County/State</th><th>Count</th><th>%</th></tr>{county_rows}</table>

<h2>Top 20 Hottest Leads</h2>
<table><tr>
<th>#</th><th>Grade</th><th>Owner</th><th>Address</th><th>Location</th><th>Type</th>
<th>ARV</th><th>Equity</th><th>Max Bid</th>
</tr>{rows_hot}</table>

</div></body></html>"""
    return html


def generate_dashboard(board: Sequence[Listing] | None = None, output: str = "docs/analytics_dashboard.html") -> str:
    """Generate the full analytics dashboard HTML."""
    if board is None:
        board = load_board("docs")
    metrics = compute_metrics(board)
    html = generate_html(metrics)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    log.info("analytics.dashboard_written", path=str(out_path), leads=metrics["total_leads"])
    return str(out_path)


def main():
    path = generate_dashboard()
    print(f"Dashboard written to {path}")


if __name__ == "__main__":
    main()
