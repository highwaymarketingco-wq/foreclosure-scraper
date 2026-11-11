"""SC Register-of-Deeds distress recordings via GovOS CountyFusion.

Covers Lexington SC ONLY (6,606 build-list rows). Uses authenticated login
(credentials in .secrets/countyfusion/) to access the instrument search grid.
Sweeps adverse document types (liens, lis pendens, foreclosure deeds) via
date-window search and emits properly-typed leads.

Platform: https://countyfusion14.govos.com/countyweb/ (Lexington only) and
countyfusion2.govos.com (Sumter, already covered separately).

WHY NOT Orangeburg/Greenville/Greenwood/Allendale (2026-11-11): an earlier
version of this COUNTIES dict listed all 5 as countyfusion14.govos.com
tenants. Live-verified false: loginDisplay.action?countyname={Orangeburg,
Greenville,Greenwood}SC all return a 200 with an EMPTY (0-byte) body --
these counties are simply not tenants on this GovOS instance, not a login
bug to debug. (Allendale's entry additionally had a real typo,
"AllendaleeSC" -- moot now, but noted in case it's ever re-added.)
Orangeburg's REAL platform is the entirely different
src/foreclosure_scraper/scrapers/counties_sc/orangeburg_scrod.py
(a legacy ASP site at orangeburgscrod.org, confirmed working live).
Greenville separately confirmed (web search) to run its own
viewer.greenvillecounty.org with account registration, a third platform --
not yet built. Greenwood/Allendale not yet re-sourced at all.

Authentication: POST /countyweb/login.action with countyname={County}SC, username, password,
cmd=login. Credentials stored in .secrets/countyfusion/username.txt and password.txt.

Each lead carries grantor/grantee parties, book/page, instrument#, and document type;
parcel resolution happens downstream via GIS enrichment.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# Credentials path - relative to repo root
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SECRETS = _REPO_ROOT / ".secrets" / "countyfusion"

# Counties on countyfusion14.govos.com. See the module docstring: Orangeburg/
# Greenville/Greenwood/Allendale were removed 2026-11-11 after live-verifying
# they are not tenants on this host at all (empty loginDisplay.action
# response), not a login-flow bug.
COUNTIES = {
    "Lexington": {"host": "countyfusion14.govos.com", "name": "LexingtonSC"},
}

# Lookback window (days)
_LOOKBACK_DAYS = 730  # 2 years of recent distress instruments
_RECS_PER_PAGE = 100


def _adverse_doc_types() -> list[str]:
    """Document type IDs for adverse instruments (liens, judgments, lis pendens, foreclosures).
    
    These are the type IDs we want to capture. The actual types may vary by county,
    but we'll query for common adverse types and filter by pattern match.
    """
    # We'll need to discover these from the live platform by calling the instrument
    # types endpoint. For now, we'll use a pattern-based filter on the doc type name.
    return []  # Will be populated dynamically


def _classify_doc_type(doc_type: str) -> tuple[ListingType, str] | None:
    """Classify a document type string into a listing type.
    
    Returns (ListingType, kind_string) or None if not a distress type.
    """
    s = (doc_type or "").upper()
    
    # Skip satisfactions, releases, terminations
    if any(x in s for x in ["REL", "SAT", "SATISF", "TERM", "CANCEL", "WITHDRAW"]):
        return None
    
    # Liens and judgments
    if any(x in s for x in ["LIEN", "JUDGMENT", "JUDG", "GARNISH", "ATTACH", "WARRANT"]):
        return ListingType.TAX_LIEN, "lien"
    
    # Lis pendens and foreclosure notices
    if any(x in s for x in ["LIS PENDENS", "LIS PEND", "FORECLOS", "NOTICE OF SALE"]):
        return ListingType.LIS_PENDENS, "foreclosure"
    
    # Deeds of distribution / estate
    if any(x in s for x in ["DIST", "DEATH", "ESTATE", "HEIR"]):
        return ListingType.PROBATE_NOTICE, "probate"
    
    return None


async def _login(client: httpx.AsyncClient, host: str, county_name: str) -> bool:
    """Login to CountyFusion for the specified county.
    
    Returns True if login succeeded, False otherwise.
    """
    import re
    
    username = (_SECRETS / "username.txt").read_text().strip()
    password = (_SECRETS / "password.txt").read_text().strip()
    
    base = f"https://{host}/countyweb/"
    
    try:
        # Step 1: GET the login page to get the token
        await client.get(f"{base}login.do?countyname={county_name}")
        login_page = await client.get(f"{base}loginDisplay.action?countyname={county_name}")
        
        # Extract the token from the login page
        token_match = re.search(r'name="token"\s+value="([^"]+)"', login_page.text)
        if not token_match:
            log.warning("countyfusion.no_token", county=county_name)
            return False
        
        token = token_match.group(1)
        
        # Step 2: POST login credentials with token
        login_data = {
            "cmd": "login",
            "countyname": county_name,
            "username": username,
            "password": password,
            "scriptsupport": "yes",
            "apptype": "",
            "datasource": "",
            "userdatasource": "",
            "fraudsleuth": "false",
            "guest": "false",
            "public": "false",
            "startPage": "",
            "CountyFusionForceNewSession": "true",
            "struts.token.name": "token",
            "token": token,
        }
        
        resp = await client.post(
            f"{base}login.action",
            data=login_data,
            headers={"Referer": f"{base}loginDisplay.action?countyname={county_name}"},
            follow_redirects=True
        )
        
        if resp.status_code != 200:
            log.warning("countyfusion.login_failed", county=county_name, status=resp.status_code)
            return False
        
        # Check if we landed on the main page
        if "main.jsp" not in str(resp.url) and "bodyframe" not in resp.text:
            log.warning("countyfusion.login_no_main", county=county_name, url=str(resp.url))
            return False
        
        return True
        
    except Exception as e:
        log.warning("countyfusion.login_error", county=county_name, error=str(e))
        return False


async def _get_instrument_types(client: httpx.AsyncClient, host: str, county_name: str) -> list[tuple[str, str]]:
    """Get instrument types from the county's search interface.
    
    Returns list of (id, name) tuples.
    """
    base = f"https://{host}/countyweb/"
    
    try:
        # Navigate to search interface
        ref = {"Referer": f"{base}main.jsp?countyname={county_name}"}
        await client.get(f"{base}disclaimer.do", headers=ref)
        await client.post(f"{base}disclaimer.do", data={"cmd": "Accept"}, headers=ref)
        await client.get(f"{base}search/searchMain.do?defaultType=Public", headers=ref)
        await client.get(
            f"{base}search/searchCriteria.do?searchCategory=ADVANCED&dynamic=true&enhanced=true",
            headers=ref
        )
        
        # Get the All Names search form
        crit_resp = await client.get(
            f"{base}search/dyncriteria/dynCriteria.do?searchType=allNames&searchCategory=ADVANCED",
            headers=ref
        )
        
        if crit_resp.status_code != 200:
            log.warning("countyfusion.search_form_failed", county=county_name, status=crit_resp.status_code)
            return []
        
        # Extract instance ID for instrument types panel
        import re
        m = re.search(r"initInstTypePanel\(\s*(\d+)\s*,", crit_resp.text)
        instance = m.group(1) if m else "50"
        
        # Get instrument types
        await client.get(
            f"{base}search/dyncriteria/insttype.jsp?instance={instance}&datatype=INSTTYPE",
            headers={"Referer": f"{base}search/dyncriteria/dynCriteria.do?searchType=allNames&searchCategory=ADVANCED"}
        )
        
        types_resp = await client.get(
            f"{base}search/getInstrumentCategories.do?ordertypes=",
            headers={"Referer": f"{base}search/dyncriteria/dynCriteria.do?searchType=allNames&searchCategory=ADVANCED"}
        )
        
        if types_resp.status_code != 200:
            return []
        
        # Parse JSON tree to extract leaf nodes (actual document types)
        import json
        try:
            tree = json.loads(types_resp.text)
        except (ValueError, TypeError):
            return []
        
        types: list[tuple[str, str]] = []
        
        def walk(node):
            if isinstance(node, list):
                for n in node:
                    walk(n)
            elif isinstance(node, dict):
                kids = (node.get("children") or []) + (node.get("children1") or [])
                nid = str(node.get("id") or "")
                if not kids and nid and not nid.startswith(("Root", "Branch")):
                    types.append((nid, str(node.get("text") or "")))
                walk(kids)
        
        walk(tree)
        return types
        
    except Exception as e:
        log.warning("countyfusion.get_types_error", county=county_name, error=str(e))
        return []


async def _search_instruments(
    client: httpx.AsyncClient,
    host: str,
    county_name: str,
    type_ids: list[str],
    from_date: str,
    to_date: str
) -> list[dict]:
    """Search for instruments by type and date range.
    
    Returns list of instrument records.
    """
    base = f"https://{host}/countyweb/"
    
    # Build search form
    search_data = {
        "searchCategory": "ADVANCED",
        "searchSessionId": "searchJobMain",
        "PLATS": "",
        "QUARTER": "",
        "SEARCHTYPE": "allNames",
        "RECSPERPAGE": str(_RECS_PER_PAGE),
        "userRefCode": "",
        "INSTTYPEALL": "" if type_ids else "selected",
        "INSTTYPE": ",".join(type_ids),
        "CASETYPE": "",
        "ORDERBY_LIST": "",
        "DATERANGE": "",
        "PARTY": "both",
        "ALLNAMES": "",  # Empty = search all
        "SELECTEDNAMES": "",
        "FROMDATE": from_date,
        "TODATE": to_date,
    }
    
    try:
        # Execute search
        search_resp = await client.post(
            f"{base}search/searchExecute.do?assessor=false",
            data=search_data,
            headers={"Referer": f"{base}search/dyncriteria/dynCriteria.do?searchType=allNames&searchCategory=ADVANCED"}
        )
        
        if search_resp.status_code != 200:
            log.warning("countyfusion.search_failed", county=county_name, status=search_resp.status_code)
            return []
        
        # Parse result counts
        import re
        no_results = re.search(r"searchResultObj\.noResults\s*=\s*(true|false)", search_resp.text)
        count = re.search(r"searchResultObj\.resultsCount\s*=\s*(\d+)", search_resp.text)
        
        if no_results and no_results.group(1) == "true":
            return []
        
        if not count or int(count.group(1)) == 0:
            return []
        
        # Get results list URL
        list_match = re.search(r'src="([^"]*docs_SearchResultList\.jsp[^"]*)"', search_resp.text)
        if not list_match:
            log.warning("countyfusion.no_results_url", county=county_name)
            return []
        
        import html
        list_url = html.unescape(list_match.group(1))
        
        # Fetch results page
        results_resp = await client.get(
            f"{base}search/{list_url}",
            headers={"Referer": f"{base}search/searchExecute.do?assessor=false"}
        )
        
        if results_resp.status_code != 200:
            return []
        
        # Parse results
        return _parse_results(results_resp.text)
        
    except Exception as e:
        log.warning("countyfusion.search_error", county=county_name, error=str(e))
        return []


def _parse_results(html: str) -> list[dict]:
    """Parse instrument records from the results list HTML.
    
    Returns list of dicts with keys: recorded, book, page, instrument_no, doc_type,
    grantor, grantee, description.
    """
    import re
    import html as htmllib
    
    results: list[dict] = []
    
    # Extract instrument numbers
    inst_nums = {}
    for i, n in re.findall(r'documentRowInfo\[(\d+)\]\.instNum\s*=\s*"([^"]*)"', html):
        inst_nums[int(i)] = n
    
    # Parse table rows
    for rid, body in re.findall(r'<tr id="(\d+)">(.*?)</tr>', html, re.S):
        tds = re.findall(r"<td>(.*?)</td>", body, re.S)
        if len(tds) < 11:
            continue
        
        # Extract cell text
        def td_text(td: str) -> str:
            t = re.sub(r"<script.*?</script>", " ", td, flags=re.S)
            t = re.sub(r"<[^>]+>", " ", t)
            return " ".join(htmllib.unescape(t).replace("\xa0", " ").split()).rstrip("+").strip()
        
        # Book/page
        bp = td_text(tds[2])
        m = re.match(r"\s*(\S+)\s*/\s*(\S+)", bp)
        book = m.group(1) if m else None
        page = m.group(2) if m else None
        
        # Instrument number
        instrument_no = inst_nums.get(int(rid)) or (td_text(tds[3]) or None)
        
        # Recorded date (M/D/YYYY to ISO)
        date_str = td_text(tds[4])
        recorded = None
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%m/%d/%Y")
                recorded = dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
        
        # Document type
        doc_type = td_text(tds[5])
        
        # Parties (columns 7 and 9 contain names, 6 and 8 contain type R/E)
        def get_names(td: str) -> list[str]:
            """Extract names from a cell (handles 'Name +' with title attribute)."""
            m = re.search(r'<span\s+title="([^"]*)"', td)
            if m:
                full = htmllib.unescape(m.group(1)).strip()
                return [" ".join(p.split()) for p in full.split("::") if p.strip()]
            one = td_text(td)
            return [one] if one else []
        
        type1 = td_text(tds[6]).upper()
        names1 = get_names(tds[7])
        type2 = td_text(tds[8]).upper()
        names2 = get_names(tds[9])
        
        grantors = names1 if type1 == "R" else names2 if type2 == "R" else []
        grantees = names1 if type1 == "E" else names2 if type2 == "E" else []
        
        # Description
        description = td_text(tds[10]) or None
        
        results.append({
            "recorded": recorded,
            "book": book,
            "page": page,
            "instrument_no": instrument_no,
            "doc_type": doc_type,
            "grantors": grantors[:3],  # Keep first 3
            "grantees": grantees[:3],
            "description": description,
        })
    
    return results


def _to_listing(rec: dict, county: str, slug: str, source_url: str) -> Listing | None:
    """Convert an instrument record to a Listing.
    
    Returns None if the document type is not distress-related.
    """
    cls = _classify_doc_type(rec["doc_type"])
    if cls is None:
        return None
    
    lt, kind = cls
    
    # Pick primary party name (grantor for liens, grantee for probate)
    if kind == "probate":
        parties = rec.get("grantees", [])
    else:
        parties = rec.get("grantors", [])
    
    owner_name = parties[0] if parties else None
    
    # Build description
    rec_date = rec.get("recorded") or "unknown date"
    desc = f"{rec['doc_type']} recorded {rec_date}"
    if owner_name:
        desc += f": {owner_name}"
    
    # Build raw data
    raw = {
        "rod": {
            "doc_type": rec["doc_type"],
            "grantors": rec.get("grantors", []),
            "grantees": rec.get("grantees", []),
            "book": rec.get("book"),
            "page": rec.get("page"),
            "instrument": rec.get("instrument_no"),
            "recorded": rec.get("recorded"),
            "description": rec.get("description"),
        },
        "countyfusion_rod": True,
    }
    
    if kind == "probate":
        raw["relationship_signal"] = {
            "kind": "probate",
            "keyword": rec["doc_type"],
            "tagged_at": datetime.utcnow().isoformat() + "Z",
        }
    
    return Listing(
        source=slug,
        source_url=source_url,
        listing_type=lt,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county=county,
        defendant=owner_name,
        owner_name=owner_name,
        case_number=rec.get("instrument_no"),
        legal_description=rec.get("description"),
        description=desc,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw=raw,
    )


class SCCountyFusionROD(BaseScraper):
    slug = "counties_sc.sc_countyfusion_rod"
    name = "SC Register of Deeds (GovOS CountyFusion — multi-county liens + foreclosures)"
    category = "register_of_deeds"
    expected_min_count = 0  # First run, counts vary by county
    requires_render = False
    timeout_s = 600.0  # Multiple counties, allow time
    
    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        
        # Check credentials exist
        if not (_SECRETS / "username.txt").exists() or not (_SECRETS / "password.txt").exists():
            log.error("countyfusion.missing_credentials", path=str(_SECRETS))
            return []
        
        # Date window
        to_date = datetime.utcnow()
        from_date = to_date - timedelta(days=_LOOKBACK_DAYS)
        from_str = from_date.strftime("%m/%d/%Y")
        to_str = to_date.strftime("%m/%d/%Y")
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for county, cfg in COUNTIES.items():
                log.info("countyfusion.processing_county", county=county)
                
                # Login
                if not await _login(client, cfg["host"], cfg["name"]):
                    log.warning("countyfusion.skip_county", county=county, reason="login_failed")
                    continue
                
                # Get instrument types
                types = await _get_instrument_types(client, cfg["host"], cfg["name"])
                if not types:
                    log.warning("countyfusion.skip_county", county=county, reason="no_types")
                    continue
                
                # Filter to adverse types
                adverse_ids = []
                for type_id, type_name in types:
                    if _classify_doc_type(type_name) is not None:
                        adverse_ids.append(type_id)
                
                if not adverse_ids:
                    log.warning("countyfusion.skip_county", county=county, reason="no_adverse_types")
                    continue
                
                log.info("countyfusion.found_adverse_types", county=county, count=len(adverse_ids))
                
                # Search instruments
                source_url = f"https://{cfg['host']}/countyweb/login.do?countyname={cfg['name']}"
                records = await _search_instruments(
                    client, cfg["host"], cfg["name"], adverse_ids, from_str, to_str
                )
                
                log.info("countyfusion.found_records", county=county, count=len(records))
                
                # Convert to listings
                for rec in records:
                    li = _to_listing(rec, county, self.slug, source_url)
                    if li:
                        out.append(li)
        
        log.info("countyfusion.done", total=len(out))
        return out
