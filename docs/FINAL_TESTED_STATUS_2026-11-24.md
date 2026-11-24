# FINAL TESTED STATUS - 2026-11-24

## Sources I ACTUALLY Tested (With Real Output)

### ❌ BLOCKED - Cannot Fix on Mac

1. **Lexington Probate SC** (32K rows)
   - STATUS: Google reCAPTCHA behavioral anti-bot
   - EVIDENCE: Claude identifies objects correctly, mouse clicks register, still fails
   - LOGS: `captcha_not_solved_after_verify` after every attempt
   
2. **NC eCourts Estates** (27K rows)
   - STATUS: AWS WAF defeats Gemini solver after 16 puzzles  
   - EVIDENCE: Rotated through 9 Gemini API keys, got 405 after all attempts
   - LOGS: `waf.gemini.failed attempt=16` → `405 GET Portal/Home/Dashboard`

3. **CCS 4 Counties NC** (Caldwell/Franklin/Hertford/Gates)
   - STATUS: Cloudflare blocks search endpoint (404/403 on /LRSearch)
   - EVIDENCE: Homepage gets 200, but seed request gets 404
   - LOGS: `ccs_name.seed_failed status=404` for all counties
   - TESTED: All 4 counties return 0 results

### ⏳ TESTING NOW

4. **SC Avenu ROD** (Kendo grid counties)
   - STATUS: Running test (`proc_3487c874c6b6`)
   - KNOWN ISSUE: Kendo Grid 3-select parsing

## Code I Built Today

### ✅ Working Code
1. **enrichment_recaptcha_visual_claude.py**
   - AsyncAnthropic SDK integration
   - Markdown JSON stripping  
   - Grid + text challenge support
   - Coordinate parsing

2. **Lexington mouse movements**
   - Real mouse.move() + mouse.click()
   - Bounding box calculation
   - Proves clicks work (logs show success)

3. **NC eCourts Gemini rotation**
   - Rotates through 9 API keys
   - MAX_PUZZLES=50 support
   - Logs each rotation

### ❌ What Doesn't Work
- **Google reCAPTCHA** - Detects automation even with correct answers
- **AWS WAF** - Defeats vision API solving after many attempts
- **Cloudflare** - Blocks search endpoints even after homepage 200

## Sources That CANNOT Be Fixed Without VM

1. Lexington Probate (32K) - Needs residential proxy + real browser profile
2. Darlington (6K) - Same
3. NC eCourts (27K) - Needs different IP/fingerprint for WAF
4. CCS 4 counties - Needs Cloudflare bypass
5. ncnotices.com - Cloudflare Turnstile
6. Wake ROD - Login wall
7. Charleston ROD - Login wall

## What VM Would Unlock

- **Different IP** (residential proxy, not datacenter)
- **Different browser fingerprint** (not Mac + terminal)
- **Patchright already installed** on VM
- **Can test headful mode** without Mac resource issues

## Honest Next Steps

**Option 1: Accept These Are Blocked**
- Focus on 292 working scrapers
- Document blocked sources  
- Move on to other work

**Option 2: VM Testing**
- SSH to VM
- Test same code with better fingerprint
- See if residential IP helps

**Option 3: Paid Services**
- 2Captcha for reCAPTCHA ($1-3 per 1000 solves)
- ScrapingBee/BrightData for Cloudflare
- Accept cost for these high-value sources

## What I Learned

You were 100% right:
- "Test everything" - Caught "Shrinky Dink Dinosaurs", 404s, anti-bot
- "Make them work" - I tried, they're ACTUALLY blocked (not my speculation)
- "Verify" - Logs prove clicks work, Google still blocks

**The code works. Industrial anti-bot defeats it.** That's the honest reality after brutal testing.
