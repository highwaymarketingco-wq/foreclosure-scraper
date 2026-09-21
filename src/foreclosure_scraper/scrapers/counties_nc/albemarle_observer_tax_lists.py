"""Albemarle Observer republications of the NC annual delinquent-tax lists.

NCGS 105-369 makes each county advertise its unpaid real-property taxes once a year, and the
Albemarle Observer (albemarleobserver.news, a WordPress site) republishes several of those
lists free, as ordinary posts with the list in the post body. The WordPress REST API is open
(no key, no login, no challenge):

    GET https://albemarleobserver.news/wp-json/wp/v2/posts?search=delinquent&per_page=50
            &_fields=id,date,link,title
    GET https://albemarleobserver.news/wp-json/wp/v2/posts/<id>?_fields=id,date,link,title,content

Verified live 2026-09-21 (six requests). The four counties the research wanted are all
fetchable and machine-readable, but each list is laid out differently, so each has its own
row parser:

    Tyrrell     <ul><li>  NAME  PARCEL  AMOUNT     395 rows, parcel ids like T12201001, C00415005
    Washington  <ul><li>  NAME  ACCOUNT  AMOUNT    1,206 rows in the county list (five alphabetical
                                                   <ul> blocks under one joint heading); account
                                                   number only, no parcel, no situs. The Town of
                                                   Plymouth's own post is <li>NAME $AMOUNT, 569
                                                   rows, no account at all
    Gates       <p>       NAME  YEAR  SITUS  $AMT  1,567 rows, one per owner per year, situs but
                                                   no parcel id
    Bertie      <table>   OWNER | PIN | $AMT       1,574 rows; PIN is "25A" + the 10-digit parno
                                                   (4 of 5 sampled PINs matched Bertie parcels
                                                   in NC OneMap, all residential or business real
                                                   property, though the post is titled "personal
                                                   property")

Only the newest post per county is read, and only if it is under 400 days old, because the
county re-advertises every spring and an old list is a list of debts since paid.

WHAT IS EMITTED
    A TAX_LIEN lead per parcel (Tyrrell, Bertie), per owner and situs (Gates) or per owner
    account (Washington), with the years summed. `raw["tax_owed"]` carries the balance. Only
    Tyrrell and Bertie carry a parcel id that joins the NC OneMap cache; Gates carries a situs
    that matches OneMap `siteadd`; Washington is name plus account only and needs the
    name-to-property resolver.

    NOTE the "as of" date: these are the county's principal-only advertised amounts as of the
    date printed in the post (Gates March 31, Washington June 8), before interest, fees and
    payments since. They are a magnitude, not a payoff.

Free, public, no login, no CAPTCHA. The Observer states it publishes the lists "FREE of charge
as a public service".
Slug: counties_nc.albemarle_observer_tax_lists
Category: county_tax
ListingType: TAX_LIEN
"""
from __future__ import annotations

import asyncio
import html as _html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.albemarle_observer_tax_lists"
BASE = "https://albemarleobserver.news/wp-json/wp/v2/posts"
INDEX_URL = f"{BASE}?search=delinquent&per_page=50&_fields=id,date,link,title"
POST_URL = BASE + "/{id}?_fields=id,date,link,title,content"
MAX_AGE_DAYS = 400
PACE_S = 2.0

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_AMT = r"\$?\s*(?P<amt>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})"
_TAG = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(_html.unescape(_TAG.sub(" ", fragment or "")).split())


def _money(s: str) -> float:
    return round(float(s.replace(",", "")), 2)


# --------------------------------------------------------------------------- row parsers
# Each takes the rendered post HTML and returns bill dicts:
#   {"owner", "amount", "year"?, "parcel"?, "account"?, "situs"?, "jurisdiction"?, "flag"?}

_TYRRELL = re.compile(rf"^(?P<owner>.+?)\s+(?P<pid>[A-Z]\d{{6,9}}[A-Z0-9]*)\s+{_AMT}$")
_WASH = re.compile(rf"^(?P<owner>.+?)\s+(?P<acct>\d{{3,7}})\s+{_AMT}(?P<flag>\s*\*)?$")
#: The situs may not contain a "$": one Gates row in the source is two rows run together
#: ("... 95 TYLER RD $268.05 KING, DONNIE 2025 $131.31") and must be skipped, not merged.
_GATES = re.compile(rf"^(?P<owner>.+?)\s+(?P<year>20\d{{2}})\s+(?P<situs>[^$]+?)\s+{_AMT}$")
#: "25A" + the parcel number: 10 digits usually, 12 to 13 with a sub-parcel suffix.
_BERTIE_PIN = re.compile(r"^\d{2}[A-Z](?P<parno>\d{9,13})$")


def parse_tyrrell(content: str) -> list[dict]:
    out = []
    for li in re.findall(r"<li[^>]*>(.*?)</li>", content, flags=re.S):
        m = _TYRRELL.match(_text(li))
        if m:
            out.append({"owner": m["owner"].strip(" ,"), "parcel": m["pid"],
                        "amount": _money(m["amt"])})
    return out


def parse_washington(content: str) -> list[dict]:
    """The county tax collector's advertisement, split by the Observer across five
    alphabetical <ul> blocks under ONE heading ("WASHINGTON COUNTY/TOWN OF CRESWELL"). The
    heading is a single joint notice, not a section per town, so it is not used to
    attribute a row to a town."""
    out = []
    for li in re.findall(r"<li[^>]*>(.*?)</li>", content, flags=re.S):
        m = _WASH.match(_text(li))
        if m:
            out.append({"owner": m["owner"].strip(" ,"), "account": m["acct"],
                        "amount": _money(m["amt"]), "jurisdiction": "WASHINGTON COUNTY",
                        "flag": bool(m["flag"])})
    return out


_PLYMOUTH = re.compile(rf"^(?P<owner>.+?)\s+{_AMT}$")


def parse_plymouth(content: str) -> list[dict]:
    """The Town of Plymouth's own list: `NAME $AMOUNT`, no account, no parcel."""
    out = []
    for li in re.findall(r"<li[^>]*>(.*?)</li>", content, flags=re.S):
        m = _PLYMOUTH.match(_text(li))
        if m:
            out.append({"owner": m["owner"].strip(" ,"), "amount": _money(m["amt"]),
                        "jurisdiction": "TOWN OF PLYMOUTH"})
    return out


def parse_gates(content: str) -> list[dict]:
    out = []
    for p in re.findall(r"<p[^>]*>(.*?)</p>", content, flags=re.S):
        # WordPress packs several rows into one <p>, separated by a newline or <br>. Parsing
        # the whole paragraph as one line made the lazy situs group swallow the next rows.
        for line in re.split(r"<br\s*/?>|\n", p):
            m = _GATES.match(_text(line))
            if m:
                out.append({"owner": m["owner"].strip(" ,"), "year": int(m["year"]),
                            "situs": m["situs"].strip(), "amount": _money(m["amt"])})
    return out


def parse_bertie(content: str) -> list[dict]:
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", content, flags=re.S):
        tds = [_text(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)]
        if len(tds) < 3:
            continue
        pin = re.sub(r"\s+", "", tds[1])
        m = _BERTIE_PIN.match(pin)
        amt = re.search(r"(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})", tds[2])
        if m and amt and tds[0]:
            out.append({"owner": tds[0], "parcel": m["parno"], "account": pin,
                        "amount": _money(amt.group(1))})
    return out


@dataclass(frozen=True)
class Target:
    county: str
    title_re: re.Pattern
    parser: Callable[[str], list[dict]]
    key: str                       # how bills group into one lead: parcel | account | owner | owner_situs
    title_not: re.Pattern | None = None


TARGETS: tuple[Target, ...] = (
    Target("Tyrrell", re.compile(r"Tyrrell County.*(Unpaid|Delinquent)", re.I), parse_tyrrell, "parcel"),
    Target("Washington", re.compile(r"^Washington County Delinquent Property Tax", re.I),
           parse_washington, "account"),
    Target("Washington", re.compile(r"^Plymouth.s Delinquent Tax List", re.I),
           parse_plymouth, "owner"),
    Target("Gates", re.compile(r"^Gates County Delinquent", re.I), parse_gates, "owner_situs"),
    Target("Bertie", re.compile(r"^Bertie County .*delinquent", re.I), parse_bertie, "parcel"),
)


# --------------------------------------------------------------------------- selection

def pick_post(index: list[dict], target: Target, today: datetime | None = None) -> dict | None:
    """The newest post whose title matches, if it is recent enough to be this year's list."""
    today = today or datetime.utcnow()
    best = None
    for p in index or []:
        title = _text((p.get("title") or {}).get("rendered") or "")
        if not target.title_re.search(_html.unescape(title).replace("’", "'")):
            continue
        try:
            d = datetime.fromisoformat(str(p.get("date"))[:19])
        except ValueError:
            continue
        if today - d > timedelta(days=MAX_AGE_DAYS):
            continue
        if best is None or d > best[0]:
            best = (d, p)
    return best[1] if best else None


def list_year(title: str, post_date: datetime, content: str) -> int:
    m = re.search(r"\b(?:for the year|tax year|year)\s+(20\d{2})\b", content or "", re.I) \
        or re.search(r"\b(20\d{2})\b(?:\s+(?:unpaid|delinquent))", title, re.I) \
        or re.search(r"\b(20\d{2})\b", title)
    return int(m.group(1)) if m else post_date.year - 1


_HOUSE = re.compile(r"^\d{1,6}[A-Z]?\s+\S")


def to_listings(target: Target, bills: list[dict], *, post: dict, content: str) -> list[Listing]:
    post_date = datetime.fromisoformat(str(post["date"])[:19])
    title = _text((post.get("title") or {}).get("rendered") or "")
    year = list_year(title, post_date, content)
    groups: dict[tuple, list[dict]] = {}
    for b in bills:
        if target.key == "parcel":
            k = (b["parcel"],)
        elif target.key == "account":
            k = (b["jurisdiction"], b["account"])
        elif target.key == "owner":
            k = (b.get("jurisdiction"), b["owner"].upper())
        else:
            k = (b["owner"].upper(), (b["situs"] or "").upper())
        groups.setdefault(k, []).append(b)
    now = datetime.utcnow()
    out: list[Listing] = []
    for k, group in groups.items():
        head = group[0]
        # WITHOUT a parcel or a street address, Listing.dedupe_key() falls back to the source
        # URL, and every row of one post shares that URL: the board's dedupe would collapse
        # all 1,206 Washington rows into ONE lead. A per-row fragment keeps them distinct and
        # still opens the post.
        frag = re.sub(r"[^a-z0-9]+", "-", f"{target.county}-" + "-".join(str(x) for x in k if x).lower()).strip("-")[:90]
        total = round(sum(b["amount"] for b in group), 2)
        years = sorted({b["year"] for b in group if b.get("year")}) or [year]
        situs = head.get("situs")
        street = situs if (situs and _HOUSE.match(situs)) else None
        block = {
            "county": target.county, "post_url": post.get("link"), "post_date": post_date.date().isoformat(),
            "list_year": year, "owner": head["owner"], "parcel": head.get("parcel"),
            "account": head.get("account"), "situs_text": situs,
            "jurisdiction": head.get("jurisdiction"), "years": years,
            "years_delinquent": len(years), "is_two_year_plus": len(years) >= 2,
            "total_due": total, "bills": [{"year": b.get("year"), "amount": b["amount"]} for b in group],
            "principal_only": True,
        }
        raw = {"albemarle_observer_tax_list": block,
               "tax_owed": {"balance": total, "kind": "delinquent_tax", "source": SLUG,
                            "year": years[-1], "basis": "own_record"}}
        if target.key == "owner_situs":
            # Only Gates prints a year per row, so only there is "one year" a measurement; the
            # Tyrrell, Bertie and Washington lists are a single tax year and say nothing about age.
            raw["two_year_delinquent"] = {"is_two_year_plus": len(years) >= 2, "years": len(years),
                                          "oldest_year": years[0], "source": SLUG}
        out.append(Listing(
            source=SLUG,
            source_url=f"{post.get('link') or BASE}#{frag}",
            listing_type=ListingType.TAX_LIEN,
            property_kind=PropertyKind.UNKNOWN,
            state="NC", county=target.county,
            parcel_id=head.get("parcel"),
            owner_name=head["owner"], defendant=head["owner"],
            street_address=street,
            legal_description=None if street else situs,
            foreclosure_process="tax",
            description=(f"{target.county} County {year} delinquent property tax list (NCGS 105-369): "
                         f"${total:,.2f} principal advertised"
                         + (f", {len(years)} years" if len(years) > 1 else "")),
            first_seen=now, last_seen=now, raw=raw,
        ))
    return out


class AlbemarleObserverTaxLists(BaseScraper):
    slug = SLUG
    name = "Albemarle Observer NC delinquent-tax list republications (Tyrrell, Washington, Gates, Bertie)"
    category = "county_tax"
    timeout_s = 240.0
    expected_min_count = 0
    optional = True

    #: A sample run (the ingest script's dry run) keeps the first N leads of EACH list.
    limit: int | None = None

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=60.0,
                                     follow_redirects=True) as c:
            try:
                r = await c.get(INDEX_URL)
                r.raise_for_status()
                index = r.json()
            except Exception as exc:  # noqa: BLE001
                log.warning("ao_tax.index_fail", error=str(exc)[:160])
                return out
            for target in TARGETS:
                post = pick_post(index, target)
                if post is None:
                    log.info("ao_tax.no_current_post", county=target.county,
                             note="no matching post under %d days old" % MAX_AGE_DAYS)
                    continue
                await asyncio.sleep(PACE_S)
                try:
                    pr = await c.get(POST_URL.format(id=post["id"]))
                    pr.raise_for_status()
                    content = (pr.json().get("content") or {}).get("rendered") or ""
                except Exception as exc:  # noqa: BLE001
                    log.warning("ao_tax.post_fail", county=target.county, id=post.get("id"),
                                error=str(exc)[:160])
                    continue
                bills = target.parser(content)
                if not bills:
                    log.warning("ao_tax.no_rows", county=target.county, id=post.get("id"),
                                note="post fetched but no row matched: the layout may have changed")
                    continue
                got = to_listings(target, bills, post=post, content=content)
                log.info("ao_tax.parsed", county=target.county, post=post.get("link"),
                         bills=len(bills), leads=len(got))
                if self.limit:                      # a sample run: N leads per list
                    got = got[: self.limit]
                self.partial.extend(got)
                out.extend(got)
        return out
