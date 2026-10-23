import os
import tempfile

from solution import best, cell, headline, latest, load, table


def _ok(model, task, started, value, err=None, samples=20, errored=0, metric="s/accuracy"):
    scores = {metric: value}
    if err is not None:
        scores[metric.rsplit("/", 1)[0] + "/stderr"] = err
    r = {"model": model, "task": task, "status": "success", "started": started, "scores": scores,
         "samples": samples}
    if errored:
        r["errored_samples"] = errored
    return r


def _bad(model, task, started, status="crashed"):
    return {"model": model, "task": task, "status": status, "started": started}


def _file(text):
    path = os.path.join(tempfile.mkdtemp(), "r.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def test_load_skips_blank_lines():
    path = _file('{"a": 1}\n\n   \n{"b": 2}\n')
    assert load(path) == [{"a": 1}, {"b": 2}]


def test_load_bad_json_names_line():
    path = _file('{"a": 1}\n\n{oops\n')
    try:
        load(path)
    except ValueError as exc:
        assert "line 3" in str(exc)
    else:
        raise AssertionError("bad JSON accepted")


def test_load_non_object_names_line():
    path = _file('{"a": 1}\n[1, 2]\n')
    try:
        load(path)
    except ValueError as exc:
        assert "line 2" in str(exc)
    else:
        raise AssertionError("array line accepted")


def test_latest_prefers_newest_success():
    old = _ok("m", "t", "2026-01-01T10:00:00", 0.5)
    new = _ok("m", "t", "2026-01-02T10:00:00", 0.7)
    assert latest([new, old])[("m", "t")] is new


def test_latest_success_beats_newer_failure():
    good = _ok("m", "t", "2026-01-01T10:00:00", 0.5)
    crash = _bad("m", "t", "2026-01-05T10:00:00")
    assert latest([good, crash])[("m", "t")] is good


def test_latest_failure_only():
    a = _bad("m", "t", "2026-01-01T10:00:00", "error")
    b = _bad("m", "t", "2026-01-03T10:00:00", "cancelled")
    assert latest([b, a])[("m", "t")] is b


def test_latest_tie_goes_to_later_record():
    a = _ok("m", "t", "2026-01-01T10:00:00", 0.5)
    b = _ok("m", "t", "2026-01-01T10:00:00", 0.6)
    assert latest([a, b])[("m", "t")] is b


def test_latest_keys():
    rs = [_ok("m", "t", "1", 0.5), _ok("m", "u", "1", 0.5), _ok("n", "t", "1", 0.5)]
    assert set(latest(rs)) == {("m", "t"), ("m", "u"), ("n", "t")}


def test_headline_accuracy_with_stderr():
    r = _ok("m", "t", "1", 0.83, 0.09, metric="hidden_tests/accuracy")
    assert headline(r) == (0.83, 0.09)


def test_headline_first_matching_metric():
    r = {"status": "success", "scores": {"x/count": 3, "a/mean": 0.4, "a/stderr": 0.1, "b/accuracy": 0.9}}
    assert headline(r) == (0.4, 0.1)


def test_headline_without_stderr():
    r = {"status": "success", "scores": {"a/accuracy": 1.0, "other/stderr": 0.2}}
    assert headline(r) == (1.0, None)


def test_headline_none():
    assert headline({"status": "success", "scores": {"a/count": 3}}) is None
    assert headline({"status": "success"}) is None


def test_cell_basic():
    assert cell(_ok("m", "t", "1", 0.83, 0.09, samples=18)) == "83 ±9 (n=18)"


def test_cell_no_error_shown_when_zero():
    assert cell(_ok("m", "t", "1", 1.0, 0.0, samples=12)) == "100 (n=12)"


def test_cell_no_error_shown_when_rounds_to_zero():
    assert cell(_ok("m", "t", "1", 0.5, 0.004, samples=12)) == "50 (n=12)"


def test_cell_without_stderr_metric():
    assert cell(_ok("m", "t", "1", 0.5, samples=4)) == "50 (n=4)"


def test_cell_unanswered():
    assert cell(_ok("m", "t", "1", 0.4, 0.11, samples=20, errored=2)) == "40 ±11 (n=20, 2 unanswered)"


def test_cell_rounds_half_up():
    assert cell(_ok("m", "t", "1", 0.125, 0.875, samples=8)) == "13 ±88 (n=8)"
    assert cell(_ok("m", "t", "1", 0.625, samples=8)) == "63 (n=8)"


def test_cell_failed():
    assert cell(_bad("m", "t", "1", "crashed")) == "failed: crashed"


def test_cell_no_score():
    r = {"model": "m", "task": "t", "status": "success", "started": "1", "scores": {"x/count": 1}, "samples": 3}
    assert cell(r) == "no score"


def test_table_layout():
    rs = [_ok("beta", "t1", "1", 0.5, 0.1, samples=10), _ok("alpha", "t2", "1", 0.75, samples=4),
          _ok("alpha", "t1", "1", 1.0, samples=10)]
    assert table(rs, ["t1", "t2"]) == (
        "| Model | t1 | t2 |\n"
        "|---|---|---|\n"
        "| alpha | 100 (n=10) | 75 (n=4) |\n"
        "| beta | 50 ±10 (n=10) | — |")


def test_table_models_given():
    rs = [_ok("b", "t", "1", 0.5, samples=2), _ok("a", "t", "1", 0.5, samples=2)]
    assert table(rs, ["t"], models=["b", "zzz", "a"]).splitlines()[2:] == [
        "| b | 50 (n=2) |", "| zzz | — |", "| a | 50 (n=2) |"]


def test_table_only_models_with_listed_tasks():
    rs = [_ok("a", "t", "1", 0.5, samples=2), _ok("b", "other", "1", 0.5, samples=2)]
    assert table(rs, ["t"]).splitlines()[2:] == ["| a | 50 (n=2) |"]


def test_table_uses_latest_and_failures():
    rs = [_ok("a", "t", "2026-01-01", 0.2, samples=5), _ok("a", "t", "2026-02-01", 0.6, samples=5),
          _bad("b", "t", "2026-01-01", "error")]
    assert table(rs, ["t"]).splitlines()[2:] == ["| a | 60 (n=5) |", "| b | failed: error |"]


def test_table_no_trailing_newline():
    assert not table([_ok("a", "t", "1", 0.5)], ["t"]).endswith("\n")


def test_best_highest():
    rs = [_ok("a", "t", "1", 0.5), _ok("b", "t", "1", 0.9), _ok("c", "t", "1", 0.7)]
    assert best(rs, "t") == "b"


def test_best_tie_alphabetical():
    rs = [_ok("zed", "t", "1", 0.9), _ok("amy", "t", "1", 0.9)]
    assert best(rs, "t") == "amy"


def test_best_uses_latest_and_skips_failures():
    rs = [_ok("a", "t", "2026-01-01", 0.99), _ok("a", "t", "2026-02-01", 0.1), _ok("b", "t", "2026-01-01", 0.5),
          _bad("c", "t", "2026-01-01")]
    assert best(rs, "t") == "b"


def test_best_none():
    assert best([], "t") is None
    assert best([_bad("a", "t", "1")], "t") is None
