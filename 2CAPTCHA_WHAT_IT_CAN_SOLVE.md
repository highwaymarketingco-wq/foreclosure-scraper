# 2Captcha Capabilities - What It Can Actually Solve

## ✅ What 2Captcha CAN Solve

| CAPTCHA Type | 2Captcha Support | Cost | Your Sources |
|--------------|------------------|------|--------------|
| **reCAPTCHA v2** | ✅ YES | $0.00099 | Wake, Lexington, 8 NC ROD, Darlington, **SC SOS** |
| **reCAPTCHA v3** | ✅ YES | $0.00099 | (if needed) |
| **reCAPTCHA Enterprise** | ✅ YES | $0.00299 | **Charleston ROD (27K rows)** ⭐ |
| **hCaptcha** | ✅ YES | $0.00099 | Tyler portals (maybe) |
| **AWS WAF** | ✅ YES | $0.00500 | NC eCourts (optional, have free) |
| **GeeTest** | ✅ YES | $0.00299 | (if needed) |
| **FunCaptcha** | ✅ YES | $0.00099 | (if needed) |

## ❌ What 2Captcha CANNOT Solve

| Defense Type | 2Captcha Support | Needs Instead | Your Sources |
|--------------|------------------|---------------|--------------|
| **Cloudflare Turnstile** | ❌ NO | CapSolver, proxy | **York County (406K)** ❌ |
| **Cloudflare Challenge** | ❌ NO | Residential proxy | **York County** ❌ |
| **PerimeterX** | ❌ NO | Special service | (none) |

## 🔍 Re-Assessment of Your Sources

### ✅ Charleston County ROD - 27K rows
- **Block:** reCAPTCHA Enterprise v3
- **2Captcha:** ✅ YES - supports Enterprise ($0.003 per solve)
- **Cost:** ~$1-5 total (with session reuse)
- **Verdict:** SHOULD WORK! Let me test it

### ❌ York County - 406K rows  
- **Block:** Cloudflare Turnstile/Challenge
- **2Captcha:** ❌ NO - doesn't solve Cloudflare
- **Needs:** CapSolver (~$0.002) + residential proxy (~$5-50/month)
- **Verdict:** 2Captcha won't help, needs different approach

### 🤔 SC DOR Tax Liens - 14K rows
- **Block:** NO CAPTCHA at all!
- **Issue:** Form requires specific Lien IDs or exact names
- **2Captcha:** Not applicable (no CAPTCHA to solve)
- **Verdict:** Need better search strategy (wildcard searches? common names?)

---

## ✅ REVISED PLAN - Using 2Captcha

### IMMEDIATE (Build now)
1. ✅ **SC SOS** - 26K rows, reCAPTCHA v2 ($3-10) - scraper built
2. ✅ **Charleston ROD** - 27K rows, reCAPTCHA Enterprise ($1-5) - BUILD NOW
3. 🔍 **Tyler NC** - 43K rows, test for hCaptcha/reCAPTCHA
4. 🔍 **Tyler SC** - 32K rows, test for hCaptcha/reCAPTCHA

**Potential:** 128K rows with 2Captcha ($9-30)

### WON'T WORK
- ❌ **York County** - Cloudflare blocks 2Captcha (needs CapSolver + proxy)
- 🤔 **SC DOR** - No CAPTCHA (needs search strategy, not CAPTCHA solving)

---

## 💰 Cost for 2Captcha Sources

**Charleston ROD (reCAPTCHA Enterprise):**
- 27K rows ÷ ~1000 per session = ~27 solves
- 27 × $0.003 = $0.081 (8 cents!) ✅

**SC SOS (reCAPTCHA v2):**
- 26K rows ÷ 26 letters = 26 searches
- With session reuse: ~3-5 solves × $0.00099 = $0.003-0.005 ✅

**Tyler portals (unknown):**
- IF reCAPTCHA: ~$1-5 each
- IF hCaptcha: ~$1-5 each
- Need to test first

**TOTAL: $2-15 for all 2Captcha-compatible sources** ✅

Your $20 covers everything easily!

---

## 🚀 ACTION PLAN

I'll build/test in this order:

1. **Charleston County ROD** (27K, reCAPTCHA Enterprise)
2. **Tyler NC probate** (43K, test CAPTCHA type)
3. **Tyler SC probate** (32K, test CAPTCHA type)
4. **SC SOS test** (26K, already built)

**York County:** Skip for now (Cloudflare needs different approach)
**SC DOR:** Investigate if wildcard/bulk searches possible

Sound good?
