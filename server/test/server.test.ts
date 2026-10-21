import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import { mkdtemp, writeFile, readFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import type { Config } from "../src/config.ts";
import { loadConfig } from "../src/config.ts";
import { citedLines, coverageNote, sections } from "../src/coverage.ts";
import { checkRows, parseRows } from "../src/extract.ts";
import { chunk, headingsAbove, insideRoots, readSources } from "../src/files.ts";
import { summarizeFiles, askLocal, extractRows } from "../src/tools.ts";
import { gradeHandoff, gradeReport } from "../src/tripwire.ts";

// A fake OpenAI-compatible endpoint that records each request and replies with a canned answer, or with
// what `respond` returns when a test sets it.
let fake: Server;
let respond: ((prompt: string) => { content: string; finish_reason?: string }) | undefined;
let port = 0;
const requests: Record<string, unknown>[] = [];
let dir = "";
let cfg: Config;

before(async () => {
  fake = createServer((req, res) => {
    let body = "";
    req.on("data", c => (body += c));
    req.on("end", () => {
      const parsed = JSON.parse(body);
      requests.push(parsed);
      const prompt: string = parsed.messages[0].content;
      const answer = respond?.(prompt) ?? { content: prompt.startsWith("These are summaries") ? "- merged" : `<think>hidden</think>- part ${requests.length}` };
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ choices: [{ message: { content: answer.content }, finish_reason: answer.finish_reason ?? "stop" }],
        usage: { prompt_tokens: 100, completion_tokens: 10 } }));
    });
  });
  await new Promise<void>(ok => fake.listen(0, "127.0.0.1", () => ok()));
  port = (fake.address() as { port: number }).port;
  dir = await mkdtemp(join(tmpdir(), "offload-test-"));
  await mkdir(join(dir, "sub"));
  await writeFile(join(dir, "a.cs"), "class A {}\r\nint x = 1;\n");
  await writeFile(join(dir, "sub", "b.md"), "# Spec\nThe slingshot launches.\n");
  cfg = {
    endpoint: `http://127.0.0.1:${port}/v1`, runtime: "none", lmsCli: "lms",
    roles: { fast: { model: "fast-model", thinking: false, contextLength: 8192 },
             careful: { model: "careful-model", thinking: true, contextLength: 8192 } },
    requestTimeoutSeconds: 10, maxAnswerTokens: 512, chunkChars: 60000, extractChunkChars: 12000, readRoots: [dir],
    logFile: join(dir, "logs", "calls.jsonl"), tripwire: { window: 4, maxBadShare: 0.5 },
  };
});

after(() => fake.close());

const FOOTER = /\n\n\[call ([0-9a-f]{6}): grade it with grade_handoff once used\]$/;
/** An answer without the call id line that ends it, and the id on that line. */
const body = (out: string) => out.replace(FOOTER, "");
const callId = (out: string) => FOOTER.exec(out)![1];
const readLines = async (file: string) => (await readFile(file, "utf8")).trim().split("\n").map(l => JSON.parse(l));
/** A config with its own log folder, so each tripwire test starts with no grades and no switched-off flows. */
const own = (name: string, tripwire = cfg.tripwire): Config => ({ ...cfg, logFile: join(dir, name, "calls.jsonl"), tripwire });

test("paths inside the roots are allowed, case-insensitively; others are not", () => {
  assert.ok(insideRoots("C:/Work/Proj/file.cs", ["c:/work/proj"]));
  assert.ok(insideRoots("C:\\Work\\Proj\\sub\\x.md", ["C:/Work/Proj"]));
  assert.ok(!insideRoots("C:/Work/Project2/x", ["C:/Work/Proj"]));
  assert.ok(!insideRoots("C:/Work/Proj/../Other/x", ["C:/Work/Proj"]));
});

test("reading outside the roots is refused, and directories expand to their files", async () => {
  await assert.rejects(readSources([resolve(dir, "..")], [join(dir, "sub")]), /Refused/);
  const files = await readSources([dir], [dir]);
  assert.deepEqual(files.map(f => f.path.replace(/\\/g, "/").split("/").slice(-2).join("/")).sort(),
    [`${dir.replace(/\\/g, "/").split("/").pop()}/a.cs`, "sub/b.md"].sort());
});

test("chunks respect the limit and split a large file by lines", () => {
  const big = { path: "big.txt", text: Array.from({ length: 200 }, (_, i) => `line ${i}`).join("\n") };
  const parts = chunk([big], 500);
  assert.ok(parts.length > 1);
  assert.ok(parts.every(p => p.length <= 500));
  assert.ok(parts[1].startsWith("=== big.txt === (continued)"));
});

test("fast mode sends numbered files with thinking off and returns the summary without hidden reasoning", async () => {
  requests.length = 0;
  const out = await summarizeFiles(cfg, { paths: [join(dir, "a.cs")], focus: "variables" });
  assert.equal(body(out), "- part 1");
  const req = requests[0] as { model: string; reasoning_effort?: string; messages: { content: string }[] };
  assert.equal(req.model, "fast-model");
  assert.equal(req.reasoning_effort, "none");
  assert.match(req.messages[0].content, /Focus on: variables/);
  assert.match(req.messages[0].content, /\s+2\| int x = 1;/);
});

test("careful mode leaves thinking on; more than one chunk is merged by a final call", async () => {
  requests.length = 0;
  const out = await summarizeFiles({ ...cfg, chunkChars: 60 }, { paths: [dir], mode: "careful" });
  assert.equal(body(out), "- merged");
  assert.ok(requests.length >= 3);
  assert.equal((requests[0] as { reasoning_effort?: string }).reasoning_effort, undefined);
});

test("every call is logged, failures included", async () => {
  await askLocal(cfg, { prompt: "hello" });
  await assert.rejects(summarizeFiles(cfg, { paths: ["C:/definitely/outside"] }));
  const log = (await readFile(cfg.logFile, "utf8")).trim().split("\n").map(l => JSON.parse(l));
  const ask = log.find(r => r.tool === "ask_local");
  assert.equal(ask.inputChars, 5);
  assert.ok(log.some(r => r.error));
});

test("the coverage note names uncited sections and lines that do not exist", () => {
  const doc = { path: "C:/x/Audit.md", text: "# Audit\nintro\n\n## One\na\nb\n## Two\nc\nd\n## Three\ne\nf\n" };
  assert.deepEqual(sections(doc).map(s => [s.heading, s.start, s.end]), [["One", 4, 6], ["Two", 7, 9], ["Three", 10, 13]]);
  assert.deepEqual(citedLines("- a (audit.md:5, 8–9) - b (Other.md:3)", [doc]).get(doc.path), [5, 8, 9]);
  const note = coverageNote("- a (Audit.md:5) - b (Audit.md:40)", [doc]);
  assert.match(note, /cited lines that do not exist: 40/);
  assert.match(note, /Audit\.md:7–9 "Two"/);
  assert.match(note, /Audit\.md:10–13 "Three"/);
  assert.doesNotMatch(note, /"One"/);
  assert.equal(coverageNote("- (Audit.md:5, 8, 11)", [doc]), "");
  assert.equal(coverageNote("- a (5) - b (lines 8-9) - c (11, 12)", [doc]), "");
  assert.match(coverageNote("- a (5)", [doc, { path: "C:/x/B.md", text: "" }]), /Audit\.md:4–6 "One"/);
});

test("code files are divided into classes and methods; calls, statements and one-line members are not", () => {
  const cs = { path: "C:/x/Pole.cs", text: [
    "using UnityEngine;",                                 // 1
    "[RequireComponent(typeof(Rigidbody))]",               // 2
    "public sealed class Pole : MonoBehaviour",            // 3
    "{",                                                   // 4
    "    [SerializeField] float height = 2f;",             // 5
    "    float grip;",                                     // 6
    "    public Pole(float h)",                            // 7
    "    {",                                               // 8
    "        height = h;",                                 // 9
    "    }",                                               // 10
    "    void Update()",                                   // 11
    "    {",                                               // 12
    "        if (grip > 0f)",                              // 13
    "            Debug.Log(",                              // 14
    "                grip);",                              // 15
    "        foreach (var c in GetComponents<Collider>())",// 16
    "            c.enabled = true;",                       // 17
    "        var v = new Vector3(",                        // 18
    "            1, 2, 3);",                               // 19
    "    }",                                               // 20
    "    private static List<int> Heights<T>(T[] all)",    // 21
    "    {",                                               // 22
    "        return Sort(all,",                            // 23
    "            height);",                                // 24
    "    }",                                               // 25
    "    public float Grip() => grip;",                    // 26
    "}",                                                   // 27
  ].join("\n") };
  assert.deepEqual(sections(cs).map(s => [s.heading, s.start, s.end]),
    [["Pole", 3, 6], ["Pole", 7, 10], ["Update", 11, 20], ["Heights", 21, 27]]);
  const ts = { path: "a.ts", text: "export async function load(p: string) {\n  run(p,\n    1);\n  return 2;\n}\n" +
    "const twice = (n: number) => {\n  return n * 2;\n};\nclass Box {\n  open(): void {\n    describe(\"x\", () => {\n      it();\n    });\n  }\n}\n" };
  assert.deepEqual(sections(ts).map(s => s.heading), ["load", "twice", "open"]);
  const py = { path: "b.py", text: "class A:\n    x = 1\n\n    def f(self):\n        g(1,\n          2)\n        return 3\n" };
  assert.deepEqual(sections(py).map(s => [s.heading, s.start, s.end]), [["f", 4, 8]]);
  assert.match(coverageNote("- update loop (Pole.cs:13)", [cs]), /Pole\.cs:21–27 "Heights"/);
  assert.doesNotMatch(coverageNote("- update loop (Pole.cs:13)", [cs]), /"Update"/);
});

test("rows are parsed from an answer with stray text, and checked word for word against the file", () => {
  const file = { path: "C:/x/Issues.md", text: "# Issues\n\n[NV-1] Audio crashes\n  status: open | owner: Avery\n\n[NV-2] UI freezes\n  status: fixed | owner: Blake\n" };
  assert.equal(parseRows("no rows here", ["id"]), undefined);
  const rows = parseRows('Here you go:\n```json\n[{"file":"Issues.md","line":3,"id":"NV-1","status":"open","owner":"Avery"},' +
    '{"file":"issues.md","line":6,"id":"NV-2","status":"open","owner":"Blake"},' +
    '{"file":"Other.md","line":1,"id":"NV-3","status":"open","owner":null},' +
    '{"file":"Issues.md","line":99,"id":"NV-4","status":"open","owner":null},' +
    '{"file":"Issues.md","line":3,"id":"NV-1","status":"OPEN","owner":"avery"}]\n```', ["id", "status", "owner"])!;
  assert.equal(rows.length, 5);
  const { kept, dropped } = checkRows(rows, [file]);
  assert.deepEqual(kept.map(r => [r.file, r.line, r.values.id]), [["Issues.md", 3, "NV-1"]]);
  assert.equal(dropped.length, 3);
  assert.match(dropped[0], /issues\.md:6: "status" value "open" is not on lines 6–14 or a heading above them/);
  assert.match(dropped[1], /Other\.md:1: not a file that was read/);
  assert.match(dropped[2], /Issues\.md:99: the line does not exist/);
});

test("a value may be a whole heading the row sits under, but not a sibling's or one inside fenced code", () => {
  const text = "# Tasks\n\n## Task A\n\n1. **Fix it**\n\n## Task B\n\n```\n## Not a heading\n```\n\n1. **Write it**\n";
  const file = { path: "C:/x/Tasks.md", text };
  assert.deepEqual(headingsAbove(text.split("\n"), 13), ["Task B", "Tasks"]);
  const rows = [
    { file: "Tasks.md", line: 5, values: { section: "Task A", title: "**Fix it**" } },
    { file: "Tasks.md", line: 13, values: { section: "## Task B", title: "Write it" } },
    { file: "Tasks.md", line: 13, values: { section: "Task A", title: "Write it" } },
    { file: "Tasks.md", line: 13, values: { section: "Not a heading", title: "Write it" } },
    { file: "Tasks.md", line: 13, values: { section: "Task", title: "Write it" } },
  ];
  const { kept, dropped } = checkRows(rows, [file]);
  assert.deepEqual(kept.map(r => [r.line, r.values.section]), [[5, "Task A"], [13, "## Task B"]]);
  assert.equal(dropped.length, 3);
});

test("bold and code marks are ignored when values are checked, and a continued chunk names its headings", () => {
  const text = "# Guide\n\n## Setup\n\n" + Array.from({ length: 40 }, (_, i) => `${i + 1}. **Step \`${i}\`** does a thing`).join("\n");
  const file = { path: "C:/x/Guide.md", text };
  const { kept } = checkRows([{ file: "Guide.md", line: 5, values: { title: "Step 0" } }], [file]);
  assert.equal(kept.length, 1);
  const parts = chunk([file], 600);
  assert.ok(parts.length > 1);
  assert.match(parts[1].split("\n")[0], /\(continued, under the headings: Guide > Setup\)$/);
});

test("extract retries once when a reply holds no readable JSON", async () => {
  const file = join(dir, "retry.md");
  await writeFile(file, "[NV-1] Thing\n");
  let calls = 0;
  respond = () => ++calls === 1 ? { content: '[{"file": "retry.md", "line": 1, "id": NV-1}]' } : { content: '[{"file":"retry.md","line":1,"id":"NV-1"}]' };
  try {
    const out = await extractRows(cfg, { paths: [file], item: "issue", fields: { id: "issue id" } });
    assert.equal(calls, 2);
    assert.match(out, /retry\.md:1\tNV-1/);
  } finally {
    respond = undefined;
  }
});

test("extract sends small chunks with thinking off and returns checked rows with notes", async () => {
  const file = join(dir, "issues.md");
  await writeFile(file, Array.from({ length: 30 }, (_, i) => `[NV-${i}] Thing ${i}\n  status: open`).join("\n"));
  requests.length = 0;
  respond = prompt => {
    const ids = [...prompt.matchAll(/^\s*(\d+)\| \[NV-(\d+)\]/gm)];
    const rows = ids.map(([, line, id]) => ({ file: "issues.md", line: Number(line), id: `NV-${id}`, status: id === "3" ? "closed" : "open" }));
    return prompt.includes("(continued)") ? { content: JSON.stringify(rows).slice(0, -20), finish_reason: "length" } : { content: JSON.stringify(rows) };
  };
  try {
    const out = await extractRows({ ...cfg, extractChunkChars: 700 }, { paths: [file], item: "issue", fields: { id: "issue id", status: "its status" } });
    assert.ok(requests.length >= 2);
    assert.equal((requests[0] as { reasoning_effort?: string }).reasoning_effort, "none");
    assert.match((requests[0] as { messages: { content: string }[] }).messages[0].content, /List every issue[\s\S]*"id": issue id/);
    const lines = out.split("\n");
    assert.match(lines[0], /^\d+ rows .*; 1 dropped\.$/);
    assert.equal(lines[1], "where\tid\tstatus");
    assert.equal(lines[2], "issues.md:1\tNV-0\topen");
    assert.match(out, /issues\.md:7: "status" value "closed"/);
    assert.match(out, /Note: part 2 of \d+ .*stopped at the token limit before its JSON array closed/);
  } finally {
    respond = undefined;
  }
});

test("each answer ends with its call id, logged with its flow and whether it was about code", async () => {
  const c = own("ids");
  const prose = await askLocal(c, { prompt: "hello" });
  const fenced = await askLocal(c, { prompt: "Fix this:\n```js\nlet x\n```" });
  const cs = await summarizeFiles(c, { paths: [join(dir, "a.cs")] });
  const md = await extractRows(c, { paths: [join(dir, "sub", "b.md")], item: "spec line", fields: { text: "the line" } });
  const log = await readLines(c.logFile);
  assert.deepEqual(log.map(r => [r.id, r.tool, r.code]),
    [[callId(prose), "ask_local", false], [callId(fenced), "ask_local", true], [callId(cs), "summarize_files", true], [callId(md), "extract", false]]);
  assert.equal(new Set(log.map(r => r.id)).size, 4);
  assert.equal(log[0].outputChars, body(prose).length);

  await assert.rejects(gradeHandoff(c, { callId: "000000", grade: "used" }), /No call with id 000000/);
  assert.match(await gradeHandoff(c, { callId: callId(prose), grade: "fixed", note: "one typo" }),
    /^Graded [0-9a-f]{6} fixed\. The flow "ask_local fast fast-model" has 0 redone or misleading in its last 1 graded calls; it switches off at 2 of 4\.$/);
  const [grade] = await readLines(join(dir, "ids", "grades.jsonl"));
  assert.deepEqual([grade.callId, grade.flow, grade.grade, grade.note, grade.code], [callId(prose), "ask_local fast fast-model", "fixed", "one typo", false]);
});

test("a flow whose redone and misleading share reaches the limit is switched off until a person switches it on", async () => {
  const c = own("share");
  const ids: string[] = [];
  for (const q of ["q1", "q2", "q3"]) ids.push(callId(await askLocal(c, { prompt: q })));
  await gradeHandoff(c, { callId: ids[0], grade: "redone", note: "wrong API" });
  await gradeHandoff(c, { callId: ids[1], grade: "used" });
  // Grading a call again replaces its grade; the prompt held no code, so one misleading answer alone does not trip it.
  assert.match(await gradeHandoff(c, { callId: ids[1], grade: "misleading", note: "invented a file" }),
    /is now switched off because 2 of its last 2 graded calls were redone or misleading \(the limit is 50% of 4\)/);

  await assert.rejects(askLocal(c, { prompt: "again" }),
    /The flow "ask_local fast fast-model" was switched off at .* because 2 of .*\. Do this job directly instead of delegating it\./);
  const refused = (await readLines(c.logFile)).at(-1);
  assert.match(refused.error, /switched off/);
  await assert.rejects(gradeHandoff(c, { callId: refused.id, grade: "used" }), /failed, so it returned nothing to grade/);
  assert.match(await askLocal(c, { prompt: "q", mode: "careful" }), FOOTER, "another flow stays on");

  const report = await gradeReport(c);
  assert.match(report, /\(2 calls not graded yet\)/);
  assert.match(report, /ask_local fast fast-model: 0 \/ 0 \/ 1 \/ 1 SWITCHED OFF at \S+: 2 of/);
  assert.match(report, /- call \w+ redone: wrong API\n {4}- call \w+ misleading: invented a file/);

  const stateFile = join(dir, "share", "flows.json");
  const state = JSON.parse(await readFile(stateFile, "utf8"));
  state["ask_local fast fast-model"].off = false;
  await writeFile(stateFile, JSON.stringify(state));
  await new Promise(ok => setTimeout(ok, 5));
  const after = await askLocal(c, { prompt: "after the fix" });
  assert.match(await gradeHandoff(c, { callId: callId(after), grade: "redone" }), /has 1 redone or misleading in its last 1 graded calls/);
  assert.match(await gradeHandoff(c, { callId: ids[2], grade: "redone" }), /predates the flow's last switch-off/);
});

test("one misleading answer about code switches its flow off at once; about prose it does not", async () => {
  const c = own("code", { window: 10, maxBadShare: 0.3 });
  const prose = await summarizeFiles(c, { paths: [join(dir, "sub", "b.md")] });
  assert.match(await gradeHandoff(c, { callId: callId(prose), grade: "misleading" }), /switches off at 3 of 10\.$/);
  const code = await summarizeFiles(c, { paths: [join(dir, "a.cs")] });
  assert.match(await gradeHandoff(c, { callId: callId(code), grade: "misleading", note: "named a method that does not exist" }),
    /"summarize_files fast fast-model" is now switched off because a misleading answer about code \(call [0-9a-f]{6}\)/);
  await assert.rejects(summarizeFiles(c, { paths: [join(dir, "sub", "b.md")] }), /Do this job directly/);
  assert.match(await gradeReport(c), /- call \w+ misleading: named a method that does not exist/);
});

test("config.local.json overrides the committed config, and relative read roots are taken from server/", async () => {
  const cdir = await mkdtemp(join(tmpdir(), "offload-cfg-"));
  await writeFile(join(cdir, "config.json"), "\uFEFF" + JSON.stringify({ ...cfg, readRoots: [".."], logFile: "logs/x.jsonl", extractChunkChars: undefined }));
  const shared = loadConfig(join(cdir, "config.json"));
  assert.deepEqual(shared.readRoots, [resolve(import.meta.dirname, "..", "..")]);
  assert.equal(shared.extractChunkChars, 12000);
  await writeFile(join(cdir, "config.local.json"), JSON.stringify({ readRoots: ["D:/Games/Project"] }));
  const local = loadConfig(join(cdir, "config.json"));
  assert.deepEqual(local.readRoots, [resolve("D:/Games/Project")]);
  assert.equal(local.endpoint, cfg.endpoint);
});

test("the MCP server lists its tools and answers a call over stdio", async () => {
  const configPath = join(dir, "test-config.json");
  await writeFile(configPath, JSON.stringify({ ...cfg, logFile: join(dir, "logs", "mcp.jsonl") }));
  const transport = new StdioClientTransport({
    command: process.execPath, args: [resolve(import.meta.dirname, "..", "src", "index.ts")],
    env: { ...process.env, OFFLOAD_CONFIG: configPath } as Record<string, string>,
  });
  const client = new Client({ name: "test", version: "0" });
  await client.connect(transport);
  try {
    const tools = (await client.listTools()).tools.map(t => t.name).sort();
    assert.deepEqual(tools, ["ask_local", "extract", "grade_handoff", "offload_stats", "summarize_files"]);
    const result = await client.callTool({ name: "summarize_files", arguments: { paths: [join(dir, "sub", "b.md")] } });
    const answer = (result.content as { text: string }[])[0].text;
    assert.match(body(answer), /^- part \d+$/);
    const graded = await client.callTool({ name: "grade_handoff", arguments: { callId: callId(answer), grade: "used" } });
    assert.match((graded.content as { text: string }[])[0].text, /^Graded [0-9a-f]{6} used\./);
    const badGrade = await client.callTool({ name: "grade_handoff", arguments: { callId: callId(answer), grade: "fine" } });
    assert.equal(badGrade.isError, true);
    const stats = await client.callTool({ name: "offload_stats", arguments: {} });
    assert.match((stats.content as { text: string }[])[0].text, /summarize_files fast fast-model: 1 \/ 0 \/ 0 \/ 0/);
    const refused = await client.callTool({ name: "summarize_files", arguments: { paths: ["C:/Windows/win.ini"] } });
    assert.equal(refused.isError, true);
    const misspelt = await client.callTool({ name: "summarize_files", arguments: { paths: [join(dir, "sub", "b.md")], question: "x" } });
    assert.equal(misspelt.isError, true);
  } finally {
    await client.close();
  }
});
