# The private dashboard Worker: how it works, how to run it, what is verified

Written 2026-09-21. Companion to `docs/HOSTING_OPTIONS_2026-09-21.md` (why this
design) and `docs/HOSTING_SETUP_CHECKLIST.md` (what the owner clicks). This
document covers the Worker and deploy tooling that were built from them.

Nothing here was deployed. No account was created, no login was made, wrangler was
not installed or run, and no Cloudflare service was contacted. Vendor facts were read
from public documentation pages on 2026-09-21 (section 10). The board was not loaded
and nothing in `.secrets` or `.env` was read.

Files written (all new; nothing existing was edited):

- `worker/src/index.js`, `access.js`, `routes.js`, `bucket.js`, `security.js`, `csp.js`
  the Worker, plain ES modules, no dependencies, no build step
- `worker/wrangler.jsonc`, `worker/deploy.conf.example`, `worker/.gitignore`, `worker/package.json`
- `worker/scripts/build_shell.mjs`, `shell_lib.mjs`, `render_config.mjs`, `config_lib.mjs`
- `worker/test/*.test.mjs`, `worker/test/helpers.mjs` (108 tests)
- `worker/README.md` (owner steps in order)
- `scripts/deploy_worker.sh` (dry run by default: deploy, smoke test, roll back a release)
- this document

---

## 1. How it works

```
 phone / desktop
      |  https://<your address>
      v
 Cloudflare Access   email + emailed 6-digit code, allow-list of emails   (the real gate)
      |
      v
 Worker "foreclosure-board"
   1. authorize(): valid Access token for THIS application, else 403      (second gate)
   2. GET/HEAD only
   3. classify(): allowlist of paths, everything else 404
   4. serve
        app files  <- static assets built from docs/ (about 0.5 MiB)
        data       <- private R2 bucket, streamed, never parsed
```

**Why assets and R2 both.** The 84 MiB board cannot be a static asset (25 MiB per file
on Workers Free), so the data streams from R2. The app files are tiny and rarely change,
so they ship with the Worker as static assets, which is the choice
`HOSTING_OPTIONS` section 5.1 made. `wrangler.jsonc` sets `assets.run_worker_first: true`
so the token check also covers app files. Without it the platform serves matching
assets without running any Worker code, and the second gate would not apply to them.

### Request handling

| Request | Served from | Cache-Control | Notes |
|---|---|---|---|
| `/`, `/index.html` | assets (`/`) | `private, no-cache` | hashed CSP; `/index.html` is fetched as `/` to avoid the assets redirect |
| `/dashboard.js`, `/style.css`, `/premium.css` | assets | `private, max-age=3600` when the URL has `?v=`, else `no-cache` | `?v=` is how `index.html` versions them |
| `/manifest.json` | assets | `private, no-cache` | `application/manifest+json` |
| `/icons/<name>` with a png, svg or ico extension | assets | `private, max-age=86400` | |
| `/run_meta.json` | R2, the **current** release | `no-store` | always current, ignores `?t=` |
| `/listings.json.gz`, `/listings_slim.json.gz`, `/listings_detail.json.gz`, `/detail_shards/NNNNN.json.gz`, `/multifamily.json`, `/land_buyers.json`, `/foreclosure_sold_pool.json`, `/run_health.json` | R2 `releases/<id>/...` | with a valid `?t=<run_time>`: `private, max-age=31536000, immutable`; otherwise `private, no-cache` | see "release pinning" |
| `/parcel_photos/[<folder>/]<name>` with a jpg, jpeg, png or webp extension | R2 `parcel_photos/...` | `private, max-age=86400` | flat or one folder deep (`streetview/`), as on disk |
| `/current.json` | R2 | `no-store` | the pointer; useful with curl to see what is live |
| `/healthz` | pointer (cached 30 s) | `no-store` | `{"ok":true,"release":"...","published_at":...,"board_count":...,"auth":"jwt"}`; 503 before the first publish |
| `/robots.txt` | Worker | `private, max-age=86400` | `Disallow: /` |
| anything else | | | 404 |

Every response, including 403, 404, 304, 416, carries: `X-Content-Type-Options: nosniff`,
`X-Robots-Tag: noindex, nofollow, noarchive`, `X-Frame-Options: DENY`, a Permissions-Policy
that switches off camera, microphone, geolocation, payment, USB, `Strict-Transport-Security:
max-age=31536000`, a Content-Security-Policy, and a Referrer-Policy. There is no
`Access-Control-Allow-Origin` and no CORS preflight is answered; the GitHub Pages site sends
`access-control-allow-origin: *` today (`HOSTING_OPTIONS` section 3).

### Allowlist

Default deny. A path is served only if `worker/src/routes.js` matches it. It refuses, before
any lookup: any character outside `[A-Za-z0-9_./-]` (so no `%2f`, no backslash, no unicode),
`//`, any dot segment or dotfile (`.env`, `.git`, `.gitkeep`, `..`), paths over 200 characters,
uncompressed `listings*.json`, and the extensions `.md .env .csv .py .sh .sqlite .db .pem .key .map
.log .yml .toml .lock .txt .bak .zip` and names containing `crm`, `outreach`, `maillist`,
`skiptrace`, `porsche`, `secret`, `credential`, `password`. A test checks that every file
`scripts/publish_private.sh` uploads is on the list, so the two cannot drift apart silently.

### Gzip files: no Content-Encoding

`dashboard.js` fetches `listings_slim.json.gz`, `listings.json.gz`, `listings_detail.json.gz` and
`detail_shards/NNNNN.json.gz` by their `.gz` names, reads the first two bytes, and if they are
`1f 8b` inflates the body itself with `DecompressionStream` (`loadBoardStreaming`,
`fetchJsonMaybeGz`). It also copes with a server that already inflated it. GitHub Pages serves
them as `application/gzip` with no `Content-Encoding` (`HOSTING_OPTIONS` section 3). The Worker
does the same: it sets `Content-Type: application/gzip` itself, sets **no** `Content-Encoding`, and
ignores whatever content type or encoding rclone stored on the object. Bytes pass through
untouched. That also keeps Range meaningful (byte offsets of the stored file, not of an inflated
stream) and avoids any compression work in the Worker.

### Release pinning (why `?t=` matters)

`dashboard.js` joins the board, the phone board, the detail file and the shards **by array index**,
which only holds inside one publish. It requests the board files, the detail file and the shards as
`<name>?t=<run_time>`, where `run_time` is what it just read from `run_meta.json`. (`run_meta.json`,
`multifamily.json` and `land_buyers.json` carry `?t=<Date.now()>` instead, which is not a run time, so they
come from the current release and are revalidated; they are not index-joined with the board.)
`publish_private.sh` names each release folder from that same `run_time`. So the Worker reads `?t=`, and when it is a well-formed run time it
serves that exact release, not "whatever is current now":

- a phone that loaded board N and taps a lead after board N+1 was published still gets shard data
  from release N, so a card can never show another property's owner and phone;
- the response is genuinely immutable, so `max-age=31536000, immutable` is safe to send;
- a `?t=` that names a release that has been pruned is a 404 (the page shows its load error and a
  reload fixes it), never the newer board;
- a missing, malformed or non-run-time `?t=` falls back to the current release, revalidated on use.

The release id is derived exactly as `publish_private.sh` derives it (`re.sub` of non-alphanumerics
on `run_time.split(".")[0]`, plus `Z`; a run time with no fractional part yields an id ending `ZZ`,
as the script produces, and a test pins that). It is validated before it becomes part of an R2 key,
and a hostile `?t=` cannot select any other key (tested).

### Pointer

`current.json` is read from R2 and remembered in the isolate for `POINTER_TTL_SECONDS` (30). If a
refresh fails or the file is missing, the last good value keeps serving; if there never was one the
answer is 503. A pointer whose `release` is not a plausible id (`../../etc`) is ignored.

### Streaming and CPU

Objects are handed to the `Response` as the R2 stream. The only R2 body ever parsed is the
pointer (about 100 bytes). There is no compression, no JSON parsing of payloads, no buffering; a
test asserts the body is a `ReadableStream` and that no buffering method is called on it.
Workers Free allows 10 ms CPU per request, and time waiting on network or storage does not count
(Cloudflare Workers limits page). Per request the Worker does: a Map lookup for the already
verified token, one regex over the path, at most one small pointer read (cached), and then hands the object stream through. `Content-Length` is not set on
GET responses (the runtime derives it from the R2 body; setting it by hand risks a mismatch); it is
set on HEAD.

### Range and conditional requests

- `Range: bytes=a-b`, `bytes=a-`, `bytes=-n` return 206 with `Content-Range: bytes a-b/size`.
  The Worker parses the header itself and passes an explicit range to R2 (no dependence on how R2
  parses header strings). A range past the end is a 416 with `Content-Range: bytes */size`.
  A multi-range or malformed header is ignored and the whole object is sent, which RFC 9110 allows.
- `If-Range` is not supported by R2, so the Worker checks it against the object's strong ETag with one
  `head()` and only honors the range when it matches.
- `ETag` is R2's. `If-None-Match` and `If-Modified-Since` give 304 (R2 evaluates them and returns
  the object without a body); a failed `If-Match` gives 412.
- HEAD uses `head()` and never opens the object.

### Access token check (`src/access.js`)

Cloudflare documents the token as the `Cf-Access-Jwt-Assertion` request header, signed RS256, with
public keys at `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` (JSON with a `keys` array
of JWKs), claims `aud` (application tags, an array), `iss`, `email` (people) or `common_name`
(service tokens), `exp`, `nbf`. The Worker:

1. requires the header (or `ctx.access`, below), else 403;
2. accepts only `alg: RS256` (rejects `none`, HS256 and friends) with a `kid`;
3. fetches the certs (subrequest, I/O not CPU), caches the key set for one hour, keeps using the old
   set for up to a day if the certs URL is down, refetches at most once a minute when it sees an
   unknown `kid` (Access rotates keys every six weeks and keeps two live);
4. verifies the signature with WebCrypto, then `exp`, `nbf` (30 s skew), `iss` equal to
   `https://<team>.cloudflareaccess.com`, `aud` contains a configured tag, and an identity claim;
5. remembers a verified token for up to five minutes so the steady state is a Map lookup.

The team domain is checked against `^[a-z0-9-]+\.cloudflareaccess\.com$` before it is used to build the
certs URL, so a mistyped or hostile variable cannot point the fetch elsewhere.

**Fails closed.** Enforcing with `ACCESS_TEAM_DOMAIN` or `ACCESS_AUD` missing or still a placeholder
answers 503 to everything. That is what a first deploy does, before Access exists.

**Local dev bypass.** `ACCESS_ENFORCE=false` is honored only when the request host is `localhost`,
`127.0.0.1` or `[::1]`. On any other host it is refused with 500, so setting it in production does not
open the site (tested).

**`ctx.access`.** Cloudflare's newer "protect a Worker with Access" feature (changelog 2026-08-14)
exposes the signed-in identity as `ctx.access`, set by the runtime only when Access authenticated the
request. The docs do not say whether the JWT header is also forwarded in that mode. Rather than gamble,
the Worker accepts either: a valid JWT header, or `ctx.access` (whose `aud`, when the runtime supplies
one, must be ours). `ACCESS_ACCEPT_CTX=false` requires the header only. The smoke test prints which
path authenticated it (`"auth":"jwt"` or `"ctx"`).

### Content-Security-Policy (`src/security.js`, `src/csp.js`)

Derived from what `docs/index.html` and `docs/dashboard.js` actually load, then checked in a real
browser (section 6). Scripts: own origin, `https://unpkg.com` (Leaflet), and SHA-256 hashes of the
inline `<script>` blocks and of inline handler attributes, so an injected script from scraped text
would not run. Styles keep `'unsafe-inline'` because the page uses many `style=""` attributes, plus
Google Fonts and unpkg. Images: self, `data:`, `blob:`, `https:` (OSM tiles, listing photo hosts that
vary by scraper). Fonts: `fonts.gstatic.com`. `connect-src 'self'` (every `fetch()` in the dashboard is
a relative URL). No frames, forms, objects, workers, base tag.

The hashes are computed by `worker/scripts/build_shell.mjs` from the very `index.html` and
`dashboard.js` it copies, and written into the shell as `csp-hashes.json`, so they ship in the same
`wrangler deploy` as the files they describe and cannot go stale relative to them. The Worker reads
that file once per isolate. If it is missing or malformed the page still loads under a weaker policy
(`'unsafe-inline'`), labelled by the `X-CSP-Mode` response header (`hashed`, `relaxed`,
`relaxed-no-hashes`); the smoke test warns on anything but `hashed`. `CSP_RELAXED=true` is the
break-glass switch.

Current numbers: 2 inline scripts and 1 inline handler (`onclick="event.stopPropagation()"`, which
`dashboard.js` writes into card markup) are hashed. A handler containing a template interpolation
cannot be hashed ahead of time; the build prints a WARNING and `--strict` fails on it.

---

## 2. Configuration

Wrangler vars (`worker/wrangler.jsonc`; `scripts/deploy_worker.sh` fills them from `worker/deploy.conf`):

| Var | Default | Meaning |
|---|---|---|
| `ACCESS_TEAM_DOMAIN` | placeholder | `acme`, `acme.cloudflareaccess.com` or with `https://` |
| `ACCESS_AUD` | placeholder | Application Audience tag; comma separated for several |
| `ACCESS_ENFORCE` | `true` | `false` only honored on localhost |
| `ACCESS_ACCEPT_CTX` | `true` | also accept `ctx.access` |
| `POINTER_TTL_SECONDS` | `30` | 0 to 300 |
| `CSP_RELAXED` | `false` | break-glass, adds `'unsafe-inline'` for scripts |
| `AUTH_DEBUG` | `false` | refusals carry `X-Auth-Deny: <reason>`; smoke tests only |

Bindings: `BOARD` (R2 bucket `foreclosure-board`, from `HOSTING_SETUP_CHECKLIST` Part 2) and
`ASSETS` (static assets from `worker/shell/`, built, git-ignored).

`worker/deploy.conf` (git-ignored, no secrets; environment variables of the same name win):
`CF_ACCOUNT_ID`, `URL_MODE` (`workers-dev` or `custom-domain`), `WORKER_HOSTNAME`,
`ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, `WORKER_NAME`, `BUCKET_NAME`, `R2_TARGET`, `CSP_RELAXED`, `AUTH_DEBUG`.
The file is parsed, never sourced, and only these keys are accepted.

**URL modes.** The template ships with `workers_dev: false` and `preview_urls: false`, so the default
`*.workers.dev` address is not exposed and the template deployed as-is has no URL at all. The checklist
Part 0 offers a free `workers.dev` address as the first choice, so `URL_MODE=workers-dev` turns it on in the
rendered config (and only there); `URL_MODE=custom-domain` adds a custom-domain route instead. Preview URLs
stay off in both. The script refuses `--apply` until one is chosen. Cloudflare says Access on a Worker covers
its `workers.dev` hostname, custom domains and previews, and with the Worker's own token check a `workers.dev`
address is not public even before Access is switched on: it answers 503.

**Two-phase first deploy.** The Access application's AUD tag exists only after Access is attached to the Worker,
and Access is attached to a Worker that already exists. So: deploy with the placeholders (safe, answers 503),
attach Access, copy the AUD tag and team name into `deploy.conf`, deploy again.

`scripts/deploy_worker.sh` modes: default dry run (runs the 108 tests, checks the shell can be built from
`docs/`, validates settings, prints the rendered config and the four commands `--apply` would run);
`--apply` (refuses without `--apply`, a valid `CF_ACCOUNT_ID`, a `URL_MODE`, `wrangler` on the PATH, a login
that lists the account; builds the shell, renders the config, runs `wrangler whoami --json`, then
`wrangler deploy --config wrangler.rendered.jsonc` from inside `worker/`); `--smoke-test URL [--apply]`;
`--rollback-release ID [--apply]`. It never reads `.secrets` or `.env`, never prints a token, and passes a
service token to curl on stdin so it is not in the process list (tested).

---

## 3. How phones access it

Same as the checklist: open the address in Safari, type the email, type the emailed 6-digit code,
then Share, Add to Home Screen. The dashboard already works on phones (a small touch screen, or `?lean=1`,
selects the slim board and fetches detail shards on tap); only the login step is new. The sign-in repeats when
the Access session ends (at most monthly). Notes and statuses in the dashboard live in each browser's
`localStorage`, so a new address starts empty (checklist Part 9).

## 4. Add or remove a person

No code and no deploy. The Worker checks the application's audience, not a list of people, so the
Access policy is the only place people are listed.

- Add: Zero Trust, Access controls, Policies, the Worker's policy, Include, Emails, add, Save.
- Remove: delete the address from that policy, Save, then Zero Trust, Team and resources, Users, select
  the person, Revoke. Access ends the session in about a minute. (Cloudflare labels may differ; match the closest.)
- Never use the "Email domain" rule with `gmail.com`.

## 5. Roll back

**A board (release).** `publish_private.sh` writes `releases/<id>/` and flips `current.json` last, and keeps the
newest N with `--prune --keep N`.

```
scripts/deploy_worker.sh --rollback-release 20260920T101010Z            # dry run
scripts/deploy_worker.sh --rollback-release 20260920T101010Z --apply
```

It checks the folder exists in the bucket and has a readable `run_meta.json` with a board count, then writes
`current.json` in the same format `publish_private.sh` writes, and reads it back. It refuses if
`publish_private.sh` is running (that script would overwrite the pointer when it finishes), and a refused
rollback leaves the pointer alone. The Worker follows within 30 seconds. Pages that are already open keep
working from the release they loaded (release pinning), provided that release still exists.
Consequence for pruning: `--keep 3` at four publishes a day means a tab left open for more than about
18 hours will get a 404 on a detail shard and needs a reload. Raising `--keep` costs R2 storage
(about 199 MiB per release against 10 GB free); `--keep 6` is comfortable.

**The Worker code.** `wrangler rollback` (from `worker/`) makes a previous Worker version active
(Cloudflare wrangler commands page). Or check out the older `worker/` and deploy again.

**Everything.** Nothing was changed on the old GitHub Pages site. Delete the Worker and bucket, or stop using the address.

---

## 6. What is verified locally, and what is not

All local, no network beyond a loopback server. Node v22.23.1.

**Tests: 108 pass, 0 fail** (`cd worker && node --test test/*.test.mjs`, about 6 seconds; the dry run of
`scripts/deploy_worker.sh` runs them too).

| File | Tests | Covers |
|---|---:|---|
| `routes.test.mjs` | 6 | allowlist, 40-odd denied names, path tricks, release id from run_time (matches `publish_private.sh`), every published file is served |
| `access.test.mjs` | 20 | RS256 verify with a generated RSA key and a stub JWKS: accept, service token, wrong aud, wrong issuer, expired, not yet valid, no identity, forged signature with the right `kid`, tampered payload, `none`/HS256/RS512 downgrades, malformed input, key cache one hour, stale keys when certs are down, key rotation, unknown `kid` rate limit, `ctx.access`, localhost-only dev bypass, placeholder config, hostile team domain |
| `worker.test.mjs` | 46 | gate on every path (403, bucket never read), 405, 503 unconfigured, pointer resolution and TTL and rollback, `?t=` pinning and pruned release, hostile `?t=`, no `Content-Encoding` on `.gz`, content types, Range 206/416/ignored/If-Range, ETag 304, 412, HEAD, streaming without buffering, security headers on 200/304/403/404/405/416, CSP contents, cache policy, CSP fallback modes, `no-store` on pointer and run_meta, error path leaks nothing |
| `shell.test.mjs` | 11 | inline script and handler extraction (comments, `src`, JSON, CRLF), hashes vs an independent parser on the real `docs/index.html`, plan refusals, 25 MiB cap, and an end to end run of `build_shell.mjs` then the Worker serving the built shell with a CSP covering every inline script |
| `config.test.mjs` | 7 | JSONC parser, the shipped template (workers.dev off, `run_worker_first`, placeholders, `compatibility_date` not in the future), config rendering and validation |
| `deploy_script.test.mjs` | 18 | the shell script against a fake wrangler in a temp repo: dry run touches nothing, every `--apply` refusal, happy path order (whoami then deploy from `worker/`), token never echoed, rollback with a fake rclone, and `--smoke-test` against a local simulation of Access in front of the real Worker (passes; wrong token fails; Access bypassed still refused by the Worker; a public site fails loudly) |

Not covered by the fakes, and said plainly: the fake R2 is my reading of the R2 API (section 1 sources),
not R2. Node's WebCrypto is not workerd.

**Real browser check.** The real Worker code ran under Node on `localhost` with a fake bucket and the real
`docs/` shell built by `build_shell.mjs`, and the Browser pane (a Chromium browser) loaded it. Results: the page rendered
its cards from `listings.json.gz` (desktop) and from `listings_slim.json.gz` plus a detail shard
(`?lean=1`, card opened); Leaflet, Google Fonts, OSM tiles and marker images loaded; the theme bootstrap and
theme toggle (hashed inline scripts) worked; the hashed `onclick="event.stopPropagation()"` ran without a
violation; **zero CSP violations from the app itself**. An injected inline `<script>` and an injected
`<img onerror>` were both blocked, as intended. The manifest was served as `application/manifest+json`. This
was the only browser test; Safari and iOS were not tested.

**Timing (Node, not workerd, informational).** Import of an RSA public JWK 1.1 ms, one RS256 verify 0.3 ms warm,
cached-token check 0.003 ms, an authorised photo request end to end 0.06 ms with faked R2. A first verify
in a cold Node process measured between 1 ms and 47 ms depending on whether the crypto stack had been used yet
(concurrent test load). Cloudflare's limit is 10 ms CPU; the warm numbers suggest a wide margin, the cold
figure is exactly what W3 needs to settle on the real runtime.

**Needs a real Cloudflare account (or a phone):**

| # | Item | How to settle |
|---|---|---|
| W1 | `wrangler` accepts the rendered config (`run_worker_first`, `preview_urls`, `workers_dev`, `routes`) and uploads the shell; `wrangler` is not installed here | first `--apply`; the config keys were checked against the wrangler configuration docs |
| W2 | Real R2 behavior for `get` with `range` and `onlyIf`: the shape of the returned `range`, that an unsatisfiable range throws (the 416 path relies on it), that a failed precondition returns an object without a body | smoke test: Range 206 with `1f8b`, `If-None-Match` 304; a manual `curl -r 999999999999-` for 416 |
| W3 | workerd CPU per request on the free plan, especially the cold isolate (import key, verify, certs JSON) | `wrangler tail` or the Workers metrics after a few sessions |
| W4 | Whether Access forwards `Cf-Access-Jwt-Assertion` to a Worker protected directly, or only `ctx.access` | the smoke test prints `authenticated via jwt` or `ctx`; both are accepted |
| W5 | The Worker can fetch the certs URL; `keys` shape as documented | smoke test healthz 200 with the service token (or AUTH_DEBUG reason `jwks_unavailable`) |
| W6 | An 84 MiB object streams through a free Worker to a phone and to desktop | first load on real devices; Cloudflare's docs say bodies stream, untested |
| W7 | iPhone home-screen app through the Access login (own cookie storage, login on another origin) | checklist Part 8; fallback is a Safari bookmark or Google login |
| W8 | Service token flow for the smoke test: needs a Service Auth policy on the Worker's Access application | README Part 8 |
| W9 | OSM tiles with the real Referer (`https://<name>.workers.dev`) | open a lead with a map; only `localhost` was tested |
| W10 | Edge behavior for `.json` responses (compression drops `Content-Length`, ETag may become weak) | none expected to matter; look at headers once |
| W11 | Exact Cloudflare dashboard labels used in the README (Application Audience tag location) | owner sees it on screen |
| W12 | First deploy on an account may prompt for a `workers.dev` subdomain | owner answers in the terminal |

---

## 7. Known risks

**Access and phones**

- **iPhone home-screen app behind Access (W7).** A standalone web app has its own cookie storage, and the
  Access login happens on another origin (`<team>.cloudflareaccess.com`). Nobody has confirmed the login
  survives this. Also, iOS fetches the manifest without cookies unless the link has `crossorigin="use-credentials"`;
  `HOSTING_OPTIONS` section 3 lists that as a change to `index.html`, which another session owns. The Worker
  side is ready for it (the manifest is same-origin and Access authenticates the credentialed request).
  Fallbacks: Safari bookmark, or Google login for one-tap sign-in.
- **Session expiry shows a network error.** `dashboard.js` treats a failed first fetch as "network error"; the
  reload-once change is in `HOSTING_OPTIONS` section 3 item 3 and is not part of the Worker.
- **Two possible authentication paths (W4).** Either works; if Cloudflare changes what it forwards, the token
  check keeps working through the other.

**Data path**

- **Range on large gz (W2, W6).** Range is implemented, unit tested against a fake, and correct by the R2 API
  as documented. `dashboard.js` itself never sends `Range`; only a browser resuming a download or `curl -r`
  does, so a Range defect would not break loading. The unverified parts are R2's exact semantics and how the
  edge and Safari handle a 206 of a very large streamed body. `Content-Length` is deliberately not set on GET.
- **Streaming 84 MiB on the free plan (W6).** Memory is not an issue (nothing is buffered) and waiting on I/O is not
  CPU time. Untested on the real runtime. The desktop still inflates a 1.15 GB board in the browser regardless of
  host (`HOSTING_OPTIONS` R9).
- **Pruned release (section 5).** Long-open tabs get a 404 on shards after their release is pruned.
- **`?t=` depends on `publish_private.sh` naming.** If either the run time format in `run_meta.json` or the id
  formula in the script changes, a non-matching `?t=` falls back to the current release, which is the old
  behavior (mix possible across a publish), not an outage. The test that pins the formula will fail first.

**Free plan limits**

- **Request budget.** With `run_worker_first`, app-file requests are Worker invocations, so they count against
  100,000 a day. Cloudflare's static assets billing page says that over the limit these requests get a 429 instead
  of falling back to free assets. Estimate at the assumptions in `HOSTING_OPTIONS` section 6 (20 sessions a day,
  about 600 requests each including 10 app files): about 12,000 a day, 12 percent. A phone stuck in a reload loop
  could spend more; watch the Workers dashboard for the first weeks.
- **R2 operations.** Every payload GET or HEAD and every photo revalidation is one Class B read (HeadObject
  counts as Class B, per the R2 pricing page). Immutable `?t=` URLs and one-day photo caching keep repeats
  off R2. The pointer is read at most every 30 seconds per isolate. Free allowance is 10 million a month.
- **CPU (W3).** Designed to stay near 1 ms; not measured on workerd.

**Content-Security-Policy**

- **Drift.** The CSP was derived from today's `index.html` and `dashboard.js`, both being edited by another session.
  A new external host (a `fetch()` to another origin, a new font or script CDN) is blocked until `src/security.js`
  allows it. A new inline handler that contains `${...}` cannot be hashed; the build warns. `CSP_RELAXED=true` is
  the stop-gap for scripts only. `connect-src` and the host lists need a code change.
- **Third parties.** Leaflet loads from unpkg with no `integrity` attribute in `index.html`; a compromised CDN
  file would run in the page with access to the board and the notes. CSP cannot fix that. Suggested change to
  `index.html` (owned by the other session): add SRI hashes, or copy Leaflet into `docs/` and the shell.
  The map also sends lead coordinates to OpenStreetMap (`HOSTING_OPTIONS` R8), and Google Fonts, unpkg and OSM
  see the site's origin as Referer (below).

**Operations**

- A **service token** used for the smoke test is a standing key to the data; delete it after the test.
- `/current.json` reveals the release id, publish time and board count to a signed-in user. Not sensitive.
- `worker/shell/` and `worker/wrangler.rendered.jsonc` are generated and git-ignored; `deploy.conf` is git-ignored.

---

## 8. Findings that differ from the brief or from `HOSTING_OPTIONS`

1. **Referrer-Policy.** Asked: `no-referrer`. Applied to every response except the HTML document, which gets
   `strict-origin-when-cross-origin`. OpenStreetMap's tile servers return 403 "Access blocked" to requests with no
   Referer (their Tile Usage Policy: "Do not send no-referrer", verified on the OSM foundation page and Leaflet's issue
   tracker), and the dashboard draws OSM tiles. The document, not the data files, is what makes those requests.
   Cost: the three third-party hosts see the site's origin. Reversible in one line in `security.js`.
2. **`workers_dev: false`.** As asked, in the template. The checklist recommends a free `workers.dev` address, so
   `URL_MODE=workers-dev` opts in at render time. The Worker fails closed either way. See section 2.
3. **`run_worker_first: true`.** Not in `HOSTING_OPTIONS` Appendix B. Required for the second gate to cover app files, at
   the price of counting them against the 100,000 daily requests.
4. **`ctx.access`.** `HOSTING_OPTIONS` cites Cloudflare's one-click Access for Workers (changelog 2026-08-14). Its docs
   describe `ctx.access` and say no JWT parsing is needed, without saying whether the header is also forwarded. The
   Worker accepts either.
5. **Release pinning by `?t=`.** Beyond the brief, and the reason immutable caching is safe (section 1).
6. **`no-store` on `run_meta.json`** (Appendix A had `no-cache`), and `/current.json` is served (behind the gate) so an operator can see
   what is live. It is not the app's business and the dashboard never requests it.
7. **`robots.txt` is behind the gate too**, per "every request". Its only reader could be a signed-in user, since Access
   blocks crawlers first; `X-Robots-Tag: noindex` on every response is the control that matters.
8. **No `Cross-Origin-Resource-Policy` header is sent.** It would add little (the Access cookie is not sent on
   cross-site subresource loads) and could not be verified against iOS home-screen icon fetching.
9. **Appendix A of `HOSTING_OPTIONS` is superseded** by `worker/src/`. Its pointer TTL, allowlist and key layout are
   kept; its `key = releases/<current>` is replaced by pinning.

## 9. Proposed edits to other files (not made, not mine to edit)

**`scripts/publish_private.sh`: no change needed.** The layout it writes (`releases/<id>/...`, `parcel_photos/...`,
`current.json` with `release`, `published_at`, `board_count`) is exactly what the Worker reads, and a test reads
`REQUIRED_FILES` and `OPTIONAL_FILES` from the script to prove every uploaded file is served. One suggestion for the
person who runs it: use `--prune --keep 6` rather than the default 3 (section 5).

**`docs/HOSTING_SETUP_CHECKLIST.md`, Parts 6 and 7** (the Worker cannot be deployed with the placeholders replaced
until Access exists, so a second deploy is needed):

```diff
 ## Part 6. Put the app online (5 minutes)

-- [ ] Claude asks you to run `npx wrangler login` in Terminal. A browser page opens asking
-      whether to let Wrangler use your Cloudflare account. Click **Allow**. This is the OAuth
-      approval only you can give.
-- [ ] Claude runs `wrangler deploy`. It prints an address like
-      `https://foreclosure-board.YOURSUBDOMAIN.workers.dev`. **Do not share it yet.** It is public
-      until Part 7 is finished.
+- [ ] In Terminal: `npm install -g wrangler`, then `wrangler login`. A browser page opens asking
+      whether to let Wrangler use your Cloudflare account. Click **Allow**. This is the OAuth
+      approval only you can give.
+- [ ] `cp worker/deploy.conf.example worker/deploy.conf`, then set `CF_ACCOUNT_ID` (Part 1) and
+      `URL_MODE=workers-dev` (or `custom-domain` and `WORKER_HOSTNAME`) from your Part 0 answer.
+- [ ] `scripts/deploy_worker.sh` (a dry run, read it), then `scripts/deploy_worker.sh --apply`. It prints
+      an address. **Do not share it yet.** Until Part 7b it answers 503 to every request.
@@ Part 7 (after the session-length bullet)
+- [ ] **7b.** Zero Trust, Access controls, Applications, open this Worker's application and copy the
+      **Application Audience (AUD) Tag**. Put it and your team name in `worker/deploy.conf`
+      (`ACCESS_AUD=`, `ACCESS_TEAM_DOMAIN=`), then run `scripts/deploy_worker.sh --apply` again.
```

**`docs/index.html` / `docs/manifest.json`** (the other session): `crossorigin="use-credentials"` on the manifest link
and relative manifest paths, as `HOSTING_OPTIONS` section 3 already lists; optionally SRI on the two unpkg tags.

---

## 10. Sources read on 2026-09-21

Vendor documentation unless marked.

- Workers Free limits (100,000 requests a day, 10 ms CPU, 50 subrequests, 128 MB, 20,000 assets, 25 MiB per asset; waiting on I/O is not CPU):
  https://developers.cloudflare.com/workers/platform/limits/
- Static assets binding, `run_worker_first` boolean and array forms, `env.ASSETS.fetch`, `assets.directory` and `binding`:
  https://developers.cloudflare.com/workers/static-assets/binding/
- Static assets billing (requests free and unlimited; `run_worker_first` requests are billable invocations and over the free limit get a 429):
  https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/
- Wrangler configuration keys (`workers_dev` default true, `preview_urls` default follows it, `routes` with `custom_domain`, `vars`, `r2_buckets`, `assets`, `observability`, `account_id` or `CLOUDFLARE_ACCOUNT_ID`):
  https://developers.cloudflare.com/workers/wrangler/configuration/
- Wrangler `deploy` flags, `--dry-run` needs no login, `rollback`, `secret put`:
  https://developers.cloudflare.com/workers/wrangler/commands/workers/
- Wrangler `whoami --json`, `login`, `CLOUDFLARE_API_TOKEN` precedence:
  https://developers.cloudflare.com/workers/wrangler/commands/general/
- R2 Workers API (`get` with `onlyIf` and `range`, object without body on failed precondition, `head`, `httpEtag`):
  https://developers.cloudflare.com/r2/api/workers/workers-api-reference/ and
  https://developers.cloudflare.com/r2/api/workers/workers-api-usage/
- R2 pricing (10 GB-month, 1 million Class A, 10 million Class B, free egress; GetObject, HeadObject are Class B; PutObject, ListObjects Class A):
  https://developers.cloudflare.com/r2/pricing/
- R2 buckets private by default, public only by r2.dev toggle or custom domain:
  https://developers.cloudflare.com/r2/buckets/public-buckets/
- Access JWT validation (header `Cf-Access-Jwt-Assertion`, certs URL, `keys` JWK array with `kid kty alg use e n`, RS256, rotation every 6 weeks with two keys valid, `aud` `iss` `email`):
  https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- Access application token claims (example payload; service tokens carry `common_name` and no `email`):
  https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/application-token/
- Access on a Worker (steps, covers `workers.dev`, custom domains and previews, `ctx.access`, no JWT parsing required):
  https://developers.cloudflare.com/workers/configuration/cloudflare-access/ and
  https://developers.cloudflare.com/changelog/post/2026-08-14-workers-access/
- Access service tokens (`CF-Access-Client-Id`, `CF-Access-Client-Secret`, Service Auth policy, secret shown once, delete to revoke):
  https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/
- OpenStreetMap Tile Usage Policy, "Do not send no-referrer" (via search summary of the OSM Foundation page, Leaflet issue 10156 and pull request 9883):
  https://operations.osmfoundation.org/policies/tiles/
