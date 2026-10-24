# What V1 had, what OMC covers, what V2 keeps

Compared on 2026-10-24 against V1 (`claude-config`, 24 skills, 9 overlays, 3 hooks, the `cfg` tool) and OMC 5.7.13. "Covered" means an OMC skill or agent does the same job well enough that V1's piece would only duplicate it.

## Pipeline stages

| V1 stage | V1 skill | OMC equivalent | V2 |
|---|---|---|---|
| Design | `senior-architect` | `/drydock`, `/ralplan`, architect agent | Covered |
| Start | `github-`, `gitea-`, `jira-…lifecycle` | Partial: `launch`, `harbor`, `drydock` (GitHub only), `project-session-manager` (worktrees for GitHub, Jira, Gitea issues), `ask-navigator`. None claims an issue, records an approval mode, stores the spec on the issue or merges and closes out | **Kept** as one `issue-lifecycle` skill; boundary with those skills is in `CLAUDE.global.md` |
| Spec | `spec-driven-workflow` | `/deep-interview`, `/ralplan` | Covered; approval rules kept as guardrails |
| Test plan | `senior-qa`, `api-test-suite-builder`, `ci-cd-pipeline-builder` | `/tdd`, test-engineer agent | Covered |
| Implement | `tdd-guide` | `/tdd`, `/execute` | Covered |
| Review | `adversarial-reviewer` | `/review`, critic and code-reviewer agents | Covered; "one pass, never re-run" kept as a guardrail |
| Merge | `ship-gate` | `/verify`, `/pr` | Covered; the merge hook kept |

## Everything else

| V1 piece | Decision | Why |
|---|---|---|
| `merge_confirm.py` hook | Kept unchanged | A merge once happened without the owner's click; OMC has no equivalent |
| `lifecycle_default.py` hook | Replaced by `host_default.py` | Same job (state the machine's default tracker), simpler state, renamed for trackers |
| `skill_overlay.py` hook, 9 overlays | Dropped | Overlays existed to bend vendored skills; V2 has none. Guardrails live in `CLAUDE.global.md` |
| Approval modes, git conventions, split rules | Kept as `CLAUDE.global.md` guardrails | OMC doesn't state who may approve or merge |
| `plain-prose`, `writing-docs` (with lint scripts) | Merged into one markdown `writing-docs` | OMC's `minimal-prose-discipline` covers chat replies and `agent-doc-discipline` covers documents agents consume; neither covers commit, PR, issue and README text for people. `writing-docs` wins for that text. Scripts dropped by DP2 |
| `fresh-session-handoff` | Kept | OMC's `launch` posts handoffs as tracker comments and `ultragoal` prints `/goal` text, but nothing writes a cold-start note for an arbitrary session. During a `/launch` run, launch's handoff wins |
| `linux-troubleshooting` | Rewritten | V1's version pointed at skills that aren't installed; V2's is self-contained |
| Vendored skills (17, upstream copies) | Dropped | Copies drift and need a vendoring process. Some (`database-schema-designer`, `migration-architect`, `api-design-reviewer`) have no OMC equivalent; add one back as a markdown skill when a task needs it |
| `skill-security-auditor`, `skill-tester` | Dropped | Not used since V1 shipped |
| `cfg` tool (7,000 lines: releases, capture, eval, lock) | Replaced by `tools/cfg.py` (about 250 lines) | Copy-based deploy with backups and rollback is enough for two machines |
| `skill-creator` and `claude-md-management` plugins | Not enabled | OMC's `skill`/`skillify` cover skill authoring; add them to `plugins` in a host profile if wanted |
| Eval harness, plugin lock, ADR-gated CI | Dropped for now | Revisit if a hook or skill regresses; tests cover the plumbing |
| `git_hooks.py` (deny-terms, secrets, identity checks) | Not ported yet | Open: see `docs/adr/0001` consequences |
| Mermaid, runbook, history docs | Dropped | V2 starts fresh |

## Open assumptions

These guesses stand in for answers nobody was available to give. Veto any of them.

1. **Repo location and name.** V2 lives in a sibling directory, `claude-config-v2`, not a rewrite in place.
2. **Git hooks not ported.** V1's commit and push checks (private-word list, secrets, noreply identity) aren't in V2. If you want them, they belong in `tools/` with `gitleaks` as the dependency.
3. **Jira commands unverified.** V1 drove Jira through a script; V2 documents the `jira` CLI directly and has not run it against a live Jira.
4. **Copy, not symlink.** V1 recorded evidence on symlinked deploys; V2 copies files, which costs a re-deploy after each edit but avoids that question.
5. **Merge guard is best-effort.** `merge_confirm.py` catches `gh pr merge`, `gh api` and `tea api` merges; aliases, quoting tricks and `curl` get past it. Use branch protection for a hard stop.
6. **Plugins are only added.** A deploy enables a host's plugins; it never disables one removed from a profile.
7. **OMC is not version-pinned.** Both machines track the marketplace's default branch; V1's `plugins.lock.json` is dropped. Add a git `ref` to the marketplace source in the host profiles to pin.
