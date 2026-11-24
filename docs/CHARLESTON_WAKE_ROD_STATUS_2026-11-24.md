# Charleston/Wake ROD — investigated 2026-11-24

Hermes's punch list (`ACTUAL_WALLED_PUNCH_LIST.md` #7) called this "new
scrapers, never built... CAPTCHA-gated." That's half right — more precise
findings below for whoever builds this next.

## Charleston County ROD — the search form itself has NO CAPTCHA; the
results viewer does, and it's a harder variant than Lexington/Darlington

- The county's own name/date search (`https://www.charlestoncounty.gov/
  departments/rod/ds-DMNameandDateSearch.php`) is a plain server-rendered
  HTML form: `recordtype` (DM1-DM7: Grantor/Grantee/both, Mortgagor/
  Mortgagee/both, All Types=DM4), `type` (DM8/DM9/DM10: Individual/Firms/
  Both), `lastname`, `firstname`, `rmcfrom`/`rmcto` (date range, HTML5 date
  inputs), `agreelegal` (required disclaimer checkbox), `test=1` (hidden,
  fixed value, not a challenge). No login, no visible CAPTCHA on this page.
- A plain POST to that same URL (no browser, no session prep beyond the
  form fields above) **works on the first try** -- confirmed live, returns
  `window.open('https://docviewer.charlestoncounty.gov/ROD/Index?postData=
  <opaque-token>', '_self')`. Same "opaque encrypted redirect token" pattern
  already seen this session (Greenville probate's `?q=...`, Charleston's own
  disclaimer-gated flow elsewhere).
- Following that token to `docviewer.charlestoncounty.gov` is where the
  real gate is: it redirects (ASP.NET session cookie set) to a **reCAPTCHA
  Enterprise v3 "Validate" page** -- invisible, score-based, auto-submits
  via JS with no checkbox and NO audio-challenge fallback at all (confirmed
  live: the page's own copy says "Auto-Validating the request... do not
  refresh", and submits itself on page load).
- This is a genuinely harder wall than Lexington/Darlington's reCAPTCHA v2
  (which at least offers an audio challenge to solve, even though Google's
  risk engine is currently refusing that challenge too -- see
  `LEXINGTON_PROBATE_RECAPTCHA_STATUS_2026-11-24.md`). v3 Enterprise has no
  user-solvable challenge to fall back to; it just scores the session and
  either passes or silently denies. Not recommended to sink more time into
  defeating this head-on without a real browser building up a normal,
  longer-lived session history first (a one-shot script will almost always
  score low).

## Wake County ROD — can't reach it from this Mac right now, different
failure mode than a wall

- Official link chain: `wake.gov` -> `services.wakegov.com/booksweb/`
  (301) -> `http://rodcrpi.wakegov.com/booksweb/` (note: plain HTTP, not
  HTTPS, on a 2026-era system -- itself a sign this is older/internal
  infrastructure).
- That final host **connection-timed-out twice** (20s and 45s) -- not a
  403, not a CAPTCHA page, a hard TCP timeout. Could be a genuinely
  decommissioned/internal-only system still linked from wake.gov's public
  page, a slow backend that needs even longer, or something IP/network-
  specific to this Mac right now.
- Retried from the VM (different egress IP/network): different failure
  mode, same outcome -- `curl: (7) Connection refused` on port 80, in
  0.2s (not a timeout this time, an active, fast rejection). Two
  different networks (this Mac's, Oracle's cloud ASN) both can't reach
  it, by two different mechanisms (silent drop vs. active refuse) --
  consistent with the origin filtering non-residential/non-NC traffic at
  the network level, not a transient outage. Not worth more retries from
  either of these two IPs; would need a US-residential proxy to tell
  whether this is truly down or just filtering cloud/out-of-state
  traffic.

## Bottom line

- **Charleston**: real wall confirmed, harder category (reCAPTCHA
  Enterprise v3, no audio fallback). Not a quick build; needs a different
  approach than the Lexington/Darlington playbook, or deprioritize.
- **Wake**: unconfirmed -- retry from a different network before writing
  this off as walled.
