# claude-config v2

A small layer on top of [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (OMC) for one person's Claude Code setup. OMC provides the development workflow: interview, plan, execute, review, verify. This repo adds only what OMC lacks: a few guardrails, issue-tracker skills, and a tool that installs the same setup on a personal machine and a work machine.

V1 (`claude-config`) built its own pipeline from 24 skills, overlays and three hooks. V2 drops that pipeline and keeps the parts OMC doesn't cover. [docs/gap-analysis.md](docs/gap-analysis.md) lists every V1 piece and what became of it.

## Design philosophies

1. **Two machines are one JSON file apart.** A host profile in `hosts/` selects skills, hooks and plugins. The personal and work profiles differ only in `name` and `defaultTracker` (a test enforces it).
2. **Skills have zero dependencies.** No third-party packages and nothing to install: a skill is markdown, plus standard-library Python under `scripts/` where determinism matters (the lifecycle skills), so a new machine needs only `python3` and the tracker's CLI. Each skill is self-contained. Plumbing (`tools/`, the hooks) may use whatever it needs to keep the repo lean; today it needs only Python 3.11+. See [ADR-0003](docs/adr/0003-skills-zero-dependency.md).

## What is here

| Path | What it holds |
|---|---|
| `config/CLAUDE.global.md` | The guardrails, deployed into `~/.claude/CLAUDE.md` as a marked block beside OMC's own. In a session whose first prompt starts with a skill or contains an OMC keyword (`tdd`, `ultrathink`, `ralph` and the rest), the guardrails and every hook stand aside so OMC runs its own way ([ADR-0004](docs/adr/0004-agent-pathways.md)) |
| `config/skills/` | `github-issue-lifecycle`, `gitea-issue-lifecycle`, `jira-ticket-lifecycle` (each with a stdlib script for its checks and tracker steps), `fresh-session-handoff`, `linux-troubleshooting`, `architecture-backfill` (docs a repo's architecture and past decisions from code and history, each claim labeled verified or inferred). Prose rules come from OMC's `minimal-prose-discipline` and `agent-doc-discipline` |
| `config/hooks/` | `merge_confirm.py` (every PR merge waits for your click), `host_default.py` (states the machine's default tracker), `skill_gate.py` (adds review context from git facts, asks before the model starts autopilot), `secrets_guard.py` (denies reads of `.env` and `deny-terms`, asks when a command names one), `bash_guard.py` (asks before a commit or push on the default branch, a commit subject or branch name off the convention, a commit holding a token or `.env`, or adding the `approved` label) |
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
3. `make status` lists files edited since the last deploy and changes still pending. A deploy stops on an edited file until you pass `FORCE=1` (`--force`; the old copy is backed up). `make rollback` undoes the last deploy. A `HOST` or `TARGET` holding `'` or `$` needs the raw command. Only values typed after `make` count; exported variables are ignored.

Per-machine values that never enter the repo live in `~/.config/claude-config/local.json`: a `defaultTracker` override and the `jira` settings that tailor `jira-ticket-lifecycle` to your Jira project (see its `references/settings.md`).

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
