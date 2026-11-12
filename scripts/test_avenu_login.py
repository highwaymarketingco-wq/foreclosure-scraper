#!/usr/bin/env python3
"""Manual test of Avenu Insights scraper - verify login and data extraction."""
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import asyncio
import httpx
import re
import json
from datetime import datetime, timedelta


async def test_williamsburg_login_and_search():
    """Test login flow and search for Williamsburg county."""
    county = "williamsburg"
    base_url = f"https://{county}sc.avenuinsights.com"
    login_url = f"{base_url}/Public/{county}sc/Account/Login"
    
    print(f"Testing {county} county...")
    print(f"Base URL: {base_url}\n")
    
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        # Step 1: Get login page
        print("1. Fetching login page...")
        resp = await client.get(login_url)
        print(f"   Status: {resp.status_code}")
        
        # Extract CSRF token
        token_match = re.search(
            r'name="__RequestVerificationToken"[^>]+value="([^"]+)"',
            resp.text
        )
        if not token_match:
            print("   ❌ No CSRF token found!")
            return False
        
        csrf_token = token_match.group(1)
        print(f"   ✓ CSRF token: {csrf_token[:30]}...")
        
        # Step 2: Login
        print("\n2. Logging in...")
        home = os.path.expanduser("~")
        with open(f"{home}/.secrets/avenu_insights/email.txt") as f:
            email = f.read().strip()
        with open(f"{home}/.secrets/avenu_insights/password.txt") as f:
            password = f.read().strip()
        
        login_data = {
            "__RequestVerificationToken": csrf_token,
            "Email": email,
            "Password": password,
        }
        
        resp2 = await client.post(login_url, data=login_data)
        print(f"   Status: {resp2.status_code}")
        print(f"   Final URL: {resp2.url}")
        
        if "InstrumentGrid" in str(resp2.url) or "Logout" in resp2.text:
            print("   ✓ Login successful!")
        else:
            print("   ❌ Login may have failed")
            return False
        
        # Step 3: Submit search
        print("\n3. Submitting search...")
        search_url = f"{base_url}/Public/{county}sc/InstrumentGrid/Search"
        
        to_date = datetime.now()
        from_date = to_date - timedelta(days=90)
        
        search_params = {
            "FromDate": from_date.strftime("%m/%d/%Y"),
            "ToDate": to_date.strftime("%m/%d/%Y"),
            "SelectedIndexIDs": "1,2,4,5",  # DEED, MORTGAGE, JUDGEMENT, TAXLIEN
            "SearchCriteria": "0",
            "take": 100,
            "skip": 0,
            "page": 1,
            "pageSize": 100,
        }
        
        print(f"   Date range: {search_params['FromDate']} to {search_params['ToDate']}")
        resp3 = await client.post(search_url, data=search_params)
        print(f"   Status: {resp3.status_code}")
        
        try:
            data = resp3.json()
            print(f"   Response: {json.dumps(data, indent=2)[:200]}...")
        except:
            print(f"   Response (not JSON): {resp3.text[:200]}...")
        
        # Step 4: Try to read grid data
        print("\n4. Attempting to read grid data...")
        endpoints = [
            f"{base_url}/Public/{county}sc/InstrumentGrid/GridRead",
            f"{base_url}/Public/{county}sc/InstrumentGrid/GetGridData",
            f"{base_url}/Public/{county}sc/InstrumentGrid/Read",
        ]
        
        for endpoint in endpoints:
            print(f"\n   Trying: {endpoint}")
            try:
                resp4 = await client.post(
                    endpoint,
                    json={"take": 100, "skip": 0, "page": 1, "pageSize": 100}
                )
                print(f"   Status: {resp4.status_code}")
                
                if resp4.status_code == 200:
                    try:
                        data = resp4.json()
                        if "Data" in data and isinstance(data["Data"], list):
                            print(f"   ✓ Found data! Records: {len(data['Data'])}")
                            if data['Data']:
                                print(f"\n   Sample record:")
                                sample = data['Data'][0]
                                for key in ['InstrumentID', 'Act', 'Kind', 'DirectName', 'IndirectName']:
                                    print(f"     {key}: {sample.get(key)}")
                            return True
                        else:
                            print(f"   Response keys: {list(data.keys())}")
                    except:
                        print(f"   Not JSON: {resp4.text[:150]}...")
            except Exception as e:
                print(f"   Error: {str(e)[:100]}")
        
        print("\n❌ Could not find working grid data endpoint")
        print("   Manual inspection needed - check browser dev tools Network tab")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_williamsburg_login_and_search())
    sys.exit(0 if result else 1)
