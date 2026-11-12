"""'Layup' quiet-title candidates: simple cases with no court-action tangle, ranked by plain rules.

A board row is a candidate when ALL of these hold (each rule is printed with the list):
  R1 county and state match (Buncombe NC first);
  R2 the tax_lien ledger entry for the row is `confirmed` with an amount delinquent in at least
     two COMPLETED levy years (interest date passed; the current year's bill never counts);
     a verdict from the PTS Cloud verifier is ignored (a known wrong-parcel defect), and an
     entry whose own PIN differs from the row's is ignored;
  R3 no bankruptcy or foreclosure signal: none of FORECLOSURE_SIGNALS in the row's listing type,
     signal stack or distress stack, no raw.bankruptcy block, and no `confirmed` verdict in the
     bankruptcy_stay or foreclosure_rod ledgers;
  R4 heirs or estate wording on the county roll (the row's owner name, or raw.heir_estate);
  R5 a single parcel: not a condominium unit (a lettered PIN extension or property kind condo),
     no fused-key QA flag (FUSED_FLAGS: one assessor row fanned out across parcels), and no other
     board row on the same PIN with a different house-numbered address. owner_record_mismatch
     (CAUTION_FLAGS) is printed as a caution, or excluded with strict=True.
Improved or vacant does not matter. RANK: the heirs claim `confirmed` in the probate_heir ledger
first, then the smaller completed-years balance first.

Pure: the caller streams the board (board_stream.iter_board_rows) and passes the ledgers in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

from .names import roll_markers
from .taxyears import is_completed

FORECLOSURE_SIGNALS = {"foreclosure_sale", "lis_pendens", "sheriff_sale", "hoa_sale", "court_sale", "upset_bid",
                       "auction", "reo", "tax_sale", "tax_sale_overage", "bankruptcy", "bankruptcy_stay",
                       "foreclosure", "trustee_sale"}
#: QA flags that mean one board key fuses several parcels (an assessor row fanned out across parcels)
FUSED_FLAGS = {"gis_row_shared", "anchor_shared_across_parcels"}
#: the board row's address-based assessor join names a different owner: the row's address may be
#: another parcel's (often the heirs parcel's MAILING address). The parcel itself is still one PIN,
#: so by default this is printed as a caution; strict=True excludes it like a fused key.
CAUTION_FLAGS = {"owner_record_mismatch"}
IGNORED_TAX_VERIFIERS = {"tax_lien_ptscloud"}


def pin_digits(v: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(v or "")).upper()


def pin10(v: Any) -> str:
    return re.sub(r"\D", "", str(v or ""))[:10]


def house_numbered(addr: Any) -> Optional[str]:
    s = re.sub(r"\s+", " ", str(addr or "").upper()).strip()
    m = re.match(r"^(\d+)\s+(.+)$", s)
    return s if m and int(m.group(1)) > 0 else None


@dataclass
class TaxFinding:
    ok: bool
    reason: str = ""
    years: list[int] = field(default_factory=list)
    balance: float = 0.0
    pin: Optional[str] = None
    verifier: str = ""


def tax_finding(entry: Optional[dict], today: date, state: str = "NC") -> TaxFinding:
    """R2 on one tax_lien ledger entry."""
    if not entry:
        return TaxFinding(False, "no tax_lien ledger entry")
    lat = entry.get("latest") or {}
    ver = str(lat.get("verifier") or "")
    if ver in IGNORED_TAX_VERIFIERS:
        return TaxFinding(False, f"tax verdict from {ver} (ignored)", verifier=ver)
    if lat.get("verdict") != "confirmed":
        return TaxFinding(False, f"tax verdict {lat.get('verdict')}", verifier=ver)
    ev = lat.get("evidence") or {}
    dby = ev.get("delinquent_by_year") or {}
    years, bal = [], 0.0
    for y, amt in dby.items():
        try:
            yi, a = int(y), float(amt or 0)
        except (TypeError, ValueError):
            continue
        if a > 0 and is_completed(yi, today, state):
            years.append(yi)
            bal += a
    years.sort()
    if len(years) < 2:
        return TaxFinding(False, f"confirmed for {len(years)} completed levy year(s)", years, round(bal, 2),
                          ev.get("pin"), ver)
    return TaxFinding(True, "", years, round(bal, 2), ev.get("pin"), ver)


def row_signals(row: dict) -> set[str]:
    raw = row.get("raw") or {}
    out = set()
    for blk in ("signal_stack", "distress_stack"):
        sigs = (raw.get(blk) or {}).get("signals") if isinstance(raw.get(blk), dict) else None
        if isinstance(sigs, list):
            out |= {str(s) for s in sigs}
    lt = str(row.get("listing_type") or "")
    if lt:
        out.add(lt)
    return out


def heirs_words(row: dict) -> list[str]:
    raw = row.get("raw") or {}
    words = roll_markers(row.get("owner_name"))
    he = raw.get("heir_estate")
    if isinstance(he, dict):
        for w in roll_markers(he.get("owner_of_record")):
            if w not in words:
                words.append(w)
    elif isinstance(he, str):
        for w in roll_markers(he):
            if w not in words:
                words.append(w)
    return words


def condo_unit(row: dict) -> bool:
    if "condo" in str(row.get("property_kind") or "").lower():
        return True
    p = pin_digits(row.get("parcel_id"))
    return len(p) == 15 and bool(re.search(r"[A-Z]", p[10:]))


@dataclass
class Candidate:
    pin: str
    address: str
    tax: TaxFinding
    heirs: list[str]
    heirs_verdict: Optional[str]
    signals: list[str]
    county: str = ""
    cautions: list[str] = field(default_factory=list)

    def rank_key(self) -> tuple:
        return (0 if self.heirs_verdict == "confirmed" else 1, self.tax.balance, self.pin)

    def signal_list(self) -> str:
        bits = [f"tax_lien confirmed for {', '.join(map(str, self.tax.years))} (${self.tax.balance:,.2f} delinquent "
                f"in those years)",
                f"heirs wording on the roll ({', '.join(self.heirs)})",
                f"probate_heir ledger: {self.heirs_verdict or 'no entry'}"]
        other = sorted(s for s in self.signals if s not in ("tax_lien",))
        if other:
            bits.append("other board signals: " + ", ".join(other))
        if self.cautions:
            bits.append("caution: " + ", ".join(self.cautions) + " (the board row's address may be another "
                        "parcel's; the intake sheet resolves the parcel by PIN)")
        return "; ".join(bits)


class LayupScan:
    """Feed board rows one at a time (add_row), then call candidates()."""

    def __init__(self, *, county: str, state: str, today: date, find_tax, find_probate=None,
                 find_confirmed_court=None, strict: bool = False) -> None:
        self.county, self.state, self.today = county.lower(), state.upper(), today
        self.strict = strict
        self.find_tax = find_tax                    # row -> ledger entry or None
        self.find_probate = find_probate or (lambda row: None)          # row -> verdict or None
        self.find_court = find_confirmed_court or (lambda row: [])      # row -> confirmed court signals
        self.rows_seen = 0
        self.in_county = 0
        self.dropped: dict[str, int] = {}
        self._cand: dict[str, Candidate] = {}
        self._addrs: dict[str, set[str]] = {}
        self._blocked: dict[str, str] = {}

    def _drop(self, why: str) -> None:
        self.dropped[why] = self.dropped.get(why, 0) + 1

    def add_row(self, row: dict) -> None:
        self.rows_seen += 1
        if str(row.get("county") or "").strip().lower() != self.county or \
                str(row.get("state") or "").strip().upper() != self.state:
            return
        self.in_county += 1
        p10 = pin10(row.get("parcel_id"))
        if len(p10) != 10:
            return self._drop("R1 no 10-digit PIN on the row")
        a = house_numbered(row.get("street_address"))
        if a:
            self._addrs.setdefault(p10, set()).add(a)
        sigs = row_signals(row)
        raw = row.get("raw") or {}
        if sigs & FORECLOSURE_SIGNALS or (isinstance(raw.get("bankruptcy"), dict) and raw.get("bankruptcy")):
            self._blocked[p10] = "R3 bankruptcy or foreclosure signal on a row of this PIN"
            return self._drop("R3 bankruptcy or foreclosure signal")
        court = self.find_court(row)
        if court:
            self._blocked[p10] = "R3 confirmed " + ", ".join(court)
            return self._drop("R3 confirmed bankruptcy/foreclosure verdict")
        words = heirs_words(row)
        if not words:
            return self._drop("R4 no heirs/estate wording")
        if condo_unit(row):
            self._blocked[p10] = "R5 condominium unit"
            return self._drop("R5 condominium unit")
        qa = set((raw.get("qa_flags") or []) if isinstance(raw.get("qa_flags"), list) else [])
        fused = qa & (FUSED_FLAGS | (CAUTION_FLAGS if self.strict else set()))
        if fused:
            self._blocked[p10] = "R5 fused-key flag " + ", ".join(sorted(fused))
            return self._drop("R5 fused-key QA flag " + ", ".join(sorted(fused)))
        cautions = sorted(qa & CAUTION_FLAGS)
        tf = tax_finding(self.find_tax(row), self.today, self.state)
        if not tf.ok:
            return self._drop("R2 " + tf.reason)
        if tf.pin and pin10(tf.pin) != p10:
            return self._drop("R2 ledger entry holds another PIN")
        pin = pin_digits(tf.pin) if tf.pin else pin_digits(row.get("parcel_id"))
        hv = self.find_probate(row)
        c = self._cand.get(p10)
        if c is None:
            self._cand[p10] = Candidate(pin=pin, address=str(row.get("street_address") or ""), tax=tf, heirs=words,
                                        heirs_verdict=hv, signals=sorted(sigs), county=self.county,
                                        cautions=cautions)
        else:
            c.signals = sorted(set(c.signals) | sigs)
            c.cautions = sorted(set(c.cautions) | set(cautions))
            c.heirs = sorted(set(c.heirs) | set(words))
            if hv == "confirmed":
                c.heirs_verdict = hv

    def candidates(self) -> list[Candidate]:
        out = []
        for p10, c in self._cand.items():
            if p10 in self._blocked:
                self._drop(self._blocked[p10] + " (another row of the PIN)")
                continue
            if len(self._addrs.get(p10, set())) > 1:
                self._drop("R5 several house-numbered addresses on one PIN")
                continue
            out.append(c)
        return sorted(out, key=Candidate.rank_key)


def why_ranked(c: Candidate, i: int) -> str:
    h = ("heirs claim confirmed in the probate_heir ledger" if c.heirs_verdict == "confirmed"
         else f"heirs claim not confirmed in the probate_heir ledger ({c.heirs_verdict or 'no entry'})")
    return (f"rank {i}: {h}; completed-years balance ${c.tax.balance:,.2f} "
            f"({len(c.tax.years)} completed years delinquent); passed R1-R5")


def iter_candidates_text(cands: Iterable[Candidate], situs: dict[str, str]) -> Iterable[str]:
    for i, c in enumerate(cands, 1):
        addr = situs.get(c.pin) or situs.get(pin10(c.pin)) or f"{c.address} (address on the board; situs not looked up)"
        yield f"{i:>2}. PIN {c.pin} | {addr}"
        yield f"    signals: {c.signal_list()}"
        yield f"    why: {why_ranked(c, i)}"
