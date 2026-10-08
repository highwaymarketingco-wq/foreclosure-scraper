"""Does a county property-tax debt on a row belong to THAT row's parcel? Pure, no I/O.

THE FINDING (2026-10-08). A verification pass against the county tax sites found that 1,209 of
New Hanover's 1,286 "owes 2+ years and $500+" flags on the published board carried ANOTHER
parcel's debt: one roll entry (one debt block) sat on about 1,198 rows and another on about 936.
Lincoln (89 flagged) and Catawba (59) flags came from other counties' PTS Cloud bills. Measured on
the 10/7 board (350,013 rows, 116,213 with raw['tax_owed']): the same kind of copy is on Pickens
(one multi-year block on 1,750 rows), Spartanburg (blocks on 1,692, 1,192 and 1,057 rows), Buncombe
(811 and 791), Henderson, Hyde and others.

THE CAUSE. scripts/recover_tax_year_from_checkpoint.py (2026-09-09) copied tax blocks and
tax_owed from a checkpoint onto board rows, matching first by source_url: every row of one bulk
document (one CSV, one PDF, one ArcGIS layer) shares that URL, so all of them took ONE donor's
block. 16a55ccb (10/2) fixed the script, not the rows. The copies then survived every run:
merge_prior_board deep-merges the prior row's raw into the fresh row with the PRIOR's leaves
winning, and enrichment_tax_owed read any tax-named block a row carried (Pass B), or an old
tax_owed with no block at all (Pass C), and stamped it as the row's own record. Older dedupe
merges on an address key without the county left PTS Cloud bills of Pitt, Guilford, Madison or
Hyde on Lincoln and Catawba rows.

THE RULE (bind_block). A county property-tax block belongs to a row only when
  county   the county the block names (`county`, PTS Cloud's `tenant`) is the row's county;
  parcel   a parcel id the block names (BLOCK_PARCEL_FIELDS) is one of the row's own ids: its
           parcel_id, the short id validation nulled, the short id it was aliased from, the short
           id an alias source keeps in its own block, or the PIN parcel_alias maps the block's short
           id to. A placeholder (fewer than 4 digits, one repeated character) is no key at all.
           Ids of two numbering systems (a 5-digit PTS account and a 10-digit PIN: different length)
           are not compared;
  else     (no comparable key) the block's own situs is the row's address
           (verification.core.address_relation 'match'), or the block came from the row's own
           source or a source merged into it (raw['also_seen_in']) and no address contradicts it;
  shared   a block that names one bill (is_specific: a parcel id, an account, an invoice or list
           item) found IDENTICAL on rows of two or more different properties in one pass binds
           only where its parcel id equals the row's own: one roll entry is one parcel's debt.
Anything else is ANOTHER property's record: scrub_unbound_tax() removes the block and what was
derived from it: tax_aging_surfaced, tax_aging_high, tax_big_old, tax_not_yet_late, and, when
raw['tax_owed'] goes, a scraper's two_year_delinquent and an amount_owed that is the tax balance.
raw['tax_owed'] goes when no block left on the row states its balance and that balance is the
removed block's amount, or the amount of a block copied onto 2+ properties of the county, or is
itself on MASS_COPY_PROPERTIES properties (on 2+ when the row is not a county tax roll's own).
The scorer, lead signals and fullmer re-derive the rest from what is left on every run.

MEASURED on the 10/7 board (read-only replay, counts only): 20,185 rows touched, 20,362 blocks
removed (other parcel 12,625, another county 3,127, no evidence 3,225, shared copy 1,000, other
address 385), 14,067 tax_owed balances removed. Of the "2+ years and $500+" flags, New Hanover
loses 1,202 of 1,209 (7 keep one from a record that binds), Lincoln 89 of 89, Catawba 58 of 59.

Not county property tax (left alone): state tax liens, LiensNC lien-agent filings, eCourts
judgments, UST registries (enrichment_tax_owed._NOT_PROPERTY_TAX_MARKS): those are a person's or a
filing's, not a parcel roll's.
"""
from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from typing import Any, Iterable, Optional

from . import parcel_alias
from .models import _normalize_parcel
from .verification.core import address_key, address_relation

#: block name -> the fields that name the parcel (or roll account) its bill is for, checked
#: against each scraper's own assignment of parcel_id. qpaybill_roll's identification_no is an
#: account, not a parcel, when the block says is_account_id_not_parcel.
BLOCK_PARCEL_FIELDS: dict[str, tuple[str, ...]] = {
    "nc_county_csv_delinquent_tax": ("county_id",),
    "nc_county_pdf_delinquent_tax": ("county_id",),
    "nc_ptscloud_delinquent_tax": ("parcel_raw", "parcel"),
    "albemarle_observer_tax_list": ("parcel",),
    "rutherford_tax": ("parcel",),
    "rutherford_wildfire": ("parcel",),
    "charleston_delinquent_tax": ("pin",),
    "multi_year_delinquent_tax": ("parcel_key",),
    "greenville_delinquent_tax": ("map_number",),
    "nc_its_public_tax": ("parcel",),
    "buncombe_delinquent_tax": ("pin",),
    "buncombe_tax": ("pin",),
    "billtrax_dorchester_delinquent_tax": ("account_number",),
    "horry_delinquent_xlsx": ("pin",),
    "horry_flc": ("pin", "PIN_1"),
    "oconee_flc_assignment": ("tms",),
    "oconee_forfeited_land": ("tms",),
    "spartanburg_delinquent_tax": ("tms",),
    "spartanburg_flc": ("tms",),
    "florence_delinquent_tax": ("tms",),
    "transylvania_tax": ("parcel",),
    "qpaybill_roll": ("parcel_from_map_number", "identification_no"),
    "pickens_tax_sale": ("parcel",),
    "catalis_roll": ("parcel_number",),
    "tax_sale_overage": ("map_number",),
    # blocks with no tax word in their name that carry a county tax balance
    "greenville_distress": ("parcel_id", "pin_published"),
    "arcgis_distress": ("PIN", "TAXPIN", "PARCELNUMB", "PARCELID", "PARCEL_ID", "MAPNUMBER", "MAP_NUMBER"),
}
#: blocks that carry a county tax balance under a name with no tax word; arcgis_distress only for a
#: tax layer (greenville_unpaid_tax_parcels: the layer's TOTTAX is the parcel's unpaid bill)
CONTAINER_BLOCKS = frozenset({"greenville_distress", "arcgis_distress"})
#: fields that make a block one bill's record (an id, an invoice, an item on a list): only such a
#: block is too specific to sit, identical, on two different properties (the shared test)
SPECIFIC_FIELDS = ("item_number", "item_no", "invoice_number", "account_number", "bill_number",
                   "bill_numbers", "notice_numbers", "ACCTNO", "tax_account_number", "identification_no")
#: keys a block lists unpaid years or bills under (enrichment_tax_owed reads them for the year count)
YEAR_LIST_KEYS = ("all_unpaid_years", "years_unpaid", "years", "bill_years", "by_year", "bills",
                  "per_year", "tax_years", "years_detail", "amount_by_year")
#: the alias sources' own long id (parcel_alias keeps the short one): a row published with parcel
#: None still carries its PIN here
_ALIAS_LONG_IDS = {"counties_nc.lincoln_vacant": ("lincoln_vacant", "PIN")}
#: fields a block names its county in (PTS Cloud calls the county its tenant)
BLOCK_COUNTY_FIELDS = ("county", "tenant")
#: fields a block states the bill's property address in
BLOCK_ADDRESS_FIELDS = ("situs", "situs_text", "property_address", "site_address", "property_location")
#: county property-tax blocks whose name has no tax word (enrichment_tax_owed._SOURCES reads them)
_EXTRA_TAX_BLOCKS = frozenset({"rutherford_wildfire", "georgetown_civicengage", "horry_delinquent_xlsx",
                               "oconee_forfeited_land"})
_TAXISH = ("tax", "flc", "forfeited", "delinquent", "lien")
#: this pipeline's own outputs, never a source's record
DERIVED_TAX_KEYS = frozenset({"tax_owed", "tax_aging_surfaced", "two_year_delinquent", "tax_aging_high",
                              "tax_big_old", "tax_not_yet_late"})
#: not a county property-tax roll: a person's lien or a filing (enrichment_tax_owed keeps the same list)
NON_PROPERTY_TAX_MARKS = ("sc_dew_lien_registry", "sc_state_tax_lien", "ust_registry", "ust_incidents",
                          "liensnc", "ecourts", "lien_registry")
#: block name -> source slug tails that write it, where the names differ
_BLOCK_SOURCE_TAILS: dict[str, tuple[str, ...]] = {
    "qpaybill_roll": ("qpaybill_delinquent_roll",),
    "billtrax_dorchester_delinquent_tax": ("dorchester_billtrax_delinquent_tax",),
    "catalis_roll": ("sc_catalis_delinquent_roll",),
    "transylvania_tax": ("transylvania_delinquent_tax",),
    "albemarle_observer_tax_list": ("albemarle_observer_tax_lists",),
}
#: amount keys a block states its debt under (enrichment_tax_owed._SOURCES / _GENERIC_KEYS)
MONEY_KEYS = ("principal_tax_due", "tax_due", "taxes_owed", "amount_owed", "total_due", "balance",
              "lien_amount", "fll_bid", "flc_bid", "opening_bid", "balance_owed", "flc_bid_amount")

#: verdicts under which a block stays on the row
BOUND = frozenset({"own_parcel", "own_address", "own_source"})

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def norm_id(v: Any) -> str:
    """A parcel id with every non-alphanumeric character removed, upper case ("" for None)."""
    if v is None or isinstance(v, (bool, dict, list)):
        return ""
    return _NON_ALNUM.sub("", str(v)).upper()


def usable_id(k: str) -> bool:
    """A normalized id that can name one parcel: at least 4 digits and not one repeated character.
    "0", "0000000000", "ID", "ESCROW", "TRUE" are placeholders or parse debris, never a key."""
    return sum(c.isdigit() for c in k) >= 4 and len(set(k)) > 1


def canon_id(v: Any) -> str:
    """norm_id() with the zero pad dedupe keys a parcel without (models._normalize_parcel: a
    10-digit PIN padded to 12 or 15 digits, a legacy '.000' suffix)."""
    n = norm_id(v)
    return (_normalize_parcel(n).upper() or n) if n else ""


def _digits(k: str) -> str:
    return re.sub(r"\D", "", k)


def _letters(k: str) -> str:
    return re.sub(r"[^A-Z]", "", k.upper())


def same_id(a: str, b: str) -> bool:
    """Two canonical ids name the same parcel: equal; equal digits (6 or more) when the letters do
    not disagree ("R0650..." against "0650...", but never account "...054A" against "...054B");
    or equal once leading zeros go ("00412345" and "412345", digits only)."""
    if a == b:
        return True
    da, db = _digits(a), _digits(b)
    la, lb = _letters(a), _letters(b)
    if len(da) >= 6 and da == db and not (la and lb and la != lb):
        return True
    za, zb = da.lstrip("0"), db.lstrip("0")
    return len(za) >= 4 and za == zb and a.isdigit() and b.isdigit()


def comparable(a: str, b: str) -> bool:
    """Two ids of one numbering system (same length, or the same number of digits, 6 or more): if
    not the same id, they are two parcels. Otherwise they are two systems (a 5-digit PTS account
    against a 10-digit PIN, a Spartanburg 10-digit map number against its 12-digit PIN) and are
    not compared."""
    return len(a) == len(b) or (len(_digits(a)) == len(_digits(b)) >= 6)


def county_key(v: Any) -> str:
    return re.sub(r"[^a-z]", "", str(v or "").lower().replace(" county", ""))


def same_county(a: Any, b: Any) -> bool:
    """One county written two ways ('Rutherford' / 'Rutherfordton', dedupe._same_county)."""
    ka, kb = county_key(a), county_key(b)
    return bool(ka and kb) and (ka == kb or ka.startswith(kb) or kb.startswith(ka))


def _get(row: Any, name: str):
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _raw(row: Any) -> dict:
    raw = _get(row, "raw")
    return raw if isinstance(raw, dict) else {}


def is_property_tax_block(name: str, blk: Any) -> bool:
    """A county property-tax DEBT record on the row: a tax-named source block (a roll entry, a
    delinquent list line, an FLC bid) that states an amount, a parcel id or the unpaid years, or a
    CONTAINER_BLOCKS block holding a tax layer's balance. A tax-named block with none of these
    (pickens_delinquent's cycle flags) attaches no debt and is left alone, as are other liens
    (NON_PROPERTY_TAX_MARKS)."""
    if not isinstance(blk, dict) or name in DERIVED_TAX_KEYS:
        return False
    if any(m in name for m in NON_PROPERTY_TAX_MARKS):
        return False
    if name in CONTAINER_BLOCKS:
        if name == "arcgis_distress" and not any(t in str(blk.get("layer") or "").lower()
                                                 for t in ("tax", "unpaid", "delinquent")):
            return False
        return bool(block_money(blk))
    if not (name in BLOCK_PARCEL_FIELDS or name in _EXTRA_TAX_BLOCKS or name.endswith("_roll")
            or any(t in name for t in _TAXISH)):
        return False
    return bool(block_money(blk) or block_ids(name, blk)
                or any(blk.get(k) for k in YEAR_LIST_KEYS if isinstance(blk.get(k), (list, dict))))


def is_specific(name: str, blk: dict) -> bool:
    """The block names one bill (a parcel id, an account, an invoice or list item number), so the
    same block on two different properties is a copy, not a coincidence."""
    return bool(block_ids(name, blk)) or any(blk.get(k) not in (None, "", [], {}) for k in SPECIFIC_FIELDS)


def block_ids(name: str, blk: dict) -> list[str]:
    """The usable parcel ids the block names (raw strings), most specific first."""
    out = []
    for f in BLOCK_PARCEL_FIELDS.get(name, ()):
        if name == "qpaybill_roll" and f == "identification_no" and blk.get("is_account_id_not_parcel"):
            continue
        v = blk.get(f)
        if usable_id(norm_id(v)):
            out.append(str(v).strip())
    return out


def block_county(blk: dict) -> Optional[str]:
    for f in BLOCK_COUNTY_FIELDS:
        v = blk.get(f)
        if isinstance(v, str) and county_key(v):
            return v
    return None


def block_address(blk: dict) -> Optional[str]:
    for f in BLOCK_ADDRESS_FIELDS:
        v = blk.get(f)
        if isinstance(v, str) and v.strip():
            return v
    if blk.get("STRNUM") and blk.get("LOCATE"):      # Greenville's tax layer splits the situs
        parts = [blk.get(k) for k in ("STRNUM", "STRPRE", "LOCATE", "STRTYP", "STRSUF")]
        return " ".join(str(p).strip() for p in parts if p not in (None, ""))
    return None


def block_money(blk: dict) -> set[float]:
    out = set()
    for k in MONEY_KEYS:
        v = blk.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out.add(round(float(v), 2))
    return out


def block_from_source(name: str, source: Any) -> bool:
    """The block is the one `source` writes (its slug's last part names it, or a part of the slug
    is the block's name: 'arcgis_distress' of counties_generic.arcgis_distress.<layer>)."""
    parts = str(source or "").split(".")
    tail = parts[-1]
    if not tail:
        return False
    return (name == tail or name in tail or tail in name or name in parts
            or tail in _BLOCK_SOURCE_TAILS.get(name, ()))


def row_sources(row: Any) -> list[str]:
    """The row's own source and every source merged into it (raw['also_seen_in'])."""
    out = [str(_get(row, "source") or "")]
    seen = _raw(row).get("also_seen_in")
    if isinstance(seen, list):
        out += [str(e.get("source") or "") for e in seen if isinstance(e, dict)]
    return [s for s in out if s]


def row_ids(row: Any) -> list[str]:
    """Every id the row is its own parcel under (raw strings, usable only)."""
    raw = _raw(row)
    cands = [_get(row, "parcel_id")]
    nulled = raw.get("parcel_id_nulled")
    if isinstance(nulled, dict):
        cands.append(nulled.get("value"))
    alias = raw.get("parcel_id_alias")
    if isinstance(alias, dict):
        cands += [alias.get("short"), alias.get("long")]
    cands.append(parcel_alias.short_id_of(row))
    spec = _ALIAS_LONG_IDS.get(str(_get(row, "source") or ""))
    if spec and isinstance(raw.get(spec[0]), dict):
        cands.append(raw[spec[0]].get(spec[1]))
    out = []
    for c in cands:
        if c is not None and usable_id(norm_id(c)) and str(c).strip() not in out:
            out.append(str(c).strip())
    return out


def id_relation(bids: list[str], rids: list[str], row: Any = None,
                alias_table: Optional[dict] = None) -> str:
    """'same' | 'different' | 'not_comparable' | 'no_key' between the block's ids and the row's."""
    if not bids or not rids:
        return "no_key"
    # each id both as written (norm_id) and as dedupe keys it (canon_id: zero pads dropped), so a
    # padded and a bare PIN are one parcel and two 15-character roll ids stay comparable
    nb = [(norm_id(b), canon_id(b)) for b in bids]
    nr = [(norm_id(r), canon_id(r)) for r in rids]
    if any(same_id(b[k], r[k]) for b in nb for r in nr for k in (0, 1)):
        return "same"
    if alias_table and row is not None:
        for b in bids:
            pin = parcel_alias.lookup(alias_table, _get(row, "state"), _get(row, "county"), b)
            if pin and any(same_id(canon_id(pin), r[1]) for r in nr):
                return "same"
    if any(comparable(b[k], r[k]) for b in nb for r in nr for k in (0, 1)):
        return "different"
    return "not_comparable"


def bind_block(row: Any, name: str, blk: dict, alias_table: Optional[dict] = None) -> str:
    """Whether the tax block `name` on `row` is that row's own record (one of BOUND) or another
    property's ('foreign_county', 'other_parcel', 'other_address', 'no_evidence'). Without the
    cross-row 'shared' test: scrub_unbound_tax() adds it."""
    bc = block_county(blk)
    if bc and _get(row, "county") and not same_county(bc, _get(row, "county")):
        return "foreign_county"
    rel = id_relation(block_ids(name, blk), row_ids(row), row, alias_table)
    if rel == "same":
        return "own_parcel"
    if rel == "different":
        return "other_parcel"
    addr = block_address(blk)
    ar = address_relation(_get(row, "street_address"), addr) if addr else "unknown"
    if ar == "match":
        return "own_address"
    if ar == "conflict":
        return "other_address"
    if any(block_from_source(name, s) for s in row_sources(row)):
        return "own_source"
    return "no_evidence"


def fingerprint(name: str, blk: dict) -> str:
    """One string per distinct block content (a copy of a block has the copy's fingerprint)."""
    try:
        return name + "|" + json.dumps(blk, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return name + "|" + repr(sorted(blk.items(), key=lambda kv: str(kv[0])))


def property_keys(row: Any, idx: int, alias_table: Optional[dict] = None) -> frozenset:
    """Which PROPERTY a row is, for the shared test: one key per parcel id the row is its own
    parcel under (and the PIN parcel_alias maps a short one to) and one for its house-numbered
    address; the row itself when it has neither. Rows sharing any key are one property."""
    st, cty = str(_get(row, "state") or ""), county_key(_get(row, "county"))
    keys = set()
    for r in row_ids(row):
        keys.add(("p", st, cty, canon_id(r)))
        pin = parcel_alias.lookup(alias_table, _get(row, "state"), _get(row, "county"), r) if alias_table else None
        if pin:
            keys.add(("p", st, cty, canon_id(pin)))
    num, name, _ = address_key(_get(row, "street_address"))
    if num and name:
        keys.add(("a", st, cty, num, tuple(sorted(name))))
    return frozenset(keys or {("r", idx)})


def count_properties(keysets: list) -> int:
    """How many different properties a list of property_keys() sets covers (union-find: two sets
    that share a key are one property)."""
    parent: dict = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for ks in keysets:
        ks = list(ks)
        for k in ks:
            parent.setdefault(k, k)
        for k in ks[1:]:
            ra, rb = find(ks[0]), find(k)
            if ra != rb:
                parent[rb] = ra
    return len({find(next(iter(ks))) for ks in keysets if ks})


def _owed_fingerprint(row: Any) -> Optional[tuple]:
    to = _raw(row).get("tax_owed")
    if not isinstance(to, dict) or not isinstance(to.get("balance"), (int, float)):
        return None
    return (str(_get(row, "state") or ""), county_key(_get(row, "county")), to.get("kind"),
            round(float(to["balance"]), 2), str(to.get("year")))


def _owed_backed(raw: dict) -> bool:
    """A block on the row (other than this pipeline's own outputs) states tax_owed's balance."""
    to = raw.get("tax_owed")
    if not isinstance(to, dict) or not isinstance(to.get("balance"), (int, float)):
        return False
    bal = round(float(to["balance"]), 2)
    return any(isinstance(b, dict) and n not in DERIVED_TAX_KEYS and n != "amount_owed"
               and bal in block_money(b) for n, b in raw.items())


#: tax_owed kinds that are a county property-tax roll's (enrichment_tax_owed._SOURCES)
_PROPERTY_OWED_KINDS = frozenset({"delinquent_tax", "flc_opening_bid", None})


def _non_property_owed(row: Any) -> bool:
    """raw['tax_owed'] is a state lien, a lien-agent filing or a judgment, not a county roll's."""
    to = _raw(row).get("tax_owed")
    if not isinstance(to, dict) or to.get("kind") not in _PROPERTY_OWED_KINDS:
        return True
    srcs = (str(_get(row, "source") or ""), str(to.get("source") or ""))
    return any(m in s for s in srcs for m in NON_PROPERTY_TAX_MARKS)


#: what the pipeline derives from a row's county tax record (enrich_tax_aging, the scrapers'
#: two-year flag, the amount_owed promotion); each is rebuilt every run from what the row still has
DERIVED_AGING_KEYS = ("tax_aging_surfaced", "tax_aging_high", "tax_big_old", "tax_not_yet_late")


def drop_derived_tax(raw: dict, drop_owed: bool, stats: Optional[dict] = None) -> int:
    """Remove from `raw` what was derived from a tax record that is gone: the aging fields always;
    with `drop_owed` also a scraper's two_year_delinquent (not the 'default' placeholder) and an
    amount_owed that IS the tax balance. Returns how many keys went."""
    n = 0
    for k in DERIVED_AGING_KEYS:
        if raw.pop(k, None) is not None:
            n += 1
    if drop_owed:
        tyd = raw.get("two_year_delinquent")
        if isinstance(tyd, dict) and tyd.get("source") != "default":
            raw.pop("two_year_delinquent", None)
            n += 1
        ao = raw.get("amount_owed")
        if isinstance(ao, dict) and ao.get("source") == "tax_owed":
            raw.pop("amount_owed", None)
            n += 1
    if stats is not None:
        stats["derived_removed"] = stats.get("derived_removed", 0) + n
    return n


def scrub_unbound_tax(listings: Iterable[Any], alias_table: Optional[dict] = None,
                      record: Optional[list] = None) -> dict:
    """Remove from every row the county property-tax blocks that are another property's record
    (bind_block, plus the shared-block test across `listings`), and what was derived from them.
    In place; idempotent (a second pass changes nothing); never raises on an odd row.

    `listings` are Listings or board row dicts (anything with state, county, parcel_id,
    street_address, source and a raw dict). Returns counts (no names, no addresses):
      rows_scrubbed, blocks_removed, by_reason, by_county, tax_owed_removed, derived_removed.
    `record`, when given, receives one (row index, block name or 'tax_owed', reason) per removal."""
    rows = list(listings)
    if alias_table is None:
        try:
            alias_table = parcel_alias.build(rows)
        except Exception:  # noqa: BLE001 - no alias table is the strict side
            alias_table = {}
    stats: dict = {"rows_scrubbed": 0, "blocks_removed": 0, "tax_owed_removed": 0, "derived_removed": 0,
                   "by_reason": defaultdict(int), "by_county": defaultdict(int)}
    scrubbed: set[int] = set()
    # A removal can leave another row's balance unbacked and shared, so repeat to a fixed point
    # (measured on the 10/7 board: the second round removes 1 balance, the third nothing).
    for _round in range(4):
        if not _scrub_once(rows, alias_table, stats, scrubbed, record):
            break
    stats["rows_scrubbed"] = len(scrubbed)
    stats["by_reason"] = dict(stats["by_reason"])
    stats["by_county"] = dict(sorted(stats["by_county"].items(), key=lambda kv: -kv[1]))
    return stats


#: An unbacked balance (no block on the row states it) shared by this many different properties is
#: a mass copy, not lots with equal assessments (1,218 Lincoln properties with one balance and year
#: on the 10/7 board). Below it, equal bills stay on a county roll's own rows (a few lots of one
#: subdivision owe the same: 18 Pickens roll rows share one 2024 bill amount) and go from any other
#: source's row (USDA listings, court index rows, contamination sites: one Anderson balance on 199).
MASS_COPY_PROPERTIES = 20


def tax_roll_source(source: Any) -> bool:
    """The row is a county property-tax roll's own lead (its slug names a tax list)."""
    s = str(source or "")
    return not any(m in s for m in NON_PROPERTY_TAX_MARKS) and (
        any(t in s for t in _TAXISH) or s.endswith("_roll"))


def _scrub_once(rows: list, alias_table: dict, stats: dict, scrubbed: set, record: Optional[list]) -> int:
    """One round of scrub_unbound_tax(); returns how many things it removed."""
    changed = 0

    # pass 1: every property-tax block's verdict and fingerprint; who carries each fingerprint
    verdicts: list[list[tuple[str, str, Optional[str]]]] = []
    holders: dict[str, list] = defaultdict(list)
    owed_holders: dict[tuple, list] = defaultdict(list)
    for i, row in enumerate(rows):
        raw = _raw(row)
        keys = property_keys(row, i, alias_table)
        mine = []
        for name, blk in list(raw.items()):
            if not is_property_tax_block(name, blk):
                continue
            try:
                v = bind_block(row, name, blk, alias_table)
            except Exception:  # noqa: BLE001 - an unreadable block is not evidence either way
                continue
            fp = fingerprint(name, blk) if is_specific(name, blk) else None
            if fp is not None:
                holders[fp].append(keys)
            mine.append((name, v, fp))
        verdicts.append(mine)
        ofp = _owed_fingerprint(row)
        if ofp is not None and not _owed_backed(raw):
            owed_holders[ofp].append(keys)
    shared_fps = {fp for fp, ks in holders.items() if len(ks) > 1 and count_properties(ks) > 1}
    shared_owed, mass_owed = set(), set()
    for fp, ks in owed_holders.items():
        if len(ks) > 1:
            n = count_properties(ks)
            if n > 1:
                shared_owed.add(fp)
            if n >= MASS_COPY_PROPERTIES:
                mass_owed.add(fp)

    # pass 2: remove the blocks that do not bind; remember their amounts (per row and per county)
    removed_money_row: dict[int, set] = defaultdict(set)
    removed_money_county: dict[tuple, set] = defaultdict(set)
    removed_n: dict[int, int] = defaultdict(int)
    for i, row in enumerate(rows):
        raw = _raw(row)
        if not raw:
            continue
        for name, v, fp in verdicts[i]:
            reason = None
            if v not in BOUND:
                reason = v
            elif fp in shared_fps and v != "own_parcel":
                reason = "shared_block"
            if reason is None:
                continue
            blk = raw.pop(name, None)
            if isinstance(blk, dict):
                money = block_money(blk)
                removed_money_row[i] |= money
                if fp in shared_fps:   # a block copied onto 2+ properties: its amount is a copy's
                    removed_money_county[(str(_get(row, "state") or ""), county_key(_get(row, "county")))] |= money
            removed_n[i] += 1
            stats["by_reason"][reason] += 1
            if record is not None:
                record.append((i, name, reason))

    # pass 3: a balance no block on the row states any more goes too when it is the amount of a block
    # removed from this row, or of a block copied onto 2+ properties of the county, or is itself
    # shared like a copy (MASS_COPY_PROPERTIES properties, or 2+ when the row is not a tax roll's)
    for i, row in enumerate(rows):
        raw = _raw(row)
        drop_owed, why = False, None
        to = raw.get("tax_owed")
        if isinstance(to, dict) and not _non_property_owed(row) and not _owed_backed(raw):
            bal = to.get("balance")
            bal = round(float(bal), 2) if isinstance(bal, (int, float)) and not isinstance(bal, bool) else None
            ck = (str(_get(row, "state") or ""), county_key(_get(row, "county")))
            if bal is not None and bal in removed_money_row.get(i, ()):
                drop_owed, why = True, "block_removed"
            elif bal is not None and bal in removed_money_county.get(ck, ()):
                drop_owed, why = True, "copied_balance"
            elif bal is not None and (_owed_fingerprint(row) in mass_owed or (
                    _owed_fingerprint(row) in shared_owed and not tax_roll_source(_get(row, "source")))):
                drop_owed, why = True, "shared_balance"
        if drop_owed:
            raw.pop("tax_owed", None)
            stats["tax_owed_removed"] += 1
            stats["by_reason"][f"tax_owed_{why}"] += 1
            if record is not None:
                record.append((i, "tax_owed", why))
        removed = removed_n.get(i, 0)
        if removed or drop_owed:
            drop_derived_tax(raw, drop_owed, stats)
            stats["blocks_removed"] += removed
            changed += removed + int(drop_owed)
            if i not in scrubbed:
                scrubbed.add(i)
                stats["by_county"][f"{_get(row, 'state') or ''}:{county_key(_get(row, 'county'))}"] += 1
    return changed


def keep_fresh_tax_blocks(fresh: Any, merged: Any) -> int:
    """After `merged = fresh.merge(prior)` (board_persist): Listing.merge() lets the PRIOR row's
    raw leaves win, so a prior copy of another parcel's tax block overwrote the fresh scrape's own
    block on every run. Put back each property-tax block of `fresh` that is fresh's own record
    (bind_block in BOUND) wherever the merged block names a different parcel or county. Returns
    how many blocks were put back. In place on `merged`."""
    fr, mr = _raw(fresh), _raw(merged)
    if not fr or not mr:
        return 0
    n = 0
    for name, fblk in fr.items():
        if not is_property_tax_block(name, fblk):
            continue
        mblk = mr.get(name)
        if not isinstance(mblk, dict) or mblk == fblk:
            continue
        if bind_block(fresh, name, fblk) not in BOUND:
            continue
        f_ids = {norm_id(x) for x in block_ids(name, fblk)}
        m_ids = {norm_id(x) for x in block_ids(name, mblk)}
        moved = (f_ids != m_ids and bool(m_ids)) or (
            block_county(fblk) and block_county(mblk) and not same_county(block_county(fblk), block_county(mblk)))
        if moved or bind_block(merged, name, mblk) not in BOUND:
            mr[name] = copy.deepcopy(fblk)
            n += 1
    return n


# ---------------------------------------------------------------------------------------------
# The county's own site is the authority (2026-10-08). A tax_lien verifier checks the bill on the
# county's site for the row's own parcel or address; a CONFIRMED answer still inside its TTL sets
# the row's balance and year count from what the site showed, whatever block the row carries
# (a scrubbed copy never comes back: only the verifier's evidence is read). Stale, refuted,
# unconfirmed and expired answers restore nothing.
# ---------------------------------------------------------------------------------------------

#: raw['tax_owed'].source / .basis of a balance read from a confirmed county-site verification
VERIFIED_SOURCE = "county_site_verified"


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _year_keys(d: Any) -> list[int]:
    """The levy years of a {year: amount} dict whose amount is positive, oldest first."""
    if not isinstance(d, dict):
        return []
    out = set()
    for k, v in d.items():
        try:
            y = int(str(k)[:4])
        except ValueError:
            continue
        if 1990 <= y <= 2100 and (_num(v) or 0) > 0:
            out.add(y)
    return sorted(out)


def confirmed_tax_record(raw: Any, now=None) -> Optional[dict]:
    """The row's tax_lien verification record when its verdict is 'confirmed' and it has not
    expired (verification.apply stamps expires_at = checked_at + the verifier's TTL)."""
    rec = decisive_tax_record(raw, now)
    return rec if rec is not None and rec.get("verdict") == "confirmed" else None


def decisive_tax_record(raw: Any, now=None) -> Optional[dict]:
    """The row's tax_lien record when its verdict is confirmed, stale or refuted and it has not
    expired; None otherwise (unconfirmed, wall, expired, no record)."""
    from .verification.core import is_expired, records_of
    for rec in records_of(raw):
        if rec.get("signal") == "tax_lien" and rec.get("verdict") in ("confirmed", "stale", "refuted") \
                and not is_expired(rec, now):
            return rec
    return None


def _money_text(v: float) -> str:
    return f"${v:,.2f}"


def county_check_note(rec: dict) -> dict:
    """raw['tax_county_check']: the verdict, when it was checked, and one short line of what the
    county's site showed (amounts and years only)."""
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    verdict = rec.get("verdict")
    total = _num(ev.get("total_delinquent")) or 0.0
    pending = {y: _num(ev["not_yet_delinquent_due"].get(str(y))) for y in _year_keys(ev.get("not_yet_delinquent_due"))}
    if verdict == "confirmed":
        n = ev.get("years_delinquent")
        detail = f"{_money_text(total)} past due" + (f" over {n} year{'s' if n != 1 else ''}" if isinstance(n, int) else "")
    elif verdict == "stale":
        detail = "the delinquent bill was paid; nothing past due now" if total <= 0 else f"{_money_text(total)} past due"
    else:
        detail = "no delinquent bill on the county site" if total <= 0 else f"{_money_text(total)} past due"
    if pending:
        detail += "; " + ", ".join(f"{y} bill {_money_text(a)} not late yet" for y, a in pending.items() if a)
    return {"verdict": verdict, "checked_at": rec.get("checked_at"), "detail": detail}


def county_check_balance(row: Any, rec: dict) -> Optional[dict]:
    """For a stale or refuted check of the row's own parcel: the past-due balance the county's site
    still shows (raw['tax_owed'] from the check), or {} when it shows none (the balance goes)."""
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    total = _num(ev.get("total_delinquent")) or 0.0
    if total <= 0:
        return {}
    return verified_tax_owed(row, rec)


def verified_checks_row(row: Any, ev: dict) -> bool:
    """The parcel the verifier checked is the row's own: the verifier says its number is one of the
    row's (tax_parcel_row_own), the checked id is one of the row's ids, or the checked bill carries
    the row's address (address_relation 'match': a PTS Cloud account found by the row's address
    has tax_parcel_row_own False and still is the row's). A check on another county's bill never
    counts."""
    if ev.get("claim_county_differs"):
        return False
    if ev.get("tax_parcel_row_own") is True:
        return True
    checked = [ev.get("pin"), ev.get("tax_parcel")]
    checked.append(ev.get("board_parcel") if ev.get("decided_on") == "board_parcel" else ev.get("claim_ident"))
    ids = [str(c).strip() for c in checked if c is not None and usable_id(norm_id(c))]
    if ids and id_relation(ids, row_ids(row)) == "same":
        return True
    return ev.get("address_relation") == "match"


def verified_tax_owed(row: Any, rec: dict) -> Optional[dict]:
    """raw['tax_owed'] from a confirmed record's evidence (total_delinquent and the late years:
    years_delinquent or delinquent_by_year), or None when the evidence does not state both or
    the verifier did not check the row's own parcel."""
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    total = _num(ev.get("total_delinquent"))
    late = _year_keys(ev.get("delinquent_by_year"))
    n = ev.get("years_delinquent")
    n = int(n) if isinstance(n, int) and not isinstance(n, bool) and n > 0 else len(late)
    if not total or total <= 0 or not n or not verified_checks_row(row, ev):
        return None
    pending = _year_keys(ev.get("not_yet_delinquent_due"))
    out = {"balance": round(total, 2), "kind": "delinquent_tax", "source": VERIFIED_SOURCE,
           "basis": VERIFIED_SOURCE, "year": late[0] if late else None, "years_delinquent": n,
           "delinquent_years": late, "unpaid_bill_years": n + len(pending), "not_yet_late_years": pending,
           "years_basis": "verified", "parcel": _get(row, "parcel_id"),
           "verifier": rec.get("verifier"), "checked_at": rec.get("checked_at")}
    if ev.get("total_delinquent_is_floor"):
        out["balance_is_floor"] = True       # a bill in legal collection shows no amount
    return out


def restore_verified_tax(listings: Iterable[Any], now=None) -> dict:
    """The county's own site decides the row's displayed tax debt, after verification.apply and
    before the scorer. For a tax_lien check of the row's own parcel inside its TTL:
      confirmed         raw['tax_owed'], the aging fields and the amount_owed promotion from the
                        check's balance and late years (verified_tax_owed);
      stale / refuted   the earlier unverified balance and what came of it are removed (the site
                        shows nothing past due), or replaced by a past-due balance the site still
                        shows;
    and raw['tax_county_check'] = {verdict, checked_at, detail} records what the site said. A row
    with no such check is not touched (an expired note is cleared). A row whose tax_owed is
    another lien's (a state lien, a lien-agent filing) is left alone. Idempotent. Returns counts."""
    from .enrichment_amount_owed import _tax_owed_promotion
    from .enrichment_tax_owed import BIG_TAX_BALANCE
    stats = {"confirmed": 0, "restored": 0, "replaced_balance": 0, "added_balance": 0,
             "not_own_parcel_or_no_years": 0, "other_lien_kept": 0,
             "stale_or_refuted": 0, "balance_removed": 0, "balance_from_check": 0, "note_only": 0,
             "notes_cleared": 0}
    for li in listings:
        raw = _raw(li)
        rec = decisive_tax_record(raw, now) if raw else None
        if rec is None:
            if raw.pop("tax_county_check", None) is not None:   # an expired check says nothing now
                stats["notes_cleared"] += 1
            continue
        old = raw.get("tax_owed")
        if isinstance(old, dict) and _non_property_owed(li):
            stats["other_lien_kept"] += 1
            continue
        ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
        if rec.get("verdict") in ("stale", "refuted"):
            # the county's site says the claim is paid (stale) or was never owed (refuted): the row
            # never shows the earlier unverified balance; it shows what the check states
            stats["stale_or_refuted"] += 1
            if not verified_checks_row(li, ev):
                stats["not_own_parcel_or_no_years"] += 1
                continue
            raw["tax_county_check"] = county_check_note(rec)
            new_to = county_check_balance(li, rec)
            if new_to:
                rec_conf = dict(rec, verdict="confirmed")
                _apply_verified(li, raw, new_to, rec_conf, _tax_owed_promotion, BIG_TAX_BALANCE)
                stats["balance_from_check"] += 1
            elif isinstance(old, dict) or any(k in raw for k in DERIVED_AGING_KEYS):
                raw.pop("tax_owed", None)
                drop_derived_tax(raw, drop_owed=True)
                stats["balance_removed"] += isinstance(old, dict)
            else:
                stats["note_only"] += 1
            continue
        stats["confirmed"] += 1
        to = verified_tax_owed(li, rec)
        if to is None:
            stats["not_own_parcel_or_no_years"] += 1
            continue
        stats["restored"] += 1
        if isinstance(old, dict):
            stats["replaced_balance"] += _num(old.get("balance")) != to["balance"]
        else:
            stats["added_balance"] += 1
        raw["tax_county_check"] = county_check_note(rec)
        _apply_verified(li, raw, to, rec, _tax_owed_promotion, BIG_TAX_BALANCE)
    return stats


def _apply_verified(li: Any, raw: dict, to: dict, rec: dict, promote, big: float) -> None:
    """raw['tax_owed'], the aging fields and the amount_owed promotion from a county-site balance."""
    raw["tax_owed"] = to
    n = to["years_delinquent"]
    surf = {"tax_year": to["year"], "years_delinquent": n, "status": "delinquent",
            "source": VERIFIED_SOURCE, "basis": "year_list", "unpaid_bill_years": to["unpaid_bill_years"]}
    if to["not_yet_late_years"]:
        surf["not_yet_late_years"] = to["not_yet_late_years"]
    raw["tax_aging_surfaced"] = surf
    raw["tax_aging_high"] = n >= 2
    raw.pop("tax_not_yet_late", None)
    if n >= 2 and to["balance"] >= big:
        raw["tax_big_old"] = True
    else:
        raw.pop("tax_big_old", None)
    ao = promote(raw, li)
    if ao is not None:
        raw["amount_owed"] = ao
