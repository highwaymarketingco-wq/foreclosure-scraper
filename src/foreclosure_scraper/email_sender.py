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
    return f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif; color:#222; max-width:680px;margin:0 auto;padding:20px;">
<h2 style="color:#1a4d2e">Foreclosure Listings — {datetime.utcnow().strftime('%B %Y')}</h2>
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
    msg["Subject"] = (
        f"Foreclosure Listings — {datetime.utcnow().strftime('%b %d, %Y')} "
        f"({run_summary.get('total', 0)} active)"
    )
    msg.attach(MIMEText(_summary_html(sheet_url, run_summary), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, app_password)
        smtp.sendmail(sender, recipients, msg.as_string())

    log.info("email.sent", recipients=recipients)
