# ADR-0018: Triggered reference files for situational rules, and human-prose-writer for text people read

**Status:** Accepted 2026-11-25, issue #97. Amends ADR-0011 (decision 2, the dependency-research principle) and ADR-0016 (decisions 1 and 7).

## Context

A triage of the global memory store found many rules that matter at only one moment of use: running a spike or a headless `claude -p` run, briefing a subagent, reviewing or merging a PR, working on a skill, writing a shell command that can fail silently. As memories, they load only when their one-line description happens to match the task, and the session index cuts the store at a character budget, so eleven memories were not loading at all. As lines in `config/CLAUDE.global.md`, they would cost context in every session.

The owner ruled that situational memories go into reference files that the guardrails trigger at the right moment, that the same routing "includes any rules that are already in the CLAUDE.md", and, for writing: "agent-doc-discipline for specs, the same as plans and any other agent docs. ticket-specs no longer exist, so that one vanishes. ticket and issue bodies get written with human-prose-writer."

The `human-prose-writer` skill loaded only when asked for by name, and the only always-on rule that loaded it was a memory.

## Decision

1. **The guardrails end with a "Reference files" table.** Each row names a moment of use and the file to read then. The files live in the private global memory store under `refs/` (ADR-0015), outside the public repo, because they quote incidents from the owner's work. The memory index lists only top-level files, so the reference files cost nothing until read. The table says what to do when a file is missing, because the store syncs only where `memory.repo` is set.
2. **A row names every situation its file applies to,** including the action before a silent failure ("before writing a recursive grep"), since a symptom never fires for a false zero count or a mangled token.
3. **Approval gates and rules that fire mid-task with no moment a row could name stay always-loaded.** "Least own code wins", naming each new dependency in the spec, and merging only the approved head stay in the guardrails.
4. **The dependency-research principle moves to a reference file** (amends ADR-0011 decision 2). Its row fires on researching, proposing or picking a dependency; a dependency found mid-build reaches it through the spec, which the always-loaded naming rule sends back for approval.
5. **`human-prose-writer` loads before any text people read is drafted, edited or reviewed,** issue and ticket bodies, release notes and changelogs included, and its whole loop runs; for issue and ticket bodies it replaces `agent-doc-discipline` (amends ADR-0016 decisions 1 and 7). The edit pass still runs on the result. Specs follow `agent-doc-discipline`, as plans do.

## Consequences

- The guardrails grow by the table, and every session pays for it. The rules it routes leave the memory index, which frees index budget for the memories that stay.
- A machine without the private store loses the rules the table routes, and the table tells the session to say so and ask before a heavy run.
- ADR-0016's measurement that writing-time voice rules did not pay off was taken without a ticket-writing skill loaded by default; whether this change pays off is untested.
