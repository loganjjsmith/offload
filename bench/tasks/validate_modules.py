"""Checks every module task in the sandbox image: the reference passes every test, and for a change
task the starting module fails some (so the tests see the change). Run before trusting scores:
    python bench/tasks/validate_modules.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from modules import HERE, files_for, parse_result, tasks  # noqa: E402

IMAGE = "offload-bench-sandbox:1"


def run(code, tests, count):
    with tempfile.TemporaryDirectory() as tmp:
        for name, content in files_for(code, tests).items():
            Path(tmp, name).write_text(content, encoding="utf-8")
        result = subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/work", "-w", "/work",
                                 IMAGE, "python3", "run_tests.py"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
    return parse_result(result.stdout + "\n" + result.stderr, count)


def main():
    broken = 0
    for t in tasks():
        share, failures = run(t["reference"], t["tests"], t["count"])
        ok = share == 1.0
        note = f"reference passes {t['count']} tests"
        start = HERE / t["id"] / "start.py"
        if ok and start.exists():
            start_share, _ = run(start.read_text(encoding="utf-8"), t["tests"], t["count"])
            ok = start_share < 1.0
            note += f"; starting module passes {start_share:.0%}"
        broken += not ok
        print(f"{'OK  ' if ok else 'BAD '}  {t['id']}: {note}")
        if share < 1.0:
            print("   " + "\n   ".join(failures))
    print(f"{broken} broken task(s)")
    sys.exit(1 if broken else 0)


if __name__ == "__main__":
    main()
