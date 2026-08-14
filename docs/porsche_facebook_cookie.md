# Turning on the Facebook Marketplace scraper

Facebook Marketplace has no public API, so the scraper reuses **your own
logged-in session** via a cookie. You paste the cookie once; every run after that
pulls live Marketplace listings until the cookie expires.

## Get the cookie (about 60 seconds, once)

1. In Chrome, sign in to **facebook.com**.
2. Open DevTools: `Cmd + Option + I`.
3. Go to the **Network** tab, then reload the page.
4. Click the first request to `facebook.com` in the list.
5. Under **Request Headers**, find the line that starts with `cookie:` and copy
   its whole value (it is long — starts with things like `datr=`, `c_user=`,
   `xs=`).

## Save it once

Paste it into a file the scraper reads automatically:

```bash
pbpaste > ~/.porsche_fb_cookie
```

(Or `echo 'PASTE_HERE' > ~/.porsche_fb_cookie`.) A leading `cookie:` label and
stray whitespace are stripped for you, so pasting the raw header is fine.

That's it. `fb_marketplace` is off when no cookie is present and on once the file
exists — no code change, no env var needed.

## Does it stay fresh?

Yes, with one caveat. **Every run pulls live listings** — nothing is cached, so
each refresh is current Marketplace inventory sorted cheapest-first under your
price cap.

The cookie itself is what has a lifespan. A Facebook session cookie typically
lasts **weeks to a couple of months**. It dies early only if you **log out**,
**change your password**, or Facebook expires the session. When that happens the
scraper simply logs "skipped" and returns nothing — it never errors the run.
Re-paste a fresh cookie (the 60 seconds above) and it's live again.

So: fresh data automatically on every run, with an occasional cookie re-paste
every month or two. Not daily.

## Compliance note

This reuses your personal logged-in session to read public Marketplace listings.
That is against Facebook's terms of service. It is your account and your call —
that is why the scraper ships **off** and only turns on when you place the
cookie file yourself.
