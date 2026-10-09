"""Any NC county whose register runs Cott eSearch v4 open to a guest with no sign-in button: the statewide
parcel record (NC OneMap) plus the county's own register index, read live (the Polk pattern).

WHY (audit 2026-10-09, lawyer_lane): the intake read the register for Buncombe and Polk only; every
other county got the parcel record and a link. These registers are the ones rod/nc_cott_v4.py
already reads by script (COUNTIES, guest=False: no 'Sign in as a Guest' click needed), so the intake
can follow the deed the county record cites (book/page), its index description and the chain, the
same way as Polk. Counties behind the guest button are not served here (the intake's fetcher does
not press it). Deed images sit behind the vendor's paid order flow: never opened.
"""
from __future__ import annotations

from ...rod.nc_cott_v4 import COUNTIES as _COTT
from ..model import RecordCheck
from .cott_v4 import CottV4Register
from .nc_onemap import ECOURTS, ONEMAP_LAYER, SRC_ONEMAP, NcOneMapAdapter

#: open Cott v4 registers (no guest button), excluding Buncombe and Polk (their own adapters)
OPEN_COTT = {c: v.base for c, v in _COTT.items() if not v.guest and c not in ("Buncombe", "Polk")}


class CottOneMapAdapter(CottV4Register, NcOneMapAdapter):
    register_fetched = True
    deaths_index = False
    deaths_note = ("The register's online index types were not checked for a deaths index by this tool; the "
                   "deaths step is not run.")

    @classmethod
    def for_cott_county(cls, county: str) -> type["CottOneMapAdapter"]:
        base = OPEN_COTT[county]
        return type(f"CottOneMap{county}Adapter", (cls,),
                    {"county": county, "rod_base": base,
                     "src_rod": f"{county} County Register of Deeds, eSearch (guest, no sign-in)"})

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
            "entry whose date agrees with the record's deed date is the deed the record cites.",
            "For the chain, use Quick Name with the party side and filed-thru date shown in the exhibit list.",
            "The deed image (with the full legal description) is a paid copy from the register's cart, or a visit "
            "to the register's office.",
        ])
        return [steps[0], rod] + [s for s in steps[1:] if not s[0].startswith("Register of Deeds")]

    def sources(self):
        w_tax = [s for s in super().sources() if s[0].endswith("tax site")]
        return [(SRC_ONEMAP, ONEMAP_LAYER, "Free public map service (ArcGIS), no login, no key."),
                (self.src_rod, self.rod_name, "Free; opens as a guest user; no login. Document images (a paid order "
                                              "flow) not opened."),
                *w_tax,
                ("NC eCourts (estates, special proceedings, civil)", ECOURTS,
                 "CAPTCHA in front of the search: walled, not queried.")]

    def not_established(self):
        return ["The full legal description: the deed image (a paid copy) was not opened.",
                "Whether an owner of record has died: no deaths index was searched.",
                "Tax bills and amounts due: not read for this county."]
