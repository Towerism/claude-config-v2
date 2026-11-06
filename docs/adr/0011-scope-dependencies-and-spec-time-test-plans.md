# ADR-0011: Build exactly the spec, keep the complexity to own small, and plan the tests with the spec

**Status:** Accepted by the owner on 2026-11-06, issue #54 (revision 5 of its spec). Amends ADR-0006 (the dropped test-plan rule, and when OMC text counts as coverage) and ADR-0009 (an operating-principles section, a fourth guardrails section, scenarios 14-17 and a context-limit note).

## Context

The owner wants the agent held to three principles:
1. **YAGNI.** Build what the user asked for, nothing more and nothing less.
2. **Dependencies.** Use as many dependencies as it takes to keep complexity low, while keeping quality, correctness and accuracy high. Code that ships to a browser client is the exception: its bundle size counts too.
3. **Test planning at spec time.** `test-engineer` plans the tests while the spec is written.

ADR-0001 listed "`test-engineer` plans the tests before the spec is written" as a gap. ADR-0006 dropped it by mistake as "OMC's choice", and `docs/gap-analysis.md` marked it "Covered". No OMC planning skill (`deep-interview`, `ralplan`, `plan`) calls `test-engineer`. OMC's `tdd` says that outside `launch`, seams are agreed with the user "before the first test exists — a seam nobody approved gets no tests".

ADR-0006 also kept the block short by not restating anything OMC says. That works only if OMC's skills load. A search of 1,387 session transcripts (2026-10-24 to 2026-11-06, subagents included) counted how often each skill was loaded:

| Skill | Loads |
|---|---|
| `tdd` | 0 |
| `minimal-code-discipline` | 0 |
| `review` | 3, plus 3 typed |
| `execute` | 3 |
| `verify` | 7 |
| `ralplan` | 7 |
| `deep-interview` | 18, plus 4 typed |
| `github-issue-lifecycle` | 76 |

So `tdd` 0 and `minimal-code-discipline` 0: their guidance never reached the model. The modes the owner types most, `autopilot`, `ralph` and `ultragoal`, run their own phases. `deep-interview` and `ralplan` don't run for every ticket either, because a detailed ticket can go straight to a spec.

## Decision

1. **OMC text counts as coverage only if the skill runs.** OMC's skills hold useful guidance, so the block keeps using them, but it names the moment each one loads, in every mode, instead of restating it. Where a skill already runs when needed, the block says nothing.
2. **Operating principles** open the block, before the guardrails:
   - A cheap spike settles an open question of fact right away. It runs in a scratch directory and is never committed, so it is not the code change the approval gate covers.
   - Candidate dependencies are researched with `/oh-my-claudecode:research`, not recalled from memory.
3. **Spec-time test plan.** A spec that changes code carries a seam list from `test-engineer`, planned without writing any file, so approving the spec approves the seams. A spec that changes no code marks the test plan `skipped:`.
   - It is enforced at the one step every tracked spec passes: step 4 of each lifecycle skill. `spec-check` refuses to store a spec without a seam list or a reasoned `skipped:` line.
   - The `spec-test-plan` quality gate blocks the same gap inside `deep-interview` and `ralplan`.
4. **Scope and dependencies.**
   - Build every spec item and nothing outside it.
   - Pick the correct option with the least complexity to own: your own code plus each dependency's upkeep. For browser code, also count bundle size.
   - Name each new dependency in the spec. A dependency found mid-build sends the spec back for approval.
   - Before any code is written, `tdd` and `minimal-code-discipline` load and apply to all of it. A dependency named in the approved spec counts as approved under `minimal-code-discipline`'s "requested or approved".
5. **Review and verify.**
   - Before the work is reported done, `/code-review` reviews the diff and `verify` runs, in parallel. OMC's `review` is for plans, not diffs.
   - Work outside the spec or under its Non-Goals is a `scope:` finding, not a defect.
   - An abstraction is asked for only when it makes the code easier to read or maintain.
   - The lifecycle `pr-body-check` requires a `Spec check:` line in the PR's review section.
   - The advisory `spec-scope` gate checks a plan against the spec both ways when OMC's `review` reviews it.
6. **Quality gates** come from `config/omc.fragment.json`. `cfg.py` merges only its `qualityGates` key into OMC's user config (`$XDG_CONFIG_HOME/claude-omc/config.jsonc`), records the previous value in `state.json`, and undoes it on rollback. A file with comments stops the deploy, and nothing is written.

The block's bullets cover repos with no tracker. The lifecycle checks cover every tracked spec and PR. The gates catch the gap inside OMC's own stages.

## Consequences

- ADR-0003 is unchanged: skill scripts stay standard-library only. #55 decides whether skills may declare dependencies, and #56 covers the Gitea skill's copied script.
- Nothing checks that `tdd` or `minimal-code-discipline` actually loaded. Rerunning the transcript count measures it.
- The gates fire from each OMC stage skill's own text, not from a hook, so they fire only when that stage runs.
- `tests/test_repo.py` pins each new bullet in its section, the block's shape and the bullets' order. `tests/test_gates.py` and `tests/skills/` cover the gates and the lifecycle checks.
