"""NC Register-of-Deeds distress recordings via the Logan "The Lookup" adapter.

Closes the NC ROD gap for the Logan counties whose pick-list loads
(Transylvania, McDowell, Mitchell). Sweeps recent recordings browserless/free
(rod/logan.py) and emits TYPED leads:
  * FCL / LIS/P / S/TR / N/SUB / R/TR  -> LIS_PENDENS      (pre-foreclosure)
  * TR/D / TD / C/TR/D / SHF/D         -> FORECLOSURE_SALE (post-sale deed)
  * D/DIST / ADM/DT / EXEC/DT          -> PROBATE_NOTICE   (+ relationship_signal)
  * LIEN / JUDGMENT                    -> TAX_LIEN         (financial)

Each lead carries grantor (defendant), instrument#, and the legal description;
the address waterfall + parcel inventory resolve a situs from the owner name.
(Spartanburg uses different codes + a broken loader -> not wired here yet.)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...rod import logan

try:  # reuse the shared business-name filter when importable
    from ...enrichment_address_backfill import _BUSINESS_STOPWORDS
except Exception:  # pragma: no cover - defensive fallback, never raise on import
    _BUSINESS_STOPWORDS = {
        "llc", "inc", "corp", "corporation", "company", "co", "ltd", "lp",
        "llp", "trust", "trustee", "estate", "of", "the", "and",
    }

_LOOKBACK_DAYS = 60

# Logan's "Reverse Party" column frequently carries a book-page reference token
# (e.g. "DOC 1186 608", "CRP 1538 543") instead of a name. Such tokens are never
# a defendant -> reject so they don't poison the owner-name backfill.
_JUNK_PARTY_RE = re.compile(r"^(?:DOC|CRP|BK|PG|DEED)\s+\d+", re.I)

# Institutional keywords that mark a party as a lender / trustee / servicer /
# government body (a NON-owner). Complements _BUSINESS_STOPWORDS, which is too
# thin for distress recordings. A clean person name ("CLARK GREGORY B.") carries
# none of these and passes through.
_INSTITUTION_WORDS = {
    "bank", "mortgage", "services", "service", "authority", "financial",
    "finance", "housing", "federal", "credit", "association", "assn", "fund",
    "capital", "loan", "national", "savings", "bancorp", "partners", "ptnrp",
    "partnership", "holdings", "lending", "servicing", "revocable", "living",
    "irrevocable", "foundation", "church", "county", "city", "department",
    "revenue",
}


def _is_junk_party(name: str | None) -> bool:
    return bool(_JUNK_PARTY_RE.match((name or "").strip()))


def _is_institutional(name: str | None) -> bool:
    """True if the party reads as a business/lender/trustee/government, not a
    person. Defensive: empty/None -> True (treated as non-owner, skipped)."""
    s = (name or "").strip()
    if not s:
        return True
    toks = set(re.sub(r"[^a-z\s]", " ", s.lower()).split())
    return bool(toks & _BUSINESS_STOPWORDS) or bool(toks & _INSTITUTION_WORDS)


def _split_parties(s: str | None) -> list[str]:
    """rod/logan.py now joins every party sharing a role with '; ' (a
    multi-grantor/heir instrument can have many) -- split back out so each
    name is filtered on its OWN merits, never on the whole joined string.
    A single plain name (no '; ') round-trips through this unchanged."""
    return [p.strip() for p in (s or "").split("; ") if p.strip()]


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        key = n.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _resolve_defendant(doc) -> str | None:
    """Pick the real owner(s) from a Logan record, never a junk/lender token.

    Logan puts the searched/reverse parties in grantor/grantee in either order,
    and on distress recordings one side is the homeowner while the other is the
    lender/trustee or a junk book-page token ("DOC 1186 608"). An instrument
    can also name SEVERAL people on the owner side (co-owners, multiple heirs)
    -- rod/logan.py's `grantor`/`grantee` are "; "-joined lists of every
    distinct name seen for that role, not a single name. Behaviour by
    instrument class:
      * deed codes (TR/D, C/TR/D, SHF/D, TD) and lis-pendens codes (S/TR, FCL,
        N/SUB, ...): keep EVERY party (either side) that looks like a person,
        filtered name-by-name so one institutional co-party (a trustee, an
        HOA) can't mask a real co-owner's name elsewhere in the same list;
        if none looks like a person (all lender/junk — common on S/TR & FCL)
        emit None rather than a guaranteed-unresolvable lender name.
      * probate / lien codes: the grantor side IS the owner (decedent/estate/
        heirs), so keep every grantor name as-is per the spartan_weekly_legals
        pattern (defendant=decedent), only rejecting junk book-page tokens —
        never institutional-filtered, so "THE UNKNOWN HEIRS OF ..." and an
        "... EST" decedent name are never thrown away for containing stopword
        tokens like "the"/"of".
    Result is always real name(s) or None, never a BK/PG/DOC structural token.
    """
    code = (doc.doc_type or "").strip().upper()
    if code in _SALE or code in _PRE:
        candidates = _split_parties(doc.grantor) + _split_parties(doc.grantee)
        keepers = [c for c in candidates if not _is_junk_party(c) and not _is_institutional(c)]
        keepers = _dedupe(keepers)
        return "; ".join(keepers) if keepers else None
    # probate / lien (or anything else): owner side is the grantor; drop only junk.
    names = [g for g in _split_parties(doc.grantor) if not _is_junk_party(g)]
    names = _dedupe(names)
    return "; ".join(names) if names else None

_PRE = {"FCL", "LIS/P", "S/TR", "N/SUB", "R/TR"}
_SALE = {"TR/D", "TD", "C/TR/D", "SHF/D"}
_PROBATE = {"D/DIST", "DEED/DIST", "ADM/DT", "EXEC/DT"}
_LIEN = {"LIEN", "LN", "LIEN000", "JUDGMENT", "JGMT", "JUDG", "JUDGM"}


def _classify(doc_type: str) -> tuple[ListingType, str] | None:
    s = (doc_type or "").strip().upper()
    if s in _PRE:
        return ListingType.LIS_PENDENS, "pre_foreclosure"
    if s in _SALE:
        return ListingType.FORECLOSURE_SALE, "foreclosure_deed"
    if s in _PROBATE:
        return ListingType.PROBATE_NOTICE, "probate"
    if s in _LIEN:
        return ListingType.TAX_LIEN, "lien"
    return None


def _to_listing(doc, slug: str, source_url: str) -> Listing | None:
    cls = _classify(doc.doc_type)
    if cls is None:
        return None
    lt, kind = cls
    rec = doc.recorded_date.strftime("%Y-%m-%d") if doc.recorded_date else "unknown date"
    desc = f"{doc.doc_type} recorded {rec}: {(doc.grantor or '?').strip()}"
    raw: dict = {"rod": {"doc_type": doc.doc_type, "grantor": doc.grantor,
                         "grantee": doc.grantee, "book": doc.book, "page": doc.page,
                         "instrument": doc.instrument_no, "recorded": rec},
                 "logan_rod": True}
    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": doc.doc_type,
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    return Listing(
        source=slug, source_url=source_url,
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state=doc.state, county=doc.county,
        defendant=_resolve_defendant(doc),
        case_number=(doc.instrument_no or "").strip() or None,
        legal_description=(doc.notes or "").strip() or None,
        description=desc,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


class NCRodLogan(BaseScraper):
    slug = "counties_nc.nc_rod_logan"
    name = "NC Register of Deeds (Logan 'The Lookup' — foreclosure/lien/probate)"
    category = "register_of_deeds"
    expected_min_count = 0   # small counties; weekly distress volume varies
    requires_render = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        # Bank rows as they are collected: if the soft timeout fires,
        # base_scraper ships self.partial instead of discarding the run.
        out = self.partial
        for (state, county), host in logan.LOGAN_COUNTIES.items():
            src = f"{host}/index.php"
            for d in await logan.discover_recent_nods(state, county, days_back=_LOOKBACK_DAYS):
                li = _to_listing(d, self.slug, src)
                if li:
                    out.append(li)
        return out
