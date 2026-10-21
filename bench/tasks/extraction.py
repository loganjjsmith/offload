"""Extraction from a long document, scored by exact match on a JSON answer.

Each sample is a generated issue-tracker export for a fictional game project, so no model
has seen it. Answering needs the whole document read accurately and a few facts aggregated,
which is the shape of "read these files and tell me X" delegation.
"""
import json
import random
import re
from collections import Counter
from datetime import date, timedelta

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import Score, mean, scorer, stderr
from inspect_ai.solver import generate, solver

SEED = 20261015
COMPONENTS = ["Audio", "Combat", "Inventory", "Networking", "Rendering", "Save System", "UI", "World Gen"]
PEOPLE = ["Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Harper", "Jordan"]
SEVERITIES = ["minor", "major", "critical"]
STATUSES = ["open", "in progress", "fixed", "won't fix"]
VERBS = ["crashes", "stutters", "desyncs", "fails to load", "shows the wrong value", "leaks memory", "freezes"]
WHEN = ["after a scene change", "when the inventory is full", "on the second save", "with two controllers",
        "at low frame rates", "after alt-tab", "when the player respawns", "during the boss fight"]
FILLER = ["Repro steps attached in the original thread.", "Seen on the dev build only.",
          "QA could not reproduce on the release candidate.", "Possibly related to last week's refactor.",
          "Logs show a null reference just before the failure.", "Happens roughly one time in five.",
          "Workaround: reload the last checkpoint.", "Needs a decision from design before work starts."]

QUESTION = """Read the issue tracker export above and answer with a single JSON object with exactly these keys:
  "open_critical": sorted list of the ids of issues that are critical AND whose status is "open"
  "busiest_assignee": the person with the most issues whose status is "open" or "in progress"
  "component_count": number of issues whose component field is "{component}", any status
  "oldest_unresolved": id of the earliest-created issue whose status is "open" or "in progress"
Reply with the JSON only."""


def _document(rng, n):
    start = date(2026, 3, 1)
    issues = []
    for i in range(n):
        issues.append({
            "id": f"NV-{1000 + i * 7 + rng.randint(0, 6)}",
            "title": f"{rng.choice(COMPONENTS[:])} {rng.choice(VERBS)} {rng.choice(WHEN)}",
            "component": rng.choice(COMPONENTS),
            "severity": rng.choices(SEVERITIES, weights=[5, 3, 2])[0],
            "status": rng.choices(STATUSES, weights=[4, 2, 3, 1])[0],
            "assignee": rng.choice(PEOPLE),
            "created": start + timedelta(days=rng.randint(0, 200), hours=0),
            "notes": " ".join(rng.sample(FILLER, rng.randint(1, 3))),
        })
    rng.shuffle(issues)
    lines = ["ISSUE TRACKER EXPORT - project Ironwood (fictional test data)", ""]
    for x in issues:
        lines += [f"[{x['id']}] {x['title']}",
                  f"  component: {x['component']} | severity: {x['severity']} | status: {x['status']}",
                  f"  assignee: {x['assignee']} | created: {x['created'].isoformat()}",
                  f"  notes: {x['notes']}", ""]
    return issues, "\n".join(lines)


def _answer(issues, component):
    unresolved = [x for x in issues if x["status"] in ("open", "in progress")]
    counts = Counter(x["assignee"] for x in unresolved).most_common()
    oldest = min(unresolved, key=lambda x: (x["created"], x["id"]))
    return {
        "open_critical": sorted(x["id"] for x in issues if x["severity"] == "critical" and x["status"] == "open"),
        # ties make the question ambiguous; samples with a tie are regenerated
        "busiest_assignee": counts[0][0] if len(counts) < 2 or counts[0][1] > counts[1][1] else None,
        "component_count": sum(x["component"] == component for x in issues),
        "oldest_unresolved": oldest["id"] if sum(x["created"] == oldest["created"] for x in unresolved) == 1 else None,
    }


def samples(count=20):
    rng = random.Random(SEED)
    out = []
    while len(out) < count:
        n = rng.choice([25, 40, 60, 90, 130])
        issues, doc = _document(rng, n)
        if len({x["id"] for x in issues}) < n:
            continue
        component = rng.choice(COMPONENTS)
        answer = _answer(issues, component)
        if None in answer.values():
            continue
        out.append(Sample(id=f"extract-{len(out):02d}-n{n}", input=doc + "\n\n" + QUESTION.format(component=component),
                          target=json.dumps(answer), metadata={"issues": n, "doc": doc, "component": component}))
    return out


def _parse(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


@scorer(metrics=[mean(), stderr()])
def fields_correct():
    """Fraction of the four fields that are exactly right; the explanation lists the wrong ones."""
    async def score(state, target):
        want = json.loads(target.text)
        got = _parse(state.output.completion) or {}
        right = [k for k in want if got.get(k) == want[k]
                 or (k == "open_critical" and isinstance(got.get(k), list) and sorted(got[k]) == want[k])]
        wrong = [k for k in want if k not in right]
        return Score(value=len(right) / len(want), answer=json.dumps(got)[:1000],
                     explanation="all correct" if not wrong else "wrong: " + ", ".join(wrong))
    return score


@task
def extraction(count: int = 20):
    return Task(dataset=MemoryDataset(samples(count)), solver=[generate()], scorer=fields_correct())


# The same documents and questions, split the way the delegation server would do it: the model only turns
# each chunk of issues into rows, and code computes the answer from the rows. No reasoning is asked of the
# model, so this runs with thinking off.
ROWS_PROMPT = """Convert every issue in this part of an issue tracker export to JSON. Reply with a JSON array only:
one object per issue, with exactly the keys "id", "component", "severity", "status", "assignee" and "created"
(YYYY-MM-DD), each value copied exactly as written.

{chunk}"""
CHUNK_ISSUES = 20


def _rows(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    try:
        rows = json.loads(match.group(0)) if match else []
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict)]


def _answer_from_rows(rows, component):
    """The question's answer computed from extracted rows; dates compare correctly as ISO strings."""
    unresolved = [r for r in rows if r.get("status") in ("open", "in progress")]
    counts = Counter(r.get("assignee") for r in unresolved).most_common()
    oldest = min(unresolved, key=lambda r: (str(r.get("created")), str(r.get("id"))), default=None)
    return {
        "open_critical": sorted(str(r.get("id")) for r in rows if r.get("severity") == "critical" and r.get("status") == "open"),
        "busiest_assignee": counts[0][0] if counts else None,
        "component_count": sum(r.get("component") == component for r in rows),
        "oldest_unresolved": oldest.get("id") if oldest else None,
    }


@solver
def rows_then_code():
    async def solve(state, generate):
        blocks = [b for b in state.metadata["doc"].split("\n\n") if b.startswith("[")]
        rows = []
        for start in range(0, len(blocks), CHUNK_ISSUES):
            chunk = "\n\n".join(blocks[start:start + CHUNK_ISSUES])
            out = await get_model().generate(ROWS_PROMPT.format(chunk=chunk))
            rows += _rows(out.completion)
        state.metadata["rows_extracted"] = len(rows)
        state.output = ModelOutput.from_content(model=str(get_model()),
                                                content=json.dumps(_answer_from_rows(rows, state.metadata["component"])))
        return state
    return solve


@task
def extraction_rows(count: int = 20):
    return Task(dataset=MemoryDataset(samples(count)), solver=[rows_then_code()], scorer=fields_correct())
