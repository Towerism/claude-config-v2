# ADR-0016: One skill for every text a person reads

**Status:** Accepted 2026-11-21, issue #76.

## Context

Agents write commit messages, PR descriptions and reviews, issues, tickets, ADRs, READMEs, chat messages and wiki pages. People read all of them, so one skill covers them all, and because it runs on every such text, its cost decides whether it is used at all.

The design was tested blind, outside this repo:

- 40 human-written texts from small, little-known repos and Jira projects, written before December 2022, so the judges could not recognise them. Five per text type.
- Each text was rewritten, or written again from a fact sheet of what it says, under each candidate design.
- Fresh judge agents scored each text alone, with names anonymised: how likely it is to be AI-written (Opus and Sonnet), invented, dropped or wrong facts against the sources (Opus and Sonnet), and whether the reader gets what they need.

What the tests showed, on 16 development texts with a Sonnet writer:

- **Writing from facts invents facts.** Without a check, 9.25 of 16 texts had at least one fact the sources don't state; a human-written control had 1 to 2, which is judge noise.
- **A private check before delivery helps at no cost.** Asking the writer to check each statement against its source in its own reasoning, and deliver only the final text, brought that to 7.25 of 16, in the same direction in all four paired comparisons, with no extra output tokens or time and nothing leaked into the text.
- **A second agent that checks the draft against the sources** brought it to 5 of 16, at up to 6.9k extra input tokens and 7.9 seconds on a README.
- **Edits that change only what gets in the reader's way** stay close to human text: P(AI) 17 to 18 against 10 for the originals, where edits without the skill scored 62.
- **Third-party rule sets did worse.** stop-slop, humanizer and WRITING.md (full, compact and as a skill) invented three to four times as many facts and read more like AI, at higher cost.

## Decision

1. **One skill, `human-prose`,** for every text a person reads. Its core rules always load. Rules for a single kind of text sit in reference files that `SKILL.md` names with when to read them: text the user sends as themselves, PR reviews, design docs, and tickets and PRs.
2. **Every text gets the private check before delivery,** written or edited.
3. **Edits change only the sentences that get in the reader's way** and keep every fact, name, link, number, hedge and stated reason.
4. **A Sonnet verifier checks README, wiki and PR texts written from sources,** for the types where paired runs on held-out texts show it lowers errors; for the others the step is removed before merge.
5. **Links are checked only with read-only `gh` commands, and only in auto mode,** so a link check never stops a session for a permission prompt.
6. **`config/CLAUDE.global.md` names when to load the skill,** because skills rarely load on their own.

## Consequences

- Texts written from facts still invent some facts, and blind judges can still tell them from human writing. The skill does not fake typos or quirks to close that gap.
- Whether the private check is real checking or just the effect of the instruction is unknown; it costs nothing measurable either way.
- Every session pays for the skill's description, and every text for about 2k input tokens of rules.
- The evaluation corpus, harness and judge outputs stay outside this repo, so the evaluation can't be rerun from the repo alone. Rerun it when the session's writer model changes.
