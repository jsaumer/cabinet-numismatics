"""The API contract: the build's OpenAPI document must not break a client
written against the one committed for the last release (docs/openapi.json).
The comparison itself is `tests/api_contract.py`."""

import copy

import pytest

from tests import api_contract
from tests.api_contract import breaking_changes

UPDATE = "run `python -m tests.api_contract update` in backend/"


def test_the_build_breaks_nothing_in_the_released_api():
    broken = breaking_changes(api_contract.load_baseline(), api_contract.current_schema())
    assert not broken, (
        "Breaking changes against docs/openapi.json (docs/api.md, Stability policy):\n  "
        + "\n  ".join(broken)
    )


def test_the_committed_document_is_this_version():
    """A release bumps pyproject's version, which makes this fail until the
    committed document is written again, additions and all."""
    committed = api_contract.load_baseline()["info"]["version"]
    assert committed == api_contract.project_version(), f"docs/openapi.json is stale: {UPDATE}"


# ---------------------------------------------------------------- the rules


def doc(paths: dict, schemas: dict | None = None) -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1.0.0"},
        "paths": paths,
        "components": {"schemas": schemas or {}},
    }


def ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def json_body(schema: dict) -> dict:
    return {"content": {"application/json": {"schema": schema}}}


def op(response: dict | None = None, request: dict | None = None, parameters=None) -> dict:
    operation = {"responses": {"200": json_body(response if response is not None else {})}}
    if request is not None:
        operation["requestBody"] = {"required": True, **json_body(request)}
    if parameters is not None:
        operation["parameters"] = parameters
    return operation


def param(name: str, schema: dict, required: bool = False, where: str = "query") -> dict:
    return {"name": name, "in": where, "required": required, "schema": schema}


STRING, INTEGER, NUMBER = {"type": "string"}, {"type": "integer"}, {"type": "number"}


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def obj(required: list[str] | None = None, **properties) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


def compare(old_schemas: dict, new_schemas: dict, *, request=False) -> list[str]:
    """One operation whose response (or request) is the `Thing` component."""
    kwargs = {"request": ref("Thing")} if request else {"response": ref("Thing")}
    old = doc({"/things": {"post": op(**kwargs)}}, old_schemas)
    new = doc({"/things": {"post": op(**kwargs)}}, new_schemas)
    return breaking_changes(old, new)


def test_identical_documents_break_nothing():
    schemas = {"Thing": obj(["id"], id=INTEGER, name=nullable(STRING))}
    assert compare(schemas, copy.deepcopy(schemas)) == []


def test_a_removed_path_and_a_removed_operation():
    old = doc({"/a": {"get": op(), "post": op()}, "/b": {"get": op()}})
    new = doc({"/a": {"get": op()}})
    assert breaking_changes(old, new) == ["POST /a: operation removed", "/b: path removed"]


def test_additions_pass():
    old = doc({"/a": {"get": op(ref("Thing"))}}, {"Thing": obj(["id"], id=INTEGER)})
    new = doc(
        {
            "/a": {
                "get": op(ref("Thing"), parameters=[param("limit", INTEGER)]),
                "post": op(request=ref("Thing")),
            },
            "/b": {"get": op()},
        },
        {"Thing": obj(["id", "name"], id=INTEGER, name=STRING)},
    )
    new["paths"]["/a"]["get"]["responses"]["404"] = {"description": "gone"}
    assert breaking_changes(old, new) == []


def test_a_removed_response_field_at_any_depth():
    old = {"Thing": obj(tags={"type": "array", "items": ref("Tag")}), "Tag": obj(name=STRING)}
    new = {"Thing": obj(tags={"type": "array", "items": ref("Tag")}), "Tag": obj()}
    assert compare(old, new) == ["POST /things: response 200: tags[].name: field removed"]


def test_a_removed_request_field():
    old, new = {"Thing": obj(name=STRING, note=STRING)}, {"Thing": obj(name=STRING)}
    assert compare(old, new, request=True) == ["POST /things: request: note: field removed"]


@pytest.mark.parametrize(
    "old, new, broken",
    [
        (STRING, INTEGER, True),
        (STRING, nullable(STRING), True),  # a client may not expect null
        (nullable(STRING), STRING, False),
        (NUMBER, INTEGER, False),  # every integer is a number
        (INTEGER, NUMBER, True),
        (STRING, {}, True),  # anything at all
        ({"type": "array", "items": STRING}, {"type": "array", "items": INTEGER}, True),
    ],
)
def test_a_response_type_may_only_narrow(old, new, broken):
    found = compare({"Thing": obj(value=old)}, {"Thing": obj(value=new)})
    assert bool(found) is broken, found


@pytest.mark.parametrize(
    "old, new, broken",
    [
        (STRING, INTEGER, True),
        (STRING, nullable(STRING), False),
        (nullable(STRING), STRING, True),  # null was accepted before
        (INTEGER, NUMBER, False),
        (NUMBER, INTEGER, True),
        (STRING, {}, False),
    ],
)
def test_a_request_type_may_only_widen(old, new, broken):
    found = compare({"Thing": obj(value=old)}, {"Thing": obj(value=new)}, request=True)
    assert bool(found) is broken, found


def test_a_listed_value_removed_or_added():
    def kinds(*values):
        return {"Thing": obj(kind={"type": "string", "enum": list(values)})}

    gone = ['POST /things: response 200: kind: no longer lists "note"']
    assert compare(kinds("coin", "note"), kinds("coin")) == gone
    assert compare(kinds("coin", "note"), kinds("coin"), request=True) == [
        'POST /things: request: kind: no longer lists "note"'
    ]
    assert compare(kinds("coin"), kinds("coin", "note")) == []
    assert compare(kinds("coin"), kinds("coin", "note"), request=True) == []


def test_a_request_field_that_starts_listing_its_values():
    free, listed = {"Thing": obj(kind=STRING)}, {"Thing": obj(kind={**STRING, "enum": ["a"]})}
    assert compare(free, listed, request=True) == [
        "POST /things: request: kind: now limited to listed values"
    ]
    assert compare(free, listed) == []  # a response saying more about itself
    assert compare(listed, free) == [] and compare(listed, free, request=True) == []


def test_required_fields():
    loose, strict = {"Thing": obj(name=STRING)}, {"Thing": obj(["name"], name=STRING)}
    assert compare(loose, strict, request=True) == ["POST /things: request: name: now required"]
    assert compare(strict, loose, request=True) == []
    assert compare(strict, loose) == ["POST /things: response 200: name: may now be missing"]
    assert compare(loose, strict) == []
    # A new field a request must carry breaks every existing caller.
    assert compare({"Thing": obj()}, strict, request=True) == [
        "POST /things: request: name: now required"
    ]


def test_parameters():
    def with_params(*parameters):
        return doc({"/a": {"get": op(parameters=list(parameters))}})

    old = with_params(param("q", STRING), param("limit", INTEGER))
    assert breaking_changes(old, with_params(param("q", STRING))) == [
        "GET /a: query parameter 'limit' removed"
    ]
    assert breaking_changes(
        old, with_params(param("q", STRING, required=True), param("limit", INTEGER))
    ) == ["GET /a: query parameter 'q' is now required"]
    assert breaking_changes(
        old, with_params(param("q", STRING), param("limit", STRING), param("x", STRING))
    ) == ["GET /a: query parameter 'limit': type changed from integer to string"]
    assert breaking_changes(
        old, with_params(param("q", STRING), param("limit", INTEGER), param("x", STRING, True))
    ) == ["GET /a: new required query parameter 'x'"]


def test_a_removed_success_response_and_a_removed_body():
    old = doc({"/a": {"post": op(STRING, request=STRING)}})
    new = copy.deepcopy(old)
    new["paths"]["/a"]["post"]["responses"] = {"201": json_body(STRING)}
    del new["paths"]["/a"]["post"]["requestBody"]
    assert breaking_changes(old, new) == [
        "POST /a: request body removed",
        "POST /a: response 200 removed",
    ]


def test_a_dictionary_of_values_and_a_model_that_holds_itself():
    def schemas(value):
        return {
            "Thing": obj(by_metal={"type": "object", "additionalProperties": value}),
            "Node": obj(children={"type": "array", "items": ref("Node")}),
        }

    assert compare(schemas(NUMBER), schemas(STRING)) == [
        "POST /things: response 200: by_metal{}: type changed from number to string"
    ]
    old = doc({"/n": {"get": op(ref("Node"))}}, schemas(NUMBER))
    assert breaking_changes(old, copy.deepcopy(old)) == []


def test_several_object_shapes_are_matched_by_name():
    def schemas(*names):
        return {
            "Thing": obj(value={"anyOf": [ref(n) for n in names]}),
            "A": obj(a=STRING),
            "B": obj(b=STRING),
            "C": obj(c=STRING),
        }

    assert compare(schemas("A", "B"), schemas("A", "C")) == [
        "POST /things: response 200: value: may now answer C"
    ]
    assert compare(schemas("A", "B"), schemas("A", "C"), request=True) == [
        "POST /things: request: value: no longer accepts B"
    ]


# ---------------------------------------------------------------- on the real document


def test_the_check_sees_a_break_in_the_real_document():
    old = api_contract.load_baseline()
    new = copy.deepcopy(old)
    del new["paths"]["/api/items/{item_id}"]["delete"]
    schemas = new["components"]["schemas"]
    del schemas["ItemDetail"]["properties"]["year_label"]
    del schemas["ItemListEntry"]["properties"]["year_label"]
    schemas["ItemOut"]["properties"]["quantity"] = {"type": "string"}
    broken = breaking_changes(old, new)
    assert "DELETE /api/items/{item_id}: operation removed" in broken
    assert "GET /api/items/{item_id}: response 200: year_label: field removed" in broken
    assert "GET /api/items: response 200: items[].year_label: field removed" in broken
    assert "POST /api/items: response 201: quantity: type changed from integer to string" in broken


def test_update_refuses_a_break_unless_it_is_meant(monkeypatch, tmp_path, capsys):
    old = doc({"/a": {"get": op()}, "/b": {"get": op()}})
    baseline = tmp_path / "openapi.json"
    monkeypatch.setattr(api_contract, "BASELINE", baseline)
    monkeypatch.setattr(api_contract, "REPO", tmp_path)

    def build(version: str, paths: tuple[str, ...]):
        new = doc({p: {"get": op()} for p in paths})
        new["info"]["version"] = version
        monkeypatch.setattr(api_contract, "current_schema", lambda: new)

    def committed() -> dict:
        return api_contract.load_baseline()

    old["info"]["version"] = "0.37.5"
    api_contract.write_baseline(old)

    build("0.38.0", ("/a",))
    assert api_contract.main(["check"]) == 1
    assert api_contract.main(["update"]) == 1 and "/b" in committed()["paths"]
    assert api_contract.main(["update", "--allow-breaking"]) == 0
    assert "/b" not in committed()["paths"] and committed()["info"]["version"] == "0.38.0"

    # From 1.0.0 the flag is not enough: only a new major version is.
    old["info"]["version"] = "1.2.0"
    api_contract.write_baseline(old)
    build("1.3.0", ("/a",))
    assert api_contract.main(["update", "--allow-breaking"]) == 1 and "/b" in committed()["paths"]
    build("2.0.0", ("/a",))
    assert api_contract.main(["update"]) == 0 and "/b" not in committed()["paths"]

    # An addition is written without ceremony.
    build("2.1.0", ("/a", "/c"))
    assert api_contract.main(["check"]) == 0
    assert api_contract.main(["update"]) == 0 and "/c" in committed()["paths"]
    assert "breaking: /b: path removed" in capsys.readouterr().out
