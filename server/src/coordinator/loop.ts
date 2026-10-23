import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type Config, role } from "../config.ts";
import { chat, type Reply } from "../local.ts";
import { type CallRecord, logCall } from "../log.ts";
import { flowOf, refusal } from "../tripwire.ts";
import { type Feedback, parseReview, reviewerPrompt, reviewerTestPath, writerPrompt } from "./prompts.ts";
import { BROKEN, codeLines, runIn, runSuite, scriptCommand, type Sandbox, type Suite } from "./run.ts";
import { currentFiles, fingerprint, loadTask, parseFiles, prepareWork, type SourceFile, type Task, writeFiles } from "./task.ts";

export type RoundRecord = { round: number; passed: number; total: number; failing: string[]; rejected: string[];
  seconds: number; note?: string };

/** One bug claim: accepted when its test fails on the code, dropped otherwise. */
export type Claim = { review: number; outcome: "accepted" | "not reproduced" | "broken test" | "no test";
  problems: string[]; test?: SourceFile; output: string };

export type Result = {
  id: string;
  status: "cloud-ready" | "stopped";
  reason?: string;
  rounds: RoundRecord[];
  reviews: { review: number; verdict: string; claims: Claim[] }[];
  reviewerTests: SourceFile[];
  start: SourceFile[];
  files: SourceFile[];
  suite?: Suite;
  minutes: number;
  promptTokens: number;
  completionTokens: number;
  modelSwitches: number;
};

/** Failing tests that passed in an earlier round, where passing is known: that round ran and named its failures. */
function regressions(now: string[], earlier: RoundRecord[]): string[] {
  return now.filter(name => earlier.some(r => r.passed > 0 && !r.failing.includes(name)));
}

function feedback(suite: Suite, files: SourceFile[], earlier: RoundRecord[], rejected: string[],
                  claims: Feedback["claims"] = []): Feedback {
  const failingReviewer = suite.reviewer.filter(r => !r.ok);
  const output = [suite.cloud.ok ? "" : suite.cloud.output, ...failingReviewer.map(r => `${r.path}:\n${r.output}`)]
    .filter(Boolean).join("\n").slice(-3000);
  const failing = [...suite.cloud.failing, ...failingReviewer.map(r => r.path)];
  return { passed: suite.passed, total: suite.total, failing, output, codeLines: codeLines(output, files),
    regressions: regressions(failing, earlier), claims, rejected };
}

/**
 * Runs one change from its task folder to cloud-ready, or until a guard stops it (docs/COORDINATOR.md), and
 * writes result.json and result.md into the folder. The run is logged like a server call, so it can be graded.
 */
export async function coordinate(cfg: Config, dir: string): Promise<Result> {
  const cc = cfg.coordinator;
  if (!cc) throw new Error("server config has no coordinator section");
  const writer = role(cfg, cc.writer);
  const reviewer = role(cfg, cc.reviewer);
  const task = await loadTask(dir);
  await prepareWork(task);
  const sb: Sandbox = { image: cc.sandboxImage, timeoutSeconds: cc.testTimeoutSeconds };
  const started = performance.now();
  const minutes = () => (performance.now() - started) / 60000;
  const result: Result = { id: randomBytes(3).toString("hex"), status: "stopped", rounds: [], reviews: [], reviewerTests: [],
    start: await currentFiles(task), files: [], minutes: 0, promptTokens: 0, completionTokens: 0, modelSwitches: 0 };
  const record: CallRecord = { id: result.id, time: new Date().toISOString(), tool: "coordinator", mode: "loop",
    model: `${writer.model} + ${reviewer.model}`, code: true, files: task.files.length, inputChars: task.spec.length,
    outputChars: 0, promptTokens: 0, completionTokens: 0, seconds: 0 };
  let lastModel = "";
  const ask = async (r: typeof writer, prompt: string): Promise<Reply> => {
    if (r.model !== lastModel && lastModel) result.modelSwitches++;
    lastModel = r.model;
    const reply = await chat(cfg, r, prompt);
    result.promptTokens += reply.promptTokens;
    result.completionTokens += reply.completionTokens;
    return reply;
  };

  try {
    const off = await refusal(cfg, flowOf(record));
    if (off) throw new Error(off);
    result.reason = await loop(task, sb, cc.maxReviews, ask, writer, reviewer, result, minutes);
    if (!result.reason) result.status = "cloud-ready";
  } catch (err) {
    result.reason = `error: ${String(err)}`;
    record.error = String(err);
  } finally {
    result.files = await currentFiles(task);
    result.minutes = minutes();
    Object.assign(record, { promptTokens: result.promptTokens, completionTokens: result.completionTokens,
      seconds: minutes() * 60, outputChars: result.files.reduce((s, f) => s + f.content.length, 0) });
    await logCall(cfg.logFile, record);
    await writeFile(join(dir, "result.json"), JSON.stringify(result, null, 2), "utf8");
    await writeFile(join(dir, "result.md"), await report(task, result), "utf8");
  }
  return result;
}

type Ask = (r: Config["roles"][string], prompt: string) => Promise<Reply>;

/** The rounds. Returns why the loop stopped, or undefined when the change is cloud-ready. */
async function loop(task: Task, sb: Sandbox, maxReviews: number, ask: Ask, writer: Config["roles"][string],
                    reviewer: Config["roles"][string], result: Result, minutes: () => number): Promise<string | undefined> {
  const testPrint = fingerprint(task.tests);
  const seen = new Set<string>();
  let fb: Feedback | undefined;
  let best = -1;
  let stalled = 0;
  for (let round = 1; round <= task.maxRounds; round++) {
    if (minutes() > task.maxMinutes) return `time limit (${task.maxMinutes} min)`;
    const roundStart = performance.now();
    const reply = await ask(writer, writerPrompt(task, await currentFiles(task), result.reviewerTests, fb));
    const { files, rejected } = parseFiles(reply.text, task.files);
    const rec: RoundRecord = { round, passed: 0, total: 0, failing: [], rejected, seconds: 0 };
    result.rounds.push(rec);
    if (files.length === 0) {
      rec.note = reply.cut ? "answer cut at the token limit, no complete file" : "no file in the answer";
      fb = { passed: 0, total: 0, failing: [], output: "", codeLines: [], regressions: [], claims: [], rejected };
      fb.output = `Your answer held no complete file for ${task.files.join(", ")}.`;
      rec.seconds = (performance.now() - roundStart) / 1000;
      if (++stalled >= 2) return "no progress in two rounds";
      continue;
    }
    await writeFiles(task.work, files);
    const now = await currentFiles(task);
    const print = fingerprint(now);
    if (seen.has(print)) return `stuck: round ${round} wrote the same files as an earlier round`;
    seen.add(print);
    const workTests = await Promise.all(task.tests.map(async t => ({ path: t.path, content: await readFile(join(task.work, t.path), "utf8") })));
    if (fingerprint(workTests) !== testPrint) return "the tests were changed";

    let suite = await runSuite(task.work, task.test, task.language, result.reviewerTests, sb);
    result.suite = suite;
    Object.assign(rec, { passed: suite.passed, total: suite.total, failing: [...suite.cloud.failing,
      ...suite.reviewer.filter(r => !r.ok).map(r => r.path)], seconds: (performance.now() - roundStart) / 1000 });
    if (reply.cut) rec.note = "answer cut at the token limit";
    if (suite.passed > best) { best = suite.passed; stalled = 0; } else if (++stalled >= 2) return "no progress in two rounds";
    if (suite.passed < suite.total) {
      fb = feedback(suite, now, result.rounds.slice(0, -1), rejected);
      continue;
    }

    if (result.reviews.length >= maxReviews) return `review limit (${maxReviews}) reached with claims still open`;
    const claims = await review(task, sb, ask, reviewer, result);
    const accepted = claims.filter(c => c.outcome === "accepted");
    if (accepted.length === 0) return result.reviews.at(-1)!.verdict === "none" ? "the reviewer gave no verdict twice" : undefined;
    suite = await runSuite(task.work, task.test, task.language, result.reviewerTests, sb);
    result.suite = suite;
    best = suite.passed;
    stalled = 0;
    fb = feedback(suite, now, result.rounds, [], accepted.map(c => ({ test: c.test!, output: c.output })));
  }
  return `round limit (${task.maxRounds})`;
}

/**
 * One review of the current files. A claim stands only when its test fails on the code and is not broken.
 * An answer cut at the token limit makes no claim: on the bench, reviewers ran out of tokens almost only on
 * clean code, searching for a bug that was not there, and a cut answer's verdict and test are drafts.
 */
async function review(task: Task, sb: Sandbox, ask: Ask, reviewer: Config["roles"][string], result: Result): Promise<Claim[]> {
  const n = result.reviews.length + 1;
  const prompt = reviewerPrompt(task, await currentFiles(task));
  let reply = await ask(reviewer, prompt);
  let parsed = parseReview(reply.text, task.language);
  if (!parsed.verdict && !reply.cut) {
    reply = await ask(reviewer, prompt);
    parsed = parseReview(reply.text, task.language);
  }
  const claims: Claim[] = [];
  if (reply.cut) {
    result.reviews.push({ review: n, verdict: "cut", claims });
    return claims;
  }
  result.reviews.push({ review: n, verdict: parsed.verdict ?? "none", claims });
  if (parsed.verdict !== "fail") return claims;
  if (!parsed.test) {
    claims.push({ review: n, outcome: "no test", problems: parsed.problems, output: "" });
    return claims;
  }
  const test = { path: reviewerTestPath(task, result.reviewerTests.length + 1), content: parsed.test };
  await writeFiles(task.work, [test]);
  const run = await runIn(task.work, scriptCommand(task.language, test.path), sb);
  const outcome = run.ok ? "not reproduced" : BROKEN.test(run.output) ? "broken test" : "accepted";
  claims.push({ review: n, outcome, problems: parsed.problems, test, output: run.output.slice(-1500) });
  if (outcome === "accepted") result.reviewerTests.push(test);
  else await rm(join(task.work, test.path), { force: true });
  return claims;
}

/** A unified diff of two files, with the header naming the changed file instead of the scratch copies. */
function gitDiff(a: string, b: string, label: string): Promise<string> {
  return new Promise(done => execFile("git", ["diff", "--no-index", "--no-color", a, b], { maxBuffer: 32 << 20, windowsHide: true },
    (_err, stdout) => done(stdout.replace(/^diff --git .*\n(?:(?:new|deleted) file mode .*\n)?index .*\n--- .*\n\+\+\+ .*$/m,
      `--- a/${label}\n+++ b/${label}`))));
}

/** The human-readable result: what the cloud agent reads instead of the rounds. */
async function report(task: Task, r: Result): Promise<string> {
  const lines = [`# Coordinator result: ${r.status}${r.reason ? ` (${r.reason})` : ""}`, "",
    `${r.rounds.length} writer round(s), ${r.reviews.length} review(s), ${r.minutes.toFixed(1)} min, ` +
    `${r.modelSwitches} model switch(es), local tokens ${r.promptTokens} in / ${r.completionTokens} out.`, "",
    "| Round | Tests passed | Failing | Note |", "|---|---|---|---|",
    ...r.rounds.map(x => `| ${x.round} | ${x.passed} of ${x.total} | ${x.failing.slice(0, 4).join("; ") || "–"} | ` +
      `${[x.note, x.rejected.length ? `ignored files: ${x.rejected.join(", ")}` : ""].filter(Boolean).join("; ") || "–"} |`)];
  for (const rv of r.reviews) {
    lines.push("", `## Review ${rv.review}: ${rv.verdict}` +
      (rv.verdict === "cut" ? " (the answer ran out of tokens, so it made no claim; read the change as unreviewed)" : ""));
    for (const c of rv.claims) lines.push(`- claim ${c.outcome}${c.problems.length ? `: ${c.problems.join(" / ")}` : ""}`);
  }
  if (r.reviewerTests.length) {
    lines.push("", "## Reviewer tests accepted (check each: a wrong one makes the writer break working code)");
    for (const t of r.reviewerTests) lines.push("", t.path, "```" + task.language, t.content.replace(/\n$/, ""), "```");
  }
  lines.push("", "## Changes");
  const scratch = await mkdtemp(join(tmpdir(), "offload-diff-"));
  for (const f of r.files) {
    const before = r.start.find(s => s.path === f.path);
    if (before?.content === f.content) continue;
    await writeFiles(scratch, [{ path: "a", content: before?.content ?? "" }, { path: "b", content: f.content }]);
    lines.push("", "```diff", (await gitDiff(join(scratch, "a"), join(scratch, "b"), f.path)).trimEnd(), "```");
  }
  await rm(scratch, { recursive: true, force: true });
  lines.push("", `[call ${r.id}: grade it with grade_handoff once used]`);
  return lines.join("\n") + "\n";
}
