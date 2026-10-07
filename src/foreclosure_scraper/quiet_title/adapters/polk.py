"""Polk County NC: the statewide parcel record plus the county's own register index, live.

  * Parcel record: NC OneMap (nc_onemap.py). Polk's short assessor legal is blank on that layer, so
    the legal description is always 'needs the deed image'.
  * Register of Deeds: Cott eSearch v4 on cotthosting.com, open as a 'Guest User' with no
    click-through and no credentials (county records matrix: access open; plain GETs of the name
    form and of a book/page search answered 200 with the results grid on 2026-10-07, no login
    redirect). The same app and form as Buncombe's register (cott_v4.py). Its index types are
    CONSOLIDATED REAL PROPERTY and PRE 95 REAL ESTATE only: there is NO deaths index online, so the
    deaths step is not run and the sheet says why. Deed images sit behind a paid order flow: never
    opened.
  * Tax bills: not read (the county tax search answered scripts with a Cloudflare block page when
    the matrix was built); the where-to-look block gives the site.
"""
from __future__ import annotations

from ..model import RecordCheck
from .cott_v4 import CottV4Register
from .nc_onemap import ECOURTS, ONEMAP_LAYER, SRC_ONEMAP, NcOneMapAdapter

ROD = "https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4/"
SRC_ROD = "Polk County Register of Deeds, eSearch (guest, cotthosting.com)"


class PolkAdapter(CottV4Register, NcOneMapAdapter):
    county = "Polk"
    register_fetched = True
    rod_base = ROD
    src_rod = SRC_ROD
    deaths_index = False
    deaths_note = ("Polk's online register index offers real-property indexes only (consolidated real property and "
                   "pre-1995 real estate); it has no deaths index online.")

    def register_link(self):
        return self.rod_name

    def static_records(self):
        out = [r for r in super().static_records() if not r.record.startswith("Deed images")]
        out.insert(2, RecordCheck("Deed images (the deeds themselves, including the full legal description)",
                                  "not opened", "The register sells images through a paid order flow; this tool "
                                                "reads the index only.",
                                  "The full legal description must be read from the deed image (book/page link in "
                                  "section 2)."))
        return out

    def how_to(self, result):
        steps = super().how_to(result)
        rod = ("Register of Deeds: the deed and the chain", [
            f"Open {self.rod_name} in a browser. It opens as 'Guest User' with no login.",
            "For the deed the record cites, open the book/page link in section 2 (Book/Page search, index All); the "
            "entry whose year agrees with the record's deed date is the deed the record cites. Click its book/page "
            "for Document Details.",
            "For the chain and the owner's name, use Quick Name: last name (Exactly), first name (Begins With), the "
            "party side and filed-thru date shown for each search in the exhibit list, then Search (All Matches).",
            "The deed image (with the full legal description) is a paid copy from the register's cart, or a visit "
            "to the Columbus office.",
        ])
        return [steps[0], rod] + [s for s in steps[1:] if not s[0].startswith("Register of Deeds")]

    def sources(self):
        w_tax = [s for s in super().sources() if s[0].endswith("tax site")]
        return [(SRC_ONEMAP, ONEMAP_LAYER, "Free public map service (ArcGIS), no login, no key."),
                (SRC_ROD, self.rod_name, "Free; opens as a guest user; no login, no click-through. Document images "
                                         "(a paid order flow) not opened."),
                *w_tax,
                ("NC eCourts (estates, special proceedings, civil)", ECOURTS,
                 "CAPTCHA in front of the search: walled, not queried.")]

    def not_established(self):
        return ["The full legal description: the statewide layer's short assessor legal is blank for Polk, and the "
                "deed image (a paid copy) was not opened.",
                "Whether an owner of record has died: Polk's register has no deaths index online.",
                "Tax bills and amounts due: not read for this county."]
