"""The names an estimate's source can go by. A price source's own estimates
begin with its name (`numista:N#123 XF`, `melt:silver @ 0.98/g`); anything
else was typed in. Nothing here imports the rest of the app, so the model,
the schemas, and the pricing service can all read the one list."""

ADAPTERS = ("melt", "numista", "pcgs", "comps")
MANUAL = "manual"
KEYS = (*ADAPTERS, MANUAL)


def key_of(source: str) -> str:
    """The key an estimate is grouped under: its price source's name, or
    `manual` for every typed-in value, whatever its source text says."""
    head = (source or "").split(":", 1)[0]
    return head if head in ADAPTERS else MANUAL
