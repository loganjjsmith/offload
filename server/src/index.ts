import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { loadConfig } from "./config.ts";
import { stats } from "./log.ts";
import { askLocal, extractRows, summarizeFiles } from "./tools.ts";
import { GRADES, gradeHandoff, gradeReport } from "./tripwire.ts";

const cfg = loadConfig();
const server = new McpServer({ name: "offload", version: "0.1.0" });

const mode = z.enum(["fast", "careful"]).optional()
  .describe('"fast" (default): thinking off, seconds. "careful": thinking on, minutes; for answers that must be exact.');

const text = (t: string) => ({ content: [{ type: "text" as const, text: t }] });
const failure = (err: unknown) => ({ content: [{ type: "text" as const, text: String(err) }], isError: true });

server.registerTool("summarize_files", {
  title: "Summarise files locally",
  description: "Reads files on this machine with a local model and returns a terse summary with file:line " +
    "references, followed by a check made by code that names the Markdown sections, classes and methods no " +
    "reference covers. " +
    "The file contents never enter your context. Use instead of reading files whose details you " +
    "only need in outline; read the lines you will edit yourself.",
  inputSchema: z.strictObject({
    paths: z.array(z.string()).min(1).describe("Absolute file paths, directories, or glob patterns"),
    focus: z.string().optional().describe("What the summary should concentrate on"),
    mode,
  }),
}, async args => { try { return text(await summarizeFiles(cfg, args)); } catch (err) { return failure(err); } });

server.registerTool("extract", {
  title: "Extract rows locally",
  description: "Lists every item of one kind in files on this machine (issues, TODOs, settings, test cases...) " +
    "as tab-separated rows of values copied from the files, each with its file:line. Code checks every value " +
    "against the file and drops rows that do not match, saying why. Do the counting, sorting or comparing " +
    "on the rows yourself: the local model only copies. The file contents never enter your context.",
  inputSchema: z.strictObject({
    paths: z.array(z.string()).min(1).describe("Absolute file paths, directories, or glob patterns"),
    item: z.string().min(1).describe('What one row is, for example "issue" or "TODO comment"'),
    fields: z.record(z.string().regex(/^\w+$/).refine(k => k !== "file" && k !== "line", "file and line are added anyway"),
      z.string()).refine(f => Object.keys(f).length > 0, "at least one field")
      .describe('Field name to what it holds, for example {"status": "the issue status", "owner": "who it is assigned to"}'),
    mode,
  }),
}, async args => { try { return text(await extractRows(cfg, args)); } catch (err) { return failure(err); } });

server.registerTool("ask_local", {
  title: "Ask the local model",
  description: "Sends a self-contained prompt to a local model and returns its answer, for drafting and " +
    "routine work that does not need the cloud model. Verify anything that matters.",
  inputSchema: z.strictObject({ prompt: z.string().min(1), mode }),
}, async args => { try { return text(await askLocal(cfg, args)); } catch (err) { return failure(err); } });

server.registerTool("grade_handoff", {
  title: "Grade a handoff",
  description: "Grades one answer from summarize_files, extract or ask_local, by the call id at its end, once you have used it: " +
    '"used" (as it was), "fixed" (small corrections), "redone" (thrown away and done again) or "misleading" ' +
    "(wrong in a way that cost extra work). Grade every handoff; it costs a few tokens. A flow (tool, mode " +
    "and model) whose answers keep being redone, or that misleads once about code, is switched off, and its " +
    "calls then tell you to do the job directly.",
  inputSchema: z.strictObject({
    callId: z.string().regex(/^[0-9a-f]{6}$/).describe("The id from the answer's last line"),
    grade: z.enum(GRADES),
    note: z.string().max(500).optional().describe("What was wrong, in a few words; shown with the flow's bad examples"),
  }),
}, async args => { try { return text(await gradeHandoff(cfg, args)); } catch (err) { return failure(err); } });

server.registerTool("offload_stats", {
  title: "Delegation statistics",
  description: "Totals from the delegation log (calls, characters read locally, characters returned, model " +
    "time), the grades per flow, and any flow the tripwire has switched off with its bad examples.",
  inputSchema: {},
}, async () => text(`${await stats(cfg.logFile)}\n\n${await gradeReport(cfg)}`));

await server.connect(new StdioServerTransport());
