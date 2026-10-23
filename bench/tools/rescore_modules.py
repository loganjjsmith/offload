"""Re-scores a finished module-task run from its Inspect log, with the current code extractor and tests.

The run's answers are re-extracted and re-tested in the sandbox image, the scores are reduced the way
Inspect does (mean over epochs per task, then mean and standard error over tasks), and a corrected copy
of the run's results.jsonl entry is appended, marked `rescored`. The Inspect log itself is not changed.
Used when a scoring fault is found after a run, such as the extractor that cut code at a "```" inside a
string (2026-10-22). From bench/:
    ..\\.venv\\Scripts\\python tools\\rescore_modules.py raw\\inspect\\<log>.eval --reason "..."
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from inspect_ai.log import read_eval_log

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH / "tasks"))
from modules import extract_code, tasks  # noqa: E402
from validate_modules import run  # noqa: E402

RESULTS = BENCH / "results" / "quality.jsonl"


def rescore(log_path, reason):
    log = read_eval_log(str(log_path))
    by_id = {t["id"]: t for t in tasks()}
    per_task = defaultdict(list)
    for s in log.samples:
        t = by_id[s.id]
        share, _ = run(extract_code(s.output.completion), t["tests"], t["count"])
        old = next(iter(s.scores.values())).value
        if abs(share - old) > 1e-9:
            print(f"{s.id} run {s.epoch}: {old:.2f} -> {share:.2f}")
        per_task[s.id].append(share)
    means = [sum(v) / len(v) for v in per_task.values()]
    n = len(means)
    mean = sum(means) / n
    err = math.sqrt(sum((m - mean) ** 2 for m in means) / (n - 1)) / math.sqrt(n) if n > 1 else 0.0
    scores = {"tests_passed/mean": round(mean, 4), "tests_passed/stderr": round(err, 4),
              "tests_passed/all_passed": round(sum(1.0 for m in means if m == 1.0) / n, 4)}
    entries = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    original = next(e for e in reversed(entries) if e.get("log") == os.path.basename(log_path))
    entry = dict(original, scores=scores, rescored=f"{datetime.now():%Y-%m-%d}: {reason}",
                 original_scores=original["scores"])
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps({"was": original["scores"], "now": scores}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    rescore(Path(args.log), args.reason)


if __name__ == "__main__":
    main()
