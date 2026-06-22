"""Email digest sender. Gmail SMTP with app password."""
from __future__ import annotations

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable

import structlog

log = structlog.get_logger()


DASHBOARD_URL = "https://highwaymarketingco-wq.github.io/foreclosure-scraper/"


def _new_banner(run_summary: dict) -> str:
    """Early-access highlight: how many NEW distressed properties appeared
    since the last run, and how many are fresh pre-foreclosures (lis
    pendens — the earliest signal, before they hit the general listings)."""
    new = run_summary.get("new_this_week", 0)
    if not new:
        return ""
    new_lp = run_summary.get("new_lis_pendens", 0)
    lp_line = (
        f' — including <strong>{new_lp}</strong> brand-new pre-foreclosure'
        f' filing{"s" if new_lp != 1 else ""} (earliest signal)'
        if new_lp else ""
    )
    return (
        f'<div style="background:#eaf5ec;border:1px solid #b9dcc0;color:#1a4d2e;'
        f'padding:14px 18px;border-radius:6px;margin:0 0 18px 0;font-weight:600">'
        f'🆕 <strong>{new}</strong> new distressed propert'
        f'{"ies" if new != 1 else "y"} in your area this run{lp_line}.'
        f'</div>'
    )


def _source_alarm_banner(run_summary: dict) -> str:
    """Loud, top-of-email banner listing any source in SILENT-FAILURE alarm
    (broken or bleeding across runs) so a dead scraper is impossible to miss."""
    alarms = run_summary.get("source_alarms") or {}
    if not alarms:
        return ""
    items = "".join(
        f'<li style="margin:4px 0"><strong>{slug}</strong>: {a.get("reason", "alarm")}</li>'
        for slug, a in sorted(alarms.items())
    )
    return (
        f'<div style="background:#fde8e8;border:2px solid #e53935;color:#8a1414;'
        f'padding:16px 18px;border-radius:6px;margin:0 0 18px 0;">'
        f'<div style="font-weight:700;font-size:15px;margin-bottom:6px">'
        f'🔴 SOURCE HEALTH — {len(alarms)} source(s) need attention</div>'
        f'<ul style="margin:6px 0 0 18px;padding:0;font-weight:600">{items}</ul>'
        f'<div style="font-weight:400;font-size:12px;margin-top:8px">'
        f'These scrapers broke or are bleeding vs their normal output. Fix before '
        f'trusting this run for those areas.</div>'
        f'</div>'
    )


def _summary_html(sheet_url: str, run_summary: dict) -> str:
    by_source = run_summary.get("by_source", {})
    by_state = run_summary.get("by_state", {})
    by_county_top = run_summary.get("by_county_top", [])
    total = run_summary.get("total", 0)
    new_count = run_summary.get("new_this_week", 0)

    rows_source = "".join(
        f"<tr><td style='padding:4px 12px;border-bottom:1px solid #eee'>{k}</td>"
        f"<td style='padding:4px 12px;border-bottom:1px solid #eee;text-align:right'>{v}</td></tr>"
        for k, v in sorted(by_source.items(), key=lambda kv: -kv[1])
    )
    rows_state = "".join(
        f"<tr><td style='padding:4px 12px;border-bottom:1px solid #eee'>{k}</td>"
        f"<td style='padding:4px 12px;border-bottom:1px solid #eee;text-align:right'>{v}</td></tr>"
        for k, v in sorted(by_state.items(), key=lambda kv: -kv[1])
    )
    rows_county = "".join(
        f"<tr><td style='padding:4px 12px;border-bottom:1px solid #eee'>{c}</td>"
        f"<td style='padding:4px 12px;border-bottom:1px solid #eee;text-align:right'>{n}</td></tr>"
        for c, n in by_county_top
    )

    sheet_link = f'<a href="{sheet_url}" style="color:#1a4d2e;text-decoration:none">Open in Google Sheet →</a>' if sheet_url else ""

    # Loud banner when this run shipped far fewer listings than the last —
    # the silent-drop failure mode is now impossible to miss in the email.
    alert = run_summary.get("count_drop_alert")
    alert_banner = ""
    if alert:
        alert_banner = (
            f'<div style="background:#fdecea;border:1px solid #f5c6cb;color:#a12;'
            f'padding:14px 18px;border-radius:6px;margin:0 0 18px 0;font-weight:600">'
            f'⚠️ Listing count dropped {alert.get("drop_pct")}% '
            f'({alert.get("prev_total")} → {alert.get("curr_total")}) vs the last run. '
            f'A source may be broken — check the run log before trusting this data.'
            f'</div>'
        )
    return f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif; color:#222; max-width:680px;margin:0 auto;padding:20px;">
<h2 style="color:#1a4d2e">Foreclosure Listings — {datetime.utcnow().strftime('%B %Y')}</h2>
{_source_alarm_banner(run_summary)}
{alert_banner}
{_new_banner(run_summary)}
<p>Run completed {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}.</p>
<p style="font-size:18px"><strong>{total}</strong> active listings across upstate SC + western NC.</p>
<p>
  <a href="{DASHBOARD_URL}" style="background:#1a4d2e;color:#fff;padding:14px 22px;text-decoration:none;border-radius:6px;display:inline-block;font-weight:600;font-size:15px">
    🏠 Open the live dashboard
  </a>
</p>
<p style="color:#888;font-size:12px;margin-top:8px">
  Filterable, mappable, with photos. Bookmark the link — it updates each month.
  {sheet_link}
</p>
<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<h3 style="color:#1a4d2e">By State</h3>
<table style="border-collapse:collapse;border:1px solid #ddd">{rows_state}</table>

<h3 style="color:#1a4d2e">Top Counties</h3>
<table style="border-collapse:collapse;border:1px solid #ddd">{rows_county}</table>

<h3 style="color:#1a4d2e">By Source</h3>
<table style="border-collapse:collapse;border:1px solid #ddd">{rows_source}</table>

<p style="color:#888;font-size:12px;margin-top:24px">
Auto-generated. Every link in the dashboard was reachability-checked at run time. Data is public record.
</p>
</body>
</html>
"""

def send_digest(
    *,
    sender: str,
    app_password: str,
    recipients: Iterable[str],
    sheet_url: str,
    run_summary: dict,
) -> None:
    recipients = [r for r in recipients if r]
    if not recipients:
        log.warning("email.no_recipients")
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    n_alarms = len(run_summary.get("source_alarms") or {})
    alarm_prefix = f"🔴 {n_alarms} SOURCE ALARM{'S' if n_alarms != 1 else ''} — " if n_alarms else ""
    msg["Subject"] = (
        f"{alarm_prefix}Foreclosure Listings — {datetime.utcnow().strftime('%b %d, %Y')} "
        f"({run_summary.get('total', 0)} active)"
    )
    msg.attach(MIMEText(_summary_html(sheet_url, run_summary), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, app_password)
        smtp.sendmail(sender, recipients, msg.as_string())

    log.info("email.sent", recipients=recipients)
