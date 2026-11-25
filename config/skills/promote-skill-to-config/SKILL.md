---
name: promote-skill-to-config
description: Adds a skill to the claude-config-v2 repo as a standard skill, so it syncs to every machine and can be invoked by name. The source is an OMC learned skill (a file in ~/.claude/skills/omc-learned/ or in the global memory store's skills/ directory) or a skill drafted with OMC's skillify. Use when the user asks to move, port or promote a learned skill into claude-config-v2, to skillify a workflow into that repo, or to make a skill available on every machine. Not for a skill that belongs in one project's .omc/skills, or for editing a skill the repo already ships.
---

# Promote a skill to claude-config-v2

claude-config-v2 deploys each `config/skills/<name>/` that a host profile lists into `~/.claude/skills/` on that machine, where it can be invoked as `/<name>`. An OMC learned skill exists on one machine only and loads only when its triggers match. The repo's general steps for adding a skill are in its README ("Add a second machine, a skill or a hook") and its rules are in its CLAUDE.md. This skill adds what those leave out: converting the source, the checks that prove the move, and removing the old copy.

## Inputs

- The source. Either a learned skill at `${CLAUDE_CONFIG_DIR:-~/.claude}/skills/omc-learned/<name>.md` or in the global memory store's `skills/` directory (`$XDG_DATA_HOME/claude-memory/skills/`, reachable as `~/.omc/skills/`; ADR-0015), or a skill drafted in this session. For a skillify run, draft the skill by skillify's own workflow first, then start at step 1 here with the draft in place of a learned file. If skillify saved the draft to a file, note where; step 9 removes it.
- The user's checkout of claude-config-v2. If its path is not known from the session, ask for it.

## Steps

1. **Check the source is safe to publish.** Read the source and the repo's CLAUDE.md. Look for machine paths, account names, tokens, and employer or client names. Done when the source has none, or the user has approved a generalised wording for each one found. Why: the repo is public and deploys itself to every machine, and its test only catches absolute paths into a home directory, never names.

2. **Pair the work and isolate it.** Pair the work with a GitHub issue in the repo by following the installed issue-lifecycle skill with its GitHub commands, run from the checkout (or with `gh -R <owner>/<repo>`). Use GitHub even when the session's default tracker is something else. Then create a git worktree at `.claude/worktrees/<n>-<slug>` on a new branch `feature/<n>-<slug>` from `origin/main`. Done when the issue is assigned to the user and the worktree is checked out. Why: the repo tracks its work in GitHub issues, but issue-lifecycle follows the session's default tracker and `gh` targets the current directory's repo, so either can file the issue in the wrong place. The repo also forbids commits to `main`.

3. **Red: add the skill folder.** Write the source to `config/skills/<name>/SKILL.md` and run `make test`. Done when `test_every_skill_is_on_some_host_and_every_hook_is_wired` fails on the new skill. `test_skill_is_well_formed` may also fail on it until step 4. Why: that failure proves the test guards the host listing before you add it.

4. **Convert the front matter.** Keep `name`, which must equal the folder name, and `description`, which must be 51 to 1024 characters on one line, with no `: ` inside unless the whole value is quoted. Delete OMC's `triggers:` list and fold its phrases into the description as a "Use when …" clause, plus a "Not for …" clause. Leave the body as it is, unless step 1 found something. Done when the front matter holds only `name` and `description`. Why: a standard skill loads by its description, and only OMC's learned-skill injector reads `triggers:`. A `: ` in an unquoted value is invalid YAML, which Claude Code fails to load, and the repo's test parser does not catch it.

5. **Green: list it and describe it.** Add the name to `skills` in both `hosts/personal.json` and `hosts/work.json`, at the same position. Add the skill to the README's `config/skills/` row, and fix any README sentence the new skill makes untrue. Run `make test` and `make lint`. Done when both pass and you have quoted the test count. Why: a test requires the two profiles to differ only in `name` and `defaultTracker`.

6. **Dry-run the deploy.** Run `python3 -I tools/cfg.py plan --host work --target "$(mktemp -d)"`. Done when a plan line under `add` ends with `skills/<name>/SKILL.md`. Why: it proves `cfg.py` picks up the folder and every file in it, which the tests do not run.

7. **Get an independent review.** Give a reviewer agent the diff and the repo's rules, without your own conclusions. Check each finding before acting on it. Done when every finding is applied or rejected with a reason. Why: a port keeps the source's body, so reject a body rewrite unless it removes something step 1 should have caught.

8. **Open the PR.** Commit with a Conventional Commits subject (`feat(skills): …`), push the branch, and open a draft PR (`gh pr create --draft`) whose body carries `Closes #<n>`. Done when the draft PR is open. Why: marking a PR ready and merging it are the user's decisions.

9. **After the merge, remove the old copy.** Run `git fetch origin`, then diff the source file's body against `origin/main:config/skills/<name>/SKILL.md`. Go on only if the only differences are the step 1 generalisations and the step 4 front matter; otherwise show the user the diff and stop. Delete the source file wherever it was saved (`omc-learned/`, the store's `skills/` or a project's `.omc/skills/`) with `command rm -f`, and remove the worktree and the local branch. Done when the source file is gone and the user knows when the skill installs: at the start of their next new session (auto sync), or right away with `git switch main && git pull && make deploy YES=1` in the checkout. Why: deleting the source must lose nothing the merged copy lacks, and while both copies exist, both load, one by trigger and one by description. A deploy from a feature branch is replaced at the next session start.

## Pitfalls

- EnterWorktree refuses a worktree when the session started outside a git repo. Work in the git worktree through shell commands with absolute paths instead.
- `rm` may be aliased to `rm -i`. The prompt never gets an answer and the file stays, so use `command rm`.
- Between deleting the learned file and the next deploy, no copy of the skill is installed.
- The repo's tests reject an absolute path into a home directory anywhere in a skill's files, even in prose about the rule itself. Write home paths as `~` or `${CLAUDE_CONFIG_DIR:-~/.claude}`.
- A skill must not read another skill's files (`../<other>/`), because a host may deploy any subset of skills. Naming another skill or an OMC agent in prose is fine.
