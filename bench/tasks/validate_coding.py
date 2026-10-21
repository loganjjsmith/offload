"""Checks every coding problem's tests against its reference solution in the sandbox image.

A problem whose reference fails is a broken test, not a hard problem. With --bugs, checks
instead that every planted bug in bugfind.py makes its tests fail. Run before trusting scores:
    python bench/tasks/validate_coding.py [--bugs]
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from coding import assemble, problems  # noqa: E402

IMAGE = "offload-bench-sandbox:1"


def run_tests(language, code, tests):
    files, command = assemble(language, code, tests)
    with tempfile.TemporaryDirectory() as tmp:
        for name, content in files.items():
            Path(tmp, name).write_text(content, encoding="utf-8")
        run = subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/work", "-w", "/work",
                              IMAGE, *command], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return run.returncode == 0, (run.stdout + run.stderr)[-1500:]


def main():
    bugs = "--bugs" in sys.argv
    if bugs:
        from bugfind import MUTATIONS, mutated
    failures = 0
    for p in problems():
        if bugs and p["id"] not in MUTATIONS:
            continue
        code = mutated(p)[0] if bugs else p["reference"]
        passed, output = run_tests(p["language"], code, p["tests"])
        ok = passed != bugs
        failures += not ok
        print(f"{'OK  ' if ok else 'BAD '}  {p['id']}" + ("  (bug breaks tests)" if bugs and ok else ""))
        if not ok:
            print("   " + ("planted bug still passes the tests" if bugs else output.replace("\n", "\n   ")))
    print(f"{failures} broken problem(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
