# Loop coordinator — specification

The loop coordinator is Phase 5's first real piece (see `PLAN.md`, "Loop coordinator"). It is a plain program,
not a model. It takes a change the cloud agent has specified, has local models write, test, review and fix it on
this PC, and hands back only finished work. The cloud agent writes the specification and the tests, and reads
the result. It never sees the rounds in between.

This document is the specification to build from. It rests on two hand-run trials (`PLAN.md`, "Trial 1 result"
and "Trial 2 result") and on benchmark numbers measured on this machine. Where a decision still waits on a
measurement, it says so.

## What success looks like

The measure is the one Phase 5 set: **cloud tokens per working, tested change**, compared with the cloud agent
doing the change alone. For the cloud agent, a coordinated change costs the specification, the tests, reading
the final diff and the review summary, and fixing what is left. Trial 2 showed the specification and tests are
most of that cost, and are worth it: a precise specification with exact expected outputs got a 163-line module
right on the first round. So the coordinator pays off on changes where writing the code is a large part of the
work: whole modules and multi-file changes, not ten-line fixes.

Secondary measures, logged for every run: the share of tasks that reach "cloud-ready", the share of those the
cloud agent accepts without changes (the tripwire grade), rounds, local time, and model loads.

## Input: a task folder

The cloud agent writes one folder per change:

| File | What it holds |
|---|---|
| `task.json` | language, the files the writer may create or change, the test command, limits (rounds, minutes) |
| `spec.md` | the specification, written for a model: exact names, signatures, edge cases, examples |
| `tests/` | the tests the change must pass. The writer sees them but may not change them. Each check must print the actual value when it fails (`assertEqual`, `assert.equal`), not a bare `assert`: the writer can only fix what it can see |
| `context/` (optional) | read-only files the writer needs, such as an interface it must implement |

The work happens in a git worktree or a scratch folder, never on a protected branch. The test command runs in
the existing coding sandbox (Docker, no network) for Python, TypeScript and C#. A Unity project would instead
use the Unity test filter from Phase 3, which is a later step.

## Roles and models

Roles are named in `server/config.json`, like the server's `fast` and `careful` roles, so the models can change
without code changes. The starting choice, from measurements on this PC:

| Role | Model | Why |
|---|---|---|
| Writer | Gemma 4 31B, thinking off | 96% of hidden tests on the module-sized tasks (Gemma 26B 74%); wrote trial 2's module in one round |
| Reviewer | Qwen3.8 27B, thinking off | other vendor than the writer; proves 45% of known bugs with a test, writes a wrong test for 1% of clean code, rarely runs out of tokens, fastest review run (35 min for 232) |
| Second reviewer (later) | Gemma 4 31B, thinking off | proves 62% and finds bugs the hidden tests miss; with Qwen3.8, 74% of known bugs proved and 4% wrong tests; already loaded as the writer, so no model swap |

Gemma 4 26B was the first choice, since it flags almost every bug, but asked for proof it ran out of tokens on 28%
of reviews (62 of 64 on clean code), and a review cut short is no review.

The writer and a reviewer do not fit on the card together, so the coordinator batches. The writer works until
the tests pass, and only then is the reviewer loaded, once. With memory-mapped loading switched off, a model
loads in 12–16 s.

## The loop

1. **Write.** The writer gets the specification, the tests, the context files, and the current files. It answers
   with the complete content of every file it changes, one fenced block per file, each labelled with its path.
   Files outside the allowed list are rejected.
2. **Test.** The coordinator runs the whole test command, every round, and records how many tests pass. A build
   or load error counts as zero.
3. **Fix.** While tests fail, the writer gets the failures back. Per trial 1, the feedback quotes the failing
   assertion *and* the line of the writer's code responsible, and it says which earlier fixes must be kept.
   Back to step 1.
4. **Review.** Once every test passes, the reviewer gets the specification and the code (with its comments; a
   reviewer reading stripped code raised more false alarms) and answers pass, or fail with a test that shows the
   bug. This is prompt version 2 plus the proof request, as in the bench task `review_proof`.
5. **Check each claim.** The coordinator runs the reviewer's test against the code:
   - it passes: the claim is dropped as a false alarm;
   - it does not build or load: the claim is dropped as a broken test;
   - it fails: the claim stands. The test joins a separate set of *reviewer tests* and goes back to the writer
     with the failure, and the loop returns to step 1.
6. **Cloud-ready** when all tests pass, the cloud's and the accepted reviewer tests, and the last review was
   clean. Whether one clean review is enough, or a second reviewer is needed, is the pending decision below.

A claim the coordinator accepts on clean code is the dangerous case: the writer would then "fix" working code.
The bench measures how often a reviewer's test fails on correct code (the "got through" column of
`review_proof_table.py`). Every accepted reviewer test is listed in the final report, so the cloud agent checks
each one. It is a few lines to read, far less than the rounds it replaced.

## Guards

- **Locked tests.** The cloud's tests are hashed before the first round; if a hash changes, the run stops.
- **Round limit:** four writer rounds by default, counting fixes after review.
- **No progress:** two rounds in a row without more tests passing stop the loop. A round that passes fewer
  tests than the round before is a regression, reported as such (trial 1's round 4 undid round 3's fix).
- **Stuck:** a round whose files are identical to an earlier round's stops the loop.
- **Time limit** per task, from `task.json`.
- **Memory (later):** before a load, check the card's free memory and the PC's free RAM, and do not load a
  model that would spill into system RAM. The first version relies on LM Studio's one-model-at-a-time load.

When a guard stops the loop, the task goes to the cloud agent as a real question: the specification, the last
files, the failing tests, and a short history of what each round tried. It never gets the full transcripts.

## Output

A `result.json` and a short `result.md` in the task folder:

- status: cloud-ready, or stopped and why;
- the final files, and the diff against the start;
- test results: the cloud's tests, then the reviewer tests with the claim each one came from;
- the review summary: claims made, dropped (with the reason) and accepted;
- rounds, local time, model loads, and local prompt and answer tokens.

Every run is logged like a server call, so the tripwire can grade it. The flow is (coordinator, writer model,
reviewer model). A pair whose cloud-ready work keeps coming back `redone` is switched off.

## Where it lives

In `server/`, in TypeScript, reusing the server's configuration, its LM Studio loader and its chat client.
The first version is a command-line program (`node server/src/coordinator.ts <task folder>`), so any agent
harness that can run a command can use it, which keeps it provider-neutral. An MCP tool that starts a run and
reports on it can follow. A run takes minutes to an hour, longer than an MCP call should wait.

## Decided by measurement: one reviewer, a second later

The bench task `review_proof` (2026-10-22 night, 232 solutions, `bench/tools/review_proof_table.py`) asks each
reviewer to prove a failed verdict with a test and runs it against the code and the reference:

| Reviewer | Known bugs proved | Wrong tests on clean code | Answers cut | Minutes |
|---|---|---|---|---|
| Gemma 4 31B | 62% | 3% | 2 | 65 |
| Gemma 4 26B | 60% | 4% | 68 | 100 |
| Qwen3.8 27B | 45% | 1% | 1 | 35 |
| Qwen3.6 35B-A3B | 42% | 4% | 9 | 51 |

Two reviewers prove more: Gemma 31B with Qwen3.8 reach 74%, with 4% wrong tests. Asking for proof made every
reviewer more careful about failing code than with review prompt version 2, so the filter's real cost is the
known bugs no one can show, not false alarms. A "clean" solution (passed the hidden tests) whose test fails on
the code but passes on the reference was, on a spot check, mostly a real bug the hidden tests miss (an LRU cache
of capacity 0, a wrap piece not joined to the next word, wrong grid paths), so accepting such a claim is right.
C# proofs barely work: reviewers paste the class into the test file, which does not build (Gemma 26B proved 1 of
10 C# bugs), one more reason C# waits.

The first version uses one reviewer, Qwen3.8; the cloud's tests remain the main gate. A second review by Gemma
31B is the next step once the first real runs show how often a change comes back.

## First real runs (2026-10-23)

Four of the bench's module-sized Python tasks, through `bench/tools/coordinator_tasks.py`; the hidden tests
served as the cloud's tests and the writer saw them. Writer Gemma 31B; reviewer Gemma 26B for `config` (the run
had started before the reviewer measurement finished), Qwen3.8 for the rest.

| Task | Result | Tests passed, by round | Review | Minutes | Local tokens in / out |
|---|---|---|---|---|---|
| config | cloud-ready | 34/37, 37/37 | cut at the token limit (Gemma 26B) | 3.2 | 14.6k / 9.8k |
| report | stopped: no progress | 28/29, 28/29, 28/29 | – | 2.3 | 16.7k / 4.0k |
| chunker | cloud-ready | 30/30 | pass | 1.6 | 7.5k / 2.6k |
| cliargs (a change) | cloud-ready | 36/36, 31/37, 37/37 | claim proved and fixed, then pass | 4.5 | 22.5k / 8.0k |

- `cliargs`: the first version passed every cloud test, and Qwen3.8 proved a bug they miss (options on a parser
  that also has commands); its test passes on the reference. The fix broke six tests, the next round restored them.
- `report`: the writer put one bracket in the wrong place (`(n=20), 2 unanswered` for `(n=20, 2 unanswered)`)
  and never saw it, because the test is a bare `assert` that prints no values. The guard stopped it after three
  rounds; the report names the failing test, so the cloud agent's fix is one character. Hence the rule above.
- Each `result.md` is 5–11 KB (roughly 1.5–3k tokens) for the cloud agent to read. The cloud's side of a real
  task, the specification and the tests, was not measured here because these tasks came with both.
- On the bench, Gemma 31B wrote these modules without seeing tests: `config` passed 84–97% of the tests,
  `report` 93–97%, `chunker` 83–100%, `cliargs` 97–100%.

## First version: scope

In: Python and TypeScript tasks in the coding sandbox, one writer, one reviewer, the guards above, the result
report, and a log entry per run. Built 2026-10-22 (`server/src/coordinate.ts`, `server/src/coordinator/`) and
tested against the fake endpoint like the rest of the server (13 tests). The first real tasks are four of the
bench's module-sized tasks, turned into task folders by `bench/tools/coordinator_tasks.py`. Trial 2's module
does not suit: it imports Inspect, which the sandbox does not have.

Later: the memory check, C# (it builds slowly in the sandbox, and the C# work here is in Unity), Unity tests through
the Phase 3 filter, a second reviewer, the MCP tool, and running tasks from a queue overnight.
