"""The CALL-READY gate: is there a checked, real problem on this lead that a person can call (or
write) the owner about today, and what still stands in the way? Pure: no I/O, no network.

docs/call_ready.md is the plain-words version (lanes, tiers, conditions, the Fullmer mapping and
the counts). The owner's goal, verbatim in spirit: if we call, there is an actual issue we can speak
about with empathy, the call does not waste anyone's time, and the lead can go to the lawyer, be
cleaned up (title, payoffs) and be sold through an agent.

LANES (the path a lead takes; one primary lane per row)
  A  owner call: delinquent tax   the county's own tax site confirmed late years and an amount on
                                  the row's own parcel inside CHECK_MAX_AGE_DAYS; the owner of record
                                  is a living person (no entity, estate or trust, no death record);
                                  not paid, not sold at a tax sale, not in bankruptcy; a phone that
                                  is tied to the record or matches the owner by name only; a sane
                                  mailing address.
  B  heir lane                    the owner of record is dead on a record (the roll's HEIRS / ESTATE
                                  wording, a probate record, the county death index) and an estate is
                                  open: a probate record names a personal representative, seen inside
                                  ESTATE_NOTICE_MAX_DAYS; the representative or an heir candidate with
                                  a stated relation is the person to reach.
  C  quiet-title lawyer lane      the owner of record is dead on a record and no open estate is on
                                  file (the title sits in the dead owner's name): the attorney's
                                  intake list is complete and every item sourced (parcel, legal
                                  description + the latest deed, deed chain, taxpayer of record,
                                  heirs, records checked: register of deeds, tax, probate, obituaries).
  D  foreclosure flip             a foreclosure / auction / sheriff / HOA sale in one of the 18
                                  original counties (config.in_scope) whose sale date is ahead or
                                  whose upset-bid window is open, and whose status was re-seen at the
                                  source inside STATUS_RECHECK_MAX_DAYS (not pulled, not stayed).
  E  mail only                    a checked issue (a confirmed county tax balance, a confirmed code
                                  or vacant-structure case) with a sane mailing address and no
                                  phone a closer may dial (or an entity / trust owner).

TIERS (how ready the lead is)
  A  call now                     every gate condition of the lane holds and the phone is tied to
                                  the property's record (the matcher matched the parcel or the
                                  property's address, or block_binding binds it by parcel/address).
  B  call, confirm identity first the gate holds; the phone matches the owner by NAME only (voter
                                  file, name + county): the first question of the call confirms the
                                  person.
  C  mail                         the gate holds and there is no dialable phone, or the lane's
                                  contact is a mailing address (an estate's representative).
  D  research                     a gate condition is not met (the list says which).

A phone on the DNC registry or flagged do-not-dial never makes tier A or B (the lead is mailed).
The DNC scrub itself is a dial-time step: no registry file has been loaded (raw['dnc_scrub'] is
absent or 'unverified' on every row), so dnc_status is published and 'dnc_not_scrubbed' is listed,
but it does not lower the tier.

RANK (0-100, ORDER within a tier, never a filter; Fullmer ranks, he does not delete): ripeness by
years delinquent (fullmer_rank.delinq_ripeness_points: year 1 is early, 2 is the base, ramping to
the 15-year peak), the size of the confirmed balance, margin versus the fixed curative cost
(raw['fullmer'].margin_coverage: 4x strong, 2x acceptable), the county-appraised value, the owner
count, exit liquidity, and for lane D the days to the sale.

OUTPUT raw['call_ready'] (public-safe: no names, phones, e-mails, ages; the dashboard is public):
  {v, lane, tier, rank, reason, unmet: [codes], checks: [{check, result, on, source}],
   phone, dnc, mail, facts: {...}, lawyer: {...} (lanes B and C), as_of}
A row with no lane gets the short form {v, lane: "", tier: "D", unmet: [...]}.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

VERSION = 1

#: the owner's rule: a county-site check older than this is not a reason to call today
CHECK_MAX_AGE_DAYS = 30
#: lane D: the sale must have been re-seen at its source this recently
STATUS_RECHECK_MAX_DAYS = 7
#: lane B: a probate notice seen this long ago or less is taken as an open estate (the board has no
#: closing date; NC and SC creditor periods run 3 and 8 months from first publication, estates
#: commonly stay open a year). Older: the clerk's index is checked by a person.
ESTATE_NOTICE_MAX_DAYS = 365
#: tax_lien verifiers whose earlier versions had a defect that can confirm another parcel's debt
#: (tax_lien_ptscloud before v4: a merged roll block was not the row's parcel; tax_lien_buncombe
#: before v5 and tax_lien_qpaybill before v3: the address account was followed without proof).
MIN_VERIFIER_VERSION = {"tax_lien_ptscloud": 4, "tax_lien_buncombe": 5, "tax_lien_qpaybill": 3}

LANES = {
    "A": "owner call: delinquent tax",
    "B": "heir lane: open estate",
    "C": "quiet-title lawyer lane",
    "D": "foreclosure flip",
    "E": "mail only",
}
TIERS = {"A": "call now", "B": "call, confirm identity first", "C": "mail", "D": "research"}

#: unmet condition codes, in plain words (the dashboard, the CSV and the evidence sheet print these)
UNMET_WORDS = {
    "no_call_lane": "no lane: not a tax, estate, title or foreclosure-sale lead, and no check confirmed an issue",
    "government_owner": "the owner of record is a government body",
    "tax_check_missing": "the county tax site has not been checked for this parcel",
    "tax_check_unconfirmed": "the county tax site check could not decide",
    "tax_check_wall": "the county tax site cannot be checked by code (a person checks it)",
    "tax_paid": "the county tax site shows the delinquent bill was paid",
    "tax_not_owed": "the county tax site shows no delinquent bill for the claimed years",
    "tax_check_old": "the county tax site check is older than 30 days",
    "tax_check_other_parcel": "the county check was for a different parcel than this row's",
    "tax_check_outdated_verifier": "the check was made by an older checker version with a known wrong-parcel defect",
    "tax_balance_de_minimis": "the confirmed balance is under $25 (a payment shortfall, not a problem to call about)",
    "tax_no_late_years": "the county site shows no completed late year",
    "sold_at_tax_sale": "the county site shows the parcel was sold at a tax sale",
    "in_bankruptcy": "a bankruptcy case or stay is on record for the owner",
    "owner_not_person": "the owner of record is a company, trust or other entity",
    "owner_unknown": "no owner of record on the row",
    "owner_deceased_on_record": "a record says the owner of record died (heir lane)",
    "owner_maybe_deceased": "an obituary or death marker names the owner; confirm the death before calling",
    "no_dialable_phone": "no phone a closer may dial is tied to the owner",
    "phone_other_record": "the phone on the row belongs to another person's or property's record",
    "phone_not_owner": "the phone on the row is an agent's, a people-search result or marked do-not-dial",
    "phone_unlinked": "nothing ties the phone on the row to the owner (no parcel, address or name match)",
    "dnc_registered": "the phone is on the Do Not Call registry or blocked; mail instead",
    "dnc_not_scrubbed": "the phone has not been scrubbed against the Do Not Call list (do it before dialing)",
    "mailing_missing": "no mailing address on the county record",
    "mailing_other_record": "the mailing address on the row is another property's or person's record",
    "mailing_malformed": "the mailing address is incomplete (no number, box or ZIP)",
    "death_not_on_record": "the death is not on a county or court record yet",
    "decedent_not_tied_to_parcel": "the county roll names someone other than the dead person as this parcel's owner",
    "decedent_tie_unproven": "no county roll owner on the row to tie the dead person to this parcel",
    "no_property_on_row": "the row names no parcel and no street address (the estate is not tied to a property)",
    "no_estate_contact": "no personal representative or heir with a stated relation is on file",
    "estate_not_open": "no open estate on file (the lawyer lane applies)",
    "estate_status_unknown": "the probate notice is over a year old; check the clerk's index for the estate's status",
    "conveyed_after_death": "a deed recorded after the death suggests the estate already conveyed the property",
    "lawyer_parcel": "lawyer's list: parcel number missing",
    "lawyer_legal_description": "lawyer's list: legal description or the latest deed's book and page missing",
    "lawyer_deed_chain": "lawyer's list: deed chain missing (fewer than two recorded transfers)",
    "lawyer_taxpayer": "lawyer's list: taxpayer of record not confirmed by the county roll or tax site",
    "lawyer_heirs": "lawyer's list: no heir candidate with a stated relation",
    "lawyer_rod_checked": "lawyer's list: register of deeds not checked",
    "lawyer_tax_checked": "lawyer's list: county tax site not checked",
    "lawyer_probate_checked": "lawyer's list: probate (estate files) not checked",
    "lawyer_obituaries_checked": "lawyer's list: obituaries not checked",
    "outside_original_counties": "a foreclosure sale outside the 18 original counties (not a flip lead)",
    "sale_window_closed": "the sale date passed and no upset-bid window is open",
    "sale_date_missing": "no sale date and no upset-bid window on the row",
    "status_not_rechecked": "the sale was not re-seen at its source in the last 7 days",
    "sale_pulled": "the sale was pulled, withdrawn, dismissed or postponed at the source",
    "sale_stayed": "a bankruptcy stay holds the sale",
    "foreclosure_ended": "the register of deeds shows the foreclosure ended",
    "issue_not_checked": "no check at a source confirmed the issue",
}

# ---------------------------------------------------------------------------------------------
# small helpers (dict rows and models.Listing alike)
# ---------------------------------------------------------------------------------------------


def _g(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def _raw(row: Any) -> dict:
    r = _g(row, "raw")
    return r if isinstance(r, dict) else {}


def _ltype(row: Any) -> str:
    v = _g(row, "listing_type")
    return str(getattr(v, "value", v) or "").strip().lower()


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def to_date(v: Any) -> Optional[date]:
    from .signal_freshness import to_date as _td
    return _td(v)


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _money(v: float) -> str:
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"


def _host(url: Any) -> str:
    m = re.match(r"^\s*https?://([^/\s]+)", str(url or ""))
    return m.group(1).lower() if m else ""


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------------------------
# facts read off the row
# ---------------------------------------------------------------------------------------------


def record(raw: dict, signal: str) -> Optional[dict]:
    """The row's verification record for `signal` (raw['verification'], one per signal)."""
    from .verification.core import records_of
    for r in records_of(raw):
        if r.get("signal") == signal:
            return r
    return None


def _version_number(v: Any) -> Optional[int]:
    m = re.match(r"^\s*v?(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


def tax_fact(row: Any, today: date) -> dict:
    """What the county tax site said about this row's parcel, judged against the lane A rules.
    {status: 'confirmed' | an unmet code, verdict, checked_on, age_days, verifier, source, years,
     total, url}."""
    from .tax_binding import verified_checks_row
    from .verification.verifiers._tax_common import DE_MINIMIS
    rec = record(_raw(row), "tax_lien")
    if rec is None:
        return {"status": "tax_check_missing"}
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    verdict = str(rec.get("verdict") or "")
    checked = to_date(rec.get("checked_at"))
    out = {"verdict": verdict, "checked_on": _iso(checked),
           "age_days": (today - checked).days if checked else None,
           "verifier": rec.get("verifier") or "", "version": rec.get("verifier_version") or "",
           "source": rec.get("source") or _host(ev.get("url")), "url": ev.get("url") or ev.get("page_url")}
    late = sorted(int(str(y)[:4]) for y, a in (ev.get("delinquent_by_year") or {}).items()
                  if str(y)[:4].isdigit() and (_num(a) or 0) > 0) \
        if isinstance(ev.get("delinquent_by_year"), dict) else []
    years = ev.get("years_delinquent")
    years = int(years) if isinstance(years, int) and not isinstance(years, bool) else len(late)
    total = _num(ev.get("total_delinquent")) or 0.0
    out.update({"years": years, "total": round(total, 2), "late_years": late[-6:]})
    sold = bool(ev.get("sold_at_tax_sale_years") or ev.get("sold_at_tax_sale_on")
                or str(ev.get("reason") or "") == "sold_at_tax_sale")
    out["sold_at_tax_sale"] = sold
    if verdict == "stale":
        out["status"] = "tax_paid"
    elif verdict == "refuted":
        out["status"] = "tax_not_owed"
    elif verdict == "wall":
        out["status"] = "tax_check_wall"
    elif verdict != "confirmed":
        out["status"] = "sold_at_tax_sale" if sold else "tax_check_unconfirmed"
    elif sold:
        out["status"] = "sold_at_tax_sale"
    elif not verified_checks_row(row, ev):
        out["status"] = "tax_check_other_parcel"
    elif (_version_number(out["version"]) or 0) < MIN_VERIFIER_VERSION.get(out["verifier"], 0):
        out["status"] = "tax_check_outdated_verifier"
    elif total < DE_MINIMIS:
        out["status"] = "tax_balance_de_minimis"
    elif years < 1:
        out["status"] = "tax_no_late_years"
    elif out["age_days"] is None or out["age_days"] > CHECK_MAX_AGE_DAYS:
        out["status"] = "tax_check_old"
    else:
        out["status"] = "confirmed"
    return out


def property_tax_claim(row: Any) -> bool:
    """The row claims a county property-tax delinquency (not a state, federal or lien-agent lien)."""
    from .verification.verifiers._tax_common import TAX_LISTING_TYPES, other_lien_listing
    raw = _raw(row)
    if _ltype(row) in TAX_LISTING_TYPES and not other_lien_listing(row):
        return True
    to = raw.get("tax_owed")
    return isinstance(to, dict) and str(to.get("kind") or "delinquent_tax") == "delinquent_tax" \
        and (_num(to.get("balance")) or 0) > 0 and not other_lien_listing(row)


def owner_kind(row: Any) -> str:
    """'individual' | 'entity' | 'trust' | 'estate' | 'government' | 'unknown' (raw['entity_type'],
    which enrichment_entity_type persists for the run's final owner name, else computed)."""
    et = _raw(row).get("entity_type")
    if isinstance(et, str) and et in ("individual", "entity", "trust", "estate", "government", "unknown"):
        return et
    from .name_normalize import classify_entity_type
    return classify_entity_type(_g(row, "owner_name"))


def _tokens(name: Any) -> frozenset:
    from .block_binding import name_tokens
    return name_tokens(name)


def names_agree(a: Any, b: Any, need: int = 2) -> Optional[bool]:
    """True when two names share `need` identity tokens (first + last, not a surname alone), False
    when both have tokens and share none, None when it cannot be told."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return None
    common = len(ta & tb)
    if common >= min(need, len(ta), len(tb)):
        return True
    return False if common == 0 else None


def _owner_names(row: Any) -> list[str]:
    from .block_binding import roll_owners
    out = [str(_g(row, "owner_name") or "")]
    try:
        out += [str(o) for o in roll_owners(row)]
    except Exception:  # noqa: BLE001 - an odd block never stops the gate
        pass
    return [o for o in out if o.strip()]


def _roll_owner_names(row: Any) -> list[str]:
    from .block_binding import roll_owners
    try:
        return [str(o) for o in roll_owners(row) if _tokens(o)]
    except Exception:  # noqa: BLE001
        return []


#: listing types whose owner_name is the notice's own reading (a decedent or a party), not a county roll's
NOTICE_TYPES = frozenset({"probate_notice", "estate_lead", "divorce_notice"})


def _decedent_ties(row: Any, name: Any) -> Optional[bool]:
    """Does a decedent name agree with the parcel's owner on the COUNTY ROLL? True when a roll owner
    shares first + last name with it; False when the row carries roll owners and every one is
    another person; None when the row has no roll owner (a notice row's own owner_name is the
    notice's reading of the decedent, so it proves nothing about the parcel)."""
    rolls = _roll_owner_names(row)
    if rolls:
        votes = [names_agree(name, o) for o in rolls]
        if any(v is True for v in votes):
            return True
        return False if all(v is False for v in votes) else None
    if _ltype(row) in NOTICE_TYPES:
        return None
    v = names_agree(name, _g(row, "owner_name"))
    return True if v else (False if v is False else None)


def has_property(row: Any) -> bool:
    """The row names a property: a usable parcel id or a house-numbered street address."""
    from .block_binding import own_location
    try:
        return own_location(row)
    except Exception:  # noqa: BLE001
        return False


def death_fact(row: Any) -> dict:
    """Who says the owner of record died. {record: [kinds], weak: [kinds], tied: bool|None,
    date_of_death, decedent_names: [..] (internal; never published)}.
    record kinds: roll_wording (HEIRS / ESTATE OF / DECEASED on the owner of record or the roll's
    heir-estate block), probate_record, sc_probate_notice, deceased_owner_roll (McDowell), death_index
    (the probate_heir verifier confirmed), listing_type (an estate / probate notice row).
    weak kinds: obituary, life_event_death, heir_summary (the heir-candidate pass's own signals)."""
    from .quiet_title.names import roll_markers
    from .signal_freshness import has_real_probate
    raw = _raw(row)
    rec_kinds: list[str] = []
    weak: list[str] = []
    names: list[str] = []
    dod: Optional[date] = None
    owner = _g(row, "owner_name")
    if roll_markers(owner) or owner_kind(row) == "estate":
        rec_kinds.append("roll_wording")
    he = raw.get("heir_estate")
    if isinstance(he, dict) and (roll_markers(he.get("owner_of_record")) or he.get("heir_names")):
        if "roll_wording" not in rec_kinds:
            rec_kinds.append("roll_wording")
        if he.get("owner_of_record"):
            names.append(str(he["owner_of_record"]))
    pb = raw.get("probate")
    if has_real_probate(pb):
        rec_kinds.append("probate_record")
        if pb.get("decedent"):
            names.append(str(pb["decedent"]))
        dod = dod or to_date(pb.get("date_of_death"))
    sp = raw.get("sc_probate_notice")
    if isinstance(sp, dict) and (sp.get("case_number") or sp.get("estate")):
        rec_kinds.append("sc_probate_notice")
        if sp.get("estate"):
            names.append(str(sp["estate"]))
        dod = dod or to_date(sp.get("date_of_death"))
    mp = raw.get("mcdowell_probate")
    if isinstance(mp, dict) and (mp.get("deceased_owner") or mp.get("ownname")):
        rec_kinds.append("deceased_owner_roll")
        names.append(str(mp.get("deceased_owner") or mp.get("ownname")))
    ph = record(raw, "probate_heir")
    if ph and ph.get("verdict") == "confirmed":
        rec_kinds.append("death_index")
    if _ltype(row) in ("estate_lead", "probate_notice") and not rec_kinds:
        rec_kinds.append("listing_type")
    ob = raw.get("obituary")
    if isinstance(ob, dict) and ob.get("decedent"):
        weak.append("obituary")
        names.append(str(ob["decedent"]))
    le = raw.get("life_event")
    if le == "death" or (isinstance(le, dict) and le.get("type") == "death"):
        weak.append("life_event_death")
    hs = raw.get("heir_candidates_summary")
    if isinstance(hs, dict) and hs.get("deceased_signals"):
        weak.append("heir_summary")
    tied: Optional[bool] = None
    if "death_index" in rec_kinds:
        tied = True                       # the county's own death + parcel check named this owner
    elif "roll_wording" in rec_kinds and isinstance(he, dict) and roll_markers(he.get("owner_of_record")):
        tied = True                       # the county roll itself titles the parcel to heirs / an estate
    elif "roll_wording" in rec_kinds and _ltype(row) not in NOTICE_TYPES:
        from .block_binding import row_owner_strength
        try:
            tied = row_owner_strength(row) != "contradicted"
        except Exception:  # noqa: BLE001
            tied = None
    if tied is None:
        for n in names:
            v = _decedent_ties(row, re.sub(r"(?i)\bestate of\b|\bheirs?\b|\bdeceased\b", " ", n))
            if v:
                tied = True
                break
            if v is False:
                tied = False
    return {"record": rec_kinds, "weak": weak, "tied": tied, "date_of_death": _iso(dod),
            "_names": names}


def estate_fact(row: Any, today: date) -> dict:
    """An open estate's contact: {open: 'open'|'unknown'|'none', pr: bool, pr_address: bool,
    heirs: int (candidates with a publishable relation), seen_on}."""
    from .enrichment_heir_candidates import PUBLISHABLE_HEIR_RELATIONS
    from .signal_freshness import has_real_probate
    raw = _raw(row)
    pr = pr_addr = False
    case = False
    for key in ("probate", "sc_probate_notice"):
        b = raw.get(key)
        if not isinstance(b, dict):
            continue
        if key == "probate" and not has_real_probate(b):
            continue
        if str(b.get("personal_representative") or "").strip():
            pr = True
        if str(b.get("pr_address") or "").strip():
            pr_addr = True
        if any(str(b.get(k) or "").strip() for k in ("es_case_number", "nc_estate_file_no", "case_number")):
            case = True
    heirs = 0
    reps = 0
    hc = raw.get("heir_candidates")
    if isinstance(hc, list):
        for c in hc:
            if not isinstance(c, dict):
                continue
            rel = str(c.get("relation") or "").strip().lower()
            if rel in PUBLISHABLE_HEIR_RELATIONS:
                heirs += 1
                if rel in ("personal representative", "executor", "executrix", "administrator",
                           "administratrix"):
                    reps += 1
    pr = pr or reps > 0
    seen = to_date(_g(row, "first_seen"))
    if not case and not pr:
        status = "none"
    elif seen is not None and (today - seen).days <= ESTATE_NOTICE_MAX_DAYS:
        status = "open"
    else:
        status = "unknown"
    he = raw.get("heir_estate")
    care_of = isinstance(he, dict) and bool(str(he.get("care_of") or "").strip())
    return {"open": status, "pr": pr, "pr_address": pr_addr, "heirs": heirs, "care_of": care_of,
            "seen_on": _iso(seen)}


#: owner_phone.match values that name the property itself (the parcel id or the property's address)
_PARCEL_MATCHES = frozenset({"parcel_id", "parcel_id_base", "parcel_id+ownerid", "name+address"})


def phone_fact(row: Any) -> dict:
    """{link: tied | name_match_only | other_record | not_owner | unlinked | none, dnc, line_type,
    tcpa_class, source, match, verdict}. `link` follows the owner's rule: tied to the record
    (block_binding binds it to the parcel or address, it is the row's own source's record, or its
    writer matched it on the parcel id or name + the property's address) or name-match-only."""
    from .block_binding import UNBOUND, block_verdict, parcel_relation
    from .enrichment_sc_phone import owner_phone_block_reason
    raw = _raw(row)
    op = raw.get("owner_phone")
    if not isinstance(op, dict) or not str(op.get("phone") or "").strip():
        return {"link": "none", "dnc": None}
    out = {"source": op.get("source"), "match": op.get("match"), "line_type": op.get("line_type"),
           "tcpa_class": op.get("tcpa_class")}
    out["dnc"] = dnc_status(raw, op.get("phone"))
    why = owner_phone_block_reason(op)
    if why:
        out.update(link="not_owner", block_reason=why)
        return out
    if op.get("identity_check") == "contradicted":
        out.update(link="other_record", verdict="identity_contradicted")
        return out
    try:
        verdict, p = block_verdict(row, "owner_phone", op, fallback=False)
    except Exception:  # noqa: BLE001
        verdict, p = "unknown", None
    out["verdict"] = verdict
    if verdict in UNBOUND:
        out["link"] = "other_record"
        return out
    match = str(op.get("match") or "").strip().lower()
    if verdict == "own_source" or match in _PARCEL_MATCHES:
        out["link"] = "tied"
    elif verdict == "bound" and p is not None and parcel_relation(row, p) == "same":
        out["link"] = "tied"
    elif verdict == "bound" or match.startswith(("name", "fuzzy", "nc_xref")):
        out["link"] = "name_match_only"
    else:
        out["link"] = "unlinked"
    return out


def _digits10(v: Any) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d[1:] if len(d) == 11 and d.startswith("1") else d


def dnc_status(raw: dict, phone: Any) -> str:
    """raw['dnc_scrub']'s status for this phone: clear | registered | unverified | do_not_dial |
    not_owner_contact, or 'not_scrubbed' when the scrub never ran for it."""
    want = _digits10(phone)
    for e in raw.get("dnc_scrub") or [] if isinstance(raw.get("dnc_scrub"), list) else []:
        if isinstance(e, dict) and _digits10(e.get("phone")) == want and want:
            return str(e.get("dnc_status") or "unverified")
    return "not_scrubbed"


_ZIP = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_STATE = re.compile(r"\b[A-Z]{2}\b")
_BOX = re.compile(r"\b(P\s*\.?\s*O\.?\s*BOX|BOX|RR|HC|PMB|RURAL ROUTE)\b", re.I)
_BAD_MAIL = re.compile(r"\b(UNKNOWN|NO ADDRESS|ADDRESS UNKNOWN|RETURNED|UNDELIVERABLE|NONE|N/A)\b", re.I)


def mailing_text(raw: dict) -> str:
    from .mailing_shape import mailing_dict
    om = mailing_dict(raw)
    s = str(om.get("mailing") or "").strip()
    if not s and om.get("street"):
        s = " ".join(str(om.get(k) or "") for k in ("street", "city", "state", "zip")).strip()
    if not s:
        gis = raw.get("gis")
        if isinstance(gis, dict) and isinstance(gis.get("mailing"), str):
            s = gis["mailing"].strip()
    return re.sub(r"\s+", " ", s)


def mailing_sane(text: str) -> bool:
    """A deliverable-looking address: a house number or a box, and a ZIP (or a two-letter state)
    after it; no notice text, no 'unknown' / 'returned' marker, not a paragraph."""
    from .verification.core import has_notice_text
    s = str(text or "").strip()
    if len(s) < 8 or len(s) > 160 or has_notice_text(s) or _BAD_MAIL.search(s):
        return False
    numbered = bool(re.match(r"^\s*\d+[A-Z]?\b", s.upper())) or bool(_BOX.search(s))
    tail = bool(_ZIP.search(s)) or bool(_STATE.search(s.upper()[-12:]))
    return numbered and tail


def mailing_fact(row: Any) -> dict:
    """{status: ok | missing | other_record | malformed, verdict}."""
    from .block_binding import UNBOUND, block_verdict
    from .mailing_shape import mailing_dict
    raw = _raw(row)
    text = mailing_text(raw)
    if not text:
        return {"status": "missing"}
    om = mailing_dict(raw)
    verdict = None
    if om:
        try:
            verdict = block_verdict(row, "owner_mailing", om, fallback=False)[0]
        except Exception:  # noqa: BLE001
            verdict = "unknown"
    if verdict in UNBOUND:
        return {"status": "other_record", "verdict": verdict}
    if not mailing_sane(text):
        return {"status": "malformed", "verdict": verdict}
    return {"status": "ok", "verdict": verdict, "absentee": bool(om.get("absentee"))}


def bankruptcy_fact(row: Any, today: date) -> dict:
    """{active: bool, basis}: a bankruptcy case or stay in force for this owner. A refuted or stale
    bankruptcy_stay verdict (the case is someone else's, or over) ends it."""
    from .signal_freshness import bankruptcy_lapsed
    raw = _raw(row)
    rec = record(raw, "bankruptcy_stay")
    if rec and rec.get("verdict") in ("refuted", "stale"):
        return {"active": False, "basis": f"bankruptcy check {rec.get('verdict')}",
                "checked_on": _iso(to_date(rec.get("checked_at")))}
    if rec and rec.get("verdict") == "confirmed":
        return {"active": True, "basis": "bankruptcy court record confirmed",
                "checked_on": _iso(to_date(rec.get("checked_at")))}
    st = raw.get("bankruptcy_stay")
    if isinstance(st, dict) and st.get("status") == "stayed" and not bankruptcy_lapsed(
            {"date_filed": st.get("date_filed"), "chapter": st.get("chapter")}, today):
        return {"active": True, "basis": "automatic stay on record"}
    bk = raw.get("bankruptcy")
    if isinstance(bk, dict) and not bk.get("date_terminated") and not bankruptcy_lapsed(bk, today) \
            and str(bk.get("match_verdict") or "") not in ("refuted", "different_person", "rejected"):
        return {"active": True, "basis": "open bankruptcy case matched to the owner"}
    if _ltype(row) == "bankruptcy":
        return {"active": True, "basis": "bankruptcy filing row"}
    return {"active": False}


_PULLED_STATUS = re.compile(r"withdraw|cancel|dismiss|settled|postpon|stayed|ended|presumed|time payment|"
                            r"disposed|hold\b", re.I)
#: listing types of a foreclosure sale a person can bid at (distress_score.FLIP_TYPES minus REO, plus
#: a lis pendens whose sale date is set: SC judicial foreclosures carry the Master-in-Equity sale)
SALE_TYPES = frozenset({"foreclosure_sale", "auction", "sheriff_sale", "hoa_sale", "lis_pendens"})


def sale_fact(row: Any, today: date) -> Optional[dict]:
    """Lane D facts, or None when the row is not a foreclosure sale. {window: open | closed |
    missing, kind, sale_on, days, upset_deadline, last_seen, recheck_days, pulled, stayed,
    original_county}."""
    from .config import in_scope
    raw = _raw(row)
    lt = _ltype(row)
    ub = raw.get("upset_bid") if isinstance(raw.get("upset_bid"), dict) else None
    if lt not in SALE_TYPES and not ub:
        return None
    sale = to_date(_g(row, "sale_date"))
    if lt == "lis_pendens" and sale is None and not ub:
        return None
    out: dict = {"kind": lt, "sale_on": _iso(sale),
                 "original_county": in_scope(_g(row, "county"), _g(row, "state"))}
    upset_open = False
    if ub and ub.get("in_window") is True:
        dl = to_date(ub.get("deadline_iso")) or to_date(_g(row, "upset_bid_deadline"))
        upset_open = dl is None or dl >= today
        out["upset_deadline"] = _iso(dl)
    days = (sale - today).days if sale else None
    out["days"] = days
    if upset_open:
        out["window"] = "upset_open"
        dl = to_date(out.get("upset_deadline"))
        out["days"] = (dl - today).days if dl else days
    elif sale is not None and days >= 0:
        out["window"] = "sale_ahead"
    elif sale is None:
        out["window"] = "missing"
    else:
        out["window"] = "closed"
    seen = to_date(_g(row, "last_seen"))
    cb = raw.get("court_bid")
    cb_seen = to_date(cb.get("looked_up_iso")) if isinstance(cb, dict) else None
    best = max([d for d in (seen, cb_seen) if d], default=None)
    out["last_seen"] = _iso(best)
    out["recheck_days"] = (today - best).days if best else None
    ps = raw.get("pulled_sale")
    status = str(_g(row, "auction_status") or "")
    out["pulled"] = bool((isinstance(ps, dict) and (ps.get("presumed_withdrawn") or (ps.get("consecutive_misses") or 0) > 0))
                         or _PULLED_STATUS.search(status))
    st = raw.get("bankruptcy_stay")
    out["stayed"] = bool(isinstance(st, dict) and st.get("status") == "stayed") or \
        bool(isinstance(raw.get("distress_stack"), dict) and raw["distress_stack"].get("stay"))
    fr = record(raw, "foreclosure_rod")
    out["rod_ended"] = bool(fr and fr.get("verdict") in ("stale", "refuted"))
    if fr:
        out["rod_check"] = {"result": fr.get("verdict"), "on": _iso(to_date(fr.get("checked_at")))}
    return out


def other_issue_checks(raw: dict, today: date) -> list[dict]:
    """Confirmed, unexpired code-enforcement / vacant-structure / foreclosure checks (lane E)."""
    from .verification.core import is_expired
    out = []
    for sig in ("code_enforcement", "vacant_structure", "foreclosure_rod"):
        rec = record(raw, sig)
        if rec and rec.get("verdict") == "confirmed" and not is_expired(
                rec, datetime(today.year, today.month, today.day, tzinfo=timezone.utc)):
            out.append({"check": sig, "result": "confirmed", "on": _iso(to_date(rec.get("checked_at"))),
                        "source": rec.get("source") or ""})
    return out


# ---------------------------------------------------------------------------------------------
# the lawyer's list (Stephen's intake list)
# ---------------------------------------------------------------------------------------------

def _latest_deed(raw: dict) -> Optional[dict]:
    dc = raw.get("deed_chain")
    tr = dc.get("transfers") if isinstance(dc, dict) else None
    best = None
    if isinstance(tr, list):
        for t in tr:
            if isinstance(t, dict) and (t.get("book") or t.get("instrument")):
                d = to_date(t.get("date"))
                if best is None or (d and (best[0] is None or d > best[0])):
                    best = (d, t)
    if best:
        return {"date": _iso(best[0]), "book": best[1].get("book"), "page": best[1].get("page")}
    ph = record(raw, "probate_heir")
    par = ((ph or {}).get("evidence") or {}).get("parcel") if ph else None
    if isinstance(par, dict) and par.get("vesting_deed"):
        return {"date": par.get("vesting_date"), "book_page": par.get("vesting_deed")}
    gis = raw.get("gis")
    ls = gis.get("last_sale") if isinstance(gis, dict) else None
    if isinstance(ls, dict) and (ls.get("book") or ls.get("deed_book")):
        return {"date": _iso(to_date(ls.get("date"))), "book": ls.get("book") or ls.get("deed_book"),
                "page": ls.get("page") or ls.get("deed_page")}
    return None


def conveyed_after_death(raw: dict, death: dict) -> bool:
    """A deed recorded after the date of death: the estate (or someone) already conveyed it."""
    dod = to_date(death.get("date_of_death"))
    deed = _latest_deed(raw)
    dd = to_date((deed or {}).get("date"))
    return bool(dod and dd and dd > dod)


def lawyer_list(row: Any, tax: dict, death: dict, estate: dict) -> dict:
    """The attorney's intake list, each item 'ok' / 'missing' / a check date / 'n/a'."""
    from .block_binding import row_owner_strength
    from .tax_binding import norm_id, usable_id
    raw = _raw(row)
    out: dict = {}
    pid = _g(row, "parcel_id")
    out["parcel"] = "ok" if pid and usable_id(norm_id(pid)) else "missing"
    deed = _latest_deed(raw)
    out["legal_description"] = "ok" if (str(_g(row, "legal_description") or "").strip() and deed) else "missing"
    dc = raw.get("deed_chain")
    n_tr = len(dc.get("transfers") or []) if isinstance(dc, dict) and isinstance(dc.get("transfers"), list) else 0
    ph = record(raw, "probate_heir")
    chain_done = bool(((((ph or {}).get("evidence") or {}).get("transfer") or {}).get("chain") or {}).get("complete"))
    out["deed_chain"] = "ok" if (n_tr >= 2 or chain_done) else "missing"
    try:
        strength = row_owner_strength(row)
    except Exception:  # noqa: BLE001
        strength = "none"
    owner_ok = strength == "roll" or (tax.get("verdict") in ("confirmed", "stale", "refuted")
                                       and str(((record(raw, "tax_lien") or {}).get("evidence") or {}).get("owner_match") or "") == "same")
    out["taxpayer"] = "ok" if (str(_g(row, "owner_name") or "").strip() and owner_ok) else "missing"
    if death.get("record") or death.get("weak"):
        out["heirs"] = "ok" if (estate.get("heirs") or estate.get("pr")) else "missing"
    else:
        out["heirs"] = "n/a"
    rod_dates = [to_date((record(raw, s) or {}).get("checked_at")) for s in ("probate_heir", "foreclosure_rod")]
    rl = raw.get("rod_lookup")
    if isinstance(rl, dict):
        rod_dates.append(to_date(rl.get("looked_up_at") or rl.get("checked_at") or rl.get("as_of")
                                 or rl.get("fetched_at")))
    rod_dates = [d for d in rod_dates if d]
    out["rod_checked"] = _iso(max(rod_dates)) if rod_dates else "missing"
    out["tax_checked"] = tax.get("checked_on") or "missing"
    prob = []
    if ph:
        prob.append(to_date(ph.get("checked_at")))
    if "probate_record" in death.get("record", []) or "sc_probate_notice" in death.get("record", []):
        prob.append(to_date(_g(row, "first_seen")))
    prob = [d for d in prob if d]
    out["probate_checked"] = _iso(max(prob)) if prob else "missing"
    obit = []
    ob = raw.get("obituary")
    if isinstance(ob, dict):
        obit.append(to_date(ob.get("pub_date") or ob.get("title_date")))
    hc = raw.get("heir_candidates")
    if isinstance(hc, list):
        obit += [to_date(c.get("source_date")) for c in hc
                 if isinstance(c, dict) and c.get("source_kind") == "obituary_survivor"]
    obit = [d for d in obit if d]
    out["obituaries_checked"] = _iso(max(obit)) if obit else "missing"
    return out


_LAWYER_UNMET = {"parcel": "lawyer_parcel", "legal_description": "lawyer_legal_description",
                 "deed_chain": "lawyer_deed_chain", "taxpayer": "lawyer_taxpayer", "heirs": "lawyer_heirs",
                 "rod_checked": "lawyer_rod_checked", "tax_checked": "lawyer_tax_checked",
                 "probate_checked": "lawyer_probate_checked", "obituaries_checked": "lawyer_obituaries_checked"}


def lawyer_unmet(ll: dict) -> list[str]:
    return [_LAWYER_UNMET[k] for k, v in ll.items() if v == "missing" and k in _LAWYER_UNMET]


# ---------------------------------------------------------------------------------------------
# rank (Fullmer: ripeness, margin vs fixed curative cost, value; ORDER, never a filter)
# ---------------------------------------------------------------------------------------------

def rank(row: Any, lane: str, tax: dict, sale: Optional[dict]) -> int:
    from .fullmer_rank import ARREARS_PRODUCTION_FILTER, CAD_STRONG, CAD_WEAK, MARGIN_COVERAGE_GOOD, \
        MARGIN_COVERAGE_MIN, delinq_ripeness_points
    raw = _raw(row)
    fm = raw.get("fullmer") if isinstance(raw.get("fullmer"), dict) else {}
    pts = 0.0
    years = tax.get("years") if tax.get("status") == "confirmed" else None
    if years is None and isinstance(fm.get("years_delinquent"), (int, float)):
        years = fm.get("years_delinquent")
    if years:
        pts += delinq_ripeness_points(float(years), _g(row, "state")) if years >= 2 else 8   # 0-40
    total = tax.get("total") if tax.get("status") == "confirmed" else (_num(fm.get("tax_arrears")) or 0)
    total = total or 0
    pts += 15 if total >= ARREARS_PRODUCTION_FILTER else 10 if total >= 5000 else 6 if total >= 1000 \
        else 3 if total >= 500 else 0                                                          # 0-15
    cov = _num(fm.get("margin_coverage"))
    pts += 15 if (cov or 0) >= MARGIN_COVERAGE_GOOD else 8 if (cov or 0) >= MARGIN_COVERAGE_MIN \
        else 4 if cov is None else 0                                                           # 0-15
    cad = _num(fm.get("cad_value"))
    pts += 10 if (cad or 0) >= CAD_STRONG else 5 if (cad or 0) >= CAD_WEAK else 0               # 0-10
    oc = fm.get("owner_count")
    pts += 5 if isinstance(oc, int) and 0 < oc <= 4 else 0                                     # 0-5
    pts += {"major": 6, "mid": 4, "thin": 1}.get(str(fm.get("liquidity") or ""), 2)            # 0-6
    if lane == "D" and sale and isinstance(sale.get("days"), int) and sale["days"] >= 0:
        d = sale["days"]
        pts += 9 if d <= 7 else 6 if d <= 14 else 3 if d <= 30 else 0                         # 0-9
    return int(max(0, min(100, round(pts))))


# ---------------------------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------------------------

def _contact_tier(phone: dict, mail: dict, unmet: list[str]) -> str:
    """A / B / C / D from the contact facts, once the lane's issue conditions hold."""
    link = phone.get("link")
    dnc = phone.get("dnc")
    blocked = dnc in ("registered", "do_not_dial", "not_owner_contact")
    if link in ("tied", "name_match_only") and not blocked:
        if dnc in (None, "not_scrubbed", "unverified"):
            unmet.append("dnc_not_scrubbed")
        return "A" if link == "tied" else "B"
    if blocked:
        unmet.append("dnc_registered")
    elif link == "other_record":
        unmet.append("phone_other_record")
    elif link == "not_owner":
        unmet.append("phone_not_owner")
    elif link == "unlinked":
        unmet.append("phone_unlinked")
    else:
        unmet.append("no_dialable_phone")
    if mail.get("status") == "ok":
        return "C"
    unmet.append({"missing": "mailing_missing", "other_record": "mailing_other_record",
                  "malformed": "mailing_malformed"}.get(mail.get("status"), "mailing_missing"))
    return "D"


def _mail_unmet(mail: dict) -> Optional[str]:
    return None if mail.get("status") == "ok" else {
        "missing": "mailing_missing", "other_record": "mailing_other_record",
        "malformed": "mailing_malformed"}.get(mail.get("status"), "mailing_missing")


def _checks(tax: dict, bk: dict, sale: Optional[dict], others: list[dict], raw: dict) -> list[dict]:
    out = []
    if tax.get("verdict"):
        out.append({"check": "county_tax_site", "result": tax["verdict"], "on": tax.get("checked_on"),
                    "source": tax.get("source") or ""})
    ph = record(raw, "probate_heir")
    if ph:
        out.append({"check": "death_index_and_deeds", "result": ph.get("verdict"),
                    "on": _iso(to_date(ph.get("checked_at"))), "source": ph.get("source") or ""})
    if bk.get("checked_on"):
        out.append({"check": "bankruptcy_court", "result": "active" if bk.get("active") else "none",
                    "on": bk["checked_on"], "source": "courtlistener"})
    if sale:
        if sale.get("last_seen"):
            out.append({"check": "sale_list", "result": "listed", "on": sale["last_seen"], "source": "row source"})
        if sale.get("rod_check"):
            out.append({"check": "register_of_deeds", "result": sale["rod_check"]["result"],
                        "on": sale["rod_check"]["on"], "source": "register of deeds"})
    out += [o for o in others if o["check"] != "foreclosure_rod" or not sale]
    return out


def _reason(lane: str, tier: str, row: Any, tax: dict, sale: Optional[dict], estate: dict,
            death: dict, others: list[dict], unmet: list[str]) -> str:
    county = str(_g(row, "county") or "the").strip()
    if tier == "D":
        hard = hard_unmet({"lane": lane, "unmet": unmet})
        first = hard[0] if hard else (unmet[0] if unmet else "issue_not_checked")
        return "Not ready: " + UNMET_WORDS.get(first, first) + "."
    if lane in ("A", "E") and tax.get("status") == "confirmed":
        n = tax.get("years") or 0
        s = (f"{county} County's tax site showed {_money(tax['total'])} past due over {n} "
             f"year{'s' if n != 1 else ''} on this parcel when checked on {tax.get('checked_on')}.")
    elif lane == "E" and others:
        o = others[0]
        s = f"The {o['check'].replace('_', ' ')} record was confirmed at {o.get('source') or 'the source'} on {o.get('on')}."
    elif lane == "B":
        who = "a personal representative" if estate.get("pr") else "heirs with a stated relation"
        s = (f"A probate record for the estate of the owner of record ({county} County) names {who}; "
             f"the notice was seen on {estate.get('seen_on')}.")
    elif lane == "C":
        kinds = ", ".join(k.replace("_", " ") for k in death.get("record", [])[:3])
        s = (f"Records say the owner of record died ({kinds}) and no open estate is on file; "
             f"the lawyer's intake list is complete.")
    elif lane == "D" and sale:
        when = (f"the upset-bid window is open until {sale.get('upset_deadline')}" if sale.get("window") == "upset_open"
                else f"the {sale.get('kind', 'sale').replace('_', ' ')} is set for {sale.get('sale_on')} "
                     f"({sale.get('days')} days)")
        s = f"In {county} County {when}; the source still listed it on {sale.get('last_seen')}."
    else:
        s = "The issue was checked at its source."
    if tier == "C" and lane == "B":
        tail = (" Mail the personal representative at the address the notice prints." if estate.get("pr_address")
                else " Mail the estate at the mailing address on record.")
    elif tier == "C" and lane == "C":
        tail = " Mail the heirs at the roll's care-of or mailing address; the attorney's packet is ready."
    else:
        tail = {"A": " The phone on file is tied to this property's record.",
                "B": " The phone matches the owner by name only: confirm you are speaking with the owner first.",
                "C": " Mail the owner at the mailing address on record."}.get(tier, "")
    return s + tail


def call_ready(row: Any, today: Optional[date] = None) -> dict:
    """The call-ready block for one row (dict board row or models.Listing). Pure; never raises on an
    odd row (an unexpected shape degrades to the short 'no lane' form with the error's class)."""
    today = today or today_utc()
    try:
        return _call_ready(row, today)
    except Exception as exc:  # noqa: BLE001 - one odd row never stops the board
        return {"v": VERSION, "lane": "", "tier": "D", "unmet": ["no_call_lane"],
                "error": type(exc).__name__}


def _call_ready(row: Any, today: date) -> dict:
    raw = _raw(row)
    kind = owner_kind(row)
    tax = tax_fact(row, today)
    tax_claim = property_tax_claim(row) or tax.get("verdict") is not None
    sale = sale_fact(row, today)
    death = death_fact(row)
    others = other_issue_checks(raw, today)
    bk = bankruptcy_fact(row, today)
    unmet: list[str] = []
    lane = ""
    tier = "D"
    extra: dict = {}

    phone = phone_fact(row)
    mail = mailing_fact(row)
    estate = estate_fact(row, today) if (death["record"] or death["weak"]) else {}

    if sale is not None and sale.get("original_county"):
        lane = "D"
        w = sale.get("window")
        if w == "closed":
            unmet.append("sale_window_closed")
        elif w == "missing":
            unmet.append("sale_date_missing")
        if sale.get("pulled"):
            unmet.append("sale_pulled")
        if sale.get("stayed") or bk.get("active"):
            unmet.append("sale_stayed")
        if sale.get("rod_ended"):
            unmet.append("foreclosure_ended")
        if sale.get("recheck_days") is None or sale["recheck_days"] > STATUS_RECHECK_MAX_DAYS:
            unmet.append("status_not_rechecked")
        if not unmet:
            tier = _contact_tier(phone, mail, unmet)
    elif death["record"] and kind != "government":
        if not has_property(row):
            unmet.append("no_property_on_row")
        elif death["tied"] is False:
            unmet.append("decedent_not_tied_to_parcel")
        elif death["tied"] is not True:
            unmet.append("decedent_tie_unproven")
        if conveyed_after_death(raw, death):
            unmet.append("conveyed_after_death")
        ll = lawyer_list(row, tax, death, estate)
        extra["lawyer"] = ll
        if estate.get("open") in ("open", "unknown"):
            # a probate record is on file: the estate's representative is the person to reach
            lane = "B"
            if estate["open"] == "unknown":
                unmet.append("estate_status_unknown")
            if not (estate.get("pr") or estate.get("heirs")):
                unmet.append("no_estate_contact")
            if not unmet:
                # by mail at the address the probate notice prints (no phone names the representative
                # on the board today), else the roll's care-of or the owner's mailing address
                if estate.get("pr_address") or estate.get("care_of") or mail.get("status") == "ok":
                    tier = "C"
                else:
                    unmet.append("mailing_missing")
        else:
            # no estate on file: the title sits in the dead owner's name (the attorney's work)
            lane = "C"
            unmet += lawyer_unmet(ll)
            if not unmet:
                if estate.get("care_of") or mail.get("status") == "ok":
                    tier = "C"
                else:
                    unmet.append(_mail_unmet(mail) or "mailing_missing")
    elif death["weak"] and kind == "individual" and tax_claim:
        lane = "B"
        unmet += ["owner_maybe_deceased", "death_not_on_record"]
        extra["lawyer"] = lawyer_list(row, tax, death, estate)
    elif kind == "government":
        unmet.append("government_owner")
    elif tax_claim:
        if tax["status"] != "confirmed":
            unmet.append(tax["status"])
        if bk.get("active"):
            unmet.append("in_bankruptcy")
        if kind == "individual" and not death["weak"]:
            # the lane is the contact path (a dialable phone: A; none: E, mail); the tier is whether
            # the issue and the record checks hold
            m = _mail_unmet(mail)
            if m:
                unmet.append(m)
            dialable = phone.get("link") in ("tied", "name_match_only") and \
                phone.get("dnc") not in ("registered", "do_not_dial", "not_owner_contact")
            if dialable:
                lane = "A"
                if not unmet:
                    tier = _contact_tier(phone, mail, unmet)
            else:
                lane = "E"
                hard = list(unmet)
                if phone.get("dnc") in ("registered", "do_not_dial", "not_owner_contact"):
                    unmet.append("dnc_registered")
                else:
                    unmet.append({"other_record": "phone_other_record", "not_owner": "phone_not_owner",
                                  "unlinked": "phone_unlinked"}.get(phone.get("link"), "no_dialable_phone"))
                tier = "C" if not hard else "D"
        elif kind in ("entity", "trust"):
            lane = "E"
            unmet.append("owner_not_person")
            m = _mail_unmet(mail)
            if m:
                unmet.append(m)
            if tax["status"] == "confirmed" and not bk.get("active") and not m:
                tier = "C"
                unmet.remove("owner_not_person")     # a mail lead: the entity is written to, not called
        else:
            lane = "A"
            unmet.append("owner_unknown")
    elif others and kind != "government":
        lane = "E"
        m = _mail_unmet(mail)
        if m:
            unmet.append(m)
        else:
            tier = "C"
    if not lane:
        if not unmet:
            unmet.append("no_call_lane")
        return {"v": VERSION, "lane": "", "tier": "D", "unmet": unmet}

    seen: set = set()
    unmet = [u for u in unmet if not (u in seen or seen.add(u))]
    out = {"v": VERSION, "lane": lane, "tier": tier, "rank": rank(row, lane, tax, sale),
           "reason": _reason(lane, tier, row, tax, sale, estate, death, others, unmet),
           "unmet": unmet, "checks": _checks(tax, bk, sale, others, raw),
           "phone": phone.get("link"), "dnc": phone.get("dnc") if phone.get("link") != "none" else None,
           "mail": mail.get("status"), "as_of": today.isoformat()}
    facts: dict = {}
    if tax.get("verdict"):
        facts.update({"tax_verdict": tax["verdict"], "years_delinquent": tax.get("years"),
                      "total_delinquent": tax.get("total"), "tax_checked_on": tax.get("checked_on")})
    if sale:
        facts.update({k: sale.get(k) for k in ("window", "sale_on", "upset_deadline", "days", "last_seen")
                      if sale.get(k) is not None})
    if death["record"] or death["weak"]:
        facts["death_on"] = death["record"] or death["weak"]
        if estate:
            facts["estate"] = estate.get("open")
            facts["heir_candidates"] = estate.get("heirs")
    if facts:
        out["facts"] = facts
    out.update(extra)
    return out


def stamp_board(listings: Iterable[Any], today: Optional[date] = None) -> dict:
    """raw['call_ready'] on every row (in place; idempotent; rows are never removed). Returns counts
    {rows, by_lane_tier: {"A/A": n, ...}, errors}."""
    today = today or today_utc()
    counts: dict = {"rows": 0, "by_lane_tier": {}, "errors": 0}
    for li in listings:
        counts["rows"] += 1
        blk = call_ready(li, today)
        raw = _g(li, "raw")
        if not isinstance(raw, dict):
            raw = {}
            if isinstance(li, dict):
                li["raw"] = raw
            else:
                li.raw = raw
        raw["call_ready"] = blk
        if blk.get("error"):
            counts["errors"] += 1
        k = f"{blk.get('lane') or '-'}/{blk.get('tier')}"
        counts["by_lane_tier"][k] = counts["by_lane_tier"].get(k, 0) + 1
    return counts


def unmet_words(codes: Iterable[str]) -> list[str]:
    return [UNMET_WORDS.get(c, c) for c in codes]


#: codes listed for the closer's information that never lower a tier: the DNC scrub is a dial-time
#: step; in the mail lane (E) the missing phone is why it is the mail lane
INFORMATIONAL = frozenset({"dnc_not_scrubbed"})
MAIL_LANE_INFO = frozenset({"no_dialable_phone", "phone_unlinked", "phone_other_record", "phone_not_owner",
                            "dnc_registered"})


def hard_unmet(blk: dict) -> list[str]:
    """The unmet codes that keep the row from a better tier (informational codes left out)."""
    skip = INFORMATIONAL | (MAIL_LANE_INFO if blk.get("lane") == "E" else frozenset())
    return [u for u in blk.get("unmet") or [] if u not in skip]
