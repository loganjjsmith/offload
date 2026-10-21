"""Decides whether a model is worth its long tests, from a short screen.

A model is dominated when an already-measured model scores at least as well on the screen,
writes at least as fast, and needs no more VRAM. A dominated model can never be the best
choice for any job, so it skips the expensive tests.
"""
import json

from . import config
from .report import HEADLINE


def _jsonl(name):
    path = config.RESULTS_DIR / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def screen_scores(tasks):
    """Mean screen score per model, for models that have every screen task."""
    by_model = {}
    for r in _jsonl("quality.jsonl"):
        if r.get("label") == "smoke" or r.get("status") != "success" or r["task"] not in tasks:
            continue
        value = (r.get("scores") or {}).get(HEADLINE[r["task"]][0])
        if value is not None:
            by_model.setdefault(r["model"], {})[r["task"]] = value
    return {m: sum(s.values()) / len(tasks) for m, s in by_model.items() if len(s) == len(tasks)}


def fit():
    """Best measured writing speed and smallest VRAM per model, over every runtime and backend."""
    out = {}
    for r in _jsonl("speed.jsonl"):
        if not r.get("ok") or r.get("label") not in (None, "rerun"):
            continue
        speed = r["generation"]["short"]["gen_tok_per_s"]
        vram = (r.get("gpu") or {}).get("model_dedicated_gb")
        best = out.setdefault(r["model"], {"speed": 0.0, "vram": float("inf")})
        best["speed"] = max(best["speed"], speed or 0.0)
        if vram:
            best["vram"] = min(best["vram"], vram)
    return out


def dominated_by(model_key, tasks):
    """The key of a measured model that dominates this one, or None."""
    scores, fits = screen_scores(tasks), fit()
    if model_key not in scores or model_key not in fits:
        return None
    mine, my_fit = scores[model_key], fits[model_key]
    for other, score in scores.items():
        if other == model_key or other.startswith("probe") or other not in fits:
            continue
        if score >= mine and fits[other]["speed"] >= my_fit["speed"] and fits[other]["vram"] <= my_fit["vram"]:
            return other
    return None
