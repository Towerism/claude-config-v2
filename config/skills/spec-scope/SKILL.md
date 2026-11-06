---
name: spec-scope
description: OMC quality gate that checks the reviewed changes against the approved spec both ways, every spec item built and nothing built outside the spec or under its Non-Goals, and reports out-of-spec work as scope findings rather than defects. Runs as an advisory gate at omc-review, the stage for diff gates; read-only. Not for finding bugs or style issues (the review lanes do that) or for checking a spec's test plan (use spec-test-plan).
---

# Spec scope gate

An **advisory** gate at OMC's `omc-review` stage, the stage for diff gates (`deep-interview` and `ralplan` are for planning gates). It is read-only: read the reviewed changes and the approved spec, change no file, and run nothing that writes.

## Check

1. Find the approved spec: the issue or ticket body, or the spec file the review names. With no approved spec, say so and return `VERDICT: PASS` with that one note.
2. Every item: every spec item built, each acceptance criterion and named change present in the changes.
3. Nothing extra: each change traces to a spec item, and none builds anything under the spec's Non-Goals.
4. Report work outside the approved spec or under its Non-Goals as `scope:` findings, not as defects.
5. Ask for an abstraction only when it makes the code easier to read or to maintain than the code without it.

## Verdict

List each finding on its own line: `missing:` for a spec item not built, `scope:` for work outside the spec or under its Non-Goals, naming the file and the spec line. End with one line: `VERDICT: PASS` when there is no `missing:` or `scope:` finding, else `VERDICT: BLOCK`.
