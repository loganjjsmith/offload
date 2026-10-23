# server — the delegation server

An MCP server that hands work to a local model on this PC, so bulky reading never enters the cloud
agent's context. Registered for the Offload project only (`.mcp.json` at the project root); Claude Code
asks once to approve it. Any MCP client can use it, and it talks to any OpenAI-compatible endpoint.

## Tools

| Tool | What it does |
|---|---|
| `summarize_files` | Reads files, folders or glob patterns itself and returns a terse summary with `file:line` references. Large inputs are split into chunks and the chunk summaries merged. Code then checks the references and appends the Markdown sections, classes and methods (C#, Java, TypeScript, JavaScript, Python) none of them falls in, so the caller knows what the summary left out. |
| `extract` | Lists every item of one kind (issues, TODOs, test cases...) as tab-separated rows with `file:line`. The model only copies values, in small chunks with thinking off; code checks every value word for word against the file and reports each dropped row and any answer cut at the token limit. The caller does the counting and comparing. This is the row method that scored 92–100% on the bench's extraction task, against under 45% for free-form answers. |
| `ask_local` | Sends a self-contained prompt to the local model. |
| `grade_handoff` | The caller grades one answer, by its call id, in one word once it has used it: `used`, `fixed` (small corrections), `redone` (thrown away and done again) or `misleading` (wrong in a way that cost extra work), with an optional note. Feeds the tripwire below. |
| `offload_stats` | Totals from the call log (calls, characters read locally, characters returned, model time), the grades per flow, how many calls are not graded yet, and each switched-off flow with its bad examples. |

Each tool takes a `mode`: `fast` (thinking off, seconds) or `careful` (thinking on, minutes). The model
for each mode, the endpoint, the folders it may read and the timeouts are in `config.json`, not in the
code. This machine's own folders go in `config.local.json` (not committed), whose keys override
`config.json`, for example `{ "readRoots": ["C:/Projects/Offload", "D:/Games/MyGame"] }`. Relative
read roots are taken from this folder; the committed default, `..`, is the Offload project itself. The request timeout is 30 minutes on purpose: careful answers can take more than ten.

## Tripwire

A local answer so poor that the cloud agent would have been better off with nothing wastes work twice, so
bad flows are switched off (PLAN, Phase 3). A **flow** is a tool, a mode and the model behind it, for
example `summarize_files fast gemma-4-26b-a4b`.

- Every answer from `summarize_files`, `extract` and `ask_local` ends with a line such as
  `[call 3f9a1c: grade it with grade_handoff once used]`. The id is stored with the call in the call log,
  along with whether the call was about code: it read a code file (by extension), or its prompt or answer
  held a fenced code block.
- `grade_handoff` appends the grade to `logs/grades.jsonl`. Grading a call again replaces its earlier grade.
- A flow is switched off when its `redone` and `misleading` grades reach `tripwire.maxBadShare` of its last
  `tripwire.window` graded calls (both in `config.json`; 30% of 10 to start with, a guess to be tuned on
  real grades). Calls not yet graded count as good, so a new flow can trip before it has a full window.
  A single `misleading` grade on a call about code switches its flow off at once.
- Switched-off flows are kept in `logs/flows.json` with the reason and the bad examples, and the server
  writes the alarm to its standard error. Calls to a switched-off flow are refused (and logged as failed)
  with a message telling the caller to do the job directly; other flows keep working.

**Switching a flow back on is manual for now:** after a fix (another model, a changed prompt, a tighter
filter) has passed a re-run of the bench task for that job, set `"off": false` on the flow's entry in
`logs/flows.json`. Keep the entry rather than deleting it: its `since` time makes only calls made after the
switch-off count, so the old grades cannot trip the flow again straight away. Changing a role's model in
config starts a new flow with no grades, so that path skips the bench re-run; do it deliberately.

`filters/` holds deterministic output filters (no model): `unity-tests.ts` turns a Unity test run into
counts plus the failures with `file:line`. Not wired into a tool yet.

## Loop coordinator

`node src/coordinate.ts <task folder>` runs one change through local write, test, review and fix rounds until
it is cloud-ready or a guard stops it, then writes `result.md` and `result.json` into the folder. The task folder
format, the loop and the guards are in `docs/COORDINATOR.md`. Roles `writer` and `reviewer` in `config.json`
name the models; tests run in the bench's sandbox image (`sandboxImage`, Docker must be running). Each run is
logged as a `coordinator` call, so `grade_handoff` grades it like any other handoff.

## Running

From this folder: `npm install` once, `npm test` for the tests (no GPU needed; a fake local model stands
in), `npm start` to run the server by hand. Every call is logged to `logs/calls.jsonl`, grades to
`logs/grades.jsonl` and switched-off flows to `logs/flows.json` (none of them committed).

## Layout

| File | Purpose |
|---|---|
| `src/index.ts` | Registers the tools and serves them over stdio |
| `src/tools.ts` | The tools: prompts, chunking, logging and the call id around each call |
| `src/local.ts` | One request to the OpenAI-compatible endpoint |
| `src/lmstudio.ts` | The only runtime-specific code: loads the role's model in LM Studio, one at a time |
| `src/files.ts` | Reading allowed paths, line numbering, chunking |
| `src/coverage.ts` | The coverage check: cited lines, Markdown sections and code declarations, the note appended to a summary |
| `src/extract.ts` | The row method: the prompt, reading rows from an answer, checking them against the files, the table |
| `src/log.ts` | The call log and its totals |
| `src/tripwire.ts` | Grades, the switch-off rule, refusals for switched-off flows, the grades report |
| `src/coordinate.ts` | Command line for the loop coordinator |
| `src/coordinator/task.ts` | The task folder, the work folder, reading files from a writer's answer |
| `src/coordinator/run.ts` | Running tests in the sandbox, counting results, quoting the code lines a failure points at |
| `src/coordinator/prompts.ts` | Writer and reviewer prompts, reading a review's verdict and proof test |
| `src/coordinator/loop.ts` | The rounds, the guards, checking bug claims, the result report |
| `src/config.ts` | Loads `config.json` (or the file named by `OFFLOAD_CONFIG`) and `config.local.json` beside it |
