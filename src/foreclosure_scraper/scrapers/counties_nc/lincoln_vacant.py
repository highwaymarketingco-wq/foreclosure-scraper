"""Lincoln County NC vacant parcels — a PROPERTY-KEYED motivated-seller source.

The county ComDev parcel layer carries a VACANT flag per parcel. Vacant (unimproved /
no-structure) parcels held by out-of-area or long-hold owners are prime motivated-seller
prospects (nothing to maintain, carrying cost with no income, often inherited raw land).
Like the elderly/exemption lane this is property-keyed: ONE bulk query returns owner +
situs address + mailing + value + parcel, a complete lead with no name-resolution needed.

Free, anonymous, compliant (public ArcGIS REST, no auth/captcha). ~14,798 vacant parcels,
paginated. GOTCHA: the host serves an incomplete TLS certificate chain (missing
intermediate CA), so we hit it with httpx verify=False -- see the 2026-11-10 note
below; it is NOT an expired certificate, despite this docstring's own prior claim.
Gate with FORECLOSURE_LINCOLN_VACANT=0 to skip.

2026-10-03 (HERMES extraction-completeness audit, batch 5): the docstring above already
claimed "mailing" was part of the bulk query, but the code never actually fetched CITY/
STATE/ZIP or surfaced ADDRESS1 beyond a private raw key -- there was no way to tell an
in-county owner from one mailing out of state. Now wired: raw['owner_mailing'] + a
(guarded) raw['absentee_owner'] flag, raw['gis']['last_sale'] (SALEPRICE paired with the
previously-uncaptured SDATE), deed/plat reference, and co-owner (NAME2). See
tests/test_lincoln_vacant.py for the live-verified fill rates and the absentee-heuristic
false-positive guard (vacant land's situs usually has no house number).

2026-11-10 (Hermes plain-code-bug flag: "TLS cert expired, still failing with
verify=False"): live-verified the REAL error first rather than trusting that
one-liner -- `curl -v` against this file's OLD host (arcgisserver.lincolncounty.org)
showed the cert presented is `CN=*.lincolncountync.gov`, valid Sep 2026 - Apr 2027
(NOT expired); curl rejects it only because the SAN doesn't cover the .org
hostname ("no alternative certificate subject name matches target host name").
verify=False (this file's existing setting) skips that hostname check, and the
call already succeeds -- reconfirmed today with the real production outFields/
where via both `curl -k` and a direct httpx(verify=False) call: HTTP 200, real
rows, and through the full LincolnVacant.fetch() pagination end to end (14,738
rows, zero exceptions). So there was no live-reproducible failure here today
with verify=False already set -- Hermes's "still failing" did not reproduce,
and the docstring's old "EXPIRED" claim (now corrected above) was simply wrong.

The real, pre-existing defect: this was the LAST Lincoln NC module in this
codebase still pointed at the legacy arcgisserver.lincolncounty.org host.
arcgisserver.lincolncountync.gov -- the official .gov domain every OTHER
Lincoln County module here already uses (lincoln_code_violations.py,
enrichment_tax_relief.py, enrichment_owner_mailing.py, enrichment_county_phone.py,
parcel_cache.py, enrichment_assessor_photo.py, assessor_cards/lincoln_nc.py,
nc_lincoln_bulk.py, arcgis_distress_layers.py) -- resolves to the SAME IP
(204.84.167.168) and serves byte-identical ComDevData/MapServer/25 data; .org
only still answers because that IP's IIS has no per-hostname TLS binding, so it
hands every caller the .gov wildcard cert regardless of Host header, which is
exactly why .org fails real cert validation (wrong SAN) while .gov does not.
.org is an unmaintained alias with no cert of its own -- one DNS/IIS cleanup on
the county's side from going dark, a latent risk this file alone still carried.
Switched QUERY_URL to the .gov host to match every sibling module.

That still leaves a TLS quirk on .gov itself, but a DIFFERENT, already-diagnosed
one: lincoln_code_violations.py's own 2026-09-15 TLS NOTE (live-confirmed by hand
then) found arcgisserver.lincolncountync.gov serves an INCOMPLETE certificate
chain -- the leaf is valid/current, the server just omits the intermediate CA,
so httpx verify=True can fail with "unable to get local issuer certificate" even
though the cert itself is fine; enrichment_tax_relief.py's Lincoln entry carries
the same fact as its own `"insecure_tls": True` flag. This file's existing
local-scoped `httpx.AsyncClient(verify=False, ...)` (not a change to the shared
http_client.client() every other scraper uses) is exactly that established
project pattern, so it stays as-is on the new host -- re-verified live above
with the real outFields list over verify=False; on this Mac verify=True even
happened to also succeed (these cert-chain quirks can vary by machine/trust
store), so verify=False remains the correct, proven choice rather than relying
on a check already documented to fail elsewhere in this same codebase.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from ...base_scraper import BaseScraper
from ...gis_fill import plausible_value
from ...models import Listing, ListingType, PropertyKind

#: 2026-11-10: switched from the legacy arcgisserver.lincolncounty.org host (same IP,
#: but its cert is now *.lincolncountync.gov, so .org fails real SAN validation) to the
#: .gov host every other Lincoln NC module already uses. See the docstring's 2026-11-10
#: note for the full live-verified diagnosis.
QUERY_URL = "https://arcgisserver.lincolncountync.gov/arcgis/rest/services/ComDevData/MapServer/25/query"
_WHERE = "VACANT='YES'"
# NAME2/ADDRESS2/CITY/STATE/ZIP/DEEDBK/DEEDPG/DEEDYR/PLATBK/PLATPG/SDATE/SBDIVN added
# 2026-10-03 (HERMES extraction-completeness audit, batch 5). Diffed the live 55-field
# layer schema against the old 9-field outFields list: CITY/STATE/ZIP (the owner's own
# MAILING address, live-sampled as 499/500 filled) were never even REQUESTED, let alone
# surfaced -- a glaring miss given this scraper's entire stated purpose is flagging
# "out-of-area... owners" as motivated-seller prospects, yet nothing in the old code
# could tell an in-county owner from one mailing from Boca Raton FL. ADDRESS1 WAS already
# fetched but only stashed under the private raw["lincoln_vacant"] key nothing downstream
# reads (same miss class as batch 4's Gaston SALEDATE/SALESAMT). DEEDBK/DEEDPG/DEEDYR
# (100% filled) is a real deed reference; SDATE (100% filled) is the last-sale DATE —
# SALEPRICE was already captured but its paired date was not, so enrichment_last_sale's
# raw['gis']['last_sale'] key was unreachable even when a real sale amount existed.
# NAME2 (51% filled) is a co-owner dropped on jointly-owned parcels. PLATBK/PLATPG (31%)
# is a plat reference. SBDIVN (subdivision name, ~100% filled though often blank-string)
# is minor context, kept in raw only.
_OUT = ("PARCELID,PIN,PHYSICALADDR,NAME1,NAME2,ADDRESS1,ADDRESS2,CITY,STATE,ZIP,"
        "IMPROVALUE,TOTALVALUE,MAINAREASQFT,SALEPRICE,SDATE,DEEDBK,DEEDPG,DEEDYR,"
        "PLATBK,PLATPG,SBDIVN,"
        # 2026-10-07 extraction audit: LANDVALUE (98% filled), ACRE/MAPPEDACRE (78%/100%),
        # LANDEFERRED (26%: present-use value deferral, i.e. rollback taxes come due on a
        # sale), QUALIFIEDCODE (83%: is the recorded sale a qualified one), ZONING (100%)
        # and TAXYEAR were on the layer and never requested.
        "LANDVALUE,ACRE,MAPPEDACRE,LANDEFERRED,QUALIFIEDCODE,ZONING,TAXYEAR")
_PAGE = 2000


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _s(v) -> str | None:
    s = str(v or "").strip()
    return s or None


def _is_absentee(mail_state: str | None, mail_street: str | None, situs: str | None) -> bool:
    """Owner mails from out of state, from a PO box, or from a different street
    than the parcel. Mirrors counties_sc.pickens_delinquent_parcels._is_absentee
    (same three tells), with ONE guard added for this specific dataset: VACANT
    land's PHYSICALADDR is usually just a road name with NO house number
    ("CAT SQUARE RD"), while the mailing street always starts with one ("7347
    HENRY RD") -- live-sampled, only 1,251/14,731 situs values here start with a
    digit. Comparing leading tokens unconditionally (the Pickens original) would
    call ~99% of this specific dataset "absentee" on that formatting mismatch
    alone, not a real signal (live-verified: 14,575/14,731 before this guard vs.
    893 out-of-state + 1,157 PO-box after it) -- exactly the false-positive-
    inflation failure mode flagged in project_signal_accuracy_validation, so the
    street-token comparison only runs when situs itself carries a house number."""
    st = (mail_state or "").strip().upper()
    if st and st != "NC":
        return True
    street = (mail_street or "").strip().upper()
    if re.search(r"\bP\.?\s?O\.?\s?BOX\b", street):
        return True
    if street and situs and re.match(r"^\d", situs.strip()):
        a = re.sub(r"\s+", " ", street).split()
        b = re.sub(r"\s+", " ", situs.strip().upper()).split()
        if a[:2] != b[:2]:
            return True
    return False


class LincolnVacant(BaseScraper):
    slug = "counties_nc.lincoln_vacant"
    name = "Lincoln County (NC) Vacant Parcels"
    category = "motivated_seller"
    # Real fetches measure 3.7-13s for the full ~14.7k-row paginated set (live-verified
    # 2026-10-16); 120s should rarely bind. Raised as defense-in-depth after a transient
    # ~123s timeout on 2026-10-15 lost the whole run (now mitigated by the self.partial
    # salvage added the same audit, but a wider margin costs nothing on a fast source).
    timeout_s = 240.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_LINCOLN_VACANT", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        # Host serves an incomplete TLS chain (missing intermediate CA), NOT an expired
        # cert -> verify=False, scoped to this one client only (public read-only GIS
        # endpoint, no auth). Same documented pattern as lincoln_code_violations.py /
        # enrichment_tax_relief.py's "insecure_tls" flag for this same .gov host.
        async with httpx.AsyncClient(verify=False, timeout=60.0) as c:
            offset = 0
            while offset < 200000:  # hard backstop; real set ~14,798
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "PARCELID", "f": "json"}
                try:
                    # Retried up to 3 times (short exponential-jitter backoff) on a
                    # transport error or timeout only -- found 2026-11-07, same gap
                    # already fixed for gaston_vacant.py, the Column legal-notice API
                    # scrapers, spartan_weekly_legals.py and arcgis_webmap.query_features():
                    # this bare httpx.AsyncClient call (verify=False for the host's expired
                    # TLS cert, so it bypasses the shared, already-retrying http_client)
                    # had zero retry cushioning, so a single transient blip on any page --
                    # including offset=0, the FIRST page of every run -- silently zeroed or
                    # truncated this whole dateless source's output, reported as a healthy
                    # result since this scraper is in main.DATELESS_OK_SOURCES (no fallback
                    # date window to self-heal from). A real non-200 status is still left
                    # alone, unretried, below.
                    async for attempt in AsyncRetrying(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential_jitter(initial=1, max=8),
                        retry=retry_if_exception_type(
                            (httpx.TransportError, httpx.TimeoutException, TimeoutError)),
                        reraise=True,
                    ):
                        with attempt:
                            r = await c.get(QUERY_URL, params=params)
                    if r.status_code != 200:
                        break
                    body = r.json()
                    feats = body.get("features", []) or []
                except Exception:  # noqa: BLE001
                    break
                if not feats:
                    break
                more = bool(body.get("exceededTransferLimit"))
                for ft in feats:
                    a = ft.get("attributes", {}) or {}
                    parcel = (str(a.get("PARCELID") or "").strip() or None)
                    pin = (str(a.get("PIN") or "").strip() or None)
                    situs = (str(a.get("PHYSICALADDR") or "").strip() or None)
                    owner = (str(a.get("NAME1") or "").strip() or None)
                    if not parcel and not pin:
                        continue

                    mail_street = _s(a.get("ADDRESS1"))
                    mail_street2 = _s(a.get("ADDRESS2"))
                    mail_city = _s(a.get("CITY"))
                    mail_state = _s(a.get("STATE"))
                    mail_zip = _s(a.get("ZIP"))
                    sale_amt = _f(a.get("SALEPRICE"))
                    sale_dt = _s(a.get("SDATE"))

                    raw: dict = {"lincoln_vacant": {
                        "PARCELID": parcel, "PIN": pin, "PHYSICALADDR": situs,
                        "NAME1": owner, "NAME2": _s(a.get("NAME2")),
                        "ADDRESS1": mail_street, "ADDRESS2": mail_street2,
                        "CITY": mail_city, "STATE": mail_state, "ZIP": mail_zip,
                        "IMPROVALUE": a.get("IMPROVALUE"), "TOTALVALUE": a.get("TOTALVALUE"),
                        "MAINAREASQFT": a.get("MAINAREASQFT"), "SALEPRICE": a.get("SALEPRICE"),
                        "co_owner": _s(a.get("NAME2")),
                        "deed_book": _s(a.get("DEEDBK")), "deed_page": _s(a.get("DEEDPG")),
                        "deed_year": a.get("DEEDYR"),
                        "plat_book": _s(a.get("PLATBK")), "plat_page": _s(a.get("PLATPG")),
                        "subdivision": _s(a.get("SBDIVN")),
                        "land_value": _f(a.get("LANDVALUE")),
                        "acre": _f(a.get("ACRE")),
                        "mapped_acre": _f(a.get("MAPPEDACRE")),
                        "land_deferred": _f(a.get("LANDEFERRED")),
                        "sale_qualified_code": _s(a.get("QUALIFIEDCODE")),
                        "zoning": _s(a.get("ZONING")),
                        "tax_year": a.get("TAXYEAR"),
                        "signal": "vacant_parcel"},
                    }
                    if mail_street or mail_city:
                        raw["owner_mailing"] = {
                            "street": mail_street, "street2": mail_street2,
                            "city": mail_city, "state": mail_state, "zip": mail_zip,
                            "source": "lincoln_county_gis",
                            # The standard keys (2026-10-07 extraction audit): the phone
                            # payload (_SLIM_RAW owner_mailing) keeps only mailing /
                            # mail_state / absentee / out_of_state, so the street/city/zip
                            # above never reached it.
                            "mailing": ", ".join(x for x in (
                                ", ".join(y for y in (mail_street, mail_street2) if y),
                                " ".join(y for y in (mail_city, mail_state, mail_zip) if y),
                            ) if x) or None,
                            "mail_state": (mail_state or "").upper() or None,
                            "out_of_state": bool(mail_state and mail_state.strip().upper() != "NC"),
                        }
                        if _is_absentee(mail_state, mail_street, situs):
                            raw["absentee_owner"] = True
                            # 2026-10-04 extraction-completeness audit (batch 11),
                            # same raw-key-naming-gap shape as dd19fa6a/6e00d55b:
                            # enrichment_lead_signals.py's absentee_owner facet and
                            # distress_score.py's own +8 absentee bonus both read
                            # raw['owner_mailing']['absentee'] (mailing_shape.
                            # mailing_of), never this bare raw['absentee_owner']
                            # key -- so a real absentee hit computed right here was
                            # invisible to both. owner_mailing already exists in
                            # this branch; just add the key the consumer reads.
                            raw["owner_mailing"]["absentee"] = True
                    # SALEPRICE is already fetched but was never paired with its own
                    # SDATE -- enrichment_last_sale.py's raw['gis']['last_sale'] key
                    # needs BOTH to surface a recorded-sale fact (same $0 = "no
                    # arms-length sale" guard _f() already applies via its >0 check).
                    if sale_amt and sale_dt:
                        raw["gis"] = {"last_sale": {
                            "amount": sale_amt, "date": sale_dt,
                            "source": "lincoln_county_gis",
                        }}
                        if _s(a.get("QUALIFIEDCODE")):
                            raw["gis"]["last_sale"]["qualification"] = _s(a.get("QUALIFIEDCODE"))

                    li = Listing(
                        source=self.slug,
                        source_url=(f"{QUERY_URL}?where=PARCELID%3D%27{parcel}%27&outFields=*&f=html"
                                    if parcel else f"{QUERY_URL}?where={_WHERE}&outFields=*&f=html"),
                        listing_type=ListingType.UNKNOWN,
                        property_kind=PropertyKind.LAND,
                        owner_name=owner,
                        street_address=situs,
                        state="NC",
                        county="Lincoln",
                        # PIN first (owner decision 2026-10-07). PARCELID is 5-6 characters, so
                        # validation.py nulled it and ~15.9k of 16.1k board rows published with
                        # no parcel_id; PIN is the 10-digit NC PIN every other NC source keys on.
                        # parcel_alias.py maps the old PARCELID rows onto it in the board merge
                        # and dedupe (raw.lincoln_vacant.PARCELID is the alias), so the switch
                        # does not publish any property twice.
                        parcel_id=pin or parcel,
                        acreage=_f(a.get("ACRE")) or _f(a.get("MAPPEDACRE")),
                        zoning=_s(a.get("ZONING")),
                        living_sqft=_f(a.get("MAINAREASQFT")),
                        # plausible_value() floors out a nominal/placeholder TOTALVALUE (e.g. an
                        # HOA common-area sliver or an unassessed new lot showing $5) so the field
                        # stays None and eligible for a later correct fill instead of permanently
                        # "filled" with an implausible dollar amount (2026-10-17 gap-sweep wave 7,
                        # top80-fill-values-sane).
                        assessed_value=plausible_value(_f(a.get("TOTALVALUE"))),
                        market_value=plausible_value(_f(a.get("TOTALVALUE"))),
                        description="County parcel flagged VACANT (unimproved / no structure) — "
                                    "carrying-cost motivated-seller signal.",
                        first_seen=now,
                        last_seen=now,
                        raw=raw,
                    )
                    out.append(li)
                    # Incremental salvage (audit 2026-10-16): this fetch never populated
                    # self.partial, so base_scraper.safe_run()'s timeout handler -- which
                    # only ever salvages rows already sitting there -- had nothing to recover.
                    # A single ~123s timeout (over the 120s cap, see timeout_s below) threw
                    # away this source's entire ~14.7k rows instead of the pages already read.
                    self.partial.append(li)
                offset += len(feats)
                # Server caps each page below _PAGE; keep paging while it flags more.
                if not more and len(feats) < _PAGE:
                    break
        return out
