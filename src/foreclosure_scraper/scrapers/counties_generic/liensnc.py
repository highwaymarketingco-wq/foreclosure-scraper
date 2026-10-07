"""LiensNC lien-agent appointments, incremental, with the owner's own login. Mac only.

`counties_generic.liensnc` is the slug the ~40,000 LiensNC rows on the board already carry
(scripts/scrape_liensnc.py + scripts/ingest_all.py, run by hand; the last ingest's newest
filing is 08/26/2026). This scraper keeps that source fresh without anyone running a script:
each cycle fetches only the filings the board does not hold yet and hands them off.

HOW IT RUNS. `mac_only = True` puts it with the residential sources (source_split), so
scripts/run_stealth_sources.py (launchd com.highway.foreclosure.stealth-handoff, 06:00) runs
it on the Mac and writes its rows into docs/handoff/stealth_leads.json, and the VM run
(FORECLOSURE_ROLE=vm) skips it and ingests those rows through national.stealth_handoff. The
work is foreclosure_scraper.liensnc_handoff.run_cycle(): one read-only board pass, the
date-bounded newest-first search, the ledger of rows sent but not on the board yet.

The search page is login-gated (that is why national.liensnc stays disabled); the account
belongs to the owner and is read by scripts/scrape_liensnc.py (LIENSNC_USER / LIENSNC_PASS
from the environment, else its built-in default). A refused login stops the cycle at once
with no retry; a CAPTCHA stops it and holds every later cycle until a person deletes
data/liensnc/captcha_seen.json.

Switches: LIENSNC_HANDOFF=0, or the file data/liensnc/OFF, turns it off. LIENSNC_MAX_PAGES
(default 300 pages of 50), LIENSNC_MAX_SECONDS (1500), LIENSNC_STOP_AFTER_KNOWN (100),
LIENSNC_PENDING_MAX_DAYS (10).

URL: https://apps.liensnc.com/scr/filing/advancedSearch.html
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import structlog

from ...base_scraper import OUTCOME_PARTIAL, BaseScraper
from ...models import Listing

log = structlog.get_logger()

_STOPPED = ("login_failed", "captcha", "captcha_hold")
#: `touch data/liensnc/OFF` pauses it without editing the launchd job (git-ignored).
_OFF_FILE = Path(__file__).resolve().parents[4] / "data" / "liensnc" / "OFF"


class LiensNCIncrementalScraper(BaseScraper):
    slug = "counties_generic.liensnc"
    name = "LiensNC lien-agent filings (incremental, owner login, Mac only)"
    category = "lien_filing"
    # Board pass (~30 s) + up to LIENSNC_MAX_SECONDS of paced paging + the conversion.
    timeout_s = 2400.0
    expected_min_count = 0      # a quiet day, or every new filing already handed off
    #: Runs only on the Mac (source_split.residential_slugs): the login lives there.
    mac_only = True

    def __init__(self) -> None:
        # Read at construction (the greenville_hard_distress pattern) so safe_run reports
        # DORMANT, an intentional skip, instead of a suspicious zero.
        super().__init__()
        if (os.environ.get("FORECLOSURE_ROLE") or "").strip().lower() == "vm":
            self.disabled = True
            self.disabled_reason = ("Mac only: the LiensNC login is used on the Mac; the VM "
                                    "ingests the hand-off")
        elif os.environ.get("LIENSNC_HANDOFF", "1") == "0" or _OFF_FILE.exists():
            self.disabled = True
            self.disabled_reason = ("switched off by the operator (LIENSNC_HANDOFF=0 or "
                                    "data/liensnc/OFF)")

    async def fetch(self) -> Iterable[Listing]:
        from ...liensnc_handoff import run_cycle, summary_lines

        rows, report = await run_cycle(log=lambda m: log.info("liensnc.progress", msg=m))
        for line in summary_lines(report):
            log.info("liensnc.cycle", summary=line)
        scan = report.get("scan") or {}
        stop = scan.get("stop_reason")
        if stop in _STOPPED:
            reason = f"{stop}: {scan.get('error') or ''}".strip()
            if not rows:
                raise RuntimeError(reason)
            self.last_outcome, self.last_reason = OUTCOME_PARTIAL, (
                f"{reason}; handed off {len(rows)} rows still pending from earlier cycles")
        elif not scan.get("complete"):
            self.last_outcome, self.last_reason = OUTCOME_PARTIAL, (
                f"scan stopped at {stop} (page {scan.get('last_page')} of "
                f"{scan.get('total_pages')}); the next cycle resumes it")
        return rows
