"""Workflow automation engine — if-this-then-that triggers for lead pipelines.

Matches Goliath Data's workflow automation feature. Rules are JSON-defined:
when a lead meets trigger conditions, actions fire (tag, reassign, queue
campaign, set status, send webhook). Rules persist in docs/workflows.json.

Example rule:
{
    "name": "hot_lead_sms_queue",
    "trigger": {"grade": "A", "has_phone": true},
    "actions": [
        {"type": "tag", "value": "priority_sms"},
        {"type": "set_status", "value": "contact_pending"},
        {"type": "queue_campaign", "value": "sms"}
    ]
}

Run standalone:
    python -m foreclosure_scraper.workflow_engine
    # Or programmatically: evaluate_workflows(listings, rules)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from .models import Listing

log = structlog.get_logger()

RULES_PATH = Path("docs/workflows.json")


def _load_rules(path: Path | str = RULES_PATH) -> list[dict]:
    """Load workflow rules from JSON file."""
    p = Path(path)
    if not p.exists():
        # Create default rules file
        default = [
            {
                "name": "hot_lead_priority",
                "enabled": True,
                "trigger": {"grade": ["A"], "has_phone": True},
                "actions": [
                    {"type": "tag", "value": "priority_sms"},
                    {"type": "set_status", "value": "contact_pending"},
                ],
            },
            {
                "name": "warm_lead_mail",
                "enabled": True,
                "trigger": {"grade": ["B"], "has_mailing_address": True},
                "actions": [
                    {"type": "tag", "value": "direct_mail"},
                    {"type": "queue_campaign", "value": "mail"},
                ],
            },
            {
                "name": "tax_lien_equity",
                "enabled": True,
                "trigger": {"listing_type": ["tax_lien"], "min_equity": 50000},
                "actions": [
                    {"type": "tag", "value": "high_equity"},
                    {"type": "set_status", "value": "researching"},
                ],
            },
        ]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(default, indent=2), encoding="utf-8")
        log.info("workflow.created_default", path=str(p))
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("workflow.load_failed", error=str(exc)[:200])
        return []


def _check_trigger(li: Listing, trigger: dict) -> bool:
    """Check if a listing matches a trigger condition."""
    raw = li.raw if isinstance(li.raw, dict) else {}

    # Grade trigger
    if "grade" in trigger:
        grades = trigger["grade"] if isinstance(trigger["grade"], list) else [trigger["grade"]]
        g = raw.get("grade")
        if isinstance(g, dict):
            g = g.get("overall", "")
        if str(g or "").upper() not in [x.upper() for x in grades]:
            return False

    # Listing type trigger
    if "listing_type" in trigger:
        types = trigger["listing_type"] if isinstance(trigger["listing_type"], list) else [trigger["listing_type"]]
        lt = li.listing_type.value if li.listing_type else ""
        if lt not in types:
            return False

    # State trigger
    if "state" in trigger:
        if (li.state or "").upper() != trigger["state"].upper():
            return False

    # County trigger
    if "county" in trigger:
        if (li.county or "").lower() != trigger["county"].lower():
            return False

    # Has phone
    if trigger.get("has_phone"):
        has = (raw.get("owner_phone") or {}).get("phone") or (raw.get("skip_trace") or {}).get("phone_numbers")
        if not has:
            return False

    # Has mailing address
    if trigger.get("has_mailing_address"):
        mailing = (raw.get("skip_trace") or {}).get("owner_mailing_address")
        if not mailing:
            return False

    # Min equity
    if "min_equity" in trigger:
        equity = raw.get("equity")
        if equity is None:
            return False
        try:
            if float(equity) < float(trigger["min_equity"]):
                return False
        except (ValueError, TypeError):
            return False

    # Min market value
    if "min_value" in trigger:
        try:
            if float(li.market_value or 0) < float(trigger["min_value"]):
                return False
        except (ValueError, TypeError):
            return False

    # Has sale date
    if trigger.get("has_sale_date"):
        if not li.sale_date:
            return False

    return True


def _apply_action(li: Listing, action: dict) -> str:
    """Apply a single action to a listing. Returns action description."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    if not isinstance(li.raw, dict):
        li.raw = {}
    atype = action.get("type", "")
    val = action.get("value", "")

    if atype == "tag":
        tags = raw.setdefault("workflow_tags", [])
        if isinstance(tags, list) and val not in tags:
            tags.append(val)
        return f"tag:{val}"

    if atype == "set_status":
        raw["workflow_status"] = val
        raw["workflow_status_at"] = datetime.now(timezone.utc).isoformat()
        return f"status:{val}"

    if atype == "queue_campaign":
        queue = raw.setdefault("campaign_queue", [])
        if isinstance(queue, list) and val not in queue:
            queue.append(val)
        return f"queue:{val}"

    if atype == "set_field":
        field = action.get("field", "")
        if field:
            raw[field] = val
        return f"set:{field}={val}"

    return f"unknown:{atype}"


def evaluate_workflows(listings: list[Listing], rules: list[dict] | None = None) -> dict:
    """Evaluate all workflow rules against all listings.

    Returns stats dict with per-rule match/action counts.
    """
    if rules is None:
        rules = _load_rules()

    stats = {
        "total_listings": len(listings),
        "rules_evaluated": 0,
        "rules_enabled": 0,
        "total_matches": 0,
        "total_actions": 0,
        "by_rule": {},
    }

    for rule in rules:
        if not rule.get("enabled", True):
            stats["by_rule"][rule.get("name", "?")] = {"matches": 0, "actions": 0, "enabled": False}
            continue
        stats["rules_enabled"] += 1
        stats["rules_evaluated"] += 1
        trigger = rule.get("trigger", {})
        actions = rule.get("actions", [])
        rname = rule.get("name", "?")
        matches = 0
        action_count = 0

        for li in listings:
            if _check_trigger(li, trigger):
                matches += 1
                for action in actions:
                    _apply_action(li, action)
                    action_count += 1

        stats["total_matches"] += matches
        stats["total_actions"] += action_count
        stats["by_rule"][rname] = {"matches": matches, "actions": action_count, "enabled": True}

    log.info("workflow.evaluated", **{k: v for k, v in stats.items() if isinstance(v, int)})
    return stats


def main():
    """Run workflows against the current board."""
    from .web_artifact import load_board
    board = load_board("docs")
    rules = _load_rules()
    print(f"Loaded {len(board)} leads, {len(rules)} rules")
    result = evaluate_workflows(board, rules)
    print(f"Matches: {result['total_matches']}, Actions: {result['total_actions']}")
    for name, info in result["by_rule"].items():
        if info.get("enabled", True):
            print(f"  {name}: {info['matches']} matches, {info['actions']} actions")


if __name__ == "__main__":
    main()
