"""Column-accuracy invariants (audit 2026-10-09, area column_accuracy; docs/audit_2026-10-09/column_accuracy.md).

Every FIELD column (address, parcel_id, owner_name, owner mailing, assessed / tax value, sqft,
beds/baths, lot size, year built, legal description, taxpayer of record, phone, email) was sampled
(30 rows per column per state, stratified by source and county, HOT/WARM first) and checked
against the primary record live; the classes found systematic got a fix and one check each:

  column-email-owner-only          best_email is the owner's address, never an artifact     max 0
  column-phone-fuzzy-rechecked     a dialable Soundex voter phone sits on an owner-named voter max 0
  column-phone-agent-not-usable    an agent / office / attorney phone is never usable          max 0
  column-call-ready-phone-nanp     a call-ready row's phone is a NANP number                  max 0
  column-sc-assessed-not-market    an SC assessed value is not the market value               max 0
  column-house-number-glued        '1000EXAMPLE DRIVE' (Berkeley 0; others max 40)
  column-layer-map-semantics       the layer registry maps values to totals, sqft to an area  max 0
  column-fill-call-list            report: HOT / WARM / call-ready fill and placeholders

The extractors, placeholder_class and compact() are shared with the sampling scripts (compact()
carries names: its output is written only outside the repo).
Memory: counters and at most SAMPLE row references per check.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8

#: the FIELD columns this area grades (the owner's names for them)
COLUMNS = ("address", "parcel_id", "owner_name", "owner_mailing", "assessed_value", "sqft",
           "beds_baths", "lot_size", "year_built", "legal_description", "taxpayer_of_record",
           "phone", "email")


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _f(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def mailing_text(row: dict) -> str | None:
    om = _raw(row).get("owner_mailing")
    if isinstance(om, str):
        return om.strip() or None
    m = _d(om).get("mailing")
    if isinstance(m, dict):
        m = " ".join(str(v) for v in m.values() if v)
    m = str(m or "").strip()
    return m or None


def taxpayer(row: dict) -> tuple[str | None, str | None]:
    """(name, where) of the name read from the county roll / parcel record, in
    gap_matrix.taxpayer_of_record_present's order."""
    raw = _raw(row)
    g = _d(raw.get("gis"))
    if g.get("owner"):
        return str(g["owner"]), "gis.owner"
    om = _d(raw.get("owner_mailing"))
    if om.get("owner") and om.get("source") != "liensnc_filing":
        return str(om["owner"]), "owner_mailing.owner"
    for k, f in (("qpaybill_roll", "owner"), ("lrcpwa", "owner"), ("heir_estate", "owner_of_record"),
                 ("mcdowell_probate", "ownname")):
        b = _d(raw.get(k))
        if b.get(f):
            return str(b[f]), f"{k}.{f}"
    if row.get("owner_name") and row.get("listing_type") in ("tax_lien", "tax_sale"):
        return str(row["owner_name"]), "owner_name(tax row)"
    return None, None


def extract(row: dict) -> dict:
    raw = _raw(row)
    out = {
        "address": row.get("street_address") or None,
        "parcel_id": row.get("parcel_id") or None,
        "owner_name": row.get("owner_name") or None,
        "owner_mailing": mailing_text(row),
        "assessed_value": next((v for v in (row.get("assessed_value"), row.get("market_value"),
                                            row.get("tax_value")) if v), None),
        "sqft": row.get("living_sqft") or None,
        "beds_baths": ((row.get("bedrooms"), row.get("bathrooms"))
                       if (row.get("bedrooms") or row.get("bathrooms")) else None),
        "lot_size": row.get("acreage") or row.get("lot_size_sqft") or None,
        "year_built": row.get("year_built") or None,
        "legal_description": row.get("legal_description") or None,
        "taxpayer_of_record": taxpayer(row)[0],
        "phone": _d(raw.get("owner_phone")).get("phone") or None,
        "email": _d(raw.get("owner_email")).get("best_email") or None,
    }
    return out


_PH_OWNER = re.compile(r"^(unknown|n/?a|none|owner|current owner|not available|tbd|see .*|"
                       r"owner of record|property owner|occupant|resident|record owner)$", re.I)
_PH_ADDR = re.compile(r"^(unknown|n/?a|none|tbd|not assigned|no address|address unknown|0+)\b", re.I)
_PH_PARCEL = re.compile(r"(?i)unknown|none|^na$|tbd|various|^0+$")
_PH_LEGAL = re.compile(r"(?i)^(see deed|n/?a|none|unknown|tbd|\.|-|0)$")
_EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_EMAIL_PH = re.compile(r"(?i)^(no|none|noemail|no-?reply|donotreply|test|example|na|n/a|unknown)@|@example\.")
_HOUSE = re.compile(r"^\s*\d+[A-Z]?\b")


def placeholder_class(col: str, v, row: dict) -> str | None:
    """A non-empty value that is not a value (a placeholder / impossible number), by class; None
    when it is a real-looking value."""
    if col == "address":
        s = str(v).strip()
        if _PH_ADDR.match(s):
            return "placeholder_text"
        if re.match(r"(?i)^p\.?\s*o\.?\s*box\b", s):
            return "po_box_as_situs"
        if re.match(r"^\s*0+\s", s):
            return "house_number_zero"
        if not _HOUSE.match(s):
            return "street_only"
        return None
    if col == "parcel_id":
        s = re.sub(r"[^A-Za-z0-9]", "", str(v))
        if len(s) < 4 or not re.search(r"\d", s) or _PH_PARCEL.search(s):
            return "junk_parcel"
        return None
    if col in ("owner_name", "taxpayer_of_record"):
        s = str(v).strip()
        if _PH_OWNER.match(s) or len(s) < 3:
            return "placeholder_name"
        return None
    if col == "owner_mailing":
        s = str(v).strip()
        if _PH_ADDR.match(s):
            return "placeholder_text"
        if not re.search(r"\d", s):
            return "no_number"
        return None
    if col == "assessed_value":
        x = _f(v)
        if x is None or x <= 0:
            return "zero_or_text"
        if x < 1000:
            return "under_1000"
        if x >= 1e9:
            return "over_1e9"
        return None
    if col == "sqft":
        x = _f(v)
        if x is None or x <= 0:
            return "zero_or_text"
        if x < 150:
            return "under_150"
        if x > 30000 and str(row.get("property_kind") or "") in ("sfr", "single_family", "PropertyKind.SFR"):
            return "sfr_over_30000"
        return None
    if col == "beds_baths":
        b, ba = v
        b, ba = _f(b), _f(ba)
        if (b is not None and (b <= 0 or b > 20)) or (ba is not None and (ba <= 0 or ba > 20)):
            return "zero_or_over_20"
        return None
    if col == "lot_size":
        x = _f(v)
        if x is None or x <= 0:
            return "zero_or_text"
        return None
    if col == "year_built":
        x = _f(v)
        if x is None or x < 1700 or x > 2027:
            return "impossible_year"
        return None
    if col == "legal_description":
        s = str(v).strip()
        if _PH_LEGAL.match(s) or len(s) < 4:
            return "placeholder_text"
        return None
    if col == "phone":
        d = re.sub(r"\D", "", str(v))
        if len(d) == 11 and d.startswith("1"):
            d = d[1:]
        if len(d) != 10 or d[0] in "01" or d[3] in "01" or len(set(d)) == 1:
            return "not_nanp"
        if d[3:6] == "555" and d[6:8] == "01":
            return "fictional_555"
        return None
    if col == "email":
        s = str(v).strip()
        if not _EMAIL_OK.match(s):
            return "malformed"
        if _EMAIL_PH.search(s):
            return "placeholder_email"
        return None
    return None


def groups(row: dict) -> list[str]:
    raw = _raw(row)
    out = ["all"]
    tier = str(_d(raw.get("distress_stack")).get("tier") or "")
    if tier in ("HOT", "WARM"):
        out.append("hot_warm")
        out.append(tier.lower())
    if str(_d(raw.get("call_ready")).get("tier") or "") in ("A", "B"):
        out.append("call_ready")
    return out


def compact(row: dict) -> dict:
    """The fields the live check needs (PRIVATE: names; written only outside the repo)."""
    raw = _raw(row)
    g = _d(raw.get("gis"))
    ph = _d(raw.get("owner_phone"))
    em = _d(raw.get("owner_email"))
    om = raw.get("owner_mailing")
    tp, tpw = taxpayer(row)
    return {
        "state": row.get("state"), "county": row.get("county"), "source": row.get("source"),
        "listing_type": row.get("listing_type"), "property_kind": row.get("property_kind"),
        "groups": groups(row), "source_url": row.get("source_url"),
        "street_address": row.get("street_address"), "city": row.get("city"), "zip": row.get("zip_code"),
        "lat": row.get("latitude"), "lng": row.get("longitude"),
        "parcel_id": row.get("parcel_id"), "owner_name": row.get("owner_name"),
        "mailing": mailing_text(row),
        "mailing_src": _d(om).get("source") if isinstance(om, dict) else "str",
        "assessed_value": row.get("assessed_value"), "market_value": row.get("market_value"),
        "tax_value": row.get("tax_value"), "living_sqft": row.get("living_sqft"),
        "living_sqft_estimated": row.get("living_sqft_estimated"),
        "bedrooms": row.get("bedrooms"), "bathrooms": row.get("bathrooms"),
        "acreage": row.get("acreage"), "lot_size_sqft": row.get("lot_size_sqft"),
        "year_built": row.get("year_built"),
        "legal_description": (row.get("legal_description") or "")[:300] or None,
        "taxpayer": tp, "taxpayer_where": tpw,
        "phone": ph.get("phone"), "phone_source": ph.get("source"), "phone_match": ph.get("match"),
        "phone_line": ph.get("line_type"), "phone_owner_match": ph.get("owner_name_match"),
        "email": em.get("best_email"), "email_class": em.get("best_classification"),
        "prov": {k: raw.get(k) for k in ("owner_name_source", "sqft_source", "situs_address_source",
                                         "address_was_owner_mailing", "parcel_from_address",
                                         "parcel_from_geo", "owner_name_as_of", "geo_imprecise",
                                         "situs_road_only") if raw.get(k) is not None},
        "gis_src": g.get("source"), "gis_owner": g.get("owner"),
    }


# =================================================================================================
# The invariants
# =================================================================================================
def _ref(row: dict) -> str:
    return f"{row.get('state') or ''}:{row.get('county') or ''}:{row.get('parcel_id') or '-'}"


class _Check:
    name = ""
    max_violations = 0
    doc = ""

    def __init__(self):
        self.checked = 0
        self.violations = 0
        self.samples: list[str] = []
        self.by: Counter = Counter()

    def bad(self, row: dict, why: str = "") -> None:
        self.violations += 1
        if why:
            self.by[why] += 1
        if len(self.samples) < SAMPLE:
            self.samples.append(_ref(row))

    def extra(self) -> str:
        return ""

    def finish(self) -> dict:
        by = ", ".join(f"{k} {v:,}" for k, v in self.by.most_common(6))
        detail = (f"{self.violations:,} of {self.checked:,} checked" + (f" ({by})" if by else "")
                  + (f"; e.g. {', '.join(self.samples)}" if self.samples else "") + self.extra())
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": self.max_violations, "ok": self.violations <= self.max_violations,
                "detail": detail}


class EmailOwnerOnly(_Check):
    """column-email-owner-only: a published raw.owner_email.best_email is the OWNER's address
    (best_classification 'owner') and not a json-dump escape artifact. The 10/9 checkpoint as
    stored: 46,978 best_emails, 0 of a 58-row sample correct (41,196 escape artifacts; the rest
    agents', contractors', lien agents'). Fixed at the source (enrichment_surface_contacts) and at
    publish (web_artifact._to_dict -> normalized_owner_email_block). max 0."""
    name = "column-email-owner-only"

    def feed(self, row: dict) -> None:
        oe = _raw(row).get("owner_email")
        if not isinstance(oe, dict) or not oe.get("best_email"):
            return
        self.checked += 1
        if oe.get("best_classification") != "owner":
            self.bad(row, f"not_owner:{oe.get('best_classification')}")
            return
        from foreclosure_scraper.enrichment_email_extract import repair_escape_artifact
        rest = {k: v for k, v in _raw(row).items() if k != "owner_email"}
        if repair_escape_artifact(oe["best_email"], rest) != str(oe["best_email"]).strip().lower():
            self.bad(row, "escape_artifact")


class PhoneFuzzyRechecked(_Check):
    """column-phone-fuzzy-rechecked: a dialable NC voter-file phone from a Soundex tier
    ('fuzzy:...') was re-checked against the voter file and found on a voter carrying the owner's
    own name (identity_basis 'fuzzy_phone_on_owner_named_voter', enrichment_sc_phone). A live check
    of the sample found 6 of 6 'fuzzy:soundex+county-unique' phones on a voter with another name,
    one on a call-ready row. Fails until the next run's voter_phone step re-gates them. max 0."""
    name = "column-phone-fuzzy-rechecked"

    def feed(self, row: dict) -> None:
        op = _raw(row).get("owner_phone")
        if not isinstance(op, dict) or not op.get("phone") or op.get("source") != "ncsbe_voter":
            return
        if not str(op.get("match") or "").lower().startswith("fuzzy:"):
            return
        from foreclosure_scraper.enrichment_sc_phone import is_owner_phone_usable
        self.checked += 1
        if is_owner_phone_usable(op) and op.get("identity_basis") != "fuzzy_phone_on_owner_named_voter":
            cr = str(_d(_raw(row).get("call_ready")).get("tier") or "")
            self.bad(row, "call_ready" if cr in ("A", "B") else "dialable")


class PhoneAgentNotUsable(_Check):
    """column-phone-agent-not-usable: an owner_phone from a listing agent, office, attorney or a
    raw-text scan is never usable as the owner's number (enrichment_sc_phone.owner_phone_block_
    reason). 10/9 checkpoint: 170 such blocks (34 HOT/WARM), all blocked by role, 0 usable. max 0."""
    name = "column-phone-agent-not-usable"

    def feed(self, row: dict) -> None:
        op = _raw(row).get("owner_phone")
        if not isinstance(op, dict) or not op.get("phone"):
            return
        from foreclosure_scraper.enrichment_sc_phone import _is_agent, is_owner_phone_usable
        if not _is_agent(op):
            return
        self.checked += 1
        if is_owner_phone_usable(op):
            self.bad(row, str(op.get("source")))


class CallReadyPhoneNanp(_Check):
    """column-call-ready-phone-nanp: a call-ready (tier A/B) row's owner phone is a well-formed
    NANP number. 10/9 checkpoint: 6 of 799 call-ready rows were not. max 0."""
    name = "column-call-ready-phone-nanp"

    def feed(self, row: dict) -> None:
        if str(_d(_raw(row).get("call_ready")).get("tier") or "") not in ("A", "B"):
            return
        ph = _d(_raw(row).get("owner_phone")).get("phone")
        if not ph:
            return
        self.checked += 1
        cls = placeholder_class("phone", ph, row)
        if cls:
            self.bad(row, cls)


class ScAssessedNotMarket(_Check):
    """column-sc-assessed-not-market: an SC assessed_value is the 4% / 6% / 10.5% ratio figure,
    never equal to the market value. 10/9 checkpoint: 2,224 rows (enrichment_owner_mailing copied
    the county appraisal into all three value columns). Fixed at the source (SC skipped) and
    withheld at publish (web_artifact._to_dict). max 0."""
    name = "column-sc-assessed-not-market"

    def feed(self, row: dict) -> None:
        if str(row.get("state") or "").upper() != "SC":
            return
        av, mv = _f(row.get("assessed_value")), _f(row.get("market_value"))
        if not av or not mv:
            return
        self.checked += 1
        if abs(av - mv) <= 0.01 * mv:
            self.bad(row, str(row.get("source")))


_GLUED = re.compile(r"^\s*\d+(?!(?:ST|ND|RD|TH)\b)[A-Za-z]{3,}", re.I)


class HouseNumberGlued(_Check):
    """column-house-number-glued: a mailing or situs street whose house number is glued to the
    street name ('1000EXAMPLE DRIVE'). 10/9 checkpoint: 1,540 Berkeley PayStar mailings (fixed:
    mailing_shape.unglue_house_number in the scraper) + 33 rows from 12 sources' own text (left;
    max 40). Berkeley rows count against max 0 separately (detail)."""
    name = "column-house-number-glued"
    max_violations = 40

    def __init__(self):
        super().__init__()
        self.berkeley = 0

    def feed(self, row: dict) -> None:
        m = mailing_text(row)
        a = row.get("street_address")
        if not m and not a:
            return
        self.checked += 1
        if (m and _GLUED.match(m)) or (a and _GLUED.match(str(a))):
            src = str(row.get("source"))
            if "berkeley_paystar" in src:
                self.berkeley += 1
            self.bad(row, src)

    def extra(self) -> str:
        return f"; berkeley_paystar {self.berkeley} (must be 0)"

    def finish(self) -> dict:
        r = super().finish()
        r["ok"] = r["ok"] and self.berkeley == 0
        return r


#: value columns may not be read from one COMPONENT (land or building) of the value; living_sqft
#: may not be read from a money field
_COMPONENT = re.compile(r"(?i)land|bldg|building|improv|impr$|^impr|dwelling_val")
_MONEY = re.compile(r"(?i)value|val$|_val|apprais|tax|price|amount|amt|^dwelling$")


def layer_map_problems() -> list[str]:
    """Mapping entries in parcel_cache's layer registry whose source field contradicts the column
    (audit 2026-10-09: Spartanburg market/tax = building only, Polk living_sqft = BUILDING_VALUE,
    Rutherford / McDowell / Mitchell / NC OneMap tax_value = land value)."""
    from foreclosure_scraper import parcel_cache as P
    cfgs = dict(P.PARCEL_LAYERS)
    cfgs.update({f"SC:{k}": v for k, v in getattr(P, "SC_DUAL_LAYERS", {}).items()})
    cfgs["NC_ONEMAP"] = P.nc_onemap_cfg("Wake")
    out = []
    for county, cfg in cfgs.items():
        m = cfg.get("map") or {}
        for col in ("market_value", "tax_value"):
            spec = m.get(col)
            if isinstance(spec, str) and _COMPONENT.search(spec) and not re.search(r"(?i)total|tot", spec):
                out.append(f"{county}.{col}={spec}")
        sq = m.get("living_sqft")
        if isinstance(sq, str) and _MONEY.search(sq) and not re.search(r"(?i)sq|area|heat", sq):
            out.append(f"{county}.living_sqft={sq}")
    return out


class LayerMapSemantics(_Check):
    """column-layer-map-semantics: the parcel-layer registry maps every value column to a TOTAL
    and living_sqft to an area field (checked once, at finish). 10/9 before the fix: 8 entries.
    max 0."""
    name = "column-layer-map-semantics"

    def feed(self, row: dict) -> None:
        pass

    def finish(self) -> dict:
        probs = layer_map_problems()
        self.checked = 1
        self.violations = len(probs)
        return {"name": self.name, "checked": self.checked, "violations": self.violations,
                "max_violations": 0, "ok": not probs,
                "detail": ("; ".join(probs[:10])) or "every value column maps to a total, sqft to an area"}


class FillOnCallList(_Check):
    """column-fill-call-list (report): for each field column, how many HOT, WARM and call-ready
    (tier A/B) rows have it and how many of those values are placeholders (placeholder_class).
    Never fails; its detail is the measurement the owner asked for."""
    name = "column-fill-call-list"
    max_violations = 10 ** 12

    def __init__(self):
        super().__init__()
        self.n = Counter()
        self.fill = Counter()
        self.ph = Counter()

    def feed(self, row: dict) -> None:
        gs = [g for g in groups(row) if g in ("hot", "warm", "call_ready")]
        if not gs:
            return
        self.checked += 1
        vals = extract(row)
        for g in gs:
            self.n[g] += 1
            for col in COLUMNS:
                v = vals.get(col)
                if v in (None, "", [], {}):
                    continue
                self.fill[(g, col)] += 1
                if placeholder_class(col, v, row):
                    self.ph[(g, col)] += 1

    def finish(self) -> dict:
        parts = []
        for g in ("hot", "warm", "call_ready"):
            cols = ", ".join(f"{c} {self.fill[(g, c)]}/{self.ph[(g, c)]}" for c in COLUMNS)
            parts.append(f"{g} n={self.n[g]}: {cols}")
        return {"name": self.name, "checked": self.checked, "violations": 0, "max_violations": 0,
                "ok": True, "detail": "filled/placeholder per column. " + " | ".join(parts)}


def make_checks() -> list:
    return [EmailOwnerOnly(), PhoneFuzzyRechecked(), PhoneAgentNotUsable(), CallReadyPhoneNanp(),
            ScAssessedNotMarket(), HouseNumberGlued(), LayerMapSemantics(), FillOnCallList()]
