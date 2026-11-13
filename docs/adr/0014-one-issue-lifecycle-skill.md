# ADR-0014: One issue-lifecycle skill that pairs work to an issue and closes it

**Status:** Accepted by the owner on 2026-11-12 (no issue: the owner waived the lifecycle for this change). Supersedes ADR-0006 decisions 3-5 and its "Sentences left to others" table. Amends ADR-0001, ADR-0003, ADR-0010, ADR-0011, ADR-0012 and ADR-0013.

## Context

Three lifecycle skills (`github-issue-lifecycle`, `gitea-issue-lifecycle`, `jira-ticket-lifecycle`) ran the tracker side of every code change: claim, a spec stored in the issue body between markers, `spec-check`, `draft`, `approved` and `in progress` labels, the user's approval posted on the issue, branch and worktree, a PR template with `pr-body-check`, a merge gate, cleanup and hotfixes. Each carried a stdlib script and its tests.

The owner on the three skills: "They are too complicated. The only thing they have to do is pair work to a ticket ... close the ticket when the work is done".

The owner approved the plan with changes: "keep sprint add. you figure how to spot check the gh, tea, and jira commands, or write tests for them if possible. Make sure that skills are written in a way (without any extra complexity or wordiness to accomplish this) that it stays out of OMC's way in other words the skills should not enforce the lifecycle proactively, but they are instead reactive (if that makes sense, or you may see a way that makes more sense to accomplish this)".

## Decision

1. **One markdown-only skill, `config/skills/issue-lifecycle/`**, for GitHub (`gh`), Gitea (`tea api`) and Jira (`jira-cli`), each tracker's commands in its own reference file. It ships no script.
2. **It reacts to events; each event is one tracker update:**
   - work starts: find the issue (key given, else search open then all, else create one), assign it to yourself; Jira also moves it to `states.inProgress` and, when `addToActiveSprint` is true, adds it to the active sprint;
   - the user asks only to file an issue: create it and stop;
   - what is built, or why, changes: rewrite the description, which stays the stakeholders' source of truth for what was built and why;
   - a decision a human would find surprising: one comment per decision;
   - a PR opens: GitHub and Gitea put `Closes #N` in the PR body; Jira moves the ticket to `states.review`;
   - the PR merges: GitHub and Gitea check the issue closed and close it by hand if not; Jira moves the ticket to `states.done`.
3. **It asks the user one thing:** whether to take an issue assigned to someone else.
4. **It never gates, approves or steers the running workflow.** OMC, or the user, decides what happens next. The global rules load it when a code change starts and at each event it lists.
5. **Approval is recorded only in the chat**, by quoting the user's words. Nothing is written to the issue for it, and no label exists for it.
6. **Cut:** the three scripts and their tests; spec markers, `spec-check`, `diff-check`, `pr-body-check`; the `draft`, `approved`, `in progress` and `hotfix` labels; approval recording on the issue; branch and worktree, the PR template, the merge gate, cleanup and hotfixes; `git-workflow.md`, the examples, Jira REST calls, attachments and spec sync; the reopen guard; "never squash". Why: the owner's words above; the work around the tracker belongs to OMC's workflow.

The commands were checked against `gh`, `tea` and `jira-cli` 1.7.0 `--help` output and read-only calls; no write call ran against a real tracker.

## Alternatives rejected

- **Keep the scripts and trim them.** The owner asked for the lifecycle to do only pairing and closing; a script would keep a second implementation to maintain.
- **Drop the Jira sprint add.** The owner kept it.

## Consequences

- "Never squash" and the reopen guard are stated nowhere, by the owner's choice.
- The seam list is enforced only by the `spec-test-plan` gate at `deep-interview` and `ralplan`; a spec written outside those stages is unchecked.
- Specs are no longer stored in the issue body; the description states what was built and why, not the plan text.
- The sentences ADR-0006's "Sentences left to others" table placed in the lifecycle skills (silence or a "go ahead" is not approval, a changed spec returns to draft, `/verify` never stands in for the user's word, a declined merge waits) are stated nowhere. The guardrails' fixed core still says that only the user's explicit, quoted words approve and that the user merges.
- The global rules' approved-label clause went with the label; no cut check was needed because the rule had nothing left to apply to.
- `tests/test_repo.py` keeps the skill markdown-only. The skill's wording and the tracker commands are checked by reading in review.
