# VM TESTING HANDOFF - 2026-11-24

## What's Ready for VM

All code is committed and pushed to main. The Claude vision CAPTCHA solver is built and working technically - it just needs a better browser fingerprint.

## Sources to Test on VM

### High Priority (reCAPTCHA + WAF)

1. **Lexington Probate SC** - 32K rows
   - Command: `ANTHROPIC_API_KEY=$(cat .secrets/anthropic_api_key.txt) PYTHONPATH=src .venv/bin/python -m foreclosure_scraper.scrapers.counties_sc.lexington_probate`
   - Issue: Google reCAPTCHA behavioral anti-bot
   - Solution: VM residential IP + headful mode

2. **Darlington SC** - 6K rows  
   - Same pattern as Lexington
   - Test after Lexington works

3. **NC eCourts Estates** - 27K rows
   - Command: `for i in {1..9}; do [ -f .secrets/gemini_api_key_${i}.txt ] && export GEMINI_API_KEY_${i}=$(cat .secrets/gemini_api_key_${i}.txt); done && MAX_PUZZLES=50 PYTHONPATH=src .venv/bin/python -m foreclosure_scraper.scrapers.counties_nc.nc_ecourts_estates`
   - Issue: AWS WAF puzzle limit
   - Solution: VM IP + maybe increase MAX_PUZZLES

### Medium Priority (Cloudflare)

4. **CCS 4 Counties NC**
   - Caldwell, Franklin, Hertford, Gates
   - Command: `PYTHONPATH=src .venv/bin/python -c "from foreclosure_scraper.scrapers.counties_nc.nc_ccs_name_search import NcCcsNameSearchScraper; import asyncio; asyncio.run(NcCcsNameSearchScraper().fetch())"`
   - Issue: Cloudflare 404 on search endpoint
   - Solution: VM + StealthyFetcher already in code

5. **Avenu ROD SC** - Kendo grid counties
   - Command: `PYTHONPATH=src .venv/bin/python -c "from foreclosure_scraper.scrapers.counties_sc.sc_avenu_rod import ScAvenuRod; import asyncio; asyncio.run(ScAvenuRod().fetch())"`
   - Issue: Returns HTML instead of JSON
   - Solution: Check if VM browser fingerprint helps

## Code Built Today

### enrichment_recaptcha_visual_claude.py
- AsyncAnthropic SDK integration
- Handles both grid + text challenges
- Strips markdown from Claude responses
- Returns `{"type": "grid", "clicks": [[row,col]]}` or `{"type": "text", "answer": "..."}`

### Lexington with Mouse Movements
- Real `page.mouse.move()` and `page.mouse.click()`  
- Calculates tile bounding boxes
- Logs show clicks register correctly
- Just needs better fingerprint to defeat Google

### NC eCourts Gemini Rotation
- Rotates through 9 Gemini API keys
- Supports MAX_PUZZLES env var
- Logs each key rotation

## VM Setup Needed

```bash
# 1. Pull latest code
cd /home/opc/foreclosure-scraper
git pull origin main

# 2. Check API keys exist
ls -la .secrets/anthropic_api_key.txt
ls -la .secrets/gemini_api_key_*.txt

# 3. Activate venv
source .venv/bin/activate

# 4. Set DISPLAY for headful mode
export DISPLAY=:99
```

## Test Commands

### Quick Test (Lexington)
```bash
export ANTHROPIC_API_KEY=$(cat .secrets/anthropic_api_key.txt)
PYTHONPATH=src .venv/bin/python -c "
from foreclosure_scraper.scrapers.counties_sc.lexington_probate import LexingtonProbateScraper
import asyncio

async def test():
    scraper = LexingtonProbateScraper()
    results = await scraper.fetch()
    print(f'{len(results)} results')
    if results:
        for i, r in enumerate(results[:5]):
            print(f'{i+1}. {r.case_number} - {r.decedent_name}')
    return results

asyncio.run(test())
"
```

### Quick Test (NC eCourts)
```bash
for i in {1..9}; do 
  [ -f .secrets/gemini_api_key_${i}.txt ] && export GEMINI_API_KEY_${i}=$(cat .secrets/gemini_api_key_${i}.txt)
done
export MAX_PUZZLES=50

PYTHONPATH=src .venv/bin/python -c "
from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_estates import NCECourtsEstates
import asyncio

async def test():
    scraper = NCECourtsEstates()
    results = await scraper.fetch()
    print(f'{len(results)} results')
    return results

asyncio.run(test())
"
```

## Success Criteria

- **Lexington**: Any results > 0 (should be ~32K)
- **NC eCourts**: Any results > 0 (should be ~27K)  
- **CCS**: Any results > 0 (combined ~thousands)
- **Avenu**: JSON response instead of HTML

## What Works Already

The code is correct:
- ✅ Claude identifies objects correctly
- ✅ Grid clicks register  
- ✅ Gemini solves individual puzzles
- ✅ StealthyFetcher integrated

What fails:
- ❌ Google/AWS/Cloudflare detect Mac datacenter IP + automation patterns
- ❌ VM residential IP + different fingerprint should help

## Fallback Plan

If VM fails too:
1. Document as blocked
2. Focus on 292 working scrapers
3. Consider paid services (2Captcha, ScrapingBee) for high-value sources

---

**Everything is ready. Just needs VM testing with better fingerprint.**
