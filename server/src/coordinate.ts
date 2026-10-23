/**
 * Runs the loop coordinator on one task folder (docs/COORDINATOR.md):
 *   node server/src/coordinate.ts <task folder>
 * Prints the status and where result.md is; exits 0 when the change is cloud-ready, 1 when a guard stopped it.
 */
import { resolve } from "node:path";
import { loadConfig } from "./config.ts";
import { coordinate } from "./coordinator/loop.ts";

const dir = process.argv[2];
if (!dir) {
  console.error("usage: node server/src/coordinate.ts <task folder>");
  process.exit(2);
}
const result = await coordinate(loadConfig(), resolve(dir));
console.log(`${result.status}${result.reason ? ` (${result.reason})` : ""}: ${result.rounds.length} round(s), ` +
  `${result.reviews.length} review(s), ${result.minutes.toFixed(1)} min. See ${resolve(dir, "result.md")}`);
process.exit(result.status === "cloud-ready" ? 0 : 1);
