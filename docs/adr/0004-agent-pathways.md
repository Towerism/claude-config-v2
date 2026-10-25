# ADR-0004: Every OMC agent gets a pathway through the guardrails

**Status:** Accepted by the owner on 2026-10-24, issue #7. This is the first version (stage 1 of 4). Stages 2-4 add addenda.

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

**Self-review rule** (instruction, not a hook). Before any review agent runs, list every workflow item that applies. For each, say whether it was done and, if not, why. Go back to skipped items that still add value. Post the list on the issue.

**Hooks.** A rule becomes a hook when its trigger is a fact in tool input or git state, and a hook can carry its whole intent. A rule that needs judgment stays an instruction, because a hook would enforce a lookalike. The full rule-by-rule table lives in issue #7. Three new stdlib hooks, plus a squash reason in `merge_confirm.py`:

- `skill_gate.py`: context for `code-simplifier`, `git-master` and `security-reviewer`; asks on model-invoked `autopilot`.
- `bash_guard.py`: asks on commits or pushes to the default branch, commit subjects, branch names, force-pushes and tokens in commits, and the `approved` label.
- `secrets_guard.py`: denies `Read`, `Grep` and `Glob` on secret files; asks on `Bash` naming one.

### Hook results

- `skill_gate.py`: stage 2, shipped. Addendum below.
- `secrets_guard.py`: stage 3, shipped. Addendum below.
- `bash_guard.py`: Addendum at stage 4 (real-harness run and p95 latency).

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

### Addenda to come (settled now, built at the stage named)

1. V1's hook ban on subprocesses (H1) is not carried. Hooks may start `git` with a fixed argv, no shell and a timeout. Stage 2, built (see the `skill_gate` addendum).
2. V1's "never blocks" bar is amended. Hooks may ask: `skill_gate`'s autopilot ask is the first example. `secrets_guard` may deny reads of secret files. Asks in headless runs are denials. Stage 2 (asks) and stage 3 (deny) are built.
3. The 500 ms p95 latency bar per hook stays: 20 direct runs, p95 under 500 ms, recorded per hook. Stages 2 and 3 measured (see the `skill_gate` and `secrets_guard` addenda); stage 4 to come.
4. `secrets_guard` is a hook, not a `permissions.deny` rule. `cfg.py` deploys hooks, plugins and marketplaces only. A `Grep` over a directory that holds a `.env` is not covered. Stage 3 built and measured: the real-harness `Grep` passed and listed the `.env` file name (see the `secrets_guard` addendum). Open.
5. `bash_guard` layers on OMC's own `git-guardrails.mjs`. OMC blocks pushes while ralph, autopilot, team or ultragoal is active, or when `OMC_GIT_GUARDRAILS=1`. The host profiles do not set that variable. `bash_guard` adds interactive asks and the default-branch rules. Stage 4.
6. OMC's opt-in `code-simplifier` Stop hook is not enabled. It simplifies changed files at every Stop. The rule is a size gate at review. Stage 2, built: `skill_gate` prints the review size check.
7. Issue #7 link: stage 4 records the PR numbers that carried each stage.

## Consequences

- Every agent in `OMC_AGENTS` has a bullet. `test_every_omc_agent_has_a_pathway` fails when one loses it.
- Every `oh-my-claudecode:<name>` token must be in `OMC_AGENTS` or `OMC_SKILLS`. A stale name fails `test_agent_references_are_real`.
- `CLAUDE.global.md` grows by about 25 lines, to about 65. The line cap in `test_global_rules_stay_short_and_name_only_real_skills` moves from under 60 to under 80.
- The writer pass and the `git-master` calls add model calls to each change.

### Known limits

- **Hooks are advisory, not a security boundary.** Quoting tricks and aliases get past them. Branch protection on the remote is the control that holds.
- **The pinned roster needs a human bump when OMC changes its agent set.** Nothing detects a new OMC agent on its own. The bump updates `OMC_AGENTS` and the bullets together.
- **Judgment stays unchecked by script.** Whether a trigger is the right one, whether a variant double-spawns an agent a skill already calls, and prose quality are review items.
