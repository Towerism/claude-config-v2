# ADR-0002: One JSON file per machine

**Status:** Accepted 2026-10-24.

## Context

The personal machine tracks work in GitHub, the work machine in Jira. Everything else should be the same.

## Decision

`hosts/<name>.json` names the skills, hooks, plugins and marketplaces a machine gets and its `defaultTracker`. Content is never rewritten per host; the only substitution is `{claude_home}` in the hook commands of `settings.fragment.json`. A test fails if two profiles differ in anything but `name` and `defaultTracker`. Machine-only values (Jira project and site) live in `~/.config/claude-config/local.json`, which nothing writes.

## Consequences

A third machine is one new file. `cfg.py` records what it installed in `<home>/claude-config/state.json`, backs up what it overwrites, and refuses to overwrite a file edited since the last deploy unless `--force` is given.
