# Google Street View Static — operator setup

The Street View enricher (`src/foreclosure_scraper/enrichment_streetview.py`)
gives every lead with a real street address a **street-level photo of the actual
house** — facade, roof line, boarded windows, overgrowth, tarps, junk cars. That
is the picture the Vision condition-grader needs. Aerial tiles show a roof
polygon; Mapillary is volunteer-contributed and thin outside metro corridors.

**This is the one paid API in the pipeline.** It ships **OFF** and does nothing
until you complete the steps below yourself. Nothing in this repo can create,
request, or enter an API key on your behalf — you do that in your own Google
Cloud Console, in your own browser.

---

## 1. What it actually costs (verified 2026-07-27)

Google retired the pooled **$200/month credit on 2025-03-01** and replaced it
with a **per-SKU free monthly cap**.

| SKU | Tier | Free per month | Price after free |
|---|---|---|---|
| **Static Street View** (the image) | Essentials | **10,000 calls** | **$7.00 / 1,000** (10,001–100,000 band) |
| **Street View Metadata** (`/metadata`) | Essentials | **Unlimited — no charge** | n/a |
| Dynamic Street View (JS embed — *not used here*) | Pro | 5,000 | $14.00 / 1,000 |

Sources (Google, official):
- <https://developers.google.com/maps/billing-and-pricing/pricing>
- <https://developers.google.com/maps/documentation/streetview/usage-and-billing>
- <https://developers.google.com/maps/documentation/streetview/metadata> —
  *"Street View Static API metadata requests are available at no charge. No quota
  is consumed when you request metadata."*

The enricher always calls the free `/metadata` endpoint first and only buys an
image when Google confirms a panorama exists within the radius. On a board where
roughly a third of addresses have no nearby panorama, that alone cuts spend by a
third at zero cost.

### Be honest about billing

**You must attach a billing account (a real credit card) to the Cloud project
even to use the free tier.** Google will not serve Street View Static requests
from a project without billing enabled — requests fail with `REQUEST_DENIED`.
The free 10,000 calls are applied as a discount on the bill, not as a
pre-payment. If usage exceeds the cap, the card is charged.

That is exactly why this enricher hard-caps itself well below the free tier
(default 2,000/month, structurally clamped to 9,000) — see §4.

---

## 2. Steps you perform in Google Cloud Console

Do all of this yourself at <https://console.cloud.google.com>. Do not paste the
key into a chat, a commit, or any file outside `.secrets/`.

1. **Create (or pick) a project.**
   Console → project picker → **New Project** → name it something like
   `foreclosure-streetview`. Note the project ID.

2. **Enable billing on that project.**
   Console → **Billing** → **Link a billing account**. Required even for free-tier
   usage (see above). If you do not want a card attached to anything, stop here —
   leave the enricher off and keep using the free Esri aerial + Mapillary stack.

3. **Enable *only* the Street View Static API.**
   Console → **APIs & Services** → **Library** → search **"Street View Static
   API"** → **Enable**.
   Do **not** enable Geocoding, Places, Directions, or Maps JavaScript. Every
   extra enabled API is another SKU that a mistake could bill against. This
   enricher uses exactly one API.

4. **Create the API key.**
   Console → **APIs & Services** → **Credentials** → **Create credentials** →
   **API key**. Copy it once; you will paste it into a file in step 6.

5. **Restrict the key — do this immediately, before you use it.**
   On the new key click **Edit API key**, then set:
   - **Application restrictions:** `IP addresses`, and add the public IP of the
     machine that runs the pipeline (`curl -s ifconfig.me` on that machine).
     If the runner's IP is dynamic, use `None` — but then §6's key hygiene and
     the quota cap in step 7 are your only protection, so keep the cap low.
     Do **not** use "HTTP referrers": this is a server-side call with no referer.
   - **API restrictions:** `Restrict key` → select **Street View Static API**
     only. A leaked key then cannot be used to bill any other SKU.
   - **Save.**

6. **Set a hard quota ceiling in Google's own console (belt *and* braces).**
   Console → **APIs & Services** → **Street View Static API** → **Quotas &
   System Limits** → find the requests-per-day limit → **Edit** → set something
   like **300/day**. This is enforced by Google, independent of this repo's
   counter, and is the guard that survives a bug on our side. 300/day still sits
   under the 10,000/month free tier even if it ran every single day.

7. **Optional but recommended: a billing budget alert.**
   Console → **Billing** → **Budgets & alerts** → create a budget of $1 with
   email alerts at 50%/90%/100%. If you ever get that email, something is wrong —
   correct behavior is $0.00 forever.

---

## 3. Where the key goes

Save the key on the machine that runs the pipeline, in the repo's gitignored
secrets directory (`.secrets/` is already in `.gitignore`):

```bash
cd ~/foreclosure-scraper
mkdir -p .secrets
printf '%s' 'PASTE_YOUR_KEY_HERE' > .secrets/google_maps_api_key.txt
chmod 600 .secrets/google_maps_api_key.txt
```

Or, if you prefer env vars, export `GOOGLE_MAPS_API_KEY` (a
`GOOGLE_STREETVIEW_API_KEY` alias is also accepted). Env wins over the file.

Verify the file is not tracked:

```bash
git check-ignore -v .secrets/google_maps_api_key.txt   # should print a .gitignore match
```

**If the key file is absent, the enricher logs `streetview.no_api_key` and
returns without making a single request.** Nothing breaks.

---

## 4. Turning it on, and the spend fences

The enricher is off until you set the gate:

```bash
export FORECLOSURE_STREETVIEW=1
```

| Env var | Default | What it does |
|---|---|---|
| `FORECLOSURE_STREETVIEW` | `0` (off) | Master gate. Anything but `1` = hard no-op. |
| `STREETVIEW_MAX` | `300` | Max **billed image calls per run**. |
| `STREETVIEW_MONTHLY_MAX` | `2000` | Max billed image calls per calendar month, tracked in a persistent counter file. |
| `STREETVIEW_ALLOW_PAID` | `0` | Without this, `STREETVIEW_MONTHLY_MAX` is silently clamped to **9,000** — under the 10,000 free tier. You cannot walk into billing by typo. |
| `STREETVIEW_DRY_RUN` | `0` | `1` = metadata-only coverage probe. Zero billed calls. Run this first. |
| `STREETVIEW_BUDGET_S` | `1200` | Wall-clock bail, seconds. |
| `STREETVIEW_CONCURRENCY` | `4` | In-flight requests. |
| `STREETVIEW_RADIUS_M` | `50` | Max metres from the point to accept a panorama. Wider = more coverage, more wrong-house risk. |
| `STREETVIEW_SIZE` | `640x640` | Image size. 640×640 is the largest free-tier size. |
| `STREETVIEW_THUMB` | `640` | Local JPEG is thumbnailed to this before it is written. |
| `STREETVIEW_COUNTER_FILE` | `<repo>/data/streetview_usage.json` | The persistent monthly counter. Resolved **absolutely** (a relative value is anchored at the repo root, never at the cwd) so launching from a different directory can't start a fresh counter. |
| `STREETVIEW_KEY_FILE` | `<repo>/.secrets/google_maps_api_key.txt` | Key file path. Same absolute resolution. |
| `STREETVIEW_METADATA_MAX` | `4 × STREETVIEW_MAX` | Cap on the free metadata probes **per run**. `STREETVIEW_MAX=0` therefore means zero probes too. |
| `STREETVIEW_METADATA_MONTHLY_MAX` | `0` (not enforced) | Monthly cap on free metadata probes. Metadata is free and consumes no Google quota, so the month-to-date total is only *recorded* unless you set this above 0. |
| `STREETVIEW_LOCK_TIMEOUT_S` | `15` | How long to wait for another process's counter lock before **denying** the reservation. It never spends unlocked. |

How the money is fenced, in order:

1. **Gate off by default.** No env var, no requests.
2. **No key → no-op.** The repo never creates one.
3. **Free metadata first.** No panorama nearby → skip, $0.
4. **Disk cache.** A photo already downloaded is re-attached for free. Re-running
   the same board costs nothing.
5. **Per-run cap** (`STREETVIEW_MAX`).
6. **Persistent monthly cap.** `data/streetview_usage.json` survives between
   runs, so ten runs in a month cannot each spend a full run's budget.
7. **Charge-on-attempt.** The counter is incremented **and flushed to disk before
   the request goes out**, never after. A crash mid-call over-counts (costs
   coverage) rather than under-counting (costs money). There are no refunds.
8. **Fail closed.** If the counter file cannot be read or written, the enricher
   refuses to make any billed call at all.
9. **Cross-process lock.** The counter's read-modify-write happens under an
   `flock`'d sidecar (`<counter>.lock`), and the on-disk month total is re-read
   inside that lock before every reservation. Two overlapping runs
   (`run_local.sh` plus `run_daily_vision.sh`, or a manual run on top of either)
   therefore share **one** month budget instead of each spending a full one. If
   the lock can't be taken within `STREETVIEW_LOCK_TIMEOUT_S`, or file locking
   isn't available at all, the run refuses to spend rather than double-spend.
10. **Wall-clock bail** (`STREETVIEW_BUDGET_S`).

What is **not** fenced monthly: the free metadata probes. They are bounded per
run by `STREETVIEW_METADATA_MAX`; the `metadata_calls` figure in the counter file
is bookkeeping, and only becomes a cap when you set
`STREETVIEW_METADATA_MONTHLY_MAX`. Google charges nothing and consumes no quota
for them.

### Recommended first run

```bash
export FORECLOSURE_STREETVIEW=1
export STREETVIEW_DRY_RUN=1          # metadata only — costs nothing
# ...run the enricher... then read the log line: streetview.done
```

`metadata_ok` tells you how many leads actually have Street View coverage. Then
drop `STREETVIEW_DRY_RUN` and start small:

```bash
export STREETVIEW_MAX=50
export STREETVIEW_MONTHLY_MAX=200
```

Check `data/streetview_usage.json` and the Cloud Console billing page after that
run. Both should say the same number, and the bill should be `$0.00`. Raise the
caps only after that reconciles.

### Counter caveat (read this)

`data/streetview_usage.json` lives in the gitignored `data/` directory, so it is
**per-machine and not committed**. The path is repo-absolute, so cwd no longer
matters, but on an ephemeral CI runner (fresh container each run) the file starts
empty every time, and the *monthly* cap therefore resets — the **per-run** cap and the **Google-side daily quota from §2 step 6**
are your real ceilings there. This is precisely why step 6 is not optional if you
ever run this on CI. The month key is UTC, which can differ by a few hours from
Google's Pacific billing month; the 1,000-call gap between the 9,000 clamp and
the 10,000 free tier absorbs that skew.

---

## 5. What it writes

Per lead, inside `raw['images']` (the whole `images` blob is already whitelisted
into the published board):

```jsonc
{
  "street": "parcel_photos/streetview/nc_buncombe_9648718374.jpg",
  "street_source": "google_streetview",
  "streetview": {
    "provider": "google_streetview",
    "pano_id": "CAoSLEFGM...",
    "capture_date": "2025-04",
    "pano_location": {"lat": 35.5951, "lng": -82.5515},
    "attribution": "© Google",
    "query": "35.595100,-82.551500",
    "fetched_at": "2026-07-27T15:04:05+00:00",
    "local_path": "parcel_photos/streetview/nc_buncombe_9648718374.jpg"
  },
  "primary": "parcel_photos/streetview/nc_buncombe_9648718374.jpg"
}
```

`primary` follows the existing priority from `enrichment_images`:
**real > street > aerial > map**, and `raw.zillow.photo` (the dashboard card
image) is kept in sync without ever clobbering a scraper's real listing photo.

### Why the image is downloaded instead of hot-linked

The signed Street View URL contains `key=<your API key>`, and `docs/listings.json`
is published to a **public** GitHub Pages site. Putting that URL on the board
would hand your billable key to anyone who opens the dashboard or views source.
So the JPEG is fetched server-side once, thumbnailed, and written to
`docs/parcel_photos/streetview/`, exactly like the assessor photos in
`enrichment_lrcpwa_photo`. Only the relative path is published. **The key never
leaves the process.** Keep it that way.

Attribution: Google's terms require the "© Google" / Google logo to remain
visible on displayed Street View imagery. The image Google returns already has
it burned in — do not crop it out.

---

## 6. If something looks wrong

| Symptom | Meaning |
|---|---|
| `streetview.disabled` | `FORECLOSURE_STREETVIEW` is not `1`. Expected default. |
| `streetview.no_api_key` | No key in env or `.secrets/`. Expected until you finish §3. |
| `streetview.abort_no_ledger` | The counter file can't be locked or written. It refused to spend. Fix the path/permissions. |
| `streetview.ledger.lock_timeout` | Another streetview process holds the spend counter. It refused to spend unlocked. Wait for the other run, or raise `STREETVIEW_LOCK_TIMEOUT_S`. |
| `streetview.ledger.no_file_locking` | No `fcntl` on this platform, so the counter can't be serialized across processes. It refused to spend. |
| `streetview.monthly_cap_clamped` | Your `STREETVIEW_MONTHLY_MAX` was above the free-tier guard and was lowered. |
| `no_imagery` high | Normal in rural NC/SC — many private drives have no panorama. |
| `errors` high with `billed_image_calls` high | Google returned non-images. Check the key restrictions from §2 step 5 (an IP restriction that no longer matches returns `REQUEST_DENIED`). |
| Any charge at all on the bill | Stop: unset `FORECLOSURE_STREETVIEW`, then reconcile `data/streetview_usage.json` against the Cloud Console usage graph before re-enabling. |

To turn it off instantly: `unset FORECLOSURE_STREETVIEW`. To turn it off
permanently and irreversibly: delete the key in the Cloud Console.
