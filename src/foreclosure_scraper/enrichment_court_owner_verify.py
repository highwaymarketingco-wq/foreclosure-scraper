"""Court-lead owner verification — guards against a geo-snap stapling the WRONG property to a docket.

CourtListener / lis-pendens / bankruptcy leads carry a real docket DEFENDANT, but a low-precision
lat/lng on the docket can make parcel_from_geo snap to a NEIGHBOR's parcel, after which gis_attrs
overwrites owner_name with that stranger's name (e.g. defendant 'Roger Leonard Mason' -> snapped onto
the 'INMAN' parcel on Atlas Court). The result is a real case attached to the wrong house — which then
drives a wrong ARV, a wrong max bid, and outreach to the wrong person.

Fix: compare the GIS-resolved owner against the docket defendant's SURNAME. On a clear mismatch, strip
the mis-attached property (parcel / address / value / specs / gis owner), revert owner_name to the
defendant, and flag the lead so it reads as an unverified name-only court record instead of a vetted
lead. Conservative — only fires when the defendant's surname is absent from the owner string entirely.
Runs PRE-valuation so the stripped lead recomputes to 'insufficient data' rather than a bogus ARV.

STALE-FLAG-ON-MERGE bug (found + fixed 2026-10-03, live-verified on the real board): this function
only ever WRITES raw['owner_mismatch']; nothing ever cleared it. Listing.merge() deep-merges `raw`
(keeps every key either side has) but only overwrites owner_name/defendant/listing_type/source when
the PRIMARY side's own value is falsy (models.py's fill-only rule) — so once a court-sourced listing
this function already flagged and stripped (owner_name reverted to the docket defendant, parcel_id
cleared) later merges with a different, non-court record for the "same" property (matched by address/
situs once parcel_id was cleared, not uncommon — e.g. a Buncombe tax-lien `arcgis_distress` row), the
merged listing keeps the TAX record's own owner_name/defendant/listing_type (none of them falsy, so
none get overwritten) but ALSO keeps the orphaned `raw['owner_mismatch']` key from the old court-side
`raw`. Live-confirmed example: a merged row published as `tax_lien`/`counties_generic.arcgis_distress.
buncombe_unpaid_bills` with owner_name == defendant == "BUCKNER (LE), CHRISTOPHER" still carried
`owner_mismatch = {"defendant_surname": "craft", "snapped_owner": "VALDEZ MELISSA KATRINA;VALDEZ JOE"}`
— a flag naming two people with no relation to the row's current identity, surfaced verbatim as a
MEDIUM red flag by scripts/build_red_flags.py. 58 of 426 live board rows carrying this function's own
flag shape (2 keys, no 'source') are on a row that no longer qualifies as `is_court` — pure orphaned
noise inflating the tracked `owner_mismatch` coverage metric. Fixed: when a listing no longer qualifies
as court-sourced, this function now clears its OWN flag shape (never promote_ptscloud_block.py's, which
always carries a 'source' key and is a separate, still-valid mechanism) instead of silently skipping it.

COURT_SIGNALS AUDIT (2026-10-09), three more rules in the same tail step (it runs in run_enrich_tail
before verification and scoring, and in scripts/reconcile_board.py as a local step):
  * LIEN CLAIMS ARE NOT LIS PENDENS. An NC Judgment Search 'CV - Claim of Lien' / 'CV - Lien' row
    (a contractor's, supplier's or HOA's claim against the owner) is retyped lien_claim, and a 'CV -
    Transcript of Judgment' row a judgment lien (distressed + nc_ecourts.signal judgment_lien, the
    money-judgment convention): on the 2026-10-08 checkpoint 6,502 + 1,435 of the 8,795 NC
    lis_pendens rows from that index were one of these; 763 were real lis pendens. Rows are kept.
  * AN ESTATE NOTICE BINDS TO A PARCEL ONLY BY NAME. A row whose claim is an estate notice
    (raw.probate.decedent) and that names a property keeps it only when the decedent agrees with an
    owner of record by name (surname AND first name, middle initials not in conflict; a roll string
    '<decedent> HEIRS' agrees), or the personal representative does and the property is not the
    representative's own printed address. Otherwise the notice is kept as an unbound county-level
    lead: no parcel, no address, no property values (raw.estate_unbound says why). A notice record
    merged onto another source's property row moves to raw.probate_unbound instead. Measured: 36 of
    111 such rows named someone else (many were the personal representative's own house, the
    address the notice prints for the representative).
  * A BANKRUPTCY FILING BINDS TO A PARCEL ONLY BY NAME. The same agreement between a debtor of the
    case and an owner of record (one not copied from the case name); otherwise the filing is kept
    as a name-only record (no parcel, no address). The CourtListener re-check refuted 8 of 12
    decidable NC links on the sample, every one a same-surname stranger or a middle-name conflict.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|esq|md|deceased|life\s*estate|estate|trustee|et\s*al|aka|"
                     r"individually|trust|llc|inc|corp)\b\.?", re.I)


def _toks(s: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z]{2,}", s or "")]


# ------------------------------------------------------------------------------------------------
# lien claims (court_signals audit 2026-10-09)
# ------------------------------------------------------------------------------------------------

LIEN_CLAIM_CAUSES = frozenset({"CV - Claim of Lien", "CV - Lien"})
JUDGMENT_LIEN_CAUSES = frozenset({"CV - Transcript of Judgment"})


def court_lien_kind(li: Any) -> Optional[str]:
    """'lien_claim' | 'judgment_lien' | None for a row built from an NC Judgment Search hit, by
    the hit's cause (or the signal the scraper stamped)."""
    src = str((li.get("source") if isinstance(li, dict) else getattr(li, "source", "")) or "")
    raw = li.get("raw") if isinstance(li, dict) else getattr(li, "raw", None)
    b = raw.get("nc_ecourts") if isinstance(raw, dict) else None
    if "ecourts" not in src or not isinstance(b, dict):
        return None
    sig = b.get("signal")
    cause = str(b.get("cause") or b.get("cause_of_action") or "").strip()
    if sig == "lien_claim" or cause in LIEN_CLAIM_CAUSES:
        return "lien_claim"
    if sig == "judgment_lien" or cause in JUDGMENT_LIEN_CAUSES:
        return "judgment_lien"
    return None


def retype_court_lien(li: Any) -> Optional[str]:
    """Retype a carried NC Judgment Search row typed lis_pendens whose cause is a claim of lien
    (-> lien_claim) or a transcript of judgment (-> distressed + nc_ecourts.signal judgment_lien).
    Returns the new kind, or None when nothing changed."""
    from .models import ListingType
    lt = getattr(getattr(li, "listing_type", None), "value", None)
    if lt != "lis_pendens":
        return None
    kind = court_lien_kind(li)
    if kind is None:
        return None
    raw = li.raw if isinstance(li.raw, dict) else {}
    raw["nc_ecourts"]["signal"] = kind
    raw["retyped"] = {"from": "lis_pendens", "to": kind, "rule": "court_signals_2026_10_09"}
    li.listing_type = ListingType.LIEN_CLAIM if kind == "lien_claim" else ListingType.DISTRESSED
    li.raw = raw
    return kind


# ------------------------------------------------------------------------------------------------
# name agreement between a court/notice party and an owner of record (court_signals 2026-10-09)
# ------------------------------------------------------------------------------------------------

_ROLE = re.compile(r"\b(HEIRS?|ESTATE\s+OF|ESTATE|EST|DECEASED|DECD|ET\s*UX|ET\s*VIR|ETUX|ETVIR|"
                   r"ET\s*AL|ETAL|LIFE\s*ESTATE|LE|TRUSTEES?|TR|JTWROS|WROS|MRS|MR|DR)\b\.?", re.I)
_GEN = frozenset({"JR", "SR", "II", "III", "IV", "V"})
_SPLIT = re.compile(r";|<br\s*/?>|\s&\s|\s\+\s|\sAND\s|\sand\s", re.I)


def segments(name: Any) -> list[str]:
    """One person per segment, role words removed ('SMITH JOHN HEIRS; SMITH MARY' -> two)."""
    out = []
    for seg in _SPLIT.split(str(name or "")):
        seg = re.sub(r"\(\s*\w*\s*\)", " ", seg)          # '(LE)', '(EST)'
        seg = _ROLE.sub(" ", seg).strip(" ,.")
        if re.search(r"[A-Za-z]{2,}", seg):
            out.append(seg)
    return out


def _readings(seg: str) -> list[tuple[str, str, str]]:
    """(LAST, FIRST, MIDDLE INITIAL) readings of one person's name: a comma means LAST, FIRST;
    Title Case is FIRST ... LAST; ALL CAPS with no comma is read both ways (county rolls are
    surname first, notices often are not)."""
    if "," in seg:
        last_part, _, rest = seg.partition(",")
        last = [t for t in re.findall(r"[A-Za-z]+", last_part.upper()) if t not in _GEN]
        given = [t for t in re.findall(r"[A-Za-z]+", rest.upper()) if t not in _GEN]
        if not last or not given:
            return []
        return [(last[-1], given[0], given[1][0] if len(given) > 1 else "")]
    toks = [t for t in re.findall(r"[A-Za-z]+", seg.upper()) if t not in _GEN]
    if len(toks) < 2:
        return []
    first_last = (toks[-1], toks[0], toks[1][0] if len(toks) > 2 else "")
    if re.search(r"[a-z]", seg):
        return [first_last]
    return [(toks[0], toks[1], toks[2][0] if len(toks) > 2 else ""), first_last]


def names_agree(a: Any, b: Any) -> bool:
    """A person in `a` and a person in `b` with the same surname and the same first name (a first
    name of one letter matches its initial), whose middle initials, where both have one, agree. An
    entity agrees only with the same entity (name_normalize.match_owner exact)."""
    from .name_normalize import is_entity, match_owner
    for sa in segments(a):
        for sb in segments(b):
            if is_entity(sa) or is_entity(sb):
                if match_owner(sa, sb) == "exact":
                    return True
                continue
            for la, fa, ma in _readings(sa):
                for lb, fb, mb in _readings(sb):
                    if la != lb:
                        continue
                    if not (fa == fb or (len(fa) == 1 and fb.startswith(fa))
                            or (len(fb) == 1 and fa.startswith(fb))):
                        continue
                    if ma and mb and ma != mb:
                        continue
                    return True
    return False


def _g(li: Any, k: str) -> Any:
    return li.get(k) if isinstance(li, dict) else getattr(li, k, None)


def _rawof(li: Any) -> dict:
    r = _g(li, "raw")
    return r if isinstance(r, dict) else {}


def _ltof(li: Any) -> str:
    lt = _g(li, "listing_type")
    return str(getattr(lt, "value", lt) or "")


def owners_of_record(li: Any, exclude: tuple = ()) -> list[str]:
    """Owner strings on the row: every county-roll owner (block_binding.roll_owners, the parcel
    cache's owner) and the row's owner_name unless it is just one of `exclude` copied (a filing's
    case name or a notice's representative written into owner_name). A roll owner is never
    excluded: it is the county's record, whatever name it holds."""
    from .block_binding import name_tokens, roll_owners
    raw = _rawof(li)
    rolls = list(roll_owners(li))
    pa = raw.get("parcel_from_address")
    if isinstance(pa, dict):
        rolls.append(pa.get("cache_owner"))
    own = _g(li, "owner_name")
    ex = [name_tokens(e) for e in exclude if name_tokens(e)]
    cands = rolls + ([own] if name_tokens(own) and name_tokens(own) not in ex else [])
    out: list[str] = []
    for c in cands:
        if name_tokens(c) and c not in out:
            out.append(c)
    return out


def _has_property(li: Any) -> bool:
    if _g(li, "parcel_id"):
        return True
    return bool(re.match(r"\s*\d*[1-9]\d*[A-Za-z]?\s+\S", str(_g(li, "street_address") or "")))


#: raw blocks the scorer reads as facts about the PROPERTY (distress_score._collect): tax
#: balances, exemptions, code cases, vacancy, storm damage, the owner-of-record name tags. A row
#: unbound from a parcel keeps them under raw['unbound_property_blocks'] (visible, never scored).
PROPERTY_SIGNAL_BLOCKS = ("tax_owed", "amount_owed", "pickens_delinquent", "str_permit_lapsed",
                          "tax_relief", "code_enforcement", "condemned", "distressed",
                          "storm_damage", "vacancy", "vacant", "vacant_lot", "life_events",
                          "two_year_delinquent", "tax_aging_surfaced", "equity")


def _strip_property(li: Any, raw: dict, owner: Optional[str], *, blocks: bool = False) -> None:
    """The property fields a wrong binding put on the row (the existing surname guard's set);
    blocks=True also moves the property-signal blocks aside (an unbound lead scores no property
    signal)."""
    if blocks:
        moved = {k: raw.pop(k) for k in PROPERTY_SIGNAL_BLOCKS if k in raw}
        if moved:
            raw.setdefault("unbound_property_blocks", {}).update(moved)
    li.owner_name = re.sub(r"\s+", " ", str(owner or "")).strip()[:120] or None
    li.parcel_id = None
    li.street_address = None
    li.market_value = None
    li.assessed_value = None
    li.living_sqft = None
    if isinstance(raw.get("gis"), dict):
        for k in ("owner", "last_sale"):
            raw["gis"].pop(k, None)
    li.raw = raw


def _flag(raw: dict, flag: str) -> None:
    flags = raw.setdefault("qa_flags", [])
    if isinstance(flags, list) and flag not in flags:
        flags.append(flag)


#: listing types whose row IS the estate notice (its claim is the notice itself)
ESTATE_NOTICE_TYPES = frozenset({"probate_notice", "estate_lead"})
#: sources whose estate leads are bound by the county roll, not by a notice (their own verifier)
ROLL_ESTATE_SOURCES = frozenset({"counties_nc.nc_heir_estate_parcels"})


def estate_binding(li: Any) -> Optional[tuple[str, str]]:
    """('bound', basis) | ('unbound', reason) for a row whose estate notice names a property, else
    None. Pure (a board dict or a Listing): the audit invariant and the tail step share it."""
    raw = _rawof(li)
    pr = raw.get("probate")
    if not isinstance(pr, dict) or not str(pr.get("decedent") or "").strip() or not _has_property(li):
        return None
    if str(_g(li, "source") or "") in ROLL_ESTATE_SOURCES:
        return None
    dec = pr.get("decedent")
    rep = pr.get("personal_representative")
    # the row's owner_name counts only when it is not the notice's own decedent or representative
    # copied (a notice row's owner_name often is): the county roll is the evidence
    owners = owners_of_record(li, exclude=tuple(x for x in (dec, rep) if x))
    if any(names_agree(dec, o) for o in owners):
        return "bound", "decedent_is_owner"
    rep_address = pr.get("pr_address")
    if rep and any(names_agree(rep, o) for o in owners):
        if not rep_address or not _same_address(li, rep_address):
            return "bound", "representative_on_title"
        return "unbound", "representative_own_address"
    if not owners:
        return "unbound", "no_owner_of_record"
    return "unbound", "decedent_not_owner_of_record"


def bind_estate_notice(li: Any) -> Optional[str]:
    """Apply the estate-notice binding rule to one row. Returns 'bound:<basis>', 'unbound',
    'block_unbound' or None (not an estate notice on a property)."""
    b = estate_binding(li)
    if b is None:
        return None
    if b[0] == "bound":
        return f"bound:{b[1]}"
    raw = _rawof(li)
    pr = raw.get("probate") or {}
    why = {"reason": b[1], "rule": "court_signals_2026_10_09"}
    if _ltof(li) in ESTATE_NOTICE_TYPES:
        raw["estate_unbound"] = why
        _flag(raw, "estate_notice_unbound")
        _strip_property(li, raw, pr.get("decedent"), blocks=True)
        return "unbound"
    # another source's property row that absorbed the notice: the notice record leaves the row
    raw["probate_unbound"] = {**pr, **why}
    raw.pop("probate", None)
    rs = raw.get("relationship_signal")
    if isinstance(rs, dict) and rs.get("kind") == "probate" and rs.get("keyword") in (
            "public_notice", "notice_to_creditors", "obituary"):
        raw["relationship_signal_unbound"] = raw.pop("relationship_signal")
    li.raw = raw
    return "block_unbound"


def _same_address(li: Any, addr: Any) -> bool:
    from .verification.core import address_relation
    return address_relation(_g(li, "street_address"), addr) == "match"


def bankruptcy_binding(li: Any) -> Optional[tuple[str, str]]:
    """('bound', 'debtor_is_owner') | ('unbound', reason) for a bankruptcy filing row that names a
    property, else None. Pure (a board dict or a Listing)."""
    if _ltof(li) != "bankruptcy" or not _has_property(li):
        return None
    raw = _rawof(li)
    cl = raw.get("courtlistener") if isinstance(raw.get("courtlistener"), dict) else {}
    case_name = cl.get("case_name") or _g(li, "defendant")
    if not str(case_name or "").strip():
        return None
    debtor = re.split(r"\s+v\.?\s+", str(case_name), maxsplit=1, flags=re.I)[0]
    owners = owners_of_record(li, exclude=(case_name, _g(li, "defendant")))
    if any(names_agree(debtor, o) for o in owners):
        return "bound", "debtor_is_owner"
    return "unbound", ("debtor_not_owner_of_record" if owners else "no_owner_of_record")


def bind_bankruptcy_filing(li: Any) -> Optional[str]:
    """Apply the name rule to a bankruptcy filing row that names a property. Returns
    'bound', 'unbound', or None (not a bankruptcy filing on a property)."""
    b = bankruptcy_binding(li)
    if b is None:
        return None
    if b[0] == "bound":
        return "bound"
    raw = _rawof(li)
    cl = raw.get("courtlistener") if isinstance(raw.get("courtlistener"), dict) else {}
    case_name = cl.get("case_name") or _g(li, "defendant")
    raw["bankruptcy_unbound_property"] = {"reason": b[1], "rule": "court_signals_2026_10_09"}
    _flag(raw, "bankruptcy_property_unbound")
    _strip_property(li, raw, re.split(r"\s+v\.?\s+", str(case_name), maxsplit=1, flags=re.I)[0],
                    blocks=True)
    return "unbound"



def _def_surname(name: str) -> str:
    """Best-effort surname of a docket defendant. 'Williams, Joseph' -> williams;
    'Roger Leonard Mason Jr' -> mason. Empty if undeterminable."""
    name = _SUFFIX.sub(" ", name or "")
    if "," in name:
        toks = _toks(name.split(",")[0])      # 'Last, First' -> Last
    else:
        toks = _toks(name)                     # 'First Middle Last' -> last token
    return toks[-1] if toks else ""


def _clear_stale_flag(li, raw: dict) -> bool:
    """Drop an orphaned flag THIS function wrote while `li` was still court-sourced, now that a
    merge has moved it onto a different, non-court record (see module docstring). Only ever
    touches our own shape (no 'source' key) — promote_ptscloud_block.py's Henderson PTS flag
    always carries one and must survive untouched."""
    om = raw.get("owner_mismatch")
    if not (isinstance(om, dict) and "source" not in om):
        return False
    raw.pop("owner_mismatch", None)
    flags = raw.get("qa_flags")
    if isinstance(flags, list) and "court_owner_mismatch" in flags:
        flags.remove("court_owner_mismatch")
    li.raw = raw
    return True


def enrich_court_owner_verify(listings) -> dict:
    stats = {"checked": 0, "mismatch": 0, "stripped": 0, "stale_cleared": 0,
             "retyped_lien_claim": 0, "retyped_judgment_lien": 0,
             "estate_bound": 0, "estate_unbound": 0, "estate_block_unbound": 0,
             "bankruptcy_bound": 0, "bankruptcy_unbound": 0}
    listings = list(listings)
    for li in listings:
        k = retype_court_lien(li)
        if k:
            stats[f"retyped_{k}"] += 1
    for li in listings:
        src = li.source or ""
        lt = li.listing_type.value if getattr(li, "listing_type", None) and hasattr(li.listing_type, "value") else ""
        raw0 = li.raw if isinstance(li.raw, dict) else {}
        is_court = (src.startswith("national.courtlistener") or lt in ("lis_pendens", "bankruptcy", "lien_claim")
                    or ("ecourts" in src and isinstance(raw0.get("nc_ecourts"), dict)))
        raw = li.raw if isinstance(li.raw, dict) else {}
        if not is_court:
            if _clear_stale_flag(li, raw):
                stats["stale_cleared"] += 1
            continue
        owner = li.owner_name or (raw.get("gis") or {}).get("owner") or ""
        defn = li.defendant or ""
        ds = _def_surname(defn)
        ot = set(_toks(owner))
        if not (ds and ot and defn and owner):
            continue
        stats["checked"] += 1
        if ds in ot:
            continue  # defendant surname present in the owner string -> consistent, keep
        # Mismatch: the on-title owner is a different family than the docket party.
        stats["mismatch"] += 1
        raw["owner_mismatch"] = {"defendant_surname": ds, "snapped_owner": owner[:80]}
        flags = raw.setdefault("qa_flags", [])
        if isinstance(flags, list) and "court_owner_mismatch" not in flags:
            flags.append("court_owner_mismatch")
        # Strip the mis-attached property -> honest name-only court record (the defendant + docket).
        li.owner_name = re.sub(r"\s+", " ", defn).strip()[:120] or None
        li.parcel_id = None
        li.street_address = None
        li.market_value = None
        li.assessed_value = None
        li.living_sqft = None
        if isinstance(raw.get("gis"), dict):
            for k in ("owner", "last_sale"):
                raw["gis"].pop(k, None)
        li.raw = raw
        stats["stripped"] += 1
    for li in listings:
        try:
            e = bind_estate_notice(li)
            if e == "unbound":
                stats["estate_unbound"] += 1
            elif e == "block_unbound":
                stats["estate_block_unbound"] += 1
            elif e:
                stats["estate_bound"] += 1
            b = bind_bankruptcy_filing(li)
            if b:
                stats[f"bankruptcy_{b}"] += 1
        except Exception:  # noqa: BLE001 - one odd row never costs the step
            stats["binding_errors"] = stats.get("binding_errors", 0) + 1
    return stats
