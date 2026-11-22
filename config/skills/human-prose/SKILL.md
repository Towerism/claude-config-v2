---
name: human-prose
description: Edits a labeled, line-numbered batch of texts people will read (commit messages, PR descriptions and reviews, issues, tickets, ADRs, READMEs, wiki pages, chat messages) for wording, shape and register, and returns line-range replacements. Used by the human-prose-editor agent on each batch just before it leaves the session. Not for writing text from sources, and not for text only agents read (SKILL.md files, prompts, CLAUDE.md).
---

# Edit text a person reads

You get a batch of finished texts. Change only the lines that get in the reader's way, and only as much as fixing them needs. Why: readers already trust the author's own words, and every rewritten line is a chance to lose a fact, a name or a hedge.

## Steps

1. Read each text as its reader, picked from its label: the kind of text and where it goes.
2. Note the lines that match a target under "What to change". Leave every other line exactly as written, including the author's voice, formatting and harmless quirks.
3. Write the replacement lines. Keep every number, name, identifier, link, code span, hedge word and stated reason of the lines you replace, and add nothing the old lines don't say. Why: you cannot see the sources, and the session that sent the batch skips any range that loses one of these.
4. Reply in the output format, one section per text, in the batch's order. Done when every text has a section and nothing else is in the reply.

## Input

```
=== 1: commit message | github owner/repo | Conventional Commits ===
1| feat(cfg): deploy agents
2|
3| Adds an agents root to ...
```

Each header gives the text's number, its kind, where it goes, and any format the project fixes, such as the repo's commit style.

## Output

```
=== 1 ===
UNCHANGED
=== 2 ===
@@ 3-4
replacement line
replacement line
```

- `@@ a-b` replaces lines a to b with the lines under it; `@@ a` replaces one line.
- A line no range names stays as it is. Ranges don't overlap. An empty replacement deletes the range.
- `UNCHANGED` when nothing in the text gets in the reader's way.

## What to change

These make text read as machine-written. Why: readers who sense machine-written text start skimming and miss what matters.

- A sentence that previews what follows, or a summary line, closing question or offer to help at the end. Start on the first real point; end on the last one.
- A sentence that only bridges or repeats what the reader just read.
- Phrasing a reader has to stop and decode ("trades tokens for trust" → "spends extra tokens to make sure every comment can be trusted"). Use everyday words and plain verbs: is, has, uses, wrote, moved, tried.
- List items forced into the same shape. Let them differ as their content does.
- A "not X" contrast the reader would never have assumed.
- Headings or bold labels in a text under about 200 words, except `## Security findings` in an issue, ticket or PR description.
- "Slop" or words built on it; call that work a refactor.
- A register that doesn't fit where the text goes (table below).

## What to leave alone

- Code blocks, inline code, quoted text, commit trailers (`Co-Authored-By:` and the like), a Conventional Commits `type(scope):` prefix, and `Closes #n` lines.
- The format the label names: the repo's commit style, a doc template, headings the text already uses.
- Facts, even ones that look wrong. You can't check them; the sender can.
- Contractions, first person and uneven sentence lengths. Don't fake informality or errors either.

## Register

Pick it from where the text goes, never from the recipient's style. Why: the user called a PR review drafted in their direct-message voice "too informal", because PR feedback is public.

| Where | Voice |
|---|---|
| Direct message from the user | Direct, warm, loose. Mostly lowercase starts, dropped apostrophes ("dont", "thats"), no period on short lines; "yea", "np", "tho", "kinda". Opens with "ah", "yes", "ok" or straight into the fact; no sign-off. |
| Channel message from the user | Direct and friendly. Capitalized full sentences with periods, one to three sentences, one claim each. No bullets. |
| Public (PR reviews, issue comments, anything outside team chat) | Formal: full capitalized sentences, no slang ("lmk", "tho", "yea", "lol"), no casual opener or closer. |

The two chat rows apply only to text the user sends as themselves; copying their habits there is not faking informality.
