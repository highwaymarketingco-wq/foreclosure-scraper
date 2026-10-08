"""SC estate notices statewide from scpublicnotices.com (SC Press Association): what publicnoticesc.py misses.

THE GAP. publicnoticesc.py drives the portal's own 'Popular Searches' dropdown with ONE preset,
'Foreclosures' (value 4), and keeps only the 7 Upstate footprint counties. The same dropdown has
two estate presets it never runs (read off the live <select> on 2026-10-07):
    30  Notice to Creditors        23  Probate Notices
Every SC estate must publish a Notice to Creditors (S.C. Code 62-3-801), so these two presets are
the statewide list of estates being opened, all 46 counties, about 1,000 notices each over the
portal's default 60 days.

WHAT CAN BE READ. Only the results grid: each row shows a ~250-character preview of the notice.
Details.aspx (the full text) sits behind a click-through Terms of Use and a Cloudflare Turnstile
CAPTCHA, the same wall publicnoticesc.py documents; it is not fetched. On the live grid (2026-10-07,
3 pages a preset) 25 of 150 Notice to Creditors rows and 1 of 150 Probate Notices rows showed the
caption 'IN THE MATTER OF: <DECEDENT> ... CASE NUMBER: 2026-ES-27-00206' in the preview; the rest
are cut off inside the boilerplate before any name. The personal
representative's name and address always sit past the cut, so this reader yields the DECEDENT and
the CASE NUMBER (the county is the case number's two-digit code), never a representative. A
person opens the Details link (and passes the CAPTCHA themselves) to read the representative.

Each named estate -> one PROBATE_NOTICE row in the same raw shape as sc_probate_notices.py
(raw['sc_probate_notice'] = {estate, case_number, county, date_of_death?, personal_representative?})
so the resolver, the scorer and enrichment_heir_candidates read it the same way. The preview text
itself is not stored (it can carry names past the decedent's).

Polite: _obit_common.PoliteFetcher (>= 1.6 s between requests, ordinary UA, a wall stops the run).
Gate off with FORECLOSURE_SC_ESTATE_NOTICES=0; PUBLICNOTICESC_ESTATE_MAX_PAGES (default 20).

SOURCE-COMPLETENESS AUDIT (2026-10-08). The VM's first run (gated run, 2026-10-08) returned 0 rows
in 35 s as ZERO_RESULT, with no warning in the log; the same code on the Mac that day read 100
previews (page 1 of each preset) and named 9 estates. Each preset's error went only into the
info-level stats, so the run could not say why. Now: a failing preset logs a warning and is retried
once after a pause (a wall is never retried), page errors log a warning, and a run that ends with
no rows because every attempt failed re-raises the last error, so safe_run reports ERROR / BLOCKED /
TIMEOUT with the reason instead of a silent ZERO_RESULT.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...obituary_text import parse_probate_notice
from ...quiet_title.fetch import Walled
from . import _press_assoc as pa
from ._obit_common import PoliteFetcher
from .publicnoticesc import BASE_URL, GRID, PRE, _NEXT_BTN_RENDERED_ID, _hidden_fields

log = structlog.get_logger()

PRESETS = {"30": "Notice to Creditors", "23": "Probate Notices"}
MAX_PAGES = int(os.environ.get("PUBLICNOTICESC_ESTATE_MAX_PAGES", "20"))
_DETAIL_URL = "https://www.scpublicnotices.com/Details.aspx?ID={}"
#: Pause before the one retry of a preset whose search postbacks failed (not a wall).
_RETRY_PAUSE_S = 15.0

#: SC county code inside an estate case number (YYYY-ES-CC-NNNNN): the state's alphabetical order
SC_COUNTY_CODES = {f"{i:02d}": n for i, n in enumerate((
    "Abbeville", "Aiken", "Allendale", "Anderson", "Bamberg", "Barnwell", "Beaufort", "Berkeley", "Calhoun",
    "Charleston", "Cherokee", "Chester", "Chesterfield", "Clarendon", "Colleton", "Darlington", "Dillon",
    "Dorchester", "Edgefield", "Fairfield", "Florence", "Georgetown", "Greenville", "Greenwood", "Hampton",
    "Horry", "Jasper", "Kershaw", "Lancaster", "Laurens", "Lee", "Lexington", "McCormick", "Marion",
    "Marlboro", "Newberry", "Oconee", "Orangeburg", "Pickens", "Richland", "Saluda", "Spartanburg", "Sumter",
    "Union", "Williamsburg", "York"), start=1)}
_COUNTY_NAMES = {n.lower(): n for n in SC_COUNTY_CODES.values()}

_CASE = re.compile(r"\b(\d{4})\s*-?\s*ES\s*-?\s*(\d{2})\s*-?\s*(\d{3,7})\b", re.I)
_MATTER = re.compile(r"\bIN\s+THE\s+MATTER\s+OF\s*:?\s*(?:THE\s+ESTATE\s+OF\s*:?\s*)?"
                     r"([A-Z][A-Za-z.'\- ]{3,70}?)\s*(?=\(|,|\bIN\s+THE\b|\bDECEASED\b|\bCASE\b|\bNOTICE\b|$)", re.I)
_COUNTY_OF = re.compile(r"\bCOUNTY\s+OF\s*:?\s*([A-Z][A-Za-z]+)\b", re.I)


def parse_preview(text: str) -> Optional[dict]:
    """{estate, case_number, county, date_of_death?, personal_representative?} from one grid
    preview, or None when the preview names no decedent."""
    t = re.sub(r"\s+", " ", text or "").strip()
    estate = None
    m = _MATTER.search(t)
    if m:
        estate = re.sub(r"\s+", " ", m.group(1)).strip(" ,.-")
    pn = parse_probate_notice(t)
    if not estate and pn.get("decedent"):
        estate = pn["decedent"]
    if not estate or len(estate.split()) < 2:
        return None
    case = county = None
    cm = _CASE.search(t)
    if cm:
        case = f"{cm.group(1)}ES{cm.group(2)}{cm.group(3).zfill(5)}"
        county = SC_COUNTY_CODES.get(cm.group(2))
    if not county:
        co = _COUNTY_OF.search(t[:200])
        if co:
            county = _COUNTY_NAMES.get(co.group(1).lower())
    if not county:
        return None
    if estate.isupper():
        estate = " ".join(w.capitalize() if len(w) > 2 else w for w in estate.split())
    out = {"estate": estate, "case_number": case, "county": county, "date_of_death": pn.get("date_of_death")}
    reps = pn.get("representatives") or []
    if reps:
        out["personal_representative"] = reps[0]["name"]
        if reps[0].get("address"):
            out["pr_address"] = reps[0]["address"]
    return {k: v for k, v in out.items() if v}


def to_listing(notice: dict, est: dict, slug: str, preset: str) -> Listing:
    now = datetime.utcnow()
    published = notice.get("published_at")
    return Listing(
        source=slug,
        source_url=_DETAIL_URL.format(notice.get("notice_id")) if notice.get("notice_id") else BASE_URL,
        listing_type=ListingType.PROBATE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC", county=est["county"],
        owner_name=est["estate"], defendant=est["estate"],
        case_number=est.get("case_number"),
        foreclosure_process="probate",
        description=f"{est['county']} SC estate notice ({PRESETS[preset]}) - {est['estate']}"
                    + (f" | {est['case_number']}" if est.get("case_number") else ""),
        first_seen=now, last_seen=now,
        raw={
            "sc_probate_notice": est,
            "public_notice": {"site": "scpublicnotices.com", "notice_id": notice.get("notice_id"),
                              "publication": notice.get("publication") or None,
                              "publication_county": notice.get("county_meta") or None,
                              "published_at": published.isoformat() if published else None,
                              "kind": "estate", "preset": PRESETS[preset], "preview_truncated": True},
            "life_event": "death",
            "dateless": True,
            "relationship_signal": {"kind": "probate", "keyword": "notice to creditors"},
        },
    )


class PublicNoticeSCEstates(BaseScraper):
    slug = "public_notices.publicnoticesc_estates"
    name = "SC estate notices statewide (SCPA portal: Notice to Creditors + Probate Notices previews)"
    category = "probate"
    timeout_s = 900.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_SC_ESTATE_NOTICES", "1") == "0":
            return []
        out = self.partial
        seen: set[str] = set()
        stats: dict = {}
        errors: list[BaseException] = []
        async with PoliteFetcher() as pf:
            for preset in PRESETS:
                st = stats.setdefault(PRESETS[preset], {"pages": 0, "notices": 0, "named": 0})
                html = session_url = None
                for attempt in (1, 2):
                    try:
                        html, session_url = await self._open_preset(pf, preset)
                        if attempt > 1:
                            st["recovered_from"] = st.pop("error", None)
                        break
                    except Walled as w:
                        st["walled"] = w.reason
                        errors.append(w)
                        break
                    except Exception as exc:  # noqa: BLE001
                        st["error"] = str(exc)[:120]
                        log.warning("publicnoticesc_estates.preset_failed", preset=PRESETS[preset],
                                    attempt=attempt, error=f"{type(exc).__name__}: {str(exc)[:160]}")
                        if attempt == 1:
                            await asyncio.sleep(_RETRY_PAUSE_S)
                        else:
                            errors.append(exc)
                if "walled" in st:
                    break
                if html is None:
                    continue
                labels: set[str] = set()
                while True:
                    st["pages"] += 1
                    for n in pa.parse_grid(html):
                        st["notices"] += 1
                        est = parse_preview(n.get("text") or "")
                        if not est:
                            continue
                        key = est.get("case_number") or f"{est['county']}|{est['estate']}"
                        if key in seen:
                            continue
                        seen.add(key)
                        st["named"] += 1
                        out.append(to_listing(n, est, self.slug, preset))
                    cur, tot = pa.current_page(html), pa.total_pages(html)
                    if cur is not None:
                        labels.add(str(cur))
                    if st["pages"] >= MAX_PAGES or (cur and tot and cur >= tot) or _NEXT_BTN_RENDERED_ID not in html \
                            or f'id="{_NEXT_BTN_RENDERED_ID}" disabled="disabled"' in html:
                        break
                    form = dict(_hidden_fields(html))
                    form.update({"__EVENTTARGET": "", "__EVENTARGUMENT": f"",
                                 f"{GRID}$ctl01$btnNext.x": "5", f"{GRID}$ctl01$btnNext.y": "5"})
                    try:
                        html = await pf.post(session_url, form)
                    except Walled as w:
                        st["walled"] = w.reason
                        errors.append(w)
                        break
                    except Exception as exc:  # noqa: BLE001
                        st["error"] = str(exc)[:120]
                        log.warning("publicnoticesc_estates.page_failed", preset=PRESETS[preset],
                                    page=st["pages"] + 1, error=f"{type(exc).__name__}: {str(exc)[:160]}")
                        errors.append(exc)
                        break
                    nxt = pa.current_page(html)
                    if nxt is not None and str(nxt) in labels:
                        break
        log.info("publicnoticesc_estates.done", rows=len(out), presets=stats)
        self.last_stats = stats
        if not out and errors:
            # Nothing read and something failed: say so (safe_run classifies the error)
            # instead of returning an empty list that reads as "the portal had no estates".
            raise errors[-1]
        return out

    @staticmethod
    async def _open_preset(pf, preset: str) -> tuple[str, str]:
        """Open a fresh portal session, run one 'Popular Searches' preset and set 50 rows a page.
        Returns (grid html, session url)."""
        html, session_url = await pf.get_with_url(BASE_URL)
        form = dict(_hidden_fields(html))
        form.update({"__EVENTTARGET": PRE + "ddlPopularSearches", "__EVENTARGUMENT": "",
                     PRE + "ddlPopularSearches": preset})
        html = await pf.post(session_url, form)
        form = dict(_hidden_fields(html))
        form.update({"__EVENTTARGET": f"{GRID}$ctl01$ddlPerPage", "__EVENTARGUMENT": "",
                     f"{GRID}$ctl01$ddlPerPage": "50"})
        html = await pf.post(session_url, form)
        return html, session_url
