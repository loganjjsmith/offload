# How Offload is built

Offload is built by AI coding agents (Claude Code) and directed by Logan Smith. This page describes how
that collaboration is set up, what each side does, and where the discipline of measuring everything
caught mistakes that would otherwise have shaped the design.

## Who does what

**Logan** sets the goal and the constraints, decides anything that touches the machine or money, and
contributes much of the design. The goal: run locally whatever this PC can do well, so a fixed cloud
subscription stretches further. The constraints, written down on day one: the best this machine can do,
chosen by tests rather than by reputation; quality, speed and fit judged together ("a smart model that
takes an hour per response is not useful"); nothing that breaks if the cloud provider changes or
disappears; and a plain-language explanation of how it all works on this exact machine.

Several of the central ideas in [`PLAN.md`](PLAN.md) are his, and are credited there by date:

- cross-model review, so a second local model from a different vendor checks the first one's work
  before the cloud agent sees it
- a loop coordinator, a plain script that runs write, test and review rounds locally and shows the cloud
  agent only finished work
- a tripwire that switches off any delegation flow whose results are worse than nothing
- the most detail per token: terse answers with `file:line` pointers instead of content
- domains: keeping data apart from actions so each model call sees only what its job needs
- tiered routing, like choosing between small, medium and large cloud models
- trying terse code to save tokens (measured, and rejected; see below)

He also made the calls that cost money or touch hardware: which runtimes to install, the download
budget for models, declining a RAM upgrade when memory prices made it cost as much as years of
subscription, and every system setting. Research is shared: candidates such as the Strata expert-offload
runtime, which gave promising first results, came out of looking at what was new together.

**The agents** do the engineering: building the benchmark harness and the delegation server, running and
analysing the benchmarks, writing the documentation, and proposing next steps with the evidence for
them. Logan did not write the code. He is new to local AI and uses the project to learn it, which is
what the plain-language explainer is for.

## The rules the agents work under

The rules live in [`AGENTS.md`](../AGENTS.md), the cross-vendor convention, so any agent can pick them up;
`CLAUDE.md` only imports it. The ones that shape the work most:

- **Measure, never assume.** Every recommendation cites numbers measured on this machine. Vendor and blog
  figures are hypotheses to test. Small samples are reported with their error bars, and a difference
  within noise is called noise.
- **Report honestly.** State what actually ran, what did not, and what was inferred. Savings that were
  not measured are not claimed.
- **Provider-agnostic by design.** The core speaks the OpenAI-compatible API that every local runtime
  serves; integrations use MCP, an open standard; models and endpoints live in config. Vendor-specific
  pieces are thin adapters.
- **Ask before touching the machine.** Installing software, large downloads, scheduled tasks and global
  agent settings each need Logan's approval, named before it happens. Agents commit to the working
  branch but never push.
- **Another project is read-only.** Logan's game project serves as realistic test material, but nothing is
  installed or changed there until it has been validated here and he approves.

## How work carries across sessions

An agent session has no memory of the last one, so continuity lives in files:

- a **plan** ([`PLAN.md`](PLAN.md)): where the project is going, with each decision dated and its evidence
- a **handoff** log, kept in the private repository: what is running, what just finished, what the next
  session should do first. Long benchmark queues run unattended overnight in a restartable queue, and the
  next session starts by reading the queue's log and the handoff.
- the **results** (`bench/results/`): every run appends one JSON line, and a report script regenerates the
  readable summary, so no number in the docs depends on an agent's memory
- the **explainer** ([`for-logan/index.html`](for-logan/index.html)), kept current as results arrive

## Where measurement caught mistakes

The most useful thing about measuring everything is that it catches the agents' own errors. Some
examples, all recorded as they happened:

- **A metric that could not move.** The first code-review results showed every reviewer catching 0% or
  100% of bugs. The metric compared an aggregated value against the wrong constant; it was fixed and the
  summary rebuilt from the per-sample scores.
- **Scoring the wrong verdict.** With thinking off, reviewers reason inline and often revise a draft
  verdict; the scorer took the first one. 32 of one model's 232 verdicts flipped when it took the last.
  A tool now re-scores finished runs from their logs.
- **A wrong diagnosis, corrected.** Long thinking-mode answers went missing. An early reading blamed the
  runtime for slowing to 2–3 tokens/s; the per-slot log showed normal speed, and the sample times had
  included queueing and retries. A reproduction tool then sent the same long requests straight to the
  runtime, and all of them returned. The cause was the evaluation library's own 600-second HTTP timeout,
  below the timeouts the harness set. Four spoiled results were re-run.
- **A test that was not a test.** Speculative decoding (MTP) first showed no speed-up, but the model
  file lacked the extra prediction head the technique needs. With a build that bundles it, writing speed
  rose 24%.
- **A setting that did not apply.** One candidate model ignored "thinking off" and wrote ~2,800 reasoning
  tokens per answer, which made its fast-mode scores look better than they were. The plan now says to
  confirm thinking can be switched off before trusting any new candidate's fast-mode scores.
- **An idea that sounded free.** Writing terse code to save tokens cut pass rates sharply (83% to 56% on
  one model). Reading code with comments stripped looked free with the first review prompt; after the
  review prompt improved, the same test showed more false alarms, so the earlier finding was reversed and
  recorded as such.
- **Silent input errors.** A live run of the delegation server ignored a misspelt argument and produced
  a worse summary without complaint. Unknown arguments are now an error.
- **A checker too strict to be useful.** The first live `extract` run kept 8 of 30 numbered steps in a
  document. The code check, built to reject invented values, also rejected every value taken from the
  heading an item sits under, and a chunk starting mid-section could not see its heading at all. After
  four fixes, three runs kept 30, 25 and 29 of 30, and never kept a wrong row.
- **Cleanup that depended on luck.** An overnight session left a model loaded on the GPU; the PC later
  hung when its displays woke, cause unproven. The agent had planned to unload the model at the end of
  its work, which only happens if the session survives. Every model is now loaded with an idle
  time-to-live, so the runtime frees the GPU itself after 15 idle minutes.
- **A safety check aimed at the wrong runtime.** The benchmark refuses a model that spills from VRAM
  into system RAM, which is a failed fit for an ordinary runtime. It also refused Strata, whose design is
  to keep most of a large model in system RAM. Each runtime now declares whether it offloads by design.

## The project uses itself

The first live trial used the workflow the project is building toward. The cloud agent wrote a spec and
tests for a small filter, a local model (Gemma 4 26B) wrote the code, a second local model (Gemma 4 31B)
reviewed it, and the cloud agent coordinated by hand and signed off. It took five rounds. The reviewer found
one real bug, which became a test, and raised one false alarm, disproved by running its own example. The
lessons became the coordinator's spec: feedback should quote the failing assertion and the responsible
line, the whole suite runs every round because a fix can undo an earlier one, and a reviewer's claim
counts only when a failing test proves it. For a module this small, hand-coordinating cost more cloud
tokens than writing it directly; the saving is expected to come from automating the coordinator, and
will be measured, not assumed.
