import { appendFile, mkdir, readFile } from "node:fs/promises";
import { dirname } from "node:path";

export type CallRecord = {
  id: string;
  time: string;
  tool: string;
  mode: string;
  model: string;
  /** True when the call read code files or its prompt or answer held a code block. */
  code: boolean;
  files: number;
  inputChars: number;
  outputChars: number;
  promptTokens: number;
  completionTokens: number;
  seconds: number;
  error?: string;
};

/** Every call is logged, so the savings can be measured rather than guessed. */
export async function logCall(file: string, record: CallRecord): Promise<void> {
  await appendJsonl(file, record);
}

export async function appendJsonl(file: string, record: object): Promise<void> {
  await mkdir(dirname(file), { recursive: true });
  await appendFile(file, JSON.stringify(record) + "\n", "utf8");
}

/** The records of a JSON-lines file, or none when it does not exist yet. */
export async function readJsonl<T>(file: string): Promise<T[]> {
  try {
    return (await readFile(file, "utf8")).split("\n").filter(Boolean).map(l => JSON.parse(l) as T);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw err;
  }
}

export async function stats(file: string): Promise<string> {
  const records = await readJsonl<CallRecord>(file);
  if (records.length === 0) return "No calls logged yet.";
  const ok = records.filter(r => !r.error);
  const inChars = ok.reduce((s, r) => s + r.inputChars, 0);
  const outChars = ok.reduce((s, r) => s + r.outputChars, 0);
  const seconds = ok.reduce((s, r) => s + r.seconds, 0);
  const byTool = new Map<string, number>();
  for (const r of ok) byTool.set(r.tool, (byTool.get(r.tool) ?? 0) + 1);
  return [
    `${ok.length} calls (${records.length - ok.length} failed): ${[...byTool].map(([t, n]) => `${t} ${n}`).join(", ")}`,
    `Read locally ${inChars} characters (~${Math.round(inChars / 4)} tokens est.); returned ${outChars} (~${Math.round(outChars / 4)} tokens est.)`,
    `Local model time ${seconds.toFixed(0)} s`,
  ].join("\n");
}
