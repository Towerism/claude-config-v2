# ADR-0016: One edit pass for every text a person reads

**Status:** Accepted 2026-11-22, issue #76. Shipped in PR #77 and being tried in use, although several of its evaluation bars were missed (see Results). Amended 2026-11-25 by ADR-0018: `human-prose-writer` now loads before any text people read is written (decision 1), and issue and ticket bodies are written with it (decision 7).

## Context

Agents write commit messages, PR descriptions and reviews, issues, tickets, ADRs, READMEs, chat messages and wiki pages. People read all of them. A first design gave the writing session one skill with every rule, from what goes in to how it should sound. In blind tests its edits read close to human text, but texts it wrote from facts still read as AI-written (P(AI) 49.5 under an Opus judge, against about 10 for human originals). The premise of this design is that an agent told to sound human while it writes ends up sounding like an imitation. The results below do not bear that out for text that agents write.

The writer keeps a few rules about accuracy. A separate pass, run once on each batch of outgoing text by a small model that sees only the skill and the texts, edits wording, shape and register.

The design was tested blind, outside this repo, on 24 held-out human texts from small, little-known repos and Jira projects written before December 2022. Fresh judge agents scored each text alone, with names anonymised. They rated how likely each text is to be AI-written (Opus and Sonnet), whether it has invented, dropped or wrong facts against the sources, and whether the reader gets what they need. Real Claude Code sessions ran in scratch Claude homes deployed with `cfg.py`, with the OMC plugin installed.

## Results

Each condition ran in one blind run, on 24 held-out texts. P(AI) is a judge's 0 to 100 estimate that a text is AI-written; human originals score about 10 (Opus judge) and 13 (Sonnet judge). "Texts with errors" counts texts with at least one invented, dropped or changed fact.

| Condition | P(AI), Opus / Sonnet judge | Texts with errors, Opus / Sonnet judge |
|---|---|---|
| Human drafts after the edit pass | 12.6 / 16.2 | 5 / 7 |
| Human drafts edited by Opus with the first design (earlier run) | 18.9 / 18.7 | 7 / 17 |
| Opus writes from facts with the writer rules only | 63.4 / 48.5 | 13 / 12 |
| The same texts after the edit pass | 63.6 / 45.0 | 12 / 13 |
| Opus writes from facts with the first design's skill | 49.5 / 32.6 | 12 / 6 |

- On human drafts the Haiku pass reads closer to human, and changes fewer facts, than the Opus edits of the first design's earlier run. Under the Opus judge it dropped 2 stated reasons (a "since" and a "so") against a bar of 1; the Sonnet judge found none. The sending session's fact gate does not check connectives.
- On text Opus wrote, the editor returned `UNCHANGED` for 15 of 24 texts, and the pass barely changed how AI-like they read. Writing with the first design's skill read clearly less AI-like. The plan's bar was edited text less AI-like than that on at least 15 of 24 texts; it was 6 (Opus judge) and 4 (Sonnet judge). Under the Sonnet judge the writer rules alone also gave more texts with errors than the first design's skill (12 against 6); the Opus judge saw no difference.
- The drafts came from the main Opus session. Drafts from the OMC writer agent were not measured.
- Bars missed: dropped stated reasons on human drafts (Opus judge), texts with errors on written text (Sonnet judge), edited text less AI-like than the first design's skill (both judges), edited text less AI-like than unedited (Opus judge), and ranges applied in mixed batches.
- In mixed batches of 3 to 4 texts, all 41 returned ranges were valid and none landed in another text. The gate skipped 3, each of which had dropped a name, an identifier or a code span's backticks, so 38 of 41 (93%) were applied against a bar of 95%. In the real sessions the editor also once labeled a range one line short (the session sent that text unedited), and the writer agent once reported an `UNCHANGED` reply as a skipped pass.
- In real sessions, 12 of 12 called the editor without being told to, 4 of 4 delegated sessions (executor, git-master, writer, a chain of commits) ran exactly one pass per batch, and 0 of 2 control sessions called it. The editor ran on Haiku when a subagent called it. The edit pass caused no permission prompt or denial.

## Drivers

- The pass runs on every batch without being asked, from the main session or a subagent.
- No fact, name, link, number, hedge or stated reason lost in an edit, by an editor that cannot see the sources.
- No permission prompt and no new runtime mechanism: a native agent call and one markdown file to deploy.
- The editor's context holds the skill and the texts, and as little else as the platform allows, at a cost low enough for every commit.

## Alternatives considered

- **The skill in the writing session (the first design).** Edits read close to human text, but written text stayed AI-like, and it needed a trigger line naming 13 kinds of text. In the same run as the edit pass, its written texts read less AI-like (P(AI) 49.5 / 32.6 against 63.6 / 45.0).
- **A nested `claude -p --model haiku`** with `--setting-sources ""`, `--strict-mcp-config`, `--tools ""`, `--disable-slash-commands` and `--system-prompt-file`. Its context was 641 tokens against the agent's 4k to 8k (16k for one large batch), and one allow rule would remove its Bash prompt. Not chosen: those flags are CLI surface rather than a contract, and a change in a later version could silently bring CLAUDE.md back. It stays the fallback.
- **`--bare`.** Needs an API key; sessions here sign in with a subscription.
- **Whole-text or sentence-pair edits.** No line addresses for the sending session to check, so a dropped fact would pass.
- **A second checker agent.** Measured on the first design: it added more errors than it removed and read more like AI, at about 77k extra input tokens per text.
- **Third-party rule sets** (stop-slop, humanizer, WRITING.md). Measured on the first design: three to four times the invented facts, more AI-like, higher cost.

## Decision

1. **Writers keep a short accuracy block in `config/CLAUDE.global.md` and nothing about voice:** state nothing the sources don't, keep every hedge, do not tie a fact to a cause the sources don't give, leave out what the reader never saw, back every PR-review claim with a check (outside auto mode, only checks that need no permission prompt), and check each statement against its source privately before delivering. Why: the editor cannot see the sources, and on 16 development texts with a Sonnet writer the private check cut texts with invented facts from 9.25 to 7.25 at no cost. The later run with the check in this block did not confirm that against the first design's full skill (12 to 13 texts with errors against 6 to 12, depending on the judge).
2. **`human-prose` only edits wording, shape and register,** in one file, on a labeled, line-numbered batch, and returns line ranges to replace or `UNCHANGED`. It leaves code, quotes, commit trailers, a `type(scope):` prefix and `Closes #n` alone. Why: one file needs no extra read, which prompted for permission in default mode.
3. **The `human-prose-editor` agent runs the skill** on Haiku, with the skill preloaded, `omitClaudeMd`, only the Read tool (an agent needs at least one) and a one-line body that answers `NO-SKILL` if the skill is missing. `cfg.py` deploys it from `config/agents/`. The `SubagentStart` hook skips it through a matcher, so the host's tracker line stays out of its context. Why: a scratch-home check showed the agent sees no CLAUDE.md, quotes the skill, runs on `claude-haiku-5-5` with about 4k to 8k input tokens per call (16k for one large mixed batch), and the hook still runs for every other agent.
4. **One trigger:** the session that commits, posts or sends text people read, or hands it to the user to post, calls the editor once per batch after the texts are final, and reports whether the pass ran. A subagent that sends text runs the pass itself; nobody edits text after it has left. A session delegating such text, or any task to the OMC executor, git-master or writer agents, says so in the subagent's prompt. Why: git-master loaded the old skill 0 of 2 times without such a line and 2 of 2 with it. In the evaluation, 12 of 12 sessions ran the pass unprompted and 4 of 4 delegated sessions ran exactly one.
5. **The sending session gates every edit:** it applies a range only if the new lines keep every number, name (ignoring case), identifier, link, code span and hedge word of the lines they replace. Why: the sending session has the sources and the editor doesn't. In mixed batches it skipped 3 of 41 ranges, each one that had lost a name, an identifier or a code span.
6. **A failed pass sends the text unedited and says so:** a missing agent, an error, `NO-SKILL` or a reply out of format.
7. **Issue and ticket bodies go through this pass only,** not `agent-doc-discipline`, because people read them.
8. **No second checker agent and no link checks by the editor.**

## Consequences

- Writers lose the voice and shape rules, and the per-text procedures for PR reviews, ADR and design-doc pitch order, security sections, read-back after posting and `gh` link checks are gone.
- Every batch costs an extra Haiku call: about $0.001 to $0.002 and 7 to 13 seconds; across a run of three commits with one pass, under $0.001 per commit.
- The pass leaves text agents write about as AI-like as before. If use confirms the measured gap, the writing-time rules return for writers, alongside the pass or in place of it.
- The editor can only replace lines in place; it cannot reorder or cut a section. Structure that reads as machine-made stays the writer's.
- Backing this out: remove `agents` from both host profiles and deploy before reverting `cfg.py`. An older `cfg.py` refuses a `state.json` that records `agents/…`, and auto sync runs the sync clone's own `cfg.py`.
- The evaluation corpus, harness and judge outputs stay outside this repo, so the evaluation can't be rerun from the repo alone.

## Follow-ups

- The nested `claude -p` path, if the agent path fails later or the platform changes how subagents load context.
- Rerun the evaluation when the Haiku model changes.
- Collect PR reviews and chat messages written by people for a later corpus; the evaluation had none.
