import copy
import json

TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
}


def _problems(name, spec, value):
    if not TYPES[spec["type"]](value):
        return [f"{name}: expected {spec['type']}"]
    out = []
    if spec["type"] == "array" and "items" in spec:
        out += [f"{name}[{i}]: expected {spec['items']}" for i, v in enumerate(value) if not TYPES[spec["items"]](v)]
    if not out and "enum" in spec and value not in spec["enum"]:
        out.append(f"{name}: not one of the allowed values")
    return out


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, name, description, params=None):
        params = {} if params is None else params
        if name in self.tools:
            raise ValueError(f"tool {name} already registered")
        for pname, spec in params.items():
            if spec.get("type") not in TYPES:
                raise ValueError(f"{pname}: unknown type")
            if "items" in spec and (spec["type"] != "array" or spec["items"] not in TYPES or spec["items"] == "array"):
                raise ValueError(f"{pname}: bad items")
            if spec.get("required") and "default" in spec:
                raise ValueError(f"{pname}: required with a default")
            if "default" in spec and _problems(pname, spec, spec["default"]):
                raise ValueError(f"{pname}: bad default")

        def register(fn):
            self.tools[name] = (fn, description, params)
            return fn
        return register

    def list(self):
        return [{"name": n, "description": d, "params": p} for n, (_, d, p) in sorted(self.tools.items())]

    def call(self, name, args):
        if name not in self.tools:
            return {"ok": False, "error": {"code": "unknown_tool", "message": f"no tool named {name}"}}
        if not isinstance(args, dict):
            return {"ok": False, "error": {"code": "invalid_args", "problems": ["arguments must be an object"]}}
        fn, _, params = self.tools[name]
        problems = [f"unknown argument {a}" for a in args if a not in params]
        kwargs = {}
        for pname, spec in params.items():
            if pname in args:
                problems += _problems(pname, spec, args[pname])
                kwargs[pname] = args[pname]
            elif spec.get("required"):
                problems.append(f"missing argument {pname}")
            elif "default" in spec:
                kwargs[pname] = copy.deepcopy(spec["default"])
        if problems:
            return {"ok": False, "error": {"code": "invalid_args", "problems": sorted(problems)}}
        try:
            return {"ok": True, "result": fn(**kwargs)}
        except Exception as exc:
            return {"ok": False, "error": {"code": "tool_error", "message": f"{type(exc).__name__}: {exc}"}}

    def call_json(self, text):
        def bad(message):
            return json.dumps({"ok": False, "error": {"code": "bad_request", "message": message}}, sort_keys=True)
        try:
            request = json.loads(text)
        except ValueError:
            return bad("not valid JSON")
        if not isinstance(request, dict):
            return bad("request must be an object")
        if not isinstance(request.get("tool"), str):
            return bad("request needs a string tool")
        return json.dumps(self.call(request["tool"], request.get("args", {})), sort_keys=True)
