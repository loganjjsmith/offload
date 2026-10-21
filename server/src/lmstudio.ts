import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { Config, Role } from "./config.ts";

const run = promisify(execFile);

/**
 * The only runtime-specific code: makes sure the role's model is the one LM Studio has loaded, with the
 * role's context length. One model at a time, because two of these models do not fit in 24 GB together.
 * The model is loaded with an idle time-to-live, so LM Studio frees the GPU itself once calls stop.
 */
export async function ensureLoaded(cfg: Config, r: Role): Promise<void> {
  if (cfg.runtime !== "lmstudio") return;
  const { stdout } = await run(cfg.lmsCli, ["ps", "--json"], { windowsHide: true });
  const loaded = JSON.parse(stdout || "[]") as { identifier: string; contextLength: number }[];
  if (loaded.length === 1 && loaded[0].identifier === r.model && loaded[0].contextLength >= r.contextLength) return;
  await run(cfg.lmsCli, ["unload", "--all"], { windowsHide: true }).catch(() => undefined);
  await run(cfg.lmsCli, ["load", r.model, "--gpu", "max", "--context-length", String(r.contextLength),
    "--parallel", "1", "--identifier", r.model, "--ttl", String(cfg.idleUnloadSeconds), "--yes"],
    { windowsHide: true, timeout: 300_000 });
}
