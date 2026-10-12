"""Debug: Cherokee SC avenuinsights login + scrape.

Login URL: https://cherokeesc.avenuinsights.com/Public/CherokeeSC/Account/Login
Email: highwaymarketingco@gmail.com
Password: [from env CHEROKEE_SC_PASSWORD]

Goal: Login, find property/foreclosure data, scrape listings.
"""
import asyncio
import os
import sys
from patchright.async_api import async_playwright

LOGIN_URL = "https://cherokeesc.avenuinsights.com/Public/CherokeeSC/Account/Login"
EMAIL = "highwaymarketingco@gmail.com"
PASSWORD = os.environ.get("CHEROKEE_SC_PASSWORD", "")

if not PASSWORD:
    print("ERROR: CHEROKEE_SC_PASSWORD env var not set")
    sys.exit(1)

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu"],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        print(f"Loading login page: {LOGIN_URL}")
        await page.goto(LOGIN_URL, timeout=60000)
        await asyncio.sleep(5)

        # Take screenshot of login page
        await page.screenshot(path="/tmp/cherokee_login.png")
        print("Login page screenshot saved")

        # Print all form fields
        fields = await page.evaluate("""() => {
            const inputs = document.querySelectorAll('input, button, [type="submit"]');
            return Array.from(inputs).map(el => ({
                tag: el.tagName,
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                placeholder: el.placeholder || '',
                text: el.innerText || el.value || ''
            }));
        }""")
        print(f"\nForm fields found: {len(fields)}")
        for f in fields:
            print(f"  {f}")

        # Find email field
        email_field = None
        for selector in [
            "input[type='email']",
            "input[name*='email' i]",
            "input[name*='Email']",
            "input[id*='email' i]",
            "input[id*='Email']",
            "input[placeholder*='email' i]",
            "input[placeholder*='Email']",
        ]:
            email_field = await page.query_selector(selector)
            if email_field:
                print(f"\nEmail field found: {selector}")
                break

        if not email_field:
            # Try all text inputs
            inputs = await page.query_selector_all("input[type='text'], input[type='email'], input:not([type])")
            for inp in inputs:
                name = await inp.get_attribute("name") or ""
                iid = await inp.get_attribute("id") or ""
                if "email" in name.lower() or "email" in iid.lower() or "user" in name.lower() or "user" in iid.lower():
                    email_field = inp
                    print(f"\nEmail field found (fallback): name={name} id={iid}")
                    break

        if not email_field:
            print("ERROR: Could not find email field")
            await page.screenshot(path="/tmp/cherokee_no_email.png")
            await browser.close()
            return

        # Find password field
        password_field = await page.query_selector("input[type='password']")
        if not password_field:
            print("ERROR: Could not find password field")
            await page.screenshot(path="/tmp/cherokee_no_password.png")
            await browser.close()
            return
        print("Password field found")

        # Fill in credentials
        await email_field.fill(EMAIL)
        await password_field.fill(PASSWORD)
        print("Credentials filled")

        # Find and click login button
        login_btn = None
        for selector in [
            "button[type='submit']",
            "input[type='submit']",
            "button[id*='login' i]",
            "button[id*='Login']",
            "button[class*='login' i]",
            "a[id*='login' i]",
            "button",
            "input[type='button']",
        ]:
            login_btn = await page.query_selector(selector)
            if login_btn:
                text = await login_btn.inner_text()
                if text and ("log" in text.lower() or "sign" in text.lower() or "submit" in text.lower()):
                    print(f"Login button found: {selector} text='{text}'")
                    break
                # If no text match, use first button
                if selector == "button":
                    print(f"Login button found (generic): {selector}")
                    break

        if not login_btn:
            print("ERROR: Could not find login button")
            await page.screenshot(path="/tmp/cherokee_no_login_btn.png")
            await browser.close()
            return

        # Click login and wait for navigation
        await login_btn.click()
        print("Login clicked, waiting for navigation...")
        await asyncio.sleep(10)

        # Check if logged in
        current_url = page.url
        print(f"\nCurrent URL after login: {current_url}")
        await page.screenshot(path="/tmp/cherokee_after_login.png")
        print("Post-login screenshot saved")

        # Check page content
        content = await page.content()
        print(f"Page content length: {len(content)}")

        # Look for error messages
        errors = await page.evaluate("""() => {
            const errs = document.querySelectorAll('.field-validation-error, .validation-summary-errors, .alert-error, .text-danger, [class*="error" i]');
            return Array.from(errs).map(e => e.innerText).filter(t => t.trim());
        }""")
        if errors:
            print(f"\nERRORS: {errors}")

        # Check if we're on a dashboard/search page
        links = await page.evaluate("""() => {
            const as = document.querySelectorAll('a');
            return Array.from(as).map(a => ({text: a.innerText.trim(), href: a.href})).filter(l => l.text && l.text.length > 1).slice(0, 30);
        }""")
        print(f"\nLinks on page ({len(links)}):")
        for l in links:
            print(f"  {l['text'][:50]} -> {l['href'][:80]}")

        # Look for property search functionality
        search_urls = [l for l in links if any(kw in l['text'].lower() or kw in l['href'].lower() for kw in ['search', 'property', 'tax', 'foreclosure', 'deed', 'record'])]
        if search_urls:
            print(f"\nSearch-related links:")
            for l in search_urls:
                print(f"  {l['text'][:50]} -> {l['href'][:80]}")

            # Click first search link
            print(f"\nNavigating to: {search_urls[0]['href']}")
            await page.goto(search_urls[0]['href'], timeout=60000)
            await asyncio.sleep(5)
            await page.screenshot(path="/tmp/cherokee_search_page.png")
            print("Search page screenshot saved")

            # Print all form fields on search page
            search_fields = await page.evaluate("""() => {
                const inputs = document.querySelectorAll('input, select, button');
                return Array.from(inputs).map(el => ({
                    tag: el.tagName,
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    text: el.innerText || el.value || ''
                }));
            }""")
            print(f"\nSearch page fields ({len(search_fields)}):")
            for f in search_fields[:20]:
                print(f"  {f}")

        # Save full page HTML
        with open("/tmp/cherokee_page.html", "w") as f:
            f.write(content)
        print("\nFull page HTML saved to /tmp/cherokee_page.html")

        await browser.close()


asyncio.run(main())
