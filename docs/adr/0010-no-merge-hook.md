# ADR-0010: The merge hook is removed

**Status:** Accepted by the owner on 2026-11-06, issue #57. Amends ADR-0006 (decision 6: the hooks). Amended 2026-11-12 by ADR-0014: the lifecycle skills' step 8 is gone, so it states nothing for ADR-0006's merge rows, and "never squash" is stated nowhere.

## Context

`merge_confirm.py` was the last guard hook. ADR-0006 removed `bash_guard.py`, `skill_gate.py` and `secrets_guard.py` and kept it: a `PreToolUse(Bash)` hook that asked before every `gh pr merge`, `gh api …/merge` or `tea api …/merge` and gave its own reason for a squash merge.

The owner asked: "remove all guards. they interfere with some of OMC's workflows with little to no added benefit", then narrowed it: "the hooks are the only thing I mean".

## Decision

1. **`config/hooks/merge_confirm.py` is deleted**, with its `PreToolUse` entry in `config/settings.fragment.json` and its name in both host profiles. The fragment has no `PreToolUse` entry left. `cfg.py` deletes the deployed copy and its `settings.json` entry on the next deploy, as it does for any hook a profile stops listing.
2. **The guardrails block is unchanged.** "Merge only when the user says so" stays, as text.
3. **`host_default.py` and `auto_sync.py` stay.** Neither guards anything.

## Alternatives rejected

- **Remove the guardrails block too.** The owner limited the request to the hooks.

## Consequences

- No hook asks before a merge. "Merge only when the user says so" and "never squash" are text only: the guardrails block and step 8 of each lifecycle skill. Branch protection on the remote remains the control that holds.
- Rows in ADR-0006's tables that named `merge_confirm.py` keep step 8 of the lifecycle skills as their stater, so the block needs no new line.
- The lifecycle skills still describe the hook, and that text is now stale; the skills were out of scope for #57. The lines: the Prompts "Merge" line and step 8 of `github-issue-lifecycle` and `jira-ticket-lifecycle`, and the intro and step 8 of `gitea-issue-lifecycle`.
