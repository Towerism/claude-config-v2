# ADR-0012: The guardrails are written for Anthropic models only

**Status:** Accepted by the owner on 2026-11-07, issue #60. Supersedes ADR-0009. Amends ADR-0011 where it amends ADR-0009 (scenarios 14-17 and the context-limit note retire with it).

## Context

ADR-0009 shaped `config/CLAUDE.global.md` so that small open-weight models could follow it: one rule per short bullet, conditions before actions, spelled-out referents, a worked example for every expected output, no model names, and tests that enforced that shape bullet by bullet. The owner reversed the premise: "the claude global.md doesn't need to support less intelligent models. it will only ever be read by anthropic models".

## Decision

1. **The block is written for Anthropic models.** It may name Anthropic models and Claude Code tools. ADR-0009's shape rules, its cited sources, its deployment notes and its scenarios 1-17 retire.
2. **The rewrite is free around a fixed core.** These stay:
   - The user holds three decisions: approving the spec in the user's quoted words, marking a PR ready, and merging.
   - The push and draft-PR grant keeps ADR-0008's phrase "explicit authorization for publishing and draft-PR creation" word for word, because OMC's `autopilot` and `ralph` wait for it.
   - Force-push only with `--force-with-lease`.
   - Never read, quote or commit `deny-terms`, tokens or `.env` contents.
   - A new rule: load `/oh-my-claudecode:agent-doc-discipline` before writing or updating a document agents consume.
3. **A rule outside the core leaves the block only when it is covered elsewhere.** A `tracer` agent and a `critic` agent must each agree that it is covered, and each must name the route from the model to the covering text with no broken edge. Per ADR-0011, OMC text counts as coverage only if its skill runs, and default model behaviour names no text, so it is no route.
4. **Tests are structural.** `tests/test_repo.py` keeps the line cap, the real-skill and lifecycle-skill checks, the no-cfg-marker, nothing-personal and restate-nothing checks, and one test that five exact anchors are present: the push-grant phrase, `--force-with-lease`, `deny-terms`, `.env` and `oh-my-claudecode:agent-doc-discipline`. The three user decisions are checked in review. The per-bullet shape tests and the per-rule phrase tests are gone.

## The cut check

Both agents read the block, OMC's block in `~/.claude/CLAUDE.md`, the hooks, the lifecycle skills and OMC's skills, independently.

- Neither found a rule covered outright. Both agree that rule depends on rule: the lifecycle skills load only through the lifecycle bullet, `tdd` and `minimal-code-discipline` only through the bullet that loads them, and the `scope:` and abstraction rules only through the review bullet.
- Both found one conditional case: "set the approved label only after the quote is posted" is stated by all three lifecycle skills, reached through the lifecycle bullet. The critic noted that skill text can be lost after compaction while the block survives, a broken edge, so it stays.
- The critic found that the quality gates (`spec-test-plan`, `spec-scope`) are not where OMC reads them after an auto-sync deploy, so every route through a gate is broken today. Filed as #61.

**Cut: none.** The rewrite merges related bullets (approval with its label, the tracker with the no-tracker case, the seam list with the no-code skip, the pipeline list with its acknowledgement, ready with merge) and keeps every rule's meaning; review compared each old rule with its new wording.

## Consequences

- Removing a rule from the block repeats the cut check, and its route goes in this ADR or a later one.
- With no shape tests, a weakened paraphrase of a rule is caught only in review. The anchor test catches only a lost anchor.
- A rule found redundant later can be cut once its route is fixed: for the gate-dependent rules, after #61.
