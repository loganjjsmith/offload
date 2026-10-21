export function summariseUnityTests(text: string): string {
  let data: any;
  try {
    data = JSON.parse(text);
  } catch (e) {
    return text;
  }

  if (
    !data ||
    typeof data !== "object" ||
    Array.isArray(data) ||
    typeof data.Summary !== "object" ||
    data.Summary === null ||
    !Array.isArray(data.Results)
  ) {
    return text;
  }

  const { Summary, Results, Duration } = data;

  // 1. Build first line: "<Passed> of <Total> passed[, <n> failed][, <n> skipped][, <n> inconclusive] (<Duration> s)"
  let summaryLine = `${Summary.Passed} of ${Summary.Total} passed`;
  if (Summary.Failed > 0) summaryLine += `, ${Summary.Failed} failed`;
  if (Summary.Skipped > 0) summaryLine += `, ${Summary.Skipped} skipped`;
  if (Summary.Inconclusive > 0) summaryLine += `, ${Summary.Inconclusive} inconclusive`;

  summaryLine += ` (${Number(Duration).toFixed(1)} s)`;

  const lines: string[] = [summaryLine];

  // 2. Process Failures
  for (const result of Results) {
    if (result.Status === "Failed") {
      // FAIL <name>: last two dot-separated parts or whole if no dots
      const fullName = typeof result.FullName === "string" ? result.FullName : "";
      const nameParts = fullName.split(".");
      const name = nameParts.length > 1 ? nameParts.slice(-2).join(".") : fullName;
      lines.push(`FAIL ${name}`);

      // Message: trim, replace whitespace runs with one space, truncate at 200 + ellipsis
      let msg = typeof result.Message === "string" ? result.Message.trim() : "";
      if (msg) {
        msg = msg.replace(/\s+/g, " ");
        if (msg.length > 200) {
          msg = msg.substring(0, 200) + "…";
        }
        lines.push(`  ${msg}`);
      }

      // StackTrace: Find first frame of form "in <path>:<line>"
      const stack = typeof result.StackTrace === "string" ? result.StackTrace : "";
      if (stack) {
        // "in <path>:<line>": the path may hold a drive letter's colon, so the line is the first run of
        // digits after a colon that is followed by whitespace or the end of the text.
        const frameRegex = /in\s+(.+?):(\d+)(?=\s|$)/;
        const match = stack.match(frameRegex);
        if (match) {
          const filePath = match[1].trim();
          const lineNum = match[2];
          // Extract filename from path using both / and \ as separators
          const fileParts = filePath.split(/[\\/]/);
          const fileName = fileParts[fileParts.length - 1] || "";
          lines.push(`  at ${fileName}:${lineNum}`);
        }
      }
    }
  }

  return lines.join("\n");
}
