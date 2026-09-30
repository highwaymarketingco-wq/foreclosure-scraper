"""Bankruptcy + large delinquent-tax-balance combo flag.

Direct implementation of the second half of Dirty Deeds Tier B #28
(docs/dirty_deeds_synthesis_2026-09-10.md): "Bankruptcy recorded against
owner or parcel + large delinquent tax balance ... Ep 036's $450k-net deal
was exactly the bankruptcy/tax pair." Both halves of the join already exist
independently on the board by the time this runs:

  * raw['bankruptcy']   — enrichment_bankruptcy.py's name-matched cross-
                           reference (chapter, date_filed, case_age_days,
                           is_long_open as of 2026-09-29).
  * raw['tax_owed']     — enrichment_tax_owed.py's normalized delinquent-tax
                           balance, cross-referenced onto same-parcel leads.

So this is a pure join, not a new scraper: pure-Python, no network, runs
over listings already in memory. Must run in main.py AFTER both
enrich_with_bankruptcy AND enrich_tax_owed / promote_tax_owed_amount_owed
(the latter two run late in the pipeline, after the resolver) — a listing
processed before both raw keys exist simply has nothing to join yet and is
silently skipped this pass (idempotent: a later pass, or the next full run,
picks it up once both signals land).
"""
from __future__ import annotations

from typing import Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

# "Large" is relative to what this combo actually sees on the board, not an arbitrary round
# number: live-measured 2026-09-29 across the 334 bankruptcy-matched leads that also carried
# a real tax_owed balance, the median was $611.79 and the 90th percentile was $3,197.68.
# $2,500 sits just under that 90th-percentile mark, so `large_balance` below flags roughly
# the top decile as materially large rather than routine single-year lateness -- the COMBO
# flag itself fires on any co-occurrence regardless of size, since the rarity of the
# co-occurrence is itself the synthesis's signal; `large_balance` is an extra ranking cut on
# top of that, not a gate.
LARGE_TAX_BALANCE_THRESHOLD = 2500.0


def enrich_bankruptcy_tax_combo(listings: Iterable[Listing]) -> dict:
    """Tag raw['bankruptcy_tax_combo'] on every listing carrying both a
    bankruptcy match and a real delinquent-tax balance. Returns run stats.
    """
    stats = {"combo": 0, "combo_large": 0, "combo_long_open": 0}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        if not raw:
            continue
        bk = raw.get("bankruptcy")
        to = raw.get("tax_owed")
        if not isinstance(bk, dict) or not isinstance(to, dict):
            continue
        if not bk.get("date_filed"):
            continue
        try:
            balance = float(to.get("balance") or 0)
        except (TypeError, ValueError):
            continue
        if balance <= 0:
            continue

        is_large = balance >= LARGE_TAX_BALANCE_THRESHOLD
        is_long_open = bool(bk.get("is_long_open"))
        li.raw["bankruptcy_tax_combo"] = {
            "tax_owed_balance": round(balance, 2),
            "tax_owed_kind": to.get("kind"),
            "tax_owed_year": to.get("year"),
            "bankruptcy_chapter": bk.get("chapter"),
            "bankruptcy_date_filed": bk.get("date_filed"),
            "case_age_days": bk.get("case_age_days"),
            "case_age_years": bk.get("case_age_years"),
            "is_long_open": is_long_open,
            "large_balance": is_large,
        }
        stats["combo"] += 1
        if is_large:
            stats["combo_large"] += 1
        if is_long_open:
            stats["combo_long_open"] += 1

    log.info("bankruptcy_tax_combo.done", **stats)
    return stats
