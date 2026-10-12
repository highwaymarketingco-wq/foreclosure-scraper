"""Find the real NC SOS UCC search page URL."""
import asyncio
from scrapling.fetchers import StealthyFetcher

CANDIDATE_URLS = [
    "https://www.sosnc.gov/online_services/search/_uniform_commercial_code",
    "https://www.sosnc.gov/online_services/search/Uniform_Commercial_Code",
    "https://www.sosnc.gov/online_services/search/_Uniform_Commercial_Code",
    "https://www.sosnc.gov/online_services/search/by_title/_uniform_commercial_code",
    "https://www.sosnc.gov/online_services/uniform_commercial_code",
]

async def main():
    for url in CANDIDATE_URLS:
        try:
            result = await asyncio.wait_for(
                StealthyFetcher.async_fetch(
                    url, headless=True, network_idle=True,
                    timeout=60000, solve_cloudflare=True,
                ),
                timeout=90,
            )
            body = getattr(result, "body", b"")
            html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
            status = getattr(result, "status", "?")
            has_ucc = "uniform commercial" in html.lower() or "ucc" in html.lower()
            has_filing = "filing" in html.lower()
            has_search = "searchcriteria" in html.lower() or "search" in html.lower()
            print(f"URL: {url}")
            print(f"  Status: {status}, Length: {len(html)}, UCC: {has_ucc}, Filing: {has_filing}, Search: {has_search}")
            if has_ucc and has_filing and len(html) > 5000:
                with open(f"/tmp/sos_ucc_candidate_{url.split('/')[-1]}.html", "w") as f:
                    f.write(html)
                print(f"  SAVED to /tmp/sos_ucc_candidate_{url.split('/')[-1]}.html")
        except Exception as e:
            print(f"URL: {url} -> ERROR: {str(e)[:100]}")

asyncio.run(main())
