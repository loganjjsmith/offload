import copy
import re


class ConfigError(Exception):
    def __init__(self, errors):
        if isinstance(errors, str):
            errors = [errors]
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def merge(base, override):
    out = copy.deepcopy(base)
    for key, value in override.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


VAR = re.compile(r"\$\$\{|\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _sub(text, env):
    def one(m):
        if m.group(0) == "$${":
            return "${"
        name, default = m.group(1), m.group(2)
        if name in env:
            return env[name]
        if default is not None:
            return default
        raise ConfigError(f"undefined variable {name}")
    return VAR.sub(one, text)


def interpolate(value, env):
    if isinstance(value, str):
        return _sub(value, env)
    if isinstance(value, dict):
        return {k: interpolate(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, env) for v in value]
    return value


TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def _check(value, schema, path, errors):
    kind = schema.get("type")
    if kind and not TYPES[kind](value):
        errors.append(f"{path}: expected {kind}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not one of the allowed values")
    if kind in ("integer", "number"):
        if "min" in schema and value < schema["min"]:
            errors.append(f"{path}: below minimum {schema['min']}")
        if "max" in schema and value > schema["max"]:
            errors.append(f"{path}: above maximum {schema['max']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}.{name}: required")
        for key, item in value.items():
            if key in props:
                _check(item, props[key], f"{path}.{key}", errors)
            elif schema.get("additional", True) is False:
                errors.append(f"{path}.{key}: not allowed")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]", errors)


def validate(config, schema):
    errors = []
    _check(config, schema, "$", errors)
    return sorted(errors)


def _defaults(value, schema):
    if isinstance(value, dict) and "properties" in schema:
        for name, sub in schema["properties"].items():
            if name not in value and "default" in sub:
                value[name] = copy.deepcopy(sub["default"])
            if name in value:
                _defaults(value[name], sub)
    if isinstance(value, list) and "items" in schema:
        for item in value:
            _defaults(item, schema["items"])


def load(base, local, env, schema):
    config = merge(base, local)
    _defaults(config, schema)
    config = interpolate(config, env)
    errors = validate(config, schema)
    if errors:
        raise ConfigError(errors)
    return config
