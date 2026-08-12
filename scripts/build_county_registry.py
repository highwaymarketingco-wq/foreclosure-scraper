#!/usr/bin/env python3
"""Every county record system in NC + SC, whether we can reach it or not.

WHY THIS EXISTS
    The source list in this project is the set of things somebody happened to
    find. Nothing ever enumerated the UNIVERSE — all 100 NC counties and all 46
    SC counties, and for each the four systems that actually hold distress
    records: the register of deeds, the court, the tax/delinquent office, and
    the assessor.

    Without that denominator you cannot answer "do we have all the county
    recorders?" at all. You can only answer "are the ones on our list working?",
    which is a different and much weaker question — and it is the question this
    project had been answering for months.

    Accessibility is recorded but is NOT a filter. A county whose recorder sits
    behind a login still belongs in the registry, because knowing it exists and
    is walled is knowledge; silently omitting it looks identical to it not
    existing.

WHAT IT PRODUCES
    docs/COUNTY_SYSTEMS_REGISTRY.md and the matching .json — one row per
    (county, system) with: the URL if found, whether it resolves, what kind of
    gate sits in front, and whether the host appears anywhere in src/.

METHOD, AND ITS LIMITS
    County names come from authoritative directories (nccourts.gov/locations for
    NC, sccounties.org for SC). NC court URLs are exact. Everything else is
    discovered by probing the URL patterns these counties actually use — which
    finds the common shapes and WILL miss counties on an unusual host. A miss is
    recorded as "not found", never as "does not exist"; the two are different and
    the file says so per row.

USAGE
    uv run python scripts/build_county_registry.py            # full run
    uv run python scripts/build_county_registry.py --state SC
    uv run python scripts/build_county_registry.py --limit 8  # smoke test
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
OUT_MD = REPO / "docs" / "COUNTY_SYSTEMS_REGISTRY.md"
OUT_JSON = REPO / "docs" / "county_systems_registry.json"

NC_COUNTIES: list[str] = []
SC_COUNTIES: list[str] = []


def _get(url: str, timeout: int = 12):
    try:
        from curl_cffi import requests as creq
        return creq.get(url, impersonate="chrome", timeout=timeout,
                        allow_redirects=True)
    except Exception:  # noqa: BLE001
        return None


def load_counties() -> None:
    """Authoritative county lists. NC from the courts directory, SC from SCAC."""
    global NC_COUNTIES, SC_COUNTIES
    r = _get("https://www.nccourts.gov/locations", 30)
    if r is not None and r.status_code == 200:
        NC_COUNTIES = sorted({
            re.sub(r"-county.*$", "", h.split("/locations/")[1])
            for h in re.findall(r'href="(/locations/[a-z-]+-county[^"]*)"', r.text)
        })
    r = _get("https://www.sccounties.org/county-information", 30)
    if r is not None and r.status_code == 200:
        SC_COUNTIES = sorted({
            n.strip().lower().replace(" ", "-")
            for n in re.findall(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\sCounty\b", r.text)
        })


#: URL shapes these counties genuinely use. Ordered cheapest-first; the first
#: that answers 200 wins. Deliberately not exhaustive — see METHOD above.
PATTERNS: dict[str, list[str]] = {
    # Widened 2026-08-12 from what the first full run actually hit: of 42
    # recorders located, 19 were <county>deeds.com, 16 a /register-of-deeds/
    # path on the county site, 3 <county>rod.com. The search subdomain shape
    # (search.<county>deeds.com) was found by hand on Haywood and Yancey and was
    # missing entirely, as were the vendor-hosted portals several counties use
    # instead of their own domain.
    "recorder": [
        "https://{c}rod.com/", "https://www.{c}rod.com/",
        "https://{c}deeds.com/", "https://www.{c}deeds.com/",
        "http://search.{c}deeds.com/", "https://search.{c}deeds.com/",
        "https://deeds.{c}{st}.gov/", "https://deeds.{c}county{st}.gov/",
        "https://rod.{c}county{st}.gov/",
        "https://registerofdeeds.{c}county{st}.gov/",
        "https://registerofdeeds.{c}{st}.gov/",
        "https://{c}countync.gov/register-of-deeds/",
        "https://www.{c}countync.gov/register-of-deeds/",
        "https://{c}countysc.gov/register-of-deeds/",
        "https://www.{c}county{st}.gov/departments/register-of-deeds/",
        "https://www.{c}county{st}.gov/departments/register_of_deeds/index.php",
        "https://{c}countync.gov/county-services/register-of-deeds/",
        # vendor-hosted portals seen in the wild in this footprint
        "https://{c}rod.permitium.com/rod",
        "https://cotthosting.com/{ST}{C}EXTERNAL/LandRecords/protected/v4/SrchName.aspx",
        "https://{c}.landmarkweb.net/",
        "https://{c}rod.org/", "https://www.{c}rod.org/",
    ],
    "tax": [
        "https://{c}countysc.gov/delinquent-tax/",
        "https://www.{c}countync.gov/tax/",
        "https://tax.{c}county{st}.gov/",
        "https://{c}county{st}.gov/tax-collector/",
    ],
    "assessor": [
        "https://qpublic.schneidercorp.com/Application.aspx?App={C}County{ST}&Layer=Parcels&PageType=Search",
    ],
}

GATE_SIGNALS = (
    ("captcha", "CAPTCHA"), ("recaptcha", "reCAPTCHA"),
    ("data mining", "ToS-ban"), ("subscription", "subscription"),
    ("log in", "login"), ("login", "login"),
    ("i agree", "agree-gate"), ("disclaimer", "disclaimer"),
)


def gates_of(html: str) -> list[str]:
    b = (html or "").lower()
    out = []
    for k, label in GATE_SIGNALS:
        if k in b and label not in out:
            out.append(label)
    return out


#: Counties whose name is shared with a county in another state. A URL built
#: from the name alone can silently land on the wrong one, and these sites often
#: never name their state: hendersondeeds.com is Henderson County KENTUCKY and
#: wilsondeeds.com is Wilson County TENNESSEE. Both were about to be adopted as
#: NC register-of-deeds sources purely because the pattern matched.
#:
#: This is not a complete list of shared names — it is the ones in this
#: footprint that a `<county>deeds.com` guess can actually collide with.
AMBIGUOUS_NAMES = {
    "henderson", "wilson", "clay", "haywood", "york", "florence", "berkeley",
    "dorchester", "jackson", "lincoln", "montgomery", "orange", "union",
    "warren", "franklin", "greene", "jones", "monroe",
    "lee", "madison",
    "randolph", "richmond", "washington", "wayne", "chester", "lancaster",
    "marion", "marlboro", "newberry", "sumter",
}


def state_confirmed(county: str, state: str, url: str, html: str) -> bool | None:
    """Is this really that state's county? True / False / None = undetermined.

    Checked in the order the evidence is trustworthy: an explicit state name or
    a state-qualified domain in the page beats anything inferred. A county whose
    name is nationally unique needs no check at all.
    """
    if county.replace("-", "").lower() not in AMBIGUOUS_NAMES:
        return True  # only one county in the US has this name
    full = {"NC": "north carolina", "SC": "south carolina"}[state.upper()]
    other = {"NC": "south carolina", "SC": "north carolina"}[state.upper()]
    b = (html or "").lower()
    if full in b and other not in b:
        return True
    # state-qualified domains, e.g. deeds.claync.us / haywoodcountync.gov
    if re.search(rf"[a-z]+(?:county)?{state.lower()}\.(?:gov|us|org)", b):
        return True
    if other in b and full not in b:
        return False
    return None


def probe_system(county: str, state: str, kind: str) -> dict:
    c = county.replace("-", "")
    row = {"county": county, "state": state, "system": kind,
           "url": None, "status": None, "gates": [], "found": False,
           "state_confirmed": None}
    for pat in PATTERNS[kind]:
        url = pat.format(c=c, C=county.replace("-", " ").title().replace(" ", ""),
                         st=state.lower(), ST=state.upper())
        r = _get(url)
        if r is not None and r.status_code == 200 and len(r.content) > 2000:
            confirmed = state_confirmed(county, state, url, r.text)
            row.update(url=url, status=r.status_code, found=True,
                       gates=gates_of(r.text), state_confirmed=confirmed)
            # A page that positively identifies as the OTHER state is not this
            # county's system. Keep looking rather than recording a wrong hit.
            if confirmed is False:
                row.update(url=None, found=False)
                continue
            return row
        if r is not None and row["status"] is None:
            row["status"] = r.status_code
    return row


def in_src(url: str | None) -> bool:
    if not url:
        return False
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().lstrip("www.")
    if not host:
        return False
    return bool(subprocess.run(["grep", "-rl", host, str(SRC)],
                               capture_output=True, text=True).stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", choices=["NC", "SC"], help="one state only")
    ap.add_argument("--limit", type=int, default=0, help="first N counties (smoke test)")
    args = ap.parse_args()

    load_counties()
    if not NC_COUNTIES and not SC_COUNTIES:
        print("could not load county directories — aborting rather than "
              "writing a registry that silently omits counties")
        return 1

    todo = []
    for st, counties in (("NC", NC_COUNTIES), ("SC", SC_COUNTIES)):
        if args.state and st != args.state:
            continue
        cs = counties[: args.limit] if args.limit else counties
        for c in cs:
            for kind in PATTERNS:
                todo.append((c, st, kind))

    print(f"probing {len(todo)} (county, system) pairs "
          f"across {len(NC_COUNTIES)} NC + {len(SC_COUNTIES)} SC counties ...",
          file=sys.stderr)

    rows = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for row in ex.map(lambda t: probe_system(*t), todo):
            row["in_src"] = in_src(row["url"])
            rows.append(row)

    found = [r for r in rows if r["found"]]
    covered = [r for r in found if r["in_src"]]
    OUT_JSON.write_text(json.dumps(rows, indent=1))

    by_kind: dict[str, list] = {}
    for r in rows:
        by_kind.setdefault(r["system"], []).append(r)

    lines = [
        "# County record systems — NC + SC",
        "",
        "Generated by `scripts/build_county_registry.py`. One row per (county,",
        "system). **Accessibility is recorded, never used as a filter** — a walled",
        "county still belongs here, because knowing it exists and is walled is",
        "knowledge, while omitting it looks identical to it not existing.",
        "",
        f"- counties: **{len(NC_COUNTIES)} NC + {len(SC_COUNTIES)} SC = "
        f"{len(NC_COUNTIES)+len(SC_COUNTIES)}**",
        f"- (county, system) pairs probed: **{len(rows)}**",
        f"- systems located: **{len(found)}**",
        f"- of those, already referenced in `src/`: **{len(covered)}**",
        "",
        "`not found` means these URL patterns did not locate it. It does NOT mean",
        "the county has no such system — most will, on a host shape this does not",
        "yet know. Those are the ones worth hand-checking.",
        "",
    ]
    for kind, rs in sorted(by_kind.items()):
        f = [r for r in rs if r["found"]]
        lines += [f"## {kind}  ({len(f)} of {len(rs)} located)", "",
                  "`state?` — is this really that state's county? Blank means the",
                  "name is nationally unique. `unverified` means the name is shared",
                  "with another state's county and the page never says which it is;",
                  "confirm before using it.",
                  "",
                  "| county | state | url | gates | state? | in src |",
                  "|---|---|---|---|---|---|"]
        for r in sorted(rs, key=lambda x: (x["state"], x["county"])):
            if not r["found"]:
                continue
            sc = r.get("state_confirmed")
            mark = "" if sc is True else ("**unverified**" if sc is None else "**WRONG STATE**")
            lines.append(f"| {r['county']} | {r['state']} | {r['url']} | "
                         f"{', '.join(r['gates']) or '-'} | {mark} | "
                         f"{'yes' if r['in_src'] else '**NO**'} |")
        missing = [r for r in rs if not r["found"]]
        lines += ["", f"<details><summary>not located by pattern "
                      f"({len(missing)})</summary>", "",
                  ", ".join(f"{r['county']} ({r['state']})" for r in missing),
                  "", "</details>", ""]
    OUT_MD.write_text("\n".join(lines))

    print(f"\n{len(NC_COUNTIES)} NC + {len(SC_COUNTIES)} SC counties")
    print(f"{len(rows)} pairs probed, {len(found)} systems located, "
          f"{len(covered)} already in src/")
    for kind, rs in sorted(by_kind.items()):
        f = [r for r in rs if r["found"]]
        new = [r for r in f if not r["in_src"]]
        print(f"  {kind:10} located {len(f):>3}/{len(rs):<3}  "
              f"not yet used: {len(new)}")
    print(f"\nwrote {OUT_MD.relative_to(REPO)} and {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
