---
documentLanguage: en
---

# Glossary

One entry per term: definition, boundaries, one resolved ambiguity. Write here the moment a term is settled. Vocabulary here is law for specs, tickets and code naming. Ship-specific terms only: a concept any sea chart carries does not get an entry.

## Advisory step
- Definition: a workflow step tagged `(advisory: <id>)` in `config/CLAUDE.global.md`, which only the user can waive (ADR-0005).
- Boundary: an untagged step is required and is never waived; only the conditional advisory steps may be `n/a`.

## Guardrails
- Definition: the rules in `config/CLAUDE.global.md` that add conditions and checks on top of OMC's workflow (ADR-0001, ADR-0004).
- Boundary: adds routing and checks; is not a replacement for any OMC stage or skill.
- Avoid: "pipeline" (V1's own pipeline was dropped; OMC owns the workflow).
- Resolved ambiguity: ADR-0004 adds routing rules on top of OMC, a stated departure from "add only gaps" in ADR-0001.

## Host profile
- Definition: `hosts/<name>.json`, naming the skills, hooks, plugins, marketplaces and `defaultTracker` one machine gets (ADR-0002).
- Boundary: is the only per-machine file in the repo; machine-only values (Jira project and site) live outside it, in `~/.config/claude-config/local.json`.
- Avoid: "environment", "config set".
- Resolved ambiguity: profiles differ only in `name` and `defaultTracker`; a test fails otherwise.

## Path declaration
- Definition: the one issue comment (ticket comment in Jira) between `<!-- path-declaration v1 -->` markers (`path-declaration:start` and `path-declaration:end` lines in Jira, which strips HTML comments) that marks each step of the change `run`, `waived` or `n/a` (ADR-0005).
- Boundary: `declaration-check` validates it at approval and at PR time; it records the path and does not prove a step ran.

## Pathway
- Definition: the stated condition under which a guardrail routes work to an OMC agent (ADR-0004).
- Boundary: every one of the 19 pinned OMC agents has a pathway; an agent appearing only in a roster is not one.
- Avoid: "mention", "roster entry".
- Resolved ambiguity: "tracer" the agent is not "tracer bullet" in TDD.

## Stamp
- Definition: the `path-declaration-ok` file a passing `declaration-check --stamp` writes into the work tree's git dir, holding the branch, issue and HEAD (ADR-0005).
- Boundary: `bash_guard.py` asks on `gh pr create` or `gh pr new` unless the stamp matches the current branch and HEAD; a new commit makes it stale.

## Waiver
- Definition: the user's own words, quoted in a `waived` line, that skip an advisory step; the cited comment starts with `Path declaration answer` (ADR-0005).
- Boundary: covers one issue and one advisory step; a required step cannot be waived.
