# VM secrets checklist

The VM needs the same secrets your Mac uses. They live in `.secrets/` (which is
git-ignored, so it is NEVER pushed and must be copied over manually). I cannot
transfer these for you — credentials are yours to move.

## How to copy them (one command from your Mac)

```bash
# from your Mac, replace <VM_IP> with your instance's public IP
rsync -av ~/foreclosure-scraper/.secrets/ ubuntu@<VM_IP>:~/foreclosure-scraper/.secrets/
```

(If `~/foreclosure-scraper/.secrets/` on the VM does not exist yet, `setup.sh`
creates it — run setup first, then rsync.)

## What must be present (required — the run refuses to start without these)

| File | What it is |
|---|---|
| `.secrets/service_account.json` | Google service account (writes the Sheet) |
| `.secrets/sheet_id.txt` | target Google Sheet id |
| `.secrets/gmail_app_password.txt` | Gmail app password (sends the digest email) |

## Strongly recommended (free enrichment pools — without these, less data)

| File | What it is |
|---|---|
| `.secrets/gemini_api_key.txt` (+ `gemini_api_key_1..N.txt`) | free Gemini Vision, auto-rotated |
| `.secrets/nvidia_api_key.txt` | free NVIDIA NIM vision lanes |
| `.secrets/groq_api_key.txt` | free Groq vision pool |
| `.secrets/github_models_token.txt` | free GitHub Models pool |
| `.secrets/google_maps_api_key.txt` | Street View + geocoding (stays within free tier) |
| `.secrets/courtlistener_token.txt` | CourtListener (lis-pendens) |
| `.secrets/anthropic_api_key.txt` | Vision fallback if no free pool is set |

## Git token (separate from `.secrets/` — needed to clone + publish)

The repo is private, so the VM needs a GitHub token to clone it and to push the
refreshed dashboard. Create a **fine-grained PAT** with **Contents: read and
write** on `highwaymarketingco-wq/foreclosure-scraper`, then before running
`setup.sh`:

```bash
echo 'github_pat_xxxxxxxx' > ~/github_token.txt   # on the VM
```

`setup.sh` picks it up and configures git; you do not need it again.
