# Sample run: `extract` on a Unity script

A real call to the delegation server, recorded on 2026-10-21 and checked line by line. It is kept as a
sample; the server's call log itself is not committed.

**The job.** The cloud agent wants every tuning value in a 592-line C# script of a Unity game (the game's
sanitised public copy), without reading the file into its own context. It calls:

```json
{
  "tool": "extract",
  "paths": ["<game>/Assets/Scripts/Identity/WireRider.cs"],
  "item": "public float field or float constant declared in the class",
  "fields": { "name": "the field's name", "value": "its initial value as written, e.g. 4.4f" }
}
```

**What the server did.** It read the file itself (25,242 characters), numbered its lines, and sent it to
Gemma 4 26B A4B running in LM Studio with thinking off. The model replied with rows of copied values;
code then checked every value word for word on the cited line before keeping the row.

**What came back to the cloud agent** (745 characters, 48 seconds):

```
16 rows (model-made, every value checked against the file by code); 0 dropped.
where	name	value
WireRider.cs:33	ClimbLockAfterWireExit	0.15f
WireRider.cs:36	WireMoveSpeed	16f
WireRider.cs:37	WirePerchGrabRange	11f
WireRider.cs:38	WireAirGrabRange	4.4f
WireRider.cs:39	WireReentryLockDuration	1.25f
WireRider.cs:40	WireJumpOffSpeed	3f
WireRider.cs:41	WireJumpOffUpSpeed	10f
WireRider.cs:42	SlingshotWireLockDuration	1.75f
WireRider.cs:47	RideClearance	0f
WireRider.cs:51	PoleAttachRadius	1f
WireRider.cs:54	HaltPerchBodyLengths	1.5f
WireRider.cs:58	JunctionMinCameraDot	0.5f
WireRider.cs:62	JunctionClearMargin	0.2f
WireRider.cs:66	PerchMountMinCameraDot	0f
WireRider.cs:70	PerchJumpWireIgnoreSeconds	0.5f
WireRider.cs:75	RidingMovingAnimSpeed	8f

[call e40a91: grade it with grade_handoff once used]
```

**Checked.** A plain search of the file for `public float` and `public const float` declarations finds
the same 16 fields, with the same names, values and line numbers. The cloud agent graded the call
`used`, which feeds the tripwire for the flow "extract, fast, gemma-4-26b-a4b".

**Not every run is this clean.** On a Markdown document with 30 numbered steps, three runs after the
checker fixes kept 30, 25 and 29 rows; the missing rows were ones the code check caught and listed as
dropped, and no wrong row was kept (see `docs/BUILDING-WITH-AI.md`).
