# ADR-0004: Every OMC agent gets a pathway through the guardrails

**Status:** Accepted by the owner on 2026-10-24, issue #7. Stage 1 set the decision. Stages 2-4 built the hooks; each stage has an addendum below. A review phase followed stage 4 and has its own section. The deviations from the approved spec are listed in one section.

## Context

OMC 5.7.13 ships 19 agents. Six have a dependable path from `config/CLAUDE.global.md`: `test-engineer`, `planner`, `architect`, `critic`, `executor` and `explore`. The other 13 do not:

- Eight appear only in `team`'s roster, so a one-unit change on `execute` never reaches them: `code-reviewer`, `security-reviewer`, `verifier`, `designer`, `writer`, `document-specialist`, `code-simplifier`, `debugger`.
- Five have no path, or only a mention: `analyst` (reached only through `/plan`, which the pipeline does not call), `tracer` ("tracer bullet" is not the agent), `qa-tester` (an optional screenshot in `pr`), `git-master` and `scientist`.

## Decision

**Pinned roster.** The guardrails cover the 19 agents of OMC 5.7.13: `analyst`, `architect`, `code-reviewer`, `code-simplifier`, `critic`, `debugger`, `designer`, `document-specialist`, `executor`, `explore`, `git-master`, `planner`, `qa-tester`, `scientist`, `security-reviewer`, `test-engineer`, `tracer`, `verifier`, `writer`. `tests/test_repo.py` holds the list as `OMC_AGENTS`.

**Each agent has a stated condition.** Every agent gets a bullet with a trigger word (`when`, `if`, `touches`, `before`, `after`). The six agents reached through an existing skill keep that path. `writer` is covered by the variant and text-owner rules below.

**Two new unnumbered sections** follow the numbered steps 1-8 in `config/CLAUDE.global.md`. The numbered steps keep their order.

- **Agents by condition** (main pipeline). Examples: `code-simplifier` before step 6 when the diff exceeds 300 changed lines; `security-reviewer` once, as a gate outside the review, when the diff touches auth, input parsing, secrets, shell, network or deserialization.
- **Variants by request type.** Four variants, each with its own agents and a selector line: Bug, UI, Docs only, Research.

**Departure from ADR-0001.** ADR-0001 says OMC owns the workflow and this repo adds only gaps. This ADR adds routing rules on top of OMC: which agent runs, and under which condition. It replaces no OMC stage or skill. OMC still decides how each skill runs. The guardrails decide when an agent is in the chain.

**Text owners.** Each human-read text type has one owner. The owner applies `oh-my-claudecode:minimal-prose-discipline` and the cold-reader rule.

- `writer` (Haiku): documents people read (READMEs, ADRs, other docs), code comments, issue titles and descriptions, summaries. Comments get a rewrite pass after tests are green.
- Error strings stay with the code author. Tests written first assert them verbatim.
- `git-master`: commit messages (subject and body, with the issue reference).
- `/oh-my-claudecode:pr`: PR title and body.
- Chat replies stay with the main loop.
- `oh-my-claudecode:agent-doc-discipline` is narrowed to documents agents consume.

This replaces the earlier single `Prose:` line.

**Spikes rule** (instruction, not a hook). Answer a simple question by running a throwaway script, or a headless `claude -p --setting-sources project` run, in a scratch directory. Never run it in the repo or against real config, accounts or the tracker. Bound it by timeout and the cheapest model. Record the question, method and result in the spec. A question only a user or missing access can settle stays open.

**Self-review rule** (instruction, not a hook). Before the spec review and again before step 6, list every workflow item that applies. For each, say whether it was done and, if not, why. Go back to skipped items that still add value. Post the list on the issue.

**Hooks.** A rule becomes a hook when its trigger is a fact in tool input or git state, and a hook can carry its whole intent. A rule that needs judgment stays an instruction, because a hook would enforce a lookalike. The full rule-by-rule table lives in issue #7. Three new stdlib hooks, plus a squash reason in `merge_confirm.py`:

- `skill_gate.py`: context for `code-simplifier`, `git-master` and `security-reviewer`; asks on model-invoked `autopilot`.
- `bash_guard.py`: asks on commits or pushes to the default branch, commit subjects, branch names, force-pushes and tokens in commits, and the `approved` label.
- `secrets_guard.py`: denies `Read`, `Grep` and `Glob` on secret files; asks on `Bash` naming one.

### Hook results

- `skill_gate.py`: stage 2, shipped. Addendum below.
- `secrets_guard.py`: stage 3, shipped. Addendum below.
- `bash_guard.py`: stage 4, shipped. Addendum below.

#### Addendum at stage 2: `skill_gate.py`

**Shipped.** `config/hooks/skill_gate.py`, registered for `PreToolUse` (matcher `Skill`) and `UserPromptExpansion`, each entry with timeout 5. `merge_confirm.py` gives a squash flag its own ask reason. A short flag group holding `s` counts.

**Why two events.** A typed slash command fires only `UserPromptExpansion` (field `command_name`). A model-invoked skill fires only `PreToolUse` (field `tool_input.skill`). Spiked 2026-10-24 with headless `claude -p` in a scratch project.

**Behaviour.**

- On review (`review`, `omc-review`, `oh-my-claudecode:review`, `oh-my-claudecode:omc-review`), the hook prints `additionalContext` for each check that applies:
  - `code-simplifier`: the working tree diff against the merge-base with the default branch exceeds 300 changed lines.
  - `git-master`: the branch has `fixup!`, `squash!` or `amend!` commits, or WIP commit subjects.
  - `security-reviewer`: the diff touches one of six fixed categories: `auth`, `input`, `secrets`, `shell`, `network`, `deserialization`.
- Several hits give one combined message. No hit prints nothing.
- On `PreToolUse` only, a model-invoked `autopilot` asks. A typed `/autopilot` passes.

**Hardening.** A spike showed that a plain `git diff HEAD` in a repo whose config sets `core.fsmonitor` or `diff.external` runs those programs. Marker files appeared. The hook runs git:

- as `git --no-optional-locks -c core.fsmonitor=false -c core.hooksPath=/dev/null -c diff.external=`, with `--no-ext-diff` and `--no-textconv`;
- with every `GIT_*` variable dropped;
- by absolute path, on a sanitized `PATH`;
- with output capped at 64 KiB and one 5-second deadline;
- printing one fixed short code on stderr for an unexpected error.

`test_hooks_do_not_run_repo_config` fails when the hardened flags are removed.

**Real-harness run.** Headless `claude -p --model haiku --setting-sources project` in a scratch repo with a bare origin. The feature branch was about 400 lines over `main`, with a `fixup!` commit and a file named `auth_login.txt`. The real hook was registered.

- Model-invoked review and typed `/review` both delivered: "Review pre-check: the diff is 402 changed lines (over 300): run oh-my-claudecode:code-simplifier first; the branch has fixup or WIP commits: run oh-my-claudecode:git-master to clean the history first; the changes touch auth: run oh-my-claudecode:security-reviewer."
- Model-invoked `autopilot` was denied with the hook's reason. Headless, an ask becomes a denial.
- Typed `/autopilot` ran with no ask.

**Latency.** 20 direct runs of `skill_gate` on a review payload: median 52 ms, 95th percentile (p95) 66 ms, max 76 ms. Bar: p95 under 500 ms. Met.

**Known limits.**

- The fixup pattern has no trailing space, so it matches a superset of subjects. Harmless.
- The "git outlives the deadline" case is enforced in code. Only a wide-diff test exercises it, because the hook sanitizes `PATH` and a fake `git` cannot be injected.
- `ruff` is not installed on the owner's machine, so lint was not run. Issues #2 and #3 track the dev environment.

#### Addendum at stage 3: `secrets_guard.py`

**Shipped.** `config/hooks/secrets_guard.py`, registered for `PreToolUse` with matcher `Read|Grep|Glob|Bash` and timeout 5. Both host profiles list it.

**Secret files.** One definition serves all four tools:

- A file named `deny-terms` or `.env`.
- A file named `.env.<suffix>`, except suffixes `example`, `sample` and `template`. `.env.` with an empty suffix counts.
- `.envrc` is not a secret file.

**Read, Grep, Glob: deny.** The hook denies when a path-like field names a secret file. The fields are `file_path`, `path` and `glob`, plus a Glob `pattern`. A field is denied when:

- it names a secret file, or its real path does (symlinks resolved);
- it resolves to `~/.config/claude-config/deny-terms`, or to the directory that holds it. Only that directory counts, so a search over the home directory is not denied.

A Grep regex `pattern` is never scanned. Searching for `process.env.API_KEY` passes.

**Bash: ask.** The hook asks when a command token holds a secret name at its start, or right after `/`, a quote or `=`. `cat .env` and `--env-file=.env` ask. `process.env.API_KEY`, `.env.example`, `.envrc` and `environment.ts` pass.

**Hook mechanics.** The hook never opens a file named by its input. It resolves paths only. Reasons are fixed strings. An unexpected error prints one fixed stderr code. The deadline is a 5-second `SIGALRM`.

**Deviations from the approved spec text.** The owner accepts or rejects each at PR time.

1. The `=` boundary for Bash tokens is an addition. It makes `--env-file=.env` ask.
2. The glob rule is narrowed. A glob whose basename opens with `*`, `?` or `[` is never matched against the secret names. The literal rule denied the ordinary listings `Glob **/*` and `Grep glob *`. The hook was fed those payloads, and the fix was written test-first. Cost: wildcard-led patterns such as `*env` or `*.env` pass. Globs that open with a literal character (`.env*`, `.e*`, `.*`, `deny-t*`) still deny.

**Real-harness run.** Headless `claude -p --model haiku` in a scratch directory holding `notes.txt`, a `.env` with only fake text, and a symlink to that `.env`. The real hook was registered. Tool results were read from the stream, so a model refusal could not hide the hook.

- `Read notes.txt`: passed.
- `Read .env`: denied with "Secret files (.env, deny-terms) are off limits: do not read, search or list them."
- `Read` of the symlink: denied through its real path.
- Bash `cat .env`: asked, with "This command names a secret file (.env or deny-terms). Confirm you want it touched." Headless, an ask becomes a denial.
- `Grep` for a word, with `path` set to a directory holding a `.env`: passed, and listed the `.env` file name. This is the known gap below.

**Latency.** 20 direct runs on a `Read` payload: median 17 ms, p95 18 ms, max 18 ms. Bar: p95 under 500 ms. Met.

**Tests.** 537 pass at this stage.

**Known limits.**

- The `Grep` gap is open. The hook is not a `permissions.deny` rule, and it does not read file content. See addenda item 4.
- Wildcard-led globs pass (see deviation 2).
- Bash matching is per token. Quoting tricks and aliases get past it, as the consequences section already says.

#### Addendum at stage 4: `bash_guard.py`

**Shipped.** `config/hooks/bash_guard.py`, registered for `PreToolUse` with matcher `Bash` and timeout 5, as a second `Bash` group beside `merge_confirm.py`. Both host profiles list it. One process runs per Bash call. The file is 1,217 lines. Most of that is a single-pass shell lexer (quotes, escapes, `$(...)`, backticks, heredocs, here-strings, redirections), so that `git` and `gh` count only at command position. `echo git push origin main` and `grep "cd /tmp/x && git commit" notes` do nothing.

**Target repo.** The hook takes the repo from `git -C`, a leading `cd`, or the payload cwd, and applies `cd`, `checkout` and `switch` in order. When it cannot tell the target, it passes silently.

**Rules.** Every decision is an ask with a fixed reason for that rule.

1. Commit on the default branch, in a repo with an origin.
2. Push forms. A plain `push` and `push origin HEAD` resolve to the current branch. Asks on `HEAD:main`, `:main`, `--delete main`, `--mirror`, `--all`, `--prune`, a force push from the default branch, and `git branch -d/-D/-m/-M` naming it.
3. Commit subject must be a Conventional Commit ending in `(#N)`, `(owner/repo#N)` or `(KEY-N)`. Checked only on branches already named `type/{issue}-slug`. `chore(release):` is never asked.
4. New branch names (`git checkout -b`) must match `feature|fix|hotfix|docs|chore/{issue}-{slug}` in a repo with an origin. `improve/`, `experiment/` and `omc-team/` are exempt.
5. Secrets in commit content: secret-file names and anchored token patterns, on added lines only.
6. The `approved` label on `gh issue edit`, `gh issue create` and `gh api`.

**Hardening and tests.** The hook uses the same hardened git as the other hooks. It opens files with `O_NONBLOCK|O_NOFOLLOW`, accepts regular files only, and reads at most 64 KiB. A FIFO, `/dev/zero` and a symlink given to `-F` return within the deadline. One 5-second deadline covers the whole hook. Stderr prints one fixed code.

- Subject and branch patterns are copied from the lifecycle scripts. An AST parity test compares `CC_TYPES`, `SUBJECT_RE`, `ISSUE_REF_RE` and `TICKET_REF_RE` with those scripts, and a behavioural parity test runs both.
- `test_secret_file_definitions_agree` keeps `bash_guard` and `secrets_guard` equal.
- Mutation checks: removing `core.fsmonitor=false` fails the repo-config test; removing the `GIT_*` filter fails the env test.
- In-process tests cover a missing git and a git that outlives the deadline, through the `run_git` seam. This closes the deadline gap that stage 2 left.
- 916 tests pass after the review fixes (see the review section).

**Layering with OMC.** OMC's `git-guardrails` hook blocks every push, `branch -D`, `reset --hard`, `clean -f` and `checkout .` while ralph, autopilot, team or ultragoal is active, or when `OMC_GIT_GUARDRAILS=1`. `bash_guard` covers interactive sessions, default-branch commits, force-pushes and deletes of the default branch, subjects, branch names and tokens. The host profiles do not set `OMC_GIT_GUARDRAILS=1`, because it would block the lifecycle's own pushes. OMC's opt-in code-simplifier Stop hook stays off (item 6 below).

**Latency.** 20 direct runs in a temp repo with a bare origin:

- `git commit -m x`: min 33 ms, median 39 ms, p95 50 ms, max 52 ms.
- Non-git `ls -la`: median 28 ms, p95 31 ms.

Bar: p95 under 500 ms. Met.

**Real-harness run.** Headless `claude -p --model haiku` in a scratch repo with a bare origin and a fake `.env`, with the real hook registered. Tool results were read from the stream. Headless, an ask becomes a denial.

- Commit on `main`: denied, "This commit lands on the default branch...".
- Bad subject on `feature/7-x`: denied.
- `fix(x): y (#7)`: committed.
- `git checkout -b fix-thing`: denied.
- `git checkout -b improve/x`: passed.
- `git add .env && git commit`: denied, "holds 1 secret file name(s) and 0 token match(es)".
- `gh issue edit 1 --add-label approved`: denied before `gh` ran.
- `git push origin HEAD` on `main`: denied, nothing pushed.

**Known limits.**

- A `cd` inside a subshell still applies to the rest of the line. Subshell scoping is not modelled.
- Unextractable input passes. The deviations list gives the cases.
- The hook is large, 1,217 lines. The diff review should read it closely.

### Addenda (settled at stage 1, built at the stage named)

1. V1's hook ban on subprocesses (H1) is not carried. Hooks may start `git` with a fixed argv, no shell and a timeout. Stage 2, built (see the `skill_gate` addendum).
2. V1's "never blocks" bar is amended. Hooks may ask: `skill_gate`'s autopilot ask is the first example. `secrets_guard` may deny reads of secret files. Asks in headless runs are denials. Stage 2 (asks), stage 3 (deny) and stage 4 (asks on commits, pushes and labels) are built.
3. The 500 ms p95 latency bar per hook stays: 20 direct runs, p95 under 500 ms, recorded per hook. Stages 2, 3 and 4 measured (see the addenda). Met at each stage.
4. `secrets_guard` is a hook, not a `permissions.deny` rule. `cfg.py` deploys hooks, plugins and marketplaces only. A `Grep` over a directory that holds a `.env` is not covered. Stage 3 built and measured: the real-harness `Grep` passed and listed the `.env` file name (see the `secrets_guard` addendum). Open.
5. `bash_guard` layers on OMC's own `git-guardrails.mjs`. OMC blocks pushes while ralph, autopilot, team or ultragoal is active, or when `OMC_GIT_GUARDRAILS=1`. The host profiles do not set that variable. `bash_guard` adds interactive asks and the default-branch rules. Stage 4, built (see the `bash_guard` addendum).
6. OMC's opt-in `code-simplifier` Stop hook is not enabled. It simplifies changed files at every Stop. The rule is a size gate at review. Stage 2, built: `skill_gate` prints the review size check.
7. Issue #7 link: the commits that carried each stage. Stage 2: `764407d`, `0b03e95`, `f3032e7`. Stage 3: `c768eba`, `f3b9138`. Stage 4: `de39985`, `9f82222`. Its PR number is recorded when the PR opens.

## Deviations from the approved spec, for the owner to accept

The owner accepts or rejects each item at PR time. Items 4 to 11 are stage 4 deviations. Items 12 and 13 are not spec deviations; they are listed for the reviewer. Items 14 to 23 were recorded in the review phase. Each tag names the stage that built the code, or Review for a change the review made.

1. **[Stage 2]** The fixup pattern has no trailing space, so it matches a superset of subjects. Harmless.
2. **[Stage 3]** The `=` boundary for Bash tokens is an addition. It makes `--env-file=.env` ask.
3. **[Stage 3]** The glob rule is narrowed: a glob whose basename opens with `*`, `?` or `[` is never matched against secret names. Wildcard-led patterns such as `*env` pass.
4. **[Stage 4]** `bash_guard` reads untracked file contents in the broad scan (bounded, 1 MiB total, safe open). The broad scan covers `git add -A`, `git add .` or a directory, and an add plus commit in one command. `ls-files -mo` plus `git diff HEAD` never see a token in a new file.
5. **[Stage 4]** Broad-scan names come from the untracked listing plus `git diff --name-only --diff-filter=d`. A deleted `.env` does not ask.
6. **[Stage 4]** Shell keywords (`if then else do while until ! { time`) are skipped. `/usr/bin/git` counts as git.
7. **[Stage 4]** A target that cannot be determined passes silently: `GIT_DIR=`, `GIT_WORK_TREE=`, `env -C`, `--git-dir`, `--work-tree`, and paths holding `$` or backticks.
8. **[Stage 4]** `git branch -m` with no old name, while on the default branch, asks.
9. **[Stage 4]** Unextractable input passes: a first line over 200 characters, an unreadable `-F`, a piped `-F -`, and `--fixup`, `--squash`, `-C`, `-c` and editor messages.
10. **[Stage 4]** A `cd` inside a subshell still applies to the rest of the line. Known gap: subshell scoping is not modelled.
11. **[Stage 4]** Rule 6 counts `gh api` only with `-f`, `-F`, `--field` or `--raw-field` key labels, or `labels[]`. `gh pr edit --add-label approved` is not covered.
12. **[Not a spec deviation]** `tests/test_cfg.py` was edited outside the listed scope at stages 2-4, because it pinned the exact hook set.
13. **[Not a spec deviation]** `bash_guard.py` is 1,217 lines. It is a review surface that the diff review should read closely.
14. **[Stage 2-4]** The fragment timeout is 10 s on every hook entry, including `merge_confirm`, `host_default`'s SessionStart and SubagentStart. It sits above the hooks' 5 s internal deadline, so the harness cannot kill a hook just before it passes silently. The spec said 5.
15. **[Review]** The auth and session security patterns are word-bounded. The spec's literal pattern matched "author".
16. **[Review]** Filter overrides add `required=false`. With `required=true`, an empty `clean` makes the diff fail and the scans skip silently (see the review section).
17. **[Review]** Glob inputs that cannot be checked are denied: more than 16 brace alternatives or groups, and unresolvable paths.
18. **[Review]** Bash words such as `ls d*` or `cat .*` now ask, because they match deny-terms and `.env`.
19. **[Stage 3]** `secrets_guard` does not deny ancestors of the directory that holds `deny-terms`. A `Grep` over the home directory returns lines from it. The spec said "a directory that contains it".
20. **[Stage 2]** `skill_gate` does not count untracked files in the 300-line size.
21. **[Review]** The lifecycle skills' "Prose for people" line points to the owner list in `config/CLAUDE.global.md`. It does not name `writer`. Spec criterion 9 said each names `writer`.
22. **[Review]** The checkout/switch duplication in `bash_guard` was not refactored.
23. **[Stage 2-4]** Lint was not run. `ruff` is not installed on the owner's machine (issues #2 and #3).

## Review phase and fixes

The review ran once, after the four stages. It used four independent lanes. No lane ran again after the fixes.

| Lane | Reviewer | Result |
|------|----------|--------|
| Standards | `code-reviewer` | 0 critical, 3 warning, 5 note |
| Intent | `code-reviewer` | 0 critical, 2 warning, 4 note |
| Security gate | `security-reviewer` (one run) | BLOCK: 1 critical, 2 warning, 3 note |
| Agent-doc discipline | `critic` with `oh-my-claudecode:agent-doc-discipline` | 0 severe, 3 major, 2 minor |

Every real finding was fixed in commits after the review. The security critical was fixed first. Raised with the owner in the PR.

**Security critical.** A spike, run before the fix, confirmed it. Repo config still ran programs through git inside `skill_gate` and `bash_guard`:

- A `filter.<name>.clean`, `smudge` or `process` in repo config, plus a `.gitattributes` line, ran when the hooks diffed the working tree.
- `log.showSignature=true` with `gpg.program` ran a script when `git log` met a commit with a `gpgsig` header.
- A plain `git diff HEAD` also ran the filter.

The fix, in both hooks:

- Pass `-c log.showSignature=false`.
- List filter names with `git config --null --name-only --get-regexp ^filter\.`. Reading config runs nothing.
- Override each name's `clean`, `smudge` and `process` with an empty value, and set `required=false`.

Tests: marker-file tests for clean, smudge, process and gpg run for both hooks. Mutation checks: removing an override fails the clean and process tests. The hooks were then restored byte-identical. The planted-filter spike now shows the filter does not run from either hook. Plain `git` still runs it.

Cost: filters from global config, such as git-lfs, are also overridden. LFS-tracked text diffs as raw content and can raise `skill_gate`'s line count.

**Other fixes.**

- A timeout in `bash_guard` keeps the asks already found.
- A lone-surrogate path no longer makes `secrets_guard` fail open. It checks the basename before `realpath`. An unresolvable path denies.
- Brace globs and Bash words with `?` or `[` are matched.
- File opens use `lstat` and `S_ISREG` first.
- The alarm is disarmed before printing.
- The squash reason no longer reads words after the merge command. `merge_method=squash` on `gh api` counts.
- `git commit <paths>`, `--include` and `--only` are scanned.
- `git add` scans only added lines for tracked files.
- `git worktree add <path>` and `git branch -c/-C` get the branch-name check.
- A parity test keeps the duplicated git-runner constants of `skill_gate` and `bash_guard` equal.
- The lifecycle skills' "Prose for people" lines point to the single owner list in the global guardrails.
- The `code-reviewer` bullet states the 300-line threshold.
- The self-review rule runs once before the spec review and once before step 6.
- The `team` bullet names the agents that `team`'s own stages already run: `verifier` always, `security-reviewer` for auth or crypto, and `code-reviewer` for over 20 files or architectural changes. These thresholds come from OMC 5.7.13 and may drift.

**Latency after the fixes.** 20 runs each, with the filter configured and a dirty tracked file:

- `bash_guard`, `git commit -m x`: median 39 ms, p95 45 ms.
- `skill_gate`, review payload: median 34 ms, p95 38 ms.

Bar: p95 under 500 ms. Met.

**Open items.**

- The merge gate's broader false asks are tracked in issue #9.
- The rendered-string question is tracked in issue #8.

## Addendum: ralph and autopilot sessions run unguarded (#12)

When the session's first prompt starts `ralph` or `autopilot` (`/ralph`, `/oh-my-claudecode:autopilot` or the bare word), OMC runs its own workflow with nothing from this repo in the way. A word in the middle of a prompt, or an invocation in a later prompt, does not count.

- `CLAUDE.global.md` opens with a rule telling the model to ignore the whole block, including the host-default tracker line.
- All five hooks print nothing in such a session. Each reads the first user message from `transcript_path` (first 256 KB, stdlib) and treats anything unreadable as "not bypassed". The check is one function copied into each hook, because a hook runs with `python3 -I` and cannot import a sibling; a test asserts the copies are identical.
- This includes `secrets_guard`: in such a session `.env` and `deny-terms` reads are not denied. That follows the request for a complete bypass. OMC's own `git-guardrails` still blocks pushes while ralph or autopilot is active.
- The bare word must be followed by whitespace, a colon or the end of the text, in any case, so `ralph's loop is broken` and `ralph.py crashes` do not trigger. A first prompt that is another command (`/model`, `! git status`) or a compact summary is the first prompt; entries marked `isSidechain` are skipped.
- A subagent's hook payload carries the parent session's `transcript_path` (checked with a throwaway headless run), so a subagent prompt the model writes cannot trigger the bypass, and a bypassed session's subagents stay bypassed.
- Limits: `host_default` on a fresh SessionStart (`source: startup`) runs before any prompt exists, so only the rule text covers it. A trigger past the first 256 KB of the transcript is missed by the hooks while the model still applies the rule.
- Accepted: the check trusts the transcript file, which the model could edit, and the bypass lasts the whole session, also after `/cancel`. The hooks are already advisory (see Known limits); branch protection is the control that holds.

## Addendum: the Bash asks parse the command (#9)

`merge_confirm` and the Bash ask of `secrets_guard` scanned the raw command, so a command that only mentioned a merge or a secret file asked: `echo "gh pr merge 5"`, `git commit -m "docs: ignore .env files"`, `grep -n ".env" README.md`, a comment. Each false ask teaches people to click through the real one.

- **Shared parser.** Each hook carries a verbatim copy of `bash_guard.py`'s parser (`Word`, `Segment`, `Parser`, `command_words` and the constants they use), because each hook is deployed alone and runs with `python3 -I`. `test_hook_parser_copies_equal_bash_guards` compares the copies by `ast`, so it fails on any change to the code; comments are ignored. Hook-side wrappers skip the prefixes `sudo`, `doas`, `nohup`, `coproc`, `builtin`, `exec`, `time -p`, `timeout N`, `nice -n N`, `stdbuf`, `watch`, `xargs`, `GIT_DIR=` and `env -C`, and parse again the text that `bash|sh|zsh|dash|ksh -c`, `eval` and `env -S` run, a heredoc fed to a shell (`bash <<E`, `cat <<E | bash`) and echo or printf text before a bare shell (printf's `\n` and `\t` decoded). The wrappers are the same in both hooks; `test_hook_wrapper_copies_are_the_same_in_both_hooks` compares them the same way. `bash_guard.py` is unchanged.
- **`merge_confirm` asks at command position.** It asks for `gh [flags] pr [flags] merge`, and for `gh api` or `tea api` with a `/merge` endpoint operand (not a flag value such as `-f body=...`) or a merge mutation in its words or heredoc. Quoted text, heredoc bodies and comments of any other command never ask. The squash reason reads the parsed words. A 5-second deadline was added; past it the hook prints nothing.
- **`secrets_guard` Bash asks on the reader allowlist.** This replaces "a command token holds a secret name" (stage 3 addendum). It asks only when a secret path is an operand of a listed reader at command position: viewers, filters (the file, not the pattern), movers, archivers and dumpers, `git diff`, `git log -p` and `git show`, `source` and `.`, an input `<`, `docker --env-file`, and the file forms of `curl`, `wget`, `dd` and `xargs -a`. The value of `--exclude` (and `-x` for `diff` and `zip`) is not an operand. A `Parser` subclass keeps the `<` target that the copy drops. `X=.env cmd` now passes, and the ask reason reads "A listed reader in this command takes a secret file (.env or deny-terms). Confirm you want it read."
- **Silent on what the parser cannot model.** Nesting past `MAX_DEPTH` (32), with each re-parse counted, passes in both hooks, as in `bash_guard`.
- **Accepted misses, pinned by tests:** output redirections, `cd`, `ls`, `rm`, `vim`, `python3 x.py .env`, `git show HEAD:.env`, `echo .env | xargs cat`, `find -exec cat`, `cat $(echo .env)`, quoted `cat '.en?'`, and a `$(gh pr merge)` inside a heredoc body. `tea pulls merge` still does not ask. An unlisted reader gets past `secrets_guard`; both hooks stay reminders, not a security boundary.

## Consequences

- Every agent in `OMC_AGENTS` has a bullet. `test_every_omc_agent_has_a_pathway` fails when one loses it.
- Every `oh-my-claudecode:<name>` token must be in `OMC_AGENTS` or `OMC_SKILLS`. A stale name fails `test_agent_references_are_real`.
- `CLAUDE.global.md` grows by about 25 lines, to about 65. The line cap in `test_global_rules_stay_short_and_name_only_real_skills` moves from under 60 to under 80.
- The writer pass and the `git-master` calls add model calls to each change.

### Known limits

- **Hooks are advisory, not a security boundary.** Quoting tricks and aliases get past them. Branch protection on the remote is the control that holds.
- **The pinned roster needs a human bump when OMC changes its agent set.** Nothing detects a new OMC agent on its own. The bump updates `OMC_AGENTS` and the bullets together.
- **Judgment stays unchecked by script.** Whether a trigger is the right one, whether a variant double-spawns an agent a skill already calls, and prose quality are review items.
