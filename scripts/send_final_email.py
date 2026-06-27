#!/usr/bin/env python
"""Final 'dashboards complete' email — sent once when the improvement loop wraps at 6pm.

Composes ONE HTML email summarizing both dashboards and sends it (Gmail SMTP) to the
configured recipients, with the business dashboard HTML attached (it is a local-only
repo with no public URL; the foreclosure dashboard is linked live).

Robust by design (it fires autonomously): reads the app password from .secrets, guards
against double-send with a sentinel, and supports --dry-run to preview without sending.

Usage:
  python scripts/send_final_email.py --dry-run     # preview, no send
  python scripts/send_final_email.py               # send once (skips if sentinel exists)
  python scripts/send_final_email.py --force       # send even if sentinel exists
"""
from __future__ import annotations

import json
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

FC_ROOT = Path(__file__).resolve().parent.parent
BIZ_ROOT = Path.home() / "business-scraper"
SENTINEL = FC_ROOT / "logs" / ".final_email_sent"

SENDER = "highwaymarketingco@gmail.com"
RECIPIENTS = ["greghhigh@gmail.com", "cashrandolphhigh@gmail.com"]
FC_URL = "https://highwaymarketingco-wq.github.io/foreclosure-scraper/"
BIZ_URL = "https://highwaymarketingco-wq.github.io/business-acquisition-dashboard/"


def _load_app_password() -> str | None:
    f = FC_ROOT / ".secrets" / "gmail_app_password.txt"
    return f.read_text().strip() if f.exists() else None


def _money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def _foreclosure_stats() -> dict:
    d = json.loads((FC_ROOT / "docs" / "listings.json").read_text())
    raw = lambda x: x.get("raw") or {}
    n = len(d) or 1
    tier = lambda t: sum(1 for x in d if raw(x).get("distress_stack", {}).get("tier") == t)
    pct = lambda c: f"{round(100 * c / n)}%"
    return {
        "count": len(d),
        "hot": tier("HOT"), "warm": tier("WARM"),
        "addr": pct(sum(1 for x in d if x.get("street_address"))),
        "photo": pct(sum(1 for x in d if raw(x).get("zillow", {}).get("photo"))),
        "owner": pct(sum(1 for x in d if x.get("owner_name") or x.get("defendant"))),
        "equity": sum(1 for x in d if raw(x).get("equity", {}).get("value") is not None),
        "absentee": sum(1 for x in d if raw(x).get("distress_stack", {}).get("absentee")),
    }


def _business_stats() -> dict:
    p = BIZ_ROOT / "docs" / "targets.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text())
    raw = lambda x: x.get("raw") or {}
    tier = lambda t: sum(1 for x in d if raw(x).get("acquire_score", {}).get("tier") == t)
    SVC = {"construction_trades", "landscaping_cleaning", "automotive"}
    svc = [x for x in d if raw(x).get("industry_bucket") in SVC]
    valued = [x for x in d if raw(x).get("calc", {}).get("fair_value_expected")]
    # top service-trade targets by estimated fair value
    top = sorted(
        [x for x in svc if raw(x).get("calc", {}).get("fair_value_expected")],
        key=lambda y: -(raw(y).get("calc", {}).get("fair_value_expected") or 0),
    )[:15]
    rows = []
    for x in top:
        c = raw(x)["calc"]
        rows.append({
            "name": (x.get("name") or "?")[:40],
            "where": f"{x.get('city') or ''}, {x.get('state') or ''}".strip(", "),
            "trade": raw(x).get("industry_bucket", ""),
            "rev": _money(x.get("revenue")),
            "sde": _money(c.get("sde_used")),
            "value": f"{_money(c.get('fair_value_low'))}-{_money(c.get('fair_value_high'))}",
        })
    # top-rated blue-collar leads (the GBP roster — contact + rating, the sourcing call-list)
    rated = sorted(
        [x for x in d if (x.get("google_rating") or 0) >= 4.5 and x.get("phone")
         and raw(x).get("industry_bucket") in (SVC | {"personal_services"})],
        key=lambda y: -(y.get("google_rating") or 0),
    )[:15]
    top_rated = [{
        "name": (x.get("name") or "?")[:36],
        "where": f"{x.get('city') or ''}, {x.get('state') or ''}".strip(", "),
        "trade": (x.get("industry") or raw(x).get("industry_bucket", "")),
        "rating": x.get("google_rating"),
        "phone": x.get("phone") or "",
        "dd": (raw(x).get("due_diligence") or {}).get("known"),
    } for x in rated]
    return {"count": len(d), "warm": tier("WARM"), "service": len(svc),
            "valued": len(valued), "top": rows, "top_rated": top_rated,
            "with_phone": sum(1 for x in d if x.get("phone"))}


def _html(fc: dict, biz: dict) -> str:
    biz_rows = "".join(
        f"<tr><td>{r['name']}</td><td>{r['where']}</td><td>{r['trade']}</td>"
        f"<td>{r['rev']}</td><td>{r['sde']}</td><td>{r['value']}</td></tr>"
        for r in biz.get("top", [])
    ) or "<tr><td colspan=6>no valued service-trade targets yet</td></tr>"
    biz_block = (
        f"<p><b>Business acquisition dashboard</b> &mdash; <a href=\"{BIZ_URL}\">{BIZ_URL}</a> (HTML also attached)</p>"
        f"<ul><li>{biz.get('count', 0):,} businesses tracked, {biz.get('service', 0):,} service-trade "
        f"(HVAC/plumbing/electrical/etc.)</li>"
        f"<li>{biz.get('valued', 0):,} carry estimated financials (revenue to SDE to value band); "
        f"{biz.get('warm', 0):,} WARM</li></ul>"
        f"<table border=1 cellpadding=5 cellspacing=0 style='border-collapse:collapse;font-size:13px'>"
        f"<tr style='background:#f0f0f0'><th>Business</th><th>Location</th><th>Trade</th>"
        f"<th>Est. revenue</th><th>Est. SDE</th><th>Est. value</th></tr>{biz_rows}</table>"
        f"<p style='color:#888;font-size:12px'>Financials are estimates from free proxies "
        f"(employees / SBA-loan size), labeled by confidence, not disclosed figures.</p>"
        if biz else "<p><i>Business dashboard not available.</i></p>"
    )
    rated_rows = "".join(
        f"<tr><td>{r['name']}</td><td>{r['where']}</td><td>{r['trade']}</td>"
        f"<td>{r['rating']}&#9733;</td><td>{r['phone']}</td><td>{r['dd']}/8</td></tr>"
        for r in (biz.get("top_rated") or [])
    )
    if rated_rows:
        biz_block += (
            f"<p style='margin-top:14px'><b>Top-rated blue-collar leads</b> "
            f"({biz.get('with_phone', 0):,} reachable shops across 60 trades — HVAC, plumbing, "
            f"electrical, roofing, auto, landscaping, restoration, junk/hauling, etc.):</p>"
            f"<table border=1 cellpadding=5 cellspacing=0 style='border-collapse:collapse;font-size:13px'>"
            f"<tr style='background:#f0f0f0'><th>Business</th><th>Location</th><th>Trade</th>"
            f"<th>Rating</th><th>Phone</th><th>Due-dil</th></tr>{rated_rows}</table>"
        )
    return f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#222">
<h2>Dashboards complete</h2>
<p>Both dashboards finished their build. Summary below.</p>
<p><b>Foreclosure / distressed dashboard</b> &mdash; <a href="{FC_URL}">{FC_URL}</a></p>
<ul>
  <li>{fc['count']:,} active leads &middot; {fc['hot']} HOT &middot; {fc['warm']:,} WARM</li>
  <li>Coverage &mdash; address {fc['addr']}, photo {fc['photo']}, owner {fc['owner']}</li>
  <li>{fc['equity']:,} with computed equity &middot; {fc['absentee']:,} absentee owners</li>
</ul>
{biz_block}
<p style="color:#888;font-size:12px">Sent automatically by the build loop on completion.</p>
</body></html>"""


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    force = "--force" in argv
    if SENTINEL.exists() and not force and not dry:
        print(f"already sent (sentinel {SENTINEL} exists); use --force to resend")
        return 0
    fc = _foreclosure_stats()
    biz = _business_stats()
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Dashboards complete — Foreclosure ({fc['count']:,} leads) + Business ({biz.get('count', 0):,})"
    msg["From"] = SENDER
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(_html(fc, biz), "html"))
    biz_html = BIZ_ROOT / "docs" / "index.html"
    if biz_html.exists():
        part = MIMEApplication(biz_html.read_bytes(), _subtype="html")
        part.add_header("Content-Disposition", "attachment", filename="business_dashboard.html")
        msg.attach(part)

    if dry:
        print("=== DRY RUN (no send) ===")
        print("To:", RECIPIENTS)
        print("Subject:", msg["Subject"])
        print("Attachments:", [p.get_filename() for p in msg.get_payload() if p.get_filename()])
        print("Foreclosure stats:", fc)
        print("Business stats:", {k: v for k, v in biz.items() if k != "top"})
        print("Top business targets:", len(biz.get("top", [])))
        return 0

    pw = _load_app_password()
    if not pw:
        print("FATAL: no gmail app password (.secrets/gmail_app_password.txt)")
        return 1
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(SENDER, pw)
        smtp.sendmail(SENDER, RECIPIENTS, msg.as_string())
    SENTINEL.write_text("sent")
    print(f"sent to {RECIPIENTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
