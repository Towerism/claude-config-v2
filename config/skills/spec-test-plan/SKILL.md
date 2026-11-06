---
name: spec-test-plan
description: OMC quality gate that checks a crystallized spec or plan draft for a test plan before it is handed off. It returns VERDICT BLOCK when a spec that changes code has no seam list, when a seam line lacks what it catches or what it misses, or when a spec that changes no code lacks a skipped test plan with a reason. Runs as a blocking gate at deep-interview and ralplan; read-only. Not for writing the seam list (the test-engineer agent does that).
---

# Spec test plan gate

A **blocking** gate at OMC's `deep-interview` and `ralplan` stages. It is read-only: read the spec or plan snapshot the stage hands you, change no file, and run nothing.

## Check

1. Decide whether the spec changes code: any source, test, script, hook or config that runs.
2. Find its `## Test plan` section, which runs to the next `## ` heading.
3. If the spec changes code, the section needs at least one seam line of the form `seam: <seam> | catches: <what it catches> | misses: <what it lets through>`, each part non-empty. Every seam line must have both `catches:` and `misses:`.
4. If the spec changes no code, it needs `test plan: skipped: <reason>` with a real reason (not empty, not the literal `<reason>`): inside the section, or, for a spec with no `## Test plan` section, anywhere in the spec (the pipeline list, for example).

## Verdict

End with one line, `VERDICT: PASS` or `VERDICT: BLOCK`. Before a `VERDICT: BLOCK`, list each finding on its own line: the missing section, the seam line and the part it lacks, or the skipped line without a reason. Do not write the missing seams yourself; the stage revises the spec.
