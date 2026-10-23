import copy

from solution import ConfigError, interpolate, load, merge, validate


def test_merge_basic():
    assert merge({"a": 1, "b": 2}, {"b": 3, "c": 4}) == {"a": 1, "b": 3, "c": 4}


def test_merge_nested():
    base = {"server": {"host": "x", "port": 1}, "keep": True}
    assert merge(base, {"server": {"port": 2}}) == {"server": {"host": "x", "port": 2}, "keep": True}


def test_merge_none_removes():
    assert merge({"a": 1, "b": {"c": 2, "d": 3}}, {"a": None, "b": {"d": None}}) == {"b": {"c": 2}}


def test_merge_none_for_missing_key():
    assert merge({"a": 1}, {"zzz": None}) == {"a": 1}


def test_merge_lists_replaced():
    assert merge({"l": [1, 2, 3]}, {"l": [9]}) == {"l": [9]}


def test_merge_dict_replaces_scalar_and_back():
    assert merge({"a": 1, "b": {"x": 1}}, {"a": {"y": 2}, "b": 5}) == {"a": {"y": 2}, "b": 5}


def test_merge_does_not_change_inputs():
    base = {"a": {"b": [1, 2]}, "c": 1}
    override = {"a": {"d": {"e": [3]}}}
    base_copy, override_copy = copy.deepcopy(base), copy.deepcopy(override)
    result = merge(base, override)
    result["a"]["b"].append(99)
    result["a"]["d"]["e"].append(99)
    assert base == base_copy and override == override_copy


def test_interpolate_simple():
    assert interpolate("http://${HOST}:${PORT}/", {"HOST": "h", "PORT": "80"}) == "http://h:80/"


def test_interpolate_default():
    assert interpolate("${A:-x}-${B:-}-${C:-a b:c}", {"A": "1"}) == "1--a b:c"


def test_interpolate_env_wins_over_default():
    assert interpolate("${A:-fallback}", {"A": ""}) == ""


def test_interpolate_missing_raises():
    try:
        interpolate({"k": ["ok", "${NOPE}"]}, {})
    except ConfigError as exc:
        assert str(exc) == "undefined variable NOPE"
        assert exc.errors == ["undefined variable NOPE"]
    else:
        raise AssertionError("missing variable accepted")


def test_interpolate_escape():
    assert interpolate("cost $${X} and ${X}", {"X": "1"}) == "cost ${X} and 1"


def test_interpolate_leaves_other_dollars():
    text = "$5 $ $$ ${1BAD} ${unclosed $name"
    assert interpolate(text, {"name": "n"}) == text


def test_interpolate_not_rescanned():
    assert interpolate("${A}", {"A": "${B}", "B": "no"}) == "${B}"


def test_interpolate_recurses_values_not_keys():
    value = {"${K}": ["${V}", {"x": "${V}"}], "n": 3, "b": True, "z": None}
    assert interpolate(value, {"K": "k", "V": "v"}) == {"${K}": ["v", {"x": "v"}], "n": 3, "b": True, "z": None}


def test_interpolate_does_not_change_input():
    value = {"a": ["${V}"]}
    interpolate(value, {"V": "v"})
    assert value == {"a": ["${V}"]}


SCHEMA = {
    "type": "object",
    "required": ["name", "server"],
    "additional": False,
    "properties": {
        "name": {"type": "string"},
        "debug": {"type": "boolean", "default": False},
        "server": {
            "type": "object",
            "required": ["port"],
            "properties": {
                "host": {"type": "string", "default": "127.0.0.1"},
                "port": {"type": "integer", "min": 1, "max": 65535},
                "mode": {"type": "string", "enum": ["fast", "careful"], "default": "fast"},
            },
        },
        "ratio": {"type": "number", "min": 0, "max": 1},
        "tags": {"type": "array", "items": {"type": "string"}},
        "workers": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "slots": {"type": "integer", "default": 1}}}},
    },
}


def test_validate_ok():
    assert validate({"name": "x", "server": {"port": 80}}, SCHEMA) == []


def test_validate_type_errors():
    config = {"name": 5, "server": {"port": "80"}, "debug": "yes", "tags": "a"}
    assert validate(config, SCHEMA) == ["$.debug: expected boolean", "$.name: expected string",
                                        "$.server.port: expected integer", "$.tags: expected array"]


def test_validate_bool_is_not_integer_or_number():
    assert validate({"name": "x", "server": {"port": True}, "ratio": False}, SCHEMA) == [
        "$.ratio: expected number", "$.server.port: expected integer"]


def test_validate_integer_accepted_as_number():
    assert validate({"name": "x", "server": {"port": 1}, "ratio": 1}, SCHEMA) == []


def test_validate_float_not_integer():
    assert validate({"name": "x", "server": {"port": 80.0}}, SCHEMA) == ["$.server.port: expected integer"]


def test_validate_required():
    assert validate({"server": {}}, SCHEMA) == ["$.name: required", "$.server.port: required"]


def test_validate_additional():
    assert validate({"name": "x", "server": {"port": 1, "extra": 1}, "zzz": 1}, SCHEMA) == ["$.zzz: not allowed"]


def test_validate_min_max():
    config = {"name": "x", "server": {"port": 70000}, "ratio": -0.5}
    assert validate(config, SCHEMA) == ["$.ratio: below minimum 0", "$.server.port: above maximum 65535"]


def test_validate_enum():
    assert validate({"name": "x", "server": {"port": 1, "mode": "slow"}}, SCHEMA) == [
        "$.server.mode: not one of the allowed values"]


def test_validate_items_paths():
    config = {"name": "x", "server": {"port": 1}, "tags": ["a", 2, "c", None],
              "workers": [{"name": "w"}, {"name": 3, "slots": "2"}]}
    assert validate(config, SCHEMA) == ["$.tags[1]: expected string", "$.tags[3]: expected string",
                                        "$.workers[1].name: expected string", "$.workers[1].slots: expected integer"]


def test_validate_root_type():
    assert validate([1], SCHEMA) == ["$: expected object"]


def test_validate_wrong_type_stops_checks():
    schema = {"type": "integer", "enum": [1, 2], "min": 5}
    assert validate("x", schema) == ["$: expected integer"]


def test_validate_schema_without_type():
    schema = {"properties": {"a": {"enum": [1, "1"]}}, "required": ["b"]}
    assert validate({"a": 2}, schema) == ["$.a: not one of the allowed values", "$.b: required"]


def test_load_merges_defaults_and_interpolates():
    base = {"name": "${APP:-offload}", "server": {"port": 1234}, "tags": ["${ENVNAME}"]}
    local = {"server": {"host": "${HOST}"}, "debug": True}
    env = {"HOST": "box", "ENVNAME": "home"}
    assert load(base, local, env, SCHEMA) == {
        "name": "offload", "debug": True, "tags": ["home"],
        "server": {"port": 1234, "host": "box", "mode": "fast"}}


def test_load_defaults_inside_lists():
    base = {"name": "x", "server": {"port": 1}, "workers": [{"name": "a"}, {"name": "b", "slots": 4}]}
    assert load(base, {}, {}, SCHEMA)["workers"] == [{"name": "a", "slots": 1}, {"name": "b", "slots": 4}]


def test_load_default_objects_filled_recursively():
    schema = {"type": "object", "properties": {
        "outer": {"type": "object", "default": {}, "properties": {
            "inner": {"type": "integer", "default": 7}}}}}
    assert load({}, {}, {}, schema) == {"outer": {"inner": 7}}


def test_load_defaults_are_copies():
    schema = {"type": "object", "properties": {"l": {"type": "array", "default": []}}}
    first = load({}, {}, {}, schema)
    first["l"].append(1)
    assert load({}, {}, {}, schema) == {"l": []}


def test_load_default_interpolated():
    schema = {"type": "object", "properties": {"path": {"type": "string", "default": "${HOME}/x"}}}
    assert load({}, {}, {"HOME": "/h"}, schema) == {"path": "/h/x"}


def test_load_local_none_removes_then_default_fills():
    base = {"name": "x", "server": {"port": 1, "mode": "careful"}}
    assert load(base, {"server": {"mode": None}}, {}, SCHEMA)["server"]["mode"] == "fast"


def test_load_raises_with_all_errors():
    try:
        load({"server": {"port": 0}}, {"zzz": 1}, {}, SCHEMA)
    except ConfigError as exc:
        assert exc.errors == ["$.name: required", "$.server.port: below minimum 1", "$.zzz: not allowed"]
    else:
        raise AssertionError("invalid config accepted")


def test_config_error_is_exception():
    assert issubclass(ConfigError, Exception)
