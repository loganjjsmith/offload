import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type Role = { model: string; thinking: boolean; contextLength: number };

export type Config = {
  endpoint: string;
  runtime: "lmstudio" | "none";
  lmsCli: string;
  /** LM Studio unloads a model nobody has used for this long, so nothing stays on the GPU after a session ends. */
  idleUnloadSeconds: number;
  roles: Record<string, Role>;
  requestTimeoutSeconds: number;
  maxAnswerTokens: number;
  chunkChars: number;
  extractChunkChars: number;
  readRoots: string[];
  logFile: string;
  /** A flow switches off when its redone and misleading answers reach `maxBadShare` of its last `window` graded calls. */
  tripwire: { window: number; maxBadShare: number };
};

export const SERVER_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const readJson = (path: string) => JSON.parse(readFileSync(path, "utf8").replace(/^﻿/, ""));

/**
 * Loads server/config.json, or the file named by OFFLOAD_CONFIG. Next to it, an optional `config.local.json`
 * (not committed) overrides any top-level key, which is where this machine's folders go. Relative paths in
 * `readRoots` and `logFile` are taken from server/.
 */
export function loadConfig(path = process.env.OFFLOAD_CONFIG ?? resolve(SERVER_DIR, "config.json")): Config {
  const local = resolve(dirname(path), "config.local.json");
  const cfg = { ...readJson(path), ...(existsSync(local) ? readJson(local) : {}) } as Config;
  return {
    ...cfg,
    extractChunkChars: cfg.extractChunkChars ?? 12000,
    readRoots: cfg.readRoots.map(r => resolve(SERVER_DIR, r)),
    logFile: resolve(SERVER_DIR, cfg.logFile),
  };
}

export function role(cfg: Config, name: string): Role {
  const r = cfg.roles[name];
  if (!r) throw new Error(`Unknown mode "${name}". Known: ${Object.keys(cfg.roles).join(", ")}`);
  return r;
}
