from solution import ArgError, Parser


def _fails(parser, argv):
    try:
        parser.parse(argv)
    except ArgError:
        return True
    return False


def _value_error(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


# Behaviour kept from the original module.

def test_basic_parse():
    p = Parser().option("level", int, 1).flag("verbose").positional("src").positional("count", int)
    assert p.parse(["a.txt", "--level", "3", "7", "--verbose"]) == {
        "level": 3, "verbose": True, "src": "a.txt", "count": 7}


def test_defaults():
    p = Parser().option("level", int, 1).option("name").flag("quiet")
    assert p.parse([]) == {"level": 1, "name": None, "quiet": False}


def test_last_occurrence_wins():
    assert Parser().option("n", int).parse(["--n", "1", "--n", "2"]) == {"n": 2}


def test_old_errors_kept():
    p = Parser().option("n", int).positional("x")
    assert _fails(p, ["x", "--zzz"])
    assert _fails(p, ["x", "--n"])
    assert _fails(p, ["x", "--n", "abc"])
    assert _fails(p, [])
    assert _fails(p, ["x", "y"])


def test_builders_return_parser():
    p = Parser()
    assert p.option("a") is p and p.flag("b") is p and p.positional("c") is p


def test_arg_error_is_exception():
    assert issubclass(ArgError, Exception)


# --name=value

def test_equals_form():
    p = Parser().option("name").option("n", int)
    assert p.parse(["--name=x", "--n=5"]) == {"name": "x", "n": 5}


def test_equals_split_at_first():
    assert Parser().option("expr").parse(["--expr=a=b=c"]) == {"expr": "a=b=c"}


def test_equals_empty_value():
    assert Parser().option("name", default="d").parse(["--name="]) == {"name": ""}


def test_equals_value_may_look_like_option():
    assert Parser().option("x").parse(["--x=--y"]) == {"x": "--y"}


def test_equals_on_flag_or_unknown_fails():
    p = Parser().flag("verbose")
    assert _fails(p, ["--verbose=yes"])
    assert _fails(p, ["--other=1"])


def test_equals_conversion_error():
    assert _fails(Parser().option("n", int), ["--n=x"])


# Multi-value options

def test_multiple_takes_until_next_option():
    p = Parser().option("only", multiple=True).flag("v")
    assert p.parse(["--only", "a", "b", "c", "--v"]) == {"only": ["a", "b", "c"], "v": True}


def test_multiple_to_end():
    assert Parser().option("only", multiple=True).parse(["--only", "a", "b"]) == {"only": ["a", "b"]}


def test_multiple_absent_is_empty_list_and_new_each_time():
    p = Parser().option("only", multiple=True, default=["ignored"])
    first = p.parse([])
    assert first == {"only": []}
    first["only"].append("x")
    assert p.parse([]) == {"only": []}


def test_multiple_needs_a_value():
    p = Parser().option("only", multiple=True).flag("v")
    assert _fails(p, ["--only"])
    assert _fails(p, ["--only", "--v"])


def test_multiple_occurrences_extend():
    p = Parser().option("tag", multiple=True)
    assert p.parse(["--tag", "a", "--tag=b", "--tag", "c", "d"]) == {"tag": ["a", "b", "c", "d"]}


def test_multiple_converts_each():
    assert Parser().option("n", int, multiple=True).parse(["--n", "1", "-2", "3"]) == {"n": [1, -2, 3]}
    assert _fails(Parser().option("n", int, multiple=True), ["--n", "1", "x"])


def test_multiple_swallows_positionals():
    p = Parser().positional("src").option("only", multiple=True)
    assert p.parse(["file", "--only", "a", "b"]) == {"src": "file", "only": ["a", "b"]}
    assert _fails(p, ["--only", "a", "file"])


# Choices

def test_option_choices():
    p = Parser().option("tier", choices=["quick", "full"])
    assert p.parse(["--tier", "full"]) == {"tier": "full"}
    assert _fails(p, ["--tier", "slow"])
    assert _fails(p, ["--tier=slow"])


def test_choices_checked_after_conversion():
    p = Parser().option("n", int, choices=[1, 2])
    assert p.parse(["--n", "2"]) == {"n": 2}
    assert _fails(p, ["--n", "3"])


def test_default_not_checked_against_choices():
    assert Parser().option("tier", default="none", choices=["a"]).parse([]) == {"tier": "none"}


def test_positional_choices():
    p = Parser().positional("runtime", choices=["lmstudio", "ollama"])
    assert p.parse(["ollama"]) == {"runtime": "ollama"}
    assert _fails(p, ["vllm"])


def test_multiple_choices_each_checked():
    p = Parser().option("only", multiple=True, choices=["a", "b"])
    assert p.parse(["--only", "b", "a"]) == {"only": ["b", "a"]}
    assert _fails(p, ["--only", "a", "c"])


# Double dash

def test_double_dash_makes_positionals():
    p = Parser().flag("v").positional("a").positional("b")
    assert p.parse(["--v", "--", "--x", "-y"]) == {"v": True, "a": "--x", "b": "-y"}


def test_double_dash_mixed_with_earlier_positionals():
    p = Parser().positional("a").positional("b")
    assert p.parse(["one", "--", "--two"]) == {"a": "one", "b": "--two"}


def test_double_dash_alone():
    assert Parser().flag("v").parse(["--"]) == {"v": False}


def test_double_dash_extra_values_fail():
    assert _fails(Parser().positional("a"), ["--", "x", "y"])


# Commands

def _app():
    p = Parser().flag("debug").option("root", default=".")
    run = p.command("run")
    run.positional("model").option("tier", choices=["quick", "full"], default="quick")
    rm = p.command("remove")
    rm.positional("model").flag("force")
    return p


def test_command_parse():
    assert _app().parse(["--debug", "run", "gemma", "--tier", "full"]) == {
        "debug": True, "root": ".", "command": "run", "model": "gemma", "tier": "full"}


def test_command_parent_option_values():
    assert _app().parse(["--root", "/x", "remove", "m", "--force"]) == {
        "debug": False, "root": "/x", "command": "remove", "model": "m", "force": True}


def test_parent_options_must_come_first():
    assert _fails(_app(), ["run", "m", "--debug"])


def test_unknown_and_missing_command():
    assert _fails(_app(), ["build"])
    assert _fails(_app(), ["--debug"])
    assert _fails(_app(), [])


def test_command_errors_propagate():
    assert _fails(_app(), ["run"])
    assert _fails(_app(), ["run", "m", "--tier", "slow"])


def test_command_and_positional_conflict():
    p = Parser().positional("x")
    assert _value_error(lambda: p.command("c"))
    q = Parser()
    q.command("c")
    assert _value_error(lambda: q.positional("x"))


def test_commands_one_level_deep():
    sub = Parser().command("c")
    assert _value_error(lambda: sub.command("d"))


def test_command_returns_new_parser():
    p = Parser()
    a, b = p.command("a"), p.command("b")
    assert isinstance(a, Parser) and a is not b and a is not p
