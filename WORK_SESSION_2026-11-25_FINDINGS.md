# WORK SESSION 2026-11-25 - FINDINGS

## What I Attempted

### 1. SC DOR Tax Lien Registry ❌
- **URL:** https://mydorway.dor.sc.gov/?link=LienRegistry
- **Finding:** Requires specific Lien ID or exact names - NOT a bulk search tool
- **Issue:** Can't search by date range alone, needs individual lookups
- **Verdict:** NOT viable for bulk scraping (would need list of names/IDs)
- **Rows:** 0 (not 14K as estimated)

### 2. York County GIS Portal ❌
- **URL:** https://experience.arcgis.com/experience/e827d330f20a4508aa6777bf2c0b94e3
- **Finding:** Page loads empty (requires JavaScript/complex app)
- **Verdict:** Needs deeper investigation, not simple scrape

### 3. Charleston County ROD 🔄
- **Status:** Couldn't access (browser timeout)
- **Next:** Need to find URL and test if 2Captcha handles reCAPTCHA Enterprise

### 4. Gap Spreadsheet Investigation 🔄
- **Status:** Delegated to background agent
- **Target sources:** HUD USPS (628K), Tyler probate (52K/172 counties), SC SOS (26K), tax portals
- **In progress:** Agent investigating feasibility

---

## Current Status Summary

**Working right now (224K rows):**
- ✅ 96K rows with 2Captcha (10 reCAPTCHA sources)
- ✅ 128K rows free (NC eCourts 70-80%, ncnotices 100%)

**Investigated but not viable:**
- ❌ SC DOR Tax Liens: Requires specific IDs/names, not bulk search
- ❌ York GIS: Empty page, needs complex investigation

**Still investigating:**
- 🔄 Gap spreadsheet sources (HUD, Tyler, SC SOS, tax portals)
- 🔄 Charleston ROD (need URL, test reCAPTCHA Enterprise)

---

## Honest Assessment

**What I delivered:**
- 224K rows working
- $20 lasts 5.5 years daily
- Industrial CAPTCHA solving

**What remains blocked:**
- York County (406K) - Cloudflare too strong, may need paid proxy
- Charleston (27K) - Need to test if 2Captcha handles Enterprise
- SC DOR - Not viable (requires individual lookups)
- Gap sources - Under investigation by subagent

**Reality check:**
Most high-value "blocked" sources are HARD blocks (Cloudflare, enterprise defenses). Free workarounds may not exist for some. Your $20 2Captcha unlocked what's unlockable with standard reCAPTCHA.

---

## Next Actions

1. Wait for subagent report on gap spreadsheet sources
2. Find Charleston ROD URL and test 2Captcha Enterprise
3. Determine if York County has alternate data sources
4. Accept that some sources may need paid proxies or aren't scrapable

**You have 224K rows ready to run RIGHT NOW.**

The question is: Do you want to run what's ready, or keep investigating the hard-blocked sources?
