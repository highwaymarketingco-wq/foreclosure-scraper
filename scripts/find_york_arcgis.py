"""Find ArcGIS REST service URL behind York County Experience Builder app."""
import httpx
import re
import json

url = "https://experience.arcgis.com/experience/ef9243d9330c4891ba724689f2eb1502"
r = httpx.get(url, timeout=30, follow_redirects=True)
html = r.text
print(f"HTML length: {len(html)}")

# Find all URLs
all_urls = re.findall(r'https?://[^\s"\'<>]+', html)
print(f"Total URLs found: {len(all_urls)}")

# Filter for interesting ones
for u in sorted(set(all_urls)):
    if 'arcgis' in u.lower() or 'rest' in u.lower() or 'feature' in u.lower() or 'map' in u.lower():
        print(f"  {u}")

# Look for JS bundles
js_urls = re.findall(r'src="([^"]+\.js)"', html)
print(f"\nJS bundles: {len(js_urls)}")
for u in js_urls[:5]:
    print(f"  {u}")

# The Experience Builder page is a SPA. The actual config is loaded
# via a separate API call. Try the Experience Builder config API.
exp_id = "ef9243d9330c4891ba724689f2eb1502"

# Try different config endpoints
for endpoint in [
    f"https://experience.arcgis.com/experience/{exp_id}/config.json",
    f"https://www.arcgis.com/sharing/rest/content/items/{exp_id}?f=json",
]:
    try:
        r2 = httpx.get(endpoint, timeout=30, follow_redirects=True)
        print(f"\n{endpoint}")
        print(f"  Status: {r2.status_code}")
        if r2.status_code == 200:
            try:
                data = r2.json()
                # Serialize and search for REST URLs
                ds = json.dumps(data)
                rest_urls = re.findall(r'https?://[^"\s]+/rest/services/[^"\s]+', ds)
                if rest_urls:
                    print(f"  REST URLs found: {set(rest_urls)}")
                fs_urls = re.findall(r'https?://[^"\s]+/FeatureServer[^"\s]*', ds)
                if fs_urls:
                    print(f"  FeatureServer URLs: {set(fs_urls)}")
                ms_urls = re.findall(r'https?://[^"\s]+/MapServer[^"\s]*', ds)
                if ms_urls:
                    print(f"  MapServer URLs: {set(ms_urls)}")
                # Print interesting fields
                if isinstance(data, dict):
                    print(f"  Keys: {list(data.keys())[:20]}")
                    for key in ['url', 'contentUrls', 'resources', 'type', 'title', 'description']:
                        if key in data:
                            val = str(data[key])[:200]
                            print(f"  {key}: {val}")
            except json.JSONDecodeError:
                print(f"  Not JSON. First 500 chars: {r2.text[:500]}")
        else:
            print(f"  Response: {r2.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")

# Try fetching the JS bundles and searching for REST URLs
for js_url in js_urls[:3]:
    try:
        r3 = httpx.get(js_url, timeout=30, follow_redirects=True)
        if r3.status_code == 200:
            rest_in_js = re.findall(r'https?://[^"\s\']+/rest/services/[^"\s\']+', r3.text)
            if rest_in_js:
                print(f"\nREST URLs in JS bundle ({js_url}):")
                for u in set(rest_in_js):
                    print(f"  {u}")
    except:
        pass
