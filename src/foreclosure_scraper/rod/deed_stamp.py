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
            v = float(m.group(1).replace(",", ""))
            if 100 <= v <= 10_000_000:
                return v
        except ValueError:
            pass
    m = EXCISE_TAX_RE.search(text)
    if m:
        try:
            stamp = float(m.group(1).replace(",", ""))
            v = stamp * 500
            if 100 <= v <= 10_000_000:
                return v
        except ValueError:
            pass
    return None
