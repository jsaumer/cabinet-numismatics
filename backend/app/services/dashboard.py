"""Customisable dashboard layout (roadmap Phase 7, P10).

One ordered list of widget instances, stored under the `dashboard_layout`
setting (see `app_settings.py`). A widget is `{id, type, size, title,
options}`; the type table (`WIDGET_OPTIONS`, `DEFAULT_SIZES`) is the single
source of truth the frontend's registry mirrors.

Reading is lenient (`normalize_for_read`): an unknown widget type is dropped,
a missing option takes its default, and an invalid stored value is replaced
by its default, so a release that retires a widget or narrows an option
never breaks the page. Writing is strict (`validate_widgets`, used by
`PUT`): any problem raises `ValueError` naming the widget id and, where it
applies, the option.
"""

import copy
import re
from collections.abc import Callable

CURRENT_VERSION = 1
MAX_WIDGETS = 40
ID_RE = re.compile(r"^[a-z0-9-]{1,36}$")
SIZES = ("full", "half", "third")

# Each option: {"choices": [...]} | {"kind": "int", "min", "max"}
# | {"kind": "str_or_null", "max"} | {"kind": "int_or_null"}, plus "default".
WIDGET_OPTIONS: dict[str, dict[str, dict]] = {
    "setup": {},
    "value_summary": {},
    "value_history": {
        "months": {"choices": [12, 24, 60, 120], "default": 24},
    },
    "breakdown": {
        "dimension": {
            "choices": ["country", "type", "decade", "grade", "tag", "acquisition_year"],
            "default": "country",
        },
        "measure": {"choices": ["value", "count", "cost"], "default": "value"},
        "top_n": {"kind": "int", "min": 3, "max": 20, "default": 8},
        "tag": {"kind": "str_or_null", "max": 64, "default": None},
        "set_id": {"kind": "int_or_null", "default": None},
    },
    "notes_by_signature": {},
    "unrealized_movers": {
        "top_n": {"kind": "int", "min": 3, "max": 25, "default": 5},
    },
    "realized_gains": {
        "top_n": {"kind": "int", "min": 3, "max": 50, "default": 20},
    },
    "counts": {},
    "recent_additions": {
        "count": {"kind": "int", "min": 3, "max": 20, "default": 6},
    },
    "wishlist": {
        "mode": {"choices": ["priority", "reached"], "default": "priority"},
        "count": {"kind": "int", "min": 3, "max": 20, "default": 6},
    },
    "fancy_serials": {
        "count": {"kind": "int", "min": 3, "max": 20, "default": 6},
    },
    "checklists": {
        "count": {"kind": "int", "min": 3, "max": 20, "default": 6},
    },
    "stack": {
        "metal": {"choices": ["all", "gold", "silver", "platinum", "palladium"], "default": "all"},
        "tag": {"kind": "str_or_null", "max": 64, "default": None},
    },
    "pricing_coverage": {},
    "stale_estimates": {
        "days": {"choices": [7, 30, 90, 365], "default": 30},
        "count": {"kind": "int", "min": 3, "max": 20, "default": 6},
    },
    "source_disagreements": {
        "count": {"kind": "int", "min": 3, "max": 20, "default": 5},
    },
    "estimate_accuracy": {},
    "backup_status": {},
    "alerts_status": {},
    "market_data": {},
    "trash": {
        "count": {"kind": "int", "min": 3, "max": 20, "default": 5},
    },
}

DEFAULT_SIZES: dict[str, str] = {
    "setup": "full",
    "value_summary": "full",
    "value_history": "full",
    "breakdown": "third",
    "notes_by_signature": "full",
    "unrealized_movers": "full",
    "realized_gains": "full",
    "counts": "third",
    "recent_additions": "half",
    "wishlist": "half",
    "fancy_serials": "half",
    "checklists": "half",
    "stack": "half",
    "pricing_coverage": "third",
    "stale_estimates": "half",
    "source_disagreements": "half",
    "estimate_accuracy": "half",
    "backup_status": "third",
    "alerts_status": "third",
    "market_data": "third",
    "trash": "third",
}


def _widget(wid: str, wtype: str, **options) -> dict:
    return {
        "id": wid,
        "type": wtype,
        "size": DEFAULT_SIZES[wtype],
        "title": None,
        "options": {**{k: v["default"] for k, v in WIDGET_OPTIONS[wtype].items()}, **options},
    }


# Today's fixed dashboard, reproduced as the default layout.
DEFAULT_LAYOUT: dict = {
    "version": CURRENT_VERSION,
    "widgets": [
        _widget("d-1", "setup"),
        _widget("d-2", "value_summary"),
        _widget("d-3", "value_history", months=24),
        _widget("d-4", "breakdown", dimension="country", measure="value"),
        _widget("d-5", "breakdown", dimension="tag", measure="value"),
        _widget("d-6", "breakdown", dimension="decade", measure="count"),
        _widget("d-7", "breakdown", dimension="acquisition_year", measure="count"),
        _widget("d-8", "breakdown", dimension="grade", measure="count"),
        _widget("d-9", "notes_by_signature"),
        _widget("d-10", "unrealized_movers"),
        _widget("d-11", "realized_gains"),
    ],
}


def default_layout() -> dict:
    return copy.deepcopy(DEFAULT_LAYOUT)


# Migration hook: {from_version: fn(layout_dict) -> layout_dict}. Empty today;
# a future schema change adds an entry here rather than a new code path.
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def _migrate(stored: dict) -> dict:
    data = dict(stored)
    version = data.get("version")
    if not isinstance(version, int):
        version = CURRENT_VERSION
    while version < CURRENT_VERSION:
        migrate = MIGRATIONS.get(version)
        if migrate is None:
            break
        data = migrate(data)
        version += 1
    data["version"] = CURRENT_VERSION
    return data


def _check_option(spec: dict, value) -> tuple[bool, object]:
    if "choices" in spec:
        return (value in spec["choices"], value)
    kind = spec.get("kind", "int")
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return False, None
        if not (spec["min"] <= value <= spec["max"]):
            return False, None
        return True, value
    if kind == "str_or_null":
        if value is None:
            return True, None
        if not isinstance(value, str) or len(value) > spec["max"]:
            return False, None
        return True, value
    if kind == "int_or_null":
        if value is None:
            return True, None
        if isinstance(value, bool) or not isinstance(value, int):
            return False, None
        return True, value
    return False, None  # pragma: no cover - every option kind above is handled


def _normalize_options(wtype: str, raw: dict | None) -> dict:
    """Lenient: a missing or invalid option value silently takes its default."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for name, spec in WIDGET_OPTIONS[wtype].items():
        if name in raw:
            ok, value = _check_option(spec, raw[name])
            out[name] = value if ok else spec["default"]
        else:
            out[name] = spec["default"]
    return out


def normalize_for_read(stored: dict | None) -> tuple[dict, bool]:
    """The layout as `GET` returns it, plus whether nothing is saved."""
    if not stored:
        return default_layout(), True

    layout = _migrate(stored)
    widgets = []
    for raw in layout.get("widgets") or []:
        if not isinstance(raw, dict):
            continue
        wtype = raw.get("type")
        if wtype not in WIDGET_OPTIONS:
            continue  # a retired or unrecognised type is dropped silently
        wid = raw.get("id")
        if not isinstance(wid, str) or not wid:
            continue
        size = raw.get("size")
        if size not in SIZES:
            size = DEFAULT_SIZES[wtype]
        title = raw.get("title")
        if not (title is None or (isinstance(title, str) and len(title) <= 80)):
            title = None
        widgets.append(
            {
                "id": wid,
                "type": wtype,
                "size": size,
                "title": title,
                "options": _normalize_options(wtype, raw.get("options")),
            }
        )
    return {"version": CURRENT_VERSION, "widgets": widgets}, False


def validate_widgets(raw_widgets: list) -> list[dict]:
    """Strict validation for `PUT`. Raises `ValueError` describing the first
    problem found, naming the widget id and, for a bad option, its name."""
    if not isinstance(raw_widgets, list):
        raise ValueError("widgets must be a list")
    if len(raw_widgets) > MAX_WIDGETS:
        raise ValueError(f"too many widgets (max {MAX_WIDGETS})")

    seen_ids: set[str] = set()
    widgets = []
    for raw in raw_widgets:
        if not isinstance(raw, dict):
            raise ValueError("each widget must be an object")
        wid = raw.get("id")
        if not isinstance(wid, str) or not ID_RE.match(wid):
            raise ValueError(f"invalid widget id {wid!r}")
        if wid in seen_ids:
            raise ValueError(f"duplicate widget id {wid!r}")
        seen_ids.add(wid)

        wtype = raw.get("type")
        if wtype not in WIDGET_OPTIONS:
            raise ValueError(f"widget '{wid}': unknown type {wtype!r}")

        size = raw.get("size")
        if size not in SIZES:
            raise ValueError(f"widget '{wid}': invalid size {size!r}")

        title = raw.get("title")
        if not (title is None or (isinstance(title, str) and len(title) <= 80)):
            raise ValueError(f"widget '{wid}': title too long")

        options_raw = raw.get("options") or {}
        if not isinstance(options_raw, dict):
            raise ValueError(f"widget '{wid}': options must be an object")
        options = {}
        for name, spec in WIDGET_OPTIONS[wtype].items():
            if name in options_raw:
                ok, value = _check_option(spec, options_raw[name])
                if not ok:
                    raise ValueError(f"widget '{wid}': invalid value for option '{name}'")
                options[name] = value
            else:
                options[name] = spec["default"]

        widgets.append({"id": wid, "type": wtype, "size": size, "title": title, "options": options})
    return widgets
