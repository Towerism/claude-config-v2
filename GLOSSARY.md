---
documentLanguage: en
---

# Glossary

One entry per term: definition, boundaries, one resolved ambiguity. Write here the moment a term is settled. Vocabulary here is law for specs, tickets and code naming. Ship-specific terms only: a concept any sea chart carries does not get an entry.

## Auto sync
- Definition: the deploy `auto_sync.py` runs at the start of each new session: it fetches `main` from `origin` into the sync clone, fast-forwards it and runs its `cfg.py deploy --yes --force` for the recorded host (ADR-0007).
- Boundary: only `main`, only fast-forwards, only on `startup`; never the user's working checkout. A failure logs a reason in `sync.log` and warns the user; a deploy that fails midway is rolled back. `"autoSync": false` in `local.json` turns it off.
- Avoid: "auto-update" (that is Claude Code's plugin update, which it does not replace).
- Resolved ambiguity: the sync clone is the dedicated clone of `main` that `cfg.py deploy --yes` makes from `origin` in `$XDG_DATA_HOME/claude-config` and records as `syncClone` in `state.json`. A manual deploy, a hand edit or a rollback holds only until the next new session unless auto sync is off; an overwritten hand edit survives only in the last five backups.

## Default tracker
- Definition: the issue tracker `host_default.py` names at session start for the current repo, with its source: a `jira.project` key in the repo's git history, then its `origin` remote, then the host profile's `defaultTracker` (ADR-0006).
- Boundary: the repo's own CLAUDE.md overrides it; a top-level `defaultTracker` in `local.json` is ignored.

## Edit pass
- Definition: the one call a session makes to the `human-prose-editor` agent with a batch of texts people read, the texts leaving the session at the same step (committed, posted, sent, or handed to the user to post), just before they leave (ADR-0016). The agent returns line-range replacements, and the session applies each range only if it keeps every number, name, identifier, link, code span and hedge word.
- Boundary: the writer owns what the text says and checks it against its sources; the editor owns only wording, shape and register and never sees the sources. The session that sends the text runs the pass, a subagent included; nobody edits text after it left.
- Avoid: "review" or "check" for it (it changes wording, it does not approve anything).

## Global memory
- Definition: the memories and learned skills that `global_memory.py` syncs between machines through a private git repo named by `memory.repo` in `local.json`, kept in the store, a clone at `$XDG_DATA_HOME/claude-memory` where top-level `<name>.md` files are memories and `skills/` holds learned skills (ADR-0015). It syncs during the session: at session start, before and after each read, write or edit of a file in the store, at session end as a backstop and, at most once a minute, on a prompt.
- Boundary: only a memory that holds in any repo on any machine belongs there; anything naming a project, client or employer stays in project memory, which this never syncs. The hook is off until `memory.repo` is set. The hook never commits a file whose name or text holds a line of `deny-terms`, and nothing that names a term is pushed; without a usable `deny-terms` it commits and pushes nothing.
- Avoid: "project memory" for it (that is Claude's per-repository memory, left unchanged).
- Resolved ambiguity: the store lives under `$XDG_DATA_HOME`, outside the Claude home, because Claude Code refuses writes there; the public repo carries the mechanism and never a memory.

## Guardrails
- Definition: the marked block in `config/CLAUDE.global.md`, written for Anthropic models only (ADR-0012); each rule states something no OMC text, skill or hook already states (ADR-0006, ADR-0008, ADR-0011, ADR-0012).
- Boundary: a rule already stated by OMC, a skill or a hook is not repeated there; the guardrails never choose OMC's stages, agents or runner. OMC text counts as coverage only if the skill runs; otherwise the guardrails name when to load it (ADR-0011).
- Resolved ambiguity: ADR-0006 amends ADR-0001's gap list; approving the spec, marking a PR ready and merging, each on the user's word, are the only fixed rules (ADR-0008).

## Handoff note
- Definition: the file `.omc/handoffs/<session id>.md` a session writes at a stage boundary or past the context limit, following the `session-handoff` skill (ADR-0019). Once it exists, `handoff_stop.py` types `/clear` and a prompt naming it into the session's tmux pane, or in a `claude --bg` job starts a new background job with that prompt, once per note.
- Boundary: written only in an interactive session inside tmux or in a background job, and never while ralph or autopilot runs. The fresh session reads it because the prompt names it; nothing injects it.
- Avoid: "handoff" alone for the file (a handoff is the whole step from this session to the fresh one); the stage files OMC's `team` skill writes to `.omc/handoffs/` are a different thing in the same folder.

## Host profile
- Definition: `hosts/<name>.json`, naming the skills, hooks, plugins, marketplaces and `defaultTracker` one machine gets (ADR-0002).
- Boundary: is the only per-machine file in the repo; machine-only values (Jira project and site) live outside it, in `~/.config/claude-config/local.json`, which no longer overrides `defaultTracker`.
- Avoid: "environment", "config set".
- Resolved ambiguity: profiles differ only in `name` and `defaultTracker`; a test fails otherwise.

## Pipeline declaration
- Definition: the list shown with a spec at approval of every OMC stage that could run for the change, each marked `will run` or `skipped: <reason>`; approving the spec acknowledges it (ADR-0006).
- Boundary: an instruction only; nothing checks it, and it asks no separate question.

## Scope finding
- Definition: a review or verify finding, marked `scope:`, for work in the diff that is outside the approved spec or under its Non-Goals; the `spec-scope` diff gate reports them too (ADR-0011).
- Boundary: not a defect. It asks to remove the work or move it to a follow-up issue, and never to grow the spec.

## Seam list
- Definition: the per-seam test plan `test-engineer` puts in a spec before it is shown, without writing any file; the `spec-test-plan` gate blocks a spec without one at `deep-interview` and `ralplan` (ADR-0011, ADR-0014).
- Boundary: sized to the risk, not to a ratio. A spec that changes no code has none and marks the test plan `skipped:` with the reason.
- Resolved ambiguity: approving the spec approves its seams, which are the seams OMC's `tdd` agrees with the user before the first test.
