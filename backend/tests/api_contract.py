"""The API contract check: the build's OpenAPI document against the one
committed for the last release (`docs/openapi.json`).

`breaking_changes(old, new)` lists what a client written against `old` could
trip over in `new`: a removed path, operation, parameter, field, or listed
value, a changed type, a request field or parameter that became required, a
response field that may now be missing. Additions pass. It reads structure
only: a narrowed range, pattern, or length, or a field that keeps its shape
and changes its meaning, is still a breaking change and still not visible
here (docs/api.md, "Stability policy").

`tests/test_api_contract.py` runs the comparison with the rest of the suite.
From `backend/`:

    python -m tests.api_contract check
    python -m tests.api_contract update [--allow-breaking]

`update` rewrites the committed document from the build. It refuses a
breaking change unless the major version went up, or, before 1.0.0 only,
`--allow-breaking` says the break is meant (and is in the changelog).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "docs" / "openapi.json"
PYPROJECT = REPO / "backend" / "pyproject.toml"

METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")
REQUEST, RESPONSE = "request", "response"


# ---------------------------------------------------------------- the documents


def project_version() -> str:
    """The version in pyproject.toml, which is what a release is cut from; an
    editable install's own metadata can be older than the file."""
    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    if match is None:
        raise RuntimeError(f"No version in {PYPROJECT}")
    return match.group(1)


def current_schema() -> dict:
    """The OpenAPI document of this build, as `/api/openapi.json` serves it."""
    # What conftest sets, for when this runs outside pytest.
    os.environ.setdefault("PHOTO_DIR", os.path.join(tempfile.gettempdir(), "cabinet-test-photos"))
    os.environ.setdefault("AUTO_MIGRATE", "false")
    os.environ.setdefault("PUBLIC_ORIGINS", "https://testserver")
    os.environ.setdefault(
        "SECRET_KEY", base64.urlsafe_b64encode(b"cabinet-test-key-32-bytes-long!!").decode()
    )
    from app.main import app

    schema = json.loads(json.dumps(app.openapi()))  # a copy: the app caches its own
    schema["info"]["version"] = project_version()
    return schema


def load_baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def write_baseline(schema: dict) -> None:
    text = json.dumps(schema, indent=1, sort_keys=True, ensure_ascii=False)
    BASELINE.write_text(text + "\n", encoding="utf-8")


def major(version: str) -> int:
    return int(re.match(r"\d+", version).group())


# ---------------------------------------------------------------- the comparison


def breaking_changes(old: dict, new: dict) -> list[str]:
    """Every way `new` breaks a client written against `old`, one line each;
    empty when `new` only adds."""
    out: list[str] = []
    new_paths = new.get("paths", {})
    for path, old_item in old.get("paths", {}).items():
        new_item = new_paths.get(path)
        if new_item is None:
            out.append(f"{path}: path removed")
            continue
        for method in METHODS:
            if method not in old_item:
                continue
            where = f"{method.upper()} {path}"
            if method not in new_item:
                out.append(f"{where}: operation removed")
                continue
            _operation(out, where, old_item[method], new_item[method], (old, new))
    return out


def _operation(out: list[str], where: str, old: dict, new: dict, docs: tuple[dict, dict]) -> None:
    old_params = {(p["in"], p["name"]): p for p in old.get("parameters", [])}
    new_params = {(p["in"], p["name"]): p for p in new.get("parameters", [])}
    for key, old_param in old_params.items():
        label = f"{where}: {key[0]} parameter {key[1]!r}"
        new_param = new_params.get(key)
        if new_param is None:
            out.append(f"{label} removed")
            continue
        if new_param.get("required") and not old_param.get("required"):
            out.append(f"{label} is now required")
        old_schema, new_schema = old_param.get("schema", {}), new_param.get("schema", {})
        _schema(out, label, "", old_schema, new_schema, REQUEST, docs)
    for key, new_param in new_params.items():
        if key not in old_params and new_param.get("required"):
            out.append(f"{where}: new required {key[0]} parameter {key[1]!r}")

    old_body, new_body = old.get("requestBody"), new.get("requestBody")
    if old_body and not new_body:
        out.append(f"{where}: request body removed")
    elif new_body and not old_body:
        if new_body.get("required"):
            out.append(f"{where}: a request body is now required")
    elif old_body and new_body:
        if new_body.get("required") and not old_body.get("required"):
            out.append(f"{where}: the request body is now required")
        _content(out, f"{where}: request", old_body, new_body, REQUEST, docs)

    new_responses = new.get("responses", {})
    for status, old_response in old.get("responses", {}).items():
        if not str(status).startswith("2"):
            continue  # error statuses and their bodies are outside the check
        label = f"{where}: response {status}"
        new_response = new_responses.get(status)
        if new_response is None:
            out.append(f"{label} removed")
            continue
        _content(out, label, old_response, new_response, RESPONSE, docs)


def _content(out, label, old: dict, new: dict, mode: str, docs) -> None:
    new_content = new.get("content", {})
    for media, old_media in old.get("content", {}).items():
        new_media = new_content.get(media)
        if new_media is None:
            out.append(f"{label}: {media} removed")
            continue
        old_schema, new_schema = old_media.get("schema", {}), new_media.get("schema", {})
        _schema(out, label, "", old_schema, new_schema, mode, docs)


def _resolve(schema: dict, doc: dict) -> tuple[str | None, dict]:
    """Follow `$ref`s; the component's name comes back with the schema."""
    name = None
    while isinstance(schema, dict) and "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = doc["components"]["schemas"][name]
    return name, schema


def _variants(schema: dict, doc: dict) -> list[tuple[str, str | None, dict]]:
    """A schema as its alternatives: (type, component name, schema) each.
    `anyOf` and `oneOf` are flattened, so `string | null` is two."""
    name, schema = _resolve(schema, doc)
    if not isinstance(schema, dict):
        return [("any", None, {})]
    alternatives = schema.get("anyOf", []) + schema.get("oneOf", [])
    if alternatives:
        return [v for alt in alternatives for v in _variants(alt, doc)]
    kind = schema.get("type")
    if isinstance(kind, list):
        return [(k, name, schema) for k in kind]
    if kind is None:
        if "properties" in schema or "additionalProperties" in schema:
            kind = "object"
        elif "items" in schema:
            kind = "array"
        elif "enum" in schema or "const" in schema:
            kind = "string"
        else:
            kind = "any"
    return [(kind, name, schema)]


def _say(out: list[str], label: str, path: str, message: str) -> None:
    out.append(f"{label}: {path}: {message}" if path else f"{label}: {message}")


def _allowed(kind: str, by: set[str]) -> bool:
    return "any" in by or kind in by or (kind == "integer" and "number" in by)


def _listed(schemas: list[dict]) -> set | None:
    """The values a field lists, or None when any alternative is open."""
    values: set = set()
    for schema in schemas:
        if "enum" in schema:
            values.update(json.dumps(v, sort_keys=True) for v in schema["enum"])
        elif "const" in schema:
            values.add(json.dumps(schema["const"], sort_keys=True))
        else:
            return None
    return values


def _schema(
    out, label, path, old: dict, new: dict, mode: str, docs, seen: frozenset = frozenset()
) -> None:
    old_variants, new_variants = _variants(old, docs[0]), _variants(new, docs[1])
    old_kinds = {k for k, _, _ in old_variants}
    new_kinds = {k for k, _, _ in new_variants}
    # A response may only narrow (never answer a type it didn't before); a
    # request may only widen (keep accepting every type it did).
    if mode == RESPONSE:
        changed = any(not _allowed(k, old_kinds) for k in new_kinds)
    else:
        changed = any(not _allowed(k, new_kinds) for k in old_kinds)
    if changed:
        was, now = " | ".join(sorted(old_kinds)), " | ".join(sorted(new_kinds))
        _say(out, label, path, f"type changed from {was} to {now}")

    for kind in sorted(old_kinds & new_kinds):
        olds = [(n, s) for k, n, s in old_variants if k == kind]
        news = [(n, s) for k, n, s in new_variants if k == kind]
        if kind == "object":
            _objects(out, label, path, olds, news, mode, docs, seen)
        elif kind == "array":
            old_items, new_items = olds[0][1].get("items"), news[0][1].get("items")
            if isinstance(old_items, dict) and isinstance(new_items, dict):
                _schema(out, label, f"{path}[]", old_items, new_items, mode, docs, seen)
        elif kind not in ("null", "any"):
            was, now = _listed([s for _, s in olds]), _listed([s for _, s in news])
            if was is not None and now is not None:
                gone = sorted(was - now)
                if gone:
                    _say(out, label, path, f"no longer lists {', '.join(gone)}")
            elif was is None and now is not None and mode == REQUEST:
                _say(out, label, path, "now limited to listed values")


def _objects(out, label, path, olds, news, mode, docs, seen) -> None:
    if len(olds) == 1 and len(news) == 1:
        pairs = [(olds[0], news[0])]
    else:
        # Several object shapes: match them by name.
        def key(named):
            return named[0] or named[1].get("title")

        by_name = {key(n): n for n in news}
        pairs = [(o, by_name[key(o)]) for o in olds if key(o) in by_name]
        if mode == REQUEST:
            for o in olds:
                if key(o) not in by_name:
                    _say(out, label, path, f"no longer accepts {key(o)}")
        else:
            was = {key(o) for o in olds}
            for n in news:
                if key(n) not in was:
                    _say(out, label, path, f"may now answer {key(n)}")
    for (old_name, old), (new_name, new) in pairs:
        pair = (old_name, new_name)
        if old_name and new_name:
            if pair in seen:
                continue  # a model that contains itself
            inner = seen | {pair}
        else:
            inner = seen
        _object(out, label, path, old, new, mode, docs, inner)


def _object(out, label, path, old: dict, new: dict, mode: str, docs, seen) -> None:
    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    for name, old_prop in old_props.items():
        field = f"{path}.{name}" if path else name
        if name not in new_props:
            _say(out, label, field, "field removed")
            continue
        _schema(out, label, field, old_prop, new_props[name], mode, docs, seen)
    old_required, new_required = set(old.get("required", [])), set(new.get("required", []))
    if mode == REQUEST:
        for name in sorted(new_required - old_required):
            _say(out, label, f"{path}.{name}" if path else name, "now required")
    else:
        for name in sorted((old_required - new_required) & set(new_props)):
            _say(out, label, f"{path}.{name}" if path else name, "may now be missing")
    old_extra, new_extra = old.get("additionalProperties"), new.get("additionalProperties")
    if isinstance(old_extra, dict) and isinstance(new_extra, dict):
        _schema(out, label, f"{path}{{}}", old_extra, new_extra, mode, docs, seen)


# ---------------------------------------------------------------- the command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("check", "update"))
    parser.add_argument(
        "--allow-breaking",
        action="store_true",
        help="before 1.0.0 only: record a breaking change that is meant",
    )
    args = parser.parse_args(argv)

    new = current_schema()
    old = load_baseline() if BASELINE.exists() else None
    broken = breaking_changes(old, new) if old else []
    for line in broken:
        print(f"breaking: {line}")
    if args.command == "check":
        if old is None:
            print(f"No baseline at {BASELINE}; run update.")
            return 1
        print("Breaking changes found." if broken else "No breaking change.")
        return 1 if broken else 0

    if broken:
        version = new["info"]["version"]
        bumped = major(version) > major(old["info"]["version"])
        meant = args.allow_breaking and major(version) < 1
        if not (bumped or meant):
            print(
                "Not written. From 1.0.0 a breaking change needs a new major version; "
                "before it, pass --allow-breaking and put the change in CHANGELOG.md."
            )
            return 1
    write_baseline(new)
    print(f"Wrote {BASELINE.relative_to(REPO)} for {new['info']['version']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
