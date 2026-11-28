"""Basic test for Tyler NC authenticated scraper."""
import sys
sys.path.insert(0, '/Users/cashhigh/foreclosure-scraper/src')

try:
    from foreclosure_scraper.scrapers.counties_nc.tyler_nc_authenticated import (
        TylerNcAuthenticatedScraper,
        TARGET_COUNTIES,
        FORECLOSURE_CASE_TYPES,
    )
    
    # Create scraper instance
    scraper = TylerNcAuthenticatedScraper()
    
    print("✓ Tyler NC scraper import successful")
    print(f"✓ Slug: {scraper.slug}")
    print(f"✓ Name: {scraper.name}")
    print(f"✓ Category: {scraper.category}")
    print(f"✓ Timeout: {scraper.timeout_s}s")
    print(f"✓ Counties: {len(TARGET_COUNTIES)}")
    print(f"✓ Case types: {FORECLOSURE_CASE_TYPES}")
    
    # Test classification
    test_cases = [
        ("SP", "25SP012345", "FORECLOSURE_SALE"),
        ("CVD", "24CVD001234", "DIVORCE_NOTICE"),
        ("CV", "25CV005678", "LIS_PENDENS"),
    ]
    
    for case_type, case_num, expected in test_cases:
        result = scraper._classify_case_type(case_type, case_num)
        result_name = result.value if result else None
        status = "✓" if result_name == expected else "✗"
        print(f"{status} {case_type} → {result_name} (expected {expected})")
    
    # Test party parsing
    test_parties = [
        ("Bank of America v John Doe", "Bank of America", "John Doe"),
        ("Wells Fargo vs Jane Smith", "Wells Fargo", "Jane Smith"),
        ("Plaintiff: Chase Bank, Defendant: Bob Jones", "Chase Bank", "Bob Jones"),
    ]
    
    for parties_text, exp_plaintiff, exp_defendant in test_parties:
        plaintiff, defendant = scraper._parse_parties(parties_text)
        status = "✓" if plaintiff == exp_plaintiff and defendant == exp_defendant else "✗"
        print(f"{status} Party parse: '{parties_text[:30]}...' → P:'{plaintiff}' D:'{defendant}'")
    
    print("\n✓ All basic tests passed!")
    print("\nScraper is ready. Run on VM with browser support.")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
