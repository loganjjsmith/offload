import json
import math


def load(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"line {number}: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"line {number}: not an object")
            out.append(record)
    return out


def latest(records):
    best = {}
    for r in records:
        key = (r["model"], r["task"])
        current = best.get(key)
        ok = r.get("status") == "success"
        if current is None:
            best[key] = r
            continue
        current_ok = current.get("status") == "success"
        if ok and not current_ok:
            best[key] = r
        elif ok == current_ok and r["started"] >= current["started"]:
            best[key] = r
    return best


def headline(record):
    scores = record.get("scores") or {}
    for name, value in scores.items():
        if name.endswith(("/accuracy", "/mean")):
            err = scores.get(name.rsplit("/", 1)[0] + "/stderr")
            return value, err
    return None


def _pct(x):
    return math.floor(x * 100 + 0.5)


def cell(record):
    if record.get("status") != "success":
        return f"failed: {record.get('status')}"
    h = headline(record)
    if h is None:
        return "no score"
    value, err = h
    text = str(_pct(value))
    if err is not None and _pct(err) >= 1:
        text += f" ±{_pct(err)}"
    note = f"n={record['samples']}"
    if record.get("errored_samples", 0) > 0:
        note += f", {record['errored_samples']} unanswered"
    return f"{text} ({note})"


def table(records, tasks, models=None):
    rows = latest(records)
    if models is None:
        models = sorted({m for (m, t) in rows if t in tasks})
    lines = ["| Model | " + " | ".join(tasks) + " |", "|" + "---|" * (len(tasks) + 1)]
    for m in models:
        cells = [cell(rows[(m, t)]) if (m, t) in rows else "—" for t in tasks]
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def best(records, task):
    found = []
    for (m, t), r in latest(records).items():
        if t == task and r.get("status") == "success" and headline(r) is not None:
            found.append((-headline(r)[0], m))
    return min(found)[1] if found else None
