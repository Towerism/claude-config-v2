# ADR-0017: Trim global rules that OMC already covers, and record the November 12 rewrite

**Status:** Accepted 2026-11-24, issue #90. Amends ADR-0011 (decisions 4 and 5), ADR-0012 (decision 2, the approval anchor), ADR-0013 (decisions 2 and 3) and ADR-0014 (decision 5).

## Context

Commit 6189b22 ("feat(CLAUDE.global.md): improvements", 2026-11-12) rewrote `config/CLAUDE.global.md` without an ADR. It:

- dropped "a new feature, or a change spanning more than one component, starts with `/oh-my-claudecode:deep-interview`";
- dropped the pipeline list (each OMC stage shown with the spec, marked `will run` or `skipped:`);
- dropped the ralplan hand-off (save an approved spec as `.omc/plans/ralplan-<slug>.md` before `autopilot`);
- dropped "run `/oh-my-claudecode:review` on the diff and `/oh-my-claudecode:verify` in parallel before reporting work done";
- dropped "build every item in the approved spec and nothing outside it";
- made plan approval conditional on the plan holding a decision a human would find surprising;
- restored "pick the correct option with the least complexity to own", the wording ADR-0013 had replaced with "least own code wins".

The rules still referred to the dropped pipeline list ("`skipped:` with the reason in the pipeline list").

A review of the rules against OMC 5.8.6 found more rules that restate OMC's own skills. Paths below are relative to the OMC plugin directory.

## Decision

1. **The 6189b22 removals stand.** Deep-interview-first, the pipeline list, the ralplan hand-off, review-plus-verify and build-exactly-the-spec stay out of the rules. OMC's workflows choose their own stages.
2. **"Least complexity to own" goes again.** The "Least own code wins" rule and the dependency-naming rule under `### Dependencies and tests` already carry it, in ADR-0013's wording.
3. **"Do not rely on your memory or context alone" merges into the check-at-the-source rule,** which now covers technical decisions and names spikes, experiments and external research as the check.
4. **Plan approval reads one way.** The user approves the final plan before code is written when it contains a decision a human would find surprising; otherwise OMC's own `pending approval` stop covers plan approval (`skills/plan/SKILL.md:166`). Marking a PR ready and merging stay the user's.
5. **An AskUserQuestion option counts as approval,** recorded by quoting the option label; typed approval is quoted as typed. OMC's plan skill takes approval through that prompt and says never to ask for it in plain text (`skills/plan/SKILL.md:128,166`).
6. **The dead "in the pipeline list" reference goes;** a plan that changes no code still marks its test plan `skipped:` with the reason.
7. **Edge cases:** only "leave an unhandled edge case out and say why in the spec" stays. `skills/minimal-code-discipline/SKILL.md:30,56` already asks whether code needs to exist and rejects speculative generality.
8. **Tests:** the linter clause and the `Not tested, and why` list stay. "Drop a test that repeats the code line by line" goes: `skills/tdd/SKILL.md:20` calls such a test "a mirror, not a check".
9. **Off-plan work:** only the `out of scope:` label stays. OMC review's intent axis already reports missing requirements and behaviour nobody asked for (`skills/review/SKILL.md:36`).
10. **A repo's own CLAUDE.md may say its PRs open ready.** In that repo the line stands for the user's decision to mark them ready.
11. **Skill listing budget:** `config/settings.fragment.json` sets `SLASH_COMMAND_TOOL_CHAR_BUDGET` to `45000`. The skill listing measured 39,825 characters against the 30,000-character budget Claude Code applied; a headless run with this value showed no "Skill listing over budget" warning, and the margin leaves room for a few new skills.

## Consequences

- Nothing in the rules asks for review and verify before work is reported done; that rests on the OMC workflow in use.
- The `spec-test-plan` gate and `GLOSSARY.md` still mention the pipeline list; a follow-up change for #90 handles them.
- Every session pays for the larger skill listing in context.
