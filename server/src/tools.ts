import { type Config, role } from "./config.ts";
import { coverageNote } from "./coverage.ts";
import { checkRows, parseRows, type Row, rowsPrompt, rowsTable } from "./extract.ts";
import { chunk, readSources } from "./files.ts";
import { chat, type Reply } from "./local.ts";
import { randomBytes } from "node:crypto";
import { type CallRecord, logCall } from "./log.ts";
import { flowOf, hasCodeBlock, isCodeFile, refusal } from "./tripwire.ts";

const SUMMARY = `Summarise the files below for a developer who will act on the summary without reading them.
Facts only, as a terse bulleted list. Give each fact a file:line reference from the line numbers shown,
always with the file name, for example (Notes.md:12) or (Notes.md:40–45).
Say plainly when something asked about is not in the files. No preamble, no closing remarks.
{focus}

{files}`;

const COMBINE = `These are summaries of consecutive parts of the same set of files. Merge them into one terse
bulleted list of facts with their file:line references, removing repeats. No preamble.
{focus}

{parts}`;

const focusLine = (focus?: string) => focus ? `Focus on: ${focus}` : "";

/**
 * Runs one tool call with the mode's role and logs it, failures included, unless the tripwire has switched
 * its flow off. `work` gets an `ask` that sends a prompt to the local model and adds its token counts to the
 * record. The answer ends with the call's id, which the caller passes to grade_handoff.
 */
async function logged(cfg: Config, tool: string, modeName: string | undefined, inputChars: number,
  work: (ask: (prompt: string) => Promise<Reply>, record: CallRecord) => Promise<string>): Promise<string> {
  const mode = modeName ?? "fast";
  const r = role(cfg, mode);
  const started = performance.now();
  const record: CallRecord = { id: randomBytes(3).toString("hex"), time: new Date().toISOString(), tool, mode,
    model: r.model, code: false, files: 0, inputChars, outputChars: 0, promptTokens: 0, completionTokens: 0, seconds: 0 };
  const ask = async (prompt: string) => {
    const reply = await chat(cfg, r, prompt);
    record.promptTokens += reply.promptTokens;
    record.completionTokens += reply.completionTokens;
    return reply;
  };
  try {
    const off = await refusal(cfg, flowOf(record));
    if (off) throw new Error(off);
    const text = await work(ask, record);
    record.outputChars = text.length;
    return `${text}\n\n[call ${record.id}: grade it with grade_handoff once used]`;
  } catch (err) {
    record.error = String(err);
    throw err;
  } finally {
    record.seconds = (performance.now() - started) / 1000;
    await logCall(cfg.logFile, record);
  }
}

/** Reads files on this machine and returns only the local model's summary; the files never reach the cloud. */
export function summarizeFiles(cfg: Config, args: { paths: string[]; focus?: string; mode?: string }) {
  return logged(cfg, "summarize_files", args.mode, 0, async (ask, record) => {
    const files = await readSources(args.paths, cfg.readRoots);
    record.files = files.length;
    record.code = files.some(f => isCodeFile(f.path));
    record.inputChars = files.reduce((s, f) => s + f.text.length, 0);
    const parts = [];
    for (const piece of chunk(files, cfg.chunkChars))
      parts.push((await ask(SUMMARY.replace("{focus}", focusLine(args.focus)).replace("{files}", piece))).text);
    let text = parts[0];
    if (parts.length > 1)
      text = (await ask(COMBINE.replace("{focus}", focusLine(args.focus)).replace("{parts}", parts.join("\n\n---\n\n")))).text;
    return text + coverageNote(text, files);
  });
}

/**
 * Lists every item of a kind in the files as rows of copied values, the row method measured in the bench:
 * the model only copies, in small chunks, and code checks every value against the file. Counting, sorting
 * and other reasoning over the rows is left to the caller.
 */
export function extractRows(cfg: Config, args: { paths: string[]; item: string; fields: Record<string, string>; mode?: string }) {
  return logged(cfg, "extract", args.mode, 0, async (ask, record) => {
    const files = await readSources(args.paths, cfg.readRoots);
    record.files = files.length;
    record.code = files.some(f => isCodeFile(f.path));
    record.inputChars = files.reduce((s, f) => s + f.text.length, 0);
    const keys = Object.keys(args.fields);
    const rows: Row[] = [], notes: string[] = [];
    const pieces = chunk(files, cfg.extractChunkChars);
    for (const [i, piece] of pieces.entries()) {
      const prompt = rowsPrompt(args.item, args.fields, piece);
      let reply = await ask(prompt);
      let parsed = parseRows(reply.text, keys);
      // An occasional reply holds broken JSON though the same prompt usually works, so one retry is made.
      if (!parsed && !reply.cut) { reply = await ask(prompt); parsed = parseRows(reply.text, keys); }
      const which = pieces.length > 1 ? `part ${i + 1} of ${pieces.length} (${piece.split("\n")[0].replace(/^=== | ===.*$/g, "")})` : "the answer";
      if (!parsed) notes.push(`${which} ${reply.cut ? "stopped at the token limit before its JSON array closed" : "held no readable JSON array"}, so its rows are missing.`);
      else if (reply.cut) notes.push(`${which} stopped at the token limit, so its last rows may be missing.`);
      rows.push(...(parsed ?? []));
    }
    const { kept, dropped } = checkRows(rows, files);
    return rowsTable(keys, kept, dropped, notes);
  });
}

/** A self-contained question answered by the local model. */
export function askLocal(cfg: Config, args: { prompt: string; mode?: string }) {
  return logged(cfg, "ask_local", args.mode, args.prompt.length, async (ask, record) => {
    const text = (await ask(args.prompt)).text;
    record.code = hasCodeBlock(args.prompt) || hasCodeBlock(text);
    return text;
  });
}
