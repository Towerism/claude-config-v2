---
name: human-prose
description: Write or revise any text a person will read, so it gives that reader what they need, reads as a person wrote it, and states nothing its sources don't. Covers commit messages, PR descriptions, PR reviews, issues, tickets, ADRs, READMEs, design docs, wiki and Confluence pages, release notes, and Slack or other chat messages, including text the user sends as themselves. Use when writing such text from facts, a diff or a conversation, and when editing someone's draft. Not for text only agents read (SKILL.md files, prompts, CLAUDE.md).
---

# Text a person reads

## Steps

Writing from sources (facts, a diff, an issue, the conversation, earlier text):

1. Name the reader and the one thing they need from this text: to approve it, to try it, to understand why, to act. Why: a text that doesn't surface what its reader cares about misses its purpose, however accurate it is.
2. Write it in the shape for its type ("Shapes by text type"), following every rule below and the section for its kind of text, if there is one: "Text the user sends as themselves", "A review of someone's PR", "ADRs, design docs and wiki pages", or "Issues, tickets and PR descriptions".
3. Run the check under "Before you deliver".
4. Deliver only the final text. Done when the reply holds the text and nothing about how it was made.

Revising someone's draft: follow "Revising someone's draft", then steps 3 and 4.

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

## Text the user sends as themselves

Use this for a Slack or chat message, or a comment, that goes out under the user's name. Why: a draft in a generic voice doesn't sound like the user.

### Pick the register by where it goes

| Where | Voice |
|---|---|
| Direct message | Direct, warm, loose, low ceremony. Mostly lowercase starts, dropped apostrophes ("dont", "thats"), no period on short lines; "yea", "np", "tho", "kinda". Quick acknowledgments of one to four words ("got it", "makes sense"). One thought may run across several short messages. Opens with "ah", "yes", "ok" or straight into the fact; no sign-off. |
| Channel | Direct and confident, friendly and explanatory. Capitalized full sentences with periods. One to three sentences per message, one claim per message. Concedes a point before adding their own ("That's a good point. … But …"). Links on their own line or with one line of context. No bullets. |
| Public (PR reviews, issue comments, anything outside the team chat) | Formal: full capitalized sentences, no slang ("lmk", "tho", "yea", "lol"), no casual opener or closer. Start from the channel voice and lean more formal. |

Pick by the destination, never by the recipient's own style. Why: the user called a PR review drafted in their direct-message voice "too informal", because PR feedback is public. Keep the text direct in every register.

### Draft it; never send it

Create a Slack message the user authored as a draft in the target DM or channel (`slack_send_message_draft`) and let the user send it. Never send it with `slack_send_message`. Why: that tool appends a "Sent using Claude" trailer the user can't turn off, which reads as noise on a message they wrote.

If the user wants to see it first, put the draft in their own self-DM, then a draft in the recipient's DM after they approve. Never send a self-DM preview: the tool can't delete a sent message.

Done when the draft sits in the right conversation, unsent.

## A review of someone's PR

Why these rules: every sentence the author reads costs their attention, and a review full of noise teaches them to skip the next one.

1. Back every sentence with a check you ran: each finding, the mechanism and consequence it states, any claim about the suggested fix, and every note or "checked and fine" line. Run each check against the base branch, the PR head, and the head with your suggested fix. Reading the code, or other reviewers agreeing, is not a check. When the check would cost more than the sentence is worth, drop the sentence. Why: one unchecked note in an earlier review was wrong, and it cost the whole review the author's trust.
2. Lead each finding with its consequence: what breaks, for whom (a user, a tester, a future maintainer), tied to the PR's goal where you can. Then say which reading applies, the mechanism, and the fix. Drop a finding with no consequence you can state. Why: a finding without a "why" reads as noise, and it leaves the author unsure whether the behaviour you describe is fine or a flaw.
3. Turn a claim about what a person would do ("a tester will log it as failed") into the symptom you reproduced, or drop it.
4. An approval lists the checks behind it, each line opening with what you did, under a lead-in that frames them as verification. Leave out what the author can see for themselves: the PR's tests, its description, CI, mergeability. Why: a bare approval feels empty, and a list of things the author already sees is noise.
5. Settle every open item before writing: check it until it is a finding or ruled out. The review has no "Open questions" section and no closing offer to walk through or discuss anything. Anything still unsettled goes in your reply to the user, never in the review. Why: an open-questions section only signals a check nobody ran.

Done when every sentence in the review names or follows from a check you ran, and the review ends on its last finding or check.

## ADRs, design docs and wiki pages

A design doc, ADR or wiki page for people is a short, high-level pitch to a cold reader. It answers "why should I care?" first. Why: a page that reads like an execution manual loses the people it is meant to convince, and anything that doesn't help a person understand the proposal only confuses them. A detailed manual for agents belongs in a separate document.

1. Order the page: a short summary of where things are now and where they are going; a short list of what is wrong today; a short list of what the change gains; then everything else.
2. Introduce each concept at a high level first, then break it down. A deep concept takes several steps.
3. Keep sections short, so readers don't tire.
4. Use a diagram whenever the reader would otherwise hold more than two or three things in mind, or scroll back to recall an earlier section.
5. Name things in words, never in keys the reader must hold in their head.
6. Where readers already know of a related effort, mention it wherever the page touches that effort's area. Why: otherwise they conclude the page is unaware of it.

For an ADR, keep its shape from "Shapes by text type" (context, decision, consequences) and apply steps 2, 5 and 6.

Done when a reader who knows nothing of the work can say, from the first screen, what changes and why it is worth it.

## Issues, tickets and PR descriptions

- Keep only what is pertinent and present in the ticket's own context: no references to local plans, reviews, interview rounds, `.omc/` files, requirement numbers or decision history. Why: a cold reader gains nothing from them, and the full history belongs in the local design record.
- Conclusion first, no filler, no restated points, plain lists instead of decorative tables. Why: the reader of a ticket wants what to do and why, fast.
- Put every security item (accepted risks, reachability, gate behaviour, follow-ups) in one `## Security findings` section of about 10 to 15 lines, never scattered under other headings. Lead with the bottom line ("nothing exploitable is on our path; the gate passes"), then the gate rule, what is accepted and why in one line per group, caveats, and links to follow-ups. Leave out raw scanner totals and per-CVE detail; link the decision record instead. Elsewhere in the text, link to the section rather than repeating it. Why: security staff and reviewers must find everything in one place, and a reviewer who meets hundreds of scanner findings up front may read nothing else.
- After posting to a tracker, read the issue, ticket or PR back and compare it with what you meant to post. Done when the two match.
