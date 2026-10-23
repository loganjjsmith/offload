"""Checks the review-with-proof task's parsing and test runs before any model is scored by it.

Each problem's hidden tests stand in for a reviewer's test: against the reference they must pass, and against
every buggy frozen solution they must count as a proof. A test that always fails must count as a wrong test, and
one that does not build must count as a broken test. Needs Docker and the sandbox image. Run:
    python bench/tasks/validate_review_proof.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from coding import problems  # noqa: E402
from review import SOLUTIONS  # noqa: E402
from review_proof import assemble_test, outcome, proof_test  # noqa: E402
from validate_coding import IMAGE  # noqa: E402

ALWAYS_FAILS = {"python": "assert False, 'always'", "typescript": "throw new Error('always');",
                "csharp": "using System.Text;\nCheck(false, \"always\");"}
DOES_NOT_BUILD = {"python": "from solution import nothing_here", "typescript": "let x: = ;",
                  "csharp": "Check(UndefinedThing.Go(), \"x\");"}


def run(language, code, test):
    files, command = assemble_test(language, code, test)
    with tempfile.TemporaryDirectory() as tmp:
        for name, content in files.items():
            Path(tmp, name).write_text(content, encoding="utf-8")
        r = subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/work", "-w", "/work", IMAGE,
                            *command], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def check(ok, what, failures):
    if not ok:
        failures.append(what)
        print("BAD  " + what)


def parsing(failures):
    fence = "```"
    answer = f'{fence}json\n{{"verdict": "fail", "issues": []}}\n{fence}\nThe test:\n{fence}python\nassert 1\n{fence}\n'
    check(proof_test(answer, "python") == "assert 1\n", "tagged test after a JSON block", failures)
    answer = f'{{"verdict": "fail"}}\n{fence}\nassert 2\n{fence}\n'
    check(proof_test(answer, "python") == "assert 2\n", "untagged test", failures)
    check(proof_test('{"verdict": "fail"} no code', "python") is None, "no test block", failures)
    check(proof_test(f"<think>{fence}python\nx\n{fence}</think>", "python") is None, "test inside thinking", failures)
    check(outcome("pass", None, None, None) == "passed", "pass verdict", failures)
    check(outcome("fail", None, None, None) == "no test", "fail without test", failures)
    check(outcome("fail", "t", (True, ""), None) == "not reproduced", "test passes on code", failures)
    check(outcome("fail", "t", (False, ""), (True, "")) == "proved", "proof", failures)
    check(outcome("fail", "t", (False, ""), (False, "")) == "wrong test", "wrong test", failures)
    check(outcome("fail", "t", (False, ""), (False, "error CS0103: x")) == "broken test", "broken test", failures)


def main():
    failures = []
    parsing(failures)
    by_id = {p["id"]: p for p in problems()}
    for p in by_id.values():
        lang = p["language"]
        check(run(lang, p["reference"], p["tests"])[0], f"{p['id']}: hidden tests pass on the reference", failures)
        failing = run(lang, p["reference"], ALWAYS_FAILS[lang])
        check(outcome("fail", "t", failing, failing) == "wrong test",
              f"{p['id']}: failing test is a wrong test ({failing[1][-200:]!r})", failures)
        broken = run(lang, p["reference"], DOES_NOT_BUILD[lang])
        check(outcome("fail", "t", broken, broken) == "broken test",
              f"{p['id']}: test that does not build is broken ({broken[1][-200:]!r})", failures)
    buggy = [json.loads(line) for line in SOLUTIONS.read_text(encoding="utf-8").splitlines()]
    buggy = [r for r in buggy if r["has_bug"]]
    for r in buggy:
        p = by_id[r["problem"]]
        on_code = run(r["language"], r["code"], p["tests"])
        on_reference = (True, "") if on_code[0] else run(r["language"], p["reference"], p["tests"])
        check(outcome("fail", p["tests"], on_code, on_reference) == "proved",
              f"{r['problem']} by {r['writer']}: hidden tests prove the bug", failures)
    print(f"{len(by_id)} problems, {len(buggy)} buggy solutions; {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
