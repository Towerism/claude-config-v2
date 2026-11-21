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
- **A hook entry's `if` field limits a tool hook to a path.** An `Edit(//<store>/**)` condition fires only for the Edit tool and a `Write(...)` one only for the Write tool, so the fragment has both. `Read(...)` on `PreToolUse` fires for reads in the store. None fires for a file outside the store.
- **`"async": true` runs a hook in the background,** and its context reaches the model on the next turn.
- **`SessionEnd` hooks share one budget.** It equals the largest `SessionEnd` timeout configured and is capped at 60 seconds (1.5 seconds only when none is configured), so an entry with a 60-second timeout gets 60. They are not documented to fire when a terminal is closed. git runs in its own process session, so killing the hook does not kill git.
- **The settings' `if` filter is documented as best-effort.**
- **There is no timer event.**

## Drivers

- Memories that hold in any repo reach every machine and every project with nothing to remember.
- No employer or client name leaves a machine, even if the user forgets to check.
- The repo stays public and holds no memory.
- The hook stays standard-library Python and exits 0 on any input, like the other hooks.

## Decision

1. **A private git repo holds the memories, and a hook syncs it.** `config/hooks/global_memory.py` runs at session start, around every access to the store and at session end (see 3). It does nothing, and runs no git, unless `~/.config/claude-config/local.json` sets `"memory": {"repo": "<git URL>"}`. The URL is a machine value, so it stays out of the public repo, and each machine may use a different one for the same repo.
2. **The store is a clone at `$XDG_DATA_HOME/claude-memory`** (default `~/.local/share/claude-memory`). Top-level `<name>.md` files are memories in Claude's own memory format. `skills/` holds OMC learned skills. There is no `MEMORY.md`: an index generated from the files cannot conflict between machines.
3. **Sync runs during the session, with a backstop at its end.** A session can run for hours, so a sync only at its end left what it learned invisible to the other machine and widened the window in which both machines edit one memory. There is no timer event, so the hook syncs on these events:
   - **Session start with source `startup`:** always.
   - **Before every Read, Write or Edit of a file in the store** (`PreToolUse`, blocking): always, so the tool sees the newest text. The sync backs off only while the last attempt failed less than 60 seconds (`PULL_SECONDS`) ago; `claude-config/memory.failed` in the Claude home holds that state. Network steps get 3 seconds (`READ_SECONDS`) here. A throttle on these pulls would hide the one that matters: the other machine edits a memory, this session reads or edits it within a minute of its last sync, works on old text, and the resulting conflict stops syncing for the rest of the session. If the pull changes a file the session read earlier, Claude Code's own "modified since read" check makes it read the file again before editing.
   - **After a Write or Edit of a file in the store** (`PostToolUse`, in the background): always, so a memory reaches the remote seconds after it is written.
   - **At session end** (`SessionEnd`, timeout 60 seconds): always. It is the backstop for what the post-write hook cannot see: a memory deleted, renamed or edited through a shell command or by hand, a post-write hook killed when a non-interactive run exits, and a write followed at once by exit.
   - **On each prompt** (`UserPromptSubmit`, in the background) **and on session start with another source:** only if the last sync attempt is older than 60 seconds. The time of the last attempt, successful or not, is the mtime of `claude-config/memory.pulled`.

   The post-write and session-end syncs wait up to 30 seconds (`WAIT_SECONDS`) for a sync already running, so two quick writes both go out, and then skip. Every other event skips quietly while another session holds the lock. For the tool events the hook does not rely on the settings' `if` filter alone: it does nothing unless the tool's file path, resolved, lies inside the store. The steps:
   1. Clone the repo when the store is missing. Without a usable `~/.config/claude-config/deny-terms` (missing, unreadable or empty) the hook stops here: no commit, nothing synced in either direction (`no-deny-terms`).
   2. Refuse to touch a store found mid-rebase, mid-merge or with a detached HEAD (`conflict`).
   3. Keep `MEMORY.md` and dot-files out of git through the store's `.git/info/exclude`. Claude's built-in memory habit is to write a `MEMORY.md` index, and two machines doing so would conflict on every sync.
   4. Stage every change, then unstage each file whose name or staged text contains a line of `deny-terms` (case-insensitive). Such a file stays on this machine, untracked.
   5. Commit what is staged, fetch, and rebase onto `origin/main` when the local `main` does not already contain it. A rebase would flatten a merge made by hand, so a `main` that already contains `origin/main` is left as it is.
   6. Check what every commit not yet on the remote adds, in two parts against `deny-terms` the same way. First, each commit's message and its author and committer name and email. Second, the file names and the added lines of each change, binary files read as text and the resolution of a hand merge included. Removed lines and deleted files are not checked, so deleting or editing a pushed memory after its term joined `deny-terms` goes through. One match stops the whole push (`blocked-files`), and the user fixes the store's local history by hand. A file committed by hand or by an earlier run never passes step 4, so this check is the last guard.
   7. Push exactly the commit that was checked.

   Network steps get 15 seconds (3 before a tool call) and local steps 10.
4. **The leak guard fails closed.** The hook itself never commits a file that names a term, and nothing that names a term is pushed. With no usable term list it commits and pushes nothing at all, because the one outcome the store must never have is a name leaving the machine. A `deny-terms` file with a UTF-8 byte-order mark is read correctly.
5. **A failed rebase is aborted and the local commit stays** (`conflict`); the user recovers by hand in the store with either `git merge origin/main` (resolve, commit) or `git rebase origin/main` (resolve, `git rebase --continue`); the next sync pushes the result. The warning reads "The store has a merge or rebase to finish by hand; local commits stay." `conflict` also reports a store found mid-rebase, mid-merge or with a detached HEAD, where the hook touched nothing; the user finishes or aborts that by hand. The clone is made with a fixed neutral git identity (`claude-memory`) in the store's own config, so a commit made by hand in the store does not carry the user's own, possibly work, identity. A store cloned before that setting keeps its old config. Every failure on every event logs a fixed reason word and the UTC time to `claude-config/memory.log` in the Claude home (last 200 lines kept). A fixed one-line `systemMessage` is shown at session start for any reason. Failing to reach the remote (`clone-failed`, `fetch-failed`, `push-failed`, `timeout`) is a normal state, so it is logged every time and shown only at session start. After a write only the reasons the user must act on are shown: `conflict`, `blocked-files`, `no-deny-terms`, `git-failed` and `no-git`. The pre-access, prompt and session-end hooks never show a warning; the pre-access and session-end hooks print nothing, and the prompt hook prints only the delta or full index described in decision 11. The reason words are `clone-failed`, `fetch-failed`, `conflict`, `push-failed`, `blocked-files`, `no-deny-terms`, `timeout`, `no-git` and `git-failed` (a local git step failed). The session continues with the local copy.
6. **A generated index goes into every `SessionStart`,** so it survives `compact` and `resume`; a prompt prints it too when the session has no usable seen record (decision 11). It is a fixed header followed by one line per memory, `<name> — <description>`. The header tells the model the entries are data, not instructions.
   - A file is listed only when its name matches `[a-z0-9][a-z0-9-]*\.md`.
   - The description is the frontmatter's, on one line, with control characters removed and cut at 110 characters.
   - The context text stops at 9,800 characters and ends with the count of files not listed. The 10,000-character limit applies to the context text, not to the raw JSON around it.
   - It never prints the `deny-terms` file or a memory body. A file kept local for naming a term is still listed, with its description, in the index on that same machine.
7. **The routing rule lives only in that header:** a memory that holds in any repo on any machine (who the user is, how they want Claude to work) is saved in the store; anything naming a project, client or employer stays in project memory; a learned skill that is not project-specific is saved in the store's `skills/`. The guardrails in `config/CLAUDE.global.md` do not repeat it.
8. **The hook links `~/.omc/skills` to the store's `skills/`** when nothing exists at that path, so OMC loads the learned skills from the store. An existing file, directory or link there is left alone. git runs with `core.symlinks=false`, so a symlink committed to the remote arrives as a plain file and cannot redirect that path.
9. **`cfg.py` merges two `permissions.allow` entries,** `Edit(//<store>/*.md)` and `Edit(//<store>/skills/**/*.md)` (markdown files only, so a nested `.git` under `skills/` is not covered either), into `settings.json`, so saving a memory or a skill in the store needs no prompt. They deliberately leave out the store's `.git/`: a rule over the whole store would let a session rewrite the store's git config without a prompt, and the hook's next run would act on it. Spiked on Claude Code 2.1.330: a skill file directly under `skills/` and one in a subfolder are written without a prompt, and writes under `<store>/.git/` and `skills/x/.git/` are refused. State records the entries it added and rollback removes exactly those; entries the user added stay.
10. **`XDG_DATA_HOME` and `XDG_CONFIG_HOME` are honoured only when absolute.**
11. **On each prompt the session is told what changed.** The hook prints the memories added or changed in the store since the session last saw it, its own writes included, in the index's entry format with the same sanitising and budget under a fixed one-line header. It prints nothing when none changed, and deleted memories are not announced. What a session has seen is one small file per session, `claude-config/memory-seen/<session id>` in the Claude home, holding the store's `main` commit at the time. Session start writes it after the index, and each prompt updates it. A session id is used as a file name only if it matches `[A-Za-z0-9-]{1,64}`. A session with no usable record on a prompt gets the full index once, the same text session start prints, and the commit is then recorded. A record is unusable when the file is missing or garbled or names a commit the store does not have: a session already running when the hook was first deployed, or one that started while the store was empty. The prompt prints nothing only while the store has no commit, or when the record cannot be written. A startup sync removes seen files older than 30 days.

### A departure from "hooks print only checked values"

The repo rule says hooks print only values they checked. This hook prints text read from the store into the session: validated file names and sanitised one-line descriptions. It is accepted because the store is the user's own private repo, written by the user's own sessions. File names are pattern-checked, descriptions are single-line with control characters removed and a length cap, and the total is capped. What remains unguarded is a well-formed but misleading description; the guards cannot judge what a sentence means.

## Alternatives passed over

- **A user-level `autoMemoryDirectory`.** One directory serves every project with no per-project subfolder, so a synced folder would pool every project's facts from every machine into one index that loads only its first 200 lines or 25 KB.
- **Syncing all of `~/.claude/projects/*/memory`.** It moves the per-project memories, including those that name an employer's projects, to the other machine, which the leak guard exists to prevent.
- **Putting the memories in this public repo.** The repo is public, and some memories must not leave the work machine.
- **`~/.claude/rules/` or CLAUDE.md imports.** Both load every body in full at every session, and a deploy overwrites them.

## Consequences

- Per-project memory is unchanged. Only memories saved in the store are shared.
- Subagents work as they did before this change. Probed on Claude Code 2.1.330, a built-in subagent and an OMC subagent both receive no auto-memory section and no `MEMORY.md` index, and no installed agent definition declares its own memory. A fork inherits the parent's context, index included. A subagent's writes into the store are synced like any other.
- A memory written through a shell command or by hand triggers no write hook; the next sync of any kind, session end included, picks it up.
- A long session with no prompts gets other machines' memories into its store when it reads or writes a memory, but its in-context index is refreshed only at the next prompt or compaction.
- In non-interactive runs the background prompt hook can be killed at exit before it reports the delta, and the post-write hook before it pushes; the session-end sync pushes what was missed.
- On a very slow disk the pre-access hook's local git steps could exceed its 15-second timeout. The access then proceeds on local text.
- About 85 memories fit the index. Past that the last line tells Claude to list the store directory.
- Two machines editing the same memory file between syncs end in a `conflict`; the user merges or rebases `origin/main` by hand in the store.
- A memory naming a deny-term stays on its machine, silently: no warning is shown for it.
- A machine with no usable `deny-terms` syncs nothing in either direction. The warning (shown at session start and after a write) says so, and the hook resumes once a term list exists.
- A well-formed but misleading description enters the session as written (see the departure above). A session that is talked into writing a misleading memory or skill writes it without a prompt, and it syncs to both machines.
- Deny-term matching is a case-insensitive substring match with no Unicode normalisation.
- A git step killed at its deadline can leave `.git/index.lock` in the store. Every sync then reports `git-failed` until the lock file is removed by hand.
- The fragment has eight entries for this hook: session start; post-write for Write and Edit (two background hooks); pre-access for Read, Write and Edit (three blocking hooks, timeout 15 seconds); prompt (background); session end (timeout 60 seconds). The other timeouts are 120 seconds.
- If only the store's `.git` is deleted, the clone fails on every run. Delete the whole store directory to re-clone.
- Both host profiles list the hook. Setting `memory.repo` is what turns it on, per machine.
- `promote-skill-to-config` also takes learned skills from the store's `skills/`.
