# claude-config v2

A small layer on top of [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (OMC) for one person's Claude Code setup. OMC provides the development workflow: interview, plan, execute, review, verify. This repo adds only what OMC lacks: a few guardrails, issue-tracker skills, and a tool that installs the same setup on a personal machine and a work machine.

V1 (`claude-config`) built its own pipeline from 24 skills, overlays and three hooks. V2 drops that pipeline and keeps the parts OMC doesn't cover. [docs/gap-analysis.md](docs/gap-analysis.md) lists every V1 piece and what became of it.

## Design philosophies

1. **Two machines are one JSON file apart.** A host profile in `hosts/` selects skills, hooks and plugins. The personal and work profiles differ only in `name` and `defaultTracker` (a test enforces it).
2. **Skills have zero dependencies.** No third-party packages and nothing to install: a skill is markdown, plus standard-library Python under `scripts/` where determinism matters (the lifecycle skills), so a new machine needs only `python3` and the tracker's CLI. Each skill is self-contained. Plumbing (`tools/`, the hooks) may use whatever it needs to keep the repo lean; today it needs only Python 3.11+. See [ADR-0003](docs/adr/0003-skills-zero-dependency.md).

## What is here

| Path | What it holds |
|---|---|
| `config/CLAUDE.global.md` | The guardrails, deployed into `~/.claude/CLAUDE.md` as a marked block beside OMC's own |
| `config/skills/` | `github-issue-lifecycle`, `gitea-issue-lifecycle`, `jira-ticket-lifecycle` (each with a stdlib script for its checks and tracker steps), `fresh-session-handoff`, `linux-troubleshooting`. Prose rules come from OMC's `minimal-prose-discipline` and `agent-doc-discipline` |
| `config/hooks/` | `merge_confirm.py` (every PR merge waits for your click), `host_default.py` (states the machine's default tracker), `skill_gate.py` (adds review context from git facts, asks before the model starts autopilot) |
| `hosts/` | `personal.json`, `work.json` |
| `tools/cfg.py` | plan, deploy, status and rollback |
| `tests/` | repo invariants, hooks, `cfg.py`, and the lifecycle scripts (`tests/skills/`, against a fake `gh` and `jira`) |
| `docs/` | gap analysis and decision records |

## Set up a machine

1. Install OMC's plugin in Claude Code, or let the deploy enable it: `cfg.py` adds the `omc` marketplace and enables `oh-my-claudecode@omc` in `settings.json`. Then run `/omc-setup` once.
2. Preview, then apply:

   ```bash
   python3 -I tools/cfg.py plan --host personal      # or: work
   python3 -I tools/cfg.py deploy --host personal --yes
   ```

   Later deploys remember the host. `--target DIR` (or `CLAUDE_CONFIG_DIR`) deploys somewhere else, such as a scratch directory.
3. `python3 -I tools/cfg.py status` lists files edited since the last deploy and changes still pending. A deploy stops on an edited file until you pass `--force` (the old copy is backed up). `python3 -I tools/cfg.py rollback` undoes the last deploy.

Per-machine values that never enter the repo live in `~/.config/claude-config/local.json`: a `defaultTracker` override and the `jira` settings that tailor `jira-ticket-lifecycle` to your Jira project (see its `references/settings.md`).

## Add a second machine, a skill or a hook

- **Machine:** copy `hosts/personal.json` to `hosts/<name>.json`, change `name` and `defaultTracker`, deploy with `--host <name>`.
- **Skill:** add `config/skills/<name>/SKILL.md` (markdown, plus stdlib-only Python under `scripts/` if it needs one), list it in the host profiles, run the tests.
- **Hook:** add it to `config/hooks/`, wire it in `config/settings.fragment.json`, list it in the host profiles, and test it.

## Develop

```bash
python3 -I -m pytest          # needs pytest; pip install pytest pytest-cov
```

CI is not set up yet; run the tests before every push.
