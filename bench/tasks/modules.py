"""Module-sized Python work: write a module to a spec, or change an existing one, scored by hidden tests.

Each task in modules/<id>/ has spec.md (what the model reads), tests.py (hidden; test_ functions that
import from `solution`) and reference.py (a solution that passes every test). A "change" task also has
start.py, the module the model is asked to modify; the prompt includes it. The tasks were written for
this project on 2026-10-22, so no model can have memorised them. Scores are the share of hidden tests
passed, which separates a nearly-right module from a broken one; all_passed counts fully working ones.
"""
import json
import re
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import Score, mean, metric, scorer, stderr
from inspect_ai.solver import generate, system_message
from inspect_ai.util import sandbox

HERE = Path(__file__).parent / "modules"
RUN_TIMEOUT_S = 300

SYSTEM = ("You are an expert Python programmer. Answer with the complete module in a single fenced python "
          "code block. It is saved as solution.py and imported by hidden tests, so it must not run anything "
          "at import time. Use only the Python standard library. Do not include tests or example usage.")
CHANGE = ("Here is the current module:\n\n```python\n{start}```\n\nMake the following changes and answer with "
          "the complete new module.\n\n{spec}")


def tasks():
    out = []
    for folder in sorted(p for p in HERE.iterdir() if (p / "spec.md").exists()):
        spec = (folder / "spec.md").read_text(encoding="utf-8")
        start = folder / "start.py"
        prompt = CHANGE.format(start=start.read_text(encoding="utf-8"), spec=spec) if start.exists() else spec
        tests = (folder / "tests.py").read_text(encoding="utf-8")
        out.append({"id": folder.name, "prompt": prompt, "tests": tests,
                    "count": len(re.findall(r"^def test_", tests, re.MULTILINE)),
                    "reference": (folder / "reference.py").read_text(encoding="utf-8")})
    return out


def extract_code(text):
    """The longest fenced python block: a module answer may quote small snippets before the module.

    Fences count only at the start of a line, since module code can hold "```" in a string.
    """
    blocks = re.findall(r"^```(?:python|py)?[ \t]*\n(.*?)^```[ \t]*$", text, re.DOTALL | re.MULTILINE)
    return max(blocks, key=len) if blocks else text.strip()


def files_for(code, tests):
    return {"solution.py": code, "tests.py": tests, "run_tests.py": (HERE / "run_tests.py").read_text(encoding="utf-8")}


def parse_result(stdout, count):
    """Share of tests passed, and the failures, from run_tests.py's last output line."""
    for line in reversed(stdout.strip().splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict) and "passed" in result:
            return result["passed"] / count, result.get("failures", [])
    return 0.0, ["no result line: " + stdout[-500:]]


@metric
def all_passed():
    def compute(scores):
        values = [getattr(s, "score", s).as_float() for s in scores]
        return sum(1.0 for v in values if v == 1.0) / len(values) if values else 0.0
    return compute


@scorer(metrics=[mean(), stderr(), all_passed()])
def tests_passed():
    async def score(state, target):
        code = extract_code(state.output.completion)
        box = sandbox()
        workdir = f"/work/{state.sample_id}-{state.epoch}"
        await box.exec(["mkdir", "-p", workdir])
        for name, content in files_for(code, state.metadata["tests"]).items():
            await box.write_file(f"{workdir}/{name}", content)
        try:
            result = await box.exec(["python3", "run_tests.py"], cwd=workdir, timeout=RUN_TIMEOUT_S)
            value, failures = parse_result(result.stdout, state.metadata["count"])
            detail = "\n".join(failures)[-2000:] or "all passed"
        except TimeoutError:
            value, detail = 0.0, "timed out"
        return Score(value=value, answer=code[-3000:], explanation=detail)

    return score


@task
def modules():
    samples = [Sample(id=t["id"], input=t["prompt"], metadata={"tests": t["tests"], "count": t["count"]})
               for t in tasks()]
    return Task(
        dataset=MemoryDataset(samples),
        solver=[system_message(SYSTEM), generate()],
        scorer=tests_passed(),
        sandbox=("docker", str(Path(__file__).parent / "sandbox" / "compose.yaml")),
    )
