"""SC Secretary of State business dissolution scraper.

NEW SOURCE discovered 2026-11-25 by subagent gap spreadsheet investigation.

URL: https://businessfilings.sc.gov/businessfiling/Entity/Search
Status: LIVE, reCAPTCHA markup present on page load (2Captcha compatible)
Data: SC business dissolutions (~26K rows estimated)

CAPTCHA Strategy:
- reCAPTCHA v2 triggers after first search
- Solve once, reuse session for 10-30 minutes
- Search by first letter (A-Z = 26 batches)
- Cost: $3-10 total with session optimization

Fields available:
- Business name
- Entity type (LLC, Corp, etc.)
- Status (Dissolved, Withdrawn, etc.)
- Filing date / dissolution date
- Registered agent

SELECTORS CONFIRMED LIVE 2026-11-28 (form #EntitySearchForm, POST to same URL):
- Search box: input#SearchTextBox (name=EntityName)
- Search type: select#EntitySearchTypeEnumId (2=Begins With, 1=Contains, 3=Exact Match) --
  previously not set at all; now forced to "Begins With" (2) before each letter.
- Search button: button#EntitySearchButton (name=ButtonType, value=Search) -- a <button>, not
  an <input>. The old selector "button:contains('Search')" is invalid CSS (:contains is a
  jQuery extension, not supported by querySelector) and "input[value='Search']" can never
  match a <button>, so search submission was silently a no-op before this fix.
Still UNVERIFIED (no live search was executed to inspect real output): the reCAPTCHA
site-key extraction/token-injection flow, and _parse_results()'s row structure. Confirm both
against a real post-search page before relying on this scraper's output.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

import structlog
from bs4 import BeautifulSoup
from nodriver import Browser

from foreclosure_scraper.base_scraper import BaseScraper
from foreclosure_scraper.models import Listing

log = structlog.get_logger()

_BASE_URL = "https://businessfilings.sc.gov"
_SEARCH_URL = f"{_BASE_URL}/businessfiling/Entity/Search"


class ScSosBusinessDissolutionScraper(BaseScraper):
    """SC Secretary of State business dissolution records."""

    slug = "sc.sc_sos_dissolutions"
    name = "SC SOS Business Dissolutions"
    category = "business_dissolution"
    timeout_s = 1800.0  # 30 minutes for full A-Z search

    async def fetch(self) -> list[Listing]:
        """Fetch dissolved business entities by searching A-Z."""
        results: list[Listing] = []
        
        try:
            from ...enrichment_2captcha import solve_recaptcha_v2
        except ImportError:
            log.error("sc_sos.no_2captcha", note="Need enrichment_2captcha.py")
            return results

        # Import nodriver browser
        try:
            import nodriver as uc
        except ImportError:
            log.error("sc_sos.no_nodriver")
            return results

        browser: Browser | None = None
        
        try:
            # Start browser
            browser = await uc.start(headless=False)
            page = await browser.get(_SEARCH_URL)
            await page.wait(2)

            # Search strategy: A-Z first letters
            letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            session_solved = False
            
            for letter in letters:
                log.info("sc_sos.searching_letter", letter=letter)

                # Force search type to "Begins With" (value=2) -- not set by default
                await page.evaluate(
                    "var el=document.getElementById('EntitySearchTypeEnumId');"
                    "if(el){el.value='2';el.dispatchEvent(new Event('change',{bubbles:true}));}"
                )

                # Fill search box (confirmed live: input#SearchTextBox, name=EntityName)
                search_box = await page.select("#SearchTextBox, input[name='EntityName'], input[type='text']")
                if search_box:
                    await search_box.clear_input()
                    await search_box.send_keys(letter)
                    await page.wait(1)

                # Click search button (confirmed live: button#EntitySearchButton -- a <button>,
                # not an <input>; the previous selector never matched, see module docstring)
                search_btn = await page.select("#EntitySearchButton, button[name='ButtonType'][value='Search']")
                if search_btn:
                    await search_btn.click()
                    await page.wait(3)
                
                # Check for CAPTCHA
                if not session_solved:
                    frames = await page.query_selector_all("iframe")
                    recaptcha_frame = None
                    
                    for frame in frames:
                        src = await frame.get_attribute("src")
                        if src and "recaptcha" in src:
                            recaptcha_frame = frame
                            break
                    
                    if recaptcha_frame:
                        log.info("sc_sos.captcha_detected", letter=letter)
                        
                        # Get site key from iframe
                        page_url = page.url
                        site_key = None
                        
                        # Extract site key from page source
                        html = await page.get_content()
                        soup = BeautifulSoup(html, "html.parser")
                        
                        # Look for data-sitekey attribute
                        for elem in soup.find_all(attrs={"data-sitekey": True}):
                            site_key = elem.get("data-sitekey")
                            break
                        
                        if not site_key:
                            # Try to extract from iframe src
                            for iframe in soup.find_all("iframe"):
                                src = iframe.get("src", "")
                                if "recaptcha" in src and "k=" in src:
                                    match = re.search(r"[?&]k=([^&]+)", src)
                                    if match:
                                        site_key = match.group(1)
                                        break
                        
                        if site_key:
                            log.info("sc_sos.solving_captcha", site_key=site_key[:20])
                            
                            # Solve with 2Captcha
                            token = await solve_recaptcha_v2(page_url, site_key)
                            
                            if token:
                                log.info("sc_sos.captcha_solved")
                                session_solved = True
                                
                                # Inject token
                                await page.evaluate(f"""
                                    document.getElementById('g-recaptcha-response').innerHTML = '{token}';
                                    if (typeof grecaptcha !== 'undefined') {{
                                        grecaptcha.getResponse = function() {{ return '{token}'; }};
                                    }}
                                """)
                                await page.wait(2)
                                
                                # Click search again
                                if search_btn:
                                    await search_btn.click()
                                    await page.wait(3)
                            else:
                                log.warning("sc_sos.captcha_failed", letter=letter)
                                continue
                        else:
                            log.warning("sc_sos.no_site_key")
                            continue
                
                # Parse results
                html = await page.get_content()
                letter_results = self._parse_results(html, letter)
                results.extend(letter_results)
                
                log.info("sc_sos.letter_done", letter=letter, found=len(letter_results), total=len(results))
                
                # Rate limiting
                await page.wait(2)
            
            log.info("sc_sos.complete", total_results=len(results))
            
        except Exception as exc:
            log.warning("sc_sos.fetch_failed", error=str(exc)[:300])
        finally:
            if browser:
                try:
                    await browser.stop()
                except Exception:
                    pass
        
        return results

    def _parse_results(self, html: str, search_letter: str) -> list[Listing]:
        """Parse business search results from HTML."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")
        
        # Find results table or list
        # NOTE: Actual structure needs to be inspected from live page
        # This is a template that will need adjustment
        
        # Look for table rows
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 3:  # Assuming at least: name, status, type
                try:
                    business_name = cells[0].get_text(strip=True)
                    status = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    entity_type = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                    
                    # Only include dissolved/withdrawn entities
                    if any(word in status.lower() for word in ["dissolv", "withdraw", "cancel", "revok"]):
                        listing = Listing(
                            county="Statewide",
                            state="SC",
                            listing_type="Business Dissolution",
                            case_number=business_name,  # Use as identifier
                            status=status,
                            notes=f"Entity Type: {entity_type}, Search: {search_letter}*",
                            source_url=_SEARCH_URL,
                        )
                        results.append(listing)
                        
                except Exception as exc:
                    log.debug("sc_sos.parse_row_failed", error=str(exc)[:100])
                    continue
        
        return results
