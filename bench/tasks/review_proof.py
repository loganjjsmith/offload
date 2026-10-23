"""Review with proof: a reviewer that fails code must also write a test that shows the bug.

The loop coordinator (docs/PLAN.md, Phase 5) accepts a claimed bug only when the reviewer's test fails on the
code under review, so a false alarm costs a round instead of broken code. This task measures whether that filter
holds. Each test runs in the coding sandbox against the reviewed code and against the problem's reference
solution:

- proved: fails on the code, passes on the reference. On buggy code, the bug is shown. On "clean" code (passed the
  hidden tests) it is a bug the hidden tests missed.
- wrong test: fails on both. The coordinator cannot tell this from a proof, since it has no reference, so on
  clean code it is a false alarm that gets through.
- broken test: fails on both, and does not even build or load against the reference, so the error is the
  test's own. The coordinator can see a build or load error without a reference and reject the test.
- not reproduced: passes on the code, so the coordinator drops the claim.

Same frozen solutions and version 2 prompt as review.py.
"""
import json
import re
import sys
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, SampleScore, accuracy, metric, scorer, stderr
from inspect_ai.solver import generate
from inspect_ai.util import sandbox

sys.path.insert(0, str(Path(__file__).parent))
from coding import FENCES, RUN_TIMEOUT_S, assemble, problems  # noqa: E402
from review import PROMPT_SPEC_ONLY, SOLUTIONS, final_verdict  # noqa: E402

HERE = Path(__file__).parent

TEST_FORMAT = {
    "python": "The test is a Python script saved as test_solution.py next to the code, which is saved as "
              "solution.py. Import what you need with `from solution import ...` and check with plain `assert` "
              "statements at the top level (a function you define must also be called); the test fails by raising.",
    "typescript": "The test is a TypeScript module run by Node 24 with type stripping, saved next to the code, which "
                  "is saved as solution.mts. Import with `import { ... } from \"./solution.mts\";` and "
                  "`import assert from \"node:assert/strict\";`; the test fails by throwing.",
    "csharp": "The test is C# top-level statements, placed before the code in one file-based app. Call the code "
              "directly and check with the harness's `Check(bool ok, string what)`, which exits with an error when "
              "ok is false. Do not define Check or a Main method.",
}

PROOF = """

If your verdict is "fail", prove it: after the JSON object, write one test that fails on this code and passes on any correct implementation of the specification. {test_format} Do not repeat the code under review; the test runs with it. Use only the standard library. Put the test in a single ```{fence} code block."""

# Output of a test that never ran its checks: it did not build, load or parse. Read on the reference's run,
# because a reference always builds and loads, so the error is the test's.
BROKEN = re.compile(r"The build failed|error CS\d+|SyntaxError|IndentationError|ImportError|ModuleNotFoundError|"
                    r"ERR_MODULE_NOT_FOUND|ERR_INVALID_TYPESCRIPT_SYNTAX|does not provide an export")
USING = re.compile(r"\s*using\s+[\w.]+\s*;\s*$")


def proof_test(completion, language):
    """The reviewer's test: the last code block tagged with the language, else the last untagged one."""
    text = re.sub(r"<think>.*?</think>", "", completion or "", flags=re.DOTALL)
    blocks = re.findall(r"^```([\w#+-]*)[ \t]*\n(.*?)^```", text, re.DOTALL | re.MULTILINE)
    tagged = [code for tag, code in blocks if tag.lower() in FENCES[language]]
    untagged = [code for tag, code in blocks if not tag and '"verdict"' not in code]
    found = tagged or untagged
    return found[-1] if found else None


def assemble_test(language, code, test):
    """Files and command for running a reviewer's test against code; C# `using` lines go to the top of the file."""
    if language != "csharp":
        return assemble(language, code, test)
    usings = [line for line in test.splitlines() if USING.match(line)]
    body = "\n".join(line for line in test.splitlines() if not USING.match(line))
    files, command = assemble(language, code, body)
    return {"Program.cs": "\n".join(usings) + "\n" + files["Program.cs"]}, command


def outcome(verdict, test, on_code, on_reference):
    """Classifies one answer. on_code and on_reference are (passed, output) pairs, or None when nothing ran."""
    if verdict != "fail":
        return "passed"
    if test is None:
        return "no test"
    if on_code[0]:
        return "not reproduced"
    if on_reference[0]:
        return "proved"
    return "broken test" if BROKEN.search(on_reference[1]) else "wrong test"


def samples(path=SOLUTIONS):
    by_id = {p["id"]: p for p in problems()}
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        p = by_id[r["problem"]]
        numbered = "\n".join(f"{i + 1:3d}  {text}" for i, text in enumerate(r["code"].split("\n")))
        prompt = PROMPT_SPEC_ONLY.format(language=r["language"], spec=p["prompt"].strip(), numbered=numbered)
        prompt += PROOF.format(test_format=TEST_FORMAT[r["language"]], fence=FENCES[r["language"]][0])
        truth = "buggy" if r["has_bug"] else "clean"
        out.append(Sample(id=f"{r['problem']}:{r['writer']}:{r['variant']}", input=prompt,
                          target="fail" if r["has_bug"] else "pass",
                          metadata={"writer": r["writer"], "has_bug": r["has_bug"], "pair": f"{r['writer']} {truth}",
                                    "language": r["language"], "code": r["code"], "reference": p["reference"]}))
    return out


async def _run(workdir, language, code, test):
    files, command = assemble_test(language, code, test)
    box = sandbox()
    await box.exec(["mkdir", "-p", workdir])
    for name, content in files.items():
        await box.write_file(f"{workdir}/{name}", content)
    try:
        result = await box.exec(command, cwd=workdir, timeout=RUN_TIMEOUT_S)
        return result.returncode == 0, (result.stdout + result.stderr)[-1500:]
    except TimeoutError:
        return False, "timed out"


def _share(scores, has_bug, outcomes):
    group = [s for s in scores if s.score.metadata["has_bug"] == has_bug]
    return sum(s.score.metadata["outcome"] in outcomes for s in group) / len(group) if group else float("nan")


@metric
def bugs_proved():
    """Share of buggy solutions failed with a test that fails on the code and passes on the reference."""
    def compute(scores: list[SampleScore]) -> float:
        return _share(scores, True, {"proved"})
    return compute


@metric
def alarms_through():
    """Share of clean solutions failed with a test that also fails on the reference: false alarms the filter keeps."""
    def compute(scores: list[SampleScore]) -> float:
        return _share(scores, False, {"wrong test"})
    return compute


@metric
def alarms_dropped():
    """Share of clean solutions failed with a test that passes on them: false alarms the filter removes."""
    def compute(scores: list[SampleScore]) -> float:
        return _share(scores, False, {"not reproduced", "no test", "broken test"})
    return compute


@scorer(metrics=[accuracy(), stderr(), bugs_proved(), alarms_through(), alarms_dropped()])
def proof():
    async def score(state, target):
        language, completion = state.metadata["language"], state.output.completion
        verdict, test = final_verdict(completion), proof_test(completion, language)
        on_code = on_reference = None
        if verdict == "fail" and test is not None:
            workdir = f"/work/{re.sub(r'[^\w.-]', '_', str(state.sample_id))}"
            on_code = await _run(workdir + "/code", language, state.metadata["code"], test)
            if not on_code[0]:
                on_reference = await _run(workdir + "/reference", language, state.metadata["reference"], test)
        result = outcome(verdict, test, on_code, on_reference)
        good = result == "proved" if state.metadata["has_bug"] else result not in ("proved", "wrong test")
        return Score(value=CORRECT if good else INCORRECT, answer=result,
                     explanation=(on_code[1] if on_code else "") + "\n--- reference ---\n" +
                                 (on_reference[1] if on_reference else ""),
                     metadata={"has_bug": state.metadata["has_bug"], "outcome": result, "test": test})
    return score


@task
def review_proof(solutions: str | None = None):
    return Task(dataset=MemoryDataset(samples(Path(solutions) if solutions else SOLUTIONS)),
                solver=[generate()], scorer=proof(),
                sandbox=("docker", str(HERE / "sandbox" / "compose.yaml")))
