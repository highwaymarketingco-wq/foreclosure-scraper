"""
Tyler eCourts - Manual CAPTCHA Solve Test

Opens Tyler in visible browser, waits for user to solve CAPTCHA,
then captures session and attempts data extraction.
"""
import asyncio
from patchright.async_api import async_playwright
import json
from datetime import datetime

async def manual_solve_test():
    print("Starting Tyler manual solve test...")
    
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=False,  # Visible so user can solve CAPTCHA
        args=['--start-maximized']
    )
    
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080}
    )
    page = await context.new_page()
    
    # Navigate to Tyler estates portal
    url = "https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29"
    print(f"\nNavigating to: {url}")
    print("⏳ Please solve the CAPTCHA if it appears...")
    
    await page.goto(url, timeout=60000)
    await page.wait_for_timeout(3000)
    
    # Check if CAPTCHA present
    title = await page.title()
    html = await page.content()
    
    if 'confirm you are human' in html.lower():
        print("\n🔴 CAPTCHA detected - waiting for you to solve it...")
        print("👉 Click 'Begin' and solve the image puzzle")
        print("   I'll detect when you're through and continue automatically")
        
        # Wait for CAPTCHA to be solved (check every 2 seconds)
        max_wait = 180  # 3 minutes
        for i in range(0, max_wait, 2):
            await page.wait_for_timeout(2000)
            current_html = await page.content()
            current_title = await page.title()
            
            if 'confirm you are human' not in current_html.lower():
                print("\n✅ CAPTCHA solved! You're through!")
                break
            
            if i % 10 == 0:
                print(f"  Still waiting... ({i}s elapsed)")
        else:
            print("\n❌ Timeout waiting for CAPTCHA solve")
            await browser.close()
            await playwright.stop()
            return
    else:
        print("\n✅ No CAPTCHA - you're already through!")
    
    # Capture session
    print("\n📸 Capturing session details...")
    cookies = await context.cookies()
    storage = await page.evaluate("""() => {
        return {
            localStorage: {...localStorage},
            sessionStorage: {...sessionStorage}
        }
    }""")
    
    session_data = {
        "timestamp": datetime.now().isoformat(),
        "url": page.url,
        "title": await page.title(),
        "cookies": cookies,
        "storage": storage,
        "user_agent": await page.evaluate("navigator.userAgent")
    }
    
    # Save session
    session_file = f"tyler_working_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(session_file, 'w') as f:
        json.dump(session_data, f, indent=2)
    print(f"💾 Session saved to: {session_file}")
    
    # Try to navigate to search
    print("\n🔍 Attempting to access estate search...")
    try:
        # Click on Estate search if visible
        await page.wait_for_timeout(2000)
        search_html = await page.content()
        
        # Look for estate/probate links
        if 'estate' in search_html.lower() or 'probate' in search_html.lower():
            print("✅ Estate section visible - you have access!")
        
        # Try to perform a simple search
        print("\n📋 Current page state:")
        print(f"  URL: {page.url}")
        print(f"  Title: {await page.title()}")
        
        # Keep browser open for manual inspection
        print("\n👀 Browser will stay open for 30 seconds so you can inspect")
        print("   Check if you can navigate to Estate Search and see records")
        await page.wait_for_timeout(30000)
        
    except Exception as e:
        print(f"\n❌ Error during search attempt: {e}")
    
    print("\n🏁 Test complete!")
    await browser.close()
    await playwright.stop()

if __name__ == "__main__":
    asyncio.run(manual_solve_test())
