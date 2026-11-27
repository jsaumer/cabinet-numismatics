"""Catalog references as they are stored and matched: one written form per
catalog that has one. Today that is Numista, whose type number arrives as
`1234`, `N#1234`, `N# 1234`, `N-1234`, or `n1234` and is kept as `N#1234`,
so pricing, the duplicate check, checklists, and "Add a run" all read the
same text."""

import re

NUMISTA = "numista"
NUMISTA_REF_ERROR = "A Numista reference is the type's number, written N#1234 or 1234"

# Leading zeros go, so N#0012 and N#12 are one reference; N#0 is none.
_NUMISTA_REF = re.compile(r"^\s*(?:n\s*[#-]?\s*)?0*([1-9]\d{0,8})\s*$", re.IGNORECASE)


def numista_ref(code: str) -> str | None:
    """`N#1234` from any accepted spelling; None when it isn't a type number."""
    match = _NUMISTA_REF.match(code or "")
    return f"N#{match.group(1)}" if match else None


def stored_form(catalog: str, code: str) -> tuple[str, str]:
    """A reference as the item form saves it: the catalog trimmed and in
    lower case, a Numista code as `N#<digits>`. A Numista code that doesn't
    read as a number comes back trimmed (a row from before the rule), so a
    lookup never raises; input models refuse it (`schemas.CatalogRefIn`)."""
    catalog, code = (catalog or "").strip().lower(), (code or "").strip()
    if catalog == NUMISTA:
        code = numista_ref(code) or code
    return catalog, code
