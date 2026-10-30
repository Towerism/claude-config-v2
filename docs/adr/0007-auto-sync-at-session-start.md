# ADR-0007: Deploy main automatically at session start

**Status:** Accepted 2026-10-30, issue #46.

## Context

A change merged to `main` reached a machine only when someone ran `make deploy` in a checkout on it. Nothing reminded anyone to do it, so a machine could run older guardrails and skills than `main` without saying so.

## Drivers

- Each new session should start on the config that is on `main`, with nothing to remember.
- Nothing about the sync may enter the model's context.
- The user's working checkout, its feature branches and uncommitted work, is never touched.
- A sync never leaves `~/.claude` half-deployed and never blocks a session for long when the network is slow or down.
- The plumbing stays standard-library Python, like `cfg.py` and the other hooks.

## Decision

1. **A `SessionStart` hook, `auto_sync.py`, with matcher `startup`**, runs before the first prompt of every new session. Its hook entry sets `statusMessage` so a spinner shows, and a 120-second timeout, long enough for the fetch deadline and a full deploy. Both host profiles list it.
2. **It deploys from a dedicated clone, never the working checkout.** `cfg.py deploy --yes` makes the clone once in `$XDG_DATA_HOME/claude-config` (default `~/.local/share/claude-config`), from the checkout it runs in, with `origin` set to that checkout's `origin`, and records its path as `syncClone` in `state.json`. Without an `origin` the deploy still runs, with a warning, and auto sync stays off.
3. **Fetch, fast-forward, deploy.** The hook fetches `main` with a 15-second deadline, fast-forwards the clone's `main` only (a `main` that diverged, for example after a force-push, is not applied), and runs the clone's `cfg.py deploy --yes --force` for the recorded host. The deadline covers the fetch only: a deploy that has started always runs to the end, in its own session. A deploy with nothing to change makes no backup.
4. **Always apply.** `--force` overwrites files edited by hand in `~/.claude`; they are backed up first, and `make rollback` restores them. This departs from ADR-0002's "refuses to overwrite a file edited since the last deploy" for the automatic path only; a manual deploy still stops on an edited file without `FORCE=1`.
5. **Silent on success, a warning on failure.** On success the hook prints nothing, or only `reloadSkills: true` when the deploy changed something, so skills it wrote are found in the same session. On failure (`fetch-failed`, `timeout`, `diverged`, `deploy-failed`, `git-failed`, `no-git`) the current config stays, a line with the UTC time and the reason goes to `~/.claude/claude-config/sync.log` (last 200 lines kept), and a fixed one-line `systemMessage` warns the user. `make status` shows the last line of that log.
6. **One sync at a time.** A lock file, `~/.claude/claude-config/sync.lock`, makes a second session that starts at the same moment skip quietly.
7. **Opt-out per machine:** `"autoSync": false` in `~/.config/claude-config/local.json`. The hook then runs no git.
8. **The same git hardening as `host_default.py`:** git by absolute path from a fixed `PATH`, a fixed argv, no `GIT_*` variables, no repo config that runs programs (fsmonitor, hooks, a custom upload-pack, the ext transport). It never prompts (`GIT_TERMINAL_PROMPT=0`, ssh in `BatchMode`) but can use the user's ssh-agent or credential helper.

## Alternatives rejected

- **Ship the config as a Claude Code plugin and use its auto-update.** A plugin can deliver skills and hooks, but not the guardrails block in `~/.claude/CLAUDE.md` or the merged `settings.json` (plugins, marketplaces, hook entries). Its update also runs in the background after the session has started, so the first session after a merge would still run the old config. `cfg.py` stays the delivery path.
- **Pull the user's working checkout.** It may sit on a feature branch, in a worktree, or hold uncommitted work; pulling would move it under the user, and deploying from it would ship unmerged changes.
- **A timer (cron or a systemd unit).** More to install per machine, and it runs whether or not Claude Code is used; a session start is exactly when the config matters.
- **Sync on `resume`, `clear`, `compact` or `fork`.** Those continue an existing session; changing its config midway helps little and costs a fetch each time.

## Consequences

- Deploys now also run automatically, at every new session, from `main` on `origin`. A manual deploy from a feature branch is replaced by `main` at the next session start; set `"autoSync": false` to try a branch for longer.
- A hand edit in `~/.claude` lasts until the next new session; it is kept in the backup that deploy makes.
- Changes to `CLAUDE.md` and `settings.json` take effect from the next session: whether Claude Code reloads them in the session that ran the sync is not documented. Skills take effect at once through `reloadSkills`.
- Offline or behind a slow remote, a session start waits up to the fetch deadline and then starts on the current config with a warning.
- A machine that has not deployed since this change has no clone recorded, so the hook does nothing until the next `make deploy YES=1`.
