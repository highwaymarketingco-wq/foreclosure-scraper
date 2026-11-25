#!/usr/bin/env python3
"""Quick test to verify 2Captcha integration works.

Usage:
    # Set your API key first:
    export TWOCAPTCHA_API_KEY="your_key_here"
    # OR create .secrets/2captcha_api_key.txt

    # Then run:
    PYTHONPATH=src .venv/bin/python scripts/test_2captcha_integration.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def test_2captcha_available():
    """Check if 2Captcha API key is configured."""
    print("🔍 Checking for 2Captcha API key...")
    
    has_key = bool(
        os.environ.get("TWOCAPTCHA_API_KEY") or
        os.path.exists(os.path.expanduser("~/.secrets/2captcha_api_key.txt")) or
        os.path.exists(".secrets/2captcha_api_key.txt")
    )
    
    if has_key:
        print("✅ 2Captcha API key found!")
        
        # Try to get balance
        try:
            from foreclosure_scraper.enrichment_2captcha import get_account_balance
            balance = await get_account_balance()
            print(f"💰 Account balance: ${balance:.2f}")
            
            if balance < 1.0:
                print("⚠️  Warning: Low balance. Add funds at https://2captcha.com")
            
            return True
        except Exception as exc:
            print(f"⚠️  API key found but validation failed: {exc}")
            return False
    else:
        print("❌ No 2Captcha API key found.")
        print("\nTo set up:")
        print("  1. Go to https://2captcha.com and register")
        print("  2. Add $10 deposit")
        print("  3. Copy your API key")
        print("  4. Save it:")
        print("     echo 'YOUR_KEY' > .secrets/2captcha_api_key.txt")
        print("\nOr set environment variable:")
        print("     export TWOCAPTCHA_API_KEY='your_key'")
        return False


async def test_wake_county():
    """Test Wake County scraper with 2Captcha."""
    print("\n🧪 Testing Wake County NC ROD scraper...")
    
    try:
        from foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha import NcRodCaptchaScraper
        
        print("⏳ This will take 30-60 seconds (solving CAPTCHA)...")
        scraper = NcRodCaptchaScraper()
        results = await scraper.fetch()
        
        # Count results by county
        by_county = {}
        for r in results:
            county = r.county or "unknown"
            by_county[county] = by_county.get(county, 0) + 1
        
        print(f"\n✅ Total results: {len(results)}")
        print("📊 By county:")
        for county, count in sorted(by_county.items()):
            emoji = "✅" if county.lower() == "wake" else "ℹ️"
            print(f"   {emoji} {county}: {count}")
        
        wake_count = by_county.get("Wake", 0)
        if wake_count > 0:
            print(f"\n🎉 SUCCESS! Wake County returned {wake_count} results!")
            print("   2Captcha integration is working correctly.")
            return True
        else:
            print("\n⚠️  Wake County returned 0 results.")
            print("   Either:")
            print("   - 2Captcha is not set up (see above)")
            print("   - CAPTCHA solving failed (check logs)")
            print("   - No recent distress filings (unlikely)")
            return False
            
    except Exception as exc:
        print(f"\n❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


async def test_lexington():
    """Test Lexington SC Probate scraper with 2Captcha."""
    print("\n🧪 Testing Lexington SC Probate scraper...")
    
    try:
        from foreclosure_scraper.scrapers.counties_sc.lexington_probate import LexingtonProbateScraper
        
        print("⏳ This will take 30-60 seconds (solving CAPTCHA)...")
        print("⚠️  Requires headful browser (window will open)")
        
        scraper = LexingtonProbateScraper()
        results = await scraper.fetch()
        
        print(f"\n✅ Total results: {len(results)}")
        
        if len(results) > 0:
            print(f"🎉 SUCCESS! Lexington returned {len(results)} results!")
            print("   2Captcha integration is working correctly.")
            
            # Show sample
            sample = results[0]
            print(f"\n📋 Sample result:")
            print(f"   Case: {sample.case_number}")
            print(f"   Type: {sample.listing_type}")
            print(f"   Name: {sample.defendant_name}")
            return True
        else:
            print("\n⚠️  Lexington returned 0 results.")
            print("   Either:")
            print("   - 2Captcha is not set up (see above)")
            print("   - CAPTCHA solving failed (check logs)")
            print("   - Site is down")
            return False
            
    except Exception as exc:
        print(f"\n❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("2CAPTCHA INTEGRATION TEST")
    print("=" * 60)
    
    # Test 1: Check API key
    has_key = await test_2captcha_available()
    
    if not has_key:
        print("\n" + "=" * 60)
        print("⚠️  Cannot test scrapers without 2Captcha API key.")
        print("   Set up your key first (see instructions above).")
        print("=" * 60)
        return
    
    # Test 2: Wake County (VM recommended but can try Mac)
    print("\n" + "-" * 60)
    wake_ok = await test_wake_county()
    
    # Test 3: Lexington (must be Mac, needs headful)
    print("\n" + "-" * 60)
    lex_ok = await test_lexington()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Wake County:       {'✅ PASS' if wake_ok else '❌ FAIL'}")
    print(f"Lexington Probate: {'✅ PASS' if lex_ok else '❌ FAIL'}")
    
    if wake_ok and lex_ok:
        print("\n🎉 All tests passed! 2Captcha is working correctly.")
        print("   You can now run the full scraper suite.")
    elif wake_ok or lex_ok:
        print("\n⚠️  Partial success. Check failed tests above.")
    else:
        print("\n❌ All tests failed. Check:")
        print("   1. API key is correct")
        print("   2. Account has balance")
        print("   3. Network connectivity")
        print("   4. Full logs for details")
    
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
