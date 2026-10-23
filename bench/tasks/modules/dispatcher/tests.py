import json

from solution import Registry

SUMMARISE = {
    "paths": {"type": "array", "items": "string", "required": True},
    "mode": {"type": "string", "enum": ["fast", "careful"], "default": "fast"},
    "max_words": {"type": "integer"},
    "ratio": {"type": "number", "default": 0.5},
    "verbose": {"type": "boolean"},
}


def _registry():
    r = Registry()

    @r.tool("summarise", "Summarise files", SUMMARISE)
    def summarise(**kwargs):
        return kwargs

    @r.tool("ping", "Health check")
    def ping():
        return "pong"

    @r.tool("fail", "Always fails", {"why": {"type": "string", "default": "no reason"}})
    def fail(why):
        raise RuntimeError(why)

    return r


def _expect_value_error(register):
    try:
        register()
    except ValueError:
        pass
    else:
        raise AssertionError("registration accepted")


def test_decorator_returns_function():
    r = Registry()

    def f():
        return 1

    assert r.tool("f", "d")(f) is f


def test_list_sorted_with_params():
    listed = _registry().list()
    assert [t["name"] for t in listed] == ["fail", "ping", "summarise"]
    assert listed[1] == {"name": "ping", "description": "Health check", "params": {}}
    assert listed[2]["params"] == SUMMARISE


def test_call_without_params():
    assert _registry().call("ping", {}) == {"ok": True, "result": "pong"}


def test_call_passes_given_and_defaults():
    result = _registry().call("summarise", {"paths": ["a.py"], "max_words": 50})
    assert result == {"ok": True, "result": {"paths": ["a.py"], "max_words": 50, "mode": "fast", "ratio": 0.5}}


def test_optional_without_default_not_passed():
    result = _registry().call("summarise", {"paths": []})["result"]
    assert "verbose" not in result and "max_words" not in result


def test_unknown_tool():
    assert _registry().call("nope", {}) == {"ok": False, "error": {"code": "unknown_tool",
                                                                    "message": "no tool named nope"}}


def test_args_must_be_dict():
    for bad in (None, [], "x", 3):
        assert _registry().call("ping", bad) == {"ok": False, "error": {
            "code": "invalid_args", "problems": ["arguments must be an object"]}}


def test_unknown_and_missing_arguments():
    result = _registry().call("summarise", {"path": "a", "zz": 1})
    assert result == {"ok": False, "error": {"code": "invalid_args", "problems": [
        "missing argument paths", "unknown argument path", "unknown argument zz"]}}


def test_type_problems():
    args = {"paths": "a.py", "mode": 3, "max_words": 5.0, "ratio": "half", "verbose": 1}
    assert _registry().call("summarise", args)["error"]["problems"] == [
        "max_words: expected integer", "mode: expected string", "paths: expected array",
        "ratio: expected number", "verbose: expected boolean"]


def test_bool_is_not_a_number():
    problems = _registry().call("summarise", {"paths": [], "max_words": True, "ratio": False})["error"]["problems"]
    assert problems == ["max_words: expected integer", "ratio: expected number"]


def test_int_accepted_as_number():
    assert _registry().call("summarise", {"paths": [], "ratio": 1})["result"]["ratio"] == 1


def test_item_problems():
    problems = _registry().call("summarise", {"paths": ["a", 1, "b", None]})["error"]["problems"]
    assert problems == ["paths[1]: expected string", "paths[3]: expected string"]


def test_enum_problem():
    assert _registry().call("summarise", {"paths": [], "mode": "slow"})["error"]["problems"] == [
        "mode: not one of the allowed values"]


def test_enum_not_checked_when_type_wrong():
    assert _registry().call("summarise", {"paths": [], "mode": 1})["error"]["problems"] == ["mode: expected string"]


def test_tool_error():
    assert _registry().call("fail", {"why": "disk full"}) == {"ok": False, "error": {
        "code": "tool_error", "message": "RuntimeError: disk full"}}
    assert _registry().call("fail", {})["error"]["message"] == "RuntimeError: no reason"


def test_tool_not_called_when_invalid():
    r = Registry()
    calls = []

    @r.tool("t", "d", {"n": {"type": "integer", "required": True}})
    def t(n):
        calls.append(n)

    r.call("t", {"n": "1"})
    assert calls == []


def test_default_is_copied():
    r = Registry()

    @r.tool("t", "d", {"items": {"type": "array", "default": []}})
    def t(items):
        items.append(1)
        return len(items)

    assert r.call("t", {}) == {"ok": True, "result": 1}
    assert r.call("t", {}) == {"ok": True, "result": 1}


def test_duplicate_name_rejected():
    r = Registry()
    r.tool("t", "d")(lambda: 1)
    _expect_value_error(lambda: r.tool("t", "again")(lambda: 2))


def test_bad_specs_rejected():
    for params in ({"a": {}}, {"a": {"type": "float"}}, {"a": {"type": "string", "items": "string"}},
                   {"a": {"type": "array", "items": "thing"}},
                   {"a": {"type": "string", "required": True, "default": "x"}},
                   {"a": {"type": "integer", "default": "1"}},
                   {"a": {"type": "string", "enum": ["x"], "default": "y"}},
                   {"a": {"type": "array", "items": "integer", "default": [1, "2"]}}):
        _expect_value_error(lambda: Registry().tool("t", "d", params)(lambda **k: 1))


def test_good_specs_accepted():
    r = Registry()
    r.tool("t", "d", {"a": {"type": "array", "items": "number", "default": [1, 2.5]},
                      "b": {"type": "boolean", "required": False, "default": False, "description": "x"},
                      "c": {"type": "string", "enum": ["x", "y"], "default": "y"}})(lambda **k: k)
    assert r.call("t", {}) == {"ok": True, "result": {"a": [1, 2.5], "b": False, "c": "y"}}


def test_call_json_ok():
    out = _registry().call_json('{"tool": "ping"}')
    assert out == json.dumps({"ok": True, "result": "pong"}, sort_keys=True)


def test_call_json_with_args():
    out = json.loads(_registry().call_json('{"tool": "summarise", "args": {"paths": ["x"], "mode": "careful"}}'))
    assert out == {"ok": True, "result": {"paths": ["x"], "mode": "careful", "ratio": 0.5}}


def test_call_json_is_sorted():
    out = _registry().call_json('{"tool": "nope"}')
    assert out == '{"error": {"code": "unknown_tool", "message": "no tool named nope"}, "ok": false}'


def test_call_json_bad_requests():
    for text in ("not json", "[1]", '{"args": {}}', '{"tool": 5}', ""):
        out = json.loads(_registry().call_json(text))
        assert out["ok"] is False and out["error"]["code"] == "bad_request", text
        assert isinstance(out["error"]["message"], str) and out["error"]["message"]


def test_call_json_args_not_object():
    out = json.loads(_registry().call_json('{"tool": "ping", "args": [1]}'))
    assert out == {"ok": False, "error": {"code": "invalid_args", "problems": ["arguments must be an object"]}}
