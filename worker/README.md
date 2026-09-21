# Private dashboard Worker

A Cloudflare Worker that serves the foreclosure dashboard to signed-in people only.
The app pages come from the Worker's static assets. The big data (board, phone
board, detail shards, photos) is streamed from a private R2 bucket. Cloudflare
Access is the login in front; the Worker also checks the Access token itself.

This folder is the Worker and its tooling. Everything the owner does is in
`docs/HOSTING_SETUP_CHECKLIST.md`; this README follows the same Part numbers and
only adds the exact commands. How it works, the risks, and what has and has not
been tested: `docs/HOSTING_WORKER_2026-09-21.md`.

```
worker/
  wrangler.jsonc          template (safe as shipped: no public URL, answers 503)
  deploy.conf.example     the few values you fill in (no secrets)
  src/                    the Worker (plain JS, no dependencies, no build step)
  scripts/                build_shell.mjs (app files + CSP hashes), render_config.mjs
  test/                   node:test suite, no Cloudflare needed
  ../scripts/deploy_worker.sh   dry run by default: deploy, smoke test, roll back a release
```

## Before you start

Nothing here changes the live GitHub Pages dashboard. Node is already installed.
Two commands are worth running now, they touch nothing:

```
cd worker && node --test test/*.test.mjs     # 100+ tests, about 6 seconds
scripts/deploy_worker.sh                     # dry run: prints the plan and the exact commands
```

## Owner steps, in order

Parts 0 to 5 are exactly as written in `docs/HOSTING_SETUP_CHECKLIST.md`. Do them
first: decide (Part 0), Cloudflare account (Part 1), private bucket named
`foreclosure-board` (Part 2), upload key and the `rclone` remote called `r2`
(Part 3), Zero Trust team plus One-time PIN (Part 4), first upload with
`scripts/publish_private.sh` (Part 5).

Have these three values ready for the next part, all from Part 0 to Part 4:
your **Account ID**, your **Zero Trust team name**, and the **address choice**.

### Part 6. Put the app online

1. Install wrangler once: `npm install -g wrangler`
   (the checklist uses `npx wrangler login`; either works, but the deploy script
   needs `wrangler` on the PATH. With npx instead, run every command below as
   `WRANGLER="npx --yes wrangler" scripts/deploy_worker.sh ...`).
2. `wrangler login`. A browser page asks whether to let Wrangler use your
   Cloudflare account. Click **Allow**. This is the one approval only you can give.
3. Create your settings file and fill in the first two lines. No secrets go in it:
   ```
   cp worker/deploy.conf.example worker/deploy.conf
   ```
   - `CF_ACCOUNT_ID=` your Account ID (Part 1)
   - `URL_MODE=workers-dev` for a free `something.workers.dev` address (no DNS),
     or `URL_MODE=custom-domain` plus `WORKER_HOSTNAME=board.yourdomain.com`
   - leave `ACCESS_TEAM_DOMAIN` and `ACCESS_AUD` empty for now
4. Dry run, read what it prints, then apply:
   ```
   scripts/deploy_worker.sh
   scripts/deploy_worker.sh --apply
   ```
   `--apply` builds the app files, writes the deploy config, checks that the login
   can see your account, and runs `wrangler deploy`. It prints the address.
   The first ever deploy on an account may ask you to pick a `workers.dev` subdomain.

**Do not share the address yet.** Until Part 7b the Worker answers **503 to every
request** and serves nothing, because it has no Access team or audience tag to check
tokens against. That is deliberate: a first deploy cannot leak anything.

### Part 7. Lock it

Exactly as the checklist, then one addition (7b):

1. Workers and Pages, click `foreclosure-board`, the **Access** tab, **Protect this
   Worker behind Access**, **All traffic** (not "Previews only"), pick the account
   policy, **Apply Access**.
2. Zero Trust, Access controls, Policies: open that policy, Include, Emails, type
   each person's address. Remove anything broader (never "Email domain").
3. **7b (new).** Copy the **Application Audience (AUD) Tag** of that Access
   application (Zero Trust, Access controls, Applications, open the Worker's
   application, Basic information; as with the checklist, match the closest label if
   Cloudflare has renamed it). Put it in `worker/deploy.conf`:
   ```
   ACCESS_TEAM_DOMAIN=yourteam
   ACCESS_AUD=<the 64 character tag>
   ```
   then run `scripts/deploy_worker.sh --apply` again. From now on the Worker refuses
   any request that does not carry a valid Access token for this application, even
   if Access itself were ever switched off or misconfigured.

### Part 8. Test

Do the checklist's tests (private window must show the login, wrong email refused,
desktop, iPhone Safari, iPhone home screen icon, Greg's phone). Then the automatic
check, no login needed:

```
scripts/deploy_worker.sh --smoke-test https://your-address --apply
```

Without credentials it proves the address hands out nothing. To also test the
Worker's own behavior (healthz, gzip bytes, Range, ETag, blocked files) give it a
service token, for the length of the test only:

1. Zero Trust, Access controls, Service credentials, Service Tokens, create a token
   (1 day is enough). Copy the Client ID and Secret; the secret is shown once.
2. On the Worker's Access application, add a policy with action **Service Auth**
   that includes that token.
3. In Terminal (values typed there, never in chat):
   ```
   export CF_ACCESS_CLIENT_ID=...
   export CF_ACCESS_CLIENT_SECRET=...
   scripts/deploy_worker.sh --smoke-test https://your-address --apply
   ```
4. Delete the service token and its policy afterwards. A service token is a standing
   key to the data; do not leave it around.

If a token check fails and you need to see why, put `AUTH_DEBUG=true` in
`worker/deploy.conf`, run `scripts/deploy_worker.sh --apply`, repeat the smoke test, and
remove the line and deploy again. Refusals then carry an `X-Auth-Deny` header naming the
reason.

### Part 9 and after

Notes carry-over and people are as in the checklist. Quick reference:

- **Add a person:** Zero Trust, Access controls, Policies, the Worker's policy,
  Include, Emails, add, Save. Nothing to deploy.
- **Remove a person:** delete the address from the policy, Save, then Zero Trust,
  Team and resources, Users, select them, **Revoke**.
- **Publish a new board:** unchanged, `scripts/publish_private.sh --apply`. The
  Worker follows the new `current.json` within 30 seconds. No Worker deploy.
- **Roll a board back to an older release:**
  ```
  scripts/deploy_worker.sh --rollback-release 20260920T101010Z            # dry run
  scripts/deploy_worker.sh --rollback-release 20260920T101010Z --apply
  ```
  Do not run it while `publish_private.sh` is running.
- **Roll the Worker code back:** `wrangler rollback` (from `worker/`).
- **Dashboard files changed** (`index.html`, `dashboard.js`, css, manifest): run
  `scripts/deploy_worker.sh --apply` again. It rebuilds the app files and the
  Content-Security-Policy hashes from `docs/`.
- **Page looks broken after a dashboard change** (blank, buttons dead): the Content
  Security Policy may be blocking new inline code. Put `CSP_RELAXED=true` in
  `worker/deploy.conf` and deploy as a stop-gap, then tell Claude.

## Local checks without Cloudflare

```
cd worker
node --test test/*.test.mjs             # everything
node scripts/build_shell.mjs --check    # can the app files be assembled from docs/?
node scripts/render_config.mjs --print --account <id> --url-mode workers-dev
```

`wrangler dev` (after `npm install -g wrangler` and `node scripts/build_shell.mjs`)
should run the Worker on your machine against a simulated, empty bucket without a
login; it was not run while this was written. The Worker honors `ACCESS_ENFORCE=false`
only on `localhost` and answers 500 to it on any other host.
