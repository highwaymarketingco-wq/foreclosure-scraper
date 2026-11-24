# Lexington SC Probate reCAPTCHA — root cause found, 2026-11-24

**Not a code bug. Google's reCAPTCHA risk engine is actively blocking this
browser/traffic pattern.** Live-tested directly against
`https://www.lex-co.com/ProbateSearch/estates` today.

## What actually happens

1. Page loads fine, checkbox click lands on the anchor frame fine.
2. The challenge Google serves is an **image-select challenge** first
   (`rc-imageselect`, 35 hits in the frame HTML), not audio from the start —
   expected/normal reCAPTCHA v2 behavior.
3. Clicking the audio-challenge toggle button (`#recaptcha-audio-button`)
   *does* fire (`audio button clicked: True`, confirmed via direct JS click +
   HTML diff — frame content measurably changes, 31,966 -> 24,165 bytes).
4. But the frame that comes back afterward contains **"Try again later"** and
   **"automated queries"** — Google's standard anti-bot lockout copy
   ("Your computer or network may be sending automated queries...") — instead
   of an `<audio>` element. No `<audio>` tag, no
   `.rc-audiochallenge-tdownload-link` ever appears. That is exactly the
   `lexington_probate.no_audio_url` log line the scraper already emits, 8/8
   attempts, every run.

## Why the 2026-11-24 wait-increase fix (4s -> up to 10s across 5 retries)
didn't help, and can't

That fix targeted a *timing* theory (audio element loads slowly). The actual
failure is Google's risk engine refusing to offer a real audio challenge to
this browser/IP/traffic-pattern at all — there's nothing slow-loading to wait
longer for. `patchright` (the stealth Chromium fork already in use here,
specifically built to defeat naive headless-browser fingerprinting) still
gets this response, which is a reasonably strong signal this is **IP/traffic-
pattern reputation**, not basic automation-fingerprint detection — the kind of
signal that accumulates from repeated solve attempts against the same site
and typically needs a real cooldown period (hours-to-days) to clear, not a
code change.

## Recommendation

- **Stop attempting this scraper for a while.** Every additional failed
  attempt from the same IP likely reinforces the block rather than giving a
  fresh read on it.
- When re-tested, try from a genuinely different public IP (the VM's, not
  this Mac's) as a first, free diagnostic — if the VM gets a clean audio
  challenge where the Mac doesn't, this is IP-reputation-specific and the fix
  is "run it from wherever hasn't been flagged yet," not a code change at all.
- Not worth more engineering time right now beyond that one check. This is a
  genuine Google anti-bot wall, same category as Imperva/Incapsula CAPTCHA
  walls elsewhere in this repo — not a scraper bug.
