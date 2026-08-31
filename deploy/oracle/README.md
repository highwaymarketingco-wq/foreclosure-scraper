# Cloud split — free Oracle Always-Free VM

This runs the heavy half of the engine on a **free, always-on** Oracle Cloud VM,
so a full run finishes without OOM-ing your 8 GB Mac and without your Mac even
being on. Your Mac keeps only the 39 stealth scrapers that need its residential
IP.

```
  ┌──────────────── your Mac (residential IP) ─────────────────┐
  │  scripts/run_stealth_sources.py                            │
  │   • runs the 39 stealth-browser sources ONLY               │
  │   • no board load, no enrichment  → stays under 8 GB       │
  │   • writes docs/handoff/stealth_leads.json → git push      │
  └───────────────────────────┬────────────────────────────────┘
                              │  (GitHub, one small file)
  ┌───────────────────────────▼──── Oracle VM (24 GB, always-on) ┐
  │  deploy/oracle/vm_run.sh   (FORECLOSURE_ROLE=vm)             │
  │   • runs the other 178 datacenter-safe sources              │
  │   • national.stealth_handoff ingests the Mac's leads        │
  │   • ALL enrichment (vision/comps/skiptrace/photos)          │
  │   • writes the board + git push → GitHub Pages dashboard    │
  └─────────────────────────────────────────────────────────────┘
```

Why the split: ~178 sources are open GIS/assessor/PDF APIs that don't care about
IP and run fine from a datacenter. The 39 stealth sources (sc_public_index,
nc_sos_ucc, the law-firm foreclosure calendars, zillow/auction, nc_ecourts, the
DataDome land sites) get IP-blocked from a datacenter, so they stay on the Mac.
The list is **derived from the code** (`foreclosure_scraper.source_split`), so it
stays correct as sources change — check it any time with:

```bash
uv run python -m foreclosure_scraper.source_split
```

---

## Part A — create the free VM (once, ~15 min, in the Oracle web console)

I can't create the account or click these for you. Do this part yourself.

1. **Sign up:** https://www.oracle.com/cloud/free/ → create an Always-Free account
   (needs a card for identity; Always-Free resources are never charged).
2. **Create instance:** Console → *Compute → Instances → Create instance*.
   - **Shape:** *Change shape → Ampere → VM.Standard.A1.Flex.* Set **4 OCPUs**
     and **24 GB RAM** (the whole Always-Free Ampere allowance — free forever).
   - **Image:** *Canonical Ubuntu 22.04* or *24.04*.
   - **SSH keys:** upload your public key (or let it generate one and download the
     private key). You'll SSH in as user **`ubuntu`**.
   - Create. Note the **public IP**.
   - If Ampere capacity is "out of capacity" in your region, retry later or pick a
     different availability domain — it frees up.
3. **Open no inbound ports.** The VM only makes outbound connections (scraping +
   git push), so you do NOT need to open any inbound port. Leave the default
   security list alone. (Egress is open by default.)

## Part B — provision it (once, ~10 min, over SSH)

```bash
ssh ubuntu@<VM_IP>

# 1. git token so the private repo can clone + publish (see secrets_checklist.md)
echo 'github_pat_xxxxxxxx' > ~/github_token.txt

# 2. bootstrap (installs uv, Python 3.12, deps, chromium; clones the repo)
export GITHUB_TOKEN="$(cat ~/github_token.txt)"
curl -fsSL "https://raw.githubusercontent.com/highwaymarketingco-wq/foreclosure-scraper/main/deploy/oracle/setup.sh" | bash
#   ^ if the repo is private and the raw URL 401s, clone manually first:
#     git clone https://x-access-token:$GITHUB_TOKEN@github.com/highwaymarketingco-wq/foreclosure-scraper.git
#     bash foreclosure-scraper/deploy/oracle/setup.sh
```

## Part C — copy your secrets (once)

From your **Mac** (see `secrets_checklist.md` for the full list):

```bash
rsync -av ~/foreclosure-scraper/.secrets/ ubuntu@<VM_IP>:~/foreclosure-scraper/.secrets/
```

## Part D — test one run, then schedule it

```bash
# on the VM
cd ~/foreclosure-scraper
bash deploy/oracle/vm_run.sh          # first run: ~1-3h (scrape + enrich + publish)
tail -f logs/vm-run-*.log             # watch it (another SSH tab)

# once a run publishes cleanly, install the daily timer:
bash deploy/oracle/install_timer.sh   # default 07:00 UTC daily
```

Check it:

```bash
systemctl list-timers foreclosure.timer --no-pager   # when it next runs
journalctl -u foreclosure.service -f                 # live run output
```

## Part E — wire up the Mac half

On your Mac, schedule the stealth half so it feeds the VM (see `deploy/mac/`):

```bash
bash ~/foreclosure-scraper/deploy/mac/install_stealth_schedule.sh
```

That runs `run_stealth_sources.py` on a cadence, pushing fresh stealth leads the
VM picks up on its next run. Run it manually any time:

```bash
cd ~/foreclosure-scraper && uv run python scripts/run_stealth_sources.py
```

---

## Operating notes

- **Single writer of the board:** only the VM writes `docs/listings.json*`. The
  Mac writes only `docs/handoff/stealth_leads.json`. Different files → the two
  hosts pushing to `main` just rebase past each other, no board conflict.
- **Ordering:** run the Mac stealth job a bit BEFORE the VM run so the hand-off
  is fresh. If the Mac hasn't pushed, the VM ingests the last hand-off (warns if
  >72 h old) — the board never goes blank.
- **Turn the split off** (run everything on one host again): unset
  `FORECLOSURE_ROLE` — the pipeline runs all 218 sources as before.
- **ARM caveat:** the VM runs only datacenter-safe sources, so it needs no
  stealth browser to scrape. `camoufox` (scrapling) is best-effort on ARM; if an
  enricher tries to render and it's missing, that enricher logs blocked and the
  run continues.
- **Costs:** VM.Standard.A1.Flex at 4 OCPU / 24 GB is within Always-Free and is
  never billed. Everything the pipeline calls (Gemini/NIM/Groq vision, Street
  View within quota) is free-tier. Net: $0/mo.
