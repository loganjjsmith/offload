import { createHash } from "node:crypto";
import { cp, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, relative } from "node:path";

export type Language = "python" | "typescript";

/** A file as a path relative to the work folder, with forward slashes, and its text. */
export type SourceFile = { path: string; content: string };

/**
 * A change the cloud agent specified, read from its task folder (docs/COORDINATOR.md, "Input"):
 * task.json, spec.md, tests/, and optionally context/ (read-only files the code needs) and start/
 * (the files as they are before the change).
 */
export type Task = {
  dir: string;
  work: string;
  language: Language;
  /** The only files the writer may create or change. */
  files: string[];
  /** The command that runs the cloud's tests from the work folder; exit code 0 means they all pass. */
  test: string[];
  maxRounds: number;
  maxMinutes: number;
  spec: string;
  tests: SourceFile[];
  context: SourceFile[];
};

const slash = (p: string) => p.replace(/\\/g, "/");

async function readTree(root: string): Promise<SourceFile[]> {
  let entries;
  try {
    entries = await readdir(root, { recursive: true, withFileTypes: true });
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw err;
  }
  const files = entries.filter(e => e.isFile()).map(e => join(e.parentPath, e.name));
  return Promise.all(files.sort().map(async f => ({ path: slash(relative(root, f)), content: await readFile(f, "utf8") })));
}

export async function loadTask(dir: string): Promise<Task> {
  const json = JSON.parse((await readFile(join(dir, "task.json"), "utf8")).replace(/^﻿/, ""));
  if (json.language !== "python" && json.language !== "typescript") {
    throw new Error(`task.json: language must be "python" or "typescript", not ${JSON.stringify(json.language)}`);
  }
  if (!Array.isArray(json.files) || json.files.length === 0) throw new Error("task.json: files must list the files the writer may change");
  if (!Array.isArray(json.test) || json.test.length === 0) throw new Error("task.json: test must be the test command, as a list");
  const tests = (await readTree(join(dir, "tests"))).map(f => ({ ...f, path: `tests/${f.path}` }));
  if (tests.length === 0) throw new Error("The task has no tests/ folder, or it is empty");
  return {
    dir, work: join(dir, "work"), language: json.language, files: json.files.map(slash), test: json.test,
    maxRounds: json.maxRounds ?? 4, maxMinutes: json.maxMinutes ?? 60,
    spec: await readFile(join(dir, "spec.md"), "utf8"), tests, context: await readTree(join(dir, "context")),
  };
}

/** A fresh work folder: the start files, the context files and the tests. */
export async function prepareWork(task: Task): Promise<void> {
  await rm(task.work, { recursive: true, force: true });
  await mkdir(task.work, { recursive: true });
  for (const sub of ["start", "context"]) {
    await cp(join(task.dir, sub), task.work, { recursive: true }).catch(err => {
      if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
    });
  }
  await cp(join(task.dir, "tests"), join(task.work, "tests"), { recursive: true });
}

/** The current text of the files the writer may change; a file not yet written is absent. */
export async function currentFiles(task: Task): Promise<SourceFile[]> {
  const out: SourceFile[] = [];
  for (const path of task.files) {
    try {
      out.push({ path, content: await readFile(join(task.work, path), "utf8") });
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
    }
  }
  return out;
}

export async function writeFiles(root: string, files: SourceFile[]): Promise<void> {
  for (const f of files) {
    await mkdir(dirname(join(root, f.path)), { recursive: true });
    await writeFile(join(root, f.path), f.content, "utf8");
  }
}

export const fingerprint = (files: SourceFile[]) =>
  createHash("sha256").update(files.map(f => `${f.path}\0${f.content}`).join("\0")).digest("hex");

/**
 * The files in a writer's answer. Each is a fenced block whose nearest non-blank line above names its path,
 * as a heading, in backticks or bare. With only one allowed file, a single unlabelled block is that file.
 * Blocks naming a path outside `allowed` are returned in `rejected`.
 */
export function parseFiles(answer: string, allowed: string[]): { files: SourceFile[]; rejected: string[] } {
  const text = answer.replace(/<think>[\s\S]*?<\/think>/g, "");
  const lines = text.split("\n");
  const blocks: { label: string; content: string }[] = [];
  for (let i = 0; i < lines.length; i++) {
    if (!/^```[\w#+.-]*\s*$/.test(lines[i])) continue;
    let j = i - 1;
    while (j >= 0 && lines[j].trim() === "") j--;
    const end = lines.findIndex((l, k) => k > i && l.trim() === "```");
    if (end < 0) break;
    blocks.push({ label: j >= 0 ? lines[j] : "", content: lines.slice(i + 1, end).join("\n") + "\n" });
    i = end;
  }
  const files: SourceFile[] = [];
  const rejected: string[] = [];
  for (const b of blocks) {
    const named = /[`*#:\s]*([\w./\\-]+\.\w+)[`*:\s]*$/.exec(b.label)?.[1];
    const path = named ? slash(named) : allowed.length === 1 && blocks.length === 1 ? allowed[0] : undefined;
    if (!path) continue;
    if (allowed.includes(path)) files.push({ path, content: b.content });
    else rejected.push(path);
  }
  return { files, rejected };
}
