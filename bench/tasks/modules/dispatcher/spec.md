Write a Python module for a tool registry like an MCP server's: tools are registered with a parameter
description, and calls are validated strictly before the tool runs. Calls never raise; every outcome is
a response dict.

## Parameters

A tool's `params` is a dict of parameter name to spec. A spec is a dict with:

- `type` (required): one of `string`, `integer`, `number`, `boolean`, `array`. `integer` accepts `int`
  but not `bool`; `number` accepts `int` and `float` but not `bool`; `boolean` accepts only `bool`;
  `array` accepts only `list`.
- `items` (only with `type: array`, optional): one of the four other type names; every element must be
  of that type.
- `required` (optional, default `False`).
- `enum` (optional): a list of allowed values.
- `default` (optional): used when the argument is missing. Not allowed together with `required: True`.
- `description` (optional): text, ignored by validation.

## API

`class Registry` with:

- `tool(name, description, params=None)`: a decorator that registers the decorated function under
  `name` and returns the function unchanged. `params` defaults to `{}`. Raise `ValueError` at
  registration if the name is already registered, a spec has no `type` or an unknown `type`, `items` is
  used without `type: array` or names an unknown type, a spec is both required and has a default, or a
  default does not itself pass the parameter's checks (type, items and enum).
- `list() -> list[dict]`: one dict per tool, sorted by name:
  `{"name": ..., "description": ..., "params": ...}` where `params` is the dict given at registration.
- `call(name, args) -> dict`:
  - Unknown tool: `{"ok": False, "error": {"code": "unknown_tool", "message": "no tool named <name>"}}`.
  - If `args` is not a dict: `{"ok": False, "error": {"code": "invalid_args", "problems": ["arguments
    must be an object"]}}`.
  - Otherwise collect every problem, as strings: `unknown argument <a>` for each argument the tool does
    not declare; `missing argument <p>` for each required parameter not given; `<p>: expected <type>`
    when a value has the wrong type; `<p>[<i>]: expected <items type>` for each array element of the
    wrong type; `<p>: not one of the allowed values` when a value is not in the enum (checked only if the
    type is right). If there are problems: `{"ok": False, "error": {"code": "invalid_args", "problems":
    <the problems, sorted>}}`.
  - Otherwise call the function with keyword arguments: the given arguments, plus each missing
    parameter that has a default (a deep copy of the default, so a tool that changes it cannot change
    later calls). Missing optional parameters without a default are not passed.
  - If the function raises an `Exception`: `{"ok": False, "error": {"code": "tool_error", "message":
    "<ExceptionClassName>: <str(exception)>"}}`. Otherwise `{"ok": True, "result": <return value>}`.
- `call_json(text) -> str`: parse `text` as JSON. If it is not valid JSON, not an object, or does not
  have a string `tool`, the response is `{"ok": False, "error": {"code": "bad_request", "message":
  "<a short explanation>"}}`. Otherwise the response is `call(tool, args)`, where `args` is the request's
  `args` value, or `{}` if it has none. Return the response as `json.dumps(response, sort_keys=True)`.
