---
documentLanguage: en
---

# Glossary

One entry per term: definition, boundaries, one resolved ambiguity. Write here the moment a term is settled. Vocabulary here is law for specs, tickets and code naming. Ship-specific terms only: a concept any sea chart carries does not get an entry.

## Auto sync
- Definition: the deploy `auto_sync.py` runs at the start of each new session: it fetches `main` from `origin` into the sync clone, fast-forwards it and runs its `cfg.py deploy --yes --force` for the recorded host (ADR-0007).
- Boundary: only `main`, only fast-forwards, only on `startup`; never the user's working checkout. A failure logs a reason in `sync.log` and warns the user; a deploy that fails midway is rolled back. `"autoSync": false` in `local.json` turns it off.
- Avoid: "auto-update" (that is Claude Code's plugin update, which it does not replace).
- Resolved ambiguity: the sync clone is the dedicated clone of `main` that `cfg.py deploy --yes` makes from `origin` in `$XDG_DATA_HOME/claude-config` and records as `syncClone` in `state.json`. A manual deploy, a hand edit or a rollback holds only until the next new session unless auto sync is off; an overwritten hand edit survives only in the last five backups.

## Default tracker
- Definition: the issue tracker `host_default.py` names at session start for the current repo, with its source: a `jira.project` key in the repo's git history, then its `origin` remote, then the host profile's `defaultTracker` (ADR-0006).
- Boundary: the repo's own CLAUDE.md overrides it; a top-level `defaultTracker` in `local.json` is ignored.

## Guardrails
- Definition: the eight lines in `config/CLAUDE.global.md`; each states something no OMC text, lifecycle skill or hook already states (ADR-0006).
- Boundary: a rule already stated by OMC, a skill or a hook is not repeated there; the guardrails never choose OMC's stages, agents or runner.
- Resolved ambiguity: ADR-0006 amends ADR-0001's gap list; approval and merge on the user's word are the only fixed rules.

## Host profile
- Definition: `hosts/<name>.json`, naming the skills, hooks, plugins, marketplaces and `defaultTracker` one machine gets (ADR-0002).
- Boundary: is the only per-machine file in the repo; machine-only values (Jira project and site) live outside it, in `~/.config/claude-config/local.json`, which no longer overrides `defaultTracker`.
- Avoid: "environment", "config set".
- Resolved ambiguity: profiles differ only in `name` and `defaultTracker`; a test fails otherwise.

## Pipeline declaration
- Definition: the list shown with a spec at approval of every OMC stage that could run for the change, each marked `will run` or `skipped: <reason>`; approving the spec acknowledges it (ADR-0006).
- Boundary: an instruction only; nothing checks it, and it asks no separate question.
