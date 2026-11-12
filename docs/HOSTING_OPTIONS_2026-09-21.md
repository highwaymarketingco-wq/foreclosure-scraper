# Hosting the foreclosure dashboard privately: options, recommendation, migration

Written 2026-09-21. Research plus a dry-run-only prototype. Nothing in this document was run
against any provider: no account was created, no login was made, nothing was installed,
uploaded, purchased or changed. Every vendor fact below was read on 2026-09-21 from the URL
given in section 11.

Related files written with this document:

- `scripts/publish_private.sh` - the publish step for the recommended design. Dry run by default.
- `docs/HOSTING_SETUP_CHECKLIST.md` - click-by-click steps for the owner.

Scope note. This is a forward-looking hosting question. It does not revisit the visibility of
the GitHub repository or the PII notices. Moving the payload out of git stops new payload from
being committed; it does not change what is already in history.

---

## 1. The answer on one screen

**Yes, the right shape is a private website with a login.** A "private website" here means
the pages and data are only served to people who have signed in with an approved email
address. Cash, Greg and a few operators can be added or removed by editing a list.

**Recommended (primary): Cloudflare Worker + R2 storage + Cloudflare Access.**

- The app pages (about 0.45 MiB) are served by one Cloudflare Worker.
- The big data (84 MiB board, 31 MiB phone board, 66 MiB of detail shards, 496 MiB of photos)
  sits in a private R2 bucket. It never goes through git again.
- Cloudflare Access sits in front. A visitor types an email address, Cloudflare emails a
  6-digit PIN, and only approved addresses get in. Unapproved requests never reach the Worker
  or the bucket.
- Expected cost: **$0 per month** at this usage (roughly 10 percent of every free allowance).
  A payment card on file may be required to switch on R2 (see risk R2).
- Works on phones and desktop with the existing dashboard code plus small changes
  (section 3).

**Fallback: a small always-on server (Hetzner, about EUR 4.49 per month) running Caddy, reachable
only over Tailscale.** Strongest privacy, but each person installs the Tailscale app, and it
costs money and upkeep. It also gives the pipeline the always-on host it has been missing.

**Why not "just make the repo private and keep GitHub Pages"?** Because a private repo does not
make a private site. On the Free plan, Pages does not publish from a private repo at all. On
Pro or Team it publishes, but the site is still public on the internet. Only GitHub Enterprise
Cloud can restrict a Pages site, only for repos owned by an organization, at $21 per user per
month, and it would still leave the 13 GiB repo and the 1 GB site cap in place.

**What Claude can do:** the Worker, the build and publish tooling, the dashboard changes,
tests, local verification, and updating every publisher script.
**What only the owner can do:** create or log in to the Cloudflare account, add a payment
method if asked, create the bucket and its access key, approve the wrangler login, decide
who is on the allow list, and test the phone flow on a real iPhone.

**Decisions needed from the owner** (full list in section 8):

1. Is a payment card on file at Cloudflare acceptable if Cloudflare asks for one? Expected
   charge is $0. `CLAUDE.md` says "FREE only", so this is the owner's call.
2. Free `workers.dev` URL (no DNS work) or a URL on a domain the owner owns?
3. Who is on the allow list, and email-PIN login or Google login?

**Biggest unverified items** (need an account or a phone to settle; section 9): whether R2 and
the Zero Trust free plan demand a card; whether the iPhone home-screen app survives the Access
login; real upload speed from the Mac.

---

## 2. What is being hosted (measured 2026-09-21)

| Piece | Size | Files | Notes |
|---|---:|---:|---|
| `listings.json.gz` | 84.0 MiB (88,098,890 B) | 1 | Desktop board. Over Cloudflare's 25 MiB per-asset cap; near GitHub's 100 MiB file cap. |
| `listings_slim.json.gz` | 30.8 MiB | 1 | Phone board. |
| `listings_detail.json.gz` | 15.7 MiB | 1 | Desktop only. |
| `detail_shards/` | 66.0 MiB | 171 | Phone detail panel, fetched on tap. Largest file 3.4 MB. |
| small JSON (run_meta, run_health, multifamily, land_buyers, sold_pool) | 2.2 MiB | 5 | |
| **Release total (what changes each publish)** | **198.6 MiB** | **179** | Already gzip, so it does not delta-compress in git. |
| `parcel_photos/` | about 496 MiB | 6,397 | Gitignored now, but 3,955 of them are already tracked. |
| App shell (index.html, dashboard.js, 2 css, manifest, icons) | 0.45 MiB | 10 | |

The board has 170,066 records (`run_meta.json`), about 4.4 times the 38,500 quoted in older
comments in the repo. Git: `git count-objects -vH` reports 13.24 GiB; the GitHub API reports
12.5 GiB (13,129,619 KB); 1,280 commits.

Not hosted, deliberately: `crm.json`, `outreach_maillist.csv`, `skiptrace_worksheet.csv`, the
uncompressed `listings*.json` (1.15 GB), `porsche.*`, all `*.md`, anything in `.secrets/`.
The dashboard never fetches any of them (checked, section 3).

---

## 3. What the client code needs (read from `docs/index.html` and `docs/dashboard.js`)

**Data loading is all relative URLs. There is no hard-coded domain in the page or the script.**

Caveat on line numbers: `docs/dashboard.js` and `docs/index.html` have uncommitted edits from
another session (about 900 changed lines, last touched 12:39 on 2026-09-21), so line numbers
drift. Names are stable. Every finding below was re-checked against the working-tree copy at
12:40 the same day, after those edits: no new fetch target, no service worker, CRM still
browser-only.

| What | Where (identifier, approx. line) | URL as fetched |
|---|---|---|
| Board, phone | `BOARD_FILES` `:487`, `loadBoardStreaming` `:541` | `listings_slim.json.gz?t=<run_time>` |
| Board, desktop | same | `listings.json.gz?t=<run_time>` |
| Run info | `:707`, `:809` | `run_meta.json?t=<now>` |
| Other datasets | `:689`, `:801`, `:834` | `multifamily.json`, `land_buyers.json` |
| Desktop detail | `:4339` | `listings_detail.json.gz` |
| Phone detail | `DETAIL_SHARD_DIR` `:4378`, fetch `:4666` | `detail_shards/NNNNN.json.gz` |
| Card photos | card render near `:4037` | relative `parcel_photos/...` taken from the board's own data |

- **No service worker.** No `serviceWorker` reference exists in either file. There is a web app
  manifest only.
- **The gzip handling already tolerates any host.** The loader sniffs the gzip magic bytes and
  handles both "raw gzip" and "server already inflated" (`fetchJsonMaybeGz` near `:77`, and the
  magic-byte check inside `loadBoardStreaming`). GitHub Pages
  serves the files as `content-type: application/gzip` (checked with `curl -I` today), so serving
  them the same way from R2 is byte-for-byte the path the code has always run.
- **Hard-coded subpath in the manifest.** `manifest.json` has `id`, `start_url` and `scope` all
  set to `/foreclosure-scraper/`. On a host where the site lives at `/`, that breaks installs.
  Making them relative (`"./"`) works at both places.
- **The CRM is browser-only.** `CRM_STORE_KEY` and `crmLoadAll`/`crmSaveAll` near
  `dashboard.js:5876-5891`: status, notes and next-action are kept
  in `localStorage` under the key `fc_crm_v1`. The dashboard sends nothing to any server and
  never touches `docs/crm.json`. That file is a separate local operator file, produced only by
  `src/foreclosure_scraper/outreach.py:37`, and the dashboard never fetches it. No backend is
  needed for the CRM to keep working.
  **But localStorage belongs to one origin.** A new URL starts with empty notes, and the iPhone
  home-screen app has its own separate storage. Notes must be exported and re-imported (R3).
- **Third parties the page calls:** Google Fonts, `unpkg.com` (Leaflet), OpenStreetMap tile
  servers and `staticmap.openstreetmap.de` (`index.html:10,38,539`, `dashboard.js:4058,4259,5158`).
  A private host does not change this. The map requests include lead coordinates.
- **Where the old public URL is hard-coded outside the page:**
  `src/foreclosure_scraper/email_sender.py:15`, `scripts/send_final_email.py:32-33`,
  `docs/OPERATIONS.md:10,204`, and a message in `.github/workflows/porsche-refresh.yml:202`.
  The daily emails to the owner and Greg link to the public site today.
- **How public it is today.** A `curl -I` of the live payload shows `access-control-allow-origin: *`
  and `cache-control: max-age=600`. Any website can read the data from a visitor's browser.

**Changes a private host with a login gate needs (Claude can make all of these):**

1. `manifest.json`: relative `id`, `start_url`, `scope`. In `index.html:15` add
   `crossorigin="use-credentials"` to the manifest link. Reason: browsers fetch the manifest
   without cookies by default, so behind Access it gets the login page instead of JSON and the
   app stops being installable. This is a well-known Access issue (sources in section 11).
2. Add CRM Export and Import (a JSON file) to the dashboard, and use it before cut-over.
3. Handle an expired login: if the first `run_meta.json` fetch fails, reload the page once so
   the browser bounces through the Access login, instead of showing "network error, reload".
   Access sessions last at most one month.
4. Change the four URL references above to the new address.
5. Nothing else in `dashboard.js` needs to change.

---

## 4. Options compared

Ranked by fit for this job: privacy, cost, effort, whether the payload leaves git, and whether
it is always on. "Cost" is the monthly cost for this dataset. Verification level is in
section 11.

| Rank | Option | Privacy | Cost per month | Effort | Payload out of git | Always on | Verdict |
|---:|---|---|---|---|---|---|---|
| 1 | **Cloudflare Worker + R2 + Access** | Per-person email login, enforced at the edge before the Worker runs. Sessions up to 1 month. Revocable within about a minute. | **$0** expected | Medium. Claude builds it; owner about 45 min. | Yes | Yes | **Primary** |
| 2 | **Hetzner VPS + Caddy + Tailscale Serve** | Strongest: no public port. Each person installs Tailscale. | About EUR 4.49 (CX23 EUR 3.99 + EUR 0.50 IPv4); CX33 8 GB EUR 6.49 if it also runs the pipeline | Medium-high, plus ongoing patching | Yes | Yes | **Fallback** |
| 3 | Cloudflare Tunnel from the Mac + Access | Same login as #1 | $0, but the domain must be on Cloudflare | Low-medium | Yes (serve `docs/` directly, no publish step) | **No.** Mac sleeps or is closed. | Stop-gap only |
| 4 | Oracle Always Free VM + Caddy/Tailscale | As #2 | $0 | Medium-high | Yes | Yes, but idle VMs can be reclaimed and the free shape shrank | Only if the pipeline VM goes ahead anyway |
| 5 | Tailscale Serve from the Mac | Strongest | $0 (Personal plan, up to 6 users) | Low, but the Mac's Tailscale app is missing | Yes | **No** | Not enough alone |
| 6 | Google Cloud Run + IAP + Cloud Storage | Google login, Gmail accounts allowed | Pay per use (egress price not verified) | High | Yes | Yes | Not recommended |
| 7 | AWS S3 + CloudFront + login glue | Needs a login mechanism you build | About $0 inside CloudFront free plan (1M requests, 100 GB) | High | Yes | Yes | Not recommended |
| 8 | GitHub Pages private (Enterprise Cloud) | GitHub login, read access to the repo | $21 per user (3 users = $63) | High: repo must move to an org | **No** | Yes | Not recommended |
| 9 | Netlify Pro | Shared password, or Netlify team login | $20 | Medium | Partly | Yes | Poor fit: forum guidance is 10 MB per file |
| 10 | Vercel Pro | Vercel accounts, or password add-on | $20 + $20 per project for password | Medium | Partly | Yes | Poor fit; Hobby forbids commercial use |

Notes on each, with the facts they rest on:

**1. Cloudflare.** Worker static assets and Pages both cap a single file at 25 MiB and allow
20,000 files on Free (Workers limits and Pages limits pages). The 84 MiB board cannot be a
static asset, so it lives in R2 (max object 5 TiB; single PUT up to 4.995 GiB). R2 free tier:
10 GB-month, 1 million Class A and 10 million Class B operations per month; egress is free.
Requests to static assets are free and unlimited; Worker invocations on Free are 100,000 per
day with 10 ms CPU each. Cloudflare Access has a free plan for up to 50 users, and Access can
now be turned on for a Worker in one click and covers its workers.dev URL, custom domains and
previews (changelog dated 2026-08-14). Pages can only protect preview URLs, not the production
`*.pages.dev` address, which is why this design uses a Worker and not Pages.

**2 and 4. VPS.** Hetzner's cost-optimized plans list 20 TB of included traffic; the prices come
from a third-party article because Hetzner's own page did not render prices (see R7). The
cost-optimized plans are EU and Singapore only. Oracle's current Always Free page shows the Arm
allowance as 1,500 OCPU-hours and 9,000 GB-hours a month, which it equates to 2 OCPUs and 12 GB.
`deploy/oracle/README.md` still says 4 OCPUs and 24 GB. Oracle treats an Arm instance as idle, and
reclaimable, if for 7 days CPU, network and memory are all below 20 percent, which a static
dashboard host would be.

**3 and 5. Mac-hosted.** `cloudflared` 2026.3.0 is installed. Named tunnels need a domain on
Cloudflare; quick tunnels have no Access and no uptime promise. `tailscale` on this Mac is a
wrapper pointing at `/Applications/Tailscale.app`, which does not exist. Either way the
dashboard is down whenever the Mac sleeps, and the memory notes call the always-on host the
permanent fix for the pipeline as well.

**6. Google Cloud.** Cloud Run can be put behind IAP directly and Gmail accounts can be granted
access. Cloud Run has a 32 MiB response limit unless the response is streamed or chunked. `gcloud`
is already logged in (account and project exist), which is the one point in its favour.

**7. AWS.** CloudFront has a $0 flat-rate plan with 1M requests and 100 GB. Cognito Lite and
Essentials give 10,000 monthly active users free. But CloudFront signed cookies need something
to issue them, so someone has to build the login. `aws` is not installed.

**8. GitHub.** Sources for the plan facts are in section 11. Enterprise is $21 per user per
month; Free gives 2,000 Actions minutes on private repos, and Pages needs a public repo on Free.
The published-site cap is 1 GB and the recommended repo size is 1 GB; this repo is 13 GiB.

**9 and 10. Netlify, Vercel.** Netlify password protection is on Pro ($20); the only per-file
guidance found was a support-forum answer recommending at most 10 MB. Vercel Pro is $20 a month,
Password Protection is $20 per protected project per month, static uploads via CLI are capped at
1 GB on Pro and 100 MB on Hobby, and Hobby is for non-commercial use.

---

## 5. Recommended design

### 5.1 Architecture

```
  iPhone / desktop browser
        |   https://foreclosure-board.<subdomain>.workers.dev      (or your own domain)
        v
  Cloudflare Access        login: emailed 6-digit PIN, allow-list of email addresses
        |                  (anyone else stops here; they never reach the Worker or R2)
        v
  Worker "foreclosure-board"
        |-- app shell: index.html, dashboard.js, style.css, premium.css, manifest, icons
        |     (0.45 MiB, Workers static assets, free and unlimited requests)
        `-- everything else is read from the R2 bucket
              R2 bucket "foreclosure-board"   (private: no r2.dev URL, no custom domain)
                current.json                       {"release": "20260921T141132Z"}
                releases/<id>/listings.json.gz, listings_slim.json.gz, listings_detail.json.gz,
                              run_meta.json, multifamily.json, land_buyers.json,
                              detail_shards/00000.json.gz ... 00170.json.gz
                parcel_photos/...                  (shared, new files only)

  Publisher: scripts/publish_private.sh --apply   (Mac launchd jobs now, the always-on VM later)
        -> rclone over R2's S3 API -> releases/<id>/ then photos, verify, then current.json last
```

**What serves the HTML:** the Worker's static assets. A request for `/` finds `index.html` and
never invokes Worker code.

**What serves the big files:** the Worker, streaming from R2. A request for
`/listings_slim.json.gz` finds no static asset, so the Worker runs, reads `current.json` (cached
30 seconds), and streams `releases/<id>/listings_slim.json.gz`. The `?t=` cache-busters the
dashboard adds are ignored by the key lookup. Files are stored as `application/gzip` with no
`Content-Encoding`, identical to what Pages serves now.

**How auth works:** Access is attached to the Worker, so it protects every hostname the Worker
has. The visitor enters an approved email, receives a 6-digit PIN (valid 10 minutes, single use)
and gets a session cookie for up to one month. Free plan: up to 50 people.

**Why releases and a pointer:** `dashboard.js` joins board, slim, detail and shards by array
index, and that only holds inside one publish. Uploading many files into one flat folder would
expose a mixed board while the upload runs. Uploading into `releases/<id>/` and writing
`current.json` last means a phone sees the old board or the new board, never a blend, and a
failed upload leaves the live board untouched. Rollback is rewriting one small file.

**How the pipeline publishes:** after `board_payload_add`, each publisher calls
`scripts/publish_private.sh --apply`. Steps: hold the board lock; verify every shard belongs to
this `run_meta.json`; verify every `.gz`; upload the release; sync new photos; check sizes;
write the pointer. Only allowlisted files are ever named. The prototype is tested (section 7,
Phase 0).

**How phones access it:** open the URL in Safari, enter email, enter the emailed PIN, then Add
to Home Screen. The dashboard already works on phones; this only adds the login step. The
phone sign-in repeats when the session ends (at most monthly).

**How a person is added or removed** (no code; a minute either way):

- Add: Cloudflare dashboard, Zero Trust, Access controls, open the policy, add the email under
  Include, Emails, save. Tell the person the URL.
- Remove: delete their email from the policy, then Zero Trust, Team and resources, Users, select
  the person, Revoke. Their existing session ends in about a minute.

**Do not** pick the "Email domain" option with `gmail.com` in the quick setup. That would admit
every Gmail user on earth.

### 5.2 Worker sketch (Appendix A has the code)

About 45 lines. It passes a local logic test against mocked R2 and assets (7 cases, all pass;
the test sat in the session scratchpad and is not in the repo, Phase 0 adds it under `tests/`).
It has not run on the real Workers runtime.

### 5.3 The fallback, spelled out

A Hetzner CX23 (2 vCPU, 4 GB, 20 TB traffic) with Ubuntu, Caddy serving the dashboard from a
folder, and `tailscale serve` so the site exists only on the private tailnet. The publisher
becomes `rsync` of the release folder plus a symlink flip, which is also atomic. Phones need
the Tailscale app and a login. If the operators will not install Tailscale, the alternative is
Caddy with per-user basic auth on a public hostname, which needs a domain and gives weaker
privacy (passwords, not identities). If the pipeline moves onto this server, size it as a CX33
(8 GB, EUR 6.49 + EUR 0.50).

### 5.4 The zero-code stop-gap

If the owner wants "private tonight": `cloudflared` is installed; with a domain on Cloudflare, a
named tunnel to a local static server plus Access gives the same login as the primary design,
serving `docs/` directly. It needs no publish step, but it is down whenever the Mac sleeps.

---

## 6. Monthly cost model (primary design)

Assumptions: up to 10 people, 20 dashboard sessions a day, 150 to 600 Worker requests per
session (app files are free; photos and shards count), 4 publishes a day, 3 releases retained.

| Item | Estimated use | Free allowance | Cost |
|---|---|---|---:|
| R2 storage | about 1.1 GB (3 releases x 199 MiB + 496 MiB photos) | 10 GB-month | $0 |
| R2 Class A (writes, lists) | about 30,000 | 1,000,000 | $0 |
| R2 Class B (reads) | about 100,000 to 400,000 | 10,000,000 | $0 |
| R2 egress | about 45 GB (phone 31 MiB, desktop 100 MiB per fresh load) | free | $0 |
| Worker requests | 3,000 to 12,000 per day | 100,000 per day | $0 |
| Cloudflare Access | 5 to 10 people | 50 people | $0 |
| **Total** | | | **$0** |

If usage ever passed the Worker free cap, Workers Paid is $5 per month minimum (10 million
requests included). Domain, if wanted: cost depends on the registrar and was not researched.
Fallback: about EUR 4.49 to EUR 7 per month. GitHub Enterprise Cloud: $63 per month for 3 people.

---

## 7. Migration plan

Nothing below touches the live GitHub Pages site until Phase 5.

**Phase 0 - Claude, no account needed (about one working session).**

1. Worker, `wrangler.jsonc`, and a script that assembles the `shell/` folder from an allowlist.
2. Dashboard changes from section 3 (manifest, crossorigin, CRM export and import, expired-login
   reload).
3. `board_payload_publish_private` in `scripts/board_payload.sh`, called only when
   `PRIVATE_HOST_TARGET` is set, so behaviour is unchanged until the owner opts in.
4. Update the four hard-coded URLs, held until cut-over.
5. Tests: publish plan, refusals, Worker routing with mocks. Local verification only.
   *Done already:* `scripts/publish_private.sh` and its local tests (below).

**Phase 1 - owner, about 30 to 45 minutes, in `HOSTING_SETUP_CHECKLIST.md`.** Cloudflare login,
two-step verification, R2 bucket (public access off), scoped R2 access key entered into
`rclone config` in Terminal (not in chat), Zero Trust free plan with a team name and One-time PIN.

**Phase 2 - joint.** `scripts/publish_private.sh` dry run, then `--apply` to R2. Owner runs
`wrangler login` and clicks Allow; Claude runs `wrangler deploy`. Owner turns on Access for the
Worker and enters the approved emails.

**Phase 3 - verify.**

- A private window, not signed in, must land on the Cloudflare login page and get no data.
- Desktop: sign in, board loads, photos and shards load.
- iPhone Safari and iPhone home-screen app on Cash's phone and on Greg's phone.
- Bucket has no public URL. `curl` on an object URL without a login returns the login redirect.

**Phase 4 - CRM.** Export from the old site on each device, import on the new one. Re-add the
home-screen icon.

**Phase 5 - cut-over, after one to two weeks of parallel running.**

1. Point all publishers at `publish_private.sh` (weekly `run_local.sh`, `lrcpwa_refresh.sh`,
   `sos_agent_refresh.sh`, and later the VM). The three GitHub Actions publishers
   (`weekly.yml`, `patch-run-scrapers.yml`, `patch-listings.yml`) need R2 keys as repo secrets
   or should be retired; `run_local.sh` already says the cloud workflow was retired.
2. Stop committing the payload: gitignore `docs/listings*.json.gz` and `docs/detail_shards/`,
   `git rm --cached` them in one ordinary commit. This ends the 120 to 180 MB per publish. It
   does not rewrite history.
3. Update the URLs in the daily emails and `OPERATIONS.md`.
4. Retire `pages.yml` and the Pages-specific gates only when the public URL is retired. That
   timing is the owner's call and is not assumed here.

**Rollback:** until Phase 5, nothing changed on the old site. After it, re-enable the git
publish path; the payload files are still on disk.

**Tests already run for the prototype (all local, no network, no provider).**

- `sh scripts/publish_private.sh` on the real repo: passes, 179 release files, all gzip valid,
  171 shards match `run_meta.json`, 6,397 photos, exit 0, about 2 s.
- Refusals verified: `--apply` with no target; with a remote that does not exist; with a
  malformed target; `--prune` without `--apply`; `--keep 1`; an unknown option; a shard gap; a
  shard-count mismatch; a corrupt gzip.
- End-to-end `--apply` against a local folder standing in for the bucket (an rclone `alias`
  remote, tiny fixture files, memory gate off): three releases published in turn, pointer moved
  last each time, `--prune --keep 2` removed the oldest, an uppercase `.JPG` photo copied,
  `crm.json`, a mail-list CSV, a `.md` file and `.DS_Store` were never uploaded, and the board
  lock was released on exit.
- The fixture test caught one real bug, now fixed: under `set -e` the lock's `wait` returned 143
  inside the exit trap and left the lock behind. The existing publishers do not use `set -e`, so
  they are not affected.
- The real board lock was held by `run_daily_vision.sh` throughout and was not touched; every
  lock test used a throwaway folder.
- The publisher takes the board lock, so on this 8 GB Mac it can wait for the lock's memory gate
  (`BOARD_MEM_GATE=enforce` waits up to 15 minutes; the default `warn` proceeds).

---

## 8. Who does what

| Task | Claude | Owner |
|---|:---:|:---:|
| Worker, wrangler config, shell build script | yes | |
| Dashboard changes (manifest, CRM export/import, login-expiry reload) | yes | |
| Publish script, publisher wiring, tests, local checks | yes | |
| Update URLs in emails and docs | yes | |
| Stop committing payload to git | yes (after cut-over OK) | |
| Create or log in to the Cloudflare account, 2-step verification | | yes |
| Add a payment method if Cloudflare asks | | yes |
| Create the R2 bucket; create the scoped access key | | yes |
| Enter the key into `rclone config` (Terminal, not chat) | | yes |
| Approve `wrangler login` (OAuth Allow button) | | yes |
| Turn on Access for the Worker; set the email list | guided | yes |
| DNS, if a custom domain is wanted | | yes |
| Test on a real iPhone, on Greg's phone | | yes |
| Decide when to retire the public Pages URL | | yes |

**Owner decisions:**

1. Card on file at Cloudflare if asked (expected charge $0; `CLAUDE.md` says FREE only).
2. `workers.dev` URL or own domain.
3. Allow-list emails (the two addresses already used for the run emails are in
   `deploy/oracle/vm_run.sh`; confirm operators).
4. Email-PIN login (simple, monthly re-login) or Google login (one tap, more setup).
5. When to retire the public Pages URL. Not assumed.

A later session could also drive the owner's logged-in Cloudflare dashboard through the browser
tools to save clicks. Account creation, card entry, passwords and OAuth approvals stay with the
owner.

---

## 9. Risks and what could not be verified

**Could not be verified without an account or a phone:**

| # | Item | Why unverified | How to settle |
|---|---|---|---|
| U1 | R2 needs a payment card | The R2 docs say "an R2 subscription" is required and are silent on a card. Community posts say a card dialog appears. | Owner follows checklist Part B; note what it asks. |
| U2 | Zero Trust free plan needs a card | Cloudflare's docs are silent; community posts conflict; third-party sites say no card. | Same. |
| U3 | iPhone home-screen app through the Access login | Standalone web apps have their own cookie storage and the login is on another origin. No source found either way. | Real-device test. Fallback: use a Safari bookmark, or Google login. |
| U4 | Free Worker (10 ms CPU) streaming an 84 MiB object | Docs say bodies stream without a size limit; not tested. | Smoke test after first deploy. |
| U5 | Upload speed from the Mac | Depends on the office uplink; about 200 MiB per full release. | First `--apply` timing. |
| U6 | Whether the Cloudflare account in `.secrets` is the owner's, and what the token can do | Values were deliberately not read. Only the file names `cloudflare_account_id.txt` and `cloudflare_api_token.txt` exist. | Owner confirms; a later session may call the token-verify endpoint with permission. |
| U7 | Exact menu labels in the Cloudflare dashboard | Read from docs, not from a login. Menus get renamed. | The checklist says to match the closest label. |
| U8 | Quick-setup Access lists individual emails | Docs show "Cloudflare account" and "Email domain" options; individual emails are set in Zero Trust policy editing. | Owner sees it on screen. |
| U9 | `wrangler.jsonc` syntax | wrangler is not installed. | Validated at first deploy. |
| U10 | Hetzner price, GCP egress price | Hetzner's page showed no prices; Cloud Run pricing page did not load. | Check at checkout. |

**Risks:**

- **R1 Partial publish shows a blended board.** Mitigated by release folders plus the pointer.
- **R2 Card requirement versus the FREE-only rule.** Owner decision. Free-tier overage on R2 is
  billable if ever exceeded; expected use is about 10 percent of every allowance. Set a
  Cloudflare usage notification.
- **R3 CRM notes are orphaned by the URL change.** Per browser and per device today. Mitigated
  by export and import before cut-over.
- **R4 Access session ends at most monthly; the phone shows a generic error.** Mitigated by the
  reload change in section 3.
- **R5 Email security tools can consume the PIN link before the person types it.** Cloudflare's
  docs warn about this. Use Gmail or mail without link scanning.
- **R6 One Cloudflare login is a single point of failure.** Owner-controlled email, two-step
  verification.
- **R7 Old public site and history stay as they are.** Out of scope; the owner has decided.
- **R8 Lead coordinates go to OpenStreetMap services from the map.** Unchanged by this plan.
- **R9 Desktop loads the 84 MiB board (1.15 GB when inflated).** Hosting cannot fix browser
  memory. Making desktop use slim plus shards is a separate change.
- **R10 Automated checks of the private URL need an Access service token.** The publisher
  verifies via R2 directly, so it does not need one.
- **R11 `deploy/oracle/README.md` is stale on the free VM size** (24 GB versus 12 GB now).

---

## 10. What already exists on this machine

Checked with `which`, `gh auth status`, `rclone listremotes`, `gcloud config list`, the
LaunchAgents folder, and the names (not values) in `.secrets/` and `.env`.

- **Installed:** `gh` (logged in as `highwaymarketingco-wq`, active, and `cashhighfive`; scopes
  gist, read:org, repo, workflow), `cloudflared` 2026.3.0, `rclone` (one remote, `smbteam`; no R2
  remote yet), `gcloud` (logged in as the hub Gmail; project `we-are-your-neon-1767234142929`),
  Node 22.23.1 and npm 10.9.8, Python 3, `jq`, `curl`.
- **Broken:** `tailscale` wrapper at `/usr/local/bin/tailscale` points to a missing app.
- **Not installed:** `wrangler`, `aws`, `flyctl`, `netlify`, `vercel`, `caddy`, `hcloud`, `doctl`.
- **LaunchAgents:** `ai.hermes.gateway`, `com.highway.foreclosure.{dailyvision, lrcpwa,
  parcelcache, sosagent, weekly}`, plus `dailycourt` disabled 2026-09-20. The three that publish
  the dashboard by git are `weekly` (via `run_local.sh`), `lrcpwa` and `sosagent`.
- **Credentials by name:** `.secrets/` has `cloudflare_account_id.txt` and
  `cloudflare_api_token.txt`, so a Cloudflare account exists. It also has Google
  (`service_account.json`, `sheet_id.txt`, `google_maps_api_key.txt`), `github_models_token.txt`,
  `gmail_app_password.txt`, and AI and data keys (anthropic, gemini 1 to 9, groq, mistral, nvidia,
  apify, courtlistener). `.env` names: `ACPASS_EMAIL`, `ACPASS_PASSWORD`, `SKIP_TRACE_PROVIDER`,
  `CENSUS_API_KEY`, `GEMINI_API_KEY_1` to `_9`, `GROQ_API_KEY`, `HUD_API_TOKEN`. There are no R2 keys and
  no Hetzner, DigitalOcean, Oracle, Fly, Netlify, Vercel, AWS or Tailscale credentials.
- **The Mac:** 8 GiB, macOS 26.6.2, currently kept awake by `caffeinate`. It is awake by
  arrangement, not by design, which is why the Mac-hosted options rank low.

---

## 11. Sources (all read 2026-09-21)

Vendor documentation unless marked secondary.

**GitHub**

- Private Pages needs Enterprise Cloud, org-owned project sites, read access to the repo:
  https://docs.github.com/en/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site
- Pages limits (1 GB site, 1 GB recommended repo, 10 minute timeout, 100 GB soft bandwidth):
  https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- Pages availability by plan, and public site from a private repo (quoted from a search result of
  docs.github.com pages, not re-fetched):
  https://docs.github.com/articles/creating-project-pages-manually
- Actions minutes (Free 2,000, Team 3,000, Enterprise 50,000; $0.006 per Linux minute):
  https://docs.github.com/en/billing/concepts/product-billing/github-actions
- Plan prices (Team $4, Enterprise $21 per user):
  https://github.com/pricing
- Public API check of account type and repo visibility (User, public, 13,129,619 KB):
  https://api.github.com/repos/highwaymarketingco-wq/foreclosure-scraper

**Cloudflare**

- Workers limits (static assets 20,000 files Free, 25 MiB per file; 100,000 requests a day;
  10 ms CPU; 50 subrequests): https://developers.cloudflare.com/workers/platform/limits/
- Workers pricing (Paid $5 minimum, 10 million requests): https://developers.cloudflare.com/workers/platform/pricing/
- Static assets requests free and unlimited:
  https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/
- Static assets served first, `env.ASSETS`, `run_worker_first`:
  https://developers.cloudflare.com/workers/static-assets/routing/worker-script/ and
  https://developers.cloudflare.com/workers/static-assets/binding/
- Pages limits (25 MiB file, 20,000 files Free): https://developers.cloudflare.com/pages/platform/limits/
- Pages Access covers previews only:
  https://developers.cloudflare.com/pages/configuration/preview-deployments/
- R2 pricing (10 GB, 1M Class A, 10M Class B, free egress, $0.015 per GB-month):
  https://developers.cloudflare.com/r2/pricing/
- R2 limits (5 TiB object, 4.995 GiB single PUT, 1 write per second per key):
  https://developers.cloudflare.com/r2/platform/limits/
- R2 needs "a Cloudflare account with an R2 subscription":
  https://developers.cloudflare.com/r2/get-started/
- R2 S3 tokens, bucket scoping: https://developers.cloudflare.com/r2/data-access/s3-api/tokens/
- rclone with R2 (`no_check_bucket`): https://developers.cloudflare.com/r2/examples/rclone/
- R2 Worker GET pattern: https://developers.cloudflare.com/r2/api/workers/workers-api-usage/
- R2 lifecycle rules by prefix, 1,000 rules: https://developers.cloudflare.com/r2/buckets/object-lifecycles/
- Access on a Worker (steps, policy options, covers custom domains and workers.dev):
  https://developers.cloudflare.com/workers/configuration/cloudflare-access/ and
  https://developers.cloudflare.com/changelog/post/2026-08-14-workers-access/
- workers.dev and Access: https://developers.cloudflare.com/workers/configuration/routing/workers-dev/
- One-time PIN (10 minute expiry, single use, scanner warning):
  https://developers.cloudflare.com/cloudflare-one/identity/one-time-pin/
- Access sessions (up to one month, revoke): 
  https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/
- Seats (one per authenticated person; remove via Users):
  https://developers.cloudflare.com/cloudflare-one/team-and-resources/users/seat-management/
- Access limits (500 applications, 1,000 emails per rule):
  https://developers.cloudflare.com/cloudflare-one/account-limits/
- Self-hosted Access needs the domain active on Cloudflare:
  https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- Free plan for up to 50 users (vendor blog, dated 2020-10-13): https://blog.cloudflare.com/teams-plans/
- Quick tunnels: no account, no SLA, no Access (search result of Cloudflare docs):
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/

**Other vendors**

- Vercel Deployment Protection and pricing ($20 per project for password; Hobby not available):
  https://vercel.com/docs/security/deployment-protection
- Vercel limits (static upload 100 MB Hobby, 1 GB Pro): https://vercel.com/docs/limits
- Vercel pricing (Pro $20, Hobby non-commercial): https://vercel.com/pricing
- Netlify password protection on Pro:
  https://docs.netlify.com/manage/security/secure-access-to-sites/password-protection/
- Netlify plans (Free, Personal $9, Pro $20): https://www.netlify.com/pricing/
- Oracle Always Free resources: https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm
- Tailscale Personal plan (up to 6 users): https://tailscale.com/pricing
- Tailscale Serve is tailnet-private: https://tailscale.com/kb/1312/serve
- DigitalOcean droplets ($4, 500 GiB): https://www.digitalocean.com/pricing/droplets
- Fly.io ($2.02 smallest machine, $0.02 per GB egress, no stated free tier):
  https://fly.io/docs/about/pricing/
- Cloud Run behind IAP, Gmail allowed:
  https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run
- Cloud Run 32 MiB non-streamed response limit: https://docs.cloud.google.com/run/quotas
- AWS Cognito pricing: https://aws.amazon.com/cognito/pricing/
- AWS CloudFront pricing: https://aws.amazon.com/cloudfront/pricing/

**Secondary (not the vendor):**

- Hetzner prices after the April 2026 increase, EU and Singapore only:
  https://www.bitdoze.com/hetzner-cloud-cost-optimized-plans/
- Zero Trust free plan, no card, 24-hour logs, blocked at user 51:
  https://zerometric.net/research/cloudflare-zero-trust-free-plan-limits-2026/
- Card prompts reported by users (search results, threads not fetched): Cloudflare Community
  threads "Why using R2 free tier involves giving card info?" and "Choose the Zero Trust Free Plan
  with No Payment Method".
- Manifest behind Access needs `crossorigin="use-credentials"`:
  https://github.com/mealie-recipes/mealie/issues/3935 and
  https://github.com/danny-avila/LibreChat/discussions/5154
- Netlify per-file guidance, 10 MB recommended (support forum, 2025-05-06):
  https://answers.netlify.com/t/what-is-the-maximum-allowed-object-size/145182

---

## Appendix A. Worker sketch

Local logic test with mocked R2 and assets: 7 of 7 pass. Not run on the real Workers runtime.
The assets folder must hold only the app shell.

```js
const RELEASE_FILES = new Set([
  "/listings.json.gz", "/listings_slim.json.gz", "/listings_detail.json.gz",
  "/run_meta.json", "/run_health.json", "/multifamily.json",
  "/land_buyers.json", "/foreclosure_sold_pool.json",
]);
const POINTER_TTL_MS = 30_000;
let pointer = { at: 0, release: null };

async function currentRelease(env) {
  if (pointer.release && Date.now() - pointer.at < POINTER_TTL_MS) return pointer.release;
  const o = await env.BOARD.get("current.json");
  if (!o) return null;
  const { release } = await o.json();
  if (!/^[0-9A-Za-z_-]{8,40}$/.test(String(release))) return null;
  pointer = { at: Date.now(), release };
  return release;
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", { status: 405 });
    }
    const path = decodeURIComponent(new URL(request.url).pathname);
    if (path.includes("..")) return new Response("Bad request", { status: 400 });

    let key = null;
    if (RELEASE_FILES.has(path) || path.startsWith("/detail_shards/")) {
      const rel = await currentRelease(env);
      if (!rel) return new Response("No release published yet", { status: 503 });
      key = `releases/${rel}${path}`;
    } else if (path.startsWith("/parcel_photos/")) {
      key = path.slice(1);
    } else {
      return env.ASSETS.fetch(request);
    }

    const obj = await env.BOARD.get(key, { onlyIf: request.headers });
    if (!obj) return new Response("Not found", { status: 404 });
    const h = new Headers();
    obj.writeHttpMetadata(h);
    h.set("etag", obj.httpEtag);
    h.set("cache-control", path === "/run_meta.json" ? "private, no-cache" : "private, max-age=300");
    h.set("x-content-type-options", "nosniff");
    const hasBody = "body" in obj;
    return new Response(hasBody ? obj.body : null, { status: hasBody ? 200 : 304, headers: h });
  },
};
```

## Appendix B. wrangler.jsonc sketch (not validated; wrangler is not installed)

```jsonc
{
  "name": "foreclosure-board",
  "main": "worker.js",
  "compatibility_date": "2026-09-01",
  "workers_dev": true,
  "assets": { "directory": "./shell", "binding": "ASSETS" },
  "r2_buckets": [{ "binding": "BOARD", "bucket_name": "foreclosure-board" }]
}
```
