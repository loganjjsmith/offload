"""A minimal streaming client for OpenAI-compatible chat endpoints, with timing."""
import json
import time
import urllib.request
from dataclasses import dataclass


@dataclass
class Timing:
    prompt_tokens: int
    completion_tokens: int
    ttft_s: float
    total_s: float

    @property
    def prompt_tok_per_s(self):
        return self.prompt_tokens / self.ttft_s if self.ttft_s > 0 else None

    @property
    def gen_tok_per_s(self):
        gen_time = self.total_s - self.ttft_s
        if self.completion_tokens < 2 or gen_time <= 0:
            return None
        return (self.completion_tokens - 1) / gen_time


def chat(base_url, model, messages, max_tokens, temperature=0.0, extra=None, timeout=1800):
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    body.update(extra or {})
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    first = None
    chunks = 0
    usage = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            event = json.loads(line[5:])
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning"):
                    if first is None:
                        first = time.perf_counter()
                    chunks += 1
    end = time.perf_counter()
    if first is None:
        first = end
    return Timing(
        prompt_tokens=(usage or {}).get("prompt_tokens", 0),
        completion_tokens=(usage or {}).get("completion_tokens", chunks),
        ttft_s=first - start,
        total_s=end - start,
    )
