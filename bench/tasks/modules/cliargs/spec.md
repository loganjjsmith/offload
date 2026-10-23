## Changes

Extend the parser as below. Everything not mentioned keeps working as before: `--name VALUE` options
(the last occurrence wins), flags, positionals filled in order, type conversion, and `ArgError` for an
unknown option, a missing value at the end, a value that fails conversion, a missing positional or an
extra one. `option`, `flag` and `positional` still return the parser.

1. **`--name=value`**: an option may be given as one argument, split at the first `=`. The value may be
   empty or contain further `=`. A flag given this way (`--verbose=yes`) raises `ArgError`, and so does
   an unknown name.
2. **Multi-value options**: `option(name, type=str, default=None, multiple=False, choices=None)`. With
   `multiple=True`, `--name` takes every following argument up to, but not including, the next argument
   that starts with `--`, or to the end; it must take at least one, otherwise `ArgError`. `--name=value`
   adds one value. Each occurrence adds to the same list, in order. The result is the list of converted
   values, or a new empty list if the option was never given (`default` is ignored for multi-value
   options).
3. **Choices**: `option(..., choices=[...])` and `positional(name, type=str, choices=None)`. After
   conversion, a value not in `choices` raises `ArgError`. For a multi-value option every value is
   checked.
4. **`--`**: every argument after a lone `--` is a positional value, even if it starts with `--`. The
   `--` itself is not a value.
5. **Commands**: `command(name) -> Parser` creates, registers and returns a sub-parser.
   - A parser cannot have both commands and positionals: calling `command` on a parser with positionals,
     or `positional` on a parser with commands, raises `ValueError`. Commands are one level deep:
     calling `command` on a parser that `command` returned raises `ValueError`.
   - When a parser has commands, `parse` reads its own options and flags until the first argument that
     does not start with `--`; that argument names the command (`ArgError` if no command has that name),
     and every argument after it is parsed by the command's parser, so the parent's options must come
     before the command name. If the arguments end without a command, raise `ArgError`.
   - The result holds the parent's options and flags, `"command": <name>`, and the command parser's
     results.
