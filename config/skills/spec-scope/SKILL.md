---
name: spec-scope
description: OMC quality gate that checks the reviewed plan against the approved spec both ways, every spec item planned and nothing planned outside the spec or under its Non-Goals, and reports out-of-spec work as scope findings rather than defects. Runs as an advisory gate at omc-review, which reviews plans; read-only. Not for code changes (use /code-review) or for checking a spec's test plan (use spec-test-plan).
---

# Spec scope gate

An **advisory** gate at OMC's `omc-review` stage. It is read-only: read the reviewed plan and the approved spec, change no file, and run nothing that writes.

## Check

1. Find the approved spec: the issue or ticket body, or the spec file the review names. With no approved spec, say so and return `VERDICT: PASS` with that one finding.
2. Every item: every spec item planned, each acceptance criterion and named change with a step in the plan.
3. Nothing extra: each step in the plan traces to a spec item, and none plans anything under the spec's Non-Goals.
4. Report work outside the approved spec or under its Non-Goals as `scope:` findings, not as defects.
5. Ask for an abstraction only when it makes the code easier to read or to maintain than the code without it.

## Verdict

List each finding on its own line: `missing:` for a spec item the plan leaves out, `scope:` for planned work outside the spec or under its Non-Goals, naming the plan step and the spec line. End with one line, `VERDICT: PASS` when there is no finding, else `VERDICT: BLOCK`.
