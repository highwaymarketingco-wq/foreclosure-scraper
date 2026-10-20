"""Johnston County NC's static delinquent-tax file, crosswalked to the board's modern PIN via
NC OneMap owner/address matching -- a net-new discovery source, not a verifier.

WHY THIS EXISTS (2026-10-20 investigation, orchestrating session). Johnston County NC publishes
a real, public, unauthenticated delinquent-tax export:

    https://www.johnstonnc.gov/files/taxoffice/DelinquentTaxPublicRecordsFile<id>.txt

linked off the county's own "Files for Download" tax-office page
(https://www.johnstonnc.gov/tax2/tcontent.cfm?pid=files, confirmed live 2026-10-20 -- the page's
own relative links, e.g. "../../files/taxoffice/township_map.pdf", resolve against it). The file
name's numeric suffix rotates whenever the county republishes (seen live as "2026108"; read
2026/10/8 -- year, month, revision), so it is never hardcoded: `extract_file_url()` regexes the
CURRENT link text off the page on every run, the same discipline
`counties_sc.florence_delinquent_tax` already uses for its own annually-renamed PDFs.

THE FILE ITSELF: UTF-16 (with BOM), comma-separated, one row per (parcel, tax year), columns
`Taxyear,ParcelNumber,LastName,FirstName,PropertyAddress,ZipCode,TotalDue,Bill,LandUnits,Type`.
ParcelNumber is wrapped in an Excel "keep this text, do not reformat" formula (`="08019024"`) --
stripped by `_strip_excel_formula()`. Rows are aggregated per parcel (summed TotalDue across
years, one `{year: amount}` map) by `aggregate_by_parcel()`.

THE CROSSWALK PROBLEM. Johnston's own ParcelNumber is a LEGACY map/block/lot id ("08019024",
"15K11023") that does not match the board's modern 12-digit PIN format at all, so these 539
distinct parcels (2026-10-20 snapshot; $761,185.57 total, tax years 2015-2025) cannot be matched
against existing board rows, or turned into new ones, by parcel id alone. The fix: NC's statewide
cadastral exchange, NC OneMap (`services.nconemap.gov/.../NC1Map_Parcels/FeatureServer/1` -- the
SAME layer `nc_heir_estate_parcels.py` already queries for every NC county outside its own 11
dedicated-layer counties, reused here via `enrichment_owner_mailing.COUNTY_GIS["NC:Cleveland"]` +
its `_query()` helper, including that helper's shared per-host throttle), scoped to Johnston via
`cntyname='JOHNSTON'` (the same county-scoping field nc_heir_estate_parcels.py's `_where()` uses
for every statewide-fallback county; confirmed live 2026-10-20 to return the identical result as
the alternative `stcntyfips='37101'` FIPS form).

THE MATCH RULE (`classify_match()`), and why it is strict. The file's LastName/FirstName are
queried as an exact-last-name + prefix-first-name `ownname LIKE 'LAST, FIRST%'` WHERE clause.
Owner name alone is NOT enough to accept a match: an early probe during this crosswalk's
development hit a real false positive where an HOA entity name ("CHANDLER RIDGE OWNERS
ASSOCIATION INC") overlaps a person's own first+last name tokens ("RIDGE", "CHANDLER") on pure
substring/name overlap -- a different kind of property and owner entirely. Every candidate NC
OneMap returns is therefore additionally required to AGREE on the house number with the
delinquent file's own PropertyAddress (`verification.core.address_relation`, this project's
standard address-agreement gate -- house-number agreement is enough, suffix/direction tokens may
differ). A legacy parcel resolves only when EXACTLY ONE candidate's address agrees (`matched`,
`unique_address_match`); zero candidates is `rejected`/`owner_not_found`; 2+ address-agreeing
candidates is `rejected`/`multiple_address_matches` (never guess which one); a candidate set with
no usable address signal on either side at all is `ambiguous_no_address_signal` (never accepted);
and one or more candidates whose address actively CONFLICTS (a different house number) is
`rejected`/`address_conflict`.

RESULT (2026-10-20 live run, full 539-parcel file): 187 resolved at `unique_address_match`
confidence (34.7%). Of those, 8 already exist as board rows (all `counties_nc.
nc_heir_estate_parcels` estate-lead rows for the SAME PIN, once both sides' parcel ids are run
through the board's own normalizer -- a raw string compare misses this, since board `parcel_id`
is sometimes dash-formatted) and already carry a `tax_lien_johnston_static` verification-ledger
entry recording this same evidence (`docs/handoff/verification/tax_lien_johnston_static/`,
commit 016a84a5). This scraper exists for the OTHER ~179: genuinely new leads with no board row
at all, that this scraper turns into real `Listing`s on every run (never a one-off count --
`fetch()` re-downloads and re-crosswalks the live file and layer fresh every time it runs).

EVIDENCE SHAPE. `raw['johnston_delinquent_tax_crosswalk']` mirrors the fields the already-
committed ledger entries use (`years_delinquent`, `total_delinquent`, `delinquent_by_year`,
`land_use_type`, `legacy_parcel`, `crosswalk_method`, `crosswalk_confidence`, `url`, plus
`resolved_pin` and `file_snapshot`) so a future verifier or audit can read either shape the same
way. `resolved_pin` is also registered in `tax_binding.BLOCK_PARCEL_FIELDS` (the field this
block's own bill is FOR) and the block name in `enrichment_tax_owed._SOURCES` (so the summed
`total_delinquent` normalizes into `raw['tax_owed']` same as every other delinquent-tax producer)
and in `web_artifact.RAW_KEEP` (so the block survives publish instead of being silently stripped).

Distress signal: `listing_type=ListingType.TAX_LIEN` is read directly by `distress_score`'s
listing-type signal table (FINANCIAL, weight 20) -- the same convention every other delinquent-
tax-roll producer here uses (e.g. `nc_county_csv_delinquent_tax.py`); it does NOT set
`raw['relationship_signal']` (that path is for probate/divorce/partition life-event signals only,
confirmed by grepping every other `ListingType.TAX_LIEN`-emitting producer in this repo -- none
of the plain delinquent-tax-roll ones set it).

Dateless: this file states no sale date, ever (a delinquent BALANCE is a standing condition, not
a scheduled event) -- routed via `DATELESS_OK_SOURCES` in main.py, same as every other
delinquent-tax source here. property_kind is left UNKNOWN: Johnston's own "Type" column (AC/LT/
UT) and NC OneMap's `structno` field (seen 0 on every one of the 187 live matches, including ones
that also carry a nonzero `improvval`, i.e. it looks unreliable on this layer) are not a
confirmed PropertyKind legend, so neither is used to guess -- consistent with
`nc_heir_estate_parcels.py` and `nc_county_csv_delinquent_tax.py`'s own choice.

Free, public, no login, no CAPTCHA, no token (despite "secure" in the NC OneMap URL path).
Gate off with FORECLOSURE_JOHNSTON_TAX_CROSSWALK=0.
Slug: counties_nc.johnston_delinquent_tax_crosswalk
Category: county_tax
"""
from __future__ import annotations

import asyncio
import csv
import io
import os
import re
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...enrichment_owner_mailing import COUNTY_GIS, _query
from ...verification.core import address_relation

log = structlog.get_logger()

STATE = "NC"
COUNTY = "Johnston"
SLUG = "counties_nc.johnston_delinquent_tax_crosswalk"
RAW_KEY = "johnston_delinquent_tax_crosswalk"

#: Johnston's own tax-office "Files for Download" page. Confirmed live 2026-10-20: a ColdFusion
#: page whose own relative links ("../../files/taxoffice/...") resolve against it.
FILES_PAGE_URL = "https://www.johnstonnc.gov/tax2/tcontent.cfm?pid=files"

#: The current "Delinquent Taxes" link on that page -- never hardcoded, the numeric suffix
#: rotates on republish (seen live as "2026108"). Matches the href regardless of quote style.
_FILE_LINK_RE = re.compile(
    r"""href\s*=\s*['"]([^'"]*DelinquentTaxPublicRecordsFile\d+\.txt)['"]""", re.I)

#: NC OneMap's statewide parcel layer -- the SAME spec `nc_heir_estate_parcels.py` uses for every
#: NC county outside its 11 dedicated-layer counties (Johnston is one of those 89).
_ONEMAP_SPEC = COUNTY_GIS["NC:Cleveland"]
_ONEMAP_OUT_FIELDS = "parno,ownname,siteadd,structno,improvval"
#: One legacy parcel's owner can carry more than one NC OneMap record (co-owned parcels, a common
#: surname); generous enough that a real multi-candidate case is still seen in full, not truncated
#: into a false "unique match".
_ONEMAP_COUNT = 50

_CROSSWALK_METHOD = "nc_onemap_owner_address_match"

#: Bounds concurrent in-flight crosswalk queries. The shared http_client per-host throttle
#: (~0.8-1.5s/request to services.nconemap.gov regardless of concurrency) is what actually paces
#: the WIRE requests -- this mainly keeps the asyncio task count sane (same role
#: _STATEWIDE_CONCURRENCY plays in nc_heir_estate_parcels.py) and lets one task's retry SLEEP
#: (_crosswalk_one, below -- outside the throttle lock) overlap with another task's actual
#: request instead of serializing both.
_CROSSWALK_CONCURRENCY = 16


# --------------------------------------------------------------------------------- pure parsing

def extract_file_url(html: str) -> Optional[str]:
    """The CURRENT dated "Delinquent Taxes" CSV link off Johnston's Files-for-Download page, or
    None when the page no longer links one (the county moved or renamed it)."""
    m = _FILE_LINK_RE.search(html or "")
    if not m:
        return None
    return urljoin(FILES_PAGE_URL, m.group(1))


def _strip_excel_formula(v: str) -> str:
    """Johnston wraps ParcelNumber in an Excel "keep this text" formula: `="08019024"` -> the
    bare value, so a leading-zero parcel never gets reformatted as a number by a spreadsheet."""
    v = (v or "").strip()
    m = re.match(r'^="(.*)"$', v)
    return m.group(1) if m else v


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def parse_delinquent_csv(data: bytes) -> list[dict]:
    """Every (parcel, tax-year) row of Johnston's own UTF-16 delinquent-tax export. Pure, no I/O
    -- `data` is the file's raw bytes, decoded here."""
    text = data.decode("utf-16")
    reader = csv.reader(io.StringIO(text))
    header = [h.strip() for h in next(reader, [])]
    rows: list[dict] = []
    for parts in reader:
        if not parts or not any((p or "").strip() for p in parts):
            continue
        rec = dict(zip(header, parts))
        parcel = _strip_excel_formula(rec.get("ParcelNumber", ""))
        if not parcel:
            continue
        try:
            year = int(_clean(rec.get("Taxyear")))
        except (TypeError, ValueError):
            year = None
        try:
            due = round(float(_clean(rec.get("TotalDue")) or "0"), 2)
        except (TypeError, ValueError):
            due = None
        rows.append({
            "parcel": parcel,
            "year": year,
            "last_name": _clean(rec.get("LastName")).upper(),
            "first_name": _clean(rec.get("FirstName")).upper(),
            "address": _clean(rec.get("PropertyAddress")).upper(),
            "zip": _clean(rec.get("ZipCode")),
            "due": due,
            "bill": _clean(rec.get("Bill")),
            "land_use_type": _clean(rec.get("Type")),
        })
    return rows


def aggregate_by_parcel(rows: list[dict]) -> dict[str, dict]:
    """One dict per LEGACY parcel id: owner name + address the file states (first alphabetically
    when it varies across a parcel's rows -- rare, same convention this crosswalk's own one-off
    predecessor used), the summed TotalDue, and a {year: amount} breakdown. Pure, no I/O."""
    agg: dict[str, dict] = {}
    for r in rows:
        rec = agg.setdefault(r["parcel"], {
            "parcel": r["parcel"], "last_names": set(), "first_names": set(),
            "addresses": set(), "zips": set(), "types": set(),
            "by_year": {}, "bills": [],
        })
        if r["last_name"]:
            rec["last_names"].add(r["last_name"])
        if r["first_name"]:
            rec["first_names"].add(r["first_name"])
        if r["address"]:
            rec["addresses"].add(r["address"])
        if r["zip"]:
            rec["zips"].add(r["zip"])
        if r["land_use_type"]:
            rec["types"].add(r["land_use_type"])
        if r["year"] is not None and r["due"] is not None:
            rec["by_year"][r["year"]] = round(rec["by_year"].get(r["year"], 0.0) + r["due"], 2)
        if r["bill"]:
            rec["bills"].append({"year": r["year"], "bill": r["bill"], "amount": r["due"]})

    out: dict[str, dict] = {}
    for parcel, rec in agg.items():
        out[parcel] = {
            "parcel": parcel,
            "last_name": sorted(rec["last_names"])[0] if rec["last_names"] else "",
            "first_name": sorted(rec["first_names"])[0] if rec["first_names"] else "",
            "address": sorted(rec["addresses"])[0] if rec["addresses"] else "",
            "zip": sorted(rec["zips"])[0] if rec["zips"] else "",
            "land_use_type": sorted(rec["types"])[0] if rec["types"] else "",
            "delinquent_by_year": rec["by_year"],
            "total_delinquent": round(sum(rec["by_year"].values()), 2),
            "years_delinquent": len(rec["by_year"]),
            "bills": rec["bills"],
        }
    return out


def _esc(s: str) -> str:
    """Escape a value for an ArcGIS SQL string literal (single quotes doubled)."""
    return (s or "").replace("'", "''")


def build_where(last_name: str, first_name: str) -> str:
    """The NC OneMap WHERE clause for one legacy parcel's owner: exact last name, PREFIX first
    name (ownname is "LAST, FIRST MIDDLE..."), scoped to Johnston by county name -- the same
    `cntyname` field nc_heir_estate_parcels._where() uses for every statewide-fallback county
    (confirmed live 2026-10-20 to match the equivalent stcntyfips='37101' FIPS form exactly)."""
    return (f"UPPER(cntyname) = 'JOHNSTON' AND "
            f"UPPER(ownname) LIKE UPPER('{_esc(last_name)}, {_esc(first_name)}%')")


def classify_match(file_address: str, candidates: list[dict]) -> dict:
    """The crosswalk verdict for one legacy parcel's owner-name hits against NC OneMap. Pure, no
    I/O -- `candidates` is already a list of attribute dicts (e.g. from `_query()`).

    See the module docstring's "THE MATCH RULE" section for the full rationale (the HOA-entity
    false positive that makes owner name alone insufficient). Returns one of:
      matched                    exactly one candidate's address agrees -> resolved_pin set.
      rejected/owner_not_found   zero candidates.
      rejected/multiple_address_matches  2+ candidates' addresses agree (ambiguous; never guessed).
      ambiguous_no_address_signal        no candidate's address conflicts OR agrees (no signal
                                  either way on this candidate set) -- never accepted.
      rejected/address_conflict  every candidate's address actively conflicts.
      rejected/no_parcel_number  the one address-agreeing candidate carries no usable parno.
    """
    n = len(candidates)
    if n == 0:
        return {"status": "rejected", "reason": "owner_not_found", "candidates": 0}

    matches: list[dict] = []
    unknowns: list[dict] = []
    conflicts: list[dict] = []
    for attrs in candidates:
        site = attrs.get("siteadd") or ""
        rel = address_relation(site, file_address)
        row = dict(attrs, relation=rel)
        if rel == "match":
            matches.append(row)
        elif rel == "unknown":
            unknowns.append(row)
        else:
            conflicts.append(row)

    if len(matches) == 1:
        pin = re.sub(r"[^0-9]", "", matches[0].get("parno") or "")
        if not pin:
            return {"status": "rejected", "reason": "no_parcel_number", "candidates": n}
        return {"status": "matched", "reason": "unique_address_match", "candidates": n,
                "resolved_pin": pin, "candidate": matches[0]}
    if len(matches) > 1:
        return {"status": "rejected", "reason": "multiple_address_matches", "candidates": n}
    if unknowns and not conflicts:
        reason = ("single_candidate_no_house_number" if n == 1
                  else "multiple_candidates_no_house_number")
        return {"status": "ambiguous_no_address_signal", "reason": reason, "candidates": n}
    return {"status": "rejected", "reason": "address_conflict", "candidates": n}


def to_listing(legacy_parcel: str, rec: dict, match: dict, *, file_url: str,
               file_label: str) -> Listing:
    """Builds one `Listing` for a MATCHED crosswalk result. Pure, no I/O."""
    now = datetime.utcnow()
    cand = match["candidate"]
    pin = match["resolved_pin"]
    owner = _clean(cand.get("ownname")) or f"{rec['last_name']}, {rec['first_name']}".strip(", ")
    situs = _clean(cand.get("siteadd")) or None
    by_year = {str(y): amt for y, amt in sorted(rec["delinquent_by_year"].items(), reverse=True)}
    total = rec["total_delinquent"]
    return Listing(
        source=SLUG,
        source_url=file_url,
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state=STATE,
        county=COUNTY,
        parcel_id=pin,
        street_address=situs,
        defendant=owner or None,
        owner_name=owner or None,
        foreclosure_process="tax",
        description=(f"{owner or ''} — {COUNTY} County NC delinquent tax "
                     f"${total:,.2f} owed, {rec['years_delinquent']} year(s) "
                     f"(legacy parcel {legacy_parcel})")[:300],
        first_seen=now,
        last_seen=now,
        raw={
            RAW_KEY: {
                "legacy_parcel": legacy_parcel,
                "resolved_pin": pin,
                "years_delinquent": rec["years_delinquent"],
                "delinquent_by_year": by_year,
                "bill_years": sorted(by_year.keys()),
                "total_delinquent": total,
                "land_use_type": rec.get("land_use_type") or None,
                "crosswalk_method": _CROSSWALK_METHOD,
                "crosswalk_confidence": match["reason"],
                "crosswalk_candidates": match.get("candidates"),
                "onemap_parno": cand.get("parno"),
                "file_snapshot": file_label,
                "url": file_url,
            },
        },
    )


# --------------------------------------------------------------------------------- scraper

class JohnstonDelinquentTaxCrosswalk(BaseScraper):
    slug = SLUG
    name = "Johnston County NC Delinquent Tax -> NC OneMap Crosswalk"
    category = "county_tax"
    # Measured live 2026-10-20: 900s (the original estimate) was NOT enough -- a soft-timeout
    # salvage fired at 344/539 parcels checked (self.partial still shipped the 119 matched so
    # far, per BaseScraper's own discipline, but a real ingest wants the FULL file checked in
    # one run). The retry in _crosswalk_one (below) adds real cost on every genuine zero-match
    # owner (most of the slowest cases): measured ~2.6s/parcel average that run. Generous margin
    # over a full 539-parcel run at that rate (~23-24 min).
    timeout_s = 1800.0
    expected_min_count = 0
    optional = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.run_stats: dict = {
            "distinct_parcels": 0, "parcels_checked": 0, "matched": 0,
            "rejected": 0, "ambiguous": 0, "errors": 0, "reasons": {},
        }

    async def _file_url(self, http) -> tuple[str, str]:
        r = await http.get(FILES_PAGE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)
        r.raise_for_status()
        url = extract_file_url(r.text)
        if not url:
            raise RuntimeError(
                "Files-for-Download page no longer links a DelinquentTaxPublicRecordsFile")
        return url, url.rsplit("/", 1)[-1]

    async def _crosswalk_one(self, http, rec: dict) -> Optional[dict]:
        """Queries NC OneMap for one legacy parcel's owner and classifies the result.

        `enrichment_owner_mailing._query_page` swallows EVERY exception internally and returns
        an empty list (its own module docstring note on the "same shape as a genuine zero-match
        query" risk) -- live-confirmed during this scraper's own canary test (2026-10-20): the
        SAME owner query ("RADFORD, EULA%") returned 0 features on one call and 2 on an
        immediately-repeated one, with a `httpx.ReadTimeout` observed on a bare repro of the
        first shape. Without a retry here, a transient network blip on the FIRST attempt is
        indistinguishable from a genuine "this owner is not on the roll" and would wrongly
        reject a legacy parcel that a second try resolves correctly -- a real cost given this
        producer's whole purpose is not under-counting real leads. A GENUINE zero-match stays
        zero on retry (no behavior change for it, just 1-2 extra cheap paced requests); a
        transient one usually recovers.

        2 attempts, not 3: the live repro that motivated this recovered on the VERY NEXT call
        with no sleep at all, and this project's 539-parcel live run (2026-10-20) showed the
        cost of retrying lands almost entirely on GENUINE zero-match owners (the slow path,
        since every address-conflict/ambiguous/matched case already got a non-empty answer on
        attempt 1 and never retries) -- a 3rd attempt bought negligible extra recovery for a
        real third of the run's total time. A short, flat 0.5s gap (not escalating) is enough
        margin over the throttle's own ~0.8-1.5s pacing for a transient blip to clear.
        """
        where = build_where(rec["last_name"], rec["first_name"])
        feats: list[dict] = []
        for attempt in range(2):
            try:
                feats = await _query(http, _ONEMAP_SPEC["url"], where,
                                     out_fields=_ONEMAP_OUT_FIELDS, count=_ONEMAP_COUNT)
            except Exception as exc:  # noqa: BLE001 - one parcel's failure must not sink the run
                log.warning("johnston_tax_crosswalk.query_fail", parcel=rec["parcel"],
                           attempt=attempt, error=str(exc)[:160])
                feats = []
            if feats:
                break
            if attempt == 0:
                await asyncio.sleep(0.5)
        return classify_match(rec["address"], feats)

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_JOHNSTON_TAX_CROSSWALK") == "0":
            return []
        out = self.partial
        async with client(timeout=30.0) as http:
            try:
                file_url, file_label = await self._file_url(http)
            except Exception as exc:  # noqa: BLE001
                log.warning("johnston_tax_crosswalk.files_page_fail", error=str(exc)[:160])
                return out
            try:
                r = await http.get(file_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60.0)
                r.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                log.warning("johnston_tax_crosswalk.csv_fail", url=file_url, error=str(exc)[:160])
                return out

            try:
                rows = parse_delinquent_csv(r.content)
            except Exception as exc:  # noqa: BLE001 - a shape change must not crash the run
                log.warning("johnston_tax_crosswalk.parse_fail", error=str(exc)[:160])
                return out
            agg = aggregate_by_parcel(rows)
            self.run_stats["distinct_parcels"] = len(agg)
            log.info("johnston_tax_crosswalk.parsed", distinct_parcels=len(agg), rows=len(rows),
                     file=file_label)

            sem = asyncio.Semaphore(_CROSSWALK_CONCURRENCY)

            async def _bounded(legacy_parcel: str, rec: dict):
                async with sem:
                    match = await self._crosswalk_one(http, rec)
                return legacy_parcel, rec, match

            for coro in asyncio.as_completed(
                [_bounded(p, rec) for p, rec in agg.items()]
            ):
                legacy_parcel, rec, match = await coro
                self.run_stats["parcels_checked"] += 1
                if match is None:
                    self.run_stats["errors"] += 1
                    continue
                reason = match["reason"]
                self.run_stats["reasons"][reason] = self.run_stats["reasons"].get(reason, 0) + 1
                if match["status"] == "matched":
                    self.run_stats["matched"] += 1
                    out.append(to_listing(legacy_parcel, rec, match,
                                          file_url=file_url, file_label=file_label))
                elif match["status"] == "ambiguous_no_address_signal":
                    self.run_stats["ambiguous"] += 1
                else:
                    self.run_stats["rejected"] += 1

        log.info("johnston_tax_crosswalk.done", listings=len(out), **self.run_stats)
        return out


if __name__ == "__main__":

    async def _main() -> None:
        s = JohnstonDelinquentTaxCrosswalk()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)} stats={s.run_stats}")
        for li in rows[:12]:
            print(f"  {li.county:10} {(li.defendant or '')[:30]:30} "
                  f"situs={(li.street_address or '')[:30]} pin={li.parcel_id}")

    asyncio.run(_main())
