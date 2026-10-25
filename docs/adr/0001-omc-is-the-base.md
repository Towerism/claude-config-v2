# ADR-0001: OMC is the base; this repo only fills gaps

**Status:** Accepted 2026-10-24 (autopilot run; veto by opening a new ADR).

## Context

V1 built a seven-stage pipeline from vendored skills, overlays that bend them, and hooks. OMC now ships the same stages (interview, plan, execute, TDD, review, verify, PR drafting) as maintained skills and agents.

## Decision

Follow OMC's workflow. Add only what OMC lacks, each with a reason in [the gap analysis](../gap-analysis.md): tracker lifecycle, the merge hook, approval and git guardrails, the rule that `test-engineer` plans the tests before the spec is written, a cold-reader rule for prose, session handoff, Linux triage, and the two-machine deploy.

## Consequences

- No vendored skills and no overlays; nothing to re-sync with an upstream.
- The global rules are a block in `CLAUDE.md`, not a replacement for it, so OMC's own block keeps working.
- Commit and push checks from V1 (`git_hooks.py`) are not ported. They would be plumbing under `tools/`, with `gitleaks` as the dependency, if wanted.
- OMC already touches trackers (`launch`, `harbor`, `drydock`, `project-session-manager`) but is GitHub-first and has no approval-mode or merge close-out. The lifecycle skills (`github-issue-lifecycle`, `gitea-issue-lifecycle`, `jira-ticket-lifecycle`) stay for Jira and Gitea and for those guardrails. Retire them if OMC covers all three trackers and the approval rules.
- Boundary: during `/launch`, its parent issue holds the spec and the lifecycle skill still owns claim, approval and merge (`CLAUDE.global.md`).
