# The checker

Run this for a README, a wiki or design page, or a PR description written from sources, after the check in `SKILL.md`'s "Before you deliver" and before delivering. Why: a second agent that sees only the sources and the draft catches unsupported statements the writer misses.

1. Spawn the `oh-my-claudecode:verifier` agent with `model: sonnet` and this prompt, with every source the text draws on pasted verbatim in place of `{src}` (the fact list, or the parts of the diff, issue, conversation and tool output the text states facts from) and your draft in place of `{text}`:

   ```
   Sources the writer had:
   <<<
   {src}
   >>>

   Text the writer produced:
   <<<
   {text}
   >>>

   List each statement in the text that the sources do not support (a new fact, cause, reason, name, plan or test claim, or a claim stated more strongly than the sources state it), one per line with a short quote. If there are none, output exactly NONE.
   ```

2. If it lists statements, fix or remove each one that really is unsupported, in one round with no second check. Why: removing every listed statement outright turns a checker's false alarm into a dropped true fact.
3. If no agent can be spawned, skip the check and say so in your reply to the user, never in the delivered text.

Done when the checker answered NONE or its list has been worked through once.
