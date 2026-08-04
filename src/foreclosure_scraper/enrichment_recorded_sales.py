"""FREE COMP SPINE — recorded sales (price + parties) from county sales layers.

enrichment_recorded_comps already turns county GIS parcel layers into a Tier-0
median $/sqft, but it only works where the layer carries HEATED SQFT. The three
biggest comp-blind counties on the board publish a *sales roll* instead: price,
deed book/page, sale date, and (in Buncombe) grantor/grantee — but no sqft, and
in most cases no sqft anywhere in the county's public GIS. Those leads therefore
fall all the way through to zestimate / tax x 1.25 / bid x 2.4.

This module mines those sales rolls and feeds the EXISTING valuation paths:

  (a) LAND subjects  -> raw['comps'] rows carrying sold_price + lot_sqft, which
      valuation.calc._land_arv already consumes as a $/acre basket. No calc
      change needed; we only fill when no comps exist (never clobber).

  (b) IMPROVED subjects -> raw['recorded_ratio_comps'], the median
      SALE-PRICE / COUNTY-ASSESSED ratio of nearby recorded arms-length sales.
      Multiplied by the subject's OWN county assessed value that is a real,
      market-grounded ARV (the standard assessment-sales ratio). This is the
      only comp basis available where no sqft exists anywhere in the county.
      It is a proxy, not a like-for-like comp, so it is capped below the
      $/sqft tiers and never graded HIGH.

  (c) Every lead that gets either -> raw['recorded_sales'], the actual
      transaction basket (price, date, deed book/page, grantor/grantee where
      published, arms-length flag) so the number is auditable.

Sources (all free, public, no login / CAPTCHA / WAF bypass):
  NC Buncombe  saledata FeatureServer table, 388k sales with Grantor1/Grantee1,
               SellingPrice, DeedBook/Page, QualifiedSale (N = NOT arms-length),
               VacantLot, Acres. No geometry -> joined by PINN to the county
               parcel polygon layer, which supplies the ring + TaxValue.
  SC Anderson  Parcel_Sales sales roll (polygons): SAPRIC, SALEDATE, SADEBK/PG,
               SATYPE, SAACRE, plus NewPropertyViewer/5 MRKT_VALUE for the ratio
               denominator. NO grantor/grantee published. SC exempt deeds under
               S.C. Code 12-24-70 state NO consideration, so a zero / nominal
               SAPRIC is a legal artefact, not a cheap sale — those are excluded
               and the provenance says so.
               NOT YET PRODUCTIVE (2026-08-03): the county's ArcGIS box was
               flapping all day — 503 for a stretch, then attribute-only queries
               succeeding while every geometry-bearing query returned "Unable to
               complete operation" or zero features. That is a source outage, not
               a block (no 403, no WAF, no CAPTCHA). The adapter's fields, its
               no-pagination quirk and its TLS chain repair are all verified; the
               spatial filter needs one more live pass once the box is healthy.
  NC Cleveland Vacant_ImprovedLot_Sales layers 0 (vacant) + 1 (improved):
               Sales_Amount, Deed_Stamp_Amount, Acres. No parties and no
               assessed value on the layer, so the ratio denominator is joined
               from the free statewide NC OneMap parcel layer (parno == the
               county Parcel_Number). NC excise stamps are $1 per $500, so a
               missing Sales_Amount is backed out of the stamps (verified
               exactly against a live row: 230 stamps == $115,000).

Ring queries are cached per ~0.005-degree bucket (~500 m) so 5,900 Buncombe
leads cost ~1,900 ring calls, not 5,900, and county-centroid geocodes (many
leads sharing one coordinate) are detected and skipped rather than comped
against a courthouse.
"""
from __future__ import annotations

import re
import ssl
from datetime import date, datetime, timedelta, timezone
from statistics import median

import certifi
import structlog

from .http_client import client
from .models import Listing, PropertyKind

log = structlog.get_logger()

# --- tunables ---------------------------------------------------------------
BUFFER_FT = 5280                 # 1-mile comp ring
BUCKET_DEG = 0.005               # ~500 m ring cache grid
SINCE_YEARS = 4                  # recorded-sale window
MIN_ARMS_LENGTH = 10_000         # below this a "sale" is a nominal/family transfer
MAX_SALE = 25_000_000
MIN_ACRES = 0.02
PPA_FLOOR, PPA_CEIL = 500.0, 3_000_000.0      # $/acre sanity band
RATIO_FLOOR, RATIO_CEIL = 0.30, 5.0           # sale / assessed sanity band
MIN_RATIO_COMPS = 3
MIN_RATIO_COMPS_MEDIUM = 8
MIN_LAND_COMPS = 2
MAX_BASKET = 25                  # transactions kept on the lead for audit
CENTROID_MIN_SHARE = 20          # >= this many leads on one coord == county centroid
EMPTY_RING_STREAK_LIMIT = 15     # consecutive empty rings before a county is written off
PAGE = 1000

# Public DigiCert intermediate ("DigiCert Global G2 TLS RSA SHA256 2020 CA1"),
# issued by DigiCert Global Root G2 which certifi already trusts. Inlined rather
# than shipped as a data file because src/foreclosure_scraper/data/ is
# .gitignored. Fetched once from the leaf's own AIA extension
# (http://cacerts.digicert.com/DigiCertGlobalG2TLSRSASHA2562020CA1-1.crt).
_DIGICERT_G2_INTERMEDIATE_PEM = """\
-----BEGIN CERTIFICATE-----
MIIEyDCCA7CgAwIBAgIQDPW9BitWAvR6uFAsI8zwZjANBgkqhkiG9w0BAQsFADBh
MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3
d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBH
MjAeFw0yMTAzMzAwMDAwMDBaFw0zMTAzMjkyMzU5NTlaMFkxCzAJBgNVBAYTAlVT
MRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxMzAxBgNVBAMTKkRpZ2lDZXJ0IEdsb2Jh
bCBHMiBUTFMgUlNBIFNIQTI1NiAyMDIwIENBMTCCASIwDQYJKoZIhvcNAQEBBQAD
ggEPADCCAQoCggEBAMz3EGJPprtjb+2QUlbFbSd7ehJWivH0+dbn4Y+9lavyYEEV
cNsSAPonCrVXOFt9slGTcZUOakGUWzUb+nv6u8W+JDD+Vu/E832X4xT1FE3LpxDy
FuqrIvAxIhFhaZAmunjZlx/jfWardUSVc8is/+9dCopZQ+GssjoP80j812s3wWPc
3kbW20X+fSP9kOhRBx5Ro1/tSUZUfyyIxfQTnJcVPAPooTncaQwywa8WV0yUR0J8
osicfebUTVSvQpmowQTCd5zWSOTOEeAqgJnwQ3DPP3Zr0UxJqyRewg2C/Uaoq2yT
zGJSQnWS+Jr6Xl6ysGHlHx+5fwmY6D36g39HaaECAwEAAaOCAYIwggF+MBIGA1Ud
EwEB/wQIMAYBAf8CAQAwHQYDVR0OBBYEFHSFgMBmx9833s+9KTeqAx2+7c0XMB8G
A1UdIwQYMBaAFE4iVCAYlebjbuYP+vq5Eu0GF485MA4GA1UdDwEB/wQEAwIBhjAd
BgNVHSUEFjAUBggrBgEFBQcDAQYIKwYBBQUHAwIwdgYIKwYBBQUHAQEEajBoMCQG
CCsGAQUFBzABhhhodHRwOi8vb2NzcC5kaWdpY2VydC5jb20wQAYIKwYBBQUHMAKG
NGh0dHA6Ly9jYWNlcnRzLmRpZ2ljZXJ0LmNvbS9EaWdpQ2VydEdsb2JhbFJvb3RH
Mi5jcnQwQgYDVR0fBDswOTA3oDWgM4YxaHR0cDovL2NybDMuZGlnaWNlcnQuY29t
L0RpZ2lDZXJ0R2xvYmFsUm9vdEcyLmNybDA9BgNVHSAENjA0MAsGCWCGSAGG/WwC
ATAHBgVngQwBATAIBgZngQwBAgEwCAYGZ4EMAQICMAgGBmeBDAECAzANBgkqhkiG
9w0BAQsFAAOCAQEAkPFwyyiXaZd8dP3A+iZ7U6utzWX9upwGnIrXWkOH7U1MVl+t
wcW1BSAuWdH/SvWgKtiwla3JLko716f2b4gp/DA/JIS7w7d7kwcsr4drdjPtAFVS
slme5LnQ89/nD/7d+MS5EHKBCQRfz5eeLjJ1js+aWNJXMX43AYGyZm0pGrFmCW3R
bpD0ufovARTFXFZkAdl9h6g4U5+LXUZtXMYnhIHUfoyMo5tS58aI7Dd8KvvwVVo4
chDYABPPTHPbqjc1qCmBaZx2vN4Ye5DUys/vZwP9BFohFrH/6j/f3IL16/RZkiMN
JCqVJUzKoZHm1Lesh3Sz8W2jmdv51b2EQJ8HmA==
-----END CERTIFICATE-----
"""


def _ssl_ctx() -> ssl.SSLContext:
    """certifi + the DigiCert G2 intermediate that Anderson's IIS omits.

    propertyviewer.andersoncountysc.org serves only its leaf certificate, so a
    stock certifi chain fails with 'unable to get local issuer certificate'
    (this silently kills assessor_cards/anderson_sc.py today). Supplying the
    public intermediate REPAIRS the chain — hostname + signature verification
    stay fully on. This is not a TLS bypass.
    """
    ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        ctx.load_verify_locations(cadata=_DIGICERT_G2_INTERMEDIATE_PEM)
    except ssl.SSLError:                       # pragma: no cover - defensive
        log.warning("recorded_sales.intermediate_ca_load_failed")
    return ctx


# --- endpoints --------------------------------------------------------------
BUNCOMBE_SALES = ("https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/"
                  "services/saledata/FeatureServer/0/query")
BUNCOMBE_PARCELS = ("https://gis.buncombecounty.org/arcgis/rest/services/"
                    "property_bc_dis/MapServer/1/query")
ANDERSON_SALES = ("https://propertyviewer.andersoncountysc.org/arcgis/rest/"
                  "services/Parcel_Sales/MapServer/0/query")
ANDERSON_CAMA = ("https://propertyviewer.andersoncountysc.org/arcgis/rest/"
                 "services/NewPropertyViewer/MapServer/5/query")
CLEVELAND_VACANT = ("https://gis.clevelandcounty.com/arcgis/rest/services/Tax/"
                    "Vacant_ImprovedLot_Sales/MapServer/0/query")
CLEVELAND_IMPROVED = ("https://gis.clevelandcounty.com/arcgis/rest/services/Tax/"
                      "Vacant_ImprovedLot_Sales/MapServer/1/query")
# Free statewide NC parcel layer — supplies the assessed value (parval) that
# Cleveland's own sales layers omit. Join key parno == Parcel_Number.
NC_ONEMAP_PARCELS = ("https://services.nconemap.gov/secure/rest/services/"
                     "NC1Map_Parcels/FeatureServer/1/query")
_NC1_FIELDS = "parno,parval,landval,gisacres,struct,siteadd,cntyname"

SUPPORTED = {("NC", "Buncombe"), ("SC", "Anderson"), ("NC", "Cleveland")}


# --- small helpers ----------------------------------------------------------
def _since_iso() -> str:
    return (date.today() - timedelta(days=365 * SINCE_YEARS)).isoformat()


def _bucket(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat / BUCKET_DEG) * BUCKET_DEG, round(lon / BUCKET_DEG) * BUCKET_DEG)


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return f


def _epoch_iso(v) -> str | None:
    n = _num(v)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n / 1000.0, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _yyyymmdd_iso(v) -> str | None:
    s = re.sub(r"\D", "", str(v or ""))
    if len(s) != 8:
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def _norm_pin(v) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(v or "")).upper()


def _buncombe_pinn(pin15: str) -> str | None:
    """Parcel-layer pinnum '962845105300000' -> saledata PINN '9628-45-1053-00000'."""
    p = _norm_pin(pin15)
    return f"{p[0:4]}-{p[4:6]}-{p[6:10]}-{p[10:15]}" if len(p) == 15 else None


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    i = max(0, min(len(vals) - 1, int(round(p * (len(vals) - 1)))))
    return vals[i]


# Place/county-centroid geocodes MEASURED on the 2026-08-03 board (25,552 leads):
# every one of these carries 50-765 leads on a single coordinate, i.e. the
# geocoder fell back to a city/county centre instead of resolving the situs.
# Hard-coding them keeps the guard working on a SMALL incremental batch, where
# the dynamic count below can never reach its threshold.
KNOWN_CENTROID_COORDS: set[tuple[float, float]] = {
    (34.504, -82.65),      # SC Anderson  — county centre, 765 leads
    (35.292, -81.535),     # NC Cleveland — Shelby centre, 53 leads
    (35.544, -82.684),     # NC Buncombe  — Candler/Enka, 334 leads
    (35.618, -82.321),     # NC Buncombe  — Swannanoa/Black Mtn, 201 leads
    (35.655, -82.696),     # NC Buncombe  — Leicester, 151 leads
    (35.595, -82.551),     # NC Buncombe  — 147 leads
}


def _degenerate_coords(listings: list[Listing]) -> set[tuple[float, float]]:
    """Coordinates shared by many leads == a place/county centroid geocode, not a
    situs. Comping against those produces confident nonsense ("recorded sales
    within 1 mile" of a point the property isn't at), so they are skipped."""
    seen: dict[tuple[float, float], int] = {}
    for li in listings:
        if li.latitude and li.longitude:
            k = (round(li.latitude, 3), round(li.longitude, 3))
            seen[k] = seen.get(k, 0) + 1
    return set(KNOWN_CENTROID_COORDS) | {k for k, n in seen.items()
                                         if n >= CENTROID_MIN_SHARE}


class _SourceDown(RuntimeError):
    """A county endpoint answered 5xx — treat the whole county as down for the run."""


async def _unpaged(http, url: str, base: dict) -> list[dict]:
    """Single query with NO paging parameters.

    Anderson's MapServer rejects them outright — sending resultOffset /
    resultRecordCount returns "Pagination is not supported." and adding
    orderByFields returns "Invalid or missing input parameters." — despite its
    metadata advertising supportsPagination. Take whatever its maxRecordCount
    (2000) gives us instead of arguing with it.
    """
    data = dict(base)
    data["f"] = "json"
    r = await http.post(url, data=data, timeout=90.0)
    if 500 <= r.status_code < 600:
        raise _SourceDown(f"{url.split('/services/')[-1][:48]} HTTP {r.status_code}")
    if r.status_code != 200:
        log.warning("recorded_sales.http", url=url.split("/services/")[-1][:48],
                    status=r.status_code)
        return []
    j = r.json()
    if "error" in j:
        log.warning("recorded_sales.query_error", url=url.split("/services/")[-1][:48],
                    msg=str(j["error"].get("message"))[:90])
        return []
    return j.get("features") or []


async def _paged(http, url: str, base: dict, *, page_size: int, page_cap: int) -> list[dict]:
    """Walk resultOffset/resultRecordCount until the server stops.

    Two traps this avoids, both live-observed on these layers:

    1. NEVER decide "last page" by comparing to the page size we ASKED for. Every
       one of these layers silently clamps resultRecordCount, so asking for 2000
       against a 1000-cap layer returns 1000 and a naive `len(batch) < asked`
       check stops after one page (that bug capped the Buncombe sales index at
       1000 of ~30,000 rows). Use exceededTransferLimit.
    2. NEVER compute the next offset as page * page_size. The Buncombe parcel
       layer honours a BYTE budget, not a row count — successive pages came back
       1673, 1685, 1828 rows — so a fixed stride silently skips and duplicates
       rows. Advance the cursor by what the server actually returned.
    """
    feats: list[dict] = []
    offset = 0
    for _ in range(page_cap):
        data = dict(base)
        data.update({"resultOffset": str(offset),
                     "resultRecordCount": str(page_size), "f": "json"})
        r = await http.post(url, data=data, timeout=90.0)
        if 500 <= r.status_code < 600:
            # The county box is down/overloaded — stop the whole county for this
            # run rather than re-asking once per bucket.
            raise _SourceDown(f"{url.split('/services/')[-1][:48]} HTTP {r.status_code}")
        if r.status_code != 200:
            log.warning("recorded_sales.http", url=url.split("/services/")[-1][:48],
                        status=r.status_code)
            break
        j = r.json()
        if "error" in j:
            log.warning("recorded_sales.query_error", url=url.split("/services/")[-1][:48],
                        msg=str(j["error"].get("message"))[:90])
            break
        batch = j.get("features") or []
        feats.extend(batch)
        offset += len(batch)
        if not batch or not j.get("exceededTransferLimit"):
            break
    return feats


async def _ring(http, url: str, lat: float, lon: float, *, where: str,
                out_fields: str, order_by: str, page_size: int = PAGE,
                page_cap: int = 4, paginate: bool = True) -> list[dict]:
    """Distance query. ArcGIS needs resultOffset + resultRecordCount, and
    orderByFields whenever objectIdField is null (true for all four layers) —
    except Anderson, which rejects all three (see _unpaged)."""
    base = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
        "distance": str(BUFFER_FT), "units": "esriSRUnit_Foot",
        "spatialRel": "esriSpatialRelIntersects", "where": where,
        "outFields": out_fields, "returnGeometry": "false",
    }
    if not paginate:
        return await _unpaged(http, url, base)
    base["orderByFields"] = order_by
    return await _paged(http, url, base, page_size=page_size, page_cap=page_cap)


# --- normalised comp record -------------------------------------------------
def _sale(parcel_id, price, sale_date, *, book=None, page=None, grantor=None,
          grantee=None, arms_length=None, qualified_code=None, vacant=None,
          acres=None, assessed=None, price_source="stated", address=None) -> dict:
    return {
        "parcel_id": parcel_id, "price": price, "sale_date": sale_date,
        "deed_book": book, "deed_page": page, "grantor": grantor, "grantee": grantee,
        "arms_length": arms_length, "qualified_code": qualified_code,
        "vacant": vacant, "acres": acres, "assessed": assessed,
        "price_source": price_source, "address": address,
    }


# --- Buncombe ---------------------------------------------------------------
_BUNCOMBE_SALE_FIELDS = ("PINN,Grantor1,Grantee1,SellingPrice,AdjustedSalePrice,"
                         "DeedBook,DeedPage,SellDate,QualifiedSale,VacantLot,Acres,"
                         "Class,Address")
_BUNCOMBE_PARCEL_FIELDS = "pin,pinnum,Acreage,Class,Improved,TaxValue,Address"


async def _buncombe_sale_index(http) -> dict[str, list[dict]]:
    """One prefetch of the whole recent Buncombe sales roll, keyed by PINN.

    ~30k rows for a 4-year window == 16 paged calls, versus a per-lead join.
    """
    idx: dict[str, list[dict]] = {}
    feats = await _paged(http, BUNCOMBE_SALES, {
        "where": f"SellDate > DATE '{_since_iso()}' AND SellingPrice > {MIN_ARMS_LENGTH}",
        "outFields": _BUNCOMBE_SALE_FIELDS, "returnGeometry": "false",
        "orderByFields": "ObjectId",
    }, page_size=1000, page_cap=80)     # saledata maxRecordCount is 1000
    for f in feats:
        a = f.get("attributes") or {}
        pinn = _norm_pin(a.get("PINN"))
        price = _num(a.get("SellingPrice"))
        if not pinn or not price or not (MIN_ARMS_LENGTH <= price <= MAX_SALE):
            continue
        q = (a.get("QualifiedSale") or "").strip().upper()
        idx.setdefault(pinn, []).append(_sale(
            a.get("PINN"), price, _epoch_iso(a.get("SellDate")),
            book=a.get("DeedBook"), page=a.get("DeedPage"),
            grantor=a.get("Grantor1"), grantee=a.get("Grantee1"),
            # Y = county-qualified arms-length, N = explicitly NOT arms-length,
            # P = partial/under review -> unknown. Live ratio check on two rings:
            # Y is tight (p25-p75 1.38-1.72), N is wide (0.83-1.90) and P is
            # small-n and noisier, so only Y is trusted for the medians.
            arms_length={"Y": True, "N": False}.get(q), qualified_code=q or None,
            vacant=(str(a.get("VacantLot")).strip().lower() == "true"),
            acres=_num(a.get("Acres")), address=a.get("Address"),
        ))
    log.info("recorded_sales.buncombe_index", rows=len(feats), pins=len(idx))
    return idx


def _buncombe_join(parcel_feats: list[dict], sale_idx: dict) -> list[dict]:
    """Ring parcels x the prefetched sales roll, joined on the dashed PINN."""
    out: list[dict] = []
    for f in parcel_feats:
        a = f.get("attributes") or {}
        pinn = _buncombe_pinn(a.get("pinnum"))
        if not pinn:
            continue
        sales = sale_idx.get(_norm_pin(pinn))
        if not sales:
            continue
        assessed = _num(a.get("TaxValue"))
        acreage = _num(a.get("Acreage"))
        improved = (a.get("Improved") or "").strip().upper() == "Y"
        for s in sales:
            rec = dict(s)
            rec["assessed"] = assessed if assessed and assessed > 0 else None
            if rec.get("acres") is None:
                rec["acres"] = acreage
            if rec.get("vacant") is None:
                rec["vacant"] = not improved
            out.append(rec)
    return out


def _buncombe_subject_basis(ring_parcels: list[dict], li: Listing) -> float | None:
    """The subject's OWN county assessed value, read from the same layer the
    ratio denominators came from. The board's li.tax_value is NOT usable here —
    on Buncombe it is frequently the land-only or a stale figure (live check:
    board 42,300 vs county 115,300 on the same PIN), so mixing bases would
    scale a good ratio by a wrong denominator."""
    want = _norm_pin(li.parcel_id)
    if not want:
        return None
    for a in ring_parcels:
        if _norm_pin(a.get("pin")) == want or _norm_pin(a.get("pinnum")) == want:
            v = _num(a.get("TaxValue"))
            return v if v and v > 0 else None
    return None


# --- Anderson ---------------------------------------------------------------
_ANDERSON_SALE_FIELDS = "TMS,SATYPE,SALEDATE,SADEBK,SADEPG,SAPRIC,SALOCA,SAACRE,SALEYEAR"


async def _anderson_ring(http, lat: float, lon: float) -> tuple[list[dict], list[dict]]:
    since_year = date.today().year - SINCE_YEARS
    feats = await _ring(
        http, ANDERSON_SALES, lat, lon,
        where=f"SAPRIC > {MIN_ARMS_LENGTH} AND SALEYEAR >= {since_year}",
        out_fields=_ANDERSON_SALE_FIELDS, order_by="OBJECTID_1", paginate=False)
    cama_feats = await _ring(
        http, ANDERSON_CAMA, lat, lon, where="MRKT_VALUE > 0",
        out_fields="TMS,MRKT_VALUE,PHYS_ADDR", order_by="OBJECTID", paginate=False)
    cama: dict[str, float] = {}
    for f in cama_feats:
        a = f.get("attributes") or {}
        v = _num(a.get("MRKT_VALUE"))
        if v and v > 0:
            cama[_norm_pin(a.get("TMS"))] = v
    out: list[dict] = []
    for f in feats:
        a = f.get("attributes") or {}
        price = _num(a.get("SAPRIC"))
        if not price or not (MIN_ARMS_LENGTH <= price <= MAX_SALE):
            continue
        tms = _norm_pin(a.get("TMS"))
        out.append(_sale(
            a.get("TMS"), price,
            _epoch_iso(a.get("SALEDATE")) or (str(a["SALEYEAR"]) if a.get("SALEYEAR") else None),
            book=a.get("SADEBK"), page=a.get("SADEPG"),
            # Anderson publishes NO grantor/grantee on this roll.
            grantor=None, grantee=None,
            arms_length=None, qualified_code=(a.get("SATYPE") or None),
            acres=_num(a.get("SAACRE")), assessed=cama.get(tms),
            address=a.get("SALOCA"),
        ))
    # Second element mirrors the Buncombe ring shape so _subject_assessed can
    # read the subject's OWN MRKT_VALUE off the same layer the denominators
    # came from, even when the subject itself has no recent recorded sale.
    return out, [{"TMS": k, "MRKT_VALUE": v} for k, v in cama.items()]


# --- Cleveland --------------------------------------------------------------
_CLEVELAND_FIELDS_IMPROVED = ("Parcel_Number,Deed_Book,Deed_Page,DateSold_YYYYMMDD,"
                              "Deed_Stamp_Amount,Sales_Amount,Sum_LND_Acres,Tax_Year")
_CLEVELAND_FIELDS_VACANT = ("Parcel_Number,Deed_Book,Deed_Page,DateSold_YYYYMMDD,"
                            "Deed_Stamp_Amount,Sales_Amount,Acres,Tax_Year")
NC_STAMP_PER_DOLLARS = 500.0     # NC excise tax: $1 per $500 of consideration


def _stamp_price(stamps) -> float | None:
    s = _num(stamps)
    return s * NC_STAMP_PER_DOLLARS if s and s > 0 else None


async def _cleveland_ring(http, lat: float, lon: float) -> tuple[list[dict], list[dict]]:
    """Cleveland's own sales layers carry NO assessed value, so the ratio
    denominator comes from the free statewide NC OneMap parcel layer, joined on
    parno == Parcel_Number (verified: both are the plain county parcel id)."""
    nc1 = await _ring(http, NC_ONEMAP_PARCELS, lat, lon,
                      where="cntyname='Cleveland'", out_fields=_NC1_FIELDS,
                      order_by="objectid", page_size=2000)
    val: dict[str, dict] = {}
    for f in nc1:
        a = f.get("attributes") or {}
        pn = _norm_pin(a.get("parno"))
        v = _num(a.get("parval"))
        if pn and v and v > 0:
            val[pn] = a
    out: list[dict] = []
    for url, fields, acre_field, vacant in (
        (CLEVELAND_IMPROVED, _CLEVELAND_FIELDS_IMPROVED, "Sum_LND_Acres", False),
        (CLEVELAND_VACANT, _CLEVELAND_FIELDS_VACANT, "Acres", True),
    ):
        feats = await _ring(http, url, lat, lon, where="1=1", out_fields=fields,
                            order_by="OBJECTID", page_size=2000)
        for f in feats:
            a = f.get("attributes") or {}
            price = _num(a.get("Sales_Amount"))
            src = "stated"
            if not price or price < MIN_ARMS_LENGTH:
                # NC deed stamps back out the consideration exactly ($1 / $500).
                price, src = _stamp_price(a.get("Deed_Stamp_Amount")), "deed_stamps"
            if not price or not (MIN_ARMS_LENGTH <= price <= MAX_SALE):
                continue
            pv = val.get(_norm_pin(a.get("Parcel_Number"))) or {}
            out.append(_sale(
                a.get("Parcel_Number"), price, _yyyymmdd_iso(a.get("DateSold_YYYYMMDD")),
                book=a.get("Deed_Book"), page=a.get("Deed_Page"),
                grantor=None, grantee=None, arms_length=None,
                vacant=vacant, acres=_num(a.get(acre_field)) or _num(pv.get("gisacres")),
                assessed=_num(pv.get("parval")), price_source=src,
                address=pv.get("siteadd") or None,
            ))
    return out, list(val.values())


# --- derivation -------------------------------------------------------------
PROVENANCE = {
    ("NC", "Buncombe"): ("buncombe_saledata_roll",
                         "Buncombe sales roll: grantor/grantee + QualifiedSale published; "
                         "QualifiedSale='N' (not arms-length) excluded from the basket and "
                         "only 'Y' (county-qualified) priced — 'P' is kept for audit but "
                         "left out of the medians."),
    ("SC", "Anderson"): ("anderson_parcel_sales_roll",
                         "Anderson sales roll publishes NO grantor/grantee and no "
                         "arms-length flag. SC exempt deeds (S.C. Code 12-24-70) state no "
                         "consideration, so zero/nominal prices are legal artefacts and are "
                         "excluded — the basket is price-bearing deeds only, unverified as "
                         "arms-length."),
    ("NC", "Cleveland"): ("cleveland_vacant_improved_lot_sales",
                          "Cleveland lot-sales layers publish no parties and no arms-length "
                          "flag; price is the stated Sales_Amount, else backed out of the NC "
                          "excise stamps ($1 per $500). Assessed value for the ratio is "
                          "joined from the statewide NC OneMap parcel layer (parval)."),
}


def _arms_length_only(sales: list[dict]) -> list[dict]:
    """Audit basket: drop only transfers the county has explicitly flagged NOT
    arms-length. A None flag means the county publishes no flag — kept, but the
    provenance string says the basket is unverified."""
    return [s for s in sales if s.get("arms_length") is not False]


def _priced_pool(sales: list[dict]) -> tuple[list[dict], str]:
    """The subset the MEDIANS are computed from.

    Where the county publishes an arms-length flag, only confirmed arms-length
    transfers are priced (Buncombe 'Y'); 'P'/unknown stays in the audit basket
    but out of the math. Where no flag is published at all (Anderson, Cleveland)
    every price-bearing deed is used and the provenance says so.
    """
    confirmed = [s for s in sales if s.get("arms_length") is True]
    if confirmed:
        return confirmed, "county_qualified_arms_length_only"
    return [s for s in sales if s.get("arms_length") is not False], "all_price_bearing_deeds"


def _acre_band(sales: list[dict], subj_acres: float | None) -> tuple[list[dict], str]:
    """Land comps must be size-comparable — $/acre falls off a cliff with lot
    size, so a 0.25-ac subject priced off 13-ac tracts (or vice versa) is
    nonsense. Mirrors enrichment_comps.LAND_LOT_BAND_PCT, widening once rather
    than returning an empty basket."""
    if not subj_acres or subj_acres <= 0:
        return sales, "no subject acreage — unbanded"
    for pct, label in ((0.50, "±50% lot size"), (2.0, "±200% lot size")):
        lo, hi = subj_acres * (1 - min(pct, 0.95)), subj_acres * (1 + pct)
        band = [s for s in sales if s.get("acres") and lo <= float(s["acres"]) <= hi]
        if len(band) >= MIN_LAND_COMPS:
            return band, label
    return sales, "no size-banded comps — unbanded"


def _ppa_list(sales: list[dict], vacant_only: bool) -> list[float]:
    out: list[float] = []
    for s in sales:
        if vacant_only and s.get("vacant") is False:
            continue
        price, ac = s.get("price"), s.get("acres")
        if not price or not ac or ac < MIN_ACRES:
            continue
        ppa = float(price) / float(ac)
        if PPA_FLOOR <= ppa <= PPA_CEIL:
            out.append(round(ppa, 2))
    return sorted(out)


def _ratio_list(sales: list[dict], want_vacant: bool | None) -> list[float]:
    out: list[float] = []
    for s in sales:
        if want_vacant is not None and s.get("vacant") is not None \
                and bool(s["vacant"]) != want_vacant:
            continue
        price, assessed = s.get("price"), s.get("assessed")
        if not price or not assessed or assessed <= 0:
            continue
        r = float(price) / float(assessed)
        if RATIO_FLOOR <= r <= RATIO_CEIL:
            out.append(round(r, 4))
    return sorted(out)


def _basket(sales: list[dict]) -> list[dict]:
    """Newest-first audit trail, capped."""
    return sorted(sales, key=lambda s: (s.get("sale_date") or ""), reverse=True)[:MAX_BASKET]


def _apply(li: Listing, sales: list[dict], *, subject_assessed: float | None,
           basis_source: str, source: str, note: str) -> dict:
    """Write the comp signals onto the lead. Returns a per-lead counts dict."""
    got = {"basket": 0, "land_comps": 0, "ratio": 0}
    arms = _arms_length_only(sales)
    if not arms:
        return got
    raw = li.raw if isinstance(li.raw, dict) else {}
    is_land = li.property_kind == PropertyKind.LAND and not (li.living_sqft and li.living_sqft > 0)

    priced, priced_basis = _priced_pool(arms)
    raw["recorded_sales"] = {
        "source": source,
        "provenance": note,
        "radius_mi": round(BUFFER_FT / 5280.0, 1),
        "since": _since_iso(),
        "count": len(arms),
        "priced_from": priced_basis,
        "priced_count": len(priced),
        "excluded_not_arms_length": sum(1 for s in sales if s.get("arms_length") is False),
        "parties_published": any(s.get("grantor") or s.get("grantee") for s in arms),
        "median_price": round(median([s["price"] for s in priced or arms]), -2),
        "sales": _basket(arms),
    }
    got["basket"] = 1

    # (a) LAND -> the $/acre basket valuation.calc._land_arv already consumes.
    if is_land:
        subj_ac = li.acreage or ((li.lot_size_sqft / 43560.0) if li.lot_size_sqft else None)
        vacant = [s for s in priced
                  if s.get("vacant") is not False and s.get("price") and s.get("acres")
                  and float(s["acres"]) >= MIN_ACRES
                  and PPA_FLOOR <= float(s["price"]) / float(s["acres"]) <= PPA_CEIL]
        banded, band_label = _acre_band(vacant, subj_ac)
        ppa = _ppa_list(banded, vacant_only=True)
        if len(ppa) >= MIN_LAND_COMPS and not raw.get("comps"):
            raw["comps"] = [
                {"sold_price": s["price"], "lot_sqft": round(float(s["acres"]) * 43560.0),
                 "geo_anchored": True, "recorded": True, "source": source,
                 "sale_date": s.get("sale_date"), "deed_book": s.get("deed_book"),
                 "deed_page": s.get("deed_page")}
                for s in banded
            ][:MAX_BASKET]
            raw["comp_median_ppa_recorded"] = round(median(ppa), 2)
            raw["recorded_sales"]["land_comp_band"] = band_label
            got["land_comps"] = len(raw["comps"])

    # (b) IMPROVED (and land where no $/acre basket landed) -> ratio comps.
    if subject_assessed and subject_assessed > 0 and not got["land_comps"]:
        ratios = _ratio_list(priced, want_vacant=True if is_land else False)
        if len(ratios) < MIN_RATIO_COMPS:
            ratios = _ratio_list(priced, want_vacant=None)
        if len(ratios) >= MIN_RATIO_COMPS:
            med = round(median(ratios), 4)
            p25, p75 = _pct(ratios, 0.25), _pct(ratios, 0.75)
            spread_ok = p25 > 0 and (p75 / p25) < 2.0
            raw["recorded_ratio_comps"] = {
                "median_ratio": med,
                "p25_ratio": p25,
                "p75_ratio": p75,
                "count": len(ratios),
                "assessed_basis": round(float(subject_assessed), 2),
                "basis_class": "land" if is_land else "improved",
                "basis_source": basis_source,
                "priced_from": priced_basis,
                "radius_mi": round(BUFFER_FT / 5280.0, 1),
                "since": _since_iso(),
                "source": source,
                # A basis of unknown provenance can never be MEDIUM: the ratio
                # would be scaling a number measured on a different yardstick.
                "confidence": ("MEDIUM" if len(ratios) >= MIN_RATIO_COMPS_MEDIUM
                               and spread_ok and basis_source == "county_layer"
                               else "LOW"),
            }
            got["ratio"] = 1
    li.raw = raw
    return got


# --- entry point ------------------------------------------------------------
async def enrich(listings: list[Listing]) -> list[Listing]:
    """Attach recorded-sales comps for the sales-roll counties. Mutates in place."""
    targets = [li for li in listings
               if (li.state, li.county) in SUPPORTED and li.latitude and li.longitude]
    if not targets:
        return listings
    bad_coords = _degenerate_coords(targets)
    counts = {"leads": 0, "basket": 0, "land_comps": 0, "ratio": 0,
              "skipped_centroid": 0, "no_ring": 0, "skipped_source_down": 0}
    down: set[tuple[str, str]] = set()
    # A county answering 200-with-an-error-body on every ring (Anderson's
    # degraded mode: "Unable to complete operation.") looks like "no comps here"
    # forever. Trip the same breaker after this many consecutive empty rings so
    # one sick service can't soak up a whole run's request budget.
    empty_streak: dict[tuple[str, str], int] = {}
    ring_cache: dict[tuple, tuple[list[dict], list[dict]]] = {}
    buncombe_idx: dict[str, list[dict]] | None = None
    # Anderson's IIS omits its TLS intermediate; the repaired-chain client is
    # opened lazily and only when Anderson leads are actually present.
    and_http = None

    try:
        async with client(timeout=90.0) as http:
            for li in targets:
                if (round(li.latitude, 3), round(li.longitude, 3)) in bad_coords:
                    counts["skipped_centroid"] += 1
                    continue
                st_co = (li.state, li.county)
                if st_co in down:
                    counts["skipped_source_down"] += 1
                    continue
                counts["leads"] += 1
                source, note = PROVENANCE[st_co]
                bkey = (st_co, _bucket(li.latitude, li.longitude))
                if bkey not in ring_cache:
                    try:
                        if st_co == ("NC", "Buncombe"):
                            if buncombe_idx is None:
                                buncombe_idx = await _buncombe_sale_index(http)
                            parcels = await _ring(
                                http, BUNCOMBE_PARCELS, *bkey[1], where="1=1",
                                out_fields=_BUNCOMBE_PARCEL_FIELDS, order_by="objectid",
                                page_size=2000)
                            ring_cache[bkey] = (_buncombe_join(parcels, buncombe_idx),
                                                [f.get("attributes") or {} for f in parcels])
                        elif st_co == ("SC", "Anderson"):
                            if and_http is None:
                                and_http = _anderson_client()
                            ring_cache[bkey] = await _anderson_ring(and_http, *bkey[1])
                        else:
                            ring_cache[bkey] = await _cleveland_ring(http, *bkey[1])
                    except _SourceDown as exc:
                        log.warning("recorded_sales.source_down", county=li.county,
                                    error=str(exc)[:90])
                        down.add(st_co)
                        ring_cache[bkey] = ([], [])
                        counts["leads"] -= 1
                        counts["skipped_source_down"] += 1
                        continue
                    except Exception as exc:  # noqa: BLE001
                        log.warning("recorded_sales.ring_failed", county=li.county,
                                    error=str(exc)[:90])
                        ring_cache[bkey] = ([], [])
                sales, parcel_attrs = ring_cache[bkey]
                if not sales:
                    counts["no_ring"] += 1
                    streak = empty_streak[st_co] = empty_streak.get(st_co, 0) + 1
                    if streak >= EMPTY_RING_STREAK_LIMIT:
                        log.warning("recorded_sales.source_unproductive",
                                    county=li.county, empty_rings=streak)
                        down.add(st_co)
                    continue
                empty_streak[st_co] = 0
                basis, basis_source = _subject_assessed(li, st_co, sales, parcel_attrs)
                got = _apply(li, sales, subject_assessed=basis, basis_source=basis_source,
                             source=source, note=note)
                counts["basket"] += 1 if got["basket"] else 0
                counts["land_comps"] += 1 if got["land_comps"] else 0
                counts["ratio"] += got["ratio"]
    except Exception:  # noqa: BLE001
        log.warning("recorded_sales.aborted")
        return listings
    finally:
        if and_http is not None:
            await and_http.aclose()
    log.info("recorded_sales.done", buckets=len(ring_cache), **counts)
    return listings


def _subject_assessed(li: Listing, st_co: tuple[str, str], sales: list[dict],
                      parcel_attrs: list[dict]) -> tuple[float | None, str]:
    """The subject's assessed value, plus WHERE it came from.

    A sale-to-assessed ratio is only meaningful multiplied by a value on the SAME
    basis as the denominators, so the ring's own layer is preferred. The
    lead-carried assessed_value is a last resort of unknown provenance and is
    labelled so the calculator can grade it down.
    """
    if st_co == ("NC", "Buncombe"):
        v = _buncombe_subject_basis(parcel_attrs, li)
        if v:
            return v, "county_layer"
    want = _norm_pin(li.parcel_id)
    key, field = {("SC", "Anderson"): ("TMS", "MRKT_VALUE"),
                  ("NC", "Cleveland"): ("parno", "parval")}.get(st_co, (None, None))
    if key and want:
        for a in parcel_attrs:
            if _norm_pin(a.get(key)) == want:
                v = _num(a.get(field))
                if v and v > 0:
                    return v, "county_layer"
    if want:
        for s in sales:
            if _norm_pin(s.get("parcel_id")) == want and s.get("assessed"):
                return float(s["assessed"]), "county_layer"
    # Last resort: the assessed_value already on the lead. NOT li.tax_value —
    # see _buncombe_subject_basis for why those two are not interchangeable.
    v = li.assessed_value
    return (float(v), "lead_assessed_value") if v and v > 0 else (None, "none")


def _anderson_client():
    """httpx client with the repaired Anderson certificate chain (verify ON).

    Keeps the repo's per-host throttle: a bespoke client must never become a
    politeness hole, least of all against a county box that is already
    answering 503.
    """
    import httpx

    from .http_client import DEFAULT_HEADERS, _ThrottledTransport
    transport = _ThrottledTransport(
        httpx.AsyncHTTPTransport(retries=0, verify=_ssl_ctx()))
    return httpx.AsyncClient(timeout=90.0, headers=dict(DEFAULT_HEADERS),
                             follow_redirects=True, transport=transport)
