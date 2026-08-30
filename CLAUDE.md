# foreclosure-scraper — read this first

Free, public-only motivated-seller lead engine. 18-county NC + SC footprint.
Publishes `docs/listings.json(.gz)` to a GitHub Pages dashboard.

**Start every session by reading [`docs/HANDOFF.md`](docs/HANDOFF.md).** It is the
current state of play and is kept up to date deliberately so a cold session does
not have to rediscover anything. This file is only the map.

## Hard constraints — these are not negotiable

- **FREE only.** No paid services. All free techniques are permitted:
  CAPTCHA solving, headless browser JS rendering, Cloudflare bypass,
  anti-bot evasion — all allowed as long as they cost nothing.
- **One board writer at a time.** Any script that writes the board must go
  through `web_artifact.load_board()`, or it wipes the vision/comps/cama
  sidecars. See `docs/HANDOFF.md`.
- **Never ask the user for credentials or API keys in chat.** Put them in
  `.env` instead.
- New-source hunting targets the **core footprint**: Western NC + Upstate SC.
  Coastal is out of scope unless a reader already covers it for free.
- No em dashes and no AI verbiage in client-facing deliverables.

## The failure mode this codebase actually has

**Silent success.** Nearly every real defect found here returned HTTP 200 and
green tests while being wrong: a 404 with a 16-byte body read as "no records", a
2,000-row response that was the head of an index rather than a filtered window, a
party list capped at exactly 1000 that looked like a count.

So: **never accept a status code as evidence.** Check that a response contains
the thing you asked for, and assert the shape in a test. When a number looks
round (1000, 2000), assume it is a cap until proven otherwise.

## Layout

| path | what |
|---|---|
| `src/foreclosure_scraper/scrapers/` | sources, auto-discovered by `_registry.py` |
| `src/foreclosure_scraper/enrichment_*.py` | enrichers |
| `src/foreclosure_scraper/web_artifact.py` | board read/write — `load_board()` |
| `scripts/` | operator tools, registry builders, self-checks |
| `docs/` | 43 files; `HANDOFF.md` is the index |

## Commands

```bash
.venv/bin/python -m pytest -q
```

```bash
.venv/bin/python scripts/board_selfcheck.py
```

```bash
.venv/bin/python scripts/recompute_valuation.py
```

Never run `regenerate_dashboard.py` to fix valuations — it is a ~13-hour network
re-enrichment. `recompute_valuation.py` does it offline in 40 seconds.

## Keeping context cheap

Tool output is the main cost driver in a session, because every turn re-sends
all of it. Print counts and samples, never whole pages or files. When a session
gets long, update `docs/HANDOFF.md` and start a new one.
