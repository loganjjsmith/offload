Write a Python module that runs jobs from a plain-text queue file, one after another, and survives
being stopped and restarted.

## Files

- The **queue file** at `path` lists one job per line. Each line is stripped of surrounding whitespace;
  blank lines and lines whose first character after stripping is `#` are ignored. A job is the stripped
  line text. If the same job appears more than once, only its first occurrence counts.
- The **done file** is `path + ".done"`: one finished job per line, appended as jobs succeed.
- The **failed file** is `path + ".failed"`: one line per job that has failed at least once, written as
  `<attempts>\t<job>`, in the order the jobs first failed. It is rewritten whenever a count changes.
- Files that do not exist are treated as empty. All files are UTF-8 and written with `"\n"` line endings.
- Every method re-reads the files it needs, so jobs appended to the queue file while it runs are picked
  up, and a new `JobQueue` on the same path continues where an earlier one stopped.

## API

`class JobQueue(path: str, max_attempts: int = 1)` — `max_attempts` below 1 raises `ValueError`.

- `jobs() -> list[str]`: the queue's jobs in file order, without duplicates.
- `done() -> set[str]`: the jobs listed in the done file (lines stripped, blank lines ignored).
- `attempts(job: str) -> int`: how many times `job` has failed, from the failed file; 0 if never.
- `given_up() -> list[str]`: jobs that failed `max_attempts` times or more, in failed-file order.
- `next_job() -> str | None`: the first job in queue order that is neither done nor given up, or `None`.
- `record(job: str, ok: bool) -> None`: when `ok`, append `job` to the done file (unless it is already
  there). When not `ok`, add one to the job's count in the failed file (adding the job at the end if it
  is new).
- `run(runner) -> list[tuple[str, bool]]`: repeatedly take `next_job()`, call `runner(job)` and record the
  outcome, until `next_job()` returns `None`. `runner` returns an exit code: `0` is success, anything else
  is failure. If `runner` raises an `Exception`, that is a failure too and the loop continues. Returns
  every `(job, ok)` pair in the order the calls were made. Because `next_job()` returns the first
  unfinished job, a failed job that still has attempts left is retried straight away.
- `status() -> dict`: `{"pending": p, "done": d, "given_up": g}`, where `p` counts queue jobs that are
  neither done nor given up, `d` counts queue jobs that are done, and `g` counts queue jobs that are given
  up. Jobs in the done or failed file that are no longer in the queue are not counted.
- `reset(job: str) -> None`: forget a job's failures by removing its line from the failed file, so it
  runs again. Jobs that are not in the failed file are ignored.
