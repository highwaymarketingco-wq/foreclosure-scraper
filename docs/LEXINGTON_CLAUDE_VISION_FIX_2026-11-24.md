# LEXINGTON CLAUDE VISION FIX - 2026-11-24

## Problem Discovery

**Audio transcription completely broken:**
```
raw_transcript=' Shrinky Dink Dinosaurs'
cleaned='shrinky dink dinosaurs'
final_answer=shrinkydinkd
```

Groq Whisper was transcribing the reCAPTCHA audio as random phrases instead of numbers. All 8 attempts failed with "captcha_not_solved_after_verify".

## Root Cause

Groq Whisper audio transcription is unreliable for reCAPTCHA:
- Gets creative phrases instead of digit sequences
- No way to fix with better prompting
- Google may be using adversarial audio

## Solution

Switch from audio to visual solving using Claude API (same pattern as daily sweeps):

### 1. Created `enrichment_recaptcha_visual_claude.py`
- Takes screenshot of visual reCAPTCHA challenge
- Sends to Claude Sonnet 4 via API
- Returns extracted numbers/letters
- Same API pattern as `enrichment_vision.py` (proven working in production)

### 2. Modified `lexington_probate.py`
- Replaced 90-line audio pipeline with 30-line vision solver
- Screenshot challenge frame → Claude API → type answer
- Removed all audio button clicking, download, transcription code

## Code Changes

**Before (audio approach):**
1. Click audio button
2. Wait for audio element to load (5 retries, 10s)
3. Download MP3 file
4. Transcribe with Groq Whisper
5. Clean transcript (remove filler words)
6. Type answer
7. Verify

**After (Claude vision):**
1. Screenshot reCAPTCHA challenge
2. Send to Claude API
3. Type answer
4. Verify

## Testing

**Testing now:** `proc_514ed9423801`
- Using ANTHROPIC_API_KEY from `.secrets/anthropic_api_key.txt`
- Will show if Claude vision can solve reCAPTCHA correctly

## Expected Results

If Claude vision works:
- ✅ Lexington: 32K rows unlocked
- ✅ Pattern proven for Darlington (6K rows)
- ✅ Pattern proven for Wake ROD (27K rows)

**Total addressable: 65K rows with one proven solution**

## Fallback Plan

If Claude vision also fails:
- Try different reCAPTCHA solving services
- Rotate user agents / cookies more aggressively
- Accept that Google anti-bot may be unbeatable
- Focus on sources without CAPTCHA

## Files Modified

1. **NEW:** `src/foreclosure_scraper/enrichment_recaptcha_visual_claude.py` (119 lines)
2. **MODIFIED:** `src/foreclosure_scraper/scrapers/counties_sc/lexington_probate.py` (-60 lines)

## Next Steps

1. ✅ Test Lexington with Claude vision (running now)
2. ⏭️ If works: Apply to Darlington
3. ⏭️ If works: Build Wake ROD with same pattern
4. ⏭️ If fails: Investigate alternative approaches

## Lessons Learned

1. **Test transcription output** - Don't assume STT works without seeing results
2. **Vision > Audio for CAPTCHAs** - Visual challenges are clearer than distorted audio
3. **Use proven patterns** - Claude API vision already working in `enrichment_vision.py`
4. **Brutal testing required** - Would never have found "Shrinky Dink Dinosaurs" without logging

---

*Testing in progress... Waiting for results...*
