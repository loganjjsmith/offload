"""Tests for review_pairs on hand-made reviews. Run from the project root:
python -m unittest discover -s bench/tools -p "test_*.py"
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
from review_pairs import (PairStats, Review, is_right, latest_logs, pair_stats, pair_table,  # noqa: E402
                          reviews_from_samples)

B_PASS, B_FAIL, B_NONE = Review(True, "pass"), Review(True, "fail"), Review(True, None)
C_PASS, C_FAIL, C_NONE = Review(False, "pass"), Review(False, "fail"), Review(False, None)


class IsRight(unittest.TestCase):
    def test_buggy_needs_fail(self):
        self.assertTrue(is_right(B_FAIL))
        self.assertFalse(is_right(B_PASS))
        self.assertFalse(is_right(B_NONE))

    def test_clean_needs_pass(self):
        self.assertTrue(is_right(C_PASS))
        self.assertFalse(is_right(C_FAIL))
        self.assertFalse(is_right(C_NONE))


class PairStatsTest(unittest.TestCase):
    A = {"1": B_PASS, "2": B_PASS, "3": B_FAIL, "4": B_NONE, "5": C_PASS, "6": C_FAIL, "7": C_PASS, "x": B_PASS}
    B = {"1": B_PASS, "2": B_FAIL, "3": B_PASS, "4": B_NONE, "5": C_NONE, "6": C_FAIL, "7": C_PASS, "y": C_FAIL}

    def test_counts_over_shared_samples(self):
        self.assertEqual(pair_stats(self.A, self.B), PairStats(buggy=4, clean=3, missed_a=3, missed_b=3, missed_both=2,
                                                               alarms_a=1, alarms_b=2, alarms_either=2,
                                                               expected_missed_both=2.25))

    def test_symmetric_counts(self):
        s = pair_stats(self.B, self.A)
        self.assertEqual((s.missed_a, s.missed_b, s.alarms_a, s.alarms_b), (3, 3, 2, 1))
        self.assertEqual((s.missed_both, s.alarms_either), (2, 2))

    def test_with_itself(self):
        s = pair_stats(self.A, self.A)
        self.assertEqual((s.buggy, s.clean, s.missed_both, s.alarms_either), (5, 3, 4, 1))

    def test_no_buggy_samples_expects_zero(self):
        s = pair_stats({"1": C_FAIL}, {"1": C_PASS})
        self.assertEqual((s.buggy, s.clean, s.expected_missed_both, s.alarms_either), (0, 1, 0.0, 1))

    def test_no_shared_samples(self):
        self.assertEqual(pair_stats({"1": B_PASS}, {"2": B_PASS}), PairStats(0, 0, 0, 0, 0, 0, 0, 0, 0.0))

    def test_disagreeing_truth_names_the_sample(self):
        with self.assertRaises(ValueError) as ctx:
            pair_stats({"cs-brackets:w:v": B_PASS}, {"cs-brackets:w:v": C_PASS})
        self.assertIn("cs-brackets:w:v", str(ctx.exception))


class ReviewsFromSamples(unittest.TestCase):
    def test_last_verdict_and_missing_output(self):
        samples = [
            SimpleNamespace(id="p:w:v", metadata={"has_bug": True},
                            output=SimpleNamespace(completion='Draft {"verdict": "pass"} then {"verdict": "fail"}')),
            SimpleNamespace(id=7, metadata={"has_bug": False}, output=None),
            SimpleNamespace(id="e", metadata={"has_bug": False}, output=SimpleNamespace(completion=None)),
            SimpleNamespace(id="t", metadata={"has_bug": False},
                            output=SimpleNamespace(completion='<think>{"verdict": "fail"}</think>{"verdict": "pass"}')),
        ]
        self.assertEqual(reviews_from_samples(samples), {"p:w:v": B_FAIL, "7": C_NONE, "e": C_NONE, "t": C_PASS})


class LatestLogs(unittest.TestCase):
    def test_last_successful_run_with_a_log_wins(self):
        entries = [
            {"model": "m1", "task": "t", "status": "success", "log": "old.eval"},
            {"model": "m1", "task": "t", "status": "success", "log": "new.eval"},
            {"model": "m1", "task": "t", "status": "crashed", "log": "bad.eval"},
            {"model": "m2", "task": "other", "status": "success", "log": "o.eval"},
            {"model": "m3", "task": "t", "status": "success"},
            {"model": "m4", "task": "t", "status": "success", "log": ""},
            {"model": "m5", "task": "t", "status": "success", "log": "m5.eval"},
        ]
        self.assertEqual(latest_logs(entries, "t"), {"m1": "new.eval", "m5": "m5.eval"})


class PairTable(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(pair_table({}), "No review runs yet.")

    def test_singles_then_pairs_sorted(self):
        reviews = {
            "zed": {"1": B_PASS, "2": B_FAIL, "3": C_PASS, "4": C_PASS},
            "amy": {"1": B_PASS, "2": B_PASS, "3": C_FAIL, "4": C_PASS},
            "max": {"1": B_FAIL, "2": B_FAIL, "3": C_PASS, "4": C_FAIL},
        }
        self.assertEqual(pair_table(reviews), "\n".join([
            "| Reviewers | Bugs missed | If independent | False alarms |",
            "|---|---|---|---|",
            "| amy | 2 of 2 (100%) | – | 1 of 2 (50%) |",
            "| max | 0 of 2 (0%) | – | 1 of 2 (50%) |",
            "| zed | 1 of 2 (50%) | – | 0 of 2 (0%) |",
            "| max + zed | 0 of 2 (0%) | 0.0 | 1 of 2 (50%) |",
            "| amy + max | 0 of 2 (0%) | 0.0 | 2 of 2 (100%) |",
            "| amy + zed | 1 of 2 (50%) | 1.0 | 1 of 2 (50%) |",
        ]))

    def test_one_reviewer_rounding_and_empty_group(self):
        reviews = {"solo": {"3": C_FAIL, "4": C_NONE, "5": C_PASS}}
        self.assertEqual(pair_table(reviews), "\n".join([
            "| Reviewers | Bugs missed | If independent | False alarms |",
            "|---|---|---|---|",
            "| solo | 0 of 0 | – | 2 of 3 (67%) |",
        ]))

    def test_pair_ties_break_by_name(self):
        same = {"1": B_FAIL, "2": C_PASS}
        rows = pair_table({"c": same, "a": same, "b": same}).split("\n")[5:]
        self.assertEqual([r.split(" | ")[0] for r in rows], ["| a + b", "| a + c", "| b + c"])


if __name__ == "__main__":
    unittest.main()
