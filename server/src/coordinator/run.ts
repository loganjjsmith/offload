import { execFile } from "node:child_process";
import { resolve } from "node:path";
import type { Language, SourceFile } from "./task.ts";

export type Run = { ok: boolean; output: string };

/** Where tests run: in a Docker image with no network (the bench's coding sandbox), or directly when `image` is unset. */
export type Sandbox = { image?: string; timeoutSeconds: number };

/** Runs a command in the work folder; exit code 0 is a pass. Output keeps its last 4,000 characters. */
export function runIn(work: string, command: string[], sb: Sandbox): Promise<Run> {
  const [file, args] = sb.image
    ? ["docker", ["run", "--rm", "--network", "none", "-v", `${resolve(work)}:/work`, "-w", "/work", sb.image, ...command]]
    : [command[0], command.slice(1)];
  // A node:test run started from inside another one would otherwise skip its files.
  const { NODE_TEST_CONTEXT: _, ...env } = process.env;
  return new Promise(done => {
    execFile(file, args, { cwd: work, env, timeout: sb.timeoutSeconds * 1000, maxBuffer: 32 << 20, windowsHide: true },
      (err, stdout, stderr) => {
        const output = `${stdout}${stderr}`.slice(-4000);
        if (err && (err as { killed?: boolean }).killed) done({ ok: false, output: `timed out after ${sb.timeoutSeconds} s\n${output}` });
        else done({ ok: !err, output });
      });
  });
}

/** How a standalone test script (a reviewer's proof) is run. */
export const scriptCommand = (language: Language, path: string) => language === "python" ? ["python3", path] : ["node", path];

export type Count = { passed: number; total: number; failing: string[] };

/**
 * Passing and failing tests, read from Python unittest or node:test output. Output in neither format
 * counts as one test, passed or failed by the exit code.
 */
export function countTests(r: Run): Count {
  const ran = /^Ran (\d+) tests?/m.exec(r.output);
  if (ran) {
    const total = Number(ran[1]);
    const bad = [...r.output.matchAll(/^(?:FAIL|ERROR): (.+)$/gm)].map(m => m[1].trim().replace(/ \([\w.]+\)$/, ""));
    const counted = /^FAILED \((.*)\)$/m.exec(r.output)?.[1] ?? "";
    const failed = [...counted.matchAll(/(?:failures|errors)=(\d+)/g)].reduce((s, m) => s + Number(m[1]), 0);
    return { passed: r.ok ? total : total - Math.max(failed, bad.length), total, failing: bad };
  }
  const pass = /^# pass (\d+)$/m.exec(r.output);
  const fail = /^# fail (\d+)$/m.exec(r.output);
  if (pass && fail) {
    const failing = [...r.output.matchAll(/^\s*not ok \d+ - (.+)$/gm)].map(m => m[1].trim());
    return { passed: Number(pass[1]), total: Number(pass[1]) + Number(fail[1]), failing };
  }
  return { passed: r.ok ? 1 : 0, total: 1, failing: r.ok ? [] : ["(the test command)"] };
}

/** Output of a test that never ran its checks because it did not build, load or parse. */
export const BROKEN = /SyntaxError|IndentationError|ImportError|ModuleNotFoundError|ERR_MODULE_NOT_FOUND|ERR_INVALID_TYPESCRIPT_SYNTAX|does not provide an export/;

/** The lines of the writer's files that a failure's stack trace points at, quoted, at most eight. */
export function codeLines(output: string, files: SourceFile[]): string[] {
  const refs = [
    ...[...output.matchAll(/File "([^"]+)", line (\d+)/g)].map(m => [m[1], m[2]]),
    ...[...output.matchAll(/([^\s()'"]+?\.(?:mts|ts|mjs|js|py)):(\d+)(?::\d+)?/g)].map(m => [m[1], m[2]]),
  ];
  const out: string[] = [];
  for (const [where, line] of refs) {
    const path = where.replace(/\\/g, "/").replace(/^file:\/\//, "");
    const file = files.find(f => path === f.path || path.endsWith("/" + f.path));
    const text = file?.content.split("\n")[Number(line) - 1];
    const quoted = file && text !== undefined ? `${file.path}:${line}: ${text.trim()}` : undefined;
    if (quoted && !out.includes(quoted)) out.push(quoted);
  }
  return out.slice(0, 8);
}

export type Suite = {
  cloud: Run & Count;
  /** Accepted reviewer tests, each run on its own. */
  reviewer: (Run & { path: string })[];
  passed: number;
  total: number;
};

/** The cloud's tests and every accepted reviewer test, run in full. */
export async function runSuite(work: string, test: string[], language: Language, reviewerTests: SourceFile[],
                               sb: Sandbox): Promise<Suite> {
  const run = await runIn(work, test, sb);
  const cloud = { ...run, ...countTests(run) };
  const reviewer = [];
  for (const t of reviewerTests) reviewer.push({ path: t.path, ...await runIn(work, scriptCommand(language, t.path), sb) });
  const ok = reviewer.filter(r => r.ok).length;
  return { cloud, reviewer, passed: cloud.passed + ok, total: cloud.total + reviewer.length };
}
