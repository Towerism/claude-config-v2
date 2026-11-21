---
name: human-prose
description: Write or revise any text a person will read, so it gives that reader what they need, reads as a person wrote it, and states nothing its sources don't. Covers commit messages, PR descriptions, PR reviews, issues, tickets, ADRs, READMEs, design docs, wiki and Confluence pages, release notes, and Slack or other chat messages, including text the user sends as themselves. Use when writing such text from facts, a diff or a conversation, and when editing someone's draft. Not for text only agents read (SKILL.md files, prompts, CLAUDE.md).
---

# Text a person reads

## Steps

Writing from sources (facts, a diff, an issue, the conversation, earlier text):

1. Name the reader and the one thing they need from this text: to approve it, to try it, to understand why, to act. Why: a text that doesn't surface what its reader cares about misses its purpose, however accurate it is.
2. Read the reference file for the text type, if the table under "Reference files" names one.
3. Write it in the shape for its type ("Shapes by text type"), following every rule below.
4. Run the check under "Before you deliver".
5. If the type is a README, a wiki or design page, or a PR description, run the checker in `references/checker.md`.
6. Deliver only the final text. Done when the reply holds the text and nothing about how it was made.

Revising someone's draft: follow "Revising someone's draft", then steps 4 and 6. Edits get no checker.

## Reference files

| Text | Read |
|---|---|
| Text the user will send as themselves (Slack, chat, a comment in their name) | `references/sent-as-the-user.md` |
| A review of someone's PR | `references/pr-review.md` |
| An ADR, design doc or wiki page | `references/design-docs.md` |
| An issue, ticket or PR description | `references/tickets-and-prs.md` |
| A README, wiki or design page, or PR description, written from sources (step 5) | `references/checker.md` |

A commit message, and a chat reply not sent as the user, need no reference file.

## What goes in

- Lead with what the reader needs, and keep it short. Cut every sentence this reader would not miss; don't explain their own system back to them. Why: readers are sensitive to noise, and a buried point leaves them unsure what the text is for.
- Keep a fact only if a cold reader gains something from it. A local IP address or a path on someone's machine does not pass.
- Make each piece of evidence say how it supports the point ("the PR added back an auth check the team had removed in 2025 to fix a bug", not "the history turned this into a regression"). Why: evidence the reader can't connect to the point reads as noise.
- Paste evidence that already exists (benchmark output, an error, a command, a log line) as a block, and don't retell the block in prose.
- When the reader can't yet picture what something does, show one or two real examples rather than a list of instructions. Use only results already public to the people involved, checked against the published source. Why: a list of instructions doesn't show much.
- Explain a new idea through something the reader already knows, and say what an unfamiliar term means the first time it appears. Why: readers take in a new idea best through ideas and sentence shapes they've seen many times.
- Leave out what the reader never saw: an earlier private version, what was cut, plan or spec keys such as D1, R4 or AC-3, local file paths, interview rounds. Why: a reference to something only the author has seen is noise.
- Keep each idea in one place. Link to where details already live instead of repeating them. Why: repeated content adds upkeep and doesn't help the reader.
- Call cleanup work a refactor; never write "slop" or words built on it.

## Links

Write every PR, issue, ticket and CI run as a clickable link or full reference, never a bare ID. Why: no one can find a run from its number alone.

- A PR in another repo is `owner/repo#n` or a full URL, never "repo #n". Why: GitHub turns a bare `#n` into a link to the current repo's item with that number.
- Write a full reference only when the sources give the repo or URL; otherwise keep the ID exactly as the sources wrote it.
- Check links only when the session's context says auto mode is active, and only with `gh pr view`, `gh issue view` or `gh run view`. In any other mode, or for a link `gh` can't check, leave the link as given and name the unchecked links in your reply to the user, never in the delivered text. Why: other link checks can stop the session for a permission prompt.

## Accuracy

- Add no fact, number, name, cause, reason, plan or claim of testing that the sources don't state. If the sources don't give a reason, don't supply one. Don't link two facts with a cause ("so", "because", "which now") unless the sources link them.
- Where the sources are vague, stay vague. Don't name what "the problem" was, explain how something works, say why it matters, or fill a table cell or a section unless the sources say it. Leave out a table column or a section you can't fill from the sources, rather than writing placeholders.
- Keep every hedge at its strength: "might", "should", "seems", "roughly", "presumably", "is meant to", "in general", "often". A hope, plan or expectation stays one; never turn it into a result. Plain wording means plain words, not stronger claims.
- Why: an overclaim in a confident tone costs more trust than leaving the claim out.

## Revising someone's draft

Edit, don't rewrite. Why: readers already trust the author's own words, and every rewritten sentence is a chance to lose a fact, a name or a qualifier.

1. Read the draft as its reader. Note only the sentences that get in that reader's way: the point is buried, a term is unexplained, a link is a bare ID, a sentence repeats another, wording the reader would have to decode, or something the reader never saw.
2. Change only those sentences, and only as much as fixing them needs. Keep every other sentence exactly as written, including the author's voice, formatting and harmless quirks.
3. Keep every fact, name, identifier, link, number, hedge and stated reason. Fix a fact only when the sources show it is wrong.
4. If nothing gets in the reader's way, return the draft unchanged.

## Wording and shape

These keep the text reading as a person wrote it. Why: readers who sense machine-written text start skimming and miss what matters.

- Use everyday words and plain verbs: is, has, uses, wrote, moved, tried. Avoid unusual phrasing a reader has to stop and decode ("trades tokens for trust" → "spends extra tokens to make sure every comment can be trusted"; "every finding earns its place" → "the skill only keeps a comment if it was tested").
- Use the shape people use for this kind of text (below), and the headings the project's own template uses, if it has one. Text under about 200 words gets no headings and no bold labels; don't split a short flat document into sections. Never take a heading's wording from these rules.
- Say what matters to this reader; don't walk through every case or option in turn just to be complete, and don't use every fact you were given.
- Start with the first real point, not a sentence that previews what follows. Let list items differ in shape as their content does, rather than making them uniformly parallel.
- Say what a thing is. Add a "not X" contrast only when the reader would otherwise assume X.
- Write only the sections the sources can fill; skip Impact, Expected behavior, Next steps or Summary when they can't. Each sentence carries something new: no sentence that only bridges or sums up what the reader just read.
- End on the last real point: no summary line, no closing question, no offer to help or discuss.
- Write as the author would: contractions are fine, first person where the author did the work, sentence lengths as they come. Don't fake informality or errors.

## Shapes by text type

- Commit message: imperative subject under about 60 characters; blank line; a body that says why, wrapped near 72 columns. A small change may have no body.
- PR description: what changes and why, then how it was tested or the evidence. Paste benchmark or test output rather than describing it.
- Issue or ticket: what is wrong or wanted, then reproduction steps or the evidence. Add expected behavior only when it isn't obvious.
- ADR: the context that forces a decision, the decision, its consequences. Short.
- README: what the thing is and who it's for in the first lines, one real example of using it, then how to install and run it.
- Chat message: one to three sentences in one paragraph, no headings or bullets; lead with the point or the ask. From thin sources, say only what they say; if they don't name the problem, neither does the message.
- Wiki or design page: a short pitch to a cold reader. Open with a few sentences on the current state and the change proposed, then the problems with today, then what the change gains; details after.

## Before you deliver

Check the text privately, in your own reasoning, before you deliver it: for each statement of fact, find the source it rests on, and remove or fix any statement with no source or stated more strongly than its source. Check the text against the shape rules. Deliver only the final text: never the draft, the check, or any note about it. Done when every statement has a source and the reply holds only the text.
