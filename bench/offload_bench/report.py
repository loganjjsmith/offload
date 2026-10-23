"""Builds results/summary.md from the speed and quality results and the published scores."""
import json
from collections import defaultdict

import yaml

from . import config

# Headline metric per task, and the published-score key it compares with.
HEADLINE = {
    "gpqa_diamond": ("choice/accuracy", "gpqa_diamond"),
    "mmlu_pro": ("choice/accuracy", "mmlu_pro"),
    "ifeval": ("instruction_following/final_acc", "ifeval"),
    "bfcl": ("bfcl_scorer/accuracy", "bfcl_v4"),
    "math500": ("expression_equivalance/accuracy", None),
    "aime2026": (None, "aime2026"),
    "coding_fresh": ("hidden_tests/accuracy", None),
    "bugfind_fresh": ("right_line/accuracy", None),
    "extraction_fresh": ("fields_correct/mean", None),
    "coding_fresh_nothink": ("hidden_tests/accuracy", None),
    "coding_fresh_terse_nothink": ("hidden_tests/accuracy", None),
    "bugfind_fresh_nothink": ("right_line/accuracy", None),
    "extraction_fresh_nothink": ("fields_correct/mean", None),
    "extraction_rows_nothink": ("fields_correct/mean", None),
    "modules_fresh": ("tests_passed/mean", None),
    "modules_fresh_nothink": ("tests_passed/mean", None),
}


def _jsonl(name):
    path = config.RESULTS_DIR / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _headline(task, scores):
    metric = HEADLINE.get(task, (None, None))[0]
    if metric and metric in scores:
        value, err = scores[metric], scores.get(metric.rsplit("/", 1)[0] + "/stderr")
        return value, err
    for k, v in scores.items():
        if k.endswith(("/accuracy", "/mean")):
            return v, scores.get(k.rsplit("/", 1)[0] + "/stderr")
    return None, None


def _fmt(v, digits=0):
    return "—" if v is None else f"{v:.{digits}f}"


def speed_table(rows):
    latest = {}
    for r in rows:
        label = r.get("label")
        if label in ("smoke", "harness-test"):
            continue
        variant = r["backend"] + (f" ({label})" if label and label != "rerun" else "")
        latest[(r["model"], r["runtime"], variant)] = r
    out = ["| Model | Runtime / backend | Load s | Model VRAM GB | Read tok/s @4k | Read tok/s @30k | "
           "Write tok/s short | Write tok/s after 15k prompt | Write tok/s long answer | iGPU peak load |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for (model, runtime, backend), r in sorted(latest.items()):
        if not r.get("ok"):
            out.append(f"| {model} | {runtime} / {backend} | failed: {r.get('error', '')[:120]} |||||||||")
            continue
        pp, gen, gpu = r["prompt_processing"], r["generation"], r.get("gpu") or {}
        igpu = max((gpu.get("other_adapters_peak_load_pct") or {"": 0}).values())
        out.append(f"| {model} | {runtime} / {backend} | {_fmt(r['load_s'], 1)} | {_fmt(gpu.get('model_dedicated_gb'), 1)} | "
                   f"{_fmt(pp['4096']['prompt_tok_per_s'])} | {_fmt(pp['30000']['prompt_tok_per_s'])} | "
                   f"{_fmt(gen['short']['gen_tok_per_s'])} | {_fmt(gen['deep']['gen_tok_per_s'])} | "
                   f"{_fmt(gen['long']['gen_tok_per_s'])} | {_fmt(igpu)}% |")
    return "\n".join(out)


def quality_table(rows, published):
    cells = defaultdict(dict)
    for r in rows:
        if r.get("label") == "smoke" or r.get("status") != "success":
            continue
        value, err = _headline(r["task"], r.get("scores") or {})
        cells[r["model"]][r["task"]] = (value, err, r.get("samples"), r.get("minutes"), r.get("errored_samples"))
    tasks = [t for t in HEADLINE if any(t in c for c in cells.values())]
    head = "| Model | " + " | ".join(tasks) + " |"
    out = [head, "|---|" + "---|" * len(tasks)]
    for model, by_task in sorted(cells.items()):
        pub = (published.get(model) or {}).get("scores", {})
        row = []
        for t in tasks:
            if t not in by_task:
                row.append("—")
                continue
            value, err, n, minutes, lost = by_task[t]
            lost_note = f", {lost} unanswered, scored as wrong" if lost else ""
            text = f"{value * 100:.0f}" + (f" ±{err * 100:.0f}" if err else "") + f" (n={n}, {minutes:.0f} min{lost_note})"
            key = HEADLINE[t][1]
            if key and key in pub:
                text += f"<br>published {pub[key]}"
            row.append(text)
        out.append(f"| {model} | " + " | ".join(row) + " |")
    return "\n".join(out)


def review_table(rows, task="review_fresh_nothink"):
    """Reviewer by writer: share of buggy solutions caught and of clean ones wrongly failed."""
    latest = {r["model"]: r["scores"] for r in rows
              if r.get("task") == task and r.get("status") == "success"}
    if not latest:
        return "No review runs yet."
    # Per-writer scores are accuracy on that writer's buggy and clean solutions, keyed "verdict/<writer> buggy".
    # The totals are weighted from them by the frozen solution counts, which also show how small each group is.
    counts = defaultdict(int)
    for r in _jsonl("review_solutions.jsonl"):
        counts[(r["writer"], "buggy" if r["has_bug"] else "clean")] += 1
    writers = sorted({w for w, _ in counts})
    head = [f"{w} ({counts[(w, 'buggy')]} buggy / {counts[(w, 'clean')]} clean): caught / false alarms" for w in writers]
    out = ["| Reviewer | Bugs caught | False alarms | " + " | ".join(head) + " |",
           "|---|---|---|" + "---|" * len(writers)]
    for model, s in sorted(latest.items()):
        acc = lambda w, kind: s.get(f"verdict/{w} {kind}")  # noqa: E731
        caught = _weighted([(acc(w, "buggy"), counts[(w, "buggy")]) for w in writers])
        alarms = _weighted([(None if acc(w, "clean") is None else 1 - acc(w, "clean"), counts[(w, "clean")])
                            for w in writers])
        pairs = [f"{_pct(acc(w, 'buggy'))} / {_pct(None if acc(w, 'clean') is None else 1 - acc(w, 'clean'))}"
                 for w in writers]
        out.append(f"| {model} | {_pct(caught)} | {_pct(alarms)} | " + " | ".join(pairs) + " |")
    return "\n".join(out)


def _weighted(pairs):
    pairs = [(v, n) for v, n in pairs if v is not None and n]
    total = sum(n for _, n in pairs)
    return sum(v * n for v, n in pairs) / total if total else None


def _pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def build():
    published = yaml.safe_load((config.RESULTS_DIR / "published.yaml").read_text(encoding="utf-8"))
    text = "\n\n".join([
        "# Results summary",
        "Generated by `python -m offload_bench report` from `speed.jsonl`, `quality.jsonl` and `published.yaml`.",
        "## Speed and fit",
        "Context 32k, one request at a time, median of repeats. Read = prompt processing; write = generation.",
        speed_table(_jsonl("speed.jsonl")),
        "## Quality",
        "Scores in percent with ± one standard error, from the quick screen unless noted. Thinking mode with "
        "the vendor's sampling and a 16k-token budget per answer. Published figures are the vendor's, at full "
        "precision, on their own harness.",
        quality_table(_jsonl("quality.jsonl"), published),
        "## Code review of model-written code",
        "Each reviewer judges the fresh coding solutions the models wrote, with no hint of whether a bug exists. "
        "Failed solutions are real bugs, passed ones are clean; code that did not compile is left out. Thinking off. "
        "The writer columns compare self-review with cross-model review.",
        review_table(_jsonl("quality.jsonl")),
        "### The same review, reading the code without comments",
        "Comments and docstrings stripped from the code under review (28% fewer characters); the reviewer "
        "still answers normally. Compare with the table above.",
        review_table(_jsonl("quality.jsonl"), "review_fresh_terse_nothink"),
        "### The same review with prompt version 2, judged only against the specification",
        "A bug counts only if the reviewer can give an input the specification covers; null or malformed input "
        "the specification never mentions, style and performance are not bugs. Code as written, with comments.",
        review_table(_jsonl("quality.jsonl"), "review_fresh_v2_nothink"),
        "### Prompt version 2, reading the code without comments",
        "Both changes together, the way the delegation server will run reviews.",
        review_table(_jsonl("quality.jsonl"), "review_fresh_v2_terse_nothink"),
    ]) + "\n"
    (config.RESULTS_DIR / "summary.md").write_text(text, encoding="utf-8")
    return text
