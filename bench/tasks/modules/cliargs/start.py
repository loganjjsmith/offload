"""A small command-line argument parser."""


class ArgError(Exception):
    """A problem with the command line, with a message for the user."""


class Parser:
    """Options are written --name VALUE; flags are --name; positionals fill in order.

    parse() returns a dict of every option, flag and positional by name.
    """

    def __init__(self):
        self.options = {}
        self.flags = set()
        self.positionals = []

    def option(self, name, type=str, default=None):
        self.options[name] = (type, default)
        return self

    def flag(self, name):
        self.flags.add(name)
        return self

    def positional(self, name, type=str):
        self.positionals.append((name, type))
        return self

    def parse(self, argv):
        result = {name: default for name, (_, default) in self.options.items()}
        result.update({name: False for name in self.flags})
        values = []
        i = 0
        while i < len(argv):
            arg = argv[i]
            if arg.startswith("--"):
                name = arg[2:]
                if name in self.flags:
                    result[name] = True
                elif name in self.options:
                    if i + 1 >= len(argv):
                        raise ArgError(f"--{name} needs a value")
                    result[name] = self._convert(name, self.options[name][0], argv[i + 1])
                    i += 1
                else:
                    raise ArgError(f"unknown option --{name}")
            else:
                values.append(arg)
            i += 1
        if len(values) < len(self.positionals):
            raise ArgError(f"missing {self.positionals[len(values)][0]}")
        if len(values) > len(self.positionals):
            raise ArgError(f"unexpected argument {values[len(self.positionals)]}")
        for (name, kind), value in zip(self.positionals, values):
            result[name] = self._convert(name, kind, value)
        return result

    @staticmethod
    def _convert(name, kind, text):
        try:
            return kind(text)
        except ValueError:
            raise ArgError(f"{name}: invalid value {text!r}") from None
