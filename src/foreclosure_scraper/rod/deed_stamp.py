"""NC deed-tax-stamp → sold-price conversion utilities.

NC charges $1 of excise tax per $500 of consideration on real-property
transfers. A "Trustee's Deed Upon Sale" recording (the document that
transfers the property to the winning bidder at a foreclosure auction)
includes the deed-tax stamp — multiply by 500 to recover the hammer
price.

This module is the canonical place to convert a recorded-document
text blob into a sold price. It's used (or will be used) by:
  * Future post-sale extraction in rod/aumentum / rod/cott / rod/cchs
    when those modules add 'TRUSTEE'S DEED UPON SALE' to their
    discover_recent_* sweeps.
  * Permitium / Manatron portals when their text gets fed back through.
"""
from __future__ import annotations

import re
from typing import Optional

# NC excise tax line patterns — vendors vary in exact label.
EXCISE_TAX_RE = re.compile(
    r"(?:excise\s+tax|stamp(?:ed)?\s+tax|consideration\s+stamp)\s*[:=]?\s*"
    r"\$\s*([\d,]+(?:\.\d{2})?)",
    re.I,
)
# Direct consideration line ("CONSIDERATION: $123,456.00")
CONSIDERATION_RE = re.compile(
    r"consideration\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I,
)


# Plausible consideration band. Reject parser misfires (a "stamp" that is
# really a zip, doc number, or phone) and nominal related-party transfers
# ($1 deeds) before they can pollute the sold-comp pool that feeds ARV.
_MIN_PRICE = 100.0
_MAX_PRICE = 10_000_000.0


def _plausible(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return v if _MIN_PRICE <= v <= _MAX_PRICE else None


def consideration_from_fields(
    consideration: Optional[float], stamp: Optional[float]
) -> Optional[float]:
    """Best sold price from a recorded deed's STRUCTURED fields (as already
    parsed by the ROD vendor adapters). Prefer an explicit consideration;
    otherwise recover it from the NC excise stamp (stamp × 500). Both pass the
    plausibility guard, so a misfired stamp or a nominal transfer returns None
    instead of injecting a garbage sold comp into the ARV pool.

    This is the canonical structured converter the adapters (aumentum, cchs, …)
    should use instead of an inline, unguarded `stamp * 500`.
    """
    try:
        c = float(consideration) if consideration is not None else None
    except (TypeError, ValueError):
        c = None
    v = _plausible(c)
    if v is not None:
        return v
    try:
        s = float(stamp) if stamp is not None else None
    except (TypeError, ValueError):
        s = None
    if s is not None:
        return _plausible(round(s * 500.0, 2))
    return None


def sold_price_from_stamp(text: str) -> Optional[float]:
    """NC deed tax: $1 per $500 of consideration. Stamp_amount × 500 =
    sold price. Prefer explicit CONSIDERATION line if present.

    Returns None when:
      * No matching pattern in `text`
      * Implausible result (<$100 or >$10M) — likely a parser misfire
        (catching a phone number, zip, or stamp on a related-party
        transfer).
    """
    m = CONSIDERATION_RE.search(text)
    if m:
        try:
            v = _plausible(float(m.group(1).replace(",", "")))
            if v is not None:
                return v
        except ValueError:
            pass
    m = EXCISE_TAX_RE.search(text)
    if m:
        try:
            return _plausible(float(m.group(1).replace(",", "")) * 500)
        except ValueError:
            pass
    return None
