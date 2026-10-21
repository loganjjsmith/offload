"""Runs benchmark jobs one after another from a plain-text queue file.

Each non-blank, non-comment line is the arguments of one `python -m offload_bench`
command. The file is re-read after every job, so jobs can be appended while it runs.
Finished lines are recorded in <file>.done, so a restarted queue skips them. Each job
runs in its own process, so a crash or hang in one cannot take down the rest.
"""
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

JOB_TIMEOUT_S = 8 * 3600  # thinking-mode quality screens on a 27B dense model run for hours


def _pending(queue_file, done_file):
    done = set(done_file.read_text(encoding="utf-8").splitlines()) if done_file.exists() else set()
    for line in queue_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in done:
            return line
    return None


def run(queue_file):
    queue_file = Path(queue_file)
    done_file = queue_file.with_name(queue_file.name + ".done")
    while (job := _pending(queue_file, done_file)) is not None:
        print(f"{datetime.now():%H:%M:%S} START {job}", flush=True)
        started = time.perf_counter()
        try:
            code = subprocess.run([sys.executable, "-m", "offload_bench", *shlex.split(job)],
                                  timeout=JOB_TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        minutes = (time.perf_counter() - started) / 60
        print(f"{datetime.now():%H:%M:%S} END   {job}  exit={code}  {minutes:.1f} min", flush=True)
        with open(done_file, "a", encoding="utf-8") as f:
            f.write(job + "\n")
    print(f"{datetime.now():%H:%M:%S} queue empty", flush=True)
