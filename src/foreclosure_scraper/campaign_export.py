"""Bulk campaign export: generate SMS, email, and direct-mail campaign CSVs.

Produces message-personalized, channel-specific campaign files from enriched
foreclosure listings. Each CSV is mail-merge ready. This goes beyond
export_leads.py (which exports raw data tables) by embedding personalized
outreach text from outreach.py into per-channel campaign files.

Channels:
  * SMS   — one row per phone number, with personalized text message
  * Email — one row per contactable lead, with subject + body
  * Mail  — one row per mailing address, with personalized letter text

All generation is local + free.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Sequence

import structlog

from .models import Listing
from .outreach import letter_text, email_text, sms_text, _first_name, _owner, _money

log = structlog.get_logger()


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _apply_filters(
    listings: Sequence[Listing], filters: dict | None
) -> list[Listing]:
    """Filter listings by grade, state, county, listing_type, has_phone,
    has_mailing_address, min_equity."""
    if not filters:
        return list(listings)

    out = []
    for li in listings:
        raw = li.raw or {}

        # Grade filter (list of acceptable grades)
        grades = filters.get("grade")
        if grades:
            grade = (raw.get("grade") or raw.get("calc", {}).get("grade", {})).get("overall", "").upper() if isinstance(raw.get("grade") or raw.get("calc", {}).get("grade", {}), dict) else str(raw.get("grade", "")).upper()
            if grade not in [g.upper() for g in grades]:
                continue

        # State filter
        state = filters.get("state")
        if state and (li.state or "").upper() != state.upper():
            continue

        # County filter
        county = filters.get("county")
        if county and (li.county or "").lower() != county.lower():
            continue

        # Listing type filter
        ltype = filters.get("listing_type")
        if ltype and (li.listing_type.value if li.listing_type else "") != ltype:
            continue

        # Has phone filter
        if filters.get("has_phone"):
            phones = (raw.get("skip_trace") or {}).get("phone_numbers") or (raw.get("owner_phone") or {}).get("phone")
            if not phones:
                continue

        # Has mailing address filter
        if filters.get("has_mailing_address"):
            mailing = (raw.get("skip_trace") or {}).get("owner_mailing_address")
            if not mailing:
                continue

        # Min equity filter
        min_equity = filters.get("min_equity")
        if min_equity is not None:
            equity = raw.get("equity") or raw.get("calc", {}).get("equity")
            if equity is None:
                continue
            try:
                if float(equity) < float(min_equity):
                    continue
            except (TypeError, ValueError):
                continue

        out.append(li)
    return out


def _export_sms(
    listings: Sequence[Listing], output_path: Path
) -> tuple[Path, int]:
    """Write SMS campaign CSV — one row per phone number."""
    rows = []
    for li in listings:
        raw = li.raw or {}
        st = raw.get("skip_trace") or {}
        phones = st.get("phone_numbers") or []
        # Also check voter_phone enricher
        vp = raw.get("owner_phone") or {}
        if vp.get("phone") and vp["phone"] not in phones:
            phones = phones + [vp["phone"]]

        if not phones:
            continue

        owner = st.get("owner_name") or li.defendant or li.owner_name or ""
        for phone in phones:
            rows.append({
                "phone": phone,
                "first_name": _first_name(owner),
                "message": sms_text(li),
                "listing_type": li.listing_type.value if li.listing_type else "",
                "address": li.street_address or "",
                "city": li.city or "",
                "state": li.state or "",
                "county": li.county or "",
                "grade": _get_grade(li),
                "dedupe_key": li.dedupe_key(),
            })

    _write_csv(output_path, rows)
    log.info("campaign_export.sms_done", path=str(output_path), rows=len(rows))
    return output_path, len(rows)


def _export_email(
    listings: Sequence[Listing], output_path: Path
) -> tuple[Path, int]:
    """Write email campaign CSV — one row per contactable lead."""
    rows = []
    for li in listings:
        raw = li.raw or {}
        st = raw.get("skip_trace") or {}
        owner = st.get("owner_name") or li.defendant or li.owner_name or ""
        if not owner:
            continue

        email = st.get("owner_email") or ""
        email_body = email_text(li)
        # Split subject from body (email_text starts with "Subject: ...")
        subject = ""
        body = email_body
        if email_body.startswith("Subject:"):
            parts = email_body.split("\n", 1)
            subject = parts[0].replace("Subject:", "").strip()
            body = parts[1].strip() if len(parts) > 1 else ""

        rows.append({
            "email": email,
            "first_name": _first_name(owner),
            "subject": subject,
            "body": body,
            "listing_type": li.listing_type.value if li.listing_type else "",
            "address": li.street_address or "",
            "city": li.city or "",
            "state": li.state or "",
            "county": li.county or "",
            "grade": _get_grade(li),
            "dedupe_key": li.dedupe_key(),
        })

    _write_csv(output_path, rows)
    log.info("campaign_export.email_done", path=str(output_path), rows=len(rows))
    return output_path, len(rows)


def _export_mail(
    listings: Sequence[Listing], output_path: Path
) -> tuple[Path, int]:
    """Write direct-mail campaign CSV — one row per mailing address."""
    rows = []
    for li in listings:
        raw = li.raw or {}
        st = raw.get("skip_trace") or {}
        owner = st.get("owner_name") or li.defendant or li.owner_name or ""
        mailing = st.get("owner_mailing_address") or ""
        if not owner or not mailing:
            continue

        calc = raw.get("calc") or {}
        rows.append({
            "owner_name": owner,
            "mailing_address": mailing,
            "property_address": li.street_address or "",
            "city": li.city or "",
            "state": li.state or "",
            "county": li.county or "",
            "letter_text": letter_text(li),
            "listing_type": li.listing_type.value if li.listing_type else "",
            "grade": _get_grade(li),
            "est_arv": _money(calc.get("arv")),
            "max_bid": _money(calc.get("max_bid")),
            "dedupe_key": li.dedupe_key(),
        })

    _write_csv(output_path, rows)
    log.info("campaign_export.mail_done", path=str(output_path), rows=len(rows))
    return output_path, len(rows)


def _get_grade(li: Listing) -> str:
    """Extract grade string from listing raw data."""
    raw = li.raw or {}
    grade = raw.get("grade")
    if isinstance(grade, dict):
        return grade.get("overall", "")
    calc = raw.get("calc", {})
    if isinstance(calc.get("grade"), dict):
        return calc["grade"].get("overall", "")
    return str(grade or "")


def _write_csv(path: Path, rows: list[dict]) -> None:
    """Write rows to CSV, creating parent dir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        # Write empty CSV with no headers
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def export_campaigns(
    listings: Sequence[Listing],
    output_dir: str | Path = "docs/campaigns",
    formats: list[str] | None = None,
    filters: dict | None = None,
) -> dict:
    """Generate campaign CSV files for SMS, email, and direct mail.

    Args:
        listings: Sequence of Listing objects.
        output_dir: Directory to write campaign files into.
        formats: List of formats: 'sms', 'email', 'mail'.
                  Defaults to all three.
        filters: Dict of filter criteria: grade (list), state, county,
                  listing_type, has_phone, has_mailing_address, min_equity.

    Returns:
        Dict with 'files' (format->path), 'stats' (counts), and 'filters_applied'.
    """
    if formats is None:
        formats = ["sms", "email", "mail"]

    out_dir = Path(output_dir)
    ts = _timestamp()
    total = len(listings)

    # Apply filters
    filtered = _apply_filters(listings, filters)
    log.info(
        "campaign_export.start",
        total=total,
        filtered=len(filtered),
        formats=formats,
        filters=filters,
    )

    results: dict[str, str] = {}
    stats: dict[str, int] = {
        "total_leads": total,
        "filtered_leads": len(filtered),
    }

    for fmt in formats:
        path = out_dir / f"{fmt}_campaign_{ts}.csv"
        try:
            if fmt == "sms":
                p, n = _export_sms(filtered, path)
                results["sms"] = str(p)
                stats["sms_rows"] = n
            elif fmt == "email":
                p, n = _export_email(filtered, path)
                results["email"] = str(p)
                stats["email_rows"] = n
            elif fmt == "mail":
                p, n = _export_mail(filtered, path)
                results["mail"] = str(p)
                stats["mail_rows"] = n
            else:
                log.warning("campaign_export.unknown_format", fmt=fmt)
        except Exception as exc:
            log.error("campaign_export.format_failed", fmt=fmt, error=str(exc)[:200])
            stats[f"{fmt}_error"] = str(exc)[:200]

    log.info("campaign_export.done", formats=list(results.keys()), stats=stats)
    return {
        "files": results,
        "stats": stats,
        "filters_applied": filters or {},
    }
