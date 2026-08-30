#!/usr/bin/env python3
"""Test 411.com phone lookup with curl-cffi browser impersonation."""
import re
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.venv/lib/python3.12/site-packages')

def test_411():
    from curl_cffi import requests as cc_requests
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://www.google.com/',
        'Connection': 'keep-alive',
    }
    
    url = 'https://www.411.com/name/John-Smith/Spartanburg-SC'
    r = cc_requests.get(url, headers=headers, impersonate='chrome120', timeout=20)
    print(f'411.com (curl-cffi): {r.status_code}, len={len(r.text)}')
    
    # Find phone numbers
    phones = re.findall(r'\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}', r.text)
    print(f'Phone patterns: {phones[:10]}')
    
    # Find name+phone combos
    # Look for result items
    for match in re.finditer(r'(\d{3})[-.\s](\d{3})[-.\s](\d{4})', r.text):
        ctx = r.text[max(0,match.start()-80):match.end()+30]
        # Clean up for display
        ctx_clean = re.sub(r'\s+', ' ', ctx).strip()
        print(f'  Context: {ctx_clean[:120]}')
    
    # Check if there's a "Not found" or captcha
    if 'captcha' in r.text.lower() or 'cloudflare' in r.text.lower():
        print('CAPTCHA/Cloudflare detected')
    if 'no results' in r.text.lower():
        print('No results message')
    if 'just a moment' in r.text.lower():
        print('Cloudflare challenge page')
    
    return r.text

if __name__ == '__main__':
    test_411()
