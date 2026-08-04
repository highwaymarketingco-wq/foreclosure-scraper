"""Pickens County SC PRE-sale delinquent-tax parcels — the whole multi-year roll.

WHY THIS EXISTS (the gap it closes):
    ``counties_sc.pickens_tax_sale`` reads the county's *Delinquent Tax Sale
    RESULTS* PDF — a POST-sale document. By the time a parcel appears there it
    has already been auctioned; the owner is down to a redemption clock and a
    third-party bidder already holds the tax title. The window where the equity
    is actually actionable — after the county has published the parcel as
    delinquent but BEFORE the hammer falls — was never read by the engine.

    Pickens publishes exactly that window as free, public, anonymous ArcGIS
    FeatureServers on its GIS org ``services1.arcgis.com/59960rq18IxUcAVI``.
    One service per delinquent roll / newspaper ad / posting run, going back to
    2020. Nothing else in the engine touches them.

LAYERS (enumerated live off the org's ``/services?f=json``, 132 services total;
every ``delinquent_*`` / ``del_*`` / ``dqnt_*`` / ``DelParces*`` / ``DelqParcels*``
/ ``Posting*`` service, all single-layer ``/0``, all polygon, all PIN-keyed):

    service                        rows  cycle  owner  mailing  situs  amount
    delinquent_2020                 436   2020    -       -       Y      -
    del_2021                        397   2021    -       -       Y      -
    dqnt_2022                       834   2022    Y       Y       Y      Y
    dqnt_2023                       362   2023    Y       Y       Y      Y
    dqnt_2024                       954   2024    Y       Y       Y      Y
    DelParces_October2025NewsAd     412   2025    Y       -       -      Y
    DelqParcels_Ad_paperlisting2    362   2025    Y       -       -      Y
    Posting3                        311   2025    Y       -       -      Y

    The three 2025 services are the CURRENT cycle: the newspaper ad the county
    is statutorily required to run (SC Code 12-51-40(d)) plus the two physical
    posting runs. A parcel in those is delinquent RIGHT NOW and has not been
    sold — that is the actionable set. The 2020-2024 services are the historical
    rolls and supply owner + mailing + situs, which the 2025 services omit, plus
    the repeat-delinquency counter.

    ``FLC_2022`` lives on the same org but is deliberately NOT read here — it is
    post-sale Forfeited Land Commission inventory, which ``counties_sc.sc_flc``
    already owns. Reading it here would double-count.

EMISSION MODEL (parcel-keyed, per the backbone):
    One Listing per PARCEL, not per roll-year. Every cycle a parcel appears in
    folds into ``raw['pickens_delinquent']['cycles']``, so a parcel delinquent
    in 2020, 2022 and 2025 is ONE lead carrying ``cycle_count=3`` — a chronic
    non-payer — rather than three rows that look like three properties.
    ``parcel_id`` puts it on the ``parcel:SC:pickens:<pin>`` dedupe key, so it
    MERGES onto whatever Pickens lead is already on the board (tax-sale result,
    Public Index case, ROD filing) instead of duplicating it.

    ``raw['pickens_delinquent']['amount_owed']`` is picked up automatically by
    ``enrichment_tax_owed`` (the slug contains "delinquent", and ``amount_owed``
    is one of its ``_GENERIC_KEYS``) and normalized to ``raw['tax_owed']``.

PRIVACY: every field is enumerated explicitly — never ``outFields=*``. The
attributes taken are owner of record, owner mailing address, situs, parcel id,
acreage, and amount due: property/assessment record fields only. These layers
carry no phone, email, SSN or DOB columns.

Free + compliant: anonymous ArcGIS REST, no key, no login, no CAPTCHA/WAF.
Dateless (a delinquency is a standing balance, not a dated sale) -> the slug
must be in ``main.DATELESS_OK_SOURCES`` or every row is filtered out.
Gate with FORECLOSURE_PICKENS_DELINQUENT=0.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Iterable, NamedTuple

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_PICKENS_DELINQUENT"

ORG = "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services"

#: Human-readable source page for the delinquent-tax office.
PAGE_URL = "https://www.co.pickens.sc.us/departments/delinquent_tax/index.php"

_PAGE = 1000


class Layer(NamedTuple):
    """One delinquent service and the attribute names it uses for each role.

    The county renamed columns between rolls (PIN vs MAP_NUMBER vs DelqParcel;
    AMOUNT_DUE vs Max_AMT_DU vs DelqParc_5), so the mapping is per-layer rather
    than a single guessed schema. ``None`` means the layer simply lacks that
    role — it is backfilled from an older layer at the same parcel.
    """
    service: str
    cycle: int
    #: True for the CURRENT (unsold, pre-sale) publication cycle.
    current: bool
    pin: str
    owner: str | None = None
    #: Second owner-name column (joint owner / long-form owner-of-record string).
    owner_alt: str | None = None
    mail_addr: str | None = None
    mail_city: str | None = None
    mail_state: str | None = None
    mail_zip: str | None = None
    situs: str | None = None
    situs_city: str | None = None
    situs_zip: str | None = None
    amount: str | None = None
    tax_year: str | None = None
    acres: str | None = None
    bldgs: str | None = None
    impvac: str | None = None
    acct: str | None = None
    pin_ext: str | None = None

    @property
    def url(self) -> str:
        return f"{ORG}/{self.service}/FeatureServer/0"

    @property
    def out_fields(self) -> str:
        """Explicit field list — never '*' (see module docstring, PRIVACY)."""
        names = ["FID"] + [
            v for k, v in self._asdict().items()
            if k not in ("service", "cycle", "current") and isinstance(v, str) and v
        ]
        seen: list[str] = []
        for n in names:
            if n not in seen:
                seen.append(n)
        return ",".join(seen)


#: Oldest -> newest. Order matters: the newest layer carrying a value wins.
LAYERS: tuple[Layer, ...] = (
    Layer("delinquent_2020", 2020, False, pin="MAP_NUMBER",
          situs="LOCADD", situs_city="LOCCITY", situs_zip="LOCZIP",
          acres="ACREAGE", acct="ACCTNO"),
    Layer("del_2021", 2021, False, pin="PIN",
          situs="LOCADD", situs_city="LOCCITY", situs_zip="LOCZIP",
          acres="ACRES", acct="ACCTNO"),
    Layer("dqnt_2022", 2022, False, pin="PIN", owner="NAME1", owner_alt="OWNER__NOW",
          mail_addr="ADD1", mail_city="CITY", mail_state="STATE", mail_zip="ZIP",
          situs="LOCADD", situs_city="LOCCITY", situs_zip="LOCZIP",
          amount="AMOUNT_DUE", tax_year="TAXYEAR", acres="ACRES",
          bldgs="BLDGS", impvac="IMPVAC", acct="ACCTNO", pin_ext="PINEXT"),
    Layer("dqnt_2023", 2023, False, pin="PIN", owner="NAME1", owner_alt="OWNER__NOW",
          mail_addr="ADD1", mail_city="CITY", mail_state="STATE", mail_zip="ZIP",
          situs="LOCADD", situs_city="LOCCITY", situs_zip="LOCZIP",
          amount="AMOUNT_DUE", tax_year="TAXYEAR", acres="ACRES",
          bldgs="BLDGS", impvac="IMPVAC", acct="ACCTNO"),
    Layer("dqnt_2024", 2024, False, pin="PIN", owner="NAME1",
          mail_addr="ADD1", mail_city="CITY", mail_state="STATE", mail_zip="ZIP",
          situs="LOCADD", situs_city="LOCCITY", situs_zip="LOCZIP",
          amount="Max_AMT_DU", tax_year="TAXYEAR", acres="ACRES",
          bldgs="BLDGS", impvac="IMPVAC", acct="ACCTNO", pin_ext="PINEXT"),
    # --- current cycle: published-but-unsold ---------------------------------
    Layer("DelParces_October2025NewsAd", 2025, True, pin="PIN",
          owner="OWNER__NOW", amount="AMOUNT_DUE", acres="CALCACRE"),
    Layer("DelqParcels_Ad_paperlisting2", 2025, True, pin="DelqParcel",
          owner="DelqParc_4", amount="DelqParc_5", acres="DelqParc_1"),
    Layer("Posting3", 2025, True, pin="PIN", owner="OWNER__NOW",
          amount="AMOUNT_DUE", acres="CALCACRE", pin_ext="PIN_SUF"),
)

#: Government / institutional owners are not sellers.
_GOV = re.compile(
    r"\b(CITY OF|TOWN OF|COUNTY OF|STATE OF|PICKENS COUNTY|HOUSING AUTHORITY|"
    r"SCHOOL DISTRICT|UNITED STATES|SECRETARY OF|DEPARTMENT OF|FORFEITED LAND|"
    r"CLEMSON UNIVERSITY|MUNICIPAL|SC DEPARTMENT)\b", re.I)

#: Pickens PIN: NNNN-NN-NN-NNNN (dashes optional in a few older rolls).
_PIN_RE = re.compile(r"^\d{4}-?\d{2}-?\d{2}-?\d{4}$")


def _clean(v: Any) -> str | None:
    """Blank-ish -> None. County data uses ' ' (single space) as its NULL."""
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _norm_pin(v: Any) -> str | None:
    """Canonical dashed PIN. Rejects anything that is not a Pickens parcel id."""
    s = _clean(v)
    if not s:
        return None
    s = s.replace(" ", "").upper()
    if not _PIN_RE.match(s):
        return None
    d = s.replace("-", "")
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}-{d[8:12]}"


def _money(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = re.sub(r"[^\d.]", "", str(v))
    if not s or s == ".":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f > 0 else None


def _zip5(v: Any) -> str | None:
    """LOCZIP/ZIP arrive as ints, sometimes ZIP+4 padded (296730000)."""
    if v in (None, "", " ", 0, "0"):
        return None
    s = re.sub(r"\D", "", str(v).split(".")[0])
    if len(s) >= 5 and s[:5] != "00000":
        return s[:5]
    return None


def _centroid(geom: dict[str, Any] | None) -> tuple[float, float] | None:
    """Mean of a polygon's ring vertices -> (lat, lng). Geometry is WGS84."""
    rings = (geom or {}).get("rings") or []
    pts = [p for ring in rings for p in ring if len(p) >= 2]
    if not pts:
        return None
    return (sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts))


def _is_absentee(mail_city: str | None, mail_state: str | None,
                 mail_addr: str | None, situs: str | None) -> bool:
    """Owner mails from out of state, from a PO box, or from a different
    street than the property. All three are classic non-occupant tells."""
    st = (mail_state or "").strip().upper()
    if st and st != "SC":
        return True
    street = (mail_addr or "").strip().upper()
    if re.search(r"\bP\.?\s?O\.?\s?BOX\b", street):
        return True
    if street and situs:
        # Compare leading house number + first street token.
        a = re.sub(r"\s+", " ", street)
        b = re.sub(r"\s+", " ", situs.strip().upper())
        if a.split()[:2] != b.split()[:2]:
            return True
    return False


def _property_kind(impvac: str | None, bldgs: Any) -> PropertyKind:
    """The assessor's own improved/vacant flag is the only trustworthy tell —
    BLDGS=0 shows up on parcels that plainly have a house, so it is not used
    to call LAND on its own."""
    if (impvac or "").strip().upper().startswith("VAC"):
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


class Row(NamedTuple):
    """One layer's contribution for one parcel, already normalized."""
    cycle: int
    current: bool
    service: str
    owner: str | None
    mail_addr: str | None
    mail_city: str | None
    mail_state: str | None
    mail_zip: str | None
    situs: str | None
    situs_city: str | None
    situs_zip: str | None
    amount: float | None
    tax_year: int | None
    acres: float | None
    bldgs: int | None
    impvac: str | None
    acct: str | None
    pin_ext: str | None
    lat: float | None
    lng: float | None


def parse_feature(feat: dict, layer: Layer) -> tuple[str, Row] | None:
    """(normalized PIN, Row) for one feature, or None if it has no usable PIN."""
    a = feat.get("attributes") or {}

    def g(role: str) -> Any:
        col = getattr(layer, role)
        return a.get(col) if col else None

    pin = _norm_pin(g("pin"))
    if not pin:
        return None

    lat = lng = None
    c = _centroid(feat.get("geometry"))
    if c:
        lat, lng = c

    owner = _clean(g("owner"))
    alt = _clean(g("owner_alt"))
    # OWNER__NOW is the long-form owner-of-record string ("SMITH, JOHN, HEIRS
    # OF,") and is strictly more informative than the terse NAME1 index form.
    if alt and (not owner or len(alt) > len(owner)):
        owner = alt

    try:
        tax_year = int(g("tax_year")) if g("tax_year") not in (None, "", " ") else None
    except (TypeError, ValueError):
        tax_year = None
    try:
        bldgs = int(g("bldgs")) if g("bldgs") not in (None, "", " ") else None
    except (TypeError, ValueError):
        bldgs = None
    try:
        acres = float(g("acres")) if g("acres") not in (None, "", " ") else None
    except (TypeError, ValueError):
        acres = None

    return pin, Row(
        cycle=layer.cycle, current=layer.current, service=layer.service,
        owner=owner,
        mail_addr=_clean(g("mail_addr")), mail_city=_clean(g("mail_city")),
        mail_state=_clean(g("mail_state")), mail_zip=_zip5(g("mail_zip")),
        situs=_clean(g("situs")), situs_city=_clean(g("situs_city")),
        situs_zip=_zip5(g("situs_zip")),
        amount=_money(g("amount")), tax_year=tax_year,
        acres=acres if acres and acres > 0 else None,
        bldgs=bldgs, impvac=_clean(g("impvac")), acct=_clean(g("acct")),
        pin_ext=_clean(g("pin_ext")),
        lat=lat, lng=lng,
    )


def build_listing(pin: str, rows: list[Row], now: datetime | None = None) -> Listing | None:
    """Fold every roll-year a parcel appears in into one parcel-keyed Listing."""
    now = now or datetime.utcnow()
    if not rows:
        return None
    # Newest cycle first — it drives the headline fields.
    rows = sorted(rows, key=lambda r: r.cycle, reverse=True)

    def newest(field: str) -> Any:
        """Newest non-empty value across the cycles at this parcel. The 2025
        posting layers carry owner + amount but no situs/mailing; the 2020-2024
        rolls carry situs + mailing. Backfilling across them is what makes these
        leads fully resolved instead of a bare PIN."""
        for r in rows:
            v = getattr(r, field)
            if v not in (None, ""):
                return v
        return None

    owner = newest("owner")
    if owner and _GOV.search(owner):
        return None

    situs = newest("situs")
    situs_city = newest("situs_city")
    situs_zip = newest("situs_zip")
    mail_addr = newest("mail_addr")
    mail_city = newest("mail_city")
    mail_state = newest("mail_state")
    mail_zip = newest("mail_zip")

    current_rows = [r for r in rows if r.current]
    # The balance that matters is the one on the most recent publication.
    amount = next((r.amount for r in rows if r.amount), None)
    cycles = sorted({r.cycle for r in rows})

    # Taken as a PAIR from one row — never a latitude from one cycle's polygon
    # and a longitude from another's.
    lat, lng = next(((r.lat, r.lng) for r in rows if r.lat is not None), (None, None))
    impvac = newest("impvac")

    raw: dict[str, Any] = {
        "pickens_delinquent": {
            "county": "Pickens",
            "parcel_id": pin,
            "pin_ext": newest("pin_ext"),
            "account_no": newest("acct"),
            # enrichment_tax_owed normalizes this into raw['tax_owed'].
            "amount_owed": amount,
            "cycles": cycles,
            "cycle_count": len(cycles),
            "latest_cycle": cycles[-1],
            "first_cycle": cycles[0],
            # True = published delinquent in the CURRENT cycle and not yet sold.
            # This is the pre-sale window the results PDF never showed us.
            "pre_sale": bool(current_rows),
            "publications": [
                {"service": r.service, "cycle": r.cycle,
                 "amount": r.amount, "current": r.current}
                for r in rows
            ],
            "repeat_delinquent": len(cycles) >= 2,
            "chronic": len(cycles) >= 3,
            "tax_year": newest("tax_year"),
            "acres": newest("acres"),
            "buildings": newest("bldgs"),
            "improved_vacant": impvac,
            "source": "pickens_county_gis_delinquent_layers",
        },
    }
    if mail_addr or mail_city:
        raw["owner_mailing"] = {
            "street": mail_addr, "city": mail_city,
            "state": mail_state, "zip": mail_zip,
            "source": "pickens_delinquent_roll",
        }
        if _is_absentee(mail_city, mail_state, mail_addr, situs):
            raw["absentee_owner"] = True
    if len(cycles) >= 3:
        # Three or more separate delinquency publications is not an oversight.
        raw["distressed"] = True

    desc = (
        f"Delinquent property tax, Pickens County SC — parcel {pin}"
        + (f"; ${amount:,.2f} due" if amount else "")
        + (f"; published in {len(cycles)} roll years ({cycles[0]}-{cycles[-1]})"
           if len(cycles) > 1 else f"; {cycles[0]} roll")
        + ("; CURRENT cycle, not yet sold" if current_rows else "")
    )

    return Listing(
        source=PickensDelinquentParcels.slug,
        source_url=PAGE_URL,
        listing_type=ListingType.TAX_LIEN,
        property_kind=_property_kind(impvac, newest("bldgs")),
        state="SC",
        county="Pickens",
        city=situs_city,
        street_address=situs,
        zip_code=situs_zip,
        parcel_id=pin,
        defendant=owner,
        owner_name=owner,
        sale_date=None,
        latitude=lat,
        longitude=lng,
        # NOTE: the delinquent balance is NOT a property value — it stays in
        # raw['pickens_delinquent']['amount_owed'] (normalized to raw['tax_owed']
        # by enrichment_tax_owed). Putting it in tax_value/assessed_value would
        # make calc.py price a house off a $300 tax bill.
        foreclosure_process="tax",
        description=desc,
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


async def fetch_layer(http, layer: Layer) -> list[tuple[str, Row]]:
    """One layer -> normalized (pin, Row) pairs. A dead layer costs that layer,
    never the run: the county retires/renames these services between cycles."""
    try:
        feats = await agw.query_features(
            http, layer.url, where="1=1", out_fields=layer.out_fields,
            return_geometry=True, out_sr=4326, order_by="FID ASC",
            page=_PAGE, max_records=20000)
    except Exception as exc:  # noqa: BLE001
        log.warning("pickens_delinquent.layer_fail",
                    service=layer.service, error=str(exc)[:200])
        return []
    out = [p for p in (parse_feature(f, layer) for f in feats) if p]
    log.info("pickens_delinquent.layer", service=layer.service, cycle=layer.cycle,
             features=len(feats), parsed=len(out))
    return out


class PickensDelinquentParcels(BaseScraper):
    slug = "counties_sc.pickens_delinquent_parcels"
    name = "Pickens County SC Pre-Sale Delinquent Tax Parcels (multi-year GIS rolls)"
    category = "motivated_seller"
    expected_min_count = 1500
    timeout_s = 300.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("pickens_delinquent.disabled")
            return []

        by_pin: dict[str, list[Row]] = {}
        live_layers = 0
        async with client(timeout=60.0) as http:
            for layer in LAYERS:
                pairs = await fetch_layer(http, layer)
                if pairs:
                    live_layers += 1
                for pin, row in pairs:
                    by_pin.setdefault(pin, []).append(row)

        if not by_pin:
            return []

        now = datetime.utcnow()
        out: list[Listing] = []
        for pin, rows in by_pin.items():
            li = build_listing(pin, rows, now=now)
            if li:
                out.append(li)

        pre = sum(1 for li in out if li.raw["pickens_delinquent"]["pre_sale"])
        log.info("pickens_delinquent.parsed", layers=live_layers, parcels=len(by_pin),
                 listings=len(out), pre_sale=pre,
                 repeat=sum(1 for li in out
                            if li.raw["pickens_delinquent"]["repeat_delinquent"]),
                 with_owner=sum(1 for li in out if li.owner_name),
                 with_situs=sum(1 for li in out if li.street_address),
                 with_amount=sum(1 for li in out
                                 if li.raw["pickens_delinquent"]["amount_owed"]))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = PickensDelinquentParcels()
        rows = await s.safe_run()
        pd_ = [li.raw["pickens_delinquent"] for li in rows]
        print(f"outcome={s.last_outcome} parcels={len(rows)} "
              f"pre_sale={sum(1 for d in pd_ if d['pre_sale'])} "
              f"repeat={sum(1 for d in pd_ if d['repeat_delinquent'])} "
              f"chronic={sum(1 for d in pd_ if d['chronic'])} "
              f"owner={sum(1 for li in rows if li.owner_name)} "
              f"situs={sum(1 for li in rows if li.street_address)} "
              f"mailing={sum(1 for li in rows if li.raw.get('owner_mailing'))} "
              f"amount={sum(1 for d in pd_ if d['amount_owed'])}")
        for li in sorted(rows, key=lambda x: -(x.raw["pickens_delinquent"]["amount_owed"] or 0))[:15]:
            d = li.raw["pickens_delinquent"]
            print(f"  {li.parcel_id}  ${d['amount_owed'] or 0:>10,.2f}  "
                  f"cyc={d['cycle_count']}{'*' if d['pre_sale'] else ' '} "
                  f"{(li.owner_name or '-')[:34]:34} {(li.street_address or '-')[:30]}")

    asyncio.run(_main())
