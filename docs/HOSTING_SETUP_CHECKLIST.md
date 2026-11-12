# Private dashboard: owner setup checklist

Written 2026-09-21. For Cash. Companion to `docs/HOSTING_OPTIONS_2026-09-21.md`, which explains
why this plan was chosen. **Nothing on this list changes the live dashboard.** The current
GitHub Pages site keeps running until you say otherwise.

Total time: about 60 to 90 minutes, split across two or three sittings. Cost expected: $0.

**About the screen names.** These steps were written from Cloudflare's documentation, not from a
logged-in screen, and Cloudflare renames menu items now and then. If a label is a little
different, pick the closest one. If you are stuck, take a screenshot and show Claude.

**Three rules.**

1. Never paste a key, token or password into a chat. Type it only where this list says
   (the Terminal `rclone config` step, or a Cloudflare page).
2. Never make the storage bucket public, never switch on its "Public access" or `r2.dev`
   address, and never attach a domain to the bucket. The Worker is the only door.
3. When you add people to the allow list, type each email address. Never use the "Email domain"
   option with `gmail.com`. That lets every Gmail user in.

---

## Part 0. Decide (5 minutes)

Write your answers on this page.

- [ ] **Card on file.** Cloudflare may ask for a payment card before it turns on R2 storage,
      and possibly for the free Zero Trust plan. You should not be charged: expected use is about
      10 percent of every free allowance, and the free Worker plan stops at its limit instead of
      billing. The repo rule says FREE only, so this is your call. Answer: yes / no
- [ ] **Web address.** Free `something.workers.dev` (no DNS work, do this first), or an address
      on a domain you already own (needs the domain on Cloudflare). Answer: workers.dev / my domain
- [ ] **Who gets in.** List every email address, one per person. Start with yours and Greg's.
      Operators later. ______________________________________
- [ ] **Login style.** Emailed 6-digit code (simplest, repeat at most monthly) or Google sign-in
      (one tap, more setup). Start with the emailed code. Answer: ______

If you answered "no" to the card, stop here and tell Claude. The fallback plan (a small server)
is in the options document.

---

## Part 1. Cloudflare account (10 minutes)

A Cloudflare account already appears to exist: `.secrets/` holds files named
`cloudflare_account_id.txt` and `cloudflare_api_token.txt`. Claude did not open them. First find
out whose account that is.

- [ ] Go to https://dash.cloudflare.com and try to log in with `highwaymarketingco@gmail.com`
      (or whichever address you think you used).
- [ ] If you get in and the account is yours: use it. Note what is already in it.
- [ ] If you have no account, choose **Sign up**. Use an email address you control long term.
      Do not use a shared or agency login that someone else could lose.
- [ ] Turn on two-step verification: profile icon (top right), My Profile, Authentication,
      Two-Factor Authentication. Use an authenticator app.
- [ ] Note your **Account ID**. It is in the address bar after `dash.cloudflare.com/`, and on the
      account home page. It is not secret, but it is needed in Part 3.

---

## Part 2. Storage bucket (10 minutes)

- [ ] Left menu: **R2 object storage** (may say "Storage and databases", then R2).
- [ ] If it says you need to add R2 to your account, follow the prompts. This is the step that may
      ask for a card. Write down what it asked for: ______________________
- [ ] Choose **Create bucket**.
- [ ] Name: `foreclosure-board`. Location: leave on automatic. Storage class: Standard.
- [ ] Open the bucket, then its **Settings**. Confirm **Public access** shows as disabled and there
      is no "Public development URL" (`r2.dev`) and no custom domain. If either is on, turn it off.

---

## Part 3. Access key for uploads (10 minutes)

The publish script uploads with a key that can touch only this bucket.

- [ ] On the **R2 object storage** overview page, under Account Details, click **Manage** next to
      API Tokens.
- [ ] **Create Account API token** (or User API token).
- [ ] Permission: **Object Read and Write**. Scope it to the bucket `foreclosure-board` only.
- [ ] Create. Cloudflare shows an **Access Key ID** and a **Secret Access Key** once. Keep the page
      open. Do not paste them anywhere except the next step.
- [ ] Open **Terminal** on the Mac. Type `rclone config` and press Return, then answer:
  - `n` (new remote)
  - name: `r2`
  - storage type: choose the S3 option (type `s3`)
  - provider: choose **Cloudflare R2 Storage**
  - env_auth: `false` (enter keys in the next step)
  - access_key_id: paste the Access Key ID
  - secret_access_key: paste the Secret Access Key
  - region: `auto`
  - endpoint: `https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com` (your Account ID from Part 1)
  - acl: `private`
  - advanced config: `n`, then keep the remote: `y`, then `q` to quit
- [ ] Check it saved: `rclone listremotes` should now show `r2:` as well as `smbteam:`.
- [ ] Close the Cloudflare key page. You cannot view the secret again; if lost, make a new key.

---

## Part 4. Login system (10 minutes)

- [ ] Left menu: **Zero Trust**. The first time, it asks you to pick a **team name** (this becomes
      `yourteam.cloudflareaccess.com`) and a **plan**. Choose the **Free** plan.
      If it asks for a card here, write that down: ______________________
- [ ] **Settings**, **Authentication**, **Login methods**. Confirm **One-time PIN** is listed.
      If not, choose **Add new**, One-time PIN, save.
- [ ] Nothing else to do here yet. The people list comes in Part 7.

---

## Part 5. First upload (Claude, with you watching, 15 minutes)

Tell Claude: "R2 is set up, the remote is `r2`, the bucket is `foreclosure-board`."

- [ ] Claude runs `PRIVATE_HOST_TARGET=r2:foreclosure-board scripts/publish_private.sh` (a dry
      run, no upload). Read the plan it prints: about 179 release files, about 199 MiB, plus
      photos.
- [ ] If the plan looks right, say "go". Claude runs it with `--apply`. Expect roughly 700 MiB the
      first time (photos), about 200 MiB on later runs.
- [ ] In Cloudflare, R2, `foreclosure-board`, Objects: you should see `current.json`, a
      `releases` folder and a `parcel_photos` folder.

---

## Part 6. Put the app online (5 minutes)

- [ ] Claude asks you to run `npx wrangler login` in Terminal. A browser page opens asking
      whether to let Wrangler use your Cloudflare account. Click **Allow**. This is the OAuth
      approval only you can give.
- [ ] Claude runs `wrangler deploy`. It prints an address like
      `https://foreclosure-board.YOURSUBDOMAIN.workers.dev`. **Do not share it yet.** It is public
      until Part 7 is finished.

---

## Part 7. Lock it (10 minutes)

- [ ] Cloudflare: **Workers and Pages**, click `foreclosure-board`, then the **Access** tab.
- [ ] Click **Protect this Worker behind Access**. Choose **All traffic** (not "Previews only").
- [ ] For the policy, choose the Cloudflare account option for now, then **Apply Access**.
- [ ] Now add the people: **Zero Trust**, **Access controls**, **Policies**, open the policy
      created for this Worker, **Include**, **Emails**, and type each address from Part 0. Save.
      Remove anything broader than that (for example an "Email domain" rule).
- [ ] Session length: leave at the default (24 hours) for the first test. Once the phone flow works,
      raise it toward one month so people sign in less often.

---

## Part 8. Test (15 minutes)

- [ ] **Locked out?** Open a **private or incognito window** and go to the address. You must see a
      Cloudflare login page, not the dashboard. If you see the dashboard, stop and tell Claude.
- [ ] Type your email. You get a 6-digit code (from `noreply@notify.cloudflare.com`; check spam).
      Enter it within 10 minutes. The dashboard should load.
- [ ] Wrong person: try an address that is not on the list. It should not get in.
- [ ] Desktop: the board loads, a card shows a photo, opening a lead works.
- [ ] iPhone in Safari: sign in, board loads, tap a lead (this loads a detail shard).
- [ ] iPhone home screen: in Safari, Share, **Add to Home Screen**. Open it from the icon. Note what
      happens on the sign-in step. **This is the one thing nobody has confirmed.** If the icon opens
      but sign-in fails or loops, tell Claude. The workaround is to use a Safari bookmark instead,
      or Google sign-in.
- [ ] Greg's phone: send him the address, watch him do it once.

---

## Part 9. Notes (CRM) carry-over (per device)

Notes and statuses live only in each browser, so the new address starts empty.

- [ ] Before the switch, on each phone and computer, open the OLD dashboard and use the new
      **Export notes** button (Claude adds it in Phase 0). Save the file.
- [ ] On the NEW address, use **Import notes** and pick that file.
- [ ] Re-add the home-screen icon for the new address.

---

## Adding and removing people

**Add:** Zero Trust, Access controls, Policies, the Worker's policy, Include, Emails, add the
address, Save. Send them the address. First login uses the emailed code.

**Remove:** delete the address from that policy, Save. Then Zero Trust, Team and resources, Users,
select the person, Action, **Revoke**. Their session ends in about a minute.

Free plan limit: 50 people. Each person who signs in uses one seat until removed.

---

## If something goes wrong

- **Locked yourself out:** Zero Trust, Access controls, Policies, add your email back.
- **The dashboard shows an old board or "no release published yet":** Claude can re-run
  `publish_private.sh --apply`. The live board only changes when `current.json` changes.
- **Undo everything:** nothing was changed on the old site. Delete the Worker and the bucket in
  Cloudflare, or just stop using the new address.
- **Costs:** Cloudflare dashboard, Billing, Notifications. Add a usage alert so a surprise cannot
  build up quietly.
