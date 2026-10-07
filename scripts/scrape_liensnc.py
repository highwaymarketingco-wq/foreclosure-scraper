#!/usr/bin/env python3
"""Scrape all LiensNC filings via login + advanced search pagination.
1000 pages × 100 entries = ~100,000 NC lien filings.

Two modes:
    uv run python scripts/scrape_liensnc.py                    # full scrape (unchanged), /tmp output
    uv run python scripts/scrape_liensnc.py --incremental      # only filings the board lacks,
                                                               # queued for the Mac hand-off
    uv run python scripts/scrape_liensnc.py --incremental --proof --max-pages 5
                                                               # bounded check: counts only,
                                                               # writes no state
    uv run python scripts/scrape_liensnc.py --incremental --rescan-from 08/27/2026
                                                               # recovery: queue again every
                                                               # filing since then the board lacks
The incremental mode is what the Mac hand-off lane runs every cycle
(src/foreclosure_scraper/liensnc_handoff.py); see the INCREMENTAL block below."""
import httpx, asyncio, re, json, os, sys, time
from selectolax.parser import HTMLParser
from datetime import date, datetime, timedelta
from collections import Counter
from pathlib import Path

LIENSNC_USER = os.environ.get("LIENSNC_USER", "cashhigh")
LIENSNC_PASS = os.environ.get("LIENSNC_PASS", "!F8Bb8i8am$NtiZ")

OUTPUT_FILE = "/tmp/liensnc_results.json"
CHECKPOINT_FILE = "/tmp/liensnc_checkpoint.json"
BASE = "https://apps.liensnc.com"
SEARCH_URL = f"{BASE}/scr/filing/advancedSearch.html"
LOGIN_URL = f"{BASE}/scr/login.html"
AUTH_URL = f"{BASE}/scr/j_spring_security_check"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ADDR_RE = re.compile(
    r'(\d{1,5}\s+[A-Z][\w\s\.\'-]+?(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|Boulevard|Blvd\.?|Way|Place|Pl\.?|Court|Ct\.?|Highway|Hwy\.?))',
    re.MULTILINE
)
# Line-anchored variant of ADDR_RE. The "Project Property" cell commonly opens with a
# lot/subdivision label before the real site address, e.g.:
#     Lot 3 Watkins St Subdivision
#     pin 1714359804
#     1900 Watkins St Raleigh
#     Raleigh, NC 27604
# ADDR_RE.search() over the whole cell is UNANCHORED, so it matches the leftmost
# digit+suffix substring anywhere in the text -- including inside a label like "Lot 3
# Watkins St Subdivision", which reads as "3 Watkins St" and is wrong (the real site is
# "1900 Watkins St Raleigh", further down). Anchoring at the start of each line (after
# stripping) only matches a line that IS a street address, never a fragment of a longer
# label, so it skips straight past "Lot 3 Watkins St Subdivision" and "pin 1714359804"
# to "1900 Watkins St Raleigh". See _extract_address().
# The suffix must be a WHOLE word (2026-10-07): with IGNORECASE and a lazy name, a suffix
# inside a word ended the match early, so "512 Example Ln" came out "512 Exampl" ("pl" read as
# Pl) and "100 Forest Ridge Rd" "100 Forest" ("st" read as St); 1 of 50 rows on a live
# results page was cut this way.
_ADDR_LINE_RE = re.compile(
    r'^(\d{1,5}\s+[A-Z][\w\s\.\'-]+?\b(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|Boulevard|Blvd\.?|Way|Place|Pl\.?|Court|Ct\.?|Highway|Hwy\.?))(?!\w)',
    re.IGNORECASE
)
CITY_STATE_RE = re.compile(r'([A-Z][\w\s]+?),\s*(?:[A-Z]{2})?\s*(\d{5})?')
PIN_RE = re.compile(r'(?:pin|tms|parcel|tax\s*map)\s*#?\s*:?\s*([\w\-]+)', re.IGNORECASE)


def _extract_address(property_text: str) -> str:
    """Pull the numbered site address out of a LiensNC 'Project Property' cell.

    Prefers a line that, on its own (after stripping), IS a street address (digit
    at the very start of the line) over ADDR_RE's unanchored whole-text search --
    see the comment on _ADDR_LINE_RE for why the unanchored search is wrong when a
    lot/subdivision label precedes the real address. When more than one line
    qualifies, the LAST one wins: the real site address is listed closest to the
    city/state/zip line, while a lot/subdivision label with an embedded
    street-suffix-shaped name (if it matches at all) comes first. Falls back to the
    old unanchored substring search when no line matches, so cells that don't put
    the address on its own line still extract something.
    """
    candidates = [
        m.group(1).strip()
        for line in (property_text or "").split("\n")
        for m in [_ADDR_LINE_RE.match(line.strip())]
        if m
    ]
    if candidates:
        return candidates[-1]
    m = ADDR_RE.search(property_text or "")
    return m.group(1).strip() if m else ""


def parse_results(html_text):
    """Parse a page of LiensNC search results."""
    tree = HTMLParser(html_text)
    table = tree.css_first('table.table-striped')
    if not table:
        return []

    results = []
    rows = table.css('tr')
    
    for row in rows[1:]:  # skip header
        cells = row.css('td')
        if len(cells) < 5:
            continue
        
        # Cell 0: Filing type + date + entry number
        cell0 = cells[0].text(separator='\n', strip=True)
        filing_type = cell0.split('\n')[0] if cell0 else ''
        date_match = re.search(r'(\d{2}/\d{2}/\d{4})', cell0)
        filing_date = date_match.group(1) if date_match else ''
        entry_match = re.search(r'Entry\s*#:\s*(\d+)', cell0)
        entry_num = entry_match.group(1) if entry_match else ''
        
        # Cell 1: Filed by
        filed_by = cells[1].text(strip=True)
        
        # Cell 2: Project property (address, project name, etc.)
        cell2 = cells[2].text(separator='\n', strip=True)
        property_text = cell2
        
        # Cell 3: Owner info
        cell3 = cells[3].text(separator='\n', strip=True)
        owner_text = cell3
        
        # Cell 4: Active related filings
        related = cells[4].text(strip=True)
        
        # Extract address from property text
        address = _extract_address(property_text)
        
        # Extract PIN/TMS
        pin_match = PIN_RE.search(property_text)
        pin = pin_match.group(1) if pin_match else ''
        
        # Extract city/state/zip from property or owner text
        city_state = CITY_STATE_RE.search(property_text + ' ' + owner_text)
        city = city_state.group(1).strip() if city_state else ''
        zip_code = city_state.group(2) if city_state and city_state.group(2) else ''
        
        # Get detail link
        detail_link = ''
        for a in cells[0].css('a'):
            href = a.attributes.get('href', '') or ''
            if 'details.html' in href:
                detail_link = href if href.startswith('http') else f"{BASE}{href}"
                break
        
        result = {
            'entry_number': entry_num,
            'filing_type': filing_type,
            'filing_date': filing_date,
            'filed_by': filed_by,
            'property_text': property_text[:500],
            'owner_text': owner_text[:500],
            'address': address,
            'pin': pin,
            'city': city,
            'zip_code': zip_code,
            'related_filings': related,
            'detail_url': detail_link,
            'source': 'liensnc',
        }
        results.append(result)
    
    return results


async def scrape_all():
    all_results = []
    
    # Load checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            state = json.load(f)
            all_results = state.get('results', [])
            start_page = state.get('last_page', 0) + 1
            print(f"Resuming from page {start_page}, {len(all_results)} results already scraped")
    else:
        start_page = 1
    
    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=30) as c:
        # Login
        print("Logging in to LiensNC...")
        await c.get(LOGIN_URL)
        r = await c.post(AUTH_URL, data={
            "j_username": LIENSNC_USER,
            "j_password": LIENSNC_PASS,
        }, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": BASE,
            "Referer": LOGIN_URL,
        })
        if 'login' in str(r.url).lower():
            print(f"LOGIN FAILED! URL: {r.url}")
            return
        print(f"Logged in! URL: {r.url}")
        
        # Search params — broad search, all dates, sorted by date desc
        params = {
            "keywords": "",
            "filingDateFrom": "01/01/2010",
            "filingDateTo": "12/31/2026",
            "sort": "FILING_DATE",
            "sortDesc": "true",
            "pager.middleButtonsCount": "10",
            "showResults": "1",
        }
        
        total_pages = 1000  # confirmed from Last link
        consecutive_empty = 0
        
        for page_num in range(start_page, total_pages + 1):
            params["currentPage"] = str(page_num)
            
            try:
                r = await c.get(SEARCH_URL, params=params)
                text = r.content.decode('utf-8', errors='replace')
            except Exception as e:
                print(f"  Page {page_num}: ERROR - {e}, retrying in 3s...")
                await asyncio.sleep(3)
                try:
                    r = await c.get(SEARCH_URL, params=params)
                    text = r.content.decode('utf-8', errors='replace')
                except Exception as e2:
                    print(f"  Page {page_num}: RETRY FAILED - {e2}")
                    continue
            
            # Check if redirected to login (session expired)
            if 'login' in str(r.url).lower():
                print(f"  Page {page_num}: Session expired, re-logging in...")
                await c.get(LOGIN_URL)
                await c.post(AUTH_URL, data={
                    "j_username": LIENSNC_USER,
                    "j_password": LIENSNC_PASS,
                }, headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": BASE, "Referer": LOGIN_URL})
                # Retry
                r = await c.get(SEARCH_URL, params=params)
                text = r.content.decode('utf-8', errors='replace')
            
            page_results = parse_results(text)
            all_results.extend(page_results)
            
            if len(page_results) == 0:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    print(f"  Page {page_num}: 3 consecutive empty pages, stopping")
                    break
            else:
                consecutive_empty = 0
            
            if page_num % 10 == 0 or page_num == total_pages:
                print(f"  Page {page_num}/{total_pages}: {len(page_results)} results (total: {len(all_results)})")
                # Checkpoint every 10 pages
                with open(CHECKPOINT_FILE, 'w') as f:
                    json.dump({'results': all_results, 'last_page': page_num}, f)
            
            # Rate limiting — be gentle
            await asyncio.sleep(0.3)
    
    # Final save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    # Summary
    with_addr = [r for r in all_results if r.get('address')]
    with_pin = [r for r in all_results if r.get('pin')]
    with_city = [r for r in all_results if r.get('city')]
    with_entry = [r for r in all_results if r.get('entry_number')]
    
    print(f"\n{'='*60}")
    print(f"TOTAL LIENSNC FILINGS SCRAPED: {len(all_results)}")
    print(f"  With entry #: {len(with_entry)}")
    print(f"  With address: {len(with_addr)}")
    print(f"  With PIN/TMS: {len(with_pin)}")
    print(f"  With city: {len(with_city)}")
    
    print(f"\nFiling type breakdown:")
    types = Counter(r.get('filing_type', 'Unknown') for r in all_results)
    for t, count in types.most_common(10):
        print(f"  {t}: {count}")
    
    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"{'='*60}")
    
    # Cleanup checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
    
    return all_results


# ---------------------------------------------------------------------------
# INCREMENTAL mode (2026-10-07).
#
# The full scrape above pages through everything since 2010 and was only ever run by hand,
# so the board's LiensNC rows were as old as the last manual ingest. This mode fetches only
# the filings the board does not hold yet:
#
#   window      the same advanced search, bounded with filingDateFrom (a few days before the
#               newest filing date on the board) .. today, newest first, 50 rows a page;
#   stop rule   `stop_after_known` rows in a row that the board already holds: its entry
#               number is on the board, or it was filed before `known_cutoff` (the full
#               scrape covered everything older). Rows already handed off but not on the
#               board yet (`neutral_ids`) and rows seen earlier in the same scan neither stop
#               nor restart the count. Also stops at the end of the results or at a cap;
#   resume      a capped or interrupted scan keeps data/liensnc/incremental_checkpoint.json
#               (the full scrape's {results, last_page} plus the window it scans) and the
#               next call continues it instead of starting over. data/ is git-ignored and,
#               unlike /tmp, survives a reboot. New filings only push rows DOWN the
#               newest-first list, so a resumed page can repeat rows but never skip one;
#   politeness  at least MIN_DELAY_S between the starts of any two requests (login
#               included), the browser User-Agent above, one re-login per scan at most and
#               one retry of a failed page;
#   failures    a refused login raises LoginFailed at once (no retry), a CAPTCHA raises
#               CaptchaSeen (nothing tries to solve it); both stop the scan.
# ---------------------------------------------------------------------------

MIN_DELAY_S = 1.6
PAGE_SIZE = 50
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "liensnc"
INCREMENTAL_CHECKPOINT = STATE_DIR / "incremental_checkpoint.json"
_PAGES_RE = re.compile(r"\(\s*([\d,]+)\s+pages?\s*\)", re.I)
_CAPTCHA_RE = re.compile(r"g-recaptcha|hcaptcha|cf-turnstile|captcha", re.I)


class LoginFailed(RuntimeError):
    """The site sent the login page back. Never retried in the same run."""


class CaptchaSeen(RuntimeError):
    """The site served a CAPTCHA. The scan stops; nothing tries to solve it."""


class SessionLost(RuntimeError):
    """The session expired again after the one re-login a scan allows."""


class Pacer:
    """At least `interval` seconds (never under MIN_DELAY_S) between the starts of any two
    requests. Call wait() right before each request."""

    def __init__(self, interval: float = MIN_DELAY_S, *, clock=time.monotonic,
                 sleep=asyncio.sleep):
        self.interval = max(float(interval), MIN_DELAY_S)
        self._clock, self._sleep, self._last = clock, sleep, None

    async def wait(self) -> None:
        if self._last is not None:
            gap = self.interval - (self._clock() - self._last)
            if gap > 0:
                await self._sleep(gap)
        self._last = self._clock()


def page_count(html_text: str) -> int | None:
    """The '(246 pages)' note under the pager, or None."""
    m = _PAGES_RE.search(html_text or "")
    return int(m.group(1).replace(",", "")) if m else None


def mdy(s) -> date | None:
    try:
        return datetime.strptime(str(s or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def search_params(since: str, until: str, page: int) -> dict:
    """The full scrape's query, bounded to a filing-date window (MM/DD/YYYY)."""
    return {
        "keywords": "",
        "filingDateFrom": since,
        "filingDateTo": until,
        "sort": "FILING_DATE",
        "sortDesc": "true",
        "pager.middleButtonsCount": "10",
        "showResults": "1",
        "currentPage": str(page),
    }


async def login(c, *, pacer: Pacer | None = None) -> None:
    """One login with the account at the top of this file. Raises LoginFailed or CaptchaSeen;
    the messages never carry the account."""
    pacer = pacer or Pacer()
    await pacer.wait()
    r0 = await c.get(LOGIN_URL)
    if _CAPTCHA_RE.search(r0.text or ""):
        raise CaptchaSeen("CAPTCHA on the LiensNC login page")
    await pacer.wait()
    r = await c.post(AUTH_URL, data={
        "j_username": LIENSNC_USER,
        "j_password": LIENSNC_PASS,
    }, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": BASE,
        "Referer": LOGIN_URL,
    })
    if "login" in str(r.url).lower():
        if _CAPTCHA_RE.search(r.text or ""):
            raise CaptchaSeen("CAPTCHA after the LiensNC login post")
        raise LoginFailed(
            "LiensNC login failed: the site sent the login page back. Check the account "
            "(LIENSNC_USER / LIENSNC_PASS, or the script default). Not retried this run.")


def load_checkpoint(path) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        st = json.loads(p.read_text())
    except Exception:  # noqa: BLE001 - a torn checkpoint means start over, not crash
        return None
    if not isinstance(st, dict) or st.get("mode") != "incremental" or not st.get("since"):
        return None
    return st


def save_checkpoint(path, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(p)


async def scan_incremental(get_page, *, board_ids, known_cutoff: date | None, since: str,
                           until: str, neutral_ids=(), stop_after_known: int = 100,
                           max_pages: int = 300, max_seconds: float | None = None,
                           page_size: int = PAGE_SIZE, checkpoint_path=None,
                           checkpoint_every: int = 10, clock=time.monotonic,
                           log=print) -> dict:
    """Walk the newest-first results and keep the filings the board does not hold.

    `get_page(page, since, until)` returns that results page's HTML (it raises SessionLost /
    CaptchaSeen, or a network error after its one retry). A checkpoint at `checkpoint_path`
    overrides `since` / `known_cutoff` and resumes after its last page. Returns counts plus
    `new` (every new filing of this scan, resumed ones included) and `complete` (False when a
    cap or an error stopped it; the checkpoint is then kept)."""
    state = load_checkpoint(checkpoint_path)
    resumed = state is not None
    if resumed:
        since = state["since"]
        until = until or state.get("until")
        known_cutoff = mdy(state.get("known_cutoff"))
        results = list(state.get("results") or [])
        page = int(state.get("last_page") or 0) + 1
        total_pages = state.get("total_pages")
        log(f"liensnc: resuming the {since} scan at page {page} ({len(results)} new so far)")
    else:
        results, page, total_pages = [], 1, None
    board_ids = board_ids if isinstance(board_ids, (set, frozenset)) else set(board_ids)
    neutral = set(neutral_ids)
    seen = {str(r.get("entry_number")) for r in results}
    new_before = len(results)
    run = fetched = 0
    last_done = page - 1
    stop, error = None, None
    t0 = clock()

    def _state() -> dict:
        return {"mode": "incremental", "since": since, "until": until,
                "known_cutoff": known_cutoff.strftime("%m/%d/%Y") if known_cutoff else None,
                "last_page": last_done, "total_pages": total_pages, "results": results,
                "saved_at": datetime.now().isoformat(timespec="seconds")}

    while True:
        if fetched >= max_pages:
            stop = "page_cap"
            break
        if max_seconds is not None and clock() - t0 >= max_seconds:
            stop = "time_cap"
            break
        try:
            html_text = await get_page(page, since, until)
        except CaptchaSeen as exc:
            stop, error = "captcha", str(exc)
            break
        except SessionLost as exc:
            stop, error = "session_lost", str(exc)
            break
        except Exception as exc:  # noqa: BLE001 - one failed page (already retried) ends the scan
            stop, error = "error", f"{type(exc).__name__}: {str(exc)[:160]}"
            break
        fetched += 1
        rows = parse_results(html_text)
        if total_pages is None:
            total_pages = page_count(html_text)
        for rec in rows:
            e = str(rec.get("entry_number") or "").strip()
            if not e or e in seen or e in neutral:
                continue          # seen this scan / already handed off: neither new nor known
            fd = mdy(rec.get("filing_date"))
            if e in board_ids or (known_cutoff and fd and fd < known_cutoff):
                run += 1
                if run >= stop_after_known:
                    break
                continue
            run = 0
            seen.add(e)
            results.append(rec)
        last_done = page
        if run >= stop_after_known:
            stop = "known_run"
            break
        if not rows:
            stop = "end_of_results"
            break
        if (total_pages and page >= total_pages) or len(rows) < page_size:
            stop = "last_page"
            break
        if checkpoint_path and fetched % checkpoint_every == 0:
            save_checkpoint(checkpoint_path, _state())
        page += 1

    complete = stop in ("known_run", "end_of_results", "last_page")
    if checkpoint_path:
        if complete:
            Path(checkpoint_path).unlink(missing_ok=True)
        else:
            save_checkpoint(checkpoint_path, _state())
    return {
        "new": results,
        "new_this_call": len(results) - new_before,
        "pages_fetched": fetched,
        "last_page": last_done,
        "total_pages": total_pages,
        "stop_reason": stop,
        "error": error,
        "complete": complete,
        "resumed": resumed,
        "since": since,
        "until": until,
        "known_cutoff": known_cutoff.strftime("%m/%d/%Y") if known_cutoff else None,
    }


async def fetch_incremental(*, board_ids, known_cutoff: date | None, since: str,
                            until: str | None = None, neutral_ids=(),
                            stop_after_known: int = 100, max_pages: int = 300,
                            max_seconds: float | None = None, delay: float = MIN_DELAY_S,
                            checkpoint_path=INCREMENTAL_CHECKPOINT, client=None,
                            pacer: Pacer | None = None, log=print) -> dict:
    """Log in once and run scan_incremental() against the live site. LoginFailed and a CAPTCHA
    on the login page propagate; everything after login is reported in the result."""
    until = until or date.today().strftime("%m/%d/%Y")
    pacer = pacer or Pacer(delay)
    own = client is None
    c = client or httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=40)
    relogins = 0
    try:
        await login(c, pacer=pacer)

        async def get_page(page: int, since_: str, until_: str) -> str:
            nonlocal relogins
            for attempt in (1, 2):
                await pacer.wait()
                try:
                    r = await c.get(SEARCH_URL, params=search_params(since_, until_, page))
                    r.raise_for_status()
                except httpx.HTTPError:
                    if attempt == 2:
                        raise
                    continue      # the one retry, paced like any other request
                text = r.content.decode("utf-8", errors="replace")
                if "login" in str(r.url).lower():
                    if _CAPTCHA_RE.search(text):
                        raise CaptchaSeen(f"CAPTCHA instead of results page {page}")
                    if relogins >= 1:
                        raise SessionLost(f"session expired again at page {page}")
                    relogins += 1
                    log(f"liensnc: session expired at page {page}; logging in again (once)")
                    await login(c, pacer=pacer)
                    continue
                if _CAPTCHA_RE.search(text):
                    raise CaptchaSeen(f"CAPTCHA on results page {page}")
                return text
            raise SessionLost(f"no results page {page} after a re-login")

        return await scan_incremental(
            get_page, board_ids=board_ids, known_cutoff=known_cutoff, since=since,
            until=until, neutral_ids=neutral_ids, stop_after_known=stop_after_known,
            max_pages=max_pages, max_seconds=max_seconds, checkpoint_path=checkpoint_path,
            log=log)
    finally:
        if own:
            await c.aclose()


def _main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--incremental", action="store_true",
                    help="only filings the board lacks, queued for the next Mac hand-off cycle")
    ap.add_argument("--proof", action="store_true",
                    help="with --incremental: count only; no checkpoint, ledger or hand-off")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--stop-after-known", type=int, default=None)
    ap.add_argument("--rescan-from", metavar="MM/DD/YYYY", default=None,
                    help="with --incremental: walk from this filing date with no stop rule and "
                         "queue again every filing the board still lacks (recovery)")
    args = ap.parse_args(argv)
    rescan = mdy(args.rescan_from) if args.rescan_from else None
    if args.rescan_from and not rescan:
        ap.error("--rescan-from takes MM/DD/YYYY")
    if not args.incremental:
        asyncio.run(scrape_all())
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from foreclosure_scraper.liensnc_handoff import run_cycle, summary_lines
    _, report = asyncio.run(run_cycle(proof=args.proof, max_pages=args.max_pages,
                                      stop_after_known=args.stop_after_known,
                                      rescan_from=rescan))
    for line in summary_lines(report):
        print(line)
    return 1 if report.get("scan", {}).get("stop_reason") in ("login_failed", "captcha") else 0


if __name__ == '__main__':
    raise SystemExit(_main())
