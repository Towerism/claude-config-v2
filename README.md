# claude-config v2

A small layer on top of [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (OMC) for one person's Claude Code setup. OMC provides the development workflow: interview, plan, execute, review, verify. This repo adds only what OMC lacks: a few guardrails, an issue-tracker skill, and a tool that installs the same setup on a personal machine and a work machine.

V1 (`claude-config`) built its own pipeline from 24 skills, overlays and three hooks. V2 drops that pipeline and keeps the parts OMC doesn't cover. [docs/gap-analysis.md](docs/gap-analysis.md) lists every V1 piece and what became of it.

## Design philosophies

1. **Two machines are one JSON file apart.** A host profile in `hosts/` selects skills, hooks and plugins. The personal and work profiles differ only in `name` and `defaultTracker` (a test enforces it).
2. **Skills have zero dependencies.** A skill is markdown: no scripts, no installs, nothing to carry to a new machine. Plumbing (`tools/`, the hooks) may use whatever it needs to keep the repo lean; today it needs only Python 3.11+.

## What is here

| Path | What it holds |
|---|---|
| `config/CLAUDE.global.md` | The guardrails, deployed into `~/.claude/CLAUDE.md` as a marked block beside OMC's own |
| `config/skills/` | `issue-lifecycle` (GitHub, Gitea and Jira), `writing-docs`, `fresh-session-handoff`, `linux-troubleshooting` |
| `config/hooks/` | `merge_confirm.py` (every PR merge waits for your click), `host_default.py` (states the machine's default tracker) |
| `hosts/` | `personal.json`, `work.json` |
| `tools/cfg.py` | plan, deploy, status and rollback |
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

Per-machine values that never enter the repo live in `~/.config/claude-config/local.json`: a `defaultTracker` override and the `jira` settings (see the Jira reference in the lifecycle skill).

## Add a second machine, a skill or a hook

- **Machine:** copy `hosts/personal.json` to `hosts/<name>.json`, change `name` and `defaultTracker`, deploy with `--host <name>`.
- **Skill:** add `config/skills/<name>/SKILL.md` (markdown only), list it in the host profiles, run the tests.
- **Hook:** add it to `config/hooks/`, wire it in `config/settings.fragment.json`, list it in the host profiles, and test it.

## Develop

```bash
python3 -I -m pytest          # needs pytest; pip install pytest pytest-cov
```

CI is not set up yet; run the tests before every push.
