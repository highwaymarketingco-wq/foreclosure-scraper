"""Static config: counties, source toggles, run knobs."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class County:
    name: str
    state: str
    fips: str
    seat: str
    aliases: tuple[str, ...] = ()


SC_COUNTIES: tuple[County, ...] = (
    # Upstate SC corridor. 2026-05-07c restored Greenville per user
    # direction (it was in the 2026-05a "narrow" pruning, but the user
    # confirmed Greenville is wanted — sc_courtrosters already targets
    # it, so adding it back unblocks that scraper's listings).
    County("Spartanburg", "SC", "45083", "Spartanburg"),
    County("Greenville",  "SC", "45045", "Greenville"),
    County("Anderson", "SC", "45007", "Anderson"),
    County("Pickens", "SC", "45077", "Pickens"),
    County("Oconee", "SC", "45073", "Walhalla"),
    County("Cherokee", "SC", "45021", "Gaffney"),
    County("Union", "SC", "45087", "Union"),
    County("Laurens", "SC", "45059", "Laurens"),
)

NC_COUNTIES: tuple[County, ...] = (
    # WNC mountains + foothills + Charlotte-metro footprint. Scope is
    # the upstate-SC / WNC corridor where the user actually invests.
    # Iteration history:
    #   2026-05-07a — pruned 11 eastern-NC counties (Wake/Forsyth/
    #     Guilford/Durham/Cumberland/Alamance/Iredell/Cabarrus/Union/
    #     Pitt/Johnston). Too far east of WNC.
    #   2026-05-07b — pruned 3 more (Mecklenburg, Madison, Yancey).
    #     Mecklenburg = Charlotte, dropped per user direction.
    County("Rutherford", "NC", "37161", "Rutherfordton"),
    County("Cleveland", "NC", "37045", "Shelby"),
    County("Henderson", "NC", "37089", "Hendersonville"),
    County("Polk", "NC", "37149", "Columbus"),
    County("Gaston", "NC", "37071", "Gastonia"),
    County("Buncombe", "NC", "37021", "Asheville"),
    County("Transylvania", "NC", "37175", "Brevard"),
    County("McDowell", "NC", "37111", "Marion"),
    County("Lincoln", "NC", "37109", "Lincolnton"),
    County("Mitchell", "NC", "37121", "Bakersville"),
    County("Burke", "NC", "37023", "Morganton"),
    # User-key coastal NC counties (Wilmington area + Onslow).
    County("New Hanover", "NC", "37129", "Wilmington"),
    County("Brunswick", "NC", "37019", "Bolivia"),
    County("Onslow", "NC", "37133", "Jacksonville"),
)

ALL_COUNTIES: tuple[County, ...] = SC_COUNTIES + NC_COUNTIES

COUNTY_BY_KEY: dict[str, County] = {
    f"{c.state}-{c.name.lower()}": c for c in ALL_COUNTIES
}


def in_scope(county_name: str | None, state: str | None) -> bool:
    """Return True if a (county, state) pair is one we track.

    Deny set takes precedence over the allow list AND the zip-prefix
    fallback (in main._in_scope) — listings in these counties never
    appear regardless of how they were attributed.
    """
    if not county_name or not state:
        return False
    norm = county_name.lower().replace(" county", "").strip()
    state_u = state.upper()
    if (norm.title(), state_u) in SCOPE_DENY_COUNTIES_NORMALIZED:
        return False
    key = f"{state_u}-{norm}"
    return key in COUNTY_BY_KEY


# Counties where listings should NEVER appear, even when they came from
# a SCOPE_BYPASS source (CourtListener bankruptcy/civil/adversary) or
# matched on SCOPE_ZIP_PREFIXES (e.g. 287xx covers Haywood NC, 296xx
# covers Abbeville SC). User direction 2026-05-07: explicitly drop
# these even though they'd otherwise sneak in via the zip fallback.
SCOPE_DENY_COUNTIES: tuple[tuple[str, str], ...] = (
    # 2026-05-07b — Charlotte + adjacent WNC pruning
    ("Mecklenburg", "NC"),  # Charlotte — out of user's flip target
    ("Madison", "NC"),
    ("Yancey", "NC"),
    ("Haywood", "NC"),
    ("Abbeville", "SC"),
    # 2026-05-07d — eastern NC counties pruned in rollback A but
    # leaking back in via SCOPE_BYPASS_SOURCES (CourtListener
    # bankruptcy/civil/adversary, which skip county checks). Run #16
    # forensics found 20 Cabarrus + 19 Union NC + 4 Rowan + 3 Iredell
    # + 1 Swain BK listings showing on the dashboard despite their
    # counties not being in NC_COUNTIES. Explicit deny plugs that.
    ("Wake", "NC"),
    ("Forsyth", "NC"),
    ("Guilford", "NC"),
    ("Durham", "NC"),
    ("Cumberland", "NC"),
    ("Alamance", "NC"),
    ("Iredell", "NC"),
    ("Cabarrus", "NC"),
    ("Union", "NC"),
    ("Pitt", "NC"),
    ("Johnston", "NC"),
    ("Rowan", "NC"),
    ("Swain", "NC"),
    # SC counties south of Newberry / around Augusta — never were in
    # SC_COUNTIES but BK / lis pendens leak via the 296 zip prefix.
    ("Newberry", "SC"),
    ("Greenwood", "SC"),
)
# Pre-normalized for fast lookup in in_scope() + main._in_scope.
SCOPE_DENY_COUNTIES_NORMALIZED: frozenset[tuple[str, str]] = frozenset(
    (c, s) for c, s in SCOPE_DENY_COUNTIES
)


# ZIP code prefixes commonly inside our scope. Used as a fallback
# when a listing has no explicit county field but does have a ZIP.
SCOPE_ZIP_PREFIXES: tuple[str, ...] = (
    # SC upstate proper (296xx is Greenville+Spartanburg+Anderson+Pickens+Oconee+
    # Laurens+Union+Cherokee). 298xx covers the south-of-Newberry strip we
    # explicitly excluded — kept off scope so we don't pull stale southern data.
    "293",  # Cherokee SC (Gaffney area)
    "296",  # Greenville+Spartanburg+Anderson+Pickens+Oconee+Laurens+Union
    # NC western piedmont + WNC mountains: Asheville/Hendersonville/Charlotte
    # corridor + Gaston/Cleveland/Rutherford/Polk
    "280", "281", "282", "287", "288",
    # NC coastal — user-key Brunswick/New Hanover/Onslow. Without 284,
    # HomeHarvest distressed listings tagged only by zip (no county
    # field) failed _in_scope. 284 = Wilmington/Brunswick/Pender/Sampson.
    "284",
)


@dataclass(frozen=True)
class RuntimeConfig:
    sheet_id: str
    google_service_account_json: str
    gmail_sender: str
    gmail_app_password: str
    email_recipients: tuple[str, ...]
    apify_token: str
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.5 Safari/605.1.15 ForeclosureScraper/0.1"
    )
    request_timeout_s: float = 30.0
    request_retries: int = 3
    parallel_scrapers: int = 8
    link_check_workers: int = 24
    sale_horizon_days: int = 120  # only keep listings with a sale date within this many days

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        recipients = tuple(
            r.strip()
            for r in os.environ.get(
                "EMAIL_RECIPIENTS",
                "greghhigh@gmail.com,cashrandolphhigh@gmail.com",
            ).split(",")
            if r.strip()
        )
        return cls(
            sheet_id=os.environ.get("SHEET_ID", ""),
            google_service_account_json=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
            gmail_sender=os.environ.get("GMAIL_SENDER", "greghhigh@gmail.com"),
            gmail_app_password=os.environ.get("GMAIL_APP_PASSWORD", ""),
            email_recipients=recipients,
            apify_token=os.environ.get("APIFY_TOKEN", ""),
        )
