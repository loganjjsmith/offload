# AGENTS.md — Offload

Conventions for whichever AI agent works on this project. Read fully at session start.
Rules only; where we are lives in `docs/HANDOFF.md`, where we are going lives in `docs/PLAN.md`.

## What this project is

A local AI system on Logan's PC that does the work a local model can handle, so paid cloud-agent
tokens go only to work that needs them: logic, design, and checking facts and programs.

Three layers are the goal, built iteratively so savings start early:

- **A. Delegation tools.** An MCP server any agent session can call, for example "summarise these files" or "draft this".
- **B. Autonomous local agent.** A local model with file and shell tools does whole tasks, and the cloud agent reviews them.
- **C. Local mode.** Run an agent harness entirely on a local model for easy sessions.

How far delegation goes is decided by **measurement**, not by assumption. See `docs/PLAN.md`.

## Hard rules

### Provider-agnostic by design (non-negotiable)

Logan must be able to switch cloud provider, or survive a provider disappearing, without
rebuilding this. So:

- The core speaks the **OpenAI-compatible HTTP API** that every local runtime serves (LM Studio,
  Ollama, llama.cpp). No runtime-specific API in the core, so the runtime stays swappable.
- Integrations use **open standards** (MCP) rather than one vendor's plugin format. Where a vendor-specific
  adapter is worth having (a Claude Code skill or hook, a Claude Desktop connector), it is a thin
  layer over the core and lives in its own folder under `adapters/`.
- Models, endpoints and roles live in **config**, never hardcoded.
- Agent instructions live in this file, `AGENTS.md`, the cross-vendor convention. `CLAUDE.md` only imports it.

### Holistic measurement

A model is judged on **quality × speed × fit**, never on benchmarks alone. A brilliant model that
takes an hour per answer is useless here. Every recommendation must cite numbers measured on
this machine. Blog and vendor figures are hypotheses to test, not results.

### Honest reporting

- State what actually ran. "Benchmarked 3 of 5 models; Ollama not yet tested" is a good report.
- Never claim savings that were not measured.
- Name what you did not do and any assumption you inferred.

### Machine-touching steps need Logan's OK

Installing software, downloading large models, creating scheduled tasks, changing global agent
config (`~/.claude/`), and anything on GitHub. Logan approved the broad direction on 2026-10-15
(both runtimes, thorough benchmarks, Remote Control auto-start). Each new install still gets named
before it happens.

### Logan's other projects are read-only from here

They are named in `private/projects.md` (not committed; the folders also sit in `readRoots` in
`server/config.local.json`). Their code, docs and requirements may be read as test material. Nothing is
installed, registered, configured or changed in them until it has been validated in Offload and Logan
approves (2026-10-17). The delegation server is registered for Offload only.

### Git

- `main` is the working branch for this project; commit freely as work completes.
- **Never push.** Logan pushes.
- No force-push and no history rewrites.

## Logan

- Strong Java and first-time Unity (his main other project is a Unity game). He chose to have
  this project **built for him**: he does not want to be coached through it.
- He wants to **understand** it, though: `docs/for-logan/index.html` explains local AI for his
  exact machine. Keep it current as measurements arrive, and keep it plain-language.
- His shell is **Windows PowerShell**. Commands handed to him are PowerShell: chain with `;` or
  newlines, never `&&`.

## Working practices

- Write files with the file-writing tool, never through shell heredocs or backtick-laden
  quoted strings. Both have mangled content before.
- Temporary and diagnostic artifacts go in `scratch/` (gitignored), never in tracked folders.
- Debug flags and verbose logging come out when the diagnosis ends.
- Docs are prose for a human reader, never agent shorthand.
- Comments describe the code, not the process or history.
- Small cohesive units: no god scripts, and no confetti of one-function files.
- Committed files may be published: `tooling/public_snapshot.py` builds a public branch from `main`
  (see `docs/PUBLISHING.md`). Machine-specific paths go in gitignored local config such as
  `server/config.local.json`; credentials and personal details never go in a committed file. The
  handoff log is excluded from the snapshot, so it may hold day-to-day detail.

## Machine (stable facts; measurements go in docs, not here)

| | |
|--|--|
| GPU | AMD Radeon RX 7900 XTX, 24 GB VRAM (RDNA 3) |
| iGPU | AMD Radeon Graphics on the CPU, 0.5 GB. Runtimes must not pick this by mistake |
| CPU | AMD Ryzen 9 7900X, 12 cores / 24 threads |
| RAM | 32 GB DDR5-6000 (2 × 16 GB) |
| OS | Windows 11 Pro |
| Disks | C: (~730 GB free), D:, E: |
