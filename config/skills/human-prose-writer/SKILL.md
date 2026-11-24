---
name: human-prose-writer
description: Write and review prose that people will read (PR and issue descriptions, tickets, READMEs, design docs, Confluence pages, commit messages, release notes) so it keeps the reader's attention and every claim holds up. Covers the writing rules with their reasons, and a draft, cold-read, verify and fix loop. Use when asked to write or review such text, to make text more readable, or when a reader would lose the thread. Not for text only agents read (SKILL.md, agent prompts, CLAUDE.md), or for the line-level edit pass on finished text (the human-prose-editor agent does that).
---

# Prose for human readers

Use this for any text a person reads to understand or decide something. Skip it for text only agents read (SKILL.md, agent prompts, CLAUDE.md), which follows agent-doc-discipline instead.

The premise behind every rule: **readers stop reading as soon as reading becomes a chore.** It becomes a chore when the text reads like noise, when they have to work to decode it, when it talks down to them, or when it leaves them unsure what it meant. In the AI era readers are quick to spot noise. Once they decide a text is a chore, they skim the rest, including the parts that matter.

The loop below is self-contained. A cold reader with every rule says what is wrong with the draft, and the writer fixes it or rewrites it, until a cold read finds nothing new.

## Steps

1. **Name the reader and what they care about.** Write down who reads this, what they already know, and the one thing they need from it (to approve, to try it, to understand why). Also decide which kind of text it is: one the reader acts on (a PR, a ticket, a decision request) or one that explains (a design doc, a pitch, a README). Done when you can say both in one sentence each. Why: a text that doesn't surface what the reader cares about won't get its purpose across, however accurate it is, and the two kinds open differently (see "Open with what the reader cares about").

2. **Draft by the rules below.** When the reader can't yet picture what the thing can do, show one or two real, verified examples. Done when a draft exists.
   - When rewriting a text whose problem is its tone, flow or structure, start over from the reader, the goal and a set of checked facts, and don't hand the old text to whoever drafts. Why: a rewrite briefed with the old text, or patched line by line, keeps the old shape and level of detail, and the reader feels no difference.
   - When fixes have piled up on one draft over several rounds, start a new draft and let its structure change completely. Why, in the user's words: after many changes under one structure, the content drifts from the structure, so the structure stops working.

3. **Run the mechanical checks.** Fix every hit, or confirm it is fine:
   ```bash
   grep -nE ', not |not just|not only|but (not|never)|instead of|rather than|but (aren|isn)'"'"'t' FILE
   grep -noE '(^|[^/A-Za-z0-9_-])#[0-9]+' FILE
   grep -noE '\]\((\.|[a-z][^:)]*)\)' FILE
   ```
   The first finds contrast pairs, the second bare `#N` references, and the third relative links (wrong in PR and issue bodies). Then read once for inline lists of exactly three and three-bullet lists, which grep can't find reliably. Done when every hit is fixed or judged fine.

4. **Get a cold read from a subagent.** Launch `oh-my-claudecode:critic`, or the closest reviewer agent if OMC isn't installed. Use opus for the first read of a new draft. Give it the reader and the text kind from step 1, the text, the sources the facts come from, and the rules below pasted word for word. Leave out your own reasoning about the draft. Ask it to name every place that may fail a rule, even at only 55% confidence, each with the quoted text, the rule, its confidence and one line on why. Done when the report is in. Why: the writer can't see their own gaps, and a reviewer handed the writer's reasoning tends to agree with it. A low bar keeps borderline problems in view, and step 5 sorts them.

5. **Check each finding, then fix or rewrite.** A reviewer can be wrong too. In one case a reviewer called a built-in command missing, suggested a wrong meaning for a term, and flagged a quote as unsourced when it was the user's own. Check each finding against the sources and the rules. Keep what holds up, and note why you reject the rest. Then decide how to act on what holds up:
   - Ambiguity and wrong facts sit in specific places, so fix them in place.
   - When several findings share one cause in the structure (for example, a text that describes one case and then patches in the exceptions), or the problem is tone or flow, rewrite from step 2.
   Done when every finding is fixed, rejected with a reason, or covered by a rewrite.

6. **Re-read with a light pass until nothing new turns up.** Send the revised text to a reviewer subagent, as in step 4. A lighter model (`oh-my-claudecode:critic` on sonnet) is enough for these re-reads. Give it the same inputs, and ask for places that may fail a rule, down to 55%, including problems the revision introduced. Go back to step 5 with what it finds. After a rewrite, run step 3 and a full step 4 read again. Done when a re-read reports nothing new that holds up. Why: revisions bring in new problems, such as a term that was explained in one file but not in another.

7. **Check how it renders.** For GitHub text, look at what the published page does. A PR body should link to the files on the branch. File links on a private repo can be checked with `gh api repos/<o>/<r>/contents/<path>?ref=<branch> -q .html_url`. Done when every link goes where it should.

8. **Run the edit pass before the text is shown as ready.** Before asking the user whether the text is ready, and before it leaves the session in any other way, send it through the `human-prose-editor` agent and apply its line-range edits that keep every number, name, identifier, link, code span and hedge word. Done when the edit pass has run, or is reported as skipped with the reason. Why: the user signs off on the text that will actually leave, so what they review must already have had the edit pass.

## The rules

Each rule comes with the reason the user gave for it. They pull against each other in places, and each rule says where its limit is. Writing is nuanced, so when two rules seem to conflict, the reader from step 1 decides.

### What to say

**Open with what the reader cares about, and keep it short.** Readers are sensitive to noise, and an explanation that doesn't surface what they care about leaves them unsure what the text is for. In a text the reader acts on, that means the conclusion comes first. In a text that explains, it means opening with why the reader should care, then letting them reach the conclusion themselves (see "Lead the reader to each idea one step at a time").

**Show what the thing can do with real examples.** People don't know what AI can do until they see it, and a list of instructions doesn't show much. Use one or two real results. Use only results that are already public to the people involved, and check each fact against the published source. For example, don't cite a review nobody has posted yet.

**Make every piece of evidence say how it supports the claim.** A fact given as evidence, where the reader can't work out how it supports the point, reads as noise. Every step should visibly follow from the one before. For example, "the history turned a disputed finding into a regression" doesn't say what the history was. "The PR added back an auth check the team had removed in 2025 to fix a bug" does.

**Claim only what the source says.** Match the strength of the source ("tends to", "may"). A claim the source doesn't make, even a reasonable one, gets weakened or cut. That includes a "because" the source doesn't give. An overclaim under a confident tone costs more trust than leaving it out. A casual voice makes overclaims easy to slip in ("nobody would have known" where the source only shows that the diff didn't show it), so keep hedges in plain words, such as "tend to".

**Say it once, briefly.** A good explanation doesn't need to be hammered in. Make each point once, in as few words as carry it, and trust the reader to get it. Leave details that live elsewhere (a README, the steps themselves) to a link. When a claim is only true with a caveat or qualifier attached, cut the claim rather than hedge it. A fix for a reviewer's finding should reword or cut, and only rarely add words. Why, in the user's words: "Why does design.md have to be so long? A good explanation doesn't need to be hammered in." A text that grows a qualifier with each round of fixes ends up correct and unreadable.

**Leave out precision the reader can't use.** A tie of 0.1%, which table sets which value, every caveat in full: detail the reader won't act on turns an explanation into a spec, and tells the reader you think they need everything spelled out. Say the gist in plain words and link to the details. When you cut a caveat, keep its strength in the gist ("treat it as a best guess"), so the shorter claim is no stronger than the source.

**Describe each option by the job it's for.** When a text covers tiers, levels or options, frame each one by the case it fits and what it does well. Don't measure the smaller options by what they lack next to the biggest one, as if the biggest were the real thing and the rest were cut-down copies ("what the cheaper levels give up", "a full run"). Watch the opening and the headings, since they set the frame for everything after them. Why, in the user's words: framing the top option as the one that counts pushes readers to believe anything less isn't worth as much. It discourages using the thing at all unless the reader is ready to pay for the top option, which defeats the reason the other options exist.

**Leave out things the reader never saw.** For example, an earlier private version of the work, or what was cut from it. A reference to something only the author has seen is noise.

**Keep each idea in one place.** Repeating the same content across documents adds upkeep and doesn't help the reader. A design doc that walks through steps makes the reader wonder why they shouldn't just read the steps. So a design doc explains the thinking, and it points to where the steps and the incidents are written down. A one-clause reason repeated for a different audience is fine.

### How to lead the reader

**Lead the reader to each idea one step at a time, without saying that you are.** In a text that explains, the reader should reach each conclusion a moment before the text states it. Three habits do this:
- Start from something the reader already knows. Readers understand a new idea when it's described with ideas and sentence shapes they've seen thousands of times.
- Put the example before the point it proves. Tell it in the order it happened and end on the lesson.
- Let each paragraph answer the question the one before raised. "A test can fool you too" naturally follows "so prove it with a test".
Don't announce the walk-through ("let's walk through", "first, we'll look at"). Why, in the user's words: when people feel they are drawing their own conclusions and get that "aha" moment, they enjoy reading. They learn more, and they learn faster. Writing that spells everything out dryly reads awkwardly and feels disrespectful.

**Walk the fine line between leading and talking down.** Leading a reader slowly to something they already know talks down to them. Keep the reader from step 1 in mind the whole way. Start from what they know, skip the steps they would take on their own, and don't explain what they do every day, such as what getting a code review is like to an engineer. Why: every piece of writing has to be aimed at its real audience, and that is how you walk the line between leading the reader and being condescending.

**Explain exactly as much as the reader needs.** Explaining too little and too much both make reading a chore.
- Too little: the reader loses the thread. They can't see how one point leads to the next, or why something is relevant. Check each sentence for the link to the one before it, and check each fact for a visible reason it's there.
- Too much: the reader feels talked down to, feels the author can't get to the point, and feels the author doesn't trust them to understand. It can also confuse: a reader who thought they knew what was going on hits an extra phrase and wonders what it was for, and whether they had it wrong. Cut each explanation the reader would have supplied themselves, and each aside that doesn't lead anywhere.
Explain each term that is unfamiliar *to this reader* the first time it appears in each text, not just once across all of them. A term the reader uses every day needs no explanation. Why, in the user's words: reading is a chore when any of these feelings come up.

### How each sentence reads

**Write in everyday language.** Unusual wording makes readers stop and work out exactly what the words mean, and that loses their attention. "Everyday" means the reader's everyday: the terms of their own field are fine, and a system's internal labels are not. Rewrite compressed or clever phrasing as plain cause and effect. Avoid idioms used as arguments, slogan headings, headings without a verb, stacked nouns and rare words. Test each sentence: could you say it out loud to a colleague across a desk without it sounding odd? Call things by what they do, in the reader's words. Step numbers, internal component names and a system's own labels belong to the people who built it, so point once to where those details live and keep them out of the running text. People take in idiomatic writing almost instantly. When they have to work out what a word or phrase means, they re-read it two or three times, and by then they're too tired to read the rest. Examples the user flagged:
- "every finding earns its place" became "the skill only keeps a comment if it was tested"
- "trades tokens for trust" became "spends extra tokens to make sure every comment can be trusted"
- "Looks like waste, isn't" became "Steps that look unnecessary but are needed"

**Write for experts as easily as for anyone.** Knowing the reader is an engineer, or any other expert, changes which explanations you can skip. It doesn't make dense writing acceptable. Experts also want to grasp a text at once, without slowing down to weigh each word. So give each sentence one idea, keep the plain connecting words that carry a reader from one sentence to the next, and spread the facts out. Signs the text has turned into a spec: sentences packed with several facts, bold labels in place of sentences, terse lead-ins, symbols like "the first N", and every sentence carrying the same heavy load. Why, in the user's words: "Being an engineer doesn't mean that we like to read slowly and digest every single word. We still like to be able to instantly grasp it." Dense writing aimed at engineers is writing no engineer wants to read.

**Leave nothing open to two readings.** Read each sentence as a stranger would and ask whether it could mean something other than what you meant. Common causes are a pronoun or "both", "it" or "that" whose target is unclear, a word that sounds stronger or weaker than the source ("exactly", "nothing else"), a "from what?" left unanswered ("would drift"), and a scope word that could cover more than you mean ("all", "every", "never"). Reword first, and add only the missing piece, such as the name the pronoun stood for or the end of the thought. Adding a whole explanation trades ambiguity for explaining too much. Why, in the user's words: ambiguity makes a text feel carelessly written, as if the reader's time isn't respected. The reader has to stop and ask "I read this as A, but do they mean B?" Some readers will stop reading there, and some will miss something important or critical.

**Avoid inline lists of exactly three, and contrast pairs.** "A, b, and c" and "X, not Y" are common AI patterns. They're subtle, but people are good at spotting patterns, so they read close to noise. Rewrite them as plain sentences, and vary their shape: a row of short sentences that all start the same way ("It merges… It drops… It keeps…") is a list in disguise, and it reads choppy. Lists of four or more real items are fine, and so are plain negative sentences.

**Write GitHub references so they can't point at the wrong repo.** Write cross-repo PRs as `owner/repo#n` or as full URLs. GitHub turns a bare `#n` in PR bodies and comments into a link to the current repo's PR with that number, if it exists. Rendered repo files never autolink.

## Pitfalls

- A detector for lists of three flags many ordinary two-part sentences. Treat its hits as candidates and judge each one.
- Applying one round of fixes can bring the same pattern back elsewhere. After a rewrite, run step 3 again.
- When the user says a text reads awkwardly but won't say where, they want the whole thing rewritten. Targeted fixes miss the point, and so does a rewrite that keeps the old skeleton (see step 2).
- curl returns 404 for github.com pages of a private repo even with a token. That doesn't mean the link is broken.
