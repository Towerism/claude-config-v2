---
name: human-prose
description: Write and review prose that people will read (PR and issue descriptions, tickets, READMEs, design docs, Confluence pages, commit messages, release notes) so it keeps the reader's attention and every claim holds up. Covers the writing rules with their reasons, and a draft, cold-read, verify and fix loop. Use when asked to write or review such text, to make text more readable, or when a reader would lose the thread. Not for text only agents read (SKILL.md, agent prompts, CLAUDE.md).
---

# Prose for human readers

Use this for any text a person reads to understand or decide something. Skip it for text only agents read (SKILL.md, agent prompts, CLAUDE.md), which follows agent-doc-discipline instead.

The premise behind every rule: **readers drop text that reads like noise.** In the AI era they are quick to spot it. Once a reader decides a text is noise, they skim the rest, including the parts that matter.

## Steps

1. **Name the reader and what they care about.** Write down who reads this, what they already know, and the one thing they need from it (to approve, to try it, to understand why). Done when you can say it in one sentence. Why: a text that doesn't surface what the reader cares about won't get its purpose across, however accurate it is.

2. **Draft by the rules below.** Lead with what the reader cares about. When the reader can't yet picture what the thing can do, show one or two real, verified examples. Done when a first draft exists.

3. **Run the mechanical checks.** Fix every hit, or confirm it is fine:
   ```bash
   grep -nE ', not |not just|not only|but (not|never)|instead of|rather than|but (aren|isn)'"'"'t' FILE
   grep -noE '(^|[^/A-Za-z0-9_-])#[0-9]+' FILE
   grep -noE '\]\((\.|[a-z][^:)]*)\)' FILE
   ```
   The first finds contrast pairs, the second bare `#N` references, and the third relative links (wrong in PR and issue bodies). Then read once for inline lists of exactly three and three-bullet lists, which grep can't find reliably. Done when every hit is fixed or judged fine.

4. **Get a cold read from a specialist.** Launch `oh-my-claudecode:critic` (opus), or the closest reviewer agent if OMC isn't installed. Give it the reader from step 1, the text, the sources the facts come from, and the rules below pasted word for word. Leave out your own reasoning about the draft. Ask for each violation with the rule, the quoted text and a rewrite that itself follows every rule. Done when the report is in. Why: the writer can't see their own gaps, and a reviewer handed the writer's reasoning tends to agree with it.

5. **Check each finding before acting on it.** A reviewer can be wrong too. In one case a reviewer called a built-in command missing, suggested a wrong meaning for a term, and flagged a quote as unsourced when it was the user's own. Keep what holds up. Where you reject a finding, say why. Done when every finding is either applied or rejected with a reason.

6. **Re-read until nothing new turns up.** Send the revised text back to the same reviewer and ask only for problems that remain or that the rewrite introduced. Done when a re-read reports nothing new. Why: rewrites bring in new problems, such as a term that was explained in one file but not in another.

7. **Check how it renders.** For GitHub text, look at what the published page does. A PR body should link to the files on the branch. File links on a private repo can be checked with `gh api repos/<o>/<r>/contents/<path>?ref=<branch> -q .html_url`. Done when every link goes where it should.

## The rules

Each rule comes with the reason the user gave for it.

**Lead with what the reader cares about, and keep it short.** Readers are sensitive to noise, and an explanation that doesn't surface what they care about leaves them unsure what the text is for.

**Show what the thing can do with real examples.** People don't know what AI can do until they see it, and a list of instructions doesn't show much. Use one or two real results. Use only results that are already public to the people involved, and check each fact against the published source. For example, don't cite a review nobody has posted yet.

**Make every piece of evidence say how it supports the claim.** A fact given as evidence, where the reader can't work out how it supports the point, reads as noise. Every step should visibly follow from the one before. For example, "the history turned a disputed finding into a regression" doesn't say what the history was. "The PR added back an auth check the team had removed in 2025 to fix a bug" does.

**Explain new ideas through things the reader already knows.** Readers understand a new idea when it's described with ideas and sentence shapes they've seen thousands of times. Explain each unfamiliar term the first time it appears in each text, not just once across all of them.

**Write in everyday language.** Unusual wording makes readers stop and work out exactly what the words mean, and that loses their attention. Rewrite compressed or clever phrasing as plain cause and effect. Avoid idioms used as arguments, slogan headings, headings without a verb, stacked nouns and rare words. Examples the user flagged:
- "every finding earns its place" became "the skill only keeps a comment if it was tested"
- "trades tokens for trust" became "spends extra tokens to make sure every comment can be trusted"
- "Looks like waste, isn't" became "Steps that look unnecessary but are needed"

**Avoid inline lists of exactly three, and contrast pairs.** "A, b, and c" and "X, not Y" are common AI patterns. They're subtle, but people are good at spotting patterns, so they read close to noise. Rewrite them as separate plain sentences. Lists of four or more real items are fine, and so are plain negative sentences.

**Leave out things the reader never saw.** For example, an earlier private version of the work, or what was cut from it. A reference to something only the author has seen is noise.

**Keep each idea in one place.** Repeating the same content across documents adds upkeep and doesn't help the reader. A design doc that walks through steps makes the reader wonder why they shouldn't just read the steps. So a design doc explains the thinking, and it points to where the steps and the incidents are written down. A one-clause reason repeated for a different audience is fine.

**Claim only what the source says.** Match the strength of the source ("tends to", "may"). A claim the source doesn't make, even a reasonable one, gets weakened or cut. An overclaim under a confident tone costs more trust than leaving it out.

**Write GitHub references so they can't point at the wrong repo.** Write cross-repo PRs as `owner/repo#n` or as full URLs. GitHub turns a bare `#n` in PR bodies and comments into a link to the current repo's PR with that number, if it exists. Rendered repo files never autolink.

## Pitfalls

- A detector for lists of three flags many ordinary two-part sentences. Treat its hits as candidates and judge each one.
- Applying one round of fixes can bring the same pattern back elsewhere. After a rewrite, run step 3 again.
- curl returns 404 for github.com pages of a private repo even with a token. That doesn't mean the link is broken.
