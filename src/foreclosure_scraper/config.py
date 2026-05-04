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
    # Scope narrowed (per user 2026-05): drop Greenville, Newberry, Abbeville,
    # Greenwood. Nothing south of Newberry, nothing around Augusta.
    County("Spartanburg", "SC", "45083", "Spartanburg"),
    County("Anderson", "SC", "45007", "Anderson"),
    County("Pickens", "SC", "45077", "Pickens"),
    County("Oconee", "SC", "45073", "Walhalla"),
    County("Cherokee", "SC", "45021", "Gaffney"),
    County("Union", "SC", "45087", "Union"),
    County("Laurens", "SC", "45059", "Laurens"),
)

NC_COUNTIES: tuple[County, ...] = (
    County("Rutherford", "NC", "37161", "Rutherfordton"),
    County("Cleveland", "NC", "37045", "Shelby"),
    County("Henderson", "NC", "37089", "Hendersonville"),
    County("Polk", "NC", "37149", "Columbus"),
    County("Gaston", "NC", "37071", "Gastonia"),
    County("Mecklenburg", "NC", "37119", "Charlotte"),
    County("Buncombe", "NC", "37021", "Asheville"),
    County("Transylvania", "NC", "37175", "Brevard"),
    County("McDowell", "NC", "37111", "Marion"),
    County("Lincoln", "NC", "37109", "Lincolnton"),
    County("Madison", "NC", "37115", "Marshall"),
    County("Yancey", "NC", "37199", "Burnsville"),
    County("Mitchell", "NC", "37121", "Bakersville"),
    County("Burke", "NC", "37023", "Morganton"),
)

ALL_COUNTIES: tuple[County, ...] = SC_COUNTIES + NC_COUNTIES

COUNTY_BY_KEY: dict[str, County] = {
    f"{c.state}-{c.name.lower()}": c for c in ALL_COUNTIES
}


def in_scope(county_name: str | None, state: str | None) -> bool:
    """Return True if a (county, state) pair is one we track."""
    if not county_name or not state:
        return False
    key = f"{state.upper()}-{county_name.lower().replace(' county', '').strip()}"
    return key in COUNTY_BY_KEY


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
