"""Columns this pipeline must never keep, whatever a county layer offers.

Some county GIS layers have exposed personal identifiers on a public layer (Lincoln NC's
taxpayer table carried TCSSN1/TCSSN2, with TCDLC1/TCDLC2 beside them). Enrichers that ask a
layer for every column (outFields=*) and keep the whole attribute bag (raw['gis_attrs_full'])
would have stored such a column silently. `drop_sensitive` removes any attribute whose NAME looks
like one of these identifiers at the moment the response is read, before anything is stored, so a
county adding a column later can not put it on a lead.

The name test is deliberately NOT a bare substring test: "ssn" sits inside CLASSNAME, a common
land-use column, and dropping that would blind the land-use enrichers.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

FORBIDDEN_FIELD = re.compile(
    r"(?<![a-z])ssn(?![a-z])|tcssn|social_?sec"
    r"|drivers?_?lic|(?<![a-z])dl_?num(?![a-z])|tcdlc"
    r"|date_?of_?birth|birth_?date|(?<![a-z])dob(?![a-z])",
    re.I,
)


def is_sensitive_field(name: Any) -> bool:
    return bool(FORBIDDEN_FIELD.search(str(name)))


def drop_sensitive(attrs: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `attrs` without any column whose name looks like an SSN, licence or birth date."""
    return {k: v for k, v in attrs.items() if not is_sensitive_field(k)}
