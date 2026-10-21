import { glob, readFile, stat } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";

export type SourceFile = { path: string; text: string };

const norm = (p: string) => resolve(p).replace(/\\/g, "/").toLowerCase();

/** True when `path` is inside one of `roots` (compared case-insensitively, as Windows paths are). */
export function insideRoots(path: string, roots: string[]): boolean {
  const p = norm(path);
  return roots.some(root => {
    const rel = relative(norm(root), p);
    return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
  });
}

/**
 * Reads the given files, directories (every file below them) or glob patterns. Only paths inside the
 * configured read roots are allowed; anything else is refused rather than skipped, so a wrong path is
 * never mistaken for an empty one.
 */
export async function readSources(patterns: string[], roots: string[]): Promise<SourceFile[]> {
  const paths = new Set<string>();
  for (const pattern of patterns) {
    const isGlob = /[*?[\]{}]/.test(pattern);
    if (isGlob) {
      for await (const p of glob(pattern.replace(/\\/g, "/"))) paths.add(resolve(p));
    } else if ((await stat(pattern)).isDirectory()) {
      for await (const p of glob("**/*", { cwd: pattern })) paths.add(resolve(pattern, p));
    } else {
      paths.add(resolve(pattern));
    }
  }
  const out: SourceFile[] = [];
  for (const p of [...paths].sort()) {
    if (!insideRoots(p, roots)) throw new Error(`Refused: ${p} is outside the allowed folders`);
    if ((await stat(p)).isFile()) out.push({ path: p, text: await readFile(p, "utf8") });
  }
  if (out.length === 0) throw new Error(`No files matched: ${patterns.join(", ")}`);
  return out;
}

/** The file with line numbers, so the model can cite file:line. */
export function numbered(file: SourceFile): string {
  const lines = file.text.replace(/\r\n/g, "\n").split("\n");
  return `=== ${file.path} ===\n` + lines.map((l, i) => `${String(i + 1).padStart(4)}| ${l}`).join("\n");
}

/** The text of the Markdown headings a line sits under, nearest first, one per level; fenced code is skipped. */
export function headingsAbove(lines: string[], line: number): string[] {
  const byLevel: string[] = [];
  let fenced = false;
  for (const text of lines.slice(0, line - 1)) {
    if (/^\s*(```|~~~)/.test(text)) { fenced = !fenced; continue; }
    const h = !fenced && /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(text);
    if (h) { byLevel.length = h[1].length - 1; byLevel[h[1].length - 1] = h[2]; }
  }
  return byLevel.filter(Boolean).reverse();
}

/**
 * Groups numbered files into chunks of at most `limit` characters; a file bigger than that is split by lines,
 * and each later part names the headings its first line sits under.
 */
export function chunk(files: SourceFile[], limit: number): string[] {
  const pieces: string[] = [];
  for (const f of files) {
    const text = numbered(f);
    if (text.length <= limit) { pieces.push(text); continue; }
    const [header, ...lines] = text.split("\n");
    const raw = f.text.replace(/\r\n/g, "\n").split("\n");
    let part = header;
    for (const [i, line] of lines.entries()) {
      if (part.length + line.length + 1 > limit && part !== header) {
        pieces.push(part);
        const under = headingsAbove(raw, i + 1);
        part = header + " (continued" + (under.length ? `, under the headings: ${under.reverse().join(" > ")}` : "") + ")";
      }
      part += "\n" + line;
    }
    pieces.push(part);
  }
  const chunks: string[] = [];
  for (const piece of pieces) {
    const last = chunks.length - 1;
    if (last >= 0 && chunks[last].length + piece.length + 2 <= limit) chunks[last] += "\n\n" + piece;
    else chunks.push(piece);
  }
  return chunks;
}
