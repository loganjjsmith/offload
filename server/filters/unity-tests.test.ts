import { test } from "node:test";
import assert from "node:assert/strict";
import { summariseUnityTests } from "./unity-tests.ts";

const run = (summary: object, results: object[], duration: number = 2.56, extra: object = {}) =>
  JSON.stringify({ Summary: summary, Results: results, Duration: duration, Mode: "EditMode", ...extra });

const counts = (total: number, passed: number, failed = 0, skipped = 0, inconclusive = 0) =>
  ({ Total: total, Passed: passed, Failed: failed, Skipped: skipped, Inconclusive: inconclusive });

const passed = (name: string) => ({ FullName: name, Status: "Passed", Duration: 0.01, Message: null, StackTrace: null });

const failed = (name: string, message: string | null, stack: string | null) =>
  ({ FullName: name, Status: "Failed", Duration: 0.01, Message: message, StackTrace: stack });

const REAL_STACK = "at SampleGame.Mechanics.Tests.LauncherConfigTests.ComputeVelocity_MatchesTheFormula () " +
  "[0x00053] in C:\\Users\\dev\\Projects\\SampleGame\\Assets\\Tests\\EditMode\\LauncherConfigTests.cs:92\r\n";

test("all passing is one line", () => {
  assert.equal(summariseUnityTests(run(counts(40, 40), [passed("A.B.C.D")])), "40 of 40 passed (2.6 s)");
});

test("duration always has one decimal", () => {
  assert.equal(summariseUnityTests(run(counts(1, 1), [passed("X.Y")], 3)), "1 of 1 passed (3.0 s)");
  assert.equal(summariseUnityTests(run(counts(1, 1), [passed("X.Y")], 0.04)), "1 of 1 passed (0.0 s)");
});

test("real failure: name, collapsed message, file and line", () => {
  const out = summariseUnityTests(run(counts(40, 39, 1), [
    passed("SampleGame.Mechanics.Tests.ProjectileMathTests.Distance_NaN_ReadsAsZero"),
    failed("SampleGame.Mechanics.Tests.LauncherConfigTests.ComputeVelocity_MatchesTheFormula",
      "  Expected: 126.5f +/- 0.00999999978f\r\n  But was:  48.7025032f\r\n", REAL_STACK),
  ]));
  assert.equal(out, [
    "39 of 40 passed, 1 failed (2.6 s)",
    "FAIL LauncherConfigTests.ComputeVelocity_MatchesTheFormula",
    "  Expected: 126.5f +/- 0.00999999978f But was: 48.7025032f",
    "  at LauncherConfigTests.cs:92",
  ].join("\n"));
});

test("skipped and inconclusive counts appear only when non-zero, in order", () => {
  assert.equal(summariseUnityTests(run(counts(10, 7, 0, 2, 1), [])), "7 of 10 passed, 2 skipped, 1 inconclusive (2.6 s)");
  assert.equal(summariseUnityTests(run(counts(10, 8, 1, 1, 0), [failed("P.Q", null, null)])),
    "8 of 10 passed, 1 failed, 1 skipped (2.6 s)\nFAIL P.Q");
});

test("null, empty and whitespace-only messages are omitted; no stack frame omits the at line", () => {
  const out = summariseUnityTests(run(counts(3, 0, 3), [
    failed("N.A.T1", null, null),
    failed("N.A.T2", "", "no frames here"),
    failed("N.A.T3", "  \r\n\t ", null),
  ]));
  assert.equal(out, "0 of 3 passed, 3 failed (2.6 s)\nFAIL A.T1\nFAIL A.T2\nFAIL A.T3");
});

test("long messages are cut to 200 characters plus an ellipsis", () => {
  const out = summariseUnityTests(run(counts(1, 0, 1), [failed("A.B", "x".repeat(250), null)]));
  assert.equal(out.split("\n")[2], "  " + "x".repeat(200) + "…");
  const exact = summariseUnityTests(run(counts(1, 0, 1), [failed("A.B", "y".repeat(200), null)]));
  assert.equal(exact.split("\n")[2], "  " + "y".repeat(200));
});

test("names with one dot or none are handled", () => {
  const out = summariseUnityTests(run(counts(2, 0, 2), [failed("Solo", null, null), failed("Class.Method", null, null)]));
  assert.equal(out, "0 of 2 passed, 2 failed (2.6 s)\nFAIL Solo\nFAIL Class.Method");
});

test("first matching frame wins; forward slashes work", () => {
  const stack = "at Foo () [0x0] in /home/u/proj/Assets/Foo.cs:12\nat Bar () [0x0] in /home/u/proj/Assets/Bar.cs:34";
  const out = summariseUnityTests(run(counts(1, 0, 1), [failed("A.B", "boom", stack)]));
  assert.equal(out.split("\n")[3], "  at Foo.cs:12");
});

test("a frame followed by trailing spaces still gives its file and line", () => {
  const out = summariseUnityTests(run(counts(1, 0, 1), [failed("A.B", null, "at Method () [0x0] in C:\\Test.cs:92  \r\n")], 0.1));
  assert.equal(out, "0 of 1 passed, 1 failed (0.1 s)\nFAIL A.B\n  at Test.cs:92");
});

test("a last frame with trailing spaces and no newline still gives its file and line", () => {
  const out = summariseUnityTests(run(counts(1, 0, 1), [failed("A.B", null, "at M () in D:\\x\\Last.cs:7   ")], 0.1));
  assert.equal(out, "0 of 1 passed, 1 failed (0.1 s)\nFAIL A.B\n  at Last.cs:7");
});

test("only Failed results are listed, in input order", () => {
  const out = summariseUnityTests(run(counts(4, 2, 2), [
    failed("M.First", "one", null), passed("M.Ok"), failed("M.Second", "two", null),
    { FullName: "M.Skip", Status: "Skipped", Duration: 0, Message: "ignored", StackTrace: null },
  ]));
  assert.equal(out, "2 of 4 passed, 2 failed (2.6 s)\nFAIL M.First\n  one\nFAIL M.Second\n  two");
});

test("unreadable input is returned unchanged", () => {
  for (const bad of ["not json", "{\"Results\": []}", "{\"Summary\": {}, \"Results\": {}}", "[]", "null"]) {
    assert.equal(summariseUnityTests(bad), bad);
  }
});
