# Audit 2026-10-09: the brief every audit agent follows

## Why
The owner wants ONE more run (full or tail) after which the board is right: every source pulled
everything it can, every row's data belongs to that row, every column means what its name says,
every document and image is read, nothing is dropped by accident, and every lead we call about
has a real, checked problem. Findings so far this month (a tax debt copied onto 20,185 wrong rows,
presence checks that counted placeholders, caps that starved counties, enrichers that were built
but never wired) are all one family: a defect nobody measured. This audit measures everything and
leaves behind checks that keep measuring.

## Rules (all of them apply to every agent)
- Repo /Users/cashhigh/foreclosure-scraper is PUBLIC. No owner names, phones, emails, notice
  text, credentials or private addresses in code, tests, fixtures, docs or commit messages. Counts,
  parcel ids, county names and source slugs are fine. Private detail (names allowed) goes only to
  /Users/cashhigh/Desktop/Audit_2026-10-09/ (not in the repo).
- 8 GB Mac. Stream the board with board_stream.iter_board_rows(); never load it whole; never write
  docs/listings.json; keep peak RSS under 1 GB; at most one board pass at a time per agent; other
  agents and a live sweep run at the same time, so check memory (vm_stat) before a heavy pass.
- VM (ssh -i ~/.ssh/oracle_foreclosure ubuntu@129.146.23.144) is read-only for you: a gated run is
  in progress using up to 16 GB. Reading logs with tail/grep is fine; never start, stop or kill
  anything, never run a heavy command there, never write to it.
- Never bypass, auto-solve or extend CAPTCHA / WAF / login / paywall handling. Existing stealth or
  solver code stays exactly as it is: do not delete, disable, extend or run it by hand. Walled
  sources are recorded (what blocks, what the owner would do by hand) and left. Click-through
  disclaimers and credential-free guest buttons are allowed.
- Never delete or disable a scraper; if one is broken or noncompliant, surface it in your report.
- Live fetching: at least 2 s between requests to one host, one request at a time per host,
  ordinary browser User-Agent. Sample, do not crawl.
- Do not edit main.py or docs/HANDOFF.md. Give the exact wiring lines (file, anchor, code) in your
  report; the lead wires them. Do not touch docs/handoff/verification/* (a sweep writes there).
- Heir candidate names publish only for the relations in PUBLISHABLE_HEIR_RELATIONS. The
  dashboard and repo stay public with names and phones for property owners (owner decision); do not
  propose private/login/history rewrites.
- Tests: targeted pytest only (uv run pytest tests/<file>). Fixtures are made up.
- Git: commit LOCALLY with the pathspec form `git commit -m "..." -- <paths>`; retry if
  .git/index.lock exists; never push, pull, fetch, rebase or reset. End every commit message with:
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
- Say what you did not verify. Never report a number you did not compute.

## What "done" means for each finding
Fixed at the source, with a test, AND an invariant check that would have caught it; or recorded as
wall / no source exists / owner decision with the exact reason. A finding with no invariant is not
done.

## The invariant interface (so the pre-run gate can run every check in one pass)
Each audit area adds scripts/audit_checks/<area>.py exposing
    def make_checks() -> list
where each item has `name` (kebab-case), `feed(row: dict) -> None` (called once per board row, in
stream order) and `finish() -> dict` returning
    {"name", "checked": int, "violations": int, "max_violations": int, "ok": bool, "detail": str}
`ok` is violations <= max_violations. Checks keep O(1) or small bounded memory (counters, capped
samples of parcel ids). The runner (scripts/audit_suite.py, written by the pipeline-gate agent)
feeds one pass of the board to all checks.

## Report format (docs/audit_2026-10-09/<area>.md, public-safe, plus your reply to the lead)
1. What you measured and how (so it can be repeated), with the counts.
2. Defects found: class, scale (rows x counties x sources), cause, fix, test, invariant name.
3. Open items: wall / no source / owner decision / not enough time, each with the reason.
4. Anything you saw outside your area that looks wrong (one line each).
Reply to the lead in plain words, under 300 words.
