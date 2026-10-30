# claude-config v2

A small layer on top of [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (OMC) for one person's Claude Code setup. OMC provides the development workflow: interview, plan, execute, review, verify. This repo adds only who approves and who merges, issue-tracker skills, and a tool that installs the same setup on a personal machine and a work machine.

V1 (`claude-config`) built its own pipeline from 24 skills, overlays and three hooks. V2 drops that pipeline and keeps the parts OMC doesn't cover. [docs/gap-analysis.md](docs/gap-analysis.md) lists every V1 piece and what became of it.

## Design philosophies

1. **Two machines are one JSON file apart.** A host profile in `hosts/` selects skills, hooks and plugins. The personal and work profiles differ only in `name` and `defaultTracker` (a test enforces it).
2. **Skills have zero dependencies.** No third-party packages and nothing to install: a skill is markdown, plus standard-library Python under `scripts/` where determinism matters (the lifecycle skills), so a new machine needs only `python3` and the tracker's CLI. Each skill is self-contained. Plumbing (`tools/`, the hooks) may use whatever it needs to keep the repo lean; today it needs only Python 3.11+. See [ADR-0003](docs/adr/0003-skills-zero-dependency.md).

## What is here

| Path | What it holds |
|---|---|
| `config/CLAUDE.global.md` | The guardrails: eight lines, deployed into `~/.claude/CLAUDE.md` as a marked block beside OMC's own. They state only what OMC, the lifecycle skills and the hooks don't: the user approves every spec and every merge ([ADR-0006](docs/adr/0006-omc-leads-the-pipeline.md)) |
| `config/skills/` | `github-issue-lifecycle`, `gitea-issue-lifecycle`, `jira-ticket-lifecycle` (each with a stdlib script for its checks and tracker steps), `fresh-session-handoff`, `linux-troubleshooting`, `architecture-backfill` (docs a repo's architecture and past decisions from code and history, each claim labeled verified or inferred). Prose rules come from OMC's `minimal-prose-discipline` and `agent-doc-discipline` |
| `config/hooks/` | `merge_confirm.py` (every PR merge waits for your click), `host_default.py` (states the repo's tracker at session start, from its history, its `origin` and the host profile) and `auto_sync.py` (deploys `main` from `origin` at the start of each new session, [ADR-0007](docs/adr/0007-auto-sync-at-session-start.md)) |
| `hosts/` | `personal.json`, `work.json` |
| `tools/cfg.py` | plan, deploy, status and rollback |
| `tests/` | repo invariants, hooks, `cfg.py`, and the lifecycle scripts (`tests/skills/`, against a fake `gh` and `jira`) |
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

Per-machine values that never enter the repo live in `~/.config/claude-config/local.json`: `autoSync` (above), and the `jira` settings that tailor `jira-ticket-lifecycle` to your Jira project (see its `references/settings.md`). A top-level `defaultTracker` there is ignored; the host profile holds the default.

## Add a second machine, a skill or a hook

- **Machine:** copy `hosts/personal.json` to `hosts/<name>.json`, change `name` and `defaultTracker`, deploy with `--host <name>`.
- **Skill:** add `config/skills/<name>/SKILL.md` (markdown, plus stdlib-only Python under `scripts/` if it needs one), list it in the host profiles, run the tests.
- **Hook:** add it to `config/hooks/`, wire it in `config/settings.fragment.json`, list it in the host profiles, and test it.

## Develop

```bash
make setup    # creates .venv and installs requirements-dev.txt (pytest, pytest-cov, ruff)
make test     # python3 -I -m pytest in the venv
make lint     # ruff check
```

On Debian and Ubuntu, `make setup` needs the `python3-venv` package. `requirements-dev.txt` mirrors the `dev` group in `pyproject.toml`; a test keeps them equal.

`.github/workflows/ci.yml` runs `make lint` and `make test` on every pull request.
