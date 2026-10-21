import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { Config } from "./config.ts";
import { appendJsonl, type CallRecord, readJsonl } from "./log.ts";

export const GRADES = ["used", "fixed", "redone", "misleading"] as const;
export type Grade = typeof GRADES[number];

export type GradeRecord = {
  time: string;
  callId: string;
  callTime: string;
  flow: string;
  code: boolean;
  grade: Grade;
  note?: string;
};

/**
 * A flow that tripped. `since` is when it was switched off; after it is switched back on, only calls made
 * after `since` count towards tripping it again, so the grades that switched it off cannot do so twice.
 */
export type FlowState = { off: boolean; since: string; reason: string; examples: { callId: string; grade: Grade; note?: string }[] };
type State = Record<string, FlowState>;

const CODE_FILE = /\.(cs|java|kt|ts|tsx|js|jsx|mjs|cjs|py|c|cc|cpp|h|hpp|go|rs|rb|php|swift|lua|shader|hlsl|cginc|ps1|sh)$/i;

export const isCodeFile = (path: string) => CODE_FILE.test(path);
export const hasCodeBlock = (text: string) => text.includes("```");

/** A flow is one way of handing work out: the tool, the mode and the model behind it. */
export const flowOf = (r: { tool: string; mode: string; model: string }) => `${r.tool} ${r.mode} ${r.model}`;

const isBad = (g: Grade) => g === "redone" || g === "misleading";
const gradesFile = (cfg: Config) => join(dirname(cfg.logFile), "grades.jsonl");
const stateFile = (cfg: Config) => join(dirname(cfg.logFile), "flows.json");

async function readState(cfg: Config): Promise<State> {
  try {
    return JSON.parse((await readFile(stateFile(cfg), "utf8")).replace(/^﻿/, "")) as State;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return {};
    throw err;
  }
}

/** The latest grade of each call, oldest call first; grading a call again replaces its earlier grade. */
function latestPerCall(grades: GradeRecord[]): GradeRecord[] {
  const byCall = new Map<string, GradeRecord>();
  for (const g of grades) byCall.set(g.callId, g);
  return [...byCall.values()].sort((a, b) => a.callTime.localeCompare(b.callTime));
}

/** The refusal for a call to a switched-off flow, or undefined when the flow is on. */
export async function refusal(cfg: Config, flow: string): Promise<string | undefined> {
  const s = (await readState(cfg))[flow];
  if (!s?.off) return undefined;
  return `The flow "${flow}" was switched off at ${s.since} because ${s.reason}. Do this job directly ` +
    `instead of delegating it. A person switches the flow back on after fixing it (server/README.md, "Tripwire").`;
}

/**
 * Records the grade of one call and switches its flow off when the flow's redone and misleading answers
 * reach `maxBadShare` of the last `window` graded calls (calls not yet graded count as good, so a new flow
 * can trip before its window fills), or at once when a misleading answer was about code.
 */
export async function gradeHandoff(cfg: Config, args: { callId: string; grade: Grade; note?: string }): Promise<string> {
  const call = (await readJsonl<CallRecord>(cfg.logFile)).findLast(r => r.id === args.callId);
  if (!call) throw new Error(`No call with id ${args.callId} in the log.`);
  if (call.error) throw new Error(`Call ${args.callId} failed, so it returned nothing to grade.`);
  const flow = flowOf(call);
  const record: GradeRecord = { time: new Date().toISOString(), callId: call.id, callTime: call.time, flow,
    code: call.code, grade: args.grade, ...(args.note ? { note: args.note } : {}) };
  await appendJsonl(gradesFile(cfg), record);

  const state = await readState(cfg);
  if (state[flow]?.off) return `Graded ${call.id} ${args.grade}. The flow "${flow}" is already switched off.`;
  const since = state[flow]?.since ?? "";
  if (call.time <= since) return `Graded ${call.id} ${args.grade}. The call predates the flow's last switch-off, so it does not count towards the tripwire.`;
  const { window, maxBadShare } = cfg.tripwire;
  const recent = latestPerCall((await readJsonl<GradeRecord>(gradesFile(cfg))).filter(g => g.flow === flow && g.callTime > since))
    .slice(-window);
  const bad = recent.filter(g => isBad(g.grade));
  const reason = args.grade === "misleading" && call.code ? `a misleading answer about code (call ${call.id})`
    : bad.length / window >= maxBadShare
      ? `${bad.length} of its last ${recent.length} graded calls were redone or misleading (the limit is ${Math.round(maxBadShare * 100)}% of ${window})`
      : undefined;
  if (!reason)
    return `Graded ${call.id} ${args.grade}. The flow "${flow}" has ${bad.length} redone or misleading in its last ` +
      `${recent.length} graded calls; it switches off at ${Math.ceil(maxBadShare * window - 1e-9)} of ${window}.`;

  state[flow] = { off: true, since: record.time, reason,
    examples: bad.map(g => ({ callId: g.callId, grade: g.grade, ...(g.note ? { note: g.note } : {}) })) };
  await writeFile(stateFile(cfg), JSON.stringify(state, null, 2) + "\n", "utf8");
  console.error(`offload tripwire: switched off "${flow}" because ${reason}`);
  return `Graded ${call.id} ${args.grade}. The flow "${flow}" is now switched off because ${reason}; ` +
    `its jobs go to you directly until it is fixed. Note this where the next session and Logan will see it.`;
}

/** Grades per flow, the calls not graded yet, and each switched-off flow with its bad examples. */
export async function gradeReport(cfg: Config): Promise<string> {
  const grades = latestPerCall(await readJsonl<GradeRecord>(gradesFile(cfg)));
  const graded = new Set(grades.map(g => g.callId));
  const ungraded = (await readJsonl<CallRecord>(cfg.logFile)).filter(r => r.id && !r.error && !graded.has(r.id)).length;
  const state = await readState(cfg);
  const flows = [...new Set([...grades.map(g => g.flow), ...Object.keys(state)])].sort();
  if (flows.length === 0) return `No handoffs graded yet (${ungraded} calls to grade).`;
  const lines = [`Grades per flow, used / fixed / redone / misleading (${ungraded} calls not graded yet):`];
  for (const flow of flows) {
    const counts = GRADES.map(k => grades.filter(g => g.flow === flow && g.grade === k).length);
    const s = state[flow];
    lines.push(`  ${flow}: ${counts.join(" / ")}${s?.off ? ` SWITCHED OFF at ${s.since}: ${s.reason}` : ""}`);
    if (s?.off) for (const e of s.examples) lines.push(`    - call ${e.callId} ${e.grade}${e.note ? `: ${e.note}` : ""}`);
  }
  return lines.join("\n");
}
