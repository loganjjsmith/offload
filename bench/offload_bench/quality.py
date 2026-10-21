"""Standard-benchmark quality suite, run through Inspect AI against the local endpoint."""
import json
import os
import threading
import time
from datetime import datetime

from . import config, gate, gpu, runtimes


def _scores(log):
    """Headline metrics from an Inspect log: every metric of the first scorer."""
    if not log.results or not log.results.scores:
        return {}
    out = {}
    for score in log.results.scores:
        for name, metric in score.metrics.items():
            out[f"{score.name}/{name}"] = round(metric.value, 4)
    return out


def _token_usage(log):
    usage = {}
    for model_usage in (log.stats.model_usage or {}).values():
        usage["input_tokens"] = usage.get("input_tokens", 0) + model_usage.input_tokens
        usage["output_tokens"] = usage.get("output_tokens", 0) + model_usage.output_tokens
        usage["reasoning_tokens"] = usage.get("reasoning_tokens", 0) + (model_usage.reasoning_tokens or 0)
    return usage


MAX_SPILL_BYTES = 0.5e9  # more than this in shared system memory means the load did not fit; 0.7 GB cut speed tenfold
# Growth in shared memory after a clean load: Windows can move VRAM out to system RAM mid-run when other
# apps need the card, and the run then crawls (2-3 tok/s on 2026-10-16) until requests time out.
MAX_MIDRUN_SPILL = 1e9
SPILL_POLL_S = 30


class _SpillWatch(threading.Thread):
    """Records peak shared memory during a run; unloads the model if it grows past MAX_MIDRUN_SPILL twice running."""

    def __init__(self, runtime):
        super().__init__(daemon=True)
        self.runtime = runtime
        self.baseline = max(gpu.snapshot("Shared").values() or [0.0])
        self.peak = self.baseline
        self.tripped = False
        self._stop = threading.Event()

    def run(self):
        strikes = 0
        while not self._stop.wait(SPILL_POLL_S):
            shared = max(gpu.snapshot("Shared").values() or [0.0])
            self.peak = max(self.peak, shared)
            if self.runtime.offloads_to_ram:
                continue
            strikes = strikes + 1 if shared - self.baseline > MAX_MIDRUN_SPILL else 0
            if strikes >= 2:
                self.tripped = True
                print(f"spilled {(shared - self.baseline) / 1e9:.1f} GB into system RAM mid-run; stopping", flush=True)
                self.runtime.teardown()
                return

    def stop(self):
        self._stop.set()

    def report(self):
        return {"spill_baseline_gb": round(self.baseline / 1e9, 2), "spill_peak_gb": round(self.peak / 1e9, 2)}


def _prepare(runtime, model, backend, context_length, parallel):
    """Loads with as many parallel slots as fit in VRAM, halving on failure or on spill to system RAM."""
    while True:
        try:
            endpoint = runtime.prepare(model, backend, context_length, parallel)
            spill = max(gpu.snapshot("Shared").values() or [0.0])
            if runtime.offloads_to_ram or spill <= MAX_SPILL_BYTES or parallel == 1:
                return endpoint, parallel
            print(f"{parallel} slots spill {spill / 1e9:.1f} GB to system RAM; halving")
        except RuntimeError:
            if parallel == 1:
                raise
        runtime.teardown()
        parallel //= 2


def run(model_key, runtime_name, backend, tier="quick", only=None, label=None, limit=None, max_tokens=None,
        gated=False):
    from inspect_ai import eval as inspect_eval
    from inspect_ai.model import GenerateConfig

    suite = config.load("suite")
    model = config.model(model_key)
    gen = dict(suite["generate"])
    if max_tokens:
        gen["max_tokens"] = max_tokens
    names = only or [n for n, t in suite["tasks"].items() if not t.get("on_request")]  # --only also sets the order
    screen = suite["screen"]
    if gated:
        done = gate.screen_scores(screen)
        if model_key in done and (by := gate.dominated_by(model_key, screen)):
            _record_gate(suite, model_key, label, by)
            return []
        names = [n for n in screen if model_key not in done] + [n for n in names if n not in screen]
    tasks = {n: suite["tasks"][n] for n in names
             if model["tier"] in suite["tasks"][n].get("tiers", [model["tier"]])}

    runtime = runtimes.get(runtime_name)
    endpoint, parallel = _prepare(runtime, model, backend, gen["max_tokens"] + gen["prompt_room"], gen["parallel"])
    gen = dict(gen, parallel=parallel)
    os.environ["LOCAL_BASE_URL"] = endpoint.base_url
    os.environ["LOCAL_API_KEY"] = "local"
    # Inspect's HTTP client cuts every request at 600 s unless told otherwise, below GenerateConfig's own
    # timeouts. Long thinking-on answers (16k tokens at ~17 tok/s per slot take ~16 min) were cut, retried
    # and lost until 2026-10-17; the same requests sent directly all returned.
    os.environ["INSPECT_HTTP_REQUEST_TIMEOUT"] = str(gen["attempt_timeout_s"])
    sampling = model["sampling"]
    generate = GenerateConfig(
        max_tokens=gen["max_tokens"], max_connections=gen["parallel"], timeout=gen["timeout_s"],
        attempt_timeout=gen["attempt_timeout_s"],
        temperature=sampling.get("temperature"), top_p=sampling.get("top_p"), top_k=sampling.get("top_k"),
        max_retries=2,
    )
    results = []
    watch = _SpillWatch(runtime)
    watch.start()
    try:
        for name, task in tasks.items():
            started = time.perf_counter()
            entry = {"suite": suite["version"], "task": name, "area": task["area"], "tier": tier, "parallel": parallel,
                     "model": model_key, "runtime": runtime_name, "backend": backend, "label": label,
                     "started": datetime.now().isoformat(timespec="seconds")}
            settings = generate.model_dump(exclude_none=True)
            settings.update(task.get("generate", {}))
            if max_tokens:
                settings["max_tokens"] = min(settings["max_tokens"], max_tokens)
            entry["max_tokens"] = settings["max_tokens"]
            try:
                logs = inspect_eval(task["task"], model=f"openai-api/local/{endpoint.model}",
                                    task_args=task.get("task_args", {}),
                                    limit=limit or task["limit"][tier], sample_shuffle=suite["sample_seed"],
                                    epochs=1,
                                    log_dir=str(config.RAW_DIR / "inspect"), display="none",
                                    fail_on_error=gen["fail_on_error"], score_on_error=True, **settings)
                log = logs[0]
                entry.update(status=log.status, samples=len(log.samples or []) or log.results.total_samples,
                             errored_samples=sum(1 for s in log.samples or [] if s.error),
                             scores=_scores(log), usage=_token_usage(log), log=os.path.basename(log.location))
                if log.error:
                    entry["error"] = str(log.error.message)[:1000]
            except Exception as exc:
                entry.update(status="crashed", error=f"{type(exc).__name__}: {exc}"[:2000])
            entry["minutes"] = round((time.perf_counter() - started) / 60, 1)
            entry.update(watch.report())
            if watch.tripped:
                entry.update(status="spilled", error="spilled into system RAM mid-run; model unloaded and the run stopped")
            _save(entry)
            results.append(entry)
            print(json.dumps({k: entry.get(k) for k in ("task", "status", "samples", "scores", "minutes", "error")}),
                  flush=True)
            if watch.tripped:
                break
            if gated and name == screen[-1] and (by := gate.dominated_by(model_key, screen)):
                _record_gate(suite, model_key, label, by)
                break
    finally:
        watch.stop()
        runtime.teardown()
    return results


def _record_gate(suite, model_key, label, by):
    print(f"{model_key} is dominated by {by} on the screen; skipping its long tests", flush=True)
    _save({"suite": suite["version"], "task": "gate", "model": model_key, "label": label,
           "status": "dominated", "dominated_by": by, "screen": suite["screen"],
           "started": datetime.now().isoformat(timespec="seconds")})


def _save(entry):
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.RESULTS_DIR / "quality.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
