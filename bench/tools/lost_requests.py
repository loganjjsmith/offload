r"""Reproduce lost requests: long thinking-on extraction prompts sent straight to a runtime, no Inspect.

Half the requests stream and half do not. A streamed request that goes wrong shows how: no token ever
arrives (stuck in a queue), tokens stop arriving (the server stalls), or the stream never closes
after the last token (delivery). A plain request can only answer or time out.

Run from bench/:  ..\.venv\Scripts\python tools\lost_requests.py qwen3.5-9b-q8 lmstudio vulkan
Writes one JSON line per request to raw/lost-requests-<model>-<runtime>-<time>.jsonl and prints a summary.
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "tasks"))
from offload_bench import config, runtimes  # noqa: E402
from extraction import samples  # noqa: E402

MAX_TOKENS = 16384
PROMPT_ROOM = 12288
TIMEOUT_S = 1500          # a plain request with no reply by then is lost
STALL_S = 300             # a stream with no new chunk for this long has stalled


def _body(model, prompt, sampling, stream):
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": MAX_TOKENS,
            "stream": stream, **{k: v for k, v in sampling.items() if v is not None}}
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def plain(client, url, body):
    r = client.post(url, json=body, timeout=TIMEOUT_S)
    r.raise_for_status()
    out = r.json()
    return {"finish_reason": out["choices"][0].get("finish_reason"),
            "completion_tokens": (out.get("usage") or {}).get("completion_tokens")}


def streamed(client, url, body, started):
    first = last = None
    chunks = 0
    finish = usage = None
    with client.stream("POST", url, json=body, timeout=httpx.Timeout(TIMEOUT_S, read=STALL_S)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            usage = event.get("usage") or usage
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                if any(delta.get(k) for k in ("content", "reasoning_content", "reasoning")):
                    chunks += 1
                    now = time.perf_counter() - started
                    first = first if first is not None else now
                    last = now
                finish = choice.get("finish_reason") or finish
    return {"finish_reason": finish, "completion_tokens": (usage or {}).get("completion_tokens"),
            "chunks": chunks, "first_chunk_s": first and round(first, 1), "last_chunk_s": last and round(last, 1)}


def run_one(client, url, model, sample, sampling, stream, log, lock):
    started = time.perf_counter()
    rec = {"id": sample.id, "mode": "stream" if stream else "plain", "started": datetime.now().isoformat(timespec="seconds")}
    try:
        body = _body(model, sample.input, sampling, stream)
        rec.update(streamed(client, url, body, started) if stream else plain(client, url, body))
        rec["outcome"] = "ok" if rec.get("finish_reason") else "no finish reason"
    except httpx.ReadTimeout:
        rec["outcome"] = "stalled" if stream else "no reply"
    except httpx.TimeoutException as exc:
        rec["outcome"] = f"timeout: {type(exc).__name__}"
    except Exception as exc:  # any other failure is a result too
        rec["outcome"] = f"error: {type(exc).__name__}: {str(exc)[:200]}"
    rec["seconds"] = round(time.perf_counter() - started, 1)
    with lock:
        log.write(json.dumps(rec) + "\n")
        log.flush()
        print(json.dumps(rec), flush=True)
    return rec


def main():
    p = argparse.ArgumentParser()
    p.add_argument("model")
    p.add_argument("runtime")
    p.add_argument("backend")
    p.add_argument("--requests", type=int, default=16)
    p.add_argument("--parallel", type=int, default=8)
    args = p.parse_args()

    model = config.model(args.model)
    runtime = runtimes.get(args.runtime)
    endpoint = runtime.prepare(model, args.backend, MAX_TOKENS + PROMPT_ROOM, args.parallel)
    url = endpoint.base_url.rstrip("/") + "/chat/completions"
    sampling = {"temperature": model["sampling"].get("temperature"), "top_p": model["sampling"].get("top_p"),
                "top_k": model["sampling"].get("top_k")}
    prompts = (samples(20) * (1 + args.requests // 20))[:args.requests]
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    path = config.RAW_DIR / f"lost-requests-{args.model}-{args.runtime}-{stamp}.jsonl"
    lock = threading.Lock()
    try:
        with open(path, "w", encoding="utf-8") as log, httpx.Client() as client, \
                ThreadPoolExecutor(max_workers=args.parallel) as pool:
            jobs = [pool.submit(run_one, client, url, endpoint.model, s, sampling, i % 2 == 0, log, lock)
                    for i, s in enumerate(prompts)]
            results = [j.result() for j in jobs]
    finally:
        runtime.teardown()
    for mode in ("stream", "plain"):
        mine = [r for r in results if r["mode"] == mode]
        outcomes = {}
        for r in mine:
            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
        print(f"{mode}: {outcomes}")
    print("log:", path)


if __name__ == "__main__":
    main()
