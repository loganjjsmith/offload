"""Re-score finished code-review runs from their Inspect logs with the review task's current verdict rule.

Appends one corrected entry per reviewer to results/quality.jsonl (label "rescored"), which the
summary then uses in place of the original. Run from bench/ after changing how verdicts are read.
"""
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from inspect_ai.log import read_eval_log

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH / "tasks"))
from review import final_verdict  # noqa: E402

RESULTS = BENCH / "results" / "quality.jsonl"


def rescore(entry):
    log = read_eval_log(str(BENCH / "raw" / "inspect" / entry["log"]))
    right = defaultdict(lambda: [0, 0])
    for s in log.samples or []:
        truth = "fail" if s.metadata["has_bug"] else "pass"
        got = final_verdict(s.output.completion if s.output else "")
        pair = right[s.metadata["pair"]]
        pair[0] += got == truth
        pair[1] += 1
    scores = {f"verdict/{pair}": round(hit / n, 4) for pair, (hit, n) in right.items()}
    hit, n = sum(v[0] for v in right.values()), sum(v[1] for v in right.values())
    scores["verdict/accuracy"] = round(hit / n, 4)
    return dict(entry, label="rescored", scores=scores, rescored_at=datetime.now().isoformat(timespec="seconds"))


def main():
    entries = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    originals = [e for e in entries if str(e.get("task", "")).startswith("review_fresh") and e.get("status") == "success"
                 and e.get("label") != "rescored"]
    with open(RESULTS, "a", encoding="utf-8") as f:
        for entry in originals:
            fixed = rescore(entry)
            f.write(json.dumps(fixed) + "\n")
            print(f"{entry['model']}: accuracy {entry['scores'].get('verdict/accuracy')} -> {fixed['scores']['verdict/accuracy']}")


if __name__ == "__main__":
    main()
