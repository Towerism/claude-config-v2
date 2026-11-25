---
name: session-handoff
description: Hand an OMC workflow off to a fresh session at a checkpoint (spec written, plan approved, execute done) or when a hook reports context past the handoff limit. Writes a handoff note and ends the turn; the handoff_stop hook then types /clear and a prompt naming the note into the session's tmux pane, so the fresh session continues with no keystroke. Use at those checkpoints only. Not for sessions outside tmux, nested claude -p runs, or while ralph or autopilot runs.
---

# Session handoff

A handoff replaces autocompaction with a clean break: this session writes a note, ends its turn, and the `handoff_stop` hook clears the session and types a prompt that tells the fresh session to read the note and run its next skill. Work through the steps in order; stop at the first one that says not to hand off, and carry on with the work.

## Steps

1. **Check that a handoff can complete.** Run `echo "pane=${TMUX_PANE-} entrypoint=${CLAUDE_CODE_ENTRYPOINT-}"`. Hand off only when it prints a pane id (like `pane=%3`) and `entrypoint=cli`. Why: the hook types `/clear` into that pane, and only in an interactive session; elsewhere nothing would clear the session and it would just stop. Background jobs also report `cli`, and their empty pane is what rules them out. Done when both values are printed, or you have decided not to hand off and continued the work.

2. **Check that no OMC run in this session would be lost.** Load the deferred tool with `ToolSearch("select:mcp__plugin_oh-my-claudecode_t__state_list_active")`, then call it with `session_id: "${CLAUDE_SESSION_ID}"`. Why the argument: without it the tool lists active modes across every session in the project, so another or a stale session's ralph would silently stop this handoff. If the tool is unavailable, an OMC continuation reminder in this turn is the signal instead.
   - ralph, autopilot, team or ultrapilot active: do not hand off. At a context-limit block, say in one line that the limit was reached inside that run, and continue. Why: OMC binds these runs to the session id, and ralph keeps its stories and feedback baseline per session, so a fresh session would start it over and lose the stories already passed.
   - ultragoal: hand off only between goals, with no `/goal` active, and name `ultragoal` resume as the next skill. Why: its ledger survives a new session, but an active `/goal` blocks the stop, so `/clear` would land during a forced continuation.
   - ralplan and deep-interview do not block a handoff: their checkpoints are step 3.
   Done when the tool (or the reminder) has shown which modes are active, and you have decided.

3. **Hand off only at a checkpoint.** A checkpoint is the point between two skills, before the next stage skill is invoked:
   - spec written: at deep-interview's execution bridge, instead of invoking the plan or execute skill;
   - plan approved: at ralplan's approval step, before it invokes ralph, team or execute, or where ralplan stops with the plan pending approval;
   - execute done: after a plain `execute` run, or a ralph or autopilot run, has finished, or an ultragoal goal has completed;
   - a hook block that names this skill;
   - you are asked to hand off, with the next step named or clear from the work.
   At a checkpoint, do not invoke the next skill: name it, with its arguments, as the note's next skill. Why: those skills chain into the next stage themselves, and a handoff after the chain would come too late to give the next stage a fresh context. Ralplan's review rounds run in this context, so there is no checkpoint during them. Done when you can name the checkpoint and the next skill.

4. **Write the note** to `${CLAUDE_PROJECT_DIR}/.omc/handoffs/${CLAUDE_SESSION_ID}.md`, under 10,000 characters, with:
   - the spec or plan path, the branch and the last commit;
   - the work done so far and the current step;
   - the next skill with its arguments;
   - decisions already settled, which the fresh session must not ask about again;
   - decisions still open.
   Why that path: the hook looks for a note under this session's id and project, and sends once per note. Done when the file exists.

5. **End the turn right after writing the note**, with one line saying a handoff is under way. Why: the hook acts when the turn ends; more work in this turn delays the clear. Done when the turn has ended.
