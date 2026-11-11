# Tyler eCourts WAF Session Capture — Integration Guide

## Problem

nc_ecourts_estates (30,000 rows) is blocked by AWS WAF randomness. The pretoken solver works but image-grid challenges fire anyway, escalating to 20+ puzzles and timing out.

Claude's finding: "this might just be Amazon's bot-check randomly letting people through sometimes and not others, not something we're doing wrong."

**Solution:** Capture comprehensive session details when it DOES work (the "lucky moment"), then compare against failed attempts to find patterns.

## The Tool

**File:** `src/foreclosure_scraper/tyler_session_capture.py`

Captures when Tyler scraper works:
- Browser fingerprint (user-agent, viewport, headless mode)
- Network timing
- All cookies (especially `aws-waf-token`)
- Request headers
- WAF challenge events
- Success/failure outcome + row count

## How to Use

### Step 1: Enable Capture Mode

```bash
export TYLER_CAPTURE_SESSION=1
```

### Step 2: Run the Scraper

```bash
# Mac
cd /Users/cashhigh/foreclosure-scraper
PYTHONPATH=src .venv/bin/python -m foreclosure_scraper run counties_nc.nc_ecourts_estates

# VM (SSH)
ssh -i ~/Downloads/ssh-key-2026-11-10.key opc@129.146.168.104 "
  cd /home/opc/foreclosure-scraper
  source .venv/bin/activate
  export TYLER_CAPTURE_SESSION=1
  PYTHONPATH=src python -m foreclosure_scraper run counties_nc.nc_ecourts_estates
"
```

### Step 3: Check Results

Capture files saved to: `~/.foreclosure_scraper/tyler_sessions/`

- `success_TIMESTAMP.json` - worked (rows > 0)
- `failure_TIMESTAMP.json` - failed (rows = 0)

### Step 4: Compare

Run 10-20 times to collect both successes and failures, then:

```python
import json
from pathlib import Path

session_dir = Path.home() / ".foreclosure_scraper" / "tyler_sessions"

successes = [json.load(open(f)) for f in session_dir.glob("success_*.json")]
failures = [json.load(open(f)) for f in session_dir.glob("failure_*.json")]

print(f"Successes: {len(successes)}, Failures: {len(failures)}")

# Compare patterns
if successes and failures:
    # Cookie differences
    success_cookies = set(c["name"] for s in successes for c in s["cookies"])
    failure_cookies = set(c["name"] for f in failures for c in f["cookies"])
    print(f"Cookies only in successes: {success_cookies - failure_cookies}")
    print(f"Cookies only in failures: {failure_cookies - success_cookies}")
    
    # Timing differences
    avg_success_time = sum(s["timing"]["total_elapsed_s"] for s in successes) / len(successes)
    avg_failure_time = sum(f["timing"]["total_elapsed_s"] for f in failures) / len(failures)
    print(f"Avg success time: {avg_success_time:.1f}s, Avg failure time: {avg_failure_time:.1f}s")
    
    # WAF event counts
    success_waf_events = sum(len(s["waf_events"]) for s in successes) / len(successes)
    failure_waf_events = sum(len(f["waf_events"]) for f in failures) / len(failures)
    print(f"Avg WAF events (success): {success_waf_events:.1f}, (failure): {failure_waf_events:.1f}")
```

## Integration into nc_ecourts_estates.py

The scraper needs to call the capture tool at key points. Add to `nc_ecourts_estates.py`:

```python
from foreclosure_scraper.tyler_session_capture import get_capture

async def fetch(self) -> list[Listing]:
    capture = get_capture()
    
    # Log browser launch
    capture.log_browser_launch(headless=True, user_agent=..., viewport=...)
    
    # Log pretoken
    pretoken = await tyler_waf_token.fetch_waf_token(...)
    capture.log_pretoken(pretoken, solved=pretoken is not None)
    
    # Log page load
    t0 = time.time()
    await page.goto(url)
    capture.log_page_load(url, status=200, timing_ms=(time.time()-t0)*1000)
    
    # Log WAF challenges
    if waf_detected:
        capture.log_waf_challenge("image-grid", solved=..., elapsed_s=...)
    
    # Log cookies
    cookies = await page.context.cookies()
    capture.log_cookies(cookies)
    
    # Log outcome
    capture.log_outcome(success=len(results) > 0, rows_fetched=len(results))
    
    return results
```

## What to Look For

### Indicators of Success Pattern

1. **aws-waf-token differences:** Successful sessions might have different token structure
2. **Timing windows:** Success might correlate with specific timing gaps between requests
3. **Challenge count:** Fewer WAF events = success?
4. **Cookie order:** Sometimes cookie presentation order matters for bot detection
5. **Request header variations:** User-Agent, Accept-Language, etc.

### Next Actions After Finding Pattern

If pattern found → update `nc_ecourts_estates.py` or `tyler_waf_token.py` to replicate it  
If no pattern → Accept AWS WAF is truly random, document as unfixable, move on

## Current Status

- ✅ Capture tool built (`tyler_session_capture.py`)
- 🔄 Integration into `nc_ecourts_estates.py` pending
- 🔄 Data collection pending
- ⏸️ Pattern analysis pending

**Next:** Integrate capture calls into nc_ecourts_estates.py, then run 20× on VM to collect data.
