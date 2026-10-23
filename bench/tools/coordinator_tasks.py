"""Turns the bench's module-sized tasks into loop coordinator task folders, to try the coordinator on known work.

Each module's hidden tests become the cloud's tests, which the writer sees, wrapped so Python's unittest runs
each test_ function as one test. A "change" task's start.py becomes the starting solution.py. Run from the
project root:
    python bench/tools/coordinator_tasks.py OUT_DIR [module ...]
then `node server/src/coordinate.ts OUT_DIR/<module>` for each.
"""
import json
import shutil
import sys
from pathlib import Path

MODULES = Path(__file__).resolve().parent.parent / "tasks" / "modules"

NOTE = ("\n\nThe module is saved as solution.py and imported by the tests, so it must not run anything at import "
        "time. Use only the Python standard library.\n")

LOADER = '''"""Runs every test_ function in hidden_tests.py as one unittest test, under its own name."""
import unittest

from tests import hidden_tests


class HiddenTests(unittest.TestCase):
    pass


for _name, _f in list(vars(hidden_tests).items()):
    if _name.startswith("test_") and callable(_f):
        setattr(HiddenTests, _name, staticmethod(_f))
'''


def build(module, out):
    src = MODULES / module
    dest = out / module
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "tests").mkdir(parents=True)
    (dest / "spec.md").write_text((src / "spec.md").read_text(encoding="utf-8").rstrip() + NOTE, encoding="utf-8")
    (dest / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (dest / "tests" / "hidden_tests.py").write_text((src / "tests.py").read_text(encoding="utf-8"), encoding="utf-8")
    (dest / "tests" / "test_module.py").write_text(LOADER, encoding="utf-8")
    if (src / "start.py").exists():
        (dest / "start").mkdir()
        shutil.copy(src / "start.py", dest / "start" / "solution.py")
    task = {"language": "python", "files": ["solution.py"],
            "test": ["python3", "-m", "unittest", "-v", "tests.test_module"], "maxRounds": 4, "maxMinutes": 60}
    (dest / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    return dest


def main():
    out = Path(sys.argv[1])
    modules = sys.argv[2:] or sorted(p.name for p in MODULES.iterdir() if (p / "spec.md").exists())
    for m in modules:
        print(build(m, out))


if __name__ == "__main__":
    main()
