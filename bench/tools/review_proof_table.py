"""Breaks down each reviewer's review-with-proof run as the loop coordinator would see it.

The coordinator accepts a claimed bug only when the reviewer's test fails on the code, and ignores an answer cut
at the token limit. So, per reviewer: the known bugs it proves; the "clean" solutions (they passed the hidden
tests) whose claim still stands, split into tests that also fail on the reference, which are wrong and would
make the writer break working code, and tests the reference passes, which on a 2026-10-23 spot check were mostly
real bugs the hidden tests miss; and how often its answers ran out of tokens. Smoke runs are left out. Run from
the project root:
    python bench/tools/review_proof_table.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

from inspect_ai.log import read_eval_log

BENCH = Path(__file__).resolve().parent.parent
TASK = "review_proof_nothink"


def latest_runs(entries):
    """The last successful, non-smoke run of the task per model."""
    runs = {}
    for e in entries:
        if e.get("task") == TASK and e.get("status") == "success" and e.get("log") and e.get("label") != "smoke":
            runs[e["model"]] = e
    return runs


def outcomes(samples):
    """Sample id -> (has_bug, outcome); an answer cut at the token limit counts as "cut"."""
    out = {}
    for s in samples:
        m = next(iter(s.scores.values())).metadata or {}
        cut = s.output is not None and s.output.stop_reason == "max_tokens"
        out[str(s.id)] = (m["has_bug"], "cut" if cut else m["outcome"])
    return out


def counts(by_id):
    """Outcome counts keyed (has_bug, outcome)."""
    return Counter(by_id.values())



def pair_table(results):
    """Two reviewers in a row: a bug is caught when either proves it; a wrong test gets through when either writes one."""
    out = ["| Reviewers | Known bugs proved by either | Wrong tests from either on clean code |", "|---|---|---|"]
    names = sorted(results)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = results[a].keys() & results[b].keys()
            buggy = [k for k in shared if results[a][k][0]]
            clean = [k for k in shared if not results[a][k][0]]
            caught = sum(results[a][k][1] == "proved" or results[b][k][1] == "proved" for k in buggy)
            through = sum(results[a][k][1] == "wrong test" or results[b][k][1] == "wrong test" for k in clean)
            out.append(f"| {a} + {b} | {_cell(caught, len(buggy))} | {_cell(through, len(clean))} |")
    return "\n".join(out)


def _cell(k, n):
    return f"{k} ({k / n:.0%})" if n else "0"


def table(rows):
    """rows: (model, minutes, Counter). Shares are of all buggy or all clean solutions."""
    out = ["| Reviewer | Known bugs proved | Claims on clean code that stand | with a wrong test | "
           "with a test the reference passes | Answers cut (clean / buggy) | Minutes |", "|---|---|---|---|---|---|---|"]
    for model, minutes, c in rows:
        buggy = sum(v for (bug, _), v in c.items() if bug)
        clean = sum(v for (bug, _), v in c.items() if not bug)
        through = c[(False, "wrong test")] + c[(False, "proved")]
        out.append(f"| {model} | {_cell(c[(True, 'proved')], buggy)} | {_cell(through, clean)} | "
                   f"{_cell(c[(False, 'wrong test')], clean)} | {c[(False, 'proved')]} | "
                   f"{c[(False, 'cut')]} / {c[(True, 'cut')]} | {minutes:.0f} |")
    return "\n".join(out)


def main():
    path = BENCH / "results" / "quality.jsonl"
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows, results = [], {}
    for model, e in sorted(latest_runs(entries).items()):
        log = BENCH / "raw" / "inspect" / e["log"]
        if not log.exists():
            print(f"{log} not found", file=sys.stderr)
            continue
        results[model] = outcomes(read_eval_log(str(log)).samples or [])
        c = counts(results[model])
        rows.append((model, e.get("minutes") or 0, c))
        detail = ", ".join(f"{'buggy' if bug else 'clean'} {o}: {v}" for (bug, o), v in sorted(c.items()))
        print(f"{model}: {detail}", file=sys.stderr)
    if not rows:
        print("No review-with-proof runs yet.")
        return
    print(table(rows))
    if len(results) > 1:
        print()
        print(pair_table(results))


if __name__ == "__main__":
    main()
