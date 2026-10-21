"""Speed-and-fit suite: load time, VRAM, prompt processing and generation speed.

Long prompts are built from Python standard-library source, which is real code of the
kind the delegation server will read. Every prompt starts with a fresh nonce so no
runtime can answer from a prompt cache.
"""
import json
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import client, config, gpu, runtimes

LONG_ANSWER = ("Write a long, thorough tutorial on implementing a B-tree in Python: explain the "
               "invariants, then give complete code for insert, search and delete with comments, then "
               "walk through a worked example step by step. Do not stop early.")
MAX_BASELINE_VRAM = 4e9  # the desktop and ordinary apps use 1-2 GB; more means a model is still loaded
# Shared memory the load adds beyond what the desktop already uses (0.2-0.3 GB). More means the model
# did not fit in VRAM: Gemma 4 31B on LM Studio ROCm spilled 2.7 GB and ran at a tenth of its speed.
MAX_SPILL = 0.5e9
SHORT_ANSWER ="Explain, in detail, how a hash map handles collisions and resizing."


def _corpus():
    lib = Path(sys.base_prefix) / "Lib"
    parts = []
    for name in ["argparse.py", "asyncio/base_events.py", "collections/__init__.py", "dataclasses.py",
                 "difflib.py", "email/message.py", "inspect.py", "json/decoder.py", "logging/__init__.py",
                 "pathlib.py", "statistics.py", "subprocess.py", "tarfile.py", "typing.py", "zipfile/__init__.py"]:
        p = lib / name
        if p.exists():
            parts.append(f"# ===== {name} =====\n" + p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


class PromptBuilder:
    """Builds prompts of a target token length, calibrated against the model's own tokenizer."""

    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.corpus = _corpus()
        sample = self.corpus[:8000]
        t = client.chat(endpoint.base_url, endpoint.model, self._messages(sample, "Reply with OK."), max_tokens=1)
        self.chars_per_token = len(sample) / max(t.prompt_tokens, 1)

    @staticmethod
    def _messages(text, question):
        return [{"role": "user", "content": f"[{uuid.uuid4()}]\n{text}\n\n{question}"}]

    def build(self, tokens, question):
        chars = int(tokens * self.chars_per_token)
        text = (self.corpus * (1 + chars // len(self.corpus)))[:chars]
        return self._messages(text, question)


def _median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def run(model_key, runtime_name, backend, extra_load_args=(), label=None):
    cfg = config.load("speed")
    model = config.model(model_key)
    runtime = runtimes.get(runtime_name)
    result = {
        "model": model_key, "runtime": runtime_name, "backend": backend, "label": label,
        "file": model["file"], "context_length": cfg["context_length"], "parallel": cfg["parallel"],
        "repeats": cfg["repeats"],
        "extra_load_args": list(extra_load_args), "started": datetime.now().isoformat(timespec="seconds"),
    }
    runtimes.free_default_ollama()
    baseline = max(gpu.snapshot().values() or [0.0])
    result["vram_in_use_before_gb"] = round(baseline / 1e9, 2)
    if baseline > MAX_BASELINE_VRAM:
        result.update(ok=False, error=f"{baseline / 1e9:.1f} GB of VRAM already in use before loading; "
                                      "another model or app is holding the card")
        _save(result)
        return result
    shared_before = max(gpu.snapshot("Shared").values() or [0.0])
    try:
        with gpu.Sampler() as sampler:
            endpoint = runtime.prepare(model, backend, cfg["context_length"], cfg["parallel"], extra_load_args)
            result["load_s"] = round(endpoint.load_seconds, 2)
            shared = max(gpu.snapshot("Shared").values() or [0.0])
            result["spilled_to_ram_gb"] = round(shared / 1e9, 2)
            if not runtime.offloads_to_ram and shared - shared_before > MAX_SPILL:
                raise RuntimeError(f"spilled {(shared - shared_before) / 1e9:.1f} GB into system RAM at load: "
                                   "does not fit in VRAM at this context, so the speed runs were skipped")
            builder = PromptBuilder(endpoint)

            prompt = {}
            for n in cfg["prompt_lengths"]:
                runs = [client.chat(endpoint.base_url, endpoint.model,
                                    builder.build(n, "Reply with OK."), max_tokens=1)
                        for _ in range(cfg["repeats"])]
                prompt[n] = {"prompt_tokens": runs[0].prompt_tokens,
                             "ttft_s": _median([r.ttft_s for r in runs]),
                             "prompt_tok_per_s": _median([r.prompt_tok_per_s for r in runs])}
            result["prompt_processing"] = prompt

            gen = {}
            for name, shape in cfg["generation"].items():
                question = LONG_ANSWER if shape["answer"] > 1024 else SHORT_ANSWER
                runs = [client.chat(endpoint.base_url, endpoint.model, builder.build(shape["prompt"], question),
                                    max_tokens=shape["answer"])
                        for _ in range(cfg["repeats"])]
                gen[name] = {"prompt_tokens": runs[0].prompt_tokens,
                             "completion_tokens": _median([r.completion_tokens for r in runs]),
                             "ttft_s": _median([r.ttft_s for r in runs]),
                             "gen_tok_per_s": _median([r.gen_tok_per_s for r in runs])}
            result["generation"] = gen
        result["gpu"] = sampler.summary()
        if result["gpu"]:
            result["gpu"]["model_dedicated_gb"] = round(result["gpu"]["card_peak_dedicated_gb"] - baseline / 1e9, 2)
        result["ok"] = True
    except Exception as exc:  # a failed combination is a result too
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"[:2000]
    finally:
        runtime.teardown()
    result["finished"] = datetime.now().isoformat(timespec="seconds")
    _save(result)
    return result


def _save(result):
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.RESULTS_DIR / "speed.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")
