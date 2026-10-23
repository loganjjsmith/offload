# Offload — Plan

Logan's goal (2026-10-15): run on his own machine whatever work it can handle well, and spend
cloud-agent tokens only where they earn their cost, so more gets done in a week. All three layers
are the goal, and delegation may go as far as fully autonomous local sub-agents, with the cloud agent doing
logic, design and fact or program checking. **How far is decided by measurement.** The work is
iterative so savings start early.

**What the subscription is for** (Logan, 2026-10-16): paying for what this machine cannot do, such as
orchestrating, thinking, planning and being a working partner, not for chores like fetching, reading and
condensing. The chores move to the local model; the exception is a chore so small that moving it saves
less than it costs to build and run.

Constraints Logan set:
- **The best this machine can do**, both in which runtime and which models, chosen by thorough
  tests. Time spent testing is fine, because the savings are long-term.
- **Holistic performance:** quality, speed and fit together. A smart model that takes an hour per
  response is not useful.
- **Agent-agnostic:** nothing that breaks if the cloud provider changes or disappears.
- **Built for him, explained to him:** the For Logan page explains how it all works on his
  exact setup.

---

## Phase 0 — Scaffold *(2026-10-15)*

Project folder, git, agent rules, Remote Control auto-start, first version of the For Logan page.

## Phase 1 — Runtimes

Install **LM Studio** and **Ollama**, both approved for testing.

1. Confirm each one actually runs on the **7900 XTX**, not on the CPU or the 0.5 GB iGPU. Check
   their logs and Task Manager's dedicated GPU memory.
2. For each runtime, list which GPU backends it offers on this machine (Vulkan, ROCm/HIP) and
   test each one. Reports conflict for RDNA 3 on Windows, and the answer can differ between
   dense and mixture-of-experts models.
3. Measure the iGPU instead of assuming. It has no memory of its own: it borrows system RAM at
   roughly a tenth of the 7900 XTX's memory bandwidth, so it can only matter for a model too big
   for 24 GB. For that case, compare discrete card plus CPU offload against discrete card plus
   iGPU split, and keep the iGPU only if it is measurably faster. For anything that fits in VRAM,
   confirm that no layers land on it.
4. Note the operational traits: runs as a background service, auto-starts, idle VRAM release,
   how models load and unload, and what its API serves (OpenAI-compatible, and an
   Anthropic-compatible endpoint if it has one, which layer C needs).

## Phase 2 — Benchmark harness and model shoot-out

A runtime-agnostic harness in `bench/` that talks to the OpenAI-compatible API, so every
runtime × backend × model combination runs the identical suite.

**Speed and fit, measured per combination:**
- generation speed (tokens/s) and prompt-processing speed (tokens/s)
- time to first token, at short, medium and long prompts
- largest context that stays fully in VRAM, and how speed falls as context grows
- VRAM used, and behaviour while Unity is open, since it competes for the same 24 GB
- model load time (cold and warm)

**Quality, scored on tasks shaped like Logan's real work:**
- summarise or extract from real files, for example the design docs and C# scripts of a Unity game project
- write a small function that has to pass tests (C#, TypeScript, Python), scored by running the tests
- find bugs planted in a code review
- tool-calling reliability: valid calls, correct arguments, recovering from errors
- following a multi-step instruction exactly

Where possible, scoring is automatic (tests pass or fail, exact-match extraction). A cloud model
judges only what cannot be checked mechanically, and sparingly.

**Standard benchmarks, the same kind as frontier-model release tables** (Logan's request, 2026-10-15). These give
scores that can be set against published numbers, so we know with real fidelity how a model *and
this system* (runtime, backend, quantization) perform on logic, coding and quality:

| Area | Benchmarks |
|---|---|
| Knowledge and reasoning | MMLU-Pro, GPQA Diamond |
| Maths and logic | AIME (latest years), MATH-500 |
| Coding | LiveCodeBench (date-filtered, so not memorised from training data), Aider Polyglot |
| Agentic coding | SWE-bench Verified (needs Docker; a subset) |
| Instruction following | IFEval |
| Tool calling | BFCL (Berkeley Function-Calling Leaderboard) |
| Long context | a needle-in-a-haystack test such as RULER, at the context sizes that fit in VRAM |

Harness: **Inspect AI** with `inspect_evals` as the primary candidate, with EleutherAI's
`lm-evaluation-harness` as the fallback. Both are open source and run against any OpenAI-compatible
endpoint, and Inspect can also run the identical suite against a cloud API if a direct
cloud-versus-local baseline is ever worth the cost. Verify both at install time.

How to read the scores:
- **Our score minus the published score is the cost of quantization and runtime.** Published
  numbers are usually full precision on datacentre hardware with the vendor's own prompts, so a
  gap is expected; measuring it is the point.
- **Runs are tiered by time.** Each benchmark has a small quick-screen subset, with confidence
  intervals, to eliminate weak candidates. Finalists get full or large runs overnight. Reasoning
  models can write thousands of tokens per question, so full suites at 30–40 tokens/s take hours.
- **The frontier column draws the line.** Next to each local score sits the published score of the
  subscription models Logan pays for, in the same area. Where the local gap is small, that area is
  a candidate for local work; where it is large, it stays on subscription tokens. Published frontier
  numbers use the vendor's own setup, so a few spot checks run the identical Inspect task against
  the cloud API to confirm the comparison is fair, kept small because they cost tokens.
- **The custom real-work tasks above still decide routing.** Standard benchmarks say how capable a
  model is; the real-work tasks say whether it is useful *for Logan's jobs*.

**Re-running when new models appear.** The suite is a fixed, versioned set: benchmark versions,
subset seeds, prompts, sampling settings and the LiveCodeBench date window are pinned in config.
A new local model, or a new runtime version, runs through one command and joins the same results table,
so scores from different months stay comparable. When a new frontier model is released, its published
scores go into the frontier column and the routing lines are checked again. Local releases get
the same watch: a new open model that fits in 24 GB, a new quantization of a current one, or a new
release of LM Studio, Ollama or their llama.cpp engines triggers a quick-screen run. If it beats the
current pick, the full run follows and the routing lines are checked again. Routing can move in both
directions, as frontier models pull ahead and local models catch up. Bumping the suite itself
(for example, moving the LiveCodeBench window forward when old problems may have leaked into training)
is a deliberate new version, and the finalists are re-run under it.

**Candidates** are refreshed at test time, because the field moves monthly. The 2026-10 starting list for
24 GB: Qwen3.6 27B / Qwen3.8 27B (dense), Qwen3-Coder 30B (MoE, ~3B active), Gemma 4 31B, plus
one small fast model (7–9B) for trivial jobs. Exact tags are verified before download.

**After the current queue: Strata** (Logan, 2026-10-16: wait until the current candidates are
benchmarked, then test it). [Strata](https://github.com/Niko1221/Strata) runs Qwen3.8-Flash-Next, a
125B mixture-of-experts model, by keeping the most-used experts in VRAM and the rest in system RAM;
MIT-licensed, Windows and Radeon 7000 listed as supported, OpenAI- and Anthropic-compatible endpoints.
The question is whether a minimal setup, on the 32 GB of RAM installed (a RAM upgrade is ruled out at
current prices), gives a real gain over the best model that fits in 24 GB.
Cautions: 32 GB of RAM is its stated minimum (64 GB runs every size; with less, some sizes read from the
SSD at 7–8 tok/s), fitting the model needs 2–3-bit quantization, the project is at v0.1.x, and its speeds
are the author's. Needs Logan's OK for the install and a ~70 GB download, then the same speed matrix and
gated quality screen as every other model.

*Result (2026-10-21):* the size that fits 32 GB is the Coder, which has half the experts pruned and is stored at
about 3.5 bits per weight. It writes at ~85 tok/s, one request at a time. Parallel slots take VRAM from its expert
cache, so four requests at once wrote 25–40 tok/s in total. On the quick screen it was the best careful
extractor measured here (95 ±3, thinking on, in a third of Gemma 31B's time) and named the planted bug every
time. It was weak at code: 61% with thinking on or off, from 6/6 in Python but 2/6 in C# and 3/6 in TypeScript
both times, the C# failures mostly code that does not compile. It needs the whole card and most of the RAM. It is a
candidate for careful extraction only. Strata's own pick for this PC (56 GB of RAM plus VRAM, 51 after its 5 GB
system reserve) is the full model at
IQ3_XXS (76 GB download); Swift 1.5 IQ2_XS (68 GB), a fine-tune that thinks less, is the other option. Either
needs Logan's OK, and probably room made by removing the Coder (86 GB with its pack).

*Module-sized Python (2026-10-22):* on eight fresh modules scored by 233 hidden tests (`modules_fresh`, three
runs each), the Coder passed 70 ±8 with thinking off and 87 ±8 with it on, against Gemma 4 31B's 96 ±2 and 96 ±1
in a quarter of the time, so it is not the coder here even in Python. Gemma 4 26B passed 74 ±8 with thinking off,
well below its 89% on short functions: module-sized work goes to the 31B. Logan's extra 100 GB of model space
(350 GB in all) was given for this testing, with long-term storage to be settled when testing ends.

**Output:** a results table in `bench/results/`, and a routing decision for each task type:
local, local with cloud review, or cloud only.

## Phase 2b — System tuning *(after the first full benchmark run)*

One change at a time, each followed by a short reference set: the speed suite for Qwen3.6 35B-A3B and
Qwen3.8 27B on their best runtime (about 10 minutes each), plus the one-minute thinking-off coding task,
which catches silent memory errors. A change stays only if it is faster and the coding score holds.
Logan makes GPU changes in AMD Software himself. Machine state on 2026-10-16: Ultimate Performance power
plan, DDR5 at its rated 6000, hardware GPU scheduling off, two monitors on the 7900 XTX (the desktop held
~1.5 GB of VRAM), and the XFX card's dual-BIOS switch on **performance** (switch away from the ports, per
XFX's quick install guide; the card reports BIOS 113-31XFSHAS1-H01). Every benchmark so far ran on the
performance BIOS, so the quiet BIOS is not a tuning step: it would only trade speed for noise.

In order of expected value:
1. Monitors on the motherboard's iGPU, which frees ~1.5 GB of VRAM; running out of VRAM slowed Qwen3.8
   tenfold on 2026-10-16. Trade-off: games pass through the iGPU with a little added latency.
   No switching is needed between work and play: Windows still renders games on the 7900 XTX (Settings >
   System > Display > Graphics, high performance) and copies each finished frame to the iGPU's output.
   The copy is what costs: a little latency and some frame rate at high refresh, and adaptive sync
   (FreeSync) may not pass through. The monitors are an MSI MPG321UX (4K, 240 Hz OLED, the gaming screen)
   and an AOC 2590G4. Copying 4K at 240 Hz is the costly case, and the motherboard's output may not
   drive 4K at 240 Hz at all. Middle option, measured first: only the AOC on the iGPU, so games on the
   OLED are untouched. It frees less than half the desktop's VRAM, since the 4K screen holds most of it;
   how much is measured, not assumed.
   **Revisit after this change:** any speed run stopped for spilling into system RAM by less than the
   VRAM freed (`spilled_to_ram_gb` in `speed.jsonl`) is re-queued, since it may fit afterwards.
2. VRAM overclock with Fast Timing. Writing speed is memory-bandwidth bound; error correction hides
   instability as lost speed, so every step is benchmarked.
3. Undervolt and a higher power limit, for prompt reading and for power and heat on long runs.
4. Optional: 64 GB RAM, so Windows can keep more than one model in its file cache and tier switches
   stop reloading from disk (loads measured at 15–50 s), and so expert-offload engines such as Strata,
   and models too big for 24 GB, become possible. Installed: 2 × 16 GB DDR5-6000 CL30 in two of an AM5
   board's four slots. Adding a second identical kit is the wrong route: four DDR5 sticks on AM5 usually
   train at 3600–5600 MT/s instead of 6000, and RAM bandwidth is exactly what CPU-side expert offload
   depends on. The right route is a 2 × 32 GB kit replacing the current one. **Declined (2026-10-16):**
   during the 2026 memory shortage it cost as much as years of subscription, which defeats the project's
   purpose. Everything, Strata included, is judged on the 32 GB installed. Revisit if prices normalise.
5. Optional: excluding model folders from Defender real-time scanning (faster loads; a security trade-off).
6. Hardware-accelerated GPU scheduling on or off; reports are mixed.
Also: Radeon Chill off; a driver update counts as a runtime release and gets the speed matrix re-run.

## Phase 3 — Layer A: delegation server

A thin MCP server we build ourselves (Node/TypeScript, official MCP SDK) in `server/`:
- tools along the lines of `summarize_files`, `extract`, `draft`, `ask_local`, finalised from the Phase 2
  routing decisions
- **reads files itself from paths it is given**, so bulk text never passes through the cloud
  model's context; that is where most of the saving comes from
- logs every call (task type, input size, output size, time), so savings can be measured, not guessed
- **a tripwire for bad handoffs** (Logan's request, 2026-10-16). A local result so poor that the cloud
  agent would have been better off with nothing wastes work twice, local time and then cloud tokens. So:
  - the cloud agent grades every handoff in one word as it uses it: `used`, `fixed` (small corrections),
    `redone` (thrown away and done again) or `misleading` (wrong in a way that cost extra work). That
    costs a few tokens and is logged with the flow: task type, model, reviewer, runtime and settings.
  - when a flow's share of `redone` and `misleading` crosses a threshold over its recent handoffs, or a
    single `misleading` result touches code, the flow is **switched off**: those jobs go to the cloud
    agent directly until the flow is looked at, and the alarm is written where the next session and Logan
    see it (`docs/HANDOFF.md` and the server log), naming the flow and showing the bad examples.
  - a switched-off flow comes back only after a fix (another model, a changed prompt, a tighter filter)
    passes a re-run of the bench task for that job, so a broken flow cannot drift back in unnoticed.
  - this also catches slow decay: a runtime or driver update, or a model swapped in config, shows up as a
    rising `redone` share before it costs much.
- **the most detail per token** (Logan's request, 2026-10-16). An invented machine language would not
  help: tokenizers are tuned to English and code, so made-up shorthand costs more tokens per idea, and
  Claude could no longer review what it cannot read. What does help:
  - terse structured answers (facts as lists with `file:line` references, no prose), which also cut the
    local model's writing, its slow side
  - pointers instead of content, so Claude reads only the lines it needs
  - detail on demand: the server keeps the full local summary and returns a short index; Claude asks
    for the sections it wants (an `expand` tool)

  Measured before it is adopted: a facts-per-token test has the local model summarise files as prose and
  in the terse format, then counts how many known facts survive per token spent.
- **condense before it reaches the cloud.** Anything bulky that the cloud agent reads only to find the
  part that matters (test runs, logs, build output, documentation, web pages, exploratory code reading)
  is filtered on this machine first. Tool output stays in the conversation for the rest of the session,
  so a bulky result is paid for again on every later turn, not just once. Two tiers, cheapest first:
  - **deterministic filters**, with no model at all, which are instant and exact: a test run reduced to
    its counts plus the failures with message and `file:line`; a log with repeated lines collapsed and
    known noise dropped; a package list reduced to what was asked about.
  - **the local model**, where judging what matters needs reading: a long log while debugging, docs,
    web pages, "how does this system work" across many files.
  - **left alone:** code the cloud agent is about to edit, which it needs word for word. Pointers
    (`file:line`) cut that reading down instead.

  Where the tokens actually go is measured, not guessed: `bench/tools/token_audit.py` counts tool output
  in the Claude Code transcripts on this machine by project and tool. First run (2026-10-16, the
  transcripts still on disk), estimated at four characters per token:

  | Source | Est. tokens | Calls | Notes |
  |---|---|---|---|
  | Reading TypeScript files (a multi-agent web app build) | 2.2 M | 1,043 | the largest single source |
  | Reading C# files (a Unity game) | 0.76 M | 443 | |
  | Reading Markdown docs (both projects) | 0.70 M | 509 | specs and reviews, often read to find one section |
  | Grep (both projects) | 0.48 M | 1,101 | |
  | Unity test runs | 0.22 M | 35 | ~6,300 each; a full pass of 40 tests is ~2,300 tokens of "Passed" records that one line could replace |
  | Unity console | 0.13 M | 102 | the debugging-log case |
  | Web search and fetch | 0.08 M | 172 | small: Claude Code already condenses pages |

  So the first wins are deterministic (test and console filters, before any model is involved), then
  local-model condensing of docs and exploratory code reading, and web tools last. Each filter is
  adopted when a before-and-after run of the audit shows the drop. The audit is re-run periodically to
  find new sources as the way Logan works changes.
- **web reading** (Logan's request, 2026-10-16), built like the file tools:
  - `web_extract(urls, question)`: the server fetches the pages, strips the HTML to text, and the local
    model returns only the facts the question asks for, each with its source URL. Pages are mostly
    menus, scripts and layout, so this is where condensing pays most, for example "breaking changes in
    the latest Unity release" across a full set of release notes.
  - `web_search(query, question)`: a search, then `web_extract` on the top results. The local model cannot
    search by itself, so this needs a search source: SearXNG (free, self-hosted, runs in the Docker
    already installed) or Brave's search API (free tier, needs a key). Either is a new install and needs
    Logan's OK.
  - **every fact carries a word-for-word quote**, and the server drops any quote that is not on the
    page. Extraction is the weakest measured task so far (19–38% with thinking off), so invented numbers
    and versions must be caught mechanically, not trusted.
  - pages are untrusted input that may carry hidden instructions. The local model gets no tools here, and
    its output reaches the cloud agent only as quoted data.
  - Measured before it is adopted: Claude Code's built-in web fetch already condenses a page with a
    small cloud model, so the saving on one page may be small. Three or four real tasks (one Unity
    release, one multi-page docs question, one comparison across several sources) run both ways, and
    cloud usage is compared.
- **checked in code before anything reaches the cloud agent** (adopted 2026-10-17): structured output is
  validated against a fixed shape and retried at most twice; every cited `file:line` must exist and every
  quoted line must match the file, or the item is dropped and the drop is reported. Free and exact,
  unlike a second model checking the first; local models are weakest at exactly this (19–45% on
  extraction with thinking off).
- later, one small capped comparison against the cheapest cloud option: the same scan job done by a
  Haiku subagent and by `summarize_files`, comparing subscription usage, so the case for local chores is
  measured against the cheap cloud tier and not only against Opus. Run once the server has real use.
- registered at **user scope**, so every project and session gets it
- delegation guidance for the agent in a user-level instructions file. **Changing it changes
  behaviour in every project, including ones Offload must not change**, so it gets Logan's OK first

## Phase 4 — Layer C: local mode

A launcher that starts an agent harness entirely on the local model, for easy sessions. Options
to test: Claude Code pointed at a local Anthropic-compatible endpoint, plus at least one
provider-neutral open-source harness, as the fallback if the provider changes. First candidate:
OpenCode (open source, plan mode, MCP, switches between cloud and local models), which may also serve
as the local agent's harness in Phase 5.

**Local chat with web search**, for everyday questions such as "how did the market do today" that need
no cloud model at all. A local chat app uses the same search source as `web_search`. Ready-made
candidates before building anything: Vane (formerly Perplexica: cited AI search on Ollama and SearXNG,
in Docker) and Jan (chat app with web search and MCP); LM Studio's chat window and Open WebUI are the
fallbacks. This saves more than routing such questions through a cloud chat: one question
costs only a few thousand cloud tokens, but sending it to the local model costs none. Pointing Claude
Desktop at the delegation server is possible too, but its built-in search would have to be switched off,
and the saving per question is small.

## Phase 5 — Layer B: autonomous local agent

The local model with file and shell tools does whole tasks. The cloud agent writes the spec and reviews
the result. Guardrails: a working folder or worktree, never a protected branch, a step limit, and
review before anything is kept. How much autonomy depends on Phase 2 numbers and Phase 3 experience.

**Terse working mode** (Logan's idea, 2026-10-16). While the local agent works, it reads and writes
code without comments or formatting; `dotnet format` (already in the .NET SDK), Prettier or Black
re-expands it deterministically, and a final local pass writes doc comments for new code. Logan's own
files are never stripped; only the agent's working copies are terse. Measured on four Unity C#
scripts with the Qwen tokenizer (20,862 tokens as written): removing comments saves 35%, minifying saves
49%. Adopted only if a terse run of the fresh coding tasks keeps the normal pass rate.

**Measured 2026-10-17: writing terse is rejected.** Fresh coding, thinking off, normal against terse:
Qwen3.6 35B-A3B 78% → 67% (20% fewer output tokens), Qwen3.8 27B 83% → 56% (45% fewer), Qwen3.5 9B
44% → 6% (64% fewer). The more a model compresses, the more it breaks, so tokens saved on writing are
paid back in failed tests and extra rounds.

**Reading terse, measured 2026-10-18: keep the comments.** Stripping comments from the code a reviewer
reads looked free with the first review prompt (Gemma 31B caught 92% against 91% with comments, about 20%
faster). With the spec-only prompt (version 2) it is not: on 232 solutions, caught / false alarms with
comments → without: Qwen3.8 81% / 11% → 75% / 14%, Gemma 31B 87% / 16% → 85% / 20%, Gemma 26B 98% / 33%
→ 96% / 42%, and no faster (24 → 29, 35 → 36, 54 → 50 minutes). The comments carry intent the
spec-only prompt leans on, so the server gives reviewers the code as written.

**Cross-model review before the cloud** (Logan's idea, 2026-10-16). Models from different vendors
tend to make different mistakes, so a second local model reviews the first one's work before the cloud
agent sees it, and each bug caught locally saves a cloud review round. Order, cheapest first: compile,
tests and linters; then the reviewer model; then the cloud agent. Both models do not fit in 24 GB
together, so reviews are batched: the writer finishes a set of changes and the reviewer loads once for
all of them. A same-model review in a fresh conversation needs no reload and is the fallback to compare
against.

The planted-bug task overstates this: it tells the model that exactly one line is wrong. Before
adoption, a realistic review task measures what matters: the solutions models already wrote in the
fresh coding tasks, with their test results, are reviewed with no hint of whether a bug exists. Failed
solutions are real bugs, passed ones are clean code, and the score is both bugs caught and false
alarms, since a false alarm makes the writer break working code. Run for each writer and reviewer
pair, including self-review, so the best reviewer for each writer is chosen by measurement.

**First live trials, before the coordinator exists** (agreed 2026-10-16; run once the benchmark queue
has finished, since a second model on the card would spill). The cloud agent plays the coordinator by
hand, so the real coordinator's spec is built from what actually happens:
1. The deterministic test-output filter from Phase 3 (a Unity test run reduced to counts plus
   failures with `file:line`): small, fully specified, mechanically tested, and worth ~2,300 tokens a
   passing run. Writer Gemma 4 26B (thinking off: 89% on fresh coding, up to ~150 tok/s), reviewer
   Gemma 4 31B (best measured reviewer: 91% of real bugs caught, 21% false alarms; Qwen3.8 27B, 83% and
   22%, is the other-vendor alternative). The two do not fit in VRAM together, so the review is batched.
   No file or shell tools needed, so nothing new is installed.
2. A larger pending item that must fit the existing harness, such as the per-writer review analysis.
3. The loop coordinator itself, specified from trials 1 and 2 and the measured reviewer catch and
   false-alarm rates.
Each records rounds, test result, and the cloud agent's approximate tokens against doing it alone.

**Trial 1 result (2026-10-17): done, `server/filters/unity-tests.ts`, 12 tests passing.** Five writer rounds
(one past the four-round limit, run on purpose to learn): a regular-expression syntax error, then a Windows
path with spaces, then pass; the reviewer found one real bug (trailing spaces after the line number),
which became a test; round 4 fixed it but broke round 3's fix; round 5 fixed both once the feedback named
the earlier pattern. The second review was a false alarm, disproved by running its own input. The cloud
sign-off found one more edge and fixed it (grade `fixed`). Local work: ~45 s of writing, 22 s of review,
~75 s of model loads; 21k prompt and 4k output tokens. Cloud tokens: hand-coordinating cost more than
writing this ~70-line module directly, as expected for a module this small; with the coordinator automated,
the cloud would write only the spec and tests and read the final code, roughly break-even here and a
saving that grows with the size of the code. Lessons for the coordinator:
- feedback that quotes the failing assertion *and* the code line responsible fixes a round fast
- always run the whole suite and tell the writer which earlier fix to keep; a writer can undo it
- reviewer claims must be executed: one of two was real
- each model swap costs ~15 s, so review in batches
- write every file from code with explicit UTF-8; a PowerShell round-trip corrupted `…` during this trial

**Trial 2 result (2026-10-22): done in one round, `bench/tools/review_pairs.py`, 14 tests passing.** The item:
for every pair of reviewers, how many real bugs both miss and how many clean solutions either flags, from the
review logs, which the coordinator needs to set how many clean reviews make a change cloud-ready. Writer Gemma 4
31B (the code-loop model since the module test), thinking off: 163 lines in 99 s (4.3k prompt, 1.7k output
tokens, ~17 tok/s with other work running on the PC). All tests passed on the first answer, and its table matches
the published per-reviewer numbers. Reviewer Qwen3.8 27B, review prompt version 2: pass, no issues, 59 s. The
cloud sign-off found no bug and made style edits only (grade `fixed`); output identical before and after.
Model loads took 35 and 41 s. Cloud tokens: the spec and 14 tests were most of the cloud's work, about as much
as writing the module directly; the saving still depends on automating the rounds and on larger items.
Lessons for the coordinator:
- a precise spec with exact output examples in the tests was enough for a first-round pass; spec quality is
  where the cloud tokens are worth spending
- load with `--parallel 1`: LM Studio's default of 4 slots spilled 1.1 GB of VRAM into RAM (0.09 GB with one)
- with LM Studio's default memory-mapped load, a loaded model keeps 14–16 GB of its file resident in system
  RAM, leaving ~0.7 GB for everything else. With mmap off (a per-model LM Studio default) loads took 12–16 s
  instead of 13–31, RAM stayed 14–16 GB free and speed was unchanged, across a three-model swap cycle
  (HANDOFF 2026-10-22 afternoon). Rule: models that fit on the card load with mmap off

**What two reviews buy** (review prompt version 2, 53 real bugs, 179 clean solutions; `review_pairs.py`):
| Reviewers | Bugs missed | If independent | False alarms |
|---|---|---|---|
| Gemma 26B alone | 1 (2%) | | 33% |
| Gemma 31B alone | 7 (13%) | | 16% |
| Qwen3.8 alone | 10 (19%) | | 11% |
| Gemma 31B + Qwen3.8 | 5 (9%) | 1.3 | 21% |
| Gemma 26B + Qwen3.6 35B-A3B | 0 | 0.1 | 54% |

The two most careful reviewers miss largely the same bugs (5 missed by both where independence predicts 1.3),
so a second clean review from a different vendor adds less than the single rates suggest. Because the
coordinator makes every claimed bug prove itself with a failing test, a false alarm costs one round rather than
broken code, which favours a high-catch reviewer such as Gemma 26B (and it is the fastest). Not yet measured:
whether a reviewer can write the failing test its claim needs. The counts are small; one bug is 2 points.

**Loop coordinator** (Logan's idea, 2026-10-16). A plain script, not a model, runs write → check →
review → fix rounds on this machine until the change is cloud-ready, so the cloud agent sees only
finished work: the spec, the final diff, the test results and a short review summary, never the
rounds in between. **The specification to build from is `docs/COORDINATOR.md`** (2026-10-22); the bullets
below are the ideas it grew from. **Built 2026-10-22** (`server/src/coordinate.ts`): on four module-sized tasks,
three were cloud-ready in 1.6–4.5 minutes, one with a reviewer-proved bug the tests missed; one stopped on a
test that never showed the writer the wrong value (COORDINATOR.md, "First real runs").
- **Cloud-ready** means the tests pass and a set number of clean reviews in a row, from different
  reviewers. The number is set from the measured miss rates: if a reviewer misses 40% of real bugs,
  one clean review is weak evidence and two from different models are stronger.
- **A claimed bug must come with a failing test.** The coordinator runs it: if it fails on the
  current code the bug is real and goes back to the writer; if it passes, the claim is dropped as a
  false alarm. This turns reviewer opinion into a mechanical check and stops nitpicking churn.
- **Guards:** the writer cannot change the tests it is judged by (checked by hash); a round limit
  (three or four); if the same change reappears, the loop is stuck; and **two rounds in a row with no
  progress stop the loop**, where progress is the number of passing tests in the full suite and a round
  that lowers it is a regression (trial 1's round 4 undid round 3's fix).
- **Decisions that need no thinker stay out of the models:** which file, which tool, retry or stop are
  code; a small local model handles any fuzzy classification; only what is still undecided reaches the
  cloud agent. (The idea behind the "JEV" step in a 2026-10-17 social post, done locally instead of
  through a paid outside service.) A stuck or over-limit task
  goes to the cloud agent with a condensed history, as a real question for the thinker.
- **Graded** by the same tripwire as every other handoff (Phase 3): a writer and reviewer pair whose
  cloud-ready work keeps coming back `redone` is switched off until it is fixed.
- **Measured** as the share of tasks that reach cloud-ready, and how many of those the cloud agent
  accepts without changes. Logan's target is that most routine work gets there.

**The success measure for this phase** is cloud tokens spent per working, tested change: Claude doing
the task alone against Claude writing the spec and reviewing while the local agent does the work.
Logan's target is 25–50% more tested code per week from the same subscription.

## Domains: a narrow slice of data and a few tools per job *(design, 2026-10-18; not built)*

Logan's idea, from a video about "nodes and edges, nouns and verbs": keep the data (nouns) apart from the
actions (verbs), so each model call sees only the part of the world its job needs, and let areas of life
meet only where that makes sense. It suits Offload better than it suits a cloud chat. Small local models
do best with a short context and a short tool list, and the measured weak spot here is tool calling over
several turns: Gemma 4 26B scored 67 on the BFCL screen, mostly lost on multi-turn questions, against
87 for Qwen3.6 35B-A3B and 77 for Gemma 4 31B. For one person, the other reason is privacy rather than
team permissions: a question about the storage server should never be able to reach personal documents.
**That fewer tools gives better calls is a hypothesis on this machine, not a result.** It is measured
first (below), and the design is only built if the numbers support it.

**Nouns: domains.** A domain is one area of Logan's work or life, for example a game project, a storage
server, personal documents, a writing project, and Offload itself. Each domain is a set of folders named in
config, plus a short index file of what is there: what each folder holds and where the important parts
are, as `file:line` pointers. A model reads the index first and then only the lines it needs, the same
"pointers instead of content" rule as Phase 3, and every pointer is checked in code before it is
trusted. Logan's files are not moved or reorganised to make a domain. Index files live in Offload, so
the game project's domain is described from here and nothing is written into that project.

**Verbs: a small tool set per domain.** Each domain gets three to five tools that fit it, rather than one
list of everything: the game project might have find-in-docs, summarise scripts and the Unity test
filter; the storage server might have read-a-log and service status, both read-only; a writing project
might have draft-a-section and check-against-the-outline. Each domain is served as **its own MCP server**, so an agent session
connects only to the domains it needs and the open-standard rule in AGENTS.md holds. To avoid a dozen
near-copies, it is one codebase (the existing server in `server/`) started once per domain with that
domain's config: its folders, its index, its tool list and its model role.

**Edges: explicit cross-domain links, in one small file.** By default a domain can read only its own
folders. Any exception is one line in a single links file: which domain may read which, how much of it,
and why. For example, the writing project may read personal documents, but only one folder of notes;
Offload may read the game project, read-only, as test material (already the rule in AGENTS.md). The server enforces the
file in code, the way `readRoots` already limits reads today, so a model cannot talk its way across a
boundary. Everything not listed stays separate. Keeping every link in one short file means Logan can
see all the ways his data can meet on one screen.

**A router chooses the domain, rules first.** With one server per domain, most routing is free: the
agent calls a tool on the server it means. Where something still has to choose (a local chat question,
or a job handed to the loop coordinator), deterministic rules go first: a domain named in the request,
the folder of any path given, a few keywords per domain. Only when the rules cannot tell does the fast
local model pick, from the domain names and one-line descriptions, with "unsure" as an allowed answer
that goes back to the asker instead of guessing. The router never widens access: picking a domain only
selects which domain's own folders and links apply. Each model decision is logged, so a choice it keeps
making can become a rule.

**Measured before anything is built.** A cheap test on the existing harness answers whether a short
tool list actually helps the local models here:
- About 20 tool-calling tasks shaped like real work, each needing one to three calls, some spread over
  several turns since that is where Gemma 26B is weakest. Each task has a known correct sequence of calls.
- Each task runs twice: once with the ~4 tools of its own domain, once with ~15 tools, the same 4 plus
  plausible tools from other domains (not random noise, which would be too easy to ignore).
- Models: Gemma 4 26B and Qwen3.6 35B-A3B, thinking off, as the server runs them.
- Scored mechanically on accuracy (right tool, valid arguments, task completed) and on time, including
  prompt tokens, since every tool description is read on every call.
- Roughly 20–30 minutes per model, run when no benchmark queue is using the card.

How the result decides the design: if the short list is clearly more accurate or faster (beyond the
standard error), the per-domain servers and the router are built. If there is no measurable difference,
domains are still worth having for privacy, but in the lighter form: the links file and per-domain
folders enforced inside the one existing server, with no per-domain servers or router.

**"Graph-based AI" means two different things, and this design touches both lightly.**
- *Knowledge graphs and GraphRAG* (nodes are things, edges are relationships). The index files and the
  links file already are a small, hand-kept graph, which is all one person's data needs for now. A full
  GraphRAG index is a later, measured trial for document-heavy domains (personal documents, writing),
  not for code: building it costs GPU hours, not Claude tokens, and it should use row extraction (the
  model writes rows, code does the rest), which scored 92–100% on this machine's four larger models
  against under 45% for free-form extraction with thinking off. Code needs no model for its graph:
  references and call graphs come from deterministic tools. No graph database unless measurement shows
  real questions that need several hops the index files cannot answer.
- *Agent graphs* (nodes are workers or steps, edges are hand-offs, as in LangGraph). Offload already has
  this shape in the router above and in the loop coordinator (Phase 5), so nothing separate is planned.

## Tuning and keeping current *(Logan's request, 2026-10-18; after the core works)*

This is fine tuning, not core enablement, so it waits until the delegation server and the domains are in
use. It covers four things.

**Better prompts per verb.** Each verb ("review this doc", "summarise these files", "extract these
fields") gets its prompt tested against a few variants on that verb's bench task, and the winner is kept
in one versioned place per verb. The first evidence that this pays off: review prompt version 2, "judge
only against the specification", cut false alarms for every reviewer and halved them for Qwen3.8 (22% to
11%), with bugs caught mostly within noise (2026-10-18). Before writing variants, review the published
prompting guidance for local models as hypotheses to test here, not as results.

**The graph: built in the cloud once, kept current locally.** A cloud session builds each domain's first
index and links, where quality matters most and it happens once. Local models then handle the routine
updates (a new file, a changed section), checked by code: the coverage check and the handoff grading
(tripwire) from Phase 3. Updates that are too risky for a local model, such as a very large document or a
change that touches many links, go to careful mode or back to the cloud.

**New verbs, routes and prompts follow the same pattern.** Each one gets a small bench task with fixed
right answers before it goes live, and the tripwire watches it afterwards.

**A new model must not need a 240-hour test.** Qualification is tiered, and each tier stops early:
1. Speed and fit on the card (minutes; the speed run already stops on spill), and a check that the
   model's thinking really switches off, since one candidate kept reasoning with it off and its fast-mode
   scores were unfairly good.
2. The two-minute gate screen against the current holder of each role (exists).
3. A small fixed regression set per verb, sized to about an hour in total, run only for the roles the
   model could win. It reuses frozen inputs such as `results/review_solutions.jsonl`, so results compare
   directly with the existing ones.
4. Full runs only for a model that wins tier 3, and only on the tasks for the role it would take.

A model can also run in shadow on real handoffs (its answer logged, not used) and be graded by the
tripwire for free, before it replaces anything.

**Watching for new techniques.** A periodic research pass (monthly, or when Logan spots something, such
as graph-based AI) lists new ways to get more out of existing models. Each is a hypothesis until a run on
this machine confirms it, and the result is recorded either way. Verified here so far: row extraction
(the model writes rows, code computes), the MTP head bundled in the GGUF (+24% writing speed on
Qwen3.6), taking the reviewer's last verdict rather than its first, and the spec-only review prompt.
Verified and dropped: stripping comments from code before review (free with the first review prompt,
worse with the spec-only one).

## Later

Expand by evidence: more task types, multi-model routing (a small fast model for trivial jobs, a big
one for harder ones), Claude Desktop connectors, and setup scripts so a new machine is one command.
