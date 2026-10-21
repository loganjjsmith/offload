# Unity test-output filter

Write a TypeScript module `unity-tests.ts` (ES module, no dependencies, runnable by Node 24's built-in
type stripping, so use only erasable TypeScript: no enums, namespaces or parameter properties) exporting:

```ts
export function summariseUnityTests(text: string): string
```

`text` is the JSON a Unity test run returns, for example:

```json
{ "Summary": { "Total": 40, "Passed": 39, "Failed": 1, "Skipped": 0, "Inconclusive": 0 },
  "Results": [
    { "FullName": "SampleGame.Mechanics.Tests.ProjectileMathTests.Distance_NaN_ReadsAsZero",
      "Status": "Passed", "Duration": 0.0001, "Message": null, "StackTrace": null },
    { "FullName": "SampleGame.Mechanics.Tests.LauncherConfigTests.ComputeVelocity_MatchesTheFormula",
      "Status": "Failed", "Duration": 0.0137,
      "Message": "  Expected: 126.5f +/- 0.00999999978f\r\n  But was:  48.7025032f\r\n",
      "StackTrace": "at SampleGame.Mechanics.Tests.LauncherConfigTests.ComputeVelocity_MatchesTheFormula () [0x00053] in C:\\Users\\dev\\Projects\\SampleGame\\Assets\\Tests\\EditMode\\LauncherConfigTests.cs:92\r\n" }
  ],
  "Duration": 2.56, "Mode": "EditMode", "success": true }
```

Other fields may be present and are ignored. Return the lines below joined with `"\n"`, no trailing newline.

1. **First line**, from `Summary` and the top-level `Duration`:
   `"<Passed> of <Total> passed"`, then for each of Failed, Skipped and Inconclusive, in that order and
   only when it is not zero, `", <n> failed"`, `", <n> skipped"`, `", <n> inconclusive"`; then
   `" (<Duration> s)"` with Duration written with exactly one decimal place (2.56 becomes `2.6`, 3 becomes
   `3.0`). Example: `"39 of 40 passed, 1 failed (2.6 s)"`.
2. **Then, for each result whose `Status` is `"Failed"`, in input order:**
   - `"FAIL <name>"`, where name is the last two dot-separated parts of `FullName` (`"A.B.Class.Method"`
     becomes `"Class.Method"`); a FullName with no dot is used whole.
   - If `Message` is a non-empty string after trimming: `"  <message>"` (two spaces), with the message
     trimmed and every run of whitespace (spaces, tabs, CR, LF) replaced by one space. If the result is
     longer than 200 characters, keep the first 200 and append `"…"`.
   - If `StackTrace` contains a frame of the form `in <path>:<line>` (the path may contain spaces, a drive
     letter's colon, and `/` or `\` separators; the line is digits): `"  at <file>:<line>"` for the first
     such frame, where file is the path's last component.
3. **Failure handling:** if `text` is not valid JSON, or `Summary` is not an object, or `Results` is not an
   array, return `text` unchanged. A filter must never hide output it cannot read.
