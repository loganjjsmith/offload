import { basename, dirname } from "node:path/posix";
import type { Language, SourceFile, Task } from "./task.ts";

const FENCE: Record<Language, string> = { python: "python", typescript: "typescript" };
const TAGS: Record<Language, string[]> = { python: ["python", "py"], typescript: ["typescript", "ts"] };

const block = (f: SourceFile, language: Language) => `${f.path}\n\`\`\`${FENCE[language]}\n${f.content.replace(/\n$/, "")}\n\`\`\``;
const numbered = (f: SourceFile) => f.content.replace(/\n$/, "").split("\n").map((l, i) => `${String(i + 1).padStart(3)}  ${l}`).join("\n");

/** What went wrong in the previous round, for the writer. Empty on the first round. */
export type Feedback = {
  passed: number;
  total: number;
  failing: string[];
  output: string;
  codeLines: string[];
  /** Tests that passed in an earlier round and fail now. */
  regressions: string[];
  /** Reviewer tests accepted since the last round: each fails on the current code. */
  claims: { test: SourceFile; output: string }[];
  rejected: string[];
};

export function writerPrompt(task: Task, current: SourceFile[], reviewerTests: SourceFile[], fb?: Feedback): string {
  const parts = [
    "You are writing code for the change specified below. Write every file in the list completely.",
    `Specification:\n${task.spec.trim()}`,
    `Files you write, and only these: ${task.files.join(", ")}`,
  ];
  if (task.context.length) parts.push("Read-only files the code uses:\n\n" + task.context.map(f => block(f, task.language)).join("\n\n"));
  parts.push("The tests your code must pass. You cannot change them:\n\n" + task.tests.map(f => block(f, task.language)).join("\n\n"));
  if (reviewerTests.length) {
    parts.push("Tests from a reviewer, which must also pass:\n\n" + reviewerTests.map(f => block(f, task.language)).join("\n\n"));
  }
  if (current.length) parts.push("The files as they are now:\n\n" + current.map(f => block(f, task.language)).join("\n\n"));
  if (fb) {
    const lines = [`Your last version passed ${fb.passed} of ${fb.total} tests.`];
    if (fb.rejected.length) lines.push(`These files are not yours to write and were ignored: ${fb.rejected.join(", ")}.`);
    if (fb.failing.length) lines.push(`Failing: ${fb.failing.join("; ")}`);
    if (fb.regressions.length) {
      lines.push(`These passed in an earlier round and fail now, so keep the earlier fix while making this one: ${fb.regressions.join("; ")}`);
    }
    if (fb.output) lines.push(`The end of the test output:\n\`\`\`\n${fb.output.trim()}\n\`\`\``);
    if (fb.codeLines.length) lines.push(`The lines of your code the failures point at:\n${fb.codeLines.map(l => `- ${l}`).join("\n")}`);
    for (const c of fb.claims) {
      lines.push(`A reviewer found a bug and showed it with this test, which fails on your code:\n${block(c.test, task.language)}\n` +
        `Its output:\n\`\`\`\n${c.output.trim()}\n\`\`\``);
    }
    parts.push(lines.join("\n\n"));
  }
  parts.push("Answer with each file as a line holding its path, then the complete file in one fenced code block. " +
    "Write no other code blocks.");
  return parts.join("\n\n");
}

/** Where a reviewer's test is saved: next to the first file, so it imports the code the way a neighbour would. */
export const reviewerTestPath = (task: Task, n: number) => {
  const dir = dirname(task.files[0]);
  return `${dir === "." ? "" : dir + "/"}review_test_${n}.${task.language === "python" ? "py" : "mts"}`;
};

function testFormat(task: Task): string {
  const first = basename(task.files[0]);
  return task.language === "python"
    ? "The test is a Python script run with python3 from the folder that holds the code. Import from the code's " +
      `files as modules (for example \`from ${first.replace(/\.py$/, "")} import ...\`) and check with plain \`assert\` ` +
      "statements at the top level (a function you define must also be called); the test fails by raising."
    : "The test is a TypeScript module run by Node 24 with type stripping, from the folder that holds the code. " +
      `Import with \`import { ... } from "./${first}";\` and \`import assert from "node:assert/strict";\`; ` +
      "the test fails by throwing.";
}

/** Review prompt version 2 with the proof request, as measured by the bench task review_proof. */
export function reviewerPrompt(task: Task, files: SourceFile[]): string {
  const code = files.map(f => `--- ${f.path} ---\n${numbered(f)}`).join("\n\n");
  return `Review the following ${task.language} code against its specification. It may be correct, or it may contain one or more bugs. Check it carefully, including the edge cases the specification mentions.
Judge it only against the specification. Report a bug only if you can give an input the specification covers on which the code returns a wrong result or fails. Inputs the specification does not mention (such as null or malformed arguments it says nothing about), style, performance and robustness beyond the specification are not bugs.

Specification:
${task.spec.trim()}

Code (line numbers added for reference):
${code}

Reply with a JSON object: {"verdict": "pass" or "fail", "issues": [{"line": <line number>, "problem": "<what is wrong>", "failing_input": "<an input that shows it>"}]}
Use "pass" with an empty issues list if the code meets the specification.

If your verdict is "fail", prove it: after the JSON object, write one test that fails on this code and passes on any correct implementation of the specification. ${testFormat(task)} Do not repeat the code under review; the test runs with it. Use only the standard library. Put the test in a single \`\`\`${FENCE[task.language]} code block.`;
}

/** The last verdict and the reviewer's test: the last block tagged with the language, else the last untagged one. */
export function parseReview(answer: string, language: Language): { verdict?: "pass" | "fail"; test?: string; problems: string[] } {
  const text = answer.replace(/<think>[\s\S]*?<\/think>/g, "");
  const verdicts = [...text.matchAll(/"verdict"\s*:\s*"(pass|fail)"/gi)].map(m => m[1].toLowerCase() as "pass" | "fail");
  const blocks = [...text.matchAll(/^```([\w#+-]*)[ \t]*\n([\s\S]*?)^```/gm)].map(m => ({ tag: m[1].toLowerCase(), code: m[2] }));
  const tagged = blocks.filter(b => TAGS[language].includes(b.tag)).map(b => b.code);
  const untagged = blocks.filter(b => !b.tag && !b.code.includes('"verdict"')).map(b => b.code);
  const found = tagged.length ? tagged : untagged;
  const problems = [...text.matchAll(/"problem"\s*:\s*"((?:[^"\\]|\\.)*)"/g)].map(m => m[1]);
  return { verdict: verdicts.at(-1), test: found.at(-1), problems };
}
