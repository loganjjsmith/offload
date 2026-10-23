import os
import tempfile

from solution import JobQueue


def _queue(text, **kwargs):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "queue.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return JobQueue(path, **kwargs), path


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_jobs_skip_blank_and_comment_lines():
    q, _ = _queue("# header\n\njob a\n   \n  job b  \n  # indented comment\njob c\n")
    assert q.jobs() == ["job a", "job b", "job c"]


def test_jobs_drop_duplicates_keeping_first():
    q, _ = _queue("b\na\nb\n  a \nc\n")
    assert q.jobs() == ["b", "a", "c"]


def test_missing_files_are_empty():
    q = JobQueue(os.path.join(tempfile.mkdtemp(), "nothing.txt"))
    assert q.jobs() == []
    assert q.done() == set()
    assert q.next_job() is None
    assert q.status() == {"pending": 0, "done": 0, "given_up": 0}


def test_max_attempts_below_one_rejected():
    for bad in (0, -1):
        try:
            JobQueue("x.txt", max_attempts=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"max_attempts={bad} accepted")


def test_next_job_in_order():
    q, _ = _queue("a\nb\nc\n")
    assert q.next_job() == "a"
    q.record("a", True)
    assert q.next_job() == "b"


def test_record_success_appends_to_done_file():
    q, path = _queue("a\nb\n")
    q.record("b", True)
    q.record("a", True)
    assert _read(path + ".done") == "b\na\n"
    assert q.done() == {"a", "b"}


def test_record_success_twice_not_duplicated():
    q, path = _queue("a\n")
    q.record("a", True)
    q.record("a", True)
    assert _read(path + ".done") == "a\n"


def test_record_failure_writes_counts():
    q, path = _queue("a\nb\n", max_attempts=5)
    q.record("b", False)
    q.record("a", False)
    q.record("b", False)
    assert _read(path + ".failed") == "2\tb\n1\ta\n"
    assert q.attempts("b") == 2
    assert q.attempts("a") == 1
    assert q.attempts("never") == 0


def test_given_up_after_max_attempts():
    q, _ = _queue("a\nb\n", max_attempts=2)
    q.record("a", False)
    assert q.given_up() == []
    assert q.next_job() == "a"
    q.record("a", False)
    assert q.given_up() == ["a"]
    assert q.next_job() == "b"


def test_run_all_succeed():
    q, _ = _queue("a\nb\nc\n")
    seen = []
    result = q.run(lambda job: seen.append(job) or 0)
    assert seen == ["a", "b", "c"]
    assert result == [("a", True), ("b", True), ("c", True)]
    assert q.next_job() is None


def test_run_failure_without_retries_moves_on():
    q, _ = _queue("a\nb\n")
    result = q.run(lambda job: 1 if job == "a" else 0)
    assert result == [("a", False), ("b", True)]
    assert q.given_up() == ["a"]


def test_run_retries_immediately():
    q, _ = _queue("a\nb\n", max_attempts=3)
    calls = []

    def runner(job):
        calls.append(job)
        return 0 if job == "b" or calls.count("a") == 3 else 2

    result = q.run(runner)
    assert result == [("a", False), ("a", False), ("a", True), ("b", True)]
    assert q.done() == {"a", "b"}


def test_run_exception_is_failure():
    q, _ = _queue("a\nb\n", max_attempts=2)

    def runner(job):
        if job == "a":
            raise RuntimeError("boom")
        return 0

    assert q.run(runner) == [("a", False), ("a", False), ("b", True)]


def test_run_nonzero_codes_fail():
    q, _ = _queue("a\nb\nc\n")
    codes = {"a": -1, "b": 255, "c": 0}
    assert q.run(lambda job: codes[job]) == [("a", False), ("b", False), ("c", True)]


def test_restart_continues():
    q, path = _queue("a\nb\nc\n")
    q.record("a", True)
    again = JobQueue(path)
    assert again.run(lambda job: 0) == [("b", True), ("c", True)]


def test_restart_keeps_failure_counts():
    q, path = _queue("a\nb\n", max_attempts=3)
    q.record("a", False)
    q.record("a", False)
    again = JobQueue(path, max_attempts=3)
    assert again.attempts("a") == 2
    assert again.run(lambda job: 1 if job == "a" else 0) == [("a", False), ("b", True)]


def test_jobs_appended_while_running_are_picked_up():
    q, path = _queue("a\n")

    def runner(job):
        if job == "a":
            with open(path, "a", encoding="utf-8") as f:
                f.write("b\n")
        return 0

    assert q.run(runner) == [("a", True), ("b", True)]


def test_status_counts():
    q, _ = _queue("a\nb\nc\nd\n", max_attempts=1)
    q.record("a", True)
    q.record("b", False)
    assert q.status() == {"pending": 2, "done": 1, "given_up": 1}


def test_status_ignores_jobs_no_longer_queued():
    q, path = _queue("a\nb\n")
    q.record("a", True)
    q.record("gone", True)
    q.record("old", False)
    assert q.status() == {"pending": 1, "done": 1, "given_up": 0}


def test_reset_lets_job_run_again():
    q, path = _queue("a\nb\n")
    q.record("a", False)
    q.record("b", False)
    assert q.next_job() is None
    q.reset("a")
    assert q.attempts("a") == 0
    assert _read(path + ".failed") == "1\tb\n"
    assert q.next_job() == "a"


def test_reset_unknown_job_is_ignored():
    q, path = _queue("a\n")
    q.record("a", False)
    q.reset("zzz")
    assert _read(path + ".failed") == "1\ta\n"


def test_done_file_lines_are_stripped():
    q, path = _queue("a\nb\n")
    with open(path + ".done", "w", encoding="utf-8") as f:
        f.write("  a  \n\n")
    assert q.done() == {"a"}
    assert q.next_job() == "b"


def test_job_text_is_stripped_line():
    q, _ = _queue("   run  --flag 1   \n")
    assert q.run(lambda job: 0 if job == "run  --flag 1" else 1) == [("run  --flag 1", True)]


def test_unicode_jobs():
    q, path = _queue("café 1\n日本\n")
    q.run(lambda job: 0)
    assert q.done() == {"café 1", "日本"}
    assert _read(path + ".done") == "café 1\n日本\n"


def test_given_up_order_follows_failed_file():
    q, _ = _queue("a\nb\nc\n")
    q.record("c", False)
    q.record("a", False)
    assert q.given_up() == ["c", "a"]
