Write a Python module that turns benchmark result records into a Markdown table.

## Records

Results are stored as JSON Lines: one JSON object per line. Each record has at least `model`, `task`,
`status` and `started` (an ISO 8601 timestamp string; comparing these strings compares the times). A
successful record (`status == "success"`) also has `scores` (an object of metric name to number, in a
meaningful order), `samples` (an integer) and optionally `errored_samples` (an integer, default 0).

## API

- `load(path) -> list[dict]`: read a JSON Lines file. Blank lines (including lines of only whitespace)
  are skipped. A line that is not valid JSON, or is valid JSON but not an object, raises `ValueError`
  whose message contains `line N`, where N is the 1-based line number in the file.
- `latest(records) -> dict[tuple[str, str], dict]`: for each `(model, task)` pair, the record to show:
  the successful record with the greatest `started`; if the pair has no successful record, the record
  with the greatest `started` of any status. When two candidates have the same `started`, the one that
  comes later in `records` wins.
- `headline(record) -> tuple[float, float | None] | None`: the record's main score. It is the first
  metric in `scores` whose name ends with `/accuracy` or `/mean`. The error is the metric whose name is
  that name's prefix (everything before the last `/`) followed by `/stderr`, or `None` if there is no
  such metric. Returns `(value, error)`, or `None` if the record has no `scores` or no headline metric.
- `cell(record) -> str`: the table text for one record.
  - A record whose status is not `"success"` shows `failed: <status>`.
  - A successful record with no headline shows `no score`.
  - Otherwise the value as a percentage, rounded to a whole number with halves rounded up (so 0.125
    shows as 13 and 0.875 as 88), then ` ±E` where E is the error as a percentage rounded the same way,
    only if the error is not `None` and E is at least 1. Then, in parentheses, `n=<samples>`, followed by
    `, <k> unanswered` if `errored_samples` is more than 0. Examples: `83 ±9 (n=18)`, `100 (n=12)`,
    `40 ±11 (n=20, 2 unanswered)`.
- `table(records, tasks, models=None) -> str`: a Markdown table built from `latest(records)`.
  - The header row is `| Model | <task 1> | <task 2> | ... |` for the given `tasks` in order, then a
    separator row `|---|---|...|` with one `---` per column (including Model).
  - One row per model: the given `models` in their order, or if `models` is `None`, every model that has
    a record for at least one of `tasks`, sorted by name.
  - Each row is `| <model> | <cell> | ... |`, with `—` (an em dash) where the model has no record for a
    task.
  - Rows are joined with `"\n"` and the result has no trailing newline.
- `best(records, task) -> str | None`: among the latest records for `task` that are successful and have a
  headline, the model with the highest headline value. Ties go to the name that sorts first. `None` if
  there is no such record.
