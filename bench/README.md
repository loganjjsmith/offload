# bench — measuring local models on this machine

This folder answers one question with numbers measured on this PC: for each kind of job, is a
local model good enough and fast enough, or should the job go to the cloud?

It measures three things for each model, runtime and GPU backend:

- **Speed and fit** (`speed`): load time, VRAM used, how fast the model reads a prompt, and how
  fast it writes an answer, for short prompts, after a long prompt, and for long answers.
- **Standard benchmarks** (`quality`): the same kind of tests vendors publish (GPQA, MMLU-Pro,
  IFEval, BFCL, MATH, AIME), run through [Inspect AI](https://inspect.aisi.org.uk/), so our numbers
  can be set against published ones and against frontier models.
- **Fresh real-work tasks** (`quality`, tasks ending in `_fresh`): coding to spec in Python,
  TypeScript and C#, finding a planted bug, and extracting facts from a long document. They were
  written for this project on 2026-10-15, after every candidate model was released, so no model
  can have memorised them.
- **Code review of model-written code** (`quality --only review_fresh_nothink`): each model reviews
  the solutions the models wrote for the coding tasks, with no hint of whether a bug exists. It is
  scored on bugs caught and false alarms, per writer, so self-review and cross-model review can be
  compared. The first run freezes the set of solutions in `results/review_solutions.jsonl`, so run it
  only after every model's coding runs.

## Setup (once)

From the project root, in PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install inspect-ai==0.3.281 inspect-evals==0.24.0 openai sympy "antlr4-python3-runtime==4.11" https://github.com/josejg/instruction_following_eval/archive/refs/heads/main.zip
docker build -t offload-bench-sandbox:1 bench\tasks\sandbox
.venv\Scripts\python bench\tasks\validate_coding.py
.venv\Scripts\python bench\tasks\validate_coding.py --bugs
```

LM Studio and Ollama must be installed, and Docker Desktop running for the coding tasks.

## Running

All commands run from the `bench` folder:

```powershell
cd bench
..\.venv\Scripts\python -m offload_bench speed qwen3.8-27b-q4xl lmstudio vulkan
..\.venv\Scripts\python -m offload_bench matrix qwen3.8-27b-q4xl
..\.venv\Scripts\python -m offload_bench quality qwen3.8-27b-q4xl lmstudio vulkan
..\.venv\Scripts\python -m offload_bench quality qwen3.8-27b-q4xl lmstudio vulkan --only coding_fresh bugfind_fresh
..\.venv\Scripts\python -m offload_bench queue queues\overnight-2026-10-15.txt
```

`matrix` runs the speed suite on every runtime and backend. `queue` runs one command per line of
a text file and skips lines it has already finished, so a long unattended run survives a restart.

Results are appended to `results/speed.jsonl` and `results/quality.jsonl`, one JSON object per
run. Full Inspect logs, with every prompt and answer, go to `raw/inspect/` (not committed); open
them with `..\.venv\Scripts\inspect view --log-dir raw\inspect`.

## One copy of each model

Every GGUF is downloaded once, into LM Studio's models folder. When Ollama needs a model, the
harness hard-links that file into Ollama's blob store under its SHA-256 name, so `ollama create`
reuses it instead of copying ("using existing layer"). Both runtimes then read the same file, with no
extra disk. Because the data is freed only when every name for it is gone, delete models with
`..\.venv\Scripts\python -m offload_bench remove <model>`, which removes both, and then drop the
model's entry from `config/models.yaml`.

## When a new model or runtime version comes out

1. Download the GGUF into LM Studio's models folder and add an entry to `config/models.yaml`.
2. Run its speed matrix and the quick quality screen (`--tier quick`).
3. If it beats the current pick for its tier, run `--tier full` and update the routing.

A new LM Studio or Ollama release, or a new llama.cpp engine in LM Studio, is the same: re-run
the speed matrix for the current picks.

The suite itself is pinned (`config/suite.yaml`: versions, sample counts and the shuffle seed),
so scores from different months are comparable. Changing it is a new suite version, and the
current picks are re-run under it.

## Layout

| Path | What it is |
|---|---|
| `config/models.yaml` | Candidate models, their tier and the vendor's recommended sampling |
| `config/runtimes.yaml` | LM Studio and Ollama, and their GPU backends |
| `config/speed.yaml` | The speed suite: context size, prompt lengths, answer lengths |
| `config/suite.yaml` | The quality suite: tasks, sample counts, token budget |
| `offload_bench/runtimes.py` | The only runtime-specific code: load a model, return an endpoint |
| `offload_bench/speed.py`, `quality.py` | The two suites |
| `offload_bench/gpu.py` | Per-adapter GPU load and VRAM from Windows performance counters |
| `tasks/` | The fresh task sets and the Docker sandbox that runs model-written code |
| `tools/` | One-off measurements: `token_audit.py` counts which tool output fills the cloud agent's context, from Claude Code transcripts; `terse_tokens.py` measures terse code |
| `queues/` | Queue files for unattended runs, and their `.done` records |
| `results/` | Measured results (committed) |
