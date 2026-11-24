# LEXINGTON CAPTCHA CHALLENGE TYPES - 2026-11-24

## Discovery

Tested Claude vision on Lexington reCAPTCHA and found it's **IMAGE GRID SELECTION** challenges, not text/number extraction:

```
- "Select all images with a bus"
- "Select all images with a fire hydrant"
- "Select all images with motorcycles"
- "Select all images with cars"
- "Select all images with crosswalks"
```

## Why Audio Was Used

**Original code switched to AUDIO** specifically to avoid image grid challenges:
- Click audio button
- Download MP3
- Transcribe numbers
- Type answer

This avoids having to identify objects in images.

## Why Audio Fails

Groq Whisper transcription is unreliable:
```
raw_transcript=' Shrinky Dink Dinosaurs'
cleaned='shrinky dink dinosaurs'
final_answer=shrinkydinkd
```

## Two Paths Forward

### Path A: Fix Audio Transcription
**Pros:**
- Already have the pipeline (button click, download, type)
- Just need better STT

**Options:**
1. Try different Whisper model/settings
2. Use OpenAI Whisper API (paid, but reliable)
3. Use AssemblyAI or similar (paid)

### Path B: Solve Image Grid with Claude
**Pros:**
- Claude can identify objects ("I can see motorcycles in row 2 col 2...")
- Already getting good descriptions

**Cons:**
- Need to click specific grid squares
- Complex logic to map Claude's answer → clicks
- May fail on ambiguous cases

**Approach:**
1. Screenshot challenge
2. Ask Claude which grid squares contain the target object
3. Parse coordinates from response
4. Click those squares
5. Submit

## Recommendation

**Try Path B first** (Claude image grid solving) because:
1. We already have Claude API working
2. Claude is proving it can identify objects correctly
3. Free (we have ANTHROPIC_API_KEY)
4. Can always fall back to Path A if it doesn't work

## Next Steps

1. Modify enrichment_recaptcha_visual_claude.py to:
   - Detect challenge type (image grid vs text)
   - Return grid coordinates for image challenges
   - Return text for text challenges

2. Modify lexington_probate.py to:
   - Parse grid coordinates from Claude
   - Click those squares
   - Submit

3. Test with real Lexington reCAPTCHA

---

**Current status: Testing needed. Claude CAN identify objects, need to wire up grid clicking.**
