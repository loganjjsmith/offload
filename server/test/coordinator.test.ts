import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Config } from "../src/config.ts";
import { coordinate } from "../src/coordinator/loop.ts";
import { parseReview } from "../src/coordinator/prompts.ts";
import { codeLines, countTests } from "../src/coordinator/run.ts";
import { parseFiles } from "../src/coordinator/task.ts";

// A fake endpoint that answers writer prompts and reviewer prompts from two scripts, in order.
let fake: Server;
/** A scripted answer; one given as an object can say it was cut at the token limit. */
type Scripted = string | { content: string; finish_reason: string };
let writerReplies: Scripted[] = [];
let reviewerReplies: Scripted[] = [];
const prompts: { writer: string[]; reviewer: string[] } = { writer: [], reviewer: [] };
let root = "";
let cfg: Config;

before(async () => {
  fake = createServer((req, res) => {
    let body = "";
    req.on("data", c => (body += c));
    req.on("end", () => {
      const prompt: string = JSON.parse(body).messages[0].content;
      const isReview = prompt.startsWith("Review the following");
      (isReview ? prompts.reviewer : prompts.writer).push(prompt);
      const next = (isReview ? reviewerReplies : writerReplies).shift() ?? "nothing scripted";
      const { content, finish_reason } = typeof next === "string" ? { content: next, finish_reason: "stop" } : next;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ choices: [{ message: { content }, finish_reason }],
        usage: { prompt_tokens: 100, completion_tokens: 10 } }));
    });
  });
  await new Promise<void>(ok => fake.listen(0, "127.0.0.1", () => ok()));
  const port = (fake.address() as { port: number }).port;
  root = await mkdtemp(join(tmpdir(), "offload-coord-"));
  cfg = {
    endpoint: `http://127.0.0.1:${port}/v1`, runtime: "none", lmsCli: "lms",
    roles: { writer: { model: "writer-model", thinking: false, contextLength: 8192 },
             reviewer: { model: "reviewer-model", thinking: false, contextLength: 8192 } },
    requestTimeoutSeconds: 10, maxAnswerTokens: 512, chunkChars: 60000, extractChunkChars: 12000, readRoots: [root],
    logFile: join(root, "logs", "calls.jsonl"), tripwire: { window: 4, maxBadShare: 0.5 },
    coordinator: { writer: "writer", reviewer: "reviewer", testTimeoutSeconds: 60, maxReviews: 2 },
  };
});

after(() => fake.close());

const SPEC = "Write sum.mts exporting sum(xs: number[]): number, the total (0 for none), and mean(xs: number[]): number, " +
  "the average. mean of an empty list throws RangeError.";
const TESTS = `import { test } from "node:test";
import assert from "node:assert/strict";
import { sum, mean } from "../sum.mts";
test("sum adds", () => assert.equal(sum([1, 2, 3]), 6));
test("sum of nothing is 0", () => assert.equal(sum([]), 0));
test("mean averages", () => assert.equal(mean([2, 4]), 3));
`;
const GOOD = `export function sum(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0);
}
export function mean(xs: number[]): number {
  if (xs.length === 0) throw new RangeError("empty");
  return sum(xs) / xs.length;
}
`;
const NO_RANGE_ERROR = GOOD.replace('  if (xs.length === 0) throw new RangeError("empty");\n', "");
const BAD_MEAN = GOOD.replace("sum(xs) / xs.length", "sum(xs) / (xs.length + 1)");
const file = (code: string, path = "sum.mts") => `${path}\n\`\`\`typescript\n${code}\`\`\`\n`;
const PASS = '{"verdict": "pass", "issues": []}';
const claim = (testCode: string) => `{"verdict": "fail", "issues": [{"line": 4, "problem": "no RangeError", "failing_input": "[]"}]}\n` +
  `\`\`\`typescript\n${testCode}\`\`\`\n`;
const THROWS_TEST = `import { mean } from "./sum.mts";\nimport assert from "node:assert/strict";\nassert.throws(() => mean([]), RangeError);\n`;

let n = 0;
async function task(maxRounds = 4): Promise<string> {
  const dir = join(root, `task${++n}`);
  await mkdir(join(dir, "tests"), { recursive: true });
  await writeFile(join(dir, "task.json"), JSON.stringify({ language: "typescript", files: ["sum.mts"],
    test: ["node", "--test", "--test-reporter=tap", "tests/sum.test.mts"], maxRounds }));
  await writeFile(join(dir, "spec.md"), SPEC);
  await writeFile(join(dir, "tests", "sum.test.mts"), TESTS);
  return dir;
}

function script(writer: Scripted[], reviewer: Scripted[]) {
  writerReplies = [...writer];
  reviewerReplies = [...reviewer];
  prompts.writer = [];
  prompts.reviewer = [];
}

test("a change that passes its tests and a clean review is cloud-ready in one round", async () => {
  script([file(GOOD)], [PASS]);
  const dir = await task();
  const r = await coordinate(cfg, dir);
  assert.equal(r.status, "cloud-ready", r.reason);
  assert.equal(r.rounds.length, 1);
  assert.deepEqual([r.rounds[0].passed, r.rounds[0].total], [3, 3]);
  assert.equal(r.files[0].content, GOOD);
  assert.match(prompts.writer[0], /sum of nothing is 0/);
  const md = await readFile(join(dir, "result.md"), "utf8");
  assert.match(md, /^# Coordinator result: cloud-ready/);
  assert.match(md, /^--- a\/sum\.mts\n\+\+\+ b\/sum\.mts$/m);
  assert.match(md, /\+export function sum/);
  assert.match(md, new RegExp(`\\[call ${r.id}: grade it with grade_handoff once used\\]`));
  const logged = (await readFile(cfg.logFile, "utf8")).trim().split("\n").map(l => JSON.parse(l));
  assert.ok(logged.some(l => l.id === r.id && l.tool === "coordinator" && l.model === "writer-model + reviewer-model"));
});

test("failing tests go back to the writer with the failure and the line of code responsible", async () => {
  script([file(BAD_MEAN), file(GOOD)], [PASS]);
  const r = await coordinate(cfg, await task());
  assert.equal(r.status, "cloud-ready", r.reason);
  assert.deepEqual(r.rounds.map(x => x.passed), [2, 3]);
  assert.match(prompts.writer[1], /Your last version passed 2 of 3 tests/);
  assert.match(prompts.writer[1], /Failing: mean averages/);
  assert.match(prompts.writer[1], /The files as they are now/);
});

test("a reviewer claim whose test passes on the code is dropped", async () => {
  script([file(GOOD)], [claim(`import { sum } from "./sum.mts";\nimport assert from "node:assert/strict";\nassert.equal(sum([1]), 1);\n`)]);
  const r = await coordinate(cfg, await task());
  assert.equal(r.status, "cloud-ready", r.reason);
  assert.equal(r.reviews[0].claims[0].outcome, "not reproduced");
  assert.equal(r.reviewerTests.length, 0);
});

test("a reviewer claim whose test does not load is dropped as broken", async () => {
  script([file(GOOD)], [claim(`import { sum } from "./nothing.mts";\nsum([]);\n`)]);
  const r = await coordinate(cfg, await task());
  assert.equal(r.status, "cloud-ready", r.reason);
  assert.equal(r.reviews[0].claims[0].outcome, "broken test");
});

test("a claim shown by a failing test goes back to the writer, joins the suite, and is listed for the cloud", async () => {
  script([file(NO_RANGE_ERROR), file(GOOD)], [claim(THROWS_TEST), PASS]);
  const dir = await task();
  const r = await coordinate(cfg, dir);
  assert.equal(r.status, "cloud-ready", r.reason);
  assert.equal(r.reviews.length, 2);
  assert.equal(r.reviews[0].claims[0].outcome, "accepted");
  assert.deepEqual(r.reviewerTests.map(t => t.path), ["review_test_1.mts"]);
  assert.deepEqual(r.rounds.map(x => [x.passed, x.total]), [[3, 3], [4, 4]]);
  assert.match(prompts.writer[1], /A reviewer found a bug and showed it with this test/);
  assert.match(prompts.writer[1], /Tests from a reviewer, which must also pass/);
  assert.match(await readFile(join(dir, "result.md"), "utf8"), /Reviewer tests accepted[\s\S]*assert\.throws/);
});

test("a review cut at the token limit makes no claim, and the report says the change is unreviewed", async () => {
  script([file(GOOD)], [{ content: claim(`throw new Error("draft");
`) + "Wait! Let me look at line", finish_reason: "length" }]);
  const dir = await task();
  const r = await coordinate(cfg, dir);
  assert.equal(r.status, "cloud-ready", r.reason);
  assert.equal(r.reviews[0].verdict, "cut");
  assert.equal(r.reviews[0].claims.length, 0);
  assert.equal(prompts.reviewer.length, 1);
  assert.match(await readFile(join(dir, "result.md"), "utf8"), /ran out of tokens.*unreviewed/);
});

test("a writer that repeats an earlier version is stopped as stuck", async () => {
  script([file(BAD_MEAN), file(BAD_MEAN)], []);
  const r = await coordinate(cfg, await task());
  assert.equal(r.status, "stopped");
  assert.match(r.reason!, /^stuck/);
});

test("two rounds without more tests passing stop the loop", async () => {
  const other = BAD_MEAN.replace("xs.length + 1", "xs.length + 2");
  const third = BAD_MEAN.replace("xs.length + 1", "xs.length + 3");
  script([file(BAD_MEAN), file(other), file(third)], []);
  const r = await coordinate(cfg, await task());
  assert.equal(r.reason, "no progress in two rounds");
  assert.equal(r.rounds.length, 3);
});

test("files outside the list are ignored and reported; the tests stay as written", async () => {
  script([file(GOOD) + file("throw 1;\n", "tests/sum.test.mts")], [PASS]);
  const dir = await task();
  const r = await coordinate(cfg, dir);
  assert.equal(r.status, "cloud-ready", r.reason);
  assert.deepEqual(r.rounds[0].rejected, ["tests/sum.test.mts"]);
  assert.equal(await readFile(join(dir, "work", "tests", "sum.test.mts"), "utf8"), TESTS);
});

test("the round limit stops the loop", async () => {
  script([file(BAD_MEAN)], []);
  const r = await coordinate(cfg, await task(1));
  assert.equal(r.reason, "round limit (1)");
});

test("files are read from labelled blocks; one unlabelled block is the only allowed file", () => {
  const two = "### `a.py`\n```python\nA\n```\nThen b.py:\n```python\nB\n```\nexample.json\n```json\n{}\n```\n";
  assert.deepEqual(parseFiles(two, ["a.py", "b.py"]), { files: [{ path: "a.py", content: "A\n" }, { path: "b.py", content: "B\n" }],
    rejected: ["example.json"] });
  assert.deepEqual(parseFiles("Here it is:\n```python\nX\n```\n", ["only.py"]).files, [{ path: "only.py", content: "X\n" }]);
  assert.deepEqual(parseFiles("<think>a.py\n```python\nno\n```</think>", ["a.py"]).files, []);
});

test("unittest and node:test results are counted; other output counts as one test", () => {
  const unittest = "F.E\n======\nFAIL: test_a (t.T.test_a)\n------\nERROR: test_c (t.T.test_c)\n------\nRan 3 tests in 0.001s\n\nFAILED (failures=1, errors=1)\n";
  assert.deepEqual(countTests({ ok: false, output: unittest }), { passed: 1, total: 3, failing: ["test_a", "test_c"] });
  assert.deepEqual(countTests({ ok: true, output: "...\nRan 3 tests in 0.0s\n\nOK\n" }), { passed: 3, total: 3, failing: [] });
  const tap = "ok 1 - a\nnot ok 2 - b\n# tests 2\n# pass 1\n# fail 1\n";
  assert.deepEqual(countTests({ ok: false, output: tap }), { passed: 1, total: 2, failing: ["b"] });
  assert.deepEqual(countTests({ ok: false, output: "boom" }), { passed: 0, total: 1, failing: ["(the test command)"] });
});

test("stack traces point at quoted lines of the writer's files", () => {
  const files = [{ path: "pkg/m.py", content: "a = 1\nb = a / 0\n" }, { path: "sum.mts", content: "x\ny\nz\n" }];
  const out = 'File "/work/pkg/m.py", line 2, in <module>\n    at mean (file:///work/sum.mts:3:7)\nFile "/usr/lib/x.py", line 9';
  assert.deepEqual(codeLines(out, files), ["pkg/m.py:2: b = a / 0", "sum.mts:3: z"]);
});

test("the review's last verdict and its test are read; a JSON block is not the test", () => {
  const answer = '```json\n{"verdict": "pass"}\n```\nOn reflection:\n{"verdict": "fail", "issues": [{"problem": "off by one"}]}\n```ts\nT\n```\n';
  assert.deepEqual(parseReview(answer, "typescript"), { verdict: "fail", test: "T\n", problems: ["off by one"] });
  assert.equal(parseReview('{"verdict": "fail"}\n```\nU\n```\n', "python").test, "U\n");
});
