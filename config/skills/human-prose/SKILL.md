---
name: human-prose
description: Write and review prose that people will read (PR and issue descriptions, tickets, READMEs, design docs, Confluence pages, commit messages, release notes) so it keeps the reader's attention and every claim holds up. Covers the writing rules with their reasons, a catalog of the tells that make text read as AI-written, and a draft, rule-free gestalt read, cold-read, verify and fix loop. Use when asked to write or review such text, to make text more readable, or when a reader would lose the thread. Not for text only agents read (SKILL.md, agent prompts, CLAUDE.md).
---

# Prose for human readers

Use this for any text a person reads to understand or decide something. Skip it for text only agents read (SKILL.md, agent prompts, CLAUDE.md), which follows agent-doc-discipline instead.

The premise behind every rule: **readers drop text that reads like noise.** In the AI era they are quick to spot it. Once a reader decides a text is noise, they skim the rest, including the parts that matter.

Readers don't check a text against a list. They react to its overall feel, often before they could name one pattern, and named rules catch only part of what they react to. The patterns are symptoms of one cause: a model fills each slot with the most typical sentence, so the text could be about anything. That is why the loop below has a reviewer who reads without rules, and why a fix adds the specific fact a sentence stood in for instead of rewording it.

## Steps

1. **Name the reader and what they care about.** Write down who reads this, what they already know, and the one thing they need from it (to approve, to try it, to understand why). Done when you can say it in one sentence. Why: a text that doesn't surface what the reader cares about won't get its purpose across, however accurate it is.

2. **Draft by the rules below.** Lead with what the reader cares about. When the reader can't yet picture what the thing can do, show one or two real, verified examples. Done when a first draft exists.

3. **Run the mechanical checks.** Fix every hit, or confirm it is fine:
   ```bash
   grep -nE ', not |not just|not only|but (not|never)|instead of|rather than|but (aren|isn)'"'"'t|(never|not|wasn'"'"'t|isn'"'"'t) (simply|just|merely|only)' FILE
   grep -noE '(^|[^/A-Za-z0-9_-])#[0-9]+' FILE
   grep -noE '\]\((\.|[a-z][^:)]*)\)' FILE
   grep -niwE 'delv\w*|pivotal|underscor\w*|showcas\w*|foster\w*|leverag\w*|robust|seamless\w*|crucial|landscape|multifaceted|intricat\w*|meticulous\w*|quietly|testament|(serves|stands|functions) as|plays? an? (key|pivotal|vital|crucial) role|worth noting|important to note|in summary|key takeaways?|here'"'"'s (what|why|how)|let'"'"'s (look|dive|take)|I hope this helps|happy to adjust|despite these challenges|in this (PR|change), we' FILE
   grep -niE '(^|[.?!] )Additionally,|, (ensuring|highlighting|underscoring|emphasizing|reflecting|making it)\b' FILE
   grep -o '—' FILE | wc -l
   ```
   The first finds juxtapositions, the second bare `#N` references, the third relative links (wrong in PR and issue bodies), the fourth AI vocabulary and stock phrases, the fifth a sentence-opening "Additionally," and analysis tacked on as an -ing tail, and the sixth counts em dashes. Phrases split across hard-wrapped lines slip past grep; for wrapped markdown, pipe `tr '\n' ' ' < FILE` into the phrase greps with `-o` added. Grep can't reliably find the rest, so read once for each of these: inline lists of exactly three, three-bullet lists, a juxtaposition split across two sentences, and a short closing line that restates the paragraph as a punchline. Then read the whole text once for each row under "The text as a whole" in `references/ai-tells.md`, starting with swappable sentences. Done when every grep hit and every whole-text row is either fixed or judged fine.

4. **Get a gestalt read.** Launch a reviewer agent (`oh-my-claudecode:critic` on opus, or the closest one) and give it only the text and the reader from step 1: no rules, no catalog, no sources. Ask it to read as someone who reads a lot of AI-written text and has learned to skim it, and to quote every sentence where its attention dropped or the text felt machine-written, saying in its own words what tipped it off. Ask also for the one thing, if any, that made the whole text feel templated. Run it alongside step 5. Done when the report is in. Why: a reviewer handed a checklist looks only for what is on it, and the reader has no checklist.

5. **Get a cold read from a specialist.** Launch `oh-my-claudecode:critic` (opus), or the closest reviewer agent if OMC isn't installed. Give it the reader from step 1, the text, the sources the facts come from, and the rules below with `references/ai-tells.md` pasted word for word. Leave out your own reasoning about the draft. Ask for each violation with the rule, the quoted text and a rewrite that itself follows every rule. Done when the report is in. Why: the writer can't see their own gaps, and a reviewer handed the writer's reasoning tends to agree with it.

6. **Check each finding before acting on it.** A reviewer can be wrong too. In one case a reviewer called a built-in command missing, suggested a wrong meaning for a term, and flagged a quote as unsourced when it was the user's own. Keep what holds up, and fix it as "Fix the cause, not the wording" below says. A gestalt finding counts when it quotes text and names a concrete feature of it, whether or not the catalog lists it; reject only findings that rest on a Not tell from the catalog (bland, formal, grammatical). When the two reviewers pull in opposite directions, prefer the change that cuts text, and never add roughness or slips to look human. Where you reject a finding, say why. Done when every finding is either applied or rejected with a reason.

7. **Re-read until nothing new turns up.** Send the revised text back to both reviewers and ask only for problems that remain or that the rewrite introduced. Done when a re-read reports nothing that survives step 6, or after two rounds of the gestalt reviewer, but not while a cold-read finding that survives step 6 is still open; then list what remains in your reply. Why: rewrites bring in new problems, such as a term that was explained in one file but not in another, and a reader asked where a text feels machine-written will nearly always quote something.

8. **Check how it renders.** For GitHub text, look at what the published page does. A PR body should link to the files on the branch. File links on a private repo can be checked with `gh api repos/<o>/<r>/contents/<path>?ref=<branch> -q .html_url`. Done when every link goes where it should.

## The rules

Each rule comes with its reason. `references/ai-tells.md` holds the full catalog of word-level, shape-level and whole-text tells; these rules are the ones that matter most.

**Write sentences that only fit this text.** Ask of each sentence whether it could appear unchanged in a text about a different project. If it could, it tells the reader nothing, and readers feel that before they can say why. Prefer cutting it. Where the reader needs the point, replace it with the fact only this work has (a number, a file, a name, what broke); a number in every paragraph is its own tell. For example, "This change improves reliability and makes the worker more robust" fits any PR. "Deliveries that hit a 503 now retry three times over 40 seconds; last week 212 were dropped" fits one.

**Fix the cause, not the wording.** When a pattern turns up, swapping in a synonym or a different sentence shape keeps the feel that tipped the reader off. Find the fact the sentence was standing in for and write that, or delete the sentence.

**Lead with what the reader cares about, and keep it short.** Readers are sensitive to noise, and an explanation that doesn't surface what they care about leaves them unsure what the text is for.

**Show what the thing can do with real examples.** People don't know what AI can do until they see it, and a list of instructions doesn't show much. Use one or two real results. Use only results that are already public to the people involved, and check each fact against the published source. For example, don't cite a review nobody has posted yet.

**Make every piece of evidence say how it supports the claim.** A fact given as evidence, where the reader can't work out how it supports the point, reads as noise. Every step should visibly follow from the one before. For example, "the history turned a disputed finding into a regression" doesn't say what the history was. "The PR added back an auth check the team had removed in 2025 to fix a bug" does. This applies to evidence the reader can't connect on their own. Leave out reasons they'd supply themselves; a "because" on every choice reads as written to a checklist.

**Explain new ideas through things the reader already knows.** Readers understand a new idea when it's described with ideas and sentence shapes they've seen thousands of times. Explain each unfamiliar term the first time it appears in each text, not just once across all of them.

**Write in everyday language.** Unusual wording makes readers stop and work out exactly what the words mean, and that loses their attention. Rewrite compressed or clever phrasing as plain cause and effect. Avoid idioms used as arguments, slogan headings, headings without a verb, stacked nouns and rare words. Examples the user flagged:
- "every finding earns its place" became "the skill only keeps a comment if it was tested"
- "trades tokens for trust" became "spends extra tokens to make sure every comment can be trusted"
- "Looks like waste, isn't" became "Steps that look unnecessary but are needed"

**Avoid inline lists of exactly three.** "A, b, and c" is a common AI pattern. It's subtle, but people are good at spotting patterns, so it reads close to noise. Rewrite it as separate plain sentences. Lists of four or more real items are fine.

**Avoid juxtaposition and cheesy stingers.** A juxtaposition sets up one idea only to swap in another. It can sit inside a sentence ("X, not Y") or span two: "She was never simply a voice behind the screen. She was part of the sound of growing up." A stinger is a short, quotable line that ends a paragraph or section by restating the point as a punchline, and it is one of the worst offenders. People are good at spotting patterns, and these are among the first they tag as AI. The more a text reads like AI, the more the reader hunts for further signs of it, and they stop following the content. A reader who has stopped paying attention gets no value from the text. Fix it by stating only the claim that is true, once, and ending the paragraph when its content ends. For example, "She hosted the station's afternoon show for twenty years." Plain negative sentences that carry a fact are fine ("The hook doesn't run on Windows").

**Leave out things the reader never saw.** For example, an earlier private version of the work, or what was cut from it. A reference to something only the author has seen is noise.

**Keep each idea in one place.** Repeating the same content across documents adds upkeep and doesn't help the reader. A design doc that walks through steps makes the reader wonder why they shouldn't just read the steps. So a design doc explains the thinking, and it points to where the steps and the incidents are written down. A one-clause reason repeated for a different audience is fine.

**Claim only what the source says.** Match the strength of the source ("tends to", "may"). A claim the source doesn't make, even a reasonable one, gets weakened or cut. An overclaim under a confident tone costs more trust than leaving it out.

**Write GitHub references so they can't point at the wrong repo.** Write cross-repo PRs as `owner/repo#n` or as full URLs. GitHub turns a bare `#n` in PR bodies and comments into a link to the current repo's PR with that number, if it exists. Rendered repo files never autolink.

## Pitfalls

- A detector for lists of three flags many ordinary two-part sentences. Treat its hits as candidates and judge each one.
- Splitting "X, not Y" into two sentences keeps the juxtaposition and often creates a stinger. Drop the rejected half instead.
- Applying one round of fixes can bring the same pattern back elsewhere. After a rewrite, run step 3 again.
- The vocabulary grep also matches code identifiers such as `__underscore__`. Skip hits inside code spans.
- Following every rule evenly can itself be a tell. A text where each paragraph does one job, each claim has a reason and each paragraph has a number reads as written to a checklist. In a blind test of three AI texts against three human ones, a rules-based reviewer found more rule breaks in the human texts; a reviewer reading without rules named this evenness as the giveaway. Apply the rules where the reader needs them, and let the rest of the text be uneven.
- Over-fixing makes text worse. Correct grammar, formal wording and plain prose are not tells, and roughening them on purpose costs clarity for nothing.
- curl returns 404 for github.com pages of a private repo even with a token. That doesn't mean the link is broken.
