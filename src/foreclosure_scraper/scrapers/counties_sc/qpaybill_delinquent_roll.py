"""qPayBill county tax portals -> the SC DELINQUENT REAL-PROPERTY ROLL, with dollars.

WHY THIS SOURCE EXISTS AT ALL
    SC runs an ADMINISTRATIVE delinquent-tax sale: no lawsuit, no docket, no party
    list, no order of sale. There is nothing to read the way an NC tax-foreclosure
    docket can be read, which is why 30 of SC's 46 counties sat at zero rows while
    having configured scrapers -- the county HTML pages those scrapers point at carry
    a notice and a sale date, and the property list only appears for a few weeks a
    year, as a PDF, if at all.

    The treasurer's own PAYMENT portal does not work that way. Its search is live
    year-round, it is authoritative (it IS the tax system), and it answers the
    question the tax-sale PDFs cannot: HOW MUCH IS OWED, AND FOR HOW MANY YEARS.

WHAT A ROW CARRIES (grid columns, verified live 2026-09-10 on Barnwell)
    Notice No. | Name / Property Address | Year | Description | Identification No.
              | Type | Status | Payment Date | Amount
    Column 1 is exactly ``OWNER NAME<br/>PROPERTY ADDRESS``, so owner and situs
    split on the tag rather than by guessing where a house number starts. Column 4
    is the TMS. Column 3 is a truncated "PROP OF <prior owner>" description.

    Searching PaidStatus=Unpaid + SearchType=RealEstate + Year=All therefore yields,
    per parcel, every unpaid year -- and a parcel appearing for two or more years is
    the two-year-plus delinquency this engine already scores as strong distress.

ENUMERATION: PAGE FOR BREADTH, THEN DEEPEN FOR CORRECTNESS
    Map Number and Property Address search require EXACT values -- prefix queries on
    both return zero rows (measured). Owner Name is a STARTS-WITH match, results come
    back alphabetically, and the grid pages at 25.

    THE PAGER WORKS BUT IS LOSSY, AND DOES NOT KNOW IT
        __EVENTTARGET = ctl00$MainContent$gvSearchResults, __EVENTARGUMENT = Page$N
        pages the grid, and a page returning fewer than 25 rows is the last one.
        Measured against a deep-prefix sweep of the same county on the same day:

            paging 36 letters to exhaustion  ->   804 parcels,   69 requests
            prefix deepening to 3 characters ->   925 parcels, 1224 requests
            in prefix and NOT in pager: 124        in pager and NOT in prefix: 3

        The pager reported errors=0, letters_retried=0, pager_stalled=0 while missing
        124 parcels -- 13% of the county. Rows are not returned in a stable order
        across postbacks, so page 2 can skip what page 1 also skipped, and no
        self-check inside a paging chain can see it. A source that looks healthy while
        dropping an eighth of a county is worse than one that fails loudly.

    SO NEITHER METHOD IS USED ALONE. Both run and the results are UNIONED:
      * every prefix is paged to exhaustion -- cheap, and the pages reveal which
        SECOND characters actually occur under that prefix;
      * a prefix that filled a page is then deepened, but ONLY into the next
        characters observed in its own pages plus everything alphabetically at or
        after the last name seen (the unread tail). Expanding into all 36 was what
        made the prefix-only sweep cost 1,224 requests; most of those 36 return zero.

    Completeness is therefore observed, not assumed: a prefix is finished when a page
    comes back under the cap AND its deepened children are finished, and anything
    still capped at max depth is logged by name rather than quietly dropped.

WHAT IS NOT DONE HERE
    The grid also renders a "View" detail link and an "Add to Cart" button. This
    reads the public search grid only. Nothing in this module opens the cart, the
    payment flow, or any authenticated path.

    THE DETAIL PAGE IS A DEAD END, checked 2026-09-10 -- do not re-chase it. The
    grid's View link (TaxesDetailsType4.aspx?receiptNo=...&recID=...) was the obvious
    place to look for the owner's MAILING address, which is the field SC leads are
    short of (SC phone/mail coverage runs 8-18% against NC's 50-89%). It returns a
    5,713-byte page whose body is the single word ERROR, both on a cold GET and when
    fetched inside the same session immediately after the search that produced the
    link, with a Referer set. The mailing address is not available through this
    portal. The realistic route to SC owner mailing addresses is the county
    ASSESSOR card keyed by the TMS this source now supplies.

WHAT THIS SOURCE DOES AND DOES NOT GIVE
    gives    parcel/TMS, owner name (100%), situs address (~57%), balance owed,
             years unpaid, two-year-plus flag, statuses, notice numbers
    does NOT give   owner phone, owner mailing address
    So it closes the SIGNAL and IDENTITY layers for these counties and leaves the
    CONTACT layer where it was. Said plainly rather than implied, because a source
    that fills three layers of five is easy to mistake for coverage.

COUNTIES: 19, all verified live 2026-09-10 to return parseable Unpaid RealEstate
rows with dollar amounts. Subdomain naming is inconsistent (three patterns), so the
map is explicit rather than derived. Five were already known to
enrichment_qpaybill_tax; the other fourteen were found by probing all 46 counties
against the observed patterns.

    Identification-No. FORMAT VARIES BY COUNTY and is deliberately NOT normalised
    here. This module is a lead SOURCE: it emits the portal's own id as parcel_id
    together with the county, which is what the resolver and dedupe want. The
    enricher's join problem -- matching a portal id to a parcel_id that arrived from
    a different source -- is a separate concern and is not solved by pretending the
    formats agree. Observed: dashed 4-group (Barnwell 056-00-00-035), 5-group (Lee
    043-00-00-284-000), SPACE-delimited (Chesterfield 259 003 008 005), letters
    embedded (Lancaster 0141H-0A-020.00), trailing dot (McCormick 154-03-01-012.),
    manufactured-home suffix (Newberry 256-1-4-28-MHN1627), and plain numeric
    (Orangeburg 2082143 -- which is an account id, not a parcel, so Orangeburg rows
    carry it as an account reference and no parcel claim).

ROBOTS / ACCESS POSTURE, checked 2026-09-10
    No robots.txt on either host checked (both 404) and no Terms page (302). No
    login, no CAPTCHA, no rate limiting observed. This is the same public search
    endpoint this repo's enrichment_qpaybill_tax has queried in production since
    2026-07-01; this module reuses its parser rather than writing a second one.

Free, public, no login.
Slug: counties_sc.qpaybill_delinquent_roll
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...enrichment_qpaybill_tax import _UA, _hidden, _url

log = structlog.get_logger()

#: county -> qPayBill subdomain. Every one verified live 2026-09-10 to return
#: parseable Unpaid RealEstate rows. Naming follows no single rule, hence explicit.
QPAYBILL_SUBS: dict[str, str] = {
    # already known to enrichment_qpaybill_tax
    "Spartanburg": "spartanburgcountytax",
    "Oconee": "oconeesctax",
    "Laurens": "laurenstreasurer",
    "Union": "uniontreasurer",
    "Cherokee": "cherokeecountysctax",
    # found 2026-09-10 by probing all 46 SC counties
    "Abbeville": "abbevilletreasurer",
    "Allendale": "allendaletreasurer",
    "Barnwell": "barnwelltreasurer",
    "Calhoun": "calhountreasurer",
    "Chesterfield": "chesterfieldcountytax",
    "Clarendon": "clarendoncountysctax",
    "Darlington": "darlingtontreasurer",
    "Lancaster": "lancastersctax",
    "Lee": "leetreasurer",
    "Marlboro": "marlborocountytax",
    "Mccormick": "mccormicktreasurer",
    "Newberry": "newberrytreasurer",
    "Orangeburg": "orangeburgtreasurer",
    "Williamsburg": "williamsburgtreasurer",
}

#: Counties whose Identification-No. is an ACCOUNT id, not a parcel. Their rows are
#: still real delinquent-tax leads with an owner, a situs address and a balance, but
#: claiming the value as parcel_id would poison dedupe (which keys on
#: parcel:{state}:{county}:{p}) with ids that are not parcels.
ACCOUNT_ID_ONLY = {"Orangeburg"}

#: Observed grid page size. A result of exactly this many rows means "there are
#: probably more" and the prefix is deepened; fewer means the prefix is exhausted.
PAGE_CAP = 25

#: First characters an SC owner-name index actually starts with. Digits included:
#: entity names like "2ND CHANCE LLC" are on these rolls.
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

#: Paging bound per prefix. Barnwell's busiest letter needed 3 pages; 200 is far
#: above any real county roll and exists only so a misbehaving pager cannot spin.
MAX_PAGES_PER_PREFIX = int(os.getenv("QPAYBILL_ROLL_MAX_PAGES", "200"))

#: How many characters deep the name prefixes may go. Depth 3 reached 925 of
#: Barnwell's parcels with 4 prefixes still capped; depth 4 exists for those.
MAX_PREFIX_DEPTH = int(os.getenv("QPAYBILL_ROLL_DEPTH", "4"))

#: Hard request budget PER COUNTY, so a portal that starts returning the cap for
#: every prefix cannot turn this into an unbounded crawl -- and, because the counties
#: sweep concurrently, so a large county cannot spend the small ones' allowance. An
#: earlier draft shared one global budget across all 19, which meant Spartanburg
#: (330k people) could exhaust it before Williamsburg (30k) issued a single query,
#: and the shortfall would have looked like "Williamsburg has no delinquent roll".
#: Barnwell's full sweep cost 873; 2,500 leaves room for counties an order of
#: magnitude larger before truncation is even reported.
REQUEST_BUDGET_PER_COUNTY = int(os.getenv("QPAYBILL_ROLL_BUDGET", "2500"))

_PER_HOST_CONCURRENCY = 3

#: Ceiling across ALL counties at once. Nineteen counties x 3 = 57 simultaneous new
#: clients, each doing its own DNS lookup, and macOS's resolver started returning
#: "nodename nor servname provided" -- a transient failure that reads exactly like a
#: dead host. Capping the total keeps the sweep inside what the resolver will take.
_GLOBAL_CONCURRENCY = int(os.getenv("QPAYBILL_ROLL_CONCURRENCY", "12"))
_GLOBAL_SEM: "asyncio.Semaphore | None" = None


def _global_sem() -> "asyncio.Semaphore":
    global _GLOBAL_SEM
    if _GLOBAL_SEM is None:
        _GLOBAL_SEM = asyncio.Semaphore(_GLOBAL_CONCURRENCY)
    return _GLOBAL_SEM
_OWED_STATUSES = ("unpaid", "sold at tax sale", "delinquent", "bankruptcy")


def parse_grid(html: str) -> list[dict]:
    """Parse the results grid into owner/address-split rows.

    Deliberately separate from enrichment_qpaybill_tax._parse_rows, which keeps only
    {tms, year, status, amount} because a balance is all an enricher needs. A lead
    source needs the owner, the situs address and the notice number too, and column
    1 splits exactly on the ``<br/>`` the portal emits.
    """
    out: list[dict] = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html):
        tds = re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
        if len(tds) < 9:
            continue

        def clean(x: str) -> str:
            x = re.sub(r"(?i)<br\s*/?>", "\n", x)
            x = re.sub(r"<[^>]+>", " ", x)
            x = (x.replace("&amp;", "&").replace("&nbsp;", " ")
                  .replace("&#39;", "'").replace("&quot;", '"'))
            return re.sub(r"[ \t]+", " ", x).strip()

        name_addr = clean(tds[1])
        ident = clean(tds[4])
        amt_m = re.search(r"\$([\d,]+\.\d{2})", clean(tds[8]))
        if not (ident and amt_m):
            continue
        amount = float(amt_m.group(1).replace(",", ""))
        # qPayBill placeholder / misfire values, same guards the enricher uses.
        if amount <= 0 or amount == 99999.00 or amount >= 1_000_000:
            continue
        status = clean(tds[6])
        if status and not any(s in status.lower() for s in _OWED_STATUSES):
            continue

        parts = [p.strip() for p in name_addr.split("\n") if p.strip()]
        owner = parts[0] if parts else None
        address = parts[1] if len(parts) > 1 else None
        out.append({
            "notice_no": clean(tds[0]) or None,
            "owner": owner,
            "address": address,
            "year": clean(tds[2]) or None,
            "description": clean(tds[3]) or None,
            "ident": ident,
            "status": status or None,
            "amount": amount,
        })
    return out


class _Budget:
    """Shared request budget. Counting requests rather than time keeps a slow portal
    from starving the other eighteen, and makes truncation reportable."""

    def __init__(self, total: int) -> None:
        self.left = total
        self.spent = 0

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        self.spent += 1
        return True


#: The GridView that renders results. Its postback target is what pages the grid.
_GRID_TARGET = "ctl00$MainContent$gvSearchResults"

_SEARCH_FIELDS = {
    "ctl00$MainContent$SearchType": "radRealEstateButton",
    "ctl00$MainContent$PaidStatus": "radUnpaidButton",
    "ctl00$MainContent$ddlYearList": "All",
    "ctl00$MainContent$ddlCriteriaList": "Name",
}


def _vs(html: str) -> dict:
    return {"vs": _hidden(html, "__VIEWSTATE"),
            "gen": _hidden(html, "__VIEWSTATEGENERATOR"),
            "ev": _hidden(html, "__EVENTVALIDATION")}


async def _post(client: httpx.AsyncClient, sub: str, vs: dict, prefix: str,
                page: int | None) -> tuple[list[dict], dict]:
    """One search (page=None) or one pager step (page=N). Returns (rows, new_vs)."""
    data = {
        "__EVENTTARGET": _GRID_TARGET if page else "",
        "__EVENTARGUMENT": f"Page${page}" if page else "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": vs["vs"], "__VIEWSTATEGENERATOR": vs["gen"],
        "__EVENTVALIDATION": vs["ev"],
        **_SEARCH_FIELDS,
        "ctl00$MainContent$txtCriteriaBox": prefix,
    }
    if not page:
        data["ctl00$MainContent$btnSearch"] = "Search"
    resp = await client.post(_url(sub), data=data)
    return parse_grid(resp.text), _vs(resp.text)


async def _fresh_vs(client: httpx.AsyncClient, sub: str) -> dict:
    r = await client.get(_url(sub))
    return _vs(r.text)


def _all_match(rows: list[dict], prefix: str) -> bool:
    """Every owner on the page must still start with the prefix we asked for. A page
    that drifts means the viewstate chain is carrying somebody else's search, and
    accepting it would file another letter's parcels under this one."""
    up = prefix.upper()
    return all((r.get("owner") or "").upper().startswith(up) for r in rows)


def _absorb(rows: list[dict], sink: dict) -> None:
    """Keyed on (ident, year, notice) so the two enumeration strategies can be
    unioned without double-counting a row either of them read."""
    for r in rows:
        sink[(r["ident"], r.get("year") or "", r.get("notice_no") or "")] = r


async def _walk_prefix(client: httpx.AsyncClient, sub: str, prefix: str,
                       budget: "_Budget", sink: dict, stats: dict) -> tuple[bool, set]:
    """Search one prefix and page it to exhaustion.

    Returns (needs_deepening, next_chars). `next_chars` is the set of characters to
    deepen into: those actually observed after this prefix in the rows we read, plus
    every character at or after the last one seen, since anything past the last name
    on the last page we managed to read is unread rather than absent.
    """
    # A prefix abandoned on one exception is a whole initial silently missing from the
    # county, with nothing but an errors counter to show it. Observed live: two
    # transient macOS DNS failures ("nodename nor servname provided") dropped letters
    # A and B outright. So retry with backoff, and if it still fails, name the prefix
    # in the log so the hole is identifiable rather than merely counted.
    rows = None
    vs = None
    for attempt in range(3):
        if not budget.take():
            return False, set()
        try:
            vs = await _fresh_vs(client, sub)
            if not vs["vs"]:
                raise RuntimeError("no __VIEWSTATE on the search page")
            rows, vs = await _post(client, sub, vs, prefix, None)
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                stats["errors"] += 1
                stats.setdefault("lost_prefixes", []).append(prefix)
                log.warning("qpaybill_roll.search_lost", prefix=prefix,
                            attempts=3, error=str(exc)[:120],
                            note="this prefix contributed NOTHING; the county roll is "
                                 "incomplete for owners whose name starts with it")
                return False, set()
            await asyncio.sleep(1.5 * (attempt + 1))
    if rows is None:
        return False, set()
    stats["queries"] += 1
    if rows and not _all_match(rows, prefix):
        stats["drifted"] += 1
        return True, set(_ALPHABET)      # cannot trust this chain; deepen widely
    _absorb(rows, sink)
    seen_chars, last_char = _next_chars(rows, prefix)
    capped = len(rows) >= PAGE_CAP

    page = 1
    while len(rows) >= PAGE_CAP:
        if page >= MAX_PAGES_PER_PREFIX:
            stats["page_capped_prefixes"] += 1
            log.warning("qpaybill_roll.page_cap", prefix=prefix, pages=page)
            break
        if not budget.take():
            break
        page += 1
        before = len(sink)
        try:
            rows, vs = await _post(client, sub, vs, prefix, page)
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            log.warning("qpaybill_roll.page_fail", prefix=prefix, page=page,
                        error=str(exc)[:120])
            break
        stats["queries"] += 1
        if rows and not _all_match(rows, prefix):
            stats["drifted"] += 1
            break
        _absorb(rows, sink)
        more, lc = _next_chars(rows, prefix)
        seen_chars |= more
        last_char = lc or last_char
        if len(sink) == before and rows:
            stats["pager_stalled"] += 1
            break

    if not capped:
        return False, set()
    # Deepen into observed children plus the unread alphabetical tail.
    tail = set()
    if last_char:
        idx = _ALPHABET.find(last_char)
        tail = set(_ALPHABET[idx:]) if idx >= 0 else set(_ALPHABET)
    return True, (seen_chars | tail) or set(_ALPHABET)


def _next_chars(rows: list[dict], prefix: str) -> tuple[set, str | None]:
    """Characters that follow `prefix` in these owners, and the last one seen."""
    n = len(prefix)
    chars = set()
    last = None
    for r in rows:
        name = (r.get("owner") or "").upper()
        if len(name) > n:
            ch = name[n]
            if ch in _ALPHABET:
                chars.add(ch)
                last = ch
    return chars, last


async def sweep_county(client: httpx.AsyncClient, county: str, sub: str,
                       budget: "_Budget") -> tuple[list[dict], dict]:
    """Union sweep of one county: page every prefix, deepen the capped ones.

    `client` is accepted for call-site symmetry but intentionally unused. Every
    prefix opens its OWN client, hence its own cookie jar: measured 2026-09-10,
    three letters paging concurrently through one shared client returned 789 of
    Barnwell's 925 parcels, because qPayBill holds the grid's paging state
    server-side against the session and a Page$2 issued for letter G could be
    answered with letter M's rows. The _all_match guard caught the crossover, so the
    loss surfaced as retries rather than as wrong data, but the rows behind the
    rejected pages were never read.
    """
    sink: dict[tuple[str, str, str], dict] = {}
    stats: dict = {"queries": 0, "errors": 0, "page_capped_prefixes": 0,
                   "pager_stalled": 0, "drifted": 0, "deepened": 0,
                   "truncated_prefixes": 0, "lost_prefixes": []}
    sem = asyncio.Semaphore(_PER_HOST_CONCURRENCY)

    async def guarded(prefix: str) -> tuple[str, bool, set]:
        async with _global_sem(), sem:
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True,
                                         headers={"User-Agent": _UA}) as own:
                deeper, chars = await _walk_prefix(own, sub, prefix, budget,
                                                   sink, stats)
                return prefix, deeper, chars

    frontier = list(_ALPHABET)
    depth = 1
    while frontier and depth <= MAX_PREFIX_DEPTH:
        results = await asyncio.gather(*(guarded(p) for p in frontier))
        nxt = [p + ch for p, deeper, chars in results if deeper for ch in sorted(chars)]
        stats["deepened"] += len(nxt)
        if nxt and depth >= MAX_PREFIX_DEPTH:
            stats["truncated_prefixes"] = len({p[:-1] for p in nxt})
            log.warning("qpaybill_roll.depth_truncated", county=county, depth=depth,
                        prefixes=sorted({p[:-1] for p in nxt})[:12],
                        note="still filling pages at max depth; raise "
                             "QPAYBILL_ROLL_DEPTH to read further")
        frontier = nxt
        depth += 1
    return list(sink.values()), stats


def _to_listings(county: str, rows: list[dict]) -> list[Listing]:
    """One Listing per PARCEL, with the unpaid years aggregated onto it.

    The portal returns a row per unpaid YEAR, so a two-year delinquency arrives as
    two rows for the same id. Emitting them separately would put the same property
    on the board twice and hide the strongest signal in the data; aggregating makes
    years_delinquent and the total balance explicit.
    """
    by_ident: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ident[r["ident"]].append(r)

    out: list[Listing] = []
    now = datetime.utcnow()
    account_only = county in ACCOUNT_ID_ONLY
    for ident, group in by_ident.items():
        group.sort(key=lambda g: (g.get("year") or ""))
        years = sorted({g["year"] for g in group if g.get("year")})
        total = round(sum(g["amount"] for g in group), 2)
        owner = next((g["owner"] for g in group if g.get("owner")), None)
        address = next((g["address"] for g in group if g.get("address")), None)
        prior = next((g["description"] for g in group if g.get("description")), None)
        out.append(Listing(
            source="counties_sc.qpaybill_delinquent_roll",
            source_url=_url(QPAYBILL_SUBS[county]),
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC",
            county=county,
            parcel_id=None if account_only else ident,
            defendant=owner,
            owner_name=owner,
            street_address=address,
            description=(f"Delinquent property tax: ${total:,.2f} owed"
                         + (f" for {len(years)} year(s) ({', '.join(years)})" if years else "")
                         + (f" — {prior}" if prior else "")),
            first_seen=now,
            last_seen=now,
            raw={"qpaybill_roll": {
                "identification_no": ident,
                "is_account_id_not_parcel": account_only,
                "county": county,
                "subdomain": QPAYBILL_SUBS[county],
                "owner": owner,
                "property_address": address,
                "balance_owed": total,
                "years_unpaid": years,
                "years_delinquent": len(years),
                "is_two_year_plus": len(years) >= 2,
                "statuses": sorted({g["status"] for g in group if g.get("status")}),
                "notice_numbers": [g["notice_no"] for g in group if g.get("notice_no")][:6],
                "prior_owner_description": prior,
                "rows": len(group),
            }},
        ))
    return out


class QPayBillDelinquentRoll(BaseScraper):
    slug = "counties_sc.qpaybill_delinquent_roll"
    name = "SC qPayBill Delinquent Real-Property Roll (19 counties)"
    category = "county_tax"
    timeout_s = 900.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        only = {c.strip().title() for c in
                (os.getenv("QPAYBILL_ROLL_COUNTIES") or "").split(",") if c.strip()}
        targets = {k: v for k, v in QPAYBILL_SUBS.items() if not only or k in only}
        budgets = {c: _Budget(REQUEST_BUDGET_PER_COUNTY) for c in targets}
        t0 = time.monotonic()
        log.info("qpaybill_roll.start", counties=len(targets),
                 budget_per_county=REQUEST_BUDGET_PER_COUNTY,
                 max_pages=MAX_PAGES_PER_PREFIX, max_depth=MAX_PREFIX_DEPTH)

        out: list[Listing] = []
        per_county: dict[str, int] = {}
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True,
                                     headers={"User-Agent": _UA}) as client:
            results = await asyncio.gather(
                *(sweep_county(client, county, sub, budgets[county])
                  for county, sub in sorted(targets.items())),
                return_exceptions=True,
            )
        for (county, _sub), res in zip(sorted(targets.items()), results):
            if isinstance(res, BaseException):
                log.warning("qpaybill_roll.county_failed", county=county,
                            error=str(res)[:140])
                per_county[county] = 0
                continue
            rows, stats = res
            listings = _to_listings(county, rows)
            per_county[county] = len(listings)
            out.extend(listings)
            lost = stats.pop("lost_prefixes", [])
            log.info("qpaybill_roll.county_done", county=county,
                     parcels=len(listings), rows=len(rows),
                     lost_prefixes=len(lost), **stats)
            if lost:
                log.warning("qpaybill_roll.county_incomplete", county=county,
                            prefixes=sorted(lost),
                            note="owners whose name starts with these were never "
                                 "read; this county's roll is INCOMPLETE")

        starved = sorted(c for c, b in budgets.items() if b.left <= 0)
        if starved:
            log.warning("qpaybill_roll.budget_exhausted", counties=starved,
                        note="these counties hit their per-county request budget and "
                             "their rolls are INCOMPLETE. Raise QPAYBILL_ROLL_BUDGET.")
        log.info("qpaybill_roll.done", parcels=len(out),
                 requests=sum(b.spent for b in budgets.values()),
                 seconds=round(time.monotonic() - t0, 1),
                 per_county=per_county)
        return out
