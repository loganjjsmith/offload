import { basename } from "node:path";
import type { SourceFile } from "./files.ts";

export type Section = { file: string; heading: string; start: number; end: number };

const lines = (f: SourceFile) => f.text.replace(/\r\n/g, "\n").split("\n");

const MODIFIERS = String.raw`(?:(?:public|private|protected|internal|static|virtual|override|abstract|sealed|async|partial|readonly|unsafe|extern|new|export|default|declare)\s+)*`;
const TYPE_DECL = new RegExp(String.raw`^\s*(?:\[[^\]]*\]\s*)*${MODIFIERS}(?:class|struct|interface|enum|record|type)\s+(\w+)`);
const NOT_A_RETURN_TYPE = new Set(["return", "await", "new", "else", "throw", "yield", "case", "goto", "using", "var", "let", "const", "typeof", "is", "as", "in", "out", "ref"]);
const NOT_A_NAME = new Set(["if", "for", "foreach", "while", "switch", "catch", "using", "lock", "fixed", "return", "nameof", "typeof", "sizeof", "function"]);

/** C#, Java, TypeScript and JavaScript declarations on one line: its name, or undefined when the line declares nothing. */
function curlyDeclaration(line: string): string | undefined {
  const type = TYPE_DECL.exec(line);
  if (type) return type[1];
  const fn = /^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\*?\s+(\w+)/.exec(line)
    ?? /^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*(?::[^=]+)?=>/.exec(line);
  if (fn) return fn[1];
  // A method: an optional return type, a name, and an opening parenthesis, with no statement end on the line.
  const method = new RegExp(String.raw`^\s*(?:\[[^\]]*\]\s*)*(${MODIFIERS})(?:(?:get|set)\s+)?(?:([\w<>\[\],.?]+)\s+)?(\w+)\s*(?:<[^>]*>)?\s*\([^;]*$`).exec(line);
  if (!method || NOT_A_NAME.has(method[3]) || (method[2] && NOT_A_RETURN_TYPE.has(method[2]))) return undefined;
  // With no return type, only a constructor (it has an access modifier) or a TypeScript method that opens
  // its body on the same line qualifies; anything else is a call spread over several lines.
  if (!method[2] && !/\b(?:public|private|protected|internal|static)\b/.test(method[1])
    && !/\)\s*(?::[^={]+)?\{\s*$/.test(line)) return undefined;
  return method[3];
}

const pythonDeclaration = (line: string) => /^\s*(?:async\s+)?(?:def|class)\s+(\w+)/.exec(line)?.[1];

/**
 * The parts of a file a summary should touch: Markdown sections from each heading to the line before the
 * next, or in code each class, type, function or method from its declaration to the line before the next
 * declaration. Parts with fewer than two non-blank lines of body (headings that only introduce sub-sections,
 * a class line straight above its first method) are left out. Other files have no parts.
 */
export function sections(file: SourceFile): Section[] {
  const text = lines(file);
  const find: ((line: string) => string | undefined) | undefined =
    /\.(md|markdown)$/i.test(file.path) ? l => /^#{1,6}\s/.test(l) ? l.replace(/^#+\s*/, "") : undefined
    : /\.(cs|java|ts|tsx|js|jsx|mjs)$/i.test(file.path) ? curlyDeclaration
    : /\.py$/i.test(file.path) ? pythonDeclaration
    : undefined;
  if (!find) return [];
  const starts = text.flatMap((l, i) => { const name = find(l); return name ? [{ i, name }] : []; });
  return starts.flatMap(({ i: s, name }, k) => {
    const e = k + 1 < starts.length ? starts[k + 1].i - 1 : text.length - 1;
    const body = text.slice(s + 1, e + 1).filter(l => l.trim() !== "").length;
    return body < 2 ? [] : [{ file: file.path, heading: name, start: s + 1, end: e + 1 }];
  });
}

const LIST = String.raw`\d+(?:\s*[–-]\s*\d+)?(?:\s*,\s*\d+(?:\s*[–-]\s*\d+)?)*`;

const expand = (list: string) => list.split(",").flatMap(part => {
  const [a, b = a] = part.split(/[–-]/).map(n => Number(n.trim()));
  return Array.from({ length: Math.max(0, b - a + 1) }, (_, i) => a + i);
});

/**
 * Every line a summary cites per file, from references like `name.md:38`, `name.md:94, 95` or
 * `name.md:99–110`. When only one file was read, bare references such as `(38)` or `(44, 55)` count too,
 * since models often drop the file name when there is only one.
 */
export function citedLines(summary: string, files: SourceFile[]): Map<string, number[]> {
  const cited = new Map<string, number[]>(files.map(f => [f.path, []]));
  for (const m of summary.matchAll(new RegExp(String.raw`([\w.\-\/\\]+\.\w+):(${LIST})`, "g"))) {
    const name = basename(m[1].replace(/\\/g, "/")).toLowerCase();
    const file = files.find(f => basename(f.path).toLowerCase() === name);
    if (file) cited.get(file.path)!.push(...expand(m[2]));
  }
  if (files.length === 1) {
    for (const m of summary.matchAll(new RegExp(String.raw`\((?:lines?\s*)?(${LIST})\)`, "g")))
      cited.get(files[0].path)!.push(...expand(m[1]));
  }
  return cited;
}

/**
 * A note listing what the summary never cites: sections with no reference inside them, and references to
 * lines that do not exist. Empty when the summary covers every section. Computed by code, not the model,
 * so the caller knows exactly which parts it still has to read itself.
 */
export function coverageNote(summary: string, files: SourceFile[]): string {
  const cited = citedLines(summary, files);
  const notes: string[] = [];
  for (const f of files) {
    const hits = cited.get(f.path)!;
    const count = lines(f).length;
    const bad = [...new Set(hits.filter(n => n < 1 || n > count))];
    if (bad.length) notes.push(`- ${basename(f.path)}: cited lines that do not exist: ${bad.join(", ")}`);
    for (const s of sections(f)) {
      if (!hits.some(n => n >= s.start && n <= s.end))
        notes.push(`- ${basename(f.path)}:${s.start}–${s.end} "${s.heading.length > 60 ? s.heading.slice(0, 57) + "..." : s.heading}"`);
    }
  }
  return notes.length ? `\n\nCoverage check (by code, not the model); sections, classes and methods no reference above falls in:\n${notes.join("\n")}` : "";
}
