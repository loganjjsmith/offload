"""Loads the YAML files in bench/config."""
import os
from pathlib import Path

import yaml

BENCH_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BENCH_DIR / "config"
RESULTS_DIR = BENCH_DIR / "results"
RAW_DIR = BENCH_DIR / "raw"


def load(name):
    with open(CONFIG_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def expand(path):
    return Path(os.path.expanduser(path))


def model(key):
    cfg = load("models")
    models = cfg["models"]
    if key not in models:
        raise SystemExit(f"Unknown model '{key}'. Known: {', '.join(models)}")
    entry = dict(models[key])
    entry["key"] = key
    entry["path"] = expand(load("runtimes")["lmstudio"]["models_dir"]) / entry["file"]
    entry["sampling"] = cfg["sampling"][entry["family"]]
    return entry
