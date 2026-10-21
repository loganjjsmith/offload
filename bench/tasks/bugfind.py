"""Find a planted bug: a correct reference solution with one line changed.

The references and their tests come from coding/*.yaml; each mutation below breaks the
tests (checked by validate_coding.py --bugs). The model names the line, and is scored on
the line number.
"""
import json
import re
import sys
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, scorer, stderr
from inspect_ai.solver import generate

sys.path.insert(0, str(Path(__file__).parent))
from coding import problems  # noqa: E402

# problem id -> (exact text to replace on one line, replacement)
MUTATIONS = {
    "py-stack-items": ("take = min(max_stack - slot[1], qty)", "take = min(max_stack, qty)"),
    "py-build-order": ("if indeg[u] == 0:", "if indeg[u] <= 1:"),
    "py-lru": ("self.data.popitem(last=False)", "self.data.popitem(last=True)"),
    "py-wrap": ("elif len(cur) + 1 + len(p) <= width:", "elif len(cur) + len(p) <= width:"),
    "py-semver": ("return -1 if xd else 1", "return 1 if xd else -1"),
    "ts-grid-path": ("if (nr < 0 || nr >= grid.length || nc < 0 || nc >= grid[nr].length) continue;",
                     "if (nr < 0 || nr > grid.length || nc < 0 || nc >= grid[0].length) continue;"),
    "ts-wildcard": ('(pattern[p] === "?" || pattern[p] === text[t])', '(pattern[p] === text[t])'),
    "ts-damage": ("const hp = Math.max(0, state.hp - d);", "const hp = Math.max(0, state.hp - damage);"),
    "cs-ring-buffer": ("else { items[start] = item; start = (start + 1) % items.Length; }",
                       "else { items[start] = item; }"),
    "cs-dijkstra": ("if (d > dist[u]) continue;", "if (d >= dist[u]) continue;"),
    "cs-cooldown": ("if (Charges == max) elapsed = 0;", "elapsed = 0;"),
    "cs-brackets": ("return stack.Count == 0 ? -1 : stack.Min();", "return stack.Count == 0 ? -1 : stack.Peek();"),
}

PROMPT = """The following {language} code is meant to satisfy the specification below, but exactly one line contains a bug.

Specification:
{spec}

Code (line numbers added for reference):
{numbered}

Reply with a JSON object: {{"line": <the line number of the buggy line>, "fix": "<the corrected line>"}}"""


def mutated(problem):
    old, new = MUTATIONS[problem["id"]]
    lines = problem["reference"].rstrip("\n").split("\n")
    hits = [i for i, line in enumerate(lines) if old in line]
    if len(hits) != 1:
        raise ValueError(f"{problem['id']}: mutation text must match exactly one line, matched {len(hits)}")
    lines[hits[0]] = lines[hits[0]].replace(old, new)
    return "\n".join(lines) + "\n", hits[0] + 1


def samples():
    out = []
    for p in problems():
        if p["id"] not in MUTATIONS:
            continue
        code, line = mutated(p)
        numbered = "\n".join(f"{i + 1:3d}  {text}" for i, text in enumerate(code.rstrip("\n").split("\n")))
        out.append(Sample(id=f"bug-{p['id']}", target=str(line),
                          input=PROMPT.format(language=p["language"], spec=p["prompt"].strip(), numbered=numbered)))
    return out


@scorer(metrics=[accuracy(), stderr()])
def right_line():
    async def score(state, target):
        text = re.sub(r"<think>.*?</think>", "", state.output.completion, flags=re.DOTALL)
        match = re.search(r'"line"\s*:\s*"?(\d+)', text)
        got = match.group(1) if match else None
        return Score(value=CORRECT if got == target.text else INCORRECT, answer=got,
                     explanation=f"expected line {target.text}")
    return score


@task
def bugfind():
    return Task(dataset=MemoryDataset(samples()), solver=[generate()], scorer=right_line())
