"""Loads a model into a runtime on a chosen backend and hands back an OpenAI-compatible endpoint.

This is the only runtime-specific code in the harness. Everything that measures a
model talks to the endpoint returned by `prepare`.
"""
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass

from . import config

API_MODEL_ID = "bench"


@dataclass
class Endpoint:
    base_url: str
    model: str
    load_seconds: float


def _http_json(url, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


def free_default_ollama():
    """Unloads anything the tray app's Ollama server holds, so it does not share VRAM."""
    try:
        loaded = _http_json("http://127.0.0.1:11434/api/ps", timeout=5).get("models", [])
    except OSError:
        return
    for m in loaded:
        _http_json("http://127.0.0.1:11434/api/generate", {"model": m["name"], "keep_alive": 0})


class LMStudio:
    name = "lmstudio"
    # A model spilling into system RAM is a failed fit here, and the suites stop it.
    offloads_to_ram = False

    def __init__(self):
        self.cfg = config.load("runtimes")["lmstudio"]
        self.cli = str(config.expand(self.cfg["cli"]))

    def _lms(self, *args, check=True):
        result = subprocess.run([self.cli, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if check and result.returncode != 0:
            raise RuntimeError(f"lms {' '.join(args)} failed: {result.stdout}\n{result.stderr}")
        return result

    def model_key(self, file):
        """LM Studio loads by model key; quantizations of one model share a key and take an @variant."""
        listed = json.loads(self._lms("ls", "--json").stdout)
        match = next((m for m in listed if m["path"].replace("\\", "/") == file), None)
        if match is None:
            raise RuntimeError(f"LM Studio has not indexed {file}")
        siblings = [m for m in listed if m["modelKey"] == match["modelKey"]]
        if len(siblings) == 1:
            return match["modelKey"]
        return f"{match['modelKey']}@{match['quantization']['name'].lower()}"

    def prepare(self, model, backend, context_length, parallel=1, extra_args=()):
        free_default_ollama()
        self._lms("server", "start")
        self._lms("unload", "--all", check=False)
        for attempt in range(6):  # just after boot, LM Studio lists its engines late
            try:
                self._lms("runtime", "select", self.cfg["backends"][backend])
                break
            except RuntimeError:
                if attempt == 5:
                    raise
                time.sleep(20)
        key = self.model_key(model["file"])
        # context_length is per request; llama.cpp shares one context across parallel slots.
        start = time.perf_counter()
        self._lms("load", key, "--gpu", "max", "--context-length", str(context_length * parallel),
                  "--parallel", str(parallel), "--identifier", API_MODEL_ID,
                  "--ttl", str(self.cfg["idle_unload_seconds"]), "--yes", *extra_args)
        load_seconds = time.perf_counter() - start
        return Endpoint(self.cfg["base_url"], API_MODEL_ID, load_seconds)

    def teardown(self):
        self._lms("unload", "--all", check=False)


def link_into_ollama_store(path):
    """Hard-links a GGUF into Ollama's content-addressed blob store under its SHA-256 name.

    `ollama create` then finds the blob already present ("using existing layer") and does not
    copy the file, so LM Studio's file is the only copy on disk. `ollama rm` removes only
    Ollama's name for it. Digests are cached by size and modification time.
    """
    cache_file = config.RAW_DIR / "digests.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    stat = os.stat(path)
    key = f"{path}|{stat.st_size}|{stat.st_mtime_ns}"
    if key not in cache:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(16 << 20), b""):
                h.update(chunk)
        cache[key] = h.hexdigest()
        config.RAW_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    blobs = config.expand("~/.ollama/models/blobs")
    blobs.mkdir(parents=True, exist_ok=True)
    link = blobs / f"sha256-{cache[key]}"
    if not link.exists():
        os.link(path, link)


def remove_model(model):
    """Deletes a model from both runtimes: Ollama's name for it, then the LM Studio file.

    Both must go, because with hard links the data is only freed when the last name is removed.
    """
    cli = str(config.expand(config.load("runtimes")["ollama"]["cli"]))
    subprocess.run([cli, "rm", f"bench-{model['key']}"], capture_output=True)
    path = model["path"]
    if path.exists():
        path.unlink()
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()
    print(f"removed {model['key']} ({model['file']}); also delete its entry in config/models.yaml")


class Ollama:
    name = "ollama"
    offloads_to_ram = False

    def __init__(self):
        self.cfg = config.load("runtimes")["ollama"]
        self.cli = str(config.expand(self.cfg["cli"]))
        self.server = None
        self.port = None

    def _env(self, backend, context_length, parallel):
        env = dict(os.environ)
        env.update(self.cfg["common_env"])
        env.update(self.cfg["backends"][backend]["env"])
        env["OLLAMA_HOST"] = f"127.0.0.1:{self.port}"
        env["OLLAMA_CONTEXT_LENGTH"] = str(context_length)
        env["OLLAMA_NUM_PARALLEL"] = str(parallel)
        return env

    def _start_server(self, env, backend):
        config.RAW_DIR.mkdir(parents=True, exist_ok=True)
        log = open(config.RAW_DIR / f"ollama-{backend}-server.log", "ab")
        self.server = subprocess.Popen([self.cli, "serve"], env=env, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(60):
            try:
                _http_json(f"http://127.0.0.1:{self.port}/api/version", timeout=2)
                return
            except OSError:
                time.sleep(1)
        raise RuntimeError("Ollama server did not start")

    def prepare(self, model, backend, context_length, parallel=1, extra_args=()):
        free_default_ollama()
        LMStudio().teardown()
        self.port = self.cfg["backends"][backend]["port"]
        env = self._env(backend, context_length, parallel)
        self._start_server(env, backend)

        name = f"bench-{model['key']}"
        modelfile = config.RAW_DIR / f"Modelfile.{model['key']}"
        modelfile.write_text(f"FROM {model['path']}\nPARAMETER num_ctx {context_length}\n", encoding="utf-8")
        link_into_ollama_store(model["path"])
        created = subprocess.run([self.cli, "create", name, "-f", str(modelfile)], env=env,
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
        if created.returncode != 0:
            raise RuntimeError(f"ollama create failed: {created.stderr[-2000:]}")

        start = time.perf_counter()
        _http_json(f"http://127.0.0.1:{self.port}/api/generate", {"model": name, "keep_alive": "60m"})
        load_seconds = time.perf_counter() - start

        loaded = _http_json(f"http://127.0.0.1:{self.port}/api/ps").get("models", [])
        for m in loaded:
            if m.get("size") and m.get("size_vram", 0) < m["size"]:
                print(f"warning: only {m['size_vram'] / m['size']:.0%} of {name} is on the GPU")
        return Endpoint(f"http://127.0.0.1:{self.port}/v1", name, load_seconds)

    def teardown(self):
        if self.server:
            # /T also ends the runner process that holds the model in VRAM.
            subprocess.run(["taskkill", "/PID", str(self.server.pid), "/T", "/F"], capture_output=True)
            self.server.wait(timeout=30)
            self.server = None


class Strata:
    """Strata keeps a large mixture-of-experts model's busiest experts in VRAM and the rest in system RAM.

    It picks its own engine for the card, so `backend` only labels the result. The model entry names
    Strata's size and family in `strata`; Strata downloads and stores the files itself.
    """
    name = "strata"
    # System RAM holding experts is the design, so the spill guards only record it.
    offloads_to_ram = True

    def __init__(self):
        self.cfg = config.load("runtimes")["strata"]
        self.cli = str(config.expand(self.cfg["cli"]))

    def _strata(self, *args, check=True):
        result = subprocess.run([self.cli, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if check and result.returncode != 0:
            raise RuntimeError(f"strata {' '.join(args)} failed: {result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        return result

    def prepare(self, model, backend, context_length, parallel=1, extra_args=()):
        free_default_ollama()
        LMStudio().teardown()
        self._strata("launch", "--stop", check=False)
        size = model["strata"]
        start = time.perf_counter()
        self._strata("launch", "--model", size["model"], "--family", size["family"],
                     "--context", str(context_length * parallel), "--parallel", str(parallel),
                     "--vision", "off", "--tune", "skip", "--access", "local", "--port", str(self.cfg["port"]),
                     "--no-tui", "--yes", *extra_args)
        load_seconds = time.perf_counter() - start
        return Endpoint(self.cfg["base_url"], API_MODEL_ID, load_seconds)

    def teardown(self):
        self._strata("launch", "--stop", check=False)


RUNTIMES = {"lmstudio": LMStudio, "ollama": Ollama, "strata": Strata}


def get(name):
    return RUNTIMES[name]()
