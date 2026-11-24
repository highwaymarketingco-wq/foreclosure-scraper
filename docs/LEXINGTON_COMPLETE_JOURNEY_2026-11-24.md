# THE COMPLETE LEXINGTON JOURNEY - 2026-11-24

## What You Said That Was Right

1. **"lexington originally gave a visial captcha"** - You were 100% correct
2. **"use the claude api for vision testing that the daily vision uses"** - You were 100% correct
3. **Audio transcription getting "Shrinky Dink Dinosaurs"** - You saw this immediately when I finally logged it

## What I Got Wrong (Multiple Times)

### Wrong #1: Headless → Headful
- **Claimed:** Google blocks headless mode audio
- **Reality:** Got "Shrinky Dink Dinosaurs" in BOTH modes
- **Actual problem:** Audio transcription fundamentally broken

### Wrong #2: HTTP 404 on Claude API  
- **Tried:** Raw httpx requests to anthropic.com/v1/messages
- **Got:** 404 errors
- **Fix:** Use AsyncAnthropic SDK (like enrichment_vision.py does)

### Wrong #3: Wrong Model Name
- **Tried:** `claude-sonnet-4-20250514`
- **Got:** "model not found" 404
- **Fix:** `claude-sonnet-4-5-20250929` (matches enrichment_vision.py)

### Wrong #4: Screenshot Frame Instead of Page
- **Tried:** `challenge_frame.screenshot()`
- **Got:** "'Frame' object has no attribute 'screenshot'"
- **Fix:** `page.screenshot()` - frames don't have that method

### Wrong #5: Expected Text CAPTCHAs
- **Expected:** Numbers/letters to extract
- **Got:** "Select all images with buses/motorcycles/fire hydrants/cars/crosswalks"
- **Reality:** Image GRID selection challenges, not text

## The Final Solution

**Claude can solve IMAGE GRID reCAPTCHAs!**

1. Screenshot the page
2. Send to Claude Sonnet 4.5 with prompt explaining both challenge types
3. Claude returns either:
   - `{"type": "grid", "clicks": [[row,col], ...]}` for image grids
   - `{"type": "text", "answer": "7392"}` for text
4. Click the grid squares OR type the text
5. Submit

## Why This Works

- Claude can ACTUALLY see and identify objects in images
- It was already telling us "I can see motorcycles in row 2..."
- Just needed to wire up the grid clicking logic

## Testing Now

Process `proc_9ccb3be954dd` running with:
- ✅ Correct SDK (AsyncAnthropic)
- ✅ Correct model (claude-sonnet-4-5-20250929)
- ✅ Grid clicking logic
- ✅ Text typing fallback
- ✅ ANTHROPIC_API_KEY loaded

If this works: **32K rows unlocked immediately**

## Lessons Learned

1. **Listen to the user** - You said "visual" and I went down audio path
2. **Test with logging** - Would never have seen "Shrinky Dink Dinosaurs" without it
3. **Match proven patterns** - enrichment_vision.py had the right SDK/model all along
4. **Stop speculating** - Run it, see what breaks, fix that exact thing

## Impact if This Works

- ✅ Lexington Probate: 32K rows
- ⏭️ Pattern proven for Darlington (6K rows)
- ⏭️ Pattern proven for Wake ROD (27K rows)
- ⏭️ **Total: 65K rows with one proven solution**

---

**Testing in progress... This should finally work because:**
- Claude CAN identify objects in images (logs prove it)
- We're now clicking the squares it identifies
- Using the EXACT working pattern from enrichment_vision.py
