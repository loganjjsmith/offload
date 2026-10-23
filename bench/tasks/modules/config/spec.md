Write a Python module that builds a configuration from a committed base and a local override,
substitutes environment variables, fills defaults and validates the result against a small schema.

## merge(base, override) -> dict

Returns a new dict; neither input is changed (including nested dicts and lists). For each key in
`override`: if its value is `None`, the key is removed from the result; else if both values are dicts,
they are merged the same way, recursively; otherwise the override's value replaces the base's (lists
are replaced, not combined). Keys only in `base` are kept.

## interpolate(value, env) -> value

Returns a copy of `value` with variables substituted in every string, recursing into dicts (values
only, not keys) and lists. Other types are returned unchanged.

- `${NAME}` is replaced by `env[NAME]`. If `NAME` is not in `env`, raise `ConfigError` with the message
  `undefined variable NAME`.
- `${NAME:-default}` is replaced by `env[NAME]` if present, otherwise by `default` (which may be empty
  and may contain any characters except `}`).
- `$${` is an escape: it produces a literal `${` and the text after it is not treated as a variable.
- NAME is a letter or underscore followed by letters, digits or underscores. A `$` that does not start
  one of these forms is left as it is.
- Substituted text is not scanned again.

## validate(config, schema) -> list[str]

Returns every problem found, as strings `"<path>: <message>"`, sorted. A path is `$` for the root, then
`.key` for an object property and `[i]` for a list item, for example `$.server.ports[2]`. A schema is a
dict with these optional keys:

- `type`: one of `object`, `array`, `string`, `integer`, `number`, `boolean`. `integer` accepts `int`
  but not `bool`; `number` accepts `int` and `float` but not `bool`; `boolean` accepts only `bool`.
  A wrong type gives `expected <type>` and nothing else is checked for that value.
- `enum`: a list; a value not equal to any item gives `not one of the allowed values`.
- `min` / `max`: for `integer` and `number` only; a smaller or larger value gives `below minimum <min>` or
  `above maximum <max>` (written with `str()`).
- `properties`: for objects, a dict of property name to schema; each property present in the value is
  checked against its schema.
- `required`: for objects, a list of names; each one missing gives the message `required` at the
  property's path, for example `$.server.port: required`.
- `additional`: for objects, default `True`; when `False`, each key not in `properties` gives
  `not allowed` at that key's path.
- `items`: for arrays, a schema that every item is checked against.
- `default`: used by `load`, not by `validate`.

## load(base, local, env, schema) -> dict

Merges `local` over `base`, then fills defaults, then interpolates, then validates. **Defaults**: for
every object in the config whose schema has `properties`, each property that is missing and whose
schema has a `default` is set to a deep copy of that default; this is applied recursively, including to
objects that were themselves just filled in from a default. If validation finds problems, raise
`ConfigError` whose `errors` attribute is the list from `validate`. Otherwise return the config.
`ConfigError` is an `Exception` subclass defined in the module; when raised by `interpolate` its
`errors` attribute is a list holding its one message.
