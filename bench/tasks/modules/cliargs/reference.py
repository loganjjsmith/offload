"""A small command-line argument parser."""


class ArgError(Exception):
    """A problem with the command line, with a message for the user."""


class Parser:
    def __init__(self, _is_command=False):
        self.options = {}
        self.flags = set()
        self.positionals = []
        self.commands = {}
        self._is_command = _is_command

    def option(self, name, type=str, default=None, multiple=False, choices=None):
        self.options[name] = (type, default, multiple, choices)
        return self

    def flag(self, name):
        self.flags.add(name)
        return self

    def positional(self, name, type=str, choices=None):
        if self.commands:
            raise ValueError("a parser with commands cannot have positionals")
        self.positionals.append((name, type, choices))
        return self

    def command(self, name):
        if self.positionals:
            raise ValueError("a parser with positionals cannot have commands")
        if self._is_command:
            raise ValueError("commands are one level deep")
        sub = Parser(_is_command=True)
        self.commands[name] = sub
        return sub

    def parse(self, argv):
        result = {}
        for name, (_, default, multiple, _) in self.options.items():
            result[name] = [] if multiple else default
        result.update({name: False for name in self.flags})
        values = []
        i = 0
        while i < len(argv):
            arg = argv[i]
            if arg == "--" and not self.commands:
                values.extend(argv[i + 1:])
                break
            if arg.startswith("--"):
                name, eq, inline = arg[2:].partition("=")
                if name in self.flags:
                    if eq:
                        raise ArgError(f"--{name} takes no value")
                    result[name] = True
                elif name in self.options:
                    kind, _, multiple, choices = self.options[name]
                    if eq:
                        texts = [inline]
                    elif multiple:
                        j = i + 1
                        while j < len(argv) and not argv[j].startswith("--"):
                            j += 1
                        texts = argv[i + 1:j]
                        if not texts:
                            raise ArgError(f"--{name} needs a value")
                        i = j - 1
                    else:
                        if i + 1 >= len(argv):
                            raise ArgError(f"--{name} needs a value")
                        texts = [argv[i + 1]]
                        i += 1
                    converted = [self._convert(name, kind, choices, t) for t in texts]
                    if multiple:
                        result[name].extend(converted)
                    else:
                        result[name] = converted[0]
                else:
                    raise ArgError(f"unknown option --{name}")
            elif self.commands:
                if arg not in self.commands:
                    raise ArgError(f"unknown command {arg}")
                result["command"] = arg
                result.update(self.commands[arg].parse(argv[i + 1:]))
                return result
            else:
                values.append(arg)
            i += 1
        if self.commands:
            raise ArgError("missing command")
        if len(values) < len(self.positionals):
            raise ArgError(f"missing {self.positionals[len(values)][0]}")
        if len(values) > len(self.positionals):
            raise ArgError(f"unexpected argument {values[len(self.positionals)]}")
        for (name, kind, choices), value in zip(self.positionals, values):
            result[name] = self._convert(name, kind, choices, value)
        return result

    @staticmethod
    def _convert(name, kind, choices, text):
        try:
            value = kind(text)
        except ValueError:
            raise ArgError(f"{name}: invalid value {text!r}") from None
        if choices is not None and value not in choices:
            raise ArgError(f"{name}: {value!r} is not one of {choices}")
        return value
