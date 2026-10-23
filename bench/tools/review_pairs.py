"""Pair up code reviewers: how many bugs both members of a pair miss, and how many clean solutions either flags.

A loop that asks a second reviewer only when the first passes a change lets a bug through when both miss it.
The table sets each pair's joint misses beside what independent reviewers would give, from the review task's
Inspect logs. Run from the project root: python bench/tools/review_pairs.py [task]
"""
import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple

from inspect_ai.log import read_eval_log

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH / "tasks"))
from review import final_verdict  # noqa: E402


class Review(NamedTuple):
    has_bug: bool          # ground truth
    verdict: str | None    # "pass", "fail", or None when the answer had no readable verdict


class PairStats(NamedTuple):
    buggy: int
    clean: int
    missed_a: int
    missed_b: int
    missed_both: int
    alarms_a: int
    alarms_b: int
    alarms_either: int
    expected_missed_both: float


def is_right(review: Review) -> bool:
    """True when the verdict matches the ground truth; an unreadable verdict is never right."""
    return review.verdict == ("fail" if review.has_bug else "pass")


def pair_stats(a: dict[str, Review], b: dict[str, Review]) -> PairStats:
    """Compare two reviewers over shared sample IDs."""
    shared_ids = set(a.keys()) & set(b.keys())
    buggy, clean = 0, 0
    missed_a, missed_b, missed_both = 0, 0, 0
    alarms_a, alarms_b, alarms_either = 0, 0, 0

    for i in shared_ids:
        ra, rb = a[i], b[i]
        if ra.has_bug != rb.has_bug:
            raise ValueError(f"Sample {i} has different ground truth in reviewers")

        right_a, right_b = is_right(ra), is_right(rb)
        if ra.has_bug:
            buggy += 1
            if not right_a:
                missed_a += 1
            if not right_b:
                missed_b += 1
            if not right_a and not right_b:
                missed_both += 1
        else:
            clean += 1
            if not right_a:
                alarms_a += 1
            if not right_b:
                alarms_b += 1
            if not right_a or not right_b:
                alarms_either += 1

    expected = (missed_a * missed_b / buggy) if buggy > 0 else 0.0
    return PairStats(buggy, clean, missed_a, missed_b, missed_both, alarms_a, alarms_b, alarms_either, expected)


def reviews_from_samples(samples) -> dict[str, Review]:
    """Convert Inspect samples into a map of sample ID to Review."""
    reviews = {}
    for s in samples:
        completion = s.output.completion if s.output else None
        verdict = final_verdict(completion)
        reviews[str(s.id)] = Review(has_bug=s.metadata["has_bug"], verdict=verdict)
    return reviews


def latest_logs(entries: list[dict], task: str) -> dict[str, str]:
    """Find the most recent successful log for each model in a given task."""
    latest = {}
    for e in entries:
        if e.get("task") == task and e.get("status") == "success" and e.get("log"):
            latest[e["model"]] = e["log"]
    return latest


def pair_table(reviews: dict[str, dict[str, Review]]) -> str:
    """Generate a Markdown table comparing reviewer performance in pairs."""
    if not reviews:
        return "No review runs yet."

    def fmt_cell(k, n):
        if n == 0:
            return "0 of 0"
        return f"{k} of {n} ({k / n:.0%})"

    lines = [
        "| Reviewers | Bugs missed | If independent | False alarms |",
        "|---|---|---|---|"
    ]

    names = sorted(reviews.keys())
    for name in names:
        s = pair_stats(reviews[name], reviews[name])
        lines.append(f"| {name} | {fmt_cell(s.missed_a, s.buggy)} | \u2013 | {fmt_cell(s.alarms_a, s.clean)} |")

    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            s = pair_stats(reviews[a], reviews[b])
            pairs.append((a, b, s))

    pairs.sort(key=lambda x: (x[2].missed_both, x[2].alarms_either, f"{x[0]} + {x[1]}"))

    for a, b, s in pairs:
        lines.append(f"| {a} + {b} | {fmt_cell(s.missed_both, s.buggy)} | {s.expected_missed_both:.1f} "
                     f"| {fmt_cell(s.alarms_either, s.clean)} |")

    return "\n".join(lines)


def main(argv=None):
    """Print the pair table for a review task's latest run per reviewer."""
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="?", default="review_fresh_v2_nothink")
    args = parser.parse_args(argv)

    quality_file = BENCH / "results" / "quality.jsonl"
    if not quality_file.exists():
        return

    entries = []
    with open(quality_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    log_map = latest_logs(entries, args.task)
    all_reviews = {}

    for model, log_name in log_map.items():
        log_path = BENCH / "raw" / "inspect" / log_name
        if not log_path.exists():
            print(f"Log file {log_path} not found", file=sys.stderr)
            continue
        log = read_eval_log(str(log_path))
        all_reviews[model] = reviews_from_samples(log.samples or [])

    print(pair_table(all_reviews))


if __name__ == "__main__":
    main()
