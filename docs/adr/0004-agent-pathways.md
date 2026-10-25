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

- `skill_gate.py`: Addendum at stage 2 (real-harness run and p95 latency).
- `secrets_guard.py`: Addendum at stage 3 (real-harness run and p95 latency).
- `bash_guard.py`: Addendum at stage 4 (real-harness run and p95 latency).

### Addenda to come (settled now, built at the stage named)

1. V1's hook ban on subprocesses (H1) is not carried. Hooks may start `git` with a fixed argv, no shell and a timeout. Stage 2.
2. V1's "never blocks" bar is amended. Hooks may ask. `secrets_guard` may deny reads of secret files. Asks in headless runs are denials. Stage 2 (asks), stage 3 (deny).
3. The 500 ms p95 latency bar per hook stays: 20 direct runs, p95 under 500 ms, recorded per hook. Stages 2-4.
4. `secrets_guard` is a hook, not a `permissions.deny` rule. `cfg.py` deploys hooks, plugins and marketplaces only. A `Grep` over a directory that holds a `.env` is not covered. Stage 3.
5. `bash_guard` layers on OMC's own `git-guardrails.mjs`. OMC blocks pushes while ralph, autopilot, team or ultragoal is active, or when `OMC_GIT_GUARDRAILS=1`. The host profiles do not set that variable. `bash_guard` adds interactive asks and the default-branch rules. Stage 4.
6. OMC's opt-in `code-simplifier` Stop hook is not enabled. It simplifies changed files at every Stop. The rule is a size gate at review. Stage 2.
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
