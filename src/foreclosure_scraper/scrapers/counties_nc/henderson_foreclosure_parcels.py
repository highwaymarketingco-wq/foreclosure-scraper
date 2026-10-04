"""Henderson County NC tax-foreclosure parcels — the list that isn't a page.

Henderson publishes its "Delinquent Real Property Tax Collection Map" as an
ArcGIS Web Experience. There is no HTML table, no PDF, no CSV: the foreclosure
roster exists only as a ``definitionExpression`` (a REID list) pinned to the
county's shared parcel FeatureServer inside the app's embedded web map. The
filter IS the list.

    app item e25ea4d18d30427cacb1064168c0dea3
      -> web map item 7c89c21f8cf6401bbb71560ab9c09ab8
        -> operational layer "Foreclosure Parcels Henderson County NC"
           definitionExpression: REID = '301249' OR REID = '1001870' OR ...
      -> gisweb.hendersoncountync.gov/.../Parcels/FeatureServer/0/query

``arcgis_webmap`` walks that chain on EVERY run and passes the live expression
straight through as the query WHERE, so the roster stays current as parcels enter
and leave foreclosure — no hardcoded REID list to go stale, and no dependence on
the expression's exact shape.

The parcel layer answers with everything a lead needs in one call: owner, situs,
full owner MAILING address, assessed value, acreage, land class, and a centroid.
So these land already property-resolved and already mailable — no downstream
name->parcel or address-resolver round trip.

Two signals ride along:

* **Estate / heir owner of record.** Henderson retitles decedent parcels in the
  owner column ("TAYLOR, JULIA HEIRS", "MAY, KENNETH F EST", "KNOX, CAROLINE
  ADMINISTRATOR"). Those get ``raw['relationship_signal'] = {'kind':'probate'}``
  so distress_score scores the tangled-title problem on top of the tax debt.
* **Absentee / out-of-state owner**, from the mailing address, in the standard
  ``raw['owner_mailing']`` shape the rest of the pipeline already reads.

Free, public, anonymous ArcGIS REST. The county server 403s a bare urllib call
but returns 200 to the shared http_client's real-browser User-Agent — a header,
not a CAPTCHA/WAF defeat. Dateless standing inventory (a tax foreclosure has no
sale date until it is calendared), so the slug is routed via DATELESS_OK_SOURCES.

Generalizing to another county is a ``_SOURCES`` entry: the app item id, a title
pattern for the layer, the allowed layer host, and that county's parcel field
names. The walking, filter extraction, safety checks, and pagination are shared.

FIXED 2026-10-03 (extraction-completeness audit, batch 4): diffed the live layer
schema (``Parcels/FeatureServer/0?f=json``, 91 fields) against this module's
``fields`` map and live-sampled the actual 15-parcel foreclosure roster. Six more
real fields ride along in the SAME query (no extra request):
  - ``PROPERTY_DESCR`` -- 100% filled legal description ("#4 OAK PARK"), never
    wired to ``Listing.legal_description``.
  - ``DEED_BOOK``/``DEED_PAGE``/``DEED_DATE`` -- 100% filled recorded-deed
    reference.
  - ``PLAT_BOOK``/``PLAT_PAGE`` -- 53% filled.
  - ``LAND_SALE_DATE``/``LAND_SALE_PRICE`` (60%/53% filled; ``PKG_SALE_DATE``/
    ``PKG_SALE_PRICE`` as a rarer 7%-filled fallback for multi-parcel package
    sales) -- a real last-sale, never captured at all; wired into the canonical
    ``raw["gis"]["last_sale"]`` shape (same convention as batch 2's Pickens fix /
    batch 3's Buncombe-elderly fix), guarding a $0 price the same way Buncombe's
    fix did (0 means no arms-length sale, not a free property).
  - ``DEED_URL``/``PLAT_URL`` -- 100%/100% filled, but these are
    courthousecomputersystems.com (CCHS) "image_link" VIEWER pages (JS-driven,
    Cloudflare-fronted, and the whole host answers ``robots.txt: Disallow: /``)
    -- live-fetching one returns an HTML viewer shell, not the deed image itself.
    This repo already has a purpose-built, wall-aware CCHS fetch path
    (``rod/cchs.py`` + ``rod/doc_images.py``, which already lists
    ``("NC","Henderson"): "cchs"``) that handles exactly this vendor's
    Cloudflare-flip and robots-walled-directory quirks correctly. Routing these
    URLs through the generic ``document_links.stamp_documents()`` -> OCR path
    would feed OCR a JS shell and bypass that compliance gate, so they are kept
    as raw REFERENCE metadata only (book/page is the real cross-reference key
    the dedicated CCHS path already uses) -- not stamped as a fetchable
    document. PLAT_URL's "not available" placeholder is filtered out.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...enrichment_owner_mailing import _is_absentee
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...mailing_shape import mailing_dict

log = structlog.get_logger()

#: Source attribution for every row. MUST equal HendersonForeclosureParcels.slug —
#: DATELESS_OK_SOURCES, source-health, and dedupe attribution all key off it, and a
#: drift here would silently drop every (dateless) row in _active_only.
SLUG = "counties_nc.henderson_foreclosure_parcels"

#: Situs placeholders the county writes for un-addressed parcels.
_NO_ADDRESS = re.compile(r"^\s*0?\s*(NO ADDRESS ASSIGNED|NO ADDRESS|NONE|N/?A)\s*$", re.I)

#: Owner strings that mark a decedent / heir title.
_ESTATE_TOKENS = (
    (re.compile(r"\bHEIRS?\b", re.I), "heirs"),
    (re.compile(r"\bADMINISTRAT(?:OR|RIX)\b", re.I), "administrator"),
    (re.compile(r"\bEXECUT(?:OR|RIX)\b", re.I), "executor"),
    (re.compile(r"\bDEC(?:EASED|'?D)\b", re.I), "deceased"),
    # Singular ESTATE / EST only. Plural "ESTATES" is a subdivision name
    # ("CHIMNEY ROCK ESTATES"), and LIFE/REAL ESTATE are living-owner phrases.
    (re.compile(r"(?<!LIFE )(?<!REAL )\bEST(?:ATE)?\b(?!S)", re.I), "estate"),
)

#: An entity that merely CONTAINS an estate word is never a decedent.
_ENTITY = re.compile(
    r"\b(LLC|L L C|INC|CORP|COMPANY|CO|LP|LLP|LLLP|TRUST|TRUSTEE|HOLDINGS?|"
    r"PROPERTIES|PARTNERS?|ASSOC|ASSN|HOA|HOMEOWNERS?|CHURCH|MINISTR\w*|"
    r"DEVELOP\w*|VENTURES?|GROUP|FARMS?|ENTERPRISES?|BANK|CREDIT UNION)\b", re.I)

#: Land classes that mean "no structure".
_LAND_CLASS = re.compile(r"VACANT|LAND|LOT|ACRE", re.I)
_COMMERCIAL_CLASS = re.compile(r"COMM|INDUST|RETAIL|OFFICE|WAREHOUSE", re.I)
_MULTI_CLASS = re.compile(r"MULTI|APART|DUPLEX|TRIPLEX|QUAD", re.I)
_MOBILE_CLASS = re.compile(r"MOBILE|MANUF|MH\b", re.I)

#: DEED_URL/PLAT_URL's own county-page placeholder when no real document exists.
_NO_DOC_URL = re.compile(r"deed-or-plat-not-available", re.I)

_SOURCES: list[dict[str, Any]] = [
    {
        "key": "henderson_foreclosure",
        "state": "NC",
        "county": "Henderson",
        # Experience Builder app: "Delinquent Real Property Tax Collection Map".
        "app_item": "e25ea4d18d30427cacb1064168c0dea3",
        "portals": ("https://www.arcgis.com", "https://hendersoncounty.maps.arcgis.com"),
        "layer_title": r"foreclos",
        # Pin the host the walked layer must live on: a re-pointed web map must
        # never silently redirect the scrape at some other server.
        "allowed_hosts": ("gisweb.hendersoncountync.gov",),
        "app_url": ("https://experience.arcgis.com/experience/"
                    "e25ea4d18d30427cacb1064168c0dea3"),
        "id_field": "REID",   # for logging/provenance only; not used to build the WHERE
        "fields": {
            "parcel": "PIN",
            "alt_id": "REID",
            "owner": "PROPERTY_OWNER",
            "situs": "LOCATION_ADDR",
            "city": "PHYADDR_CITY",
            "zip": "PHYADDR_ZIP",
            "value": "TOTAL_PROP_VALUE",
            "land_value": "TOTAL_LAND_VALUE_ASSESSED",
            "bldg_value": "TOTAL_BLDG_VALUE_ASSESSED",
            "acreage": "ACREAGE",
            "living_sqft": "HEATED_AREA",
            "land_class": "LAND_CLASS",
            "lat": "Centroid_Latitude",
            "lng": "Centroid_Longitude",
            "mail": ("OWNER_MAIL_1", "OWNER_MAIL_2", "OWNER_MAIL_3",
                     "OWNER_MAIL_CITY", "OWNER_MAIL_STATE", "OWNER_MAIL_ZIP"),
            "mail_state": "OWNER_MAIL_STATE",
            "legal": "PROPERTY_DESCR",
            "deed_book": "DEED_BOOK",
            "deed_page": "DEED_PAGE",
            "deed_date": "DEED_DATE",
            "deed_url": "DEED_URL",
            "plat_book": "PLAT_BOOK",
            "plat_page": "PLAT_PAGE",
            "plat_url": "PLAT_URL",
            "land_sale_date": "LAND_SALE_DATE",
            "land_sale_price": "LAND_SALE_PRICE",
            "pkg_sale_date": "PKG_SALE_DATE",
            "pkg_sale_price": "PKG_SALE_PRICE",
        },
    },
]


def _clean(v: Any) -> str | None:
    if v in (None, "", " "):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _num(v: Any) -> float | None:
    if v in (None, "", " "):
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None
    return f if f != 0 else None


def _situs(a: dict, fields: dict) -> str | None:
    s = _clean(a.get(fields["situs"]))
    if not s or _NO_ADDRESS.match(s):
        return None
    return s


def estate_signal(owner: str | None) -> str | None:
    """Return the estate/heir token in an owner-of-record string, else None.

    "TAYLOR, JULIA HEIRS" -> 'heirs'; "MAY, KENNETH F EST" -> 'estate';
    "CHIMNEY ROCK ESTATES, HOA" -> None (plural + entity).
    """
    if not owner:
        return None
    # An owner string can hold several parties ("KNOX, CAROLINE ADMINISTRATOR;
    # HARPER, EDNA V ESTATE"); a decedent in ANY of them counts, but a party
    # that is an entity can't itself be one.
    for party in re.split(r"[;&]|\bAND\b", owner, flags=re.I):
        if not party.strip() or _ENTITY.search(party):
            continue
        for pat, label in _ESTATE_TOKENS:
            if pat.search(party):
                return label
    return None


def _property_kind(a: dict, fields: dict) -> PropertyKind:
    lc = (a.get(fields["land_class"]) or "").upper()
    if _MOBILE_CLASS.search(lc):
        return PropertyKind.MOBILE
    if _MULTI_CLASS.search(lc):
        return PropertyKind.MULTI_FAMILY
    if _COMMERCIAL_CLASS.search(lc):
        return PropertyKind.COMMERCIAL
    if _LAND_CLASS.search(lc):
        return PropertyKind.LAND
    if _num(a.get(fields["living_sqft"])):
        return PropertyKind.SINGLE_FAMILY
    return PropertyKind.UNKNOWN


def _mailing(a: dict, fields: dict) -> str | None:
    parts = [_clean(a.get(f)) for f in fields["mail"]]
    return _clean(" ".join(p for p in parts if p))


def _esri_date(v: Any) -> datetime | None:
    """Esri date fields arrive as epoch-milliseconds."""
    try:
        ms = float(v)
        if ms <= 0:
            return None
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _doc_url(v: Any) -> str | None:
    """A DEED_URL/PLAT_URL value, dropping the county's own "not available"
    placeholder page so it isn't mistaken for a real document reference."""
    s = _clean(v)
    if not s or _NO_DOC_URL.search(s):
        return None
    return s


def _out_fields(fields: dict) -> str:
    """Explicit field list — never '*'. We take only the columns we name."""
    names: list[str] = []
    for v in fields.values():
        for f in (v if isinstance(v, tuple) else (v,)):
            if f and f not in names:
                names.append(f)
    return ",".join(names)


def build_listing(src: dict, layer: agw.MapLayer, attrs: dict,
                  now: datetime | None = None) -> Listing | None:
    """Map one parcel row to a Listing. Returns None when it can't be keyed."""
    fields = src["fields"]
    now = now or datetime.utcnow()
    parcel = _clean(attrs.get(fields["parcel"]))
    owner = _clean(attrs.get(fields["owner"]))
    situs = _situs(attrs, fields)
    if not parcel and not situs:
        return None

    mailing = _mailing(attrs, fields)
    mail_state = (_clean(attrs.get(fields["mail_state"])) or "").upper() or None
    value = _num(attrs.get(fields["value"]))
    alt_id = _clean(attrs.get(fields["alt_id"]))
    estate = estate_signal(owner)
    legal = _clean(attrs.get(fields.get("legal"))) if fields.get("legal") else None

    raw: dict[str, Any] = {
        "tax_foreclosure": {
            "county_program": "Delinquent Real Property Tax Collection",
            "roster": layer.title,
            "layer_url": layer.url,
            "filter_field": src.get("id_field"),
            "filter_id": alt_id,
            "land_class": _clean(attrs.get(fields["land_class"])),
            "land_value": _num(attrs.get(fields["land_value"])),
            "building_value": _num(attrs.get(fields["bldg_value"])),
            "deed_book": _clean(attrs.get(fields.get("deed_book"))) if fields.get("deed_book") else None,
            "deed_page": _clean(attrs.get(fields.get("deed_page"))) if fields.get("deed_page") else None,
            "deed_date": (_esri_date(attrs.get(fields["deed_date"])).isoformat()
                          if fields.get("deed_date") and _esri_date(attrs.get(fields["deed_date"]))
                          else None),
            "plat_book": _clean(attrs.get(fields.get("plat_book"))) if fields.get("plat_book") else None,
            "plat_page": _clean(attrs.get(fields.get("plat_page"))) if fields.get("plat_page") else None,
            # NOTE: DEED_URL/PLAT_URL are courthousecomputersystems.com (CCHS)
            # JS image-viewer pages on a robots-disallowed, Cloudflare-fronted
            # host -- kept as reference metadata only (book/page is the real
            # cross-reference key), NOT routed through stamp_documents()/OCR.
            # The repo's dedicated rod/cchs.py + rod/doc_images.py already
            # handle this vendor's compliance quirks for Henderson.
            "deed_url": _doc_url(attrs.get(fields.get("deed_url"))) if fields.get("deed_url") else None,
            "plat_url": _doc_url(attrs.get(fields.get("plat_url"))) if fields.get("plat_url") else None,
        },
        # Standard shape the rest of the pipeline reads (promote_owner,
        # distress_score absentee tiering, skip-trace, mail merge).
        "owner_mailing": {
            "owner": owner,
            "mailing": mailing,
            "situs": situs,
            "parcel_id": parcel,
            "mail_state": mail_state,
            "absentee": _is_absentee(situs, mailing),
            "out_of_state": bool(mail_state and mail_state != src["state"]),
            "source": f"{src['county'].lower()}_county_gis",
        },
    }

    # A recorded last-sale: LAND_SALE_* first (more common, 60% filled on the
    # live roster), PKG_SALE_* (multi-parcel package sale) as a fallback. A $0
    # price means no arms-length sale (inheritance/correction deed), same
    # guard as the batch-3 Buncombe-elderly fix -- never surfaced as a sale.
    for date_key, price_key in (("land_sale_date", "land_sale_price"),
                                 ("pkg_sale_date", "pkg_sale_price")):
        if not (fields.get(date_key) and fields.get(price_key)):
            continue
        sale_dt = _esri_date(attrs.get(fields[date_key]))
        sale_amt = _num(attrs.get(fields[price_key]))
        if sale_dt and sale_amt:
            raw["gis"] = {"last_sale": {
                "date": sale_dt.isoformat(), "amount": sale_amt,
                "source": "henderson_county_gis",
            }}
            break

    if estate:
        # Tangled title on top of the tax debt — scored as a LIFE_EVENT.
        raw["relationship_signal"] = {
            "kind": "probate",
            "keyword": f"{estate}_owner_of_record",
            "source": SLUG,
        }
        raw["heir_estate"] = {"owner_of_record": owner, "match": estate}

    desc = (f"Tax foreclosure parcel ({src['county']} County, {src['state']})"
            + (f" — owner of record {owner}" if owner else "")
            + (f" — {estate} title" if estate else ""))

    return Listing(
        source=SLUG,
        source_url=src["app_url"],
        listing_type=ListingType.TAX_SALE,
        property_kind=_property_kind(attrs, fields),
        foreclosure_process="tax",
        state=src["state"],
        county=src["county"],
        city=_clean(attrs.get(fields["city"])),
        zip_code=_clean(attrs.get(fields["zip"])),
        street_address=situs,
        parcel_id=parcel,
        defendant=owner,
        owner_name=owner,
        sale_date=None,
        latitude=_num(attrs.get(fields["lat"])),
        longitude=_num(attrs.get(fields["lng"])),
        acreage=_num(attrs.get(fields["acreage"])),
        living_sqft=_num(attrs.get(fields["living_sqft"])),
        tax_value=value,
        assessed_value=value,
        land_use=_clean(attrs.get(fields["land_class"])),
        legal_description=legal,
        description=desc,
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


async def fetch_source(http, src: dict) -> list[Listing]:
    """Walk one county's app -> web map -> filtered layer, then query it."""
    layers = await agw.walk_layers(http, src["app_item"], portals=src["portals"])
    layer = agw.find_layer(layers, src["layer_title"])
    if not layer or not layer.url:
        log.warning("henderson_fc.no_layer", key=src["key"],
                    layers=[lyr.title for lyr in layers][:12])
        return []
    expr = layer.definition_expression
    if not agw.is_safe_expression(expr):
        log.warning("henderson_fc.unsafe_expr", key=src["key"], expr=str(expr)[:120])
        return []
    if not agw.host_matches(layer.url, src["allowed_hosts"]):
        # The web map was re-pointed at a host we didn't expect — refuse it
        # rather than fetch from wherever the remote document now says.
        log.warning("henderson_fc.host_mismatch", key=src["key"], url=layer.url)
        return []

    ids = agw.literal_values(expr, src.get("id_field"))
    log.info("henderson_fc.filter", key=src["key"], layer=layer.title,
             ids=len(ids), expr_chars=len(expr))

    rows = await agw.query_attributes(
        http, layer.url, where=expr, out_fields=_out_fields(src["fields"]),
        page=1000, max_records=5000)

    now = datetime.utcnow()
    out: list[Listing] = []
    for attrs in rows:
        li = build_listing(src, layer, attrs, now=now)
        if li:
            out.append(li)
    log.info("henderson_fc.county", key=src["key"], rows=len(rows), listings=len(out),
             estates=sum(1 for li in out if "heir_estate" in (li.raw or {})))
    return out


class HendersonForeclosureParcels(BaseScraper):
    slug = SLUG
    name = "Henderson County NC Tax-Foreclosure Parcels (ArcGIS web-map filter)"
    category = "county_tax"
    expected_min_count = 3
    timeout_s = 180.0
    requires_apify = False
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=45.0) as http:
            for src in _SOURCES:
                try:
                    out.extend(await fetch_source(http, src))
                except Exception as exc:  # noqa: BLE001
                    # One county failing must not sink the rest, but a lone
                    # configured source re-raises so the run reports ERROR
                    # instead of a believable ZERO_RESULT.
                    log.warning("henderson_fc.source_fail", key=src["key"],
                                error=str(exc)[:200])
                    if len(_SOURCES) == 1:
                        raise
        log.info("henderson_fc.parsed", listings=len(out))
        return out


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        s = HendersonForeclosureParcels()
        rows = await s.safe_run()
        est = sum(1 for li in rows if "heir_estate" in (li.raw or {}))
        abs_ = sum(1 for li in rows if mailing_dict(li).get("absentee"))
        oos = sum(1 for li in rows if mailing_dict(li).get("out_of_state"))
        print(f"outcome={s.last_outcome} count={len(rows)} estate={est} absentee={abs_} out_of_state={oos}")
        for li in rows:
            print(f"  {(li.defendant or '')[:36]:36} pin={li.parcel_id:12} "
                  f"situs={(li.street_address or '-')[:22]:22} "
                  f"val={li.tax_value} kind={li.property_kind.value}")

    asyncio.run(_main())
