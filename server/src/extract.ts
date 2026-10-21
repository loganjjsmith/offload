import { basename } from "node:path";
import { headingsAbove, type SourceFile } from "./files.ts";

/** One extracted item: where it starts and its field values as the model copied them. */
export type Row = { file: string; line: number; values: Record<string, string | null> };

/** How many lines after an item's first line its values may sit on (an item can span a few lines). */
const SPAN = 8;

export const ROWS_PROMPT = `List every {item} in the numbered files below. Reply with a JSON array only: one object per
{item}, with exactly the keys "file", "line", {keys}. "file" is the file name and "line" the number of the
line where the {item} starts, from the numbers shown. Copy every other value exactly as it is written in
the file, without rewording, and use null when the file does not state it. If there are none, reply [].
{fields}

{files}`;

export function rowsPrompt(item: string, fields: Record<string, string>, files: string): string {
  const keys = Object.keys(fields).map(k => `"${k}"`).join(", ");
  const list = Object.entries(fields).map(([k, d]) => `- "${k}": ${d}`).join("\n");
  return ROWS_PROMPT.replaceAll("{item}", item).replace("{keys}", keys)
    .replace("{fields}", `The keys mean:\n${list}`).replace("{files}", files);
}

/** The rows in a model's answer, or undefined when it holds no JSON array. Objects without a usable line are kept, to be dropped with a reason. */
export function parseRows(text: string, keys: string[]): Row[] | undefined {
  const start = text.indexOf("["), end = text.lastIndexOf("]");
  if (start < 0 || end < start) return undefined;
  let parsed: unknown;
  try { parsed = JSON.parse(text.slice(start, end + 1)); } catch { return undefined; }
  if (!Array.isArray(parsed)) return undefined;
  return parsed.filter((o): o is Record<string, unknown> => !!o && typeof o === "object" && !Array.isArray(o))
    .map(o => ({
      file: String(o.file ?? ""),
      line: Number(o.line),
      values: Object.fromEntries(keys.map(k => [k, o[k] === null || o[k] === undefined ? null : String(o[k])])),
    }));
}

/** Text compared ignoring case, spacing, and Markdown's bold, italic and code marks, which models often drop. */
const squash = (s: string) => s.toLowerCase().replace(/[*`]+/g, "").replace(/\s+/g, " ").trim();

/**
 * Checks each row against the files in code: the file must be one that was read, the line must exist, and
 * every value must appear word for word (ignoring case and spacing) on that line or the few after it, or be
 * a whole heading the line sits under (for a field such as "section"). A model that invents or rewords a
 * value loses the row, and the reason is reported.
 */
export function checkRows(rows: Row[], files: SourceFile[]): { kept: Row[]; dropped: string[] } {
  const kept: Row[] = [], dropped: string[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    const name = basename(row.file.replace(/\\/g, "/")).toLowerCase();
    const candidates = files.filter(f => f.path.toLowerCase() === row.file.toLowerCase()
      || basename(f.path.replace(/\\/g, "/")).toLowerCase() === name);
    const where = `${row.file || "(no file)"}:${Number.isFinite(row.line) ? row.line : "?"}`;
    if (candidates.length === 0) { dropped.push(`${where}: not a file that was read`); continue; }
    let reason = "";
    const match = candidates.find(f => {
      const lines = f.text.replace(/\r\n/g, "\n").split("\n");
      if (!Number.isInteger(row.line) || row.line < 1 || row.line > lines.length) { reason = "the line does not exist"; return false; }
      const near = squash(lines.slice(row.line - 1, row.line + SPAN).join(" "));
      const headings = headingsAbove(lines, row.line).map(squash);
      const missing = Object.entries(row.values)
        .find(([, v]) => v !== null && !near.includes(squash(v)) && !headings.includes(squash(v).replace(/^#+\s*/, "")));
      if (missing) { reason = `"${missing[0]}" value ${JSON.stringify(missing[1])} is not on lines ${row.line}–${row.line + SPAN} or a heading above them`; return false; }
      return true;
    });
    if (!match) { dropped.push(`${where}: ${reason}`); continue; }
    const fixed = { ...row, file: basename(match.path.replace(/\\/g, "/")) };
    // The same item listed twice, from overlapping chunks or differing only in case or spacing, is kept once.
    const key = JSON.stringify([match.path, row.line, Object.values(row.values).map(v => v === null ? null : squash(v))]);
    if (!seen.has(key)) { seen.add(key); kept.push(fixed); }
  }
  return { kept, dropped };
}

const cell = (v: string | null) => v === null ? "" : v.replace(/\s+/g, " ").trim();

/** Kept rows as tab-separated lines under a header, then what was dropped and any other notes. */
export function rowsTable(keys: string[], kept: Row[], dropped: string[], notes: string[]): string {
  const out = [`${kept.length} rows (model-made, every value checked against the file by code); ${dropped.length} dropped.`,
    ["where", ...keys].join("\t"),
    ...kept.map(r => [`${r.file}:${r.line}`, ...keys.map(k => cell(r.values[k]))].join("\t"))];
  if (dropped.length) out.push("", "Dropped by the check:", ...dropped.map(d => `- ${d}`));
  if (notes.length) out.push("", ...notes.map(n => `Note: ${n}`));
  return out.join("\n");
}
