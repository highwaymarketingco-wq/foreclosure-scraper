"""Minimal nodriver test — find the correct API for snap Chromium on VM."""
import asyncio
import nodriver as uc


async def test_kwargs():
    """Test 1: uc.start() with kwargs (like start_browser does)."""
    print("\n=== Test 1: uc.start() with kwargs ===")
    try:
        browser = await uc.start(
            headless=False,
            sandbox=False,
            browser_executable_path="/snap/bin/chromium",
            browser_args=["--headless=new", "--disable-gpu"],
        )
        print("BROWSER STARTED OK")
        page = await browser.get("about:blank")
        content = await page.get_content()
        print(f"Content length: {len(content)}")
        browser.stop()
        print("DONE")
    except Exception as e:
        print(f"ERROR: {e}")


async def test_config():
    """Test 2: uc.start(config) with Config object."""
    print("\n=== Test 2: uc.start(config) ===")
    try:
        config = uc.Config(sandbox=False, headless=False)
        config.add_argument("--disable-gpu")
        browser = await uc.start(config)
        print("BROWSER STARTED OK")
        page = await browser.get("about:blank")
        content = await page.get_content()
        print(f"Content length: {len(content)}")
        browser.stop()
        print("DONE")
    except Exception as e:
        print(f"ERROR: {e}")


async def test_config_headless():
    """Test 3: Config with headless=True."""
    print("\n=== Test 3: Config headless=True ===")
    try:
        config = uc.Config(sandbox=False, headless=True)
        config.add_argument("--disable-gpu")
        browser = await uc.start(config)
        print("BROWSER STARTED OK")
        page = await browser.get("about:blank")
        content = await page.get_content()
        print(f"Content length: {len(content)}")
        browser.stop()
        print("DONE")
    except Exception as e:
        print(f"ERROR: {e}")


async def test_start_browser():
    """Test 4: Use production start_browser()."""
    print("\n=== Test 4: production start_browser() ===")
    try:
        from foreclosure_scraper.browser_utils import start_browser
        browser = await start_browser(headless=False)
        print("BROWSER STARTED OK")
        page = await browser.get("about:blank")
        content = await page.get_content()
        print(f"Content length: {len(content)}")
        browser.stop()
        print("DONE")
    except Exception as e:
        print(f"ERROR: {e}")


async def main():
    await test_kwargs()
    await test_config()
    await test_config_headless()
    await test_start_browser()


if __name__ == "__main__":
    asyncio.run(main())
