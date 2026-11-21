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
- **On 24 held-out texts in real sessions, with an Opus writer,** the new skill wrote texts with errors in 6 of 24 against the old skill's 15 (human originals: 4, the judges' noise floor), and edits with errors in 7 of 24 against 20. It read less like AI (P(AI) 49 against 60 written, 19 against 57 edited) and took about 10 seconds per text against 48.
- **Third-party rule sets did worse.** stop-slop, humanizer and WRITING.md (full, compact and as a skill) invented three to four times as many facts and read more like AI, at higher cost.

## Drivers

- No invented facts, and no fact, name or stated reason lost in an edit.
- A cost low enough to run on every commit message and chat message.
- Text that does not read as AI-written, without faking typos or quirks.
- No step that stops a session for a person.

## Alternatives considered

- **Writing in a single pass with no check.** More invented facts in every paired comparison on the development texts.
- **An in-call audit that prints a draft, a list of problems and a final text.** About as accurate as the private check, but slower, and its draft and list land in the delivered text in a real session.
- **A second checker agent for every text, for some types, or by length.** Measured per type on held-out texts; it added more errors than it removed (Decision 4).
- **Rules for each kind of text in reference files.** Cheaper per text, but reading them prompted for permission in default mode (Decision 1).
- **Third-party rule sets** (stop-slop, humanizer, WRITING.md). More invented facts, more AI-like, higher cost.

## Decision

1. **One skill, `human-prose`, in one file,** for every text a person reads. Rules for a single kind of text (text the user sends as themselves, PR reviews, design docs, tickets and PRs) are sections of `SKILL.md`, not separate files. Why: in default permission mode, reading a file next to the skill stopped the session for a permission prompt, and a tool grant in the skill's front matter made loading the skill itself need approval. One file needs no read and no grant.
2. **Every text gets the private check before delivery,** written or edited.
3. **Edits change only the sentences that get in the reader's way** and keep every fact, name, link, number, hedge and stated reason.
4. **No second checker agent.** On held-out README, wiki and PR texts, a Sonnet verifier's fix round left errors where they were on most texts, added one on four and removed one on two, and texts read more like AI after it. It also cost about 77k extra input tokens and 10 to 25 seconds per text.
5. **Links are checked only with read-only `gh` commands, and only in auto mode,** so a link check never stops a session for a permission prompt.
6. **`config/CLAUDE.global.md` names when to load the skill,** because skills rarely load on their own. With it, 24 of 24 sessions loaded the skill without being told to.

## Consequences

- Texts written from facts still invent some facts, and blind judges can still tell them from human writing. The skill does not add typos or quirks to close that gap; text the user sends as themselves copies the user's own habits, which is a matter of voice, not disguise.
- Whether the private check is real checking or just the effect of the instruction is unknown; it costs nothing measurable either way.
- A near-empty session with the skill installed read about 1.7k more input tokens than one without it. The description and the global rules line account for about 180 of them; the rest was not traced. Every text pays about 3.7k tokens of rules. A commit message costs about the same as with the old skill and takes less time.
- The evaluation corpus, harness and judge outputs stay outside this repo, so the evaluation can't be rerun from the repo alone.

## Follow-ups

- Collect PR reviews and chat messages written by people for a later corpus; the evaluation had none, so those rules were reviewed by reading, not measured.
- Rerun the evaluation when the session's writer model changes.
