# Tyler eCourts WAF Investigation - CORRECTED

## The Real Tool (Already Deployed)

**Location:** `scripts/waf_ab_probe.py` (on VM at `/home/opc/foreclosure-scraper/scripts/`)

This is the actual A/B probe tool for Tyler eCourts AWS WAF debugging. It:
- Uses the real `nc_ecourts_estates` scraper module
- Captures full request/response headers via Playwright
- Tests headless vs non-headless browser modes
- Logs comprehensive session details (timing, events, cookies, headers)
- Saves JSON + HTML snapshot per run

## Current Test Run (2026-11-11)

**Running now on VM:**
- 10 total attempts (5 headless=true, 5 headless=false)
- Each attempt: pretoken fetch → navigate → WAF detection → capture
- Results save to: `/home/opc/foreclosure-scraper/waf_probe_results/`

**Output files per attempt:**
- `headless_{true|false}_N.json` - Full headers, timing, events, WAF verdict
- `headless_{true|false}_N.html` - DOM snapshot

## How to Use (Manual)

### Single Run
```bash
cd /home/opc/foreclosure-scraper
PYTHONPATH=src DISPLAY=:99 python scripts/waf_ab_probe.py true output_prefix
```

Args:
- `true|false` - Headless mode
- `output_prefix` - Filename prefix (creates `{prefix}.json` and `{prefix}.html`)

### Batch Collection
```bash
# Run 10 attempts, mix of headless modes
for i in {1..10}; do
  mode=$( [ $((i % 2)) -eq 0 ] && echo "true" || echo "false" )
  python scripts/waf_ab_probe.py $mode "attempt_${i}"
  sleep 5
done
```

## Analysis (After Collection)

### Check Success Rate
```bash
cd waf_probe_results
echo "=== Headless=True ==="
grep '"waf_present"' headless_true_*.json
echo "=== Headless=False ==="
grep '"waf_present"' headless_false_*.json
```

WAF present = **blocked** (bad)  
WAF not present = **bypassed** (good!)

### Compare Successful vs Failed Headers
```python
import json
from pathlib import Path

results_dir = Path("/home/opc/foreclosure-scraper/waf_probe_results")

successes = []
failures = []

for f in results_dir.glob("*.json"):
    data = json.load(open(f))
    if data.get("waf_present") == False:  # Success!
        successes.append(data)
    elif data.get("waf_present") == True:  # Failed
        failures.append(data)

print(f"Successes: {len(successes)}, Failures: {len(failures)}")

if successes:
    print("\n=== SUCCESSFUL ATTEMPTS ===")
    for s in successes:
        print(f"  Headless: {s['headless']}, Pretoken: {s['pretoken']}, Elapsed: {s['elapsed_s']}s")
        # Check for unique cookies/headers
        success_cookies = {c['name'] for r in s.get('responses', []) for c in r.get('headers', {}).get('set-cookie', '').split(';')}
        print(f"  Cookies set: {success_cookies}")

if failures:
    print("\n=== FAILED ATTEMPTS ===")
    for f in failures:
        print(f"  Headless: {f['headless']}, Pretoken: {f['pretoken']}, Elapsed: {f['elapsed_s']}s")
```

### Key Comparisons
1. **Headless mode correlation?** Do headless=false attempts bypass WAF more often?
2. **Pretoken effectiveness?** All attempts should have pretoken=True (it's enabled by default now)
3. **Timing patterns?** Do successful attempts have specific timing windows?
4. **Cookie differences?** Different `aws-waf-token` structure in success vs failure?
5. **Header variations?** User-Agent, Accept-Language, etc.

## Expected Outcomes

### Scenario 1: Headless Mode Matters
- Headless=False → WAF bypassed consistently
- Headless=True → WAF blocks consistently
- **Action:** Change scraper to use `headless=False` (like sc_public_index does)

### Scenario 2: Truly Random
- Both modes get ~50/50 success/failure
- No clear pattern in headers, cookies, or timing
- **Action:** Accept as unfixable random AWS WAF behavior, document, move on

### Scenario 3: Pattern Found
- Specific cookie value, header order, or timing correlates with success
- **Action:** Replicate that pattern in scraper code

## Current Status (2026-11-11)

- ✅ Tool discovered (was on VM, not Mac)
- ✅ Test run launched (10 attempts, 5+5 split)
- 🔄 Data collection in progress (ETA: 15-30 minutes)
- ⏸️ Analysis pending completion
- ⏸️ Scraper fix pending analysis results

## Previous Misunderstanding

I built `tyler_session_capture.py` thinking the tool didn't exist yet. That's now **deprecated** - use `waf_ab_probe.py` instead, which is simpler and already proven to work.

**Correct tool:** `scripts/waf_ab_probe.py` (this one!)  
~~Incorrect tool:~~ `src/foreclosure_scraper/tyler_session_capture.py` (ignore this)
