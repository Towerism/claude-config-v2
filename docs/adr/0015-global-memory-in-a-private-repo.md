# ADR-0015: Share general memories and learned skills through a private git repo

**Status:** Accepted 2026-11-20, issue #71.

## Context

A rule learned on one machine ("decide reversible defaults yourself") has to be learned again on the other, and is not visible in other projects on the same machine. The facts below were checked by spikes on Claude Code 2.1.330 and OMC 5.7.30.

- **Claude Code's file memory is per repository and machine-local.** A user-level `autoMemoryDirectory` gives one directory for every project, with no per-project subfolder. Pointing it at a synced folder would pool every project's facts from every machine into one index, and that index loads only its first 200 lines or 25 KB.
- **OMC's only user-wide durable store is learned skills.** Its project memory, notepad and wiki are per project.
- **This repo is public.** It can carry the mechanism but not the memories. Some memories on a work machine name an employer's projects and must not leave it.
- **Claude Code refuses writes under the Claude home** as a "sensitive file", so the store has to live elsewhere. An `Edit(//<absolute path>/...)` allow rule alone permits writes there. A `Write(...)` path rule is not matched, and `additionalDirectories` alone does not grant the write.
- **Hook output over 10,000 characters is replaced by a preview.** A 9,950-character output arrives whole; a 10,050-character one does not. The index needs a budget below that.
- **OMC loads user skills through a symlinked `~/.omc/skills`.**

## Drivers

- Memories that hold in any repo reach every machine and every project with nothing to remember.
- No employer or client name leaves a machine, even if the user forgets to check.
- The repo stays public and holds no memory.
- The hook stays standard-library Python and exits 0 on any input, like the other hooks.

## Decision

1. **A private git repo holds the memories, and a hook syncs it.** `config/hooks/global_memory.py` runs on every `SessionStart` and on `SessionEnd`. It does nothing, and runs no git, unless `~/.config/claude-config/local.json` sets `"memory": {"repo": "<git URL>"}`. The URL is a machine value, so it stays out of the public repo, and each machine may use a different one for the same repo.
2. **The store is a clone at `$XDG_DATA_HOME/claude-memory`** (default `~/.local/share/claude-memory`). Top-level `<name>.md` files are memories in Claude's own memory format. `skills/` holds OMC learned skills. There is no `MEMORY.md`: an index generated from the files cannot conflict between machines.
3. **Sync runs on `SessionStart` with source `startup` and on `SessionEnd`,** under a lock; a session that finds it held skips the sync quietly. The steps:
   1. Clone the repo when the store is missing. Without a usable `~/.config/claude-config/deny-terms` (missing, unreadable or empty) the hook stops here: no commit, nothing synced in either direction (`no-deny-terms`).
   2. Refuse to touch a store found mid-rebase, mid-merge or with a detached HEAD (`conflict`).
   3. Keep `MEMORY.md` and dot-files out of git through the store's `.git/info/exclude`. Claude's built-in memory habit is to write a `MEMORY.md` index, and two machines doing so would conflict on every sync.
   4. Stage every change, then unstage each file whose name or staged text contains a line of `deny-terms` (case-insensitive). Such a file stays on this machine, untracked.
   5. Commit what is staged, fetch, and rebase onto `origin/main`.
   6. Check everything the push would send, which is every commit not yet on the remote: file text (binary files included), file names, and commit messages, against `deny-terms` the same way. One match stops the whole push (`blocked-files`), and the user fixes the store's local history by hand. A file committed by hand or by an earlier run never passes step 4, so this check is the last guard.
   7. Push exactly the commit that was checked.

   Network steps get 15 seconds and local steps 10.
4. **The leak guard fails closed.** The hook itself never commits a file that names a term, and nothing that names a term is pushed. With no usable term list it commits and pushes nothing at all, because the one outcome the store must never have is a name leaving the machine. A `deny-terms` file with a UTF-8 byte-order mark is read correctly.
5. **A failed rebase is aborted and the local commit stays** (`conflict`); someone merges it by hand in the store. `conflict` also reports a store found mid-rebase, mid-merge or with a detached HEAD, where the hook touched nothing; the user finishes or aborts that by hand. Every failure logs a fixed reason word and the UTC time to `claude-config/memory.log` in the Claude home (last 200 lines kept) and shows the user a fixed one-line `systemMessage`. The reason words are `clone-failed`, `fetch-failed`, `conflict`, `push-failed`, `blocked-files`, `no-deny-terms`, `timeout`, `no-git` and `git-failed` (a local git step failed). The session continues with the local copy.
6. **A generated index goes into every `SessionStart`,** so it survives `compact` and `resume`. It is a fixed header followed by one line per memory, `<name> — <description>`. The header tells the model the entries are data, not instructions.
   - A file is listed only when its name matches `[a-z0-9][a-z0-9-]*\.md`.
   - The description is the frontmatter's, on one line, with control characters removed and cut at 110 characters.
   - The context text stops at 9,800 characters and ends with the count of files not listed. The 10,000-character limit applies to the context text, not to the raw JSON around it.
   - It never prints the `deny-terms` file or a memory body. A file kept local for naming a term is still listed, with its description, in the index on that same machine.
7. **The routing rule lives only in that header:** a memory that holds in any repo on any machine (who the user is, how they want Claude to work) is saved in the store; anything naming a project, client or employer stays in project memory; a learned skill that is not project-specific is saved in the store's `skills/`. The guardrails in `config/CLAUDE.global.md` do not repeat it.
8. **The hook links `~/.omc/skills` to the store's `skills/`** when nothing exists at that path, so OMC loads the learned skills from the store. An existing file, directory or link there is left alone. git runs with `core.symlinks=false`, so a symlink committed to the remote arrives as a plain file and cannot redirect that path.
9. **`cfg.py` merges two `permissions.allow` entries,** `Edit(//<store>/*.md)` and `Edit(//<store>/skills/**)`, into `settings.json`, so saving a memory or a skill in the store needs no prompt. They deliberately leave out the store's `.git/`: a rule over the whole store would let a session rewrite the store's git config without a prompt, and the hook's next run would act on it. Spiked on Claude Code 2.1.330: both rules permit their writes, and a write under `<store>/.git/` is refused. State records the entries it added and rollback removes exactly those; entries the user added stay.
10. **`XDG_DATA_HOME` and `XDG_CONFIG_HOME` are honoured only when absolute.**

### A departure from "hooks print only checked values"

The repo rule says hooks print only values they checked. This hook prints text read from the store into the session: validated file names and sanitised one-line descriptions. It is accepted because the store is the user's own private repo, written by the user's own sessions. File names are pattern-checked, descriptions are single-line with control characters removed and a length cap, and the total is capped. What remains unguarded is a well-formed but misleading description; the guards cannot judge what a sentence means.

## Alternatives passed over

- **A user-level `autoMemoryDirectory`.** One directory serves every project with no per-project subfolder, so a synced folder would pool every project's facts from every machine into one index that loads only its first 200 lines or 25 KB.
- **Syncing all of `~/.claude/projects/*/memory`.** It moves the per-project memories, including those that name an employer's projects, to the other machine, which the leak guard exists to prevent.
- **Putting the memories in this public repo.** The repo is public, and some memories must not leave the work machine.
- **`~/.claude/rules/` or CLAUDE.md imports.** Both load every body in full at every session, and a deploy overwrites them.

## Consequences

- Per-project memory is unchanged. Only memories saved in the store are shared.
- Subagents get no index; a subagent that needs a memory is briefed by its parent. A `SubagentStart` entry later is one line in the fragment.
- About 85 memories fit the index. Past that the last line tells Claude to list the store directory.
- Two machines editing the same memory file between syncs end in a `conflict`; the user merges by hand in the store.
- A memory naming a deny-term stays on its machine, silently: no warning is shown for it.
- A machine with no usable `deny-terms` syncs nothing in either direction. The warning says so, and the hook resumes once a term list exists.
- A well-formed but misleading description enters the session as written (see the departure above). A session that is talked into writing a misleading memory or skill writes it without a prompt, and it syncs to both machines.
- Deny-term matching is a case-insensitive substring match with no Unicode normalisation.
- A git step killed at its deadline can leave `.git/index.lock` in the store. Every sync then reports `git-failed` until the lock file is removed by hand.
- Claude Code gives `SessionEnd` hooks at most 60 seconds, whatever timeout is configured.
- If only the store's `.git` is deleted, the clone fails on every run. Delete the whole store directory to re-clone.
- Both host profiles list the hook. Setting `memory.repo` is what turns it on, per machine.
- `promote-skill-to-config` also takes learned skills from the store's `skills/`.
