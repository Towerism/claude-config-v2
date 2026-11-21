# claude-config v2

A small layer on top of [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (OMC) for one person's Claude Code setup. OMC provides the development workflow: interview, plan, execute, review, verify. This repo adds only who approves and who merges, issue-tracker skills, and a tool that installs the same setup on a personal machine and a work machine.

V1 (`claude-config`) built its own pipeline from 24 skills, overlays and three hooks. V2 drops that pipeline and keeps the parts OMC doesn't cover. [docs/gap-analysis.md](docs/gap-analysis.md) lists every V1 piece and what became of it.

## Design philosophies

1. **Two machines are one JSON file apart.** A host profile in `hosts/` selects skills, hooks and plugins. The personal and work profiles differ only in `name` and `defaultTracker` (a test enforces it).
2. **Skills have zero dependencies.** No third-party packages and nothing to install: a skill is markdown, plus standard-library Python under `scripts/` where determinism matters (no skill ships a script today), so a new machine needs only the tracker's CLI and `python3`. Each skill is self-contained. Plumbing (`tools/`, the hooks) may use whatever it needs to keep the repo lean; today it needs only Python 3.11+. See [ADR-0003](docs/adr/0003-skills-zero-dependency.md).

## What is here

| Path | What it holds |
|---|---|
| `config/CLAUDE.global.md` | The guardrails, written for Anthropic models only ([ADR-0012](docs/adr/0012-guardrails-for-anthropic-models-only.md)), deployed into `~/.claude/CLAUDE.md` as a marked block, normally after OMC's own. They state only what OMC, the skills and the hooks don't: the user approves every spec and every merge ([ADR-0006](docs/adr/0006-omc-leads-the-pipeline.md); no hook enforces the merge rule since [ADR-0010](docs/adr/0010-no-merge-hook.md)) and decides when a PR is marked ready ([ADR-0008](docs/adr/0008-omc-pushes-feature-branches.md)), and OMC may push its feature branch and open a draft PR in any mode ([ADR-0008](docs/adr/0008-omc-pushes-feature-branches.md)) |
| `config/skills/` | `issue-lifecycle` (markdown only: pairs the work to a GitHub, Gitea or Jira issue, keeps its description current and closes it, [ADR-0014](docs/adr/0014-one-issue-lifecycle-skill.md)), `fresh-session-handoff`, `linux-troubleshooting`, `architecture-backfill` (docs a repo's architecture and past decisions from code and history, each claim labeled verified or inferred), `human-prose` (rules and a review loop for prose people read, such as PR descriptions, tickets and design docs), `promote-skill-to-config` (moves an OMC learned skill or a skillify draft into this repo), and the OMC quality-gate skills `spec-test-plan` and `spec-scope` ([ADR-0011](docs/adr/0011-scope-dependencies-and-spec-time-test-plans.md)). The rules for replies and agent-read docs come from OMC's `minimal-prose-discipline` and `agent-doc-discipline` |
| `config/hooks/` | `host_default.py` (states the repo's tracker at session start, from its history, its `origin` and the host profile), `auto_sync.py` (deploys `main` from `origin` at the start of each new session, [ADR-0007](docs/adr/0007-auto-sync-at-session-start.md)) and `global_memory.py` (syncs general memories and learned skills through a private git repo; off until `memory.repo` is set, [ADR-0015](docs/adr/0015-global-memory-in-a-private-repo.md)) |
| `config/omc.fragment.json` | The `qualityGates` that `cfg.py` merges into OMC's user config: `spec-test-plan` blocks at `deep-interview` and `ralplan`, `spec-scope` advises at `omc-review` |
| `hosts/` | `personal.json`, `work.json` |
| `tools/cfg.py` | plan, deploy, status and rollback |
| `tests/` | repo invariants, hooks, `cfg.py` and the quality-gate skills |
| `docs/` | gap analysis and decision records |

## Set up a machine

1. Install OMC's plugin in Claude Code, or let the deploy enable it: `cfg.py` adds the `omc` marketplace and enables `oh-my-claudecode@omc` in `settings.json`. Then run `/omc-setup` once.
2. Preview, then apply:

   ```bash
   make plan HOST=personal            # or: work
   make deploy HOST=personal YES=1
   ```

   `make deploy` without `YES=1` only prints the plan. Later deploys remember the host, so `HOST` can be left out. `TARGET=DIR` (or `CLAUDE_CONFIG_DIR`) deploys somewhere else, such as a scratch directory. The same runs without make: `python3 -I tools/cfg.py plan --host personal`, then `... deploy --host personal --yes`.
3. After that, deploys also run automatically ([ADR-0007](docs/adr/0007-auto-sync-at-session-start.md)). The first `make deploy YES=1` clones `main` from this checkout's `origin` into `~/.local/share/claude-config` (`$XDG_DATA_HOME/claude-config`); offline, it warns and the next deploy tries again. At the start of each new session the `auto_sync.py` hook fetches `main` into that clone, fast-forwards it and deploys it with `--force`.
   - Files edited by hand in `~/.claude` are overwritten. They are backed up, but only the last five backups are kept. `make rollback` restores the last one, and like a hand edit it holds only until the next new session, unless auto sync is off.
   - A manual deploy from a feature branch is replaced by `main` at the next session start.
   - On success you see only a spinner. On failure the reason goes to `~/.claude/claude-config/sync.log`, `make status` shows it, and you see a one-line warning. Most failures leave the current config as it was; a deploy that fails midway is rolled back, and if that fails too the warning says to run `make rollback`.
   - A `diverged` warning (`main` on `origin` was rewritten, for example by a force-push) is repaired by running `make deploy YES=1` in a checkout: it resets the clone's `main` to `origin`'s.
   - The fetch runs git with a fixed `PATH` (`/usr/local/bin:/usr/bin:/bin`) and its own ssh command (`ssh -o BatchMode=yes`, which replaces a `core.sshCommand`). A setup that needs a custom ssh command, or a credential helper outside that `PATH`, gets `fetch-failed` every time.
   - To turn auto sync off on a machine, set `"autoSync": false` in `~/.config/claude-config/local.json`.
   - Anyone who can push to `main` changes every synced machine at its next session start, so protect `main` with branch protection.
4. `make status` lists files edited since the last deploy, changes still pending and the last failed sync. A deploy stops on an edited file until you pass `FORCE=1` (`--force`; the old copy is backed up). `make rollback` undoes the last deploy. A `HOST` or `TARGET` holding `'` or `$` needs the raw command. Only values typed after `make` count; exported variables are ignored.

Per-machine values that never enter the repo live in `~/.config/claude-config/local.json`: `autoSync` (above), `memory.repo` (see "Share memories between machines"), and the `jira` settings that tailor `issue-lifecycle` to your Jira project (see its `references/jira.md`). A top-level `defaultTracker` there is ignored; the host profile holds the default.

### Share memories between machines (optional)

[ADR-0015](docs/adr/0015-global-memory-in-a-private-repo.md) syncs memories that hold in any repo, and learned skills, through a private git repo. Per-project memory stays on its machine.

1. Create an empty private git repo that every machine can reach over ssh without a prompt (the hook runs git with `ssh -o BatchMode=yes`).
2. On each machine, put the repo's URL in `~/.config/claude-config/local.json`; the URL may differ per machine:

   ```json
   { "memory": { "repo": "<git URL>" } }
   ```
3. Create `~/.config/claude-config/deny-terms` with one term per line, at least one. The hook never commits a file whose name or text holds a term (case-insensitive), and it pushes nothing that names a term, commit messages included. With no term list it commits and pushes nothing. The file stays outside the repo.
4. Start a new session. The hook clones the repo to `~/.local/share/claude-memory` (`$XDG_DATA_HOME/claude-memory`), syncs at every new session and at session end, and lists the memories at every session start. It links `~/.omc/skills` to the store's `skills/` when nothing is at that path.

Failures go to `~/.claude/claude-config/memory.log`, each with a one-line warning in the session. `no-deny-terms` means nothing was synced because the term list is missing or empty. `blocked-files` means the leak guard stopped a push that would send a term; fix the store's local history by hand. `conflict` means two machines edited the same file, or the store was found mid-rebase, mid-merge or with a detached HEAD: merge, finish or abort by hand in the store. `git-failed` means a local git step failed; if it repeats, look for a stale `.git/index.lock` in the store. If only the store's `.git` is gone, delete the whole store directory so the next session clones again.

## Add a second machine, a skill or a hook

- **Machine:** copy `hosts/personal.json` to `hosts/<name>.json`, change `name` and `defaultTracker`, deploy with `--host <name>`.
- **Skill:** add `config/skills/<name>/SKILL.md` (markdown, plus stdlib-only Python under `scripts/` if it needs one), list it in the host profiles, run the tests.
- **Hook:** add it to `config/hooks/`, wire it in `config/settings.fragment.json`, list it in the host profiles, and test it.

The fragment's `env` keys are set in the deployed `settings.json` on every host; today that is `OMC_GIT_GUARDRAILS=0`, which turns off OMC's `git-guardrails` hook in every mode ([ADR-0008](docs/adr/0008-omc-pushes-feature-branches.md)). The fragment also adds two `permissions.allow` entries, `Edit` rules for the global-memory store's `*.md` files and its `skills/` directory (not its `.git/`), so saving a memory or a skill there needs no prompt. Rollback removes only those keys and those entries.

## Develop

```bash
make setup    # creates .venv and installs requirements-dev.txt (pytest, pytest-cov, ruff)
make test     # python3 -I -m pytest in the venv
make lint     # ruff check
```

On Debian and Ubuntu, `make setup` needs the `python3-venv` package. `requirements-dev.txt` mirrors the `dev` group in `pyproject.toml`; a test keeps them equal.

`.github/workflows/ci.yml` runs `make lint` and `make test` on every pull request.
