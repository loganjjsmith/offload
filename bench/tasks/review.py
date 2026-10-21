"""Review model-written code with no hint of whether it has a bug, scored on catches and false alarms.

The code under review is what the candidate models wrote for the fresh coding tasks, with the
hidden-test result as ground truth: a failed solution has a real bug a model made, a passed one is
clean. Solutions that did not compile or timed out are left out, because a compiler or a test run
catches those for free. Each sample records its writer, so self-review and cross-model review can
be compared pair by pair.

The set of solutions is frozen in results/review_solutions.jsonl the first time the task runs, so
every reviewer sees identical code. Delete that file to rebuild it from newer coding runs; that
is a new version of this task, and earlier review scores are no longer comparable.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import read_eval_log
from inspect_ai.scorer import (CORRECT, INCORRECT, Score, SampleScore, accuracy, grouped, metric, scorer,
                               stderr)
from inspect_ai.solver import generate

sys.path.insert(0, str(Path(__file__).parent))
from coding import extract_code, problems  # noqa: E402
from strip import strip_comments  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent
RESULTS = BENCH / "results"
SOLUTIONS = RESULTS / "review_solutions.jsonl"
INSPECT_LOGS = BENCH / "raw" / "inspect"

# Test output that means the code never ran its tests: a compiler or the first test run catches these.
NOT_RUN = re.compile(r"The build failed|error CS\d+|SyntaxError|IndentationError|^timed out$", re.MULTILINE)

PROMPT = """Review the following {language} code against its specification. It may be correct, or it may contain one or more bugs. Check it carefully, including the edge cases the specification mentions.

Specification:
{spec}

Code (line numbers added for reference):
{numbered}

Reply with a JSON object: {{"verdict": "pass" or "fail", "issues": [{{"line": <line number>, "problem": "<what is wrong>", "failing_input": "<an input that shows it>"}}]}}
Use "pass" with an empty issues list if the code meets the specification."""

# Version 2: false alarms in version 1 were mostly nitpicks outside the specification, so it may only be judged against it.
PROMPT_SPEC_ONLY = PROMPT.replace(
    "Check it carefully, including the edge cases the specification mentions.",
    "Check it carefully, including the edge cases the specification mentions.\n"
    "Judge it only against the specification. Report a bug only if you can give an input the specification "
    "covers on which the code returns a wrong result or fails. Inputs the specification does not mention "
    "(such as null or malformed arguments it says nothing about), style, performance and robustness beyond "
    "the specification are not bugs.")


def _coding_runs():
    """The latest successful run of each coding variant per model, from quality.jsonl."""
    latest = {}
    for line in (RESULTS / "quality.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line) if line.strip() else {}
        if entry.get("task", "").startswith("coding_fresh") and entry.get("status") == "success" and entry.get("log"):
            latest[(entry["model"], entry["task"])] = entry
    return latest.values()


def build(out=SOLUTIONS):
    """Collects every compiled, untimed-out coding solution, one per distinct (problem, code)."""
    seen, rows = set(), []
    for run in _coding_runs():
        log = read_eval_log(str(INSPECT_LOGS / run["log"]))
        for sample in log.samples or []:
            score = next(iter(sample.scores.values()), None)
            if score is None or not sample.output or not sample.output.completion:
                continue
            if score.value != CORRECT and NOT_RUN.search(score.explanation or ""):
                continue
            language = sample.metadata["language"]
            code = extract_code(sample.output.completion, language).strip("\n")
            key = (sample.id, hashlib.sha256(re.sub(r"\s+", "", code).encode()).hexdigest())
            if not code or key in seen:
                continue
            seen.add(key)
            rows.append({"problem": sample.id, "language": language, "writer": run["model"], "variant": run["task"],
                         "has_bug": score.value != CORRECT, "code": code})
    rows.sort(key=lambda r: (r["problem"], r["writer"], r["variant"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return rows


def samples(path, strip=False, prompt=PROMPT):
    if not path.exists():
        build(path)
    specs = {p["id"]: p["prompt"].strip() for p in problems()}
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        code = strip_comments(r["code"], r["language"]) if strip else r["code"]
        numbered = "\n".join(f"{i + 1:3d}  {text}" for i, text in enumerate(code.split("\n")))
        truth = "buggy" if r["has_bug"] else "clean"
        out.append(Sample(id=f"{r['problem']}:{r['writer']}:{r['variant']}", target="fail" if r["has_bug"] else "pass",
                          input=prompt.format(language=r["language"], spec=specs[r["problem"]], numbered=numbered),
                          metadata={"writer": r["writer"], "has_bug": r["has_bug"], "pair": f"{r['writer']} {truth}"}))
    return out


def _rate(scores, has_bug, want_correct):
    group = [s for s in scores if s.score.metadata["has_bug"] == has_bug]
    if not group:
        return float("nan")
    # Metrics see the reduced value (1.0 or 0.0), not CORRECT/INCORRECT, so compare as a float.
    hits = sum(1 for s in group if (s.score.as_float() == 1.0) == want_correct)
    return hits / len(group)


@metric
def catches():
    """Share of buggy solutions the reviewer failed."""
    def compute(scores: list[SampleScore]) -> float:
        return _rate(scores, has_bug=True, want_correct=True)
    return compute


@metric
def false_alarms():
    """Share of clean solutions the reviewer failed, or answered unreadably."""
    def compute(scores: list[SampleScore]) -> float:
        return _rate(scores, has_bug=False, want_correct=False)
    return compute


VERDICT = re.compile(r'"verdict"\s*:\s*"(pass|fail)"', re.IGNORECASE)


def final_verdict(completion):
    """The last verdict in the answer: with thinking off, models reason inline and revise earlier drafts."""
    found = VERDICT.findall(re.sub(r"<think>.*?</think>", "", completion or "", flags=re.DOTALL))
    return found[-1].lower() if found else None


@scorer(metrics=[accuracy(), stderr(), catches(), false_alarms(), grouped(accuracy(), "pair", all=False)])
def verdict():
    async def score(state, target):
        got = final_verdict(state.output.completion)
        return Score(value=CORRECT if got == target.text else INCORRECT, answer=got,
                     metadata={"has_bug": state.metadata["has_bug"]})
    return score


@task
def review(solutions: str | None = None, strip_comments: bool = False, spec_only: bool = False):
    """strip_comments: the reviewer reads the code without comments or docstrings ("reading terse").
    spec_only: prompt version 2, which allows only bugs shown by an input the specification covers."""
    prompt = PROMPT_SPEC_ONLY if spec_only else PROMPT
    return Task(dataset=MemoryDataset(samples(Path(solutions) if solutions else SOLUTIONS, strip_comments, prompt)),
                solver=[generate()], scorer=verdict())


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else SOLUTIONS
    built = build(target)
    buggy = sum(r["has_bug"] for r in built)
    print(f"{len(built)} solutions ({buggy} buggy, {len(built) - buggy} clean) written to {target}")
