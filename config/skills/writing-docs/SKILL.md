---
name: writing-docs
description: Guides writing any text a person will read later so a reader with no context can act on it and it doesn't read as AI-written. Load it once per session before the first commit message, issue or PR text, review note, code comment, docstring, assertion or error message, CLI or UI string, or document (README, docs page, ADR, runbook, how-to, changelog, release notes), and when the user asks to document a system, process or decision, even without the word "doc". Also use when the user says text is hard to follow or sounds like AI. Not for the chat reply itself, code, identifiers, machine-read formats, or files written for Claude (CLAUDE.md, SKILL.md, memory, subagent prompts).
---

# Writing docs

A text succeeds when a reader with no context, often the owner months later, can use it to do or decide something.

## Load once

These rules cover every text a person will read later, for the rest of the session. While the block starting `Base directory for this skill: …/writing-docs` is in the conversation, don't load the skill again; reload only if compaction dropped it.

## For a cold reader

1. **Reader and task.** Name who reads this and what they need to do or decide. The opening lines say what the text is for.
2. **Answer first.** The point, the decision or the command comes before the background. A diff shows what changed; only prose says why and which alternative was rejected.
3. **Assume nothing from the conversation.** "As discussed" and "the earlier fix" mean nothing later; name the issue, file, command, error or decision. Spell out an acronym or requirement ID on first use; a bare `FR-23` needs a few words saying what it requires.
4. **Concrete and runnable.** Real commands, paths and values ("from 4 s to 300 ms", not "faster"), expected output where it helps, an example before the general rule.
5. **One kind of document.** A tutorial, a how-to, a reference or an explanation, never a mix. Link between them.
6. **Structure that carries meaning.** Headings shaped like the reader's tasks, numbered lists only for real sequences, tables for comparisons, a diagram only when it shows how something works. Prose for reasoning, causes and trade-offs.
7. **Maintainable.** Link to the source of truth instead of copying it, date decisions, and update the existing document instead of adding a near-duplicate.

## Against AI tells

- Plain words: "use", not "leverage" or "utilize". No "delve", "seamless" or "robust" without a stated property.
- Cut hedges and filler ("it's worth noting", "basically"), restated conclusions, false warmth, stock openers and sign-offs ("Great question", "Let me know if…").
- Keep only list items that carry information; no triplets for cadence. State Y directly instead of "not X, but Y".
- Use em-dashes and bold rarely. Vary sentence and paragraph length.

## Precedence

Comprehension comes first. Then technical precision ("ensure" for a real guarantee is fine), the reader's own terms, and formats other tools need, such as Conventional Commit syntax, spec markers and `Closes #N`. If removing a tell makes the text harder to follow, keep the clearer version.

## Short texts

For a commit message, issue or PR text, review note, comment, docstring or string in code, apply the points that fit the length: the reader, the answer first, concrete values, defined terms, a link to the source of truth. Skip the document kinds and the check below.

## Check

Before a document file goes to a reviewer, a commit, a PR or the user, reread it as the cold reader: every command runs or is marked not run, every link resolves, no `TODO` is left. For a substantial document, give a fresh subagent only the document and ask "can I now do X?", and fix where its answer differs from yours. Say in your report which documents you checked and which findings you left, with a reason.
