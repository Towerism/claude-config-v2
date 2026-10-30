# ADR-0007: Deploy main automatically at session start

**Status:** Accepted 2026-10-30, issue #46.

## Context

A change merged to `main` reached a machine only when someone ran `make deploy` in a checkout on it. Nothing reminded anyone to do it, so a machine could run older guardrails and skills than `main` without saying so.

## Drivers

- Each new session should start on the config that is on `main`, with nothing to remember.
- Nothing about the sync may enter the model's context.
- The user's working checkout, its feature branches and uncommitted work, is never touched.
- A sync never leaves `~/.claude` half-deployed without saying so, and never blocks a session for long when the network is slow or down.
- The plumbing stays standard-library Python, like `cfg.py` and the other hooks.

## Decision

1. **A `SessionStart` hook, `auto_sync.py`, with matcher `startup`**, runs before the first prompt of every new session. Its hook entry sets `statusMessage` so a spinner shows, and a 120-second timeout, longer than the fetch deadline, the local git steps and a full deploy together. Both host profiles list it.
2. **It deploys from a dedicated clone, never the working checkout.** `cfg.py deploy --yes` clones `main` from the `origin` URL of the checkout it runs in, once, into `$XDG_DATA_HOME/claude-config` (default `~/.local/share/claude-config`), and records the path as `syncClone` in `state.json`; later deploys reuse the recorded clone. Without an `origin`, or offline, the deploy still runs with a warning, nothing is recorded, and the next deploy tries again.
3. **Fetch, fast-forward, clean, deploy.** The hook fetches `main` with a 15-second deadline, fast-forwards the clone's `main` only, and removes untracked files from the clone (`cfg.py` collects files by walking the disk, so they would ship). Each local git step has 10 seconds. The clone, its `tools/` and `tools/cfg.py` must belong to the user and not be group- or world-writable, or nothing runs. The hook then runs the clone's `cfg.py deploy --yes --force` for the recorded host. The deadlines never cover the deploy: once started, it runs to the end, in its own session, and it inherits the lock. A deploy with nothing to change makes no backup.
4. **Always apply.** `--force` overwrites files edited by hand in `~/.claude`; they are backed up first, and `make rollback` restores them. This departs from ADR-0002's "refuses to overwrite a file edited since the last deploy" for the automatic path only; a manual deploy still stops on an edited file without `FORCE=1`.
5. **Silent on success, a warning on failure.** On success the hook prints nothing, or only `reloadSkills: true` when the deploy changed something, so skills it wrote are found in the same session. On failure a line with the UTC time and a fixed reason goes to `~/.claude/claude-config/sync.log` (last 200 lines kept), and a fixed one-line `systemMessage` warns the user. `make status` shows the last line of that log. The reasons:
   - before any write, so the current config stays: `fetch-failed`, `timeout`, `diverged`, `git-failed`, `no-git`, `unsafe-clone`, and `deploy-failed` (the deploy stopped before its backup);
   - after the deploy's backup: `deploy-rolled-back` (the hook ran the clone's `cfg.py rollback`, which worked) or `deploy-failed-partial` (the rollback failed too; the warning says the config may be partly updated and to run `make rollback`).
6. **A diverged `main` is repaired by hand.** A `main` that can't be fast-forwarded, for example after a force-push, is not applied and is reported as `diverged`; the warning says to run `make deploy YES=1`. A deploy run by hand from a checkout other than the clone fetches `main` into the clone and, if they diverged, resets the clone's `main` to `origin/main`. If that fetch fails it warns and deploys anyway.
7. **One sync at a time.** A lock file, `~/.claude/claude-config/sync.lock`, makes a second session that starts during a sync skip quietly. The deploy inherits the lock, so it stays held until the deploy ends even if the hook is killed.
8. **Opt-out per machine:** `"autoSync": false` in `~/.config/claude-config/local.json`. The hook then runs no git.
9. **git runs hardened**, by absolute path from the fixed `PATH` `/usr/local/bin:/usr/bin:/bin`, with a fixed argv and environment: no `GIT_*` variables from the session, no `SSH_ASKPASS`, `GIT_TERMINAL_PROMPT=0`, `GIT_SSH_COMMAND="ssh -o BatchMode=yes"` and `GIT_ATTR_NOSYSTEM=1`. These settings are overridden on the command line: `core.fsmonitor`, `core.hooksPath`, `core.gitProxy`, `core.askPass`, `core.attributesFile`, `protocol.ext.allow`, `remote.origin.uploadpack`, `submodule.recurse`, `fetch.recurseSubmodules`, `gc.auto` and `maintenance.auto`, plus `--no-optional-locks`. Filters named in the repo's own `.gitattributes` are not overridden; claude-config has no `.gitattributes` today, and adding one with a filter needs a new look at this hook.

## Alternatives rejected

- **Ship the config as a Claude Code plugin and use its auto-update.** A plugin can deliver skills and hooks, but not the guardrails block in `~/.claude/CLAUDE.md` or the merged `settings.json` (plugins, marketplaces, hook entries). Its update also runs in the background after the session has started, so the first session after a merge would still run the old config. `cfg.py` stays the delivery path.
- **Pull the user's working checkout.** It may sit on a feature branch, in a worktree, or hold uncommitted work; pulling would move it under the user, and deploying from it would ship unmerged changes.
- **A timer (cron or a systemd unit).** More to install per machine, and it runs whether or not Claude Code is used; a session start is exactly when the config matters.
- **Sync on `resume`, `clear`, `compact` or `fork`.** Those continue an existing session; changing its config midway helps little and costs a fetch each time.

## Consequences

- Deploys now also run automatically, at every new session, from `main` on `origin`. A manual deploy from a feature branch is replaced by `main` at the next session start; set `"autoSync": false` to try a branch for longer.
- A rollback, like a hand edit in `~/.claude`, holds only until the next new session, unless `"autoSync": false` is set. An overwritten hand edit survives only in the backups, and `cfg.py` keeps the last five (`KEEP_BACKUPS`).
- **Anyone who can push or merge to `main`, or who controls the GitHub account, gets code execution on every synced machine at its next session start, with no human deploy in between.** Protect `main` with branch protection (required reviews, no force-push) on the repo's host.
- Changes to `CLAUDE.md` and `settings.json` take effect from the next session: whether Claude Code reloads them in the session that ran the sync is not documented. Skills take effect at once through `reloadSkills`.
- Offline or behind a slow remote, a session start waits up to the fetch deadline and then starts on the current config with a warning.
- Because `GIT_SSH_COMMAND` overrides `core.sshCommand` and `PATH` is fixed, a setup that needs a custom ssh command, or a credential helper outside `/usr/local/bin:/usr/bin:/bin`, gets `fetch-failed` at every session start. The warning, `~/.claude/claude-config/sync.log` and `make status` show it; such a machine can opt out.
- A rollback after a partial deploy uses `cfg.py rollback`, which restores `settings.json` whole only if it still matches the last recorded deploy; otherwise it strips claude-config's hook entries from it, and the next `make deploy YES=1` puts them back.
- A machine that has not deployed since this change has no clone recorded, so the hook does nothing until the next `make deploy YES=1`.
