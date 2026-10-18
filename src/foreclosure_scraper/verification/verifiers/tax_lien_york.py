"""tax_lien, York County SC: is this parcel still on the county's own active tax-sale list?

A tax_lien adapter beside tax_lien_buncombe (the reference): same SIGNAL, same GOVERNS, same
verdict meanings, one tax_lien ledger. Added 2026-10-18 (tax-claim-has-checker's residual
counties beyond the original 5): 844 York rows carried a tax_sale listing type and no verifier
knew the county's site.

THE SOURCE (scrapers/counties_sc/york_delinquent_tax.py already reads it for the board; no login,
no CAPTCHA, no terms click-through -- a public ArcGIS FeatureServer, 853 features, small enough to
load whole rather than query per parcel):

    https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/
    Tax_Sale_Properties_2025_View/FeatureServer/0

Uses the shared _arcgis_layer helper (layer_for): one load per sweep run, shared by every row
that needs it, instead of one request per parcel.

THE CLAIM AND WHAT "STILL TRUE" MEANS (live-checked 2026-10-18, not assumed). This view is the
county's own curated "currently delinquent enough to go to tax sale" list, not a generic parcel
database -- the scraper's own module docstring and field list confirm every row it publishes came
straight from this view. `SOLD` was checked across the full live dataset: every one of 853
current features reads SOLD='N' (zero 'Y'), which means the county does not flip this field in
place when a property resolves -- it DROPS the row from the view entirely (sold at auction, or
redeemed by the owner paying up). So the live signal is presence in the layer, not a field value:
a parcel still in the loaded snapshot means the county's own list still carries it; absent means
it left the list, for whatever reason (SalePrice/DateSold on the scraper's own rows are the
property's LAST ORDINARY sale, unrelated to the tax auction -- not useful here).

VERDICTS:
  confirmed    the parcel is a row in the layer snapshot today.
  stale        the parcel is not in a COMPLETE snapshot (the claim WAS true -- the scraper saw it
               on the list -- and is not anymore: resolved by sale or redemption, either way the
               distress signal this row scores is no longer current).
  unconfirmed  no parcel id on the row, or the layer load itself did not complete (retried later;
               the jail-verifier rule applies here too: never decide "dropped off" from an
               incomplete snapshot).
  refuted      never (the county publishes no field here that could contradict the scraper's own
               read -- an absent-from-a-complete-snapshot answer only ever means "no longer on
               the list today").

Evidence is a whitelist (public ledger): no owner names, no mailing addresses.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _arcgis_layer as ag
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 21          # the active-sale season is short (Oct-Jan); re-check every 3 weeks
RETRY_DAYS = 7
SOURCE = "services1.arcgis.com (York County SC Tax Sale Properties)"
GOVERNS = tc.GOVERNS
SOURCE_SLUG = "counties_sc.york_delinquent_tax"
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed",)

LAYER = ("https://services1.arcgis.com/2AGLxyiJoNiVHKwq"
        "/arcgis/rest/services/Tax_Sale_Properties_2025_View/FeatureServer/0")
OUT_FIELDS = "ParcelID,TAXMAPID,NAME,ownernames,SOLD"

_NAME = __name__.rsplit(".", 1)[-1]


def applies(row: dict) -> bool:
    return (str(row.get("state") or "").strip().upper() == "SC"
            and str(row.get("county") or "").strip().lower() == "york"
            and str(row.get("source") or "") == SOURCE_SLUG
            and tc.claims_property_tax(row, False))


async def _snapshot(client: Any) -> ag.LayerSnapshot:
    return await ag.layer_for(client, LAYER, out_fields=OUT_FIELDS, order_by="OBJECTID")


def _find(snap: ag.LayerSnapshot, norm: str) -> Optional[dict]:
    for a in snap.rows:
        if (tc.alnum(a.get("ParcelID") or "") == norm
                or tc.alnum(a.get("TAXMAPID") or "") == norm):
            return a
    return None


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client: Any, *, today: Optional[date] = None) -> VerificationResult:
    pid = str(tc.g(row, "parcel_id") or "").strip()
    if not pid:
        return _res("unconfirmed", {"reason": "no_parcel"})
    snap = await _snapshot(client)
    if not snap.complete:
        return _res("unconfirmed", {"reason": "fetch_failed", **snap.evidence()})
    norm = tc.alnum(pid)
    match = _find(snap, norm)
    if match is None:
        return _res("stale", {"tax_parcel": pid, "still_listed": False, **snap.evidence()})
    owner = str(match.get("NAME") or match.get("ownernames") or "").strip()
    row_owner = str(tc.g(row, "owner_name") or "").strip()
    owner_match = ("same" if (owner and row_owner and tc.alnum(owner) == tc.alnum(row_owner))
                  else ("unknown" if not (owner and row_owner) else "differs"))
    return _res("confirmed", {"tax_parcel": pid, "still_listed": True,
                              "owner_match": owner_match, **snap.evidence()})
