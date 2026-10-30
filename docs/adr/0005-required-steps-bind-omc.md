# ADR-0005: Required steps bind OMC's lightest-path principle

**Status:** Accepted by the owner on 2026-10-25, issue #14. Superseded by ADR-0006.

## Context

OMC's operating principles say "Choose the lightest-weight path that preserves quality." On #12 the model used that principle to skip the interview, the test plan, the analyst pass, the self-review, the spec review and the review notes. The user approved the spec without knowing. ADR-0001 made OMC the base and ADR-0004 added routing rules on top of it; neither says which wins when a rule here meets that principle.

## Decision

1. **Precedence.** `config/CLAUDE.global.md` states that its requirements override OMC's "lightest-weight path" principle. The principle governs only how a step is carried out where the block is silent. Only the user can waive a step.
2. **Required vs advisory.** Waivable steps are tagged `(advisory: <id>)`; an untagged step is required. Advisory ids: `interview`, `analyst`, `docs-lookup`, `test-plan`, `history-cleanup`, `simplifier`, `qa`, `design`. Required: `self-review`, `spec-review`, `review-notes`, `tdd`, `diff-review`, `security-gate`, `verify`, and `repro` for the bug variant. A test keeps the tags equal to the sets in the lifecycle script.
3. **Path declaration.** After the claim, the lifecycle skill asks once "Review the proposed pipeline?", a plain yes or no that lists no skipped steps. Yes opens a wizard that shows the proposed path. No lets the model skip advisory steps it judges fit, each recorded as a waived line citing the No answer. Required steps are never skipped. The declaration is shown at spec approval.
4. **Record.** The user's answers are posted verbatim as issue comments. The declaration is one issue comment between `<!-- path-declaration v1 -->` markers with `run`, `waived` and `n/a` lines. Jira strips HTML comments from stored comments, so the Jira skill fences it with `path-declaration:start` and `path-declaration:end` lines instead (#29).
5. **Check.** `declaration-check` in each lifecycle script runs before `approved` is set and again at PR time, where a pass leaves a stamp holding the branch, issue and HEAD.
6. **Hook.** `bash_guard.py` asks on `gh pr create` unless the stamp names the current branch and HEAD. It asks rather than denies because every `bash_guard` decision is an ask. A `ralph` or `autopilot` session (#12) is bypassed and never reaches any of this.
7. **Self-review.** The "otherwise say why not" exit in the self-review rule applies to advisory steps only.

## Departure

ADR-0001 says OMC owns the workflow and this repo adds only gaps. ADR-0004 adds routing on top of OMC. This ADR goes one step further: the guardrails now bind OMC's own principle, and a hook extension (the `gh pr create` ask) enforces part of it.

## Limit

The check verifies that every cited URL is a comment on the issue by the authenticated login and that a waiver's quote appears in the cited answer comment. It cannot prove that a step ran. A model that writes the comments itself, including a fake user answer, goes undetected. The hook only asks, like the other hooks (ADR-0004, known limits). It gates only `gh pr create` and `gh pr new`, also behind `-R`/`--repo`; a pull request opened on Gitea (`tea api ... POST .../pulls`) or through `gh api .../pulls` is not gated. An `n/a` fact for a conditional step is unverifiable: the check reads it and cannot test it. Branch protection and the user's review of the declaration at approval are the controls that hold.
